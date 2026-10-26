import unittest
from unittest.mock import MagicMock, patch

from app import scheduler


def _settings(**overrides):
    values = {
        'benchmark_running': '0',
        'auto_switch': '1',
        'auto_benchmark': '1',
        'benchmark_schedule_mode': 'interval',
        'quick_check_threshold': '15',
    }
    values.update(overrides)
    return lambda key, default='': values.get(key, default)


class DockerEventBenchmarkGuardTest(unittest.TestCase):
    def _run_drifting_quick_check(self, **settings):
        app = MagicMock()
        app.config = {
            'GLUETUN_CONTAINER': 'gluetun',
            'GLUETUN_HOST': 'gluetun',
            'GLUETUN_PROXY_PORT': 8888,
        }
        with (
            patch('app.database.get_setting', side_effect=_settings(**settings)),
            patch('app.database.set_setting'),
            patch.object(scheduler, '_quick_check', return_value=(False, 'srv-a', 40.0, 100.0)),
            patch.object(scheduler, '_do_benchmark') as do_benchmark,
        ):
            scheduler._run_event_triggered_quick_check(app)
        return do_benchmark

    def test_drift_does_not_start_full_benchmark_when_auto_benchmark_disabled(self):
        do_benchmark = self._run_drifting_quick_check(auto_benchmark='0')

        do_benchmark.assert_not_called()

    def test_drift_does_not_start_full_benchmark_on_fixed_time_schedule(self):
        do_benchmark = self._run_drifting_quick_check(benchmark_schedule_mode='calendar')

        do_benchmark.assert_not_called()

    def test_drift_starts_full_benchmark_tagged_with_its_origin(self):
        do_benchmark = self._run_drifting_quick_check()

        do_benchmark.assert_called_once()
        self.assertEqual(do_benchmark.call_args.kwargs['trigger'], 'docker_event_benchmark')


class BenchmarkOriginTest(unittest.TestCase):
    def test_scheduled_run_is_tagged_scheduled(self):
        db = MagicMock()
        db.__enter__.return_value.execute.return_value.fetchone.return_value = {'n': 0}
        with (
            patch('app.database.get_setting', side_effect=_settings()),
            patch('app.database.get_db', return_value=db),
            patch.object(scheduler, '_do_benchmark') as do_benchmark,
            patch.object(scheduler, '_restore_configured_trigger'),
        ):
            scheduler.run_benchmark(MagicMock())

        self.assertEqual(do_benchmark.call_args.kwargs['trigger'], 'scheduled')

    def test_manual_run_forwards_requested_origin(self):
        with patch.object(scheduler, '_do_benchmark') as do_benchmark:
            scheduler.run_benchmark_now(MagicMock(), trigger='api')
            scheduler.run_benchmark_now(MagicMock())

        self.assertEqual(
            [c.kwargs['trigger'] for c in do_benchmark.call_args_list],
            ['api', None],
        )

    def test_trigger_now_passes_origin_to_worker_thread(self):
        app = MagicMock()
        with patch.object(scheduler.threading, 'Thread') as thread:
            scheduler.trigger_now(app, trigger='import')

        self.assertEqual(thread.call_args.kwargs['args'], [app, 'import'])


if __name__ == '__main__':
    unittest.main()
