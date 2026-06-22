# Gluetun Companion Unraid template

This folder contains the upstream DockerMan template for installing Gluetun
Companion on Unraid.

- `gluetun-companion.xml` points to the upstream `Aerya` GHCR image and `main`
  branch URLs.
- The template is suitable for manual DockerMan installs and can be reused as a
  base for a later Community Applications submission.

## Unraid-specific notes

- Generate `SECRET_KEY` once with `openssl rand -hex 32`, paste it in the
  template, and keep it unchanged for the life of the instance.
- The container intentionally runs as root. Gluetun Companion must read and
  write DockerMan templates under
  `/boot/config/plugins/dockerMan/templates-user`, which are root-owned and
  typically mode `600` on Unraid. Exposing `PUID`/`PGID` would be misleading
  unless the user also changes host permissions manually.
- The Docker socket mount is required for sidecar benchmarks, Docker event
  monitoring and recreating running containers attached to Gluetun's network
  namespace.
- The DockerMan templates mount is required for persistent Unraid switches:
  Companion writes Gluetun environment changes back to the Gluetun XML template
  before recreating the container.
- The Gluetun appdata mount is read-only and lets Companion import the local
  `servers.json` used by the installed Gluetun container before falling back to
  the public catalogue sidecar.
- The WebUI entry uses `[PORT:8765]`, the container port, so Unraid follows any
  host-port remap made by the user.
