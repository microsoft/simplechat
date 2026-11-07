# test_orchestration_dependency_native_runtime.py
"""Native data-only services through the real dependency compiler and executor.

Version: 0.261.127
Implemented in: 0.261.127
Native jobs, readers, retained results and runtime execute with isolated external I/O.
"""

from copy import deepcopy
from dataclasses import replace
import sys

import pytest

from test_orchestration_native_results import (
    CONVERSATION, USER, bridge_runtime, finish_native, transformation_spec, use_production_builder,
)
from functions_orchestration_checkpoints import context_state, restore_context, step_input_fingerprint
from functions_orchestration_executor import RunContext, execute_plan, resume_native_dependency_step
from functions_orchestration_registry import resolve_available_capability_ids
from functions_orchestration_result_contracts import ResultContractError
from functions_orchestration_schema import PlanValidationError, normalize_plan
from test_support.orchestration_research import document_action_policy_module


@pytest.fixture(autouse=True)
def document_policy(monkeypatch):
    monkeypatch.setitem(sys.modules, 'functions_document_actions', document_action_policy_module())


def prepare(runtime, **arguments):
    use_production_builder(runtime, **arguments)
    runtime.step['capability_id'] = 'tabular_analyze'
    runtime.context.native_bridge_for_step = lambda step, context: runtime.bound
    runtime.context.resolve_source_manifest = lambda ids: runtime.service.access.source_resolver(ids, user_id=USER)
    settings = {**runtime.native.settings, 'enable_user_workspace': True}
    available = resolve_available_capability_ids(
        settings, contract_version=2,
        request_context={'native_bridge_for_step': runtime.context.native_bridge_for_step},
    )
    plan = normalize_plan(
        {'run_id': 'parent-run', 'steps': [deepcopy(runtime.step)]},
        CONVERSATION, USER, settings=settings, contract_version=2, available_capability_ids=available,
    )
    runtime.context.plan_id = plan['plan_id']
    parent = runtime.native.parents.read_item('parent-run', CONVERSATION)
    parent['plan'] = plan
    runtime.native.parents.replace_item(parent['id'], parent)
    runtime.plan, runtime.settings = plan, settings
    runtime.step = plan['steps'][0]
    return plan


def run(runtime):
    return execute_plan(
        runtime.plan, runtime.context, settings=runtime.settings, user_id=USER,
        get_adapter=lambda capability: pytest.fail('Native v2 work must never enter a legacy adapter.'),
    )


def reopen_once(runtime, context=None, *, fingerprint=None, cancel_requested=None):
    context = context or runtime.context
    if fingerprint is None:
        fingerprint = step_input_fingerprint(runtime.step, context, None, settings=runtime.settings)
    return resume_native_dependency_step(
        runtime.step, context, settings=runtime.settings, user_id=USER,
        input_fingerprint=fingerprint, cancel_requested=cancel_requested,
    )


def test_native_admission_requires_server_binding_not_a_boolean(monkeypatch):
    with bridge_runtime(monkeypatch, operation='query') as runtime:
        settings = {**runtime.native.settings, 'enable_user_workspace': True}
        for request in (None, {}, {'native_bridge_for_step': True}):
            available = resolve_available_capability_ids(settings, request_context=request, contract_version=2)
            assert 'tabular_analyze' not in available
        prepare(runtime, columns=['Item_ID', 'amount'], query_expression='amount >= 36')
        runtime.context.native_bridge_for_step = None
        with pytest.raises(PlanValidationError):
            run(runtime)
        assert runtime.native.jobs.created == 0 and runtime.native.publications == []


@pytest.mark.parametrize('operation, task_type, names', [
    ('query', None, {'records', 'coverage'}),
    ('transform', None, {'records', 'coverage'}),
    ('analysis', None, {'analysis', 'coverage'}),
    ('transform', 'combined', {'records', 'analysis', 'coverage'}),
])
def test_native_mode_has_exact_outputs_and_no_files(monkeypatch, operation, task_type, names):
    with bridge_runtime(monkeypatch, operation=operation, task_type=task_type) as runtime:
        arguments = {}
        if operation == 'query':
            arguments = {'columns': ['Item_ID', 'amount'], 'query_expression': 'amount >= 36'}
        elif operation == 'transform':
            arguments = {'columns': ['Item_ID', 'doubled'], 'transformation_spec': transformation_spec()}
        if task_type:
            arguments['task_type'] = task_type
        prepare(runtime, **arguments)
        assert {output['name'] for output in runtime.step['outputs']} == names
        result = run(runtime)
        if result['status'] == 'waiting':
            finish_native(runtime, {'wait': runtime.context.pending_results['compute']})
            retained = reopen_once(runtime)
            assert retained['status'] == 'completed', retained
            runtime.context.task_results['compute'] = retained['task_result']
            runtime.context.pending_results.pop('compute')
            result = run(runtime)
        assert result['status'] == 'completed', result
        task = runtime.context.task_results['compute']
        assert {reference.output_name for reference in task.outputs} == names
        if 'records' in names:
            rows = list(runtime.service.open_result(task.output('records')).iter_records())
            assert len(rows) == (2 if operation == 'query' else 37)
            assert rows[-1]['Item_ID'] == 'item-000037'
        if 'analysis' in names:
            value = runtime.service.open_result(task.output('analysis')).read_value()
            assert value['counts']['sum'] == 703
        assert runtime.native.publications == [] and result['artifacts'] == []


@pytest.mark.parametrize('fault', ['no_source', 'multiple_sources', 'aggregate', 'missing_schema', 'wrong_outputs'])
def test_invalid_native_work_is_rejected_without_submission(monkeypatch, fault):
    with bridge_runtime(monkeypatch, operation='query') as runtime:
        prepare(runtime, columns=['Item_ID', 'amount'], query_expression='amount >= 36')
        raw = deepcopy(runtime.plan)
        step = raw['steps'][0]
        if fault == 'no_source':
            step['arguments']['document_ids'] = []
        elif fault == 'multiple_sources':
            step['arguments']['document_ids'].append('narrative-source')
        elif fault == 'aggregate':
            step['arguments']['query_expression'] = 'amount.sum()'
        elif fault == 'missing_schema':
            step['arguments'].pop('columns')
        else:
            step['outputs'] = [{'name': 'analysis', 'kind': 'structured-v1'}, {'name': 'coverage', 'kind': 'structured-v1'}]
        with pytest.raises(PlanValidationError):
            normalize_plan(
                raw, CONVERSATION, USER, settings=runtime.settings,
                contract_version=2, available_capability_ids=['tabular_analyze'],
            )
        assert runtime.native.jobs.created == 0 and runtime.native.blobs.reads == []


def test_pending_native_restart_requires_exact_fingerprint_and_never_resubmits(monkeypatch):
    with bridge_runtime(monkeypatch) as runtime:
        runtime.native.settings['tabular_generated_output_inline_max_rows'] = 1
        prepare(runtime, columns=['Item_ID', 'doubled'], transformation_spec=transformation_spec())
        first = run(runtime)
        assert first['status'] == 'waiting'
        stamp = step_input_fingerprint(runtime.step, runtime.context, None, settings=runtime.settings)
        state = context_state(runtime.context)
        assert 'native_bridge_for_step' not in state
        again = run(runtime)
        assert again['status'] == 'waiting' and runtime.native.jobs.created == 1
        context = RunContext(
            run_id='parent-run', plan_id=runtime.plan['plan_id'], user_id=USER, conversation_id=CONVERSATION,
            plan_contract_version=2, result_service=runtime.service, gpt_model='gpt-4o',
            result_guard_token_for_step=runtime.context.result_guard_token_for_step,
            resolve_source_manifest=runtime.context.resolve_source_manifest,
            native_bridge_for_step=lambda step, context: runtime.bound,
        )
        restore_context(context, {'state': state})
        with pytest.raises(ResultContractError):
            reopen_once(runtime, context, fingerprint='0' * 64)
        pending = reopen_once(runtime, context, fingerprint=stamp)
        assert pending['status'] == 'waiting'
        assert pending['task_result'].outputs == ()
        finish_native(runtime, pending)

        def forbidden(*args, **kwargs):
            raise AssertionError('Continuation must not select a model, build a request, or submit another job.')

        runtime.bound = replace(runtime.bound, request_builder=forbidden, model_resolver=forbidden)
        ready = reopen_once(runtime, context, fingerprint=stamp)
        assert ready['status'] == 'completed', ready
        rows = list(runtime.service.open_result(ready['task_result'].output('records')).iter_records())
        assert len(rows) == 37 and runtime.native.jobs.created == 1
        assert context.task_results['compute'].status == 'pending'
        metadata = runtime.service.open_result(ready['task_result'].output('records')).metadata()
        assert metadata['input_fingerprint'] == stamp


@pytest.mark.parametrize('fault', ['unbound_factory', 'wrong_mode', 'snapshot', 'fingerprint', 'narrative', 'locator'])
def test_native_runtime_requires_a_matching_replayable_server_binding(monkeypatch, fault):
    with bridge_runtime(monkeypatch, operation='query') as runtime:
        prepare(runtime, columns=['Item_ID', 'amount'], query_expression='amount >= 36')
        if fault == 'unbound_factory':
            runtime.context.native_bridge_for_step = lambda step, context: runtime.module.build_native_orchestration_bridge
        elif fault == 'wrong_mode':
            runtime.bound = runtime.module.build_native_orchestration_bridge(native_operation='analysis')
        elif fault == 'snapshot':
            runtime.bound = replace(runtime.bound, source_policy='snapshot')
        elif fault == 'fingerprint':
            runtime.bound = replace(runtime.bound, input_fingerprint_for_step=lambda step, context: '0' * 64)
        else:
            original = runtime.context.resolve_source_manifest

            def invalid_source(ids):
                manifest = original(ids)
                if fault == 'narrative':
                    manifest[0]['source_kind'] = 'narrative'
                else:
                    manifest[0].pop('storage_locator', None)
                return manifest

            runtime.context.resolve_source_manifest = invalid_source
        result = run(runtime)
        assert result['status'] == 'failed'
        assert runtime.native.jobs.created == 0 and runtime.native.blobs.reads == []
        assert runtime.provider.calls == [] and runtime.native.publications == []


def test_native_resume_rejects_changed_declared_request_before_opening(monkeypatch):
    with bridge_runtime(monkeypatch) as runtime:
        runtime.native.settings['tabular_generated_output_inline_max_rows'] = 1
        prepare(runtime, columns=['Item_ID', 'doubled'], transformation_spec=transformation_spec())
        waiting = run(runtime)
        assert waiting['status'] == 'waiting'
        stamp = step_input_fingerprint(runtime.step, runtime.context, None, settings=runtime.settings)
        runtime.step['arguments']['question'] = 'A different, unapproved computation.'
        with pytest.raises(ResultContractError) as refused:
            reopen_once(runtime, fingerprint=stamp)
        assert refused.value.code == 'result_input_changed'
        assert runtime.native.jobs.created == 1 and runtime.native.publications == []


@pytest.mark.parametrize('fault', ['acl', 'screening', 'source_change', 'guard', 'cancel'])
def test_native_continuation_rechecks_current_state(monkeypatch, fault):
    with bridge_runtime(monkeypatch) as runtime:
        runtime.native.settings['tabular_generated_output_inline_max_rows'] = 1
        prepare(runtime, columns=['Item_ID', 'doubled'], transformation_spec=transformation_spec())
        waiting = run(runtime)
        assert waiting['status'] == 'waiting'
        finish_native(runtime, {'wait': runtime.context.pending_results['compute']})
        if fault == 'acl':
            runtime.native.state['allowed'] = False
        elif fault == 'screening':
            runtime.native.document['content_screening'] = {'state': 'pending_review'}
        elif fault == 'source_change':
            runtime.native.document.update(version=2, _etag='changed')
        elif fault == 'guard':
            runtime.state['guard'] = 'not-the-original-owner'
        result = reopen_once(runtime, cancel_requested=(lambda: True) if fault == 'cancel' else None)
        assert result['status'] in {'failed', 'cancelled'}
        assert result.get('task_result') is None
        assert runtime.native.jobs.created == 1 and runtime.native.publications == []
