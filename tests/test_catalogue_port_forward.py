import json
import os
import unittest
from tempfile import TemporaryDirectory

from app import database
from app.catalogue import (
    get_catalogue_entries,
    import_to_servers,
    local_catalogue_candidates,
    refresh_catalogue,
    refresh_catalogue_from_local,
)


_RESTORE_DB_DIR = TemporaryDirectory()


class CataloguePortForwardingTest(unittest.TestCase):
    def _fresh_db(self, directory):
        database.init_db(os.path.join(directory, 'test.db'))

    def tearDown(self):
        database.init_db(os.path.join(_RESTORE_DB_DIR.name, 'restore.db'))

    def _write_provider(self, directory):
        payload = {
            'servers': [
                {
                    'name': 'FR#61',
                    'country': 'France',
                    'country_code': 'fr',
                    'hostname': 'fr-61.protonvpn.net',
                    'port_forward': True,
                    'stream': True,
                },
                {
                    'name': 'FR#61',
                    'country': 'France',
                    'country_code': 'fr',
                    'hostname': 'fr-61-ovpn.protonvpn.net',
                    'port_forward': True,
                },
                {
                    'name': 'FR#10',
                    'country': 'France',
                    'country_code': 'fr',
                    'hostname': 'fr-10.protonvpn.net',
                    'port_forward': False,
                },
                {
                    'name': 'NL#1',
                    'country': 'Netherlands',
                    'country_code': 'nl',
                    'hostname': 'nl-01.protonvpn.net',
                    'stream': True,
                },
            ],
        }
        with open(os.path.join(directory, 'protonvpn.json'), 'w', encoding='utf-8') as fh:
            json.dump(payload, fh)

    def test_refresh_deduplicates_and_filters_port_forward_servers(self):
        with TemporaryDirectory() as d:
            self._fresh_db(d)
            self._write_provider(d)

            result = refresh_catalogue(d)
            self.assertTrue(result['ok'])
            self.assertEqual(result['providers']['protonvpn'], 3)

            all_entries = get_catalogue_entries(provider='protonvpn', filter_type='name')
            self.assertEqual([e['value'] for e in all_entries], ['FR#10', 'FR#61', 'NL#1'])

            p2p_entries = get_catalogue_entries(
                provider='protonvpn',
                filter_type='name',
                server_type='p2p',
            )
            self.assertEqual([e['value'] for e in p2p_entries], ['FR#61'])
            self.assertEqual(p2p_entries[0]['port_forward'], 1)
            self.assertEqual(p2p_entries[0]['server_types'], 'p2p,stream')

            countries = get_catalogue_entries(
                provider='protonvpn',
                filter_type='country',
                server_type='stream',
            )
            self.assertEqual([e['value'] for e in countries], ['France', 'Netherlands'])

    def test_import_can_limit_to_port_forward_servers(self):
        with TemporaryDirectory() as d:
            self._fresh_db(d)
            self._write_provider(d)
            refresh_catalogue(d)

            result = import_to_servers(
                mode='provider',
                provider='protonvpn',
                filter_type='name',
                server_type='p2p',
            )
            self.assertTrue(result['ok'])
            self.assertEqual(result['added'], 1)
            with database.get_db() as db:
                rows = db.execute('SELECT name FROM servers ORDER BY name').fetchall()
            self.assertEqual([r['name'] for r in rows], ['FR#61'])

    def test_refresh_reads_aggregate_gluetun_servers_json(self):
        with TemporaryDirectory() as d:
            self._fresh_db(d)
            payload = {
                'version': 1,
                'protonvpn': {
                    'servers': [
                        {
                            'server_name': 'NL#1',
                            'country': 'Netherlands',
                            'hostname': 'nl-01.protonvpn.net',
                            'stream': True,
                        },
                        {
                            'server_name': 'NL#2',
                            'country': 'Netherlands',
                            'hostname': 'nl-02.protonvpn.net',
                            'port_forward': True,
                        },
                    ],
                },
                'airvpn': {'servers': []},
            }
            with open(os.path.join(d, 'servers.json'), 'w', encoding='utf-8') as fh:
                json.dump(payload, fh)

            result = refresh_catalogue(d)

            self.assertTrue(result['ok'])
            self.assertEqual(result['providers']['protonvpn'], 2)
            stream = get_catalogue_entries(
                provider='protonvpn',
                filter_type='country',
                server_type='stream',
            )
            p2p = get_catalogue_entries(
                provider='protonvpn',
                filter_type='country',
                server_type='p2p',
            )
            self.assertEqual([e['value'] for e in stream], ['Netherlands'])
            self.assertEqual([e['value'] for e in p2p], ['Netherlands'])

    def test_local_refresh_prefers_sibling_aggregate_servers_json(self):
        with TemporaryDirectory() as d:
            self._fresh_db(d)
            servers_dir = os.path.join(d, 'servers')
            os.mkdir(servers_dir)
            aggregate = {
                'version': 1,
                'protonvpn': {
                    'servers': [
                        {
                            'server_name': 'FR#109',
                            'country': 'France',
                            'hostname': 'node-fr-17.protonvpn.net',
                            'port_forward': True,
                        },
                    ],
                },
            }
            provider = {
                'servers': [
                    {
                        'server_name': 'FR#440',
                        'country': 'France',
                        'hostname': 'node-fr-33.protonvpn.net',
                        'port_forward': True,
                    },
                ],
            }
            with open(os.path.join(d, 'servers.json'), 'w', encoding='utf-8') as fh:
                json.dump(aggregate, fh)
            with open(os.path.join(servers_dir, 'protonvpn.json'), 'w', encoding='utf-8') as fh:
                json.dump(provider, fh)

            self.assertEqual(local_catalogue_candidates(servers_dir), [d, servers_dir])
            result = refresh_catalogue_from_local(servers_dir)

            self.assertTrue(result['ok'])
            self.assertEqual(result['source'], 'local')
            self.assertEqual(result['servers_dir'], d)
            self.assertEqual(result['providers']['protonvpn'], 1)
            p2p = get_catalogue_entries(
                provider='protonvpn',
                filter_type='name',
                server_type='p2p',
            )
            self.assertEqual([e['value'] for e in p2p], ['FR#109'])


if __name__ == '__main__':
    unittest.main()
