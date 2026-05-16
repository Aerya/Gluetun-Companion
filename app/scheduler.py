import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)
_scheduler: BackgroundScheduler | None = None
_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Weighted score for best-server selection
# ---------------------------------------------------------------------------

def _weighted_score(server_name: str, current_dl: float, db) -> float:
    """
    Blend the current cycle's result (65%) with exponentially-weighted
    historical data (35%) so that a single lucky/unlucky run doesn't dominate.
    """
    rows = db.execute(
        'SELECT download_mbps FROM speed_tests '
        'WHERE server_name=? AND success=1 ORDER BY tested_at DESC LIMIT 5',
        (server_name,),
    ).fetchall()
    if not rows:
        return current_dl
    weights = [0.5 ** i for i in range(len(rows))]
    hist = sum(w * r['download_mbps'] for w, r in zip(weights, rows)) / sum(weights)
    return 0.65 * current_dl + 0.35 * hist


# ---------------------------------------------------------------------------
# Per-server test (isolated function so we can run it in a timed thread)
# ---------------------------------------------------------------------------

def _test_one_server(
    server_name: str,
    filter_type: str,
    container: str,
    compose_dir: str,
    project: str,
    proxy_host: str,
    proxy_port: int,
    proxy_user: str | None,
    proxy_pass: str | None,
    wait_secs: int,
    dl_duration: float,
    dl_samples: int,
    lat_samples: int,
    do_upload: bool,
    warmup: float,
    dl_streams: int,
) -> dict:
    """
    Full test cycle for one server: switch → wait → probe IPs → DL → UL → LAT.
    Returns a result dict on success, raises on failure.
    """
    from .gluetun import FILTER_VARS, switch_server, wait_for_vpn, get_public_ips
    from .speedtest import test_download, test_latency, test_upload

    label = f"{FILTER_VARS.get(filter_type, 'SERVER_NAMES')}={server_name}"
    logger.info('Testing: %s', label)

    ok, err = switch_server(server_name, filter_type, container, compose_dir, project)
    if not ok:
        raise RuntimeError(f'Switch failed: {err}')

    connected, connect_secs = wait_for_vpn(
        proxy_host, proxy_port, timeout=wait_secs,
        proxy_user=proxy_user, proxy_password=proxy_pass,
    )
    if not connected:
        raise RuntimeError(f'VPN connection timeout after {connect_secs:.0f}s')

    public_ip, public_ipv6 = get_public_ips(proxy_host, proxy_port, proxy_user, proxy_pass)

    dl_median, dl_detail = test_download(
        proxy_host, proxy_port,
        duration=dl_duration, samples=dl_samples, warmup=warmup, streams=dl_streams,
        proxy_user=proxy_user, proxy_password=proxy_pass,
    )
    lat_median, lat_detail = test_latency(
        proxy_host, proxy_port, samples=lat_samples,
        proxy_user=proxy_user, proxy_password=proxy_pass,
    )

    ul_median: float | None = None
    if do_upload:
        try:
            ul_median, ul_detail = test_upload(
                proxy_host, proxy_port, duration=dl_duration,
                proxy_user=proxy_user, proxy_password=proxy_pass,
            )
            ul_parts = '  '.join(
                f"{r['endpoint']}:{r['mbps']:.1f}" if r['mbps'] else f"{r['endpoint']}:ERR"
                for r in ul_detail
            )
            logger.info('    UL  [%s]', ul_parts)
        except Exception as exc:
            logger.warning('  Upload test failed for %s: %s', server_name, exc)

    dl_parts = '  '.join(
        f"{r['endpoint']}:{r['mbps']:.1f}" if r['mbps'] else f"{r['endpoint']}:ERR"
        for r in dl_detail
    )
    lat_parts = '  '.join(
        f"{r['endpoint']}:{r['ms']:.0f}ms" if r['ms'] else f"{r['endpoint']}:ERR"
        for r in lat_detail
    )
    logger.info(
        '  %s → DL %.1f Mbps  UL %s  LAT %.0f ms  connect %.0fs',
        server_name, dl_median,
        f'{ul_median:.1f}' if ul_median else '—',
        lat_median, connect_secs,
    )
    logger.info('    DL  [%s]', dl_parts)
    logger.info('    LAT [%s]', lat_parts)

    _record_test(
        server_name,
        success=True,
        download_mbps=dl_median,
        upload_mbps=ul_median,
        latency_ms=lat_median,
        public_ip=public_ip,
        public_ipv6=public_ipv6,
    )

    return {
        'server': server_name,
        'filter_type': filter_type,
        'dl': dl_median,
        'ul': ul_median,
        'lat': lat_median,
        'connect_secs': connect_secs,
    }


def _test_server_with_retry(
    server_name: str,
    filter_type: str,
    container: str,
    compose_dir: str,
    project: str,
    proxy_host: str,
    proxy_port: int,
    proxy_user: str | None,
    proxy_pass: str | None,
    wait_secs: int,
    dl_duration: float,
    dl_samples: int,
    lat_samples: int,
    do_upload: bool,
    warmup: float,
    dl_streams: int,
    max_retries: int,
    timeout_secs: int,
) -> dict | None:
    """
    Wraps _test_one_server with retry logic and a hard wall-clock timeout.
    Returns result dict on success, None on final failure (error already recorded).
    """
    last_err = 'Unknown error'
    for attempt in range(max_retries + 1):
        try:
            with ThreadPoolExecutor(max_workers=1) as ex:
                future = ex.submit(
                    _test_one_server,
                    server_name, filter_type, container, compose_dir, project,
                    proxy_host, proxy_port, proxy_user, proxy_pass,
                    wait_secs, dl_duration, dl_samples, lat_samples, do_upload, warmup, dl_streams,
                )
                return future.result(timeout=timeout_secs)
        except FuturesTimeout:
            last_err = f'Timed out after {timeout_secs}s'
            logger.warning('  %s timed out (%ds) — skipping retries', server_name, timeout_secs)
            break   # timeout = don't retry (server is just gone)
        except Exception as exc:
            last_err = str(exc)
            if attempt < max_retries:
                logger.warning(
                    '  Retry %d/%d for %s: %s', attempt + 1, max_retries, server_name, exc
                )
                time.sleep(5)

    _record_test(server_name, success=False, error=last_err)
    return None


# ---------------------------------------------------------------------------
# Benchmark cycle
# ---------------------------------------------------------------------------

def run_benchmark(app):
    with _lock:
        _do_benchmark(app)


def _do_benchmark(app):
    from .database import get_db, get_setting, set_setting
    from .gluetun import (
        FILTER_VARS, switch_server, wait_for_vpn,
        get_public_ips, get_current_filters, format_filters,
    )

    set_setting('benchmark_running', '1')
    cycle_start = time.time()
    logger.info('=== Benchmark cycle started ===')

    try:
        container   = app.config['GLUETUN_CONTAINER']
        compose_dir = app.config['COMPOSE_DIR']
        project     = app.config.get('COMPOSE_PROJECT', '')
        proxy_host  = app.config['GLUETUN_HOST']
        proxy_port  = app.config['GLUETUN_PROXY_PORT']

        wait_secs      = int(get_setting('connection_wait_seconds', '45'))
        auto_sw        = get_setting('auto_switch', '1') == '1'
        proxy_user     = get_setting('proxy_username', '') or None
        proxy_pass     = get_setting('proxy_password', '') or None
        dl_duration    = float(get_setting('speedtest_duration', '8'))
        dl_samples     = int(get_setting('speedtest_samples', '3'))
        lat_samples    = min(dl_samples, 3)
        max_retries    = int(get_setting('speedtest_retries', '2'))
        timeout_secs   = int(get_setting('server_timeout_secs', '300'))
        auto_exclude   = int(get_setting('auto_exclude_failures', '5'))
        do_upload      = get_setting('speedtest_upload', '1') == '1'
        warmup         = 2.0 if get_setting('speedtest_warmup', '1') == '1' else 0.0
        dl_streams     = int(get_setting('speedtest_streams', '4'))

        with get_db() as db:
            servers = db.execute(
                'SELECT name, filter_type FROM servers WHERE enabled = 1 ORDER BY name'
            ).fetchall()
            cycle_id = db.execute(
                'INSERT INTO benchmark_cycles (started_at) VALUES (CURRENT_TIMESTAMP)'
            ).lastrowid

        if not servers:
            logger.info('No enabled servers — skipping benchmark')
            return

        results: list[dict] = []

        for row in servers:
            result = _test_server_with_retry(
                row['name'], row['filter_type'],
                container, compose_dir, project,
                proxy_host, proxy_port, proxy_user, proxy_pass,
                wait_secs, dl_duration, dl_samples, lat_samples,
                do_upload, warmup, dl_streams, max_retries, timeout_secs,
            )
            if result:
                results.append(result)
                _update_consecutive_failures(row['name'], success=True, threshold=auto_exclude)
            else:
                _update_consecutive_failures(row['name'], success=False, threshold=auto_exclude)

        best_server_label: str | None = None
        if auto_sw and results:
            with get_db() as db:
                best = max(results, key=lambda r: _weighted_score(r['server'], r['dl'], db))
            best_label = f"{FILTER_VARS.get(best['filter_type'], 'SERVER_NAMES')}={best['server']}"
            logger.info('Best (weighted): %s (%.1f Mbps current)', best_label, best['dl'])
            best_server_label = best_label

            from_label = format_filters(get_current_filters(container))

            # From-server's speed in this cycle (for delta logging)
            from_name = next(iter(get_current_filters(container).values()), '').split(',')[0].strip()
            from_result = next((r for r in results if r['server'] == from_name), None)
            from_mbps = from_result['dl'] if from_result else None

            if best_label != from_label:
                ok, err = switch_server(
                    best['server'], best['filter_type'], container, compose_dir, project
                )
                if ok:
                    connected, connect_secs = wait_for_vpn(
                        proxy_host, proxy_port, timeout=wait_secs,
                        proxy_user=proxy_user, proxy_password=proxy_pass,
                    )
                    to_ipv4, to_ipv6 = get_public_ips(proxy_host, proxy_port, proxy_user, proxy_pass)
                    logger.info(
                        'Switched to best: %s  (%s / %s)  connect %.0fs',
                        best_label, to_ipv4, to_ipv6, connect_secs,
                    )
                else:
                    connect_secs = 0.0
                    to_ipv4 = to_ipv6 = None
                _record_switch(
                    from_server=from_label,
                    to_server=best_label,
                    reason='auto_best',
                    success=ok,
                    connect_secs=connect_secs if ok else None,
                    from_mbps=from_mbps,
                    to_mbps=best['dl'],
                    to_ipv4=to_ipv4,
                    to_ipv6=to_ipv6,
                )
                if ok:
                    from .notify import send_switch_notification
                    send_switch_notification(
                        from_server=from_label,
                        to_server=best_label,
                        from_mbps=from_mbps,
                        to_mbps=best['dl'],
                        connect_secs=connect_secs,
                        to_ipv4=to_ipv4,
                        to_ipv6=to_ipv6,
                        reason='auto_best',
                        discord_url=get_setting('discord_webhook_url') or None,
                        apprise_urls=get_setting('apprise_urls') or None,
                    )
            else:
                logger.info('Already on best: %s', best_label)

        duration_secs = round(time.time() - cycle_start, 1)
        logger.info('=== Benchmark cycle finished in %.0fs ===', duration_secs)

        with get_db() as db:
            db.execute(
                '''UPDATE benchmark_cycles
                   SET finished_at=CURRENT_TIMESTAMP, duration_secs=?, servers_tested=?, best_server=?
                   WHERE id=?''',
                (duration_secs, len(results), best_server_label, cycle_id),
            )

    finally:
        set_setting('benchmark_running', '0')


# ---------------------------------------------------------------------------
# Single-server on-demand test (launched from UI "Tester maintenant")
# ---------------------------------------------------------------------------

def test_single_server(app, server_name: str, filter_type: str):
    with _lock:
        _do_single_server(app, server_name, filter_type)


def _do_single_server(app, server_name: str, filter_type: str):
    from .database import get_db, get_setting, set_setting

    set_setting('benchmark_running', '1')
    logger.info('Single-server test: %s (%s)', server_name, filter_type)

    try:
        container   = app.config['GLUETUN_CONTAINER']
        compose_dir = app.config['COMPOSE_DIR']
        project     = app.config.get('COMPOSE_PROJECT', '')
        proxy_host  = app.config['GLUETUN_HOST']
        proxy_port  = app.config['GLUETUN_PROXY_PORT']

        wait_secs    = int(get_setting('connection_wait_seconds', '45'))
        proxy_user   = get_setting('proxy_username', '') or None
        proxy_pass   = get_setting('proxy_password', '') or None
        dl_duration  = float(get_setting('speedtest_duration', '8'))
        dl_samples   = int(get_setting('speedtest_samples', '3'))
        lat_samples  = min(dl_samples, 3)
        max_retries  = int(get_setting('speedtest_retries', '2'))
        timeout_secs = int(get_setting('server_timeout_secs', '300'))
        auto_exclude = int(get_setting('auto_exclude_failures', '5'))
        do_upload    = get_setting('speedtest_upload', '1') == '1'
        warmup       = 2.0 if get_setting('speedtest_warmup', '1') == '1' else 0.0
        dl_streams   = int(get_setting('speedtest_streams', '4'))

        result = _test_server_with_retry(
            server_name, filter_type,
            container, compose_dir, project,
            proxy_host, proxy_port, proxy_user, proxy_pass,
            wait_secs, dl_duration, dl_samples, lat_samples,
            do_upload, warmup, dl_streams, max_retries, timeout_secs,
        )
        if result:
            _update_consecutive_failures(server_name, success=True, threshold=auto_exclude)
            logger.info('Single-server test done: %s %.1f Mbps', server_name, result['dl'])
        else:
            _update_consecutive_failures(server_name, success=False, threshold=auto_exclude)
    finally:
        set_setting('benchmark_running', '0')


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _record_test(
    server_name: str,
    *,
    success: bool,
    download_mbps: float | None = None,
    upload_mbps: float | None = None,
    latency_ms: float | None = None,
    public_ip: str | None = None,
    public_ipv6: str | None = None,
    error: str | None = None,
):
    from .database import get_db
    with get_db() as db:
        db.execute(
            '''INSERT INTO speed_tests
               (server_name, download_mbps, upload_mbps, latency_ms,
                public_ip, public_ipv6, success, error_msg)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
            (server_name, download_mbps, upload_mbps, latency_ms,
             public_ip, public_ipv6, int(success), error),
        )


def _record_switch(
    from_server: str | None,
    to_server: str,
    reason: str,
    success: bool,
    connect_secs: float | None = None,
    from_mbps: float | None = None,
    to_mbps: float | None = None,
    to_ipv4: str | None = None,
    to_ipv6: str | None = None,
):
    from .database import get_db
    with get_db() as db:
        db.execute(
            '''INSERT INTO switches
               (from_server, to_server, reason, success,
                connect_secs, from_mbps, to_mbps, to_ipv4, to_ipv6)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (from_server, to_server, reason, int(success),
             connect_secs, from_mbps, to_mbps, to_ipv4, to_ipv6),
        )


def _update_consecutive_failures(server_name: str, success: bool, threshold: int):
    from .database import get_db
    with get_db() as db:
        if success:
            db.execute(
                'UPDATE servers SET consecutive_failures=0 WHERE name=?', (server_name,)
            )
        else:
            db.execute(
                'UPDATE servers SET consecutive_failures=consecutive_failures+1 WHERE name=?',
                (server_name,),
            )
            if threshold > 0:
                row = db.execute(
                    'SELECT consecutive_failures FROM servers WHERE name=?', (server_name,)
                ).fetchone()
                if row and row['consecutive_failures'] >= threshold:
                    db.execute('UPDATE servers SET enabled=0 WHERE name=?', (server_name,))
                    logger.warning(
                        'Server %s auto-disabled after %d consecutive failures',
                        server_name, row['consecutive_failures'],
                    )


# ---------------------------------------------------------------------------
# Scheduler lifecycle
# ---------------------------------------------------------------------------

def purge_old_tests(app):
    """Delete speed_tests older than db_retention_days. 0 = disabled."""
    from .database import get_db, get_setting
    with app.app_context():
        days = int(get_setting('db_retention_days', '30'))
    if days <= 0:
        return
    with get_db() as db:
        deleted = db.execute(
            "DELETE FROM speed_tests WHERE tested_at < datetime('now', ? || ' days')",
            (f'-{days}',),
        ).rowcount
    if deleted:
        logger.info('DB purge: removed %d speed_tests older than %d days', deleted, days)


def start_scheduler(app):
    global _scheduler
    from .database import get_setting

    with app.app_context():
        hours = float(get_setting('test_interval_hours', '6'))

    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(
        run_benchmark,
        trigger=IntervalTrigger(hours=hours),
        args=[app],
        id='benchmark',
        replace_existing=True,
        misfire_grace_time=300,
    )
    _scheduler.add_job(
        purge_old_tests,
        trigger=IntervalTrigger(hours=24),
        args=[app],
        id='db_purge',
        replace_existing=True,
        misfire_grace_time=3600,
    )
    _scheduler.start()
    logger.info('Scheduler started — benchmark every %.1f hours', hours)


def reschedule(hours: float):
    if _scheduler:
        _scheduler.reschedule_job('benchmark', trigger=IntervalTrigger(hours=hours))
        logger.info('Benchmark rescheduled to every %.1f hours', hours)


def trigger_now(app):
    t = threading.Thread(target=run_benchmark, args=[app], daemon=True, name='benchmark-now')
    t.start()


def trigger_single_server(app, server_name: str, filter_type: str):
    t = threading.Thread(
        target=test_single_server,
        args=[app, server_name, filter_type],
        daemon=True,
        name=f'test-{server_name}',
    )
    t.start()


def get_next_run():
    if not _scheduler:
        return None
    job = _scheduler.get_job('benchmark')
    return job.next_run_time if job else None
