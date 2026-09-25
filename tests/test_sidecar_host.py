"""Regression tests for the separate sidecar poll address."""

import unittest

from app.gluetun import get_sidecar_host


class SidecarHostTest(unittest.TestCase):
    def test_uses_gluetun_host_when_no_override_is_configured(self):
        self.assertEqual(get_sidecar_host({'GLUETUN_HOST': 'gluetun'}), 'gluetun')

    def test_uses_dedicated_host_for_published_sidecar_endpoint(self):
        self.assertEqual(
            get_sidecar_host({'GLUETUN_HOST': 'gluetun', 'SIDECAR_HOST': 'host.docker.internal'}),
            'host.docker.internal',
        )

    def test_empty_override_keeps_backward_compatible_default(self):
        self.assertEqual(get_sidecar_host({'GLUETUN_HOST': 'gluetun', 'SIDECAR_HOST': ''}), 'gluetun')


if __name__ == '__main__':
    unittest.main()
