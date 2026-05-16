import logging
import threading

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)
_scheduler: BackgroundScheduler | None = None
_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Benchmark job
# ---------------------------------------------------------------------------

def run_benchmark(app):
    """Full benchmark cycle: test each enabled server, then switch to the best."""
    with _lock:
        _do_benchmark(app)


def _do_benchmark(app):
    from .database import get_db, get_setting, set_setting
    from .gluetun import FILTER_VARS, switch_server, wait_for_vpn, get_public_ips, get_current_filters, format_filters
    from .speedtest import test_download, test_latency

    # Mark as running
    set_setting('benchmark_running', '1')
    logger.info('=== Benchmark cycle started ===')

    try:
        container   = app.config['GLUETUN_CONTAINER']
        compose_dir = app.config['COMPOSE_DIR']
        project     = app.config.get('COMPOSE_PROJECT', '')
        proxy_host  = app.config['GLUETUN_HOST']
        proxy_port  = app.config['GLUETUN_PROXY_PORT']

        wait_secs    = int(get_setting('connection_wait_seconds', '45'))
        auto_sw      = get_setting('auto_switch', '1') == '1'
        proxy_user   = get_setting('proxy_username', '') or None
        proxy_pass   = get_setting('proxy_password', '') or None
        dl_duration  = float(get_setting('speedtest_duration', '8'))
        dl_samples   = int(get_setting('speedtest_samples', '3'))
        lat_samples  = min(dl_samples, 3)

        with get_db() as db:
            servers = db.execute(
                'SELECT name, filter_type FROM servers WHERE enabled = 1 ORDER BY name'
            ).fetchall()

        if not servers:
            logger.info('No enabled servers — skipping benchmark')
            return

        results: list[dict] = []

        for row in servers:
            server_name = row['name']
            filter_type = row['filter_type']
            label = f"{FILTER_VARS.get(filter_type, 'SERVER_NAMES')}={server_name}"
            logger.info('Testing: %s', label)

            ok, err = switch_server(server_name, filter_type, container, compose_dir, project)
            if not ok:
                _record_test(server_name, success=False, error=f'Switch failed: {err}')
                continue

            connected = wait_for_vpn(proxy_host, proxy_port, timeout=wait_secs, proxy_user=proxy_user, proxy_password=proxy_pass)
            if not connected:
                _record_test(server_name, success=False, error='VPN connection timeout')
                continue

            try:
                public_ip, public_ipv6 = get_public_ips(proxy_host, proxy_port, proxy_user, proxy_pass)

                dl_median, dl_detail = test_download(
                    proxy_host, proxy_port,
                    duration=dl_duration, samples=dl_samples,
                    proxy_user=proxy_user, proxy_password=proxy_pass,
                )
                lat_median, lat_detail = test_latency(
                    proxy_host, proxy_port,
                    samples=lat_samples,
                    proxy_user=proxy_user, proxy_password=proxy_pass,
                )

                # Log per-endpoint breakdown
                dl_parts = '  '.join(
                    f"{r['endpoint']}:{r['mbps']:.1f}" if r['mbps'] else f"{r['endpoint']}:ERR"
                    for r in dl_detail
                )
                lat_parts = '  '.join(
                    f"{r['endpoint']}:{r['ms']:.0f}ms" if r['ms'] else f"{r['endpoint']}:ERR"
                    for r in lat_detail
                )
                logger.info(
                    '  %s → median %.1f Mbps  median %.0f ms',
                    server_name, dl_median, lat_median,
                )
                logger.info('    DL  [%s]', dl_parts)
                logger.info('    LAT [%s]', lat_parts)

                _record_test(
                    server_name,
                    success=True,
                    download_mbps=dl_median,
                    latency_ms=lat_median,
                    public_ip=public_ip,
                    public_ipv6=public_ipv6,
                )
                results.append({'server': server_name, 'filter_type': filter_type, 'dl': dl_median, 'lat': lat_median})

            except Exception as exc:
                _record_test(server_name, success=False, error=str(exc))
                logger.warning('  %s test error: %s', server_name, exc)

        if auto_sw and results:
            best = max(results, key=lambda r: r['dl'])
            best_label = f"{FILTER_VARS.get(best['filter_type'], 'SERVER_NAMES')}={best['server']}"
            logger.info('Best: %s (%.1f Mbps)', best_label, best['dl'])

            from_label = format_filters(get_current_filters(container))
            if best_label != from_label:
                ok, err = switch_server(best['server'], best['filter_type'], container, compose_dir, project)
                if ok:
                    wait_for_vpn(proxy_host, proxy_port, timeout=wait_secs, proxy_user=proxy_user, proxy_password=proxy_pass)
                    to_ipv4, to_ipv6 = get_public_ips(proxy_host, proxy_port, proxy_user, proxy_pass)
                    logger.info('Switched to best: %s  (%s / %s)', best_label, to_ipv4, to_ipv6)
                else:
                    to_ipv4 = to_ipv6 = None
                _record_switch(
                    from_server=from_label,
                    to_server=best_label,
                    reason='auto_best',
                    success=ok,
                    to_ipv4=to_ipv4,
                    to_ipv6=to_ipv6,
                )
            else:
                logger.info('Already on best: %s', best_label)

    finally:
        set_setting('benchmark_running', '0')
        logger.info('=== Benchmark cycle finished ===')


def _record_test(
    server_name: str,
    *,
    success: bool,
    download_mbps: float | None = None,
    latency_ms: float | None = None,
    public_ip: str | None = None,
    public_ipv6: str | None = None,
    error: str | None = None,
):
    from .database import get_db
    with get_db() as db:
        db.execute(
            '''INSERT INTO speed_tests
               (server_name, download_mbps, latency_ms, public_ip, public_ipv6, success, error_msg)
               VALUES (?, ?, ?, ?, ?, ?, ?)''',
            (server_name, download_mbps, latency_ms, public_ip, public_ipv6, int(success), error),
        )


def _record_switch(
    from_server: str | None,
    to_server: str,
    reason: str,
    success: bool,
    to_ipv4: str | None = None,
    to_ipv6: str | None = None,
):
    from .database import get_db
    with get_db() as db:
        db.execute(
            '''INSERT INTO switches (from_server, to_server, reason, success, to_ipv4, to_ipv6)
               VALUES (?, ?, ?, ?, ?, ?)''',
            (from_server, to_server, reason, int(success), to_ipv4, to_ipv6),
        )


# ---------------------------------------------------------------------------
# Scheduler lifecycle
# ---------------------------------------------------------------------------

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
    _scheduler.start()
    logger.info('Scheduler started — benchmark every %.1f hours', hours)


def reschedule(hours: float):
    if _scheduler:
        _scheduler.reschedule_job(
            'benchmark',
            trigger=IntervalTrigger(hours=hours),
        )
        logger.info('Benchmark rescheduled to every %.1f hours', hours)


def trigger_now(app):
    """Fire benchmark in a daemon thread so the HTTP response returns immediately."""
    t = threading.Thread(target=run_benchmark, args=[app], daemon=True, name='benchmark-now')
    t.start()


def get_next_run():
    if not _scheduler:
        return None
    job = _scheduler.get_job('benchmark')
    return job.next_run_time if job else None
