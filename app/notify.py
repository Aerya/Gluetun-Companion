"""
Notifications — Discord webhook and/or Apprise.

Alert types and their severity levels:
  critical : notif_auto_exclude   — server auto-disabled
  medium   : notif_auto_switch    — automatic VPN switch
             notif_airvpn         — new AirVPN servers detected
  info     : notif_manual_switch  — manual switch (button)
             notif_already_best   — already on best server
             notif_benchmark_end  — benchmark cycle finished
"""

import logging
import re

import requests

from .i18n import get_translations

logger = logging.getLogger(__name__)

_LOGO_URL = 'https://raw.githubusercontent.com/Aerya/Gluetun-Companion/main/assets/logo.png'

# ── Severity ──────────────────────────────────────────────────────────────────

_SEVERITY: dict[str, str] = {
    'failover':           'critical',
    'auto_exclude':       'critical',
    'benchmark_failure':  'critical',
    'auto_switch':        'medium',
    'airvpn':             'medium',
    'pool_rotation':      'medium',
    'manual_switch':      'info',
    'already_best':       'info',
    'benchmark_start':    'info',
    'benchmark_end':      'info',
    'quick_check':        'info',
    'optimal_hour':       'info',
    'catalogue_changes':  'info',
}

_LEVEL_ORDER: dict[str, int] = {'critical': 0, 'medium': 1, 'info': 2}


def _should_mention(alert_type: str, level_setting: str) -> bool:
    """Return True if the mention should be added for this alert type and level setting."""
    alert_sev = _SEVERITY.get(alert_type, 'info')
    threshold_sev = {'critical': 'critical', 'medium': 'medium', 'all': 'info'}.get(
        level_setting, 'critical'
    )
    return _LEVEL_ORDER[alert_sev] <= _LEVEL_ORDER[threshold_sev]


# ── Discord helpers ───────────────────────────────────────────────────────────

def _discord_allowed_mentions(mention: str) -> dict:
    """
    Build a Discord allowed_mentions object from a raw mention string.
    '<@416345506579611668>'  → {'users': ['416345506579611668']}
    '<@&987654321>'          → {'roles': ['987654321']}
    """
    user_ids = re.findall(r'<@!?(\d+)>', mention)
    role_ids = re.findall(r'<@&(\d+)>', mention)
    result: dict = {}
    if user_ids:
        result['users'] = user_ids
    if role_ids:
        result['roles'] = role_ids
    if not result:
        result['parse'] = ['users', 'roles', 'everyone']
    return result


def _strip_filter(label: str | None) -> str:
    """'SERVER_NAMES=Chamukuy' → 'Chamukuy'."""
    if not label:
        return '—'
    return label.split('=', 1)[1] if '=' in label else label


def _discord_base_payload(title: str, color: int, fields: list[dict],
                           t: dict, companion_url: str | None = None) -> dict:
    """Shared Discord embed skeleton."""
    author: dict = {'name': t['notif_footer'], 'icon_url': _LOGO_URL}
    if companion_url:
        author['url'] = companion_url
    return {
        'username':   'Gluetun Companion',
        'avatar_url': _LOGO_URL,
        'embeds': [{
            'author': author,
            'title':  title,
            'color':  color,
            'fields': fields,
        }],
    }


def _post_discord(url: str, payload: dict, mention: str | None,
                  alert_type: str, level_setting: str) -> None:
    """Add mention to payload if applicable, then POST to Discord."""
    if mention and _should_mention(alert_type, level_setting):
        payload['content'] = mention
        payload['allowed_mentions'] = _discord_allowed_mentions(mention)
    resp = requests.post(url.strip(), json=payload, timeout=10)
    resp.raise_for_status()


def _notify_apprise(urls: str, title: str, body: str) -> None:
    """Fire Apprise notification across all configured URLs."""
    try:
        import apprise as _apprise
    except ImportError:
        logger.warning('Apprise not installed — add "apprise" to requirements.txt')
        return
    ap = _apprise.Apprise()
    for u in urls.splitlines():
        u = u.strip()
        if u:
            ap.add(u)
    ok = ap.notify(title=title, body=body)
    if not ok:
        logger.warning('Apprise notify() returned False for title=%r', title)


# ── Switch payload helpers (shared by auto + manual switch) ──────────────────

def _switch_discord_payload(
    from_server, to_server, from_mbps, to_mbps,
    connect_secs, to_ipv4, to_ipv6, t,
    companion_url=None, updated_images=None, qc_info=None,
    from_ipv4=None, from_ipv6=None,
) -> dict:
    gain  = (to_mbps - from_mbps) if (from_mbps and to_mbps) else None
    color = 0x3fb950 if (gain is None or gain >= 0) else 0xf85149
    if gain is None:
        color = 0x58a6ff

    from_label = _strip_filter(from_server)
    to_label   = _strip_filter(to_server)

    from_value = f'`{from_label}`' if from_server else '—'
    if from_ipv4:
        from_value += f'\n`{from_ipv4}`'
        if from_ipv6:
            from_value += f'\n`{from_ipv6}`'

    to_value = f'`{to_label}`'
    if to_ipv4:
        to_value += f'\n`{to_ipv4}`'
        if to_ipv6:
            to_value += f'\n`{to_ipv6}`'

    fields = [
        {'name': t['notif_field_from'], 'value': from_value, 'inline': True},
        {'name': t['notif_field_to'],   'value': to_value,   'inline': True},
        {'name': '​', 'value': '​',      'inline': True},
    ]
    if from_mbps is not None:
        fields.append({'name': t['notif_field_speed_before'], 'value': f'{from_mbps:.1f} Mbps', 'inline': True})
    if to_mbps is not None:
        fields.append({'name': t['notif_field_speed_after'], 'value': f'{to_mbps:.1f} Mbps', 'inline': True})
    if gain is not None:
        sign = '+' if gain >= 0 else ''
        fields.append({'name': t['notif_field_gain'], 'value': f'{sign}{gain:.1f} Mbps', 'inline': True})
    if connect_secs is not None:
        fields.append({'name': t['notif_field_connect'], 'value': f'{connect_secs:.0f} s', 'inline': True})

    if qc_info and qc_info.get('current_dl') is not None and qc_info.get('last_dl'):
        degraded = qc_info['current_dl'] < qc_info['last_dl']
        sign = '−' if degraded else '+'
        qc_server = _strip_filter(qc_info.get('server', ''))
        fields.append({
            'name':   t.get('notif_qc_triggered_field', 'Dérive détectée'),
            'value':  (
                f'`{qc_server}` {sign}{qc_info["diff_pct"]:.0f}% '
                f'({qc_info["current_dl"]:.0f} → {qc_info["last_dl"]:.0f} Mbps)'
            ),
            'inline': False,
        })

    if updated_images:
        fields.append({
            'name':   t.get('notif_updated_images', 'Images mises à jour'),
            'value':  '\n'.join(f'`{img}`' for img in updated_images),
            'inline': False,
        })

    return _discord_base_payload(t['notif_title'], color, fields, t, companion_url)


def _switch_text_body(
    from_server, to_server, from_mbps, to_mbps,
    connect_secs, to_ipv4, to_ipv6, t,
    companion_url=None, updated_images=None, qc_info=None,
    from_ipv4=None, from_ipv6=None,
) -> str:
    gain     = (to_mbps - from_mbps) if (from_mbps and to_mbps) else None
    from_part = _strip_filter(from_server) or '?'
    if from_ipv4:
        from_part += f' ({from_ipv4})'
    to_part = _strip_filter(to_server)
    if to_ipv4:
        to_part += f' ({to_ipv4})'
        if to_ipv6:
            to_part += f' / {to_ipv6}'

    lines = [f'🔄 {from_part} → {to_part}']
    if from_mbps is not None and to_mbps is not None:
        sign = '+' if gain >= 0 else ''
        lines.append(f'{t["notif_text_speed"]} : {from_mbps:.1f} → {to_mbps:.1f} Mbps ({sign}{gain:.1f})')
    if connect_secs is not None:
        lines.append(f'{t["notif_text_connect"]} : {connect_secs:.0f} s')
    if qc_info and qc_info.get('current_dl') is not None and qc_info.get('last_dl'):
        sign = '−' if qc_info['current_dl'] < qc_info['last_dl'] else '+'
        qc_server = _strip_filter(qc_info.get('server', ''))
        lines.append(
            f'{t.get("notif_qc_triggered_field", "Dérive")} : '
            f'{qc_server} {sign}{qc_info["diff_pct"]:.0f}% '
            f'({qc_info["current_dl"]:.0f}→{qc_info["last_dl"]:.0f} Mbps)'
        )
    if updated_images:
        lines.append(
            f'{t.get("notif_updated_images", "Images mises à jour")} : '
            + ', '.join(updated_images)
        )
    if companion_url:
        lines.append(companion_url)
    return '\n'.join(lines)


# ── Public notification functions ─────────────────────────────────────────────

def send_switch_notification(
    from_server: str | None,
    to_server: str,
    from_mbps: float | None,
    to_mbps: float | None,
    connect_secs: float | None,
    to_ipv4: str | None,
    to_ipv6: str | None,
    reason: str,
    discord_url: str | None = None,
    apprise_urls: str | None = None,
    lang: str = 'fr',
    companion_url: str | None = None,
    updated_images: list[str] | None = None,
    qc_info: dict | None = None,
    from_ipv4: str | None = None,
    from_ipv6: str | None = None,
    mention: str | None = None,
    mention_level: str = 'critical',
    alert_type: str = 'auto_switch',
):
    if not discord_url and not apprise_urls:
        return
    t = dict(get_translations(lang))
    if reason == 'emergency_failover':
        t['notif_title'] = t.get('notif_failover_title', 'VPN outage — emergency failover')
        t['notif_apprise_title'] = t.get(
            'notif_failover_apprise_title', 'VPN outage — Gluetun Companion'
        )

    if discord_url:
        try:
            payload = _switch_discord_payload(
                from_server, to_server, from_mbps, to_mbps,
                connect_secs, to_ipv4, to_ipv6, t,
                companion_url=companion_url, updated_images=updated_images,
                qc_info=qc_info, from_ipv4=from_ipv4, from_ipv6=from_ipv6,
            )
            _post_discord(discord_url, payload, mention, alert_type, mention_level)
            logger.info('Discord switch notification sent (%s)', alert_type)
        except Exception as exc:
            logger.warning('Discord switch notification failed: %s', exc)

    if apprise_urls:
        try:
            body = _switch_text_body(
                from_server, to_server, from_mbps, to_mbps,
                connect_secs, to_ipv4, to_ipv6, t,
                companion_url=companion_url, updated_images=updated_images,
                qc_info=qc_info, from_ipv4=from_ipv4, from_ipv6=from_ipv6,
            )
            _notify_apprise(apprise_urls, t['notif_apprise_title'], body)
            logger.info('Apprise switch notification sent (%s)', alert_type)
        except Exception as exc:
            logger.warning('Apprise switch notification failed: %s', exc)


def send_failover_failure_notification(
    server: str | None,
    error: str,
    discord_url: str | None = None,
    apprise_urls: str | None = None,
    lang: str = 'fr',
    companion_url: str | None = None,
    mention: str | None = None,
    mention_level: str = 'critical',
) -> None:
    """Notify that the VPN is down and emergency failover could not recover it."""
    if not discord_url and not apprise_urls:
        return
    t = get_translations(lang)
    title = t.get('notif_failover_failed_title', 'VPN outage — failover failed')
    body = t.get('notif_failover_failed_body', 'No usable replacement server: {error}').replace(
        '{error}', error
    )
    if discord_url:
        try:
            payload = _discord_base_payload(title, 0xf85149, [
                {'name': t.get('notif_field_from', 'Current server'),
                 'value': f'`{_strip_filter(server)}`', 'inline': True},
                {'name': t.get('notif_failover_error', 'Error'),
                 'value': body, 'inline': False},
            ], t, companion_url)
            _post_discord(discord_url, payload, mention, 'failover', mention_level)
        except Exception as exc:
            logger.warning('Discord failover failure notification failed: %s', exc)
    if apprise_urls:
        try:
            _notify_apprise(
                apprise_urls,
                t.get('notif_failover_apprise_title', title),
                f'{_strip_filter(server)}\n{body}',
            )
        except Exception as exc:
            logger.warning('Apprise failover failure notification failed: %s', exc)


def send_already_best_notification(
    server: str,
    speed_mbps: float | None,
    ipv4: str | None,
    ipv6: str | None,
    discord_url: str | None = None,
    apprise_urls: str | None = None,
    lang: str = 'fr',
    companion_url: str | None = None,
    mention: str | None = None,
    mention_level: str = 'critical',
):
    if not discord_url and not apprise_urls:
        return
    t = get_translations(lang)
    title = t.get('notif_already_best_title', 'Already on best server')
    server_label = _strip_filter(server)

    if discord_url:
        try:
            fields = [{'name': t.get('notif_already_best_field', 'Active server'),
                       'value': f'`{server_label}`', 'inline': True}]
            if speed_mbps is not None:
                fields.append({'name': t.get('notif_field_speed', 'Speed'),
                               'value': f'{speed_mbps:.1f} Mbps', 'inline': True})
            if ipv4:
                fields.append({'name': 'IPv4', 'value': ipv4, 'inline': True})
            if ipv6:
                fields.append({'name': 'IPv6', 'value': ipv6, 'inline': True})
            payload = _discord_base_payload(title, 0x58a6ff, fields, t, companion_url)
            _post_discord(discord_url, payload, mention, 'already_best', mention_level)
            logger.info('Discord already-best notification sent')
        except Exception as exc:
            logger.warning('Discord already-best notification failed: %s', exc)

    if apprise_urls:
        try:
            lines = [server_label]
            if speed_mbps is not None:
                lines.append(f'{t.get("notif_text_speed", "Speed")} : {speed_mbps:.1f} Mbps')
            if ipv4:
                ip = ipv4 + (f' / {ipv6}' if ipv6 else '')
                lines.append(f'{t.get("notif_text_ip", "IP")} : {ip}')
            if companion_url:
                lines.append(companion_url)
            _notify_apprise(
                apprise_urls,
                t.get('notif_already_best_apprise_title', 'Already optimal — Gluetun Companion'),
                '\n'.join(lines),
            )
            logger.info('Apprise already-best notification sent')
        except Exception as exc:
            logger.warning('Apprise already-best notification failed: %s', exc)


def send_auto_exclude_notification(
    server: str,
    failures: int,
    discord_url: str | None = None,
    apprise_urls: str | None = None,
    lang: str = 'fr',
    companion_url: str | None = None,
    mention: str | None = None,
    mention_level: str = 'critical',
):
    """Notify when a server is automatically disabled after too many consecutive failures."""
    if not discord_url and not apprise_urls:
        return
    t = get_translations(lang)
    server_label = _strip_filter(server)
    title  = t.get('notif_auto_exclude_title', '🚫 Serveur désactivé automatiquement')
    reason = t.get('notif_auto_exclude_reason', '{n} échecs consécutifs').replace('{n}', str(failures))

    if discord_url:
        try:
            fields = [
                {'name': t.get('notif_auto_exclude_server', 'Serveur'),
                 'value': f'`{server_label}`', 'inline': True},
                {'name': t.get('notif_auto_exclude_failures', 'Échecs'),
                 'value': str(failures), 'inline': True},
            ]
            payload = _discord_base_payload(title, 0xf85149, fields, t, companion_url)
            _post_discord(discord_url, payload, mention, 'auto_exclude', mention_level)
            logger.info('Discord auto-exclude notification sent for %s', server)
        except Exception as exc:
            logger.warning('Discord auto-exclude notification failed: %s', exc)

    if apprise_urls:
        try:
            body = f'🚫 {server_label}\n{reason}'
            if companion_url:
                body += f'\n{companion_url}'
            _notify_apprise(
                apprise_urls,
                t.get('notif_auto_exclude_apprise_title', 'Serveur désactivé — Gluetun Companion'),
                body,
            )
            logger.info('Apprise auto-exclude notification sent for %s', server)
        except Exception as exc:
            logger.warning('Apprise auto-exclude notification failed: %s', exc)


def send_benchmark_failure_notification(
    n_servers: int,
    duration_secs: float,
    discord_url: str | None = None,
    apprise_urls: str | None = None,
    lang: str = 'fr',
    companion_url: str | None = None,
    mention: str | None = None,
    mention_level: str = 'critical',
):
    """Notify when a full benchmark cycle completes with 0 successful results."""
    if not discord_url and not apprise_urls:
        return
    t = get_translations(lang)
    title = t.get('notif_benchmark_failure_title', '⚠️ Benchmark : aucun résultat')
    dur_min = int(duration_secs // 60)
    dur_sec = int(duration_secs % 60)
    dur_str = f'{dur_min}m {dur_sec:02d}s' if dur_min else f'{dur_sec}s'

    if discord_url:
        try:
            fields = [
                {'name': t.get('notif_benchmark_failure_servers', 'Serveurs testés'),
                 'value': str(n_servers), 'inline': True},
                {'name': t.get('notif_benchmark_end_duration', 'Durée'),
                 'value': dur_str, 'inline': True},
                {'name': t.get('notif_benchmark_failure_cause', 'Cause probable'),
                 'value': t.get('notif_benchmark_failure_hint',
                                'Gluetun injoignable ou tous les serveurs en échec'),
                 'inline': False},
            ]
            payload = _discord_base_payload(title, 0xf85149, fields, t, companion_url)
            _post_discord(discord_url, payload, mention, 'benchmark_failure', mention_level)
            logger.info('Discord benchmark-failure notification sent')
        except Exception as exc:
            logger.warning('Discord benchmark-failure notification failed: %s', exc)

    if apprise_urls:
        try:
            lines = [
                t.get('notif_benchmark_failure_hint',
                      'Gluetun injoignable ou tous les serveurs en échec'),
                f'{n_servers} serveurs · {dur_str}',
            ]
            if companion_url:
                lines.append(companion_url)
            _notify_apprise(
                apprise_urls,
                t.get('notif_benchmark_failure_apprise_title',
                      'Benchmark échoué — Gluetun Companion'),
                '\n'.join(lines),
            )
            logger.info('Apprise benchmark-failure notification sent')
        except Exception as exc:
            logger.warning('Apprise benchmark-failure notification failed: %s', exc)


def send_benchmark_start_notification(
    sidecar_mode: bool,
    paused_containers: list[str],
    discord_url: str | None = None,
    apprise_urls: str | None = None,
    lang: str = 'fr',
    companion_url: str | None = None,
    mention: str | None = None,
    mention_level: str = 'critical',
):
    """Notify just before a full benchmark can interrupt VPN-dependent services."""
    if not discord_url and not apprise_urls:
        return
    t = get_translations(lang)
    mode = t.get('notif_benchmark_start_sidecar', 'Sidecar') if sidecar_mode else t.get(
        'notif_benchmark_start_proxy', 'HTTP proxy'
    )
    paused = ', '.join(paused_containers) if paused_containers else t.get(
        'notif_benchmark_start_none', 'None'
    )

    if discord_url:
        try:
            fields = [
                {'name': t.get('notif_benchmark_start_mode', 'Mode'), 'value': mode, 'inline': True},
                {'name': t.get('notif_benchmark_start_paused', 'Paused containers'),
                 'value': paused, 'inline': False},
            ]
            payload = _discord_base_payload(
                t.get('notif_benchmark_start_title', 'Benchmark started'),
                0x58a6ff,
                fields,
                t,
                companion_url,
            )
            _post_discord(discord_url, payload, mention, 'benchmark_start', mention_level)
            logger.info('Discord benchmark-start notification sent')
        except Exception as exc:
            logger.warning('Discord benchmark-start notification failed: %s', exc)

    if apprise_urls:
        try:
            lines = [
                f"{t.get('notif_benchmark_start_mode', 'Mode')}: {mode}",
                f"{t.get('notif_benchmark_start_paused', 'Paused containers')}: {paused}",
                t.get('notif_benchmark_start_hint', 'Temporary VPN interruptions may occur during the cycle.'),
            ]
            if companion_url:
                lines.append(companion_url)
            _notify_apprise(
                apprise_urls,
                t.get('notif_benchmark_start_apprise_title', 'Benchmark started — Gluetun Companion'),
                '\n'.join(lines),
            )
            logger.info('Apprise benchmark-start notification sent')
        except Exception as exc:
            logger.warning('Apprise benchmark-start notification failed: %s', exc)


def send_benchmark_end_notification(
    n_tested: int,
    best_server: str | None,
    best_dl: float | None,
    duration_secs: float,
    discord_url: str | None = None,
    apprise_urls: str | None = None,
    lang: str = 'fr',
    companion_url: str | None = None,
    mention: str | None = None,
    mention_level: str = 'critical',
):
    """Notify when a full benchmark cycle completes."""
    if not discord_url and not apprise_urls:
        return
    t = get_translations(lang)
    title = t.get('notif_benchmark_end_title', '✅ Benchmark terminé')
    best_label = _strip_filter(best_server) if best_server else '—'

    if discord_url:
        try:
            fields = [
                {'name': t.get('notif_benchmark_end_tested', 'Serveurs testés'),
                 'value': str(n_tested), 'inline': True},
                {'name': t.get('notif_benchmark_end_best', 'Meilleur serveur'),
                 'value': f'`{best_label}`', 'inline': True},
            ]
            if best_dl is not None:
                fields.append({'name': t.get('notif_field_speed', 'Vitesse'),
                               'value': f'{best_dl:.1f} Mbps', 'inline': True})
            dur_min = int(duration_secs // 60)
            dur_sec = int(duration_secs % 60)
            dur_str = f'{dur_min}m {dur_sec:02d}s' if dur_min else f'{dur_sec}s'
            fields.append({'name': t.get('notif_benchmark_end_duration', 'Durée'),
                           'value': dur_str, 'inline': True})
            payload = _discord_base_payload(title, 0x3fb950, fields, t, companion_url)
            _post_discord(discord_url, payload, mention, 'benchmark_end', mention_level)
            logger.info('Discord benchmark-end notification sent')
        except Exception as exc:
            logger.warning('Discord benchmark-end notification failed: %s', exc)

    if apprise_urls:
        try:
            lines = [f'{n_tested} serveurs testés']
            if best_server:
                speed_str = f' ({best_dl:.1f} Mbps)' if best_dl else ''
                lines.append(f'{t.get("notif_benchmark_end_best", "Meilleur")} : {best_label}{speed_str}')
            if companion_url:
                lines.append(companion_url)
            _notify_apprise(
                apprise_urls,
                t.get('notif_benchmark_end_apprise_title', 'Benchmark terminé — Gluetun Companion'),
                '\n'.join(lines),
            )
            logger.info('Apprise benchmark-end notification sent')
        except Exception as exc:
            logger.warning('Apprise benchmark-end notification failed: %s', exc)


def send_new_airvpn_servers_notification(
    new_servers: list[dict],
    discord_url: str | None = None,
    apprise_urls: str | None = None,
    lang: str = 'fr',
    mention: str | None = None,
    mention_level: str = 'critical',
    companion_url: str | None = None,
):
    """Notify when new AirVPN servers are available in the user's countries."""
    if not discord_url and not apprise_urls:
        return
    if not new_servers:
        return

    t = get_translations(lang)
    n = len(new_servers)
    title = t.get('airvpn_notif_title', '🆕 Nouveaux serveurs AirVPN')

    countries_seen: dict[str, list[str]] = {}
    for s in new_servers:
        countries_seen.setdefault(s['country'], []).append(s['name'])

    if discord_url:
        try:
            fields = [
                {'name': country, 'value': '\n'.join(f'`{nm}`' for nm in names), 'inline': True}
                for country, names in countries_seen.items()
            ]
            payload = _discord_base_payload(title, 0x3fb950, fields, t, companion_url)
            _post_discord(discord_url, payload, mention, 'airvpn', mention_level)
            logger.info('Discord new-AirVPN-servers notification sent (%d server(s))', n)
        except Exception as exc:
            logger.warning('Discord new-AirVPN-servers notification failed: %s', exc)

    if apprise_urls:
        try:
            lines = []
            for country, names in countries_seen.items():
                lines.append(f'{country}: {", ".join(names)}')
            if companion_url:
                lines.append(companion_url)
            _notify_apprise(apprise_urls, title, '\n'.join(lines))
            logger.info('Apprise new-AirVPN-servers notification sent (%d server(s))', n)
        except Exception as exc:
            logger.warning('Apprise new-AirVPN-servers notification failed: %s', exc)


def send_quick_check_notification(
    server: str,
    speed_mbps: float,
    last_mbps: float | None,
    ipv4: str | None,
    ipv6: str | None,
    discord_url: str | None = None,
    apprise_urls: str | None = None,
    lang: str = 'fr',
    companion_url: str | None = None,
    mention: str | None = None,
    mention_level: str = 'critical',
):
    """Notify after a manual quick check (proxy test of current server)."""
    if not discord_url and not apprise_urls:
        return
    t = get_translations(lang)
    server_label = _strip_filter(server)
    title = t.get('notif_quick_check_title', 'Quick check').replace('{server}', server_label)

    if discord_url:
        try:
            fields = [
                {'name': t.get('notif_quick_check_server', 'Serveur'),
                 'value': f'`{server_label}`', 'inline': True},
                {'name': t.get('notif_field_speed', 'Vitesse'),
                 'value': f'{speed_mbps:.1f} Mbps', 'inline': True},
            ]
            if last_mbps is not None:
                diff = speed_mbps - last_mbps
                sign = '+' if diff >= 0 else ''
                fields.append({
                    'name':   t.get('notif_quick_check_baseline', 'Baseline'),
                    'value':  f'{last_mbps:.1f} Mbps ({sign}{diff:.1f})',
                    'inline': True,
                })
            if ipv4:
                ip_val = ipv4 + (f'\n`{ipv6}`' if ipv6 else '')
                fields.append({'name': 'IP', 'value': f'`{ip_val}`', 'inline': True})
            payload = _discord_base_payload(title, 0x58a6ff, fields, t, companion_url)
            _post_discord(discord_url, payload, mention, 'quick_check', mention_level)
            logger.info('Discord quick-check notification sent for %s (%.1f Mbps)', server_label, speed_mbps)
        except Exception as exc:
            logger.warning('Discord quick-check notification failed: %s', exc)

    if apprise_urls:
        try:
            lines = [server_label, f'{t.get("notif_text_speed", "Vitesse")} : {speed_mbps:.1f} Mbps']
            if last_mbps is not None:
                diff = speed_mbps - last_mbps
                sign = '+' if diff >= 0 else ''
                lines.append(f'{t.get("notif_quick_check_baseline", "Baseline")} : {last_mbps:.1f} Mbps ({sign}{diff:.1f})')
            if ipv4:
                lines.append(f'IP : {ipv4}' + (f' / {ipv6}' if ipv6 else ''))
            if companion_url:
                lines.append(companion_url)
            _notify_apprise(
                apprise_urls,
                t.get('notif_quick_check_apprise_title', 'Quick check — Gluetun Companion'),
                '\n'.join(lines),
            )
            logger.info('Apprise quick-check notification sent for %s', server_label)
        except Exception as exc:
            logger.warning('Apprise quick-check notification failed: %s', exc)


def send_optimal_hour_notification(
    old_hour: int | None,
    new_hour: int,
    discord_url: str | None = None,
    apprise_urls: str | None = None,
    lang: str = 'fr',
    companion_url: str | None = None,
    mention: str | None = None,
    mention_level: str = 'critical',
):
    """Notify when the global optimal benchmark hour changes."""
    if not discord_url and not apprise_urls:
        return
    t = get_translations(lang)
    title = t.get('notif_optimal_hour_title', '🕐 Fenêtre optimale de benchmark')
    old_str = f'{old_hour:02d}:00' if old_hour is not None else '—'
    new_str = f'{new_hour:02d}:00'

    if discord_url:
        try:
            fields = []
            if old_hour is not None:
                fields.append({
                    'name':   t.get('notif_optimal_hour_old', 'Heure précédente'),
                    'value':  old_str,
                    'inline': True,
                })
            fields.append({
                'name':   t.get('notif_optimal_hour_new', 'Nouvelle heure optimale'),
                'value':  new_str,
                'inline': True,
            })
            payload = _discord_base_payload(title, 0x58a6ff, fields, t, companion_url)
            _post_discord(discord_url, payload, mention, 'optimal_hour', mention_level)
            logger.info(
                'Discord optimal-hour notification sent (old=%s → new=%dh)',
                old_str, new_hour,
            )
        except Exception as exc:
            logger.warning('Discord optimal-hour notification failed: %s', exc)

    if apprise_urls:
        try:
            body = t.get(
                'notif_optimal_hour_body',
                'Meilleure heure : {old} → {new}',
            ).replace('{old}', old_str).replace('{new}', new_str)
            if companion_url:
                body += f'\n{companion_url}'
            _notify_apprise(
                apprise_urls,
                t.get('notif_optimal_hour_apprise_title',
                      'Fenêtre optimale — Gluetun Companion'),
                body,
            )
            logger.info('Apprise optimal-hour notification sent')
        except Exception as exc:
            logger.warning('Apprise optimal-hour notification failed: %s', exc)


def send_catalogue_changes_notification(
    diff: dict,
    auto_added: list[str],
    discord_url: str | None = None,
    apprise_urls: str | None = None,
    lang: str = 'fr',
    companion_url: str | None = None,
    mention: str | None = None,
    mention_level: str = 'critical',
):
    """
    Notify when new servers appear in (or are removed from) the Gluetun catalogue.

    diff       — {provider: {added: [names], removed: [names]}}
    auto_added — server names that were automatically added to the user's list
    """
    if not discord_url and not apprise_urls:
        return
    if not diff and not auto_added:
        return

    t = get_translations(lang)
    title = t.get('notif_catalogue_title', '📋 Catalogue Gluetun mis à jour')

    # Build per-provider summary
    total_added   = sum(len(v.get('added', []))   for v in diff.values())
    total_removed = sum(len(v.get('removed', [])) for v in diff.values())

    if discord_url:
        try:
            fields = []
            if total_added:
                added_lines = []
                for p, changes in diff.items():
                    if changes.get('added'):
                        added_lines.append(f'**{p}** +{len(changes["added"])}')
                fields.append({
                    'name':   t.get('notif_catalogue_added', 'Nouveaux serveurs'),
                    'value':  '\n'.join(added_lines) or str(total_added),
                    'inline': True,
                })
            if total_removed:
                removed_lines = []
                for p, changes in diff.items():
                    if changes.get('removed'):
                        removed_lines.append(f'**{p}** -{len(changes["removed"])}')
                fields.append({
                    'name':   t.get('notif_catalogue_removed', 'Serveurs supprimés'),
                    'value':  '\n'.join(removed_lines) or str(total_removed),
                    'inline': True,
                })
            if auto_added:
                fields.append({
                    'name':   t.get('notif_catalogue_auto_added', 'Ajoutés automatiquement'),
                    'value':  ', '.join(auto_added[:10]) + (f' … (+{len(auto_added)-10})' if len(auto_added) > 10 else ''),
                    'inline': False,
                })
            payload = _discord_base_payload(title, 0x17a2b8, fields, t, companion_url)
            _post_discord(discord_url, payload, mention, 'catalogue_changes', mention_level)
            logger.info(
                'Discord catalogue notification sent (+%d/-%d auto-add:%d)',
                total_added, total_removed, len(auto_added),
            )
        except Exception as exc:
            logger.warning('Discord catalogue notification failed: %s', exc)

    if apprise_urls:
        try:
            lines = []
            if total_added:
                per = ', '.join(
                    f'{p} +{len(v["added"])}'
                    for p, v in diff.items() if v.get('added')
                )
                lines.append(f'{t.get("notif_catalogue_added", "Nouveaux")}: {per}')
            if total_removed:
                per = ', '.join(
                    f'{p} -{len(v["removed"])}'
                    for p, v in diff.items() if v.get('removed')
                )
                lines.append(f'{t.get("notif_catalogue_removed", "Supprimés")}: {per}')
            if auto_added:
                lines.append(
                    f'{t.get("notif_catalogue_auto_added", "Auto-ajoutés")}: '
                    + ', '.join(auto_added[:10])
                )
            if companion_url:
                lines.append(companion_url)
            _notify_apprise(
                apprise_urls,
                t.get('notif_catalogue_apprise_title', 'Catalogue Gluetun — Gluetun Companion'),
                '\n'.join(lines),
            )
            logger.info('Apprise catalogue notification sent')
        except Exception as exc:
            logger.warning('Apprise catalogue notification failed: %s', exc)


def send_test_notification(
    target: str,
    discord_url: str | None = None,
    apprise_urls: str | None = None,
    lang: str = 'fr',
    mention: str | None = None,
) -> tuple[bool, str]:
    """Send a test notification. target: 'discord', 'apprise', or 'all'."""
    t = get_translations(lang)

    if target in ('discord', 'all') and discord_url:
        try:
            payload = {
                'username':   'Gluetun Companion',
                'avatar_url': _LOGO_URL,
                'embeds': [{
                    'title':       f'✅ {t["notif_footer"]} — test',
                    'description': t.get('notif_test_body', 'Notification test — OK'),
                    'color':       0x3fb950,
                    'footer':      {'text': t['notif_footer']},
                }],
            }
            if mention:
                payload['content'] = mention
                payload['allowed_mentions'] = _discord_allowed_mentions(mention)
            resp = requests.post(discord_url.strip(), json=payload, timeout=10)
            resp.raise_for_status()
            logger.info('Discord test notification sent')
        except Exception as exc:
            logger.warning('Discord test notification failed: %s', exc)
            return False, f'Discord : {exc}'

    if target in ('apprise', 'all') and apprise_urls:
        try:
            body = t.get('notif_test_body', 'Notification test — OK')
            _notify_apprise(apprise_urls, f'{t["notif_footer"]} — test', body)
            logger.info('Apprise test notification sent')
        except Exception as exc:
            logger.warning('Apprise test notification failed: %s', exc)
            return False, f'Apprise : {exc}'

    return True, 'OK'


# ── Pool rotation notifications ───────────────────────────────────────────────

def send_pool_rotation_notification(
    pool_name: str,
    from_server: str | None,
    to_server: str,
    dl_mbps: float | None,
    to_ipv4: str | None,
    to_ipv6: str | None,
    manual: bool = False,
    discord_url: str | None = None,
    apprise_urls: str | None = None,
    lang: str = 'fr',
    companion_url: str | None = None,
    mention: str | None = None,
    mention_level: str = 'medium',
):
    """Notify after a pool rotation switch."""
    if not discord_url and not apprise_urls:
        return
    t = get_translations(lang)

    from_label = _strip_filter(from_server) if from_server else '—'
    to_label   = _strip_filter(to_server)
    trigger_label = t.get('notif_pool_manual', 'Manuel') if manual else t.get('notif_pool_auto', 'Automatique')

    title = t.get('notif_pool_title', '🔁 Pool rotation') + f' — {pool_name}'

    if discord_url:
        try:
            fields = [
                {'name': t.get('notif_pool_pool', 'Pool'), 'value': f'`{pool_name}`', 'inline': True},
                {'name': t.get('notif_pool_trigger', 'Déclenchement'), 'value': trigger_label, 'inline': True},
                {'name': '​', 'value': '​', 'inline': True},
                {'name': t.get('notif_field_from', 'Avant'), 'value': f'`{from_label}`', 'inline': True},
                {'name': t.get('notif_field_to',   'Après'), 'value': f'`{to_label}`', 'inline': True},
                {'name': '​', 'value': '​', 'inline': True},
            ]
            if dl_mbps is not None:
                fields.append({
                    'name': t.get('notif_pool_speed', 'Débit mesuré après bascule'),
                    'value': f'{dl_mbps:.1f} Mbps', 'inline': True,
                })
            if to_ipv4:
                ip_val = to_ipv4 + (f' / {to_ipv6}' if to_ipv6 else '')
                fields.append({'name': 'IP', 'value': f'`{ip_val}`', 'inline': True})
            payload = _discord_base_payload(title, 0x58a6ff, fields, t, companion_url)
            _post_discord(discord_url, payload, mention, 'pool_rotation', mention_level)
            logger.info('Discord pool rotation notification sent (pool=%s)', pool_name)
        except Exception as exc:
            logger.warning('Discord pool rotation notification failed: %s', exc)

    if apprise_urls:
        try:
            lines = [
                f'🔁 {from_label} → {to_label}',
                f'{t.get("notif_pool_pool", "Pool")} : {pool_name} ({trigger_label})',
            ]
            if dl_mbps is not None:
                lines.append(f'{t.get("notif_pool_speed", "Débit")} : {dl_mbps:.1f} Mbps')
            if to_ipv4:
                ip_str = to_ipv4 + (f' / {to_ipv6}' if to_ipv6 else '')
                lines.append(f'IP : {ip_str}')
            if companion_url:
                lines.append(companion_url)
            _notify_apprise(apprise_urls, title, '\n'.join(lines))
            logger.info('Apprise pool rotation notification sent (pool=%s)', pool_name)
        except Exception as exc:
            logger.warning('Apprise pool rotation notification failed: %s', exc)
