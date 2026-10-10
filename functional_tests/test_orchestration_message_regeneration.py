# test_orchestration_message_regeneration.py
"""
Functional coverage for fresh, review-required orchestration message generations.
Version: 0.261.320
Implemented in: 0.261.317

The real planning, revision, execution, and retry state machines run against the
existing offline HTTP harness. Only storage, catalog, and provider boundaries are
replaced; no Azure or model service is called.
"""

from copy import deepcopy
import importlib
import json
from types import SimpleNamespace
import uuid

import pytest

from test_orchestration_harness_routes import modules as harness_modules, real_http_harness  # noqa: F401
from test_orchestration_elicitation_routes import reply_payload, resolution, style_question
from test_orchestration_model_selection import TERRA_SELECTION
from test_support.offline_bootstrap import offline_app_imports
from test_support.orchestration_harness_execution import compose_step, input_binding


QUESTION = 'Write a short original explanation.'


@pytest.fixture(scope='module')
def modules():
    with offline_app_imports():
        importlib.import_module('route_backend_chats')
    environment = harness_modules.__wrapped__()
    try:
        yield next(environment)
    finally:
        with pytest.raises(StopIteration):
            next(environment)


def frames(response):
    return [
        json.loads(frame.partition('data:')[2].strip())
        for frame in response.get_data(as_text=True).split('\n\n')
        if frame.startswith('data:') and frame.partition('data:')[2].strip() != '[DONE]'
    ]

def planning_replies(*, answered=False):
    return ([json.dumps(resolution(QUESTION))] if answered else []) + [
        json.dumps({'kind': 'plan', 'steps': [compose_step()], 'final_response': input_binding('prepare')}),
    ]


@pytest.fixture
def context(real_http_harness, modules, monkeypatch):
    harness = real_http_harness.harness
    harness.settings['enable_user_workspace'] = False
    harness.conversations.create_item({'id': 'conv1', 'user_id': 'owner'})
    case = SimpleNamespace(
        harness=harness, client=real_http_harness.client, route=modules.route,
        settings=harness.settings, messages=harness.messages, runs=harness.runs,
        conversations=harness.conversations, model=SimpleNamespace(calls=harness.model_calls),
    )
    conversations = importlib.import_module('route_backend_conversations')
    monkeypatch.setattr(modules.auth, 'get_user_profile_image', lambda: None)
    monkeypatch.setattr(conversations, 'get_user_settings', lambda *args, **kwargs: {'settings': {}})
    monkeypatch.setattr(conversations, 'build_chat_model_catalog', lambda **kwargs: [{
        'deployment_name': 'gpt-4o', 'provider': 'aoai',
    }])
    monkeypatch.setattr(conversations, 'get_user_groups', lambda *args: [])
    monkeypatch.setattr(conversations, 'ensure_governance_access', lambda *args, **kwargs: None)
    query = case.messages.query_items

    def bounded_query(query, parameters=None, **kwargs):
        rows = original_query(query, parameters=parameters, **kwargs)
        params = {item['name']: item['value'] for item in parameters or []}
        if '@message_id' in params:
            rows = [row for row in rows if row['id'] == params['@message_id']]
        if '@thread_id' in params:
            rows = [
                row for row in rows
                if (row.get('metadata') or {}).get('thread_info', {}).get('thread_id') == params['@thread_id']
            ]
        if "c.role = 'user'" in query:
            rows = [row for row in rows if row.get('role') == 'user']
        anchor = params.get('@anchor')
        if anchor:
            rows = [
                row for row in rows
                if row.get('timestamp', '') < anchor
                or (row.get('metadata') or {}).get('thread_info', {}).get('root_timestamp', anchor) < anchor
            ]
        return rows

    original_query = query
    monkeypatch.setattr(case.messages, 'query_items', bounded_query)
    return case


def source_run(context, *, execute=True, **selection):
    if not selection:
        selection = {'model_deployment': 'gpt-4o'}
    context.harness.replies = planning_replies()
    response = context.client.post('/api/v2/orchestration/plan', json={
        'conversation_id': 'conv1', 'turn_id': 'source-turn',
        'message': QUESTION, 'approval_mode': 'manual', **selection,
    }, buffered=True)
    events = frames(response)
    assert response.status_code == 200 and not any(event.get('error') for event in events), events
    plan = next(event['plan'] for event in events if event.get('plan'))
    if execute:
        context.harness.replies = ['The original complete answer.']
        response = context.client.post('/api/v2/orchestration/run', json={
            'conversation_id': 'conv1', 'run_id': plan['run_id'], 'plan_id': plan['plan_id'],
        }, buffered=True)
        events = frames(response)
        assert not any(event.get('error') for event in events), events
    return context.runs.read_item(plan['run_id'], 'conv1')


def prepare(context, source, *, submission_id=None, **fields):
    response = context.client.post(
        f"/api/v2/orchestration/messages/{source}/regenerate",
        json={'submission_id': submission_id or str(uuid.uuid4()), **fields},
    )
    return response, response.get_json()


def plan_again(context, prepared, **overrides):
    context.harness.replies = planning_replies(answered=bool(
        prepared['user_message']['metadata'].get('orchestration_clarification_answers'),
    ))
    response = context.client.post(
        '/api/v2/orchestration/plan', json={**prepared['plan_request'], **overrides}, buffered=True,
    )
    return response, frames(response)


def test_deleted_answer_regenerates_from_surviving_owned_question(context):
    original = source_run(context)
    context.messages.delete_item(
        original['assistant_message_id'], 'conv1',
        etag=context.messages.read_item(original['assistant_message_id'], 'conv1')['_etag'],
    )
    response, prepared = prepare(context, original['user_message_id'])
    assert response.status_code == 200, prepared
    assert prepared['turn_id'] != original['turn_id']
    assert prepared['new_attempt'] == 2
    assert prepared['user_message']['content'] == original['user_message']
    response, events = plan_again(context, prepared)
    assert response.status_code == 200, events
    assert not any(event.get('error') for event in events), events
    plan = next(event['plan'] for event in events if event.get('plan'))
    assert plan['run_id'] != original['run_id']
    saved = context.runs.read_item(plan['run_id'], 'conv1')
    assert saved['regeneration_of_run_id'] == original['run_id']
    assert 'retry_of_run_id' not in saved
    assert 'execution_lease' not in saved
    assert not saved.get('started_at')
    assert saved['user_message_id'] == prepared['user_message_id']
    assert saved['requires_fresh_review'] is True
    assert saved['status'] == 'awaiting_approval'
    assert context.messages.read_item(prepared['user_message_id'], 'conv1')['metadata']['response_attempt']['state'] == 'awaiting_review'


def test_regeneration_forces_review_despite_auto_and_disabled_approval_override(context):
    original = source_run(context)
    context.settings.update({
        'chat_orchestration_approval_mode': 'auto',
        'chat_orchestration_allow_user_approval_override': False,
    })
    response, prepared = prepare(context, original['assistant_message_id'])
    assert response.status_code == 200, prepared
    _, events = plan_again(context, prepared, approval_mode='auto')
    plan = next(event['plan'] for event in events if event.get('plan'))
    assert plan['approval']['mode'] == 'manual'
    assert plan['approval']['state'] == 'pending'
    assert plan['status'] == 'awaiting_approval'
    refused = context.client.post('/api/v2/orchestration/run', json={
        'conversation_id': 'conv1', 'run_id': plan['run_id'], 'plan_id': plan['plan_id'],
    })
    assert refused.status_code == 409, refused.get_data(as_text=True)
    assert refused.get_json()['code'] == 'fresh_review_required'
    context.harness.replies = ['The regenerated complete answer.']
    approved = context.client.post('/api/v2/orchestration/run', json={
        'conversation_id': 'conv1', 'run_id': plan['run_id'], 'plan_id': plan['plan_id'],
        'reviewed_regeneration': True,
    }, buffered=True)
    events = frames(approved)
    assert not any(event.get('error') for event in events), events
    saved = context.runs.read_item(plan['run_id'], 'conv1')
    answer = context.messages.read_item(saved['assistant_message_id'], 'conv1')
    assert answer['metadata']['thread_info']['thread_attempt'] == 2
    assert answer['metadata']['thread_info']['thread_id'] == prepared['thread_id']
    assert context.messages.read_item(prepared['user_message_id'], 'conv1')['metadata']['response_attempt']['state'] == 'completed'


def test_duplicate_preparation_and_invocation_cannot_create_extra_generations(context):
    original = source_run(context)
    submission = str(uuid.uuid4())
    first_response, first = prepare(context, original['user_message_id'], submission_id=submission)
    second_response, second = prepare(context, original['user_message_id'], submission_id=submission)
    assert first_response.status_code == second_response.status_code == 200
    assert second['user_message_id'] == first['user_message_id']
    assert second['new_attempt'] == first['new_attempt'] == 2
    _, events = plan_again(context, first)
    assert not any(event.get('error') for event in events), events
    calls = len(context.model.calls)
    refused, _ = plan_again(context, first)
    assert refused.status_code == 409
    assert refused.get_json()['code'] == 'retry_already_submitted'
    assert len(context.model.calls) == calls
    assert context.messages.read_item(first['user_message_id'], 'conv1')['metadata']['response_attempt']['state'] == 'awaiting_review'


@pytest.mark.parametrize('status', ['running', 'waiting'])
def test_active_execution_cannot_be_regenerated(context, status):
    original = source_run(context, execute=False)
    context.runs.upsert_item({**original, 'status': status, 'started_at': '2026-01-01T00:00:00Z'})
    before = len(context.model.calls)
    response, payload = prepare(context, original['user_message_id'])
    assert response.status_code == 409
    assert payload['code'] == 'orchestration_regeneration_busy'
    assert len(context.model.calls) == before
    question = context.messages.read_item(original['user_message_id'], 'conv1')
    assert 'thread_info' not in question['metadata']


def test_running_recovery_descendant_is_not_competed_with(context):
    original = source_run(context)
    child = {
        **original, 'id': 'current-recovery', 'run_id': 'current-recovery',
        'retry_of_run_id': original['run_id'], 'status': 'running',
    }
    context.runs.upsert_item(child)
    context.runs.upsert_item({**original, 'latest_attempt_run_id': child['run_id']})
    response, payload = prepare(context, original['assistant_message_id'])
    assert response.status_code == 409
    assert payload['code'] == 'orchestration_regeneration_busy'


def test_later_turns_and_old_execution_outputs_are_not_planning_context(context):
    original = source_run(context)
    for role in ('user', 'assistant'):
        context.messages.upsert_item({
            'id': f'later-{role}', 'conversation_id': 'conv1', 'role': role,
            'content': 'LATER TURN MUST NOT APPEAR', 'timestamp': '2999-01-01T00:00:00Z', 'metadata': {},
        })
    response, prepared = prepare(context, original['user_message_id'])
    assert response.status_code == 200, prepared
    before = len(context.model.calls)
    _, events = plan_again(context, prepared)
    assert not any(event.get('error') for event in events), events
    plan = next(event['plan'] for event in events if event.get('plan'))
    saved = context.runs.read_item(plan['run_id'], 'conv1')
    ids = {row['id'] for row in saved['conversation_context']['messages']}
    assert original['user_message_id'] not in ids
    assert original['assistant_message_id'] not in ids
    assert not ids.intersection({'later-user', 'later-assistant'})
    assert saved['conversation_context']['logical_order'] is True
    request_text = json.dumps(context.model.calls[before:])
    assert 'LATER TURN MUST NOT APPEAR' not in request_text
    assert not saved['result_aliases']


def test_saved_auto_routing_drops_planners_resolved_pinned_identity(context):
    original = source_run(context, execute=False)
    original['seeds'].update({'model_routing': 'auto', 'model': deepcopy(TERRA_SELECTION)})
    body = context.route._regeneration_request(original)
    seeds = context.route.resolve_seeds(body)
    assert seeds['model_routing'] == 'auto'
    assert not seeds.get('model')
    assert 'model_endpoint_id' not in body


def test_changed_inputs_are_refused_before_planning(context):
    original = source_run(context)
    response, prepared = prepare(context, original['user_message_id'])
    assert response.status_code == 200, prepared
    changed = context.runs.read_item(original['run_id'], 'conv1')
    changed['seeds']['tags'] = ['changed-after-preparation']
    context.runs.upsert_item(changed)
    before = len(context.model.calls)
    refused, _ = plan_again(context, prepared)
    assert refused.status_code == 409
    assert refused.get_json()['code'] == 'retry_source_changed'
    assert len(context.model.calls) == before
    question = context.messages.read_item(prepared['user_message_id'], 'conv1')
    assert question['metadata']['response_attempt']['state'] == 'failed'


def test_browser_changes_do_not_replace_saved_planning_inputs(context):
    original = source_run(context)
    response, prepared = prepare(context, original['user_message_id'])
    assert response.status_code == 200, prepared
    _, events = plan_again(
        context, prepared, message='INJECTED WORDING', model_deployment='unavailable',
        model_endpoint_id='unavailable', model_id='unavailable', model_provider='openai',
        approval_mode='auto',
    )
    assert not any(event.get('error') for event in events), events
    plan = next(event['plan'] for event in events if event.get('plan'))
    saved = context.runs.read_item(plan['run_id'], 'conv1')
    assert saved['user_message'] == original['user_message']
    assert saved['seeds']['model']['model_deployment'] == 'gpt-4o'
    assert saved['approval']['mode'] == 'manual'


@pytest.mark.parametrize('change', ['deleted', 'masked', 'foreign'])
def test_unavailable_questions_do_not_reserve_an_attempt(context, change):
    original = source_run(context)
    question = context.messages.read_item(original['user_message_id'], 'conv1')
    if change == 'deleted':
        question['metadata']['is_deleted'] = True
    elif change == 'masked':
        question['metadata']['masked'] = True
    else:
        question['metadata']['user_info'] = {'user_id': 'somebody-else'}
    context.messages.upsert_item(question)
    response, payload = prepare(context, original['user_message_id'])
    assert response.status_code in (403, 404, 409), payload
    assert not context.conversations.read_item('conv1', 'conv1').get('retry_threads')


def test_incomplete_historical_context_returns_deliberate_composer_fallback(context):
    original = source_run(context)
    original.pop('seeds')
    original.pop('original_seeds')
    context.runs.upsert_item(original)
    response, payload = prepare(context, original['user_message_id'])
    assert response.status_code == 409
    assert payload['code'] == 'orchestration_regeneration_context_unavailable'
    assert 'composer' in payload['error']


def test_logical_snapshot_can_be_revalidated_after_an_earlier_turn_was_retried(context):
    rows = [
        {'id': 'first-q', 'role': 'user', 'content': 'first', 'timestamp': '2026-01-01T00:00:01Z', 'metadata': {}},
        {'id': 'third-q', 'role': 'user', 'content': 'third', 'timestamp': '2026-01-01T00:00:03Z', 'metadata': {}},
        {
            'id': 'second-retry', 'role': 'user', 'content': 'second',
            'timestamp': '2026-01-01T00:00:08Z',
            'metadata': {'retried': True, 'thread_info': {'thread_id': 'second', 'root_timestamp': '2026-01-01T00:00:02Z'}},
        },
    ]
    snapshot = context.route.build_conversation_snapshot(rows, logical_order=True)
    validated = context.route.validate_conversation_snapshot(snapshot, rows)
    assert [row['id'] for row in validated['messages']] == ['first-q', 'second-retry', 'third-q']


def test_lost_preparation_response_and_reloaded_prepared_question_reuse_one_attempt(context):
    original = source_run(context)
    _, first = prepare(context, original['user_message_id'])
    response, recovered = prepare(context, original['user_message_id'])
    assert response.status_code == 200, recovered
    assert recovered['user_message_id'] == first['user_message_id']
    response, restored = prepare(context, first['user_message_id'])
    assert response.status_code == 200, restored
    assert restored['plan_request'] == first['plan_request']
    assert restored['available_attempts'] == [1, 2]
    _, events = plan_again(context, restored)
    assert not any(event.get('error') for event in events), events


def test_failed_planning_without_a_run_remains_retryable_from_saved_inputs(context):
    original = source_run(context)
    _, prepared = prepare(context, original['user_message_id'])
    context.harness.replies = []
    failed = context.client.post('/api/v2/orchestration/plan', json=prepared['plan_request'], buffered=True)
    assert any(event.get('error') for event in frames(failed)), frames(failed)
    question = context.messages.read_item(prepared['user_message_id'], 'conv1')
    assert question['metadata']['response_attempt']['state'] == 'failed'
    assert context.route.get_latest_turn_run('conv1', 'owner', prepared['turn_id']) is None
    response, next_attempt = prepare(context, question['id'])
    assert response.status_code == 200, next_attempt
    assert next_attempt['new_attempt'] == 3
    assert next_attempt['plan_request']['message'] == question['content']
    _, events = plan_again(context, next_attempt)
    assert not any(event.get('error') for event in events), events


@pytest.mark.parametrize('failed_continuation', [False, True])
def test_clarification_preserves_answers_and_manual_review(context, failed_continuation):
    original = source_run(context)
    context.settings.update({
        'chat_orchestration_approval_mode': 'auto',
        'chat_orchestration_allow_user_approval_override': False,
    })
    _, prepared = prepare(context, original['user_message_id'])
    context.harness.replies = [json.dumps(style_question())]
    response = context.client.post('/api/v2/orchestration/plan', json=prepared['plan_request'], buffered=True)
    events = frames(response)
    question = next(event['elicitation'] for event in events if event.get('elicitation'))
    context.harness.replies = [] if failed_continuation else planning_replies(answered=True)
    answer = reply_payload(question, turn_id=prepared['turn_id'])
    answer['conversation_id'] = 'conv1'
    answer['approval_mode'] = 'auto'
    response = context.client.post('/api/v2/orchestration/plan', json=answer, buffered=True)
    events = frames(response)
    if failed_continuation:
        assert any(event.get('error') for event in events), events
        response, next_attempt = prepare(context, prepared['user_message_id'])
        assert response.status_code == 200, next_attempt
        _, events = plan_again(context, next_attempt)
    assert not any(event.get('error') for event in events), events
    plan = next(event['plan'] for event in events if event.get('plan'))
    saved = context.runs.read_item(plan['run_id'], 'conv1')
    assert saved['answered_questions'][0]['answer'] == {'style': 'brief'}
    assert plan['approval']['mode'] == 'manual'
    assert saved['requires_fresh_review'] is True


def test_reloaded_prepared_request_refuses_a_new_running_recovery_descendant(context):
    original = source_run(context)
    _, prepared = prepare(context, original['user_message_id'])
    child = {**original, 'id': 'late-recovery', 'run_id': 'late-recovery', 'status': 'waiting'}
    context.runs.upsert_item(child)
    context.runs.upsert_item({**original, 'latest_attempt_run_id': child['run_id']})
    refused, _ = plan_again(context, prepared)
    assert refused.status_code == 409
    assert refused.get_json()['code'] == 'orchestration_regeneration_busy'


def test_deliberate_model_override_replaces_saved_auto_routing(context, monkeypatch):
    original = source_run(context)
    original['seeds']['model_routing'] = 'auto'
    context.runs.upsert_item(original)
    selection = {
        'model_deployment': 'another-model', 'model_endpoint_id': 'another-endpoint',
        'model_id': 'another-id', 'model_provider': 'aoai',
    }
    conversations = importlib.import_module('route_backend_conversations')
    monkeypatch.setattr(conversations, 'build_chat_model_catalog', lambda **kwargs: [{
        'deployment_name': 'another-model', 'endpoint_id': 'another-endpoint',
        'model_id': 'another-id', 'provider': 'aoai',
    }])
    response, prepared = prepare(context, original['user_message_id'], **selection)
    assert response.status_code == 200, prepared
    for key, value in selection.items():
        assert prepared['plan_request'][key] == value
    assert 'model_routing' not in prepared['plan_request']
    assert 'agent_info' not in prepared['plan_request']


def test_image_generation_does_not_bypass_planning_model_authorization(context, monkeypatch):
    original = source_run(context)
    original['seeds']['image_generation'] = True
    context.runs.upsert_item(original)
    conversations = importlib.import_module('route_backend_conversations')
    monkeypatch.setattr(conversations, 'build_chat_model_catalog', lambda **kwargs: [])
    response, payload = prepare(context, original['user_message_id'])
    assert response.status_code == 409, payload
    assert payload['code'] == 'retry_model_unavailable'
    assert not context.conversations.read_item('conv1', 'conv1').get('retry_threads')


@pytest.mark.parametrize('payload', [[], False, 7, {'submission_id': 'not a valid token'}, {'submission_id': True}])
def test_malformed_preparation_does_not_mutate_the_source(context, payload):
    original = source_run(context)
    response = context.client.post(
        f"/api/v2/orchestration/messages/{original['user_message_id']}/regenerate", json=payload,
    )
    assert response.status_code == 400, response.get_json()
    assert not context.conversations.read_item('conv1', 'conv1').get('retry_threads')


@pytest.mark.parametrize('prepared_invocation', [False, True])
def test_regeneration_submission_errors_never_expose_exception_details(context, monkeypatch, prepared_invocation):
    original = source_run(context)
    _, prepared = prepare(context, original['user_message_id'])
    sentinel = 'Traceback: private storage endpoint and credential'

    def refuse(*args, **kwargs):
        raise context.route.SubmissionIdError(sentinel)

    if prepared_invocation:
        monkeypatch.setattr(context.route, '_restore_prepared_regeneration', refuse)
        response = context.client.post('/api/v2/orchestration/plan', json=prepared['plan_request'])
    else:
        monkeypatch.setattr(context.route, 'normalize_submission_id', refuse)
        response, _ = prepare(context, original['user_message_id'])
    assert response.status_code == 400
    assert response.get_json()['code'] == 'invalid_request'
    assert sentinel not in response.get_data(as_text=True)


def test_unsaved_planning_retry_review_floor_cannot_be_overridden_by_auto(context):
    context.settings.update({
        'chat_orchestration_approval_mode': 'auto',
        'chat_orchestration_allow_user_approval_override': False,
    })
    context.harness.replies = planning_replies()
    response = context.client.post('/api/v2/orchestration/plan', json={
        'conversation_id': 'conv1', 'turn_id': 'unsaved-retry', 'message': QUESTION,
        'model_deployment': 'gpt-4o', 'requires_fresh_review': True, 'approval_mode': 'auto',
    }, buffered=True)
    events = frames(response)
    assert not any(event.get('error') for event in events), events
    plan = next(event['plan'] for event in events if event.get('plan'))
    assert plan['approval']['mode'] == 'manual'
    saved = context.runs.read_item(plan['run_id'], 'conv1')
    assert saved['requires_fresh_review'] is True
    assert not saved.get('regeneration_of_run_id')
    refused = context.client.post('/api/v2/orchestration/run', json={
        'conversation_id': 'conv1', 'run_id': plan['run_id'], 'plan_id': plan['plan_id'],
    })
    assert refused.status_code == 409
    assert refused.get_json()['code'] == 'fresh_review_required'
    context.harness.replies = ['The reviewed planning retry answer.']
    approved = context.client.post('/api/v2/orchestration/run', json={
        'conversation_id': 'conv1', 'run_id': plan['run_id'], 'plan_id': plan['plan_id'],
        'reviewed_regeneration': True,
    }, buffered=True)
    events = frames(approved)
    assert approved.status_code == 200 and not any(event.get('error') for event in events), events
    terminal = next(event for event in events if event.get('done'))
    assert terminal['status'] == 'completed', terminal
    assert terminal['full_content'] == 'The reviewed planning retry answer.'
