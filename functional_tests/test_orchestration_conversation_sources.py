# test_orchestration_conversation_sources.py
"""
Functional regressions for exact conversation-source transformations.
Version: 0.261.341
Implemented in: 0.261.341

Exercises real discovery, resolver, Flask planning and initialized execution with
offline storage/model boundaries. Discovery previews never substitute for full
authorized sources, and no-retrieval resolutions cannot become workspace audits.
"""

import importlib
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from azure.cosmos._cosmos_responses import CosmosDict

from test_orchestration_conversation_context import message
from test_orchestration_conversation_context_routes import (
    _compose_only_plan,
    _new_topic,
    _plan,
    _planned,
    _replace_history,
    _resolution,
    _run,
    _search_then_answer_plan,
    no_candidate_document_probe,  # noqa: F401
)
from test_orchestration_harness_routes import modules, real_http_harness  # noqa: F401
from test_support.orchestration_revisions import AtomicMemoryContainer


REQUEST = 'Rewrite the above content as a concise report without dropping its constraints.'


@pytest.fixture
def context(modules):
    return importlib.import_module('functions_orchestration_context')


def long_sources():
    source = ('BEGIN preserve the owner constraint\n' + 'pasted source material ' * 6000)[:116886]
    middle = 'MIDDLE preserve the authorization constraint\n'
    source = source[:50000] + middle + source[50000 + len(middle):]
    end = 'END preserve the explicitly selected scope.'
    source = source[:-len(end)] + end
    answer = ('Assistant unverified assertions. ' * 1000)[:29192]
    return [message('source', 'user', source, 1), message('answer', 'assistant', answer, 2)]


def transform_resolution():
    return _resolution(
        resolved_message=REQUEST, message_ids=['answer'], requires_retrieval=False,
    )


def verified_model(harness):
    harness.settings['gpt_model']['selected'][0].update({
        'contextWindow': 128000, 'outputTokenLimit': 16384,
        'responseLength': 1024, 'outputTokenAccounting': 'total_generation',
    })


def test_discovery_retains_long_user_source_and_answer_roles_with_provenance(context):
    rows = long_sources()
    assert len(rows[0]['content']) == 116886
    assert len(rows[1]['content']) == 29192
    snapshot = context.build_conversation_snapshot(rows)
    assert context.conversation_snapshot_size(snapshot) <= context.HISTORY_MAX_BYTES
    assert [entry['role'] for entry in snapshot['messages']] == ['user', 'assistant']
    assert [entry['id'] for entry in snapshot['messages']] == ['source', 'answer']
    for entry, original in zip(snapshot['messages'], rows):
        assert entry['content_complete'] is False
        assert entry['source_characters'] == len(original['content'])
        assert entry['source'] == {
            'kind': 'stored_message', 'message_id': entry['id'], 'role': entry['role'],
        }
    validated = context.validate_conversation_snapshot(snapshot, rows)
    exact = context.resolve_conversation_source_messages(validated, rows, ['source', 'answer'])
    assert [entry['content'] for entry in exact] == [entry['content'] for entry in rows]
    assert 'MIDDLE preserve the authorization constraint' in exact[0]['content']
    with pytest.raises(context.ConversationContextError):
        context.execution_conversation_messages(SimpleNamespace(
            conversation_context=snapshot, context_message_ids=['source'],
        ))


def test_long_paste_is_reloaded_exactly_for_composition_not_used_as_a_preview(real_http_harness, monkeypatch):
    runtime = real_http_harness
    harness = runtime.harness
    verified_model(harness)
    rows = long_sources()
    _replace_history(harness, rows)
    harness.replies = [transform_resolution(), _compose_only_plan(), 'Rewritten complete source.']
    plan = _planned(runtime, REQUEST)
    record = harness.runs.read_item(plan['run_id'], 'conversation-1')
    assert record['request_resolution']['message_ids'] == ['source', 'answer']
    assert record['conversation_context']['messages'][0]['content_complete'] is False
    budget = importlib.import_module('functions_workflow_context')
    calculate = budget.calculate_workflow_context_budget
    audits = []

    def capture_budget(*args, **kwargs):
        audit = calculate(*args, **kwargs)
        audits.append(audit)
        return audit

    monkeypatch.setattr(budget, 'calculate_workflow_context_budget', capture_budget)
    events = _run(runtime, plan)
    assert not any(event.get('error') for event in events), events
    composition = harness.model_calls[-1]['messages']
    assert audits and audits[0]['decision'] == 'full_input', json.dumps(audits)
    assert audits[0]['limit_status'] == 'known'
    for row in rows:
        assert any(
            entry['role'] == row['role'] and entry['content'] == row['content']
            for entry in composition
        )
    assert all('Conversation discovery preview' not in entry['content'] for entry in composition)
    assert any('they are not verified evidence' in entry['content'] for entry in composition if entry['role'] == 'system')
    saved = harness.runs.read_item(plan['run_id'], 'conversation-1')
    assert saved['status'] == 'completed'


def test_missing_target_clarifies_without_a_model_or_workspace_fallback(real_http_harness):
    runtime = real_http_harness
    _replace_history(runtime.harness, [])
    events = _plan(runtime, 'Please rewrite that answer.')
    assert not any(event.get('type') == 'orchestration_plan' for event in events), events
    assert any('Which message or text' in json.dumps(event) for event in events), events
    assert runtime.harness.model_calls == []


def test_history_disabled_does_not_restore_pasted_content(real_http_harness):
    runtime = real_http_harness
    _replace_history(runtime.harness, long_sources())
    runtime.harness.settings['conversation_history_limit'] = 0
    events = _plan(runtime, REQUEST)
    assert any('Which message or text' in json.dumps(event) for event in events), events
    assert runtime.harness.model_calls == []


def test_ambiguous_resolver_new_topic_transformation_cannot_search_all_workspaces(real_http_harness):
    runtime = real_http_harness
    _replace_history(runtime.harness, long_sources())
    runtime.harness.replies = [_new_topic(REQUEST)]
    events = _plan(runtime, REQUEST)
    assert any('Which message or text' in json.dumps(event) for event in events), events
    assert len(runtime.harness.model_calls) == 1


def test_no_retrieval_resolution_repairs_inconsistent_workspace_audit_plan(real_http_harness):
    runtime = real_http_harness
    _replace_history(runtime.harness, long_sources())
    runtime.harness.replies = [
        transform_resolution(), _search_then_answer_plan(REQUEST), _compose_only_plan(),
    ]
    plan = _planned(runtime, REQUEST)
    assert [step['capability_id'] for step in plan['steps']] == ['compose']
    planning = runtime.harness.model_calls[1]['messages']
    payload = json.loads(planning[1]['content'])
    assert payload['source_policy'] == 'conversation_only'
    assert 'document_search' not in payload['capability_availability']['available']
    correction = runtime.harness.model_calls[-1]['messages'][-1]['content']
    assert 'not workspace or web retrieval' in correction


def test_repeated_inconsistent_plan_fails_instead_of_broadening_scope(real_http_harness):
    runtime = real_http_harness
    _replace_history(runtime.harness, long_sources())
    runtime.harness.replies = [
        transform_resolution(), _search_then_answer_plan(REQUEST), _search_then_answer_plan(REQUEST),
    ]
    events = _plan(runtime, REQUEST)
    assert any('not a workspace search' in event.get('error', '') for event in events), events
    assert not any(event.get('type') == 'orchestration_plan' for event in events)


def test_explicit_workspace_retrieval_overrides_no_retrieval_resolution(real_http_harness):
    runtime = real_http_harness
    _replace_history(runtime.harness)
    request = 'Search workspace documents for current policies.'
    runtime.harness.replies = [_new_topic(request), _search_then_answer_plan(request)]
    plan = _planned(runtime, request)
    assert [step['capability_id'] for step in plan['steps']] == ['document_search', 'compose']
    payload = json.loads(runtime.harness.model_calls[-1]['messages'][1]['content'])
    assert payload['source_policy'] == 'retrieval_allowed'
    assert payload['request_resolution']['message_ids'] == []


def test_new_topic_has_no_prior_source_in_composition(real_http_harness):
    runtime = real_http_harness
    _replace_history(runtime.harness, long_sources())
    request = 'Explain Python generators.'
    runtime.harness.replies = [_new_topic(request), _compose_only_plan(), 'Generators yield values.']
    plan = _planned(runtime, request)
    events = _run(runtime, plan)
    assert not any(event.get('error') for event in events), events
    encoded = json.dumps(runtime.harness.model_calls[-1]['messages'])
    assert 'pasted source material' not in encoded
    assert 'Assistant unverified assertions' not in encoded


def test_full_source_exceeding_verified_model_budget_is_not_truncated_or_sent(real_http_harness):
    runtime = real_http_harness
    verified_model(runtime.harness)
    _replace_history(runtime.harness, [
        message('source', 'user', 'budget material ' * 150000, 1),
        message('answer', 'assistant', 'An earlier short response.', 2),
    ])
    runtime.harness.replies = [transform_resolution(), _compose_only_plan()]
    plan = _planned(runtime, REQUEST)
    _run(runtime, plan)
    record = runtime.harness.runs.read_item(plan['run_id'], 'conversation-1')
    assert record['status'] == 'failed'
    assert record['failure']['code'] == 'result_input_too_large'
    assert 'larger model or revise the plan' in record['failure']['message']
    assert len(runtime.harness.model_calls) == 2


@pytest.mark.parametrize('mutation', ['changed', 'deleted', 'masked'])
def test_selected_long_source_revision_is_rechecked_before_execution(real_http_harness, mutation):
    runtime = real_http_harness
    _replace_history(runtime.harness, long_sources())
    runtime.harness.replies = [transform_resolution(), _compose_only_plan()]
    plan = _planned(runtime, REQUEST)
    key = ('conversation-1', 'source')
    if mutation == 'deleted':
        del runtime.harness.messages.items[key]
    elif mutation == 'masked':
        runtime.harness.messages.items[key]['metadata'] = {'masked': True}
    else:
        runtime.harness.messages.items[key]['content'] += 'Changed after planning.'
    response = runtime.client.post('/api/v2/orchestration/run', json={
        'conversation_id': 'conversation-1', 'run_id': plan['run_id'],
    }, buffered=True)
    assert response.status_code == 409
    assert 'context' in response.get_json()['error'].lower()
    assert len(runtime.harness.model_calls) == 2


def test_inline_source_does_not_require_history(modules):
    result = modules.route.resolve_conversation_request('Rewrite this: A short sentence.', {'messages': []})
    assert result['relationship'] == 'new_topic'
    assert result['message_ids'] == []


def test_legacy_clipped_snapshot_requires_a_new_plan(context):
    rows = long_sources()
    snapshot = context.build_conversation_snapshot(rows)
    snapshot['schema_version'] = 1
    with pytest.raises(context.ConversationContextError):
        context.validate_conversation_snapshot(snapshot, rows)


def test_complete_legacy_snapshot_preserves_existing_read_and_retry_behavior(context):
    rows = [message('source', 'user', 'Complete supplied text.', 1)]
    legacy = {
        'schema_version': 1, 'messages': [context.normalize_history_message(rows[0])], 'truncated': False,
    }
    validated = context.validate_conversation_snapshot(legacy, rows)
    assert validated == legacy
    exact = context.resolve_conversation_source_messages(validated, rows, ['source'])
    assert exact == [{'id': 'source', 'role': 'user', 'content': 'Complete supplied text.'}]


def test_many_large_turns_evict_whole_turns_only_when_reference_metadata_cannot_fit(context):
    rows = [
        message(f'{index:036d}', 'user' if index % 2 == 0 else 'assistant', '大' * 10000, index)
        for index in range(50)
    ]
    snapshot = context.build_conversation_snapshot(rows, {'conversation_history_limit': 50})
    assert context.conversation_snapshot_size(snapshot) <= context.HISTORY_MAX_BYTES
    assert snapshot['messages'][0]['role'] == 'user'
    assert snapshot['messages'][-2]['id'] == rows[-2]['id']
    assert snapshot['messages'][-1]['id'] == rows[-1]['id']
    context.validate_conversation_snapshot(snapshot, rows)


def test_shared_membership_is_rechecked_before_exact_message_reads(real_http_harness, context, monkeypatch):
    runtime = real_http_harness
    _replace_history(runtime.harness, long_sources())
    runtime.harness.replies = [transform_resolution(), _compose_only_plan()]
    plan = _planned(runtime, REQUEST)
    record = runtime.harness.runs.read_item(plan['run_id'], 'conversation-1')
    collaboration = importlib.import_module('functions_orchestration_collaboration')
    backing = {
        'id': 'conversation-1', 'user_id': 'owner', 'conversation_kind': 'collaboration_source',
        'collaboration_conversation_id': 'conversation-1',
    }
    authorize = Mock(side_effect=PermissionError('Membership was revoked.'))
    monkeypatch.setattr(collaboration, 'shared_conversation', lambda conversation_id: {'id': conversation_id})
    monkeypatch.setattr(collaboration, 'authorize_shared_orchestration', authorize)
    read = Mock(wraps=runtime.harness.messages.read_item)
    monkeypatch.setattr(runtime.harness.messages, 'read_item', read)
    execution = importlib.import_module('functions_orchestration_execution')
    with pytest.raises(context.ConversationContextError):
        execution._conversation_context(
            record, runtime.harness.messages, lambda: backing,
            full_message_ids=['source', 'answer'],
        )
    authorize.assert_called_once_with({'id': 'conversation-1'}, 'owner')
    read.assert_not_called()


def test_no_history_setting_changed_after_planning_blocks_execution(real_http_harness):
    runtime = real_http_harness
    _replace_history(runtime.harness, long_sources())
    runtime.harness.replies = [transform_resolution(), _compose_only_plan()]
    plan = _planned(runtime, REQUEST)
    runtime.harness.settings['conversation_history_limit'] = 0
    response = runtime.client.post('/api/v2/orchestration/run', json={
        'conversation_id': 'conversation-1', 'run_id': plan['run_id'],
    }, buffered=True)
    assert response.status_code == 409
    assert len(runtime.harness.model_calls) == 2


@pytest.mark.parametrize('mutation', ['changed', 'deleted'])
def test_retry_rejects_changed_or_deleted_selected_source(real_http_harness, mutation):
    runtime = real_http_harness
    verified_model(runtime.harness)
    _replace_history(runtime.harness, long_sources())
    runtime.harness.replies = [
        transform_resolution(), _compose_only_plan(), RuntimeError('Synthetic provider failure.'),
    ]
    plan = _planned(runtime, REQUEST)
    _run(runtime, plan)
    record = runtime.harness.runs.read_item(plan['run_id'], 'conversation-1')
    assert record['status'] == 'failed'
    key = ('conversation-1', 'source')
    if mutation == 'changed':
        runtime.harness.messages.items[key]['content'] += 'Changed after failure.'
    else:
        del runtime.harness.messages.items[key]
    response = runtime.client.post(f"/api/v2/orchestration/runs/{plan['run_id']}/retry", json={
        'conversation_id': 'conversation-1', 'expected_version': record['recovery_version'],
        'submission_id': '226f6df6-f2ab-4a95-b6c9-f13380672f18', 'confirm_external_effects': False,
    }, buffered=True)
    assert response.status_code == 409, response.get_json()
    assert response.get_json()['code'] == 'recovery_unavailable'
    assert response.get_json()['error'] == (
        'The original context or access changed. Review the request and create a new plan.'
    )
    assert len(runtime.harness.model_calls) == 3


def test_search_as_a_subject_is_not_an_explicit_workspace_request(modules):
    allowed = modules.route.conversation_retrieval_allowed(
        {'requires_retrieval': False}, 'Rewrite your answer about search indexing.',
    )
    assert allowed is False


def test_sdk_owned_elicitation_conversation_authorizes_current_owner(context, modules, monkeypatch):
    conversations = AtomicMemoryContainer('id')
    conversations.create_item({'id': 'conversation-1', 'user_id': 'owner'})
    monkeypatch.setattr(modules.config, 'cosmos_conversations_container', conversations)
    conversation = context._owned_elicitation_conversation('owner', 'conversation-1')
    assert isinstance(conversation, CosmosDict)
    assert conversation['_etag']
    assert conversation['user_id'] == 'owner'
    with pytest.raises(context.ElicitationContextError):
        context._owned_elicitation_conversation('foreign', 'conversation-1')
    with pytest.raises(context.ElicitationContextError):
        context._owned_elicitation_conversation('owner', 'missing')


def test_sdk_image_reference_candidates_use_partitioned_message_read(context, modules, monkeypatch):
    messages = AtomicMemoryContainer('conversation_id')
    messages.create_item({
        'id': 'conversation-1_image-1', 'conversation_id': 'conversation-1',
        'role': 'image', 'file_name': 'selected.png',
    })
    monkeypatch.setattr(modules.config, 'cosmos_messages_container', messages)
    point = messages.read_item('conversation-1_image-1', 'conversation-1')
    assert isinstance(point, CosmosDict)
    selected = context._image_reference_message_candidates({
        'image_references': [{'type': 'message', 'message_id': 'conversation-1_image-1'}],
    }, 'conversation-1')
    assert selected == [{
        'message_id': 'conversation-1_image-1', 'file_name': 'selected.png',
        'label': 'selected.png', 'workspace_document_id': '',
    }]
    for message_id in ('conversation-2_image-1', 'conversation-1_missing'):
        with pytest.raises(context.CatalogResolutionError):
            context._image_reference_message_candidates({
                'image_references': [{'type': 'message', 'message_id': message_id}],
            }, 'conversation-1')


def test_sdk_chat_attachment_reference_readiness_query(context, modules, monkeypatch):
    conversations = AtomicMemoryContainer('id')
    messages = AtomicMemoryContainer('conversation_id')
    conversations.create_item({'id': 'conversation-1', 'user_id': 'owner'})
    messages.create_item({
        'id': 'attachment-1', 'conversation_id': 'conversation-1',
        'role': 'file', 'file_name': 'source.txt', 'percentage_complete': 100,
    })
    monkeypatch.setattr(modules.config, 'cosmos_conversations_container', conversations)
    monkeypatch.setattr(modules.config, 'cosmos_messages_container', messages)
    source_access = importlib.import_module('functions_mixed_source_orchestration')
    search = importlib.import_module('functions_search_service')
    monkeypatch.setattr(search, 'resolve_document_contexts', lambda *args, **kwargs: [{
        'scope': 'chat', 'document': {'id': 'attachment-1', 'percentage_complete': 100},
    }])
    monkeypatch.setattr(source_access, 'resolve_authorized_source_manifest', lambda *args, **kwargs: [{
        'document_id': 'attachment-1', 'authorization_status': 'authorized',
        'scope': 'chat', 'scope_id': 'conversation-1', 'display_name': 'Stored attachment',
    }])
    reference = {
        'kind': 'chat_attachment', 'id': 'attachment-1',
        'scope': {'kind': 'chat', 'id': 'conversation-1'},
    }
    selected = context.resolve_elicitation_references([reference], 'owner', 'conversation-1')
    assert selected[0]['label'] == 'Stored attachment'
    query, parameters, partition = messages.queries[-1]
    assert partition == 'conversation-1'
    assert 'c.id = @document_id' in query
    assert parameters == [{'name': '@document_id', 'value': 'attachment-1'}]
    rows = messages.query_items(query, parameters=parameters, partition_key=partition)
    assert type(rows[0]) is dict
    messages.items[('conversation-1', 'attachment-1')]['percentage_complete'] = 0
    with pytest.raises(context.ElicitationContextError) as failure:
        context.resolve_elicitation_references([reference], 'owner', 'conversation-1')
    assert failure.value.reason == 'document_not_ready'
    del messages.items[('conversation-1', 'attachment-1')]
    with pytest.raises(context.ElicitationContextError) as failure:
        context.resolve_elicitation_references([reference], 'owner', 'conversation-1')
    assert failure.value.reason == 'document_unavailable'
