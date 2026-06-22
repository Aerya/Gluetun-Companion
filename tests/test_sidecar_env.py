import unittest
from unittest.mock import patch

from app.scheduler import _sidecar_extra_env


def _dns_setting(key, default=''):
    return {'dns_block_malicious': '1', 'dns_unblock_hostnames': ''}.get(key, default)


class SidecarExtraEnvTest(unittest.TestCase):
    @patch('app.gluetun.get_setting', side_effect=_dns_setting)
    def test_airvpn_benchmark_env_neutralizes_stale_proton_filters(self, _gs):
        profile = {
            'compose_provider': 'airvpn',
            'vpn_type': 'wireguard',
            'extra_env': {
                'VPN_SERVICE_PROVIDER': 'airvpn',
                'VPN_TYPE': 'wireguard',
                'WIREGUARD_PRIVATE_KEY': 'main-key',
                'WIREGUARD_ADDRESSES': '10.1.2.3/32',
                'PORT_FORWARD_ONLY': 'on',
                'SERVER_TYPES': 'P2P',
                'VPN_PORT_FORWARDING_PROVIDER': 'protonvpn',
            },
            'port_forwarding': False,
            'port_forward_only': True,
            'server_types': [],
        }

        env = _sidecar_extra_env(
            'Adhara',
            'name',
            profile,
            {'WIREGUARD_PRIVATE_KEY': 'sidecar-key'},
        )

        self.assertEqual(env['VPN_SERVICE_PROVIDER'], 'airvpn')
        self.assertEqual(env['SERVER_NAMES'], 'Adhara')
        self.assertEqual(env['PORT_FORWARD_ONLY'], '')
        self.assertEqual(env['SERVER_TYPES'], '')
        self.assertEqual(env['VPN_PORT_FORWARDING'], 'off')
        self.assertEqual(env['VPN_PORT_FORWARDING_PROVIDER'], '')
        self.assertEqual(env['WIREGUARD_PRIVATE_KEY'], 'sidecar-key')

    @patch('app.gluetun.get_setting', side_effect=_dns_setting)
    def test_airvpn_single_server_env_uses_vars_shape(self, _gs):
        profile = {
            'compose_provider': 'airvpn',
            'vpn_type': 'wireguard',
            'vars': {
                'WIREGUARD_PRIVATE_KEY': 'main-key',
                'PORT_FORWARD_ONLY': 'on',
            },
            'port_forwarding': False,
            'port_forward_only': True,
            'server_types': [],
        }

        env = _sidecar_extra_env('Adhara', 'name', profile)

        self.assertEqual(env['VPN_SERVICE_PROVIDER'], 'airvpn')
        self.assertEqual(env['VPN_TYPE'], 'wireguard')
        self.assertEqual(env['SERVER_NAMES'], 'Adhara')
        self.assertEqual(env['PORT_FORWARD_ONLY'], '')
        self.assertEqual(env['VPN_PORT_FORWARDING'], 'off')


if __name__ == '__main__':
    unittest.main()
