"""
Gluetun server catalogue — reads provider JSON files from the mounted Gluetun volume.

The Gluetun container exports per-provider JSON files to a volume:
  volumes:
    - ./gluetun:/gluetun
  environment:
    UPDATER_PERIOD: 24h                    # enable periodic updates
    UPDATER_PREFER_DIRECT_DOWNLOAD: "yes"  # write one JSON per provider to /gluetun/servers/
    # UPDATER_VPN_SERVICE_PROVIDERS: airvpn,mullvad  # optional: add extra providers

The Sidecar mounts the same volume read-only and reads
/gluetun/servers/<provider>.json to build the catalogue.

⚠️  ProtonVPN is excluded: generating its JSON requires Proton credentials
    (paid account for premium servers) and cannot be automated transparently.
    See https://github.com/qdm12/gluetun-wiki/blob/main/setup/servers.md#list-of-vpn-servers
"""

import glob as glob_mod
import json
import logging
import os
import secrets
import time
from datetime import datetime

import requests as _requests

from .database import get_db, get_setting, set_setting

logger = logging.getLogger(__name__)

# Providers excluded from catalogue auto-import (empty = all allowed)
_EXCLUDED_PROVIDERS: set[str] = set()

# Gluetun VPN_SERVICE_PROVIDER value → JSON filename mapping
# (most match directly, a few differ)
_PROVIDER_ALIASES: dict[str, str] = {
    'private internet access': 'private internet access',
    'vpn unlimited':           'vpn unlimited',
    'perfect privacy':         'perfect privacy',
}


def _normalize_provider(name: str) -> str:
    """Lowercase + strip the provider name."""
    return name.lower().strip()


def read_catalogue_dir(servers_dir: str) -> dict[str, list[dict]]:
    """
    Read all provider JSON files from the Gluetun servers directory.
    Returns {provider: [normalized_server_dict, ...]}

    Each server dict has keys: name, country, country_code, region, city, hostname.
    """
    result: dict[str, list[dict]] = {}

    if not os.path.isdir(servers_dir):
        logger.warning('catalogue: servers dir not found: %s', servers_dir)
        return result

    pattern = os.path.join(servers_dir, '*.json')
    for filepath in sorted(glob_mod.glob(pattern)):
        filename = os.path.basename(filepath)
        if filename == 'manifest.json':
            continue

        provider = filename[:-5].lower()  # strip .json → provider name

        if provider in _EXCLUDED_PROVIDERS:
            logger.info('catalogue: skipping %s (requires Proton credentials)', provider)
            continue

        try:
            with open(filepath, 'r', encoding='utf-8') as fh:
                data = json.load(fh)
        except Exception as exc:
            logger.warning('catalogue: failed to read %s: %s', filepath, exc)
            continue

        raw_servers = data.get('servers', [])
        if not raw_servers:
            logger.debug('catalogue: %s has no servers', filename)
            continue

        normalized: list[dict] = []
        for s in raw_servers:
            # hostname: some providers use 'hostname', others 'hostnames' (list)
            hostnames = s.get('hostnames') or []
            hostname = s.get('hostname') or (hostnames[0] if hostnames else '')

            entry = {
                'name':         s.get('name') or s.get('server_name') or '',
                'country':      s.get('country') or '',
                'country_code': (s.get('country_code') or s.get('countryCode') or '').lower(),
                'region':       s.get('region') or '',
                'city':         s.get('city') or '',
                'hostname':     hostname or '',
            }
            # Skip fully empty entries
            if any(entry.values()):
                normalized.append(entry)

        if normalized:
            result[provider] = normalized
            logger.info('catalogue: read %d servers from %s', len(normalized), filename)

    return result


def refresh_catalogue(servers_dir: str | None = None) -> dict:
    """
    Read Gluetun provider JSON files and update the gluetun_catalogue table.
    Returns summary: {ok, total, providers} or {ok: False, error}.
    """
    if servers_dir is None:
        servers_dir = get_setting('catalogue_servers_dir', '/gluetun/servers')

    providers_data = read_catalogue_dir(servers_dir)

    if not providers_data:
        msg = f'No provider JSON files found in {servers_dir}'
        logger.warning('catalogue: %s', msg)
        return {'ok': False, 'error': msg}

    total = 0
    provider_counts: dict[str, int] = {}

    with get_db() as db:
        for provider, servers in providers_data.items():
            # Delete-then-insert: simpler than upsert for variable fields
            db.execute('DELETE FROM gluetun_catalogue WHERE provider=?', (provider,))
            for s in servers:
                db.execute(
                    '''INSERT INTO gluetun_catalogue
                        (provider, name, country, country_code, region, city, hostname, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                    (
                        provider,
                        s['name'],
                        s['country'],
                        s['country_code'],
                        s['region'],
                        s['city'],
                        s['hostname'],
                        datetime.utcnow().isoformat(),
                    ),
                )
                total += 1
            provider_counts[provider] = len(servers)

    set_setting('catalogue_last_refresh', datetime.utcnow().isoformat())
    logger.info(
        'catalogue refresh done: %d servers (%s)',
        total,
        ', '.join(f'{p}:{n}' for p, n in provider_counts.items()),
    )
    return {'ok': True, 'total': total, 'providers': provider_counts}


def detect_active_provider(container_name: str) -> str:
    """
    Read the VPN_SERVICE_PROVIDER env var from the running Gluetun container.
    Returns the lowercase provider name (matches the JSON filename without .json).
    Returns '' on failure.
    """
    try:
        from .gluetun import _container_env  # type: ignore[attr-defined]
        env = _container_env(container_name)
        return env.get('VPN_SERVICE_PROVIDER', '').lower().strip()
    except Exception as exc:
        logger.warning('detect_active_provider: %s', exc)
        return ''


def get_providers() -> list[str]:
    """Return sorted list of providers currently in the catalogue."""
    with get_db() as db:
        rows = db.execute(
            'SELECT DISTINCT provider FROM gluetun_catalogue ORDER BY provider'
        ).fetchall()
    return [r[0] for r in rows]


def get_catalogue_entries(
    provider: str | None = None,
    filter_type: str = 'name',
) -> list[dict]:
    """
    Return unique filter values from the catalogue for the given filter type.

    filter_type: 'name' | 'country' | 'city' | 'region' | 'hostname'
    Returns list of {value, country, country_code, provider} dicts, sorted.
    """
    col_map = {
        'name':     'name',
        'country':  'country',
        'city':     'city',
        'region':   'region',
        'hostname': 'hostname',
    }
    col = col_map.get(filter_type, 'name')

    with get_db() as db:
        if provider:
            rows = db.execute(
                f'''SELECT DISTINCT {col} AS value, country, country_code, provider
                    FROM gluetun_catalogue
                    WHERE provider=? AND {col} != ''
                    ORDER BY {col}''',
                (provider,),
            ).fetchall()
        else:
            rows = db.execute(
                f'''SELECT DISTINCT {col} AS value, country, country_code, provider
                    FROM gluetun_catalogue
                    WHERE {col} != ''
                    ORDER BY {col}''',
            ).fetchall()

    return [dict(r) for r in rows]


_ALL_FILTER_TYPES = ['name', 'country', 'city', 'region', 'hostname']


def _import_one_filter_type(
    mode: str,
    provider: str,
    filter_type: str,
    container_name: str,
) -> dict:
    """
    Core import logic for a single filter type.
    Returns {ok, added, skipped, error?}
    """
    col_map = {
        'name':     'name',
        'country':  'country',
        'city':     'city',
        'region':   'region',
        'hostname': 'hostname',
    }
    col = col_map.get(filter_type, 'name')

    with get_db() as db:
        if mode == 'active':
            active = detect_active_provider(container_name)
            if not active:
                return {
                    'ok': False,
                    'error': 'Could not detect active VPN provider from Gluetun container',
                }
            rows = db.execute(
                f'SELECT DISTINCT {col} FROM gluetun_catalogue WHERE provider=? AND {col} != ""',
                (active,),
            ).fetchall()

        elif mode == 'provider' and provider:
            rows = db.execute(
                f'SELECT DISTINCT {col} FROM gluetun_catalogue WHERE provider=? AND {col} != ""',
                (provider,),
            ).fetchall()

        else:  # all providers
            rows = db.execute(
                f'SELECT DISTINCT {col} FROM gluetun_catalogue WHERE {col} != ""'
            ).fetchall()

        added = skipped = 0
        for (value,) in rows:
            if not value:
                skipped += 1
                continue
            try:
                cur = db.execute(
                    'INSERT OR IGNORE INTO servers (name, filter_type) VALUES (?, ?)',
                    (value, filter_type),
                )
                if cur.rowcount > 0:
                    added += 1
                else:
                    skipped += 1
            except Exception as exc:
                logger.warning('_import_one_filter_type %s: %s', filter_type, exc)
                skipped += 1

    return {'ok': True, 'added': added, 'skipped': skipped}


def import_to_servers(
    mode: str,
    provider: str = '',
    filter_type: str = 'name',
    container_name: str = '',
) -> dict:
    """
    Import servers from gluetun_catalogue into the servers table.

    mode:        'all' | 'provider' | 'active'
    filter_type: 'name' | 'country' | 'city' | 'region' | 'hostname' | 'all'
                 'all' imports every attribute for every matching server.
    Returns {ok, added, skipped, error?}
    """
    types_to_import = (
        _ALL_FILTER_TYPES if filter_type == 'all'
        else [filter_type if filter_type in _ALL_FILTER_TYPES else 'name']
    )

    total_added = total_skipped = 0
    for ft in types_to_import:
        result = _import_one_filter_type(mode, provider, ft, container_name)
        if not result.get('ok'):
            return result   # propagate first error (e.g. active provider not detected)
        total_added   += result['added']
        total_skipped += result['skipped']

    logger.info(
        'catalogue import: added=%d skipped=%d (mode=%s filter=%s)',
        total_added, total_skipped, mode, filter_type,
    )
    return {'ok': True, 'added': total_added, 'skipped': total_skipped}


def _snapshot_catalogue_names(db) -> dict[str, set[str]]:
    """Return {provider: {server_name, ...}} snapshot of the current catalogue."""
    rows = db.execute('SELECT provider, name FROM gluetun_catalogue').fetchall()
    snap: dict[str, set[str]] = {}
    for r in rows:
        snap.setdefault(r['provider'], set()).add(r['name'])
    return snap


def _compute_catalogue_diff(
    before: dict[str, set[str]],
    after: dict[str, set[str]],
) -> dict[str, dict[str, list[str]]]:
    """
    Compare two {provider: set_of_names} snapshots.
    Returns {provider: {added: [...], removed: [...]}} — only providers with changes.
    """
    diff: dict[str, dict[str, list[str]]] = {}
    for p in set(before) | set(after):
        b = before.get(p, set())
        a = after.get(p, set())
        added   = sorted(a - b)
        removed = sorted(b - a)
        if added or removed:
            diff[p] = {'added': added, 'removed': removed}
    return diff


def _auto_add_matched_servers(
    new_entries: list[dict],
    db,
) -> list[str]:
    """
    For each newly appeared catalogue entry, check whether the user has already
    configured a country / region / city server whose value matches.  If so,
    add the new server as a ``filter_type='name'`` entry (individual benchmark).

    Returns the list of server names that were inserted.

    Matching rules
    ──────────────
    User server  (name="France",  filter_type="country") →
        matches any catalogue entry where  country == "France"  (case-insensitive)

    User server  (name="Île-de-France", filter_type="region") →
        matches any catalogue entry where  region == "Île-de-France"

    User server  (name="Paris", filter_type="city") →
        matches any catalogue entry where  city == "Paris"

    ``filter_type='name'`` and ``filter_type='hostname'`` user entries are not
    used for matching (they are already pointing at specific servers).
    """
    # Build {filter_type: set_of_lowercase_values} from user's servers table
    user_rows = db.execute(
        "SELECT name, filter_type FROM servers WHERE filter_type IN ('country', 'region', 'city')"
    ).fetchall()
    if not user_rows:
        return []

    matchers: dict[str, set[str]] = {}
    for row in user_rows:
        matchers.setdefault(row['filter_type'], set()).add(row['name'].strip().lower())

    # Existing server names (to avoid duplicates)
    existing: set[str] = {
        r['name'].strip().lower()
        for r in db.execute('SELECT name FROM servers').fetchall()
    }

    inserted: list[str] = []
    for entry in new_entries:
        srv_name = (entry.get('name') or '').strip()
        if not srv_name or srv_name.lower() in existing:
            continue

        matched = any(
            (entry.get(ft) or '').strip().lower() in vals
            for ft, vals in matchers.items()
        )
        if matched:
            try:
                db.execute(
                    'INSERT OR IGNORE INTO servers (name, filter_type, enabled) VALUES (?, ?, 1)',
                    (srv_name, 'name'),
                )
                existing.add(srv_name.lower())
                inserted.append(srv_name)
            except Exception as exc:
                logger.warning('auto-add catalogue server %s: %s', srv_name, exc)

    return inserted


def _wait_for_catalogue_sidecar(host: str, port: int, timeout: int = 60, token: str = '') -> bool:
    """
    Poll the sidecar /ready endpoint until it responds 200 or timeout expires.
    Uses /ready (not /ping) to avoid routing to the ICMP-ping endpoint.
    Passes X-Sidecar-Token header when token is set.
    """
    url      = f'http://{host}:{port}/ready'
    headers  = {'X-Sidecar-Token': token} if token else {}
    deadline = time.time() + timeout
    time.sleep(3)   # give Flask a moment to boot
    while time.time() < deadline:
        try:
            r = _requests.get(url, headers=headers, timeout=5)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(2)
    return False


def refresh_catalogue_from_sidecar(
    sidecar_image: str,
    sidecar_host: str,
    catalogue_port: int = 8767,
    auto_add: bool = False,
) -> dict:
    """
    Spin up a catalogue-only sidecar container, call its /catalogue endpoint,
    save the results to gluetun_catalogue, then destroy the container.

    The sidecar fetches server lists from the public Gluetun GitHub repository:
      https://github.com/qdm12/gluetun-servers/tree/main/pkg/servers
    No volume mounting or Gluetun API required — pure HTTPS download.

    Returns {ok, total, providers, diff, auto_added} or {ok: False, error}.

    diff       — {provider: {added: [...], removed: [...]}} (empty dict when no change)
    auto_added — list of server names inserted into the servers table (only when
                 auto_add=True and the server matches a user-configured country /
                 region / city filter).
    """
    from .gluetun import create_catalogue_sidecar, cleanup_catalogue_sidecar, _CATALOGUE_SIDECAR_PORT

    if catalogue_port == _CATALOGUE_SIDECAR_PORT:
        catalogue_port = int(get_setting('catalogue_sidecar_port', str(_CATALOGUE_SIDECAR_PORT)))

    # ── Generate one-time shared secret for this sidecar instance ───────────
    token = secrets.token_hex(32)

    # ── 1. Create sidecar ────────────────────────────────────────────────────
    ok, err = create_catalogue_sidecar(sidecar_image, catalogue_port, token=token)
    if not ok:
        logger.error('refresh_catalogue_from_sidecar: sidecar creation failed: %s', err)
        return {'ok': False, 'error': f'Sidecar creation failed: {err}'}

    try:
        # ── 2. Wait for sidecar Flask to start ───────────────────────────────
        ready = _wait_for_catalogue_sidecar(sidecar_host, catalogue_port, timeout=60, token=token)
        if not ready:
            return {'ok': False, 'error': 'Catalogue sidecar did not start in time'}

        # ── 3. Call /catalogue ───────────────────────────────────────────────
        url     = f'http://{sidecar_host}:{catalogue_port}/catalogue'
        headers = {'X-Sidecar-Token': token}
        resp    = _requests.get(url, headers=headers, timeout=60)
        resp.raise_for_status()
        data = resp.json()

        if not data.get('ok'):
            return {'ok': False, 'error': data.get('error', 'Catalogue endpoint returned ok=false')}

        providers_data: dict[str, list[dict]] = data.get('providers', {})
        if not providers_data:
            return {'ok': False, 'error': 'No providers returned by sidecar (check volume mount)'}

        # ── 4. Save to DB ────────────────────────────────────────────────────
        total = 0
        provider_counts: dict[str, int] = {}
        diff: dict[str, dict[str, list[str]]] = {}
        auto_added_names: list[str] = []

        with get_db() as db:
            # Snapshot before overwrite so we can compute the diff
            before_snap = _snapshot_catalogue_names(db)

            now_iso = datetime.utcnow().isoformat()
            for provider, servers in providers_data.items():
                db.execute('DELETE FROM gluetun_catalogue WHERE provider=?', (provider,))
                for s in servers:
                    db.execute(
                        '''INSERT INTO gluetun_catalogue
                            (provider, name, country, country_code, region, city, hostname, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                        (
                            provider,
                            s.get('name', ''),
                            s.get('country', ''),
                            s.get('country_code', ''),
                            s.get('region', ''),
                            s.get('city', ''),
                            s.get('hostname', ''),
                            now_iso,
                        ),
                    )
                    total += 1
                provider_counts[provider] = len(servers)

            # Compute diff (after snapshot → what changed)
            after_snap: dict[str, set[str]] = {
                p: {s['name'] for s in srvs}
                for p, srvs in providers_data.items()
            }
            diff = _compute_catalogue_diff(before_snap, after_snap)

            # Auto-add new servers that match user's country/region/city filters
            if auto_add and diff:
                new_entries: list[dict] = []
                for p, changes in diff.items():
                    added_names = set(changes.get('added', []))
                    for s in providers_data.get(p, []):
                        if s.get('name') in added_names:
                            new_entries.append(s)
                if new_entries:
                    auto_added_names = _auto_add_matched_servers(new_entries, db)

        set_setting('catalogue_last_refresh', datetime.utcnow().isoformat())

        if diff:
            change_summary = ', '.join(
                f'{p}: +{len(v["added"])}/-{len(v["removed"])}'
                for p, v in diff.items()
            )
            logger.info('catalogue diff: %s', change_summary)
        if auto_added_names:
            logger.info('catalogue auto-add: %d server(s): %s',
                        len(auto_added_names), ', '.join(auto_added_names))
        logger.info(
            'catalogue refresh via sidecar: %d servers (%s)',
            total,
            ', '.join(f'{p}:{n}' for p, n in provider_counts.items()),
        )
        return {
            'ok':         True,
            'total':      total,
            'providers':  provider_counts,
            'diff':       diff,
            'auto_added': auto_added_names,
        }

    except Exception as exc:
        logger.error('refresh_catalogue_from_sidecar: %s', exc)
        return {'ok': False, 'error': str(exc)}

    finally:
        # ── 5. Always clean up the sidecar ───────────────────────────────────
        cleanup_catalogue_sidecar()


def catalogue_stats() -> dict:
    """Return summary stats for the catalogue (for display in UI).

    Counts are distinct server names — not raw row counts — so the number
    shown in the provider dropdown matches what the user can actually import.
    """
    with get_db() as db:
        total = db.execute(
            "SELECT COUNT(DISTINCT name) FROM gluetun_catalogue WHERE name != ''"
        ).fetchone()[0]
        providers = db.execute(
            "SELECT provider, COUNT(DISTINCT name) as n "
            "FROM gluetun_catalogue WHERE name != '' "
            "GROUP BY provider ORDER BY provider"
        ).fetchall()
    last_refresh = get_setting('catalogue_last_refresh', '')
    return {
        'total':        total,
        'providers':    [{'name': r[0], 'count': r[1]} for r in providers],
        'last_refresh': last_refresh,
    }
