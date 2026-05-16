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
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT    UNIQUE NOT NULL,
                filter_type TEXT    NOT NULL DEFAULT 'name',
                enabled     INTEGER NOT NULL DEFAULT 1,
                created_at  TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS speed_tests (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                server_name   TEXT    NOT NULL,
                download_mbps REAL,
                latency_ms    REAL,
                public_ip     TEXT,
                success       INTEGER NOT NULL DEFAULT 0,
                error_msg     TEXT,
                tested_at     TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS switches (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                from_server TEXT,
                to_server   TEXT    NOT NULL,
                reason      TEXT,
                success     INTEGER NOT NULL DEFAULT 0,
                switched_at TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
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
                ('test_file_size_mb',        '10'),
                ('connection_wait_seconds',  '45'),
                ('benchmark_running',        '0'),
                ('proxy_username',           ''),
                ('proxy_password',           ''),
                ('speedtest_samples',        '3'),
                ('speedtest_duration',       '8');
        ''')
        # Migration: add filter_type to existing tables that predate this column
        try:
            db.execute("ALTER TABLE servers ADD COLUMN filter_type TEXT NOT NULL DEFAULT 'name'")
        except Exception:
            pass  # column already exists


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
