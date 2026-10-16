import unittest
from unittest.mock import patch

from apscheduler.triggers.calendarinterval import CalendarIntervalTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.scheduler import _configured_benchmark_trigger, _is_already_active_server


class BenchmarkScheduleTest(unittest.TestCase):
    def test_calendar_schedule_runs_every_n_days_at_fixed_time(self):
        settings = {
            'benchmark_schedule_mode': 'calendar',
            'benchmark_schedule_days': '3',
            'benchmark_schedule_time': '02:30',
            'benchmark_schedule_anchor': '2026-10-16',
        }
        with patch('app.database.get_setting', side_effect=lambda key, default='': settings.get(key, default)):
            trigger = _configured_benchmark_trigger()

        self.assertIsInstance(trigger, CalendarIntervalTrigger)
        self.assertEqual(trigger.days, 3)
        self.assertEqual(trigger.start_date.isoformat(), '2026-10-16')
        self.assertEqual((trigger._time.hour, trigger._time.minute), (2, 30))

    def test_interval_schedule_remains_backward_compatible(self):
        settings = {
            'benchmark_schedule_mode': 'interval',
            'test_interval_hours': '6',
        }
        with patch('app.database.get_setting', side_effect=lambda key, default='': settings.get(key, default)):
            trigger = _configured_benchmark_trigger()

        self.assertIsInstance(trigger, IntervalTrigger)
        self.assertEqual(trigger.interval.total_seconds(), 6 * 3600)

    def test_current_best_server_does_not_trigger_a_switch(self):
        self.assertTrue(_is_already_active_server('Fuyue', 'Fuyue'))
        self.assertFalse(_is_already_active_server('Fuyue', 'Dalim'))


if __name__ == '__main__':
    unittest.main()
