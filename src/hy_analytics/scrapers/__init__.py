"""Per-platform ingestion adapters.

Each platform lives in its own module (e.g. ``instagram.py``). Modules implement
the ``ScraperProtocol`` interface (to be added in ``base.py`` when the first
real scraper lands) so providers and platforms are interchangeable from the
caller's perspective.

Use the ``new-scraper`` skill to scaffold a new platform adapter — it consults
the ``social-scraper`` subagent for design opinions before writing code.
"""
