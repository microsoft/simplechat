# test_chat_retry_edit_model_endpoint_replay.py
#!/usr/bin/env python3
"""
Functional test for retry and edit model endpoint replay.
Version: 0.261.033
Implemented in: 0.261.033

This test ensures retry and edit requests preserve the model endpoint identity
used by the original streamed response instead of falling back to the default
Azure OpenAI resource with only a model or display name.
"""

import ast
import os


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONVERSATION_ROUTE_FILE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'route_backend_conversations.py',
)
RETRY_JS_FILE = os.path.join(
    ROOT_DIR,
    'application',
    'single_app',
    'static',
    'js',
    'chat',
    'chat-retry.js',
)


def read_file_text(file_path):
    with open(file_path, 'r', encoding='utf-8') as file_handle:
        return file_handle.read()


def load_replayed_model_context_builder():
    route_source = read_file_text(CONVERSATION_ROUTE_FILE)
    route_tree = ast.parse(route_source, filename=CONVERSATION_ROUTE_FILE)
    helper_node = next(
        node
        for node in route_tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == '_build_replayed_model_context'
    )
    helper_module = ast.Module(body=[helper_node], type_ignores=[])
    helper_namespace = {}
    exec(compile(helper_module, CONVERSATION_ROUTE_FILE, 'exec'), helper_namespace)
    return helper_namespace['_build_replayed_model_context']


def build_original_metadata():
    return {
        'model_selection': {
            'frontend_requested_model': 'gpt-5.6-luna',
            'selected_model': 'resolved-azure-deployment',
            'model_id': 'model-luna',
            'model_endpoint_id': 'endpoint-luna',
            'model_provider': 'aoai',
            'model_icon': {'kind': 'bootstrap', 'value': 'bi-moon'},
        },
    }


def test_edit_replays_original_model_endpoint_identity():
    builder = load_replayed_model_context_builder()

    replayed_context = builder(build_original_metadata())

    assert replayed_context == {
        'model_deployment': 'gpt-5.6-luna',
        'model_id': 'model-luna',
        'model_endpoint_id': 'endpoint-luna',
        'model_provider': 'aoai',
        'model_icon': {'kind': 'bootstrap', 'value': 'bi-moon'},
    }


def test_retry_selection_preserves_or_replaces_endpoint_identity():
    builder = load_replayed_model_context_builder()
    original_metadata = build_original_metadata()

    same_model_context = builder(original_metadata, {'model': 'gpt-5.6-luna'})
    assert same_model_context['model_endpoint_id'] == 'endpoint-luna'
    assert same_model_context['model_id'] == 'model-luna'

    changed_model_context = builder(original_metadata, {'model': 'legacy-deployment'})
    assert changed_model_context['model_deployment'] == 'legacy-deployment'
    assert changed_model_context['model_endpoint_id'] is None
    assert changed_model_context['model_id'] is None
    assert changed_model_context['model_provider'] is None

    explicit_context = builder(original_metadata, {
        'model': 'new-request-model',
        'model_id': 'new-model',
        'model_endpoint_id': 'new-endpoint',
        'model_provider': 'openai',
    })
    assert explicit_context['model_deployment'] == 'new-request-model'
    assert explicit_context['model_id'] == 'new-model'
    assert explicit_context['model_endpoint_id'] == 'new-endpoint'
    assert explicit_context['model_provider'] == 'openai'


def test_retry_frontend_sends_complete_model_identity():
    retry_source = read_file_text(RETRY_JS_FILE)

    assert 'selectedOption?.dataset?.requestModel' in retry_source
    assert 'requestBody.model_id = selectedOption?.dataset?.modelId || null;' in retry_source
    assert 'requestBody.model_endpoint_id = selectedOption?.dataset?.endpointId || null;' in retry_source
    assert 'requestBody.model_provider = selectedOption?.dataset?.provider || null;' in retry_source
    assert "requestBody.model_icon = JSON.parse(selectedOption?.dataset?.modelIcon || '{}');" in retry_source


if __name__ == '__main__':
    tests = [
        test_edit_replays_original_model_endpoint_identity,
        test_retry_selection_preserves_or_replaces_endpoint_identity,
        test_retry_frontend_sends_complete_model_identity,
    ]
    results = []
    for test in tests:
        try:
            test()
            print(f'{test.__name__}: passed')
            results.append(True)
        except Exception as exc:
            print(f'{test.__name__}: failed: {exc}')
            results.append(False)

    raise SystemExit(0 if all(results) else 1)