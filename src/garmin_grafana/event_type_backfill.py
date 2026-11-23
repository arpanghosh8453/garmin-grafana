"""Backfill the `eventType` field (race, training, uncategorized...) of existing activities.

Only the ActivitySummary start points already stored in InfluxDB are updated: the
field is written with the exact measurement, tags and timestamp of each existing
point, so InfluxDB 1.x merges it into that point. Nothing else is rewritten, no
FIT file is downloaded and no point is created for an activity missing from the
database. Garmin Connect is only asked for the activity list, year by year
(one request per 20 activities).

Usage (inside the garmin-fetch-data container, InfluxDB 1.x only):
    python garmin_grafana/event_type_backfill.py --start 2019-12-22 --end 2026-11-23 [--dry-run]
"""
import garmin_fetch

import argparse
import logging
import time
from collections import Counter
from datetime import datetime, timedelta

import pytz


def year_ranges(start_date, end_date):
    """Split [start_date, end_date] into calendar-year chunks."""
    current = start_date
    while current <= end_date:
        chunk_end = min(datetime(current.year, 12, 31), end_date)
        yield current, chunk_end
        current = chunk_end + timedelta(days=1)


def existing_start_points(start_date, end_date):
    """Map ActivityID -> list of (time, tags, eventType) of the stored ActivitySummary points."""
    query = (
        'SELECT * FROM "ActivitySummary" '
        f"WHERE time >= '{start_date:%Y-%m-%d}T00:00:00Z' AND time < '{end_date + timedelta(days=1):%Y-%m-%d}T00:00:00Z' "
        'GROUP BY *'
    )
    points = {}
    for (_, tags), rows in garmin_fetch.influxdbclient.query(query).items():
        activity_id = str(tags.get('ActivityID'))
        for row in rows:
            points.setdefault(activity_id, []).append((row['time'], dict(tags), row.get('eventType')))
    return points


def backfill(start_date, end_date, dry_run=False, pause_seconds=5):
    stats = Counter()
    values = Counter()
    for chunk_start, chunk_end in year_ranges(start_date, end_date):
        activities = garmin_fetch.garmin_obj.get_activities_by_date(f"{chunk_start:%Y-%m-%d}", f"{chunk_end:%Y-%m-%d}")
        stored = existing_start_points(chunk_start, chunk_end)
        points = []
        for activity in activities:
            stats['garmin_activities'] += 1
            event_type = garmin_fetch.get_activity_event_type(activity)
            if not event_type or not activity.get('startTimeGMT'):
                stats['no_event_type'] += 1
                continue
            start_time = datetime.strptime(activity['startTimeGMT'], "%Y-%m-%d %H:%M:%S").replace(tzinfo=pytz.UTC)
            start_time_str = start_time.strftime('%Y-%m-%dT%H:%M:%SZ')
            # The start point is the stored point of this activity at its start time (the END point is later).
            matches = [p for p in stored.get(str(activity.get('activityId')), []) if p[0] == start_time_str]
            if not matches:
                stats['not_in_influxdb'] += 1
                continue
            values[event_type] += 1
            for point_time, tags, current_value in matches:
                if current_value == event_type:
                    stats['already_set'] += 1
                    continue
                points.append({
                    "measurement": "ActivitySummary",
                    "time": point_time,
                    "tags": tags,
                    "fields": {"eventType": event_type},
                })
        stats['points_written'] += 0 if dry_run else len(points)
        stats['points_to_write'] += len(points)
        if points and not dry_run:
            garmin_fetch.influxdbclient.write_points(points)
        logging.info(f"{chunk_start:%Y-%m-%d} to {chunk_end:%Y-%m-%d}: {len(activities)} Garmin activities, {len(points)} points to update")
        time.sleep(pause_seconds)
    logging.info(f"Event type values found: {dict(values)}")
    logging.info(f"Summary{' (dry run, nothing written)' if dry_run else ''}: {dict(stats)}")
    return stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill ActivitySummary.eventType for activities already stored in InfluxDB 1.x")
    parser.add_argument("--start", required=True, help="first date, YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="last date, YYYY-MM-DD (included)")
    parser.add_argument("--dry-run", action="store_true", help="count what would be written, write nothing")
    args = parser.parse_args()

    if garmin_fetch.INFLUXDB_VERSION != '1':
        raise SystemExit("event_type_backfill only supports InfluxDB 1.x")
    garmin_fetch.garmin_obj = garmin_fetch.garmin_login()
    backfill(datetime.strptime(args.start, "%Y-%m-%d"), datetime.strptime(args.end, "%Y-%m-%d"), dry_run=args.dry_run)
