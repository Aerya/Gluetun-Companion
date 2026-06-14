import json
import unittest
from unittest.mock import patch

from app.dns_path import _build_dns_status, _intermediary, _provider_name


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
