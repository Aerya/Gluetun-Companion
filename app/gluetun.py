"""
Gluetun container control + VPN connectivity helpers.

Network architecture (no shared Docker network required)
---------------------------------------------------------
- Docker socket  → read container env (current filters), switch server via
                   docker compose up --force-recreate
- Proxy port     → VPN status check, public IP, wait loop.
                   The proxy is exposed on the host so the companion reaches it
                   via host.docker.internal (see docker-compose.yml extra_hosts).
"""

import os
import subprocess
import time
import logging
from urllib.parse import quote

import docker
import requests

logger = logging.getLogger(__name__)

_PROBE_URL = 'https://www.cloudflare.com/cdn-cgi/trace'

# Mapping: short label → Gluetun environment variable name
FILTER_VARS: dict[str, str] = {
    'name':     'SERVER_NAMES',
    'country':  'SERVER_COUNTRIES',
    'region':   'SERVER_REGIONS',
    'city':     'SERVER_CITIES',
    'hostname': 'SERVER_HOSTNAMES',
}

FILTER_LABELS: dict[str, str] = {
    'name':     'Nom',
    'country':  'Pays',
    'region':   'Région',
    'city':     'Ville',
    'hostname': 'Hostname',
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _proxies(
    host: str,
    port: int,
    user: str | None = None,
    password: str | None = None,
) -> dict:
    creds = f'{quote(user, safe="")}:{quote(password or "", safe="")}@' if user else ''
    proxy = f'http://{creds}{host}:{port}'
    return {'http': proxy, 'https': proxy}


def _probe(proxy_host: str, proxy_port: int, user: str | None, password: str | None):
    px = _proxies(proxy_host, proxy_port, user, password)
    return requests.get(_PROBE_URL, proxies=px, timeout=10)


def _container_env(container_name: str) -> dict[str, str]:
    """Return the full env dict of a running container."""
    container = docker.from_env().containers.get(container_name)
    env = {}
    for var in container.attrs['Config'].get('Env') or []:
        if '=' in var:
            k, v = var.split('=', 1)
            env[k] = v
    return env


# ---------------------------------------------------------------------------
# Docker / container helpers
# ---------------------------------------------------------------------------

def get_current_filters(container_name: str) -> dict[str, str]:
    """
    Return all non-empty Gluetun filter env vars from the running container
    as {filter_type: value}, e.g. {'name': 'Chamukuy,Elgafar'}.
    """
    result: dict[str, str] = {}
    try:
        env = _container_env(container_name)
        for label, env_var in FILTER_VARS.items():
            val = env.get(env_var, '').strip()
            if val:
                result[label] = val
    except Exception as exc:
        logger.warning('get_current_filters: %s', exc)
    return result


def format_filters(filters: dict[str, str]) -> str:
    """Human-readable representation of active filters, e.g. 'SERVER_NAMES=Chamukuy'."""
    if not filters:
        return '—'
    return '  '.join(f'{FILTER_VARS[k]}={v}' for k, v in filters.items())


def switch_server(
    filter_value: str,
    filter_type: str,
    container_name: str,
    compose_dir: str,
    compose_project: str = '',
) -> tuple[bool, str | None]:
    """
    Write a docker-compose.override.yml that sets the correct Gluetun filter
    variable to `filter_value` and clears all other filter variables (so they
    don't conflict with values from the main compose file).

    Returns (success, error_message).
    """
    env_var = FILTER_VARS.get(filter_type, 'SERVER_NAMES')

    # Build environment block: set target var, blank-out all others
    env_lines = ''
    for label, var in FILTER_VARS.items():
        value = filter_value if var == env_var else ''
        env_lines += f'      {var}: "{value}"\n'

    override = (
        f'services:\n'
        f'  {container_name}:\n'
        f'    environment:\n'
        f'{env_lines}'
    )
    override_path = os.path.join(compose_dir, 'docker-compose.override.yml')
    try:
        with open(override_path, 'w') as fh:
            fh.write(override)
    except OSError as exc:
        return False, f'Cannot write override file: {exc}'

    cmd = ['docker', 'compose']
    if compose_project:
        cmd += ['-p', compose_project]
    cmd += ['up', '-d', '--force-recreate', container_name]

    try:
        result = subprocess.run(
            cmd,
            cwd=compose_dir,
            capture_output=True,
            text=True,
            timeout=90,
        )
        if result.returncode != 0:
            err = (result.stderr or result.stdout or 'unknown error').strip()
            logger.error('docker compose failed: %s', err)
            return False, err
        return True, None
    except subprocess.TimeoutExpired:
        return False, 'docker compose timed out after 90s'
    except FileNotFoundError:
        return False, 'docker binary not found in PATH'
    except Exception as exc:
        return False, str(exc)


# ---------------------------------------------------------------------------
# Proxy-based VPN status / IP helpers
# ---------------------------------------------------------------------------

def get_vpn_status(
    proxy_host: str,
    proxy_port: int,
    proxy_user: str | None = None,
    proxy_password: str | None = None,
) -> str:
    try:
        resp = _probe(proxy_host, proxy_port, proxy_user, proxy_password)
        if resp.status_code == 200:
            return 'running'
    except Exception:
        pass
    return 'stopped'


def get_public_ip(
    proxy_host: str,
    proxy_port: int,
    proxy_user: str | None = None,
    proxy_password: str | None = None,
) -> str | None:
    try:
        resp = _probe(proxy_host, proxy_port, proxy_user, proxy_password)
        for line in resp.text.splitlines():
            if line.startswith('ip='):
                return line[3:].strip()
    except Exception:
        pass
    return None


def wait_for_vpn(
    proxy_host: str,
    proxy_port: int,
    timeout: int = 60,
    proxy_user: str | None = None,
    proxy_password: str | None = None,
) -> bool:
    time.sleep(4)
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = _probe(proxy_host, proxy_port, proxy_user, proxy_password)
            if resp.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(3)
    return False
