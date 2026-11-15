# Gluetun Companion

[![fr](https://img.shields.io/badge/lang-fr-blue)](README.md)
[![en](https://img.shields.io/badge/lang-en-red)](README.en.md)

[![Build](https://github.com/Aerya/Gluetun-Companion/actions/workflows/docker-publish.yml/badge.svg?branch=main)](https://github.com/Aerya/Gluetun-Companion/actions/workflows/docker-publish.yml)
[![Trivy CVE scan](https://img.shields.io/badge/Trivy-enabled-1904DA?logo=aquasecurity&logoColor=white)](https://github.com/Aerya/Gluetun-Companion/blob/main/.github/workflows/trivy-scan.yml)
[![Dependabot](https://img.shields.io/badge/Dependabot-enabled-025E8C?logo=dependabot&logoColor=white)](https://github.com/Aerya/Gluetun-Companion/blob/main/.github/dependabot.yml)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white)](https://github.com/Aerya/Gluetun-Companion/pkgs/container/gluetun-companion)
[![Architecture](https://img.shields.io/badge/arch-amd64%20%7C%20arm64-lightgrey)](#)
[![Gluetun compatible](https://img.shields.io/badge/Gluetun-compatible-0d1117?logo=github&logoColor=white)](https://github.com/qdm12/gluetun)
[![AirVPN compatible](https://img.shields.io/badge/AirVPN-compatible-1a7a3d)](https://airvpn.org/?referred_by=483746)
[![Proton compatible](https://img.shields.io/badge/Proton-compatible-6d4aff?logo=protonvpn&logoColor=white)](https://protonvpn.com)
[![Unraid DockerMan](https://img.shields.io/badge/Unraid-DockerMan-f15a2b?logo=unraid&logoColor=white)](#)
[![Discord](https://img.shields.io/badge/Discord-webhook-5865F2?logo=discord&logoColor=white)](https://discord.com/developers/docs/resources/webhook)
[![Apprise](https://img.shields.io/badge/Apprise-compatible-3d85c8?logo=python&logoColor=white)](https://github.com/caronc/apprise)
[![Docker socket-proxy](https://img.shields.io/badge/socket--proxy-compatible-blueviolet?logo=docker&logoColor=white)](https://github.com/Tecnativa/docker-socket-proxy)

**Article lié** — Présentation et tour d'horizon illustré (captures d'écran de l'interface) sur le blog : **[Gluetun Companion : interface web pour piloter automatiquement vos serveurs VPN WireGuard et OpenVPN dans Gluetun](https://upandclear.org/2026/06/16/gluetun-companion-interface-web-pour-piloter-automatiquement-vos-serveurs-vpn-wireguard-et-openvpn-dans-gluetun/)**.

**Vous l'utilisez ? Vous l'aimez ? [⭐ Ajouter une étoile !](https://github.com/Aerya/Gluetun-Companion/stargazers)** — ça prend deux secondes.

Gluetun Companion est une interface Web pour piloter un container [Gluetun](https://github.com/qdm12/gluetun) existant : benchmarks VPN, sélection automatique, bascules, gestion des containers dépendants, trackers BitTorrent, port forwarding et métriques.

> [!IMPORTANT]
> ## 📚 Documentation complète
>
> 🇫🇷 **[Ouvrir le Wiki français](https://github.com/Aerya/Gluetun-Companion/wiki)**
> &nbsp;·&nbsp;
> 🇬🇧 **[Open the English Wiki](https://github.com/Aerya/Gluetun-Companion/wiki/English)**

**Vous voulez aller à l’essentiel ?** Consultez la [compatibilité](#compatibilité), passez directement au [démarrage rapide](#démarrage-rapide), puis revenez aux [fonctionnalités](#fonctionnalités) et au [fonctionnement détaillé](https://github.com/Aerya/Gluetun-Companion/wiki/Fonctionnement) selon vos besoins. La maintenance du projet est décrite dans le Wiki, notamment les [workflows automatisés](https://github.com/Aerya/Gluetun-Companion/wiki/Workflows-automatisés) et la [sécurité](https://github.com/Aerya/Gluetun-Companion/wiki/Sécurité).

Gluetun Companion est une interface Web pour piloter automatiquement vos serveurs VPN WireGuard et OpenVPN dans [Gluetun](https://github.com/qdm12/gluetun) :

- Il benchmarke vos serveurs depuis le tunnel VPN lui-même, en mode sidecar sans redémarrer Gluetun, ou via le proxy HTTP intégré ;
- chaque serveur est évalué sur le débit, la latence, le jitter, la perte de paquets, le DNS, l’historique et la stabilité réelle ;
- le meilleur serveur peut être sélectionné automatiquement selon votre usage : équilibré, gaming, BitTorrent, DDL, téléchargement ou streaming ;
- les pools de rotation permettent aussi de changer de serveur sans benchmark, en aléatoire, round-robin ou selon le meilleur débit historique ;
- les profils VPN gèrent plusieurs fournisseurs, protocoles et configurations personnalisées, avec chiffrement des secrets et support WireGuard/OpenVPN ;
- le catalogue Gluetun, l’import AirVPN, la détection de nouveaux serveurs et l’exclusion des serveurs surchargés facilitent la maintenance au quotidien ;
- Companion gère les containers Docker liés à Gluetun : recréation après bascule, pause pendant les tests et mise à jour optionnelle des images ;
- il peut vérifier les trackers BitTorrent, gérer le port forwarding VPN et synchroniser les ports avec qBittorrent ou rTorrent ;
- historique, patterns horaires, notifications Discord/Apprise, API REST, endpoint Prometheus et dashboard Grafana complètent l’outil pour un vrai pilotage homelab.

> **Statut : bêta.** Gluetun Companion est encore en phase de test. Il est développé et éprouvé principalement avec **AirVPN** ; les autres fournisseurs ne sont quasiment pas testés en conditions réelles, même si la mécanique (catalogue, benchmark, bascule, gestion des containers) est strictement identique pour tous. Vos retours sont précieux.

> **État actuel des validations :**
>
> - **100 % fonctionnel avec AirVPN en WireGuard** ;
> - fonctionnement testé en WireGuard avec quelques autres fournisseurs ;
> - retours recherchés concernant les fournisseurs **OpenVPN** ;
> - **ProtonVPN WireGuard + port forwarding NAT-PMP** pris en charge via les profils VPN ; retours encore utiles sur la synchronisation qBittorrent en conditions réelles ;
> - retours recherchés pour les serveurs **Custom WireGuard** et **Custom OpenVPN**.

**Développement assisté par IA :** environ **70 % du code a été réalisé avec l’aide de Claude Code et Codex**, sous direction et validation humaines. Une attention particulière est portée à la sécurité : [chiffrement et protection des secrets](https://github.com/Aerya/Gluetun-Companion/wiki/Sécurité), [workflows automatisés, Dependabot et Trivy](https://github.com/Aerya/Gluetun-Companion/wiki/Workflows-automatisés), limitation de l’accès au socket Docker via [`docker-socket-proxy`](https://github.com/Tecnativa/docker-socket-proxy), tests automatisés et revue des modifications. Cette transparence ne remplace pas les retours en conditions réelles, particulièrement importants pendant la bêta.

**Issues et pull requests bienvenues**, en respectant les formes : pour une [issue](https://github.com/Aerya/Gluetun-Companion/issues), merci d'indiquer la version, le fournisseur VPN, les logs pertinents et les étapes de reproduction ; pour une PR, une description claire du problème résolu et du comportement attendu.

### Nettoyage des conteneurs temporaires

Le nettoyage vérifie un label posé à la création des conteneurs temporaires. Une collision de nom ne supprime plus Companion ni un conteneur tiers, même avec un hostname personnalisé ou absent. Le label est interne : ne l’ajoutez pas aux services permanents. Après une mise à jour, un ancien conteneur temporaire sans label est conservé : si son nom bloque un benchmark ou le catalogue, vérifiez son rôle avant de le supprimer manuellement. Si le nom appartient à un service permanent, renommez ce service pour libérer le nom réservé.

### Sécurité TLS — octobre 2026

Mise à jour des certificats et des composants TLS des images après l’incident eMudhra. Les contrôles couvrent les chaînes compromises, dont les deux cas « No CT », et une connexion HTTPS valide. Une image déjà en cours d’exécution reste inchangée : son remplacement doit être planifié après validation.

[Détails de l’incident](https://emudhra.we-have-a-problem.com/) · [TLS checks](security/emudhra/README.md)

## Fonctionnalités

- benchmarks en mode sidecar ou via le proxy HTTP Gluetun ;
- WireGuard et OpenVPN, profils multi-fournisseurs et configurations custom ;
- sélection et bascule automatique selon le débit, la stabilité, l’historique et le profil d’usage ;
- pools de rotation, failover et sélection intelligente pour les gros catalogues ;
- découverte et contrôle des trackers BitTorrent depuis qBittorrent ou rTorrent ;
- port forwarding fournisseur, natif Gluetun ou custom, avec synchronisation client ;
- gestion et recréation des containers Docker liés à Gluetun, y compris dans d’autres stacks Compose ;
- trafic réel du tunnel VPN en direct (débits, volumes, historique horaire, journalier et mensuel) ;
- notifications Discord/Apprise, API REST, Prometheus et Grafana ;
- support Unraid/DockerMan.

## Compatibilité

| Élément | Support |
|---|---|
| WireGuard | Oui |
| OpenVPN | Oui |
| AirVPN | Principalement testé |
| ProtonVPN | Supporté, port forwarding NAT-PMP inclus |
| Unraid | Backend DockerMan supporté |

## Démarrage rapide

Gluetun doit exposer son proxy HTTP, et Companion doit pouvoir accéder au socket Docker — de préférence via `docker-socket-proxy` — ainsi qu’au dossier Compose de Gluetun.

```yaml
services:
  socket-proxy:
    image: tecnativa/docker-socket-proxy
    restart: unless-stopped
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    environment:
      CONTAINERS: 1
      EVENTS: 1
      POST: 1

  gluetun-companion:
    image: ghcr.io/aerya/gluetun-companion:latest
    container_name: gluetun-companion
    restart: unless-stopped
    ports:
      - "8765:8765"
    volumes:
      - /chemin/vers/data:/data
      - /chemin/vers/stack/gluetun:/compose:rw
      - /chemin/vers/stacks:/stacks:ro
    environment:
      - TZ=Europe/Paris
      - SECRET_KEY=remplacer-par-une-chaine-aleatoire
      - GLUETUN_HOST=host.docker.internal
      # Optionnel : définissez cette adresse sur host.docker.internal si GLUETUN_HOST est un nom de service Docker.
      # - SIDECAR_HOST=host.docker.internal
      - GLUETUN_PROXY_PORT=8887
      - GLUETUN_CONTAINER=gluetun
      - COMPOSE_DIR=/compose
      - COMPOSE_STACKS_DIR=/stacks
      - DOCKER_HOST=tcp://socket-proxy:2375
    depends_on:
      - socket-proxy
```

`EVENTS=1` est nécessaire pour détecter immédiatement les redémarrages de Gluetun. Le dossier monté sur `/compose` doit contenir le fichier Compose de la stack Gluetun. Pour recréer aussi les services d’autres projets Compose partageant son réseau, montez la racine de leurs stacks sur `/stacks` et définissez `COMPOSE_STACKS_DIR=/stacks`. Le sous-dossier doit porter le nom du projet Compose (`/stacks/plex` pour le projet `plex`). Companion attend également la fin effective d’une suppression Docker avant de retenter une recréation interrompue.

**`EXEC` (optionnel).** Avec `EXEC: 1`, Companion lit deux fichiers dans Gluetun par `docker exec` : son catalogue de serveurs, pour nommer exactement le serveur actif, et `/gluetun/wireguard/wg0.conf`, pour savoir si une bascule gérée est possible. Sans `EXEC`, tout fonctionne aussi : le serveur actif est déduit des filtres ou du dernier serveur observé et signalé « non vérifié », et la présence de `wg0.conf` est indiquée comme non vérifiée. Companion détecte le refus sans créer d’exec, n’en crée donc aucun tant qu’il dure, et revérifie toutes les 5 minutes : ajouter `EXEC: 1` plus tard suffit, sans redémarrer Companion. `EXEC: 1` permet en revanche à tous les clients de ce proxy de lancer des commandes dans n’importe quel conteneur ; c’est acceptable si Companion en est le seul client.

Lorsque `GLUETUN_HOST` est un nom de service Docker, il convient aux requêtes proxy de Companion, mais pas aux sidecars temporaires de benchmark dont le port HTTP est publié sur l’hôte Docker. Définissez `SIDECAR_HOST=host.docker.internal` (en conservant le mapping `host-gateway`) pour interroger ces sidecars. S’il est absent, il reprend `GLUETUN_HOST` afin de conserver la compatibilité.

Le **port API sidecar** des paramètres est le port publié sur l’hôte Docker. Le sidecar écoute toujours sur son port interne `8766` : Companion publie automatiquement `8766/tcp` vers le port configuré, par exemple `8767`. Aucune modification du port interne ni de `catalogue_sidecar_port` n’est nécessaire. Lors d’un benchmark, `8766` est ajouté automatiquement à `FIREWALL_INPUT_PORTS` du clone temporaire, sans modifier le pare-feu du Gluetun de production.

Dans **Paramètres → Planification & Cycle**, vous pouvez soit conserver un intervalle, soit lancer le benchmark à une heure précise tous les X jours. Cette planification calendaire conserve son rythme après le redémarrage de Companion. Avec elle, un redémarrage de Gluetun (mise à jour automatique de l’image, healthcheck…) déclenche seulement un test rapide, sans benchmark complet : les cycles complets ne tournent qu’à l’heure prévue. En mode intervalle, une dérive détectée après un redémarrage lance toujours un benchmark complet, sauf si le cycle automatique est désactivé. L’**Historique** indique l’origine de chaque benchmark (planifié, manuel, API, import ou redémarrage de Gluetun) et permet de filtrer dessus ; les tests enregistrés avant cette version restent classés « Manuel ».

### Control Server Gluetun : accès et authentification

Companion lit l’état du VPN et le port forwardé avec le [Control Server officiel de Gluetun](https://github.com/qdm12/gluetun-wiki/blob/main/setup/advanced/control-server.md). Les routes sont privées par défaut dans les versions récentes de Gluetun : publier le port ne suffit donc pas, il faut aussi choisir une authentification.

La méthode recommandée avec Companion est une clé API :

1. Générez une clé avec `docker run --rm qmcgaw/gluetun genkey`.
2. Ajoutez le port et le rôle au service Gluetun. Le port hôte peut être différent si `8000` est déjà utilisé :

```yaml
services:
  gluetun:
    ports:
      - "8043:8000/tcp"
    environment:
      - HTTP_CONTROL_SERVER_AUTH_DEFAULT_ROLE={"auth":"apikey","apikey":"VOTRE_CLE_API"}
```

3. Dans **Companion → Paramètres → Ports forwardés VPN**, indiquez l’URL accessible depuis le container Companion, par exemple `http://host.docker.internal:8043`, puis saisissez la même clé dans **X-API-Key**.
4. Recréez Gluetun après la modification et vérifiez que Companion affiche son état sans erreur `401` ou `403`.

Dans `8043:8000`, `8000` est le port interne de Gluetun et `8043` le port publié sur l’hôte. Si votre configuration exige d’ajouter le Control Server à `FIREWALL_INPUT_PORTS`, utilisez donc `8000`, jamais `8043`. Vous pouvez laisser le champ URL vide lorsque l’autodétection Docker fonctionne ; avec un port remappé, Portainer ou Synology, renseignez l’URL explicitement. Elle doit être joignable **depuis le container Companion**, pas seulement depuis l’hôte ou votre navigateur.

Diagnostic rapide :

```bash
# Depuis l’hôte Docker — remplacez 8043 par le port hôte choisi
curl -i http://127.0.0.1:8043/v1/portforward

# Depuis le container Gluetun — le port interne reste toujours 8000
docker exec gluetun wget -S -O- http://127.0.0.1:8000/v1/portforward
```

La réponse attendue est `HTTP/1.1 200 OK` avec un contenu tel que `{"port":47987,"ports":[47987]}`. Un `401` ou `403` indique que la clé API n’est pas configurée de la même façon dans Gluetun et Companion.

Sur un LAN réellement maîtrisé uniquement, la forme Compose suivante désactive l’authentification :

```yaml
environment:
  - HTTP_CONTROL_SERVER_AUTH_DEFAULT_ROLE={"auth":"none"}
```

La documentation Gluetun déconseille fortement cette option. N’exposez jamais le Control Server directement sur Internet ; si un accès distant est indispensable, protégez-le avec TLS et un reverse proxy.

Avec ProtonVPN, activez `VPN_PORT_FORWARDING=on` et utilisez une règle **Natif Gluetun** sans port fixe. Gluetun obtient le port dynamique ; Companion le lit puis synchronise qBittorrent. N’ajoutez pas ce port dynamique à `FIREWALL_VPN_INPUT_PORTS`, `FIREWALL_INPUT_PORTS` ou aux mappings Docker.

### WireGuard : configuration pilotée par Companion

Pour permettre à Companion de benchmarker les serveurs puis de sélectionner et basculer automatiquement vers le meilleur d'un fournisseur pris en charge nativement (notamment ProtonVPN), ne montez pas de fichier `wg0.conf` dans `/gluetun/wireguard/wg0.conf`. Gluetun donne priorité à ce fichier et à son endpoint WireGuard, ce qui est incompatible avec les variables `SERVER_*` écrites par Companion. Configurez plutôt le fournisseur et les identifiants WireGuard via un profil VPN dans Companion.

La **clé privée WireGuard** du profil principal est obligatoire pour les bascules de Gluetun. La **clé privée Sidecar** est une seconde identité réservée aux containers de benchmark : elle ne remplace jamais la clé principale.

Un `wg0.conf` reste adapté à une configuration WireGuard custom et figée. Dans ce mode, Companion ne peut ni benchmarker les serveurs en basculant le Gluetun principal, ni appliquer automatiquement le meilleur résultat. Des benchmarks isolés par sidecar restent possibles avec un profil VPN compatible, mais Companion refuse toute bascule gérée afin de ne pas appliquer un override qui arrêterait Gluetun.

```bash
docker compose up -d
```

Ouvrir ensuite [http://localhost:8765](http://localhost:8765). Pour le Compose complet, Unraid, les profils, les trackers, les variables et le dépannage, consulter le [Wiki français](https://github.com/Aerya/Gluetun-Companion/wiki/Accueil).

Lors de la création du premier compte, Companion ouvre automatiquement un **guide de démarrage en trois étapes** : préparer les branchements Compose, choisir entre reprendre la configuration Gluetun actuelle ou importer des serveurs depuis un catalogue, puis lancer un premier benchmark. Le bouton **?** de la barre de navigation permet de rouvrir ce guide à tout moment.

## Applications tierces

- [AirDash](https://github.com/zlimteck/AirDash) — tableau de bord AirVPN natif et non officiel pour iPhone et iPad.

### Changement manuel prioritaire

Depuis **Serveurs**, une demande de changement est enregistrée immédiatement, même pendant un benchmark planifié ou une observation continue. Companion demande l’arrêt du test, attend son nettoyage, puis change le serveur et reconnecte les applications sous le même verrou. Le suivi sur la page indique l’attente, la bascule, la reconnexion ou l’échec ; un second clic ne remplace pas la demande en cours.

Les tâches automatiques déjà en attente cèdent la priorité. Si le verrou reste occupé pendant dix minutes, la demande échoue explicitement sans forcer son déverrouillage. Après un redémarrage de Companion, une demande interrompue est signalée et n’est pas rejouée automatiquement : vérifiez le serveur actif avant de réessayer. Le fonctionnement automatique reprend ensuite selon les réglages existants.

### Trafic VPN réel

Le bloc **Trafic VPN en direct** du tableau de bord et la page **Trafic** affichent ce qui passe réellement dans le tunnel du Gluetun principal : débits descendant et montant, volumes reçus et envoyés (dernière heure, jour, mois, cumul), serveur, fournisseur, protocole et interface. L’historique couvre le temps réel, 1 h, 24 h, 7 j, 30 j et les mois. Ces mesures sont distinctes des benchmarks.

**Méthode.** Companion lit `/proc/net/dev` dans Gluetun via `docker exec cat` (lecture seule, sans shell ni privilège). L’interface est `VPN_INTERFACE` si elle est définie, sinon `tun0`, puis `wg0`. Les conteneurs en `network_mode: service:gluetun` partagent ce tunnel : leur trafic est compté une fois, au total, sans répartition par conteneur. Seul le contenu des compteurs réseau est lu, jamais celui des communications.

**Fiabilité.** Une reconnexion, un changement de serveur ou un redémarrage de Gluetun remet les compteurs de l’interface à zéro : Companion le détecte, sans pic ni débit négatif. Les volumes sont persistés et survivent aux redémarrages de Companion. Aucun historique n’est inventé avant l’activation. Après une interruption de la collecte, le volume manquant est réparti uniformément sur la période, sans débit instantané. Les sondes de Companion qui passent par le proxy HTTP de Gluetun sont elles aussi comptées.

**État du tunnel.** La présence de `tun0`/`wg0` ne prouve pas que le VPN fonctionne. « Tunnel connecté » n’est donc affiché que si le healthcheck Docker de Gluetun, qui teste une connexion à travers le tunnel, est `healthy`. Sinon : « Interface présente, VPN en échec » (`unhealthy`) ou « Interface présente » (healthcheck absent ou en cours). Les compteurs restent mesurés dans tous les cas. Prometheus distingue `gluetun_companion_vpn_tunnel_up` (interface présente) de `gluetun_companion_vpn_tunnel_healthy` (healthcheck).

**Autorisations Docker.** La lecture passe par `docker exec`. Avec le socket monté directement (Unraid, Synology), rien n’est à configurer. Avec `docker-socket-proxy`, l’exec est refusé par défaut et la page affiche « Mesure indisponible » sans valeur trompeuse. Deux options :

- **Proxy dédié** (`wollomatic/socket-proxy`), déclaré avec `TRAFFIC_DOCKER_HOST=tcp://traffic-proxy:2375` dans Companion. Il n’accepte que Companion (`-allowfrom`) et n’autorise que l’inspection de Gluetun, l’exec dans Gluetun (ciblé par son nom) et le démarrage d’un exec. Le proxy principal garde `EXEC=0`. Remplacez `gluetun` par la valeur de `GLUETUN_CONTAINER` :

```yaml
  traffic-proxy:
    image: wollomatic/socket-proxy:1
    restart: unless-stopped
    # L'image tourne en 65534 : ajoutez le GID du groupe docker de l'hôte
    # (getent group docker | cut -d: -f3), sinon le socket est illisible.
    user: "65534:998"
    read_only: true
    cap_drop: [ALL]
    security_opt: [no-new-privileges:true]
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    command:
      - '-listenip=0.0.0.0'
      - '-allowfrom=gluetun-companion'
      - '-allowGET=((/v1\..{1,2})?/version|/v1\..{1,2}/containers/gluetun/json)'
      - '-allowPOST=/v1\..{1,2}/(containers/gluetun/exec|exec/[0-9a-f]{64}/start)'
```

- **`EXEC: 1` sur le proxy principal** : plus simple, mais tous les clients de ce proxy peuvent alors démarrer des commandes dans n’importe quel conteneur.

**Ce que le proxy dédié protège, et ce qu’il ne protège pas.** Testé avec Companion, il refuse l’exec dans les autres conteneurs (y compris via `..`, `%2F`, `//` ou un identifiant), la création, l’arrêt et la liste des conteneurs, ainsi que toute requête d’un autre conteneur. En revanche :
- toute commande peut être lancée dans Gluetun, pas seulement `cat` ;
- un exec créé ailleurs peut être démarré si son identifiant est connu. Or `docker-socket-proxy` avec `CONTAINERS=1` et `POST=1` autorise la *création* d’un exec dans n’importe quel conteneur : en combinant les deux proxys, Companion peut donc exécuter une commande ailleurs que dans Gluetun.

Le proxy dédié n’ajoute donc aucune autorisation pour les *autres* clients du proxy principal, mais ne confine pas Companion lui-même. Ce n’est pas un recul : `CONTAINERS=1` et `POST=1`, déjà requis par les benchmarks et la recréation des conteneurs, permettent de créer un conteneur avec n’importe quelle configuration, ce qui équivaut déjà à un accès root sur l’hôte.

**Réglages** (**Paramètres → Trafic VPN**) : activation, fréquence de collecte (3 à 60 s, 5 s par défaut), conservation du détail horaire (90 j par défaut) et journalier (730 j par défaut ; 0 = illimité), unités, et réinitialisation confirmée des statistiques, sans effet sur le VPN. Les totaux mensuels sont toujours conservés.

**Prometheus.** `/metrics` expose `gluetun_companion_vpn_traffic_received_bytes_total` et `gluetun_companion_vpn_traffic_sent_bytes_total` (compteurs), les débits courants `..._receive_bytes_per_second` et `..._transmit_bytes_per_second`, `gluetun_companion_vpn_tunnel_up`, `gluetun_companion_vpn_tunnel_healthy` et `gluetun_companion_vpn_traffic_monitoring_available{status}`. Le dashboard Grafana fourni comprend une section « Trafic VPN réel ». L’API REST propose `GET /api/v1/traffic` (et `?range=24h`, `7d`, `30d`, `months`…).
