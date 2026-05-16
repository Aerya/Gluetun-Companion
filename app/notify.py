"""
Switch notifications — Discord webhook and/or Apprise.
"""

import logging

import requests

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
) -> dict:
    gain = (to_mbps - from_mbps) if (from_mbps and to_mbps) else None
    color = 0x3fb950  # green
    if gain is not None and gain < 0:
        color = 0xf85149  # red
    elif gain is None:
        color = 0x58a6ff  # blue / neutral

    reason_label = 'Automatique (meilleur score pondéré)' if reason == 'auto_best' else 'Manuelle'

    fields = [
        {'name': 'Ancien serveur', 'value': f'`{from_server}`' if from_server else '—', 'inline': True},
        {'name': 'Nouveau serveur', 'value': f'`{to_server}`', 'inline': True},
        {'name': '​', 'value': '​', 'inline': True},  # spacer
    ]
    if from_mbps is not None:
        fields.append({'name': 'Débit avant', 'value': f'{from_mbps:.1f} Mbps', 'inline': True})
    if to_mbps is not None:
        fields.append({'name': 'Débit après', 'value': f'{to_mbps:.1f} Mbps', 'inline': True})
    if gain is not None:
        sign = '+' if gain >= 0 else ''
        fields.append({'name': 'Gain', 'value': f'{sign}{gain:.1f} Mbps', 'inline': True})
    if to_ipv4:
        fields.append({'name': 'IPv4', 'value': to_ipv4, 'inline': True})
    if to_ipv6:
        fields.append({'name': 'IPv6', 'value': to_ipv6, 'inline': True})
    if connect_secs is not None:
        fields.append({'name': 'Connexion', 'value': f'{connect_secs:.0f} s', 'inline': True})
    fields.append({'name': 'Raison', 'value': reason_label, 'inline': False})

    return {
        'embeds': [{
            'title': '🔄 Bascule VPN',
            'color': color,
            'fields': fields,
            'footer': {'text': 'Gluetun Companion'},
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
) -> str:
    gain = (to_mbps - from_mbps) if (from_mbps and to_mbps) else None
    reason_label = 'auto (meilleur score)' if reason == 'auto_best' else 'manuelle'

    lines = [f'🔄 {from_server or "?"} → {to_server}']
    if from_mbps is not None and to_mbps is not None:
        sign = '+' if gain >= 0 else ''
        lines.append(f'Débit : {from_mbps:.1f} → {to_mbps:.1f} Mbps ({sign}{gain:.1f})')
    if to_ipv4:
        ip = to_ipv4
        if to_ipv6:
            ip += f' / {to_ipv6}'
        lines.append(f'IP : {ip}')
    if connect_secs is not None:
        lines.append(f'Connexion : {connect_secs:.0f} s')
    lines.append(f'Raison : {reason_label}')
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
):
    if not discord_url and not apprise_urls:
        return

    if discord_url:
        try:
            payload = _discord_payload(
                from_server, to_server, from_mbps, to_mbps,
                connect_secs, to_ipv4, to_ipv6, reason,
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
                connect_secs, to_ipv4, to_ipv6, reason,
            )
            ap.notify(title='Bascule VPN — Gluetun Companion', body=body)
            logger.info('Apprise notification sent')
        except ImportError:
            logger.warning('Apprise not installed — add "apprise" to requirements.txt')
        except Exception as exc:
            logger.warning('Apprise notification failed: %s', exc)
