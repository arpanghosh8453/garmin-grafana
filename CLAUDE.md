# garmin-grafana — Claude Code Instructions

## Project Overview

A Python application that fetches health data from **Garmin Connect** and stores it in a local **InfluxDB** database for visualization with **Grafana**. Runs as a Docker container stack.

## Stack

- **Python 3.13** with `uv` as the package manager
- **InfluxDB 1.11** (recommended) or InfluxDB 3.x (supported)
- **Grafana** with the `marcusolsson-hourly-heatmap-panel` plugin
- **Docker + Docker Compose** (multistage build)

## Project Structure

```
src/garmin_grafana/
  garmin_fetch.py          # Main script — periodic fetch and bulk update
  garmin_bulk_importer.py  # Import from Garmin Connect local export files
  fit_activity_importer.py # .FIT file parser
  influxdb_exporter.py     # Export data to CSV files
Grafana_Datasource/        # Auto-provisioning datasource config
Grafana_Dashboard/         # Dashboard JSON for auto-provisioning
k8s/                       # Helm chart for Kubernetes
```

## Key Commands

```bash
# Start the full stack
docker compose up -d

# Follow logs in real time
docker compose logs --follow

# Initial login (generates Garmin OAuth tokens)
docker compose run --rm garmin-fetch-data

# Bulk update historical data
docker compose run --rm \
  -e MANUAL_START_DATE=YYYY-MM-DD \
  -e MANUAL_END_DATE=YYYY-MM-DD \
  garmin-fetch-data

# Install dependencies locally
uv sync

# Export data to CSV
docker exec garmin-fetch-data python /app/garmin_grafana/influxdb_exporter.py --last-n-days=30
```

## Code Conventions

- Configuration constants in `UPPER_CASE`, read via `os.getenv()` with defaults
- Supports `override-default-vars.env` file to override system ENV vars
- Functions in `snake_case`; procedural style (not OO), except in bulk importer
- Logging via Python's standard `logging` module
- No type hints or docstrings in the current codebase — maintain consistency
- No linter/formatter configured — follow the existing code style

## Database

- Default database name: `GarminStats`
- Query language: **InfluxQL** (compatible with both v1.x and v3.x)
- Tags identify time series; timestamps act as implicit primary key

## Key Environment Variables

| Variable | Description |
|---|---|
| `INFLUXDB_HOST` | InfluxDB host |
| `INFLUXDB_PORT` | Port (8086 for v1, 8181 for v3) |
| `INFLUXDB_DATABASE` | Database name (default: `GarminStats`) |
| `GARMINCONNECT_EMAIL` | Garmin Connect email (optional) |
| `GARMINCONNECT_BASE64_PASSWORD` | Base64-encoded password (optional) |
| `FETCH_SELECTION` | Comma-separated list of metrics to fetch |
| `UPDATE_INTERVAL_SECONDS` | Periodic fetch interval (default: 300s) |
| `USER_TIMEZONE` | User timezone (e.g. `America/New_York`) |

## Notes

- The project has **no automated tests** at this time
- The main development workflow is Docker-based
- When modifying the dashboard, update the JSON in `Grafana_Dashboard/`
- Pull requests should follow the guidelines in `.github/CONTRIBUTING.md`
- All documentation and code comments must be written in **English**
