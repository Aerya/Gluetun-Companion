<p align="center">
  <img src="assets/logo.png" alt="Gluetun Companion" width="200">
</p>


> 🇫🇷 [Version française](README.md)



# Gluetun Companion

> **Related article** — Overview and illustrated walkthrough (with UI screenshots) on the blog: **[Gluetun Companion: web interface to automatically pilot your WireGuard and OpenVPN VPN servers in Gluetun](https://upandclear.org/2026/06/16/gluetun-companion-interface-web-pour-piloter-automatiquement-vos-serveurs-vpn-wireguard-et-openvpn-dans-gluetun/)** (in French).

<p align="center">
<a href="https://github.com/Aerya/Gluetun-Companion/actions/workflows/docker-publish.yml"><img src="https://github.com/Aerya/Gluetun-Companion/actions/workflows/docker-publish.yml/badge.svg?branch=main" alt="Build"></a>
<a href="https://github.com/Aerya/Gluetun-Companion/blob/main/.github/workflows/trivy-scan.yml"><img src="https://img.shields.io/badge/Trivy-enabled-1904DA?logo=aquasecurity&logoColor=white" alt="Trivy CVE scan"></a>
<a href="https://github.com/Aerya/Gluetun-Companion/blob/main/.github/dependabot.yml"><img src="https://img.shields.io/badge/Dependabot-enabled-025E8C?logo=dependabot&logoColor=white" alt="Dependabot"></a>
<a href="https://github.com/Aerya/Gluetun-Companion/pkgs/container/gluetun-companion"><img src="https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white" alt="Docker"></a>
<a href="#"><img src="https://img.shields.io/badge/arch-amd64%20%7C%20arm64-lightgrey" alt="arch"></a>
<a href="README.md"><img src="https://img.shields.io/badge/i18n-FR%20%7C%20EN-informational" alt="i18n"></a>
<a href="https://github.com/qdm12/gluetun"><img src="https://img.shields.io/badge/Gluetun-compatible-0d1117?logo=github&logoColor=white" alt="Gluetun compatible"></a>
<a href="https://airvpn.org/?referred_by=483746"><img src="https://img.shields.io/badge/AirVPN-compatible-1a7a3d?logoColor=white" alt="AirVPN"></a>
<a href="https://protonvpn.com"><img src="https://img.shields.io/badge/Proton-compatible-6d4aff?logo=protonvpn&logoColor=white" alt="Proton compatible"></a>
<a href="#"><img src="https://img.shields.io/badge/Unraid-DockerMan-f15a2b?logo=unraid&logoColor=white" alt="Unraid DockerMan"></a>
<a href="https://discord.com/developers/docs/resources/webhook"><img src="https://img.shields.io/badge/Discord-webhook-5865F2?logo=discord&logoColor=white" alt="Discord"></a>
<a href="https://github.com/caronc/apprise"><img src="https://img.shields.io/badge/Apprise-compatible-3d85c8?logo=python&logoColor=white" alt="Apprise"></a>
<a href="https://github.com/Tecnativa/docker-socket-proxy"><img src="https://img.shields.io/badge/socket--proxy-compatible-blueviolet?logo=docker&logoColor=white" alt="Docker socket-proxy"></a>
</p>

> **Using it? Liking it? [⭐ Drop a star!](https://github.com/Aerya/Gluetun-Companion/stargazers)** — takes two seconds.

> **Want the shortest path?** Check [compatibility](#compatibility), go directly to the [quick start](#quick-start), then return to [features](#features) and [detailed operation](#how-it-works) as needed. Project maintenance is covered under [automated workflows](#automated-workflows) and [security](#security).

Gluetun Companion is a Web UI for automatically managing WireGuard and OpenVPN servers inside [Gluetun](https://github.com/qdm12/gluetun):
- It benchmarks your VPN servers from inside the tunnel itself, using sidecar mode without restarting your main Gluetun, or Gluetun’s HTTP proxy
- Each server is evaluated using speed, latency, jitter, packet loss, DNS latency, history and real-world stability
- The best server can be selected automatically according to your usage profile: balanced, gaming, BitTorrent, DDL, download or streaming
- Rotation pools also let you switch servers without a full benchmark, using random, round-robin or best historical download selection
- VPN profiles support multiple providers, protocols and custom configurations, with encrypted secrets and WireGuard/OpenVPN support
- The Gluetun catalogue, AirVPN picker, new-server detection and overloaded-server filtering make daily maintenance easier
- Companion manages Docker containers attached to Gluetun: recreation after switches, pause during benchmarks and optional image updates
- It can check BitTorrent trackers, handle VPN port forwarding and synchronize ports with qBittorrent or rTorrent
- History, hourly patterns, Discord/Apprise notifications, REST API, Prometheus metrics and Grafana support turn it into a full homelab VPN control panel


> **Status: beta.** Gluetun Companion is still in testing. It is developed and battle-tested primarily with **AirVPN**; other providers have barely been tested in real conditions, even though the mechanics (catalogue, benchmark, switching, container management) are strictly identical for all of them. Your feedback is invaluable.
>
> **Current validation status:**
> - **100% functional with AirVPN over WireGuard**;
> - tested over WireGuard with a few other providers;
> - feedback needed for **OpenVPN providers**;
> - **ProtonVPN WireGuard + NAT-PMP port forwarding** supported through VPN profiles; real-world qBittorrent synchronization feedback is still useful;
> - feedback needed for **Custom WireGuard** and **Custom OpenVPN** servers.

 **AI-assisted development:** approximately **70% of the code was produced with the assistance of Claude Code and Codex**, under human direction and validation. Particular attention is paid to security: [secret encryption and protection](#security), [automated workflows, Dependabot and Trivy](#automated-workflows), restricted Docker socket access through [`docker-socket-proxy`](#quick-start), automated tests, and change review. This transparency does not replace real-world feedback, which remains especially important during beta testing.

 **Issues and pull requests are welcome**, with proper form: for an [issue](https://github.com/Aerya/Gluetun-Companion/issues), please include the version, VPN provider, relevant logs and reproduction steps; for a PR, a clear description of the problem solved and the expected behaviour.


---

## Compatibility

Gluetun Companion supports **WireGuard and OpenVPN** with Gluetun-compatible providers. VPN profiles manage the credentials required by each protocol and provider, while the following variables select which servers should be tested or used:

| Gluetun variable | Filter |
|---|---|
| `SERVER_NAMES` | Server name |
| `SERVER_COUNTRIES` | Country |
| `SERVER_REGIONS` | Region |
| `SERVER_CITIES` | City |
| `SERVER_HOSTNAMES` | Hostname |

Both **WireGuard and OpenVPN** profiles support benchmarking, metrics and automatic switching. In sidecar mode, WireGuard profiles can use a dedicated identity to avoid disrupting the main tunnel; OpenVPN profiles are tested with their own credentials.

Primarily designed and tested for **[AirVPN](https://airvpn.org/?referred_by=483746)** *(affiliate link)* — [AirVPN filter variables](https://github.com/qdm12/gluetun-wiki/blob/main/setup/providers/airvpn.md#optional-environment-variables).

---

## Table of contents

- [Compatibility](#compatibility)
- [Quick start](#quick-start)
- [Features](#features)
  - [Speed testing](#speed-testing)
  - [Server selection & automatic switching](#server-selection--automatic-switching)
  - [Rotation pools](#rotation-pools)
  - [Multi-provider (WireGuard & OpenVPN)](#multi-provider-wireguard--openvpn)
  - [Gluetun server catalogue](#gluetun-server-catalogue)
  - [Docker container management](#docker-container-management)
  - [BitTorrent tracker checks](#bittorrent-tracker-checks)
  - [AirVPN](#airvpn)
  - [Analysis & history](#analysis--history)
  - [UI & notifications](#ui--notifications)
  - [Integration & infrastructure](#integration--infrastructure)
- [Environment variables](#environment-variables)
- [How it works](#how-it-works)
  - [Sidecar mode (default)](#sidecar-mode-default)
  - [HTTP proxy mode (optional)](#http-proxy-mode-optional)
  - [Containers to restart after switch](#containers-to-restart-after-switch)
  - [Containers to pause during benchmark](#containers-to-pause-during-benchmark)
  - ["Test running" banner and Stop button](#test-running-banner-and-stop-button)
  - [AirVPN server picker](#airvpn-server-picker)
  - [Quick check before benchmark](#quick-check-before-benchmark-option)
  - [Time optimization](#time-optimization-option)
  - [Smart benchmark selection](#smart-benchmark-selection-recommended-for-large-catalogues)
  - [Allowed servers before benchmark](#allowed-servers-before-benchmark-option)
  - [Avoid loaded AirVPN servers](#avoid-loaded-airvpn-servers-option-dedicated-to-airvpn)
  - [Docker events listener](#docker-events-listener)
  - [BitTorrent tracker checks through the VPN](#bittorrent-tracker-checks-through-the-vpn)
  - [BitTorrent clients and tracker discovery](#bittorrent-clients-and-tracker-discovery)
  - [VPN forwarded port inventory](#vpn-forwarded-port-inventory)
  - [Usage profiles](#usage-profiles)
  - [VPN profiles (WireGuard & OpenVPN)](#vpn-profiles-wireguard--openvpn)
    - [OpenVPN profiles](#openvpn-profiles)
    - [Custom WireGuard: personal single server](#custom-wireguard-personal-single-server)
  - [Rotation pools (how it works)](#rotation-pools-1)
  - [Selection score — stability components](#selection-score--stability-components)
  - [Per-server confidence score](#per-server-confidence-score)
  - [Jitter & Packet Loss](#jitter--packet-loss)
  - [Hourly patterns view](#hourly-patterns-view-historypatterns)
  - [New AirVPN server detection](#new-airvpn-server-detection)
  - [Contextual notifications](#contextual-notifications)
  - [REST API](#rest-api)
  - [Prometheus /metrics endpoint](#prometheus-metrics-endpoint)
  - [Automatic cycle vs manual trigger](#automatic-cycle-vs-manual-trigger)
- [Grafana dashboard](#grafana-dashboard)
- [Automated workflows](#automated-workflows)
- [Notes](#notes)
- [Security](#security)
- [Credits](#credits)
- [License](#license)

---

## Quick start

### 1. Expose Gluetun's HTTP proxy on the host

```yaml
# in your existing Gluetun docker-compose.yml
ports:
  - 8887:8888   # or whichever port you have configured

environment:
  HTTPPROXY: "on"
  HTTPPROXY_LOG: "off"
  # HTTPPROXY_USER: ""       # optional — set in the UI Settings if needed
  # HTTPPROXY_PASSWORD: ""
```

### 2. Mount the Gluetun compose directory

The companion needs write access to the directory containing your Gluetun `docker-compose.yml` so it can write a `docker-compose.override.yml` and restart the service.

> **Unraid / DockerMan**
> If Gluetun is managed by Unraid's Docker Manager (`net.unraid.docker.managed=dockerman`), Companion auto-detects that backend and does not use `docker compose` for switches. Mount the Unraid template directory as writable, for example `- /boot/config/plugins/dockerMan/templates-user:/boot/config/plugins/dockerMan/templates-user`, so changes are persisted back into the DockerMan template before the container is recreated. `CONTROL_BACKEND=unraid` can force this mode if automatic detection is not enough.

### 3. Run the companion

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
      - /path/to/data:/data
      - /path/to/gluetun/stack:/compose   # ← adapt this path
      - /path/to/gluetun/openvpn:/openvpn
    extra_hosts:
      - "host.docker.internal:host-gateway"
    environment:
      - TZ=Europe/Paris
      - SECRET_KEY=replace-with-a-random-string   # openssl rand -hex 32
      - DATA_DIR=/data
      - GLUETUN_HOST=host.docker.internal
      - GLUETUN_PROXY_PORT=8887
      - GLUETUN_CONTAINER=gluetun-airvpn   # exact name of your Gluetun container (Compose service name is auto-detected)
      - COMPOSE_DIR=/compose
      - OPENVPN_CONFIG_DIR=/openvpn
      - OPENVPN_CONTAINER_DIR=/gluetun/openvpn
      - DOCKER_HOST=tcp://socket-proxy:2375
      # Optional: protect /metrics with a Bearer token.
      # Leave unset (or empty) for open access — standard for internal Prometheus scrapes.
      # - METRICS_TOKEN=your-secret-token
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

> **Why `socket-proxy`?**
> The Docker socket gives near-total access to the host. The [Tecnativa proxy](https://github.com/Tecnativa/docker-socket-proxy) sits between Companion and the socket, restricting access to the required operations: reading containers/images/networks/volumes, plus POST/DELETE needed to create and remove temporary sidecar containers. It blocks direct daemon access (exec, info, swarm…). Fully transparent for the user, reduced attack surface.

Open **http://localhost:8765** — first login: enter the credentials you want (account created automatically).

> **Unraid / DockerMan:** a temporary XML template is available in [`templates/unraid`](templates/unraid/README.md) for manual install or *Private Apps*, pending a possible Community Applications publication.

> **Companion in the same stack as Gluetun?**
> Remove `extra_hosts` and use the service name: `GLUETUN_HOST: gluetun`.
> On a switch, the companion only targets the Gluetun service (`docker compose up -d <service>`) — it never restarts itself.

### 4. Import servers

**Servers → Import from Gluetun**: the companion reads `SERVER_NAMES`, `SERVER_COUNTRIES`, etc. directly from the running container and imports each value with its filter type. The Gluetun catalogue can also import servers by country, city, region, hostname or name, with server-type filtering when the provider exposes it (for example `P2P`, `Streaming`, `Secure Core`, `Tor` or `Free` on ProtonVPN). Manual addition is also available on the same screen.

> ⚠️ **Companion benchmarks each server individually, by name.** Setting `SERVER_COUNTRIES`, `SERVER_REGIONS` or `SERVER_CITIES` adds a single entry (e.g. "France") — Companion does **not** automatically discover individual servers in that country. Add each server by its name (`SERVER_NAMES`) for benchmarking to work. **Minimum 2 named servers required.**

---

## Features

### Speed testing
- **Sidecar mode** (default) — a `gluetun-companion-test` container clones the real Gluetun config for each server; `gluetun-companion-sidecar` measures speed via **Ookla + librespeed in parallel** (dual mode, default), Ookla only, librespeed only, or iperf3 directly inside the VPN tunnel; your main Gluetun is never restarted during testing
- **HTTP proxy mode** (optional) — measures speed via the Gluetun HTTP proxy with no extra containers; briefly interrupts dependent services on each server switch
- **Multi-source results** — Ookla, librespeed and iperf3 speeds stored separately and displayed in the dashboard and history
- **Multi-stream download** — N concurrent TCP connections (configurable, default: 4)
- **Automatic benchmarking** every X hours — download, upload and latency per server; automatic cycle can be disabled (manual trigger only)
- **Smart benchmark selection** *(option)* — avoids huge cycles on massive catalogues: tests the best known servers for the usage profile, explores a few new servers and refreshes old measurements
- **Allowed servers before benchmark** *(option)* — select which **entry types** to include in each cycle (`SERVER_NAMES`, `SERVER_COUNTRIES`, `SERVER_CITIES`, `SERVER_REGIONS`, `SERVER_HOSTNAMES`) and, for AirVPN, skip overloaded servers; excluded servers remain in the list and can be tested manually
- **Quick check before benchmark** *(option)* — tests only the current server before each cycle; if speed is within ±N% of the last known result, the full benchmark is skipped entirely — no containers paused, no VPN restarts; triggers the full benchmark only when performance drifts significantly
- **Time optimization** *(option)* — analyses hourly speed and variance patterns to identify the best and worst benchmark windows; recommended time slots displayed in Settings; optional auto-shift: if the next cycle falls on an unfavorable hour, it is shifted up to 3 h forward to the next favorable window
- **On-demand quick benchmark** — button always available (dashboard and settings); tests only the active server via the Gluetun HTTP proxy, result in seconds, no VPN interruption, result saved in history
- **Duration estimate** — the dashboard shows a dynamically calculated duration range (optimistic / pessimistic) based on your settings (`wait_secs`, `duration`, `samples`, `retries`, sidecar or proxy mode); automatic ⚠️ alert if the estimated total exceeds 30 minutes; the same estimate is shown live in Settings as you adjust parameters
- **Jitter & Packet Loss** — network stability measured at every test (21 TTFB probes in proxy mode, ICMP via sidecar); 🟢/🟡/🔴 indicator on Servers page, dedicated columns in History, jitter shown in hourly patterns; factored into selection score (up to −15 % jitter / −25 % loss penalty)
- **DNS latency** *(sidecar)* — DNS resolution time measured from inside the VPN tunnel via `dig` (4 domains in parallel, median returned); detects slow, overloaded, or hijacking resolvers; column in History, DNS shown in the Stability tooltip, data in hourly patterns
- **Docker events listener** — daemon thread watching for Gluetun container `start` events; if Gluetun restarts on its own (crash, update, watchdog), automatically triggers a quick check after N seconds (VPN reconnect delay); if speed drift exceeds the configured threshold and auto-switch is enabled, immediately runs a full benchmark; restarts triggered by Companion itself are ignored; 5-minute cooldown between triggers

### Observed DNS resolvers

Companion separates two pieces of information:

- the **DNS intermediary** read from the Gluetun configuration, for example `Local DNS (192.168.0.64)`;
- the **resolvers actually observed on the Internet**, for example `Cloudflare, Quad9`.

When a private tunnel address appears to belong to the VPN provider, the UI remains cautious: `Probable intermediary: AirVPN VPN provider DNS (10.x.x.x)`. No local software such as AdGuard Home or Pi-hole is assumed or required.

Universal detection uses the free [bash.ws](https://bash.ws/dnsleak) service: a temporary sidecar sharing Gluetun's network requests an identifier, triggers ten unique resolutions, then retrieves the observed resolver IPs, ASNs and countries. No `docker exec` or additional Docker socket access is required. Results are cached for six hours to limit requests. This operation discloses the VPN IP and test DNS queries to the third-party service, but no Companion identifier or user-browsed domain.

The **VPN Status** card displays the intermediary and observed operators. In tables, only DNS latency remains visible; details are provided in a tooltip. The state is also exposed by `GET /api/v1/status` under `dns_path` (`intermediary`, `resolvers`, `observed_summary`, `tested_at`).

### Server selection & automatic switching
- **Automatic switching** to the fastest server (`docker compose up -d`), based on a weighted score combining current speed, exponential history, jitter, packet loss and involuntary reconnects (via Docker events); configurable *Speed vs stability* slider; **6 usage profiles** (Balanced, Gaming, BitTorrent, DDL, Download, Streaming) — each profile weights metrics differently to find the server best suited to your actual use case; dependent services (`network_mode: service:gluetun`) are recreated automatically
- **Manual switch** to any configured server from the Servers page — Gluetun is reconfigured and `network_mode: service:gluetun` containers are recreated automatically
- **5 filter types**: `SERVER_NAMES`, `SERVER_COUNTRIES`, `SERVER_REGIONS`, `SERVER_CITIES`, `SERVER_HOSTNAMES`
- Configurable **retry** per server + global timeout per server
- **Auto-disable** a server after N consecutive failures

### Rotation pools

- **Rotation without benchmarking** — switch to a server from a predefined group without triggering a full measurement cycle; ideal for periodic rotation or quick one-off changes
- **Readable candidate rules** — each pool starts from simple rules: specific server, Gluetun filter type (`SERVER_NAMES`, `SERVER_COUNTRIES`, `SERVER_CITIES`, `SERVER_REGIONS`, `SERVER_HOSTNAMES`), VPN profile, top metric, or all active servers. Rules can either add their results or keep only servers matching every rule.
- **Per-pool exclusions** — exclude specific servers from one pool without disabling them in Companion; they remain available elsewhere, but this pool will never pick them.
- **3 selection modes**: 🎲 random, 🔄 round-robin (persistent cursor across rotations), 🏆 best historical download
- **Final limit** — after rules and exclusions, restrict the pool to the N best historical download speeds (if unset, all remaining candidates are eligible)
- **Manual or scheduled** — instant one-click rotation from the UI, or automatic rotation on a configurable interval (in hours; e.g. every 12 h or every 2 days)
- **Optional post-switch measurement** — after each switch, a fast proxy test measures the new server's speed and records it in the history (method `proxy_qc`). This measurement does not choose the server; it audits the completed rotation.
- **Notifications** — Discord/Apprise alert on each rotation (manual or automatic), including previous server, new server, and speed if post-switch measurement is enabled

### Multi-provider (WireGuard & OpenVPN)

- **VPN profiles** — create multiple sets of credentials from **Settings → VPN profiles**; each profile is linked to a provider **and a connection type** (WireGuard or OpenVPN, depending on what Gluetun supports natively for that provider); **all 24 providers from the Gluetun wiki are integrated**
- **Secret encryption** — private keys, OpenVPN passwords and other sensitive fields are encrypted at rest (Fernet/AES-128, key derived from `SECRET_KEY` via PBKDF2HMAC-SHA256 with 480 000 iterations); changing `SECRET_KEY` makes existing profiles unreadable (documented behavior)
- **Server ↔ profile assignment** — on the **Servers** page, assign a VPN profile to each server via a dropdown; a *Provider* column shows the linked profile; the `?profile=` filter limits the view to a single profile or to unassigned servers
- **Orphan server alert** — a badge warns when servers have no assigned profile while at least one VPN profile is configured; those servers continue to work normally but cannot be selected by the multi-profile benchmark
- **Multi-profile benchmark** — in sidecar mode, each server is tested with its profile's credentials injected into the temporary container; on the final switch, Companion automatically writes `VPN_SERVICE_PROVIDER`, `VPN_TYPE` and all credential variables (`WIREGUARD_*` or `OPENVPN_*`) to `docker-compose.override.yml`, blanking credentials inherited from the base compose file so nothing leaks between providers
- **Sidecar and OpenVPN** — OpenVPN profiles are tested with the same credentials as the main tunnel (most providers allow several simultaneous connections); the dedicated sidecar key only applies to WireGuard profiles
- **Rotation policy** — three modes configurable in **Settings → VPN profiles → Rotation policy**:
  - `none` — Companion always stays in the currently active profile; servers from other profiles are never selected
  - `free` — picks the best server across all profiles (default behavior without profiles)
  - `conditional` — switches to another profile only if its best server outperforms the best server in the current profile by more than N % (configurable threshold, default 10 %)
- **Provider column in `/history`** — each history row shows the VPN profile associated with the tested server (only visible when at least one profile is configured)

**Integrated providers** (from the [Gluetun wiki](https://github.com/qdm12/gluetun-wiki/tree/main/setup/providers)):

| Provider | WireGuard | OpenVPN | OpenVPN credentials |
|---|---|---|---|
| AirVPN | Native | Native | Client certificate + key (`OPENVPN_CERT`, `OPENVPN_KEY`) |
| CyberGhost | Via `custom` | Native | `OPENVPN_USER`/`OPENVPN_PASSWORD` + client certificate + key |
| ExpressVPN | — | Native | `OPENVPN_USER`/`OPENVPN_PASSWORD` |
| FastestVPN | Native | Native | `OPENVPN_USER`/`OPENVPN_PASSWORD` |
| Giganews (VyprVPN) | — | Native | `OPENVPN_USER`/`OPENVPN_PASSWORD` |
| HideMyAss | — | Native | `OPENVPN_USER`/`OPENVPN_PASSWORD` |
| IPVanish | — | Native | `OPENVPN_USER`/`OPENVPN_PASSWORD` |
| IVPN | Native | Native | `OPENVPN_USER` (password optional with the account ID) |
| Mullvad | Native | — | OpenVPN removed by Mullvad in January 2026 |
| NordVPN | Native | Native | Service credentials (`OPENVPN_USER`/`OPENVPN_PASSWORD`) |
| Perfect Privacy | — | Native | `OPENVPN_USER`/`OPENVPN_PASSWORD` |
| Privado | — | Native | `OPENVPN_USER`/`OPENVPN_PASSWORD` |
| Private Internet Access | Via `custom` | Native | `OPENVPN_USER`/`OPENVPN_PASSWORD` |
| PrivateVPN | Via `custom` | Native | `OPENVPN_USER`/`OPENVPN_PASSWORD` |
| ProtonVPN | Native | Native | Dedicated OpenVPN credentials (`+pmp` for port forwarding) |
| PureVPN | Via `custom` | Native | `OPENVPN_USER`/`OPENVPN_PASSWORD` |
| SlickVPN | — | Native | `OPENVPN_USER`/`OPENVPN_PASSWORD` + certificate + encrypted key |
| Surfshark | Native | Native | `OPENVPN_USER`/`OPENVPN_PASSWORD` |
| TorGuard | Via `custom` | Native | `OPENVPN_USER`/`OPENVPN_PASSWORD` |
| VPN Secure | — | Native | Certificate + encrypted key + passphrase (`OPENVPN_KEY_PASSPHRASE`) |
| VPN Unlimited | Via `custom` | Native | `OPENVPN_USER`/`OPENVPN_PASSWORD` + client certificate + key |
| VyprVPN | Via `custom` | Native | `OPENVPN_USER`/`OPENVPN_PASSWORD` |
| Windscribe | Native | Native | `OPENVPN_USER`/`OPENVPN_PASSWORD` (from a generated config file) |
| Custom | Native | Native | `.conf` file mounted into Gluetun + optional credentials |

> Client certificates and keys (CyberGhost, VPN Unlimited, AirVPN OpenVPN, SlickVPN, VPN Secure) go straight into the form: paste the base64 body as a single line (without the `BEGIN`/`END` markers) — no file mount needed.
>
> **Custom WireGuard** remains available for any provider without native WireGuard support in Gluetun (CyberGhost, PIA, PrivateVPN, PureVPN, TorGuard, VPN Unlimited, VyprVPN…) as long as it provides a standard WireGuard configuration file.

---

### Gluetun server catalogue
- **Real Gluetun catalogue first** — the catalogue Sidecar automatically mounts the Gluetun container's `/gluetun` volume when it is available and reads `/gluetun/servers.json` first; this is the exact list loaded by Gluetun. If that volume is not available, Companion falls back to the public [`qdm12/gluetun-servers`](https://github.com/qdm12/gluetun-servers/tree/main/pkg/servers) repository
- **Automatic refresh** — the list is updated **at every benchmark cycle** (configurable interval in Settings → Measure, default: 6 h); a dedicated button in Settings and in the `/servers` modal lets you force an immediate refresh
- **Auto-add new servers** *(option)* — when new servers appear in the catalogue for a **country**, **region** or **city** you already have configured, Companion automatically adds them to your server list (as `SERVER_NAMES` entries) without any manual action; disabled by default, enable in **Settings → Maintenance → Catalogue**
- **Change notifications** *(option)* — Discord/Apprise alert sent on each refresh when servers are added to or removed from the catalogue, with per-provider detail (+N/−N); enable in **Settings → Notifications**
- **3 import modes in Settings**:
  1. **All providers** — imports servers from every provider available in the local Gluetun catalogue, or from the GitHub fallback
  2. **Chosen provider** — imports only the servers of a provider selected manually
  3. **Active provider** — automatically detects the provider configured in your Gluetun and imports its servers only
  — for each mode, an option to **run a full benchmark** immediately after import (using the configured method in Settings, across all servers in the list)
- **All filter types** — each server is imported with its full attributes: `SERVER_NAMES`, `SERVER_COUNTRIES`, `SERVER_CITIES`, `SERVER_REGIONS`, `SERVER_HOSTNAMES`
- **Multi-filter selection from `/servers`** — select servers by freely mixing filter types (e.g. names + countries + cities at the same time); Companion applies the right filter in Gluetun and changes the filter type on the fly if needed
- ⚠️ **ProtonVPN** — When the Gluetun container's `/gluetun` volume is available, the **Catalogue** uses `servers.json` and can therefore show the Premium servers actually loaded by Gluetun, including P2P/Streaming/hostname metadata. Without that volume, the GitHub fallback may still be limited to public data.

**Prerequisites** — the catalogue sidecar works without extra configuration. To enrich the catalogue with the data actually loaded by Gluetun, Companion tries to mount the Gluetun container's `/gluetun` volume read-only; otherwise outbound HTTPS access is enough for the GitHub fallback.

### Docker container management
- **Gluetun network containers (auto-managed)** — running containers using `network_mode: service:gluetun` are detected and recreated automatically after each switch, including those already stuck in a dead namespace (left over from a previously failed switch). Intentionally stopped containers stay stopped. Containers in a **different Compose stack** from Gluetun are also handled if their directory is accessible from Companion or if their `com.docker.compose` labels are present. Orphan detection is limited to containers referencing a **known former Gluetun** (ID history kept in the database) — Companion never touches dependents of another VPN or an unrelated stack
- **Containers to restart after switch** — only for containers routing through Gluetun's HTTP/SOCKS5 proxy; ordered list (drag & drop)
- **Pause during benchmark** — list of containers (torrent, Usenet…) stopped before the benchmark starts and automatically restarted when it ends, even on error
- **Automatic Docker image updates** *(option)* — at switch time, Companion can update images before restarting containers: Gluetun itself, auto-managed network containers, post-switch containers and benchmark-paused containers; togglable per container from Settings

### BitTorrent tracker checks
- **Multiple clients** — configure one or more qBittorrent or rTorrent/ruTorrent clients in **Settings → BitTorrent**; each client can be a tracker source, even if its container is also stopped during benchmarks
- **Persistent discovery** — Companion fetches tracker URLs from loaded torrents, deduplicates them, then displays source clients, torrent count, last check and success status
- **Passkeys hidden** — private passkeys and tokens are stripped from detected URLs before storage/display, including query-string keys and token-like path segments
- **Per-URL control** — each tracker can be enabled or ignored individually for future checks
- **VPN compatibility score** — enabled trackers are checked through the VPN path; by default, 80% success is enough to consider the server compatible, avoiding false negatives when a single tracker is down
- **Optional switch criterion** — when enabled, a benchmarked server below the tracker threshold is excluded from the auto-switch pick; pools ignore servers already known as tracker-incompatible
- **Per-provider port forwarding** — declare AirVPN/manual, Gluetun-native (`/v1/portforward`) or custom rules in **Settings → Port Forwarding**; when automation is enabled, Companion applies the current provider's rules after every switch (manual, benchmark, pool rotation), resynchronizes qBittorrent or rTorrent *(beta)* and runs the configured `on_port_change` hooks; a periodic check also catches port renewals that happen without a container restart

### AirVPN
- **Built-in AirVPN server picker** — *+ Add AirVPN servers* button on the Servers page: live data from `airvpn.org/api/status/` (5-min server-side cache), four tabs — full searchable list, geographic distribution by country, **Recommended** tab (load < 70 %, bandwidth ≥ 5 Gbit/s) and **Changes** tab (newly detected servers, disappeared servers, load shifts, top 5 healthiest countries); multi-select, one-click add
- **Visible and filterable AirVPN bandwidth** — Companion stores the capacity advertised by AirVPN (`bw_max`) separately from benchmark results: sortable/filterable column in `/servers`, filter in the AirVPN import modal, badges on the dashboard, history, pool rotations and switches. This is provider metadata, not a measured speed result.
- **Avoid loaded AirVPN servers** *(optional, dedicated to [AirVPN](https://airvpn.org/?referred_by=483746))* — at benchmark start, **[AirVPN](https://airvpn.org/?referred_by=483746)** servers of type `SERVER_NAMES` whose **load** or **user count** exceeds a configurable threshold are automatically skipped; data from the AirVPN cache (updated every 5 min); servers without AirVPN data are never excluded; thresholds configurable in Settings → Measure → Which servers are allowed
- **New AirVPN server detection** *(optional)* — compares the AirVPN API with your configured servers every 24 h; badge and dismissable banner on the Servers page + *Changes* tab in the add modal; Discord/Apprise notification with optional mention

### Analysis & history
- **Per-server confidence score** — 🟢/🟡/🔴 indicator on the Servers page and in History; based on measurement count and result variability; factored into the automatic selection score (light weighting)
- **Hourly patterns** (`/history/patterns`) — 0h–23h bar chart showing average speed by hour of day, color-coded by relative performance; best and worst hour displayed; helps identify server saturation windows
- **Sortable columns** — click table headers in `/history` and `/servers` to sort; clicking again reverses the order; ▲/▼/⇅ visual indicators; sort persists across pages
- **On-demand test** of a single server from the UI without waiting for the next cycle
- **CSV export** of the full history

### UI & notifications
- **Web UI** dark/light/auto, FR/EN — auth, dashboard with sparkline, paginated history, charts, switches page with Mbps gain and connection time
- **Server detail panel** — click a server name in `/servers`: aggregate stats (average speeds, latency, peak, test count), sparkline of the last 30 tests, recent results and actions (test, switch, full history) in a side panel
- **Getting-started checklist** — dashboard card guiding the install (VPN profile → server import → first benchmark), disappears once setup is complete
- **Column picker** — hide unneeded columns on `/servers` (preference kept per browser)
- **Settings search** — search field filtering cards across all tabs with a per-tab match counter
- **VPN provider logos** — shown next to server names throughout the UI and in the catalogue (bundled SVGs + server-side cached favicons — the browser never contacts a third-party service)
- **Global test banner** — visible on every page during a test: test type, current server, progress %, estimated time remaining and a Stop button (state persists across page reloads)
- **Contextual notifications** — 10 independently-configurable alert types (auto/manual switch, auto-exclude, benchmark with no results, benchmark complete, quick check result, pool rotation, new AirVPN servers, catalogue changes, optimal window change) via Discord webhook (rich embed) and/or [Apprise](https://github.com/caronc/apprise/wiki) (Telegram, ntfy, Gotify, Slack, Pushover…); severity levels 🔴/🟡/🔵; global Discord mention with configurable severity threshold
- **Automatic purge** of SQLite history with configurable retention (in days)

### Integration & infrastructure
- **`/healthz` endpoint** unauthenticated, for Docker healthchecks
- **`/metrics` endpoint** in Prometheus format — throughput, latency, switches, active server; optionally protected by Bearer token; Grafana-compatible
- **REST API `/api/v1/`** protected by Bearer token — VPN status, server list, history, switches, trigger full or quick benchmark; designed for Home Assistant, n8n, bash scripts
- **Structured JSON logs** optional via `LOG_JSON=1` (Loki/Grafana compatible)
- **SQLite database** (WAL) — no external dependencies

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `SECRET_KEY` | *(required)* | Flask session signing key |
| `GLUETUN_HOST` | `host.docker.internal` | Gluetun HTTP proxy host |
| `GLUETUN_PROXY_PORT` | `8887` | Gluetun HTTP proxy port |
| `GLUETUN_CONTAINER` | `gluetun-airvpn` | Gluetun container name |
| `COMPOSE_DIR` | `/compose` | Path (inside the container) to the Gluetun compose directory |
| `CONTROL_BACKEND` | `auto` | Control backend: automatic detection, or `compose` / `unraid` to force a mode |
| `UNRAID_TEMPLATE_DIR` | `/boot/config/plugins/dockerMan/templates-user` | Unraid DockerMan template directory, mounted writable when `CONTROL_BACKEND=unraid` or when the Gluetun container is detected as DockerMan-managed |
| `DATA_DIR` | `/data` | SQLite database directory |
| `OPENVPN_CONFIG_DIR` | `/openvpn` | Directory writable by Companion for Custom OpenVPN files |
| `OPENVPN_CONTAINER_DIR` | `/gluetun/openvpn` | Equivalent path as seen from the Gluetun container |
| `DOCKER_HOST` | *(local socket)* | Set to `tcp://socket-proxy:2375` when using the Tecnativa socket proxy |
| `METRICS_TOKEN` | *(empty)* | If set, the `/metrics` endpoint requires `Authorization: Bearer <token>`; leave empty for open access (standard for internal networks) |

Benchmark parameters (streams, duration, warm-up, retry…) are configured in the UI → **Settings**.

---

## How it works

### Sidecar mode (default)

```
Benchmark cycle (every X hours)
  ├─ "Pause bench" containers stopped (torrents, Usenet…)
  ├─ Pull ghcr.io/aerya/gluetun-companion-sidecar:latest
  │   (once per cycle, image kept cached; best-effort: falls back to the
  │    cached image if the registry/DNS is momentarily unavailable)
  └─ For each enabled server:
       1. Start gluetun-companion-test
          (clone of your Gluetun, configured for the target server)
       2. Start gluetun-companion-sidecar
          (network_mode: container:gluetun-companion-test)
       3. Wait for VPN via /health polling (configurable timeout)
       4. Speed test inside the VPN tunnel (configurable engine):
          - Dual (default): Ookla + librespeed in parallel, iperf3 as fallback
          - Ookla only, librespeed only, or iperf3 only
          → DL, UL, latency recorded per source
       5. Stop + remove the test containers (sidecar image kept cached)
       → Auto-retry on failure, global timeout per server
       → Auto-disable after N consecutive failures
  └─ Weighted score (65% current cycle + 35% exponential history)
  └─ Switch real Gluetun to the best server (one single restart)
  └─ "Post-switch" containers recreated (network namespace included)
  └─ "Pause bench" containers restarted (guaranteed — finally block)
  └─ Discord / Apprise notification (if configured)
```

**Available test engines (Settings → Measure → Sidecar Mode):**
- **Dual** (default) — Ookla + librespeed in parallel; results from both sources stored separately
- **Ookla only** — official Speedtest.net CLI, rarely blocked by VPN IPs
- **librespeed only** — librespeed-cli, public librespeed.org servers (HTTP)
- **iperf3 only** — direct TCP to public iperf3 servers (often blocked by VPN IPs)

**Fallbacks:**
- iperf3 as last resort if all primary sources fail (enabled by default)
- HTTP proxy fallback if sidecar fails entirely (disabled by default)

> ⚠ **Simultaneous connection**: sidecar mode uses one extra VPN connection slot for the entire benchmark duration. Check your provider's limits (AirVPN: 3–5 depending on plan).
> Companion runs sidecar tests one at a time and waits 180 s by default after container cleanup (`sidecar_disconnect_wait_seconds`) so the provider can close the VPN session before the next server starts. **This is the main driver of cycle duration**: with N servers a cycle takes at least N × this delay. If your plan allows several simultaneous connections (AirVPN: 3–5), lower it significantly (60 s or less) in **Settings → Measure** to shorten cycles; raise it if you see "too many connections" errors.
> The sidecar image is pulled **once per cycle** then reused from cache: less load on the registry/DNS, and a test no longer fails (nor switches the server) on a transient DNS hiccup.

### HTTP proxy mode (optional)

```
Benchmark cycle (every X hours)
  └─ For each enabled server:
       1. Write docker-compose.override.yml
       2. docker compose up -d  ← real Gluetun restarts
       3. Wait for VPN via HTTP proxy polling
       4. Optional TCP warm-up (2 s, not counted)
       5. Download from N endpoints → median Mbps
       6. Upload → Mbps
       7. Latency TTFB → median ms
  └─ Weighted score → switch → notification
```

Enable via **Settings → Measure → Sidecar Mode → toggle off**.

### Containers to restart after switch

In **Settings → Decide → Containers to restart after switch**: ordered list of containers recreated after each VPN switch. In Compose mode, Companion uses `docker compose up -d --force-recreate`; in Unraid/DockerMan mode, it recreates containers through the Docker SDK so they rejoin the current Gluetun network namespace. Drag & drop to reorder. Useful for `qbittorrent`, `radarr`, `sonarr`, or any service with `network_mode: service:gluetun`.

### Containers to pause during benchmark

In **Settings → Measure → Containers to pause during benchmark**: list of containers stopped before the benchmark and restarted after — in all cases, even if the benchmark crashes. If a container is in both lists, the pause list takes priority (no duplicate restart). Useful for `qbittorrent`, `sabnzbd`, `nzbget`, `transmission`.

### BitTorrent tracker checks through the VPN

In **Settings → BitTorrent**, Companion can verify whether the trackers actually used by your torrents are reachable from the VPN server being tested or selected. The goal is not to perform a full real announce for every torrent, but to verify useful connectivity with four levels:

According to the [official Gluetun DNS documentation](https://github.com/qdm12/gluetun-wiki/blob/main/setup/options/dns.md), Gluetun enables `BLOCK_MALICIOUS=on` by default. Some announce URLs may therefore be blocked by its DNS lists even when the tracker is available. Under **Settings → BitTorrent → Gluetun DNS filtering**, Companion can keep this protection enabled while allowing specific domains through `DNS_UNBLOCK_HOSTNAMES`, or disable `BLOCK_MALICIOUS` entirely as a last resort. The setting is written to `docker-compose.override.yml`, applied immediately by recreating Gluetun, and preserved across subsequent switches. Disabling it globally reduces DNS protection for every container sharing Gluetun's network; a targeted exception is recommended.

1. **DNS** — the tracker domain can be resolved.
2. **Port** — the TCP/UDP tracker port responds.
3. **Tracker endpoint** — the `/announce` URL or UDP tracker handshake responds. HTTP `400`, `401`, `403` or `invalid request` responses can still count as reachable: the tracker rejected the test request, but the endpoint is accessible.
4. **Aggregated score** — if the percentage of reachable trackers is above the configured threshold (80% by default), the VPN server is considered compatible.

This threshold avoids false negatives: a private or public tracker can be temporarily down without making the VPN server bad. Companion stores per-URL history so it can gradually distinguish globally unavailable trackers from trackers blocked only on specific VPN paths.

Two separate toggles are available in **Settings → BitTorrent**:

- **Enable tracker checks during VPN verification** runs discovery before benchmarks, then checks enabled URLs for each tested server.
- **Require an OK tracker result for automatic switches and pools** turns that score into an eligibility criterion: during a benchmark, servers below the threshold are excluded from the final pick; in pool rotation, servers already known below threshold are ignored, while never-tested servers remain candidates.

The **Servers** page shows a sortable **Trackers** column with the latest known result per server (`OK`, below-threshold percentage, or `—` when never tested). This makes compatible and problematic servers easy to spot.

HTTP/HTTPS trackers are checked through Gluetun's HTTP proxy when configured. UDP trackers require Companion to be able to send UDP from the VPN path; if your installation only exposes the HTTP proxy, UDP URLs can still be listed and managed, but real UDP checks depend on your network topology.

### BitTorrent clients and tracker discovery

Companion can manage multiple BitTorrent sources: for example one main qBittorrent instance, another qBittorrent dedicated to cross-seed, and an rTorrent/ruTorrent instance. Each configured client contains:

- type: `qBittorrent` or `rTorrent / ruTorrent RPC2`;
- API/WebUI URL;
- credentials;
- optional Docker container name;
- category or tag filters;
- options to include/exclude paused torrents or private torrents.

For qBittorrent, Companion uses the Web API: torrent list, then the trackers endpoint for each hash. For rTorrent/ruTorrent, Companion uses XML-RPC/RPC2 and fetches trackers per torrent.

Discovery always runs **before** stopping containers configured in "Containers to pause during benchmark". So if `qbittorrent` or `rutorrent` is stopped during measurement, Companion uses the already cached tracker list. Discovered URLs remain visible in the UI and can be enabled or ignored one by one for future cycles. URLs are normalized without passkeys (`?passkey=...`, `authkey`, `token`, private path segments, etc.) so secrets are not exposed in the interface.

### VPN forwarded port inventory

In **Settings → Port Forwarding**, Companion manages incoming ports required by BitTorrent clients per VPN provider. Three states are available:

- **Disabled** — rules remain stored but are not applied.
- **Manual active** — rules can be declared, checked and synchronized on demand.
- **Automatic active** *(default once port forwarding is enabled; can be turned off)* — when Gluetun switches to another VPN server or provider (manual switch, benchmark **or pool rotation**), Companion automatically applies the current provider's rules. This also covers ProtonVPN switches to another server of the same provider, where the NAT-PMP port may change. After a Docker-detected Gluetun reconnection, Companion also rereads the native port and propagates it when needed. Finally, a **periodic check (every 5 min)** compares the native `/v1/portforward` port to the last applied port: if Gluetun renewed the port **without a container restart** (e.g. NAT-PMP renewal), the rules are re-applied automatically.

Each entry contains:

- readable name;
- provider (`AirVPN`, `ProtonVPN`, `Custom WireGuard`, etc., or `Manual`);
- mode (`Manual` or `Gluetun native`);
- manual port, optional in native mode;
- protocols `TCP` and/or `UDP`;
- optional linked BitTorrent client;
- optional `on_port_change` command;
- free-form note.

For each declared port, the UI shows:

- whether the port is present in `FIREWALL_VPN_INPUT_PORTS`;
- whether the port is present in `FIREWALL_INPUT_PORTS`;
- whether the port is published on the Gluetun Docker container, per protocol;
- qBittorrent listen port when the entry is linked to a qBittorrent client.

The **Sync** button updates the linked client's listen port: qBittorrent through the Web API (`/api/v2/app/setPreferences` + read-back verification), or **rTorrent via XML-RPC** (`network.port_range.set` + read-back — *beta support, implemented against the XML-RPC spec but not yet validated on a live rTorrent instance; the `on_port_change` hook remains available as a fallback*). In **Gluetun native** mode, Companion first reads the Gluetun Control Server (`GET /v1/portforward`) and then pushes the returned port to the client.

**Testing reachability from the Internet**: each rule's **Test from Internet** button performs a **real TCP connection** from Companion to `VPN_public_IP:port`. Since Companion egresses through your ISP connection (not the VPN tunnel), this exercises the actual inbound path: Internet → VPN provider → Gluetun → client. **TCP only** — UDP has no handshake and cannot be verified this way. The configuration indicators (firewall, Docker publishing, listen port) remain local checks; this button is the only one proving real reachability. For a manual external double-check: [canyouseeme.org](https://canyouseeme.org/) or [yougetsignal.com](https://www.yougetsignal.com/tools/open-ports/) (VPN public IP and port must be typed by hand — these sites cannot be pre-filled).

To enable Gluetun native support, expose its [Control Server](https://github.com/qdm12/gluetun-wiki/blob/main/setup/advanced/control-server.md). In Companion, set the URL, for example `http://host.docker.internal:8967` when Docker publishes `8967:8000`. If Gluetun uses `apikey` authentication, also enter the `X-API-Key` value. Companion uses `/v1/portforward` as the primary source and retries the legacy `/v1/openvpn/portforwarded` endpoint if the Control Server rejects or does not expose the modern endpoint.

#### ProtonVPN and qBittorrent

ProtonVPN assigns a random NAT-PMP port which may change on every connection or renewal. Do not enter a fixed port or publish that port in the Docker Compose file. In the ProtonVPN profile, enable **Port forwarding**; Companion then writes `VPN_PORT_FORWARDING=on` for that profile and can restrict selection to **P2P / port-forwarding** servers with `PORT_FORWARD_ONLY=on`. Other Gluetun server types (`Streaming`, `Secure Core`, `Tor`, `Free`) can also be selected from the profile or catalogue when useful. Then configure a rule using provider `ProtonVPN`, **Gluetun native** mode, and the relevant qBittorrent client. Companion:

1. reads the current port from `GET /v1/portforward`;
2. sends it to qBittorrent through `/api/v2/app/setPreferences`;
3. reads qBittorrent preferences back to confirm the change;
4. checks every 5 minutes whether Gluetun renewed the port and injects the new value when needed;
5. repeats after a Gluetun reconnect, a switch to ProtonVPN or a switch between ProtonVPN servers.

With ProtonVPN over **OpenVPN**, the OpenVPN username must also carry the `+pmp` suffix. ProtonVPN over **WireGuard** does not use this suffix. Gluetun native integrations open the dynamic port on the VPN side themselves, so `FIREWALL_VPN_INPUT_PORTS`, `FIREWALL_INPUT_PORTS`, and a static Docker port mapping are not required for this port.

For AirVPN, Companion does not create the port in the AirVPN panel. The expected flow is:

1. reserve the port in the AirVPN panel;
2. publish the port on Gluetun, for example `19975:19975/tcp` and `19975:19975/udp`;
3. add the port to `FIREWALL_INPUT_PORTS` and `FIREWALL_VPN_INPUT_PORTS`;
4. declare the port in Companion;
5. link the port to the relevant qBittorrent client or add an `on_port_change` command;
6. enable automatic application if rules should follow VPN provider changes.

For rTorrent/ruTorrent, simply link an rTorrent-type client to the rule: XML-RPC synchronisation applies automatically *(beta — see above)*. For other clients, personal WireGuard servers or any specific need, use `on_port_change` to call a controlled script or command. Available variables are `{port}`, `{provider}`, `{name}`, `{protocols}` and `{client}`. Example:

```bash
/compose/hooks/update-rtorrent-port.sh {port}
```

A `Custom WireGuard` rule can therefore cover a personal WireGuard server: the port can be declared manually, or handled by an external hook, and Companion runs the command when the rule becomes applicable.

### "Test running" banner and Stop button

While any test is active (full benchmark, continuous observation, quick proxy test, sidecar, pool rotation), a green banner appears at the top of every page showing the **test type**, the **server under test**, the **progress in %** (bar + percentage) and an **estimated time remaining** based on the average duration of servers already tested this cycle.

A **Stop** button is available for all modes:

- **Benchmark / Observation / Sidecar** — stops after the current server (≤ 2 seconds).
- **Quick test (proxy)** — stops after the current sample (≤ one sample duration, typically 8 s).
- **Pool rotation** — stop signal sent; the rotation completes cleanly.

The stop request is **persisted server-side**: reloading or leaving the page does not reset it — the banner stays on "Stop requested…" until the test actually stops.

### AirVPN server picker

On **Servers → + Add AirVPN servers**: a modal loads live data from the [AirVPN API](https://airvpn.org/?referred_by=483746) (5-min server-side cache). Four tabs:
- **Servers** — full list with color-coded load bar (green/orange/red), user count, health status, sortable columns, real-time search
- **By country** — collapsible sections per country with flag emoji, 🏆 **Best** badge on the least-loaded server, "Select all" button per country
- **⭐ Recommended** — servers matching the pre-selection criteria: load < 70 % and AirVPN advertised bandwidth ≥ 5 Gbit/s; green badge showing the count. Real peering between your access link and the VPN server is not known at import time: Companion approximates it later through benchmarks (latency, jitter, loss, throughput).
- **↔ Changes** — diff since the last check: newly appeared servers (selectable for instant add), disappeared servers, load shifts ≥ 10 % (with ↑↓ arrow and delta badge), top 5 countries ranked by healthy-server percentage then average load

Servers already in the database are grayed out with their checkbox disabled. The search bar filters all tabs simultaneously. Multi-select, one-click add.

### Quick check before benchmark *(option)*

Enable via **Settings → Measure → Avoid unnecessary tests**.

When enabled, each cycle starts with a speed test of the **currently active server only** — before stopping any containers or restarting Gluetun:

- **Within threshold (default ±15%)**: the full benchmark is skipped. No containers are stopped, Gluetun is not restarted, no VPN interruption. Cycle completes in seconds.
- **Outside threshold**: the full benchmark runs normally — all servers are tested, the best one is selected.

> **Implementation**: the quick check runs **exclusively via the Gluetun HTTP proxy** — no sidecar container is created, no VPN reconnection wait. Result in 10–15 seconds.

This is ideal for frequent scheduling intervals (e.g. every 2–3 hours) where you want a sanity check without the cost of a full benchmark every time.

> The threshold is configurable (1–100 %). A value of 15 means: if the current speed is between 85 % and 115 % of the last known result, the full benchmark is skipped.

### Time optimization *(option)*

Enable via **Settings → Measure → Optimize the time**.

Companion analyses the test history to compute, for each hour of the day (0–23), the **average download speed** and **coefficient of variation** (CV = σ/μ). An hour with high speed and low variance is a good benchmark window — measurements are representative and reproducible there.

**Score per hour** = `avg_speed × max(0, 1 − CV/100)`

- 🟢 **Good window** — score ≥ 70 % of the maximum
- 🔴 **Avoid** — score < 50 % of the maximum

**When it's useful**: if your ISP throttles bandwidth at certain hours (e.g. evening congestion), or if the VPN servers you use are significantly more loaded at certain times of day. In that case, benchmarking during off-peak hours gives measurements that better reflect real-world usage.

**When it adds no value**: if your network is stable 24/7 and your VPN servers have a relatively constant load, this option won't make a practical difference. It doesn't change *which* server is fastest — only *when* you measure it.

**Requirements**: at least **6 tests** in at least **8 different hour slots**. Results stabilise after several days of automatic benchmarks. Below this threshold, per-hour averages are too sensitive to outliers to be reliable.

**Auto-shift** *(sub-option)*: if a scheduled cycle falls on an unfavorable hour, the benchmark is deferred by up to 3 h to the next favorable window. If none is found within that delay, the benchmark runs immediately. Once complete, the scheduler resumes its normal interval.

**Optimal window stability**: the best hour is only confirmed and notified after **two consecutive cycles** pointing to the same hour. This prevents false alerts caused by statistical noise (previously, a single exceptional measurement was enough to trigger a window change notification).

> This option complements the automatic cycle — it does not replace it. The configured interval remains the reference; the adaptive shift only adjusts the next trigger if the hour is deemed unfavorable.

### Smart benchmark selection *(recommended for large catalogues)*

Enable via **Settings → Measure → How many servers to test**.

Two modes are available:

- **Test everything** — exhaustive mode: every compatible active server participates in the cycle. Useful to build an initial baseline, but very long with catalogues such as NordVPN.
- **Smart selection** — recommended mode: Companion tests the **N best known servers** for the active usage profile, adds a few **never-tested** servers, then refreshes a few results older than X days.

Configurable quotas are under **Advanced smart selection options**:

- **Known top** — number of already-measured servers to keep according to the usage profile.
- **New** — number of never-benchmarked servers to explore in each cycle.
- **Old after d** + **Refresh** — minimum age and number of old results to recheck.

Set a quota to `0` to disable that part. The dashboard reminds you which mode is used, the estimated server count, and the test mode (`sidecar` or `proxy`) before a manual launch.

#### Pyramidal continuous observation

Enable via **Settings → Measure → How many servers to test → Pyramidal continuous observation**.

This mode makes usage profiles serious without running a huge benchmark every time. It turns the automatic cycle into progressive data collection:

- **Exploration** — tests a batch of never-measured servers, rotating through the list day by day.
- **Confirmation** — retests servers that already have a few measurements, up to the “confirmed” threshold.
- **Finalists** — focuses repeated measurements on the best candidates that do not have enough history yet.
- **Refresh** — rechecks a few mature servers whose measurements have become old.

In continuous observation, Companion does not run quick check, does not stop the containers configured in “Containers to stop during benchmark”, and does not automatically switch servers. The goal is to build useful history, not to disturb normal usage.

The dashboard shows live observation state: current server, next server, cycle progress, the latest Companion activity lines, and a direct link to `/history` to review stored results. An internal watchdog regularly checks that observation resumes after a restart or when the regular automatic benchmark cycle is paused.

If the regular automatic cycle is also enabled, it keeps a different goal: compare the configured selection at a regular interval and, if auto-switch is enabled, move Gluetun to the best server. When a scheduled cycle becomes due during continuous observation, Companion pauses observation, runs the normal full benchmark (including pausing configured containers), then resumes observation through the watchdog. Pool rotations and manual tests (quick or full) also have priority: they interrupt the current observation run, execute, then observation resumes if needed.

Usage profiles should not be treated as instant magic: with one or two measurements, they are only an indication. They become genuinely meaningful once servers have several full benchmarks, ideally at different hours.

### Allowed servers before benchmark *(option)*

Enable via **Settings → Measure → Which servers are allowed**.

These rules reduce the list before a full benchmark. Excluded servers remain visible in `/servers` and can still be tested manually.

By default, the benchmark tests **all** enabled entries in `/servers`, regardless of their Gluetun type. With **Allowed Gluetun types**, you select exactly which types will participate in each cycle:

| Type | Gluetun variable | Typical use |
|---|---|---|
| **Name** | `SERVER_NAMES` | Individual AirVPN servers, precise name |
| **Country** | `SERVER_COUNTRIES` | Broad geographic selection |
| **City** | `SERVER_CITIES` | Precise geographic selection |
| **Region** | `SERVER_REGIONS` | Region / state |
| **Hostname** | `SERVER_HOSTNAMES` | FQDN hostname |

- **All checked** (default): identical behaviour — no filtering.
- **Some checked**: only entries of the checked types are tested; the others remain in `/servers` and can be tested individually via the "Test now" button.

> Useful if you have `country`/`region` entries as fallback but only want to test them occasionally, without including them in every automatic cycle.

### Avoid loaded AirVPN servers *(option, dedicated to [AirVPN](https://airvpn.org/?referred_by=483746))*

Enable via **Settings → Measure → Which servers are allowed → Avoid loaded AirVPN servers**.

When you have added a large number of **[AirVPN](https://airvpn.org/?referred_by=483746)** servers (type `SERVER_NAMES`), a full benchmark cycle can take a very long time. This pre-filter lets you **automatically skip overloaded servers** at the start of each cycle:

- **Max load (%)** — `0` = disabled. E.g. `70` → servers showing more than 70% load in the AirVPN cache are skipped for this cycle.
- **Max users** — `0` = disabled. E.g. `30` → servers with more than 30 connected users are skipped.

The two thresholds are independent and cumulative — a server is skipped as soon as **at least one** enabled threshold is exceeded.

**Data source**: the internal `airvpn_snapshot` table, updated every **5 minutes** from the `airvpn.org/api/status/` API. No extra API call is made at benchmark launch.

**Servers without data**: a `name`-type server with no entry in the snapshot (non-AirVPN provider, server absent from the API) is **never filtered** — it is always included in the benchmark.

**Scope**: this filter only applies to `name`-type servers (**[AirVPN](https://airvpn.org/?referred_by=483746)**). Entries of type `country`, `city`, `region`, `hostname` are never affected.

> Skipped servers remain in `/servers`, can be tested manually, and will be candidates again in the next cycle if their load has dropped in the meantime.

### Docker events listener

A daemon thread starts with Companion and continuously monitors the Docker event stream filtered to the Gluetun container. On every `start` event received:

```
Docker "start" event received on the Gluetun container
  ├─ Companion-initiated restart? (180 s suppression window)   → silently ignored
  ├─ Cooldown active? (5 min since last trigger)               → ignored
  ├─ Benchmark already running?                                → ignored
  └─ OK — schedule a deferred quick check
       1. Wait N seconds (= "Connection wait" setting)
          to allow the VPN to reconnect
       2. Quick check via HTTP proxy on the active server
          ├─ VPN not ready yet (no proxy response)
          │    → log warning, abort
          ├─ No baseline result in the database yet
          │    → result saved as new baseline, done
          ├─ Speed within ±N% threshold
          │    → log OK, done
          └─ Drift detected (speed outside threshold)
               ├─ Auto-switch enabled → immediate full benchmark
               └─ Auto-switch disabled → log warning only
```

**Companion restart suppression**: when Companion switches to a server (`switch_server()`), it opens a 180-second suppression window. Any `start` event received during that window is ignored — this prevents an infinite loop where Companion would trigger a quick check after every switch it just initiated.

**Badge in history**: tests triggered by a Docker event are tagged `docker_event` in the database. A dark `auto` badge appears on the corresponding row in the History page (`/history`), with an explanatory tooltip.

**Requirements**: the Docker socket (or Tecnativa proxy) must be accessible from Companion, and the `GLUETUN_CONTAINER` variable must match the exact name of the Gluetun container.

### Per-server confidence score

A color indicator is shown on the **Servers** page (*Confidence* column) and in **History** for each server. It reflects how reliable the accumulated measurements are.

| Level | Conditions |
|---|---|
| 🟢 High | ≥ 5 measurements **and** variability < 40 % |
| 🟡 Moderate | 2–4 measurements or variability 40–70 % |
| 🔴 Low | ≤ 1 measurement, variability > 70 % or consecutive failures |

**Variability** (coefficient of variation) is the standard deviation of speeds divided by the mean: 0 % = identical results every test, 100 % = very scattered results. Quick check tests (`proxy_qc`) are excluded from the calculation.

The score lightly influences automatic server selection: HIGH × 1.0 · MEDIUM × 0.95 · LOW × 0.85 applied to the weighted score.

### Usage profiles

Companion provides 6 **usage profiles** selectable from the **Servers** page (pill bar) or from **Settings → Decide → Usage profile**.

The active profile determines **how the best server is selected** at the end of each benchmark cycle, by weighting the measured metrics differently.

Important: a usage profile is only reliable when enough history exists. At first, Companion can mostly compare available throughput; latency, jitter, packet loss, upload, DDL single-stream speed, and stability become truly discriminating only after several full benchmarks per server. To build that history without looping over the whole catalogue, use **pyramidal continuous observation** in **Settings → Measure**.

| Profile | Primary criterion | Typical use |
|---|---|---|
| **Balanced** (default) | Existing weighted score (speed + history + stability) | General use — identical behavior to before |
| **Gaming** | Low latency + low jitter | FPS, MMO, competitive games |
| **BitTorrent** | Maximum multi-stream upload | qBittorrent, Transmission, Deluge |
| **DDL (single-stream)** | Single-stream download throughput | Usenet (SABnzbd), direct downloaders (JDownloader) |
| **Download (multi-stream)** | Maximum multi-stream download | Radarr/Sonarr, large file transfers |
| **Video streaming** | Stable throughput + low jitter | Jellyfin, Plex, direct play |

**Algorithm**: for each result from the current benchmark cycle, Companion computes the `_weighted_score` (speed + history + stability), then min-max normalises [0,1] all results on each axis. The weighted combination of normalised scores determines the best server for the active profile. The **Balanced** profile reproduces the exact previous behavior — no regression.

**DDL profile and single-stream test**: the DDL profile leverages an additional metric, **single-stream download speed** (`dl_single_mbps`), measured after the main test (VPN connection already established, no reconnect overhead). This test is **optional** and disabled by default — enable it via **Settings → Measure → Speed measurement → Single-stream test (DDL)**.

**Servers page**: the profile pill bar displays the **best server for the active profile** (computed from historical averages). The recommended server is highlighted with a 🏆 badge on its row (hidden in Balanced mode).

**Explainable score**: each server in the table view has a 📊 button (chart icon) next to its name. Clicking it opens a popover showing each metric's contribution to the final score — download speed, upload, latency, jitter, packet loss — as weighted progress bars with the raw measured values. Only metrics actually used by the active profile are displayed.

**Scoring time window**: by default, the averages used to rank servers are computed over the **last 30 days**. This can be adjusted in **Settings → Decide → Scoring window**: 7 d, 14 d, 30 d, or all data. A shorter window favours recent performance; a longer window smooths out one-off spikes.

**Outlier detection**: enable in **Settings → Decide → Filter outlier values**. When active, isolated measurements that are clearly out of range are excluded from averages and scoring — they remain visible in the history. Concrete example: if a server normally delivers 80–100 Mbps but one exceptional test returns 5 or 200 Mbps (transient spike, momentary saturation, failed test), that value is excluded from calculations. The IQR method automatically determines the normal range per server and per metric (speed, latency, jitter…) with no threshold to configure. Requires at least 4 measurements per server to take effect.

### VPN profiles (WireGuard & OpenVPN)

VPN profiles let you manage multiple VPN providers or identities — over WireGuard as well as OpenVPN — in a single Companion instance, with automatic optimised switching between them. All 24 providers from the [Gluetun wiki](https://github.com/qdm12/gluetun-wiki/tree/main/setup/providers) are integrated (see the [provider table](#multi-provider-wireguard--openvpn)).

#### Creating a profile

In **Settings → VPN profiles**:

1. Choose a provider from the dropdown → credential fields appear dynamically based on what Gluetun requires for that provider
2. If the provider supports both, choose the **connection type** (WireGuard or OpenVPN) — the fields adapt to the selected type
3. Fill in the fields (private key, OpenVPN credentials, etc.) — fields marked 🔒 are encrypted before storage
4. Name the profile (e.g. "Mullvad — Sweden", "PIA — OpenVPN US")
5. The *Active* and *Rotation allowed* toggles include or exclude the profile from automatic cycles

> **Secret security**: encrypted values are stored with the prefix `enc:` in the database. They are only decrypted at the moment the Compose override is written or a sidecar container is launched — never exposed in logs or configuration exports.

#### OpenVPN profiles

Depending on the provider, an OpenVPN profile carries:

- **Credentials** — `OPENVPN_USER` / `OPENVPN_PASSWORD` (most providers: ExpressVPN, IPVanish, NordVPN, PIA, Surfshark, TorGuard, VyprVPN…); note that several providers use *service* credentials distinct from the website login (NordVPN, ProtonVPN, Surfshark, Windscribe)
- **Client certificate and key** — CyberGhost, VPN Unlimited and AirVPN (OpenVPN) additionally (or instead) require a client certificate and key: paste the base64 body **as a single line**, without the `BEGIN`/`END` markers, into the `OPENVPN_CERT` / `OPENVPN_KEY` fields — no file mount needed
- **Encrypted key + passphrase** — SlickVPN and VPN Secure use an encrypted client key (`OPENVPN_ENCRYPTED_KEY`) with its passphrase (`OPENVPN_KEY_PASSPHRASE`)

On switch, Companion writes `VPN_TYPE=openvpn` and the `OPENVPN_*` variables to the Compose override, blanking credentials from other providers/types to prevent any leak. In sidecar mode, OpenVPN profiles are tested with their own credentials (no dedicated sidecar key — most providers allow several simultaneous connections per account).

The **Custom OpenVPN** mode (`VPN_SERVICE_PROVIDER=custom` + `VPN_TYPE=openvpn`) covers any provider missing from the Gluetun catalogue. Under **Settings → VPN profiles → Custom OpenVPN configurations**, Companion can upload a `.ovpn` or `.conf` file, detect files already mounted in Gluetun, list them, and automatically create the matching profile.

The same host directory must be mounted in both containers:

```yaml
# Gluetun Compose
services:
  gluetun-airvpn:
    volumes:
      - /home/aerya/docker/gluetun/openvpn:/gluetun/openvpn:ro

# Companion Compose
services:
  gluetun-companion:
    volumes:
      - /home/aerya/docker/gluetun/openvpn:/openvpn
    environment:
      - OPENVPN_CONFIG_DIR=/openvpn
      - OPENVPN_CONTAINER_DIR=/gluetun/openvpn
```

Uploaded files therefore appear in Gluetun as `/gluetun/openvpn/profile-name.ovpn`. Detection can also inventory other `.ovpn` or `.conf` files already available below `/gluetun`, without `docker exec`.

As documented by Gluetun, any companion files referenced by the configuration (`ca.crt`, key, script, etc.) must also be mounted below `/gluetun` and referenced with absolute paths. If the `remote` directive contains a hostname, replace it with an IP address so Gluetun's startup firewall does not require an initial DNS resolution.

#### Custom WireGuard: personal single server

The **Custom WireGuard** provider is for Gluetun `VPN_SERVICE_PROVIDER=custom` setups, especially when you have one personal WireGuard server or a provider with no Gluetun server catalogue.

In this mode, Companion does **not set any `SERVER_*` variable** (`SERVER_NAMES`, `SERVER_COUNTRIES`, etc.). The custom profile fields describe the single WireGuard endpoint directly:

- `WIREGUARD_ENDPOINT_IP`
- `WIREGUARD_ENDPOINT_PORT`
- `WIREGUARD_PUBLIC_KEY`
- `WIREGUARD_PRIVATE_KEY`
- `WIREGUARD_ADDRESSES`
- `WIREGUARD_PRESHARED_KEY` if your configuration uses one

The row added in **Servers** becomes only a statistics label, for example `Personal server`, `Home-WG` or `VPS-Paris`. It lets Companion attach benchmarks, history, Prometheus and Grafana metrics to that server without comparing it against other destinations.

Recommended setup:

1. Create a **Custom WireGuard** profile in **Settings → VPN profiles**.
2. Copy the values from your WireGuard `.conf` file into the profile fields.
3. Add one entry in **Servers** with any clear label.
4. Assign that entry to the Custom WireGuard profile.
5. Let scheduled observation or benchmarks measure that server regularly.

On switch, Companion writes `VPN_SERVICE_PROVIDER=custom`, `VPN_TYPE=wireguard` and the `WIREGUARD_*` variables to `docker-compose.override.yml`, while leaving all `SERVER_*` variables empty.

#### ⚠️ Per-profile WireGuard sidecar key (recommended)

> **If you use sidecar mode for WireGuard benchmarks, the most reliable setup is to give each WireGuard profile its own dedicated sidecar identity. Companion can also, as an advanced option, reuse the main profile WireGuard configuration.**
>
> This section only applies to **WireGuard** profiles: OpenVPN profiles are tested directly with their own credentials (the *Dedicated sidecar key* section is hidden for them).

**Why this is recommended:** sidecar test containers clone the environment of your main Gluetun container, including its `WIREGUARD_PRIVATE_KEY`. When a test container initiates a new WireGuard handshake using the same key from a different IP address, some VPN providers update the peer routing… and your main Gluetun tunnel may drop.

**Why there is no global key:** an AirVPN key cannot authenticate against Mullvad or Proton, and vice-versa. A shared sidecar key across multiple providers is inherently invalid — each profile must carry its own configuration.

**Solution:** in **Settings → VPN profiles**, edit each profile and fill in the *Dedicated sidecar key* section:
- **Sidecar private key** — a new private key generated from the same provider as the profile (e.g. `wg genkey` for providers that support it, or from your client account)
- **Sidecar IP address** — the IP address assigned to this key by your provider (CIDR format, e.g. `10.x.x.x/32`)
- **Sidecar pre-shared key** — only if your provider requires one

**AirVPN / device case:** exporting the same AirVPN device again normally returns the same `PrivateKey`, `PresharedKey`, and `Address`. To get a different triplet dedicated to the sidecar, create a second AirVPN device/peer, even if it represents the same physical home server.

**Advanced option:** enable *Reuse the main profile WireGuard configuration* if you accept the sidecar using the same WireGuard identity as the main Gluetun instance. This is convenient for providers that tolerate it, but it may disturb the main tunnel with others.

If a profile has neither a dedicated sidecar key nor the reuse option enabled, its servers are **skipped** in sidecar mode (no failure recorded — they are simply excluded from the cycle). If the proxy fallback is enabled, they automatically fall back to proxy mode instead.

#### Server ↔ profile assignment

On the **Servers** page:

- The *Provider* column shows the VPN profile assigned to each server
- If no profile is assigned, a dropdown lets you assign one directly from the table
- The `?profile=<id>` filter (dropdown in the filter bar) limits the display to servers from a given profile or to unassigned servers (`__none__`)
- Servers without a profile when at least one profile is configured are flagged as *(orphan servers)*

#### Multi-profile benchmark — execution flow

```
Benchmark cycle with VPN profiles
  ├─ Load and decrypt credentials (WireGuard or OpenVPN)
  │    for each distinct profile_id in the server list
  │    → in-memory cache for the duration of the cycle (decrypted secrets, not persisted)
  └─ For each enabled server:
       1. Retrieve extra_env from the associated profile
          (VPN_SERVICE_PROVIDER, VPN_TYPE, WIREGUARD_* or OPENVPN_*)
       2. Sidecar mode:
          ├─ OpenVPN profile → sidecar container launched with the profile credentials
          │   (most providers allow several simultaneous connections)
          ├─ WireGuard profile with a dedicated sidecar key → sidecar launched with sidecar key
          │   (prevents peer conflict with the main Gluetun tunnel)
          ├─ WireGuard profile allowing reuse → sidecar launched with main profile vars
          └─ WireGuard profile with no sidecar key and no reuse → server SKIPPED for this cycle
             (if proxy fallback enabled → tested in proxy mode instead)
       3. Proxy mode: test via Gluetun HTTP proxy (no sidecar container)
  └─ Select the best server according to the rotation policy:
       ├─ none        → constrained to the profile of the currently active Gluetun server
       ├─ conditional → cross-profile switch if gain > threshold (default 10 %)
       └─ free        → global best across all profiles
  └─ Gluetun switch:
       → writes VPN_SERVICE_PROVIDER + VPN_TYPE + credentials to the Compose override
         (credentials from other providers/types are blanked)
       → docker compose up -d (single Gluetun restart)
```

#### Rotation policy

| Mode | Behavior |
|---|---|
| **none** | Companion finds the best server within the currently active profile. If no results are available for that profile (all excluded, all orphaned), no switch occurs. |
| **free** | All tested servers are candidates — the global best is selected regardless of profile. |
| **conditional** | Benchmark is global, but a cross-profile switch only happens if `score_global_best > score_best_in_current_profile × (1 + threshold/100)`. Otherwise the best server in the current profile is retained. |

> The `conditional` threshold is configurable from 1 to 100 % in Settings. A threshold of 10 % means: "only switch profiles if the gain exceeds 10 %".

---

### Rotation pools

Rotation pools let you switch to a server from a predefined group **without triggering a full benchmark**. Accessible from the **Rotation** page in the navigation bar.

#### Creating a pool

In **Rotation → New pool**:

1. Give the pool a name (e.g. "Gaming FR", "Fallback EU")
2. Choose the **selection mode**:
   - 🎲 **Random** — `random.choice()` from the candidates
   - 🔄 **Round-robin** — alphabetical cycle with a persistent cursor between rotations
   - 🏆 **Best historical download** — candidate with the highest historical average download speed
3. Add one or more **criteria** to build the **candidate servers**:
   - `All active servers` — includes every enabled server in Companion
   - `Specific server` — type the exact name; autocomplete suggests existing servers
   - `Gluetun filter type` — choose the variable (`SERVER_COUNTRIES`, `SERVER_NAMES`, etc.) and optionally a value (empty = all servers of that type)
   - `VPN profile` — all servers assigned to a specific WireGuard or OpenVPN profile
   - `Top N by metric` — adds or restricts using the best historical download, jitter, packet loss or DNS metrics
   - `Minimum AirVPN bandwidth` — adds AirVPN servers whose advertised capacity (`bw_max`) is at least the chosen value
4. Choose how rules are combined:
   - **Add the results of each rule** — each rule adds servers; duplicates are merged automatically.
   - **Keep only servers matching every rule** — stricter, useful for "France + AirVPN profile + Top download".
5. Add **pool exclusions** if needed: these servers remain active in Companion, but this pool will never pick them.
6. Set an optional **final limit**: if specified, only the N best historical download speeds remain eligible after rules and exclusions.
7. Configure the **schedule**: automatic rotation every N hours (disabled = manual only)
8. Enable **Measure after switch** to record speed after each rotation. This measurement is not used to choose the server.

The preview updates in real time inside the modal: candidates before exclusions, excluded servers, usable servers and optional final limit.

#### Rotation execution flow

```
Rotation triggered (manual or automatic):
  1. Resolve candidates
     ├─ rules added together or intersected depending on the selected mode
     ├─ explicit pool exclusions removed
     ├─ known tracker-incompatible servers removed (if enabled)
     └─ final limit by historical download speed (if set)
  2. Pick target server (random / round-robin / best historical download)
  3. switch_server() → write docker-compose.override.yml + docker compose up -d
     └─ If a VPN profile is attached: inject VPN_SERVICE_PROVIDER, VPN_TYPE and WIREGUARD_* or OPENVPN_* into the override
  4. Wait for VPN reconnection + recreate `network_mode: service:gluetun` containers
  5. If post-switch measurement is enabled:
     ├─ Wait for VPN reconnection (connection_wait_seconds)
     ├─ Quick proxy test (proxy_qc)
     └─ Record in speed_tests (test_trigger='pool_rotation')
  6. Update pool state (last_rotated_at, next_rotation_at, last server, last speed/error, round-robin cursor)
  7. Discord/Apprise notification (if enabled)
```

#### Automatic scheduling

The scheduler checks every **5 minutes** whether any pool has a pending rotation (`next_rotation_at <= now`). If a benchmark is running, the rotation is deferred to the next tick without modifying `next_rotation_at`.

> Pool rotations and benchmarks share the same operational lock: a rotation will not trigger during an active benchmark, and vice versa.

When at least one automatic rotation pool is active, the classic automatic cycle in **Settings → Measure** is paused: the toggle is disabled in the UI, manual benchmarks remain available, and pool rotations become the primary scheduler. This pause **persists across container restarts**: Companion detects active pools at startup and will not re-enable the benchmark cycle even if `auto_benchmark=1` remained in the database.

Pool rotations are visible on the dashboard `/` and in `/history`. A switch appears as pool activity; if **Measure after switch** is enabled, the `proxy_qc` test also gets the `pool` badge.

#### Pool rotation notifications

| Type | Severity | Content |
|---|---|---|
| 🟡 Pool rotation | Medium | Pool name, trigger (auto/manual), previous → new server, speed if post-switch measurement is enabled, public IP |

---

### Selection score — stability components

The final selection score now integrates **four reliability components**, all scaled by the *Speed vs stability* slider (Settings):

```
score = (w_cur × current_dl + w_hist × exp_history)
        × confidence_factor
        × effective_stability

effective_stability = 1 − (stability_weight/100) × (1 − raw_stability)

raw_stability = jitter_factor × loss_factor × reconnect_factor
```

| Component | Source | Max penalty |
|---|---|---|
| **Jitter** | Measured each test (jitter_ms) | −15 % at 150 ms |
| **Packet loss** | Measured each test (packet_loss_pct) | −25 % at 10 % loss |
| **Involuntary reconnects** | Docker events over 30 d (test_trigger=docker_event) | −10 % per reconnect, max −30 % |
| **Confidence** (historical variance) | Coefficient of variation over all tests in the scoring window (proxy_qc excluded) | −15 % (LOW) · −5 % (MEDIUM) |

**Speed vs stability slider** (Settings → Decide):
- **0** — speed only, all stability penalties disabled
- **30** (default) — 30 % of the max penalties applied
- **100** — full penalties — a 300 Mbps server with 3 involuntary reconnects + high jitter can lose up to ~40 % of its score

> A 200 Mbps server with no reconnects and stable jitter will be preferred over a 300 Mbps server that disconnects every hour, as soon as `stability_weight ≥ ~20`.

### Hourly patterns view (`/history/patterns`)

Accessible from **History → Hourly patterns**, this view shows average performance by hour of day (0h–23h) for a selected server.

- Bar chart color-coded by performance relative to the server's best hour: 🟢 ≥ 85 % · 🟡 65–85 % · 🟠 45–65 % · 🔴 < 45 %
- Hours displayed in local time (respects the `TZ` environment variable)
- Best and worst hour shown in stat cards
- Quick checks (`proxy_qc`) excluded
- **Visualisation only** — this view does not influence the scheduler. The [Time optimization](#time-optimization-option) setting in Parameters is what uses this data to shift automatic benchmarks.
- Useful for checking whether a specific VPN server shows meaningful performance variation by hour of day

### New AirVPN server detection

**Disabled by default**, AirVPN users only. Enable in **Settings → Notifications**.

**How it works:**
1. Every 24 h, Companion fetches the server list from `airvpn.org/api/status/`
2. It identifies which countries your configured (name-type) servers belong to
3. Any new server that appears in one of those countries is stored in the database for 7 days

**UI surfaces:**
- **Badge** `+N` on the *Add AirVPN servers* button (Servers page)
- **Dismissable banner** at the top of the Servers page: *"3 new servers available in your countries (NL, FR)"* with a link to the modal
- **Changes tab** in the add modal: *New servers detected* section with ⭐ *New* badge and checkbox for direct one-click add; unified search filter

**Discord/Apprise notification:**
Sent only when new servers are discovered, grouped by country. Uses the global *Discord mention* field (see [Contextual notifications](#contextual-notifications)).

> After 7 days, servers leave the "new" list automatically. Servers you add to your list no longer appear in the badge/banner.

### Contextual notifications

Companion sends targeted alerts via **Discord webhook** and/or **[Apprise](https://github.com/caronc/apprise/wiki)** based on events. Each alert type can be toggled independently in **Settings → Notifications**.

| Alert type | Severity | On by default | Trigger |
|---|---|---|---|
| 🔴 Server auto-exclude | Critical | ✅ | A server is disabled after N consecutive failures |
| 🔴 Benchmark with no results | Critical | ✅ | A full cycle completes with no valid results |
| 🟡 Automatic switch | Medium | ✅ | Companion switches to a faster server |
| 🟡 New AirVPN servers | Medium | *(depends on AirVPN detection)* | New servers detected in your countries |
| 🔵 Manual switch | Info | ❌ | Switch triggered manually from the UI |
| 🔵 Benchmark complete | Info | ❌ | Benchmark cycle finished successfully |
| 🔵 Already on best | Info | ❌ | Active server is already the best — no change |
| 🔵 Quick check result | Info | ✅ | Manual quick benchmark completed (server, speed, delta vs baseline) |
| 🔵 Catalogue changes | Info | ❌ | Servers added or removed during a catalogue refresh (per-provider detail) |
| 🔵 Optimal window changed | Info | ❌ | The global optimal benchmark hour has changed (based on historical patterns) |

**Global Discord mention**: a single `Discord mention` field (e.g. `<@123456789>` for a user, `<@&987654321>` for a role) applies to all alerts. A severity threshold is configurable:
- **Critical only** (default) — mention only for 🔴 alerts
- **Medium and critical** — mention for 🔴 and 🟡
- **All** — mention for all alerts

> The mention is injected into the Discord payload via `allowed_mentions` to guarantee delivery even on servers with mention restrictions.

---

### Jitter & Packet Loss

Every test automatically measures the **stability** of the VPN connection, in addition to throughput.

**Measurement method:**
- **Proxy mode** — 21 TTFB (Time To First Byte) probes spread across 3 targets (Cloudflare, Google, Quad9). Variance of response times yields jitter; failed requests yield the loss rate.
- **Sidecar mode** — the sidecar container's `/ping` endpoint performs ICMP pings to the same 3 targets (20 packets each). Falls back to None gracefully if the sidecar version doesn't support `/ping`.

**Metrics produced:**
- `jitter_ms` — standard deviation of response times (ms) — represents variability/instability
- `packet_loss_pct` — percentage of lost requests/packets
- `ping_min_ms` / `ping_max_ms` — best and worst response times

**UI surfaces:**
- **Servers page** — *Stability* column: colored dot 🟢 (jitter < 15 ms, loss < 1 %) / 🟡 (< 50 ms, < 5 %) / 🔴 (above), tooltip with detailed values
- **History** — *Jitter* and *Loss* columns with the same color coding per row
- **Hourly patterns** — each bar's tooltip includes the average jitter for that hour

**Integration into selection score:**
The score is multiplied by a cumulative penalty factor:
- Jitter: `max(0.85, 1 − jitter_ms / 1000)` → up to −15 % penalty
- Loss: `max(0.75, 1 − packet_loss_pct / 40)` → up to −25 % penalty

> A fast but unstable server will be ranked below a slightly slower but consistent one.

### Prometheus `/metrics` Endpoint

The `GET /metrics` endpoint exposes key metrics in Prometheus text format, with no external dependencies.

**Available metrics** (per server):
- `gluetun_companion_server_avg_dl_mbps` — average download throughput (full benchmarks only, `proxy_qc` excluded)
- `gluetun_companion_server_avg_ul_mbps` — average upload throughput
- `gluetun_companion_server_avg_latency_ms` — average latency
- `gluetun_companion_server_test_count` — total number of tests
- `gluetun_companion_server_failure_count` — number of failed tests
- `gluetun_companion_server_consecutive_failures` — current consecutive failures
- `gluetun_companion_server_enabled` — 1 if enabled for benchmarking
- `gluetun_companion_server_active` — 1 if this is the currently active Gluetun server
- `gluetun_companion_server_last_benchmark_ts_seconds` — Unix timestamp of the last recorded test

Server metrics include `server`, `provider` and `profile` labels, so Grafana filters update automatically when you add servers, providers or VPN profiles.

**Global metrics**:
- `gluetun_companion_switches_total` — total number of switches
- `gluetun_companion_switches_success_total` — successful switches
- `gluetun_companion_benchmark_running` — 1 if a benchmark is currently running
- `gluetun_companion_benchmark_total_servers`, `gluetun_companion_benchmark_done_servers`, `gluetun_companion_benchmark_remaining_servers` — progress of the current benchmark/observation cycle
- `gluetun_companion_continuous_observation_enabled`, `gluetun_companion_continuous_observation_running` — continuous observation state
- `gluetun_companion_rotation_pools_total`, `gluetun_companion_rotation_pools_enabled`, `gluetun_companion_rotation_pools_auto_enabled` — global pool counters
- `gluetun_companion_rotation_pool_last_speed_mbps`, `gluetun_companion_rotation_pool_last_rotation_timestamp_seconds`, `gluetun_companion_rotation_pool_next_rotation_timestamp_seconds` — per-pool metrics with the `pool` label
- `gluetun_companion_last_switch_timestamp_seconds` — Unix timestamp of the last switch

**Authentication**: open by default (standard for internal networks). Two ways to protect `/metrics` with a Bearer token: set the `METRICS_TOKEN` environment variable, or configure an **API token** in Settings → Maintenance → REST API (both are supported; `METRICS_TOKEN` takes precedence).

**Prometheus scrape config** (add to `prometheus.yml`):
```yaml
scrape_configs:
  - job_name: gluetun-companion
    static_configs:
      - targets: ['gluetun-companion:8765']
    # If METRICS_TOKEN is set:
    # bearer_token: your-secret-token
```

---

### REST API

The API is **disabled by default**. To enable it: **Settings → Maintenance → REST API → Generate a new token**.

**Authentication**: all requests must include the header:
```
Authorization: Bearer <your-token>
```

**Available endpoints:**

| Method | URL | Description |
|---|---|---|
| `GET` | `/api/v1/status` | Active server, VPN state, benchmark running, next cycle |
| `GET` | `/api/v1/servers` | Full server list with average speed, jitter, confidence |
| `GET` | `/api/v1/history` | Test history (`?limit=50&offset=0&server=Castor`) |
| `GET` | `/api/v1/switches` | Switch history (`?limit=20`) |
| `POST` | `/api/v1/benchmark/trigger` | Trigger a full benchmark (async, HTTP 202) |
| `POST` | `/api/v1/benchmark/trigger-quick` | Trigger a quick proxy test (async, HTTP 202) |

**curl examples:**
```bash
# Status
curl -H "Authorization: Bearer <token>" http://localhost:8765/api/v1/status

# Trigger a benchmark
curl -X POST -H "Authorization: Bearer <token>" http://localhost:8765/api/v1/benchmark/trigger

# Last 10 tests for server Castor
curl -H "Authorization: Bearer <token>" \
  "http://localhost:8765/api/v1/history?limit=10&server=Castor"
```

**Response codes:**
- `200` — success (GET)
- `202` — trigger accepted (POST)
- `401` — invalid or missing token
- `403` — API disabled (no token configured)
- `409` — a benchmark is already running (POST trigger)

> POST triggers return immediately — the benchmark runs in the background. Poll `GET /api/v1/status` to track progress (`benchmark_running`).

### Automatic cycle vs manual trigger

In **Settings → Measure**: the automatic cycle can be disabled via the *Enable automatic benchmark cycle* toggle. The interval field is then grayed out. Two buttons are always available (dashboard and settings):

- **Quick benchmark** — tests only the active server via the Gluetun HTTP proxy; result in seconds, no VPN interruption, result saved in history (`proxy_qc` method).
- **Full benchmark** — runs a complete cycle immediately, regardless of the automatic cycle setting or the *Quick check* option. Uses the configured method (sidecar or proxy), shown in parentheses on the button.

> **Duration estimate**: the dashboard displays a `~min–max / server` range and an estimated total for the selection that will actually be tested, calculated from `wait_secs`, `duration`, `samples`, `retries`, the mode (proxy/sidecar), filters, and smart selection. A ⚠️ alert appears automatically if the pessimistic total exceeds 30 minutes. The same estimate is recalculated live in **Settings → Measure** after each change.

---

## Grafana dashboard

A Grafana dashboard JSON file is downloadable from **Settings**. It is pre-wired to Companion's Prometheus metrics and includes panels for:

- Download/upload throughput per server (bar gauge)
- Latency, jitter, packet loss, DNS (bar gauge)
- Confidence index and profile score (bar gauge)
- Errors by type (donut chart)
- Continuous observation: enabled/running state and cycle progress
- Rotation pools: pool count, active automatic pools, last/next rotation
- Summary table of all servers
- Automatic Grafana filters by provider, VPN profile and server

### Available Prometheus metrics

In addition to the base metrics (`avg_dl`, `avg_ul`, `avg_latency`, `test_count`, `failure_count`, `enabled`, `active`), Companion exposes:

| Metric | Description |
|---|---|
| `gluetun_companion_server_avg_jitter_ms` | Average jitter (sidecar tests only) |
| `gluetun_companion_server_avg_loss_pct` | Average packet loss |
| `gluetun_companion_server_avg_dns_ms` | Average DNS latency |
| `gluetun_companion_server_confidence` | Confidence index: 0=LOW, 1=MEDIUM, 2=HIGH |
| `gluetun_companion_server_score` | Active profile score [0–1] |
| `gluetun_companion_server_last_benchmark_ts_seconds` | Unix timestamp of the last test |
| `gluetun_companion_benchmark_total_servers`, `*_done_servers`, `*_remaining_servers` | Current benchmark/observation cycle progress |
| `gluetun_companion_continuous_observation_enabled`, `*_running` | Continuous observation state |
| `gluetun_companion_rotation_pools_total`, `*_enabled`, `*_auto_enabled` | Global pool counters |
| `gluetun_companion_rotation_pool_last_speed_mbps`, `*_last_rotation_timestamp_seconds`, `*_next_rotation_timestamp_seconds` | Per-pool metrics (`pool`) |
| `gluetun_companion_errors_total{type}` | Error counter by type: timeout, connection, vpn, other |

---

## Automated workflows

The badges at the top of the README provide a quick status view. The repository currently configures the following automations:

| Automation | Trigger | Purpose |
|---|---|---|
| [Docker build and publication](.github/workflows/docker-publish.yml) | Every PR, every push to `main`, and every `v*` tag | Builds the Companion and Sidecar images for `amd64`/`arm64`. On `main` and tags, publishes them to GHCR. On PRs, also runs an `amd64` HTTP smoke test. |
| [Dependabot](.github/dependabot.yml) | Every Monday at 06:00 UTC | Monitors Python dependencies for Companion and Sidecar, GitHub Actions, and Docker base images, then opens update PRs. |
| [Dependabot auto-merge](.github/workflows/dependabot-automerge.yml) | When a Dependabot PR is opened or updated | Requests auto-merge for `patch` updates after checks pass. GitHub's **Allow auto-merge** repository setting must be enabled; otherwise the PR remains for manual merging. Minor updates remain subject to review, while major updates are generally ignored by the Dependabot configuration. |
| [Trivy scan](.github/workflows/trivy-scan.yml) | Every Monday at 07:00 UTC, or manually | Builds and scans both images for `HIGH`/`CRITICAL` CVEs, uploads SARIF results to the Security tab, and opens either a fix PR or an issue when manual action is required. |

A successful Docker workflow means the images build and start in the smoke test. To technically prevent merging a failing PR, the relevant checks must also be configured as **required status checks** in the `main` branch protection rules.

---

## Notes

- **Sidecar mode (default):** your main Gluetun is never restarted during testing — dependent services are not interrupted. **Proxy mode (optional):** the benchmark briefly interrupts those services on each server test. Schedule during off-peak hours.
- **Frequency and server count:** each test triggers a VPN reconnection. Testing 10 servers every 2 hours = 120 reconnections/day. Most providers limit *simultaneous* connections, not frequency — but a very short interval may trigger abuse detection. **6 h and fewer than 10 servers** is a sensible default.
- In Compose mode, `docker-compose.override.yml` is managed automatically — do not edit it manually. In Unraid/DockerMan mode, Companion writes managed variables back into the Gluetun container's DockerMan template before recreation.
- IPv6 is displayed if your VPN provider supports it (AirVPN does).
- The Docker socket (`/var/run/docker.sock`) is required for sidecar mode, post-switch containers, and the benchmark pause feature.

---

## Security

- **Anti brute-force** — The login endpoint blocks an IP after 5 failures within 5 minutes for 15 minutes. No external dependency: pure in-memory sliding window.
- **CSRF** — All POST actions (forms and AJAX) are protected by a CSRF token via server-side session. The `X-CSRF-Token` header is automatically injected on every non-GET `fetch` request via a JavaScript interceptor.
- **XSS** — Third-party API data (AirVPN) injected into the DOM via `innerHTML` is always escaped by a `_esc()` helper (HTML entity encoding) before insertion. Inline `onclick`/`onchange` attributes present in dynamic components only contain JSON-encoded values or constants — no raw user data is interpolated into them.
- **SECRET_KEY** — The application refuses to start if `SECRET_KEY` is missing or equal to the default value. Generate a secure key with: `openssl rand -hex 32`.
- **Network exposure** — Gunicorn listens on `0.0.0.0:8765`. **Do not expose this port directly to the internet.** On a publicly accessible server, place Companion behind a reverse proxy (Nginx, Caddy, Traefik) with HTTPS and strong authentication, or restrict the binding to the local interface: `127.0.0.1:8765:8765` in your `docker-compose.yml`.
- **`/metrics`** — Open by default on the LAN. If your machine is reachable from outside, set the `METRICS_TOKEN` environment variable or configure an API token in Settings → Maintenance → REST API: `/metrics` will use it automatically (Bearer token required in the `Authorization` header).
- **Sidecar** — Each sidecar container (speed-test on port `8766`, catalogue on port `8767`) automatically receives a random secret generated by the Companion (`SIDECAR_SECRET`, 32 bytes of entropy via `secrets.token_hex`). Every HTTP request to the sidecar must include this secret in the `X-Sidecar-Token` header — a request without the correct token receives a `403`. The secret is unique per instance and destroyed along with the container at the end of the test. These ports must not be reachable from untrusted networks: if your host is publicly accessible, restrict the port binding or isolate them with a firewall.
- **Secrets in /settings** — The API token, proxy password, and webhook URLs are displayed in cleartext in the Settings page. Restrict access to Companion to trusted users only.
- **YAML/XML injection** — The server filter value is sanitised before being written to `docker-compose.override.yml` in Compose mode (newlines stripped, quotes and backslashes escaped). In Unraid/DockerMan mode, values are escaped before being written to the XML template, with a timestamped `.bak` backup.
- **Docker socket** — The Docker socket is secured via [docker-socket-proxy](https://github.com/Tecnativa/docker-socket-proxy), which restricts allowed calls to: read access (containers, images, networks, volumes) plus POST/DELETE for temporary sidecar management. Direct daemon access (exec, swarm, info…) is blocked.

### Docker image security

Both images (`gluetun-companion` and `gluetun-companion-sidecar`) bundle **third-party Go binaries** (Docker CLI, Docker Compose, librespeed-cli, ookla speedtest) with their own dependency chains, invisible to Python package managers. A two-layer pipeline keeps these images up to date:

**Dependabot** (already in place, runs every Monday 06:00 UTC):
- Updates **pip** dependencies for both Companion and Sidecar (automatic PRs; patch updates request auto-merge when that GitHub feature is enabled, minor updates remain under manual review)
- Tracks **Docker base images** (`python:3.12-slim`) — Python runtime security rebuilds
- Tracks **GitHub Actions** versions in CI workflows

**Trivy workflow** (`.github/workflows/trivy-scan.yml`, every Monday 07:00 UTC):
- Builds both images and scans them with [Trivy](https://github.com/aquasecurity/trivy) for HIGH and CRITICAL CVEs
- Uploads results as SARIF to the repository's **Security tab** (*Security → Code scanning*)
- If fixable CVEs are found and a newer Docker CLI image is available: **automatically opens a PR** bumping `FROM docker:XX-cli` in the Dockerfile
- If no automatic fix is possible: **opens an Issue** listing the CVEs for manual review

**Smoke test** (`.github/workflows/docker-publish.yml`, on every PR):
- Builds both images for amd64
- Starts each container with a minimal configuration and checks it responds over HTTP within 20 seconds
- Fails if an image no longer starts; it blocks merging when configured as a required check in the `main` branch protection rules

---

## Credits

Thanks to **[qdm12](https://github.com/qdm12/gluetun)** for Gluetun, without which this project would not exist.

Thanks to **[Tecnativa](https://github.com/Tecnativa/docker-socket-proxy)** for docker-socket-proxy, used to secure access to the Docker socket.

Thanks to **[brashenfr](https://github.com/brashenfr)**, **[dje33](https://github.com/the-real-dje33)**, **[lnksilver5](https://github.com/lnksilver5)**, **[prismillon](https://github.com/prismillon)**, **[Ptite Pomme](https://github.com/ptitzgeg-on-git)**, **[x0gen](https://github.com/x0gen)**, **[zlimteck](https://github.com/zlimteck)** and **[Zup](https://github.com/Gusdezup)** for their ideas and testing.

---

## License

[PolyForm Noncommercial 1.0.0](LICENSE) — free for personal and non-profit use, commercial use requires authorization.
