import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from flask import Flask

from app import database
from app.scheduler import _check_active_server_history


class ActiveServerHistoryTest(unittest.TestCase):
    @patch('docker.from_env')
    @patch('app.gluetun.get_public_ips', return_value=('2.2.2.2', None))
    @patch('app.gluetun.get_active_server', return_value='NewServer')
    def test_records_an_observed_external_server_change(
        self, _active, _ips, docker_from_env,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            database.init_db(os.path.join(tmp, 'companion.db'))
            database.set_setting('benchmark_running', '0')
            database.set_setting('last_observed_active_server', 'OldServer')
            database.set_setting('last_observed_gluetun_id', 'old-container-id')
            container = MagicMock()
            container.id = 'new-container-id'
            docker_from_env.return_value.containers.get.return_value = container
            flask_app = Flask(__name__)
            flask_app.config.update({
                'GLUETUN_CONTAINER': 'gluetun',
                'GLUETUN_HOST': 'gluetun',
                'GLUETUN_PROXY_PORT': 8888,
            })

            _check_active_server_history(flask_app)

            with database.get_db() as db:
                row = db.execute(
                    'SELECT from_server, to_server, reason, success FROM switches'
                ).fetchone()
            self.assertEqual(row['from_server'], 'OldServer')
            self.assertEqual(row['to_server'], 'NewServer')
            self.assertEqual(row['reason'], 'external_recreate')
            self.assertEqual(row['success'], 1)


if __name__ == '__main__':
    unittest.main()
