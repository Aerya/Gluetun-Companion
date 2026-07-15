# Gluetun Companion

> 🇫🇷 [Version française](README.md)

[![Build](https://github.com/Aerya/Gluetun-Companion/actions/workflows/docker-publish.yml/badge.svg?branch=main)](https://github.com/Aerya/Gluetun-Companion/actions/workflows/docker-publish.yml)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white)](https://github.com/Aerya/Gluetun-Companion/pkgs/container/gluetun-companion)

Gluetun Companion is a Web UI for controlling an existing [Gluetun](https://github.com/qdm12/gluetun) container: VPN benchmarks, automatic selection, switches, dependent-container management, BitTorrent trackers, port forwarding and metrics.

> **Full documentation: [open the English Wiki](https://github.com/Aerya/Gluetun-Companion/wiki/Home)** · [Wiki français](https://github.com/Aerya/Gluetun-Companion/wiki/Accueil)

> **Status: beta.** The project is primarily tested with AirVPN. Feedback for other providers, especially OpenVPN, is welcome.

## Features

- sidecar or Gluetun HTTP proxy benchmarks;
- WireGuard and OpenVPN, multi-provider profiles and custom configurations;
- automatic selection and switching based on throughput, stability, history and usage profile;
- rotation pools, failover and intelligent selection for large catalogues;
- tracker discovery and control from qBittorrent or rTorrent;
- provider, native Gluetun or custom port forwarding, with client synchronization;
- management of Docker containers attached to Gluetun;
- Discord/Apprise notifications, REST API, Prometheus and Grafana;
- Unraid/DockerMan support.

## Compatibility

| Item | Support |
|---|---|
| WireGuard | Yes |
| OpenVPN | Yes |
| AirVPN | Primarily tested |
| ProtonVPN | Supported, including NAT-PMP port forwarding |
| Unraid | DockerMan backend supported |

## Quick start

Gluetun must expose its HTTP proxy. Companion also needs Docker socket access — preferably through `docker-socket-proxy` — and read/write access to Gluetun’s Compose directory.

```yaml
services:
  gluetun-companion:
    image: ghcr.io/aerya/gluetun-companion:latest
    container_name: gluetun-companion
    restart: unless-stopped
    ports:
      - "8765:8765"
    volumes:
      - /path/to/data:/data
      - /path/to/gluetun/stack:/compose:rw
    environment:
      - TZ=Europe/Paris
      - SECRET_KEY=replace-with-a-random-string
      - GLUETUN_HOST=host.docker.internal
      - GLUETUN_PROXY_PORT=8887
      - GLUETUN_CONTAINER=gluetun
      - COMPOSE_DIR=/compose
```

```bash
docker compose up -d
```

Then open [http://localhost:8765](http://localhost:8765). For the complete Compose setup, Unraid, profiles, trackers, variables and troubleshooting, see the [English Wiki](https://github.com/Aerya/Gluetun-Companion/wiki/Home).

## Links

- [English Wiki](https://github.com/Aerya/Gluetun-Companion/wiki/Home) · [Wiki français](https://github.com/Aerya/Gluetun-Companion/wiki/Accueil)
- [Issues](https://github.com/Aerya/Gluetun-Companion/issues) · [Releases](https://github.com/Aerya/Gluetun-Companion/releases) · [License](LICENSE)
