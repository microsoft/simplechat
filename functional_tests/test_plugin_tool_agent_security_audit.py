# test_plugin_tool_agent_security_audit.py
#!/usr/bin/env python3
"""
Functional test for plugin, tool, and agent security audit fixes.
Version: 0.242.068
Implemented in: 0.242.055

This test ensures plugin invocation records and OpenAPI diagnostics redact
secret-bearing values before browser/model-visible serialization, and that
SimpleChat group scope fallback uses the shared active-group validator.
"""

import ast
import importlib
import os
import re
import sys
import types
import traceback
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from typing import Any


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(ROOT_DIR, 'application', 'single_app')
CONFIG_FILE = os.path.join(APP_DIR, 'config.py')
OPENAPI_PLUGIN_FILE = os.path.join(APP_DIR, 'semantic_kernel_plugins', 'openapi_plugin.py')
SIMPLECHAT_OPERATIONS_FILE = os.path.join(APP_DIR, 'functions_simplechat_operations.py')

sys.path.insert(0, APP_DIR)


def read_file_text(file_path):
    with open(file_path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def read_config_version():
    for line in read_file_text(CONFIG_FILE).splitlines():
        if line.strip().startswith('VERSION = '):
            return line.split('=', 1)[1].strip().strip('"')
    raise AssertionError('VERSION assignment not found in config.py')


def install_plugin_logger_import_stubs():
    sys.modules['functions_appinsights'] = types.SimpleNamespace(
        log_event=lambda *args, **kwargs: None,
        get_appinsights_logger=lambda: None,
    )
    sys.modules['functions_authentication'] = types.SimpleNamespace(
        get_current_user_id=lambda: 'user-123',
    )
    sys.modules['functions_debug'] = types.SimpleNamespace(
        debug_print=lambda *args, **kwargs: None,
    )


def load_openapi_redaction_helpers():
    source = read_file_text(OPENAPI_PLUGIN_FILE)
    parsed = ast.parse(source, filename=OPENAPI_PLUGIN_FILE)
    selected_nodes = []
    selected_names = {
        'OPENAPI_REDACTED_VALUE',
        'OPENAPI_SENSITIVE_KEY_NAMES',
        'OPENAPI_SENSITIVE_KEY_FRAGMENTS',
        'OPENAPI_SECRET_ASSIGNMENT_RE',
        'OPENAPI_AUTHORIZATION_VALUE_RE',
        '_normalize_openapi_sensitive_key',
        '_is_openapi_sensitive_key',
        '_redact_openapi_url',
        '_redact_openapi_string',
        '_redact_openapi_value',
    }
    for node in parsed.body:
        if isinstance(node, ast.Assign):
            target_names = [target.id for target in node.targets if isinstance(target, ast.Name)]
            if any(target_name in selected_names for target_name in target_names):
                selected_nodes.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in selected_names:
            selected_nodes.append(node)

    namespace = {
        'Any': Any,
        're': re,
        'parse_qsl': parse_qsl,
        'urlencode': urlencode,
        'urlsplit': urlsplit,
        'urlunsplit': urlunsplit,
    }
    module = ast.Module(body=selected_nodes, type_ignores=[])
    exec(compile(module, OPENAPI_PLUGIN_FILE, 'exec'), namespace)
    return namespace


def extract_function_source(source_text, function_name):
    parsed = ast.parse(source_text)
    for node in ast.walk(parsed):
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return ast.get_source_segment(source_text, node)
    raise AssertionError(f'Function {function_name} not found')


def assert_no_secret_text(payload, secret_values):
    serialized = repr(payload)
    for secret_value in secret_values:
        assert secret_value not in serialized, f'Secret value leaked: {secret_value}'


def test_plugin_invocation_safe_serialization_redacts_secrets():
    print('Testing plugin invocation safe serialization redacts secrets...')

    install_plugin_logger_import_stubs()
    logger_module = importlib.import_module('semantic_kernel_plugins.plugin_invocation_logger')

    invocation = logger_module.PluginInvocation(
        plugin_name='OpenApiPlugin',
        function_name='call_operation',
        parameters={
            'url': 'https://api.example.test/items?api_key=query-secret&tenant=contoso',
            'headers': {
                'Authorization': 'Bearer bearer-secret',
                'X-API-Key': 'header-secret',
                'Accept': 'application/json',
            },
            'body': {
                'client_secret': 'client-secret-value',
                'message': 'safe text',
            },
        },
        result={
            'nextLink': 'https://api.example.test/next?token=result-token&skip=10',
            'status': 'ok',
        },
        start_time=1.0,
        end_time=2.0,
        duration_ms=1000.0,
        user_id='user-123',
        timestamp='2026-06-17T00:00:00',
        success=True,
        conversation_id='conversation-123',
        invocation_id='invocation-123',
        error_message='Authorization: Bearer error-secret',
    )

    safe_payload = invocation.to_safe_dict()

    assert safe_payload['parameters']['headers']['Authorization'] == logger_module.REDACTED_INVOCATION_VALUE
    assert safe_payload['parameters']['headers']['X-API-Key'] == logger_module.REDACTED_INVOCATION_VALUE
    assert safe_payload['parameters']['body']['client_secret'] == logger_module.REDACTED_INVOCATION_VALUE
    assert 'api_key=***REDACTED***' in safe_payload['parameters']['url']
    assert 'token=***REDACTED***' in safe_payload['result']['nextLink']
    assert 'Bearer ***REDACTED***' in safe_payload['error_message']
    assert_no_secret_text(
        safe_payload,
        {
            'query-secret',
            'bearer-secret',
            'header-secret',
            'client-secret-value',
            'result-token',
            'error-secret',
        },
    )


def test_openapi_redaction_helpers_redact_diagnostics():
    print('Testing OpenAPI redaction helpers redact diagnostics...')

    helpers = load_openapi_redaction_helpers()
    redact_value = helpers['_redact_openapi_value']
    redact_url = helpers['_redact_openapi_url']

    redacted_url = redact_url(
        'https://user:password-secret@api.example.test/path?subscription-key=sub-secret&filter=name'
    )
    assert 'password-secret' not in redacted_url
    assert 'sub-secret' not in redacted_url
    assert 'subscription-key=***REDACTED***' in redacted_url
    assert 'filter=name' in redacted_url

    redacted_payload = redact_value({
        'headers': {
            'Authorization': 'Bearer openapi-bearer-secret',
            'Content-Type': 'application/json',
        },
        'query': {
            'api_key': 'openapi-query-secret',
            'category': 'news',
        },
        'message': 'token=openapi-token-secret',
    })
    assert redacted_payload['headers']['Authorization'] == helpers['OPENAPI_REDACTED_VALUE']
    assert redacted_payload['query']['api_key'] == helpers['OPENAPI_REDACTED_VALUE']
    assert redacted_payload['query']['category'] == 'news'
    assert 'token=***REDACTED***' in redacted_payload['message']
    assert_no_secret_text(
        redacted_payload,
        {
            'openapi-bearer-secret',
            'openapi-query-secret',
            'openapi-token-secret',
        },
    )


def test_simplechat_active_group_fallback_uses_authorized_helper():
    print('Testing SimpleChat active group fallback uses require_active_group...')

    source = read_file_text(SIMPLECHAT_OPERATIONS_FILE)
    function_source = extract_function_source(source, '_resolve_group_doc_for_current_user')
    assert 'require_active_group(' in function_source
    assert 'activeGroupOid' not in function_source
    assert 'get_user_settings' not in function_source


def main():
    expected_version = '0.242.068'
    actual_version = read_config_version()
    assert actual_version == expected_version, f'Expected version {expected_version}, found {actual_version}'

    tests = [
        test_plugin_invocation_safe_serialization_redacts_secrets,
        test_openapi_redaction_helpers_redact_diagnostics,
        test_simplechat_active_group_fallback_uses_authorized_helper,
    ]
    results = []
    for test in tests:
        try:
            test()
            print(f'PASS {test.__name__}')
            results.append(True)
        except Exception as exc:
            print(f'FAIL {test.__name__}: {exc}')
            traceback.print_exc()
            results.append(False)

    passed = sum(1 for result in results if result)
    print(f'Results: {passed}/{len(results)} tests passed')
    return all(results)


if __name__ == '__main__':
    sys.exit(0 if main() else 1)