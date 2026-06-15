"""Ingestion orchestration for the sales (QuickBooks invoices) domain.

The depletions side lives in ``services.depletions_ingestion`` — fully
isolated by schema (``sales`` vs ``depletions``), with no shared
helpers. Each domain owns its own resolution, upload ledger, and
idempotency machinery.

Idempotency:
  * SHA-256 dedup on ``sales.file_uploads`` — re-running on the same
    file is a no-op (returns the prior upload with
    ``status='skipped_duplicate'``).
  * Sales: upsert ``invoices`` by ``(source_system, invoice_ref)``;
    DELETE + INSERT lines under that invoice.

Per-run caches:
  Many invoice lines reference the same product, customer, and
  distributor. ``_Caches`` keeps these resolutions in memory for the
  duration of one ingestion call so we don't hit the DB once per line.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TypedDict

import structlog
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hy_sales.models import (
    Customer,
    CustomerAlias,
    Distributor,
    FileUpload,
    Invoice,
    InvoiceLine,
    Product,
    ProductAlias,
)
from hy_sales.parsers.canonical import ParsedSalesInvoice
from hy_sales.parsers.sales import parse_sales_xlsx
from hy_sales.services.customer_parser import parse_customer_name

logger = structlog.get_logger(__name__)


ProgressCallback = Callable[[int, int], None]

_PROGRESS_EVERY = 100


class UploadSummary(TypedDict):
    """Return value from ``ingest_sales_file``."""

    id: int
    filename: str
    sha256: str
    kind: str
    status: str
    row_count_processed: int
    row_count_inserted: int
    row_count_updated: int
    row_count_skipped: int
    row_count_failed: int


@dataclass
class _Caches:
    """In-memory caches scoped to a single sales-ingestion run.

    Cuts DB round-trips when many invoice lines reference the same
    product / customer / distributor.
    """

    product: dict[str, int] = field(default_factory=dict)
    customer: dict[str, int] = field(default_factory=dict)
    distributor: dict[str, int] = field(default_factory=dict)


# ----------------------------------------------------------------
# Public entry point
# ----------------------------------------------------------------


async def ingest_sales_file(
    session: AsyncSession,
    path: Path,
    source_system: str = "quickbooks",
    on_progress: ProgressCallback | None = None,
) -> UploadSummary:
    """Parse + ingest a QuickBooks sales xlsx file."""
    upload, is_new = await _get_or_create_upload(
        session, path, kind="sales", source_system=source_system
    )
    if not is_new:
        logger.info("upload.skip.duplicate", path=str(path), sha=upload.sha256)
        return _summary(upload, status="skipped_duplicate")

    invoices = parse_sales_xlsx(path)
    caches = _Caches()

    total = len(invoices)
    inserted = 0
    updated = 0
    failed = 0

    for i, parsed in enumerate(invoices, start=1):
        try:
            was_update = await _upsert_invoice(session, parsed, upload, source_system, caches)
            if was_update:
                updated += 1
            else:
                inserted += 1
        except Exception as exc:  # per-row failure must not abort the batch
            failed += 1
            logger.error(
                "invoice.ingest.fail",
                invoice_ref=parsed.invoice_ref,
                error=str(exc),
            )

        if on_progress is not None and (i % _PROGRESS_EVERY == 0 or i == total):
            on_progress(i, total)

    if invoices:
        dates = [inv.invoice_date for inv in invoices]
        upload.period_start = min(dates)
        upload.period_end = max(dates)

    _apply_counters(
        upload,
        processed=total,
        inserted=inserted,
        updated=updated,
        skipped=0,
        failed=failed,
    )
    upload.status = "success" if failed == 0 else "partial"
    upload.processed_at = datetime.now()
    await session.flush()

    return _summary(upload)


# ----------------------------------------------------------------
# Invoice upsert
# ----------------------------------------------------------------


async def _upsert_invoice(
    session: AsyncSession,
    parsed: ParsedSalesInvoice,
    upload: FileUpload,
    source_system: str,
    caches: _Caches,
) -> bool:
    """Upsert one invoice header and replace its lines.

    Returns True if the invoice header already existed (updated),
    False if newly inserted.
    """
    customer_id = await _resolve_customer(
        session,
        parsed.customer_raw_text,
        source_system,
        cache=caches.customer,
        distributor_cache=caches.distributor,
    )

    existing = await session.scalar(
        select(Invoice).where(
            Invoice.source_system == source_system,
            Invoice.invoice_ref == parsed.invoice_ref,
        )
    )

    if existing is None:
        invoice = Invoice(
            source_system=source_system,
            invoice_ref=parsed.invoice_ref,
            invoice_date=parsed.invoice_date,
            transaction_type=parsed.transaction_type,
            customer_id=customer_id,
            customer_raw_text=parsed.customer_raw_text,
            po_number=parsed.po_number,
            file_upload_id=upload.id,
        )
        session.add(invoice)
        await session.flush()
        was_update = False
    else:
        existing.invoice_date = parsed.invoice_date
        existing.transaction_type = parsed.transaction_type
        existing.customer_id = customer_id
        existing.customer_raw_text = parsed.customer_raw_text
        existing.po_number = parsed.po_number
        existing.file_upload_id = upload.id
        invoice = existing
        await session.execute(delete(InvoiceLine).where(InvoiceLine.invoice_id == invoice.id))
        await session.flush()
        was_update = True

    for line in parsed.lines:
        product_id = await _resolve_product(
            session,
            line.product_raw_text,
            cache=caches.product,
        )
        session.add(
            InvoiceLine(
                invoice_id=invoice.id,
                line_seq=line.line_seq,
                product_id=product_id,
                product_raw_text=line.product_raw_text,
                quantity=line.quantity,
                sales_price=line.sales_price,
                amount=line.amount,
                file_upload_id=upload.id,
            )
        )
    await session.flush()
    return was_update


# ----------------------------------------------------------------
# Alias / dimension resolution (cache-aware)
# ----------------------------------------------------------------


async def _resolve_product(
    session: AsyncSession,
    raw_text: str,
    cache: dict[str, int],
) -> int:
    """Return Product.id for ``raw_text``. Auto-create product + alias if missing."""
    if raw_text in cache:
        return cache[raw_text]

    alias = await session.scalar(select(ProductAlias).where(ProductAlias.alias_text == raw_text))
    if alias is not None:
        cache[raw_text] = alias.product_id
        return alias.product_id

    normalized = raw_text.strip()
    product = await session.scalar(
        select(Product).where(func.lower(Product.full_name) == normalized.lower())
    )

    if product is None:
        product = Product(full_name=normalized)
        session.add(product)
        await session.flush()

    session.add(
        ProductAlias(
            alias_text=raw_text,
            product_id=product.id,
            source="sales",
        )
    )
    await session.flush()
    cache[raw_text] = product.id
    return product.id


async def _resolve_customer(
    session: AsyncSession,
    raw_text: str,
    source_system: str,
    cache: dict[str, int],
    distributor_cache: dict[str, int],
) -> int | None:
    """Return customer.id for ``raw_text``, or None if raw is empty.

    On first sighting of a customer, runs ``parse_customer_name`` to
    populate ``state_code`` and link to (or auto-create) the parent
    ``distributor`` row with the right channel classification.
    """
    if not raw_text:
        return None
    if raw_text in cache:
        return cache[raw_text]

    alias = await session.scalar(select(CustomerAlias).where(CustomerAlias.alias_text == raw_text))
    if alias is not None:
        cache[raw_text] = alias.customer_id
        return alias.customer_id

    normalized = raw_text.strip()
    customer = await session.scalar(
        select(Customer).where(func.lower(Customer.canonical_name) == normalized.lower())
    )

    if customer is None:
        parsed = parse_customer_name(normalized)
        distributor_id: int | None = None
        if parsed.distributor_name:
            distributor_id = await _resolve_distributor_id_with_channel(
                session,
                name=parsed.distributor_name,
                channel=parsed.channel,
                cache=distributor_cache,
            )
        customer = Customer(
            canonical_name=normalized,
            state_code=parsed.state_code,
            distributor_id=distributor_id,
        )
        session.add(customer)
        await session.flush()

    session.add(
        CustomerAlias(
            alias_text=raw_text,
            customer_id=customer.id,
            source_system=source_system,
        )
    )
    await session.flush()
    cache[raw_text] = customer.id
    return customer.id


async def _resolve_distributor_id_with_channel(
    session: AsyncSession,
    *,
    name: str,
    channel: str,
    cache: dict[str, int],
) -> int:
    """Get or create a distributor by name, preferring the parsed channel.

    If the row already exists with the default ``'distributor'`` channel
    but we now know better (e.g. ``'control_state'``), upgrade it.
    """
    if name in cache:
        return cache[name]

    distributor = await session.scalar(select(Distributor).where(Distributor.name == name))
    if distributor is None:
        distributor = Distributor(name=name, channel=channel)
        session.add(distributor)
        await session.flush()
    elif distributor.channel == "distributor" and channel in ("control_state", "military"):
        distributor.channel = channel
        await session.flush()
    cache[name] = distributor.id
    return distributor.id


# ----------------------------------------------------------------
# Upload ledger helpers
# ----------------------------------------------------------------


async def _get_or_create_upload(
    session: AsyncSession,
    path: Path,
    *,
    kind: str,
    source_system: str,
) -> tuple[FileUpload, bool]:
    """Return ``(upload, is_new)``. ``is_new=False`` means previously succeeded."""
    sha = _sha256_of(path)
    existing = await session.scalar(select(FileUpload).where(FileUpload.sha256 == sha))

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

    upload = FileUpload(
        filename=path.name,
        sha256=sha,
        kind=kind,
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


def _apply_counters(
    upload: FileUpload,
    *,
    processed: int,
    inserted: int,
    updated: int,
    skipped: int,
    failed: int,
) -> None:
    upload.row_count_processed = processed
    upload.row_count_inserted = inserted
    upload.row_count_updated = updated
    upload.row_count_skipped = skipped
    upload.row_count_failed = failed


def _summary(upload: FileUpload, status: str | None = None) -> UploadSummary:
    return UploadSummary(
        id=upload.id,
        filename=upload.filename,
        sha256=upload.sha256,
        kind=upload.kind,
        status=status if status is not None else upload.status,
        row_count_processed=upload.row_count_processed,
        row_count_inserted=upload.row_count_inserted,
        row_count_updated=upload.row_count_updated,
        row_count_skipped=upload.row_count_skipped,
        row_count_failed=upload.row_count_failed,
    )
