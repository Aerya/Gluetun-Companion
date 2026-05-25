<p align="center">
  <img src="assets/logo.png" alt="Gluetun Companion" width="200">
</p>

# Gluetun Companion

Benchmark automatique de vos serveurs VPN [Gluetun](https://github.com/qdm12/gluetun), bascule vers le plus rapide, Web UI complète.

> 🇬🇧 [English version](README.en.md)

<p align="center">
<a href="https://github.com/Aerya/Gluetun-Companion/actions/workflows/docker-publish.yml"><img src="https://github.com/Aerya/Gluetun-Companion/actions/workflows/docker-publish.yml/badge.svg?branch=main" alt="Build"></a>
<a href="https://github.com/Aerya/Gluetun-Companion/blob/main/.github/workflows/trivy-scan.yml"><img src="https://img.shields.io/badge/Trivy-enabled-1904DA?logo=aquasecurity&logoColor=white" alt="Trivy CVE scan"></a>
<a href="https://github.com/Aerya/Gluetun-Companion/blob/main/.github/dependabot.yml"><img src="https://img.shields.io/badge/Dependabot-enabled-025E8C?logo=dependabot&logoColor=white" alt="Dependabot"></a>
<a href="https://github.com/Aerya/Gluetun-Companion/pkgs/container/gluetun-companion"><img src="https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white" alt="Docker"></a>
<a href="#"><img src="https://img.shields.io/badge/arch-amd64%20%7C%20arm64-lightgrey" alt="arch"></a>
<a href="README.en.md"><img src="https://img.shields.io/badge/i18n-FR%20%7C%20EN-informational" alt="i18n"></a>
<a href="https://github.com/qdm12/gluetun"><img src="https://img.shields.io/badge/Gluetun-compatible-0d1117?logo=github&logoColor=white" alt="Gluetun compatible"></a>
<a href="https://airvpn.org/?referred_by=483746"><img src="https://img.shields.io/badge/AirVPN-compatible-1a7a3d?logoColor=white" alt="AirVPN"></a>
<a href="https://discord.com/developers/docs/resources/webhook"><img src="https://img.shields.io/badge/Discord-webhook-5865F2?logo=discord&logoColor=white" alt="Discord"></a>
<a href="https://github.com/caronc/apprise"><img src="https://img.shields.io/badge/Apprise-compatible-3d85c8?logo=python&logoColor=white" alt="Apprise"></a>
<a href="https://github.com/Tecnativa/docker-socket-proxy"><img src="https://img.shields.io/badge/socket--proxy-compatible-blueviolet?logo=docker&logoColor=white" alt="Docker socket-proxy"></a>
</p>

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

## Table des matières

- [Compatibilité](#compatibilité)
- [Fonctionnalités](#fonctionnalités)
  - [Mesure de performances](#mesure-de-performances)
  - [Sélection & bascule automatique](#sélection--bascule-automatique)
  - [Multi-provider WireGuard](#multi-provider-wireguard)
  - [Catalogue de serveurs Gluetun](#catalogue-de-serveurs-gluetun)
  - [Gestion des containers Docker](#gestion-des-containers-docker)
  - [AirVPN](#airvpn)
  - [Analyse & historique](#analyse--historique)
  - [Interface & notifications](#interface--notifications)
  - [Intégration & infrastructure](#intégration--infrastructure)
- [Démarrage rapide](#démarrage-rapide)
- [Variables d'environnement](#variables-denvironnement)
- [Fonctionnement](#fonctionnement)
  - [Mode Sidecar (défaut)](#mode-sidecar-défaut)
  - [Mode Proxy HTTP (optionnel)](#mode-proxy-http-optionnel)
  - [Vérification rapide avant benchmark](#vérification-rapide-avant-benchmark-option)
  - [Scheduling adaptatif](#scheduling-adaptatif-option)
  - [Filtrage du benchmark par type d'entrée](#filtrage-du-benchmark-par-type-dentrée-option)
  - [Pré-filtre AirVPN avant benchmark](#pré-filtre-airvpn-avant-benchmark-option-dédié-airvpn)
  - [Écoute Docker events](#écoute-docker-events)
  - [Profils d'usage](#profils-dusage)
  - [Profils VPN WireGuard](#profils-vpn-wireguard)
  - [Pools de rotation](#pools-de-rotation)
  - [Score de sélection — composantes de stabilité](#score-de-sélection--composantes-de-stabilité)
  - [Score de confiance par serveur](#score-de-confiance-par-serveur)
  - [Jitter & Packet Loss](#jitter--packet-loss)
  - [Patterns horaires](#vue-patterns-horaires-historypatterns)
  - [Détection nouveaux serveurs AirVPN](#détection-de-nouveaux-serveurs-airvpn)
  - [Notifications contextuelles](#notifications-contextuelles)
  - [REST API](#rest-api)
  - [Endpoint /metrics Prometheus](#endpoint-prometheus-metrics)
  - [Cycle automatique vs manuel](#cycle-automatique-vs-déclenchement-manuel)
- [Notes](#notes)
- [Sécurité](#sécurité)
- [Crédits](#crédits)
- [Licence](#licence)

---

## Fonctionnalités

### Mesure de performances
- **Mode Sidecar** (défaut) — un container `gluetun-companion-test` clone la config réelle de Gluetun pour chaque serveur ; `gluetun-companion-sidecar` mesure le débit via **Ookla + librespeed en parallèle** (mode dual, défaut), Ookla seul, librespeed seul ou iperf3 directement dans le tunnel VPN ; votre Gluetun principal n'est jamais relancé pendant les tests
- **Mode Proxy HTTP** (optionnel) — mesure via le proxy HTTP Gluetun sans container supplémentaire ; interrompt brièvement les services dépendants à chaque bascule
- **Résultats multi-sources** — les vitesses Ookla, librespeed et iperf3 sont stockées séparément et affichées dans le dashboard et l'historique
- **Téléchargement multi-flux** — N connexions TCP simultanées (configurable, défaut : 4)
- **Benchmark automatique** toutes les X heures — download, upload et latence par serveur ; cycle automatique désactivable (déclenchement manuel uniquement)
- **Pré-filtrage du benchmark** *(option)* — sélectionnez les **types d'entrées** à inclure dans chaque cycle (`SERVER_NAMES`, `SERVER_COUNTRIES`, `SERVER_CITIES`, `SERVER_REGIONS`, `SERVER_HOSTNAMES`) ; par défaut tous les types sont testés ; les serveurs exclus restent dans la liste et peuvent être testés manuellement ; configurable dans Paramètres → Filtrage du benchmark
- **Vérification rapide avant benchmark** *(option)* — teste uniquement le serveur actif avant chaque cycle ; si le débit est dans la plage ±N% par rapport au dernier résultat connu, le benchmark complet est ignoré — aucun container stoppé, aucun redémarrage VPN ; déclenche le benchmark complet uniquement si les performances dérivent significativement
- **Scheduling adaptatif** *(option)* — analyse les patterns horaires de débit et de variance pour identifier les meilleures et pires fenêtres de benchmark ; affiche les plages recommandées dans les Paramètres ; option de décalage automatique : si le prochain cycle tombe sur une heure défavorable, il est décalé jusqu'à 3 h vers la prochaine fenêtre favorable
- **Benchmark rapide à la demande** — bouton disponible en permanence (dashboard et paramètres) ; teste uniquement le serveur actif via le proxy HTTP de Gluetun, résultat en quelques secondes, aucune interruption VPN, résultat sauvegardé dans l'historique
- **Jitter & Packet Loss** — stabilité réseau mesurée à chaque test (21 sondes TTFB en mode proxy, ICMP via sidecar) ; indicateur 🟢/🟡/🔴 sur la page Serveurs, colonnes dédiées dans l'historique, jitter affiché dans les patterns horaires ; intégré dans le score de sélection (pénalité jusqu'à −15 % jitter / −25 % perte)
- **Latence DNS** *(sidecar)* — mesure du temps de résolution DNS depuis l'intérieur du tunnel VPN via `dig` (4 domaines en parallèle, médiane retournée) ; détecte les résolveurs lents, surchargés ou qui interceptent les requêtes ; colonne dans l'historique, tooltip sur l'indicateur Stabilité, données dans les patterns horaires
- **Écoute Docker events** — thread daemon qui surveille les événements `start` du container Gluetun ; si Gluetun redémarre de lui-même (crash, mise à jour, watchdog), déclenche automatiquement un quick check après N secondes (délai de reconnexion VPN) ; si la dérive de débit dépasse le seuil configuré et que la bascule automatique est activée, lance immédiatement un benchmark complet ; les redémarrages déclenchés par Companion lui-même sont ignorés ; cooldown de 5 min entre deux déclenchements

### Sélection & bascule automatique
- **Bascule automatique** vers le meilleur serveur (`docker compose up -d`), basée sur un score pondéré intégrant débit actuel, historique exponentiel, jitter, perte paquets et reconnexions involontaires (via Docker events) ; curseur *Priorité débit vs stabilité* configurable ; **6 profils d'usage** sélectionnables (Équilibré, Jeu en ligne, BitTorrent, DDL, Téléchargement, Streaming) — chaque profil pondère différemment les métriques pour trouver le serveur le mieux adapté à l'usage réel ; les services dépendants (`network_mode: service:gluetun`) sont recréés automatiquement
- **Bascule manuelle** vers n'importe quel serveur configuré depuis la page Serveurs — Gluetun est reconfiguré et les containers `network_mode: service:gluetun` sont recréés automatiquement
- **5 types de filtre** : `SERVER_NAMES`, `SERVER_COUNTRIES`, `SERVER_REGIONS`, `SERVER_CITIES`, `SERVER_HOSTNAMES`
- **Retry** configurable par serveur + timeout global par serveur
- **Auto-désactivation** d'un serveur après N échecs consécutifs

### Pools de rotation

- **Rotation sans benchmark** — basculez vers un serveur d'un groupe prédéfini sans lancer de cycle de mesure complet ; idéal pour la rotation périodique ou les changements ponctuels
- **Critères combinables** (UNION) — chaque pool accepte autant de critères que nécessaire : serveur précis, type de filtre Gluetun (`SERVER_NAMES`, `SERVER_COUNTRIES`, `SERVER_CITIES`, `SERVER_REGIONS`, `SERVER_HOSTNAMES`), profil VPN WireGuard, ou tous les serveurs actifs ; les critères s'additionnent
- **3 modes de sélection** : 🎲 aléatoire, 🔄 tour à tour (round-robin avec curseur persistant), 🏆 meilleur score historique
- **Top-N** — restreindre le pool aux N serveurs avec le meilleur score moyen (si non renseigné, tous les candidats sont éligibles)
- **Manuel ou planifié** — déclenchement immédiat depuis l'UI, ou rotation automatique sur un intervalle configurable (en heures ; ex. toutes les 12 h ou tous les 2 jours)
- **Quick bench optionnel** — après chaque bascule, un test proxy rapide mesure le débit du nouveau serveur et l'enregistre dans l'historique (méthode `proxy_qc`)
- **Notifications** — alerte Discord/Apprise à chaque rotation (manuelle ou automatique), avec serveur précédent, nouveau serveur, débit si quick bench activé

### Multi-provider WireGuard

- **Profils VPN WireGuard** — créez plusieurs profils d'identifiants WireGuard depuis **Paramètres → Profils VPN WireGuard** ; chaque profil est associé à un fournisseur (AirVPN, Mullvad, ProtonVPN, NordVPN, IVPN, Surfshark, Windscribe, ou Custom WireGuard pour tout autre fournisseur compatible)
- **Chiffrement des secrets** — les clés privées et autres champs sensibles sont chiffrés en base (Fernet/AES-128, clé dérivée de `SECRET_KEY` via PBKDF2HMAC-SHA256 avec 480 000 itérations) ; changer `SECRET_KEY` rend les profils illisibles (comportement documenté)
- **Liaison serveurs ↔ profils** — sur la page **Serveurs**, assignez un profil VPN à chaque serveur via un menu déroulant ; une colonne *Provider* affiche le profil associé ; le filtre `?profile=` permet de ne voir que les serveurs d'un profil donné ou les serveurs non assignés
- **Alerte serveurs orphelins** — un badge d'alerte signale les serveurs sans profil assigné dès qu'au moins un profil WireGuard est configuré ; ces serveurs continuent de fonctionner normalement mais ne pourront pas être retenus par le benchmark multi-profil
- **Benchmark multi-profil** — en mode sidecar, chaque serveur est testé avec les identifiants WireGuard de son profil injectés dans le container temporaire ; lors de la bascule finale, Companion écrit automatiquement `VPN_SERVICE_PROVIDER`, `VPN_TYPE=wireguard` et toutes les variables `WIREGUARD_*` dans `docker-compose.override.yml`
- **Politique de rotation** — trois modes configurables dans **Paramètres → Profils VPN WireGuard → Politique de rotation** :
  - `none` — Companion reste toujours dans le profil actuellement actif ; les serveurs d'autres profils ne sont jamais retenus à la fin du benchmark
  - `free` — choisit le meilleur serveur tous profils confondus (comportement par défaut sans profils)
  - `conditional` — bascule vers un autre profil uniquement si son meilleur serveur est supérieur de plus de N % au meilleur serveur du profil actif (seuil configurable, défaut 10 %)
- **Colonne Provider dans `/history`** — chaque ligne de l'historique affiche le profil WireGuard associé au serveur testé (visible uniquement si au moins un profil est configuré)

**Providers supportés :**

| Provider | Type | Variables Gluetun |
|---|---|---|
| AirVPN | Natif | `WIREGUARD_PRIVATE_KEY`, `WIREGUARD_PRESHARED_KEY`, `WIREGUARD_ADDRESSES` |
| FastestVPN | Natif | `WIREGUARD_PRIVATE_KEY`, `WIREGUARD_ADDRESSES` |
| IVPN | Natif | `WIREGUARD_PRIVATE_KEY`, `WIREGUARD_ADDRESSES` |
| Mullvad | Natif | `WIREGUARD_PRIVATE_KEY`, `WIREGUARD_ADDRESSES` |
| NordVPN | Natif | `WIREGUARD_PRIVATE_KEY` |
| ProtonVPN | Natif | `WIREGUARD_PRIVATE_KEY`, `WIREGUARD_ADDRESSES` |
| Surfshark | Natif | `WIREGUARD_PRIVATE_KEY`, `WIREGUARD_ADDRESSES` |
| Windscribe | Natif | `WIREGUARD_PRIVATE_KEY`, `WIREGUARD_PRESHARED_KEY`, `WIREGUARD_ADDRESSES` |
| Custom WireGuard | Via `custom` | Endpoint IP/port, clé publique, clé privée, adresses, clé pré-partagée (optionnel) |

> Le mode Custom WireGuard couvre tous les fournisseurs non listés ci-dessus (CyberGhost, PrivateVPN, PureVPN, TorGuard, VPN Unlimited, VyprVPN…) dès lors qu'ils fournissent un fichier de configuration WireGuard standard.

---

### Catalogue de serveurs Gluetun
- **Téléchargement GitHub** — le Sidecar catalogue télécharge les listes de serveurs directement depuis le dépôt public [`qdm12/gluetun-servers`](https://github.com/qdm12/gluetun-servers/tree/main/pkg/servers) ; **aucun volume à monter**, aucune modification de votre configuration Gluetun requise
- **Mise à jour automatique** — la liste est rafraîchie **à chaque cycle de benchmark** (intervalle configurable dans Paramètres → Planification & Cycle, défaut : 6 h) ; un bouton dédié dans les Paramètres et dans le modal `/servers` permet de forcer une mise à jour immédiate
- **Auto-ajout des nouveaux serveurs** *(option)* — quand de nouveaux serveurs apparaissent dans le catalogue pour un **pays**, une **région** ou une **ville** que vous avez déjà configuré, Companion les ajoute automatiquement à votre liste (type `SERVER_NAMES`) sans intervention manuelle ; désactivé par défaut, activable dans **Paramètres → Catalogue**
- **Notification de changements** *(option)* — Discord/Apprise envoyés à chaque refresh si des serveurs sont ajoutés ou supprimés du catalogue, avec le détail par provider (+N/-N) ; activable dans **Paramètres → Notifications**
- **3 modes d'import dans les Paramètres** :
  1. **Tous les providers** — importe les serveurs de tous les providers disponibles sur GitHub
  2. **Provider au choix** — importe uniquement les serveurs du provider sélectionné manuellement
  3. **Provider actif** — détecte automatiquement le provider configuré dans votre Gluetun et n'importe que ses serveurs
  — pour chacun de ces modes, option de **lancer un benchmark complet** immédiatement après l'import (méthode configurée dans Paramètres, sur tous les serveurs de la liste)
- **Tous les types de filtre** — chaque serveur est importé avec ses attributs complets : `SERVER_NAMES`, `SERVER_COUNTRIES`, `SERVER_CITIES`, `SERVER_REGIONS`, `SERVER_HOSTNAMES`
- **Sélection multi-filtre depuis `/servers`** — sélectionnez des serveurs en mixant librement les types de filtre (ex : noms + pays + villes simultanément) ; Companion applique le bon filtre dans Gluetun et change le type à la volée si nécessaire
- ⚠️ **ProtonVPN** — Les serveurs gratuits ProtonVPN sont disponibles via le **Catalogue**. Pour accéder aux serveurs Premium, utilisez **Importer depuis Gluetun** afin de récupérer les serveurs déjà configurés dans votre compose Gluetun (compte payant requis).

**Prérequis** — le sidecar catalogue a uniquement besoin d'un accès HTTPS sortant (réseau bridge Docker, activé par défaut). **Aucune modification de `docker-compose.yml` requise.**

### Gestion des containers Docker
- **Containers réseau Gluetun (auto-gérés)** — tous les containers en `network_mode: service:gluetun` sont détectés et relancés automatiquement après chaque bascule
- **Containers à redémarrer après bascule** — uniquement pour les containers utilisant le proxy HTTP/SOCKS5 de Gluetun ; liste ordonnée (glisser-déposer)
- **Pause pendant le benchmark** — liste de containers (torrents, Usenet…) stoppés avant le début du benchmark et relancés automatiquement à la fin, même en cas d'erreur
- **Mise à jour automatique des images Docker** *(option)* — au moment de la bascule, Companion peut mettre à jour les images avant de relancer les containers : Gluetun lui-même, les containers réseau auto-gérés, les containers à redémarrer après bascule et les containers en pause pendant le benchmark ; activable individuellement par container depuis les Paramètres

### AirVPN
- **Sélecteur de serveurs AirVPN intégré** — bouton *+ Ajouter un serveur AirVPN* sur la page Serveurs : données en direct depuis `airvpn.org/api/status/` (cache 5 min), quatre onglets — liste complète searchable, répartition géographique par pays, onglet **Recommandés** (charge < 50 %, santé OK, < 30 utilisateurs) et onglet **Changements** (nouveaux serveurs détectés, serveurs disparus, évolutions de charge, top 5 pays les plus sains) ; ajout multi-sélection en un clic
- **Pré-filtre AirVPN avant benchmark** *(optionnel, dédié [AirVPN](https://airvpn.org/?referred_by=483746))* — au démarrage du benchmark, les serveurs **[AirVPN](https://airvpn.org/?referred_by=483746)** de type `SERVER_NAMES` dont la **charge** ou le **nombre d'utilisateurs** dépasse un seuil configurable sont automatiquement ignorés ; données issues du cache AirVPN (mis à jour toutes les 5 min) ; les serveurs sans données AirVPN ne sont jamais exclus ; seuils configurables dans Paramètres → Filtrage du benchmark
- **Détection de nouveaux serveurs AirVPN** *(optionnel)* — compare l'API AirVPN avec vos serveurs configurés toutes les 24 h ; bannière et badge sur la page Serveurs + onglet *Changements* dans le modal d'ajout ; notification Discord/Apprise avec mention optionnelle

### Analyse & historique
- **Score de confiance par serveur** — indicateur 🟢/🟡/🔴 sur la page Serveurs et dans l'historique ; basé sur le nombre de mesures et la variabilité des résultats ; intégré dans le score de sélection automatique (pondération légère)
- **Patterns horaires** (`/history/patterns`) — graphique barres 0h–23h du débit moyen par tranche horaire, coloré selon les performances relatives ; meilleure et pire heure affichées ; permet de repérer les créneaux de saturation serveur
- **Colonnes triables** — cliquez sur n'importe quel en-tête de colonne dans `/history` (11 colonnes) et `/servers` (8 colonnes) pour trier ; une seconde presse inverse l'ordre ; indicateurs ▲/▼/⇅ visuels ; tri persistant via pagination
- **Test unitaire** d'un serveur depuis l'UI sans attendre le prochain cycle
- **Export CSV** de l'historique complet

### Interface & notifications
- **Web UI** dark/light, FR/EN — auth, dashboard avec sparkline, historique paginé, graphiques, page bascules avec gain Mbps et temps de connexion
- **Notifications contextuelles** — 10 types d'alertes configurables indépendamment (bascule auto/manuelle, auto-exclusion, benchmark sans résultat, fin de benchmark, résultat quick check, rotation de pool, nouveaux serveurs AirVPN, changements catalogue, changement fenêtre optimale) via webhook Discord (embed coloré) et/ou [Apprise](https://github.com/caronc/apprise/wiki) (Telegram, ntfy, Gotify, Slack, Pushover…) ; sévérité 🔴/🟡/🔵 ; mention Discord globale avec seuil de sévérité configurable
- **Purge automatique** de l'historique SQLite configurable (rétention en jours)

### Intégration & infrastructure
- **Endpoint `/healthz`** non authentifié pour les healthchecks Docker
- **Endpoint `/metrics`** au format Prometheus — débit, latence, bascules, serveur actif ; optionnellement protégé par Bearer token ; compatible Grafana
- **REST API `/api/v1/`** protégée par Bearer token — statut VPN, liste des serveurs, historique, bascules, déclenchement benchmark complet ou rapide ; conçue pour Home Assistant, n8n, scripts bash
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

  socket-proxy:
    image: tecnativa/docker-socket-proxy
    container_name: socket-proxy
    restart: always
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    environment:
      CONTAINERS: 1
      IMAGES: 1
      NETWORKS: 1
      VOLUMES: 1
      POST: 1
      DELETE: 1
    networks:
      - companion-net

  gluetun-companion:
    image: ghcr.io/aerya/gluetun-companion:latest
    container_name: gluetun-companion
    restart: always
    ports:
      - 8765:8765
    volumes:
      - /chemin/vers/data:/data
      - /chemin/vers/stack/gluetun:/compose   # ← adapter
    extra_hosts:
      - "host.docker.internal:host-gateway"
    environment:
      - TZ=Europe/Paris
      - SECRET_KEY=remplacer-par-une-chaine-aleatoire   # openssl rand -hex 32
      - DATA_DIR=/data
      - GLUETUN_HOST=host.docker.internal
      - GLUETUN_PROXY_PORT=8887
      - GLUETUN_CONTAINER=gluetun-airvpn   # nom exact du container Gluetun (le service Compose est détecté automatiquement)
      - COMPOSE_DIR=/compose
      - DOCKER_HOST=tcp://socket-proxy:2375
      # Optionnel : protéger /metrics par un Bearer token.
      # Laisser vide (ou non défini) pour un accès libre — standard pour les scrapes Prometheus internes.
      # - METRICS_TOKEN=votre-token-secret
    networks:
      - companion-net
    depends_on:
      - socket-proxy

networks:
  companion-net:
```

```bash
docker compose up -d
```

> **Pourquoi `socket-proxy` ?**
> Le socket Docker donne un accès quasi-total à l'hôte. Le proxy [Tecnativa](https://github.com/Tecnativa/docker-socket-proxy) s'intercale entre Companion et le socket, et restreint l'accès aux opérations nécessaires : lecture des containers/images/réseaux/volumes, et POST/DELETE requis pour créer et supprimer les containers sidecar temporaires. Il empêche notamment tout accès direct au daemon (exec, info, swarm…). Fonctionnement identique pour l'utilisateur, surface d'attaque réduite.

Ouvrir **http://localhost:8765** — première connexion : entrez le compte à créer (enregistré automatiquement).

> **Companion dans la même stack que Gluetun ?**
> Supprimez `extra_hosts` et utilisez le nom de service : `GLUETUN_HOST: gluetun`.
> Lors d'une bascule, le companion cible uniquement le service Gluetun (`docker compose up -d <service>`) — il ne se recrée pas lui-même.

### 4. Importer les serveurs

**Serveurs → Importer depuis Gluetun** : le companion lit les variables `SERVER_NAMES`, `SERVER_COUNTRIES`, etc. directement depuis le container en cours et importe chaque valeur avec son type de filtre. Ajout manuel possible depuis le même écran.

> ⚠️ **Companion benchmarke chaque serveur individuellement par son nom.** Configurer `SERVER_COUNTRIES`, `SERVER_REGIONS` ou `SERVER_CITIES` ajoute une seule entrée (ex : « France ») — Companion ne découvre **pas** automatiquement les serveurs individuels de ce pays. Ajoutez chaque serveur par son nom (`SERVER_NAMES`) pour que le benchmark fonctionne. **Minimum 2 serveurs nommés requis.**

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
| `DOCKER_HOST` | *(socket local)* | Remplacer par `tcp://socket-proxy:2375` si vous utilisez le proxy Tecnativa |
| `METRICS_TOKEN` | *(vide)* | Si défini, l'endpoint `/metrics` exige `Authorization: Bearer <token>` ; laisser vide pour un accès libre (standard réseau interne) |

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

### Sélecteur de serveurs AirVPN

Sur **Serveurs → + Ajouter un serveur AirVPN** : un modal charge les données en direct depuis l'[API AirVPN](https://airvpn.org/?referred_by=483746) (cache 5 min côté serveur). Quatre onglets :
- **Serveurs** — liste complète avec barre de charge colorée (vert/orange/rouge), nombre d'utilisateurs, statut de santé, tri par colonne, recherche en temps réel
- **Par pays** — sections collapsibles par pays avec flag emoji, badge 🏆 **Best** sur le serveur le moins chargé, bouton "Sélectionner tous" par pays
- **⭐ Recommandés** — serveurs réunissant les trois critères : charge < 50 %, santé OK et moins de 30 utilisateurs connectés ; badge vert indiquant le nombre disponible
- **↔ Changements** — diff depuis la dernière consultation : nouveaux serveurs apparus (ajoutables en un clic), serveurs disparus de l'API, changements de charge ≥ 10 % (avec flèche ↑↓ et delta), top 5 pays classés par pourcentage de serveurs sains puis charge moyenne

Les serveurs déjà dans la base sont grisés et leur case à cocher est désactivée. La barre de recherche filtre simultanément tous les onglets. Sélection multiple, ajout en un clic.

### Vérification rapide avant benchmark *(option)*

Activer via **Paramètres → Planification & Benchmark → Vérification rapide avant benchmark**.

Lorsque cette option est activée, chaque cycle commence par un test de débit sur le **serveur actuellement actif uniquement** — avant de stopper des containers ou de relancer Gluetun :

- **Dans la plage (défaut ±15 %)** : le benchmark complet est ignoré. Aucun container n'est stoppé, Gluetun n'est pas relancé, aucune interruption VPN. Le cycle se termine en quelques secondes.
- **Hors plage** : le benchmark complet se lance normalement — tous les serveurs sont testés, le meilleur est sélectionné.

> **Implémentation** : la vérification rapide passe **exclusivement par le proxy HTTP** de Gluetun — aucun container sidecar créé, aucune attente de reconnexion VPN. Résultat obtenu en 10–15 secondes.

Idéal pour des intervalles fréquents (ex. toutes les 2–3 h) où l'on veut un contrôle rapide sans le coût d'un benchmark complet à chaque fois.

> La tolérance est configurable (1–100 %). Une valeur de 15 signifie : si le débit actuel est compris entre 85 % et 115 % du dernier résultat connu, le benchmark complet est ignoré.

### Scheduling adaptatif *(option)*

Activer via **Paramètres → Planification & Benchmark → Scheduling adaptatif**.

Companion analyse l'historique des tests pour calculer, pour chaque tranche horaire (0h–23h), le **débit moyen** et le **coefficient de variation** (CV = σ/μ). Une heure avec un débit élevé et une faible variance est une bonne fenêtre de benchmark — les mesures y sont représentatives et reproductibles.

**Score par heure** = `débit_moyen × max(0, 1 − CV/100)`

- 🟢 **Bonne fenêtre** — score ≥ 70 % du maximum
- 🔴 **À éviter** — score < 50 % du maximum

**Prérequis** : au moins 3 tests dans au moins 6 tranches horaires différentes. Les résultats s'affichent directement dans la carte Paramètres dès que les données sont suffisantes.

**Décalage automatique** *(sous-option)* : si le cycle planifié tombe sur une heure défavorable, le benchmark est décalé d'un maximum de 3 h vers la prochaine fenêtre favorable. Si aucune n'est trouvée dans ce délai, le benchmark s'exécute immédiatement. Une fois terminé, le planificateur reprend son intervalle normal.

> Cette option est complémentaire du cycle automatique — elle ne le remplace pas. L'intervalle configuré reste la référence ; le décalage adaptatif n'ajuste que le prochain déclenchement si l'heure est jugée défavorable.

### Filtrage du benchmark par type d'entrée *(option)*

Activer via **Paramètres → Planification & Cycle → Filtrage du benchmark → Types de serveurs à inclure**.

Par défaut, le benchmark teste **toutes** les entrées activées dans `/servers`, quel que soit leur type Gluetun. Avec cette option, vous sélectionnez exactement quels types participeront au cycle :

| Type | Variable Gluetun | Usage typique |
|---|---|---|
| **Nom** | `SERVER_NAMES` | Serveurs AirVPN individuels, nom précis |
| **Pays** | `SERVER_COUNTRIES` | Sélection géographique large |
| **Ville** | `SERVER_CITIES` | Sélection géographique précise |
| **Région** | `SERVER_REGIONS` | Région / état |
| **Hostname** | `SERVER_HOSTNAMES` | Hostname FQDN |

- **Tous cochés** (défaut) : comportement identique à avant — aucun filtrage.
- **Certains cochés** : seules les entrées des types cochés sont testées ; les autres restent dans `/servers` et peuvent être testées individuellement via le bouton « Tester maintenant ».

> Utile si vous avez des entrées de type `country`/`region` pour une bascule de secours mais ne souhaitez les tester que ponctuellement, sans les inclure dans chaque cycle automatique.

### Pré-filtre AirVPN avant benchmark *(option, dédié [AirVPN](https://airvpn.org/?referred_by=483746))*

Activer via **Paramètres → Planification & Cycle → Filtrage du benchmark → Filtre AirVPN avant benchmark**.

Lorsque vous avez ajouté un grand nombre de serveurs **[AirVPN](https://airvpn.org/?referred_by=483746)** (type `SERVER_NAMES`), le benchmark complet peut être très long. Ce pré-filtre permet d'**ignorer automatiquement les serveurs surchargés** au moment du lancement du cycle :

- **Charge max (%)** — `0` = désactivé. Ex : `70` → les serveurs affichant une charge > 70 % dans le cache AirVPN sont ignorés pour ce cycle.
- **Utilisateurs max** — `0` = désactivé. Ex : `30` → les serveurs avec plus de 30 utilisateurs connectés sont ignorés.

Les deux seuils sont indépendants et cumulables — un serveur est ignoré dès qu'**au moins un** seuil activé est dépassé.

**Données utilisées** : la table interne `airvpn_snapshot`, mise à jour toutes les **5 minutes** depuis l'API `airvpn.org/api/status/`. Aucun appel API supplémentaire n'est effectué au lancement du benchmark.

**Serveurs sans données** : un serveur de type `name` sans entrée dans le snapshot (provider non-AirVPN, serveur hors API) n'est **jamais filtré** — il est toujours inclus dans le benchmark.

**Périmètre** : ce filtre ne s'applique qu'aux serveurs de type `name` (**[AirVPN](https://airvpn.org/?referred_by=483746)**). Les entrées de type `country`, `city`, `region`, `hostname` ne sont jamais affectées.

> Les serveurs ignorés restent dans `/servers`, peuvent être testés manuellement, et seront à nouveau candidats au prochain cycle si leur charge a baissé entre-temps.

### Écoute Docker events

Un thread daemon démarre avec Companion et surveille en continu le flux d'événements Docker filtré sur le container Gluetun. À chaque événement `start` reçu :

```
Événement Docker "start" reçu sur le container Gluetun
  ├─ Redémarrage initié par Companion ? (fenêtre de 180 s)  → ignoré silencieusement
  ├─ Cooldown actif ? (5 min depuis le dernier déclenchement) → ignoré
  ├─ Benchmark déjà en cours ?                               → ignoré
  └─ OK — programmation d'un quick check différé
       1. Attente de N secondes (= valeur « Délai de reconnexion »)
          pour laisser le VPN se reconnecter
       2. Quick check via le proxy HTTP sur le serveur actif
          ├─ VPN pas encore prêt (pas de réponse proxy)
          │    → log d'avertissement, abandon
          ├─ Aucun résultat de référence en base
          │    → résultat enregistré comme nouvelle référence, fin
          ├─ Débit dans la plage ±N %
          │    → log OK, fin
          └─ Dérive détectée (débit hors plage)
               ├─ Bascule auto activée → benchmark complet immédiat
               └─ Bascule auto désactivée → log d'avertissement uniquement
```

**Suppression des redémarrages Companion** : quand Companion bascule vers un serveur (`switch_server()`), il active une fenêtre de suppression de 180 secondes. Tout événement `start` reçu pendant cette fenêtre est ignoré — ce mécanisme évite une boucle infinie où Companion déclencherait lui-même un quick check après chaque bascule qu'il vient d'initier.

**Badge dans l'historique** : les tests déclenchés par un événement Docker sont marqués `docker_event` en base. Un badge sombre `auto` apparaît sur la ligne correspondante dans l'historique (`/history`), avec un tooltip explicatif.

**Prérequis** : le socket Docker (ou le proxy Tecnativa) doit être accessible depuis Companion, et la variable `GLUETUN_CONTAINER` doit correspondre au nom exact du container Gluetun.

### Score de confiance par serveur

Un indicateur coloré est affiché sur la page **Serveurs** (colonne *Fiabilité*) et dans l'**Historique** pour chaque serveur. Il reflète la fiabilité des mesures accumulées.

| Niveau | Conditions |
|---|---|
| 🟢 Élevé | ≥ 5 mesures **et** variabilité < 40 % |
| 🟡 Modéré | 2–4 mesures ou variabilité 40–70 % |
| 🔴 Faible | ≤ 1 mesure, variabilité > 70 % ou échecs consécutifs |

La **variabilité** (coefficient de variation) mesure l'écart-type des débits rapporté à la moyenne : 0 % = résultats identiques à chaque test, 100 % = résultats très dispersés. Les tests `proxy_qc` sont exclus du calcul.

Le score influence légèrement la sélection automatique du meilleur serveur : HIGH × 1,0 · MEDIUM × 0,95 · LOW × 0,85 appliqués sur le score pondéré.

### Profils d'usage

Companion propose 6 **profils d'usage** sélectionnables depuis la page **Serveurs** (barre de pills) ou depuis **Paramètres → Bascule automatique → Profil d'usage**.

Le profil actif détermine **comment le meilleur serveur est sélectionné** à la fin de chaque cycle de benchmark, en pondérant différemment les métriques mesurées.

| Profil | Critère principal | Usage typique |
|---|---|---|
| **Équilibré** (défaut) | Score pondéré existant (débit + historique + stabilité) | Usage général — comportement identique à avant |
| **Jeu en ligne** | Faible latence + faible jitter | FPS, MMO, jeux compétitifs |
| **BitTorrent** | Upload multiflux maximal | qBittorrent, Transmission, Deluge |
| **DDL (mono-flux)** | Débit monoflux | Usenet (SABnzbd), téléchargeurs directs (JDownloader) |
| **Téléchargement (multi-flux)** | Débit download multiflux maximal | Radarr/Sonarr, transferts volumineux |
| **Streaming vidéo** | Débit stable + faible jitter | Jellyfin, Plex, lecture directe |

**Algorithme** : pour chaque résultat du cycle en cours, Companion calcule le `_weighted_score` (débit + historique + stabilité), puis normalise [0,1] l'ensemble des résultats sur chaque axe. La combinaison pondérée des scores normalisés détermine le meilleur serveur selon le profil actif. Le profil **Équilibré** reproduit exactement le comportement antérieur — aucune régression.

**Profil DDL et test monoflux** : le profil DDL exploite une métrique supplémentaire, le **débit monoflux** (`dl_single_mbps`), mesurée après le test principal (connexion VPN déjà établie, sans surcoût de reconnexion). Ce test est **optionnel** et désactivé par défaut — activer via **Paramètres → Mesure de vitesse → Test monoflux (DDL)**.

**Page Serveurs** : la barre de profils affiche le **meilleur serveur pour le profil actif** (calculé sur les moyennes historiques). Ce serveur est mis en évidence par un badge 🏆 sur sa ligne (masqué en profil Équilibré).

**Score explicable** : chaque serveur affiché dans la vue tableau dispose d'un bouton 📊 (icône graphique) à côté de son nom. Un clic ouvre un popover détaillant la contribution de chaque métrique au score final — débit download, upload, latence, jitter, perte de paquets — sous forme de barres de progression pondérées, avec les valeurs brutes mesurées. Seules les métriques effectivement utilisées par le profil actif sont affichées.

**Fenêtre temporelle de scoring** : par défaut, les moyennes utilisées pour le classement des serveurs sont calculées sur les **30 derniers jours**. Ce paramètre est ajustable dans **Paramètres → Bascule automatique → Fenêtre de scoring** : 7 j, 14 j, 30 j, ou toutes les données. Une fenêtre courte favorise les performances récentes ; une fenêtre longue lisse les pics ponctuels.

**Détection d'outliers** : option activable dans **Paramètres → Bascule automatique → Filtrage des valeurs aberrantes**. Lorsqu'elle est active, chaque série de résultats par serveur et par métrique est filtrée via la méthode IQR (interquartile range × 1,5) avant le calcul des moyennes. Les mesures manifestement aberrantes (pic réseau, saturation ponctuelle) sont ignorées pour le scoring — elles restent visibles dans l'historique. Requiert au minimum 4 mesures par serveur pour s'appliquer.

### Profils VPN WireGuard

Les profils WireGuard permettent de gérer plusieurs fournisseurs ou identités VPN dans une seule instance Companion, avec bascule automatique optimisée entre eux.

#### Création d'un profil

Dans **Paramètres → Profils VPN WireGuard** :

1. Choisissez le provider dans le menu déroulant → les champs de configuration apparaissent dynamiquement selon les variables requises par Gluetun pour ce fournisseur
2. Remplissez les champs (clé privée, adresses IP, etc.) — les champs marqués 🔒 sont chiffrés avant stockage
3. Nommez le profil (ex. « Mullvad — Suède », « ProtonVPN — Gaming »)
4. Les options *Actif* et *Rotation autorisée* permettent d'inclure ou exclure le profil des cycles automatiques

> **Sécurité des clés** : les valeurs chiffrées sont préfixées `enc:` en base. Elles ne sont déchiffrées qu'au moment de la construction de l'override Compose ou du lancement d'un container sidecar — jamais exposées dans les logs ni dans l'export de configuration.

#### ⚠️ Clé WireGuard dédiée aux tests sidecar (obligatoire)

> **Si vous utilisez le mode sidecar pour les benchmarks avec WireGuard, vous devez configurer une paire de clés WireGuard distincte dans Paramètres → Profils VPN WireGuard → Clé WireGuard dédiée aux tests.**

**Pourquoi c'est nécessaire :** les containers sidecar de test clonent l'environnement complet de votre container Gluetun principal, y compris sa `WIREGUARD_PRIVATE_KEY`. Quand un container de test initie un nouveau handshake WireGuard depuis une adresse IP différente avec la même clé, le fournisseur VPN met à jour la route du peer… et le tunnel de votre Gluetun principal tombe. Résultat : le VPN passe en état *unhealthy*, et Companion affiche « VPN down » en rouge.

**Solution :** générez une seconde paire de clés WireGuard auprès de votre fournisseur (procédure identique à la configuration initiale — une clé supplémentaire dans votre compte client), puis renseignez dans Companion :
- **Clé privée WireGuard (tests)** — nouvelle clé privée, distincte de celle de votre profil principal
- **Adresse IP WireGuard (tests)** — l'adresse IP assignée à cette clé par votre fournisseur (format CIDR, ex. `10.x.x.x/32`)
- **Clé pré-partagée (optionnelle)** — uniquement si votre fournisseur en exige une

Cette clé dédiée est injectée dans tous les containers de test à la place de la clé principale. Elle s'applique à tous les fournisseurs WireGuard. **Tant qu'elle n'est pas configurée, une alerte rouge s'affiche dans les paramètres.**

#### Liaison serveurs ↔ profils

Sur la page **Serveurs** :

- La colonne *Provider* affiche le profil WireGuard assigné à chaque serveur
- Si aucun profil n'est assigné, un menu déroulant permet l'assignation directe depuis le tableau
- Le filtre `?profile=<id>` (dropdown dans la barre de filtres) limite l'affichage aux serveurs d'un profil ou aux serveurs non assignés (`__none__`)
- Les serveurs sans profil pendant qu'au moins un profil est configuré sont signalés par une alerte *(serveurs orphelins)*

#### Benchmark multi-profil — flux d'exécution

```
Cycle de benchmark avec profils WireGuard
  ├─ Chargement et déchiffrement des vars WireGuard
  │    pour chaque profil_id distinct dans la liste de serveurs
  │    → cache en mémoire pour la durée du cycle (clés déchiffrées, non persistées)
  └─ Pour chaque serveur activé :
       1. Récupération de l'extra_env du profil associé
          (VPN_SERVICE_PROVIDER, VPN_TYPE=wireguard, WIREGUARD_*)
       2. Lancement de gluetun-companion-test avec ces variables injectées
          (les vars du profil s'ajoutent aux vars du container réel Gluetun)
       3. Test de débit via gluetun-companion-sidecar (identique au mode standard)
  └─ Sélection du meilleur serveur selon la politique de rotation :
       ├─ none        → contraint au profil du serveur Gluetun actuellement actif
       ├─ conditional → bascule cross-profil si gain > seuil (défaut 10 %)
       └─ free        → meilleur global, tous profils confondus
  └─ Bascule Gluetun :
       → écriture de VPN_SERVICE_PROVIDER + VPN_TYPE + WIREGUARD_* dans l'override Compose
       → docker compose up -d (un seul redémarrage Gluetun)
```

#### Politique de rotation

| Mode | Comportement |
|---|---|
| **none** | Companion cherche le meilleur serveur dans le profil actuellement actif. Si aucun résultat n'est disponible pour ce profil (tous exclus, tous orphelins), aucune bascule. |
| **free** | Tous les serveurs testés sont candidats — le meilleur global est retenu sans égard au profil. |
| **conditional** | Le benchmark est global, mais la bascule vers un autre profil n'a lieu que si `score_meilleur_global > score_meilleur_du_profil_actif × (1 + seuil/100)`. Autrement, le meilleur serveur du profil actif est conservé. |

> Le seuil du mode `conditional` est configurable de 1 à 100 % dans les Paramètres. Un seuil de 10 % signifie : « ne change de profil que si le gain est supérieur à 10 % ».

---

### Pools de rotation

Les pools de rotation permettent de basculer vers un serveur d'un groupe prédéfini **sans déclencher de benchmark complet**. Accessible depuis la page **Rotation** dans la barre de navigation.

#### Création d'un pool

Dans **Rotation → Nouveau pool** :

1. Donnez un nom au pool (ex. « Gaming FR », « Fallback EU »)
2. Choisissez le **mode de sélection** :
   - 🎲 **Aléatoire** — `random.choice()` parmi les candidats
   - 🔄 **Tour à tour** — cycle alphabétique avec curseur persistant entre deux rotations
   - 🏆 **Meilleur score** — candidat avec le meilleur débit moyen historique
3. Définissez un **Top-N** optionnel : si renseigné, seuls les N serveurs avec le meilleur score moyen sont éligibles, même si les critères en sélectionnent davantage
4. Ajoutez un ou plusieurs **critères** (UNION — chaque critère ajoute des candidats) :
   - `Tous les serveurs actifs` — inclut l'intégralité des serveurs activés dans Companion
   - `Serveur précis` — saisissez le nom exact ; l'autocomplete propose les serveurs existants
   - `Type de filtre Gluetun` — choisissez la variable (`SERVER_COUNTRIES`, `SERVER_NAMES`, etc.) et optionnellement une valeur (vide = tous les serveurs de ce type)
   - `Profil VPN WireGuard` — tous les serveurs assignés à un profil WireGuard spécifique
5. Configurez la **planification** : rotation automatique toutes les N heures (désactivée = manuel uniquement)
6. Activez le **quick bench** si vous souhaitez enregistrer le débit après chaque bascule

L'aperçu des candidats est mis à jour en temps réel dans le modal pendant la configuration.

#### Flux d'exécution d'une rotation

```
Rotation déclenchée (manuelle ou automatique) :
  1. Résolution des candidats
     ├─ UNION de tous les critères du pool
     └─ Filtrage top-N par score moyen (si activé)
  2. Sélection du serveur cible (random / round-robin / best-score)
  3. switch_server() → écriture docker-compose.override.yml + docker compose up -d
     └─ Si profil WireGuard associé : injection VPN_SERVICE_PROVIDER + WIREGUARD_* dans l'override
  4. Si quick bench activé :
     ├─ Attente reconnexion VPN (connection_wait_seconds)
     ├─ Test proxy rapide (proxy_qc)
     └─ Enregistrement dans speed_tests (test_trigger='pool_rotation')
  5. Mise à jour de l'état du pool (last_rotated_at, next_rotation_at, curseur round-robin)
  6. Notification Discord/Apprise (si activé)
```

#### Planification automatique

Le scheduler vérifie toutes les **5 minutes** si des pools ont une rotation en attente (`next_rotation_at <= now`). Si un benchmark est en cours, la rotation est différée au prochain tick (sans modifier `next_rotation_at`).

> Les rotations de pool et les benchmarks sont **indépendants** — ils ne se bloquent pas mutuellement, mais une rotation ne se déclenche pas pendant un benchmark actif.

#### Notifications de rotation de pool

| Type | Sévérité | Contenu |
|---|---|---|
| 🟡 Rotation de pool | Moyen | Nom du pool, mode (auto/manuel), serveur précédent → nouveau, débit si quick bench activé, IP publique |

---

### Score de sélection — composantes de stabilité

Le score final de sélection intègre désormais **quatre composantes de fiabilité**, toutes pondérées par le curseur *Priorité débit vs stabilité* (Paramètres) :

```
score = (w_cur × débit_actuel + w_hist × historique_exp)
        × confidence_factor
        × effective_stability

effective_stability = 1 − (stability_weight/100) × (1 − raw_stability)

raw_stability = jitter_factor × loss_factor × reconnect_factor
```

| Composante | Source | Pénalité max |
|---|---|---|
| **Jitter** | Mesuré à chaque test (jitter_ms) | −15 % à 150 ms |
| **Perte paquets** | Mesuré à chaque test (packet_loss_pct) | −25 % à 10 % de perte |
| **Reconnexions involontaires** | Docker events sur 30 j (test_trigger=docker_event) | −10 % par reconnexion, max −30 % |
| **Confiance** (variance historique) | Coefficient de variation sur tous les tests de la fenêtre de scoring (proxy_qc exclus) | −15 % (LOW) · −5 % (MEDIUM) |

**Curseur Priorité débit vs stabilité** (Paramètres → Bascule automatique) :
- **0** — seul le débit compte, toutes les pénalités sont désactivées
- **30** (défaut) — 30 % des pénalités sont appliquées
- **100** — pénalités complètes — un serveur à 300 Mbps avec 3 reconnexions involontaires + jitter élevé peut perdre jusqu'à ~40 % de score

> Un serveur à 200 Mbps sans reconnexion et avec un jitter stable sera préféré à un 300 Mbps qui déconnecte toutes les heures, dès lors que `stability_weight ≥ ~20`.

### Vue patterns horaires (`/history/patterns`)

Accessible depuis **Historique → Patterns horaires**, cette vue affiche les performances moyennes par tranche horaire (0h–23h) pour un serveur donné.

- Graphique en barres colorées selon les performances relatives au maximum du serveur : 🟢 ≥ 85 % · 🟡 65–85 % · 🟠 45–65 % · 🔴 < 45 %
- Heures en heure locale (variable d'environnement `TZ` respectée)
- Meilleure et pire heure affichées en stat cards
- Tests rapides (`proxy_qc`) exclus
- Utile pour planifier les benchmarks aux créneaux les plus favorables

### Détection de nouveaux serveurs AirVPN

Fonctionnalité **désactivée par défaut**, uniquement pour les utilisateurs AirVPN. Activable dans **Paramètres → Notifications**.

**Logique :**
1. Toutes les 24 h, Companion récupère la liste AirVPN via `airvpn.org/api/status/`
2. Il compare avec les serveurs configurés (type `name`) pour déterminer quels pays vous utilisez
3. Si un nouveau serveur apparaît dans un de ces pays, il est stocké dans la base pendant 7 jours

**Surfaces UI :**
- **Badge** `+N` sur le bouton *Ajouter un serveur AirVPN* (page Serveurs)
- **Bannière dismissable** en haut de la page Serveurs : *« 3 nouveaux serveurs disponibles dans vos pays (NL, FR) »* avec lien vers le modal
- **Onglet Changements** dans le modal d'ajout : section *Nouveaux serveurs détectés* avec badge ⭐ *Nouveau* et case à cocher pour ajout direct ; filtre de recherche unifié

**Notification Discord/Apprise :**
Envoyée uniquement lors de la découverte de nouveaux serveurs, regroupée par pays. Utilise le champ *Mention Discord* global (voir [Notifications contextuelles](#notifications-contextuelles)).

> Après 7 jours, les serveurs quittent automatiquement la liste des "nouveaux". Les serveurs ajoutés à votre liste ne s'affichent plus dans le badge/bannière.

### Notifications contextuelles

Companion envoie des alertes ciblées via **webhook Discord** et/ou **[Apprise](https://github.com/caronc/apprise/wiki)** selon les événements. Chaque type d'alerte est activable indépendamment dans **Paramètres → Notifications**.

| Type d'alerte | Sévérité | Activé par défaut | Déclenchement |
|---|---|---|---|
| 🔴 Auto-exclusion serveur | Critique | ✅ | Un serveur est désactivé après N échecs consécutifs |
| 🔴 Benchmark sans résultat | Critique | ✅ | Le cycle complet se termine sans aucun résultat valide |
| 🟡 Bascule automatique | Moyen | ✅ | Companion bascule vers un meilleur serveur |
| 🟡 Rotation de pool | Moyen | ✅ | Un pool de rotation bascule vers un nouveau serveur (auto ou manuel) |
| 🟡 Nouveaux serveurs AirVPN | Moyen | *(selon détection AirVPN)* | Nouveaux serveurs détectés dans vos pays |
| 🔵 Bascule manuelle | Info | ❌ | Bascule déclenchée manuellement depuis l'UI |
| 🔵 Fin de benchmark | Info | ❌ | Cycle de benchmark terminé avec succès |
| 🔵 Déjà sur le meilleur | Info | ❌ | Le serveur actif est déjà le meilleur — aucun changement |
| 🔵 Résultat quick check | Info | ✅ | Benchmark rapide manuel terminé (serveur, vitesse, delta vs baseline) |
| 🔵 Changements catalogue | Info | ❌ | Serveurs ajoutés ou supprimés lors d'un refresh catalogue (détail par provider) |
| 🔵 Fenêtre optimale changée | Info | ❌ | L'heure globale optimale de benchmark a changé (basé sur les patterns historiques) |

**Mention Discord globale** : un seul champ `Mention Discord` (ex. `<@123456789>` pour un utilisateur, `<@&987654321>` pour un rôle) s'applique à toutes les alertes. Un seuil de sévérité est configurable :
- **Critique uniquement** (défaut) — mention uniquement pour les alertes 🔴
- **Moyen et critique** — mention pour 🔴 et 🟡
- **Toutes** — mention pour toutes les alertes

> La mention est injectée dans le payload Discord via `allowed_mentions` pour garantir la délivrance même sur les serveurs avec restrictions de mentions.

---

### Jitter & Packet Loss

Chaque test mesure automatiquement la **stabilité** de la connexion VPN, en plus du débit.

**Méthode selon le mode :**
- **Mode proxy** — 21 sondes TTFB (Time To First Byte) réparties sur 3 cibles (Cloudflare, Google, Quad9). La variance des temps de réponse donne le jitter, les requêtes échouées donnent le taux de perte.
- **Mode sidecar** — l'endpoint `/ping` du container sidecar effectue un ping ICMP sur les mêmes 3 cibles (20 paquets chacune). Retombe sur None si l'ancienne version du sidecar ne supporte pas `/ping`.

**Métriques produites :**
- `jitter_ms` — écart-type des temps de réponse (ms) — représente la variabilité/instabilité
- `packet_loss_pct` — pourcentage de requêtes/paquets perdus
- `ping_min_ms` / `ping_max_ms` — meilleur et pire temps de réponse

**Surfaces UI :**
- **Page Serveurs** — colonne *Stabilité* : point coloré 🟢 (jitter < 15 ms, perte < 1 %) / 🟡 (< 50 ms, < 5 %) / 🔴 (au-delà), tooltip avec valeurs détaillées
- **Historique** — colonnes *Jitter* et *Perte* avec code couleur identique par ligne
- **Patterns horaires** — le tooltip de chaque barre inclut le jitter moyen de la tranche horaire

**Intégration dans le score de sélection :**
Le score est multiplié par un facteur de pénalité cumulatif :
- Jitter : `max(0.85, 1 − jitter_ms / 1000)` → pénalité jusqu'à −15 %
- Perte : `max(0.75, 1 − packet_loss_pct / 40)` → pénalité jusqu'à −25 %

> Un serveur rapide mais instable sera donc déclassé au profit d'un serveur légèrement moins rapide mais fiable.

### Endpoint Prometheus `/metrics`

L'endpoint `GET /metrics` expose les métriques clés au format texte Prometheus, sans dépendance externe.

**Métriques disponibles** (par serveur) :
- `gluetun_companion_server_avg_dl_mbps` — débit download moyen (benchmarks complets uniquement, `proxy_qc` exclu)
- `gluetun_companion_server_avg_ul_mbps` — débit upload moyen
- `gluetun_companion_server_avg_latency_ms` — latence moyenne
- `gluetun_companion_server_test_count` — nombre total de tests
- `gluetun_companion_server_failure_count` — nombre de tests échoués
- `gluetun_companion_server_consecutive_failures` — échecs consécutifs en cours
- `gluetun_companion_server_enabled` — 1 si activé pour le benchmark
- `gluetun_companion_server_active` — 1 si c'est le serveur Gluetun actuellement actif

**Métriques globales** :
- `gluetun_companion_switches_total` — nombre total de bascules
- `gluetun_companion_switches_success_total` — bascules réussies
- `gluetun_companion_benchmark_running` — 1 si un benchmark est en cours
- `gluetun_companion_last_switch_timestamp_seconds` — timestamp Unix de la dernière bascule

**Authentification** : par défaut ouvert (standard pour un réseau interne). Deux façons de protéger `/metrics` par Bearer token : définir la variable d'environnement `METRICS_TOKEN`, ou configurer un **token API** dans Paramètres → API (les deux sont supportés, `METRICS_TOKEN` a la priorité).

**Scrape Prometheus** (à ajouter dans `prometheus.yml`) :
```yaml
scrape_configs:
  - job_name: gluetun-companion
    static_configs:
      - targets: ['gluetun-companion:8765']
    # Si METRICS_TOKEN est défini :
    # bearer_token: your-secret-token
```

---

### REST API

L'API est **désactivée par défaut**. Pour l'activer : **Paramètres → REST API → Générer un nouveau token**.

**Authentification** : toutes les requêtes doivent inclure l'en-tête :
```
Authorization: Bearer <votre-token>
```

**Endpoints disponibles :**

| Méthode | URL | Description |
|---|---|---|
| `GET` | `/api/v1/status` | Serveur actif, état VPN, benchmark en cours, prochain cycle |
| `GET` | `/api/v1/servers` | Liste complète des serveurs avec débit moyen, jitter, fiabilité |
| `GET` | `/api/v1/history` | Historique des tests (`?limit=50&offset=0&server=Castor`) |
| `GET` | `/api/v1/switches` | Historique des bascules (`?limit=20`) |
| `POST` | `/api/v1/benchmark/trigger` | Déclencher un benchmark complet (asynchrone, HTTP 202) |
| `POST` | `/api/v1/benchmark/trigger-quick` | Déclencher un test rapide proxy (asynchrone, HTTP 202) |

**Exemples curl :**
```bash
# Statut
curl -H "Authorization: Bearer <token>" http://localhost:8765/api/v1/status

# Déclencher un benchmark
curl -X POST -H "Authorization: Bearer <token>" http://localhost:8765/api/v1/benchmark/trigger

# Historique des 10 derniers tests du serveur Castor
curl -H "Authorization: Bearer <token>" \
  "http://localhost:8765/api/v1/history?limit=10&server=Castor"
```

**Codes de retour :**
- `200` — succès (GET)
- `202` — déclenchement accepté (POST trigger)
- `401` — token invalide ou absent
- `403` — API désactivée (aucun token configuré)
- `409` — un benchmark est déjà en cours (POST trigger)

> Les POST triggers retournent immédiatement — le benchmark tourne en arrière-plan. Utilisez `GET /api/v1/status` pour suivre la progression (`benchmark_running`).

### Cycle automatique vs déclenchement manuel

Dans **Paramètres → Planification & Benchmark** : le cycle automatique peut être désactivé via le toggle *Activer le cycle de benchmark automatique*. Le champ intervalle est alors grisé. Deux boutons restent disponibles à tout moment (dashboard et paramètres) :

- **Benchmark rapide** — teste uniquement le serveur actif via le proxy HTTP de Gluetun ; résultat en quelques secondes, aucune interruption VPN, résultat sauvegardé dans l'historique (méthode `proxy_qc`).
- **Benchmark complet** — lance un cycle complet immédiatement, quels que soient le cycle automatique et l'option *Vérification rapide*. Utilise la méthode configurée (sidecar ou proxy), label affiché entre parenthèses sur le bouton.

---

## Export / import de configuration

Accessible depuis **Paramètres**, le bouton **Exporter la configuration** génère un fichier `companion-config.json` contenant les paramètres *hors secrets* (mots de passe, tokens, webhooks ne sont pas exportés). Ce fichier peut être réimporté sur une autre instance via le bouton **Importer**. Si l'import modifie l'intervalle de benchmark ou le cycle automatique, le planificateur est rechargé immédiatement.

---

## Dashboard Grafana

Un fichier JSON de dashboard Grafana est téléchargeable depuis **Paramètres**. Il est pré-câblé sur les métriques Prometheus de Companion et comprend des panneaux pour :

- Débit descendant/montant par serveur (bar gauge)
- Latence, jitter, perte de paquets, DNS (bar gauge)
- Indice de confiance et score de profil (bar gauge)
- Erreurs par type (donut chart)
- Tableau récapitulatif de tous les serveurs

### Métriques Prometheus disponibles

En plus des métriques de base (`avg_dl`, `avg_ul`, `avg_latency`, `test_count`, `failure_count`, `enabled`, `active`), Companion expose :

| Métrique | Description |
|---|---|
| `gluetun_companion_server_avg_jitter_ms` | Jitter moyen (tests sidecar uniquement) |
| `gluetun_companion_server_avg_loss_pct` | Perte de paquets moyenne |
| `gluetun_companion_server_avg_dns_ms` | Latence DNS moyenne |
| `gluetun_companion_server_confidence` | Indice de confiance : 0=LOW, 1=MEDIUM, 2=HIGH |
| `gluetun_companion_server_score` | Score du profil actif [0–1] |
| `gluetun_companion_server_last_benchmark_ts_seconds` | Timestamp Unix du dernier test |
| `gluetun_companion_errors_total{type}` | Compteur d'erreurs par type : timeout, connection, vpn, other |

---

## Notes

- **Mode sidecar (défaut) :** votre Gluetun principal n'est jamais relancé pendant les tests — les services dépendants ne sont pas interrompus. **Mode proxy (optionnel) :** le benchmark interrompt brièvement ces services à chaque test de serveur. Planifiez pendant les heures creuses.
- **Fréquence et nombre de serveurs :** chaque test génère une reconnexion VPN. Tester 10 serveurs toutes les 2 heures = 120 reconnexions/jour. La plupart des fournisseurs limitent les connexions *simultanées*, pas la fréquence — mais un intervalle trop court peut déclencher une détection d'abus. **6 h et moins de 10 serveurs** est un réglage raisonnable.
- Le fichier `docker-compose.override.yml` est géré automatiquement — ne le modifiez pas manuellement.
- L'IPv6 est affiché si votre fournisseur VPN le supporte (AirVPN le supporte).
- Le socket Docker (`/var/run/docker.sock`) est requis pour le mode sidecar, les containers post-bascule et la pause pendant le benchmark.

---

## Sécurité

- **CSRF** — Toutes les actions POST (formulaires et AJAX) sont protégées par un token CSRF via session serveur. L'en-tête `X-CSRF-Token` est injecté automatiquement sur chaque `fetch` non-GET grâce à un intercepteur JavaScript.
- **XSS** — Les données issues d'API tierces (AirVPN) injectées dans le DOM via `innerHTML` sont systématiquement échappées par une fonction `_esc()` (HTML entity encoding) avant insertion. Les attributs `onclick`/`onchange` inline présents dans les composants dynamiques ne contiennent que des valeurs JSONifiées ou des constantes — aucune donnée utilisateur non échappée n'y est interpolée.
- **SECRET_KEY** — L'application refuse de démarrer si `SECRET_KEY` est absente ou égale à la valeur par défaut (`dev-secret-change-me`, `remplacer-par-une-chaine-aleatoire-longue`). Génère une clé sécurisée avec : `openssl rand -hex 32`.
- **Injection YAML** — La valeur du filtre de serveur est assainie avant écriture dans `docker-compose.override.yml` (retours à la ligne supprimés, guillemets et backslashs échappés).
- **Socket Docker** — Le socket Docker est sécurisé via [docker-socket-proxy](https://github.com/Tecnativa/docker-socket-proxy), qui restreint les appels autorisés : lecture (containers, images, réseaux, volumes) + POST/DELETE pour la gestion des sidecars temporaires. Tout accès direct au daemon Docker (exec, swarm, info…) est bloqué.
- **Anti brute-force** — Le login bloque une IP après 5 échecs en 5 minutes pendant 15 minutes (compteur en mémoire, remis à zéro à la connexion réussie).
- **Exposition réseau** — Gunicorn écoute sur `0.0.0.0:8765` (toutes interfaces). **Ne pas exposer ce port directement sur Internet.** Sur un serveur accessible publiquement, placez Companion derrière un reverse proxy (Nginx, Caddy, Traefik) avec HTTPS et authentification forte, ou restreignez le binding à l'interface locale : `127.0.0.1:8765:8765` dans le `docker-compose.yml`.
- **`/metrics`** — Ouvert par défaut sur le LAN. Si votre machine est accessible depuis l'extérieur, définissez la variable `METRICS_TOKEN` ou configurez un token API dans Paramètres → API : `/metrics` l'utilisera automatiquement pour exiger un Bearer token.
- **Sidecar** — Chaque container sidecar (speed-test sur le port `8766`, catalogue sur le port `8767`) reçoit automatiquement un secret aléatoire généré par le Companion (`SIDECAR_SECRET`, 32 octets d'entropie via `secrets.token_hex`). Toutes les requêtes HTTP vers le sidecar exigent ce secret dans l'en-tête `X-Sidecar-Token` — un sidecar sans le bon token répond `403`. Ce secret est unique par instance et détruit avec le container à la fin du test. Ces ports ne doivent pas être accessibles depuis l'extérieur : si votre hôte est public, restreignez le binding ou isolez ces ports par firewall.
- **Secrets dans /settings** — Le token API, le mot de passe proxy et les URLs de webhook sont affichés en clair dans l'interface d'administration. Tout accès à l'UI admin équivaut à un accès total à ces secrets.

### Sécurité des images Docker

Les deux images (`gluetun-companion` et `gluetun-companion-sidecar`) embarquent des **binaires Go tiers** (Docker CLI, Docker Compose, librespeed-cli, ookla speedtest) qui ont leur propre chaîne de dépendances, invisible pour les gestionnaires de paquets Python. Un pipeline à deux niveaux maintient ces images à jour :

**Dependabot** (déjà en place, exécuté chaque lundi 06:00 UTC) :
- Met à jour les dépendances **pip** de Companion et du Sidecar (PRs automatiques, patch = auto-merge, mineur = revue manuelle)
- Surveille les images de base **Docker** (`python:3.12-slim`) — mises à jour de sécurité du runtime Python
- Surveille les versions des **GitHub Actions** dans les workflows CI

**Workflow Trivy** (`.github/workflows/trivy-scan.yml`, chaque lundi 07:00 UTC) :
- Builde les deux images et les scanne avec [Trivy](https://github.com/aquasecurity/trivy) pour les CVE de sévérité HIGH et CRITICAL
- Upload les résultats au format SARIF dans l'**onglet Security** du dépôt GitHub (visible sous *Security → Code scanning*)
- Si des CVE avec fix disponible sont détectées et qu'une image Docker CLI plus récente existe : **ouvre automatiquement une PR** qui bumpe le `FROM docker:XX-cli` dans le Dockerfile
- Si aucun changement automatique n'est possible : **ouvre une Issue** listant les CVE à corriger manuellement

**Smoke test** (`.github/workflows/docker-publish.yml`, sur chaque PR) :
- Builde les deux images en amd64
- Démarre chaque container avec une configuration minimale et vérifie qu'il répond en HTTP dans les 20 secondes
- Bloque le merge si une image ne démarre plus — garantit que les mises à jour de sécurité ne cassent pas les fonctionnalités

---

## Crédits

Merci à **[qdm12](https://github.com/qdm12/gluetun)** pour Gluetun, sans lequel ce projet n'existerait pas.

Merci à **[Tecnativa](https://github.com/Tecnativa/docker-socket-proxy)** pour docker-socket-proxy, utilisé pour sécuriser l'accès au socket Docker.

Merci à **[brashenfr](https://github.com/brashenfr)**, **[dje33](https://github.com/the-real-dje33)**, **[lnksilver5](https://github.com/lnksilver5)**, **[Ptite Pomme](https://github.com/ptitzgeg-on-git)**, **[x0gen](https://github.com/x0gen)**, **[zlimteck](https://github.com/zlimteck)** et **[Zup](https://github.com/Gusdezup)** pour les idées et les tests.

---

## Licence

[PolyForm Noncommercial 1.0.0](LICENSE) — usage personnel et associatif libre, usage commercial sur autorisation.
