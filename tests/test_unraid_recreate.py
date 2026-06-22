import unittest
from unittest.mock import MagicMock, patch

from app.unraid import recreate_kwargs_from_inspect, sdk_recreate


def _gluetun_attrs():
    """Representative `docker inspect` of the real Unraid Gluetun container."""
    return {
        'Name': '/gluetun',
        'Config': {
            'Image': 'qmcgaw/gluetun:v3.39.1',
            'Env': [
                'VPN_SERVICE_PROVIDER=protonvpn',
                'VPN_TYPE=wireguard',
                'WIREGUARD_PRIVATE_KEY=keep-this-secret=',
                'VPN_PORT_FORWARDING=on',
                'SERVER_COUNTRIES=France',
            ],
            'Labels': {
                'net.unraid.docker.managed': 'dockerman',
                'net.unraid.docker.webui': 'http://[IP]:[PORT:8222]',
            },
        },
        'HostConfig': {
            'NetworkMode': 'bridge',
            'CapAdd': ['CAP_NET_ADMIN'],
            'CapDrop': None,
            'Sysctls': {'net.ipv6.conf.all.disable_ipv6': '1'},
            'Devices': [],
            'Binds': [
                '/mnt/user/appdata/gluetun:/gluetun:rw',
                '/mnt/user/appdata/gluetun/tmp:/tmp/gluetun:rw',
            ],
            'RestartPolicy': {'Name': 'always', 'MaximumRetryCount': 0},
            'Privileged': False,
            'Dns': [],
            'ExtraHosts': ['host.docker.internal:host-gateway'],
            'PortBindings': {
                '8000/tcp': [{'HostIp': '', 'HostPort': '8222'}],
                '8080/tcp': [{'HostIp': '', 'HostPort': '8080'},
                             {'HostIp': '', 'HostPort': '9892'}],
            },
        },
    }


class RecreateKwargsTest(unittest.TestCase):
    def test_env_merge_replaces_and_appends_preserving_secret(self):
        kw = recreate_kwargs_from_inspect(
            _gluetun_attrs(),
            env_overrides={'VPN_PORT_FORWARDING': 'on', 'PORT_FORWARD_ONLY': 'on',
                           'SERVER_COUNTRIES': 'Germany'},
        )
        env = kw['environment']
        self.assertIn('WIREGUARD_PRIVATE_KEY=keep-this-secret=', env)  # secret kept
        self.assertIn('SERVER_COUNTRIES=Germany', env)                 # replaced in place
        self.assertIn('PORT_FORWARD_ONLY=on', env)                     # appended
        self.assertEqual(env.count('VPN_PORT_FORWARDING=on'), 1)       # not duplicated
        # order preserved: replaced key stays at its original index
        self.assertEqual([e.split('=', 1)[0] for e in env][:5],
                         ['VPN_SERVICE_PROVIDER', 'VPN_TYPE', 'WIREGUARD_PRIVATE_KEY',
                          'VPN_PORT_FORWARDING', 'SERVER_COUNTRIES'])

    def test_labels_caps_sysctls_preserved(self):
        kw = recreate_kwargs_from_inspect(_gluetun_attrs())
        self.assertEqual(kw['labels']['net.unraid.docker.managed'], 'dockerman')
        self.assertEqual(kw['cap_add'], ['CAP_NET_ADMIN'])
        self.assertEqual(kw['sysctls'], {'net.ipv6.conf.all.disable_ipv6': '1'})
        self.assertEqual(kw['extra_hosts'], ['host.docker.internal:host-gateway'])
        self.assertEqual(kw['restart_policy'], {'Name': 'always', 'MaximumRetryCount': 0})
        self.assertIn('/mnt/user/appdata/gluetun:/gluetun:rw', kw['volumes'])

    def test_ports_single_and_multiple(self):
        kw = recreate_kwargs_from_inspect(_gluetun_attrs())
        self.assertEqual(kw['ports']['8000/tcp'], 8222)
        self.assertEqual(sorted(kw['ports']['8080/tcp']), [8080, 9892])

    def test_dependent_uses_network_name_and_drops_ports(self):
        attrs = {
            'Name': '/qbittorrent',
            'Config': {'Image': 'lscr.io/linuxserver/qbittorrent',
                       'Env': ['PUID=1000'], 'Labels': {'net.unraid.docker.managed': 'dockerman'}},
            'HostConfig': {
                'NetworkMode': 'container:OLD_GLUETUN_ID',
                'Binds': ['/mnt/user/appdata/qbittorrent:/config:rw'],
                'RestartPolicy': {'Name': 'unless-stopped', 'MaximumRetryCount': 0},
                'PortBindings': {},
            },
        }
        kw = recreate_kwargs_from_inspect(attrs, network_mode='container:gluetun')
        self.assertEqual(kw['network_mode'], 'container:gluetun')
        self.assertNotIn('ports', kw)  # ports invalid when sharing a namespace

    def test_image_baked_env_is_stripped(self):
        attrs = _gluetun_attrs()
        attrs['Config']['Env'].append('PATH=/usr/local/sbin:/usr/bin')
        image_env = ['PATH=/usr/local/sbin:/usr/bin', 'S6_VERBOSITY=1']
        kw = recreate_kwargs_from_inspect(attrs, image_env=image_env)
        self.assertNotIn('PATH=/usr/local/sbin:/usr/bin', kw['environment'])
        # explicitly-set vars are kept
        self.assertIn('VPN_SERVICE_PROVIDER=protonvpn', kw['environment'])
        self.assertIn('SERVER_COUNTRIES=France', kw['environment'])

    def test_empty_restart_policy_becomes_none(self):
        attrs = _gluetun_attrs()
        attrs['HostConfig']['RestartPolicy'] = {'Name': '', 'MaximumRetryCount': 0}
        kw = recreate_kwargs_from_inspect(attrs)
        self.assertIsNone(kw['restart_policy'])


class SdkRecreateTest(unittest.TestCase):
    @patch('docker.from_env')
    def test_stops_removes_and_runs_with_merged_env(self, from_env):
        client = MagicMock()
        cont = MagicMock()
        cont.attrs = _gluetun_attrs()
        client.containers.get.return_value = cont
        client.images.get.return_value.attrs = {'Config': {'Env': []}}
        from_env.return_value = client

        sdk_recreate('gluetun', env_overrides={'SERVER_COUNTRIES': 'Germany'})

        cont.stop.assert_called_once()
        cont.remove.assert_called_once()
        client.containers.run.assert_called_once()
        kw = client.containers.run.call_args.kwargs
        self.assertEqual(kw['name'], 'gluetun')
        self.assertIn('SERVER_COUNTRIES=Germany', kw['environment'])

    @patch('docker.from_env')
    def test_rolls_back_on_run_failure(self, from_env):
        client = MagicMock()
        cont = MagicMock()
        cont.attrs = _gluetun_attrs()
        client.containers.get.return_value = cont
        client.images.get.return_value.attrs = {'Config': {'Env': []}}
        client.containers.run.side_effect = [RuntimeError('boom'), MagicMock()]
        from_env.return_value = client

        with self.assertRaises(RuntimeError):
            sdk_recreate('gluetun', env_overrides={'X': '1'})
        # original run + rollback run
        self.assertEqual(client.containers.run.call_count, 2)


if __name__ == '__main__':
    unittest.main()
