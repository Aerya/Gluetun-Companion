import calendar
import atexit
import json
import logging
import os
import signal
import threading
import time
from datetime import datetime

from flask import Flask, session
from markupsafe import Markup
from .database import init_db
from .i18n import get_translations

_cleanup_hooks_registered = False

# Process-wide cache for server→flag and server→provider lookups used by the
# template helpers (server_flag / server_provider_icon).  Rebuilt at most every
# 5 minutes — new catalogue imports appear after the TTL expires.
_server_lookup_cache: dict = {'flags': {}, 'providers': {}, 'ts': 0.0}


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
    global _cleanup_hooks_registered
    _configure_logging()

    app = Flask(
        __name__,
        template_folder='templates',
        static_folder=os.path.join(os.path.dirname(__file__), '..', 'assets'),
    )

    secret_key = os.environ.get('SECRET_KEY', '')
    if not secret_key or secret_key in (
        'dev-secret-change-me',
        'remplacer-par-une-chaine-aleatoire-longue',
    ):
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

    # Reset stale benchmark flags left by a previous crash/restart.
    # If the app was killed mid-benchmark, 'benchmark_running' is still '1' in
    # the DB — the finally block that restarts paused containers never ran.
    # We detect this case and restart them now so the user's stack resumes.
    from .database import get_setting, set_setting
    import json as _json

    _was_running = get_setting('benchmark_running', '0') == '1'
    set_setting('benchmark_running', '0')
    set_setting('benchmark_current_server', '')
    set_setting('benchmark_next_server', '')
    set_setting('benchmark_log_lines', '[]')
    set_setting('benchmark_started_at', '')
    set_setting('benchmark_mode', '')
    set_setting('benchmark_total_servers', '0')
    set_setting('benchmark_done_servers', '0')

    if _was_running:
        _log = logging.getLogger(__name__)
        _log.warning(
            'App restarted while a benchmark was in progress — '
            'checking for containers to resume'
        )
        _pause_raw = get_setting('pause_bench_containers', '[]')
        try:
            _pause_list = _json.loads(_pause_raw)
        except Exception:
            _pause_list = []
        if _pause_list:
            _log.warning(
                'Restarting %d container(s) that were paused mid-benchmark: %s',
                len(_pause_list), ', '.join(_pause_list),
            )
            try:
                from .gluetun import start_stopped_containers
                start_stopped_containers(
                    _pause_list,
                    compose_dir=app.config.get('COMPOSE_DIR', '/compose'),
                    compose_project=app.config.get('COMPOSE_PROJECT', ''),
                    pull_set=set(),
                )
            except Exception as _exc:
                _log.error(
                    'Could not restart paused containers after app restart: %s', _exc
                )

    # A previous worker/container may have been stopped mid-sidecar test. The
    # VPN session is held by gluetun-companion-test, not by the speed sidecar,
    # so clean both temporary containers before accepting new work.
    try:
        from .gluetun import cleanup_test_containers
        cleanup_test_containers()
        logging.getLogger(__name__).info('Temporary sidecar test containers cleaned at startup')
    except Exception as _exc:
        logging.getLogger(__name__).warning(
            'Could not clean temporary sidecar test containers at startup: %s', _exc
        )

    if not _cleanup_hooks_registered:
        _cleanup_hooks_registered = True

        def _cleanup_before_exit(*_args):
            try:
                from .gluetun import cleanup_test_containers
                cleanup_test_containers()
            except Exception as _exc:
                logging.getLogger(__name__).warning(
                    'Could not clean temporary sidecar test containers before exit: %s', _exc
                )
            if _args:
                raise SystemExit(0)

        atexit.register(_cleanup_before_exit)
        if threading.current_thread() is threading.main_thread():
            for _sig in (signal.SIGTERM, signal.SIGINT):
                try:
                    signal.signal(_sig, _cleanup_before_exit)
                except Exception:
                    pass

    app.jinja_env.filters['localtime'] = _utc_to_local

    def _strip_prefix(label: str | None) -> str:
        """Strip Gluetun filter-var prefix: 'SERVER_NAMES=Menkent' → 'Menkent'."""
        if not label:
            return label or ''
        return label.split('=', 1)[-1].strip() if '=' in label else label.strip()

    app.jinja_env.filters['strip_prefix'] = _strip_prefix

    def _bw_label(mbps) -> str:
        """Format provider bandwidth/capacity stored in Mbit/s."""
        try:
            value = int(float(mbps or 0))
        except (TypeError, ValueError):
            value = 0
        if value <= 0:
            return ''
        if value >= 1000:
            gbps = value / 1000
            return f'{int(gbps)} Gbit/s' if value % 1000 == 0 else f'{gbps:.1f} Gbit/s'
        return f'{value} Mbit/s'

    app.jinja_env.filters['bw_label'] = _bw_label

    def _rel_time(value) -> str:
        """Human relative time: 'il y a 2 h' / '2 h ago', or 'dans 3 h 12' for future.

        Accepts a UTC datetime string (SQLite CURRENT_TIMESTAMP) or a datetime
        object (tz-aware or naive local).  Empty string on bad input.
        """
        if not value:
            return ''
        try:
            if isinstance(value, datetime):
                if value.tzinfo is not None:
                    now = datetime.now(tz=value.tzinfo)
                else:
                    now = datetime.now()
                delta = (value - now).total_seconds()
            else:
                utc_dt = datetime.strptime(str(value)[:19], '%Y-%m-%d %H:%M:%S')
                ts = calendar.timegm(utc_dt.timetuple())
                delta = ts - datetime.now().timestamp()
        except (ValueError, TypeError):
            return ''

        fr = session.get('lang', 'fr') == 'fr'
        future = delta > 0
        secs = abs(int(delta))
        if secs < 60:
            txt = "moins d'1 min" if fr else 'less than 1 min'
        elif secs < 3600:
            txt = f'{secs // 60} min'
        elif secs < 86400:
            h, m = secs // 3600, (secs % 3600) // 60
            txt = f'{h} h {m:02d}' if m else f'{h} h'
        else:
            d = secs // 86400
            txt = f'{d} j' if fr else f'{d} d'
        if future:
            return f'dans {txt}' if fr else f'in {txt}'
        return f'il y a {txt}' if fr else f'{txt} ago'

    app.jinja_env.filters['reltime'] = _rel_time

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

    @app.context_processor
    def inject_globals():
        """Inject app-wide flags needed in base.html (e.g. for conditional notices)."""
        from .database import get_vpn_profiles
        try:
            _profiles = get_vpn_profiles()
            _has_wg = len(_profiles) > 0
            _has_airvpn = any(p.get('provider', '').lower() == 'airvpn' for p in _profiles)
        except Exception:
            _has_wg = False
            _has_airvpn = False
        try:
            from .dns_path import get_dns_path
            _dns_path = get_dns_path(app.config['GLUETUN_CONTAINER'], session.get('lang', 'fr'))
        except Exception:
            _dns_path = {'nodes': [], 'short': '', 'detail': '', 'errors': [], 'ok': False}
        return {
            '_g_has_wg_profiles':    _has_wg,
            '_g_has_airvpn_profile': _has_airvpn,
            'dns_path':               _dns_path,
        }

    @app.context_processor
    def inject_flag_utils():
        """Inject server_flag(label) — returns a country flag emoji for a server name.

        Accepts both raw names ("Chamukuy") and formatted labels ("SERVER_NAMES=Chamukuy").
        Data is sourced from gluetun_catalogue and airvpn_snapshot.

        Lookups are cached process-wide with a 5-minute TTL — rebuilding
        them on every render is too costly with large catalogues (NordVPN
        alone is ~18k rows).
        """
        from .database import get_db

        def _flag_emoji(code: str) -> str:
            if not code or len(code) < 2:
                return ''
            c = code.upper()[:2]
            if not (c[0].isalpha() and c[1].isalpha()):
                return ''
            return chr(0x1F1E6 + ord(c[0]) - 65) + chr(0x1F1E6 + ord(c[1]) - 65)

        now = time.time()
        if now - _server_lookup_cache['ts'] > 300:
            try:
                with get_db() as _db:
                    _rows = _db.execute(
                        'SELECT name, country_code FROM gluetun_catalogue '
                        'WHERE country_code != "" '
                        'UNION SELECT name, country_code FROM airvpn_snapshot '
                        'WHERE country_code != ""'
                    ).fetchall()
                    _flags = {r['name']: r['country_code'].upper() for r in _rows}

                    # Server→provider lookup, three sources by priority
                    _prov_rows = _db.execute(
                        'SELECT name, provider FROM gluetun_catalogue WHERE provider != ""'
                    ).fetchall()
                    _providers = {r['name']: r['provider'].lower() for r in _prov_rows}
                    try:
                        for r in _db.execute('SELECT name FROM airvpn_snapshot').fetchall():
                            _providers.setdefault(r['name'], 'airvpn')
                    except Exception:
                        pass
                    try:
                        for r in _db.execute(
                            'SELECT s.name, vp.provider FROM servers s '
                            'JOIN vpn_profiles vp ON vp.id = s.vpn_profile_id '
                            'WHERE vp.provider != ""'
                        ).fetchall():
                            _providers.setdefault(r['name'], r['provider'].lower())
                    except Exception:
                        pass
                _server_lookup_cache['flags'] = _flags
                _server_lookup_cache['providers'] = _providers
                _server_lookup_cache['ts'] = now
            except Exception:
                # Keep stale cache on error; empty dicts if never built
                _server_lookup_cache['ts'] = now

        _flags = _server_lookup_cache['flags']
        _providers = _server_lookup_cache['providers']

        def server_flag_emoji(label: str | None) -> str:
            """Return the raw flag emoji for text-only contexts such as charts."""
            if not label or label in ('-', '—'):
                return ''
            # Strip filter-var prefix: "SERVER_NAMES=Chamukuy" → "Chamukuy"
            name = label.split('=', 1)[-1].strip() if '=' in label else label.strip()
            return _flag_emoji(_flags.get(name, ''))

        def server_flag(label: str | None) -> Markup | str:
            """Return an accessible flag with a browser-localised country tooltip."""
            if not label or label in ('-', '—'):
                return ''
            name = label.split('=', 1)[-1].strip() if '=' in label else label.strip()
            code = _flags.get(name, '')
            emoji = _flag_emoji(code)
            if not emoji:
                return ''
            return Markup(
                f'<span class="country-flag" data-country-code="{code}" '
                f'role="img">{emoji}</span>'
            )

        def server_provider_icon(label: str | None, size: int = 16) -> str:
            """Return an <img> for the provider icon of a server.

            Priority:
            1. Bundled SVG in /static/providers/ (best quality, offline)
            2. /provider-icon/<provider> — favicon cached server-side
               (no browser request ever leaves for a third party)
            """
            if not label or label in ('-', '—'):
                return ''
            name = label.split('=', 1)[-1].strip() if '=' in label else label.strip()
            provider = _providers.get(name, '')
            if not provider:
                return ''
            s = str(size)
            style = 'vertical-align:middle;object-fit:contain;border-radius:2px'
            from flask import url_for
            from .routes import PROVIDER_SVG_FILES, PROVIDER_FAVICON_DOMAINS
            try:
                if provider in PROVIDER_SVG_FILES:
                    url = url_for('static', filename=f'providers/{provider}.svg')
                elif provider in PROVIDER_FAVICON_DOMAINS:
                    url = url_for('main.provider_icon', provider=provider)
                else:
                    return ''
            except Exception:
                return ''
            return (
                f'<img src="{url}" alt="{provider}" '
                f'width="{s}" height="{s}" style="{style}" title="{provider}">'
            )

        return {
            'server_flag': server_flag,
            'server_flag_emoji': server_flag_emoji,
            'server_provider_icon': server_provider_icon,
        }

    from .routes import bp
    app.register_blueprint(bp)

    from .api import api_bp
    app.register_blueprint(api_bp)

    from .scheduler import start_scheduler
    start_scheduler(app)

    return app
