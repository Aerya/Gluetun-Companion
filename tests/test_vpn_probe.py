"""probe_status() returns VPN status and public IP from one proxy request."""

import unittest
from unittest.mock import patch

from app.gluetun import get_public_ip, get_vpn_status, probe_status

_PROBE_BODY = 'fl=abc\nip=203.0.113.7\nts=1700000000\n'


class _FakeResponse:
    def __init__(self, status_code=200, text=_PROBE_BODY):
        self.status_code = status_code
        self.text = text


class ProbeStatusTest(unittest.TestCase):
    def test_one_request_yields_status_and_ip(self):
        with patch('app.gluetun.requests.get', return_value=_FakeResponse()) as mock_get:
            status, ip = probe_status('gluetun', 8888)
        self.assertEqual(status, 'running')
        self.assertEqual(ip, '203.0.113.7')
        self.assertEqual(mock_get.call_count, 1)

    def test_non_200_reads_as_stopped(self):
        with patch('app.gluetun.requests.get', return_value=_FakeResponse(status_code=502)):
            self.assertEqual(probe_status('gluetun', 8888), ('stopped', None))

    def test_connection_error_reads_as_stopped(self):
        with patch('app.gluetun.requests.get', side_effect=OSError('no route')):
            self.assertEqual(probe_status('gluetun', 8888), ('stopped', None))

    def test_running_without_a_parsable_ip(self):
        with patch('app.gluetun.requests.get', return_value=_FakeResponse(text='fl=abc\n')):
            self.assertEqual(probe_status('gluetun', 8888), ('running', None))

    def test_single_fact_helpers_still_work(self):
        with patch('app.gluetun.requests.get', return_value=_FakeResponse()):
            self.assertEqual(get_vpn_status('gluetun', 8888), 'running')
            self.assertEqual(get_public_ip('gluetun', 8888), '203.0.113.7')


if __name__ == '__main__':
    unittest.main()
