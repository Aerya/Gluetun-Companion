import json
import logging

import docker

from .database import get_db
from .gluetun import _container_env
from .torrent_trackers import get_torrent_client, _qbit_session

logger = logging.getLogger(__name__)


SUPPORTED_PROVIDERS = {'airvpn', 'manual'}
SUPPORTED_MODES = {'manual'}
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
    if provider not in SUPPORTED_PROVIDERS:
        provider = 'manual'
    mode = (data.get('mode') or 'manual').strip().lower()
    if mode not in SUPPORTED_MODES:
        mode = 'manual'
    port = int(data.get('port') or 0)
    if not (1 <= port <= 65535):
        raise ValueError('Port invalide.')
    protocols = _clean_protocols(data.get('protocols'))
    name = (data.get('name') or '').strip() or f'{provider}:{port}'
    notes = (data.get('notes') or '').strip()
    torrent_client_id = int(data.get('torrent_client_id') or 0) or None
    enabled = 1 if data.get('enabled') else 0
    port_forward_id = int(data.get('id') or 0)

    with get_db() as db:
        if port_forward_id:
            db.execute(
                '''UPDATE port_forwards
                   SET name=?, provider=?, mode=?, port=?, protocols=?,
                       torrent_client_id=?, enabled=?, notes=?, updated_at=CURRENT_TIMESTAMP
                   WHERE id=?''',
                (name, provider, mode, port, protocols, torrent_client_id, enabled, notes, port_forward_id),
            )
            return port_forward_id
        cur = db.execute(
            '''INSERT INTO port_forwards
               (name, provider, mode, port, protocols, torrent_client_id, enabled, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
            (name, provider, mode, port, protocols, torrent_client_id, enabled, notes),
        )
        return int(cur.lastrowid)


def delete_port_forward(port_forward_id: int) -> bool:
    with get_db() as db:
        cur = db.execute('DELETE FROM port_forwards WHERE id=?', (port_forward_id,))
        return cur.rowcount > 0


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


def sync_qbit_listen_port(port_forward_id: int, timeout: float = 6.0) -> dict:
    pf = get_port_forward(port_forward_id)
    if not pf:
        return {'ok': False, 'error': 'Port forward introuvable.'}
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
            data={'json': json.dumps({'listen_port': int(pf['port'])})},
            timeout=timeout,
        )
        if resp.status_code >= 400:
            return {'ok': False, 'error': f'qBittorrent setPreferences failed ({resp.status_code})'}
        listen_port, err = _qbit_listen_port(client, timeout=timeout)
        return {'ok': listen_port == int(pf['port']), 'listen_port': listen_port, 'error': err}
    except Exception as exc:
        return {'ok': False, 'error': str(exc)}


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
