<p align="center">
  <img src="assets/logo.png" alt="Gluetun Companion" width="200">
</p>

# Gluetun Companion

Benchmark automatique de vos serveurs VPN [Gluetun](https://github.com/qdm12/gluetun), bascule vers le plus rapide, Web UI complète.

> 🇬🇧 [English version](README.en.md)

<p align="center">
<a href="https://github.com/Aerya/Gluetun-Companion/actions/workflows/docker-publish.yml"><img src="https://github.com/Aerya/Gluetun-Companion/actions/workflows/docker-publish.yml/badge.svg?branch=main" alt="Build"></a>
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

## Fonctionnalités

**Mesure de performances**
- **Mode Sidecar** (défaut) — un container `gluetun-companion-test` clone la config réelle de Gluetun pour chaque serveur ; `gluetun-companion-sidecar` mesure le débit via **Ookla + librespeed en parallèle** (mode dual, défaut), Ookla seul, librespeed seul ou iperf3 directement dans le tunnel VPN ; votre Gluetun principal n'est jamais relancé pendant les tests
- **Mode Proxy HTTP** (optionnel) — mesure via le proxy HTTP Gluetun sans container supplémentaire ; interrompt brièvement les services dépendants à chaque bascule
- **Résultats multi-sources** — les vitesses Ookla, librespeed et iperf3 sont stockées séparément et affichées dans le dashboard et l'historique
- **Téléchargement multi-flux** — N connexions TCP simultanées (configurable, défaut : 4)
- **Benchmark automatique** toutes les X heures — download, upload et latence par serveur ; cycle automatique désactivable (déclenchement manuel uniquement)
- **Vérification rapide avant benchmark** *(option)* — teste uniquement le serveur actif avant chaque cycle ; si le débit est dans la plage ±N% par rapport au dernier résultat connu, le benchmark complet est ignoré — aucun container stoppé, aucun redémarrage VPN ; déclenche le benchmark complet uniquement si les performances dérivent significativement
- **Benchmark rapide à la demande** — bouton disponible en permanence (dashboard et paramètres) ; teste uniquement le serveur actif via le proxy HTTP de Gluetun, résultat en quelques secondes, aucune interruption VPN, résultat sauvegardé dans l'historique
- **Jitter & Packet Loss** — stabilité réseau mesurée à chaque test (21 sondes TTFB en mode proxy, ICMP via sidecar) ; indicateur 🟢/🟡/🔴 sur la page Serveurs, colonnes dédiées dans l'historique, jitter affiché dans les patterns horaires ; intégré dans le score de sélection (pénalité jusqu'à −15 % jitter / −25 % perte)
- **Latence DNS** *(sidecar)* — mesure du temps de résolution DNS depuis l'intérieur du tunnel VPN via `dig` (4 domaines en parallèle, médiane retournée) ; détecte les résolveurs lents, surchargés ou qui interceptent les requêtes ; colonne dans l'historique, tooltip sur l'indicateur Stabilité, données dans les patterns horaires
- **Écoute Docker events** — thread daemon qui surveille les événements `start` du container Gluetun ; si Gluetun redémarre de lui-même (crash, mise à jour, watchdog), déclenche automatiquement un quick check après N secondes (délai de reconnexion VPN) ; si la dérive de débit dépasse le seuil configuré et que la bascule automatique est activée, lance immédiatement un benchmark complet ; les redémarrages déclenchés par Companion lui-même sont ignorés ; cooldown de 5 min entre deux déclenchements

**Sélection & bascule automatique**
- **Bascule automatique** vers le meilleur serveur (`docker compose up -d`), basée sur un score pondéré intégrant débit actuel, historique exponentiel, jitter, perte paquets et reconnexions involontaires (via Docker events) ; curseur *Priorité débit vs stabilité* configurable ; les services dépendants (`network_mode: service:gluetun`) sont recréés automatiquement
- **Bascule manuelle** vers n'importe quel serveur configuré depuis la page Serveurs — Gluetun est reconfiguré et les containers `network_mode: service:gluetun` sont recréés automatiquement
- **5 types de filtre** : `SERVER_NAMES`, `SERVER_COUNTRIES`, `SERVER_REGIONS`, `SERVER_CITIES`, `SERVER_HOSTNAMES`
- **Retry** configurable par serveur + timeout global par serveur
- **Auto-désactivation** d'un serveur après N échecs consécutifs

**Gestion des containers Docker**
- **Containers réseau Gluetun (auto-gérés)** — tous les containers en `network_mode: service:gluetun` sont détectés et relancés automatiquement après chaque bascule
- **Containers à redémarrer après bascule** — uniquement pour les containers utilisant le proxy HTTP/SOCKS5 de Gluetun ; liste ordonnée (glisser-déposer)
- **Pause pendant le benchmark** — liste de containers (torrents, Usenet…) stoppés avant le début du benchmark et relancés automatiquement à la fin, même en cas d'erreur
- **Mise à jour automatique des images Docker** *(option)* — au moment de la bascule, Companion peut mettre à jour les images avant de relancer les containers : Gluetun lui-même, les containers réseau auto-gérés, les containers à redémarrer après bascule et les containers en pause pendant le benchmark ; activable individuellement par container depuis les Paramètres

**AirVPN**
- **Sélecteur de serveurs AirVPN intégré** — bouton *+ Ajouter un serveur AirVPN* sur la page Serveurs : données en direct depuis `airvpn.org/api/status/` (cache 5 min), deux vues — liste complète searchable (charge, utilisateurs, santé) et répartition géographique par pays avec badge **Best** sur le serveur le moins chargé ; ajout multi-sélection en un clic
- **Détection de nouveaux serveurs AirVPN** *(optionnel)* — compare l'API AirVPN avec vos serveurs configurés toutes les 24 h ; bannière et badge sur la page Serveurs + onglet *Nouveaux* dans le modal d'ajout ; notification Discord/Apprise avec mention optionnelle

**Analyse & historique**
- **Score de confiance par serveur** — indicateur 🟢/🟡/🔴 sur la page Serveurs et dans l'historique ; basé sur le nombre de mesures et la variabilité des résultats ; intégré dans le score de sélection automatique (pondération légère)
- **Patterns horaires** (`/history/patterns`) — graphique barres 0h–23h du débit moyen par tranche horaire, coloré selon les performances relatives ; meilleure et pire heure affichées ; permet de repérer les créneaux de saturation serveur
- **Test unitaire** d'un serveur depuis l'UI sans attendre le prochain cycle
- **Export CSV** de l'historique complet

**Interface & notifications**
- **Web UI** dark/light, FR/EN — auth, dashboard avec sparkline, historique paginé, graphiques, page bascules avec gain Mbps et temps de connexion
- **Notifications** à chaque bascule — webhook Discord (embed coloré) et/ou [Apprise](https://github.com/caronc/apprise/wiki) (Telegram, ntfy, Gotify, Slack, Pushover…)
- **Purge automatique** de l'historique SQLite configurable (rétention en jours)

**Intégration & infrastructure**
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
      - GLUETUN_CONTAINER=gluetun-airvpn   # nom exact du container Gluetun
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
> Le socket Docker donne un accès quasi-total à l'hôte. Le proxy [Tecnativa](https://github.com/Tecnativa/docker-socket-proxy) s'intercale entre Companion et le socket, et n'expose que les opérations strictement nécessaires — Companion ne peut pas lancer de container privilégié, monter des chemins arbitraires, etc. Fonctionnement identique pour l'utilisateur, surface d'attaque réduite.

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

Sur **Serveurs → + Ajouter un serveur AirVPN** : un modal charge les données en direct depuis l'[API AirVPN](https://airvpn.org/?referred_by=483746) (cache 5 min côté serveur). Deux onglets :
- **Serveurs** — liste complète avec barre de charge colorée (vert/orange/rouge), nombre d'utilisateurs, statut de santé, recherche en temps réel
- **Par pays** — sections collapsibles par pays avec flag emoji, badge 🏆 **Best** sur le serveur le moins chargé, bouton "Sélectionner tous" par pays

Les serveurs déjà dans la base sont grisés et leur case à cocher est désactivée. Sélection multiple, ajout en un clic.

### Vérification rapide avant benchmark *(option)*

Activer via **Paramètres → Planification & Benchmark → Vérification rapide avant benchmark**.

Lorsque cette option est activée, chaque cycle commence par un test de débit sur le **serveur actuellement actif uniquement** — avant de stopper des containers ou de relancer Gluetun :

- **Dans la plage (défaut ±15 %)** : le benchmark complet est ignoré. Aucun container n'est stoppé, Gluetun n'est pas relancé, aucune interruption VPN. Le cycle se termine en quelques secondes.
- **Hors plage** : le benchmark complet se lance normalement — tous les serveurs sont testés, le meilleur est sélectionné.

> **Implémentation** : la vérification rapide passe **exclusivement par le proxy HTTP** de Gluetun — aucun container sidecar créé, aucune attente de reconnexion VPN. Résultat obtenu en 10–15 secondes.

Idéal pour des intervalles fréquents (ex. toutes les 2–3 h) où l'on veut un contrôle rapide sans le coût d'un benchmark complet à chaque fois.

> La tolérance est configurable (1–100 %). Une valeur de 15 signifie : si le débit actuel est compris entre 85 % et 115 % du dernier résultat connu, le benchmark complet est ignoré.

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
| **Confiance** (variance historique) | Coefficient de variation sur les 5 derniers tests | −15 % (LOW) · −5 % (MEDIUM) |

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
- **Onglet Nouveaux** dans le modal d'ajout : liste de tous les serveurs AirVPN pas encore dans votre liste (badge ⭐ *Nouveau* sur ceux qui ont été détectés automatiquement) ; filtre de recherche unifié

**Notification Discord/Apprise :**
Envoyée uniquement lors de la découverte de nouveaux serveurs, regroupée par pays. Champ *Mention Discord* optionnel (ex. `<@123456789>`) pour notifier un utilisateur ou un rôle.

> Après 7 jours, les serveurs quittent automatiquement la liste des "nouveaux". Les serveurs ajoutés à votre liste ne s'affichent plus dans le badge/bannière.

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

**Authentification** : par défaut ouvert (standard pour un réseau interne). Définir `METRICS_TOKEN` pour exiger un Bearer token.

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

## Notes

- **Mode sidecar (défaut) :** votre Gluetun principal n'est jamais relancé pendant les tests — les services dépendants ne sont pas interrompus. **Mode proxy (optionnel) :** le benchmark interrompt brièvement ces services à chaque test de serveur. Planifiez pendant les heures creuses.
- **Fréquence et nombre de serveurs :** chaque test génère une reconnexion VPN. Tester 10 serveurs toutes les 2 heures = 120 reconnexions/jour. La plupart des fournisseurs limitent les connexions *simultanées*, pas la fréquence — mais un intervalle trop court peut déclencher une détection d'abus. **6 h et moins de 10 serveurs** est un réglage raisonnable.
- Le fichier `docker-compose.override.yml` est géré automatiquement — ne le modifiez pas manuellement.
- L'IPv6 est affiché si votre fournisseur VPN le supporte (AirVPN le supporte).
- Le socket Docker (`/var/run/docker.sock`) est requis pour le mode sidecar, les containers post-bascule et la pause pendant le benchmark.

---

## Sécurité

- **CSRF** — Toutes les actions POST (formulaires et AJAX) sont protégées par un token CSRF via session serveur. L'en-tête `X-CSRF-Token` est injecté automatiquement sur chaque `fetch` non-GET grâce à un intercepteur JavaScript.
- **XSS** — Les données issues d'API tierces (AirVPN) injectées dans le DOM via `innerHTML` sont systématiquement échappées par une fonction `_esc()` (HTML entity encoding). Les handlers d'événements sur éléments dynamiques utilisent `addEventListener` plutôt que des attributs `onchange` inline.
- **SECRET_KEY** — L'application refuse de démarrer si `SECRET_KEY` est absente ou égale à la valeur par défaut. Génère une clé sécurisée avec : `openssl rand -hex 32`.
- **Injection YAML** — La valeur du filtre de serveur est assainie avant écriture dans `docker-compose.override.yml` (retours à la ligne supprimés, guillemets et backslashs échappés).
- **Socket Docker** — Le socket Docker est sécurisé via [docker-socket-proxy](https://github.com/Tecnativa/docker-socket-proxy), qui limite l'accès au strict nécessaire (lecture des containers, pas d'accès root au daemon).

---

## Crédits

Merci à **[qdm12](https://github.com/qdm12/gluetun)** pour Gluetun, sans lequel ce projet n'existerait pas.

Merci à **[Tecnativa](https://github.com/Tecnativa/docker-socket-proxy)** pour docker-socket-proxy, utilisé pour sécuriser l'accès au socket Docker.

Merci à **Zup** pour les idées et les tests.

---

## Licence

[PolyForm Noncommercial 1.0.0](LICENSE) — usage personnel et associatif libre, usage commercial sur autorisation.
