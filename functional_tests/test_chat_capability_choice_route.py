#!/usr/bin/env python3
# test_chat_capability_choice_route.py
"""
Functional test for authenticated chat capability decisions.
Version: 0.250.066
Implemented in: 0.250.066

This test ensures proposal decisions reauthorize the exact personal
conversation and source turn, reject forged or stale choices, revalidate
capability authorization, and remain idempotent under duplicate clicks.
"""

import copy
import importlib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from flask import Flask


REPO_ROOT = Path(__file__).resolve().parents[1]
SINGLE_APP_ROOT = REPO_ROOT / 'application' / 'single_app'
if str(SINGLE_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(SINGLE_APP_ROOT))

from functions_chat_capabilities import (  # noqa: E402
    build_capability_recommendation,
    build_governed_capability_inventory,
    classify_capability_requirements,
)
from functions_chat_capability_choices import (  # noqa: E402
    build_capability_choice_proposal,
    build_capability_provenance,
)


class DummyNotFoundError(Exception):
    """Raised when an in-memory Cosmos item cannot be read."""


class ConditionalConflict(Exception):
    """Represent a Cosmos ETag conflict."""

    status_code = 412


class FakeConversationContainer:
    def __init__(self, items):
        self.items = {item['id']: copy.deepcopy(item) for item in items}

    def read_item(self, item=None, partition_key=None, *args, **kwargs):
        del kwargs
        item_id = item if item is not None else args[0]
        stored = self.items.get(item_id)
        if stored is None or partition_key != item_id:
            raise DummyNotFoundError(item_id)
        return copy.deepcopy(stored)


class FakeMessageContainer:
    def __init__(self, items):
        self.items = {
            (item['conversation_id'], item['id']): copy.deepcopy(item)
            for item in items
        }
        self.versions = {key: 1 for key in self.items}
        self.read_count = 0
        self.replace_count = 0
        for key, item in self.items.items():
            item['_etag'] = str(self.versions[key])

    def read_item(self, item=None, partition_key=None, *args, **kwargs):
        del kwargs
        self.read_count += 1
        item_id = item if item is not None else args[0]
        stored = self.items.get((partition_key, item_id))
        if stored is None:
            raise DummyNotFoundError(item_id)
        return copy.deepcopy(stored)

    def replace_item(self, *, item, body, etag, match_condition):
        del match_condition
        key = (body.get('conversation_id'), item)
        stored = self.items.get(key)
        if stored is None or stored.get('_etag') != etag:
            raise ConditionalConflict()
        self.versions[key] += 1
        saved = copy.deepcopy(body)
        saved['_etag'] = str(self.versions[key])
        self.items[key] = saved
        self.replace_count += 1
        return copy.deepcopy(saved)

    def query_items(self, *, query, parameters, partition_key, **kwargs):
        del query, kwargs
        parameter_values = {
            parameter['name']: parameter['value']
            for parameter in parameters
        }
        proposal_id = parameter_values.get('@proposal_id')
        execution_id = parameter_values.get('@execution_id')
        matches = []
        for (conversation_id, _), message in self.items.items():
            metadata = message.get('metadata') if isinstance(message.get('metadata'), dict) else {}
            resume = metadata.get('capability_resume') if isinstance(metadata.get('capability_resume'), dict) else {}
            if (
                conversation_id == partition_key
                and message.get('role') == 'assistant'
                and resume.get('proposal_id') == proposal_id
                and resume.get('execution_id') == execution_id
            ):
                matches.append(copy.deepcopy(message))
        return matches[:1]

    def set_item(self, item):
        key = (item['conversation_id'], item['id'])
        self.versions[key] = self.versions.get(key, 0) + 1
        stored = copy.deepcopy(item)
        stored['_etag'] = str(self.versions[key])
        self.items[key] = stored


def _inventory(*, web_authorized=True):
    resolved = {
        capability_id: {
            'enabled': True,
            'available': True,
            'authorized': True,
            'governance_mode': 'recommend',
        }
        for capability_id in (
            'workspace_search', 'analyze', 'compare', 'image',
            'web_search', 'url_access', 'deep_research',
        )
    }
    resolved['web_search']['authorized'] = web_authorized
    return build_governed_capability_inventory(resolved_capabilities=resolved)


def _proposal_documents(*, expires_at=None):
    inventory = _inventory()
    recommendation = build_capability_recommendation(
        inventory,
        classify_capability_requirements('What are the current county rules?'),
    )
    now = datetime.now(timezone.utc)
    proposal = build_capability_choice_proposal(
        recommendation,
        run_id='parent-run-1',
        conversation_id='conversation-owner',
        user_message_id='user-message-1',
        assistant_message_id='proposal-1',
        now=now,
    )
    if expires_at:
        proposal['expires_at'] = expires_at
    provenance = build_capability_provenance(
        selection_snapshot={
            'conversation_id': 'conversation-owner',
            'toggles': {
                'workspace_search': False,
                'web_search': False,
                'url_access': False,
                'source_review': False,
                'deep_research': False,
            },
        },
        capability_inventory=inventory,
        proposal=proposal,
        effective_capabilities=[],
    )
    user_message = {
        'id': 'user-message-1',
        'conversation_id': 'conversation-owner',
        'role': 'user',
        'content': 'What are the current county rules?',
        'metadata': {
            'orchestration': {'run_id': 'parent-run-1'},
            'capability_provenance': copy.deepcopy(provenance),
            'thread_info': {
                'thread_id': 'thread-1',
                'previous_thread_id': None,
            },
        },
    }
    assistant_message = {
        'id': 'proposal-1',
        'conversation_id': 'conversation-owner',
        'role': 'assistant',
        'content': 'Choose how to continue.',
        'metadata': {
            'capability_proposal': proposal,
            'capability_provenance': provenance,
            'capability_resume_request': {
                'hybrid_search': False,
                'web_search_enabled': False,
                'url_access_enabled': False,
                'source_review_enabled': False,
                'deep_research_enabled': False,
                'selected_document_ids': [],
                'active_group_ids': [],
                'active_public_workspace_ids': [],
                'doc_scope': 'personal',
                'chat_type': 'user',
            },
        },
    }
    return user_message, assistant_message


@pytest.fixture
def capability_route_app(monkeypatch):
    monkeypatch.chdir(SINGLE_APP_ROOT)
    route_backend_chats = importlib.import_module('route_backend_chats')
    user_state = {'id': 'user-owner'}
    inventory_state = {'web_authorized': True}
    user_message, proposal_message = _proposal_documents()
    conversations = FakeConversationContainer([
        {'id': 'conversation-owner', 'user_id': 'user-owner'},
        {'id': 'conversation-foreign', 'user_id': 'user-foreign'},
    ])
    messages = FakeMessageContainer([user_message, proposal_message])

    monkeypatch.setattr(route_backend_chats, 'login_required', lambda func: func)
    monkeypatch.setattr(route_backend_chats, 'user_required', lambda func: func)
    monkeypatch.setattr(
        route_backend_chats,
        'swagger_route',
        lambda **kwargs: (lambda func: func),
    )
    monkeypatch.setattr(route_backend_chats, 'get_auth_security', lambda: {})
    monkeypatch.setattr(route_backend_chats, 'get_current_user_id', lambda: user_state['id'])
    monkeypatch.setattr(route_backend_chats, 'get_current_user_info', lambda: {'email': 'owner@example.com'})
    monkeypatch.setattr(route_backend_chats, 'get_settings', lambda: {})
    monkeypatch.setattr(route_backend_chats, 'cosmos_conversations_container', conversations)
    monkeypatch.setattr(route_backend_chats, 'cosmos_messages_container', messages)
    monkeypatch.setattr(route_backend_chats, 'CosmosResourceNotFoundError', DummyNotFoundError)
    monkeypatch.setattr(
        route_backend_chats,
        '_get_authorized_chat_scope_context',
        lambda *args, **kwargs: {
            'active_group_ids': [],
            'active_group_id': None,
            'active_public_workspace_ids': [],
            'active_public_workspace_id': None,
        },
    )
    monkeypatch.setattr(
        route_backend_chats,
        '_resolve_authorized_chat_selected_documents',
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        route_backend_chats,
        '_resolve_server_chat_capability_inventory',
        lambda **kwargs: _inventory(web_authorized=inventory_state['web_authorized']),
    )
    monkeypatch.setattr(route_backend_chats, 'log_event', lambda *args, **kwargs: None)

    app = Flask(__name__)
    app.config['TESTING'] = True
    app.secret_key = 'capability-route-test'
    route_backend_chats.register_route_backend_chats(app)
    app.config['capability_route_state'] = {
        'route_module': route_backend_chats,
        'messages': messages,
        'user': user_state,
        'inventory': inventory_state,
    }
    return app


def _decision(client, option_id='web_search', conversation_id='conversation-owner', **extra):
    return client.post(
        '/api/chat/capability-proposals/proposal-1/decision',
        json={
            'conversation_id': conversation_id,
            'option_id': option_id,
            **extra,
        },
    )


def test_owner_decision_is_idempotent_and_ignores_capability_claims(capability_route_app):
    with capability_route_app.test_client() as client:
        first = _decision(client, capabilities=['deep_research'])
        duplicate = _decision(client, capabilities=['deep_research'])

    state = capability_route_app.config['capability_route_state']
    stored = state['messages'].items[('conversation-owner', 'proposal-1')]
    assert first.status_code == 200
    assert duplicate.status_code == 200
    assert first.get_json()['idempotent'] is False
    assert duplicate.get_json()['idempotent'] is True
    assert stored['metadata']['capability_proposal']['decision']['capability_ids'] == ['web_search']
    assert state['messages'].replace_count == 1


def test_forged_and_conflicting_options_are_rejected(capability_route_app):
    with capability_route_app.test_client() as client:
        forged = _decision(client, option_id='forged_capability')
        approved = _decision(client, option_id='web_search')
        conflicting = _decision(client, option_id='deep_research')

    assert forged.status_code == 400
    assert forged.get_json()['code'] == 'option_not_allowlisted'
    assert approved.status_code == 200
    assert conflicting.status_code == 409
    assert conflicting.get_json()['code'] == 'decision_conflict'


def test_foreign_conversation_is_rejected_before_proposal_read(capability_route_app):
    state = capability_route_app.config['capability_route_state']
    initial_reads = state['messages'].read_count
    with capability_route_app.test_client() as client:
        response = _decision(client, conversation_id='conversation-foreign')

    assert response.status_code == 403
    assert state['messages'].read_count == initial_reads


def test_cross_turn_and_deleted_source_messages_are_rejected(capability_route_app):
    state = capability_route_app.config['capability_route_state']
    user_key = ('conversation-owner', 'user-message-1')
    source_message = copy.deepcopy(state['messages'].items[user_key])
    source_message['metadata']['orchestration']['run_id'] = 'other-run'
    source_message['metadata']['capability_provenance']['proposed_capabilities']['run_id'] = 'other-run'
    state['messages'].set_item(source_message)
    with capability_route_app.test_client() as client:
        cross_turn = _decision(client)
    assert cross_turn.status_code == 400
    assert cross_turn.get_json()['code'] == 'proposal_run_mismatch'

    source_message['metadata']['orchestration']['run_id'] = 'parent-run-1'
    source_message['metadata']['capability_provenance']['proposed_capabilities']['run_id'] = 'parent-run-1'
    source_message['metadata']['is_deleted'] = True
    state['messages'].set_item(source_message)
    with capability_route_app.test_client() as client:
        deleted = _decision(client)
    assert deleted.status_code == 400
    assert deleted.get_json()['code'] == 'proposal_user_message_invalid'


def test_expired_and_revoked_capabilities_cannot_be_approved(capability_route_app):
    state = capability_route_app.config['capability_route_state']
    proposal_key = ('conversation-owner', 'proposal-1')
    proposal_message = copy.deepcopy(state['messages'].items[proposal_key])
    proposal_message['metadata']['capability_proposal']['expires_at'] = (
        datetime.now(timezone.utc) - timedelta(minutes=1)
    ).isoformat()
    state['messages'].set_item(proposal_message)
    with capability_route_app.test_client() as client:
        expired = _decision(client)
    assert expired.status_code == 409
    assert expired.get_json()['code'] == 'proposal_expired'

    user_message, fresh_proposal = _proposal_documents()
    state['messages'].set_item(user_message)
    state['messages'].set_item(fresh_proposal)
    state['inventory']['web_authorized'] = False
    with capability_route_app.test_client() as client:
        revoked = _decision(client)
    assert revoked.status_code == 409
    assert revoked.get_json()['code'] == 'capability_unauthorized'


def test_resume_claim_reconstructs_effective_capabilities_server_side(capability_route_app):
    state = capability_route_app.config['capability_route_state']
    route_backend_chats = state['route_module']
    with capability_route_app.test_client() as client:
        approved = _decision(client, capabilities=['deep_research'])
    assert approved.status_code == 200

    context = route_backend_chats._claim_authorized_capability_resume(
        settings={},
        user_id='user-owner',
        user_email='owner@example.com',
        user_roles=[],
        conversation_id='conversation-owner',
        proposal_id='proposal-1',
    )
    request_data = context['request_data']
    resume_context = request_data['_capability_resume_context']
    assert request_data['web_search_enabled'] is True
    assert request_data['deep_research_enabled'] is False
    assert request_data['_server_external_query'] == 'What are the current county rules?'
    assert resume_context['effective_capability_ids'] == ['web_search']
    assert resume_context['capability_origins'] == {
        'web_search': 'discovery_approved',
    }
    assert resume_context['selection_snapshot']['toggles']['web_search'] is False

    with pytest.raises(route_backend_chats.CapabilityChoiceError) as duplicate_claim:
        route_backend_chats._claim_authorized_capability_resume(
            settings={},
            user_id='user-owner',
            user_email='owner@example.com',
            user_roles=[],
            conversation_id='conversation-owner',
            proposal_id='proposal-1',
        )
    assert duplicate_claim.value.code == 'resume_in_progress'


def test_resume_revalidates_revocation_after_approval(capability_route_app):
    state = capability_route_app.config['capability_route_state']
    route_backend_chats = state['route_module']
    with capability_route_app.test_client() as client:
        approved = _decision(client)
    assert approved.status_code == 200

    state['inventory']['web_authorized'] = False
    with pytest.raises(route_backend_chats.CapabilityChoiceError) as revoked_claim:
        route_backend_chats._claim_authorized_capability_resume(
            settings={},
            user_id='user-owner',
            user_email='owner@example.com',
            user_roles=[],
            conversation_id='conversation-owner',
            proposal_id='proposal-1',
        )
    assert revoked_claim.value.code == 'capability_unauthorized'


def test_parent_proposal_linkage_survives_child_run_metadata(capability_route_app):
    state = capability_route_app.config['capability_route_state']
    route_backend_chats = state['route_module']
    with capability_route_app.test_client() as client:
        approved = _decision(client)
    assert approved.status_code == 200

    user_key = ('conversation-owner', 'user-message-1')
    user_message = copy.deepcopy(state['messages'].items[user_key])
    user_message['metadata']['orchestration_parent'] = copy.deepcopy(
        user_message['metadata']['orchestration']
    )
    user_message['metadata']['orchestration'] = {
        'run_id': 'child-run-1',
        'parent_run_id': 'parent-run-1',
    }
    state['messages'].set_item(user_message)

    context = route_backend_chats._load_authorized_capability_proposal_context(
        settings={},
        user_id='user-owner',
        user_email='owner@example.com',
        user_roles=[],
        conversation_id='conversation-owner',
        proposal_id='proposal-1',
    )
    assert context['proposal']['run_id'] == 'parent-run-1'
    assert context['provenance']['proposed_capabilities']['run_id'] == 'parent-run-1'


def test_persisted_assistant_reconciles_process_loss_without_duplicate_execution(capability_route_app):
    state = capability_route_app.config['capability_route_state']
    route_backend_chats = state['route_module']
    with capability_route_app.test_client() as client:
        approved = _decision(client)
    assert approved.status_code == 200

    claimed = route_backend_chats._claim_authorized_capability_resume(
        settings={},
        user_id='user-owner',
        user_email='owner@example.com',
        user_roles=[],
        conversation_id='conversation-owner',
        proposal_id='proposal-1',
    )
    resume_context = claimed['request_data']['_capability_resume_context']
    state['messages'].set_item({
        'id': 'resumed-assistant-1',
        'conversation_id': 'conversation-owner',
        'role': 'assistant',
        'content': 'Completed before proposal state was updated.',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'metadata': {
            'capability_resume': {
                'proposal_id': 'proposal-1',
                'execution_id': resume_context['execution_id'],
            },
        },
    })

    reconciled = route_backend_chats._claim_authorized_capability_resume(
        settings={},
        user_id='user-owner',
        user_email='owner@example.com',
        user_roles=[],
        conversation_id='conversation-owner',
        proposal_id='proposal-1',
    )
    assert reconciled['already_completed'] is True
    assert reconciled['proposal']['resume']['status'] == 'completed'
    assert reconciled['proposal']['resume']['assistant_message_id'] == 'resumed-assistant-1'


def test_policy_blocked_submitted_capability_is_rejected_before_execution(capability_route_app):
    route_backend_chats = capability_route_app.config['capability_route_state']['route_module']
    blocked = route_backend_chats._get_policy_blocked_selected_capability_ids(
        {
            'chat_capability_governance': {
                'web_search': 'blocked',
            },
        },
        {'web_search_enabled': True},
    )
    assert blocked == ['web_search']
    assert 'not currently available or permitted' in (
        route_backend_chats._build_selected_capability_rejection_message([
            {'id': 'web_search', 'label': 'Web Search'},
        ])
    )


def test_effective_capabilities_reconstruct_each_execution_mode(capability_route_app):
    route_backend_chats = capability_route_app.config['capability_route_state']['route_module']
    base_request = {
        'selected_document_ids': ['document-1', 'document-2'],
        'active_group_ids': [],
        'active_public_workspace_ids': [],
        'doc_scope': 'personal',
    }
    retrieval_request = route_backend_chats._apply_effective_capabilities_to_request(
        base_request,
        ['workspace_search', 'web_search', 'url_access', 'deep_research'],
    )
    assert retrieval_request['hybrid_search'] is True
    assert retrieval_request['web_search_enabled'] is True
    assert retrieval_request['url_access_enabled'] is True
    assert retrieval_request['source_review_enabled'] is True
    assert retrieval_request['deep_research_enabled'] is True

    analyze_request = route_backend_chats._apply_effective_capabilities_to_request(
        base_request,
        ['analyze'],
    )
    assert analyze_request['document_action']['type'] == 'analyze'
    assert analyze_request['document_action']['document_ids'] == [
        'document-1',
        'document-2',
    ]

    compare_request = route_backend_chats._apply_effective_capabilities_to_request(
        base_request,
        ['compare'],
    )
    assert compare_request['document_action']['type'] == 'comparison'
    assert compare_request['document_action']['left_document_id'] == 'document-1'
    assert compare_request['document_action']['right_document_ids'] == ['document-2']


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-q']))