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
    redirect, render_template, request, session, url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from .database import (
    get_db, get_setting, set_setting, compute_confidence_all,
    get_new_airvpn_servers, dismiss_new_airvpn_servers,
    get_stability_all,
)
from .profiles import PROFILES, score_servers as _score_servers
from .gluetun import (
    FILTER_VARS, FILTER_LABELS,
    get_current_filters, format_filters,
    get_public_ip, get_public_ips, get_vpn_status, switch_server,
    wait_for_vpn, restart_network_dependents,
    list_docker_containers,
)
from .i18n import flash_t, get_t
from .scheduler import get_next_run, reschedule, trigger_now, trigger_quick_now, trigger_single_server

bp = Blueprint('main', __name__)

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
    if request.method == 'POST':
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
            session['logged_in'] = True
            session['username'] = username
            return redirect(url_for('main.dashboard'))

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
            'SELECT * FROM speed_tests ORDER BY tested_at DESC LIMIT ?', (recent_limit,)
        ).fetchall()
        last_switch = db.execute(
            'SELECT * FROM switches ORDER BY switched_at DESC LIMIT 1'
        ).fetchone()
        server_count = db.execute(
            'SELECT COUNT(*) AS n FROM servers WHERE enabled = 1'
        ).fetchone()['n']
        server_stats = db.execute('''
            SELECT server_name,
                   ROUND(AVG(download_mbps), 1) AS avg_dl,
                   ROUND(MAX(download_mbps), 1) AS max_dl
            FROM speed_tests WHERE success = 1
            GROUP BY server_name
            ORDER BY avg_dl DESC
            LIMIT 12
        ''').fetchall()
        last_cycle = db.execute(
            'SELECT * FROM benchmark_cycles ORDER BY id DESC LIMIT 1'
        ).fetchone()

        # Sparkline for active server (last 20 successful tests, chronological)
        sparkline_labels: list[str] = []
        sparkline_dl: list[float] = []
        sparkline_ul: list[float | None] = []
        sparkline_server: str | None = None
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

    return render_template(
        'dashboard.html',
        vpn_status=vpn_status,
        public_ip=public_ip,
        current_server=current_server,
        recent_tests=recent_tests,
        recent_limit=recent_limit,
        last_switch=last_switch,
        server_count=server_count,
        server_stats=server_stats,
        next_run=get_next_run() if get_setting('auto_benchmark', '1') == '1' else None,
        benchmark_running=benchmark_running,
        sidecar_mode=get_setting('sidecar_mode', '1'),
        last_cycle=last_cycle,
        sparkline_server=sparkline_server,
        sparkline_labels=sparkline_labels,
        sparkline_dl=sparkline_dl,
        sparkline_ul=sparkline_ul,
    )


# ---------------------------------------------------------------------------
# Servers
# ---------------------------------------------------------------------------

_SERVERS_SORT = {
    'avg_dl':  'avg_dl  DESC NULLS LAST, s.name',
    'avg_ul':  'avg_ul  DESC NULLS LAST, s.name',
    'max_dl':  'max_dl  DESC NULLS LAST, s.name',
    'latency': 'avg_lat ASC  NULLS LAST, s.name',
    'name':    's.name ASC',
}

@bp.route('/servers')
@login_required
def servers():
    sort        = request.args.get('sort', 'avg_dl')
    type_filter = request.args.get('type', '').strip()
    q           = request.args.get('q',    '').strip()
    from_date   = request.args.get('from_date', '').strip()
    to_date     = request.args.get('to_date',   '').strip()

    if sort not in _SERVERS_SORT:
        sort = 'avg_dl'
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
                ROUND(AVG(CASE WHEN st.success=1 THEN st.download_mbps END), 1)   AS avg_dl,
                ROUND(AVG(CASE WHEN st.success=1 THEN st.upload_mbps   END), 1)   AS avg_ul,
                ROUND(AVG(CASE WHEN st.success=1 THEN st.latency_ms    END), 0)   AS avg_lat,
                ROUND(MAX(CASE WHEN st.success=1 THEN st.download_mbps END), 1)   AS max_dl,
                ROUND(AVG(CASE WHEN st.success=1 AND st.dl_single_mbps IS NOT NULL
                               THEN st.dl_single_mbps END), 1)                    AS avg_dl_single,
                MAX(st.tested_at)                                                  AS last_tested,
                COUNT(st.id)                                                       AS total_tests,
                SUM(CASE WHEN st.success=1 THEN 1 ELSE 0 END)                     AS ok_tests,
                (SELECT public_ip   FROM speed_tests
                 WHERE server_name=s.name AND success=1 ORDER BY tested_at DESC LIMIT 1) AS last_ipv4,
                (SELECT public_ipv6 FROM speed_tests
                 WHERE server_name=s.name AND success=1 ORDER BY tested_at DESC LIMIT 1) AS last_ipv6
            FROM servers s
            LEFT JOIN speed_tests st ON st.server_name = s.name
            {where_sql}
            GROUP BY s.id
            {having_sql}
            ORDER BY {order_sql}
        ''', params).fetchall()
        filter_types = [r['filter_type'] for r in db.execute(
            'SELECT DISTINCT filter_type FROM servers ORDER BY filter_type'
        ).fetchall()]

    existing_names = [r['name'] for r in rows if r['filter_type'] == 'name']

    # Current active server — read from Gluetun (best-effort, empty string on failure)
    try:
        _container = current_app.config['GLUETUN_CONTAINER']
        _filters   = get_current_filters(_container)
        active_server = next(iter(_filters.values())).split(',')[0].strip() if _filters else ''
    except Exception:
        active_server = ''

    # Profile scores for display
    _stability = get_stability_all()
    active_profile = get_setting('active_profile', 'balanced')
    profile_scores = _score_servers(rows, active_profile, _stability)
    profile_best   = max(profile_scores, key=profile_scores.get) if profile_scores else None

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

    return render_template(
        'servers.html', servers=rows,
        filter_labels=FILTER_LABELS, filter_vars=FILTER_VARS,
        existing_names=existing_names,
        sort=sort, type_filter=type_filter, q=q,
        from_date=from_date, to_date=to_date,
        filter_types=filter_types,
        active_server=active_server,
        confidence=compute_confidence_all(),
        stability=_stability,
        new_airvpn=new_airvpn,
        new_airvpn_names=new_airvpn_names,
        new_airvpn_countries=new_airvpn_countries,
        profiles=PROFILES,
        active_profile=active_profile,
        profile_scores=profile_scores,
        profile_best=profile_best,
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


@bp.route('/servers/switch/<int:server_id>', methods=['POST'])
@login_required
def manual_switch(server_id):
    cfg = current_app.config
    with get_db() as db:
        row = db.execute('SELECT name, filter_type FROM servers WHERE id=?', (server_id,)).fetchone()
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

    ok, err = switch_server(
        row['name'], row['filter_type'],
        container, compose_dir, project,
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
    'date_desc':   'tested_at DESC',
    'date_asc':    'tested_at ASC',
    'server_asc':  'server_name ASC, tested_at DESC',
    'server_desc': 'server_name DESC, tested_at DESC',
    'dl_desc':     'download_mbps DESC',
    'dl_asc':      'download_mbps ASC',
}

@bp.route('/history')
@login_required
def history():
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
            f'SELECT * FROM speed_tests {where_sql} ORDER BY {order_sql} LIMIT ? OFFSET ?',
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

    pages = max(1, (total + _HISTORY_PER_PAGE - 1) // _HISTORY_PER_PAGE)
    return render_template(
        'history.html',
        tests=tests, per_server=per_server,
        page=page, pages=pages, total=total,
        sort=sort, server_filter=server_filter, method_filter=method_filter,
        from_date=from_date, to_date=to_date,
        show_failed=show_failed,
        server_names=server_names,
        timeline_data=timeline_data,
        confidence=compute_confidence_all(),
        stability=get_stability_all(),
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
# Draft test layouts  (/history_test · /servers_test · /dash_test)
# ---------------------------------------------------------------------------

@bp.route('/history_test')
@login_required
def history_test():
    from .database import get_hourly_benchmark_stats
    page          = max(1, request.args.get('page', 1, type=int))
    sort          = request.args.get('sort', 'date_desc')
    server_filter = request.args.get('server', '').strip()
    method_filter = request.args.get('method', '')
    from_date     = request.args.get('from_date', '').strip()
    to_date       = request.args.get('to_date',   '').strip()

    if sort not in _SORT_COLS:
        sort = 'date_desc'
    order_sql = _SORT_COLS[sort]

    where_parts: list[str] = []
    params: list = []
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
            f'SELECT * FROM speed_tests {where_sql} ORDER BY {order_sql} LIMIT ? OFFSET ?',
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
            GROUP BY server_name ORDER BY avg_dl DESC
        ''').fetchall()
        server_names = [r['server_name'] for r in db.execute(
            'SELECT DISTINCT server_name FROM speed_tests ORDER BY server_name'
        ).fetchall()]
        timeline_data = []
        if server_filter:
            timeline_data = db.execute('''
                SELECT tested_at, download_mbps, upload_mbps
                FROM speed_tests
                WHERE server_name = ? AND success = 1
                ORDER BY tested_at ASC LIMIT 200
            ''', (server_filter,)).fetchall()

    pages = max(1, (total + _HISTORY_PER_PAGE - 1) // _HISTORY_PER_PAGE)
    return render_template(
        'history_test.html',
        tests=tests, per_server=per_server,
        page=page, pages=pages, total=total,
        sort=sort, server_filter=server_filter, method_filter=method_filter,
        from_date=from_date, to_date=to_date,
        server_names=server_names,
        timeline_data=timeline_data,
        confidence=compute_confidence_all(),
        stability=get_stability_all(),
        adaptive_stats=get_hourly_benchmark_stats(),
    )


@bp.route('/servers_test')
@login_required
def servers_test():
    from .database import get_hourly_benchmark_stats
    sort        = request.args.get('sort', 'avg_dl')
    type_filter = request.args.get('type', '').strip()
    q           = request.args.get('q',    '').strip()
    from_date   = request.args.get('from_date', '').strip()
    to_date     = request.args.get('to_date',   '').strip()

    if sort not in _SERVERS_SORT:
        sort = 'avg_dl'
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
                ROUND(AVG(CASE WHEN st.success=1 THEN st.download_mbps END), 1) AS avg_dl,
                ROUND(AVG(CASE WHEN st.success=1 THEN st.upload_mbps   END), 1) AS avg_ul,
                ROUND(AVG(CASE WHEN st.success=1 THEN st.latency_ms    END), 0) AS avg_lat,
                ROUND(MAX(CASE WHEN st.success=1 THEN st.download_mbps END), 1) AS max_dl,
                ROUND(AVG(CASE WHEN st.success=1 AND st.dl_single_mbps IS NOT NULL
                               THEN st.dl_single_mbps END), 1)                  AS avg_dl_single,
                MAX(st.tested_at)                                                AS last_tested,
                COUNT(st.id)                                                     AS total_tests,
                SUM(CASE WHEN st.success=1 THEN 1 ELSE 0 END)                   AS ok_tests,
                (SELECT public_ip   FROM speed_tests
                 WHERE server_name=s.name AND success=1 ORDER BY tested_at DESC LIMIT 1) AS last_ipv4,
                (SELECT public_ipv6 FROM speed_tests
                 WHERE server_name=s.name AND success=1 ORDER BY tested_at DESC LIMIT 1) AS last_ipv6
            FROM servers s
            LEFT JOIN speed_tests st ON st.server_name = s.name
            {where_sql}
            GROUP BY s.id
            {having_sql}
            ORDER BY {order_sql}
        ''', params).fetchall()
        filter_types = [r['filter_type'] for r in db.execute(
            'SELECT DISTINCT filter_type FROM servers ORDER BY filter_type'
        ).fetchall()]

    existing_names = [r['name'] for r in rows if r['filter_type'] == 'name']

    try:
        _container = current_app.config['GLUETUN_CONTAINER']
        _filters   = get_current_filters(_container)
        active_server = next(iter(_filters.values())).split(',')[0].strip() if _filters else ''
    except Exception:
        active_server = ''

    new_airvpn: list[dict] = []
    new_airvpn_names: list[str] = []
    new_airvpn_countries = ''
    if get_setting('airvpn_new_server_notif', '0') == '1':
        new_airvpn = get_new_airvpn_servers()
        new_airvpn_names = [s['name'] for s in new_airvpn]
        cc_set = {(s['country_code'].upper() if s['country_code'] else s['country'])
                  for s in new_airvpn}
        new_airvpn_countries = ', '.join(sorted(cc_set))

    _stability = get_stability_all()
    active_profile = get_setting('active_profile', 'balanced')
    profile_scores = _score_servers(rows, active_profile, _stability)
    profile_best   = max(profile_scores, key=profile_scores.get) if profile_scores else None

    return render_template(
        'servers_test.html', servers=rows,
        filter_labels=FILTER_LABELS, filter_vars=FILTER_VARS,
        existing_names=existing_names,
        sort=sort, type_filter=type_filter, q=q,
        from_date=from_date, to_date=to_date,
        filter_types=filter_types,
        active_server=active_server,
        confidence=compute_confidence_all(),
        stability=_stability,
        new_airvpn=new_airvpn,
        new_airvpn_names=new_airvpn_names,
        new_airvpn_countries=new_airvpn_countries,
        adaptive_stats=get_hourly_benchmark_stats(),
        profiles=PROFILES,
        active_profile=active_profile,
        profile_scores=profile_scores,
        profile_best=profile_best,
    )


@bp.route('/dash_test')
@login_required
def dash_test():
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
    recent_limit = request.args.get('limit', 10, type=int)
    if recent_limit not in _ALLOWED_LIMITS:
        recent_limit = 10

    with get_db() as db:
        recent_tests = db.execute(
            'SELECT * FROM speed_tests ORDER BY tested_at DESC LIMIT ?', (recent_limit,)
        ).fetchall()
        last_switch = db.execute(
            'SELECT * FROM switches ORDER BY switched_at DESC LIMIT 1'
        ).fetchone()
        server_count = db.execute(
            'SELECT COUNT(*) AS n FROM servers WHERE enabled = 1'
        ).fetchone()['n']
        server_stats = db.execute('''
            SELECT server_name,
                   ROUND(AVG(download_mbps), 1) AS avg_dl,
                   ROUND(MAX(download_mbps), 1) AS max_dl,
                   ROUND(AVG(latency_ms),    0) AS avg_lat,
                   COUNT(*) AS cnt
            FROM speed_tests WHERE success = 1
            GROUP BY server_name
            ORDER BY avg_dl DESC
            LIMIT 12
        ''').fetchall()
        last_cycle = db.execute(
            'SELECT * FROM benchmark_cycles ORDER BY id DESC LIMIT 1'
        ).fetchone()
        total_tests = db.execute(
            'SELECT COUNT(*) AS n FROM speed_tests WHERE success=1'
        ).fetchone()['n']

        sparkline_labels: list[str] = []
        sparkline_dl: list[float] = []
        sparkline_ul: list = []
        sparkline_server: str | None = None
        if current_filters:
            sname = next(iter(current_filters.values())).split(',')[0].strip()
            sparkline_server = sname
            spark_rows = db.execute('''
                SELECT tested_at, download_mbps, upload_mbps
                FROM speed_tests
                WHERE server_name=? AND success=1 AND test_method != 'proxy_qc'
                ORDER BY tested_at DESC LIMIT 20
            ''', (sname,)).fetchall()
            for r in reversed(spark_rows):
                sparkline_labels.append(r['tested_at'][5:16])
                sparkline_dl.append(r['download_mbps'] or 0)
                sparkline_ul.append(r['upload_mbps'])

    return render_template(
        'dash_test.html',
        vpn_status=vpn_status,
        public_ip=public_ip,
        current_server=current_server,
        recent_tests=recent_tests,
        recent_limit=recent_limit,
        last_switch=last_switch,
        server_count=server_count,
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
# Switches log
# ---------------------------------------------------------------------------

@bp.route('/switches')
@login_required
def switches():
    from_date     = request.args.get('from_date',     '').strip()
    to_date       = request.args.get('to_date',       '').strip()
    status_filter = request.args.get('status_filter', '')

    where_parts: list[str] = []
    params: list = []
    if from_date:
        where_parts.append("DATE(switched_at) >= ?")
        params.append(from_date)
    if to_date:
        where_parts.append("DATE(switched_at) <= ?")
        params.append(to_date)
    if status_filter == 'ok':
        where_parts.append("success = 1")
    elif status_filter == 'fail':
        where_parts.append("success = 0")
    where_sql = ('WHERE ' + ' AND '.join(where_parts)) if where_parts else ''

    with get_db() as db:
        rows = db.execute(
            f'SELECT * FROM switches {where_sql} ORDER BY switched_at DESC LIMIT 500',
            params,
        ).fetchall()
    return render_template('switches.html', switches=rows,
                           from_date=from_date, to_date=to_date,
                           status_filter=status_filter)


@bp.route('/switches_test')
@login_required
def switches_test():
    from_date     = request.args.get('from_date',     '').strip()
    to_date       = request.args.get('to_date',       '').strip()
    status_filter = request.args.get('status_filter', '')

    where_parts: list[str] = []
    params: list = []
    if from_date:
        where_parts.append("DATE(switched_at) >= ?")
        params.append(from_date)
    if to_date:
        where_parts.append("DATE(switched_at) <= ?")
        params.append(to_date)
    if status_filter == 'ok':
        where_parts.append("success = 1")
    elif status_filter == 'fail':
        where_parts.append("success = 0")
    where_sql = ('WHERE ' + ' AND '.join(where_parts)) if where_parts else ''

    with get_db() as db:
        rows = db.execute(
            f'SELECT * FROM switches {where_sql} ORDER BY switched_at DESC LIMIT 500',
            params,
        ).fetchall()

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
        'switches_test.html',
        switches=rows,
        from_date=from_date,
        to_date=to_date,
        status_filter=status_filter,
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
            set_setting('test_interval_hours', request.form.get('interval', '6'))
            auto_bm = bool(request.form.get('auto_benchmark'))
            set_setting('auto_benchmark',      '1' if auto_bm else '0')
            set_setting('quick_check_mode',    '1' if request.form.get('quick_check_mode') else '0')
            try:
                qct = float(request.form.get('quick_check_threshold', '15'))
                set_setting('quick_check_threshold', str(max(1.0, min(qct, 100.0))))
            except ValueError:
                pass
            set_setting('adaptive_scheduling', '1' if request.form.get('adaptive_scheduling') else '0')
            set_setting('adaptive_auto_shift', '1' if request.form.get('adaptive_auto_shift') else '0')
            reschedule(float(request.form.get('interval', '6')), enabled=auto_bm)
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
                       'notif_auto_exclude', 'notif_benchmark_end', 'notif_benchmark_failure'):
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
        'notify_mention':           get_setting('notify_mention',          ''),
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
        'weighted_score_current_pct':   get_setting('weighted_score_current_pct', '65'),
        'stability_weight':             get_setting('stability_weight', '30'),
        'active_profile':               get_setting('active_profile', 'balanced'),
        'single_stream_test':           get_setting('single_stream_test', '0'),
        'api_token':                    get_setting('api_token', ''),
    }
    from .database import get_hourly_benchmark_stats
    adaptive_stats = get_hourly_benchmark_stats()
    return render_template(
        'settings.html',
        cfg=cfg,
        next_run=get_next_run(),
        gluetun_container=current_app.config['GLUETUN_CONTAINER'],
        adaptive_stats=adaptive_stats,
        profiles=PROFILES,
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
        entry   = {
            'name':        name,
            'country':     country,
            'country_code': cc,
            'location':    s.get('location', ''),
            'continent':   s.get('continent', ''),
            'load':        load,
            'users':       s.get('users', 0) or 0,
            'bw':          bw,
            'bw_max':      bw_max,
            'avail_mbps':  max(0, bw_max - bw),
            'health':      s.get('health', 'ok'),
        }
        servers.append(entry)
        if country not in countries_map:
            countries_map[country] = {'country': country, 'country_code': cc, 'servers': []}
        countries_map[country]['servers'].append(entry)

    servers.sort(key=lambda x: x['name'])

    countries_list: list[dict] = []
    for cdata in countries_map.values():
        healthy = [sv for sv in cdata['servers'] if sv['health'] == 'ok']
        pool    = healthy or cdata['servers']
        best    = min(pool, key=lambda x: x['load'])['name'] if pool else None
        cdata['best']         = best
        cdata['server_count'] = len(cdata['servers'])
        cdata['servers'].sort(key=lambda x: x['load'])
        countries_list.append(cdata)
    countries_list.sort(key=lambda x: x['country'])

    result = {'servers': servers, 'countries': countries_list}
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
    token = current_app.config.get('METRICS_TOKEN', '')
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
                SUM(CASE WHEN st.success=0 THEN 1 ELSE 0 END)      AS failed_tests
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

    # ── Active server (best-effort) ────────────────────────────────────────
    active_server = ''
    try:
        _filters = get_current_filters(current_app.config['GLUETUN_CONTAINER'])
        active_server = next(iter(_filters.values())).split(',')[0].strip() if _filters else ''
    except Exception:
        pass

    bm_running = int(get_setting('benchmark_running', '0') == '1')

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
