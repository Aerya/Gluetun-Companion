"""
Gluetun Companion — speed-test sidecar.

This container runs inside the VPN network namespace of a cloned Gluetun container
(network_mode: container:<gluetun-test>). Traffic goes through the VPN tunnel directly —
no HTTP proxy involved.

API
---
GET  /health           → {"vpn": true, "ip": "x.x.x.x"}  (503 if VPN not up)
POST /test?duration=8&streams=4
                       → {"download_mbps":…, "upload_mbps":…, "latency_ms":…,
                           "method":"iperf3|http", "ip":…}
"""

import json
import logging
import os
import subprocess
import time
import threading
from statistics import median

import requests
from flask import Flask, jsonify, request

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format='%(levelname)s %(name)s %(message)s')
logger = logging.getLogger(__name__)

_PROBE_URL = 'https://www.cloudflare.com/cdn-cgi/trace'

# Public iperf3 servers tried in order — first one that responds wins
_IPERF3_SERVERS: list[tuple[str, int]] = [
    ('bouygues.iperf.fr',    5209),
    ('ping.online.net',      5209),
    ('speedtest.wtnet.de',   5200),
    ('iperf.he.net',         5201),
    ('speedtest.uztelecom.uz', 5200),
]

# HTTP direct-download endpoints (used when iperf3 fails)
_DL_ENDPOINTS: list[tuple[str, str]] = [
    ('Cloudflare', 'https://speed.cloudflare.com/__down?bytes=209715200'),
    ('Hetzner-DE', 'https://fsn1-speed.hetzner.com/100MB.bin'),
    ('OVH-FR',     'https://proof.ovh.net/files/100Mb.dat'),
]
_UL_ENDPOINT = 'https://speed.cloudflare.com/__up'

_UPLOAD_CHUNK = os.urandom(65_536)

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

    result: dict = {}

    dl_mbps, ul_mbps, iperf_server = _try_iperf3(duration, streams)
    if dl_mbps is not None:
        result['method']       = 'iperf3'
        result['iperf_server'] = iperf_server
        result['download_mbps'] = dl_mbps
        result['upload_mbps']   = ul_mbps
        logger.info('iperf3 %s → DL %.1f  UL %s Mbps',
                    iperf_server, dl_mbps,
                    f'{ul_mbps:.1f}' if ul_mbps else '—')
    else:
        logger.info('iperf3 unavailable — falling back to HTTP')
        dl_mbps, ul_mbps = _http_test(duration, streams)
        result['method']       = 'http'
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
# iperf3 helpers
# ---------------------------------------------------------------------------

def _iperf3_run(host: str, port: int, duration: int, streams: int, reverse: bool) -> dict:
    cmd = [
        'iperf3', '-c', host, '-p', str(port),
        '-t', str(duration), '-P', str(streams),
        '--connect-timeout', '5000',   # 5 s max to establish connection
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
            # Download (server→client, reverse mode)
            dl_data = _iperf3_run(host, port, duration, streams, reverse=True)
            dl_bps  = dl_data['end']['sum_received']['bits_per_second']

            # Upload (client→server)
            ul_data = _iperf3_run(host, port, duration, streams, reverse=False)
            ul_bps  = ul_data['end']['sum_sent']['bits_per_second']

            return round(dl_bps / 1e6, 2), round(ul_bps / 1e6, 2), host

        except Exception as exc:
            logger.warning('iperf3 %s:%d failed: %s', host, port, exc)
            continue

    return None, None, None


# ---------------------------------------------------------------------------
# HTTP fallback helpers
# ---------------------------------------------------------------------------

def _stream_dl(url: str, duration: float, cap: int = 150 * 1024 * 1024) -> float:
    received = 0
    start = time.perf_counter()
    resp = requests.get(url, stream=True, timeout=duration + 15,
                        headers={'User-Agent': 'gluetun-companion-sidecar/1.0'})
    resp.raise_for_status()
    for chunk in resp.iter_content(chunk_size=131_072):
        received += len(chunk)
        if received >= cap or (time.perf_counter() - start) >= duration:
            break
    elapsed = time.perf_counter() - start
    if received < 512 * 1024 or elapsed < 0.5:
        raise RuntimeError(f'Insufficient data: {received // 1024} KB in {elapsed:.1f}s')
    return round((received * 8) / (elapsed * 1e6), 2)


def _parallel_dl(url: str, duration: float, streams: int) -> float:
    speeds: list[float | None] = [None] * streams
    errors: list[str] = []

    def _worker(idx: int):
        try:
            speeds[idx] = _stream_dl(url, duration)
        except Exception as exc:
            errors.append(str(exc))

    threads = [threading.Thread(target=_worker, args=(i,), daemon=True) for i in range(streams)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=duration + 20)
    good = [s for s in speeds if s is not None]
    if not good:
        raise RuntimeError('All streams failed: ' + ' | '.join(set(errors)))
    return round(sum(good), 2)


def _stream_ul(url: str, duration: float, cap: int = 150 * 1024 * 1024) -> float:
    sent = [0]
    t0   = [None]

    def _gen():
        t0[0] = time.perf_counter()
        while sent[0] < cap and (time.perf_counter() - t0[0]) < duration:
            yield _UPLOAD_CHUNK
            sent[0] += len(_UPLOAD_CHUNK)

    try:
        requests.post(url, data=_gen(), timeout=duration + 15,
                      headers={'Content-Type': 'application/octet-stream',
                               'User-Agent': 'gluetun-companion-sidecar/1.0'})
    except requests.exceptions.ChunkedEncodingError:
        pass

    if t0[0] is None:
        raise RuntimeError('Upload stream never started')
    elapsed = time.perf_counter() - t0[0]
    if sent[0] < 512 * 1024 or elapsed < 0.5:
        raise RuntimeError(f'Insufficient upload: {sent[0] // 1024} KB')
    return round((sent[0] * 8) / (elapsed * 1e6), 2)


def _parallel_ul(url: str, duration: float, streams: int) -> float:
    speeds: list[float | None] = [None] * streams
    errors: list[str] = []

    def _worker(idx: int):
        try:
            speeds[idx] = _stream_ul(url, duration)
        except Exception as exc:
            errors.append(str(exc))

    threads = [threading.Thread(target=_worker, args=(i,), daemon=True) for i in range(streams)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=duration + 20)
    good = [s for s in speeds if s is not None]
    if not good:
        raise RuntimeError('All streams failed: ' + ' | '.join(set(errors)))
    return round(sum(good), 2)


def _http_test(duration: float, streams: int) -> tuple[float, float | None]:
    dl_speeds: list[float] = []
    for label, url in _DL_ENDPOINTS:
        try:
            mbps = _parallel_dl(url, duration, streams)
            dl_speeds.append(mbps)
            logger.info('HTTP DL %s ×%d → %.1f Mbps', label, streams, mbps)
        except Exception as exc:
            logger.warning('HTTP DL %s failed: %s', label, exc)

    ul_mbps: float | None = None
    try:
        ul_mbps = _parallel_ul(_UL_ENDPOINT, duration, streams)
        logger.info('HTTP UL ×%d → %.1f Mbps', streams, ul_mbps)
    except Exception as exc:
        logger.warning('HTTP UL failed: %s', exc)

    dl = round(median(dl_speeds), 2) if dl_speeds else 0.0
    return dl, ul_mbps


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
    return round(median(values), 1) if values else 0.0


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8766, debug=False)
