import unittest
from unittest.mock import patch

from flask import Flask, session

from app.i18n import get_lang, negotiate_lang


class I18nLanguageTest(unittest.TestCase):
    def _app(self):
        app = Flask(__name__)
        app.secret_key = 'test-secret'
        return app

    def test_persisted_language_wins_over_stale_session(self):
        app = self._app()
        with app.test_request_context('/'):
            session['lang'] = 'en'
            with patch('app.database.get_setting', return_value='fr'):
                self.assertEqual(get_lang(), 'fr')
                self.assertEqual(session['lang'], 'fr')

    def test_invalid_persisted_language_falls_back_to_french(self):
        app = self._app()
        with app.test_request_context('/'):
            session['lang'] = 'en'
            with patch('app.database.get_setting', return_value='de'):
                self.assertEqual(get_lang(), 'fr')
                self.assertEqual(session['lang'], 'fr')

    def test_english_persisted_language_is_kept(self):
        app = self._app()
        with app.test_request_context('/'):
            session['lang'] = 'fr'
            with patch('app.database.get_setting', return_value='en'):
                self.assertEqual(get_lang(), 'en')
                self.assertEqual(session['lang'], 'en')


class BrowserLanguageDetectionTest(unittest.TestCase):
    def _app(self):
        app = Flask(__name__)
        app.secret_key = 'test-secret'
        return app

    def _detect(self, accept_language):
        """get_lang() with no stored preference and the given browser header."""
        app = self._app()
        headers = {'Accept-Language': accept_language} if accept_language else {}
        with app.test_request_context('/', headers=headers):
            with patch('app.database.get_setting', return_value=''):
                return get_lang()

    def test_english_browser_gets_english(self):
        self.assertEqual(self._detect('en-US,en;q=0.9'), 'en')

    def test_french_browser_gets_french(self):
        self.assertEqual(self._detect('fr-CA,fr;q=0.9,en;q=0.5'), 'fr')

    def test_unsupported_browser_language_falls_back_to_french(self):
        self.assertEqual(self._detect('de-DE,de;q=0.9'), 'fr')

    def test_missing_header_falls_back_to_french(self):
        self.assertEqual(self._detect(None), 'fr')

    def test_stored_preference_beats_browser_header(self):
        app = self._app()
        with app.test_request_context('/', headers={'Accept-Language': 'en-US,en'}):
            with patch('app.database.get_setting', return_value='fr'):
                self.assertEqual(get_lang(), 'fr')

    def test_detected_language_lands_in_session(self):
        app = self._app()
        with app.test_request_context('/', headers={'Accept-Language': 'en-GB'}):
            with patch('app.database.get_setting', return_value=''):
                self.assertEqual(get_lang(), 'en')
                self.assertEqual(session['lang'], 'en')


class NegotiateLangTest(unittest.TestCase):
    def test_quality_ordering_wins_over_position(self):
        self.assertEqual(negotiate_lang('fr;q=0.3,en;q=0.8'), 'en')

    def test_equal_quality_keeps_browser_order(self):
        self.assertEqual(negotiate_lang('en,fr'), 'en')

    def test_first_supported_language_wins_over_unsupported_ones(self):
        self.assertEqual(negotiate_lang('de,es,en-US;q=0.7'), 'en')

    def test_zero_quality_language_is_ignored(self):
        self.assertEqual(negotiate_lang('en;q=0'), 'fr')

    def test_wildcard_gets_the_default(self):
        self.assertEqual(negotiate_lang('*'), 'fr')

    def test_underscore_subtag_is_accepted(self):
        self.assertEqual(negotiate_lang('en_US'), 'en')

    def test_garbage_header_falls_back_to_french(self):
        self.assertEqual(negotiate_lang('!!!;q=abc'), 'fr')

    def test_empty_header_falls_back_to_french(self):
        self.assertEqual(negotiate_lang(''), 'fr')


if __name__ == '__main__':
    unittest.main()
