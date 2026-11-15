"""Docker ``exec`` that degrades cleanly when a socket proxy forbids it.

With ``docker-socket-proxy`` and ``EXEC=0`` (the documented setup), creating
an exec is allowed (``POST /containers/{id}/exec`` falls under
``CONTAINERS=1``) but starting it is refused (``POST /exec/{id}/start`` →
403).  Every attempt therefore leaves a never-started exec record held by
dockerd until the target container restarts.  Retrying on each call piles up
thousands of them per day.

The gate below learns whether exec may be *started* without creating
anything: it starts an exec ID that cannot exist.  A proxy that forbids exec
answers 403; when the request reaches Docker, it answers 404 ("no such exec
instance").  Exec instances are only created once that probe says allowed.
A denied state is re-probed periodically, so granting ``EXEC=1`` later is
picked up automatically, without restarting Companion.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

ALLOWED = 'allowed'
DENIED = 'denied'
UNKNOWN = 'unknown'

# 64 hex characters: matches proxy allowlists for exec IDs, never a real exec.
_PROBE_EXEC_ID = '0' * 64
DENIED_RECHECK_SECS = 300.0      # cheap probe, creates nothing
ALLOWED_RECHECK_SECS = 3600.0    # a revoked permission is also caught by real 403s
UNKNOWN_RECHECK_SECS = 30.0      # Docker/proxy unreachable: retry soon


def _status_code(exc: Exception) -> int | None:
    response = getattr(exc, 'response', None)
    code = getattr(response, 'status_code', None)
    if code is None:
        code = getattr(exc, 'status_code', None)
    return code


class ExecGate:
    """Process-wide knowledge of whether ``docker exec`` can be started."""

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._state = UNKNOWN
        self._checked_at: float | None = None
        self._logged_denied = False

    @property
    def state(self) -> str:
        return self._state

    def _set(self, state: str) -> None:
        if state == DENIED and not self._logged_denied:
            logger.warning(
                'Docker exec is refused (docker-socket-proxy without EXEC=1?). '
                'Features that read files inside Gluetun fall back to safe '
                'defaults; re-checking every %d s without creating exec instances.',
                int(DENIED_RECHECK_SECS),
            )
            self._logged_denied = True
        elif state == ALLOWED and self._state == DENIED:
            logger.info('Docker exec is now allowed: exact checks resume.')
            self._logged_denied = False
        self._state = state
        self._checked_at = self._clock()

    def mark_denied(self) -> None:
        with self._lock:
            self._set(DENIED)

    def _due(self) -> bool:
        if self._checked_at is None:
            return True
        ttl = {ALLOWED: ALLOWED_RECHECK_SECS, DENIED: DENIED_RECHECK_SECS}.get(
            self._state, UNKNOWN_RECHECK_SECS)
        return self._clock() - self._checked_at >= ttl

    def check(self, api) -> str:
        """Return ALLOWED, DENIED or UNKNOWN, probing only when the cache expired."""
        with self._lock:
            if not self._due():
                return self._state
            self._set(self._probe(api))
            return self._state

    @staticmethod
    def _probe(api) -> str:
        try:
            api.exec_start(_PROBE_EXEC_ID)
        except Exception as exc:
            code = _status_code(exc)
            if code == 404:
                return ALLOWED     # reached Docker: exec endpoints are open
            if code in (401, 403):
                return DENIED
            logger.debug('Docker exec probe inconclusive: %s', exc)
            return UNKNOWN
        return ALLOWED             # cannot happen with a non-existent ID

    def reset(self) -> None:
        with self._lock:
            self._state = UNKNOWN
            self._checked_at = None
            self._logged_denied = False


gate = ExecGate()


@dataclass
class ExecOutcome:
    """Result of :func:`run_in_container`.

    ``status`` is ``ok`` when the command ran (whatever its exit code),
    ``denied`` when Docker exec is refused, ``unavailable`` when it could not
    be attempted (Docker unreachable, container gone, unexpected error).
    """
    status: str
    exit_code: int | None = None
    output: bytes = b''

    @property
    def ran(self) -> bool:
        return self.status == 'ok'


def run_in_container(container, cmd: list[str], **kwargs) -> ExecOutcome:
    """``container.exec_run`` guarded by :data:`gate`.

    Never creates an exec instance while exec is known to be refused.
    """
    api = container.client.api
    state = gate.check(api)
    if state == DENIED:
        return ExecOutcome('denied')
    if state == UNKNOWN:
        return ExecOutcome('unavailable')
    try:
        result = container.exec_run(cmd, **kwargs)
    except Exception as exc:
        if _status_code(exc) in (401, 403):
            # Permission revoked since the last probe: at most one abandoned
            # exec, then no new one until a probe says allowed again.
            gate.mark_denied()
            return ExecOutcome('denied')
        logger.debug('docker exec %s failed: %s', cmd[:1], exc)
        return ExecOutcome('unavailable')
    return ExecOutcome('ok', getattr(result, 'exit_code', None), getattr(result, 'output', b'') or b'')
