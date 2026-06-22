import unittest
from unittest.mock import MagicMock, patch

from app.port_forwarding import read_gluetun_native_ports


def _resp(status, payload=None, text=''):
    m = MagicMock()
    m.status_code = status
    if payload is not None:
        m.json.return_value = payload
    else:
        m.json.side_effect = ValueError()
        m.text = text
    return m


class ReadGluetunNativePortsTest(unittest.TestCase):
    @patch('app.port_forwarding.get_setting', return_value='')
    @patch('app.port_forwarding.requests.get')
    def test_primary_endpoint(self, rget, _gs):
        rget.return_value = _resp(200, {'port': 5914})
        res = read_gluetun_native_ports(api_url='http://gluetun:8000')
        self.assertTrue(res['ok'])
        self.assertEqual(res['ports'], [5914])
        self.assertEqual(res['source'], 'v1/portforward')

    @patch('app.port_forwarding.get_setting', return_value='')
    @patch('app.port_forwarding.requests.get')
    def test_falls_back_to_legacy_on_401(self, rget, _gs):
        def _get(url, headers=None, timeout=None):
            if url.endswith('/v1/portforward'):
                return _resp(401, text='Unauthorized')
            if url.endswith('/v1/openvpn/portforwarded'):
                return _resp(200, {'port': 40849})
            raise AssertionError(url)
        rget.side_effect = _get
        res = read_gluetun_native_ports(api_url='http://gluetun:8000')
        self.assertTrue(res['ok'])
        self.assertEqual(res['ports'], [40849])
        self.assertEqual(res['source'], 'legacy')

    @patch('app.port_forwarding._container_env',
           return_value={'VPN_PORT_FORWARDING': 'off', 'VPN_SERVICE_PROVIDER': 'protonvpn'})
    @patch('app.port_forwarding.get_setting', return_value='')
    @patch('app.port_forwarding.requests.get')
    def test_diagnostic_when_port_forwarding_off(self, rget, _gs, _env):
        rget.return_value = _resp(200, {})
        res = read_gluetun_native_ports(api_url='http://gluetun:8000', container_name='gluetun')
        self.assertFalse(res['ok'])
        self.assertIn('VPN_PORT_FORWARDING', res['error'])

    @patch('app.port_forwarding._container_env',
           return_value={'VPN_PORT_FORWARDING': 'on', 'VPN_SERVICE_PROVIDER': 'airvpn'})
    @patch('app.port_forwarding.get_setting', return_value='')
    @patch('app.port_forwarding.requests.get')
    def test_diagnostic_when_provider_has_no_native_pf(self, rget, _gs, _env):
        rget.return_value = _resp(200, {})
        res = read_gluetun_native_ports(api_url='http://gluetun:8000', container_name='gluetun')
        self.assertFalse(res['ok'])
        self.assertIn('airvpn', res['error'])

    @patch.dict('os.environ', {'GLUETUN_HOST': '172.17.0.1', 'GLUETUN_CONTAINER': 'gluetun'}, clear=False)
    @patch('app.port_forwarding.get_setting')
    @patch('app.port_forwarding.docker.from_env')
    @patch('app.port_forwarding.requests.get')
    def test_falls_back_to_docker_published_control_port(self, rget, docker_env, get_setting):
        get_setting.side_effect = lambda key, default='': {
            'port_forward_gluetun_api_url': 'http://host.docker.internal:8000',
            'port_forward_gluetun_api_key': '',
            'gluetun_host': '',
        }.get(key, default)
        container = MagicMock()
        container.attrs = {
            'NetworkSettings': {
                'Ports': {'8000/tcp': [{'HostIp': '', 'HostPort': '8222'}]},
            },
        }
        docker_env.return_value.containers.get.return_value = container

        def _get(url, headers=None, timeout=None):
            if url.startswith('http://host.docker.internal:8000'):
                raise OSError('unreachable')
            if url == 'http://172.17.0.1:8222/v1/openvpn/portforwarded':
                return _resp(200, {'port': 41893})
            if url == 'http://172.17.0.1:8222/v1/portforward':
                return _resp(404, text='not found')
            raise AssertionError(url)
        rget.side_effect = _get

        res = read_gluetun_native_ports()

        self.assertTrue(res['ok'])
        self.assertEqual(res['ports'], [41893])
        self.assertEqual(res['api_url'], 'http://172.17.0.1:8222')


if __name__ == '__main__':
    unittest.main()
