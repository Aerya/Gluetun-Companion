import csv
import io
from functools import wraps

from flask import (
    Blueprint, Response, current_app, flash, jsonify,
    redirect, render_template, request, session, url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from .database import get_db, get_setting, set_setting
from .gluetun import (
    FILTER_VARS, FILTER_LABELS,
    get_current_filters, format_filters,
    get_public_ip, get_vpn_status, switch_server,
)
from .i18n import flash_t, get_t
from .scheduler import get_next_run, reschedule, trigger_now, trigger_single_server

bp = Blueprint('main', __name__)

_HISTORY_PER_PAGE = 50


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

    with get_db() as db:
        recent_tests = db.execute(
            'SELECT * FROM speed_tests ORDER BY tested_at DESC LIMIT 15'
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
                FROM speed_tests WHERE server_name=? AND success=1
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
        last_switch=last_switch,
        server_count=server_count,
        server_stats=server_stats,
        next_run=get_next_run(),
        benchmark_running=benchmark_running,
        last_cycle=last_cycle,
        sparkline_server=sparkline_server,
        sparkline_labels=sparkline_labels,
        sparkline_dl=sparkline_dl,
        sparkline_ul=sparkline_ul,
    )


# ---------------------------------------------------------------------------
# Servers
# ---------------------------------------------------------------------------

@bp.route('/servers')
@login_required
def servers():
    with get_db() as db:
        rows = db.execute('''
            SELECT
                s.id, s.name, s.filter_type, s.enabled,
                s.consecutive_failures, s.created_at,
                ROUND(AVG(CASE WHEN st.success=1 THEN st.download_mbps END), 1) AS avg_dl,
                ROUND(AVG(CASE WHEN st.success=1 THEN st.upload_mbps   END), 1) AS avg_ul,
                ROUND(AVG(CASE WHEN st.success=1 THEN st.latency_ms    END), 0) AS avg_lat,
                ROUND(MAX(CASE WHEN st.success=1 THEN st.download_mbps END), 1) AS max_dl,
                MAX(st.tested_at)                                                AS last_tested,
                COUNT(st.id)                                                     AS total_tests,
                SUM(CASE WHEN st.success=1 THEN 1 ELSE 0 END)                   AS ok_tests,
                (SELECT public_ip   FROM speed_tests
                 WHERE server_name=s.name AND success=1 ORDER BY tested_at DESC LIMIT 1) AS last_ipv4,
                (SELECT public_ipv6 FROM speed_tests
                 WHERE server_name=s.name AND success=1 ORDER BY tested_at DESC LIMIT 1) AS last_ipv6
            FROM servers s
            LEFT JOIN speed_tests st ON st.server_name = s.name
            GROUP BY s.id
            ORDER BY avg_dl DESC NULLS LAST, s.name
        ''').fetchall()
    return render_template('servers.html', servers=rows, filter_labels=FILTER_LABELS, filter_vars=FILTER_VARS)


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

    from_label = format_filters(get_current_filters(cfg['GLUETUN_CONTAINER']))
    ok, err = switch_server(
        row['name'], row['filter_type'],
        cfg['GLUETUN_CONTAINER'], cfg['COMPOSE_DIR'], cfg.get('COMPOSE_PROJECT', ''),
    )
    to_label = f"{FILTER_VARS[row['filter_type']]}={row['name']}"
    with get_db() as db:
        db.execute(
            'INSERT INTO switches (from_server, to_server, reason, success) VALUES (?, ?, ?, ?)',
            (from_label, to_label, 'manual', int(ok)),
        )
    lang = get_setting('ui_lang', 'fr')
    if ok:
        from .notify import send_switch_notification
        send_switch_notification(
            from_server=from_label,
            to_server=to_label,
            from_mbps=None,
            to_mbps=None,
            connect_secs=None,
            to_ipv4=None,
            to_ipv6=None,
            reason='manual',
            discord_url=get_setting('discord_webhook_url') or None,
            apprise_urls=get_setting('apprise_urls') or None,
            lang=lang,
        )
        flash_t('flash_switched', 'success', to=to_label)
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

    pages = max(1, (total + _HISTORY_PER_PAGE - 1) // _HISTORY_PER_PAGE)
    return render_template(
        'history.html',
        tests=tests, per_server=per_server,
        page=page, pages=pages, total=total,
        sort=sort, server_filter=server_filter, method_filter=method_filter,
        server_names=server_names,
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
    with get_db() as db:
        rows = db.execute(
            'SELECT * FROM switches ORDER BY switched_at DESC LIMIT 150'
        ).fetchall()
    return render_template('switches.html', switches=rows)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'save':
            set_setting('test_interval_hours',     request.form.get('interval', '6'))
            set_setting('auto_switch',             '1' if request.form.get('auto_switch') else '0')
            set_setting('connection_wait_seconds', request.form.get('wait_secs', '45'))
            set_setting('speedtest_samples',       request.form.get('speedtest_samples', '3'))
            set_setting('speedtest_duration',      request.form.get('speedtest_duration', '8'))
            set_setting('speedtest_retries',       request.form.get('speedtest_retries', '2'))
            set_setting('server_timeout_secs',     request.form.get('server_timeout_secs', '300'))
            set_setting('auto_exclude_failures',   request.form.get('auto_exclude_failures', '5'))
            set_setting('speedtest_warmup',        '1' if request.form.get('speedtest_warmup') else '0')
            set_setting('speedtest_streams',       request.form.get('speedtest_streams', '4'))
            reschedule(float(request.form.get('interval', '6')))
            flash_t('flash_settings_saved', 'success')

        elif action == 'db_retention':
            set_setting('db_retention_days', request.form.get('db_retention_days', '30'))
            flash_t('flash_retention_saved', 'success')

        elif action == 'notifications':
            set_setting('discord_webhook_url', request.form.get('discord_webhook_url', '').strip())
            set_setting('apprise_urls',        request.form.get('apprise_urls', '').strip())
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
            set_setting('sidecar_speedtest_method', request.form.get('sidecar_speedtest_method', 'auto'))
            flash_t('flash_sidecar_saved', 'success')

        return redirect(url_for('main.settings'))

    cfg = {
        'interval':              get_setting('test_interval_hours', '6'),
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
        'discord_webhook_url':   get_setting('discord_webhook_url', ''),
        'apprise_urls':          get_setting('apprise_urls', ''),
        'sidecar_mode':             get_setting('sidecar_mode', '1'),
        'sidecar_image':            get_setting('sidecar_image', 'ghcr.io/aerya/gluetun-companion-sidecar:latest'),
        'sidecar_port':             get_setting('sidecar_port', '8766'),
        'sidecar_speedtest_method': get_setting('sidecar_speedtest_method', 'auto'),
    }
    return render_template('settings.html', cfg=cfg, next_run=get_next_run())


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


@bp.route('/api/trigger', methods=['POST'])
@login_required
def api_trigger():
    if get_setting('benchmark_running', '0') == '1':
        return jsonify({'status': 'already_running'}), 409
    trigger_now(current_app._get_current_object())
    return jsonify({'status': 'started'})


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
        'next_run':               str(get_next_run()) if get_next_run() else None,
    })
