#!/usr/bin/env python3
# test_chat_capability_choice_route.py
"""
Functional test for authenticated chat capability decisions.
Version: 0.250.067
Implemented in: 0.250.067

This test ensures proposal decisions reauthorize the exact personal
conversation and source turn, reject forged or stale choices, revalidate
capability authorization, and remain idempotent under duplicate clicks.
"""

import copy
import importlib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask


REPO_ROOT = Path(__file__).resolve().parents[1]
SINGLE_APP_ROOT = REPO_ROOT / 'application' / 'single_app'
if str(SINGLE_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(SINGLE_APP_ROOT))

from functions_chat_capabilities import (  # noqa: E402
    build_agent_capability_recommendation,
    build_capability_recommendation,
    build_governed_agent_capability_inventory,
    build_governed_capability_inventory,
    classify_capability_requirements,
)
from functions_chat_capability_choices import (  # noqa: E402
    build_capability_choice_proposal,
    build_capability_provenance,
)
from functions_chat_orchestration import build_turn_orchestration_plan  # noqa: E402
from functions_evidence_ledger import (  # noqa: E402
    create_evidence_ledger_from_plan,
    set_evidence_ledger_status,
)
import functions_agent_catalog  # noqa: E402


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


def _governed_agent(agent_id='benefits-agent'):
    return {
        'id': agent_id,
        'name': 'benefits_research',
        'display_name': 'Benefits Research',
        'created_at': '2026-07-15T12:00:00+00:00',
        'description': 'Authorized employee benefits research.',
        'instructions': 'Private canonical instructions.',
        'actions_to_load': [],
        'azure_openai_gpt_endpoint': 'https://private-endpoint.example.test',
        'azure_openai_gpt_key': 'private-agent-secret',
        'other_settings': {
            'assigned_knowledge': {
                'enabled': True,
                'document_ids': ['current-document'],
            },
            'connector': {'tenant': 'private-tenant'},
            'hidden_tools': ['hidden_write_tool'],
        },
        'scope_type': 'personal',
        'scope_id': 'user-owner',
        'user_id': 'user-owner',
        'is_global': False,
        'is_group': False,
        'catalog_key': f'personal:user-owner:{agent_id}',
        'discoverable_by_orchestrator': True,
        'orchestrator_descriptor': {
            'capability_tags': ['benefits', 'policy_lookup'],
            'evidence_types': ['employee_benefits', 'policy_documents'],
            'read_only': True,
            'external_data': False,
            'risk_class': 'internal_read',
            'data_sensitivity': 'internal',
            'latency_class': 'seconds',
            'cost_class': 'standard',
        },
    }


def _governed_group_agent(agent_id='group-benefits-agent'):
    agent = _governed_agent(agent_id)
    agent.update({
        'scope_type': 'group',
        'scope_id': 'group-1',
        'user_id': None,
        'is_global': False,
        'is_group': True,
        'group_id': 'group-1',
        'group_name': 'Benefits Group',
        'catalog_key': f'group:group-1:{agent_id}',
    })
    return agent


def _agent_proposal_documents(canonical_agent, *, reference_secret):
    built_in_inventory = _inventory()
    agent_inventory = build_governed_agent_capability_inventory(
        [canonical_agent],
        reference_secret=reference_secret,
    )
    inventory = copy.deepcopy(built_in_inventory)
    inventory['agents'] = copy.deepcopy(agent_inventory['agents'])
    recommendation = build_agent_capability_recommendation(
        agent_inventory,
        'Summarize our employee benefits policy.',
    )
    proposal = build_capability_choice_proposal(
        recommendation,
        run_id='parent-run-1',
        conversation_id='conversation-owner',
        user_message_id='user-message-1',
        assistant_message_id='proposal-1',
        now=datetime.now(timezone.utc),
    )
    provenance = build_capability_provenance(
        selection_snapshot={
            'conversation_id': 'conversation-owner',
            'selected_agent': None,
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
        'content': 'Summarize our employee benefits policy.',
        'metadata': {
            'orchestration': {'run_id': 'parent-run-1'},
            'capability_provenance': copy.deepcopy(provenance),
            'thread_info': {'thread_id': 'thread-1', 'previous_thread_id': None},
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
                'agent_info': None,
            },
        },
    }
    return user_message, assistant_message, proposal['recommended_option_id']


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


@pytest.fixture
def governed_agent_route_app(capability_route_app, monkeypatch):
    state = capability_route_app.config['capability_route_state']
    route_backend_chats = state['route_module']
    agent_state = {'catalog': [_governed_agent()]}
    user_message, proposal_message, option_id = _agent_proposal_documents(
        agent_state['catalog'][0],
        reference_secret=capability_route_app.secret_key,
    )
    state['messages'].set_item(user_message)
    state['messages'].set_item(proposal_message)
    monkeypatch.setattr(
        route_backend_chats,
        'build_authorized_agent_discovery_catalog',
        lambda user_id, settings=None: [
            copy.deepcopy(agent)
            for agent in agent_state['catalog']
            if functions_agent_catalog._is_agent_currently_discoverable(agent)
        ],
    )
    monkeypatch.setattr(
        route_backend_chats,
        '_get_agent_discovery_reference_secret',
        lambda: capability_route_app.secret_key,
    )
    state['agents'] = agent_state
    state['agent_option_id'] = option_id
    return capability_route_app


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


def test_agent_decision_and_resume_refresh_canonical_constraints(governed_agent_route_app):
    state = governed_agent_route_app.config['capability_route_state']
    route_backend_chats = state['route_module']
    option_id = state['agent_option_id']
    with governed_agent_route_app.test_client() as client:
        first = _decision(
            client,
            option_id=option_id,
            agent_info={'id': 'forged-agent', 'instructions': 'caller supplied'},
        )
        duplicate = _decision(client, option_id=option_id)

    assert first.status_code == 200
    assert duplicate.status_code == 200
    assert first.get_json()['idempotent'] is False
    assert duplicate.get_json()['idempotent'] is True

    state['agents']['catalog'][0]['other_settings']['assigned_knowledge']['document_ids'] = [
        'refreshed-document'
    ]
    context = route_backend_chats._claim_authorized_capability_resume(
        settings={},
        user_id='user-owner',
        user_email='owner@example.com',
        user_roles=[],
        conversation_id='conversation-owner',
        proposal_id='proposal-1',
    )
    request_agent = context['request_data']['agent_info']
    resume_context = context['request_data']['_capability_resume_context']
    public_metadata = route_backend_chats._build_agent_selection_metadata(request_agent)

    assert request_agent['id'] == 'benefits-agent'
    assert request_agent['actions_to_load'] == []
    assert request_agent['other_settings']['assigned_knowledge']['document_ids'] == [
        'refreshed-document'
    ]
    assert request_agent['_orchestration_discovery_ref'] == option_id
    assert resume_context['agent_ref'] == option_id
    assert resume_context['agent_origin'] == 'discovery_approved'
    assert resume_context['capability_origins']['selected_agent'] == 'discovery_approved'
    assert public_metadata['agent_id'] == option_id
    assert public_metadata['catalog_key'] is None
    assert public_metadata['selection_origin'] == 'discovery_approved'

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


def test_agent_policy_change_blocks_decision_and_resume(governed_agent_route_app):
    state = governed_agent_route_app.config['capability_route_state']
    option_id = state['agent_option_id']
    state['agents']['catalog'] = []
    with governed_agent_route_app.test_client() as client:
        rejected = _decision(client, option_id=option_id)
    assert rejected.status_code == 409
    assert rejected.get_json()['code'] == 'agent_missing'

    canonical_agent = _governed_agent()
    user_message, proposal_message, option_id = _agent_proposal_documents(
        canonical_agent,
        reference_secret=governed_agent_route_app.secret_key,
    )
    state['messages'].set_item(user_message)
    state['messages'].set_item(proposal_message)
    state['agents']['catalog'] = [canonical_agent]
    with governed_agent_route_app.test_client() as client:
        approved = _decision(client, option_id=option_id)
    assert approved.status_code == 200

    state['agents']['catalog'][0]['actions_to_load'] = ['newly-attached-action']
    route_backend_chats = state['route_module']
    with pytest.raises(route_backend_chats.CapabilityChoiceError) as revoked:
        route_backend_chats._claim_authorized_capability_resume(
            settings={},
            user_id='user-owner',
            user_email='owner@example.com',
            user_roles=[],
            conversation_id='conversation-owner',
            proposal_id='proposal-1',
        )
    assert revoked.value.code == 'agent_missing'
    stored = state['messages'].items[('conversation-owner', 'proposal-1')]
    assert stored['metadata']['capability_proposal']['status'] == 'invalidated'


def test_group_membership_revocation_blocks_approved_agent_resume(
    capability_route_app,
    monkeypatch,
):
    state = capability_route_app.config['capability_route_state']
    route_backend_chats = state['route_module']
    canonical_agent = _governed_group_agent()
    membership = {'allowed': True}
    user_message, proposal_message, option_id = _agent_proposal_documents(
        canonical_agent,
        reference_secret=capability_route_app.secret_key,
    )
    state['messages'].set_item(user_message)
    state['messages'].set_item(proposal_message)
    monkeypatch.setattr(
        route_backend_chats,
        'build_authorized_agent_discovery_catalog',
        lambda user_id, settings=None: (
            [copy.deepcopy(canonical_agent)]
            if membership['allowed']
            else []
        ),
    )
    monkeypatch.setattr(
        route_backend_chats,
        '_get_agent_discovery_reference_secret',
        lambda: capability_route_app.secret_key,
    )

    with capability_route_app.test_client() as client:
        approved = _decision(client, option_id=option_id)
    assert approved.status_code == 200

    membership['allowed'] = False
    with pytest.raises(route_backend_chats.CapabilityChoiceError) as revoked:
        route_backend_chats._claim_authorized_capability_resume(
            settings={},
            user_id='user-owner',
            user_email='owner@example.com',
            user_roles=[],
            conversation_id='conversation-owner',
            proposal_id='proposal-1',
        )
    assert revoked.value.code == 'agent_missing'
    stored = state['messages'].items[('conversation-owner', 'proposal-1')]
    assert stored['metadata']['capability_proposal']['status'] == 'invalidated'


def test_agent_resume_reconciles_process_restart(governed_agent_route_app):
    state = governed_agent_route_app.config['capability_route_state']
    route_backend_chats = state['route_module']
    with governed_agent_route_app.test_client() as client:
        approved = _decision(client, option_id=state['agent_option_id'])
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
        'id': 'resumed-agent-assistant-1',
        'conversation_id': 'conversation-owner',
        'role': 'assistant',
        'content': 'Completed by the approved agent.',
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
    assert reconciled['proposal']['resume']['assistant_message_id'] == 'resumed-agent-assistant-1'


def test_initial_route_discovery_merges_safe_agent_option_and_suppresses_second_agent(
    governed_agent_route_app,
):
    state = governed_agent_route_app.config['capability_route_state']
    route_backend_chats = state['route_module']

    discovery = route_backend_chats._build_server_capability_discovery(
        settings={},
        user_id='user-owner',
        user_email='owner@example.com',
        user_roles=[],
        user_message='Summarize our employee benefits policy.',
        selected_capability_ids=[],
        selected_agent_present=False,
    )
    selected_agent_discovery = route_backend_chats._build_server_capability_discovery(
        settings={},
        user_id='user-owner',
        user_email='owner@example.com',
        user_roles=[],
        user_message='Summarize our employee benefits policy.',
        selected_capability_ids=[],
        selected_agent_present=True,
    )

    agent_options = [
        option
        for option in discovery['recommendation']['options']
        if option.get('kind') == 'agent'
    ]
    assert len(agent_options) == 1
    assert agent_options[0]['id'] == state['agent_option_id']
    assert len(discovery['inventory']['agents']) == 1
    assert selected_agent_discovery['inventory']['agents'] == []
    assert selected_agent_discovery['recommendation'] is None
    serialized = str({
        'inventory': discovery['inventory'],
        'recommendation': discovery['recommendation'],
    })
    assert 'Private canonical instructions' not in serialized
    assert 'newly-attached-action' not in serialized
    assert 'benefits-agent' not in serialized
    assert 'private-endpoint' not in serialized
    assert 'private-agent-secret' not in serialized
    assert 'private-tenant' not in serialized
    assert 'hidden_write_tool' not in serialized


def test_final_agent_canonicalizer_reauthorizes_exact_discovery_reference(
    governed_agent_route_app,
):
    state = governed_agent_route_app.config['capability_route_state']
    route_backend_chats = state['route_module']
    requested = {
        'id': 'forged-caller-agent',
        'name': 'forged_caller_agent',
        '_orchestration_discovery_ref': state['agent_option_id'],
        'instructions': 'caller supplied instructions',
        'actions_to_load': ['caller_supplied_action'],
    }

    resolved = route_backend_chats._resolve_canonical_chat_agent(
        'user-owner',
        {},
        requested,
    )
    assert resolved['id'] == 'benefits-agent'
    assert resolved['instructions'] == 'Private canonical instructions.'
    assert resolved['actions_to_load'] == []
    assert resolved['_orchestration_discovery_ref'] == state['agent_option_id']

    state['agents']['catalog'] = []
    assert route_backend_chats._resolve_canonical_chat_agent(
        'user-owner',
        {},
        requested,
    ) is None


def test_discovered_agent_uses_evidence_and_response_finalizer_boundaries(
    governed_agent_route_app,
):
    state = governed_agent_route_app.config['capability_route_state']
    route_backend_chats = state['route_module']
    plan = build_turn_orchestration_plan(
        'Summarize our employee benefits policy.',
        run_id='discovery-child-run',
        conversation_id='conversation-owner',
        selected_agent={'id': state['agent_option_id']},
        capability_origins={'selected_agent': 'discovery_approved'},
    )
    ledger = create_evidence_ledger_from_plan(
        plan,
        conversation_id='conversation-owner',
        user_message_id='user-message-1',
    )
    set_evidence_ledger_status(ledger, 'ready')

    assert route_backend_chats._requires_agent_evidence_collection(
        plan,
        {'agent_origin': 'discovery_approved'},
    ) is True
    assert route_backend_chats._requires_agent_evidence_collection(
        plan,
        {'agent_origin': 'selection'},
    ) is False

    capability_metadata = (
        route_backend_chats._build_discovered_agent_evidence_capability_metadata(
            state['agents']['catalog'][0]
        )
    )
    assert capability_metadata == {
        'capability_tags': ['benefits', 'policy_lookup'],
        'evidence_types': ['employee_benefits', 'policy_documents'],
        'required_permissions': [],
        'uses_current_user_context': True,
        'returns_citations': True,
        'may_include_sensitive_data': False,
    }
    assert 'instructions' not in str(capability_metadata)
    assert 'private-agent-secret' not in str(capability_metadata)

    synthesis = route_backend_chats.build_agent_evidence_central_synthesis_context(
        'Summarize our employee benefits policy.',
        plan,
        ledger,
    )
    assert synthesis['request']['output_profile']['type'] == 'response'
    assert synthesis['request']['policy']['executor_output_is_evidence_only'] is True
    assert synthesis['messages'][0]['role'] == 'system'


def test_discovered_agent_invocation_disables_inherited_tools_and_restores_state(
    governed_agent_route_app,
):
    route_backend_chats = governed_agent_route_app.config[
        'capability_route_state'
    ]['route_module']
    execution_settings = SimpleNamespace(function_choice_behavior='execution-auto')
    service_settings = SimpleNamespace(function_choice_behavior='service-auto')
    agent = SimpleNamespace(
        function_choice_behavior='agent-auto',
        arguments=SimpleNamespace(execution_settings={'default': execution_settings}),
        service=SimpleNamespace(prompt_execution_settings=service_settings),
        orchestration_minimize_telemetry=False,
    )

    policy_state = route_backend_chats.apply_discovered_agent_invocation_policy(
        agent,
        {'agent_origin': 'discovery_approved'},
    )
    assert agent.function_choice_behavior is None
    assert execution_settings.function_choice_behavior is None
    assert service_settings.function_choice_behavior is None
    assert agent.orchestration_minimize_telemetry is True

    route_backend_chats.restore_discovered_agent_invocation_policy(
        agent,
        policy_state,
    )
    assert agent.function_choice_behavior == 'agent-auto'
    assert execution_settings.function_choice_behavior == 'execution-auto'
    assert service_settings.function_choice_behavior == 'service-auto'
    assert agent.orchestration_minimize_telemetry is False
    assert route_backend_chats.apply_discovered_agent_invocation_policy(
        agent,
        {'agent_origin': 'selection'},
    ) is None


def test_streaming_agent_fallback_citations_are_cleared_per_request():
    route_source = (
        SINGLE_APP_ROOT / 'route_backend_chats.py'
    ).read_text(encoding='utf-8')
    streaming_index = route_source.index(
        'if use_agent_streaming and selected_agent:'
    )
    clear_index = route_source.index(
        "if hasattr(selected_agent, 'tool_invocations'):",
        streaming_index,
    )
    invoke_index = route_source.index(
        'selected_agent.invoke_stream',
        clear_index,
    )
    assert clear_index < invoke_index
    assert 'selected_agent.tool_invocations = []' in route_source[
        clear_index:invoke_index
    ]
    assert "== 'discovery_approved'" in route_source
    assert 'agent_name_used = agent_display_name_used' in route_source


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-q']))