"""
Usage-profile definitions and per-profile server scoring.

Each profile defines a weight vector over 6 metrics:
  dl       — multi-stream download Mbps  (higher = better)
  ul       — upload Mbps                  (higher = better)
  lat      — latency ms                   (lower  = better)
  jit      — jitter ms                    (lower  = better)
  loss     — packet loss %                (lower  = better)
  single   — single-stream download Mbps  (higher = better)

The 'balanced' profile (w_dl=1, others=0) reproduces the existing
benchmark behaviour exactly when combined with the weighted_score
(order-preserving normalisation).

Public functions
----------------
score_servers(rows, profile_key, stability)  → {name: float} for /servers display
score_results(results, profile_key, ws_dict) → {name: float} for _do_benchmark
"""

from __future__ import annotations

PROFILES: dict[str, dict] = {
    'balanced': {
        'label_fr':   'Équilibré (défaut)',
        'label_en':   'Balanced (default)',
        'hint_fr':    'Sélection basée sur le score pondéré existant (débit + historique + stabilité)',
        'hint_en':    'Selection based on the existing weighted score (speed + history + stability)',
        'weights':    {'dl': 1.0, 'ul': 0.0, 'lat': 0.0, 'jit': 0.0, 'loss': 0.0, 'single': 0.0},
        'use_single': False,
    },
    'gaming': {
        'label_fr':   'Jeu en ligne',
        'label_en':   'Gaming',
        'hint_fr':    'Priorité à la faible latence et au jitter ; débit secondaire',
        'hint_en':    'Prioritises low latency and jitter; speed is secondary',
        'weights':    {'dl': 0.2, 'ul': 0.2, 'lat': 0.4, 'jit': 0.4, 'loss': 0.3, 'single': 0.0},
        'use_single': False,
    },
    'torrent': {
        'label_fr':   'BitTorrent',
        'label_en':   'BitTorrent',
        'hint_fr':    "Priorité à l'upload multiflux ; latence ignorée",
        'hint_en':    'Prioritises multi-stream upload; latency ignored',
        'weights':    {'dl': 0.3, 'ul': 1.0, 'lat': 0.0, 'jit': 0.0, 'loss': 0.2, 'single': 0.0},
        'use_single': False,
    },
    'ddl': {
        'label_fr':   'DDL (mono-flux)',
        'label_en':   'DDL (single-stream)',
        'hint_fr':    'Priorité au débit monoflux ; idéal pour Usenet / téléchargeurs directs',
        'hint_en':    'Prioritises single-stream download; ideal for Usenet / direct downloaders',
        'weights':    {'dl': 0.3, 'ul': 0.0, 'lat': 0.0, 'jit': 0.0, 'loss': 0.1, 'single': 1.0},
        'use_single': True,
    },
    'download': {
        'label_fr':   'Téléchargement (multi-flux)',
        'label_en':   'Download (multi-stream)',
        'hint_fr':    'Priorité au débit de téléchargement multiflux maximal',
        'hint_en':    'Prioritises maximum multi-stream download throughput',
        'weights':    {'dl': 1.0, 'ul': 0.0, 'lat': 0.1, 'jit': 0.0, 'loss': 0.1, 'single': 0.0},
        'use_single': False,
    },
    'streaming': {
        'label_fr':   'Streaming vidéo',
        'label_en':   'Video streaming',
        'hint_fr':    'Bon débit + faible jitter ; stabilité importante',
        'hint_en':    'Good throughput + low jitter; stability matters',
        'weights':    {'dl': 0.6, 'ul': 0.0, 'lat': 0.2, 'jit': 0.4, 'loss': 0.3, 'single': 0.0},
        'use_single': False,
    },
}


def _opt(v) -> 'float | None':
    """Return float(v) when v is a real measurement, None when it is missing."""
    return float(v) if v is not None else None


def _pnorm(vals: dict[str, 'float | None'], invert: bool = False) -> dict[str, float]:
    """Min-max normalise a {name: value | None} dict to [0, 1].

    Entries whose value is None (no measurement at all) receive a neutral
    score of 0.5 — they neither win nor lose on this dimension.
    If *invert* is True the direction is flipped (lower raw = 1.0).
    When all known values are identical every measured server gets 1.0.
    """
    if not vals:
        return {}
    known = {k: v for k, v in vals.items() if v is not None}
    if not known:
        return {k: 0.5 for k in vals}
    mn = min(known.values())
    mx = max(known.values())
    if mx == mn:
        normed = {k: 1.0 for k in known}
    else:
        normed = {k: (v - mn) / (mx - mn) for k, v in known.items()}
    if invert:
        normed = {k: 1.0 - n for k, n in normed.items()}
    result = {k: 0.5 for k in vals}   # neutral score for unmeasured servers
    result.update(normed)
    return result


def _row_get(row, key: str, default=None):
    """Return a value from dict-like rows, including sqlite3.Row."""
    if hasattr(row, 'get'):
        return row.get(key, default)
    try:
        return row[key]
    except (KeyError, IndexError):
        return default


def score_servers(
    rows,
    profile_key: str,
    stability: dict[str, dict],
) -> dict[str, float]:
    """Compute a profile score ∈ [0, 1] for each server using historical averages.

    *rows* must expose: name, avg_dl, avg_ul, avg_lat, avg_dl_single (may be None).
    *stability* is from database.get_stability_all().

    Returns {server_name: score}.
    """
    profile = PROFILES.get(profile_key, PROFILES['balanced'])
    w = profile['weights']

    names = [r['name'] for r in rows]
    if not names:
        return {}

    # dl/ul/single: 0.0 when NULL means "never tested" → legitimate worst score
    raw_dl     = {r['name']: float(r['avg_dl']              or 0.0) for r in rows}
    raw_ul     = {r['name']: float(r['avg_ul']              or 0.0) for r in rows}
    raw_single = {r['name']: float(_row_get(r, 'avg_dl_single') or 0.0) for r in rows}
    # lat/jit/loss: None when NULL means "no measurement" → neutral 0.5 via _pnorm
    # (0ms latency / 0ms jitter / 0% loss are impossible to fake; defaulting to 0.0
    #  would make unmeasured servers appear as the best, skewing all profile scores)
    raw_lat    = {r['name']: _opt(r['avg_lat'])                                       for r in rows}
    raw_jit    = {r['name']: _opt((stability.get(r['name']) or {}).get('avg_jitter')) for r in rows}
    raw_loss   = {r['name']: _opt((stability.get(r['name']) or {}).get('avg_loss'))   for r in rows}

    n_dl     = _pnorm(raw_dl)
    n_ul     = _pnorm(raw_ul)
    n_lat    = _pnorm(raw_lat,  invert=True)
    n_jit    = _pnorm(raw_jit,  invert=True)
    n_loss   = _pnorm(raw_loss, invert=True)
    n_single = _pnorm(raw_single)

    total_w = sum(w.values())
    if total_w == 0:
        return {name: 0.0 for name in names}

    scores: dict[str, float] = {}
    for name in names:
        score = (
            w['dl']     * n_dl    .get(name, 0.0)
            + w['ul']     * n_ul    .get(name, 0.0)
            + w['lat']    * n_lat   .get(name, 0.0)
            + w['jit']    * n_jit   .get(name, 0.0)
            + w['loss']   * n_loss  .get(name, 0.0)
            + w['single'] * n_single.get(name, 0.0)
        ) / total_w
        scores[name] = round(score, 4)
    return scores


def score_servers_detail(
    rows,
    profile_key: str,
    stability: dict[str, dict],
) -> tuple[dict[str, float], dict[str, dict]]:
    """Like score_servers() but also returns the per-component breakdown.

    Returns (scores, details) where:
      scores  = {name: float}          — same output as score_servers()
      details = {name: {
          'score':      int  (0–100),
          'components': {'dl', 'ul', 'lat', 'jit', 'loss'}  — normalised 0–100
          'raws':       {'dl', 'ul', 'lat', 'jit', 'loss'}  — raw measured values
          'weights':    profile weight vector
      }}
    """
    profile = PROFILES.get(profile_key, PROFILES['balanced'])
    w = profile['weights']

    names = [r['name'] for r in rows]
    if not names:
        return {}, {}

    raw_dl     = {r['name']: float(r['avg_dl']              or 0.0) for r in rows}
    raw_ul     = {r['name']: float(r['avg_ul']              or 0.0) for r in rows}
    raw_single = {r['name']: float(_row_get(r, 'avg_dl_single') or 0.0) for r in rows}
    raw_lat    = {r['name']: _opt(r['avg_lat'])                         for r in rows}
    raw_jit    = {r['name']: _opt((stability.get(r['name']) or {}).get('avg_jitter')) for r in rows}
    raw_loss   = {r['name']: _opt((stability.get(r['name']) or {}).get('avg_loss'))   for r in rows}

    n_dl     = _pnorm(raw_dl)
    n_ul     = _pnorm(raw_ul)
    n_lat    = _pnorm(raw_lat,    invert=True)
    n_jit    = _pnorm(raw_jit,    invert=True)
    n_loss   = _pnorm(raw_loss,   invert=True)
    n_single = _pnorm(raw_single)

    total_w = sum(w.values()) or 1.0

    scores:  dict[str, float] = {}
    details: dict[str, dict]  = {}

    for name in names:
        c_dl   = n_dl.get(name, 0.0)
        c_ul   = n_ul.get(name, 0.0)
        c_lat  = n_lat.get(name, 0.0)
        c_jit  = n_jit.get(name, 0.0)
        c_loss = n_loss.get(name, 0.0)
        c_sg   = n_single.get(name, 0.0)

        score = (
            w['dl']     * c_dl
            + w['ul']   * c_ul
            + w['lat']  * c_lat
            + w['jit']  * c_jit
            + w['loss'] * c_loss
            + w['single'] * c_sg
        ) / total_w

        scores[name] = round(score, 4)
        details[name] = {
            'score': round(score * 100),
            'components': {
                'dl':   round(c_dl   * 100),
                'ul':   round(c_ul   * 100),
                'lat':  round(c_lat  * 100),
                'jit':  round(c_jit  * 100),
                'loss': round(c_loss * 100),
            },
            'raws': {
                'dl':   raw_dl.get(name),
                'ul':   raw_ul.get(name),
                'lat':  raw_lat.get(name),
                'jit':  raw_jit.get(name),
                'loss': raw_loss.get(name),
            },
            'weights': {k: v for k, v in w.items()},
        }

    return scores, details


def score_results(
    results: list[dict],
    profile_key: str,
    weighted_scores: dict[str, float],
) -> dict[str, float]:
    """Compute a profile score for each result dict from the current benchmark cycle.

    *results* items must have: server, dl, ul, lat, jitter_ms, packet_loss_pct,
    and optionally dl_single.

    *weighted_scores* is {server_name: _weighted_score_value} (acts as the 'dl'
    axis — preserves existing ordering for the 'balanced' profile).

    Returns {server_name: combined_score}.
    """
    profile = PROFILES.get(profile_key, PROFILES['balanced'])
    w = profile['weights']

    names = [r['server'] for r in results]
    if not names:
        return {}

    raw_ws     = weighted_scores
    raw_ul     = {r['server']: float(r.get('ul')     or 0.0) for r in results}
    raw_single = {r['server']: float(r.get('dl_single') or 0.0) for r in results}
    raw_lat    = {r['server']: _opt(r.get('lat'))             for r in results}
    raw_jit    = {r['server']: _opt(r.get('jitter_ms'))       for r in results}
    raw_loss   = {r['server']: _opt(r.get('packet_loss_pct')) for r in results}

    n_dl     = _pnorm(raw_ws)
    n_ul     = _pnorm(raw_ul)
    n_lat    = _pnorm(raw_lat,  invert=True)
    n_jit    = _pnorm(raw_jit,  invert=True)
    n_loss   = _pnorm(raw_loss, invert=True)
    n_single = _pnorm(raw_single)

    total_w = sum(w.values())
    if total_w == 0:
        return {name: 0.0 for name in names}

    scores: dict[str, float] = {}
    for name in names:
        score = (
            w['dl']     * n_dl    .get(name, 0.0)
            + w['ul']     * n_ul    .get(name, 0.0)
            + w['lat']    * n_lat   .get(name, 0.0)
            + w['jit']    * n_jit   .get(name, 0.0)
            + w['loss']   * n_loss  .get(name, 0.0)
            + w['single'] * n_single.get(name, 0.0)
        ) / total_w
        scores[name] = round(score, 4)
    return scores
