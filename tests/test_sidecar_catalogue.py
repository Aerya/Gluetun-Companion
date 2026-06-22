"""Unit tests for the sidecar catalogue reader."""

import importlib.util
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

_SIDECAR_PATH = Path(__file__).resolve().parents[1] / 'sidecar' / 'app.py'
_spec = importlib.util.spec_from_file_location('sidecar_app_catalogue', _SIDECAR_PATH)
sidecar = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sidecar)


class MountedCatalogueTest(unittest.TestCase):
    def test_prefers_aggregate_servers_json_with_proton_premium_metadata(self):
        with TemporaryDirectory() as d:
            payload = {
                'version': 1,
                'protonvpn': {
                    'servers': [
                        {
                            'server_name': 'FR#208',
                            'country': 'France',
                            'city': 'Marseille',
                            'hostname': 'node-fr-24.protonvpn.net',
                            'port_forward': True,
                            'stream': True,
                        },
                    ],
                },
            }
            provider = {
                'servers': [
                    {
                        'server_name': 'FR#999',
                        'country': 'France',
                        'hostname': 'node-fr-99.protonvpn.net',
                    },
                ],
            }
            servers_dir = Path(d) / 'servers'
            servers_dir.mkdir()
            (Path(d) / 'servers.json').write_text(json.dumps(payload), encoding='utf-8')
            (servers_dir / 'protonvpn.json').write_text(json.dumps(provider), encoding='utf-8')

            data = sidecar._read_mounted_catalogue(d)

        self.assertEqual(set(data), {'protonvpn'})
        self.assertEqual(len(data['protonvpn']), 1)
        server = data['protonvpn'][0]
        self.assertEqual(server['name'], 'FR#208')
        self.assertEqual(server['city'], 'Marseille')
        self.assertEqual(server['hostname'], 'node-fr-24.protonvpn.net')
        self.assertEqual(server['server_types'], 'p2p,stream')


if __name__ == '__main__':
    unittest.main()
