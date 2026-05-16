import os
import subprocess
import time
import logging

import docker
import requests

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Docker helpers
# ---------------------------------------------------------------------------

def _docker():
    return docker.from_env()


def get_current_server(container_name: str) -> str | None:
    """Read SERVER_NAMES from the running gluetun container environment."""
    try:
        container = _docker().containers.get(container_name)
        for var in container.attrs['Config'].get('Env') or []:
            if var.startswith('SERVER_NAMES='):
                return var.split('=', 1)[1]
    except Exception as e:
        logger.warning('get_current_server: %s', e)
    return None


def switch_server(
    server_name: str,
    container_name: str,
    compose_dir: str,
    compose_project: str = '',
) -> tuple[bool, str | None]:
    """
    Write a docker-compose.override.yml that overrides SERVER_NAMES, then
    run `docker compose up -d --force-recreate <container>`.

    Returns (success, error_message).
    """
    override_path = os.path.join(compose_dir, 'docker-compose.override.yml')
    service_name = container_name  # compose service name == container name in most setups

    override = (
        f'services:\n'
        f'  {service_name}:\n'
        f'    environment:\n'
        f'      SERVER_NAMES: "{server_name}"\n'
    )
    try:
        with open(override_path, 'w') as fh:
            fh.write(override)
    except OSError as e:
        return False, f'Cannot write override file: {e}'

    cmd = ['docker', 'compose']
    if compose_project:
        cmd += ['-p', compose_project]
    cmd += ['up', '-d', '--force-recreate', service_name]

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
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# Gluetun API helpers
# ---------------------------------------------------------------------------

def _api_get(gluetun_host: str, api_port: int, path: str, timeout: int = 5):
    url = f'http://{gluetun_host}:{api_port}{path}'
    return requests.get(url, timeout=timeout)


def get_vpn_status(gluetun_host: str, api_port: int) -> str:
    """Return 'running', 'stopped', or 'unknown'."""
    try:
        resp = _api_get(gluetun_host, api_port, '/v1/openvpn/status')
        if resp.status_code == 200:
            return resp.json().get('status', 'unknown')
    except Exception:
        pass
    return 'unknown'


def get_public_ip(gluetun_host: str, api_port: int) -> str | None:
    try:
        resp = _api_get(gluetun_host, api_port, '/v1/publicip/ip', timeout=8)
        if resp.status_code == 200:
            return resp.json().get('public_ip')
    except Exception:
        pass
    return None


def wait_for_vpn(gluetun_host: str, api_port: int, timeout: int = 60) -> bool:
    """Poll gluetun API until VPN status is 'running' or timeout."""
    deadline = time.time() + timeout
    # Give the container a moment to restart
    time.sleep(3)
    while time.time() < deadline:
        try:
            status = get_vpn_status(gluetun_host, api_port)
            if status == 'running':
                return True
        except Exception:
            pass
        time.sleep(3)
    return False
