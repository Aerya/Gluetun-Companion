"""Single-worker manual intent, independent from transient benchmark flags."""
import json
import logging
import threading

from .database import get_setting, set_setting

logger = logging.getLogger(__name__)
_reservation = threading.Lock()
_pending = threading.Event()
_generation = 0


def generation():
    return _generation


_ACTIVE = {'queued', 'switching', 'reconnecting'}


def pending():
    return _pending.is_set()


def status():
    try:
        return json.loads(get_setting('manual_switch_status', '{}') or '{}')
    except (ValueError, TypeError):
        return {}


def update_status(state):
    value = status()
    value['state'] = state
    set_setting('manual_switch_status', json.dumps(value))


def recover_interrupted():
    # Never silently replay a production switch after a process restart.
    if status().get('state') in _ACTIVE:
        update_status('interrupted')


def submit_switch(app, server_id, server_name, execute):
    """Reserve before stopping the current job; duplicate clicks cannot overwrite it."""
    global _generation
    if not _reservation.acquire(blocking=False):
        return False
    _pending.set()
    _generation += 1
    try:
        set_setting('manual_switch_status', json.dumps({
            'server_id': server_id, 'server': server_name, 'state': 'queued',
        }))
        from .scheduler import request_stop
        request_stop()
        threading.Thread(
            target=_run, args=(app, server_id, execute),
            name='manual-switch', daemon=True,
        ).start()
    except Exception:
        try:
            update_status('failed')
        finally:
            _pending.clear()
            _reservation.release()
        raise
    return True


def _run(app, server_id, execute):
    from .scheduler import _lock
    acquired = False
    try:
        with app.app_context():
            # Do not forcibly release a live operation's lock or race its cleanup.
            acquired = _lock.acquire(timeout=600)
            if not acquired:
                update_status('timeout')
                return
            update_status('switching')
            execute(server_id)
            update_status('connected')
    except Exception:
        logger.exception('Manual switch failed')
        with app.app_context():
            update_status('reconnect_failed' if status().get('state') == 'reconnecting' else 'failed')
    finally:
        try:
            if acquired:
                with app.app_context():
                    for key, value in (
                        ('benchmark_running', '0'), ('benchmark_mode', ''),
                        ('benchmark_current_server', ''), ('benchmark_stop_requested', '0'),
                    ):
                        set_setting(key, value)
        finally:
            # Keep automatic jobs excluded until production reconciliation ends.
            _pending.clear()
            if acquired:
                _lock.release()
            _reservation.release()
