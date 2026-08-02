"""Regression tests for the compression / conditional-request hook."""

import gzip
import os
import unittest

from flask import Flask, Response, jsonify

from app.caching import register_http_cache

ASSETS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'assets'
)

_LONG_BODY = 'hello world ' * 200   # comfortably over the 512-byte floor


class HttpCacheTest(unittest.TestCase):
    def _app(self):
        # Mirrors create_app(): assets/ as the static folder, so URLs are /assets/…
        app = Flask(__name__, static_folder=ASSETS_DIR)
        app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 3600

        @app.route('/page')
        def page():
            return Response(f'<html>{_LONG_BODY}</html>', mimetype='text/html')

        @app.route('/tiny')
        def tiny():
            return Response('ok', mimetype='text/html')

        @app.route('/json')
        def json_route():
            return jsonify({'values': [_LONG_BODY]})

        @app.route('/with-vary')
        def with_vary():
            resp = Response(f'<html>{_LONG_BODY}</html>', mimetype='text/html')
            resp.vary.add('Cookie')
            return resp

        register_http_cache(app)
        return app

    # ── streamed responses ────────────────────────────────────────────────

    def test_static_files_are_served_not_broken(self):
        """send_file() responses are direct-passthrough; touching .data raises."""
        client = self._app().test_client()
        for path in ('/assets/logo.png', '/assets/world-map.svg'):
            with self.subTest(path=path):
                resp = client.get(path, headers={'Accept-Encoding': 'gzip'})
                self.assertEqual(resp.status_code, 200)
                self.assertTrue(resp.get_data())
                resp.close()

    def test_static_files_get_a_bounded_max_age(self):
        client = self._app().test_client()
        resp = client.get('/assets/logo.png')
        self.assertIn('max-age=3600', resp.headers.get('Cache-Control', ''))
        resp.close()

    # ── compression ───────────────────────────────────────────────────────

    def test_gzip_body_is_actually_gzip_framed(self):
        client = self._app().test_client()
        resp = client.get('/page', headers={'Accept-Encoding': 'gzip'})
        self.assertEqual(resp.headers.get('Content-Encoding'), 'gzip')
        body = resp.get_data()
        self.assertEqual(body[:2], b'\x1f\x8b')     # RFC 1952, not zlib's 78 9c
        self.assertIn(_LONG_BODY, gzip.decompress(body).decode())

    def test_json_is_compressed_too(self):
        client = self._app().test_client()
        resp = client.get('/json', headers={'Accept-Encoding': 'gzip'})
        self.assertEqual(resp.headers.get('Content-Encoding'), 'gzip')
        gzip.decompress(resp.get_data())

    def test_small_bodies_are_left_alone(self):
        client = self._app().test_client()
        resp = client.get('/tiny', headers={'Accept-Encoding': 'gzip'})
        self.assertIsNone(resp.headers.get('Content-Encoding'))
        self.assertEqual(resp.get_data(), b'ok')

    def test_client_without_gzip_gets_plain_bytes(self):
        client = self._app().test_client()
        resp = client.get('/page', headers={'Accept-Encoding': 'identity'})
        self.assertIsNone(resp.headers.get('Content-Encoding'))
        self.assertIn(_LONG_BODY, resp.get_data().decode())

    def test_client_explicitly_forbidding_gzip_gets_plain_bytes(self):
        client = self._app().test_client()
        resp = client.get('/page', headers={'Accept-Encoding': 'gzip;q=0, identity'})
        self.assertIsNone(resp.headers.get('Content-Encoding'))
        self.assertIn(_LONG_BODY, resp.get_data().decode())

    # ── headers ───────────────────────────────────────────────────────────

    def test_existing_vary_is_preserved(self):
        """Dropping Vary: Cookie would let a shared cache mix up sessions."""
        client = self._app().test_client()
        resp = client.get('/with-vary', headers={'Accept-Encoding': 'gzip'})
        vary = {v.strip() for v in resp.headers.get('Vary', '').split(',')}
        self.assertIn('Cookie', vary)
        self.assertIn('Accept-Encoding', vary)

    def test_vary_is_set_even_when_not_compressed(self):
        client = self._app().test_client()
        resp = client.get('/page', headers={'Accept-Encoding': 'identity'})
        self.assertIn('Accept-Encoding', resp.headers.get('Vary', ''))

    # ── conditional requests ──────────────────────────────────────────────

    def test_matching_etag_returns_304_with_no_body(self):
        client = self._app().test_client()
        first = client.get('/page', headers={'Accept-Encoding': 'gzip'})
        etag = first.headers.get('ETag')
        self.assertTrue(etag)

        second = client.get('/page', headers={
            'Accept-Encoding': 'gzip', 'If-None-Match': etag,
        })
        self.assertEqual(second.status_code, 304)
        self.assertEqual(second.get_data(), b'')

    def test_stale_etag_returns_the_full_body(self):
        client = self._app().test_client()
        resp = client.get('/page', headers={
            'Accept-Encoding': 'gzip', 'If-None-Match': '"not-the-current-one"',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertIn(_LONG_BODY, gzip.decompress(resp.get_data()).decode())

    def test_dynamic_pages_must_revalidate(self):
        client = self._app().test_client()
        resp = client.get('/page')
        self.assertEqual(resp.headers.get('Cache-Control'), 'no-cache')


if __name__ == '__main__':
    unittest.main()
