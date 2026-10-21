# test_orchestration_followup_citation_provenance.py
"""Selected sourced answers retain provenance through formatting-only follow-ups.

Version: 0.261.370
Implemented in: 0.261.370

Real planning routes, retained results, composition and publication run with
offline provider/storage boundaries. No source search is repeated for formatting.
"""

from copy import deepcopy
import importlib
import json

import pytest

from test_orchestration_conversation_context_routes import (
    _compose_only_plan, _planned, _resolution, _run, frames, no_candidate_document_probe,
)
from test_orchestration_harness_routes import modules, real_http_harness
from test_orchestration_reason_render_pipeline import narrative_io
from test_support.orchestration_harness_execution import compose_step, decoded_frames, input_binding


__all__ = ['modules', 'real_http_harness', 'no_candidate_document_probe', 'narrative_io']

REQUEST = 'Reformat that comparison into a concise briefing table. Use our existing notes.'
ANSWER = (
    'The original limit is USD 125,000. (Source: Policy.md, Page: 2) [#document-1_2]\n\n'
    'The revised limit is USD 150,000. (Source: Update.md, Page: 3) [#target-1_3]'
)
TABLE = (
    '| Old | New |\n| --- | --- |\n'
    '| USD 125,000 (Source: Policy.md, Page: 2) [#document-1_2] '
    '| USD 150,000 (Source: Update.md, Page: 3) [#target-1_3] |'
)
HITS = [
    {
        'document_id': 'document-1', 'id': 'document-1_2', 'page_number': 2, 'chunk_sequence': 2,
        'file_name': 'Policy.md', 'chunk_text': 'The original limit is USD 125,000.',
    },
    {
        'document_id': 'target-1', 'id': 'target-1_3', 'page_number': 3, 'chunk_sequence': 3,
        'file_name': 'Update.md', 'chunk_text': 'The revised limit is USD 150,000.',
    },
]


@pytest.fixture
def harness(real_http_harness):
    return real_http_harness.harness


@pytest.fixture
def sourced_conversation(real_http_harness, harness, narrative_io, monkeypatch, request):
    searches = []

    def search(*args, **kwargs):
        searches.append((args, kwargs))
        return deepcopy(HITS)

    monkeypatch.setattr(importlib.import_module('functions_search'), 'hybrid_search', search)
    record = harness.create([
        {
            'step_id': 'search', 'capability_id': 'document_search',
            'arguments': {'query': 'Compare the limits.', 'doc_scope': 'personal',
                          'document_ids': ['document-1', 'target-1']},
        },
        compose_step(inputs={'passages': {'binding': input_binding('search', getattr(request, 'param', 'evidence')),
                                         'allow_partial': False}}),
    ], replies=[ANSWER], final_response=input_binding('prepare'))
    execution = harness.prepare()
    try:
        frames = execution.execute()
    finally:
        execution.close()
    done = decoded_frames(frames)[-1]
    assert done['status'] == 'completed', done
    saved = harness.runs.read_item(record['id'], 'conversation-1')
    message = harness.messages.read_item(saved['assistant_message_id'], 'conversation-1')
    assert len(message['hybrid_citations']) == 2
    return {
        'runtime': real_http_harness, 'record': saved, 'message': message,
        'searches': searches, 'reads': narrative_io['reads'],
    }


def followup_plan(case, *, selected=None, reply=TABLE, turn_id='followup-turn'):
    harness = case['runtime'].harness
    selected = [case['message']['id']] if selected is None else selected
    harness.replies = [
        _resolution(resolved_message=REQUEST, message_ids=selected, requires_retrieval=False),
        _compose_only_plan('Reformat the selected comparison, preserving its references.'),
        reply,
    ]
    return _planned(case['runtime'], REQUEST, turn_id=turn_id)


@pytest.mark.parametrize('selection', ['assistant', 'both'])
@pytest.mark.parametrize('sourced_conversation', ['evidence', 'prepared'], indirect=True)
def test_formatting_binds_selected_final_result_and_publishes_citations(sourced_conversation, selection):
    case = sourced_conversation
    harness = case['runtime'].harness
    selected = [case['message']['id']]
    if selection == 'both':
        selected.insert(0, case['record']['user_message_id'])
    before_reads = len(case['reads'])
    plan = followup_plan(case, selected=selected)
    step = next(step for step in plan['steps'] if step['capability_id'] == 'compose')
    assert step['arguments']['knowledge_basis'] == 'sources'
    assert len(step['inputs']) == 1
    binding = next(iter(step['inputs'].values()))['binding']
    stored = harness.runs.read_item(plan['run_id'], 'conversation-1')
    assert stored['result_aliases'][binding['existing_result']] == case['record']['final_response']
    events = _run(case['runtime'], plan)
    assert not any(event.get('error') for event in events), events
    payload = json.loads(harness.model_calls[-1]['messages'][-1]['content'])
    source = next(iter(payload['inputs'].values()))
    assert source['value'] == ANSWER
    assert {item['citation_id'] for item in source['document_citations']} == {hit['id'] for hit in HITS}
    assert any('copy its citation value verbatim' in m['content'] for m in harness.model_calls[-1]['messages'])
    saved = harness.runs.read_item(plan['run_id'], 'conversation-1')
    message = harness.messages.read_item(saved['assistant_message_id'], 'conversation-1')
    assert saved['status'] == 'completed'
    assert message['content'] == TABLE
    assert {item['citation_id'] for item in message['hybrid_citations']} == {hit['id'] for hit in HITS}
    done = next(event for event in reversed(events) if event.get('hybrid_citations'))
    assert done['hybrid_citations'] == message['hybrid_citations']
    assert len(case['searches']) == 1
    assert not any(kind == 'chunks' for kind, _ in case['reads'][before_reads:])


@pytest.fixture
def followup_message(sourced_conversation):
    case = sourced_conversation
    plan = followup_plan(case)
    events = _run(case['runtime'], plan)
    assert not any(event.get('error') for event in events), events
    harness = case['runtime'].harness
    saved = harness.runs.read_item(plan['run_id'], 'conversation-1')
    return harness.messages.read_item(saved['assistant_message_id'], 'conversation-1')


def test_chained_followup_keeps_original_lineage_without_another_search(sourced_conversation, followup_message):
    case = sourced_conversation
    harness = case['runtime'].harness
    second = {**case, 'message': followup_message}
    plan = followup_plan(second, turn_id='second-followup')
    events = _run(case['runtime'], plan)
    assert not any(event.get('error') for event in events), events
    saved = harness.runs.read_item(plan['run_id'], 'conversation-1')
    message = harness.messages.read_item(saved['assistant_message_id'], 'conversation-1')
    assert len(message['hybrid_citations']) == 2
    assert len(case['searches']) == 1


@pytest.mark.parametrize('selection', ['pasted', 'originating_request'])
def test_user_text_does_not_admit_unselected_answer_sources(sourced_conversation, selection):
    case = sourced_conversation
    harness = case['runtime'].harness
    user = {
        'id': 'pasted-text', 'conversation_id': 'conversation-1', 'role': 'user',
        'content': ANSWER, 'timestamp': '2099-01-01T00:00:00+00:00',
    }
    harness.messages.create_item(user)
    message_id = user['id'] if selection == 'pasted' else case['record']['user_message_id']
    plan = followup_plan(case, selected=[message_id], reply='Reformatted user text.')
    saved = harness.runs.read_item(plan['run_id'], 'conversation-1')
    assert saved['result_aliases'] == {}
    assert plan['steps'][0]['inputs'] == {}
    events = _run(case['runtime'], plan)
    assert not any(event.get('error') for event in events), events
    saved = harness.runs.read_item(plan['run_id'], 'conversation-1')
    message = harness.messages.read_item(saved['assistant_message_id'], 'conversation-1')
    assert message['hybrid_citations'] == []


def test_removed_retained_producer_cannot_be_used_after_planning(sourced_conversation):
    case = sourced_conversation
    harness = case['runtime'].harness
    plan = followup_plan(case)
    before = len(harness.model_calls)
    source = dict(case['record'])
    source['checkpoints_deleted'] = True
    harness.runs.upsert_item(source)
    response = case['runtime'].client.post('/api/v2/orchestration/run', json={
        'conversation_id': 'conversation-1', 'run_id': plan['run_id'],
    }, buffered=True)
    assert response.status_code == 409
    assert len(harness.model_calls) == before


def test_delivery_only_refresh_recovers_followup_provenance_without_execution(sourced_conversation):
    case = sourced_conversation
    harness = case['runtime'].harness
    plan = followup_plan(case)
    harness.run_id = plan['run_id']
    execution = harness.prepare()
    try:
        result = harness.run_engine(execution)
        assert result['status'] == 'completed', result
        record = execution.lease.read()
        services = harness.services()
        before = len(harness.model_calls)
        with harness.publication_only(services):
            frames = harness.execution.refresh_harness_delivery(
                record, services=services, settings=harness.settings, lease=execution.lease,
            )
        done = decoded_frames(frames)[-1]
        assert done['status'] == 'completed', done
        assert done['full_content'] == TABLE
        assert {item['citation_id'] for item in done['hybrid_citations']} == {hit['id'] for hit in HITS}
        assert len(harness.model_calls) == before
        assert len(case['searches']) == 1
    finally:
        execution.close()


def test_plan_editor_replanning_preserves_selected_answer_association(sourced_conversation):
    case = sourced_conversation
    runtime = case['runtime']
    harness = runtime.harness
    plan = followup_plan(case)
    response = runtime.client.post(f"/api/v2/orchestration/runs/{plan['run_id']}/edit", json={
        'conversation_id': 'conversation-1', 'plan_id': plan['plan_id'],
    })
    assert response.status_code == 200, response.get_data(as_text=True)
    editor = response.get_json()['editor']
    revised = json.loads(_compose_only_plan('Reformat the selected answer into a shorter table.'))
    revised['revised_request'] = REQUEST
    harness.replies = [json.dumps(revised)]
    response = runtime.client.post(f"/api/v2/orchestration/runs/{plan['run_id']}/revisions", json={
        'conversation_id': 'conversation-1', 'expected_version': editor['version'],
        'submission_id': 'followup-edit-1', 'action': 'ask', 'edits': editor['edits'],
        'instruction': 'Make the table shorter without new retrieval.',
    }, buffered=True)
    events = frames(response)
    assert response.status_code == 200, events
    assert not any(event.get('error') for event in events), events
    revised_editor = next(event['editor'] for event in events if event.get('editor'))
    step = next(step for step in revised_editor['plan']['steps'] if step['capability_id'] == 'compose')
    assert len(step['inputs']) == 1
    assert step['arguments']['knowledge_basis'] == 'sources'
    assert len(case['searches']) == 1


def test_changed_historical_answer_cannot_reintroduce_its_original_text(sourced_conversation):
    case = sourced_conversation
    harness = case['runtime'].harness
    changed = dict(case['message'])
    changed['content'] = 'Edited source-free summary.'
    harness.messages.upsert_item(changed)
    plan = followup_plan(case, reply='Reformatted edited summary.')
    step = next(step for step in plan['steps'] if step['capability_id'] == 'compose')
    assert step['inputs'] == {}
    events = _run(case['runtime'], plan)
    assert not any(event.get('error') for event in events), events
    prompt = json.dumps(harness.model_calls[-1]['messages'])
    assert 'Edited source-free summary.' in prompt
    assert 'The original limit is USD 125,000.' not in prompt
    saved = harness.runs.read_item(plan['run_id'], 'conversation-1')
    message = harness.messages.read_item(saved['assistant_message_id'], 'conversation-1')
    assert message['hybrid_citations'] == []


def test_edit_after_planning_prevents_execution_of_retained_source(sourced_conversation):
    case = sourced_conversation
    harness = case['runtime'].harness
    plan = followup_plan(case)
    before = len(harness.model_calls)
    changed = dict(case['message'])
    changed['metadata'] = {**changed['metadata'], 'masked': True}
    harness.messages.upsert_item(changed)
    response = case['runtime'].client.post('/api/v2/orchestration/run', json={
        'conversation_id': 'conversation-1', 'run_id': plan['run_id'],
    }, buffered=True)
    assert response.status_code == 409
    assert len(harness.model_calls) == before
