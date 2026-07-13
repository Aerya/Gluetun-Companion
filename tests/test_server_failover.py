import os
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from flask import Flask

from app import database, scheduler
from app.server_eligibility import excluded_server_names, parse_excluded_countries


class ServerEligibilityTest(unittest.TestCase):
    def test_country_setting_is_normalized_and_malformed_json_is_safe(self):
        self.assertEqual(parse_excluded_countries('["fr", "GB", ""]'), {'FR', 'GB'})
        self.assertEqual(parse_excluded_countries('not-json'), set())

    def test_country_resolution_uses_catalogue_and_airvpn_snapshot(self):
        with TemporaryDirectory() as directory:
            database.init_db(os.path.join(directory, 'test.db'))
            with database.get_db() as db:
                db.execute(
                    "INSERT INTO gluetun_catalogue (provider, name, country, country_code) "
                    "VALUES ('airvpn', 'Paris', 'France', 'FR')"
                )
                db.execute(
                    "INSERT INTO airvpn_snapshot (name, country, country_code) "
                    "VALUES ('London', 'United Kingdom', 'GB')"
                )
                self.assertEqual(
                    excluded_server_names(db, {'FR', 'GB'}), {'Paris', 'London'}
                )

    def test_failover_candidate_stays_in_profile_and_excludes_countries(self):
        with TemporaryDirectory() as directory:
            database.init_db(os.path.join(directory, 'test.db'))
            profile_id = database.create_vpn_profile('AirVPN', 'airvpn', {})
            database.set_setting('excluded_countries', '["FR"]')
            with database.get_db() as db:
                db.executemany(
                    'INSERT INTO servers (name, vpn_profile_id) VALUES (?, ?)',
                    [('Current', profile_id), ('FastFR', profile_id), ('SafeNL', profile_id)],
                )
                db.executemany(
                    'INSERT INTO airvpn_snapshot (name, country, country_code) VALUES (?, ?, ?)',
                    [('FastFR', 'France', 'FR'), ('SafeNL', 'Netherlands', 'NL')],
                )
                db.executemany(
                    'INSERT INTO speed_tests (server_name, download_mbps, success, test_method) '
                    'VALUES (?, ?, 1, "sidecar")',
                    [('FastFR', 900.0), ('SafeNL', 400.0)],
                )

            candidate = scheduler._select_failover_candidate('Current')
            self.assertEqual(candidate['name'], 'SafeNL')
            self.assertEqual(candidate['vpn_profile_id'], profile_id)


class FailoverWatchdogTest(unittest.TestCase):
    def setUp(self):
        scheduler._gluetun_unhealthy_since = None
        scheduler._failover_last_attempt = 0.0
        scheduler._failover_failed_servers.clear()
        self.app = Flask(__name__)
        self.app.config['GLUETUN_CONTAINER'] = 'gluetun'

    @patch('app.scheduler._run_emergency_failover', return_value=True)
    @patch('app.scheduler.time.time', return_value=200.0)
    @patch('docker.from_env')
    @patch('app.database.get_setting')
    def test_unhealthy_after_grace_triggers_failover_even_when_auto_switch_is_off(
        self, get_setting, from_env, _time, run_failover,
    ):
        values = {
            'failover_enabled': '1',
            'failover_unhealthy_grace_seconds': '90',
            'failover_cooldown_seconds': '600',
            'benchmark_running': '0',
            'auto_switch': '0',
        }
        get_setting.side_effect = lambda key, default='': values.get(key, default)
        container = MagicMock(status='running')
        container.attrs = {'State': {'Status': 'running', 'Health': {'Status': 'unhealthy'}}}
        from_env.return_value.containers.get.return_value = container
        scheduler._gluetun_unhealthy_since = 100.0

        scheduler._check_gluetun_failover(self.app)

        run_failover.assert_called_once_with(self.app, 'running/unhealthy')
        self.assertIsNone(scheduler._gluetun_unhealthy_since)

    @patch('app.scheduler._run_emergency_failover')
    @patch('app.scheduler.time.time', return_value=150.0)
    @patch('docker.from_env')
    @patch('app.database.get_setting')
    def test_grace_period_prevents_premature_switch(
        self, get_setting, from_env, _time, run_failover,
    ):
        values = {
            'failover_enabled': '1',
            'failover_unhealthy_grace_seconds': '90',
            'failover_cooldown_seconds': '600',
        }
        get_setting.side_effect = lambda key, default='': values.get(key, default)
        container = MagicMock(status='running')
        container.attrs = {'State': {'Status': 'running', 'Health': {'Status': 'unhealthy'}}}
        from_env.return_value.containers.get.return_value = container
        scheduler._gluetun_unhealthy_since = 100.0

        scheduler._check_gluetun_failover(self.app)

        run_failover.assert_not_called()


if __name__ == '__main__':
    unittest.main()
