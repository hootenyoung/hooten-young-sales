# syntax=docker/dockerfile:1.7
#
# Multi-stage build for the hy-sales FastAPI service.
#
# Stage 1 (builder): use the official Astral uv image to resolve and
# install dependencies + the project itself into an isolated .venv.
#
# Stage 2 (runtime): copy the .venv + source onto a slim Python base.
# Runs as a non-root user. Listens on $PORT (Cloud Run sets it; defaults
# to 8000 locally).

# -----------------------------------------------------------------
# Builder
# -----------------------------------------------------------------
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Install deps first (cached layer when only source changes).
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Now install the project itself.
COPY src/ ./src/
COPY README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev


# -----------------------------------------------------------------
# Runtime
# -----------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

# Run as non-root.
RUN groupadd --system app && useradd --system --gid app --create-home app

WORKDIR /app

# Copy the prebuilt venv + source from the builder.
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --from=builder --chown=app:app /app/src /app/src

# Add venv to PATH so uvicorn etc. resolve.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_ENV=production

USER app
EXPOSE 8000

# Cloud Run injects $PORT (8080). Default to 8000 for local runs.
CMD ["sh", "-c", "exec uvicorn hy_sales.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
