"""
Gluetun Companion — speed-test sidecar.

This container runs inside the VPN network namespace of a cloned Gluetun container
(network_mode: container:<gluetun-test>). Traffic goes through the VPN tunnel directly —
no HTTP proxy involved.

API
---
GET  /health           → {"vpn": true, "ip": "x.x.x.x"}  (503 if VPN not up)

POST /test?duration=8&streams=4&method=dual&iperf_fallback=1
                       → {
                           "download_mbps": 450.0,     # avg of succeeded sources
                           "upload_mbps": 220.0,
                           "latency_ms": 15.0,
                           "method": "dual",
                           "ip": "x.x.x.x",
                           "dl_ookla": 460.0,          # null if not run / failed
                           "ul_ookla": 230.0,
                           "dl_librespeed": 440.0,
                           "ul_librespeed": 210.0,
                           "dl_iperf3": null,
                           "ul_iperf3": null,
                           "ookla_server": "Paris (Bouygues)",
                           "iperf_server": null,
                           "jitter_ms": 2.1,           # null if ping failed
                           "packet_loss_pct": 0.0,
                           "ping_min_ms": 4.9,
                           "ping_max_ms": 7.2,
                           "dns_latency_ms": 18.0      # null if dig unavailable
                         }

POST /ping?targets=1.1.1.1,8.8.8.8,9.9.9.9&count=20&interval=0.2
                       → {
                           "results": [
                             {"target": "1.1.1.1", "jitter_ms": 0.5,
                              "packet_loss_pct": 0.0, "ping_min_ms": 4.9,
                              "ping_max_ms": 7.2},
                             ...
                           ]
                         }

method values:
  dual        — Ookla + librespeed in parallel; iperf3 fallback if both fail (when iperf_fallback=1)
  ookla       — Ookla only; iperf3 fallback if it fails (when iperf_fallback=1)
  librespeed  — librespeed-cli only; iperf3 fallback if it fails (when iperf_fallback=1)
  iperf3      — iperf3 only (no fallback)
"""

import json
import logging
import os
import re
import socket
import subprocess
import time
import glob
from concurrent.futures import ThreadPoolExecutor, as_completed
from statistics import median, pstdev

import requests
from flask import Flask, jsonify, request

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format='%(levelname)s %(name)s %(message)s')
logger = logging.getLogger(__name__)

_PROBE_URL    = 'https://www.cloudflare.com/cdn-cgi/trace'
# Providers excluded from catalogue fetch (empty = all fetched)
_CAT_EXCLUDED: set[str] = set()
# Directory where Gluetun writes per-provider JSON files
# (set via SERVERS_DIR env var when Companion creates this container)
# Public GitHub repository that holds per-provider server JSON files.
# No volume mounting or Gluetun API required — pure HTTP download.
_GITHUB_API_URL = 'https://api.github.com/repos/qdm12/gluetun-servers/contents/pkg/servers'
_GITHUB_RAW_URL = 'https://raw.githubusercontent.com/qdm12/gluetun-servers/main/pkg/servers'
_LOCAL_GLUETUN_DIR = os.environ.get('GLUETUN_DIR', '/gluetun')
# Shared secret — Companion generates a random token per sidecar instance and
# passes it via SIDECAR_SECRET env var.  All endpoints require it when set.
_SECRET       = os.environ.get('SIDECAR_SECRET', '')

# Public iperf3 servers tried in order — first one that responds wins
_IPERF3_SERVERS: list[tuple[str, int]] = [
    ('bouygues.iperf.fr',      5209),
    ('ping.online.net',        5209),
    ('speedtest.wtnet.de',     5200),
    ('iperf.he.net',           5201),
    ('speedtest.uztelecom.uz', 5200),
]

# Stability-probe targets — diverse ASNs (Cloudflare / Google / Quad9) for a
# representative jitter/loss measurement. All three accept TCP on 443 and 53.
_STABILITY_TARGETS = ['1.1.1.1', '8.8.8.8', '9.9.9.9']

# Reachability is measured with TCP handshakes, NOT ICMP: commercial VPNs
# (e.g. ProtonVPN) rate-limit concurrent ICMP, which starves parallel pings and
# fabricates packet loss on a perfectly healthy tunnel. A SYN/ACK on either port
# proves reachability; ports are tried in order and the first that answers is
# reused for the remaining samples of that target.
_STABILITY_PORTS = [443, 53]

# Per-handshake timeout. The kernel retransmits a lost SYN at ~1 s, so a probe
# only counts as lost after ~2 s of genuine non-response — single dropped SYNs
# are absorbed by that retransmit rather than reported as loss.
_STABILITY_TIMEOUT = 2.0

_SERVER_TYPE_FIELDS = {
    'p2p':         'port_forward',
    'stream':      'stream',
    'secure_core': 'secure_core',
    'tor':         'tor',
    'free':        'free',
}


def _server_types_from_raw(server: dict) -> str:
    return ','.join(
        key for key, field in _SERVER_TYPE_FIELDS.items()
        if bool(server.get(field))
    )


def _ips_from_raw(server: dict) -> str:
    raw = server.get('ips') or []
    if isinstance(raw, str):
        raw = [part.strip() for part in raw.replace(';', ',').split(',')]
    elif not isinstance(raw, (list, tuple, set)):
        raw = []
    ips: list[str] = []
    for item in raw:
        value = str(item or '').strip()
        if value and value not in ips:
            ips.append(value)
    return json.dumps(ips, separators=(',', ':')) if ips else ''


def _normalize_server_list(raw_servers: list[dict]) -> list[dict]:
    normalized_by_name: dict[str, dict] = {}
    normalized_extra: list[dict] = []
    for s in raw_servers:
        hostnames = s.get('hostnames') or []
        hostname = s.get('hostname') or (hostnames[0] if hostnames else '')
        srv = {
            'name':         s.get('name') or s.get('server_name') or '',
            'country':      s.get('country') or '',
            'country_code': (s.get('country_code') or s.get('countryCode') or '').lower(),
            'region':       s.get('region') or '',
            'city':         s.get('city') or '',
            'hostname':     hostname or '',
            'ips':          _ips_from_raw(s),
            'port_forward': bool(s.get('port_forward')),
            'server_types':  _server_types_from_raw(s),
        }
        if any(v for k, v in srv.items() if k != 'port_forward'):
            if srv['name']:
                existing = normalized_by_name.get(srv['name'])
                if existing:
                    existing['port_forward'] = bool(existing.get('port_forward') or srv['port_forward'])
                    existing_types = {
                        t for t in (existing.get('server_types') or '').split(',') if t
                    }
                    existing_types.update(t for t in (srv.get('server_types') or '').split(',') if t)
                    existing['server_types'] = ','.join(
                        t for t in _SERVER_TYPE_FIELDS if t in existing_types
                    )
                    if not existing.get('hostname') and srv.get('hostname'):
                        existing['hostname'] = srv['hostname']
                    if not existing.get('ips') and srv.get('ips'):
                        existing['ips'] = srv['ips']
                else:
                    normalized_by_name[srv['name']] = srv
            else:
                normalized_extra.append(srv)
    return list(normalized_by_name.values()) + normalized_extra


def _read_mounted_catalogue(root: str = _LOCAL_GLUETUN_DIR) -> dict[str, list[dict]]:
    """Read Gluetun's mounted catalogue, preferring the loaded aggregate file.

    `/gluetun/servers.json` is the catalogue Gluetun actually loaded and can
    contain Proton premium servers missing from the public provider JSON files.
    """
    result: dict[str, list[dict]] = {}
    aggregate = os.path.join(root, 'servers.json')
    if os.path.isfile(aggregate):
        try:
            with open(aggregate, encoding='utf-8') as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                for provider, provider_data in data.items():
                    if provider == 'version' or provider in _CAT_EXCLUDED:
                        continue
                    servers = provider_data.get('servers', []) if isinstance(provider_data, dict) else []
                    normalized = _normalize_server_list(servers)
                    if normalized:
                        result[provider.lower()] = normalized
        except Exception as exc:
            logger.warning('catalogue: cannot read mounted aggregate %s: %s', aggregate, exc)
        if result:
            return result

    for directory in (root, os.path.join(root, 'servers')):
        if not os.path.isdir(directory):
            continue
        for path in sorted(glob.glob(os.path.join(directory, '*.json'))):
            fname = os.path.basename(path)
            if fname == 'manifest.json':
                continue
            provider = fname[:-5].lower()
            if provider in _CAT_EXCLUDED:
                continue
            try:
                with open(path, encoding='utf-8') as fh:
                    data = json.load(fh)
                normalized = _normalize_server_list(data.get('servers', []))
            except Exception as exc:
                logger.warning('catalogue: cannot read mounted provider %s: %s', path, exc)
                continue
            if normalized:
                result[provider] = normalized
        if result:
            return result
    return result


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------

def _require_auth():
    """Return a 403 Response if the shared secret is set and the request
    does not supply it via the X-Sidecar-Token header."""
    if _SECRET and request.headers.get('X-Sidecar-Token') != _SECRET:
        from flask import abort
        abort(403)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.route('/health')
def health():
    _require_auth()
    try:
        resp = requests.get(_PROBE_URL, timeout=10)
        if resp.status_code == 200:
            ip = None
            for line in resp.text.splitlines():
                if line.startswith('ip='):
                    ip = line[3:].strip()
            return jsonify({'vpn': True, 'ip': ip})
    except Exception as exc:
        return jsonify({'vpn': False, 'error': str(exc)}), 503
    return jsonify({'vpn': False}), 503


# ---------------------------------------------------------------------------
# Ready — lightweight readiness probe (no VPN check)
# ---------------------------------------------------------------------------

@app.route('/ready')
def ready():
    _require_auth()
    return jsonify({'ok': True})


# ---------------------------------------------------------------------------
# Catalogue — read Gluetun per-provider JSON files from mounted volume
# ---------------------------------------------------------------------------

@app.route('/catalogue')
def catalogue():
    """
    Return the Gluetun server catalogue.

    Prefer a mounted /gluetun/servers.json from the user's Gluetun container
    (the exact catalogue Gluetun loaded), then fall back to the public
    gluetun-servers repository for installs without that volume.
    Requires X-Sidecar-Token header when SIDECAR_SECRET is set.
    Called by the Companion at the start of each benchmark cycle and on
    manual catalogue refresh.
    """
    _require_auth()

    local = _read_mounted_catalogue()
    if local:
        total = sum(len(v) for v in local.values())
        logger.info('catalogue: total %d servers from mounted Gluetun catalogue', total)
        return jsonify({'ok': True, 'providers': local, 'source': 'local'})

    # ── 1. List available provider files via GitHub API ──────────────────────
    try:
        gh_resp = requests.get(
            _GITHUB_API_URL,
            timeout=15,
            headers={'Accept': 'application/vnd.github.v3+json', 'User-Agent': 'gluetun-companion'},
        )
        gh_resp.raise_for_status()
        file_list = gh_resp.json()
    except Exception as exc:
        logger.error('catalogue: GitHub API error: %s', exc)
        return jsonify({
            'ok': False,
            'error': f'GitHub API unreachable: {exc}',
            'providers': {},
        }), 503

    # ── 2. Download and parse each provider JSON ─────────────────────────────
    result: dict[str, list] = {}

    for entry in file_list:
        fname = entry.get('name', '')
        if not fname.endswith('.json'):
            continue

        provider = fname[:-5].lower()   # strip .json → provider name

        if provider in _CAT_EXCLUDED:
            logger.info('catalogue: skipping %s (excluded)', provider)
            continue

        raw_url = f'{_GITHUB_RAW_URL}/{fname}'
        try:
            r = requests.get(raw_url, timeout=30, headers={'User-Agent': 'gluetun-companion'})
            r.raise_for_status()
            data = r.json()
        except Exception as exc:
            logger.warning('catalogue: cannot fetch %s: %s', fname, exc)
            continue

        normalized = _normalize_server_list(data.get('servers', []))
        if normalized:
            result[provider] = normalized
            logger.info('catalogue: %s → %d servers', provider, len(normalized))

    if not result:
        return jsonify({
            'ok': False,
            'error': 'No servers fetched from GitHub (check network access)',
            'providers': {},
        }), 404

    total = sum(len(v) for v in result.values())
    logger.info('catalogue: total %d servers from %d providers', total, len(result))
    return jsonify({'ok': True, 'providers': result})


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------

@app.route('/test', methods=['GET', 'POST'])
def test():
    _require_auth()
    duration       = max(4, min(60, int(request.args.get('duration', 8))))
    streams        = max(1, min(16, int(request.args.get('streams', 4))))
    method         = request.args.get('method', 'dual')
    iperf_fallback = request.args.get('iperf_fallback', '1') == '1'

    # Normalise legacy 'auto' value
    if method == 'auto':
        method = 'dual'

    result: dict = {
        'dl_ookla': None, 'ul_ookla': None, 'ookla_server': None,
        'dl_librespeed': None, 'ul_librespeed': None,
        'dl_iperf3': None, 'ul_iperf3': None, 'iperf_server': None,
    }

    if method == 'iperf3':
        dl, ul, srv = _try_iperf3(duration, streams)
        if dl is None:
            return jsonify({'error': 'iperf3 failed — all servers unreachable'}), 503
        result['dl_iperf3']    = dl
        result['ul_iperf3']    = ul
        result['iperf_server'] = srv

    elif method == 'ookla':
        dl, ul, srv = _ookla_run(duration)
        if dl is None and iperf_fallback:
            logger.info('Ookla failed — trying iperf3 fallback')
            dl, ul, srv2 = _try_iperf3(duration, streams)
            result['dl_iperf3']    = dl
            result['ul_iperf3']    = ul
            result['iperf_server'] = srv2
        else:
            result['dl_ookla']    = dl
            result['ul_ookla']    = ul
            result['ookla_server'] = srv
        if dl is None:
            return jsonify({'error': 'ookla failed and all fallbacks exhausted'}), 503

    elif method == 'librespeed':
        dl, ul = _librespeed_run(duration)
        if dl is None and iperf_fallback:
            logger.info('librespeed failed — trying iperf3 fallback')
            dl, ul, srv2 = _try_iperf3(duration, streams)
            result['dl_iperf3']    = dl
            result['ul_iperf3']    = ul
            result['iperf_server'] = srv2
        else:
            result['dl_librespeed'] = dl
            result['ul_librespeed'] = ul
        if dl is None:
            return jsonify({'error': 'librespeed failed and all fallbacks exhausted'}), 503

    else:  # dual
        _run_dual(duration, streams, iperf_fallback, result)
        if (result['dl_ookla'] is None and result['dl_librespeed'] is None
                and result['dl_iperf3'] is None):
            return jsonify({'error': 'all speed test sources failed'}), 503

    # download_mbps / upload_mbps = best value across all sources
    dl_values = [v for v in (result['dl_ookla'], result['dl_librespeed'], result['dl_iperf3']) if v]
    ul_values = [v for v in (result['ul_ookla'], result['ul_librespeed'], result['ul_iperf3']) if v]
    result['download_mbps'] = max(dl_values) if dl_values else None
    result['upload_mbps']   = max(ul_values) if ul_values else None
    result['method']        = method

    # Latency + stability + DNS + public IP — all in parallel
    with ThreadPoolExecutor(max_workers=4) as ex:
        fut_lat  = ex.submit(_measure_latency)
        fut_stab = ex.submit(_measure_stability, 20, 0.2)
        fut_dns  = ex.submit(_measure_dns)
        fut_ip   = ex.submit(_get_public_ip)

        result['latency_ms']     = fut_lat.result()
        stability                = fut_stab.result()
        result['dns_latency_ms'] = fut_dns.result()
        result['ip']             = fut_ip.result()

    if stability:
        result['jitter_ms']       = stability['jitter_ms']
        result['packet_loss_pct'] = stability['packet_loss_pct']
        result['ping_min_ms']     = stability.get('ping_min_ms')
        result['ping_max_ms']     = stability.get('ping_max_ms')
        logger.info(
            'stability → jitter=%.1f ms  loss=%.1f%%  min=%.0f ms  max=%.0f ms',
            stability['jitter_ms'], stability['packet_loss_pct'],
            stability.get('ping_min_ms') or 0, stability.get('ping_max_ms') or 0,
        )
    else:
        result['jitter_ms'] = result['packet_loss_pct'] = None
        result['ping_min_ms'] = result['ping_max_ms'] = None
        logger.warning('stability measurement failed — jitter/loss not available')

    return jsonify(result)


# ---------------------------------------------------------------------------
# Ping endpoint
# ---------------------------------------------------------------------------

@app.route('/ping', methods=['GET', 'POST'])
def ping_endpoint():
    """
    Probe one or more targets with TCP handshakes and return per-target
    jitter/loss stats. Companion calls this when the /test response doesn't
    include stability data (e.g. older sidecar image).

    TCP (not ICMP) is used so the measurement is immune to the concurrent-ICMP
    rate-limiting that some commercial VPNs apply (which otherwise fabricates
    packet loss on a healthy tunnel). The response schema is unchanged.

    Params:
      targets  — comma-separated IPs (default: 1.1.1.1,8.8.8.8,9.9.9.9)
      count    — handshakes per target (default: 20, range: 5–100)
      interval — seconds between handshakes (default: 0.2, range: 0.1–1.0)
    """
    _require_auth()
    targets_str = request.args.get('targets', ','.join(_STABILITY_TARGETS))
    targets     = [t.strip() for t in targets_str.split(',') if t.strip()]
    count       = max(5, min(100, int(request.args.get('count', 20))))
    interval    = max(0.1, min(1.0, float(request.args.get('interval', 0.2))))

    if not targets:
        return jsonify({'error': 'no targets specified'}), 400

    ping_results = []
    with ThreadPoolExecutor(max_workers=len(targets)) as ex:
        futures = {ex.submit(_tcp_probe_target, t, count, interval): t for t in targets}
        for fut in as_completed(futures):
            r = fut.result()
            if r:
                ping_results.append(r)

    return jsonify({'results': ping_results})


# ---------------------------------------------------------------------------
# TCP-handshake stability probe
# ---------------------------------------------------------------------------
#
# Why TCP and not ICMP: the previous implementation shelled out to `ping` and
# measured ICMP echo loss. Commercial VPNs such as ProtonVPN rate-limit
# *concurrent* ICMP, so probing three resolvers in parallel starved two of the
# three flows (~90 % loss each) while the tunnel itself was perfectly healthy
# (0 % loss, stable RTT over TCP/HTTP). Averaging the per-target losses then
# reported ~60 % loss — a pure artifact. TCP SYN handshakes are not subject to
# that rate-limit, so they measure real reachability and latency variability.
# The output schema is byte-for-byte identical to the old ICMP path.


def _tcp_connect_once(ip: str, port: int, timeout: float) -> float:
    """Open a TCP connection to (ip, port) and return the handshake RTT in ms.

    A completed handshake (SYN → SYN/ACK → ACK) and a refused connection (RST)
    both prove the host is reachable, so both yield a valid RTT sample. Only a
    timeout or an unreachable route raises (OSError) — those are the genuine
    "loss" cases the caller counts.
    """
    t0 = time.perf_counter()
    try:
        socket.create_connection((ip, port), timeout=timeout).close()
    except ConnectionRefusedError:
        pass  # RST received → reachable; the round-trip to the RST is a valid RTT
    return (time.perf_counter() - t0) * 1000.0


def _tcp_probe_samples(
    target: str,
    count: int,
    interval: float,
    ports: list[int] | None = None,
    timeout: float = _STABILITY_TIMEOUT,
) -> dict:
    """Probe `target` with `count` sequential TCP handshakes.

    The first reachable port in `ports` is negotiated once and reused for the
    remaining samples. If no port answers on a sample, later samples fall back
    to the first port only, which bounds the time spent on a fully unreachable
    target.

    Returns raw counters so callers can pool them correctly across targets:
        {'target': str, 'rtts': [float, ...], 'attempts': int, 'failures': int}
    """
    ports = ports or _STABILITY_PORTS
    rtts: list[float] = []
    attempts = 0
    failures = 0
    port: int | None = None

    for i in range(count):
        attempts += 1
        candidates = [port] if port is not None else ports
        rtt = None
        for candidate in candidates:
            try:
                rtt = _tcp_connect_once(target, candidate, timeout)
                port = candidate            # lock onto the port that answered
                break
            except OSError:
                continue
        if rtt is None:
            failures += 1
            if port is None:
                port = ports[0]             # bound time on an unreachable target
        else:
            rtts.append(rtt)
        if interval and i < count - 1:
            time.sleep(interval)

    logger.info('tcp-probe %s:%s → %d/%d ok', target, port, attempts - failures, attempts)
    return {'target': target, 'rtts': rtts, 'attempts': attempts, 'failures': failures}


def _stats_from_samples(rtts: list[float], attempts: int, failures: int) -> dict:
    """Turn one target's raw samples into the per-target stability schema.

    jitter_ms is the population stddev of the handshake RTTs (0.0 when only one
    sample succeeded, None when none did); packet_loss_pct is failures/attempts.
    """
    loss = round(100.0 * failures / attempts, 1) if attempts else None
    if rtts:
        return {
            'jitter_ms':       round(pstdev(rtts), 1) if len(rtts) > 1 else 0.0,
            'packet_loss_pct': loss,
            'ping_min_ms':     round(min(rtts), 1),
            'ping_max_ms':     round(max(rtts), 1),
        }
    return {
        'jitter_ms':       None,
        'packet_loss_pct': loss,
        'ping_min_ms':     None,
        'ping_max_ms':     None,
    }


def _tcp_probe_target(target: str, count: int, interval: float) -> dict | None:
    """Probe one target and return its per-target stability stats for /ping:
    {target, jitter_ms, packet_loss_pct, ping_min_ms, ping_max_ms}, or None if
    the probe could not run at all.
    """
    samples = _tcp_probe_samples(target, count, interval)
    if samples['attempts'] == 0:
        return None
    stats = _stats_from_samples(samples['rtts'], samples['attempts'], samples['failures'])
    return {'target': target, **stats}


def _aggregate_stability(samples_list: list[dict]) -> dict | None:
    """Aggregate per-target raw samples into the single stability dict for /test.

    packet_loss_pct is POOLED — Σ failures / Σ attempts — not the mean of the
    per-target loss percentages. That mean is exactly what fabricated ~60 % loss
    under ICMP rate-limiting and would over-weight a single unreachable target.
    jitter_ms is the mean of each target's RTT stddev, which isolates real
    variability from the baseline-RTT differences between targets. min/max are
    global across every successful handshake. Returns None when no target
    produced a usable RTT sample (preserving the old "no data" contract).
    """
    total_attempts = sum(s['attempts'] for s in samples_list)
    total_failures = sum(s['failures'] for s in samples_list)
    all_rtts = [r for s in samples_list for r in s['rtts']]

    if total_attempts == 0 or not all_rtts:
        return None

    per_target_jitter = [pstdev(s['rtts']) for s in samples_list if len(s['rtts']) > 1]
    return {
        'jitter_ms':       round(sum(per_target_jitter) / len(per_target_jitter), 1) if per_target_jitter else 0.0,
        'packet_loss_pct': round(100.0 * total_failures / total_attempts, 1),
        'ping_min_ms':     round(min(all_rtts), 1),
        'ping_max_ms':     round(max(all_rtts), 1),
    }


def _measure_stability(count: int = 20, interval: float = 0.2) -> dict | None:
    """Probe _STABILITY_TARGETS in parallel (one thread per target, sequential
    handshakes within each — TCP is not ICMP-rate-limited, so this stays safe)
    and aggregate. Returns {jitter_ms, packet_loss_pct, ping_min_ms,
    ping_max_ms} or None when no target produced a usable sample.
    """
    samples: list[dict] = []
    with ThreadPoolExecutor(max_workers=len(_STABILITY_TARGETS)) as ex:
        futures = {ex.submit(_tcp_probe_samples, t, count, interval): t
                   for t in _STABILITY_TARGETS}
        for fut in as_completed(futures):
            try:
                samples.append(fut.result())
            except Exception as exc:
                logger.warning('tcp-probe failed: %s', exc)

    # The /test handler logs the aggregate line; per-target lines come from
    # _tcp_probe_samples, so no aggregate logging is needed here.
    return _aggregate_stability(samples)


# ---------------------------------------------------------------------------
# Dual parallel runner
# ---------------------------------------------------------------------------

def _run_dual(duration: int, streams: int, iperf_fallback: bool, result: dict) -> None:
    """Run Ookla + librespeed in parallel; mutates `result` in place."""
    with ThreadPoolExecutor(max_workers=2) as ex:
        fut_ookla = ex.submit(_ookla_run, duration)
        fut_libre = ex.submit(_librespeed_run, duration)

        futures = {fut_ookla: 'ookla', fut_libre: 'libre'}
        for fut in as_completed(futures):
            kind = futures[fut]
            try:
                if kind == 'ookla':
                    dl, ul, srv = fut.result()
                    result['dl_ookla']     = dl
                    result['ul_ookla']     = ul
                    result['ookla_server'] = srv
                else:
                    dl, ul = fut.result()
                    result['dl_librespeed'] = dl
                    result['ul_librespeed'] = ul
            except Exception as exc:
                logger.warning('Parallel %s failed: %s', kind, exc)

    # Both failed → try iperf3 as fallback
    if result['dl_ookla'] is None and result['dl_librespeed'] is None and iperf_fallback:
        logger.info('Ookla + librespeed both failed — trying iperf3 fallback')
        dl, ul, srv = _try_iperf3(duration, streams)
        result['dl_iperf3']    = dl
        result['ul_iperf3']    = ul
        result['iperf_server'] = srv


# ---------------------------------------------------------------------------
# Ookla Speedtest CLI
# ---------------------------------------------------------------------------

def _ookla_run(duration: int) -> tuple[float | None, float | None, str | None]:
    try:
        cmd = [
            'speedtest',
            '--accept-license', '--accept-gdpr',
            '--format=json',
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=duration * 3 + 120)

        result_obj = None
        for line in r.stdout.strip().splitlines():
            try:
                obj = json.loads(line)
                if obj.get('type') == 'result':
                    result_obj = obj
            except Exception:
                pass

        if not result_obj:
            raise RuntimeError(
                f'no result in ookla output (exit {r.returncode}): {r.stdout[:200]}'
            )

        dl = round(result_obj['download']['bandwidth'] * 8 / 1_000_000, 2)
        ul = round(result_obj['upload']['bandwidth'] * 8 / 1_000_000, 2)

        srv_name = result_obj.get('server', {}).get('name', '')
        srv_loc  = result_obj.get('server', {}).get('location', '')
        srv_str  = f'{srv_name}, {srv_loc}' if srv_loc else srv_name

        logger.info('ookla → DL %.1f  UL %.1f Mbps  [%s]', dl, ul, srv_str)
        return dl or None, ul or None, srv_str or None

    except Exception as exc:
        logger.warning('ookla failed: %s', exc)
        return None, None, None


# ---------------------------------------------------------------------------
# librespeed
# ---------------------------------------------------------------------------

def _librespeed_run(duration: int) -> tuple[float | None, float | None]:
    try:
        cmd = [
            'librespeed-cli',
            '--json',
            '--no-icmp',
            '--telemetry-level', 'disabled',
            '--duration', str(duration),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=duration + 60)
        if r.returncode != 0:
            raise RuntimeError(f'librespeed-cli exit {r.returncode}: {(r.stderr or "")[:120]}')
        data = json.loads(r.stdout)
        if isinstance(data, list):
            data = data[0] if data else None
        if not data:
            raise RuntimeError('empty or null librespeed output')
        dl = round(float(data.get('download', 0)), 2)
        ul = round(float(data.get('upload', 0)), 2)
        logger.info('librespeed → DL %.1f  UL %.1f Mbps', dl, ul)
        return dl or None, ul or None
    except Exception as exc:
        logger.warning('librespeed failed: %s', exc)
        return None, None


# ---------------------------------------------------------------------------
# iperf3
# ---------------------------------------------------------------------------

def _iperf3_run(host: str, port: int, duration: int, streams: int, reverse: bool) -> dict:
    cmd = [
        'iperf3', '-c', host, '-p', str(port),
        '-t', str(duration), '-P', str(streams),
        '--connect-timeout', '5000',
        '-J',
    ]
    if reverse:
        cmd.append('-R')
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=duration + 10)
    if r.returncode != 0:
        stderr = (r.stderr or '').strip()
        raise RuntimeError(f'iperf3 exit {r.returncode}: {stderr[:120]}')
    return json.loads(r.stdout)


def _try_iperf3(duration: int, streams: int) -> tuple[float | None, float | None, str | None]:
    for host, port in _IPERF3_SERVERS:
        try:
            dl_data = _iperf3_run(host, port, duration, streams, reverse=True)
            dl_bps  = dl_data['end']['sum_received']['bits_per_second']

            ul_data = _iperf3_run(host, port, duration, streams, reverse=False)
            ul_bps  = ul_data['end']['sum_sent']['bits_per_second']

            dl = round(dl_bps / 1e6, 2)
            ul = round(ul_bps / 1e6, 2)
            logger.info('iperf3 %s → DL %.1f  UL %.1f Mbps', host, dl, ul)
            return dl, ul, host

        except Exception as exc:
            logger.warning('iperf3 %s:%d failed: %s', host, port, exc)
            continue

    return None, None, None


# ---------------------------------------------------------------------------
# DNS latency
# ---------------------------------------------------------------------------

# Domains chosen to be unlikely to be blocked or short-circuited by VPN DNS
_DNS_DOMAINS = ['google.com', 'cloudflare.com', 'github.com', 'reddit.com']


def _measure_dns() -> float | None:
    """
    Measure VPN DNS latency using `dig` against the system resolver.
    In sidecar mode the system resolver is the VPN's DNS — this detects
    slow, filtered, or redirected DNS (abnormally fast = cached/hijacked;
    abnormally slow = overloaded or geographically distant resolver).

    Runs 4 queries in parallel; returns median resolution time in ms.
    Returns None if dig is unavailable or all probes fail.
    """
    def _dig_once(domain: str) -> float | None:
        try:
            r = subprocess.run(
                ['dig', domain, '+time=2', '+tries=1'],
                capture_output=True, text=True, timeout=5,
            )
            m = re.search(r'Query time:\s+(\d+)\s+msec', r.stdout)
            return float(m.group(1)) if m else None
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=len(_DNS_DOMAINS)) as ex:
        values = [v for v in ex.map(_dig_once, _DNS_DOMAINS) if v is not None]

    if not values:
        return None
    result_ms = round(median(values), 1)
    logger.info('dns → median=%.0f ms  samples=%s', result_ms, values)
    return result_ms


# ---------------------------------------------------------------------------
# Latency + public IP
# ---------------------------------------------------------------------------

def _measure_latency() -> float | None:
    endpoints = [
        'https://www.cloudflare.com/cdn-cgi/trace',
        'https://www.google.com/generate_204',
        'https://fsn1-speed.hetzner.com/1MB.bin',
    ]
    values: list[float] = []
    for url in endpoints:
        try:
            t0   = time.perf_counter()
            resp = requests.get(url, stream=True, timeout=10,
                                headers={'User-Agent': 'gluetun-companion-sidecar/1.0'})
            next(resp.iter_content(chunk_size=1), None)
            resp.close()
            values.append((time.perf_counter() - t0) * 1000)
        except Exception:
            pass
    return round(median(values), 1) if values else None


def _get_public_ip() -> str | None:
    try:
        resp = requests.get(_PROBE_URL, timeout=10)
        for line in resp.text.splitlines():
            if line.startswith('ip='):
                return line[3:].strip()
    except Exception:
        pass
    return None


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8766, debug=False)
