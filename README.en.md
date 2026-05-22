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

## Features

- **Built-in AirVPN server picker** — *+ Add an AirVPN server* button on the Servers page: live data from `airvpn.org/api/status/` (5-min server-side cache), two views — full searchable list (load, users, health) and geographic distribution by country with a **Best** badge on the least-loaded server; multi-select, one-click add
- **Pause during benchmark** — list of containers (torrent, Usenet…) stopped before the benchmark starts and automatically restarted when it ends, even on error
- **Gluetun network containers (auto-managed)** — all containers using `network_mode: service:gluetun` are detected and restarted automatically after each switch
- **Containers to restart after switch** — only for containers routing through Gluetun's HTTP/SOCKS5 proxy; ordered list (drag & drop)
- **Automatic Docker image updates** *(option)* — at switch time, Companion can update images before restarting containers: Gluetun itself, auto-managed network containers, post-switch containers and benchmark-paused containers; togglable per container from Settings
- **Quick check before benchmark** *(option)* — tests only the current server before each cycle; if speed is within ±N% of the last known result, the full benchmark is skipped entirely — no containers paused, no VPN restarts; triggers the full benchmark only when performance drifts significantly
- **On-demand quick benchmark** — button always available (dashboard and settings); tests only the active server via the Gluetun HTTP proxy, result in seconds, no VPN interruption, result saved in history
- **Automatic benchmarking** every X hours — download, upload and latency per server; automatic cycle can be disabled (manual trigger only)
- **Sidecar mode** (default) — a `gluetun-companion-test` container clones the real Gluetun config for each server; `gluetun-companion-sidecar` measures speed via **Ookla + librespeed in parallel** (dual mode, default), Ookla only, librespeed only, or iperf3 directly inside the VPN tunnel; your main Gluetun is never restarted during testing
- **Multi-source results** — Ookla, librespeed and iperf3 speeds stored separately and displayed in the dashboard and history
- **HTTP proxy mode** (optional) — measures speed via the Gluetun HTTP proxy with no extra containers; briefly interrupts dependent services on each server switch
- **Multi-stream download** — N concurrent TCP connections (configurable, default: 4)
- **Automatic switching** to the fastest server (`docker compose up -d`), based on a weighted score (configurable weight: current measurement vs exponential history); dependent services (`network_mode: service:gluetun`) are recreated automatically
- **5 filter types**: `SERVER_NAMES`, `SERVER_COUNTRIES`, `SERVER_REGIONS`, `SERVER_CITIES`, `SERVER_HOSTNAMES`
- Configurable **retry** per server + global timeout per server
- **Auto-disable** a server after N consecutive failures
- **Web UI** dark/light, FR/EN — auth, dashboard with sparkline, paginated history, charts, switches page with Mbps gain and connection time
- **CSV export** of the full history
- **On-demand test** of a single server from the UI without waiting for the next cycle
- **Manual switch** to any configured server from the Servers page — Gluetun is reconfigured and `network_mode: service:gluetun` containers are recreated automatically
- **Notifications** on every switch — Discord webhook (rich embed) and/or [Apprise](https://github.com/caronc/apprise/wiki) (Telegram, ntfy, Gotify, Slack, Pushover…)
- **Automatic purge** of SQLite history with configurable retention (in days)
- **Per-server confidence score** — 🟢/🟡/🔴 indicator on the Servers page and in History; based on measurement count and result variability; factored into the automatic selection score (light weighting)
- **Hourly patterns** (`/history/patterns`) — 0h–23h bar chart showing average speed by hour of day, color-coded by relative performance; best and worst hour displayed; helps identify server saturation windows
- **`/healthz` endpoint** unauthenticated, for Docker healthchecks
- **`/metrics` endpoint** in Prometheus format — throughput, latency, switches, active server; optionally protected by Bearer token; Grafana-compatible
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

### Per-server confidence score

A color indicator is shown on the **Servers** page (*Confidence* column) and in **History** for each server. It reflects how reliable the accumulated measurements are.

| Level | Conditions |
|---|---|
| 🟢 High | ≥ 5 measurements **and** variability < 40 % |
| 🟡 Moderate | 2–4 measurements or variability 40–70 % |
| 🔴 Low | ≤ 1 measurement, variability > 70 % or consecutive failures |

**Variability** (coefficient of variation) is the standard deviation of speeds divided by the mean: 0 % = identical results every test, 100 % = very scattered results. Quick check tests (`proxy_qc`) are excluded from the calculation.

The score lightly influences automatic server selection: HIGH × 1.0 · MEDIUM × 0.95 · LOW × 0.85 applied to the weighted score.

### Hourly patterns view (`/history/patterns`)

Accessible from **History → Hourly patterns**, this view shows average performance by hour of day (0h–23h) for a selected server.

- Bar chart color-coded by performance relative to the server's best hour: 🟢 ≥ 85 % · 🟡 65–85 % · 🟠 45–65 % · 🔴 < 45 %
- Hours displayed in local time (respects the `TZ` environment variable)
- Best and worst hour shown in stat cards
- Quick checks (`proxy_qc`) excluded
- Useful for scheduling benchmarks during peak performance windows

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
