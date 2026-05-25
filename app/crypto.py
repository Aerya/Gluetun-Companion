"""
Symmetric encryption for WireGuard credentials stored in SQLite.

The Fernet key is derived from the SECRET_KEY environment variable via
PBKDF2HMAC-SHA256.  Changing SECRET_KEY makes all existing encrypted values
unreadable (equivalent to wiping all WireGuard profiles), so the app logs a
clear warning when this happens.

Public API
----------
encrypt(plaintext: str) -> str
    Returns a prefixed ciphertext string "enc:<base64_token>".

decrypt(ciphertext: str) -> str
    Accepts "enc:<base64_token>" (decrypts and returns plaintext) or a plain
    string (returned as-is, for backward compatibility with unencrypted values).

is_encrypted(value: str) -> bool
    True when the value carries the "enc:" prefix.

mask(value: str) -> str
    Returns "••••" for encrypted/non-empty values, "" for empty ones.
    Use this to avoid ever sending plaintext secrets to the browser.
"""

from __future__ import annotations

import base64
import os

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

# Prefix that distinguishes encrypted values stored in the DB.
_PREFIX = 'enc:'

# Fixed application salt — ties the derived key to Gluetun Companion so that
# the same SECRET_KEY used by another app cannot decrypt our credentials.
_SALT = b'gluetun-companion-wg-v1'

# Cached Fernet instance (key derivation is intentionally slow — cache it).
_fernet_cache: Fernet | None = None
_fernet_secret: str = ''


def _get_fernet() -> Fernet:
    global _fernet_cache, _fernet_secret
    secret = os.environ.get('SECRET_KEY', '')
    if not secret:
        raise RuntimeError(
            'SECRET_KEY env var is not set — cannot encrypt/decrypt WireGuard credentials.'
        )
    # Re-derive only when SECRET_KEY changes (e.g. during tests).
    if _fernet_cache is None or secret != _fernet_secret:
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=_SALT,
            iterations=480_000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(secret.encode()))
        _fernet_cache = Fernet(key)
        _fernet_secret = secret
    return _fernet_cache


def encrypt(plaintext: str) -> str:
    """Encrypt *plaintext* and return a prefixed ciphertext string.

    An empty string is returned as-is (no point encrypting nothing).
    """
    if not plaintext:
        return plaintext
    token = _get_fernet().encrypt(plaintext.encode()).decode()
    return f'{_PREFIX}{token}'


def decrypt(ciphertext: str) -> str:
    """Decrypt a prefixed ciphertext string.

    Plain strings (without the "enc:" prefix) are returned unchanged so that
    legacy or non-secret values stored in vpn_profile_vars work transparently.

    Raises ValueError when decryption fails (e.g. wrong SECRET_KEY).
    """
    if not ciphertext or not ciphertext.startswith(_PREFIX):
        return ciphertext
    token = ciphertext[len(_PREFIX):]
    try:
        return _get_fernet().decrypt(token.encode()).decode()
    except (InvalidToken, Exception) as exc:
        raise ValueError(
            f'Cannot decrypt WireGuard credential. '
            f'If you changed SECRET_KEY you must re-enter your WireGuard keys. '
            f'Detail: {exc}'
        ) from exc


def is_encrypted(value: str) -> bool:
    """Return True when *value* carries the "enc:" prefix."""
    return bool(value and value.startswith(_PREFIX))


def mask(value: str) -> str:
    """Return "••••" for any non-empty value, "" for empty ones.

    Use this helper before passing credential values to Jinja2 templates so
    that secrets never reach the browser in plaintext.
    """
    return '••••' if value else ''
