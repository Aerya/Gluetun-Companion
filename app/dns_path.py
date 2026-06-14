"""Resolve the currently configured DNS path used by Gluetun."""

from __future__ import annotations

import ipaddress
import re
import threading
import time
from urllib.parse import urlparse

import requests

from .database import get_setting
from .gluetun import get_container_env
from .crypto import decrypt


_CACHE: dict[str, object] = {'ts': 0.0, 'container': '', 'lang': '', 'result': None}
_CACHE_LOCK = threading.Lock()
_CACHE_TTL = 60.0

_PROVIDERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ('Cloudflare', ('1.1.1.1', '1.0.0.1', '2606:4700:4700::1111',
                    '2606:4700:4700::1001', 'cloudflare', 'cloudflare-dns.com', 'one.one.one.one')),
    ('Quad9', ('9.9.9.9', '149.112.112.112', '2620:fe::fe', '2620:fe::9', 'quad9', 'quad9.net')),
    ('Google Public DNS', ('8.8.8.8', '8.8.4.4', '2001:4860:4860::8888',
                           '2001:4860:4860::8844', 'google', 'dns.google')),
    ('AdGuard DNS', ('94.140.14.14', '94.140.15.15', '2a10:50c0::ad1:ff',
                     '2a10:50c0::ad2:ff', 'adguard', 'dns.adguard-dns.com', 'dns-family.adguard.com')),
    ('Mullvad DNS', ('194.242.2.2', '193.19.108.2', 'mullvad', 'dns.mullvad.net')),
    ('OpenDNS', ('208.67.222.222', '208.67.220.220', 'opendns', 'dns.opendns.com')),
    ('NextDNS', ('45.90.28.', '45.90.30.', 'dns.nextdns.io')),
    ('Control D', ('76.76.2.', '76.76.10.', 'controld.com')),
)


def _strip_endpoint(value: str) -> str:
    value = value.strip()
    if not value or value.startswith('#'):
        return ''
    if value.startswith('[/') and ']' in value:
        value = value.split(']', 1)[1]
    parsed = urlparse(value if '://' in value else f'//{value}')
    host = parsed.hostname
    if host:
        return host
    return value.strip('[]').split('#', 1)[0].strip()


def _provider_for(value: str) -> str:
    host = _strip_endpoint(value).lower().rstrip('.')
    for label, needles in _PROVIDERS:
        if any(host == needle or host.endswith('.' + needle) or host.startswith(needle)
               for needle in needles):
            return label
    return ''


def _is_private(value: str) -> bool:
    try:
        return ipaddress.ip_address(_strip_endpoint(value)).is_private
    except ValueError:
        return False


def _split_values(raw: str) -> list[str]:
    return [item.strip() for item in re.split(r'[,\n]+', raw or '') if item.strip()]


def _node(label: str, address: str = '', kind: str = '') -> dict[str, str]:
    return {'label': label, 'address': address, 'kind': kind}


def _labels(lang: str) -> dict[str, str]:
    if lang == 'en':
        return {
            'gluetun': 'Gluetun DNS', 'local': 'Local DNS',
            'private_vpn': 'Private / VPN provider DNS', 'upstream': 'Upstream DNS',
            'configured': 'Configured resolver', 'inherited': 'Inherited / VPN provider DNS',
            'public': 'Public DNS',
        }
    return {
        'gluetun': 'DNS Gluetun', 'local': 'DNS local',
        'private_vpn': 'DNS privé / fournisseur VPN', 'upstream': 'DNS amont',
        'configured': 'Résolveur configuré', 'inherited': 'DNS hérité / fournisseur VPN',
        'public': 'DNS public',
    }


def _read_adguard_upstreams() -> tuple[list[str], str]:
    if get_setting('dns_adguard_enabled', '0') != '1':
        return [], ''
    base = get_setting('dns_adguard_url', '').strip().rstrip('/')
    if not base:
        return [], ''
    auth = None
    username = get_setting('dns_adguard_username', '').strip()
    try:
        password = decrypt(get_setting('dns_adguard_password', ''))
    except ValueError as exc:
        return [], str(exc)
    if username:
        auth = (username, password)
    try:
        response = requests.get(f'{base}/control/dns_info', auth=auth, timeout=3)
        response.raise_for_status()
        data = response.json()
        upstreams = list(data.get('upstream_dns') or [])
        if data.get('upstream_dns_file'):
            upstreams.append(data['upstream_dns_file'])
        return [str(item) for item in upstreams if str(item).strip()], ''
    except Exception as exc:
        return [], str(exc)


def _configured_local_host() -> str:
    configured = _strip_endpoint(get_setting('dns_local_address', ''))
    if configured:
        return configured
    url = get_setting('dns_adguard_url', '').strip()
    if not url:
        return ''
    return urlparse(url).hostname or ''


def _upstream_nodes(values: list[str], fallback_label: str) -> list[dict[str, str]]:
    nodes: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for value in values:
        host = _strip_endpoint(value)
        if not host:
            continue
        provider = _provider_for(value)
        label = provider or fallback_label
        key = (label, host)
        if key not in seen:
            nodes.append(_node(label, host, 'upstream'))
            seen.add(key)
    return nodes


def _build_dns_path(container_name: str, lang: str = 'fr') -> dict:
    labels = _labels(lang)
    try:
        env = get_container_env(container_name)
        docker_error = ''
    except Exception as exc:
        env = {}
        docker_error = str(exc)

    if docker_error:
        return {
            'nodes': [], 'short': '', 'detail': '', 'resolver_type': '',
            'errors': [docker_error], 'ok': False,
        }

    resolver_type = (env.get('DNS_UPSTREAM_RESOLVER_TYPE')
                     or env.get('DNS_UPSTREAM_TYPE') or 'dot').lower()
    nodes = [_node(labels['gluetun'], env.get('DNS_ADDRESS', '127.0.0.1'), 'gluetun')]
    errors: list[str] = []

    plain_values = _split_values(env.get('DNS_UPSTREAM_PLAIN_ADDRESSES', ''))
    resolver_values = _split_values(
        env.get('DNS_UPSTREAM_RESOLVERS', '')
        or env.get('DNS_UPSTREAM_RESOLVER', '')
        or env.get('DOT_PROVIDERS', '')
    )

    if resolver_type == 'plain' and plain_values:
        for address in plain_values:
            host = _strip_endpoint(address)
            if _is_private(address):
                configured_local = _configured_local_host()
                is_configured_local = bool(configured_local and host == configured_local)
                if is_configured_local:
                    local_label = get_setting('dns_local_label', '').strip() or labels['local']
                else:
                    local_label = labels['private_vpn']
                nodes.append(_node(local_label, host, 'local'))
                adguard_upstreams, adguard_error = (
                    _read_adguard_upstreams() if is_configured_local else ([], '')
                )
                manual = _split_values(get_setting('dns_manual_upstreams', ''))
                upstreams = adguard_upstreams or (manual if is_configured_local else [])
                if adguard_error:
                    errors.append(adguard_error)
                nodes.extend(_upstream_nodes(upstreams, labels['upstream']))
            else:
                nodes.extend(_upstream_nodes([address], labels['public']))
    elif resolver_values:
        nodes.extend(_upstream_nodes(resolver_values, labels['configured']))
    elif env.get('DNS_KEEP_NAMESERVER', '').lower() in ('on', 'true', 'yes', '1'):
        nodes.append(_node(labels['inherited'], '', 'vpn'))
    else:
        # Gluetun uses Cloudflare by default when its internal encrypted resolver
        # is enabled and no explicit upstream is configured.
        nodes.append(_node('Cloudflare', '', 'upstream'))

    labels: list[str] = []
    details: list[str] = []
    for node in nodes:
        if node['label'] not in labels:
            labels.append(node['label'])
        details.append(
            f"{node['label']} ({node['address']})" if node['address'] else node['label']
        )

    return {
        'nodes': nodes,
        'short': ' → '.join(labels),
        'detail': ' → '.join(details),
        'resolver_type': resolver_type,
        'errors': errors,
        'ok': True,
    }


def get_dns_path(container_name: str, lang: str = 'fr', force: bool = False) -> dict:
    now = time.time()
    with _CACHE_LOCK:
        cached = _CACHE.get('result')
        if (not force and cached and _CACHE.get('container') == container_name
                and _CACHE.get('lang') == lang
                and now - float(_CACHE.get('ts') or 0) < _CACHE_TTL):
            return dict(cached)
        result = _build_dns_path(container_name, lang=lang)
        _CACHE.update({'ts': now, 'container': container_name, 'lang': lang, 'result': result})
        return dict(result)


def clear_dns_path_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.update({'ts': 0.0, 'container': '', 'lang': '', 'result': None})
