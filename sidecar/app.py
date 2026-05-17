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
                           "iperf_server": null
                         }

method values:
  dual        — Ookla + librespeed in parallel; iperf3 fallback if both fail (when iperf_fallback=1)
  ookla       — Ookla only; iperf3 fallback if it fails (when iperf_fallback=1)
  librespeed  — librespeed-cli only; iperf3 fallback if it fails (when iperf_fallback=1)
  iperf3      — iperf3 only (no fallback)
"""

import json
import logging
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from flask import Flask, jsonify, request

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format='%(levelname)s %(name)s %(message)s')
logger = logging.getLogger(__name__)

_PROBE_URL = 'https://www.cloudflare.com/cdn-cgi/trace'

# Public iperf3 servers tried in order — first one that responds wins
_IPERF3_SERVERS: list[tuple[str, int]] = [
    ('bouygues.iperf.fr',      5209),
    ('ping.online.net',        5209),
    ('speedtest.wtnet.de',     5200),
    ('iperf.he.net',           5201),
    ('speedtest.uztelecom.uz', 5200),
]


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.route('/health')
def health():
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
# Test
# ---------------------------------------------------------------------------

@app.route('/test', methods=['GET', 'POST'])
def test():
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
        # Check that at least one source succeeded
        if (result['dl_ookla'] is None and result['dl_librespeed'] is None
                and result['dl_iperf3'] is None):
            return jsonify({'error': 'all speed test sources failed'}), 503

    # download_mbps / upload_mbps = best value across all sources (used for server ranking)
    dl_values = [v for v in (result['dl_ookla'], result['dl_librespeed'], result['dl_iperf3']) if v]
    ul_values = [v for v in (result['ul_ookla'], result['ul_librespeed'], result['ul_iperf3']) if v]
    result['download_mbps'] = max(dl_values) if dl_values else None
    result['upload_mbps']   = max(ul_values) if ul_values else None
    result['method']        = method
    result['latency_ms']    = _measure_latency()

    try:
        resp = requests.get(_PROBE_URL, timeout=10)
        for line in resp.text.splitlines():
            if line.startswith('ip='):
                result['ip'] = line[3:].strip()
    except Exception:
        pass

    return jsonify(result)


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
        # Ookla controls its own test duration; give generous subprocess timeout
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
# Latency
# ---------------------------------------------------------------------------

def _measure_latency() -> float:
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
    from statistics import median
    return round(median(values), 1) if values else 0.0


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8766, debug=False)
