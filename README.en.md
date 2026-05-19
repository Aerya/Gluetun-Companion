<p align="center">
  <img src="assets/logo.png" alt="Gluetun Companion" width="200">
</p>

# Gluetun Companion

Automatic VPN server benchmarking via [Gluetun](https://github.com/qdm12/gluetun), switches to the fastest server, full Web UI.

> 🇫🇷 [Version française](README.md)

[![Build](https://github.com/Aerya/Gluetun-Companion/actions/workflows/docker-publish.yml/badge.svg?branch=main)](https://github.com/Aerya/Gluetun-Companion/actions/workflows/docker-publish.yml)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white)](https://github.com/Aerya/Gluetun-Companion/pkgs/container/gluetun-companion)
[![arch](https://img.shields.io/badge/arch-amd64%20%7C%20arm64-lightgrey)](#)
[![i18n](https://img.shields.io/badge/i18n-FR%20%7C%20EN-informational)](README.md)
[![Gluetun compatible](https://img.shields.io/badge/Gluetun-compatible-0d1117?logo=github&logoColor=white)](https://github.com/qdm12/gluetun)

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

- 🆕 **Pause during benchmark** — list of containers (torrent, Usenet…) stopped before the benchmark starts and automatically restarted when it ends, even on error; prevents their traffic from skewing measurements and avoids overloading the VPN tunnel on modest hardware
- 🆕 **Containers to restart after switch** — ordered list (drag & drop), sequential restart via `docker compose up -d --force-recreate` after each VPN switch; correctly handles containers using `network_mode: service:gluetun`
- **Automatic benchmarking** every X hours — download, upload and latency per server
- **Sidecar mode** (default) — a `gluetun-companion-test` container clones the real Gluetun config for each server; `gluetun-companion-sidecar` measures speed via **Ookla + librespeed in parallel** (dual mode, default), Ookla only, librespeed only, or iperf3 directly inside the VPN tunnel; your main Gluetun is never restarted during testing
- **Multi-source results** — Ookla, librespeed and iperf3 speeds stored separately and displayed in the dashboard and history
- **HTTP proxy mode** (optional) — measures speed via the Gluetun HTTP proxy with no extra containers; briefly interrupts dependent services on each server switch
- **Multi-stream download** — N concurrent TCP connections (configurable, default: 4)
- **Automatic switching** to the fastest server (`docker compose up -d`), based on a weighted score (65% current + 35% history); dependent services (`network_mode: service:gluetun`) are recreated automatically
- **5 filter types**: `SERVER_NAMES`, `SERVER_COUNTRIES`, `SERVER_REGIONS`, `SERVER_CITIES`, `SERVER_HOSTNAMES`
- Configurable **retry** per server + global timeout per server
- **Auto-disable** a server after N consecutive failures
- **Web UI** dark/light, FR/EN — auth, dashboard with sparkline, paginated history, charts, switches page with Mbps gain and connection time
- **CSV export** of the full history
- **On-demand test** of a single server from the UI without waiting for the next cycle
- **Notifications** on every switch — Discord webhook (rich embed) and/or [Apprise](https://github.com/caronc/apprise/wiki) (Telegram, ntfy, Gotify, Slack, Pushover…)
- **Automatic purge** of SQLite history with configurable retention (in days)
- **`/healthz` endpoint** unauthenticated, for Docker healthchecks
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
  gluetun-companion:
    image: ghcr.io/aerya/gluetun-companion:latest
    container_name: gluetun-companion
    restart: always
    ports:
      - 8765:8765
    volumes:
      - /path/to/data:/data
      - /var/run/docker.sock:/var/run/docker.sock
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
```

```bash
docker compose up -d
```

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

---

## Notes

- **Sidecar mode (default):** your main Gluetun is never restarted during testing — dependent services are not interrupted. **Proxy mode (optional):** the benchmark briefly interrupts those services on each server test. Schedule during off-peak hours.
- **Frequency and server count:** each test triggers a VPN reconnection. Testing 10 servers every 2 hours = 120 reconnections/day. Most providers limit *simultaneous* connections, not frequency — but a very short interval may trigger abuse detection. **6 h and fewer than 10 servers** is a sensible default.
- `docker-compose.override.yml` is managed automatically — do not edit it manually.
- IPv6 is displayed if your VPN provider supports it (AirVPN does).
- The Docker socket (`/var/run/docker.sock`) is required for sidecar mode, post-switch containers, and the benchmark pause feature.

---

## Credits

Thanks to **[qdm12](https://github.com/qdm12/gluetun)** for Gluetun, without which this project would not exist.

Thanks to **Zup** for ideas and testing.

---

## License

[PolyForm Noncommercial 1.0.0](LICENSE) — free for personal and non-profit use, commercial use requires authorization.
