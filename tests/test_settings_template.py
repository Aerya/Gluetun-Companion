import unittest
from pathlib import Path


SETTINGS_TEMPLATE = (
    Path(__file__).resolve().parents[1] / 'app' / 'templates' / 'settings.html'
)


class SettingsTemplateTest(unittest.TestCase):
    def test_existing_non_secret_vpn_profile_values_are_displayed(self):
        template = SETTINGS_TEMPLATE.read_text(encoding='utf-8')

        self.assertIn("if (input && !f.secret) input.value = existingVal;", template)
        self.assertNotIn('value="${existingVal}"', template)

    def test_native_port_status_does_not_claim_static_firewall_ports_are_required(self):
        template = SETTINGS_TEMPLATE.read_text(encoding='utf-8')

        self.assertIn("if pf.mode == 'native' else 'FIREWALL_VPN_INPUT_PORTS'", template)
        self.assertIn("'Control Server' if pf.mode == 'native'", template)

    def test_port_forward_sync_uses_its_own_visible_result_area(self):
        template = SETTINGS_TEMPLATE.read_text(encoding='utf-8')

        self.assertIn('id="port-forward-action-result"', template)
        self.assertIn("function _portForwardMsg(text, cls)", template)
        self.assertIn(".catch(err => _portForwardMsg(err.message", template)


if __name__ == '__main__':
    unittest.main()
