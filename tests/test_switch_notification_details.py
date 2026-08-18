from app.notify import _switch_discord_payload


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
