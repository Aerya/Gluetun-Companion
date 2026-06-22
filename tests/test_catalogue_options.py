import unittest
from unittest.mock import patch

from app.routes import (
    _normalize_catalogue_filter_type,
    _normalize_catalogue_server_type,
)


class CatalogueOptionsTest(unittest.TestCase):
    def test_all_attributes_are_kept_for_explicit_proton_provider(self):
        self.assertEqual(
            _normalize_catalogue_filter_type('provider', 'protonvpn', 'all'),
            'all',
        )
        self.assertEqual(
            _normalize_catalogue_server_type('provider', 'protonvpn', 'p2p'),
            'p2p',
        )

    def test_proton_options_are_dropped_for_other_provider(self):
        self.assertEqual(
            _normalize_catalogue_filter_type('provider', 'airvpn', 'all'),
            'name',
        )
        self.assertEqual(
            _normalize_catalogue_server_type('provider', 'airvpn', 'p2p'),
            '',
        )

    @patch('app.catalogue.detect_active_provider', return_value='protonvpn')
    def test_active_proton_keeps_proton_options(self, _detect):
        self.assertEqual(
            _normalize_catalogue_filter_type('active', '', 'all', 'gluetun'),
            'all',
        )
        self.assertEqual(
            _normalize_catalogue_server_type('active', '', 'p2p', 'gluetun'),
            'p2p',
        )


if __name__ == '__main__':
    unittest.main()
