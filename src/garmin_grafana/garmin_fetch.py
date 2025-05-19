# %%
import base64, requests, time, pytz, logging, os, sys, dotenv, io, zipfile
from fitparse import FitFile, FitParseError
from datetime import datetime, timedelta
from influxdb import InfluxDBClient
from influxdb.exceptions import InfluxDBClientError
from influxdb_client_3 import InfluxDBClient3, InfluxDBError
import xml.etree.ElementTree as ET
from garth.exc import GarthHTTPError
from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)
garmin_obj = None
banner_text = """

*****  █▀▀ ▄▀█ █▀█ █▀▄▀█ █ █▄ █    █▀▀ █▀█ ▄▀█ █▀▀ ▄▀█ █▄ █ ▄▀█  *****
*****  █▄█ █▀█ █▀▄ █ ▀ █ █ █ ▀█    █▄█ █▀▄ █▀█ █▀  █▀█ █ ▀█ █▀█  *****

______________________________________________________________________

By Arpan Ghosh | Please consider supporting the project if you love it
______________________________________________________________________

"""
print(banner_text)

env_override = dotenv.load_dotenv("override-default-vars.env", override=True)
if env_override:
    logging.warning("System ENV variables are overridden with override-default-vars.env")

# %%
INFLUXDB_VERSION = os.getenv("INFLUXDB_VERSION",'1') # Your influxdb database version (accepted values are '1' or '3')
assert INFLUXDB_VERSION in ['1','3'], "Only InfluxDB version 1 or 3 is allowed - please ensure to set this value to either 1 or 3"
INFLUXDB_HOST = os.getenv("INFLUXDB_HOST",'your.influxdb.hostname') # Required
INFLUXDB_PORT = int(os.getenv("INFLUXDB_PORT", 8086)) # Required
INFLUXDB_USERNAME = os.getenv("INFLUXDB_USERNAME", 'influxdb_username') # Required
INFLUXDB_PASSWORD = os.getenv("INFLUXDB_PASSWORD", 'influxdb_access_password') # Required
INFLUXDB_DATABASE = os.getenv("INFLUXDB_DATABASE", 'GarminStats') # Required
INFLUXDB_V3_ACCESS_TOKEN = os.getenv("INFLUXDB_V3_ACCESS_TOKEN",'') # InfluxDB V3 Access token, required only for InfluxDB V3
TOKEN_DIR = os.getenv("TOKEN_DIR", "~/.garminconnect") # optional
GARMINCONNECT_EMAIL = os.environ.get("GARMINCONNECT_EMAIL", None) # optional, asks in prompt on run if not provided
GARMINCONNECT_PASSWORD = base64.b64decode(os.getenv("GARMINCONNECT_BASE64_PASSWORD")).decode("utf-8") if os.getenv("GARMINCONNECT_BASE64_PASSWORD") != None else None # optional, asks in prompt on run if not provided
GARMINCONNECT_IS_CN = True if os.getenv("GARMINCONNECT_IS_CN") in ['True', 'true', 'TRUE','t', 'T', 'yes', 'Yes', 'YES', '1'] else False # optional if you are using a Chinese account
GARMIN_DEVICENAME = os.getenv("GARMIN_DEVICENAME", "Unknown")  # optional, attepmts to set the same automatically if not given
AUTO_DATE_RANGE = False if os.getenv("AUTO_DATE_RANGE") in ['False','false','FALSE','f','F','no','No','NO','0'] else True # optional
MANUAL_START_DATE = os.getenv("MANUAL_START_DATE", None) # optional, in YYYY-MM-DD format, if you want to bulk update only from specific date
MANUAL_END_DATE = os.getenv("MANUAL_END_DATE", datetime.today().strftime('%Y-%m-%d')) # optional, in YYYY-MM-DD format, if you want to bulk update until a specific date
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO") # optional
FETCH_FAILED_WAIT_SECONDS = int(os.getenv("FETCH_FAILED_WAIT_SECONDS", 1800)) # optional
RATE_LIMIT_CALLS_SECONDS = int(os.getenv("RATE_LIMIT_CALLS_SECONDS", 5)) # optional
INFLUXDB_ENDPOINT_IS_HTTP = False if os.getenv("INFLUXDB_ENDPOINT_IS_HTTP") in ['False','false','FALSE','f','F','no','No','NO','0'] else True # optional
GARMIN_DEVICENAME_AUTOMATIC = False if GARMIN_DEVICENAME != "Unknown" else True # optional
UPDATE_INTERVAL_SECONDS = int(os.getenv("UPDATE_INTERVAL_SECONDS", 300)) # optional
FETCH_SELECTION = os.getenv("FETCH_SELECTION", "daily_avg,sleep,steps,heartrate,stress,breathing,hrv,vo2,activity,race_prediction,body_composition") # additional available values are lactate_threshold,training_status,training_readiness,hill_score,endurance_score,blood_pressure,hydration which you can add to the list seperated by , without any space
LACTATE_THRESHOLD_SPORTS = os.getenv("LACTATE_THRESHOLD_SPORTS", "RUNNING").upper().split(",") # Garmin currently implements RUNNING, but has provisions for CYCLING, and SWIMMING
KEEP_FIT_FILES = True if os.getenv("KEEP_FIT_FILES") in ['True', 'true', 'TRUE','t', 'T', 'yes', 'Yes', 'YES', '1'] else False # optional
FIT_FILE_STORAGE_LOCATION = os.getenv("FIT_FILE_STORAGE_LOCATION", os.path.join(os.path.expanduser("~"), "fit_filestore"))
ALWAYS_PROCESS_FIT_FILES = True if os.getenv("ALWAYS_PROCESS_FIT_FILES") in ['True', 'true', 'TRUE','t', 'T', 'yes', 'Yes', 'YES', '1'] else False # optional, will process all FIT files for all activities including indoor ones lacking GPS data
REQUEST_INTRADAY_DATA_REFRESH = True if os.getenv("REQUEST_INTRADAY_DATA_REFRESH") in ['True', 'true', 'TRUE','t', 'T', 'yes', 'Yes', 'YES', '1'] else False # optional, This requests data refresh for the intraday data (older than 6 months) - see issue #77. Pauses the script for 24 hours when the daily limit is reached.
IGNORE_INTRADAY_DATA_REFRESH_DAYS = int(os.getenv("IGNORE_INTRADAY_DATA_REFRESH_DAYS", 30)) # optional, ignores the REQUEST_INTRADAY_DATA_REFRESH for the specified number of days from current date. 
TAG_MEASUREMENTS_WITH_USER_EMAIL = True if os.getenv("TAG_MEASUREMENTS_WITH_USER_EMAIL") in ['True', 'true', 'TRUE','t', 'T', 'yes', 'Yes', 'YES', '1'] else False # Adds an additional "User_ID" tag in each measurement for multi user database support - see #96
FORCE_REPROCESS_ACTIVITIES = False if os.getenv("FORCE_REPROCESS_ACTIVITIES") in ['False','false','FALSE','f','F','no','No','NO','0'] else True # optional, will enable re-processing of fit files when set to true, may skip activities if set to false (issue #30)
USER_TIMEZONE = os.getenv("USER_TIMEZONE", "") # optional, fetches timezone info from last activity automatically if left blank
PARSED_ACTIVITY_ID_LIST = []

# %%
for handler in logging.root.handlers[:]:
    logging.root.removeHandler(handler)

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

# %%
try:
    if INFLUXDB_ENDPOINT_IS_HTTP:
        if INFLUXDB_VERSION == '1':
            influxdbclient = InfluxDBClient(host=INFLUXDB_HOST, port=INFLUXDB_PORT, username=INFLUXDB_USERNAME, password=INFLUXDB_PASSWORD)
            influxdbclient.switch_database(INFLUXDB_DATABASE)
        else:
            influxdbclient = InfluxDBClient3(
            host=f"http://{INFLUXDB_HOST}:{INFLUXDB_PORT}",
            token=INFLUXDB_V3_ACCESS_TOKEN,
            database=INFLUXDB_DATABASE
            )
    else:
        if INFLUXDB_VERSION == '1':
            influxdbclient = InfluxDBClient(host=INFLUXDB_HOST, port=INFLUXDB_PORT, username=INFLUXDB_USERNAME, password=INFLUXDB_PASSWORD, ssl=True, verify_ssl=True)
            influxdbclient.switch_database(INFLUXDB_DATABASE)
        else:
            influxdbclient = InfluxDBClient3(
            host=f"https://{INFLUXDB_HOST}:{INFLUXDB_PORT}",
            token=INFLUXDB_V3_ACCESS_TOKEN,
            database=INFLUXDB_DATABASE
            )
    demo_point = {
    'measurement': 'DemoPoint',
    'time': '1970-01-01T00:00:00+00:00',
    'tags': {'DemoTag': 'DemoTagValue'},
    'fields': {'DemoField': 0}
     }
    # The following code block tests the connection by writing/overwriting a demo point. raises error and aborts if connection fails. 
    if INFLUXDB_VERSION == '1':
        influxdbclient.write_points([demo_point])
    else:
        influxdbclient.write(record=[demo_point])
except (InfluxDBClientError, InfluxDBError) as err:
    logging.error("Unable to connect with influxdb database! Aborted")
    raise InfluxDBClientError("InfluxDB connection failed:" + str(err))

# %%
def iter_days(start_date: str, end_date: str):
    start = datetime.strptime(start_date, '%Y-%m-%d')
    end = datetime.strptime(end_date, '%Y-%m-%d')
    current = end

    while current >= start:
        yield current.strftime('%Y-%m-%d')
        current -= timedelta(days=1)


# %%
def garmin_login():
    try:
        logging.info(f"Trying to login to Garmin Connect using token data from directory '{TOKEN_DIR}'...")
        garmin = Garmin()
        garmin.login(TOKEN_DIR)
        logging.info("login to Garmin Connect successful using stored session tokens.")

    except (FileNotFoundError, GarthHTTPError, GarminConnectAuthenticationError):
        logging.warning("Session is expired or login information not present/incorrect. You'll need to log in again...login with your Garmin Connect credentials to generate them.")
        try:
            user_email = GARMINCONNECT_EMAIL or input("Enter Garminconnect Login e-mail: ")
            user_password = GARMINCONNECT_PASSWORD or input("Enter Garminconnect password (characters will be visible): ")
            garmin = Garmin(
                email=user_email, password=user_password, is_cn=GARMINCONNECT_IS_CN, return_on_mfa=True
            )
            result1, result2 = garmin.login()
            if result1 == "needs_mfa":  # MFA is required
                mfa_code = input("MFA one-time code (via email or SMS): ")
                garmin.resume_login(result2, mfa_code)

            garmin.garth.dump(TOKEN_DIR)
            logging.info(f"Oauth tokens stored in '{TOKEN_DIR}' directory for future use")

            garmin.login(TOKEN_DIR)
            logging.info("login to Garmin Connect successful using stored session tokens. Please restart the script. Saved logins will be used automatically")
            exit() # terminating script

        except (
            FileNotFoundError,
            GarthHTTPError,
            GarminConnectAuthenticationError,
            requests.exceptions.HTTPError,
        ) as err:
            logging.error(str(err))
            raise Exception("Session is expired : please login again and restart the script")

    return garmin

# %%
def write_points_to_influxdb(points):
    write_chunk_size = 20000
    try:
        if len(points) != 0:
            if TAG_MEASUREMENTS_WITH_USER_EMAIL:
                for item in points:
                    item['tags'].update({'User_ID': garmin_obj.garth.profile.get('userName','Unknown')})
            # Write in chunks - Issue reported for large activities data containing >20000 points - Error 413 : payload too large
            for i in range(0, len(points), write_chunk_size):
                if INFLUXDB_VERSION == '1':
                    influxdbclient.write_points(points[i:i + write_chunk_size])
                else:
                    influxdbclient.write(record=points[i:i + write_chunk_size])
            logging.info("Success : updated influxDB database with new points")
    except (InfluxDBClientError, InfluxDBError) as err:
        logging.error("Write failed : Unable to connect with database! " + str(err))

# %%
def get_daily_stats(date_str):
    points_list = []
    stats_json = garmin_obj.get_stats(date_str)
    if stats_json['wellnessStartTimeGmt'] and datetime.strptime(date_str, "%Y-%m-%d") < datetime.today():
        points_list.append({
            "measurement":  "DailyStats",
            "time": pytz.timezone("UTC").localize(datetime.strptime(stats_json['wellnessStartTimeGmt'], "%Y-%m-%dT%H:%M:%S.%f")).isoformat(),
            "tags": {
                "Device": GARMIN_DEVICENAME,
                "Database_Name": INFLUXDB_DATABASE
            },
            "fields": {
                "activeKilocalories": stats_json.get('activeKilocalories'),
                "bmrKilocalories": stats_json.get('bmrKilocalories'),

                'totalSteps': stats_json.get('totalSteps'),
                'totalDistanceMeters': stats_json.get('totalDistanceMeters'),

                "highlyActiveSeconds": stats_json.get("highlyActiveSeconds"),
                "activeSeconds": stats_json.get("activeSeconds"),
                "sedentarySeconds": stats_json.get("sedentarySeconds"),
                "sleepingSeconds": stats_json.get("sleepingSeconds"),
                "moderateIntensityMinutes": stats_json.get("moderateIntensityMinutes"),
                "vigorousIntensityMinutes": stats_json.get("vigorousIntensityMinutes"),

                "floorsAscendedInMeters": stats_json.get("floorsAscendedInMeters"),
                "floorsDescendedInMeters": stats_json.get("floorsDescendedInMeters"),
                "floorsAscended": stats_json.get("floorsAscended"),
                "floorsDescended": stats_json.get("floorsDescended"),

                "minHeartRate": stats_json.get("minHeartRate"),
                "maxHeartRate": stats_json.get("maxHeartRate"),
                "restingHeartRate": stats_json.get("restingHeartRate"),
                "minAvgHeartRate": stats_json.get("minAvgHeartRate"),
                "maxAvgHeartRate": stats_json.get("maxAvgHeartRate"),
                
                "stressDuration": stats_json.get("stressDuration"),
                "restStressDuration": stats_json.get("restStressDuration"),
                "activityStressDuration": stats_json.get("activityStressDuration"),
                "uncategorizedStressDuration": stats_json.get("uncategorizedStressDuration"),
                "totalStressDuration": stats_json.get("totalStressDuration"),
                "lowStressDuration": stats_json.get("lowStressDuration"),
                "mediumStressDuration": stats_json.get("mediumStressDuration"),
                "highStressDuration": stats_json.get("highStressDuration"),
                
                "stressPercentage": stats_json.get("stressPercentage"),
                "restStressPercentage": stats_json.get("restStressPercentage"),
                "activityStressPercentage": stats_json.get("activityStressPercentage"),
                "uncategorizedStressPercentage": stats_json.get("uncategorizedStressPercentage"),
                "lowStressPercentage": stats_json.get("lowStressPercentage"),
                "mediumStressPercentage": stats_json.get("mediumStressPercentage"),
                "highStressPercentage": stats_json.get("highStressPercentage"),
                
                "bodyBatteryChargedValue": stats_json.get("bodyBatteryChargedValue"),
                "bodyBatteryDrainedValue": stats_json.get("bodyBatteryDrainedValue"),
                "bodyBatteryHighestValue": stats_json.get("bodyBatteryHighestValue"),
                "bodyBatteryLowestValue": stats_json.get("bodyBatteryLowestValue"),
                "bodyBatteryDuringSleep": stats_json.get("bodyBatteryDuringSleep"),
                "bodyBatteryAtWakeTime": stats_json.get("bodyBatteryAtWakeTime"),
                
                "averageSpo2": stats_json.get("averageSpo2"),
                "lowestSpo2": stats_json.get("lowestSpo2"),
            }
        })
        if points_list:
            logging.info(f"Success : Fetching daily metrics for date {date_str}")
        return points_list
    else:
        logging.debug("No daily stat data available for the give date " + date_str)
        return []
    

# %%
def get_last_sync():
    global GARMIN_DEVICENAME
    points_list = []
    sync_data = garmin_obj.get_device_last_used()
    if GARMIN_DEVICENAME_AUTOMATIC:
        GARMIN_DEVICENAME = sync_data.get('lastUsedDeviceName') or "Unknown"
    points_list.append({
        "measurement":  "DeviceSync",
        "time": datetime.fromtimestamp(sync_data['lastUsedDeviceUploadTime']/1000, tz=pytz.timezone("UTC")).isoformat(),
        "tags": {
            "Device": GARMIN_DEVICENAME,
            "Database_Name": INFLUXDB_DATABASE
        },
        "fields": {
            "imageUrl": sync_data.get('imageUrl'),
            "Device_Name": GARMIN_DEVICENAME
        }
    })
    if points_list:
        logging.info(f"Success : Updated device last sync time")
    else:
        logging.warning("No associated/synced Garmin device found with your account")
    return points_list

# %%
def get_sleep_data(date_str):
    points_list = []
    all_sleep_data = garmin_obj.get_sleep_data(date_str)
    sleep_json = all_sleep_data.get("dailySleepDTO", None)
    if sleep_json["sleepEndTimestampGMT"]:
        points_list.append({
        "measurement":  "SleepSummary",
        "time": datetime.fromtimestamp(sleep_json["sleepEndTimestampGMT"]/1000, tz=pytz.timezone("UTC")).isoformat(),
        "tags": {
            "Device": GARMIN_DEVICENAME,
            "Database_Name": INFLUXDB_DATABASE
            },
        "fields": {
            "sleepTimeSeconds": sleep_json.get("sleepTimeSeconds"),
            "deepSleepSeconds": sleep_json.get("deepSleepSeconds"),
            "lightSleepSeconds": sleep_json.get("lightSleepSeconds"),
            "remSleepSeconds": sleep_json.get("remSleepSeconds"),
            "awakeSleepSeconds": sleep_json.get("awakeSleepSeconds"),
            "averageSpO2Value": sleep_json.get("averageSpO2Value"),
            "lowestSpO2Value": sleep_json.get("lowestSpO2Value"),
            "highestSpO2Value": sleep_json.get("highestSpO2Value"),
            "averageRespirationValue": sleep_json.get("averageRespirationValue"),
            "lowestRespirationValue": sleep_json.get("lowestRespirationValue"),
            "highestRespirationValue": sleep_json.get("highestRespirationValue"),
            "awakeCount": sleep_json.get("awakeCount"),
            "avgSleepStress": sleep_json.get("avgSleepStress"),
            "sleepScore": ((sleep_json.get("sleepScores") or {}).get("overall") or {}).get("value"),
            "restlessMomentsCount": all_sleep_data.get("restlessMomentsCount"),
            "avgOvernightHrv": all_sleep_data.get("avgOvernightHrv"),
            "bodyBatteryChange": all_sleep_data.get("bodyBatteryChange"),
            "restingHeartRate": all_sleep_data.get("restingHeartRate")
            }
        })
    sleep_movement_intraday = all_sleep_data.get("sleepMovement")
    if sleep_movement_intraday:
        for entry in sleep_movement_intraday:
            points_list.append({
                "measurement":  "SleepIntraday",
                "time": pytz.timezone("UTC").localize(datetime.strptime(entry["startGMT"], "%Y-%m-%dT%H:%M:%S.%f")).isoformat(),
                "tags": {
                    "Device": GARMIN_DEVICENAME,
                    "Database_Name": INFLUXDB_DATABASE
                },
                "fields": {
                    "SleepMovementActivityLevel": entry.get("activityLevel",-1),
                    "SleepMovementActivitySeconds": int((datetime.strptime(entry["endGMT"], "%Y-%m-%dT%H:%M:%S.%f") - datetime.strptime(entry["startGMT"], "%Y-%m-%dT%H:%M:%S.%f")).total_seconds())
                }
            })
    sleep_levels_intraday = all_sleep_data.get("sleepLevels")
    if sleep_levels_intraday:
        for entry in sleep_levels_intraday:
            if entry.get("activityLevel") or entry.get("activityLevel") == 0: # Include 0 for Deepsleep but not None - Refer to issue #43
                points_list.append({
                    "measurement":  "SleepIntraday",
                    "time": pytz.timezone("UTC").localize(datetime.strptime(entry["startGMT"], "%Y-%m-%dT%H:%M:%S.%f")).isoformat(),
                    "tags": {
                        "Device": GARMIN_DEVICENAME,
                        "Database_Name": INFLUXDB_DATABASE
                    },
                    "fields": {
                        "SleepStageLevel": entry.get("activityLevel"),
                        "SleepStageSeconds": int((datetime.strptime(entry["endGMT"], "%Y-%m-%dT%H:%M:%S.%f") - datetime.strptime(entry["startGMT"], "%Y-%m-%dT%H:%M:%S.%f")).total_seconds())
                    }
                })
    sleep_restlessness_intraday = all_sleep_data.get("sleepRestlessMoments")
    if sleep_restlessness_intraday:
        for entry in sleep_restlessness_intraday:
            if entry.get("value"):
                points_list.append({
                    "measurement":  "SleepIntraday",
                    "time": datetime.fromtimestamp(entry["startGMT"]/1000, tz=pytz.timezone("UTC")).isoformat(),
                    "tags": {
                        "Device": GARMIN_DEVICENAME,
                        "Database_Name": INFLUXDB_DATABASE
                    },
                    "fields": {
                        "sleepRestlessValue": entry.get("value")
                    }
                })
    sleep_spo2_intraday = all_sleep_data.get("wellnessEpochSPO2DataDTOList")
    if sleep_spo2_intraday:
        for entry in sleep_spo2_intraday:
            if entry.get("spo2Reading"):
                points_list.append({
                    "measurement":  "SleepIntraday",
                    "time": pytz.timezone("UTC").localize(datetime.strptime(entry["epochTimestamp"], "%Y-%m-%dT%H:%M:%S.%f")).isoformat(),
                    "tags": {
                        "Device": GARMIN_DEVICENAME,
                        "Database_Name": INFLUXDB_DATABASE
                    },
                    "fields": {
                        "spo2Reading": entry.get("spo2Reading")
                    }
                })
    sleep_respiration_intraday = all_sleep_data.get("wellnessEpochRespirationDataDTOList")
    if sleep_respiration_intraday:
        for entry in sleep_respiration_intraday:
            if entry.get("respirationValue"):
                points_list.append({
                    "measurement":  "SleepIntraday",
                    "time": datetime.fromtimestamp(entry["startTimeGMT"]/1000, tz=pytz.timezone("UTC")).isoformat(),
                    "tags": {
                        "Device": GARMIN_DEVICENAME,
                        "Database_Name": INFLUXDB_DATABASE
                    },
                    "fields": {
                        "respirationValue": entry.get("respirationValue")
                    }
                })
    sleep_heart_rate_intraday = all_sleep_data.get("sleepHeartRate")
    if sleep_heart_rate_intraday:
        for entry in sleep_heart_rate_intraday:
            if entry.get("value"):
                points_list.append({
                    "measurement":  "SleepIntraday",
                    "time": datetime.fromtimestamp(entry["startGMT"]/1000, tz=pytz.timezone("UTC")).isoformat(),
                    "tags": {
                        "Device": GARMIN_DEVICENAME,
                        "Database_Name": INFLUXDB_DATABASE
                    },
                    "fields": {
                        "heartRate": entry.get("value")
                    }
                })
    sleep_stress_intraday = all_sleep_data.get("sleepStress")
    if sleep_stress_intraday:
        for entry in sleep_stress_intraday:
            if entry.get("value"):
                points_list.append({
                    "measurement":  "SleepIntraday",
                    "time": datetime.fromtimestamp(entry["startGMT"]/1000, tz=pytz.timezone("UTC")).isoformat(),
                    "tags": {
                        "Device": GARMIN_DEVICENAME,
                        "Database_Name": INFLUXDB_DATABASE
                    },
                    "fields": {
                        "stressValue": entry.get("value")
                    }
                })
    sleep_bb_intraday = all_sleep_data.get("sleepBodyBattery")
    if sleep_bb_intraday:
        for entry in sleep_bb_intraday:
            if entry.get("value"):
                points_list.append({
                    "measurement":  "SleepIntraday",
                    "time": datetime.fromtimestamp(entry["startGMT"]/1000, tz=pytz.timezone("UTC")).isoformat(),
                    "tags": {
                        "Device": GARMIN_DEVICENAME,
                        "Database_Name": INFLUXDB_DATABASE
                    },
                    "fields": {
                        "bodyBattery": entry.get("value")
                    }
                })
    sleep_hrv_intraday = all_sleep_data.get("hrvData")
    if sleep_hrv_intraday:
        for entry in sleep_hrv_intraday:
            if entry.get("value"):
                points_list.append({
                    "measurement":  "SleepIntraday",
                    "time": datetime.fromtimestamp(entry["startGMT"]/1000, tz=pytz.timezone("UTC")).isoformat(),
                    "tags": {
                        "Device": GARMIN_DEVICENAME,
                        "Database_Name": INFLUXDB_DATABASE
                    },
                    "fields": {
                        "hrvData": entry.get("value")
                    }
                })
    if points_list:
        logging.info(f"Success : Fetching intraday sleep metrics for date {date_str}")
    return points_list

# %%
def get_intraday_hr(date_str):
    points_list = []
    hr_list = garmin_obj.get_heart_rates(date_str).get("heartRateValues") or []
    for entry in hr_list:
        if entry[1]:
            points_list.append({
                    "measurement":  "HeartRateIntraday",
                    "time": datetime.fromtimestamp(entry[0]/1000, tz=pytz.timezone("UTC")).isoformat(),
                    "tags": {
                        "Device": GARMIN_DEVICENAME,
                        "Database_Name": INFLUXDB_DATABASE
                    },
                    "fields": {
                        "HeartRate": entry[1]
                    }
                })
    if points_list:
        logging.info(f"Success : Fetching intraday Heart Rate for date {date_str}")
    return points_list

# %%
def get_intraday_steps(date_str):
    points_list = []
    steps_list = garmin_obj.get_steps_data(date_str)
    for entry in steps_list:
        if entry["steps"] or entry["steps"] == 0:
            points_list.append({
                    "measurement":  "StepsIntraday",
                    "time": pytz.timezone("UTC").localize(datetime.strptime(entry['startGMT'], "%Y-%m-%dT%H:%M:%S.%f")).isoformat(),
                    "tags": {
                        "Device": GARMIN_DEVICENAME,
                        "Database_Name": INFLUXDB_DATABASE
                    },
                    "fields": {
                        "StepsCount": entry["steps"]
                    }
                })
    if points_list:
        logging.info(f"Success : Fetching intraday steps for date {date_str}")
    return points_list

# %%
def get_intraday_stress(date_str):
    points_list = []
    stress_list = garmin_obj.get_stress_data(date_str).get('stressValuesArray') or []
    for entry in stress_list:
        if entry[1] or entry[1] == 0:
            points_list.append({
                    "measurement":  "StressIntraday",
                    "time": datetime.fromtimestamp(entry[0]/1000, tz=pytz.timezone("UTC")).isoformat(),
                    "tags": {
                        "Device": GARMIN_DEVICENAME,
                        "Database_Name": INFLUXDB_DATABASE
                    },
                    "fields": {
                        "stressLevel": entry[1]
                    }
                })
    bb_list = garmin_obj.get_stress_data(date_str).get('bodyBatteryValuesArray') or []
    for entry in bb_list:
        if entry[2] or entry[2] == 0:
            points_list.append({
                    "measurement":  "BodyBatteryIntraday",
                    "time": datetime.fromtimestamp(entry[0]/1000, tz=pytz.timezone("UTC")).isoformat(),
                    "tags": {
                        "Device": GARMIN_DEVICENAME,
                        "Database_Name": INFLUXDB_DATABASE
                    },
                    "fields": {
                        "BodyBatteryLevel": entry[2]
                    }
                })
    if points_list:
        logging.info(f"Success : Fetching intraday stress and Body Battery values for date {date_str}")
    return points_list

# %%
def get_intraday_br(date_str):
    points_list = []
    br_list = garmin_obj.get_respiration_data(date_str).get('respirationValuesArray') or []
    for entry in br_list:
        if entry[1]:
            points_list.append({
                    "measurement":  "BreathingRateIntraday",
                    "time": datetime.fromtimestamp(entry[0]/1000, tz=pytz.timezone("UTC")).isoformat(),
                    "tags": {
                        "Device": GARMIN_DEVICENAME,
                        "Database_Name": INFLUXDB_DATABASE
                    },
                    "fields": {
                        "BreathingRate": entry[1]
                    }
                })
    if points_list:
        logging.info(f"Success : Fetching intraday Breathing Rate for date {date_str}")
    return points_list

# %%
def get_intraday_hrv(date_str):
    points_list = []
    hrv_list = (garmin_obj.get_hrv_data(date_str) or {}).get('hrvReadings') or []
    for entry in hrv_list:
        if entry.get('hrvValue'):
            points_list.append({
                    "measurement":  "HRV_Intraday",
                    "time": pytz.timezone("UTC").localize(datetime.strptime(entry['readingTimeGMT'],"%Y-%m-%dT%H:%M:%S.%f")).isoformat(),
                    "tags": {
                        "Device": GARMIN_DEVICENAME,
                        "Database_Name": INFLUXDB_DATABASE
                    },
                    "fields": {
                        "hrvValue": entry.get('hrvValue')
                    }
                })
    if points_list:
        logging.info(f"Success : Fetching intraday HRV for date {date_str}")
    return points_list

# %%
def get_body_composition(date_str):
    points_list = []
    weight_list_all = garmin_obj.get_weigh_ins(date_str, date_str).get('dailyWeightSummaries', [])
    if weight_list_all:
        weight_list = weight_list_all[0].get('allWeightMetrics', [])
        for weight_dict in weight_list:
            data_fields = {
                    "weight": weight_dict.get("weight"),
                    "bmi": weight_dict.get("bmi"),
                    "bodyFat": weight_dict.get("bodyFat"),
                    "bodyWater": weight_dict.get("bodyWater"),
                    "boneMass": weight_dict.get("boneMass"),
                    "muscleMass": weight_dict.get("muscleMass"),
                    "physiqueRating": weight_dict.get("physiqueRating"),
                    "visceralFat": weight_dict.get("visceralFat"),
                    "metabolicAge": datetime.fromtimestamp(int(weight_dict.get("metabolicAge")/1000), tz=pytz.timezone("UTC")) if weight_dict.get("metabolicAge") else None
                }
            if not all(value is None for value in data_fields.values()):
                points_list.append({
                    "measurement":  "BodyComposition",
                    "time": datetime.fromtimestamp((weight_dict['timestampGMT']/1000) , tz=pytz.timezone("UTC")).isoformat() if weight_dict['timestampGMT'] else datetime.strptime(date_str, "%Y-%m-%d").replace(hour=0, tzinfo=pytz.UTC).isoformat(), # Use GMT 00:00 is timestamp is not available (issue #15)
                    "tags": {
                        "Device": GARMIN_DEVICENAME,
                        "Database_Name": INFLUXDB_DATABASE,
                        "Frequency" : "Intraday",
                        "SourceType" : weight_dict.get('sourceType', "Unknown")
                    },
                    "fields": data_fields
                })
        logging.info(f"Success : Fetching intraday Body Composition (Weight, BMI etc) for date {date_str}")
    return points_list

# %%
def get_activity_summary(date_str):
    points_list = []
    activity_with_gps_id_dict = {}
    activity_list = garmin_obj.get_activities_by_date(date_str, date_str)
    for activity in activity_list:
        if activity.get('hasPolyline') or ALWAYS_PROCESS_FIT_FILES: # will process FIT files lacking GPS data if ALWAYS_PROCESS_FIT_FILES is set to True
            if not activity.get('hasPolyline'):
                logging.warning(f"Activity ID {activity.get('activityId')} got no GPS data - yet, activity FIT file data will be processed as ALWAYS_PROCESS_FIT_FILES is on")
            activity_with_gps_id_dict[activity.get('activityId')] = (activity.get('activityType') or {}).get('typeKey', "Unknown")
        if "startTimeGMT" in activity: # "startTimeGMT" should be available for all activities (fix #13)
            points_list.append({
                "measurement":  "ActivitySummary",
                "time": datetime.strptime(activity["startTimeGMT"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=pytz.UTC).isoformat(),
                "tags": {
                    "Device": GARMIN_DEVICENAME,
                    "Database_Name": INFLUXDB_DATABASE,
                    "ActivityID": activity.get('activityId'),
                    "ActivitySelector": datetime.strptime(activity["startTimeGMT"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=pytz.UTC).strftime('%Y%m%dT%H%M%SUTC-') + (activity.get('activityType') or {}).get('typeKey', "Unknown")
                },
                "fields": {
                    "Activity_ID": activity.get('activityId'),
                    'Device_ID': activity.get('deviceId'),
                    'activityName': activity.get('activityName'),
                    'activityType': (activity.get('activityType') or {}).get('typeKey',None),
                    'distance': activity.get('distance'),
                    'elapsedDuration': activity.get('elapsedDuration'),
                    'movingDuration': activity.get('movingDuration'),
                    'averageSpeed': activity.get('averageSpeed'),
                    'maxSpeed': activity.get('maxSpeed'),
                    'calories': activity.get('calories'),
                    'bmrCalories': activity.get('bmrCalories'),
                    'averageHR': activity.get('averageHR'),
                    'maxHR': activity.get('maxHR'),
                    'locationName': activity.get('locationName'),
                    'lapCount': activity.get('lapCount'),
                    'hrTimeInZone_1': activity.get('hrTimeInZone_1'),
                    'hrTimeInZone_2': activity.get('hrTimeInZone_2'),
                    'hrTimeInZone_3': activity.get('hrTimeInZone_3'),
                    'hrTimeInZone_4': activity.get('hrTimeInZone_4'),
                    'hrTimeInZone_5': activity.get('hrTimeInZone_5'),
                }
            })
            points_list.append({
                "measurement":  "ActivitySummary",
                "time": (datetime.strptime(activity["startTimeGMT"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=pytz.UTC) + timedelta(seconds=int(activity.get('elapsedDuration', 0)))).isoformat(),
                "tags": {
                    "Device": GARMIN_DEVICENAME,
                    "Database_Name": INFLUXDB_DATABASE,
                    "ActivityID": activity.get('activityId'),
                    "ActivitySelector": datetime.strptime(activity["startTimeGMT"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=pytz.UTC).strftime('%Y%m%dT%H%M%SUTC-') + (activity.get('activityType') or {}).get('typeKey', "Unknown")
                },
                "fields": {
                    "Activity_ID": activity.get('activityId'),
                    'Device_ID': activity.get('deviceId'),
                    'activityName': "END",
                    'activityType': "No Activity",
                }
            })
            logging.info(f"Success : Fetching Activity summary with id {activity.get('activityId')} for date {date_str}")
        else:
            logging.warning(f"Skipped : Start Timestamp missing for activity id {activity.get('activityId')} for date {date_str}")
    return points_list, activity_with_gps_id_dict

# %%
def fetch_activity_GPS(activityIDdict): # Uses FIT file by default, falls back to TCX
    points_list = []
    for activityID in activityIDdict.keys():
        activity_type = activityIDdict[activityID]
        if (activityID in PARSED_ACTIVITY_ID_LIST) and (not FORCE_REPROCESS_ACTIVITIES):
            logging.info(f"Skipping : Activity ID {activityID} has already been processed within current runtime")
            return []
        if (activityID in PARSED_ACTIVITY_ID_LIST) and (FORCE_REPROCESS_ACTIVITIES):
            logging.info(f"Re-processing : Activity ID {activityID} (FORCE_REPROCESS_ACTIVITIES is on)")
        try:
            zip_data = garmin_obj.download_activity(activityID, dl_fmt=garmin_obj.ActivityDownloadFormat.ORIGINAL)
            logging.info(f"Processing : Activity ID {activityID} FIT file data - this may take a while...")
            zip_buffer = io.BytesIO(zip_data)
            with zipfile.ZipFile(zip_buffer) as zip_ref:
                fit_filename = next((f for f in zip_ref.namelist() if f.endswith('.fit')), None)
                if not fit_filename:
                    raise FileNotFoundError(f"No FIT file found in the downloaded zip archive for Activity ID {activityID}")
                else:
                    fit_data = zip_ref.read(fit_filename)
                    fit_file_buffer = io.BytesIO(fit_data)
                    fitfile = FitFile(fit_file_buffer)
                    fitfile.parse()
                    all_records_list = [record.get_values() for record in fitfile.get_messages('record')]
                    all_sessions_list = [record.get_values() for record in fitfile.get_messages('session')]
                    all_lengths_list = [record.get_values() for record in fitfile.get_messages('length')]
                    all_laps_list = [record.get_values() for record in fitfile.get_messages('lap')]
                    if len(all_records_list) == 0:
                        raise FileNotFoundError(f"No records found in FIT file for Activity ID {activityID} - Discarding FIT file")
                    else:
                        activity_start_time = all_records_list[0]['timestamp'].replace(tzinfo=pytz.UTC)
                    for parsed_record in all_records_list:
                        if parsed_record.get('timestamp'):
                            point = {
                                "measurement": "ActivityGPS",
                                "time": parsed_record['timestamp'].replace(tzinfo=pytz.UTC).isoformat(), 
                                "tags": {
                                    "Device": GARMIN_DEVICENAME,
                                    "Database_Name": INFLUXDB_DATABASE,
                                    "ActivityID": activityID,
                                    "ActivitySelector": activity_start_time.strftime('%Y%m%dT%H%M%SUTC-') + activity_type
                                },
                                "fields": {
                                    "ActivityName": activity_type,
                                    "Activity_ID": activityID,
                                    "Latitude": int(parsed_record['position_lat']) * ( 180 / 2**31 ) if parsed_record.get('position_lat') else None,
                                    "Longitude": int(parsed_record['position_long']) * ( 180 / 2**31 ) if parsed_record.get('position_long') else None,
                                    "Altitude": parsed_record.get('enhanced_altitude', None) or parsed_record.get('altitude', None),
                                    "Distance": parsed_record.get('distance', None),
                                    "DurationSeconds": (parsed_record['timestamp'].replace(tzinfo=pytz.UTC) - activity_start_time).total_seconds(),
                                    "HeartRate": float(parsed_record.get('heart_rate', None)) if parsed_record.get('heart_rate', None) else None,
                                    "Speed": parsed_record.get('enhanced_speed', None) or parsed_record.get('speed', None),
                                    "Cadence": parsed_record.get('cadence', None),
                                    "Fractional_Cadence": parsed_record.get('fractional_cadence', None),
                                    "Temperature": parsed_record.get('temperature', None),
                                    "Accumulated_Power": parsed_record.get('accumulated_power', None),
                                    "Power": parsed_record.get('power', None)
                                }
                            }
                            points_list.append(point)
                    for session_record in all_sessions_list:
                        if session_record.get('start_time') or session_record.get('timestamp'):
                            point = {
                                "measurement": "ActivitySession",
                                "time": session_record['start_time'].replace(tzinfo=pytz.UTC).isoformat() or session_record['timestamp'].replace(tzinfo=pytz.UTC).isoformat(), 
                                "tags": {
                                    "Device": GARMIN_DEVICENAME,
                                    "Database_Name": INFLUXDB_DATABASE,
                                    "ActivityID": activityID,
                                    "ActivitySelector": activity_start_time.strftime('%Y%m%dT%H%M%SUTC-') + activity_type
                                },
                                "fields": {
                                    "Index": int(session_record.get('message_index', -1)) + 1,
                                    "ActivityName": activity_type,
                                    "Activity_ID": activityID,
                                    "Sport": session_record.get('sport', None),
                                    "Sub_Sport": session_record.get('sub_sport', None),
                                    "Pool_Length": session_record.get('pool_length', None),
                                    "Pool_Length_Unit": session_record.get('pool_length_unit', None),
                                    "Lengths": session_record.get('num_laps', None),
                                    "Laps": session_record.get('num_lengths', None),
                                    "Aerobic_Training": session_record.get('total_training_effect', None),
                                    "Anaerobic_Training": session_record.get('total_anaerobic_training_effect', None),
                                    "Primary_Benefit": session_record.get('primary_benefit', None),
                                    "Recovery_Time": session_record.get('recovery_time', None)
                                }
                            }
                            points_list.append(point)
                    for length_record in all_lengths_list:
                        if length_record.get('start_time') or length_record.get('timestamp'):
                            point = {
                                "measurement": "ActivityLength",
                                "time": length_record['start_time'].replace(tzinfo=pytz.UTC).isoformat() or length_record['timestamp'].replace(tzinfo=pytz.UTC).isoformat(), 
                                "tags": {
                                    "Device": GARMIN_DEVICENAME,
                                    "Database_Name": INFLUXDB_DATABASE,
                                    "ActivityID": activityID,
                                    "ActivitySelector": activity_start_time.strftime('%Y%m%dT%H%M%SUTC-') + activity_type
                                },
                                "fields": {
                                    "Index": int(length_record.get('message_index', -1)) + 1,
                                    "ActivityName": activity_type,
                                    "Activity_ID": activityID,
                                    "Elapsed_Time": length_record.get('total_elapsed_time', None),
                                    "Strokes": length_record.get('total_strokes', None),
                                    "Swim_Stroke": length_record.get('swim_stroke', None),
                                    "Avg_Speed": length_record.get('avg_speed', None),
                                    "Calories": length_record.get('total_calories', None),
                                    "Avg_Cadence": length_record.get('avg_swimming_cadence', None)
                                }
                            }
                            points_list.append(point)
                    for lap_record in all_laps_list:
                        if lap_record.get('start_time') or lap_record.get('timestamp'):
                            point = {
                                "measurement": "ActivityLap",
                                "time": lap_record['start_time'].replace(tzinfo=pytz.UTC).isoformat() or lap_record['timestamp'].replace(tzinfo=pytz.UTC).isoformat(), 
                                "tags": {
                                    "Device": GARMIN_DEVICENAME,
                                    "Database_Name": INFLUXDB_DATABASE,
                                    "ActivityID": activityID,
                                    "ActivitySelector": activity_start_time.strftime('%Y%m%dT%H%M%SUTC-') + activity_type
                                },
                                "fields": {
                                    "Index": int(lap_record.get('message_index', -1)) + 1,
                                    "ActivityName": activity_type,
                                    "Activity_ID": activityID,
                                    "Elapsed_Time": lap_record.get('total_elapsed_time', None),
                                    "Sport": lap_record.get('sport', None),
                                    "Lengths": lap_record.get('num_lengths', None),
                                    "Length_Index": lap_record.get('first_length_index', None),
                                    "Distance": lap_record.get('total_distance', None),
                                    "Cycles": lap_record.get('total_cycles', None),
                                    "Avg_Stroke_Distance": lap_record.get('avg_stroke_distance', None),
                                    "Moving_Duration": lap_record.get('total_moving_time', None),
                                    "Standing_Duration": lap_record.get('time_standing', None),
                                    "Avg_Speed": lap_record.get('enhanced_avg_speed', None),
                                    "Max_Speed": lap_record.get('enhanced_max_speed', None),
                                    "Calories": lap_record.get('total_calories', None),
                                    "Avg_Power": lap_record.get('avg_power', None),
                                    "Avg_HR": lap_record.get('avg_heart_rate', None),
                                    "Max_HR": lap_record.get('max_heart_rate', None),
                                    "Avg_Cadence": lap_record.get('avg_cadence', None),
                                    "Avg_Temperature": lap_record.get('avg_temperature', None)
                                }
                            }
                            points_list.append(point)
                    if KEEP_FIT_FILES:
                        os.makedirs(FIT_FILE_STORAGE_LOCATION, exist_ok=True)
                        fit_path = os.path.join(FIT_FILE_STORAGE_LOCATION, activity_start_time.strftime('%Y%m%dT%H%M%SUTC-') + activity_type + ".fit")
                        with open(fit_path, "wb") as f:
                            f.write(fit_data)
                        logging.info(f"Success : Activity ID {activityID} stored in output file {fit_path}")
        except (FileNotFoundError, FitParseError) as err:
            logging.error(err)
            logging.warning(f"Fallback : Failed to use FIT file for activityID {activityID} - Trying TCX file...")
            try:
                root = ET.fromstring(garmin_obj.download_activity(activityID, dl_fmt=garmin_obj.ActivityDownloadFormat.TCX).decode("UTF-8"))
            except requests.exceptions.Timeout as err:
                logging.warning(f"Request timeout for fetching large activity record {activityID} - skipping record")
                return []
            except Exception as err:
                logging.exception(f"Unable to fetch TCX for activity record {activityID} : skipping record")
                return []
            ns = {"tcx": "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2", "ns3": "http://www.garmin.com/xmlschemas/ActivityExtension/v2"}
            for activity in root.findall("tcx:Activities/tcx:Activity", ns):
                activity_start_time = datetime.fromisoformat(activity.find("tcx:Id", ns).text.strip("Z"))
                lap_index = 1
                for lap in activity.findall("tcx:Lap", ns):
                    lap_start_time = datetime.fromisoformat(lap.attrib.get("StartTime").strip("Z"))
                    for tp in lap.findall(".//tcx:Trackpoint", ns):
                        time_obj = datetime.fromisoformat(tp.findtext("tcx:Time", default=None, namespaces=ns).strip("Z"))
                        lat = tp.findtext("tcx:Position/tcx:LatitudeDegrees", default=None, namespaces=ns)
                        lon = tp.findtext("tcx:Position/tcx:LongitudeDegrees", default=None, namespaces=ns)
                        alt = tp.findtext("tcx:AltitudeMeters", default=None, namespaces=ns)
                        dist = tp.findtext("tcx:DistanceMeters", default=None, namespaces=ns)
                        hr = tp.findtext("tcx:HeartRateBpm/tcx:Value", default=None, namespaces=ns)
                        speed = tp.findtext("tcx:Extensions/ns3:TPX/ns3:Speed", default=None, namespaces=ns)

                        try: lat = float(lat)
                        except: lat = None
                        try: lon = float(lon)
                        except: lon = None
                        try: alt = float(alt)
                        except: alt = None
                        try: dist = float(dist)
                        except: dist = None
                        try: hr = float(hr)
                        except: hr = None
                        try: speed = float(speed)
                        except: speed = None

                        point = {
                            "measurement": "ActivityGPS",
                            "time": time_obj.isoformat(), 
                            "tags": {
                                "Device": GARMIN_DEVICENAME,
                                "Database_Name": INFLUXDB_DATABASE,
                                "ActivityID": activityID,
                                "ActivitySelector": activity_start_time.strftime('%Y%m%dT%H%M%SUTC-') + activity_type
                            },
                            "fields": {
                                "ActivityName": activity_type,
                                "Activity_ID": activityID,
                                "Latitude": lat,
                                "Longitude": lon,
                                "Altitude": alt,
                                "Distance": dist,
                                "DurationSeconds": (time_obj - activity_start_time).total_seconds(),
                                "HeartRate": hr,
                                "Speed": speed,
                                "lap": lap_index
                            }
                        }
                        points_list.append(point)
                    
                    lap_index += 1
        logging.info(f"Success : Fetching detailed activity for Activity ID {activityID}")
        PARSED_ACTIVITY_ID_LIST.append(activityID)
    return points_list

def get_lactate_threshold(date_str):
    points_list = []
    endpoints = {}
    
    for ltsport in LACTATE_THRESHOLD_SPORTS:
        endpoints[f"SpeedThreshold_{ltsport}"] = f"/biometric-service/stats/lactateThresholdSpeed/range/{date_str}/{date_str}?aggregation=daily&sport={ltsport}"
        endpoints[f"HeartRateThreshold_{ltsport}"] = f"/biometric-service/stats/lactateThresholdHeartRate/range/{date_str}/{date_str}?aggregation=daily&sport={ltsport}"

    for label, endpoint in endpoints.items():
        lt_list_all = garmin_obj.connectapi(endpoint)
        if lt_list_all:
            for lt_dict in lt_list_all:
                value = lt_dict.get("value")
                if value is not None:
                    points_list.append({
                        "measurement": "LactateThreshold",
                        "time": datetime.fromtimestamp(datetime.strptime(date_str, "%Y-%m-%d").timestamp(), tz=pytz.timezone("UTC")).isoformat(),
                        "tags": {
                            "Device": GARMIN_DEVICENAME,
                            "Database_Name": INFLUXDB_DATABASE
                        },
                        "fields": {f"{label}": value}
                    })
                    logging.info(f"Success : Fetching {label} for date {date_str}")

    return points_list
    
def get_training_status(date_str):
    points_list = []
    ts_list_all = garmin_obj.get_training_status(date_str)
    ts_training_data_all = (ts_list_all.get("mostRecentTrainingStatus") or {}).get("latestTrainingStatusData", {})

    if ts_training_data_all:
        for device_id, ts_dict in ts_training_data_all.items():
            logging.info(f"Success : Processing Training Status for Device {device_id}")
            data_fields = {
                "trainingStatus": ts_dict.get("trainingStatus"),
                "trainingStatusFeedbackPhrase": ts_dict.get("trainingStatusFeedbackPhrase"),
                "weeklyTrainingLoad": ts_dict.get("weeklyTrainingLoad"),
                "fitnessTrend": ts_dict.get("fitnessTrend"),
                "acwrPercent": (ts_dict.get("acuteTrainingLoadDTO") or {}).get("acwrPercent"),
                "dailyTrainingLoadAcute": (ts_dict.get("acuteTrainingLoadDTO") or {}).get("dailyTrainingLoadAcute"),
                "dailyTrainingLoadChronic": (ts_dict.get("acuteTrainingLoadDTO") or {}).get("dailyTrainingLoadChronic"),
                "maxTrainingLoadChronic": (ts_dict.get("acuteTrainingLoadDTO") or {}).get("maxTrainingLoadChronic"),
                "minTrainingLoadChronic": (ts_dict.get("acuteTrainingLoadDTO") or {}).get("minTrainingLoadChronic"),
                "dailyAcuteChronicWorkloadRatio": (ts_dict.get("acuteTrainingLoadDTO") or {}).get("dailyAcuteChronicWorkloadRatio"),
            }
            if ts_dict.get("timestamp") and any(value is not None for value in data_fields.values()):
                points_list.append({
                    "measurement": "TrainingStatus",
                    "time": datetime.fromtimestamp(ts_dict["timestamp"]/1000, tz=pytz.timezone("UTC")).isoformat(),
                    "tags": {
                        "Device": GARMIN_DEVICENAME,
                        "Database_Name": INFLUXDB_DATABASE
                    },
                    "fields": data_fields
                })
                logging.info(f"Success : Fetching Training Status for date {date_str}")
    return points_list

# Contribution from PR #17 by @arturgoms 
def get_training_readiness(date_str):
    points_list = []
    tr_list_all = garmin_obj.get_training_readiness(date_str)
    if tr_list_all:
        for tr_dict in tr_list_all:
            data_fields = {
                    "level": tr_dict.get("level"),
                    "score": tr_dict.get("score"),
                    "sleepScore": tr_dict.get("sleepScore"),
                    "sleepScoreFactorPercent": tr_dict.get("sleepScoreFactorPercent"),
                    "recoveryTime": tr_dict.get("recoveryTime"),
                    "recoveryTimeFactorPercent": tr_dict.get("recoveryTimeFactorPercent"),
                    "acwrFactorPercent": tr_dict.get("acwrFactorPercent"),
                    "acuteLoad": tr_dict.get("acuteLoad"),
                    "stressHistoryFactorPercent": tr_dict.get("stressHistoryFactorPercent"),
                    "hrvFactorPercent": tr_dict.get("hrvFactorPercent"),
                }
            if (not all(value is None for value in data_fields.values())) and tr_dict.get('timestamp'):
                points_list.append({
                    "measurement":  "TrainingReadiness",
                    "time": pytz.timezone("UTC").localize(datetime.strptime(tr_dict['timestamp'],"%Y-%m-%dT%H:%M:%S.%f")).isoformat(),
                    "tags": {
                        "Device": GARMIN_DEVICENAME,
                        "Database_Name": INFLUXDB_DATABASE
                    },
                    "fields": data_fields
                })
                logging.info(f"Success : Fetching Training Readiness for date {date_str}")
    return points_list

# Contribution from PR #17 by @arturgoms 
def get_hillscore(date_str):
    points_list = []
    hill = garmin_obj.get_hill_score(date_str)
    if hill:
        data_fields = {
            "strengthScore": hill.get("strengthScore"),
            "enduranceScore": hill.get("enduranceScore"),
            "hillScoreClassificationId": hill.get("hillScoreClassificationId"),
            "overallScore": hill.get("overallScore"),
            "hillScoreFeedbackPhraseId": hill.get("hillScoreFeedbackPhraseId"),
            "vo2MaxPreciseValue": hill.get("vo2MaxPreciseValue")
        }
        if not all(value is None for value in data_fields.values()):
            points_list.append({
                "measurement":  "HillScore",
                "time": datetime.strptime(date_str,"%Y-%m-%d").replace(hour=0, tzinfo=pytz.UTC).isoformat(), # Use GMT 00:00 for daily record
                "tags": {
                    "Device": GARMIN_DEVICENAME,
                    "Database_Name": INFLUXDB_DATABASE
                },
                "fields": data_fields
            })
            logging.info(f"Success : Fetching Hill Score for date {date_str}")
    return points_list

# Contribution from PR #17 by @arturgoms 
def get_race_predictions(date_str):
    points_list = []
    rp_all_list = garmin_obj.get_race_predictions(startdate=date_str, enddate=date_str, _type="daily")
    rp_all = rp_all_list[0] if len(rp_all_list) > 0 else {}
    if rp_all:
        data_fields = {
            "time5K": rp_all.get("time5K"),
            "time10K": rp_all.get("time10K"),
            "timeHalfMarathon": rp_all.get("timeHalfMarathon"),
            "timeMarathon": rp_all.get("timeMarathon"),
        }
        if not all(value is None for value in data_fields.values()):
            points_list.append({
                "measurement":  "RacePredictions",
                "time": datetime.strptime(date_str,"%Y-%m-%d").replace(hour=0, tzinfo=pytz.UTC).isoformat(), # Use GMT 00:00 for daily record
                "tags": {
                    "Device": GARMIN_DEVICENAME,
                    "Database_Name": INFLUXDB_DATABASE
                },
                "fields": data_fields
            })
            logging.info(f"Success : Fetching Race Predictions for date {date_str}")
    return points_list

def get_vo2_max(date_str):
    points_list = []
    max_metrics = garmin_obj.get_max_metrics(date_str)
    try:
        if max_metrics:
            vo2_max_value = (max_metrics[0].get("generic") or {}).get("vo2MaxPreciseValue", None)
            vo2_max_value_cycling = (max_metrics[0].get("cycling") or {}).get("vo2MaxPreciseValue", None)
            if vo2_max_value or vo2_max_value_cycling:
                points_list.append({
                    "measurement":  "VO2_Max",
                    "time": datetime.strptime(date_str,"%Y-%m-%d").replace(hour=0, tzinfo=pytz.UTC).isoformat(), # Use GMT 00:00 for daily record
                    "tags": {
                        "Device": GARMIN_DEVICENAME,
                        "Database_Name": INFLUXDB_DATABASE
                    },
                    "fields": {"VO2_max_value" : vo2_max_value, "VO2_max_value_cycling" : vo2_max_value_cycling}
                })
                logging.info(f"Success : Fetching VO2-max for date {date_str}")
        return points_list
    except AttributeError as err:
        return []

def get_endurance_score(date_str):
    points_list = []
    endurance_dict = garmin_obj.get_endurance_score(date_str)
    if endurance_dict:
        if endurance_dict.get("overallScore"):
            points_list.append({
                "measurement":  "EnduranceScore",
                "time": pytz.timezone("UTC").localize(datetime.strptime(date_str,"%Y-%m-%d")).isoformat(), # Use GMT 00:00 is timestamp is not available
                "tags": {
                    "Device": GARMIN_DEVICENAME,
                    "Database_Name": INFLUXDB_DATABASE
                },
                "fields": {
                    "EnduranceScore": endurance_dict.get("overallScore")
                    }
            })
            logging.info(f"Success : Fetching Endurance Score for date {date_str}")
    return points_list

def get_blood_pressure(date_str):
    points_list = []
    bp_all = garmin_obj.get_blood_pressure(date_str, date_str).get('measurementSummaries',[])
    if len(bp_all) > 0:
        bp_list = bp_all[0].get('measurements',[])
        for bp_measurement in bp_list:
            data_fields = {
                'Systolic': bp_measurement.get('systolic', None),
                "Diastolic": bp_measurement.get('diastolic', None),
                "Pulse": bp_measurement.get('pulse', None)
            }
            if not all(value is None for value in data_fields.values()) and 'measurementTimestampGMT' in bp_measurement:
                points_list.append({
                    "measurement":  "BloodPressure",
                    "time": pytz.UTC.localize(datetime.strptime(bp_measurement['measurementTimestampGMT'], '%Y-%m-%dT%H:%M:%S.%f')),
                    "tags": {
                        "Device": GARMIN_DEVICENAME,
                        "Database_Name": INFLUXDB_DATABASE,
                        "Source": bp_measurement.get('sourceType', None)
                    },
                    "fields": data_fields
                })
        logging.info(f"Success : Fetching Blood Pressure for date {date_str}")
    return points_list

def get_hydration(date_str):
    points_list = []
    hydration_dict = garmin_obj.get_hydration_data(date_str)
    data_fields = {
        'ValueInML': hydration_dict.get('valueInML', None),
        "SweatLossInML": hydration_dict.get('sweatLossInML', None),
        "GoalInML": hydration_dict.get('goalInML', None),
        "ActivityIntakeInML": hydration_dict.get('activityIntakeInML', None)
    }
    if not all(value is None for value in data_fields.values()):
        points_list.append({
            "measurement":  "Hydration",
            "time": datetime.strptime(date_str,"%Y-%m-%d").replace(hour=0, tzinfo=pytz.UTC).isoformat(), # Use GMT 00:00 for daily record
            "tags": {
                "Device": GARMIN_DEVICENAME,
                "Database_Name": INFLUXDB_DATABASE
            },
            "fields": data_fields
        })
        logging.info(f"Success : Fetching Hydration data for date {date_str}")
    return points_list

# %%
def daily_fetch_write(date_str):
    if REQUEST_INTRADAY_DATA_REFRESH and (datetime.strptime(date_str, "%Y-%m-%d") <= (datetime.today() - timedelta(days=IGNORE_INTRADAY_DATA_REFRESH_DAYS))):
        data_refresh_response = garmin_obj.connectapi(f"wellness-service/wellness/epoch/request/{date_str}", method="POST").get("status", "Unknown")
        logging.info(f"Intraday data refresh request status: {data_refresh_response}")
        if data_refresh_response == "SUBMITTED":
            logging.info(f"Waiting 10 seconds for refresh request to process...")
            time.sleep(10)
        elif data_refresh_response == "COMPLETE":
            logging.info(f"Data for date {date_str} is already available")
        elif data_refresh_response == "NO_FILES_FOUND":
            logging.info(f"No Data is available for date {date_str} to refresh")
            return None
        elif data_refresh_response == "DENIED":
            logging.info(f"Daily refresh limit reached. Pausing script for 24 hours to ensure Intraday data fetching. Disable REQUEST_INTRADAY_DATA_REFRESH to avoid this!")
            time.sleep(86500)
            data_refresh_response = garmin_obj.connectapi(f"wellness-service/wellness/epoch/request/{date_str}", method="POST").get("status", "Unknown")
            logging.info(f"Intraday data refresh request status: {data_refresh_response}")
            logging.info(f"Waiting 10 seconds...")
            time.sleep(10)
        else:
            logging.info(f"Refresh response is unknown!")
            time.sleep(5)
    if 'daily_avg' in FETCH_SELECTION:
        write_points_to_influxdb(get_daily_stats(date_str))
    if 'sleep' in FETCH_SELECTION:
        write_points_to_influxdb(get_sleep_data(date_str))
    if 'steps' in FETCH_SELECTION:
        write_points_to_influxdb(get_intraday_steps(date_str))
    if 'heartrate' in FETCH_SELECTION:
        write_points_to_influxdb(get_intraday_hr(date_str))
    if 'stress' in FETCH_SELECTION:
        write_points_to_influxdb(get_intraday_stress(date_str))
    if 'breathing' in FETCH_SELECTION:
        write_points_to_influxdb(get_intraday_br(date_str))
    if 'hrv' in FETCH_SELECTION:
        write_points_to_influxdb(get_intraday_hrv(date_str))
    if 'vo2' in FETCH_SELECTION:
        write_points_to_influxdb(get_vo2_max(date_str))
    if 'race_prediction' in FETCH_SELECTION:
        write_points_to_influxdb(get_race_predictions(date_str))
    if 'body_composition' in FETCH_SELECTION:
        write_points_to_influxdb(get_body_composition(date_str))
    if 'lactate_threshold' in FETCH_SELECTION:
        write_points_to_influxdb(get_lactate_threshold(date_str))
    if 'training_status' in FETCH_SELECTION:
        write_points_to_influxdb(get_training_status(date_str))
    if 'training_readiness' in FETCH_SELECTION:
        write_points_to_influxdb(get_training_readiness(date_str))
    if 'hill_score' in FETCH_SELECTION:
        write_points_to_influxdb(get_hillscore(date_str))
    if 'endurance_score' in FETCH_SELECTION:
        write_points_to_influxdb(get_endurance_score(date_str))
    if 'blood_pressure' in FETCH_SELECTION:
        write_points_to_influxdb(get_blood_pressure(date_str))
    if 'hydration' in FETCH_SELECTION:
        write_points_to_influxdb(get_hydration(date_str))
    if 'activity' in FETCH_SELECTION:
        activity_summary_points_list, activity_with_gps_id_dict = get_activity_summary(date_str)
        write_points_to_influxdb(activity_summary_points_list)
        write_points_to_influxdb(fetch_activity_GPS(activity_with_gps_id_dict))
            

# %%
def fetch_write_bulk(start_date_str, end_date_str):
    global garmin_obj
    logging.info("Fetching data for the given period in reverse chronological order")
    time.sleep(3)
    write_points_to_influxdb(get_last_sync())
    for current_date in iter_days(start_date_str, end_date_str):
        repeat_loop = True
        while repeat_loop:
            try:
                daily_fetch_write(current_date)
                logging.info(f"Success : Fetched all available health metrics for date {current_date} (skipped any if unavailable)")
                logging.info(f"Waiting : for {RATE_LIMIT_CALLS_SECONDS} seconds")
                time.sleep(RATE_LIMIT_CALLS_SECONDS)
                repeat_loop = False
            except GarminConnectTooManyRequestsError as err:
                logging.error(err)
                logging.info(f"Too many requests (429) : Failed to fetch one or more metrics - will retry for date {current_date}")
                logging.info(f"Waiting : for {FETCH_FAILED_WAIT_SECONDS} seconds")
                time.sleep(FETCH_FAILED_WAIT_SECONDS)
                repeat_loop = True
            except (
                    GarminConnectConnectionError,
                    requests.exceptions.HTTPError,
                    requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout,
                    GarthHTTPError
                    ) as err:
                logging.error(err)
                logging.info(f"Connection Error : Failed to fetch one or more metrics - skipping date {current_date}")
                logging.info(f"Waiting : for {RATE_LIMIT_CALLS_SECONDS} seconds")
                time.sleep(RATE_LIMIT_CALLS_SECONDS)
                repeat_loop = False
            except GarminConnectAuthenticationError as err:
                logging.error(err)
                logging.info(f"Authentication Failed : Retrying login with given credentials (won't work automatically for MFA/2FA enabled accounts)")
                garmin_obj = garmin_login()
                time.sleep(5)
                repeat_loop = True


# %%
garmin_obj = garmin_login()

# %%
if MANUAL_START_DATE:
    fetch_write_bulk(MANUAL_START_DATE, MANUAL_END_DATE)
    logging.info(f"Bulk update success : Fetched all available health metrics for date range {MANUAL_START_DATE} to {MANUAL_END_DATE}")
    exit(0)
else:
    try:
        if INFLUXDB_VERSION == "1":
            last_influxdb_sync_time_UTC = pytz.utc.localize(datetime.strptime(list(influxdbclient.query(f"SELECT * FROM HeartRateIntraday ORDER BY time DESC LIMIT 1").get_points())[0]['time'],"%Y-%m-%dT%H:%M:%SZ"))
        else:
            last_influxdb_sync_time_UTC = pytz.utc.localize(influxdbclient.query(query="SELECT * FROM HeartRateIntraday ORDER BY time DESC LIMIT 1", language="influxql").to_pylist()[0]['time'])
    except Exception as err:
        logging.error(err)
        logging.warning("No previously synced data found in local InfluxDB database, defaulting to 7 day initial fetching. Use specific start date ENV variable to bulk update past data")
        last_influxdb_sync_time_UTC = (datetime.today() - timedelta(days=7)).astimezone(pytz.timezone("UTC"))
    try:
        if USER_TIMEZONE: # If provided by user, using that. 
            local_timediff = datetime.now(tz=pytz.timezone(USER_TIMEZONE)).utcoffset()
        else: # otherwise try to set automatically
            last_activity_dict = garmin_obj.get_last_activity() # (very unlineky event that this will be empty given Garmin's userbase, everyone should have at least one activity)
            local_timediff = datetime.strptime(last_activity_dict['startTimeLocal'], '%Y-%m-%d %H:%M:%S') - datetime.strptime(last_activity_dict['startTimeGMT'], '%Y-%m-%d %H:%M:%S')
        if local_timediff >= timedelta(0):
            logging.info("Using user's local timezone as UTC+" + str(local_timediff))
        else:
            logging.info("Using user's local timezone as UTC-" + str(-local_timediff))
    except (KeyError, TypeError) as err:
        logging.warning(f"Unable to determine user's timezone - Defaulting to UTC. Consider providing TZ identifier with USER_TIMEZONE environment variable")
        local_timediff = timedelta(hours=0)
    
    while True:
        last_watch_sync_time_UTC = datetime.fromtimestamp(int(garmin_obj.get_device_last_used().get('lastUsedDeviceUploadTime')/1000)).astimezone(pytz.timezone("UTC"))
        if last_influxdb_sync_time_UTC < last_watch_sync_time_UTC:
            logging.info(f"Update found : Current watch sync time is {last_watch_sync_time_UTC} UTC")
            fetch_write_bulk((last_influxdb_sync_time_UTC + local_timediff).strftime('%Y-%m-%d'), (last_watch_sync_time_UTC + local_timediff).strftime('%Y-%m-%d')) # Using local dates for deciding which dates to fetch in current iteration (see issue #25)
            last_influxdb_sync_time_UTC = last_watch_sync_time_UTC
        else:
            logging.info(f"No new data found : Current watch and influxdb sync time is {last_watch_sync_time_UTC} UTC")
        logging.info(f"waiting for {UPDATE_INTERVAL_SECONDS} seconds before next automatic update calls")
        time.sleep(UPDATE_INTERVAL_SECONDS)

