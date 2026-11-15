"""
Real VPN tunnel traffic monitoring.

What is measured
----------------
Companion reads the kernel byte counters of the VPN interface created by the
*production* Gluetun container (``GLUETUN_CONTAINER``): ``tun0`` by default,
``VPN_INTERFACE`` when set, for both WireGuard and OpenVPN.  ``rx`` is the
decrypted traffic received through the tunnel (download) and ``tx`` the
traffic sent through it (upload).  Benchmark sidecars are separate containers
with their own network namespace and are never read.

Every container started with ``network_mode: container:<gluetun>`` or
``network_mode: service:<gluetun>`` shares the same network namespace and
therefore the same VPN interface: its traffic is included exactly once, and
cannot be split per container from these counters.

How it is read
--------------
Gluetun does not publish byte counters and ``GET /containers/{id}/stats`` only
reports the interfaces Docker created (``eth0``), i.e. encrypted traffic plus
LAN traffic of the HTTP proxy and published ports.  The only reliable source
is ``/proc/net/dev`` *inside* Gluetun's network namespace, read with a
short-lived ``docker exec cat`` (no shell, read-only, counters only — never
packet contents).  Through ``docker-socket-proxy`` this requires ``EXEC=1``;
without it the monitor reports an explicit ``unavailable`` state instead of
showing misleading values.

Reliability rules
-----------------
* A tunnel *identity* (container ID + start time + interface + ifindex) is
  stored with each sample.  Any change (server switch, reconnection, Gluetun
  restart, protocol change) means the counters restarted from zero: the new
  counter value is counted, never the difference with the previous tunnel.
* A decrease of the counters with an unchanged identity can only be a counter
  overflow (32- or 64-bit); it is accepted only if the resulting rate is
  plausible, otherwise the sample is treated as a restart.
* The very first sample after activation (or after a voluntary reset) is only
  a baseline: traffic that happened before monitoring is never invented.
* Samples and aggregates are flushed in one SQLite transaction guarded by a
  version number (compare-and-swap).  A second Companion process can never
  count the same bytes twice, and after a Companion restart the delta is
  computed from the last *persisted* counters, so unflushed traffic is
  recovered instead of being lost or duplicated.
* After a collection gap (Companion or Docker temporarily unavailable) the
  volume is spread over the missing period and no instantaneous rate is
  produced, so charts show no artificial peak.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ── Tunables ────────────────────────────────────────────────────────────────
DEFAULT_INTERVAL_SECS = 5
MIN_INTERVAL_SECS = 3
MAX_INTERVAL_SECS = 60
FLUSH_EVERY_SECS = 60
PURGE_EVERY_SECS = 3600
LIVE_BUFFER_SECS = 15 * 60
MINUTE_RETENTION_SECS = 48 * 3600
DEFAULT_HOURLY_RETENTION_DAYS = 90
MIN_HOURLY_RETENTION_DAYS = 31        # the 30-day view needs hourly data
DEFAULT_DAILY_RETENTION_DAYS = 730
# Retry period once Docker refused ``exec`` (socket proxy without EXEC=1).
# Each refused attempt leaves an unstarted exec record in dockerd until the
# Gluetun container stops, so do not retry often.
FORBIDDEN_RETRY_SECS = 3600
ERROR_RETRY_SECS = 30
# Highest believable rate for a single tunnel (≈ 25 Gbit/s).  Anything above
# comes from inconsistent counters, never from real traffic.
MAX_PLAUSIBLE_BYTES_PER_SEC = 3.2e9

COUNTER_32 = 2 ** 32
COUNTER_64 = 2 ** 64

_IFACE_RE = re.compile(r'^[A-Za-z0-9_.-]{1,15}$')
_DEFAULT_IFACES = ('tun0', 'wg0')
_VPN_IFACE_PREFIXES = ('tun', 'wg', 'tap')

SETTING_DEFAULTS: dict[str, str] = {
    'traffic_monitor_enabled': '1',
    'traffic_monitor_interval': str(DEFAULT_INTERVAL_SECS),
    'traffic_hourly_retention_days': str(DEFAULT_HOURLY_RETENTION_DAYS),
    'traffic_daily_retention_days': str(DEFAULT_DAILY_RETENTION_DAYS),
    'traffic_rate_unit': 'mbps',      # mbps | mbytes
    'traffic_volume_unit': 'si',      # si (GB) | iec (GiB)
}

SCHEMA = '''
    CREATE TABLE IF NOT EXISTS vpn_traffic_state (
        id          INTEGER PRIMARY KEY CHECK (id = 1),
        version     INTEGER NOT NULL DEFAULT 0,
        identity    TEXT,
        rx_counter  INTEGER,
        tx_counter  INTEGER,
        sampled_at  REAL,
        updated_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS vpn_traffic_totals (
        id              INTEGER PRIMARY KEY CHECK (id = 1),
        rx_bytes        INTEGER NOT NULL DEFAULT 0,
        tx_bytes        INTEGER NOT NULL DEFAULT 0,
        bench_rx_bytes  INTEGER NOT NULL DEFAULT 0,
        bench_tx_bytes  INTEGER NOT NULL DEFAULT 0,
        since           REAL
    );
    CREATE TABLE IF NOT EXISTS vpn_traffic_minute (
        bucket          INTEGER PRIMARY KEY,
        rx_bytes        INTEGER NOT NULL DEFAULT 0,
        tx_bytes        INTEGER NOT NULL DEFAULT 0,
        bench_rx_bytes  INTEGER NOT NULL DEFAULT 0,
        bench_tx_bytes  INTEGER NOT NULL DEFAULT 0,
        peak_rx_bps     REAL,
        peak_tx_bps     REAL
    );
    CREATE TABLE IF NOT EXISTS vpn_traffic_hour (
        bucket          INTEGER PRIMARY KEY,
        rx_bytes        INTEGER NOT NULL DEFAULT 0,
        tx_bytes        INTEGER NOT NULL DEFAULT 0,
        bench_rx_bytes  INTEGER NOT NULL DEFAULT 0,
        bench_tx_bytes  INTEGER NOT NULL DEFAULT 0,
        peak_rx_bps     REAL,
        peak_tx_bps     REAL
    );
    CREATE TABLE IF NOT EXISTS vpn_traffic_day (
        day             TEXT PRIMARY KEY,
        rx_bytes        INTEGER NOT NULL DEFAULT 0,
        tx_bytes        INTEGER NOT NULL DEFAULT 0,
        bench_rx_bytes  INTEGER NOT NULL DEFAULT 0,
        bench_tx_bytes  INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS vpn_traffic_month (
        month           TEXT PRIMARY KEY,
        rx_bytes        INTEGER NOT NULL DEFAULT 0,
        tx_bytes        INTEGER NOT NULL DEFAULT 0,
        bench_rx_bytes  INTEGER NOT NULL DEFAULT 0,
        bench_tx_bytes  INTEGER NOT NULL DEFAULT 0
    );
    INSERT OR IGNORE INTO vpn_traffic_state (id, version) VALUES (1, 0);
    INSERT OR IGNORE INTO vpn_traffic_totals (id) VALUES (1);
'''


def ensure_schema(db) -> None:
    """Create the traffic tables and default settings (idempotent)."""
    db.executescript(SCHEMA)
    for key, value in SETTING_DEFAULTS.items():
        db.execute(
            'INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)', (key, value)
        )


# ── Pure helpers ────────────────────────────────────────────────────────────

def parse_proc_net_dev(text: str) -> dict[str, tuple[int, int]]:
    """Parse ``/proc/net/dev`` into ``{iface: (rx_bytes, tx_bytes)}``."""
    counters: dict[str, tuple[int, int]] = {}
    for line in (text or '').splitlines():
        if ':' not in line:
            continue
        name, data = line.split(':', 1)
        name = name.strip()
        fields = data.split()
        if not name or len(fields) < 9:
            continue
        try:
            counters[name] = (int(fields[0]), int(fields[8]))
        except ValueError:
            continue
    return counters


def valid_iface(name: str | None) -> bool:
    return bool(name) and bool(_IFACE_RE.match(name))


def pick_vpn_interface(
    counters: dict[str, tuple[int, int]], configured: str | None,
) -> str | None:
    """Return the Gluetun VPN interface present in ``counters``.

    An explicit ``VPN_INTERFACE`` is authoritative: if it is missing the
    tunnel is down, another interface is never substituted.  Without it,
    Gluetun's defaults are tried (``tun0``; ``wg0`` on older releases), then a
    single unambiguous tun/wg/tap interface.
    """
    if configured:
        return configured if configured in counters else None
    for name in _DEFAULT_IFACES:
        if name in counters:
            return name
    candidates = sorted(
        n for n in counters if n.startswith(_VPN_IFACE_PREFIXES)
    )
    return candidates[0] if len(candidates) == 1 else None


@dataclass(frozen=True)
class CounterSample:
    identity: str
    rx: int
    tx: int
    ts: float


@dataclass
class Delta:
    rx: int
    tx: int
    start: float
    end: float
    rx_rate: float | None
    tx_rate: float | None
    event: str     # baseline | ok | gap | reset | wrap | glitch | clock


def _counter_delta(prev: int, cur: int, same: bool) -> tuple[int, str]:
    if not same:
        return cur, 'reset'
    if cur >= prev:
        return cur - prev, 'ok'
    modulus = COUNTER_32 if prev < COUNTER_32 else COUNTER_64
    return cur + modulus - prev, 'wrap'


def compute_delta(
    prev: CounterSample | None,
    cur: CounterSample,
    interval: float,
) -> Delta:
    """Turn two counter samples into transferred bytes and rates.

    Never returns negative values and never counts bytes that belong to a
    previous tunnel instance.
    """
    if prev is None:
        return Delta(0, 0, cur.ts, cur.ts, None, None, 'baseline')
    dt = cur.ts - prev.ts
    if dt <= 0:
        # Clock moved backwards: resynchronise without counting anything.
        return Delta(0, 0, cur.ts, cur.ts, None, None, 'clock')

    same = prev.identity == cur.identity
    rx, rx_event = _counter_delta(prev.rx, cur.rx, same)
    tx, tx_event = _counter_delta(prev.tx, cur.tx, same)
    events = {rx_event, tx_event}
    event = 'reset' if 'reset' in events else ('wrap' if 'wrap' in events else 'ok')

    if event == 'wrap' and max(rx, tx) / dt > MAX_PLAUSIBLE_BYTES_PER_SEC:
        # Not a believable overflow: the kernel counters restarted in place.
        rx = cur.rx if rx_event == 'wrap' else rx
        tx = cur.tx if tx_event == 'wrap' else tx
        event = 'reset'

    if max(rx, tx) / dt > MAX_PLAUSIBLE_BYTES_PER_SEC:
        return Delta(0, 0, cur.ts, cur.ts, None, None, 'glitch')

    max_regular_gap = max(interval * 3, interval + 10)
    if event in ('ok', 'wrap') and dt <= max_regular_gap:
        return Delta(rx, tx, prev.ts, cur.ts, rx / dt, tx / dt, event)
    if event in ('ok', 'wrap'):
        event = 'gap'
    return Delta(rx, tx, prev.ts, cur.ts, None, None, event)


def split_over_minutes(start: float, end: float, total: int) -> list[tuple[int, int]]:
    """Split ``total`` bytes uniformly over [start, end] per UTC minute.

    The parts are integers whose sum is exactly ``total``.
    """
    if total <= 0:
        return []
    if end <= start:
        return [(int(end // 60) * 60, total)]
    span = end - start
    parts: list[tuple[int, int]] = []
    allocated = 0
    bucket = int(start // 60) * 60
    while bucket < end:
        seg_end = min(bucket + 60, end)
        cum = round(total * (seg_end - start) / span)
        share = cum - allocated
        if share:
            parts.append((bucket, share))
            allocated += share
        bucket += 60
    if allocated != total:          # floating point safety net
        last_bucket = int(end // 60) * 60
        parts.append((last_bucket, total - allocated))
    return parts


def local_day(ts: float) -> str:
    return time.strftime('%Y-%m-%d', time.localtime(ts))


def local_month(ts: float) -> str:
    return time.strftime('%Y-%m', time.localtime(ts))


def _int_setting(raw: str | None, default: int, lo: int, hi: int) -> int:
    try:
        value = int(float(raw))
    except (TypeError, ValueError):
        return default
    return max(lo, min(value, hi))


# ── Docker reader ───────────────────────────────────────────────────────────

@dataclass
class Reading:
    state: str                 # ok | tunnel_down | container_down | forbidden | error
    identity: str = ''
    rx: int = 0
    tx: int = 0
    iface: str = ''
    provider: str = ''
    protocol: str = ''
    container_id: str = ''
    detail: str = ''
    health: str = ''           # Docker healthcheck: healthy | unhealthy | starting | '' (none)


class DockerCounterReader:
    """Read the VPN interface counters of the production Gluetun container."""

    def __init__(self, client_factory=None):
        self._client_factory = client_factory
        self._client = None
        self._detected_iface: dict[str, str] = {}

    def _get_client(self):
        if self._client is None:
            if self._client_factory is not None:
                self._client = self._client_factory()
            else:
                import docker
                # TRAFFIC_DOCKER_HOST: optional dedicated socket proxy that only
                # allows inspecting and exec-ing into Gluetun (least privilege).
                dedicated = os.environ.get('TRAFFIC_DOCKER_HOST', '').strip()
                if dedicated:
                    self._client = docker.DockerClient(base_url=dedicated, timeout=15)
                else:
                    self._client = docker.from_env(timeout=15)
        return self._client

    @staticmethod
    def _status_code(exc) -> int | None:
        response = getattr(exc, 'response', None)
        code = getattr(response, 'status_code', None)
        if code is None:
            code = getattr(exc, 'status_code', None)
        return code

    @staticmethod
    def _exec_cat(api, container: str, iface: str) -> str:
        """``cat`` the counters inside Gluetun: no shell, nothing written.

        ``container`` is the container *name*, so a path-filtering proxy can
        restrict exec to Gluetun alone (``/containers/<name>/exec``)."""
        exec_id = api.exec_create(
            container,
            ['cat', '/proc/net/dev', f'/sys/class/net/{iface}/ifindex'],
            stdout=True, stderr=False, tty=False, privileged=False,
        )['Id']
        output = api.exec_start(exec_id, demux=True, tty=False)
        stdout = output[0] if isinstance(output, tuple) else output
        return (stdout or b'').decode('utf-8', errors='replace')

    def read(self, container_name: str) -> Reading:
        try:
            api = self._get_client().api
            info = api.inspect_container(container_name)
        except Exception as exc:
            code = self._status_code(exc)
            if code == 404:
                return Reading('container_down', detail='not_found')
            if code == 403:
                return Reading('forbidden', detail='inspect_forbidden')
            self._client = None
            return Reading('error', detail=type(exc).__name__)

        state = info.get('State') or {}
        container_id = info.get('Id') or ''
        env: dict[str, str] = {}
        for item in (info.get('Config') or {}).get('Env') or []:
            if '=' in item:
                key, value = item.split('=', 1)
                env[key] = value
        provider = (env.get('VPN_SERVICE_PROVIDER') or '').strip()
        protocol = (env.get('VPN_TYPE') or 'openvpn').strip().lower()
        if not state.get('Running') or state.get('Paused') or state.get('Restarting'):
            return Reading(
                'container_down', provider=provider, protocol=protocol,
                container_id=container_id, detail='not_running',
            )

        configured = (env.get('VPN_INTERFACE') or '').strip()
        if configured and not valid_iface(configured):
            return Reading(
                'error', provider=provider, protocol=protocol,
                container_id=container_id, detail='invalid_vpn_interface',
            )
        iface = configured or self._detected_iface.get(container_id) or _DEFAULT_IFACES[0]
        base = {'provider': provider, 'protocol': protocol, 'container_id': container_id}
        # Two attempts at most: the second one only when the interface name
        # had to be discovered (VPN_INTERFACE unset and not tun0).
        for _attempt in range(2):
            try:
                text = self._exec_cat(api, container_name, iface)
            except Exception as exc:
                code = self._status_code(exc)
                if code == 403:
                    return Reading('forbidden', detail='exec_forbidden', **base)
                if code in (404, 409):
                    return Reading('container_down', detail='not_running', **base)
                return Reading('error', detail=type(exc).__name__, **base)
            counters = parse_proc_net_dev(text)
            found = pick_vpn_interface(counters, configured or None)
            if found and found != iface and not configured:
                self._detected_iface[container_id] = found
                iface = found
                continue
            break
        if not found or found != iface:
            return Reading(
                'tunnel_down', iface=configured or iface,
                detail='no_vpn_interface' if counters else 'empty_output', **base,
            )

        # exec targeted the name: make sure it still designates the container
        # inspected above (a recreation in between would mix two tunnels).
        try:
            after = api.inspect_container(container_name)
        except Exception as exc:
            return Reading('error', detail=type(exc).__name__, **base)
        after_state = after.get('State') or {}
        if (after.get('Id') != container_id
                or after_state.get('StartedAt') != state.get('StartedAt')):
            return Reading('error', detail='container_changed', **base)

        last = text.strip().splitlines()[-1].strip() if text.strip() else ''
        ifindex = last if last.isdigit() else '?'
        rx, tx = counters[found]
        identity = '|'.join((
            container_id, str(state.get('StartedAt') or ''), found, ifindex,
        ))
        health = str(((after_state.get('Health') or {}).get('Status')) or '').lower()
        return Reading(
            'ok', identity=identity, rx=rx, tx=tx, iface=found,
            provider=provider, protocol=protocol, container_id=container_id,
            health=health,
        )


# ── Monitor ─────────────────────────────────────────────────────────────────

class _Conflict(Exception):
    """Another writer advanced the persisted counter state."""


# States in which the tunnel interface exists and its counters are sampled.
MEASURING_STATES = ('connected', 'unhealthy', 'unverified')


def health_state(health: str) -> tuple[str, str]:
    """Map Gluetun's Docker health to a tunnel state.

    The interface alone (tun0/wg0) does not prove the VPN works: Gluetun's
    built-in healthcheck dials through the tunnel, so only ``healthy`` is
    reported as connected.  Counters are still recorded in every case."""
    if health == 'healthy':
        return 'connected', ''
    if health == 'unhealthy':
        return 'unhealthy', 'gluetun_unhealthy'
    if health == 'starting':
        return 'unverified', 'health_starting'
    return 'unverified', 'no_healthcheck'


@dataclass
class _Status:
    state: str = 'starting'
    reason: str = ''
    iface: str = ''
    provider: str = ''
    protocol: str = ''
    last_sample_at: float | None = None
    rx_rate: float | None = None
    tx_rate: float | None = None
    last_event: str = ''
    extra: dict = field(default_factory=dict)


# pending[minute_bucket] = [rx, tx, bench_rx, bench_tx, peak_rx, peak_tx]
def _new_slot() -> list:
    return [0, 0, 0, 0, None, None]


def _max(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return max(a, b)


class TrafficMonitor:
    def __init__(
        self,
        container_name: str,
        reader=None,
        clock=time.time,
        settings_getter=None,
    ):
        self.container_name = container_name
        self.reader = reader or DockerCounterReader()
        self.clock = clock
        self._settings_getter = settings_getter
        self._lock = threading.RLock()
        self._prev: CounterSample | None = None
        self._version: int = 0
        self._loaded = False
        self._pending: dict[int, list] = {}
        self._pending_since_flush = False
        self._last_flush = 0.0
        self._last_purge = 0.0
        self._retry_at = 0.0
        self._status = _Status()
        self._buffer: deque = deque()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None

    # ── settings ──
    def _setting(self, key: str) -> str:
        default = SETTING_DEFAULTS.get(key, '')
        if self._settings_getter is not None:
            return self._settings_getter(key, default)
        from .database import get_setting
        return get_setting(key, default)

    def enabled(self) -> bool:
        return self._setting('traffic_monitor_enabled') == '1'

    def interval(self) -> int:
        return _int_setting(
            self._setting('traffic_monitor_interval'),
            DEFAULT_INTERVAL_SECS, MIN_INTERVAL_SECS, MAX_INTERVAL_SECS,
        )

    def _benchmark_active(self) -> bool:
        try:
            return self._setting('benchmark_running') == '1'
        except Exception:
            return False

    # ── persistence ──
    def _load_state(self) -> None:
        from .database import get_db
        with get_db() as db:
            row = db.execute(
                'SELECT version, identity, rx_counter, tx_counter, sampled_at '
                'FROM vpn_traffic_state WHERE id = 1'
            ).fetchone()
        self._version = int(row['version']) if row else 0
        if row and row['identity'] and row['sampled_at'] is not None:
            self._prev = CounterSample(
                row['identity'], int(row['rx_counter'] or 0),
                int(row['tx_counter'] or 0), float(row['sampled_at']),
            )
        else:
            self._prev = None
        self._loaded = True

    def flush(self, now: float | None = None) -> bool:
        """Persist pending aggregates together with the counter state."""
        from .database import get_db
        now = self.clock() if now is None else now
        with self._lock:
            if not self._loaded:
                return True
            pending = self._pending
            prev = self._prev
            version = self._version
            dirty = self._pending_since_flush
            if not dirty and not pending:
                return True
            self._pending = {}
            self._pending_since_flush = False
        try:
            with get_db() as db:
                cur = db.execute(
                    '''UPDATE vpn_traffic_state
                       SET version = version + 1, identity = ?, rx_counter = ?,
                           tx_counter = ?, sampled_at = ?, updated_at = CURRENT_TIMESTAMP
                       WHERE id = 1 AND version = ?''',
                    (
                        prev.identity if prev else None,
                        prev.rx if prev else None,
                        prev.tx if prev else None,
                        prev.ts if prev else None,
                        version,
                    ),
                )
                if cur.rowcount != 1:
                    raise _Conflict()
                self._write_aggregates(db, pending, now, prev)
        except _Conflict:
            logger.warning(
                'VPN traffic: persisted counters changed concurrently — '
                'discarding %d unsaved minute(s) and resynchronising',
                len(pending),
            )
            with self._lock:
                self._pending = {}
                self._load_state()
            return False
        except Exception as exc:
            logger.warning('VPN traffic: flush failed (%s) — will retry', exc)
            with self._lock:
                for bucket, slot in pending.items():
                    self._merge_slot(self._pending, bucket, slot)
                self._pending_since_flush = True
            return False
        with self._lock:
            self._version = version + 1
            self._last_flush = now
        return True

    @staticmethod
    def _merge_slot(target: dict, bucket: int, slot: list) -> None:
        cur = target.setdefault(bucket, _new_slot())
        for i in range(4):
            cur[i] += slot[i]
        cur[4] = _max(cur[4], slot[4])
        cur[5] = _max(cur[5], slot[5])

    @staticmethod
    def aggregate(pending: dict[int, list], now: float, minute_cutoff: float) -> dict:
        minutes: dict[int, list] = {}
        hours: dict[int, list] = {}
        days: dict[str, list] = {}
        months: dict[str, list] = {}
        total = [0, 0, 0, 0]
        for bucket, slot in pending.items():
            if bucket >= minute_cutoff:
                TrafficMonitor._merge_slot(minutes, bucket, slot)
            TrafficMonitor._merge_slot(hours, bucket // 3600 * 3600, slot)
            TrafficMonitor._merge_slot(days, local_day(bucket), slot)
            TrafficMonitor._merge_slot(months, local_month(bucket), slot)
            for i in range(4):
                total[i] += slot[i]
        return {
            'minutes': minutes, 'hours': hours, 'days': days,
            'months': months, 'total': total,
        }

    def _write_aggregates(self, db, pending: dict[int, list], now: float,
                          prev: CounterSample | None) -> None:
        agg = self.aggregate(pending, now, now - MINUTE_RETENTION_SECS)
        with_peaks = '''
            INSERT INTO {t} ({k}, rx_bytes, tx_bytes, bench_rx_bytes, bench_tx_bytes,
                             peak_rx_bps, peak_tx_bps)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT({k}) DO UPDATE SET
                rx_bytes = rx_bytes + excluded.rx_bytes,
                tx_bytes = tx_bytes + excluded.tx_bytes,
                bench_rx_bytes = bench_rx_bytes + excluded.bench_rx_bytes,
                bench_tx_bytes = bench_tx_bytes + excluded.bench_tx_bytes,
                peak_rx_bps = MAX(COALESCE(peak_rx_bps, 0), COALESCE(excluded.peak_rx_bps, 0)),
                peak_tx_bps = MAX(COALESCE(peak_tx_bps, 0), COALESCE(excluded.peak_tx_bps, 0))
        '''
        plain = '''
            INSERT INTO {t} ({k}, rx_bytes, tx_bytes, bench_rx_bytes, bench_tx_bytes)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT({k}) DO UPDATE SET
                rx_bytes = rx_bytes + excluded.rx_bytes,
                tx_bytes = tx_bytes + excluded.tx_bytes,
                bench_rx_bytes = bench_rx_bytes + excluded.bench_rx_bytes,
                bench_tx_bytes = bench_tx_bytes + excluded.bench_tx_bytes
        '''
        for table, rows in (('vpn_traffic_minute', agg['minutes']),
                            ('vpn_traffic_hour', agg['hours'])):
            sql = with_peaks.format(t=table, k='bucket')
            db.executemany(sql, [(b, *s) for b, s in rows.items()])
        db.executemany(plain.format(t='vpn_traffic_day', k='day'),
                       [(d, *s[:4]) for d, s in agg['days'].items()])
        db.executemany(plain.format(t='vpn_traffic_month', k='month'),
                       [(m, *s[:4]) for m, s in agg['months'].items()])
        total = agg['total']
        # ``since`` = first baseline after activation or a voluntary reset.
        db.execute(
            '''UPDATE vpn_traffic_totals
               SET rx_bytes = rx_bytes + ?, tx_bytes = tx_bytes + ?,
                   bench_rx_bytes = bench_rx_bytes + ?, bench_tx_bytes = bench_tx_bytes + ?,
                   since = COALESCE(since, ?)
               WHERE id = 1''',
            (*total, prev.ts if prev else None),
        )

    def purge(self, now: float | None = None) -> None:
        from .database import get_db
        now = self.clock() if now is None else now
        hourly_days = _int_setting(
            self._setting('traffic_hourly_retention_days'),
            DEFAULT_HOURLY_RETENTION_DAYS, MIN_HOURLY_RETENTION_DAYS, 3650,
        )
        daily_days = _int_setting(
            self._setting('traffic_daily_retention_days'),
            DEFAULT_DAILY_RETENTION_DAYS, 0, 36500,
        )
        with get_db() as db:
            db.execute('DELETE FROM vpn_traffic_minute WHERE bucket < ?',
                       (int(now - MINUTE_RETENTION_SECS),))
            db.execute('DELETE FROM vpn_traffic_hour WHERE bucket < ?',
                       (int(now - hourly_days * 86400),))
            if daily_days > 0:
                db.execute('DELETE FROM vpn_traffic_day WHERE day < ?',
                           (local_day(now - daily_days * 86400),))
        self._last_purge = now

    # ── sampling ──
    def _record(self, delta: Delta, bench: bool) -> None:
        if delta.rx or delta.tx:
            rx_parts = dict(split_over_minutes(delta.start, delta.end, delta.rx))
            tx_parts = dict(split_over_minutes(delta.start, delta.end, delta.tx))
            for bucket in set(rx_parts) | set(tx_parts):
                rx = rx_parts.get(bucket, 0)
                tx = tx_parts.get(bucket, 0)
                slot = [rx, tx, rx if bench else 0, tx if bench else 0, None, None]
                self._merge_slot(self._pending, bucket, slot)
        if delta.rx_rate is not None:
            bucket = int(delta.end // 60) * 60
            slot = self._pending.setdefault(bucket, _new_slot())
            slot[4] = _max(slot[4], delta.rx_rate)
            slot[5] = _max(slot[5], delta.tx_rate)

    def _push_live(self, ts: float, rx_rate, tx_rate) -> None:
        self._buffer.append((ts, rx_rate, tx_rate))
        cutoff = ts - LIVE_BUFFER_SECS
        while self._buffer and self._buffer[0][0] < cutoff:
            self._buffer.popleft()

    def process(self, reading: Reading, now: float, interval: float, bench: bool = False) -> Delta | None:
        """Apply one reading.  Returns the computed delta for ``ok`` readings."""
        with self._lock:
            if not self._loaded:
                self._load_state()
            st = self._status
            st.iface = reading.iface or st.iface
            st.provider = reading.provider or st.provider
            st.protocol = reading.protocol or st.protocol
            if reading.state != 'ok':
                state_map = {
                    'tunnel_down': 'tunnel_down',
                    'container_down': 'container_down',
                    'forbidden': 'unavailable',
                    'error': 'unavailable',
                }
                st.state = state_map.get(reading.state, 'unavailable')
                st.reason = reading.detail or reading.state
                st.rx_rate = st.tx_rate = None
                if st.state in ('tunnel_down', 'container_down'):
                    # Keep the chart honest: an explicit hole, not a zero.
                    self._push_live(now, None, None)
                return None

            sample = CounterSample(reading.identity, reading.rx, reading.tx, now)
            delta = compute_delta(self._prev, sample, interval)
            self._record(delta, bench)
            self._prev = sample
            self._pending_since_flush = True
            st.state, st.reason = health_state(reading.health)
            st.last_event = delta.event
            st.last_sample_at = now
            st.rx_rate = delta.rx_rate
            st.tx_rate = delta.tx_rate
            self._push_live(now, delta.rx_rate, delta.tx_rate)
            if delta.event in ('reset', 'wrap', 'gap', 'glitch', 'clock'):
                logger.info(
                    'VPN traffic: %s on %s (rx +%d B, tx +%d B)',
                    delta.event, reading.iface, delta.rx, delta.tx,
                )
            return delta

    def tick(self) -> float:
        """Run one collection step and return the delay before the next one."""
        now = self.clock()
        interval = self.interval()
        if not self.enabled():
            self._on_disabled()
            return max(interval, 10)
        if now < self._retry_at:
            return min(self._retry_at - now, interval * 6)
        reading = self.reader.read(self.container_name)
        delta = self.process(reading, now, interval, bench=self._benchmark_active())
        if reading.state == 'forbidden':
            self._retry_at = now + FORBIDDEN_RETRY_SECS
            logger.warning(
                'VPN traffic: Docker refused to read Gluetun counters (%s). '
                'With docker-socket-proxy, EXEC=1 is required. Retrying in %d min.',
                reading.detail, FORBIDDEN_RETRY_SECS // 60,
            )
        elif reading.state == 'error':
            self._retry_at = now + ERROR_RETRY_SECS
        else:
            self._retry_at = 0.0
        if (delta is not None and delta.event == 'baseline') or \
                now - self._last_flush >= FLUSH_EVERY_SECS:
            self.flush(now)
        if now - self._last_purge >= PURGE_EVERY_SECS:
            try:
                self.purge(now)
            except Exception as exc:
                logger.warning('VPN traffic: purge failed: %s', exc)
        return interval

    def _on_disabled(self) -> None:
        with self._lock:
            if self._status.state == 'disabled':
                return
            if not self._loaded:
                self._load_state()
        self.flush()
        with self._lock:
            # Forget the baseline so that re-enabling never counts the traffic
            # that flowed while monitoring was off.
            self._prev = None
            self._pending_since_flush = True
            self._status = _Status(state='disabled')
            self._buffer.clear()
        self.flush()

    def reset(self) -> None:
        """Erase all traffic statistics (the VPN tunnel is not touched)."""
        from .database import get_db
        with self._lock:
            with get_db() as db:
                for table in ('vpn_traffic_minute', 'vpn_traffic_hour',
                              'vpn_traffic_day', 'vpn_traffic_month'):
                    db.execute(f'DELETE FROM {table}')
                db.execute(
                    'UPDATE vpn_traffic_totals SET rx_bytes = 0, tx_bytes = 0, '
                    'bench_rx_bytes = 0, bench_tx_bytes = 0, since = NULL WHERE id = 1'
                )
                db.execute(
                    'UPDATE vpn_traffic_state SET version = version + 1, identity = NULL, '
                    'rx_counter = NULL, tx_counter = NULL, sampled_at = NULL, '
                    'updated_at = CURRENT_TIMESTAMP WHERE id = 1'
                )
                row = db.execute('SELECT version FROM vpn_traffic_state WHERE id = 1').fetchone()
            self._version = int(row['version'])
            self._prev = None
            self._pending = {}
            self._pending_since_flush = False
            self._buffer.clear()
            self._status.rx_rate = self._status.tx_rate = None
            self._loaded = True
            self._retry_at = 0.0
        logger.info('VPN traffic statistics reset by the user')
        self.wake()

    # ── thread ──
    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name='vpn-traffic')
        self._thread.start()
        logger.info('VPN traffic monitor started (container: %s)', self.container_name)

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def wake(self) -> None:
        """Apply new settings immediately (also retries a refused exec)."""
        self._retry_at = 0.0
        self._wake.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                delay = self.tick()
            except Exception as exc:
                logger.warning('VPN traffic: collection error: %s', exc)
                delay = ERROR_RETRY_SECS
            self._wake.wait(max(1.0, delay))
            self._wake.clear()
        self.flush()

    # ── read side ──
    def _pending_view(self, now: float) -> dict:
        with self._lock:
            pending = {b: list(s) for b, s in self._pending.items()}
        return self.aggregate(pending, now, now - MINUTE_RETENTION_SECS)

    def live(self, since: float | None = None) -> dict:
        from .database import get_db
        now = self.clock()
        interval = self.interval()
        with self._lock:
            st = self._status
            enabled = self.enabled()
            state = 'disabled' if not enabled else st.state
            rx_rate, tx_rate = st.rx_rate, st.tx_rate
            fresh = st.last_sample_at is not None and now - st.last_sample_at <= interval * 3 + 2
            reason = st.reason
            if state in MEASURING_STATES and not fresh:
                state, reason = 'unavailable', 'stale'
            if state not in MEASURING_STATES:
                rx_rate = tx_rate = None
            samples = [
                [round(ts, 3), rx, tx] for ts, rx, tx in self._buffer
                if since is None or ts > since
            ]
            info = {
                'iface': st.iface, 'provider': st.provider, 'protocol': st.protocol,
                'last_event': st.last_event, 'last_sample_at': st.last_sample_at,
            }
        pv = self._pending_view(now)
        today, month = local_day(now), local_month(now)
        with get_db() as db:
            totals = db.execute('SELECT * FROM vpn_traffic_totals WHERE id = 1').fetchone()
            day_row = db.execute('SELECT * FROM vpn_traffic_day WHERE day = ?', (today,)).fetchone()
            month_row = db.execute('SELECT * FROM vpn_traffic_month WHERE month = ?', (month,)).fetchone()
            hour_rows = db.execute(
                'SELECT COALESCE(SUM(rx_bytes),0) AS rx, COALESCE(SUM(tx_bytes),0) AS tx '
                'FROM vpn_traffic_minute WHERE bucket >= ?', (int(now - 3600),)
            ).fetchone()

        def _sum(row, extra, keys=('rx_bytes', 'tx_bytes', 'bench_rx_bytes', 'bench_tx_bytes')):
            base = [int(row[k]) if row and row[k] is not None else 0 for k in keys]
            extra = extra or [0, 0, 0, 0]
            return [base[i] + int(extra[i]) for i in range(4)]

        all_t = _sum(totals, pv['total'])
        day_t = _sum(day_row, pv['days'].get(today))
        month_t = _sum(month_row, pv['months'].get(month))
        last_hour_rx = int(hour_rows['rx']) + sum(
            s[0] for b, s in pv['minutes'].items() if b >= now - 3600)
        last_hour_tx = int(hour_rows['tx']) + sum(
            s[1] for b, s in pv['minutes'].items() if b >= now - 3600)
        since_ts = totals['since'] if totals and totals['since'] is not None else None

        def _block(t):
            return {'rx': t[0], 'tx': t[1], 'total': t[0] + t[1],
                    'bench_rx': t[2], 'bench_tx': t[3]}

        try:
            server = (self._setting('last_observed_active_server') or '').split('=', 1)[-1].strip()
        except Exception:
            server = ''
        return {
            'enabled': enabled,
            'status': state,
            'reason': reason,
            'interval': interval,
            'container': self.container_name,
            'server': server,
            'rx_rate': rx_rate,
            'tx_rate': tx_rate,
            'now': now,
            'since': since_ts,
            'totals': {
                'all': _block(all_t),
                'today': _block(day_t),
                'month': _block(month_t),
                'last_hour': {'rx': last_hour_rx, 'tx': last_hour_tx,
                              'total': last_hour_rx + last_hour_tx},
            },
            'samples': samples,
            **info,
        }

    def history(self, range_key: str) -> dict:
        """Series for the detailed history page."""
        from .database import get_db
        now = self.clock()
        pv = self._pending_view(now)
        with get_db() as db:
            totals = db.execute('SELECT since FROM vpn_traffic_totals WHERE id = 1').fetchone()
        since = totals['since'] if totals else None
        out: dict = {'range': range_key, 'now': now, 'since': since,
                     'rate': None, 'volume': None}

        def minute_rows(start: int) -> dict[int, list]:
            with get_db() as db:
                rows = db.execute(
                    'SELECT * FROM vpn_traffic_minute WHERE bucket >= ? ORDER BY bucket',
                    (start,),
                ).fetchall()
            data = {r['bucket']: [r['rx_bytes'], r['tx_bytes'], r['bench_rx_bytes'],
                                  r['bench_tx_bytes'], r['peak_rx_bps'], r['peak_tx_bps']]
                    for r in rows}
            for b, s in pv['minutes'].items():
                if b >= start:
                    self._merge_slot(data, b, s)
            return data

        def hour_rows(start: int) -> dict[int, list]:
            with get_db() as db:
                rows = db.execute(
                    'SELECT * FROM vpn_traffic_hour WHERE bucket >= ? ORDER BY bucket',
                    (start,),
                ).fetchall()
            data = {r['bucket']: [r['rx_bytes'], r['tx_bytes'], r['bench_rx_bytes'],
                                  r['bench_tx_bytes'], r['peak_rx_bps'], r['peak_tx_bps']]
                    for r in rows}
            for b, s in pv['hours'].items():
                if b >= start:
                    self._merge_slot(data, b, s)
            return data

        def keyed_rows(table: str, key: str, first: str | None) -> dict[str, list]:
            with get_db() as db:
                if first:
                    rows = db.execute(
                        f'SELECT * FROM {table} WHERE {key} >= ? ORDER BY {key}', (first,)
                    ).fetchall()
                else:
                    rows = db.execute(f'SELECT * FROM {table} ORDER BY {key}').fetchall()
            data = {r[key]: [r['rx_bytes'], r['tx_bytes'], r['bench_rx_bytes'],
                             r['bench_tx_bytes'], None, None] for r in rows}
            src = pv['days'] if table == 'vpn_traffic_day' else pv['months']
            for k, s in src.items():
                if first is None or k >= first:
                    self._merge_slot(data, k, s)
            return data

        def monitored(bucket, width: int | None) -> bool:
            """Was monitoring active during this bucket?  Earlier buckets stay
            ``null`` (no invented history) instead of showing zero traffic."""
            if since is None:
                return False
            if isinstance(bucket, str):
                first = local_day(since) if len(bucket) == 10 else local_month(since)
                return bucket >= first
            return bucket + (width or 0) > since

        def series(buckets: list, data: dict, width: int | None, rate: bool) -> list:
            points = []
            for b in buckets:
                slot = data.get(b)
                if slot is None and monitored(b, width):
                    slot = [0, 0, 0, 0, None, None]
                if slot is None:
                    points.append({'t': b, 'rx': None, 'tx': None})
                    continue
                point = {'t': b, 'rx': slot[0], 'tx': slot[1],
                         'bench_rx': slot[2], 'bench_tx': slot[3]}
                if rate and width:
                    point['rx_rate'] = slot[0] / width
                    point['tx_rate'] = slot[1] / width
                    point['peak_rx'] = slot[4]
                    point['peak_tx'] = slot[5]
                points.append(point)
            return points

        def regroup(data: dict, width: int) -> dict:
            grouped: dict[int, list] = {}
            for b, s in data.items():
                self._merge_slot(grouped, b // width * width, s)
            return grouped

        def aligned(start: float, end: float, width: int) -> list[int]:
            first = int(start // width) * width
            return list(range(first, int(end // width) * width + 1, width))

        if range_key == 'live':
            live = self.live()
            out['rate'] = {'width': None, 'points': [
                {'t': ts, 'rx_rate': rx, 'tx_rate': tx} for ts, rx, tx in live['samples']]}
            # Rate samples carry no volume: the summary comes from the minute
            # buckets covering the same window (the chart has no volume panel).
            window_start = int(now - LIVE_BUFFER_SECS) // 60 * 60
            data = minute_rows(window_start)
            out['window'] = {'start': window_start, 'end': now}
            out['summary_points'] = series(aligned(window_start, now, 60), data, 60, False)
        elif range_key == '1h':
            data = minute_rows(int(now - 3600) // 60 * 60)
            out['rate'] = {'width': 60, 'points': series(aligned(now - 3540, now, 60), data, 60, True)}
            out['volume'] = {'width': 300, 'points': series(aligned(now - 3300, now, 300), regroup(data, 300), 300, False)}
        elif range_key == '24h':
            data = minute_rows(int(now - 86400) // 300 * 300)
            out['rate'] = {'width': 300, 'points': series(aligned(now - 86100, now, 300), regroup(data, 300), 300, True)}
            hours = hour_rows(int(now - 86400) // 3600 * 3600)
            out['volume'] = {'width': 3600, 'points': series(aligned(now - 82800, now, 3600), hours, 3600, False)}
        elif range_key in ('7d', '30d'):
            days_n = 7 if range_key == '7d' else 30
            hours = hour_rows(int(now - days_n * 86400) // 3600 * 3600)
            out['rate'] = {'width': 3600, 'points': series(
                aligned(now - days_n * 86400 + 3600, now, 3600), hours, 3600, True)}
            day_keys = [local_day(now - i * 86400) for i in range(days_n - 1, -1, -1)]
            day_keys = sorted(set(day_keys))
            days = keyed_rows('vpn_traffic_day', 'day', day_keys[0])
            out['volume'] = {'width': 86400, 'points': series(day_keys, days, None, False)}
        elif range_key == 'months':
            months = keyed_rows('vpn_traffic_month', 'month', None)
            keys = sorted(months)
            if keys:
                current = local_month(now)
                y, m = map(int, keys[0].split('-'))
                filled = []
                while True:
                    key = f'{y:04d}-{m:02d}'
                    filled.append(key)
                    if key >= current:
                        break
                    m += 1
                    if m > 12:
                        y, m = y + 1, 1
                keys = filled
            out['volume'] = {'width': None, 'points': series(keys, months, None, False)}
        else:
            raise ValueError('unknown range')

        summary = {'rx': 0, 'tx': 0, 'peak_rx': None, 'peak_tx': None,
                   'bench_rx': 0, 'bench_tx': 0}
        src = out.pop('summary_points', None) or (out['volume'] or out['rate'] or {}).get('points')
        if src:
            for p in src:
                summary['rx'] += p.get('rx') or 0
                summary['tx'] += p.get('tx') or 0
                summary['bench_rx'] += p.get('bench_rx') or 0
                summary['bench_tx'] += p.get('bench_tx') or 0
        if out['rate']:
            for p in out['rate']['points']:
                summary['peak_rx'] = _max(summary['peak_rx'], _max(p.get('peak_rx'), p.get('rx_rate')))
                summary['peak_tx'] = _max(summary['peak_tx'], _max(p.get('peak_tx'), p.get('tx_rate')))
        summary['total'] = summary['rx'] + summary['tx']
        out['summary'] = summary
        return out

    def prometheus_snapshot(self) -> dict:
        live = self.live(since=float('inf'))
        return {
            'enabled': live['enabled'],
            'status': live['status'],
            'available': 1 if live['status'] in MEASURING_STATES + ('tunnel_down', 'container_down') else 0,
            # Interface present and sampled (not a proof that the VPN works).
            'tunnel_up': 1 if live['status'] in MEASURING_STATES else 0,
            # Gluetun healthcheck through the tunnel: None when unknown.
            'healthy': {'connected': 1, 'unhealthy': 0}.get(live['status']),
            'rx_total': live['totals']['all']['rx'],
            'tx_total': live['totals']['all']['tx'],
            'rx_rate': live['rx_rate'],
            'tx_rate': live['tx_rate'],
            'iface': live['iface'],
            'provider': live['provider'],
            'protocol': live['protocol'],
            'last_sample_at': live['last_sample_at'],
            'since': live['since'],
        }


# ── Process-wide singleton ──────────────────────────────────────────────────
_monitor: TrafficMonitor | None = None
_monitor_lock = threading.Lock()


def get_monitor(container_name: str | None = None) -> TrafficMonitor:
    global _monitor
    with _monitor_lock:
        if _monitor is None:
            if container_name is None:
                try:
                    from flask import current_app
                    container_name = current_app.config['GLUETUN_CONTAINER']
                except Exception:
                    container_name = 'gluetun'
            _monitor = TrafficMonitor(container_name)
        return _monitor


def start_monitor(container_name: str) -> TrafficMonitor:
    monitor = get_monitor(container_name)
    monitor.start()
    return monitor
