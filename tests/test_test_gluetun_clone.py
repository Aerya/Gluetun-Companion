import unittest
from unittest.mock import MagicMock, patch

from app.gluetun import create_test_gluetun


def _real_gluetun_attrs():
    """Representative `docker inspect` of a real ProtonVPN Gluetun container
    whose forwarded port is pushed to a torrent client sharing its network
    namespace (network_mode: service:gluetun)."""
    return {
        'Config': {
            'Image': 'qmcgaw/gluetun:latest',
            'Env': [
                'VPN_SERVICE_PROVIDER=protonvpn',
                'VPN_TYPE=wireguard',
                'WIREGUARD_PRIVATE_KEY=main-key=',
                'WIREGUARD_ADDRESSES=10.2.0.2/32',
                'SERVER_COUNTRIES=United States',
                'PORT_FORWARD_ONLY=on',
                'VPN_PORT_FORWARDING=on',
                'VPN_PORT_FORWARDING_PROVIDER=protonvpn',
                # Reaches qBittorrent only from the REAL container's namespace.
                'VPN_PORT_FORWARDING_UP_COMMAND=/bin/sh -c "wget -O- '
                'http://127.0.0.1:8080/api/v2/app/setPreferences?json=%7B%22listen_port%22%3A{{PORTS}}%7D"',
                'VPN_PORT_FORWARDING_DOWN_COMMAND=/bin/sh -c "echo down"',
            ],
        },
        'HostConfig': {
            'CapAdd': ['NET_ADMIN'],
            'Sysctls': {},
            'Devices': [],
        },
    }


class TestGluetunClonePortForwardingTest(unittest.TestCase):
    """The benchmark clone must never run port forwarding.

    Inheriting VPN_PORT_FORWARDING_UP_COMMAND made the clone retry a command
    against a torrent client that does not exist in its network namespace
    ("up command: failed: Connection refused") for the whole test.
    """

    def _run_clone(self, extra_env=None):
        client = MagicMock()
        client.containers.get.return_value.attrs = _real_gluetun_attrs()
        with patch('app.gluetun.docker.from_env', return_value=client):
            ok, err = create_test_gluetun(
                'gluetun', 'country', 'Netherlands', 8766, extra_env=extra_env,
            )
        self.assertTrue(ok, err)
        return client.containers.run.call_args.kwargs['environment']

    def test_inherited_port_forwarding_is_neutralized(self):
        env = self._run_clone()

        self.assertEqual(env['VPN_PORT_FORWARDING'], 'off')
        self.assertEqual(env['VPN_PORT_FORWARDING_PROVIDER'], '')
        self.assertEqual(env['VPN_PORT_FORWARDING_UP_COMMAND'], '')
        self.assertEqual(env['VPN_PORT_FORWARDING_DOWN_COMMAND'], '')

    def test_profile_managed_port_forwarding_is_overridden(self):
        # _managed_env_pairs turns port forwarding ON for native-PF providers;
        # the clone must still win over it.
        env = self._run_clone(extra_env={
            'VPN_SERVICE_PROVIDER': 'protonvpn',
            'VPN_TYPE': 'wireguard',
            'WIREGUARD_PRIVATE_KEY': 'sidecar-key=',
            'VPN_PORT_FORWARDING': 'on',
            'VPN_PORT_FORWARDING_PROVIDER': 'protonvpn',
        })

        self.assertEqual(env['VPN_PORT_FORWARDING'], 'off')
        self.assertEqual(env['VPN_PORT_FORWARDING_PROVIDER'], '')
        # The dedicated sidecar identity still applies.
        self.assertEqual(env['WIREGUARD_PRIVATE_KEY'], 'sidecar-key=')

    def test_server_selection_filter_is_preserved(self):
        # PORT_FORWARD_ONLY selects which Proton servers are eligible, so it
        # must survive: benchmarks should measure the servers production uses.
        env = self._run_clone()

        self.assertEqual(env['PORT_FORWARD_ONLY'], 'on')
        self.assertEqual(env['SERVER_COUNTRIES'], 'Netherlands')


if __name__ == '__main__':
    unittest.main()
