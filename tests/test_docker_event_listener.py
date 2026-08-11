from unittest import TestCase
from unittest.mock import MagicMock, patch

from app.scheduler import _docker_event_loop


class _OneStartEvent:
    def __iter__(self):
        yield {'Action': 'start', 'id': 'new-gluetun-id'}
        raise KeyboardInterrupt


class DockerEventListenerTest(TestCase):
    def _client(self):
        client = MagicMock()
        client.containers.get.return_value.id = 'current-gluetun-id'
        client.events.return_value = _OneStartEvent()
        return client

    def _run_loop(self, companion_restart):
        """Run the loop over one start event; return the thread names it spawned."""
        client = self._client()
        with (
            patch('docker.from_env', return_value=client),
            patch('app.gluetun.record_gluetun_id'),
            patch('app.gluetun.is_companion_restart', return_value=companion_restart),
            patch('app.database.get_setting', return_value='1'),
            patch('app.scheduler.threading.Thread') as thread,
        ):
            with self.assertRaises(KeyboardInterrupt):
                _docker_event_loop(MagicMock(), 'gluetun-airvpn')

        return [c.kwargs.get('name') for c in thread.call_args_list]

    def test_companion_restart_does_not_start_parallel_network_repair(self):
        names = self._run_loop(companion_restart=True)

        self.assertNotIn('gluetun-network-repair', names)

    def test_external_restart_starts_network_repair(self):
        names = self._run_loop(companion_restart=False)

        self.assertEqual(names.count('gluetun-network-repair'), 1)

    def test_boot_scan_runs_regardless_of_events(self):
        """A Gluetun recreated while Companion is down (host reboot, Unraid or
        image update) emits no event, so the loop must reconcile at startup."""
        for companion_restart in (True, False):
            with self.subTest(companion_restart=companion_restart):
                names = self._run_loop(companion_restart)

                self.assertEqual(names.count('gluetun-network-repair-boot'), 1)
