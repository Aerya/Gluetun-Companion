import logging
from app import create_app

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
)

app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8765, debug=False)
