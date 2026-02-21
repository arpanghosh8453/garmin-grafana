# syntax=docker/dockerfile:1
# check=skip=SecretsUsedInArgOrEnv

ARG PYTHON_VERSION=3.13
ARG DEBIAN_VERSION=bookworm

FROM ghcr.io/astral-sh/uv:0.6.17-python${PYTHON_VERSION}-${DEBIAN_VERSION}-slim AS build
ARG PYTHON_VERSION

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*
RUN uv sync --locked

FROM python:${PYTHON_VERSION}-slim-${DEBIAN_VERSION} AS runtime
ARG PYTHON_VERSION

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN groupadd --gid 1000 appuser && useradd --uid 1000 --gid appuser --shell /bin/bash --create-home appuser

COPY --chown=appuser:appuser --from=build /app/.venv /app/.venv
COPY --chown=appuser:appuser src /app/

USER appuser

CMD ["python", "garmin_grafana/garmin_fetch.py"]

FROM gcr.io/distroless/python3-debian13:nonroot AS distroless
ARG PYTHON_VERSION

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME="/home/nonroot" \
    TOKEN_DIR="/home/nonroot/.garminconnect" \
    PYTHONPATH="/app/.venv/lib/python${PYTHON_VERSION}/site-packages:/app"

WORKDIR /app

COPY --chown=nonroot:nonroot --from=build /app/.venv/lib/python${PYTHON_VERSION}/site-packages /app/.venv/lib/python${PYTHON_VERSION}/site-packages
COPY --chown=nonroot:nonroot src /app/

USER nonroot:nonroot

CMD ["/usr/bin/python3", "garmin_grafana/garmin_fetch.py"]
