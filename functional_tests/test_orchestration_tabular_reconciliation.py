#!/usr/bin/env python3
# test_orchestration_tabular_reconciliation.py
"""
Functional test for reconciling differently structured spreadsheets in chat orchestration.
Version: 0.261.219
Implemented in: 0.261.219

This test ensures that tabular_inspect is a gated Gather capability that retains a bounded
inspection without a model, that tabular_merge plans accept union, aliases, exclusion,
de-duplication, sorting and a bound column mapping only in valid combinations, that a
mapping must come from a compose step using the tabular_column_mapping_v1 profile, that the
real executor runs inspect -> compose mapping -> merge end to end with the mapping
re-validated at merge time, that union merges retain nullable columns that render as blank
cells, and that the planner is offered the reconciliation recipe.
"""

import csv
import io
import json
import sys

import pytest

from test_orchestration_dependency_runtime import binding, execute, runtime  # noqa: F401
from test_support.versioning import assert_app_version_at_least


PROFILE = 'tabular_column_mapping_v1'
AVAILABLE = ['tabular_inspect', 'tabular_merge', 'document_search', 'compose', 'render_file']
FILES = {
    'crm-doc': ('crm.csv', b'Customer ID,Name,Amount\r\n001,Ann,10\r\n002,Bob,5\r\n'),
    'erp-doc': ('erp.csv', b'cust_id,Full Name,Total,Notes\n003,Cy,7,vip\n'),
    'web-doc': ('web.csv', b'Name,Channel\nDee,Online\n'),
    'notes-doc': ('notes.docx', b'not a spreadsheet'),
}
MAPPING = {
    'columns': ['Customer ID', 'Name', 'Amount'],
    'mappings': [
        {'source_column': 'cust_id', 'target_column': 'Customer ID', 'confidence': 'high'},
        {'source_column': 'Full Name', 'target_column': 'Name', 'confidence': 'medium'},
        {'source_column': 'Total', 'target_column': 'Amount', 'confidence': 'low'},
        {'source_column': 'Notes', 'target_column': None, 'confidence': 'high'},
    ],
    'notes': 'Lined up the customer columns.',
}


def step(step_id, capability_id, document_ids=None, **arguments):
    value = {'step_id': step_id, 'capability_id': capability_id, 'arguments': dict(arguments)}
    if document_ids is not None:
        value['arguments']['document_ids'] = list(document_ids)
    return value


def mapping_compose(inputs=None, outputs=None):
    return {
        'step_id': 'map', 'capability_id': 'compose',
        'arguments': {'instruction': 'Line up the columns of these files for one merged table.'},
        'inputs': inputs if inputs is not None else {
            'inspection': {'binding': binding('inspect', 'inspection'), 'allow_partial': False},
        },
        'outputs': outputs or [{'name': 'mapping', 'kind': 'structured-v1', 'profile': PROFILE}],
    }


def mapped_merge(document_ids=('crm-doc', 'erp-doc'), **arguments):
    value = step('merge', 'tabular_merge', document_ids, **arguments)
    value['inputs'] = {'mapping': {'binding': binding('map', 'mapping'), 'allow_partial': False}}
    return value


def profiles():
    from functions_orchestration_services import composition_profiles, validate_composition_profile

    return composition_profiles(), validate_composition_profile


def tabular_case(runtime, steps, replies=(), *, settings=None, available=AVAILABLE):
    profile_map, validator = profiles()
    case = runtime.make(
        steps, replies, settings=settings, available=available, profiles=profile_map,
        profile_validator=validator,
    )
    for document_id, (file_name, _) in FILES.items():
        case.fixture.sources[document_id] = {
            'document_id': document_id, 'scope': 'personal', 'scope_id': 'owner',
            'source_version': 1, 'source_revision': f'{document_id}-revision',
            'file_name': file_name,
            'source_kind': 'tabular' if file_name.endswith('.csv') else 'narrative',
        }
    reads = []

    def reader(source, user_id, group_id=None, public_workspace_id=None, *, purpose):
        assert user_id == 'owner' and purpose == 'native'
        reads.append(source['document_id'])
        return {'id': source['document_id']}, FILES[source['document_id']][1]

    case.context.merge_source_reader = reader
    case.reads = reads
    return case


def make_plan(runtime, steps, **kwargs):
    profile_map, _ = profiles()
    return runtime.make(steps, available=kwargs.pop('available', AVAILABLE), profiles=profile_map, **kwargs).plan


def test_version_includes_reconciliation():
    assert_app_version_at_least('0.261.219')


def test_tabular_inspect_is_a_gated_gather_capability(runtime):
    registry = runtime.registry
    capability = registry.get_capability('tabular_inspect')
    assert capability['role'] == registry.ROLE_GATHER
    assert capability['label'] == 'Inspect spreadsheets'
    assert capability['result_outputs'] == {'inspection': 'structured-v1'}
    assert capability['result_input_kinds'] == {'sources': ('source-set-v1',)}
    assert capability['document_action_type'] == 'merge'
    assert capability['inputs']['properties']['document_ids']['minItems'] == 1
    assert 'tabular_inspect' not in runtime.contracts.REASON_CAPABILITIES

    settings = {'enable_chat_orchestration': True, 'enable_user_workspace': True}
    available = {item['id'] for item in registry.resolve_available_capabilities(settings)}
    assert {'tabular_inspect', 'tabular_merge'} <= available
    disabled = {**settings, 'document_action_capabilities': {'merge': {'enabled': False}}}
    available = {item['id'] for item in registry.resolve_available_capabilities(disabled)}
    assert not {'tabular_inspect', 'tabular_merge'} & available

    from admin_settings_fields import ADMIN_SETTINGS_FIELDS

    options = [
        option['value'] for fields in ADMIN_SETTINGS_FIELDS.values() for field in fields
        if field.get('key') == 'chat_orchestration_enabled_capabilities' for option in field['options']
    ]
    assert options.index('tabular_inspect') < options.index('tabular_merge')


def test_inspect_plans_name_sources_or_bind_a_source_set(runtime):
    schema = runtime.schema
    plan = make_plan(runtime, [step('inspect', 'tabular_inspect', ['crm-doc'])])
    assert plan['steps'][0]['arguments'] == {'document_ids': ['crm-doc'], 'doc_scope': 'all'}
    with pytest.raises(schema.PlanValidationError) as missing:
        make_plan(runtime, [step('inspect', 'tabular_inspect')])
    assert missing.value.code == 'source_binding_required'
    with pytest.raises(schema.PlanValidationError):
        make_plan(runtime, [step('inspect', 'tabular_inspect', ['crm-doc'], sheet='Data', sheets='all')])
    with pytest.raises(schema.PlanValidationError):
        make_plan(runtime, [step('inspect', 'tabular_inspect', ['crm-doc'], sample_rows=11)])

    plan = make_plan(runtime, [step('inspect', 'tabular_inspect', ['crm-doc', 'notes-doc'])])
    with pytest.raises(schema.PlanValidationError) as kinds:
        schema.validate_plan_document_source_kinds(plan, {'crm-doc': 'tabular', 'notes-doc': 'narrative'})
    assert kinds.value.code == 'source_kind_invalid'


@pytest.mark.parametrize('arguments', [
    {'schema_policy': 'union', 'on_incompatible': 'exclude'},
    {'column_aliases': {'Customer ID': ['cust_id']}, 'header_row': 2},
    {'schema_policy': 'mapped', 'columns': ['Customer ID', 'Amount']},
    {'sheets': 'all', 'dedupe': 'key_columns', 'dedupe_columns': ['Customer ID'], 'dedupe_keep': 'last'},
    {'dedupe': 'exact_rows', 'sort_by': [{'column': 'Amount', 'descending': True, 'value_type': 'number'}]},
])
def test_reconciliation_arguments_validate(runtime, arguments):
    plan = make_plan(runtime, [step('merge', 'tabular_merge', ['crm-doc', 'erp-doc'], **arguments)])
    for key, value in arguments.items():
        assert plan['steps'][0]['arguments'][key] == value


@pytest.mark.parametrize('arguments', [
    {'columns': ['Customer ID']},
    {'schema_policy': 'mapped'},
    {'sheet': 'Data', 'sheets': 'all'},
    {'dedupe_columns': ['Customer ID']},
    {'dedupe': 'key_columns'},
    {'column_aliases': {'Customer ID': ['Amount'], 'Amount': ['Total']}},
    {'sort_by': [{'column': 'A'}, {'column': 'a'}]},
])
def test_conflicting_merge_settings_are_refused_at_planning(runtime, arguments):
    with pytest.raises(runtime.schema.PlanValidationError) as refused:
        make_plan(runtime, [step('merge', 'tabular_merge', ['crm-doc', 'erp-doc'], **arguments)])
    assert refused.value.code in ('merge_options_invalid', 'plan_invalid')


def test_a_bound_mapping_must_be_a_prepared_column_mapping(runtime):
    schema = runtime.schema
    inspect = step('inspect', 'tabular_inspect', ['crm-doc', 'erp-doc'])
    plan = make_plan(runtime, [inspect, mapping_compose(), mapped_merge()])
    merge = next(item for item in plan['steps'] if item['step_id'] == 'merge')
    assert merge['depends_on'] == ['map']

    with pytest.raises(schema.PlanValidationError) as unprofiled:
        make_plan(runtime, [inspect, mapping_compose(outputs=[{'name': 'mapping', 'kind': 'structured-v1'}]), mapped_merge()])
    assert unprofiled.value.code == 'mapping_profile_required'
    for arguments in ({'columns': ['Customer ID']}, {'column_aliases': {'Name': ['Full Name']}}, {'schema_policy': 'union'}):
        with pytest.raises(schema.PlanValidationError) as conflict:
            make_plan(runtime, [inspect, mapping_compose(), mapped_merge(**arguments)])
        assert conflict.value.code == 'merge_options_invalid'
    make_plan(runtime, [inspect, mapping_compose(), mapped_merge(schema_policy='mapped', dedupe='exact_rows')])


def test_inspection_is_retained_without_a_model(runtime):
    case = tabular_case(runtime, [step('inspect', 'tabular_inspect', ['crm-doc', 'erp-doc'], sample_rows=1)])
    result = execute(runtime, case)
    assert result['status'] == 'completed', result
    assert case.model.calls == []
    assert case.reads == ['crm-doc', 'erp-doc']
    task = runtime.contracts.TaskResult.from_dict(result['task_results']['inspect'])
    assert task.status == 'complete'
    reference = task.output('inspection')
    assert reference.completeness.coverage.unit == 'sources'
    inspection = case.fixture.restart().open_result(reference).read_value()
    assert inspection['version'] == 'tabular-inspection-v1'
    assert [entry['file_name'] for entry in inspection['sources']] == ['crm.csv', 'erp.csv']
    assert inspection['sources'][1]['tables'][0]['columns'] == ['cust_id', 'Full Name', 'Total', 'Notes']
    assert inspection['compatibility']['identical_columns'] is False
    assert inspection['compatibility']['suggested_policy'] == 'union'


def test_inspect_compose_mapping_merge_runs_end_to_end(runtime):
    steps = [step('inspect', 'tabular_inspect', ['crm-doc', 'erp-doc']), mapping_compose(), mapped_merge()]
    case = tabular_case(runtime, steps, [json.dumps({'mapping': MAPPING})])
    result = execute(runtime, case)
    assert result['status'] == 'completed', result
    assert len(case.model.calls) == 1
    payload = json.loads(case.model.calls[0][0][-1]['content'])
    assert payload['profiles'][PROFILE]['required'] == ['columns', 'mappings']
    assert payload['inputs']['inspection']['value']['version'] == 'tabular-inspection-v1'

    task = runtime.contracts.TaskResult.from_dict(result['task_results']['merge'])
    service = case.fixture.restart()
    rows = list(service.open_result(task.output('records')).iter_records())
    assert rows == [
        {'Source File': 'crm.csv', 'Customer ID': '001', 'Name': 'Ann', 'Amount': '10'},
        {'Source File': 'crm.csv', 'Customer ID': '002', 'Name': 'Bob', 'Amount': '5'},
        {'Source File': 'erp.csv', 'Customer ID': '003', 'Name': 'Cy', 'Amount': '7'},
    ]
    report = service.open_result(task.output('report')).read_value()
    assert report['policy']['schema_policy'] == 'mapped'
    assert report['policy']['column_aliases'] == {
        'Customer ID': ['cust_id'], 'Name': ['Full Name'], 'Amount': ['Total'],
    }
    assert report['mapping'] == {
        'profile': PROFILE, 'explicitly_ignored': ['Notes'],
        'low_confidence': [{'source_column': 'Total', 'target_column': 'Amount'}],
        'notes': 'Lined up the customer columns.',
    }
    assert report['sources'][1]['ignored_columns'] == ['Notes']


def test_an_invalid_prepared_mapping_is_asked_for_once_more_then_fails(runtime):
    invalid = {**MAPPING, 'mappings': [{'source_column': 'Total', 'target_column': 'Revenue', 'confidence': 'high'}]}
    steps = [step('inspect', 'tabular_inspect', ['crm-doc', 'erp-doc']), mapping_compose(), mapped_merge()]
    case = tabular_case(runtime, steps, [json.dumps({'mapping': invalid}), json.dumps({'mapping': invalid})])
    result = execute(runtime, case)
    assert result['status'] == 'failed'
    assert len(case.model.calls) == 2
    assert 'merge' not in result['task_results']
    assert case.reads == ['crm-doc', 'erp-doc']


def test_union_merge_retains_nullable_columns_that_render_blank(runtime):
    from functions_generated_file_exports import GeneratedFileExportRequest, build_generated_file_export
    from functions_orchestration_export_sources import open_orchestration_export_source

    case = tabular_case(runtime, [step(
        'merge', 'tabular_merge', ['crm-doc', 'web-doc'], schema_policy='union',
        sort_by=[{'column': 'Name', 'descending': True}],
    )])
    result = execute(runtime, case)
    assert result['status'] == 'completed', result
    task = runtime.contracts.TaskResult.from_dict(result['task_results']['merge'])
    records = task.output('records')
    assert [(column.name, column.nullable) for column in records.columns] == [
        ('Source File', False), ('Customer ID', True), ('Name', False), ('Amount', True), ('Channel', True),
    ]
    assert any('left blank' in text for text in records.completeness.limitations)
    source = open_orchestration_export_source(case.fixture.restart(), records)
    with build_generated_file_export(
        source=source, export_request=GeneratedFileExportRequest('csv', 'exact_tabular_records_v1'),
        max_output_bytes=1024 * 1024,
    ) as output:
        content = output.file_content.read()
        source.require_complete_consumption()
    assert list(csv.reader(io.StringIO(content.decode('utf-8')))) == [
        ['Source File', 'Customer ID', 'Name', 'Amount', 'Channel'],
        ['web.csv', '', 'Dee', '', 'Online'],
        ['crm.csv', '002', 'Bob', '5', ''],
        ['crm.csv', '001', 'Ann', '10', ''],
    ]


def test_excluded_files_are_reported_in_the_summary_and_limitations(runtime):
    case = tabular_case(runtime, [step(
        'merge', 'tabular_merge', ['crm-doc', 'web-doc'], on_incompatible='exclude',
    )])
    result = execute(runtime, case)
    assert result['status'] == 'completed', result
    task = runtime.contracts.TaskResult.from_dict(result['task_results']['merge'])
    records = task.output('records')
    assert records.item_count == 2
    assert any('were left out' in text for text in records.completeness.limitations)
    summary = next(item['summary'] for item in result['steps'] if item['step_id'] == 'merge')
    assert summary == (
        "Merged 2 row(s) from 2 file(s) into 4 column(s); left out 1 file(s) or sheet(s) whose columns don't fit."
    )


def test_missing_dedupe_columns_use_an_application_owned_failure(runtime):
    case = tabular_case(runtime, [step(
        'merge', 'tabular_merge', ['crm-doc', 'web-doc'], schema_policy='union',
        dedupe='key_columns', dedupe_columns=['Order ID'],
    )])
    result = execute(runtime, case)
    assert result['status'] == 'failed'
    assert result['failure']['code'] == 'merge_columns_not_found'
    assert 'Order ID' not in result['message']


def test_composition_profile_validator_accepts_only_valid_mappings():
    from functions_orchestration_result_contracts import ResultContractError
    from functions_orchestration_services import composition_profiles, validate_composition_profile

    assert set(composition_profiles()) == {'prepared_slide_deck_v1', PROFILE}
    assert validate_composition_profile(PROFILE, MAPPING) is True
    for invalid in (
        {'columns': ['A'], 'mappings': [], 'extra': True},
        {'columns': ['A', 'a'], 'mappings': []},
        {'columns': ['A'], 'mappings': [{'source_column': 'B', 'target_column': 'C', 'confidence': 'high'}]},
        {'columns': ['A', 'B'], 'mappings': [{'source_column': 'B', 'target_column': 'A', 'confidence': 'high'}]},
        {'columns': ['A'], 'mappings': [{'source_column': 'A', 'target_column': None, 'confidence': 'high'}]},
        {'columns': ['A'], 'mappings': [{'source_column': 'x', 'target_column': 'A', 'confidence': 'sure'}]},
        {'columns': ['A'], 'mappings': [
            {'source_column': 'x', 'target_column': 'A', 'confidence': 'high'},
            {'source_column': 'X', 'target_column': None, 'confidence': 'high'},
        ]},
        {'columns': [], 'mappings': []},
    ):
        with pytest.raises(ResultContractError) as refused:
            validate_composition_profile(PROFILE, invalid)
        assert refused.value.code == 'result_schema_invalid'


def test_planner_is_offered_the_reconciliation_recipe(runtime):
    from functions_orchestration_deliverables import build_deliverable_availability

    settings = {'enable_chat_orchestration': True, 'enable_user_workspace': True}
    capabilities = [
        runtime.registry.get_capability(capability_id)
        for capability_id in ('tabular_inspect', 'tabular_merge', 'compose', 'render_file')
    ]
    availability = build_deliverable_availability(
        settings, capabilities=capabilities, unavailable={}, export_catalog=None,
    )
    recipes = {recipe['for']: recipe['steps'] for recipe in availability['recipes']}
    steps = recipes['One file merged from CSV or Excel files whose columns differ']
    assert PROFILE in steps and 'tabular_inspect' in steps

    without_inspect = build_deliverable_availability(
        settings, capabilities=[item for item in capabilities if item['id'] != 'tabular_inspect'],
        unavailable={}, export_catalog=None,
    )
    assert 'One file merged from CSV or Excel files whose columns differ' not in {
        recipe['for'] for recipe in without_inspect['recipes']
    }


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-q']))
