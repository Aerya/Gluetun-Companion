from functools import wraps

from flask import (
    Blueprint, current_app, flash, jsonify,
    redirect, render_template, request, session, url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from .database import get_db, get_setting, set_setting
from .gluetun import (
    FILTER_VARS, FILTER_LABELS,
    get_current_filters, format_filters,
    get_public_ip, get_vpn_status, switch_server,
)
from .scheduler import get_next_run, reschedule, trigger_now

bp = Blueprint('main', __name__)


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
            # First-run: create account with whatever credentials were entered
            set_setting('admin_username', username)
            set_setting('admin_password_hash', generate_password_hash(password))
            session['logged_in'] = True
            session['username'] = username
            flash('Compte créé avec succès.', 'success')
            return redirect(url_for('main.dashboard'))

        if username == stored_user and check_password_hash(stored_hash, password):
            session['logged_in'] = True
            session['username'] = username
            return redirect(url_for('main.dashboard'))

        flash('Identifiants incorrects.', 'danger')

    return render_template('login.html')


@bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('main.login'))


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

    vpn_status      = get_vpn_status(proxy_host, proxy_port, px_user, px_pass)
    public_ip       = get_public_ip(proxy_host, proxy_port, px_user, px_pass) if vpn_status == 'running' else None
    current_filters = get_current_filters(container)
    current_server  = format_filters(current_filters)
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

        # Per-server best download for quick dashboard chart
        server_stats = db.execute('''
            SELECT server_name,
                   ROUND(AVG(download_mbps), 1) AS avg_dl,
                   ROUND(MAX(download_mbps), 1) AS max_dl
            FROM speed_tests WHERE success = 1
            GROUP BY server_name
            ORDER BY avg_dl DESC
            LIMIT 12
        ''').fetchall()

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
                s.id, s.name, s.filter_type, s.enabled, s.created_at,
                ROUND(AVG(CASE WHEN st.success=1 THEN st.download_mbps END), 1) AS avg_dl,
                ROUND(AVG(CASE WHEN st.success=1 THEN st.latency_ms   END), 0) AS avg_lat,
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
    """Read all Gluetun filter env vars from the container and bulk-insert each value."""
    container_name = current_app.config['GLUETUN_CONTAINER']
    filters = get_current_filters(container_name)

    if not filters:
        flash('Aucune variable de filtre trouvée dans le container Gluetun (SERVER_NAMES, SERVER_COUNTRIES…).', 'danger')
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
        flash(f'{added} entrée(s) importée(s) : {", ".join(imported)}.', 'success')
    else:
        flash('Ces entrées sont déjà dans la liste.', 'info')
    return redirect(url_for('main.servers'))


@bp.route('/servers/add', methods=['POST'])
@login_required
def add_server():
    name        = request.form.get('name', '').strip()
    filter_type = request.form.get('filter_type', 'name').strip()

    if not name:
        flash('La valeur est requise.', 'warning')
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

    flash(f'Ajouté : {FILTER_VARS[filter_type]}={name}.', 'success')
    return redirect(url_for('main.servers'))


@bp.route('/servers/toggle/<int:server_id>', methods=['POST'])
@login_required
def toggle_server(server_id):
    with get_db() as db:
        db.execute(
            'UPDATE servers SET enabled = 1 - enabled WHERE id = ?',
            (server_id,),
        )
    return redirect(url_for('main.servers'))


@bp.route('/servers/delete/<int:server_id>', methods=['POST'])
@login_required
def delete_server(server_id):
    with get_db() as db:
        db.execute('DELETE FROM servers WHERE id = ?', (server_id,))
    flash('Serveur supprimé.', 'success')
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
        row['name'],
        row['filter_type'],
        cfg['GLUETUN_CONTAINER'],
        cfg['COMPOSE_DIR'],
        cfg.get('COMPOSE_PROJECT', ''),
    )
    to_label = f"{FILTER_VARS[row['filter_type']]}={row['name']}"
    with get_db() as db:
        db.execute(
            'INSERT INTO switches (from_server, to_server, reason, success) VALUES (?, ?, ?, ?)',
            (from_label, to_label, 'manual', int(ok)),
        )
    if ok:
        flash(f'Basculé vers {to_label}.', 'success')
    else:
        flash(f'Échec : {err}', 'danger')
    return redirect(url_for('main.servers'))


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

@bp.route('/history')
@login_required
def history():
    with get_db() as db:
        tests = db.execute(
            'SELECT * FROM speed_tests ORDER BY tested_at DESC LIMIT 300'
        ).fetchall()
        per_server = db.execute('''
            SELECT server_name,
                   ROUND(AVG(download_mbps), 1) AS avg_dl,
                   ROUND(MIN(download_mbps), 1) AS min_dl,
                   ROUND(MAX(download_mbps), 1) AS max_dl,
                   COUNT(*) AS cnt
            FROM speed_tests WHERE success = 1
            GROUP BY server_name
            ORDER BY avg_dl DESC
        ''').fetchall()
    return render_template('history.html', tests=tests, per_server=per_server)


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
            interval  = request.form.get('interval', '6')
            auto_sw   = '1' if request.form.get('auto_switch') else '0'
            wait_secs = request.form.get('wait_secs', '45')
            samples   = request.form.get('speedtest_samples', '3')
            duration  = request.form.get('speedtest_duration', '8')

            set_setting('test_interval_hours', interval)
            set_setting('auto_switch', auto_sw)
            set_setting('connection_wait_seconds', wait_secs)
            set_setting('speedtest_samples', samples)
            set_setting('speedtest_duration', duration)
            reschedule(float(interval))
            flash('Paramètres enregistrés.', 'success')

        elif action == 'credentials':
            new_user = request.form.get('username', '').strip()
            new_pass = request.form.get('password', '')
            if new_user:
                set_setting('admin_username', new_user)
            if new_pass:
                set_setting('admin_password_hash', generate_password_hash(new_pass))
            flash('Identifiants mis à jour.', 'success')

        elif action == 'proxy_credentials':
            set_setting('proxy_username', request.form.get('proxy_username', '').strip())
            set_setting('proxy_password', request.form.get('proxy_password', ''))
            flash('Identifiants proxy enregistrés.', 'success')

        return redirect(url_for('main.settings'))

    cfg = {
        'interval':       get_setting('test_interval_hours', '6'),
        'auto_sw':        get_setting('auto_switch', '1'),
        'size_mb':        get_setting('test_file_size_mb', '10'),
        'wait_secs':      get_setting('connection_wait_seconds', '45'),
        'username':          get_setting('admin_username', 'admin'),
        'proxy_username':    get_setting('proxy_username', ''),
        'proxy_password':    get_setting('proxy_password', ''),
        'speedtest_samples': get_setting('speedtest_samples', '3'),
        'speedtest_duration':get_setting('speedtest_duration', '8'),
    }
    return render_template('settings.html', cfg=cfg, next_run=get_next_run())


# ---------------------------------------------------------------------------
# JSON API
# ---------------------------------------------------------------------------

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
    cfg      = current_app.config
    px_user  = get_setting('proxy_username') or None
    px_pass  = get_setting('proxy_password') or None
    return jsonify({
        'vpn_status':        get_vpn_status(cfg['GLUETUN_HOST'], cfg['GLUETUN_PROXY_PORT'], px_user, px_pass),
        'public_ip':         get_public_ip(cfg['GLUETUN_HOST'], cfg['GLUETUN_PROXY_PORT'], px_user, px_pass),
        'current_server':    format_filters(get_current_filters(cfg['GLUETUN_CONTAINER'])),
        'benchmark_running': get_setting('benchmark_running', '0') == '1',
        'next_run':          str(get_next_run()) if get_next_run() else None,
    })
