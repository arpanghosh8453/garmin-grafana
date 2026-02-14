# Automatically run CI/Cd pipeline on update of this script.

"""
This script can be used to import data from a Garmin bulk export.

The currently supported imports are:
* daily_avg
* sleep
* hydration
* activity

Future work:
* Add support for monitor .fit files.
"""
import time
import argparse
from typing import List
from pathlib import Path
from datetime import datetime, timezone
from fitparse import FitFile, FitParseError
from collections import namedtuple
from io import BytesIO
from unittest import mock
from enum import Enum

import zipfile
import os
import logging
import json
import re
import socket
import garmin_fetch

# The FIT file index contains a list of all activites and
# their date, filename, and activity type. This index makes lookups
# easier throughout the import process.

CACHED_FIT_FILE_INDEX_FILENAME = "fit_file_index.json"


class GarminBulkImporterError(Exception):
    pass


def iso_to_timestamp_ms(iso_str: str) -> int:
    dt = datetime.fromisoformat(iso_str)
    dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


FitFileEntry = namedtuple(
    "FitFileEntry", ["date", "activity", "zip_file_name", "fit_file_name"]
)


class ActivityDownloadFormatEnum(Enum):
    ORIGINAL = 0
    TCX = 1


def cache_fit_file_index(fit_file_index, output_path: Path):
    """
    Save fit_file_index to a JSON file for debugging.
    """
    output_path = Path(output_path)
    logging.info(f"Caching fit index to {output_path}")

    serializable = []
    for entry in fit_file_index:
        serializable.append(
            {
                "date": entry.date.isoformat(),
                "zip_file_name": str(entry.zip_file_name),
                "fit_file_name": entry.fit_file_name,
                "activity": entry.activity,
            }
        )

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(serializable, f, indent=4)


def load_cached_fit_file_index(input_path: Path):
    """
    Load fit_file_index from a JSON debug file.
    """
    input_path = Path(input_path)
    if not input_path.exists():
        return None

    logging.info(f"Using cached fit index at {input_path}")
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    fit_file_index = []
    for entry in data:
        fit_file_index.append(
            FitFileEntry(
                date=datetime.fromisoformat(entry["date"]),
                activity=entry["activity"],
                zip_file_name=Path(entry["zip_file_name"]),
                fit_file_name=entry["fit_file_name"],
            )
        )

    return fit_file_index


class GarminBulkExport:
    """Returns data from the bulk exported data from Garmin.

    Implements the same interface as the Garmin API.
    """

    # Path to the root directory of the bulk export
    path: Path

    # Contains a list of all files in the export
    all_files: List[Path]

    # Activities data
    activities: dict

    # Aggregated stats
    agg_stats: dict

    # Sleep stats
    sleep_stats: dict

    # Hydration stats
    hydration_stats: dict

    # FIT files
    fit_file_index: dict

    ActivityDownloadFormat = ActivityDownloadFormatEnum

    def __init__(self, bulk_data_path: Path):
        self.path = Path(os.path.expanduser(bulk_data_path))
        if not self.path.exists():
            self.fail(f"{self.path} does not exist")

        self.all_files = self.get_all_files()
        self.activities = self.load_activities()

        # Must calculate sleep stats before aggregated stats
        self.sleep_stats = self.load_sleep_stats()
        self.agg_stats, self.hydration_stats = self.load_agg_stats()

        self.cached_fit_file_index = self.path / CACHED_FIT_FILE_INDEX_FILENAME
        self.fit_file_index = (
            load_cached_fit_file_index(self.cached_fit_file_index)
            or self.load_fit_file_index()
        )

    def fail(self, msg: str):
        """Raise a failure with a custom message."""
        raise GarminBulkImporterError(msg)

    def get_all_files(self) -> List[Path]:
        """Returns all of the files found in the export directory."""
        files = []
        for root, _, filenames in os.walk(self.path):
            for name in filenames:
                files.append(os.path.join(root, name))
        all_files = [Path(f) for f in files]
        logging.info("Found %d total files in directory", len(all_files))

        return all_files

    def load_activities(self):
        """Returns all found activities."""
        summary_file_paths = [
            p
            for p in self.all_files
            if re.search(r"DI-Connect-Fitness.*summarizedActivities.json", str(p))
        ]
        if not summary_file_paths:
            return {}

        activities = []
        for p in summary_file_paths:
            with open(p) as f:
                data = json.load(f)
                for entry in data:
                    activities.extend(entry["summarizedActivitiesExport"])

        for a in activities:
            # Convert values into the expected API format and key names.
            a["startTimeGMT"] = datetime.fromtimestamp(
                a["startTimeGmt"] / 1000, tz=timezone.utc
            ).strftime("%Y-%m-%d %H:%M:%S")
            activity_type = a.get("activityType")
            a["activityName"] = a.get("name", activity_type)
            a["activityType"] = {"typeKey": activity_type}
            a["averageSpeed"] = a.get("avgSpeed")
            a["maxHR"] = a.get("maxHr")
            a["averageHR"] = a.get("avgHr")

        logging.info("Loading %d activities", len(activities))
        return sorted(activities, key=lambda o: o["startTimeGMT"])

    def load_sleep_stats(self):
        """Returns all found sleep stats."""
        sleep_stats_paths = [
            p
            for p in self.all_files
            if re.search(r"DI-Connect-Wellness.*sleepData.json", str(p))
        ]
        if not sleep_stats_paths:
            self.fail("Failed to find any sleep stats files")

        sleep_stats = {}
        for p in sleep_stats_paths:
            with open(p) as f:
                data = json.load(f)
                for stats in data:
                    if "calendarDate" not in stats:
                        continue
                    stats_date = stats.get("calendarDate")
                    if stats_date in sleep_stats:
                        self.fail(
                            f"Duplicate entries found for sleep stats dated on {stats_date}"
                        )

                    # Coerce values into the expected API format.
                    stats["sleepEndTimestampGMT"] = iso_to_timestamp_ms(
                        stats["sleepEndTimestampGMT"]
                    )
                    sleep_stats[stats_date.strip()] = stats

        logging.info("Loading %d days of sleep stats", len(sleep_stats))
        return sleep_stats

    def calculate_sleeping_seconds(self, date_str):
        """Calculates the sleepingSeconds from the sleep stats."""
        sleep_data = self.get_sleep_data(date_str)
        sleep_stats = sleep_data.get("dailySleepDTO")
        total = 0
        if sleep_stats:
            total = sum(
                [
                    sleep_stats.get("deepSleepSeconds", 0),
                    sleep_stats.get("lightSleepSeconds", 0),
                    sleep_stats.get("awakeSleepSeconds", 0),
                    sleep_stats.get("unmeasurableSeconds", 0),
                ]
            )

        return total if total > 0 else None

    def load_agg_stats(self):
        """Returns all found aggregate daily stats."""
        agg_stats_paths = [
            p
            for p in self.all_files
            if re.search(r"DI-Connect-Aggregator.*UDSFile.*.json", str(p))
        ]
        if not agg_stats_paths:
            self.fail("Failed to find any aggregated stats files")

        agg_stats = {}
        hydration_stats = {}
        for p in agg_stats_paths:
            with open(p) as f:
                data = json.load(f)
                for stats in data:
                    # Hydration entry
                    if "hydration" in stats:
                        stats = stats["hydration"]
                        stats_date = stats["calendarDate"]
                        hydration_stats[stats_date.strip()] = stats
                    # Standard daily stats entry
                    else:
                        stats_date = stats["calendarDate"]
                        if stats_date in agg_stats:
                            self.fail(
                                f"Duplicate entries found for aggregated stats dated on {stats_date}"
                            )

                        # 'sleepingSeconds' isn't included in this data structure
                        # so we have to calculate it from the sleep stats.
                        stats["sleepingSeconds"] = self.calculate_sleeping_seconds(
                            stats_date
                        )

                        agg_stats[stats_date.strip()] = stats

        logging.info("Loading %d days of aggregated stats", len(agg_stats))
        return agg_stats, hydration_stats

    def load_fit_file_index(self):
        """Load and index all activity .fit files.

        Returns a list of activities with their date, filename, and corresponding activity.

        Does not currently support monitoring messages, only activities.
        """

        def get_fields(msg):
            data = {}
            for field in msg:
                data[field.name] = field.value
            return data

        zip_file_paths = [
            p
            for p in self.all_files
            if re.search(r"DI-Connect-Uploaded-Files.*.zip", str(p))
        ]

        fit_file_index = []

        for zip_file_path in zip_file_paths:
            with zipfile.ZipFile(zip_file_path, "r") as z:
                namelist = z.namelist()
                logging.info("Processing %s (%d files)", zip_file_path, len(namelist))
                for i, filename in enumerate(namelist):
                    if i % 500 == 0:
                        logging.info(f"{i/len(namelist):.2%} .fit files processed ... ")

                    if filename.lower().endswith(".fit"):
                        f = z.open(filename)
                        try:
                            fit_file = FitFile(f)
                            fit_file.parse()
                        except FitParseError as e:
                            raise RuntimeError(f"Failed to parse FIT file: {e}")

                        session_sport = None
                        session_date = None
                        for msg in fit_file.messages:
                            if msg.name == "session":
                                session_data = get_fields(msg)
                                session_date = session_data["start_time"].replace(
                                    tzinfo=timezone.utc
                                )
                                session_sport = session_data.get("sport", "Unknown")

                        if session_sport is not None and session_date is not None:
                            fit_file_index.append(
                                FitFileEntry(
                                    date=session_date,
                                    activity=session_sport,
                                    zip_file_name=zip_file_path,
                                    fit_file_name=filename,
                                )
                            )

        logging.info("Found %d activity .fit files", len(fit_file_index))
        cache_fit_file_index(fit_file_index, self.cached_fit_file_index)
        return fit_file_index

    def get_device_last_used(self):
        """
        Mimics the Garmin API's get_device_last_used endpoint but overrides the device name
        to be the hostname of the local machine.
        """
        hostname = socket.gethostname()

        return {
            "lastUsedDeviceName": hostname,
            "userDeviceId": None,
            "imageUrl": None,
            "lastUsedDeviceUploadTime": 0,
        }

    def get_last_activity(self):
        """Mimics the Garmin API's get_last_activity endpoint"""
        return self.activities[-1]

    def get_stats(self, date_str: str) -> dict:
        """Mimics the Garmin API's get_stats endpoint"""
        stats = self.agg_stats.get(date_str)
        if stats is None or not stats.get("includesWellnessData", True):
            return {
                "wellnessStartTimeGmt": None,
            }
        return stats

    def get_sleep_data(self, date_str: str) -> dict:
        """Mimics the Garmin API's get_sleep_data endpoint"""
        stats = self.sleep_stats.get(date_str)
        if stats is None:
            return {"dailySleepDTO": {"sleepEndTimestampGMT": None}}
        return {"dailySleepDTO": stats}

    def get_hydration_data(self, date_str: str) -> dict:
        """Mimics the Garmin API's get_hydration_data endpoint"""
        return self.hydration_stats.get(date_str, {})

    def get_activities_by_date(self, start_date_str, end_date_str):
        """Mimics the Garmin API's get_activities_by_date endpoint"""
        start_dt = datetime.strptime(start_date_str, "%Y-%m-%d")

        # End should include the full day, so extend to 23:59:59
        end_dt = datetime.strptime(end_date_str, "%Y-%m-%d")
        end_dt = end_dt.replace(hour=23, minute=59, second=59)

        results = []

        for act in self.activities:
            act_dt = datetime.strptime(act["startTimeGMT"], "%Y-%m-%d %H:%M:%S")

            # Inclusive range check
            if start_dt <= act_dt <= end_dt:
                results.append(act)

        return results

    def download_activity(self, activityId, dl_fmt=ActivityDownloadFormatEnum.ORIGINAL):
        """
        Mimics Garmin API download_activity.

        Returns:
            bytes: ZIP archive containing the matching .fit file
        """
        if dl_fmt == ActivityDownloadFormatEnum.TCX:
            return b""

        # Find the activity summary by activityId
        activity = next(
            (a for a in self.activities if a.get("activityId") == activityId),
            None,
        )
        if not activity:
            self.fail(f"Activity ID not found: {activityId}")

        activity_start = datetime.strptime(
            activity["startTimeGMT"], "%Y-%m-%d %H:%M:%S"
        ).replace(tzinfo=timezone.utc)

        # Find closest matching FIT file
        # Allow small timestamp drift (Garmin often differs by seconds)
        MAX_TIME_DIFF_SECONDS = 300  # 5 minutes

        best_match = None
        best_delta = None

        for entry in self.fit_file_index:
            delta = abs((entry.date - activity_start).total_seconds())

            if delta <= MAX_TIME_DIFF_SECONDS:
                if best_delta is None or delta < best_delta:
                    best_match = entry
                    best_delta = delta

        if not best_match:
            self.fail(
                f"No matching FIT file found for activityId={activityId} "
                f"({activity_start.isoformat()})"
            )

        logging.info(
            "Matched activityId=%s to FIT file %s (%s, delta=%ds)",
            activityId,
            best_match.fit_file_name,
            best_match.zip_file_name,
            int(best_delta),
        )

        # Extract FIT file and return ZIP (in-memory)
        zip_buffer = BytesIO()

        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as out_zip:
            with zipfile.ZipFile(best_match.zip_file_name, "r") as src_zip:
                with src_zip.open(best_match.fit_file_name) as fit_file:
                    fit_bytes = fit_file.read()
                    out_zip.writestr(
                        best_match.fit_file_name.split("/")[-1],
                        fit_bytes,
                    )

        zip_buffer.seek(0)
        return zip_buffer.getvalue()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="Garmin Bulk Import", description="Imports data from a Garmin bulk export"
    )
    parser.add_argument(
        "--bulk_data_path",
        # This is the default path used with doing a manual docker import (See README instructions)
        default="/bulk_export",
        help="Path to a directory containing your Garmin data from the bulk export",
    )
    parser.add_argument("--start_date", help="Optional start date (YYYY-MM-DD).")
    parser.add_argument(
        "--end_date",
        help="End date (YYYY-MM-DD)",
        default=datetime.today().strftime("%Y-%m-%d"),
    )
    parser.add_argument(
        "--ignore_errors",
        action="store_true",
        help="If true, will ignore errors and continue processing data",
    )
    args = parser.parse_args()

    args.start_date = args.start_date or os.getenv("MANUAL_START_DATE")
    if not args.start_date:
        raise RuntimeError(
            "start_date must be set using --start_date or MANUAL_START_DATE environment varioable"
        )

    # Override the garmin_obj with GarminBulkExport that implements the same interface.
    garmin_fetch.garmin_obj = GarminBulkExport(args.bulk_data_path)

    # Override these timeouts since we aren't making API calls.
    garmin_fetch.UPDATE_INTERVAL_SECONDS = 0
    garmin_fetch.RATE_LIMIT_CALLS_SECONDS = 0
    garmin_fetch.ALWAYS_PROCESS_FIT_FILES = True
    garmin_fetch.IGNORE_ERRORS = args.ignore_errors

    if garmin_fetch.IGNORE_ERRORS:
        logging.info(
            "IGNORE_ERRORS is enabled. We reccomend saving the output so that you can check for any failed imports afterwards."
        )
        time.sleep(5)

    # These are the only types of data that are included in the bulk export.
    garmin_fetch.FETCH_SELECTION = "daily_avg,sleep,activity,hydration"

    garmin_fetch.fetch_write_bulk(args.start_date, args.end_date)
    logging.info(
        f"Bulk update success : Fetched all available health metrics for date range {args.start_date} to {args.end_date}"
    )
