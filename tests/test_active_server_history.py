from unittest.mock import MagicMock, patch

import pytest
from flask import Flask

from app import database
from app.scheduler import _check_active_server_history


@pytest.fixture
def observer(tmp_path):
    database.init_db(str(tmp_path / 'companion.db'))
    for key, value in {
        'benchmark_running': '0',
        'last_observed_active_server': 'OldServer',
        'last_observed_gluetun_id': 'old-container-id',
        'discord_webhook_url': 'https://example.invalid/webhook',
        'apprise_urls': 'json://example.invalid',
        'ui_lang': 'en',
        'notify_mention': '@here',
        'notify_mention_level': 'medium',
    }.items():
        database.set_setting(key, value)
    app = Flask(__name__)
    app.config.update(GLUETUN_CONTAINER='gluetun', GLUETUN_HOST='gluetun',
                      GLUETUN_PROXY_PORT=8888)
    container = MagicMock(id='new-container-id')
    with (patch('docker.from_env') as docker,
          patch('app.gluetun.get_active_server', return_value='NewServer') as active,
          patch('app.gluetun.get_public_ips', return_value=('2.2.2.2', None)) as ips,
          patch('app.notify.send_switch_notification') as notify,
          patch('app.scheduler.manual_switch_pending', return_value=False) as pending):
        docker.return_value.containers.get.return_value = container
        yield app, container, active, ips, notify, pending


def rows():
    with database.get_db() as db:
        return db.execute('SELECT * FROM switches ORDER BY id').fetchall()


def record(source, target, reason='manual'):
    with database.get_db() as db:
        db.execute('INSERT INTO switches (from_server, to_server, reason, success) '
                   'VALUES (?, ?, ?, 1)', (source, target, reason))


@pytest.mark.parametrize('recreated', [True, False])
def test_records_and_notifies_observed_server_change_once(observer, recreated):
    app, container, _, _, notify, _ = observer
    if not recreated:
        container.id = 'old-container-id'
    _check_active_server_history(app)
    _check_active_server_history(app)
    assert len(rows()) == 1
    row = rows()[0]
    reason = 'external_recreate' if recreated else 'vpn_reconnect'
    assert (row['from_server'], row['to_server'], row['reason'], row['success']) == (
        'OldServer', 'NewServer', reason, 1)
    notify.assert_called_once_with(
        from_server='OldServer', to_server='NewServer', from_mbps=None,
        to_mbps=None, connect_secs=None, to_ipv4='2.2.2.2', to_ipv6=None,
        reason=reason, discord_url='https://example.invalid/webhook',
        apprise_urls='json://example.invalid', lang='en', companion_url=None,
        mention='@here', mention_level='medium', alert_type='auto_switch')


def test_disabled_notification_still_records_history(observer):
    app, _, _, _, notify, _ = observer
    database.set_setting('notif_auto_switch', '0')
    _check_active_server_history(app)
    assert len(rows()) == 1
    notify.assert_not_called()


@pytest.mark.parametrize('previous,active', [('', 'NewServer'), ('OldServer', 'OldServer'),
                                            ('OldServer', None)])
def test_initial_unchanged_or_unknown_server_is_silent(observer, previous, active):
    app, _, get_active, _, notify, _ = observer
    database.set_setting('last_observed_active_server', previous)
    get_active.return_value = active
    _check_active_server_history(app)
    assert not rows()
    notify.assert_not_called()


@pytest.mark.parametrize('manual', [False, True])
def test_inflight_companion_operation_is_not_observed(observer, manual):
    app, _, active, _, notify, pending = observer
    if manual:
        pending.return_value = True
    else:
        database.set_setting('benchmark_running', '1')
    _check_active_server_history(app)
    active.assert_not_called()
    notify.assert_not_called()
    assert not rows()


def test_companion_switch_does_not_generate_duplicate_notification(observer):
    app, _, _, _, notify, _ = observer
    record('OldServer', 'SERVER_NAMES=NewServer')
    _check_active_server_history(app)
    assert len(rows()) == 1
    notify.assert_not_called()
    assert database.get_setting('last_observed_active_server') == 'NewServer'


@pytest.mark.parametrize('reason', ['external_recreate', 'vpn_reconnect', 'manual'])
def test_earlier_visit_does_not_hide_return_to_same_server(observer, reason):
    app, _, _, _, notify, _ = observer
    record('AnotherServer', 'NewServer', reason)
    record('NewServer', 'OldServer', reason)
    _check_active_server_history(app)
    assert len(rows()) == 3
    notify.assert_called_once()


def test_previous_external_row_does_not_suppress_real_transition(observer):
    app, _, _, _, notify, _ = observer
    record('AnotherServer', 'NewServer', 'external_recreate')
    _check_active_server_history(app)
    assert len(rows()) == 2
    notify.assert_called_once()


def test_ip_lookup_failure_still_notifies_server_change(observer):
    app, _, _, ips, notify, _ = observer
    ips.side_effect = RuntimeError('proxy unavailable')
    _check_active_server_history(app)
    assert len(rows()) == 1
    assert notify.call_args.kwargs['to_ipv4'] is None
    assert notify.call_args.kwargs['to_ipv6'] is None
