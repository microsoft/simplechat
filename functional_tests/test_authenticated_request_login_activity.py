# test_authenticated_request_login_activity.py
#!/usr/bin/env python3
"""
Functional test for authenticated request login activity tracking.
Version: 0.241.130
Implemented in: 0.241.130

This test ensures that passive authenticated browser requests emit a throttled
login activity record and that explicit OAuth callback logins do not double
count on the immediate redirect.
"""

import importlib.util
import sys
import types
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / 'application' / 'single_app' / 'functions_activity_logging.py'
MODULE_NAME = 'functional_test_functions_activity_logging'


class FakeContainer:
    def __init__(self):
        self.items = []

    def create_item(self, body):
        self.items.append(body)


class FakeSession(dict):
    def __init__(self):
        super().__init__()
        self.modified = False


def load_functions_activity_logging(fake_container):
    fake_config = types.ModuleType('config')
    fake_config.cosmos_activity_logs_container = fake_container

    fake_appinsights = types.ModuleType('functions_appinsights')
    fake_appinsights.logged_events = []

    def log_event(message, extra=None, level=None, debug_only=False):
        fake_appinsights.logged_events.append({
            'message': message,
            'extra': extra,
            'level': level,
            'debug_only': debug_only
        })

    fake_appinsights.log_event = log_event

    fake_debug = types.ModuleType('functions_debug')
    fake_debug.debug_messages = []

    def debug_print(*args, **kwargs):
        fake_debug.debug_messages.append({'args': args, 'kwargs': kwargs})

    fake_debug.debug_print = debug_print

    module_spec = importlib.util.spec_from_file_location(MODULE_NAME, MODULE_PATH)
    module = importlib.util.module_from_spec(module_spec)

    original_modules = {
        'config': sys.modules.get('config'),
        'functions_appinsights': sys.modules.get('functions_appinsights'),
        'functions_debug': sys.modules.get('functions_debug')
    }

    sys.modules['config'] = fake_config
    sys.modules['functions_appinsights'] = fake_appinsights
    sys.modules['functions_debug'] = fake_debug

    try:
        module_spec.loader.exec_module(module)
    finally:
        for name, original_module in original_modules.items():
            if original_module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original_module

    return module


def assert_true(condition, message):
    if not condition:
        raise AssertionError(message)


def test_authenticated_request_login_is_throttled():
    print('🔍 Testing throttled authenticated-request login activity...')
    fake_container = FakeContainer()
    activity_logging = load_functions_activity_logging(fake_container)
    fake_session = FakeSession()

    first_emit = activity_logging.maybe_log_authenticated_request_login(
        user_id='user-123',
        session_state=fake_session,
        request_path='/profile',
        request_method='GET',
        now_epoch=2000
    )
    second_emit = activity_logging.maybe_log_authenticated_request_login(
        user_id='user-123',
        session_state=fake_session,
        request_path='/profile',
        request_method='GET',
        now_epoch=2005
    )
    third_emit = activity_logging.maybe_log_authenticated_request_login(
        user_id='user-123',
        session_state=fake_session,
        request_path='/profile',
        request_method='GET',
        now_epoch=2000 + activity_logging.USER_LOGIN_ACTIVITY_MIN_INTERVAL_SECONDS + 1
    )

    assert_true(first_emit is True, 'First authenticated GET should emit a login activity record.')
    assert_true(second_emit is False, 'Second authenticated GET inside the throttle window should not emit a record.')
    assert_true(third_emit is True, 'Authenticated GET after the throttle window should emit a new record.')
    assert_true(len(fake_container.items) == 2, 'Expected exactly two login activity records after throttle validation.')

    first_record = fake_container.items[0]
    assert_true(first_record.get('activity_type') == 'user_login', 'Authenticated request should reuse the user_login activity type.')
    assert_true(first_record.get('login_method') == 'authenticated_request', 'Authenticated request should record the authenticated_request login method.')
    assert_true(first_record.get('auth_signal') == 'authenticated_request', 'Authenticated request should capture the auth signal on the activity record.')
    assert_true(first_record.get('request_path') == '/profile', 'Authenticated request should capture the request path on the activity record.')


def test_callback_login_marks_session_to_avoid_duplicate_redirect_logging():
    print('🔍 Testing callback-login dedup on immediate redirect...')
    fake_container = FakeContainer()
    activity_logging = load_functions_activity_logging(fake_container)
    fake_session = FakeSession()

    activity_logging.log_user_login('user-123', 'azure_ad')
    activity_logging.record_user_login_session_activity(fake_session, now_epoch=3000)

    emitted = activity_logging.maybe_log_authenticated_request_login(
        user_id='user-123',
        session_state=fake_session,
        request_path='/',
        request_method='GET',
        now_epoch=3005
    )

    assert_true(emitted is False, 'Immediate browser redirect after explicit login should not create a duplicate login record.')
    assert_true(len(fake_container.items) == 1, 'Explicit callback login should remain a single record after immediate redirect.')
    assert_true(fake_container.items[0].get('login_method') == 'azure_ad', 'Explicit callback login should preserve the azure_ad login method.')


def test_non_get_requests_do_not_emit_login_activity():
    print('🔍 Testing non-GET request exclusion...')
    fake_container = FakeContainer()
    activity_logging = load_functions_activity_logging(fake_container)
    fake_session = FakeSession()

    emitted = activity_logging.maybe_log_authenticated_request_login(
        user_id='user-123',
        session_state=fake_session,
        request_path='/profile',
        request_method='POST',
        now_epoch=4000
    )

    assert_true(emitted is False, 'Non-GET authenticated requests should not be counted as login activity.')
    assert_true(len(fake_container.items) == 0, 'Non-GET authenticated requests should not create login activity records.')


if __name__ == '__main__':
    tests = [
        test_authenticated_request_login_is_throttled,
        test_callback_login_marks_session_to_avoid_duplicate_redirect_logging,
        test_non_get_requests_do_not_emit_login_activity
    ]

    failures = 0
    for test in tests:
        try:
            test()
            print(f'✅ {test.__name__} passed')
        except Exception as exc:
            failures += 1
            print(f'❌ {test.__name__} failed: {exc}')

    if failures:
        sys.exit(1)

    print('✅ All authenticated request login activity tests passed')