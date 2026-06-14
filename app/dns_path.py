"""Detect the DNS intermediary and the recursive resolvers observed on the Internet."""

from __future__ import annotations

import ipaddress
import json
import logging
import re
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import docker

from .database import get_setting, set_setting
from .gluetun import get_container_env


logger = logging.getLogger(__name__)

_CACHE: dict[str, object] = {'ts': 0.0, 'container': '', 'lang': '', 'result': None}
_CACHE_LOCK = threading.Lock()
_REFRESH_LOCK = threading.Lock()
_CACHE_TTL = 60.0
_OBSERVATION_TTL = 6 * 3600
_DNS_OBSERVER_NAME = 'gluetun-companion-dns-observer'

_PUBLIC_DNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ('Cloudflare', ('1.1.1.1', '1.0.0.1', '2606:4700:4700::1111',
                    '2606:4700:4700::1001', 'cloudflare', 'cloudflare-dns.com')),
    ('Quad9', ('9.9.9.9', '149.112.112.112', '2620:fe::fe', '2620:fe::9', 'quad9')),
    ('Google Public DNS', ('8.8.8.8', '8.8.4.4', '2001:4860:4860::8888',
                           '2001:4860:4860::8844', 'google')),
    ('AdGuard DNS', ('94.140.14.14', '94.140.15.15', 'adguard')),
    ('Mullvad DNS', ('194.242.2.2', '193.19.108.2', 'mullvad')),
    ('OpenDNS', ('208.67.222.222', '208.67.220.220', 'opendns')),
    ('NextDNS', ('45.90.28.', '45.90.30.', 'nextdns')),
    ('Control D', ('76.76.2.', '76.76.10.', 'control d', 'controld')),
)


def _labels(lang: str) -> dict[str, str]:
    if lang == 'en':
        return {
            'local': 'Local DNS', 'vpn': 'VPN provider DNS', 'public': 'DNS server',
            'unknown': 'DNS intermediary', 'intermediary': 'Intermediary',
            'probable': 'Probable intermediary', 'observed': 'Observed resolvers',
            'pending': 'Detection pending', 'unavailable': 'Unavailable',
        }
    return {
        'local': 'DNS local', 'vpn': 'DNS du fournisseur VPN', 'public': 'Serveur DNS',
        'unknown': 'Intermédiaire DNS', 'intermediary': 'Intermédiaire',
        'probable': 'Intermédiaire probable', 'observed': 'Résolveurs observés',
        'pending': 'Détection en attente', 'unavailable': 'Indisponible',
    }


def _strip_endpoint(value: str) -> str:
    value = (value or '').strip()
    if not value:
        return ''
    parsed = urlparse(value if '://' in value else f'//{value}')
    return (parsed.hostname or value.strip('[]')).strip()


def _split_values(raw: str) -> list[str]:
    return [value.strip() for value in re.split(r'[,\n]+', raw or '') if value.strip()]


def _provider_name(*values: str) -> str:
    text = ' '.join(values).lower()
    host = _strip_endpoint(values[0]).lower() if values else ''
    for label, needles in _PUBLIC_DNS:
        if any(host == needle or host.startswith(needle) or needle in text for needle in needles):
            return label
    return ''


def _provider_display(provider: str) -> str:
    if not provider:
        return ''
    known = {
        'airvpn': 'AirVPN', 'ivpn': 'IVPN', 'mullvad': 'Mullvad',
        'nordvpn': 'NordVPN', 'protonvpn': 'ProtonVPN',
        'surfshark': 'Surfshark', 'windscribe': 'Windscribe',
    }
    if provider.lower() in known:
        return known[provider.lower()]
    return provider.replace('_', ' ').replace('-', ' ').title()


def _intermediary(env: dict[str, str], lang: str) -> dict:
    labels = _labels(lang)
    provider = _provider_display(env.get('VPN_SERVICE_PROVIDER', ''))
    resolver_type = (env.get('DNS_UPSTREAM_RESOLVER_TYPE') or 'dot').lower()
    values = _split_values(env.get('DNS_UPSTREAM_PLAIN_ADDRESSES', ''))
    if not values:
        values = _split_values(
            env.get('DNS_UPSTREAM_RESOLVERS', '')
            or env.get('DNS_UPSTREAM_RESOLVER', '')
            or env.get('DOT_PROVIDERS', '')
        )

    address = _strip_endpoint(values[0]) if values else ''
    if address:
        public_name = _provider_name(values[0])
        if public_name:
            return {'label': public_name, 'address': address, 'probable': False}
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            return {'label': labels['public'], 'address': address, 'probable': False}
        if ip.is_private:
            if ip.version == 4 and (address.startswith('192.168.') or address.startswith('172.')):
                return {'label': labels['local'], 'address': address, 'probable': False}
            if provider and provider.lower() != 'custom':
                return {
                    'label': f"{labels['vpn']} {provider}",
                    'address': address,
                    'probable': True,
                }
            return {'label': labels['local'], 'address': address, 'probable': False}
        return {'label': labels['public'], 'address': address, 'probable': False}

    if env.get('DNS_KEEP_NAMESERVER', '').lower() in ('on', 'true', 'yes', '1'):
        label = f"{labels['vpn']} {provider}" if provider else labels['vpn']
        return {'label': label, 'address': '', 'probable': True}
    if resolver_type == 'dot':
        return {'label': 'Cloudflare', 'address': '', 'probable': False}
    return {'label': labels['unknown'], 'address': env.get('DNS_ADDRESS', ''), 'probable': True}


def _load_observation() -> dict:
    try:
        data = json.loads(get_setting('dns_observed_result', '{}') or '{}')
        return data if isinstance(data, dict) else {}
    except (TypeError, ValueError):
        return {}


def _observation_is_stale(observation: dict) -> bool:
    ttl = _OBSERVATION_TTL if observation.get('resolvers') else 5 * 60
    return time.time() - float(observation.get('timestamp') or 0) >= ttl


def _remove_observer(client) -> None:
    try:
        client.containers.get(_DNS_OBSERVER_NAME).remove(force=True)
    except docker.errors.NotFound:
        pass


def _run_observation_sidecar(container_name: str) -> list[dict]:
    """Run the complete bash.ws test through Gluetun without Docker exec."""
    client = docker.from_env()
    _remove_observer(client)
    image = get_setting('sidecar_image', 'ghcr.io/aerya/gluetun-companion-sidecar:latest')
    command = r'''
set -eu
test_id="$(curl -fsSL --max-time 10 https://bash.ws/id)"
case "$test_id" in *[!A-Za-z0-9_-]*|'') exit 2 ;; esac
for index in 0 1 2 3 4 5 6 7 8 9; do
  dig +time=2 +tries=1 "${index}.${test_id}.bash.ws" >/dev/null 2>&1 || true
done
curl -fsSL --max-time 15 "https://bash.ws/dnsleak/test/${test_id}?json"
'''.strip()
    container = None
    try:
        container = client.containers.run(
            image=image,
            name=_DNS_OBSERVER_NAME,
            network_mode=f'container:{container_name}',
            command=['sh', '-c', command],
            detach=True,
            remove=False,
        )
        deadline = time.time() + 35
        while time.time() < deadline:
            container.reload()
            if container.status in ('exited', 'dead'):
                break
            time.sleep(0.5)
        else:
            raise TimeoutError('DNS observation sidecar timed out')
        exit_code = int(container.attrs.get('State', {}).get('ExitCode', 1))
        output = container.logs(stdout=True, stderr=True).decode('utf-8', errors='replace').strip()
        if exit_code != 0:
            raise RuntimeError(f'DNS observation sidecar exited with code {exit_code}: {output}')
        payload = json.loads(output)
        if not isinstance(payload, list):
            raise RuntimeError('bash.ws returned an invalid DNS observation payload')
        return payload
    finally:
        if container is not None:
            try:
                container.remove(force=True)
            except Exception as exc:
                logger.debug('Could not remove DNS observation sidecar: %s', exc)


def refresh_observed_resolvers(container_name: str) -> dict:
    """Run a bash.ws observation from inside Gluetun and cache its result."""
    if not _REFRESH_LOCK.acquire(blocking=False):
        return _load_observation()
    try:
        payload = _run_observation_sidecar(container_name)
        resolvers: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in payload if isinstance(payload, list) else []:
            if item.get('type') != 'dns':
                continue
            ip = str(item.get('ip') or '').strip()
            if not ip or ip in seen:
                continue
            asn = str(item.get('asn') or '').strip()
            provider = _provider_name(ip, asn) or asn or 'DNS'
            resolvers.append({
                'ip': ip,
                'provider': provider,
                'country': str(item.get('country_name') or '').strip(),
            })
            seen.add(ip)
        now = time.time()
        observation = {
            'timestamp': now,
            'tested_at': datetime.fromtimestamp(now, timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
            'resolvers': resolvers,
            'error': '' if resolvers else 'No DNS resolver was returned by bash.ws',
        }
        set_setting('dns_observed_result', json.dumps(observation, ensure_ascii=False))
        clear_dns_path_cache()
        return observation
    except Exception as exc:
        logger.warning('DNS resolver observation failed: %s', exc)
        previous = _load_observation()
        if previous.get('resolvers'):
            previous['refresh_error'] = str(exc)
            return previous
        observation = {'timestamp': time.time(), 'resolvers': [], 'error': str(exc)}
        set_setting('dns_observed_result', json.dumps(observation, ensure_ascii=False))
        clear_dns_path_cache()
        return observation
    finally:
        _REFRESH_LOCK.release()


def _refresh_in_background(container_name: str) -> None:
    if _REFRESH_LOCK.locked():
        return
    threading.Thread(
        target=refresh_observed_resolvers,
        args=(container_name,),
        daemon=True,
        name='dns-resolver-observation',
    ).start()


def _build_dns_status(container_name: str, lang: str) -> dict:
    labels = _labels(lang)
    try:
        env = get_container_env(container_name)
    except Exception as exc:
        return {
            'ok': False, 'intermediary': {}, 'resolvers': [], 'tooltip': '',
            'observed_summary': labels['unavailable'], 'error': str(exc),
        }
    intermediary = _intermediary(env, lang)
    observation = _load_observation()
    if _observation_is_stale(observation):
        _refresh_in_background(container_name)
    resolvers = observation.get('resolvers') or []
    observed_names: list[str] = []
    for resolver in resolvers:
        name = resolver.get('provider') or resolver.get('ip')
        if name and name not in observed_names:
            observed_names.append(name)
    observed_summary = ', '.join(observed_names) or labels['pending']
    intermediary_title = labels['probable'] if intermediary.get('probable') else labels['intermediary']
    intermediary_value = intermediary.get('label', '')
    if intermediary.get('address'):
        intermediary_value += f" ({intermediary['address']})"
    resolver_details = ', '.join(
        f"{r.get('provider') or 'DNS'} ({r.get('ip')})" for r in resolvers
    ) or labels['pending']
    return {
        'ok': True,
        'intermediary': intermediary,
        'intermediary_title': intermediary_title,
        'intermediary_value': intermediary_value,
        'resolvers': resolvers,
        'observed_summary': observed_summary,
        'tested_at': observation.get('tested_at', ''),
        'tooltip': f"{intermediary_title} : {intermediary_value} · {labels['observed']} : {resolver_details}",
        'error': observation.get('error', ''),
    }


def get_dns_path(container_name: str, lang: str = 'fr', force: bool = False) -> dict:
    now = time.time()
    with _CACHE_LOCK:
        cached = _CACHE.get('result')
        if (not force and cached and _CACHE.get('container') == container_name
                and _CACHE.get('lang') == lang
                and now - float(_CACHE.get('ts') or 0) < _CACHE_TTL):
            return dict(cached)
        result = _build_dns_status(container_name, lang)
        _CACHE.update({'ts': now, 'container': container_name, 'lang': lang, 'result': result})
        return dict(result)


def clear_dns_path_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.update({'ts': 0.0, 'container': '', 'lang': '', 'result': None})
