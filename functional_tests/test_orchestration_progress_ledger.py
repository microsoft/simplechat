#!/usr/bin/env python3
# test_orchestration_progress_ledger.py
"""
Functional test for the orchestration progress ledger and typed recoveries.
Version: 0.261.457
Implemented in: 0.261.457

This test ensures that, with the reactive loop enabled, a step that fails with a typed
failure the server has one recovery for is run again inside the approved plan, that the
loop is bounded by the round limit and by stall detection, that nothing changes when the
setting is off, and that the ledger records server vocabulary only.
"""

import json
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_orchestration_dependency_runtime import (  # noqa: E402,F401 (fixture)
    binding, compose, execute, runtime, source_input,
)

LIMITATION = 'One required source could not be read. PRIVATE-LIMITATION'
REACTIVE = {'enable_chat_orchestration_reactive_loop': True}


def _progress(runtime):
    import functions_orchestration_progress as progress
    return progress


def _case(runtime, settings=None, *, allow_partial=False, replies=('Prepared limited answer.',)):
    return runtime.make([
        compose('upstream'),
        compose('answer', inputs={'draft': source_input('upstream', 'answer', partial=allow_partial)}),
    ], list(replies), final_response=binding('answer'), settings=settings)


def _partial_producer(runtime, calls=None):
    """An upstream step that finishes partial, as an analysis with limitations does."""
    partial = runtime.contracts.Completeness(
        'partial', 1, 1, runtime.contracts.Coverage(2, 1, 'sources'), 'partial',
        ('retained_subset',), (LIMITATION,),
    )

    def produce(step, context, **kwargs):
        if calls is not None:
            calls.append(step['step_id'])
        if step['step_id'] != 'upstream':
            return runtime.composition.adapter_compose(step, context, **kwargs)
        task = context.result_service.persist_task_result(
            producer=context.result_producer(step), role='reason', status='partial',
            outputs=[runtime.NamedOutput('answer', 'markdown-v1', 'Exact retained subset.', partial)],
            sources=[], origin='generated', guard_token=context.result_guard_token_for_step(step['step_id']),
        )
        return runtime.schema.build_step_result(status='partial', task_result=task)

    return produce, partial


def _logs(runtime, monkeypatch):
    logs = []
    progress = _progress(runtime)
    monkeypatch.setattr(progress, 'log_event', lambda message, **kwargs: logs.append((message, kwargs.get('extra') or {})))
    return logs


def test_setting_off_keeps_the_refusal(runtime):
    case = _case(runtime)
    produce, _partial = _partial_producer(runtime)
    result = execute(runtime, case, get_adapter=lambda capability: produce)
    assert result['steps'][1]['status'] == 'failed'
    assert result['steps'][1]['failure']['code'] == 'input_partial_not_accepted'
    assert case.model.calls == []
    assert 'progress_ledger' not in result
    assert case.context.accepted_partial_inputs == set()


def test_partial_input_is_recovered_inside_the_approved_plan(runtime, monkeypatch):
    case = _case(runtime, REACTIVE)
    calls = []
    produce, partial = _partial_producer(runtime, calls)
    logs = _logs(runtime, monkeypatch)
    events = []
    plan_before = json.dumps(case.plan, sort_keys=True, default=str)

    result = execute(runtime, case, get_adapter=lambda capability: produce, emit=events.append)

    # The first attempt is refused before its adapter is called; the second one composes.
    assert calls == ['upstream', 'answer']
    assert len(case.model.calls) == 1
    answer = result['steps'][1]
    assert answer['status'] == 'partial' and not answer.get('failure')
    task = case.context.task_results['answer']
    assert task.status == 'partial'
    # The limitation travels with the answer, so it is disclosed, not hidden.
    assert task.output('answer').completeness.limitations == partial.limitations
    assert result['message'].startswith('Prepared limited answer.')
    # The plan is a ledger of intent: recovery changes how a step is attempted, not the plan.
    assert json.dumps(case.plan, sort_keys=True, default=str) == plan_before
    assert case.plan['steps'][1]['inputs']['draft']['allow_partial'] is False
    assert result['progress_ledger'] == [{
        'round': 1, 'step_id': 'answer', 'capability_id': 'compose',
        'failure_code': 'input_partial_not_accepted', 'recovery': 'accept_partial_input',
        'outcome': 'recovered', 'producer_capability_id': 'compose',
    }]
    outcomes = [extra['progress_outcome'] for message, extra in logs if message.endswith('Progress recorded.')]
    assert outcomes == ['applied', 'recovered']
    assert any(
        event.get('type') == 'step' and 'stating the limits' in (event.get('summary') or '')
        for event in events
    )
    # Server vocabulary only: no source text reaches the ledger or its telemetry.
    assert 'PRIVATE-LIMITATION' not in json.dumps([result['progress_ledger'], logs], default=str)


def test_recovered_run_matches_a_plan_that_declared_the_partial_input(runtime):
    """Recovery reaches the state the planner could have asked for, and no other."""
    recovered = _case(runtime, REACTIVE)
    declared = _case(runtime, allow_partial=True)
    for case in (recovered, declared):
        produce, _partial = _partial_producer(runtime)
        case.result = execute(runtime, case, get_adapter=lambda capability, produce=produce: produce)
    for field in ('status', 'outcome', 'message'):
        assert recovered.result[field] == declared.result[field], field
    assert (
        recovered.context.task_results['answer'].output('answer').completeness
        == declared.context.task_results['answer'].output('answer').completeness
    )
    assert 'progress_ledger' not in declared.result


def test_zero_rounds_disables_recovery_and_records_why(runtime, monkeypatch):
    case = _case(runtime, {**REACTIVE, 'chat_orchestration_max_recovery_rounds': 0})
    produce, _partial = _partial_producer(runtime)
    logs = _logs(runtime, monkeypatch)
    result = execute(runtime, case, get_adapter=lambda capability: produce)
    assert result['steps'][1]['failure']['code'] == 'input_partial_not_accepted'
    assert case.model.calls == []
    assert [entry['outcome'] for entry in result['progress_ledger']] == ['round_limit']
    assert result['progress_ledger'][0]['recovery'] is None
    assert [extra['progress_outcome'] for _message, extra in logs] == ['round_limit']


def test_the_same_failure_after_a_recovery_is_a_stall(runtime):
    progress = _progress(runtime)
    context = SimpleNamespace(run_id='run-1', conversation_id='conversation-1', task_results={})
    ledger = progress.ProgressLedger(REACTIVE, context)
    step = {'step_id': 'answer', 'capability_id': 'compose'}
    failed = {
        'status': 'failed', 'failure': {'code': 'input_partial_not_accepted'},
        'observation': {'producer_step_id': 'upstream'},
    }
    applied = ledger.recover(step, failed, context)
    assert applied['recovery'] == 'accept_partial_input'
    assert context.accepted_partial_inputs == {('answer', 'upstream')}
    ledger.settle(applied, failed)
    assert ledger.recover(step, failed, context) is None
    assert [entry['outcome'] for entry in ledger.entries] == ['not_recovered', 'stalled']
    assert ledger.rounds == 1


def test_recovery_is_admitted_by_registry_policy_not_by_the_failure_alone(runtime):
    progress = _progress(runtime)
    context = SimpleNamespace(run_id='run-1', conversation_id='conversation-1', task_results={})
    ledger = progress.ProgressLedger(REACTIVE, context)
    failed = {
        'status': 'failed', 'failure': {'code': 'input_partial_not_accepted'},
        'observation': {'producer_step_id': 'upstream'},
    }
    # A capability whose descriptor does not read partial results is never given one.
    refusing = next(
        item['id'] for item in runtime.registry.CAPABILITY_REGISTRY
        if item.get('partial_inputs_supported') is False
    )
    assert ledger.recover({'step_id': 'work', 'capability_id': refusing}, failed, context) is None
    # Without a known producer there is nothing to accept.
    unknown = {'status': 'failed', 'failure': {'code': 'input_partial_not_accepted'}}
    assert ledger.recover({'step_id': 'answer', 'capability_id': 'compose'}, unknown, context) is None
    # A failure with no defined recovery is left to fail.
    other = {'status': 'failed', 'failure': {'code': 'result_invalid'}}
    assert ledger.recover({'step_id': 'answer', 'capability_id': 'compose'}, other, context) is None
    assert ledger.entries == [] and not getattr(context, 'accepted_partial_inputs', None)


def test_a_prepared_answer_that_failed_its_check_is_checked_again(runtime):
    progress = _progress(runtime)
    context = SimpleNamespace(run_id='run-1', conversation_id='conversation-1', task_results={})
    ledger = progress.ProgressLedger(REACTIVE, context)
    step = {'step_id': 'answer', 'capability_id': 'compose'}
    for code in ('completeness_incomplete', 'completeness_unavailable'):
        failed = {
            'status': 'failed', 'failure': {'code': code}, 'observation': {'preparation_status': 'prepared'},
        }
        applied = ledger.recover(step, failed, context)
        assert applied['recovery'] == 'recheck_answer'
        assert context.completeness_recheck_step_ids == {'answer'}
        ledger.settle(applied, failed)
        # The same failure after its recovery is a stall.
        assert ledger.recover(step, failed, context) is None
    # Without a prepared answer there is nothing to check again.
    other = progress.ProgressLedger(REACTIVE, SimpleNamespace(run_id='r', conversation_id='c', task_results={}))
    unprepared = {'status': 'failed', 'failure': {'code': 'completeness_incomplete'}}
    assert other.recover(step, unprepared, other.context) is None and other.entries == []


def test_a_reply_that_holds_an_answer_carries_one_plain_sentence(runtime):
    schema = runtime.schema
    failures = [schema.build_failure('completeness_incomplete')]
    note = schema.failure_explanation(failures, partial=True, answered=True)
    assert note == schema.ANSWERED_PARTIAL_NOTE
    assert '\n' not in note and 'run details' not in note and 'saved' not in note
    # With no answer to show, or a stopped run, the full explanation is kept.
    for kwargs in ({'partial': True}, {'partial': False, 'answered': True}, {'partial': True, 'cancelled': True, 'answered': True}):
        assert schema.failure_explanation(failures, **kwargs) != note


def test_round_limit_reads_the_bounded_setting(runtime):
    progress = _progress(runtime)
    assert progress.round_limit({}) == 2
    assert progress.round_limit({'chat_orchestration_max_recovery_rounds': 5}) == 5
    assert progress.round_limit({'chat_orchestration_max_recovery_rounds': 0}) == 0
    for invalid in (True, 9, -1, 'many', None):
        assert progress.round_limit({'chat_orchestration_max_recovery_rounds': invalid}) == 2
    # The retained-hint cap is a different setting and does not bound recoveries.
    assert progress.round_limit({'chat_orchestration_max_replans': 0}) == 2
    assert progress.reactive_loop_enabled({'enable_chat_orchestration_reactive_loop': 'true'}) is False
    assert progress.reactive_loop_enabled(REACTIVE) is True


def test_the_setting_is_declared_off_by_default_everywhere_it_is_saved():
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app')
    read = lambda *parts: open(os.path.join(root, *parts), encoding='utf-8').read()
    assert "'enable_chat_orchestration_reactive_loop': False" in read('functions_settings.py')
    assert "form_data.get('enable_chat_orchestration_reactive_loop') == 'on'" in read('route_frontend_admin_settings.py')
    assert '"key": "enable_chat_orchestration_reactive_loop"' in read('admin_settings_fields.py')
    assert 'name="enable_chat_orchestration_reactive_loop"' in read('templates', 'admin', '_panes', 'chat-orchestration.html')
    assert "'chat_orchestration_max_recovery_rounds': 2" in read('functions_settings.py')
    assert "_clamped('chat_orchestration_max_recovery_rounds', 2, 0, 5)" in read('route_frontend_admin_settings.py')
    assert '"key": "chat_orchestration_max_recovery_rounds"' in read('admin_settings_fields.py')
    assert 'name="chat_orchestration_max_recovery_rounds"' in read('templates', 'admin', '_panes', 'chat-orchestration.html')


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-q', '-p', 'no:cacheprovider']))
