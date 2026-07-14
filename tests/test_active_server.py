import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.gluetun import (
    _active_server_cache,
    _latest_vpn_endpoint,
    get_active_server,
)


class ActiveServerTest(unittest.TestCase):
    def setUp(self):
        _active_server_cache.clear()

    def test_extracts_latest_wireguard_endpoint(self):
        logs = (
            'INFO [wireguard] Connecting to 1.2.3.4:51820\n'
            'INFO [wireguard] Connecting to 198.54.134.251:1637\n'
        )
        self.assertEqual(_latest_vpn_endpoint(logs), '198.54.134.251')

    @patch('app.gluetun.docker.from_env')
    def test_maps_live_endpoint_to_catalogue_server(self, from_env):
        container = MagicMock()
        container.id = 'gluetun-id'
        container.attrs = {
            'Config': {
                'Env': [
                    'VPN_SERVICE_PROVIDER=airvpn',
                    'SERVER_NAMES=Chamukuy,Elgafar,Dalim,Bunda',
                ]
            }
        }
        container.logs.return_value = (
            b'INFO [wireguard] Connecting to 198.54.134.251:1637\n'
        )
        container.exec_run.return_value = SimpleNamespace(
            exit_code=0,
            output=json.dumps({
                'servers': [
                    {'server_name': 'Bunda', 'ips': ['198.54.134.251']},
                ]
            }).encode(),
        )
        from_env.return_value.containers.get.return_value = container

        self.assertEqual(get_active_server('gluetun-airvpn'), 'Bunda')

    @patch('app.gluetun.get_setting', return_value='Bunda')
    @patch('app.gluetun.docker.from_env')
    def test_never_displays_all_candidates_when_endpoint_is_unknown(self, from_env, _setting):
        container = MagicMock()
        container.id = 'gluetun-id'
        container.attrs = {
            'Config': {
                'Env': [
                    'VPN_SERVICE_PROVIDER=airvpn',
                    'SERVER_NAMES=Chamukuy,Elgafar,Dalim,Bunda',
                ]
            }
        }
        container.logs.return_value = b'no endpoint in these logs\n'
        from_env.return_value.containers.get.return_value = container

        self.assertEqual(get_active_server('gluetun-airvpn'), 'Bunda')


if __name__ == '__main__':
    unittest.main()
