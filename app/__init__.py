import os
from flask import Flask
from .database import init_db


def create_app():
    app = Flask(
        __name__,
        template_folder='templates',
        static_folder=os.path.join(os.path.dirname(__file__), '..', 'static'),
    )
    app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-change-me')

    app.config['DATA_DIR'] = os.environ.get('DATA_DIR', '/data')
    app.config['DB_PATH'] = os.path.join(app.config['DATA_DIR'], 'companion.db')
    app.config['GLUETUN_HOST'] = os.environ.get('GLUETUN_HOST', 'gluetun-airvpn')
    app.config['GLUETUN_PROXY_PORT'] = int(os.environ.get('GLUETUN_PROXY_PORT', '8887'))
    app.config['GLUETUN_API_PORT'] = int(os.environ.get('GLUETUN_API_PORT', '8000'))
    app.config['GLUETUN_CONTAINER'] = os.environ.get('GLUETUN_CONTAINER', 'gluetun-airvpn')
    app.config['COMPOSE_DIR'] = os.environ.get('COMPOSE_DIR', '/compose')
    app.config['COMPOSE_PROJECT'] = os.environ.get('COMPOSE_PROJECT', '')

    os.makedirs(app.config['DATA_DIR'], exist_ok=True)
    init_db(app.config['DB_PATH'])

    from .routes import bp
    app.register_blueprint(bp)

    from .scheduler import start_scheduler
    start_scheduler(app)

    return app
