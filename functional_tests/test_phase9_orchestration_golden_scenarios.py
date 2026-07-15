#!/usr/bin/env python3
# test_phase9_orchestration_golden_scenarios.py
"""
Functional test for Phase 9 deterministic orchestration golden scenarios.
Version: 0.250.068
Implemented in: 0.250.068

This test composes planning, governed choice, evidence collection, executor
normalization, and central synthesis contracts without live external services.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SINGLE_APP_ROOT = REPO_ROOT / 'application' / 'single_app'
sys.path.insert(0, str(SINGLE_APP_ROOT))

from functions_agent_action_evidence import (  # noqa: E402
    agent_action_evidence_collection_complete,
    apply_agent_action_evidence_to_ledger,
    build_agent_action_evidence_task,
    normalize_agent_action_evidence_response,
)
from functions_central_synthesis import (  # noqa: E402
    build_central_synthesis_messages,
    central_synthesis_is_ready,
    create_central_synthesis_request,
)
from functions_chat_capabilities import (  # noqa: E402
    CONTINUE_WITHOUT_CAPABILITIES_OPTION_ID,
    build_agent_capability_recommendation,
    build_capability_recommendation,
    build_governed_agent_capability_inventory,
    build_governed_capability_inventory,
    classify_capability_requirements,
)
from functions_chat_capability_choices import (  # noqa: E402
    apply_capability_choice_decision,
    build_capability_choice_proposal,
    build_minimized_external_query,
)
from functions_chat_orchestration import build_turn_orchestration_plan  # noqa: E402
from functions_evidence_collectors import (  # noqa: E402
    apply_evidence_collector_result,
    apply_evidence_collector_results,
    collect_selected_image_evidence,
    collect_web_search_evidence,
)
from functions_evidence_ledger import (  # noqa: E402
    add_fact,
    create_evidence_ledger_from_plan,
)
from functions_image_generation import (  # noqa: E402
    build_grounded_image_synthesis_profile,
    constrain_image_proposal_to_evidence_ledger,
)


NOW = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)


def _finalizer_steps(plan):
    return [step for step in plan['steps'] if step['type'] == 'finalize']


def _build_executor_task(plan, ledger, request, executor_type, evidence_types):
    return build_agent_action_evidence_task(
        plan,
        ledger,
        request,
        executor_type=executor_type,
        executor_name='Phase 9 deterministic executor',
        capability_metadata={
            'capability_tags': ['profile', 'analytics'],
            'evidence_types': evidence_types,
            'required_permissions': ['read'],
            'uses_current_user_context': True,
            'returns_citations': True,
        },
        authorization_context={
            'user_id': 'authenticated-user',
            'conversation_id': 'authorized-conversation',
        },
    )


def _selected_headshot_result():
    return collect_selected_image_evidence(
        [{
            'message_id': 'selected-headshot-message',
            'file_name': 'headshot.png',
            'mime_type': 'image/png',
            'workspace_scope': 'conversation',
            'vision_analysis': {
                'description': 'A verified professional headshot.',
                'objects': ['person', 'glasses'],
            },
        }],
        requested=True,
        authorized=True,
    )


def _all_builtin_capabilities_available(*, web_search=True, deep_research=True):
    resolved = {
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
    for capability_id, available in (
        ('web_search', web_search),
        ('deep_research', deep_research),
    ):
        resolved[capability_id]['enabled'] = available
        resolved[capability_id]['available'] = available
    return build_governed_capability_inventory(resolved_capabilities=resolved)


def test_golden_m365_work_life_image_collects_before_one_finalizer():
    request = (
        'Create a whiteboard sketch of my work life grounded in my M365 '
        'profile and selected headshot.'
    )
    plan = build_turn_orchestration_plan(
        request,
        run_id='phase9-golden-m365',
        selected_agent={'id': 'selected-profile-agent'},
        selected_image_reference_count=1,
        image_generation_available=True,
    )
    ledger = create_evidence_ledger_from_plan(
        plan,
        user_message_id='phase9-golden-m365-message',
    )
    task = _build_executor_task(
        plan,
        ledger,
        request,
        'selected_agent',
        ['enterprise_data', 'profile'],
    )

    assert central_synthesis_is_ready(plan, ledger) is False
    apply_evidence_collector_result(
        ledger,
        _selected_headshot_result(),
        source_id='selected_images',
    )
    executor_result = normalize_agent_action_evidence_response(
        task,
        executor_response={
            'sources_attempted': [{'tool': 'get_current_profile', 'status': 'succeeded'}],
            'facts': [
                {'text': 'The user is a Solution Architect.', 'confidence': 'source_supported'},
                {'text': 'Two coworkers collaborate with the user.', 'confidence': 'source_supported'},
            ],
            'citations': [{
                'title': 'Current M365 profile',
                'excerpt': 'Role: Solution Architect',
            }],
        },
    )
    apply_agent_action_evidence_to_ledger(ledger, task, executor_result)

    assert agent_action_evidence_collection_complete(plan, ledger, task) is True
    assert ledger['status'] == 'ready'
    synthesis = create_central_synthesis_request(
        request,
        plan,
        ledger,
        output_profile=build_grounded_image_synthesis_profile(),
    )
    serialized = json.dumps(synthesis)
    instructions = ' '.join(synthesis['output_profile']['instructions'])

    assert synthesis['requested_output']['type'] == 'image_proposal'
    assert synthesis['policy']['executor_output_is_evidence_only'] is True
    assert 'The user is a Solution Architect.' in serialized
    assert 'A verified professional headshot.' in serialized
    assert 'generic person icons for collaborators' in instructions
    assert len(_finalizer_steps(plan)) == 1
    assert _finalizer_steps(plan)[0]['capability'] == 'image_proposal'


def test_golden_sql_dashboard_uses_actual_metrics_and_omits_unsupported_metrics():
    request = 'Create an infographic showing customer churn trends from the SQL database.'
    plan = build_turn_orchestration_plan(
        request,
        run_id='phase9-golden-sql',
        selected_action={'type': 'analysis'},
        image_generation_available=True,
    )
    ledger = create_evidence_ledger_from_plan(
        plan,
        user_message_id='phase9-golden-sql-message',
    )
    task = _build_executor_task(
        plan,
        ledger,
        request,
        'selected_action',
        ['structured_data', 'business_metrics'],
    )
    executor_result = normalize_agent_action_evidence_response(
        task,
        executor_response={
            'sources_attempted': [{'tool': 'execute_read_query', 'status': 'succeeded'}],
            'facts': [
                {
                    'text': 'Enterprise churn is 6 percent and SMB churn is 14 percent.',
                    'confidence': 'source_supported',
                },
                {
                    'text': 'Overall churn improved by 99 percent.',
                    'confidence': 'unsupported',
                },
            ],
            'results': [{
                'type': 'sql_result',
                'status': 'succeeded',
                'summary': 'Enterprise: 6%; SMB: 14%.',
            }],
        },
    )
    apply_agent_action_evidence_to_ledger(ledger, task, executor_result)

    synthesis = create_central_synthesis_request(
        request,
        plan,
        ledger,
        output_profile=build_grounded_image_synthesis_profile(),
    )
    serialized = json.dumps(synthesis)

    assert ledger['status'] == 'ready'
    assert 'Enterprise churn is 6 percent' in serialized
    assert 'Enterprise: 6%; SMB: 14%.' in serialized
    assert 'Overall churn improved by 99 percent.' not in serialized
    assert synthesis['omitted_unsupported_fact_count'] == 1
    assert len(_finalizer_steps(plan)) == 1


def test_golden_public_profile_not_found_keeps_headshot_and_discloses_gap():
    request = (
        'Create a professional profile visual using my LinkedIn public profile '
        'and selected headshot.'
    )
    plan = build_turn_orchestration_plan(
        request,
        run_id='phase9-golden-public-profile',
        web_search_enabled=True,
        selected_image_reference_count=1,
        image_generation_available=True,
    )
    ledger = create_evidence_ledger_from_plan(
        plan,
        user_message_id='phase9-golden-public-profile-message',
    )
    web_result = collect_web_search_evidence(
        [],
        runs=[{
            'query': 'public professional profile',
            'status': 'completed',
            'success': True,
        }],
        requested=True,
    )
    apply_evidence_collector_results(
        ledger,
        [web_result, _selected_headshot_result()],
    )
    unsupported = add_fact(
        ledger,
        'The LinkedIn profile says the user is a chief executive.',
        [],
        confidence='unsupported',
        fact_id='unsupported-linkedin-title',
    )

    synthesis = create_central_synthesis_request(
        request,
        plan,
        ledger,
        output_profile=build_grounded_image_synthesis_profile(),
    )
    serialized = json.dumps(synthesis)
    image_fact = next(
        fact for fact in ledger['facts']
        if 'verified professional headshot' in fact['text']
    )
    image_artifact = next(
        artifact for artifact in ledger['artifacts']
        if artifact['type'] == 'image_reference'
    )
    constrained = constrain_image_proposal_to_evidence_ledger(
        {
            'prompt': 'Create a professional profile visual using the verified headshot.',
            'evidenceIds': [image_fact['id'], unsupported['id']],
            'referenceImageIds': [image_artifact['id']],
        },
        ledger,
    )

    assert ledger['status'] == 'partial'
    assert 'chief executive' not in serialized
    assert 'Web search completed but returned no verifiable public sources.' in serialized
    assert image_fact['text'] in serialized
    assert constrained['evidenceIds'] == [image_fact['id']]
    assert constrained['referenceImageIds'] == [image_artifact['id']]


def test_golden_selected_image_qa_uses_response_finalizer_without_image_proposal():
    request = 'What is this image about?'
    plan = build_turn_orchestration_plan(
        request,
        run_id='phase9-golden-selected-image-qa',
        selected_image_reference_count=1,
        image_generation_available=True,
    )
    ledger = create_evidence_ledger_from_plan(
        plan,
        user_message_id='phase9-golden-selected-image-qa-message',
    )
    apply_evidence_collector_results(ledger, [_selected_headshot_result()])

    synthesis = create_central_synthesis_request(request, plan, ledger)
    messages = build_central_synthesis_messages(synthesis)

    assert plan['task_profile'] == 'grounded_answer'
    assert synthesis['requested_output']['type'] == 'response'
    assert synthesis['output_profile']['type'] == 'response'
    assert _finalizer_steps(plan) == [{
        **_finalizer_steps(plan)[0],
        'capability': 'response',
    }]
    assert 'simpleimage' not in json.dumps(messages)
    assert 'A verified professional headshot.' in json.dumps(synthesis)


def test_golden_current_local_rules_choice_approve_decline_and_unavailable():
    request = (
        'Explain the current property-line, fence, shed, lighting, easement, '
        'and maintenance rules for 123 Main Street in Fairfax County, Virginia.'
    )
    inventory = _all_builtin_capabilities_available()
    requirements = classify_capability_requirements(request)
    recommendation = build_capability_recommendation(inventory, requirements)
    proposal = build_capability_choice_proposal(
        recommendation,
        run_id='phase9-golden-fairfax-parent',
        conversation_id='phase9-golden-fairfax-conversation',
        user_message_id='phase9-golden-fairfax-message',
        assistant_message_id='phase9-golden-fairfax-proposal',
        now=NOW,
    )

    approved, approved_idempotent = apply_capability_choice_decision(
        proposal,
        'deep_research',
        actor_user_id='authorized-user',
        now=NOW,
    )
    declined, declined_idempotent = apply_capability_choice_decision(
        proposal,
        CONTINUE_WITHOUT_CAPABILITIES_OPTION_ID,
        actor_user_id='authorized-user',
        now=NOW,
    )
    minimized_query = build_minimized_external_query(request)
    unavailable_recommendation = build_capability_recommendation(
        _all_builtin_capabilities_available(web_search=False, deep_research=False),
        requirements,
    )

    assert requirements[0]['id'] == 'current_authoritative_sources'
    assert recommendation['recommended_option_id'] == 'deep_research'
    assert [option['id'] for option in recommendation['options']] == [
        'deep_research',
        'web_search',
        CONTINUE_WITHOUT_CAPABILITIES_OPTION_ID,
    ]
    assert approved['decision']['status'] == 'approved'
    assert approved['decision']['effective_capability_ids'] == [
        'deep_research',
        'web_search',
    ]
    assert approved_idempotent is False
    assert declined['decision']['status'] == 'declined'
    assert declined['decision']['effective_capability_ids'] == []
    assert declined_idempotent is False
    assert '123 Main Street' not in minimized_query['query']
    assert unavailable_recommendation is None


def test_golden_governed_agent_remains_evidence_only_and_centrally_finalized():
    canonical_agent = {
        'catalog_key': 'personal:authorized-user:canonical-private-agent-id',
        'created_at': '2026-07-15T12:00:00+00:00',
        'display_name': 'Benefits Research',
        'scope_type': 'personal',
        'scope_id': 'authorized-user',
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
        'instructions': 'Private canonical instructions.',
        'azure_openai_gpt_key': 'private-secret-value',
        'actions_to_load': [],
    }
    inventory = build_governed_agent_capability_inventory(
        [canonical_agent],
        reference_secret='phase9-reference-secret',
    )
    recommendation = build_agent_capability_recommendation(
        inventory,
        'Summarize our employee benefits policy.',
    )
    proposal = build_capability_choice_proposal(
        recommendation,
        run_id='phase9-golden-agent-parent',
        conversation_id='phase9-golden-agent-conversation',
        user_message_id='phase9-golden-agent-message',
        assistant_message_id='phase9-golden-agent-proposal',
        now=NOW,
    )
    approved, _ = apply_capability_choice_decision(
        proposal,
        proposal['recommended_option_id'],
        actor_user_id='authorized-user',
        now=NOW,
    )
    agent_reference = approved['decision']['agent_ref']
    request = 'Summarize our employee benefits policy.'
    plan = build_turn_orchestration_plan(
        request,
        run_id='phase9-golden-agent-child',
        selected_agent={'id': agent_reference},
        capability_origins={'selected_agent': 'discovery_approved'},
    )
    ledger = create_evidence_ledger_from_plan(
        plan,
        user_message_id='phase9-golden-agent-message',
    )
    task = _build_executor_task(
        plan,
        ledger,
        request,
        'selected_agent',
        ['employee_benefits', 'policy_documents'],
    )
    executor_result = normalize_agent_action_evidence_response(
        task,
        executor_response={
            'sources_attempted': [{'tool': 'read_benefits_policy', 'status': 'succeeded'}],
            'facts': [{
                'text': 'The plan includes an employer retirement contribution.',
                'confidence': 'source_supported',
            }],
            'results': [{
                'type': 'executor_prose',
                'status': 'succeeded',
                'summary': 'This executor text is evidence, not the final answer.',
            }],
        },
    )
    apply_agent_action_evidence_to_ledger(ledger, task, executor_result)
    synthesis = create_central_synthesis_request(request, plan, ledger)
    serialized = json.dumps(synthesis)

    selected_source = next(source for source in plan['sources'] if source['id'] == 'selected_agent')
    assert selected_source['origin'] == 'discovery_approved'
    assert selected_source['required'] is True
    assert synthesis['policy']['executor_output_is_evidence_only'] is True
    assert synthesis['output_profile']['type'] == 'response'
    assert len(_finalizer_steps(plan)) == 1
    assert 'This executor text is evidence, not the final answer.' in serialized
    assert 'canonical-private-agent-id' not in serialized
    assert 'Private canonical instructions.' not in serialized
    assert 'private-secret-value' not in serialized


if __name__ == '__main__':
    raise SystemExit(0)