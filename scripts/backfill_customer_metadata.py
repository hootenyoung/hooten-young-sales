"""One-off backfill: populate state_code + distributor_id on existing customers.

The first ingestion runs (before parse_customer_name was wired into
_resolve_customer) created Customer rows with NULL state_code and
NULL distributor_id. This script parses each existing customer's
canonical_name and fills in those fields where the parser produces a
confident result.

Run once after deploying the customer_parser change:

    uv run python scripts/backfill_customer_metadata.py

Idempotent — safe to re-run. Only writes when a value changes.
"""

from __future__ import annotations

import asyncio
import sys
from collections import Counter

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hy_sales.db.engine import async_session_factory
from hy_sales.models import Customer, Distributor
from hy_sales.services.customer_parser import parse_customer_name


async def _resolve_distributor(
    session: AsyncSession,
    name: str,
    channel: str,
    cache: dict[str, int],
) -> int:
    if name in cache:
        return cache[name]
    distributor = await session.scalar(select(Distributor).where(Distributor.name == name))
    if distributor is None:
        distributor = Distributor(name=name, channel=channel)
        session.add(distributor)
        await session.flush()
    elif distributor.channel == "distributor" and channel in ("control_state", "military"):
        distributor.channel = channel
    cache[name] = distributor.id
    return distributor.id


async def backfill() -> int:
    async with async_session_factory() as session:
        customers = (await session.scalars(select(Customer))).all()
        distributor_cache: dict[str, int] = {}
        counters: Counter[str] = Counter()

        for customer in customers:
            counters["total"] += 1
            parsed = parse_customer_name(customer.canonical_name)

            updated = False
            if parsed.state_code and customer.state_code != parsed.state_code:
                customer.state_code = parsed.state_code
                updated = True
            if parsed.distributor_name and customer.distributor_id is None:
                distributor_id = await _resolve_distributor(
                    session,
                    parsed.distributor_name,
                    parsed.channel,
                    distributor_cache,
                )
                customer.distributor_id = distributor_id
                updated = True

            if updated:
                counters["updated"] += 1
                counters[f"channel.{parsed.channel}"] += 1
                if parsed.state_code:
                    counters["state.populated"] += 1
                else:
                    counters["state.unknown"] += 1
            else:
                counters["unchanged"] += 1

        await session.commit()

        print("Backfill complete.")
        print(f"  Total customers:    {counters['total']}")
        print(f"  Updated:            {counters['updated']}")
        print(f"  Unchanged:          {counters['unchanged']}")
        print(f"  State populated:    {counters['state.populated']}")
        print(f"  State left null:    {counters['state.unknown']}")
        for key, value in sorted(counters.items()):
            if key.startswith("channel."):
                print(f"  {key}: {value}")
        return counters["updated"]


def main() -> None:
    sys.exit(0 if asyncio.run(backfill()) >= 0 else 1)


if __name__ == "__main__":
    main()
