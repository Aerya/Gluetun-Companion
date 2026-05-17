"""
Switch notifications — Discord webhook and/or Apprise.
"""

import logging

import requests

from .i18n import get_translations

logger = logging.getLogger(__name__)


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
) -> dict:
    gain = (to_mbps - from_mbps) if (from_mbps and to_mbps) else None
    color = 0x3fb950  # green
    if gain is not None and gain < 0:
        color = 0xf85149  # red
    elif gain is None:
        color = 0x58a6ff  # blue / neutral

    reason_label = t['notif_reason_auto'] if reason == 'auto_best' else t['notif_reason_manual']

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
    fields.append({'name': t['notif_field_reason'], 'value': reason_label, 'inline': False})

    return {
        'embeds': [{
            'title': t['notif_title'],
            'color': color,
            'fields': fields,
            'footer': {'text': t['notif_footer']},
        }]
    }


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
) -> str:
    gain = (to_mbps - from_mbps) if (from_mbps and to_mbps) else None
    reason_label = t['notif_reason_auto_short'] if reason == 'auto_best' else t['notif_reason_manual_short']

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
    lines.append(f'{t["notif_text_reason"]} : {reason_label}')
    return '\n'.join(lines)


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
):
    if not discord_url and not apprise_urls:
        return

    t = get_translations(lang)

    if discord_url:
        try:
            payload = _discord_payload(
                from_server, to_server, from_mbps, to_mbps,
                connect_secs, to_ipv4, to_ipv6, reason, t,
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
            )
            ap.notify(title=t['notif_apprise_title'], body=body)
            logger.info('Apprise notification sent')
        except ImportError:
            logger.warning('Apprise not installed — add "apprise" to requirements.txt')
        except Exception as exc:
            logger.warning('Apprise notification failed: %s', exc)
