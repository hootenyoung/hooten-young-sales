---
name: new-endpoint
description: Scaffold a new FastAPI route in src/hy_analytics/api/. Activate when the user asks to "add an endpoint", "create a route", "expose X over HTTP", or names a new URL/path for the API.
---

# new-endpoint

Create a new FastAPI route following Hooten Young Analytics conventions.

## When to activate

- User asks to add / create / scaffold a new HTTP endpoint.
- User describes a feature in API terms ("expose the trend analysis as a GET", "add a webhook for ...").

## Conventions to follow

1. **Location** — `src/hy_analytics/api/routes/<resource>.py`. Group by resource (e.g. `posts.py`, `trends.py`, `accounts.py`), not by HTTP verb.
2. **Router pattern** — each module exposes an `APIRouter` named `router`. Include in `src/hy_analytics/api/__init__.py` via `app.include_router(...)`.
3. **Pydantic schemas** — request + response models live alongside the route in the same module, or in `src/hy_analytics/api/schemas/` if reused.
4. **Types required** — every handler has typed parameters and a typed return. No `dict`/`Any` in the public surface.
5. **Async by default** — handlers are `async def`. If a handler must be sync, justify in a docstring.
6. **DB sessions** — injected via dependency (`Annotated[AsyncSession, Depends(get_session)]`). Never instantiate a session inside a handler.
7. **Errors** — raise `HTTPException` for client errors; let unexpected exceptions bubble (a global handler maps them to 500 + structured log).
8. **OpenAPI** — include a `summary` and `description` on every handler. Tag by resource.
9. **Auth** — if the endpoint is non-public, use the project's auth dependency (TBD when auth lands). For now, document the assumption explicitly.

## Steps

1. Confirm the resource name and HTTP shape with the user if ambiguous.
2. Create the route module with the structure above.
3. Wire it into `src/hy_analytics/api/__init__.py`.
4. Create a sibling test file under `tests/api/test_<resource>.py` with at least one happy-path test using `httpx.AsyncClient` against `app`.
5. Update `docs/architecture.md` via `/sync-architecture` if the new route changes the surface meaningfully.
6. Report the created file paths and any new env vars / dependencies introduced.

## Template

```python
"""<Resource> endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from hy_analytics.api.deps import get_session

router = APIRouter(prefix="/<resource>", tags=["<resource>"])


class <Resource>Response(BaseModel):
    id: int


@router.get(
    "/{<resource>_id}",
    response_model=<Resource>Response,
    summary="Get a <resource> by ID",
)
async def get_<resource>(
    <resource>_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> <Resource>Response:
    """Detailed description of what this endpoint returns."""
    raise NotImplementedError
```
