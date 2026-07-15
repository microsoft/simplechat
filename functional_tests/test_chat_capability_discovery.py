#!/usr/bin/env python3
# test_chat_capability_discovery.py
"""
Functional test for governed chat capability discovery and recommendation.
Version: 0.250.067
Implemented in: 0.250.067

This test ensures server-resolved capability states remain distinct and only
authorized, available, discoverable capabilities can be recommended.
"""

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SINGLE_APP_ROOT = REPO_ROOT / 'application' / 'single_app'
sys.path.insert(0, str(SINGLE_APP_ROOT))

from functions_agent_payload import AgentPayloadError, sanitize_agent_payload  # noqa: E402
from json_schema_validation import validate_agent  # noqa: E402
from functions_chat_capabilities import (  # noqa: E402
    CONTINUE_WITHOUT_CAPABILITIES_OPTION_ID,
    build_capability_recommendation,
    build_governed_agent_capability_inventory,
    build_governed_capability_inventory,
    classify_capability_requirements,
)


def _resolved_capabilities(*, deep_research=True, web_search=True):
    return {
        'workspace_search': {
            'enabled': True,
            'available': True,
            'authorized': True,
            'governance_mode': 'recommend',
        },
        'analyze': {
            'enabled': True,
            'available': True,
            'authorized': True,
            'governance_mode': 'recommend',
        },
        'compare': {
            'enabled': True,
            'available': True,
            'authorized': True,
            'governance_mode': 'recommend',
        },
        'image': {
            'enabled': True,
            'available': True,
            'authorized': True,
            'governance_mode': 'manual_only',
        },
        'web_search': {
            'enabled': web_search,
            'available': web_search,
            'authorized': True,
            'governance_mode': 'recommend',
        },
        'url_access': {
            'enabled': True,
            'available': True,
            'authorized': True,
            'governance_mode': 'recommend',
        },
        'deep_research': {
            'enabled': deep_research,
            'available': deep_research,
            'authorized': True,
            'governance_mode': 'recommend',
        },
    }


def _entry(inventory, capability_id):
    return next(
        item for item in inventory['capabilities'] if item['id'] == capability_id
    )


def test_inventory_preserves_selection_and_governed_states():
    resolved = _resolved_capabilities()
    resolved['compare']['authorized'] = False
    resolved['image']['governance_mode'] = 'blocked'
    resolved['url_access']['available'] = False
    inventory = build_governed_capability_inventory(
        selected_capability_ids=['workspace_search'],
        resolved_capabilities=resolved,
    )

    assert _entry(inventory, 'workspace_search')['state'] == 'selected'
    assert _entry(inventory, 'workspace_search')['selected'] is True
    assert _entry(inventory, 'web_search')['state'] == 'unselected'
    assert _entry(inventory, 'web_search')['discoverable'] is True
    assert _entry(inventory, 'compare')['state'] == 'unauthorized'
    assert _entry(inventory, 'compare')['discoverable'] is False
    assert _entry(inventory, 'image')['state'] == 'policy_blocked'
    assert _entry(inventory, 'url_access')['state'] == 'unavailable'


def test_inventory_fails_closed_without_server_resolution():
    inventory = build_governed_capability_inventory(
        selected_capability_ids=['web_search'],
        resolved_capabilities={},
    )

    web_search = _entry(inventory, 'web_search')
    assert web_search['selected'] is True
    assert web_search['state'] == 'unavailable'
    assert web_search['discoverable'] is False


def test_only_workspace_search_can_be_automatically_discovered():
    resolved = _resolved_capabilities()
    resolved['workspace_search']['governance_mode'] = 'auto_read_only'
    resolved['analyze']['governance_mode'] = 'auto_read_only'
    resolved['compare']['governance_mode'] = 'auto_read_only'
    inventory = build_governed_capability_inventory(
        resolved_capabilities=resolved,
    )

    assert _entry(inventory, 'workspace_search')['auto_use_allowed'] is True
    assert _entry(inventory, 'analyze')['auto_use_allowed'] is False
    assert _entry(inventory, 'analyze')['requires_user_choice'] is True
    assert _entry(inventory, 'compare')['auto_use_allowed'] is False
    assert _entry(inventory, 'compare')['requires_user_choice'] is True


def test_simple_timeless_question_has_no_recommendation():
    inventory = build_governed_capability_inventory(
        resolved_capabilities=_resolved_capabilities(),
    )
    requirements = classify_capability_requirements(
        'Explain recursion with a short example.'
    )

    assert requirements == []
    assert build_capability_recommendation(inventory, requirements) is None


def test_local_current_rules_offer_deep_research_and_web_search():
    inventory = build_governed_capability_inventory(
        resolved_capabilities=_resolved_capabilities(),
    )
    requirements = classify_capability_requirements(
        'What are the current Virginia and Fairfax County property rules?'
    )
    recommendation = build_capability_recommendation(inventory, requirements)

    assert requirements == [{
        'id': 'current_authoritative_sources',
        'reason_code': 'current_authoritative_sources',
        'required_inputs': [],
    }]
    assert recommendation['recommended_option_id'] == 'deep_research'
    assert [option['id'] for option in recommendation['options']] == [
        'deep_research',
        'web_search',
        CONTINUE_WITHOUT_CAPABILITIES_OPTION_ID,
    ]

    timeless_wording_requirements = classify_capability_requirements(
        'What are the Fairfax County zoning and property rules?'
    )
    assert timeless_wording_requirements[0]['id'] == 'current_authoritative_sources'


def test_local_current_rules_offer_only_available_capabilities():
    web_only_inventory = build_governed_capability_inventory(
        resolved_capabilities=_resolved_capabilities(deep_research=False),
    )
    requirements = classify_capability_requirements(
        'Check the current Fairfax County zoning rules.'
    )
    web_only = build_capability_recommendation(web_only_inventory, requirements)
    assert [option['id'] for option in web_only['options']] == [
        'web_search',
        CONTINUE_WITHOUT_CAPABILITIES_OPTION_ID,
    ]

    no_research_inventory = build_governed_capability_inventory(
        resolved_capabilities=_resolved_capabilities(
            deep_research=False,
            web_search=False,
        ),
    )
    assert build_capability_recommendation(no_research_inventory, requirements) is None


def test_selected_capability_resolves_matching_requirement():
    inventory = build_governed_capability_inventory(
        selected_capability_ids=['web_search'],
        resolved_capabilities=_resolved_capabilities(),
    )
    requirements = classify_capability_requirements(
        'What is the latest stable Python release?'
    )

    assert build_capability_recommendation(inventory, requirements) is None


def test_analyze_and_compare_require_authorized_targets():
    inventory = build_governed_capability_inventory(
        resolved_capabilities=_resolved_capabilities(),
    )

    no_targets = classify_capability_requirements(
        'Analyze and compare the documents.',
        authorized_document_count=0,
    )
    no_target_recommendation = build_capability_recommendation(inventory, no_targets)
    assert no_target_recommendation is None

    one_target = classify_capability_requirements(
        'Analyze this document.',
        authorized_document_count=1,
    )
    one_target_recommendation = build_capability_recommendation(inventory, one_target)
    assert one_target_recommendation['recommended_option_id'] == 'analyze'

    two_targets = classify_capability_requirements(
        'Compare these documents for differences.',
        authorized_document_count=2,
    )
    two_target_recommendation = build_capability_recommendation(inventory, two_targets)
    assert two_target_recommendation['recommended_option_id'] == 'compare'


def test_image_is_recommended_only_for_explicit_visual_output():
    resolved = _resolved_capabilities()
    resolved['image']['governance_mode'] = 'recommend'
    inventory = build_governed_capability_inventory(
        resolved_capabilities=resolved,
    )

    assert build_capability_recommendation(
        inventory,
        classify_capability_requirements('Explain why diagrams can help learning.'),
    ) is None
    recommendation = build_capability_recommendation(
        inventory,
        classify_capability_requirements('Create an infographic about recursion.'),
    )
    assert recommendation['recommended_option_id'] == 'image'
    diagram_recommendation = build_capability_recommendation(
        inventory,
        classify_capability_requirements('Turn this explanation into an image.'),
    )
    assert diagram_recommendation['recommended_option_id'] == 'image'


def test_blocked_and_unauthorized_capabilities_are_never_offered():
    resolved = _resolved_capabilities()
    resolved['deep_research']['authorized'] = False
    resolved['web_search']['governance_mode'] = 'blocked'
    inventory = build_governed_capability_inventory(
        resolved_capabilities=resolved,
    )
    requirements = classify_capability_requirements(
        'Research the current county regulations using authoritative sources.'
    )

    assert build_capability_recommendation(inventory, requirements) is None

    blocked_bundle = _resolved_capabilities()
    blocked_bundle['web_search']['governance_mode'] = 'blocked'
    blocked_bundle_inventory = build_governed_capability_inventory(
        resolved_capabilities=blocked_bundle,
    )
    blocked_bundle_recommendation = build_capability_recommendation(
        blocked_bundle_inventory,
        requirements,
    )
    assert blocked_bundle_recommendation is None


def test_agent_inventory_defaults_closed_and_exposes_only_safe_descriptors():
    agents = [
        {
            'catalog_key': 'personal:user-1:benefits-agent',
            'created_at': '2026-07-15T12:00:00+00:00',
            'display_name': 'Benefits Research',
            'discoverable_by_orchestrator': True,
            'orchestrator_descriptor': {
                'capability_tags': ['benefits', 'policy_lookup'],
                'evidence_types': ['employee_benefits', 'policy_documents'],
                'read_only': True,
                'risk_class': 'internal_read',
                'data_sensitivity': 'internal',
                'latency_class': 'seconds',
                'cost_class': 'standard',
            },
            'instructions': 'SECRET instructions must never leave the canonical record.',
            'actions_to_load': ['hidden_action'],
            'assigned_knowledge': {'document_ids': ['private-document-id']},
        },
        {
            'catalog_key': 'global::default-closed',
            'created_at': '2026-07-15T12:00:00+00:00',
            'display_name': 'Default Closed',
            'orchestrator_descriptor': {
                'capability_tags': ['benefits'],
                'evidence_types': ['policy_documents'],
                'read_only': True,
                'risk_class': 'internal_read',
                'data_sensitivity': 'internal',
                'latency_class': 'seconds',
                'cost_class': 'low',
            },
        },
        {
            'catalog_key': 'group:group-1:write-agent',
            'created_at': '2026-07-15T12:00:00+00:00',
            'display_name': 'Write Agent',
            'discoverable_by_orchestrator': True,
            'orchestrator_descriptor': {
                'capability_tags': ['benefits'],
                'evidence_types': ['policy_documents'],
                'read_only': False,
                'risk_class': 'consequential_write',
                'data_sensitivity': 'internal',
                'latency_class': 'seconds',
                'cost_class': 'standard',
            },
        },
    ]

    inventory = build_governed_agent_capability_inventory(
        agents,
        reference_secret='phase-8b-test-secret',
    )

    assert inventory['version'] == 1
    assert len(inventory['agents']) == 1
    descriptor = inventory['agents'][0]
    assert descriptor['id'].startswith('agent:personal:')
    assert descriptor['label'] == 'Benefits Research'
    assert descriptor['state'] == 'unselected'
    assert descriptor['discoverable'] is True
    assert descriptor['auto_use_allowed'] is False
    assert descriptor['requires_user_choice'] is True
    assert descriptor['capability_tags'] == ['benefits', 'policy_lookup']
    assert descriptor['evidence_types'] == ['employee_benefits', 'policy_documents']
    assert set(descriptor) == {
        'id',
        'kind',
        'label',
        'category',
        'state',
        'scope',
        'scope_class',
        'discoverable',
        'auto_use_allowed',
        'requires_user_choice',
        'read_only',
        'external_data',
        'risk_class',
        'data_sensitivity',
        'cost_class',
        'latency_class',
        'capability_tags',
        'evidence_types',
    }
    serialized = str(inventory)
    assert 'SECRET instructions' not in serialized
    assert 'hidden_action' not in serialized
    assert 'private-document-id' not in serialized
    assert 'default-closed' not in serialized
    assert 'write-agent' not in serialized


def test_agent_discovery_policy_is_normalized_and_defaults_closed():
    base_payload = {
        'name': 'benefits_research',
        'display_name': 'Benefits Research',
        'description': 'Looks up employee benefits.',
        'instructions': 'Canonical instructions.',
        'actions_to_load': [],
        'other_settings': {},
        'max_completion_tokens': -1,
    }

    default_closed = sanitize_agent_payload(base_payload)
    assert default_closed['discoverable_by_orchestrator'] is False
    assert default_closed['orchestrator_descriptor'] == {}

    governed = sanitize_agent_payload({
        **base_payload,
        'id': '11111111-1111-4111-8111-111111111111',
        'discoverable_by_orchestrator': True,
        'orchestrator_descriptor': {
            'capability_tags': [' Benefits ', 'benefits', 'Policy Lookup!'],
            'evidence_types': ['Policy Documents'],
            'read_only': True,
            'external_data': False,
            'risk_class': 'internal_read',
            'data_sensitivity': 'internal',
            'latency_class': 'seconds',
            'cost_class': 'standard',
            'ignored_secret': 'must not survive normalization',
        },
    })
    assert governed['discoverable_by_orchestrator'] is True
    assert governed['orchestrator_descriptor'] == {
        'capability_tags': ['benefits', 'policy_lookup'],
        'evidence_types': ['policy_documents'],
        'read_only': True,
        'external_data': False,
        'risk_class': 'internal_read',
        'data_sensitivity': 'internal',
        'latency_class': 'seconds',
        'cost_class': 'standard',
    }
    assert validate_agent(governed) is None

    try:
        sanitize_agent_payload({
            **base_payload,
            'discoverable_by_orchestrator': True,
            'orchestrator_descriptor': {
                'capability_tags': ['benefits'],
                'evidence_types': ['policy_documents'],
                'read_only': False,
                'risk_class': 'consequential_write',
                'data_sensitivity': 'internal',
                'latency_class': 'seconds',
                'cost_class': 'standard',
            },
        })
        raise AssertionError('discoverable write-capable agents must be rejected')
    except AgentPayloadError as exc:
        assert 'read-only' in str(exc).lower()

    try:
        sanitize_agent_payload({
            **base_payload,
            'agent_type': 'new_foundry',
            'discoverable_by_orchestrator': True,
            'orchestrator_descriptor': governed['orchestrator_descriptor'],
        })
        raise AssertionError('Foundry agents must remain outside Phase 8B discovery')
    except AgentPayloadError as exc:
        assert 'local agents only' in str(exc).lower()

    try:
        sanitize_agent_payload({
            **base_payload,
            'actions_to_load': ['hidden_action'],
            'discoverable_by_orchestrator': True,
            'orchestrator_descriptor': governed['orchestrator_descriptor'],
        })
        raise AssertionError('agents with attached actions must remain undiscoverable')
    except AgentPayloadError as exc:
        assert 'without attached actions' in str(exc).lower()


if __name__ == '__main__':
    tests = [
        test_inventory_preserves_selection_and_governed_states,
        test_inventory_fails_closed_without_server_resolution,
        test_only_workspace_search_can_be_automatically_discovered,
        test_simple_timeless_question_has_no_recommendation,
        test_local_current_rules_offer_deep_research_and_web_search,
        test_local_current_rules_offer_only_available_capabilities,
        test_selected_capability_resolves_matching_requirement,
        test_analyze_and_compare_require_authorized_targets,
        test_image_is_recommended_only_for_explicit_visual_output,
        test_blocked_and_unauthorized_capabilities_are_never_offered,
        test_agent_inventory_defaults_closed_and_exposes_only_safe_descriptors,
        test_agent_discovery_policy_is_normalized_and_defaults_closed,
    ]
    results = []

    for test in tests:
        print(f'\nRunning {test.__name__}...')
        try:
            test()
            print('Passed')
            results.append(True)
        except Exception as exc:
            print(f'Failed: {exc}')
            results.append(False)

    passed = sum(results)
    total = len(results)
    print(f'\nResults: {passed}/{total} tests passed')
    sys.exit(0 if all(results) else 1)