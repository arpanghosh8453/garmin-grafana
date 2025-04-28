#!/bin/bash

echo "Starting Garmin Grafana (an open-source project by Arpan Ghosh) setup..."
echo "Please consider supporting this project and developer(s) if you enjoy it after installing"

sleep 5;

echo "Checking if Docker is installed..."
if ! command -v docker &> /dev/null
then
    echo "Docker is not installed. Attempting to install docker... If this seep fails, you can re-try this script after installing docker manually"
    curl -fsSL https://get.docker.com -o get-docker.sh && sh get-docker.sh
    echo "Docker installed, adding current user to docker group (requires superuser access)"
    sudo groupadd docker; sudo usermod -aG docker $USER; newgrp docker
fi

echo "Checking if Docker daemon is running..."
if ! docker info &> /dev/null
then
    echo "Docker daemon is not running. Please start Docker and try again."
    exit 1
fi

echo "Creating garminconnect-tokens directory..."
mkdir -p garminconnect-tokens

# echo "Setting ownership of garminconnect-tokens to UID 1000...(matching grafana-data-fetch container's internal user)"
chown -R 1000:1000 garminconnect-tokens || { echo "Permission change failed - you may need to run this as sudo?. Exiting."; exit 1; }

echo "Renaming compose-example.yml to compose.yml..."
mv compose-example.yml compose.yml

echo "Replacing {DS_GARMIN_STATS} variable with garmin_influxdb in the dashboard JSON..."
# Check if the OS is macOS (Darwin)
if [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS sed requires an extension for -i, use '' for no backup
    sed -i '' 's/\${DS_GARMIN_STATS}/garmin_influxdb/g' ./Grafana_Dashboard/Garmin-Grafana-Dashboard.json
else
    # Linux sed works without an extension for -i
    sed -i 's/\${DS_GARMIN_STATS}/garmin_influxdb/g' ./Grafana_Dashboard/Garmin-Grafana-Dashboard.json
fi

echo "🐳 Pulling the latest thisisarpanghosh/garmin-fetch-data Docker image..."
docker pull thisisarpanghosh/garmin-fetch-data:latest || { echo "Docker pull failed. Do you have docker installed and can run docker commands?"; exit 1; }

echo "🐳 Running garmin-fetch-data in initialization mode...setting up authentication"
docker compose run --rm garmin-fetch-data || { echo "Unable to run garmin-fetch-data container. Exiting."; exit 1; }

echo "Starting all services using Docker Compose..."
docker compose up -d || { echo "Docker Compose failed. Do you have docker compose installed? Exiting."; exit 1; }

echo "Following logs. Press Ctrl+C to exit."
docker compose logs --follow
