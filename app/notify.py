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
    'auto_exclude':    'critical',
    'auto_switch':     'medium',
    'airvpn':          'medium',
    'manual_switch':   'info',
    'already_best':    'info',
    'benchmark_end':   'info',
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
    t = get_translations(lang)

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
