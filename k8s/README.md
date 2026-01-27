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


