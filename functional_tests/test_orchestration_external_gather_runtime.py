# test_orchestration_external_gather_runtime.py
"""External Gather content retains real authorization lineage through composition.

Version: 0.261.139
Implemented in: 0.261.127
Empty-result lineage coverage added in: 0.261.129
Authorization/capture gating and fingerprint coverage extended in: 0.261.130
Single orchestration contract updated in: 0.261.139
Provider identity, configuration and storage I/O are isolated; runtime and facade are real.
"""

from copy import deepcopy
from dataclasses import replace

import pytest

from test_orchestration_dependency_runtime import binding, compose, runtime, source_input
from test_orchestration_external_sources import ExternalSourceWorld


def test_external_discovery_requires_all_server_callbacks_not_boolean_flags(runtime):
    settings = {'enable_web_search': True}
    names = (
        'external_source_admission', 'external_source_preflight',
        'capture_external_source_configuration', 'external_source_authorizer',
    )
    callbacks = {name: lambda **kwargs: None for name in names}
    for missing in names:
        request = {**callbacks, missing: True}
        available = runtime.registry.resolve_available_capability_ids(
            settings, request_context=request, contract_version=2,
        )
        assert 'web_search' not in available
    available = runtime.registry.resolve_available_capability_ids(
        settings, request_context=callbacks, contract_version=2,
    )
    assert 'web_search' in available
    descriptor = runtime.registry.get_capability('web_search', contract_version=2)
    assert descriptor['runtime_bindings'] == names


@pytest.mark.parametrize('capability_id', [
    'web_search', 'url_fetch', 'deep_research', 'agent_invoke', 'action_invoke',
])
@pytest.mark.parametrize('name', ['external_source_preflight', 'capture_external_source_configuration'])
@pytest.mark.parametrize('callback', [None, True, False, {}, 'browser-provided-hook'])
def test_every_external_capability_requires_callable_acquisition_guards(runtime, capability_id, name, callback):
    context = {
        'external_source_admission': lambda **kwargs: None,
        'external_source_preflight': lambda **kwargs: None,
        'capture_external_source_configuration': lambda *args, **kwargs: None,
        'external_source_authorizer': lambda **kwargs: None,
        name: callback,
    }
    unavailable = {}
    available = runtime.registry.resolve_available_capabilities(
        {}, request_context=context, candidate_ids=[capability_id],
        contract_version=2, unavailable=unavailable,
    )
    assert available == []
    assert unavailable == {capability_id: 'external_result_lineage_unavailable'}


@pytest.mark.parametrize('name', ['external_source_preflight', 'capture_external_source_configuration'])
@pytest.mark.parametrize('callback', [True, False, {}, 'browser-provided-hook'])
def test_context_rejects_noncallable_external_acquisition_guards(runtime, name, callback):
    with pytest.raises(runtime.contracts.ResultContractError) as caught:
        runtime.executor.RunContext(
            run_id='run-1', plan_id='plan-1', conversation_id='conversation-1', user_id='owner',
            user_message='', plan_contract_version=2, **{name: callback},
        )
    assert caught.value.code == 'result_external_reader_required'


@pytest.mark.parametrize('name', ['external_source_preflight', 'capture_external_source_configuration'])
def test_external_acquisition_guards_are_ephemeral_and_preserve_checkpoint_fingerprints(runtime, name):
    context = runtime.executor.RunContext(
        run_id='run-1', plan_id='plan-1', conversation_id='conversation-1', user_id='owner',
        user_message='', plan_contract_version=2,
    )
    plan = runtime.schema.normalize_plan(
        {'steps': [compose()]}, 'conversation-1', 'owner', settings={}, contract_version=2,
        available_capability_ids=['compose'],
    )
    state_before = runtime.checkpoints.context_state(context)
    binding_before = runtime.checkpoints.context_binding(context, plan, {})
    fingerprint_before = runtime.checkpoints.step_input_fingerprint(
        plan['steps'][0], context, binding_before, settings={},
    )
    assert getattr(context, name) is None
    callback = lambda *args, **kwargs: None
    setattr(context, name, callback)
    request = runtime.executor._dependency_request_context(context)
    state_after = runtime.checkpoints.context_state(context)
    binding_after = runtime.checkpoints.context_binding(context, plan, {})
    fingerprint_after = runtime.checkpoints.step_input_fingerprint(
        plan['steps'][0], context, binding_after, settings={},
    )
    assert request[name] is callback
    assert state_after == state_before and name not in state_after
    assert binding_after == binding_before and fingerprint_after == fingerprint_before


def test_external_runtime_bindings_do_not_change_saved_step_fingerprints(runtime, monkeypatch):
    case = runtime.make([compose()])
    settings = {**case.settings, 'enable_web_search': True}
    plan = runtime.schema.normalize_plan({
        'steps': [{'step_id': 'gather', 'capability_id': 'web_search', 'arguments': {'query': 'approved query'}}],
    }, 'conversation-1', 'owner', settings=settings, contract_version=2,
        available_capability_ids=['web_search'])
    context_binding = runtime.checkpoints.context_binding(case.context, plan, settings)
    current_fingerprint = runtime.checkpoints.step_input_fingerprint(
        plan['steps'][0], case.context, context_binding, settings=settings,
    )
    previous_descriptor = runtime.registry.get_capability('web_search', contract_version=2)
    previous_descriptor['runtime_bindings'] = (
        'external_source_admission', 'capture_external_source_configuration', 'external_source_authorizer',
    )
    monkeypatch.setattr(
        runtime.checkpoints, 'get_capability',
        lambda capability_id, *, contract_version: deepcopy(previous_descriptor),
    )
    previous_fingerprint = runtime.checkpoints.step_input_fingerprint(
        plan['steps'][0], case.context, context_binding, settings=settings,
    )
    assert previous_fingerprint == current_fingerprint


@pytest.mark.parametrize('missing', ['external_source_preflight', 'capture_external_source_configuration'])
def test_missing_external_acquisition_guard_blocks_execution_before_any_adapter(runtime, missing):
    case = runtime.make([compose()])
    settings = {**case.settings, 'enable_web_search': True}
    plan = runtime.schema.normalize_plan({
        'run_id': 'run-1', 'plan_id': 'plan-1', 'turn_id': 'turn-1',
        'steps': [{'step_id': 'gather', 'capability_id': 'web_search', 'arguments': {'query': 'approved query'}}],
    }, 'conversation-1', 'owner', settings=settings, contract_version=2,
        available_capability_ids=['web_search'])
    case.context.external_source_admission = lambda **kwargs: None
    case.context.external_source_preflight = lambda **kwargs: None
    case.context.capture_external_source_configuration = lambda *args, **kwargs: None
    setattr(case.context, missing, None)
    case.context.result_service.access.external_source_authorizer = lambda *args, **kwargs: None
    resolved = []

    def forbidden_adapter(capability_id):
        resolved.append(capability_id)
        raise AssertionError('Missing acquisition guards must prevent selecting an acquisition adapter.')

    with pytest.raises(runtime.schema.PlanValidationError) as caught:
        runtime.executor.execute_plan(
            plan, case.context, settings=settings, user_id='owner', get_adapter=forbidden_adapter,
        )
    assert caught.value.code == 'capability_unavailable'
    assert resolved == [] and case.model.calls == [] and case.context.task_results == {}


@pytest.mark.parametrize('partial', [False, True])
@pytest.mark.parametrize('empty', [False, True])
def test_external_gather_retains_full_content_and_composed_lineage_after_restart(runtime, partial, empty):
    with ExternalSourceWorld() as world:
        case = runtime.make([compose('draft')], ['Prepared from the exact retained external content.'])
        case.model.model_metadata = replace(case.model.model_metadata, context_window=131072, input_limit=98304)
        settings = {**case.settings, **world.settings}
        plan = runtime.schema.normalize_plan({
            'run_id': 'run-1', 'plan_id': 'plan-1', 'turn_id': 'turn-1',
            'steps': [
                {'step_id': 'gather', 'capability_id': 'web_search', 'arguments': {'query': 'approved query'}},
                compose('draft', inputs={'source': source_input('gather', partial=partial)}),
            ],
            'final_response': binding('draft'),
        }, 'conversation-1', 'owner', settings=settings, contract_version=2,
            available_capability_ids=['web_search', 'compose'])
        world.fixture.runs['run-1'] = deepcopy(case.fixture.runs['run-1'])
        world.fixture.runs['run-1']['plan'] = deepcopy(plan)
        provider = world.provider()
        context = case.context
        context.result_service = world.service(provider)
        context.external_source_admission = provider.admit_gather_result
        context.external_source_preflight = provider.preflight_gather_invocation
        context.capture_external_source_configuration = world.admit_configuration
        context.user_roles = list(world.roles)
        context.user_enable_agents = True
        body = 'Full retained integration content. ' * 1000 + 'AUTHORITATIVE-FINAL-LINE'
        notes = [] if empty else [body]
        citations = [] if empty else [
            {'document_id': 'https://public.example/page', 'url': 'https://public.example/page'},
        ]
        captured = []

        def gather(step, scoped, *, settings, **kwargs):
            scoped.external_source_preflight(producer=scoped.result_producer(step), selector=None)
            scoped.capture_external_source_configuration(
                'web', producer=scoped.result_producer(step), settings=settings, source=None,
            )
            result = runtime.schema.build_step_result(
                status='partial' if partial else 'completed', notes=notes, citations=citations,
            )
            captured.append(deepcopy(result))
            return result

        result = runtime.executor.execute_plan(
            plan, context, settings=settings, user_id='owner',
            get_adapter=lambda capability: gather if capability == 'web_search' else runtime.composition.adapter_compose,
        )
        assert result['steps'][-1]['status'] in ('completed', 'partial'), result['steps'][-1].get('failure')
        assert len(captured) == len(case.model.calls) == 1, result
        gathered = context.task_results['gather']
        answer = context.task_results['draft']
        assert gathered.status == answer.status == ('partial' if partial else 'complete')
        restarted = world.service(world.provider())
        prepared_reader = restarted.open_result(gathered.output('prepared'), allow_partial=partial)
        prepared = prepared_reader.read_value()
        assert prepared['notes'] == notes
        assert prepared['citations'] == captured[0]['citations']
        assert prepared['content_scope'] == 'reported_external_content'
        assert prepared_reader.metadata()['origin'] == 'grounded'
        answer_reader = restarted.open_result(answer.output('answer'), allow_partial=partial)
        text = answer_reader.read_text()
        metadata = answer_reader.metadata()
        assert text == 'Prepared from the exact retained external content.'
        assert metadata['origin'] == 'grounded'
        assert metadata['external_source_count'] == 1
        if empty:
            assert prepared['notes'] == prepared['citations'] == prepared['evidence'] == []
        else:
            assert body in case.model.calls[0][0][-1]['content']
        assert context.documents_touched == [] and result['artifacts'] == []
        assert result['citations'] == []
        world.roles = ()
        with pytest.raises(PermissionError):
            restarted.open_result(answer.output('answer'), allow_partial=partial)
