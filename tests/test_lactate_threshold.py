import os
import sys
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

import dotenv
import influxdb


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


class NoNetworkInfluxDBClient:
    def __init__(self, *args, **kwargs):
        pass

    def switch_database(self, database):
        pass

    def write_points(self, points):
        return True


# Importing garmin_fetch initializes InfluxDB and writes a demo point. Replace
# that client and suppress dotenv loading so this test cannot contact services
# or consume user configuration.
with (
    patch.object(influxdb, "InfluxDBClient", NoNetworkInfluxDBClient),
    patch.object(dotenv, "load_dotenv", return_value=False),
    patch.dict(os.environ, {"INFLUXDB_VERSION": "1", "INFLUXDB_ENDPOINT_IS_HTTP": "true"}),
):
    from garmin_grafana import garmin_fetch


class SyntheticGarminClient:
    def __init__(self):
        self.calls = []

    def connectapi(self, endpoint):
        self.calls.append(endpoint)
        if "lactateThresholdSpeed" in endpoint:
            return [{"value": 3.25}]
        if "lactateThresholdHeartRate" in endpoint:
            return [{"value": 171}]
        raise AssertionError(f"Unexpected synthetic endpoint: {endpoint}")


class LactateThresholdTests(TestCase):
    def test_range_queries_use_latest_aggregation_and_map_synthetic_values(self):
        client = SyntheticGarminClient()
        expected_endpoints = [
            "/biometric-service/stats/lactateThresholdSpeed/range/2026-10-01/2026-10-01?sport=RUNNING&aggregation=daily&aggregationStrategy=LATEST",
            "/biometric-service/stats/lactateThresholdHeartRate/range/2026-10-01/2026-10-01?sport=RUNNING&aggregation=daily&aggregationStrategy=LATEST",
        ]

        with (
            patch.object(garmin_fetch, "garmin_obj", client),
            patch.object(garmin_fetch, "LACTATE_THRESHOLD_SPORTS", ["RUNNING"]),
            patch.object(garmin_fetch, "GARMIN_DEVICENAME", "synthetic-device"),
            patch.object(garmin_fetch, "INFLUXDB_DATABASE", "synthetic-database"),
        ):
            points = garmin_fetch.get_lactate_threshold("2026-10-01")

        self.assertEqual(client.calls, expected_endpoints)
        self.assertEqual(
            [point["fields"] for point in points],
            [
                {"SpeedThreshold_RUNNING": 3.25},
                {"HeartRateThreshold_RUNNING": 171},
            ],
        )
        self.assertTrue(all(point["measurement"] == "LactateThreshold" for point in points))
        self.assertTrue(all(point["tags"]["Device"] == "synthetic-device" for point in points))
        self.assertTrue(all(point["tags"]["Database_Name"] == "synthetic-database" for point in points))


if __name__ == "__main__":
    from unittest import main

    main()
