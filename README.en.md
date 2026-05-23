<p align="center">
  <img src="assets/logo.png" alt="Gluetun Companion" width="200">
</p>

# Gluetun Companion

Automatic VPN server benchmarking via [Gluetun](https://github.com/qdm12/gluetun), switches to the fastest server, full Web UI.

> 🇫🇷 [Version française](README.md)

<p align="center">
<a href="https://github.com/Aerya/Gluetun-Companion/actions/workflows/docker-publish.yml"><img src="https://github.com/Aerya/Gluetun-Companion/actions/workflows/docker-publish.yml/badge.svg?branch=main" alt="Build"></a>
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
  - [Docker events listener](#docker-events-listener)
  - [Usage profiles](#usage-profiles)
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

### Docker container management
- **Gluetun network containers (auto-managed)** — all containers using `network_mode: service:gluetun` are detected and restarted automatically after each switch
- **Containers to restart after switch** — only for containers routing through Gluetun's HTTP/SOCKS5 proxy; ordered list (drag & drop)
- **Pause during benchmark** — list of containers (torrent, Usenet…) stopped before the benchmark starts and automatically restarted when it ends, even on error
- **Automatic Docker image updates** *(option)* — at switch time, Companion can update images before restarting containers: Gluetun itself, auto-managed network containers, post-switch containers and benchmark-paused containers; togglable per container from Settings

### AirVPN
- **Built-in AirVPN server picker** — *+ Add an AirVPN server* button on the Servers page: live data from `airvpn.org/api/status/` (5-min server-side cache), two views — full searchable list (load, users, health) and geographic distribution by country with a **Best** badge on the least-loaded server; multi-select, one-click add
- **New AirVPN server detection** *(optional)* — compares the AirVPN API with your configured servers every 24 h; badge and dismissable banner on the Servers page + *New* tab in the add modal; Discord/Apprise notification with optional mention

### Analysis & history
- **Per-server confidence score** — 🟢/🟡/🔴 indicator on the Servers page and in History; based on measurement count and result variability; factored into the automatic selection score (light weighting)
- **Hourly patterns** (`/history/patterns`) — 0h–23h bar chart showing average speed by hour of day, color-coded by relative performance; best and worst hour displayed; helps identify server saturation windows
- **On-demand test** of a single server from the UI without waiting for the next cycle
- **CSV export** of the full history

### UI & notifications
- **Web UI** dark/light, FR/EN — auth, dashboard with sparkline, paginated history, charts, switches page with Mbps gain and connection time
- **Contextual notifications** — 6 independently-configurable alert types (auto/manual switch, auto-exclude, benchmark with no results, benchmark complete, new AirVPN servers) via Discord webhook (rich embed) and/or [Apprise](https://github.com/caronc/apprise/wiki) (Telegram, ntfy, Gotify, Slack, Pushover…); severity levels 🔴/🟡/🔵; global Discord mention with configurable severity threshold
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
      - GLUETUN_CONTAINER=gluetun-airvpn   # exact name of your Gluetun container
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
> The Docker socket gives near-total access to the host. The [Tecnativa proxy](https://github.com/Tecnativa/docker-socket-proxy) sits between Companion and the socket, exposing only the operations Companion actually needs — it cannot launch privileged containers, mount arbitrary paths, etc. Fully transparent for the user, reduced attack surface.

Open **http://localhost:8765** — first login: enter the credentials you want (account created automatically).

> **Companion in the same stack as Gluetun?**
> Remove `extra_hosts` and use the service name: `GLUETUN_HOST: gluetun`.
> On a switch, the companion only targets the Gluetun service (`docker compose up -d <service>`) — it never restarts itself.

### 4. Import servers

**Servers → Import from Gluetun**: the companion reads `SERVER_NAMES`, `SERVER_COUNTRIES`, etc. directly from the running container and imports each value with its filter type. Manual addition is also available on the same screen.

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

On **Servers → + Add an AirVPN server**: a modal loads live data from the [AirVPN API](https://airvpn.org/?referred_by=483746) (5-min server-side cache). Two tabs:
- **Servers** — full list with color-coded load bar (green/orange/red), user count, health status, real-time search
- **By country** — collapsible sections per country with flag emoji, 🏆 **Best** badge on the least-loaded server, "Select all" button per country

Servers already in the database are grayed out with their checkbox disabled. Multi-select, one-click add.

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
| **Confidence** (historical variance) | Coefficient of variation over last 5 tests | −15 % (LOW) · −5 % (MEDIUM) |

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
- **New tab** in the add modal: lists all AirVPN servers not yet in your list (⭐ *New* badge on automatically detected ones); unified search filter

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

**Authentication**: open by default (standard for internal networks). Set `METRICS_TOKEN` to require a Bearer token.

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

## Notes

- **Sidecar mode (default):** your main Gluetun is never restarted during testing — dependent services are not interrupted. **Proxy mode (optional):** the benchmark briefly interrupts those services on each server test. Schedule during off-peak hours.
- **Frequency and server count:** each test triggers a VPN reconnection. Testing 10 servers every 2 hours = 120 reconnections/day. Most providers limit *simultaneous* connections, not frequency — but a very short interval may trigger abuse detection. **6 h and fewer than 10 servers** is a sensible default.
- `docker-compose.override.yml` is managed automatically — do not edit it manually.
- IPv6 is displayed if your VPN provider supports it (AirVPN does).
- The Docker socket (`/var/run/docker.sock`) is required for sidecar mode, post-switch containers, and the benchmark pause feature.

---

## Security

- **CSRF** — All POST actions (forms and AJAX) are protected by a CSRF token via server-side session. The `X-CSRF-Token` header is automatically injected on every non-GET `fetch` request via a JavaScript interceptor.
- **XSS** — Third-party API data (AirVPN) injected into the DOM via `innerHTML` is always escaped by a `_esc()` helper (HTML entity encoding). Event handlers on dynamic elements use `addEventListener` rather than inline `onchange` attributes.
- **SECRET_KEY** — The application refuses to start if `SECRET_KEY` is missing or equal to the default value. Generate a secure key with: `openssl rand -hex 32`.
- **YAML injection** — The server filter value is sanitised before being written to `docker-compose.override.yml` (newlines stripped, quotes and backslashes escaped).
- **Docker socket** — The Docker socket is secured via [docker-socket-proxy](https://github.com/Tecnativa/docker-socket-proxy), restricting access to the bare minimum (container read access, no root access to the daemon).

---

## Credits

Thanks to **[qdm12](https://github.com/qdm12/gluetun)** for Gluetun, without which this project would not exist.

Thanks to **[Tecnativa](https://github.com/Tecnativa/docker-socket-proxy)** for docker-socket-proxy, used to secure access to the Docker socket.

Thanks to **Zup** for ideas and testing.

---

## License

[PolyForm Noncommercial 1.0.0](LICENSE) — free for personal and non-profit use, commercial use requires authorization.
