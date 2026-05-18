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

- **Benchmark automatique** toutes les X heures — download, upload et latence par serveur
- **Mode Sidecar** (défaut) — un container `gluetun-companion-test` clone la config réelle
  de Gluetun pour chaque serveur ; `gluetun-companion-sidecar` mesure le débit via
  **Ookla + librespeed en parallèle** (mode dual, défaut), **Ookla seul**, **librespeed seul**
  ou **iperf3** directement dans le tunnel VPN. Votre Gluetun principal n'est jamais relancé
  pendant les tests — seulement une fois à la fin pour basculer vers le meilleur serveur
- **Résultats multi-sources** — les vitesses Ookla, librespeed et iperf3 sont stockées
  séparément et affichées dans le dashboard et l'historique
- **Mode Proxy HTTP** (optionnel, si sidecar désactivé) — mesure via le proxy HTTP Gluetun
  (port 8887), sans container supplémentaire, mais interrompt brièvement les services
  dépendants à chaque bascule de serveur
- **Téléchargement multi-flux** — N connexions TCP simultanées (configurable, défaut : 4)
- **Bascule automatique** vers le meilleur serveur (`docker compose up -d`),
  basée sur un score pondéré (65 % mesure actuelle + 35 % historique) ;
  les services dépendants (`network_mode: service:gluetun`) sont relancés automatiquement
- **5 types de filtre** : SERVER\_NAMES, SERVER\_COUNTRIES, SERVER\_REGIONS,
  SERVER\_CITIES, SERVER\_HOSTNAMES
- **Retry** configurable par serveur + timeout global par serveur
- **Auto-désactivation** d'un serveur après N échecs consécutifs
- **Web UI** dark/light, **FR/EN** — auth, dashboard avec sparkline, historique paginé, graphiques,
  page bascules avec gain Mbps et temps de connexion
- **Export CSV** de l'historique complet
- **Test unitaire** d'un serveur depuis l'UI sans attendre le prochain cycle
- **Notifications** à chaque bascule — webhook Discord (embed coloré) et/ou
  [Apprise](https://github.com/caronc/apprise/wiki) (Telegram, ntfy, Gotify, Slack, Pushover…)
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
      - /home/aerya/docker/dockge-enhanced/stacks/airvpn:/compose   # <-- adapter
    extra_hosts:
      - "host.docker.internal:host-gateway"
    environment:
      - TZ=Europe/Paris
      - SECRET_KEY=remplacer-par-une-chaine-aleatoire-longue   # openssl rand -hex 32
      - DATA_DIR=/data
      - GLUETUN_HOST=host.docker.internal
      - GLUETUN_PROXY_PORT=8887          # port du proxy HTTP Gluetun exposé sur l'hôte
      - GLUETUN_CONTAINER=gluetun-airvpn   # nom exact du service dans le compose Gluetun
      - COMPOSE_DIR=/compose

networks: {}
```

> **Companion dans la même stack que Gluetun ?**
> Si vous placez le companion dans le même `docker-compose.yml` que Gluetun,
> vous pouvez supprimer `extra_hosts` et utiliser le nom de service comme hôte :
> `GLUETUN_HOST: gluetun` (ou le nom de votre service Gluetun).
> Lors d'une bascule de serveur, Gluetun Companion cible désormais **uniquement le service
> Gluetun** (`docker compose up -d <service>`) — il ne se recrée donc pas lui-même.
> La configuration en stack séparée reste néanmoins recommandée pour éviter tout effet
> de bord lors des mises à jour d'image.

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

**Mode Sidecar (défaut)**

```
Cycle de benchmark (toutes les X heures)
  └─ Pour chaque serveur activé :
       1. Pull ghcr.io/aerya/gluetun-companion-sidecar:latest
       2. Lancement de gluetun-companion-test
          (copie de votre Gluetun, configuré sur le serveur cible)
       3. Lancement de gluetun-companion-sidecar
          (network_mode: container:gluetun-companion-test)
       4. Attente connexion VPN via /health polling (timeout configurable)
       5. Test de débit dans le tunnel VPN (selon moteur configuré) :
          - Dual (défaut) : Ookla + librespeed en parallèle, iperf3 en fallback
          - Ookla seul, librespeed seul ou iperf3 seul (configurable)
          → DL, UL, latence enregistrés par source
       6. Stop + suppression des containers et de l'image sidecar
       → Retry automatique si échec, timeout global par serveur
       → Auto-désactivation si N échecs consécutifs
  └─ Score pondéré par serveur (65 % cycle actuel + 35 % historique exponentiel)
  └─ Bascule du vrai Gluetun vers le meilleur (un seul redémarrage)
  └─ Notification Discord / Apprise (si configurée)
  └─ Enregistrement cycle (durée totale, serveurs testés, meilleur serveur)
```

**Mode Proxy HTTP (optionnel, si sidecar désactivé)**

```
Cycle de benchmark (toutes les X heures)
  └─ Pour chaque serveur activé :
       1. Écriture de docker-compose.override.yml
          → variable cible = "<serveur>", toutes les autres vidées
       2. docker compose up -d  ← le vrai Gluetun redémarre
       3. Attente connexion VPN via poll proxy HTTP (timeout configurable)
       4. Warm-up TCP optionnel (2 s drainés, non comptés)
       5. Download depuis N endpoints (Cloudflare, Hetzner, Fast.com, OVH, Tele2)
          → médiane des Mbps mesurés
       6. Upload vers Cloudflare __up → Mbps
       7. Latence TTFB depuis N endpoints → médiane ms
       8. Enregistrement SQLite
       → Les services dépendants de Gluetun sont brièvement interrompus
  └─ Score pondéré par serveur → bascule → notification → enregistrement cycle
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
| `DATA_DIR` | `/data` | Dossier de la base SQLite |

> Les paramètres de benchmark (flux parallèles, durée, warm-up, etc.) se configurent
> directement dans l'UI → **Paramètres**.

---

## Mode Sidecar

Le **mode Sidecar est activé par défaut**. Il est plus précis et moins intrusif que le
mode proxy : votre vrai Gluetun n'est jamais redémarré pendant les tests.

```
Pour chaque serveur à tester
  └─ Pull ghcr.io/aerya/gluetun-companion-sidecar:latest  (toujours la dernière version)
  └─ gluetun-companion-test    ← copie de votre Gluetun (même image + variables d'env)
                                  configurée avec la valeur SERVER_* cible
  └─ gluetun-companion-sidecar ← network_mode: container:gluetun-companion-test
                                  mesure via Ookla + librespeed (parallèle) dans le tunnel VPN
  └─ Stop + suppression des deux containers et de l'image sidecar du disque

Une fois tous les serveurs testés
  └─ Bascule du vrai Gluetun vers le meilleur serveur (un seul redémarrage)
```

**Moteur de test (configurable dans Paramètres → Mode Sidecar) :**
- **Dual** (défaut) — Ookla (Speedtest.net) + librespeed en parallèle ; les résultats des deux sources
  sont stockés séparément et la moyenne sert de valeur principale pour le classement
- **Ookla uniquement** — CLI officiel Speedtest.net, infrastructure massive, rarement bloquée par les VPN
- **librespeed uniquement** — librespeed-cli, serveurs publics librespeed.org (HTTP, rarement bloqué)
- **iperf3 uniquement** — connexions TCP directes vers des serveurs publics iperf3 (souvent bloqués par les IPs VPN)

**Options de fallback (configurables) :**
- **iperf3 en fallback** (activé par défaut) — si toutes les sources principales échouent, iperf3 est tenté en dernier recours
- **Proxy HTTP en fallback** (désactivé par défaut) — si le sidecar échoue complètement, bascule sur le mode proxy HTTP

**Avantages par rapport au mode proxy :**
- Votre vrai Gluetun (et tous les services qui en dépendent) n'est jamais interrompu pendant le benchmark
- Mesure du débit TCP brut sans surcharge proxy HTTP — plus précis sur les VPN rapides

**Mode proxy (optionnel) :** Paramètres → Mode Sidecar → désactiver.
Utile si vous n'avez pas accès au socket Docker.

### Containers à redémarrer après bascule

Dans **Paramètres → Containers à redémarrer après bascule**, vous pouvez définir une liste ordonnée de containers Docker à redémarrer automatiquement après chaque bascule de serveur VPN (modes proxy et sidecar).

- Les containers disponibles sont détectés automatiquement via l'API Docker — un menu déroulant vous permet de les sélectionner
- Les lignes peuvent être réordonnées par glisser-déposer
- Un délai de 3 secondes est appliqué entre chaque redémarrage
- Typiquement utile pour : `qbittorrent`, `radarr`, `sonarr`, ou tout service qui doit se reconnecter après un changement de tunnel VPN

> ⚠ **Prérequis :** le socket Docker (`/var/run/docker.sock`) doit être monté dans le container Gluetun Companion (déjà requis pour le mode sidecar).

> ⚠ **Connexion simultanée — valable pour tous les fournisseurs VPN**
>
> Le mode Sidecar ajoute **une connexion VPN simultanée supplémentaire** pendant toute la
> durée du benchmark (le container Gluetun de test). Si votre fournisseur limite le nombre
> de connexions simultanées (AirVPN : 3–5 selon l'abonnement ; la plupart des autres
> fournisseurs : idem), cette option consomme un slot de plus.
> Assurez-vous d'avoir un slot libre.
> Cet avertissement s'applique à **tous les fournisseurs compatibles avec Gluetun**,
> pas uniquement AirVPN.

---

## Notes

- **En mode sidecar (défaut) :** votre Gluetun principal n'est jamais relancé pendant les
  tests — les services dépendants (qBittorrent, Sonarr, Radarr…) ne sont pas interrompus.
  **En mode proxy (optionnel) :** le benchmark interrompt brièvement ces services le temps
  de tester chaque serveur. Planifiez les cycles pendant les heures creuses ou augmentez
  l'intervalle.
- **Fréquence et nombre de serveurs** : chaque test d'un serveur génère une reconnexion VPN.
  Tester 10 serveurs toutes les 2 heures représente 120 reconnexions par jour.
  La plupart des fournisseurs (dont AirVPN) limitent les connexions *simultanées* et non
  la fréquence, mais un intervalle trop court avec beaucoup de serveurs peut déclencher
  une détection d'abus. **6 h et moins de 10 serveurs** est un réglage raisonnable.
- Le fichier `docker-compose.override.yml` est géré automatiquement — ne le modifiez pas.
- L'IPv6 est affiché si votre fournisseur VPN le supporte (AirVPN le supporte).
