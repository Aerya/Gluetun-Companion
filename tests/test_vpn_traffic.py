"""Real VPN tunnel traffic monitoring: counters, resets, persistence."""

import os
import tempfile
import unittest
from unittest.mock import MagicMock

from app import database
from app import vpn_traffic as vt
from app.vpn_traffic import (
    COUNTER_32, CounterSample, DockerCounterReader, Reading, TrafficMonitor,
    compute_delta, parse_proc_net_dev, pick_vpn_interface, split_over_minutes,
)

PROC_NET_DEV = """Inter-|   Receive                                                |  Transmit
 face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed
    lo:    1200      12    0    0    0     0          0         0     1200      12    0    0    0     0       0          0
  eth0: 98765432  80000    0    0    0     0          0         0 12345678   60000    0    0    0     0       0          0
  tun0: 5000000    4000    0    0    0     0          0         0   700000    3000    0    0    0     0       0          0
"""

# 2026-11-15 12:00:00 UTC — a fixed, minute-aligned origin for fake clocks.
T0 = 1794744000.0


class FakeClock:
    def __init__(self, t=T0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, secs):
        self.t += secs
        return self.t


class FakeReader:
    """Return queued readings; the last one is repeated."""

    def __init__(self):
        self.queue = []
        self.last = Reading('error', detail='no reading')

    def push(self, reading):
        self.queue.append(reading)

    def read(self, _container):
        if self.queue:
            self.last = self.queue.pop(0)
        return self.last


def ok(rx, tx, identity='c1|start1|tun0|5', health='healthy'):
    return Reading('ok', identity=identity, rx=rx, tx=tx, iface='tun0',
                   provider='airvpn', protocol='wireguard', container_id='c1',
                   health=health)


class DbTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        database.init_db(os.path.join(self._tmp.name, 'companion.db'))
        database.set_setting('traffic_monitor_interval', '5')
        self.clock = FakeClock()

    def tearDown(self):
        self._tmp.cleanup()

    def monitor(self, reader=None):
        return TrafficMonitor('gluetun', reader=reader or FakeReader(), clock=self.clock)

    def totals(self):
        with database.get_db() as db:
            return dict(db.execute('SELECT * FROM vpn_traffic_totals WHERE id = 1').fetchone())

    def sums(self, table):
        with database.get_db() as db:
            row = db.execute(
                f'SELECT COALESCE(SUM(rx_bytes),0) AS rx, COALESCE(SUM(tx_bytes),0) AS tx FROM {table}'
            ).fetchone()
        return row['rx'], row['tx']

    def feed(self, mon, reader, readings, step=5):
        for reading in readings:
            reader.push(reading)
            mon.tick()
            self.clock.advance(step)


# ── Pure helpers ────────────────────────────────────────────────────────────

class ParsingTest(unittest.TestCase):
    def test_parse_proc_net_dev(self):
        counters = parse_proc_net_dev(PROC_NET_DEV)
        self.assertEqual(counters['tun0'], (5000000, 700000))
        self.assertEqual(counters['eth0'], (98765432, 12345678))
        self.assertNotIn('face |bytes', counters)

    def test_parse_ignores_garbage(self):
        self.assertEqual(parse_proc_net_dev('nonsense\n  x: a b c'), {})

    def test_interface_selection(self):
        counters = parse_proc_net_dev(PROC_NET_DEV)
        self.assertEqual(pick_vpn_interface(counters, None), 'tun0')
        self.assertEqual(pick_vpn_interface(counters, 'tun0'), 'tun0')
        # An explicit VPN_INTERFACE that is absent means "tunnel down", never
        # a substitution with another interface (eth0 would be host traffic).
        self.assertIsNone(pick_vpn_interface(counters, 'wg1'))
        self.assertEqual(pick_vpn_interface({'lo': (0, 0), 'wg0': (1, 1)}, None), 'wg0')
        self.assertIsNone(pick_vpn_interface({'lo': (0, 0), 'eth0': (1, 1)}, None))
        self.assertIsNone(pick_vpn_interface({'tun1': (0, 0), 'tun2': (1, 1)}, None))

    def test_split_over_minutes_is_exact(self):
        parts = split_over_minutes(T0 + 30, T0 + 30 + 600, 1_000_003)
        self.assertEqual(sum(v for _, v in parts), 1_000_003)
        self.assertEqual(len(parts), 11)
        self.assertTrue(all(v >= 0 for _, v in parts))
        self.assertEqual(split_over_minutes(T0, T0 + 5, 0), [])


class ComputeDeltaTest(unittest.TestCase):
    def s(self, rx, tx, ts, identity='a'):
        return CounterSample(identity, rx, tx, ts)

    def test_first_sample_is_only_a_baseline(self):
        d = compute_delta(None, self.s(10**9, 10**8, T0), 5)
        self.assertEqual((d.rx, d.tx, d.event), (0, 0, 'baseline'))
        self.assertIsNone(d.rx_rate)

    def test_regular_rate(self):
        d = compute_delta(self.s(1000, 500, T0), self.s(6_251_000, 1_250_500, T0 + 5), 5)
        self.assertEqual((d.rx, d.tx, d.event), (6_250_000, 1_250_000, 'ok'))
        self.assertAlmostEqual(d.rx_rate * 8 / 1e6, 10.0)   # 10 Mbit/s
        self.assertAlmostEqual(d.tx_rate * 8 / 1e6, 2.0)

    def test_reconnection_counts_new_counter_only(self):
        prev = self.s(50_000_000, 9_000_000, T0, 'tunnel-1')
        d = compute_delta(prev, self.s(30_000, 2_000, T0 + 5, 'tunnel-2'), 5)
        self.assertEqual((d.rx, d.tx, d.event), (30_000, 2_000, 'reset'))
        self.assertIsNone(d.rx_rate)   # no artificial peak on reconnection

    def test_new_counter_higher_than_old_is_not_a_difference(self):
        # The new tunnel already carried more than the old one: counting the
        # difference would lose traffic, counting both would double it.
        prev = self.s(1_000, 1_000, T0, 'tunnel-1')
        d = compute_delta(prev, self.s(5_000, 3_000, T0 + 5, 'tunnel-2'), 5)
        self.assertEqual((d.rx, d.tx), (5_000, 3_000))

    def test_never_negative(self):
        d = compute_delta(self.s(10**12, 10**12, T0), self.s(10, 10, T0 + 5), 5)
        self.assertGreaterEqual(d.rx, 0)
        self.assertGreaterEqual(d.tx, 0)

    def test_32bit_overflow(self):
        prev = self.s(COUNTER_32 - 1_000, 100, T0)
        d = compute_delta(prev, self.s(4_000, 200, T0 + 5), 5)
        self.assertEqual((d.rx, d.tx, d.event), (5_000, 100, 'wrap'))

    def test_implausible_overflow_is_a_restart(self):
        # 2^64 wrap from a small value would mean exabytes in 5 s.
        prev = self.s(COUNTER_32 + 10, 100, T0)
        d = compute_delta(prev, self.s(4_000, 200, T0 + 5), 5)
        self.assertEqual(d.event, 'reset')
        self.assertEqual(d.rx, 4_000)

    def test_glitch_is_discarded(self):
        prev = self.s(0, 0, T0, 'x')
        d = compute_delta(prev, self.s(10**15, 0, T0 + 1, 'y'), 5)
        self.assertEqual((d.rx, d.tx, d.event), (0, 0, 'glitch'))

    def test_gap_keeps_bytes_without_rate(self):
        d = compute_delta(self.s(0, 0, T0), self.s(3_600_000, 0, T0 + 3600), 5)
        self.assertEqual((d.rx, d.event), (3_600_000, 'gap'))
        self.assertIsNone(d.rx_rate)

    def test_clock_going_backwards(self):
        d = compute_delta(self.s(0, 0, T0), self.s(100, 0, T0 - 10), 5)
        self.assertEqual((d.rx, d.event), (0, 'clock'))


# ── Monitor ─────────────────────────────────────────────────────────────────

class MonitorTest(DbTestCase):
    def test_no_invented_history_and_steady_counting(self):
        reader = FakeReader()
        mon = self.monitor(reader)
        self.feed(mon, reader, [ok(10**9, 10**8), ok(10**9 + 1000, 10**8 + 100),
                                ok(10**9 + 3000, 10**8 + 300)])
        mon.flush()
        totals = self.totals()
        self.assertEqual((totals['rx_bytes'], totals['tx_bytes']), (3000, 300))
        self.assertEqual(totals['since'], T0)
        for table in ('vpn_traffic_minute', 'vpn_traffic_hour',
                      'vpn_traffic_day', 'vpn_traffic_month'):
            self.assertEqual(self.sums(table), (3000, 300), table)

    def test_live_payload(self):
        reader = FakeReader()
        mon = self.monitor(reader)
        self.feed(mon, reader, [ok(0, 0), ok(6_250_000, 1_250_000)], step=0)
        self.clock.advance(0)
        live = mon.live()
        # second tick happened at the same fake time: delta ignored (clock)
        self.assertEqual(live['status'], 'connected')

        mon2 = self.monitor(reader)
        reader.push(ok(0, 0))
        mon2.tick()
        self.clock.advance(5)
        reader.push(ok(6_250_000, 1_250_000))
        mon2.tick()
        live = mon2.live()
        self.assertEqual(live['status'], 'connected')
        self.assertAlmostEqual(live['rx_rate'], 1_250_000)
        self.assertEqual(live['totals']['all']['rx'], 6_250_000)
        self.assertEqual(live['totals']['today']['tx'], 1_250_000)
        self.assertEqual(live['iface'], 'tun0')
        self.assertEqual(live['protocol'], 'wireguard')
        self.assertTrue(live['samples'])

    def test_reconnection_and_gluetun_restart(self):
        reader = FakeReader()
        mon = self.monitor(reader)
        self.feed(mon, reader, [
            ok(1_000_000, 100_000, 'c1|s1|tun0|5'),
            ok(1_500_000, 150_000, 'c1|s1|tun0|5'),    # +500k / +50k
            ok(20_000, 2_000, 'c1|s1|tun0|9'),         # server switch: tun0 recreated
            ok(30_000, 3_000, 'c1|s1|tun0|9'),         # +10k / +1k
            ok(4_000, 400, 'c1|s2|tun0|5'),            # docker restart: same ID, new start
            ok(5_000, 500, 'c2|s3|tun0|5'),            # recreated container
        ])
        mon.flush()
        totals = self.totals()
        self.assertEqual(totals['rx_bytes'], 500_000 + 20_000 + 10_000 + 4_000 + 5_000)
        self.assertEqual(totals['tx_bytes'], 50_000 + 2_000 + 1_000 + 400 + 500)

    def test_tunnel_temporarily_unavailable(self):
        reader = FakeReader()
        mon = self.monitor(reader)
        self.feed(mon, reader, [ok(1000, 100)])
        self.feed(mon, reader, [Reading('tunnel_down', iface='tun0', detail='no_vpn_interface')])
        live = mon.live()
        self.assertEqual(live['status'], 'tunnel_down')
        self.assertIsNone(live['rx_rate'])
        # Back with the same interface: the bytes of the outage are real.
        self.feed(mon, reader, [ok(4000, 400)])
        mon.flush()
        self.assertEqual(self.totals()['rx_bytes'], 3000)
        self.assertIsNotNone(mon.live()['samples'][1][0])
        self.assertIsNone(mon.live()['samples'][1][1])   # explicit hole

    def test_container_down_and_forbidden_states(self):
        reader = FakeReader()
        mon = self.monitor(reader)
        self.feed(mon, reader, [Reading('container_down', detail='not_running')])
        self.assertEqual(mon.live()['status'], 'container_down')
        self.feed(mon, reader, [Reading('forbidden', detail='exec_forbidden')])
        live = mon.live()
        self.assertEqual((live['status'], live['reason']), ('unavailable', 'exec_forbidden'))
        self.assertIsNone(live['rx_rate'])
        # Refused exec is not hammered: the next tick waits.
        calls = len(reader.queue)
        reader.push(ok(1, 1))
        mon.tick()
        self.assertEqual(len(reader.queue), calls + 1)
        mon.wake()
        mon.tick()
        self.assertEqual(mon.live()['status'], 'connected')

    def test_stale_samples_are_not_shown_as_live(self):
        reader = FakeReader()
        mon = self.monitor(reader)
        self.feed(mon, reader, [ok(0, 0), ok(1000, 1000)])
        self.clock.advance(120)
        live = mon.live()
        self.assertEqual((live['status'], live['reason']), ('unavailable', 'stale'))
        self.assertIsNone(live['rx_rate'])

    def test_companion_restart_recovers_unflushed_traffic_once(self):
        reader = FakeReader()
        mon = self.monitor(reader)
        self.feed(mon, reader, [ok(1000, 100), ok(2000, 200), ok(5000, 500)])
        # Crash: nothing flushed since the baseline.
        self.assertEqual(self.totals()['rx_bytes'], 0)
        self.clock.advance(300)
        reader2 = FakeReader()
        mon2 = self.monitor(reader2)
        self.feed(mon2, reader2, [ok(9000, 900)])
        mon2.flush()
        totals = self.totals()
        self.assertEqual((totals['rx_bytes'], totals['tx_bytes']), (8000, 800))
        # Spread over the gap: no minute holds the whole volume.
        with database.get_db() as db:
            biggest = db.execute('SELECT MAX(rx_bytes) AS m FROM vpn_traffic_minute').fetchone()['m']
        self.assertLess(biggest, 8000)

    def test_companion_and_gluetun_restart_together(self):
        reader = FakeReader()
        mon = self.monitor(reader)
        self.feed(mon, reader, [ok(10_000, 1_000), ok(20_000, 2_000)])
        mon.flush()
        self.clock.advance(600)
        reader2 = FakeReader()
        mon2 = self.monitor(reader2)
        self.feed(mon2, reader2, [ok(3_000, 300, 'c9|s9|tun0|5')])
        mon2.flush()
        self.assertEqual(self.totals()['rx_bytes'], 10_000 + 3_000)

    def test_two_collectors_never_double_count(self):
        r1, r2 = FakeReader(), FakeReader()
        m1, m2 = self.monitor(r1), self.monitor(r2)
        for rx in (1000, 2000, 3000, 4000):
            r1.push(ok(rx, rx // 10))
            r2.push(ok(rx, rx // 10))
            m1.tick()
            m2.tick()
            m1.flush()
            m2.flush()
            self.clock.advance(5)
        totals = self.totals()
        self.assertLessEqual(totals['rx_bytes'], 3000)
        self.assertEqual(self.sums('vpn_traffic_minute')[0], totals['rx_bytes'])

    def test_benchmark_traffic_is_tagged(self):
        reader = FakeReader()
        mon = self.monitor(reader)
        self.feed(mon, reader, [ok(0, 0), ok(1000, 100)])
        database.set_setting('benchmark_running', '1')
        self.feed(mon, reader, [ok(6000, 600)])
        database.set_setting('benchmark_running', '0')
        mon.flush()
        totals = self.totals()
        self.assertEqual(totals['rx_bytes'], 6000)
        self.assertEqual(totals['bench_rx_bytes'], 5000)

    def test_disable_then_enable_does_not_count_disabled_period(self):
        reader = FakeReader()
        mon = self.monitor(reader)
        self.feed(mon, reader, [ok(1000, 100), ok(2000, 200)])
        database.set_setting('traffic_monitor_enabled', '0')
        mon.tick()
        self.assertEqual(mon.live()['status'], 'disabled')
        self.clock.advance(3600)
        database.set_setting('traffic_monitor_enabled', '1')
        self.feed(mon, reader, [ok(900_000, 90_000), ok(901_000, 90_100)])
        mon.flush()
        self.assertEqual(self.totals()['rx_bytes'], 1000 + 1000)

    def test_disabled_at_boot_forgets_old_baseline(self):
        reader = FakeReader()
        mon = self.monitor(reader)
        self.feed(mon, reader, [ok(1000, 100)])
        database.set_setting('traffic_monitor_enabled', '0')
        mon2 = self.monitor(FakeReader())
        mon2.tick()
        database.set_setting('traffic_monitor_enabled', '1')
        reader3 = FakeReader()
        mon3 = self.monitor(reader3)
        self.clock.advance(3600)
        self.feed(mon3, reader3, [ok(500_000, 50_000)])
        mon3.flush()
        self.assertEqual(self.totals()['rx_bytes'], 0)

    def test_reset_is_voluntary_and_rebaselines(self):
        reader = FakeReader()
        mon = self.monitor(reader)
        self.feed(mon, reader, [ok(0, 0), ok(5000, 500)])
        mon.flush()
        mon.reset()
        totals = self.totals()
        self.assertEqual((totals['rx_bytes'], totals['since']), (0, None))
        self.assertEqual(self.sums('vpn_traffic_hour'), (0, 0))
        self.feed(mon, reader, [ok(9000, 900), ok(9500, 950)])
        mon.flush()
        totals = self.totals()
        self.assertEqual(totals['rx_bytes'], 500)
        self.assertIsNotNone(totals['since'])

    def test_retention_purge(self):
        reader = FakeReader()
        mon = self.monitor(reader)
        self.feed(mon, reader, [ok(0, 0), ok(1000, 100)])
        mon.flush()
        with database.get_db() as db:
            db.execute('INSERT INTO vpn_traffic_minute (bucket, rx_bytes, tx_bytes) VALUES (?, 1, 1)',
                       (int(T0 - 3 * 86400),))
            db.execute('INSERT INTO vpn_traffic_hour (bucket, rx_bytes, tx_bytes) VALUES (?, 1, 1)',
                       (int(T0 - 100 * 86400),))
            db.execute('INSERT INTO vpn_traffic_hour (bucket, rx_bytes, tx_bytes) VALUES (?, 1, 1)',
                       (int(T0 - 40 * 86400),))
            db.execute("INSERT INTO vpn_traffic_day (day, rx_bytes, tx_bytes) VALUES ('2020-01-01', 1, 1)")
            db.execute("INSERT INTO vpn_traffic_month (month, rx_bytes, tx_bytes) VALUES ('2020-01', 1, 1)")
        mon.purge()
        with database.get_db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM vpn_traffic_minute WHERE bucket < ?',
                                        (int(T0 - 86400),)).fetchone()[0], 0)
            hours = [r[0] for r in db.execute('SELECT bucket FROM vpn_traffic_hour')]
            self.assertIn(int(T0 - 40 * 86400), hours)          # 90 days kept by default
            self.assertNotIn(int(T0 - 100 * 86400), hours)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM vpn_traffic_day WHERE day='2020-01-01'").fetchone()[0], 0)
            # Monthly totals are tiny and kept forever.
            self.assertEqual(db.execute("SELECT COUNT(*) FROM vpn_traffic_month WHERE month='2020-01'").fetchone()[0], 1)

    def test_long_gap_does_not_fill_minute_table(self):
        reader = FakeReader()
        mon = self.monitor(reader)
        self.feed(mon, reader, [ok(0, 0)])
        mon.flush()
        self.clock.advance(10 * 86400)
        self.feed(mon, reader, [ok(10**9, 10**8)])
        mon.flush()
        with database.get_db() as db:
            minutes = db.execute('SELECT COUNT(*) FROM vpn_traffic_minute').fetchone()[0]
        self.assertLessEqual(minutes, 48 * 60 + 2)
        self.assertEqual(self.sums('vpn_traffic_hour'), (10**9, 10**8))
        self.assertEqual(self.sums('vpn_traffic_month'), (10**9, 10**8))


class HistoryTest(DbTestCase):
    def test_ranges_and_no_data_before_activation(self):
        reader = FakeReader()
        mon = self.monitor(reader)
        self.feed(mon, reader, [ok(0, 0)] + [ok(i * 60_000, i * 6_000) for i in range(1, 30)], step=10)
        for key in ('live', '1h', '24h', '7d', '30d', 'months'):
            with self.subTest(range=key):
                data = mon.history(key)
                self.assertEqual(data['range'], key)
                self.assertIn('summary', data)
        h24 = mon.history('24h')
        before = [p for p in h24['rate']['points'] if p['t'] + 300 <= T0]
        self.assertTrue(before)
        self.assertTrue(all(p['rx'] is None for p in before))   # not zero: unknown
        self.assertEqual(h24['summary']['rx'], 29 * 60_000)
        months = mon.history('months')
        self.assertEqual(len(months['volume']['points']), 1)
        self.assertEqual(months['volume']['points'][0]['rx'], 29 * 60_000)
        with self.assertRaises(ValueError):
            mon.history('bogus')


class HealthTest(DbTestCase):
    """The VPN interface alone is not proof that the VPN works."""

    def test_states_follow_gluetun_healthcheck(self):
        for health, state, reason in (
            ('healthy', 'connected', ''),
            ('unhealthy', 'unhealthy', 'gluetun_unhealthy'),
            ('starting', 'unverified', 'health_starting'),
            ('', 'unverified', 'no_healthcheck'),
        ):
            with self.subTest(health=health):
                reader = FakeReader()
                mon = self.monitor(reader)
                self.feed(mon, reader, [ok(1_000, 100, health=health),
                                        ok(51_000, 5_100, health=health)])
                live = mon.live()
                self.assertEqual((live['status'], live['reason']), (state, reason))
                # Counters are measured whatever the health: rates stay visible.
                self.assertAlmostEqual(live['rx_rate'], 10_000)
                snap = mon.prometheus_snapshot()
                self.assertEqual(snap['tunnel_up'], 1)
                self.assertEqual(snap['available'], 1)
                self.assertEqual(snap['healthy'], {'connected': 1, 'unhealthy': 0}.get(state))

    def test_unhealthy_then_recovered_counts_continuously(self):
        reader = FakeReader()
        mon = self.monitor(reader)
        self.feed(mon, reader, [ok(0, 0), ok(5_000, 500, health='unhealthy'), ok(9_000, 900)])
        self.assertEqual(mon.live()['status'], 'connected')
        self.assertEqual(mon.live()['totals']['all']['rx'], 9_000)


class LiveHistorySummaryTest(DbTestCase):
    def test_live_range_summary_counts_volumes(self):
        reader = FakeReader()
        mon = self.monitor(reader)
        self.feed(mon, reader, [ok(0, 0), ok(60_000, 6_000), ok(90_000, 9_000)])
        h = mon.history('live')
        self.assertEqual((h['summary']['rx'], h['summary']['tx']), (90_000, 9_000))
        self.assertEqual(h['summary']['total'], 99_000)
        self.assertGreater(h['summary']['peak_rx'], 0)
        self.assertNotIn('summary_points', h)


# ── Docker reader ───────────────────────────────────────────────────────────

class ApiError(Exception):
    def __init__(self, code):
        super().__init__(f'HTTP {code}')
        self.response = MagicMock(status_code=code)


class DockerReaderTest(unittest.TestCase):
    def reader(self, inspect=None, outputs=None, exec_error=None, probe_code=404):
        """``probe_code``: answer to the exec permission probe (404 = allowed,
        403 = socket proxy without EXEC=1)."""
        api = MagicMock()
        api.base_url = f'tcp://fake-{id(api)}:2375'
        api.inspect_container.return_value = inspect or {
            'Id': 'abc', 'State': {'Running': True, 'StartedAt': '2026-11-15T10:00:00Z',
                                   'Health': {'Status': 'healthy'}},
            'Config': {'Env': ['VPN_SERVICE_PROVIDER=AirVPN', 'VPN_TYPE=wireguard']},
        }
        api.exec_create.return_value = {'Id': 'e1'}
        results = iter([(o, None) for o in (outputs or [])])
        self.probes = 0

        def exec_start(exec_id, *args, **kwargs):
            if exec_id == '0' * 64:
                self.probes += 1
                raise ApiError(probe_code)
            if exec_error:
                raise exec_error
            return next(results)

        api.exec_start.side_effect = exec_start
        client = MagicMock(api=api)
        return DockerCounterReader(client_factory=lambda: client), api

    def test_reads_tun0_with_strong_identity(self):
        reader, api = self.reader(outputs=[(PROC_NET_DEV + '7\n').encode()])
        r = reader.read('gluetun')
        self.assertEqual(r.state, 'ok')
        self.assertEqual((r.rx, r.tx), (5000000, 700000))
        self.assertEqual(r.identity, 'abc|2026-11-15T10:00:00Z|tun0|7')
        self.assertEqual((r.provider, r.protocol), ('AirVPN', 'wireguard'))
        cmd = api.exec_create.call_args[0][1]
        self.assertEqual(cmd[0], 'cat')                 # no shell
        self.assertEqual(api.exec_create.call_args[1]['privileged'], False)
        # exec targets the container *name*, so a path-filtering proxy can
        # allow /containers/gluetun/exec and nothing else.
        self.assertEqual(api.exec_create.call_args[0][0], 'gluetun')
        self.assertEqual(r.health, 'healthy')

    def test_container_recreated_during_read_is_discarded(self):
        reader, api = self.reader(outputs=[(PROC_NET_DEV + '7\n').encode()])
        first = {'Id': 'abc', 'State': {'Running': True, 'StartedAt': 'a'}, 'Config': {}}
        second = {'Id': 'def', 'State': {'Running': True, 'StartedAt': 'b'}, 'Config': {}}
        api.inspect_container.side_effect = [first, second]
        r = reader.read('gluetun')
        self.assertEqual((r.state, r.detail), ('error', 'container_changed'))

    def test_dedicated_traffic_docker_host(self):
        import docker
        from unittest.mock import patch
        with patch.dict(os.environ, {'TRAFFIC_DOCKER_HOST': 'tcp://traffic-proxy:2375'}), \
             patch.object(docker, 'DockerClient') as dedicated, \
             patch.object(docker, 'from_env') as default:
            DockerCounterReader()._get_client()
        dedicated.assert_called_once_with(base_url='tcp://traffic-proxy:2375', timeout=15)
        default.assert_not_called()

    def test_discovers_wg0_in_the_same_tick(self):
        text = PROC_NET_DEV.replace('tun0', 'wg0')
        reader, api = self.reader(outputs=[text.encode(), (text + '4\n').encode()])
        r = reader.read('gluetun')
        self.assertEqual((r.state, r.iface), ('ok', 'wg0'))
        self.assertTrue(r.identity.endswith('|wg0|4'))
        self.assertEqual(api.exec_create.call_count, 2)

    def test_forbidden_exec_with_socket_proxy(self):
        reader, _ = self.reader(exec_error=ApiError(403))
        r = reader.read('gluetun')
        self.assertEqual((r.state, r.detail), ('forbidden', 'exec_forbidden'))

    def test_refused_exec_creates_no_exec_instance(self):
        reader, api = self.reader(probe_code=403)
        for _ in range(20):
            r = reader.read('gluetun')
            self.assertEqual((r.state, r.detail), ('forbidden', 'exec_forbidden'))
        api.exec_create.assert_not_called()
        self.assertEqual(self.probes, 1)       # cached until the gate re-checks

    def test_405_refusal_from_path_filtering_proxy(self):
        reader, api = self.reader(probe_code=405)
        self.assertEqual(reader.read('gluetun').state, 'forbidden')
        api.exec_create.assert_not_called()

    def test_reads_again_once_exec_is_granted(self):
        from app import docker_exec
        reader, api = self.reader(probe_code=403,
                                  outputs=[(PROC_NET_DEV + '7\n').encode()])
        self.assertEqual(reader.read('gluetun').state, 'forbidden')
        # Operator sets EXEC=1; the monitor's wake() (settings saved) or the
        # gate's periodic re-check picks it up without restarting Companion.
        docker_exec.reset()
        api.exec_start.side_effect = None
        api.exec_start.side_effect = lambda exec_id, *a, **k: (
            (_ for _ in ()).throw(ApiError(404)) if exec_id == '0' * 64
            else ((PROC_NET_DEV + '7\n').encode(), None))
        self.assertEqual(reader.read('gluetun').state, 'ok')
        self.assertEqual(api.exec_create.call_count, 1)

    def test_stopped_container(self):
        reader, api = self.reader(inspect={'Id': 'abc', 'State': {'Running': False}, 'Config': {}})
        self.assertEqual(reader.read('gluetun').state, 'container_down')
        api.exec_create.assert_not_called()

    def test_missing_interface_is_tunnel_down(self):
        text = '\n'.join(l for l in PROC_NET_DEV.splitlines() if 'tun0' not in l)
        reader, _ = self.reader(outputs=[text.encode()])
        r = reader.read('gluetun')
        self.assertEqual(r.state, 'tunnel_down')

    def test_invalid_vpn_interface_env_is_rejected(self):
        reader, api = self.reader(inspect={
            'Id': 'abc', 'State': {'Running': True},
            'Config': {'Env': ['VPN_INTERFACE=tun0;rm -rf /']},
        })
        self.assertEqual(reader.read('gluetun').state, 'error')
        api.exec_create.assert_not_called()


if __name__ == '__main__':
    unittest.main()
