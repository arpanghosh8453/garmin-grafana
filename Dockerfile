# syntax=docker/dockerfile:1

FROM ghcr.io/astral-sh/uv:0.6.17-python3.13-bookworm-slim AS build

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*
RUN uv sync --locked

FROM python:3.13-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN groupadd --gid 1000 appuser && useradd --uid 1000 --gid appuser --shell /bin/bash --create-home appuser

COPY --chown=appuser:appuser --from=build /app/.venv /app/.venv
COPY --chown=appuser:appuser src /app/

USER appuser

CMD ["python", "garmin_grafana/garmin_fetch.py"]
