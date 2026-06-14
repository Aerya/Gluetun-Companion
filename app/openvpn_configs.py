"""Manage custom OpenVPN configuration files shared with Gluetun."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path, PurePosixPath

import docker
from werkzeug.utils import secure_filename

from .database import get_setting, set_setting


logger = logging.getLogger(__name__)

_SCANNER_NAME = 'gluetun-companion-openvpn-scanner'
_ALLOWED_SUFFIXES = {'.ovpn', '.conf'}
_MAX_FILE_SIZE = 2 * 1024 * 1024


def _safe_name(filename: str) -> str:
    name = secure_filename(filename or '')
    if not name or Path(name).suffix.lower() not in _ALLOWED_SUFFIXES:
        raise ValueError('Le fichier doit utiliser l’extension .ovpn ou .conf.')
    return name


def save_uploaded_config(file_storage, config_dir: str) -> str:
    """Validate and save an uploaded OpenVPN configuration."""
    name = _safe_name(file_storage.filename)
    data = file_storage.stream.read(_MAX_FILE_SIZE + 1)
    if not data:
        raise ValueError('Le fichier OpenVPN est vide.')
    if len(data) > _MAX_FILE_SIZE:
        raise ValueError('Le fichier OpenVPN dépasse la limite de 2 Mio.')
    target_dir = Path(config_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / name
    if target.is_symlink():
        raise ValueError('Le fichier cible ne peut pas être un lien symbolique.')
    target.write_bytes(data)
    try:
        target.chmod(0o600)
    except OSError:
        pass
    return name


def _remove_scanner(client) -> None:
    try:
        client.containers.get(_SCANNER_NAME).remove(force=True)
    except docker.errors.NotFound:
        pass


def scan_gluetun_configs(container_name: str) -> list[str]:
    """List OpenVPN files mounted in Gluetun without using Docker exec."""
    client = docker.from_env()
    _remove_scanner(client)
    image = get_setting('sidecar_image', 'ghcr.io/aerya/gluetun-companion-sidecar:latest')
    client.images.pull(image)
    command = (
        "find /gluetun -type f \\( -iname '*.ovpn' -o -iname '*.conf' \\) "
        "-print 2>/dev/null | sort"
    )
    scanner = None
    try:
        scanner = client.containers.run(
            image=image,
            name=_SCANNER_NAME,
            volumes_from=[f'{container_name}:ro'],
            command=['sh', '-c', command],
            detach=True,
            remove=False,
        )
        deadline = time.time() + 30
        while time.time() < deadline:
            scanner.reload()
            if scanner.status in ('exited', 'dead'):
                break
            time.sleep(0.5)
        else:
            raise TimeoutError('OpenVPN configuration scan timed out')
        exit_code = int(scanner.attrs.get('State', {}).get('ExitCode', 1))
        output = scanner.logs(stdout=True, stderr=True).decode('utf-8', errors='replace')
        if exit_code != 0:
            raise RuntimeError(f'OpenVPN scanner exited with code {exit_code}: {output.strip()}')
        paths = sorted({
            line.strip() for line in output.splitlines()
            if line.strip().startswith('/gluetun/')
            and PurePosixPath(line.strip()).suffix.lower() in _ALLOWED_SUFFIXES
        })
        set_setting('openvpn_discovered_configs', json.dumps(paths))
        return paths
    finally:
        if scanner is not None:
            try:
                scanner.remove(force=True)
            except Exception as exc:
                logger.debug('Could not remove OpenVPN scanner: %s', exc)


def list_openvpn_configs(config_dir: str, container_dir: str) -> list[dict[str, object]]:
    """Combine uploaded files and the latest Gluetun volume scan."""
    configs: dict[str, dict[str, object]] = {}
    local_dir = Path(config_dir)
    if local_dir.is_dir():
        for path in sorted(local_dir.iterdir()):
            if path.is_file() and path.suffix.lower() in _ALLOWED_SUFFIXES:
                container_path = str(PurePosixPath(container_dir) / path.name)
                configs[container_path] = {
                    'name': path.name,
                    'path': container_path,
                    'uploaded': True,
                    'size': path.stat().st_size,
                }
    try:
        discovered = json.loads(get_setting('openvpn_discovered_configs', '[]') or '[]')
    except (TypeError, ValueError):
        discovered = []
    for raw_path in discovered if isinstance(discovered, list) else []:
        path = str(raw_path)
        if path.startswith('/gluetun/') and PurePosixPath(path).suffix.lower() in _ALLOWED_SUFFIXES:
            configs.setdefault(path, {
                'name': PurePosixPath(path).name,
                'path': path,
                'uploaded': False,
                'size': None,
            })
    return sorted(configs.values(), key=lambda item: str(item['path']).lower())


def validate_import_path(path: str, configs: list[dict[str, object]]) -> str:
    allowed = {str(config['path']) for config in configs}
    if path not in allowed:
        raise ValueError('Configuration OpenVPN introuvable. Relancez la détection.')
    return path
