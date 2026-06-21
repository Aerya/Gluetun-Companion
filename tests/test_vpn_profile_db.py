import os
import unittest
from tempfile import TemporaryDirectory

from app import database


class VpnProfilePortForwardingDbTest(unittest.TestCase):
    """The port_forwarding / port_forward_only columns survive the migration
    and round-trip through create/get/update/list."""

    def _fresh_db(self, directory):
        database.init_db(os.path.join(directory, 'test.db'))

    def test_create_and_read_back_flags(self):
        with TemporaryDirectory() as d:
            self._fresh_db(d)
            pid = database.create_vpn_profile(
                name='Proton-NL', provider='protonvpn', vpn_type='wireguard',
                vars={'WIREGUARD_PRIVATE_KEY': 'enc:xxx'},
                port_forwarding=True, port_forward_only=True,
                server_types=['p2p', 'stream'],
            )
            p = database.get_vpn_profile(pid)
            self.assertTrue(p['port_forwarding'])
            self.assertTrue(p['port_forward_only'])
            self.assertEqual(p['server_types'], ['p2p', 'stream'])

    def test_defaults_off_and_p2p_on(self):
        with TemporaryDirectory() as d:
            self._fresh_db(d)
            pid = database.create_vpn_profile(name='Air', provider='airvpn', vars={})
            p = database.get_vpn_profile(pid)
            self.assertFalse(p['port_forwarding'])     # default 0
            self.assertTrue(p['port_forward_only'])    # default 1

    def test_update_toggles(self):
        with TemporaryDirectory() as d:
            self._fresh_db(d)
            pid = database.create_vpn_profile(
                name='Proton', provider='protonvpn', vars={}, port_forwarding=True,
            )
            database.update_vpn_profile(pid, port_forwarding=False, port_forward_only=False)
            database.update_vpn_profile(pid, server_types=['tor'])
            p = database.get_vpn_profile(pid)
            self.assertFalse(p['port_forwarding'])
            self.assertFalse(p['port_forward_only'])
            self.assertEqual(p['server_types'], ['tor'])

    def test_list_exposes_flags(self):
        with TemporaryDirectory() as d:
            self._fresh_db(d)
            database.create_vpn_profile(name='Proton', provider='protonvpn', vars={},
                                        port_forwarding=True)
            profiles = database.get_vpn_profiles()
            self.assertTrue(profiles)
            self.assertTrue(all('port_forwarding' in p and 'port_forward_only' in p and 'server_types' in p
                                for p in profiles))


if __name__ == '__main__':
    unittest.main()
