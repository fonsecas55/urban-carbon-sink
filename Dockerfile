# syntax=docker/dockerfile:1.7
#
# Production image for the monthly CASA pipeline (Bloco 7).
#
# Multi-stage: a build stage resolves the LOCKED geospatial environment with uv
# (the same uv.lock validated live), a slim runtime stage carries only the .venv
# + source + baked baseline data/config. rasterio/pyproj/shapely come from
# manylinux wheels (GDAL bundled), but those wheels still dynamically link a few
# base C libs that python:3.12-slim omits (notably libexpat1) — installed below.
#
# The container is stateless and disposable: it is launched by the host cron,
# pulls S2/S3/DW/CAMS, computes, writes output/<region>.json + COG, and exits.

# ---- build -----------------------------------------------------------------
FROM python:3.12-slim AS build

# uv binary from its official image (pin to the version that produced uv.lock).
COPY --from=ghcr.io/astral-sh/uv:0.11.17 /uv /uvx /usr/local/bin/

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Layer 1 — dependencies only (cached until the lockfile changes).
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# Layer 2 — the package itself (changes most often).
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# ---- runtime ---------------------------------------------------------------
FROM python:3.12-slim AS runtime

# System libs the rasterio/GDAL manylinux wheels dynamically link but slim omits.
# libexpat1 is the one rasterio imports fail on; keep this list minimal.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libexpat1 \
    && rm -rf /var/lib/apt/lists/*

# Non-root user whose UID matches the WSL host (1000) so the bind-mounted
# output/ directory is writable and nothing runs as root.
RUN useradd --uid 1000 --create-home --shell /usr/sbin/nologin casa

WORKDIR /app

# venv + source from the build stage (both stages share /app, so the venv's
# interpreter shebangs stay valid).
COPY --from=build /app /app

# Baseline data + config baked in for reproducibility; either can still be
# overridden at runtime with a bind mount (see docker-compose.yml).
COPY data ./data
COPY config ./config

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER casa

# Entrypoint is the CLI; the cron wrapper appends `run --online ...`.
ENTRYPOINT ["casa"]
CMD ["--help"]
