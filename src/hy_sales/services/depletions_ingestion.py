"""Ingestion orchestration for the depletions domain only.

Physically isolated from the sales-side ingestion in
``services.ingestion`` — different schema (``depletions``), different
models (``Dep*``), different upload ledger
(``depletions.file_uploads``). The two services never touch each
other's rows.

Idempotency:

* SHA-256 dedup on ``depletions.file_uploads`` — re-running on the same
  file is a no-op (returns the prior upload with
  ``status='skipped_duplicate'``).
* Postgres ``INSERT ... ON CONFLICT DO UPDATE`` against
  ``uq_dep_facts_natural`` ``(account_id, product_id, period_month)``,
  gated by a WHERE that makes unchanged values a true no-op (no write,
  prior ``file_upload_id`` preserved).

Throughput strategy:
  Per-row INSERTs over ~130k facts are network-latency bound (one
  round-trip per row). This module batches in three phases:

    1. Pre-resolve every unique product in ONE round-trip (SELECT then
       a single multi-row INSERT for new ones).
    2. Pre-resolve every unique account by natural key the same way,
       updating the secondary fields of existing rows in one
       in-memory pass.
    3. Stream the fact rows through ``pg_insert(...).values([batch])
       .on_conflict_do_update(...)`` in chunks of ``_FACT_BATCH``,
       reducing 130k round-trips to ~260.

  For a 130k-row file this drops wall time from minutes to seconds and
  there is no thread-safety to worry about — one async session, one
  transaction, one writer.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, TypedDict

import structlog
from sqlalchemy import and_, func, literal_column, or_, select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from hy_sales.models import (
    DepAccount,
    DepFact,
    DepFileUpload,
    DepProduct,
    DepProductAlias,
)
from hy_sales.parsers.canonical import ParsedDepletionRow
from hy_sales.parsers.depletions import parse_depletions_xlsx

logger = structlog.get_logger(__name__)


ProgressCallback = Callable[[int, int], None]

# Rows per multi-row INSERT to the facts table. 500 keeps the parameter
# count well under Postgres' 65535 cap (6 cols x 500 = 3000) while
# giving one statement enough work that round-trip latency is amortized.
_FACT_BATCH = 500

# How often the row loops call the progress callback.
_PROGRESS_EVERY = 5000


class DepUploadSummary(TypedDict):
    """Return value from ``ingest_depletions_file``."""

    id: int
    filename: str
    sha256: str
    status: str
    row_count_processed: int
    row_count_inserted: int
    row_count_updated: int
    row_count_skipped: int
    row_count_failed: int


# Natural-key tuple for an account: (name, address, state_code).
AccountKey = tuple[str, str | None, str | None]


@dataclass
class _AccountFields:
    """Secondary fields collected from the source file for one account."""

    city: str | None = None
    county: str | None = None
    zip_code: str | None = None
    dist_state_code: str | None = None
    distributor_code: str | None = None


# ----------------------------------------------------------------
# Public entry point
# ----------------------------------------------------------------


async def ingest_depletions_file(
    session: AsyncSession,
    path: Path,
    source_system: str = "idig",
    on_progress: ProgressCallback | None = None,
) -> DepUploadSummary:
    """Parse + bulk-ingest a depletions xlsx into the ``depletions`` schema."""
    upload, is_new = await _get_or_create_upload(session, path, source_system=source_system)
    if not is_new:
        logger.info("dep_upload.skip.duplicate", path=str(path), sha=upload.sha256)
        return _summary(upload, status="skipped_duplicate")

    rows = parse_depletions_xlsx(path)
    total = len(rows)

    if total == 0:
        upload.status = "success"
        upload.processed_at = datetime.now()
        await session.flush()
        return _summary(upload)

    # PHASE 1: bulk product resolution.
    product_id_by_raw = await _bulk_resolve_products(session, rows)

    # PHASE 2: bulk account resolution.
    account_id_by_key = await _bulk_resolve_accounts(session, rows)

    # PHASE 3: batched fact upsert.
    inserted, updated, skipped, failed = await _bulk_upsert_facts(
        session,
        rows,
        product_id_by_raw=product_id_by_raw,
        account_id_by_key=account_id_by_key,
        upload_id=upload.id,
        on_progress=on_progress,
    )

    dates = [r.period_month for r in rows]
    upload.period_start = min(dates)
    upload.period_end = max(dates)
    upload.row_count_processed = total
    upload.row_count_inserted = inserted
    upload.row_count_updated = updated
    upload.row_count_skipped = skipped
    upload.row_count_failed = failed
    upload.status = "success" if failed == 0 else "partial"
    upload.processed_at = datetime.now()
    await session.flush()

    return _summary(upload)


# ----------------------------------------------------------------
# Phase 1 — bulk product resolution
# ----------------------------------------------------------------


async def _bulk_resolve_products(
    session: AsyncSession,
    rows: list[ParsedDepletionRow],
) -> dict[str, int]:
    """Return ``{raw_text -> DepProduct.id}`` for every product in ``rows``.

    Two queries total (best case): one SELECT of existing aliases, one
    multi-row INSERT for the new ones. Aliases are created with
    ``source='idig'``.
    """
    raw_texts = {r.product_raw_text for r in rows if r.product_raw_text}
    if not raw_texts:
        return {}

    existing_aliases = (
        await session.execute(
            select(DepProductAlias.alias_text, DepProductAlias.product_id).where(
                DepProductAlias.alias_text.in_(raw_texts)
            )
        )
    ).all()
    out: dict[str, int] = {a.alias_text: a.product_id for a in existing_aliases}

    unresolved = raw_texts - out.keys()
    if not unresolved:
        return out

    # For each unresolved raw, check if a product with that canonical
    # name already exists (case-insensitive) before inserting a new one.
    existing_products = (
        await session.execute(
            select(DepProduct.id, DepProduct.full_name).where(
                func.lower(DepProduct.full_name).in_({t.strip().lower() for t in unresolved})
            )
        )
    ).all()
    canonical_id_by_lower = {p.full_name.lower(): p.id for p in existing_products}

    new_products: list[dict[str, Any]] = []
    to_alias: list[tuple[str, int | None]] = []
    pending_names: list[str] = []
    for raw in unresolved:
        normalized = raw.strip()
        cid = canonical_id_by_lower.get(normalized.lower())
        if cid is not None:
            to_alias.append((raw, cid))
        else:
            # Multiple raws may normalize to the same canonical name —
            # only insert the product once per canonical name.
            if normalized.lower() not in {n.lower() for n in pending_names}:
                pending_names.append(normalized)
                new_products.append({"full_name": normalized})
            to_alias.append((raw, None))

    if new_products:
        inserted_rows = (
            await session.execute(
                pg_insert(DepProduct).values(new_products).returning(
                    DepProduct.id, DepProduct.full_name
                )
            )
        ).all()
        for row in inserted_rows:
            canonical_id_by_lower[row.full_name.lower()] = row.id

    alias_rows: list[dict[str, Any]] = []
    for raw, cid in to_alias:
        resolved_id = cid if cid is not None else canonical_id_by_lower[raw.strip().lower()]
        alias_rows.append({"alias_text": raw, "product_id": resolved_id, "source": "idig"})
        out[raw] = resolved_id

    if alias_rows:
        await session.execute(pg_insert(DepProductAlias).values(alias_rows))

    return out


# ----------------------------------------------------------------
# Phase 2 — bulk account resolution
# ----------------------------------------------------------------


async def _bulk_resolve_accounts(
    session: AsyncSession,
    rows: list[ParsedDepletionRow],
) -> dict[AccountKey, int]:
    """Return ``{(name, address, state_code) -> DepAccount.id}``.

    Refreshes secondary fields (city, county, zip, dist_state_code,
    distributor_code) on existing accounts when the parsed file carries
    new values. Inserts missing accounts in one multi-row INSERT.
    """
    fields_by_key: dict[AccountKey, _AccountFields] = {}
    for r in rows:
        key: AccountKey = (r.account_name, r.account_address, r.state_code)
        if key not in fields_by_key:
            fields_by_key[key] = _AccountFields(
                city=r.account_city,
                county=r.account_county,
                zip_code=r.account_zip,
                dist_state_code=r.dist_state_code,
                distributor_code=r.distributor_code,
            )

    out: dict[AccountKey, int] = {}

    # SELECT every account whose natural key matches one of the parsed
    # keys. Postgres tuple-IN with mixed NULLs is finicky, so we split
    # the IN list into key groups where all components are non-NULL and
    # OR-merge a handful of explicit IS-NULL predicates for the rest.
    fully_specified = [k for k in fields_by_key if k[1] is not None and k[2] is not None]
    rest = [k for k in fields_by_key if k not in fully_specified]

    predicates: list[Any] = []
    if fully_specified:
        predicates.append(
            tuple_(DepAccount.name, DepAccount.address, DepAccount.state_code).in_(fully_specified)
        )
    for name, address, state_code in rest:
        clauses = [DepAccount.name == name]
        clauses.append(
            DepAccount.address.is_(None) if address is None else DepAccount.address == address
        )
        clauses.append(
            DepAccount.state_code.is_(None)
            if state_code is None
            else DepAccount.state_code == state_code
        )
        predicates.append(and_(*clauses))

    existing_rows: list[DepAccount] = []
    if predicates:
        existing_rows = list(
            (await session.scalars(select(DepAccount).where(or_(*predicates)))).all()
        )

    existing_by_key: dict[AccountKey, DepAccount] = {
        (acc.name, acc.address, acc.state_code): acc for acc in existing_rows
    }

    # Refresh secondary fields on existing accounts where the parsed
    # row carries a value that differs from what's stored. ORM-tracked
    # attribute changes get bundled into one UPDATE batch on flush.
    for key, acc in existing_by_key.items():
        fields = fields_by_key.get(key)
        if fields is None:
            continue
        if fields.city is not None and acc.city != fields.city:
            acc.city = fields.city
        if fields.county is not None and acc.county != fields.county:
            acc.county = fields.county
        if fields.zip_code is not None and acc.zip_code != fields.zip_code:
            acc.zip_code = fields.zip_code
        if fields.dist_state_code is not None and acc.dist_state_code != fields.dist_state_code:
            acc.dist_state_code = fields.dist_state_code
        if fields.distributor_code is not None and acc.distributor_code != fields.distributor_code:
            acc.distributor_code = fields.distributor_code
        out[key] = acc.id

    # Insert the missing accounts in one shot.
    to_insert: list[dict[str, Any]] = []
    missing_keys: list[AccountKey] = []
    for key, fields in fields_by_key.items():
        if key in existing_by_key:
            continue
        name, address, state_code = key
        to_insert.append(
            {
                "name": name,
                "address": address,
                "state_code": state_code,
                "city": fields.city,
                "county": fields.county,
                "zip_code": fields.zip_code,
                "dist_state_code": fields.dist_state_code,
                "distributor_code": fields.distributor_code,
            }
        )
        missing_keys.append(key)

    if to_insert:
        inserted_rows = (
            await session.execute(
                pg_insert(DepAccount)
                .values(to_insert)
                .returning(
                    DepAccount.id,
                    DepAccount.name,
                    DepAccount.address,
                    DepAccount.state_code,
                )
            )
        ).all()
        for row in inserted_rows:
            out[(row.name, row.address, row.state_code)] = row.id

    # Flush ORM-tracked refreshes + ensure any RETURNING-bound rows are
    # committed to the session identity map.
    await session.flush()
    return out


# ----------------------------------------------------------------
# Phase 3 — batched fact upsert
# ----------------------------------------------------------------


async def _bulk_upsert_facts(
    session: AsyncSession,
    rows: list[ParsedDepletionRow],
    *,
    product_id_by_raw: dict[str, int],
    account_id_by_key: dict[AccountKey, int],
    upload_id: int,
    on_progress: ProgressCallback | None,
) -> tuple[int, int, int, int]:
    """UPSERT facts in chunks of ``_FACT_BATCH``.

    Returns ``(inserted, updated, skipped, failed)``.

    Three-way classification works via Postgres MVCC semantics:
      * INSERT-path rows: ``xmax = 0`` (no concurrent supersede)
      * UPDATE-path rows: ``xmax`` set to current txid
      * Rows filtered by the DO-UPDATE WHERE clause: not in RETURNING

    DEDUPLICATION
      Postgres rejects an ``INSERT ... ON CONFLICT DO UPDATE`` that
      would touch the same conflict-target row twice in one statement
      (PG error 21000, "ON CONFLICT DO UPDATE command cannot affect row
      a second time"). Some iDIG exports contain fully-identical
      duplicate rows for the same (account, product, month) — observed
      ~2,820 such pairs in the June 2026 file. We collapse duplicates
      here by ``(account_id, product_id, period_month)``, last-wins.
      The collapsed rows count as ``skipped`` so the per-upload counters
      still sum to ``row_count_processed``.

    SAVEPOINTS
      Each batch runs inside ``session.begin_nested()`` so a future
      unexpected batch error (FK miss, bad data) can't poison the
      outer transaction and cascade into "current transaction is
      aborted" on every later statement.
    """
    total_input = len(rows)
    inserted = 0
    updated = 0
    skipped = 0
    failed = 0

    # Resolve every parsed row to its (account_id, product_id) and
    # collapse exact duplicates by upsert natural key. Last write wins.
    resolved_by_key: dict[tuple[int, int, Any], dict[str, Any]] = {}
    for parsed in rows:
        account_id = account_id_by_key.get(
            (parsed.account_name, parsed.account_address, parsed.state_code)
        )
        product_id = product_id_by_raw.get(parsed.product_raw_text)
        if account_id is None or product_id is None:
            failed += 1
            logger.error(
                "dep_fact.resolve_miss",
                account=parsed.account_name,
                product=parsed.product_raw_text,
            )
            continue
        key = (account_id, product_id, parsed.period_month)
        resolved_by_key[key] = {
            "account_id": account_id,
            "product_id": product_id,
            "period_month": parsed.period_month,
            "cases_9l": parsed.cases_9l,
            "cases_physical": parsed.cases_physical,
            "file_upload_id": upload_id,
        }

    duplicates_collapsed = total_input - failed - len(resolved_by_key)
    if duplicates_collapsed > 0:
        skipped += duplicates_collapsed
        logger.info(
            "dep_fact.dedupe.collapsed",
            count=duplicates_collapsed,
            note="identical duplicate rows in source; last-write-wins",
        )

    values_all = list(resolved_by_key.values())
    seen = 0
    for batch in _chunked(values_all, _FACT_BATCH):
        try:
            async with session.begin_nested():
                batch_inserted, batch_updated = await _upsert_facts_batch(session, batch)
            inserted += batch_inserted
            updated += batch_updated
            skipped += len(batch) - batch_inserted - batch_updated
        except Exception as exc:
            failed += len(batch)
            logger.error("dep_fact.batch.fail", size=len(batch), error=str(exc))

        seen += len(batch)
        if on_progress is not None:
            on_progress(seen, len(values_all))

    return inserted, updated, skipped, failed


async def _upsert_facts_batch(
    session: AsyncSession,
    values: list[dict[str, Any]],
) -> tuple[int, int]:
    """Run one multi-row UPSERT and return ``(inserted, updated)`` counts."""
    insert_stmt = pg_insert(DepFact).values(values)
    upsert_stmt = insert_stmt.on_conflict_do_update(
        index_elements=["account_id", "product_id", "period_month"],
        set_={
            "cases_9l": insert_stmt.excluded.cases_9l,
            "cases_physical": insert_stmt.excluded.cases_physical,
            "file_upload_id": insert_stmt.excluded.file_upload_id,
            "updated_at": func.now(),
        },
        where=(
            (DepFact.cases_9l.is_distinct_from(insert_stmt.excluded.cases_9l))
            | (DepFact.cases_physical.is_distinct_from(insert_stmt.excluded.cases_physical))
        ),
    )
    returning_stmt: Any = upsert_stmt.returning(literal_column("xmax = 0").label("inserted"))
    result_rows = (await session.execute(returning_stmt)).all()

    inserted = sum(1 for r in result_rows if r.inserted)
    updated = sum(1 for r in result_rows if not r.inserted)
    return inserted, updated


def _chunked[T](items: list[T], size: int) -> Iterator[list[T]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


# ----------------------------------------------------------------
# Upload ledger helpers
# ----------------------------------------------------------------


async def _get_or_create_upload(
    session: AsyncSession,
    path: Path,
    *,
    source_system: str,
) -> tuple[DepFileUpload, bool]:
    """Return ``(upload, is_new)``. ``is_new=False`` means previously succeeded."""
    sha = _sha256_of(path)
    existing = await session.scalar(select(DepFileUpload).where(DepFileUpload.sha256 == sha))

    if existing is not None and existing.status == "success":
        return existing, False

    if existing is not None:
        existing.status = "processing"
        existing.error_message = None
        existing.row_count_processed = 0
        existing.row_count_inserted = 0
        existing.row_count_updated = 0
        existing.row_count_skipped = 0
        existing.row_count_failed = 0
        await session.flush()
        return existing, True

    upload = DepFileUpload(
        filename=path.name,
        sha256=sha,
        source_system=source_system,
        status="processing",
    )
    session.add(upload)
    await session.flush()
    return upload, True


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _summary(upload: DepFileUpload, status: str | None = None) -> DepUploadSummary:
    return DepUploadSummary(
        id=upload.id,
        filename=upload.filename,
        sha256=upload.sha256,
        status=status if status is not None else upload.status,
        row_count_processed=upload.row_count_processed,
        row_count_inserted=upload.row_count_inserted,
        row_count_updated=upload.row_count_updated,
        row_count_skipped=upload.row_count_skipped,
        row_count_failed=upload.row_count_failed,
    )


__all__ = ["DepUploadSummary", "ProgressCallback", "ingest_depletions_file"]
