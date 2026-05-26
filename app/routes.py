import csv
import io
import json
import logging
import threading
import time
from functools import wraps

logger = logging.getLogger(__name__)

from flask import (
    Blueprint, Response, current_app, flash, jsonify,
    redirect, render_template, request, send_file, session, url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from .database import (
    get_db, get_setting, set_setting, compute_confidence_all,
    get_new_airvpn_servers, dismiss_new_airvpn_servers,
    get_stability_all, get_server_filtered_stats,
    get_airvpn_snapshot, update_airvpn_snapshot,
    get_vpn_profiles, get_vpn_profile,
    create_vpn_profile, update_vpn_profile, delete_vpn_profile,
    get_servers_without_profile,
    get_rotation_pools, get_rotation_pool,
    create_rotation_pool, update_rotation_pool, delete_rotation_pool,
    set_pool_next_rotation, _UNSET as _DB_UNSET,
)
from .wg_providers import WG_PROVIDERS, get_all_providers, get_fields, get_secret_field_keys
from .crypto import encrypt as crypto_encrypt, decrypt as crypto_decrypt, mask as crypto_mask
from .profiles import PROFILES, score_servers as _score_servers, score_servers_detail as _score_servers_detail
from .gluetun import (
    FILTER_VARS, FILTER_LABELS,
    get_current_filters, format_filters,
    get_public_ip, get_public_ips, get_vpn_status, switch_server,
    wait_for_vpn, restart_network_dependents,
    list_docker_containers,
)
from .i18n import flash_t, get_t
from .scheduler import (
    get_next_run, reschedule, trigger_now, trigger_quick_now,
    trigger_single_server, request_stop, _lock as scheduler_lock,
)

bp = Blueprint('main', __name__)


def _active_auto_pool_count() -> int:
    with get_db() as db:
        return db.execute(
            'SELECT COUNT(*) AS n FROM rotation_pools WHERE enabled = 1 AND auto_rotate = 1'
        ).fetchone()['n']


def _standby_benchmark_cycle_for_pools() -> None:
    set_setting('auto_benchmark', '0')
    try:
        reschedule(float(get_setting('test_interval_hours', '6') or '6'), enabled=False)
    except Exception as exc:
        logger.warning('reschedule after pool standby failed: %s', exc)

# ---------------------------------------------------------------------------
# Config export/import — allowed keys (no secrets)
# ---------------------------------------------------------------------------
_EXPORT_KEYS = frozenset({
    'test_interval_hours', 'auto_switch', 'connection_wait_seconds',
    'speedtest_samples', 'speedtest_duration', 'speedtest_retries',
    'server_timeout_secs', 'auto_exclude_failures', 'speedtest_warmup',
    'speedtest_streams', 'db_retention_days', 'sidecar_mode', 'sidecar_image',
    'sidecar_port', 'sidecar_speedtest_method', 'sidecar_iperf_fallback',
    'sidecar_proxy_fallback', 'post_switch_containers', 'pause_bench_containers',
    'auto_benchmark', 'pull_gluetun', 'pull_post_switch_containers',
    'pull_pause_bench_containers', 'pull_network_containers',
    'quick_check_mode', 'quick_check_threshold', 'scoring_window_days', 'outlier_detection',
    'weighted_score_current_pct',
    'stability_weight', 'adaptive_scheduling', 'adaptive_auto_shift',
    'notif_auto_switch', 'notif_manual_switch', 'notif_already_best',
    'notif_auto_exclude', 'notif_benchmark_end', 'notif_benchmark_failure',
    'notif_quick_check', 'notif_optimal_hour_change', 'notif_catalogue_changes',
    'catalogue_auto_add', 'notify_mention_level',
    'active_profile', 'single_stream_test', 'airvpn_new_server_notif',
    'proxy_username',
    'catalogue_import_mode', 'catalogue_import_provider',
    'catalogue_bench_on_import', 'catalogue_import_filter_type',
    'ui_lang',
    # WireGuard rotation + bench filters (non-secret, safe to export)
    'wg_rotation_mode', 'wg_rotation_threshold',
    'bench_include_types', 'airvpn_bench_max_load', 'airvpn_bench_max_users',
})

# ---------------------------------------------------------------------------
# Login rate limiting (in-memory, per remote IP)
# ---------------------------------------------------------------------------
_login_attempts: dict[str, list[float]] = {}   # ip → [timestamp, ...]
_login_lock = threading.Lock()
_RL_MAX_ATTEMPTS = 5    # max failures before lockout
_RL_WINDOW_SECS  = 300  # sliding window (5 min)
_RL_LOCKOUT_SECS = 900  # lockout duration after max failures (15 min)


def _rl_check(ip: str) -> tuple[bool, int]:
    """Return (allowed, retry_after_secs). Cleans expired entries."""
    now = time.time()
    with _login_lock:
        times = [t for t in _login_attempts.get(ip, []) if now - t < _RL_WINDOW_SECS]
        _login_attempts[ip] = times
        if len(times) >= _RL_MAX_ATTEMPTS:
            retry_after = int(_RL_LOCKOUT_SECS - (now - times[0]))
            return False, max(retry_after, 1)
        return True, 0


def _rl_record_failure(ip: str) -> None:
    now = time.time()
    with _login_lock:
        times = [t for t in _login_attempts.get(ip, []) if now - t < _RL_WINDOW_SECS]
        times.append(now)
        _login_attempts[ip] = times


def _rl_reset(ip: str) -> None:
    with _login_lock:
        _login_attempts.pop(ip, None)


_HISTORY_PER_PAGE = 50
_airvpn_cache: dict = {'data': None, 'ts': 0.0}
_AIRVPN_CACHE_TTL = 300  # 5 minutes


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('main.login'))
        return f(*args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

@bp.route('/login', methods=['GET', 'POST'])
def login():
    ip = request.remote_addr or '0.0.0.0'
    if request.method == 'POST':
        allowed, retry_after = _rl_check(ip)
        if not allowed:
            mins = (retry_after + 59) // 60
            flash(f'Trop de tentatives. Réessayez dans {mins} min.', 'danger')
            return render_template('login.html', first_login=False), 429

        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        stored_user = get_setting('admin_username', 'admin')
        stored_hash = get_setting('admin_password_hash', '')

        if not stored_hash:
            set_setting('admin_username', username)
            set_setting('admin_password_hash', generate_password_hash(password))
            session['logged_in'] = True
            session['username'] = username
            flash_t('flash_account_created', 'success')
            return redirect(url_for('main.dashboard'))

        if username == stored_user and check_password_hash(stored_hash, password):
            _rl_reset(ip)
            session['logged_in'] = True
            session['username'] = username
            return redirect(url_for('main.dashboard'))

        _rl_record_failure(ip)
        flash_t('flash_login_failed', 'danger')

    first_login = not bool(get_setting('admin_password_hash', ''))
    return render_template('login.html', first_login=first_login)


@bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('main.login'))


@bp.route('/lang/<code>')
def set_lang(code):
    if code in ('fr', 'en'):
        session['lang'] = code
        set_setting('ui_lang', code)
    return redirect(request.referrer or url_for('main.dashboard'))


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@bp.route('/')
@login_required
def dashboard():
    from .database import get_hourly_benchmark_stats
    cfg = current_app.config
    proxy_host = cfg['GLUETUN_HOST']
    proxy_port = cfg['GLUETUN_PROXY_PORT']
    container  = cfg['GLUETUN_CONTAINER']
    px_user    = get_setting('proxy_username') or None
    px_pass    = get_setting('proxy_password') or None

    vpn_status        = get_vpn_status(proxy_host, proxy_port, px_user, px_pass)
    public_ip         = get_public_ip(proxy_host, proxy_port, px_user, px_pass) if vpn_status == 'running' else None
    current_filters   = get_current_filters(container)
    current_server    = format_filters(current_filters)
    benchmark_running = get_setting('benchmark_running', '0') == '1'

    _ALLOWED_LIMITS = {10, 20, 50}
    recent_limit = request.args.get('limit', 15, type=int)
    if recent_limit not in _ALLOWED_LIMITS:
        recent_limit = 15

    with get_db() as db:
        recent_tests = db.execute(
            'SELECT st.*, vp.name AS profile_name, vp.provider AS provider_key '
            'FROM speed_tests st '
            'LEFT JOIN servers s ON s.name = st.server_name '
            'LEFT JOIN vpn_profiles vp ON vp.id = s.vpn_profile_id '
            'ORDER BY st.tested_at DESC LIMIT ?', (recent_limit,)
        ).fetchall()
        last_switch = db.execute(
            'SELECT * FROM switches ORDER BY switched_at DESC LIMIT 1'
        ).fetchone()
        recent_pool_switches = db.execute(
            '''SELECT * FROM switches
               WHERE reason LIKE 'pool_rotation:%'
               ORDER BY switched_at DESC LIMIT 5'''
        ).fetchall()
        server_count = db.execute(
            'SELECT COUNT(*) AS n FROM servers WHERE enabled = 1'
        ).fetchone()['n']
        bench_est = _bench_estimate(server_count)
        server_stats = db.execute('''
            SELECT st.server_name,
                   vp.name  AS profile_name,
                   vp.provider AS provider_key,
                   ROUND(AVG(st.download_mbps), 1) AS avg_dl,
                   ROUND(MAX(st.download_mbps), 1) AS max_dl,
                   ROUND(AVG(st.latency_ms),    0) AS avg_lat,
                   COUNT(*) AS cnt
            FROM speed_tests st
            LEFT JOIN servers s ON s.name = st.server_name
            LEFT JOIN vpn_profiles vp ON vp.id = s.vpn_profile_id
            WHERE st.success = 1
            GROUP BY st.server_name
            ORDER BY avg_dl DESC
            LIMIT 12
        ''').fetchall()
        last_cycle = db.execute(
            'SELECT * FROM benchmark_cycles ORDER BY id DESC LIMIT 1'
        ).fetchone()
        total_tests = db.execute(
            'SELECT COUNT(*) AS n FROM speed_tests WHERE success=1'
        ).fetchone()['n']

        # Sparkline for active server (last 20 successful tests, chronological)
        sparkline_labels: list[str] = []
        sparkline_dl: list[float] = []
        sparkline_ul: list[float | None] = []
        sparkline_server: str | None = None
        active_profile: dict | None = None
        if current_filters:
            sname = next(iter(current_filters.values())).split(',')[0].strip()
            sparkline_server = sname
            spark_rows = db.execute('''
                SELECT tested_at, download_mbps, upload_mbps
                FROM speed_tests
                WHERE server_name=? AND success=1 AND test_method != 'proxy_qc'
                ORDER BY tested_at DESC LIMIT 20
            ''', (sname,)).fetchall()
            # reverse to chronological order
            for r in reversed(spark_rows):
                sparkline_labels.append(r['tested_at'][5:16])
                sparkline_dl.append(r['download_mbps'] or 0)
                sparkline_ul.append(r['upload_mbps'])
            # Provider of the active server
            _prof_row = db.execute(
                'SELECT vp.name AS profile_name, vp.provider AS provider_key '
                'FROM servers s '
                'LEFT JOIN vpn_profiles vp ON vp.id = s.vpn_profile_id '
                'WHERE s.name = ?', (sname,)
            ).fetchone()
            if _prof_row and _prof_row['profile_name']:
                active_profile = dict(_prof_row)

    return render_template(
        'dashboard.html',
        vpn_status=vpn_status,
        public_ip=public_ip,
        current_server=current_server,
        active_profile=active_profile,
        recent_tests=recent_tests,
        recent_limit=recent_limit,
        last_switch=last_switch,
        recent_pool_switches=recent_pool_switches,
        server_count=server_count,
        bench_est=bench_est,
        server_stats=server_stats,
        next_run=get_next_run() if get_setting('auto_benchmark', '1') == '1' else None,
        benchmark_running=benchmark_running,
        sidecar_mode=get_setting('sidecar_mode', '1'),
        last_cycle=last_cycle,
        total_tests=total_tests,
        sparkline_server=sparkline_server,
        sparkline_labels=sparkline_labels,
        sparkline_dl=sparkline_dl,
        sparkline_ul=sparkline_ul,
        adaptive_stats=get_hourly_benchmark_stats(),
        stability=get_stability_all(),
        confidence=compute_confidence_all(),
    )


# ---------------------------------------------------------------------------
# Servers
# ---------------------------------------------------------------------------

_SERVERS_SORT = {
    # legacy keys (kept for backward compat)
    'avg_dl':  'avg_dl  DESC NULLS LAST, s.name',
    'avg_ul':  'avg_ul  DESC NULLS LAST, s.name',
    'max_dl':  'max_dl  DESC NULLS LAST, s.name',
    'latency': 'avg_lat ASC  NULLS LAST, s.name',
    'name':    's.name ASC',
    # direction-aware keys used by clickable headers
    'name_asc':       's.name ASC',
    'name_desc':      's.name DESC',
    'type_asc':       's.filter_type ASC,  s.name ASC',
    'type_desc':      's.filter_type DESC, s.name ASC',
    'ip_asc':         'last_ipv4 ASC  NULLS LAST, s.name',
    'ip_desc':        'last_ipv4 DESC NULLS LAST, s.name',
    'avg_dl_desc':    'avg_dl  DESC NULLS LAST, s.name',
    'avg_dl_asc':     'avg_dl  ASC  NULLS LAST, s.name',
    'avg_ul_desc':    'avg_ul  DESC NULLS LAST, s.name',
    'avg_ul_asc':     'avg_ul  ASC  NULLS LAST, s.name',
    'max_dl_desc':    'max_dl  DESC NULLS LAST, s.name',
    'max_dl_asc':     'max_dl  ASC  NULLS LAST, s.name',
    'latency_asc':    'avg_lat ASC  NULLS LAST, s.name',
    'latency_desc':   'avg_lat DESC NULLS LAST, s.name',
    'tests_desc':     'total_tests DESC, s.name',
    'tests_asc':      'total_tests ASC,  s.name',
    'load_desc':      'airvpn_load DESC NULLS LAST, s.name',
    'load_asc':       'airvpn_load ASC  NULLS LAST, s.name',
    'users_desc':     'airvpn_users DESC NULLS LAST, s.name',
    'users_asc':      'airvpn_users ASC  NULLS LAST, s.name',
    # stability / quality sorts
    'jitter_asc':     'avg_jitter ASC  NULLS LAST, s.name',
    'jitter_desc':    'avg_jitter DESC NULLS LAST, s.name',
    'loss_asc':       'avg_loss   ASC  NULLS LAST, s.name',
    'loss_desc':      'avg_loss   DESC NULLS LAST, s.name',
    'dns_asc':        'avg_dns    ASC  NULLS LAST, s.name',
    'dns_desc':       'avg_dns    DESC NULLS LAST, s.name',
}

_SERVERS_VALID_PER_PAGE = {10, 20, 50, 100, 0}   # 0 = all


@bp.route('/servers')
@login_required
def servers():
    from .database import get_hourly_benchmark_stats
    sort           = request.args.get('sort', 'avg_dl')
    type_filter    = request.args.get('type', '').strip()
    q              = request.args.get('q',    '').strip()
    from_date      = request.args.get('from_date', '').strip()
    to_date        = request.args.get('to_date',   '').strip()
    per_page       = request.args.get('per_page', 50, type=int)
    page           = max(1, request.args.get('page', 1, type=int))
    profile_filter = request.args.get('profile', '').strip()  # filter by vpn_profile_id
    conf_filter    = request.args.get('conf', '').strip().upper()    # HIGH / MEDIUM / LOW
    top_n          = request.args.get('top_n', 0, type=int)         # 0 = all

    if sort not in _SERVERS_SORT:
        sort = 'avg_dl'
    if per_page not in _SERVERS_VALID_PER_PAGE:
        per_page = 50
    order_sql = _SERVERS_SORT[sort]

    where_parts: list[str] = []
    having_parts: list[str] = []
    params: list = []

    if type_filter:
        where_parts.append('s.filter_type = ?')
        params.append(type_filter)
    if q:
        where_parts.append('s.name LIKE ?')
        params.append(f'%{q}%')
    if profile_filter == '__none__':
        where_parts.append('s.vpn_profile_id IS NULL')
    elif profile_filter:
        try:
            where_parts.append('s.vpn_profile_id = ?')
            params.append(int(profile_filter))
        except ValueError:
            pass

    having_params: list = []
    if from_date:
        having_parts.append("DATE(MAX(st.tested_at)) >= ?")
        having_params.append(from_date)
    if to_date:
        having_parts.append("DATE(MAX(st.tested_at)) <= ?")
        having_params.append(to_date)
    params.extend(having_params)

    where_sql  = ('WHERE '  + ' AND '.join(where_parts))  if where_parts  else ''
    having_sql = ('HAVING ' + ' AND '.join(having_parts)) if having_parts else ''

    with get_db() as db:
        rows = db.execute(f'''
            SELECT
                s.id, s.name, s.filter_type, s.enabled,
                s.consecutive_failures, s.created_at,
                s.vpn_profile_id,
                vp.name     AS vp_name,
                vp.provider AS vp_provider,
                ROUND(AVG(CASE WHEN st.success=1 THEN st.download_mbps END), 1)   AS avg_dl,
                ROUND(AVG(CASE WHEN st.success=1 THEN st.upload_mbps   END), 1)   AS avg_ul,
                ROUND(AVG(CASE WHEN st.success=1 THEN st.latency_ms    END), 0)   AS avg_lat,
                ROUND(MAX(CASE WHEN st.success=1 THEN st.download_mbps END), 1)   AS max_dl,
                ROUND(AVG(CASE WHEN st.success=1 AND st.dl_single_mbps IS NOT NULL
                               THEN st.dl_single_mbps END), 1)                    AS avg_dl_single,
                ROUND(AVG(CASE WHEN st.success=1 AND st.test_method!='proxy_qc'
                               THEN st.jitter_ms END), 1)                         AS avg_jitter,
                ROUND(AVG(CASE WHEN st.success=1 AND st.test_method!='proxy_qc'
                               THEN st.packet_loss_pct END), 1)                   AS avg_loss,
                ROUND(AVG(CASE WHEN st.success=1 AND st.test_method!='proxy_qc'
                               THEN st.dns_latency_ms END), 0)                    AS avg_dns,
                MAX(st.tested_at)                                                  AS last_tested,
                COUNT(st.id)                                                       AS total_tests,
                SUM(CASE WHEN st.success=1 THEN 1 ELSE 0 END)                     AS ok_tests,
                (SELECT public_ip   FROM speed_tests
                 WHERE server_name=s.name AND success=1 ORDER BY tested_at DESC LIMIT 1) AS last_ipv4,
                (SELECT public_ipv6 FROM speed_tests
                 WHERE server_name=s.name AND success=1 ORDER BY tested_at DESC LIMIT 1) AS last_ipv6,
                av.load  AS airvpn_load,
                av.users AS airvpn_users
            FROM servers s
            LEFT JOIN speed_tests st ON st.server_name = s.name
            LEFT JOIN airvpn_snapshot av ON av.name = s.name
            LEFT JOIN vpn_profiles vp ON vp.id = s.vpn_profile_id
            {where_sql}
            GROUP BY s.id
            {having_sql}
            ORDER BY {order_sql}
        ''', params).fetchall()
        filter_types = [r['filter_type'] for r in db.execute(
            'SELECT DISTINCT filter_type FROM servers ORDER BY filter_type'
        ).fetchall()]

    existing_names     = [r['name'] for r in rows if r['filter_type'] == 'name']
    existing_all_names = [r['name'] for r in rows]  # all filter types (for catalogue picker)

    # Current active server — read from Gluetun (best-effort, empty string on failure)
    try:
        _container = current_app.config['GLUETUN_CONTAINER']
        _filters   = get_current_filters(_container)
        active_server = next(iter(_filters.values())).split(',')[0].strip() if _filters else ''
    except Exception:
        active_server = ''

    # ── Scoring window + outlier settings ────────────────────────────────────
    _score_window  = int(get_setting('scoring_window_days', '30')) or None  # 0 → None = all
    _outlier_on    = get_setting('outlier_detection', '1') == '1'

    # ── Filtered per-server stats (avg_dl/ul/lat with window + IQR) ───────────
    _fstats = get_server_filtered_stats(_score_window, _outlier_on)
    # Save raw SQL averages (include proxy_qc) before overwriting with filtered stats.
    # These are used as a fallback for profile scoring when the filtered stats return None
    # (which happens for servers that only have proxy_qc quick-check tests, not full benchmarks).
    rows = [dict(r) for r in rows]
    for r in rows:
        r['_raw_avg_dl']  = r.get('avg_dl')
        r['_raw_avg_ul']  = r.get('avg_ul')
        r['_raw_avg_lat'] = r.get('avg_lat')

    for r in rows:
        fs = _fstats.get(r['name'])
        if fs:
            r['avg_dl']        = fs['avg_dl']
            r['avg_ul']        = fs['avg_ul']
            r['avg_lat']       = fs['avg_lat']
            r['avg_dl_single'] = fs['avg_dl_single']
            r['outliers_removed'] = fs['outliers_removed']
        else:
            r.setdefault('outliers_removed', 0)

    # ── Profile scores for display ────────────────────────────────────────────
    _stability = get_stability_all(_score_window)
    active_profile = get_setting('active_profile', 'balanced')

    # Build scoring rows: use filtered (IQR-cleaned, no proxy_qc) stats when available;
    # fall back to raw SQL averages (incl. proxy_qc) for avg_dl so that servers with
    # only quick-check data still differentiate by download speed instead of all tying.
    def _make_scoring_row(r: dict) -> dict:
        sr = dict(r)
        if sr.get('avg_dl') is None and sr.get('_raw_avg_dl') is not None:
            sr['avg_dl']  = sr['_raw_avg_dl']
            sr['avg_ul']  = sr.get('_raw_avg_ul')
            sr['avg_lat'] = sr.get('_raw_avg_lat')
        return sr

    _rows_scoring = [_make_scoring_row(r) for r in rows]

    profile_scores, profile_scores_detail = _score_servers_detail(_rows_scoring, active_profile, _stability)
    profile_best   = max(profile_scores, key=profile_scores.get) if profile_scores else None
    profile_bests = {}
    for profile_key in PROFILES:
        _scores = _score_servers(_rows_scoring, profile_key, _stability)
        profile_bests[profile_key] = max(_scores, key=_scores.get) if _scores else None

    # Detect whether all profiles converge to the same best server (= data-limited situation:
    # only download speed is available, so every profile picks the download champion).
    _unique_bests = {v for v in profile_bests.values() if v}
    profile_scores_limited = len(_unique_bests) <= 1 and bool(_unique_bests)

    # Strip internal scoring keys before passing rows to the template
    for r in rows:
        r.pop('_raw_avg_dl',  None)
        r.pop('_raw_avg_ul',  None)
        r.pop('_raw_avg_lat', None)

    # ── Confidence filter (Python-side — computed from benchmark history) ────
    _confidence_all = compute_confidence_all(_score_window)
    if conf_filter in ('HIGH', 'MEDIUM', 'LOW'):
        rows = [r for r in rows
                if _confidence_all.get(r['name'], {}).get('level') == conf_filter]

    # ── Top-N limiter (applied after sort + conf filter, before pagination) ──
    _valid_top_n = {5, 10, 20, 50}
    if top_n not in _valid_top_n:
        top_n = 0
    if top_n:
        rows = rows[:top_n]

    # ── Pagination (Python-side slice — full rows needed for scores above) ───
    total_servers = len(rows)
    if per_page == 0:
        srv_pages  = 1
        page       = 1
        page_rows  = rows
    else:
        srv_pages = max(1, (total_servers + per_page - 1) // per_page)
        page      = min(page, srv_pages)
        _offset   = (page - 1) * per_page
        page_rows = rows[_offset:_offset + per_page]

    # AirVPN new-server data (banner + badge) — only if feature enabled
    new_airvpn: list[dict] = []
    new_airvpn_names: list[str] = []
    new_airvpn_countries = ''
    if get_setting('airvpn_new_server_notif', '0') == '1':
        new_airvpn = get_new_airvpn_servers()
        new_airvpn_names = [s['name'] for s in new_airvpn]
        # Build a sorted, deduplicated country-code list for the banner (e.g. "NL, FR")
        cc_set = {(s['country_code'].upper() if s['country_code'] else s['country'])
                  for s in new_airvpn}
        new_airvpn_countries = ', '.join(sorted(cc_set))

    _all_vpn_profiles = get_vpn_profiles()
    return render_template(
        'servers.html', servers=page_rows,
        filter_labels=FILTER_LABELS, filter_vars=FILTER_VARS,
        existing_names=existing_names,
        existing_all_names=existing_all_names,
        sort=sort, type_filter=type_filter, q=q,
        from_date=from_date, to_date=to_date,
        filter_types=filter_types,
        page=page, pages=srv_pages, total=total_servers, per_page=per_page,
        active_server=active_server,
        confidence=_confidence_all,
        stability=_stability,
        new_airvpn=new_airvpn,
        new_airvpn_names=new_airvpn_names,
        new_airvpn_countries=new_airvpn_countries,
        profiles=PROFILES,
        active_profile=active_profile,
        profile_scores=profile_scores,
        profile_scores_detail=profile_scores_detail,
        profile_best=profile_best,
        profile_bests=profile_bests,
        profile_scores_limited=profile_scores_limited,
        adaptive_stats=get_hourly_benchmark_stats(),
        scoring_window_days=_score_window or 0,
        outlier_detection=_outlier_on,
        vpn_profiles=_all_vpn_profiles,
        profile_filter=profile_filter,
        conf_filter=conf_filter,
        top_n=top_n,
        wg_providers=WG_PROVIDERS,
    )


@bp.route('/servers/import', methods=['POST'])
@login_required
def import_servers():
    container_name = current_app.config['GLUETUN_CONTAINER']
    filters = get_current_filters(container_name)

    if not filters:
        flash_t('flash_no_filter', 'danger')
        return redirect(url_for('main.servers'))

    added = 0
    imported: list[str] = []
    with get_db() as db:
        for filter_type, values_str in filters.items():
            for value in values_str.split(','):
                value = value.strip()
                if not value:
                    continue
                cur = db.execute(
                    'INSERT OR IGNORE INTO servers (name, filter_type) VALUES (?, ?)',
                    (value, filter_type),
                )
                if cur.rowcount:
                    added += 1
                    imported.append(f'{FILTER_VARS[filter_type]}={value}')

    if added:
        flash_t('flash_import_done', 'success', count=added, names=', '.join(imported))
    else:
        flash_t('flash_import_exists', 'info')
    return redirect(url_for('main.servers'))


@bp.route('/servers/add', methods=['POST'])
@login_required
def add_server():
    name        = request.form.get('name', '').strip()
    filter_type = request.form.get('filter_type', 'name').strip()

    if not name:
        flash_t('flash_value_required', 'warning')
        return redirect(url_for('main.servers'))
    if filter_type not in FILTER_VARS:
        filter_type = 'name'

    with get_db() as db:
        try:
            db.execute(
                'INSERT OR IGNORE INTO servers (name, filter_type) VALUES (?, ?)',
                (name, filter_type),
            )
        except Exception as exc:
            flash(str(exc), 'danger')
            return redirect(url_for('main.servers'))

    flash_t('flash_added', 'success', entry=f'{FILTER_VARS[filter_type]}={name}')
    return redirect(url_for('main.servers'))


@bp.route('/servers/toggle/<int:server_id>', methods=['POST'])
@login_required
def toggle_server(server_id):
    with get_db() as db:
        db.execute('UPDATE servers SET enabled = 1 - enabled WHERE id = ?', (server_id,))
    return redirect(url_for('main.servers'))


@bp.route('/servers/delete/<int:server_id>', methods=['POST'])
@login_required
def delete_server(server_id):
    with get_db() as db:
        db.execute('DELETE FROM servers WHERE id = ?', (server_id,))
    flash_t('flash_server_deleted', 'success')
    return redirect(url_for('main.servers'))


@bp.route('/servers/assign-profile/<int:server_id>', methods=['POST'])
@login_required
def assign_server_profile(server_id):
    """Assign (or unassign) a VPN profile to a single server."""
    pid_raw = request.form.get('vpn_profile_id', '').strip()
    with get_db() as db:
        if pid_raw == '' or pid_raw == '0':
            db.execute('UPDATE servers SET vpn_profile_id = NULL WHERE id = ?', (server_id,))
        else:
            try:
                pid = int(pid_raw)
                db.execute('UPDATE servers SET vpn_profile_id = ? WHERE id = ?', (pid, server_id))
            except ValueError:
                pass
    return redirect(request.referrer or url_for('main.servers'))


@bp.route('/servers/bulk-assign-profile', methods=['POST'])
@login_required
def bulk_assign_server_profile():
    """Assign all servers that have no VPN profile to a given profile."""
    pid_raw = request.form.get('vpn_profile_id', '').strip()
    try:
        pid = int(pid_raw)
        if pid <= 0:
            raise ValueError
    except ValueError:
        flash('Profil invalide.', 'danger')
        return redirect(url_for('main.settings'))
    with get_db() as db:
        # Verify the profile exists
        row = db.execute('SELECT id FROM vpn_profiles WHERE id = ?', (pid,)).fetchone()
        if not row:
            flash('Profil introuvable.', 'danger')
            return redirect(url_for('main.settings'))
        cur = db.execute(
            'UPDATE servers SET vpn_profile_id = ? WHERE vpn_profile_id IS NULL',
            (pid,),
        )
        count = cur.rowcount
    flash(f'{count} serveur(s) assigné(s) au profil.', 'success')
    return redirect(url_for('main.settings'))


@bp.route('/servers/switch/<int:server_id>', methods=['POST'])
@login_required
def manual_switch(server_id):
    cfg = current_app.config
    with get_db() as db:
        row = db.execute(
            'SELECT s.name, s.filter_type, s.vpn_profile_id, '
            '       vp.provider AS vp_provider '
            'FROM servers s '
            'LEFT JOIN vpn_profiles vp ON vp.id = s.vpn_profile_id '
            'WHERE s.id = ?', (server_id,)
        ).fetchone()
    if not row:
        flash('Serveur introuvable.', 'danger')
        return redirect(url_for('main.servers'))

    container   = cfg['GLUETUN_CONTAINER']
    compose_dir = cfg['COMPOSE_DIR']
    project     = cfg.get('COMPOSE_PROJECT', '')
    proxy_host  = cfg.get('GLUETUN_HOST', 'gluetun')
    proxy_port  = int(cfg.get('GLUETUN_PROXY_PORT', 8888))
    proxy_user  = get_setting('proxy_username') or None
    proxy_pass  = get_setting('proxy_password') or None
    wait_secs   = int(get_setting('connection_wait_seconds', '45'))
    lang        = get_setting('ui_lang', 'fr')

    from_label = format_filters(get_current_filters(container))

    # Capture the old server's IP before switching
    from_ipv4, from_ipv6 = get_public_ips(proxy_host, proxy_port, proxy_user, proxy_pass)

    # Build WireGuard profile dict if this server has an assigned VPN profile (P1-3)
    _manual_wg_profile = None
    if row['vpn_profile_id'] is not None:
        from .database import get_vpn_profile as _get_vp_manual
        from .crypto import decrypt as _dec_manual, is_encrypted as _is_enc_manual
        from .wg_providers import WG_PROVIDERS as _WGP_manual
        _mp = _get_vp_manual(row['vpn_profile_id'])
        if _mp:
            _mp_prov_key = _mp['provider']
            _mp_prov_def = _WGP_manual.get(_mp_prov_key, {})
            _mp_compose_prov = _mp_prov_def.get('compose_provider', _mp_prov_key)
            _mp_vars: dict[str, str] = {}
            for _k, _v in _mp['vars'].items():
                try:
                    _mp_vars[_k] = _dec_manual(_v) if _is_enc_manual(_v) else _v
                except ValueError:
                    _mp_vars[_k] = ''
            _manual_wg_profile = {'compose_provider': _mp_compose_prov, 'vars': _mp_vars}

    ok, err = switch_server(
        row['name'], row['filter_type'],
        container, compose_dir, project,
        wg_profile=_manual_wg_profile,
    )
    to_label = f"{FILTER_VARS[row['filter_type']]}={row['name']}"
    with get_db() as db:
        switch_id = db.execute(
            'INSERT INTO switches (from_server, to_server, reason, success) VALUES (?, ?, ?, ?)',
            (from_label, to_label, 'manual', int(ok)),
        ).lastrowid
    if ok:
        flash_t('flash_switched', 'success', to=to_label)

        # In the background: wait for VPN, get new IPs, recreate dependents, then notify.
        app = current_app._get_current_object()

        def _bg_restart():
            with app.app_context():
                vpn_ok, elapsed = wait_for_vpn(
                    proxy_host, proxy_port,
                    timeout=wait_secs,
                    proxy_user=proxy_user,
                    proxy_password=proxy_pass,
                )
                if vpn_ok:
                    restarted, _ = restart_network_dependents(
                        container, compose_dir, project,
                    )
                    logger.info(
                        'Manual switch: VPN up in %.0fs — recreated %d network dependent(s): %s',
                        elapsed, len(restarted), ', '.join(restarted) or 'none',
                    )
                    to_ipv4, to_ipv6 = get_public_ips(
                        proxy_host, proxy_port, proxy_user, proxy_pass,
                    )
                else:
                    logger.warning(
                        'Manual switch: VPN not ready after %.0fs — network dependents NOT recreated',
                        elapsed,
                    )
                    to_ipv4, to_ipv6 = None, None

                # Update the switch row with IPs and connection time now that we have them
                with get_db() as db:
                    db.execute(
                        'UPDATE switches SET connect_secs=?, to_ipv4=?, to_ipv6=? WHERE id=?',
                        (elapsed if vpn_ok else None, to_ipv4, to_ipv6, switch_id),
                    )

                if get_setting('notif_manual_switch', '0') == '1':
                    from .notify import send_switch_notification
                    send_switch_notification(
                        from_server=from_label,
                        to_server=to_label,
                        from_mbps=None,
                        to_mbps=None,
                        connect_secs=elapsed if vpn_ok else None,
                        to_ipv4=to_ipv4,
                        to_ipv6=to_ipv6,
                        reason='manual',
                        discord_url=get_setting('discord_webhook_url') or None,
                        apprise_urls=get_setting('apprise_urls') or None,
                        lang=lang,
                        companion_url=get_setting('companion_url') or None,
                        from_ipv4=from_ipv4,
                        from_ipv6=from_ipv6,
                        mention=get_setting('notify_mention', '').strip() or None,
                        mention_level=get_setting('notify_mention_level', 'critical'),
                        alert_type='manual_switch',
                    )

        threading.Thread(target=_bg_restart, daemon=True, name='manual-switch-net').start()
    else:
        flash_t('flash_switch_failed', 'danger', err=err)
    return redirect(url_for('main.servers'))


@bp.route('/servers/test/<int:server_id>', methods=['POST'])
@login_required
def test_server_now(server_id):
    if get_setting('benchmark_running', '0') == '1':
        flash_t('flash_benchmark_running', 'warning')
        return redirect(url_for('main.servers'))

    with get_db() as db:
        row = db.execute('SELECT name, filter_type FROM servers WHERE id=?', (server_id,)).fetchone()
    if not row:
        flash_t('flash_server_not_found', 'danger')
        return redirect(url_for('main.servers'))

    trigger_single_server(
        current_app._get_current_object(), row['name'], row['filter_type']
    )
    flash_t('flash_test_started', 'info', name=row['name'])
    return redirect(url_for('main.servers'))


@bp.route('/api/airvpn-new-servers/dismiss', methods=['POST'])
@login_required
def api_airvpn_dismiss():
    """Mark all tracked new AirVPN servers as dismissed (user closed the banner)."""
    dismiss_new_airvpn_servers()
    return jsonify({'status': 'ok'})


@bp.route('/servers/add-bulk', methods=['POST'])
@login_required
def add_servers_bulk():
    data        = request.get_json(silent=True) or {}
    names       = data.get('names', [])
    filter_type = data.get('filter_type', 'name')
    if filter_type not in FILTER_VARS:
        filter_type = 'name'
    added = skipped = 0
    with get_db() as db:
        for name in names:
            name = name.strip()
            if not name:
                continue
            cur = db.execute(
                'INSERT OR IGNORE INTO servers (name, filter_type) VALUES (?, ?)',
                (name, filter_type),
            )
            if cur.rowcount:
                added += 1
            else:
                skipped += 1
    return jsonify({'added': added, 'skipped': skipped})


# ---------------------------------------------------------------------------
# History — hourly patterns
# ---------------------------------------------------------------------------

@bp.route('/history/patterns')
@login_required
def history_patterns():
    server_filter = request.args.get('server', '').strip()

    with get_db() as db:
        server_names = [r['server_name'] for r in db.execute(
            'SELECT DISTINCT server_name FROM speed_tests WHERE success=1 ORDER BY server_name'
        ).fetchall()]

        raw_rows = []
        if server_filter:
            # datetime(tested_at, 'localtime') converts UTC→local using the system TZ env var
            raw_rows = db.execute('''
                SELECT strftime('%H', datetime(tested_at, 'localtime')) AS hour,
                       ROUND(AVG(download_mbps),   1) AS avg_dl,
                       ROUND(AVG(upload_mbps),     1) AS avg_ul,
                       ROUND(AVG(jitter_ms),       1) AS avg_jitter,
                       ROUND(AVG(packet_loss_pct), 1) AS avg_loss,
                       ROUND(AVG(dns_latency_ms),  1) AS avg_dns,
                       COUNT(*) AS n
                FROM speed_tests
                WHERE server_name = ? AND success = 1 AND test_method != 'proxy_qc'
                GROUP BY hour
                ORDER BY hour
            ''', (server_filter,)).fetchall()

    # Fill all 24 hours (missing hours → null)
    hours_map = {r['hour']: r for r in raw_rows}
    hourly_data = []
    for h in range(24):
        hkey = f'{h:02d}'
        r = hours_map.get(hkey)
        hourly_data.append({
            'hour':       hkey,
            'avg_dl':     r['avg_dl']     if r else None,
            'avg_ul':     r['avg_ul']     if r else None,
            'avg_jitter': r['avg_jitter'] if r else None,
            'avg_loss':   r['avg_loss']   if r else None,
            'avg_dns':    r['avg_dns']    if r else None,
            'n':          r['n']          if r else 0,
        })

    measured    = [h for h in hourly_data if h['avg_dl'] is not None]
    total_tests = sum(h['n'] for h in hourly_data)
    has_data    = bool(measured) and total_tests >= 7
    best_hour   = max(measured, key=lambda h: h['avg_dl']) if has_data else None
    worst_hour  = min(measured, key=lambda h: h['avg_dl']) if has_data else None

    return render_template(
        'patterns.html',
        server_names=server_names,
        server_filter=server_filter,
        hourly_data=hourly_data,
        has_data=has_data,
        total_tests=total_tests,
        best_hour=best_hour,
        worst_hour=worst_hour,
    )


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

_SORT_COLS = {
    'date_desc':      'tested_at DESC',
    'date_asc':       'tested_at ASC',
    'server_asc':     'server_name ASC,  tested_at DESC',
    'server_desc':    'server_name DESC, tested_at DESC',
    'dl_desc':        'download_mbps DESC NULLS LAST',
    'dl_asc':         'download_mbps ASC  NULLS LAST',
    'ul_desc':        'upload_mbps   DESC NULLS LAST',
    'ul_asc':         'upload_mbps   ASC  NULLS LAST',
    'latency_asc':    'latency_ms    ASC  NULLS LAST',
    'latency_desc':   'latency_ms    DESC NULLS LAST',
    'ip_asc':         'public_ip     ASC  NULLS LAST',
    'ip_desc':        'public_ip     DESC NULLS LAST',
    'jitter_asc':     'jitter_ms     ASC  NULLS LAST',
    'jitter_desc':    'jitter_ms     DESC NULLS LAST',
    'loss_asc':       'packet_loss_pct ASC  NULLS LAST',
    'loss_desc':      'packet_loss_pct DESC NULLS LAST',
    'dns_asc':        'dns_latency_ms ASC  NULLS LAST',
    'dns_desc':       'dns_latency_ms DESC NULLS LAST',
    'method_asc':     'test_method   ASC,  tested_at DESC',
    'method_desc':    'test_method   DESC, tested_at DESC',
    'status_asc':     'success ASC,  tested_at DESC',
    'status_desc':    'success DESC, tested_at DESC',
}

@bp.route('/history')
@login_required
def history():
    from .database import get_hourly_benchmark_stats
    page          = max(1, request.args.get('page', 1, type=int))
    sort          = request.args.get('sort', 'date_desc')
    server_filter = request.args.get('server', '').strip()
    method_filter = request.args.get('method', '')
    from_date     = request.args.get('from_date', '').strip()
    to_date       = request.args.get('to_date', '').strip()
    show_failed   = request.args.get('show_failed', '') == '1'

    if sort not in _SORT_COLS:
        sort = 'date_desc'
    order_sql = _SORT_COLS[sort]

    where_parts: list[str] = []
    params: list = []
    if not show_failed:
        where_parts.append('success = 1')
    if server_filter:
        where_parts.append('server_name = ?')
        params.append(server_filter)
    if method_filter in ('proxy', 'sidecar'):
        where_parts.append('test_method = ?')
        params.append(method_filter)
    if from_date:
        where_parts.append("DATE(tested_at) >= ?")
        params.append(from_date)
    if to_date:
        where_parts.append("DATE(tested_at) <= ?")
        params.append(to_date)
    where_sql = ('WHERE ' + ' AND '.join(where_parts)) if where_parts else ''

    offset = (page - 1) * _HISTORY_PER_PAGE

    with get_db() as db:
        total = db.execute(
            f'SELECT COUNT(*) AS n FROM speed_tests {where_sql}', params
        ).fetchone()['n']
        tests = db.execute(
            f'''SELECT st.*,
                       s.vpn_profile_id,
                       vp.name     AS vp_name,
                       vp.provider AS vp_provider
                FROM speed_tests st
                LEFT JOIN servers s        ON s.name = st.server_name
                LEFT JOIN vpn_profiles vp  ON vp.id  = s.vpn_profile_id
                {where_sql}
                ORDER BY {order_sql} LIMIT ? OFFSET ?''',
            params + [_HISTORY_PER_PAGE, offset],
        ).fetchall()
        per_server = db.execute('''
            SELECT server_name,
                   ROUND(AVG(download_mbps), 1) AS avg_dl,
                   ROUND(MIN(download_mbps), 1) AS min_dl,
                   ROUND(MAX(download_mbps), 1) AS max_dl,
                   ROUND(AVG(upload_mbps),   1) AS avg_ul,
                   COUNT(*) AS cnt
            FROM speed_tests WHERE success = 1
            GROUP BY server_name
            ORDER BY avg_dl DESC
        ''').fetchall()
        server_names = [r['server_name'] for r in db.execute(
            'SELECT DISTINCT server_name FROM speed_tests ORDER BY server_name'
        ).fetchall()]
        hist_vpn_profiles = get_vpn_profiles()
        # Chronological data for timeline chart (only when a server is selected)
        timeline_data = []
        if server_filter:
            timeline_data = db.execute('''
                SELECT tested_at, download_mbps, upload_mbps
                FROM speed_tests
                WHERE server_name = ? AND success = 1
                ORDER BY tested_at ASC
                LIMIT 200
            ''', (server_filter,)).fetchall()
        # Last completed benchmark cycle (for duration display)
        last_bench_cycle = db.execute(
            '''SELECT started_at, finished_at, duration_secs, servers_tested, best_server
               FROM benchmark_cycles
               WHERE finished_at IS NOT NULL
               ORDER BY id DESC LIMIT 1'''
        ).fetchone()
        recent_pool_switches = db.execute(
            '''SELECT * FROM switches
               WHERE reason LIKE 'pool_rotation:%'
               ORDER BY switched_at DESC LIMIT 10'''
        ).fetchall()

    pages = max(1, (total + _HISTORY_PER_PAGE - 1) // _HISTORY_PER_PAGE)
    return render_template(
        'history.html',
        tests=tests, per_server=per_server,
        page=page, pages=pages, total=total,
        sort=sort, server_filter=server_filter, method_filter=method_filter,
        from_date=from_date, to_date=to_date,
        show_failed=show_failed,
        last_bench_cycle=last_bench_cycle,
        recent_pool_switches=recent_pool_switches,
        server_names=server_names,
        timeline_data=timeline_data,
        confidence=compute_confidence_all(),
        stability=get_stability_all(),
        adaptive_stats=get_hourly_benchmark_stats(),
        vpn_profiles=hist_vpn_profiles,
        wg_providers=get_all_providers(),
    )


@bp.route('/history/export.csv')
@login_required
def history_export():
    with get_db() as db:
        rows = db.execute(
            'SELECT * FROM speed_tests ORDER BY tested_at DESC'
        ).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'id', 'server_name', 'download_mbps', 'upload_mbps', 'latency_ms',
        'public_ip', 'public_ipv6', 'success', 'error_msg', 'tested_at',
    ])
    for r in rows:
        writer.writerow([
            r['id'], r['server_name'], r['download_mbps'], r['upload_mbps'],
            r['latency_ms'], r['public_ip'], r['public_ipv6'],
            r['success'], r['error_msg'], r['tested_at'],
        ])

    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=speedtest_history.csv'},
    )


# ---------------------------------------------------------------------------
# Switches log
# ---------------------------------------------------------------------------

@bp.route('/switches')
@login_required
def switches():
    from_date       = request.args.get('from_date',       '').strip()
    to_date         = request.args.get('to_date',         '').strip()
    status_filter   = request.args.get('status_filter',   '')
    reason_filter   = request.args.get('reason_filter',   '').strip()
    provider_filter = request.args.get('provider_filter', '').strip()

    where_parts: list[str] = []
    params: list = []
    if from_date:
        where_parts.append("DATE(sw.switched_at) >= ?")
        params.append(from_date)
    if to_date:
        where_parts.append("DATE(sw.switched_at) <= ?")
        params.append(to_date)
    if status_filter == 'ok':
        where_parts.append("sw.success = 1")
    elif status_filter == 'fail':
        where_parts.append("sw.success = 0")
    if reason_filter:
        where_parts.append("sw.reason = ?")
        params.append(reason_filter)
    if provider_filter:
        try:
            _pid = int(provider_filter)
            where_parts.append("s_to.vpn_profile_id = ?")
            params.append(_pid)
        except ValueError:
            provider_filter = ''
    where_sql = ('WHERE ' + ' AND '.join(where_parts)) if where_parts else ''

    with get_db() as db:
        rows = db.execute(
            f'''SELECT sw.*,
                       vp_to.name   AS to_profile_name,
                       vp_from.name AS from_profile_name
                FROM switches sw
                LEFT JOIN servers s_to    ON s_to.name    = sw.to_server
                LEFT JOIN vpn_profiles vp_to   ON vp_to.id   = s_to.vpn_profile_id
                LEFT JOIN servers s_from  ON s_from.name  = sw.from_server
                LEFT JOIN vpn_profiles vp_from ON vp_from.id = s_from.vpn_profile_id
                {where_sql}
                ORDER BY sw.switched_at DESC LIMIT 500''',
            params,
        ).fetchall()
        reason_values = [r['reason'] for r in db.execute(
            'SELECT DISTINCT reason FROM switches WHERE reason IS NOT NULL AND reason != "" ORDER BY reason'
        ).fetchall()]
        vpn_profiles = get_vpn_profiles()

    total = len(rows)
    ok_count = sum(1 for r in rows if r['success'])
    failed_count = total - ok_count
    gains = [
        (r['to_mbps'] or 0) - (r['from_mbps'] or 0)
        for r in rows
        if r['from_mbps'] is not None and r['to_mbps'] is not None
    ]
    avg_gain = round(sum(gains) / len(gains), 1) if gains else None
    best_gain = round(max(gains), 1) if gains else None

    return render_template(
        'switches.html',
        switches=rows,
        from_date=from_date,
        to_date=to_date,
        status_filter=status_filter,
        reason_filter=reason_filter,
        provider_filter=provider_filter,
        reason_values=reason_values,
        vpn_profiles=vpn_profiles,
        total=total,
        ok_count=ok_count,
        failed_count=failed_count,
        avg_gain=avg_gain,
        best_gain=best_gain,
    )




# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'save_planning':
            active_auto_pools = _active_auto_pool_count()
            set_setting('test_interval_hours', request.form.get('interval', '6'))
            auto_bm = bool(request.form.get('auto_benchmark'))
            set_setting('auto_benchmark', '0' if active_auto_pools else ('1' if auto_bm else '0'))
            set_setting('quick_check_mode',    '1' if request.form.get('quick_check_mode') else '0')
            try:
                qct = float(request.form.get('quick_check_threshold', '15'))
                set_setting('quick_check_threshold', str(max(1.0, min(qct, 100.0))))
            except ValueError:
                pass
            set_setting('adaptive_scheduling', '1' if request.form.get('adaptive_scheduling') else '0')
            set_setting('adaptive_auto_shift', '1' if request.form.get('adaptive_auto_shift') else '0')
            # Bench pre-filters
            _types_selected = request.form.getlist('bench_include_types')
            _valid_types = {'name', 'country', 'city', 'region', 'hostname'}
            _types_clean = [t for t in _types_selected if t in _valid_types]
            set_setting('bench_include_types', json.dumps(_types_clean))
            try:
                _max_load = int(request.form.get('airvpn_bench_max_load', '0') or '0')
                set_setting('airvpn_bench_max_load', str(max(0, min(_max_load, 100))))
            except ValueError:
                pass
            try:
                _max_users = int(request.form.get('airvpn_bench_max_users', '0') or '0')
                set_setting('airvpn_bench_max_users', str(max(0, _max_users)))
            except ValueError:
                pass
            reschedule(float(request.form.get('interval', '6')), enabled=(auto_bm and not active_auto_pools))
            if active_auto_pools and auto_bm:
                flash_t('flash_pool_cycle_standby', 'warning')
            else:
                flash_t('flash_settings_saved', 'success')

        elif action == 'save_speed':
            set_setting('speedtest_duration',  request.form.get('speedtest_duration', '8'))
            set_setting('speedtest_samples',   request.form.get('speedtest_samples', '3'))
            set_setting('speedtest_streams',   request.form.get('speedtest_streams', '4'))
            set_setting('speedtest_warmup',    '1' if request.form.get('speedtest_warmup') else '0')
            set_setting('single_stream_test',  '1' if request.form.get('single_stream_test') else '0')
            flash_t('flash_settings_saved', 'success')

        elif action == 'save_vpn':
            set_setting('connection_wait_seconds', request.form.get('wait_secs', '45'))
            set_setting('speedtest_retries',       request.form.get('speedtest_retries', '2'))
            set_setting('server_timeout_secs',     request.form.get('server_timeout_secs', '300'))
            set_setting('auto_exclude_failures',   request.form.get('auto_exclude_failures', '5'))
            flash_t('flash_settings_saved', 'success')

        elif action == 'save_switch':
            set_setting('auto_switch',   '1' if request.form.get('auto_switch') else '0')
            try:
                wsp = float(request.form.get('weighted_score_current_pct', '65'))
                set_setting('weighted_score_current_pct', str(max(1.0, min(wsp, 99.0))))
            except ValueError:
                pass
            try:
                sw = float(request.form.get('stability_weight', '30'))
                set_setting('stability_weight', str(int(max(0.0, min(sw, 100.0)))))
            except ValueError:
                pass
            _ap = request.form.get('active_profile', 'balanced')
            if _ap in PROFILES:
                set_setting('active_profile', _ap)
            try:
                _win = int(request.form.get('scoring_window_days', '30'))
                if _win in (0, 7, 14, 30):
                    set_setting('scoring_window_days', str(_win))
            except ValueError:
                pass
            set_setting('outlier_detection', '1' if request.form.get('outlier_detection') else '0')
            flash_t('flash_settings_saved', 'success')

        # Legacy catch-all (kept for backward compat / direct API calls)
        elif action == 'save':
            flash_t('flash_settings_saved', 'success')

        elif action == 'save_api_token':
            import secrets as _sec
            action_type = request.form.get('api_token_action', '')
            if action_type == 'generate':
                new_token = _sec.token_hex(32)
                set_setting('api_token', new_token)
            elif action_type == 'clear':
                set_setting('api_token', '')
            flash_t('flash_settings_saved', 'success')

        elif action == 'db_retention':
            set_setting('db_retention_days', request.form.get('db_retention_days', '30'))
            flash_t('flash_retention_saved', 'success')

        elif action == 'notifications':
            set_setting('discord_webhook_url',    request.form.get('discord_webhook_url', '').strip())
            set_setting('apprise_urls',           request.form.get('apprise_urls', '').strip())
            set_setting('airvpn_new_server_notif','1' if request.form.get('airvpn_new_server_notif') else '0')
            # Per-type toggles
            for _k in ('notif_auto_switch', 'notif_manual_switch', 'notif_already_best',
                       'notif_auto_exclude', 'notif_benchmark_end', 'notif_benchmark_failure',
                       'notif_quick_check', 'notif_optimal_hour_change', 'notif_catalogue_changes'):
                set_setting(_k, '1' if request.form.get(_k) else '0')
            # Global mention
            set_setting('notify_mention',       request.form.get('notify_mention', '').strip())
            set_setting('notify_mention_level', request.form.get('notify_mention_level', 'critical'))
            flash_t('flash_notifications_saved', 'success')

        elif action == 'credentials':
            new_user = request.form.get('username', '').strip()
            new_pass = request.form.get('password', '')
            if new_user:
                set_setting('admin_username', new_user)
            if new_pass:
                set_setting('admin_password_hash', generate_password_hash(new_pass))
            flash_t('flash_credentials_saved', 'success')

        elif action == 'proxy_credentials':
            set_setting('proxy_username', request.form.get('proxy_username', '').strip())
            set_setting('proxy_password', request.form.get('proxy_password', ''))
            flash_t('flash_proxy_saved', 'success')

        elif action == 'sidecar':
            set_setting('sidecar_mode',             '1' if request.form.get('sidecar_mode') else '0')
            set_setting('sidecar_image',            request.form.get('sidecar_image', '').strip()
                                                    or 'ghcr.io/aerya/gluetun-companion-sidecar:latest')
            set_setting('sidecar_port',             request.form.get('sidecar_port', '8766').strip() or '8766')
            set_setting('sidecar_speedtest_method', request.form.get('sidecar_speedtest_method', 'dual'))
            set_setting('sidecar_iperf_fallback',   '1' if request.form.get('sidecar_iperf_fallback') else '0')
            set_setting('sidecar_proxy_fallback',   '1' if request.form.get('sidecar_proxy_fallback') else '0')
            flash_t('flash_sidecar_saved', 'success')

        elif action == 'catalogue':
            set_setting('catalogue_import_mode',          request.form.get('catalogue_import_mode', 'active'))
            set_setting('catalogue_import_provider',      request.form.get('catalogue_import_provider', '').strip())
            set_setting('catalogue_bench_on_import',      '1' if request.form.get('catalogue_bench_on_import') else '0')
            set_setting('catalogue_import_filter_type',   request.form.get('catalogue_import_filter_type', 'all'))
            set_setting('catalogue_auto_add',             '1' if request.form.get('catalogue_auto_add') else '0')
            flash_t('flash_catalogue_saved', 'success')

        elif action == 'post_switch':
            containers = [c.strip() for c in request.form.getlist('post_switch_containers') if c.strip()]
            pull_set   = set(request.form.getlist('pull_post_switch_containers'))
            set_setting('post_switch_containers',      json.dumps(containers))
            set_setting('pull_post_switch_containers', json.dumps([n for n in containers if n in pull_set]))
            flash_t('flash_post_switch_saved', 'success')

        elif action == 'pause_bench':
            containers = [c.strip() for c in request.form.getlist('pause_bench_containers') if c.strip()]
            pull_set   = set(request.form.getlist('pull_pause_bench_containers'))
            set_setting('pause_bench_containers',      json.dumps(containers))
            set_setting('pull_pause_bench_containers', json.dumps([n for n in containers if n in pull_set]))
            flash_t('flash_pause_bench_saved', 'success')

        elif action == 'pull_network':
            set_setting('pull_gluetun', '1' if request.form.get('pull_gluetun') else '0')
            pull_list = [n.strip() for n in request.form.getlist('pull_network_containers') if n.strip()]
            set_setting('pull_network_containers', json.dumps(pull_list))
            flash_t('flash_post_switch_saved', 'success')  # reuse generic "saved" flash

        # ── WireGuard profiles ──────────────────────────────────────────────
        elif action == 'wg_profile_save':
            _provider = request.form.get('wg_provider', '').strip()
            _name     = request.form.get('wg_profile_name', '').strip()
            _pid_raw  = request.form.get('wg_profile_id', '').strip()
            _enabled  = bool(request.form.get('wg_enabled'))
            _rotation = bool(request.form.get('wg_rotation_allowed'))
            try:
                _priority = int(request.form.get('wg_rotation_priority', '0') or '0')
            except ValueError:
                _priority = 0

            if _provider not in WG_PROVIDERS or not _name:
                flash('Fournisseur ou nom de profil invalide.', 'danger')
            else:
                _secret_keys = get_secret_field_keys(_provider)
                _all_fields  = get_fields(_provider)
                _vars: dict[str, str] = {}
                for _f in _all_fields:
                    _fkey = _f['key']
                    _val  = request.form.get(f'wg_var_{_fkey}', '').strip()
                    if not _val and _pid_raw:
                        # Edit mode: keep existing value if field left empty
                        continue
                    if _val:
                        _vars[_fkey] = crypto_encrypt(_val) if _fkey in _secret_keys else _val

                # ── Per-profile sidecar key fields ──────────────────────────
                _sc_pk_raw  = request.form.get('wg_sidecar_pk_profile', '').strip()
                _sc_addr    = request.form.get('wg_sidecar_addr_profile', '').strip()
                _sc_psk_raw = request.form.get('wg_sidecar_psk_profile', '').strip()
                _sc_reuse   = bool(request.form.get('wg_sidecar_reuse_profile'))
                # Encrypt secrets when provided; empty = keep existing (handled below)
                _sc_pk  = crypto_encrypt(_sc_pk_raw)  if _sc_pk_raw  else None
                _sc_psk = crypto_encrypt(_sc_psk_raw) if _sc_psk_raw else None
                # Addresses are not secret
                _sc_addr_val = _sc_addr if _sc_addr else None   # None = keep existing in edit mode

                if _pid_raw:
                    # Update existing profile
                    try:
                        _pid = int(_pid_raw)
                    except ValueError:
                        _pid = 0
                    if _pid and update_vpn_profile(
                        _pid,
                        name=_name,
                        provider=_provider,
                        vars=_vars if _vars else None,
                        enabled=_enabled,
                        rotation_allowed=_rotation,
                        rotation_priority=_priority,
                        sidecar_private_key=_sc_pk,
                        sidecar_addresses=_sc_addr_val,
                        sidecar_preshared_key=_sc_psk,
                        sidecar_reuse_profile=_sc_reuse,
                    ):
                        flash_t('flash_settings_saved', 'success')
                    else:
                        flash('Profil introuvable.', 'danger')
                else:
                    # Create new profile
                    create_vpn_profile(
                        name=_name,
                        provider=_provider,
                        vars=_vars,
                        enabled=_enabled,
                        rotation_allowed=_rotation,
                        rotation_priority=_priority,
                        sidecar_private_key=_sc_pk  or '',
                        sidecar_addresses=_sc_addr_val or '',
                        sidecar_preshared_key=_sc_psk or '',
                        sidecar_reuse_profile=_sc_reuse,
                    )
                    flash_t('flash_settings_saved', 'success')

        elif action == 'wg_profile_delete':
            try:
                _pid = int(request.form.get('wg_profile_id', '0') or '0')
            except ValueError:
                _pid = 0
            if _pid and delete_vpn_profile(_pid):
                flash_t('flash_settings_saved', 'success')
            else:
                flash('Profil introuvable.', 'danger')

        elif action == 'save_wg_rotation':
            _mode = request.form.get('wg_rotation_mode', 'none')
            if _mode in ('none', 'free', 'conditional'):
                set_setting('wg_rotation_mode', _mode)
            try:
                _thr = int(request.form.get('wg_rotation_threshold', '10') or '10')
                set_setting('wg_rotation_threshold', str(max(1, min(_thr, 100))))
            except ValueError:
                pass
            flash_t('flash_settings_saved', 'success')

        return redirect(url_for('main.settings'))

    cfg = {
        'interval':              get_setting('test_interval_hours', '6'),
        'auto_benchmark':        get_setting('auto_benchmark', '1'),
        'auto_sw':               get_setting('auto_switch', '1'),
        'wait_secs':             get_setting('connection_wait_seconds', '45'),
        'username':              get_setting('admin_username', 'admin'),
        'proxy_username':        get_setting('proxy_username', ''),
        'proxy_password':        get_setting('proxy_password', ''),
        'speedtest_samples':     get_setting('speedtest_samples', '3'),
        'speedtest_duration':    get_setting('speedtest_duration', '8'),
        'speedtest_retries':     get_setting('speedtest_retries', '2'),
        'server_timeout_secs':   get_setting('server_timeout_secs', '300'),
        'auto_exclude_failures': get_setting('auto_exclude_failures', '5'),
        'speedtest_warmup':      get_setting('speedtest_warmup', '1'),
        'speedtest_streams':     get_setting('speedtest_streams', '4'),
        'db_retention_days':     get_setting('db_retention_days', '30'),
        'discord_webhook_url':      get_setting('discord_webhook_url', ''),
        'apprise_urls':             get_setting('apprise_urls', ''),
        'airvpn_new_server_notif':  get_setting('airvpn_new_server_notif', '0'),
        'airvpn_notify_mention':    get_setting('airvpn_notify_mention', ''),   # legacy
        'notif_auto_switch':        get_setting('notif_auto_switch',    '1'),
        'notif_manual_switch':      get_setting('notif_manual_switch',  '0'),
        'notif_already_best':       get_setting('notif_already_best',   '0'),
        'notif_auto_exclude':       get_setting('notif_auto_exclude',   '1'),
        'notif_benchmark_end':      get_setting('notif_benchmark_end',     '0'),
        'notif_benchmark_failure':  get_setting('notif_benchmark_failure', '1'),
        'notif_quick_check':           get_setting('notif_quick_check',            '1'),
        'notif_optimal_hour_change':   get_setting('notif_optimal_hour_change',    '0'),
        'notif_catalogue_changes':     get_setting('notif_catalogue_changes',      '0'),
        'notify_mention':              get_setting('notify_mention',               ''),
        'notify_mention_level':     get_setting('notify_mention_level',    'critical'),
        'sidecar_mode':             get_setting('sidecar_mode', '1'),
        'sidecar_image':            get_setting('sidecar_image', 'ghcr.io/aerya/gluetun-companion-sidecar:latest'),
        'sidecar_port':             get_setting('sidecar_port', '8766'),
        'sidecar_speedtest_method': get_setting('sidecar_speedtest_method', 'dual'),
        'sidecar_iperf_fallback':      get_setting('sidecar_iperf_fallback', '1'),
        'sidecar_proxy_fallback':      get_setting('sidecar_proxy_fallback', '0'),
        'post_switch_containers':       json.loads(get_setting('post_switch_containers', '[]')),
        'pause_bench_containers':       json.loads(get_setting('pause_bench_containers', '[]')),
        'pull_gluetun':                 get_setting('pull_gluetun', '0'),
        'pull_post_switch_containers':  set(json.loads(get_setting('pull_post_switch_containers', '[]'))),
        'pull_pause_bench_containers':  set(json.loads(get_setting('pull_pause_bench_containers', '[]'))),
        'pull_network_containers':      set(json.loads(get_setting('pull_network_containers', '[]'))),
        'quick_check_mode':             get_setting('quick_check_mode', '0'),
        'quick_check_threshold':        get_setting('quick_check_threshold', '15'),
        'adaptive_scheduling':          get_setting('adaptive_scheduling', '0'),
        'adaptive_auto_shift':          get_setting('adaptive_auto_shift', '0'),
        'scoring_window_days':          get_setting('scoring_window_days', '30'),
        'outlier_detection':            get_setting('outlier_detection', '1'),
        'weighted_score_current_pct':   get_setting('weighted_score_current_pct', '65'),
        'stability_weight':             get_setting('stability_weight', '30'),
        'active_profile':               get_setting('active_profile', 'balanced'),
        'single_stream_test':           get_setting('single_stream_test', '0'),
        'api_token':                    get_setting('api_token', ''),
        'catalogue_import_mode':          get_setting('catalogue_import_mode', 'active'),
        'catalogue_import_provider':      get_setting('catalogue_import_provider', ''),
        'catalogue_bench_on_import':      get_setting('catalogue_bench_on_import', '0'),
        'catalogue_import_filter_type':   get_setting('catalogue_import_filter_type', 'all'),
        'catalogue_auto_add':             get_setting('catalogue_auto_add', '0'),
        'catalogue_last_refresh':         get_setting('catalogue_last_refresh', ''),
        'bench_include_types':            json.loads(get_setting('bench_include_types', '[]')),
        'airvpn_bench_max_load':          get_setting('airvpn_bench_max_load', '0'),
        'airvpn_bench_max_users':         get_setting('airvpn_bench_max_users', '0'),
        'wg_rotation_mode':               get_setting('wg_rotation_mode', 'none'),
        'wg_rotation_threshold':          get_setting('wg_rotation_threshold', '10'),
    }
    # WireGuard profiles — loaded separately (with masked secrets for display)
    _raw_profiles = get_vpn_profiles()
    _has_wg_profiles = len(_raw_profiles) > 0
    _wg_profiles_display = []
    for _p in _raw_profiles:
        _display_vars = {}
        for _k, _v in _p['vars'].items():
            from .crypto import is_encrypted as _is_enc
            _display_vars[_k] = crypto_mask(_v) if _is_enc(_v) else _v
        # Exclude raw 'vars' (ciphertexts) and sidecar raw keys from the dict
        # sent to the browser — only vars_display (masked) is needed by the JS.
        _safe_profile = {k: v for k, v in _p.items()
                         if k not in ('vars', 'sidecar_private_key', 'sidecar_preshared_key')}
        _safe_profile['vars_display'] = _display_vars
        # Boolean flags so JS can show "configured (hidden)" hints
        _safe_profile['sidecar_pk_set']  = bool(_p.get('sidecar_private_key'))
        _safe_profile['sidecar_psk_set'] = bool(_p.get('sidecar_preshared_key'))
        _wg_profiles_display.append(_safe_profile)
    _orphan_count = len(get_servers_without_profile())
    from .database import get_hourly_benchmark_stats
    from .catalogue import catalogue_stats
    adaptive_stats = get_hourly_benchmark_stats()
    active_auto_pools = _active_auto_pool_count()
    bench_est_settings = _bench_estimate()  # per-server only (no server_count needed)
    return render_template(
        'settings.html',
        cfg=cfg,
        bench_est=bench_est_settings,
        next_run=None if active_auto_pools else get_next_run(),
        gluetun_container=current_app.config['GLUETUN_CONTAINER'],
        adaptive_stats=adaptive_stats,
        profiles=PROFILES,
        catalogue_stats=catalogue_stats(),
        wg_profiles=_wg_profiles_display,
        wg_providers=get_all_providers(),
        wg_providers_json=json.dumps({
            k: {
                'label':      p['label'],
                'native_wg':  p['native_wg'],
                'via_custom': p['via_custom'],
                'hint_fr':    p.get('hint_fr', ''),
                'hint_en':    p.get('hint_en', ''),
                'help_url':   p.get('help_url', ''),
                'fields': [
                    {
                        'key':       f['key'],
                        'label_fr':  f['label_fr'],
                        'label_en':  f['label_en'],
                        'required':  f['required'],
                        'secret':    f['secret'],
                    }
                    for f in p['fields']
                ],
            }
            for k, p in WG_PROVIDERS.items()
        }),
        wg_orphan_count=_orphan_count,
        has_wg_profiles=_has_wg_profiles,
        active_auto_pools=active_auto_pools,
    )


# ---------------------------------------------------------------------------
# AirVPN live data
# ---------------------------------------------------------------------------

@bp.route('/api/airvpn-servers')
@login_required
def api_airvpn_servers():
    global _airvpn_cache
    now = time.time()
    if _airvpn_cache['data'] and now - _airvpn_cache['ts'] < _AIRVPN_CACHE_TTL:
        return jsonify(_airvpn_cache['data'])
    try:
        import requests as _req
        resp = _req.get(
            'https://airvpn.org/api/status/',
            headers={'User-Agent': 'Gluetun-Companion/1.0'},
            timeout=10,
        )
        resp.raise_for_status()
        raw = resp.json()
    except Exception as exc:
        return jsonify({'error': str(exc)}), 502

    servers: list[dict] = []
    countries_map: dict[str, dict] = {}

    for s in raw.get('servers', []):
        name    = s.get('public_name', '')
        country = s.get('country_name', '')
        cc      = (s.get('country_code') or '').lower()
        bw      = s.get('bw', 0) or 0
        bw_max  = s.get('bw_max', 0) or 0
        load    = s.get('currentload', 0) or 0
        users   = s.get('users', 0) or 0
        health  = s.get('health', 'ok')
        entry   = {
            'name':         name,
            'country':      country,
            'country_code': cc,
            'location':     s.get('location', ''),
            'continent':    s.get('continent', ''),
            'load':         load,
            'users':        users,
            'bw':           bw,
            'bw_max':       bw_max,
            'avail_mbps':   max(0, bw_max - bw),
            'health':       health,
        }
        servers.append(entry)
        if country not in countries_map:
            countries_map[country] = {'country': country, 'country_code': cc, 'servers': []}
        countries_map[country]['servers'].append(entry)

    servers.sort(key=lambda x: x['name'])

    # ── Diff vs previous snapshot ────────────────────────────────────────────
    snapshot     = get_airvpn_snapshot()
    has_snapshot = bool(snapshot)
    current_names = {s['name'] for s in servers}
    snap_names    = set(snapshot.keys())

    appeared: list[dict] = []
    disappeared: list[dict] = []
    load_changes: list[dict] = []

    if has_snapshot:
        appeared     = [s for s in servers if s['name'] not in snap_names]
        disappeared  = [
            {'name': n, **snapshot[n]}
            for n in sorted(snap_names - current_names)
        ]
        for s in servers:
            if s['name'] in snapshot:
                prev = snapshot[s['name']]['load']
                delta = s['load'] - prev
                if abs(delta) >= 10:
                    load_changes.append({
                        'name':         s['name'],
                        'country':      s['country'],
                        'country_code': s['country_code'],
                        'load':         s['load'],
                        'prev_load':    prev,
                        'delta':        delta,
                    })
        load_changes.sort(key=lambda x: abs(x['delta']), reverse=True)

    # ── Recommended flag: health ok + load < 50 % + users < 30 ─────────────
    _REC_LOAD  = 50
    _REC_USERS = 30
    for s in servers:
        s['recommended'] = (
            s['health'] == 'ok'
            and s['load'] < _REC_LOAD
            and s['users'] < _REC_USERS
        )

    # Persist snapshot for next call
    update_airvpn_snapshot(servers)

    # ── Countries ────────────────────────────────────────────────────────────
    countries_list: list[dict] = []
    for cdata in countries_map.values():
        total   = len(cdata['servers'])
        n_ok    = sum(1 for sv in cdata['servers'] if sv['health'] == 'ok')
        healthy = [sv for sv in cdata['servers'] if sv['health'] == 'ok']
        pool    = healthy or cdata['servers']
        best    = min(pool, key=lambda x: x['load'])['name'] if pool else None
        cdata['best']         = best
        cdata['server_count'] = total
        cdata['healthy_pct']  = round(n_ok / total * 100) if total else 0
        cdata['avg_load']     = round(sum(sv['load'] for sv in cdata['servers']) / total) if total else 0
        cdata['servers'].sort(key=lambda x: x['load'])
        countries_list.append(cdata)
    countries_list.sort(key=lambda x: x['country'])

    # Top-5 healthiest countries (desc healthy_pct, then asc avg_load)
    best_health_countries = sorted(
        countries_list,
        key=lambda c: (-c['healthy_pct'], c['avg_load']),
    )[:5]

    result = {
        'servers':   servers,
        'countries': countries_list,
        'diff': {
            'has_snapshot':         has_snapshot,
            'appeared':             appeared,
            'disappeared':          disappeared,
            'load_changes':         load_changes,
            'best_health_countries': best_health_countries,
        },
    }
    _airvpn_cache = {'data': result, 'ts': now}
    return jsonify(result)


# ---------------------------------------------------------------------------
# JSON API
# ---------------------------------------------------------------------------

@bp.route('/healthz')
def healthz():
    try:
        with get_db() as db:
            db.execute('SELECT 1')
        return jsonify({'status': 'ok', 'db': 'ok'})
    except Exception as exc:
        return jsonify({'status': 'error', 'db': str(exc)}), 500


@bp.route('/metrics')
def metrics():
    """
    Prometheus metrics endpoint.
    Unauthenticated by default — set METRICS_TOKEN env var to require
    an 'Authorization: Bearer <token>' header.
    """
    # METRICS_TOKEN env var takes precedence; fall back to the DB api_token if set.
    token = current_app.config.get('METRICS_TOKEN', '') or get_setting('api_token', '')
    if token:
        auth = request.headers.get('Authorization', '')
        if auth != f'Bearer {token}':
            return Response(
                'Unauthorized\n',
                status=401,
                headers={'WWW-Authenticate': 'Bearer realm="metrics"'},
            )

    def _esc(v: str) -> str:
        """Escape a Prometheus label value."""
        return str(v).replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')

    lines: list[str] = []

    def _metric(name: str, help_text: str, type_: str,
                samples: list[tuple[dict, object]]) -> None:
        lines.append(f'# HELP {name} {help_text}')
        lines.append(f'# TYPE {name} {type_}')
        for labels, value in samples:
            if value is None:
                continue
            if labels:
                lstr = ','.join(f'{k}="{_esc(v)}"' for k, v in labels.items())
                lines.append(f'{name}{{{lstr}}} {value}')
            else:
                lines.append(f'{name} {value}')

    # ── DB queries ─────────────────────────────────────────────────────────
    with get_db() as db:
        server_rows = db.execute('''
            SELECT
                s.name,
                s.enabled,
                s.consecutive_failures,
                ROUND(AVG(CASE WHEN st.success=1
                               AND (st.test_method IS NULL OR st.test_method != 'proxy_qc')
                               THEN st.download_mbps END), 2) AS avg_dl,
                ROUND(AVG(CASE WHEN st.success=1
                               AND (st.test_method IS NULL OR st.test_method != 'proxy_qc')
                               THEN st.upload_mbps END), 2)   AS avg_ul,
                ROUND(AVG(CASE WHEN st.success=1
                               AND (st.test_method IS NULL OR st.test_method != 'proxy_qc')
                               THEN st.latency_ms END), 2)    AS avg_lat,
                COUNT(st.id)                                        AS total_tests,
                SUM(CASE WHEN st.success=0 THEN 1 ELSE 0 END)      AS failed_tests,
                MAX(strftime('%s', st.tested_at))                   AS last_ts
            FROM servers s
            LEFT JOIN speed_tests st ON st.server_name = s.name
            GROUP BY s.id
            ORDER BY s.name
        ''').fetchall()

        sw = db.execute('''
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN success=1 THEN 1 ELSE 0 END)  AS successful,
                MAX(strftime('%s', switched_at))             AS last_ts
            FROM switches
        ''').fetchone()

        err_rows = db.execute('''
            SELECT
                CASE
                    WHEN LOWER(COALESCE(error_msg,'')) LIKE '%timeout%'  THEN 'timeout'
                    WHEN LOWER(COALESCE(error_msg,'')) LIKE '%connect%'
                      OR LOWER(COALESCE(error_msg,'')) LIKE '%refused%'  THEN 'connection'
                    WHEN LOWER(COALESCE(error_msg,'')) LIKE '%vpn%'
                      OR LOWER(COALESCE(error_msg,'')) LIKE '%gluetun%'  THEN 'vpn'
                    ELSE 'other'
                END AS error_type,
                COUNT(*) AS cnt
            FROM speed_tests
            WHERE success=0
              AND error_msg IS NOT NULL
              AND TRIM(COALESCE(error_msg,'')) != ''
            GROUP BY error_type
        ''').fetchall()

    # ── Active server (best-effort) ────────────────────────────────────────
    active_server = ''
    try:
        _filters = get_current_filters(current_app.config['GLUETUN_CONTAINER'])
        active_server = next(iter(_filters.values())).split(',')[0].strip() if _filters else ''
    except Exception:
        pass

    bm_running = int(get_setting('benchmark_running', '0') == '1')

    # ── Stability / confidence / profile scores (extended metrics) ─────────
    stab_map = get_stability_all()
    conf_map = compute_confidence_all()
    _CONF_NUM = {'LOW': 0, 'MEDIUM': 1, 'HIGH': 2}

    _profile_scores: dict[str, float] = {}
    _active_profile = get_setting('active_profile', 'balanced')
    try:
        from .profiles import score_servers as _score_srv
        _profile_scores = _score_srv(server_rows, _active_profile, stab_map)
    except Exception:
        pass

    # ── Per-server gauges ──────────────────────────────────────────────────
    _metric('gluetun_companion_server_avg_dl_mbps',
            'Average download speed in Mbps (full benchmarks only, proxy_qc excluded)',
            'gauge',
            [({'server': r['name']}, r['avg_dl']) for r in server_rows])

    _metric('gluetun_companion_server_avg_ul_mbps',
            'Average upload speed in Mbps (full benchmarks only, proxy_qc excluded)',
            'gauge',
            [({'server': r['name']}, r['avg_ul']) for r in server_rows])

    _metric('gluetun_companion_server_avg_latency_ms',
            'Average latency in milliseconds (full benchmarks only, proxy_qc excluded)',
            'gauge',
            [({'server': r['name']}, r['avg_lat']) for r in server_rows])

    _metric('gluetun_companion_server_test_count',
            'Total number of speed tests recorded for this server',
            'gauge',
            [({'server': r['name']}, r['total_tests']) for r in server_rows])

    _metric('gluetun_companion_server_failure_count',
            'Total number of failed speed tests for this server',
            'gauge',
            [({'server': r['name']}, r['failed_tests'] or 0) for r in server_rows])

    _metric('gluetun_companion_server_consecutive_failures',
            'Current consecutive failure count (reset to 0 on success)',
            'gauge',
            [({'server': r['name']}, r['consecutive_failures']) for r in server_rows])

    _metric('gluetun_companion_server_enabled',
            '1 if the server is enabled for benchmarking, 0 if disabled',
            'gauge',
            [({'server': r['name']}, 1 if r['enabled'] else 0) for r in server_rows])

    _metric('gluetun_companion_server_active',
            '1 if this is the currently active Gluetun server, 0 otherwise',
            'gauge',
            [({'server': r['name']}, 1 if r['name'] == active_server else 0)
             for r in server_rows])

    _metric('gluetun_companion_server_last_benchmark_ts_seconds',
            'Unix timestamp of the last speed test recorded for this server (any method)',
            'gauge',
            [({'server': r['name']}, int(r['last_ts']))
             for r in server_rows if r['last_ts']])

    _metric('gluetun_companion_server_avg_jitter_ms',
            'Average jitter in milliseconds (sidecar tests only, proxy_qc excluded)',
            'gauge',
            [({'server': name}, data.get('avg_jitter'))
             for name, data in stab_map.items()])

    _metric('gluetun_companion_server_avg_loss_pct',
            'Average packet loss percentage (sidecar tests only, proxy_qc excluded)',
            'gauge',
            [({'server': name}, data.get('avg_loss'))
             for name, data in stab_map.items()])

    _metric('gluetun_companion_server_avg_dns_ms',
            'Average DNS latency in milliseconds (sidecar tests only, proxy_qc excluded)',
            'gauge',
            [({'server': name}, data.get('avg_dns'))
             for name, data in stab_map.items()])

    _metric('gluetun_companion_server_confidence',
            'Confidence level: 0=LOW, 1=MEDIUM, 2=HIGH',
            'gauge',
            [({'server': name}, _CONF_NUM.get(data.get('level', 'LOW'), 0))
             for name, data in conf_map.items()])

    if _profile_scores:
        _metric('gluetun_companion_server_score',
                'Current usage-profile score in [0, 1] (higher = better for active profile)',
                'gauge',
                [({'server': name, 'profile': _active_profile}, score)
                 for name, score in _profile_scores.items()])

    _metric('gluetun_companion_errors_total',
            'Total failed speed tests grouped by error type (timeout, connection, vpn, other)',
            'counter',
            [({'type': r['error_type']}, r['cnt']) for r in err_rows])

    # ── Global counters / gauges ───────────────────────────────────────────
    _metric('gluetun_companion_switches_total',
            'Total number of VPN server switches recorded (successful + failed)',
            'counter',
            [({}, sw['total'] or 0)])

    _metric('gluetun_companion_switches_success_total',
            'Total number of successful VPN server switches',
            'counter',
            [({}, sw['successful'] or 0)])

    _metric('gluetun_companion_benchmark_running',
            '1 if a benchmark cycle is currently in progress, 0 otherwise',
            'gauge',
            [({}, bm_running)])

    if sw['last_ts']:
        _metric('gluetun_companion_last_switch_timestamp_seconds',
                'Unix timestamp of the most recent VPN server switch',
                'gauge',
                [({}, int(sw['last_ts']))])

    return Response(
        '\n'.join(lines) + '\n',
        mimetype='text/plain; version=0.0.4; charset=utf-8',
    )


@bp.route('/api/set-profile', methods=['POST'])
@login_required
def api_set_profile():
    """Switch the active usage profile (called from /servers profile pill)."""
    profile_key = (request.form.get('active_profile') or '').strip()
    if profile_key not in PROFILES:
        return jsonify({'status': 'invalid_profile'}), 400
    set_setting('active_profile', profile_key)
    return redirect(url_for('main.servers'))


@bp.route('/api/trigger', methods=['POST'])
@login_required
def api_trigger():
    if get_setting('benchmark_running', '0') == '1':
        return jsonify({'status': 'already_running'}), 409
    # Set flag before starting thread so the dashboard spinner appears immediately
    set_setting('benchmark_running', '1')
    trigger_now(current_app._get_current_object())
    return jsonify({'status': 'started'})


@bp.route('/api/trigger_quick', methods=['POST'])
@login_required
def api_trigger_quick():
    if get_setting('benchmark_running', '0') == '1':
        return jsonify({'status': 'already_running'}), 409
    # Set flag before starting thread so the spinner appears immediately
    set_setting('benchmark_running', '1')
    trigger_quick_now(current_app._get_current_object())
    return jsonify({'status': 'started'})


@bp.route('/api/stop-benchmark', methods=['POST'])
@login_required
def api_stop_benchmark():
    """Request the running benchmark to stop after the current server test."""
    if get_setting('benchmark_running', '0') != '1':
        return jsonify({'status': 'not_running'}), 409
    request_stop()
    return jsonify({'status': 'stop_requested'})


@bp.route('/api/notify-test', methods=['POST'])
@login_required
def api_notify_test():
    """Send a test notification using the URLs provided in the request body."""
    from .notify import send_test_notification
    data        = request.get_json(silent=True) or {}
    target      = data.get('target', 'all')          # 'discord' | 'apprise' | 'all'
    discord_url = (data.get('discord_url') or '').strip() or None
    apprise_urls= (data.get('apprise_urls') or '').strip() or None
    mention     = (data.get('mention') or '').strip() or None
    lang        = get_setting('ui_lang', 'fr')
    ok, msg     = send_test_notification(target, discord_url, apprise_urls, lang, mention=mention)
    return jsonify({'ok': ok, 'msg': msg}), (200 if ok else 502)


@bp.route('/api/docker-containers')
@login_required
def api_docker_containers():
    """Return the list of currently running Docker container names."""
    return jsonify(list_docker_containers())


# ---------------------------------------------------------------------------
# Config export / import
# ---------------------------------------------------------------------------

@bp.route('/config/export')
@login_required
def config_export():
    """Download non-secret settings as a JSON file."""
    from datetime import datetime, timezone

    with get_db() as db:
        rows = db.execute('SELECT key, value FROM settings').fetchall()

    payload = {
        '_version':     1,
        '_exported_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'settings':     {r['key']: r['value'] for r in rows if r['key'] in _EXPORT_KEYS},
    }

    resp = Response(
        json.dumps(payload, indent=2, ensure_ascii=False),
        mimetype='application/json',
    )
    resp.headers['Content-Disposition'] = 'attachment; filename="companion-config.json"'
    return resp


@bp.route('/config/import', methods=['POST'])
@login_required
def config_import():
    """Import settings from a JSON file (secrets are ignored)."""
    f = request.files.get('config_file')
    if not f:
        flash('Aucun fichier fourni.', 'danger')
        return redirect(url_for('main.settings'))

    try:
        data = json.loads(f.read().decode('utf-8'))
    except Exception as exc:
        flash(f'Fichier invalide : {exc}', 'danger')
        return redirect(url_for('main.settings'))

    if not isinstance(data, dict) or 'settings' not in data:
        flash("Format invalide — clé 'settings' manquante.", 'danger')
        return redirect(url_for('main.settings'))

    imported = skipped = 0
    _schedule_keys = {'test_interval_hours', 'auto_benchmark'}
    _needs_reschedule = False
    for key, value in data['settings'].items():
        if key in _EXPORT_KEYS:
            set_setting(key, str(value))
            imported += 1
            if key in _schedule_keys:
                _needs_reschedule = True
        else:
            skipped += 1

    if _needs_reschedule:
        try:
            _h = float(get_setting('test_interval_hours', '6') or '6')
            _en = get_setting('auto_benchmark', '0') == '1'
            reschedule(_h, enabled=_en)
        except Exception as _exc:
            logger.warning('reschedule after config import failed: %s', _exc)

    flash(
        f'{imported} paramètre(s) importé(s).'
        + (f' {skipped} clé(s) ignorée(s) (secrètes ou inconnues).' if skipped else ''),
        'success',
    )
    return redirect(url_for('main.settings'))


# ---------------------------------------------------------------------------
# Grafana dashboard download
# ---------------------------------------------------------------------------

@bp.route('/grafana-dashboard')
@login_required
def grafana_dashboard():
    """Serve the pre-built Grafana dashboard JSON."""
    import os
    path = os.path.join(os.path.dirname(__file__), '..', 'assets', 'grafana-dashboard.json')
    return send_file(path, mimetype='application/json', as_attachment=True,
                     download_name='gluetun-companion-dashboard.json')


@bp.route('/api/gluetun-network-containers')
@login_required
def api_gluetun_network_containers():
    """Return containers using network_mode: service:<gluetun_container>."""
    from .gluetun import list_network_dependents
    container = current_app.config['GLUETUN_CONTAINER']
    try:
        return jsonify(list_network_dependents(container))
    except Exception:
        return jsonify([])


# ── Catalogue API ───────────────────────────────────────────────────────────

@bp.route('/api/catalogue/refresh', methods=['POST'])
@login_required
def api_catalogue_refresh():
    """Force-refresh the Gluetun server catalogue via a catalogue sidecar.
    The sidecar downloads server lists from the public Gluetun GitHub repo —
    no volume mounting required."""
    from .catalogue import refresh_catalogue_from_sidecar
    sidecar_image = get_setting('sidecar_image', 'ghcr.io/aerya/gluetun-companion-sidecar:latest')
    sidecar_host  = current_app.config['GLUETUN_HOST']
    result = refresh_catalogue_from_sidecar(
        sidecar_image=sidecar_image,
        sidecar_host=sidecar_host,
    )
    return jsonify(result), (200 if result.get('ok') else 500)


@bp.route('/api/catalogue/providers')
@login_required
def api_catalogue_providers():
    """Return list of providers and their server counts in the catalogue."""
    from .catalogue import catalogue_stats
    return jsonify(catalogue_stats())


@bp.route('/api/catalogue/servers')
@login_required
def api_catalogue_servers():
    """
    Return catalogue entries for a filter type.
    Query params: provider (optional), filter_type (default: name)
    """
    from .catalogue import get_catalogue_entries
    provider    = request.args.get('provider', '').strip() or None
    filter_type = request.args.get('filter_type', 'name')
    entries     = get_catalogue_entries(provider=provider, filter_type=filter_type)
    return jsonify({'entries': entries, 'filter_type': filter_type})


@bp.route('/api/catalogue/add-and-test', methods=['POST'])
@login_required
def api_catalogue_add_and_test():
    """
    Add a single server from the catalogue to the servers table (if not already there),
    then trigger a background test/switch on it.
    Body JSON: {name, filter_type}
    """
    from .scheduler import trigger_single_server
    data        = request.get_json(force=True, silent=True) or {}
    name        = data.get('name', '').strip()
    filter_type = data.get('filter_type', 'name')

    if not name:
        return jsonify({'ok': False, 'error': 'missing name'}), 400
    if filter_type not in FILTER_VARS:
        filter_type = 'name'

    if get_setting('benchmark_running', '0') == '1':
        return jsonify({'ok': False, 'error': 'benchmark_running'}), 409

    with get_db() as db:
        db.execute('INSERT OR IGNORE INTO servers (name, filter_type) VALUES (?, ?)', (name, filter_type))
        row = db.execute('SELECT id FROM servers WHERE name=?', (name,)).fetchone()
        if not row:
            return jsonify({'ok': False, 'error': 'failed to add server'}), 500

    trigger_single_server(current_app._get_current_object(), name, filter_type)
    return jsonify({'ok': True, 'name': name})


@bp.route('/api/catalogue/import', methods=['POST'])
@login_required
def api_catalogue_import():
    """
    Import servers from the catalogue into the servers table.
    Body JSON: {mode, provider, filter_type, bench_on_import}
    """
    from .catalogue import import_to_servers
    data        = request.get_json(force=True, silent=True) or {}
    mode        = data.get('mode', 'active')
    provider    = data.get('provider', '')
    filter_type = data.get('filter_type', 'name')
    container   = current_app.config['GLUETUN_CONTAINER']

    result = import_to_servers(
        mode=mode,
        provider=provider,
        filter_type=filter_type,
        container_name=container,
    )

    if result.get('ok') and data.get('bench_on_import'):
        try:
            trigger_now(current_app._get_current_object())
            result['bench_triggered'] = True
        except Exception as exc:
            result['bench_triggered'] = False
            result['bench_error'] = str(exc)

    return jsonify(result), (200 if result.get('ok') else 500)


# ---------------------------------------------------------------------------
# Rotation pools
# ---------------------------------------------------------------------------

@bp.route('/pools')
@login_required
def pools():
    from .i18n import get_t
    from .rotation_pools import resolve_pool_servers
    t    = get_t()
    lang = get_setting('ui_lang', 'fr')
    all_pools = get_rotation_pools()

    # Resolve candidate counts for each pool (for display)
    _metric_labels = {
        'dl': t.get('pools_crit_met_dl', 'DL'),
        'jitter': t.get('pools_crit_met_jitter', 'Jitter'),
        'loss': t.get('pools_crit_met_loss', 'Loss'),
        'dns': t.get('pools_crit_met_dns', 'DNS'),
    }
    for p in all_pools:
        try:
            p['candidate_count'] = len(resolve_pool_servers(p['id']))
        except Exception:
            p['candidate_count'] = 0
        # Add human-readable display label for top_metric criteria
        for c in p.get('criteria', []):
            if c.get('crit_type') == 'top_metric':
                try:
                    mdata = json.loads(c.get('crit_value') or '{}')
                    met   = _metric_labels.get(mdata.get('metric', ''), '?')
                    c['_display'] = f"Top {mdata.get('n', '?')} {met}"
                except Exception:
                    c['_display'] = str(c.get('crit_value', '?'))

    # Build server list for autocomplete
    with get_db() as db:
        all_servers = db.execute(
            'SELECT name, filter_type, vpn_profile_id FROM servers WHERE enabled=1 ORDER BY name'
        ).fetchall()
        all_servers = [dict(s) for s in all_servers]

        # Available filter values per type (for dropdown)
        filter_values: dict[str, list[str]] = {}
        for ft in ('name', 'country', 'city', 'region', 'hostname'):
            rows = db.execute(
                'SELECT DISTINCT name FROM servers WHERE filter_type=? AND enabled=1 ORDER BY name',
                (ft,),
            ).fetchall()
            filter_values[ft] = [r['name'] for r in rows]

    wg_profiles_list = get_vpn_profiles()

    return render_template(
        'pools.html',
        t=t, lang=lang,
        pools=all_pools,
        all_servers=all_servers,
        filter_values_json=json.dumps(filter_values),
        wg_profiles=wg_profiles_list,
    )


@bp.route('/api/pools', methods=['POST'])
@login_required
def api_pool_create():
    """Create a new rotation pool from JSON body."""
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'ok': False, 'error': 'Name is required'}), 400

    criteria = _parse_pool_criteria(data.get('criteria') or [])
    interval_h = _parse_interval(data)

    pool_id = create_rotation_pool(
        name=name,
        mode=data.get('mode', 'random'),
        criteria_logic=_parse_criteria_logic(data.get('criteria_logic')),
        enabled=bool(data.get('enabled', True)),
        auto_rotate=bool(data.get('auto_rotate', False)),
        interval_hours=interval_h,
        quick_bench=bool(data.get('quick_bench', False)),
        notify=bool(data.get('notify', True)),
        top_n=_parse_top_n(data.get('top_n')),
        criteria=criteria,
    )
    # Schedule first auto-rotation if applicable
    _pool_enabled = bool(data.get('enabled', True))
    _pool_auto = bool(data.get('auto_rotate', False))
    _maybe_schedule_next(pool_id, interval_h, _pool_enabled and _pool_auto)
    if _pool_enabled and _pool_auto:
        _standby_benchmark_cycle_for_pools()
    return jsonify({'ok': True, 'id': pool_id})


@bp.route('/api/pools/<int:pool_id>', methods=['PUT'])
@login_required
def api_pool_update(pool_id: int):
    """Update an existing pool."""
    data = request.get_json(silent=True) or {}
    pool = get_rotation_pool(pool_id)
    if not pool:
        return jsonify({'ok': False, 'error': 'Not found'}), 404

    name = (data.get('name') or '').strip() or None
    interval_h = _parse_interval(data)
    auto_rotate = data.get('auto_rotate')
    criteria_logic = _parse_criteria_logic(data.get('criteria_logic')) if 'criteria_logic' in data else None
    criteria = _parse_pool_criteria(data.get('criteria') or []) if 'criteria' in data else None

    # top_n: only update if key was present in request; otherwise use sentinel to leave unchanged
    top_n_arg = _parse_top_n(data['top_n']) if 'top_n' in data else _DB_UNSET

    update_rotation_pool(
        pool_id,
        name=name,
        mode=data.get('mode'),
        criteria_logic=criteria_logic,
        enabled=data.get('enabled'),
        auto_rotate=None if auto_rotate is None else bool(auto_rotate),
        interval_hours=interval_h,
        quick_bench=data.get('quick_bench'),
        notify=data.get('notify'),
        top_n=top_n_arg,
        criteria=criteria,
    )
    _enabled_after = bool(data.get('enabled')) if 'enabled' in data else bool(pool['enabled'])
    _auto_after = bool(auto_rotate) if auto_rotate is not None else bool(pool['auto_rotate'])
    # Reschedule if auto_rotate, enabled or interval changed
    if auto_rotate is not None or interval_h is not None or 'enabled' in data:
        _maybe_schedule_next(
            pool_id,
            interval_h if interval_h is not None else pool['interval_hours'],
            _enabled_after and _auto_after,
        )
    if _enabled_after and _auto_after:
        _standby_benchmark_cycle_for_pools()
    return jsonify({'ok': True})


@bp.route('/api/pools/<int:pool_id>', methods=['DELETE'])
@login_required
def api_pool_delete(pool_id: int):
    if delete_rotation_pool(pool_id):
        return jsonify({'ok': True})
    return jsonify({'ok': False, 'error': 'Not found'}), 404


@bp.route('/api/pools/<int:pool_id>/rotate', methods=['POST'])
@login_required
def api_pool_rotate(pool_id: int):
    """Trigger an immediate manual rotation for this pool."""
    from .rotation_pools import do_pool_rotation
    pool = get_rotation_pool(pool_id)
    if not pool:
        return jsonify({'ok': False, 'error': 'Not found'}), 404
    if not pool.get('enabled'):
        return jsonify({'ok': False, 'error': 'Pool disabled'}), 409
    if get_setting('benchmark_running', '0') == '1':
        return jsonify({'ok': False, 'error': 'Benchmark in progress'}), 409
    if not scheduler_lock.acquire(blocking=False):
        return jsonify({'ok': False, 'error': 'Benchmark in progress'}), 409
    try:
        if get_setting('benchmark_running', '0') == '1':
            return jsonify({'ok': False, 'error': 'Benchmark in progress'}), 409
        result = do_pool_rotation(pool_id, current_app._get_current_object(), manual=True)
    except Exception as exc:
        logger.error('Pool rotation [%d]: unexpected error: %s', pool_id, exc)
        set_setting('benchmark_running', '0')
        set_setting('benchmark_current_server', '')
        return jsonify({'ok': False, 'error': str(exc)}), 500
    finally:
        scheduler_lock.release()
    return jsonify(result)


@bp.route('/api/pools/<int:pool_id>/candidates')
@login_required
def api_pool_candidates(pool_id: int):
    """Return the current candidate server list for a pool (live resolution)."""
    from .rotation_pools import resolve_pool_servers
    pool = get_rotation_pool(pool_id)
    if not pool:
        return jsonify({'ok': False, 'error': 'Not found'}), 404
    candidates = resolve_pool_servers(pool_id)
    return jsonify({'ok': True, 'candidates': candidates, 'count': len(candidates)})


# ── Benchmark duration estimate ───────────────────────────────────────────────

def _bench_estimate(server_count: int = 0) -> dict:
    """
    Compute an optimistic/pessimistic per-server benchmark duration estimate
    from the current settings.

    Phases per server (proxy mode):
      connect  — wait_secs (pessimistic) / min(wait_secs, 15) (optimistic)
      warmup   — 2s if enabled, else 0
      DL       — dl_duration × dl_samples
      UL       — dl_duration
      stability— 21 TTFB probes ≈ 10s fixed
      overhead — docker-compose switch + deps ≈ 5s fixed

    Sidecar adds ≈ 15s container lifecycle per attempt.
    Retries multiply the pessimistic estimate by (max_retries + 1).
    """
    wait_secs   = int(get_setting('connection_wait_seconds', '45'))
    dl_duration = float(get_setting('speedtest_duration', '8'))
    dl_samples  = int(get_setting('speedtest_samples', '3'))
    warmup      = 2.0 if get_setting('speedtest_warmup', '1') == '1' else 0.0
    max_retries = int(get_setting('speedtest_retries', '2'))
    sidecar     = get_setting('sidecar_mode', '1') == '1'

    # test phases (everything after the VPN connection)
    test_phases = warmup + dl_duration * dl_samples + dl_duration + 10 + 5
    if sidecar:
        test_phases += 15  # container create + cleanup

    # optimistic: fast connect (15s), no retries
    per_min = int(min(wait_secs, 15) + test_phases)
    # pessimistic: full timeout × (retries + 1)
    per_max = int((wait_secs + test_phases) * (max_retries + 1))

    def _fmt(s: int) -> str:
        if s < 60:
            return f"{s}s"
        m, r = divmod(s, 60)
        h, m2 = divmod(m, 60)
        if h:
            return f"{h}h{m2:02d}min" if m2 else f"{h}h"
        return f"{m}m{r:02d}s" if r else f"{m}min"

    total_min = per_min * server_count
    total_max = per_max * server_count

    return {
        'per_min_s':   _fmt(per_min),
        'per_max_s':   _fmt(per_max),
        'total_min_s': _fmt(total_min) if server_count else '—',
        'total_max_s': _fmt(total_max) if server_count else '—',
        'warn':        server_count > 0 and total_max > 1800,  # > 30 min
        'mode':        'sidecar' if sidecar else 'proxy',
        'max_retries': max_retries,
    }


# ── Pool helpers ──────────────────────────────────────────────────────────────

def _parse_pool_criteria(raw: list) -> list[dict]:
    """Validate and normalise criteria list from JSON payload."""
    result = []
    for c in raw:
        ctype = (c.get('crit_type') or '').strip()
        if ctype not in ('all', 'server', 'filter', 'profile', 'top_metric'):
            continue
        cval = c.get('crit_value')
        if ctype == 'server' and not cval:
            continue
        if ctype == 'filter':
            try:
                fdata = json.loads(cval) if isinstance(cval, str) else cval
                if not fdata or not fdata.get('type'):
                    continue
                cval = json.dumps({'type': fdata['type'], 'value': fdata.get('value', '')})
            except Exception:
                continue
        if ctype == 'profile':
            try:
                int(cval)
            except (TypeError, ValueError):
                continue
        if ctype == 'top_metric':
            try:
                mdata = json.loads(cval) if isinstance(cval, str) else (cval or {})
                metric = str(mdata.get('metric', '')).strip()
                n = int(mdata.get('n', 0))
                if metric not in ('dl', 'jitter', 'loss', 'dns') or n < 1:
                    continue
                cval = json.dumps({'metric': metric, 'n': n})
            except Exception:
                continue
        result.append({'crit_type': ctype, 'crit_value': cval if ctype != 'all' else None})
    return result


def _parse_interval(data: dict) -> float | None:
    raw = data.get('interval_hours')
    if raw is None:
        return None
    try:
        return max(0.5, float(raw))
    except (TypeError, ValueError):
        return None


def _parse_criteria_logic(raw) -> str:
    return raw if raw in ('union', 'intersection') else 'union'


def _parse_top_n(raw) -> int | None:
    if raw is None or raw == '':
        return None
    try:
        v = int(raw)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def _maybe_schedule_next(pool_id: int, interval_h: float | None, auto_rotate: bool) -> None:
    """Set next_rotation_at = now + interval if auto_rotate is True, else clear it."""
    from datetime import datetime, timedelta
    if auto_rotate and interval_h and interval_h > 0:
        next_dt = (datetime.utcnow() + timedelta(hours=interval_h)).strftime('%Y-%m-%d %H:%M:%S')
        set_pool_next_rotation(pool_id, next_dt)
    else:
        set_pool_next_rotation(pool_id, None)


@bp.route('/api/status')
@login_required
def api_status():
    cfg     = current_app.config
    px_user = get_setting('proxy_username') or None
    px_pass = get_setting('proxy_password') or None
    return jsonify({
        'vpn_status':             get_vpn_status(cfg['GLUETUN_HOST'], cfg['GLUETUN_PROXY_PORT'], px_user, px_pass),
        'public_ip':              get_public_ip(cfg['GLUETUN_HOST'], cfg['GLUETUN_PROXY_PORT'], px_user, px_pass),
        'current_server':         format_filters(get_current_filters(cfg['GLUETUN_CONTAINER'])),
        'benchmark_running':      get_setting('benchmark_running', '0') == '1',
        'current_server_testing': get_setting('benchmark_current_server', ''),
        'next_run':               str(get_next_run()) if (get_next_run() and get_setting('auto_benchmark', '1') == '1') else None,
    })
