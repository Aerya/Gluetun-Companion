"""
Switch notifications — Discord webhook and/or Apprise.
"""

import logging

import requests

from .i18n import get_translations

logger = logging.getLogger(__name__)


def _footer_text(base: str, companion_url: str | None) -> str:
    """Build footer text: 'Gluetun Companion' or 'Gluetun Companion — https://...'"""
    if companion_url:
        return f'{base} — {companion_url}'
    return base


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
) -> dict:
    gain = (to_mbps - from_mbps) if (from_mbps and to_mbps) else None
    color = 0x3fb950  # green
    if gain is not None and gain < 0:
        color = 0xf85149  # red
    elif gain is None:
        color = 0x58a6ff  # blue / neutral

    fields = [
        {'name': t['notif_field_from'], 'value': f'`{from_server}`' if from_server else '—', 'inline': True},
        {'name': t['notif_field_to'],   'value': f'`{to_server}`', 'inline': True},
        {'name': '​', 'value': '​', 'inline': True},  # spacer
    ]
    if from_mbps is not None:
        fields.append({'name': t['notif_field_speed_before'], 'value': f'{from_mbps:.1f} Mbps', 'inline': True})
    if to_mbps is not None:
        fields.append({'name': t['notif_field_speed_after'], 'value': f'{to_mbps:.1f} Mbps', 'inline': True})
    if gain is not None:
        sign = '+' if gain >= 0 else ''
        fields.append({'name': t['notif_field_gain'], 'value': f'{sign}{gain:.1f} Mbps', 'inline': True})
    if to_ipv4:
        fields.append({'name': 'IPv4', 'value': to_ipv4, 'inline': True})
    if to_ipv6:
        fields.append({'name': 'IPv6', 'value': to_ipv6, 'inline': True})
    if connect_secs is not None:
        fields.append({'name': t['notif_field_connect'], 'value': f'{connect_secs:.0f} s', 'inline': True})

    # Quick check triggered info
    if qc_info and qc_info.get('current_dl') is not None and qc_info.get('last_dl'):
        sign = '−' if qc_info['current_dl'] < qc_info['last_dl'] else '+'
        fields.append({
            'name': t.get('notif_qc_triggered_field', 'Quick check'),
            'value': (
                f'`{qc_info["server"]}` — '
                f'{qc_info["current_dl"]:.1f} Mbps '
                f'({sign}{qc_info["diff_pct"]:.1f}% vs {qc_info["last_dl"]:.1f} Mbps)'
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

    embed: dict = {
        'title':  t['notif_title'],
        'color':  color,
        'fields': fields,
        'footer': {'text': _footer_text(t['notif_footer'], companion_url)},
    }
    return {'embeds': [embed]}


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
) -> str:
    gain = (to_mbps - from_mbps) if (from_mbps and to_mbps) else None

    lines = [f'🔄 {from_server or "?"} → {to_server}']
    if from_mbps is not None and to_mbps is not None:
        sign = '+' if gain >= 0 else ''
        lines.append(f'{t["notif_text_speed"]} : {from_mbps:.1f} → {to_mbps:.1f} Mbps ({sign}{gain:.1f})')
    if to_ipv4:
        ip = to_ipv4
        if to_ipv6:
            ip += f' / {to_ipv6}'
        lines.append(f'{t["notif_text_ip"]} : {ip}')
    if connect_secs is not None:
        lines.append(f'{t["notif_text_connect"]} : {connect_secs:.0f} s')

    # Quick check triggered info
    if qc_info and qc_info.get('current_dl') is not None and qc_info.get('last_dl'):
        sign = '−' if qc_info['current_dl'] < qc_info['last_dl'] else '+'
        lines.append(
            f'{t.get("notif_qc_triggered_field", "Quick check")} : '
            f'{qc_info["server"]} — '
            f'{qc_info["current_dl"]:.1f} Mbps '
            f'({sign}{qc_info["diff_pct"]:.1f}% vs {qc_info["last_dl"]:.1f} Mbps)'
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
                'embeds': [{
                    'title': f'✅ {t["notif_footer"]} — test',
                    'description': t.get('notif_test_body', 'Notification test — OK'),
                    'color': 0x3fb950,
                    'footer': {'text': t['notif_footer']},
                }]
            }
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

    if discord_url:
        try:
            fields = [
                {
                    'name':   t.get('notif_already_best_field', 'Active server'),
                    'value':  f'`{server}`',
                    'inline': True,
                },
            ]
            if speed_mbps is not None:
                fields.append({
                    'name':   t.get('notif_field_speed_after', 'Speed'),
                    'value':  f'{speed_mbps:.1f} Mbps',
                    'inline': True,
                })
            if ipv4:
                fields.append({'name': 'IPv4', 'value': ipv4, 'inline': True})
            if ipv6:
                fields.append({'name': 'IPv6', 'value': ipv6, 'inline': True})
            embed: dict = {
                'title':  title,
                'color':  0x58a6ff,   # blue — no change
                'fields': fields,
                'footer': {'text': _footer_text(t['notif_footer'], companion_url)},
            }
            payload = {'embeds': [embed]}
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
            lines = [server]
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
            )
            ap.notify(title=t['notif_apprise_title'], body=body)
            logger.info('Apprise notification sent')
        except ImportError:
            logger.warning('Apprise not installed — add "apprise" to requirements.txt')
        except Exception as exc:
            logger.warning('Apprise notification failed: %s', exc)
