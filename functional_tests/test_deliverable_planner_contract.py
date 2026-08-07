#!/usr/bin/env python3
# test_deliverable_planner_contract.py
"""
Functional test for the Phase 11A deliverable planner contract.
Version: 0.250.126
Implemented in: 0.250.126

This test ensures deliverable intent and materialized deliverable plans remain
separate from capability planning and are available to central synthesis.
"""

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SINGLE_APP_ROOT = REPO_ROOT / 'application' / 'single_app'
sys.path.insert(0, str(SINGLE_APP_ROOT))

from functions_central_synthesis import create_central_synthesis_request  # noqa: E402
from functions_chat_orchestration import build_turn_orchestration_plan  # noqa: E402
from functions_deliverable_planner import (  # noqa: E402
    build_deliverable_intent,
    materialize_deliverable_plan,
)
from functions_evidence_ledger import (  # noqa: E402
    add_evidence_source,
    add_fact,
    add_missing_evidence,
    create_evidence_ledger_from_plan,
    materialize_deliverable_plan_for_ledger,
    set_evidence_ledger_status,
)


def _source_requirement_ids(ledger, source_id):
    return list(next(
        source.get('requirement_ids') or []
        for source in ledger.get('sources') or []
        if source.get('id') == source_id
    ))


def _build_agent_plan(original_request, run_id):
    return build_turn_orchestration_plan(
        original_request,
        run_id=run_id,
        selected_agent={'id': 'analysis-agent'},
    )


def test_inline_answer_intent_persists_without_artifact():
    original_request = 'Summarize the current account status in two sentences.'
    plan = build_turn_orchestration_plan(
        original_request,
        run_id='phase-11a-inline-only',
    )
    ledger = create_evidence_ledger_from_plan(
        plan,
        user_message_id='phase-11a-inline-message',
        original_request=original_request,
    )

    assert ledger['requested_output']['type'] == 'response'
    assert ledger['deliverable_intent']['response_mode'] == 'inline_response_only'
    assert ledger['deliverable_intent']['primary_response']['type'] == 'inline_answer'
    assert ledger['deliverable_intent']['provisional_deliverables'] == []
    assert ledger['materialized_deliverable_plan'] == {}


def test_explicit_csv_request_materializes_required_artifact_for_synthesis():
    original_request = 'Use the selected agent and create a CSV with one row per project.'
    requested_output = {
        'type': 'generated_file',
        'format': 'csv',
        'instructions': ['Include one row per project.'],
    }
    directive_snapshot = {
        'revision': 'memory-revision-7',
        'effects': {
            'ask_first': [
                {
                    'ref': 'directive-review-files',
                    'target': 'generated_file',
                    'reason_code': 'ask_before_files',
                }
            ],
        },
    }
    plan = _build_agent_plan(original_request, 'phase-11a-csv-artifact')
    intent = build_deliverable_intent(
        original_request,
        plan,
        requested_output=requested_output,
        directive_snapshot=directive_snapshot,
    )
    ledger = create_evidence_ledger_from_plan(
        plan,
        user_message_id='phase-11a-csv-message',
        requested_output=requested_output,
        deliverable_intent=intent,
        original_request=original_request,
    )
    requirement_ids = _source_requirement_ids(ledger, 'selected_agent')
    add_evidence_source(
        ledger,
        'selected_agent',
        'succeeded',
        source_id='selected_agent',
        summary='The selected agent returned authorized project rows.',
        requirement_ids=requirement_ids,
        authorization_status='authorized',
    )
    add_fact(
        ledger,
        'Project Apollo is green and Project Borealis is at risk.',
        ['selected_agent'],
        requirement_ids=requirement_ids,
        confidence='source_supported',
    )
    set_evidence_ledger_status(ledger, 'ready')
    materialized = materialize_deliverable_plan_for_ledger(ledger)
    synthesis_request = create_central_synthesis_request(original_request, plan, ledger)

    assert intent['response_mode'] == 'summary_with_primary_artifact'
    assert intent['provisional_deliverables'][0]['adapter_id'] == 'csv_structured_artifact'
    assert materialized['deliverables'][0]['required'] is True
    assert materialized['deliverables'][0]['format'] == 'csv'
    assert materialized['deliverables'][0]['approval_required'] is True
    assert materialized['deliverables'][0]['approval']['state'] == 'required'
    assert synthesis_request['deliverable_intent']['directive_constraints']['revision'] == 'memory-revision-7'
    assert synthesis_request['materialized_deliverable_plan']['deliverables'][0]['format'] == 'csv'
    assert synthesis_request['materialized_deliverable_plan']['evidence_snapshot']['ledger_status'] == 'ready'
    assert 'one row per project' in json.dumps(synthesis_request)


def test_partial_evidence_override_creates_distinct_plan_revision():
    original_request = 'Create a CSV from selected agent evidence even if one source is missing.'
    requested_output = {'type': 'generated_file', 'format': 'csv'}
    plan = _build_agent_plan(original_request, 'phase-11a-partial-evidence')
    intent = build_deliverable_intent(
        original_request,
        plan,
        requested_output=requested_output,
    )
    ledger = create_evidence_ledger_from_plan(
        plan,
        user_message_id='phase-11a-partial-message',
        requested_output=requested_output,
        deliverable_intent=intent,
        original_request=original_request,
    )
    requirement_ids = _source_requirement_ids(ledger, 'selected_agent')
    add_evidence_source(
        ledger,
        'selected_agent',
        'not_found',
        source_id='selected_agent',
        summary='The selected agent did not return usable rows.',
        requirement_ids=requirement_ids,
        authorization_status='authorized',
    )
    missing = add_missing_evidence(
        ledger,
        requirement_ids[0] if requirement_ids else None,
        'selected_agent',
        'not_found',
        'The selected agent did not return usable rows.',
        source_id='selected_agent',
    )
    set_evidence_ledger_status(ledger, 'partial')
    materialized = materialize_deliverable_plan(
        intent,
        ledger,
        materialized_plan_revision=2,
        partial_evidence_override={'decision_ref': 'accepted-limited-output'},
    )

    assert materialized['materialized_plan_revision'] == 2
    assert materialized['deliverables'][0]['status'] == 'partial'
    assert materialized['partial_evidence_override']['decision_ref'] == 'accepted-limited-output'
    assert materialized['partial_evidence_override']['missing_or_failed_ids'] == [missing['id']]
    assert materialized['partial_evidence_override']['disclosure_required'] is True


def test_unsupported_explicit_file_is_failed_not_silently_removed():
    original_request = 'Create a PowerPoint deck from this answer.'
    requested_output = {'type': 'generated_file', 'format': 'pptx'}
    plan = build_turn_orchestration_plan(
        original_request,
        run_id='phase-11a-unsupported-pptx',
    )
    intent = build_deliverable_intent(
        original_request,
        plan,
        requested_output=requested_output,
    )
    ledger = create_evidence_ledger_from_plan(
        plan,
        user_message_id='phase-11a-unsupported-message',
        requested_output=requested_output,
        deliverable_intent=intent,
        original_request=original_request,
    )
    materialized = materialize_deliverable_plan_for_ledger(ledger)

    assert len(intent['provisional_deliverables']) == 1
    assert intent['provisional_deliverables'][0]['required'] is True
    assert intent['provisional_deliverables'][0]['status'] == 'unsupported'
    assert materialized['deliverables'][0]['required'] is True
    assert materialized['deliverables'][0]['status'] == 'failed'
    assert materialized['deliverables'][0]['reason_codes'] == ['requested_format_not_supported']


if __name__ == '__main__':
    tests = [
        test_inline_answer_intent_persists_without_artifact,
        test_explicit_csv_request_materializes_required_artifact_for_synthesis,
        test_partial_evidence_override_creates_distinct_plan_revision,
        test_unsupported_explicit_file_is_failed_not_silently_removed,
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