import os
import unittest
from unittest.mock import MagicMock, patch

from app.gluetun import _remove_container


class RemoveContainerSelfGuardTest(unittest.TestCase):
    """_remove_container must never stop/remove the container it runs in.

    Our internal ephemeral-clone names (e.g. "gluetun-companion-test", see
    _TEST_GLUETUN_NAME) are plain strings a user could reasonably also pick
    for their real Companion container -- the quick-start guide's own
    suggested test setup uses that exact name. Startup/shutdown cleanup
    matches by name alone, so without this guard a real Companion container
    sharing one of those names gets killed by its own cleanup within seconds
    of starting.
    """

    def test_refuses_to_remove_self(self):
        client = MagicMock()
        container = MagicMock()
        container.id = 'abcdef1234567890'
        client.containers.get.return_value = container

        with patch.dict(os.environ, {'HOSTNAME': 'abcdef123456'}):
            _remove_container(client, 'gluetun-companion-test', kill_first=True)

        container.kill.assert_not_called()
        container.stop.assert_not_called()
        container.remove.assert_not_called()

    def test_removes_other_containers_normally(self):
        client = MagicMock()
        container = MagicMock()
        container.id = 'deadbeef000000'
        client.containers.get.return_value = container

        with patch.dict(os.environ, {'HOSTNAME': 'abcdef123456'}):
            _remove_container(client, 'gluetun-companion-test', kill_first=True)

        container.kill.assert_called_once()
        container.remove.assert_called_once_with(force=True)

    def test_removes_normally_when_hostname_unset(self):
        client = MagicMock()
        container = MagicMock()
        container.id = 'deadbeef000000'
        client.containers.get.return_value = container

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('HOSTNAME', None)
            _remove_container(client, 'gluetun-companion-test', kill_first=True)

        container.remove.assert_called_once_with(force=True)


if __name__ == '__main__':
    unittest.main()
