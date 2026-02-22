### Garmin Bulk Importer (From Garmin Connect Export)

If you downloaded a bulk export .zip from the Garmin Connect website. You can import that data as well without having to be rate limited by API calls.

##### Using Docker

Use this method if your Garmin Grafana stack is running locally on the same machine.

> [!NOTE]
> The runtime image does not include `uv`, so Docker examples use `python` directly.

1. Download your Garmin data (See [Export All Garmin Data Using Account Management Center](https://support.garmin.com/en-US/?faq=W1TvTPW8JZ6LfJSfK512Q8), this process can take several weeks)
2. Stop the currently running garmin-fetch container.
3. Run the `garmin_bulk_importer.py` script using the docker container and specify the path to the unzipped Garmin data and a start and end time.

```
# In ~/garmin-grafana
docker compose run --rm -v <path_to_export>:/bulk_export -e MANUAL_START_DATE=YYYY-MM-DD -e MANUAL_END_DATE=YYYY-MM-DD garmin-fetch-data python /app/garmin_grafana/garmin_bulk_importer.py
```

Example:

```
docker compose run --rm -v "~/Downloads/Garmin Export 2025-11-27":/bulk_export -e MANUAL_START_DATE=2018-01-01 -e MANUAL_END_DATE=2025-01-03 garmin-fetch-data python /app/garmin_grafana/garmin_bulk_importer.py
```

##### Using Python

This method is useful if your Garmin Grafana stack is running on a remote machine.

1. Download your Garmin data (See [Export All Garmin Data Using Account Management Center](https://support.garmin.com/en-US/?faq=W1TvTPW8JZ6LfJSfK512Q8), this process can take several weeks)
2. Update the influxdb docker container to map port 8086 externally

```
  influxdb:
    ports:
      - '<external_port>:8086'  # This can be any unused port
```

3. Checkout this repo locally on any machine
4. cd into the repo and install the Python dependences

```
uv sync --locked
```

5. cd into `src/garmin_grafana` and create a `override-default-vars.env` file

```
INFLUXDB_HOST = "<influxdb_host_machine_ip_address>"
INFLUXDB_PORT = "<influxdb_external_port>" # This should be the port you mapped to above
```

6. Run the `garmin_bulk_importer.py` script and specify the path to the unzipped Garmin data and a start and end time

```
# In ~/garmin-grafana/src/garmin_grafana
uv run garmin_bulk_importer.py --bulk_data_path="~/Downloads/Garmin Export 2025-11-27" --start_date=2018-01-01 --end_date=2025-01-03
```

> [!TIP]
> If you would like to skip any missing data or formatting error and continue the import process, you can use the `--ignore_errors` flag with the garmin_bulk_importer.py as a command line argument

## Manually Import Activity .FIT files

If you want to manually import .FIT files saved locally on your machine you can run the `fit_activity_importer.py` script. Follow the same instructions in the section above to setup your environment to run the script using either Docker or Python script directly. Replace the last step with either of the following:

Docker:

```
# In ~/garmin-grafana
docker compose run --rm -v <path_to_fit_file>:/fit_file.fit garmin-fetch-data python /app/garmin_grafana/fit_activity_importer.py
```

Example:

```
docker compose run --rm -v "~/Downloads/F129000.FIT":/fit_file.fit garmin-fetch-data python /app/garmin_grafana/fit_activity_importer.py
```

Python:

```
# In ~/garmin-grafana/src/garmin_grafana
uv run fit_activity_importer.py --fit_file=<path_to_fit_file>
```
