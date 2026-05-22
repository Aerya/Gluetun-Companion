import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)
_scheduler: BackgroundScheduler | None = None
_lock = threading.Lock()

# Docker event listener state
_last_docker_event_ts: float = 0.0   # epoch of last event-triggered quick check
_DOCKER_EVENT_COOLDOWN = 300          # minimum seconds between two event-triggered checks


# ---------------------------------------------------------------------------
# Weighted score for best-server selection
# ---------------------------------------------------------------------------

def _weighted_score(
    server_name: str,
    current_dl: float,
    db,
    current_pct: float = 65.0,
    confidence_factor: float = 1.0,
    jitter_ms: float | None = None,
    packet_loss_pct: float | None = None,
) -> float:
    """
    Blend the current cycle's result with exponentially-weighted historical
    data so that a single lucky/unlucky run doesn't dominate.
    ``current_pct`` controls how much weight (0–100) goes to the current
    measurement; the remainder goes to the exponential history.
    ``confidence_factor`` is a light penalty from the confidence score:
      HIGH → 1.0 (no penalty), MEDIUM → 0.95, LOW → 0.85.
    ``jitter_ms`` and ``packet_loss_pct`` apply additional stability penalties:
      - jitter:  up to −15 % at 150 ms
      - loss:    up to −25 % at 10 % packet loss
    """
    rows = db.execute(
        'SELECT download_mbps FROM speed_tests '
        'WHERE server_name=? AND success=1 ORDER BY tested_at DESC LIMIT 5',
        (server_name,),
    ).fetchall()
    if not rows:
        base = current_dl
    else:
        w_cur  = max(0.0, min(current_pct, 100.0)) / 100.0
        w_hist = 1.0 - w_cur
        weights = [0.5 ** i for i in range(len(rows))]
        hist = sum(w * r['download_mbps'] for w, r in zip(weights, rows)) / sum(weights)
        base = w_cur * current_dl + w_hist * hist

    # Stability penalties (optional — None means no data → no penalty)
    jitter_factor = max(0.85, 1.0 - min(jitter_ms / 1000.0, 0.15)) \
        if jitter_ms is not None else 1.0
    loss_factor   = max(0.75, 1.0 - min(packet_loss_pct / 40.0, 0.25)) \
        if (packet_loss_pct is not None and packet_loss_pct > 0) else 1.0

    return base * confidence_factor * jitter_factor * loss_factor


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
    warmup: float,
    dl_streams: int,
) -> dict:
    """
    Full test cycle for one server: switch → wait → probe IPs → DL → UL → LAT.
    Returns a result dict on success, raises on failure.
    """
    import json as _json
    from .database import get_setting, set_setting
    from .gluetun import (
        FILTER_VARS, switch_server, wait_for_vpn, get_public_ips,
        restart_network_dependents, restart_containers_in_order,
        list_network_dependents,
    )
    from .speedtest import test_download, test_latency, test_upload, test_stability

    label = f"{FILTER_VARS.get(filter_type, 'SERVER_NAMES')}={server_name}"
    logger.info('Testing: %s', label)
    set_setting('benchmark_current_server', server_name)

    # Capture network dependents BEFORE switching Gluetun so containers whose
    # NetworkMode stores the old container ID (not the name) are not missed.
    pre_switch_deps = list_network_dependents(container)

    ok, err = switch_server(server_name, filter_type, container, compose_dir, project)
    if not ok:
        raise RuntimeError(f'Switch failed: {err}')

    connected, connect_secs = wait_for_vpn(
        proxy_host, proxy_port, timeout=wait_secs,
        proxy_user=proxy_user, proxy_password=proxy_pass,
    )
    if not connected:
        raise RuntimeError(f'VPN connection timeout after {connect_secs:.0f}s')

    # VPN is up — recreate services that lost their network namespace
    # (compose_dir/project let us use `docker compose up` with the already-
    # mounted path rather than the container-inaccessible host-label path)
    restarted, _ = restart_network_dependents(container, compose_dir, project,
                                               explicit_list=pre_switch_deps)
    if restarted:
        logger.info('Recreated network dependents: %s', ', '.join(restarted))
    # NOTE: post_switch_containers are intentionally NOT restarted here.
    # They are only restarted once after the final winning-server switch in
    # _do_benchmark, not after every per-server test during a benchmark cycle.

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
    try:
        ul_median, ul_detail = test_upload(
            proxy_host, proxy_port, duration=dl_duration, streams=dl_streams,
            proxy_user=proxy_user, proxy_password=proxy_pass,
        )
        ul_parts = '  '.join(
            f"{r['endpoint']}:{r['mbps']:.1f}" if r['mbps'] else f"{r['endpoint']}:ERR"
            for r in ul_detail
        )
        logger.info('    UL  [%s]', ul_parts)
    except Exception as exc:
        logger.warning('  Upload test failed for %s: %s', server_name, exc)

    # Stability test (jitter + packet loss via HTTP TTFB sampling)
    stability: dict | None = None
    try:
        stability = test_stability(
            proxy_host, proxy_port,
            proxy_user=proxy_user, proxy_password=proxy_pass,
        )
        if stability:
            logger.info(
                '    STAB jitter=%.1f ms  loss=%.1f%%  min=%.0f ms  max=%.0f ms',
                stability['jitter_ms'], stability['packet_loss_pct'],
                stability.get('ping_min_ms') or 0, stability.get('ping_max_ms') or 0,
            )
    except Exception as exc:
        logger.warning('  Stability test failed for %s: %s', server_name, exc)

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
        jitter_ms=stability['jitter_ms'] if stability else None,
        packet_loss_pct=stability['packet_loss_pct'] if stability else None,
        ping_min_ms=stability.get('ping_min_ms') if stability else None,
        ping_max_ms=stability.get('ping_max_ms') if stability else None,
    )

    return {
        'server':       server_name,
        'filter_type':  filter_type,
        'dl':           dl_median,
        'ul':           ul_median,
        'lat':          lat_median,
        'connect_secs': connect_secs,
        'jitter_ms':       stability['jitter_ms']       if stability else None,
        'packet_loss_pct': stability['packet_loss_pct'] if stability else None,
    }


def _test_one_server_sidecar(
    server_name: str,
    filter_type: str,
    real_container: str,
    sidecar_image: str,
    sidecar_host: str,
    sidecar_port: int,
    wait_secs: int,
    dl_duration: float,
    dl_streams: int,
    sidecar_method: str = 'dual',
    sidecar_iperf_fallback: str = '1',
) -> dict:
    """
    Full sidecar test cycle for one server:
      1. Create test Gluetun container (clone of real, with overridden SERVER_*)
      2. Create speed-test sidecar in test Gluetun's network namespace
      3. Wait for VPN via sidecar /health polling
      4. Run iperf3 + HTTP test via sidecar /test
      5. Cleanup both containers (in finally block)

    The real Gluetun container is never touched during this step.
    """
    from .database import set_setting
    from .gluetun import (
        FILTER_VARS,
        create_test_gluetun, create_speed_sidecar, stream_sidecar_logs,
        wait_for_sidecar, run_sidecar_test, run_sidecar_ping_test,
        cleanup_test_containers,
    )

    label = f"{FILTER_VARS.get(filter_type, 'SERVER_NAMES')}={server_name}"
    logger.info('Sidecar testing: %s', label)
    set_setting('benchmark_current_server', server_name)

    try:
        # Step 1 — launch test Gluetun with the target server
        ok, err = create_test_gluetun(real_container, filter_type, server_name, sidecar_port)
        if not ok:
            raise RuntimeError(f'Test Gluetun creation failed: {err}')

        # Step 2 — attach sidecar to test Gluetun's network namespace
        ok, err = create_speed_sidecar(sidecar_image)
        if not ok:
            raise RuntimeError(f'Speed sidecar creation failed: {err}')

        # Forward sidecar logs to companion logger
        stream_sidecar_logs()

        # Step 3 — wait for VPN connectivity on sidecar
        connected, connect_secs = wait_for_sidecar(sidecar_host, sidecar_port, timeout=wait_secs)
        if not connected:
            raise RuntimeError(f'Sidecar VPN timeout after {connect_secs:.0f}s')

        # Step 4 — run speed test
        data = run_sidecar_test(sidecar_host, sidecar_port,
                                duration=int(dl_duration), streams=dl_streams,
                                method=sidecar_method,
                                iperf_fallback=sidecar_iperf_fallback)

        dl_median  = data.get('download_mbps') or 0.0
        ul_median  = data.get('upload_mbps')
        lat_median = data.get('latency_ms')
        public_ip  = data.get('ip')
        method     = data.get('method', '?')
        iperf_srv  = data.get('iperf_server', '')

        dl_ookla      = data.get('dl_ookla')
        ul_ookla      = data.get('ul_ookla')
        dl_librespeed = data.get('dl_librespeed')
        ul_librespeed = data.get('ul_librespeed')
        dl_iperf3     = data.get('dl_iperf3')
        ul_iperf3     = data.get('ul_iperf3')

        # Stability + DNS: read from sidecar /test response (if sidecar supports it)
        # then fall back to calling /ping separately for jitter/loss
        jitter_ms       = data.get('jitter_ms')
        packet_loss_pct = data.get('packet_loss_pct')
        ping_min_ms     = data.get('ping_min_ms')
        ping_max_ms     = data.get('ping_max_ms')
        dns_latency_ms  = data.get('dns_latency_ms')

        if jitter_ms is None:
            stability = run_sidecar_ping_test(sidecar_host, sidecar_port)
            if stability:
                jitter_ms       = stability['jitter_ms']
                packet_loss_pct = stability['packet_loss_pct']
                ping_min_ms     = stability.get('ping_min_ms')
                ping_max_ms     = stability.get('ping_max_ms')

        sources_log = []
        if dl_ookla:
            sources_log.append(f'ookla:{dl_ookla:.0f}')
        if dl_librespeed:
            sources_log.append(f'libre:{dl_librespeed:.0f}')
        if dl_iperf3:
            sources_log.append(f'iperf3:{dl_iperf3:.0f}')

        logger.info(
            '  %s → DL %.1f Mbps  UL %s  LAT %s ms  connect %.0fs  [%s]',
            server_name, dl_median,
            f'{ul_median:.1f}' if ul_median else '—',
            f'{lat_median:.0f}' if lat_median else '—',
            connect_secs,
            '  '.join(sources_log) or method,
        )
        if jitter_ms is not None:
            logger.info(
                '    STAB jitter=%.1f ms  loss=%.1f%%',
                jitter_ms, packet_loss_pct or 0.0,
            )
        if dns_latency_ms is not None:
            logger.info('    DNS  median=%.0f ms', dns_latency_ms)

        _record_test(
            server_name,
            success=True,
            download_mbps=dl_median,
            upload_mbps=ul_median,
            latency_ms=lat_median,
            public_ip=public_ip,
            method='sidecar',
            dl_ookla=dl_ookla,
            ul_ookla=ul_ookla,
            dl_librespeed=dl_librespeed,
            ul_librespeed=ul_librespeed,
            dl_iperf3=dl_iperf3,
            ul_iperf3=ul_iperf3,
            jitter_ms=jitter_ms,
            packet_loss_pct=packet_loss_pct,
            ping_min_ms=ping_min_ms,
            ping_max_ms=ping_max_ms,
            dns_latency_ms=dns_latency_ms,
        )

        return {
            'server':          server_name,
            'filter_type':     filter_type,
            'dl':              dl_median,
            'ul':              ul_median,
            'lat':             lat_median,
            'connect_secs':    connect_secs,
            'jitter_ms':       jitter_ms,
            'packet_loss_pct': packet_loss_pct,
        }

    finally:
        cleanup_test_containers(sidecar_image)


def _test_direct_proxy(
    proxy_host: str,
    proxy_port: int,
    proxy_user: str | None,
    proxy_pass: str | None,
    dl_duration: float,
    dl_samples: int,
    warmup: float,
    dl_streams: int,
) -> float | None:
    """
    Test download speed via the existing proxy without any server switch.
    Used for quick check in proxy mode (Gluetun never restarted).
    Returns median download Mbps, or None on failure.
    """
    from .speedtest import test_download
    try:
        dl_median, _ = test_download(
            proxy_host, proxy_port,
            duration=dl_duration, samples=dl_samples, warmup=warmup, streams=dl_streams,
            proxy_user=proxy_user, proxy_password=proxy_pass,
        )
        return dl_median
    except Exception as exc:
        logger.warning('Quick check direct proxy test failed: %s', exc)
        return None


def _quick_check(
    container: str,
    proxy_host: str,
    proxy_port: int,
    proxy_user: str | None,
    proxy_pass: str | None,
    dl_duration: float,
    dl_streams: int,
    dl_samples: int,
    warmup: float,
    threshold_pct: float,
    trigger: str | None = None,
) -> tuple[bool, str | None, float | None, float | None]:
    """
    Test the current VPN connection speed via the Gluetun HTTP proxy — always,
    regardless of sidecar_mode.  No container spin-up, no VPN reconnection,
    completes in a few seconds.

    Returns (within_threshold, server_name, current_dl_mbps, last_dl_mbps).
    within_threshold=True → full benchmark can be skipped.
    last_dl_mbps is None when no prior result exists.
    """
    from .database import get_db
    from .gluetun import get_current_filters

    # ── Identify current server ───────────────────────────────────────────
    filters = get_current_filters(container)
    if not filters:
        logger.info('Quick check: cannot read current server from Gluetun — running full benchmark')
        return False, None, None, None

    filter_type = next(iter(filters))
    server_name = filters[filter_type].split(',')[0].strip()

    # ── Last known *proxy* speed ──────────────────────────────────────────
    # We only compare against proxy measurements — sidecar results use a
    # different measurement path and are systematically higher, which would
    # make the delta always look huge and defeat the purpose of the quick check.
    with get_db() as db:
        row = db.execute(
            "SELECT download_mbps FROM speed_tests "
            "WHERE server_name=? AND success=1 AND test_method='proxy_qc' "
            "ORDER BY tested_at DESC LIMIT 1",
            (server_name,),
        ).fetchone()

    last_dl = row['download_mbps'] if row else None

    if last_dl is None:
        logger.info(
            'Quick check: no previous proxy result for %s — '
            'running proxy test to establish baseline then full benchmark',
            server_name,
        )

    logger.info('Quick check: testing %s via proxy%s, threshold: ±%.0f%%',
                server_name,
                f' (last proxy: {last_dl:.1f} Mbps' + ')' if last_dl else ' (no proxy baseline)',
                threshold_pct)

    # ── Test via existing Gluetun HTTP proxy — fast, no container ────────
    current_dl = _test_direct_proxy(
        proxy_host, proxy_port, proxy_user, proxy_pass,
        dl_duration, dl_samples, warmup, dl_streams,
    )

    if current_dl is None:
        logger.warning('Quick check: proxy test failed — running full benchmark')
        return False, server_name, None, last_dl

    # ── Always save the result so future quick checks have a proxy baseline ──
    # Uses a distinct method tag ('proxy_qc') so these appear separately in
    # /history without being mixed with full proxy-mode benchmark results.
    _record_test(server_name, success=True, download_mbps=current_dl, method='proxy_qc',
                 trigger=trigger)

    # ── No baseline yet → establish it, then run full benchmark ──────────
    if last_dl is None:
        logger.info(
            'Quick check: %s — %.1f Mbps recorded as proxy baseline — running full benchmark',
            server_name, current_dl,
        )
        return False, server_name, current_dl, None

    # ── Compare ───────────────────────────────────────────────────────────
    diff_pct = abs(current_dl - last_dl) / last_dl * 100 if last_dl > 0 else 100.0
    within   = diff_pct <= threshold_pct

    logger.info(
        'Quick check: %s — current %.1f Mbps / last proxy %.1f Mbps (Δ%.1f%%) → %s',
        server_name, current_dl, last_dl, diff_pct,
        f'within ±{threshold_pct:.0f}% — skipping full benchmark'
        if within else
        f'outside ±{threshold_pct:.0f}% — running full benchmark',
    )
    return within, server_name, current_dl, last_dl


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
                    wait_secs, dl_duration, dl_samples, lat_samples, warmup, dl_streams,
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


def _test_server_sidecar_with_retry(
    server_name: str,
    filter_type: str,
    real_container: str,
    sidecar_image: str,
    sidecar_host: str,
    sidecar_port: int,
    wait_secs: int,
    dl_duration: float,
    dl_streams: int,
    max_retries: int,
    timeout_secs: int,
    sidecar_method: str = 'dual',
    sidecar_iperf_fallback: str = '1',
) -> dict | None:
    last_err = 'Unknown error'
    for attempt in range(max_retries + 1):
        try:
            with ThreadPoolExecutor(max_workers=1) as ex:
                future = ex.submit(
                    _test_one_server_sidecar,
                    server_name, filter_type,
                    real_container, sidecar_image, sidecar_host, sidecar_port,
                    wait_secs, dl_duration, dl_streams, sidecar_method,
                    sidecar_iperf_fallback,
                )
                return future.result(timeout=timeout_secs)
        except FuturesTimeout:
            last_err = f'Timed out after {timeout_secs}s'
            logger.warning('  %s sidecar timed out (%ds)', server_name, timeout_secs)
            break
        except Exception as exc:
            last_err = str(exc)
            if attempt < max_retries:
                logger.warning(
                    '  Sidecar retry %d/%d for %s: %s', attempt + 1, max_retries, server_name, exc
                )
                time.sleep(5)

    _record_test(server_name, success=False, error=last_err)
    return None


# ---------------------------------------------------------------------------
# Benchmark cycle
# ---------------------------------------------------------------------------

def run_benchmark(app):
    """Scheduled entry point — respects auto_benchmark setting."""
    from .database import get_setting
    if get_setting('auto_benchmark', '1') != '1':
        logger.info('Auto benchmark disabled — skipping scheduled run')
        return
    with _lock:
        _do_benchmark(app)


def run_benchmark_now(app):
    """Manual trigger — always runs, bypasses auto_benchmark + quick check."""
    with _lock:
        _do_benchmark(app, skip_quick_check=True)


def _do_benchmark(app, skip_quick_check: bool = False):
    import json as _json
    from .database import get_db, get_setting, set_setting
    from .gluetun import (
        FILTER_VARS, switch_server, wait_for_vpn,
        get_public_ips, get_current_filters, format_filters,
        restart_network_dependents, restart_containers_in_order,
        stop_containers, start_stopped_containers,
        list_network_dependents,
    )

    set_setting('benchmark_running', '1')
    cycle_start = time.time()

    # These are needed in the finally block (and before quick check), so define early.
    container   = app.config['GLUETUN_CONTAINER']
    compose_dir = app.config['COMPOSE_DIR']
    project     = app.config.get('COMPOSE_PROJECT', '')
    proxy_host  = app.config['GLUETUN_HOST']
    proxy_port  = app.config['GLUETUN_PROXY_PORT']

    # Read all benchmark settings up front (needed for quick check and main loop)
    wait_secs      = int(get_setting('connection_wait_seconds', '45'))
    auto_sw        = get_setting('auto_switch', '1') == '1'
    pull_gluetun   = get_setting('pull_gluetun', '0') == '1'
    proxy_user     = get_setting('proxy_username', '') or None
    proxy_pass     = get_setting('proxy_password', '') or None
    dl_duration    = float(get_setting('speedtest_duration', '8'))
    dl_samples     = int(get_setting('speedtest_samples', '3'))
    lat_samples    = min(dl_samples, 3)
    max_retries    = int(get_setting('speedtest_retries', '2'))
    timeout_secs   = int(get_setting('server_timeout_secs', '300'))
    auto_exclude   = int(get_setting('auto_exclude_failures', '5'))
    warmup         = 2.0 if get_setting('speedtest_warmup', '1') == '1' else 0.0
    dl_streams     = int(get_setting('speedtest_streams', '4'))
    sidecar_mode          = get_setting('sidecar_mode', '1') == '1'
    sidecar_image         = get_setting('sidecar_image', 'ghcr.io/aerya/gluetun-companion-sidecar:latest')
    sidecar_port          = int(get_setting('sidecar_port', '8766'))
    sidecar_method        = get_setting('sidecar_speedtest_method', 'dual')
    sidecar_iperf_fallback = get_setting('sidecar_iperf_fallback', '1')
    sidecar_proxy_fallback = get_setting('sidecar_proxy_fallback', '0') == '1'

    # ── Quick check (before pausing containers) ──────────────────────────────
    # Test only the current server.  If its speed is within ±N% of the last
    # known result, skip the full benchmark entirely — no containers paused,
    # no VPN restarts, no disruption.
    quick_check_mode      = get_setting('quick_check_mode', '0') == '1'
    quick_check_threshold = float(get_setting('quick_check_threshold', '15'))
    qc_info: dict | None = None   # populated if quick check fails and triggers full bench
    if quick_check_mode and not skip_quick_check:
        logger.info('Quick check mode enabled (threshold ±%.0f%%) — testing current server first', quick_check_threshold)
        qc_passed, qc_server, qc_dl, qc_last_dl = _quick_check(
            container=container,
            proxy_host=proxy_host, proxy_port=proxy_port,
            proxy_user=proxy_user, proxy_pass=proxy_pass,
            dl_duration=dl_duration, dl_streams=dl_streams, dl_samples=dl_samples,
            warmup=warmup,
            threshold_pct=quick_check_threshold,
        )
        if qc_passed:
            duration_secs = round(time.time() - cycle_start, 1)
            logger.info('=== Quick check passed (%.0fs) — full benchmark skipped ===', duration_secs)
            set_setting('benchmark_running', '0')
            set_setting('benchmark_current_server', '')
            return
        elif qc_dl is not None and qc_last_dl:
            # Quick check ran but deviation too large → full benchmark triggered
            diff_pct = abs(qc_dl - qc_last_dl) / qc_last_dl * 100
            qc_info = {
                'server':     qc_server,
                'current_dl': qc_dl,
                'last_dl':    qc_last_dl,
                'diff_pct':   diff_pct,
            }

    # Containers to pause before benchmark and restart after
    # (e.g. torrent clients that would distort speed measurements)
    _pause_raw = _json.loads(get_setting('pause_bench_containers', '[]'))
    pause_containers: list[str] = [c.strip() for c in _pause_raw if c and c.strip()]
    pause_exclude = set(pause_containers)  # passed to restart functions
    pull_post_switch_set = set(_json.loads(get_setting('pull_post_switch_containers', '[]')))
    pull_pause_bench_set = set(_json.loads(get_setting('pull_pause_bench_containers', '[]')))
    pull_network_set     = set(_json.loads(get_setting('pull_network_containers', '[]')))

    if pause_containers:
        logger.info(
            'Pausing %d container(s) before benchmark: %s',
            len(pause_containers), ', '.join(pause_containers),
        )
        _stopped = stop_containers(pause_containers)
        logger.info('Paused %d/%d container(s)', len(_stopped), len(pause_containers))

    logger.info('=== Benchmark cycle started ===')

    try:
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
            if sidecar_mode:
                result = _test_server_sidecar_with_retry(
                    row['name'], row['filter_type'],
                    container, sidecar_image, proxy_host, sidecar_port,
                    wait_secs, dl_duration, dl_streams, max_retries, timeout_secs,
                    sidecar_method, sidecar_iperf_fallback,
                )
                if result is None and sidecar_proxy_fallback:
                    logger.info('Sidecar failed for %s — falling back to HTTP proxy', row['name'])
                    result = _test_server_with_retry(
                        row['name'], row['filter_type'],
                        container, compose_dir, project,
                        proxy_host, proxy_port, proxy_user, proxy_pass,
                        wait_secs, dl_duration, dl_samples, lat_samples,
                        warmup, dl_streams, max_retries, timeout_secs,
                    )
            else:
                result = _test_server_with_retry(
                    row['name'], row['filter_type'],
                    container, compose_dir, project,
                    proxy_host, proxy_port, proxy_user, proxy_pass,
                    wait_secs, dl_duration, dl_samples, lat_samples,
                    warmup, dl_streams, max_retries, timeout_secs,
                )
            if result:
                results.append(result)
                _update_consecutive_failures(row['name'], success=True, threshold=auto_exclude)
            else:
                _update_consecutive_failures(row['name'], success=False, threshold=auto_exclude)

        best_server_label: str | None = None
        if auto_sw and results:
            current_pct = float(get_setting('weighted_score_current_pct', '65'))
            # Confidence factors — computed once for all servers (no N+1 queries)
            from .database import compute_confidence_all as _conf_all
            _conf_map = _conf_all()
            _CONF_FACTORS = {'HIGH': 1.0, 'MEDIUM': 0.95, 'LOW': 0.85}
            with get_db() as db:
                best = max(
                    results,
                    key=lambda r: _weighted_score(
                        r['server'], r['dl'], db, current_pct,
                        _CONF_FACTORS.get(
                            _conf_map.get(r['server'], {}).get('level', 'MEDIUM'), 0.95
                        ),
                        jitter_ms=r.get('jitter_ms'),
                        packet_loss_pct=r.get('packet_loss_pct'),
                    ),
                )
            best_label = f"{FILTER_VARS.get(best['filter_type'], 'SERVER_NAMES')}={best['server']}"
            logger.info('Best (weighted): %s (%.1f Mbps current)', best_label, best['dl'])
            best_server_label = best_label

            from_label = format_filters(get_current_filters(container))

            # From-server's speed in this cycle (for delta logging)
            from_name = next(iter(get_current_filters(container).values()), '').split(',')[0].strip()
            from_result = next((r for r in results if r['server'] == from_name), None)
            from_mbps = from_result['dl'] if from_result else None

            if best_label != from_label:
                # Capture network dependents BEFORE Gluetun is recreated so that
                # containers whose NetworkMode stores the old container ID are not missed.
                pre_switch_net_deps = list_network_dependents(container)

                updated_images: list[str] = []
                if pull_gluetun:
                    from .gluetun import pull_image
                    ok_p, upd, img = pull_image(container)
                    logger.info('Gluetun pull: %s — %s', img, 'updated' if upd else 'up to date' if ok_p else 'failed')
                    if upd:
                        updated_images.append(img)
                ok, err = switch_server(
                    best['server'], best['filter_type'], container, compose_dir, project
                )
                if ok:
                    connected, connect_secs = wait_for_vpn(
                        proxy_host, proxy_port, timeout=wait_secs,
                        proxy_user=proxy_user, proxy_password=proxy_pass,
                    )
                    restarted, net_updated = restart_network_dependents(
                        container, compose_dir, project,
                        exclude=pause_exclude, pull_set=pull_network_set,
                        explicit_list=pre_switch_net_deps,
                    )
                    updated_images.extend(net_updated)
                    if restarted:
                        logger.info('Recreated network dependents: %s', ', '.join(restarted))
                    _post_switch = _json.loads(get_setting('post_switch_containers', '[]'))
                    if _post_switch:
                        _restarted2, ps_updated = restart_containers_in_order(
                            _post_switch, compose_dir, project,
                            exclude=pause_exclude, pull_set=pull_post_switch_set,
                        )
                        updated_images.extend(ps_updated)
                        logger.info(
                            'Post-switch containers: %d/%d recreated',
                            len(_restarted2), len(_post_switch),
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
                        lang=get_setting('ui_lang', 'fr'),
                        companion_url=get_setting('companion_url') or None,
                        updated_images=updated_images or None,
                        qc_info=qc_info,
                    )
            else:
                logger.info('Already on best: %s', best_label)
                cur_ipv4, cur_ipv6 = get_public_ips(proxy_host, proxy_port, proxy_user, proxy_pass)
                from .notify import send_already_best_notification
                send_already_best_notification(
                    server=best_label,
                    speed_mbps=best['dl'],
                    ipv4=cur_ipv4,
                    ipv6=cur_ipv6,
                    discord_url=get_setting('discord_webhook_url') or None,
                    apprise_urls=get_setting('apprise_urls') or None,
                    lang=get_setting('ui_lang', 'fr'),
                    companion_url=get_setting('companion_url') or None,
                )

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
        # Always restart paused containers — even if the benchmark failed or
        # was interrupted — so the user's downloads resume automatically.
        if pause_containers:
            logger.info(
                'Restarting %d paused container(s) after benchmark: %s',
                len(pause_containers), ', '.join(pause_containers),
            )
            # Use plain docker start — containers were stopped (not removed),
            # so they don't need compose recreate.  This also works for
            # containers from stacks other than the gluetun stack.
            _resumed = start_stopped_containers(pause_containers, compose_dir, project,
                                                pull_set=pull_pause_bench_set)
            logger.info(
                'Paused containers restarted: %d/%d',
                len(_resumed), len(pause_containers),
            )
        set_setting('benchmark_running', '0')
        set_setting('benchmark_current_server', '')


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
        auto_exclude   = int(get_setting('auto_exclude_failures', '5'))
        warmup         = 2.0 if get_setting('speedtest_warmup', '1') == '1' else 0.0
        dl_streams     = int(get_setting('speedtest_streams', '4'))
        sidecar_mode           = get_setting('sidecar_mode', '1') == '1'
        sidecar_image          = get_setting('sidecar_image', 'ghcr.io/aerya/gluetun-companion-sidecar:latest')
        sidecar_port           = int(get_setting('sidecar_port', '8766'))
        sidecar_method         = get_setting('sidecar_speedtest_method', 'dual')
        sidecar_iperf_fallback = get_setting('sidecar_iperf_fallback', '1')
        sidecar_proxy_fallback = get_setting('sidecar_proxy_fallback', '0') == '1'

        if sidecar_mode:
            result = _test_server_sidecar_with_retry(
                server_name, filter_type,
                container, sidecar_image, proxy_host, sidecar_port,
                wait_secs, dl_duration, dl_streams, max_retries, timeout_secs,
                sidecar_method, sidecar_iperf_fallback,
            )
            if result is None and sidecar_proxy_fallback:
                logger.info('Sidecar failed for %s — falling back to HTTP proxy', server_name)
                result = _test_server_with_retry(
                    server_name, filter_type,
                    container, compose_dir, project,
                    proxy_host, proxy_port, proxy_user, proxy_pass,
                    wait_secs, dl_duration, dl_samples, lat_samples,
                    warmup, dl_streams, max_retries, timeout_secs,
                )
        else:
            result = _test_server_with_retry(
                server_name, filter_type,
                container, compose_dir, project,
                proxy_host, proxy_port, proxy_user, proxy_pass,
                wait_secs, dl_duration, dl_samples, lat_samples,
                warmup, dl_streams, max_retries, timeout_secs,
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
    method: str = 'proxy',
    dl_ookla: float | None = None,
    ul_ookla: float | None = None,
    dl_librespeed: float | None = None,
    ul_librespeed: float | None = None,
    dl_iperf3: float | None = None,
    ul_iperf3: float | None = None,
    jitter_ms: float | None = None,
    packet_loss_pct: float | None = None,
    ping_min_ms: float | None = None,
    ping_max_ms: float | None = None,
    dns_latency_ms: float | None = None,
    trigger: str | None = None,
):
    from .database import get_db
    with get_db() as db:
        db.execute(
            '''INSERT INTO speed_tests
               (server_name, download_mbps, upload_mbps, latency_ms,
                public_ip, public_ipv6, success, error_msg, test_method,
                dl_ookla, ul_ookla, dl_librespeed, ul_librespeed, dl_iperf3, ul_iperf3,
                jitter_ms, packet_loss_pct, ping_min_ms, ping_max_ms, dns_latency_ms,
                test_trigger)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (server_name, download_mbps, upload_mbps, latency_ms,
             public_ip, public_ipv6, int(success), error, method,
             dl_ookla, ul_ookla, dl_librespeed, ul_librespeed, dl_iperf3, ul_iperf3,
             jitter_ms, packet_loss_pct, ping_min_ms, ping_max_ms, dns_latency_ms,
             trigger),
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


def check_airvpn_new_servers(app):
    """
    Compare AirVPN API server list with user's configured servers.
    Store newly discovered servers (in the same countries) in airvpn_new_servers.
    Send Discord/Apprise notification when truly new entries are found.
    No-op when airvpn_new_server_notif == '0'.
    """
    from .database import (
        get_db, get_setting,
        upsert_new_airvpn_servers, purge_old_new_airvpn_servers,
    )

    if get_setting('airvpn_new_server_notif', '0') != '1':
        return

    # Purge stale entries first
    purge_old_new_airvpn_servers()

    # Fetch AirVPN API
    try:
        import requests as _req
        resp = _req.get(
            'https://airvpn.org/api/status/',
            headers={'User-Agent': 'Gluetun-Companion/1.0'},
            timeout=15,
        )
        resp.raise_for_status()
        raw = resp.json()
    except Exception as exc:
        logger.warning('AirVPN new-server check: API fetch failed: %s', exc)
        return

    # Build server → metadata map from API
    api_servers: dict[str, dict] = {}
    for s in raw.get('servers', []):
        name = s.get('public_name', '').strip()
        if name:
            api_servers[name] = s

    # Get our configured servers (name-type only)
    with get_db() as db:
        my_names = {r['name'] for r in db.execute(
            "SELECT name FROM servers WHERE filter_type = 'name'"
        ).fetchall()}

    if not my_names:
        logger.info('AirVPN new-server check: no name-type servers configured — skipping')
        return

    # Determine countries of our configured servers via API
    my_countries: set[str] = set()
    for name in my_names:
        if name in api_servers:
            country = api_servers[name].get('country_name', '').strip()
            if country:
                my_countries.add(country)

    if not my_countries:
        logger.info('AirVPN new-server check: none of our servers matched the AirVPN API — skipping')
        return

    # Find new servers in those countries (not already configured)
    candidates: list[dict] = []
    for name, s in api_servers.items():
        country = s.get('country_name', '').strip()
        if name not in my_names and country in my_countries:
            candidates.append({
                'name':         name,
                'country':      country,
                'country_code': (s.get('country_code') or '').lower(),
            })

    if not candidates:
        logger.info('AirVPN new-server check: no new servers found in known countries (%s)',
                    ', '.join(sorted(my_countries)))
        return

    # Persist — only truly new insertions trigger a notification
    newly_added = upsert_new_airvpn_servers(candidates)

    if not newly_added:
        logger.info('AirVPN new-server check: %d candidate(s) already tracked — no notification',
                    len(candidates))
        return

    logger.info(
        'AirVPN new-server check: %d new server(s) detected — %s',
        len(newly_added),
        ', '.join(s['name'] for s in newly_added),
    )

    from .notify import send_new_airvpn_servers_notification
    send_new_airvpn_servers_notification(
        new_servers=newly_added,
        discord_url=get_setting('discord_webhook_url') or None,
        apprise_urls=get_setting('apprise_urls') or None,
        lang=get_setting('ui_lang', 'fr'),
        mention=get_setting('airvpn_notify_mention', '').strip() or None,
        companion_url=get_setting('companion_url') or None,
    )


# ---------------------------------------------------------------------------
# Docker event listener — automatic quick check on Gluetun restart
# ---------------------------------------------------------------------------

def _run_event_triggered_quick_check(app):
    """
    Called after the Docker event listener detects an unexpected Gluetun restart.

    Flow:
      1. Run a quick proxy speed test on the current server.
      2. Within ±threshold → log OK, no action.
      3. Drift detected + auto-switch enabled → trigger a full benchmark so that
         Companion can switch to a better server if Gluetun reconnected on a
         degraded one.
      4. No baseline yet, QC test failed, or auto-switch disabled → log and return.
    """
    from .database import get_setting, set_setting

    if get_setting('benchmark_running', '0') == '1':
        logger.info('Docker event QC: benchmark already running — skipping')
        return

    with _lock:
        # Double-check inside the lock (another thread may have started a benchmark)
        if get_setting('benchmark_running', '0') == '1':
            logger.info('Docker event QC: benchmark started concurrently — skipping')
            return

        container   = app.config['GLUETUN_CONTAINER']
        proxy_host  = app.config['GLUETUN_HOST']
        proxy_port  = app.config['GLUETUN_PROXY_PORT']
        proxy_user  = get_setting('proxy_username', '') or None
        proxy_pass  = get_setting('proxy_password', '') or None
        dl_duration = float(get_setting('speedtest_duration', '8'))
        dl_samples  = int(get_setting('speedtest_samples', '3'))
        warmup      = 2.0 if get_setting('speedtest_warmup', '1') == '1' else 0.0
        dl_streams  = int(get_setting('speedtest_streams', '4'))
        threshold   = float(get_setting('quick_check_threshold', '15'))
        auto_sw     = get_setting('auto_switch', '1') == '1'

        set_setting('benchmark_running', '1')
        try:
            within, server_name, current_dl, last_dl = _quick_check(
                container=container,
                proxy_host=proxy_host, proxy_port=proxy_port,
                proxy_user=proxy_user, proxy_pass=proxy_pass,
                dl_duration=dl_duration, dl_streams=dl_streams, dl_samples=dl_samples,
                warmup=warmup, threshold_pct=threshold,
                trigger='docker_event',
            )
        finally:
            set_setting('benchmark_running', '0')
            set_setting('benchmark_current_server', '')

        # ── Evaluate result ────────────────────────────────────────────────
        if current_dl is None:
            logger.info(
                'Docker event QC: proxy test failed for %s — VPN may still be reconnecting',
                server_name or '?',
            )
            return

        if last_dl is None:
            # No prior baseline — the QC result was saved; no further action needed.
            logger.info(
                'Docker event QC: %s — %.1f Mbps — no baseline yet, proxy_qc saved',
                server_name or '?', current_dl,
            )
            return

        if within:
            logger.info(
                'Docker event QC: %s — %.1f Mbps — within ±%.0f%% of last %.1f Mbps — OK',
                server_name, current_dl, threshold, last_dl,
            )
            return

        diff_pct = abs(current_dl - last_dl) / last_dl * 100 if last_dl > 0 else 100.0
        if not auto_sw:
            logger.info(
                'Docker event QC: %s — %.1f Mbps (Δ%.1f%%) — drift detected '
                'but auto-switch disabled — no action',
                server_name, current_dl, diff_pct,
            )
            return

        logger.info(
            'Docker event QC: %s — %.1f Mbps (Δ%.1f%%) — drift detected — '
            'triggering full benchmark',
            server_name, current_dl, diff_pct,
        )
        # We already hold _lock → call _do_benchmark directly (no deadlock risk)
        _do_benchmark(app, skip_quick_check=True)


def _docker_event_loop(app, container_name: str) -> None:
    """
    Daemon thread: stream Docker events and react to unexpected Gluetun restarts.

    Filters:
      - container = GLUETUN_CONTAINER
      - event     = 'start'

    Guards:
      - is_companion_restart()  → ignore (Companion itself triggered this restart)
      - _DOCKER_EVENT_COOLDOWN  → ignore if a check fired recently
      - benchmark_running       → ignore if a benchmark is already in progress
    """
    global _last_docker_event_ts
    from .gluetun import is_companion_restart

    while True:
        try:
            import docker as _docker
            client = _docker.from_env()
            logger.info(
                'Docker event listener: watching container "%s" for restart events',
                container_name,
            )
            for event in client.events(
                filters={'container': container_name, 'event': 'start'},
                decode=True,
            ):
                if event.get('Action') != 'start':
                    continue

                # Ignore restarts triggered by Companion itself (server switch)
                if is_companion_restart():
                    logger.info(
                        'Docker event: Gluetun start detected — Companion-triggered, ignoring'
                    )
                    continue

                # Cooldown guard
                now     = time.time()
                elapsed = now - _last_docker_event_ts
                if elapsed < _DOCKER_EVENT_COOLDOWN:
                    logger.info(
                        'Docker event: Gluetun restart detected — cooldown active '
                        '(%.0fs remaining) — skipping',
                        _DOCKER_EVENT_COOLDOWN - elapsed,
                    )
                    continue

                # Benchmark already running?
                from .database import get_setting
                if get_setting('benchmark_running', '0') == '1':
                    logger.info(
                        'Docker event: Gluetun restart detected — benchmark already running — skipping'
                    )
                    continue

                _last_docker_event_ts = now
                logger.info(
                    'Docker event: Gluetun restart detected — scheduling auto quick check'
                )

                def _delayed_qc(a=app):
                    from .database import get_setting as _gs
                    wait = int(_gs('connection_wait_seconds', '45'))
                    logger.info(
                        'Docker event: waiting %ds for VPN reconnect before quick check…', wait
                    )
                    time.sleep(wait)
                    logger.info('Docker event: running automatic quick check now')
                    _run_event_triggered_quick_check(a)

                threading.Thread(
                    target=_delayed_qc, daemon=True, name='docker-event-qc'
                ).start()

        except Exception as exc:
            logger.warning(
                'Docker event listener crashed: %s — restarting in 30s', exc
            )
            time.sleep(30)


def start_docker_event_listener(app, container_name: str) -> None:
    """Start the Docker event watcher as a background daemon thread."""
    t = threading.Thread(
        target=_docker_event_loop,
        args=[app, container_name],
        daemon=True,
        name='docker-events',
    )
    t.start()
    logger.info('Docker event listener started (watching: %s)', container_name)


def start_scheduler(app):
    global _scheduler
    from .database import get_setting

    with app.app_context():
        hours   = float(get_setting('test_interval_hours', '6'))
        enabled = get_setting('auto_benchmark', '1') == '1'

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
    _scheduler.add_job(
        check_airvpn_new_servers,
        trigger=IntervalTrigger(hours=24),
        args=[app],
        id='airvpn_check',
        replace_existing=True,
        misfire_grace_time=3600,
    )
    _scheduler.start()

    # Docker event listener — watches Gluetun container for unexpected restarts
    start_docker_event_listener(app, app.config['GLUETUN_CONTAINER'])

    if not enabled:
        _scheduler.pause_job('benchmark')
        logger.info('Scheduler started — automatic benchmark DISABLED (manual trigger only)')
    else:
        logger.info('Scheduler started — benchmark every %.1f hours', hours)


def reschedule(hours: float, enabled: bool = True):
    if not _scheduler:
        return
    _scheduler.reschedule_job('benchmark', trigger=IntervalTrigger(hours=hours))
    if enabled:
        _scheduler.resume_job('benchmark')
        logger.info('Benchmark rescheduled to every %.1f hours', hours)
    else:
        _scheduler.pause_job('benchmark')
        logger.info('Automatic benchmark disabled — job paused (%.1f h interval kept)', hours)


def trigger_now(app):
    """Manual trigger: always runs full benchmark, ignores auto_benchmark + quick check."""
    t = threading.Thread(target=run_benchmark_now, args=[app], daemon=True, name='benchmark-now')
    t.start()


def run_quick_check_now(app):
    """Manual quick benchmark — proxy test of current server only, no VPN switch."""
    from .database import get_setting, set_setting
    from .gluetun import get_current_filters

    with _lock:
        set_setting('benchmark_running', '1')
        try:
            container  = app.config['GLUETUN_CONTAINER']
            proxy_host = app.config['GLUETUN_HOST']
            proxy_port = app.config['GLUETUN_PROXY_PORT']
            proxy_user = get_setting('proxy_username', '') or None
            proxy_pass = get_setting('proxy_password', '') or None
            dl_duration = float(get_setting('speedtest_duration', '8'))
            dl_samples  = int(get_setting('speedtest_samples', '3'))
            warmup      = 2.0 if get_setting('speedtest_warmup', '1') == '1' else 0.0
            dl_streams  = int(get_setting('speedtest_streams', '4'))

            filters = get_current_filters(container)
            if not filters:
                logger.warning('Quick benchmark now: cannot read current server from Gluetun')
                return

            filter_type = next(iter(filters))
            server_name = filters[filter_type].split(',')[0].strip()
            set_setting('benchmark_current_server', server_name)

            logger.info('Quick benchmark: testing %s via HTTP proxy', server_name)
            dl = _test_direct_proxy(
                proxy_host, proxy_port, proxy_user, proxy_pass,
                dl_duration, dl_samples, warmup, dl_streams,
            )
            if dl is not None:
                _record_test(server_name, success=True, download_mbps=dl, method='proxy_qc')
                logger.info('Quick benchmark: %s → %.1f Mbps (saved as proxy_qc)', server_name, dl)
            else:
                logger.warning('Quick benchmark: proxy test failed for %s', server_name)
        finally:
            set_setting('benchmark_running', '0')
            set_setting('benchmark_current_server', '')


def trigger_quick_now(app):
    """Manual trigger: quick proxy test of current server only, no VPN switch."""
    t = threading.Thread(target=run_quick_check_now, args=[app], daemon=True, name='quickcheck-now')
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
