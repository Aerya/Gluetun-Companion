# Gluetun Companion

Benchmark automatique des serveurs AirVPN via Gluetun, avec bascule automatique vers le meilleur serveur et Web UI.

## Fonctionnalités

- Test de vitesse (download + latence) de chaque serveur via le proxy HTTP Gluetun
- Planification automatique toutes les X heures
- Bascule automatique vers le serveur le plus rapide (`docker compose up --force-recreate`)
- Web UI dark theme avec auth, historique, graphiques
- Base de données SQLite — aucune dépendance externe

---

## Mise en route

### 1. Préparer le dossier compose de Gluetun

Le companion doit pouvoir écrire un `docker-compose.override.yml` dans le dossier
qui contient votre `docker-compose.yml` Gluetun, et relancer le service.

> **Important :** votre service Gluetun doit avoir pour **nom de service**
> la même valeur que `GLUETUN_CONTAINER` (par défaut `gluetun-airvpn`).

### 2. Exposer le port de l'API de contrôle Gluetun (réseau interne)

Le companion accède à l'API Gluetun sur le port **8000** (interne au réseau Docker).
Vous n'avez **pas besoin** de l'exposer sur l'hôte, les deux containers doivent
juste être sur le même réseau Docker.

Ajoutez `8000` à `FIREWALL_INPUT_PORTS` dans votre Gluetun si ce n'est pas déjà fait :

```yaml
# dans votre docker-compose gluetun existant
environment:
  FIREWALL_INPUT_PORTS: 936,8989,7878,5076,8081,9696,8887,19975,8000
```

### 3. Configurer le companion

Éditez `docker-compose.yml` et remplacez les trois valeurs marquées `# <-- CHANGE THIS` :

```yaml
volumes:
  - /chemin/absolu/vers/votre/dossier/gluetun:/compose   # dossier du compose Gluetun

environment:
  COMPOSE_PROJECT: nom_du_projet   # `docker compose ls` pour trouver le nom
  # ex : si votre dossier s'appelle "vpn" → projet = "vpn"

networks:
  vpn_net:
    name: nom_du_reseau_gluetun    # `docker network ls` pour trouver le nom
```

### 4. Lancer

```bash
docker compose up -d --build
```

Ouvrir : **http://localhost:8765**

Première connexion → entrez le compte que vous souhaitez créer (il sera enregistré automatiquement).

---

## Ajouter des serveurs à tester

Dans la Web UI → **Serveurs** → **Ajouter**.

Entrez le nom exact du serveur AirVPN tel qu'utilisé dans `SERVER_NAMES`
(ex : `Chamukuy`, `Elgafar`, `Dalim`, `Menkent`).

La liste complète des serveurs AirVPN est disponible ici :
https://github.com/qdm12/gluetun-wiki/blob/main/setup/providers/airvpn.md

---

## Fonctionnement interne

```
Cycle de benchmark (toutes les X heures)
  └─ Pour chaque serveur activé :
       1. Écriture de docker-compose.override.yml  →  SERVER_NAMES: "<serveur>"
       2. docker compose up -d --force-recreate gluetun-airvpn
       3. Attente connexion VPN  (poll GET /v1/openvpn/status)
       4. Download 10 Mo via proxy :8887  →  calcul Mbps
       5. Mesure latence TTFB via proxy
       6. Enregistrement SQLite
  └─ Sélection du meilleur serveur (download max)
  └─ Bascule finale si différent du serveur actuel
```

### Test de vitesse

Le test se fait en téléchargeant un fichier de taille configurable depuis
`speed.cloudflare.com` **via le proxy HTTP Gluetun** (port 8887).
Cela mesure la vitesse réelle du tunnel VPN, pas la vitesse de l'hôte.

---

## Variables d'environnement

| Variable | Défaut | Description |
|---|---|---|
| `SECRET_KEY` | *(requis)* | Clé Flask pour les sessions |
| `GLUETUN_HOST` | `gluetun-airvpn` | Nom du container Gluetun sur le réseau Docker |
| `GLUETUN_PROXY_PORT` | `8887` | Port du proxy HTTP Gluetun |
| `GLUETUN_API_PORT` | `8000` | Port de l'API de contrôle Gluetun |
| `GLUETUN_CONTAINER` | `gluetun-airvpn` | Nom du service dans le compose Gluetun |
| `COMPOSE_DIR` | `/compose` | Chemin (dans le container) du dossier compose Gluetun |
| `COMPOSE_PROJECT` | *(vide)* | Nom du projet compose Gluetun (`docker compose ls`) |
| `DATA_DIR` | `/data` | Dossier de la base SQLite |

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
    ├── database.py        # SQLite (WAL)
    ├── gluetun.py         # contrôle Docker + API Gluetun
    ├── speedtest.py       # test download/latence via proxy
    ├── scheduler.py       # APScheduler + cycle de benchmark
    ├── routes.py          # toutes les routes Flask + API JSON
    └── templates/
        ├── base.html
        ├── login.html
        ├── dashboard.html
        ├── servers.html
        ├── history.html
        ├── switches.html
        └── settings.html
```

---

## Notes

- Le benchmark **interrompt brièvement** tous les services qui passent par Gluetun
  (qBittorrent, Sonarr, Radarr…) le temps de tester chaque serveur.
  Planifiez les tests pendant les heures creuses.
- Le fichier `docker-compose.override.yml` est géré automatiquement.
  Ne le modifiez pas manuellement.
- Inspiré de [gluetun-switcher](https://github.com/fuzzzor/gluetun-switcher).
