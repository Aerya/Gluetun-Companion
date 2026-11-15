"""Docker exec behind a socket proxy that refuses it (docker-socket-proxy EXEC=0).

Regression: every refused attempt used to leave an unstarted exec instance in
dockerd, thousands per day, and a denied ``wg0.conf`` check was reported as
"absent".  Exec must not be created while it is refused, and must resume on
its own once permission is granted.
"""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import docker

from app import docker_exec
from app.docker_exec import ALLOWED, DENIED, UNKNOWN, run_in_container
from app.gluetun import (
    WG_CONFIG_ABSENT, WG_CONFIG_PRESENT, WG_CONFIG_UNKNOWN,
    _active_server_cache, get_active_server, get_active_server_info,
    has_wireguard_config_file, wireguard_config_file_state,
)


def api_error(status):
    response = SimpleNamespace(status_code=status, reason='', url='')
    if status == 404:
        return docker.errors.NotFound('No such exec instance', response=response)
    return docker.errors.APIError(f'HTTP {status}', response=response)


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class FakeDocker:
    """Low-level API + container emulating a proxy whose EXEC flag can change."""

    def __init__(self, exec_allowed=False):
        self.exec_allowed = exec_allowed
        self.created = 0        # exec instances created (abandoned when not started)
        self.started = 0
        self.probes = 0
        self.api = MagicMock()
        self.api.base_url = 'http+docker://fake'
        self.api.exec_start.side_effect = self._exec_start
        self.container = MagicMock()
        self.container.client.api = self.api
        self.container.exec_run.side_effect = self._exec_run
        self.exit_code = 0
        self.output = b''

    def _exec_start(self, exec_id, *a, **kw):
        self.probes += 1
        if not self.exec_allowed:
            raise api_error(403)
        raise api_error(404)    # probe ID never exists

    def _exec_run(self, cmd, **kw):
        self.created += 1       # POST /containers/{id}/exec is allowed by CONTAINERS=1
        if not self.exec_allowed:
            raise api_error(403)
        self.started += 1
        return SimpleNamespace(exit_code=self.exit_code, output=self.output)


class GateTestCase(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        p = patch.object(docker_exec, '_now', self.clock)
        p.start()
        self.addCleanup(p.stop)

    def advance(self, secs):
        self.clock.t += secs


class ExecGateTest(GateTestCase):
    def test_denied_creates_no_exec_and_is_not_retried_every_call(self):
        fake = FakeDocker(exec_allowed=False)
        for _ in range(500):
            self.assertEqual(run_in_container(fake.container, ['true']).status, 'denied')
            self.advance(1)    # 500 s of polling
        self.assertEqual(fake.created, 0)
        # One probe at start, one re-check after DENIED_RECHECK_SECS.
        self.assertEqual(fake.probes, 2)

    def test_recovers_automatically_when_exec_is_granted(self):
        fake = FakeDocker(exec_allowed=False)
        self.assertEqual(run_in_container(fake.container, ['true']).status, 'denied')
        fake.exec_allowed = True         # operator sets EXEC=1, Companion keeps running
        self.advance(docker_exec.DENIED_RECHECK_SECS - 1)
        self.assertEqual(run_in_container(fake.container, ['true']).status, 'denied')
        self.assertEqual(fake.created, 0)
        self.advance(1)
        outcome = run_in_container(fake.container, ['true'])
        self.assertTrue(outcome.ran)
        self.assertEqual(outcome.exit_code, 0)
        self.assertEqual((fake.created, fake.started), (1, 1))
        self.assertEqual(docker_exec.gate_for(fake.api).state, ALLOWED)

    def test_revoked_permission_leaves_at_most_one_abandoned_exec(self):
        fake = FakeDocker(exec_allowed=True)
        self.assertTrue(run_in_container(fake.container, ['true']).ran)
        fake.exec_allowed = False        # EXEC=1 removed while allowed state is cached
        for _ in range(50):
            self.assertEqual(run_in_container(fake.container, ['true']).status, 'denied')
        self.assertEqual(fake.created, 2)   # the successful one + one refused
        self.assertEqual(docker_exec.gate_for(fake.api).state, DENIED)

    def test_unreachable_docker_is_unknown_and_retried_soon(self):
        api = MagicMock(base_url='tcp://socket-proxy:2375')
        api.exec_start.side_effect = docker.errors.DockerException('connection refused')
        gate = docker_exec.gate_for(api)
        self.assertEqual(gate.check(api), UNKNOWN)
        self.assertEqual(gate.check(api), UNKNOWN)
        self.assertEqual(api.exec_start.call_count, 1)
        self.advance(docker_exec.UNKNOWN_RECHECK_SECS)
        api.exec_start.side_effect = api_error(404)
        self.assertEqual(gate.check(api), ALLOWED)

    def test_probe_targets_an_impossible_exec_id(self):
        fake = FakeDocker(exec_allowed=True)
        docker_exec.gate_for(fake.api).check(fake.api)
        (exec_id,), _ = fake.api.exec_start.call_args
        self.assertRegex(exec_id, r'^0{64}$')


    def test_405_refusal_is_denied(self):
        api = MagicMock(base_url='tcp://other-proxy:2375')
        api.exec_start.side_effect = api_error(405)
        self.assertEqual(docker_exec.gate_for(api).check(api), DENIED)

    def test_endpoints_keep_separate_permissions(self):
        main = FakeDocker(exec_allowed=False)
        main.api.base_url = 'tcp://socket-proxy:2375'
        dedicated = FakeDocker(exec_allowed=True)
        dedicated.api.base_url = 'tcp://traffic-proxy:2375'
        self.assertEqual(run_in_container(main.container, ['true']).status, 'denied')
        self.assertTrue(run_in_container(dedicated.container, ['true']).ran)
        self.assertEqual(run_in_container(main.container, ['true']).status, 'denied')
        self.assertEqual((main.created, dedicated.created), (0, 1))

    def test_concurrent_callers_share_one_probe(self):
        import threading
        fake = FakeDocker(exec_allowed=False)
        barrier = threading.Barrier(8)

        def call():
            barrier.wait()
            run_in_container(fake.container, ['true'])

        threads = [threading.Thread(target=call) for _ in range(8)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        self.assertEqual((fake.probes, fake.created), (1, 0))


class WireguardConfigStateTest(GateTestCase):
    def _patched(self, fake, mounts=()):
        fake.container.attrs = {'Mounts': list(mounts)}
        p = patch('app.gluetun.docker.from_env')
        from_env = p.start()
        self.addCleanup(p.stop)
        from_env.return_value.containers.get.return_value = fake.container

    def test_denied_exec_is_unknown_not_absent(self):
        fake = FakeDocker(exec_allowed=False)
        self._patched(fake)
        self.assertEqual(wireguard_config_file_state('gluetun'), WG_CONFIG_UNKNOWN)
        self.assertFalse(has_wireguard_config_file('gluetun'))
        self.assertEqual(fake.created, 0)

    def test_exit_codes_map_to_present_and_absent(self):
        fake = FakeDocker(exec_allowed=True)
        self._patched(fake)
        fake.exit_code = 0
        self.assertEqual(wireguard_config_file_state('gluetun'), WG_CONFIG_PRESENT)
        fake.exit_code = 1
        self.assertEqual(wireguard_config_file_state('gluetun'), WG_CONFIG_ABSENT)
        fake.exit_code = 127
        self.assertEqual(wireguard_config_file_state('gluetun'), WG_CONFIG_UNKNOWN)

    def test_direct_mount_is_present_without_exec(self):
        fake = FakeDocker(exec_allowed=False)
        self._patched(fake, mounts=[{'Destination': '/gluetun/wireguard/wg0.conf'}])
        self.assertEqual(wireguard_config_file_state('gluetun'), WG_CONFIG_PRESENT)
        self.assertEqual((fake.probes, fake.created), (0, 0))

    def test_docker_unreachable_is_unknown(self):
        with patch('app.gluetun.docker.from_env', side_effect=docker.errors.DockerException('x')):
            self.assertEqual(wireguard_config_file_state('gluetun'), WG_CONFIG_UNKNOWN)

    def test_check_recovers_after_permission_is_granted(self):
        fake = FakeDocker(exec_allowed=False)
        self._patched(fake)
        self.assertEqual(wireguard_config_file_state('gluetun'), WG_CONFIG_UNKNOWN)
        fake.exec_allowed = True
        fake.exit_code = 1
        self.advance(docker_exec.DENIED_RECHECK_SECS)
        self.assertEqual(wireguard_config_file_state('gluetun'), WG_CONFIG_ABSENT)


class ActiveServerSourceTest(GateTestCase):
    def setUp(self):
        super().setUp()
        _active_server_cache.clear()
        self.addCleanup(_active_server_cache.clear)

    def _patched(self, fake, server_names):
        fake.container.id = 'gluetun-id'
        fake.container.attrs = {'Config': {'Env': [
            'VPN_SERVICE_PROVIDER=airvpn', f'SERVER_NAMES={server_names}',
        ]}}
        fake.container.logs.return_value = b'INFO [wireguard] Connecting to 198.54.134.251:1637\n'
        fake.output = json.dumps({'servers': [
            {'server_name': 'Bunda', 'ips': ['198.54.134.251']},
        ]}).encode()
        p = patch('app.gluetun.docker.from_env')
        from_env = p.start()
        self.addCleanup(p.stop)
        from_env.return_value.containers.get.return_value = fake.container

    def test_catalogue_match_is_verified(self):
        fake = FakeDocker(exec_allowed=True)
        self._patched(fake, 'Chamukuy,Bunda')
        info = get_active_server_info('gluetun-airvpn')
        self.assertEqual(info, {'name': 'Bunda', 'source': 'catalogue', 'verified': True})
        self.assertEqual(get_active_server('gluetun-airvpn'), 'Bunda')

    def test_single_filter_fallback_is_not_verified(self):
        fake = FakeDocker(exec_allowed=False)
        self._patched(fake, 'Bunda')
        info = get_active_server_info('gluetun-airvpn')
        self.assertEqual(info, {'name': 'Bunda', 'source': 'configured', 'verified': False})
        self.assertEqual(fake.created, 0)

    @patch('app.gluetun.get_setting', return_value='Chamukuy')
    def test_observed_fallback_is_not_verified(self, _setting):
        fake = FakeDocker(exec_allowed=False)
        self._patched(fake, 'Chamukuy,Bunda')
        info = get_active_server_info('gluetun-airvpn')
        self.assertEqual(info, {'name': 'Chamukuy', 'source': 'observed', 'verified': False})

    @patch('app.gluetun.get_setting', return_value='')
    def test_nothing_known(self, _setting):
        fake = FakeDocker(exec_allowed=False)
        self._patched(fake, 'Chamukuy,Bunda')
        self.assertEqual(get_active_server_info('gluetun-airvpn'),
                         {'name': None, 'source': None, 'verified': False})

    def test_repeated_polling_while_denied_creates_no_exec(self):
        fake = FakeDocker(exec_allowed=False)
        self._patched(fake, 'Bunda')
        for _ in range(200):
            get_active_server_info('gluetun-airvpn')
            self.advance(5)    # dashboard poll interval
        self.assertEqual(fake.created, 0)
        self.assertLessEqual(fake.probes, 1 + 1000 // int(docker_exec.DENIED_RECHECK_SECS))

    def test_verified_after_permission_is_granted(self):
        fake = FakeDocker(exec_allowed=False)
        self._patched(fake, 'Chamukuy,Bunda')
        with patch('app.gluetun.get_setting', return_value=''):
            self.assertFalse(get_active_server_info('gluetun-airvpn')['verified'])
        fake.exec_allowed = True
        self.advance(docker_exec.DENIED_RECHECK_SECS)
        self.assertEqual(get_active_server_info('gluetun-airvpn'),
                         {'name': 'Bunda', 'source': 'catalogue', 'verified': True})


class ExecStateSurfaceTest(unittest.TestCase):
    """The pages and APIs tell a verified server from a fallback and show
    an unknown wg0.conf check instead of hiding it."""

    def setUp(self):
        import os
        import tempfile
        from app import database
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        # create_app() repoints the module-level database path; restore it
        # before the temporary directory disappears.
        self.addCleanup(setattr, database, '_db_path', database._db_path)
        env = patch.dict(os.environ, {
            'SECRET_KEY': 'test-' + 'k' * 40, 'DATA_DIR': self._tmp.name,
            'GLUETUN_CONTAINER': 'gluetun-test', 'DOCKER_HOST': 'tcp://127.0.0.1:1',
            'METRICS_TOKEN': '',
        })
        env.start()
        self.addCleanup(env.stop)
        for target in ('app.scheduler.start_scheduler', 'app.gluetun.cleanup_test_containers'):
            p = patch(target)
            p.start()
            self.addCleanup(p.stop)
        p = patch('app._cleanup_hooks_registered', True)
        p.start()
        self.addCleanup(p.stop)
        from app import create_app
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        with self.client.session_transaction() as sess:
            sess['logged_in'] = True
            sess['username'] = 'admin'
            sess['_csrf_token'] = 'csrf-test'
        for target, value in (('app.routes.probe_status', ('running', '1.2.3.4')),
                              ('app.routes.get_current_filters', {'name': 'Chamukuy,Bunda'})):
            p = patch(target, return_value=value)
            p.start()
            self.addCleanup(p.stop)

    def _active(self, info):
        p = patch('app.routes.get_active_server_info', return_value=info)
        p.start()
        self.addCleanup(p.stop)
        from app.caching import cache
        cache.clear()

    def test_api_status_exposes_verification(self):
        from app import database
        database.set_setting('api_token', 'tok')
        hdr = {'Authorization': 'Bearer tok'}
        for info in ({'name': 'Bunda', 'source': 'catalogue', 'verified': True},
                     {'name': 'Bunda', 'source': 'configured', 'verified': False}):
            with patch('app.gluetun.get_active_server_info', return_value=info), \
                 patch('app.gluetun.get_vpn_status', return_value='running'), \
                 patch('app.gluetun.get_current_filters', return_value={}), \
                 patch('app.dns_path.get_dns_path', return_value={}):
                resp = self.client.get('/api/v1/status', headers=hdr)
            self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True)[:300])
            data = resp.get_json()
            self.assertEqual(data['active_server'], 'Bunda')
            self.assertEqual(data['active_server_source'], info['source'])
            self.assertIs(data['active_server_verified'], info['verified'])

    def test_webui_status_snapshot_exposes_verification(self):
        self._active({'name': 'Bunda', 'source': 'observed', 'verified': False})
        data = self.client.get('/api/status').get_json()
        self.assertEqual(data['current_server'], 'Bunda')
        self.assertIs(data['current_server_verified'], False)

    def test_dashboard_marks_unverified_server(self):
        from app.i18n import TRANSLATIONS
        label = TRANSLATIONS['fr']['dash_active_server_unverified']
        self._active({'name': 'Bunda', 'source': 'configured', 'verified': False})
        html = self.client.get('/').get_data(as_text=True)
        self.assertIn(label, html)

    def test_dashboard_has_no_mark_for_verified_server(self):
        from app.i18n import TRANSLATIONS
        label = TRANSLATIONS['fr']['dash_active_server_unverified']
        self._active({'name': 'Bunda', 'source': 'catalogue', 'verified': True})
        html = self.client.get('/').get_data(as_text=True)
        self.assertNotIn(label, html)

    def test_servers_page_shows_unknown_wg0_check(self):
        from app.i18n import TRANSLATIONS
        t = TRANSLATIONS['fr']
        with patch('app.routes.wireguard_config_file_state', return_value=WG_CONFIG_UNKNOWN):
            html = self.client.get('/servers').get_data(as_text=True)
        self.assertIn(t['srv_wg0_config_unknown_title'], html)
        self.assertNotIn(t['srv_wg0_config_warning_title'], html)
        with patch('app.routes.wireguard_config_file_state', return_value=WG_CONFIG_ABSENT):
            html = self.client.get('/servers').get_data(as_text=True)
        self.assertNotIn(t['srv_wg0_config_unknown_title'], html)

    def test_translations_exist_in_both_languages(self):
        from app.i18n import TRANSLATIONS
        for key in ('dash_active_server_unverified', 'dash_active_server_unverified_hint',
                    'srv_wg0_config_unknown_title', 'srv_wg0_config_unknown'):
            for lang in ('fr', 'en'):
                self.assertTrue(TRANSLATIONS[lang][key].strip(), f'{lang}.{key}')


if __name__ == '__main__':
    unittest.main()
