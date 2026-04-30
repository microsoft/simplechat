# gunicorn.conf.py
import os


def _env_int(name, default):
    value = os.environ.get(name)
    if value is None or value == '':
        return default

    try:
        return int(value)
    except ValueError:
        return default


bind = os.environ.get('GUNICORN_BIND', f"0.0.0.0:{os.environ.get('PORT', '5000')}")
worker_class = os.environ.get('GUNICORN_WORKER_CLASS', 'gthread')
workers = _env_int('GUNICORN_WORKERS', 2)
threads = _env_int('GUNICORN_THREADS', 8)
timeout = _env_int('GUNICORN_TIMEOUT', 900)
graceful_timeout = _env_int('GUNICORN_GRACEFUL_TIMEOUT', 60)
keepalive = _env_int('GUNICORN_KEEPALIVE', 75)
max_requests = _env_int('GUNICORN_MAX_REQUESTS', 500)
max_requests_jitter = _env_int('GUNICORN_MAX_REQUESTS_JITTER', 50)
accesslog = '-'
errorlog = '-'
capture_output = True
preload_app = False
