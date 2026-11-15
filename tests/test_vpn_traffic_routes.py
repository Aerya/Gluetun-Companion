"""HTTP surface of the real VPN traffic monitor: WebUI API, page, /metrics,
REST v1 and the settings actions."""

import os
import re
import tempfile
import unittest
from unittest.mock import patch

from app import database
from app import vpn_traffic as vt
from app.i18n import TRANSLATIONS
from app.vpn_traffic import Reading, TrafficMonitor


class FakeClock:
    def __init__(self, t=1794744000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, secs):
        self.t += secs


class FakeReader:
    def __init__(self):
        self.queue = []
        self.last = Reading('error', detail='no reading')

    def push(self, reading):
        self.queue.append(reading)

    def read(self, _container):
        if self.queue:
            self.last = self.queue.pop(0)
        return self.last


def ok(rx, tx, health='healthy'):
    return Reading('ok', identity='c1|start1|tun0|5', rx=rx, tx=tx, iface='tun0',
                   provider='AirVPN', protocol='wireguard', container_id='c1', health=health)


class TrafficRoutesTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        env = {
            'SECRET_KEY': 'test-' + 'k' * 40,
            'DATA_DIR': self._tmp.name,
            'GLUETUN_CONTAINER': 'gluetun-test',
            'DOCKER_HOST': 'tcp://127.0.0.1:1',
            'METRICS_TOKEN': '',
        }
        self._env = patch.dict(os.environ, env)
        self._env.start()
        # Never start the scheduler, the Docker listener or the real collector.
        # Nor any Docker cleanup, at startup or registered for interpreter exit.
        self._patches = [
            patch('app.scheduler.start_scheduler'),
            patch('app.gluetun.cleanup_test_containers'),
            patch('app._cleanup_hooks_registered', True),
        ]
        for p in self._patches:
            p.start()
        from app import create_app
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.clock = FakeClock()
        self.reader = FakeReader()
        self.monitor = TrafficMonitor('gluetun-test', reader=self.reader, clock=self.clock)
        self._old_monitor = vt._monitor
        vt._monitor = self.monitor
        self.client = self.app.test_client()
        with self.client.session_transaction() as sess:
            sess['logged_in'] = True
            sess['username'] = 'admin'
            sess['_csrf_token'] = 'csrf-test'

    def tearDown(self):
        vt._monitor = self._old_monitor
        for p in reversed(self._patches):
            p.stop()
        self._env.stop()
        self._tmp.cleanup()

    def feed(self, *readings, step=5):
        for reading in readings:
            self.reader.push(reading)
            self.monitor.tick()
            self.clock.advance(step)

    def test_live_and_history_require_login(self):
        anon = self.app.test_client()
        for url in ('/api/vpn-traffic/live', '/api/vpn-traffic/history?range=24h', '/traffic'):
            resp = anon.get(url)
            self.assertEqual(resp.status_code, 302, url)
            self.assertIn('/login', resp.headers['Location'])

    def test_live_endpoint_reports_rates_and_units(self):
        self.feed(ok(1_000_000, 100_000), ok(1_000_000 + 5 * 125_000, 100_000 + 5 * 12_500))
        resp = self.client.get('/api/vpn-traffic/live')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers['Cache-Control'], 'no-store')
        data = resp.get_json()
        self.assertEqual(data['status'], 'connected')
        self.assertAlmostEqual(data['rx_rate'], 125_000)
        self.assertAlmostEqual(data['tx_rate'], 12_500)
        self.assertEqual(data['totals']['all']['rx'], 5 * 125_000)
        self.assertEqual(data['units'], {'rate': 'mbps', 'volume': 'si'})

    def test_history_rejects_unknown_range(self):
        resp = self.client.get('/api/vpn-traffic/history?range=forever')
        self.assertEqual(resp.status_code, 400)
        for key in ('live', '1h', '24h', '7d', '30d', 'months'):
            resp = self.client.get(f'/api/vpn-traffic/history?range={key}')
            self.assertEqual(resp.status_code, 200, key)
            self.assertIn('summary', resp.get_json())

    def test_traffic_page_renders_in_both_languages(self):
        self.feed(ok(10, 10), ok(5_000, 1_000))
        for lang, title in (('fr', TRANSLATIONS['fr']['trf_page_title']),
                            ('en', TRANSLATIONS['en']['trf_page_title'])):
            database.set_setting('ui_lang', lang)
            with self.client.session_transaction() as sess:
                sess['lang'] = lang
            resp = self.client.get('/traffic?range=7d')
            self.assertEqual(resp.status_code, 200, lang)
            html = resp.get_data(as_text=True)
            self.assertIn('id="trf-history"', html)
            self.assertIn('vpn-traffic.js', html)

    def test_metrics_expose_counters_and_availability(self):
        self.feed(ok(1_000, 100), ok(51_000, 5_100))
        body = self.client.get('/metrics').get_data(as_text=True)
        self.assertIn('# TYPE gluetun_companion_vpn_traffic_received_bytes_total counter', body)
        self.assertRegex(body, r'\ngluetun_companion_vpn_traffic_received_bytes_total 50000(\.0)?\n')
        self.assertRegex(body, r'\ngluetun_companion_vpn_traffic_sent_bytes_total 5000(\.0)?\n')
        self.assertRegex(body, r'gluetun_companion_vpn_traffic_monitoring_available\{status="connected"\} 1')
        self.assertRegex(body, r'\ngluetun_companion_vpn_tunnel_up 1\n')
        self.assertIn('gluetun_companion_vpn_traffic_receive_bytes_per_second 10000', body)
        self.assertIn('interface="tun0"', body)
        self.assertRegex(body, r'\ngluetun_companion_vpn_tunnel_healthy 1\n')

    def test_metrics_separate_interface_from_health(self):
        self.feed(ok(1_000, 100, health='unhealthy'), ok(2_000, 200, health='unhealthy'))
        body = self.client.get('/metrics').get_data(as_text=True)
        self.assertRegex(body, r'\ngluetun_companion_vpn_tunnel_up 1\n')
        self.assertRegex(body, r'\ngluetun_companion_vpn_tunnel_healthy 0\n')
        self.assertRegex(body, r'monitoring_available\{status="unhealthy"\} 1')

    def test_metrics_when_exec_is_forbidden(self):
        self.feed(Reading('forbidden', detail='exec_forbidden'))
        body = self.client.get('/metrics').get_data(as_text=True)
        self.assertRegex(body, r'gluetun_companion_vpn_traffic_monitoring_available\{status="unavailable"\} 0')
        self.assertRegex(body, r'\ngluetun_companion_vpn_tunnel_up 0\n')
        # No rate sample is published when it cannot be measured.
        self.assertNotRegex(body, r'\ngluetun_companion_vpn_traffic_receive_bytes_per_second \d')

    def test_rest_api_requires_token_and_returns_live_data(self):
        self.feed(ok(0, 0), ok(4_000, 400))
        self.assertEqual(self.client.get('/api/v1/traffic').status_code, 403)
        database.set_setting('api_token', 'tok')
        self.assertEqual(self.client.get('/api/v1/traffic').status_code, 401)
        hdr = {'Authorization': 'Bearer tok'}
        data = self.client.get('/api/v1/traffic', headers=hdr).get_json()
        self.assertEqual(data['totals']['all']['rx'], 4_000)
        self.assertNotIn('samples', data)
        data = self.client.get('/api/v1/traffic?range=24h', headers=hdr).get_json()
        self.assertIn('history', data)
        self.assertEqual(self.client.get('/api/v1/traffic?range=x', headers=hdr).status_code, 400)

    def _post_settings(self, **form):
        form.setdefault('_csrf_token', 'csrf-test')
        return self.client.post('/settings', data=form)

    def test_reset_requires_explicit_confirmation(self):
        self.feed(ok(0, 0), ok(9_000, 900))
        self._post_settings(action='vpn_traffic_reset')
        self.assertEqual(self.monitor.live()['totals']['all']['rx'], 9_000)
        self._post_settings(action='vpn_traffic_reset', confirm_reset='RESET')
        self.assertEqual(self.monitor.live()['totals']['all']['rx'], 0)

    def test_settings_are_clamped_and_validated(self):
        self._post_settings(action='vpn_traffic', traffic_monitor_interval='1',
                            traffic_hourly_retention_days='2', traffic_daily_retention_days='-4',
                            traffic_rate_unit='bogus', traffic_volume_unit='iec')
        get = database.get_setting
        self.assertEqual(get('traffic_monitor_enabled'), '0')  # unchecked switch
        self.assertEqual(get('traffic_monitor_interval'), str(vt.MIN_INTERVAL_SECS))
        self.assertEqual(get('traffic_hourly_retention_days'), str(vt.MIN_HOURLY_RETENTION_DAYS))
        self.assertEqual(get('traffic_daily_retention_days'), '0')
        self.assertEqual(get('traffic_rate_unit'), 'mbps')
        self.assertEqual(get('traffic_volume_unit'), 'iec')
        self.assertFalse(self.monitor.enabled())


class TrafficTranslationsTest(unittest.TestCase):
    def test_traffic_keys_exist_in_both_languages(self):
        keys = {k for lang in ('fr', 'en') for k in TRANSLATIONS[lang]
                if re.match(r'(trf_|set_traffic_|flash_traffic_|nav_traffic|set_tab_traffic)', k)}
        self.assertGreater(len(keys), 40)
        for lang in ('fr', 'en'):
            missing = keys - TRANSLATIONS[lang].keys()
            self.assertFalse(missing, f'{lang} missing {sorted(missing)}')
            for key in keys:
                self.assertTrue(TRANSLATIONS[lang][key].strip(), f'{lang}.{key} is empty')


if __name__ == '__main__':
    unittest.main()
