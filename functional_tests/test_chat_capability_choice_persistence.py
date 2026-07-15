#!/usr/bin/env python3
# test_chat_capability_choice_persistence.py
"""
Functional test for conditional capability-choice persistence.
Version: 0.250.066
Implemented in: 0.250.066

This test ensures persisted decisions and resume claims use exact conversation
partitions, honor ETags, and cannot execute the same capability choice twice.
"""

import copy
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
    build_capability_choice_proposal,
    build_capability_provenance,
)
from functions_chat_capability_persistence import (  # noqa: E402
    persist_capability_decision,
    persist_capability_resume_claim,
    persist_capability_resume_completion,
    read_capability_proposal_message,
)


NOW = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)


class ConditionalConflict(Exception):
    status_code = 412


class FakeContainer:
    def __init__(self, message):
        self.message = copy.deepcopy(message)
        self.version = 1
        self.replace_count = 0
        self.force_one_conflict = False
        self.message['_etag'] = str(self.version)

    def read_item(self, *, item, partition_key):
        if item != self.message['id'] or partition_key != self.message['conversation_id']:
            raise KeyError(item)
        return copy.deepcopy(self.message)

    def replace_item(self, *, item, body, etag, match_condition):
        del match_condition
        if self.force_one_conflict:
            self.force_one_conflict = False
            raise ConditionalConflict()
        if item != self.message['id'] or etag != self.message['_etag']:
            raise ConditionalConflict()
        self.version += 1
        self.replace_count += 1
        self.message = copy.deepcopy(body)
        self.message['_etag'] = str(self.version)
        return copy.deepcopy(self.message)


def _inventory():
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
    return build_governed_capability_inventory(resolved_capabilities=resolved)


def _container():
    inventory = _inventory()
    recommendation = build_capability_recommendation(
        inventory,
        classify_capability_requirements('What are the current county rules?'),
    )
    proposal = build_capability_choice_proposal(
        recommendation,
        run_id='run-1',
        conversation_id='conversation-1',
        user_message_id='user-message-1',
        assistant_message_id='proposal-1',
        now=NOW,
    )
    provenance = build_capability_provenance(
        selection_snapshot={'toggles': {'web_search': False}},
        capability_inventory=inventory,
        proposal=proposal,
        effective_capabilities=[],
    )
    return FakeContainer({
        'id': 'proposal-1',
        'conversation_id': 'conversation-1',
        'role': 'assistant',
        'content': 'Choose how to continue.',
        'metadata': {
            'capability_proposal': proposal,
            'capability_provenance': provenance,
        },
    })


def test_decision_retries_conditional_conflict_and_replays_idempotently():
    container = _container()
    container.force_one_conflict = True
    _, approved, idempotent = persist_capability_decision(
        container,
        conversation_id='conversation-1',
        proposal_id='proposal-1',
        option_id='web_search',
        actor_user_id='user-1',
        refreshed_inventory=_inventory(),
        now=NOW,
    )
    _, replayed, replay_idempotent = persist_capability_decision(
        container,
        conversation_id='conversation-1',
        proposal_id='proposal-1',
        option_id='web_search',
        actor_user_id='user-1',
        refreshed_inventory=_inventory(),
        now=NOW,
    )

    assert approved['status'] == 'approved'
    assert idempotent is False
    assert replay_idempotent is True
    assert replayed == approved
    assert container.replace_count == 1
    assert container.message['metadata']['capability_provenance']['capability_decisions'][0]['option_id'] == 'web_search'


def test_conflicting_decision_never_replaces_message():
    container = _container()
    persist_capability_decision(
        container,
        conversation_id='conversation-1',
        proposal_id='proposal-1',
        option_id='web_search',
        actor_user_id='user-1',
        refreshed_inventory=_inventory(),
        now=NOW,
    )
    try:
        persist_capability_decision(
            container,
            conversation_id='conversation-1',
            proposal_id='proposal-1',
            option_id='deep_research',
            actor_user_id='user-1',
            refreshed_inventory=_inventory(),
            now=NOW,
        )
        raise AssertionError('conflicting choice must fail')
    except CapabilityChoiceError as exc:
        assert exc.code == 'decision_conflict'
    assert container.replace_count == 1


def test_resume_claim_is_single_execution_and_completion_is_durable():
    container = _container()
    persist_capability_decision(
        container,
        conversation_id='conversation-1',
        proposal_id='proposal-1',
        option_id='web_search',
        actor_user_id='user-1',
        refreshed_inventory=_inventory(),
        now=NOW,
    )
    _, claimed, _ = persist_capability_resume_claim(
        container,
        conversation_id='conversation-1',
        proposal_id='proposal-1',
        refreshed_inventory=_inventory(),
        now=NOW,
        execution_id='execution-1',
        child_run_id='child-run-1',
    )
    assert claimed['resume']['status'] == 'running'

    try:
        persist_capability_resume_claim(
            container,
            conversation_id='conversation-1',
            proposal_id='proposal-1',
            refreshed_inventory=_inventory(),
            now=NOW,
            execution_id='execution-2',
        )
        raise AssertionError('duplicate live claim must fail')
    except CapabilityChoiceError as exc:
        assert exc.code == 'resume_in_progress'

    _, completed, _ = persist_capability_resume_completion(
        container,
        conversation_id='conversation-1',
        proposal_id='proposal-1',
        execution_id='execution-1',
        assistant_message_id='assistant-1',
        now=NOW,
    )
    assert completed['resume']['status'] == 'completed'
    assert completed['resume']['assistant_message_id'] == 'assistant-1'


def test_exact_partition_and_message_shape_are_enforced():
    container = _container()
    try:
        read_capability_proposal_message(
            container,
            conversation_id='conversation-2',
            proposal_id='proposal-1',
        )
        raise AssertionError('foreign partitions must fail')
    except KeyError:
        pass

    container.message['role'] = 'user'
    try:
        read_capability_proposal_message(
            container,
            conversation_id='conversation-1',
            proposal_id='proposal-1',
        )
        raise AssertionError('non-assistant proposal messages must fail')
    except CapabilityChoiceError as exc:
        assert exc.code == 'proposal_role_invalid'


def test_expired_and_revoked_states_are_persisted():
    expired_container = _container()
    expired_container.message['metadata']['capability_proposal']['expires_at'] = (
        NOW - timedelta(seconds=1)
    ).isoformat()
    try:
        persist_capability_decision(
            expired_container,
            conversation_id='conversation-1',
            proposal_id='proposal-1',
            option_id='web_search',
            actor_user_id='user-1',
            refreshed_inventory=_inventory(),
            now=NOW,
        )
        raise AssertionError('expired proposal must fail')
    except CapabilityChoiceError as exc:
        assert exc.code == 'proposal_expired'
    assert expired_container.message['metadata']['capability_proposal']['status'] == 'expired'

    revoked_container = _container()
    revoked_inventory = copy.deepcopy(_inventory())
    web_search = next(
        capability
        for capability in revoked_inventory['capabilities']
        if capability['id'] == 'web_search'
    )
    web_search.update({
        'state': 'unauthorized',
        'authorized': False,
        'discoverable': False,
    })
    try:
        persist_capability_decision(
            revoked_container,
            conversation_id='conversation-1',
            proposal_id='proposal-1',
            option_id='web_search',
            actor_user_id='user-1',
            refreshed_inventory=revoked_inventory,
            now=NOW,
        )
        raise AssertionError('revoked proposal must fail')
    except CapabilityChoiceError as exc:
        assert exc.code == 'capability_unauthorized'
    stored_proposal = revoked_container.message['metadata']['capability_proposal']
    assert stored_proposal['status'] == 'invalidated'
    assert stored_proposal['decision']['status'] == 'invalidated'
    assert stored_proposal['invalidation_reason'] == 'capability_unauthorized'


def test_approved_choice_expires_before_unclaimed_resume():
    container = _container()
    persist_capability_decision(
        container,
        conversation_id='conversation-1',
        proposal_id='proposal-1',
        option_id='web_search',
        actor_user_id='user-1',
        refreshed_inventory=_inventory(),
        now=NOW,
    )
    try:
        persist_capability_resume_claim(
            container,
            conversation_id='conversation-1',
            proposal_id='proposal-1',
            refreshed_inventory=_inventory(),
            now=NOW + timedelta(days=2),
        )
        raise AssertionError('expired approved choice must not resume')
    except CapabilityChoiceError as exc:
        assert exc.code == 'proposal_expired'
    proposal = container.message['metadata']['capability_proposal']
    assert proposal['status'] == 'invalidated'
    assert proposal['resume']['status'] == 'failed'
    assert proposal['invalidation_reason'] == 'proposal_expired'


if __name__ == '__main__':
    tests = [
        test_decision_retries_conditional_conflict_and_replays_idempotently,
        test_conflicting_decision_never_replaces_message,
        test_resume_claim_is_single_execution_and_completion_is_durable,
        test_exact_partition_and_message_shape_are_enforced,
        test_expired_and_revoked_states_are_persisted,
        test_approved_choice_expires_before_unclaimed_resume,
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