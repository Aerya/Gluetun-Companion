<p align="center">
  <img src="assets/logo.png" alt="Gluetun Companion" width="480">
</p>

# Gluetun Companion

Benchmark automatique de vos serveurs VPN [Gluetun](https://github.com/qdm12/gluetun), bascule vers le plus rapide, Web UI complète.

> 🇬🇧 [English version](README.en.md)

[![Build](https://github.com/Aerya/Gluetun-Companion/actions/workflows/docker-publish.yml/badge.svg?branch=main)](https://github.com/Aerya/Gluetun-Companion/actions/workflows/docker-publish.yml)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white)](https://github.com/Aerya/Gluetun-Companion/pkgs/container/gluetun-companion)
[![arch](https://img.shields.io/badge/arch-amd64%20%7C%20arm64-lightgrey)](#)
[![i18n](https://img.shields.io/badge/i18n-FR%20%7C%20EN-informational)](README.en.md)
[![Latest release](https://img.shields.io/github/v/release/Aerya/Gluetun-Companion?label=release&color=brightgreen)](https://github.com/Aerya/Gluetun-Companion/releases/latest)
[![Gluetun compatible](https://img.shields.io/badge/Gluetun-compatible-0d1117?logo=github&logoColor=white)](https://github.com/qdm12/gluetun)

> **Tu l'utilises ? Tu l'aimes ? [⭐ Mets une étoile !](https://github.com/Aerya/Gluetun-Companion/stargazers)** — ça prend deux secondes.

---

## Compatibilité

Gluetun Companion fonctionne avec **tous les fournisseurs VPN compatibles Gluetun** dès lors qu'au moins une de ces variables de filtre est présente dans votre configuration :

| Variable Gluetun | Filtre |
|---|---|
| `SERVER_NAMES` | Nom du serveur |
| `SERVER_COUNTRIES` | Pays |
| `SERVER_REGIONS` | Région |
| `SERVER_CITIES` | Ville |
| `SERVER_HOSTNAMES` | Hostname |

Indépendant de la technologie de tunnel : fonctionne identiquement avec OpenVPN, WireGuard ou toute autre tech supportée par Gluetun.

Conçu et testé en priorité pour **[AirVPN](https://airvpn.org/?referred_by=483746)** *(lien affilié)* — [variables de filtre AirVPN](https://github.com/qdm12/gluetun-wiki/blob/main/setup/providers/airvpn.md#optional-environment-variables).

---

## Fonctionnalités

- 🆕 **Pause pendant le benchmark** — liste de containers (torrents, Usenet…) stoppés avant le début du benchmark et relancés automatiquement à la fin, même en cas d'erreur ; évite que leur trafic fausse les mesures et prévient la surcharge du tunnel VPN sur matériel modeste
- 🆕 **Containers à redémarrer après bascule** — liste ordonnée (glisser-déposer), redémarrage séquentiel via `docker compose up -d --force-recreate` après chaque bascule VPN ; gère correctement les containers en `network_mode: service:gluetun`
- **Benchmark automatique** toutes les X heures — download, upload et latence par serveur
- **Mode Sidecar** (défaut) — un container `gluetun-companion-test` clone la config réelle de Gluetun pour chaque serveur ; `gluetun-companion-sidecar` mesure le débit via **Ookla + librespeed en parallèle** (mode dual, défaut), Ookla seul, librespeed seul ou iperf3 directement dans le tunnel VPN ; votre Gluetun principal n'est jamais relancé pendant les tests
- **Résultats multi-sources** — les vitesses Ookla, librespeed et iperf3 sont stockées séparément et affichées dans le dashboard et l'historique
- **Mode Proxy HTTP** (optionnel) — mesure via le proxy HTTP Gluetun sans container supplémentaire ; interrompt brièvement les services dépendants à chaque bascule
- **Téléchargement multi-flux** — N connexions TCP simultanées (configurable, défaut : 4)
- **Bascule automatique** vers le meilleur serveur (`docker compose up -d`), basée sur un score pondéré (65 % mesure actuelle + 35 % historique) ; les services dépendants (`network_mode: service:gluetun`) sont recréés automatiquement
- **5 types de filtre** : `SERVER_NAMES`, `SERVER_COUNTRIES`, `SERVER_REGIONS`, `SERVER_CITIES`, `SERVER_HOSTNAMES`
- **Retry** configurable par serveur + timeout global par serveur
- **Auto-désactivation** d'un serveur après N échecs consécutifs
- **Web UI** dark/light, FR/EN — auth, dashboard avec sparkline, historique paginé, graphiques, page bascules avec gain Mbps et temps de connexion
- **Export CSV** de l'historique complet
- **Test unitaire** d'un serveur depuis l'UI sans attendre le prochain cycle
- **Notifications** à chaque bascule — webhook Discord (embed coloré) et/ou [Apprise](https://github.com/caronc/apprise/wiki) (Telegram, ntfy, Gotify, Slack, Pushover…)
- **Purge automatique** de l'historique SQLite configurable (rétention en jours)
- **Endpoint `/healthz`** non authentifié pour les healthchecks Docker
- **Logs JSON structurés** optionnels via `LOG_JSON=1` (compatibles Loki/Grafana)
- **Base de données SQLite** (WAL) — aucune dépendance externe

---

## Démarrage rapide

### 1. Exposer le proxy HTTP Gluetun sur l'hôte

```yaml
# dans votre docker-compose.yml Gluetun existant
ports:
  - 8887:8888   # ou le port que vous avez configuré

environment:
  HTTPPROXY: "on"
  HTTPPROXY_LOG: "off"
  # HTTPPROXY_USER: ""       # optionnel — à reporter dans Paramètres de l'UI
  # HTTPPROXY_PASSWORD: ""
```

### 2. Monter le dossier compose de Gluetun

Le companion doit pouvoir écrire un `docker-compose.override.yml` dans le dossier qui contient votre `docker-compose.yml` Gluetun, puis relancer le service.

### 3. Lancer le companion

```yaml
services:
  gluetun-companion:
    image: ghcr.io/aerya/gluetun-companion:latest
    container_name: gluetun-companion
    restart: always
    ports:
      - 8765:8765
    volumes:
      - /chemin/vers/data:/data
      - /var/run/docker.sock:/var/run/docker.sock
      - /chemin/vers/stack/gluetun:/compose   # ← adapter
    extra_hosts:
      - "host.docker.internal:host-gateway"
    environment:
      - TZ=Europe/Paris
      - SECRET_KEY=remplacer-par-une-chaine-aleatoire   # openssl rand -hex 32
      - DATA_DIR=/data
      - GLUETUN_HOST=host.docker.internal
      - GLUETUN_PROXY_PORT=8887
      - GLUETUN_CONTAINER=gluetun-airvpn   # nom exact du container Gluetun
      - COMPOSE_DIR=/compose
```

```bash
docker compose up -d
```

Ouvrir **http://localhost:8765** — première connexion : entrez le compte à créer (enregistré automatiquement).

> **Companion dans la même stack que Gluetun ?**
> Supprimez `extra_hosts` et utilisez le nom de service : `GLUETUN_HOST: gluetun`.
> Lors d'une bascule, le companion cible uniquement le service Gluetun (`docker compose up -d <service>`) — il ne se recrée pas lui-même.

### 4. Importer les serveurs

**Serveurs → Importer depuis Gluetun** : le companion lit les variables `SERVER_NAMES`, `SERVER_COUNTRIES`, etc. directement depuis le container en cours et importe chaque valeur avec son type de filtre. Ajout manuel possible depuis le même écran.

---

## Variables d'environnement

| Variable | Défaut | Description |
|---|---|---|
| `SECRET_KEY` | *(requis)* | Clé Flask pour les sessions |
| `GLUETUN_HOST` | `host.docker.internal` | Hôte du proxy HTTP Gluetun |
| `GLUETUN_PROXY_PORT` | `8887` | Port du proxy HTTP Gluetun |
| `GLUETUN_CONTAINER` | `gluetun-airvpn` | Nom du container Gluetun |
| `COMPOSE_DIR` | `/compose` | Chemin (dans le container) du dossier compose Gluetun |
| `DATA_DIR` | `/data` | Dossier de la base SQLite |

Les paramètres de benchmark (flux, durée, warm-up, retry…) se configurent dans l'UI → **Paramètres**.

---

## Fonctionnement

### Mode Sidecar (défaut)

```
Cycle de benchmark (toutes les X heures)
  ├─ Containers "pause bench" stoppés (torrents, Usenet…)
  └─ Pour chaque serveur activé :
       1. Pull ghcr.io/aerya/gluetun-companion-sidecar:latest
       2. Lancement de gluetun-companion-test
          (copie de votre Gluetun, configuré sur le serveur cible)
       3. Lancement de gluetun-companion-sidecar
          (network_mode: container:gluetun-companion-test)
       4. Attente connexion VPN via /health polling (timeout configurable)
       5. Test de débit dans le tunnel VPN (moteur configurable) :
          - Dual (défaut) : Ookla + librespeed en parallèle, iperf3 en fallback
          - Ookla seul, librespeed seul, ou iperf3 seul
          → DL, UL, latence enregistrés par source
       6. Stop + suppression des containers et de l'image sidecar
       → Retry automatique si échec, timeout global par serveur
       → Auto-désactivation si N échecs consécutifs
  └─ Score pondéré (65 % cycle actuel + 35 % historique exponentiel)
  └─ Bascule du vrai Gluetun vers le meilleur (un seul redémarrage)
  └─ Containers "post-bascule" recréés (network namespace inclus)
  └─ Containers "pause bench" relancés (garanti — bloc finally)
  └─ Notification Discord / Apprise (si configurée)
```

**Moteurs de test disponibles (Paramètres → Mode Sidecar) :**
- **Dual** (défaut) — Ookla + librespeed en parallèle ; résultats des deux sources stockés séparément
- **Ookla uniquement** — CLI Speedtest.net, rarement bloqué par les IPs VPN
- **librespeed uniquement** — librespeed-cli, serveurs librespeed.org (HTTP)
- **iperf3 uniquement** — TCP direct vers serveurs publics iperf3 (souvent bloqués par VPN)

**Fallbacks :**
- iperf3 en dernier recours si toutes les sources principales échouent (activé par défaut)
- Proxy HTTP en fallback si le sidecar échoue complètement (désactivé par défaut)

> ⚠ **Connexion simultanée** : le mode sidecar consomme un slot VPN supplémentaire pendant toute la durée du benchmark. Vérifiez les limites de votre fournisseur (AirVPN : 3–5 selon l'abonnement).

### Mode Proxy HTTP (optionnel)

```
Cycle de benchmark (toutes les X heures)
  └─ Pour chaque serveur activé :
       1. Écriture de docker-compose.override.yml
       2. docker compose up -d  ← le vrai Gluetun redémarre
       3. Attente connexion VPN via poll proxy HTTP
       4. Warm-up TCP optionnel (2 s, non comptés)
       5. Download depuis N endpoints → médiane Mbps
       6. Upload → Mbps
       7. Latence TTFB → médiane ms
  └─ Score pondéré → bascule → notification
```

Activer via **Paramètres → Mode Sidecar → désactiver**.

### Containers à redémarrer après bascule

Dans **Paramètres → Containers à redémarrer après bascule** : liste ordonnée de containers recréés via `docker compose up -d --force-recreate` après chaque bascule VPN. Drag & drop pour réordonner. Utile pour `qbittorrent`, `radarr`, `sonarr`, ou tout service avec `network_mode: service:gluetun`.

### Containers à stopper pendant le benchmark

Dans **Paramètres → Containers à stopper pendant le benchmark** : liste de containers stoppés avant le benchmark et relancés après — dans tous les cas, même si le benchmark plante. Si un container est dans les deux listes, la liste de pause a priorité (pas de doublon). Utile pour `qbittorrent`, `sabnzbd`, `nzbget`, `transmission`.

---

## Notes

- **Mode sidecar (défaut) :** votre Gluetun principal n'est jamais relancé pendant les tests — les services dépendants ne sont pas interrompus. **Mode proxy (optionnel) :** le benchmark interrompt brièvement ces services à chaque test de serveur. Planifiez pendant les heures creuses.
- **Fréquence et nombre de serveurs :** chaque test génère une reconnexion VPN. Tester 10 serveurs toutes les 2 heures = 120 reconnexions/jour. La plupart des fournisseurs limitent les connexions *simultanées*, pas la fréquence — mais un intervalle trop court peut déclencher une détection d'abus. **6 h et moins de 10 serveurs** est un réglage raisonnable.
- Le fichier `docker-compose.override.yml` est géré automatiquement — ne le modifiez pas manuellement.
- L'IPv6 est affiché si votre fournisseur VPN le supporte (AirVPN le supporte).
- Le socket Docker (`/var/run/docker.sock`) est requis pour le mode sidecar, les containers post-bascule et la pause pendant le benchmark.

---

## Crédits

Merci à **[qdm12](https://github.com/qdm12/gluetun)** pour Gluetun, sans lequel ce projet n'existerait pas.

Merci à **Zup** pour les idées et les tests.

---

## Licence

[PolyForm Noncommercial 1.0.0](LICENSE) — usage personnel et associatif libre, usage commercial sur autorisation.
