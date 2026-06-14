from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from app.gluetun import apply_dns_filtering, switch_server


class SwitchServerOverrideTest(TestCase):
    def test_deduplicates_managed_profile_variables(self) -> None:
        profile = {
            'compose_provider': 'airvpn',
            'vars': {
                'VPN_SERVICE_PROVIDER': 'airvpn',
                'VPN_TYPE': 'wireguard',
                'SERVER_NAMES': 'must-not-override-selection',
                'WIREGUARD_PRIVATE_KEY': 'private-key',
                'WIREGUARD_PRESHARED_KEY': 'preshared-key',
                'WIREGUARD_ADDRESSES': '10.146.38.51/32',
            },
        }

        with TemporaryDirectory() as directory:
            with (
                patch('app.gluetun._detect_compose_project', return_value='airvpn'),
                patch('app.gluetun._detect_compose_service', return_value='gluetun-airvpn'),
                patch('app.gluetun.mark_companion_restart'),
                patch('app.gluetun.subprocess.run') as run,
            ):
                run.return_value.returncode = 0
                run.return_value.stderr = ''
                run.return_value.stdout = ''
                success, error = switch_server(
                    'Dalim',
                    'server_names',
                    'gluetun-airvpn',
                    directory,
                    wg_profile=profile,
                )

                override = (Path(directory) / 'docker-compose.override.yml').read_text()

        self.assertTrue(success)
        self.assertIsNone(error)
        self.assertEqual(override.count('VPN_SERVICE_PROVIDER:'), 1)
        self.assertEqual(override.count('VPN_TYPE:'), 1)
        self.assertEqual(override.count('SERVER_NAMES:'), 1)
        self.assertIn('SERVER_NAMES: "Dalim"', override)
        self.assertEqual(override.count('WIREGUARD_PRIVATE_KEY:'), 1)

    def test_switch_preserves_dns_filtering_settings(self) -> None:
        with TemporaryDirectory() as directory:
            with (
                patch('app.gluetun._detect_compose_project', return_value='airvpn'),
                patch('app.gluetun._detect_compose_service', return_value='gluetun-airvpn'),
                patch('app.gluetun.mark_companion_restart'),
                patch('app.gluetun.get_setting', side_effect=lambda key, default='': {
                    'dns_block_malicious': '0',
                    'dns_unblock_hostnames': 'tracker.example.org',
                }.get(key, default), create=True),
                patch('app.gluetun.subprocess.run') as run,
            ):
                run.return_value.returncode = 0
                run.return_value.stderr = ''
                run.return_value.stdout = ''
                success, error = switch_server(
                    'Dalim', 'server_names', 'gluetun-airvpn', directory,
                )
                override = (Path(directory) / 'docker-compose.override.yml').read_text()

        self.assertTrue(success)
        self.assertIsNone(error)
        self.assertIn('BLOCK_MALICIOUS: "off"', override)
        self.assertIn('DNS_UNBLOCK_HOSTNAMES: "tracker.example.org"', override)

    def test_apply_dns_filtering_updates_existing_override(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'docker-compose.override.yml'
            path.write_text(
                'services:\n  gluetun-airvpn:\n    environment:\n'
                '      SERVER_NAMES: "Dalim"\n      BLOCK_MALICIOUS: "on"\n',
                encoding='utf-8',
            )
            with (
                patch('app.gluetun._detect_compose_project', return_value='airvpn'),
                patch('app.gluetun._detect_compose_service', return_value='gluetun-airvpn'),
                patch('app.gluetun.mark_companion_restart'),
                patch('app.gluetun.list_network_dependents_for_recreate', return_value=['qbittorrent']),
                patch('app.gluetun.restart_network_dependents') as restart_dependents,
                patch('app.gluetun.subprocess.run') as run,
            ):
                run.return_value.returncode = 0
                run.return_value.stderr = ''
                run.return_value.stdout = ''
                success, error = apply_dns_filtering(
                    'gluetun-airvpn', directory, False, 'tracker.example.org',
                )
                override = path.read_text(encoding='utf-8')

        self.assertTrue(success)
        self.assertIsNone(error)
        self.assertEqual(override.count('BLOCK_MALICIOUS:'), 1)
        self.assertIn('BLOCK_MALICIOUS: "off"', override)
        self.assertIn('DNS_UNBLOCK_HOSTNAMES: "tracker.example.org"', override)
        self.assertIn('SERVER_NAMES: "Dalim"', override)
        restart_dependents.assert_called_once_with(
            'gluetun-airvpn', directory, 'airvpn', explicit_list=['qbittorrent'],
        )
