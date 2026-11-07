# test_orchestration_render_waiting_runtime.py
"""Real Render delivery resumes under the original orchestration attempt without producer replay.

Version: 0.261.141
Implemented in: 0.261.127
Uncertain output-acknowledgement regression implemented in: 0.261.129
Saved Render payload and diagnostic preservation implemented in: 0.261.130
Shared-resumer dispatch and effect-boundary coverage added in: 0.261.130
Render outage wrapper forwards the step time limit since: 0.261.141
The compiler, executor, leases, checkpoints, result store, renderer and artifact transport are real.
Only model and external Azure I/O are isolated.
"""

from copy import deepcopy
import importlib
from types import SimpleNamespace

import pytest
from azure.core.exceptions import ServiceResponseError

from functions_model_capabilities import ModelTokenBudget
from functions_orchestration_executor import (
    RunContext, _render_dependency_step, _validate_render_step_result, execute_plan,
    resume_waiting_dependency_step,
)
from functions_orchestration_output_store import OutputStorageError
from functions_orchestration_registry import resolve_available_capability_ids
from functions_orchestration_result_contracts import ResultContractError
from functions_orchestration_schema import build_step_result, normalize_plan
from test_orchestration_dependency_runtime import binding, compose, source_input
from test_orchestration_output_lifecycle import lifecycle, production_modules


@pytest.fixture
def render_runtime(lifecycle, monkeypatch, request):
    recovery = importlib.import_module('functions_orchestration_recovery')
    run_store = importlib.import_module('functions_orchestration_runs')
    monkeypatch.setattr(recovery, '_now', lambda: lifecycle.now)
    monkeypatch.setattr(run_store, 'cosmos_orchestration_runs_container', lifecycle.runs)
    monkeypatch.setattr(run_store, 'cosmos_orchestration_run_steps_container', lifecycle.results.container)
    settings = {'chat_orchestration_max_steps': 8}
    calls = []
    state = {}

    def model(messages, **kwargs):
        calls.append((deepcopy(messages), kwargs))
        if len(calls) != 1:
            raise AssertionError('File retry or waiting continuation repeated content generation.')
        return '# Original prepared report\n\nThe authoritative final paragraph.'

    model.model_metadata = ModelTokenBudget(
        model_id='offline-render-runtime', provider='openai', context_window=32768,
        input_limit=24576, output_limit=2048, output_accounting='total_generation',
    )
    model.output_tokens = 512
    model.provider = 'openai'
    available = resolve_available_capability_ids(
        settings, contract_version=2, request_context={'rendering_service': lifecycle.service},
    )
    steps = [
        compose('draft'),
        {
            'step_id': 'file', 'capability_id': 'render_file',
            'arguments': {
                'file_name': 'Prepared report.md', 'output_format': 'md', 'profile': 'prepared_text_v1',
            },
            'inputs': {'source': source_input('draft', 'answer')}, 'outputs': [],
        },
    ]
    for index in range(1, getattr(request, 'param', 1)):
        step = deepcopy(steps[1])
        step['step_id'] = f'file-{index + 1}'
        step['arguments']['file_name'] = f'Prepared report {index + 1}.md'
        steps.append(step)
    plan = normalize_plan({
        'run_id': 'run-1', 'plan_id': 'render-plan', 'turn_id': 'render-turn',
        'steps': steps,
        'final_response': binding('draft'),
    }, 'conversation-1', 'owner', settings=settings, contract_version=2, available_capability_ids=available)
    initial = lifecycle.runs.read_item('run-1', 'conversation-1')
    initial.update(
        plan=plan, run_id='run-1', turn_id=plan['turn_id'], user_message='Prepare the report.',
        original_user_message='Prepare the report.', recovery_version='initial-render-version',
        execution_lease=recovery.lease_fields(),
    )
    initial = lifecycle.runs.upsert_item(initial)
    leases = []

    def current():
        return lifecycle.runs.read_item('run-1', 'conversation-1')

    def execute(record, *, export_catalog=None):
        lease = recovery.ExecutionLease(record, lambda: True)
        leases.append(lease)

        def guard(step_id):
            lease.read()
            return lease.token

        context = RunContext(
            run_id='run-1', plan_id=plan['plan_id'], user_id='owner', conversation_id='conversation-1',
            user_message='Prepare the report.', plan_contract_version=2, attempt_index=record['attempt_index'],
            result_service=lifecycle.service.results, rendering_service=lifecycle.service,
            result_guard_token_for_step=guard, invoke_prompt=model,
            execution_deadline_at=record['execution_deadline_at'],
            export_catalog=export_catalog,
        )
        context.approved_work_id = 'run-1'
        state['context'] = context
        events = []
        try:
            lease.start()
            result = execute_plan(
                plan, context, settings=settings, user_id='owner', emit=events.append,
                persist=lambda kind, value: lease.update(value) if kind == 'run' else None,
                checkpoints=lambda active: recovery.ExecutionCheckpoints(record, active, settings, lease),
            )
            state['events'] = events
            return result
        finally:
            lease.close(release=True)

    def claim(submission):
        record = current()
        result = recovery.claim_waiting_continuation('run-1', 'owner', {
            'conversation_id': 'conversation-1', 'submission_id': submission,
            'expected_version': record['recovery_version'],
        }, authorize=lambda: True)
        assert result['acquired'] is True
        return result['record']

    yield SimpleNamespace(
        lifecycle=lifecycle, recovery=recovery, plan=plan, settings=settings,
        calls=calls, state=state, initial=initial, current=current, execute=execute, claim=claim,
    )
    assert all(lease.stopped.is_set() for lease in leases)


def _restart_completed(case):
    record = case.current()
    return case.recovery._replace(record, {
        'status': 'running',
        'execution_lease': {
            **case.recovery.lease_fields(),
            'token': case.initial['execution_lease']['token'],
        },
    })


def _render_effects(case):
    lifecycle = case.lifecycle
    return deepcopy({
        'runs': lifecycle.runs.items,
        'messages': lifecycle.messages.items,
        'conversations': lifecycle.conversations.items,
        'results': lifecycle.results.container.items,
        'blobs': lifecycle.blobs.data,
        'uploads': lifecycle.blobs.uploads,
        'deletes': lifecycle.blobs.deletes,
        'model_calls': len(case.calls),
        'render_calls': len(lifecycle.render_calls),
    })


@pytest.mark.parametrize('saved_status', ['waiting', 'completed'])
def test_saved_render_dispatches_once_to_shared_resumer(render_runtime, monkeypatch, saved_status):
    case = render_runtime
    if saved_status == 'waiting':
        case.lifecycle.failures['md'] = [TimeoutError('Isolated initial-render transport failure.')]
    first = case.execute(case.initial)
    assert first['status'] == saved_status
    checkpoint = case.recovery.checkpoint_store(case.current(), lambda: True)
    saved = checkpoint.load('file', waiting=saved_status == 'waiting')
    rendering = importlib.import_module('functions_orchestration_rendering')
    executor = importlib.import_module('functions_orchestration_executor')
    policy = importlib.import_module('functions_orchestration_execution_policy')
    resume = rendering.resume_render_file
    received, forbidden_calls = [], []

    def forbidden(*args, **kwargs):
        forbidden_calls.append(True)
        raise AssertionError('A saved Render reader must not execute or use a mutating run-wide projection.')

    def observe(step, context, pending_result, **kwargs):
        received.append((deepcopy(step), deepcopy(pending_result)))
        assert kwargs['service_factory'] is executor._context_rendering_service
        assert kwargs['resolve_inputs'] is executor.resolve_step_inputs
        assert kwargs['build_step_result'] is executor.build_step_result
        assert kwargs['build_failure'] is executor.build_failure
        assert context.rendering_service is case.lifecycle.service
        assert kwargs['settings'] == case.settings and kwargs['user_id'] == 'owner'
        with pytest.raises(policy.OrchestrationFilePolicyError):
            policy.require_generated_file_publication_allowed()
        before = _render_effects(case)
        # Run/checkpoint bookkeeping is outside the shared reader's zero-effect boundary.
        with monkeypatch.context() as reader_only:
            for method in (
                'read', 'list_public_outputs', 'committed_artifacts',
                'ensure_output', 'render_attempt', 'reconcile', 'claim_due', 'manual_retry',
            ):
                reader_only.setattr(case.lifecycle.service, method, forbidden)
            for method in ('fail', 'cancel'):
                reader_only.setattr(case.lifecycle.service.store, method, forbidden)
            reader_only.setattr(case.lifecycle.service.results, 'persist_task_result', forbidden)
            result = resume(step, context, pending_result, **kwargs)
        after = _render_effects(case)
        assert after == before
        return result

    monkeypatch.setattr(rendering, 'resume_render_file', observe)
    claimed = case.claim('shared-reader') if saved_status == 'waiting' else _restart_completed(case)
    result = case.execute(claimed)

    assert received == [(case.plan['steps'][1], saved['result'])]
    assert forbidden_calls == []
    assert result['status'] == saved_status
    assert result['outputs'] == first['outputs'] and result['artifacts'] == first['artifacts']
    assert result['task_results'] == first['task_results']
    assert result['pending_results'] == first['pending_results']
    assert len(case.calls) == len(case.lifecycle.render_calls) == 1
    assert case.lifecycle.blobs.uploads == (1 if saved_status == 'completed' else 0)


def test_real_render_retry_consumes_same_result_and_wait_refresh_never_renders(render_runtime, monkeypatch):
    case = render_runtime
    case.lifecycle.failures['md'] = [TimeoutError('Isolated renderer transport failure.')]
    first = case.execute(case.initial)
    assert first['status'] == 'waiting', first
    assert first['artifacts'] == []
    assert len(first['outputs']) == 1 and first['outputs'][0]['state'] == 'retry_scheduled'
    assert first['outputs'][0]['file_name'] == 'Prepared_report.md'
    assert first['result_outputs'][0]['kind'] == 'markdown-v1'
    wait = first['pending_results']['file']
    assert set(wait) == {'kind', 'output_id', 'error_code'}
    assert wait['error_code'] == first['outputs'][0]['error_code']
    original = case.lifecycle.raw(wait['output_id'])
    original_task = first['task_results']['draft']
    original_guard = case.initial['execution_lease']['token']

    pending_claim = case.claim('pending-file-event')
    assert pending_claim['execution_lease']['token'] == original_guard

    def forbidden(*args, **kwargs):
        raise AssertionError('A saved output read entered rendering, reconciliation or retry scheduling.')

    with monkeypatch.context() as reads_only:
        for method in ('ensure_output', 'render_attempt', 'reconcile', 'claim_due', 'manual_retry'):
            reads_only.setattr(case.lifecycle.service, method, forbidden)
        pending = case.execute(pending_claim)
    assert pending['status'] == 'waiting', pending
    assert pending['task_results']['draft'] == original_task
    assert pending['pending_results']['file'] == wait
    assert case.lifecycle.render_calls == [('md', 'prepared_text_v1')]
    assert len(case.calls) == 1 and case.lifecycle.blobs.uploads == 0

    case.lifecycle.advance_due(first['outputs'][0])
    rendered = case.lifecycle.run(first['outputs'][0])
    assert rendered['state'] == 'completed'
    with monkeypatch.context() as reads_only:
        for method in ('ensure_output', 'render_attempt', 'reconcile', 'claim_due', 'manual_retry'):
            reads_only.setattr(case.lifecycle.service, method, forbidden)
        complete = case.execute(case.claim('completed-file-event'))
    assert complete['status'] == 'completed', complete
    assert complete['pending_results'] == {}
    assert complete['task_results']['draft'] == original_task
    assert 'file' not in complete['task_results']
    assert len(complete['artifacts']) == len(complete['outputs']) == 1
    assert complete['outputs'][0]['output_id'] == wait['output_id']
    assert complete['outputs'][0]['state'] == 'completed'
    assert case.state['events'][-1]['outputs'] == complete['outputs']
    assert 'result_outputs' not in case.state['events'][-1]
    saved = case.current()
    assert saved['outputs'] == complete['outputs'] and saved['result_outputs'] == complete['result_outputs']
    final_output = case.lifecycle.raw(wait['output_id'])
    assert final_output['producer'] == original['producer']
    assert final_output['source_ref'] == original['source_ref']
    assert final_output['deadline_at'] == original['deadline_at']
    assert len(case.calls) == 1 and case.lifecycle.blobs.uploads == 1
    assert len(case.lifecycle.render_calls) == 2
    content = case.lifecycle.download(complete['outputs'][0])
    assert content.decode('utf-8').endswith('The authoritative final paragraph.')


@pytest.mark.parametrize('read_outage', [False, True])
def test_waiting_render_passes_full_checkpoint_to_public_resumer(
    render_runtime, monkeypatch, read_outage,
):
    case = render_runtime
    case.lifecycle.failures['md'] = [TimeoutError('Isolated renderer transport failure.')]
    first = case.execute(case.initial)
    output_id = first['pending_results']['file']['output_id']
    checkpoint = case.recovery.checkpoint_store(case.current(), lambda: True)
    saved = checkpoint.load('file', waiting=True)
    rendering = importlib.import_module('functions_orchestration_rendering')
    resume = rendering.resume_render_file
    read = case.lifecycle.runs.read_item
    received = []

    def unavailable(item, partition_key, **kwargs):
        if item == output_id:
            raise ServiceResponseError('Isolated saved-output metadata outage.')
        return read(item=item, partition_key=partition_key, **kwargs)

    def observe(step, context, pending_result, **kwargs):
        received.append(deepcopy(pending_result))
        if read_outage and len(received) == 1:
            with monkeypatch.context() as outage:
                outage.setattr(case.lifecycle.runs, 'read_item', unavailable)
                return resume(step, context, pending_result, **kwargs)
        return resume(step, context, pending_result, **kwargs)

    def forbidden(*args, **kwargs):
        raise AssertionError('Saved-output observation cannot admit, render or schedule another attempt.')

    monkeypatch.setattr(rendering, 'resume_render_file', observe)
    with monkeypatch.context() as reads_only:
        for method in ('ensure_output', 'render_attempt', 'reconcile', 'claim_due', 'manual_retry'):
            reads_only.setattr(case.lifecycle.service, method, forbidden)
        claimed = case.claim('full-render-checkpoint')
        if read_outage:
            with pytest.raises(OutputStorageError):
                case.execute(claimed)
            current = case.current()
            remaining = case.recovery.checkpoint_store(current, lambda: True).load('file', waiting=True)
            file_step = next(step for step in current['execution_steps'] if step['step_id'] == 'file')
            assert remaining == saved
            assert file_step['status'] == 'waiting'
            assert file_step['failure'] is None
            assert current['pending_results']['file'] == first['pending_results']['file']
            pending = case.execute(case.claim('full-render-checkpoint-recheck'))
        else:
            pending = case.execute(claimed)

    assert received == [saved['result']] * (2 if read_outage else 1)
    assert received[0]['outputs'] == first['steps'][1]['outputs']
    assert pending['status'] == 'waiting'
    assert pending['task_results'] == first['task_results']
    assert 'file' not in pending['task_results']
    assert pending['pending_results']['file'] == first['pending_results']['file']
    assert len(case.calls) == len(case.lifecycle.render_calls) == 1
    assert case.lifecycle.blobs.uploads == 0


@pytest.mark.parametrize('defect', ['missing', 'status', 'wait', 'kind', 'output'])
def test_render_wait_resume_requires_original_matching_checkpoint(
    render_runtime, monkeypatch, defect,
):
    case = render_runtime
    case.lifecycle.failures['md'] = [TimeoutError('Isolated renderer transport failure.')]
    case.execute(case.initial)
    payload = case.recovery.checkpoint_store(case.current(), lambda: True).load('file', waiting=True)
    saved = deepcopy(payload['result'])
    if defect == 'missing':
        saved = None
    elif defect == 'status':
        saved['status'] = 'completed'
    elif defect == 'wait':
        saved.pop('wait')
    elif defect == 'kind':
        saved['wait']['kind'] = 'native_tabular_compute'
    else:
        saved['wait']['output_id'] = 'orender_' + '0' * 64

    def forbidden(*args, **kwargs):
        raise AssertionError('A missing or mismatched saved wait must not enter the output reader.')

    rendering = importlib.import_module('functions_orchestration_rendering')
    monkeypatch.setattr(rendering, 'resume_render_file', forbidden)
    with pytest.raises(ResultContractError) as raised:
        resume_waiting_dependency_step(
            case.plan['steps'][1], case.state['context'], settings=case.settings, user_id='owner',
            input_fingerprint=payload['input_fingerprint'], saved_result=saved,
        )
    assert raised.value.code == 'result_wait_invalid'
    assert len(case.calls) == len(case.lifecycle.render_calls) == 1
    assert case.lifecycle.blobs.uploads == 0


def test_render_wait_resume_accepts_legacy_two_field_wait(render_runtime):
    case = render_runtime
    case.lifecycle.failures['md'] = [TimeoutError('Isolated renderer transport failure.')]
    first = case.execute(case.initial)
    payload = case.recovery.checkpoint_store(case.current(), lambda: True).load('file', waiting=True)
    saved = deepcopy(payload['result'])
    saved['wait'].pop('error_code', None)
    case.state['context'].pending_results['file'] = deepcopy(saved['wait'])

    result = resume_waiting_dependency_step(
        case.plan['steps'][1], case.state['context'], settings=case.settings, user_id='owner',
        input_fingerprint=payload['input_fingerprint'], saved_result=saved,
    )
    assert set(saved['wait']) == {'kind', 'output_id'}
    assert result['status'] == 'waiting' and result['outputs'] == first['outputs']
    assert result['wait']['error_code'] == first['outputs'][0]['error_code']
    assert result.get('task_result') is None
    assert len(case.calls) == len(case.lifecycle.render_calls) == 1
    assert case.lifecycle.blobs.uploads == 0


def test_completed_render_checkpoint_is_reopened_without_render_or_model_replay(render_runtime):
    case = render_runtime
    first = case.execute(case.initial)
    assert first['status'] == 'completed', first
    result = case.execute(_restart_completed(case))
    assert result['status'] == 'completed', result
    assert result['outputs'] == first['outputs'] and result['artifacts'] == first['artifacts']
    assert len(case.calls) == len(case.lifecycle.render_calls) == case.lifecycle.blobs.uploads == 1


@pytest.mark.parametrize('saved_status', ['waiting', 'completed'])
@pytest.mark.parametrize('change', ['output_id', 'file_name', 'profile', 'attempt', 'approved_work', 'deadline'])
def test_saved_output_cannot_change_its_identity_or_approved_inputs(
    render_runtime, monkeypatch, change, saved_status,
):
    case = render_runtime
    if saved_status == 'waiting':
        case.lifecycle.failures['md'] = [TimeoutError('Isolated renderer transport failure.')]
    first = case.execute(case.initial)
    context = case.state['context']
    step = deepcopy(case.plan['steps'][1])
    saved = deepcopy(first['steps'][1])
    if change == 'output_id':
        if saved_status == 'waiting':
            saved['wait']['output_id'] = 'orender_' + '0' * 64
        else:
            saved['outputs'][0]['output_id'] = 'orender_' + '0' * 64
    elif change == 'file_name':
        step['arguments']['file_name'] = 'A different report.md'
    elif change == 'profile':
        step['arguments']['profile'] = 'a_different_profile'
    elif change == 'attempt':
        context.attempt_index += 1
    elif change == 'approved_work':
        context.approved_work_id = 'different-approved-work'
    else:
        context.execution_deadline_at = case.lifecycle.now.isoformat()
    rendering = importlib.import_module('functions_orchestration_rendering')
    resume = rendering.resume_render_file
    received = []

    def observe(step, context, pending_result, **kwargs):
        received.append(deepcopy(pending_result))
        return resume(step, context, pending_result, **kwargs)

    monkeypatch.setattr(rendering, 'resume_render_file', observe)
    before = _render_effects(case)
    result = _render_dependency_step(
        step, context, settings=case.settings, user_id='owner', saved_result=saved,
    )
    after = _render_effects(case)
    assert received == [saved] and after == before
    assert result['status'] == 'failed', result
    assert result['artifacts'] == [] and result.get('task_result') is None
    assert len(case.calls) == len(case.lifecycle.render_calls) == 1
    assert case.lifecycle.blobs.uploads == (1 if saved_status == 'completed' else 0)


def test_saved_preview_state_cannot_promote_a_pending_output(render_runtime):
    case = render_runtime
    case.lifecycle.failures['md'] = [TimeoutError('Isolated renderer transport failure.')]
    first = case.execute(case.initial)
    saved = deepcopy(first['steps'][1])
    saved['wait']['state'] = 'completed'
    saved['outputs'][0]['state'] = 'completed'
    result = _render_dependency_step(
        case.plan['steps'][1], case.state['context'], settings=case.settings, user_id='owner',
        saved_result=saved,
    )
    assert result['status'] == 'waiting' and result['artifacts'] == []
    assert result['outputs'][0]['state'] == 'retry_scheduled'
    assert set(result['wait']) == {'kind', 'output_id', 'error_code'}
    assert result['wait']['error_code'] == result['outputs'][0]['error_code']
    assert len(case.calls) == len(case.lifecycle.render_calls) == 1


@pytest.mark.parametrize('render_runtime', [2], indirect=True)
def test_sibling_wait_checkpoint_cannot_resurrect_a_completed_file(render_runtime):
    case = render_runtime
    case.lifecycle.failures['md'] = [
        TimeoutError('First isolated output failure.'),
        TimeoutError('Second isolated output failure.'),
    ]
    first = case.execute(case.initial)
    assert first['status'] == 'waiting', first
    assert set(first['pending_results']) == {'file', 'file-2'}
    assert len(first['outputs']) == 2 and first['artifacts'] == []
    original_task = first['task_results']['draft']

    case.lifecycle.advance_due(first['outputs'][0])
    first_file = case.lifecycle.run(first['outputs'][0])
    assert first_file['state'] == 'completed'
    pending = case.execute(case.claim('first-of-two-files-completed'))
    assert pending['status'] == 'waiting', pending
    assert set(pending['pending_results']) == {'file-2'}
    assert [output['state'] for output in pending['outputs']] == ['completed', 'retry_scheduled']
    assert len(pending['artifacts']) == 1
    assert pending['artifacts'][0]['output_id'] == first_file['output_id']
    assert pending['task_results']['draft'] == original_task

    case.lifecycle.advance_due(first['outputs'][1])
    second_file = case.lifecycle.run(first['outputs'][1])
    assert second_file['state'] == 'completed'
    complete = case.execute(case.claim('second-of-two-files-completed'))
    assert complete['status'] == 'completed', complete
    assert complete['pending_results'] == {}
    assert len(complete['artifacts']) == 2 and len(complete['outputs']) == 2
    assert set(complete['task_results']) == {'draft'}
    assert complete['task_results']['draft'] == original_task
    assert len(case.calls) == 1 and len(case.lifecycle.render_calls) == 4
    assert case.lifecycle.blobs.uploads == 2


@pytest.mark.parametrize('boundary', ['before_attempt', 'after_commit'])
def test_initial_render_read_outage_preserves_admitted_wait_without_a_task(
    render_runtime, monkeypatch, boundary,
):
    case = render_runtime
    read = case.lifecycle.runs.read_item
    render = case.lifecycle.service.render_attempt
    faults = []
    armed = {}

    def read_with_outage(item, partition_key, **kwargs):
        if armed.get('output_id') == item:
            armed.clear()
            faults.append(item)
            raise ServiceResponseError('Isolated output acknowledgement read failure.')
        return read(item=item, partition_key=partition_key, **kwargs)

    def render_with_outage(output_id, **kwargs):
        if boundary == 'before_attempt':
            armed['output_id'] = output_id
        output = render(output_id, **kwargs)
        if boundary == 'after_commit':
            armed['output_id'] = output_id
        return output

    with monkeypatch.context() as outage:
        outage.setattr(case.lifecycle.runs, 'read_item', read_with_outage)
        outage.setattr(case.lifecycle.service, 'render_attempt', render_with_outage)
        first = case.execute(case.initial)

    assert len(faults) == 1
    assert first['status'] == 'waiting', first
    step = first['steps'][1]
    assert step['status'] == 'waiting' and step['failure'] is None
    assert step.get('task_result') is None
    assert step['output_error'] == {'code': 'output_storage_unavailable', 'retryable': True}
    assert bool(step['outputs']) == (boundary == 'before_attempt')
    assert set(first['task_results']) == {'draft'}
    wait = first['pending_results']['file']
    assert wait == {
        'kind': 'orchestration_output', 'output_id': faults[0], 'error_code': 'output_storage_unavailable',
    }
    checkpoint = case.recovery.checkpoint_store(case.current(), lambda: True)
    saved_wait = checkpoint.load('file', waiting=True)
    assert saved_wait['result']['wait'] == wait
    assert saved_wait['result']['output_error'] == step['output_error']
    assert saved_wait['result']['outputs'] == step['outputs']
    assert saved_wait['result']['artifacts'] == [] and saved_wait['result'].get('task_result') is None

    if boundary == 'before_attempt':
        output = case.lifecycle.run(first['outputs'][0])
        assert output['state'] == 'completed'

    def forbidden(*args, **kwargs):
        raise AssertionError('Admitted output recovery repeated work instead of reading its commit.')

    with monkeypatch.context() as reads_only:
        for method in ('ensure_output', 'render_attempt', 'reconcile', 'claim_due', 'manual_retry'):
            reads_only.setattr(case.lifecycle.service, method, forbidden)
        complete = case.execute(case.claim(f'{boundary}-acknowledged'))
    assert complete['status'] == 'completed'
    assert complete['pending_results'] == {}
    assert complete['task_results'] == first['task_results']
    assert complete['outputs'][0]['output_id'] == wait['output_id']
    assert len(complete['artifacts']) == len(case.calls) == 1
    assert len(case.lifecycle.render_calls) == case.lifecycle.blobs.uploads == 1


@pytest.mark.parametrize('defect', [
    'missing_error', 'false_retryable', 'invalid_retryable', 'missing_code', 'empty_code',
    'missing_wait', 'wrong_kind', 'invalid_id', 'mismatched_code',
    'failure', 'artifact', 'task_result', 'completed',
])
def test_empty_render_outputs_require_an_admitted_retryable_wait(defect):
    result = build_step_result(
        status='waiting', wait={
            'kind': 'orchestration_output', 'output_id': 'orender_' + 'a' * 64,
            'error_code': 'output_storage_unavailable',
        },
    )
    result.update(outputs=[], output_error={'code': 'output_storage_unavailable', 'retryable': True})
    if defect == 'missing_error':
        result.pop('output_error')
    elif defect in ('false_retryable', 'invalid_retryable'):
        result['output_error']['retryable'] = False if defect == 'false_retryable' else 'true'
    elif defect == 'missing_code':
        result['output_error'].pop('code')
    elif defect == 'empty_code':
        result['output_error']['code'] = ''
    elif defect == 'missing_wait':
        result.pop('wait')
    elif defect == 'wrong_kind':
        result['wait']['kind'] = 'native_tabular_compute'
    elif defect == 'invalid_id':
        result['wait']['output_id'] = 'foreign-output'
    elif defect == 'mismatched_code':
        result['wait']['error_code'] = 'different-error'
    elif defect == 'failure':
        result['failure'] = {'code': 'step_failed'}
    elif defect == 'artifact':
        result['artifacts'] = [{'artifact_message_id': 'unverified-file'}]
    elif defect == 'task_result':
        result['task_result'] = {}
    else:
        result['status'] = 'completed'
    with pytest.raises(ResultContractError):
        _validate_render_step_result({'step_id': 'file', 'arguments': {}}, result)
