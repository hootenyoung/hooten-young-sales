"""Business logic and ingestion orchestration.

Services sit between the parsers / API layer and the database, handling
upserts, alias resolution, and idempotency.
"""
