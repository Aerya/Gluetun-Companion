import unittest
from unittest.mock import MagicMock, patch

from app.gluetun import list_network_dependents, list_orphaned_network_dependents


def _container(name, cid, network_mode='', running=True):
    c = MagicMock()
    c.name = name
    c.id = cid
    c.attrs = {
        'HostConfig': {'NetworkMode': network_mode},
        'State': {'Running': running},
    }
    return c


class NetworkDependentsTest(unittest.TestCase):
    @patch('app.gluetun.record_gluetun_id')
    @patch('docker.from_env')
    def test_network_dependents_ignore_stopped_containers(self, from_env, _record):
        client = MagicMock()
        gluetun = _container('gluetun', 'gluetun-full-id')
        client.containers.get.return_value = gluetun
        client.containers.list.return_value = [
            _container('qbittorrent', 'qbit-id', 'container:gluetun', running=True),
            _container('prowlarr', 'prowlarr-id', 'container:gluetun-full-id', running=True),
            _container('helper', 'helper-id', 'container:gluetun', running=False),
        ]
        from_env.return_value = client

        deps = list_network_dependents('gluetun')

        self.assertEqual(deps, ['prowlarr', 'qbittorrent'])

    @patch('app.gluetun._known_gluetun_ids', return_value={'dead-gluetun-id'})
    @patch('app.database.get_setting', return_value='1')
    @patch('docker.from_env')
    def test_orphaned_dependents_ignore_stopped_containers(self, from_env, _get_setting, _known_ids):
        client = MagicMock()
        client.containers.list.return_value = [
            _container('gluetun', 'current-gluetun-id', 'bridge', running=True),
            _container('qbittorrent', 'qbit-id', 'container:dead-gluetun-id', running=True),
            _container('helper', 'helper-id', 'container:dead-gluetun-id', running=False),
        ]
        from_env.return_value = client

        deps = list_orphaned_network_dependents()

        self.assertEqual(deps, ['qbittorrent'])


if __name__ == '__main__':
    unittest.main()
