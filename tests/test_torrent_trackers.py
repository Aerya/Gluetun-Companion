import os
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app import database
from app.torrent_trackers import (
    check_enabled_trackers,
    tracker_display_name,
    tracker_status_for_server,
)


class TorrentTrackerScopeTest(unittest.TestCase):
    def test_display_name_uses_the_meaningful_hostname_label(self):
        self.assertEqual(tracker_display_name('tracker.ygg.re'), 'Ygg')
        self.assertEqual(tracker_display_name('announce.sharewood.tv'), 'Sharewood')
        self.assertEqual(tracker_display_name('cinemaz.to'), 'Cinemaz')

    def test_check_scope_can_use_checked_trackers_or_all_trackers(self):
        with TemporaryDirectory() as directory:
            database.init_db(os.path.join(directory, 'test.db'))
            with database.get_db() as db:
                db.executemany(
                    '''INSERT INTO tracker_urls
                       (url, scheme, host, port, path, enabled)
                       VALUES (?, 'https', ?, 443, '/announce', ?)''',
                    [
                        ('https://tracker.one/announce', 'tracker.one', 1),
                        ('https://tracker.two/announce', 'tracker.two', 0),
                    ],
                )

            def successful_check(tracker, _timeout, _server_name):
                return {
                    'tracker_id': tracker['id'], 'url': tracker['url'],
                    'success': True, 'status': 'ok', 'error': '',
                    'level_dns': True, 'level_port': True,
                    'level_endpoint': True, 'elapsed_ms': 1,
                }

            with patch('app.torrent_trackers.check_tracker', side_effect=successful_check):
                database.set_setting('tracker_check_scope', 'enabled')
                checked = check_enabled_trackers(server_name='Bunda')
                database.set_setting('tracker_check_scope', 'all')
                all_trackers = check_enabled_trackers(server_name='Bunda')

            self.assertEqual(checked['total'], 1)
            self.assertEqual(checked['scope'], 'enabled')
            self.assertEqual(all_trackers['total'], 2)
            self.assertEqual(all_trackers['scope'], 'all')

    def test_server_success_rate_uses_the_selected_scope(self):
        with TemporaryDirectory() as directory:
            database.init_db(os.path.join(directory, 'test.db'))
            with database.get_db() as db:
                db.executemany(
                    '''INSERT INTO tracker_urls
                       (url, scheme, host, port, path, enabled)
                       VALUES (?, 'https', ?, 443, '/announce', ?)''',
                    [
                        ('https://tracker.one/announce', 'tracker.one', 1),
                        ('https://tracker.two/announce', 'tracker.two', 0),
                    ],
                )
                db.executemany(
                    '''INSERT INTO tracker_checks
                       (tracker_id, server_name, success, status)
                       VALUES (?, 'Bunda', ?, ?)''',
                    [(1, 1, 'ok'), (2, 0, 'timeout')],
                )

            database.set_setting('tracker_check_scope', 'enabled')
            checked = tracker_status_for_server('Bunda')
            database.set_setting('tracker_check_scope', 'all')
            all_trackers = tracker_status_for_server('Bunda')

            self.assertEqual(checked['success_pct'], 100.0)
            self.assertEqual(checked['total'], 1)
            self.assertEqual(all_trackers['success_pct'], 50.0)
            self.assertEqual(all_trackers['total'], 2)


if __name__ == '__main__':
    unittest.main()
