import os
import unittest
from unittest.mock import MagicMock, patch

import docker

from app.gluetun import (
    _TEMPORARY_LABEL, _TEST_GLUETUN_NAME, _SIDECAR_NAME,
    _CATALOGUE_SIDECAR_NAME, _remove_container, cleanup_test_containers,
    cleanup_catalogue_sidecar, create_test_gluetun, create_speed_sidecar,
    create_catalogue_sidecar,
)


class TemporaryContainerOwnershipTest(unittest.TestCase):
    def container(self, labels=None):
        container = MagicMock()
        container.id = 'abcdef123456' + '0' * 52
        container.attrs = {'Config': {'Labels': labels, 'Image': 'test-image'},
                           'HostConfig': {}}
        return container

    def test_unmarked_containers_survive_all_cleanup_paths(self):
        for hostname in ('custom-companion', '', 'abcdef123456'):
            for labels in (None, {}, {'com.docker.compose.service': 'companion'},
                           {_TEMPORARY_LABEL: 'wrong-role'}):
                with self.subTest(hostname=hostname, labels=labels):
                    client = MagicMock()
                    container = self.container(labels)
                    client.containers.get.return_value = container
                    with patch.dict(os.environ, {'HOSTNAME': hostname}), patch(
                        'app.gluetun.docker.from_env', return_value=client,
                    ):
                        cleanup_test_containers()
                        cleanup_catalogue_sidecar()
                    container.kill.assert_not_called()
                    container.stop.assert_not_called()
                    container.remove.assert_not_called()

    def test_marked_containers_can_be_cleaned_after_restart(self):
        for name in (_TEST_GLUETUN_NAME, _SIDECAR_NAME, _CATALOGUE_SIDECAR_NAME):
            for kill_first in (True, False):
                with self.subTest(name=name, kill_first=kill_first):
                    client = MagicMock()
                    container = self.container({_TEMPORARY_LABEL: name})
                    client.containers.get.return_value = container
                    with patch.dict(os.environ, {'HOSTNAME': 'custom-companion'}):
                        self.assertTrue(_remove_container(client, name, kill_first))
                    container.remove.assert_called_once_with(force=True)
                    if kill_first:
                        container.kill.assert_called_once()
                    else:
                        container.stop.assert_called_once_with(timeout=10)

    def test_missing_container_is_successful_cleanup(self):
        client = MagicMock()
        client.containers.get.side_effect = docker.errors.NotFound('absent')
        self.assertTrue(_remove_container(client, _TEST_GLUETUN_NAME))

    def test_failed_inspection_never_removes_container(self):
        client = MagicMock()
        client.containers.get.side_effect = docker.errors.APIError('unavailable')
        self.assertFalse(_remove_container(client, _TEST_GLUETUN_NAME))

    def test_creation_labels_each_temporary_role(self):
        for name, create, args in (
            (_TEST_GLUETUN_NAME, create_test_gluetun, ('real-vpn', 'country', 'France')),
            (_SIDECAR_NAME, create_speed_sidecar, ('test-image',)),
            (_CATALOGUE_SIDECAR_NAME, create_catalogue_sidecar, ('test-image',)),
        ):
            with self.subTest(name=name):
                client = MagicMock()
                real = self.container()
                def get(container_name):
                    if container_name == 'real-vpn':
                        return real
                    raise docker.errors.NotFound('absent')
                client.containers.get.side_effect = get
                with patch('app.gluetun.docker.from_env', return_value=client):
                    ok, error = create(*args)
                self.assertTrue(ok, error)
                self.assertEqual(client.containers.run.call_args.kwargs['labels'],
                                 {_TEMPORARY_LABEL: name})
                real.kill.assert_not_called()
                real.remove.assert_not_called()

    def test_name_collision_aborts_creation_without_touching_real_container(self):
        for create, args in (
            (create_test_gluetun, ('real-vpn', 'country', 'France')),
            (create_speed_sidecar, ('test-image',)),
            (create_catalogue_sidecar, ('test-image',)),
        ):
            with self.subTest(create=create.__name__):
                client = MagicMock()
                real = self.container()
                client.containers.get.return_value = real
                with patch.dict(os.environ, {'HOSTNAME': 'custom-companion'}), patch(
                    'app.gluetun.docker.from_env', return_value=client,
                ):
                    ok, error = create(*args)
                self.assertFalse(ok)
                self.assertIn('name unavailable', error)
                client.containers.run.assert_not_called()
                real.kill.assert_not_called()
                real.stop.assert_not_called()
                real.remove.assert_not_called()
