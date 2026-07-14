"""
Rotation pools — server rotation without full benchmarks.

A pool defines a set of candidate servers (via combinable criteria) and a
rotation mode. Companion rotates to a picked server on demand or on a
schedule, optionally running a quick proxy speed test afterwards.

Rotation modes:
  random      — random.choice(candidates)
  round_robin — cycle through candidates alphabetically
  best_score  — server with highest historical average download speed
"""

import json
import logging
import random
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Server resolution
# ---------------------------------------------------------------------------

def resolve_pool_servers(pool_id: int, automatic: bool = True) -> list[dict]:
    """
    Return the list of candidate servers for this pool, combining all criteria
    using either union (each criterion adds servers) or intersection (each
    criterion restricts the set), depending on pool.criteria_logic.

    If top_n is set on the pool, restrict to the top-N by historical avg
    download speed (proxy_qc excluded, same window as scoring).

    Explicit per-pool exclusions are applied after criteria and before top_n.
    Global country exclusions apply to automatic rotations, while a manual
    pool rotation can still be used as an explicit override.

    Each returned dict: {id, name, filter_type, vpn_profile_id, avg_dl}
    """
    from .database import get_db

    with get_db() as db:
        pool = db.execute(
            'SELECT * FROM rotation_pools WHERE id = ?', (pool_id,)
        ).fetchone()
        if not pool:
            return []
        pool = dict(pool)

        criteria = db.execute(
            'SELECT * FROM rotation_pool_criteria WHERE pool_id = ? ORDER BY id',
            (pool_id,),
        ).fetchall()

        candidate_sets: list[set[str]] = []

        for crit in criteria:
            ctype = crit['crit_type']
            cval  = crit['crit_value']

            if ctype == 'all':
                rows = db.execute(
                    '''SELECT s.name
                       FROM servers s
                       LEFT JOIN vpn_profiles vp ON vp.id = s.vpn_profile_id
                       WHERE s.enabled = 1
                         AND (s.vpn_profile_id IS NULL OR vp.enabled = 1)'''
                ).fetchall()
                candidate_sets.append({r['name'] for r in rows})

            elif ctype == 'server':
                # Include even if disabled? No — only active servers.
                row = db.execute(
                    '''SELECT s.name
                       FROM servers s
                       LEFT JOIN vpn_profiles vp ON vp.id = s.vpn_profile_id
                       WHERE s.name = ? AND s.enabled = 1
                         AND (s.vpn_profile_id IS NULL OR vp.enabled = 1)''',
                    (cval,),
                ).fetchone()
                if row:
                    candidate_sets.append({row['name']})

            elif ctype == 'filter':
                try:
                    fdata = json.loads(cval) if cval else {}
                    ftype = fdata.get('type', '').strip()
                    fval  = fdata.get('value', '').strip()
                except (json.JSONDecodeError, AttributeError, TypeError):
                    logger.warning('Pool %d: malformed filter criterion: %r', pool_id, cval)
                    continue
                if ftype and fval:
                    rows = db.execute(
                        '''SELECT s.name
                           FROM servers s
                           LEFT JOIN vpn_profiles vp ON vp.id = s.vpn_profile_id
                           WHERE s.filter_type = ? AND s.name = ? AND s.enabled = 1
                             AND (s.vpn_profile_id IS NULL OR vp.enabled = 1)''',
                        (ftype, fval),
                    ).fetchall()
                elif ftype:
                    # All servers of this filter type
                    rows = db.execute(
                        '''SELECT s.name
                           FROM servers s
                           LEFT JOIN vpn_profiles vp ON vp.id = s.vpn_profile_id
                           WHERE s.filter_type = ? AND s.enabled = 1
                             AND (s.vpn_profile_id IS NULL OR vp.enabled = 1)''',
                        (ftype,),
                    ).fetchall()
                else:
                    rows = []
                candidate_sets.append({r['name'] for r in rows})

            elif ctype == 'profile':
                try:
                    profile_id = int(cval)
                except (TypeError, ValueError):
                    continue
                rows = db.execute(
                    '''SELECT s.name
                       FROM servers s
                       JOIN vpn_profiles vp ON vp.id = s.vpn_profile_id
                       WHERE s.vpn_profile_id = ? AND s.enabled = 1 AND vp.enabled = 1''',
                    (profile_id,),
                ).fetchall()
                candidate_sets.append({r['name'] for r in rows})

            elif ctype == 'top_metric':
                try:
                    mdata  = json.loads(cval) if cval else {}
                    metric = str(mdata.get('metric', '')).strip()
                    n      = int(mdata.get('n', 0))
                except (json.JSONDecodeError, AttributeError, TypeError, ValueError):
                    logger.warning('Pool %d: malformed top_metric criterion: %r', pool_id, cval)
                    continue
                if metric not in ('dl', 'jitter', 'loss', 'dns') or n < 1:
                    logger.warning('Pool %d: invalid top_metric metric=%r n=%r', pool_id, metric, n)
                    continue
                _metric_col = {
                    'dl':     'AVG(CASE WHEN st.success=1 AND st.test_method!="proxy_qc" THEN st.download_mbps END)',
                    'jitter': 'AVG(CASE WHEN st.success=1 AND st.test_method!="proxy_qc" THEN st.jitter_ms END)',
                    'loss':   'AVG(CASE WHEN st.success=1 AND st.test_method!="proxy_qc" THEN st.packet_loss_pct END)',
                    'dns':    'AVG(CASE WHEN st.success=1 AND st.test_method!="proxy_qc" THEN st.dns_latency_ms END)',
                }[metric]
                _order = 'ASC' if metric in ('jitter', 'loss', 'dns') else 'DESC'
                rows = db.execute(
                    f'''SELECT s.name
                        FROM servers s
                        LEFT JOIN vpn_profiles vp ON vp.id = s.vpn_profile_id
                        LEFT JOIN speed_tests st ON st.server_name = s.name
                        WHERE s.enabled = 1
                          AND (s.vpn_profile_id IS NULL OR vp.enabled = 1)
                        GROUP BY s.id
                        HAVING {_metric_col} IS NOT NULL
                        ORDER BY {_metric_col} {_order}
                        LIMIT ?''',
                    (n,),
                ).fetchall()
                candidate_sets.append({r['name'] for r in rows})

            elif ctype == 'airvpn_bw_min':
                try:
                    bw_min = int(cval)
                except (TypeError, ValueError):
                    continue
                if bw_min < 1:
                    continue
                rows = db.execute(
                    '''SELECT s.name
                       FROM servers s
                       LEFT JOIN vpn_profiles vp ON vp.id = s.vpn_profile_id
                       JOIN airvpn_snapshot av ON av.name = s.name
                       WHERE s.enabled = 1
                         AND s.filter_type = 'name'
                         AND av.bw_max_mbps >= ?
                         AND (s.vpn_profile_id IS NULL OR vp.enabled = 1)''',
                    (bw_min,),
                ).fetchall()
                candidate_sets.append({r['name'] for r in rows})

        non_empty_sets = [s for s in candidate_sets if s]
        if not non_empty_sets:
            return []
        if pool.get('criteria_logic') == 'intersection':
            candidate_names = set.intersection(*non_empty_sets)
        else:
            candidate_names = set.union(*non_empty_sets)

        if not candidate_names:
            return []

        excluded_names = {
            r['server_name'] for r in db.execute(
                'SELECT server_name FROM rotation_pool_exclusions WHERE pool_id = ?',
                (pool_id,),
            ).fetchall()
        }
        candidate_names -= excluded_names

        if automatic:
            from .database import get_setting
            from .server_eligibility import parse_excluded_countries, excluded_server_names
            country_codes = parse_excluded_countries(get_setting('excluded_countries', '[]'))
            candidate_names -= excluded_server_names(db, country_codes)

        if not candidate_names:
            return []

        # Fetch full server data + historical avg_dl for scoring / top-N
        placeholders = ','.join('?' * len(candidate_names))
        servers = db.execute(
            f'''SELECT s.id, s.name, s.filter_type, s.vpn_profile_id,
                       COALESCE(
                           AVG(CASE WHEN st.success = 1 AND st.test_method != 'proxy_qc'
                                    THEN st.download_mbps END),
                           0.0
                       ) AS avg_dl
                FROM servers s
                LEFT JOIN vpn_profiles vp ON vp.id = s.vpn_profile_id
                LEFT JOIN speed_tests st ON st.server_name = s.name
                WHERE s.name IN ({placeholders})
                  AND s.enabled = 1
                  AND (s.vpn_profile_id IS NULL OR vp.enabled = 1)
                GROUP BY s.id''',
            list(candidate_names),
        ).fetchall()

        candidates = [dict(s) for s in servers]

    # Apply top_n filter
    top_n = pool.get('top_n')
    if top_n and isinstance(top_n, int) and top_n > 0 and len(candidates) > top_n:
        candidates.sort(key=lambda x: x['avg_dl'], reverse=True)
        candidates = candidates[:top_n]

    try:
        from .database import get_setting
        if get_setting('tracker_check_enabled', '0') == '1' and get_setting('tracker_require_for_switch', '0') == '1':
            from .torrent_trackers import tracker_status_for_servers
            statuses = tracker_status_for_servers([c['name'] for c in candidates])
            kept = []
            skipped = []
            for cand in candidates:
                status = statuses.get(cand['name'])
                cand['tracker_status'] = status or {'known': False}
                if status and status.get('known') and not status.get('ok'):
                    skipped.append(
                        f"{cand['name']}({status.get('success_pct', 0)}% "
                        f"{status.get('passed', 0)}/{status.get('tested', 0)})"
                    )
                    continue
                kept.append(cand)
            if skipped:
                logger.info(
                    'Pool %d tracker filter: skipped %d known-incompatible candidate(s): %s',
                    pool_id, len(skipped), ', '.join(skipped),
                )
            candidates = kept
    except Exception as exc:
        logger.warning('Pool %d tracker eligibility filter failed: %s', pool_id, exc)

    return candidates


# ---------------------------------------------------------------------------
# Server selection
# ---------------------------------------------------------------------------

def pick_server(pool: dict, candidates: list[dict]) -> dict | None:
    """
    Pick one server from candidates according to pool mode.
    round_robin uses pool['current_rr_idx'] as a cursor into the
    alphabetically-sorted candidate list.
    """
    if not candidates:
        return None

    mode = pool.get('mode', 'random')

    if mode == 'random':
        return random.choice(candidates)

    elif mode == 'round_robin':
        sorted_cands = sorted(candidates, key=lambda x: x['name'])
        idx = int(pool.get('current_rr_idx') or 0) % len(sorted_cands)
        return sorted_cands[idx]

    elif mode == 'best_score':
        return max(candidates, key=lambda x: float(x.get('avg_dl') or 0))

    return random.choice(candidates)


def _next_rr_idx(pool: dict, candidates: list[dict], picked_name: str) -> int:
    """Return the next round-robin cursor after picking picked_name."""
    sorted_cands = sorted(candidates, key=lambda x: x['name'])
    if not sorted_cands:
        return 0
    try:
        cur_pos = next(i for i, s in enumerate(sorted_cands) if s['name'] == picked_name)
    except StopIteration:
        cur_pos = int(pool.get('current_rr_idx') or 0)
    return (cur_pos + 1) % len(sorted_cands)


# ---------------------------------------------------------------------------
# Full rotation execution
# ---------------------------------------------------------------------------

def do_pool_rotation(pool_id: int, app, manual: bool = False) -> dict:
    """
    Execute one rotation cycle for a pool:
      1. Resolve candidate servers from pool criteria
      2. Pick one server (random / round-robin / best-score)
      3. Switch Gluetun (override Compose + docker compose up -d)
      4. Optional: wait for VPN + run proxy_qc speed test
      5. Update pool state (last_rotated_at, next_rotation_at, rr_idx)
      6. Optional: send Discord/Apprise notification

    Returns {ok: bool, server: str|None, dl_mbps: float|None, error: str|None}
    """
    from .database import (
        get_db, get_setting, set_setting, get_vpn_profile,
        set_pool_rotation_state, set_pool_last_error,
    )
    from .gluetun import (
        switch_server, wait_for_vpn, get_public_ips, get_active_server,
        list_network_dependents, list_network_dependents_for_recreate,
        restart_network_dependents, pull_gluetun_before_switch,
        restart_configured_post_switch_containers,
    )
    from .crypto import decrypt as crypto_decrypt, is_encrypted as is_enc
    from .wg_providers import WG_PROVIDERS

    # ── Load pool ────────────────────────────────────────────────────────────
    pool = None
    with get_db() as db:
        row = db.execute('SELECT * FROM rotation_pools WHERE id = ?', (pool_id,)).fetchone()
        if row:
            pool = dict(row)

    if not pool:
        logger.error('Pool rotation: pool %d not found', pool_id)
        return {'ok': False, 'server': None, 'dl_mbps': None, 'error': 'Pool not found'}
    if not pool.get('enabled'):
        logger.info('Pool rotation [%d] "%s": disabled', pool_id, pool['name'])
        set_pool_last_error(pool_id, 'Pool disabled')
        return {'ok': False, 'server': None, 'dl_mbps': None, 'error': 'Pool disabled'}

    logger.info(
        'Pool rotation [%d] "%s": resolving candidates (mode=%s, manual=%s)',
        pool_id, pool['name'], pool['mode'], manual,
    )

    candidates = resolve_pool_servers(pool_id, automatic=not manual)
    if not candidates:
        logger.warning('Pool rotation [%d] "%s": no candidates — skipping', pool_id, pool['name'])
        set_pool_last_error(pool_id, 'No candidates')
        return {'ok': False, 'server': None, 'dl_mbps': None, 'error': 'No candidates'}

    server = pick_server(pool, candidates)
    if not server:
        set_pool_last_error(pool_id, 'No server picked')
        return {'ok': False, 'server': None, 'dl_mbps': None, 'error': 'No server picked'}

    logger.info(
        'Pool rotation [%d] "%s": picked %s (avg %.1f Mbps, %d candidates)',
        pool_id, pool['name'], server['name'], server.get('avg_dl') or 0.0, len(candidates),
    )

    # ── App config ───────────────────────────────────────────────────────────
    container   = app.config['GLUETUN_CONTAINER']
    compose_dir = app.config['COMPOSE_DIR']
    project     = app.config.get('COMPOSE_PROJECT', '')
    proxy_host  = app.config['GLUETUN_HOST']
    proxy_port  = app.config['GLUETUN_PROXY_PORT']
    proxy_user  = get_setting('proxy_username', '') or None
    proxy_pass  = get_setting('proxy_password', '') or None
    wait_secs   = int(get_setting('connection_wait_seconds', '45'))

    # ── Build WireGuard profile override (if server has a VPN profile) ───────
    wg_profile = None
    if server.get('vpn_profile_id'):
        _p = get_vpn_profile(server['vpn_profile_id'])
        if _p and not _p.get('enabled', False):
            logger.warning(
                'Pool rotation [%d]: profile %d is disabled', pool_id, server['vpn_profile_id']
            )
            set_pool_last_error(pool_id, 'VPN profile disabled')
            return {
                'ok': False,
                'server': server['name'],
                'dl_mbps': None,
                'error': 'VPN profile disabled',
            }
        if _p:
            _prov_key     = _p['provider']
            _prov_def     = WG_PROVIDERS.get(_prov_key, {})
            _compose_prov = _prov_def.get('compose_provider', _prov_key)
            _decrypted: dict[str, str] = {}
            for _vk, _vv in _p['vars'].items():
                try:
                    _decrypted[_vk] = crypto_decrypt(_vv) if is_enc(_vv) else _vv
                except ValueError as exc:
                    logger.error('Pool rotation: cannot decrypt %s for profile %d: %s',
                                 _vk, server['vpn_profile_id'], exc)
                    _decrypted[_vk] = ''
            wg_profile = {
                'compose_provider': _compose_prov,
                'vpn_type':         _p.get('vpn_type', 'wireguard') or 'wireguard',
                'vars':             _decrypted,
            }

    # ── Snapshot current server + IPs + speed before switching ──────────────
    from_server   = get_active_server(container)
    pre_deps      = list_network_dependents_for_recreate(container)

    # Capture the outgoing VPN provider so port-forward rules can follow a
    # provider change (multi-provider pools rotate across WireGuard profiles)
    from .port_forwarding import get_gluetun_provider as _pf_provider
    old_provider = _pf_provider(container)

    # Capture current public IP before the switch
    try:
        from_ipv4, from_ipv6 = get_public_ips(proxy_host, proxy_port, proxy_user, proxy_pass)
    except Exception:
        from_ipv4, from_ipv6 = None, None

    # Look up last known average speed for the outgoing server
    from_mbps: float | None = None
    if from_server:
        with get_db() as db:
            _fr = db.execute(
                '''SELECT ROUND(AVG(download_mbps), 1) AS avg_dl
                   FROM speed_tests
                   WHERE server_name = ? AND success = 1 AND test_method != 'proxy_qc'
                   LIMIT 20''',
                (from_server,),
            ).fetchone()
            from_mbps = _fr['avg_dl'] if _fr else None

    # ── Acquire benchmark mutex (prevents concurrent scheduler benchmark) ──
    set_setting('benchmark_running', '1')
    set_setting('benchmark_current_server', f'pool:{pool_id}')

    # ── Switch Gluetun ────────────────────────────────────────────────────
    pull_gluetun_before_switch(container)
    ok, err = switch_server(
        filter_value=server['name'],
        filter_type=server['filter_type'],
        container_name=container,
        compose_dir=compose_dir,
        compose_project=project,
        wg_profile=wg_profile,
    )

    if not ok:
        logger.error('Pool rotation [%d]: switch to %s failed: %s',
                     pool_id, server['name'], err)
        set_pool_last_error(pool_id, str(err))
        set_setting('benchmark_running', '0'); set_setting('benchmark_stop_requested', '0')
        set_setting('benchmark_current_server', '')
        return {'ok': False, 'server': server['name'], 'dl_mbps': None, 'error': err}

    vpn_up, _elapsed = wait_for_vpn(
        proxy_host, proxy_port,
        timeout=wait_secs,
        proxy_user=proxy_user,
        proxy_password=proxy_pass,
    )
    # Recreate dependents regardless of VPN status — Gluetun's container IS
    # alive (switch_server() just recreated it), so its network namespace is
    # valid even if the VPN tunnel hasn't come up yet.
    restarted, _ = restart_network_dependents(
        container, compose_dir, project, explicit_list=pre_deps,
    )
    post_restarted, _ = restart_configured_post_switch_containers(
        compose_dir, project, already_restarted=set(restarted),
    )
    if post_restarted:
        logger.info(
            'Pool rotation [%d]: configured post-switch containers restarted: %s',
            pool_id, ', '.join(post_restarted),
        )
    if vpn_up:
        logger.info(
            'Pool rotation [%d]: VPN up in %.0fs; recreated %d network dependent(s): %s',
            pool_id, _elapsed, len(restarted), ', '.join(restarted) or 'none',
        )
    else:
        logger.warning(
            'Pool rotation [%d]: VPN not up within %ds; '
            'recreated %d network dependent(s) anyway: %s',
            pool_id, wait_secs, len(restarted), ', '.join(restarted) or 'none',
        )

    # ── Port forwards: re-apply the current provider after every switch ──────
    try:
        from .port_forwarding import apply_current_provider_port_forwards
        pf_result = apply_current_provider_port_forwards(
            container, reason='pool_rotation',
        )
        if not pf_result.get('skipped_reason'):
            logger.info(
                'Pool rotation [%d]: port forwards for provider %s: applied %s/%s, ok=%s',
                pool_id, pf_result.get('provider') or old_provider or '?',
                pf_result.get('applied', 0), pf_result.get('rules', 0), pf_result.get('ok'),
            )
    except Exception as _pf_exc:
        logger.warning('Pool rotation [%d]: port forward apply failed: %s', pool_id, _pf_exc)

    # Record switch — IPs/to_mbps added via UPDATE once the bench completes
    switch_id: int | None = None
    with get_db() as db:
        switch_id = db.execute(
            '''INSERT INTO switches
               (from_server, to_server, reason, success,
                connect_secs, from_mbps, from_ipv4, from_ipv6)
               VALUES (?, ?, ?, 1, ?, ?, ?, ?)''',
            (from_server, server['name'],
             f'pool_rotation:{pool["name"]}:{"manual" if manual else "auto"}',
             _elapsed if vpn_up else None,
             from_mbps, from_ipv4, from_ipv6),
        ).lastrowid

    # ── Optional quick bench ─────────────────────────────────────────────
    dl_mbps: float | None  = None
    to_ipv4: str | None    = None
    to_ipv6: str | None    = None

    if pool['quick_bench']:
        if vpn_up:
            try:
                from .speedtest import test_download as _tdl
                dl_duration = float(get_setting('speedtest_duration', '8'))
                dl_samples  = int(get_setting('speedtest_samples', '3'))
                dl_streams  = int(get_setting('speedtest_streams', '4'))
                dl_mbps, _ = _tdl(
                    proxy_host, proxy_port,
                    duration=dl_duration, samples=dl_samples, warmup=2.0, streams=dl_streams,
                    proxy_user=proxy_user, proxy_password=proxy_pass,
                )
                to_ipv4, to_ipv6 = get_public_ips(proxy_host, proxy_port, proxy_user, proxy_pass)
                # Store result so it appears in history
                with get_db() as db:
                    db.execute(
                        '''INSERT INTO speed_tests
                           (server_name, download_mbps, public_ip, public_ipv6,
                            success, test_method, test_trigger)
                           VALUES (?, ?, ?, ?, 1, 'proxy_qc', 'pool_rotation')''',
                        (server['name'], dl_mbps, to_ipv4, to_ipv6),
                    )
                logger.info(
                    'Pool rotation [%d]: quick bench %s → %.1f Mbps',
                    pool_id, server['name'], dl_mbps,
                )
            except Exception as exc:
                logger.warning('Pool rotation [%d]: quick bench failed: %s', pool_id, exc)
                to_ipv4, to_ipv6 = get_public_ips(proxy_host, proxy_port, proxy_user, proxy_pass)
        else:
            logger.warning('Pool rotation [%d]: VPN not up within %ds', pool_id, wait_secs)
            to_ipv4, to_ipv6 = get_public_ips(proxy_host, proxy_port, proxy_user, proxy_pass)
    else:
        # Get IPs for notification even without quick bench
        try:
            to_ipv4, to_ipv6 = get_public_ips(proxy_host, proxy_port, proxy_user, proxy_pass)
        except Exception:
            pass

    # ── Finalize switch record with destination IPs and speed ───────────────
    if switch_id:
        with get_db() as db:
            db.execute(
                'UPDATE switches SET to_ipv4 = ?, to_ipv6 = ?, to_mbps = ? WHERE id = ?',
                (to_ipv4, to_ipv6, dl_mbps, switch_id),
            )

    # ── Update pool state ────────────────────────────────────────────────
    now   = datetime.utcnow()
    now_s = now.strftime('%Y-%m-%d %H:%M:%S')
    next_s: str | None = None
    if pool['auto_rotate'] and pool['interval_hours']:
        next_s = (now + timedelta(hours=float(pool['interval_hours']))).strftime('%Y-%m-%d %H:%M:%S')
    new_rr_idx = _next_rr_idx(pool, candidates, server['name'])
    set_pool_rotation_state(
        pool_id, now_s, next_s, new_rr_idx,
        last_server=server['name'], last_error=None, last_dl_mbps=dl_mbps,
    )

    # ── Notification ──────────────────────────────────────────────────────
    if pool['notify']:
        _send_pool_notification(pool, server['name'], from_server, dl_mbps, to_ipv4, to_ipv6, manual)

    set_setting('benchmark_running', '0'); set_setting('benchmark_stop_requested', '0')
    set_setting('benchmark_current_server', '')
    return {'ok': True, 'server': server['name'], 'dl_mbps': dl_mbps, 'error': None}


def _send_pool_notification(
    pool: dict,
    to_server: str,
    from_server: str | None,
    dl_mbps: float | None,
    to_ipv4: str | None,
    to_ipv6: str | None,
    manual: bool,
) -> None:
    from .database import get_setting
    from .notify import send_pool_rotation_notification

    discord_url   = get_setting('discord_webhook_url') or None
    apprise_urls  = get_setting('apprise_urls') or None
    if not discord_url and not apprise_urls:
        return

    lang          = get_setting('ui_lang', 'fr')
    companion_url = get_setting('companion_url') or None
    mention       = get_setting('notify_mention', '').strip() or None
    mention_level = get_setting('notify_mention_level', 'medium')

    try:
        send_pool_rotation_notification(
            pool_name=pool['name'],
            from_server=from_server,
            to_server=to_server,
            dl_mbps=dl_mbps,
            to_ipv4=to_ipv4,
            to_ipv6=to_ipv6,
            manual=manual,
            discord_url=discord_url,
            apprise_urls=apprise_urls,
            lang=lang,
            companion_url=companion_url,
            mention=mention,
            mention_level=mention_level,
        )
    except Exception as exc:
        logger.warning('Pool rotation: notification failed: %s', exc)
