import calendar
import json
import logging
import os
from datetime import datetime

from flask import Flask, session
from .database import init_db
from .i18n import get_translations


def _utc_to_local(dt_str: str | None) -> str:
    """Convert a UTC datetime string (SQLite CURRENT_TIMESTAMP) to local system time.

    Uses calendar.timegm + datetime.fromtimestamp so the TZ env var is
    respected via the C library — no tzdata package required.
    """
    if not dt_str:
        return dt_str or ''
    try:
        utc_dt = datetime.strptime(dt_str[:19], '%Y-%m-%d %H:%M:%S')
        ts = calendar.timegm(utc_dt.timetuple())   # UTC → Unix timestamp
        return datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')
    except ValueError:
        return dt_str


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            'ts':      self.formatTime(record, '%Y-%m-%dT%H:%M:%S'),
            'level':   record.levelname,
            'logger':  record.name,
            'msg':     record.getMessage(),
        }
        if record.exc_info:
            entry['exc'] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


def _configure_logging():
    level = os.environ.get('LOG_LEVEL', 'INFO').upper()
    handler = logging.StreamHandler()
    if os.environ.get('LOG_JSON', '0') == '1':
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            '%(asctime)s %(levelname)-8s %(name)s  %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
        ))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(getattr(logging, level, logging.INFO))


def create_app():
    _configure_logging()

    app = Flask(
        __name__,
        template_folder='templates',
        static_folder=os.path.join(os.path.dirname(__file__), '..', 'assets'),
    )

    secret_key = os.environ.get('SECRET_KEY', '')
    if not secret_key or secret_key == 'dev-secret-change-me':
        import sys
        logging.getLogger(__name__).critical(
            'SECRET_KEY is not set or uses the default value. '
            'Generate one with: openssl rand -hex 32'
        )
        sys.exit(1)
    app.secret_key = secret_key

    app.config['DATA_DIR']         = os.environ.get('DATA_DIR', '/data')
    app.config['DB_PATH']          = os.path.join(app.config['DATA_DIR'], 'companion.db')
    app.config['GLUETUN_HOST']     = os.environ.get('GLUETUN_HOST', 'host.docker.internal')
    app.config['GLUETUN_PROXY_PORT'] = int(os.environ.get('GLUETUN_PROXY_PORT', '8887'))
    app.config['GLUETUN_CONTAINER'] = os.environ.get('GLUETUN_CONTAINER', 'gluetun-airvpn')
    app.config['COMPOSE_DIR']      = os.environ.get('COMPOSE_DIR', '/compose')
    app.config['COMPOSE_PROJECT']  = os.environ.get('COMPOSE_PROJECT', '')
    # Optional Bearer token for /metrics — leave empty to allow open access (standard Prometheus)
    app.config['METRICS_TOKEN']    = os.environ.get('METRICS_TOKEN', '')

    os.makedirs(app.config['DATA_DIR'], exist_ok=True)
    init_db(app.config['DB_PATH'])

    # Reset stale benchmark flags left by a previous crash/restart
    from .database import set_setting
    set_setting('benchmark_running', '0')
    set_setting('benchmark_current_server', '')

    app.jinja_env.filters['localtime'] = _utc_to_local

    from .csrf import generate_csrf, validate_csrf
    app.jinja_env.globals['csrf_token'] = generate_csrf

    @app.before_request
    def _csrf_check():
        return validate_csrf()

    # ── Auto-detect Companion URL (for notifications) ─────────────────────
    # Captures request.url_root on real page hits and persists it to settings.
    # COMPANION_URL env var overrides auto-detection.
    # A module-level sentinel avoids a DB write on every request.
    _detected_companion_url: list[str] = ['']   # mutable container for closure

    @app.before_request
    def _capture_companion_url():
        from flask import request as _req
        from .database import set_setting
        forced = os.environ.get('COMPANION_URL', '').rstrip('/')
        if forced:
            url = forced
        else:
            # Skip background API/static calls — url_root from those may be bare
            if _req.endpoint in (None, 'static', 'main.healthz', 'main.metrics'):
                return
            # Skip REST API calls — they carry no browser context
            if _req.path.startswith('/api/v1/'):
                return
            url = _req.url_root.rstrip('/')
        if url and url != _detected_companion_url[0]:
            _detected_companion_url[0] = url
            set_setting('companion_url', url)

    @app.context_processor
    def inject_i18n():
        lang = session.get('lang', 'fr')
        return {'t': get_translations(lang), 'lang': lang}

    from .routes import bp
    app.register_blueprint(bp)

    from .api import api_bp
    app.register_blueprint(api_bp)

    from .scheduler import start_scheduler
    start_scheduler(app)

    return app
