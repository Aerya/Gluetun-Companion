from functools import wraps

from flask import (
    Blueprint, current_app, flash, jsonify,
    redirect, render_template, request, session, url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from .database import get_db, get_setting, set_setting
from .gluetun import get_current_server, get_public_ip, get_vpn_status, switch_server
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
    host, api_port, container = (
        cfg['GLUETUN_HOST'], cfg['GLUETUN_API_PORT'], cfg['GLUETUN_CONTAINER']
    )

    vpn_status     = get_vpn_status(host, api_port)
    public_ip      = get_public_ip(host, api_port) if vpn_status == 'running' else None
    current_server = get_current_server(container)
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
                s.id, s.name, s.country, s.city, s.region, s.enabled, s.created_at,
                ROUND(AVG(CASE WHEN st.success=1 THEN st.download_mbps END), 1) AS avg_dl,
                ROUND(AVG(CASE WHEN st.success=1 THEN st.latency_ms   END), 0) AS avg_lat,
                ROUND(MAX(CASE WHEN st.success=1 THEN st.download_mbps END), 1) AS max_dl,
                MAX(st.tested_at)                                                AS last_tested,
                COUNT(st.id)                                                     AS total_tests,
                SUM(CASE WHEN st.success=1 THEN 1 ELSE 0 END)                   AS ok_tests
            FROM servers s
            LEFT JOIN speed_tests st ON st.server_name = s.name
            GROUP BY s.id
            ORDER BY avg_dl DESC NULLS LAST, s.name
        ''').fetchall()
    return render_template('servers.html', servers=rows)


@bp.route('/servers/add', methods=['POST'])
@login_required
def add_server():
    name    = request.form.get('name', '').strip()
    country = request.form.get('country', '').strip()
    city    = request.form.get('city', '').strip()
    region  = request.form.get('region', '').strip()

    if not name:
        flash('Le nom du serveur est requis.', 'warning')
        return redirect(url_for('main.servers'))

    with get_db() as db:
        try:
            db.execute(
                'INSERT OR IGNORE INTO servers (name, country, city, region) VALUES (?, ?, ?, ?)',
                (name, country or None, city or None, region or None),
            )
        except Exception as exc:
            flash(str(exc), 'danger')
            return redirect(url_for('main.servers'))

    flash(f'Serveur « {name} » ajouté.', 'success')
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


@bp.route('/servers/switch/<path:server_name>', methods=['POST'])
@login_required
def manual_switch(server_name):
    cfg = current_app.config
    current = get_current_server(cfg['GLUETUN_CONTAINER'])
    ok, err = switch_server(
        server_name,
        cfg['GLUETUN_CONTAINER'],
        cfg['COMPOSE_DIR'],
        cfg.get('COMPOSE_PROJECT', ''),
    )
    with get_db() as db:
        db.execute(
            'INSERT INTO switches (from_server, to_server, reason, success) VALUES (?, ?, ?, ?)',
            (current, server_name, 'manual', int(ok)),
        )
    if ok:
        flash(f'Basculé vers {server_name}.', 'success')
    else:
        flash(f'Échec du basculement : {err}', 'danger')
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
    cfg = current_app.config
    return jsonify({
        'vpn_status':         get_vpn_status(cfg['GLUETUN_HOST'], cfg['GLUETUN_API_PORT']),
        'public_ip':          get_public_ip(cfg['GLUETUN_HOST'], cfg['GLUETUN_API_PORT']),
        'current_server':     get_current_server(cfg['GLUETUN_CONTAINER']),
        'benchmark_running':  get_setting('benchmark_running', '0') == '1',
        'next_run':           str(get_next_run()) if get_next_run() else None,
    })
