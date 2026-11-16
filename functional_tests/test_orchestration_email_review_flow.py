# test_orchestration_email_review_flow.py
"""Durable outgoing references and current review cards in headless publication.

Version: 0.261.324
Implemented in: 0.261.324
The real headless owner, checkpoint and finalization run with offline cloud I/O.
Producer bridge/effect coverage lives in test_orchestration_operation_runtime.py.
"""

import importlib
import sys
from copy import deepcopy
from pathlib import Path

import pytest

# Production modules are imported by the shared harness before its offline fixture.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'application' / 'single_app'))
from test_orchestration_harness_execution import harness, initialized_application
from test_support.orchestration_harness_execution import decoded_frames, input_binding


def producer_event(record):
    m365 = importlib.import_module('functions_orchestration_m365')
    return {
        'type': 'm365_pending_action_reference', 'run_id': record['id'],
        'step_id': 'prepare', 'user_message_id': record['user_message_id'],
        'reference': {
            'id': 'saved-action', 'user_id': record['user_id'],
            'conversation_id': record['conversation_id'],
            'request_id': m365.step_request_id(f"{record['id']}\x00prepare"),
        },
    }


@pytest.mark.parametrize('later_failure', [False, True])
@pytest.mark.parametrize('disconnect', [False, True])
def test_new_action_survives_finalization_and_later_failure(harness, monkeypatch, later_failure, disconnect):
    cards = importlib.import_module('functions_msgraph_pending_actions')
    current = {'id': 'saved-action', 'status': 'pending', 'summary': {'subject': 'Prepared email'}}
    reads = []

    def resolve(user_id, conversation_id, **kwargs):
        reads.append((user_id, conversation_id, kwargs))
        return [deepcopy(current)]

    monkeypatch.setattr(cards, 'get_chat_pending_action_cards', resolve)
    harness.create(replies=[], final_response=input_binding('prepare'))
    execution = harness.prepare()
    record = harness.read()
    event = producer_event(record)

    def reply():
        execution._progress(event)
        execution._progress(event)
        current['status'] = 'review_required'
        if later_failure:
            raise RuntimeError('PRIVATE_LATER_MODEL_FAILURE')
        return 'Ready to review — not sent.'

    harness.replies.append(reply)
    progress = []

    def receive(frame):
        progress.append(frame)
        if disconnect:
            raise ConnectionError('PRIVATE_UI_DISCONNECT')

    frames = execution.execute(emit=receive)
    done = decoded_frames(frames)[-1]
    saved = harness.read()
    message = harness.assistant_messages()[0]
    assert saved['m365_pending_action_ids'] == ['saved-action']
    assert message['metadata']['m365_pending_action_ids'] == ['saved-action']
    assert done['metadata']['m365_pending_action_ids'] == ['saved-action']
    assert done['m365_pending_actions'][0]['status'] == 'review_required'
    assert done['message_saved'] and len(harness.assistant_messages()) == 1
    assert done['status'] == ('failed' if later_failure else 'completed')
    assert all(user == record['user_id'] and conversation == record['conversation_id']
               for user, conversation, _kwargs in reads)
    assert 'PRIVATE_' not in str(done)
    if not disconnect:
        live = [frame for frame in decoded_frames(progress) if frame.get('type') == 'm365_pending_action']
        assert live[0]['pending_action']['status'] == 'pending'
        assert live[0]['user_message_id'] == record['user_message_id']
        assert live[0]['request_id'] == event['reference']['request_id']


@pytest.mark.parametrize('field,value', [
    ('user_id', 'foreign-owner'), ('conversation_id', 'foreign-conversation'),
    ('request_id', 'foreign-request'),
])
def test_foreign_reference_cannot_be_attached(harness, monkeypatch, field, value):
    harness.create(replies=['Prepared answer.'], final_response=input_binding('prepare'))
    execution = harness.prepare()
    event = producer_event(harness.read())
    event['reference'][field] = value
    execution._progress(event)
    execution.execute()
    assert not harness.read().get('m365_pending_action_ids')
    assert 'm365_pending_action_ids' not in harness.assistant_messages()[0]['metadata']


def test_refresh_failure_retains_minimal_durable_link_without_retrying_effect(harness, monkeypatch):
    cards = importlib.import_module('functions_msgraph_pending_actions')

    def unavailable(*args, **kwargs):
        raise ConnectionError('PRIVATE_COSMOS_QUERY')

    monkeypatch.setattr(cards, 'get_chat_pending_action_cards', unavailable)
    harness.create(replies=['Prepared answer.'], final_response=input_binding('prepare'))
    execution = harness.prepare()
    execution._progress(producer_event(harness.read()))
    frames = execution.execute()
    done = decoded_frames(frames)[-1]
    assert done['status'] == 'completed' and done['message_saved']
    assert done['metadata']['m365_pending_action_ids'] == ['saved-action']
    assert done['m365_pending_actions_error']['error'] == 'm365_pending_actions_unavailable'
    assert 'PRIVATE_' not in str(done)
