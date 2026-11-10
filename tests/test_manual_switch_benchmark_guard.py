import json
import inspect
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from contextlib import closing, ExitStack
from unittest.mock import Mock, patch

from flask import Flask
from app import database, manual_switch as manual, scheduler, routes

ROOT = Path(__file__).resolve().parents[1]


class ManualSwitchPriorityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_path = database._db_path
        database._db_path = str(Path(self.tmp.name) / 'test.db')
        with closing(sqlite3.connect(database._db_path)) as db:
            db.executescript("""
                CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT);
                CREATE TABLE servers (id INTEGER PRIMARY KEY, name TEXT);
                INSERT INTO servers VALUES (1, 'Chosen');
            """)
            db.commit()
        self.app = Flask(__name__)
        self.app.secret_key = 'test'
        self.app.register_blueprint(routes.bp)
        self.threads = []
        self.real_thread = threading.Thread

    def tearDown(self):
        for t in self.threads:
            t.join(3)
            self.assertFalse(t.is_alive())
        self.assertFalse(manual.pending())
        self.assertFalse(scheduler._lock.locked())
        database._db_path = self.old_path
        self.tmp.cleanup()
        scheduler._stop_event.clear()

    def thread(self, *args, **kwargs):
        t = self.real_thread(*args, **kwargs)
        self.threads.append(t)
        return t

    def test_scheduled_and_observation_release_before_manual_switch(self):
        for mode in ('benchmark', 'observation'):
            with self.subTest(mode=mode):
                scheduler._lock.acquire()
                database.set_setting('benchmark_running', '1')
                database.set_setting('benchmark_mode', mode)
                called = threading.Event()
                def execute(server_id):
                    self.assertEqual(server_id, 1)
                    self.assertTrue(scheduler._lock.locked())
                    called.set()
                try:
                    with patch.object(manual.threading, 'Thread', side_effect=self.thread):
                        self.assertTrue(manual.submit_switch(self.app, 1, 'Chosen', execute))
                        self.assertTrue(manual.pending())
                        self.assertTrue(scheduler._stop_event.is_set())
                        self.assertFalse(called.is_set())
                        self.assertFalse(manual.submit_switch(self.app, 2, 'Other', execute))
                        self.assertEqual(manual.status()['server'], 'Chosen')
                finally:
                    scheduler._lock.release()
                self.threads[-1].join(3)
                self.assertTrue(called.is_set())
                self.assertEqual(manual.status()['state'], 'connected')
                self.assertEqual(database.get_setting('benchmark_running'), '0')

    def test_post_redirects_while_benchmark_still_holds_lock(self):
        scheduler._lock.acquire()
        try:
            with patch.object(manual.threading, 'Thread', side_effect=self.thread), \
                 patch.object(routes, '_execute_manual_switch') as execute:
                with self.app.test_request_context('/servers/switch/1', method='POST'):
                    response = routes.manual_switch.__wrapped__(1)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(manual.status()['state'], 'queued')
                execute.assert_not_called()
                scheduler._lock.release()
                self.threads[-1].join(3)
                execute.assert_called_once_with(1)
        finally:
            if scheduler._lock.locked():
                scheduler._lock.release()

    def test_preparation_and_reconnection_errors_release_everything(self):
        for phase in ('switching', 'reconnecting'):
            def execute(_):
                manual.update_status(phase)
                raise RuntimeError('private error detail')
            with patch.object(manual.threading, 'Thread', side_effect=self.thread):
                manual.submit_switch(self.app, 1, 'Chosen', execute)
            self.threads[-1].join(3)
            self.assertEqual(manual.status()['state'],
                             'reconnect_failed' if phase == 'reconnecting' else 'failed')
            self.assertNotIn('private', json.dumps(manual.status()))
            self.assertFalse(manual.pending())
            self.assertFalse(scheduler._lock.locked())
            self.assertEqual(database.get_setting('benchmark_running'), '0')

    def test_timeout_does_not_unlock_or_clear_live_benchmark(self):
        database.set_setting('benchmark_running', '1')
        lock = Mock()
        lock.acquire.return_value = False
        execute = Mock()
        with patch.object(scheduler, '_lock', lock), \
             patch.object(manual.threading, 'Thread', side_effect=self.thread):
            manual.submit_switch(self.app, 1, 'Chosen', execute)
            self.threads[-1].join(3)
        execute.assert_not_called()
        lock.release.assert_not_called()
        self.assertEqual(manual.status()['state'], 'timeout')
        self.assertEqual(database.get_setting('benchmark_running'), '1')

    def test_start_failure_releases_reservation_and_restart_marks_interrupted(self):
        with patch.object(manual.threading, 'Thread') as thread:
            thread.return_value.start.side_effect = RuntimeError('cannot start')
            with self.assertRaises(RuntimeError):
                manual.submit_switch(self.app, 1, 'Chosen', Mock())
        self.assertEqual(manual.status()['state'], 'failed')
        self.assertFalse(manual.pending())
        for state in ('queued', 'switching', 'reconnecting'):
            manual.update_status(state)
            manual.recover_interrupted()
            self.assertEqual(manual.status()['state'], 'interrupted')

    def test_queued_automatic_job_cannot_run_after_manual_completion(self):
        # The lock acquisition represents a queued job waking after a manual
        # request was accepted and completed. Pending is already false then.
        class DelayedLock:
            def __enter__(self):
                manual._generation += 1
            def __exit__(self, *args):
                pass
        with patch.object(scheduler, '_lock', DelayedLock()), \
             patch.object(scheduler, '_do_benchmark') as benchmark:
            scheduler.run_benchmark_now(self.app)
        benchmark.assert_not_called()

    def test_automatic_job_does_not_start_during_manual_request(self):
        manual._pending.set()
        try:
            with patch.object(scheduler, '_do_benchmark') as benchmark:
                scheduler.run_benchmark_now(self.app)
            benchmark.assert_not_called()
        finally:
            manual._pending.clear()

    def test_cancelled_proxy_worker_is_joined_before_return(self):
        from concurrent.futures import TimeoutError
        future = Mock()
        future.result.side_effect = TimeoutError()
        executor = Mock()
        executor.submit.return_value = future
        scheduler._stop_event.set()
        args = {name: 1 for name in inspect.signature(
            scheduler._test_server_with_retry).parameters}
        args.update(server_name='Candidate', max_retries=0, timeout_secs=30)
        with patch.object(scheduler, 'ThreadPoolExecutor', return_value=executor):
            self.assertIsNone(scheduler._test_server_with_retry(**args))
        executor.shutdown.assert_called_once_with(wait=True, cancel_futures=True)

    def test_real_switch_worker_reconciles_before_success_and_reports_vpn_failure(self):
        with database.get_db() as db:
            db.executescript("""
                ALTER TABLE servers ADD COLUMN filter_type TEXT DEFAULT 'name';
                ALTER TABLE servers ADD COLUMN vpn_profile_id INTEGER;
                CREATE TABLE vpn_profiles (id INTEGER PRIMARY KEY, provider TEXT);
                CREATE TABLE switches (
                    id INTEGER PRIMARY KEY, from_server TEXT, to_server TEXT,
                    reason TEXT, success INTEGER, connect_secs REAL,
                    to_ipv4 TEXT, to_ipv6 TEXT);
            """)
        self.app.config.update(GLUETUN_CONTAINER='vpn', COMPOSE_DIR='/compose')
        for vpn_ok, dependents in ((True, ['client']), (False, ['client']), (True, [])):
            with ExitStack() as stack:
                mocks = {}
                for name, value in {
                    'app.routes.get_active_server': 'Previous',
                    'app.routes.get_gluetun_provider': 'airvpn',
                    'app.routes.get_public_ips': (None, None),
                    'app.gluetun.list_network_dependents_for_recreate': ['client'],
                    'app.gluetun.pull_gluetun_before_switch': [],
                    'app.gluetun.restart_configured_post_switch_containers': ([], []),
                    'app.routes.switch_server': (True, ''),
                    'app.routes.wait_for_vpn': (vpn_ok, 1),
                    'app.routes.restart_network_dependents': (dependents, []),
                    'app.routes.apply_current_provider_port_forwards': {},
                    'app.routes._invalidate_vpn_snapshot': None,
                }.items():
                    mocks[name] = stack.enter_context(patch(name, return_value=value))
                docker = stack.enter_context(patch('docker.from_env'))
                docker.return_value.containers.get.return_value.status = 'running'
                stack.enter_context(patch.object(manual.threading, 'Thread', side_effect=self.thread))
                manual.submit_switch(self.app, 1, 'Chosen', routes._execute_manual_switch)
                self.threads[-1].join(3)
                self.assertEqual(manual.status()['state'],
                                 'connected' if vpn_ok and dependents else 'reconnect_failed')
                mocks['app.routes.restart_network_dependents'].assert_called_once()
                self.assertFalse(scheduler._lock.locked())

    def test_status_requires_login(self):
        with self.app.test_client() as client:
            self.assertEqual(client.get('/api/manual-switch/status').status_code, 302)

    def test_proxy_restore_has_its_own_enabled_by_default_notification(self):
        source = (ROOT / 'app' / 'scheduler.py').read_text()
        self.assertIn("get_setting('notif_proxy_test_revert', '1') == '1'", source)
        self.assertIn("alert_type='proxy_test_revert'", source)


if __name__ == '__main__':
    unittest.main()
