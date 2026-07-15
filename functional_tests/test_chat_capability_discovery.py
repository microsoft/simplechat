#!/usr/bin/env python3
# test_chat_capability_discovery.py
"""
Functional test for governed chat capability discovery and recommendation.
Version: 0.250.066
Implemented in: 0.250.066

This test ensures server-resolved capability states remain distinct and only
authorized, available, discoverable capabilities can be recommended.
"""

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SINGLE_APP_ROOT = REPO_ROOT / 'application' / 'single_app'
sys.path.insert(0, str(SINGLE_APP_ROOT))

from functions_chat_capabilities import (  # noqa: E402
    CONTINUE_WITHOUT_CAPABILITIES_OPTION_ID,
    build_capability_recommendation,
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