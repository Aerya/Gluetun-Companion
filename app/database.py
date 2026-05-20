import sqlite3
import os
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
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                server_name   TEXT NOT NULL,
                download_mbps REAL,
                upload_mbps   REAL,
                latency_ms    REAL,
                public_ip     TEXT,
                public_ipv6   TEXT,
                success       INTEGER NOT NULL DEFAULT 0,
                error_msg     TEXT,
                tested_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
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
                ('weighted_score_current_pct',  '65');
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
