#!/usr/bin/env python3
# test_chat_capability_choice_contract.py
"""
Functional test for durable chat capability decisions and resume claims.
Version: 0.250.066
Implemented in: 0.250.066

This test ensures capability proposals are bounded, decisions are allowlisted
and idempotent, resume claims cannot execute twice, and external queries omit
unapproved personal data.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SINGLE_APP_ROOT = REPO_ROOT / 'application' / 'single_app'
sys.path.insert(0, str(SINGLE_APP_ROOT))

from functions_chat_capabilities import (  # noqa: E402
    build_capability_recommendation,
    build_governed_capability_inventory,
    classify_capability_requirements,
)
from functions_chat_capability_choices import (  # noqa: E402
    CapabilityChoiceError,
    add_sensitive_external_query_options,
    apply_capability_choice_decision,
    build_capability_choice_proposal,
    build_capability_provenance,
    build_minimized_external_query,
    claim_capability_choice_resume,
    complete_capability_choice_resume,
    fail_capability_choice_resume,
    revalidate_capability_choice,
)


NOW = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)


def _inventory(*, web_state='unselected', deep_state='unselected'):
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
    if web_state != 'unselected':
        if web_state == 'unavailable':
            resolved['web_search']['available'] = False
        elif web_state == 'unauthorized':
            resolved['web_search']['authorized'] = False
        elif web_state == 'policy_blocked':
            resolved['web_search']['governance_mode'] = 'blocked'
    if deep_state != 'unselected':
        if deep_state == 'unavailable':
            resolved['deep_research']['available'] = False
        elif deep_state == 'unauthorized':
            resolved['deep_research']['authorized'] = False
        elif deep_state == 'policy_blocked':
            resolved['deep_research']['governance_mode'] = 'blocked'
    return build_governed_capability_inventory(resolved_capabilities=resolved)


def _proposal(inventory=None, now=NOW):
    inventory = inventory or _inventory()
    requirements = classify_capability_requirements(
        'What are the current Fairfax County zoning rules?'
    )
    recommendation = build_capability_recommendation(inventory, requirements)
    return build_capability_choice_proposal(
        recommendation,
        run_id='parent-run',
        conversation_id='conversation-1',
        user_message_id='user-message-1',
        assistant_message_id='proposal-1',
        now=now,
    )


def test_approval_is_allowlisted_and_idempotent():
    proposal = _proposal()
    approved, idempotent = apply_capability_choice_decision(
        proposal,
        'deep_research',
        actor_user_id='user-1',
        now=NOW,
    )
    replayed, replay_idempotent = apply_capability_choice_decision(
        approved,
        'deep_research',
        actor_user_id='user-1',
        now=NOW + timedelta(seconds=1),
    )

    assert approved['status'] == 'approved'
    assert approved['decision']['capability_ids'] == ['deep_research']
    assert approved['decision']['effective_capability_ids'] == [
        'deep_research',
        'web_search',
    ]
    assert approved['resume']['status'] == 'pending'
    assert idempotent is False
    assert replay_idempotent is True
    assert replayed == approved


def test_decline_is_durable_and_conflicting_decision_is_rejected():
    proposal = _proposal()
    declined, _ = apply_capability_choice_decision(
        proposal,
        'continue_without_capabilities',
        actor_user_id='user-1',
        now=NOW,
    )

    assert declined['status'] == 'declined'
    assert declined['decision']['capability_ids'] == []
    try:
        apply_capability_choice_decision(
            declined,
            'web_search',
            actor_user_id='user-1',
            now=NOW,
        )
        raise AssertionError('conflicting decisions must fail')
    except CapabilityChoiceError as exc:
        assert exc.code == 'decision_conflict'


def test_forged_and_expired_choices_are_rejected():
    proposal = _proposal()
    try:
        apply_capability_choice_decision(
            proposal,
            'forged_capability',
            actor_user_id='user-1',
            now=NOW,
        )
        raise AssertionError('forged options must fail')
    except CapabilityChoiceError as exc:
        assert exc.code == 'option_not_allowlisted'

    try:
        apply_capability_choice_decision(
            proposal,
            'web_search',
            actor_user_id='user-1',
            now=NOW + timedelta(days=2),
        )
        raise AssertionError('expired proposals must fail')
    except CapabilityChoiceError as exc:
        assert exc.code == 'proposal_expired'


def test_revalidation_rejects_revoked_capability():
    proposal = _proposal()
    approved, _ = apply_capability_choice_decision(
        proposal,
        'web_search',
        actor_user_id='user-1',
        now=NOW,
    )
    assert revalidate_capability_choice(approved, _inventory()) is True

    try:
        revalidate_capability_choice(
            approved,
            _inventory(web_state='unauthorized'),
        )
        raise AssertionError('revoked capabilities must fail revalidation')
    except CapabilityChoiceError as exc:
        assert exc.code == 'capability_unauthorized'

    deep_approved, _ = apply_capability_choice_decision(
        _proposal(),
        'deep_research',
        actor_user_id='user-1',
        now=NOW,
    )
    blocked_bundle_inventory = _inventory()
    web_search_entry = next(
        entry
        for entry in blocked_bundle_inventory['capabilities']
        if entry['id'] == 'web_search'
    )
    web_search_entry.update({
        'state': 'policy_blocked',
        'discoverable': False,
    })
    try:
        revalidate_capability_choice(deep_approved, blocked_bundle_inventory)
        raise AssertionError('blocked bundle dependencies must fail revalidation')
    except CapabilityChoiceError as exc:
        assert exc.code == 'capability_policy_blocked'


def test_resume_claim_and_completion_are_idempotent():
    approved, _ = apply_capability_choice_decision(
        _proposal(),
        'web_search',
        actor_user_id='user-1',
        now=NOW,
    )
    claimed, claim_idempotent = claim_capability_choice_resume(
        approved,
        now=NOW,
        execution_id='execution-1',
        child_run_id='child-run-1',
    )
    assert claim_idempotent is False
    assert claimed['resume']['status'] == 'running'

    try:
        claim_capability_choice_resume(
            claimed,
            now=NOW + timedelta(seconds=1),
            execution_id='execution-2',
        )
        raise AssertionError('a live resume lease must prevent duplicate execution')
    except CapabilityChoiceError as exc:
        assert exc.code == 'resume_in_progress'

    completed, completed_idempotent = complete_capability_choice_resume(
        claimed,
        execution_id='execution-1',
        assistant_message_id='assistant-1',
        now=NOW + timedelta(seconds=2),
    )
    replayed, replay_idempotent = claim_capability_choice_resume(
        completed,
        now=NOW + timedelta(seconds=3),
    )
    assert completed_idempotent is False
    assert replay_idempotent is True
    assert replayed['resume']['assistant_message_id'] == 'assistant-1'


def test_failed_resume_can_be_reclaimed_after_release():
    approved, _ = apply_capability_choice_decision(
        _proposal(),
        'web_search',
        actor_user_id='user-1',
        now=NOW,
    )
    claimed, _ = claim_capability_choice_resume(
        approved,
        now=NOW,
        execution_id='execution-1',
    )
    failed, idempotent = fail_capability_choice_resume(
        claimed,
        execution_id='execution-1',
        error_type='network failure',
        now=NOW + timedelta(seconds=1),
    )
    reclaimed, _ = claim_capability_choice_resume(
        failed,
        now=NOW + timedelta(seconds=2),
        execution_id='execution-2',
    )

    assert idempotent is False
    assert failed['resume']['status'] == 'failed'
    assert failed['resume']['error_type'] == 'network_failure'
    assert reclaimed['resume']['execution_id'] == 'execution-2'


def test_external_query_omits_unapproved_personal_data():
    message = (
        'Check current Fairfax County zoning and parcel records for '
        '1234 Main Street, Fairfax VA 22030. Email me at person@example.com.'
    )
    minimized = build_minimized_external_query(message)
    approved = build_minimized_external_query(
        message,
        include_sensitive_inputs=True,
    )

    assert '1234 Main Street' not in minimized['query']
    assert 'person@example.com' not in minimized['query']
    assert minimized['source'] == 'current_message_only'
    assert minimized['conversation_history_included'] is False
    assert minimized['workspace_content_included'] is False
    assert 'street_address' in minimized['omitted_sensitive_input_types']
    assert '1234 Main Street' in approved['query']
    assert 'person@example.com' not in approved['query']
    assert 'email_address' in approved['omitted_sensitive_input_types']


def test_parcel_lookup_adds_explicit_sensitive_option():
    recommendation = build_capability_recommendation(
        _inventory(),
        classify_capability_requirements(
            'Check current parcel rules for 1234 Main Street, Fairfax VA 22030.'
        ),
    )
    updated = add_sensitive_external_query_options(
        recommendation,
        'Check current parcel rules for 1234 Main Street, Fairfax VA 22030.',
    )
    option_ids = [option['id'] for option in updated['options']]

    assert 'deep_research' in option_ids
    assert 'deep_research_with_sensitive_inputs' in option_ids
    assert updated['recommended_option_id'] == 'deep_research_with_sensitive_inputs'
    sensitive_option = next(
        option
        for option in updated['options']
        if option['id'] == 'deep_research_with_sensitive_inputs'
    )
    assert sensitive_option['sensitive_input_types'] == ['street_address']


def test_provenance_keeps_each_stage_separate():
    proposal = _proposal()
    approved, _ = apply_capability_choice_decision(
        proposal,
        'web_search',
        actor_user_id='user-1',
        now=NOW,
    )
    provenance = build_capability_provenance(
        selection_snapshot={'toggles': {'web_search': False}},
        capability_inventory=_inventory(),
        proposal=proposal,
        decisions=[approved['decision']],
        effective_capabilities=[
            {'id': 'web_search', 'origin': 'discovery_approved', 'required': True},
        ],
    )

    assert provenance['selection_snapshot']['toggles']['web_search'] is False
    assert provenance['version'] == 2
    assert provenance['automatic_capability_root_ids'] == []
    assert provenance['automatic_capability_effective_ids'] == []
    assert provenance['proposed_capabilities']['status'] == 'pending'
    assert provenance['capability_decisions'][0]['status'] == 'approved'
    assert provenance['effective_capabilities'] == [{
        'id': 'web_search',
        'origin': 'discovery_approved',
        'required': True,
    }]


if __name__ == '__main__':
    tests = [
        test_approval_is_allowlisted_and_idempotent,
        test_decline_is_durable_and_conflicting_decision_is_rejected,
        test_forged_and_expired_choices_are_rejected,
        test_revalidation_rejects_revoked_capability,
        test_resume_claim_and_completion_are_idempotent,
        test_failed_resume_can_be_reclaimed_after_release,
        test_external_query_omits_unapproved_personal_data,
        test_parcel_lookup_adds_explicit_sensitive_option,
        test_provenance_keeps_each_stage_separate,
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