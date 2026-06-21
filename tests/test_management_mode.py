import os
import unittest
from unittest.mock import MagicMock, patch

from app.gluetun import (
    CONTROL_BACKEND_COMPOSE,
    CONTROL_BACKEND_UNRAID,
    _managed_env_pairs,
    _management_mode,
)


def _dns_setting(key, default=''):
    return {'dns_block_malicious': '1', 'dns_unblock_hostnames': ''}.get(key, default)


class ManagedEnvPairsTest(unittest.TestCase):
    """The shared env builder is the single source of truth for every backend."""

    @patch('app.gluetun.get_setting', side_effect=_dns_setting)
    def test_filter_targets_one_var_and_blanks_others(self, _gs):
        d = dict(_managed_env_pairs('France', 'country', None))
        self.assertEqual(d['SERVER_COUNTRIES'], 'France')
        self.assertEqual(d['SERVER_NAMES'], '')
        self.assertEqual(d['SERVER_CITIES'], '')
        self.assertEqual(d['BLOCK_MALICIOUS'], 'on')

    @patch('app.gluetun.get_setting', side_effect=_dns_setting)
    def test_profile_sets_provider_type_and_blanks_other_credentials(self, _gs):
        profile = {
            'compose_provider': 'protonvpn',
            'vpn_type': 'wireguard',
            'vars': {'WIREGUARD_PRIVATE_KEY': 'secret-key'},
        }
        pairs = _managed_env_pairs('France', 'country', profile)
        d = dict(pairs)
        self.assertEqual(d['VPN_SERVICE_PROVIDER'], 'protonvpn')
        self.assertEqual(d['VPN_TYPE'], 'wireguard')
        self.assertEqual(d['WIREGUARD_PRIVATE_KEY'], 'secret-key')
        # A different provider's credential is blanked out (anti-leak).
        self.assertEqual(d['WIREGUARD_PRESHARED_KEY'], '')
        keys = [k for k, _ in pairs]
        self.assertEqual(keys.count('VPN_SERVICE_PROVIDER'), 1)
        self.assertEqual(keys.count('WIREGUARD_PRIVATE_KEY'), 1)

    @patch('app.gluetun.get_setting', side_effect=_dns_setting)
    def test_custom_provider_does_not_set_server_filter(self, _gs):
        profile = {'compose_provider': 'custom', 'vpn_type': 'wireguard', 'vars': {}}
        d = dict(_managed_env_pairs('France', 'country', profile))
        self.assertEqual(d['SERVER_COUNTRIES'], '')


class ManagementModeTest(unittest.TestCase):
    def _mode_with_labels(self, labels):
        client = MagicMock()
        client.containers.get.return_value.labels = labels
        with patch('app.gluetun.docker.from_env', return_value=client), \
                patch.dict(os.environ, {}, clear=False):
            os.environ.pop('CONTROL_BACKEND', None)
            return _management_mode('gluetun')

    def test_compose_label_detected(self):
        self.assertEqual(
            self._mode_with_labels({'com.docker.compose.project': 'airvpn'}),
            CONTROL_BACKEND_COMPOSE,
        )

    def test_unraid_label_detected(self):
        self.assertEqual(
            self._mode_with_labels({'net.unraid.docker.managed': 'dockerman'}),
            CONTROL_BACKEND_UNRAID,
        )

    def test_default_is_compose(self):
        self.assertEqual(self._mode_with_labels({}), CONTROL_BACKEND_COMPOSE)

    def test_compose_wins_when_both_labels_present(self):
        self.assertEqual(
            self._mode_with_labels({
                'com.docker.compose.project': 'x',
                'net.unraid.docker.managed': 'dockerman',
            }),
            CONTROL_BACKEND_COMPOSE,
        )

    def test_env_override_forces_unraid_even_with_compose_label(self):
        client = MagicMock()
        client.containers.get.return_value.labels = {'com.docker.compose.project': 'x'}
        with patch('app.gluetun.docker.from_env', return_value=client), \
                patch.dict(os.environ, {'CONTROL_BACKEND': 'unraid'}):
            self.assertEqual(_management_mode('gluetun'), CONTROL_BACKEND_UNRAID)


if __name__ == '__main__':
    unittest.main()
