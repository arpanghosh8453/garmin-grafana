# Kubernetes Deployment

Helm chart for deploying garmin-grafana.

## Install using released charts

Use the default `values.yaml` as guide. Sample *values.yaml* configuration file could be:

```yaml
grafana:
  enabled: false

influxdb:
  image:
    repository: influxdb
    tag: "1.11"
  persistence:
    enabled: true
    size: 5Gi
  auth:
    database: myGarminStats
    username: admin
    password: password
    adminUser: admin
    adminPassword: password

garmin:
  image:
    repository: ghcr.io/arpanghosh8453/garmin-fetch-data
    tag: v0.3.0
  port: 8000
  tokens:
    persistence:
      enabled: true
      size: 100Mi
  credentials:
    email: user@gmail.com
    base64Password: cGFzc3dvcmQK # Password, in base64
```

the file disables the installation of Grafana stacks, installs Influxdb with custom user and passwords.


Now you can install the application using Helm:

```bash
helm upgrade --install garmin-grafana oci://ghcr.io/arpanghosh8453/garmin-grafana \
     --version v0.3.1-helm --namespace garmin-grafana --create-namespace -f values.yaml --wait
```

## MFA on a K8s Cluster

To run this on a k8s cluster when you have MFA enabled on your account please follow the following steps.


### 1. Scale down the deployment

```bash
kubectl scale deployment garmin-grafana-garmin -n garmin-grafana --replicas=0
```

### 2. Run interactive pod with PVC mounted for token persistence

```bash
kubectl run -it garmin-auth -n garmin-grafana --rm \
  --image=ghcr.io/arpanghosh8453/garmin-fetch-data:v0.3.0 \
  --overrides='{"spec":{"volumes":[{"name":"tokens","persistentVolumeClaim":{"claimName":"garmin-grafana-tokens"}}],"containers":[{"name":"garmin-auth","image":"ghcr.io/arpanghosh8453/garmin-fetch-data:v0.3.0","command":["/bin/bash"],"stdin":true,"tty":true,"env":[{"name":"GARMINCONNECT_EMAIL","value":"address@xyz.com"},{"name":"GARMINCONNECT_BASE64_PASSWORD","value":"12345678ABC"},{"name":"INFLUXDB_HOST","value":"garmin-grafana-influxdb"},{"name":"INFLUXDB_PORT","value":"8086"},{"name":"INFLUXDB_DATABASE","value":"GarminStats"},{"name":"INFLUXDB_USERNAME","value":"admin"},{"name":"INFLUXDB_PASSWORD","value":"yourPassword"}],"volumeMounts":[{"name":"tokens","mountPath":"/home/appuser/.garminconnect"}]}]}}'
```

### 3. Inside the pod, run the script

```bash
export INFLUXDB_USERNAME=admin
export INFLUXDB_PASSWORD="yourPassword"
source /app/.venv/bin/activate
python garmin_grafana/garmin_fetch.py
```

Enter the MFA code when prompted, then type `exit` to leave the pod.

### 4. Scale back up

```bash
kubectl scale deployment garmin-grafana-garmin -n garmin-grafana --replicas=1
```


## Local Development

### Prerequisites

Use `./templates/example-secret.yaml` to provide secrets (apply your credentials directly or use any secret operator separately).
Default setup uses emptyDir volumes for easy testing. Enable persistence for production use.

### Quick Start

#### Local Testing (minikube)

If missing tools, install them:

* [minikube](https://minikube.sigs.k8s.io/docs/start/)
* [helm](https://helm.sh/docs/intro/install/)

```bash
# One command setup - will open Grafana in browser in ~2 minutes and show password in terminal
make test-minikube
# Cleanup when done
make clean-minikube
# Get Grafana password
make get-grafana-password
```

#### Install to any K8s cluster (from local chart)

```bash
# From the k8s directory
helm dependency build
helm install garmin-grafana . -n garmin-grafana --create-namespace

# With custom values
helm install garmin-grafana . -f your-values.yaml -n garmin-grafana --create-namespace
```

#### Fetcher-only deployment (no dashboard)

```bash
# Deploy data fetcher + influx without Grafana dashboard
helm install garmin-grafana . --set grafana.enabled=false -n garmin-grafana --create-namespace
```

#### Get raw manifests

```bash
helm template garmin-grafana . -n garmin-grafana > garmin-grafana.yaml
```


