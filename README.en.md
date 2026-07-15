# Gluetun Companion

🇫🇷 [Version française](README.md)

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

**Related article** — Overview and illustrated walkthrough (with UI screenshots) on the blog: **[Gluetun Companion: web interface to automatically pilot your WireGuard and OpenVPN VPN servers in Gluetun](https://upandclear.org/2026/06/16/gluetun-companion-interface-web-pour-piloter-automatiquement-vos-serveurs-vpn-wireguard-et-openvpn-dans-gluetun/)** (in French).

**Using it? Liking it? [⭐ Drop a star!](https://github.com/Aerya/Gluetun-Companion/stargazers)** — takes two seconds.

Gluetun Companion is a Web UI for controlling an existing [Gluetun](https://github.com/qdm12/gluetun) container: VPN benchmarks, automatic selection, switches, dependent-container management, BitTorrent trackers, port forwarding and metrics.

**Full documentation: [open the English Wiki](https://github.com/Aerya/Gluetun-Companion/wiki/Home)** · [Wiki français](https://github.com/Aerya/Gluetun-Companion/wiki/Accueil)

**Want the shortest path?** Check [compatibility](#compatibility), go directly to the [quick start](#quick-start), then return to [features](#features) and [detailed operation](https://github.com/Aerya/Gluetun-Companion/wiki/How-it-works) as needed. Project maintenance is covered in the Wiki, including [automated workflows](https://github.com/Aerya/Gluetun-Companion/wiki/Automated-workflows) and [security](https://github.com/Aerya/Gluetun-Companion/wiki/Security).

Gluetun Companion is a Web UI for automatically managing WireGuard and OpenVPN servers inside [Gluetun](https://github.com/qdm12/gluetun):

- It benchmarks your VPN servers from inside the tunnel itself, using sidecar mode without restarting your main Gluetun, or Gluetun’s HTTP proxy;
- each server is evaluated using speed, latency, jitter, packet loss, DNS latency, history and real-world stability;
- the best server can be selected automatically according to your usage profile: balanced, gaming, BitTorrent, DDL, download or streaming;
- rotation pools also let you switch servers without a full benchmark, using random, round-robin or best historical download selection;
- VPN profiles support multiple providers, protocols and custom configurations, with encrypted secrets and WireGuard/OpenVPN support;
- the Gluetun catalogue, AirVPN picker, new-server detection and overloaded-server filtering make daily maintenance easier;
- Companion manages Docker containers attached to Gluetun: recreation after switches, pause during benchmarks and optional image updates;
- it can check BitTorrent trackers, handle VPN port forwarding and synchronize ports with qBittorrent or rTorrent;
- history, hourly patterns, Discord/Apprise notifications, REST API, Prometheus metrics and Grafana support turn it into a full homelab VPN control panel.

> **Status: beta.** Gluetun Companion is still in testing. It is developed and battle-tested primarily with **AirVPN**; other providers have barely been tested in real conditions, even though the mechanics (catalogue, benchmark, switching, container management) are strictly identical for all of them. Your feedback is invaluable.

> **Current validation status:**
>
> - **100% functional with AirVPN over WireGuard**;
> - tested over WireGuard with a few other providers;
> - feedback needed for **OpenVPN providers**;
> - **ProtonVPN WireGuard + NAT-PMP port forwarding** supported through VPN profiles; real-world qBittorrent synchronization feedback is still useful;
> - feedback needed for **Custom WireGuard** and **Custom OpenVPN** servers.

**AI-assisted development:** approximately **70% of the code was produced with the assistance of Claude Code and Codex**, under human direction and validation. Particular attention is paid to security: [secret encryption and protection](https://github.com/Aerya/Gluetun-Companion/wiki/Security), [automated workflows, Dependabot and Trivy](https://github.com/Aerya/Gluetun-Companion/wiki/Automated-workflows), restricted Docker socket access through [`docker-socket-proxy`](https://github.com/Tecnativa/docker-socket-proxy), automated tests, and change review. This transparency does not replace real-world feedback, which remains especially important during beta testing.

**Issues and pull requests are welcome**, with proper form: for an [issue](https://github.com/Aerya/Gluetun-Companion/issues), please include the version, VPN provider, relevant logs and reproduction steps; for a PR, a clear description of the problem solved and the expected behaviour.

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
