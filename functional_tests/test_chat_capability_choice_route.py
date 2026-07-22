#!/usr/bin/env python3
# test_chat_capability_choice_route.py
"""
Functional test for authenticated chat capability decisions.
Version: 0.250.076
Implemented in: 0.250.067; contextual goal coverage added in 0.250.076

This test ensures proposal decisions reauthorize the exact personal
conversation and source turn, reject forged or stale choices, revalidate
capability authorization, and remain idempotent under duplicate clicks.
"""

import copy
import hashlib
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
    build_contextual_egress_recommendation,
    build_governed_agent_capability_inventory,
    build_governed_capability_inventory,
    classify_capability_requirements,
)
from functions_chat_capability_choices import (  # noqa: E402
    build_approved_user_turn_goal,
    build_capability_choice_proposal,
    build_capability_provenance,
)
from functions_chat_clarifications import (  # noqa: E402
    build_chat_clarification,
    claim_chat_clarification_response,
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
        del kwargs
        parameter_values = {
            parameter['name']: parameter['value']
            for parameter in parameters
        }
        proposal_id = parameter_values.get('@proposal_id')
        execution_id = parameter_values.get('@execution_id')
        child_run_id = parameter_values.get('@child_run_id')
        source_thread_id = parameter_values.get('@source_thread_id')
        thread_id = parameter_values.get('@thread_id')
        if source_thread_id:
            matches = []
            for (conversation_id, _), message in self.items.items():
                metadata = (
                    message.get('metadata')
                    if isinstance(message.get('metadata'), dict)
                    else {}
                )
                thread_info = (
                    metadata.get('thread_info')
                    if isinstance(metadata.get('thread_info'), dict)
                    else {}
                )
                if (
                    conversation_id == partition_key
                    and message.get('role') == 'assistant'
                    and isinstance(
                        metadata.get('chat_clarification'),
                        dict,
                    )
                    and thread_info.get('thread_id') == source_thread_id
                ):
                    matches.append(copy.deepcopy(message))
            matches.sort(
                key=lambda message: str(message.get('timestamp') or ''),
                reverse=True,
            )
            return matches[:2]
        if (
            'c.metadata.chat_clarification.status = "pending"' in query
        ):
            matches = []
            for (conversation_id, _), message in self.items.items():
                metadata = (
                    message.get('metadata')
                    if isinstance(message.get('metadata'), dict)
                    else {}
                )
                clarification = metadata.get('chat_clarification')
                if (
                    conversation_id == partition_key
                    and message.get('role') == 'assistant'
                    and isinstance(clarification, dict)
                    and clarification.get('status') in {
                        'pending',
                        'resolving',
                    }
                ):
                    matches.append(copy.deepcopy(message))
            matches.sort(
                key=lambda message: str(message.get('timestamp') or ''),
                reverse=True,
            )
            return matches[:2]
        if 'c.role = "user"' in query:
            matches = []
            for (conversation_id, _), message in self.items.items():
                metadata = (
                    message.get('metadata')
                    if isinstance(message.get('metadata'), dict)
                    else {}
                )
                thread_info = (
                    metadata.get('thread_info')
                    if isinstance(metadata.get('thread_info'), dict)
                    else {}
                )
                if not (
                    conversation_id == partition_key
                    and message.get('role') == 'user'
                    and metadata.get('is_deleted') is not True
                    and metadata.get('masked') is not True
                    and not (metadata.get('masked_ranges') or [])
                    and metadata.get(
                        'is_generated_chat_artifact'
                    ) is not True
                    and thread_info.get('active_thread') is not False
                ):
                    continue
                if thread_id and thread_info.get('thread_id') != thread_id:
                    continue
                matches.append(copy.deepcopy(message))
            matches.sort(
                key=lambda message: str(message.get('timestamp') or ''),
                reverse=True,
            )
            return matches[:2]
        matches = []
        for (conversation_id, _), message in self.items.items():
            metadata = message.get('metadata') if isinstance(message.get('metadata'), dict) else {}
            resume = metadata.get('capability_resume') if isinstance(metadata.get('capability_resume'), dict) else {}
            orchestration = metadata.get('orchestration') if isinstance(metadata.get('orchestration'), dict) else {}
            if child_run_id:
                if (
                    conversation_id == partition_key
                    and message.get('role') in {'assistant', 'image', 'safety'}
                    and orchestration.get('run_id') == child_run_id
                ):
                    matches.append(copy.deepcopy(message))
                continue
            if (
                conversation_id == partition_key
                and message.get('role') in {'assistant', 'image', 'safety'}
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


def _inventory(*, web_authorized=True, selected_capability_ids=None):
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
    return build_governed_capability_inventory(
        selected_capability_ids=selected_capability_ids,
        resolved_capabilities=resolved,
    )


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


def _contextual_proposal_documents(*, selected_web=False):
    selected_capability_ids = ['web_search'] if selected_web else None
    inventory = _inventory(
        selected_capability_ids=selected_capability_ids,
    )
    prior_message = {
        'id': 'user-message-0',
        'conversation_id': 'conversation-owner',
        'role': 'user',
        'content': 'Find JPMorgan press releases from the past three years.',
        'timestamp': '2026-07-17T10:00:00+00:00',
        'metadata': {
            'thread_info': {
                'thread_id': 'thread-0',
                'previous_thread_id': None,
                'thread_attempt': 1,
                'active_thread': True,
            },
        },
    }
    current_message = {
        'id': 'user-message-1',
        'conversation_id': 'conversation-owner',
        'role': 'user',
        'content': 'Yes, search.',
        'timestamp': '2026-07-17T10:01:00+00:00',
        'metadata': {
            'thread_info': {
                'thread_id': 'thread-1',
                'previous_thread_id': 'thread-0',
                'thread_attempt': 1,
                'active_thread': True,
            },
        },
    }
    approved_goal = build_approved_user_turn_goal(
        [prior_message, current_message],
        conversation_id='conversation-owner',
        current_user_message_id='user-message-1',
    )
    if selected_web:
        recommendation = build_contextual_egress_recommendation(
            {
                'status': 'valid',
                'decision': 'direct',
                'prior_goal_included': True,
                'requirements': [],
            },
            inventory,
            {'selected_capability_ids': ['web_search']},
        )
    else:
        recommendation = build_capability_recommendation(
            inventory,
            classify_capability_requirements(
                'What are the current county rules?'
            ),
        )
    proposal = build_capability_choice_proposal(
        recommendation,
        run_id='parent-run-1',
        conversation_id='conversation-owner',
        user_message_id='user-message-1',
        assistant_message_id='proposal-1',
        approved_user_turn_goal=approved_goal,
        capability_inventory=inventory,
        now=datetime.now(timezone.utc),
    )
    selection_snapshot = {
        'conversation_id': 'conversation-owner',
        'toggles': {
            'workspace_search': False,
            'web_search': selected_web,
            'url_access': False,
            'source_review': False,
            'deep_research': False,
        },
    }
    effective_capabilities = (
        [{'id': 'web_search', 'origin': 'selection', 'required': True}]
        if selected_web
        else []
    )
    provenance = build_capability_provenance(
        selection_snapshot=selection_snapshot,
        capability_inventory=inventory,
        proposal=proposal,
        effective_capabilities=effective_capabilities,
    )
    current_message['metadata'].update({
        'orchestration': {'run_id': 'parent-run-1'},
        'capability_provenance': copy.deepcopy(provenance),
    })
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
                'web_search_enabled': selected_web,
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
    return (
        prior_message,
        current_message,
        assistant_message,
        proposal['recommended_option_id'],
    )


def _claimed_clarification_documents(
    *,
    blank_response=False,
    missing_response_thread=False,
    masked_source=False,
):
    now = datetime.now(timezone.utc)
    source_message = {
        'id': 'clarification-source-user',
        'conversation_id': 'conversation-owner',
        'role': 'user',
        'content': 'Find the rules for this jurisdiction.',
        'timestamp': now.isoformat(),
        'metadata': {
            'masked': masked_source,
            'thread_info': {
                'thread_id': 'clarification-source-thread',
                'previous_thread_id': None,
                'active_thread': True,
                'thread_attempt': 1,
            },
        },
    }
    clarification = build_chat_clarification(
        {
            'code': 'jurisdiction_required',
            'option_values': [],
        },
        parent_run_id='clarification-parent-run',
        conversation_id='conversation-owner',
        source_user_message_id='clarification-source-user',
        source_thread_id='clarification-source-thread',
        assistant_message_id='clarification-checkpoint',
        now=now,
        ttl_seconds=3600,
    )
    claimed, _ = claim_chat_clarification_response(
        clarification,
        response_user_message_id='clarification-response-user',
        response_text='Virginia',
        child_run_id='clarification-child-run',
        response_thread_id='clarification-response-thread',
        now=now + timedelta(seconds=1),
    )
    checkpoint_message = {
        'id': 'clarification-checkpoint',
        'conversation_id': 'conversation-owner',
        'role': 'assistant',
        'content': claimed['question'],
        'timestamp': (now + timedelta(seconds=1)).isoformat(),
        'metadata': {
            'awaiting_user_clarification': True,
            'chat_clarification': claimed,
            'thread_info': {
                'thread_id': 'clarification-source-thread',
                'previous_thread_id': None,
                'active_thread': True,
                'thread_attempt': 1,
            },
        },
    }
    response_metadata = {
        'clarification_response': {
            '_clarification_id': 'clarification-checkpoint',
        },
        'thread_info': {
            'thread_id': 'clarification-response-thread',
            'previous_thread_id': 'clarification-source-thread',
            'active_thread': True,
            'thread_attempt': 1,
        },
    }
    if missing_response_thread:
        response_metadata.pop('thread_info')
    response_message = {
        'id': 'clarification-response-user',
        'conversation_id': 'conversation-owner',
        'role': 'user',
        'content': '' if blank_response else 'Virginia',
        'timestamp': (now + timedelta(seconds=2)).isoformat(),
        'metadata': response_metadata,
    }
    return source_message, checkpoint_message, response_message


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
        lambda **kwargs: _inventory(
            web_authorized=inventory_state['web_authorized'],
            selected_capability_ids=kwargs.get('selected_capability_ids'),
        ),
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


def _replace_builtin_proposal_option(state, capability_id):
    proposal_key = ('conversation-owner', 'proposal-1')
    proposal_message = copy.deepcopy(state['messages'].items[proposal_key])
    proposal = proposal_message['metadata']['capability_proposal']
    proposal['recommended_option_id'] = capability_id
    proposal['options'] = [
        {
            'id': capability_id,
            'kind': 'capability',
            'capability_ids': [capability_id],
            'effective_capability_ids': [capability_id],
            'label': capability_id.replace('_', ' ').title(),
            'latency_class': 'seconds',
            'cost_class': 'standard',
            'external_data': False,
            'requires_user_choice': True,
            'read_only': capability_id != 'image',
            'risk_class': 'internal_read',
            'data_sensitivity': 'internal',
            'external_query_mode': 'minimized',
            'sensitive_input_types': [],
        },
        {
            'id': 'continue_without_capabilities',
            'kind': 'continue',
            'capability_ids': [],
            'effective_capability_ids': [],
            'label': 'Continue without additional capabilities',
            'latency_class': 'immediate',
            'cost_class': 'none',
            'external_data': False,
            'requires_user_choice': True,
            'external_query_mode': 'minimized',
            'sensitive_input_types': [],
        },
    ]
    proposal_message['metadata']['capability_provenance'][
        'proposed_capabilities'
    ] = copy.deepcopy(proposal)
    state['messages'].set_item(proposal_message)


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
    resume_context = context['capability_resume_context']
    assert '_capability_resume_context' not in request_data
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


def test_contextual_resume_rebuilds_exact_approved_user_goal(
    capability_route_app,
):
    state = capability_route_app.config['capability_route_state']
    route_backend_chats = state['route_module']
    prior, current, proposal, _ = _contextual_proposal_documents()
    state['messages'].set_item(prior)
    state['messages'].set_item(current)
    state['messages'].set_item(proposal)

    with capability_route_app.test_client() as client:
        approved = _decision(client, option_id='web_search')
    assert approved.status_code == 200

    context = route_backend_chats._claim_authorized_capability_resume(
        settings={},
        user_id='user-owner',
        user_email='owner@example.com',
        user_roles=[],
        conversation_id='conversation-owner',
        proposal_id='proposal-1',
    )

    assert context['request_data']['_server_external_query'] == (
        'Find JPMorgan press releases from the past three years. Yes, search.'
    )
    assert context['request_data']['_server_contextual_goal_query'] == (
        'Find JPMorgan press releases from the past three years. Yes, search.'
    )
    assert context['request_data']['web_search_enabled'] is True
    assert context['capability_resume_context']['decision'][
        'prior_goal_included'
    ] is True
    assert context['capability_resume_context'][
        'execution_effective_capability_ids'
    ] == ['web_search']
    assert '_approved_user_turn_goal' in (
        context['capability_resume_context']['_contextual_proposal']
    )


def test_contextual_source_mutation_invalidates_decision_and_resume(
    capability_route_app,
):
    state = capability_route_app.config['capability_route_state']
    route_backend_chats = state['route_module']
    prior, current, proposal, _ = _contextual_proposal_documents()
    state['messages'].set_item(prior)
    state['messages'].set_item(current)
    state['messages'].set_item(proposal)

    mutated_prior = copy.deepcopy(prior)
    mutated_prior['content'] = 'Changed after the contextual proposal.'
    state['messages'].set_item(mutated_prior)
    with capability_route_app.test_client() as client:
        rejected = _decision(client, option_id='web_search')
    assert rejected.status_code == 409
    assert rejected.get_json()['code'] == 'goal_source_changed'
    stored = state['messages'].items[('conversation-owner', 'proposal-1')]
    assert stored['metadata']['capability_proposal']['status'] == 'invalidated'

    prior, current, proposal, _ = _contextual_proposal_documents()
    state['messages'].set_item(prior)
    state['messages'].set_item(current)
    state['messages'].set_item(proposal)
    with capability_route_app.test_client() as client:
        approved = _decision(client, option_id='web_search')
    assert approved.status_code == 200
    prior['metadata']['masked_ranges'] = [{'start': 0, 'end': 4}]
    state['messages'].set_item(prior)

    with pytest.raises(route_backend_chats.CapabilityChoiceError) as stale_resume:
        route_backend_chats._claim_authorized_capability_resume(
            settings={},
            user_id='user-owner',
            user_email='owner@example.com',
            user_roles=[],
            conversation_id='conversation-owner',
            proposal_id='proposal-1',
        )
    assert stale_resume.value.code == 'goal_source_inactive'
    stored = state['messages'].items[('conversation-owner', 'proposal-1')]
    assert stored['metadata']['capability_proposal']['status'] == 'invalidated'


def test_contextual_decline_suppresses_selected_external_execution(
    capability_route_app,
):
    state = capability_route_app.config['capability_route_state']
    route_backend_chats = state['route_module']
    prior, current, proposal, _ = _contextual_proposal_documents(
        selected_web=True
    )
    state['messages'].set_item(prior)
    state['messages'].set_item(current)
    state['messages'].set_item(proposal)

    with capability_route_app.test_client() as client:
        declined = _decision(
            client,
            option_id='continue_without_capabilities',
        )
    assert declined.status_code == 200

    state['inventory']['web_authorized'] = False

    context = route_backend_chats._claim_authorized_capability_resume(
        settings={},
        user_id='user-owner',
        user_email='owner@example.com',
        user_roles=[],
        conversation_id='conversation-owner',
        proposal_id='proposal-1',
    )
    request_data = context['request_data']
    assert request_data['web_search_enabled'] is False
    assert request_data['url_access_enabled'] is False
    assert request_data['source_review_enabled'] is False
    assert request_data['deep_research_enabled'] is False
    assert request_data['_server_contextual_egress_declined'] is True
    assert '_server_external_query' not in request_data
    assert '_server_contextual_goal_query' not in request_data
    assert context['capability_resume_context']['decision'][
        'approval_scope'
    ] == 'prior_user_goal_egress_declined'
    assert context['capability_resume_context'][
        'execution_effective_capability_ids'
    ] == []
    assert context['capability_resume_context']['capability_origins'] == {}

    route_source = (
        REPO_ROOT / 'application' / 'single_app' / 'route_backend_chats.py'
    ).read_text(encoding='utf-8')
    streaming_generator = route_source.index(
        'def generate(publish_background_event=None):'
    )
    selected_reconstruction = route_source.index(
        'selected_builtin_capability_ids = (',
        streaming_generator,
    )
    selected_reconstruction_end = route_source.index(
        'if capability_resume_context:',
        selected_reconstruction,
    )
    assert "'execution_effective_capability_ids'" in route_source[
        selected_reconstruction:selected_reconstruction_end
    ]
    post_claim_validation = route_source.index(
        'execution_validation_baseline = build_decline_aware_execution_baseline('
    )
    request_reconstruction = route_source.index(
        'request_data = _apply_effective_capabilities_to_request(',
        post_claim_validation,
    )
    post_claim_source = route_source[
        post_claim_validation:request_reconstruction
    ]
    assert '**execution_validation_baseline' in post_claim_source
    assert (
        "execution_validation_baseline.get('selected_capability_ids')"
        in post_claim_source
    )
    assert "claimed_proposal.get('_external_capability_ids')" in (
        post_claim_source
    )
    assigned_knowledge_application = route_source.index(
        'if assigned_knowledge_filters:',
        streaming_generator,
    )
    decline_enforcement = route_source.index(
        "if data.get('_server_contextual_egress_declined') is True:",
        assigned_knowledge_application,
    )
    external_execution = route_source.index(
        'if web_search_enabled:',
        decline_enforcement,
    )
    assert assigned_knowledge_application < decline_enforcement < external_execution
    decline_source = route_source[decline_enforcement:external_execution]
    for marker in (
        'web_search_enabled = False',
        'url_access_enabled = False',
        'source_review_enabled = False',
        'deep_research_enabled = False',
        'assigned_knowledge_url_review_urls = []',
        'assigned_knowledge_deep_research_urls = []',
    ):
        assert marker in decline_source
    legacy_chat = route_source.index(
        'def chat_api(server_request_data=None, server_resume_context=None):'
    )
    legacy_assigned_knowledge = route_source.index(
        'if assigned_knowledge_filters:',
        legacy_chat,
    )
    legacy_decline_enforcement = route_source.index(
        "if data.get('_server_contextual_egress_declined') is True:",
        legacy_assigned_knowledge,
    )
    legacy_source_review = route_source.index(
        'if source_review_enabled:',
        legacy_decline_enforcement,
    )
    assert (
        legacy_assigned_knowledge
        < legacy_decline_enforcement
        < legacy_source_review
    )
    compatibility_reconstruction = route_source.index(
        'compatibility_selected_capability_ids = (',
        legacy_decline_enforcement,
    )
    compatibility_decline_enforcement = route_source.index(
        "if data.get('_server_contextual_egress_declined') is True:",
        compatibility_reconstruction,
    )
    assert "'execution_effective_capability_ids'" in route_source[
        compatibility_reconstruction:compatibility_decline_enforcement
    ]
    assert "capability.get('state') == 'selected'" not in route_source[
        compatibility_reconstruction:compatibility_decline_enforcement
    ]
    assert compatibility_decline_enforcement < legacy_source_review
    legacy_assigned_sources = route_source[
        legacy_assigned_knowledge:compatibility_reconstruction
    ]
    streaming_assigned_knowledge = route_source.index(
        'if assigned_knowledge_filters:',
        route_source.index('def generate(publish_background_event=None):'),
    )
    streaming_decline_enforcement = route_source.index(
        "if data.get('_server_contextual_egress_declined') is True:",
        streaming_assigned_knowledge,
    )
    streaming_assigned_sources = route_source[
        streaming_assigned_knowledge:streaming_decline_enforcement
    ]
    assert legacy_assigned_sources.count(
        "data.get('_server_contextual_egress_declined') is not True"
    ) >= 3
    assert streaming_assigned_sources.count(
        "data.get('_server_contextual_egress_declined') is not True"
    ) >= 3
    legacy_final_decline = route_source.index(
        "if data.get('_server_contextual_egress_declined') is True:",
        compatibility_decline_enforcement + 1,
    )
    legacy_final_revalidation = route_source.index(
        '_rebuild_claimed_contextual_goal(',
        legacy_final_decline,
    )
    legacy_web_collector = route_source.index(
        'perform_research_web_searches(',
        legacy_final_revalidation,
    )
    legacy_source_collector = route_source.index(
        'perform_source_review(',
        legacy_final_revalidation,
    )
    assert (
        compatibility_decline_enforcement
        < legacy_final_decline
        < legacy_final_revalidation
        < legacy_web_collector
        < legacy_source_collector
    )


def test_clarification_child_output_reconciliation_uses_exact_run(
    capability_route_app,
):
    state = capability_route_app.config['capability_route_state']
    route_backend_chats = state['route_module']
    state['messages'].set_item({
        'id': 'clarification-child-output',
        'conversation_id': 'conversation-owner',
        'role': 'assistant',
        'content': 'Clarified child result.',
        'timestamp': '2026-07-17T12:00:00+00:00',
        'metadata': {
            'orchestration': {'run_id': 'clarification-child-run'},
        },
    })
    state['messages'].set_item({
        'id': 'other-output',
        'conversation_id': 'conversation-owner',
        'role': 'assistant',
        'content': 'Unrelated result.',
        'timestamp': '2026-07-17T12:01:00+00:00',
        'metadata': {
            'orchestration': {'run_id': 'other-run'},
        },
    })

    matched = route_backend_chats._find_persisted_clarification_child_output(
        conversation_id='conversation-owner',
        child_run_id='clarification-child-run',
    )
    missing = route_backend_chats._find_persisted_clarification_child_output(
        conversation_id='conversation-owner',
        child_run_id='missing-child-run',
    )

    assert matched['id'] == 'clarification-child-output'
    assert missing is None


def test_stream_clarification_cleanup_resolves_output_or_releases_no_output(
    capability_route_app,
):
    state = capability_route_app.config['capability_route_state']
    route_backend_chats = state['route_module']

    source, checkpoint, response = _claimed_clarification_documents()
    for message in (source, checkpoint, response):
        state['messages'].set_item(message)
    no_output = route_backend_chats._finalize_stream_clarification_claim(
        conversation_id='conversation-owner',
        clarification=checkpoint['metadata']['chat_clarification'],
    )
    assert no_output['status'] == 'expired'
    assert no_output['invalidation_reason'] == (
        'clarification_child_output_missing'
    )

    source, checkpoint, response = _claimed_clarification_documents()
    child_output = {
        'id': 'clarification-child-output-cleanup',
        'conversation_id': 'conversation-owner',
        'role': 'assistant',
        'content': 'Clarification result.',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'metadata': {
            'orchestration': {'run_id': 'clarification-child-run'},
        },
    }
    for message in (source, checkpoint, response, child_output):
        state['messages'].set_item(message)
    completed = route_backend_chats._finalize_stream_clarification_claim(
        conversation_id='conversation-owner',
        clarification=checkpoint['metadata']['chat_clarification'],
    )
    assert completed['status'] == 'resolved'
    assert completed['lease_expires_at'] is None


def test_stale_stream_cleanup_cannot_invalidate_renewed_claim(
    capability_route_app,
):
    state = capability_route_app.config['capability_route_state']
    route_backend_chats = state['route_module']
    source, checkpoint, response = _claimed_clarification_documents()
    stale_claim = copy.deepcopy(
        checkpoint['metadata']['chat_clarification']
    )
    renewed_claim, _ = claim_chat_clarification_response(
        stale_claim,
        response_user_message_id='clarification-response-user',
        response_text='Virginia',
        child_run_id='clarification-child-run',
        response_thread_id='clarification-response-thread',
        now=datetime.now(timezone.utc) + timedelta(minutes=31),
    )
    checkpoint['metadata']['chat_clarification'] = renewed_claim
    for message in (source, checkpoint, response):
        state['messages'].set_item(message)

    with pytest.raises(
        route_backend_chats.ChatClarificationError
    ) as stale_cleanup:
        route_backend_chats._finalize_stream_clarification_claim(
            conversation_id='conversation-owner',
            clarification=stale_claim,
        )

    assert stale_cleanup.value.code == 'clarification_response_claim_mismatch'
    stored = state['messages'].items[
        ('conversation-owner', 'clarification-checkpoint')
    ]['metadata']['chat_clarification']
    assert stored['status'] == 'resolving'
    assert stored['claimed_at'] == renewed_claim['claimed_at']
    assert stored.get('invalidation_reason') is None


def test_clarification_recovery_context_deduplicates_response_and_lineage(
    capability_route_app,
):
    route_backend_chats = capability_route_app.config[
        'capability_route_state'
    ]['route_module']
    source = {
        'id': 'clarification-source-user',
        'metadata': {'thread_info': {'thread_id': 'source-thread'}},
    }
    response = {
        'id': 'clarification-response-user',
        'metadata': {
            'thread_info': {
                'thread_id': 'response-thread',
                'previous_thread_id': 'source-thread',
            },
        },
    }
    clarification = {
        '_source_user_message_id': 'clarification-source-user',
        '_source_thread_id': 'source-thread',
        '_response_user_message_id': 'clarification-response-user',
    }

    recovered = route_backend_chats._prepare_clarification_recovery_context(
        {
            'prior_user_messages': [source, response],
            'predecessor_thread_id': 'response-thread',
        },
        clarification,
    )

    assert [
        message['id']
        for message in recovered['prior_user_messages']
    ] == ['clarification-source-user']
    assert recovered['predecessor_thread_id'] == 'source-thread'
    with pytest.raises(route_backend_chats.ChatClarificationError) as missing:
        route_backend_chats._prepare_clarification_recovery_context(
            {
                'prior_user_messages': [response],
                'predecessor_thread_id': 'response-thread',
            },
            clarification,
        )
    assert missing.value.code == 'clarification_response_claim_mismatch'


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


def test_missing_document_action_target_is_atomically_invalidated_on_resume(
    capability_route_app,
):
    state = capability_route_app.config['capability_route_state']
    route_backend_chats = state['route_module']
    _replace_builtin_proposal_option(state, 'analyze')
    with capability_route_app.test_client() as client:
        approved = _decision(client, option_id='analyze')
    assert approved.status_code == 200
    assert approved.get_json()['resume_endpoint'] == '/api/chat/document-action/stream'

    with pytest.raises(route_backend_chats.CapabilityChoiceError) as missing_target:
        route_backend_chats._claim_authorized_capability_resume(
            settings={},
            user_id='user-owner',
            user_email='owner@example.com',
            user_roles=[],
            conversation_id='conversation-owner',
            proposal_id='proposal-1',
        )

    assert missing_target.value.code == 'capability_input_unavailable'
    stored = state['messages'].items[('conversation-owner', 'proposal-1')]
    proposal = stored['metadata']['capability_proposal']
    assert proposal['status'] == 'invalidated'
    assert proposal['resume']['status'] == 'failed'
    assert proposal['invalidation_reason'] == 'capability_input_unavailable'


def test_compare_requires_two_distinct_authorized_targets(
    capability_route_app,
    monkeypatch,
):
    state = capability_route_app.config['capability_route_state']
    route_backend_chats = state['route_module']
    _replace_builtin_proposal_option(state, 'compare')
    with capability_route_app.test_client() as client:
        approved = _decision(client, option_id='compare')
    assert approved.status_code == 200

    original_loader = route_backend_chats._load_authorized_capability_proposal_context

    def load_with_duplicate_target(**kwargs):
        context = original_loader(**kwargs)
        context['authorized_documents'] = [
            {'id': 'document-1'},
            {'document_id': 'document-1'},
        ]
        context['baseline_error_code'] = None
        return context

    monkeypatch.setattr(
        route_backend_chats,
        '_load_authorized_capability_proposal_context',
        load_with_duplicate_target,
    )

    with pytest.raises(route_backend_chats.CapabilityChoiceError) as missing_target:
        route_backend_chats._claim_authorized_capability_resume(
            settings={},
            user_id='user-owner',
            user_email='owner@example.com',
            user_roles=[],
            conversation_id='conversation-owner',
            proposal_id='proposal-1',
        )

    assert missing_target.value.code == 'capability_input_unavailable'
    assert route_backend_chats._distinct_authorized_document_ids(
        [{'id': 'document-1'}, {'document_id': 'document-1'}]
    ) == {'document-1'}
    stored = state['messages'].items[('conversation-owner', 'proposal-1')]
    assert stored['metadata']['capability_proposal']['status'] == 'invalidated'


def test_image_resume_reconstructs_server_request_and_additive_origin(
    capability_route_app,
):
    state = capability_route_app.config['capability_route_state']
    route_backend_chats = state['route_module']
    _replace_builtin_proposal_option(state, 'image')
    with capability_route_app.test_client() as client:
        approved = _decision(client, option_id='image')
    assert approved.status_code == 200
    assert approved.get_json()['resume_endpoint'] == '/api/chat/stream'

    context = route_backend_chats._claim_authorized_capability_resume(
        settings={},
        user_id='user-owner',
        user_email='owner@example.com',
        user_roles=[],
        conversation_id='conversation-owner',
        proposal_id='proposal-1',
    )
    request_data = context['request_data']
    resume_context = context['capability_resume_context']
    assert request_data['image_generation'] is True
    assert request_data['retry_user_message_id'] == 'user-message-1'
    assert request_data['retry_thread_id'] == 'thread-1'
    assert resume_context['capability_origins']['image'] == 'discovery_approved'
    assert resume_context['selection_snapshot']['toggles'].get('image') is not True

    route_source = (
        REPO_ROOT / 'application' / 'single_app' / 'route_backend_chats.py'
    ).read_text(encoding='utf-8')
    assert (
        'def chat_api(server_request_data=None, server_resume_context=None):'
        in route_source
    )
    assert 'legacy_result = chat_api(data, resume_context)' in route_source
    compatibility_start = route_source.index(
        'def generate_compatibility_response():'
    )
    compatibility_end = route_source.index(
        'if compatibility_mode:',
        compatibility_start,
    )
    compatibility_source = route_source[compatibility_start:compatibility_end]
    assert '_complete_correlated_capability_resume_output(' in compatibility_source
    assert 'if resume_context and not correlated_output_persisted:' in (
        compatibility_source
    )
    assert 'persist_capability_resume_failure(' in compatibility_source
    assert 'external_retrieval_message = resolve_external_retrieval_message(' in route_source
    assert 'user_message=external_retrieval_message' in route_source

    state['messages'].set_item({
        'id': 'resumed-image-1',
        'conversation_id': 'conversation-owner',
        'role': 'image',
        'content': 'generated-image',
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
    assert reconciled['proposal']['resume']['assistant_message_id'] == 'resumed-image-1'


def test_selected_deep_research_resume_enables_web_with_selection_origin(
    capability_route_app,
):
    state = capability_route_app.config['capability_route_state']
    route_backend_chats = state['route_module']
    user_message, proposal_message = _proposal_documents()
    for message in (user_message, proposal_message):
        provenance = message['metadata']['capability_provenance']
        provenance['selection_snapshot']['toggles'].update({
            'deep_research': True,
            'source_review': True,
            'web_search': False,
        })
        provenance['effective_capabilities'] = [
            {'id': 'deep_research', 'origin': 'selection', 'required': True},
            {'id': 'web_search', 'origin': 'selection', 'required': True},
        ]
    proposal_message['metadata']['capability_resume_request'].update({
        'deep_research_enabled': True,
        'source_review_enabled': True,
        'web_search_enabled': False,
    })
    state['messages'].set_item(user_message)
    state['messages'].set_item(proposal_message)

    with capability_route_app.test_client() as client:
        response = _decision(
            client,
            option_id='continue_without_capabilities',
        )
    assert response.status_code == 200

    context = route_backend_chats._claim_authorized_capability_resume(
        settings={},
        user_id='user-owner',
        user_email='owner@example.com',
        user_roles=[],
        conversation_id='conversation-owner',
        proposal_id='proposal-1',
    )
    request_data = context['request_data']
    resume_context = context['capability_resume_context']
    assert request_data['deep_research_enabled'] is True
    assert request_data['source_review_enabled'] is True
    assert request_data['web_search_enabled'] is True
    assert resume_context['capability_origins']['deep_research'] == 'selection'
    assert resume_context['capability_origins']['web_search'] == 'selection'
    assert resume_context['selection_snapshot']['toggles']['deep_research'] is True
    assert resume_context['selection_snapshot']['toggles']['web_search'] is False


def test_automatic_deep_research_resume_uses_persisted_root_closure(
    capability_route_app,
    monkeypatch,
):
    state = capability_route_app.config['capability_route_state']
    route_backend_chats = state['route_module']
    user_message, proposal_message = _proposal_documents()
    for message in (user_message, proposal_message):
        provenance = message['metadata']['capability_provenance']
        provenance['automatic_capability_root_ids'] = ['deep_research']
        provenance['automatic_capability_effective_ids'] = [
            'deep_research',
            'web_search',
        ]
        provenance['effective_capabilities'] = [
            {'id': 'deep_research', 'origin': 'discovery_auto', 'required': True},
            {'id': 'web_search', 'origin': 'discovery_auto', 'required': True},
        ]
    state['messages'].set_item(user_message)
    state['messages'].set_item(proposal_message)

    def automatic_inventory(**kwargs):
        inventory = _inventory(
            selected_capability_ids=kwargs.get('selected_capability_ids'),
        )
        for capability_id in ('deep_research', 'web_search'):
            capability = next(
                entry
                for entry in inventory['capabilities']
                if entry['id'] == capability_id
            )
            capability.update({
                'auto_use_allowed': True,
                'requires_user_choice': False,
                'governance_mode': 'auto_read_only',
            })
        return inventory

    monkeypatch.setattr(
        route_backend_chats,
        '_resolve_server_chat_capability_inventory',
        automatic_inventory,
    )
    with capability_route_app.test_client() as client:
        response = _decision(
            client,
            option_id='continue_without_capabilities',
        )
    assert response.status_code == 200

    context = route_backend_chats._claim_authorized_capability_resume(
        settings={},
        user_id='user-owner',
        user_email='owner@example.com',
        user_roles=[],
        conversation_id='conversation-owner',
        proposal_id='proposal-1',
    )
    request_data = context['request_data']
    resume_context = context['capability_resume_context']
    assert request_data['deep_research_enabled'] is True
    assert request_data['source_review_enabled'] is True
    assert request_data['web_search_enabled'] is True
    assert resume_context['capability_origins']['deep_research'] == 'discovery_auto'
    assert resume_context['capability_origins']['web_search'] == 'discovery_auto'
    assert resume_context['automatic_capability_root_ids'] == ['deep_research']
    assert resume_context['automatic_capability_effective_ids'] == [
        'deep_research',
        'web_search',
    ]
    assert resume_context['selection_snapshot']['toggles']['deep_research'] is False
    assert resume_context['selection_snapshot']['toggles']['web_search'] is False


def test_selected_agent_invalidates_stale_image_option(
    capability_route_app,
    monkeypatch,
):
    state = capability_route_app.config['capability_route_state']
    route_backend_chats = state['route_module']
    canonical_agent = _governed_agent('selected-agent-id')
    user_message, proposal_message = _proposal_documents()
    _replace_builtin_proposal_option(state, 'image')
    proposal_message = copy.deepcopy(
        state['messages'].items[('conversation-owner', 'proposal-1')]
    )
    with capability_route_app.app_context():
        binding = route_backend_chats._build_selected_agent_resume_binding(
            canonical_agent
        )
    user_message['metadata']['capability_provenance']['selection_snapshot'][
        'agent_id'
    ] = canonical_agent['id']
    proposal_message['metadata']['capability_provenance']['selection_snapshot'][
        'agent_id'
    ] = canonical_agent['id']
    proposal_message['metadata']['capability_resume_request']['agent_info'] = binding
    state['messages'].set_item(user_message)
    state['messages'].set_item(proposal_message)
    monkeypatch.setattr(
        route_backend_chats,
        '_build_user_accessible_chat_agents',
        lambda *args, **kwargs: [canonical_agent],
    )

    with capability_route_app.test_client() as client:
        response = _decision(client, option_id='image')

    assert response.status_code == 409
    assert response.get_json()['code'] == 'capability_combination_unsupported'
    stored = state['messages'].items[('conversation-owner', 'proposal-1')]
    proposal = stored['metadata']['capability_proposal']
    assert proposal['status'] == 'invalidated'
    assert proposal['invalidation_reason'] == 'capability_combination_unsupported'


def test_execution_reauthorization_invalidates_revocation_after_claim(
    capability_route_app,
    monkeypatch,
):
    state = capability_route_app.config['capability_route_state']
    route_backend_chats = state['route_module']
    with capability_route_app.test_client() as client:
        approved = _decision(client)
    assert approved.status_code == 200

    original_loader = route_backend_chats._load_authorized_capability_proposal_context
    load_count = {'value': 0}

    def load_with_execution_revocation(**kwargs):
        context = original_loader(**kwargs)
        load_count['value'] += 1
        if load_count['value'] == 2:
            context['baseline_error_code'] = 'agent_missing'
        return context

    monkeypatch.setattr(
        route_backend_chats,
        '_load_authorized_capability_proposal_context',
        load_with_execution_revocation,
    )

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
    assert load_count['value'] == 2
    stored = state['messages'].items[('conversation-owner', 'proposal-1')]
    proposal = stored['metadata']['capability_proposal']
    assert proposal['status'] == 'invalidated'
    assert proposal['resume']['status'] == 'failed'
    assert proposal['invalidation_reason'] == 'agent_missing'


def test_execution_reauthorization_rejects_changed_claim_without_invalidation(
    capability_route_app,
    monkeypatch,
):
    state = capability_route_app.config['capability_route_state']
    route_backend_chats = state['route_module']
    with capability_route_app.test_client() as client:
        approved = _decision(client)
    assert approved.status_code == 200

    original_loader = route_backend_chats._load_authorized_capability_proposal_context
    load_count = {'value': 0}

    def load_with_reclaimed_execution(**kwargs):
        context = original_loader(**kwargs)
        load_count['value'] += 1
        if load_count['value'] == 2:
            context['proposal']['resume']['execution_id'] = 'newer-execution-id'
            stored = state['messages'].items[
                ('conversation-owner', 'proposal-1')
            ]
            stored['metadata']['capability_proposal']['resume'][
                'execution_id'
            ] = 'newer-execution-id'
        return context

    monkeypatch.setattr(
        route_backend_chats,
        '_load_authorized_capability_proposal_context',
        load_with_reclaimed_execution,
    )

    with pytest.raises(route_backend_chats.CapabilityChoiceError) as mismatch:
        route_backend_chats._claim_authorized_capability_resume(
            settings={},
            user_id='user-owner',
            user_email='owner@example.com',
            user_roles=[],
            conversation_id='conversation-owner',
            proposal_id='proposal-1',
        )

    assert mismatch.value.code == 'resume_claim_mismatch'
    assert load_count['value'] == 2
    stored = state['messages'].items[('conversation-owner', 'proposal-1')]
    proposal = stored['metadata']['capability_proposal']
    assert proposal['status'] == 'approved'
    assert proposal['resume']['status'] == 'running'
    assert proposal.get('invalidation_reason') is None


def test_post_claim_context_failure_releases_exact_resume_lease(
    capability_route_app,
    monkeypatch,
):
    state = capability_route_app.config['capability_route_state']
    route_backend_chats = state['route_module']
    with capability_route_app.test_client() as client:
        approved = _decision(client)
    assert approved.status_code == 200

    original_loader = route_backend_chats._load_authorized_capability_proposal_context
    load_count = {'value': 0}

    def fail_second_context_load(**kwargs):
        load_count['value'] += 1
        if load_count['value'] == 2:
            raise RuntimeError('simulated post-claim context failure')
        return original_loader(**kwargs)

    monkeypatch.setattr(
        route_backend_chats,
        '_load_authorized_capability_proposal_context',
        fail_second_context_load,
    )
    with pytest.raises(RuntimeError, match='post-claim context failure'):
        route_backend_chats._claim_authorized_capability_resume(
            settings={},
            user_id='user-owner',
            user_email='owner@example.com',
            user_roles=[],
            conversation_id='conversation-owner',
            proposal_id='proposal-1',
        )

    stored = state['messages'].items[('conversation-owner', 'proposal-1')]
    resume = stored['metadata']['capability_proposal']['resume']
    assert resume['status'] == 'failed'
    assert resume['lease_expires_at'] is None
    assert resume['error_type'] == 'runtimeerror'


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
    resume_context = claimed['capability_resume_context']
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


def test_stream_model_setup_failure_releases_resume_lease(
    capability_route_app,
    monkeypatch,
):
    state = capability_route_app.config['capability_route_state']
    route_backend_chats = state['route_module']
    with capability_route_app.test_client() as client:
        approved = _decision(client)
    assert approved.status_code == 200

    monkeypatch.setattr(
        route_backend_chats,
        'get_settings',
        lambda: {
            'enable_gpt_apim': True,
            'azure_apim_gpt_deployment': '',
        },
    )
    stream_metadata = {}
    stream_events = {}

    def initialize_stream_cache(cache_key, metadata, ttl_seconds=None):
        del ttl_seconds
        stream_metadata[cache_key] = copy.deepcopy(metadata)
        stream_events[cache_key] = []

    def set_stream_meta(cache_key, metadata, ttl_seconds=None):
        del ttl_seconds
        stream_metadata[cache_key] = copy.deepcopy(metadata)

    def append_stream_event(cache_key, event_text, ttl_seconds=None):
        del ttl_seconds
        stream_events.setdefault(cache_key, []).append(event_text)

    monkeypatch.setattr(
        route_backend_chats.app_settings_cache,
        'initialize_stream_session_cache',
        initialize_stream_cache,
    )
    monkeypatch.setattr(
        route_backend_chats.app_settings_cache,
        'get_stream_session_meta',
        lambda cache_key: copy.deepcopy(stream_metadata.get(cache_key)),
    )
    monkeypatch.setattr(
        route_backend_chats.app_settings_cache,
        'set_stream_session_meta',
        set_stream_meta,
    )
    monkeypatch.setattr(
        route_backend_chats.app_settings_cache,
        'append_stream_session_event',
        append_stream_event,
    )
    monkeypatch.setattr(
        route_backend_chats.app_settings_cache,
        'get_stream_session_events',
        lambda cache_key, start_index=0: list(
            stream_events.get(cache_key, [])[start_index:]
        ),
    )
    with capability_route_app.test_client() as client:
        response = client.post(
            '/api/chat/stream',
            json={
                'conversation_id': 'conversation-owner',
                'capability_resume_proposal_id': 'proposal-1',
            },
            buffered=True,
        )
        response_text = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'APIM deployment not configured' in response_text
    stored = state['messages'].items[('conversation-owner', 'proposal-1')]
    resume = stored['metadata']['capability_proposal']['resume']
    assert resume['status'] == 'failed'
    assert resume['lease_expires_at'] is None
    assert resume['error_type'] == 'stream_ended_before_resume_completion'


def test_stream_session_initialization_failure_releases_resume_lease(
    capability_route_app,
    monkeypatch,
):
    state = capability_route_app.config['capability_route_state']
    route_backend_chats = state['route_module']
    with capability_route_app.test_client() as client:
        approved = _decision(client)
    assert approved.status_code == 200

    monkeypatch.setattr(
        route_backend_chats.CHAT_STREAM_REGISTRY,
        'start_session',
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError('simulated stream-session failure')
        ),
    )
    with capability_route_app.test_client() as client:
        response = client.post(
            '/api/chat/stream',
            json={
                'conversation_id': 'conversation-owner',
                'capability_resume_proposal_id': 'proposal-1',
            },
        )

    assert response.status_code == 500
    assert response.get_json()['error'] == 'Failed to initialize chat stream'
    stored = state['messages'].items[('conversation-owner', 'proposal-1')]
    resume = stored['metadata']['capability_proposal']['resume']
    assert resume['status'] == 'failed'
    assert resume['lease_expires_at'] is None
    assert resume['error_type'] == 'runtimeerror'


def test_compatibility_mode_cannot_bypass_pending_clarification(
    capability_route_app,
    monkeypatch,
):
    state = capability_route_app.config['capability_route_state']
    route_backend_chats = state['route_module']
    pending = {
        'status': 'pending',
        'clarification_id': 'clarification-1',
        'expires_at': (
            datetime.now(timezone.utc) + timedelta(minutes=5)
        ).isoformat(),
    }
    monkeypatch.setattr(
        route_backend_chats,
        '_load_latest_chat_clarification_context',
        lambda **kwargs: {
            'context_state': {},
            'latest_user_message': {'id': 'user-message-1'},
            'clarification': pending,
        },
    )
    monkeypatch.setattr(
        route_backend_chats,
        'validate_chat_clarification_source',
        lambda *args, **kwargs: {'id': 'source-user-message'},
    )

    with capability_route_app.test_client() as client:
        image_response = client.post(
            '/api/chat/stream',
            json={
                'conversation_id': 'conversation-owner',
                'message': 'Virginia',
                'image_generation': True,
            },
        )
        retry_response = client.post(
            '/api/chat/stream',
            json={
                'conversation_id': 'conversation-owner',
                'message': 'Retry another turn.',
                'retry_user_message_id': 'unrelated-user-message',
            },
        )

    assert image_response.status_code == 409
    assert image_response.get_json()['code'] == 'clarification_pending'
    assert retry_response.status_code == 409
    assert retry_response.get_json()['code'] == 'clarification_pending'


def test_pending_clarification_blocks_all_chat_execution_routes(
    capability_route_app,
    monkeypatch,
):
    state = capability_route_app.config['capability_route_state']
    route_backend_chats = state['route_module']

    def reject_pending_clarification(**kwargs):
        del kwargs
        raise route_backend_chats.ChatClarificationError(
            'answer the pending clarification first',
            code='clarification_pending',
        )

    monkeypatch.setattr(
        route_backend_chats,
        '_preflight_chat_clarification',
        reject_pending_clarification,
    )
    monkeypatch.setattr(
        route_backend_chats,
        'image_generation_is_enabled',
        lambda settings: True,
    )
    requests = (
        ('/api/chat', {'message': 'Run directly.'}),
        (
            '/api/chat/document-action',
            {
                'message': 'Analyze this.',
                'document_action': {'type': 'analyze'},
            },
        ),
        (
            '/api/chat/document-action/stream',
            {
                'message': 'Analyze this.',
                'document_action': {'type': 'analyze'},
            },
        ),
        ('/api/chat/analyze', {'message': 'Analyze this.'}),
        ('/api/chat/analyze/stream', {'message': 'Analyze this.'}),
        (
            '/api/chat/image-proposals/generate',
            {'prompt': 'Generate an image.'},
        ),
    )

    with capability_route_app.test_client() as client:
        responses = [
            client.post(
                endpoint,
                json={
                    'conversation_id': 'conversation-owner',
                    **payload,
                },
            )
            for endpoint, payload in requests
        ]

    assert [response.status_code for response in responses] == [409] * len(
        requests
    )
    assert all(
        response.get_json()['code'] == 'clarification_pending'
        for response in responses
    )


def test_clarification_preflight_allows_only_normal_answer_or_exact_retry(
    capability_route_app,
    monkeypatch,
):
    state = capability_route_app.config['capability_route_state']
    route_backend_chats = state['route_module']
    response_text = 'Virginia'
    pending = {
        'status': 'pending',
        'clarification_id': 'clarification-1',
        'expires_at': (
            datetime.now(timezone.utc) + timedelta(minutes=5)
        ).isoformat(),
        '_response_user_message_id': None,
        '_response_hash': None,
    }
    context = {
        'context_state': {},
        'latest_user_message': {'id': 'source-user-message'},
        'clarification': pending,
    }
    monkeypatch.setattr(
        route_backend_chats,
        '_load_latest_chat_clarification_context',
        lambda **kwargs: copy.deepcopy(context),
    )
    validated = []
    monkeypatch.setattr(
        route_backend_chats,
        'validate_chat_clarification_source',
        lambda *args, **kwargs: validated.append(kwargs['clarification']),
    )

    allowed = route_backend_chats._preflight_chat_clarification(
        conversation_id='conversation-owner',
        user_message=response_text,
        allow_pending_response=True,
    )
    assert allowed['clarification']['status'] == 'pending'
    with pytest.raises(route_backend_chats.ChatClarificationError) as blocked:
        route_backend_chats._preflight_chat_clarification(
            conversation_id='conversation-owner',
            user_message=response_text,
        )
    assert blocked.value.code == 'clarification_pending'

    context['clarification'] = {
        'status': 'resolving',
        'clarification_id': 'clarification-1',
        'expires_at': (
            datetime.now(timezone.utc) + timedelta(minutes=5)
        ).isoformat(),
        '_response_user_message_id': 'clarification-response-user',
        '_response_thread_id': 'clarification-response-thread',
        '_source_thread_id': 'source-thread',
        '_response_hash': hashlib.sha256(
            response_text.encode('utf-8')
        ).hexdigest(),
    }
    context['latest_user_message'] = {
        'id': 'clarification-response-user',
    }
    state['messages'].set_item({
        'id': 'clarification-response-user',
        'conversation_id': 'conversation-owner',
        'role': 'user',
        'content': response_text,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'metadata': {
            'thread_info': {
                'thread_id': 'clarification-response-thread',
                'previous_thread_id': 'source-thread',
                'active_thread': True,
            },
        },
    })
    exact_retry = route_backend_chats._preflight_chat_clarification(
        conversation_id='conversation-owner',
        user_message=response_text,
        retry_user_message_id='clarification-response-user',
        allow_exact_response_retry=True,
    )
    assert exact_retry['exact_response_retry'] is True
    with pytest.raises(route_backend_chats.ChatClarificationError) as mismatch:
        route_backend_chats._preflight_chat_clarification(
            conversation_id='conversation-owner',
            user_message=response_text,
            retry_user_message_id='different-user-message',
            allow_exact_response_retry=True,
        )
    assert mismatch.value.code == 'clarification_pending'
    assert len(validated) == 4


def test_preflight_terminalizes_malformed_claimed_response_rows(
    capability_route_app,
):
    state = capability_route_app.config['capability_route_state']
    route_backend_chats = state['route_module']

    for malformed_kwargs in (
        {'blank_response': True},
        {'missing_response_thread': True},
    ):
        source, checkpoint, response = _claimed_clarification_documents(
            **malformed_kwargs
        )
        for message in (source, checkpoint, response):
            state['messages'].set_item(message)

        with pytest.raises(
            route_backend_chats.ChatClarificationError
        ) as rejected:
            route_backend_chats._preflight_chat_clarification(
                conversation_id='conversation-owner',
                user_message='Virginia',
                retry_user_message_id='clarification-response-user',
                allow_exact_response_retry=True,
            )

        assert rejected.value.code == (
            'clarification_response_claim_mismatch'
        )
        stored = state['messages'].items[
            ('conversation-owner', 'clarification-checkpoint')
        ]
        stored_clarification = stored['metadata']['chat_clarification']
        assert stored_clarification['status'] == 'expired'
        assert stored_clarification['invalidation_reason'] == (
            'clarification_response_claim_mismatch'
        )
        assert stored['metadata']['awaiting_user_clarification'] is False


def test_preflight_terminalizes_invalid_clarification_source(
    capability_route_app,
):
    state = capability_route_app.config['capability_route_state']
    route_backend_chats = state['route_module']
    source, checkpoint, response = _claimed_clarification_documents(
        masked_source=True
    )
    for message in (source, checkpoint, response):
        state['messages'].set_item(message)

    with pytest.raises(
        route_backend_chats.ChatClarificationError
    ) as rejected:
        route_backend_chats._preflight_chat_clarification(
            conversation_id='conversation-owner',
            user_message='Virginia',
            retry_user_message_id='clarification-response-user',
            allow_exact_response_retry=True,
        )

    assert rejected.value.code == 'clarification_source_invalid'
    stored = state['messages'].items[
        ('conversation-owner', 'clarification-checkpoint')
    ]
    stored_clarification = stored['metadata']['chat_clarification']
    assert stored_clarification['status'] == 'expired'
    assert stored_clarification['invalidation_reason'] == (
        'clarification_source_invalid'
    )
    assert stored['metadata']['awaiting_user_clarification'] is False


def test_preflight_preserves_live_unmaterialized_clarification_claim(
    capability_route_app,
):
    state = capability_route_app.config['capability_route_state']
    route_backend_chats = state['route_module']
    source, checkpoint, _ = _claimed_clarification_documents()
    for message in (source, checkpoint):
        state['messages'].set_item(message)

    with pytest.raises(
        route_backend_chats.ChatClarificationError
    ) as rejected:
        route_backend_chats._preflight_chat_clarification(
            conversation_id='conversation-owner',
            user_message='Virginia',
        )

    assert rejected.value.code == 'clarification_response_in_progress'
    stored = state['messages'].items[
        ('conversation-owner', 'clarification-checkpoint')
    ]
    stored_clarification = stored['metadata']['chat_clarification']
    assert stored_clarification['status'] == 'resolving'
    assert stored_clarification.get('invalidation_reason') is None
    assert stored['metadata']['awaiting_user_clarification'] is True


def test_expected_clarification_cannot_downgrade_after_resolution(
    capability_route_app,
):
    state = capability_route_app.config['capability_route_state']
    route_backend_chats = state['route_module']
    source, checkpoint, response = _claimed_clarification_documents()
    checkpoint['metadata']['chat_clarification'].update({
        'status': 'resolved',
        'resolved_at': datetime.now(timezone.utc).isoformat(),
        'lease_expires_at': None,
    })
    checkpoint['metadata']['awaiting_user_clarification'] = False
    for message in (source, checkpoint, response):
        state['messages'].set_item(message)

    with pytest.raises(
        route_backend_chats.ChatClarificationError
    ) as rejected:
        route_backend_chats._preflight_chat_clarification(
            conversation_id='conversation-owner',
            user_message='Virginia',
            allow_pending_response=True,
            expected_clarification_id='clarification-checkpoint',
        )

    assert rejected.value.code == 'clarification_response_conflict'


def test_expired_exact_retry_cannot_downgrade_to_fresh_turn(
    capability_route_app,
):
    state = capability_route_app.config['capability_route_state']
    route_backend_chats = state['route_module']
    source, checkpoint, response = _claimed_clarification_documents()
    checkpoint['metadata']['chat_clarification'].update({
        'status': 'expired',
        'expired_at': datetime.now(timezone.utc).isoformat(),
        'lease_expires_at': None,
    })
    checkpoint['metadata']['awaiting_user_clarification'] = False
    for message in (source, checkpoint, response):
        state['messages'].set_item(message)

    with pytest.raises(
        route_backend_chats.ChatClarificationError
    ) as rejected:
        route_backend_chats._preflight_chat_clarification(
            conversation_id='conversation-owner',
            user_message='Virginia',
            retry_user_message_id='clarification-response-user',
            allow_exact_response_retry=True,
        )

    assert rejected.value.code == 'clarification_expired'


def test_edited_terminal_retry_cannot_downgrade_to_fresh_turn(
    capability_route_app,
):
    state = capability_route_app.config['capability_route_state']
    route_backend_chats = state['route_module']

    for terminal_status, expected_code in (
        ('resolved', 'clarification_response_conflict'),
        ('expired', 'clarification_expired'),
    ):
        source, checkpoint, response = _claimed_clarification_documents()
        checkpoint['metadata']['chat_clarification'].update({
            'status': terminal_status,
            'lease_expires_at': None,
        })
        checkpoint['metadata']['awaiting_user_clarification'] = False
        for message in (source, checkpoint, response):
            state['messages'].set_item(message)

        with pytest.raises(
            route_backend_chats.ChatClarificationError
        ) as rejected:
            route_backend_chats._preflight_chat_clarification(
                conversation_id='conversation-owner',
                user_message='Edited Virginia answer',
                retry_user_message_id='clarification-response-user',
                allow_exact_response_retry=True,
            )

        assert rejected.value.code == expected_code


def test_non_latest_clarification_response_retry_targets_exact_checkpoint(
    capability_route_app,
    monkeypatch,
):
    state = capability_route_app.config['capability_route_state']
    route_backend_chats = state['route_module']
    monkeypatch.setattr(
        route_backend_chats,
        '_load_latest_chat_clarification_context',
        lambda **kwargs: (_ for _ in ()).throw(
            route_backend_chats.ChatClarificationError(
                'unrelated latest clarification is ambiguous',
                code='clarification_ambiguous',
            )
        ),
    )

    for checkpoint_status in ('resolving', 'resolved'):
        source, checkpoint, response = _claimed_clarification_documents()
        checkpoint['metadata']['chat_clarification']['status'] = (
            checkpoint_status
        )
        if checkpoint_status == 'resolved':
            checkpoint['metadata']['chat_clarification'].update({
                'resolved_at': datetime.now(timezone.utc).isoformat(),
                'lease_expires_at': None,
            })
            checkpoint['metadata']['awaiting_user_clarification'] = False
        later_user = {
            'id': 'later-unrelated-user',
            'conversation_id': 'conversation-owner',
            'role': 'user',
            'content': 'A later unrelated request.',
            'timestamp': (
                datetime.now(timezone.utc) + timedelta(minutes=1)
            ).isoformat(),
            'metadata': {
                'thread_info': {
                    'thread_id': 'later-thread',
                    'previous_thread_id': 'clarification-response-thread',
                    'active_thread': True,
                    'thread_attempt': 1,
                },
            },
        }
        for message in (source, checkpoint, response, later_user):
            state['messages'].set_item(message)

        preflight = route_backend_chats._preflight_chat_clarification(
            conversation_id='conversation-owner',
            user_message='Virginia',
            retry_user_message_id='clarification-response-user',
            allow_exact_response_retry=True,
        )

        assert preflight['exact_response_retry'] is True
        assert preflight['latest_user_message']['id'] == (
            'clarification-response-user'
        )
        assert preflight['clarification']['status'] == checkpoint_status


def test_recovery_etag_conflict_preserves_mask_and_invalidates(
    capability_route_app,
    monkeypatch,
):
    state = capability_route_app.config['capability_route_state']
    route_backend_chats = state['route_module']
    source, checkpoint, response = _claimed_clarification_documents()
    for message in (source, checkpoint, response):
        state['messages'].set_item(message)
    claimed = checkpoint['metadata']['chat_clarification']
    response_document = state['messages'].read_item(
        item='clarification-response-user',
        partition_key='conversation-owner',
    )
    original_replace_item = state['messages'].replace_item
    conflict_injected = {'value': False}

    def replace_with_concurrent_mask(**kwargs):
        if (
            kwargs.get('item') == 'clarification-response-user'
            and not conflict_injected['value']
        ):
            conflict_injected['value'] = True
            masked_response = state['messages'].read_item(
                item='clarification-response-user',
                partition_key='conversation-owner',
            )
            masked_response['metadata']['masked'] = True
            state['messages'].set_item(masked_response)
            raise ConditionalConflict()
        return original_replace_item(**kwargs)

    monkeypatch.setattr(
        state['messages'],
        'replace_item',
        replace_with_concurrent_mask,
    )

    with pytest.raises(
        route_backend_chats.ChatClarificationError
    ) as rejected:
        route_backend_chats._persist_claimed_clarification_response_metadata(
            response_document,
            claimed,
            conversation_id='conversation-owner',
            desired_metadata={'model_selection': {'selected_model': 'test'}},
        )

    assert rejected.value.code == 'clarification_response_claim_mismatch'
    stored_response = state['messages'].items[
        ('conversation-owner', 'clarification-response-user')
    ]
    assert stored_response['metadata']['masked'] is True
    assert 'model_selection' not in stored_response['metadata']
    stored_checkpoint = state['messages'].items[
        ('conversation-owner', 'clarification-checkpoint')
    ]
    stored_clarification = stored_checkpoint['metadata'][
        'chat_clarification'
    ]
    assert stored_clarification['status'] == 'expired'
    assert stored_clarification['invalidation_reason'] == (
        'clarification_response_claim_mismatch'
    )


def test_recovery_physical_deletion_invalidates_without_recreation(
    capability_route_app,
    monkeypatch,
):
    state = capability_route_app.config['capability_route_state']
    route_backend_chats = state['route_module']
    source, checkpoint, response = _claimed_clarification_documents()
    for message in (source, checkpoint, response):
        state['messages'].set_item(message)
    claimed = checkpoint['metadata']['chat_clarification']
    response_document = state['messages'].read_item(
        item='clarification-response-user',
        partition_key='conversation-owner',
    )
    original_replace_item = state['messages'].replace_item

    def replace_after_deletion(**kwargs):
        if kwargs.get('item') == 'clarification-response-user':
            state['messages'].items.pop(
                ('conversation-owner', 'clarification-response-user'),
                None,
            )
            raise DummyNotFoundError('clarification-response-user')
        return original_replace_item(**kwargs)

    monkeypatch.setattr(
        state['messages'],
        'replace_item',
        replace_after_deletion,
    )

    with pytest.raises(
        route_backend_chats.ChatClarificationError
    ) as rejected:
        route_backend_chats._persist_claimed_clarification_response_metadata(
            response_document,
            claimed,
            conversation_id='conversation-owner',
            desired_metadata={'model_selection': {'selected_model': 'test'}},
        )

    assert rejected.value.code == 'clarification_response_claim_mismatch'
    assert (
        'conversation-owner',
        'clarification-response-user',
    ) not in state['messages'].items
    stored_checkpoint = state['messages'].items[
        ('conversation-owner', 'clarification-checkpoint')
    ]
    stored_clarification = stored_checkpoint['metadata'][
        'chat_clarification'
    ]
    assert stored_clarification['status'] == 'expired'
    assert stored_clarification['invalidation_reason'] == (
        'clarification_response_claim_mismatch'
    )


def test_preflight_finds_pending_checkpoint_with_filtered_source(
    capability_route_app,
):
    state = capability_route_app.config['capability_route_state']
    route_backend_chats = state['route_module']
    source, checkpoint, _ = _claimed_clarification_documents(
        masked_source=True
    )
    clarification = checkpoint['metadata']['chat_clarification']
    clarification.update({
        'status': 'pending',
        'child_run_id': None,
        'claimed_at': None,
        'lease_expires_at': None,
        '_response_user_message_id': None,
        '_response_thread_id': None,
        '_response_hash': None,
    })
    for message in (source, checkpoint):
        state['messages'].set_item(message)

    with pytest.raises(
        route_backend_chats.ChatClarificationError
    ) as rejected:
        route_backend_chats._preflight_chat_clarification(
            conversation_id='conversation-owner',
            user_message='Start another action.',
        )

    assert rejected.value.code == 'clarification_source_invalid'
    stored = state['messages'].items[
        ('conversation-owner', 'clarification-checkpoint')
    ]
    stored_clarification = stored['metadata']['chat_clarification']
    assert stored_clarification['status'] == 'expired'
    assert stored_clarification['invalidation_reason'] == (
        'clarification_source_invalid'
    )


def test_resolved_source_thread_checkpoint_is_not_pending(
    capability_route_app,
):
    state = capability_route_app.config['capability_route_state']
    route_backend_chats = state['route_module']
    source, checkpoint, _ = _claimed_clarification_documents()
    clarification = checkpoint['metadata']['chat_clarification']
    clarification.update({
        'status': 'resolved',
        'lease_expires_at': None,
        'resolved_at': datetime.now(timezone.utc).isoformat(),
    })
    checkpoint['metadata']['awaiting_user_clarification'] = False
    for message in (source, checkpoint):
        state['messages'].set_item(message)

    preflight = route_backend_chats._preflight_chat_clarification(
        conversation_id='conversation-owner',
        user_message='Start a new request.',
    )

    assert preflight['clarification'] is None
    assert preflight['exact_response_retry'] is False


def test_exact_clarification_response_retry_leaves_compatibility_bridge(
    capability_route_app,
    monkeypatch,
):
    state = capability_route_app.config['capability_route_state']
    route_backend_chats = state['route_module']
    response_text = 'Virginia'
    resolved = {
        'status': 'resolved',
        '_response_user_message_id': 'clarification-response-user',
        '_response_hash': hashlib.sha256(
            response_text.encode('utf-8')
        ).hexdigest(),
    }
    monkeypatch.setattr(
        route_backend_chats,
        '_load_latest_chat_clarification_context',
        lambda **kwargs: {
            'context_state': {},
            'latest_user_message': {
                'id': 'clarification-response-user',
            },
            'clarification': resolved,
        },
    )
    monkeypatch.setattr(
        route_backend_chats,
        'validate_chat_clarification_source',
        lambda *args, **kwargs: {'id': 'source-user-message'},
    )
    monkeypatch.setattr(
        route_backend_chats.CHAT_STREAM_REGISTRY,
        'start_session',
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError('normal-generator-route-selected')
        ),
    )

    with capability_route_app.test_client() as client:
        response = client.post(
            '/api/chat/stream',
            json={
                'conversation_id': 'conversation-owner',
                'message': response_text,
                'retry_user_message_id': 'clarification-response-user',
            },
        )

    assert response.status_code == 500
    assert response.get_json()['error'] == 'Failed to initialize chat stream'


def test_persisted_safety_reconciles_process_loss_without_reexecution(
    capability_route_app,
):
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
    resume_context = claimed['capability_resume_context']
    state['messages'].set_item({
        'id': 'resumed-safety-1',
        'conversation_id': 'conversation-owner',
        'role': 'safety',
        'content': 'Blocked by content safety.',
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
    assert reconciled['proposal']['resume']['assistant_message_id'] == 'resumed-safety-1'

    route_source = (
        REPO_ROOT / 'application' / 'single_app' / 'route_backend_chats.py'
    ).read_text(encoding='utf-8')
    safety_start = route_source.index("if blocked:\n                            # Upsert to safety container")
    safety_end = route_source.index(
        'except HttpResponseError as e:',
        safety_start,
    )
    safety_source = route_source[safety_start:safety_end]
    assert "['capability_resume']" in safety_source
    assert 'complete_stream_capability_resume(assistant_message_id)' in safety_source

    compatibility_safety_start = route_source.index(
        "safety_doc.setdefault('metadata', {})['capability_provenance']"
    )
    compatibility_safety_end = route_source.index(
        'cosmos_messages_container.upsert_item(safety_doc)',
        compatibility_safety_start,
    )
    compatibility_safety_source = route_source[
        compatibility_safety_start:compatibility_safety_end
    ]
    assert "safety_doc['metadata']['capability_resume']" in (
        compatibility_safety_source
    )

    partial_failure_start = route_source.index(
        'except Exception as e:\n                    error_msg = str(e)'
    )
    partial_failure_end = route_source.index(
        'partial_error_payload = {',
        partial_failure_start,
    )
    partial_failure_source = route_source[
        partial_failure_start:partial_failure_end
    ]
    assert "'capability_resume': (" in partial_failure_source
    assert 'cosmos_messages_container.upsert_item(assistant_doc)' in (
        partial_failure_source
    )
    assert 'complete_stream_capability_resume(assistant_message_id)' in (
        partial_failure_source
    )
    partial_error_start = route_source.index(
        'partial_error_payload = {',
        partial_failure_start,
    )
    partial_error_end = route_source.index(
        'yield f"data: {json.dumps(partial_error_payload)}',
        partial_error_start,
    )
    partial_error_source = route_source[
        partial_error_start:partial_error_end
    ]
    assert "'metadata': project_chat_metadata_for_client({" in (
        partial_error_source
    )
    assert 'fail_stream_capability_resume(type(e).__name__)' not in (
        partial_failure_source
    )

    cancellation_start = route_source.index(
        'def finalize_cancelled_stream_response():'
    )
    cancellation_end = route_source.index(
        'if stream_cancel_requested():',
        cancellation_start,
    )
    cancellation_source = route_source[cancellation_start:cancellation_end]
    cancellation_correlation_index = cancellation_source.index(
        "'capability_resume': ("
    )
    cancellation_upsert_index = cancellation_source.index(
        'cosmos_messages_container.upsert_item(assistant_doc)'
    )
    cancellation_completion_index = cancellation_source.index(
        'complete_stream_capability_resume(assistant_message_id)'
    )
    assert cancellation_correlation_index < cancellation_upsert_index
    assert cancellation_upsert_index < cancellation_completion_index

    document_runtime_start = route_source.index(
        'except Exception as runtime_error:',
        route_source.index("document_action_reply = execution_result.get('reply', '')"),
    )
    document_runtime_end = route_source.index(
        "prepared_agent_citations = persist_agent_citation_artifacts(",
        route_source.index('}, 409', document_runtime_start),
    )
    document_runtime_source = route_source[
        document_runtime_start:document_runtime_end
    ]
    assert "'capability_resume': (" in document_runtime_source
    assert 'cosmos_messages_container.upsert_item(partial_assistant_doc)' in (
        document_runtime_source
    )
    assert "'message_id': partial_message_id" in document_runtime_source

    document_stream_start = route_source.index(
        "@bp.route('/api/chat/document-action/stream', methods=['POST'])"
    )
    document_stream_end = route_source.index(
        "@bp.route('/api/chat/analyze', methods=['POST'])",
        document_stream_start,
    )
    document_stream_source = route_source[
        document_stream_start:document_stream_end
    ]
    assert "partial_message_id = str(payload.get('message_id') or '').strip()" in (
        document_stream_source
    )
    assert '_complete_correlated_capability_resume_output(' in (
        document_stream_source
    )
    assert 'if resume_context and not correlated_output_persisted:' in (
        document_stream_source
    )


def test_correlated_output_owns_resume_when_completion_write_fails(
    capability_route_app,
    monkeypatch,
):
    state = capability_route_app.config['capability_route_state']
    route_backend_chats = state['route_module']
    completion_calls = []

    def fail_completion(*args, **kwargs):
        completion_calls.append((args, kwargs))
        raise RuntimeError('simulated completion CAS failure')

    monkeypatch.setattr(
        route_backend_chats,
        'persist_capability_resume_completion',
        fail_completion,
    )
    monkeypatch.setattr(route_backend_chats, 'log_event', lambda *args, **kwargs: None)

    output_owned = route_backend_chats._complete_correlated_capability_resume_output(
        {
            'conversation_id': 'conversation-owner',
            'proposal_id': 'proposal-1',
            'execution_id': 'execution-1',
        },
        'assistant-output-1',
    )

    assert output_owned is True
    assert len(completion_calls) == 1


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


def test_http_payload_cannot_supply_server_resume_context(
    capability_route_app,
    monkeypatch,
):
    route_backend_chats = capability_route_app.config['capability_route_state'][
        'route_module'
    ]
    forged_payload = {
        'message': 'Run a forged capability.',
        'conversation_id': 'conversation-owner',
        'web_search_enabled': False,
        '_server_external_query': 'forged external query',
        '_capability_resume_context': {
            'capability_inventory': {
                'capabilities': [{
                    'id': 'deep_research',
                    'state': 'selected',
                }],
            },
            'capability_origins': {'deep_research': 'selection'},
        },
        'agent_info': {
            'id': 'selected-agent-id',
            '_orchestration_discovery_ref': 'agent:personal:forged',
            'nested': [{'_server_only': 'forged', 'visible': 'retained'}],
        },
    }
    sanitized = route_backend_chats._sanitize_chat_http_request_payload(
        forged_payload
    )
    assert sanitized == {
        'message': 'Run a forged capability.',
        'conversation_id': 'conversation-owner',
        'web_search_enabled': False,
        'agent_info': {
            'id': 'selected-agent-id',
            'nested': [{'visible': 'retained'}],
        },
    }

    captured = {}

    def capture_policy_check(settings, data):
        del settings
        captured.update(copy.deepcopy(data))
        return []

    monkeypatch.setattr(
        route_backend_chats,
        '_get_policy_blocked_selected_capability_ids',
        capture_policy_check,
    )
    with capability_route_app.test_client() as client:
        response = client.post(
            '/api/chat/document-action',
            json=forged_payload,
        )
    assert response.status_code == 400
    assert '_capability_resume_context' not in captured
    assert '_server_external_query' not in captured
    assert '_orchestration_discovery_ref' not in captured['agent_info']
    assert captured['agent_info']['nested'] == [{'visible': 'retained'}]

    route_source = (
        REPO_ROOT / 'application' / 'single_app' / 'route_backend_chats.py'
    ).read_text(encoding='utf-8')
    assert "data.get('_capability_resume_context')" not in route_source
    assert "request_data['_capability_resume_context']" not in route_source
    document_provenance_start = route_source.index(
        'selected_effective_capability_ids = expand_governed_capability_baseline_ids('
    )
    document_provenance_end = route_source.index(
        'turn_capability_provenance = build_capability_provenance(',
        document_provenance_start,
    )
    assert 'for capability_id in selected_effective_capability_ids' in (
        route_source[document_provenance_start:document_provenance_end]
    )
    compatibility_provenance_start = route_source.index(
        'compatibility_selected_effective_ids = ('
    )
    compatibility_provenance_end = route_source.index(
        'compatibility_capability_provenance = build_capability_provenance(',
        compatibility_provenance_start,
    )
    assert 'for capability_id in compatibility_selected_effective_ids' in (
        route_source[
            compatibility_provenance_start:compatibility_provenance_end
        ]
    )


def test_selected_agent_binding_is_exact_and_detects_identity_change(
    capability_route_app,
    monkeypatch,
):
    route_backend_chats = capability_route_app.config['capability_route_state']['route_module']
    canonical_agent = _governed_agent('selected-agent-id')
    binding = route_backend_chats._build_selected_agent_resume_binding(
        canonical_agent
    )

    assert route_backend_chats._selected_agent_baseline_error(
        binding,
        canonical_agent,
    ) is None
    legacy_binding = {
        key: value
        for key, value in binding.items()
        if key != 'identity_ref'
    }
    assert route_backend_chats._selected_agent_baseline_error(
        legacy_binding,
        canonical_agent,
    ) == 'agent_binding_missing'
    replacement = copy.deepcopy(canonical_agent)
    replacement['created_at'] = '2026-07-16T12:00:00+00:00'
    assert route_backend_chats._selected_agent_baseline_error(
        binding,
        replacement,
    ) == 'agent_policy_changed'
    disabled = copy.deepcopy(canonical_agent)
    disabled['is_enabled'] = False
    assert route_backend_chats._selected_agent_baseline_error(
        binding,
        disabled,
    ) == 'agent_policy_blocked'

    same_name_different_id = copy.deepcopy(canonical_agent)
    same_name_different_id['id'] = 'different-agent-id'
    monkeypatch.setattr(
        route_backend_chats,
        '_build_user_accessible_chat_agents',
        lambda *args, **kwargs: [same_name_different_id],
    )
    assert route_backend_chats._resolve_canonical_chat_agent(
        'user-owner',
        {},
        binding,
    ) is None

    monkeypatch.setattr(
        route_backend_chats,
        '_build_user_accessible_chat_agents',
        lambda *args, **kwargs: [canonical_agent],
    )
    monkeypatch.setattr(
        route_backend_chats,
        'ensure_governance_access',
        lambda *args, **kwargs: (_ for _ in ()).throw(PermissionError('blocked')),
    )
    assert route_backend_chats._resolve_canonical_chat_agent(
        'user-owner',
        {},
        binding,
    ) is None


def test_selected_agent_deletion_atomically_invalidates_decision(
    capability_route_app,
    monkeypatch,
):
    state = capability_route_app.config['capability_route_state']
    route_backend_chats = state['route_module']
    canonical_agent = _governed_agent('selected-agent-id')
    user_message, proposal_message = _proposal_documents()
    with capability_route_app.app_context():
        proposal_message['metadata']['capability_resume_request']['agent_info'] = (
            route_backend_chats._build_selected_agent_resume_binding(
                canonical_agent
            )
        )
    state['messages'].set_item(user_message)
    state['messages'].set_item(proposal_message)
    monkeypatch.setattr(
        route_backend_chats,
        '_build_user_accessible_chat_agents',
        lambda *args, **kwargs: [],
    )

    with capability_route_app.test_client() as client:
        response = _decision(client)

    assert response.status_code == 409
    assert response.get_json()['code'] == 'agent_missing'
    stored = state['messages'].items[('conversation-owner', 'proposal-1')]
    proposal = stored['metadata']['capability_proposal']
    assert proposal['status'] == 'invalidated'
    assert proposal['invalidation_reason'] == 'agent_missing'


def test_selected_agent_snapshot_without_binding_atomically_invalidates(
    capability_route_app,
):
    state = capability_route_app.config['capability_route_state']
    user_message, proposal_message = _proposal_documents()
    user_message['metadata']['capability_provenance']['selection_snapshot'][
        'agent_id'
    ] = 'legacy-selected-agent'
    proposal_message['metadata']['capability_provenance']['selection_snapshot'][
        'agent_id'
    ] = 'legacy-selected-agent'
    proposal_message['metadata']['capability_resume_request']['agent_info'] = None
    state['messages'].set_item(user_message)
    state['messages'].set_item(proposal_message)

    with capability_route_app.test_client() as client:
        response = _decision(client)

    assert response.status_code == 409
    assert response.get_json()['code'] == 'agent_binding_missing'
    stored = state['messages'].items[('conversation-owner', 'proposal-1')]
    proposal = stored['metadata']['capability_proposal']
    assert proposal['status'] == 'invalidated'
    assert proposal['invalidation_reason'] == 'agent_binding_missing'


def test_selected_scope_and_document_drift_atomically_invalidate_decision(
    capability_route_app,
):
    state = capability_route_app.config['capability_route_state']
    user_message, scoped_proposal = _proposal_documents()
    scoped_proposal['metadata']['capability_resume_request']['active_group_ids'] = [
        'group-1'
    ]
    state['messages'].set_item(user_message)
    state['messages'].set_item(scoped_proposal)

    with capability_route_app.test_client() as client:
        scope_response = _decision(client)

    assert scope_response.status_code == 409
    assert scope_response.get_json()['code'] == 'capability_scope_unauthorized'
    stored_scope = state['messages'].items[('conversation-owner', 'proposal-1')]
    assert stored_scope['metadata']['capability_proposal']['status'] == 'invalidated'

    user_message, document_proposal = _proposal_documents()
    document_proposal['metadata']['capability_resume_request'][
        'selected_document_ids'
    ] = ['document-1']
    state['messages'].set_item(user_message)
    state['messages'].set_item(document_proposal)

    with capability_route_app.test_client() as client:
        document_response = _decision(client)

    assert document_response.status_code == 409
    assert document_response.get_json()['code'] == 'capability_document_unauthorized'
    stored_document = state['messages'].items[('conversation-owner', 'proposal-1')]
    assert stored_document['metadata']['capability_proposal']['status'] == 'invalidated'


def test_public_scope_requires_current_workspace_and_chat_status(
    capability_route_app,
    monkeypatch,
):
    route_backend_chats = capability_route_app.config['capability_route_state']['route_module']
    workspace_docs = {
        'public-active': {'id': 'public-active', 'status': 'active'},
        'public-inactive': {'id': 'public-inactive', 'status': 'inactive'},
        'public-unknown': {'id': 'public-unknown', 'status': 'unexpected'},
    }
    monkeypatch.setattr(
        route_backend_chats,
        'get_user_visible_public_workspace_ids_from_settings',
        lambda user_id: [
            'public-active',
            'public-inactive',
            'public-unknown',
            'public-deleted',
        ],
    )
    monkeypatch.setattr(
        route_backend_chats,
        'find_public_workspace_by_id',
        lambda workspace_id: copy.deepcopy(workspace_docs.get(workspace_id)),
    )

    allowed_workspace_ids = route_backend_chats._get_chat_allowed_public_workspace_ids(
        'user-owner',
        [
            'public-active',
            'public-inactive',
            'public-unknown',
            'public-deleted',
        ],
    )

    assert allowed_workspace_ids == ['public-active']


def test_group_scope_and_group_agent_require_current_chat_status(
    capability_route_app,
    monkeypatch,
):
    route_backend_chats = capability_route_app.config['capability_route_state']['route_module']
    groups = {
        'group-active': {'id': 'group-active', 'status': 'active', 'name': 'Active'},
        'group-inactive': {'id': 'group-inactive', 'status': 'inactive', 'name': 'Inactive'},
        'group-unknown': {'id': 'group-unknown', 'status': 'unexpected', 'name': 'Unknown'},
    }
    monkeypatch.setattr(
        route_backend_chats,
        'find_group_by_id',
        lambda group_id: copy.deepcopy(groups.get(group_id)),
    )
    monkeypatch.setattr(
        route_backend_chats,
        'get_user_role_in_group',
        lambda group_doc, user_id: 'User' if group_doc else None,
    )
    monkeypatch.setattr(
        route_backend_chats,
        'get_group_agents',
        lambda group_id: [_governed_group_agent()],
    )

    assert route_backend_chats._get_chat_allowed_group_ids(
        'user-owner',
        ['group-active', 'group-inactive', 'group-unknown', 'group-deleted'],
    ) == ['group-active']
    candidates = route_backend_chats._build_user_accessible_chat_agents(
        'user-owner',
        {},
        requested_agent={
            'id': 'group-benefits-agent',
            'is_group': True,
            'group_id': 'group-inactive',
        },
    )
    assert all(not candidate.get('is_group') for candidate in candidates)


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
    resume_context = context['capability_resume_context']
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
    resume_context = claimed['capability_resume_context']
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