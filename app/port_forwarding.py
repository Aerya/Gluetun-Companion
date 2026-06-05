import json
import logging
import re
import subprocess
import time

import docker
import requests

from .database import get_db, get_setting, set_setting
from .gluetun import _container_env
from .torrent_trackers import get_torrent_client, _qbit_session

logger = logging.getLogger(__name__)


SUPPORTED_MODES = {'manual', 'native'}
SUPPORTED_PROTOCOLS = {'tcp', 'udp'}


def _clean_protocols(value: str | list[str] | tuple[str, ...] | None) -> str:
    if isinstance(value, (list, tuple)):
        raw = value
    else:
        raw = str(value or 'tcp,udp').replace(';', ',').split(',')
    protos = []
    for item in raw:
        proto = str(item or '').strip().lower()
        if proto in SUPPORTED_PROTOCOLS and proto not in protos:
            protos.append(proto)
    return ','.join(protos or ['tcp', 'udp'])


def _parse_port_list(value: str) -> set[int]:
    ports: set[int] = set()
    for part in str(value or '').replace(';', ',').split(','):
        part = part.strip()
        if not part:
            continue
        if '-' in part:
            start, end = part.split('-', 1)
            try:
                a, b = int(start), int(end)
            except ValueError:
                continue
            for port in range(max(1, a), min(65535, b) + 1):
                ports.add(port)
            continue
        try:
            port = int(part)
        except ValueError:
            continue
        if 1 <= port <= 65535:
            ports.add(port)
    return ports


def _status(ok: bool | None, label_ok='OK', label_bad='manquant') -> dict:
    if ok is True:
        return {'state': 'ok', 'label': label_ok}
    if ok is False:
        return {'state': 'bad', 'label': label_bad}
    return {'state': 'unknown', 'label': 'inconnu'}


def list_port_forwards() -> list[dict]:
    with get_db() as db:
        rows = db.execute(
            '''SELECT pf.*, tc.name AS client_name, tc.client_type, tc.base_url AS client_url
               FROM port_forwards pf
               LEFT JOIN torrent_clients tc ON tc.id = pf.torrent_client_id
               ORDER BY pf.enabled DESC, pf.provider COLLATE NOCASE, pf.name COLLATE NOCASE, pf.port'''
        ).fetchall()
    return [dict(r) for r in rows]


def get_port_forward(port_forward_id: int) -> dict | None:
    with get_db() as db:
        row = db.execute('SELECT * FROM port_forwards WHERE id=?', (port_forward_id,)).fetchone()
    return dict(row) if row else None


def save_port_forward(data: dict) -> int:
    provider = (data.get('provider') or 'airvpn').strip().lower()
    if not provider:
        provider = 'manual'
    mode = (data.get('mode') or 'manual').strip().lower()
    if mode not in SUPPORTED_MODES:
        mode = 'manual'
    port = int(data.get('port') or 0)
    if mode == 'manual' and not (1 <= port <= 65535):
        raise ValueError('Port invalide.')
    if mode == 'native':
        port = port if 1 <= port <= 65535 else 0
    protocols = _clean_protocols(data.get('protocols'))
    name = (data.get('name') or '').strip() or f'{provider}:{port}'
    notes = (data.get('notes') or '').strip()
    hook_cmd = (data.get('on_port_change_cmd') or '').strip()
    torrent_client_id = int(data.get('torrent_client_id') or 0) or None
    enabled = 1 if data.get('enabled') else 0
    port_forward_id = int(data.get('id') or 0)

    with get_db() as db:
        if port_forward_id:
            db.execute(
                '''UPDATE port_forwards
                   SET name=?, provider=?, mode=?, port=?, protocols=?,
                       torrent_client_id=?, on_port_change_cmd=?, enabled=?,
                       notes=?, updated_at=CURRENT_TIMESTAMP
                   WHERE id=?''',
                (name, provider, mode, port, protocols, torrent_client_id, hook_cmd, enabled, notes, port_forward_id),
            )
            return port_forward_id
        cur = db.execute(
            '''INSERT INTO port_forwards
               (name, provider, mode, port, protocols, torrent_client_id, on_port_change_cmd, enabled, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (name, provider, mode, port, protocols, torrent_client_id, hook_cmd, enabled, notes),
        )
        return int(cur.lastrowid)


def delete_port_forward(port_forward_id: int) -> bool:
    with get_db() as db:
        cur = db.execute('DELETE FROM port_forwards WHERE id=?', (port_forward_id,))
        return cur.rowcount > 0


def list_active_provider_forwards(provider: str) -> list[dict]:
    provider = (provider or '').strip().lower()
    if not provider:
        return []
    with get_db() as db:
        rows = db.execute(
            '''SELECT pf.*, tc.name AS client_name, tc.client_type, tc.base_url AS client_url
               FROM port_forwards pf
               LEFT JOIN torrent_clients tc ON tc.id = pf.torrent_client_id
               WHERE pf.enabled = 1
                 AND pf.provider = ?
               ORDER BY pf.name COLLATE NOCASE, pf.port''',
            (provider,),
        ).fetchall()
    return [dict(r) for r in rows]


def _docker_published_ports(container_name: str, port: int, protocols: list[str]) -> dict[str, bool | None]:
    result = {proto: None for proto in protocols}
    if not container_name:
        return result
    try:
        container = docker.from_env().containers.get(container_name)
        ports = container.attrs.get('NetworkSettings', {}).get('Ports') or {}
        for proto in protocols:
            bindings = ports.get(f'{port}/{proto}')
            result[proto] = bool(bindings)
    except Exception as exc:
        logger.warning('port forwarding docker inspect failed: %s', exc)
    return result


def _qbit_listen_port(client: dict, timeout: float = 6.0) -> tuple[int | None, str]:
    try:
        sess = _qbit_session(client, timeout=timeout)
        base_url = (client.get('base_url') or '').rstrip('/')
        resp = sess.get(base_url + '/api/v2/app/preferences', timeout=timeout)
        if resp.status_code >= 400:
            return None, f'qBittorrent preferences failed ({resp.status_code})'
        value = resp.json().get('listen_port')
        return int(value), ''
    except Exception as exc:
        return None, str(exc)


def _extract_ports(payload) -> list[int]:
    values = []
    if isinstance(payload, dict):
        for key in ('ports', 'port', 'forwarded_port', 'forwarded_ports'):
            if key in payload:
                values = payload[key]
                break
    else:
        values = payload
    if isinstance(values, int):
        values = [values]
    if isinstance(values, str):
        values = re.findall(r'\d+', values)
    ports = []
    for value in values or []:
        try:
            port = int(value)
        except (TypeError, ValueError):
            continue
        if 1 <= port <= 65535 and port not in ports:
            ports.append(port)
    return ports


def read_gluetun_native_ports(api_url: str | None = None, timeout: float = 5.0) -> dict:
    """Read Gluetun native port forwarding status from the Control Server."""
    base = (api_url or get_setting('port_forward_gluetun_api_url', '') or '').strip().rstrip('/')
    if not base:
        return {'ok': False, 'ports': [], 'error': 'URL Control Server Gluetun absente.'}
    try:
        api_key = (get_setting('port_forward_gluetun_api_key', '') or '').strip()
        headers = {'X-API-Key': api_key} if api_key else {}
        resp = requests.get(base + '/v1/portforward', headers=headers, timeout=timeout)
        if resp.status_code >= 400:
            return {'ok': False, 'ports': [], 'error': f'Gluetun /v1/portforward HTTP {resp.status_code}'}
        try:
            payload = resp.json()
        except ValueError:
            payload = resp.text
        ports = _extract_ports(payload)
        return {'ok': bool(ports), 'ports': ports, 'raw': payload, 'error': '' if ports else 'Aucun port retourné.'}
    except Exception as exc:
        return {'ok': False, 'ports': [], 'error': str(exc)}


def get_gluetun_provider(container_name: str) -> str:
    try:
        env = _container_env(container_name)
    except Exception:
        return ''
    return (env.get('VPN_SERVICE_PROVIDER') or '').strip().lower()


def _effective_port(pf: dict, native_ports: list[int]) -> tuple[int | None, str]:
    mode = (pf.get('mode') or 'manual').strip().lower()
    if mode == 'native':
        if native_ports:
            return int(native_ports[0]), ''
        return None, 'Port natif Gluetun indisponible.'
    port = int(pf.get('port') or 0)
    return (port, '') if 1 <= port <= 65535 else (None, 'Port manuel invalide.')


def _set_last_applied_port(port_forward_id: int, port: int) -> None:
    with get_db() as db:
        db.execute(
            'UPDATE port_forwards SET last_applied_port=?, updated_at=CURRENT_TIMESTAMP WHERE id=?',
            (port, port_forward_id),
        )


def _run_port_hook(pf: dict, port: int) -> dict:
    cmd = (pf.get('on_port_change_cmd') or '').strip()
    if not cmd:
        return {'ok': True, 'skipped': True, 'error': ''}
    timeout = int(get_setting('port_forward_hook_timeout_secs', '20') or '20')
    mapping = {
        'port': str(port),
        'provider': str(pf.get('provider') or ''),
        'name': str(pf.get('name') or ''),
        'protocols': str(pf.get('protocols') or ''),
        'client': str(pf.get('client_name') or ''),
    }
    rendered = cmd
    for key, value in mapping.items():
        rendered = rendered.replace('{' + key + '}', value)
    try:
        proc = subprocess.run(
            rendered,
            shell=True,
            text=True,
            capture_output=True,
            timeout=max(1, min(timeout, 120)),
        )
        return {
            'ok': proc.returncode == 0,
            'skipped': False,
            'returncode': proc.returncode,
            'stdout': (proc.stdout or '')[-500:],
            'stderr': (proc.stderr or '')[-500:],
            'error': '' if proc.returncode == 0 else f'hook exit {proc.returncode}',
        }
    except Exception as exc:
        return {'ok': False, 'skipped': False, 'error': str(exc)}


def sync_qbit_listen_port(port_forward_id: int, timeout: float = 6.0, port_override: int | None = None) -> dict:
    pf = get_port_forward(port_forward_id)
    if not pf:
        return {'ok': False, 'error': 'Port forward introuvable.'}
    if port_override is None and (pf.get('mode') or 'manual') == 'native':
        native = read_gluetun_native_ports()
        ports = native.get('ports') or []
        if not ports:
            return {'ok': False, 'error': native.get('error') or 'Port natif Gluetun indisponible.'}
        port_override = int(ports[0])
    client_id = int(pf.get('torrent_client_id') or 0)
    client = get_torrent_client(client_id) if client_id else None
    if not client:
        return {'ok': False, 'error': 'Aucun client BitTorrent lié.'}
    if client.get('client_type') != 'qbittorrent':
        return {'ok': False, 'error': 'Synchronisation disponible uniquement pour qBittorrent.'}
    try:
        sess = _qbit_session(client, timeout=timeout)
        base_url = (client.get('base_url') or '').rstrip('/')
        resp = sess.post(
            base_url + '/api/v2/app/setPreferences',
            data={'json': json.dumps({'listen_port': int(port_override or pf['port'])})},
            timeout=timeout,
        )
        if resp.status_code >= 400:
            return {'ok': False, 'error': f'qBittorrent setPreferences failed ({resp.status_code})'}
        listen_port, err = _qbit_listen_port(client, timeout=timeout)
        expected = int(port_override or pf['port'])
        if listen_port == expected:
            _set_last_applied_port(int(pf['id']), expected)
        return {'ok': listen_port == expected, 'listen_port': listen_port, 'error': err}
    except Exception as exc:
        return {'ok': False, 'error': str(exc)}


def apply_provider_port_forwards(
    provider: str,
    *,
    reason: str = 'provider_change',
    retries: int = 5,
    retry_delay: float = 3.0,
) -> dict:
    """Apply enabled qBittorrent port rules for a provider after a VPN switch."""
    provider = (provider or '').strip().lower()
    result = {
        'ok': True,
        'enabled': get_setting('port_forward_enabled', '0') == '1',
        'auto_sync': get_setting('port_forward_auto_sync', '0') == '1',
        'provider': provider,
        'reason': reason,
        'rules': 0,
        'applied': 0,
        'skipped': 0,
        'errors': [],
        'details': [],
    }
    if not result['enabled']:
        result['skipped_reason'] = 'disabled'
        return result
    if not provider:
        result['ok'] = False
        result['skipped_reason'] = 'missing_provider'
        return result

    forwards = list_active_provider_forwards(provider)
    native = read_gluetun_native_ports() if any((pf.get('mode') or '') == 'native' for pf in forwards) else {'ok': True, 'ports': []}
    result['native'] = native
    result['rules'] = len(forwards)
    for pf in forwards:
        effective_port, port_error = _effective_port(pf, native.get('ports') or [])
        detail = {
            'id': pf.get('id'),
            'name': pf.get('name'),
            'port': effective_port or pf.get('port'),
            'mode': pf.get('mode') or 'manual',
            'client': pf.get('client_name') or '',
            'client_type': pf.get('client_type') or '',
            'ok': False,
            'skipped': False,
            'error': '',
        }
        if not effective_port:
            detail.update({'skipped': True, 'error': port_error})
            result['ok'] = False
            result['errors'].append(f"{detail['name']}: {port_error}")
            result['details'].append(detail)
            continue

        hook = _run_port_hook(pf, effective_port)
        detail['hook'] = hook
        if hook.get('ok') is False:
            result['ok'] = False
            result['errors'].append(f"{detail['name']}: {hook.get('error') or 'hook failed'}")

        if not pf.get('torrent_client_id'):
            if hook.get('skipped'):
                detail.update({'skipped': True, 'error': 'Aucun client lié.'})
                result['skipped'] += 1
            else:
                detail['ok'] = bool(hook.get('ok'))
                if detail['ok']:
                    _set_last_applied_port(int(pf['id']), effective_port)
                    result['applied'] += 1
                else:
                    result['skipped'] += 1
            result['details'].append(detail)
            continue
        if pf.get('client_type') != 'qbittorrent':
            if hook.get('skipped'):
                detail.update({'skipped': True, 'error': 'Client non synchronisable automatiquement.'})
                result['skipped'] += 1
            else:
                detail['ok'] = bool(hook.get('ok'))
                if detail['ok']:
                    _set_last_applied_port(int(pf['id']), effective_port)
                    result['applied'] += 1
            result['details'].append(detail)
            continue

        last = {'ok': False, 'error': ''}
        for attempt in range(max(1, retries)):
            last = sync_qbit_listen_port(int(pf['id']), port_override=effective_port)
            if last.get('ok'):
                break
            if attempt < retries - 1:
                time.sleep(max(0.0, retry_delay))
        qbit_ok = bool(last.get('ok'))
        hook_ok = bool(hook.get('ok'))
        detail['ok'] = qbit_ok and hook_ok
        detail['listen_port'] = last.get('listen_port')
        detail['error'] = last.get('error') or (hook.get('error') or '')
        if detail['ok']:
            _set_last_applied_port(int(pf['id']), effective_port)
            result['applied'] += 1
        else:
            result['ok'] = False
            result['errors'].append(f"{detail['name']}: {detail['error'] or 'sync failed'}")
        result['details'].append(detail)
        continue

    set_setting('port_forward_last_auto_result', json.dumps({
        **result,
        'finished_at': time.strftime('%Y-%m-%d %H:%M:%S'),
    }, ensure_ascii=False))
    logger.info(
        'Port forward provider apply: provider=%s rules=%d applied=%d skipped=%d ok=%s',
        provider, result['rules'], result['applied'], result['skipped'], result['ok'],
    )
    return result


def apply_after_provider_change(old_provider: str, new_provider: str, *, reason: str) -> dict:
    old_provider = (old_provider or '').strip().lower()
    new_provider = (new_provider or '').strip().lower()
    result = {
        'ok': True,
        'old_provider': old_provider,
        'new_provider': new_provider,
        'provider_changed': bool(new_provider and new_provider != old_provider),
        'enabled': get_setting('port_forward_enabled', '0') == '1',
        'auto_sync': get_setting('port_forward_auto_sync', '0') == '1',
        'reason': reason,
    }
    if not result['enabled']:
        result['skipped_reason'] = 'disabled'
        return result
    if not result['auto_sync']:
        result['skipped_reason'] = 'manual_only'
        return result
    if not result['provider_changed']:
        result['skipped_reason'] = 'same_provider'
        return result
    applied = apply_provider_port_forwards(new_provider, reason=reason)
    result.update(applied)
    result['old_provider'] = old_provider
    result['new_provider'] = new_provider
    result['provider_changed'] = True
    return result


def inspect_port_forward(pf: dict, gluetun_container: str) -> dict:
    item = dict(pf)
    protocols = _clean_protocols(item.get('protocols')).split(',')
    port = int(item.get('port') or 0)

    env = {}
    env_error = ''
    try:
        env = _container_env(gluetun_container)
    except Exception as exc:
        env_error = str(exc)

    fw_vpn_ports = _parse_port_list(env.get('FIREWALL_VPN_INPUT_PORTS', '')) if env else set()
    fw_input_ports = _parse_port_list(env.get('FIREWALL_INPUT_PORTS', '')) if env else set()
    docker_ports = _docker_published_ports(gluetun_container, port, protocols)

    client_status = {'state': 'unknown', 'label': 'non lié'}
    client_listen_port = None
    client_error = ''
    if item.get('torrent_client_id'):
        client = get_torrent_client(int(item['torrent_client_id']))
        if client and client.get('client_type') == 'qbittorrent':
            client_listen_port, client_error = _qbit_listen_port(client)
            client_status = _status(client_listen_port == port if client_listen_port else False, 'OK', 'différent')
        elif client:
            client_status = {'state': 'unknown', 'label': 'lecture non supportée'}

    item['protocol_list'] = protocols
    item['gluetun_vpn_input'] = _status(port in fw_vpn_ports if env else None)
    item['gluetun_input'] = _status(port in fw_input_ports if env else None)
    item['docker_ports'] = {proto: _status(docker_ports.get(proto), proto.upper(), proto.upper()) for proto in protocols}
    item['client_status'] = client_status
    item['client_listen_port'] = client_listen_port
    item['client_error'] = client_error
    item['env_error'] = env_error

    checks = [
        item['gluetun_vpn_input']['state'],
        item['gluetun_input']['state'],
        *[v['state'] for v in item['docker_ports'].values()],
    ]
    if item.get('torrent_client_id'):
        checks.append(client_status['state'])
    if 'bad' in checks:
        item['overall_state'] = 'bad'
        item['overall_label'] = 'À corriger'
    elif 'unknown' in checks:
        item['overall_state'] = 'unknown'
        item['overall_label'] = 'À vérifier'
    else:
        item['overall_state'] = 'ok'
        item['overall_label'] = 'OK'
    return item


def inspect_port_forwards(gluetun_container: str) -> list[dict]:
    return [inspect_port_forward(pf, gluetun_container) for pf in list_port_forwards()]
