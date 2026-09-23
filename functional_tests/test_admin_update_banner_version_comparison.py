# test_admin_update_banner_version_comparison.py
"""
Functional coverage for shared classic/V2 admin release status.
Version: 0.261.126
Implemented in: 0.261.126

Execute the production checker, parser and comparator with HTTP/storage boundaries
mocked. AST loading avoids initializing Azure clients; these are behavior tests,
not startup/import-cycle tests. No live network or application settings are used.
"""

import ast
from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
import re
import types
import unittest
from unittest.mock import Mock

from bs4 import BeautifulSoup
import requests


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'application' / 'single_app'
NOW = datetime(2026, 9, 21, 12, tzinfo=timezone.utc)
CURRENT = '0.261.126'


class FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW


class UpdateStatusTests(unittest.TestCase):
    def setUp(self):
        source = ast.parse((APP / 'functions_settings.py').read_text(encoding='utf-8'))
        names = {
            'get_application_update_status', 'compare_versions',
            'extract_latest_version_from_html',
        }
        nodes = [node for node in source.body if isinstance(node, ast.FunctionDef) and node.name in names]
        self.settings = {}
        self.get = Mock(return_value=types.SimpleNamespace(
            status_code=200,
            text='<a href="/microsoft/simplechat/releases/tag/v0.261.127">Release</a>',
        ))
        self.save = Mock(side_effect=self.persist)
        self.log = Mock()
        self.namespace = {
            'datetime': FrozenDatetime, 'timezone': timezone, 're': re,
            'logging': logging, 'BeautifulSoup': BeautifulSoup, 'log_event': self.log,
            'requests': types.SimpleNamespace(get=self.get, RequestException=requests.RequestException),
            'update_settings': self.save, 'AIConnectionError': type('AIConnectionError', (Exception,), {}),
        }
        exec(compile(ast.Module(body=nodes, type_ignores=[]), 'functions_settings.py', 'exec'), self.namespace)
        self.check = self.namespace['get_application_update_status']

    def persist(self, updates):
        self.settings.update(updates)
        return True

    def cached(self, version='0.261.127', age=3600, **extra):
        self.settings.update({
            'latest_version_available': version,
            'last_update_check_time': (NOW - timedelta(seconds=age)).isoformat(),
            **extra,
        })

    def test_numeric_comparison_ignores_stale_boolean(self):
        for version, expected in (
            ('0.261.125', False), (CURRENT, False), ('0.261.127', True),
            ('v0.261.127', True), ('V00.0261.00127', True), ('0.261.9', False),
            ('0.262.001', True),
        ):
            with self.subTest(version=version):
                self.cached(version, update_available=not expected)
                result = self.check(self.settings, CURRENT)
                self.assertEqual(result['update_available'], expected)
                self.assertEqual(result['status'], 'checked')
                self.assertEqual(result['latest_version'], version.lstrip('vV'))
        self.get.assert_not_called()
        self.save.assert_not_called()

    def test_first_check_shared_by_subsequent_admin_visit(self):
        first = self.check(self.settings, CURRENT)
        second = self.check(dict(self.settings), CURRENT)
        self.assertEqual(first, second)
        self.assertTrue(first['update_available'])
        self.get.assert_called_once_with('https://github.com/microsoft/simplechat/releases', timeout=3)
        self.save.assert_called_once()

    def test_cache_boundary(self):
        for age, calls in ((86399, 0), (86400, 1), (86401, 1)):
            with self.subTest(age=age):
                self.settings.clear()
                self.get.reset_mock()
                self.cached(age=age)
                result = self.check(self.settings, CURRENT)
                self.assertEqual(self.get.call_count, calls)
                self.assertEqual(result['status'], 'checked')

    def test_invalid_timestamps_and_versions_refresh(self):
        for value in (None, '', 'broken', 123, '2026-09-21T11:00:00', (NOW + timedelta(days=1)).isoformat()):
            with self.subTest(timestamp=value):
                self.settings.clear()
                self.cached(last_update_check_time=value)
                self.get.reset_mock()
                result = self.check(self.settings, CURRENT)
                self.get.assert_called_once()
                self.assertEqual(result['status'], 'checked')
        for value in (None, {}, 123, 'not-a-version'):
            with self.subTest(version=value):
                self.settings.clear()
                self.cached(version=value)
                self.get.reset_mock()
                result = self.check(self.settings, CURRENT)
                self.get.assert_called_once()
                self.assertEqual(result['latest_version'], '0.261.127')

    def test_timeout_retains_stale_result_and_throttles_failure(self):
        self.cached(age=90000)
        previous_success = self.settings['last_update_check_time']
        self.get.side_effect = requests.Timeout('sensitive provider details')
        first = self.check(self.settings, CURRENT)
        second = self.check(self.settings, CURRENT)
        self.assertEqual(first, second)
        self.assertEqual(first['status'], 'stale')
        self.assertEqual(first['checked_at'], previous_success)
        self.assertTrue(first['update_available'])
        self.assertNotIn('sensitive', first['error'])
        self.get.assert_called_once()
        self.log.assert_called()

    def test_no_result_http_and_parse_failures_are_unavailable(self):
        for status, text in ((503, 'Unavailable'), (200, ''), (200, '<a href="/releases/tag/vbad">bad</a>')):
            with self.subTest(status=status, text=text):
                self.settings.clear()
                self.get.return_value = types.SimpleNamespace(status_code=status, text=text)
                result = self.check(self.settings, CURRENT)
                self.assertEqual(result['status'], 'unavailable')
                self.assertIsNone(result['latest_version'])
                self.assertIsNone(result['checked_at'])
                self.assertFalse(result['update_available'])
                self.assertTrue(result['error'])

    def test_failed_attempt_retried_after_expiry(self):
        self.settings.update({
            'last_update_check_failed': True,
            'last_update_check_attempt_time': (NOW - timedelta(days=1)).isoformat(),
        })
        result = self.check(self.settings, CURRENT)
        self.assertEqual(result['status'], 'checked')
        self.assertFalse(self.settings['last_update_check_failed'])

    def test_cache_write_failure_visible_without_breaking_settings(self):
        for failure in (False, self.namespace['AIConnectionError']()):
            with self.subTest(failure=failure):
                self.settings.clear()
                self.save.side_effect = failure if isinstance(failure, Exception) else None
                self.save.return_value = False
                result = self.check(self.settings, CURRENT)
                self.assertEqual(result['status'], 'stale')
                self.assertIn('cache', result['error'])
                self.assertEqual(result['latest_version'], '0.261.127')

    def test_parser_preserves_highest_numeric_release_selection(self):
        self.get.return_value.text = (
            '<a href="/microsoft/simplechat/releases/tag/v0.261.9">Older</a>'
            '<a href="/microsoft/simplechat/releases/tag/v0.261.128">Newer</a>'
            '<a href="/microsoft/simplechat/releases/tag/v0.262.0-beta">Prerelease</a>'
        )
        result = self.check(self.settings, CURRENT)
        self.assertEqual(result['latest_version'], '0.261.128')

    def test_v2_get_returns_separate_status_and_preserves_redaction(self):
        tree = ast.parse((APP / 'route_backend_v2.py').read_text(encoding='utf-8'))
        route = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == 'v2_admin_get_settings')
        decorators = [ast.unparse(node) for node in route.decorator_list]
        self.assertIn('admin_required', decorators)
        self.assertIn('login_required', decorators)
        self.assertIn('swagger_route(security=get_auth_security())', decorators)
        route.decorator_list = []
        namespace = {
            'get_settings': lambda: self.settings,
            'get_application_update_status': self.check,
            'VERSION': CURRENT, 'ADMIN_NAV': [], 'jsonify': lambda value: value,
            '_redact_admin_settings_for_v2': lambda settings: {'secret': 'REDACTED'},
            'get_admin_settings_fields': dict, 'get_admin_section_status': dict,
            'get_app_role_requirements': list, '_build_branding_assets': lambda settings: {},
            '_build_status_readouts': dict, '_build_endpoint_readouts': lambda settings: {},
            '_build_model_catalog': lambda settings: [], 'is_mcp_ui_enabled': lambda: False,
            'get_suppressed_capability_keys': list, 'logging': logging, 'log_event': self.log,
        }
        exec(compile(ast.Module(body=[route], type_ignores=[]), 'route_backend_v2.py', 'exec'), namespace)
        payload, code = namespace['v2_admin_get_settings']()
        self.assertEqual(code, 200)
        self.assertEqual(payload['version'], CURRENT)
        self.assertEqual(payload['settings'], {'secret': 'REDACTED'})
        self.assertEqual(payload['update_status']['status'], 'checked')
        self.get.side_effect = requests.Timeout()
        self.settings.clear()
        payload, code = namespace['v2_admin_get_settings']()
        self.assertEqual(code, 200)
        self.assertEqual(payload['update_status']['status'], 'unavailable')

    def test_classic_route_uses_shared_status(self):
        source = (APP / 'route_frontend_admin_settings.py').read_text(encoding='utf-8')
        self.assertIn('update_status = get_application_update_status(settings, current_version)', source)
        self.assertIn("update_available = update_status['update_available']", source)
        self.assertIn('update_status=update_status', source)


if __name__ == '__main__':
    unittest.main()
