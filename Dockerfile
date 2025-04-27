FROM ghcr.io/astral-sh/uv:0.6.17-python3.13-bookworm-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt update && apt install build-essential -y

COPY garmin-fetch.py /app/
COPY pyproject.toml /app/
COPY uv.lock /app/

WORKDIR /app
RUN uv sync --locked

RUN groupadd --gid 1000 appuser && useradd --uid 1000 --gid appuser --shell /bin/bash --create-home appuser && chown -R appuser:appuser /app
USER appuser

CMD ["uv", "run", "garmin-fetch.py"]