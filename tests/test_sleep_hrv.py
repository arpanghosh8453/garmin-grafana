"""Regression tests for SleepSummary.avgOvernightHrv field-type normalization.

The Garmin API returns ``avgOvernightHrv`` sometimes as an integer and
sometimes as a float. Writing those unnormalised into InfluxDB produced two
field types (``float`` and ``integer``) on the same measurement, which breaks
queries that span shard groups.

The importer (``garmin_grafana.garmin_fetch.get_sleep_data``) must therefore
always emit an InfluxDB float when a value is present, and keep ``None`` when
Garmin does not provide one.

These tests exercise the real importer code path. The third-party client
modules (InfluxDB, Garmin Connect, fitparse, dotenv, requests, pytz) are
stubbed so the suite runs with nothing but the Python standard library.
"""

import datetime
import os
import sys
import types
import unittest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC_DIR = os.path.join(_REPO_ROOT, "src")

# Sentinel used to distinguish "avgOvernightHrv key absent" from "present as null".
_MISSING = object()

# The SleepSummary point uses fake Garmin payloads; one sample timestamp.
SAMPLE_SLEEP_END_TS_MS = 1704067200000  # 2024-01-01T00:00:00Z


class _UtcTz(datetime.tzinfo):
    """Minimal UTC tzinfo stand-in for the stubbed pytz module."""

    def utcoffset(self, dt):
        return datetime.timedelta(0)

    def dst(self, dt):
        return datetime.timedelta(0)

    def tzname(self, dt):
        return "UTC"

    def localize(self, dt):
        return dt.replace(tzinfo=self)


def _stub_module(name, **attrs):
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    sys.modules[name] = mod
    return mod


def _install_stubs():
    """Stand in for every third-party module imported by garmin_fetch.

    Only the pieces exercised at import time or by ``get_sleep_data`` are
    provided. Calling ``get_sleep_data`` must be the only network-free path
    used by the tests.
    """

    class _NoopClient:
        def __init__(self, *args, **kwargs):
            pass

        def switch_database(self, *args, **kwargs):
            pass

        def write_points(self, *args, **kwargs):
            pass

        def write(self, *args, **kwargs):
            pass

    utc_tz = _UtcTz()
    influx_exceptions = _stub_module("influxdb.exceptions", InfluxDBClientError=Exception)
    _stub_module(
        "influxdb",
        InfluxDBClient=_NoopClient,
        exceptions=influx_exceptions,
    )
    _stub_module(
        "influxdb_client_3",
        InfluxDBClient3=_NoopClient,
        InfluxDBError=Exception,
    )
    _stub_module(
        "garminconnect",
        Garmin=object,
        GarminConnectAuthenticationError=Exception,
        GarminConnectConnectionError=Exception,
        GarminConnectTooManyRequestsError=Exception,
    )
    _stub_module("fitparse", FitFile=object, FitParseError=Exception)
    _stub_module("dotenv", load_dotenv=lambda *a, **k: False)
    _stub_module("requests")
    _stub_module("pytz", timezone=lambda name: utc_tz, utc=utc_tz)


_install_stubs()
sys.path.insert(0, _SRC_DIR)

# garmin_fetch prints an ASCII-art banner (box-drawing characters) on import;
# make sure output encoding cannot abort the import on narrow console code pages.
for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if _reconfigure is not None:
        _reconfigure(errors="replace")

import garmin_grafana.garmin_fetch as garmin_fetch  # noqa: E402  (stubs must be in place first)


class _FakeGarmin:
    """Returns a canned get_sleep_data response."""

    def __init__(self, payload):
        self._payload = payload

    def get_sleep_data(self, date_str):
        return self._payload


def _sleep_payload(hrv):
    """Build a minimal Garmin sleep response with avgOvernightHrv.

    ``hrv`` may be ``None`` (present but null) or ``_MISSING`` (key absent).
    """
    payload = {
        "dailySleepDTO": {"sleepEndTimestampGMT": SAMPLE_SLEEP_END_TS_MS},
    }
    if hrv is not _MISSING:
        payload["avgOvernightHrv"] = hrv
    return payload


class SleepSummaryHrvTestCase(unittest.TestCase):
    def _collect_sleep_points(self, payload):
        garmin_fetch.garmin_obj = _FakeGarmin(payload)
        return garmin_fetch.get_sleep_data("2024-01-01")

    def _sleep_summary_point(self, payload):
        points = self._collect_sleep_points(payload)
        self.assertEqual(len(points), 1, "expected exactly one SleepSummary point")
        point = points[0]
        self.assertEqual(point["measurement"], "SleepSummary")
        return point

    def test_integer_hrv_is_written_as_float(self):
        point = self._sleep_summary_point(_sleep_payload(57))
        value = point["fields"]["avgOvernightHrv"]
        self.assertEqual(value, 57.0)
        self.assertIsInstance(value, float)

    def test_float_hrv_stays_float(self):
        point = self._sleep_summary_point(_sleep_payload(57.0))
        value = point["fields"]["avgOvernightHrv"]
        self.assertEqual(value, 57.0)
        self.assertIsInstance(value, float)

    def test_missing_hrv_preserves_none(self):
        point = self._sleep_summary_point(_sleep_payload(_MISSING))
        self.assertIsNone(point["fields"]["avgOvernightHrv"])

    def test_explicit_null_hrv_preserves_none(self):
        point = self._sleep_summary_point(_sleep_payload(None))
        self.assertIsNone(point["fields"]["avgOvernightHrv"])

    def test_point_still_carries_timestamp_and_tags(self):
        point = self._sleep_summary_point(_sleep_payload(57.0))
        expected_time = datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc).isoformat()
        self.assertEqual(point["time"], expected_time)
        self.assertIn("Device", point["tags"])
        self.assertIn("Database_Name", point["tags"])


if __name__ == "__main__":
    unittest.main()
