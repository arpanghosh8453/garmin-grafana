import garmin_fetch

import argparse
import json
import logging
import hashlib
import zipfile

from fitparse import FitFile, FitParseError
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any
from pathlib import Path
from io import BytesIO
from unittest import mock


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_fit_activity_summary(fit_file: FitFile) -> List[Dict[str, Any]]:
    """
    Extract an activity summary from a FIT file using session, activity, and file_id messages.

    This returns points that are formatted for the Garmin Grafana database.
    """

    file_data = {}
    session_data = {}
    activity_data = {}

    for msg in fit_file.get_messages():
        if msg.name == "file_id":
            for field in msg:
                file_data[field.name] = field.value
        elif msg.name == "session":
            for field in msg:
                session_data[field.name] = field.value
        elif msg.name == "activity":
            for field in msg:
                activity_data[field.name] = field.value

    # Create an actitivy id based on the md5sum hash of file metadata.
    serialized = json.dumps(
        file_data,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    md5hash = hashlib.md5(serialized).digest()
    activity_id = int.from_bytes(md5hash[:4], byteorder="big", signed=False)

    if "start_time" not in session_data:
        raise ValueError("FIT file does not contain a session start_time")

    start_time = session_data["start_time"].replace(tzinfo=timezone.utc)

    elapsed_duration = session_data.get("total_elapsed_time", 0)
    moving_duration = session_data.get("total_timer_time", 0)

    activity_type = session_data.get("sport", "Unknown")

    activity_selector = start_time.strftime("%Y%m%dT%H%M%SUTC-") + str(activity_type)

    # Start point
    start_point = {
        "measurement": "ActivitySummary",
        "time": start_time.isoformat(),
        "tags": {
            "Device": file_data.get("garmin_product", "Garmin"),
            "Database_Name": garmin_fetch.INFLUXDB_DATABASE,
            "ActivityID": activity_id,
            "ActivitySelector": activity_selector,
        },
        "fields": {
            "Device_ID": file_data.get("serial_number"),
            "activityType": activity_type,
            "activityName": f"{activity_type.capitalize()} {str(start_time.date())}",
            "distance": session_data.get("total_distance"),
            "elapsedDuration": elapsed_duration,
            "movingDuration": moving_duration,
            "averageSpeed": session_data.get("avg_speed"),
            "maxSpeed": session_data.get("max_speed"),
            "calories": session_data.get("total_calories"),
            "averageHR": session_data.get("avg_heart_rate"),
            "maxHR": session_data.get("max_heart_rate"),
            "lapCount": session_data.get("num_laps"),
        },
    }

    # End point
    end_time = start_time + timedelta(seconds=int(elapsed_duration))

    end_point = {
        "measurement": "ActivitySummary",
        "time": end_time.isoformat(),
        "tags": {
            "Device": file_data.get("garmin_product", "Garmin"),
            "Database_Name": garmin_fetch.INFLUXDB_DATABASE,
            "ActivityID": activity_id,
            "ActivitySelector": activity_selector,
        },
        "fields": {
            "Device_ID": file_data.get("serial_number"),
            "ActivityID": activity_id,
            "activityName": "END",
            "activityType": "No Activity",
        },
    }

    return activity_id, activity_type, start_point, end_point


class MockGarminObject:
    """Imitates the Garmin API to return avtivity files."""

    def __init__(self, fit_file_path: Path):
        self.file_path = fit_file_path
        self.ActivityDownloadFormat = mock.MagicMock()

    def download_activity(self, *_, **__):
        """
        Create an in-memory .zip file containing the .fit file.
        """
        file_path = Path(self.file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        zip_buffer = BytesIO()

        with zipfile.ZipFile(
            zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED
        ) as zf:
            zf.write(
                filename=file_path,
                arcname=file_path.name.lower(),
            )

        zip_buffer.seek(0)
        return zip_buffer.read()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="Garmin Activity FIT File Importer",
        description="Imports activity summary from a local .fit file",
    )
    parser.add_argument(
        "--fit_file",
        # This is the default path used with doing a manual docker import (See README instructions)
        default="/fit_file.fit",
        help="Path to the .fit file",
    )
    parser.add_argument(
        "--dry_run",
        action="store_true",
        help="Prints results instead of submitting to database.",
    )

    args = parser.parse_args()
    fit_path = Path(args.fit_file)

    if not fit_path.exists():
        raise FileNotFoundError(f"FIT file not found: {fit_path}")

    try:
        fit_file = FitFile(str(fit_path))
        fit_file.parse()
    except FitParseError as e:
        raise RuntimeError(f"Failed to parse FIT file: {e}")

    activity_id, activity_type, start_point, end_point = get_fit_activity_summary(
        fit_file
    )

    # Override the garmin_obj to return the fit file we want to import.
    garmin_fetch.garmin_obj = MockGarminObject(fit_path)
    gps_points = garmin_fetch.fetch_activity_GPS({activity_id: activity_type})
    logger.info("Parsed %d activity summary points", len(gps_points))

    if args.dry_run:
        print(json.dumps([start_point, end_point], indent=4))
    else:
        garmin_fetch.write_points_to_influxdb([start_point, end_point])
        garmin_fetch.write_points_to_influxdb(gps_points)
