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

## Fonctionnalités

- benchmarks en mode sidecar ou via le proxy HTTP Gluetun ;
- WireGuard et OpenVPN, profils multi-fournisseurs et configurations custom ;
- sélection et bascule automatique selon le débit, la stabilité, l’historique et le profil d’usage ;
- pools de rotation, failover et sélection intelligente pour les gros catalogues ;
- découverte et contrôle des trackers BitTorrent depuis qBittorrent ou rTorrent ;
- port forwarding fournisseur, natif Gluetun ou custom, avec synchronisation client ;
- gestion des containers Docker liés à Gluetun ;
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
    environment:
      - TZ=Europe/Paris
      - SECRET_KEY=remplacer-par-une-chaine-aleatoire
      - GLUETUN_HOST=host.docker.internal
      - GLUETUN_PROXY_PORT=8887
      - GLUETUN_CONTAINER=gluetun
      - COMPOSE_DIR=/compose
      - DOCKER_HOST=tcp://socket-proxy:2375
    depends_on:
      - socket-proxy
```

`EVENTS=1` est nécessaire pour détecter immédiatement les redémarrages de Gluetun. Le dossier monté sur `/compose` doit être celui qui contient le fichier Compose de la stack Gluetun ; Companion l'utilise pour recréer les services partageant son réseau après une bascule.

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
