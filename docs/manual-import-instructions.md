### Manual .FIT Activity Import

Use `fit_activity_importer.py` to import a local Garmin `.FIT` activity file into InfluxDB.

#### Using Docker

Use this when your Garmin Grafana stack is running locally.

1. Stop the currently running `garmin-fetch-data` container.
2. Run the importer and mount your local `.FIT` file into the container.

```bash
# In ~/garmin-grafana
docker compose run --rm -v <path_to_fit_file>:/fit_file.fit garmin-fetch-data python /app/garmin_grafana/fit_activity_importer.py
```

Example:

```bash
docker compose run --rm -v "~/Downloads/F129000.FIT":/fit_file.fit garmin-fetch-data python /app/garmin_grafana/fit_activity_importer.py
```

#### Using Local Python Environment

Use this when InfluxDB is remote or when you run the importer without Docker.

1. Ensure your local environment has project dependencies installed.
2. Run:

```bash
python src/garmin_grafana/fit_activity_importer.py --fit_file=<path_to_fit_file>
```

Optional dry run (prints points instead of writing to InfluxDB):

```bash
python src/garmin_grafana/fit_activity_importer.py --fit_file=<path_to_fit_file> --dry_run
```
