# test_orchestration_dependency_runtime.py
"""Real Gather / Reason / Render compiler, executor, composition, retained readers and checkpoints.

Version: 0.261.139
Implemented in: 0.261.127
Pending-Gather regression implemented in: 0.261.129
Single orchestration contract updated in: 0.261.139
External model/search/storage I/O is isolated; no paid or provider calls.
"""

from copy import deepcopy
from dataclasses import replace
import json
import socket
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pytest

from test_support.app_stubs import stubbed_app_imports
from test_support.orchestration_research import document_action_policy_module


SETTINGS = {'enable_user_workspace': True, 'chat_orchestration_max_steps': 8}


@pytest.fixture
def runtime(monkeypatch):
    monkeypatch.setitem(sys.modules, 'functions_document_actions', document_action_policy_module())
    with stubbed_app_imports(), patch.object(
        socket.socket, 'connect', side_effect=AssertionError('Unexpected external I/O'),
    ):
        import functions_orchestration_checkpoints as checkpoints
        import functions_orchestration_composition as composition
        import functions_orchestration_executor as executor
        import functions_orchestration_registry as registry
        import functions_orchestration_result_contracts as contracts
        import functions_orchestration_result_runtime as result_runtime
        import functions_orchestration_schema as schema
        from functions_model_capabilities import ModelTokenBudget
        from functions_orchestration_results import NamedOutput
        from test_support.orchestration_results import ResultFixture, complete

        class Model:
            def __init__(self, replies):
                self.replies = list(replies)
                self.calls = []
                self.usage = {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0}
                self.model_metadata = ModelTokenBudget(
                    model_id='offline-composition', provider='openai', context_window=32768,
                    input_limit=24576, output_limit=2048, output_accounting='total_generation',
                )
                self.output_tokens = 512
                self.provider = 'openai'

            def __call__(self, messages, **kwargs):
                self.calls.append((deepcopy(messages), deepcopy(kwargs)))
                if not self.replies:
                    raise AssertionError('Unexpected additional content-generation call')
                for key, value in (('prompt_tokens', 7), ('completion_tokens', 3), ('total_tokens', 10)):
                    self.usage[key] += value
                reply = self.replies.pop(0)
                if isinstance(reply, Exception):
                    raise reply
                return reply

        def make(
            steps, replies=(), *, final_response=None, settings=None, aliases=None,
            profiles=None, profile_validator=None,
        ):
            settings = {**SETTINGS, **(settings or {})}
            raw = {'steps': deepcopy(steps), 'run_id': 'run-1', 'plan_id': 'plan-1', 'turn_id': 'turn-1'}
            if final_response is not None:
                raw['final_response'] = final_response
            plan = schema.normalize_plan(
                raw, 'conversation-1', 'owner', settings=settings, contract_version=2,
                available_capability_ids=['compose', 'document_search', 'document_analyze', 'document_compare'],
                existing_results=aliases, composition_profiles=profiles,
            )
            fixture = ResultFixture(blob=True)
            fixture.runs['run-1']['plan'] = deepcopy(plan)
            model = Model(replies)
            context = executor.RunContext(
                run_id='run-1', plan_id='plan-1', conversation_id='conversation-1', user_id='owner',
                user_message='Prepare the requested content.', plan_contract_version=2,
                result_service=fixture.service, result_aliases=aliases,
                result_guard_token_for_step=lambda step_id: 'owned-execution-token',
                resolve_source_manifest=fixture.resolve, invoke_prompt=model,
                composition_profiles=profiles, composition_profile_validator=profile_validator,
            )
            context.prompt_token_usage = model.usage
            return SimpleNamespace(plan=plan, fixture=fixture, context=context, model=model, settings=settings)

        yield SimpleNamespace(
            checkpoints=checkpoints, composition=composition,
            executor=executor, registry=registry, contracts=contracts, schema=schema,
            result_runtime=result_runtime, NamedOutput=NamedOutput, complete=complete,
            make=make,
        )


def binding(step_id=None, output='answer', *, alias=None):
    return {
        'version': 'orchestration-input-binding-v1', 'step_id': step_id,
        'output_name': None if alias else output, 'existing_result': alias,
    }


def compose(step_id='draft', *, inputs=None, outputs=None, depends_on=None):
    return {
        'step_id': step_id, 'capability_id': 'compose',
        'arguments': {'instruction': f'Prepare {step_id} from the named inputs, or create original content.'},
        'inputs': inputs or {}, 'outputs': outputs or [{'name': 'answer', 'kind': 'markdown-v1'}],
        'depends_on': depends_on or [],
    }


def source_input(step_id, output='prepared', *, partial=False):
    return {'binding': binding(step_id, output), 'allow_partial': partial}


def set_result_contract(monkeypatch, registry, capability_id, contract):
    """Simulate a server-side revision of one producer's result contract."""
    descriptor = next(item for item in registry.CAPABILITY_REGISTRY if item['id'] == capability_id)
    monkeypatch.setitem(descriptor, 'result_contract_version', contract)


def execute(runtime, case, **kwargs):
    return runtime.executor.execute_plan(
        case.plan, case.context, settings=case.settings, user_id='owner',
        **kwargs,
    )


def test_text_answer_uses_one_call_and_retains_exact_content(runtime):
    case = runtime.make([compose()], ['Exact answer.\n\nNo second synthesis.'], final_response=binding('draft'))
    events = []
    result = execute(runtime, case, emit=events.append)
    assert result['status'] == 'completed'
    assert result['message'] == 'Exact answer.\n\nNo second synthesis.'
    assert len(case.model.calls) == 1
    assert result['artifacts'] == []
    assert result['outputs'] == events[-1]['outputs'] == []
    assert 'result_outputs' not in events[-1]
    assert result['result_outputs'][0]['kind'] == 'markdown-v1'
    assert result['result_outputs'][0]['status'] == 'complete'
    task = runtime.contracts.TaskResult.from_dict(result['task_results']['draft'])
    reader = case.fixture.restart().open_result(task.output('answer'))
    text = reader.read_text()
    metadata = reader.metadata()
    assert text == result['message']
    assert metadata['origin'] == 'generated'


def test_default_dispatch_uses_shared_v2_resolver_and_keeps_render_extension(runtime, monkeypatch):
    """The shared resolver added in 0.261.126 owns non-Render v2 selection."""
    resolve = runtime.executor._default_get_adapter
    calls = []

    def observed(name, *, contract_version=1):
        calls.append((name, contract_version))
        return resolve(name, contract_version=contract_version)

    monkeypatch.setattr(runtime.executor, '_default_get_adapter', observed)
    case = runtime.make([compose()], ['One shared-resolver composition.'], final_response=binding('draft'))
    result = execute(runtime, case)
    assert result['status'] == 'completed' and result['message'] == 'One shared-resolver composition.'
    assert len(case.model.calls) == 1 and calls == [('compose', 2)]
    response_adapter = runtime.executor._dependency_adapter('respond')
    render_adapter = runtime.executor._dependency_adapter('render_file')
    assert response_adapter is None
    assert render_adapter is runtime.executor._render_dependency_step
    assert calls == [('compose', 2), ('respond', 2)]


def test_source_free_multiple_named_outputs_and_structured_types(runtime):
    columns = [{'name': 'id', 'value_type': 'string', 'nullable': False}]
    outputs = [
        {'name': 'config', 'kind': 'structured-v1', 'schema': {
            'type': 'object', 'properties': {'enabled': {'type': 'boolean'}, 'nested': {'type': 'array'}},
            'required': ['enabled', 'nested'], 'additionalProperties': False,
        }},
        {'name': 'rows', 'kind': 'records-v1', 'columns': columns},
        {'name': 'report', 'kind': 'markdown-v1'},
    ]
    values = {
        'config': {'enabled': False, 'nested': [None, '001', 2, True]},
        'rows': [{'id': '001'}, {'id': '=SUM(A1:A2)'}, {'id': '\u00e9-last'}],
        'report': '# Prepared report\n\nFull content.',
    }
    case = runtime.make([compose(outputs=outputs)], [json.dumps(values)])
    result = execute(runtime, case)
    assert result['status'] == 'completed'
    assert len(case.model.calls) == 1
    assert result['message'] == 'The requested content is prepared. No downloadable files were created.'
    task = runtime.contracts.TaskResult.from_dict(result['task_results']['draft'])
    service = case.fixture.restart()
    data = service.open_result(task.output('config')).read_value()
    records = list(service.open_result(task.output('rows')).iter_records())
    report = service.open_result(task.output('report')).read_text()
    assert data == values['config'] and records == values['rows'] and report == values['report']
    assert result['delivery_facts'] == {'files': []}


def test_interleaved_dag_uses_full_named_gather_outputs_and_no_sibling_notes(runtime, monkeypatch):
    steps = [
        compose('answer', inputs={'new_sources': source_input('second')}),
        {'step_id': 'first', 'capability_id': 'document_search', 'arguments': {'query': 'first query'}},
        compose('reason', inputs={'sources': source_input('first', 'evidence')}),
        {'step_id': 'second', 'capability_id': 'document_search', 'arguments': {'query': 'different approved query'},
         'depends_on': ['reason']},
    ]
    case = runtime.make(steps, ['Prepared intermediate question.', 'Prepared final answer.'], final_response=binding('answer'))
    case.context.notes = ['UNDECLARED_SIBLING_SECRET']
    seen = []
    search = ModuleType('functions_search')

    def hybrid_search(query, user_id, **kwargs):
        seen.append(query)
        return [
            {'document_id': 'document-1', 'id': 'first-hit', 'chunk_text': 'First complete returned excerpt.'},
            {'document_id': 'document-1', 'id': 'last-hit', 'chunk_text': 'Last complete returned excerpt.'},
        ]

    search.hybrid_search = hybrid_search
    monkeypatch.setitem(sys.modules, 'functions_search', search)
    result = execute(runtime, case)
    assert [step['step_id'] for step in result['steps']] == ['first', 'reason', 'second', 'answer']
    assert [step['role'] for step in result['steps']] == ['gather', 'reason', 'gather', 'reason']
    assert result['status'] == 'completed'
    assert len(seen) == 2 and len(case.model.calls) == 2
    first_prompt = case.model.calls[0][0][-1]['content']
    assert 'Last complete returned excerpt.' in first_prompt
    assert 'UNDECLARED_SIBLING_SECRET' not in json.dumps(case.model.calls)
    task = case.context.task_results['first']
    reader = case.fixture.restart().open_result(task.output('prepared'))
    value = reader.read_value()
    assert value['content_scope'] == 'returned_excerpts'
    assert value['evidence'][0]['evidence'][-1]['chunk_text'] == 'Last complete returned excerpt.'
    assert value['citations'][-1]['citation_id'] == 'last-hit'


@pytest.mark.parametrize('case_name', [
    'missing', 'disabled', 'cycle', 'wrong_output', 'unknown_capability', 'unknown_argument',
    'unknown_input_kind', 'duplicate_step', 'duplicate_output', 'step_budget', 'alias', 'role',
])
def test_invalid_plans_fail_without_repair_or_dropping_work(runtime, case_name):
    raw = {
        'planner_contract_version': 2,
        'steps': [compose('producer'), compose('consumer', inputs={'value': source_input('producer', 'answer')})],
    }
    settings = dict(SETTINGS)
    if case_name == 'missing':
        raw['steps'][1]['inputs']['value'] = source_input('missing')
    elif case_name == 'disabled':
        raw['steps'][0]['enabled'] = False
    elif case_name == 'cycle':
        raw['steps'][0]['depends_on'] = ['consumer']
    elif case_name == 'wrong_output':
        raw['steps'][1]['inputs']['value'] = source_input('producer', 'absent')
    elif case_name == 'unknown_capability':
        raw['steps'][0]['capability_id'] = 'render_file'
    elif case_name == 'unknown_argument':
        raw['steps'][0]['arguments']['allow_generated_files'] = True
    elif case_name == 'unknown_input_kind':
        raw['steps'][0]['outputs'][0]['kind'] = 'imaginary-v1'
    elif case_name == 'duplicate_step':
        raw['steps'][1]['step_id'] = 'producer'
    elif case_name == 'duplicate_output':
        raw['steps'][0]['outputs'] *= 2
    elif case_name == 'step_budget':
        settings['chat_orchestration_max_steps'] = 1
    elif case_name == 'alias':
        raw['steps'][1]['inputs']['value']['binding'] = binding(alias='not-admitted')
    elif case_name == 'role':
        raw['steps'][0]['role'] = 'render'
    original = deepcopy(raw)
    with pytest.raises(runtime.schema.PlanValidationError):
        runtime.schema.validate_plan(
            raw, settings=settings, available_capability_ids=['compose', 'document_search'],
        )
    assert raw == original


def test_kind_mismatch_and_unsupported_profile_are_rejected(runtime):
    case = runtime.make([compose(outputs=[{'name': 'data', 'kind': 'structured-v1'}])])
    case.plan['final_response'] = binding('draft', 'data')
    with pytest.raises(runtime.schema.PlanValidationError) as failure:
        runtime.schema.validate_plan(case.plan, settings=SETTINGS, available_capability_ids=['compose'])
    assert failure.value.code == 'result_kind_incompatible'
    with pytest.raises(runtime.schema.PlanValidationError):
        runtime.make([compose(outputs=[{'name': 'slides', 'kind': 'structured-v1', 'profile': 'unimplemented-slides'}])])


@pytest.mark.parametrize('capability', ['compose', 'document_search'])
def test_no_implicit_files_and_no_permission_from_plan_arguments(runtime, capability):
    step = compose() if capability == 'compose' else {
        'step_id': 'search', 'capability_id': 'document_search', 'arguments': {'query': 'Read evidence.'},
    }
    case = runtime.make([step])
    from functions_orchestration_execution_policy import (
        generated_file_publication_allowed, require_generated_file_publication_allowed,
    )
    observed = []

    def attempted_file(step, context, **kwargs):
        observed.append(generated_file_publication_allowed())
        require_generated_file_publication_allowed()
        raise AssertionError('Managed publication should have failed')

    result = execute(runtime, case, get_adapter=lambda capability: attempted_file)
    assert observed == [False]
    assert result['status'] == 'failed'
    assert result['failure']['code'] == 'file_publication_not_allowed'
    assert result['artifacts'] == [] and case.model.calls == []
    after = generated_file_publication_allowed()
    assert after is True


def test_pending_work_is_waiting_not_a_successful_preview_or_synthesis(runtime):
    case = runtime.make([
        compose('native'), compose('answer', inputs={'data': source_input('native', 'answer')}),
    ], final_response=binding('answer'))
    calls = []
    events = []

    def pending(step, context, **kwargs):
        calls.append(step['step_id'])
        return runtime.schema.build_step_result(
            status='waiting', notes=['A preview is not final data.'],
            task_result=runtime.contracts.TaskResult(context.result_producer(step), 'reason', 'pending', ()),
            wait={'kind': 'native_compute', 'job_id': 'server-owned-job'},
        )

    result = execute(runtime, case, get_adapter=lambda capability: pending, emit=events.append)
    again = execute(runtime, case, get_adapter=lambda capability: pending)
    assert calls == ['native']
    assert result['status'] == again['status'] == 'waiting'
    assert result['completed_at'] is None and result['message'] != 'A preview is not final data.'
    assert case.model.calls == []
    assert result['pending_results']['native']['job_id'] == 'server-owned-job'
    assert result['outputs'] == []
    assert all(output['status'] == 'pending' for output in result['result_outputs'])
    assert events[-1]['phase'] == 'waiting'


@pytest.mark.parametrize('status', ['pending', 'waiting'])
@pytest.mark.parametrize('typed_pending', [False, True])
def test_pending_gather_requires_its_typed_wait_before_any_consumer(runtime, status, typed_pending):
    case = runtime.make([
        {'step_id': 'search', 'capability_id': 'document_search', 'arguments': {'query': 'approved query'}},
        compose('answer', inputs={'sources': source_input('search')}),
    ], ['A pending preview must never be consumed.'], final_response=binding('answer'))
    calls = []

    def gather(step, context, **kwargs):
        calls.append(step['step_id'])
        task = (
            runtime.contracts.TaskResult(context.result_producer(step), 'gather', 'pending', ())
            if typed_pending else None
        )
        return runtime.schema.build_step_result(
            status=status, notes=['Only a pending preview.'], task_result=task,
            wait={
                'kind': 'orchestration_result',
                'input_fingerprint': context.result_input_fingerprint_for_step(step['step_id']),
            },
        )

    result = execute(
        runtime, case, get_adapter=lambda capability: (
            gather if capability == 'document_search' else runtime.composition.adapter_compose
        ),
    )
    assert result['status'] == ('waiting' if typed_pending else 'failed')
    assert result['steps'][0]['status'] == ('waiting' if typed_pending else 'failed')
    assert calls == ['search'] and case.model.calls == []
    assert case.fixture.container.items == {} and case.fixture.blobs.records == {}
    if typed_pending:
        assert case.context.task_results['search'].status == 'pending'
        assert case.context.task_results['search'].outputs == ()
    else:
        assert case.context.task_results == {} and case.context.pending_results == {}
        assert result['steps'][0]['failure']['code'] == 'result_invalid'


@pytest.mark.parametrize('allow_partial', [False, True])
def test_partial_input_is_never_promoted(runtime, allow_partial):
    case = runtime.make([
        compose('upstream'), compose('answer', inputs={'draft': source_input('upstream', 'answer', partial=allow_partial)}),
    ], ['Prepared limited answer.'], final_response=binding('answer'))
    partial = runtime.contracts.Completeness(
        'partial', 1, 1, runtime.contracts.Coverage(2, 1, 'sources'), 'partial',
        ('retained_subset',), ('One required source could not be read.',),
    )

    def produce(step, context, **kwargs):
        if step['step_id'] != 'upstream':
            return runtime.composition.adapter_compose(step, context, **kwargs)
        task = context.result_service.persist_task_result(
            producer=context.result_producer(step), role='reason', status='partial',
            outputs=[runtime.NamedOutput('answer', 'markdown-v1', 'Exact retained subset.', partial)],
            sources=[], origin='generated', guard_token=context.result_guard_token_for_step(step['step_id']),
        )
        return runtime.schema.build_step_result(status='partial', task_result=task)

    result = execute(runtime, case, get_adapter=lambda capability: produce)
    assert result['status'] == 'failed' and result['outcome'] == 'partial'
    assert len(case.model.calls) == int(allow_partial)
    if allow_partial:
        task = case.context.task_results['answer']
        assert task.status == 'partial'
        assert task.output('answer').completeness.status == 'partial'
        assert task.output('answer').completeness.limitations == partial.limitations
    else:
        assert result['steps'][1]['status'] == 'failed'


def test_successful_prose_does_not_hide_required_failure(runtime):
    case = runtime.make([compose('broken'), compose('answer')], ['An independently prepared explanation.'],
                        final_response=binding('answer'))

    def produce(step, context, **kwargs):
        if step['step_id'] == 'broken':
            return runtime.schema.build_step_result(
                status='failed', error='PRIVATE_ERROR', message='A success-shaped paragraph.',
            )
        return runtime.composition.adapter_compose(step, context, **kwargs)

    result = execute(runtime, case, get_adapter=lambda capability: produce)
    assert result['status'] == 'failed' and result['outcome'] == 'partial'
    assert result['message'].startswith('An independently prepared explanation.')
    assert 'PRIVATE_ERROR' not in json.dumps(result)
    assert len(case.model.calls) == 1


def test_failed_comparison_retains_diagnostics_without_exposing_usable_outputs(runtime, monkeypatch):
    case = runtime.make([
        {'step_id': 'compare', 'capability_id': 'document_compare', 'arguments': {
            'left_document_id': 'document-1', 'right_document_ids': ['document-2'],
            'comparison_prompt': 'Compare the complete sources.',
        }},
        compose('answer', inputs={'comparison': source_input('compare', 'comparison', partial=True)}),
    ], final_response=binding('answer'))
    case.fixture.sources['document-2'] = {
        **case.fixture.sources['document-1'], 'document_id': 'document-2',
    }
    tasks, calls, events, persisted = [], [], [], []

    def failed_compare(step, context, **kwargs):
        calls.append(step['step_id'])
        task = context.result_service.persist_task_result(
            producer=context.result_producer(step), role='reason', status='failed',
            outputs=[
                runtime.NamedOutput('comparison', 'comparison-v1', {
                    'left_document_id': 'document-1', 'right_document_ids': ['document-2'],
                    'items': [], 'failed_document_ids': ['document-2'],
                }, runtime.complete(0, status='failed', expected=1)),
                runtime.NamedOutput('coverage', 'structured-v1', {
                    'failed_document_ids': ['document-2'], 'diagnostic': 'PRIVATE_DIAGNOSTIC_CONTENT',
                }, runtime.complete(1, status='failed')),
            ],
            sources=list(case.fixture.sources.values()), origin='grounded',
            guard_token=context.result_guard_token_for_step(step['step_id']),
        )
        tasks.append(task)
        return runtime.schema.build_step_result(
            status='failed', task_result=task, error='PRIVATE_PROVIDER_ERROR',
            message='A success-shaped failure paragraph.',
        )

    with monkeypatch.context() as scoped:
        scoped.setattr(
            case.context.result_service, 'open_result',
            lambda *args, **kwargs: pytest.fail('Failed diagnostics must not be opened as consumable results.'),
        )
        result = execute(
            runtime, case, get_adapter=lambda capability: failed_compare, emit=events.append,
            persist=lambda kind, record: persisted.append((kind, deepcopy(record))),
        )
    assert calls == ['compare'] and case.model.calls == []
    assert result['status'] == result['outcome'] == 'failed'
    failed_step = result['steps'][0]
    assert failed_step['task_result'] == tasks[0].to_dict()
    assert failed_step['checkpoint_available'] is False
    assert result['steps'][1]['status'] == 'skipped'
    assert case.context.task_results == result['task_results'] == {}
    assert result['outputs'] == []
    assert all(output['status'] == 'unavailable' and 'reference' not in output for output in result['result_outputs'])
    assert any(event.get('task_result') == tasks[0].to_dict() for event in events)
    assert any(kind == 'step' and record.get('task_result') == tasks[0].to_dict() for kind, record in persisted)
    assert 'PRIVATE_DIAGNOSTIC_CONTENT' not in json.dumps(result)
    assert 'PRIVATE_PROVIDER_ERROR' not in json.dumps(result)
    assert 'success-shaped failure paragraph' not in json.dumps(result)
    restarted = case.fixture.restart()
    for reference in tasks[0].outputs:
        with pytest.raises(runtime.contracts.ResultContractError):
            restarted.open_result(reference, allow_partial=True)
    with pytest.raises(runtime.contracts.ResultContractError):
        runtime.result_runtime.validate_task_outputs(case.plan['steps'][0], case.context, tasks[0])
    for reference in (
        replace(tasks[0].outputs[0], output_name='unregistered'),
        replace(tasks[0].outputs[0], kind='structured-v1'),
    ):
        invalid = replace(tasks[0], outputs=(reference,))
        with pytest.raises(runtime.contracts.ResultContractError):
            runtime.result_runtime.validate_task_diagnostics(case.plan['steps'][0], case.context, invalid)


@pytest.mark.parametrize('invalid', ['producer', 'role', 'status', 'descriptor', 'deleted'])
def test_failed_diagnostic_descriptors_require_current_trusted_producer(runtime, invalid):
    case = runtime.make([compose()])

    def failed(step, context, **kwargs):
        producer = context.result_producer(step)
        if invalid == 'producer':
            producer = replace(producer, user_id='different-owner')
        task = runtime.contracts.TaskResult(
            producer, 'gather' if invalid == 'role' else 'reason',
            'pending' if invalid == 'status' else 'failed', (),
        )
        if invalid == 'deleted':
            case.fixture.conversation['orchestration_deleted'] = True
        return {'status': 'failed', 'task_result': task.to_dict() if invalid == 'descriptor' else task}

    result = execute(runtime, case, get_adapter=lambda capability: failed)
    assert result['status'] == 'failed'
    assert result['failure']['code'] == ('result_unavailable' if invalid == 'deleted' else 'result_invalid')
    assert 'task_result' not in result['steps'][0]
    assert result['task_results'] == {} and case.model.calls == []


@pytest.mark.parametrize('status', ['completed', 'failed', 'cancelled'])
def test_nonrender_artifacts_are_rejected_even_when_the_adapter_failed(runtime, status):
    case = runtime.make([compose()])

    def attempted_file(step, context, **kwargs):
        return runtime.schema.build_step_result(status=status, artifacts=[{'file_id': 'not-render-produced'}])

    result = execute(runtime, case, get_adapter=lambda capability: attempted_file)
    assert result['status'] == 'failed'
    assert result['failure']['code'] == 'file_publication_not_allowed'
    assert result['artifacts'] == [] and case.model.calls == []
    assert 'not-render-produced' not in json.dumps(result)


def test_model_budget_refuses_required_inputs_without_clipping_or_calling(runtime):
    case = runtime.make([compose()], ['Should never be used'])
    case.model.model_metadata = replace(case.model.model_metadata, input_limit=512)
    case.plan['steps'][0]['arguments']['instruction'] = 'Retain every item. ' * 1000
    result = execute(runtime, case)
    assert result['status'] == 'failed'
    assert result['failure']['code'] == 'result_input_too_large'
    assert case.model.calls == []


def test_fingerprints_are_declaration_scoped_and_every_context_saves_the_single_contract(runtime):
    case = runtime.make([compose('a'), compose('b')], ['A', 'B'])
    binding_before = runtime.checkpoints.context_binding(case.context, case.plan, case.settings)
    before = runtime.checkpoints.step_input_fingerprint(case.plan['steps'][1], case.context, binding_before, settings=case.settings)
    execute(runtime, case)
    case.context.artifacts.append({'unrelated': 'sibling artifact'})
    case.context.notes.append('unrelated sibling notes')
    after = runtime.checkpoints.step_input_fingerprint(case.plan['steps'][1], case.context, 'unrelated-binding', settings=case.settings)
    assert before == after
    changed = deepcopy(case.plan['steps'][1])
    changed['arguments']['instruction'] += ' Changed requirement.'
    different = runtime.checkpoints.step_input_fingerprint(changed, case.context, binding_before, settings=case.settings)
    assert different != before
    default = runtime.executor.RunContext()
    state = runtime.checkpoints.context_state(default)
    assert default.plan_contract_version == 2
    assert state['plan_contract_version'] == 2
    assert state['task_results'] == {} and state['result_aliases'] == {}
    assert 'task_result' not in runtime.schema.build_step_result()


def test_checkpoint_contains_refs_not_datasets_and_wait_has_separate_manifest(runtime):
    case = runtime.make([compose()], ['Exact saved content.'])
    execute(runtime, case)
    store = runtime.checkpoints.CheckpointStore(
        case.fixture.container, run_id='run-1', user_id='owner', conversation_id='conversation-1',
        turn_id='turn-1', authorize=lambda: True, token='checkpoint-owner',
    )
    store.initialize()
    step = case.plan['steps'][0]
    case.context.notes = ['INCIDENTAL_SIBLING_DATASET']
    task = case.context.task_results['draft']
    result = runtime.schema.build_step_result(task_result=task, notes=['GIANT_DATASET_SENTINEL'])
    bound = runtime.checkpoints.context_binding(case.context, case.plan, case.settings)
    stamp = runtime.checkpoints.step_input_fingerprint(step, case.context, bound, settings=case.settings)
    payload = store.commit(step, result, case.context, input_fingerprint=stamp, binding=bound)
    loaded = store.load('draft')
    encoded = json.dumps(loaded)
    assert 'GIANT_DATASET_SENTINEL' not in encoded and 'Exact saved content.' not in encoded
    assert 'INCIDENTAL_SIBLING_DATASET' not in encoded
    assert 'invoke_prompt' not in encoded and 'owned-execution-token' not in encoded
    assert loaded['result']['task_result'] == task.to_dict()
    restored = runtime.executor.RunContext(
        run_id='run-1', conversation_id='conversation-1', user_id='owner', plan_contract_version=2,
        result_service=case.fixture.restart(),
    )
    runtime.checkpoints.restore_context(restored, loaded)
    content = restored.result_service.open_result(restored.task_results['draft'].output('answer')).read_text()
    assert content == 'Exact saved content.'
    waiting = runtime.schema.build_step_result(
        status='waiting', task_result=runtime.contracts.TaskResult(
            case.context.result_producer(step), 'reason', 'pending', (),
        ), wait={'kind': 'native_compute', 'job_id': 'safe-handle'},
    )
    store.commit(step, waiting, case.context, input_fingerprint=stamp, binding=bound)
    wait_payload = store.load('draft', waiting=True)
    completed_payload = store.load('draft')
    assert wait_payload['result']['status'] == 'waiting'
    assert completed_payload == payload


@pytest.mark.parametrize('change', ['revocation', 'screening', 'revision', 'snapshot_revision', 'deletion', 'cancel'])
def test_current_access_and_cancellation_fail_closed(runtime, change):
    case = runtime.make([compose('producer'), compose('answer', inputs={'source': source_input('producer', 'answer')})],
                        ['Should not be called'], final_response=binding('answer'))
    called = []

    def produce(step, context, **kwargs):
        called.append(step['step_id'])
        if step['step_id'] == 'answer':
            return runtime.composition.adapter_compose(step, context, **kwargs)
        task = context.result_service.persist_task_result(
            producer=context.result_producer(step), role='reason', status='complete',
            outputs=[runtime.NamedOutput('answer', 'markdown-v1', 'Source-bound answer.', runtime.complete(1))],
            sources=[case.fixture.sources['document-1']], origin='grounded',
            guard_token=context.result_guard_token_for_step(step['step_id']),
            source_policy='snapshot' if change == 'snapshot_revision' else 'current',
        )
        return runtime.schema.build_step_result(task_result=task)

    def event(value):
        if value.get('step_id') != 'producer' or value.get('phase') != 'completed':
            return
        if change == 'revocation':
            case.fixture.denied.add('document-1')
        elif change == 'screening':
            case.fixture.held.add('document-1')
        elif change in ('revision', 'snapshot_revision'):
            case.fixture.sources['document-1']['source_revision'] = 'changed'
        elif change == 'deletion':
            case.fixture.conversation['orchestration_deleted'] = True
        else:
            case.fixture.runs['run-1']['cancellation_requested_at'] = 'server-stop'

    result = execute(
        runtime, case, get_adapter=lambda capability: produce, emit=event,
        cancel_requested=lambda: bool(case.fixture.runs['run-1'].get('cancellation_requested_at')),
    )
    assert result['status'] == ('cancelled' if change == 'cancel' else 'failed')
    assert result['steps'][0]['status'] == 'completed'
    assert case.model.calls == []
    assert 'Source-bound answer.' not in result['message']
    assert result['outputs'] == []
    assert result['result_outputs'][0]['status'] == 'unavailable'
    assert 'reference' not in result['result_outputs'][0]


def test_default_registry_and_plan_admission_use_the_single_contract(runtime):
    ids = runtime.registry.all_capability_ids()
    assert {'compose', 'render_file'} <= set(ids) and 'respond' not in ids
    analyze = runtime.registry.get_capability('document_analyze')
    assert analyze['role'] == 'reason' and 'phase' not in analyze
    assert runtime.registry.get_capability('respond') is None
    with pytest.raises(ValueError):
        runtime.registry.get_capability('document_analyze', contract_version=1)
    plan = runtime.schema.normalize_plan(
        {'steps': [compose()], 'final_response': binding('draft')},
        'conversation-1', 'owner', settings=SETTINGS, available_capability_ids=['compose'],
    )
    assert plan['planner_contract_version'] == 2
    with pytest.raises(runtime.schema.LegacyPlanError):
        runtime.schema.normalize_plan(
            {'steps': [compose()]}, 'conversation-1', 'owner', available_capability_ids=['compose'],
            contract_version=1,
        )


@pytest.mark.parametrize('status', ['failed', 'cancelled', 'invalid', 'unavailable', 'pending'])
def test_nonready_injected_tasks_cannot_be_completed_previews(runtime, status):
    case = runtime.make([compose()])
    case.context.task_results['draft'] = runtime.contracts.TaskResult(
        case.context.result_producer(case.plan['steps'][0]), 'reason', status, (),
    )
    with pytest.raises(runtime.contracts.ResultContractError):
        execute(runtime, case)
    assert case.model.calls == []


def test_full_record_collection_not_preview_reaches_one_call_consumer(runtime):
    columns = [{'name': 'id', 'value_type': 'string', 'nullable': False}]
    rows = [{'id': f'authoritative-record-{index:04d}'} for index in range(800)]
    case = runtime.make([
        compose('source', outputs=[{'name': 'rows', 'kind': 'records-v1', 'columns': columns}]),
        compose('answer', inputs={'rows': source_input('source', 'rows')}),
    ], ['All retained rows considered.'], final_response=binding('answer'))
    case.model.model_metadata = replace(case.model.model_metadata, context_window=250000, input_limit=200000)
    task = case.context.result_service.persist_task_result(
        producer=case.context.result_producer(case.plan['steps'][0]), role='reason', status='complete',
        outputs=[runtime.NamedOutput('rows', 'records-v1', rows, runtime.complete(len(rows)),
                                     tuple(runtime.contracts.RecordColumn.from_dict(column) for column in columns))],
        sources=[], origin='generated', guard_token=case.context.result_guard_token_for_step('source'),
    )
    case.context.task_results['source'] = task
    result = execute(runtime, case)
    assert result['status'] == 'completed' and len(case.model.calls) == 1
    payload = json.loads(case.model.calls[0][0][-1]['content'])
    assert payload['inputs']['rows']['value'] == rows


@pytest.mark.parametrize('profile_available', [False, True])
def test_structured_profile_is_explicit_and_validator_is_required_before_generation(runtime, profile_available):
    seen = []
    profile = {
        'type': 'object', 'properties': {'title': {'type': 'string'}},
        'required': ['title'], 'additionalProperties': False,
    }

    def validate(profile, value):
        seen.append((profile, value))
        return profile == 'fixture_profile' and value == {'title': 'Original structured content'}

    case = runtime.make(
        [compose(outputs=[{'name': 'data', 'kind': 'structured-v1', 'profile': 'fixture_profile'}])],
        ['{"data":{"title":"Original structured content"}}'],
        profiles={
            'fixture_profile': profile,
            'unselected_profile': {'description': 'UNSELECTED_PROFILE ' * 2000},
        },
        profile_validator=validate if profile_available else None,
    )
    result = execute(runtime, case)
    assert result['status'] == ('completed' if profile_available else 'failed')
    assert len(case.model.calls) == int(profile_available)
    assert len(seen) == int(profile_available)
    if profile_available:
        payload = json.loads(case.model.calls[0][0][-1]['content'])
        assert payload['profiles'] == {'fixture_profile': profile}


def test_selected_profile_definition_counts_toward_the_model_budget(runtime):
    case = runtime.make(
        [compose(outputs=[{'name': 'data', 'kind': 'structured-v1', 'profile': 'large_profile'}])],
        ['Should not be generated'],
        profiles={'large_profile': {'type': 'object', 'description': 'Required schema context. ' * 2000}},
        profile_validator=lambda name, value: None,
    )
    result = execute(runtime, case)
    assert result['status'] == 'failed'
    assert result['failure']['code'] == 'result_input_too_large'
    assert case.model.calls == []


@pytest.mark.parametrize('invalid', [None, 'version', 'count', 'overlap', 'table', 'image'])
def test_composition_uses_authoritative_prepared_slide_profile_without_rendering(runtime, monkeypatch, invalid):
    # These execution services load after the fixture establishes the application I/O boundary.
    from functions_generated_export_registry import PREPARED_SLIDE_DECK_VERSION, get_prepared_slide_deck_schema
    import functions_generated_office_adapters as office
    from functions_orchestration_services import composition_profiles, validate_composition_profile

    value = {
        'schema_version': PREPARED_SLIDE_DECK_VERSION, 'slide_count': 1,
        'slides': [{
            'layout': 'title_and_content', 'title': 'Prepared content', 'shapes': [
                {
                    'type': 'text_box', 'box': {'left': 0.5, 'top': 1.6, 'width': 6, 'height': 1.2},
                    'paragraphs': [{'text': 'Draft once, then render the retained value.'}],
                },
                {
                    'type': 'table', 'box': {'left': 0.5, 'top': 3.3, 'width': 6, 'height': 1.2},
                    'rows': [['Stage', 'State'], ['Reason', 'Prepared']],
                },
                {
                    'type': 'image', 'box': {'left': 7, 'top': 1.6, 'width': 4, 'height': 2.4},
                    'source': 'asset:diagram', 'alt': 'Opaque asset resolved only by the later renderer.',
                },
            ],
        }],
    }
    if invalid == 'version':
        value['schema_version'] = 'invented-slide-schema'
    elif invalid == 'count':
        value['slide_count'] = 2
    elif invalid == 'overlap':
        value['slides'][0]['shapes'][1]['box'] = deepcopy(value['slides'][0]['shapes'][0]['box'])
    elif invalid == 'table':
        value['slides'][0]['shapes'][1]['rows'][-1].pop()
    elif invalid == 'image':
        value['slides'][0]['shapes'][2]['source'] = 'https://untrusted.invalid/image.png'
    prepared_values = []
    original = office.prepare_generated_slide_deck

    def validate(value, **kwargs):
        prepared_values.append(deepcopy(value))
        return original(value, **kwargs)

    monkeypatch.setattr(office, 'prepare_generated_slide_deck', validate)
    monkeypatch.setattr(
        office.office, 'render_prepared_pptx',
        lambda *args, **kwargs: pytest.fail('Reason composition must not render an Office file.'),
    )
    profiles = composition_profiles()
    case = runtime.make(
        [compose(outputs=[{'name': 'slides', 'kind': 'structured-v1', 'profile': PREPARED_SLIDE_DECK_VERSION}])],
        [json.dumps({'slides': value})], profiles=profiles, profile_validator=validate_composition_profile,
    )
    result = execute(runtime, case)
    assert len(case.model.calls) == 1 and prepared_values == [value]
    payload = json.loads(case.model.calls[0][0][-1]['content'])
    expected_schema = get_prepared_slide_deck_schema()
    assert payload['profiles'] == {PREPARED_SLIDE_DECK_VERSION: expected_schema}
    assert result['artifacts'] == [] and result['delivery_facts'] == {'files': []}
    if invalid is not None:
        assert result['status'] == 'failed'
        assert result['failure']['code'] == 'result_invalid'
        assert result['task_results'] == {}
    else:
        assert result['status'] == 'completed'
        reference = case.context.task_results['draft'].output('slides')
        reader = case.fixture.restart().open_result(reference)
        retained = reader.read_value()
        metadata = reader.metadata()
        assert retained == value and metadata['origin'] == 'generated'


def test_failed_optional_only_work_is_not_success_by_empty_required_set(runtime):
    case = runtime.make([compose()])
    case.plan['steps'][0]['optional'] = True
    result = execute(
        runtime, case, get_adapter=lambda capability: lambda *args, **kwargs: runtime.schema.build_step_result(
            status='failed', failure=runtime.schema.build_failure('step_failed'),
        ),
    )
    assert result['status'] == 'failed'
    assert result['failure'] is not None


def test_unimplemented_retention_boundaries_are_not_offered_or_executed(runtime):
    unavailable = {}
    capabilities = runtime.registry.resolve_available_capabilities(
        {'enable_web_search': True, 'enable_user_workspace': True},
        unavailable=unavailable, contract_version=2,
    )
    assert 'web_search' not in {capability['id'] for capability in capabilities}
    assert 'tabular_analyze' not in {capability['id'] for capability in capabilities}
    assert unavailable['web_search'] == 'external_result_lineage_unavailable'
    assert unavailable['tabular_analyze'] == 'native_typed_result_bridge_unavailable'
    # Discovery asks only whether settings permit them; planning also needs the services.
    permitted = runtime.registry.resolve_available_capability_ids(
        {'enable_web_search': True, 'enable_user_workspace': True}, include_runtime_bindings=False,
    )
    assert 'web_search' in permitted and 'tabular_analyze' in permitted


def test_fixed_outputs_reject_nonstring_names_as_contract_errors(runtime):
    raw = {'planner_contract_version': 2, 'steps': [{
        'step_id': 'search', 'capability_id': 'document_search', 'arguments': {'query': 'known request'},
        'outputs': [{'name': [], 'kind': 'structured-v1'}],
    }]}
    with pytest.raises(runtime.schema.PlanValidationError):
        runtime.schema.validate_plan(raw, settings=SETTINGS, available_capability_ids=['document_search'])


@pytest.mark.parametrize('document_ids', [[''], [' document-1'], ['document-1 ']])
def test_declared_source_ids_are_not_trimmed_or_dropped(runtime, document_ids):
    raw = {'planner_contract_version': 2, 'steps': [{
        'step_id': 'search', 'capability_id': 'document_search',
        'arguments': {'query': 'An explicit source query.', 'document_ids': document_ids},
    }]}
    original = deepcopy(raw)
    with pytest.raises(runtime.schema.PlanValidationError):
        runtime.schema.validate_plan(raw, settings=SETTINGS, available_capability_ids=['document_search'])
    assert raw == original


def test_v2_edit_cannot_disable_a_bound_producer_and_preserves_original(runtime):
    case = runtime.make([
        compose('draft'), compose('answer', inputs={'draft': source_input('draft', 'answer')}),
    ], final_response=binding('answer'))
    original = deepcopy(case.plan)
    with pytest.raises(runtime.schema.PlanValidationError):
        runtime.schema.apply_plan_edits(case.plan, {'disabled_step_ids': ['draft']})
    assert case.plan == original


@pytest.mark.parametrize('problem', ['document_limit', 'document_access', 'capability_limit', 'source_kind'])
def test_required_work_limits_and_input_kinds_are_strict(runtime, problem):
    settings = {
        **SETTINGS,
        'document_action_capabilities': {'analyze': {'enabled': True, 'chat_max_documents': 2}},
    }
    raw = {'planner_contract_version': 2, 'steps': [{
        'step_id': 'analyze', 'capability_id': 'document_analyze',
        'arguments': {'analysis_prompt': 'Read every selected document.', 'document_ids': ['one', 'two']},
    }]}
    authorized = {'one', 'two'}
    if problem == 'document_limit':
        raw['steps'][0]['arguments']['document_ids'].append('three')
        authorized.add('three')
    elif problem == 'document_access':
        authorized = {'one'}
    elif problem == 'capability_limit':
        raw['steps'] = [{
            'step_id': f'search-{index}', 'capability_id': 'document_search', 'arguments': {'query': f'Query {index}'},
        } for index in range(4)]
    elif problem == 'source_kind':
        raw['steps'][0]['arguments'].pop('document_ids')
        raw['steps'][0]['inputs'] = {'sources': source_input('draft', 'answer')}
        raw['steps'].insert(0, compose())
    original = deepcopy(raw)
    with pytest.raises(runtime.schema.PlanValidationError):
        runtime.schema.validate_plan(
            raw, settings=settings, authorized_document_ids=authorized,
            available_capability_ids=['compose', 'document_analyze', 'document_search'],
        )
    assert raw == original


def test_checkpoint_reuse_cannot_substitute_another_readable_producer(runtime):
    case = runtime.make([compose('one'), compose('two')], ['First actual output.', 'Second actual output.'])
    execute(runtime, case)
    with pytest.raises(runtime.contracts.ResultContractError) as failure:
        runtime.result_runtime.validate_task_outputs(
            case.plan['steps'][1], case.context, case.context.task_results['one'], reused=True,
        )
    assert failure.value.code == 'result_producer_mismatch'


def test_skipped_work_does_not_duplicate_the_previous_steps_model_usage(runtime):
    case = runtime.make([compose('answer'), compose('disabled')], ['One prepared answer.'])
    case.plan['steps'][1]['enabled'] = False
    result = execute(runtime, case)
    assert result['status'] == 'completed'
    assert result['steps'][0]['token_usage'] == {'prompt_tokens': 7, 'completion_tokens': 3, 'total_tokens': 10}
    assert result['steps'][1]['token_usage'] == {}
    assert len(case.model.calls) == 1


def test_named_source_set_cannot_be_rebound_to_a_different_scope(runtime, monkeypatch):
    case = runtime.make([
        {'step_id': 'search', 'capability_id': 'document_search', 'arguments': {'query': 'Find a source.'}},
        {'step_id': 'analyze', 'capability_id': 'document_analyze',
         'arguments': {'analysis_prompt': 'Read the exact gathered source.'},
         'inputs': {'sources': source_input('search', 'sources')}},
    ])
    search = ModuleType('functions_search')
    search.hybrid_search = lambda *args, **kwargs: [
        {'document_id': 'document-1', 'id': 'hit-1', 'chunk_text': 'Original personal source.'},
    ]
    monkeypatch.setitem(sys.modules, 'functions_search', search)
    called = []

    def resolver(capability):
        called.append(capability)
        if capability == 'document_analyze':
            raise AssertionError('A changed source must be refused before invoking Analyze.')
        return runtime.executor._dependency_adapter(capability)

    def event(value):
        if value.get('step_id') == 'search' and value.get('phase') == 'completed':
            case.context.resolve_source_manifest = lambda ids, **scope: [{
                **case.fixture.sources['document-1'], 'scope': 'group', 'scope_id': 'different-group',
                'authorization_status': 'authorized',
            }]

    result = execute(runtime, case, get_adapter=resolver, emit=event)
    assert result['status'] == 'failed'
    assert result['failure']['code'] == 'result_unavailable'
    assert called == ['document_search'] and case.model.calls == []


def test_partial_source_set_is_not_silently_promoted_by_analyze(runtime):
    with pytest.raises(runtime.schema.PlanValidationError):
        runtime.make([
            {'step_id': 'search', 'capability_id': 'document_search', 'arguments': {'query': 'Find sources.'}},
            {'step_id': 'analyze', 'capability_id': 'document_analyze',
             'arguments': {'analysis_prompt': 'Read every required source.'},
             'inputs': {'sources': source_input('search', 'sources', partial=True)}},
        ])


@pytest.mark.parametrize('capability_id, contract', [
    ('document_search', 'orchestration-gathered-content-v1'),
    ('document_analyze', 'analyze-final-v1'),
    ('document_compare', 'comparison-v1'),
    ('tabular_analyze', 'native-tabular-result-v1'),
    ('compose', 'compose-v1'),
])
def test_producer_contract_comes_from_server_metadata_not_the_plan_version(runtime, capability_id, contract):
    context = runtime.executor.RunContext(
        user_id='owner', conversation_id='conversation-1', run_id='run-1',
        attempt_index=3, plan_contract_version=2,
    )
    producer = context.result_producer({
        'step_id': 'producer', 'capability_id': capability_id,
        'result_contract_version': 'model-supplied-contract', 'contract_version': 2,
        'user_id': 'different-owner', 'run_id': 'different-run',
    })
    capability = runtime.registry.get_capability(capability_id)
    assert producer.contract_version == capability['result_contract_version'] == contract
    assert type(producer.contract_version) is str and context.plan_contract_version == 2
    assert (producer.user_id, producer.run_id, producer.attempt_index) == ('owner', 'run-1', 3)


@pytest.mark.parametrize('invalid_contract', [None, 2, '', ' '])
def test_producer_rejects_invalid_result_contract_metadata(runtime, monkeypatch, invalid_contract):
    context = runtime.executor.RunContext(
        user_id='owner', conversation_id='conversation-1', run_id='run-1', plan_contract_version=2,
    )
    set_result_contract(monkeypatch, runtime.registry, 'compose', invalid_contract)
    with pytest.raises(runtime.contracts.ResultContractError):
        context.result_producer(compose())


def test_producer_contract_revision_changes_only_that_producers_fingerprints(runtime, monkeypatch):
    case = runtime.make([
        compose(),
        {'step_id': 'search', 'capability_id': 'document_search', 'arguments': {'query': 'Find a source.'}},
    ])
    step, search = case.plan['steps']
    before = runtime.checkpoints.step_input_fingerprint(step, case.context, None, settings=case.settings)
    search_before = runtime.checkpoints.step_input_fingerprint(search, case.context, None, settings=case.settings)
    set_result_contract(monkeypatch, runtime.registry, 'compose', 'compose-v2')
    after = runtime.checkpoints.step_input_fingerprint(step, case.context, None, settings=case.settings)
    search_after = runtime.checkpoints.step_input_fingerprint(search, case.context, None, settings=case.settings)
    assert before != after
    assert search_before == search_after
