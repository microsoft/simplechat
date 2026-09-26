#!/usr/bin/env python3
# test_orchestration_step_budget_outcome.py
"""
Functional test for keeping finished work that crossed its step time budget.
Version: 0.261.141
Implemented in: 0.261.141

This test ensures that a step whose work finished and committed before the executor
noticed its time budget keeps that result (and logs the overrun), while a budget the
work itself observed, or a user cancellation, still ends the step.
"""

import time
from unittest.mock import patch

from test_orchestration_dependency_runtime import binding, compose, execute, runtime  # noqa: F401


class _Clock:
    """The executor's monotonic clock, advanced explicitly by each test."""

    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now

    def __getattr__(self, name):
        return getattr(time, name)


def _producer(runtime, case, clock, *, advance, observe=False, cancel=False):
    def produce(step, context, **kwargs):
        task = context.result_service.persist_task_result(
            producer=context.result_producer(step), role='reason', status='complete',
            outputs=[runtime.NamedOutput('answer', 'markdown-v1', 'Finished answer.', runtime.complete(1))],
            sources=[], origin='generated',
            guard_token=context.result_guard_token_for_step(step['step_id']),
            input_fingerprint=context.result_input_fingerprint_for_step(step['step_id']),
        )
        clock.now += advance
        if cancel:
            case.fixture.runs['run-1']['cancellation_requested_at'] = 'server-stop'
        if observe:
            kwargs['cancel_requested']()
        return runtime.schema.build_step_result(task_result=task)

    return produce


def _run(runtime, monkeypatch, *, advance, observe=False, cancel=False):
    case = runtime.make(
        [compose()], [], final_response=binding('draft'),
        settings={'chat_orchestration_step_timeout_seconds': 30},
    )
    clock = _Clock()
    monkeypatch.setattr(runtime.executor, 'time', clock)
    produce = _producer(runtime, case, clock, advance=advance, observe=observe, cancel=cancel)
    with patch.object(runtime.executor, 'log_event') as logged:
        result = execute(
            runtime, case, get_adapter=lambda capability: produce,
            cancel_requested=lambda: bool(case.fixture.runs['run-1'].get('cancellation_requested_at')),
        )
    return result, logged


def _over_budget_logs(logged):
    return [
        call for call in logged.call_args_list
        if 'finished after its time budget' in call.args[0]
    ]


def test_finished_work_past_its_step_budget_is_kept_and_logged(runtime, monkeypatch):
    print('🔍 Testing a finished step that crossed its budget keeps its result...')
    result, logged = _run(runtime, monkeypatch, advance=45)
    assert result['status'] == 'completed'
    assert result['steps'][0]['status'] == 'completed'
    assert result['message'] == 'Finished answer.'
    overruns = _over_budget_logs(logged)
    assert len(overruns) == 1
    extra = overruns[0].kwargs['extra']
    assert extra['failure_code'] == 'step_timeout'
    assert extra['step_timeout_seconds'] == 30
    assert extra['elapsed_ms'] >= 45000
    assert extra['capability_id'] == 'compose'
    assert 'run-1' not in str(extra) and 'draft' not in str(extra)
    print('✅ Finished work past its budget was kept.')


def test_a_budget_the_work_observed_still_fails_the_step(runtime, monkeypatch):
    print('🔍 Testing a budget observed during the step still fails it...')
    result, logged = _run(runtime, monkeypatch, advance=45, observe=True)
    assert result['steps'][0]['status'] == 'failed'
    assert result['steps'][0]['failure']['code'] == 'step_timeout'
    assert result['status'] == 'failed'
    assert 'Finished answer.' not in result['message']
    assert _over_budget_logs(logged) == []
    print('✅ An observed budget failed the step.')


def test_work_within_its_budget_is_not_reported_as_an_overrun(runtime, monkeypatch):
    print('🔍 Testing in-budget work logs no overrun...')
    result, logged = _run(runtime, monkeypatch, advance=5)
    assert result['status'] == 'completed'
    assert _over_budget_logs(logged) == []
    print('✅ In-budget work was not reported.')


def test_a_cancellation_after_the_work_returned_still_cancels(runtime, monkeypatch):
    print('🔍 Testing a user cancellation noticed after return still cancels...')
    result, logged = _run(runtime, monkeypatch, advance=45, cancel=True)
    assert result['status'] == 'cancelled'
    assert result['steps'][0]['status'] == 'cancelled'
    assert result['steps'][0]['failure']['code'] == 'user_cancelled'
    assert 'Finished answer.' not in result['message']
    assert _over_budget_logs(logged) == []
    print('✅ The cancellation still discarded the result.')
