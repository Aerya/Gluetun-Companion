"""Regression coverage for Gluetun's current public server schema."""

import os
import unittest
from tempfile import TemporaryDirectory

from app import database
from app.catalogue import _normalize_server_list, _providers_with_blank_catalogue_names


class CatalogueServerNamesTest(unittest.TestCase):
    def test_hostname_is_a_stable_fallback_for_unnamed_public_servers(self):
        servers = _normalize_server_list([
            {
                'country': 'Albania',
                'city': 'Tirana',
                'hostname': 'al-tia-wg-001',
                'ips': ['103.124.165.2'],
            },
            {
                'country': 'Albania',
                'city': 'Tirana',
                'hostname': 'al-tia-wg-002',
                'ips': ['103.124.165.3'],
            },
        ])

        self.assertEqual([server['name'] for server in servers], [
            'al-tia-wg-001', 'al-tia-wg-002',
        ])

    def test_blank_legacy_names_mark_a_provider_for_a_new_baseline(self):
        previous_db_path = database._db_path
        try:
            with TemporaryDirectory() as directory:
                database.init_db(os.path.join(directory, 'test.db'))
                with database.get_db() as db:
                    db.execute(
                        "INSERT INTO gluetun_catalogue (provider, name) VALUES (?, ?)",
                        ('mullvad', ''),
                    )
                    self.assertEqual(_providers_with_blank_catalogue_names(db), {'mullvad'})
        finally:
            database._db_path = previous_db_path


if __name__ == '__main__':
    unittest.main()
