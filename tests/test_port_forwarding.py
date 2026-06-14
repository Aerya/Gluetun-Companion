import unittest
from unittest.mock import MagicMock, patch

from app.port_forwarding import (
    _extract_ports,
    inspect_port_forward,
    sync_qbit_listen_port,
)


class ProtonPortForwardingTest(unittest.TestCase):
    def test_gluetun_control_server_port_payload(self):
        self.assertEqual(_extract_ports({'port': 5914}), [5914])

    @patch('app.port_forwarding._docker_published_ports')
    @patch('app.port_forwarding._container_env', return_value={
        'VPN_SERVICE_PROVIDER': 'protonvpn',
        'VPN_PORT_FORWARDING': 'on',
    })
    def test_native_rule_uses_dynamic_port_without_static_mappings(self, _env, docker_ports):
        rule = {
            'id': 1,
            'name': 'ProtonVPN qBittorrent',
            'provider': 'protonvpn',
            'mode': 'native',
            'port': 0,
            'protocols': 'tcp,udp',
            'torrent_client_id': None,
        }
        result = inspect_port_forward(
            rule,
            'gluetun-protonvpn',
            {'ok': True, 'ports': [5914], 'error': ''},
        )
        self.assertEqual(result['effective_port'], 5914)
        self.assertEqual(result['gluetun_vpn_input']['state'], 'ok')
        self.assertEqual(result['gluetun_input']['state'], 'ok')
        self.assertTrue(all(item['state'] == 'ok' for item in result['docker_ports'].values()))
        docker_ports.assert_not_called()

    @patch('app.port_forwarding._set_last_applied_port')
    @patch('app.port_forwarding._qbit_listen_port', return_value=(5914, ''))
    @patch('app.port_forwarding._qbit_session')
    @patch('app.port_forwarding.get_torrent_client', return_value={
        'id': 4,
        'client_type': 'qbittorrent',
        'base_url': 'http://qbittorrent:8080',
    })
    @patch('app.port_forwarding.get_port_forward', return_value={
        'id': 7,
        'provider': 'protonvpn',
        'mode': 'native',
        'port': 0,
        'torrent_client_id': 4,
    })
    def test_dynamic_proton_port_is_injected_into_qbittorrent(
        self, _rule, _client, qbit_session, _listen_port, remember_port,
    ):
        response = MagicMock(status_code=200)
        qbit_session.return_value.post.return_value = response

        result = sync_qbit_listen_port(7, port_override=5914)

        self.assertTrue(result['ok'])
        self.assertEqual(result['listen_port'], 5914)
        post = qbit_session.return_value.post
        self.assertIn('setPreferences', post.call_args.args[0])
        self.assertIn('5914', post.call_args.kwargs['data']['json'])
        remember_port.assert_called_once_with(7, 5914)


if __name__ == '__main__':
    unittest.main()
