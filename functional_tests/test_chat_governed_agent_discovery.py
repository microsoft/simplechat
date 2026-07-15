#!/usr/bin/env python3
# test_chat_governed_agent_discovery.py
"""
Functional test for governed chat-agent discovery.
Version: 0.250.067
Implemented in: 0.250.067

This test ensures personal, global, and group discovery catalogs are filtered
by current authorization and governance before safe descriptors are built.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SINGLE_APP_ROOT = REPO_ROOT / 'application' / 'single_app'
SEMANTIC_KERNEL_LOADER = SINGLE_APP_ROOT / 'semantic_kernel_loader.py'
AGENT_LOGGING_WRAPPER = SINGLE_APP_ROOT / 'agent_logging_chat_completion.py'
sys.path.insert(0, str(SINGLE_APP_ROOT))

import functions_agent_catalog  # pyright: ignore[reportMissingImports]  # noqa: E402
from functions_chat_capabilities import (  # pyright: ignore[reportMissingImports]  # noqa: E402
    CONTINUE_WITHOUT_CAPABILITIES_OPTION_ID,
    build_agent_capability_recommendation,
    build_capability_recommendation,
    build_governed_agent_capability_inventory,
    build_governed_capability_inventory,
    classify_capability_requirements,
    merge_capability_recommendations,
    resolve_governed_agent_capability_reference,
)
from functions_chat_capability_choices import (  # pyright: ignore[reportMissingImports]  # noqa: E402
    CapabilityChoiceError,
    apply_capability_choice_decision,
    build_capability_choice_proposal,
    revalidate_capability_choice,
)
from functions_chat_orchestration import build_turn_orchestration_plan  # pyright: ignore[reportMissingImports]  # noqa: E402


REFERENCE_SECRET = 'phase-8b-catalog-test-secret'
NOW = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)


def _agent(agent_id, display_name, **overrides):
    agent = {
        'id': agent_id,
        'name': agent_id,
        'display_name': display_name,
        'created_at': '2026-07-15T12:00:00+00:00',
        'is_enabled': True,
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
        'instructions': f'private instructions for {agent_id}',
        'actions_to_load': [],
        'azure_openai_gpt_endpoint': 'https://private-endpoint.example.test',
        'azure_openai_gpt_key': 'private-agent-secret',
        'other_settings': {
            'connector': {'tenant': 'private-tenant'},
            'hidden_tools': ['hidden_write_tool'],
        },
    }
    agent.update(overrides)
    return agent


def _settings(**overrides):
    settings = {
        'allow_user_agents': True,
        'enable_semantic_kernel': True,
        'per_user_semantic_kernel': False,
        'merge_global_semantic_kernel_with_workspace': False,
        'enable_group_workspaces': True,
        'allow_group_agents': True,
    }
    settings.update(overrides)
    return settings


def test_catalog_filters_authorization_governance_and_availability(monkeypatch):
    group_calls = []
    monkeypatch.setattr(functions_agent_catalog, 'ensure_migration_complete', lambda user_id: None)
    monkeypatch.setattr(
        functions_agent_catalog,
        'get_personal_agents',
        lambda user_id: [
            _agent('personal-allowed', 'Benefits Research'),
            _agent('personal-disabled', 'Disabled', is_enabled=False),
            _agent('personal-hidden', 'Hidden', hidden=True),
            _agent('personal-default-closed', 'Closed', discoverable_by_orchestrator=False),
            _agent('personal-foundry', 'Foundry', agent_type='new_foundry'),
            _agent('personal-action-agent', 'Action Agent', actions_to_load=['hidden_action']),
        ],
    )
    monkeypatch.setattr(
        functions_agent_catalog,
        'get_global_agents',
        lambda: [
            _agent('global-allowed', 'Benefits Research'),
            _agent('global-policy-denied', 'Denied'),
        ],
    )
    monkeypatch.setattr(
        functions_agent_catalog,
        'get_user_groups',
        lambda user_id: [
            {'id': 'group-current', 'name': 'Current Group'},
            {'id': 'group-inactive', 'name': 'Inactive Group', 'status': 'inactive'},
        ],
    )

    def get_group_agents(group_id):
        group_calls.append(group_id)
        return [_agent('group-allowed', 'Benefits Research')]

    def ensure_governance_access(feature_key, user_id, **kwargs):
        del feature_key, user_id
        if kwargs.get('item_id') == 'global-policy-denied':
            raise PermissionError('denied')

    monkeypatch.setattr(functions_agent_catalog, 'get_group_agents', get_group_agents)
    monkeypatch.setattr(
        functions_agent_catalog,
        'ensure_governance_access',
        ensure_governance_access,
    )

    catalog = functions_agent_catalog.build_authorized_agent_discovery_catalog(
        'user-1',
        settings=_settings(),
    )

    assert [agent['catalog_key'] for agent in catalog] == [
        'personal:user-1:personal-allowed',
        'global:global:global-allowed',
        'group:group-current:group-allowed',
    ]
    assert group_calls == ['group-current']
    serialized = str(catalog)
    assert 'global-policy-denied' not in serialized
    assert 'personal-disabled' not in serialized
    assert 'personal-hidden' not in serialized
    assert 'personal-default-closed' not in serialized
    assert 'personal-foundry' not in serialized
    assert 'personal-action-agent' not in serialized


def test_revoked_group_membership_and_global_policy_remove_candidates(monkeypatch):
    membership = {'groups': [{'id': 'group-current', 'name': 'Current Group'}]}
    monkeypatch.setattr(functions_agent_catalog, 'ensure_migration_complete', lambda user_id: None)
    monkeypatch.setattr(functions_agent_catalog, 'get_personal_agents', lambda user_id: [])
    monkeypatch.setattr(functions_agent_catalog, 'get_global_agents', lambda: [_agent('global-1', 'Global')])
    monkeypatch.setattr(
        functions_agent_catalog,
        'get_user_groups',
        lambda user_id: list(membership['groups']),
    )
    monkeypatch.setattr(
        functions_agent_catalog,
        'get_group_agents',
        lambda group_id: [_agent('group-1', 'Group')],
    )
    monkeypatch.setattr(
        functions_agent_catalog,
        'ensure_governance_access',
        lambda *args, **kwargs: None,
    )

    initial = functions_agent_catalog.build_authorized_agent_discovery_catalog(
        'user-1',
        settings=_settings(),
    )
    membership['groups'] = []
    refreshed = functions_agent_catalog.build_authorized_agent_discovery_catalog(
        'user-1',
        settings=_settings(
            per_user_semantic_kernel=True,
            merge_global_semantic_kernel_with_workspace=False,
        ),
    )

    assert {agent['scope_type'] for agent in initial} == {'global', 'group'}
    assert refreshed == []


def test_duplicate_names_use_stable_opaque_references_and_canonical_resolution():
    canonical_agents = [
        {
            **_agent('personal-agent-id', 'Benefits Research'),
            'scope_type': 'personal',
            'scope_id': 'user-1',
            'catalog_key': 'personal:user-1:personal-agent-id',
        },
        {
            **_agent('group-agent-id', 'Benefits Research'),
            'scope_type': 'group',
            'scope_id': 'group-1',
            'group_id': 'group-1',
            'catalog_key': 'group:group-1:group-agent-id',
        },
    ]

    first_inventory = build_governed_agent_capability_inventory(
        canonical_agents,
        reference_secret=REFERENCE_SECRET,
    )
    rebuilt_inventory = build_governed_agent_capability_inventory(
        list(reversed(canonical_agents)),
        reference_secret=REFERENCE_SECRET,
    )
    references = [agent['id'] for agent in first_inventory['agents']]

    assert len(set(references)) == 2
    assert set(references) == {
        agent['id'] for agent in rebuilt_inventory['agents']
    }
    assert all('personal-agent-id' not in reference for reference in references)
    assert all('group-agent-id' not in reference for reference in references)
    assert all('group-1' not in reference for reference in references)

    approved_reference = references[1]
    resolved = resolve_governed_agent_capability_reference(
        canonical_agents,
        approved_reference,
        reference_secret=REFERENCE_SECRET,
    )
    assert resolved['catalog_key'] == 'group:group-1:group-agent-id'
    assert resolve_governed_agent_capability_reference(
        canonical_agents,
        'agent:group:forged',
        reference_secret=REFERENCE_SECRET,
    ) is None

    original_identity = {
        **canonical_agents[0],
        'created_at': '2026-07-15T12:00:00+00:00',
    }
    replacement_identity = {
        **canonical_agents[0],
        'created_at': '2026-07-15T12:30:00+00:00',
    }
    original_reference = build_governed_agent_capability_inventory(
        [original_identity],
        reference_secret=REFERENCE_SECRET,
    )['agents'][0]['id']
    replacement_reference = build_governed_agent_capability_inventory(
        [replacement_identity],
        reference_secret=REFERENCE_SECRET,
    )['agents'][0]['id']
    assert original_reference != replacement_reference


def test_agent_matching_is_deterministic_bounded_and_suppressed_by_selection():
    canonical_agents = [
        {
            **_agent('benefits-agent', 'Benefits Research'),
            'scope_type': 'personal',
            'scope_id': 'user-1',
            'catalog_key': 'personal:user-1:benefits-agent',
        },
        {
            **_agent(
                'service-agent',
                'Service Records',
                orchestrator_descriptor={
                    'capability_tags': ['service_tickets', 'incident_lookup'],
                    'evidence_types': ['business_system_records'],
                    'read_only': True,
                    'external_data': False,
                    'risk_class': 'internal_read',
                    'data_sensitivity': 'internal',
                    'latency_class': 'seconds',
                    'cost_class': 'low',
                },
            ),
            'scope_type': 'global',
            'catalog_key': 'global:global:service-agent',
        },
    ]
    inventory = build_governed_agent_capability_inventory(
        canonical_agents,
        reference_secret=REFERENCE_SECRET,
    )

    recommendation = build_agent_capability_recommendation(
        inventory,
        'Summarize our employee benefits policy.',
    )

    assert recommendation['recommended_option_id'].startswith('agent:personal:')
    assert len(recommendation['options']) == 2
    assert recommendation['options'][0]['kind'] == 'agent'
    assert recommendation['options'][1]['id'] == CONTINUE_WITHOUT_CAPABILITIES_OPTION_ID
    assert recommendation['reason_codes'] == ['specialized_organizational_knowledge']
    assert build_agent_capability_recommendation(
        inventory,
        'Explain recursion with a short example.',
    ) is None
    assert build_agent_capability_recommendation(
        inventory,
        'Summarize our employee benefits policy.',
        selected_agent_present=True,
    ) is None
    assert build_agent_capability_recommendation(
        inventory,
        'Summarize our employee benefits policy.',
        selected_capability_ids=['workspace_search'],
    ) is None


def test_agent_and_builtin_options_share_one_recommendation_contract():
    resolved_capabilities = {
        capability_id: {
            'enabled': True,
            'available': True,
            'authorized': True,
            'governance_mode': 'recommend',
        }
        for capability_id in (
            'workspace_search',
            'analyze',
            'compare',
            'image',
            'web_search',
            'url_access',
            'deep_research',
        )
    }
    builtins = build_capability_recommendation(
        build_governed_capability_inventory(
            resolved_capabilities=resolved_capabilities,
        ),
        classify_capability_requirements(
            'What are the current updates to our employee benefits policy?'
        ),
    )
    agent_inventory = build_governed_agent_capability_inventory(
        [{
            **_agent('benefits-agent', 'Benefits Research'),
            'scope_type': 'personal',
            'scope_id': 'user-1',
            'catalog_key': 'personal:user-1:benefits-agent',
        }],
        reference_secret=REFERENCE_SECRET,
    )
    agents = build_agent_capability_recommendation(
        agent_inventory,
        'What are the current updates to our employee benefits policy?',
    )

    combined = merge_capability_recommendations(builtins, agents)
    option_ids = [option['id'] for option in combined['options']]

    assert option_ids[-1] == CONTINUE_WITHOUT_CAPABILITIES_OPTION_ID
    assert option_ids.count(CONTINUE_WITHOUT_CAPABILITIES_OPTION_ID) == 1
    assert len([option for option in combined['options'] if option.get('kind') == 'agent']) == 1
    assert set(combined['requirement_ids']) == {
        'current_authoritative_sources',
        'specialized_organizational_knowledge',
    }
    serialized = str(combined)
    assert 'private instructions' not in serialized
    assert 'benefits-agent' not in serialized
    assert 'private-endpoint' not in serialized
    assert 'private-agent-secret' not in serialized
    assert 'hidden_write_tool' not in serialized
    assert 'private-tenant' not in serialized


def test_agent_option_uses_existing_durable_choice_and_revalidation_contract():
    agent_inventory = build_governed_agent_capability_inventory(
        [{
            **_agent('benefits-agent', 'Benefits Research'),
            'scope_type': 'personal',
            'scope_id': 'user-1',
            'catalog_key': 'personal:user-1:benefits-agent',
        }],
        reference_secret=REFERENCE_SECRET,
    )
    recommendation = build_agent_capability_recommendation(
        agent_inventory,
        'Summarize our employee benefits policy.',
    )
    proposal = build_capability_choice_proposal(
        recommendation,
        run_id='parent-run-1',
        conversation_id='conversation-1',
        user_message_id='user-message-1',
        assistant_message_id='proposal-1',
        now=NOW,
    )
    agent_option = proposal['options'][0]

    assert agent_option['kind'] == 'agent'
    assert agent_option['agent_ref'] == agent_option['id']
    assert agent_option['capability_ids'] == []
    assert set(agent_option) == {
        'id',
        'kind',
        'agent_ref',
        'capability_ids',
        'effective_capability_ids',
        'label',
        'category',
        'scope_class',
        'latency_class',
        'cost_class',
        'external_data',
        'requires_user_choice',
        'read_only',
        'risk_class',
        'data_sensitivity',
        'capability_tags',
        'evidence_types',
        'external_query_mode',
        'sensitive_input_types',
    }

    approved, idempotent = apply_capability_choice_decision(
        proposal,
        agent_option['id'],
        actor_user_id='user-1',
        now=NOW,
    )
    assert idempotent is False
    assert approved['status'] == 'approved'
    assert approved['decision']['capability_ids'] == []
    assert approved['decision']['agent_ref'] == agent_option['id']
    assert revalidate_capability_choice(
        approved,
        {'version': 1, 'capabilities': [], 'agents': agent_inventory['agents']},
    ) is True

    with pytest.raises(CapabilityChoiceError) as revoked:
        revalidate_capability_choice(
            approved,
            {'version': 1, 'capabilities': [], 'agents': []},
        )
    assert revoked.value.code == 'agent_missing'

    changed_inventory = {
        'version': 1,
        'capabilities': [],
        'agents': [
            {
                **agent_inventory['agents'][0],
                'external_data': True,
                'risk_class': 'external_read',
            }
        ],
    }
    with pytest.raises(CapabilityChoiceError) as changed_policy:
        revalidate_capability_choice(approved, changed_inventory)
    assert changed_policy.value.code == 'agent_policy_changed'


def test_approved_discovered_agent_is_a_required_existing_plan_source():
    plan = build_turn_orchestration_plan(
        'Summarize our employee benefits policy.',
        conversation_id='conversation-1',
        selected_agent={'id': 'agent:personal:2b25d558bf54aa330659b19e47c251ad'},
        capability_origins={'selected_agent': 'discovery_approved'},
    )
    selected_agent_source = next(
        source for source in plan['sources'] if source['id'] == 'selected_agent'
    )
    selected_agent_step = next(
        step for step in plan['steps'] if step['capability'] == 'selected_agent'
    )

    assert selected_agent_source['origin'] == 'discovery_approved'
    assert selected_agent_source['required'] is True
    assert selected_agent_step['origin'] == 'discovery_approved'
    assert selected_agent_step['required'] is True
    assert 'approved_capability_discovery' in plan['reason_codes']


def test_agent_loader_and_discovered_run_telemetry_are_minimized():
    loader_source = SEMANTIC_KERNEL_LOADER.read_text(encoding='utf-8')
    wrapper_source = AGENT_LOGGING_WRAPPER.read_text(encoding='utf-8')

    assert '"agents": agents_cfg' not in loader_source
    assert '"aoai_endpoint"' not in loader_source
    assert '"aoai_key"' not in loader_source
    assert '"actions_to_load": agent_config' not in loader_source
    assert '_build_agent_loader_log_summary' in loader_source
    assert '_build_agent_connection_log_summary' in loader_source

    assert 'orchestration_minimize_telemetry' in wrapper_source
    assert '"prompt": None if minimize_telemetry' in wrapper_source
    assert 'if not minimize_telemetry:' in wrapper_source
    assert '"telemetry_minimized": minimize_telemetry' in wrapper_source


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-q']))