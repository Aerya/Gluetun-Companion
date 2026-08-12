"""Helpers for the explicit first-run import from the active Gluetun container."""

from .wg_providers import WG_PROVIDERS, default_vpn_type, get_fields, get_vpn_types


def active_profile_values(env: dict[str, str]) -> dict:
    """Return validated profile values extracted from effective container env.

    Docker has already resolved Compose ``env_file`` and ``.env`` references at
    this point. Values backed only by mounted secret files are deliberately not
    read here and are reported as missing instead.
    """
    provider = (env.get('VPN_SERVICE_PROVIDER') or '').strip().lower()
    if provider not in WG_PROVIDERS:
        return {'ok': False, 'provider': provider, 'error': 'unsupported_provider'}

    vpn_type = (env.get('VPN_TYPE') or '').strip().lower()
    if vpn_type not in get_vpn_types(provider):
        vpn_type = default_vpn_type(provider)

    fields = get_fields(provider, vpn_type)
    values = {
        field['key']: (env.get(field['key']) or '').strip()
        for field in fields
        if (env.get(field['key']) or '').strip()
    }
    missing = [
        field['key'] for field in fields
        if field.get('required') and not values.get(field['key'])
    ]
    return {
        'ok': not missing,
        'provider': provider,
        'vpn_type': vpn_type,
        'values': values,
        'missing': missing,
        'error': 'missing_required' if missing else '',
    }
