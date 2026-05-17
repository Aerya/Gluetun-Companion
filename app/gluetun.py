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
import threading
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


def _detect_compose_project(container_name: str) -> str:
    """
    Read the compose project name from the container's Docker labels.
    Docker Compose sets com.docker.compose.project on every managed container.
    """
    try:
        container = docker.from_env().containers.get(container_name)
        project = container.labels.get('com.docker.compose.project', '')
        if project:
            logger.debug('Detected compose project: %s', project)
        return project
    except Exception as exc:
        logger.warning('_detect_compose_project: %s', exc)
        return ''


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

    # Use provided project name, or auto-detect from container labels
    project = compose_project or _detect_compose_project(container_name)

    # Do NOT pass --force-recreate or a specific service name.
    # Compose compares desired state (main file + override) with running containers:
    # - gluetun gets recreated because its env changed
    # - services using network_mode: service:gluetun are automatically restarted
    #   by Compose because their dependency (gluetun's container ID) changed.
    cmd = ['docker', 'compose']
    if project:
        cmd += ['-p', project]
    cmd += ['up', '-d']

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
# Dependent-container restart
# ---------------------------------------------------------------------------

def restart_network_dependents(container_name: str) -> list[str]:
    """
    Find and restart every container whose NetworkMode is
    'container:<container_name>' (i.e. network_mode: service:<container_name>
    in Compose).  Called after the VPN is confirmed up so the dependents
    re-attach to the live network namespace.
    Returns the list of restarted container names.
    """
    restarted: list[str] = []
    try:
        client = docker.from_env()
        target = f'container:{container_name}'
        for c in client.containers.list():
            if c.attrs['HostConfig'].get('NetworkMode') == target:
                logger.info('Restarting network dependent: %s', c.name)
                c.restart(timeout=10)
                restarted.append(c.name)
    except Exception as exc:
        logger.warning('restart_network_dependents: %s', exc)
    return restarted


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


def get_public_ips(
    proxy_host: str,
    proxy_port: int,
    proxy_user: str | None = None,
    proxy_password: str | None = None,
) -> tuple[str | None, str | None]:
    """Return (ipv4, ipv6) by probing Cloudflare's protocol-specific endpoints."""
    px = _proxies(proxy_host, proxy_port, proxy_user, proxy_password)
    ipv4: str | None = None
    ipv6: str | None = None
    for url, kind in [
        ('https://www.cloudflare.com/cdn-cgi/trace',  'v4'),
        ('https://ipv6.cloudflare.com/cdn-cgi/trace', 'v6'),
    ]:
        try:
            resp = requests.get(url, proxies=px, timeout=10)
            for line in resp.text.splitlines():
                if line.startswith('ip='):
                    if kind == 'v4':
                        ipv4 = line[3:].strip()
                    else:
                        ipv6 = line[3:].strip()
                    break
        except Exception:
            pass
    return ipv4, ipv6


# ---------------------------------------------------------------------------
# Sidecar container management
# ---------------------------------------------------------------------------

_TEST_GLUETUN_NAME  = 'gluetun-companion-test'
_SIDECAR_NAME       = 'gluetun-companion-sidecar'


def _remove_container(client, name: str) -> None:
    """Stop and remove a container by name, ignoring NotFound."""
    try:
        c = client.containers.get(name)
        try:
            c.stop(timeout=10)
        except Exception:
            pass
        c.remove(force=True)
    except docker.errors.NotFound:
        pass
    except Exception as exc:
        logger.warning('_remove_container %s: %s', name, exc)


def create_test_gluetun(
    real_container_name: str,
    filter_type: str,
    filter_value: str,
    sidecar_port: int = 8766,
) -> tuple[bool, str | None]:
    """
    Clone the real Gluetun container config, override the SERVER_* filter
    for the target server, and start a new test container.
    The sidecar port is published on the host so the companion can reach the
    sidecar API via host.docker.internal:<sidecar_port>.
    """
    try:
        client = docker.from_env()
        real   = client.containers.get(real_container_name)
        attrs  = real.attrs

        # Build env dict from real container, override filter vars
        env: dict[str, str] = {}
        for var in attrs['Config'].get('Env') or []:
            if '=' in var:
                k, v = var.split('=', 1)
                env[k] = v
        for label, var in FILTER_VARS.items():
            env[var] = ''
        env[FILTER_VARS.get(filter_type, 'SERVER_NAMES')] = filter_value

        image    = attrs['Config']['Image']
        cap_add  = attrs['HostConfig'].get('CapAdd') or []
        sysctls  = attrs['HostConfig'].get('Sysctls') or {}
        devices  = attrs['HostConfig'].get('Devices') or []

        _remove_container(client, _TEST_GLUETUN_NAME)

        client.containers.run(
            image=image,
            name=_TEST_GLUETUN_NAME,
            environment=env,
            cap_add=cap_add,
            sysctls=sysctls,
            devices=devices,
            ports={f'{sidecar_port}/tcp': sidecar_port},
            detach=True,
            remove=False,
        )
        logger.info('Test Gluetun container started: %s → %s=%s',
                    _TEST_GLUETUN_NAME, FILTER_VARS.get(filter_type, 'SERVER_NAMES'), filter_value)
        return True, None
    except Exception as exc:
        return False, str(exc)


def create_speed_sidecar(sidecar_image: str) -> tuple[bool, str | None]:
    """
    Pull the latest sidecar image, then create the container in the test Gluetun
    network namespace. Pulling every time ensures we always run the latest version.
    """
    try:
        client = docker.from_env()

        logger.info('Pulling sidecar image: %s', sidecar_image)
        client.images.pull(sidecar_image)
        logger.info('Sidecar image up to date: %s', sidecar_image)

        _remove_container(client, _SIDECAR_NAME)

        client.containers.run(
            image=sidecar_image,
            name=_SIDECAR_NAME,
            network_mode=f'container:{_TEST_GLUETUN_NAME}',
            detach=True,
            remove=False,
        )
        logger.info('Speed sidecar started: %s (network via %s)', _SIDECAR_NAME, _TEST_GLUETUN_NAME)
        return True, None
    except Exception as exc:
        return False, str(exc)


def stream_sidecar_logs() -> None:
    """Forward gluetun-companion-sidecar container logs to the companion logger (background thread)."""
    _sidecar_logger = logging.getLogger('sidecar')

    def _run():
        try:
            client    = docker.from_env()
            container = client.containers.get(_SIDECAR_NAME)
            for raw in container.logs(stream=True, follow=True):
                line = raw.decode('utf-8', errors='replace').strip()
                if line:
                    _sidecar_logger.info(line)
        except Exception as exc:
            _sidecar_logger.debug('Log stream ended: %s', exc)

    threading.Thread(target=_run, daemon=True, name='sidecar-logs').start()


def wait_for_sidecar(
    host: str,
    port: int,
    timeout: int = 90,
) -> tuple[bool, float]:
    """
    Poll the sidecar /health endpoint until VPN is up or timeout expires.
    Returns (success, elapsed_seconds).
    """
    url   = f'http://{host}:{port}/health'
    start = time.time()
    # Give sidecar a moment to boot
    time.sleep(5)
    deadline = start + timeout
    while time.time() < deadline:
        try:
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200 and resp.json().get('vpn'):
                return True, round(time.time() - start, 1)
        except Exception:
            pass
        time.sleep(3)
    return False, round(time.time() - start, 1)


def run_sidecar_test(
    host: str,
    port: int,
    duration: int = 8,
    streams: int = 4,
    method: str = 'auto',
) -> dict:
    """
    Call the sidecar /test endpoint and return the result dict.
    Raises RuntimeError if the call fails.
    """
    url  = f'http://{host}:{port}/test'
    timeout = duration * 2 + 60  # generous timeout
    resp = requests.post(
        url,
        params={'duration': duration, 'streams': streams, 'method': method},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()


def cleanup_test_containers(sidecar_image: str | None = None) -> None:
    """Stop and remove the test Gluetun and sidecar containers, then delete the sidecar image."""
    client = docker.from_env()
    for name in [_SIDECAR_NAME, _TEST_GLUETUN_NAME]:
        _remove_container(client, name)
    if sidecar_image:
        try:
            client.images.remove(sidecar_image, force=True)
            logger.info('Sidecar image removed: %s', sidecar_image)
        except Exception as exc:
            logger.debug('Could not remove sidecar image: %s', exc)
    logger.info('Test containers cleaned up')


def wait_for_vpn(
    proxy_host: str,
    proxy_port: int,
    timeout: int = 60,
    proxy_user: str | None = None,
    proxy_password: str | None = None,
) -> tuple[bool, float]:
    """
    Wait until the VPN proxy is responsive or timeout expires.
    Returns (success, elapsed_seconds) where elapsed includes the initial sleep.
    """
    start = time.time()
    time.sleep(4)
    deadline = start + timeout
    while time.time() < deadline:
        try:
            resp = _probe(proxy_host, proxy_port, proxy_user, proxy_password)
            if resp.status_code == 200:
                return True, round(time.time() - start, 1)
        except Exception:
            pass
        time.sleep(3)
    return False, round(time.time() - start, 1)
