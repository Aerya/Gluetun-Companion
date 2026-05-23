"""
Lightweight CSRF protection — no external dependency.

Usage:
  - Call generate_csrf() to get/create the session token (registered as
    a Jinja global so {{ csrf_token() }} works in templates).
  - validate_csrf() is called automatically via a before_request hook
    registered in create_app().
"""

import secrets
from typing import Optional

from flask import abort, make_response, redirect, request, session, url_for


def generate_csrf() -> str:
    """Return (and lazily create) the CSRF token for the current session."""
    if '_csrf_token' not in session:
        session['_csrf_token'] = secrets.token_hex(32)
    return session['_csrf_token']


def validate_csrf() -> Optional['flask.Response']:
    """Check CSRF token on mutating requests.

    Returns None when the request is valid.
    Returns a redirect Response when the session is stale (e.g. SECRET_KEY
    changed after a container restart) so the user gets a fresh session
    instead of an opaque 403.
    Calls abort(403) for genuine token mismatches.
    """
    if request.method not in ('POST', 'PUT', 'DELETE', 'PATCH'):
        return None
    # /healthz is unauthenticated and has no session
    if request.endpoint == 'main.healthz':
        return None
    # REST API uses Bearer token auth — no session/CSRF needed
    if request.path.startswith('/api/v1/'):
        return None

    token = session.get('_csrf_token')
    submitted = (
        request.form.get('_csrf_token')
        or request.headers.get('X-CSRF-Token')
    )

    if not token or not submitted or token != submitted:
        # Empty session most likely means the browser held a cookie signed
        # with an old SECRET_KEY (e.g. after a container restart).
        # Flask silently drops the undecipherable cookie and creates a new
        # empty session, so _csrf_token is absent.  Redirect to login and
        # clear the stale cookie so the user gets a fresh session — much
        # friendlier than a bare 403.
        if not token:
            resp = make_response(redirect(url_for('main.login')))
            resp.delete_cookie('session')
            return resp
        abort(403, description='CSRF token missing or invalid.')

    return None
