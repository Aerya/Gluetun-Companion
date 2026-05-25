"""
WireGuard provider catalog for Gluetun Companion.

Each entry describes one VPN provider with native or custom WireGuard support.

Keys per provider
-----------------
label            : display name shown in the UI
compose_provider : value of VPN_SERVICE_PROVIDER written to the compose override
native_wg        : True when Gluetun has a built-in server list for this provider
via_custom       : True when the provider uses VPN_SERVICE_PROVIDER=custom
fields           : ordered list of WireGuard credential field descriptors
server_filters   : Gluetun filter env vars available for this provider (empty = none)
help_url         : link to the Gluetun wiki page for this provider
hint_fr / hint_en: short guidance shown under the provider form

Field descriptor keys
---------------------
key        : Gluetun env var name  (e.g. "WIREGUARD_PRIVATE_KEY")
label_fr   : French UI label
label_en   : English UI label
required   : bool — must be non-empty before the profile can be activated
secret     : bool — value stored encrypted and masked in the UI (shown as ••••)
"""

from __future__ import annotations

_F = dict  # type alias for readability

WG_PROVIDERS: dict[str, dict] = {

    # ── Providers with native WireGuard support in Gluetun ─────────────────

    'airvpn': {
        'label':            'AirVPN',
        'compose_provider': 'airvpn',
        'native_wg':        True,
        'via_custom':       False,
        'fields': [
            _F(key='WIREGUARD_PRIVATE_KEY',
               label_fr='Clé privée',        label_en='Private key',
               required=True,  secret=True),
            _F(key='WIREGUARD_PRESHARED_KEY',
               label_fr='Clé pré-partagée',  label_en='Preshared key',
               required=True,  secret=True),
            _F(key='WIREGUARD_ADDRESSES',
               label_fr='Adresse IP (CIDR)', label_en='IP address (CIDR)',
               required=True,  secret=False),
        ],
        'server_filters': [
            'SERVER_COUNTRIES', 'SERVER_REGIONS', 'SERVER_CITIES',
            'SERVER_NAMES', 'SERVER_HOSTNAMES',
        ],
        'help_url': 'https://github.com/qdm12/gluetun-wiki/blob/main/setup/providers/airvpn.md',
        'hint_fr': 'Obtenez vos clés depuis le générateur de configuration de votre espace client AirVPN.',
        'hint_en': 'Get your keys from the Config Generator in your AirVPN Client Area.',
    },

    'ivpn': {
        'label':            'IVPN',
        'compose_provider': 'ivpn',
        'native_wg':        True,
        'via_custom':       False,
        'fields': [
            _F(key='WIREGUARD_PRIVATE_KEY',
               label_fr='Clé privée',        label_en='Private key',
               required=True,  secret=True),
            _F(key='WIREGUARD_ADDRESSES',
               label_fr='Adresse IP (CIDR)', label_en='IP address (CIDR)',
               required=True,  secret=False),
        ],
        'server_filters': ['SERVER_COUNTRIES', 'SERVER_CITIES', 'SERVER_HOSTNAMES'],
        'help_url': 'https://github.com/qdm12/gluetun-wiki/blob/main/setup/providers/ivpn.md',
        'hint_fr': 'Clé propre à votre compte, commune à tous les serveurs IVPN.',
        'hint_en': 'Account-specific key, the same for all IVPN servers.',
    },

    'mullvad': {
        'label':            'Mullvad',
        'compose_provider': 'mullvad',
        'native_wg':        True,
        'via_custom':       False,
        'fields': [
            _F(key='WIREGUARD_PRIVATE_KEY',
               label_fr='Clé privée',        label_en='Private key',
               required=True,  secret=True),
            _F(key='WIREGUARD_ADDRESSES',
               label_fr='Adresse IP (CIDR)', label_en='IP address (CIDR)',
               required=True,  secret=False),
        ],
        'server_filters': ['SERVER_COUNTRIES', 'SERVER_CITIES', 'SERVER_HOSTNAMES'],
        'help_url': 'https://github.com/qdm12/gluetun-wiki/blob/main/setup/providers/mullvad.md',
        'hint_fr': 'Générez un fichier de configuration WireGuard depuis votre espace Mullvad pour obtenir votre clé privée.',
        'hint_en': 'Generate a WireGuard config file from your Mullvad account to get your private key.',
    },

    'nordvpn': {
        'label':            'NordVPN',
        'compose_provider': 'nordvpn',
        'native_wg':        True,
        'via_custom':       False,
        'fields': [
            _F(key='WIREGUARD_PRIVATE_KEY',
               label_fr='Clé privée', label_en='Private key',
               required=True, secret=True),
        ],
        'server_filters': ['SERVER_COUNTRIES', 'SERVER_REGIONS', 'SERVER_CITIES', 'SERVER_HOSTNAMES'],
        'help_url': 'https://github.com/qdm12/gluetun-wiki/blob/main/setup/providers/nordvpn.md',
        'hint_fr': 'Obtenez votre clé privée depuis la section "Configuration manuelle" de votre espace NordVPN.',
        'hint_en': 'Get your private key from the Manual Configuration section of your NordVPN account.',
    },

    'protonvpn': {
        'label':            'ProtonVPN',
        'compose_provider': 'protonvpn',
        'native_wg':        True,
        'via_custom':       False,
        'fields': [
            _F(key='WIREGUARD_PRIVATE_KEY',
               label_fr='Clé privée', label_en='Private key',
               required=True, secret=True),
        ],
        'server_filters': ['SERVER_COUNTRIES', 'SERVER_REGIONS', 'SERVER_CITIES', 'SERVER_HOSTNAMES'],
        'help_url': 'https://github.com/qdm12/gluetun-wiki/blob/main/setup/providers/protonvpn.md',
        'hint_fr': 'Générez un fichier de configuration WireGuard depuis votre espace ProtonVPN pour obtenir votre clé privée.',
        'hint_en': 'Generate a WireGuard config file from your ProtonVPN account to get your private key.',
    },

    'surfshark': {
        'label':            'Surfshark',
        'compose_provider': 'surfshark',
        'native_wg':        True,
        'via_custom':       False,
        'fields': [
            _F(key='WIREGUARD_PRIVATE_KEY',
               label_fr='Clé privée',        label_en='Private key',
               required=True,  secret=True),
            _F(key='WIREGUARD_ADDRESSES',
               label_fr='Adresse IP (CIDR)', label_en='IP address (CIDR)',
               required=True,  secret=False),
        ],
        'server_filters': ['SERVER_COUNTRIES', 'SERVER_REGIONS', 'SERVER_CITIES', 'SERVER_HOSTNAMES'],
        'help_url': 'https://github.com/qdm12/gluetun-wiki/blob/main/setup/providers/surfshark.md',
        'hint_fr': 'Obtenez votre clé privée et votre adresse IP depuis la section "Configuration manuelle" de Surfshark.',
        'hint_en': 'Get your private key and IP address from the Surfshark Manual Setup section.',
    },

    'fastestvpn': {
        'label':            'FastestVPN',
        'compose_provider': 'fastestvpn',
        'native_wg':        True,
        'via_custom':       False,
        'fields': [
            _F(key='WIREGUARD_PRIVATE_KEY',
               label_fr='Clé privée',        label_en='Private key',
               required=True,  secret=True),
            _F(key='WIREGUARD_ADDRESSES',
               label_fr='Adresse IP (CIDR)', label_en='IP address (CIDR)',
               required=True,  secret=False),
        ],
        'server_filters': ['SERVER_COUNTRIES', 'SERVER_CITIES', 'SERVER_HOSTNAMES'],
        'help_url': 'https://github.com/qdm12/gluetun-wiki/blob/main/setup/providers/fastestvpn.md',
        'hint_fr': 'Contactez le support FastestVPN pour obtenir un fichier de configuration WireGuard contenant votre clé privée et votre adresse IP.',
        'hint_en': 'Contact FastestVPN support to get a WireGuard config file containing your private key and IP address.',
    },

    'windscribe': {
        'label':            'Windscribe',
        'compose_provider': 'windscribe',
        'native_wg':        True,
        'via_custom':       False,
        'fields': [
            _F(key='WIREGUARD_PRIVATE_KEY',
               label_fr='Clé privée',        label_en='Private key',
               required=True,  secret=True),
            _F(key='WIREGUARD_PRESHARED_KEY',
               label_fr='Clé pré-partagée',  label_en='Preshared key',
               required=True,  secret=True),
            _F(key='WIREGUARD_ADDRESSES',
               label_fr='Adresse IP (CIDR)', label_en='IP address (CIDR)',
               required=True,  secret=False),
        ],
        'server_filters': ['SERVER_REGIONS', 'SERVER_CITIES', 'SERVER_HOSTNAMES'],
        'help_url': 'https://github.com/qdm12/gluetun-wiki/blob/main/setup/providers/windscribe.md',
        'hint_fr': 'Clé propre à votre compte Windscribe, commune à tous les serveurs.',
        'hint_en': 'Account-specific key, the same for all Windscribe servers.',
    },

    # ── Providers using VPN_SERVICE_PROVIDER=custom (no native WG list) ────
    # These providers support WireGuard but Gluetun has no built-in server
    # list for them — the user must provide endpoint IP, port and public key.
    # Covered: CyberGhost, PrivateVPN, PureVPN, VPN Unlimited, TorGuard,
    #          VyprVPN, and any other provider not listed above.

    'custom': {
        'label':            'Custom WireGuard',
        'compose_provider': 'custom',
        'native_wg':        False,
        'via_custom':       True,
        'fields': [
            _F(key='WIREGUARD_ENDPOINT_IP',
               label_fr='IP du serveur',          label_en='Server endpoint IP',
               required=True,  secret=False),
            _F(key='WIREGUARD_ENDPOINT_PORT',
               label_fr='Port du serveur',         label_en='Server endpoint port',
               required=True,  secret=False),
            _F(key='WIREGUARD_PUBLIC_KEY',
               label_fr='Clé publique du serveur', label_en='Server public key',
               required=True,  secret=False),
            _F(key='WIREGUARD_PRIVATE_KEY',
               label_fr='Votre clé privée',        label_en='Your private key',
               required=True,  secret=True),
            _F(key='WIREGUARD_ADDRESSES',
               label_fr='Adresse IP (CIDR)',       label_en='IP address (CIDR)',
               required=True,  secret=False),
            _F(key='WIREGUARD_PRESHARED_KEY',
               label_fr='Clé pré-partagée (opt)',  label_en='Preshared key (opt)',
               required=False, secret=True),
        ],
        'server_filters': [],
        'help_url': 'https://github.com/qdm12/gluetun-wiki/blob/main/setup/providers/custom.md',
        'hint_fr': (
            'Pour CyberGhost, PrivateVPN, PureVPN, VPN Unlimited, TorGuard, VyprVPN '
            'et tout fournisseur sans support WireGuard natif dans Gluetun.'
        ),
        'hint_en': (
            'For CyberGhost, PrivateVPN, PureVPN, VPN Unlimited, TorGuard, VyprVPN, '
            'and any provider without native WireGuard support in Gluetun.'
        ),
    },
}


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def get_provider(key: str) -> dict | None:
    """Return provider descriptor by key, or None if unknown."""
    return WG_PROVIDERS.get(key)


def get_all_providers() -> list[tuple[str, dict]]:
    """Return [(key, descriptor)] sorted alphabetically by label."""
    return sorted(WG_PROVIDERS.items(), key=lambda kv: kv[1]['label'])


def get_fields(provider_key: str) -> list[dict]:
    """Return all field descriptors for the given provider (empty list if unknown)."""
    p = WG_PROVIDERS.get(provider_key)
    return p['fields'] if p else []


def get_required_fields(provider_key: str) -> list[dict]:
    """Return only the required field descriptors."""
    return [f for f in get_fields(provider_key) if f['required']]


def get_secret_field_keys(provider_key: str) -> set[str]:
    """Return the set of env-var keys that must be stored encrypted."""
    return {f['key'] for f in get_fields(provider_key) if f['secret']}
