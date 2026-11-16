from unittest.mock import patch

import pytest
from flask import Flask

from app import database, scheduler


@pytest.fixture
def observation_db(tmp_path):
    old = database._db_path
    database.init_db(str(tmp_path / 'observation.db'))
    database.set_setting('continuous_observation', '1')
    with database.get_db() as db:
        db.execute("INSERT INTO servers (name, filter_type) VALUES ('Candidate', 'name')")
        db.execute("INSERT INTO airvpn_snapshot (name, load, users, country_code) VALUES ('Candidate', 95, 100, 'US')")
    yield
    database._db_path = old
    scheduler._observation_watchdog_state = None


@pytest.mark.parametrize('setting,value', [
    ('excluded_countries', '["US"]'),
    ('bench_include_types', '["country"]'),
    ('airvpn_bench_max_load', '80'),
    ('airvpn_bench_max_users', '50'),
])
def test_filtered_candidates_do_not_restart_observation(observation_db, setting, value):
    database.set_setting(setting, value)
    app = Flask(__name__)
    with patch.object(scheduler, 'trigger_observation_now') as trigger, \
         patch('app.catalogue.refresh_catalogue_from_sidecar') as catalogue:
        for _ in range(12):
            scheduler._check_continuous_observation(app)
        assert scheduler._do_benchmark(app, observation=True) == 0
        trigger.assert_not_called()
        catalogue.assert_not_called()
        assert database.get_setting('benchmark_running', '0') == '0'
        # Removing a filter resumes automatically; no persistent backoff/disable.
        database.set_setting(setting, '[]' if value.startswith('[') else '0')
        scheduler._check_continuous_observation(app)
        trigger.assert_called_once_with(app)


def test_snapshot_change_resumes_and_missing_data_keeps_candidate(observation_db):
    database.set_setting('airvpn_bench_max_load', '80')
    assert not scheduler._has_observation_work_left()
    with database.get_db() as db:
        db.execute("UPDATE airvpn_snapshot SET load=70")
    assert scheduler._has_observation_work_left()
    with database.get_db() as db:
        db.execute("DELETE FROM airvpn_snapshot")
    assert scheduler._has_observation_work_left()


def test_disabled_profiles_and_orphans_do_not_trigger(observation_db):
    with database.get_db() as db:
        db.execute("INSERT INTO vpn_profiles (id,name,provider,enabled) VALUES (1,'Disabled','airvpn',0), (2,'Enabled','airvpn',1)")
        db.execute("UPDATE servers SET vpn_profile_id=1")
    assert not scheduler._has_observation_work_left()
    with database.get_db() as db:
        db.execute("UPDATE servers SET vpn_profile_id=2")
        db.execute("INSERT INTO servers (name) VALUES ('Orphan')")
    assert [s['name'] for s in scheduler._observation_candidate_servers()] == ['Candidate']
