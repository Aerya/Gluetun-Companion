"""
REST API v1 — protected by Bearer token.

All endpoints require:
  Authorization: Bearer <api_token>

The token is configured in Settings → REST API.
If no token is set, all endpoints return 403 (API disabled).

Base URL : /api/v1/
"""
import logging
from functools import wraps

from flask import Blueprint, current_app, jsonify, request

from .database import get_db, get_setting

logger = logging.getLogger(__name__)

api_bp = Blueprint('api', __name__, url_prefix='/api/v1')


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def _api_auth(f):
    """Require a valid Bearer token.  If no token is configured → 403."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        token = get_setting('api_token', '').strip()
        if not token:
            return jsonify({
                'error': 'API disabled',
                'detail': 'Set an API token in Settings → REST API to enable the API.',
            }), 403
        auth = request.headers.get('Authorization', '')
        if auth != f'Bearer {token}':
            return jsonify({'error': 'Unauthorized', 'detail': 'Invalid or missing Bearer token.'}), 401
        return f(*args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# GET /api/v1/status
# ---------------------------------------------------------------------------

@api_bp.route('/status')
@_api_auth
def status():
    """Current VPN status, active server, benchmark state, next scheduled run."""
    from .gluetun import get_current_filters, format_filters, get_vpn_status
    from .scheduler import get_next_run

    filters     = get_current_filters(current_app.config['GLUETUN_CONTAINER'])
    vpn_status  = get_vpn_status(
        current_app.config['GLUETUN_HOST'],
        current_app.config['GLUETUN_PROXY_PORT'],
    )
    next_run    = get_next_run()

    active_server = None
    if filters:
        active_server = next(iter(filters.values()), None)

    return jsonify({
        'benchmark_running':    get_setting('benchmark_running',    '0') == '1',
        'benchmark_current':    get_setting('benchmark_current_server', '') or None,
        'auto_benchmark':       get_setting('auto_benchmark',       '1') == '1',
        'auto_switch':          get_setting('auto_switch',          '1') == '1',
        'active_server':        active_server,
        'active_filter':        format_filters(filters) if filters else None,
        'vpn_connected':        vpn_status.get('connected', False) if vpn_status else False,
        'next_benchmark_at':    next_run.isoformat() if next_run else None,
    })


# ---------------------------------------------------------------------------
# GET /api/v1/servers
# ---------------------------------------------------------------------------

@api_bp.route('/servers')
@_api_auth
def servers():
    """List all configured servers with aggregated stats."""
    from .database import compute_confidence_all, get_stability_all
    from .gluetun import get_current_filters

    filters = get_current_filters(current_app.config['GLUETUN_CONTAINER'])
    active_name = next(iter(filters.values()), '').split(',')[0].strip() if filters else ''

    conf_map  = compute_confidence_all()
    stab_map  = get_stability_all()

    with get_db() as db:
        rows = db.execute('''
            SELECT
                s.id, s.name, s.filter_type, s.enabled, s.consecutive_failures,
                ROUND(AVG(CASE WHEN st.success=1 AND st.test_method NOT IN ('proxy_qc')
                               THEN st.download_mbps END), 2) AS avg_dl,
                ROUND(AVG(CASE WHEN st.success=1 AND st.test_method NOT IN ('proxy_qc')
                               THEN st.upload_mbps END), 2)   AS avg_ul,
                ROUND(AVG(CASE WHEN st.success=1 AND st.test_method NOT IN ('proxy_qc')
                               THEN st.latency_ms END), 1)    AS avg_lat,
                COUNT(CASE WHEN st.success=1 THEN 1 END)      AS tests_ok,
                COUNT(CASE WHEN st.success=0 THEN 1 END)      AS tests_fail,
                MAX(st.tested_at)                              AS last_tested_at
            FROM servers s
            LEFT JOIN speed_tests st ON st.server_name = s.name
            GROUP BY s.id
            ORDER BY s.name
        ''').fetchall()

    result = []
    for r in rows:
        conf  = conf_map.get(r['name'], {})
        stab  = stab_map.get(r['name'], {})
        result.append({
            'id':                   r['id'],
            'name':                 r['name'],
            'filter_type':          r['filter_type'],
            'enabled':              bool(r['enabled']),
            'is_active':            r['name'] == active_name,
            'consecutive_failures': r['consecutive_failures'],
            'avg_dl_mbps':          r['avg_dl'],
            'avg_ul_mbps':          r['avg_ul'],
            'avg_latency_ms':       r['avg_lat'],
            'tests_ok':             r['tests_ok'],
            'tests_fail':           r['tests_fail'],
            'last_tested_at':       r['last_tested_at'],
            'confidence':           conf.get('level'),
            'confidence_nb':        conf.get('nb'),
            'avg_jitter_ms':        stab.get('avg_jitter'),
            'avg_loss_pct':         stab.get('avg_loss'),
            'avg_dns_ms':           stab.get('avg_dns'),
        })

    return jsonify({'count': len(result), 'servers': result})


# ---------------------------------------------------------------------------
# GET /api/v1/history
# ---------------------------------------------------------------------------

@api_bp.route('/history')
@_api_auth
def history():
    """Recent speed tests.

    Query params:
      limit  (int, default 50, max 500)
      offset (int, default 0)
      server (str, optional) — filter by server name
    """
    try:
        limit  = min(int(request.args.get('limit',  50)),  500)
        offset = max(int(request.args.get('offset',  0)),    0)
    except ValueError:
        return jsonify({'error': 'limit and offset must be integers'}), 400

    server = request.args.get('server', '').strip() or None

    with get_db() as db:
        if server:
            rows = db.execute(
                '''SELECT id, server_name, download_mbps, upload_mbps, latency_ms,
                          public_ip, public_ipv6, success, error_msg, test_method,
                          jitter_ms, packet_loss_pct, ping_min_ms, ping_max_ms,
                          dns_latency_ms, test_trigger, tested_at
                   FROM speed_tests WHERE server_name=?
                   ORDER BY tested_at DESC LIMIT ? OFFSET ?''',
                (server, limit, offset),
            ).fetchall()
            total = db.execute(
                'SELECT COUNT(*) FROM speed_tests WHERE server_name=?', (server,)
            ).fetchone()[0]
        else:
            rows = db.execute(
                '''SELECT id, server_name, download_mbps, upload_mbps, latency_ms,
                          public_ip, public_ipv6, success, error_msg, test_method,
                          jitter_ms, packet_loss_pct, ping_min_ms, ping_max_ms,
                          dns_latency_ms, test_trigger, tested_at
                   FROM speed_tests
                   ORDER BY tested_at DESC LIMIT ? OFFSET ?''',
                (limit, offset),
            ).fetchall()
            total = db.execute('SELECT COUNT(*) FROM speed_tests').fetchone()[0]

    results = [dict(r) for r in rows]
    # Convert SQLite integers to Python bools
    for r in results:
        r['success'] = bool(r['success'])

    return jsonify({
        'total':   total,
        'limit':   limit,
        'offset':  offset,
        'count':   len(results),
        'results': results,
    })


# ---------------------------------------------------------------------------
# GET /api/v1/switches
# ---------------------------------------------------------------------------

@api_bp.route('/switches')
@_api_auth
def switches():
    """Recent server switches.

    Query params:
      limit  (int, default 20, max 200)
      offset (int, default 0)
    """
    try:
        limit  = min(int(request.args.get('limit',  20)),  200)
        offset = max(int(request.args.get('offset',  0)),    0)
    except ValueError:
        return jsonify({'error': 'limit and offset must be integers'}), 400

    with get_db() as db:
        rows = db.execute(
            '''SELECT id, from_server, to_server, reason, success,
                      connect_secs, from_mbps, to_mbps, to_ipv4, to_ipv6, switched_at
               FROM switches
               ORDER BY switched_at DESC LIMIT ? OFFSET ?''',
            (limit, offset),
        ).fetchall()
        total = db.execute('SELECT COUNT(*) FROM switches').fetchone()[0]

    results = [dict(r) for r in rows]
    for r in results:
        r['success'] = bool(r['success'])

    return jsonify({
        'total':   total,
        'limit':   limit,
        'offset':  offset,
        'count':   len(results),
        'results': results,
    })


# ---------------------------------------------------------------------------
# POST /api/v1/benchmark/trigger
# ---------------------------------------------------------------------------

@api_bp.route('/benchmark/trigger', methods=['POST'])
@_api_auth
def benchmark_trigger():
    """Trigger a full benchmark cycle immediately.

    Returns immediately — the benchmark runs in a background thread.
    Check GET /api/v1/status for progress (benchmark_running).
    """
    if get_setting('benchmark_running', '0') == '1':
        return jsonify({
            'status':  'already_running',
            'message': 'A benchmark is already in progress.',
        }), 409

    from .scheduler import trigger_now
    trigger_now(current_app._get_current_object())
    logger.info('REST API: full benchmark triggered')
    return jsonify({
        'status':  'triggered',
        'message': 'Full benchmark started in background.',
    }), 202


# ---------------------------------------------------------------------------
# POST /api/v1/benchmark/trigger-quick
# ---------------------------------------------------------------------------

@api_bp.route('/benchmark/trigger-quick', methods=['POST'])
@_api_auth
def benchmark_trigger_quick():
    """Trigger a quick proxy benchmark on the currently active server only.

    No VPN restart, no container disruption. Result available in GET /api/v1/history.
    Returns immediately — runs in background.
    """
    if get_setting('benchmark_running', '0') == '1':
        return jsonify({
            'status':  'already_running',
            'message': 'A benchmark is already in progress.',
        }), 409

    from .scheduler import trigger_quick_now
    trigger_quick_now(current_app._get_current_object())
    logger.info('REST API: quick benchmark triggered')
    return jsonify({
        'status':  'triggered',
        'message': 'Quick benchmark started in background.',
    }), 202
