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


def _env_bool(name, default):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in ('0', 'false', 'no', 'off')


bind = os.environ.get('GUNICORN_BIND', f"0.0.0.0:{os.environ.get('PORT', '5000')}")
worker_class = os.environ.get('GUNICORN_WORKER_CLASS', 'gthread')
workers = _env_int('GUNICORN_WORKERS', 2)
threads = _env_int('GUNICORN_THREADS', 8)
timeout = _env_int('GUNICORN_TIMEOUT', 900)
background_tasks_enabled = _env_bool('SIMPLECHAT_RUN_BACKGROUND_TASKS', True)
graceful_timeout = _env_int('GUNICORN_GRACEFUL_TIMEOUT', 300 if background_tasks_enabled else 60)
keepalive = _env_int('GUNICORN_KEEPALIVE', 75)
# Request-count recycling can terminate in-process background exports mid-batch.
max_requests = _env_int('GUNICORN_MAX_REQUESTS', 0 if background_tasks_enabled else 500)
max_requests_jitter = _env_int('GUNICORN_MAX_REQUESTS_JITTER', 0 if max_requests == 0 else 50)
accesslog = '-'
errorlog = '-'
capture_output = True
preload_app = False
