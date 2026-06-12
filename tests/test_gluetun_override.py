from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from app.gluetun import switch_server


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
