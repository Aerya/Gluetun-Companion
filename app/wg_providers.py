"""
VPN provider catalog for Gluetun Companion.

Each entry describes one VPN provider supported by Gluetun, with the
connection types (WireGuard and/or OpenVPN) Gluetun handles natively for it.
The catalog is built from the official Gluetun wiki:
https://github.com/qdm12/gluetun-wiki/tree/main/setup/providers

Keys per provider
-----------------
label            : display name shown in the UI
compose_provider : value of VPN_SERVICE_PROVIDER written to the compose
                   override.  Provider dict keys are identical to this value
                   so they also match the Gluetun catalogue JSON names.
vpn_types        : tuple of supported types, e.g. ('wireguard', 'openvpn').
                   The first entry is the default type for new profiles.
fields           : {vpn_type: [field descriptors]} credential fields per type
server_filters   : Gluetun filter env vars available for this provider (empty = none)
help_url         : link to the Gluetun wiki page for this provider
hints            : {vpn_type: {'fr': str, 'en': str}} guidance shown under the form

Field descriptor keys
---------------------
key        : Gluetun env var name  (e.g. "WIREGUARD_PRIVATE_KEY")
label_fr   : French UI label
label_en   : English UI label
required   : bool — must be non-empty before the profile can be activated
secret     : bool — value stored encrypted and masked in the UI (shown as ••••)

Notes
-----
- Client certificates / keys (Cyberghost, VPN Unlimited, AirVPN OpenVPN,
  SlickVPN, VPN Secure) are passed through the Gluetun env vars
  OPENVPN_CERT / OPENVPN_KEY / OPENVPN_ENCRYPTED_KEY as the base64 body on a
  single line (no BEGIN/END markers, no newlines) — no file mount required.
- Mullvad is WireGuard-only: Mullvad removed OpenVPN support in January 2026.
"""

from __future__ import annotations

_F = dict  # type alias for readability

VPN_TYPES = ('wireguard', 'openvpn')

# ── Shared field descriptors ────────────────────────────────────────────────

def _wg_private_key() -> dict:
    return _F(key='WIREGUARD_PRIVATE_KEY',
              label_fr='Clé privée',        label_en='Private key',
              required=True,  secret=True)

def _wg_preshared_key(required: bool = True) -> dict:
    return _F(key='WIREGUARD_PRESHARED_KEY',
              label_fr='Clé pré-partagée' + ('' if required else ' (opt)'),
              label_en='Preshared key'    + ('' if required else ' (opt)'),
              required=required, secret=True)

def _wg_addresses() -> dict:
    return _F(key='WIREGUARD_ADDRESSES',
              label_fr='Adresse IP (CIDR)', label_en='IP address (CIDR)',
              required=True,  secret=False)

def _ovpn_user(required: bool = True) -> dict:
    return _F(key='OPENVPN_USER',
              label_fr='Identifiant OpenVPN' + ('' if required else ' (opt)'),
              label_en='OpenVPN username'    + ('' if required else ' (opt)'),
              required=required, secret=False)

def _ovpn_password(required: bool = True) -> dict:
    return _F(key='OPENVPN_PASSWORD',
              label_fr='Mot de passe OpenVPN' + ('' if required else ' (opt)'),
              label_en='OpenVPN password'     + ('' if required else ' (opt)'),
              required=required, secret=True)

def _ovpn_cert() -> dict:
    return _F(key='OPENVPN_CERT',
              label_fr='Certificat client (base64, une seule ligne)',
              label_en='Client certificate (base64, single line)',
              required=True,  secret=False)

def _ovpn_key() -> dict:
    return _F(key='OPENVPN_KEY',
              label_fr='Clé client (base64, une seule ligne)',
              label_en='Client key (base64, single line)',
              required=True,  secret=True)

def _ovpn_encrypted_key() -> dict:
    return _F(key='OPENVPN_ENCRYPTED_KEY',
              label_fr='Clé client chiffrée (base64, une seule ligne)',
              label_en='Encrypted client key (base64, single line)',
              required=True,  secret=True)

def _ovpn_key_passphrase(label_fr: str = 'Passphrase de la clé',
                         label_en: str = 'Key passphrase',
                         required: bool = True) -> dict:
    return _F(key='OPENVPN_KEY_PASSPHRASE',
              label_fr=label_fr, label_en=label_en,
              required=required, secret=True)

_HINT_OVPN_USERPASS_FR = 'Identifiants OpenVPN du fournisseur (souvent distincts des identifiants du site web).'
_HINT_OVPN_USERPASS_EN = 'Provider OpenVPN credentials (often different from your website login).'

_HINT_CERT_FR = ('Collez le contenu base64 du certificat/de la clé sur une seule ligne, '
                 'sans les lignes BEGIN/END. Ces valeurs se trouvent dans le fichier '
                 '.ovpn ou les fichiers fournis par le fournisseur.')
_HINT_CERT_EN = ('Paste the base64 body of the certificate/key as a single line, '
                 'without the BEGIN/END markers. These values are found in the .ovpn '
                 'file or the files supplied by the provider.')


WG_PROVIDERS: dict[str, dict] = {

    # ── Providers with native WireGuard support in Gluetun ─────────────────

    'airvpn': {
        'label':            'AirVPN',
        'compose_provider': 'airvpn',
        'vpn_types':        ('wireguard', 'openvpn'),
        'fields': {
            'wireguard': [
                _wg_private_key(),
                _wg_preshared_key(required=True),
                _wg_addresses(),
            ],
            'openvpn': [
                _ovpn_cert(),
                _ovpn_key(),
            ],
        },
        'server_filters': [
            'SERVER_COUNTRIES', 'SERVER_REGIONS', 'SERVER_CITIES',
            'SERVER_NAMES', 'SERVER_HOSTNAMES',
        ],
        'help_url': 'https://github.com/qdm12/gluetun-wiki/blob/main/setup/providers/airvpn.md',
        'hints': {
            'wireguard': {
                'fr': 'Obtenez vos clés depuis le générateur de configuration de votre espace client AirVPN.',
                'en': 'Get your keys from the Config Generator in your AirVPN Client Area.',
            },
            'openvpn': {
                'fr': 'AirVPN en OpenVPN utilise un certificat et une clé client (pas de login/mot de passe). ' + _HINT_CERT_FR,
                'en': 'AirVPN over OpenVPN authenticates with a client certificate and key (no username/password). ' + _HINT_CERT_EN,
            },
        },
    },

    'cyberghost': {
        'label':            'CyberGhost',
        'compose_provider': 'cyberghost',
        'vpn_types':        ('openvpn',),
        'fields': {
            'openvpn': [
                _ovpn_user(),
                _ovpn_password(),
                _ovpn_cert(),
                _ovpn_key(),
            ],
        },
        'server_filters': ['SERVER_COUNTRIES', 'SERVER_HOSTNAMES'],
        'help_url': 'https://github.com/qdm12/gluetun-wiki/blob/main/setup/providers/cyberghost.md',
        'hints': {
            'openvpn': {
                'fr': 'CyberGhost demande identifiants + certificat et clé client. ' + _HINT_CERT_FR
                      + ' Pour WireGuard, utilisez le fournisseur « Custom WireGuard ».',
                'en': 'CyberGhost needs credentials + a client certificate and key. ' + _HINT_CERT_EN
                      + ' For WireGuard, use the "Custom WireGuard" provider.',
            },
        },
    },

    'expressvpn': {
        'label':            'ExpressVPN',
        'compose_provider': 'expressvpn',
        'vpn_types':        ('openvpn',),
        'fields': {
            'openvpn': [_ovpn_user(), _ovpn_password()],
        },
        'server_filters': ['SERVER_COUNTRIES', 'SERVER_CITIES', 'SERVER_HOSTNAMES'],
        'help_url': 'https://github.com/qdm12/gluetun-wiki/blob/main/setup/providers/expressvpn.md',
        'hints': {
            'openvpn': {
                'fr': 'Identifiants de la page « Configuration manuelle » de votre espace ExpressVPN.',
                'en': 'Credentials from the Manual Configuration page of your ExpressVPN account.',
            },
        },
    },

    'fastestvpn': {
        'label':            'FastestVPN',
        'compose_provider': 'fastestvpn',
        'vpn_types':        ('wireguard', 'openvpn'),
        'fields': {
            'wireguard': [_wg_private_key(), _wg_addresses()],
            'openvpn':   [_ovpn_user(), _ovpn_password()],
        },
        'server_filters': ['SERVER_COUNTRIES', 'SERVER_CITIES', 'SERVER_HOSTNAMES'],
        'help_url': 'https://github.com/qdm12/gluetun-wiki/blob/main/setup/providers/fastestvpn.md',
        'hints': {
            'wireguard': {
                'fr': 'Contactez le support FastestVPN pour obtenir un fichier de configuration WireGuard contenant votre clé privée et votre adresse IP.',
                'en': 'Contact FastestVPN support to get a WireGuard config file containing your private key and IP address.',
            },
            'openvpn': {
                'fr': _HINT_OVPN_USERPASS_FR,
                'en': _HINT_OVPN_USERPASS_EN,
            },
        },
    },

    'giganews': {
        'label':            'Giganews (VyprVPN)',
        'compose_provider': 'giganews',
        'vpn_types':        ('openvpn',),
        'fields': {
            'openvpn': [_ovpn_user(), _ovpn_password()],
        },
        'server_filters': ['SERVER_REGIONS', 'SERVER_HOSTNAMES'],
        'help_url': 'https://github.com/qdm12/gluetun-wiki/blob/main/setup/providers/giganews.md',
        'hints': {
            'openvpn': {
                'fr': _HINT_OVPN_USERPASS_FR,
                'en': _HINT_OVPN_USERPASS_EN,
            },
        },
    },

    'hidemyass': {
        'label':            'HideMyAss',
        'compose_provider': 'hidemyass',
        'vpn_types':        ('openvpn',),
        'fields': {
            'openvpn': [_ovpn_user(), _ovpn_password()],
        },
        'server_filters': ['SERVER_COUNTRIES', 'SERVER_REGIONS', 'SERVER_CITIES', 'SERVER_HOSTNAMES'],
        'help_url': 'https://github.com/qdm12/gluetun-wiki/blob/main/setup/providers/hidemyass.md',
        'hints': {
            'openvpn': {
                'fr': _HINT_OVPN_USERPASS_FR,
                'en': _HINT_OVPN_USERPASS_EN,
            },
        },
    },

    'ipvanish': {
        'label':            'IPVanish',
        'compose_provider': 'ipvanish',
        'vpn_types':        ('openvpn',),
        'fields': {
            'openvpn': [_ovpn_user(), _ovpn_password()],
        },
        'server_filters': ['SERVER_COUNTRIES', 'SERVER_CITIES', 'SERVER_HOSTNAMES'],
        'help_url': 'https://github.com/qdm12/gluetun-wiki/blob/main/setup/providers/ipvanish.md',
        'hints': {
            'openvpn': {
                'fr': _HINT_OVPN_USERPASS_FR,
                'en': _HINT_OVPN_USERPASS_EN,
            },
        },
    },

    'ivpn': {
        'label':            'IVPN',
        'compose_provider': 'ivpn',
        'vpn_types':        ('wireguard', 'openvpn'),
        'fields': {
            'wireguard': [_wg_private_key(), _wg_addresses()],
            'openvpn':   [_ovpn_user(), _ovpn_password(required=False)],
        },
        'server_filters': ['SERVER_COUNTRIES', 'SERVER_CITIES', 'SERVER_HOSTNAMES'],
        'help_url': 'https://github.com/qdm12/gluetun-wiki/blob/main/setup/providers/ivpn.md',
        'hints': {
            'wireguard': {
                'fr': 'Clé propre à votre compte, commune à tous les serveurs IVPN.',
                'en': 'Account-specific key, the same for all IVPN servers.',
            },
            'openvpn': {
                'fr': "L'identifiant peut être votre e-mail ou votre ID de compte (i-xxxx-xxxx-xxxx). "
                      "Le mot de passe n'est requis que si l'identifiant n'est pas l'ID de compte.",
                'en': 'The username can be your email or your account ID (i-xxxx-xxxx-xxxx). '
                      'The password is only needed when the username is not the account ID.',
            },
        },
    },

    'mullvad': {
        'label':            'Mullvad',
        'compose_provider': 'mullvad',
        'vpn_types':        ('wireguard',),
        'fields': {
            'wireguard': [_wg_private_key(), _wg_addresses()],
        },
        'server_filters': ['SERVER_COUNTRIES', 'SERVER_CITIES', 'SERVER_HOSTNAMES'],
        'help_url': 'https://github.com/qdm12/gluetun-wiki/blob/main/setup/providers/mullvad.md',
        'hints': {
            'wireguard': {
                'fr': 'Générez un fichier de configuration WireGuard depuis votre espace Mullvad pour obtenir votre clé privée. '
                      '(Mullvad a supprimé OpenVPN en janvier 2026.)',
                'en': 'Generate a WireGuard config file from your Mullvad account to get your private key. '
                      '(Mullvad removed OpenVPN support in January 2026.)',
            },
        },
    },

    'nordvpn': {
        'label':            'NordVPN',
        'compose_provider': 'nordvpn',
        'vpn_types':        ('wireguard', 'openvpn'),
        'fields': {
            'wireguard': [_wg_private_key()],
            'openvpn':   [_ovpn_user(), _ovpn_password()],
        },
        'server_filters': ['SERVER_COUNTRIES', 'SERVER_REGIONS', 'SERVER_CITIES', 'SERVER_HOSTNAMES'],
        'help_url': 'https://github.com/qdm12/gluetun-wiki/blob/main/setup/providers/nordvpn.md',
        'hints': {
            'wireguard': {
                'fr': 'Obtenez votre clé privée depuis la section "Configuration manuelle" de votre espace NordVPN.',
                'en': 'Get your private key from the Manual Configuration section of your NordVPN account.',
            },
            'openvpn': {
                'fr': 'Utilisez les identifiants de service (Manual configuration → Service credentials), pas votre e-mail/mot de passe.',
                'en': 'Use your service credentials (Manual configuration → Service credentials), not your email/password.',
            },
        },
    },

    'perfect privacy': {
        'label':            'Perfect Privacy',
        'compose_provider': 'perfect privacy',
        'vpn_types':        ('openvpn',),
        'fields': {
            'openvpn': [_ovpn_user(), _ovpn_password()],
        },
        'server_filters': ['SERVER_CITIES'],
        'help_url': 'https://github.com/qdm12/gluetun-wiki/blob/main/setup/providers/perfect-privacy.md',
        'hints': {
            'openvpn': {
                'fr': _HINT_OVPN_USERPASS_FR,
                'en': _HINT_OVPN_USERPASS_EN,
            },
        },
    },

    'privado': {
        'label':            'Privado',
        'compose_provider': 'privado',
        'vpn_types':        ('openvpn',),
        'fields': {
            'openvpn': [_ovpn_user(), _ovpn_password()],
        },
        'server_filters': ['SERVER_COUNTRIES', 'SERVER_REGIONS', 'SERVER_CITIES', 'SERVER_HOSTNAMES'],
        'help_url': 'https://github.com/qdm12/gluetun-wiki/blob/main/setup/providers/privado.md',
        'hints': {
            'openvpn': {
                'fr': _HINT_OVPN_USERPASS_FR,
                'en': _HINT_OVPN_USERPASS_EN,
            },
        },
    },

    'private internet access': {
        'label':            'Private Internet Access',
        'compose_provider': 'private internet access',
        'vpn_types':        ('openvpn',),
        'fields': {
            'openvpn': [_ovpn_user(), _ovpn_password()],
        },
        'server_filters': ['SERVER_REGIONS', 'SERVER_NAMES', 'SERVER_HOSTNAMES'],
        'help_url': 'https://github.com/qdm12/gluetun-wiki/blob/main/setup/providers/private-internet-access.md',
        'hints': {
            'openvpn': {
                'fr': 'Identifiants de votre compte PIA. Pour WireGuard, PIA n\'est pas supporté nativement par Gluetun '
                      '(extraction possible via pia-wg-config + « Custom WireGuard »).',
                'en': 'Your PIA account credentials. For WireGuard, PIA is not natively supported by Gluetun '
                      '(a config can be extracted with pia-wg-config + "Custom WireGuard").',
            },
        },
    },

    'privatevpn': {
        'label':            'PrivateVPN',
        'compose_provider': 'privatevpn',
        'vpn_types':        ('openvpn',),
        'fields': {
            'openvpn': [_ovpn_user(), _ovpn_password()],
        },
        'server_filters': ['SERVER_COUNTRIES', 'SERVER_CITIES', 'SERVER_HOSTNAMES'],
        'help_url': 'https://github.com/qdm12/gluetun-wiki/blob/main/setup/providers/privatevpn.md',
        'hints': {
            'openvpn': {
                'fr': 'Identifiants de votre compte PrivateVPN (pas le « Proxy login » du Control Panel). '
                      'Pour WireGuard, utilisez « Custom WireGuard ».',
                'en': 'Your PrivateVPN account login (not the "Proxy login" from the Control Panel). '
                      'For WireGuard, use "Custom WireGuard".',
            },
        },
    },

    'protonvpn': {
        'label':            'ProtonVPN',
        'compose_provider': 'protonvpn',
        'vpn_types':        ('wireguard', 'openvpn'),
        'fields': {
            'wireguard': [_wg_private_key()],
            'openvpn':   [_ovpn_user(), _ovpn_password()],
        },
        'server_filters': ['SERVER_COUNTRIES', 'SERVER_REGIONS', 'SERVER_CITIES', 'SERVER_HOSTNAMES'],
        'help_url': 'https://github.com/qdm12/gluetun-wiki/blob/main/setup/providers/protonvpn.md',
        'hints': {
            'wireguard': {
                'fr': 'Générez un fichier de configuration WireGuard depuis votre espace ProtonVPN pour obtenir votre clé privée.',
                'en': 'Generate a WireGuard config file from your ProtonVPN account to get your private key.',
            },
            'openvpn': {
                'fr': "Identifiants OpenVPN spécifiques (account.proton.me → VPN → OpenVPN/IKEv2). "
                      "Ajoutez +pmp à l'identifiant pour le port forwarding.",
                'en': 'OpenVPN-specific credentials (account.proton.me → VPN → OpenVPN/IKEv2). '
                      'Append +pmp to the username for port forwarding.',
            },
        },
    },

    'purevpn': {
        'label':            'PureVPN',
        'compose_provider': 'purevpn',
        'vpn_types':        ('openvpn',),
        'fields': {
            'openvpn': [_ovpn_user(), _ovpn_password()],
        },
        'server_filters': ['SERVER_COUNTRIES', 'SERVER_REGIONS', 'SERVER_CITIES', 'SERVER_HOSTNAMES'],
        'help_url': 'https://github.com/qdm12/gluetun-wiki/blob/main/setup/providers/purevpn.md',
        'hints': {
            'openvpn': {
                'fr': _HINT_OVPN_USERPASS_FR + ' Pour WireGuard, utilisez « Custom WireGuard ».',
                'en': _HINT_OVPN_USERPASS_EN + ' For WireGuard, use "Custom WireGuard".',
            },
        },
    },

    'slickvpn': {
        'label':            'SlickVPN',
        'compose_provider': 'slickvpn',
        'vpn_types':        ('openvpn',),
        'fields': {
            'openvpn': [
                _ovpn_user(),
                _ovpn_password(),
                _ovpn_cert(),
                _ovpn_encrypted_key(),
                _ovpn_key_passphrase(required=False,
                                     label_fr='Passphrase de la clé (opt)',
                                     label_en='Key passphrase (opt)'),
            ],
        },
        'server_filters': ['SERVER_COUNTRIES', 'SERVER_REGIONS', 'SERVER_CITIES', 'SERVER_HOSTNAMES'],
        'help_url': 'https://github.com/qdm12/gluetun-wiki/blob/main/setup/providers/slickvpn.md',
        'hints': {
            'openvpn': {
                'fr': 'SlickVPN demande identifiants + certificat et clé client chiffrée. ' + _HINT_CERT_FR,
                'en': 'SlickVPN needs credentials + a client certificate and encrypted key. ' + _HINT_CERT_EN,
            },
        },
    },

    'surfshark': {
        'label':            'Surfshark',
        'compose_provider': 'surfshark',
        'vpn_types':        ('wireguard', 'openvpn'),
        'fields': {
            'wireguard': [_wg_private_key(), _wg_addresses()],
            'openvpn':   [_ovpn_user(), _ovpn_password()],
        },
        'server_filters': ['SERVER_COUNTRIES', 'SERVER_REGIONS', 'SERVER_CITIES', 'SERVER_HOSTNAMES'],
        'help_url': 'https://github.com/qdm12/gluetun-wiki/blob/main/setup/providers/surfshark.md',
        'hints': {
            'wireguard': {
                'fr': 'Obtenez votre clé privée et votre adresse IP depuis la section "Configuration manuelle" de Surfshark.',
                'en': 'Get your private key and IP address from the Surfshark Manual Setup section.',
            },
            'openvpn': {
                'fr': 'Identifiants dans VPN → Configuration manuelle → Identifiants.',
                'en': 'Credentials from VPN → Manual setup → Credentials.',
            },
        },
    },

    'torguard': {
        'label':            'TorGuard',
        'compose_provider': 'torguard',
        'vpn_types':        ('openvpn',),
        'fields': {
            'openvpn': [_ovpn_user(), _ovpn_password()],
        },
        'server_filters': ['SERVER_COUNTRIES', 'SERVER_CITIES', 'SERVER_HOSTNAMES'],
        'help_url': 'https://github.com/qdm12/gluetun-wiki/blob/main/setup/providers/torguard.md',
        'hints': {
            'openvpn': {
                'fr': _HINT_OVPN_USERPASS_FR + ' Pour WireGuard, utilisez « Custom WireGuard ».',
                'en': _HINT_OVPN_USERPASS_EN + ' For WireGuard, use "Custom WireGuard".',
            },
        },
    },

    'vpnsecure': {
        'label':            'VPN Secure',
        'compose_provider': 'vpnsecure',
        'vpn_types':        ('openvpn',),
        'fields': {
            'openvpn': [
                _ovpn_key_passphrase(label_fr='Mot de passe du compte (passphrase de la clé)',
                                     label_en='Account password (key passphrase)'),
                _ovpn_cert(),
                _ovpn_encrypted_key(),
            ],
        },
        'server_filters': ['SERVER_REGIONS', 'SERVER_CITIES', 'SERVER_HOSTNAMES'],
        'help_url': 'https://github.com/qdm12/gluetun-wiki/blob/main/setup/providers/vpn-secure.md',
        'hints': {
            'openvpn': {
                'fr': 'VPN Secure utilise votre certificat (fichier votrelogin.crt) et votre clé chiffrée (votrelogin.key). ' + _HINT_CERT_FR,
                'en': 'VPN Secure uses your certificate (yourusername.crt) and encrypted key (yourusername.key). ' + _HINT_CERT_EN,
            },
        },
    },

    'vpn unlimited': {
        'label':            'VPN Unlimited',
        'compose_provider': 'vpn unlimited',
        'vpn_types':        ('openvpn',),
        'fields': {
            'openvpn': [
                _ovpn_user(),
                _ovpn_password(),
                _ovpn_cert(),
                _ovpn_key(),
            ],
        },
        'server_filters': ['SERVER_COUNTRIES', 'SERVER_REGIONS', 'SERVER_CITIES', 'SERVER_HOSTNAMES'],
        'help_url': 'https://github.com/qdm12/gluetun-wiki/blob/main/setup/providers/vpn-unlimited.md',
        'hints': {
            'openvpn': {
                'fr': 'VPN Unlimited demande identifiants + certificat et clé client. ' + _HINT_CERT_FR
                      + ' Pour WireGuard, utilisez « Custom WireGuard ».',
                'en': 'VPN Unlimited needs credentials + a client certificate and key. ' + _HINT_CERT_EN
                      + ' For WireGuard, use "Custom WireGuard".',
            },
        },
    },

    'vyprvpn': {
        'label':            'VyprVPN',
        'compose_provider': 'vyprvpn',
        'vpn_types':        ('openvpn',),
        'fields': {
            'openvpn': [_ovpn_user(), _ovpn_password()],
        },
        'server_filters': ['SERVER_REGIONS', 'SERVER_HOSTNAMES'],
        'help_url': 'https://github.com/qdm12/gluetun-wiki/blob/main/setup/providers/vyprvpn.md',
        'hints': {
            'openvpn': {
                'fr': _HINT_OVPN_USERPASS_FR + ' Pour WireGuard, utilisez « Custom WireGuard ».',
                'en': _HINT_OVPN_USERPASS_EN + ' For WireGuard, use "Custom WireGuard".',
            },
        },
    },

    'windscribe': {
        'label':            'Windscribe',
        'compose_provider': 'windscribe',
        'vpn_types':        ('wireguard', 'openvpn'),
        'fields': {
            'wireguard': [
                _wg_private_key(),
                _wg_preshared_key(required=True),
                _wg_addresses(),
            ],
            'openvpn': [_ovpn_user(), _ovpn_password()],
        },
        'server_filters': ['SERVER_REGIONS', 'SERVER_CITIES', 'SERVER_HOSTNAMES'],
        'help_url': 'https://github.com/qdm12/gluetun-wiki/blob/main/setup/providers/windscribe.md',
        'hints': {
            'wireguard': {
                'fr': 'Clé propre à votre compte Windscribe, commune à tous les serveurs.',
                'en': 'Account-specific key, the same for all Windscribe servers.',
            },
            'openvpn': {
                'fr': 'Identifiants issus d\'un fichier de configuration généré sur windscribe.com/getconfig/openvpn.',
                'en': 'Credentials from a generated config file at windscribe.com/getconfig/openvpn.',
            },
        },
    },

    # ── Custom provider (VPN_SERVICE_PROVIDER=custom) ──────────────────────
    # Covers every provider without native support in Gluetun, as long as a
    # standard WireGuard or OpenVPN configuration is available.

    'custom': {
        'label':            'Custom (WireGuard / OpenVPN)',
        'compose_provider': 'custom',
        'vpn_types':        ('wireguard', 'openvpn'),
        'fields': {
            'wireguard': [
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
                _wg_addresses(),
                _wg_preshared_key(required=False),
            ],
            'openvpn': [
                _F(key='OPENVPN_CUSTOM_CONFIG',
                   label_fr='Chemin du fichier .conf dans le container (ex : /gluetun/custom.conf)',
                   label_en='Path of the .conf file inside the container (e.g. /gluetun/custom.conf)',
                   required=True,  secret=False),
                _ovpn_user(required=False),
                _ovpn_password(required=False),
            ],
        },
        'server_filters': [],
        'help_url': 'https://github.com/qdm12/gluetun-wiki/blob/main/setup/providers/custom.md',
        'hints': {
            'wireguard': {
                'fr': 'Pour CyberGhost, PrivateVPN, PureVPN, VPN Unlimited, TorGuard, VyprVPN '
                      'et tout fournisseur sans support WireGuard natif dans Gluetun.',
                'en': 'For CyberGhost, PrivateVPN, PureVPN, VPN Unlimited, TorGuard, VyprVPN, '
                      'and any provider without native WireGuard support in Gluetun.',
            },
            'openvpn': {
                'fr': 'Le fichier de configuration OpenVPN doit être monté dans le container Gluetun '
                      '(volume), puis son chemin renseigné ici. Identifiants optionnels selon le fichier.',
                'en': 'The OpenVPN configuration file must be mounted into the Gluetun container '
                      '(volume), then its in-container path set here. Credentials are optional depending on the file.',
            },
        },
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


def get_vpn_types(provider_key: str) -> tuple[str, ...]:
    """Return the supported VPN types for a provider (default type first)."""
    p = WG_PROVIDERS.get(provider_key)
    return p['vpn_types'] if p else ()


def default_vpn_type(provider_key: str) -> str:
    """Return the default (preferred) VPN type for a provider."""
    types = get_vpn_types(provider_key)
    return types[0] if types else 'wireguard'


def get_fields(provider_key: str, vpn_type: str = '') -> list[dict]:
    """Return field descriptors for (provider, vpn_type).

    When *vpn_type* is empty or unsupported, the provider's default type
    is used.  Returns an empty list for unknown providers.
    """
    p = WG_PROVIDERS.get(provider_key)
    if not p:
        return []
    if vpn_type not in p['vpn_types']:
        vpn_type = p['vpn_types'][0]
    return p['fields'].get(vpn_type, [])


def get_required_fields(provider_key: str, vpn_type: str = '') -> list[dict]:
    """Return only the required field descriptors for (provider, vpn_type)."""
    return [f for f in get_fields(provider_key, vpn_type) if f['required']]


def get_secret_field_keys(provider_key: str, vpn_type: str = '') -> set[str]:
    """Return the env-var keys stored encrypted for (provider, vpn_type).

    With an empty *vpn_type*, the union across all the provider's types is
    returned (useful when handling stored vars of unknown type).
    """
    p = WG_PROVIDERS.get(provider_key)
    if not p:
        return set()
    if vpn_type in p['vpn_types']:
        return {f['key'] for f in p['fields'][vpn_type] if f['secret']}
    return {
        f['key']
        for fields in p['fields'].values()
        for f in fields
        if f['secret']
    }


def all_credential_keys() -> set[str]:
    """Return every credential env-var key across all providers and types.

    Used to blank out credentials inherited from the base compose file (or
    the cloned container env) when switching to a different VPN profile, so
    that e.g. a WIREGUARD_PRESHARED_KEY from AirVPN does not leak into a
    Mullvad or OpenVPN session.
    """
    keys: set[str] = set()
    for p in WG_PROVIDERS.values():
        for fields in p['fields'].values():
            keys.update(f['key'] for f in fields)
    return keys
