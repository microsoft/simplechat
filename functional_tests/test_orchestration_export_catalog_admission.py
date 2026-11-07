# test_orchestration_export_catalog_admission.py
"""Functional tests for server-admitted export format/profile subsets.

Version: 0.261.139
Implemented in: 0.261.127
Single orchestration contract updated in: 0.261.139
Real registry, compiler, planner, leases, checkpoints and rendering services are used.
Application imports are deferred until fixture setup; only provider/storage I/O is isolated.
"""

from copy import deepcopy
import importlib
import json
from types import SimpleNamespace

import pytest

from test_orchestration_dependency_runtime import binding, compose, execute, runtime, source_input
from test_orchestration_render_waiting_runtime import lifecycle, production_modules, render_runtime
from test_support.app_stubs import stubbed_config


def _catalog(*pairs):
    registry = importlib.import_module('functions_generated_export_registry')
    return [
        {
            **entry,
            'profiles': [
                profile for profile in entry['profiles'] if (entry['format_id'], profile['profile']) in pairs
            ],
        }
        for entry in registry.get_generated_file_export_catalog()
        if any(entry['format_id'] == format_id for format_id, _ in pairs)
    ]


def _raw_plan(output_format='md', profile='prepared_text_v1', *, output=None, options=None):
    arguments = {'file_name': f'Prepared.{output_format}', 'output_format': output_format, 'profile': profile}
    if options is not None:
        arguments['options'] = options
    return {
        'run_id': 'run-1', 'plan_id': 'catalog-plan', 'turn_id': 'catalog-turn',
        'steps': [
            compose(outputs=[output] if output else None),
            {
                'step_id': 'file', 'capability_id': 'render_file', 'arguments': arguments,
                'inputs': {'source': source_input('draft', 'answer')}, 'outputs': [],
            },
        ],
    }


def _normalize(runtime, raw, catalog=None):
    return runtime.schema.normalize_plan(
        raw, 'conversation-1', 'owner', settings={'chat_orchestration_max_steps': 8},
        contract_version=2, available_capability_ids=['compose', 'render_file'],
        export_catalog=catalog,
    )


def _planned(lifecycle, replies, catalog, calls):
    def create(**request):
        calls.append(deepcopy(request))
        return SimpleNamespace(
            choices=[SimpleNamespace(
                finish_reason='stop',
                message=SimpleNamespace(content=json.dumps(replies.pop(0)), refusal=None),
            )],
            usage=SimpleNamespace(prompt_tokens=20, completion_tokens=40, total_tokens=60),
        )

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    model = SimpleNamespace(deployment='offline-catalog-planner', as_planner_client=lambda: client)
    with stubbed_config(cognitive_services_scope='offline-scope'):
        planner = importlib.import_module('functions_orchestration_planner')
        return planner.plan_request(
            'Prepare an original Markdown report.', {'message': 'Prepare an original Markdown report.'},
            'conversation-1', 'owner', settings={'chat_orchestration_max_steps': 8},
            contract_version=2, planner_model=model,
            request_context={'rendering_service': lifecycle.service}, export_catalog=catalog,
        )


def test_none_empty_and_profile_subset_have_distinct_canonical_meanings(runtime):
    shared = importlib.import_module('functions_generated_export_registry').get_generated_file_export_catalog()
    default = runtime.registry.resolve_admitted_export_catalog()
    empty = runtime.registry.resolve_admitted_export_catalog([])
    selected = _catalog(('json', 'structured_value_v1'), ('md', 'prepared_text_v1'))
    original = deepcopy(selected)
    narrowed = runtime.registry.resolve_admitted_export_catalog(list(reversed(selected)))
    pairs = runtime.registry.admitted_export_pairs(narrowed)
    assert default == shared and empty == []
    assert narrowed == selected
    assert pairs == frozenset({('json', 'structured_value_v1'), ('md', 'prepared_text_v1')})
    narrowed[0]['profiles'][0]['source_kinds'].append('untrusted')
    refreshed = runtime.registry.resolve_admitted_export_catalog(selected)
    assert refreshed == selected == original


def test_explicit_format_without_profiles_admits_no_pairs(runtime):
    catalog = _catalog(('md', 'prepared_text_v1'))
    catalog[0]['profiles'] = []
    result = runtime.registry.resolve_admitted_export_catalog(catalog)
    pairs = runtime.registry.admitted_export_pairs(catalog)
    assert result == [] and pairs == frozenset()


@pytest.mark.parametrize('invalid', ['md', {}, False, ()])
def test_catalog_must_be_an_explicit_list_not_a_truthy_or_empty_fallback(runtime, invalid):
    with pytest.raises(runtime.registry.CapabilityResolutionError):
        runtime.registry.resolve_admitted_export_catalog(invalid)


@pytest.mark.parametrize('change', [
    'unknown-format', 'format-alias', 'duplicate-format', 'unknown-profile', 'duplicate-profile',
    'changed-source-kinds', 'changed-options-schema', 'changed-input-schema',
    'missing-format-metadata', 'extra-format-metadata', 'missing-profile-metadata', 'invalid-profiles',
])
def test_unknown_or_redefined_catalog_metadata_is_rejected_and_logged(runtime, monkeypatch, change):
    catalog = _catalog(('md', 'prepared_text_v1'))
    entry = catalog[0]
    profile = entry['profiles'][0]
    if change == 'unknown-format':
        entry['format_id'] = 'invented'
    elif change == 'format-alias':
        entry['format_id'] = 'markdown'
    elif change == 'duplicate-format':
        catalog.append(deepcopy(entry))
    elif change == 'unknown-profile':
        profile['profile'] = 'invented'
    elif change == 'duplicate-profile':
        entry['profiles'].append(deepcopy(profile))
    elif change == 'changed-source-kinds':
        profile['source_kinds'].append('records')
    elif change == 'changed-options-schema':
        profile['options_schema']['additionalProperties'] = True
    elif change == 'changed-input-schema':
        profile['input_schema'] = {'type': 'object'}
    elif change == 'missing-format-metadata':
        entry.pop('renderer_version')
    elif change == 'extra-format-metadata':
        entry['allow_generated_files'] = True
    elif change == 'missing-profile-metadata':
        profile.pop('requires_complete')
    else:
        entry['profiles'] = 'prepared_text_v1'
    events = []
    monkeypatch.setattr(runtime.registry, 'log_event', lambda message, **kwargs: events.append(message))
    with pytest.raises(runtime.registry.CapabilityResolutionError):
        runtime.registry.resolve_admitted_export_catalog(catalog)
    assert events == ['[ORCHESTRATION_REGISTRY] Invalid admitted export catalog.']


def test_real_service_projection_and_id_wrapper_use_the_same_subset(lifecycle):
    registry = importlib.import_module('functions_orchestration_registry')
    catalog = _catalog(('md', 'prepared_text_v1'))
    kwargs = {
        'contract_version': 2, 'candidate_ids': {'render_file'},
        'request_context': {'rendering_service': lifecycle.service}, 'export_catalog': catalog,
    }
    capabilities = registry.resolve_available_capabilities({}, **kwargs)
    identifiers = registry.resolve_available_capability_ids({}, **kwargs)
    assert identifiers == ['render_file']
    render = capabilities[0]
    assert render['inputs']['properties']['output_format']['enum'] == ['md']
    assert len(render['inputs']['oneOf']) == 1
    assert render['inputs']['oneOf'][0]['properties']['profile'] == {'const': 'prepared_text_v1'}
    assert render['result_input_kinds']['source'] == ('markdown-v1',)
    unchanged = registry.get_capability('render_file', contract_version=2)
    assert len(unchanged['inputs']['properties']['output_format']['enum']) > 1
    assert lifecycle.render_calls == [] and lifecycle.blobs.uploads == 0


@pytest.mark.parametrize('restricted', ['empty-catalog', 'missing-service', 'admin-denied'])
def test_catalog_cannot_grant_a_service_or_override_capability_permissions(lifecycle, restricted):
    registry = importlib.import_module('functions_orchestration_registry')
    unavailable = {}
    settings = {'chat_orchestration_enabled_capabilities': ['compose']} if restricted == 'admin-denied' else {}
    service = None if restricted == 'missing-service' else lifecycle.service
    catalog = [] if restricted == 'empty-catalog' else _catalog(('md', 'prepared_text_v1'))
    capabilities = registry.resolve_available_capabilities(
        settings, contract_version=2, candidate_ids={'render_file'},
        request_context={'rendering_service': service}, export_catalog=catalog, unavailable=unavailable,
    )
    assert capabilities == []
    assert unavailable == {'render_file': {
        'empty-catalog': 'export_catalog_unavailable',
        'missing-service': 'rendering_service_unavailable',
        'admin-denied': 'not_enabled_for_orchestration',
    }[restricted]}


@pytest.mark.parametrize('selection', ['default', 'selected', 'full'])
def test_compiler_preserves_required_files_named_bindings_and_final_response(runtime, selection):
    catalog = {
        'default': None,
        'selected': _catalog(('md', 'prepared_text_v1')),
        'full': runtime.registry.resolve_admitted_export_catalog(),
    }[selection]
    raw = _raw_plan()
    raw['final_response'] = binding('draft')
    original = deepcopy(raw)
    plan = _normalize(runtime, raw, catalog)
    checked = runtime.schema.validate_plan(
        plan, available_capability_ids=['compose', 'render_file'], contract_version=2, export_catalog=catalog,
    )
    assert [step['step_id'] for step in checked['steps']] == ['draft', 'file']
    assert checked['steps'][1]['depends_on'] == ['draft']
    assert checked['steps'][1]['inputs'] == original['steps'][1]['inputs']
    assert checked['steps'][1]['outputs'] == []
    assert checked['final_response'] == original['final_response']
    assert checked['validation']['repairs'] == [] and raw == original


@pytest.mark.parametrize('selection', ['empty', 'other-format', 'other-profile'])
def test_compiler_refuses_unadmitted_pairs_without_dropping_a_required_file(runtime, selection):
    raw = _raw_plan()
    if selection == 'other-profile':
        raw = _raw_plan(
            'json', 'structured_value_v1',
            output={'name': 'answer', 'kind': 'structured-v1', 'schema': {'type': 'object'}},
        )
        catalog = _catalog(('json', 'exact_records_v1'))
    else:
        catalog = [] if selection == 'empty' else _catalog(('pdf', 'prepared_report_v1'))
    original = deepcopy(raw)
    with pytest.raises(runtime.schema.PlanValidationError) as failure:
        _normalize(runtime, raw, catalog)
    assert failure.value.code == 'capability_unavailable'
    assert raw == original


def test_narrowing_does_not_replace_the_shared_source_kind_validation(runtime):
    raw = _raw_plan(output={'name': 'answer', 'kind': 'text-v1'})
    with pytest.raises(runtime.schema.PlanValidationError) as failure:
        _normalize(runtime, raw, _catalog(('md', 'prepared_text_v1')))
    assert failure.value.code == 'result_kind_incompatible'


def test_model_supplied_catalog_cannot_reopen_a_server_denied_representation(runtime):
    raw = _raw_plan()
    raw['export_catalog'] = _catalog(('md', 'prepared_text_v1'))
    with pytest.raises(runtime.schema.PlanValidationError) as failure:
        _normalize(runtime, raw, [])
    assert failure.value.code == 'capability_unavailable'


@pytest.mark.parametrize('options', [None, {}, {'columns': ['id']}, {'columns': ['id'], 'sheet_name': ''}])
def test_selected_workbook_profile_still_requires_its_real_options(runtime, options):
    output = {
        'name': 'answer', 'kind': 'records-v1',
        'columns': [{'name': 'id', 'value_type': 'string', 'nullable': False}],
    }
    raw = _raw_plan('xlsx', 'tabular_workbook_v1', output=output, options=options)
    with pytest.raises(runtime.schema.PlanValidationError):
        _normalize(runtime, raw, _catalog(('xlsx', 'tabular_workbook_v1')))


def test_selected_workbook_profile_preserves_explicit_options(runtime):
    output = {
        'name': 'answer', 'kind': 'records-v1',
        'columns': [{'name': 'id', 'value_type': 'string', 'nullable': False}],
    }
    options = {'columns': ['id'], 'sheet_name': 'Prepared data'}
    raw = _raw_plan('xlsx', 'tabular_workbook_v1', output=output, options=options)
    plan = _normalize(runtime, raw, _catalog(('xlsx', 'tabular_workbook_v1')))
    assert plan['steps'][1]['arguments']['options'] == options
    assert plan['steps'][0]['outputs'] == [output]


def test_editor_checks_current_catalog_atomically_without_changing_bindings(runtime):
    raw = _raw_plan()
    raw['steps'].insert(1, compose('optional-note'))
    raw['final_response'] = binding('draft')
    plan = _normalize(runtime, raw)
    original = deepcopy(plan)
    edits = {'disabled_step_ids': ['optional-note']}
    with pytest.raises(runtime.schema.PlanValidationError):
        runtime.schema.apply_plan_edits(
            plan, edits, contract_version=2, export_catalog=[], composition_profiles={},
        )
    assert plan == original
    edited = runtime.schema.apply_plan_edits(
        plan, edits, contract_version=2, export_catalog=_catalog(('md', 'prepared_text_v1')),
        composition_profiles={},
    )
    assert edited is plan and edited['steps'][1]['enabled'] is False
    assert edited['steps'][2]['inputs'] == original['steps'][2]['inputs']
    assert edited['steps'][0]['outputs'] == original['steps'][0]['outputs']
    assert edited['final_response'] == original['final_response']


def test_editor_revalidates_explicitly_supplied_composition_profiles(runtime):
    profile = {'type': 'object', 'properties': {'title': {'type': 'string'}}, 'required': ['title']}
    case = runtime.make(
        [compose(outputs=[{'name': 'answer', 'kind': 'structured-v1', 'profile': 'server_profile_v1'}])],
        profiles={'server_profile_v1': profile},
    )
    original = deepcopy(case.plan)
    accepted = runtime.schema.apply_plan_edits(
        case.plan, {}, contract_version=2, export_catalog=[],
        composition_profiles={'server_profile_v1': profile},
    )
    assert accepted == original
    with pytest.raises(runtime.schema.PlanValidationError):
        runtime.schema.apply_plan_edits(case.plan, {}, composition_profiles={})
    assert case.plan == original


@pytest.mark.parametrize('operation', ['validate_plan', 'apply_plan_edits'])
@pytest.mark.parametrize('version', [1, True, '2', 3])
def test_saved_contract_cannot_be_reinterpreted_by_an_editor_keyword(runtime, operation, version):
    plan = _normalize(runtime, _raw_plan())
    original = deepcopy(plan)
    arguments = (plan, {}) if operation == 'apply_plan_edits' else (plan,)
    with pytest.raises(runtime.schema.PlanValidationError):
        getattr(runtime.schema, operation)(*arguments, contract_version=version, export_catalog=[])
    assert plan == original


@pytest.mark.parametrize('repair', [False, True])
def test_planner_prompt_and_elicitation_repair_keep_the_same_admitted_pairs(lifecycle, repair):
    reply = {'kind': 'plan', **_raw_plan()}
    replies = ([{'kind': 'elicitation', 'questions': []}] if repair else []) + [reply]
    calls = []
    kind, plan = _planned(lifecycle, replies, _catalog(('md', 'prepared_text_v1')), calls)
    assert kind == 'plan' and plan['steps'][1]['capability_id'] == 'render_file'
    assert len(calls) == (2 if repair else 1)
    for call in calls:
        context = json.loads(call['messages'][1]['content'])
        render = next(capability for capability in context['capabilities'] if capability['id'] == 'render_file')
        assert render['inputs']['properties']['output_format']['enum'] == ['md']
        assert len(render['inputs']['oneOf']) == 1
    assert lifecycle.render_calls == [] and lifecycle.blobs.uploads == 0


def test_planner_rejects_a_model_file_request_outside_its_actual_catalog(lifecycle):
    calls = []
    planner = importlib.import_module('functions_orchestration_planner')
    with pytest.raises(planner.PlannerError) as failure:
        _planned(lifecycle, [{'kind': 'plan', **_raw_plan()}], [], calls)
    assert failure.value.reason == 'invalid_plan_or_missing_requirement'
    assert len(calls) == 1
    context = json.loads(calls[0]['messages'][1]['content'])
    assert all(capability['id'] != 'render_file' for capability in context['capabilities'])
    assert lifecycle.render_calls == [] and lifecycle.blobs.uploads == 0


def test_invalid_server_catalog_fails_before_a_planner_model_call(lifecycle):
    calls = []
    catalog = _catalog(('md', 'prepared_text_v1'))
    catalog[0]['profiles'][0]['source_kinds'].append('records')
    registry = importlib.import_module('functions_orchestration_registry')
    with pytest.raises(registry.CapabilityResolutionError):
        _planned(lifecycle, [{'kind': 'plan', **_raw_plan()}], catalog, calls)
    assert calls == [] and lifecycle.render_calls == [] and lifecycle.blobs.uploads == 0


def test_admitted_catalog_reaches_real_execution_but_not_checkpoint_state(render_runtime):
    case = render_runtime
    result = case.execute(case.initial, export_catalog=_catalog(('md', 'prepared_text_v1')))
    assert result['status'] == 'completed', result
    assert len(case.calls) == 1 and case.lifecycle.render_calls == [('md', 'prepared_text_v1')]
    assert len(result['artifacts']) == 1 and case.lifecycle.blobs.uploads == 1
    checkpoints = importlib.import_module('functions_orchestration_checkpoints')
    state = checkpoints.context_state(case.state['context'])
    assert 'export_catalog' not in state


@pytest.mark.parametrize('selection', ['empty', 'other-format'])
def test_executor_refuses_current_exclusions_before_any_content_or_render_call(render_runtime, selection):
    case = render_runtime
    catalog = [] if selection == 'empty' else _catalog(('pdf', 'prepared_report_v1'))
    schema = importlib.import_module('functions_orchestration_schema')
    with pytest.raises(schema.PlanValidationError):
        case.execute(case.initial, export_catalog=catalog)
    assert case.calls == [] and case.lifecycle.render_calls == [] and case.lifecycle.blobs.uploads == 0


def test_waiting_restore_and_saved_render_read_recheck_catalog_without_replay(render_runtime):
    case = render_runtime
    case.lifecycle.failures['md'] = [TimeoutError('Isolated renderer transport failure.')]
    waiting = case.execute(case.initial)
    assert waiting['status'] == 'waiting'
    context = case.state['context']
    context.export_catalog = _catalog(('pdf', 'prepared_report_v1'))
    current = case.current()
    with pytest.raises(case.recovery.CheckpointError) as failure:
        case.recovery.validate_resume(current, context, case.settings, lambda: True, allow_waiting=True)
    assert failure.value.code == 'context_unavailable'
    executor = importlib.import_module('functions_orchestration_executor')
    with pytest.raises(executor.ResultContractError) as failure:
        executor._render_dependency_step(
            case.plan['steps'][1], context, settings=case.settings, user_id='owner',
            saved_result={'wait': waiting['pending_results']['file']},
        )
    assert failure.value.code == 'result_adapter_unavailable'
    claimed = case.claim('catalog-revoked')
    with pytest.raises(importlib.import_module('functions_orchestration_schema').PlanValidationError):
        case.execute(claimed, export_catalog=[])
    assert len(case.calls) == 1 and case.lifecycle.render_calls == [('md', 'prepared_text_v1')]
    assert case.lifecycle.blobs.uploads == 0
    saved = case.current()
    assert saved['attempt_index'] == current['attempt_index']
    assert saved['task_results'] == waiting['task_results']
    assert saved['pending_results'] == waiting['pending_results']


def test_answer_only_execution_is_not_blocked_by_an_explicitly_empty_file_catalog(runtime):
    case = runtime.make([compose()], ['An original answer.'], final_response=binding('draft'))
    case.context.export_catalog = []
    result = execute(runtime, case)
    assert result['status'] == 'completed' and result['message'] == 'An original answer.'
    assert len(case.model.calls) == 1 and result['artifacts'] == result['outputs'] == []
