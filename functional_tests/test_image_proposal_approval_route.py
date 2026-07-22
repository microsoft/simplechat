#!/usr/bin/env python3
# test_image_proposal_approval_route.py
"""
Functional test for the image proposal approval route.
Version: 0.250.064
Implemented in: 0.250.064

This test ensures proposal generation reauthorizes the personal conversation
and source assistant message, constrains evidence and reference lineage, and
enforces blocked and partial-confirmation states before image generation.
"""

import copy
import importlib
import sys
from pathlib import Path

import pytest
from flask import Flask


REPO_ROOT = Path(__file__).resolve().parents[1]
SINGLE_APP_ROOT = REPO_ROOT / 'application' / 'single_app'
if str(SINGLE_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(SINGLE_APP_ROOT))


class DummyNotFoundError(Exception):
    """Raised when an in-memory Cosmos item cannot be read."""


class FakeConversationContainer:
    """Store personal conversations by their id and partition key."""

    def __init__(self, items):
        self.items = {item['id']: copy.deepcopy(item) for item in items}
        self.upserted_items = []

    def read_item(self, item=None, partition_key=None, *args, **kwargs):
        item_id = item if item is not None else args[0]
        stored_item = self.items.get(item_id)
        if stored_item is None or partition_key != item_id:
            raise DummyNotFoundError(item_id)
        return copy.deepcopy(stored_item)

    def upsert_item(self, item):
        stored_item = copy.deepcopy(item)
        self.items[stored_item['id']] = stored_item
        self.upserted_items.append(stored_item)
        return copy.deepcopy(stored_item)


class FakeMessageContainer:
    """Store assistant messages under their conversation partition."""

    def __init__(self, items):
        self.items = {
            (item['conversation_id'], item['id']): copy.deepcopy(item)
            for item in items
        }
        self.read_count = 0

    def read_item(self, item=None, partition_key=None, *args, **kwargs):
        self.read_count += 1
        item_id = item if item is not None else args[0]
        stored_item = self.items.get((partition_key, item_id))
        if stored_item is None:
            raise DummyNotFoundError(item_id)
        return copy.deepcopy(stored_item)

    def query_items(self, *, query, parameters, partition_key, **kwargs):
        del query, parameters, partition_key, kwargs
        return []

    def set_item(self, item):
        self.items[(item['conversation_id'], item['id'])] = copy.deepcopy(item)


def _evidence_metadata(
    *,
    ledger_status='ready',
    runtime_status='succeeded',
    requirement_status='satisfied',
    source_status='succeeded',
    include_supported_fact=True,
):
    ledger = {
        'version': 1,
        'status': ledger_status,
        'requirements': [{
            'id': 'profile_evidence',
            'description': 'Verified profile evidence',
            'required': True,
            'status': requirement_status,
        }],
        'sources': [{
            'id': 'selected_agent',
            'type': 'selected_agent',
            'status': source_status,
            'required': True,
            'authorization_status': 'authorized',
        }],
        'facts': [],
        'results': [],
        'citations': [],
        'artifacts': [{
            'id': 'artifact-headshot',
            'type': 'image_reference',
            'name': 'Authorized headshot',
            'reference': 'conversation-owner_image_1_2_3',
            'message_id': 'conversation-owner_image_1_2_3',
            'source_ids': ['selected_agent'],
        }],
        'missing_or_failed': [],
    }
    if include_supported_fact:
        ledger['facts'].append({
            'id': 'fact-profile-role',
            'text': 'The profile includes a verified role.',
            'source_ids': ['selected_agent'],
        })
    return {
        'evidence_ledger': ledger,
        'orchestration_runtime': {
            'version': 1,
            'status': runtime_status,
        },
    }


def _assistant_message(conversation_id, message_id='assistant-source', metadata=None):
    return {
        'id': message_id,
        'conversation_id': conversation_id,
        'role': 'assistant',
        'content': 'Grounded image proposal.',
        'metadata': metadata or _evidence_metadata(),
    }


def _approval_payload(conversation_id='conversation-owner', **overrides):
    payload = {
        'conversation_id': conversation_id,
        'assistant_message_id': 'assistant-source',
        'proposal': {
            'version': 1,
            'visualId': 'profile-visual',
            'title': 'Profile visual',
            'prompt': 'Create a grounded profile illustration.',
            'evidenceIds': ['fact-profile-role', 'forged-fact'],
            'referenceImageIds': ['artifact-headshot', 'foreign-image-reference'],
        },
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def approval_route_app(monkeypatch):
    """Register the production route with in-memory authorization dependencies."""
    monkeypatch.chdir(SINGLE_APP_ROOT)
    route_backend_chats = importlib.import_module('route_backend_chats')
    user_state = {'id': 'user-owner'}
    generated_requests = []

    conversation_container = FakeConversationContainer([
        {'id': 'conversation-owner', 'user_id': 'user-owner', 'title': 'Owner conversation'},
        {'id': 'conversation-foreign', 'user_id': 'user-foreign', 'title': 'Foreign conversation'},
    ])
    other_run_metadata = _evidence_metadata()
    other_run_metadata['evidence_ledger']['run_id'] = 'other-run'
    other_run_metadata['evidence_ledger']['facts'] = [{
        'id': 'fact-other-run',
        'text': 'Evidence from another assistant turn.',
        'source_ids': ['selected_agent'],
    }]
    message_container = FakeMessageContainer([
        _assistant_message('conversation-owner'),
        _assistant_message(
            'conversation-owner',
            message_id='assistant-other-run',
            metadata=other_run_metadata,
        ),
        _assistant_message('conversation-foreign', message_id='assistant-foreign'),
    ])

    def generate_image(**kwargs):
        generated_requests.append(copy.deepcopy(kwargs))
        proposal = copy.deepcopy(kwargs['proposal'])
        message_id = 'conversation-owner_image_9_8_7'
        return {
            'reply': 'Image loading...',
            'image_url': f'/api/image/{message_id}',
            'conversation_id': kwargs['conversation_id'],
            'model_deployment_name': 'mock-image-model',
            'message_id': message_id,
            'image_message': {
                'id': message_id,
                'prompt': kwargs['prompt'],
                'created_at': '2026-07-15T12:00:00Z',
                'timestamp': '2026-07-15T12:00:00Z',
                'metadata': {'image_proposal': proposal},
            },
        }

    monkeypatch.setattr(route_backend_chats, 'login_required', lambda func: func)
    monkeypatch.setattr(route_backend_chats, 'user_required', lambda func: func)
    monkeypatch.setattr(
        route_backend_chats,
        'swagger_route',
        lambda **kwargs: (lambda func: func),
    )
    monkeypatch.setattr(route_backend_chats, 'get_auth_security', lambda: {})
    monkeypatch.setattr(route_backend_chats, 'get_current_user_id', lambda: user_state['id'])
    monkeypatch.setattr(route_backend_chats, 'get_current_user_info', lambda: {})
    monkeypatch.setattr(
        route_backend_chats,
        'get_settings',
        lambda: {'enable_image_generation': True},
    )
    monkeypatch.setattr(
        route_backend_chats,
        'cosmos_conversations_container',
        conversation_container,
    )
    monkeypatch.setattr(
        route_backend_chats,
        'cosmos_messages_container',
        message_container,
    )
    monkeypatch.setattr(route_backend_chats, 'CosmosResourceNotFoundError', DummyNotFoundError)
    monkeypatch.setattr(route_backend_chats, 'generate_chat_image_message', generate_image)
    monkeypatch.setattr(
        route_backend_chats,
        'invalidate_conversation_cache_for_item',
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(route_backend_chats, 'log_event', lambda *args, **kwargs: None)

    app = Flask(__name__)
    app.config['TESTING'] = True
    route_backend_chats.register_route_backend_chats(app)
    app.config['approval_route_state'] = {
        'conversations': conversation_container,
        'messages': message_container,
        'generated_requests': generated_requests,
        'user': user_state,
    }
    return app


def test_owner_approval_constrains_forged_lineage(approval_route_app):
    """Verify valid owner approval retains only source-ledger lineage."""
    with approval_route_app.test_client() as client:
        response = client.post(
            '/api/chat/image-proposals/generate',
            json=_approval_payload(),
        )

    state = approval_route_app.config['approval_route_state']
    assert response.status_code == 200
    assert len(state['generated_requests']) == 1
    generated_proposal = state['generated_requests'][0]['proposal']
    assert generated_proposal['evidenceIds'] == ['fact-profile-role']
    assert generated_proposal['referenceImageIds'] == ['artifact-headshot']
    assert response.get_json()['approval_review']['state'] == 'ready'


def test_other_turn_lineage_is_removed_from_selected_source_message(approval_route_app):
    """Verify same-conversation evidence from another turn cannot cross ledgers."""
    payload = _approval_payload()
    payload['proposal']['evidenceIds'] = ['fact-other-run']

    with approval_route_app.test_client() as client:
        response = client.post('/api/chat/image-proposals/generate', json=payload)

    state = approval_route_app.config['approval_route_state']
    assert response.status_code == 200
    assert 'evidenceIds' not in state['generated_requests'][0]['proposal']


def test_legacy_proposal_without_source_ledger_remains_approvable(approval_route_app):
    """Verify legacy ungrounded proposals retain their existing opt-in flow."""
    with approval_route_app.test_client() as client:
        response = client.post(
            '/api/chat/image-proposals/generate',
            json=_approval_payload(assistant_message_id=''),
        )

    state = approval_route_app.config['approval_route_state']
    generated_proposal = state['generated_requests'][0]['proposal']
    assert response.status_code == 200
    assert response.get_json()['approval_review']['ledger_status'] == 'unavailable'
    assert 'evidenceIds' not in generated_proposal
    assert 'referenceImageIds' not in generated_proposal


def test_foreign_conversation_is_rejected_before_source_read(approval_route_app):
    """Verify conversation ownership gates all dependent source-message reads."""
    state = approval_route_app.config['approval_route_state']
    initial_read_count = state['messages'].read_count

    with approval_route_app.test_client() as client:
        response = client.post(
            '/api/chat/image-proposals/generate',
            json=_approval_payload(conversation_id='conversation-foreign'),
        )

    assert response.status_code == 403
    assert state['messages'].read_count == initial_read_count
    assert state['generated_requests'] == []


def test_missing_conversation_and_cross_partition_source_return_not_found(approval_route_app):
    """Verify missing objects cannot downgrade into unbound image generation."""
    with approval_route_app.test_client() as client:
        missing_conversation = client.post(
            '/api/chat/image-proposals/generate',
            json=_approval_payload(conversation_id='conversation-missing'),
        )
        foreign_source = client.post(
            '/api/chat/image-proposals/generate',
            json=_approval_payload(assistant_message_id='assistant-foreign'),
        )

    state = approval_route_app.config['approval_route_state']
    assert missing_conversation.status_code == 404
    assert foreign_source.status_code == 404
    assert state['generated_requests'] == []


def test_active_to_partial_transition_requires_literal_confirmation(approval_route_app):
    """Verify active evidence blocks and terminal partial evidence needs boolean true."""
    state = approval_route_app.config['approval_route_state']
    active_message = _assistant_message(
        'conversation-owner',
        metadata=_evidence_metadata(
            ledger_status='collecting',
            runtime_status='running',
            requirement_status='pending',
            source_status='running',
            include_supported_fact=False,
        ),
    )
    state['messages'].set_item(active_message)

    with approval_route_app.test_client() as client:
        blocked = client.post(
            '/api/chat/image-proposals/generate',
            json=_approval_payload(confirm_partial=True),
        )

        partial_message = _assistant_message(
            'conversation-owner',
            metadata=_evidence_metadata(
                ledger_status='partial',
                runtime_status='partial',
                requirement_status='unsatisfied',
                source_status='partial',
            ),
        )
        partial_message['metadata']['evidence_ledger']['missing_or_failed'].append({
            'status': 'not_found',
            'message': 'The requested public profile could not be verified.',
        })
        state['messages'].set_item(partial_message)

        missing_confirmation = client.post(
            '/api/chat/image-proposals/generate',
            json=_approval_payload(),
        )
        string_confirmation = client.post(
            '/api/chat/image-proposals/generate',
            json=_approval_payload(confirm_partial='true'),
        )
        confirmed = client.post(
            '/api/chat/image-proposals/generate',
            json=_approval_payload(confirm_partial=True),
        )

    assert blocked.status_code == 409
    assert blocked.get_json()['approval_review']['state'] == 'blocked'
    assert missing_confirmation.status_code == 409
    assert string_confirmation.status_code == 409
    assert missing_confirmation.get_json()['approval_review']['state'] == 'confirmation_required'
    assert confirmed.status_code == 200
    assert len(state['generated_requests']) == 1