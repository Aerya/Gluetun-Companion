import unittest
from unittest.mock import patch

from app.dns_path import _build_dns_path, _provider_for


class DnsPathTest(unittest.TestCase):
    def test_recognizes_common_providers(self):
        self.assertEqual(_provider_for('tls://dns.quad9.net'), 'Quad9')
        self.assertEqual(_provider_for('1.1.1.1:53'), 'Cloudflare')
        self.assertEqual(_provider_for('https://dns.google/dns-query'), 'Google Public DNS')

    @patch('app.dns_path._read_adguard_upstreams', return_value=(['tls://dns.quad9.net'], ''))
    @patch('app.dns_path.get_setting')
    @patch('app.dns_path.get_container_env')
    def test_local_adguard_chain(self, container_env, setting, _adguard):
        container_env.return_value = {
            'DNS_ADDRESS': '127.0.0.1',
            'DNS_UPSTREAM_RESOLVER_TYPE': 'plain',
            'DNS_UPSTREAM_PLAIN_ADDRESSES': '192.168.0.64:53',
        }
        setting.side_effect = lambda key, default='': {
            'dns_local_label': 'AdGuard Home',
            'dns_local_address': '192.168.0.64',
            'dns_manual_upstreams': '',
        }.get(key, default)
        result = _build_dns_path('gluetun')
        self.assertEqual(result['short'], 'DNS Gluetun → AdGuard Home → Quad9')
        self.assertIn('192.168.0.64', result['detail'])

    @patch('app.dns_path.get_container_env', return_value={})
    def test_default_gluetun_resolver_is_cloudflare(self, _container_env):
        result = _build_dns_path('gluetun')
        self.assertEqual(result['short'], 'DNS Gluetun → Cloudflare')
        result_en = _build_dns_path('gluetun', lang='en')
        self.assertEqual(result_en['short'], 'Gluetun DNS → Cloudflare')

    @patch('app.dns_path.get_setting', return_value='')
    @patch('app.dns_path.get_container_env')
    def test_unknown_private_resolver_is_not_named_local_service(self, container_env, _setting):
        container_env.return_value = {
            'DNS_UPSTREAM_RESOLVER_TYPE': 'plain',
            'DNS_UPSTREAM_PLAIN_ADDRESSES': '10.0.0.1:53',
        }
        result = _build_dns_path('gluetun')
        self.assertIn('DNS privé / fournisseur VPN', result['short'])


if __name__ == '__main__':
    unittest.main()
