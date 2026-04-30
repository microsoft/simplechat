#!/usr/bin/env python3
# test_gunicorn_startup_support.py
"""
Functional test for Gunicorn startup support.
Version: 0.239.128
Implemented in: 0.239.128

This test ensures that the application exposes Gunicorn-friendly startup
configuration and only disables background loops when the runtime is
explicitly configured to do so.
"""

import os
import sys
import importlib.util

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))


def load_module(module_name, file_path):
    """Load a module directly from disk for standalone functional validation."""
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise AssertionError(f'Could not load module spec for {module_name}')

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_gunicorn_startup_support():
    """Validate Gunicorn config defaults and runtime helper behavior."""
    print("Testing Gunicorn startup support...")

    original_server_software = os.environ.get('SERVER_SOFTWARE')
    original_background_setting = os.environ.get('SIMPLECHAT_RUN_BACKGROUND_TASKS')
    original_disable_instrumentation = os.environ.get('DISABLE_FLASK_INSTRUMENTATION')

    try:
        os.environ['SERVER_SOFTWARE'] = 'gunicorn/23.0.0'
        os.environ['SIMPLECHAT_RUN_BACKGROUND_TASKS'] = '0'
        os.environ['DISABLE_FLASK_INSTRUMENTATION'] = '1'

        app_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app')
        app_module = load_module('simplechat_app_module', os.path.join(app_dir, 'app.py'))
        import gunicorn
        gunicorn_conf = load_module('simplechat_gunicorn_conf', os.path.join(app_dir, 'gunicorn.conf.py'))

        if gunicorn.__name__ != 'gunicorn':
            raise AssertionError('Gunicorn package import failed')

        if not app_module.is_running_under_gunicorn():
            raise AssertionError('Gunicorn runtime was not detected')

        if app_module.should_start_background_tasks():
            raise AssertionError('Background tasks should stay disabled when explicitly set to 0')

        os.environ.pop('SIMPLECHAT_RUN_BACKGROUND_TASKS', None)
        if not app_module.should_start_background_tasks():
            raise AssertionError('Background tasks should default to enabled when unset')

        os.environ['SIMPLECHAT_RUN_BACKGROUND_TASKS'] = '1'
        if not app_module.should_start_background_tasks():
            raise AssertionError('Background task override did not enable background loops')

        if gunicorn_conf.worker_class != 'gthread':
            raise AssertionError(f"Unexpected worker class: {gunicorn_conf.worker_class}")

        if gunicorn_conf.preload_app is not False:
            raise AssertionError('Gunicorn preload_app should remain disabled')

        if gunicorn_conf.workers < 1 or gunicorn_conf.threads < 1:
            raise AssertionError('Gunicorn workers/threads must be positive integers')

        print('Gunicorn runtime detection: OK')
        print(f"Gunicorn bind: {gunicorn_conf.bind}")
        print(f"Gunicorn workers: {gunicorn_conf.workers}")
        print(f"Gunicorn threads: {gunicorn_conf.threads}")
        print('Background task gating: explicit false disables, unset enables')
        return True

    except Exception as exc:
        print(f"Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        if original_server_software is None:
            os.environ.pop('SERVER_SOFTWARE', None)
        else:
            os.environ['SERVER_SOFTWARE'] = original_server_software

        if original_background_setting is None:
            os.environ.pop('SIMPLECHAT_RUN_BACKGROUND_TASKS', None)
        else:
            os.environ['SIMPLECHAT_RUN_BACKGROUND_TASKS'] = original_background_setting

        if original_disable_instrumentation is None:
            os.environ.pop('DISABLE_FLASK_INSTRUMENTATION', None)
        else:
            os.environ['DISABLE_FLASK_INSTRUMENTATION'] = original_disable_instrumentation


if __name__ == '__main__':
    success = test_gunicorn_startup_support()
    sys.exit(0 if success else 1)
