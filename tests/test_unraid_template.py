import os
import re
import shutil
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.unraid import find_template, update_template_env, write_template_env

FIXTURE = Path(__file__).parent / 'fixtures' / 'my-gluetun.xml'
UNRAID_TEMPLATE = Path(__file__).resolve().parents[1] / 'templates' / 'unraid' / 'gluetun-companion.xml'


def _val(text, name):
    m = re.search(r'<Config\b[^>]*\bTarget="' + name + r'"[^>]*>(.*?)</Config>', text)
    return m.group(1) if m else None


class FindTemplateTest(unittest.TestCase):
    def test_finds_by_name_element(self):
        with patch.dict(os.environ, {'UNRAID_TEMPLATE_DIR': str(FIXTURE.parent)}):
            self.assertEqual(find_template('gluetun'), str(FIXTURE))

    def test_returns_none_for_unknown(self):
        with patch.dict(os.environ, {'UNRAID_TEMPLATE_DIR': str(FIXTURE.parent)}):
            self.assertIsNone(find_template('does-not-exist'))

    def test_returns_none_when_dir_missing(self):
        with patch.dict(os.environ, {'UNRAID_TEMPLATE_DIR': '/no/such/dir'}):
            self.assertIsNone(find_template('gluetun'))


class UpdateTemplateEnvTest(unittest.TestCase):
    def setUp(self):
        self.text = FIXTURE.read_text(encoding='utf-8')

    def test_updates_existing_variable(self):
        new, changed = update_template_env(self.text, [('VPN_PORT_FORWARDING', 'off')])
        self.assertEqual(_val(new, 'VPN_PORT_FORWARDING'), 'off')
        self.assertIn('VPN_PORT_FORWARDING', changed)

    def test_inserts_missing_variable_before_container_close(self):
        new, _ = update_template_env(self.text, [('PORT_FORWARD_ONLY', 'on')])
        self.assertEqual(_val(new, 'PORT_FORWARD_ONLY'), 'on')
        self.assertIn('Target="PORT_FORWARD_ONLY"', new)
        # inserted before the closing tag
        self.assertLess(new.index('PORT_FORWARD_ONLY'), new.index('</Container>'))

    def test_fills_self_closing_empty_variable(self):
        new, _ = update_template_env(self.text, [('UNBLOCK', 'tracker.example.org')])
        self.assertEqual(_val(new, 'UNBLOCK'), 'tracker.example.org')

    def test_does_not_touch_port_node_value(self):
        new, _ = update_template_env(self.text, [('SERVER_COUNTRIES', 'Germany')])
        # the Control Server Port config (Target="8000") must stay intact
        self.assertIn('Name="HTTP_CONTROL_SERVER_PORT"', new)
        self.assertRegex(new, r'Name="HTTP_CONTROL_SERVER_PORT"[^>]*>8222</Config>')

    def test_preserves_xml_entities_elsewhere(self):
        new, _ = update_template_env(self.text, [('SERVER_COUNTRIES', 'Germany')])
        self.assertIn('&#x1F389;', new)
        self.assertIn('&amp;gt;', new)

    def test_escapes_special_characters_in_value(self):
        new, _ = update_template_env(self.text, [('SERVER_COUNTRIES', 'A&B<C>')])
        self.assertEqual(_val(new, 'SERVER_COUNTRIES'), 'A&amp;B&lt;C&gt;')

    def test_no_change_returns_identical_text(self):
        new, _ = update_template_env(self.text, [('VPN_SERVICE_PROVIDER', 'protonvpn')])
        self.assertEqual(new, self.text)


class WriteTemplateEnvTest(unittest.TestCase):
    def test_writes_backup_and_updates_file(self):
        with TemporaryDirectory() as d:
            path = os.path.join(d, 'my-gluetun.xml')
            shutil.copy2(FIXTURE, path)
            changed = write_template_env(
                path,
                [('VPN_PORT_FORWARDING', 'off'), ('WIREGUARD_PRIVATE_KEY', 'newsecret=')],
                secret_keys={'WIREGUARD_PRIVATE_KEY'},
            )
            self.assertIn('VPN_PORT_FORWARDING', changed)
            updated = Path(path).read_text(encoding='utf-8')
            self.assertEqual(_val(updated, 'VPN_PORT_FORWARDING'), 'off')
            self.assertEqual(_val(updated, 'WIREGUARD_PRIVATE_KEY'), 'newsecret=')
            backups = [f for f in os.listdir(d) if '.bak-' in f]
            self.assertEqual(len(backups), 1)

    def test_noop_when_already_current_writes_no_backup(self):
        with TemporaryDirectory() as d:
            path = os.path.join(d, 'my-gluetun.xml')
            shutil.copy2(FIXTURE, path)
            changed = write_template_env(path, [('VPN_SERVICE_PROVIDER', 'protonvpn')])
            self.assertEqual(changed, [])
            self.assertEqual([f for f in os.listdir(d) if '.bak-' in f], [])


class DockerManTemplateFileTest(unittest.TestCase):
    def test_upstream_template_is_parseable_and_not_fork_specific(self):
        text = UNRAID_TEMPLATE.read_text(encoding='utf-8')
        root = ET.fromstring(text)
        self.assertEqual(root.findtext('Repository'), 'ghcr.io/aerya/gluetun-companion:latest')
        self.assertNotIn('Hugs11', text)
        self.assertNotIn('fork-test', text)
        targets = {
            node.attrib.get('Target')
            for node in root.findall('Config')
        }
        self.assertIn('/gluetun', targets)
        self.assertNotIn('PUID', targets)
        self.assertNotIn('PGID', targets)


if __name__ == '__main__':
    unittest.main()
