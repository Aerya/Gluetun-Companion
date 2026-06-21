"""
Gluetun container control + VPN connectivity helpers.

Network architecture (no shared Docker network required)
---------------------------------------------------------
- Docker socket  → read container env (current filters), switch server via
                   docker compose up -d <service> (only the Gluetun service,
                   so Companion is never inadvertently restarted).
- Proxy port     → VPN status check, public IP, wait loop.
                   The proxy is exposed on the host so the companion reaches it
                   via host.docker.internal (see docker-compose.yml extra_hosts).
"""

import json
import os
import subprocess
import threading
import time
import logging
from urllib.parse import quote

import docker
import requests

from .database import get_setting

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
# Companion-triggered restart suppression
# ---------------------------------------------------------------------------
# When Companion itself triggers a Gluetun restart (server switch), we open a
# suppression window so the Docker event listener does not mistake it for an
# external restart and fire a spurious quick check.

_companion_lock            = threading.Lock()
_companion_restart_until: float = 0.0


def mark_companion_restart(suppress_secs: float = 180.0) -> None:
    """
    Call immediately before Companion triggers a Gluetun restart (server switch).
    The window must cover the full ``connection_wait_seconds`` reconnect time.
    """
    global _companion_restart_until
    with _companion_lock:
        _companion_restart_until = time.time() + suppress_secs
    logger.debug('Companion restart window set for %.0fs', suppress_secs)


def is_companion_restart() -> bool:
    """Return True if we are inside a Companion-triggered restart suppression window."""
    with _companion_lock:
        return time.time() < _companion_restart_until


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


def get_container_env(container_name: str) -> dict[str, str]:
    """Public, read-only access to a container's environment variables."""
    return _container_env(container_name)


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


def _detect_compose_service(container_name: str) -> str:
    """
    Read the compose service name from the container's Docker labels.
    Docker Compose sets com.docker.compose.service on every managed container.
    Falls back to container_name if the label is absent.
    """
    try:
        container = docker.from_env().containers.get(container_name)
        service = container.labels.get('com.docker.compose.service', '')
        if service:
            logger.debug('Detected compose service: %s', service)
            return service
    except Exception as exc:
        logger.warning('_detect_compose_service: %s', exc)
    return container_name


# ---------------------------------------------------------------------------
# Control-backend detection
# ---------------------------------------------------------------------------
# Companion drives Gluetun differently depending on how the container is
# managed.  Compose stacks are recreated with ``docker compose up -d``.  Unraid's
# Docker Manager (``net.unraid.docker.managed=dockerman``) has no compose
# project, so the container is recreated from its Unraid template instead.
# Detection is automatic per container; the ``CONTROL_BACKEND`` environment
# variable (``auto`` | ``compose`` | ``unraid``) forces a backend when needed.

CONTROL_BACKEND_COMPOSE = 'compose'
CONTROL_BACKEND_UNRAID = 'unraid'


def _control_backend_override() -> str:
    """Return a forced control backend from the environment, or '' for auto."""
    value = (os.environ.get('CONTROL_BACKEND', '') or '').strip().lower()
    return value if value in (CONTROL_BACKEND_COMPOSE, CONTROL_BACKEND_UNRAID) else ''


def _management_mode(container_name: str) -> str:
    """Return the control backend for *container_name*: 'compose' or 'unraid'.

    Resolution order (first match wins):
      1. ``CONTROL_BACKEND`` override (``compose``/``unraid``), when set;
      2. a ``com.docker.compose.project`` label        → ``compose``;
      3. ``net.unraid.docker.managed=dockerman`` label → ``unraid``;
      4. default                                        → ``compose``
         (preserves the historical behaviour for plain ``docker run`` setups).
    """
    override = _control_backend_override()
    if override:
        return override
    try:
        labels = docker.from_env().containers.get(container_name).labels or {}
    except Exception as exc:
        logger.warning('_management_mode(%s): %s — defaulting to compose', container_name, exc)
        return CONTROL_BACKEND_COMPOSE
    if labels.get('com.docker.compose.project'):
        return CONTROL_BACKEND_COMPOSE
    if (labels.get('net.unraid.docker.managed') or '').strip().lower() == 'dockerman':
        return CONTROL_BACKEND_UNRAID
    return CONTROL_BACKEND_COMPOSE


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
    """Human-readable representation of active filter values, without Gluetun env prefixes."""
    if not filters:
        return '—'
    labels: list[str] = []
    for value in filters.values():
        labels.extend(part.strip() for part in str(value).split(',') if part.strip())
    return ' · '.join(labels) if labels else '—'


def _managed_env_pairs(
    filter_value: str,
    filter_type: str,
    wg_profile: 'dict | None',
) -> list[tuple[str, str]]:
    """Compute the ordered (key, value) env vars Companion manages for a switch.

    Single source of truth shared by every control backend (Compose override,
    Unraid template recreate) so they all write exactly the same values and can
    never diverge.  Values are RAW — each backend escapes them for its own
    target format (YAML double-quoted, XML text, …).

    Order (kept stable so the Compose override output is unchanged):
      1. every SERVER_* filter var — the target one set to *filter_value*,
         all others blanked so base-compose values cannot conflict;
      2. DNS filtering (BLOCK_MALICIOUS, DNS_UNBLOCK_HOSTNAMES);
      3. when *wg_profile* is given: VPN_SERVICE_PROVIDER, VPN_TYPE, the profile
         credential vars, then every other known credential key blanked (so a
         previous provider's secret cannot leak into the new session).
    """
    env_var = FILTER_VARS.get(filter_type, 'SERVER_NAMES')

    compose_provider = ''
    vpn_type = 'wireguard'
    profile_vars: dict[str, str] = {}
    if wg_profile:
        compose_provider = wg_profile.get('compose_provider', '')
        if wg_profile.get('vars') is not None:
            profile_vars = dict(wg_profile.get('vars') or {})
        else:
            profile_vars = dict(wg_profile.get('extra_env') or {})
        compose_provider = compose_provider or profile_vars.get('VPN_SERVICE_PROVIDER', '')
        vpn_type = (
            wg_profile.get('vpn_type')
            or profile_vars.get('VPN_TYPE')
            or 'wireguard'
        )

        # These values are generated explicitly below. Profiles imported from
        # older code paths can still contain them, which would otherwise emit
        # duplicate keys.
        managed_vars = {
            'VPN_SERVICE_PROVIDER',
            'VPN_TYPE',
            *FILTER_VARS.values(),
        }
        profile_vars = {
            key: value for key, value in profile_vars.items()
            if key not in managed_vars
        }

    uses_server_filter = compose_provider != 'custom'

    pairs: list[tuple[str, str]] = []

    # Set the target filter var, blank-out all others.
    for label, var in FILTER_VARS.items():
        raw = filter_value if uses_server_filter and var == env_var else ''
        pairs.append((var, raw))

    # DNS filtering is managed by Companion as well, so the user's choice
    # survives every regenerated override and provider/server switch.
    try:
        dns_block_malicious = get_setting('dns_block_malicious', '1')
        dns_unblock_hostnames = get_setting('dns_unblock_hostnames', '')
    except Exception:
        # Keep standalone uses and early-startup recovery aligned with
        # Gluetun's own secure default if the settings DB is unavailable.
        dns_block_malicious = '1'
        dns_unblock_hostnames = ''
    pairs.append(('BLOCK_MALICIOUS', 'on' if dns_block_malicious == '1' else 'off'))
    pairs.append(('DNS_UNBLOCK_HOSTNAMES', dns_unblock_hostnames))

    # VPN profile vars (provider + type + credentials).
    if wg_profile:
        if compose_provider:
            pairs.append(('VPN_SERVICE_PROVIDER', compose_provider))
        pairs.append(('VPN_TYPE', vpn_type))
        for k, v in profile_vars.items():
            pairs.append((k, v))
        # Blank every known credential var the profile does not set, so values
        # inherited from the base compose file (another provider/type) cannot
        # leak into the new session (e.g. AirVPN preshared key on Mullvad).
        from .wg_providers import all_credential_keys
        for k in sorted(all_credential_keys() - set(profile_vars)):
            pairs.append((k, ''))

    return pairs


def switch_server(
    filter_value: str,
    filter_type: str,
    container_name: str,
    compose_dir: str,
    compose_project: str = '',
    wg_profile: 'dict | None' = None,
) -> tuple[bool, str | None]:
    """
    Write a docker-compose.override.yml that sets the correct Gluetun filter
    variable to `filter_value` and clears all other filter variables (so they
    don't conflict with values from the main compose file).

    If *wg_profile* is provided, it must be a dict with:
        compose_provider : str   — value of VPN_SERVICE_PROVIDER (e.g. "airvpn")
        vpn_type         : str   — 'wireguard' (default) or 'openvpn'
        vars             : dict  — credential env vars, secrets already decrypted
                                   e.g. {"WIREGUARD_PRIVATE_KEY": "...", ...}
                                   or   {"OPENVPN_USER": "...", ...}

    When *wg_profile* is provided, VPN_SERVICE_PROVIDER, VPN_TYPE and all
    profile vars are also written to the override so that Gluetun switches
    both the server filter AND the credentials in a single restart.  Every
    known credential var NOT set by the profile is blanked out so that values
    from the base compose file (e.g. another provider's preshared key) cannot
    leak into the new session.
    For VPN_SERVICE_PROVIDER=custom, Gluetun has no SERVER_* selector; all
    SERVER_* vars are cleared and the server name is only used as a stats label.

    Returns (success, error_message).
    """
    # Resolve project and service name BEFORE writing the override so that the
    # YAML key matches the actual Compose service name (which may differ from
    # the container_name when an explicit container_name: is set in the compose).
    project = compose_project or _detect_compose_project(container_name)
    service = _detect_compose_service(container_name)

    def _safe(raw: str) -> str:
        """Sanitise a value against YAML injection."""
        return raw.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '').replace('\r', '')

    # Managed env vars (server filters + DNS + VPN profile) come from the single
    # shared builder so every control backend writes exactly the same values.
    env_lines = ''.join(
        f'      {key}: "{_safe(value)}"\n'
        for key, value in _managed_env_pairs(filter_value, filter_type, wg_profile)
    )

    # Use the Compose service name (not the container name) as the YAML key so
    # that the override is applied to the correct service even when service name
    # and container_name differ.
    override = (
        f'services:\n'
        f'  {service}:\n'
        f'    environment:\n'
        f'{env_lines}'
    )
    override_path = os.path.join(compose_dir, 'docker-compose.override.yml')
    try:
        with open(override_path, 'w') as fh:
            fh.write(override)
    except OSError as exc:
        return False, f'Cannot write override file: {exc}'

    # Pass only the gluetun service name so that Compose recreates exclusively
    # that service.  This prevents the Companion (or any other service in the
    # same stack) from being inadvertently restarted.
    # Network-dependent containers (network_mode: service:gluetun) are handled
    # separately by restart_network_dependents() once the VPN is confirmed up.
    cmd = ['docker', 'compose']
    if project:
        cmd += ['-p', project]
    cmd += ['up', '-d', service]

    # Tell the Docker event listener this restart is Companion-initiated so it
    # does not trigger a spurious quick check on the resulting 'start' event.
    mark_companion_restart()

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


def apply_dns_filtering(
    container_name: str,
    compose_dir: str,
    block_malicious: bool,
    unblock_hostnames: str = '',
    compose_project: str = '',
) -> tuple[bool, str | None]:
    """Persist DNS filtering values in Companion's override and recreate Gluetun."""
    service = _detect_compose_service(container_name)
    project = compose_project or _detect_compose_project(container_name)
    override_path = os.path.join(compose_dir, 'docker-compose.override.yml')

    def _safe(raw: str) -> str:
        return raw.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '').replace('\r', '')

    values = {
        'BLOCK_MALICIOUS': 'on' if block_malicious else 'off',
        'DNS_UNBLOCK_HOSTNAMES': unblock_hostnames,
    }

    try:
        network_dependents = list_network_dependents_for_recreate(container_name)
    except Exception as exc:
        logger.warning('Unable to list network dependents before DNS update: %s', exc)
        network_dependents = []

    try:
        if os.path.exists(override_path):
            with open(override_path, encoding='utf-8') as fh:
                lines = fh.readlines()
        else:
            lines = ['services:\n', f'  {service}:\n', '    environment:\n']

        environment_idx = next(
            (i for i, line in enumerate(lines) if line.rstrip() == '    environment:'),
            None,
        )
        if environment_idx is None:
            service_idx = next(
                (i for i, line in enumerate(lines) if line.rstrip() == f'  {service}:'),
                None,
            )
            if service_idx is None:
                if lines and not lines[-1].endswith('\n'):
                    lines[-1] += '\n'
                lines.extend([f'  {service}:\n', '    environment:\n'])
                environment_idx = len(lines) - 1
            else:
                lines.insert(service_idx + 1, '    environment:\n')
                environment_idx = service_idx + 1

        for key, value in values.items():
            replacement = f'      {key}: "{_safe(value)}"\n'
            existing_idx = next(
                (i for i, line in enumerate(lines) if line.lstrip().startswith(f'{key}:')),
                None,
            )
            if existing_idx is None:
                environment_idx += 1
                lines.insert(environment_idx, replacement)
            else:
                lines[existing_idx] = replacement

        tmp_path = override_path + '.tmp'
        with open(tmp_path, 'w', encoding='utf-8', newline='\n') as fh:
            fh.writelines(lines)
        os.replace(tmp_path, override_path)
    except OSError as exc:
        return False, f'Cannot write override file: {exc}'

    cmd = ['docker', 'compose']
    if project:
        cmd += ['-p', project]
    cmd += ['up', '-d', service]
    mark_companion_restart()
    try:
        result = subprocess.run(
            cmd, cwd=compose_dir, capture_output=True, text=True, timeout=90,
        )
        if result.returncode != 0:
            return False, (result.stderr or result.stdout or 'unknown error').strip()
        if network_dependents:
            restart_network_dependents(
                container_name,
                compose_dir,
                project,
                explicit_list=network_dependents,
            )
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

def _compose_recreate(
    container_name: str,
    compose_dir: str = '',
    compose_project: str = '',
) -> None:
    """
    Recreate a container via ``docker compose up -d --force-recreate <service>``
    so that it re-attaches to the correct (possibly new) network namespace.

    When a container uses ``network_mode: service:X`` and X has just been
    recreated (new container ID), a plain ``docker restart`` fails with
    "joining network namespace … No such container".  Running
    ``docker compose up -d --force-recreate <service>`` lets Compose resolve
    the *current* container ID for X and recreate the dependent properly.

    Candidate strategy (tried in order, first success wins):
      1. Container's own ``com.docker.compose.project.working_dir`` label —
         correct for containers in a *different* Compose stack than Gluetun.
         Works when that stack's directory is mounted inside the Companion
         container, or when running Companion bare-metal.
      2. Caller-supplied ``compose_dir`` — Gluetun's own compose directory,
         which is always mounted inside the Companion container.  Correct for
         containers in the *same* stack as Gluetun.
      3. Plain ``docker restart`` — last resort; may fail if the parent
         container was recreated (stale namespace reference).
    """
    client = docker.from_env()
    c = client.containers.get(container_name)
    labels  = c.labels
    service = labels.get('com.docker.compose.service', '') or container_name

    own_work_dir = labels.get('com.docker.compose.project.working_dir', '')
    own_project  = labels.get('com.docker.compose.project', '')

    # Build (work_dir, project) candidates in priority order.
    candidates: list[tuple[str, str]] = []
    if own_work_dir:
        candidates.append((own_work_dir, own_project or compose_project))
    if compose_dir and compose_dir != own_work_dir:
        candidates.append((compose_dir, compose_project or own_project))

    last_err = ''
    for work_dir, project in candidates:
        # The candidate's compose dir may not be mounted inside the Companion
        # container (cross-stack dependent) — skip to the next candidate
        # instead of letting subprocess raise and abort the whole loop.
        if work_dir and not os.path.isdir(work_dir):
            last_err = f'compose dir not accessible from Companion: {work_dir}'
            logger.warning(
                'Compose recreate attempt skipped for %s: %s — trying next candidate',
                container_name, last_err,
            )
            continue
        cmd = ['docker', 'compose']
        if project:
            cmd += ['-p', project]
        cmd += ['up', '-d', '--force-recreate', service]
        logger.info(
            'Recreating %s via compose: %s (cwd=%s)',
            container_name, ' '.join(cmd), work_dir,
        )
        try:
            result = subprocess.run(
                cmd,
                cwd=work_dir,
                capture_output=True,
                text=True,
                timeout=90,
            )
        except subprocess.TimeoutExpired:
            last_err = 'docker compose timed out after 90s'
            logger.warning(
                'Compose recreate attempt failed for %s (cwd=%s): %s — trying next candidate',
                container_name, work_dir, last_err,
            )
            continue
        except OSError as exc:   # missing docker binary, bad cwd race, etc.
            last_err = str(exc)
            logger.warning(
                'Compose recreate attempt failed for %s (cwd=%s): %s — trying next candidate',
                container_name, work_dir, last_err,
            )
            continue
        if result.returncode == 0:
            return   # success
        last_err = (result.stderr or result.stdout or 'unknown error').strip()
        logger.warning(
            'Compose recreate attempt failed for %s (cwd=%s): %s — trying next candidate',
            container_name, work_dir, last_err,
        )

    if candidates:
        # All compose attempts failed
        raise RuntimeError(f'docker compose up failed for {container_name}: {last_err}')

    # No compose info at all — plain restart (may fail for network-dependent
    # containers after their parent was recreated)
    logger.warning(
        'No compose dir for %s — falling back to plain restart '
        '(may fail if using network_mode: service:X)',
        container_name,
    )
    c.restart(timeout=15)


def restart_network_dependents(
    container_name: str,
    compose_dir: str = '',
    compose_project: str = '',
    exclude: set[str] | None = None,
    pull_set: set[str] | None = None,
    explicit_list: list[str] | None = None,
) -> tuple[list[str], list[str]]:
    """
    Find and recreate every container whose NetworkMode references
    ``container_name`` (i.e. ``network_mode: service:<container_name>`` in
    Compose).  Called after the VPN is confirmed up so the dependents
    re-attach to the live network namespace.

    Docker stores the NetworkMode as ``container:<id>`` (old container ID) or
    ``container:<name>`` depending on the Compose version.  We match both by
    inspecting every running (or errored) container.

    ``compose_dir`` / ``compose_project`` should be the same values used for
    the gluetun service — they are already mounted/known inside the companion
    container and let us call ``docker compose up -d --force-recreate``.

    ``exclude`` — container names to skip (e.g. those paused before the
    benchmark; they will be restarted separately at benchmark end).

    ``explicit_list`` — when provided, use this pre-captured list instead of
    auto-detecting.  Pass the result of ``list_network_dependents()`` called
    *before* switching Gluetun so that containers whose NetworkMode references
    the old Gluetun container ID (stored at creation time) are not missed.

    Returns (restarted_names, updated_image_names).
    """
    restarted: list[str] = []
    updated_imgs: list[str] = []
    exclude_set = set(exclude) if exclude else set()

    # Build the list of container names to restart
    if explicit_list is not None:
        # Use the pre-captured list (avoids missing containers with stale Gluetun IDs)
        names_to_restart = [n for n in explicit_list if n not in exclude_set]
        for n in explicit_list:
            if n in exclude_set:
                logger.info(
                    'Skipping network-dependent %s (paused — will restart at benchmark end)', n
                )
    else:
        # Auto-detect: match by current container name or ID.
        # NOTE: this misses containers whose NetworkMode was stored with an older
        # Gluetun container ID (before the switch).  Prefer passing explicit_list.
        names_to_restart = []
        try:
            client = docker.from_env()
            try:
                gluetun    = client.containers.get(container_name)
                gluetun_id = gluetun.id
            except Exception:
                gluetun_id = ''
            name_target = f'container:{container_name}'
            id_target   = f'container:{gluetun_id}' if gluetun_id else None
            for c in client.containers.list(all=True):
                mode = c.attrs['HostConfig'].get('NetworkMode', '')
                if mode == name_target or (id_target and mode == id_target):
                    if c.name in exclude_set:
                        logger.info(
                            'Skipping network-dependent %s (paused — will restart at benchmark end)',
                            c.name,
                        )
                        continue
                    names_to_restart.append(c.name)
        except Exception as exc:
            logger.warning('restart_network_dependents (detect): %s', exc)

    # Restart each container
    for name in names_to_restart:
        logger.info('Recreating network-dependent container: %s', name)
        try:
            if pull_set and name in pull_set:
                ok, updated, img = pull_image(name)
                logger.info('  pull %s: %s%s', img, 'updated' if updated else 'up to date', '' if ok else ' (failed)')
                if updated:
                    updated_imgs.append(img)
            _compose_recreate(name, compose_dir, compose_project)
            restarted.append(name)
        except Exception as exc:
            logger.warning('Failed to recreate %s: %s', name, exc)

    return restarted, updated_imgs


def stop_containers(container_names: list[str]) -> list[str]:
    """
    Gracefully stop the named containers (without removing them) so that
    benchmark speed tests are not distorted by concurrent download traffic.

    Already-stopped containers are skipped without error.
    Returns the list of containers that were in a running state and got stopped
    (plus those already stopped — all are counted as "handled" so the caller
    knows they should be restarted afterwards).
    """
    handled: list[str] = []
    names = [n.strip() for n in container_names if n and n.strip()]
    if not names:
        return handled
    try:
        client = docker.from_env()
        for name in names:
            try:
                c = client.containers.get(name)
                if c.status == 'running':
                    logger.info('Pausing container before benchmark: %s', name)
                    c.stop(timeout=30)
                else:
                    logger.info(
                        'Container %s already stopped (status: %s) — skipping',
                        name, c.status,
                    )
                handled.append(name)
            except Exception as exc:
                logger.warning('Failed to stop container %s: %s', name, exc)
    except Exception as exc:
        logger.warning('stop_containers: %s', exc)
    return handled


def start_stopped_containers(
    container_names: list[str],
    compose_dir: str = '',
    compose_project: str = '',
    pull_set: set[str] | None = None,
) -> list[str]:
    """
    Start containers that were previously stopped (but not removed) via
    ``stop_containers()``.

    Strategy (handles both network-independent and network-dependent containers):
    1. Detect containers that use ``network_mode: service:<parent>`` (stored as
       ``NetworkMode: container:<id-or-name>``).  After the parent (Gluetun) has
       been **recreated**, a plain ``docker start`` either errors with "no such
       container" or silently starts then immediately exits because the stored
       container ID is stale.  These containers go **directly** to
       ``docker compose up -d --force-recreate`` so Compose resolves the current
       parent ID.
    2. All other containers: try a plain ``docker start`` first.  If that fails,
       fall back to ``docker compose up -d --force-recreate``.

    Returns the list of container names that were successfully started.
    """
    started: list[str] = []
    names = [n.strip() for n in container_names if n and n.strip()]
    if not names:
        return started
    try:
        client = docker.from_env()
        for name in names:
            try:
                c = client.containers.get(name)
                logger.info('Starting paused container: %s (status: %s)', name, c.status)
                if c.status != 'running':
                    if pull_set and name in pull_set:
                        ok, updated, img = pull_image(name)
                        logger.info('  pull %s: %s%s', img, 'updated' if updated else 'up to date', '' if ok else ' (failed)')
                    # Containers that share a network namespace via
                    # "network_mode: service:<parent>" are stored with
                    # NetworkMode = "container:<id-or-name>".  After the parent
                    # (Gluetun) has been *recreated* the old container ID is gone,
                    # so a plain "docker start" either fails with "no such
                    # container" or, worse, silently starts then immediately exits.
                    # Skip straight to compose recreate for these containers.
                    network_mode = c.attrs.get('HostConfig', {}).get('NetworkMode', '')
                    is_net_dependent = (
                        network_mode.startswith('container:')
                        or network_mode.startswith('service:')
                    )
                    container_project = c.labels.get('com.docker.compose.project', '')
                    if is_net_dependent:
                        logger.info(
                            '%s uses NetworkMode %r — using compose recreate directly '
                            '(skipping docker start after parent recreation)',
                            name, network_mode,
                        )
                        # Use the Companion's mounted compose_dir when available.
                        # If compose_project is unset, derive the project name from
                        # the container's own label (avoids using host-side paths
                        # from com.docker.compose.project.working_dir that are
                        # inaccessible from inside the Companion container).
                        if compose_dir and (not compose_project or container_project == compose_project):
                            effective_project = compose_project or container_project
                            logger.info(
                                '%s — compose recreate with dir=%r project=%r',
                                name, compose_dir, effective_project,
                            )
                            _compose_recreate(name, compose_dir, effective_project)
                        else:
                            logger.info(
                                '%s is in project %r (not %r) — using container labels for recreate',
                                name, container_project, compose_project,
                            )
                            _compose_recreate(name, '', '')
                    else:
                        try:
                            c.start()
                        except Exception as start_exc:
                            # Plain start failed — try compose recreate as fallback.
                            logger.warning(
                                'docker start failed for %s (%s) — trying compose recreate',
                                name, start_exc,
                            )
                            # Only use the caller's compose context (Gluetun's stack)
                            # if the container belongs to the same compose project.
                            if compose_project and container_project == compose_project:
                                _compose_recreate(name, compose_dir, compose_project)
                            else:
                                logger.info(
                                    '%s is in project %r (not %r) — using container labels for recreate',
                                    name, container_project, compose_project,
                                )
                                _compose_recreate(name, '', '')
                started.append(name)
                logger.info('Started paused container: %s OK', name)
            except Exception as exc:
                logger.warning('Failed to start paused container %s: %s', name, exc)
    except Exception as exc:
        logger.warning('start_stopped_containers: %s', exc)
    return started


def pull_image(container_name: str) -> tuple[bool, bool, str]:
    """
    Pull the latest version of the image used by *container_name*.
    Returns (success, updated, image_name).
    *updated* is True when the local image digest changed after the pull.
    """
    try:
        client = docker.from_env()
        c = client.containers.get(container_name)
        image_name = c.attrs['Config']['Image']
        old_id     = c.attrs['Image']          # sha256 of current image
        new_image  = client.images.pull(image_name)
        new_id     = new_image.id
        updated    = old_id != new_id
        if updated:
            logger.info('Image updated for %s: %s', container_name, image_name)
        else:
            logger.info('Image already up to date for %s: %s', container_name, image_name)
        return True, updated, image_name
    except Exception as exc:
        logger.warning('pull_image %s: %s', container_name, exc)
        return False, False, str(exc)


def record_gluetun_id(container_id: str) -> None:
    """Remember a Gluetun container ID in the persistent history.

    The history is what lets ``list_orphaned_network_dependents`` distinguish
    "dependent of a *former Gluetun*" from "dependent of some unrelated dead
    container" (e.g. a second VPN stack the user runs) — Companion must never
    adopt and recreate containers outside its own scope.

    Capped at the 25 most recent IDs.  No-op if the ID is already recorded.
    """
    if not container_id:
        return
    try:
        from .database import get_setting, set_setting
        history = json.loads(get_setting('gluetun_id_history', '[]') or '[]')
        if not isinstance(history, list):
            history = []
        if container_id in history:
            return
        history.append(container_id)
        set_setting('gluetun_id_history', json.dumps(history[-25:]))
    except Exception as exc:
        logger.debug('record_gluetun_id: %s', exc)


def _known_gluetun_ids() -> set[str]:
    """Return the recorded Gluetun IDs, both full and short (12-char) forms."""
    try:
        from .database import get_setting
        history = json.loads(get_setting('gluetun_id_history', '[]') or '[]')
        if not isinstance(history, list):
            return set()
        ids = {str(i) for i in history if i}
        return ids | {i[:12] for i in ids}
    except Exception:
        return set()


def list_network_dependents(container_name: str) -> list[str]:
    """
    Return the sorted names of all containers that use
    ``network_mode: service:<container_name>`` (i.e. share Gluetun's namespace).
    Read-only — does not restart anything.
    """
    result: list[str] = []
    try:
        client = docker.from_env()
        try:
            gluetun    = client.containers.get(container_name)
            gluetun_id = gluetun.id
            record_gluetun_id(gluetun_id)   # keep the ID history fresh
        except Exception:
            gluetun_id = ''
        name_target = f'container:{container_name}'
        id_target   = f'container:{gluetun_id}' if gluetun_id else None
        for c in client.containers.list(all=True):
            mode = c.attrs['HostConfig'].get('NetworkMode', '')
            if mode == name_target or (id_target and mode == id_target):
                result.append(c.name)
    except Exception as exc:
        logger.warning('list_network_dependents: %s', exc)
    return sorted(result)


def list_network_dependents_for_recreate(container_name: str) -> list[str]:
    """
    Extended version of ``list_network_dependents`` for use as a pre-switch
    capture.  Returns the union of:

    * Containers that currently reference ``container_name`` by name or ID
      (the normal case — Gluetun hasn't been recreated yet).
    * Containers whose NetworkMode references a **dead** container ID
      (orphaned from a previous Gluetun recreate that didn't fix dependents).

    The second set handles the scenario where a previous switch failed to
    recreate the dependents (VPN timeout, compose error, etc.) — leaving them
    with a stale container reference (``SandboxKey`` empty).  Without this,
    ``list_network_dependents`` returns ``[]`` for already-broken dependents
    and the next switch silently skips them again.
    """
    current  = set(list_network_dependents(container_name))
    orphaned = set(list_orphaned_network_dependents())
    combined = sorted(current | orphaned)
    if orphaned - current:
        logger.info(
            'list_network_dependents_for_recreate: also including %d already-orphaned '
            'container(s) in pre-switch list: %s',
            len(orphaned - current),
            ', '.join(sorted(orphaned - current)),
        )
    return combined


def list_orphaned_network_dependents() -> list[str]:
    """
    Find containers whose network namespace is broken because they reference a
    stale container ID in their NetworkMode (``container:<dead-id>``).

    Called after an **external** Gluetun restart: the old container is gone, so
    ``list_network_dependents`` (which matches by current name/ID) would return
    nothing.  This function instead identifies any container whose NetworkMode
    references a container ID that no longer exists — meaning the network
    namespace it was sharing has been destroyed.

    Only containers whose stale reference matches a **recorded former Gluetun
    ID** are adopted — a dead reference to some unrelated container (e.g. a
    second VPN stack the user runs) is not Companion's to fix.  Exception:
    the first scan after upgrading to this version adopts all dead-ref
    orphans once (the ID history did not exist before, so pre-existing broken
    dependents would otherwise never be repaired).

    Returns the sorted list of container names that need to be recreated.
    """
    result: list[str] = []
    try:
        from .database import get_setting, set_setting

        client = docker.from_env()
        # Build the set of all currently-known container IDs and names
        all_containers  = client.containers.list(all=True)
        known_ids       = {c.id for c in all_containers}
        # Also include short IDs (first 12 chars) as Docker stores them
        known_short_ids = {c.id[:12] for c in all_containers}
        known_names     = {c.name for c in all_containers}

        gluetun_ids = _known_gluetun_ids()
        # One-time legacy pass: before this version no ID history existed, so
        # orphans created earlier reference IDs we never recorded.
        legacy_pass = get_setting('orphan_legacy_adoption_done', '0') != '1'

        for c in all_containers:
            mode = c.attrs['HostConfig'].get('NetworkMode', '')
            if not mode.startswith('container:'):
                continue
            ref = mode[len('container:'):]
            # Reference still resolves → not orphaned
            if ref in known_ids or ref in known_short_ids or ref in known_names:
                continue
            # Dead reference — only adopt if it was one of *our* Gluetun IDs
            if ref in gluetun_ids or ref[:12] in gluetun_ids:
                logger.debug(
                    'list_orphaned_network_dependents: %s has stale NetworkMode %r '
                    '(former Gluetun ID)', c.name, mode,
                )
                result.append(c.name)
            elif legacy_pass:
                logger.info(
                    'list_orphaned_network_dependents: %s has stale NetworkMode %r — '
                    'adopting once (legacy pass, no ID history yet)', c.name, mode,
                )
                result.append(c.name)
            else:
                logger.debug(
                    'list_orphaned_network_dependents: %s references dead container %r '
                    'which was never a Gluetun managed by Companion — skipping',
                    c.name, ref,
                )

        if legacy_pass:
            set_setting('orphan_legacy_adoption_done', '1')
    except Exception as exc:
        logger.warning('list_orphaned_network_dependents: %s', exc)
    return sorted(result)


def list_docker_containers() -> list[str]:
    """Return the names of all currently running Docker containers, sorted."""
    try:
        client = docker.from_env()
        return sorted(c.name for c in client.containers.list())
    except Exception as exc:
        logger.warning('list_docker_containers: %s', exc)
        return []


def restart_containers_in_order(
    container_names: list[str],
    compose_dir: str = '',
    compose_project: str = '',
    delay_secs: float = 3.0,
    exclude: set[str] | None = None,
    pull_set: set[str] | None = None,
) -> tuple[list[str], list[str]]:
    """
    Recreate Docker containers one by one in the specified order, with a short
    pause between each.  Intended to be called after a VPN server switch so
    that user-chosen dependents (e.g. qbittorrent, Radarr …) come back up in
    the right sequence.

    Uses ``docker compose up -d --force-recreate <service>`` (not ``docker
    restart``) so that containers using ``network_mode: service:<gluetun>``
    are recreated with the correct new network namespace reference.

    ``compose_dir`` / ``compose_project`` should match those of the gluetun
    service when the dependent containers live in the same Compose stack.

    ``exclude`` — container names to skip (e.g. those paused before the
    benchmark; they will be restarted separately at benchmark end).

    Returns (restarted_names, updated_image_names).
    """
    restarted: list[str] = []
    updated_imgs: list[str] = []
    exclude_set = set(exclude) if exclude else set()
    names = [
        n.strip() for n in container_names
        if n and n.strip() and n.strip() not in exclude_set
    ]
    if not names:
        return restarted, updated_imgs
    logger.info('Post-switch restart: will recreate %d container(s): %s', len(names), ', '.join(names))
    for idx, name in enumerate(names):
        logger.info('Post-switch recreate [%d/%d]: %s …', idx + 1, len(names), name)
        try:
            if pull_set and name in pull_set:
                ok, updated, img = pull_image(name)
                logger.info('  pull %s: %s%s', img, 'updated' if updated else 'up to date', '' if ok else ' (failed)')
                if updated:
                    updated_imgs.append(img)
            _compose_recreate(name, compose_dir, compose_project)
            restarted.append(name)
            logger.info('Post-switch recreate [%d/%d]: %s OK', idx + 1, len(names), name)
        except Exception as exc:
            logger.warning('Post-switch recreate [%d/%d]: %s FAILED — %s', idx + 1, len(names), name, exc)
        if delay_secs > 0 and idx < len(names) - 1:
            time.sleep(delay_secs)
    return restarted, updated_imgs


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

_TEST_GLUETUN_NAME      = 'gluetun-companion-test'
_SIDECAR_NAME           = 'gluetun-companion-sidecar'
_CATALOGUE_SIDECAR_NAME = 'gluetun-companion-catalogue'
_CATALOGUE_SIDECAR_PORT = 8767


def _remove_container(client, name: str, kill_first: bool = False) -> None:
    """Stop and remove a container by name, ignoring NotFound."""
    try:
        c = client.containers.get(name)
        if kill_first:
            try:
                c.kill()
            except Exception:
                pass
        else:
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
    extra_env: 'dict[str, str] | None' = None,
) -> tuple[bool, str | None]:
    """
    Clone the real Gluetun container config, override the SERVER_* filter
    for the target server, and start a new test container.
    The sidecar port is published on the host so the companion can reach the
    sidecar API via host.docker.internal:<sidecar_port>.

    *extra_env* is an optional dict of additional env vars to set/override,
    typically the WireGuard credential vars for a VPN profile
    (e.g. {"VPN_SERVICE_PROVIDER": "airvpn", "VPN_TYPE": "wireguard",
            "WIREGUARD_PRIVATE_KEY": "...", ...}).
    Secret values must already be decrypted by the caller.
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
        is_custom_provider = (extra_env or {}).get('VPN_SERVICE_PROVIDER') == 'custom'
        for label, var in FILTER_VARS.items():
            env[var] = ''
        if not is_custom_provider:
            env[FILTER_VARS.get(filter_type, 'SERVER_NAMES')] = filter_value

        # Apply VPN profile vars (provider, type, credentials) if provided.
        # When the test targets a specific profile, first clear every known
        # credential var inherited from the real container so credentials of
        # another provider/type cannot leak into the test session.
        if extra_env:
            if extra_env.get('VPN_SERVICE_PROVIDER'):
                from .wg_providers import all_credential_keys
                for k in all_credential_keys():
                    env.pop(k, None)
            env.update(extra_env)

        image    = attrs['Config']['Image']
        cap_add  = attrs['HostConfig'].get('CapAdd') or []
        sysctls  = attrs['HostConfig'].get('Sysctls') or {}
        devices  = attrs['HostConfig'].get('Devices') or []

        # Remove the speed sidecar first: it shares the test Gluetun network
        # namespace and can otherwise keep the WireGuard session alive while
        # the next test container is being prepared.
        _remove_container(client, _SIDECAR_NAME, kill_first=True)
        _remove_container(client, _TEST_GLUETUN_NAME, kill_first=True)

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


def pull_sidecar_image(sidecar_image: str) -> bool:
    """Best-effort pull of the sidecar image (once per benchmark cycle).

    Returns True if the image is available afterwards (freshly pulled OR already
    cached).  A failed pull is non-fatal: as long as a cached copy exists the
    cycle can keep testing, which makes benchmarks resilient to transient
    registry/DNS failures instead of falling back to the proxy on every server.
    """
    try:
        client = docker.from_env()
        try:
            logger.info('Pulling sidecar image: %s', sidecar_image)
            client.images.pull(sidecar_image)
            logger.info('Sidecar image up to date: %s', sidecar_image)
            return True
        except Exception as exc:
            # Pull failed (e.g. DNS/registry hiccup) — fall back to a cached copy.
            try:
                client.images.get(sidecar_image)
                logger.warning(
                    'Sidecar image pull failed (%s) — using cached image', exc,
                )
                return True
            except Exception:
                logger.error('Sidecar image pull failed and no cached copy: %s', exc)
                return False
    except Exception as exc:
        logger.error('pull_sidecar_image %s: %s', sidecar_image, exc)
        return False


def create_speed_sidecar(
    sidecar_image: str, token: str = '', pull: bool = True,
) -> tuple[bool, str | None]:
    """
    Create the sidecar container in the test Gluetun network namespace.

    *pull* controls registry access: with ``pull=False`` the locally cached
    image is reused (pulled only if missing).  Per-server tests pass
    ``pull=False`` so the image is fetched once per cycle via
    ``pull_sidecar_image`` instead of before every server — this avoids
    hammering the registry/DNS and keeps tests resilient to transient failures.

    *token* is passed as SIDECAR_SECRET env var so the sidecar requires it on
    every request.  Generate with secrets.token_hex(32) in the caller.
    """
    try:
        client = docker.from_env()

        if pull:
            logger.info('Pulling sidecar image: %s', sidecar_image)
            client.images.pull(sidecar_image)
            logger.info('Sidecar image up to date: %s', sidecar_image)
        else:
            # Reuse the cached image; pull only if it is missing locally.
            try:
                client.images.get(sidecar_image)
            except docker.errors.ImageNotFound:
                logger.info('Sidecar image not cached — pulling: %s', sidecar_image)
                client.images.pull(sidecar_image)

        _remove_container(client, _SIDECAR_NAME, kill_first=True)

        env: dict[str, str] = {}
        if token:
            env['SIDECAR_SECRET'] = token

        client.containers.run(
            image=sidecar_image,
            name=_SIDECAR_NAME,
            network_mode=f'container:{_TEST_GLUETUN_NAME}',
            cap_add=['NET_RAW'],
            environment=env,
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
    token: str = '',
) -> tuple[bool, float]:
    """
    Poll the sidecar /health endpoint until VPN is up or timeout expires.
    Returns (success, elapsed_seconds).
    """
    url     = f'http://{host}:{port}/health'
    headers = {'X-Sidecar-Token': token} if token else {}
    start   = time.time()
    # Give sidecar a moment to boot
    time.sleep(5)
    deadline = start + timeout
    while time.time() < deadline:
        try:
            resp = requests.get(url, headers=headers, timeout=5)
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
    method: str = 'dual',
    iperf_fallback: str = '1',
    token: str = '',
) -> dict:
    """
    Call the sidecar /test endpoint and return the result dict.
    Raises RuntimeError if the call fails.
    """
    url     = f'http://{host}:{port}/test'
    headers = {'X-Sidecar-Token': token} if token else {}
    # Ookla controls its own duration; give generous timeout
    timeout = duration * 4 + 120
    resp = requests.post(
        url,
        params={
            'duration':       duration,
            'streams':        streams,
            'method':         method,
            'iperf_fallback': iperf_fallback,
        },
        headers=headers,
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()


def run_sidecar_ping_test(
    host: str,
    port: int,
    targets: list[str] | None = None,
    count: int = 20,
    interval: float = 0.2,
    token: str = '',
) -> dict | None:
    """
    Call the sidecar /ping endpoint to measure jitter and packet loss from
    inside the VPN tunnel (ICMP ping to diverse IPs).

    Expected sidecar response:
        {"results": [{"target": "1.1.1.1", "avg_ms": 12.3, "jitter_ms": 2.1,
                       "packet_loss_pct": 0.0, "ping_min_ms": 10.1, "ping_max_ms": 15.2}]}

    Returns aggregated dict or None if the endpoint is unavailable (old sidecar
    or network failure) — callers must handle None gracefully.
    """
    if targets is None:
        targets = ['1.1.1.1', '8.8.8.8', '9.9.9.9']
    url     = f'http://{host}:{port}/ping'
    headers = {'X-Sidecar-Token': token} if token else {}
    timeout = count * interval * len(targets) + 30
    try:
        resp = requests.post(
            url,
            params={
                'targets':  ','.join(targets),
                'count':    count,
                'interval': interval,
            },
            headers=headers,
            timeout=timeout,
        )
        if resp.status_code == 404:
            logger.debug('Sidecar /ping not available (old image) — skipping stability test')
            return None
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.ConnectionError:
        return None
    except Exception as exc:
        logger.warning('Sidecar ping test error: %s', exc)
        return None

    results = data.get('results', [])
    if not results:
        return None

    jitters  = [r['jitter_ms']       for r in results if r.get('jitter_ms')       is not None]
    losses   = [r['packet_loss_pct'] for r in results if r.get('packet_loss_pct') is not None]
    mins_    = [r['ping_min_ms']     for r in results if r.get('ping_min_ms')      is not None]
    maxs_    = [r['ping_max_ms']     for r in results if r.get('ping_max_ms')      is not None]

    if not jitters:
        return None

    return {
        'jitter_ms':       round(sum(jitters) / len(jitters), 1),
        'packet_loss_pct': round(sum(losses)  / len(losses),  1) if losses else 0.0,
        'ping_min_ms':     round(min(mins_), 1)  if mins_ else None,
        'ping_max_ms':     round(max(maxs_), 1)  if maxs_ else None,
    }




def cleanup_test_containers(sidecar_image: str | None = None) -> None:
    """Stop and remove the test Gluetun and sidecar containers.

    The sidecar image is intentionally kept cached between server tests and
    cycles: it is pulled once per benchmark cycle (see ``pull_sidecar_image``),
    not per server.  Deleting and re-pulling it for every server hammered the
    registry/DNS and made each test fail on a transient DNS hiccup.  The
    *sidecar_image* argument is kept for backward compatibility but no longer
    triggers image removal.
    """
    client = docker.from_env()
    for name in [_SIDECAR_NAME, _TEST_GLUETUN_NAME]:
        _remove_container(client, name, kill_first=True)
    logger.info('Test containers cleaned up')


def create_catalogue_sidecar(
    sidecar_image: str,
    port: int = _CATALOGUE_SIDECAR_PORT,
    token: str = '',
) -> tuple[bool, str | None]:
    """
    Create a standalone sidecar container (bridge network, internet access).
    The sidecar fetches server lists from the public Gluetun GitHub repository:
      https://github.com/qdm12/gluetun-servers/tree/main/pkg/servers

    No volume mounting required — the sidecar only needs outbound HTTPS.

    *token* is passed as SIDECAR_SECRET env var so all sidecar endpoints
    require it on every request.  Generate with secrets.token_hex(32) in
    the caller and reuse the same token for all subsequent HTTP calls.
    """
    try:
        client = docker.from_env()

        logger.info('Pulling sidecar image for catalogue: %s', sidecar_image)
        client.images.pull(sidecar_image)

        _remove_container(client, _CATALOGUE_SIDECAR_NAME)

        env: dict[str, str] = {}
        if token:
            env['SIDECAR_SECRET'] = token

        client.containers.run(
            image=sidecar_image,
            name=_CATALOGUE_SIDECAR_NAME,
            network_mode='bridge',
            environment=env,
            ports={'8766/tcp': port},
            detach=True,
            remove=False,
        )
        logger.info(
            'Catalogue sidecar started: %s (port: %d, auth: %s)',
            _CATALOGUE_SIDECAR_NAME, port, 'yes' if token else 'no',
        )
        return True, None
    except Exception as exc:
        return False, str(exc)


def cleanup_catalogue_sidecar() -> None:
    """Stop and remove the catalogue sidecar container."""
    try:
        _remove_container(docker.from_env(), _CATALOGUE_SIDECAR_NAME)
        logger.info('Catalogue sidecar removed')
    except Exception as exc:
        logger.debug('cleanup_catalogue_sidecar: %s', exc)


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
