import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)
_scheduler: BackgroundScheduler | None = None
_lock = threading.Lock()
_current_test_trigger: str | None = None
_observation_watchdog_state: str | None = None

# ── Stop-benchmark signal ──────────────────────────────────────────────────
# Set via request_stop() from the REST API; cleared at the start of every
# benchmark cycle so stale signals don't bleed into the next run.
_stop_event = threading.Event()


def request_stop() -> None:
    """Signal the running benchmark to stop after the current server test."""
    _stop_event.set()
    # Persist the stop request so the UI can reflect it after a page refresh
    from .database import set_setting
    set_setting('benchmark_stop_requested', '1')
    logger.info('Stop requested by user — benchmark will abort after current server')


def _clear_benchmark_running() -> None:
    """Clear benchmark_running and benchmark_stop_requested in one call."""
    from .database import set_setting
    set_setting('benchmark_running', '0')
    set_setting('benchmark_stop_requested', '0')


def _progress_log(message: str) -> None:
    """Keep a tiny user-facing live log for dashboard observation status."""
    import json
    from datetime import datetime
    from .database import get_setting, set_setting

    try:
        lines = json.loads(get_setting('benchmark_log_lines', '[]') or '[]')
        if not isinstance(lines, list):
            lines = []
    except Exception:
        lines = []

    lines.append({
        'ts': datetime.now().strftime('%H:%M:%S'),
        'msg': str(message),
    })
    set_setting('benchmark_log_lines', json.dumps(lines[-5:], ensure_ascii=False))


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
    reconnect_count: int = 0,
    stability_weight: float = 30.0,
) -> float:
    """
    Blend the current cycle's result with exponentially-weighted historical
    data so that a single lucky/unlucky run doesn't dominate.

    ``current_pct`` (1–99) controls how much weight goes to the current
    measurement vs. the exponential history (last 5 results).

    ``confidence_factor`` — light penalty from the confidence score:
      HIGH → 1.0 (no penalty) · MEDIUM → 0.95 · LOW → 0.85.

    Stability components (each 0–1, 1 = perfect):
      - jitter_factor     : up to −15 % at 150 ms jitter
      - loss_factor       : up to −25 % at 10 % packet loss
      - reconnect_factor  : up to −30 % for 3+ involuntary reconnects (−10% each)

    ``stability_weight`` (0–100) scales how much the stability penalties affect
    the final score:
      0   → pure speed (all penalties disabled)
      30  → default — 30 % of the max penalty is applied
      100 → full penalty (a server with 3 reconnects + high jitter can lose ~40 %)

    Formula:
      base             = w_cur × current_dl + (1−w_cur) × exponential_hist
      raw_stability    = jitter_factor × loss_factor × reconnect_factor
      effective_stab   = 1 − (stability_weight/100) × (1 − raw_stability)
      score            = base × confidence_factor × effective_stab
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

    # ── Raw per-factor penalties (None → no data → no penalty) ──────────────
    j_raw = (max(0.85, 1.0 - min(jitter_ms       / 1000.0, 0.15))
             if jitter_ms is not None else 1.0)
    l_raw = (max(0.75, 1.0 - min(packet_loss_pct / 40.0,   0.25))
             if (packet_loss_pct is not None and packet_loss_pct > 0) else 1.0)
    r_raw = (max(0.70, 1.0 - reconnect_count * 0.10)
             if reconnect_count > 0 else 1.0)

    # ── Combined raw stability multiplier ────────────────────────────────────
    raw_stability = j_raw * l_raw * r_raw          # e.g. 0.85 × 0.80 × 0.80 ≈ 0.54

    # ── Scale by stability_weight ─────────────────────────────────────────────
    # stab_w=0 → effective=1.0 (no penalty); stab_w=1 → effective=raw_stability
    stab_w = max(0.0, min(stability_weight, 100.0)) / 100.0
    effective_stab = 1.0 - stab_w * (1.0 - raw_stability)

    return base * confidence_factor * effective_stab


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
    wg_profile: 'dict | None' = None,
) -> dict:
    """
    Full test cycle for one server: switch → wait → probe IPs → DL → UL → LAT.
    *wg_profile* (optional) is forwarded to switch_server() so that WireGuard
    provider credentials are written to the compose override alongside the
    server filter.  Without it, proxy-mode tests silently use whatever
    credentials are already present in Gluetun's environment.
    Returns a result dict on success, raises on failure.
    """
    import json as _json
    from .database import get_setting, set_setting
    from .gluetun import (
        FILTER_VARS, switch_server, wait_for_vpn, get_public_ips,
        restart_network_dependents, restart_containers_in_order,
        list_network_dependents, list_network_dependents_for_recreate,
    )
    from .database import get_setting as _gs
    from .speedtest import test_download, test_latency, test_upload, test_stability

    label = f"{FILTER_VARS.get(filter_type, 'SERVER_NAMES')}={server_name}"
    logger.info('Testing: %s', label)
    set_setting('benchmark_current_server', server_name)

    # Capture network dependents BEFORE switching Gluetun.  Use the extended
    # variant so that containers already orphaned from a previous failed switch
    # (SandboxKey empty, NetworkMode references a dead container ID) are also
    # included — plain list_network_dependents() would miss them.
    pre_switch_deps = list_network_dependents_for_recreate(container)

    ok, err = switch_server(server_name, filter_type, container, compose_dir, project,
                            wg_profile=wg_profile)
    if not ok:
        raise RuntimeError(f'Switch failed: {err}')

    connected, connect_secs = wait_for_vpn(
        proxy_host, proxy_port, timeout=wait_secs,
        proxy_user=proxy_user, proxy_password=proxy_pass,
    )

    # Recreate dependents regardless of VPN status — Gluetun's container IS
    # alive (switch_server() recreated it), so its network namespace is valid.
    # Waiting for VPN success before recreating would leave dependents stuck in
    # a dead namespace on timeout, breaking them for all subsequent switches.
    restarted, _ = restart_network_dependents(container, compose_dir, project,
                                               explicit_list=pre_switch_deps)
    if restarted:
        logger.info(
            'Recreated network dependents%s: %s',
            '' if connected else ' (VPN not yet up)',
            ', '.join(restarted),
        )

    if not connected:
        raise RuntimeError(f'VPN connection timeout after {connect_secs:.0f}s')
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

    # Optional single-stream DL test (DDL profile / single_stream_test setting)
    dl_single: float | None = None
    if _gs('single_stream_test', '0') == '1':
        try:
            dl_single, _ = test_download(
                proxy_host, proxy_port,
                duration=dl_duration, samples=1, warmup=0.0, streams=1,
                proxy_user=proxy_user, proxy_password=proxy_pass,
            )
            logger.info('    DL1 (single-stream) %.1f Mbps', dl_single)
        except Exception as exc:
            logger.warning('  Single-stream DL test failed for %s: %s', server_name, exc)

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
        dl_single_mbps=dl_single,
    )

    return {
        'server':          server_name,
        'filter_type':     filter_type,
        'dl':              dl_median,
        'ul':              ul_median,
        'lat':             lat_median,
        'connect_secs':    connect_secs,
        'jitter_ms':       stability['jitter_ms']       if stability else None,
        'packet_loss_pct': stability['packet_loss_pct'] if stability else None,
        'dl_single':       dl_single,
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
    extra_env: 'dict[str, str] | None' = None,
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
    import secrets as _secrets
    from .database import set_setting, get_setting as _sgs
    from .gluetun import (
        FILTER_VARS,
        create_test_gluetun, create_speed_sidecar, stream_sidecar_logs,
        wait_for_sidecar, run_sidecar_test, run_sidecar_ping_test,
        cleanup_test_containers,
    )

    label = f"{FILTER_VARS.get(filter_type, 'SERVER_NAMES')}={server_name}"
    logger.info('Sidecar testing: %s', label)
    set_setting('benchmark_current_server', server_name)

    # One-time shared secret for this sidecar instance — prevents any other
    # process from interacting with the sidecar API during the test.
    token = _secrets.token_hex(32)

    try:
        # Step 1 — launch test Gluetun with the target server (+ optional WG profile env)
        ok, err = create_test_gluetun(real_container, filter_type, server_name, sidecar_port,
                                      extra_env=extra_env)
        if not ok:
            raise RuntimeError(f'Test Gluetun creation failed: {err}')

        # Step 2 — attach sidecar to test Gluetun's network namespace
        ok, err = create_speed_sidecar(sidecar_image, token=token)
        if not ok:
            raise RuntimeError(f'Speed sidecar creation failed: {err}')

        # Forward sidecar logs to companion logger
        stream_sidecar_logs()

        # Step 3 — wait for VPN connectivity on sidecar
        connected, connect_secs = wait_for_sidecar(
            sidecar_host, sidecar_port, timeout=wait_secs, token=token,
        )
        if not connected:
            raise RuntimeError(f'Sidecar VPN timeout after {connect_secs:.0f}s')

        # Step 4 — run speed test
        data = run_sidecar_test(sidecar_host, sidecar_port,
                                duration=int(dl_duration), streams=dl_streams,
                                method=sidecar_method,
                                iperf_fallback=sidecar_iperf_fallback,
                                token=token)

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
            stability = run_sidecar_ping_test(sidecar_host, sidecar_port, token=token)
            if stability:
                jitter_ms       = stability['jitter_ms']
                packet_loss_pct = stability['packet_loss_pct']
                ping_min_ms     = stability.get('ping_min_ms')
                ping_max_ms     = stability.get('ping_max_ms')

        # Optional single-stream DL test (sidecar still running)
        dl_single: float | None = None
        if _sgs('single_stream_test', '0') == '1':
            try:
                single_data = run_sidecar_test(
                    sidecar_host, sidecar_port,
                    duration=int(dl_duration), streams=1,
                    method=sidecar_method,
                    iperf_fallback=sidecar_iperf_fallback,
                    token=token,
                )
                dl_single = single_data.get('download_mbps') or None
                if dl_single:
                    logger.info('    DL1 (single-stream) %.1f Mbps', dl_single)
            except Exception as exc:
                logger.warning('  Single-stream sidecar DL failed for %s: %s', server_name, exc)

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
            dl_single_mbps=dl_single,
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
            'dl_single':       dl_single,
        }

    finally:
        cleanup_test_containers(sidecar_image)
        try:
            settle = max(0, int(_sgs('sidecar_disconnect_wait_seconds', '180') or '180'))
        except ValueError:
            settle = 180
        if settle:
            logger.info(
                '  %s: waiting %ds after sidecar cleanup so provider sessions can close',
                server_name, settle,
            )
            time.sleep(settle)


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
    Respects _stop_event — exits after the current sample if stop is requested.
    """
    from .speedtest import test_download
    try:
        dl_median, _ = test_download(
            proxy_host, proxy_port,
            duration=dl_duration, samples=dl_samples, warmup=warmup, streams=dl_streams,
            proxy_user=proxy_user, proxy_password=proxy_pass,
            stop_event=_stop_event,
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
    from .gluetun import get_current_filters, get_public_ips

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
    _qc_ipv4, _qc_ipv6 = get_public_ips(proxy_host, proxy_port, proxy_user, proxy_pass)
    _record_test(server_name, success=True, download_mbps=current_dl, method='proxy_qc',
                 trigger=trigger, public_ip=_qc_ipv4, public_ipv6=_qc_ipv6)

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
    wg_profile: 'dict | None' = None,
) -> dict | None:
    """
    Wraps _test_one_server with retry logic and a hard wall-clock timeout.
    Returns result dict on success, None on final failure (error already recorded).
    """
    last_err = 'Unknown error'
    _STOP_POLL = 2.0  # seconds between stop-event checks while waiting for a result
    for attempt in range(max_retries + 1):
        ex = ThreadPoolExecutor(max_workers=1)
        future = ex.submit(
            _test_one_server,
            server_name, filter_type, container, compose_dir, project,
            proxy_host, proxy_port, proxy_user, proxy_pass,
            wait_secs, dl_duration, dl_samples, lat_samples, warmup, dl_streams,
            wg_profile,
        )
        try:
            # Poll in short intervals so a stop request interrupts mid-test
            # instead of waiting for the full timeout_secs wall-clock.
            deadline = time.monotonic() + timeout_secs
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise FuturesTimeout()
                try:
                    result = future.result(timeout=min(_STOP_POLL, remaining))
                    break   # completed successfully
                except FuturesTimeout:
                    if _stop_event.is_set():
                        logger.info(
                            '  %s: stop requested mid-test — abandoning thread',
                            server_name,
                        )
                        ex.shutdown(wait=False, cancel_futures=True)
                        return None
                    # Not timed out globally yet — keep waiting
            ex.shutdown(wait=False)   # don't block — thread is done
            return result
        except FuturesTimeout:
            last_err = f'Timed out after {timeout_secs}s'
            logger.warning('  %s timed out (%ds) — abandoning thread', server_name, timeout_secs)
            # shutdown(wait=False) lets us move on immediately; the daemon thread
            # will eventually be reaped without blocking the benchmark cycle.
            ex.shutdown(wait=False, cancel_futures=True)
            break   # timeout = don't retry
        except Exception as exc:
            last_err = str(exc)
            ex.shutdown(wait=False)
            if attempt < max_retries:
                logger.warning(
                    '  Retry %d/%d for %s: %s', attempt + 1, max_retries, server_name, exc
                )
                # Interruptible retry delay — honour stop requests immediately
                if _stop_event.wait(timeout=5):
                    logger.info('  %s: stop requested during retry delay', server_name)
                    return None

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
    extra_env: 'dict[str, str] | None' = None,
) -> dict | None:
    last_err = 'Unknown error'
    for attempt in range(max_retries + 1):
        if _stop_event.is_set():
            logger.info('  %s: stop requested before sidecar test', server_name)
            return None
        try:
            return _test_one_server_sidecar(
                server_name, filter_type,
                real_container, sidecar_image, sidecar_host, sidecar_port,
                wait_secs, dl_duration, dl_streams, sidecar_method,
                sidecar_iperf_fallback,
                extra_env,
            )
        except Exception as exc:
            last_err = str(exc)
            if attempt < max_retries:
                logger.warning(
                    '  Sidecar retry %d/%d for %s: %s',
                    attempt + 1, max_retries, server_name, exc,
                )
                if _stop_event.wait(timeout=5):
                    logger.info('  %s: stop requested during sidecar retry delay', server_name)
                    return None

    _record_test(server_name, success=False, error=last_err)
    return None



# ---------------------------------------------------------------------------
# Benchmark cycle
# ---------------------------------------------------------------------------

def _compute_adaptive_delay() -> int | None:
    """Return seconds to wait before benchmarking, or None if the current hour is fine.

    Reads hourly stats from the DB.  If the current local hour is already in the
    'good_hours' bucket (or there is not enough data), returns None — run now.
    Otherwise looks ahead up to 3 hours for the next good window and returns the
    number of seconds until the start of that hour.  Returns None if no good window
    is found within 3 hours (we run anyway rather than delay indefinitely).
    """
    from .database import get_hourly_benchmark_stats
    from datetime import datetime, timedelta

    stats = get_hourly_benchmark_stats()
    if not stats['has_enough_data'] or not stats['good_hours']:
        return None

    current_hour = datetime.now().hour
    if current_hour in stats['good_hours']:
        return None  # already in a good window

    now = datetime.now()
    for delta_h in range(1, 4):  # look at the next 1, 2 and 3 hours
        candidate_hour = (current_hour + delta_h) % 24
        if candidate_hour in stats['good_hours']:
            # Seconds until the start of that hour
            candidate_dt = (now.replace(minute=0, second=0, microsecond=0)
                            + timedelta(hours=delta_h))
            delay = int((candidate_dt - now).total_seconds())
            return max(delay, 60)   # at least 1 minute

    return None  # no good window within 3 h → run now


def _restore_interval_trigger() -> None:
    """Restore the benchmark job to its configured IntervalTrigger.

    Called after a benchmark completes when the job may have been switched to a
    one-shot DateTrigger by the adaptive-scheduling logic.
    """
    if not _scheduler:
        return
    job = _scheduler.get_job('benchmark')
    if job is None:
        return
    from apscheduler.triggers.date import DateTrigger
    if isinstance(job.trigger, DateTrigger):
        from .database import get_setting
        hours   = float(get_setting('test_interval_hours', '6'))
        enabled = get_setting('auto_benchmark', '1') == '1'
        reschedule(hours, enabled)
        logger.info('Adaptive scheduling: interval trigger restored (every %.1f h)', hours)


def run_benchmark(app):
    """Scheduled entry point — respects auto_benchmark and adaptive scheduling."""
    from .database import get_setting, get_db
    if get_setting('auto_benchmark', '1') != '1':
        logger.info('Auto benchmark disabled — skipping scheduled run')
        return

    # Defence-in-depth: skip if any auto-rotating pool is active — pool rotation
    # manages the schedule and the benchmark job should have been paused already.
    try:
        with get_db() as _db:
            _pools = _db.execute(
                'SELECT COUNT(*) AS n FROM rotation_pools WHERE enabled=1 AND auto_rotate=1'
            ).fetchone()['n']
        if _pools:
            logger.info(
                'Auto benchmark skipped — %d active rotation pool(s) manage the schedule',
                _pools,
            )
            return
    except Exception:
        pass

    # ── Adaptive scheduling: shift to next favorable hour if needed ──────────
    # Only shift when the interval job still exists in the scheduler.
    # DateTrigger (one-shot) jobs are removed by APScheduler *before* execution,
    # so get_job() returning None means we are already in a shifted run — just
    # proceed with the benchmark instead of trying to reschedule a removed job.
    if (get_setting('adaptive_scheduling', '0') == '1'
            and get_setting('adaptive_auto_shift', '0') == '1'
            and _scheduler is not None
            and _scheduler.get_job('benchmark') is not None):
        delay_secs = _compute_adaptive_delay()
        if delay_secs:
            from apscheduler.triggers.date import DateTrigger
            from datetime import datetime, timedelta
            next_fire = datetime.now() + timedelta(seconds=delay_secs)
            _scheduler.reschedule_job('benchmark', trigger=DateTrigger(run_date=next_fire))
            logger.info(
                'Adaptive scheduling: current hour is suboptimal — '
                'benchmark shifted by %.0f min to %s',
                delay_secs / 60, next_fire.strftime('%H:%M'),
            )
            return

    if (
        get_setting('benchmark_running', '0') == '1'
        and get_setting('benchmark_mode', '') == 'observation'
    ):
        logger.info('Scheduled benchmark due — pausing continuous observation first')
        _progress_log('Observation continue mise en pause : cycle planifie prioritaire')
        _stop_event.set()

    with _lock:
        # The scheduled job is the classic decision cycle: it may pause
        # configured containers and auto-switch to the best server. Continuous
        # observation is only background collection and resumes later via its
        # watchdog if work remains.
        _do_benchmark(app, observation=False)

    # Restore IntervalTrigger in case we were running from a one-shot DateTrigger
    _restore_interval_trigger()


def run_observation_now(app):
    """Run the continuous observation loop immediately, outside the interval schedule."""
    from .database import get_setting
    if get_setting('continuous_observation', '0') != '1':
        logger.info('Continuous observation not started — option disabled')
        return
    if get_setting('benchmark_running', '0') == '1':
        logger.info('Continuous observation not started — benchmark already running')
        return
    if not _lock.acquire(blocking=False):
        logger.info('Continuous observation not started — scheduler lock busy')
        return
    try:
        cycle_no = 0
        while get_setting('continuous_observation', '0') == '1':
            cycle_no += 1
            logger.info('Continuous observation immediate loop: cycle #%d', cycle_no)
            tested = _do_benchmark(app, observation=True) or 0
            if _stop_event.is_set():
                logger.info('Continuous observation immediate loop stopped by user request')
                break
            if tested <= 0:
                logger.info('Continuous observation immediate loop stopped: no successful test in last cycle')
                break
            if not _has_observation_work_left():
                logger.info('Continuous observation immediate loop complete: no server left below target')
                break
            time.sleep(30)
    finally:
        _lock.release()


def run_benchmark_now(app):
    """Manual trigger — always runs, bypasses auto_benchmark + quick check."""
    with _lock:
        _do_benchmark(app, skip_quick_check=True)


def _observation_candidate_servers() -> list:
    """Return servers eligible for observation before pyramid quotas are applied."""
    from .database import get_db
    with get_db() as db:
        servers = db.execute(
            'SELECT s.name, s.filter_type, s.vpn_profile_id, '
            '       vp.provider AS vp_provider, vp.name AS vp_name, '
            '       vp.enabled AS vp_enabled, vp.rotation_allowed AS vp_rotation_allowed '
            'FROM servers s '
            'LEFT JOIN vpn_profiles vp ON vp.id = s.vpn_profile_id '
            'WHERE s.enabled = 1 '
            '  AND (s.vpn_profile_id IS NULL OR vp.enabled = 1) '
            'ORDER BY s.name'
        ).fetchall()

    any_profiles = any(s['vpn_profile_id'] is not None for s in servers)
    if any_profiles:
        servers = [s for s in servers if s['vpn_profile_id'] is not None]
    return servers


def _has_observation_work_left() -> bool:
    return bool(_apply_benchmark_scope(_observation_candidate_servers(), observation=True))


def _apply_benchmark_scope(servers: list, observation: bool = False) -> list:
    """Limit a full benchmark to an explainable, configurable working set."""
    from datetime import datetime, timedelta
    from .database import get_db, get_setting, get_stability_all
    from .profiles import score_servers

    mode = get_setting('benchmark_scope_mode', 'smart')
    if (mode != 'smart' and not observation) or not servers:
        return servers

    def _as_int(key: str, default: int, lo: int, hi: int) -> int:
        try:
            return max(lo, min(int(get_setting(key, str(default)) or default), hi))
        except ValueError:
            return default

    def _rotating_slice(rows: list[dict], quota: int) -> list[dict]:
        if quota <= 0 or not rows:
            return []
        rows = sorted(rows, key=lambda r: r['name'])
        if len(rows) <= quota:
            return rows
        offset = datetime.utcnow().toordinal() % len(rows)
        rotated = rows[offset:] + rows[:offset]
        return rotated[:quota]

    def _score_pick(rows: list[dict], quota: int) -> list[str]:
        if quota <= 0 or not rows:
            return []
        scores = score_servers(rows, active_profile, get_stability_all())
        return [
            name for name, _score in sorted(
                scores.items(), key=lambda item: item[1], reverse=True
            )[:quota]
        ]

    top_n = _as_int('benchmark_scope_top_n', 50, 0, 500)
    untested_n = _as_int('benchmark_scope_untested_n', 10, 0, 200)
    refresh_days = _as_int('benchmark_scope_refresh_days', 14, 1, 365)
    refresh_n = _as_int('benchmark_scope_refresh_n', 20, 0, 500)
    active_profile = get_setting('active_profile', 'balanced')

    if not observation and top_n <= 0 and untested_n <= 0 and refresh_n <= 0:
        logger.info('Benchmark scope=smart but all quotas are 0 — keeping full list')
        return servers

    candidate_names = {s['name'] for s in servers}
    with get_db() as db:
        stats_rows = db.execute(
            '''SELECT s.name,
                      AVG(CASE WHEN st.success=1 AND (st.test_method IS NULL OR st.test_method!='proxy_qc') THEN st.download_mbps END) AS avg_dl,
                      AVG(CASE WHEN st.success=1 AND (st.test_method IS NULL OR st.test_method!='proxy_qc') THEN st.upload_mbps END) AS avg_ul,
                      AVG(CASE WHEN st.success=1 AND (st.test_method IS NULL OR st.test_method!='proxy_qc') THEN st.latency_ms END) AS avg_lat,
                      AVG(CASE WHEN st.success=1 AND (st.test_method IS NULL OR st.test_method!='proxy_qc') THEN st.dl_single_mbps END) AS avg_dl_single,
                      COUNT(CASE WHEN st.success=1 AND (st.test_method IS NULL OR st.test_method!='proxy_qc') THEN 1 END) AS full_tests,
                      MAX(CASE WHEN st.success=1 AND (st.test_method IS NULL OR st.test_method!='proxy_qc') THEN st.tested_at END) AS last_full_test
               FROM servers s
               LEFT JOIN speed_tests st ON st.server_name = s.name
               GROUP BY s.id'''
        ).fetchall()

    stats = {r['name']: dict(r) for r in stats_rows if r['name'] in candidate_names}
    known_rows = [r for r in stats.values() if (r.get('full_tests') or 0) > 0]
    untested_rows = [r for r in stats.values() if not (r.get('full_tests') or 0)]

    if observation:
        target_tests = _as_int('observation_target_tests', 11, 2, 50)
        confirm_tests = _as_int('observation_confirm_tests', 3, 2, 20)
        confirm_tests = min(confirm_tests, target_tests)
        explore_n = _as_int('observation_explore_n', 20, 0, 500)
        confirm_n = _as_int('observation_confirm_n', 20, 0, 500)
        finalist_n = _as_int('observation_finalist_n', 10, 0, 500)

        selected: set[str] = set()
        selected.update(r['name'] for r in _rotating_slice(untested_rows, explore_n))

        confirm_rows = [
            r for r in known_rows
            if 0 < (r.get('full_tests') or 0) < confirm_tests
        ]
        selected.update(_score_pick(confirm_rows, confirm_n))

        finalist_rows = [
            r for r in known_rows
            if confirm_tests <= (r.get('full_tests') or 0) < target_tests
        ]
        selected.update(_score_pick(finalist_rows, finalist_n))

        if refresh_n > 0:
            cutoff = datetime.utcnow() - timedelta(days=refresh_days)
            mature_rows = [
                r for r in known_rows
                if (r.get('full_tests') or 0) >= target_tests and r.get('last_full_test')
            ]
            stale = []
            for r in mature_rows:
                try:
                    last_dt = datetime.strptime(str(r['last_full_test'])[:19], '%Y-%m-%d %H:%M:%S')
                except ValueError:
                    continue
                if last_dt < cutoff:
                    stale.append((last_dt, r))
            selected.update(r['name'] for _last_dt, r in sorted(stale)[:refresh_n])

        if not selected:
            logger.info('Continuous observation selected no server - target reached or no eligible server')
            return []
        else:
            scoped = [s for s in servers if s['name'] in selected]
            logger.info(
                'Continuous observation scope: selected %d/%d server(s) '
                '(explore=%d, confirm<%d=%d, finalists<%d=%d, refresh>%dd=%d, profile=%s)',
                len(scoped), len(servers), explore_n, confirm_tests, confirm_n,
                target_tests, finalist_n, refresh_days, refresh_n, active_profile,
            )
            return scoped

    selected: set[str] = set()
    if top_n > 0 and known_rows:
        selected.update(_score_pick(known_rows, top_n))

    if untested_n > 0 and untested_rows:
        selected.update(r['name'] for r in sorted(untested_rows, key=lambda r: r['name'])[:untested_n])

    if refresh_n > 0 and known_rows:
        cutoff = datetime.utcnow() - timedelta(days=refresh_days)
        stale = []
        for r in known_rows:
            last_raw = r.get('last_full_test')
            if not last_raw:
                continue
            try:
                last_dt = datetime.strptime(str(last_raw)[:19], '%Y-%m-%d %H:%M:%S')
            except ValueError:
                continue
            if last_dt < cutoff:
                stale.append((last_dt, r['name']))
        selected.update(name for _last_dt, name in sorted(stale)[:refresh_n])

    if not selected:
        logger.info('Benchmark scope=smart selected no server — keeping full list')
        return servers

    before = len(servers)
    scoped = [s for s in servers if s['name'] in selected]
    logger.info(
        'Benchmark scope=smart: selected %d/%d server(s) '
        '(top=%d, untested=%d, stale>%dd=%d, profile=%s)',
        len(scoped), before, top_n, untested_n, refresh_days, refresh_n, active_profile,
    )
    return scoped


def _do_benchmark(app, skip_quick_check: bool = False, observation: bool = False):
    global _current_test_trigger
    import json as _json
    from .database import get_db, get_setting, set_setting
    from .gluetun import (
        FILTER_VARS, switch_server, wait_for_vpn,
        get_public_ips, get_current_filters, format_filters,
        restart_network_dependents, restart_containers_in_order,
        stop_containers, start_stopped_containers,
        list_network_dependents, list_network_dependents_for_recreate,
    )

    _stop_event.clear()   # reset any leftover stop signal from a previous run
    set_setting('benchmark_stop_requested', '0')
    _current_test_trigger = 'observation' if observation else None
    set_setting('benchmark_running', '1')
    cycle_start = time.time()
    set_setting('benchmark_started_at', str(cycle_start))
    set_setting('benchmark_mode', 'observation' if observation else 'benchmark')
    set_setting('benchmark_total_servers', '0')
    set_setting('benchmark_done_servers', '0')
    set_setting('benchmark_next_server', '')
    set_setting('benchmark_log_lines', '[]')
    _progress_log('Observation continue demarree' if observation else 'Benchmark demarre')

    # ── Catalogue refresh via sidecar (always) ───────────────────────────────
    # The sidecar downloads server lists from the public Gluetun GitHub repo.
    # No volume mounting required.
    try:
        from .catalogue import refresh_catalogue_from_sidecar
        _sidecar_img       = get_setting('sidecar_image', 'ghcr.io/aerya/gluetun-companion-sidecar:latest')
        _sidecar_host      = app.config['GLUETUN_HOST']
        _cat_auto_add      = get_setting('catalogue_auto_add', '0') == '1'
        _notif_cat_changes = get_setting('notif_catalogue_changes', '0') == '1'
        _cat = refresh_catalogue_from_sidecar(
            sidecar_image=_sidecar_img,
            sidecar_host=_sidecar_host,
            auto_add=_cat_auto_add,
        )
        if _cat.get('ok'):
            logger.info('catalogue: refreshed via sidecar — %d servers', _cat.get('total', 0))
            _cat_diff       = _cat.get('diff', {})
            _cat_auto_added = _cat.get('auto_added', [])
            if _notif_cat_changes and (_cat_diff or _cat_auto_added):
                _c_discord_url  = get_setting('discord_webhook_url') or None
                _c_apprise_urls = get_setting('apprise_urls') or None
                _c_lang         = get_setting('ui_lang', 'fr')
                _c_companion    = get_setting('companion_url') or None
                _c_mention      = get_setting('notify_mention', '').strip() or None
                _c_mention_lvl  = get_setting('notify_mention_level', 'critical')
                from .notify import send_catalogue_changes_notification
                send_catalogue_changes_notification(
                    diff=_cat_diff,
                    auto_added=_cat_auto_added,
                    discord_url=_c_discord_url,
                    apprise_urls=_c_apprise_urls,
                    lang=_c_lang,
                    companion_url=_c_companion,
                    mention=_c_mention,
                    mention_level=_c_mention_lvl,
                )
        else:
            logger.warning('catalogue: refresh failed — %s', _cat.get('error', '?'))
    except Exception as _cat_exc:
        logger.warning('catalogue: refresh error — %s', _cat_exc)

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
    tracker_checks_enabled = get_setting('tracker_check_enabled', '0') == '1'
    tracker_required_for_switch = get_setting('tracker_require_for_switch', '0') == '1'

    # ── Notification settings ────────────────────────────────────────────────
    _discord_url      = get_setting('discord_webhook_url') or None
    _apprise_urls     = get_setting('apprise_urls') or None
    _notif_lang       = get_setting('ui_lang', 'fr')
    _companion_url    = get_setting('companion_url') or None
    _mention          = get_setting('notify_mention', '').strip() or None
    _mention_level    = get_setting('notify_mention_level', 'critical')
    _notif_auto_sw    = get_setting('notif_auto_switch',       '1') == '1'
    _notif_best       = get_setting('notif_already_best',      '0') == '1'
    _notif_exclude    = get_setting('notif_auto_exclude',      '1') == '1'
    _notif_bench_end  = get_setting('notif_benchmark_end',     '0') == '1'
    _notif_bench_fail = get_setting('notif_benchmark_failure', '1') == '1'

    # ── Quick check (before pausing containers) ──────────────────────────────
    # Test only the current server.  If its speed is within ±N% of the last
    # known result, skip the full benchmark entirely — no containers paused,
    # no VPN restarts, no disruption.
    quick_check_mode      = get_setting('quick_check_mode', '0') == '1'
    quick_check_threshold = float(get_setting('quick_check_threshold', '15'))
    qc_info: dict | None = None   # populated if quick check fails and triggers full bench
    if quick_check_mode and not skip_quick_check and not observation:
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
            _clear_benchmark_running()
            set_setting('benchmark_current_server', '')
            set_setting('benchmark_next_server', '')
            set_setting('benchmark_started_at', '')
            set_setting('benchmark_mode', '')
            set_setting('benchmark_total_servers', '0')
            set_setting('benchmark_done_servers', '0')
            _progress_log('Quick check OK - benchmark complet ignore')
            return 0
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
    pause_containers: list[str] = [] if observation else [c.strip() for c in _pause_raw if c and c.strip()]
    pause_exclude = set(pause_containers)  # passed to restart functions
    pull_post_switch_set = set(_json.loads(get_setting('pull_post_switch_containers', '[]')))
    pull_pause_bench_set = set(_json.loads(get_setting('pull_pause_bench_containers', '[]')))
    pull_network_set     = set(_json.loads(get_setting('pull_network_containers', '[]')))

    if tracker_checks_enabled and not observation:
        try:
            from .torrent_trackers import discover_trackers
            _progress_log('Decouverte trackers BitTorrent')
            _td = discover_trackers()
            logger.info(
                'Tracker discovery before benchmark: %d found, %d new, %d error(s)',
                _td.get('trackers_found', 0), _td.get('trackers_new', 0), len(_td.get('errors', [])),
            )
        except Exception as exc:
            logger.warning('Tracker discovery before benchmark failed: %s', exc)

    if pause_containers:
        logger.info(
            'Pausing %d container(s) before benchmark: %s',
            len(pause_containers), ', '.join(pause_containers),
        )
        _stopped = stop_containers(pause_containers)
        logger.info('Paused %d/%d container(s)', len(_stopped), len(pause_containers))

    if observation:
        auto_sw = False
        logger.info(
            '=== Continuous observation cycle started (no quick check, no paused containers, no auto-switch) ==='
        )
    else:
        logger.info('=== Benchmark cycle started ===')

    try:
        with get_db() as db:
            servers = db.execute(
                'SELECT s.name, s.filter_type, s.vpn_profile_id, '
                '       vp.provider AS vp_provider, vp.name AS vp_name, '
                '       vp.enabled AS vp_enabled, vp.rotation_allowed AS vp_rotation_allowed '
                'FROM servers s '
                'LEFT JOIN vpn_profiles vp ON vp.id = s.vpn_profile_id '
                # Only include servers whose assigned profile is enabled (or no profile assigned)
                'WHERE s.enabled = 1 '
                '  AND (s.vpn_profile_id IS NULL OR vp.enabled = 1) '
                'ORDER BY s.name'
            ).fetchall()
            cycle_id = db.execute(
                'INSERT INTO benchmark_cycles (started_at) VALUES (CURRENT_TIMESTAMP)'
            ).lastrowid

        if not servers:
            logger.info('No enabled servers — skipping benchmark')
            _progress_log('Aucun serveur actif a tester')
            return 0

        # ── Pre-filter 0: exclude orphan servers when WireGuard profiles exist ─
        # If ANY vpn_profiles exist the user has set up WireGuard multi-provider.
        # Servers without vpn_profile_id cannot be benchmarked correctly in that
        # context (they would run with whatever credentials are already in Gluetun).
        _any_profiles = any(s['vpn_profile_id'] is not None for s in servers)
        if _any_profiles:
            _before_orphan = len(servers)
            servers = [s for s in servers if s['vpn_profile_id'] is not None]
            _excluded = _before_orphan - len(servers)
            if _excluded:
                logger.info(
                    'Orphan pre-filter: excluded %d server(s) with no VPN profile assigned',
                    _excluded,
                )

        # ── Pre-filter 1: include only selected filter types ─────────────────
        # Setting: bench_include_types — JSON list of types, e.g. ["name","country"]
        # Empty list (default) = include all types (no filtering).
        try:
            _include_types = set(_json.loads(get_setting('bench_include_types', '[]')))
        except Exception:
            _include_types = set()
        if _include_types:
            _before = len(servers)
            servers = [s for s in servers if s['filter_type'] in _include_types]
            logger.info(
                'Bench type filter: keeping types %s → %d/%d server(s)',
                sorted(_include_types), len(servers), _before,
            )

        # ── Pre-filter 2: AirVPN load/users threshold (name-type only) ───────
        # Settings: airvpn_bench_max_load (0=disabled), airvpn_bench_max_users (0=disabled)
        # Uses airvpn_snapshot table (updated every 5 min from AirVPN API).
        # Servers without snapshot data are always kept.
        _max_load  = int(get_setting('airvpn_bench_max_load',  '0') or '0')
        _max_users = int(get_setting('airvpn_bench_max_users', '0') or '0')
        if _max_load > 0 or _max_users > 0:
            _name_servers = [s for s in servers if s['filter_type'] == 'name']
            if _name_servers:
                with get_db() as db:
                    _snap_rows = db.execute(
                        'SELECT name, load, users FROM airvpn_snapshot'
                    ).fetchall()
                _snap_map = {r['name']: r for r in _snap_rows}
                _kept, _skipped = [], []
                for s in servers:
                    if s['filter_type'] != 'name':
                        _kept.append(s)
                        continue
                    _snap = _snap_map.get(s['name'])
                    if _snap is None:
                        # No AirVPN data → always keep (may be a non-AirVPN name server)
                        _kept.append(s)
                        continue
                    if _max_load > 0 and _snap['load'] is not None and _snap['load'] > _max_load:
                        _skipped.append(f"{s['name']}(load={_snap['load']}%)")
                        continue
                    if _max_users > 0 and _snap['users'] is not None and _snap['users'] > _max_users:
                        _skipped.append(f"{s['name']}(users={_snap['users']})")
                        continue
                    _kept.append(s)
                if _skipped:
                    logger.info(
                        'AirVPN pre-filter: skipped %d server(s) exceeding thresholds '
                        '(max_load=%d%%, max_users=%d): %s',
                        len(_skipped), _max_load, _max_users, ', '.join(_skipped),
                    )
                servers = _kept

        servers = _apply_benchmark_scope(servers, observation=observation)

        if not servers:
            logger.info('No servers left after pre-filters — skipping benchmark')
            _progress_log('Aucun serveur restant dans le perimetre')
            return 0
        set_setting('benchmark_total_servers', str(len(servers)))
        set_setting('benchmark_done_servers', '0')
        _progress_log(f'{len(servers)} serveur(s) selectionne(s)')

        # ── Load WireGuard profile vars for each distinct vpn_profile_id ─────
        # Decrypts secrets once per profile and builds a lookup table so each
        # server test can pass the correct env vars to create_test_gluetun().
        from .wg_providers import WG_PROVIDERS as _WGP
        from .crypto import decrypt as _crypto_decrypt, is_encrypted as _is_enc
        from .database import get_vpn_profile as _get_profile, get_setting as _get_set


        _distinct_profile_ids = {
            row['vpn_profile_id']
            for row in servers
            if row['vpn_profile_id'] is not None
        }
        # {profile_id: {'compose_provider': str, 'extra_env': {var: decrypted_val}}}
        _profile_env_cache: dict[int, dict] = {}
        for _pid in _distinct_profile_ids:
            _p = _get_profile(_pid)
            if not _p:
                continue
            _prov_key = _p['provider']
            _prov_def = _WGP.get(_prov_key, {})
            _compose_prov = _prov_def.get('compose_provider', _prov_key)
            _extra: dict[str, str] = {
                'VPN_SERVICE_PROVIDER': _compose_prov,
                'VPN_TYPE': 'wireguard',
            }
            for _vk, _vv in _p['vars'].items():
                try:
                    _extra[_vk] = _crypto_decrypt(_vv) if _is_enc(_vv) else _vv
                except ValueError as _exc:
                    logger.error('Cannot decrypt %s for profile %d: %s', _vk, _pid, _exc)
                    _extra[_vk] = ''
            # Per-profile sidecar WireGuard identity.
            # Dedicated sidecar values are preferred. Profiles may explicitly
            # allow reusing the main WireGuard identity when the provider allows it.
            _sidecar_ovr: dict[str, str] = {}
            _sidecar_reuse = bool(_p.get('sidecar_reuse_profile', False))
            _sc_pk_raw  = _p.get('sidecar_private_key',  '')
            _sc_addr    = _p.get('sidecar_addresses',    '')
            _sc_psk_raw = _p.get('sidecar_preshared_key', '')
            if _sc_pk_raw:
                try:
                    _sidecar_ovr['WIREGUARD_PRIVATE_KEY'] = (
                        _crypto_decrypt(_sc_pk_raw) if _is_enc(_sc_pk_raw) else _sc_pk_raw
                    )
                except ValueError as _exc:
                    logger.error('Cannot decrypt sidecar_private_key for profile %d: %s', _pid, _exc)
            if _sc_addr:
                _sidecar_ovr['WIREGUARD_ADDRESSES'] = _sc_addr
            if _sc_psk_raw:
                try:
                    _sidecar_ovr['WIREGUARD_PRESHARED_KEY'] = (   # correct var name
                        _crypto_decrypt(_sc_psk_raw) if _is_enc(_sc_psk_raw) else _sc_psk_raw
                    )
                except ValueError as _exc:
                    logger.error('Cannot decrypt sidecar_preshared_key for profile %d: %s', _pid, _exc)
            if not _sidecar_ovr and not _sidecar_reuse and sidecar_mode:
                logger.warning(
                    'Profile #%d (%s/%s): no dedicated sidecar WireGuard key configured '
                    'and main-profile reuse is disabled — '
                    'servers in this profile will be skipped in sidecar mode '
                    '(configure a sidecar key or enable reuse in Settings → WireGuard profiles).',
                    _pid, _compose_prov, _p.get('name', '?'),
                )

            _profile_env_cache[_pid] = {
                'compose_provider': _compose_prov,
                'extra_env':        _extra,
                'sidecar_override': _sidecar_ovr,
                'sidecar_reuse_profile': _sidecar_reuse,
            }
        if _distinct_profile_ids:
            logger.info(
                'Loaded WireGuard env for %d profile(s): %s',
                len(_profile_env_cache),
                ', '.join(
                    f"#{pid}({_profile_env_cache[pid]['compose_provider']})"
                    for pid in sorted(_profile_env_cache)
                ),
            )

        results: list[dict] = []

        for idx, row in enumerate(servers, start=1):
            if _stop_event.is_set():
                logger.info(
                    'Benchmark aborted by user — %d/%d server(s) tested',
                    len(results), len(servers),
                )
                break
            set_setting('benchmark_current_server', row['name'])
            set_setting('benchmark_done_servers', str(idx - 1))
            next_server = servers[idx]['name'] if idx < len(servers) else ''
            set_setting('benchmark_next_server', next_server)
            _progress_log(f'Test {idx}/{len(servers)} : {row["name"]}')

            # Resolve WireGuard extra_env for this server's profile (None if no profile)
            _pid = row['vpn_profile_id']
            _penv = _profile_env_cache.get(_pid) if _pid is not None else None
            _extra_env = _penv['extra_env'] if _penv else None

            # Sidecar uses either a dedicated per-profile identity or, when the
            # profile explicitly allows it, the same WireGuard identity as Gluetun.
            _effective_sidecar = _penv.get('sidecar_override', {}) if _penv else {}
            _sidecar_reuse = bool(_penv.get('sidecar_reuse_profile')) if _penv else False

            if sidecar_mode:
                if not _effective_sidecar and not _sidecar_reuse:
                    _skip_reason = (
                        f'no sidecar key or reuse option for profile #{_pid}'
                        if _pid else 'server has no VPN profile'
                    )
                    if sidecar_proxy_fallback:
                        logger.info(
                            'Server %s: skipping sidecar (%s) — proxy fallback',
                            row['name'], _skip_reason,
                        )
                        result = _test_server_with_retry(
                            row['name'], row['filter_type'],
                            container, compose_dir, project,
                            proxy_host, proxy_port, proxy_user, proxy_pass,
                            wait_secs, dl_duration, dl_samples, lat_samples,
                            warmup, dl_streams, max_retries, timeout_secs,
                            wg_profile=_penv,
                        )
                    else:
                        logger.info(
                            'Server %s: skipping (%s, no proxy fallback configured)',
                            row['name'], _skip_reason,
                        )
                        set_setting('benchmark_done_servers', str(idx))
                        _progress_log(f'Ignore {row["name"]} : {_skip_reason}')
                        continue   # not a failure — just untestable in this mode
                else:
                    _sidecar_env: dict[str, str] = dict(_extra_env) if _extra_env else {}
                    _sidecar_env.update(_effective_sidecar)
                    result = _test_server_sidecar_with_retry(
                        row['name'], row['filter_type'],
                        container, sidecar_image, proxy_host, sidecar_port,
                        wait_secs, dl_duration, dl_streams, max_retries, timeout_secs,
                        sidecar_method, sidecar_iperf_fallback,
                        extra_env=_sidecar_env,
                    )
                    if result is None and sidecar_proxy_fallback:
                        logger.info('Sidecar failed for %s — falling back to HTTP proxy', row['name'])
                        result = _test_server_with_retry(
                            row['name'], row['filter_type'],
                            container, compose_dir, project,
                            proxy_host, proxy_port, proxy_user, proxy_pass,
                            wait_secs, dl_duration, dl_samples, lat_samples,
                            warmup, dl_streams, max_retries, timeout_secs,
                            wg_profile=_penv,
                        )
            else:
                result = _test_server_with_retry(
                    row['name'], row['filter_type'],
                    container, compose_dir, project,
                    proxy_host, proxy_port, proxy_user, proxy_pass,
                    wait_secs, dl_duration, dl_samples, lat_samples,
                    warmup, dl_streams, max_retries, timeout_secs,
                    wg_profile=_penv,   # pass profile so switch_server writes WG creds
                )
            if result:
                results.append(result)
                _progress_log(f'OK {row["name"]} - {float(result.get("dl", 0) or 0):.1f} Mbps')
                if tracker_checks_enabled and not observation:
                    try:
                        from .torrent_trackers import check_enabled_trackers
                        _tc = check_enabled_trackers(server_name=row['name'])
                        result['tracker_check'] = _tc
                        result['tracker_ok'] = True if int(_tc.get('total') or 0) == 0 else bool(_tc.get('ok'))
                        logger.info(
                            'Tracker check for %s: %.1f%% (%d/%d, threshold %d%%)',
                            row['name'], _tc.get('success_pct', 0),
                            _tc.get('passed', 0), _tc.get('total', 0), _tc.get('threshold', 80),
                        )
                        _progress_log(
                            f'Trackers {row["name"]}: {_tc.get("success_pct", 0)}% '
                            f'({_tc.get("passed", 0)}/{_tc.get("total", 0)})'
                        )
                    except Exception as exc:
                        result['tracker_ok'] = False
                        result['tracker_check'] = {'error': str(exc)}
                        logger.warning('Tracker check for %s failed: %s', row['name'], exc)
                _update_consecutive_failures(row['name'], success=True, threshold=auto_exclude)
            else:
                if _stop_event.is_set():
                    logger.info(
                        'Benchmark interrupted during %s — not counting it as a server failure',
                        row['name'],
                    )
                    _progress_log(f'Interrompu {row["name"]} - cycle prioritaire')
                    break
                _progress_log(f'Echec {row["name"]}')
                _excluded_failures = _update_consecutive_failures(
                    row['name'], success=False, threshold=auto_exclude
                )
                if _excluded_failures and _notif_exclude:
                    from .notify import send_auto_exclude_notification
                    send_auto_exclude_notification(
                        server=row['name'],
                        failures=_excluded_failures,
                        discord_url=_discord_url,
                        apprise_urls=_apprise_urls,
                        lang=_notif_lang,
                        companion_url=_companion_url,
                        mention=_mention,
                        mention_level=_mention_level,
                    )
            set_setting('benchmark_done_servers', str(idx))

        # ── No successful result at all → notify failure ─────────────────────
        if not results and _notif_bench_fail and not observation and not _stop_event.is_set():
            _fail_dur = round(time.time() - cycle_start, 1)
            from .notify import send_benchmark_failure_notification
            send_benchmark_failure_notification(
                n_servers=len(servers),
                duration_secs=_fail_dur,
                discord_url=_discord_url,
                apprise_urls=_apprise_urls,
                lang=_notif_lang,
                companion_url=_companion_url,
                mention=_mention,
                mention_level=_mention_level,
            )

        best_server_label: str | None = None
        best_server_name: str | None = None
        decision_results = results
        if auto_sw and results and tracker_required_for_switch and tracker_checks_enabled and not observation:
            _before_tracker_filter = len(results)
            decision_results = [r for r in results if r.get('tracker_ok')]
            if decision_results:
                logger.info(
                    'Tracker eligibility: keeping %d/%d benchmark result(s) for auto-switch',
                    len(decision_results), _before_tracker_filter,
                )
            else:
                logger.warning(
                    'Tracker eligibility: no benchmark result passed tracker threshold; auto-switch skipped'
                )
                _progress_log('Auto-switch ignore : aucun serveur compatible trackers')

        if auto_sw and decision_results:
            current_pct      = float(get_setting('weighted_score_current_pct', '65'))
            stability_weight = float(get_setting('stability_weight', '30'))
            active_profile   = get_setting('active_profile', 'balanced')
            # Compute per-server metadata once (no N+1 queries)
            from .database import (
                compute_confidence_all  as _conf_all,
                get_docker_event_counts as _event_counts,
                get_setting             as _gs,
            )
            from .profiles import score_results as _score_results
            _conf_map      = _conf_all()
            retention_days = int(_gs('db_retention_days', '30'))
            _reconnect_map = _event_counts(days=retention_days)
            _CONF_FACTORS  = {'HIGH': 1.0, 'MEDIUM': 0.95, 'LOW': 0.85}
            # Compute _weighted_score for every result (used as 'dl' axis in profiling)
            with get_db() as db:
                _ws_map = {
                    r['server']: _weighted_score(
                        r['server'], r['dl'], db, current_pct,
                        _CONF_FACTORS.get(
                            _conf_map.get(r['server'], {}).get('level', 'MEDIUM'), 0.95
                        ),
                        jitter_ms=r.get('jitter_ms'),
                        packet_loss_pct=r.get('packet_loss_pct'),
                        reconnect_count=_reconnect_map.get(r['server'], 0),
                        stability_weight=stability_weight,
                    )
                    for r in decision_results
                }
            # Profile-based normalised score → pick best (unconstrained first)
            _profile_scores = _score_results(decision_results, active_profile, _ws_map)
            best = max(decision_results, key=lambda r: _profile_scores.get(r['server'], 0.0))

            # ── WireGuard rotation policy ─────────────────────────────────────
            # Applied only when multiple VPN profiles are configured.
            _wg_rotation_mode = get_setting('wg_rotation_mode', 'none')
            _has_wg_profiles  = bool(_distinct_profile_ids)
            if _wg_rotation_mode != 'free' and _has_wg_profiles:
                # Determine current Gluetun server's profile
                _cur_filter_map  = get_current_filters(container)
                _cur_sv_name     = next(iter(_cur_filter_map.values()), '').split(',')[0].strip() \
                                   if _cur_filter_map else ''
                _cur_profile_id  = next(
                    (row['vpn_profile_id'] for row in servers if row['name'] == _cur_sv_name),
                    None,
                )

                # Build lookup helpers: profile id and rotation_allowed flag per server name
                _srv_profile_map = {
                    row['name']: (row['vpn_profile_id'], bool(row.get('vp_rotation_allowed', False)))
                    for row in servers
                }

                def _row_profile(name):
                    return _srv_profile_map.get(name, ('X', False))[0]

                def _row_rotation_allowed(name):
                    return _srv_profile_map.get(name, ('X', False))[1]

                if _wg_rotation_mode == 'none':
                    # Stay in current profile: only consider servers with the same profile id
                    _same = [r for r in decision_results if _row_profile(r['server']) == _cur_profile_id]
                    if _same:
                        best = max(_same, key=lambda r: _profile_scores.get(r['server'], 0.0))
                        logger.info(
                            'Rotation=none: constrained to profile #%s (%d candidates)',
                            _cur_profile_id, len(_same),
                        )
                    else:
                        logger.warning(
                            'Rotation=none but no results in current profile #%s — using global best',
                            _cur_profile_id,
                        )

                elif _wg_rotation_mode == 'conditional':
                    _wg_thr = float(get_setting('wg_rotation_threshold', '10')) / 100.0
                    _best_pid = _row_profile(best['server'])
                    if _best_pid != _cur_profile_id:
                        # Only rotate to a different profile if it has rotation_allowed=True
                        if not _row_rotation_allowed(best['server']):
                            logger.info(
                                'Rotation=conditional: cross-profile best %s is in profile #%s '
                                'which has rotation_allowed=False → staying in current profile',
                                best['server'], _best_pid,
                            )
                            _best_pid = _cur_profile_id  # force same-profile fallback below
                        if _best_pid != _cur_profile_id:
                            # Global best is a rotation-allowed cross-profile — check gain
                            _same = [r for r in decision_results if _row_profile(r['server']) == _cur_profile_id]
                            if _same:
                                _cur_pb = max(_same, key=lambda r: _profile_scores.get(r['server'], 0.0))
                                _cur_pb_score  = _profile_scores.get(_cur_pb['server'], 0.0)
                                _global_score  = _profile_scores.get(best['server'], 0.0)
                                _required      = _cur_pb_score * (1.0 + _wg_thr)
                                if _global_score <= _required:
                                    logger.info(
                                        'Rotation=conditional: cross-profile gain %.2f%% < threshold %.0f%% '
                                        '→ staying in profile #%s',
                                        (_global_score - _cur_pb_score) / max(_cur_pb_score, 1e-9) * 100,
                                        _wg_thr * 100,
                                        _cur_profile_id,
                                    )
                                    best = _cur_pb
                                else:
                                    logger.info(
                                        'Rotation=conditional: cross-profile gain %.2f%% ≥ threshold %.0f%% '
                                        '→ switching to profile #%s',
                                        (_global_score - _cur_pb_score) / max(_cur_pb_score, 1e-9) * 100,
                                        _wg_thr * 100,
                                        _best_pid,
                                    )
                        else:
                            # Forced back to same profile — pick best within it
                            _same = [r for r in decision_results if _row_profile(r['server']) == _cur_profile_id]
                            if _same:
                                best = max(_same, key=lambda r: _profile_scores.get(r['server'], 0.0))

            best_server_name  = best['server']   # bare name, for result lookup
            best_label = f"{FILTER_VARS.get(best['filter_type'], 'SERVER_NAMES')}={best_server_name}"
            logger.info(
                'Best (profile=%s): %s (%.1f Mbps current, score=%.4f)',
                active_profile, best_label, best['dl'],
                _profile_scores.get(best['server'], 0.0),
            )
            best_server_label = best_label

            from_label = format_filters(get_current_filters(container))

            # From-server's speed in this cycle (for delta logging)
            from_name = next(iter(get_current_filters(container).values()), '').split(',')[0].strip()
            from_result = next((r for r in results if r['server'] == from_name), None)
            from_mbps = from_result['dl'] if from_result else None

            if best_label != from_label:
                # Capture network dependents BEFORE Gluetun is recreated — use
                # the extended variant that also detects already-orphaned containers
                # (stale NetworkMode from a previous failed switch).
                pre_switch_net_deps = list_network_dependents_for_recreate(container)
                try:
                    from .port_forwarding import get_gluetun_provider
                    from_provider = get_gluetun_provider(container)
                except Exception:
                    from_provider = ''

                updated_images: list[str] = []
                if pull_gluetun:
                    from .gluetun import pull_image
                    ok_p, upd, img = pull_image(container)
                    logger.info('Gluetun pull: %s — %s', img, 'updated' if upd else 'up to date' if ok_p else 'failed')
                    if upd:
                        updated_images.append(img)
                # Build wg_profile arg for the best server (None if no profile)
                _best_pid = next(
                    (row['vpn_profile_id'] for row in servers
                     if row['name'] == best['server']),
                    None,
                )
                _best_wg = None
                if _best_pid is not None and _best_pid in _profile_env_cache:
                    _best_penv = _profile_env_cache[_best_pid]
                    _best_wg = {
                        'compose_provider': _best_penv['compose_provider'],
                        'vars': {
                            k: v for k, v in _best_penv['extra_env'].items()
                            if k not in ('VPN_SERVICE_PROVIDER', 'VPN_TYPE')
                        },
                    }
                to_provider = ((_best_wg or {}).get('compose_provider') or from_provider or '').strip().lower()
                ok, err = switch_server(
                    best['server'], best['filter_type'], container, compose_dir, project,
                    wg_profile=_best_wg,
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
                    _apply_port_forwards_after_provider_change(
                        from_provider, to_provider, 'auto_best',
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
                if ok and _notif_auto_sw:
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
                        discord_url=_discord_url,
                        apprise_urls=_apprise_urls,
                        lang=_notif_lang,
                        companion_url=_companion_url,
                        updated_images=updated_images or None,
                        qc_info=qc_info,
                        mention=_mention,
                        mention_level=_mention_level,
                        alert_type='auto_switch',
                    )
            else:
                logger.info('Already on best: %s', best_label)
                if _notif_best:
                    cur_ipv4, cur_ipv6 = get_public_ips(proxy_host, proxy_port, proxy_user, proxy_pass)
                    from .notify import send_already_best_notification
                    send_already_best_notification(
                        server=best_label,
                        speed_mbps=best['dl'],
                        ipv4=cur_ipv4,
                        ipv6=cur_ipv6,
                        discord_url=_discord_url,
                        apprise_urls=_apprise_urls,
                        lang=_notif_lang,
                        companion_url=_companion_url,
                        mention=_mention,
                        mention_level=_mention_level,
                    )

        duration_secs = round(time.time() - cycle_start, 1)
        logger.info('=== Benchmark cycle finished in %.0fs ===', duration_secs)
        _progress_log(f'Cycle termine - {len(results)} resultat(s)')

        with get_db() as db:
            db.execute(
                '''UPDATE benchmark_cycles
                   SET finished_at=CURRENT_TIMESTAMP, duration_secs=?, servers_tested=?, best_server=?
                   WHERE id=?''',
                (duration_secs, len(results), best_server_label, cycle_id),
            )

        if _notif_bench_end and results and not observation:
            _best_dl = next(
                (r['dl'] for r in results if r.get('server') == best_server_name),
                None,
            )
            from .notify import send_benchmark_end_notification
            send_benchmark_end_notification(
                n_tested=len(results),
                best_server=best_server_label,
                best_dl=_best_dl,
                duration_secs=duration_secs,
                discord_url=_discord_url,
                apprise_urls=_apprise_urls,
                lang=_notif_lang,
                companion_url=_companion_url,
                mention=_mention,
                mention_level=_mention_level,
            )

        # ── Optimal benchmark hour change notification ────────────────────────
        # Only fires when best_hour is stable across 2 consecutive cycles
        # (avoids spamming on statistical noise with few data points).
        if get_setting('notif_optimal_hour_change', '0') == '1':
            from .database import get_hourly_benchmark_stats as _hour_stats_fn
            try:
                _hour_stats = _hour_stats_fn()
                if _hour_stats.get('has_enough_data') and _hour_stats.get('best_hour') is not None:
                    _new_hour = _hour_stats['best_hour']
                    _old_hour_str    = get_setting('last_optimal_hour', '')
                    _pending_str     = get_setting('pending_optimal_hour', '')
                    _old_hour = int(_old_hour_str) if _old_hour_str.lstrip('-').isdigit() else None
                    _pending  = int(_pending_str)  if _pending_str.lstrip('-').isdigit()  else None

                    if _new_hour == _old_hour:
                        # Stable — clear any pending candidate
                        set_setting('pending_optimal_hour', '')
                    elif _new_hour == _pending:
                        # Confirmed stable for 2 cycles → notify now
                        set_setting('last_optimal_hour', str(_new_hour))
                        set_setting('pending_optimal_hour', '')
                        from .notify import send_optimal_hour_notification
                        send_optimal_hour_notification(
                            old_hour=_old_hour,
                            new_hour=_new_hour,
                            discord_url=_discord_url,
                            apprise_urls=_apprise_urls,
                            lang=_notif_lang,
                            companion_url=_companion_url,
                            mention=_mention,
                            mention_level=_mention_level,
                        )
                        logger.info(
                            'Optimal benchmark hour changed (confirmed): %s → %02dh',
                            _old_hour_str or '(none)', _new_hour,
                        )
                    else:
                        # New candidate — store it, wait for next cycle to confirm
                        set_setting('pending_optimal_hour', str(_new_hour))
                        logger.info(
                            'Optimal benchmark hour candidate: %02dh (will notify if confirmed next cycle)',
                            _new_hour,
                        )
            except Exception as _hour_exc:
                logger.warning('Optimal hour notification error: %s', _hour_exc)

        return len(results)

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
        _clear_benchmark_running()
        _current_test_trigger = None
        set_setting('benchmark_current_server', '')
        set_setting('benchmark_next_server', '')
        set_setting('benchmark_started_at', '')
        set_setting('benchmark_mode', '')
        set_setting('benchmark_total_servers', '0')
        set_setting('benchmark_done_servers', '0')


# ---------------------------------------------------------------------------
# Single-server on-demand test (launched from UI "Tester maintenant")
# ---------------------------------------------------------------------------

def test_single_server(app, server_name: str, filter_type: str):
    with _lock:
        _do_single_server(app, server_name, filter_type)


def _do_single_server(app, server_name: str, filter_type: str):
    from .database import get_db, get_setting, set_setting, get_vpn_profile as _get_prof_ss
    from .crypto import decrypt as _dec_ss, is_encrypted as _is_enc_ss
    from .wg_providers import WG_PROVIDERS as _WGP_SS
    from .gluetun import (
        switch_server, wait_for_vpn,
        get_current_filters, restart_network_dependents,
        list_network_dependents, list_network_dependents_for_recreate,
    )

    set_setting('benchmark_running', '1')
    logger.info('Single-server test: %s (%s)', server_name, filter_type)

    try:
        container   = app.config['GLUETUN_CONTAINER']
        compose_dir = app.config['COMPOSE_DIR']
        project     = app.config.get('COMPOSE_PROJECT', '')
        proxy_host  = app.config['GLUETUN_HOST']
        proxy_port  = app.config['GLUETUN_PROXY_PORT']
        try:
            from .port_forwarding import get_gluetun_provider
            from_provider = get_gluetun_provider(container)
        except Exception:
            from_provider = ''

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

        # ── Load WireGuard profile for this server (profile-aware switch) ────
        with get_db() as _db_ss:
            _srv_row = _db_ss.execute(
                'SELECT vpn_profile_id FROM servers WHERE name = ?', (server_name,)
            ).fetchone()
        _ss_profile_id = _srv_row['vpn_profile_id'] if _srv_row else None
        _ss_wg_profile = None
        _ss_sidecar_override: dict[str, str] = {}
        _ss_sidecar_reuse = False
        if _ss_profile_id is not None:
            _ss_p = _get_prof_ss(_ss_profile_id)
            if _ss_p:
                _ss_prov_key = _ss_p['provider']
                _ss_prov_def = _WGP_SS.get(_ss_prov_key, {})
                _ss_compose_prov = _ss_prov_def.get('compose_provider', _ss_prov_key)
                _ss_vars: dict[str, str] = {}
                _ss_sidecar_reuse = bool(_ss_p.get('sidecar_reuse_profile', False))
                for _k, _v in _ss_p['vars'].items():
                    try:
                        _ss_vars[_k] = _dec_ss(_v) if _is_enc_ss(_v) else _v
                    except ValueError:
                        _ss_vars[_k] = ''
                _ss_wg_profile = {'compose_provider': _ss_compose_prov, 'vars': _ss_vars}
                # Per-profile sidecar key
                _sc_pk = _ss_p.get('sidecar_private_key', '')
                _sc_ad = _ss_p.get('sidecar_addresses', '')
                _sc_ps = _ss_p.get('sidecar_preshared_key', '')
                if _sc_pk:
                    try:
                        _ss_sidecar_override['WIREGUARD_PRIVATE_KEY'] = (
                            _dec_ss(_sc_pk) if _is_enc_ss(_sc_pk) else _sc_pk
                        )
                    except ValueError:
                        pass
                if _sc_ad:
                    _ss_sidecar_override['WIREGUARD_ADDRESSES'] = _sc_ad
                if _sc_ps:
                    try:
                        _ss_sidecar_override['WIREGUARD_PRESHARED_KEY'] = (
                            _dec_ss(_sc_ps) if _is_enc_ss(_sc_ps) else _sc_ps
                        )
                    except ValueError:
                        pass

        to_provider = ((_ss_wg_profile or {}).get('compose_provider') or from_provider or '').strip().lower()

        if sidecar_mode:
            # ── Sidecar mode: test in isolation, switch only on success ──────
            # Build sidecar env: profile vars + dedicated key override, or
            # profile vars only when reuse is explicitly enabled.
            _ss_sidecar_env: dict[str, str] = {}
            _ss_sidecar_allowed = bool(_ss_sidecar_override) or _ss_sidecar_reuse
            if _ss_wg_profile and _ss_sidecar_allowed:
                _ss_sidecar_env.update({'VPN_SERVICE_PROVIDER': _ss_wg_profile['compose_provider'],
                                         'VPN_TYPE': 'wireguard'})
                _ss_sidecar_env.update(_ss_wg_profile['vars'])
            if _ss_sidecar_override:
                _ss_sidecar_env.update(_ss_sidecar_override)
            if _ss_wg_profile and not _ss_sidecar_allowed:
                logger.info(
                    'Server %s: skipping sidecar (no sidecar key or reuse option for profile #%s)',
                    server_name, _ss_profile_id,
                )
                result = None
            else:
                result = _test_server_sidecar_with_retry(
                    server_name, filter_type,
                    container, sidecar_image, proxy_host, sidecar_port,
                    wait_secs, dl_duration, dl_streams, max_retries, timeout_secs,
                    sidecar_method, sidecar_iperf_fallback,
                    extra_env=_ss_sidecar_env or None,
                )
            if result is None and sidecar_proxy_fallback:
                logger.info('Sidecar failed for %s — falling back to HTTP proxy', server_name)
                # Proxy fallback: save original server so we can revert on failure
                orig_filters = get_current_filters(container)
                result = _test_server_with_retry(
                    server_name, filter_type,
                    container, compose_dir, project,
                    proxy_host, proxy_port, proxy_user, proxy_pass,
                    wait_secs, dl_duration, dl_samples, lat_samples,
                    warmup, dl_streams, max_retries, timeout_secs,
                )
                if result is None and orig_filters:
                    # Proxy test failed → revert Gluetun to the original server
                    orig_ft = next(iter(orig_filters))
                    orig_sv = orig_filters[orig_ft].split(',')[0].strip()
                    if orig_sv and orig_sv != server_name:
                        logger.info('Proxy fallback failed → reverting Gluetun to %s', orig_sv)
                        switch_server(orig_sv, orig_ft, container, compose_dir, project)

            if result:
                # Test succeeded (sidecar or proxy fallback) → switch real Gluetun
                logger.info('Single-server test passed (%.1f Mbps) → switching Gluetun to %s',
                            result['dl'], server_name)
                pre_deps = list_network_dependents_for_recreate(container)
                ok, err = switch_server(server_name, filter_type, container, compose_dir, project,
                                        wg_profile=_ss_wg_profile)
                if ok:
                    connected, _ = wait_for_vpn(
                        proxy_host, proxy_port, timeout=wait_secs,
                        proxy_user=proxy_user, proxy_password=proxy_pass,
                    )
                    restarted, _ = restart_network_dependents(
                        container, compose_dir, project, explicit_list=pre_deps,
                    )
                    if restarted:
                        logger.info('Recreated network dependents: %s', ', '.join(restarted))
                    _apply_port_forwards_after_provider_change(
                        from_provider, to_provider, 'single_server',
                    )
                    if connected:
                        logger.info('Gluetun now on %s', server_name)
                    else:
                        logger.warning('Switched to %s but VPN reconnect timed out', server_name)
                else:
                    logger.error('Switch to %s failed after sidecar test: %s', server_name, err)

        else:
            # ── Proxy mode: Gluetun must switch first; revert on failure ────
            orig_filters = get_current_filters(container)
            result = _test_server_with_retry(
                server_name, filter_type,
                container, compose_dir, project,
                proxy_host, proxy_port, proxy_user, proxy_pass,
                wait_secs, dl_duration, dl_samples, lat_samples,
                warmup, dl_streams, max_retries, timeout_secs,
                wg_profile=_ss_wg_profile,
            )
            if result is None and orig_filters:
                # Test failed → revert Gluetun to the server it was on before
                orig_ft = next(iter(orig_filters))
                orig_sv = orig_filters[orig_ft].split(',')[0].strip()
                if orig_sv and orig_sv != server_name:
                    logger.info('Proxy single-server test failed → reverting Gluetun to %s', orig_sv)
                    switch_server(orig_sv, orig_ft, container, compose_dir, project)
            elif result:
                logger.info('Single-server proxy test done: %s %.1f Mbps — Gluetun stays on this server',
                            server_name, result['dl'])

        if result:
            _update_consecutive_failures(server_name, success=True, threshold=auto_exclude)
        else:
            _update_consecutive_failures(server_name, success=False, threshold=auto_exclude)
    finally:
        _clear_benchmark_running()


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
    dl_single_mbps: float | None = None,
):
    from .database import get_db
    if trigger is None:
        trigger = _current_test_trigger
    with get_db() as db:
        db.execute(
            '''INSERT INTO speed_tests
               (server_name, download_mbps, upload_mbps, latency_ms,
                public_ip, public_ipv6, success, error_msg, test_method,
                dl_ookla, ul_ookla, dl_librespeed, ul_librespeed, dl_iperf3, ul_iperf3,
                jitter_ms, packet_loss_pct, ping_min_ms, ping_max_ms, dns_latency_ms,
                test_trigger, dl_single_mbps)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (server_name, download_mbps, upload_mbps, latency_ms,
             public_ip, public_ipv6, int(success), error, method,
             dl_ookla, ul_ookla, dl_librespeed, ul_librespeed, dl_iperf3, ul_iperf3,
             jitter_ms, packet_loss_pct, ping_min_ms, ping_max_ms, dns_latency_ms,
             trigger, dl_single_mbps),
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


def _apply_port_forwards_after_provider_change(
    old_provider: str,
    new_provider: str,
    reason: str,
) -> dict:
    from .port_forwarding import apply_after_provider_change
    result = apply_after_provider_change(old_provider, new_provider, reason=reason)
    if result.get('provider_changed') and not result.get('skipped_reason'):
        logger.info(
            'Port forwards after provider change %s -> %s: applied %s/%s, ok=%s',
            old_provider or '?', new_provider or '?',
            result.get('applied', 0), result.get('rules', 0), result.get('ok'),
        )
    return result


def _apply_port_forwards_for_current_provider(container: str, reason: str) -> dict:
    from .database import get_setting
    if get_setting('port_forward_enabled', '0') != '1':
        return {'ok': True, 'skipped_reason': 'disabled'}
    if get_setting('port_forward_auto_sync', '0') != '1':
        return {'ok': True, 'skipped_reason': 'manual_only'}
    from .port_forwarding import apply_provider_port_forwards, get_gluetun_provider
    provider = get_gluetun_provider(container)
    if not provider:
        return {'ok': False, 'skipped_reason': 'missing_provider'}
    return apply_provider_port_forwards(provider, reason=reason)


def _update_consecutive_failures(
    server_name: str, success: bool, threshold: int
) -> int | None:
    """
    Update the consecutive-failure counter for *server_name*.
    Returns the failure count when the server is auto-disabled, None otherwise.
    """
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
                    n_fail = row['consecutive_failures']
                    logger.warning(
                        'Server %s auto-disabled after %d consecutive failures',
                        server_name, n_fail,
                    )
                    return n_fail
    return None


# ---------------------------------------------------------------------------
# Scheduler lifecycle
# ---------------------------------------------------------------------------

def purge_old_tests(app):
    """Delete speed_tests older than db_retention_days. 0 = disabled."""
    from .database import get_db, get_setting, set_setting
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
        mention=get_setting('notify_mention', '').strip() or None,
        mention_level=get_setting('notify_mention_level', 'critical'),
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
            _clear_benchmark_running()
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

                # Record every Gluetun container ID (Companion-triggered or
                # not) — this history is what lets the orphan scan recognise
                # dependents of former Gluetun instances.
                try:
                    from .gluetun import record_gluetun_id
                    record_gluetun_id(event.get('id', ''))
                except Exception:
                    pass

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
                    from .gluetun import (
                        list_orphaned_network_dependents,
                        restart_network_dependents,
                    )
                    wait = int(_gs('connection_wait_seconds', '45'))
                    logger.info(
                        'Docker event: waiting %ds for VPN reconnect before quick check…', wait
                    )
                    time.sleep(wait)

                    # After an external Gluetun restart, containers that share its
                    # network namespace (network_mode: service:gluetun-*) still
                    # reference the old (now dead) container ID.  They appear
                    # "running" but have no working network.  Recreate them now so
                    # the user's services (qBittorrent, etc.) come back up cleanly.
                    try:
                        orphans = list_orphaned_network_dependents()
                        if orphans:
                            logger.info(
                                'Docker event: orphaned network-dependent containers detected: %s — recreating…',
                                ', '.join(orphans),
                            )
                            compose_dir = a.config.get('COMPOSE_DIR', '')
                            project     = a.config.get('COMPOSE_PROJECT', '')
                            restarted, _ = restart_network_dependents(
                                container_name,
                                compose_dir, project,
                                explicit_list=orphans,
                            )
                            if restarted:
                                logger.info(
                                    'Docker event: recreated orphaned containers: %s',
                                    ', '.join(restarted),
                                )
                        else:
                            logger.info('Docker event: no orphaned network-dependent containers found')
                    except Exception as _exc:
                        logger.warning('Docker event: error recreating orphaned containers: %s', _exc)

                    try:
                        pf = _apply_port_forwards_for_current_provider(
                            container_name, 'docker_reconnect',
                        )
                        if not pf.get('skipped_reason'):
                            logger.info(
                                'Docker event: port forwards reapplied for provider %s (%s/%s)',
                                pf.get('provider') or '?',
                                pf.get('applied', 0), pf.get('rules', 0),
                            )
                    except Exception as _exc:
                        logger.warning('Docker event: port forward reapply failed: %s', _exc)

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


def _check_rotation_pools(app):
    """
    Runs every 5 minutes. For each auto-rotate pool whose next_rotation_at has
    passed, execute a pool rotation — unless a benchmark is already running.
    Pool rotations are intentionally NOT locked by _lock to avoid blocking the
    benchmark; instead we check benchmark_running before switching.
    """
    from .database import get_db, get_setting, set_setting
    from .rotation_pools import do_pool_rotation

    with app.app_context():
        try:
            with get_db() as db:
                due = db.execute(
                    """SELECT id, name FROM rotation_pools
                       WHERE enabled = 1 AND auto_rotate = 1
                         AND next_rotation_at IS NOT NULL
                         AND next_rotation_at <= datetime('now')
                       ORDER BY next_rotation_at""",
                ).fetchall()
        except Exception as exc:
            logger.error('Pool rotation check: DB error: %s', exc)
            return

        if not due:
            return

        for row in due:
            wait_for_observation = False
            if get_setting('benchmark_running', '0') == '1':
                if get_setting('benchmark_mode', '') == 'observation':
                    logger.info(
                        'Pool rotation [%d] "%s": due — pausing continuous observation first',
                        row['id'], row['name'],
                    )
                    _progress_log('Observation continue mise en pause : rotation de pool prioritaire')
                    _stop_event.set()
                    wait_for_observation = True
                else:
                    logger.info(
                        'Pool rotation [%d] "%s": benchmark running — deferring',
                        row['id'], row['name'],
                    )
                    continue
            if wait_for_observation:
                acquired = _lock.acquire(blocking=True, timeout=180)
            else:
                acquired = _lock.acquire(blocking=False)
            if not acquired:
                logger.info(
                    'Pool rotation [%d] "%s": scheduler lock busy; deferring',
                    row['id'], row['name'],
                )
                continue
            logger.info(
                'Pool rotation [%d] "%s": auto-rotation due — executing',
                row['id'], row['name'],
            )
            try:
                result = do_pool_rotation(row['id'], app, manual=False)
                if result['ok']:
                    logger.info(
                        'Pool rotation [%d]: switched to %s%s',
                        row['id'], result['server'],
                        f' ({result["dl_mbps"]:.1f} Mbps)' if result.get('dl_mbps') else '',
                    )
                else:
                    logger.warning(
                        'Pool rotation [%d]: failed — %s', row['id'], result.get('error')
                    )
            except Exception as exc:
                logger.error('Pool rotation [%d]: unexpected error: %s', row['id'], exc)
                _clear_benchmark_running()
                set_setting('benchmark_current_server', '')
            finally:
                _lock.release()


def _check_continuous_observation(app):
    """
    Watchdog for pyramidal continuous observation.

    This is deliberately independent from auto_benchmark: rotation pools may put
    the planned benchmark cycle on standby, but observation is an explicit data
    collection mode and must resume after restarts as long as there is work left.
    """
    from .database import get_setting
    global _observation_watchdog_state

    with app.app_context():
        def _state_once(state: str, message: str, level: str = 'info') -> None:
            global _observation_watchdog_state
            if _observation_watchdog_state == state:
                return
            _observation_watchdog_state = state
            getattr(logger, level)(message)
            _progress_log(message)

        if get_setting('continuous_observation', '0') != '1':
            _observation_watchdog_state = None
            return
        if get_setting('benchmark_running', '0') == '1':
            _observation_watchdog_state = 'running'
            return
        if _lock.locked():
            _state_once(
                'busy',
                'Continuous observation watchdog: scheduler lock busy — waiting',
            )
            return
        try:
            has_work = _has_observation_work_left()
        except Exception as exc:
            _state_once(
                'error',
                f'Continuous observation watchdog: cannot evaluate work left — {exc}',
                level='warning',
            )
            return
        if not has_work:
            _state_once(
                'complete',
                'Continuous observation watchdog: enabled, but target is already reached',
            )
            return
        _observation_watchdog_state = 'starting'
        logger.info('Continuous observation watchdog: work detected — starting/resuming now')
        _progress_log('Observation continue : reprise automatique')
        trigger_observation_now(app)


def start_scheduler(app):
    global _scheduler
    from .database import get_setting, get_db

    with app.app_context():
        # No benchmark can be running right after boot — clear any flags left
        # over from a crash or restart mid-cycle, otherwise the UI banner
        # stays stuck (running and/or "stop requested" shown forever).
        from .database import set_setting as _set
        _set('benchmark_running', '0')
        _set('benchmark_stop_requested', '0')
        _set('benchmark_current_server', '')
        _set('benchmark_next_server', '')

        hours   = float(get_setting('test_interval_hours', '6'))
        enabled = get_setting('auto_benchmark', '1') == '1'

        # If any auto-rotating pool is active, the pool rotation manages the
        # schedule — the regular benchmark cycle must stay paused regardless
        # of the auto_benchmark setting.  This handles restarts where
        # auto_benchmark may still be '1' from before the pool was activated.
        _active_pools = 0
        try:
            with get_db() as _db:
                _active_pools = _db.execute(
                    'SELECT COUNT(*) AS n FROM rotation_pools'
                    ' WHERE enabled = 1 AND auto_rotate = 1'
                ).fetchone()['n']
        except Exception:
            pass
        if _active_pools:
            enabled = False
            # Keep the DB in sync so the UI checkbox state is consistent
            if get_setting('auto_benchmark', '1') == '1':
                from .database import set_setting
                set_setting('auto_benchmark', '0')

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
    _scheduler.add_job(
        _check_rotation_pools,
        trigger=IntervalTrigger(minutes=5),
        args=[app],
        id='pool_rotation_check',
        replace_existing=True,
        misfire_grace_time=120,
    )
    _scheduler.add_job(
        _check_continuous_observation,
        trigger=IntervalTrigger(minutes=1),
        args=[app],
        id='continuous_observation_watchdog',
        replace_existing=True,
        misfire_grace_time=120,
    )
    _scheduler.start()

    # Docker event listener — watches Gluetun container for unexpected restarts
    start_docker_event_listener(app, app.config['GLUETUN_CONTAINER'])

    if not enabled:
        _scheduler.pause_job('benchmark')
        if _active_pools:
            logger.info(
                'Scheduler started — benchmark PAUSED (%d active rotation pool(s) — manual trigger still available)',
                _active_pools,
            )
            with app.app_context():
                if get_setting('continuous_observation', '0') == '1':
                    logger.info(
                        'Continuous observation enabled at startup — watchdog will resume it even while benchmark cycle is paused'
                    )
                    trigger_observation_now(app)
        else:
            logger.info('Scheduler started — automatic benchmark DISABLED (manual trigger only)')
    else:
        logger.info('Scheduler started — benchmark every %.1f hours', hours)
        with app.app_context():
            if get_setting('continuous_observation', '0') == '1':
                logger.info('Continuous observation enabled at startup — starting immediately')
                trigger_observation_now(app)


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


def trigger_observation_now(app):
    """Start or resume continuous observation immediately if it is enabled."""
    t = threading.Thread(target=run_observation_now, args=[app], daemon=True, name='observation-now')
    t.start()


def run_quick_check_now(app):
    """Manual quick benchmark — proxy test of current server only, no VPN switch."""
    from .database import get_db, get_setting, set_setting
    from .gluetun import get_current_filters, get_public_ips

    with _lock:
        _stop_event.clear()   # reset any leftover stop signal
        set_setting('benchmark_stop_requested', '0')
        set_setting('benchmark_running', '1')
        set_setting('benchmark_mode', 'quick')
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

            # Fetch previous proxy_qc baseline for comparison in notification
            with get_db() as db:
                _prev = db.execute(
                    "SELECT download_mbps FROM speed_tests "
                    "WHERE server_name=? AND success=1 AND test_method='proxy_qc' "
                    "ORDER BY tested_at DESC LIMIT 1",
                    (server_name,),
                ).fetchone()
            last_dl = _prev['download_mbps'] if _prev else None

            logger.info('Quick benchmark: testing %s via HTTP proxy', server_name)
            dl = _test_direct_proxy(
                proxy_host, proxy_port, proxy_user, proxy_pass,
                dl_duration, dl_samples, warmup, dl_streams,
            )
            if dl is not None:
                _qnow_ipv4, _qnow_ipv6 = get_public_ips(proxy_host, proxy_port, proxy_user, proxy_pass)
                _record_test(server_name, success=True, download_mbps=dl, method='proxy_qc',
                             public_ip=_qnow_ipv4, public_ipv6=_qnow_ipv6)
                logger.info('Quick benchmark: %s → %.1f Mbps (saved as proxy_qc)', server_name, dl)

                # ── Notification ─────────────────────────────────────────────
                if get_setting('notif_quick_check', '1') == '1':
                    _discord_url   = get_setting('discord_webhook_url') or None
                    _apprise_urls  = get_setting('apprise_urls') or None
                    _notif_lang    = get_setting('ui_lang', 'fr')
                    _companion_url = get_setting('companion_url') or None
                    _mention       = get_setting('notify_mention', '').strip() or None
                    _mention_level = get_setting('notify_mention_level', 'critical')
                    from .notify import send_quick_check_notification
                    send_quick_check_notification(
                        server=server_name,
                        speed_mbps=dl,
                        last_mbps=last_dl,
                        ipv4=_qnow_ipv4,
                        ipv6=_qnow_ipv6,
                        discord_url=_discord_url,
                        apprise_urls=_apprise_urls,
                        lang=_notif_lang,
                        companion_url=_companion_url,
                        mention=_mention,
                        mention_level=_mention_level,
                    )
            else:
                logger.warning('Quick benchmark: proxy test failed for %s', server_name)
        finally:
            _clear_benchmark_running()
            set_setting('benchmark_mode', '')
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
