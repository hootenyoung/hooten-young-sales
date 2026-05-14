"""FastAPI application entrypoint.

Routers will be registered here as they are added under ``src/hy_analytics/api/routes/``.
Use the ``new-endpoint`` skill to scaffold new routes consistently.
"""

from fastapi import FastAPI

app = FastAPI(
    title="Hooten Young Analytics",
    version="0.1.0",
    description=(
        "Social + competitor intelligence engine. "
        "Internal API consumed by the hooten-young-dashboard repo."
    ),
)


@app.get("/health", tags=["meta"], summary="Liveness probe")
async def health() -> dict[str, str]:
    """Returns 200 if the process is up. Used by Cloud Run liveness checks."""
    return {"status": "ok"}
