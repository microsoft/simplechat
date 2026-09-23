# test_orchestration_external_gather_runtime.py
"""External Gather content retains real authorization lineage through composition.

Version: 0.261.129
Implemented in: 0.261.127
Empty-result lineage coverage added in: 0.261.129
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


@pytest.mark.parametrize('capability_id', [
    'web_search', 'url_fetch', 'deep_research', 'agent_invoke', 'action_invoke',
])
@pytest.mark.parametrize('preflight', [None, True, False, {}, 'browser-provided-hook'])
def test_every_external_capability_requires_callable_preflight(runtime, capability_id, preflight):
    context = {
        'external_source_admission': lambda **kwargs: None,
        'capture_external_source_configuration': lambda **kwargs: None,
        'external_source_authorizer': lambda **kwargs: None,
        'external_source_preflight': preflight,
    }
    unavailable = {}
    available = runtime.registry.resolve_available_capabilities(
        {}, request_context=context, candidate_ids=[capability_id],
        contract_version=2, unavailable=unavailable,
    )
    legacy = runtime.registry.get_capability(capability_id)
    assert available == []
    assert unavailable == {capability_id: 'external_result_lineage_unavailable'}
    assert 'runtime_bindings' not in legacy and 'runtime_binding' not in legacy


@pytest.mark.parametrize('preflight', [True, False, {}, 'browser-provided-hook'])
def test_context_rejects_noncallable_external_preflight(runtime, preflight):
    with pytest.raises(runtime.contracts.ResultContractError) as caught:
        runtime.executor.RunContext(
            run_id='run-1', plan_id='plan-1', conversation_id='conversation-1', user_id='owner',
            user_message='', plan_contract_version=2, external_source_preflight=preflight,
        )
    assert caught.value.code == 'result_external_reader_required'


@pytest.mark.parametrize('version', [1, 2])
def test_external_preflight_is_ephemeral_and_preserves_checkpoint_fingerprints(runtime, version):
    context = runtime.executor.RunContext(
        run_id='run-1', plan_id='plan-1', conversation_id='conversation-1', user_id='owner',
        user_message='', plan_contract_version=version,
    )
    steps = [compose()] if version == 2 else [
        {'step_id': 'answer', 'capability_id': 'respond', 'arguments': {}},
    ]
    plan = runtime.schema.normalize_plan(
        {'steps': steps}, 'conversation-1', 'owner', settings={}, contract_version=version,
        available_capability_ids=['compose'] if version == 2 else ['respond'],
    )
    state_before = runtime.checkpoints.context_state(context)
    binding_before = runtime.checkpoints.context_binding(context, plan, {})
    fingerprint_before = runtime.checkpoints.step_input_fingerprint(
        plan['steps'][0], context, binding_before, settings={},
    )
    assert context.external_source_preflight is None
    context.external_source_preflight = lambda **kwargs: None
    request = runtime.executor._dependency_request_context(context)
    state_after = runtime.checkpoints.context_state(context)
    binding_after = runtime.checkpoints.context_binding(context, plan, {})
    fingerprint_after = runtime.checkpoints.step_input_fingerprint(
        plan['steps'][0], context, binding_after, settings={},
    )
    assert request['external_source_preflight'] is context.external_source_preflight
    assert state_after == state_before and 'external_source_preflight' not in state_after
    assert binding_after == binding_before and fingerprint_after == fingerprint_before


def test_missing_external_preflight_blocks_execution_before_any_adapter(runtime):
    case = runtime.make([compose()])
    settings = {**case.settings, 'enable_web_search': True}
    plan = runtime.schema.normalize_plan({
        'run_id': 'run-1', 'plan_id': 'plan-1', 'turn_id': 'turn-1',
        'steps': [{'step_id': 'gather', 'capability_id': 'web_search', 'arguments': {'query': 'approved query'}}],
    }, 'conversation-1', 'owner', settings=settings, contract_version=2,
        available_capability_ids=['web_search'])
    case.context.external_source_admission = lambda **kwargs: None
    case.context.capture_external_source_configuration = lambda **kwargs: None
    case.context.result_service.access.external_source_authorizer = lambda *args, **kwargs: None
    resolved = []

    def forbidden_adapter(capability_id):
        resolved.append(capability_id)
        raise AssertionError('Missing preflight must prevent selecting an acquisition adapter.')

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
