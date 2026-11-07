# test_chat_retry_edit_model_endpoint_replay.py
#!/usr/bin/env python3
"""
Functional test for retry and edit model endpoint replay.
Version: 0.261.419
Implemented in: 0.261.033

This test ensures retry and edit requests preserve the model endpoint identity
used by the original streamed response instead of falling back to the default
Azure OpenAI resource with only a model or display name. The integration uses
the current real, catalog-authorized replay owner rather than restoring the
superseded route-local helper.
"""

from pathlib import Path

import pytest

from test_chat_retry_request_contract import replay  # noqa: F401


ROOT_DIR = Path(__file__).resolve().parents[1]
RETRY_JS_FILE = ROOT_DIR / 'application' / 'single_app' / 'static' / 'js' / 'chat' / 'chat-retry.js'
MODELS = [
    {
        'deployment_name': 'resolved-azure-deployment', 'model_id': 'model-luna',
        'endpoint_id': 'endpoint-luna', 'provider': 'aoai',
    },
    {'deployment_name': 'legacy-deployment'},
    {
        'deployment_name': 'new-request-model', 'model_id': 'new-model',
        'endpoint_id': 'new-endpoint', 'provider': 'openai',
    },
]


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


def test_edit_replays_original_model_endpoint_identity(replay):
    replayed_context = replay.resolve_replay_selection(
        build_original_metadata(), {}, models=MODELS, agents=[],
    )

    assert replayed_context == {
        'model_deployment': 'resolved-azure-deployment',
        'model_id': 'model-luna',
        'model_endpoint_id': 'endpoint-luna',
        'model_provider': 'aoai',
    }


def test_retry_selection_preserves_or_replaces_endpoint_identity(replay):
    original_metadata = build_original_metadata()

    same_model_context = replay.resolve_replay_selection(
        original_metadata,
        {'model': 'resolved-azure-deployment', 'model_endpoint_id': 'endpoint-luna', 'model_id': 'model-luna'},
        models=MODELS, agents=[],
    )
    assert same_model_context['model_endpoint_id'] == 'endpoint-luna'
    assert same_model_context['model_id'] == 'model-luna'

    changed_model_context = replay.resolve_replay_selection(
        original_metadata, {'model': 'legacy-deployment'}, models=MODELS, agents=[],
    )
    assert changed_model_context['model_deployment'] == 'legacy-deployment'
    assert not {'model_endpoint_id', 'model_id', 'model_provider'}.intersection(changed_model_context)

    explicit_context = replay.resolve_replay_selection(original_metadata, {
        'model': 'new-request-model',
        'model_id': 'new-model',
        'model_endpoint_id': 'new-endpoint',
        'model_provider': 'openai',
    }, models=MODELS, agents=[])
    assert explicit_context['model_deployment'] == 'new-request-model'
    assert explicit_context['model_id'] == 'new-model'
    assert explicit_context['model_endpoint_id'] == 'new-endpoint'
    assert explicit_context['model_provider'] == 'openai'


def test_missing_original_endpoint_does_not_fall_back_to_another_resource(replay):
    with pytest.raises(replay.ChatRetryError) as error:
        replay.resolve_replay_selection(build_original_metadata(), {}, models=MODELS[1:], agents=[])
    assert error.value.code == 'retry_model_unavailable'


def test_retry_frontend_sends_complete_model_identity():
    retry_source = RETRY_JS_FILE.read_text(encoding='utf-8')

    assert 'selectedOption?.dataset?.requestModel' in retry_source
    assert 'requestBody.model_id = selectedOption?.dataset?.modelId || null;' in retry_source
    assert 'requestBody.model_endpoint_id = selectedOption?.dataset?.endpointId || null;' in retry_source
    assert 'requestBody.model_provider = selectedOption?.dataset?.provider || null;' in retry_source
    assert "requestBody.model_icon = JSON.parse(selectedOption?.dataset?.modelIcon || '{}');" in retry_source


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-q']))