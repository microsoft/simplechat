#!/usr/bin/env python3
# test_phase9_orchestration_observability.py
"""
Functional test for Phase 9 orchestration observability and privacy.
Version: 0.250.069
Implemented in: 0.250.068

This test ensures evaluation events expose only bounded aggregate run,
recommendation, latency, and citation-yield fields without private payloads.
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[1]
SINGLE_APP_ROOT = REPO_ROOT / 'application' / 'single_app'
sys.path.insert(0, str(SINGLE_APP_ROOT))

from functions_orchestration_evaluation import (  # noqa: E402
    build_orchestration_run_evaluation_event,
    build_planner_completed_evaluation_event,
    build_planner_rejected_evaluation_event,
    build_planner_shadow_compared_evaluation_event,
    build_planner_timed_out_evaluation_event,
    build_recommendation_created_evaluation_event,
    build_recommendation_decision_evaluation_event,
    build_recommendation_outcome_evaluation_event,
)


PRIVATE_VALUES = (
    'canonical-agent-private-id',
    'private-group-name',
    'private prompt text',
    'private evidence text',
    'https://private-endpoint.example.test',
    'private-secret-value',
    'write_customer_record',
    'private-model-id',
    'agent:group:canonical-agent-private-id',
)


def _proposal():
    agent_reference = 'agent:group:canonical-agent-private-id'
    return {
        'run_id': 'parent-run-private-id',
        'reason_codes': [
            'specialized_organizational_knowledge',
            'private prompt text',
        ],
        'requirement_ids': ['specialized_organizational_knowledge'],
        'recommended_option_id': agent_reference,
        'options': [
            {
                'id': agent_reference,
                'kind': 'agent',
                'agent_ref': agent_reference,
                'label': 'private-group-name',
                'scope_class': 'private-group-name',
                'capability_ids': [],
                'external_data': False,
                'instructions': 'private prompt text',
                'endpoint': 'https://private-endpoint.example.test',
                'action_arguments': {'name': 'write_customer_record'},
            },
            {
                'id': 'continue_without_capabilities',
                'kind': 'continue',
                'capability_ids': [],
            },
        ],
        'created_at': '2026-07-15T12:00:00+00:00',
        'decision': {
            'option_id': agent_reference,
            'agent_ref': agent_reference,
            'status': 'approved',
            'actor_user_id': 'canonical-agent-private-id',
            'decided_at': '2026-07-15T12:00:02.500000+00:00',
        },
    }


def _run():
    return SimpleNamespace(
        run_id='child-run-private-id',
        status='partial',
        mode='coordinated',
        task_profile='grounded_answer',
        started_at='2026-07-15T12:00:03+00:00',
        completed_at='2026-07-15T12:00:08+00:00',
        replan_count=1,
        nodes=[
            SimpleNamespace(
                id='canonical-agent-private-id',
                type='collect',
                capability='selected_agent',
                required=True,
                status='succeeded',
                debug_message='private prompt text',
            ),
            SimpleNamespace(
                id='private-group-name',
                type='collect',
                capability='web_search',
                required=False,
                status='failed',
                debug_message='private-secret-value',
            ),
            SimpleNamespace(
                id='finalize-private-id',
                type='finalize',
                capability='response',
                required=True,
                status='succeeded',
            ),
        ],
        evidence_ledger={
            'citations': [{
                'title': 'private evidence text',
                'uri': 'https://private-endpoint.example.test',
            }],
            'unsupported_facts': [{'text': 'private prompt text'}],
            'missing_or_failed': [{'message': 'private-secret-value'}],
            'facts': [{'text': 'private evidence text'}],
        },
    )


def _assert_private_values_absent(event):
    serialized = json.dumps(event, sort_keys=True)
    for private_value in PRIVATE_VALUES:
        assert private_value not in serialized


def test_run_event_contains_bounded_aggregate_outcomes_only():
    event = build_orchestration_run_evaluation_event(_run())

    assert event['event_type'] == 'orchestration_run_completed'
    assert event['run_correlation_id'] != 'child-run-private-id'
    assert len(event['run_correlation_id']) == 16
    assert event['source_count'] == 2
    assert event['required_source_count'] == 1
    assert event['source_succeeded_count'] == 1
    assert event['source_failed_count'] == 1
    assert event['finalizer_status'] == 'succeeded'
    assert event['citation_count'] == 1
    assert event['citation_yield'] == 1.0
    assert event['unsupported_fact_count'] == 1
    assert event['missing_evidence_count'] == 1
    assert event['run_latency_ms'] == 5000
    _assert_private_values_absent(event)


def test_recommendation_events_bucket_agents_and_drop_unknown_reasons():
    proposal = _proposal()
    created = build_recommendation_created_evaluation_event(proposal)
    decided = build_recommendation_decision_evaluation_event(
        proposal,
        idempotent=True,
    )

    assert created['recommended_capability'] == 'governed_agent'
    assert created['reason_codes'] == ['specialized_organizational_knowledge']
    assert created['option_count'] == 2
    assert decided['decision_status'] == 'approved'
    assert decided['selected_capability'] == 'governed_agent'
    assert decided['decision_latency_ms'] == 2500
    assert decided['idempotent'] is True
    _assert_private_values_absent(created)
    _assert_private_values_absent(decided)


def test_resumed_outcome_reports_incremental_latency_and_citation_yield():
    proposal = _proposal()
    outcome = build_recommendation_outcome_evaluation_event(
        _run(),
        {
            'original_proposal': proposal,
            'decision': proposal['decision'],
            'agent_info': {
                'id': 'canonical-agent-private-id',
                'instructions': 'private prompt text',
            },
        },
    )

    assert outcome['event_type'] == 'orchestration_recommendation_outcome'
    assert outcome['decision_status'] == 'approved'
    assert outcome['selected_capability'] == 'governed_agent'
    assert outcome['incremental_latency_ms'] == 5500
    assert outcome['citation_count'] == 1
    assert outcome['citation_yield'] == 1.0
    assert outcome['parent_run_correlation_id'] != 'parent-run-private-id'
    _assert_private_values_absent(outcome)


def test_planner_events_use_fixed_privacy_safe_dimensions():
    metadata = {
        'version': 1,
        'mode': 'shadow',
        'status': 'valid',
        'decision': 'propose',
        'candidate_count': 2,
        'recommended_capability_classes': [
            'web_search',
            'governed_agent',
            'agent:group:canonical-agent-private-id',
        ],
        'reason_codes': [
            'public_source_archive_research',
            'private prompt text',
        ],
        'latency_ms': 412,
        'fallback_used': False,
        'raw_response': 'private evidence text',
    }
    completed = build_planner_completed_evaluation_event(
        'private-planner-run-id',
        metadata,
        provider_class='azure_openai',
        model_name='private-model-id-gpt-4o',
    )
    compared = build_planner_shadow_compared_evaluation_event(
        'private-planner-run-id',
        metadata,
        {
            'planner_decision': 'propose',
            'deterministic_decision': 'direct',
            'agreement_category': 'decision_disagreement',
            'raw_difference': 'private prompt text',
        },
        provider_class='azure_openai',
        model_name='private-model-id-gpt-4o',
    )

    assert completed['event_type'] == 'orchestration_planner_completed'
    assert completed['run_correlation_id'] != 'private-planner-run-id'
    assert completed['provider_class'] == 'azure_openai'
    assert completed['model_class'] == 'other'
    assert completed['capability_classes'] == ['web_search', 'governed_agent']
    assert completed['reason_codes'] == ['public_source_archive_research']
    assert compared['event_type'] == 'orchestration_planner_shadow_compared'
    assert compared['agreement_category'] == 'decision_disagreement'
    _assert_private_values_absent(completed)
    _assert_private_values_absent(compared)


def test_planner_rejection_and_timeout_events_expose_only_bounded_failures():
    rejected_metadata = {
        'mode': 'shadow',
        'status': 'rejected',
        'failure_code': 'unknown_capability',
        'latency_ms': 25,
        'fallback_used': True,
        'raw_error': 'private-secret-value',
    }
    timed_out_metadata = {
        **rejected_metadata,
        'status': 'timed_out',
        'failure_code': 'transport_timeout',
        'latency_ms': 5000,
    }
    rejected = build_planner_rejected_evaluation_event(
        'private-planner-run-id',
        rejected_metadata,
        provider_class='openai_style',
        model_name='private-model-id',
    )
    timed_out = build_planner_timed_out_evaluation_event(
        'private-planner-run-id',
        timed_out_metadata,
        provider_class='anthropic',
        model_name='private-model-id-claude',
    )

    assert rejected['event_type'] == 'orchestration_planner_rejected'
    assert rejected['failure_code'] == 'unknown_capability'
    assert timed_out['event_type'] == 'orchestration_planner_timed_out'
    assert timed_out['failure_code'] == 'transport_timeout'
    assert timed_out['model_class'] == 'claude'
    _assert_private_values_absent(rejected)
    _assert_private_values_absent(timed_out)


if __name__ == '__main__':
    raise SystemExit(0)