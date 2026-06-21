import math
import os
import sqlite3
from contextlib import contextmanager

# Sentinel for optional parameters that distinguish "not provided" from None
_UNSET = object()

_db_path = None
_VPN_SERVER_TYPES = {'p2p', 'stream', 'secure_core', 'tor', 'free'}


def _clean_server_types(value) -> str:
    if isinstance(value, str):
        raw = value.replace(';', ',').split(',')
    elif isinstance(value, (list, tuple, set)):
        raw = list(value)
    else:
        raw = []
    aliases = {
        'streaming': 'stream',
        'secure-core': 'secure_core',
        'secure core': 'secure_core',
        'port_forward': 'p2p',
    }
    out: list[str] = []
    for item in raw:
        key = aliases.get(str(item or '').strip().lower(), str(item or '').strip().lower())
        if key in _VPN_SERVER_TYPES and key not in out:
            out.append(key)
    return ','.join(out)


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

            -- ── VPN provider profiles (WireGuard / OpenVPN) ────────────────
            -- One row per configured VPN account (provider + credentials).
            -- Credentials are stored encrypted in vpn_profile_vars.
            CREATE TABLE IF NOT EXISTS vpn_profiles (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                name             TEXT    NOT NULL,           -- user-given name, e.g. "AirVPN Principal"
                provider         TEXT    NOT NULL,           -- wg_providers.py key, e.g. "airvpn"
                vpn_type         TEXT    NOT NULL DEFAULT 'wireguard',  -- 'wireguard' | 'openvpn'
                enabled          INTEGER NOT NULL DEFAULT 1,
                rotation_allowed INTEGER NOT NULL DEFAULT 0, -- may this profile be used in rotation?
                rotation_priority INTEGER NOT NULL DEFAULT 0, -- lower = higher priority
                sidecar_private_key  TEXT NOT NULL DEFAULT '',
                sidecar_addresses     TEXT NOT NULL DEFAULT '',
                sidecar_preshared_key TEXT NOT NULL DEFAULT '',
                sidecar_reuse_profile INTEGER NOT NULL DEFAULT 0,
                port_forwarding   INTEGER NOT NULL DEFAULT 0,
                port_forward_only INTEGER NOT NULL DEFAULT 1,
                server_types      TEXT    NOT NULL DEFAULT '',
                created_at       TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at       TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            -- One row per WireGuard env var (PRIVATE_KEY, ADDRESSES, …) per profile.
            -- Secret values are stored encrypted with the "enc:" prefix (see crypto.py).
            CREATE TABLE IF NOT EXISTS vpn_profile_vars (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id INTEGER NOT NULL REFERENCES vpn_profiles(id) ON DELETE CASCADE,
                var_key    TEXT    NOT NULL,   -- Gluetun env var name
                var_value  TEXT    NOT NULL DEFAULT '',
                UNIQUE(profile_id, var_key)
            );

            CREATE TABLE IF NOT EXISTS gluetun_catalogue (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                provider     TEXT NOT NULL,
                name         TEXT NOT NULL DEFAULT '',
                country      TEXT NOT NULL DEFAULT '',
                country_code TEXT NOT NULL DEFAULT '',
                region       TEXT NOT NULL DEFAULT '',
                city         TEXT NOT NULL DEFAULT '',
                hostname     TEXT NOT NULL DEFAULT '',
                port_forward INTEGER NOT NULL DEFAULT 0,
                server_types TEXT NOT NULL DEFAULT '',
                updated_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_catalogue_provider
                ON gluetun_catalogue(provider);

            CREATE TABLE IF NOT EXISTS airvpn_new_servers (
                name          TEXT PRIMARY KEY,
                country       TEXT NOT NULL DEFAULT '',
                country_code  TEXT NOT NULL DEFAULT '',
                first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                dismissed     INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS airvpn_snapshot (
                name         TEXT PRIMARY KEY,
                load         INTEGER NOT NULL DEFAULT 0,
                users        INTEGER NOT NULL DEFAULT 0,
                bw_mbps      INTEGER NOT NULL DEFAULT 0,
                bw_max_mbps  INTEGER NOT NULL DEFAULT 0,
                avail_mbps   INTEGER NOT NULL DEFAULT 0,
                health       TEXT NOT NULL DEFAULT 'ok',
                country      TEXT NOT NULL DEFAULT '',
                country_code TEXT NOT NULL DEFAULT ''
            );

            CREATE INDEX IF NOT EXISTS idx_vpn_profile_vars_profile
                ON vpn_profile_vars(profile_id);

            -- ── Rotation pools ─────────────────────────────────────────────
            -- A pool defines a set of candidate servers and a rotation mode.
            -- Companion periodically (or on demand) picks one and switches Gluetun.
            CREATE TABLE IF NOT EXISTS rotation_pools (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                name             TEXT    NOT NULL,
                mode             TEXT    NOT NULL DEFAULT 'random',
                                          -- 'random' | 'round_robin' | 'best_score'
                enabled          INTEGER NOT NULL DEFAULT 1,
                auto_rotate      INTEGER NOT NULL DEFAULT 0,
                interval_hours   REAL    NOT NULL DEFAULT 6.0,
                next_rotation_at TEXT,             -- ISO datetime (UTC) of next auto-rotation
                last_rotated_at  TEXT,             -- ISO datetime (UTC) of last rotation
                current_rr_idx   INTEGER NOT NULL DEFAULT 0,  -- round-robin cursor
                criteria_logic   TEXT    NOT NULL DEFAULT 'union',
                                          -- 'union' | 'intersection'
                quick_bench      INTEGER NOT NULL DEFAULT 0,  -- run proxy_qc after switch
                notify           INTEGER NOT NULL DEFAULT 1,
                top_n            INTEGER,          -- if set, restrict to top-N by avg score
                last_server      TEXT,
                last_error       TEXT,
                last_dl_mbps     REAL,
                created_at       TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            -- Criteria that feed a pool. criteria_logic controls union vs intersection.
            CREATE TABLE IF NOT EXISTS rotation_pool_criteria (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                pool_id     INTEGER NOT NULL REFERENCES rotation_pools(id) ON DELETE CASCADE,
                crit_type   TEXT    NOT NULL,
                             -- 'all'     : all enabled servers
                             -- 'server'  : crit_value = server name
                             -- 'filter'  : crit_value = JSON {"type":"country","value":"France"}
                             -- 'profile' : crit_value = vpn_profile_id (string)
                             -- 'top_metric' : crit_value = JSON {"metric":"dl","n":5}
                             -- 'airvpn_bw_min' : crit_value = minimum AirVPN capacity in Mbit/s
                crit_value  TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_pool_criteria_pool
                ON rotation_pool_criteria(pool_id);

            -- Per-pool explicit exclusions. These servers stay active in
            -- Companion, but this pool will never pick them.
            CREATE TABLE IF NOT EXISTS rotation_pool_exclusions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                pool_id     INTEGER NOT NULL REFERENCES rotation_pools(id) ON DELETE CASCADE,
                server_name TEXT    NOT NULL,
                UNIQUE(pool_id, server_name)
            );

            CREATE INDEX IF NOT EXISTS idx_pool_exclusions_pool
                ON rotation_pool_exclusions(pool_id);

            CREATE TABLE IF NOT EXISTS torrent_clients (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                name              TEXT    NOT NULL,
                client_type       TEXT    NOT NULL DEFAULT 'qbittorrent',
                base_url          TEXT    NOT NULL DEFAULT '',
                username          TEXT    NOT NULL DEFAULT '',
                password          TEXT    NOT NULL DEFAULT '',
                container_name    TEXT    NOT NULL DEFAULT '',
                enabled           INTEGER NOT NULL DEFAULT 1,
                include_paused    INTEGER NOT NULL DEFAULT 1,
                include_private   INTEGER NOT NULL DEFAULT 1,
                category_filter   TEXT    NOT NULL DEFAULT '',
                tag_filter        TEXT    NOT NULL DEFAULT '',
                created_at        TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at        TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS tracker_urls (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                url              TEXT    UNIQUE NOT NULL,
                scheme           TEXT    NOT NULL DEFAULT '',
                host             TEXT    NOT NULL DEFAULT '',
                port             INTEGER,
                path             TEXT    NOT NULL DEFAULT '',
                enabled          INTEGER NOT NULL DEFAULT 1,
                first_seen_at    TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_seen_at     TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_checked_at  TEXT,
                last_status      TEXT    NOT NULL DEFAULT 'unknown',
                last_error       TEXT    NOT NULL DEFAULT '',
                success_count    INTEGER NOT NULL DEFAULT 0,
                failure_count    INTEGER NOT NULL DEFAULT 0,
                torrent_count    INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS tracker_sources (
                client_id     INTEGER NOT NULL REFERENCES torrent_clients(id) ON DELETE CASCADE,
                tracker_id    INTEGER NOT NULL REFERENCES tracker_urls(id) ON DELETE CASCADE,
                torrent_hash  TEXT    NOT NULL DEFAULT '',
                torrent_name  TEXT    NOT NULL DEFAULT '',
                last_seen_at  TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (client_id, tracker_id, torrent_hash)
            );

            CREATE TABLE IF NOT EXISTS tracker_checks (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                tracker_id      INTEGER NOT NULL REFERENCES tracker_urls(id) ON DELETE CASCADE,
                server_name     TEXT    NOT NULL DEFAULT '',
                vpn_ipv4        TEXT    NOT NULL DEFAULT '',
                level_dns       INTEGER NOT NULL DEFAULT 0,
                level_port      INTEGER NOT NULL DEFAULT 0,
                level_endpoint  INTEGER NOT NULL DEFAULT 0,
                success         INTEGER NOT NULL DEFAULT 0,
                status          TEXT    NOT NULL DEFAULT '',
                error_msg       TEXT    NOT NULL DEFAULT '',
                elapsed_ms      INTEGER NOT NULL DEFAULT 0,
                checked_at      TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS port_forwards (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                name               TEXT    NOT NULL DEFAULT '',
                provider           TEXT    NOT NULL DEFAULT 'airvpn',
                mode               TEXT    NOT NULL DEFAULT 'manual',
                port               INTEGER NOT NULL,
                protocols          TEXT    NOT NULL DEFAULT 'tcp,udp',
                torrent_client_id  INTEGER REFERENCES torrent_clients(id) ON DELETE SET NULL,
                on_port_change_cmd TEXT    NOT NULL DEFAULT '',
                last_applied_port  INTEGER,
                enabled            INTEGER NOT NULL DEFAULT 1,
                notes              TEXT    NOT NULL DEFAULT '',
                created_at         TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at         TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_tracker_urls_host
                ON tracker_urls(host);
            CREATE INDEX IF NOT EXISTS idx_tracker_sources_tracker
                ON tracker_sources(tracker_id);
            CREATE INDEX IF NOT EXISTS idx_tracker_checks_tracker
                ON tracker_checks(tracker_id);
            CREATE INDEX IF NOT EXISTS idx_port_forwards_client
                ON port_forwards(torrent_client_id);

            INSERT OR IGNORE INTO settings (key, value) VALUES
                ('test_interval_hours',      '6'),
                ('admin_username',           'admin'),
                ('admin_password_hash',      ''),
                ('auto_switch',              '1'),
                ('connection_wait_seconds',  '45'),
                ('benchmark_running',        '0'),
                ('benchmark_stop_requested', '0'),
                ('benchmark_current_server',''),
                ('benchmark_next_server',   ''),
                ('benchmark_log_lines',     '[]'),
                ('benchmark_started_at',     ''),
                ('benchmark_mode',           ''),
                ('benchmark_total_servers',  '0'),
                ('benchmark_done_servers',   '0'),
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
                ('sidecar_disconnect_wait_seconds', '180'),
                ('post_switch_containers',      '[]'),
                ('pause_bench_containers',      '[]'),
                ('auto_benchmark',              '1'),
                ('pull_gluetun',                '0'),
                ('pull_post_switch_containers', '[]'),
                ('pull_pause_bench_containers', '[]'),
                ('pull_network_containers',     '[]'),
                ('quick_check_mode',            '0'),
                ('quick_check_threshold',       '15'),
                ('benchmark_scope_mode',        'smart'),
                ('benchmark_scope_top_n',       '50'),
                ('benchmark_scope_untested_n',  '10'),
                ('benchmark_scope_refresh_days','14'),
                ('benchmark_scope_refresh_n',   '20'),
                ('continuous_observation',      '0'),
                ('observation_target_tests',     '11'),
                ('observation_explore_n',        '20'),
                ('observation_confirm_tests',    '3'),
                ('observation_confirm_n',        '20'),
                ('observation_finalist_n',       '10'),
                ('scoring_window_days',         '30'),
                ('outlier_detection',           '1'),
                ('weighted_score_current_pct',  '65'),
                ('airvpn_new_server_notif',     '0'),
                ('airvpn_notify_mention',       ''),
                ('stability_weight',            '30'),
                ('api_token',                   ''),
                ('adaptive_scheduling',         '0'),
                ('adaptive_auto_shift',         '0'),
                ('pending_optimal_hour',        ''),
                ('gluetun_id_history',          '[]'),
                ('orphan_legacy_adoption_done', '0'),
                ('notif_auto_switch',           '1'),
                ('notif_manual_switch',         '0'),
                ('notif_already_best',          '0'),
                ('notif_auto_exclude',          '1'),
                ('notif_benchmark_end',         '0'),
                ('notif_benchmark_failure',     '1'),
                ('notif_quick_check',           '1'),
                ('notify_mention',              ''),
                ('notify_mention_level',        'medium'),
                ('active_profile',              'balanced'),
                ('single_stream_test',          '0'),
                ('catalogue_enabled',          '0'),
                ('catalogue_servers_dir',      '/gluetun/servers'),
                ('catalogue_import_mode',      'active'),
                ('catalogue_import_provider',  ''),
                ('catalogue_bench_on_import',  '0'),
                ('catalogue_server_type',      ''),
                ('catalogue_sidecar_port',     '8767'),
                ('catalogue_last_refresh',     ''),
                ('tracker_check_enabled',      '0'),
                ('tracker_require_for_switch', '0'),
                ('tracker_check_threshold_pct','80'),
                ('tracker_check_timeout_secs', '3'),
                ('tracker_check_concurrency',  '12'),
                ('dns_block_malicious',        '1'),
                ('dns_unblock_hostnames',      ''),
                ('port_forward_enabled',       '0'),
                ('port_forward_auto_sync',     '1'),
                ('port_forward_gluetun_api_url', 'http://host.docker.internal:8000'),
                ('port_forward_gluetun_api_key', ''),
                ('port_forward_hook_timeout_secs', '20'),
                ('port_forward_last_auto_result', ''),
                -- WireGuard multi-provider rotation
                ('wg_rotation_mode',           'none'),   -- none | free | conditional
                ('wg_rotation_threshold',      '10');     -- % score gain required (conditional mode)
        ''')
        db.execute(
            """DELETE FROM settings
               WHERE key IN (
                   'wg_active_profile_id',
                   'wg_sidecar_private_key',
                   'wg_sidecar_addresses',
                   'wg_sidecar_preshared_key'
               )"""
        )
        # Data migration: legacy airvpn_notify_mention → notify_mention
        _legacy = db.execute(
            "SELECT value FROM settings WHERE key='airvpn_notify_mention'"
        ).fetchone()
        if _legacy and _legacy[0]:
            _cur = db.execute(
                "SELECT value FROM settings WHERE key='notify_mention'"
            ).fetchone()
            if not _cur or not _cur[0]:
                db.execute(
                    "UPDATE settings SET value=? WHERE key='notify_mention'",
                    (_legacy[0],),
                )

        # Early sidecar builds used a 20 s disconnect wait. AirVPN can keep
        # WireGuard sessions visible for much longer after Docker cleanup, so
        # migrate that initial default to a safer value without touching custom
        # user values.
        _sidecar_wait = db.execute(
            "SELECT value FROM settings WHERE key='sidecar_disconnect_wait_seconds'"
        ).fetchone()
        if _sidecar_wait and (_sidecar_wait[0] or '') in ('', '20'):
            db.execute(
                "UPDATE settings SET value='180' WHERE key='sidecar_disconnect_wait_seconds'"
            )

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
            "ALTER TABLE speed_tests ADD COLUMN dl_single_mbps REAL",
            # WireGuard multi-provider: link servers to a VPN profile
            "ALTER TABLE servers ADD COLUMN vpn_profile_id INTEGER REFERENCES vpn_profiles(id)",
            # Per-profile dedicated WireGuard sidecar test keys (replaces global settings)
            # Stored encrypted with enc: prefix, same as vpn_profile_vars secrets.
            "ALTER TABLE vpn_profiles ADD COLUMN sidecar_private_key  TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE vpn_profiles ADD COLUMN sidecar_addresses     TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE vpn_profiles ADD COLUMN sidecar_preshared_key TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE vpn_profiles ADD COLUMN sidecar_reuse_profile INTEGER NOT NULL DEFAULT 0",
            # ProtonVPN (and other native-PF providers): enable Gluetun VPN port
            # forwarding for this profile, and target P2P / port-forwarding servers.
            "ALTER TABLE vpn_profiles ADD COLUMN port_forwarding   INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE vpn_profiles ADD COLUMN port_forward_only INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE vpn_profiles ADD COLUMN server_types TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE gluetun_catalogue ADD COLUMN port_forward INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE gluetun_catalogue ADD COLUMN server_types TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE rotation_pools ADD COLUMN criteria_logic TEXT NOT NULL DEFAULT 'union'",
            "ALTER TABLE rotation_pools ADD COLUMN last_server TEXT",
            "ALTER TABLE rotation_pools ADD COLUMN last_error TEXT",
            "ALTER TABLE rotation_pools ADD COLUMN last_dl_mbps REAL",
            "ALTER TABLE switches ADD COLUMN from_ipv4 TEXT",
            "ALTER TABLE switches ADD COLUMN from_ipv6 TEXT",
            "ALTER TABLE airvpn_snapshot ADD COLUMN bw_mbps INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE airvpn_snapshot ADD COLUMN bw_max_mbps INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE airvpn_snapshot ADD COLUMN avail_mbps INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE torrent_clients ADD COLUMN container_name TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE torrent_clients ADD COLUMN include_paused INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE torrent_clients ADD COLUMN include_private INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE torrent_clients ADD COLUMN category_filter TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE torrent_clients ADD COLUMN tag_filter TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE tracker_urls ADD COLUMN torrent_count INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE port_forwards ADD COLUMN provider TEXT NOT NULL DEFAULT 'airvpn'",
            "ALTER TABLE port_forwards ADD COLUMN mode TEXT NOT NULL DEFAULT 'manual'",
            "ALTER TABLE port_forwards ADD COLUMN protocols TEXT NOT NULL DEFAULT 'tcp,udp'",
            "ALTER TABLE port_forwards ADD COLUMN torrent_client_id INTEGER REFERENCES torrent_clients(id) ON DELETE SET NULL",
            "ALTER TABLE port_forwards ADD COLUMN on_port_change_cmd TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE port_forwards ADD COLUMN last_applied_port INTEGER",
            "ALTER TABLE port_forwards ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1",
            "ALTER TABLE port_forwards ADD COLUMN notes TEXT NOT NULL DEFAULT ''",
            # Multi-type VPN profiles: 'wireguard' (legacy default) or 'openvpn'
            "ALTER TABLE vpn_profiles ADD COLUMN vpn_type TEXT NOT NULL DEFAULT 'wireguard'",
        ]:
            try:
                db.execute(stmt)
            except Exception:
                pass

        # ── One-time settings migrations ─────────────────────────────────────
        # Provider auto-sync becomes opt-out: port-forward rules configured per
        # provider are meant to follow provider changes without a second toggle.
        # Existing installs are flipped once; users can still disable it.
        _row = db.execute(
            "SELECT value FROM settings WHERE key='pf_auto_sync_default_migrated'"
        ).fetchone()
        if not _row:
            db.execute("UPDATE settings SET value='1' WHERE key='port_forward_auto_sync'")
            db.execute(
                "INSERT OR REPLACE INTO settings (key, value) "
                "VALUES ('pf_auto_sync_default_migrated', '1')"
            )


@contextmanager
def get_db():
    conn = sqlite3.connect(_db_path)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA foreign_keys = ON')   # enable cascade deletes
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


def compute_confidence_all(window_days: int | None = None) -> dict[str, dict]:
    """Compute confidence scores for all servers (zero migrations needed).

    Returns {server_name: {'level': 'HIGH'|'MEDIUM'|'LOW', 'nb': int,
                            'cv_pct': float|None, 'consec': int}}

    Rules:
      HIGH   — ≥ 5 successful measurements AND σ < 15 % AND 0 consecutive failures
      MEDIUM — 2–4 measurements OR σ 15–30 %  (and no LOW condition)
      LOW    — ≤ 1 measurement  OR σ > 30 %   OR consecutive_failures > 0

    proxy_qc tests are excluded (quick checks — not representative benchmarks).
    SQLite variance = E[x²] − E[x]² (population variance, no STDDEV function needed).
    *window_days* restricts the computation to the last N days (None = all history).
    """
    window_sql = ''
    params: list = []
    if window_days:
        window_sql = "AND st.tested_at >= datetime('now', ?)"
        params = [f'-{window_days} days']

    with get_db() as db:
        rows = db.execute(f'''
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
            LEFT JOIN speed_tests st ON st.server_name = s.name {window_sql}
            GROUP BY s.name
        ''', params).fetchall()

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

def get_stability_all(window_days: int | None = None) -> dict[str, dict]:
    """Return average stability metrics per server (proxy_qc excluded).

    Returns {server_name: {'avg_jitter': float|None, 'avg_loss': float|None,
                           'avg_ping_min': float|None, 'avg_ping_max': float|None,
                           'avg_dns': float|None, 'n': int}}

    *window_days* restricts the computation to the last N days (None = all history).
    """
    window_sql = ''
    params: list = []
    if window_days:
        window_sql = "AND st.tested_at >= datetime('now', ?)"
        params = [f'-{window_days} days']

    with get_db() as db:
        rows = db.execute(f'''
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
            LEFT JOIN speed_tests st ON st.server_name = s.name {window_sql}
            GROUP BY s.name
        ''', params).fetchall()

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
# Outlier detection + windowed server stats
# ---------------------------------------------------------------------------

def _iqr_filter(values: list) -> list:
    """Remove outliers using the IQR × 1.5 fence.

    Returns the input unchanged when fewer than 4 values are present
    (not enough data to reliably identify outliers) or when IQR == 0
    (all values identical — nothing to filter).
    """
    if len(values) < 4:
        return values
    sv = sorted(values)
    n = len(sv)
    q1 = sv[n // 4]
    q3 = sv[(3 * n) // 4]
    iqr = q3 - q1
    if iqr == 0:
        return values
    lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    filtered = [v for v in values if lo <= v <= hi]
    return filtered if filtered else values   # never return empty list


def get_server_filtered_stats(
    window_days: int | None = None,
    filter_outliers: bool = True,
) -> dict[str, dict]:
    """Return per-server DL/UL/LAT/DL_SINGLE averages with optional
    time-window (days) and IQR outlier filtering.

    Returns {name: {avg_dl, avg_ul, avg_lat, avg_dl_single, nb, outliers_removed}}.
    Servers with no qualifying tests still appear with None averages and nb=0.
    """
    window_sql = ''
    params: list = []
    if window_days:
        window_sql = "AND st.tested_at >= datetime('now', ?)"
        params = [f'-{window_days} days']

    with get_db() as db:
        raw_rows = db.execute(f'''
            SELECT
                s.name,
                st.download_mbps,
                st.upload_mbps,
                st.latency_ms,
                st.dl_single_mbps
            FROM servers s
            LEFT JOIN speed_tests st
                ON st.server_name = s.name
                AND st.success = 1
                AND st.test_method != 'proxy_qc'
                {window_sql}
            ORDER BY s.name
        ''', params).fetchall()

    from collections import defaultdict
    per: dict[str, dict] = defaultdict(lambda: {'dl': [], 'ul': [], 'lat': [], 'sg': []})
    all_names: set[str] = set()

    for r in raw_rows:
        all_names.add(r['name'])
        if r['download_mbps'] is not None:
            per[r['name']]['dl'].append(float(r['download_mbps']))
        if r['upload_mbps'] is not None:
            per[r['name']]['ul'].append(float(r['upload_mbps']))
        if r['latency_ms'] is not None:
            per[r['name']]['lat'].append(float(r['latency_ms']))
        if r['dl_single_mbps'] is not None:
            per[r['name']]['sg'].append(float(r['dl_single_mbps']))

    result: dict[str, dict] = {}
    for name in all_names:
        m = per[name]
        dl_all = m['dl']
        dl_flt = _iqr_filter(dl_all) if filter_outliers else dl_all
        ul_flt = _iqr_filter(m['ul']) if filter_outliers else m['ul']
        lat_flt = _iqr_filter(m['lat']) if filter_outliers else m['lat']
        sg_flt  = _iqr_filter(m['sg'])  if filter_outliers else m['sg']

        def _avg(vals, ndigits=1):
            return round(sum(vals) / len(vals), ndigits) if vals else None

        result[name] = {
            'avg_dl':          _avg(dl_flt),
            'avg_ul':          _avg(ul_flt),
            'avg_lat':         round(sum(lat_flt) / len(lat_flt)) if lat_flt else None,
            'avg_dl_single':   _avg(sg_flt),
            'nb':              len(dl_all),
            'outliers_removed': len(dl_all) - len(dl_flt),
        }

    return result


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


def get_airvpn_snapshot() -> dict:
    """Return previous AirVPN snapshot keyed by server name."""
    with get_db() as db:
        rows = db.execute(
            '''SELECT name, load, users, bw_mbps, bw_max_mbps, avail_mbps,
                      health, country, country_code
               FROM airvpn_snapshot'''
        ).fetchall()
    return {
        r['name']: {
            'load': r['load'], 'users': r['users'], 'health': r['health'],
            'country': r['country'], 'country_code': r['country_code'],
            'bw': r['bw_mbps'], 'bw_max': r['bw_max_mbps'],
            'avail_mbps': r['avail_mbps'],
        }
        for r in rows
    }


def update_airvpn_snapshot(servers: list[dict]) -> None:
    """Replace the entire AirVPN snapshot with the current server list."""
    with get_db() as db:
        db.execute('DELETE FROM airvpn_snapshot')
        db.executemany(
            '''INSERT INTO airvpn_snapshot
               (name, load, users, bw_mbps, bw_max_mbps, avail_mbps, health, country, country_code)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            [(s['name'], s['load'], s['users'],
              int(s.get('bw', 0) or 0), int(s.get('bw_max', 0) or 0),
              int(s.get('avail_mbps', 0) or 0), s['health'],
              s.get('country', ''), s.get('country_code', '')) for s in servers],
        )


def get_hourly_benchmark_stats(min_samples: int = 6) -> dict:
    """Compute per-hour download stats for adaptive scheduling.

    Returns a dict with:
      has_enough_data  — True when ≥ 8 distinct hours have ≥ min_samples tests
      hours            — {hour_int: {n, avg_dl, cv_pct, score}}
      good_hours       — hours whose score ≥ 70 % of the best (sorted)
      bad_hours        — hours whose score < 50 % of the best (sorted)
      best_hour        — hour int with highest score, or None
      worst_hour       — hour int with lowest score (among covered hours), or None

    Hours are in local time (respects the TZ env var via SQLite 'localtime').
    proxy_qc tests are excluded — they are not representative benchmarks.
    """
    with get_db() as db:
        rows = db.execute('''
            SELECT
                CAST(strftime('%H', tested_at, 'localtime') AS INTEGER) AS hour,
                COUNT(*)                                                  AS n,
                AVG(download_mbps)                                        AS avg_dl,
                AVG(download_mbps * download_mbps)
                  - AVG(download_mbps) * AVG(download_mbps)              AS variance
            FROM speed_tests
            WHERE success = 1
              AND test_method NOT IN ('proxy_qc')
              AND download_mbps IS NOT NULL
            GROUP BY hour
            HAVING n >= ?
            ORDER BY hour
        ''', (min_samples,)).fetchall()

    if len(rows) < 8:
        return {
            'has_enough_data': False,
            'hours': {},
            'good_hours': [],
            'bad_hours': [],
            'best_hour': None,
            'worst_hour': None,
        }

    hours: dict[int, dict] = {}
    for r in rows:
        avg = r['avg_dl'] or 0.0
        var = max(r['variance'] or 0.0, 0.0)
        stddev = math.sqrt(var) if var > 0 else 0.0
        cv_pct = round(stddev / avg * 100, 1) if avg > 0 else 100.0
        # Score: rewards high average speed AND low variance
        score = avg * max(0.0, 1.0 - cv_pct / 100.0)
        hours[int(r['hour'])] = {
            'n':      int(r['n']),
            'avg_dl': round(avg, 1),
            'cv_pct': cv_pct,
            'score':  round(score, 1),
        }

    max_score = max(h['score'] for h in hours.values()) if hours else 0.0
    min_score = min(h['score'] for h in hours.values()) if hours else 0.0

    good_hours = sorted(h for h, d in hours.items() if max_score > 0 and d['score'] >= 0.70 * max_score)
    bad_hours  = sorted(h for h, d in hours.items() if max_score > 0 and d['score'] <  0.50 * max_score)

    best_hour  = max(hours, key=lambda h: hours[h]['score']) if hours else None
    worst_hour = min(hours, key=lambda h: hours[h]['score']) if hours else None

    return {
        'has_enough_data': True,
        'hours':      hours,
        'good_hours': good_hours,
        'bad_hours':  bad_hours,
        'best_hour':  best_hour,
        'worst_hour': worst_hour,
    }


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


# ---------------------------------------------------------------------------
# VPN profile CRUD (WireGuard / OpenVPN)
# ---------------------------------------------------------------------------

def get_vpn_profiles(enabled_only: bool = False) -> list[dict]:
    """Return all VPN profiles, optionally filtered to enabled ones only.

    Each profile dict includes a 'vars' sub-dict {var_key: var_value} with
    raw (possibly encrypted) values — callers decrypt secrets as needed.
    """
    where = 'WHERE enabled = 1' if enabled_only else ''
    with get_db() as db:
        profiles = db.execute(
            f'SELECT id, name, provider, vpn_type, enabled, rotation_allowed, '
            f'rotation_priority, created_at, updated_at, '
            f'sidecar_private_key, sidecar_addresses, sidecar_preshared_key, sidecar_reuse_profile, '
            f'port_forwarding, port_forward_only, server_types '
            f'FROM vpn_profiles {where} ORDER BY rotation_priority, id'
        ).fetchall()

        result = []
        for p in profiles:
            vars_rows = db.execute(
                'SELECT var_key, var_value FROM vpn_profile_vars WHERE profile_id = ?',
                (p['id'],),
            ).fetchall()
            result.append({
                'id':                   p['id'],
                'name':                 p['name'],
                'provider':             p['provider'],
                'vpn_type':             p['vpn_type'] or 'wireguard',
                'enabled':              bool(p['enabled']),
                'rotation_allowed':     bool(p['rotation_allowed']),
                'rotation_priority':    p['rotation_priority'],
                'created_at':           p['created_at'],
                'updated_at':           p['updated_at'],
                'vars':                 {r['var_key']: r['var_value'] for r in vars_rows},
                'sidecar_private_key':  p['sidecar_private_key']  or '',
                'sidecar_addresses':    p['sidecar_addresses']    or '',
                'sidecar_preshared_key': p['sidecar_preshared_key'] or '',
                'sidecar_reuse_profile': bool(p['sidecar_reuse_profile']),
                'port_forwarding':       bool(p['port_forwarding']),
                'port_forward_only':     bool(p['port_forward_only']),
                'server_types':          [t for t in (p['server_types'] or '').split(',') if t],
            })
    return result


def get_vpn_profile(profile_id: int) -> dict | None:
    """Return one VPN profile by id, or None if not found."""
    with get_db() as db:
        p = db.execute(
            'SELECT id, name, provider, vpn_type, enabled, rotation_allowed, '
            'rotation_priority, created_at, updated_at, '
            'sidecar_private_key, sidecar_addresses, sidecar_preshared_key, sidecar_reuse_profile, '
            'port_forwarding, port_forward_only, server_types '
            'FROM vpn_profiles WHERE id = ?',
            (profile_id,),
        ).fetchone()
        if not p:
            return None
        vars_rows = db.execute(
            'SELECT var_key, var_value FROM vpn_profile_vars WHERE profile_id = ?',
            (profile_id,),
        ).fetchall()
    return {
        'id':                    p['id'],
        'name':                  p['name'],
        'provider':              p['provider'],
        'vpn_type':              p['vpn_type'] or 'wireguard',
        'enabled':               bool(p['enabled']),
        'rotation_allowed':      bool(p['rotation_allowed']),
        'rotation_priority':     p['rotation_priority'],
        'created_at':            p['created_at'],
        'updated_at':            p['updated_at'],
        'vars':                  {r['var_key']: r['var_value'] for r in vars_rows},
        'sidecar_private_key':   p['sidecar_private_key']   or '',
        'sidecar_addresses':     p['sidecar_addresses']     or '',
        'sidecar_preshared_key': p['sidecar_preshared_key'] or '',
        'sidecar_reuse_profile': bool(p['sidecar_reuse_profile']),
        'port_forwarding':       bool(p['port_forwarding']),
        'port_forward_only':     bool(p['port_forward_only']),
        'server_types':          [t for t in (p['server_types'] or '').split(',') if t],
    }


def create_vpn_profile(
    name: str,
    provider: str,
    vars: dict[str, str],
    enabled: bool = True,
    rotation_allowed: bool = False,
    rotation_priority: int = 0,
    sidecar_private_key: str = '',
    sidecar_addresses: str = '',
    sidecar_preshared_key: str = '',
    sidecar_reuse_profile: bool = False,
    vpn_type: str = 'wireguard',
    port_forwarding: bool = False,
    port_forward_only: bool = True,
    server_types=None,
) -> int:
    """Insert a new VPN profile and its vars.  Returns the new profile id.

    *vars* is {var_key: var_value} — secret values must already be encrypted
    by the caller (use crypto.encrypt()).
    """
    with get_db() as db:
        cur = db.execute(
            'INSERT INTO vpn_profiles '
            '(name, provider, vpn_type, enabled, rotation_allowed, rotation_priority, '
            ' sidecar_private_key, sidecar_addresses, sidecar_preshared_key, sidecar_reuse_profile, '
            ' port_forwarding, port_forward_only, server_types) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (name, provider, vpn_type, int(enabled), int(rotation_allowed), rotation_priority,
             sidecar_private_key, sidecar_addresses, sidecar_preshared_key,
             int(sidecar_reuse_profile), int(port_forwarding), int(port_forward_only),
             _clean_server_types(server_types)),
        )
        profile_id = cur.lastrowid
        for var_key, var_value in vars.items():
            db.execute(
                'INSERT OR REPLACE INTO vpn_profile_vars (profile_id, var_key, var_value) '
                'VALUES (?, ?, ?)',
                (profile_id, var_key, var_value),
            )
    return profile_id


def update_vpn_profile(
    profile_id: int,
    name: str | None = None,
    provider: str | None = None,
    vars: dict[str, str] | None = None,
    enabled: bool | None = None,
    rotation_allowed: bool | None = None,
    rotation_priority: int | None = None,
    sidecar_private_key: str | None = None,
    sidecar_addresses: str | None = None,
    sidecar_preshared_key: str | None = None,
    sidecar_reuse_profile: bool | None = None,
    vpn_type: str | None = None,
    allowed_var_keys: 'set[str] | None' = None,
    port_forwarding: bool | None = None,
    port_forward_only: bool | None = None,
    server_types=None,
) -> bool:
    """Update an existing VPN profile.  Returns False if the profile doesn't exist.

    Only non-None arguments are updated.  For *vars*, each key-value pair is
    upserted individually (pass only the vars you want to change).
    Secret values must already be encrypted by the caller.

    When *allowed_var_keys* is provided, stored vars whose key is NOT in the
    set are deleted — used when the provider or VPN type changes so stale
    credentials of the previous type are not injected later.
    """
    with get_db() as db:
        p = db.execute('SELECT id FROM vpn_profiles WHERE id = ?', (profile_id,)).fetchone()
        if not p:
            return False

        fields: list[str] = ["updated_at = CURRENT_TIMESTAMP"]
        params: list = []
        if name is not None:
            fields.append('name = ?');          params.append(name)
        if provider is not None:
            fields.append('provider = ?');      params.append(provider)
        if vpn_type is not None:
            fields.append('vpn_type = ?');      params.append(vpn_type)
        if enabled is not None:
            fields.append('enabled = ?');       params.append(int(enabled))
        if rotation_allowed is not None:
            fields.append('rotation_allowed = ?'); params.append(int(rotation_allowed))
        if rotation_priority is not None:
            fields.append('rotation_priority = ?'); params.append(rotation_priority)
        if sidecar_private_key is not None:
            fields.append('sidecar_private_key = ?');  params.append(sidecar_private_key)
        if sidecar_addresses is not None:
            fields.append('sidecar_addresses = ?');    params.append(sidecar_addresses)
        if sidecar_preshared_key is not None:
            fields.append('sidecar_preshared_key = ?'); params.append(sidecar_preshared_key)
        if sidecar_reuse_profile is not None:
            fields.append('sidecar_reuse_profile = ?'); params.append(int(sidecar_reuse_profile))
        if port_forwarding is not None:
            fields.append('port_forwarding = ?');    params.append(int(port_forwarding))
        if port_forward_only is not None:
            fields.append('port_forward_only = ?');  params.append(int(port_forward_only))
        if server_types is not None:
            fields.append('server_types = ?');       params.append(_clean_server_types(server_types))

        if fields:
            params.append(profile_id)
            db.execute(
                f'UPDATE vpn_profiles SET {", ".join(fields)} WHERE id = ?',
                params,
            )

        if vars is not None:
            for var_key, var_value in vars.items():
                db.execute(
                    'INSERT OR REPLACE INTO vpn_profile_vars (profile_id, var_key, var_value) '
                    'VALUES (?, ?, ?)',
                    (profile_id, var_key, var_value),
                )

        if allowed_var_keys is not None:
            rows = db.execute(
                'SELECT var_key FROM vpn_profile_vars WHERE profile_id = ?',
                (profile_id,),
            ).fetchall()
            stale = [r['var_key'] for r in rows if r['var_key'] not in allowed_var_keys]
            for var_key in stale:
                db.execute(
                    'DELETE FROM vpn_profile_vars WHERE profile_id = ? AND var_key = ?',
                    (profile_id, var_key),
                )
    return True


def delete_vpn_profile(profile_id: int) -> bool:
    """Delete a VPN profile, its vars (FK cascade), and unassign servers.

    vpn_profile_vars uses ON DELETE CASCADE → removed automatically when
    PRAGMA foreign_keys=ON (now set in get_db).
    servers.vpn_profile_id has no cascade → we NULL it explicitly.
    """
    with get_db() as db:
        p = db.execute('SELECT id FROM vpn_profiles WHERE id = ?', (profile_id,)).fetchone()
        if not p:
            return False
        # Unassign servers so they are not left with a dangling FK
        db.execute('UPDATE servers SET vpn_profile_id = NULL WHERE vpn_profile_id = ?',
                   (profile_id,))
        db.execute('DELETE FROM vpn_profiles WHERE id = ?', (profile_id,))
    return True


def get_servers_without_profile() -> list[dict]:
    """Return servers that have no vpn_profile_id set (orphaned servers)."""
    with get_db() as db:
        rows = db.execute(
            'SELECT id, name, filter_type, enabled FROM servers '
            'WHERE vpn_profile_id IS NULL ORDER BY name'
        ).fetchall()
    return [dict(r) for r in rows]


def assign_servers_to_profile(server_ids: list[int], profile_id: int) -> int:
    """Set vpn_profile_id for the given server ids.  Returns number of rows updated."""
    if not server_ids:
        return 0
    placeholders = ','.join('?' * len(server_ids))
    with get_db() as db:
        cur = db.execute(
            f'UPDATE servers SET vpn_profile_id = ? WHERE id IN ({placeholders})',
            [profile_id, *server_ids],
        )
    return cur.rowcount


# ---------------------------------------------------------------------------
# Rotation pools CRUD
# ---------------------------------------------------------------------------

def get_rotation_pools() -> list[dict]:
    """Return all rotation pools ordered by name, with criteria and exclusions."""
    with get_db() as db:
        pools = db.execute(
            'SELECT * FROM rotation_pools ORDER BY name'
        ).fetchall()
        result = []
        for p in pools:
            pd = dict(p)
            crits = db.execute(
                'SELECT * FROM rotation_pool_criteria WHERE pool_id = ? ORDER BY id',
                (pd['id'],),
            ).fetchall()
            pd['criteria'] = [dict(c) for c in crits]
            excl = db.execute(
                'SELECT server_name FROM rotation_pool_exclusions WHERE pool_id = ? ORDER BY server_name',
                (pd['id'],),
            ).fetchall()
            pd['exclusions'] = [r['server_name'] for r in excl]
            result.append(pd)
    return result


def get_rotation_pool(pool_id: int) -> dict | None:
    """Return a single pool with its criteria and exclusions, or None."""
    with get_db() as db:
        p = db.execute(
            'SELECT * FROM rotation_pools WHERE id = ?', (pool_id,)
        ).fetchone()
        if not p:
            return None
        pd = dict(p)
        crits = db.execute(
            'SELECT * FROM rotation_pool_criteria WHERE pool_id = ? ORDER BY id',
            (pool_id,),
        ).fetchall()
        pd['criteria'] = [dict(c) for c in crits]
        excl = db.execute(
            'SELECT server_name FROM rotation_pool_exclusions WHERE pool_id = ? ORDER BY server_name',
            (pool_id,),
        ).fetchall()
        pd['exclusions'] = [r['server_name'] for r in excl]
    return pd


def create_rotation_pool(
    name: str,
    mode: str = 'random',
    criteria_logic: str = 'union',
    enabled: bool = True,
    auto_rotate: bool = False,
    interval_hours: float = 6.0,
    quick_bench: bool = False,
    notify: bool = True,
    top_n: int | None = None,
    criteria: list[dict] | None = None,
    exclusions: list[str] | None = None,
) -> int:
    """Create a rotation pool and its criteria/exclusions.  Returns the new pool id."""
    with get_db() as db:
        cur = db.execute(
            '''INSERT INTO rotation_pools
               (name, mode, criteria_logic, enabled, auto_rotate, interval_hours,
                quick_bench, notify, top_n)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (name, mode, criteria_logic, int(enabled), int(auto_rotate),
             interval_hours, int(quick_bench), int(notify), top_n),
        )
        pool_id = cur.lastrowid
        if criteria:
            for c in criteria:
                db.execute(
                    'INSERT INTO rotation_pool_criteria (pool_id, crit_type, crit_value) '
                    'VALUES (?, ?, ?)',
                    (pool_id, c['crit_type'], c.get('crit_value')),
                )
        if exclusions:
            for server_name in exclusions:
                db.execute(
                    'INSERT OR IGNORE INTO rotation_pool_exclusions (pool_id, server_name) '
                    'VALUES (?, ?)',
                    (pool_id, server_name),
                )
    return pool_id


def update_rotation_pool(
    pool_id: int,
    name: str | None = None,
    mode: str | None = None,
    criteria_logic: str | None = None,
    enabled: bool | None = None,
    auto_rotate: bool | None = None,
    interval_hours: float | None = None,
    quick_bench: bool | None = None,
    notify: bool | None = None,
    top_n=_UNSET,   # None = clear top_n; _UNSET = don't touch
    criteria: list[dict] | None = None,
    exclusions: list[str] | None = None,
) -> bool:
    """Update a pool and optionally replace criteria/exclusions.  Returns False if not found."""
    with get_db() as db:
        if not db.execute('SELECT id FROM rotation_pools WHERE id = ?', (pool_id,)).fetchone():
            return False
        fields, params = [], []
        if name           is not None:  fields.append('name = ?');           params.append(name)
        if mode           is not None:  fields.append('mode = ?');           params.append(mode)
        if criteria_logic is not None:  fields.append('criteria_logic = ?'); params.append(criteria_logic)
        if enabled        is not None:  fields.append('enabled = ?');        params.append(int(enabled))
        if auto_rotate    is not None:  fields.append('auto_rotate = ?');    params.append(int(auto_rotate))
        if interval_hours is not None:  fields.append('interval_hours = ?'); params.append(interval_hours)
        if quick_bench    is not None:  fields.append('quick_bench = ?');    params.append(int(quick_bench))
        if notify         is not None:  fields.append('notify = ?');         params.append(int(notify))
        # top_n uses _UNSET sentinel: None means "clear it", _UNSET means "don't touch"
        if top_n is not _UNSET:         fields.append('top_n = ?');          params.append(top_n)
        if fields:
            params.append(pool_id)
            db.execute(f'UPDATE rotation_pools SET {", ".join(fields)} WHERE id = ?', params)
        if criteria is not None:
            db.execute('DELETE FROM rotation_pool_criteria WHERE pool_id = ?', (pool_id,))
            for c in criteria:
                db.execute(
                    'INSERT INTO rotation_pool_criteria (pool_id, crit_type, crit_value) '
                    'VALUES (?, ?, ?)',
                    (pool_id, c['crit_type'], c.get('crit_value')),
                )
        if exclusions is not None:
            db.execute('DELETE FROM rotation_pool_exclusions WHERE pool_id = ?', (pool_id,))
            for server_name in exclusions:
                db.execute(
                    'INSERT OR IGNORE INTO rotation_pool_exclusions (pool_id, server_name) '
                    'VALUES (?, ?)',
                    (pool_id, server_name),
                )
    return True


def get_pool_exclusions(pool_id: int) -> set[str]:
    """Return explicit server-name exclusions for a pool."""
    with get_db() as db:
        rows = db.execute(
            'SELECT server_name FROM rotation_pool_exclusions WHERE pool_id = ?',
            (pool_id,),
        ).fetchall()
    return {r['server_name'] for r in rows}


def delete_rotation_pool(pool_id: int) -> bool:
    """Delete a pool and cascade-delete its criteria.  Returns False if not found."""
    with get_db() as db:
        if not db.execute('SELECT id FROM rotation_pools WHERE id = ?', (pool_id,)).fetchone():
            return False
        db.execute('DELETE FROM rotation_pools WHERE id = ?', (pool_id,))
    return True


def set_pool_rotation_state(
    pool_id: int,
    last_rotated_at: str,
    next_rotation_at: str | None,
    current_rr_idx: int,
    last_server: str | None = None,
    last_error: str | None = None,
    last_dl_mbps: float | None = None,
) -> None:
    """Update pool rotation state after a successful rotation."""
    with get_db() as db:
        db.execute(
            '''UPDATE rotation_pools
               SET last_rotated_at = ?, next_rotation_at = ?, current_rr_idx = ?,
                   last_server = ?, last_error = ?, last_dl_mbps = ?
               WHERE id = ?''',
            (last_rotated_at, next_rotation_at, current_rr_idx,
             last_server, last_error, last_dl_mbps, pool_id),
        )


def set_pool_last_error(pool_id: int, error: str) -> None:
    """Store the last pool rotation failure for UI/debugging."""
    with get_db() as db:
        db.execute(
            '''UPDATE rotation_pools
               SET last_error = ?, last_rotated_at = datetime('now')
               WHERE id = ?''',
            (error, pool_id),
        )


def set_pool_next_rotation(pool_id: int, next_rotation_at: str | None) -> None:
    """Update only next_rotation_at (used when auto_rotate is toggled)."""
    with get_db() as db:
        db.execute(
            'UPDATE rotation_pools SET next_rotation_at = ? WHERE id = ?',
            (next_rotation_at, pool_id),
        )
