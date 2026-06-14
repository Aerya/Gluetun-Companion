import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import docker
from werkzeug.datastructures import FileStorage

from app.openvpn_configs import (
    list_openvpn_configs,
    save_uploaded_config,
    scan_gluetun_configs,
    validate_import_path,
)


class OpenVpnConfigsTest(unittest.TestCase):
    def test_upload_sanitizes_name_and_lists_container_path(self):
        with tempfile.TemporaryDirectory() as directory:
            upload = FileStorage(stream=io.BytesIO(b'client\nremote vpn.example 1194\n'), filename='../Paris VPN.ovpn')
            name = save_uploaded_config(upload, directory)
            self.assertEqual(name, 'Paris_VPN.ovpn')
            self.assertTrue((Path(directory) / name).is_file())
            configs = list_openvpn_configs(directory, '/gluetun/openvpn')
            self.assertEqual(configs[0]['path'], '/gluetun/openvpn/Paris_VPN.ovpn')
            self.assertTrue(configs[0]['uploaded'])

    def test_upload_rejects_non_openvpn_extension(self):
        with tempfile.TemporaryDirectory() as directory:
            upload = FileStorage(stream=io.BytesIO(b'nope'), filename='secret.txt')
            with self.assertRaises(ValueError):
                save_uploaded_config(upload, directory)

    @patch('app.openvpn_configs.set_setting')
    @patch('app.openvpn_configs.get_setting', return_value='sidecar:test')
    @patch('app.openvpn_configs.docker.from_env')
    def test_scan_inherits_gluetun_volumes_without_exec(self, from_env, _setting, save_setting):
        client = from_env.return_value
        client.containers.get.side_effect = docker.errors.NotFound('missing')
        scanner = MagicMock()
        scanner.status = 'exited'
        scanner.attrs = {'State': {'ExitCode': 0}}
        scanner.logs.return_value = b'/gluetun/openvpn/france.ovpn\n/gluetun/custom.conf\n/tmp/nope.ovpn\n'
        client.containers.run.return_value = scanner

        paths = scan_gluetun_configs('gluetun-airvpn')

        self.assertEqual(paths, ['/gluetun/custom.conf', '/gluetun/openvpn/france.ovpn'])
        kwargs = client.containers.run.call_args.kwargs
        self.assertEqual(kwargs['volumes_from'], ['gluetun-airvpn:ro'])
        self.assertNotIn('exec', ' '.join(kwargs['command']).lower())
        save_setting.assert_called_once_with('openvpn_discovered_configs', json.dumps(paths))
        scanner.remove.assert_called_once_with(force=True)

    def test_import_rejects_unknown_path(self):
        configs = [{'path': '/gluetun/openvpn/known.ovpn'}]
        with self.assertRaises(ValueError):
            validate_import_path('/gluetun/openvpn/unknown.ovpn', configs)


if __name__ == '__main__':
    unittest.main()
