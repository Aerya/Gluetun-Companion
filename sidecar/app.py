"""
Gluetun Companion — speed-test sidecar.

This container runs inside the VPN network namespace of a cloned Gluetun container
(network_mode: container:<gluetun-test>). Traffic goes through the VPN tunnel directly —
no HTTP proxy involved.

API
---
GET  /health           → {"vpn": true, "ip": "x.x.x.x"}  (503 if VPN not up)
POST /test?duration=8&streams=4&method=auto
                       → {"download_mbps":…, "upload_mbps":…, "latency_ms":…,
                           "method":"iperf3|librespeed", "ip":…}

method values:
  auto        — try iperf3 first, fall back to librespeed if all iperf3 servers fail
  iperf3      — iperf3 only (error 503 if all servers unreachable)
  librespeed  — librespeed-cli only
"""

import json
import logging
import subprocess
import time

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
    duration = max(4, min(60, int(request.args.get('duration', 8))))
    streams  = max(1, min(16, int(request.args.get('streams', 4))))
    method   = request.args.get('method', 'auto')

    result: dict = {}

    if method == 'iperf3':
        dl_mbps, ul_mbps, iperf_server = _try_iperf3(duration, streams)
        if dl_mbps is None:
            return jsonify({'error': 'iperf3 failed — all servers unreachable'}), 503
        result['method']        = 'iperf3'
        result['iperf_server']  = iperf_server
        result['download_mbps'] = dl_mbps
        result['upload_mbps']   = ul_mbps

    elif method == 'librespeed':
        dl_mbps, ul_mbps = _librespeed_run(duration)
        if dl_mbps is None:
            return jsonify({'error': 'librespeed failed'}), 503
        result['method']        = 'librespeed'
        result['download_mbps'] = dl_mbps
        result['upload_mbps']   = ul_mbps

    else:  # auto
        dl_mbps, ul_mbps, iperf_server = _try_iperf3(duration, streams)
        if dl_mbps is not None:
            result['method']        = 'iperf3'
            result['iperf_server']  = iperf_server
            result['download_mbps'] = dl_mbps
            result['upload_mbps']   = ul_mbps
        else:
            logger.info('iperf3 unavailable — falling back to librespeed')
            dl_mbps, ul_mbps = _librespeed_run(duration)
            if dl_mbps is None:
                return jsonify({'error': 'both iperf3 and librespeed failed'}), 503
            result['method']        = 'librespeed'
            result['download_mbps'] = dl_mbps
            result['upload_mbps']   = ul_mbps

    result['latency_ms'] = _measure_latency()

    try:
        resp = requests.get(_PROBE_URL, timeout=10)
        for line in resp.text.splitlines():
            if line.startswith('ip='):
                result['ip'] = line[3:].strip()
    except Exception:
        pass

    return jsonify(result)


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
            data = data[0]
        dl = round(float(data.get('download', 0)), 2)
        ul = round(float(data.get('upload', 0)), 2)
        logger.info('librespeed → DL %.1f  UL %.1f Mbps', dl, ul)
        return dl or None, ul or None
    except Exception as exc:
        logger.warning('librespeed failed: %s', exc)
        return None, None


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
