"""Make a PostgreSQL version of an InfluxDB Grafana dashboard for the postgres backend.

  python Grafana_Postgres/convert_to_postgres.py Grafana_Dashboard/Garmin-Grafana-Dashboard.json Grafana_Dashboard/Garmin-Strength-Training-Dashboard.json

Writes Grafana_Postgres/dashboards/<name>-Postgres.json (kept out of Grafana_Dashboard/, which InfluxDB
installs provision wholesale), and checks that DASHBOARD_TABLES in src/garmin_grafana/postgres_backend.py
lists every table and column they query. Query-builder targets (the structured InfluxQL ones) are
translated mechanically to Grafana's PostgreSQL macros; raw InfluxQL targets come from RAW below,
and any raw query without a translation is reported and left disabled in the output.

Table and column names are the measurement, tag and field names (see postgres_backend.py): each
measurement is a table with a `time` column and one column per tag and field.
"""
import copy
import json
import re
import sys
from pathlib import Path

DATASOURCE = {"type": "grafana-postgresql-datasource", "uid": "${DS_GARMIN_STATS_PG}"}

AGGREGATES = {
    "mean": 'avg({})', "sum": 'sum({})', "max": 'max({})', "min": 'min({})', "count": 'count({})',
    "median": 'percentile_cont(0.5) WITHIN GROUP (ORDER BY {})', "spread": '(max({0}) - min({0}))',
    "stddev": 'stddev({})',
    # InfluxDB's last()/first() only see points that have the field
    "last": '(array_agg({0} ORDER BY time DESC) FILTER (WHERE {0} IS NOT NULL))[1]',
    "first": '(array_agg({0} ORDER BY time) FILTER (WHERE {0} IS NOT NULL))[1]',
}

# Hand translations of the raw InfluxQL targets, by their exact query text.
# {name} is the series name, filled in by series_name() (the target's alias, as InfluxDB would show it).
HR_BUCKETS = ('SELECT "time", mean_value AS "{{name}}" FROM (SELECT $__timeGroupAlias(time, \'1m\'), avg("HeartRate") '
              'AS mean_value FROM "HeartRateIntraday" WHERE $__timeFilter(time) GROUP BY 1) t WHERE mean_value {} ORDER BY 1')
RAW = {
    'select mean_value from (SELECT mean("HeartRate") as mean_value FROM "HeartRateIntraday" WHERE $timeFilter GROUP BY time(1m) fill(null)) where mean_value <= 96': HR_BUCKETS.format("<= 96"),
    'select mean_value from (SELECT mean("HeartRate") as mean_value FROM "HeartRateIntraday" WHERE $timeFilter GROUP BY time(1m) fill(null)) where mean_value > 96': HR_BUCKETS.format("> 96"),
    'select mean_value from (SELECT mean("HeartRate") as mean_value FROM "HeartRateIntraday" WHERE $timeFilter GROUP BY time(1m) fill(null)) where mean_value < 60': HR_BUCKETS.format("< 60"),
    'select mean_value from (SELECT mean("HeartRate") as mean_value FROM "HeartRateIntraday" WHERE $timeFilter GROUP BY time(1m) fill(null)) where mean_value > 110': HR_BUCKETS.format("> 110"),
    **{f'SELECT "SleepStageLevel"+1 FROM "SleepIntraday" WHERE SleepStageLevel={n} AND $timeFilter':
       f'SELECT time, "SleepStageLevel" + 1 AS "{{name}}" FROM "SleepIntraday" '
       f'WHERE "SleepStageLevel" = {n} AND $__timeFilter(time) ORDER BY 1' for n in range(4)},
}

# Strength Training dashboard: hand translations by (panel title, refId); its InfluxQL is all raw.
SETS = '"StrengthExerciseSet"'
WORKING = ('"Weight_kg" > 0 AND "ExerciseLabel" <> \'ROW/INDOOR_ROW\' AND "ExerciseCategory" <> \'RUN\' AND $__timeFilter(time)')
# = ANY(ARRAY[...]) rather than IN (...): with no strength sets the variables are empty, and IN () is a
# syntax error where InfluxDB's =~ /^$ExerciseCategory$/ just matches nothing.
CATEGORY, LABEL = (' AND "ExerciseCategory" = ANY(ARRAY[$ExerciseCategory]::text[])',
                   ' AND "ExerciseLabel" = ANY(ARRAY[$ExerciseLabel]::text[])')
VOLUME, EPLEY = '"Reps" * "Weight_kg"', '"Weight_kg" * (1 + "Reps" / 30.0)'
# GROUP BY time(1d) without tz(): UTC days. (Not $__timeGroup: it returns epoch numbers, which can't be grouped again.)
DAY = "date_bin('1 day', time, TIMESTAMPTZ '1970-01-01 00:00:00+00')"
DAILY_VOLUME = f"SELECT {DAY} AS day, sum({VOLUME}) AS dvol FROM {SETS} WHERE {WORKING} GROUP BY 1"
# Aggregates over the whole range have no time of their own; InfluxDB reports the range start.
RANGE_START = "$__timeFrom()::timestamptz"  # the macro alone is a text literal
WHOLE_RANGE = f'{RANGE_START} AS "time"'
RAW_BY_PANEL = {
    ("Total Volume", "A"): f'SELECT {WHOLE_RANGE}, sum({VOLUME}) AS "{{name}}" FROM {SETS} WHERE {WORKING} HAVING count({VOLUME}) > 0',
    ("Weighted Sets", "A"): f'SELECT {WHOLE_RANGE}, count("Reps") AS "{{name}}" FROM {SETS} WHERE {WORKING} HAVING count("Reps") > 0',
    ("Total Reps", "A"): f'SELECT {WHOLE_RANGE}, sum("Reps") AS "{{name}}" FROM {SETS} WHERE {WORKING} HAVING count("Reps") > 0',
    ("Number of Workouts", "A"): f'SELECT {WHOLE_RANGE}, count(dvol) AS "{{name}}" FROM ({DAILY_VOLUME}) d HAVING count(dvol) > 0',
    ("Avg Volume / Workout", "A"): f'SELECT {WHOLE_RANGE}, avg(dvol) AS "{{name}}" FROM ({DAILY_VOLUME}) d HAVING count(dvol) > 0',
    ("Estimated 1RM Progression (Epley) by Exercise", "A"):
        f'SELECT $__timeGroupAlias(time, \'1d\'), "ExerciseLabel" AS metric, max({EPLEY}) AS e1rm FROM {SETS} '
        f'WHERE {WORKING}{CATEGORY}{LABEL} GROUP BY 1, 2 ORDER BY 1',
    ("Training Volume per Workout", "A"):
        f'SELECT $__timeGroupAlias(time, \'1d\'), sum({VOLUME}) AS "{{name}}" FROM {SETS} WHERE {WORKING} GROUP BY 1 ORDER BY 1',
    ("Personal Records (Top Set & Est. 1RM)", "A"):
        f'SELECT {RANGE_START} AS "Time", "ExerciseLabel", max("Weight_kg") AS "Max Weight (kg)", max({EPLEY}) AS "Best Est. 1RM (kg)" '
        f'FROM {SETS} WHERE {WORKING}{CATEGORY}{LABEL} GROUP BY 2 ORDER BY 2',
    ("Volume by Category", "A"):
        f'SELECT {WHOLE_RANGE}, "ExerciseCategory" AS metric, sum({VOLUME}) AS "Volume" FROM {SETS} WHERE {WORKING}{CATEGORY} GROUP BY 2 ORDER BY 2',
    ("Sets by Category", "A"):
        f'SELECT {RANGE_START} AS "Time", "ExerciseCategory", count("Reps") AS "Sets" FROM {SETS} WHERE {WORKING}{CATEGORY} GROUP BY 2 ORDER BY 2',
    ("Recent Sets (Workout Detail)", "A"):
        f'SELECT time AS "Time", "ExerciseLabel" AS "Exercise", "Reps", "Weight_kg" AS "Weight (kg)", {VOLUME} AS "Volume (kg)", '
        f'"SetOrder" AS "Set #" FROM {SETS} WHERE {WORKING}{CATEGORY}{LABEL} ORDER BY time DESC LIMIT 100',
    ("Workout Summary (per session)", "A"):
        f'SELECT {DAY} AS "Time", count("Reps") AS "Sets", sum("Reps") AS "Reps", sum({VOLUME}) AS "Volume (kg)", '
        f'sum("Duration_s") AS "Time Under Tension (s)" FROM {SETS} WHERE {WORKING} GROUP BY 1 ORDER BY 1',
    **{("HR Zone Time Distribution (Strength Sessions)", ref):
        f'SELECT {WHOLE_RANGE}, sum("SecsInZone") AS "{{name}}" FROM "StrengthHRZones" WHERE "ZoneNumber" = {n} '
        f'AND $__timeFilter(time) HAVING count("SecsInZone") > 0' for n, ref in enumerate("ABCDE", 1)},
    ("Time Under Tension by Exercise", "A"):
        f'SELECT {RANGE_START} AS "Time", "ExerciseLabel", sum("Duration_s") AS "Total Time Under Tension (s)" FROM {SETS} '
        f'WHERE {WORKING}{CATEGORY}{LABEL} GROUP BY 2 ORDER BY 2',
    # InfluxDB fills this subquery's weeks (Thursday-based, from the epoch) from the week of the first
    # workout in the range to the end of the range, so the weeks are generated here, not by the macro.
    ("Workouts per Week", "A"):
        f"WITH d AS ({DAILY_VOLUME}) SELECT w.time, count(d.dvol) AS \"{{name}}\" FROM generate_series("
        f"(SELECT date_bin('1 week', min(day) FILTER (WHERE dvol IS NOT NULL), TIMESTAMPTZ '1970-01-01 00:00:00+00') FROM d), "
        f"$__timeTo()::timestamptz, interval '1 week') AS w(time) "
        f"LEFT JOIN d ON d.day >= w.time AND d.day < w.time + interval '1 week' GROUP BY 1 ORDER BY 1",
    ("Workout Calendar", "A"):
        f'SELECT $__timeGroupAlias(time, \'1d\', 0), count("Reps") AS "{{name}}" FROM {SETS} WHERE {WORKING} GROUP BY 1 ORDER BY 1',
    ("Sets Needing Classification (UNKNOWN)", "A"):
        f'SELECT {WHOLE_RANGE}, count("Reps") AS "{{name}}" FROM {SETS} WHERE "ExerciseCategory" = \'UNKNOWN\' AND $__timeFilter(time) '
        f'HAVING count("Reps") > 0',
}

RAW_TABLES = {
    "StrengthExerciseSet": {"tags": ["ExerciseCategory", "ExerciseLabel"], "fields": ["Reps", "Weight_kg", "Duration_s", "SetOrder"]},
    "StrengthHRZones": {"tags": [], "fields": ["ZoneNumber", "SecsInZone"]},
}

# Dashboard variables whose InfluxQL can't be translated by the SHOW TAG VALUES pattern alone.
RAW_VARIABLES = {
    'SHOW TAG VALUES FROM "StrengthExerciseSet" WITH KEY = "ExerciseLabel" WHERE ExerciseCategory =~ /^$ExerciseCategory$/':
        'SELECT DISTINCT "ExerciseLabel" FROM "StrengthExerciseSet" WHERE "ExerciseCategory" = ANY(ARRAY[$ExerciseCategory]::text[]) ORDER BY 1',
}


def q(name):
    name = re.sub(r"::(tag|field)$", "", name)  # the builder's type hints, e.g. "ActivitySelector::tag"
    return '"' + name.replace('"', '""') + '"'


def tag_conditions(tags):
    sql = ""
    for i, t in enumerate(tags):
        joiner = "" if i == 0 else f" {t.get('condition', 'AND')} "
        value = t["value"]
        if t["operator"] in ("=~", "!~"):
            regex = value.strip("/")
            sql += f"{joiner}{q(t['key'])} {'~' if t['operator'] == '=~' else '!~'} '{regex}'"
        else:
            op = {"=": "=", "!=": "<>", "<": "<", ">": ">"}[t["operator"]]
            sql += f"{joiner}{q(t['key'])} {op} '{value}'"
    return f" AND ({sql})" if sql else ""


def series_name(t, measurement, column):
    """What InfluxDB calls a series in Grafana: the target's alias ($col, $m filled in), else
    "measurement.column". Panel overrides and transformations match on this name."""
    alias = t.get("alias") or ""
    named = alias.replace("$col", column).replace("$measurement", measurement).replace("$m", measurement)
    return named if alias and "$" not in named else f"{measurement}.{column}"


def interval_ms(interval):
    m = re.fullmatch(r"(\d+)(ms|s|m|h|d|w)", interval or "")
    return int(m[1]) * {"ms": 1, "s": 1000, "m": 60000, "h": 3600000, "d": 86400000, "w": 604800000}[m[2]] if m else None


def builder_sql(t):
    """InfluxQL query-builder target -> PostgreSQL time-series SQL with Grafana macros."""
    if not re.fullmatch(r"\w+", t.get("measurement") or ""):
        return None  # e.g. measurement "%": a placeholder for data this project doesn't write
    table = q(t["measurement"])
    group = {g["type"]: g.get("params") or [] for g in t.get("groupBy", [])}
    interval = group.get("time", [None])[0]
    fill = (group.get("fill") or [None])[0]
    columns, window, seen = [], False, {}
    for parts in t.get("select", []):
        field = re.sub(r"::(tag|field)$", "", next(p["params"][0] for p in parts if p["type"] == "field"))
        expr, name = q(field), field
        for p in parts[1:]:
            kind = p["type"]
            if kind in AGGREGATES:
                expr, name = AGGREGATES[kind].format(expr), kind  # InfluxQL names the column after the function
            elif kind == "cumulative_sum":
                expr, window, name = f"sum({expr}) OVER (ORDER BY 1)", True, kind
            elif kind == "math":
                expr = f"({expr}) {p['params'][0]}"
            elif kind == "alias":
                name = p["params"][0]
            else:
                raise ValueError(f"unsupported select part {kind}")
        if name in seen:  # InfluxQL: mean, mean_1, mean_2 ...
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 0
        columns.append(f"{expr} AS {q(series_name(t, t['measurement'], name))}")
    where = f"$__timeFilter(time){tag_conditions(t.get('tags', []))}"
    aggregated = any(p["type"] in AGGREGATES for parts in t.get("select", []) for p in parts)
    if interval and t.get("tz"):
        # InfluxQL tz(): buckets start at local midnight etc. The macros only bucket in UTC, so use
        # date_bin in that zone, on InfluxDB's origin (the epoch), so 1d/1w buckets line up the same.
        tz = t["tz"]
        group_expr = (f"(date_bin('{interval}'::interval, time AT TIME ZONE '{tz}', TIMESTAMP '1970-01-01') "
                      f"AT TIME ZONE '{tz}')")
        if window:
            columns = [c.replace("OVER (ORDER BY 1)", f"OVER (ORDER BY {group_expr})") for c in columns]
        sql = f"SELECT {group_expr} AS \"time\", {', '.join(columns)} FROM {table} WHERE {where} GROUP BY 1 ORDER BY 1"
        if str(fill) == "0":  # fill(0): every bucket in the range, 0 where there's no data
            names = [c.rsplit(" AS ", 1)[1] for c in columns]
            first = (f"date_bin('{interval}'::interval, $__timeFrom()::timestamptz AT TIME ZONE '{tz}', "
                     f"TIMESTAMP '1970-01-01') AT TIME ZONE '{tz}'")
            sql = (f"SELECT b.time, {', '.join(f'COALESCE(v.{n}, 0) AS {n}' for n in names)} "
                   f"FROM generate_series({first}, $__timeTo()::timestamptz, '{interval}'::interval) AS b(time) "
                   f"LEFT JOIN ({sql}) v USING (time) ORDER BY 1")
        return sql
    if interval:
        fill_arg = {"null": ", NULL", "0": ", 0", "previous": ", previous", "none": ""}.get(str(fill), "")
        bucket = f"$__timeGroupAlias(time, '{interval}'{fill_arg})"
        if window:  # a window over the aggregate needs the bucket in its ORDER BY, not "1"
            columns = [c.replace("OVER (ORDER BY 1)", f"OVER (ORDER BY $__timeGroup(time, '{interval}'))") for c in columns]
        return f"SELECT {bucket}, {', '.join(columns)} FROM {table} WHERE {where} GROUP BY 1 ORDER BY 1"
    if aggregated:  # one value over the whole range (stat/gauge panels)
        return f"SELECT max(time) AS \"time\", {', '.join(columns)} FROM {table} WHERE {where}"
    return f"SELECT time, {', '.join(columns)} FROM {table} WHERE {where} ORDER BY 1"


def referenced_tables(dashboard):
    """{measurement: {"tags": [...], "fields": [...]}} that the builder targets query."""
    found = {}
    def walk(x):
        for p in x.get("panels", []):
            for t in p.get("targets", []):
                if t.get("rawQuery") or not re.fullmatch(r"\w+", t.get("measurement") or ""):
                    continue
                m = found.setdefault(t["measurement"], {"tags": set(), "fields": set()})
                for parts in t.get("select", []):
                    m["fields"].update(re.sub(r"::(tag|field)$", "", x["params"][0]) for x in parts if x["type"] == "field")
                for tg in t.get("tags", []):  # WHERE filters: a tag unless marked ::field
                    key, hint = re.fullmatch(r"(.+?)(?:::(tag|field))?", tg["key"]).groups()
                    m["fields" if hint == "field" else "tags"].add(key)
            walk(p)
    walk(dashboard)
    return found


def convert(dashboard):
    out = copy.deepcopy(dashboard)
    missing = []
    for inp in out.get("__inputs", []):
        if inp.get("pluginId") == "influxdb":
            inp.update({"name": "DS_GARMIN_STATS_PG", "label": "Garmin Stats (PostgreSQL)",
                        "pluginId": "grafana-postgresql-datasource", "pluginName": "PostgreSQL"})
    panels = []
    def walk(x):
        for p in x.get("panels", []):
            panels.append(p); walk(p)
    walk(out)
    for p in panels:
        if isinstance(p.get("datasource"), dict) and p["datasource"].get("type") == "influxdb":
            p["datasource"] = DATASOURCE
        gaps = set()
        for t in p.get("targets", []):
            if (t.get("datasource") or {}).get("type") != "influxdb":
                continue
            group = {g["type"]: (g.get("params") or [None])[0] for g in t.get("groupBy", [])}
            if not t.get("rawQuery") and t.get("tz") and group.get("fill") == "null":
                gaps.add(interval_ms(group.get("time")))
            if t.get("rawQuery"):
                sql = RAW.get(t["query"]) or RAW_BY_PANEL.get((p["title"], t["refId"]))
                if sql:
                    m = re.search(r'FROM "(\w+)"', t["query"])
                    sql = sql.replace("{name}", series_name(t, m[1] if m else "", "value").replace('"', '""'))
            else:
                sql = builder_sql(t)
            source = t.get("query") or f"measurement {t.get('measurement')!r}"
            new = {"refId": t["refId"], "datasource": DATASOURCE, "editorMode": "code",
                   "format": "table" if t.get("resultFormat") == "table" else "time_series",
                   "rawQuery": True, "rawSql": sql or f"-- no PostgreSQL translation yet for: {source}"}
            if t.get("hide") or not sql:
                new["hide"] = True
            if not sql:
                missing.append(f"{p['title']}: {source[:100]}")
            t.clear(); t.update(new)
        if p.get("type") == "timeseries" and gaps and None not in gaps:
            # fill(null) made InfluxDB return empty buckets, which break the line; date_bin doesn't, so
            # tell the panel to disconnect points further apart than one bucket.
            custom = p.setdefault("fieldConfig", {}).setdefault("defaults", {}).setdefault("custom", {})
            custom.setdefault("insertNulls", max(gaps))
    for v in out.get("templating", {}).get("list", []):
        if v.get("type") == "datasource" and v.get("query") == "influxdb":
            # A data source picker (the Strength dashboard's DS_GARMIN_STATS): make it pick PostgreSQL
            # sources, under the name the converted panels refer to.
            v.update({"name": "DS_GARMIN_STATS_PG", "query": "grafana-postgresql-datasource", "current": {}})
            continue
        if (v.get("datasource") or {}).get("type") == "influxdb":
            text = (v.get("query") or {}).get("query", "") if isinstance(v.get("query"), dict) else v.get("query", "")
            m = re.fullmatch(r'SHOW TAG VALUES FROM "(\w+)" WITH KEY = "(\w+)"( WHERE \$timeFilter)?', text)
            v["datasource"] = DATASOURCE
            if text in RAW_VARIABLES:
                v["query"] = v["definition"] = RAW_VARIABLES[text]
            elif m:
                time_filter = " WHERE $__timeFilter(time)" if m[3] else ""
                v["query"] = v["definition"] = f'SELECT DISTINCT {q(m[2])} FROM {q(m[1])}{time_filter} ORDER BY 1'
            else:
                missing.append(f"variable {v['name']}: {text}")
    out["title"] = dashboard.get("title", "Garmin") + " (PostgreSQL)"
    out["uid"] = (dashboard.get("uid") or "garmin") + "-pg"
    return out, missing


if __name__ == "__main__":
    tables = {}
    for path in sys.argv[1:]:
        src = Path(path)
        original = json.loads(src.read_text())
        dashboard, missing = convert(original)
        dst = Path(__file__).resolve().parent / "dashboards" / (src.stem + "-Postgres.json")
        dst.write_text(json.dumps(dashboard, indent=2) + "\n")
        print(f"{dst}: {len(missing)} raw queries without a translation" + "".join(f"\n  {m}" for m in missing))
        for name, cols in referenced_tables(original).items():
            t = tables.setdefault(name, {"tags": set(), "fields": set()})
            t["tags"] |= cols["tags"]; t["fields"] |= cols["fields"]
    # The Strength dashboard's InfluxQL is all raw, so its tables are listed here (RAW_BY_PANEL uses them).
    for name, cols in RAW_TABLES.items():
        t = tables.setdefault(name, {"tags": set(), "fields": set()})
        t["tags"] |= set(cols["tags"]); t["fields"] |= set(cols["fields"])
    # The fetcher creates these tables at startup (PostgresClient.ensure_tables), so DASHBOARD_TABLES
    # must list every table and column the dashboards query.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "garmin_grafana"))
    from postgres_backend import DASHBOARD_TABLES
    listed = {k: (set(t.split()), {c.partition(":")[0] for c in f.split()}) for k, (t, f) in DASHBOARD_TABLES.items()}
    absent = [f"{k}: tags {sorted(v['tags'] - listed.get(k, (set(), set()))[0])}, "
              f"fields {sorted(v['fields'] - v['tags'] - listed.get(k, (set(), set()))[1])}"
              for k, v in sorted(tables.items())
              if v["tags"] - listed.get(k, (set(), set()))[0] or v["fields"] - v["tags"] - listed.get(k, (set(), set()))[1]]
    if absent:
        sys.exit("Add these to DASHBOARD_TABLES in src/garmin_grafana/postgres_backend.py:\n  " + "\n  ".join(absent))
    print(f"DASHBOARD_TABLES covers all {len(tables)} tables the dashboards query")
