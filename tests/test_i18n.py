import unittest
from unittest.mock import patch

from flask import Flask, session

from app.i18n import get_lang


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


if __name__ == '__main__':
    unittest.main()
