import math
import os
import sqlite3
from contextlib import contextmanager

_db_path = None


def init_db(db_path: str):
    global _db_path
    _db_path = db_path
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    with get_db() as db:
        db.executescript('''
            CREATE TABLE IF NOT EXISTS servers (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                name                 TEXT    UNIQUE NOT NULL,
                filter_type          TEXT    NOT NULL DEFAULT 'name',
                enabled              INTEGER NOT NULL DEFAULT 1,
                consecutive_failures INTEGER NOT NULL DEFAULT 0,
                created_at           TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS speed_tests (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                server_name      TEXT NOT NULL,
                download_mbps    REAL,
                upload_mbps      REAL,
                latency_ms       REAL,
                public_ip        TEXT,
                public_ipv6      TEXT,
                success          INTEGER NOT NULL DEFAULT 0,
                error_msg        TEXT,
                tested_at        TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                jitter_ms        REAL,
                packet_loss_pct  REAL,
                ping_min_ms      REAL,
                ping_max_ms      REAL,
                dns_latency_ms   REAL,
                test_trigger     TEXT
            );

            CREATE TABLE IF NOT EXISTS switches (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                from_server  TEXT,
                to_server    TEXT NOT NULL,
                reason       TEXT,
                success      INTEGER NOT NULL DEFAULT 0,
                connect_secs REAL,
                from_mbps    REAL,
                to_mbps      REAL,
                to_ipv4      TEXT,
                to_ipv6      TEXT,
                switched_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS benchmark_cycles (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                finished_at    TEXT,
                duration_secs  REAL,
                servers_tested INTEGER,
                best_server    TEXT
            );

            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS airvpn_new_servers (
                name          TEXT PRIMARY KEY,
                country       TEXT NOT NULL DEFAULT '',
                country_code  TEXT NOT NULL DEFAULT '',
                first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                dismissed     INTEGER NOT NULL DEFAULT 0
            );

            INSERT OR IGNORE INTO settings (key, value) VALUES
                ('test_interval_hours',      '6'),
                ('admin_username',           'admin'),
                ('admin_password_hash',      ''),
                ('auto_switch',              '1'),
                ('connection_wait_seconds',  '45'),
                ('benchmark_running',        '0'),
                ('benchmark_current_server',''),
                ('proxy_username',           ''),
                ('proxy_password',           ''),
                ('speedtest_samples',        '3'),
                ('speedtest_duration',       '8'),
                ('speedtest_retries',        '2'),
                ('server_timeout_secs',      '300'),
                ('auto_exclude_failures',    '5'),
                ('speedtest_warmup',         '1'),
                ('speedtest_streams',        '4'),
                ('db_retention_days',        '30'),
                ('discord_webhook_url',      ''),
                ('apprise_urls',             ''),
                ('sidecar_mode',             '1'),
                ('sidecar_image',            'ghcr.io/aerya/gluetun-companion-sidecar:latest'),
                ('sidecar_port',             '8766'),
                ('sidecar_speedtest_method', 'dual'),
                ('sidecar_iperf_fallback',   '1'),
                ('sidecar_proxy_fallback',   '0'),
                ('post_switch_containers',      '[]'),
                ('pause_bench_containers',      '[]'),
                ('auto_benchmark',              '1'),
                ('pull_gluetun',                '0'),
                ('pull_post_switch_containers', '[]'),
                ('pull_pause_bench_containers', '[]'),
                ('pull_network_containers',     '[]'),
                ('quick_check_mode',            '0'),
                ('quick_check_threshold',       '15'),
                ('weighted_score_current_pct',  '65'),
                ('airvpn_new_server_notif',     '0'),
                ('airvpn_notify_mention',       ''),
                ('stability_weight',            '30');
        ''')
        # Migrations for columns added after initial schema
        for stmt in [
            "ALTER TABLE servers ADD COLUMN filter_type TEXT NOT NULL DEFAULT 'name'",
            "ALTER TABLE servers ADD COLUMN consecutive_failures INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE speed_tests ADD COLUMN upload_mbps REAL",
            "ALTER TABLE speed_tests ADD COLUMN public_ipv6 TEXT",
            "ALTER TABLE speed_tests ADD COLUMN test_method TEXT NOT NULL DEFAULT 'proxy'",
            "ALTER TABLE switches ADD COLUMN connect_secs REAL",
            "ALTER TABLE switches ADD COLUMN from_mbps REAL",
            "ALTER TABLE switches ADD COLUMN to_mbps REAL",
            "ALTER TABLE switches ADD COLUMN to_ipv4 TEXT",
            "ALTER TABLE switches ADD COLUMN to_ipv6 TEXT",
            "ALTER TABLE speed_tests ADD COLUMN dl_ookla REAL",
            "ALTER TABLE speed_tests ADD COLUMN ul_ookla REAL",
            "ALTER TABLE speed_tests ADD COLUMN dl_librespeed REAL",
            "ALTER TABLE speed_tests ADD COLUMN ul_librespeed REAL",
            "ALTER TABLE speed_tests ADD COLUMN dl_iperf3 REAL",
            "ALTER TABLE speed_tests ADD COLUMN ul_iperf3 REAL",
            "ALTER TABLE speed_tests ADD COLUMN jitter_ms REAL",
            "ALTER TABLE speed_tests ADD COLUMN packet_loss_pct REAL",
            "ALTER TABLE speed_tests ADD COLUMN ping_min_ms REAL",
            "ALTER TABLE speed_tests ADD COLUMN ping_max_ms REAL",
            "ALTER TABLE speed_tests ADD COLUMN dns_latency_ms REAL",
            "ALTER TABLE speed_tests ADD COLUMN test_trigger TEXT",
        ]:
            try:
                db.execute(stmt)
            except Exception:
                pass


@contextmanager
def get_db():
    conn = sqlite3.connect(_db_path)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_setting(key: str, default: str = '') -> str:
    with get_db() as db:
        row = db.execute('SELECT value FROM settings WHERE key = ?', (key,)).fetchone()
        return row['value'] if row else default


def set_setting(key: str, value: str):
    with get_db() as db:
        db.execute(
            'INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)',
            (key, str(value)),
        )


def compute_confidence_all() -> dict[str, dict]:
    """Compute confidence scores for all servers (zero migrations needed).

    Returns {server_name: {'level': 'HIGH'|'MEDIUM'|'LOW', 'nb': int,
                            'cv_pct': float|None, 'consec': int}}

    Rules:
      HIGH   — ≥ 5 successful measurements AND σ < 15 % AND 0 consecutive failures
      MEDIUM — 2–4 measurements OR σ 15–30 %  (and no LOW condition)
      LOW    — ≤ 1 measurement  OR σ > 30 %   OR consecutive_failures > 0

    proxy_qc tests are excluded (quick checks — not representative benchmarks).
    SQLite variance = E[x²] − E[x]² (population variance, no STDDEV function needed).
    """
    with get_db() as db:
        rows = db.execute('''
            SELECT
                s.name,
                COALESCE(s.consecutive_failures, 0) AS consec,
                COALESCE(
                    SUM(CASE WHEN st.success=1 AND st.test_method!='proxy_qc' THEN 1 ELSE 0 END),
                    0
                ) AS nb,
                AVG(CASE WHEN st.success=1 AND st.test_method!='proxy_qc'
                         THEN st.download_mbps END) AS avg_dl,
                (
                    AVG(CASE WHEN st.success=1 AND st.test_method!='proxy_qc'
                             THEN st.download_mbps * st.download_mbps END) -
                    AVG(CASE WHEN st.success=1 AND st.test_method!='proxy_qc'
                             THEN st.download_mbps END) *
                    AVG(CASE WHEN st.success=1 AND st.test_method!='proxy_qc'
                             THEN st.download_mbps END)
                ) AS variance
            FROM servers s
            LEFT JOIN speed_tests st ON st.server_name = s.name
            GROUP BY s.name
        ''').fetchall()

    result: dict[str, dict] = {}
    for r in rows:
        name   = r['name']
        nb     = int(r['nb'] or 0)
        avg    = r['avg_dl'] or 0.0
        var    = max(r['variance'] or 0.0, 0.0)
        consec = int(r['consec'] or 0)

        if nb == 0:
            result[name] = {'level': 'LOW', 'nb': 0, 'cv_pct': None, 'consec': consec}
            continue

        stddev = math.sqrt(var) if var > 0 else 0.0
        cv_pct = round(stddev / avg * 100, 1) if avg > 0 else 0.0

        # LOW — any degrading condition (VPN speeds vary a lot; threshold calibrated accordingly)
        if nb <= 1 or cv_pct > 70 or consec > 0:
            level = 'LOW'
        # HIGH — sufficient data AND stable results
        elif nb >= 5 and cv_pct < 40:
            level = 'HIGH'
        # MEDIUM — everything else (2–4 measures, OR σ between 40–70 %)
        else:
            level = 'MEDIUM'

        result[name] = {'level': level, 'nb': nb, 'cv_pct': cv_pct, 'consec': consec}

    return result


# ---------------------------------------------------------------------------
# Stability metrics (jitter / packet loss) per server
# ---------------------------------------------------------------------------

def get_stability_all() -> dict[str, dict]:
    """Return average stability metrics per server (proxy_qc excluded).

    Returns {server_name: {'avg_jitter': float|None, 'avg_loss': float|None,
                           'avg_ping_min': float|None, 'avg_ping_max': float|None,
                           'avg_dns': float|None, 'n': int}}
    """
    with get_db() as db:
        rows = db.execute('''
            SELECT
                s.name,
                ROUND(AVG(CASE WHEN st.success=1 AND st.test_method!='proxy_qc'
                               THEN st.jitter_ms END), 1)         AS avg_jitter,
                ROUND(AVG(CASE WHEN st.success=1 AND st.test_method!='proxy_qc'
                               THEN st.packet_loss_pct END), 1)   AS avg_loss,
                ROUND(AVG(CASE WHEN st.success=1 AND st.test_method!='proxy_qc'
                               THEN st.ping_min_ms END), 1)       AS avg_ping_min,
                ROUND(AVG(CASE WHEN st.success=1 AND st.test_method!='proxy_qc'
                               THEN st.ping_max_ms END), 1)       AS avg_ping_max,
                ROUND(AVG(CASE WHEN st.success=1 AND st.test_method!='proxy_qc'
                               THEN st.dns_latency_ms END), 1)    AS avg_dns,
                COALESCE(
                    SUM(CASE WHEN st.success=1 AND st.test_method!='proxy_qc'
                              AND st.jitter_ms IS NOT NULL THEN 1 ELSE 0 END),
                    0
                ) AS n
            FROM servers s
            LEFT JOIN speed_tests st ON st.server_name = s.name
            GROUP BY s.name
        ''').fetchall()

    return {
        r['name']: {
            'avg_jitter':   r['avg_jitter'],
            'avg_loss':     r['avg_loss'],
            'avg_ping_min': r['avg_ping_min'],
            'avg_ping_max': r['avg_ping_max'],
            'avg_dns':      r['avg_dns'],
            'n':            int(r['n'] or 0),
        }
        for r in rows
    }


# ---------------------------------------------------------------------------
# AirVPN new-server detection helpers
# ---------------------------------------------------------------------------

def get_new_airvpn_servers() -> list[dict]:
    """Return non-dismissed new AirVPN servers seen in the last 7 days
    that are not yet in the user's servers table."""
    with get_db() as db:
        rows = db.execute("""
            SELECT n.name, n.country, n.country_code, n.first_seen_at
            FROM airvpn_new_servers n
            WHERE n.dismissed = 0
              AND n.first_seen_at >= datetime('now', '-7 days')
              AND n.name NOT IN (
                  SELECT name FROM servers WHERE filter_type = 'name'
              )
            ORDER BY n.first_seen_at DESC
        """).fetchall()
    return [dict(r) for r in rows]


def upsert_new_airvpn_servers(servers: list[dict]) -> list[dict]:
    """Insert newly discovered servers (INSERT OR IGNORE).
    Returns only the truly newly inserted entries.
    Also cleans up entries that have since been added to the servers table."""
    newly_added: list[dict] = []
    with get_db() as db:
        for s in servers:
            cur = db.execute(
                "INSERT OR IGNORE INTO airvpn_new_servers (name, country, country_code)"
                " VALUES (?, ?, ?)",
                (s['name'], s['country'], s['country_code']),
            )
            if cur.rowcount:
                newly_added.append(s)
        # Clean up servers that have been added by the user in the meantime
        db.execute("""
            DELETE FROM airvpn_new_servers
            WHERE name IN (SELECT name FROM servers WHERE filter_type = 'name')
        """)
    return newly_added


def dismiss_new_airvpn_servers():
    """Mark all tracked new servers as dismissed (user acknowledged the banner)."""
    with get_db() as db:
        db.execute("UPDATE airvpn_new_servers SET dismissed = 1")


def get_docker_event_counts(days: int = 30) -> dict[str, int]:
    """Return {server_name: count} of involuntary reconnects detected via Docker events.

    A docker_event test is recorded each time the Docker event listener detects an
    unexpected Gluetun restart and fires a quick check.  Each such event represents
    one involuntary VPN reconnection while that server was active.
    Only looks at the last ``days`` days (aligned with the DB retention window).
    """
    with get_db() as db:
        rows = db.execute(
            "SELECT server_name, COUNT(*) AS cnt FROM speed_tests "
            "WHERE test_trigger = 'docker_event' "
            "  AND tested_at >= datetime('now', ? || ' days') "
            "GROUP BY server_name",
            (f'-{days}',),
        ).fetchall()
    return {r['server_name']: int(r['cnt']) for r in rows}


def purge_old_new_airvpn_servers():
    """Remove entries older than 7 days — they are no longer 'new'."""
    with get_db() as db:
        db.execute(
            "DELETE FROM airvpn_new_servers"
            " WHERE first_seen_at < datetime('now', '-7 days')"
        )
