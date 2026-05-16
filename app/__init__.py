import json
import logging
import os

from flask import Flask
from .database import init_db


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            'ts':      self.formatTime(record, '%Y-%m-%dT%H:%M:%S'),
            'level':   record.levelname,
            'logger':  record.name,
            'msg':     record.getMessage(),
        }
        if record.exc_info:
            entry['exc'] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


def _configure_logging():
    level = os.environ.get('LOG_LEVEL', 'INFO').upper()
    handler = logging.StreamHandler()
    if os.environ.get('LOG_JSON', '0') == '1':
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            '%(asctime)s %(levelname)-8s %(name)s  %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S',
        ))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(getattr(logging, level, logging.INFO))


def create_app():
    _configure_logging()

    app = Flask(
        __name__,
        template_folder='templates',
        static_folder=os.path.join(os.path.dirname(__file__), '..', 'static'),
    )
    app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-change-me')

    app.config['DATA_DIR']         = os.environ.get('DATA_DIR', '/data')
    app.config['DB_PATH']          = os.path.join(app.config['DATA_DIR'], 'companion.db')
    app.config['GLUETUN_HOST']     = os.environ.get('GLUETUN_HOST', 'host.docker.internal')
    app.config['GLUETUN_PROXY_PORT'] = int(os.environ.get('GLUETUN_PROXY_PORT', '8887'))
    app.config['GLUETUN_CONTAINER'] = os.environ.get('GLUETUN_CONTAINER', 'gluetun-airvpn')
    app.config['COMPOSE_DIR']      = os.environ.get('COMPOSE_DIR', '/compose')
    app.config['COMPOSE_PROJECT']  = os.environ.get('COMPOSE_PROJECT', '')

    os.makedirs(app.config['DATA_DIR'], exist_ok=True)
    init_db(app.config['DB_PATH'])

    from .routes import bp
    app.register_blueprint(bp)

    from .scheduler import start_scheduler
    start_scheduler(app)

    return app
