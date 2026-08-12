import unittest

from app.onboarding import active_profile_values


class ActiveProfileImportTest(unittest.TestCase):
    def test_reads_effective_wireguard_values(self):
        result = active_profile_values({
            'VPN_SERVICE_PROVIDER': 'airvpn',
            'VPN_TYPE': 'wireguard',
            'WIREGUARD_PRIVATE_KEY': 'private',
            'WIREGUARD_PRESHARED_KEY': 'preshared',
            'WIREGUARD_ADDRESSES': '10.1.2.3/32',
            'SERVER_COUNTRIES': 'Netherlands',
        })

        self.assertTrue(result['ok'])
        self.assertEqual(result['provider'], 'airvpn')
        self.assertEqual(result['vpn_type'], 'wireguard')
        self.assertEqual(result['values']['WIREGUARD_ADDRESSES'], '10.1.2.3/32')
        self.assertNotIn('SERVER_COUNTRIES', result['values'])

    def test_reports_required_values_hidden_behind_secret_files(self):
        result = active_profile_values({
            'VPN_SERVICE_PROVIDER': 'airvpn',
            'VPN_TYPE': 'wireguard',
            'WIREGUARD_ADDRESSES': '10.1.2.3/32',
        })

        self.assertFalse(result['ok'])
        self.assertEqual(
            result['missing'],
            ['WIREGUARD_PRIVATE_KEY', 'WIREGUARD_PRESHARED_KEY'],
        )

    def test_rejects_unknown_provider(self):
        result = active_profile_values({'VPN_SERVICE_PROVIDER': 'unknownvpn'})

        self.assertFalse(result['ok'])
        self.assertEqual(result['error'], 'unsupported_provider')


if __name__ == '__main__':
    unittest.main()
