#!/bin/bash

echo "Starting Garmin Grafana (an open-source project by Arpan Ghosh) setup..."
echo "Please consider supporting this project and developer(s) if you enjoy it after installing"

sleep 5;

echo "Checking if Docker is installed..."
if ! command -v docker &> /dev/null
then
    echo "Docker is not installed. Attempting to install docker... If this step fails, you can re-try this script after installing docker manually"
    curl -fsSL https://get.docker.com -o get-docker.sh && sh get-docker.sh || { echo "Automatic Docker installation failed - Please install docker manually. Exiting."; exit 1; }
    echo "Docker installed, adding current user to docker group (requires superuser access)"
    sudo groupadd docker; sudo usermod -aG docker $USER; newgrp docker
fi

echo "Checking if Docker daemon is running..."
if ! docker info &> /dev/null
then
    echo "Docker daemon is not running. Trying to start it automatically...."
    sudo systemctl start docker || { echo "Automatic Docker restart failed (only works on debian/ubuntu based systems) - Please restart docker manually."; }
    sleep 3;
    if ! docker info &> /dev/null
    then
        echo "Docker daemon is not running. Please start/re-start Docker and try again."
        exit 1
    fi
fi

echo "Creating garminconnect-tokens directory..."
mkdir -p garminconnect-tokens

# Garmin session tokens are sensitive credentials. We make the directory
# owned by the container's appuser (uid/gid 1000) instead of the old
# ``chmod -R 777`` approach which made the tokens world-readable/writable.
echo "Setting garminconnect-tokens ownership to uid/gid 1000 (container appuser)..."
if ! sudo chown -R 1000:1000 garminconnect-tokens; then
    echo "chown failed - falling back to chmod 700 for the current user. If the"
    echo "container reports permission errors, re-run with sudo or uncomment the"
    echo "'user: root' line in compose.yml."
    chmod -R 700 garminconnect-tokens || true
fi

if [ -f compose.yml ]; then
    echo "compose.yml already exists - leaving it untouched."
else
    echo "Creating compose.yml from compose-example.yml..."
    cp compose-example.yml compose.yml
fi

if [ ! -f .env ]; then
    echo "Creating .env from .env.example - EDIT IT AND CHANGE THE PASSWORDS before going to production!"
    cp .env.example .env
fi

echo "Replacing {DS_GARMIN_STATS} variable with garmin_influxdb in the dashboard JSON..."
if [[ "$OSTYPE" == "darwin"* ]]; then
    sed -i '' 's/\${DS_GARMIN_STATS}/garmin_influxdb/g' ./Grafana_Dashboard/Garmin-Grafana-Dashboard.json
else
    sed -i 's/\${DS_GARMIN_STATS}/garmin_influxdb/g' ./Grafana_Dashboard/Garmin-Grafana-Dashboard.json
fi

# echo "Setting garmin-fetch-data Docker container user as root..." # This replacement runs the container as root and requires the bind volume mount for the token storage updated accordingly as well. 
# if [[ "$OSTYPE" == "darwin"* ]]; then
#     sed -i '' 's/# user: root/user: root/g' ./compose.yml
#     sed -i '' 's|/home/appuser/.garminconnect|/root/.garminconnect|g' ./compose.yml
# else
#     sed -i 's/# user: root/user: root/g' ./compose.yml
#     sed -i 's|/home/appuser/.garminconnect|/root/.garminconnect|g' ./compose.yml
# fi

echo "🐳 Pulling the latest thisisarpanghosh/garmin-fetch-data Docker image..."
docker pull thisisarpanghosh/garmin-fetch-data:latest || { echo "Docker pull failed. Do you have docker installed and can run docker commands?"; exit 1; }

echo "🐳Terminating any previous running containers from this stack"
docker compose down

echo "🐳 Running garmin-fetch-data in initialization mode...setting up authentication"
docker compose run --rm garmin-fetch-data || { echo "Unable to run garmin-fetch-data container. Exiting."; exit 1; }

echo "Starting all services using Docker Compose..."
docker compose up -d || { echo "Docker Compose failed. Do you have docker compose installed? Exiting."; exit 1; }

echo "Following logs. Press Ctrl+C to exit."
docker compose logs --follow
