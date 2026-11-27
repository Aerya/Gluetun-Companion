from unittest.mock import patch

import pytest

from app.i18n import get_translations
from app.notify import _switch_discord_payload, send_switch_notification


def test_switch_payload_lists_recreated_containers_and_updated_images():
    t = {
        'notif_footer': 'Gluetun Companion',
        'notif_title': 'Bascule VPN',
        'notif_field_from': 'Depuis',
        'notif_field_to': 'Vers',
        'notif_field_speed_before': 'Avant',
        'notif_field_speed_after': 'Après',
        'notif_field_gain': 'Gain',
        'notif_field_connect': 'Connexion',
        'notif_recreated_containers': 'Conteneurs recréés — réseau Gluetun',
        'notif_updated_images': 'Images mises à jour',
    }
    payload = _switch_discord_payload(
        'SERVER_NAMES=Alwaid', 'SERVER_NAMES=Dedalus', None, None, 4.0,
        '1.2.3.4', None, t,
        recreated_containers=['qbittorrentvpn1', 'prowlarr'],
        updated_images=['lscr.io/linuxserver/qbittorrent:latest'],
    )
    fields = payload['embeds'][0]['fields']
    by_name = {f['name']: f['value'] for f in fields}
    assert by_name['Conteneurs recréés — réseau Gluetun'] == '`qbittorrentvpn1`\n`prowlarr`'
    assert by_name['Images mises à jour'] == '`lscr.io/linuxserver/qbittorrent:latest`'


@pytest.mark.parametrize('lang', ['fr', 'en'])
@pytest.mark.parametrize('reason', ['external_recreate', 'vpn_reconnect'])
def test_observed_switch_reason_is_visible_on_discord_and_apprise(lang, reason):
    with (patch('app.notify._post_discord') as discord,
          patch('app.notify._notify_apprise') as apprise):
        send_switch_notification(
            'OldServer', 'NewServer', None, None, None, '2.2.2.2', None,
            reason, discord_url='https://example.invalid/webhook',
            apprise_urls='json://example.invalid', lang=lang)
    expected = get_translations(lang)[f'notif_{reason}_title']
    payload = discord.call_args.args[1]
    assert payload['embeds'][0]['title'] == expected
    fields = payload['embeds'][0]['fields']
    assert 'OldServer' in fields[0]['value']
    assert 'NewServer' in fields[1]['value']
    assert '2.2.2.2' in fields[1]['value']
    assert apprise.call_args.args[1] == expected
    assert 'OldServer' in apprise.call_args.args[2]
    assert 'NewServer' in apprise.call_args.args[2]
