"""Ingestion CLI — one-time-or-occasional manual ingestion of xlsx files.

Usage::

    uv run hy-sales-ingest sales      <path-to-sales.xlsx>
    uv run hy-sales-ingest depletions <path-to-depletions.xlsx>

The CLI is intentionally thin — it parses args, hands off to the
``services.ingestion`` module, prints a JSON summary, and sets a
non-zero exit code on failure. The future HTTP upload endpoint will
import the same service functions.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import structlog

from hy_sales.db.engine import async_session_factory
from hy_sales.services.ingestion import (
    UploadSummary,
    ingest_depletions_file,
    ingest_sales_file,
)

logger = structlog.get_logger(__name__)


def _progress(done: int, total: int) -> None:
    """Print a one-line progress update to stderr (keeps stdout clean for the JSON summary)."""
    print(f"  [{done:>5} / {total}] rows ingested", file=sys.stderr, flush=True)


async def _run(kind: str, path: Path) -> int:
    if not path.exists():
        print(f"Error: file not found: {path}", file=sys.stderr)
        return 2

    print(f"Parsing {path.name}...", file=sys.stderr, flush=True)

    async with async_session_factory() as session:
        try:
            if kind == "sales":
                summary: UploadSummary = await ingest_sales_file(
                    session, path, on_progress=_progress
                )
            else:  # kind == "depletions"
                summary = await ingest_depletions_file(session, path, on_progress=_progress)
            await session.commit()
        except Exception as exc:
            await session.rollback()
            print(f"Error: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1

    print(json.dumps(dict(summary), indent=2, default=str))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="hy-sales-ingest",
        description=(
            "Ingest a Hooten Young sales or depletions xlsx file into the "
            "configured Postgres database (DATABASE_URL)."
        ),
    )
    parser.add_argument(
        "kind",
        choices=["sales", "depletions"],
        help="Type of file being ingested.",
    )
    parser.add_argument(
        "path",
        # expanduser handles ~/... even when the user quotes the whole path,
        # which prevents the shell from expanding the tilde.
        type=lambda s: Path(s).expanduser(),
        help="Path to the xlsx file.",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(_run(args.kind, args.path)))


if __name__ == "__main__":
    main()
