import socket
import struct
import time
import xmlrpc.client
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

from .database import get_db, get_setting, set_setting


SUPPORTED_CLIENT_TYPES = {'qbittorrent', 'rtorrent'}
TRACKER_CHECK_SCOPES = {'enabled', 'all'}
_TRACKER_SKIP_PREFIXES = ('** [', 'dht:', 'pex:', 'lsd:')
_SENSITIVE_QUERY_KEYS = {
    'passkey', 'pass_key', 'authkey', 'auth_key', 'key', 'token', 'apikey',
    'api_key', 'uid', 'pid', 'rsskey',
}


def _strip_sensitive_tracker_path(path: str) -> str:
    parts = [p for p in (path or '').split('/') if p]
    if not parts:
        return '/announce'
    def _token_like(value: str) -> bool:
        if len(value) < 16:
            return False
        allowed = sum(ch.isalnum() or ch in ('-', '_') for ch in value)
        return allowed == len(value)
    kept: list[str] = []
    for part in parts:
        if _token_like(part):
            continue
        kept.append(part)
        low = part.lower()
        if low == 'announce' or low.startswith('announce.'):
            break
    return '/' + '/'.join(kept)


class _TimeoutTransport(xmlrpc.client.Transport):
    def __init__(self, timeout: float):
        super().__init__()
        self.timeout = timeout

    def make_connection(self, host):
        conn = super().make_connection(host)
        conn.timeout = self.timeout
        return conn


class _TimeoutSafeTransport(xmlrpc.client.SafeTransport):
    def __init__(self, timeout: float):
        super().__init__()
        self.timeout = timeout

    def make_connection(self, host):
        conn = super().make_connection(host)
        conn.timeout = self.timeout
        return conn


@dataclass(frozen=True)
class TrackerHit:
    url: str
    torrent_hash: str = ''
    torrent_name: str = ''


def _now_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


def _proxy_dict() -> dict | None:
    import os
    host = get_setting('gluetun_host', '') or os.environ.get('GLUETUN_HOST', 'host.docker.internal')
    port = get_setting('gluetun_proxy_port', '') or os.environ.get('GLUETUN_PROXY_PORT', '8887')
    user = get_setting('proxy_username', '').strip()
    password = get_setting('proxy_password', '')
    creds = ''
    if user:
        from urllib.parse import quote
        creds = quote(user, safe='') + ':' + quote(password, safe='') + '@'
    proxy = f'http://{creds}{host}:{port}'
    return {'http': proxy, 'https': proxy}


def normalize_tracker_url(url: str) -> str:
    raw = (url or '').strip()
    if not raw or raw.lower().startswith(_TRACKER_SKIP_PREFIXES):
        return ''
    parts = urlsplit(raw)
    if parts.scheme.lower() not in ('http', 'https', 'udp'):
        return ''
    scheme = parts.scheme.lower()
    host = (parts.hostname or '').lower()
    if not host or host in ('localhost', '127.0.0.1', '::1'):
        return ''
    netloc = host
    if parts.port:
        netloc += f':{parts.port}'
    path = _strip_sensitive_tracker_path(parts.path or '/announce')
    query = parts.query
    if query:
        kept = [
            (k, v)
            for k, v in parse_qsl(query, keep_blank_values=True)
            if k.lower() not in _SENSITIVE_QUERY_KEYS
        ]
        query = urlencode(sorted(kept))
    return urlunsplit((scheme, netloc, path, query, ''))


def display_tracker_url(url: str) -> str:
    return normalize_tracker_url(url) or ''


def tracker_display_name(host: str) -> str:
    """Build a short human-readable tracker name from its hostname."""
    value = (host or '').strip().lower().rstrip('.')
    if not value:
        return ''
    labels = [label for label in value.split('.') if label]
    if not labels:
        return value
    generic = {'www', 'tracker', 'tracker1', 'tracker2', 'announce', 'bt', 'udp'}
    meaningful = [label for label in labels[:-1] if label not in generic]
    label = meaningful[0] if meaningful else labels[0]
    return label.replace('-', ' ').replace('_', ' ').title()


def tracker_check_scope() -> str:
    scope = (get_setting('tracker_check_scope', 'enabled') or 'enabled').strip().lower()
    return scope if scope in TRACKER_CHECK_SCOPES else 'enabled'


def tracker_parts(url: str) -> dict:
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    port = parts.port or (443 if scheme == 'https' else 80 if scheme == 'http' else 6969)
    return {
        'scheme': scheme,
        'host': (parts.hostname or '').lower(),
        'port': port,
        'path': parts.path or '/announce',
    }


def list_torrent_clients() -> list[dict]:
    with get_db() as db:
        return [dict(r) for r in db.execute(
            'SELECT * FROM torrent_clients ORDER BY enabled DESC, name COLLATE NOCASE'
        ).fetchall()]


def get_torrent_client(client_id: int) -> dict | None:
    with get_db() as db:
        row = db.execute('SELECT * FROM torrent_clients WHERE id=?', (client_id,)).fetchone()
        return dict(row) if row else None


def save_torrent_client(data: dict) -> int:
    client_type = (data.get('client_type') or 'qbittorrent').strip().lower()
    if client_type not in SUPPORTED_CLIENT_TYPES:
        client_type = 'qbittorrent'
    name = (data.get('name') or '').strip() or client_type
    base_url = (data.get('base_url') or '').strip().rstrip('/')
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    container_name = (data.get('container_name') or '').strip()
    enabled = 1 if data.get('enabled') else 0
    include_paused = 1 if data.get('include_paused') else 0
    include_private = 1 if data.get('include_private') else 0
    category_filter = (data.get('category_filter') or '').strip()
    tag_filter = (data.get('tag_filter') or '').strip()
    client_id = int(data.get('id') or 0)
    with get_db() as db:
        if client_id:
            if password:
                db.execute(
                    '''UPDATE torrent_clients
                       SET name=?, client_type=?, base_url=?, username=?, password=?,
                           container_name=?, enabled=?, include_paused=?, include_private=?,
                           category_filter=?, tag_filter=?, updated_at=CURRENT_TIMESTAMP
                       WHERE id=?''',
                    (name, client_type, base_url, username, password, container_name,
                     enabled, include_paused, include_private, category_filter, tag_filter, client_id),
                )
            else:
                db.execute(
                    '''UPDATE torrent_clients
                       SET name=?, client_type=?, base_url=?, username=?,
                           container_name=?, enabled=?, include_paused=?, include_private=?,
                           category_filter=?, tag_filter=?, updated_at=CURRENT_TIMESTAMP
                       WHERE id=?''',
                    (name, client_type, base_url, username, container_name,
                     enabled, include_paused, include_private, category_filter, tag_filter, client_id),
                )
            return client_id
        cur = db.execute(
            '''INSERT INTO torrent_clients
               (name, client_type, base_url, username, password, container_name,
                enabled, include_paused, include_private, category_filter, tag_filter)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (name, client_type, base_url, username, password, container_name,
             enabled, include_paused, include_private, category_filter, tag_filter),
        )
        return int(cur.lastrowid)


def delete_torrent_client(client_id: int) -> bool:
    with get_db() as db:
        cur = db.execute('DELETE FROM torrent_clients WHERE id=?', (client_id,))
        return cur.rowcount > 0


def _qbit_session(client: dict, timeout: float) -> requests.Session:
    sess = requests.Session()
    sess.headers.update({'User-Agent': 'Gluetun-Companion/trackers'})
    base_url = (client.get('base_url') or '').rstrip('/')
    if not base_url:
        raise RuntimeError('qBittorrent URL is empty')
    if client.get('username') or client.get('password'):
        resp = sess.post(
            base_url + '/api/v2/auth/login',
            data={'username': client.get('username', ''), 'password': client.get('password', '')},
            timeout=timeout,
        )
        if resp.status_code >= 400 or 'Fails.' in resp.text:
            raise RuntimeError(f'qBittorrent authentication failed ({resp.status_code}: {resp.text[:120]})')
    return sess


def _qbit_trackers(client: dict, timeout: float = 8.0) -> list[TrackerHit]:
    sess = _qbit_session(client, timeout)
    base_url = client['base_url'].rstrip('/')
    resp = sess.get(base_url + '/api/v2/torrents/info', timeout=timeout)
    if resp.status_code >= 400:
        raise RuntimeError(f'qBittorrent torrents/info failed ({resp.status_code}: {resp.text[:120]})')
    torrents = resp.json() or []
    cat_filter = {v.strip() for v in (client.get('category_filter') or '').split(',') if v.strip()}
    tag_filter = {v.strip() for v in (client.get('tag_filter') or '').split(',') if v.strip()}
    include_paused = bool(client.get('include_paused'))
    include_private = bool(client.get('include_private'))
    hits: list[TrackerHit] = []
    for tor in torrents:
        if not include_paused and str(tor.get('state', '')).lower().startswith('paused'):
            continue
        if not include_private and tor.get('isPrivate'):
            continue
        if cat_filter and str(tor.get('category', '')).strip() not in cat_filter:
            continue
        if tag_filter:
            tags = {v.strip() for v in str(tor.get('tags', '')).split(',') if v.strip()}
            if not tags.intersection(tag_filter):
                continue
        h = tor.get('hash') or ''
        if not h:
            continue
        tr = sess.get(
            base_url + '/api/v2/torrents/trackers',
            params={'hash': h},
            timeout=timeout,
        )
        if tr.status_code >= 400:
            raise RuntimeError(f'qBittorrent trackers failed for {h[:8]} ({tr.status_code}: {tr.text[:120]})')
        for item in tr.json() or []:
            url = normalize_tracker_url(item.get('url', ''))
            if url:
                hits.append(TrackerHit(url=url, torrent_hash=h, torrent_name=tor.get('name', '')))
    return hits


def rtorrent_proxy(client: dict, timeout: float = 8.0) -> 'xmlrpc.client.ServerProxy':
    """Build an XML-RPC proxy for an rTorrent/ruTorrent client config.

    Applies HTTP basic-auth from the stored credentials and defaults the
    path to /RPC2 when the base URL has none.  Shared by tracker discovery
    and port-forward synchronisation.
    """
    url = client['base_url'].rstrip('/')
    parts = urlsplit(url)
    netloc = parts.netloc
    if client.get('username') or client.get('password'):
        from urllib.parse import quote
        netloc = (
            f"{quote(client.get('username', ''), safe='')}:"
            f"{quote(client.get('password', ''), safe='')}@" + parts.netloc
        )
    url = urlunsplit((parts.scheme, netloc, parts.path or '/RPC2', parts.query, parts.fragment))
    transport = _TimeoutSafeTransport(timeout) if url.startswith('https://') else _TimeoutTransport(timeout)
    return xmlrpc.client.ServerProxy(url, allow_none=True, use_builtin_types=True, transport=transport)


def _rtorrent_trackers(client: dict, timeout: float = 8.0) -> list[TrackerHit]:
    proxy = rtorrent_proxy(client, timeout=timeout)
    rows = proxy.d.multicall2('', 'main', 'd.hash=', 'd.name=')
    hits: list[TrackerHit] = []
    for row in rows or []:
        h = row[0] if row else ''
        name = row[1] if len(row) > 1 else ''
        try:
            trackers = proxy.t.multicall(h, '', 't.url=')
        except Exception:
            trackers = []
        for trow in trackers or []:
            raw = trow[0] if isinstance(trow, (list, tuple)) and trow else trow
            url = normalize_tracker_url(str(raw or ''))
            if url:
                hits.append(TrackerHit(url=url, torrent_hash=h, torrent_name=name))
    return hits


def fetch_client_trackers(client: dict) -> list[TrackerHit]:
    if client['client_type'] == 'qbittorrent':
        return _qbit_trackers(client)
    if client['client_type'] == 'rtorrent':
        return _rtorrent_trackers(client)
    raise RuntimeError('Unsupported client type')


def discover_trackers(client_id: int | None = None) -> dict:
    clients = [get_torrent_client(client_id)] if client_id else list_torrent_clients()
    clients = [c for c in clients if c and c.get('enabled')]
    summary = {'clients': 0, 'trackers_found': 0, 'trackers_new': 0, 'errors': []}
    for client in clients:
        summary['clients'] += 1
        try:
            hits = fetch_client_trackers(client)
            stats = persist_tracker_hits(client['id'], hits)
            summary['trackers_found'] += stats['found']
            summary['trackers_new'] += stats['new']
        except Exception as exc:
            summary['errors'].append({'client': client.get('name', '?'), 'error': str(exc)})
    return summary


def persist_tracker_hits(client_id: int, hits: list[TrackerHit]) -> dict:
    seen_urls = set()
    new_count = 0
    with get_db() as db:
        for hit in hits:
            url = normalize_tracker_url(hit.url)
            if not url:
                continue
            parts = tracker_parts(url)
            old = db.execute('SELECT id FROM tracker_urls WHERE url=?', (url,)).fetchone()
            if old:
                tracker_id = old['id']
                db.execute(
                    '''UPDATE tracker_urls
                       SET last_seen_at=CURRENT_TIMESTAMP, scheme=?, host=?, port=?, path=?
                       WHERE id=?''',
                    (parts['scheme'], parts['host'], parts['port'], parts['path'], tracker_id),
                )
            else:
                cur = db.execute(
                    '''INSERT INTO tracker_urls (url, scheme, host, port, path)
                       VALUES (?, ?, ?, ?, ?)''',
                    (url, parts['scheme'], parts['host'], parts['port'], parts['path']),
                )
                tracker_id = int(cur.lastrowid)
                new_count += 1
            seen_urls.add(url)
            db.execute(
                '''INSERT OR REPLACE INTO tracker_sources
                   (client_id, tracker_id, torrent_hash, torrent_name, last_seen_at)
                   VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)''',
                (client_id, tracker_id, hit.torrent_hash, hit.torrent_name),
            )
        db.execute('''
            UPDATE tracker_urls
               SET torrent_count = (
                   SELECT COUNT(DISTINCT torrent_hash)
                   FROM tracker_sources
                   WHERE tracker_sources.tracker_id = tracker_urls.id
               )
        ''')
    return {'found': len(seen_urls), 'new': new_count}


def scrub_tracker_passkeys() -> dict:
    """Merge existing tracker rows whose URL only differs by sensitive query args."""
    merged = 0
    updated = 0
    with get_db() as db:
        rows = db.execute('SELECT * FROM tracker_urls').fetchall()
        for row in rows:
            clean = normalize_tracker_url(row['url'])
            if not clean or clean == row['url']:
                continue
            parts = tracker_parts(clean)
            target = db.execute('SELECT id FROM tracker_urls WHERE url=?', (clean,)).fetchone()
            if target:
                target_id = target['id']
                old_id = row['id']
                db.execute(
                    '''UPDATE OR IGNORE tracker_sources
                       SET tracker_id=?
                       WHERE tracker_id=?''',
                    (target_id, old_id),
                )
                db.execute(
                    '''UPDATE tracker_checks
                       SET tracker_id=?
                       WHERE tracker_id=?''',
                    (target_id, old_id),
                )
                db.execute('DELETE FROM tracker_sources WHERE tracker_id=?', (old_id,))
                db.execute('DELETE FROM tracker_urls WHERE id=?', (old_id,))
                merged += 1
            else:
                db.execute(
                    '''UPDATE tracker_urls
                       SET url=?, scheme=?, host=?, port=?, path=?
                       WHERE id=?''',
                    (clean, parts['scheme'], parts['host'], parts['port'], parts['path'], row['id']),
                )
                updated += 1
        db.execute('''
            UPDATE tracker_urls
               SET torrent_count = (
                   SELECT COUNT(DISTINCT torrent_hash)
                   FROM tracker_sources
                   WHERE tracker_sources.tracker_id = tracker_urls.id
               )
        ''')
    return {'updated': updated, 'merged': merged}


def list_trackers() -> list[dict]:
    scrub_tracker_passkeys()
    with get_db() as db:
        rows = db.execute('''
            SELECT tu.*,
                   COUNT(DISTINCT ts.client_id) AS client_count,
                   GROUP_CONCAT(DISTINCT tc.name) AS client_names
            FROM tracker_urls tu
            LEFT JOIN tracker_sources ts ON ts.tracker_id = tu.id
            LEFT JOIN torrent_clients tc ON tc.id = ts.client_id
            GROUP BY tu.id
            ORDER BY tu.enabled DESC, tu.host COLLATE NOCASE, tu.url COLLATE NOCASE
        ''').fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d['display_url'] = display_tracker_url(d['url'])
            d['display_name'] = tracker_display_name(d['host'])
            attempts = int(d.get('success_count') or 0) + int(d.get('failure_count') or 0)
            d['success_pct'] = round((int(d.get('success_count') or 0) / attempts) * 100, 1) if attempts else None
            out.append(d)
        return out


def tracker_summary() -> dict:
    with get_db() as db:
        row = db.execute('''
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN enabled=1 THEN 1 ELSE 0 END) AS enabled,
                   SUM(CASE WHEN last_status='ok' THEN 1 ELSE 0 END) AS ok,
                   SUM(CASE WHEN last_status NOT IN ('ok', 'unknown') THEN 1 ELSE 0 END) AS failed
            FROM tracker_urls
        ''').fetchone()
        clients = db.execute('SELECT COUNT(*) AS n FROM torrent_clients').fetchone()['n']
        return {
            'total': row['total'] or 0,
            'enabled': row['enabled'] or 0,
            'ok': row['ok'] or 0,
            'failed': row['failed'] or 0,
            'clients': clients or 0,
            'threshold': int(get_setting('tracker_check_threshold_pct', '80') or '80'),
            'scope': tracker_check_scope(),
        }


def tracker_status_for_servers(server_names: list[str] | None = None) -> dict[str, dict]:
    """Return the latest enabled-tracker check aggregate for each server."""
    threshold = int(get_setting('tracker_check_threshold_pct', '80') or '80')
    scope = tracker_check_scope()
    scope_join = '' if scope == 'all' else 'AND tu.enabled = 1'
    with get_db() as db:
        enabled_total = db.execute(
            'SELECT COUNT(*) AS n FROM tracker_urls' + ('' if scope == 'all' else ' WHERE enabled=1')
        ).fetchone()['n'] or 0
        if not enabled_total:
            return {}

        params: list = []
        server_filter = ''
        if server_names:
            names = [str(n) for n in server_names if n]
            if not names:
                return {}
            placeholders = ','.join('?' for _ in names)
            server_filter = f'AND tc.server_name IN ({placeholders})'
            params.extend(names)

        rows = db.execute(f'''
            WITH latest AS (
                SELECT tc.*
                FROM tracker_checks tc
                JOIN tracker_urls tu ON tu.id = tc.tracker_id {scope_join}
                JOIN (
                    SELECT tracker_id, server_name, MAX(checked_at) AS checked_at
                    FROM tracker_checks
                    WHERE server_name != ''
                    GROUP BY tracker_id, server_name
                ) lx
                  ON lx.tracker_id = tc.tracker_id
                 AND lx.server_name = tc.server_name
                 AND lx.checked_at = tc.checked_at
                WHERE tc.server_name != ''
                {server_filter}
            )
            SELECT server_name,
                   COUNT(*) AS tested,
                   SUM(CASE WHEN success=1 THEN 1 ELSE 0 END) AS passed,
                   MAX(checked_at) AS last_checked_at,
                   GROUP_CONCAT(CASE WHEN success=0 THEN status END, ', ') AS failures
            FROM latest
            GROUP BY server_name
        ''', params).fetchall()

    statuses: dict[str, dict] = {}
    for row in rows:
        tested = int(row['tested'] or 0)
        passed = int(row['passed'] or 0)
        pct = round((passed / tested) * 100, 1) if tested else 0.0
        statuses[row['server_name']] = {
            'known': tested > 0,
            'total': enabled_total,
            'tested': tested,
            'passed': passed,
            'failed': max(0, tested - passed),
            'success_pct': pct,
            'threshold': threshold,
            'ok': pct >= threshold if tested else False,
            'last_checked_at': row['last_checked_at'],
            'failures': row['failures'] or '',
        }
    return statuses


def tracker_status_for_server(server_name: str) -> dict:
    return tracker_status_for_servers([server_name]).get(server_name, {
        'known': False,
        'total': 0,
        'tested': 0,
        'passed': 0,
        'failed': 0,
        'success_pct': 0.0,
        'threshold': int(get_setting('tracker_check_threshold_pct', '80') or '80'),
        'ok': False,
        'last_checked_at': None,
        'failures': '',
    })


def tracker_server_is_eligible(server_name: str, allow_unknown: bool = True) -> tuple[bool, dict]:
    status = tracker_status_for_server(server_name)
    if not status.get('known'):
        return allow_unknown, status
    return bool(status.get('ok')), status


def set_tracker_enabled(tracker_id: int, enabled: bool) -> bool:
    with get_db() as db:
        cur = db.execute(
            'UPDATE tracker_urls SET enabled=? WHERE id=?',
            (1 if enabled else 0, tracker_id),
        )
        return cur.rowcount > 0


def set_all_tracker_enabled(enabled: bool) -> int:
    """Enable or disable every discovered tracker URL and return its count."""
    with get_db() as db:
        cur = db.execute('UPDATE tracker_urls SET enabled=?', (1 if enabled else 0,))
        return cur.rowcount


def save_tracker_settings(threshold: int, timeout: int, concurrency: int, scope: str = 'enabled') -> None:
    set_setting('tracker_check_threshold_pct', str(max(1, min(int(threshold), 100))))
    set_setting('tracker_check_timeout_secs', str(max(1, min(int(timeout), 15))))
    set_setting('tracker_check_concurrency', str(max(1, min(int(concurrency), 64))))
    normalized_scope = (scope or 'enabled').strip().lower()
    set_setting('tracker_check_scope', normalized_scope if normalized_scope in TRACKER_CHECK_SCOPES else 'enabled')


def _tcp_probe(host: str, port: int, timeout: float) -> bool:
    with socket.create_connection((host, port), timeout=timeout):
        return True


def _udp_tracker_probe(host: str, port: int, timeout: float) -> tuple[bool, str]:
    addrs = socket.getaddrinfo(host, port, type=socket.SOCK_DGRAM)
    if not addrs:
        return False, 'dns_failed'
    transaction_id = int(time.time() * 1000) & 0xFFFFFFFF
    payload = struct.pack('!QII', 0x41727101980, 0, transaction_id)
    last_error = ''
    for family, socktype, proto, _, sockaddr in addrs[:3]:
        try:
            with socket.socket(family, socktype, proto) as sock:
                sock.settimeout(timeout)
                sock.sendto(payload, sockaddr)
                data, _ = sock.recvfrom(32)
                if len(data) >= 8:
                    action, tid = struct.unpack('!II', data[:8])
                    if action == 0 and tid == transaction_id:
                        return True, 'ok'
                last_error = 'bad_udp_response'
        except Exception as exc:
            last_error = str(exc)
    return False, last_error or 'udp_failed'


def check_tracker(tracker: dict, timeout: float, server_name: str = '') -> dict:
    started = time.monotonic()
    url = tracker['url']
    parts = tracker_parts(url)
    scheme, host, port = parts['scheme'], parts['host'], int(parts['port'])
    result = {
        'tracker_id': tracker['id'],
        'url': url,
        'level_dns': False,
        'level_port': False,
        'level_endpoint': False,
        'success': False,
        'status': 'failed',
        'error': '',
        'elapsed_ms': 0,
    }
    try:
        if scheme in ('http', 'https'):
            proxies = _proxy_dict()
            resp = requests.get(
                url,
                proxies=proxies,
                timeout=timeout,
                headers={'User-Agent': 'Gluetun-Companion/trackers'},
                allow_redirects=False,
            )
            result['level_dns'] = True
            result['level_port'] = True
            # Tracker-specific 4xx responses are good enough: the endpoint is
            # reachable, even if this was not a real announce payload.
            result['level_endpoint'] = resp.status_code < 500
            result['success'] = result['level_endpoint']
            result['status'] = 'ok' if result['success'] else f'http_{resp.status_code}'
        elif scheme == 'udp':
            # UDP cannot be verified through Gluetun's HTTP proxy. This works
            # when Companion itself is in the VPN namespace, otherwise it is
            # marked explicitly so it does not look like a tracker outage.
            socket.getaddrinfo(host, port, type=socket.SOCK_DGRAM)
            result['level_dns'] = True
            ok, msg = _udp_tracker_probe(host, port, timeout)
            result['level_port'] = ok
            result['level_endpoint'] = ok
            result['success'] = ok
            result['status'] = 'ok' if ok else 'udp_failed'
            result['error'] = '' if ok else msg
        else:
            result['status'] = 'unsupported'
            result['error'] = 'unsupported scheme'
    except requests.exceptions.ProxyError as exc:
        result['status'] = 'proxy_failed'
        result['error'] = str(exc)
    except requests.exceptions.ConnectTimeout:
        result['status'] = 'timeout'
        result['error'] = 'connect timeout'
    except requests.exceptions.ReadTimeout:
        result['level_dns'] = True
        result['level_port'] = True
        result['status'] = 'timeout'
        result['error'] = 'read timeout'
    except requests.exceptions.SSLError as exc:
        result['level_dns'] = True
        result['level_port'] = True
        result['status'] = 'tls_failed'
        result['error'] = str(exc)
    except socket.gaierror as exc:
        result['status'] = 'dns_failed'
        result['error'] = str(exc)
    except Exception as exc:
        result['error'] = str(exc)
    result['elapsed_ms'] = _now_ms(started)
    _persist_tracker_check(result, server_name)
    return result


def _persist_tracker_check(result: dict, server_name: str = '') -> None:
    with get_db() as db:
        db.execute(
            '''INSERT INTO tracker_checks
               (tracker_id, server_name, level_dns, level_port, level_endpoint,
                success, status, error_msg, elapsed_ms)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (
                result['tracker_id'], server_name,
                1 if result['level_dns'] else 0,
                1 if result['level_port'] else 0,
                1 if result['level_endpoint'] else 0,
                1 if result['success'] else 0,
                result['status'], result.get('error', '')[:500],
                result['elapsed_ms'],
            ),
        )
        db.execute(
            '''UPDATE tracker_urls
               SET last_checked_at=CURRENT_TIMESTAMP,
                   last_status=?,
                   last_error=?,
                   success_count=success_count+?,
                   failure_count=failure_count+?
               WHERE id=?''',
            (
                result['status'],
                result.get('error', '')[:500],
                1 if result['success'] else 0,
                0 if result['success'] else 1,
                result['tracker_id'],
            ),
        )


def check_enabled_trackers(tracker_ids: list[int] | None = None, server_name: str = '') -> dict:
    scrub_tracker_passkeys()
    timeout = float(get_setting('tracker_check_timeout_secs', '3') or '3')
    concurrency = int(get_setting('tracker_check_concurrency', '12') or '12')
    threshold = int(get_setting('tracker_check_threshold_pct', '80') or '80')
    scope = tracker_check_scope()
    scope_sql = '' if scope == 'all' else 'enabled=1 AND '
    with get_db() as db:
        if tracker_ids:
            placeholders = ','.join('?' for _ in tracker_ids)
            rows = db.execute(
                f'SELECT * FROM tracker_urls WHERE {scope_sql}id IN ({placeholders})',
                tracker_ids,
            ).fetchall()
        else:
            rows = db.execute(
                'SELECT * FROM tracker_urls' + ('' if scope == 'all' else ' WHERE enabled=1')
            ).fetchall()
    trackers = [dict(r) for r in rows]
    results: list[dict] = []
    if trackers:
        with ThreadPoolExecutor(max_workers=max(1, min(concurrency, len(trackers)))) as ex:
            futs = [ex.submit(check_tracker, tr, timeout, server_name) for tr in trackers]
            for fut in as_completed(futs):
                results.append(fut.result())
    ok = sum(1 for r in results if r['success'])
    total = len(results)
    pct = round((ok / total) * 100, 1) if total else 0.0
    return {
        'ok': pct >= threshold if total else False,
        'threshold': threshold,
        'scope': scope,
        'success_pct': pct,
        'passed': ok,
        'failed': total - ok,
        'total': total,
        'results': sorted(results, key=lambda r: r['url']),
    }
