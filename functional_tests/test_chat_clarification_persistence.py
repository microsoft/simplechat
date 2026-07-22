#!/usr/bin/env python3
# test_chat_clarification_persistence.py
"""
Functional test for durable structured chat clarification.
Version: 0.250.076
Implemented in: 0.250.076

This test ensures server-authored clarification checkpoints are allowlisted,
expire predictably, and resolve idempotently with optimistic concurrency.
"""

import copy
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SINGLE_APP_ROOT = REPO_ROOT / 'application' / 'single_app'
sys.path.insert(0, str(SINGLE_APP_ROOT))

from functions_chat_clarifications import (  # noqa: E402
    CHAT_CLARIFICATION_QUESTIONS,
    ChatClarificationError,
    apply_chat_clarification_response,
    build_chat_clarification,
    claim_chat_clarification_response,
    complete_chat_clarification_response,
    persist_chat_clarification_expiry,
    persist_chat_clarification_invalidation,
    persist_chat_clarification_response_claim,
    persist_chat_clarification_response_completion,
    persist_chat_clarification_response,
    read_chat_clarification_message,
    validate_chat_clarification_retry,
)


NOW = datetime(2026, 7, 17, 12, 0, tzinfo=timezone.utc)


class _ConditionalConflict(Exception):
    status_code = 412


class _FakeContainer:
    def __init__(self, message, *, conflicts=0):
        self.message = copy.deepcopy(message)
        self.conflicts = conflicts
        self.replace_calls = 0

    def read_item(self, *, item, partition_key):
        assert item == self.message['id']
        assert partition_key == self.message['conversation_id']
        return copy.deepcopy(self.message)

    def replace_item(self, *, item, body, etag, match_condition):
        assert item == self.message['id']
        assert etag == self.message['_etag']
        assert match_condition is not None
        self.replace_calls += 1
        if self.conflicts:
            self.conflicts -= 1
            raise _ConditionalConflict('etag conflict')
        updated = copy.deepcopy(body)
        updated['_etag'] = f'etag-{self.replace_calls + 1}'
        self.message = updated
        return copy.deepcopy(updated)


def _clarification(
    code='jurisdiction_required',
    options=None,
    now=NOW,
    ttl_seconds=300,
):
    return build_chat_clarification(
        {
            'code': code,
            'option_values': list(options or []),
        },
        parent_run_id='parent-run-1',
        conversation_id='conversation-1',
        source_user_message_id='user-message-1',
        source_thread_id='thread-1',
        assistant_message_id='clarification-1',
        now=now,
        ttl_seconds=ttl_seconds,
    )


def _message(clarification):
    return {
        'id': clarification['clarification_id'],
        'conversation_id': 'conversation-1',
        'role': 'assistant',
        'content': clarification['question'],
        '_etag': 'etag-1',
        'metadata': {
            'awaiting_user_clarification': True,
            'chat_clarification': copy.deepcopy(clarification),
        },
    }


def test_all_clarification_codes_use_fixed_server_questions():
    for code, question in CHAT_CLARIFICATION_QUESTIONS.items():
        clarification = _clarification(code)
        assert clarification['code'] == code
        assert clarification['question'] == question
        assert clarification['status'] == 'pending'
        assert clarification['clarification_budget_used'] == 1
        assert clarification['_source_user_message_id'] == 'user-message-1'
        assert clarification['_source_thread_id'] == 'thread-1'

    try:
        _clarification('execute_arbitrary_tool')
        raise AssertionError('unknown clarification codes must fail closed')
    except ChatClarificationError as exc:
        assert exc.code == 'invalid_clarification_code'


def test_response_resolution_is_idempotent_and_conflicts_fail():
    clarification = _clarification(
        'source_scope_required',
        ['My workspace', 'Public web', 'Both'],
    )
    resolved, idempotent = apply_chat_clarification_response(
        clarification,
        response_user_message_id='user-message-2',
        response_text='Both',
        child_run_id='child-run-1',
        now=NOW + timedelta(seconds=5),
    )
    replayed, replay_idempotent = apply_chat_clarification_response(
        resolved,
        response_user_message_id='user-message-2',
        response_text='Both',
        child_run_id='child-run-1',
        now=NOW + timedelta(seconds=6),
    )

    assert idempotent is False
    assert replay_idempotent is True
    assert replayed == resolved
    assert resolved['status'] == 'resolved'
    assert resolved['response_mode'] == 'option'
    assert resolved['child_run_id'] == 'child-run-1'
    assert resolved['_response_user_message_id'] == 'user-message-2'
    assert resolved['_response_hash']
    assert 'Both' not in resolved.values()

    try:
        apply_chat_clarification_response(
            resolved,
            response_user_message_id='different-user-message',
            response_text='Both',
            now=NOW + timedelta(seconds=6),
        )
        raise AssertionError('same text from a new message is not an idempotent replay')
    except ChatClarificationError as exc:
        assert exc.code == 'clarification_response_conflict'


def test_retry_validator_preserves_exact_response_identity_only():
    claimed, _ = claim_chat_clarification_response(
        _clarification(ttl_seconds=7200),
        response_user_message_id='user-message-2',
        response_text='Virginia',
        child_run_id='child-run-1',
        response_thread_id='thread-2',
        now=NOW + timedelta(seconds=5),
    )
    response_message = {
        'id': 'user-message-2',
        'role': 'user',
        'content': 'Virginia',
    }

    recovery = validate_chat_clarification_retry(
        claimed,
        response_message,
        proposed_text='Virginia',
        now=NOW + timedelta(seconds=6),
    )
    assert recovery == {
        'mode': 'recover',
        'response_user_message_id': 'user-message-2',
        'response_thread_id': 'thread-2',
        'child_run_id': 'child-run-1',
    }

    resolved, _ = complete_chat_clarification_response(
        claimed,
        response_user_message_id='user-message-2',
        child_run_id='child-run-1',
        now=NOW + timedelta(seconds=6),
    )
    assert validate_chat_clarification_retry(
        resolved,
        response_message,
        proposed_text='Virginia',
        now=NOW + timedelta(seconds=7),
    )['mode'] == 'replay'

    for proposed_text, expected_code in (
        ('Maryland', 'clarification_response_conflict'),
        ('Virginia', 'clarification_expired'),
    ):
        candidate = copy.deepcopy(resolved)
        if expected_code == 'clarification_expired':
            candidate['status'] = 'expired'
        try:
            validate_chat_clarification_retry(
                candidate,
                response_message,
                proposed_text=proposed_text,
                now=NOW + timedelta(seconds=8),
            )
            raise AssertionError('invalid clarification retry must fail')
        except ChatClarificationError as exc:
            assert exc.code == expected_code

    try:
        apply_chat_clarification_response(
            resolved,
            response_user_message_id='user-message-3',
            response_text='Public web',
            now=NOW + timedelta(seconds=7),
        )
        raise AssertionError('conflicting clarification responses must fail')
    except ChatClarificationError as exc:
        assert exc.code == 'clarification_response_conflict'


def test_free_text_response_is_linked_without_persisting_answer():
    resolved, _ = apply_chat_clarification_response(
        _clarification(),
        response_user_message_id='user-message-2',
        response_text='Virginia and Fairfax County',
        now=NOW + timedelta(seconds=5),
    )

    assert resolved['response_mode'] == 'free_text'
    assert 'Virginia and Fairfax County' not in str(resolved)


def test_response_lease_blocks_duplicates_and_reclaims_after_process_loss():
    claimed, idempotent = claim_chat_clarification_response(
        _clarification(ttl_seconds=7200),
        response_user_message_id='user-message-2',
        response_text='Virginia',
        child_run_id='child-run-1',
        response_thread_id='thread-2',
        now=NOW + timedelta(seconds=5),
    )
    assert idempotent is False
    assert claimed['status'] == 'resolving'
    assert claimed['lease_expires_at']

    try:
        claim_chat_clarification_response(
            claimed,
            response_user_message_id='duplicate-user-message',
            response_text='Virginia',
            child_run_id='duplicate-child-run',
            response_thread_id='duplicate-thread',
            now=NOW + timedelta(seconds=6),
        )
        raise AssertionError('a live clarification lease must block duplicate planning')
    except ChatClarificationError as exc:
        assert exc.code == 'clarification_response_in_progress'

    try:
        claim_chat_clarification_response(
            claimed,
            response_user_message_id='recovered-user-message',
            response_text='Virginia',
            child_run_id='replacement-child-run',
            response_thread_id='replacement-thread',
            now=NOW + timedelta(minutes=31),
        )
        raise AssertionError('lease recovery must require the exact response message')
    except ChatClarificationError as exc:
        assert exc.code == 'clarification_response_conflict'

    reclaimed, reclaim_idempotent = claim_chat_clarification_response(
        claimed,
        response_user_message_id='user-message-2',
        response_text='Virginia',
        child_run_id='replacement-child-run',
        response_thread_id='replacement-thread',
        now=NOW + timedelta(minutes=31),
    )
    assert reclaim_idempotent is False
    assert reclaimed['_response_user_message_id'] == 'user-message-2'
    assert reclaimed['_response_thread_id'] == 'thread-2'
    assert reclaimed['child_run_id'] == 'child-run-1'

    completed, completion_idempotent = complete_chat_clarification_response(
        reclaimed,
        response_user_message_id='user-message-2',
        child_run_id='child-run-1',
        now=NOW + timedelta(minutes=31, seconds=1),
    )
    assert completion_idempotent is False
    assert completed['status'] == 'resolved'
    assert completed['lease_expires_at'] is None


def test_claim_and_completion_persistence_use_separate_etag_transitions():
    container = _FakeContainer(_message(_clarification()), conflicts=1)
    _, claimed, claim_idempotent = persist_chat_clarification_response_claim(
        container,
        conversation_id='conversation-1',
        clarification_id='clarification-1',
        response_user_message_id='user-message-2',
        response_text='Virginia',
        child_run_id='child-run-1',
        now=NOW + timedelta(seconds=5),
    )
    _, completed, completion_idempotent = (
        persist_chat_clarification_response_completion(
            container,
            conversation_id='conversation-1',
            clarification_id='clarification-1',
            response_user_message_id='user-message-2',
            child_run_id='child-run-1',
            now=NOW + timedelta(seconds=6),
        )
    )

    assert claim_idempotent is False
    assert completion_idempotent is False
    assert claimed['status'] == 'resolving'
    assert completed['status'] == 'resolved'
    assert container.replace_calls == 3


def test_completion_rejects_stale_generation_and_invalid_response():
    claimed, _ = claim_chat_clarification_response(
        _clarification(ttl_seconds=7200),
        response_user_message_id='user-message-2',
        response_text='Virginia',
        child_run_id='child-run-1',
        response_thread_id='thread-2',
        now=NOW + timedelta(seconds=5),
    )
    stale_container = _FakeContainer(_message(claimed))
    try:
        persist_chat_clarification_response_completion(
            stale_container,
            conversation_id='conversation-1',
            clarification_id='clarification-1',
            response_user_message_id='user-message-2',
            child_run_id='child-run-1',
            expected_claimed_at='different-claim-generation',
            now=NOW + timedelta(seconds=6),
        )
        raise AssertionError('stale completion must not resolve a renewed claim')
    except ChatClarificationError as exc:
        assert exc.code == 'clarification_response_claim_mismatch'
    assert stale_container.message['metadata']['chat_clarification'][
        'status'
    ] == 'resolving'

    invalid_container = _FakeContainer(_message(claimed))

    def reject_response(_clarification):
        raise KeyError('response-user-message')

    try:
        persist_chat_clarification_response_completion(
            invalid_container,
            conversation_id='conversation-1',
            clarification_id='clarification-1',
            response_user_message_id='user-message-2',
            child_run_id='child-run-1',
            expected_claimed_at=claimed['claimed_at'],
            response_validator=reject_response,
            now=NOW + timedelta(seconds=6),
        )
        raise AssertionError('invalid response must terminalize completion')
    except ChatClarificationError as exc:
        assert exc.code == 'clarification_response_claim_mismatch'
    invalidated = invalid_container.message['metadata']['chat_clarification']
    assert invalidated['status'] == 'expired'
    assert invalidated['invalidation_reason'] == (
        'clarification_response_claim_mismatch'
    )


def test_claim_source_failure_is_durably_invalidated():
    container = _FakeContainer(_message(_clarification()), conflicts=1)

    def reject_source(_clarification):
        raise KeyError('source-user-message')

    try:
        persist_chat_clarification_response_claim(
            container,
            conversation_id='conversation-1',
            clarification_id='clarification-1',
            response_user_message_id='user-message-2',
            response_text='Virginia',
            child_run_id='child-run-1',
            source_validator=reject_source,
            now=NOW + timedelta(seconds=5),
        )
        raise AssertionError('invalid clarification source must fail closed')
    except ChatClarificationError as exc:
        assert exc.code == 'clarification_source_invalid'

    stored = container.message['metadata']['chat_clarification']
    assert stored['status'] == 'expired'
    assert stored['invalidation_reason'] == 'clarification_source_invalid'
    assert stored['lease_expires_at'] is None
    assert container.message['metadata']['awaiting_user_clarification'] is False
    assert container.replace_calls == 2


def test_stale_recovery_claim_cannot_invalidate_renewed_generation():
    stale_claim, _ = claim_chat_clarification_response(
        _clarification(ttl_seconds=7200),
        response_user_message_id='user-message-2',
        response_text='Virginia',
        child_run_id='child-run-1',
        response_thread_id='thread-2',
        now=NOW + timedelta(seconds=5),
    )
    renewed_claim, _ = claim_chat_clarification_response(
        stale_claim,
        response_user_message_id='user-message-2',
        response_text='Virginia',
        child_run_id='child-run-1',
        response_thread_id='thread-2',
        now=NOW + timedelta(minutes=31),
    )
    container = _FakeContainer(_message(renewed_claim))
    source_validations = []

    def reject_source(_clarification):
        source_validations.append(True)
        raise KeyError('source-user-message')

    try:
        persist_chat_clarification_response_claim(
            container,
            conversation_id='conversation-1',
            clarification_id='clarification-1',
            response_user_message_id='user-message-2',
            response_text='Virginia',
            child_run_id='child-run-1',
            response_thread_id='thread-2',
            source_validator=reject_source,
            expected_response_user_message_id=(
                stale_claim['_response_user_message_id']
            ),
            expected_child_run_id=stale_claim['child_run_id'],
            expected_claimed_at=stale_claim['claimed_at'],
            now=NOW + timedelta(minutes=31, seconds=1),
        )
        raise AssertionError('stale recovery must not mutate renewed claim')
    except ChatClarificationError as exc:
        assert exc.code == 'clarification_response_claim_mismatch'

    assert source_validations == []
    stored = container.message['metadata']['chat_clarification']
    assert stored['status'] == 'resolving'
    assert stored['claimed_at'] == renewed_claim['claimed_at']
    assert stored.get('invalidation_reason') is None
    assert container.replace_calls == 0


def test_persistence_retries_etag_and_same_response_replays_once():
    container = _FakeContainer(_message(_clarification()), conflicts=1)
    validated_sources = []

    def validate_source(clarification):
        validated_sources.append(clarification['_source_user_message_id'])

    saved_message, resolved, idempotent = persist_chat_clarification_response(
        container,
        conversation_id='conversation-1',
        clarification_id='clarification-1',
        response_user_message_id='user-message-2',
        response_text='Virginia',
        child_run_id='child-run-1',
        source_validator=validate_source,
        now=NOW + timedelta(seconds=5),
    )
    replay_message, replayed, replay_idempotent = (
        persist_chat_clarification_response(
            container,
            conversation_id='conversation-1',
            clarification_id='clarification-1',
            response_user_message_id='user-message-2',
            response_text='Virginia',
            child_run_id='child-run-1',
            source_validator=validate_source,
            now=NOW + timedelta(seconds=6),
        )
    )

    assert saved_message['metadata']['awaiting_user_clarification'] is False
    assert resolved['status'] == 'resolved'
    assert idempotent is False
    assert replay_idempotent is True
    assert replayed == resolved
    assert replay_message['id'] == 'clarification-1'
    assert container.replace_calls == 2
    assert validated_sources == [
        'user-message-1',
        'user-message-1',
        'user-message-1',
    ]


def test_expiry_is_persisted_and_blocks_response():
    clarification = _clarification(now=NOW - timedelta(minutes=10))
    container = _FakeContainer(_message(clarification))

    try:
        persist_chat_clarification_response(
            container,
            conversation_id='conversation-1',
            clarification_id='clarification-1',
            response_user_message_id='user-message-2',
            response_text='Virginia',
            now=NOW,
        )
        raise AssertionError('expired clarification responses must fail')
    except ChatClarificationError as exc:
        assert exc.code == 'clarification_expired'

    _, persisted = read_chat_clarification_message(
        container,
        conversation_id='conversation-1',
        clarification_id='clarification-1',
    )
    assert persisted['status'] == 'expired'
    assert container.message['metadata']['awaiting_user_clarification'] is False


def test_preflight_expiry_transition_is_idempotent():
    clarification = _clarification(now=NOW - timedelta(minutes=10))
    container = _FakeContainer(_message(clarification), conflicts=1)

    _, expired, idempotent = persist_chat_clarification_expiry(
        container,
        conversation_id='conversation-1',
        clarification_id='clarification-1',
        now=NOW,
    )
    _, replayed, replay_idempotent = persist_chat_clarification_expiry(
        container,
        conversation_id='conversation-1',
        clarification_id='clarification-1',
        now=NOW + timedelta(seconds=1),
    )

    assert idempotent is False
    assert replay_idempotent is True
    assert replayed == expired
    assert expired['status'] == 'expired'
    assert container.message['metadata']['awaiting_user_clarification'] is False


def test_source_invalidation_terminalizes_a_live_response_claim():
    claimed, _ = claim_chat_clarification_response(
        _clarification(ttl_seconds=7200),
        response_user_message_id='user-message-2',
        response_text='Virginia',
        child_run_id='child-run-1',
        response_thread_id='thread-2',
        now=NOW + timedelta(seconds=5),
    )
    container = _FakeContainer(_message(claimed), conflicts=1)

    _, invalidated, idempotent = persist_chat_clarification_invalidation(
        container,
        conversation_id='conversation-1',
        clarification_id='clarification-1',
        reason='clarification_source_invalid',
        now=NOW + timedelta(seconds=6),
    )
    _, replayed, replay_idempotent = persist_chat_clarification_invalidation(
        container,
        conversation_id='conversation-1',
        clarification_id='clarification-1',
        reason='clarification_source_invalid',
        now=NOW + timedelta(seconds=7),
    )

    assert idempotent is False
    assert replay_idempotent is True
    assert replayed == invalidated
    assert invalidated['status'] == 'expired'
    assert invalidated['lease_expires_at'] is None
    assert invalidated['invalidation_reason'] == 'clarification_source_invalid'
    assert container.message['metadata']['awaiting_user_clarification'] is False
