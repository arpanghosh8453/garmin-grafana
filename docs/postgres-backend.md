### PostgreSQL backend

garmin-grafana can store its data in PostgreSQL instead of InfluxDB, with optional TimescaleDB. The
fetcher still builds the same points, and `postgres_backend.py` stores them the way InfluxDB would,
so the rest of the project works unchanged. This is the wrapper idea from
[discussion #56](https://github.com/arpanghosh8453/garmin-grafana/discussions/56).

##### How data is stored

- **Tables:** one table per measurement (`"HeartRateIntraday"`, `"SleepSummary"`, ...), created on
  first write, with a `time` column, one text column per tag and one column per field. New tags and
  fields add columns as they appear, like InfluxDB.
- **Re-writes:** a point is identified by its time and tag values. Writing it again overwrites the
  fields it carries and keeps the others, which is how InfluxDB merges re-fetched days. There are no
  duplicates and nothing to set up.
- **Missing values:** a field the fetcher sends as `None` is left out, as with InfluxDB, so a day
  re-fetched without (say) SpO₂ keeps the value already stored.
- **Field types:** integer columns widen to double precision when a decimal arrives. A value that
  can't be stored in a column's type is skipped with a warning, the way InfluxDB rejects it.
- **Tables before data:** at startup the fetcher creates the tables the dashboards query
  (`DASHBOARD_TABLES` in `postgres_backend.py`), so panels for data an account doesn't have show "No data"
  rather than an error. A column with no values yet takes the type of the first value written.
- **Lost connections:** if the database restarts or drops the connection, the next write reconnects
  and retries. If a write still fails, the fetcher fetches the same dates again on its next update
  instead of moving on.
- **TimescaleDB:** with `POSTGRES_TIMESCALE=true`, each table becomes a hypertable (one-year chunks)
  when the extension is available. Plain PostgreSQL is plenty for a person's Garmin data.

##### New install

Follow the README's manual install with two changes:

1. In your `compose.yml` (from [compose-example.yml](../compose-example.yml)), uncomment every line
   marked `(PostgreSQL)` and comment out the InfluxDB lines they replace:
   - `garmin-fetch-data`: `depends_on` `postgres` instead of `influxdb`, and the `DATABASE_BACKEND` and
     `POSTGRES_*` variables
   - the `postgres` service instead of the `influxdb` service
   - `grafana`: the two `./Grafana_Postgres/...` provisioning mounts instead of `./Grafana_Datasource`
     and `./Grafana_Dashboard`
   - `volumes`: `postgres_data`
2. For step 5, Grafana self-provisioning, run:

```
sed -i 's/\${DS_GARMIN_STATS_PG}/garmin_postgres/g' Grafana_Postgres/dashboards/Garmin-Grafana-Dashboard-Postgres.json
```

The Strength Training dashboard picks its data source from a dropdown and needs no `sed`. To import
the dashboards by hand, use the two JSON files in `Grafana_Postgres/dashboards/` with a PostgreSQL
data source.

| Variable | Default | |
|---|---|---|
| `DATABASE_BACKEND` | `influxdb` | `postgres` to use this backend |
| `POSTGRES_HOST` / `POSTGRES_PORT` | `localhost` / `5432` | |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` | `garmin` / (empty) | the user needs to create tables |
| `POSTGRES_DATABASE` | `garmin_stats` | must exist |
| `POSTGRES_SSLMODE` | `prefer` | libpq sslmode |
| `POSTGRES_TIMESCALE` | `false` | use hypertables |

##### Moving an existing InfluxDB database

`influxdb_to_postgres.py` copies every measurement through the same backend, so the tables come out
exactly as the fetcher creates them.
- **Settings:** it uses your usual `INFLUXDB_*` variables (InfluxDB 1.x, or 3.x with
  `INFLUXDB_VERSION=3` and `INFLUXDB_V3_ACCESS_TOKEN`) and the `POSTGRES_*` ones.
- **Reruns:** it's safe to run again, because points are upserted.
- **`--verify`:** compares the number of values in every field afterwards.

With both databases in your compose file and the `POSTGRES_*` variables set on `garmin-fetch-data`:

```
docker compose stop garmin-fetch-data
docker compose run --rm garmin-fetch-data python /app/garmin_grafana/influxdb_to_postgres.py --verify
```

Then switch `garmin-fetch-data` to `DATABASE_BACKEND=postgres` and Grafana to the
`Grafana_Postgres/` provisioning mounts, recreate the containers (`docker compose up -d`), and remove
InfluxDB once you're happy.

An existing install switched without migrating starts with an empty PostgreSQL database; the data
stays in InfluxDB.

##### CSV export

`influxdb_exporter.py` (see the README's export section) also reads PostgreSQL when
`DATABASE_BACKEND=postgres`. It produces the same files, column for column.

##### Dashboards

`Grafana_Postgres/convert_to_postgres.py` regenerates the PostgreSQL dashboards from the InfluxDB
ones, so a change to a dashboard only needs a rerun:

- **Query-builder panels** are translated mechanically.
- **Hand-written InfluxQL** has translations in `RAW` (by query text) and `RAW_BY_PANEL`
  (by panel and query).
- **Series names** stay InfluxDB's (target aliases, `measurement.mean`, `$tag_…` names), so panel
  overrides and transformations keep working.
- **Time zones:** `tz('$TimeZone')` queries are grouped in that time zone with `date_bin`.
- **Data source pickers and import inputs** are switched to PostgreSQL.

It also checks that `DASHBOARD_TABLES` in `postgres_backend.py` lists every table and column the
dashboards query, and names any that are missing.

```
uv run python Grafana_Postgres/convert_to_postgres.py Grafana_Dashboard/Garmin-Grafana-Dashboard.json Grafana_Dashboard/Garmin-Strength-Training-Dashboard.json
```

##### How it was tested

Against a copy of a real database: 17 measurements, about 1.06 million points, 10 months (Dec 2025 – Oct 2026).

- **Migration from InfluxDB 1.x:** every field's value count matched, and the sum, min and max of
  all 139 fields (and the latest value of text fields) were identical. It took 49 seconds, and a
  second run changed nothing.
- **Migration from InfluxDB 3.x (3.11.7 Core):** the same data loaded through `InfluxDBClient3`,
  then migrated. All 218 columns in 18 tables came out identical to the 1.x migration.
- **Fetcher:** `garmin_fetch.py` imported with `DATABASE_BACKEND=postgres` against a disposable
  PostgreSQL, its own point builders fed made-up Garmin responses. That covered the real startup path
  (connection-test point and table creation), then writes through `write_points_to_influxdb()`:
  - a re-write overwrites only the fields given
  - naive and ISO `Z` times land on the same UTC point
  - a new tag (`User_ID`) starts a separate series
  - integer-to-decimal widening works
  - a wrong-type value is skipped and the rest of the point kept
  - the strength-set purge removes only its activity
  - the last-sync lookup works
  - an empty pre-created column takes its first value's type
  - activity summaries and sleep summaries with missing values, after the startup schema
  - a lost connection, and a failed write being counted
- **Main dashboard:** all 142 panel queries were run through Grafana 13.2.5 against both databases
  over the last 30 and 365 days. 134 returned identical values and series names, 8 were empty in
  both, and none failed. They render identically.
- **Strength Training dashboard:** realistic workouts (790 sets, 240 HR-zone points, written as the
  fetcher's own points to both databases), all 21 queries compared. The cases: every category and
  a single category, over 7, 30, 120 and 400 days, plus a window with no workouts. Every query
  returned identical values, text and series names, and in the empty window all were empty in
  both. It renders as shipped, with its data source picker selecting PostgreSQL.
- **CSV export:** a year exported from both databases. All 17 CSVs were identical.
- **Storage:** plain PostgreSQL 148 MB, TimescaleDB 190 MB, InfluxDB 54 MB (InfluxDB compresses;
  TimescaleDB's compression is under its non-OSI license).

##### Limitations

- The "Battery Level" panel queries `"%"` (a GarminHomeAssistant placeholder) and is disabled in the
  PostgreSQL dashboard.
- The Kubernetes chart (`k8s/`) still deploys InfluxDB only.
- The fetcher writes its connection-test `DemoPoint` with the current time on every start. With either
  database they pile up: about 336k points (32 MB) in the database this was tested on.
