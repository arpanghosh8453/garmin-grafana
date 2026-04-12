# CLAUDE.md

This file gives guidance to Claude Code (claude.ai/code) when working with this repository.

## Project overview

`garmin-grafana` is a Python application that fetches health and activity data from Garmin Connect and writes it into an InfluxDB database (v1.x or v3) so the data can be visualized in Grafana via a provided dashboard. It is primarily distributed as a Docker image and run alongside InfluxDB + Grafana through `compose-example.yml`, but can also be run locally with `uv` or deployed via the Helm chart in `k8s/`.

- Language: Python 3.13 (pinned in `.python-version` and `pyproject.toml`)
- Package manager: [`uv`](https://docs.astral.sh/uv/) (see `uv.lock`)
- Runtime entry point: `src/garmin_grafana/garmin_fetch.py`
- Package name: `garmin_grafana` (src layout), console script `garmin-fetch`

## Repository layout

```
src/garmin_grafana/
  garmin_fetch.py            # Main long-running fetch loop; reads env vars, logs into Garmin,
                             # pulls daily stats/activities, writes points to InfluxDB v1 or v3.
  garmin_bulk_importer.py    # One-shot bulk backfill of historical Garmin data.
  fit_activity_importer.py   # Parses .fit activity files (via fitparse) into InfluxDB points.
  influxdb_exporter.py       # Helper to export data out of InfluxDB.
  __init__.py                # Exposes `main()` which imports garmin_fetch (used by console script).

Extra/
  garmin-fetch.ipynb         # Notebook form of the fetch script (kept in sync manually).
  Garmin-Grafana-Logo.svg

Grafana_Dashboard/
  Garmin-Grafana-Dashboard.json   # Main Grafana dashboard definition (imported via provisioning).
  Garmin-Grafana-Dashboard.yaml   # Grafana dashboard provisioning config.
  Garmin-Grafana-Dashboard-Preview.png

Grafana_Datasource/
  influxdb.yaml              # Grafana datasource provisioning config for InfluxDB.

k8s/                         # Helm chart (Chart.yaml, values.yaml, templates/, Makefile)
docs/manual-import-instructions.md
.github/workflows/           # CI: codeberg-sync, prod.push (Docker image), version.release
Dockerfile                   # Multi-stage build: uv sync -> python:3.13-slim runtime
compose-example.yml          # Reference docker-compose stack (fetcher + InfluxDB + Grafana)
kubernetes-spec-example.yaml
easy-install.sh              # Convenience installer script
pyproject.toml / uv.lock     # Python deps
```

## Common commands

All commands assume the repo root as working directory. On Windows use Git Bash / PowerShell equivalents.

### Local development (uv)

```bash
# Install/refresh the locked environment
uv sync --locked

# Run the main fetcher (requires env vars, see below)
uv run python src/garmin_grafana/garmin_fetch.py

# Run the bulk historical importer
uv run python src/garmin_grafana/garmin_bulk_importer.py

# Run the FIT file importer
uv run python src/garmin_grafana/fit_activity_importer.py

# Use the installed console script (after `uv sync`)
uv run garmin-fetch
```

There is currently **no test suite, linter, or formatter configured** in `pyproject.toml`. Do not invent commands like `pytest` / `ruff` / `black` unless the user adds them; instead, run the scripts directly and inspect logs.

### Docker / Compose

```bash
# Build the image locally
docker build -t garmin-grafana:dev .

# Bring up the full stack (fetcher + InfluxDB + Grafana)
docker compose -f compose-example.yml up -d

# Tail fetcher logs
docker compose -f compose-example.yml logs -f garmin-fetch-data
```

The published image is `thisisarpanghosh/garmin-fetch-data:latest` (built by `.github/workflows/prod.push.yml`).

### Kubernetes / Helm

```bash
# From k8s/
make           # See k8s/Makefile for available targets
helm install garmin-grafana ./k8s -f ./k8s/values.yaml
```

## Configuration model

`garmin_fetch.py` is configured **entirely through environment variables** (read near the top of the file with `os.getenv(...)`). A local `override-default-vars.env` file, if present in the working directory, is loaded via `dotenv.load_dotenv(..., override=True)` and will override system env vars — useful for local dev.

Key variables (non-exhaustive; see `compose-example.yml` and README for the full list):

- `INFLUXDB_VERSION` — `1` (default, recommended) or `3`
- `INFLUXDB_HOST`, `INFLUXDB_PORT`, `INFLUXDB_DATABASE`
- `INFLUXDB_USERNAME`, `INFLUXDB_PASSWORD` (v1 only)
- `INFLUXDB_V3_ACCESS_TOKEN` (v3 only; also needs the `org` parameter — see commit c200d44)
- `GARMINCONNECT_EMAIL`, `GARMINCONNECT_BASE64_PASSWORD` (optional; tokens are otherwise cached)
- `GARMINCONNECT_IS_CN` — set `True` for Garmin China
- Garmin tokens are persisted to `~/.garminconnect` (mounted as `./garminconnect-tokens` in Compose, owned by uid/gid 1000 to match the Dockerfile's `appuser`).

When adding new config, follow the existing pattern: read with `os.getenv("NAME", default)`, document it in `compose-example.yml`, and (if user-facing) in `README.md`.

## Architecture notes

- **Single long-running loop**: `garmin_fetch.py` authenticates once (re-using cached Garth tokens), then periodically pulls daily summaries, sleep, stress, HR, activities, body battery, VO2 max, HR zones, etc., converting each dataset into InfluxDB points. Both v1 (`influxdb.InfluxDBClient`) and v3 (`influxdb_client_3.InfluxDBClient3`) clients are supported behind an `INFLUXDB_VERSION` switch.
- **Activity parsing**: raw `.fit` files from Garmin are parsed with `fitparse` in `fit_activity_importer.py`; `garmin_bulk_importer.py` orchestrates historical backfills.
- **Grafana side is provisioning-only**: the repo does not run Grafana itself; `Grafana_Dashboard/*.yaml` and `Grafana_Datasource/influxdb.yaml` are dropped into Grafana's provisioning directories (see `compose-example.yml` volume mounts) so the dashboard and datasource appear automatically on first boot.
- **Dashboard edits**: the source of truth for dashboard changes is `Grafana_Dashboard/Garmin-Grafana-Dashboard.json`. Prefer exporting from Grafana and committing the full JSON rather than hand-editing unless the change is small and localized. Recent HR-zone coloring work (commit 5e89e00) shows the expected pattern: update both the Python producer (so the field exists in InfluxDB) and the dashboard JSON (so panels consume it).
- **Notebook mirror**: `Extra/garmin-fetch.ipynb` mirrors `garmin_fetch.py` for users who prefer notebooks. It is maintained manually — if you change behavior in the script, call it out so the notebook can be updated, but do not attempt to auto-regenerate it.

## Contribution conventions

- See `.github/CONTRIBUTING.md` for the project's contribution rules.
- Commit messages in history are short, imperative, and frequently reference issue/PR numbers (e.g., `Fix syntaxerror (missing comma) (Fix #241)`). Match that style.
- The Dockerfile copies `src/` into `/app/`, so keep the package importable as `garmin_grafana.*` and avoid adding top-level modules outside `src/garmin_grafana/`.
- Dependencies are pinned in `pyproject.toml`; after changing them, run `uv lock` (or `uv sync`) so `uv.lock` stays in sync — CI builds depend on it (`uv sync --locked` in the Dockerfile).
