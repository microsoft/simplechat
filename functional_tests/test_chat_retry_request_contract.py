# test_chat_retry_request_contract.py
"""
Functional regression coverage for canonical chat retry inputs.
Version: 0.261.319
Implemented in: 0.261.317

Real replay helpers run with external bootstrap I/O blocked. These checks protect
endpoint identity, agent-wins routing, saved options, and explicit overrides.
"""

from copy import deepcopy
import importlib
from pathlib import Path
import sys

import pytest

from test_support.offline_bootstrap import offline_app_imports


APP_ROOT = Path(__file__).resolve().parents[1] / 'application' / 'single_app'
MODELS = [
    {'deployment_name': 'shared-model', 'model_id': 'model-a', 'endpoint_id': 'endpoint-a', 'provider': 'aoai'},
    {'deployment_name': 'shared-model', 'model_id': 'model-b', 'endpoint_id': 'endpoint-b', 'provider': 'aoai'},
]
AGENTS = [
    {'id': 'agent-a', 'name': 'research', 'display_name': 'Research', 'is_global': True, 'is_group': False},
    {'id': 'agent-b', 'name': 'research', 'display_name': 'Personal research', 'is_global': False, 'is_group': False},
]
DOCUMENT_CONTEXT = {
    'document_context_requested': True, 'hybrid_search': False,
    'selection_mode': 'selected', 'selected_document_ids': ['document-a'],
    'doc_scope': 'user', 'tags': ['finance'], 'document_filter_mode': 'union',
}


@pytest.fixture(scope='module')
def replay():
    with offline_app_imports():
        original_path = list(sys.path)
        sys.path.insert(0, str(APP_ROOT))
        try:
            module = importlib.import_module('functions_chat_retry')
            yield module
        finally:
            sys.path[:] = original_path


def source():
    return {
        'id': 'question-2', 'conversation_id': 'conversation', 'role': 'user',
        'content': 'What is the capital of Germany?',
        'metadata': {
            'model_selection': {
                'selected_model': 'shared-model', 'model_id': 'model-b',
                'model_endpoint_id': 'endpoint-b', 'model_provider': 'aoai',
                'reasoning_effort': 'medium',
            },
            'button_states': {'web_search': True, 'url_access': False, 'deep_research': False},
            'thread_info': {'thread_id': 'thread', 'thread_attempt': 2, 'active_thread': True},
        },
    }


def prepare(replay, question, overrides=None, models=None, agents=None):
    return replay.build_replay_request(
        question, overrides or {}, document_context=DOCUMENT_CONTEXT,
        models=MODELS if models is None else models, agents=AGENTS if agents is None else agents,
    )


def test_retry_restores_complete_identity_and_saved_options(replay):
    question = source()
    original = deepcopy(question)
    result = prepare(replay, question)
    assert {key: result[key] for key in replay.MODEL_FIELDS} == {
        'model_deployment': 'shared-model', 'model_id': 'model-b',
        'model_endpoint_id': 'endpoint-b', 'model_provider': 'aoai',
    }
    assert result['message'] == 'What is the capital of Germany?'
    assert result['reasoning_effort'] == 'medium'
    assert result['web_search_enabled'] is True
    assert result['url_access_enabled'] is False
    assert result['selected_document_ids'] == ['document-a']
    assert result['document_filter_mode'] == 'union'
    assert result['tags'] == ['finance']
    assert question == original


def test_retry_restores_requested_not_adjusted_reasoning(replay):
    question = source()
    question['metadata'].update({'requested_reasoning_effort': 'high', 'reasoning_effort': 'low'})
    result = prepare(replay, question)
    assert result['reasoning_effort'] == 'high'
    result = prepare(replay, question, {'reasoning_effort': None})
    assert 'reasoning_effort' not in result


def test_saved_agent_metadata_becomes_an_exclusive_agent_request(replay):
    question = source()
    question['metadata']['agent_selection'] = {
        'agent_id': 'agent-a', 'selected_agent': 'research',
        'agent_display_name': 'Old label', 'is_global': True, 'is_group': False,
    }
    result = prepare(replay, question)
    assert result['agent_info']['id'] == 'agent-a'
    assert result['agent_info']['name'] == 'research'
    assert result['agent_info']['display_name'] == 'Research'
    assert result['agent_info']['is_global'] is True
    assert not set(replay.MODEL_FIELDS).intersection(result)
    assert 'reasoning_effort' not in result


def test_explicit_model_override_can_replace_an_agent_without_losing_endpoint(replay):
    question = source()
    question['metadata']['agent_selection'] = {
        'agent_id': 'agent-a', 'selected_agent': 'research', 'is_global': True,
    }
    result = prepare(replay, question, {
        'model_deployment': 'shared-model', 'model_id': 'model-a',
        'model_endpoint_id': 'endpoint-a', 'model_provider': 'aoai',
    })
    assert result['model_endpoint_id'] == 'endpoint-a'
    assert result['model_id'] == 'model-a'
    assert 'agent_info' not in result


def test_legacy_provider_is_not_mistaken_for_endpoint_identity(replay):
    question = source()
    question['metadata']['model_selection'] = {'selected_model': 'legacy', 'model_provider': 'aoai'}
    result = prepare(replay, question, models=[{'deployment_name': 'legacy'}])
    assert result['model_deployment'] == 'legacy'
    assert 'model_endpoint_id' not in result
    assert 'model_provider' not in result


def test_empty_legacy_agent_metadata_does_not_turn_a_model_response_into_an_agent(replay):
    question = source()
    question['metadata']['agent_selection'] = {
        'selected_agent': None, 'agent_id': None, 'is_global': False, 'is_group': False,
    }
    result = prepare(replay, question)
    assert result['model_endpoint_id'] == 'endpoint-b'
    assert 'agent_info' not in result


@pytest.mark.parametrize('scope', ['global', 'personal', 'group'])
def test_agent_identity_and_scope_must_both_match(replay, scope):
    question = source()
    agent = {
        'id': 'same-id', 'name': 'same-name', 'is_global': scope == 'global',
        'is_group': scope == 'group', 'group_id': 'group-a' if scope == 'group' else None,
    }
    question['metadata']['agent_selection'] = {
        **agent, 'agent_id': agent['id'], 'selected_agent': agent['name'],
    }
    result = prepare(replay, question, agents=[agent, {**agent, 'id': 'different-id'}])
    assert result['agent_info']['id'] == 'same-id'
    assert result['agent_info'].get('group_id') == agent['group_id']


@pytest.mark.parametrize('kind', ['model', 'agent'])
def test_unavailable_original_selection_is_not_replaced(replay, kind):
    question = source()
    if kind == 'agent':
        question['metadata']['agent_selection'] = {
            'agent_id': 'removed-agent', 'selected_agent': 'research', 'is_global': True,
        }
    with pytest.raises(replay.ChatRetryError) as error:
        prepare(replay, question, models=[], agents=AGENTS)
    assert error.value.code == f'retry_{kind}_unavailable'


def test_ambiguous_deployment_only_override_requires_an_explicit_endpoint(replay):
    with pytest.raises(replay.ChatRetryError) as error:
        prepare(replay, source(), {'model': 'shared-model'})
    assert error.value.code == 'retry_model_unavailable'


def test_agent_id_never_falls_back_to_another_agent_with_the_same_name(replay):
    question = source()
    question['metadata']['agent_selection'] = {
        'agent_id': 'removed', 'selected_agent': 'research', 'is_global': True,
    }
    with pytest.raises(replay.ChatRetryError):
        prepare(replay, question)


def test_masked_question_is_not_replayed(replay):
    question = source()
    question['metadata']['masked_ranges'] = [{'start': 0, 'end': 5}]
    with pytest.raises(replay.ChatRetryError) as error:
        prepare(replay, question)
    assert error.value.code == 'retry_message_masked'


def test_new_metadata_contains_inputs_not_previous_execution_approvals(replay):
    question = source()
    question['metadata'].update({
        'm365_approval': {'approved': True}, 'execution_receipt': {'id': 'old'},
        'orchestration': {'run_id': 'old'}, 'saved_analysis': {'id': 'old'},
        'response_attempt': {'state': 'failed'}, 'is_deleted': False,
    })
    request_body = prepare(replay, question)
    result = replay.build_replay_metadata(question['metadata'], request_body)
    assert result['model_selection']['model_endpoint_id'] == 'endpoint-b'
    assert result['button_states']['web_search'] is True
    assert not {'m365_approval', 'execution_receipt', 'orchestration', 'saved_analysis', 'response_attempt', 'is_deleted'}.intersection(result)


if __name__ == '__main__':
    raise SystemExit(pytest.main([str(Path(__file__).resolve()), '-q']))
