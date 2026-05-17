"""
Speed testing through a Gluetun HTTP proxy.

Strategy
--------
Download: timed streaming with optional warm-up. We optionally drain `warmup`
seconds before starting the clock so TCP slow-start and proxy handshake don't
skew the first sample. Then we stream for `duration` seconds or `cap_bytes`
bytes, whichever comes first. Speed = actual bytes received / actual elapsed.

Upload: POST random data to Cloudflare's __up endpoint via the proxy. We
generate data on-the-fly and stop after `duration` seconds; speed is computed
from bytes yielded / elapsed measured inside the generator.

Latency: TTFB (TCP connect + TLS + first-byte) via a tiny HTTP GET.

Multiple diverse endpoints → median returned, so one outlier doesn't dominate.
"""

import logging
import os
import re
import threading
import time
from statistics import median
from urllib.parse import quote

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Endpoint catalogues
# ---------------------------------------------------------------------------

DOWNLOAD_ENDPOINTS: list[tuple[str, str]] = [
    ('Cloudflare',  'https://speed.cloudflare.com/__down?bytes={size}'),
    ('Hetzner-DE',  'https://fsn1-speed.hetzner.com/100MB.bin'),
    ('Fast.com',    'fastcom://'),
    ('OVH-FR',      'https://proof.ovh.net/files/100Mb.dat'),
    ('Tele2',       'https://speedtest.tele2.net/100MB.zip'),
]

UPLOAD_ENDPOINTS: list[tuple[str, str]] = [
    ('Cloudflare', 'https://speed.cloudflare.com/__up'),
]

LATENCY_ENDPOINTS: list[tuple[str, str]] = [
    ('Cloudflare', 'https://www.cloudflare.com/cdn-cgi/trace'),
    ('Google',     'https://www.google.com/generate_204'),
    ('Hetzner-DE', 'https://fsn1-speed.hetzner.com/1MB.bin'),
    ('OVH-FR',     'https://proof.ovh.net/files/1Mb.dat'),
]

# Cloudflare: request enough bytes to survive warmup + measurement at high speeds
_CF_SIZE = 400 * 1024 * 1024   # 400 MB virtual stream

# Pre-generated random chunk for upload (64 KB)
_UPLOAD_CHUNK = os.urandom(65_536)


# ---------------------------------------------------------------------------
# Proxy helpers
# ---------------------------------------------------------------------------

def _proxies(
    host: str,
    port: int,
    user: str | None = None,
    password: str | None = None,
) -> dict:
    if user:
        creds = f'{quote(user, safe="")}:{quote(password or "", safe="")}@'
    else:
        creds = ''
    proxy = f'http://{creds}{host}:{port}'
    return {'http': proxy, 'https': proxy}


# ---------------------------------------------------------------------------
# Fast.com dynamic URL resolution
# ---------------------------------------------------------------------------

_FASTCOM_FALLBACK_TOKEN = 'YXNkZmFzZGxmbnNkYWZoYXNkZmhrYWxm'
_fastcom_cache: dict = {'token': None, 'ts': 0.0}
_fastcom_lock  = threading.Lock()
_FASTCOM_TTL   = 3600


def _get_fastcom_token(px: dict) -> str:
    with _fastcom_lock:
        now = time.time()
        if _fastcom_cache['token'] and now - _fastcom_cache['ts'] < _FASTCOM_TTL:
            return _fastcom_cache['token']
        try:
            hdrs = {'User-Agent': 'Mozilla/5.0 (compatible; gluetun-companion/1.0)'}
            home = requests.get('https://fast.com/', proxies=px, timeout=10, headers=hdrs)
            m = re.search(r'/app-[a-f0-9]+\.js', home.text)
            if not m:
                raise ValueError('JS bundle not found')
            js = requests.get('https://fast.com' + m.group(0), proxies=px, timeout=10, headers=hdrs)
            tm = re.search(r'token:"([A-Za-z0-9+/=]{20,})"', js.text)
            if not tm:
                raise ValueError('token not found in JS')
            token = tm.group(1)
            _fastcom_cache['token'] = token
            _fastcom_cache['ts'] = now
            logger.debug('Fast.com token refreshed: %s…', token[:8])
            return token
        except Exception as exc:
            logger.warning('Fast.com token fetch failed (%s) — using fallback', exc)
            return _FASTCOM_FALLBACK_TOKEN


def _resolve_fastcom_url(px: dict) -> str:
    token = _get_fastcom_token(px)
    api = (
        f'https://api.fast.com/netflix/speedtest/v2'
        f'?https=true&token={token}&urlCount=1'
    )
    resp = requests.get(api, proxies=px, timeout=10,
                        headers={'User-Agent': 'Mozilla/5.0 (compatible; gluetun-companion/1.0)'})
    resp.raise_for_status()
    targets = resp.json().get('targets') or []
    if not targets:
        raise RuntimeError('Fast.com API returned no targets')
    return targets[0]['url']


# ---------------------------------------------------------------------------
# Core measurement primitives
# ---------------------------------------------------------------------------

def _stream_speed(
    url: str,
    px: dict,
    duration: float,
    cap_bytes: int,
    min_bytes: int = 512 * 1024,
    warmup: float = 0.0,
) -> float:
    """
    Stream from `url` through proxy `px`.
    Optional `warmup` seconds are drained first (not counted) so TCP slow-start
    and proxy overhead don't bias the measurement.
    Returns speed in Mbps. Raises if insufficient data received.
    """
    received = 0
    conn_start = time.perf_counter()
    # If no warmup, measurement starts immediately
    meas_start: float | None = conn_start if warmup <= 0 else None

    try:
        resp = requests.get(
            url,
            proxies=px,
            stream=True,
            timeout=duration + max(warmup, 0) + 15,
            headers={'User-Agent': 'gluetun-companion/1.0'},
        )
        resp.raise_for_status()
        for chunk in resp.iter_content(chunk_size=131_072):
            now = time.perf_counter()
            if meas_start is None:
                # Still in warmup phase
                if (now - conn_start) >= warmup:
                    meas_start = now
                continue   # don't count warmup bytes
            received += len(chunk)
            if received >= cap_bytes or (now - meas_start) >= duration:
                break
    except requests.exceptions.ChunkedEncodingError:
        pass   # server closed early — still count what we got

    if meas_start is None:
        raise RuntimeError('Warmup phase not completed (server too slow?)')
    elapsed = time.perf_counter() - meas_start
    if received < min_bytes or elapsed < 0.5:
        raise RuntimeError(
            f'Insufficient data: {received / 1024:.0f} KB in {elapsed:.1f}s'
        )
    return round((received * 8) / (elapsed * 1_000_000), 2)


def _stream_upload(
    url: str,
    px: dict,
    duration: float,
    cap_bytes: int,
    min_bytes: int = 512 * 1024,
) -> float:
    """
    POST random data to `url` through proxy for `duration` seconds.

    elapsed is measured from first byte generated to server response received,
    NOT from generator start to generator end. This avoids over-estimation caused
    by local socket buffering (companion→proxy loopback is near-infinite speed;
    the real bottleneck is the VPN tunnel, whose back-pressure only appears once
    OS buffers fill up, which can take hundreds of ms at gigabit loopback speeds).

    Measuring until the server acknowledges receipt gives an accurate end-to-end
    throughput at the cost of one RTT overhead (~1–2% error at typical VPN latency).
    """
    sent = [0]
    t0 = [None]

    def _gen():
        t0[0] = time.perf_counter()
        while sent[0] < cap_bytes and (time.perf_counter() - t0[0]) < duration:
            yield _UPLOAD_CHUNK
            sent[0] += len(_UPLOAD_CHUNK)

    try:
        requests.post(
            url,
            data=_gen(),
            proxies=px,
            timeout=duration + 15,
            headers={
                'Content-Type': 'application/octet-stream',
                'User-Agent': 'gluetun-companion/1.0',
            },
        )
    except requests.exceptions.ChunkedEncodingError:
        pass

    if t0[0] is None:
        raise RuntimeError('Upload stream never started')
    # elapsed = generator start → server response (end-to-end, not generator exit)
    elapsed = time.perf_counter() - t0[0]
    total_sent = sent[0]
    if total_sent < min_bytes or elapsed < 0.5:
        raise RuntimeError(f'Insufficient upload: {total_sent / 1024:.0f} KB in {elapsed:.1f}s')
    return round((total_sent * 8) / (elapsed * 1_000_000), 2)


def _parallel_stream_speed(
    url: str,
    px: dict,
    duration: float,
    cap_bytes: int,
    streams: int,
    min_bytes: int = 512 * 1024,
    warmup: float = 0.0,
) -> float:
    """
    Launch `streams` concurrent downloads from `url` and sum their individual speeds.
    Each worker measures its own bytes/elapsed independently; total = Σ Mbps.
    This saturates the VPN tunnel the same way a multi-connection download manager would.
    """
    speeds: list[float | None] = [None] * streams
    errors: list[str] = []

    def _worker(idx: int):
        try:
            speeds[idx] = _stream_speed(
                url, px,
                duration=duration,
                cap_bytes=cap_bytes,
                min_bytes=min_bytes,
                warmup=warmup,
            )
        except Exception as exc:
            errors.append(str(exc))

    threads = [threading.Thread(target=_worker, args=(i,), daemon=True) for i in range(streams)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=duration + max(warmup, 0) + 20)

    good = [s for s in speeds if s is not None]
    if not good:
        raise RuntimeError('All parallel streams failed: ' + '; '.join(errors))
    return round(sum(good), 2)


def _parallel_stream_upload(
    url: str,
    px: dict,
    duration: float,
    cap_bytes: int,
    streams: int,
    min_bytes: int = 512 * 1024,
) -> float:
    """
    Launch `streams` concurrent uploads to `url` and sum their individual speeds.
    Each worker POSTs independently; total = Σ Mbps.
    """
    speeds: list[float | None] = [None] * streams
    errors: list[str] = []

    def _worker(idx: int):
        try:
            speeds[idx] = _stream_upload(
                url, px,
                duration=duration,
                cap_bytes=cap_bytes,
                min_bytes=min_bytes,
            )
        except Exception as exc:
            errors.append(str(exc))

    threads = [threading.Thread(target=_worker, args=(i,), daemon=True) for i in range(streams)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=duration + 20)

    good = [s for s in speeds if s is not None]
    if not good:
        raise RuntimeError('All parallel upload streams failed: ' + '; '.join(errors))
    return round(sum(good), 2)


def _ttfb(url: str, px: dict) -> float:
    """Return TTFB in ms (TCP+TLS+first-byte) through proxy. Raises on failure."""
    start = time.perf_counter()
    resp = requests.get(url, proxies=px, stream=True, timeout=15)
    next(resp.iter_content(chunk_size=1), None)
    resp.close()
    return round((time.perf_counter() - start) * 1000, 1)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def test_download(
    proxy_host: str,
    proxy_port: int,
    duration: float = 8.0,
    samples: int = 3,
    warmup: float = 0.0,
    streams: int = 1,
    proxy_user: str | None = None,
    proxy_password: str | None = None,
) -> tuple[float, list[dict]]:
    """
    Test download speed through the proxy against `samples` diverse endpoints.
    Each endpoint is streamed for up to `duration` seconds (after `warmup` drain).
    With streams > 1, multiple concurrent TCP connections are opened per endpoint
    so the VPN tunnel is saturated the same way a download manager would.
    Returns (median_mbps, [{'endpoint', 'mbps', 'error'}, ...]).
    Raises RuntimeError if no endpoint succeeded.
    """
    px = _proxies(proxy_host, proxy_port, proxy_user, proxy_password)
    cap = 150 * 1024 * 1024

    endpoints = DOWNLOAD_ENDPOINTS[:samples]
    results: list[dict] = []
    speeds: list[float] = []

    for label, url_tpl in endpoints:
        try:
            if url_tpl == 'fastcom://':
                url = _resolve_fastcom_url(px)
            elif '{size}' in url_tpl:
                url = url_tpl.format(size=_CF_SIZE)
            else:
                url = url_tpl
            if streams > 1:
                mbps = _parallel_stream_speed(
                    url, px, duration=duration, cap_bytes=cap,
                    streams=streams, warmup=warmup,
                )
            else:
                mbps = _stream_speed(url, px, duration=duration, cap_bytes=cap, warmup=warmup)
            speeds.append(mbps)
            results.append({'endpoint': label, 'mbps': mbps, 'error': None})
            logger.debug('  DL %s ×%d → %.1f Mbps', label, streams, mbps)
        except Exception as exc:
            results.append({'endpoint': label, 'mbps': None, 'error': str(exc)})
            logger.debug('  DL %s → error: %s', label, exc)

    if not speeds:
        raise RuntimeError('All download endpoints failed: ' +
                           '; '.join(r['error'] or '' for r in results))

    return round(median(speeds), 2), results


def test_upload(
    proxy_host: str,
    proxy_port: int,
    duration: float = 8.0,
    streams: int = 1,
    proxy_user: str | None = None,
    proxy_password: str | None = None,
) -> tuple[float, list[dict]]:
    """
    Test upload speed through the proxy (Cloudflare __up endpoint).
    With streams > 1, multiple concurrent POSTs are sent so the VPN tunnel
    is saturated the same way as parallel download streams.
    Returns (mbps, [{'endpoint', 'mbps', 'error'}, ...]).
    Raises RuntimeError if no endpoint succeeded.
    """
    px = _proxies(proxy_host, proxy_port, proxy_user, proxy_password)
    cap = 150 * 1024 * 1024

    results: list[dict] = []
    speeds: list[float] = []

    for label, url in UPLOAD_ENDPOINTS:
        try:
            if streams > 1:
                mbps = _parallel_stream_upload(
                    url, px, duration=duration, cap_bytes=cap, streams=streams,
                )
            else:
                mbps = _stream_upload(url, px, duration=duration, cap_bytes=cap)
            speeds.append(mbps)
            results.append({'endpoint': label, 'mbps': mbps, 'error': None})
            logger.debug('  UL %s ×%d → %.1f Mbps', label, streams, mbps)
        except Exception as exc:
            results.append({'endpoint': label, 'mbps': None, 'error': str(exc)})
            logger.debug('  UL %s → error: %s', label, exc)

    if not speeds:
        raise RuntimeError('Upload failed: ' +
                           '; '.join(r['error'] or '' for r in results))

    return round(median(speeds), 2), results


def test_latency(
    proxy_host: str,
    proxy_port: int,
    samples: int = 3,
    proxy_user: str | None = None,
    proxy_password: str | None = None,
) -> tuple[float, list[dict]]:
    """
    Measure TTFB latency through the proxy against `samples` diverse endpoints.
    Returns (median_ms, [{'endpoint', 'ms', 'error'}, ...]).
    Raises RuntimeError if no endpoint succeeded.
    """
    px = _proxies(proxy_host, proxy_port, proxy_user, proxy_password)
    endpoints = LATENCY_ENDPOINTS[:samples]
    results: list[dict] = []
    values: list[float] = []

    for label, url in endpoints:
        try:
            ms = _ttfb(url, px)
            values.append(ms)
            results.append({'endpoint': label, 'ms': ms, 'error': None})
            logger.debug('  LAT %s → %.0f ms', label, ms)
        except Exception as exc:
            results.append({'endpoint': label, 'ms': None, 'error': str(exc)})
            logger.debug('  LAT %s → error: %s', label, exc)

    if not values:
        raise RuntimeError('All latency endpoints failed')

    return round(median(values), 1), results
