# test_privacy_logging_telemetry_audit.py
#!/usr/bin/env python3
"""
Functional test for privacy logging and telemetry audit fixes.
Version: 0.242.068
Implemented in: 0.242.058

This test ensures logging, telemetry, and document-processing diagnostics redact
secret-bearing fields and avoid raw agent or uploaded document content in audit
surfaces that are not intended to store full private payloads.
"""

import importlib
import os
import sys
import types
import traceback


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(ROOT_DIR, 'application', 'single_app')
CONFIG_FILE = os.path.join(APP_DIR, 'config.py')
APPINSIGHTS_FILE = os.path.join(APP_DIR, 'functions_appinsights.py')
PLUGIN_LOGGER_FILE = os.path.join(APP_DIR, 'semantic_kernel_plugins', 'plugin_invocation_logger.py')
GROUPCHAT_ORCHESTRATOR_FILE = os.path.join(APP_DIR, 'agent_orchestrator_groupchat.py')
MAGNETIC_ORCHESTRATOR_FILE = os.path.join(APP_DIR, 'agent_orchestrator_magnetic.py')
DOCUMENTS_FILE = os.path.join(APP_DIR, 'functions_documents.py')

sys.path.insert(0, APP_DIR)


def read_file_text(file_path):
    with open(file_path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def read_config_version():
    for line in read_file_text(CONFIG_FILE).splitlines():
        if line.strip().startswith('VERSION = '):
            return line.split('=', 1)[1].strip().strip('"')
    raise AssertionError('VERSION assignment not found in config.py')


def install_appinsights_import_stubs():
    azure_module = types.ModuleType('azure')
    monitor_module = types.ModuleType('azure.monitor')
    opentelemetry_module = types.ModuleType('azure.monitor.opentelemetry')
    opentelemetry_module.configure_azure_monitor = lambda *args, **kwargs: None

    sys.modules['azure'] = azure_module
    sys.modules['azure.monitor'] = monitor_module
    sys.modules['azure.monitor.opentelemetry'] = opentelemetry_module
    sys.modules['app_settings_cache'] = types.SimpleNamespace(
        get_settings_cache=lambda: {}
    )


def install_plugin_logger_import_stubs():
    install_appinsights_import_stubs()
    sys.modules['functions_authentication'] = types.SimpleNamespace(
        get_current_user_id=lambda: 'user-123'
    )
    sys.modules['functions_debug'] = types.SimpleNamespace(
        debug_print=lambda *args, **kwargs: None
    )


def test_log_event_redaction_helpers_redact_secret_fields():
    print('Testing log_event redaction helpers redact secret fields...')

    install_appinsights_import_stubs()
    appinsights = importlib.import_module('functions_appinsights')

    payload = {
        'Authorization': 'Bearer auth-secret',
        'nested': {
            'api_key': 'api-secret',
            'message': 'token=inline-token-secret status=ok',
        },
        'url': 'https://example.test/path?sig=sas-secret&filter=active',
        'plain': 'safe diagnostic text',
    }
    sanitized = appinsights.sanitize_log_properties(payload)

    assert sanitized['Authorization'] == appinsights.REDACTED_LOG_VALUE
    assert sanitized['nested']['api_key'] == appinsights.REDACTED_LOG_VALUE
    assert 'inline-token-secret' not in repr(sanitized)
    assert 'sas-secret' not in repr(sanitized)
    assert 'filter=active' in sanitized['url']
    assert sanitized['plain'] == 'safe diagnostic text'

    sanitized_message = appinsights.sanitize_log_message(
        'Authorization: Bearer bearer-secret connection_string=connection-secret'
    )
    assert 'bearer-secret' not in sanitized_message
    assert 'connection-secret' not in sanitized_message


def test_plugin_function_logger_uses_parameter_shapes():
    print('Testing plugin function logger avoids raw parameters...')

    source = read_file_text(PLUGIN_LOGGER_FILE)

    assert '"parameters": parameters' not in source
    assert '"param_string": param_str' not in source
    assert 'parameter_shapes' in source
    assert 'parameter_names' in source
    assert 'sanitize_plugin_invocation_value(str(error), max_string_length=500)' in source
    assert 'values_sample' not in source


def test_plugin_result_preview_uses_shape_summary():
    print('Testing plugin result preview uses shape summary...')

    install_plugin_logger_import_stubs()
    logger_module = importlib.import_module('semantic_kernel_plugins.plugin_invocation_logger')

    preview, summary = logger_module._build_plugin_result_logging_payload(
        'OpenApiPlugin',
        'call_operation',
        {
            'message': 'private tool response text',
            'token': 'tool-result-token-secret',
            'status': 'ok',
        }
    )

    assert preview.startswith('<dict> keys=')
    assert summary is None
    assert 'private tool response text' not in preview
    assert 'tool-result-token-secret' not in preview


def test_agent_orchestrators_log_content_lengths_only():
    print('Testing agent orchestrators avoid raw message content telemetry...')

    groupchat_source = read_file_text(GROUPCHAT_ORCHESTRATOR_FILE)
    magnetic_source = read_file_text(MAGNETIC_ORCHESTRATOR_FILE)

    forbidden_patterns = [
        '"content": getattr(message, "content", None)',
        '"content": message.content',
        'raw_message',
        '\\n{message.content}',
        'Reflection summary updated: {summary}',
    ]
    for source in (groupchat_source, magnetic_source):
        for pattern in forbidden_patterns:
            assert pattern not in source, f'Raw content logging pattern remains: {pattern}'
        assert 'content_length' in source


def test_document_processing_logs_avoid_raw_document_text():
    print('Testing document-processing logs avoid raw document text...')

    source = read_file_text(DOCUMENTS_FILE)

    forbidden_patterns = [
        'Document metadata retrieved: {document_items}',
        'page_text_content:{page_text_content}',
        'using json dump of metadata',
        'Content repr: {repr(content)}',
        'First 500 chars: {content[:500]}',
        'Last 100 chars:',
    ]
    for pattern in forbidden_patterns:
        assert pattern not in source, f'Raw document logging pattern remains: {pattern}'

    assert 'text_length:{len(page_text_content or \'\')}' in source
    assert 'metadata fields' in source


def main():
    expected_version = '0.242.068'
    actual_version = read_config_version()
    assert actual_version == expected_version, f'Expected version {expected_version}, found {actual_version}'

    tests = [
        test_log_event_redaction_helpers_redact_secret_fields,
        test_plugin_function_logger_uses_parameter_shapes,
        test_plugin_result_preview_uses_shape_summary,
        test_agent_orchestrators_log_content_lengths_only,
        test_document_processing_logs_avoid_raw_document_text,
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