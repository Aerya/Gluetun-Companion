import os
import unittest
from tempfile import TemporaryDirectory

from app import database


class DatabaseIndexesTest(unittest.TestCase):
    def test_servers_page_history_indexes_are_created(self):
        previous_db_path = database._db_path
        try:
            with TemporaryDirectory() as directory:
                database.init_db(os.path.join(directory, 'test.db'))
                with database.get_db() as db:
                    speed_indexes = {
                        row['name'] for row in db.execute('PRAGMA index_list(speed_tests)')
                    }
                    tracker_indexes = {
                        row['name'] for row in db.execute('PRAGMA index_list(tracker_checks)')
                    }
                    catalogue_indexes = {
                        row['name'] for row in db.execute('PRAGMA index_list(gluetun_catalogue)')
                    }
        finally:
            database._db_path = previous_db_path

            self.assertTrue({
                'idx_speed_tests_server_tested',
                'idx_speed_tests_server_success_tested',
            }.issubset(speed_indexes))
            self.assertIn('idx_tracker_checks_latest_server', tracker_indexes)
            self.assertIn('idx_catalogue_name', catalogue_indexes)


if __name__ == '__main__':
    unittest.main()
