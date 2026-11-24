"""Copy an existing garmin-grafana InfluxDB (1.x, or 3.x with INFLUXDB_VERSION=3) database into PostgreSQL.

Uses the same INFLUXDB_* and POSTGRES_* environment variables as garmin_fetch.py, and writes through
the postgres backend, so the tables come out exactly as the fetcher would create them. Safe to run
again: points are upserted, so a second run only refreshes what's there.

  python garmin_grafana/influxdb_to_postgres.py              # every measurement
  python garmin_grafana/influxdb_to_postgres.py --verify     # then compare value counts per field
"""
import argparse
import logging
import os
import sys

from influxdb import InfluxDBClient

try:
    from .postgres_backend import PostgresClient
except ImportError:  # run as a script
    from postgres_backend import PostgresClient

def cast(kind, value):
    """InfluxDB's JSON gives whole floats as ints (65.0 -> 65): make float fields floats again. Nothing
    else is converted: a field can have a different type in each shard (e.g. hrTimeInZone_1 is integer
    in some, float in others), and SHOW FIELD KEYS reports only one of them."""
    return float(value) if kind == "float" and isinstance(value, int) and not isinstance(value, bool) else value

BATCH = 20000
WINDOW_NS = 30 * 86400 * 10**9  # read 30 days at a time (influxdb-python's chunked mode breaks with msgpack)


class Rows(list):
    def get_points(self):
        return iter(self)


class Influx3:
    """InfluxDB 3 through its InfluxQL support, answering queries the way influxdb-python does."""

    def __init__(self):
        from influxdb_client_3 import InfluxDBClient3
        scheme = "https" if os.getenv("INFLUXDB_ENDPOINT_IS_HTTP", "true").lower() in ("false", "f", "no", "0") else "http"
        self.client = InfluxDBClient3(host=f"{scheme}://{os.getenv('INFLUXDB_HOST', 'localhost')}:{os.getenv('INFLUXDB_PORT', 8181)}",
                                      token=os.getenv("INFLUXDB_V3_ACCESS_TOKEN", ""),
                                      database=os.getenv("INFLUXDB_DATABASE", "GarminStats"))

    def query(self, query, epoch=None):
        table = self.client.query(query, language="influxql")
        rows = table.to_pylist()
        if "time" in table.column_names:  # nanoseconds since the epoch, as epoch="ns" gives in 1.x
            for row, ns in zip(rows, table.column("time").cast("int64").to_pylist()):
                row["time"] = ns
        for row in rows:
            row.pop("iox::measurement", None)
        return Rows(rows)


def influx():
    if os.getenv("INFLUXDB_VERSION", "1") == "3":
        return Influx3()
    client = InfluxDBClient(host=os.getenv("INFLUXDB_HOST", "localhost"), port=int(os.getenv("INFLUXDB_PORT", 8086)),
                            username=os.getenv("INFLUXDB_USERNAME", ""), password=os.getenv("INFLUXDB_PASSWORD", ""),
                            database=os.getenv("INFLUXDB_DATABASE", "GarminStats"))
    return client


def postgres():
    return PostgresClient(host=os.getenv("POSTGRES_HOST", "localhost"), port=int(os.getenv("POSTGRES_PORT", 5432)),
                          user=os.getenv("POSTGRES_USER", "garmin"), password=os.getenv("POSTGRES_PASSWORD", ""),
                          database=os.getenv("POSTGRES_DATABASE", "garmin_stats"),
                          sslmode=os.getenv("POSTGRES_SSLMODE", "prefer"),
                          timescale=os.getenv("POSTGRES_TIMESCALE", "").lower() in ("1", "true", "yes", "t"))


def schema(src, measurement):
    tags = [r["tagKey"] for r in src.query(f'SHOW TAG KEYS FROM "{measurement}"').get_points()]
    fields = {r["fieldKey"]: r["fieldType"] for r in src.query(f'SHOW FIELD KEYS FROM "{measurement}"').get_points()}
    return tags, fields


def copy_measurement(src, dst, measurement):
    tags, fields = schema(src, measurement)
    if not fields:
        return 0
    first = next(src.query(f'SELECT * FROM "{measurement}" ORDER BY time ASC LIMIT 1', epoch="ns").get_points())["time"]
    last = next(src.query(f'SELECT * FROM "{measurement}" ORDER BY time DESC LIMIT 1', epoch="ns").get_points())["time"]
    batch, total = [], 0
    for start in range(first, last + 1, WINDOW_NS):
        rows = src.query(f'SELECT * FROM "{measurement}" WHERE time >= {start} AND time < {start + WINDOW_NS}', epoch="ns")
        for row in rows.get_points():
            point = {"measurement": measurement, "time": row["time"],
                     "tags": {t: row[t] for t in tags if row.get(t) is not None},
                     "fields": {f: cast(kind, row[f]) for f, kind in fields.items() if row.get(f) is not None}}
            if point["fields"]:
                batch.append(point)
            if len(batch) >= BATCH:
                dst.write_points(batch)
                total += len(batch)
                batch = []
    if batch:
        dst.write_points(batch)
        total += len(batch)
    return total


def verify(src, dst, measurement):
    """Non-null values per field, InfluxDB vs PostgreSQL. Returns the fields that differ."""
    _, fields = schema(src, measurement)
    counts = next(src.query(f'SELECT COUNT(*) FROM "{measurement}"').get_points(), {})
    differ = []
    for field in fields:
        want = counts.get(f"count_{field}", 0)
        got = dst.conn.execute(f'SELECT count("{field}") FROM "{measurement}"').fetchone()[0]
        if want != got:
            differ.append(f"{field}: influxdb {want}, postgres {got}")
    return differ


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("measurements", nargs="*", help="only these (default: all)")
    parser.add_argument("--verify", action="store_true", help="compare value counts per field afterwards")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    src, dst = influx(), postgres()
    names = args.measurements or [r["name"] for r in src.query("SHOW MEASUREMENTS").get_points()]
    failed = 0
    for name in names:
        n = copy_measurement(src, dst, name)
        problems = verify(src, dst, name) if args.verify else []
        failed += bool(problems)
        logging.info(f"{name}: copied {n} points" + (f"; MISMATCH {problems}" if problems else " (verified)" if args.verify else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
