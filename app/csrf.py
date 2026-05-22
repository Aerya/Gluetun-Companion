"""
Lightweight CSRF protection — no external dependency.

Usage:
  - Call generate_csrf() to get/create the session token (registered as
    a Jinja global so {{ csrf_token() }} works in templates).
  - validate_csrf() is called automatically via a before_request hook
    registered in create_app().
"""

import secrets

from flask import abort, request, session


def generate_csrf() -> str:
    """Return (and lazily create) the CSRF token for the current session."""
    if '_csrf_token' not in session:
        session['_csrf_token'] = secrets.token_hex(32)
    return session['_csrf_token']


def validate_csrf() -> None:
    """Abort 403 if the request is mutating and the CSRF token is wrong."""
    if request.method not in ('POST', 'PUT', 'DELETE', 'PATCH'):
        return
    # /healthz is unauthenticated and has no session
    if request.endpoint == 'main.healthz':
        return
    # REST API uses Bearer token auth — no session/CSRF needed
    if request.path.startswith('/api/v1/'):
        return

    token = session.get('_csrf_token')
    submitted = (
        request.form.get('_csrf_token')
        or request.headers.get('X-CSRF-Token')
    )
    if not token or not submitted or token != submitted:
        abort(403, description='CSRF token missing or invalid.')
