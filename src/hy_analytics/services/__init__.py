"""Domain services.

Long-running or cross-cutting logic that doesn't fit cleanly in a route handler
or a scraper module: pattern analysis, embedding generation, competitor gap
analysis, insight publication.

Services should be thin orchestrators — push pure computation into ``utils/`` or
dedicated modules so services remain easy to test.
"""
