import json
import unittest
from unittest.mock import MagicMock, patch

from app.gluetun import (
    _compose_recreate,
    _verify_attached,
    list_network_dependents,
    list_orphaned_network_dependents,
    record_gluetun_id,
    restart_network_dependents,
)


def _container(name, cid, network_mode='', running=True):
    c = MagicMock()
    c.name = name
    c.id = cid
    c.attrs = {
        'HostConfig': {'NetworkMode': network_mode},
        'State': {'Running': running},
    }
    return c


def _client_with(containers, broken=None):
    """Wire a MagicMock client the way _list_containers_safe reads the daemon:
    an ``api.containers()`` listing plus a ``containers.get()`` per entry.
    *broken* maps a container ID to the error its inspect raises.
    """
    broken = dict(broken or {})
    by_key = {}
    for c in containers:
        by_key[c.id] = c
        by_key[c.name] = c

    def _get(key):
        if key in broken:
            raise Exception(broken[key])
        return by_key[key]

    client = MagicMock()
    client.api.containers.return_value = (
        [{'Id': c.id, 'Names': [f'/{c.name}']} for c in containers]
        + [{'Id': cid, 'Names': ['/corrupt']} for cid in broken]
    )
    client.containers.get.side_effect = _get
    return client


class NetworkDependentsTest(unittest.TestCase):
    @patch('app.gluetun.record_gluetun_id')
    @patch('docker.from_env')
    def test_network_dependents_ignore_stopped_containers(self, from_env, _record):
        from_env.return_value = _client_with([
            _container('gluetun', 'gluetun-full-id', 'bridge'),
            _container('qbittorrent', 'qbit-id', 'container:gluetun', running=True),
            _container('prowlarr', 'prowlarr-id', 'container:gluetun-full-id', running=True),
            _container('helper', 'helper-id', 'container:gluetun', running=False),
        ])

        deps = list_network_dependents('gluetun')

        self.assertEqual(deps, ['prowlarr', 'qbittorrent'])

    @patch('app.gluetun.record_dependent_names')
    @patch('app.gluetun.record_gluetun_id')
    @patch('docker.from_env')
    def test_one_uninspectable_container_does_not_blank_the_scan(
        self, from_env, _record, _record_names,
    ):
        """One container the daemon cannot inspect ("RWLayer ... is unexpectedly
        nil") must not take the whole enumeration down with it, as docker-py's
        containers.list() does."""
        from_env.return_value = _client_with(
            [
                _container('gluetun', 'gluetun-full-id', 'bridge'),
                _container('qbittorrent', 'qbit-id', 'container:gluetun-full-id'),
            ],
            broken={'bdeb063da405': 'RWLayer of container bdeb063da405 is unexpectedly nil'},
        )

        self.assertEqual(list_network_dependents('gluetun'), ['qbittorrent'])

    @patch('app.gluetun._known_gluetun_ids', return_value={'dead-gluetun-id'})
    @patch('app.database.get_setting', return_value='1')
    @patch('docker.from_env')
    def test_orphaned_dependents_ignore_stopped_containers(self, from_env, _get_setting, _known_ids):
        from_env.return_value = _client_with([
            _container('gluetun', 'current-gluetun-id', 'bridge', running=True),
            _container('qbittorrent', 'qbit-id', 'container:dead-gluetun-id', running=True),
            _container('helper', 'helper-id', 'container:dead-gluetun-id', running=False),
        ])

        deps = list_orphaned_network_dependents()

        self.assertEqual(deps, ['qbittorrent'])

    @patch('app.gluetun.record_dependent_names')
    @patch('app.gluetun._known_dependent_names', return_value={'qbittorrent', 'sabnzbd'})
    @patch('app.gluetun._known_gluetun_ids', return_value={'some-other-gluetun-id'})
    @patch('app.database.get_setting', return_value='1')
    @patch('docker.from_env')
    def test_orphan_adopted_by_remembered_name_when_id_rolled_out_of_history(
        self, from_env, _get_setting, _known_ids, _known_deps, _record,
    ):
        """A long benchmark evicts the referenced ID; the name memory must still
        adopt the dependent (regression: containers stranded forever)."""
        from_env.return_value = _client_with([
            _container('gluetun', 'current-gluetun-id', 'bridge', running=True),
            # References an ID no longer in the capped history.
            _container('qbittorrent', 'qbit-id', 'container:evicted-gluetun-id'),
            _container('sabnzbd', 'sab-id', 'container:evicted-gluetun-id'),
            # Never seen attached to Gluetun, unknown ID → not ours to touch.
            _container('other-vpn-app', 'other-id', 'container:unrelated-dead-id'),
        ])

        deps = list_orphaned_network_dependents()

        self.assertEqual(deps, ['qbittorrent', 'sabnzbd'])

    @patch('app.gluetun.record_dependent_names')
    @patch('app.gluetun._known_dependent_names', return_value=set())
    @patch('app.gluetun._known_gluetun_ids', return_value=set())
    @patch('app.database.get_setting', return_value='1')
    @patch('docker.from_env')
    def test_orphan_of_unrelated_stack_is_left_alone(
        self, from_env, _get_setting, _known_ids, _known_deps, _record,
    ):
        client = MagicMock()
        client.containers.list.return_value = [
            _container('other-vpn-app', 'other-id', 'container:unrelated-dead-id'),
        ]
        from_env.return_value = client

        self.assertEqual(list_orphaned_network_dependents(), [])


class OrphanAdoptionScopeTest(unittest.TestCase):
    """The blanket adoption pass must stay a *one-time, pre-history* migration.

    Widening what Companion remembers (name memory, a larger ID cap) must never
    re-open it, or an upgrade would adopt — and recreate — containers belonging
    to an unrelated VPN stack that merely reference a dead container.
    """

    CONTAINERS = [
        _container('gluetun', 'current-gluetun-id', 'bridge'),
        # Ours: the Gluetun ID it points at aged out of the capped history.
        _container('qbittorrent', 'qbit-id', 'container:evicted-gluetun-id'),
        # Someone else's VPN stack, equally dead reference.
        _container('other-vpn-app', 'other-id', 'container:unrelated-dead-id'),
    ]

    def _scan(self, store):
        def _get(key, default=''):
            return store.get(key, default)

        def _set(key, value):
            store[key] = value

        with patch('app.database.get_setting', _get), \
             patch('app.database.set_setting', _set), \
             patch('docker.from_env', return_value=_client_with(self.CONTAINERS)):
            return list_orphaned_network_dependents()

    def test_upgrade_with_migration_done_does_not_rescan_unrelated_stack(self):
        """The reported risk: a database whose legacy migration already ran, on
        the first scan of the new (name-memory) version.  Only keyed orphans."""
        store = {
            'orphan_legacy_adoption_done': '1',
            'gluetun_id_history':          json.dumps(['some-other-gluetun-id']),
            'gluetun_dependent_names':     json.dumps(['qbittorrent']),
        }

        self.assertEqual(self._scan(store), ['qbittorrent'])

    def test_upgrade_with_migration_done_and_empty_name_memory_adopts_nothing(self):
        """Same upgrade, before anything has been recorded under the new key:
        an unmatched dead reference stays untouched rather than being swept up."""
        store = {
            'orphan_legacy_adoption_done': '1',
            'gluetun_id_history':          '[]',
            'gluetun_dependent_names':     '[]',
        }

        self.assertEqual(self._scan(store), [])

    def test_legacy_pass_runs_once_then_stops_adopting_unknowns(self):
        """A pre-history database still gets its one blanket pass — and only one;
        the unrelated container it swept up is not remembered as a dependent."""
        store = {}

        first = self._scan(store)
        self.assertEqual(first, ['other-vpn-app', 'qbittorrent'])
        self.assertEqual(store['orphan_legacy_adoption_done'], '1')
        self.assertEqual(
            json.loads(store.get('gluetun_dependent_names', '[]')), [],
            'legacy-pass guesses must not be promoted into name memory',
        )

        self.assertEqual(self._scan(store), [])

    def test_keyed_orphans_are_remembered_for_the_next_rollover(self):
        store = {
            'orphan_legacy_adoption_done': '1',
            'gluetun_id_history':          json.dumps(['evicted-gluetun-id']),
            'gluetun_dependent_names':     '[]',
        }

        self.assertEqual(self._scan(store), ['qbittorrent'])
        self.assertEqual(
            json.loads(store['gluetun_dependent_names']), ['qbittorrent'],
        )


class GluetunIdHistoryTest(unittest.TestCase):
    def test_history_survives_a_full_benchmark_worth_of_recreates(self):
        """One Gluetun recreate per tested server must not evict the IDs that
        already-orphaned dependents still reference."""
        store = {'gluetun_id_history': '[]'}

        def _get(key, default=''):
            return store.get(key, default)

        def _set(key, value):
            store[key] = value

        with patch('app.database.get_setting', _get), \
             patch('app.database.set_setting', _set):
            record_gluetun_id('the-id-a-broken-dependent-points-at')
            for i in range(60):          # a 60-server benchmark
                record_gluetun_id(f'gluetun-id-{i}')

        history = json.loads(store['gluetun_id_history'])
        self.assertIn('the-id-a-broken-dependent-points-at', history)


class VerifyAttachedTest(unittest.TestCase):
    BEFORE = {'id': 'old-id', 'started': '2026-08-09T13:04:20Z', 'running': True,
              'mode': 'container:gluetun'}

    def _verify(
        self, running=True, started='2026-08-09T16:28:15Z',
        mode='container:gluetun', gluetun_id='current-gluetun-id',
    ):
        after = {'id': 'new-id', 'started': started, 'running': running, 'mode': mode}
        with patch('app.gluetun._dependent_state', return_value=after):
            return _verify_attached('qbittorrent', 'gluetun', gluetun_id, self.BEFORE)

    def test_running_and_restarted_and_correct_namespace_is_attached(self):
        ok, why = self._verify()
        self.assertTrue(ok, why)

    def test_container_that_exited_after_recreate_is_not_attached(self):
        ok, why = self._verify(running=False)
        self.assertFalse(ok)
        self.assertIn('not running', why)

    def test_untouched_container_is_not_attached_despite_matching_name_ref(self):
        """Unraid writes NetworkMode by name, so the reference reads as correct
        even on a container that was never recreated — StartedAt catches it."""
        ok, why = self._verify(started=self.BEFORE['started'])
        self.assertFalse(ok)
        self.assertIn('never restarted', why)

    def test_stale_id_reference_is_not_attached(self):
        ok, why = self._verify(mode='container:4e29eb8d9dde')
        self.assertFalse(ok)
        self.assertIn('not the current Gluetun', why)

    def test_current_gluetun_short_id_reference_is_attached(self):
        ok, why = self._verify(mode='container:current-glue')
        self.assertTrue(ok, why)


class DependentRecreateBackendTest(unittest.TestCase):
    @patch('app.gluetun.time.sleep')
    @patch('app.gluetun._compose_recreate')
    @patch('app.unraid.sdk_recreate')
    @patch('app.gluetun._verify_attached', return_value=(False, 'still detached'))
    @patch('app.gluetun._dependent_state', return_value=None)
    @patch('app.gluetun._management_mode', return_value='unraid')
    @patch('docker.from_env')
    def test_retry_uses_unraid_backend_not_compose(
        self, from_env, _mode, _state, _verify, sdk_recreate, compose_recreate, _sleep,
    ):
        """The retry must not fall back to Compose on a DockerMan host, where
        there is no compose project for it to find."""
        from_env.return_value = MagicMock()

        restarted, _ = restart_network_dependents(
            'gluetun', '', '', explicit_list=['qbittorrent'],
        )

        self.assertEqual(restarted, [])
        self.assertEqual(sdk_recreate.call_count, 2)     # initial + retry
        compose_recreate.assert_not_called()


class ComposeReplacementRecoveryTest(unittest.TestCase):
    @patch('app.gluetun.os.path.isdir', return_value=True)
    @patch('app.gluetun.subprocess.run')
    @patch('docker.from_env')
    def test_created_replacement_is_removed_without_volumes_then_retried(
        self, from_env, run, _isdir,
    ):
        current = MagicMock()
        current.labels = {
            'com.docker.compose.service': 'qbittorrentvpn1',
            'com.docker.compose.project': 'airvpn',
            'com.docker.compose.project.working_dir': '/compose',
        }
        client = MagicMock()
        client.containers.get.return_value = current
        client.api.containers.return_value = [{
            'Id': 'created-id',
            'Names': ['/7cebe17ebeda_qbittorrentvpn1'],
            'Labels': {
                'com.docker.compose.replace': 'qbittorrentvpn1',
                'com.docker.compose.service': 'qbittorrentvpn1',
                'com.docker.compose.project': 'airvpn',
            },
        }]
        from_env.return_value = client
        run.side_effect = [
            MagicMock(
                returncode=1,
                stderr='Error response from daemon: No such container: old_qbittorrentvpn1',
                stdout='',
            ),
            MagicMock(returncode=0, stderr='', stdout=''),
        ]

        _compose_recreate('qbittorrentvpn1', '/compose', 'airvpn')

        self.assertEqual(run.call_count, 2)
        client.api.remove_container.assert_called_once_with(
            'created-id', v=False, force=True,
        )

    @patch('app.gluetun.os.path.isdir', return_value=True)
    @patch('app.gluetun.subprocess.run')
    @patch('docker.from_env')
    def test_unrelated_created_container_is_never_removed(
        self, from_env, run, _isdir,
    ):
        current = MagicMock()
        current.labels = {
            'com.docker.compose.service': 'qbittorrentvpn1',
            'com.docker.compose.project': 'airvpn',
            'com.docker.compose.project.working_dir': '/compose',
        }
        client = MagicMock()
        client.containers.get.return_value = current
        client.api.containers.return_value = [{
            'Id': 'unrelated-id',
            'Names': ['/temporary_other_service'],
            'Labels': {
                'com.docker.compose.replace': 'other-service',
                'com.docker.compose.service': 'other-service',
                'com.docker.compose.project': 'airvpn',
            },
        }]
        from_env.return_value = client
        run.return_value = MagicMock(
            returncode=1,
            stderr='Error response from daemon: No such container: missing',
            stdout='',
        )

        with self.assertRaises(RuntimeError):
            _compose_recreate('qbittorrentvpn1', '/compose', 'airvpn')

        client.api.remove_container.assert_not_called()


    @patch('app.gluetun.os.path.isdir', return_value=True)
    @patch('app.gluetun.subprocess.run')
    @patch('docker.from_env')
    def test_name_conflict_cleans_labelled_replacement_then_retries(
        self, from_env, run, _isdir,
    ):
        current = MagicMock()
        current.labels = {
            'com.docker.compose.service': 'prowlarr',
            'com.docker.compose.project': 'airvpn',
            'com.docker.compose.project.working_dir': '/compose',
        }
        client = MagicMock()
        client.containers.get.return_value = current
        client.api.containers.return_value = [{
            'Id': 'replacement-id',
            'Names': ['/b1f54429e6bf_prowlarr'],
            'Labels': {
                'com.docker.compose.replace': 'prowlarr',
                'com.docker.compose.service': 'prowlarr',
                'com.docker.compose.project': 'airvpn',
            },
        }]
        from_env.return_value = client
        run.side_effect = [
            MagicMock(
                returncode=1,
                stderr='Error response from daemon: Conflict. The container name "/b1f54429e6bf_prowlarr" is already in use',
                stdout='',
            ),
            MagicMock(returncode=0, stderr='', stdout=''),
        ]

        _compose_recreate('prowlarr', '/compose', 'airvpn')

        self.assertEqual(run.call_count, 2)
        client.api.remove_container.assert_called_once_with(
            'replacement-id', v=False, force=True,
        )

if __name__ == '__main__':
    unittest.main()
