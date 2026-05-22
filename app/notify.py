"""
Switch notifications — Discord webhook and/or Apprise.
"""

import logging

import requests

from .i18n import get_translations

logger = logging.getLogger(__name__)


_LOGO_URL = 'https://raw.githubusercontent.com/Aerya/Gluetun-Companion/main/assets/logo.png'


def _strip_filter(label: str | None) -> str:
    """'SERVER_NAMES=Chamukuy' → 'Chamukuy'. Strips filter-key prefix for display."""
    if not label:
        return '—'
    return label.split('=', 1)[1] if '=' in label else label


def _discord_payload(
    from_server: str | None,
    to_server: str,
    from_mbps: float | None,
    to_mbps: float | None,
    connect_secs: float | None,
    to_ipv4: str | None,
    to_ipv6: str | None,
    reason: str,
    t: dict,
    companion_url: str | None = None,
    updated_images: list[str] | None = None,
    qc_info: dict | None = None,
    from_ipv4: str | None = None,
    from_ipv6: str | None = None,
) -> dict:
    gain = (to_mbps - from_mbps) if (from_mbps and to_mbps) else None
    color = 0x3fb950  # green
    if gain is not None and gain < 0:
        color = 0xf85149  # red
    elif gain is None:
        color = 0x58a6ff  # blue / neutral

    from_label = _strip_filter(from_server)
    to_label   = _strip_filter(to_server)

    # Build "from" value: name + IP if available
    from_value = f'`{from_label}`' if from_server else '—'
    if from_ipv4:
        from_value += f'\n`{from_ipv4}`'
        if from_ipv6:
            from_value += f'\n`{from_ipv6}`'

    # Build "to" value: name + IP if available
    to_value = f'`{to_label}`'
    if to_ipv4:
        to_value += f'\n`{to_ipv4}`'
        if to_ipv6:
            to_value += f'\n`{to_ipv6}`'

    fields = [
        {'name': t['notif_field_from'], 'value': from_value, 'inline': True},
        {'name': t['notif_field_to'],   'value': to_value,   'inline': True},
        {'name': '​', 'value': '​', 'inline': True},  # spacer
    ]
    if from_mbps is not None:
        fields.append({'name': t['notif_field_speed_before'], 'value': f'{from_mbps:.1f} Mbps', 'inline': True})
    if to_mbps is not None:
        fields.append({'name': t['notif_field_speed_after'], 'value': f'{to_mbps:.1f} Mbps', 'inline': True})
    if gain is not None:
        sign = '+' if gain >= 0 else ''
        fields.append({'name': t['notif_field_gain'], 'value': f'{sign}{gain:.1f} Mbps', 'inline': True})
    # IPs are now embedded directly in the from/to fields above.
    if connect_secs is not None:
        fields.append({'name': t['notif_field_connect'], 'value': f'{connect_secs:.0f} s', 'inline': True})

    # Quick check triggered info — explains why the full benchmark was launched
    if qc_info and qc_info.get('current_dl') is not None and qc_info.get('last_dl'):
        degraded = qc_info['current_dl'] < qc_info['last_dl']
        sign = '−' if degraded else '+'
        qc_server = _strip_filter(qc_info.get('server', ''))
        fields.append({
            'name': t.get('notif_qc_triggered_field', 'Dérive détectée'),
            'value': (
                f'`{qc_server}` {sign}{qc_info["diff_pct"]:.0f}% '
                f'({qc_info["current_dl"]:.0f} → {qc_info["last_dl"]:.0f} Mbps)'
            ),
            'inline': False,
        })

    # Updated images
    if updated_images:
        fields.append({
            'name': t.get('notif_updated_images', 'Images mises à jour'),
            'value': '\n'.join(f'`{img}`' for img in updated_images),
            'inline': False,
        })

    author: dict = {'name': t['notif_footer'], 'icon_url': _LOGO_URL}
    if companion_url:
        author['url'] = companion_url
    embed: dict = {
        'author': author,
        'title':  t['notif_title'],
        'color':  color,
        'fields': fields,
    }
    payload: dict = {
        'username':   'Gluetun Companion',
        'avatar_url': _LOGO_URL,
        'embeds':     [embed],
    }
    return payload


def _text_body(
    from_server: str | None,
    to_server: str,
    from_mbps: float | None,
    to_mbps: float | None,
    connect_secs: float | None,
    to_ipv4: str | None,
    to_ipv6: str | None,
    reason: str,
    t: dict,
    companion_url: str | None = None,
    updated_images: list[str] | None = None,
    qc_info: dict | None = None,
    from_ipv4: str | None = None,
    from_ipv6: str | None = None,
) -> str:
    gain = (to_mbps - from_mbps) if (from_mbps and to_mbps) else None

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

    # Quick check triggered info
    if qc_info and qc_info.get('current_dl') is not None and qc_info.get('last_dl'):
        sign = '−' if qc_info['current_dl'] < qc_info['last_dl'] else '+'
        qc_server = _strip_filter(qc_info.get('server', ''))
        lines.append(
            f'{t.get("notif_qc_triggered_field", "Dérive")} : '
            f'{qc_server} {sign}{qc_info["diff_pct"]:.0f}% '
            f'({qc_info["current_dl"]:.0f}→{qc_info["last_dl"]:.0f} Mbps)'
        )

    # Updated images
    if updated_images:
        lines.append(
            f'{t.get("notif_updated_images", "Images mises à jour")} : '
            + ', '.join(updated_images)
        )

    if companion_url:
        lines.append(companion_url)
    return '\n'.join(lines)


def send_test_notification(
    target: str,
    discord_url: str | None = None,
    apprise_urls: str | None = None,
    lang: str = 'fr',
    mention: str | None = None,
) -> tuple[bool, str]:
    """
    Send a test notification to Discord and/or Apprise.
    `target` is 'discord', 'apprise', or 'all'.
    Returns (success, message).
    """
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
                payload['allowed_mentions'] = {'parse': ['users', 'roles']}
            resp = requests.post(discord_url.strip(), json=payload, timeout=10)
            resp.raise_for_status()
            logger.info('Discord test notification sent')
        except Exception as exc:
            logger.warning('Discord test notification failed: %s', exc)
            return False, f'Discord : {exc}'

    if target in ('apprise', 'all') and apprise_urls:
        try:
            import apprise as _apprise
            ap = _apprise.Apprise()
            for url in apprise_urls.splitlines():
                url = url.strip()
                if url:
                    ap.add(url)
            body = t.get('notif_test_body', 'Notification test — OK')
            ok = ap.notify(title=f'{t["notif_footer"]} — test', body=body)
            if not ok:
                return False, 'Apprise : notify() returned False'
            logger.info('Apprise test notification sent')
        except ImportError:
            return False, 'Apprise not installed'
        except Exception as exc:
            logger.warning('Apprise test notification failed: %s', exc)
            return False, f'Apprise : {exc}'

    return True, 'OK'


def send_already_best_notification(
    server: str,
    speed_mbps: float | None,
    ipv4: str | None,
    ipv6: str | None,
    discord_url: str | None = None,
    apprise_urls: str | None = None,
    lang: str = 'fr',
    companion_url: str | None = None,
):
    """Send a notification when the current server is already the best — no switch needed."""
    if not discord_url and not apprise_urls:
        return

    t = get_translations(lang)
    title = t.get('notif_already_best_title', 'Already on best server')
    server_label = _strip_filter(server)

    if discord_url:
        try:
            fields = [
                {
                    'name':   t.get('notif_already_best_field', 'Active server'),
                    'value':  f'`{server_label}`',
                    'inline': True,
                },
            ]
            if speed_mbps is not None:
                fields.append({
                    'name':   t.get('notif_field_speed', 'Speed'),
                    'value':  f'{speed_mbps:.1f} Mbps',
                    'inline': True,
                })
            if ipv4:
                fields.append({'name': 'IPv4', 'value': ipv4, 'inline': True})
            if ipv6:
                fields.append({'name': 'IPv6', 'value': ipv6, 'inline': True})
            author: dict = {'name': t['notif_footer'], 'icon_url': _LOGO_URL}
            if companion_url:
                author['url'] = companion_url
            embed: dict = {
                'author': author,
                'title':  title,
                'color':  0x58a6ff,   # blue — no change
                'fields': fields,
            }
            payload: dict = {
                'username':   'Gluetun Companion',
                'avatar_url': _LOGO_URL,
                'embeds':     [embed],
            }
            resp = requests.post(discord_url.strip(), json=payload, timeout=10)
            resp.raise_for_status()
            logger.info('Discord already-best notification sent')
        except Exception as exc:
            logger.warning('Discord already-best notification failed: %s', exc)

    if apprise_urls:
        try:
            import apprise as _apprise
            ap = _apprise.Apprise()
            for url in apprise_urls.splitlines():
                url = url.strip()
                if url:
                    ap.add(url)
            lines = [server_label]
            if speed_mbps is not None:
                lines.append(f'{t.get("notif_text_speed", "Speed")} : {speed_mbps:.1f} Mbps')
            if ipv4:
                ip = ipv4 + (f' / {ipv6}' if ipv6 else '')
                lines.append(f'{t.get("notif_text_ip", "IP")} : {ip}')
            if companion_url:
                lines.append(companion_url)
            ap.notify(
                title=t.get('notif_already_best_apprise_title', 'Already optimal — Gluetun Companion'),
                body='\n'.join(lines),
            )
            logger.info('Apprise already-best notification sent')
        except ImportError:
            logger.warning('Apprise not installed — add "apprise" to requirements.txt')
        except Exception as exc:
            logger.warning('Apprise already-best notification failed: %s', exc)


def send_new_airvpn_servers_notification(
    new_servers: list[dict],
    discord_url: str | None = None,
    apprise_urls: str | None = None,
    lang: str = 'fr',
    mention: str | None = None,
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

    # Group by country for display
    countries_seen: dict[str, list[str]] = {}
    for s in new_servers:
        countries_seen.setdefault(s['country'], []).append(s['name'])

    if discord_url:
        try:
            fields = []
            for country, names in countries_seen.items():
                fields.append({
                    'name':   country,
                    'value':  '\n'.join(f'`{nm}`' for nm in names),
                    'inline': True,
                })
            author: dict = {'name': t['notif_footer'], 'icon_url': _LOGO_URL}
            if companion_url:
                author['url'] = companion_url
            embed: dict = {
                'author': author,
                'title':  title,
                'color':  0x3fb950,
                'fields': fields,
            }
            payload: dict = {
                'username':   'Gluetun Companion',
                'avatar_url': _LOGO_URL,
                'embeds':     [embed],
            }
            if mention:
                payload['content'] = mention
                # allowed_mentions is required for Discord to actually ping;
                # without it the mention is rendered as plain text.
                payload['allowed_mentions'] = {'parse': ['users', 'roles']}
            resp = requests.post(discord_url.strip(), json=payload, timeout=10)
            resp.raise_for_status()
            logger.info('Discord new-AirVPN-servers notification sent (%d server(s))', n)
        except Exception as exc:
            logger.warning('Discord new-AirVPN-servers notification failed: %s', exc)

    if apprise_urls:
        try:
            import apprise as _apprise
            ap = _apprise.Apprise()
            for url in apprise_urls.splitlines():
                url = url.strip()
                if url:
                    ap.add(url)
            lines = []
            if mention:
                lines.append(mention)
            for country, names in countries_seen.items():
                lines.append(f'{country}: {", ".join(names)}')
            if companion_url:
                lines.append(companion_url)
            ap.notify(title=title, body='\n'.join(lines))
            logger.info('Apprise new-AirVPN-servers notification sent (%d server(s))', n)
        except ImportError:
            logger.warning('Apprise not installed — add "apprise" to requirements.txt')
        except Exception as exc:
            logger.warning('Apprise new-AirVPN-servers notification failed: %s', exc)


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
):
    if not discord_url and not apprise_urls:
        return

    t = get_translations(lang)

    if discord_url:
        try:
            payload = _discord_payload(
                from_server, to_server, from_mbps, to_mbps,
                connect_secs, to_ipv4, to_ipv6, reason, t,
                companion_url=companion_url,
                updated_images=updated_images,
                qc_info=qc_info,
                from_ipv4=from_ipv4,
                from_ipv6=from_ipv6,
            )
            resp = requests.post(discord_url.strip(), json=payload, timeout=10)
            resp.raise_for_status()
            logger.info('Discord notification sent')
        except Exception as exc:
            logger.warning('Discord notification failed: %s', exc)

    if apprise_urls:
        try:
            import apprise  # optional dependency
            ap = apprise.Apprise()
            for url in apprise_urls.splitlines():
                url = url.strip()
                if url:
                    ap.add(url)
            body = _text_body(
                from_server, to_server, from_mbps, to_mbps,
                connect_secs, to_ipv4, to_ipv6, reason, t,
                companion_url=companion_url,
                updated_images=updated_images,
                qc_info=qc_info,
                from_ipv4=from_ipv4,
                from_ipv6=from_ipv6,
            )
            ap.notify(title=t['notif_apprise_title'], body=body)
            logger.info('Apprise notification sent')
        except ImportError:
            logger.warning('Apprise not installed — add "apprise" to requirements.txt')
        except Exception as exc:
            logger.warning('Apprise notification failed: %s', exc)
