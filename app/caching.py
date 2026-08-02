"""Flask-Caching instance plus the after_request gzip / ETag hook."""

import gzip

from flask_caching import Cache
from flask import Response, request

# ---------------------------------------------------------------------------
# Data cache
# ---------------------------------------------------------------------------
# In-process is enough: the app runs a single gunicorn worker so APScheduler
# is not duplicated.
cache = Cache()

CACHE_CONFIG = {
    'CACHE_TYPE': 'SimpleCache',
    'CACHE_DEFAULT_TIMEOUT': 3,
    'CACHE_THRESHOLD': 64,
}


# ---------------------------------------------------------------------------
# HTTP compression + conditional requests
# ---------------------------------------------------------------------------

# Types that actually shrink — already-compressed formats (png, woff2, …) are skipped.
_COMPRESSIBLE_MIMETYPES = frozenset({
    'text/html',
    'text/css',
    'text/plain',
    'text/xml',
    'application/json',
    'application/javascript',
    'image/svg+xml',
})

# Below this, framing overhead cancels out the saving.
_MIN_COMPRESS_BYTES = 512

_GZIP_LEVEL = 6


def register_http_cache(app) -> None:
    """Install the compression / ETag ``after_request`` hook on ``app``."""

    @app.after_request
    def _compress_and_cache(response: Response) -> Response:
        # send_file() responses stream off disk — reading .data raises. Werkzeug
        # already gives them an ETag, Last-Modified and Cache-Control.
        if response.direct_passthrough or response.status_code != 200:
            return response

        # vary.add, not assignment: an existing "Vary: Cookie" must survive.
        response.vary.add('Accept-Encoding')
        # Without a stored ui_lang the UI language is negotiated from the
        # browser, so the same URL can render FR or EN.
        response.vary.add('Accept-Language')

        if (
            response.mimetype in _COMPRESSIBLE_MIMETYPES
            # ``gzip;q=0`` explicitly forbids gzip.  Use Werkzeug's parsed
            # quality value instead of a substring check so such clients keep
            # receiving the identity representation.
            and request.accept_encodings['gzip'] > 0
            and 'Content-Encoding' not in response.headers
            and response.content_length is not None
            and response.content_length > _MIN_COMPRESS_BYTES
        ):
            response.set_data(gzip.compress(response.get_data(), _GZIP_LEVEL))
            response.headers['Content-Encoding'] = 'gzip'

        # Revalidate every time; the ETag makes that a bodyless 304.
        response.headers.setdefault('Cache-Control', 'no-cache')

        response.add_etag()
        return response.make_conditional(request)
