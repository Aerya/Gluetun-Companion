import os
import unittest
from tempfile import TemporaryDirectory

from app import database
from app.rotation_pools import resolve_pool_servers


class RotationPoolCountryExclusionTest(unittest.TestCase):
    def test_global_country_exclusions_apply_to_manual_pool_rotations(self):
        with TemporaryDirectory() as directory:
            database.init_db(os.path.join(directory, 'test.db'))
            database.set_setting('excluded_countries', '["FR"]')
            with database.get_db() as db:
                db.executemany(
                    'INSERT INTO servers (name, enabled) VALUES (?, 1)',
                    [('Paris',), ('Amsterdam',)],
                )
                db.executemany(
                    'INSERT INTO airvpn_snapshot (name, country, country_code) VALUES (?, ?, ?)',
                    [('Paris', 'France', 'FR'), ('Amsterdam', 'Netherlands', 'NL')],
                )

            pool_id = database.create_rotation_pool(
                name='Tous les serveurs', criteria=[{'crit_type': 'all'}]
            )

            automatic = resolve_pool_servers(pool_id, automatic=True)
            manual = resolve_pool_servers(pool_id, automatic=False)

            self.assertEqual([server['name'] for server in automatic], ['Amsterdam'])
            self.assertEqual([server['name'] for server in manual], ['Amsterdam'])


if __name__ == '__main__':
    unittest.main()
