import os
import tempfile
import unittest

from app import database


class BenchmarkHistoryRepairTest(unittest.TestCase):
    def test_repairs_empty_best_server_and_removes_unfinished_cycles(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'companion.db')
            database.init_db(path)
            with database.get_db() as db:
                db.execute(
                    "INSERT INTO servers (name, filter_type) VALUES ('Bunda', 'name')"
                )
                db.execute(
                    "INSERT INTO speed_tests "
                    "(server_name, download_mbps, success, tested_at, test_method) "
                    "VALUES ('Bunda', 900, 1, '2026-07-14 05:30:00', 'sidecar')"
                )
                completed_id = db.execute(
                    "INSERT INTO benchmark_cycles "
                    "(started_at, finished_at, servers_tested, best_server) "
                    "VALUES ('2026-07-14 05:00:00', '2026-07-14 06:00:00', 1, NULL)"
                ).lastrowid
                db.execute(
                    "INSERT INTO benchmark_cycles (started_at) VALUES ('2026-07-14 06:30:00')"
                )
                db.execute(
                    "DELETE FROM settings WHERE key='benchmark_history_repaired_v1'"
                )

            database.init_db(path)

            with database.get_db() as db:
                rows = db.execute(
                    'SELECT id, finished_at, best_server FROM benchmark_cycles ORDER BY id'
                ).fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['id'], completed_id)
            self.assertEqual(rows[0]['best_server'], 'SERVER_NAMES=Bunda')


if __name__ == '__main__':
    unittest.main()
