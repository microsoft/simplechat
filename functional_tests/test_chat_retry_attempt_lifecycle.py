# test_chat_retry_attempt_lifecycle.py
"""
Functional regression coverage for durable chat retry attempts.
Version: 0.261.319
Implemented in: 0.261.317

Real replay, route admission, history, and background-worker functions run with
external I/O blocked. Storage and provider boundaries are in memory.
"""

from contextlib import nullcontext
from copy import deepcopy
import importlib
import inspect
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import uuid

from azure.cosmos.exceptions import CosmosResourceExistsError
from flask import Flask, g, jsonify, request
import pytest

from test_chat_soft_deleted_message_visibility_fix import (
    CONVERSATION, USER, FakeContainer, message, soft_deleted,
)
from test_support.offline_bootstrap import offline_app_imports


APP_ROOT = Path(__file__).resolve().parents[1] / 'application' / 'single_app'
MODEL = {
    'deployment_name': 'shared-model', 'model_id': 'model-b',
    'endpoint_id': 'endpoint-b', 'provider': 'aoai',
}
AGENT = {
    'id': 'agent-a', 'name': 'research', 'display_name': 'Research',
    'is_global': True, 'is_group': False,
}


class AttemptContainer(FakeContainer):
    def __init__(self, items=()):
        super().__init__(items)
        self.after_replace = None

    def create_item(self, body, **kwargs):
        if body['id'] in self.items:
            raise CosmosResourceExistsError(status_code=409, message='Exists')
        return self._store(body)

    def replace_item(self, **kwargs):
        result = super().replace_item(**kwargs)
        if self.after_replace:
            callback, self.after_replace = self.after_replace, None
            callback()
        return result


@pytest.fixture(scope='module')
def modules():
    with offline_app_imports():
        original_path = list(sys.path)
        sys.path.insert(0, str(APP_ROOT))
        try:
            yield SimpleNamespace(
                replay=importlib.import_module('functions_chat_retry'),
                chats=importlib.import_module('route_backend_chats'),
                conversations=importlib.import_module('route_backend_conversations'),
            )
        finally:
            sys.path[:] = original_path


@pytest.fixture
def context(modules, monkeypatch):
    question = message('q1', 'user', 'Original question', '2026-01-01T00:00:03', 'thread')
    question['metadata']['model_selection'] = {
        'selected_model': MODEL['deployment_name'], 'model_id': MODEL['model_id'],
        'model_endpoint_id': MODEL['endpoint_id'], 'model_provider': MODEL['provider'],
    }
    answer = message('a1', 'assistant', 'Original answer', '2026-01-01T00:00:04', 'thread')
    messages = AttemptContainer([question, answer])
    conversations = AttemptContainer([{'id': CONVERSATION, 'user_id': USER}])
    settings = {'enable_multi_model_endpoints': True, 'enable_semantic_kernel': True}
    models = [deepcopy(MODEL)]
    agents = [deepcopy(AGENT)]
    from functions_chat_content_checks import ChatContentDecision

    allowed = ChatContentDecision('chat_input', 'not_required', 'allow', {})
    for module in (modules.chats, modules.conversations):
        monkeypatch.setattr(module, 'cosmos_messages_container', messages)
        monkeypatch.setattr(module, 'cosmos_conversations_container', conversations)
        monkeypatch.setattr(module, 'get_current_user_id', lambda: USER)
        monkeypatch.setattr(module, 'get_settings', lambda *args, **kwargs: settings)
        monkeypatch.setattr(module, 'check_chat_content', lambda *args, **kwargs: allowed)
        monkeypatch.setattr(module, 'log_event', lambda *args, **kwargs: None)
    monkeypatch.setattr(modules.conversations, 'build_chat_model_catalog', lambda **kwargs: models)
    monkeypatch.setattr(modules.conversations, 'build_accessible_agent_catalog', lambda *args, **kwargs: agents)
    monkeypatch.setattr(modules.conversations, 'ensure_governance_access', lambda *args, **kwargs: None)
    monkeypatch.setattr(modules.chats, 'debug_print', lambda *args, **kwargs: None)

    def prepare(*, submission_id=None, source=None, edited=False, content=None):
        source = source or messages.get('q1')
        body = modules.conversations._build_authorized_message_replay_request(USER, source, {}, settings)
        if content is not None:
            body['message'] = content
        return modules.replay.prepare_retry_attempt(
            messages, conversations, USER, source, body,
            submission_id=submission_id or str(uuid.uuid4()), edited=edited,
        )

    app = Flask('retry-attempt-lifecycle')
    app.config['TESTING'] = True
    app.secret_key = 'test-only'
    return SimpleNamespace(
        **vars(modules), messages=messages, store=conversations, settings=settings,
        models=models, agents=agents, prepare=prepare, app=app,
    )


def claim(context, question, **kwargs):
    return context.replay.claim_retry_attempt(
        context.messages, context.store, USER, CONVERSATION, question['id'], **kwargs,
    )


def test_duplicate_preparation_has_one_identity_and_one_carousel_attempt(context):
    submission_id = str(uuid.uuid4())
    first = context.prepare(submission_id=submission_id)
    second = context.prepare(submission_id=submission_id)
    assert second['id'] == first['id']
    assert second['metadata']['thread_info']['thread_attempt'] == 2
    assert len(context.messages.items) == 3
    assert context.messages.get('a1')['metadata']['thread_info']['active_thread'] is False


def test_changed_duplicate_submission_is_rejected(context):
    submission_id = str(uuid.uuid4())
    context.prepare(submission_id=submission_id)
    with pytest.raises(context.replay.ChatRetryError) as failure:
        context.prepare(submission_id=submission_id, content='Different wording', edited=True)
    assert failure.value.code == 'submission_conflict'
    assert len(context.messages.items) == 3


def test_competing_preparation_cannot_start_another_attempt(context):
    first = context.prepare()
    reconciled = context.prepare()
    assert reconciled['id'] == first['id']
    with pytest.raises(context.replay.ChatRetryError) as failure:
        context.prepare(content='Changed selections before invocation')
    assert failure.value.code == 'retry_in_progress'
    claimed = claim(context, first)
    assert claimed['metadata']['response_attempt']['state'] == 'running'
    with pytest.raises(context.replay.ChatRetryError) as failure:
        context.prepare()
    assert failure.value.code == 'retry_in_progress'
    assert len(context.messages.items) == 3


def test_reloaded_prepared_question_reconciles_without_a_new_attempt(context):
    first = context.prepare()
    recovered = context.replay.reconcile_prepared_retry(
        context.messages, context.store, USER, first,
    )
    assert recovered['id'] == first['id']
    assert recovered['metadata']['response_attempt']['state'] == 'prepared'
    assert len(context.messages.items) == 3
    claim(context, recovered)
    with pytest.raises(context.replay.ChatRetryError) as failure:
        context.replay.reconcile_prepared_retry(context.messages, context.store, USER, recovered)
    assert failure.value.code == 'retry_attempt_changed'


def test_hard_deleted_source_cannot_be_reconciled(context):
    prepared = context.prepare()
    context.messages.items.pop('q1')
    with pytest.raises(context.replay.ChatRetryError) as failure:
        context.replay.reconcile_prepared_retry(context.messages, context.store, USER, prepared)
    assert failure.value.code == 'retry_source_changed'


def test_prepared_agent_reauthorization_failure_is_durable(context, monkeypatch):
    source = context.messages.get('q1')
    source['metadata']['agent_selection'] = {
        **AGENT, 'agent_id': AGENT['id'], 'selected_agent': AGENT['name'],
    }
    context.messages.upsert_item(source)
    prepared = context.prepare()

    def refuse(*args, **kwargs):
        raise PermissionError('Access removed')

    monkeypatch.setattr(context.conversations, 'ensure_governance_access', refuse)
    with context.app.test_request_context('/retry', method='POST', json={}):
        response, status = context.conversations._prepare_message_attempt_response(prepared['id'])
    assert status == 403
    assert response.get_json()['code'] == 'forbidden'
    saved = context.messages.get(prepared['id'])['metadata']['response_attempt']
    assert saved['state'] == 'failed'
    assert saved['code'] == 'forbidden'
    assert saved['error'] == response.get_json()['error']
    assert len(context.messages.items) == 3


def test_interleaved_reservation_recovers_the_same_question(context):
    recovered = []
    context.store.after_replace = lambda: recovered.append(context.prepare())
    first = context.prepare()
    assert recovered[0]['id'] == first['id']
    assert len(context.messages.items) == 3
    assert context.messages.get('q1')['metadata']['thread_info']['active_thread'] is False


def test_one_time_claim_and_terminal_status(context):
    question = context.prepare()
    first = claim(context, question, thread_id='thread', thread_attempt=2)
    assert first['metadata']['response_attempt']['state'] == 'running'
    with pytest.raises(context.replay.ChatRetryError) as failure:
        claim(context, question)
    assert failure.value.code == 'retry_already_submitted'
    context.replay.set_retry_attempt_state(context.messages, CONVERSATION, question['id'], 'completed')
    context.replay.set_retry_attempt_state(context.messages, CONVERSATION, question['id'], 'failed', error='Late callback')
    saved = context.messages.get(question['id'])
    assert saved['metadata']['response_attempt']['state'] == 'completed'
    assert 'error' not in saved['metadata']['response_attempt']


@pytest.mark.parametrize('change', ['content', 'mask', 'delete'])
def test_changed_source_cannot_be_consumed(context, change):
    question = context.prepare()
    source = context.messages.get('q1')
    if change == 'content':
        source['content'] = 'Changed after preparation'
    elif change == 'mask':
        source['metadata']['masked'] = True
    else:
        source = soft_deleted(source)
    context.messages.upsert_item(source)
    with pytest.raises(context.replay.ChatRetryError) as failure:
        claim(context, question)
    assert failure.value.code == 'retry_source_changed'


def test_deleted_answer_does_not_remove_the_question_retry(context):
    context.messages.upsert_item(soft_deleted(context.messages.get('a1')))
    question = context.prepare()
    claimed = claim(context, question)
    assert claimed['metadata']['thread_info']['thread_attempt'] == 2
    assert context.messages.get('a1')['metadata']['is_deleted'] is True


def test_history_stops_at_the_retried_logical_turn(context):
    context.messages.upsert_item(message('before', 'user', 'Earlier context', '2026-01-01T00:00:01'))
    context.messages.upsert_item(message('before-answer', 'assistant', 'Earlier answer', '2026-01-01T00:00:02'))
    context.messages.upsert_item(message('later', 'user', 'Later question', '2026-01-01T00:00:05', 'later-thread'))
    context.messages.upsert_item(message('later-answer', 'assistant', 'Later answer', '2026-01-01T00:00:06', 'later-thread'))
    question = context.prepare(edited=True, content='Viewed edited wording')
    rows = list(context.messages.query_items(query='SELECT * FROM c ORDER BY c.timestamp ASC'))
    with context.app.test_request_context():
        result = context.chats.build_conversation_history_segments(
            rows, 50, user_message_id=question['id'], fallback_user_message=question['content'],
            include_assistant_citation_context=False,
        )
    contents = [row['content'] for row in result['history_messages']]
    assert contents == ['Earlier context', 'Earlier answer', 'Viewed edited wording']
    ordered = context.replay.order_retry_messages(rows)
    assert next(index for index, row in enumerate(ordered) if row['id'] == question['id']) < next(
        index for index, row in enumerate(ordered) if row['id'] == 'later'
    )
    assert context.messages.get('later-answer')['content'] == 'Later answer'


@pytest.mark.parametrize('agent', [False, True])
def test_real_invocation_admission_ignores_tampered_browser_selections(context, agent):
    if agent:
        source = context.messages.get('q1')
        source['metadata']['agent_selection'] = {
            'selected_agent': AGENT['name'], 'agent_id': AGENT['id'],
            'agent_display_name': AGENT['display_name'], 'is_global': True, 'is_group': False,
        }
        context.messages.upsert_item(source)
    question = context.prepare()
    calls = []

    @context.chats._with_prepared_chat_retry
    def invoke():
        calls.append(deepcopy(request.get_json()))
        return jsonify({'reply': 'Provider boundary response'})

    context.app.add_url_rule('/invoke', view_func=invoke, methods=['POST'])
    client = context.app.test_client()
    payload = {
        'message': 'Browser changed the question', 'conversation_id': CONVERSATION,
        'retry_user_message_id': question['id'], 'retry_thread_id': 'thread', 'retry_thread_attempt': 2,
        'model_deployment': 'another-model', 'model_endpoint_id': 'another-endpoint',
        'agent_info': {'id': 'another-agent', 'name': 'another-agent'},
    }
    first = client.post('/invoke', json=payload)
    assert first.status_code == 200
    assert calls[0]['message'] == 'Original question'
    if agent:
        assert calls[0]['agent_info']['id'] == AGENT['id']
        assert 'model_endpoint_id' not in calls[0]
        assert 'reasoning_effort' not in calls[0]
    else:
        assert calls[0]['model_endpoint_id'] == MODEL['endpoint_id']
        assert calls[0]['model_id'] == MODEL['model_id']
        assert 'agent_info' not in calls[0]
    duplicate = client.post('/invoke', json=payload)
    assert duplicate.status_code == 409
    assert len(calls) == 1
    assert context.messages.get(question['id'])['metadata']['response_attempt']['state'] == 'completed'


def test_removed_model_fails_the_admitted_attempt_without_provider_work(context):
    question = context.prepare()
    context.models.clear()
    calls = []

    @context.chats._with_prepared_chat_retry
    def invoke():
        calls.append(True)
        return jsonify({'reply': 'Must not be generated'})

    context.app.add_url_rule('/invoke', view_func=invoke, methods=['POST'])
    response = context.app.test_client().post('/invoke', json={
        'conversation_id': CONVERSATION, 'retry_user_message_id': question['id'],
    })
    assert response.status_code == 409
    assert response.get_json()['code'] == 'retry_model_unavailable'
    assert calls == []
    assert context.messages.get(question['id'])['metadata']['response_attempt']['state'] == 'failed'


def test_stale_runtime_metadata_cannot_reactivate_or_regress_an_attempt(context):
    question = context.prepare()
    stale = claim(context, question)
    context.replay.set_retry_attempt_state(context.messages, CONVERSATION, question['id'], 'completed')
    current = context.messages.get(question['id'])
    current['metadata']['thread_info']['active_thread'] = False
    context.messages.upsert_item(current)
    stale['metadata']['capability_usage'] = {'web_search': {'used': True}}
    context.chats._save_chat_user_metadata(stale, True)
    saved = context.messages.get(question['id'])
    assert saved['metadata']['response_attempt']['state'] == 'completed'
    assert saved['metadata']['thread_info']['active_thread'] is False
    assert saved['metadata']['capability_usage']['web_search']['used'] is True


@pytest.mark.parametrize(('payload', 'state'), [
    ({'done': True}, 'completed'),
    ({'error': 'Provider failed', 'error_code': 'provider_failed'}, 'failed'),
    ({'done': True, 'canceled': True}, 'interrupted'),
    ({'error': 'Interrupted response', 'interrupted': True}, 'interrupted'),
    ({'done': True, 'blocked': True}, 'failed'),
])
def test_terminal_events_belong_to_the_actual_attempt(context, payload, state):
    question = context.prepare()
    claimed = claim(context, question)
    result = context.chats._persist_retry_terminal_payload(claimed, payload)
    assert result == state
    assert payload['user_message_id'] == question['id']
    assert payload['retry_thread_attempt'] == 2
    assert context.messages.get(question['id'])['metadata']['response_attempt']['state'] == state


def test_browser_disconnect_does_not_interrupt_background_generation(context, monkeypatch):
    question = context.prepare()
    claimed = claim(context, question)
    monkeypatch.setattr(context.chats, 'login_required', lambda function: function)
    monkeypatch.setattr(context.chats, 'user_required', lambda function: function)
    monkeypatch.setattr(context.chats, 'm365_action_card_events', lambda *args: nullcontext())
    monkeypatch.setattr(context.chats, 'get_request_pending_action_references', lambda: [])
    completions = []
    monkeypatch.setattr(context.chats, 'complete_m365_request', lambda **kwargs: completions.append(kwargs['success']))
    context.chats.register_route_backend_chats(context.app)
    entry = next(view for view in context.app.view_functions.values() if view.__name__ == 'chat_stream_api')
    worker_response = inspect.getclosurevars(inspect.unwrap(entry)).nonlocals['build_background_stream_response']
    jobs = []
    context.app.extensions['executor'] = SimpleNamespace(submit=jobs.append)

    def generate():
        yield f"data: {json.dumps({'done': True, 'full_content': 'Finished after disconnect'})}\n\n"

    with context.app.test_request_context('/api/chat/stream', method='POST', json={}):
        g.chat_retry_question = claimed
        response = worker_response(generate)
        response.close()
        saved = context.messages.get(question['id'])
        assert saved['metadata']['response_attempt']['state'] == 'running'
        jobs[0]()
    assert context.messages.get(question['id'])['metadata']['response_attempt']['state'] == 'completed'
    assert completions == [True]
