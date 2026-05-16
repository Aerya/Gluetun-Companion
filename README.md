# Gluetun Companion

> 🇬🇧 [English version](README.en.md)

Benchmark automatique des serveurs VPN via [Gluetun](https://github.com/qdm12/gluetun),
bascule automatique vers le meilleur serveur, et Web UI complète.

> **Merci à [qdm12](https://github.com/qdm12/gluetun)** pour Gluetun, sans lequel ce projet n'existerait pas.

---

## Compatibilité

Gluetun Companion fonctionne en théorie avec **tous les fournisseurs VPN compatibles Gluetun**
dès lors qu'au moins une de ces variables de filtre est utilisée dans votre configuration :

| Variable Gluetun | Description |
|---|---|
| `SERVER_NAMES` | Nom du serveur |
| `SERVER_COUNTRIES` | Pays |
| `SERVER_REGIONS` | Région |
| `SERVER_CITIES` | Ville |
| `SERVER_HOSTNAMES` | Hostname du serveur |

Le companion est **indépendant de la technologie de tunnel** utilisée : il fonctionne
identiquement avec OpenVPN, WireGuard ou toute autre tech supportée par votre fournisseur.

Il est conçu et testé en priorité pour **[AirVPN](https://airvpn.org/?referred_by=483746)**
*(lien affilié — merci si vous passez par là !)*, dont la liste des variables de filtre est
documentée ici :
[gluetun-wiki — AirVPN optional environment variables](https://github.com/qdm12/gluetun-wiki/blob/main/setup/providers/airvpn.md#optional-environment-variables)

---

## Fonctionnalités

- **Benchmark automatique** toutes les X heures — download, upload et latence par serveur,
  via le proxy HTTP Gluetun (port 8887), sans réseau Docker partagé
- **Téléchargement multi-flux** — N connexions TCP simultanées par endpoint (configurable,
  défaut : 4) pour saturer le tunnel VPN comme un gestionnaire de téléchargement
- **Bascule automatique** vers le meilleur serveur (`docker compose up -d`),
  basée sur un score pondéré (65 % mesure actuelle + 35 % historique) ;
  les services dépendants (`network_mode: service:gluetun`) sont relancés automatiquement
- **5 types de filtre** : SERVER\_NAMES, SERVER\_COUNTRIES, SERVER\_REGIONS,
  SERVER\_CITIES, SERVER\_HOSTNAMES
- **Warm-up TCP** configurable pour éviter le biais slow-start
- **Retry** configurable par serveur + timeout global par serveur
- **Auto-désactivation** d'un serveur après N échecs consécutifs
- **Web UI** dark/light — auth, dashboard avec sparkline, historique paginé, graphiques,
  page bascules avec gain Mbps et temps de connexion
- **Export CSV** de l'historique complet
- **Test unitaire** d'un serveur depuis l'UI sans attendre le prochain cycle
- **Purge automatique** de l'historique SQLite configurable (rétention en jours)
- **Endpoint `/healthz`** non authentifié pour les healthchecks Docker
- **Logs JSON structurés** optionnels via `LOG_JSON=1` (compatibles Loki/Grafana)
- **Base de données SQLite** (WAL) — aucune dépendance externe

---

## Mise en route

### 1. Exposer le proxy HTTP Gluetun sur l'hôte

Le companion n'utilise **pas** l'API Gluetun (port 8000) ni un réseau Docker partagé.
Il passe exclusivement par le **proxy HTTP** Gluetun, accessible via `host.docker.internal`.

Dans votre compose Gluetun, exposez le proxy HTTP sur l'hôte :

```yaml
# dans votre docker-compose.yml Gluetun existant
ports:
  - 8887:8888   # ou le port que vous avez configuré

environment:
  HTTPPROXY: "on"
  HTTPPROXY_LOG: "off"
  # HTTPPROXY_USER: ""       # optionnel — à reporter dans les paramètres de l'UI
  # HTTPPROXY_PASSWORD: ""
```

### 2. Monter le dossier compose de Gluetun

Le companion doit pouvoir écrire un `docker-compose.override.yml` dans le dossier
qui contient votre `docker-compose.yml` Gluetun, puis relancer le service.

### 3. Configurer le companion

```yaml
services:
  gluetun-companion:
    image: ghcr.io/aerya/gluetun-companion:latest
    container_name: gluetun-companion
    restart: always
    ports:
      - 8765:8765
    volumes:
      - /home/aerya/docker/gluetun-companion:/data
      - /var/run/docker.sock:/var/run/docker.sock
      - /home/aerya/docker/dockge-enhanced/stacks/airvpn:/compose  # <-- adapter
      # Dans cet exemple j'utilise Dockge ([-Enhanced](https://github.com/Aerya/Dockge-Enhanced))
    extra_hosts:
      - "host.docker.internal:host-gateway"
    environment:
      SECRET_KEY: remplacer-par-une-chaine-aleatoire-longue   # openssl rand -hex 32
      DATA_DIR: /data
      GLUETUN_HOST: host.docker.internal
      GLUETUN_PROXY_PORT: "8887"          # port du proxy HTTP Gluetun exposé sur l'hôte
      GLUETUN_CONTAINER: gluetun-airvpn   # nom exact du service dans le compose Gluetun
      COMPOSE_DIR: /compose

networks: {}
```

> **Note :** `COMPOSE_PROJECT` est optionnel. S'il est absent, le companion le détecte
> automatiquement depuis le label `com.docker.compose.project` du container Gluetun.

### 4. Lancer

```bash
docker compose up -d
```

Ouvrir : **http://localhost:8765**

Première connexion → entrez le compte que vous souhaitez créer (enregistré automatiquement).

### 5. Importer les serveurs

**Serveurs** → **Importer depuis Gluetun** : le companion lit les variables
`SERVER_NAMES`, `SERVER_COUNTRIES`, etc. directement depuis le container en cours
et importe chaque valeur avec son type de filtre.

Vous pouvez aussi ajouter des serveurs manuellement depuis le même écran.

---

## Fonctionnement interne

```
Cycle de benchmark (toutes les X heures)
  └─ Pour chaque serveur activé :
       1. Écriture de docker-compose.override.yml
          → variable cible = "<serveur>", toutes les autres vidées
       2. docker compose up -d
       3. Attente connexion VPN via poll proxy HTTP (timeout configurable)
       4. Warm-up TCP optionnel (2 s drainés, non comptés)
       5. Download depuis N endpoints (Cloudflare, Hetzner, Fast.com, OVH, Tele2)
          → médiane des Mbps mesurés
       6. Upload vers Cloudflare __up → Mbps
       7. Latence TTFB depuis N endpoints → médiane ms
       8. Enregistrement SQLite (DL, UL, latence, IPv4, IPv6)
       9. Retry automatique si échec (configurable), timeout global par serveur
      10. Auto-désactivation si N échecs consécutifs
  └─ Score pondéré par serveur (65 % cycle actuel + 35 % historique exponentiel)
  └─ Bascule vers le meilleur si différent du serveur actuel
  └─ Enregistrement cycle (durée totale, serveurs testés, meilleur serveur)
```

---

## Variables d'environnement

| Variable | Défaut | Description |
|---|---|---|
| `SECRET_KEY` | *(requis)* | Clé Flask pour les sessions |
| `GLUETUN_HOST` | `host.docker.internal` | Hôte du proxy HTTP Gluetun |
| `GLUETUN_PROXY_PORT` | `8887` | Port du proxy HTTP Gluetun |
| `GLUETUN_CONTAINER` | `gluetun-airvpn` | Nom du container Gluetun (pour Docker SDK) |
| `COMPOSE_DIR` | `/compose` | Chemin (dans le container) du dossier compose Gluetun |
| `COMPOSE_PROJECT` | *(auto-détecté)* | Nom du projet compose Gluetun |
| `DATA_DIR` | `/data` | Dossier de la base SQLite |

> Les paramètres de benchmark (flux parallèles, durée, warm-up, etc.) se configurent
> directement dans l'UI → **Paramètres**.

---

## Structure du projet

```
gluetun-companion/
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── run.py
└── app/
    ├── __init__.py        # factory Flask
    ├── database.py        # SQLite WAL + migrations
    ├── gluetun.py         # contrôle Docker + proxy VPN
    ├── speedtest.py       # download / upload / latence via proxy
    ├── scheduler.py       # APScheduler + cycle complet + test unitaire
    ├── routes.py          # routes Flask + API JSON + export CSV
    └── templates/
        ├── base.html      # layout, dark/light toggle, badge VPN down
        ├── login.html
        ├── dashboard.html # sparkline serveur actif, durée cycle
        ├── servers.html   # import, test unitaire, auto-exclude
        ├── history.html   # pagination, export CSV, upload
        ├── switches.html  # gain Mbps, temps de connexion
        └── settings.html  # tous les paramètres
```

---

## Notes

- Le benchmark **interrompt brièvement** les services qui transitent par Gluetun
  (qBittorrent, Sonarr, Radarr…) le temps de tester chaque serveur.
  Planifiez les cycles pendant les heures creuses ou augmentez l'intervalle.
- Le fichier `docker-compose.override.yml` est géré automatiquement — ne le modifiez pas.
- L'IPv6 est affiché si votre fournisseur VPN le supporte (AirVPN le supporte).
