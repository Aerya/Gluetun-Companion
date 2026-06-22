"""Unit tests for the sidecar's TCP-handshake stability probe.

The sidecar (`sidecar/app.py`) is a standalone Flask module, not part of the
`app` package, so it is loaded by path under a distinct name to avoid colliding
with the repo-root `app` package. All tests mock the connector — no real
network traffic is generated.
"""

import importlib.util
import socket
import unittest
from pathlib import Path
from unittest.mock import patch

_SIDECAR_PATH = Path(__file__).resolve().parents[1] / 'sidecar' / 'app.py'
_spec = importlib.util.spec_from_file_location('sidecar_app', _SIDECAR_PATH)
sidecar = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sidecar)


class StatsFromSamplesTest(unittest.TestCase):
    def test_loss_min_max_and_jitter(self):
        stats = sidecar._stats_from_samples([10.0, 12.0, 14.0], attempts=4, failures=1)
        self.assertEqual(stats['packet_loss_pct'], 25.0)
        self.assertEqual(stats['ping_min_ms'], 10.0)
        self.assertEqual(stats['ping_max_ms'], 14.0)
        self.assertGreater(stats['jitter_ms'], 0.0)

    def test_single_sample_has_zero_jitter(self):
        stats = sidecar._stats_from_samples([8.0], attempts=1, failures=0)
        self.assertEqual(stats['jitter_ms'], 0.0)
        self.assertEqual(stats['packet_loss_pct'], 0.0)
        self.assertEqual(stats['ping_min_ms'], 8.0)

    def test_fully_failed_target_reports_100pct_and_null_rtts(self):
        stats = sidecar._stats_from_samples([], attempts=20, failures=20)
        self.assertEqual(stats['packet_loss_pct'], 100.0)
        self.assertIsNone(stats['jitter_ms'])
        self.assertIsNone(stats['ping_min_ms'])
        self.assertIsNone(stats['ping_max_ms'])


class AggregateStabilityTest(unittest.TestCase):
    def test_healthy_targets_report_zero_loss(self):
        samples = [
            {'target': '1.1.1.1', 'rtts': [22.0, 23.0, 21.0], 'attempts': 3, 'failures': 0},
            {'target': '8.8.8.8', 'rtts': [25.0, 24.0, 26.0], 'attempts': 3, 'failures': 0},
            {'target': '9.9.9.9', 'rtts': [23.0, 22.0, 24.0], 'attempts': 3, 'failures': 0},
        ]
        agg = sidecar._aggregate_stability(samples)
        self.assertEqual(agg['packet_loss_pct'], 0.0)
        self.assertEqual(agg['ping_min_ms'], 21.0)
        self.assertEqual(agg['ping_max_ms'], 26.0)
        self.assertEqual(set(agg), {'jitter_ms', 'packet_loss_pct', 'ping_min_ms', 'ping_max_ms'})

    def test_loss_is_pooled_not_mean_of_percentages(self):
        # Unequal attempt counts: a healthy target with many samples plus a
        # short, fully-unreachable one. Mean-of-percentages → (0 + 100) / 2 =
        # 50 %. Pooled → 2 failures / 12 attempts = 16.7 %. The pooled form is
        # the one that does not over-weight a single unreachable target.
        samples = [
            {'target': 'a', 'rtts': [10.0] * 10, 'attempts': 10, 'failures': 0},
            {'target': 'b', 'rtts': [], 'attempts': 2, 'failures': 2},
        ]
        agg = sidecar._aggregate_stability(samples)
        self.assertEqual(agg['packet_loss_pct'], round(100 * 2 / 12, 1))  # 16.7
        self.assertNotEqual(agg['packet_loss_pct'], 50.0)

    def test_jitter_isolated_from_per_target_baseline_offset(self):
        # Two individually-steady targets with a 100 ms baseline gap between
        # them. Pooling RTTs would blow jitter up to ~50 ms; the mean-of-
        # per-target-stddev keeps it at ~0, while min/max still span the range.
        samples = [
            {'target': 'a', 'rtts': [10.0, 10.0, 10.0], 'attempts': 3, 'failures': 0},
            {'target': 'b', 'rtts': [110.0, 110.0, 110.0], 'attempts': 3, 'failures': 0},
        ]
        agg = sidecar._aggregate_stability(samples)
        self.assertEqual(agg['jitter_ms'], 0.0)
        self.assertEqual(agg['ping_min_ms'], 10.0)
        self.assertEqual(agg['ping_max_ms'], 110.0)

    def test_no_usable_sample_returns_none(self):
        samples = [{'target': 'a', 'rtts': [], 'attempts': 20, 'failures': 20}]
        self.assertIsNone(sidecar._aggregate_stability(samples))

    def test_empty_input_returns_none(self):
        self.assertIsNone(sidecar._aggregate_stability([]))


class TcpConnectOnceTest(unittest.TestCase):
    def test_refused_connection_is_reachable_not_loss(self):
        with patch.object(sidecar.socket, 'create_connection',
                          side_effect=ConnectionRefusedError()):
            rtt = sidecar._tcp_connect_once('1.1.1.1', 443, timeout=1.0)
        self.assertIsInstance(rtt, float)
        self.assertGreaterEqual(rtt, 0.0)

    def test_timeout_propagates_as_oserror(self):
        with patch.object(sidecar.socket, 'create_connection',
                          side_effect=socket.timeout('timed out')):
            with self.assertRaises(OSError):
                sidecar._tcp_connect_once('1.1.1.1', 443, timeout=1.0)

    def test_success_closes_socket_and_returns_rtt(self):
        closed = {'value': False}

        class _FakeSock:
            def close(self):
                closed['value'] = True

        with patch.object(sidecar.socket, 'create_connection', return_value=_FakeSock()):
            rtt = sidecar._tcp_connect_once('1.1.1.1', 443, timeout=1.0)
        self.assertTrue(closed['value'])
        self.assertIsInstance(rtt, float)


class TcpProbeSamplesTest(unittest.TestCase):
    def test_counts_successes_and_failures(self):
        calls = {'n': 0}

        def fake_connect(ip, port, timeout):
            calls['n'] += 1
            if calls['n'] == 3:
                raise socket.timeout('timed out')
            return 12.5

        with patch.object(sidecar, '_tcp_connect_once', side_effect=fake_connect):
            out = sidecar._tcp_probe_samples('1.1.1.1', count=5, interval=0)
        self.assertEqual(out['attempts'], 5)
        self.assertEqual(out['failures'], 1)
        self.assertEqual(len(out['rtts']), 4)
        self.assertEqual(out['target'], '1.1.1.1')

    def test_port_negotiation_falls_back_to_second_port(self):
        def fake_connect(ip, port, timeout):
            if port == 443:
                raise socket.timeout('blocked')
            return 9.0

        with patch.object(sidecar, '_tcp_connect_once', side_effect=fake_connect):
            out = sidecar._tcp_probe_samples('1.1.1.1', count=4, interval=0, ports=[443, 53])
        self.assertEqual(out['failures'], 0)
        self.assertEqual(len(out['rtts']), 4)

    def test_unreachable_target_is_bounded_to_first_port(self):
        seen_ports = []

        def fake_connect(ip, port, timeout):
            seen_ports.append(port)
            raise socket.timeout('down')

        with patch.object(sidecar, '_tcp_connect_once', side_effect=fake_connect):
            out = sidecar._tcp_probe_samples('1.1.1.1', count=3, interval=0, ports=[443, 53])
        self.assertEqual(out['failures'], 3)
        self.assertEqual(out['rtts'], [])
        # First sample probes both ports; once both fail, only the first port is
        # retried — this bounds the time spent on a fully unreachable target.
        self.assertEqual(seen_ports, [443, 53, 443, 443])


class TcpProbeTargetTest(unittest.TestCase):
    def test_returns_per_target_public_schema(self):
        with patch.object(
            sidecar, '_tcp_probe_samples',
            return_value={'target': '1.1.1.1', 'rtts': [10.0, 12.0], 'attempts': 2, 'failures': 0},
        ):
            out = sidecar._tcp_probe_target('1.1.1.1', 2, 0)
        self.assertEqual(
            set(out),
            {'target', 'jitter_ms', 'packet_loss_pct', 'ping_min_ms', 'ping_max_ms'},
        )
        self.assertEqual(out['target'], '1.1.1.1')
        self.assertEqual(out['packet_loss_pct'], 0.0)


class MeasureStabilityTest(unittest.TestCase):
    def test_aggregates_targets_without_network(self):
        per_target = {
            '1.1.1.1': {'target': '1.1.1.1', 'rtts': [22.0, 23.0], 'attempts': 2, 'failures': 0},
            '8.8.8.8': {'target': '8.8.8.8', 'rtts': [25.0, 24.0], 'attempts': 2, 'failures': 0},
            '9.9.9.9': {'target': '9.9.9.9', 'rtts': [23.0, 22.0], 'attempts': 2, 'failures': 0},
        }

        def fake_samples(target, count, interval, *args, **kwargs):
            return per_target[target]

        with patch.object(sidecar, '_tcp_probe_samples', side_effect=fake_samples):
            out = sidecar._measure_stability(count=2, interval=0)
        self.assertEqual(
            set(out),
            {'jitter_ms', 'packet_loss_pct', 'ping_min_ms', 'ping_max_ms'},
        )
        self.assertEqual(out['packet_loss_pct'], 0.0)
        self.assertEqual(out['ping_min_ms'], 22.0)
        self.assertEqual(out['ping_max_ms'], 25.0)

    def test_returns_none_when_all_targets_unreachable(self):
        def fake_samples(target, count, interval, *args, **kwargs):
            return {'target': target, 'rtts': [], 'attempts': 20, 'failures': 20}

        with patch.object(sidecar, '_tcp_probe_samples', side_effect=fake_samples):
            self.assertIsNone(sidecar._measure_stability(count=20, interval=0))


if __name__ == '__main__':
    unittest.main()
