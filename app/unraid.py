"""
Unraid control backend for Gluetun Companion.

On Unraid, containers are created by the Docker Manager (label
``net.unraid.docker.managed=dockerman``) from a per-container template XML in
``/boot/config/plugins/dockerMan/templates-user/`` — there is no Docker Compose
project, so Companion cannot drive them with ``docker compose up -d``.

This module provides the Unraid-specific half of the control layer:

- locate a container's Unraid template;
- write Companion-managed environment variables back into that template
  (``<Config Type="Variable">`` nodes), so the change **persists** and survives
  Unraid's own recreate-from-template on auto-update;
- (recreate of the live container is handled separately via the Docker SDK).

The whole module is gated behind ``gluetun._management_mode() == 'unraid'`` so a
plain Docker / Compose host never touches any of this.

Design notes
------------
- Template write-back is done with **surgical regex text edits**, not a full XML
  re-serialisation: Unraid templates contain HTML entities (``&#x1F389;``,
  ``&amp;gt;`` …) and hand-formatted text that ``xml.etree`` would mangle on
  rewrite.  We only replace the value of the targeted ``<Config>`` nodes and
  leave every other byte untouched.
- A timestamped ``.bak`` copy is written before any modification.
- Secret values are never logged — only the variable names that changed.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import time

logger = logging.getLogger(__name__)

DEFAULT_TEMPLATE_DIR = '/boot/config/plugins/dockerMan/templates-user'


def template_dir() -> str:
    """Directory holding the Unraid user templates (env-overridable)."""
    return (os.environ.get('UNRAID_TEMPLATE_DIR', '') or DEFAULT_TEMPLATE_DIR).strip()


# ---------------------------------------------------------------------------
# Template lookup
# ---------------------------------------------------------------------------

_NAME_RE = re.compile(r'<Name>\s*([^<\s][^<]*?)\s*</Name>')


def _template_name(text: str) -> str:
    m = _NAME_RE.search(text)
    return m.group(1).strip() if m else ''


def find_template(container_name: str, directory: str | None = None) -> str | None:
    """Return the path of the Unraid template whose ``<Name>`` matches.

    Matching is by the template's ``<Name>`` element (authoritative), not the
    filename, so a container renamed in the UI is still found.  Returns ``None``
    when no template directory or no match is found.
    """
    directory = directory or template_dir()
    if not container_name or not os.path.isdir(directory):
        return None
    try:
        candidates = sorted(
            os.path.join(directory, f)
            for f in os.listdir(directory)
            if f.lower().endswith('.xml')
        )
    except OSError as exc:
        logger.warning('find_template: cannot list %s: %s', directory, exc)
        return None
    for path in candidates:
        try:
            with open(path, encoding='utf-8') as fh:
                text = fh.read()
        except OSError:
            continue
        if _template_name(text) == container_name:
            return path
    return None


# ---------------------------------------------------------------------------
# Template env write-back
# ---------------------------------------------------------------------------

def _xml_escape(value: str) -> str:
    return (
        value.replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
        .replace('"', '&quot;')
    )


def _attr(tag: str, name: str) -> str:
    m = re.search(r'\b' + re.escape(name) + r'="([^"]*)"', tag)
    return m.group(1) if m else ''


# Matches a whole <Config …>…</Config> or self-closing <Config …/> element.
_CONFIG_RE = re.compile(
    r'<Config\b(?P<tag>[^>]*?)(?:/>|>(?P<val>.*?)</Config>)',
    re.DOTALL,
)


def update_template_env(
    template_text: str,
    pairs: list[tuple[str, str]],
    secret_keys: 'frozenset[str] | set[str]' = frozenset(),
) -> tuple[str, list[str]]:
    """Return ``(new_text, changed_keys)`` with managed env vars written in.

    For every ``(name, value)`` in *pairs*, the ``<Config Type="Variable"
    Target="name">`` node's value is replaced (existing node) or a new node is
    inserted before ``</Container>`` (missing).  Only ``Type="Variable"`` nodes
    are touched — ``Port``/``Path`` nodes that happen to share a target are left
    alone.  Everything else in the file is preserved byte-for-byte.
    """
    wanted = dict(pairs)
    seen: set[str] = set()

    def _repl(m: re.Match) -> str:
        tag = m.group('tag')
        if _attr(tag, 'Type') != 'Variable':
            return m.group(0)
        target = _attr(tag, 'Target')
        if target not in wanted:
            return m.group(0)
        seen.add(target)
        return f'<Config{tag}>{_xml_escape(wanted[target])}</Config>'

    new_text = _CONFIG_RE.sub(_repl, template_text)

    missing = [(n, v) for n, v in pairs if n not in seen]
    if missing:
        block = ''.join(
            f'  <Config Name="{n}" Target="{n}" Default="" Mode="" Description="" '
            f'Type="Variable" Display="always" Required="false" '
            f'Mask="{"true" if n in secret_keys else "false"}">{_xml_escape(v)}</Config>\n'
            for n, v in missing
        )
        new_text, count = re.subn(
            r'</Container>', lambda _m: block + '</Container>', new_text, count=1
        )
        if count == 0:
            logger.warning('update_template_env: no </Container> found, appending block')
            new_text = new_text + '\n' + block

    changed = [n for n, _ in pairs]
    return new_text, changed


def write_template_env(
    template_path: str,
    pairs: list[tuple[str, str]],
    secret_keys: 'frozenset[str] | set[str]' = frozenset(),
) -> list[str]:
    """Back up *template_path* then write the managed env vars into it.

    Returns the list of variable names written.  Never logs secret values.
    """
    with open(template_path, encoding='utf-8') as fh:
        original = fh.read()
    new_text, changed = update_template_env(original, pairs, secret_keys)
    if new_text == original:
        logger.info('Unraid template %s already up to date', template_path)
        return []

    backup = f'{template_path}.bak-{time.strftime("%Y%m%d-%H%M%S")}'
    shutil.copy2(template_path, backup)
    tmp = template_path + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='') as fh:
        fh.write(new_text)
    os.replace(tmp, template_path)

    loggable = [n for n in changed if n not in secret_keys]
    redacted = [n for n in changed if n in secret_keys]
    logger.info(
        'Unraid template updated: %s (backup %s); set %s%s',
        template_path, backup, loggable,
        f' + {len(redacted)} secret var(s)' if redacted else '',
    )
    return changed


# ---------------------------------------------------------------------------
# Container recreate (Docker SDK) — replay a container faithfully, changing only
# the environment (and, for dependents, the network namespace reference).
# ---------------------------------------------------------------------------

def _strip_image_env(
    container_env: 'list[str] | None',
    image_env: 'list[str] | None',
) -> list[str]:
    """Drop env entries identical to the image's baked defaults.

    Docker layers image env first, then explicit ``-e`` values.  Replaying only
    the entries that differ from the image keeps the effective environment
    identical while letting image-baked vars (``PATH``, s6/linuxserver
    internals, gluetun option defaults …) float with image updates instead of
    being pinned to the values captured at inspect time.  ``image_env=None``
    strips nothing (back-compatible).
    """
    if not image_env:
        return list(container_env or [])
    baked = set(image_env)
    return [e for e in (container_env or []) if e not in baked]


def _merge_env(current: 'list[str] | None', overrides: dict[str, str]) -> list[str]:
    """Merge a container's ``Config.Env`` list with override key/values.

    Existing keys are replaced in place (order preserved); new keys are appended.
    Blank overrides are kept (mirrors Companion's credential-blanking).
    """
    out: list[str] = []
    remaining = dict(overrides)
    for item in current or []:
        key = item.split('=', 1)[0]
        if key in remaining:
            out.append(f'{key}={remaining.pop(key)}')
        else:
            out.append(item)
    for key, value in remaining.items():
        out.append(f'{key}={value}')
    return out


def _ports_from_bindings(port_bindings: 'dict | None') -> dict:
    """Convert inspect ``HostConfig.PortBindings`` to the docker-py ``ports`` kwarg."""
    ports: dict = {}
    for cport, binds in (port_bindings or {}).items():
        hosts = []
        for b in binds or []:
            ip = (b or {}).get('HostIp') or ''
            hp = (b or {}).get('HostPort') or ''
            if not hp:
                continue
            hosts.append((ip, int(hp)) if ip else int(hp))
        if len(hosts) == 1:
            ports[cport] = hosts[0]
        elif hosts:
            ports[cport] = hosts
    return ports


def _devices_from_inspect(devices: 'list | None') -> list[str]:
    out: list[str] = []
    for d in devices or []:
        host = (d or {}).get('PathOnHost', '')
        cont = (d or {}).get('PathInContainer', '') or host
        perms = (d or {}).get('CgroupPermissions', 'rwm') or 'rwm'
        if host:
            out.append(f'{host}:{cont}:{perms}')
    return out


def recreate_kwargs_from_inspect(
    attrs: dict,
    env_overrides: 'dict[str, str] | None' = None,
    network_mode: 'str | None' = None,
    image_env: 'list[str] | None' = None,
) -> dict:
    """Build ``client.containers.run`` kwargs that re-create *attrs* faithfully.

    Only the environment (merged with *env_overrides*) and, optionally, the
    network mode are changed.  Everything else — image, labels (incl.
    ``net.unraid.docker.managed``), caps, sysctls, devices, volumes, published
    ports, restart policy — is replayed from the live ``docker inspect`` so the
    container stays byte-for-byte the one Unraid created.

    *image_env* (the image's ``Config.Env``) is stripped from the replayed
    environment so image-baked defaults are not pinned — see ``_strip_image_env``.
    """
    config = attrs.get('Config', {}) or {}
    host = attrs.get('HostConfig', {}) or {}
    name = (attrs.get('Name', '') or '').lstrip('/')
    rp = host.get('RestartPolicy') or {}

    kwargs: dict = {
        'name': name,
        'image': config.get('Image', ''),
        'environment': _merge_env(
            _strip_image_env(config.get('Env'), image_env), env_overrides or {}
        ),
        'labels': config.get('Labels') or {},
        'network_mode': network_mode or host.get('NetworkMode', '') or 'bridge',
        'cap_add': list(host.get('CapAdd') or []),
        'cap_drop': list(host.get('CapDrop') or []),
        'sysctls': dict(host.get('Sysctls') or {}),
        'devices': _devices_from_inspect(host.get('Devices')),
        'volumes': list(host.get('Binds') or []),
        'restart_policy': rp if rp.get('Name') and rp.get('Name') != 'no' else None,
        'privileged': bool(host.get('Privileged')),
        'dns': list(host.get('Dns') or []),
        'extra_hosts': list(host.get('ExtraHosts') or []),
        'detach': True,
    }
    # Published ports are meaningless (and rejected by Docker) for a container
    # that shares another container's network namespace.
    if not str(kwargs['network_mode']).startswith('container:'):
        kwargs['ports'] = _ports_from_bindings(host.get('PortBindings'))
    return kwargs


def sdk_recreate(
    container_name: str,
    env_overrides: 'dict[str, str] | None' = None,
    network_mode: 'str | None' = None,
    *,
    stop_timeout: int = 30,
):
    """Recreate a container from its live inspect via the Docker SDK.

    Stop and remove *container_name*, then re-create it with an identical
    configuration except for the environment (merged with *env_overrides*, minus
    image-baked defaults) and, optionally, *network_mode*.  On failure after
    removal, attempt a best-effort rollback to the original configuration and
    re-raise.  Returns the new container object.
    """
    import docker

    client = docker.from_env()
    c = client.containers.get(container_name)
    attrs = c.attrs
    try:
        image_env = (
            client.images.get(attrs.get('Config', {}).get('Image', ''))
            .attrs.get('Config', {}).get('Env') or []
        )
    except Exception as exc:
        logger.warning('sdk_recreate: cannot read image env for %s: %s', container_name, exc)
        image_env = []

    new_kwargs = recreate_kwargs_from_inspect(attrs, env_overrides, network_mode, image_env)
    original_kwargs = recreate_kwargs_from_inspect(attrs, None, None, image_env)

    logger.info('sdk_recreate: stopping + removing %s', container_name)
    c.stop(timeout=stop_timeout)
    c.remove()
    try:
        new = client.containers.run(**new_kwargs)
        logger.info('sdk_recreate: %s recreated (id=%s)', container_name, new.short_id)
        return new
    except Exception as exc:
        logger.error(
            'sdk_recreate: recreate of %s failed (%s) — rolling back to original config',
            container_name, exc,
        )
        try:
            client.containers.run(**original_kwargs)
        except Exception as rb:
            logger.critical('sdk_recreate: ROLLBACK of %s FAILED: %s', container_name, rb)
        raise
