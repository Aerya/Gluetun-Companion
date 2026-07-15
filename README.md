# Gluetun Companion

> 🇬🇧 [English version](README.en.md)

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

> **Article lié** — Présentation et tour d'horizon illustré (captures d'écran de l'interface) sur le blog : **[Gluetun Companion : interface web pour piloter automatiquement vos serveurs VPN WireGuard et OpenVPN dans Gluetun](https://upandclear.org/2026/06/16/gluetun-companion-interface-web-pour-piloter-automatiquement-vos-serveurs-vpn-wireguard-et-openvpn-dans-gluetun/)**.

> **Vous l'utilisez ? Vous l'aimez ? [⭐ Ajouter une étoile !](https://github.com/Aerya/Gluetun-Companion/stargazers)** — ça prend deux secondes.

Gluetun Companion est une interface Web pour piloter un container [Gluetun](https://github.com/qdm12/gluetun) existant : benchmarks VPN, sélection automatique, bascules, gestion des containers dépendants, trackers BitTorrent, port forwarding et métriques.

> **Documentation complète : [ouvrir le Wiki français](https://github.com/Aerya/Gluetun-Companion/wiki/Accueil)** · [Wiki English](https://github.com/Aerya/Gluetun-Companion/wiki/Home)

> **Vous voulez aller à l’essentiel ?** Consultez la [compatibilité](#compatibilité), passez directement au [démarrage rapide](#démarrage-rapide), puis revenez aux [fonctionnalités](#fonctionnalités) et au [fonctionnement détaillé](https://github.com/Aerya/Gluetun-Companion/wiki/Fonctionnement) selon vos besoins. La maintenance du projet est décrite dans le Wiki, notamment les [workflows automatisés](https://github.com/Aerya/Gluetun-Companion/wiki/Workflows-automatisés) et la [sécurité](https://github.com/Aerya/Gluetun-Companion/wiki/Sécurité).

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
```

```bash
docker compose up -d
```

Ouvrir ensuite [http://localhost:8765](http://localhost:8765). Pour le Compose complet, Unraid, les profils, les trackers, les variables et le dépannage, consulter le [Wiki français](https://github.com/Aerya/Gluetun-Companion/wiki/Accueil).

## Liens

- [Wiki français](https://github.com/Aerya/Gluetun-Companion/wiki/Accueil) · [Wiki anglais](https://github.com/Aerya/Gluetun-Companion/wiki/Home)
- [Issues](https://github.com/Aerya/Gluetun-Companion/issues) · [Releases](https://github.com/Aerya/Gluetun-Companion/releases) · [Licence](LICENSE)
