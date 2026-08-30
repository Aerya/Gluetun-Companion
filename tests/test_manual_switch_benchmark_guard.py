import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ManualSwitchBenchmarkGuardTest(unittest.TestCase):
    def test_manual_switch_is_blocked_before_it_reads_or_changes_gluetun(self):
        routes = (ROOT / 'app' / 'routes.py').read_text(encoding='utf-8')
        start = routes.index('def manual_switch(server_id):')
        body = routes[start:routes.index("@bp.route('/servers/test/", start)]

        guard = "if get_setting('benchmark_running', '0') == '1':"
        self.assertIn(guard, body)
        self.assertLess(body.index(guard), body.index('cfg = current_app.config'))
        self.assertIn("flash_t('flash_benchmark_running', 'warning')", body)

    def test_proxy_restore_has_its_own_enabled_by_default_notification(self):
        scheduler = (ROOT / 'app' / 'scheduler.py').read_text(encoding='utf-8')
        routes = (ROOT / 'app' / 'routes.py').read_text(encoding='utf-8')
        settings = (ROOT / 'app' / 'templates' / 'settings.html').read_text(encoding='utf-8')

        self.assertIn("get_setting('notif_proxy_test_revert', '1') == '1'", scheduler)
        self.assertIn("alert_type='proxy_test_revert'", scheduler)
        self.assertIn("'notif_proxy_test_revert', '1'", routes)
        self.assertIn('name="notif_proxy_test_revert"', settings)


if __name__ == '__main__':
    unittest.main()
