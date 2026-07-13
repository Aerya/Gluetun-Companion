"""Global eligibility rules for automatic VPN server selection."""

from __future__ import annotations

import json


def parse_excluded_countries(raw: str | None) -> set[str]:
    """Return normalized ISO country codes from the JSON setting."""
    try:
        values = json.loads(raw or '[]')
    except (TypeError, json.JSONDecodeError):
        return set()
    if not isinstance(values, list):
        return set()
    return {
        str(value).strip().upper()
        for value in values
        if str(value).strip()
    }


def available_countries(db) -> list[dict[str, str]]:
    """List countries known by either the Gluetun catalogue or AirVPN API."""
    rows = db.execute(
        '''SELECT country_code, MAX(country) AS country
           FROM (
               SELECT country_code, country FROM gluetun_catalogue
               UNION ALL
               SELECT country_code, country FROM airvpn_snapshot
           )
           WHERE country_code != ''
           GROUP BY UPPER(country_code)
           ORDER BY country COLLATE NOCASE, country_code'''
    ).fetchall()
    return [
        {'code': row['country_code'].upper(), 'name': row['country'] or row['country_code'].upper()}
        for row in rows
    ]


def excluded_server_names(db, country_codes: set[str]) -> set[str]:
    """Resolve server names belonging to globally excluded countries."""
    if not country_codes:
        return set()
    placeholders = ','.join('?' for _ in country_codes)
    params = sorted(country_codes)
    rows = db.execute(
        f'''SELECT DISTINCT name
            FROM (
                SELECT name, UPPER(country_code) AS country_code
                FROM gluetun_catalogue
                UNION ALL
                SELECT name, UPPER(country_code) AS country_code
                FROM airvpn_snapshot
            )
            WHERE country_code IN ({placeholders})''',
        params,
    ).fetchall()
    return {row['name'] for row in rows}
