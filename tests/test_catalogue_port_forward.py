import json
import os
import unittest
from tempfile import TemporaryDirectory

from app import database
from app.catalogue import get_catalogue_entries, import_to_servers, refresh_catalogue


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


if __name__ == '__main__':
    unittest.main()
