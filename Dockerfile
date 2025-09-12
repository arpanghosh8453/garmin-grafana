# syntax=docker/dockerfile:1.7

############################
# STAGE 1: build deps
############################
FROM ghcr.io/astral-sh/uv:0.6.17-python3.13-bookworm-slim AS build

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Only copy lockfiles first to maximize layer cache reuse
COPY pyproject.toml uv.lock ./

# Install toolchain only for building wheels; remove apt lists afterwards
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential binutils \
 && rm -rf /var/lib/apt/lists/*


RUN uv sync --locked --no-dev --no-install-project \
 && rm -rf /root/.cache

COPY src ./src

############################
# STAGE 2: runtime
############################
# Distroless python is smaller than python:slim, but has no shell.
FROM python:3.13-slim-bookworm AS runtime

# Make sure Python finds the venv first
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Copy venv and sources with correct ownership in one go (no extra chown layer)
COPY --chown=nonroot:nonroot --from=build /app/.venv /app/.venv
COPY --chown=nonroot:nonroot --from=build /app/src /app/src

# Distroless already runs as nonroot
CMD ["python", "src/garmin_grafana/garmin_fetch.py"]
