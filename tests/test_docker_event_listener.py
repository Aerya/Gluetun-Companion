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

    def test_companion_restart_does_not_start_parallel_network_repair(self):
        client = self._client()
        with (
            patch('docker.from_env', return_value=client),
            patch('app.gluetun.record_gluetun_id'),
            patch('app.gluetun.is_companion_restart', return_value=True),
            patch('app.scheduler.threading.Thread') as thread,
        ):
            with self.assertRaises(KeyboardInterrupt):
                _docker_event_loop(MagicMock(), 'gluetun-airvpn')

        thread.assert_not_called()

    def test_external_restart_starts_network_repair(self):
        client = self._client()
        with (
            patch('docker.from_env', return_value=client),
            patch('app.gluetun.record_gluetun_id'),
            patch('app.gluetun.is_companion_restart', return_value=False),
            patch('app.database.get_setting', return_value='1'),
            patch('app.scheduler.threading.Thread') as thread,
        ):
            with self.assertRaises(KeyboardInterrupt):
                _docker_event_loop(MagicMock(), 'gluetun-airvpn')

        thread.assert_called_once()
        self.assertEqual(thread.call_args.kwargs['name'], 'gluetun-network-repair')
