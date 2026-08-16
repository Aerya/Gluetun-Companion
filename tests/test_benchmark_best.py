import sqlite3
import unittest
from contextlib import nullcontext
from unittest.mock import MagicMock, patch

from app.scheduler import _best_result_for_active_profile, _build_server_profile_map


class BenchmarkBestTest(unittest.TestCase):
    @patch('app.profiles.score_results')
    @patch('app.database.get_docker_event_counts', return_value={})
    @patch('app.database.compute_confidence_all', return_value={})
    @patch('app.database.get_db')
    @patch('app.database.get_setting')
    @patch('app.scheduler._weighted_score')
    def test_ranks_results_without_requiring_auto_switch(
        self, weighted_score, get_setting, get_db, _confidence, _events, score_results,
    ):
        settings = {
            'weighted_score_current_pct': '65',
            'stability_weight': '30',
            'db_retention_days': '30',
            'active_profile': 'balanced',
        }
        get_setting.side_effect = lambda key, default='': settings.get(key, default)
        get_db.return_value = nullcontext(MagicMock())
        weighted_score.side_effect = lambda _name, dl, *_args, **_kwargs: dl
        score_results.return_value = {'Slow': 0.2, 'Fast': 0.9}
        results = [
            {'server': 'Slow', 'filter_type': 'name', 'dl': 100.0},
            {'server': 'Fast', 'filter_type': 'name', 'dl': 900.0},
        ]

        best, scores = _best_result_for_active_profile(results)

        self.assertEqual(best['server'], 'Fast')
        self.assertEqual(scores['Fast'], 0.9)

    def test_build_server_profile_map_accepts_sqlite_rows(self):
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        try:
            conn.execute(
                'CREATE TABLE servers ('
                'name TEXT, vpn_profile_id INTEGER, vp_rotation_allowed INTEGER)'
            )
            conn.executemany(
                'INSERT INTO servers VALUES (?, ?, ?)',
                [('Ceibo', 1, 0), ('Germany', 2, 1)],
            )
            rows = conn.execute(
                'SELECT name, vpn_profile_id, vp_rotation_allowed FROM servers'
            ).fetchall()

            profile_map = _build_server_profile_map(rows)

            self.assertEqual(
                profile_map,
                {'Ceibo': (1, False), 'Germany': (2, True)},
            )
        finally:
            conn.close()


if __name__ == '__main__':
    unittest.main()
