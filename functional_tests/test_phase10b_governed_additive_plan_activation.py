# test_phase10b_governed_additive_plan_activation.py
"""Functional tests for Phase 10B governed additive plan activation.

Version: 0.250.072
Implemented in: 0.250.072

This test ensures validated planner candidates become bounded server-owned
capability options without rewriting selected mandates.
"""

import os
import sys
import copy
from pathlib import Path


sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'application', 'single_app'))

from functions_chat_capabilities import (  # noqa: E402
    arbitrate_planner_capability_recommendation,
    build_capability_recommendation,
    build_governed_capability_inventory,
    build_planner_capability_recommendation,
    expand_governed_capability_baseline_ids,
    filter_unsupported_document_action_recommendation,
    match_governed_capabilities,
)
from functions_chat_capability_planner import (  # noqa: E402
    build_capability_planner_request,
    capability_planner_is_eligible,
)
from functions_chat_capability_choices import (  # noqa: E402
    CapabilityChoiceError,
    add_sensitive_external_query_options,
    apply_capability_choice_decision,
    build_capability_choice_proposal,
    build_capability_resume_origins,
    build_minimized_external_query,
    build_resumed_external_query,
    revalidate_capability_choice,
    revalidate_capability_execution_baseline,
    revalidate_capability_execution_compatibility,
    resolve_external_retrieval_message,
)
from functions_settings import normalize_chat_capability_planner_settings  # noqa: E402
from functions_orchestration_evaluation import (  # noqa: E402
    build_planner_activation_evaluation_event,
    build_recommendation_created_evaluation_event,
    build_recommendation_revalidation_evaluation_event,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _build_inventory(selected_capability_ids=None):
    resolved = {
        capability_id: {
            'enabled': True,
            'available': True,
            'authorized': True,
            'discoverable': True,
            'input_ready': True,
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
    return build_governed_capability_inventory(
        selected_capability_ids=selected_capability_ids,
        resolved_capabilities=resolved,
    )


def _planner_result(candidate_plans, recommended_plan_id='candidate_1'):
    return {
        'version': 1,
        'status': 'valid',
        'decision': 'propose',
        'requirements': [
            {
                'id': 'requirement_1',
                'evidence_types': ['public_web'],
                'reason_code': 'cross_source_evidence',
            },
        ],
        'candidate_plans': candidate_plans,
        'recommended_plan_id': recommended_plan_id,
        'clarification_code': None,
        'fallback_used': False,
    }


def test_workspace_and_web_materialize_as_one_server_owned_option():
    recommendation = build_planner_capability_recommendation(
        _planner_result([
            {
                'id': 'candidate_1',
                'capability_ids': ['workspace_search', 'web_search'],
                'reason_code': 'cross_source_evidence',
                'confidence': 'high',
            },
        ]),
        _build_inventory(),
    )

    assert recommendation['source'] == 'planner'
    assert len(recommendation['options']) == 2
    option = recommendation['options'][0]
    assert option['id'].startswith('plan:')
    assert option['capability_ids'] == ['web_search', 'workspace_search']
    assert option['effective_capability_ids'] == ['web_search', 'workspace_search']
    assert option['label'] == 'Search workspace and web'
    assert option['external_data'] is True
    assert option['risk_class'] == 'external_read'
    assert option['data_sensitivity'] == 'internal'


def test_selected_mandate_is_removed_from_approval_but_retained_as_context():
    recommendation = build_planner_capability_recommendation(
        _planner_result([
            {
                'id': 'candidate_1',
                'capability_ids': ['workspace_search', 'web_search'],
                'reason_code': 'cross_source_evidence',
                'confidence': 'high',
            },
        ]),
        _build_inventory(selected_capability_ids=['workspace_search']),
        {'selected_capability_ids': ['workspace_search']},
    )

    option = recommendation['options'][0]
    assert option['capability_ids'] == ['web_search']
    assert option['effective_capability_ids'] == ['web_search']
    assert option['label'] == 'Add Web Search'
    assert recommendation['selected_capability_ids'] == ['workspace_search']


def test_selected_bundle_dependency_keeps_selection_origin_after_approval():
    inventory = _build_inventory(selected_capability_ids=['web_search'])
    recommendation = build_planner_capability_recommendation(
        _planner_result([
            {
                'id': 'candidate_1',
                'capability_ids': ['web_search', 'deep_research'],
                'reason_code': 'public_source_archive_research',
                'confidence': 'high',
            },
        ]),
        inventory,
        {'selected_capability_ids': ['web_search']},
    )

    option = recommendation['options'][0]
    assert option['capability_ids'] == ['deep_research']
    assert option['effective_capability_ids'] == ['deep_research', 'web_search']
    assert recommendation['selected_context_labels'] == ['Web Search']
    assert build_capability_resume_origins(
        inventory,
        option['effective_capability_ids'],
    ) == {
        'deep_research': 'discovery_approved',
        'web_search': 'selection',
    }


def test_selected_deep_research_dependency_is_not_offered_for_approval():
    inventory = _build_inventory(selected_capability_ids=['deep_research'])
    recommendation = build_planner_capability_recommendation(
        _planner_result([{
            'id': 'candidate_1',
            'capability_ids': ['workspace_search', 'web_search'],
            'reason_code': 'cross_source_evidence',
            'confidence': 'high',
        }]),
        inventory,
        {'selected_capability_ids': ['deep_research']},
    )

    assert expand_governed_capability_baseline_ids(
        inventory,
        ['deep_research'],
    ) == ['deep_research', 'web_search']
    option = recommendation['options'][0]
    assert option['capability_ids'] == ['workspace_search']
    assert option['effective_capability_ids'] == ['workspace_search']
    assert recommendation['selected_capability_ids'] == [
        'deep_research',
        'web_search',
    ]
    assert revalidate_capability_execution_baseline(
        inventory,
        selected_capability_ids=['deep_research'],
        prior_effective_capabilities=[
            {'id': 'deep_research', 'origin': 'selection'},
            {'id': 'web_search', 'origin': 'selection'},
        ],
    ) is True
    assert build_capability_resume_origins(
        inventory,
        ['workspace_search'],
    ) == {
        'deep_research': 'selection',
        'web_search': 'selection',
        'workspace_search': 'discovery_approved',
    }

    blocked_inventory = copy.deepcopy(inventory)
    blocked_web = next(
        entry
        for entry in blocked_inventory['capabilities']
        if entry['id'] == 'web_search'
    )
    blocked_web['state'] = 'policy_blocked'
    try:
        revalidate_capability_execution_baseline(
            blocked_inventory,
            selected_capability_ids=['deep_research'],
        )
    except CapabilityChoiceError as error:
        assert error.code == 'capability_policy_blocked'
    else:
        raise AssertionError('selected bundle dependency policy drift must fail closed')


def test_deterministic_recommendation_subtracts_selected_bundle_closure():
    inventory = _build_inventory(selected_capability_ids=['workspace_search'])
    selected_workspace = next(
        entry
        for entry in inventory['capabilities']
        if entry['id'] == 'workspace_search'
    )
    selected_workspace['bundle'] = ['workspace_search', 'url_access']
    recommendation = build_capability_recommendation(
        inventory,
        [{
            'id': 'supplied_url_review',
            'reason_code': 'user_supplied_url_requires_review',
            'required_inputs': [],
        }],
    )
    assert recommendation is None


def test_deterministic_bundle_choice_rejects_current_closure_drift():
    inventory = _build_inventory()
    recommendation = build_capability_recommendation(
        inventory,
        [{
            'id': 'current_authoritative_sources',
            'reason_code': 'current_authoritative_sources',
            'required_inputs': [],
        }],
    )
    proposal = build_capability_choice_proposal(
        recommendation,
        run_id='run-deterministic-bundle',
        conversation_id='conversation-deterministic-bundle',
        user_message_id='user-deterministic-bundle',
    )
    approved, _ = apply_capability_choice_decision(
        proposal,
        'deep_research',
        actor_user_id='user-1',
    )
    assert revalidate_capability_choice(approved, inventory) is True

    changed_inventory = copy.deepcopy(inventory)
    changed_deep_research = next(
        entry
        for entry in changed_inventory['capabilities']
        if entry['id'] == 'deep_research'
    )
    changed_deep_research['bundle'] = ['deep_research']
    try:
        revalidate_capability_choice(approved, changed_inventory)
    except CapabilityChoiceError as error:
        assert error.code == 'capability_bundle_changed'
    else:
        raise AssertionError('deterministic bundle drift must fail closed')


def test_image_is_incompatible_with_selected_or_approved_agent_mandates():
    image_proposal = build_capability_choice_proposal(
        {
            'recommended_option_id': 'image',
            'options': [
                {
                    'id': 'image',
                    'capability_ids': ['image'],
                    'effective_capability_ids': ['image'],
                    'label': 'Image',
                },
                {
                    'id': 'continue_without_capabilities',
                    'capability_ids': [],
                    'effective_capability_ids': [],
                    'label': 'Continue',
                },
            ],
        },
        run_id='run-image-agent',
        conversation_id='conversation-image-agent',
        user_message_id='user-image-agent',
    )
    approved_image, _ = apply_capability_choice_decision(
        image_proposal,
        'image',
        actor_user_id='user-1',
    )
    try:
        revalidate_capability_execution_compatibility(
            approved_image,
            selected_agent_present=True,
        )
    except CapabilityChoiceError as error:
        assert error.code == 'capability_combination_unsupported'
    else:
        raise AssertionError('selected agent plus Image must fail closed')

    selected_image_agent_proposal = copy.deepcopy(approved_image)
    selected_image_agent_proposal['decision'] = {
        'status': 'approved',
        'effective_capability_ids': [],
        'agent_ref': 'agent:approved',
    }
    try:
        revalidate_capability_execution_compatibility(
            selected_image_agent_proposal,
            selected_capability_ids=['image'],
        )
    except CapabilityChoiceError as error:
        assert error.code == 'capability_combination_unsupported'
    else:
        raise AssertionError('selected Image plus approved agent must fail closed')


def test_auto_discovered_capability_is_not_requested_for_approval_again():
    inventory = _build_inventory()
    workspace_search = next(
        entry
        for entry in inventory['capabilities']
        if entry['id'] == 'workspace_search'
    )
    workspace_search.update({
        'auto_use_allowed': True,
        'requires_user_choice': False,
        'governance_mode': 'auto_read_only',
    })
    recommendation = build_planner_capability_recommendation(
        _planner_result([
            {
                'id': 'candidate_1',
                'capability_ids': ['workspace_search', 'web_search'],
                'reason_code': 'cross_source_evidence',
                'confidence': 'high',
            },
        ]),
        inventory,
        {'auto_capability_ids': ['workspace_search']},
    )

    option = recommendation['options'][0]
    assert option['capability_ids'] == ['web_search']
    assert option['effective_capability_ids'] == ['web_search']
    assert option['label'] == 'Add Web Search'


def test_deep_research_bundle_collapses_equivalent_explicit_plan():
    recommendation = build_planner_capability_recommendation(
        _planner_result([
            {
                'id': 'candidate_1',
                'capability_ids': ['deep_research'],
                'reason_code': 'public_source_archive_research',
                'confidence': 'high',
            },
            {
                'id': 'candidate_2',
                'capability_ids': ['deep_research', 'web_search'],
                'reason_code': 'multi_source_research',
                'confidence': 'high',
            },
        ]),
        _build_inventory(),
    )

    assert len(recommendation['options']) == 2
    option = recommendation['options'][0]
    assert option['capability_ids'] == ['deep_research']
    assert option['effective_capability_ids'] == ['deep_research', 'web_search']
    assert option['label'] == 'Run Deep Research'
    assert option['latency_class'] == 'minutes'
    assert option['cost_class'] == 'extended'


def test_low_confidence_recommendation_does_not_activate():
    recommendation = build_planner_capability_recommendation(
        _planner_result([
            {
                'id': 'candidate_1',
                'capability_ids': ['web_search'],
                'reason_code': 'public_source_retrieval',
                'confidence': 'medium',
            },
        ]),
        _build_inventory(),
    )

    assert recommendation is None


def test_unknown_unavailable_write_and_cyclic_candidates_fail_closed():
    inventory = _build_inventory()
    invalid_candidates = [
        {
            'id': 'candidate_1',
            'capability_ids': ['unknown_capability'],
            'reason_code': 'public_source_retrieval',
            'confidence': 'high',
        },
        {
            'id': 'candidate_1',
            'capability_ids': ['image'],
            'reason_code': 'visual_output',
            'confidence': 'high',
        },
    ]
    for candidate in invalid_candidates:
        assert build_planner_capability_recommendation(
            _planner_result([candidate]),
            inventory,
        ) is None

    unavailable_inventory = copy.deepcopy(inventory)
    web_search = next(
        entry
        for entry in unavailable_inventory['capabilities']
        if entry['id'] == 'web_search'
    )
    web_search.update({
        'state': 'unavailable',
        'available': False,
        'discoverable': False,
    })
    assert build_planner_capability_recommendation(
        _planner_result([
            {
                'id': 'candidate_1',
                'capability_ids': ['web_search'],
                'reason_code': 'public_source_retrieval',
                'confidence': 'high',
            },
        ]),
        unavailable_inventory,
    ) is None

    cyclic_inventory = copy.deepcopy(inventory)
    workspace_search = next(
        entry
        for entry in cyclic_inventory['capabilities']
        if entry['id'] == 'workspace_search'
    )
    web_search = next(
        entry
        for entry in cyclic_inventory['capabilities']
        if entry['id'] == 'web_search'
    )
    workspace_search['bundle'] = ['workspace_search', 'web_search']
    web_search['bundle'] = ['web_search', 'workspace_search']
    assert build_planner_capability_recommendation(
        _planner_result([
            {
                'id': 'candidate_1',
                'capability_ids': ['workspace_search'],
                'reason_code': 'authorized_workspace_evidence',
                'confidence': 'high',
            },
        ]),
        cyclic_inventory,
    ) is None


def test_document_actions_do_not_activate_with_required_retrieval_members():
    mixed_candidate = _planner_result([
        {
            'id': 'candidate_1',
            'capability_ids': ['analyze', 'web_search'],
            'reason_code': 'cross_source_evidence',
            'confidence': 'high',
        },
    ])
    assert build_planner_capability_recommendation(
        mixed_candidate,
        _build_inventory(),
    ) is None

    selected_retrieval_inventory = _build_inventory(
        selected_capability_ids=['workspace_search']
    )
    assert build_planner_capability_recommendation(
        _planner_result([
            {
                'id': 'candidate_1',
                'capability_ids': ['workspace_search', 'analyze'],
                'reason_code': 'document_analysis',
                'confidence': 'high',
            },
        ]),
        selected_retrieval_inventory,
        {'selected_capability_ids': ['workspace_search']},
    ) is None

    standalone_action = build_planner_capability_recommendation(
        _planner_result([
            {
                'id': 'candidate_1',
                'capability_ids': ['analyze'],
                'reason_code': 'document_analysis',
                'confidence': 'high',
            },
        ]),
        _build_inventory(),
    )
    assert standalone_action['options'][0]['capability_ids'] == ['analyze']

    deterministic_action = {
        'recommended_option_id': 'analyze',
        'options': [
            {
                'id': 'analyze',
                'capability_ids': ['analyze'],
                'effective_capability_ids': ['analyze'],
            },
            {
                'id': 'continue_without_capabilities',
                'capability_ids': [],
                'effective_capability_ids': [],
            },
        ],
    }
    assert filter_unsupported_document_action_recommendation(
        deterministic_action,
        ['workspace_search'],
    ) is None
    assert filter_unsupported_document_action_recommendation(
        deterministic_action,
        [],
    )['recommended_option_id'] == 'analyze'

    deterministic_image = {
        'recommended_option_id': 'image',
        'options': [
            {
                'id': 'image',
                'capability_ids': ['image'],
                'effective_capability_ids': ['image'],
            },
            {
                'id': 'continue_without_capabilities',
                'capability_ids': [],
                'effective_capability_ids': [],
            },
        ],
    }
    assert filter_unsupported_document_action_recommendation(
        deterministic_image,
        [],
        selected_agent_present=True,
    ) is None

    deterministic_agent = {
        'recommended_option_id': 'agent:approved',
        'options': [
            {
                'id': 'agent:approved',
                'kind': 'agent',
                'agent_ref': 'agent:approved',
                'capability_ids': [],
                'effective_capability_ids': [],
            },
            {
                'id': 'continue_without_capabilities',
                'capability_ids': [],
                'effective_capability_ids': [],
            },
        ],
    }
    assert filter_unsupported_document_action_recommendation(
        deterministic_agent,
        ['image'],
    ) is None

    assert build_planner_capability_recommendation(
        _planner_result([
            {
                'id': 'candidate_1',
                'capability_ids': ['image', 'web_search'],
                'reason_code': 'visual_output',
                'confidence': 'high',
            },
        ]),
        _build_inventory(),
    ) is None


def test_automatic_bundle_requires_every_dependency_to_be_auto_approved():
    inventory = _build_inventory()
    deep_research = next(
        entry
        for entry in inventory['capabilities']
        if entry['id'] == 'deep_research'
    )
    deep_research.update({
        'auto_use_allowed': True,
        'requires_user_choice': False,
        'governance_mode': 'auto_read_only',
    })
    requirements = [{
        'id': 'current_authoritative_sources',
        'reason_code': 'public_source_archive_research',
        'required_inputs': [],
    }]

    blocked_match = match_governed_capabilities(inventory, requirements)
    assert blocked_match['auto_capability_ids'] == []

    web_search = next(
        entry
        for entry in inventory['capabilities']
        if entry['id'] == 'web_search'
    )
    web_search.update({
        'auto_use_allowed': True,
        'requires_user_choice': False,
        'governance_mode': 'auto_read_only',
    })
    allowed_match = match_governed_capabilities(inventory, requirements)
    assert allowed_match['auto_capability_ids'] == ['deep_research']
    assert allowed_match['recommendation'] is None

    prior_effective = [
        {'id': 'deep_research', 'origin': 'discovery_auto'},
        {'id': 'web_search', 'origin': 'discovery_auto'},
    ]
    assert revalidate_capability_execution_baseline(
        inventory,
        prior_effective_capabilities=prior_effective,
        automatic_capability_root_ids=['deep_research'],
        automatic_capability_effective_ids=['deep_research', 'web_search'],
    ) is True

    changed_inventory = copy.deepcopy(inventory)
    changed_deep_research = next(
        entry
        for entry in changed_inventory['capabilities']
        if entry['id'] == 'deep_research'
    )
    changed_deep_research['bundle'] = ['deep_research']
    try:
        revalidate_capability_execution_baseline(
            changed_inventory,
            prior_effective_capabilities=prior_effective,
            automatic_capability_root_ids=['deep_research'],
            automatic_capability_effective_ids=['deep_research', 'web_search'],
        )
    except CapabilityChoiceError as error:
        assert error.code == 'capability_bundle_changed'
    else:
        raise AssertionError('automatic bundle closure drift must fail closed')


def test_automatic_bundle_dependency_can_retain_selection_origin():
    inventory = _build_inventory(selected_capability_ids=['web_search'])
    deep_research = next(
        entry
        for entry in inventory['capabilities']
        if entry['id'] == 'deep_research'
    )
    deep_research.update({
        'auto_use_allowed': True,
        'requires_user_choice': False,
        'governance_mode': 'auto_read_only',
    })
    match = match_governed_capabilities(
        inventory,
        [{
            'id': 'current_authoritative_sources',
            'reason_code': 'public_source_archive_research',
            'required_inputs': [],
        }],
    )
    assert match['auto_capability_ids'] == ['deep_research']
    prior_effective = [
        {'id': 'web_search', 'origin': 'selection'},
        {'id': 'deep_research', 'origin': 'discovery_auto'},
    ]
    assert revalidate_capability_execution_baseline(
        inventory,
        selected_capability_ids=['web_search'],
        prior_effective_capabilities=prior_effective,
        automatic_capability_root_ids=['deep_research'],
        automatic_capability_effective_ids=['deep_research', 'web_search'],
    ) is True
    assert build_capability_resume_origins(
        inventory,
        [],
        prior_effective_capabilities=prior_effective,
        automatic_capability_root_ids=['deep_research'],
    ) == {
        'web_search': 'selection',
        'deep_research': 'discovery_auto',
    }


def test_rootless_legacy_automatic_bundle_cannot_gain_new_dependency():
    inventory = _build_inventory()
    workspace_search = next(
        entry
        for entry in inventory['capabilities']
        if entry['id'] == 'workspace_search'
    )
    workspace_search.update({
        'auto_use_allowed': True,
        'requires_user_choice': False,
        'governance_mode': 'auto_read_only',
    })
    prior_effective = [
        {'id': 'workspace_search', 'origin': 'discovery_auto'},
    ]
    assert revalidate_capability_execution_baseline(
        inventory,
        prior_effective_capabilities=prior_effective,
    ) is True

    changed_inventory = copy.deepcopy(inventory)
    changed_workspace = next(
        entry
        for entry in changed_inventory['capabilities']
        if entry['id'] == 'workspace_search'
    )
    changed_workspace['bundle'] = ['workspace_search', 'web_search']
    try:
        revalidate_capability_execution_baseline(
            changed_inventory,
            prior_effective_capabilities=prior_effective,
        )
    except CapabilityChoiceError as error:
        assert error.code == 'capability_bundle_changed'
    else:
        raise AssertionError('legacy automatic bundle expansion must fail closed')

    ambiguous_prior_effective = [
        {'id': 'deep_research', 'origin': 'discovery_auto'},
        {'id': 'web_search', 'origin': 'discovery_auto'},
    ]
    removed_dependency_inventory = copy.deepcopy(inventory)
    removed_dependency_deep_research = next(
        entry
        for entry in removed_dependency_inventory['capabilities']
        if entry['id'] == 'deep_research'
    )
    removed_dependency_deep_research['bundle'] = ['deep_research']
    try:
        revalidate_capability_execution_baseline(
            removed_dependency_inventory,
            prior_effective_capabilities=ambiguous_prior_effective,
        )
    except CapabilityChoiceError as error:
        assert error.code == 'capability_bundle_changed'
    else:
        raise AssertionError('ambiguous legacy automatic closure must fail closed')


def test_planner_card_is_bounded_to_three_actionable_options_plus_continue():
    recommendation = build_planner_capability_recommendation(
        _planner_result([
            {
                'id': 'candidate_1',
                'capability_ids': ['web_search'],
                'reason_code': 'public_source_retrieval',
                'confidence': 'high',
            },
            {
                'id': 'candidate_2',
                'capability_ids': ['workspace_search'],
                'reason_code': 'authorized_workspace_evidence',
                'confidence': 'high',
            },
            {
                'id': 'candidate_3',
                'capability_ids': ['analyze'],
                'reason_code': 'document_analysis',
                'confidence': 'high',
            },
            {
                'id': 'candidate_4',
                'capability_ids': ['url_access'],
                'reason_code': 'public_source_retrieval',
                'confidence': 'high',
            },
        ]),
        _build_inventory(),
    )

    assert len(recommendation['options']) == 4
    assert recommendation['options'][-1]['id'] == 'continue_without_capabilities'


def test_assist_mode_is_normalized_and_uses_new_turn_eligibility():
    default_settings = normalize_chat_capability_planner_settings({})
    settings = normalize_chat_capability_planner_settings({
        'chat_capability_planner_mode': 'assist',
    })
    planner_request = build_capability_planner_request(
        'Find current sources.',
        _build_inventory(),
    )

    assert default_settings['chat_capability_planner_mode'] == 'assist'
    assert default_settings['chat_capability_planner_timeout_ms'] == 10000
    assert settings['chat_capability_planner_mode'] == 'assist'
    assert capability_planner_is_eligible(settings, planner_request) is True
    assert capability_planner_is_eligible(
        settings,
        planner_request,
        is_resume=True,
    ) is False


def test_deterministic_material_conflict_wins_but_complementary_plan_activates():
    inventory = _build_inventory()
    planner_recommendation = build_planner_capability_recommendation(
        _planner_result([
            {
                'id': 'candidate_1',
                'capability_ids': ['workspace_search', 'web_search'],
                'reason_code': 'cross_source_evidence',
                'confidence': 'high',
            },
        ]),
        inventory,
    )
    deterministic_workspace = {
        'recommended_option_id': 'workspace_search',
        'options': [{
            'id': 'workspace_search',
            'capability_ids': ['workspace_search'],
            'effective_capability_ids': ['workspace_search'],
        }],
    }
    selected, summary = arbitrate_planner_capability_recommendation(
        planner_recommendation,
        deterministic_workspace,
    )

    assert selected['source'] == 'planner'
    assert summary['activation_status'] == 'materialized'

    deterministic_deep_research = {
        'recommended_option_id': 'deep_research',
        'options': [{
            'id': 'deep_research',
            'capability_ids': ['deep_research'],
            'effective_capability_ids': ['deep_research', 'web_search'],
        }],
    }
    selected, summary = arbitrate_planner_capability_recommendation(
        planner_recommendation,
        deterministic_deep_research,
    )

    assert selected == deterministic_deep_research
    assert summary == {
        'activation_status': 'suppressed',
        'recommendation_source': 'deterministic',
        'suppression_reason': 'deterministic_conflict',
    }


def test_every_planner_alternative_preserves_deterministic_material_source():
    planner_recommendation = build_planner_capability_recommendation(
        _planner_result([
            {
                'id': 'candidate_1',
                'capability_ids': ['workspace_search', 'web_search'],
                'reason_code': 'cross_source_evidence',
                'confidence': 'high',
            },
            {
                'id': 'candidate_2',
                'capability_ids': ['web_search'],
                'reason_code': 'public_source_retrieval',
                'confidence': 'high',
            },
        ]),
        _build_inventory(),
    )
    deterministic_workspace = {
        'recommended_option_id': 'workspace_search',
        'options': [{
            'id': 'workspace_search',
            'capability_ids': ['workspace_search'],
            'effective_capability_ids': ['workspace_search'],
        }],
    }

    selected, summary = arbitrate_planner_capability_recommendation(
        planner_recommendation,
        deterministic_workspace,
    )

    actionable_options = [
        option
        for option in selected['options']
        if option['id'] != 'continue_without_capabilities'
    ]
    assert summary['activation_status'] == 'materialized'
    assert len(actionable_options) == 1
    assert actionable_options[0]['effective_capability_ids'] == [
        'web_search',
        'workspace_search',
    ]


def test_governed_agent_candidate_reuses_server_owned_opaque_reference():
    agent_ref = 'agent:global:' + ('a' * 32)
    inventory = _build_inventory()
    inventory['agents'] = [{
        'id': agent_ref,
        'kind': 'agent',
        'label': 'Research specialist',
        'category': 'specialized_agent',
        'state': 'unselected',
        'scope_class': 'global',
        'discoverable': True,
        'requires_user_choice': True,
        'read_only': True,
        'external_data': False,
        'risk_class': 'internal_read',
        'data_sensitivity': 'internal',
        'cost_class': 'standard',
        'latency_class': 'seconds',
        'capability_tags': ['research'],
        'evidence_types': ['authorized_knowledge'],
    }]
    recommendation = build_planner_capability_recommendation(
        _planner_result([
            {
                'id': 'candidate_1',
                'capability_ids': [agent_ref],
                'reason_code': 'specialized_authorized_agent',
                'confidence': 'high',
            },
        ]),
        inventory,
    )

    option = recommendation['options'][0]
    assert option['id'] == agent_ref
    assert option['agent_ref'] == agent_ref
    assert option['kind'] == 'agent'


def _approved_planner_proposal(recommendation):
    proposal = build_capability_choice_proposal(
        recommendation,
        run_id='phase10b-run',
        conversation_id='phase10b-conversation',
        user_message_id='phase10b-user-message',
        assistant_message_id='phase10b-proposal',
    )
    approved, _ = apply_capability_choice_decision(
        proposal,
        recommendation['recommended_option_id'],
        actor_user_id='phase10b-user',
    )
    return approved


def test_plan_binding_revalidates_exact_bundle_and_policy_state():
    inventory = _build_inventory()
    recommendation = build_planner_capability_recommendation(
        _planner_result([
            {
                'id': 'candidate_1',
                'capability_ids': ['deep_research'],
                'reason_code': 'public_source_archive_research',
                'confidence': 'high',
            },
        ]),
        inventory,
    )
    approved = _approved_planner_proposal(recommendation)

    assert approved['version'] == 2
    assert approved['recommendation_source'] == 'planner'
    assert revalidate_capability_choice(approved, inventory) is True

    changed_bundle_inventory = copy.deepcopy(inventory)
    deep_research = next(
        entry
        for entry in changed_bundle_inventory['capabilities']
        if entry['id'] == 'deep_research'
    )
    deep_research['bundle'] = ['deep_research']
    try:
        revalidate_capability_choice(approved, changed_bundle_inventory)
    except CapabilityChoiceError as error:
        assert error.code == 'capability_bundle_changed'
    else:
        raise AssertionError('bundle drift must invalidate the approved plan')

    changed_policy_inventory = copy.deepcopy(inventory)
    web_search = next(
        entry
        for entry in changed_policy_inventory['capabilities']
        if entry['id'] == 'web_search'
    )
    web_search['cost_class'] = 'low'
    try:
        revalidate_capability_choice(approved, changed_policy_inventory)
    except CapabilityChoiceError as error:
        assert error.code == 'capability_plan_policy_changed'
    else:
        raise AssertionError('policy drift must invalidate the opaque plan binding')


def test_phase10b_read_only_rule_does_not_reject_legacy_deterministic_image_choice():
    inventory = _build_inventory()
    proposal = build_capability_choice_proposal(
        {
            'version': 1,
            'status': 'pending',
            'recommended_option_id': 'image',
            'options': [
                {
                    'id': 'image',
                    'capability_ids': ['image'],
                    'effective_capability_ids': ['image'],
                    'label': 'Image',
                    'latency_class': 'seconds',
                    'cost_class': 'standard',
                    'external_data': False,
                },
            ],
        },
        run_id='legacy-image-run',
        conversation_id='legacy-image-conversation',
        user_message_id='legacy-image-user-message',
        assistant_message_id='legacy-image-proposal',
    )
    approved, _ = apply_capability_choice_decision(
        proposal,
        'image',
        actor_user_id='legacy-image-user',
    )

    assert revalidate_capability_choice(approved, inventory) is True


def test_forged_effective_capability_payload_is_rejected():
    recommendation = build_planner_capability_recommendation(
        _planner_result([
            {
                'id': 'candidate_1',
                'capability_ids': ['web_search'],
                'reason_code': 'public_source_retrieval',
                'confidence': 'high',
            },
        ]),
        _build_inventory(),
    )
    approved = _approved_planner_proposal(recommendation)
    approved['decision']['effective_capability_ids'].append('workspace_search')

    try:
        revalidate_capability_choice(approved, _build_inventory())
    except CapabilityChoiceError as error:
        assert error.code == 'capability_decision_mismatch'
    else:
        raise AssertionError('forged effective capabilities must be rejected')


def test_sensitive_current_turn_option_keeps_server_plan_binding():
    inventory = _build_inventory()
    recommendation = build_planner_capability_recommendation(
        _planner_result([
            {
                'id': 'candidate_1',
                'capability_ids': ['web_search'],
                'reason_code': 'public_source_retrieval',
                'confidence': 'high',
            },
        ]),
        inventory,
    )
    recommendation = add_sensitive_external_query_options(
        recommendation,
        'Look up the property records at 123 Main Street.',
    )

    sensitive_option = next(
        option
        for option in recommendation['options']
        if option['id'].endswith('_with_sensitive_inputs')
    )
    assert sensitive_option['external_query_mode'] == 'include_approved_sensitive_inputs'
    assert sensitive_option['sensitive_input_types'] == ['street_address']
    recommendation['recommended_option_id'] = sensitive_option['id']
    approved = _approved_planner_proposal(recommendation)
    assert revalidate_capability_choice(approved, inventory) is True


def test_empty_minimized_query_never_falls_back_to_raw_sensitive_message():
    raw_message = '123 Main Street'
    minimized = build_minimized_external_query(raw_message)

    assert minimized['query'] == ''
    assert resolve_external_retrieval_message(
        {'_server_external_query': minimized['query']},
        raw_message,
    ) == ''
    assert resolve_external_retrieval_message({}, raw_message) == raw_message

    selected_web_query = build_resumed_external_query(
        raw_message,
        {'workspace_search', 'web_search'},
    )
    assert selected_web_query == ''
    assert resolve_external_retrieval_message(
        {'_server_external_query': selected_web_query},
        raw_message,
    ) == ''
    assert build_resumed_external_query(
        raw_message,
        {'url_access'},
    ) is None

    mixed_sensitive_query = build_resumed_external_query(
        'Parcel 123 Main Street, email person@example.com, phone 555-123-4567, account ID ABCD-1234.',
        {'web_search'},
        external_query_mode='include_approved_sensitive_inputs',
        approved_sensitive_input_types=['street_address'],
    )
    assert '123 Main Street' in mixed_sensitive_query
    assert 'person@example.com' not in mixed_sensitive_query
    assert '555-123-4567' not in mixed_sensitive_query
    assert 'ABCD-1234' not in mixed_sensitive_query


def test_selected_and_automatic_baselines_revalidate_before_execution():
    selected_inventory = _build_inventory(
        selected_capability_ids=['workspace_search']
    )
    assert revalidate_capability_execution_baseline(
        selected_inventory,
        selected_capability_ids=['workspace_search'],
    ) is True

    blocked_selected_inventory = copy.deepcopy(selected_inventory)
    selected_workspace = next(
        entry
        for entry in blocked_selected_inventory['capabilities']
        if entry['id'] == 'workspace_search'
    )
    selected_workspace.update({
        'state': 'policy_blocked',
        'discoverable': False,
    })
    try:
        revalidate_capability_execution_baseline(
            blocked_selected_inventory,
            selected_capability_ids=['workspace_search'],
        )
    except CapabilityChoiceError as error:
        assert error.code == 'capability_policy_blocked'
    else:
        raise AssertionError('blocked selected mandates must invalidate the plan')

    automatic_inventory = _build_inventory()
    automatic_workspace = next(
        entry
        for entry in automatic_inventory['capabilities']
        if entry['id'] == 'workspace_search'
    )
    automatic_workspace.update({
        'auto_use_allowed': True,
        'requires_user_choice': False,
        'governance_mode': 'auto_read_only',
    })
    prior_effective = [{
        'id': 'workspace_search',
        'origin': 'discovery_auto',
        'required': True,
    }]
    assert revalidate_capability_execution_baseline(
        automatic_inventory,
        prior_effective_capabilities=prior_effective,
    ) is True

    changed_auto_inventory = copy.deepcopy(automatic_inventory)
    changed_auto_workspace = next(
        entry
        for entry in changed_auto_inventory['capabilities']
        if entry['id'] == 'workspace_search'
    )
    changed_auto_workspace.update({
        'auto_use_allowed': False,
        'governance_mode': 'recommend',
    })
    try:
        revalidate_capability_execution_baseline(
            changed_auto_inventory,
            prior_effective_capabilities=prior_effective,
        )
    except CapabilityChoiceError as error:
        assert error.code == 'capability_policy_blocked'
    else:
        raise AssertionError('stale automatic discovery must invalidate the plan')
    assert build_capability_resume_origins(
        changed_auto_inventory,
        [],
        prior_effective_capabilities=prior_effective,
    ) == {}


def test_sensitive_variants_keep_planner_card_within_actionable_limit():
    recommendation = build_planner_capability_recommendation(
        _planner_result([
            {
                'id': 'candidate_1',
                'capability_ids': ['web_search'],
                'reason_code': 'public_source_retrieval',
                'confidence': 'high',
            },
            {
                'id': 'candidate_2',
                'capability_ids': ['deep_research'],
                'reason_code': 'public_source_archive_research',
                'confidence': 'high',
            },
            {
                'id': 'candidate_3',
                'capability_ids': ['url_access'],
                'reason_code': 'public_source_retrieval',
                'confidence': 'high',
            },
        ]),
        _build_inventory(),
    )
    recommendation = add_sensitive_external_query_options(
        recommendation,
        'Review property records for 123 Main Street.',
        max_actionable_options=3,
    )

    actionable_options = [
        option
        for option in recommendation['options']
        if option['id'] != 'continue_without_capabilities'
    ]
    assert len(actionable_options) == 3
    assert recommendation['options'][-1]['id'] == 'continue_without_capabilities'
    assert actionable_options[0]['id'] == recommendation['recommended_option_id']


def test_activation_events_use_only_bounded_additive_dimensions():
    metadata = {
        'mode': 'assist',
        'status': 'valid',
        'decision': 'propose',
        'candidate_count': 2,
        'recommended_capability_classes': [
            'workspace_search',
            'web_search',
            'agent:group:private-canonical-id',
        ],
        'reason_codes': ['cross_source_evidence', 'private rationale'],
        'latency_ms': 317,
        'fallback_used': False,
        'activation_status': 'materialized',
        'recommendation_source': 'planner',
        'suppression_reason': None,
        'raw_response': 'private planner response',
    }
    event = build_planner_activation_evaluation_event(
        'private-run-id',
        metadata,
        provider_class='azure_openai',
        model_name='gpt-5.6-terra-private-deployment',
    )

    assert event['event_type'] == 'orchestration_planner_activation'
    assert event['planner_mode'] == 'assist'
    assert event['activation_status'] == 'materialized'
    assert event['recommendation_source'] == 'planner'
    assert event['capability_combination'] == 'web_search+workspace_search'
    serialized = repr(event)
    assert 'private-run-id' not in serialized
    assert 'private planner response' not in serialized
    assert 'private-canonical-id' not in serialized

    recommendation = build_planner_capability_recommendation(
        _planner_result([
            {
                'id': 'candidate_1',
                'capability_ids': ['workspace_search', 'web_search'],
                'reason_code': 'cross_source_evidence',
                'confidence': 'high',
            },
        ]),
        _build_inventory(),
    )
    proposal = build_capability_choice_proposal(
        recommendation,
        run_id='private-run-id',
        conversation_id='conversation',
        user_message_id='user-message',
        assistant_message_id='assistant-message',
    )
    created = build_recommendation_created_evaluation_event(proposal)
    assert created['recommendation_source'] == 'planner'
    assert created['capability_count'] == 2
    assert created['capability_combination'] == 'web_search+workspace_search'
    assert created['reason_codes'] == ['cross_source_evidence']

    succeeded = build_recommendation_revalidation_evaluation_event(
        'private-proposal-id',
        phase='execution',
        proposal=proposal,
    )
    invalidated = build_recommendation_revalidation_evaluation_event(
        'private-proposal-id',
        phase='resume',
        error_code='capability_bundle_changed',
    )
    assert succeeded['status'] == 'succeeded'
    assert succeeded['capability_count'] == 2
    assert succeeded['capability_combination'] == 'web_search+workspace_search'
    assert invalidated['status'] == 'invalidated'
    assert invalidated['reason_class'] == 'bundle'
    assert 'private-proposal-id' not in repr(succeeded)
    assert 'private-proposal-id' not in repr(invalidated)


def test_admin_settings_expose_and_normalize_governed_activation_modes():
    template_source = (
        REPO_ROOT / 'application' / 'single_app' / 'templates' / 'admin_settings.html'
    ).read_text(encoding='utf-8')
    route_source = (
        REPO_ROOT / 'application' / 'single_app' / 'route_frontend_admin_settings.py'
    ).read_text(encoding='utf-8')

    assert 'id="chat-capability-planner-section"' in template_source
    assert 'name="chat_capability_planner_mode"' in template_source
    assert 'value="off"' in template_source
    assert 'value="shadow"' in template_source
    assert 'value="assist"' in template_source
    assert "chat_capability_planner_mode|default('assist') == 'assist'" in (
        template_source
    )
    planner_section = template_source.split(
        'id="chat-capability-planner-section"',
        1,
    )[1].split('<!-- Embeddings Configuration Section -->', 1)[0]
    assert 'innerHTML' not in planner_section
    assert 'insertAdjacentHTML' not in planner_section
    assert '|safe' not in planner_section
    assert 'onclick=' not in planner_section
    assert 'chat_capability_planner_settings = (' in route_source
    assert '**chat_capability_planner_settings,' in route_source

    normalized = normalize_chat_capability_planner_settings({
        'chat_capability_planner_mode': 'assist',
        'chat_capability_planner_timeout_ms': 999999,
        'chat_capability_planner_max_completion_tokens': -1,
        'chat_capability_planner_max_candidate_plans': 99,
        'chat_capability_planner_max_capabilities_per_plan': 0,
        'chat_capability_planner_model_source': 'same_as_chat',
    })
    assert normalized == {
        'chat_capability_planner_mode': 'assist',
        'chat_capability_planner_timeout_ms': 10000,
        'chat_capability_planner_max_completion_tokens': 64,
        'chat_capability_planner_max_candidate_plans': 5,
        'chat_capability_planner_max_capabilities_per_plan': 1,
        'chat_capability_planner_model_source': 'same_as_chat',
        'chat_capability_planner_model_endpoint_id': '',
        'chat_capability_planner_model_id': '',
    }