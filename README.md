# Gluetun Companion

> 🇬🇧 [English version](README.en.md)

[![Build](https://github.com/Aerya/Gluetun-Companion/actions/workflows/docker-publish.yml/badge.svg?branch=main)](https://github.com/Aerya/Gluetun-Companion/actions/workflows/docker-publish.yml)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white)](https://github.com/Aerya/Gluetun-Companion/pkgs/container/gluetun-companion)

Gluetun Companion est une interface Web pour piloter un container [Gluetun](https://github.com/qdm12/gluetun) existant : benchmarks VPN, sélection automatique, bascules, gestion des containers dépendants, trackers BitTorrent, port forwarding et métriques.

> **Documentation complète : [ouvrir le Wiki français](https://github.com/Aerya/Gluetun-Companion/wiki/Accueil)** · [Wiki English](https://github.com/Aerya/Gluetun-Companion/wiki/Home)

> **Statut : bêta.** Le projet est principalement éprouvé avec AirVPN. Les retours sur les autres fournisseurs, notamment OpenVPN, sont bienvenus.

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
