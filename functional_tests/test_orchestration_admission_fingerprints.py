# test_orchestration_admission_fingerprints.py
"""Approved v2 work survives changes to new-plan admission, never execution policy.

Version: 0.261.127
Implemented in: 0.261.127
Real fingerprints, retained results, leases and waiting checkpoints are exercised.
Only transport and producer/model I/O are isolated by the existing runtime fixtures.
"""

from copy import deepcopy

import pytest

from test_orchestration_dependency_recovery import durable
from test_orchestration_dependency_runtime import binding, compose, runtime
from test_orchestration_waiting_continuation import claim, waiting


ADMISSION_KEY = 'enable_chat_orchestration_harness'


@pytest.mark.parametrize('enabled', [True, False])
def test_v2_context_and_step_fingerprints_ignore_only_new_plan_admission(runtime, enabled):
    case = runtime.make([compose()], final_response=binding('draft'))
    settings = deepcopy(case.settings)
    original = deepcopy(settings)
    checkpoints = runtime.checkpoints
    expected_binding = checkpoints.context_binding(case.context, case.plan, settings)
    expected_step = checkpoints.step_input_fingerprint(
        case.plan['steps'][0], case.context, expected_binding, settings=settings,
    )
    settings[ADMISSION_KEY] = enabled
    supplied = deepcopy(settings)
    actual_binding = checkpoints.context_binding(case.context, case.plan, settings)
    actual_step = checkpoints.step_input_fingerprint(
        case.plan['steps'][0], case.context, actual_binding, settings=settings,
    )
    assert actual_binding == expected_binding
    assert actual_step == expected_step
    assert settings == supplied and case.settings == original


@pytest.mark.parametrize('changes', [
    {'chat_orchestration_max_steps': 4},
    {'chat_orchestration_enabled_capabilities': ['document_search']},
    {'enable_user_workspace': False},
    {'enable_chat_orchestration_actions': True},
])
def test_actual_execution_policy_changes_still_invalidate_both_v2_fingerprints(runtime, changes):
    case = runtime.make([compose()])
    checkpoints = runtime.checkpoints
    original_binding = checkpoints.context_binding(case.context, case.plan, case.settings)
    original_step = checkpoints.step_input_fingerprint(
        case.plan['steps'][0], case.context, original_binding, settings=case.settings,
    )
    settings = {**case.settings, **changes, ADMISSION_KEY: False}
    changed_binding = checkpoints.context_binding(case.context, case.plan, settings)
    changed_step = checkpoints.step_input_fingerprint(
        case.plan['steps'][0], case.context, changed_binding, settings=settings,
    )
    assert changed_binding != original_binding
    assert changed_step != original_step


def test_legacy_context_and_step_fingerprints_keep_the_exact_existing_contract(runtime):
    plan = runtime.schema.normalize_plan(
        {'steps': [{'step_id': 'answer', 'capability_id': 'respond', 'arguments': {}}]},
        'conversation-1', 'owner', available_capability_ids=['respond'],
    )
    context = runtime.executor.RunContext(
        run_id=plan['run_id'], plan_id=plan['plan_id'], user_id='owner', conversation_id='conversation-1',
        user_message='A legacy answer.', plan_contract_version=1,
    )
    checkpoints = runtime.checkpoints
    settings = {ADMISSION_KEY: True}
    expected_binding = checkpoints.fingerprint({
        'plan': checkpoints.effective_plan(plan),
        'inputs': {key: getattr(context, key, None) for key in checkpoints.INPUT_FIELDS},
        'model': {key: None for key in ('model_id', 'endpoint_id', 'provider', 'model_deployment')},
        'memory_digest': checkpoints.fingerprint(context.memory_context or {}),
        'agent_catalog_digest': checkpoints.fingerprint(context.agent_catalog or []),
        'action_catalog_digest': checkpoints.fingerprint(context.action_catalog or []),
        'settings_digest': checkpoints.fingerprint(settings),
    })
    actual_binding = checkpoints.context_binding(context, plan, settings)
    expected_step = checkpoints.fingerprint({
        'binding': actual_binding,
        'step': checkpoints.effective_plan({'steps': plan['steps']})[0],
        'context': checkpoints.context_state(context),
    })
    actual_step = checkpoints.step_input_fingerprint(plan['steps'][0], context, actual_binding, settings=settings)
    disabled_binding = checkpoints.context_binding(context, plan, {ADMISSION_KEY: False})
    assert actual_binding == expected_binding
    assert actual_step == expected_step
    assert disabled_binding != actual_binding


@pytest.mark.parametrize('states', [(True, False), (False, True)])
def test_actual_same_attempt_waits_keep_original_results_guard_and_deadline_across_toggle(waiting, states):
    original = waiting.read_run('run-1')
    for index, enabled in enumerate(states):
        waiting.case.settings[ADMISSION_KEY] = enabled
        acquired = claim(waiting, submission=f'admission-change-{index}')
        assert acquired['acquired'] is True
        record = acquired['record']
        context = waiting.fresh_context(record)
        result = waiting.run(record, context)
        saved = waiting.read_run('run-1')
        assert result['status'] == 'waiting'
        assert saved['task_results'] == original['task_results']
        assert saved['pending_results'] == original['pending_results']
        assert saved['attempt_index'] == original['attempt_index']
        assert saved['execution_binding'] == original['execution_binding']
        assert saved['started_at'] == original['started_at']
        assert saved['execution_deadline_at'] == original['execution_deadline_at']
        assert record['execution_lease']['token'] == waiting.record['execution_lease']['token']
        assert len(waiting.case.model.calls) == 1
    assert len(waiting.runs.items) == 1
