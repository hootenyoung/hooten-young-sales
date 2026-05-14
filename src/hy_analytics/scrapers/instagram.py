"""Instagram scraper — Apify actor wrapper (placeholder).

TODO: Implement using the design opinions in ``.claude/agents/social-scraper.md``.
Specifically, invoke the ``social-scraper`` subagent before writing real code
to confirm:

- Which Apify actor to use (or an alternative provider).
- The normalized ``InstagramPost`` shape (fields, types, units).
- Pagination + rate-limit handling (tenacity + Retry-After).
- Raw payload archival path under ``gs://${GCS_BUCKET_RAW_MEDIA}/instagram/...``.
- Idempotent upsert key (Instagram media ``id``).

Once design is settled, follow the three-step separation: ``fetch()`` returns an
``AsyncIterator[InstagramPost]``, ``parse()`` normalizes raw payloads, and
``persist()`` upserts into Postgres.
"""
