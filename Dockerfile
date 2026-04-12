# syntax=docker/dockerfile:1

FROM ghcr.io/astral-sh/uv:0.6.17-python3.13-bookworm-slim AS build

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
# Pure-Python wheels are available for all pinned deps on Python 3.13, so
# build-essential is no longer required -> smaller/faster build.
RUN uv sync --locked

FROM python:3.13-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

RUN groupadd --gid 1000 appuser && useradd --uid 1000 --gid appuser --shell /bin/bash --create-home appuser

COPY --chown=appuser:appuser --from=build /app/.venv /app/.venv
COPY --chown=appuser:appuser src /app/src

ENV PYTHONPATH=/app/src

USER appuser

# Run as a module so ``if __name__ == "__main__": main()`` is executed and the
# package layout stays clean (matches ``uv run garmin-fetch`` behaviour).
CMD ["python", "-m", "garmin_grafana.garmin_fetch"]
