# Garmin → Grafana — Guide d'installation personnel

> Tableau de bord Grafana alimenté automatiquement par les données de ta montre Garmin.

## Architecture

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  Garmin      │────▶│  garmin-     │────▶│  InfluxDB    │
│  Connect API │     │  fetch-data  │     │  (v1.11)     │
└──────────────┘     └──────────────┘     └──────┬───────┘
                                                 │
                                          ┌──────▼───────┐
                                          │   Grafana     │
                                          │ localhost:3000│
                                          └──────────────┘
```

## Prérequis

- **Docker Desktop** (Windows / Mac / Linux)
- Un **compte Garmin Connect** avec une montre Garmin synchronisée

## Installation rapide

### 1. Cloner le dépôt

```bash
git clone https://github.com/arpanghosh8453/garmin-grafana.git
cd garmin-grafana
```

### 2. Créer le fichier `.env`

```bash
cp .env.example .env
```

Édite `.env` et change les mots de passe :

```env
INFLUXDB_USER=influxdb_user
INFLUXDB_PASSWORD=ton_mot_de_passe_influxdb
INFLUXDB_DATABASE=GarminStats
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=ton_mot_de_passe_grafana
```

### 3. Créer `compose.yml`

```bash
cp compose-example.yml compose.yml
```

### 4. Remplacer la variable datasource dans le dashboard

```bash
python -c "
import pathlib
p = pathlib.Path('Grafana_Dashboard/Garmin-Grafana-Dashboard.json')
c = p.read_text(encoding='utf-8').replace('\${DS_GARMIN_STATS}', 'garmin_influxdb')
p.write_text(c, encoding='utf-8')
print('OK:', c.count('garmin_influxdb'), 'remplacements')
"
```

### 5. Builder l'image et démarrer InfluxDB

```bash
docker compose build garmin-fetch-data
docker compose up -d influxdb
```

Attendre qu'InfluxDB soit healthy :

```bash
docker inspect --format '{{.State.Health.Status}}' influxdb
# → "healthy"
```

### 6. Authentification Garmin (première fois uniquement)

```bash
docker compose run --rm garmin-fetch-data
```

Saisis ton email et mot de passe Garmin Connect quand demandé.
Les tokens OAuth sont sauvegardés dans `./garminconnect-tokens/` (~1 an de validité).

> **⚠️ En cas d'erreur 429 (Too Many Requests)** : voir la section
> [Contournement du 429](#contournement-du-429-garmin-sso) ci-dessous.

### 7. Lancer toute la stack

```bash
docker compose up -d
```

### 8. Accéder à Grafana

- **URL** : http://localhost:3000
- **Login** : les valeurs de `GRAFANA_ADMIN_USER` / `GRAFANA_ADMIN_PASSWORD` dans `.env`
- Le dashboard **Garmin Stats** est automatiquement provisionné

## Commandes utiles

| Commande | Description |
|---|---|
| `docker compose up -d` | Démarrer tous les services |
| `docker compose down` | Arrêter tous les services |
| `docker compose logs -f garmin-fetch-data` | Suivre les logs du fetcher |
| `docker compose restart garmin-fetch-data` | Redémarrer le fetcher |
| `docker ps` | Voir les containers actifs |

## Contournement du 429 Garmin SSO

Si `garmin-fetch-data` retourne une erreur **429 Too Many Requests** lors de
l'authentification, c'est que Garmin rate-limite les appels scriptés à son SSO.

### Méthode du ticket navigateur (recommandée)

1. **Connecte-toi à https://connect.garmin.com** dans ton navigateur (Chrome/Firefox).

2. **Ouvre cette URL** dans un nouvel onglet :
   ```
   https://sso.garmin.com/sso/signin?id=gauth-widget&embedWidget=true&gauthHost=https%3A%2F%2Fsso.garmin.com%2Fsso%2Fembed&service=https%3A%2F%2Fsso.garmin.com%2Fsso%2Fembed&source=https%3A%2F%2Fsso.garmin.com%2Fsso%2Fembed&redirectAfterAccountLoginUrl=https%3A%2F%2Fsso.garmin.com%2Fsso%2Fembed&redirectAfterAccountCreationUrl=https%3A%2F%2Fsso.garmin.com%2Fsso%2Fembed
   ```

3. **Affiche le code source** (Ctrl+U) et cherche `ticket=` (Ctrl+F).
   Tu trouves un ticket de la forme `ST-xxxxxx-xxxxxxxxxxxx-cas`.

4. **Dans un terminal**, lance :
   ```bash
   docker run --rm -it \
     -v ./garminconnect-tokens:/tokens \
     -v ./Extra:/scripts \
     garmin-grafana:local python /scripts/exchange_ticket.py
   ```

5. **Colle le ticket** quand demandé (< 10 secondes après le refresh de la page SSO).

6. Les tokens sont écrits dans `./garminconnect-tokens/`. Relance :
   ```bash
   docker compose up -d
   ```

## Données collectées

Le fetcher récupère automatiquement (toutes les 5 minutes) :

- 💓 Fréquence cardiaque (intraday)
- 😴 Sommeil (durée, phases, score)
- 👟 Pas (intraday + cumul)
- 😰 Stress & Body Battery
- 🫁 Respiration
- 📈 HRV (variabilité cardiaque)
- 🏃 Activités sportives (GPS, laps, HR zones)
- ⚖️ Composition corporelle (poids, IMC, masse grasse)
- 🏋️ Entraînement force (séries, répétitions, poids)
- 🎯 Prédictions de course (5K, 10K, semi, marathon)
- 🏔️ VO2 Max, Fitness Age, Endurance Score, Hill Score

## Structure des fichiers

```
garmin-grafana/
├── .env                          ← Tes secrets (ignoré par Git)
├── compose.yml                   ← Ta config Docker (ignoré par Git)
├── garminconnect-tokens/         ← Tokens OAuth Garmin (ignoré par Git)
├── compose-example.yml           ← Template Compose
├── .env.example                  ← Template des variables
├── Dockerfile                    ← Image du fetcher
├── src/garmin_grafana/           ← Code Python du fetcher
├── Grafana_Dashboard/            ← Dashboard JSON provisionné
├── Grafana_Datasource/           ← Datasource YAML provisionnée
├── Extra/
│   ├── exchange_ticket.py        ← Script contournement 429
│   └── preauth-garmin.py         ← Script pré-auth alternatif
└── k8s/                          ← Helm chart (Kubernetes)
```

## Dépannage

| Problème | Solution |
|---|---|
| `PermissionError` sur les tokens | Décommenter `user: root` dans `compose.yml` et changer le volume en `/root/.garminconnect` |
| Dashboard vide ("No data") | Vérifier que `${DS_GARMIN_STATS}` est remplacé par `garmin_influxdb` dans le JSON (étape 4) |
| 429 Too Many Requests | Ne PAS retenter pendant 12h, ou utiliser la méthode du ticket navigateur |
| Grafana "Login failed" | `docker exec grafana grafana cli admin reset-admin-password NouveauMotDePasse` |
| Fetcher crash-loop | `docker compose logs garmin-fetch-data` pour voir l'erreur |
