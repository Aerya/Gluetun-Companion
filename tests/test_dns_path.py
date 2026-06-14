import json
import unittest
from unittest.mock import MagicMock, patch

from app.dns_path import (
    _build_dns_status,
    _intermediary,
    _provider_name,
    _run_observation_sidecar,
)


class DnsPathTest(unittest.TestCase):
    def test_recognizes_common_resolver_operators(self):
        self.assertEqual(_provider_name('172.70.1.2', 'AS13335 Cloudflare, Inc.'), 'Cloudflare')
        self.assertEqual(_provider_name('9.9.9.9'), 'Quad9')
        self.assertEqual(_provider_name('8.8.8.8'), 'Google Public DNS')

    def test_local_intermediary(self):
        result = _intermediary({
            'DNS_UPSTREAM_RESOLVER_TYPE': 'plain',
            'DNS_UPSTREAM_PLAIN_ADDRESSES': '192.168.0.64:53',
            'VPN_SERVICE_PROVIDER': 'airvpn',
        }, 'fr')
        self.assertEqual(result, {
            'label': 'DNS local', 'address': '192.168.0.64', 'probable': False,
        })

    def test_probable_vpn_intermediary(self):
        result = _intermediary({
            'DNS_UPSTREAM_RESOLVER_TYPE': 'plain',
            'DNS_UPSTREAM_PLAIN_ADDRESSES': '10.4.0.1:53',
            'VPN_SERVICE_PROVIDER': 'airvpn',
        }, 'fr')
        self.assertTrue(result['probable'])
        self.assertIn('AirVPN', result['label'])

    @patch('app.dns_path.get_setting', return_value='test-sidecar:latest')
    @patch('app.dns_path.docker.from_env')
    def test_observation_uses_temporary_sidecar_in_gluetun_network(self, from_env, _setting):
        client = from_env.return_value
        client.containers.get.side_effect = __import__('docker').errors.NotFound('missing')
        observer = MagicMock()
        observer.status = 'exited'
        observer.attrs = {'State': {'ExitCode': 0}}
        observer.logs.return_value = b'[{"type":"dns","ip":"1.1.1.1"}]'
        client.containers.run.return_value = observer

        payload = _run_observation_sidecar('gluetun-airvpn')

        self.assertEqual(payload[0]['ip'], '1.1.1.1')
        kwargs = client.containers.run.call_args.kwargs
        self.assertEqual(kwargs['network_mode'], 'container:gluetun-airvpn')
        self.assertEqual(kwargs['image'], 'test-sidecar:latest')
        observer.remove.assert_called_once_with(force=True)

    @patch('app.dns_path._refresh_in_background')
    @patch('app.dns_path.get_setting')
    @patch('app.dns_path.get_container_env')
    def test_status_combines_intermediary_and_observed_resolvers(
        self, container_env, setting, refresh,
    ):
        container_env.return_value = {
            'DNS_UPSTREAM_RESOLVER_TYPE': 'plain',
            'DNS_UPSTREAM_PLAIN_ADDRESSES': '192.168.0.64:53',
        }
        setting.side_effect = lambda key, default='': json.dumps({
            'timestamp': 4102444800,
            'tested_at': '2100-01-01 00:00:00',
            'resolvers': [
                {'ip': '172.70.1.2', 'provider': 'Cloudflare', 'country': 'France'},
                {'ip': '149.112.112.1', 'provider': 'Quad9', 'country': 'Switzerland'},
            ],
        }) if key == 'dns_observed_result' else default
        result = _build_dns_status('gluetun', 'fr')
        self.assertEqual(result['intermediary_value'], 'DNS local (192.168.0.64)')
        self.assertEqual(result['observed_summary'], 'Cloudflare, Quad9')
        self.assertIn('172.70.1.2', result['tooltip'])
        refresh.assert_not_called()


if __name__ == '__main__':
    unittest.main()
