<p align="center">
  <img src="assets/logo.png" alt="Gluetun Companion" width="200">
</p>

# Gluetun Companion

Automatic VPN server benchmarking via [Gluetun](https://github.com/qdm12/gluetun), switches to the fastest server, full Web UI.

> 🇫🇷 [Version française](README.md)

<p align="center">
<a href="https://github.com/Aerya/Gluetun-Companion/actions/workflows/docker-publish.yml"><img src="https://github.com/Aerya/Gluetun-Companion/actions/workflows/docker-publish.yml/badge.svg?branch=main" alt="Build"></a>
<a href="https://github.com/Aerya/Gluetun-Companion/blob/main/.github/workflows/trivy-scan.yml"><img src="https://img.shields.io/badge/Trivy-enabled-1904DA?logo=aquasecurity&logoColor=white" alt="Trivy CVE scan"></a>
<a href="https://github.com/Aerya/Gluetun-Companion/blob/main/.github/dependabot.yml"><img src="https://img.shields.io/badge/Dependabot-enabled-025E8C?logo=dependabot&logoColor=white" alt="Dependabot"></a>
<a href="https://github.com/Aerya/Gluetun-Companion/pkgs/container/gluetun-companion"><img src="https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white" alt="Docker"></a>
<a href="#"><img src="https://img.shields.io/badge/arch-amd64%20%7C%20arm64-lightgrey" alt="arch"></a>
<a href="README.md"><img src="https://img.shields.io/badge/i18n-FR%20%7C%20EN-informational" alt="i18n"></a>
<a href="https://github.com/qdm12/gluetun"><img src="https://img.shields.io/badge/Gluetun-compatible-0d1117?logo=github&logoColor=white" alt="Gluetun compatible"></a>
<a href="https://airvpn.org/?referred_by=483746"><img src="https://img.shields.io/badge/AirVPN-compatible-1a7a3d?logoColor=white" alt="AirVPN"></a>
<a href="https://discord.com/developers/docs/resources/webhook"><img src="https://img.shields.io/badge/Discord-webhook-5865F2?logo=discord&logoColor=white" alt="Discord"></a>
<a href="https://github.com/caronc/apprise"><img src="https://img.shields.io/badge/Apprise-compatible-3d85c8?logo=python&logoColor=white" alt="Apprise"></a>
<a href="https://github.com/Tecnativa/docker-socket-proxy"><img src="https://img.shields.io/badge/socket--proxy-compatible-blueviolet?logo=docker&logoColor=white" alt="Docker socket-proxy"></a>
</p>

> **Using it? Liking it? [⭐ Drop a star!](https://github.com/Aerya/Gluetun-Companion/stargazers)** — takes two seconds.

---

## Compatibility

Gluetun Companion works with **any Gluetun-compatible VPN provider** as long as at least one of these filter variables is present in your configuration:

| Gluetun variable | Filter |
|---|---|
| `SERVER_NAMES` | Server name |
| `SERVER_COUNTRIES` | Country |
| `SERVER_REGIONS` | Region |
| `SERVER_CITIES` | City |
| `SERVER_HOSTNAMES` | Hostname |

Independent of tunnel technology: works identically with OpenVPN, WireGuard, or any other protocol supported by Gluetun.

Primarily designed and tested for **[AirVPN](https://airvpn.org/?referred_by=483746)** *(affiliate link)* — [AirVPN filter variables](https://github.com/qdm12/gluetun-wiki/blob/main/setup/providers/airvpn.md#optional-environment-variables).

---

## Table of contents

- [Compatibility](#compatibility)
- [Features](#features)
  - [Speed testing](#speed-testing)
  - [Server selection & automatic switching](#server-selection--automatic-switching)
  - [Multi-provider WireGuard](#multi-provider-wireguard)
  - [Gluetun server catalogue](#gluetun-server-catalogue)
  - [Docker container management](#docker-container-management)
  - [AirVPN](#airvpn)
  - [Analysis & history](#analysis--history)
  - [UI & notifications](#ui--notifications)
  - [Integration & infrastructure](#integration--infrastructure)
- [Quick start](#quick-start)
- [Environment variables](#environment-variables)
- [How it works](#how-it-works)
  - [Sidecar mode (default)](#sidecar-mode-default)
  - [HTTP proxy mode (optional)](#http-proxy-mode-optional)
  - [Quick check before benchmark](#quick-check-before-benchmark-option)
  - [Adaptive scheduling](#adaptive-scheduling-option)
  - [Benchmark filtering by entry type](#benchmark-filtering-by-entry-type-option)
  - [AirVPN pre-filter before benchmark](#airvpn-pre-filter-before-benchmark-option-dedicated-to-airvpn)
  - [Docker events listener](#docker-events-listener)
  - [Usage profiles](#usage-profiles)
  - [WireGuard VPN profiles](#wireguard-vpn-profiles)
  - [Rotation pools](#rotation-pools)
  - [Selection score — stability components](#selection-score--stability-components)
  - [Per-server confidence score](#per-server-confidence-score)
  - [Jitter & Packet Loss](#jitter--packet-loss)
  - [Hourly patterns view](#hourly-patterns-view-historypatterns)
  - [New AirVPN server detection](#new-airvpn-server-detection)
  - [Contextual notifications](#contextual-notifications)
  - [REST API](#rest-api)
  - [Prometheus /metrics endpoint](#prometheus-metrics-endpoint)
  - [Automatic cycle vs manual trigger](#automatic-cycle-vs-manual-trigger)
- [Notes](#notes)
- [Security](#security)
- [Credits](#credits)

---

## Features

### Speed testing
- **Sidecar mode** (default) — a `gluetun-companion-test` container clones the real Gluetun config for each server; `gluetun-companion-sidecar` measures speed via **Ookla + librespeed in parallel** (dual mode, default), Ookla only, librespeed only, or iperf3 directly inside the VPN tunnel; your main Gluetun is never restarted during testing
- **HTTP proxy mode** (optional) — measures speed via the Gluetun HTTP proxy with no extra containers; briefly interrupts dependent services on each server switch
- **Multi-source results** — Ookla, librespeed and iperf3 speeds stored separately and displayed in the dashboard and history
- **Multi-stream download** — N concurrent TCP connections (configurable, default: 4)
- **Automatic benchmarking** every X hours — download, upload and latency per server; automatic cycle can be disabled (manual trigger only)
- **Benchmark pre-filtering** *(option)* — select which **entry types** to include in each cycle (`SERVER_NAMES`, `SERVER_COUNTRIES`, `SERVER_CITIES`, `SERVER_REGIONS`, `SERVER_HOSTNAMES`); all types included by default; excluded servers remain in the list and can be tested manually; configurable in Settings → Benchmark filtering
- **Quick check before benchmark** *(option)* — tests only the current server before each cycle; if speed is within ±N% of the last known result, the full benchmark is skipped entirely — no containers paused, no VPN restarts; triggers the full benchmark only when performance drifts significantly
- **Adaptive scheduling** *(option)* — analyses hourly speed and variance patterns to identify the best and worst benchmark windows; recommended time slots displayed in Settings; optional auto-shift: if the next cycle falls on an unfavorable hour, it is shifted up to 3 h forward to the next favorable window
- **On-demand quick benchmark** — button always available (dashboard and settings); tests only the active server via the Gluetun HTTP proxy, result in seconds, no VPN interruption, result saved in history
- **Jitter & Packet Loss** — network stability measured at every test (21 TTFB probes in proxy mode, ICMP via sidecar); 🟢/🟡/🔴 indicator on Servers page, dedicated columns in History, jitter shown in hourly patterns; factored into selection score (up to −15 % jitter / −25 % loss penalty)
- **DNS latency** *(sidecar)* — DNS resolution time measured from inside the VPN tunnel via `dig` (4 domains in parallel, median returned); detects slow, overloaded, or hijacking resolvers; column in History, DNS shown in the Stability tooltip, data in hourly patterns
- **Docker events listener** — daemon thread watching for Gluetun container `start` events; if Gluetun restarts on its own (crash, update, watchdog), automatically triggers a quick check after N seconds (VPN reconnect delay); if speed drift exceeds the configured threshold and auto-switch is enabled, immediately runs a full benchmark; restarts triggered by Companion itself are ignored; 5-minute cooldown between triggers

### Server selection & automatic switching
- **Automatic switching** to the fastest server (`docker compose up -d`), based on a weighted score combining current speed, exponential history, jitter, packet loss and involuntary reconnects (via Docker events); configurable *Speed vs stability* slider; **6 usage profiles** (Balanced, Gaming, BitTorrent, DDL, Download, Streaming) — each profile weights metrics differently to find the server best suited to your actual use case; dependent services (`network_mode: service:gluetun`) are recreated automatically
- **Manual switch** to any configured server from the Servers page — Gluetun is reconfigured and `network_mode: service:gluetun` containers are recreated automatically
- **5 filter types**: `SERVER_NAMES`, `SERVER_COUNTRIES`, `SERVER_REGIONS`, `SERVER_CITIES`, `SERVER_HOSTNAMES`
- Configurable **retry** per server + global timeout per server
- **Auto-disable** a server after N consecutive failures

### Rotation pools

- **Rotation without benchmarking** — switch to a server from a predefined group without triggering a full measurement cycle; ideal for periodic rotation or quick one-off changes
- **Composable criteria** (UNION) — each pool accepts any number of criteria: specific server, Gluetun filter type (`SERVER_NAMES`, `SERVER_COUNTRIES`, `SERVER_CITIES`, `SERVER_REGIONS`, `SERVER_HOSTNAMES`), WireGuard VPN profile, or all active servers; criteria are combined additively
- **3 selection modes**: 🎲 random, 🔄 round-robin (persistent cursor across rotations), 🏆 best historical score
- **Top-N** — restrict the pool to the N servers with the best average score (if unset, all candidates are eligible)
- **Manual or scheduled** — instant one-click rotation from the UI, or automatic rotation on a configurable interval (in hours; e.g. every 12 h or every 2 days)
- **Optional quick bench** — after each switch, a fast proxy test measures the new server's speed and records it in the history (method `proxy_qc`)
- **Notifications** — Discord/Apprise alert on each rotation (manual or automatic), including previous server, new server, and speed if quick bench is enabled

### Multi-provider WireGuard

- **WireGuard VPN profiles** — create multiple sets of WireGuard credentials from **Settings → WireGuard VPN profiles**; each profile is linked to a provider (AirVPN, Mullvad, ProtonVPN, NordVPN, IVPN, Surfshark, Windscribe, or Custom WireGuard for any other compatible provider)
- **Secret encryption** — private keys and other sensitive fields are encrypted at rest (Fernet/AES-128, key derived from `SECRET_KEY` via PBKDF2HMAC-SHA256 with 480 000 iterations); changing `SECRET_KEY` makes existing profiles unreadable (documented behavior)
- **Server ↔ profile assignment** — on the **Servers** page, assign a VPN profile to each server via a dropdown; a *Provider* column shows the linked profile; the `?profile=` filter limits the view to a single profile or to unassigned servers
- **Orphan server alert** — a badge warns when servers have no assigned profile while at least one WireGuard profile is configured; those servers continue to work normally but cannot be selected by the multi-profile benchmark
- **Multi-profile benchmark** — in sidecar mode, each server is tested with its profile's WireGuard credentials injected into the temporary container; on the final switch, Companion automatically writes `VPN_SERVICE_PROVIDER`, `VPN_TYPE=wireguard` and all `WIREGUARD_*` variables to `docker-compose.override.yml`
- **Rotation policy** — three modes configurable in **Settings → WireGuard VPN profiles → Rotation policy**:
  - `none` — Companion always stays in the currently active profile; servers from other profiles are never selected
  - `free` — picks the best server across all profiles (default behavior without profiles)
  - `conditional` — switches to another profile only if its best server outperforms the best server in the current profile by more than N % (configurable threshold, default 10 %)
- **Provider column in `/history`** — each history row shows the WireGuard profile associated with the tested server (only visible when at least one profile is configured)

**Supported providers:**

| Provider | Type | Gluetun variables |
|---|---|---|
| AirVPN | Native | `WIREGUARD_PRIVATE_KEY`, `WIREGUARD_PRESHARED_KEY`, `WIREGUARD_ADDRESSES` |
| FastestVPN | Native | `WIREGUARD_PRIVATE_KEY`, `WIREGUARD_ADDRESSES` |
| IVPN | Native | `WIREGUARD_PRIVATE_KEY`, `WIREGUARD_ADDRESSES` |
| Mullvad | Native | `WIREGUARD_PRIVATE_KEY`, `WIREGUARD_ADDRESSES` |
| NordVPN | Native | `WIREGUARD_PRIVATE_KEY` |
| ProtonVPN | Native | `WIREGUARD_PRIVATE_KEY`, `WIREGUARD_ADDRESSES` |
| Surfshark | Native | `WIREGUARD_PRIVATE_KEY`, `WIREGUARD_ADDRESSES` |
| Windscribe | Native | `WIREGUARD_PRIVATE_KEY`, `WIREGUARD_PRESHARED_KEY`, `WIREGUARD_ADDRESSES` |
| Custom WireGuard | Via `custom` | Endpoint IP/port, public key, private key, addresses, pre-shared key (optional) |

> Custom WireGuard covers any provider not listed above (CyberGhost, PrivateVPN, PureVPN, TorGuard, VPN Unlimited, VyprVPN…) as long as they provide a standard WireGuard configuration file.

---

### Gluetun server catalogue
- **GitHub download** — the catalogue Sidecar downloads server lists directly from the public [`qdm12/gluetun-servers`](https://github.com/qdm12/gluetun-servers/tree/main/pkg/servers) repository; **no volume to mount**, no changes to your Gluetun configuration required
- **Automatic refresh** — the list is updated **at every benchmark cycle** (configurable interval in Settings → Scheduling & Cycle, default: 6 h); a dedicated button in Settings and in the `/servers` modal lets you force an immediate refresh
- **Auto-add new servers** *(option)* — when new servers appear in the catalogue for a **country**, **region** or **city** you already have configured, Companion automatically adds them to your server list (as `SERVER_NAMES` entries) without any manual action; disabled by default, enable in **Settings → Catalogue**
- **Change notifications** *(option)* — Discord/Apprise alert sent on each refresh when servers are added to or removed from the catalogue, with per-provider detail (+N/−N); enable in **Settings → Notifications**
- **3 import modes in Settings**:
  1. **All providers** — imports servers from every provider available on GitHub
  2. **Chosen provider** — imports only the servers of a provider selected manually
  3. **Active provider** — automatically detects the provider configured in your Gluetun and imports its servers only
  — for each mode, an option to **run a full benchmark** immediately after import (using the configured method in Settings, across all servers in the list)
- **All filter types** — each server is imported with its full attributes: `SERVER_NAMES`, `SERVER_COUNTRIES`, `SERVER_CITIES`, `SERVER_REGIONS`, `SERVER_HOSTNAMES`
- **Multi-filter selection from `/servers`** — select servers by freely mixing filter types (e.g. names + countries + cities at the same time); Companion applies the right filter in Gluetun and changes the filter type on the fly if needed
- ⚠️ **ProtonVPN** — Free ProtonVPN servers are available via the **Catalogue**. To access Premium servers, use **Import from Gluetun** to retrieve the servers already configured in your Gluetun compose (paid account required).

**Prerequisites** — the catalogue sidecar only needs outbound HTTPS access (Docker bridge network, enabled by default). **No `docker-compose.yml` changes required.**

### Docker container management
- **Gluetun network containers (auto-managed)** — all containers using `network_mode: service:gluetun` are detected and restarted automatically after each switch
- **Containers to restart after switch** — only for containers routing through Gluetun's HTTP/SOCKS5 proxy; ordered list (drag & drop)
- **Pause during benchmark** — list of containers (torrent, Usenet…) stopped before the benchmark starts and automatically restarted when it ends, even on error
- **Automatic Docker image updates** *(option)* — at switch time, Companion can update images before restarting containers: Gluetun itself, auto-managed network containers, post-switch containers and benchmark-paused containers; togglable per container from Settings

### AirVPN
- **Built-in AirVPN server picker** — *+ Add an AirVPN server* button on the Servers page: live data from `airvpn.org/api/status/` (5-min server-side cache), four tabs — full searchable list, geographic distribution by country, **Recommended** tab (load < 50 %, health OK, < 30 users) and **Changes** tab (newly detected servers, disappeared servers, load shifts, top 5 healthiest countries); multi-select, one-click add
- **AirVPN pre-filter before benchmark** *(optional, dedicated to [AirVPN](https://airvpn.org/?referred_by=483746))* — at benchmark start, **[AirVPN](https://airvpn.org/?referred_by=483746)** servers of type `SERVER_NAMES` whose **load** or **user count** exceeds a configurable threshold are automatically skipped; data from the AirVPN cache (updated every 5 min); servers without AirVPN data are never excluded; thresholds configurable in Settings → Benchmark filtering
- **New AirVPN server detection** *(optional)* — compares the AirVPN API with your configured servers every 24 h; badge and dismissable banner on the Servers page + *Changes* tab in the add modal; Discord/Apprise notification with optional mention

### Analysis & history
- **Per-server confidence score** — 🟢/🟡/🔴 indicator on the Servers page and in History; based on measurement count and result variability; factored into the automatic selection score (light weighting)
- **Hourly patterns** (`/history/patterns`) — 0h–23h bar chart showing average speed by hour of day, color-coded by relative performance; best and worst hour displayed; helps identify server saturation windows
- **Sortable columns** — click any column header in `/history` (11 columns) and `/servers` (8 columns) to sort; clicking again reverses the order; ▲/▼/⇅ visual indicators; sort persists across pages
- **On-demand test** of a single server from the UI without waiting for the next cycle
- **CSV export** of the full history

### UI & notifications
- **Web UI** dark/light, FR/EN — auth, dashboard with sparkline, paginated history, charts, switches page with Mbps gain and connection time
- **Contextual notifications** — 10 independently-configurable alert types (auto/manual switch, auto-exclude, benchmark with no results, benchmark complete, quick check result, pool rotation, new AirVPN servers, catalogue changes, optimal window change) via Discord webhook (rich embed) and/or [Apprise](https://github.com/caronc/apprise/wiki) (Telegram, ntfy, Gotify, Slack, Pushover…); severity levels 🔴/🟡/🔵; global Discord mention with configurable severity threshold
- **Automatic purge** of SQLite history with configurable retention (in days)

### Integration & infrastructure
- **`/healthz` endpoint** unauthenticated, for Docker healthchecks
- **`/metrics` endpoint** in Prometheus format — throughput, latency, switches, active server; optionally protected by Bearer token; Grafana-compatible
- **REST API `/api/v1/`** protected by Bearer token — VPN status, server list, history, switches, trigger full or quick benchmark; designed for Home Assistant, n8n, bash scripts
- **Structured JSON logs** optional via `LOG_JSON=1` (Loki/Grafana compatible)
- **SQLite database** (WAL) — no external dependencies

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

> **Companion in the same stack as Gluetun?**
> Remove `extra_hosts` and use the service name: `GLUETUN_HOST: gluetun`.
> On a switch, the companion only targets the Gluetun service (`docker compose up -d <service>`) — it never restarts itself.

### 4. Import servers

**Servers → Import from Gluetun**: the companion reads `SERVER_NAMES`, `SERVER_COUNTRIES`, etc. directly from the running container and imports each value with its filter type. Manual addition is also available on the same screen.

> ⚠️ **Companion benchmarks each server individually, by name.** Setting `SERVER_COUNTRIES`, `SERVER_REGIONS` or `SERVER_CITIES` adds a single entry (e.g. "France") — Companion does **not** automatically discover individual servers in that country. Add each server by its name (`SERVER_NAMES`) for benchmarking to work. **Minimum 2 named servers required.**

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `SECRET_KEY` | *(required)* | Flask session signing key |
| `GLUETUN_HOST` | `host.docker.internal` | Gluetun HTTP proxy host |
| `GLUETUN_PROXY_PORT` | `8887` | Gluetun HTTP proxy port |
| `GLUETUN_CONTAINER` | `gluetun-airvpn` | Gluetun container name |
| `COMPOSE_DIR` | `/compose` | Path (inside the container) to the Gluetun compose directory |
| `DATA_DIR` | `/data` | SQLite database directory |
| `DOCKER_HOST` | *(local socket)* | Set to `tcp://socket-proxy:2375` when using the Tecnativa socket proxy |
| `METRICS_TOKEN` | *(empty)* | If set, the `/metrics` endpoint requires `Authorization: Bearer <token>`; leave empty for open access (standard for internal networks) |

Benchmark parameters (streams, duration, warm-up, retry…) are configured in the UI → **Settings**.

---

## How it works

### Sidecar mode (default)

```
Benchmark cycle (every X hours)
  ├─ "Pause bench" containers stopped (torrents, Usenet…)
  └─ For each enabled server:
       1. Pull ghcr.io/aerya/gluetun-companion-sidecar:latest
       2. Start gluetun-companion-test
          (clone of your Gluetun, configured for the target server)
       3. Start gluetun-companion-sidecar
          (network_mode: container:gluetun-companion-test)
       4. Wait for VPN via /health polling (configurable timeout)
       5. Speed test inside the VPN tunnel (configurable engine):
          - Dual (default): Ookla + librespeed in parallel, iperf3 as fallback
          - Ookla only, librespeed only, or iperf3 only
          → DL, UL, latency recorded per source
       6. Stop + remove containers and sidecar image
       → Auto-retry on failure, global timeout per server
       → Auto-disable after N consecutive failures
  └─ Weighted score (65% current cycle + 35% exponential history)
  └─ Switch real Gluetun to the best server (one single restart)
  └─ "Post-switch" containers recreated (network namespace included)
  └─ "Pause bench" containers restarted (guaranteed — finally block)
  └─ Discord / Apprise notification (if configured)
```

**Available test engines (Settings → Sidecar Mode):**
- **Dual** (default) — Ookla + librespeed in parallel; results from both sources stored separately
- **Ookla only** — official Speedtest.net CLI, rarely blocked by VPN IPs
- **librespeed only** — librespeed-cli, public librespeed.org servers (HTTP)
- **iperf3 only** — direct TCP to public iperf3 servers (often blocked by VPN IPs)

**Fallbacks:**
- iperf3 as last resort if all primary sources fail (enabled by default)
- HTTP proxy fallback if sidecar fails entirely (disabled by default)

> ⚠ **Simultaneous connection**: sidecar mode uses one extra VPN connection slot for the entire benchmark duration. Check your provider's limits (AirVPN: 3–5 depending on plan).

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

Enable via **Settings → Sidecar Mode → toggle off**.

### Containers to restart after switch

In **Settings → Containers to restart after switch**: ordered list of containers recreated via `docker compose up -d --force-recreate` after each VPN switch. Drag & drop to reorder. Useful for `qbittorrent`, `radarr`, `sonarr`, or any service with `network_mode: service:gluetun`.

### Containers to pause during benchmark

In **Settings → Containers to pause during benchmark**: list of containers stopped before the benchmark and restarted after — in all cases, even if the benchmark crashes. If a container is in both lists, the pause list takes priority (no duplicate restart). Useful for `qbittorrent`, `sabnzbd`, `nzbget`, `transmission`.

### AirVPN server picker

On **Servers → + Add an AirVPN server**: a modal loads live data from the [AirVPN API](https://airvpn.org/?referred_by=483746) (5-min server-side cache). Four tabs:
- **Servers** — full list with color-coded load bar (green/orange/red), user count, health status, sortable columns, real-time search
- **By country** — collapsible sections per country with flag emoji, 🏆 **Best** badge on the least-loaded server, "Select all" button per country
- **⭐ Recommended** — servers meeting all three criteria: load < 50 %, health OK, and fewer than 30 connected users; green badge showing the count
- **↔ Changes** — diff since the last check: newly appeared servers (selectable for instant add), disappeared servers, load shifts ≥ 10 % (with ↑↓ arrow and delta badge), top 5 countries ranked by healthy-server percentage then average load

Servers already in the database are grayed out with their checkbox disabled. The search bar filters all tabs simultaneously. Multi-select, one-click add.

### Quick check before benchmark *(option)*

Enable via **Settings → Scheduling & Benchmark → Quick check before benchmark**.

When enabled, each cycle starts with a speed test of the **currently active server only** — before stopping any containers or restarting Gluetun:

- **Within threshold (default ±15%)**: the full benchmark is skipped. No containers are stopped, Gluetun is not restarted, no VPN interruption. Cycle completes in seconds.
- **Outside threshold**: the full benchmark runs normally — all servers are tested, the best one is selected.

> **Implementation**: the quick check runs **exclusively via the Gluetun HTTP proxy** — no sidecar container is created, no VPN reconnection wait. Result in 10–15 seconds.

This is ideal for frequent scheduling intervals (e.g. every 2–3 hours) where you want a sanity check without the cost of a full benchmark every time.

> The threshold is configurable (1–100 %). A value of 15 means: if the current speed is between 85 % and 115 % of the last known result, the full benchmark is skipped.

### Adaptive scheduling *(option)*

Enable via **Settings → Scheduling & Benchmark → Adaptive scheduling**.

Companion analyses the test history to compute, for each hour of the day (0–23), the **average download speed** and **coefficient of variation** (CV = σ/μ). An hour with high speed and low variance is a good benchmark window — measurements are representative and reproducible there.

**Score per hour** = `avg_speed × max(0, 1 − CV/100)`

- 🟢 **Good window** — score ≥ 70 % of the maximum
- 🔴 **Avoid** — score < 50 % of the maximum

**Requirements**: at least 3 tests in at least 6 different hour slots. Results are displayed directly in the Settings card as soon as enough data is available.

**Auto-shift** *(sub-option)*: if a scheduled cycle falls on an unfavorable hour, the benchmark is deferred by up to 3 h to the next favorable window. If none is found within that delay, the benchmark runs immediately. Once complete, the scheduler resumes its normal interval.

> This option complements the automatic cycle — it does not replace it. The configured interval remains the reference; the adaptive shift only adjusts the next trigger if the hour is deemed unfavorable.

### Benchmark filtering by entry type *(option)*

Enable via **Settings → Scheduling & Cycle → Benchmark filtering → Server types to include**.

By default, the benchmark tests **all** enabled entries in `/servers`, regardless of their Gluetun type. With this option, you select exactly which types will participate in each cycle:

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

### AirVPN pre-filter before benchmark *(option, dedicated to [AirVPN](https://airvpn.org/?referred_by=483746))*

Enable via **Settings → Scheduling & Cycle → Benchmark filtering → AirVPN pre-filter**.

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

Companion provides 6 **usage profiles** selectable from the **Servers** page (pill bar) or from **Settings → Automatic switching → Usage profile**.

The active profile determines **how the best server is selected** at the end of each benchmark cycle, by weighting the measured metrics differently.

| Profile | Primary criterion | Typical use |
|---|---|---|
| **Balanced** (default) | Existing weighted score (speed + history + stability) | General use — identical behavior to before |
| **Gaming** | Low latency + low jitter | FPS, MMO, competitive games |
| **BitTorrent** | Maximum multi-stream upload | qBittorrent, Transmission, Deluge |
| **DDL (single-stream)** | Single-stream download throughput | Usenet (SABnzbd), direct downloaders (JDownloader) |
| **Download (multi-stream)** | Maximum multi-stream download | Radarr/Sonarr, large file transfers |
| **Video streaming** | Stable throughput + low jitter | Jellyfin, Plex, direct play |

**Algorithm**: for each result from the current benchmark cycle, Companion computes the `_weighted_score` (speed + history + stability), then min-max normalises [0,1] all results on each axis. The weighted combination of normalised scores determines the best server for the active profile. The **Balanced** profile reproduces the exact previous behavior — no regression.

**DDL profile and single-stream test**: the DDL profile leverages an additional metric, **single-stream download speed** (`dl_single_mbps`), measured after the main test (VPN connection already established, no reconnect overhead). This test is **optional** and disabled by default — enable it via **Settings → Speed measurement → Single-stream test (DDL)**.

**Servers page**: the profile pill bar displays the **best server for the active profile** (computed from historical averages). The recommended server is highlighted with a 🏆 badge on its row (hidden in Balanced mode).

**Explainable score**: each server in the table view has a 📊 button (chart icon) next to its name. Clicking it opens a popover showing each metric's contribution to the final score — download speed, upload, latency, jitter, packet loss — as weighted progress bars with the raw measured values. Only metrics actually used by the active profile are displayed.

**Scoring time window**: by default, the averages used to rank servers are computed over the **last 30 days**. This can be adjusted in **Settings → Automatic switching → Scoring window**: 7 d, 14 d, 30 d, or all data. A shorter window favours recent performance; a longer window smooths out one-off spikes.

**Outlier detection**: enable in **Settings → Automatic switching → Filter outlier values**. When active, each per-server, per-metric result series is filtered using the IQR method (interquartile range × 1.5) before computing averages. Clearly aberrant measurements (network spike, transient saturation) are excluded from scoring — they remain visible in the history. Requires at least 4 measurements per server to take effect.

### WireGuard VPN profiles

WireGuard profiles let you manage multiple VPN providers or identities in a single Companion instance, with automatic optimised switching between them.

#### Creating a profile

In **Settings → WireGuard VPN profiles**:

1. Choose a provider from the dropdown → credential fields appear dynamically based on what Gluetun requires for that provider
2. Fill in the fields (private key, IP addresses, etc.) — fields marked 🔒 are encrypted before storage
3. Name the profile (e.g. "Mullvad — Sweden", "ProtonVPN — Gaming")
4. The *Active* and *Rotation allowed* toggles include or exclude the profile from automatic cycles

> **Key security**: encrypted values are stored with the prefix `enc:` in the database. They are only decrypted at the moment the Compose override is written or a sidecar container is launched — never exposed in logs or configuration exports.

#### ⚠️ Dedicated WireGuard test key (required)

> **If you use sidecar mode for benchmarks with WireGuard, you must configure a separate WireGuard key pair in Settings → WireGuard VPN Profiles → Dedicated WireGuard test key.**

**Why this is necessary:** sidecar test containers clone the full environment of your main Gluetun container, including its `WIREGUARD_PRIVATE_KEY`. When a test container initiates a new WireGuard handshake from a different IP address using the same key, the VPN provider updates the peer routing… and your main Gluetun tunnel drops. The result: the VPN goes *unhealthy*, and Companion shows "VPN down" in red.

**Solution:** generate a second WireGuard key pair from your provider (same process as your initial setup — one extra key in your client account), then fill in Companion:
- **WireGuard private key (tests)** — a new private key, separate from your main profile key
- **WireGuard IP address (tests)** — the IP address assigned to this key by your provider (CIDR format, e.g. `10.x.x.x/32`)
- **Pre-shared key (optional)** — only if your provider requires one

This dedicated key is injected into all test containers in place of the main key. It applies to all WireGuard providers. **Until it is configured, a red alert is shown in Settings.**

#### Server ↔ profile assignment

On the **Servers** page:

- The *Provider* column shows the WireGuard profile assigned to each server
- If no profile is assigned, a dropdown lets you assign one directly from the table
- The `?profile=<id>` filter (dropdown in the filter bar) limits the display to servers from a given profile or to unassigned servers (`__none__`)
- Servers without a profile when at least one profile is configured are flagged as *(orphan servers)*

#### Multi-profile benchmark — execution flow

```
Benchmark cycle with WireGuard profiles
  ├─ Load and decrypt WireGuard vars
  │    for each distinct profile_id in the server list
  │    → in-memory cache for the duration of the cycle (decrypted keys, not persisted)
  └─ For each enabled server:
       1. Retrieve extra_env from the associated profile
          (VPN_SERVICE_PROVIDER, VPN_TYPE=wireguard, WIREGUARD_*)
       2. Launch gluetun-companion-test with those variables injected
          (profile vars are merged on top of the real Gluetun container vars)
       3. Speed test via gluetun-companion-sidecar (identical to standard mode)
  └─ Select the best server according to the rotation policy:
       ├─ none        → constrained to the profile of the currently active Gluetun server
       ├─ conditional → cross-profile switch if gain > threshold (default 10 %)
       └─ free        → global best across all profiles
  └─ Gluetun switch:
       → writes VPN_SERVICE_PROVIDER + VPN_TYPE + WIREGUARD_* to the Compose override
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
   - 🏆 **Best score** — candidate with the highest historical average speed
3. Set an optional **Top-N**: if specified, only the N servers with the best average score are eligible, even if the criteria match more
4. Add one or more **criteria** (UNION — each criterion adds candidates):
   - `All active servers` — includes every enabled server in Companion
   - `Specific server` — type the exact name; autocomplete suggests existing servers
   - `Gluetun filter type` — choose the variable (`SERVER_COUNTRIES`, `SERVER_NAMES`, etc.) and optionally a value (empty = all servers of that type)
   - `WireGuard VPN profile` — all servers assigned to a specific WireGuard profile
5. Configure the **schedule**: automatic rotation every N hours (disabled = manual only)
6. Enable **quick bench** to record speed after each switch

The candidate preview updates in real time inside the modal as you configure criteria.

#### Rotation execution flow

```
Rotation triggered (manual or automatic):
  1. Resolve candidates
     ├─ UNION of all pool criteria
     └─ Top-N filter by average score (if set)
  2. Pick target server (random / round-robin / best-score)
  3. switch_server() → write docker-compose.override.yml + docker compose up -d
     └─ If WireGuard profile attached: inject VPN_SERVICE_PROVIDER + WIREGUARD_* into override
  4. If quick bench enabled:
     ├─ Wait for VPN reconnection (connection_wait_seconds)
     ├─ Quick proxy test (proxy_qc)
     └─ Record in speed_tests (test_trigger='pool_rotation')
  5. Update pool state (last_rotated_at, next_rotation_at, round-robin cursor)
  6. Discord/Apprise notification (if enabled)
```

#### Automatic scheduling

The scheduler checks every **5 minutes** whether any pool has a pending rotation (`next_rotation_at <= now`). If a benchmark is running, the rotation is deferred to the next tick without modifying `next_rotation_at`.

> Pool rotations and benchmarks are **independent** — they do not block each other, but a rotation will not trigger while a benchmark is active.

#### Pool rotation notifications

| Type | Severity | Content |
|---|---|---|
| 🟡 Pool rotation | Medium | Pool name, trigger (auto/manual), previous → new server, speed if quick bench enabled, public IP |

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

**Speed vs stability slider** (Settings → Automatic switching):
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
- Useful for scheduling benchmarks during peak performance windows

### New AirVPN server detection

**Disabled by default**, AirVPN users only. Enable in **Settings → Notifications**.

**How it works:**
1. Every 24 h, Companion fetches the server list from `airvpn.org/api/status/`
2. It identifies which countries your configured (name-type) servers belong to
3. Any new server that appears in one of those countries is stored in the database for 7 days

**UI surfaces:**
- **Badge** `+N` on the *Add an AirVPN server* button (Servers page)
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

**Global metrics**:
- `gluetun_companion_switches_total` — total number of switches
- `gluetun_companion_switches_success_total` — successful switches
- `gluetun_companion_benchmark_running` — 1 if a benchmark is currently running
- `gluetun_companion_last_switch_timestamp_seconds` — Unix timestamp of the last switch

**Authentication**: open by default (standard for internal networks). Two ways to protect `/metrics` with a Bearer token: set the `METRICS_TOKEN` environment variable, or configure an **API token** in Settings → API (both are supported; `METRICS_TOKEN` takes precedence).

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

The API is **disabled by default**. To enable it: **Settings → REST API → Generate a new token**.

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

In **Settings → Scheduling & Benchmark**: the automatic cycle can be disabled via the *Enable automatic benchmark cycle* toggle. The interval field is then grayed out. Two buttons are always available (dashboard and settings):

- **Quick benchmark** — tests only the active server via the Gluetun HTTP proxy; result in seconds, no VPN interruption, result saved in history (`proxy_qc` method).
- **Full benchmark** — runs a complete cycle immediately, regardless of the automatic cycle setting or the *Quick check* option. Uses the configured method (sidecar or proxy), shown in parentheses on the button.

---

## Configuration export / import

Available from **Settings**, the **Export configuration** button generates a `companion-config.json` file containing settings *excluding secrets* (passwords, tokens, webhooks are not exported). This file can be re-imported on another instance via the **Import** button. If the import changes the benchmark interval or the automatic cycle, the scheduler reloads immediately.

---

## Grafana dashboard

A Grafana dashboard JSON file is downloadable from **Settings**. It is pre-wired to Companion's Prometheus metrics and includes panels for:

- Download/upload throughput per server (bar gauge)
- Latency, jitter, packet loss, DNS (bar gauge)
- Confidence index and profile score (bar gauge)
- Errors by type (donut chart)
- Summary table of all servers

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
| `gluetun_companion_errors_total{type}` | Error counter by type: timeout, connection, vpn, other |

---

## Notes

- **Sidecar mode (default):** your main Gluetun is never restarted during testing — dependent services are not interrupted. **Proxy mode (optional):** the benchmark briefly interrupts those services on each server test. Schedule during off-peak hours.
- **Frequency and server count:** each test triggers a VPN reconnection. Testing 10 servers every 2 hours = 120 reconnections/day. Most providers limit *simultaneous* connections, not frequency — but a very short interval may trigger abuse detection. **6 h and fewer than 10 servers** is a sensible default.
- `docker-compose.override.yml` is managed automatically — do not edit it manually.
- IPv6 is displayed if your VPN provider supports it (AirVPN does).
- The Docker socket (`/var/run/docker.sock`) is required for sidecar mode, post-switch containers, and the benchmark pause feature.

---

## Security

- **Anti brute-force** — The login endpoint blocks an IP after 5 failures within 5 minutes for 15 minutes. No external dependency: pure in-memory sliding window.
- **CSRF** — All POST actions (forms and AJAX) are protected by a CSRF token via server-side session. The `X-CSRF-Token` header is automatically injected on every non-GET `fetch` request via a JavaScript interceptor.
- **XSS** — Third-party API data (AirVPN) injected into the DOM via `innerHTML` is always escaped by a `_esc()` helper (HTML entity encoding) before insertion. Inline `onclick`/`onchange` attributes present in dynamic components only contain JSON-encoded values or constants — no raw user data is interpolated into them.
- **SECRET_KEY** — The application refuses to start if `SECRET_KEY` is missing or equal to the default value. Generate a secure key with: `openssl rand -hex 32`.
- **Network exposure** — Gunicorn listens on `0.0.0.0:8765`. **Do not expose this port directly to the internet.** On a publicly accessible server, place Companion behind a reverse proxy (Nginx, Caddy, Traefik) with HTTPS and strong authentication, or restrict the binding to the local interface: `127.0.0.1:8765:8765` in your `docker-compose.yml`.
- **`/metrics`** — Open by default on the LAN. If your machine is reachable from outside, set the `METRICS_TOKEN` environment variable or configure an API token in Settings → API: `/metrics` will use it automatically (Bearer token required in the `Authorization` header).
- **Sidecar** — Each sidecar container (speed-test on port `8766`, catalogue on port `8767`) automatically receives a random secret generated by the Companion (`SIDECAR_SECRET`, 32 bytes of entropy via `secrets.token_hex`). Every HTTP request to the sidecar must include this secret in the `X-Sidecar-Token` header — a request without the correct token receives a `403`. The secret is unique per instance and destroyed along with the container at the end of the test. These ports must not be reachable from untrusted networks: if your host is publicly accessible, restrict the port binding or isolate them with a firewall.
- **Secrets in /settings** — The API token, proxy password, and webhook URLs are displayed in cleartext in the Settings page. Restrict access to Companion to trusted users only.
- **YAML injection** — The server filter value is sanitised before being written to `docker-compose.override.yml` (newlines stripped, quotes and backslashes escaped).
- **Docker socket** — The Docker socket is secured via [docker-socket-proxy](https://github.com/Tecnativa/docker-socket-proxy), which restricts allowed calls to: read access (containers, images, networks, volumes) plus POST/DELETE for temporary sidecar management. Direct daemon access (exec, swarm, info…) is blocked.

### Docker image security

Both images (`gluetun-companion` and `gluetun-companion-sidecar`) bundle **third-party Go binaries** (Docker CLI, Docker Compose, librespeed-cli, ookla speedtest) with their own dependency chains, invisible to Python package managers. A two-layer pipeline keeps these images up to date:

**Dependabot** (already in place, runs every Monday 06:00 UTC):
- Updates **pip** dependencies for both Companion and Sidecar (auto-PR; patch = auto-merge, minor = manual review)
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
- Blocks the merge if an image fails to start — ensures security updates do not break functionality

---

## Credits

Thanks to **[qdm12](https://github.com/qdm12/gluetun)** for Gluetun, without which this project would not exist.

Thanks to **[Tecnativa](https://github.com/Tecnativa/docker-socket-proxy)** for docker-socket-proxy, used to secure access to the Docker socket.

Thanks to **[brashenfr](https://github.com/brashenfr)**, **[dje33](https://github.com/the-real-dje33)**, **[lnksilver5](https://github.com/lnksilver5)**, **[Ptite Pomme](https://github.com/ptitzgeg-on-git)**, **[x0gen](https://github.com/x0gen)**, **[zlimteck](https://github.com/zlimteck)** and **[Zup](https://github.com/Gusdezup)** for their ideas and testing.

---

## License

[PolyForm Noncommercial 1.0.0](LICENSE) — free for personal and non-profit use, commercial use requires authorization.
