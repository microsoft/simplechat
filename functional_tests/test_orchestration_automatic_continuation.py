#!/usr/bin/env python3
# test_orchestration_automatic_continuation.py
"""
Functional test for automatic continuation of a failed orchestration attempt.
Version: 0.261.462
Implemented in: 0.261.458

This test ensures that a failed attempt is followed by the next one without the user's
sign-off only while that next attempt stays inside the approved plan: the setting is on, the
server already defines the successor, no external action runs again, no confirmation is
needed, the recovery limit is not reached and the attempt does not repeat the failure of the
one before it. It also checks that a click is never held to that rule and that the client
only continues attempts it was following.
"""

import os
import sys

import pytest

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_orchestration_dependency_runtime import runtime  # noqa: E402,F401 (fixture)

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application')
REACTIVE = {'enable_chat_orchestration_reactive_loop': True}


def _progress(runtime):
    import functions_orchestration_progress as progress
    return progress


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding='utf-8') as handle:
        return handle.read()


def _record(run_id='run-1', *, failed=(('calculate', 'calculation_program_invalid'),), **changes):
    record = {
        'id': run_id, 'conversation_id': 'conversation-1', 'status': 'failed', 'attempt_index': 1,
        'failure': {'code': failed[0][1], 'capability_id': 'tabular_analyze'} if failed else None,
        'plan': {'steps': [
            {'step_id': 'find', 'capability_id': 'document_search'},
            {'step_id': 'calculate', 'capability_id': 'tabular_analyze'},
            {'step_id': 'answer', 'capability_id': 'compose'},
        ]},
        'execution_steps': [
            {'step_id': 'find', 'status': 'completed'},
            *[{'step_id': step_id, 'status': 'failed', 'failure': {'code': code}} for step_id, code in failed],
        ],
    }
    record.update(changes)
    return record


def _recovery(**changes):
    recovery = {
        'eligible': True, 'reason_code': None, 'requires_confirmation': False,
        'retry_step_ids': ['calculate', 'answer'], 'reused_step_ids': ['find'],
    }
    recovery.update(changes)
    return recovery


def test_a_failed_attempt_inside_the_approved_plan_continues(runtime):
    progress = _progress(runtime)
    decision, reason = progress.automatic_continuation(_record(), _recovery(), REACTIVE)
    assert reason is None
    assert decision == {'kind': 'retry', 'recovery': 'continue_attempt', 'round': 1, 'round_limit': 2}


def test_the_server_derived_plan_change_continues_as_its_own_kind(runtime):
    progress = _progress(runtime)
    recovery = _recovery(
        eligible=False, reason_code='input_partial_not_recoverable', can_use_available_information=True,
    )
    decision, _reason = progress.automatic_continuation(_record(), recovery, REACTIVE)
    assert decision['kind'] == 'available_information'
    assert decision['recovery'] == 'continue_available_information'


def test_nothing_continues_when_the_setting_is_off(runtime):
    progress = _progress(runtime)
    for settings in ({}, None, {'enable_chat_orchestration_reactive_loop': 'true'}):
        assert progress.automatic_continuation(_record(), _recovery(), settings) == (None, 'disabled')


@pytest.mark.parametrize('record_changes, recovery_changes, reason', [
    ({'status': 'completed'}, {}, 'not_failed'),
    ({'status': 'cancelled'}, {}, 'not_failed'),
    # The user asked for a stop; a failure recorded afterwards is not one to work around.
    ({'cancellation_requested_at': '2026-11-18T00:00:00+00:00'}, {}, 'not_failed'),
    ({}, {'eligible': False, 'reason_code': 'retry_would_repeat'}, 'not_eligible'),
    ({}, {'requires_confirmation': True}, 'confirmation_required'),
    # Missing replay-safety information never authorizes a repeat.
    ({}, {'requires_confirmation': None}, 'confirmation_required'),
    ({'attempt_index': 3}, {}, 'round_limit'),
])
def test_what_stops_an_automatic_continuation(runtime, record_changes, recovery_changes, reason):
    progress = _progress(runtime)
    record = _record(**record_changes)
    assert progress.automatic_continuation(record, _recovery(**recovery_changes), REACTIVE) == (None, reason)


def test_an_external_action_is_never_run_again_unasked(runtime):
    progress = _progress(runtime)
    effect = sorted(runtime.registry.external_effect_capability_ids())[0]
    record = _record()
    record['plan']['steps'][1]['capability_id'] = effect
    assert progress.automatic_continuation(record, _recovery(), REACTIVE) == (None, 'external_effect')
    # The same capability among the steps that are kept, not run again, does not block.
    kept = _record()
    kept['plan']['steps'][0]['capability_id'] = effect
    decision, _reason = progress.automatic_continuation(kept, _recovery(), REACTIVE)
    assert decision is not None


def test_the_recovery_limit_bounds_attempts(runtime):
    progress = _progress(runtime)
    parent = _record('run-1', failed=(('calculate', 'result_invalid'),))
    second = _record('run-2', attempt_index=2, retry_of_run_id='run-1')
    decision, _reason = progress.automatic_continuation(second, _recovery(), REACTIVE, parent=parent)
    assert decision['round'] == 2
    third = _record('run-3', attempt_index=3, retry_of_run_id='run-2')
    assert progress.automatic_continuation(third, _recovery(), REACTIVE, parent=second) == (None, 'round_limit')
    zero = {**REACTIVE, 'chat_orchestration_max_recovery_rounds': 0}
    assert progress.automatic_continuation(_record(), _recovery(), zero) == (None, 'round_limit')


def test_repeating_the_previous_failure_is_a_stall(runtime):
    progress = _progress(runtime)
    parent = _record('run-1')
    same = _record('run-2', attempt_index=2, retry_of_run_id='run-1')
    assert progress.automatic_continuation(same, _recovery(), REACTIVE, parent=parent) == (None, 'stalled')
    # A different failure, or the same step failing for another reason, is progress.
    moved = _record('run-2', attempt_index=2, retry_of_run_id='run-1', failed=(('answer', 'completeness_incomplete'),))
    assert progress.automatic_continuation(moved, _recovery(), REACTIVE, parent=parent)[0] is not None
    # History that cannot be read, or is not this attempt's parent, is treated as a repeat.
    assert progress.automatic_continuation(same, _recovery(), REACTIVE, parent=None) == (None, 'stalled')
    other = _record('run-9')
    assert progress.automatic_continuation(same, _recovery(), REACTIVE, parent=other) == (None, 'stalled')


def test_the_ledger_line_is_server_vocabulary(runtime, monkeypatch):
    progress = _progress(runtime)
    logs = []
    monkeypatch.setattr(progress, 'log_event', lambda message, **kwargs: logs.append((message, kwargs.get('extra') or {})))
    record = _record()
    decision, _reason = progress.automatic_continuation(record, _recovery(), REACTIVE)
    progress.log_automatic_continuation(decision, None, record, successor_run_id='run-2')
    progress.log_automatic_continuation(None, 'stalled', record)
    applied, refused = (extra for _message, extra in logs)
    assert applied['recovery'] == 'continue_attempt' and applied['progress_outcome'] == 'applied'
    assert applied['failure_code'] == 'calculation_program_invalid' and applied['round'] == 1
    assert refused['recovery'] is None and refused['progress_outcome'] == 'stalled'
    for _message, extra in logs:
        assert extra['stage'] == 'automatic_continuation'
        assert 'run-1' not in str(extra) and 'run-2' not in str(extra) and 'conversation-1' not in str(extra)


def test_what_the_server_offered_is_recorded_once_per_run(runtime, monkeypatch):
    progress = _progress(runtime)
    logs = []
    monkeypatch.setattr(progress, 'log_event', lambda message, **kwargs: logs.append(kwargs.get('extra') or {}))
    monkeypatch.setattr(progress, '_OFFERS_LOGGED', set())
    record, recovery = _record(), _recovery()
    decision, reason = progress.automatic_continuation(record, recovery, REACTIVE)
    for _read_again in range(3):
        progress.log_continuation_offer(decision, reason, record, recovery)
    assert len(logs) == 1
    assert logs[0]['stage'] == 'automatic_continuation_offer' and logs[0]['progress_outcome'] == 'offered'
    assert logs[0]['recovery'] == 'continue_attempt'
    # Why an attempt was not offered is recorded too, with the server's own reason.
    blocked = _recovery(eligible=False, reason_code='retry_would_repeat')
    decision, reason = progress.automatic_continuation(record, blocked, REACTIVE)
    progress.log_continuation_offer(decision, reason, record, blocked)
    assert logs[1]['progress_outcome'] == 'not_eligible' and logs[1]['recovery_reason'] == 'retry_would_repeat'
    # A live attempt, a run that did not fail and a setting that is off are not answers.
    live = _recovery(eligible=False, reason_code='execution_live')
    progress.log_continuation_offer(None, 'not_eligible', _record('run-2'), live)
    progress.log_continuation_offer(None, 'disabled', _record('run-3'), recovery)
    progress.log_continuation_offer(None, 'not_failed', _record('run-4'), recovery)
    assert len(logs) == 2
    for extra in logs:
        assert 'run-1' not in str(extra) and 'conversation-1' not in str(extra)


def test_the_server_starts_the_next_attempt_and_the_page_only_follows_it():
    controller = _read('v2_ui', 'src', 'lib', 'orchestrationController.ts')
    helper = controller[controller.index('async function continueFailedRunAutomatically('):]
    helper = helper[:helper.index('\n}\n')]
    # The page never asks for a retry here: which conversation is on screen cannot matter.
    assert 'retryOrchestrationRun(' not in helper and 'activeConversationId' in helper
    assert 'loadOrchestrationRecovery(' not in helper
    assert 'record?.latest_attempt_run_id' in helper and 'next.retry_of_run_id !== runId' in helper
    assert 'void reconcileOrchestrationRun(conversationId, nextRunId);' in helper
    # Following is tracked whatever is on screen; only showing its plan needs the conversation open.
    assert helper.index('activeConversationId === conversationId') < helper.index('.beginRun({')
    route = _read('single_app', 'route_backend_orchestration.py')
    assert "log_continuation_offer(decision, reason, record, public.get('recovery'))" in route
    assert '_continue_failed_run(run_id, conversation_id or record[' in route
    stream = route[route.index('def _stream_execution('):route.index('def _prepare_execution_stream(')]
    # After the run is closed and its stream ended, on the worker, with or without a browser.
    assert stream.index('emit(finished)') < stream.index('after()')
    follow = route[route.index('def _continue_failed_run('):route.index('def _validate_retry_context(')]
    assert 'prepare_retry(' in follow and '_validate_retry_context(current, user_id, settings, preparing=True)' in follow
    assert "run_plan({" in follow and 'reactive_loop_enabled(settings)' in follow


def test_the_route_decides_and_a_click_is_not_held_to_the_rule():
    route = _read('single_app', 'route_backend_orchestration.py')
    # The flag is removed before the request reaches the shared retry preparation, so a
    # clicked retry and an automatic one are prepared by the same fenced code.
    assert "data = {key: value for key, value in data.items() if key != 'automatic'}" in route
    assert "if type(data['automatic']) is not bool:" in route
    assert "code='automatic_continuation_unavailable'" in route
    assert "public['recovery'] = {**public['recovery'], 'auto_continue': {'kind': decision['kind']}}" in route
    retry = route[route.index('def orchestration_retry(run_id):'):route.index('def _run_saved_plan(data):')]
    assert retry.index('if automatic:') < retry.index('_validate_retry_context(record, user_id, settings, preparing=True)')
    recovery = _read('single_app', 'functions_orchestration_recovery.py')
    assert "'automatic'" not in recovery


def test_the_client_only_continues_attempts_it_was_following():
    controller = _read('v2_ui', 'src', 'lib', 'orchestrationController.ts')
    helper = controller[controller.index('async function continueFailedRunAutomatically('):]
    helper = helper[:helper.index('\n}\n')]
    assert 'automaticContinuations.has(key)' in helper and 'automaticContinuations.add(key)' in helper
    assert 'if (!nextRunId) return;' in helper
    # Two call sites: the live stream's terminal frame, and a stream this tab lost and re-read.
    assert controller.count('void continueFailedRunAutomatically(conversationId, runId);') == 2
    assert "const continueUnasked = status === 'failed' && Boolean(tracked) && !tracked?.resumed;" in controller
    assert '...(submission.automatic ? { automatic: true } : {}),' in controller
    types = _read('v2_ui', 'src', 'lib', 'orchestration.ts')
    assert "auto_continue?: { kind: 'retry' | 'available_information' };" in types
    # No recovery panel or page load starts work: only the controller calls the helper.
    for name in ('OrchestrationRecoveryNotice.tsx', 'OrchestrationPlanPanel.tsx'):
        assert 'auto_continue' not in _read('v2_ui', 'src', 'components', 'chat', name)


def test_the_scorecard_counts_continuations_and_how_later_attempts_ended():
    import importlib.util

    path = os.path.join(ROOT, '..', 'scripts', 'orchestration_scorecard.py')
    spec = importlib.util.spec_from_file_location('orchestration_scorecard_under_test', path)
    scorecard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scorecard)
    assert 'attempt = toint(customDimensions.sc_attempt_index)' in scorecard.build_query(2)

    def row(message, minute, **fields):
        return {
            'timestamp': f'2026-11-18T10:{minute:02d}:00Z', 'm': message, 'version': '0.261.458',
            'outcome': '', 'failure_code': '', 'capability': '', 'rule': '', 'error_type': '',
            'error_site': '', 'recovery': '', 'progress_outcome': '', 'attempt': None, **fields,
        }

    summary = scorecard.summarize([
        row(scorecard.OUTCOME, 1, outcome='failed', failure_code='result_invalid', capability='tabular_analyze', attempt=1),
        row(scorecard.PROGRESS, 2, recovery='continue_attempt', progress_outcome='applied', failure_code='result_invalid'),
        row(scorecard.OUTCOME, 3, outcome='completed', attempt=2),
        # A step recovery is still counted once, when its step finishes.
        row(scorecard.PROGRESS, 4, recovery='accept_partial_input', progress_outcome='applied', failure_code='input_partial_not_accepted'),
        row(scorecard.PROGRESS, 5, recovery='accept_partial_input', progress_outcome='recovered', failure_code='input_partial_not_accepted'),
    ])['0.261.458']
    assert summary['recoveries'] == {
        'result_invalid -> continue_attempt: applied': 1,
        'input_partial_not_accepted -> accept_partial_input: recovered': 1,
    }
    assert summary['later_attempts'] == {'completed': 1}
    assert (summary['runs'], summary['completed']) == (2, 1)
    assert 'Later attempts, by outcome' in scorecard.render({'0.261.458': summary})


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-q', '-p', 'no:cacheprovider']))
