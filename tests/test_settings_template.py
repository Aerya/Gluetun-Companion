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


if __name__ == '__main__':
    unittest.main()
