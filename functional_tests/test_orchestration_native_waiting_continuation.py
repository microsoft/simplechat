# test_orchestration_native_waiting_continuation.py
"""Real native jobs resume through durable same-attempt orchestration ownership.

Version: 0.261.127
Implemented in: 0.261.127
External storage/provider I/O is isolated; native service, bridge and runtime are real.
"""

from copy import deepcopy
from dataclasses import replace
import importlib
import sys

import pytest

from functions_orchestration_executor import RunContext, execute_plan
from test_orchestration_dependency_native_runtime import prepare
from test_orchestration_native_results import (
    CONVERSATION, USER, bridge_runtime, finish_native, transformation_spec,
)
from test_support.orchestration_research import document_action_policy_module


def test_native_waiting_continuation_retains_original_guard_and_never_submits_again(monkeypatch):
    monkeypatch.setitem(sys.modules, 'functions_document_actions', document_action_policy_module())
    with bridge_runtime(monkeypatch) as runtime:
        monkeypatch.setattr(
            sys.modules['config'], 'cosmos_orchestration_run_steps_container', runtime.container, raising=False,
        )
        recovery = importlib.import_module('functions_orchestration_recovery')
        run_store = importlib.import_module('functions_orchestration_runs')
        runtime.native.settings['tabular_generated_output_inline_max_rows'] = 1
        prepare(runtime, columns=['Item_ID', 'doubled'], transformation_spec=transformation_spec())
        monkeypatch.setattr(run_store, 'cosmos_orchestration_runs_container', runtime.native.parents)
        monkeypatch.setattr(run_store, 'cosmos_orchestration_run_steps_container', runtime.container)
        record = runtime.native.parents.read_item('parent-run', CONVERSATION)
        record.update(
            record_type='run', run_id=record['id'], turn_id=runtime.plan['turn_id'],
            approval={'state': 'approved'}, recovery_version='native-initial-version',
            user_message='', original_user_message='', execution_lease=recovery.lease_fields(),
        )
        record = runtime.native.parents.replace_item(record['id'], record)
        token = record['execution_lease']['token']

        def current():
            return runtime.native.parents.read_item('parent-run', CONVERSATION)

        def execute(record):
            lease = recovery.ExecutionLease(record, lambda: True)

            def guard(step_id):
                lease.read()
                if step_id != 'compute':
                    raise AssertionError('Only the original native step owns this result guard.')
                return lease.token

            context = RunContext(
                run_id=record['id'], plan_id=runtime.plan['plan_id'],
                user_id=USER, conversation_id=CONVERSATION, attempt_index=record['attempt_index'],
                plan_contract_version=2, result_service=runtime.service, gpt_model='gpt-4o',
                result_guard_token_for_step=guard,
                native_bridge_for_step=lambda step, context: runtime.bound,
                resolve_source_manifest=runtime.context.resolve_source_manifest,
            )
            context.source_manifest = deepcopy(runtime.native.source_manifest)
            context.execution_manifest = deepcopy(runtime.native.source_manifest)
            try:
                lease.start()
                return execute_plan(
                    runtime.plan, context, settings=runtime.settings, user_id=USER,
                    get_adapter=lambda capability: pytest.fail('A waiting native job entered legacy dispatch.'),
                    persist=lambda kind, value: lease.update(value) if kind == 'run' else None,
                    checkpoints=lambda active: recovery.ExecutionCheckpoints(record, active, runtime.settings, lease),
                )
            finally:
                lease.close(release=True)

        first = execute(record)
        assert first['status'] == 'waiting', first
        original_task = first['task_results']['compute']
        original_wait = first['pending_results']['compute']
        original_deadline = first['execution_deadline_at']
        stored = current()
        assert stored['task_results'] == first['task_results']
        assert stored['pending_results'] == first['pending_results']
        assert stored['execution_deadline_at'] == original_deadline

        def forbidden(*args, **kwargs):
            raise AssertionError('A wait refresh selected a model or rebuilt a native request.')

        runtime.bound = replace(runtime.bound, request_builder=forbidden, model_resolver=forbidden)

        def claim(submission):
            record = current()
            acquired = recovery.claim_waiting_continuation('parent-run', USER, {
                'conversation_id': CONVERSATION, 'submission_id': submission,
                'expected_version': record['recovery_version'],
            }, authorize=lambda: True)
            assert acquired['acquired'] is True
            claimed = acquired['record']
            assert claimed['attempt_index'] == 1 and claimed['execution_lease']['token'] == token
            return claimed

        pending = execute(claim('pending-event'))
        assert pending['status'] == 'waiting', pending
        assert pending['task_results']['compute'] == original_task
        assert pending['pending_results']['compute'] == original_wait
        assert runtime.native.jobs.created == 1 and runtime.provider.calls == []

        finish_native(runtime, {'wait': original_wait})
        complete = execute(claim('ready-event'))
        assert complete['status'] == 'completed', complete
        assert complete['pending_results'] == {}
        assert complete['task_results']['compute']['producer'] == original_task['producer']
        assert complete['execution_deadline_at'] == original_deadline
        stored = current()
        assert stored['task_results'] == complete['task_results']
        assert stored['pending_results'] == {}
        assert stored['execution_deadline_at'] == original_deadline
        task = runtime.module.TaskResult.from_dict(complete['task_results']['compute'])
        rows = list(runtime.service.open_result(task.output('records')).iter_records())
        coverage = runtime.service.open_result(task.output('coverage')).read_value()
        assert len(rows) == 37 and rows[-1] == {'Item_ID': 'item-000037', 'doubled': 74}
        assert coverage['outputs']['records']['actual_count'] == 37
        assert runtime.native.jobs.created == 1 and runtime.native.publications == []
