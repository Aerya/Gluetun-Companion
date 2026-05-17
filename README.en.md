# Gluetun Companion

Automatic VPN server benchmarking via [Gluetun](https://github.com/qdm12/gluetun),
with automatic switching to the fastest server and a full Web UI.

> **Thanks to [qdm12](https://github.com/qdm12/gluetun)** for Gluetun, without which this project would not exist.

---

## Compatibility

Gluetun Companion works in theory with **any Gluetun-compatible VPN provider**
as long as at least one of these filter variables is used in your configuration:

| Gluetun variable | Description |
|---|---|
| `SERVER_NAMES` | Server name |
| `SERVER_COUNTRIES` | Country |
| `SERVER_REGIONS` | Region |
| `SERVER_CITIES` | City |
| `SERVER_HOSTNAMES` | Server hostname |

The companion is **independent of the tunnel technology** in use: it works identically
with OpenVPN, WireGuard, or any other protocol supported by your provider.

It is primarily designed and tested for **[AirVPN](https://airvpn.org/?referred_by=483746)**
*(affiliate link — thank you if you use it!)*, whose filter variables are documented here:
[gluetun-wiki — AirVPN optional environment variables](https://github.com/qdm12/gluetun-wiki/blob/main/setup/providers/airvpn.md#optional-environment-variables)

---

## Features

- **Automatic benchmarking** every X hours — download, upload and latency per server
- **Sidecar mode** (default) — a `gluetun-companion-test` container clones the real Gluetun
  config for each server; a `gluetun-companion-sidecar` container measures speed via
  **iperf3** or **librespeed** directly inside the VPN tunnel. Your main Gluetun is never
  restarted during testing — only once at the end to switch to the winner
- **HTTP proxy mode** (optional, if sidecar is disabled) — measures speed through the
  Gluetun HTTP proxy (port 8887), no extra containers, but briefly interrupts dependent
  services on each server switch
- **Multi-stream download** — N concurrent TCP connections (configurable, default: 4)
- **Automatic switching** to the fastest server (`docker compose up -d`),
  based on a weighted score (65% current measurement + 35% historical);
  dependent services (`network_mode: service:gluetun`) are restarted automatically
- **5 filter types**: SERVER\_NAMES, SERVER\_COUNTRIES, SERVER\_REGIONS,
  SERVER\_CITIES, SERVER\_HOSTNAMES
- Configurable **retry** per server + global timeout per server
- **Auto-disable** a server after N consecutive failures
- **Web UI** dark/light, **FR/EN** — auth, dashboard with sparkline, paginated history, charts,
  switches page with Mbps gain and connection time
- **CSV export** of the full history
- **On-demand test** of a single server from the UI without waiting for the next cycle
- **Notifications** on every switch — Discord webhook (rich embed) and/or
  [Apprise](https://github.com/caronc/apprise/wiki) (Telegram, ntfy, Gotify, Slack, Pushover…)
- **Automatic purge** of SQLite history with configurable retention (in days)
- **`/healthz` endpoint** unauthenticated, for Docker healthchecks
- **Structured JSON logs** optional via `LOG_JSON=1` (Loki/Grafana compatible)
- **SQLite database** (WAL) — no external dependencies

---

## Getting started

### 1. Expose Gluetun's HTTP proxy on the host

The companion does **not** use the Gluetun API (port 8000) or a shared Docker network.
It exclusively goes through Gluetun's **HTTP proxy**, reachable via `host.docker.internal`.

In your Gluetun compose, expose the HTTP proxy on the host:

```yaml
# in your existing Gluetun docker-compose.yml
ports:
  - 8887:8888   # or whichever port you have configured

environment:
  HTTPPROXY: "on"
  HTTPPROXY_LOG: "off"
  # HTTPPROXY_USER: ""       # optional — set in the UI settings if needed
  # HTTPPROXY_PASSWORD: ""
```

### 2. Mount the Gluetun compose directory

The companion must be able to write a `docker-compose.override.yml` into the directory
that contains your Gluetun `docker-compose.yml`, then restart the service.

### 3. Configure the companion

```yaml
services:
  gluetun-companion:
    image: ghcr.io/aerya/gluetun-companion:latest
    container_name: gluetun-companion
    restart: always
    ports:
      - 8765:8765
    volumes:
      - /home/user/docker/gluetun-companion:/data
      - /var/run/docker.sock:/var/run/docker.sock
      - /home/aerya/docker/dockge-enhanced/stacks/airvpn:/compose   # <-- adapt this
    extra_hosts:
      - "host.docker.internal:host-gateway"
    environment:
      - TZ=Europe/Paris
      - SECRET_KEY=replace-with-a-long-random-string   # openssl rand -hex 32
      - DATA_DIR=/data
      - GLUETUN_HOST=host.docker.internal
      - GLUETUN_PROXY_PORT=8887          # Gluetun HTTP proxy port exposed on the host
      - GLUETUN_CONTAINER=gluetun-airvpn   # exact service name in the Gluetun compose
      - COMPOSE_DIR=/compose

networks: {}
```

> **Running the companion in the same stack as Gluetun?**
> You can drop `extra_hosts` and use the service name as the host:
> `GLUETUN_HOST: gluetun` (or whatever your Gluetun service is named).
> **Caution:** in this setup, if Compose decides to recreate the companion
> (e.g. on an image update), it will stop mid-benchmark.
> A separate stack is recommended.

### 4. Start

```bash
docker compose up -d
```

Open: **http://localhost:8765**

First login → enter the credentials you want to create (saved automatically).

### 5. Import servers

**Servers** → **Import from Gluetun**: the companion reads `SERVER_NAMES`,
`SERVER_COUNTRIES`, etc. directly from the running container and imports each value
with its filter type.

You can also add servers manually from the same page.

---

## How it works

**Sidecar mode (default)**

```
Benchmark cycle (every X hours)
  └─ For each enabled server:
       1. Pull ghcr.io/aerya/gluetun-companion-sidecar:latest
       2. Start gluetun-companion-test
          (clone of your Gluetun, configured for the target server)
       3. Start gluetun-companion-sidecar
          (network_mode: container:gluetun-companion-test)
       4. Wait for VPN via /health polling (configurable timeout)
       5. Speed test via iperf3 or librespeed inside the VPN tunnel
          → DL, UL, latency recorded
       6. Stop + remove both containers and delete the sidecar image
       → Auto-retry on failure, global timeout per server
       → Auto-disable after N consecutive failures
  └─ Weighted score per server (65% current + 35% exponential history)
  └─ Switch real Gluetun to best server (single restart)
  └─ Discord / Apprise notification (if configured)
  └─ Cycle record (total duration, servers tested, best server)
```

**HTTP proxy mode (optional, if sidecar is disabled)**

```
Benchmark cycle (every X hours)
  └─ For each enabled server:
       1. Write docker-compose.override.yml
          → target variable = "<server>", all others cleared
       2. docker compose up -d  ← real Gluetun restarts
       3. Wait for VPN via HTTP proxy polling (configurable timeout)
       4. Optional TCP warm-up (2s drained, not counted)
       5. Download from N endpoints (Cloudflare, Hetzner, Fast.com, OVH, Tele2)
          → median Mbps
       6. Upload to Cloudflare __up → Mbps
       7. Latency TTFB from N endpoints → median ms
       8. SQLite record
       → Dependent services are briefly interrupted on each switch
  └─ Weighted score → switch → notification → cycle record
```

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `SECRET_KEY` | *(required)* | Flask session signing key |
| `GLUETUN_HOST` | `host.docker.internal` | Gluetun HTTP proxy host |
| `GLUETUN_PROXY_PORT` | `8887` | Gluetun HTTP proxy port |
| `GLUETUN_CONTAINER` | `gluetun-airvpn` | Gluetun container name (for Docker SDK) |
| `COMPOSE_DIR` | `/compose` | Path (inside the container) to the Gluetun compose directory |
| `DATA_DIR` | `/data` | SQLite database directory |

> Benchmark parameters (parallel streams, duration, warm-up, etc.) are configured
> directly in the UI → **Settings**.

---

## Sidecar mode

**Sidecar mode is enabled by default.** It is more accurate and less disruptive than proxy
mode: your real Gluetun is never restarted during testing.

```
For each server under test
  └─ Pull ghcr.io/aerya/gluetun-companion-sidecar:latest  (always latest version)
  └─ gluetun-companion-test   ← clone of your Gluetun (same image + env vars)
                                 configured with the target SERVER_* value
  └─ gluetun-companion-sidecar← network_mode: container:gluetun-companion-test
                                 measures via iperf3 or librespeed inside the VPN tunnel
  └─ Stop + remove both containers and delete the sidecar image from disk

After all servers are tested
  └─ Switch real Gluetun to the best server (one single restart)
```

**Test engine (configurable in Settings → Sidecar Mode):**
- **Auto** (default) — iperf3 first, librespeed as fallback if all iperf3 servers are unreachable
- **iperf3 only** — error if all iperf3 servers fail
- **librespeed only** — librespeed-cli, public librespeed.org servers (HTTP, rarely blocked)

**Advantages over proxy mode:**
- Your real Gluetun (and all services depending on it) is never interrupted during benchmarking
- Measures raw TCP throughput without HTTP proxy overhead — more accurate on fast VPNs

**Proxy mode (optional):** Settings → Sidecar Mode → toggle off.
Useful if you do not have access to the Docker socket.

> ⚠ **Simultaneous connection warning** — valid for ALL VPN providers
>
> Sidecar mode adds **one extra concurrent VPN connection** for the entire duration of the
> benchmark (the test Gluetun container). If your provider limits simultaneous connections
> (AirVPN: 3–5 depending on plan; most other providers: similar), this consumes one extra slot.
> Make sure you have a free connection slot.
> This warning applies to **all providers compatible with Gluetun**, not just AirVPN.

---

## Notes

- **In sidecar mode (default):** your main Gluetun is never restarted during testing —
  dependent services (qBittorrent, Sonarr, Radarr…) are not interrupted.
  **In proxy mode (optional):** the benchmark briefly interrupts these services while testing
  each server. Schedule cycles during off-peak hours or increase the interval.
- **Frequency and server count**: each server test triggers a VPN reconnection.
  Testing 10 servers every 2 hours means 120 reconnections per day.
  Most providers (including AirVPN) limit *simultaneous* connections rather than
  frequency, but a very short interval with many servers may trigger abuse detection.
  **6 h and fewer than 10 servers** is a sensible default.
- The `docker-compose.override.yml` file is managed automatically — do not edit it manually.
- IPv6 is displayed if your VPN provider supports it (AirVPN does).
