# test_workflow_document_selection.py
"""
Functional tests for rolling per-task document selection and contextual Ask AI.
Version: 0.261.329
Implemented in: 0.261.329

Exercises typed filters, real paged/authorized catalog reads, normalization and
the real assist core without network access. No selection writes documents.
"""

import ast
import copy
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'application' / 'single_app'))
sys.path.insert(0, str(ROOT / 'functional_tests'))

import functions_workflow_document_selection as selection
import test_workflow_loop_inputs as loop_tests
from test_support import workflow_assist as wa
from test_workflow_document_picker_recent_targets import document_actions_over_stubs


@pytest.mark.parametrize('optimized', [False, True])
def test_pure_selector_cold_import_and_validation_without_application_bootstrap(optimized):
    probe = """
import sys
import functions_workflow_document_selection as selection
if any(name == 'config' or name == 'flask' or name.startswith('azure.') or
       name.startswith('content_screening') for name in sys.modules):
    raise AssertionError('Pure selector imported application or Azure bootstrap.')
config = {'scopes': [{'scope_type': 'personal'}], 'on_empty': 'report',
          'filters': {'field': 'filename', 'operator': 'starts_with', 'value': 'Tim'}}
matcher = selection.DocumentSelectionMatcher(config, 365 * 1440, now=1000000)
matched = matcher.matches({'_ts': 1000000, 'file_name': 'tim.pdf'})
if not matched:
    raise AssertionError('Exact case-insensitive metadata matching failed.')
try:
    selection.DocumentSelectionMatcher(config, True)
except selection.DocumentSelectionError:
    pass
else:
    raise AssertionError('Boolean window was accepted.')
"""
    environment = {**os.environ, 'PYTHONPATH': str(ROOT / 'application' / 'single_app')}
    result = subprocess.run(
        [sys.executable, *(['-O'] if optimized else []), '-c', probe],
        cwd=ROOT, env=environment, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def predicate(field='filename', operator='starts_with', value='Tim', **kwargs):
    return {'field': field, 'operator': operator, 'value': value, **kwargs}


def action(filters=None, kind='analyze', scopes=None):
    return {
        'type': kind, 'target_mode': 'recent', 'recent_window_minutes': 5 * 1440,
        'document_selection': {
            'scopes': scopes or [{'scope_type': 'personal'}], 'on_empty': 'report',
            'filters': filters if filters is not None else {'operator': 'and', 'conditions': []},
        },
        **({'merge_kind': 'pdf', 'output_format': 'pdf'} if kind == 'merge' else {}),
    }


def matcher(filters=None, minutes=7200):
    config = action(filters)
    return selection.DocumentSelectionMatcher(config['document_selection'], minutes, now=1000000)


@pytest.mark.parametrize('unit,number', [(1, 5), (60, 5), (1440, 5), (10080, 5), (1440, 365)])
def test_exact_time_boundaries_and_updated_documents(unit, number):
    match = matcher(minutes=unit * number)
    for timestamp, expected in [(match.cutoff - 1, False), (match.cutoff, True), (1000000, True),
                                (1000001, False), (True, False), (float('nan'), False)]:
        assert match.matches({'_ts': timestamp, 'file_name': 'new.pdf'}) is expected


@pytest.mark.parametrize('value', [0, -1, 525601, 1.5, True, '7200', None])
def test_invalid_windows_are_not_clamped_or_defaulted(value):
    with pytest.raises(selection.DocumentSelectionError):
        matcher(minutes=value)


@pytest.mark.parametrize('condition,metadata', [
    (predicate(), {'file_name': ['Tim.pdf']}),
    (predicate('classification', 'equals', 'Restricted'), {'document_classification': ['Restricted']}),
    (predicate('tags', 'has_any', ['X']), {'tags': 'X'}),
    (predicate('author', 'contains', 'Tim'), {'authors': [None, 12, {'name': 'Tim'}]}),
])
def test_malformed_metadata_does_not_match(condition, metadata):
    match = matcher(condition)
    assert not match.matches({'_ts': 1000000, **metadata})


def test_workspace_and_time_boundaries_are_outside_nested_or():
    filters = {'operator': 'and', 'conditions': [
        {'operator': 'or', 'conditions': [predicate(), predicate('tags', 'has_any', ['X'])]},
        predicate('file_type', 'has_any', ['pdf', 'csv']),
    ]}
    match = matcher(filters)
    base = {'_ts': 1000000, 'file_name': 'Other.pdf', 'tags': ['X']}
    assert match.matches(base)
    assert match.matches({**base, 'file_name': 'tim-report.csv', 'tags': []})
    assert not match.matches({**base, 'file_name': 'Other.csv', 'tags': []})
    assert not match.matches({**base, '_ts': match.cutoff - 1})
    assert not match.matches({**base, 'file_name': 'Tim.docx'})


@pytest.mark.parametrize('field,operator,value,metadata', [
    ('filename', 'contains', 'REPORT', {'file_name': 'Tim-report.pdf'}),
    ('filename', 'equals', 'tim.pdf', {'file_name': 'Tim.pdf'}),
    ('filename', 'regex', r'^Tim.*\.pdf$', {'file_name': 'tim-report.pdf'}),
    ('tags', 'has_all', ['X', 'Y'], {'tags': ['x', 'Y', 'other']}),
    ('file_type', 'has_any', ['pdf'], {'file_name': 'REPORT.PDF'}),
    ('classification', 'equals', 'restricted', {'document_classification': 'Restricted'}),
    ('author', 'contains', 'tim', {'authors': ['Tim Jones']}),
    ('keywords', 'equals', 'finance', {'keywords': ['Finance']}),
])
def test_metadata_matching_and_visible_case_option(field, operator, value, metadata):
    match = matcher(predicate(field, operator, value))
    assert match.matches({'_ts': 1000000, **metadata})
    if field == 'filename' and operator == 'regex':
        assert not matcher(predicate(field, operator, value, match_case=True)).matches({'_ts': 1000000, **metadata})


@pytest.mark.parametrize('filters', [
    predicate(operator='regex', value='['), predicate(field='unsupported'),
    predicate('tags', 'equals', 'X'), predicate('file_type', 'has_any', ['exe']),
    predicate('author', 'regex', '.*'), predicate(value=''), predicate(match_case='true'),
    {'operator': 'xor', 'conditions': []},
    {'operator': 'and', 'conditions': [{'operator': 'or', 'conditions': []}]},
    {'operator': 'and', 'conditions': [predicate()] * 32},
])
def test_malformed_filters_are_rejected(filters):
    with pytest.raises(selection.DocumentSelectionError):
        matcher(filters)


def test_bounded_regex_timeout_is_a_failure_not_an_empty_match():
    match = matcher(predicate(operator='regex', value='(a+)+$'))
    with patch.object(selection, 'REGEX_TIMEOUT_SECONDS', 0.000001):
        with pytest.raises(selection.DocumentSelectionError, match='took too long'):
            match.matches({'_ts': 1000000, 'file_name': 'a' * 20000 + '!'})


@pytest.fixture
def catalog():
    harness = loop_tests.LoopInputTests()
    harness.setUp()
    try:
        yield harness
    finally:
        harness.doCleanups()


def resolve(catalog, config=None, limit=10):
    return selection.resolve_document_selection(
        catalog.workflow, config or action(), catalog.settings, actor_user_id='owner', limit=limit,
    )


def test_real_paged_catalog_filters_before_limits_and_uses_current_documents(catalog):
    now = int(time.time())
    for index in range(240):
        catalog.add_document(f'doc-{index}', file_name='Other.txt', _ts=now)
    catalog.add_document('match-1', file_name='Tim-first.pdf', _ts=now - 60)
    catalog.add_document('match-2', file_name='TIM-second.pdf', _ts=now)
    result = resolve(catalog, action(predicate()), limit=2)
    assert result['count_exact'] is True
    assert [entry['document']['document_id'] for entry in result['entries']] == ['match-2', 'match-1']
    assert catalog.index.responses[0].pages_read >= 3


def test_limit_failure_never_returns_a_partial_selection(catalog):
    for index in range(3):
        catalog.add_document(f'doc-{index}', _ts=int(time.time()))
    with pytest.raises(selection.DocumentSelectionLimitError) as caught:
        resolve(catalog, limit=2)
    assert caught.value.count == 3 and caught.value.count_exact is False


def test_catalog_failure_and_inaccessible_scope_are_not_no_matches(catalog):
    catalog.add_document('one', _ts=int(time.time()))
    catalog.index.incomplete = True
    with pytest.raises(loop_tests.WorkflowLoopInputError):
        resolve(catalog)
    catalog.index.incomplete = False
    with pytest.raises(loop_tests.WorkflowLoopInputError):
        resolve(catalog, action(scopes=[{'scope_type': 'group', 'scope_id': 'forged'}]))
    result = resolve(catalog, action(predicate(value='No such prefix')))
    assert result['count'] == 0 and result['count_exact'] is True


def test_group_boundary_is_mandatory_and_public_scope_is_explicit(catalog):
    now = int(time.time())
    catalog.add_document('own', scope='group', _ts=now)
    catalog.add_document('public', scope='public', _ts=now)
    catalog.workflow['group_id'] = 'group-1'
    with pytest.raises(loop_tests.WorkflowLoopInputError):
        resolve(catalog, action(scopes=[{'scope_type': 'personal'}]))
    own = resolve(catalog, action(scopes=[{'scope_type': 'group', 'scope_id': 'group-1'}]))
    assert own['count'] == 1
    catalog.workflow.pop('group_id')
    public = resolve(catalog, action(scopes=[{'scope_type': 'public', 'scope_id': 'public-1'}]))
    assert [entry['document']['document_id'] for entry in public['entries']] == ['public']


@pytest.mark.parametrize('kind', ['analyze', 'search', 'comparison', 'merge'])
def test_save_normalization_preserves_selector_for_every_action(kind):
    config = action(predicate(), kind)
    with document_actions_over_stubs() as actions:
        normalized = actions.normalize_document_action_config(config)
    assert normalized['document_selection'] == config['document_selection']
    assert normalized['recent_window_minutes'] == 7200
    assert normalized['doc_scope'] == 'personal'
    assert normalized['document_ids'] == []


def test_contextual_metadata_edits_apply_while_clarification_is_needed():
    draft = wa.new_draft(name='', description='')
    draft['tasks'] = [{**draft['tasks'][0], 'name': 'Task 1', 'instructions': ''}]
    output = {'outcome': 'changed', 'reply': 'Named the draft.',
              'operations': [{'op': 'set_name', 'name': 'Tuesday and Thursday document summary'},
                             {'op': 'set_description', 'description': 'Summarize recently updated documents twice weekly.'},
                             {'op': 'set_task_name', 'task': 'task_1', 'name': 'Summarize documents'}],
              'clarification': {'question': 'What time should it run?', 'fields': ['schedule_time']}}
    model = wa.ScriptedModel(json.dumps(output))
    services = wa.services(model)
    body = wa.request_body(instruction='Give this a name and a description.', draft=draft)
    body['conversation'] = [{'role': 'user', 'text': 'Summarize my latest documents on Tuesday and Thursday.'}]
    result = wa.run(body, services)
    assert result['outcome'] == 'changed'
    assert result['candidate']['name'] == output['operations'][0]['name']
    assert result['candidate']['tasks'][0]['instructions'] == ''
    assert result['clarification'] == output['clarification']
    assert model.envelope()['authoring'] == {'is_new': True, 'blank_initial_task': True}


def test_noop_metadata_edit_keeps_the_missing_detail_question():
    draft = wa.new_draft()
    output = {'outcome': 'changed', 'reply': 'Reviewed.',
              'operations': [{'op': 'set_name', 'name': draft['name']}],
              'clarification': {'question': 'Which lookback window?', 'fields': ['lookback']}}
    result = wa.run(wa.request_body(draft=draft), wa.services(wa.ScriptedModel(json.dumps(output))))
    assert result['outcome'] == 'explained' and result['changes'] == []
    assert result['clarification'] == output['clarification']


def test_ai_targeted_window_and_filter_edits_preserve_other_conditions_and_tasks():
    draft = wa.new_draft()
    filters = {'operator': 'and', 'conditions': [
        predicate('file_type', 'has_any', ['pdf', 'csv']),
        {'operator': 'or', 'conditions': [predicate(), predicate('tags', 'has_any', ['X'])]},
    ]}
    draft['tasks'][0]['document_action'] = action(filters)
    second_task = copy.deepcopy(draft['tasks'][1])
    operations = [
        {'op': 'update_task_document_window', 'task': 'task_1', 'recent_window_minutes': 50400},
        {'op': 'replace_task_document_filter', 'task': 'task_1', 'path': [1, 0],
         'filter': predicate(operator='regex', value=r'^Tim.*\.pdf$', match_case=True)},
    ]
    result = wa.run(wa.request_body(draft=draft), wa.services(wa.ScriptedModel(wa.reply('changed', 'Updated.', operations))))
    updated = result['candidate']['tasks'][0]['document_action']
    expected = copy.deepcopy(filters)
    expected['conditions'][1]['conditions'][0] = operations[1]['filter']
    assert updated['recent_window_minutes'] == 50400
    assert updated['document_selection']['filters'] == expected
    assert result['candidate']['tasks'][1] == second_task
    assert draft['tasks'][0]['document_action']['recent_window_minutes'] == 7200


@pytest.mark.parametrize('path', [[9], [1, 9], [0, 0], []])
def test_invalid_filter_paths_fail_without_applying_partial_changes(path):
    draft = wa.new_draft()
    draft['tasks'][0]['document_action'] = action({'operator': 'and', 'conditions': [predicate()]})
    output = wa.reply('changed', 'Updated.', [
        {'op': 'update_task_document_window', 'task': 'task_1', 'recent_window_minutes': 50400},
        {'op': 'replace_task_document_filter', 'task': 'task_1', 'path': path, 'filter': predicate(value='Other')},
    ])
    error = wa.refusal(wa.request_body(draft=draft), wa.services(wa.ScriptedModel(output, output)))
    assert error.code == 'assistant_output_invalid'
    assert draft['tasks'][0]['document_action']['recent_window_minutes'] == 7200


def test_complete_authoring_cannot_use_placeholder_task_instructions():
    draft = wa.new_draft(name='', description='')
    draft['tasks'] = [{**draft['tasks'][0], 'instructions': ''}]
    output = {'outcome': 'changed', 'reply': 'Created.', 'authoring_complete': True,
              'operations': [{'op': 'set_name', 'name': 'Document review'}]}
    error = wa.refusal(wa.request_body(draft=draft), wa.services(wa.ScriptedModel(json.dumps(output), json.dumps(output))))
    assert error.code == 'assistant_output_invalid'


def test_native_source_scope_binding_is_actor_scoped_and_restored():
    entries = [{'document': {'document_id': 'same', 'scope_type': 'group', 'scope_id': 'group-2'}}]
    with selection.selected_document_sources(entries, 'owner'):
        validator = selection.selected_document_context_validator('owner')
        assert not validator({'scope': 'personal'}, 'same')
        assert not validator({'scope': 'group', 'group_id': 'group-1'}, 'same')
        assert validator({'scope': 'group', 'group_id': 'group-2'}, 'same')
        assert selection.selected_document_context_validator('another-owner') is None
        assert not selection.selected_source_matches('owner', 'same', 'group', 'group-1')
        with selection.selected_document_sources([], 'owner'):
            assert selection.selected_source_matches('owner', 'same', 'group', 'group-1')
        assert not selection.selected_source_matches('owner', 'same', 'group', 'group-1')
    assert selection.selected_document_context_validator('owner') is None
    with pytest.raises(selection.DocumentSelectionError, match='share an identifier'):
        with selection.selected_document_sources(entries + [
            {'document': {'document_id': 'same', 'scope_type': 'personal', 'scope_id': 'owner'}},
        ], 'owner'):
            pytest.fail('Conflicting source identities must never dispatch.')


def test_real_native_context_and_search_readers_keep_the_selected_workspace():
    path = ROOT / 'application' / 'single_app' / 'functions_search_service.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    names = {'resolve_document_context', 'resolve_document_contexts', '_resolve_group_document_context', 'search_documents'}
    namespace = {
        'selected_source_matches': selection.selected_source_matches,
        'selected_document_context_validator': selection.selected_document_context_validator,
        'current_public_chat_scope': lambda _actor: None,
        'normalize_search_scope': lambda scope: scope,
        'normalize_search_id_list': lambda values: list(values or []),
        '_resolve_active_group_ids': lambda *_args, **_kwargs: ['group-1', 'group-2'],
        '_resolve_public_workspace_ids': lambda *_args, **_kwargs: [],
        '_resolve_personal_document_context': lambda *_args: {'scope': 'personal', 'document': {'id': 'same'}},
        '_resolve_chat_upload_context': lambda **_kwargs: None,
        'strict_source_authority_enabled': lambda: False,
        'get_document_record': lambda **kwargs: {'id': kwargs['document_id'], 'group_id': kwargs['group_id']},
        'assert_document_available': lambda document, **_kwargs: document,
        'build_search_request': lambda **_kwargs: {'query': 'review', 'doc_scope': 'all', 'document_ids': ['same']},
        'hybrid_search': lambda **_kwargs: [
            {'document_id': 'same', 'scope': 'personal', 'scope_id': 'owner'},
            {'document_id': 'same', 'scope': 'group', 'scope_id': 'group-1'},
            {'document_id': 'same', 'scope': 'group', 'scope_id': 'group-2'},
        ],
    }
    exec(compile(ast.Module(body=[
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names
    ], type_ignores=[]), str(path), 'exec'), namespace)
    entries = [{'document': {'document_id': 'same', 'scope_type': 'group', 'scope_id': 'group-2'}}]
    with selection.selected_document_sources(entries, 'owner'):
        one = namespace['resolve_document_context']('same', 'owner')
        many = namespace['resolve_document_contexts'](['same'], 'owner')
        found = namespace['search_documents']('review', 'owner', document_ids=['same'])
    assert one['group_id'] == many[0]['group_id'] == 'group-2'
    assert found['result_count'] == found['document_count'] == 1
    assert found['results'][0]['scope_id'] == 'group-2'


def test_durable_selection_freezes_each_task_and_reauthorizes_on_resume(catalog):
    catalog.add_document('first', file_name='Tim-first.pdf', _ts=int(time.time()))

    class Execution:
        run_id = 'durable-run'
        check = staticmethod(lambda: None)

        def __init__(self):
            self.units = {}

        def run_unit(self, key, operation, *, inputs, replay_safe):
            assert replay_safe is True
            if key not in self.units:
                self.units[key] = operation()
            return self.units[key]

    execution = Execution()
    namespace = extracted_runner('_resolve_task_document_selection',
        current_workflow_execution=lambda: execution, _get_recent_workflow_document_limit=lambda *_args: 10,
        DOCUMENT_ACTION_TYPE_MERGE='merge', DOCUMENT_ACTION_TYPE_COMPARISON='comparison', WorkflowInputError=ValueError,
    )
    run = namespace['_resolve_task_document_selection']
    workflow = {**catalog.workflow, 'active_task': {'id': 'one'}}
    first = run(workflow, action(), catalog.settings)
    catalog.add_document('second', _ts=int(time.time()))
    resumed = run(workflow, action(), catalog.settings)
    other_task = run({**workflow, 'active_task': {'id': 'two'}}, action(), catalog.settings)
    assert first['document_ids'] == resumed['document_ids'] == ['first']
    assert len(other_task['document_ids']) == 2 and len(execution.units) == 2
    catalog.personal.items['first']['version'] = 2
    with pytest.raises(loop_tests.WorkflowLoopInputError):
        run(workflow, action(), catalog.settings)


def test_empty_cached_selection_still_reauthorizes_its_workspaces(catalog):
    config = action(scopes=[{'scope_type': 'group', 'scope_id': 'group-1'}])
    workflow = {**catalog.workflow, 'active_task': {'id': 'one'}, '_task_document_selection_snapshots': {}}
    namespace = extracted_runner('_resolve_task_document_selection',
        current_workflow_execution=lambda: None, _get_recent_workflow_document_limit=lambda *_args: 10,
        DOCUMENT_ACTION_TYPE_MERGE='merge', DOCUMENT_ACTION_TYPE_COMPARISON='comparison', WorkflowInputError=ValueError,
    )
    first = namespace['_resolve_task_document_selection'](workflow, config, catalog.settings)
    assert first['selection_summary']['status'] == 'no_matches'
    catalog.memberships.remove(('owner', 'group-1'))
    with pytest.raises(loop_tests.WorkflowLoopInputError):
        namespace['_resolve_task_document_selection'](workflow, config, catalog.settings)


@pytest.mark.parametrize('source_changed', [False, True])
def test_merge_collector_reads_only_frozen_authorized_documents(catalog, source_changed):
    catalog.add_document('picked', file_name='Tim-picked.pdf', _ts=int(time.time()))
    config = action(predicate(), kind='merge')
    with document_actions_over_stubs():
        captured = resolve(catalog, config)
    resolved = {**config, 'selection_entries': captured['entries']}
    catalog.add_document('later', file_name='Tim-later.pdf', _ts=int(time.time()))
    if source_changed:
        catalog.personal.items['picked']['version'] = 2
    documents = []
    merge = ModuleType('functions_workflow_merge')
    merge.WORKFLOW_MERGE_CAPABILITY = 'merge'
    merge.WorkflowMergeAccessError = type('MergeAccessError', (Exception,), {})
    merge.WorkflowMergeCancelled = type('MergeCancelled', (Exception,), {})
    merge.WorkflowMergeError = type('MergeError', (Exception,), {})

    def collect(rows, extensions, limit):
        documents.extend(rows)
        assert extensions == ['.pdf'] and limit == 10
        return rows

    def execute(action_config, _settings, **kwargs):
        rows = kwargs['collect_documents'](action_config, ['.pdf'], 10)
        return {'reply': 'Merged selected files.', 'merge_summary': {'files': len(rows)}}

    merge.collect_merge_candidates = collect
    merge.execute_workflow_merge = execute
    namespace = extracted_runner(
        '_execute_document_merge_workflow',
        current_workflow_execution=lambda: None,
        _resolve_task_document_selection=lambda *_args: resolved,
        _collect_merge_workflow_documents=lambda *_args: pytest.fail('Guided Merge must not enumerate a new catalog.'),
        _throttled_cancellation_check=lambda check: check,
        _is_workflow_run_cancellation_requested=lambda *_args: False,
        _add_workflow_activity_thought=lambda *_args, **_kwargs: None,
        resolve_analysis_source_manifest=lambda *_args, **_kwargs: None,
        WorkflowInputError=ValueError, WorkflowRunCancelledError=RuntimeError,
        WORKFLOW_RUN_CANCELLED_MESSAGE='Cancelled.',
    )
    with patch.dict(sys.modules, {'functions_workflow_merge': merge}):
        run = namespace['_execute_document_merge_workflow']
        if source_changed:
            with pytest.raises(loop_tests.WorkflowLoopInputError):
                run(catalog.workflow, config, catalog.settings, run_id='run')
        else:
            result = run(catalog.workflow, config, catalog.settings, run_id='run')
            assert result['merge_summary']['files'] == 1
    assert [document['id'] for document in documents] == ([] if source_changed else ['picked'])


def test_ai_selector_is_handle_authorized_and_lossless_on_next_turn():
    draft = wa.new_draft()
    filters = action(predicate())['document_selection']['filters']
    operation = {'op': 'set_task_document_selection', 'task': 'task_1', 'action': 'analyze',
                 'workspaces': ['workspace_1'], 'recent_window_minutes': 7200, 'filters': filters, 'on_empty': 'report'}
    model = wa.ScriptedModel(wa.reply('changed', 'Set the task document window.', [operation]))
    result = wa.run(wa.request_body(draft=draft), wa.services(model))
    candidate = result['candidate']
    assert candidate['tasks'][0]['document_action']['document_selection']['filters'] == filters
    next_model = wa.ScriptedModel(wa.reply('explained', 'Reviewed.'))
    wa.run(wa.request_body(draft=candidate), wa.services(next_model))
    view = next_model.envelope()['draft']['tasks'][0]['document_target']
    assert view['recent_window_minutes'] == 7200
    assert view['workspaces'] == ['workspace_1'] and view['filters'] == filters
    invalid = wa.reply('changed', 'Set it.', [{**operation, 'workspaces': ['workspace_99']}])
    bad = wa.ScriptedModel(invalid, invalid)
    error = wa.refusal(wa.request_body(draft=draft), wa.services(bad))
    assert error.code == 'assistant_output_invalid'


def extracted_runner(*names, **namespace):
    path = ROOT / 'application' / 'single_app' / 'functions_workflow_runner.py'
    tree = ast.parse(path.read_text(encoding='utf-8-sig'))
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), namespace)
    return namespace


@pytest.mark.parametrize('kind', ['analyze', 'search', 'comparison', 'merge'])
def test_empty_selection_dispatch_calls_no_processing_or_merge_model(kind):
    config = action(kind=kind)
    config['selection_summary'] = {'status': 'no_matches', 'count': 0, 'cutoff_ts': 1000}
    namespace = extracted_runner('_execute_workflow_dispatch', '_no_document_selection_result',
        current_workflow_execution=lambda: None, _get_document_action_config=lambda _workflow: config,
        _resolve_task_document_selection=lambda *_args: config,
    )
    result = namespace['_execute_workflow_dispatch']({'document_action': config}, {}, '', 'run-1', None, {})
    assert result['selection_summary']['status'] == 'no_matches'
    assert result['token_usage'] == {}
    assert result['model_deployment_name'] is None


def test_no_matches_survive_history_projection_without_fabricating_contract_outputs():
    from functions_workflow_results import build_workflow_task_result, workflow_result_summary
    from functions_workflow_validation import validate_workflow_task_output

    config = action()
    config['selection_summary'] = {'status': 'no_matches', 'count': 0, 'cutoff_ts': 1000}
    namespace = extracted_runner('_no_document_selection_result')
    result = namespace['_no_document_selection_result'](config)
    envelope = build_workflow_task_result(
        result, workflow={'id': 'workflow', 'user_id': 'owner'}, run_id='run', task={'id': 'task'},
    )
    summary = workflow_result_summary(envelope, {'sha256': 'a' * 64, 'size_bytes': 1})
    assert summary['document_selection'] == config['selection_summary']
    default = validate_workflow_task_output(envelope)
    required = validate_workflow_task_output(envelope, {'kind': 'records', 'expected_count': 1})
    assert default['eligible'] is True
    assert required['eligible'] is False and 'output_kind_mismatch' in required['reason_codes']
    assert envelope['outputs'][envelope['authoritative_output']]['kind'] == 'text'


def test_selection_freezes_per_task_retry_and_refreshes_in_new_run(catalog):
    catalog.add_document('first', file_name='Tim-first.pdf', _ts=int(time.time()))
    config = action()
    workflow = {**catalog.workflow, 'active_task': {'id': 'task-1'}, '_task_document_selection_snapshots': {}}
    namespace = extracted_runner('_resolve_task_document_selection',
        current_workflow_execution=lambda: None, _get_recent_workflow_document_limit=lambda *_args: 10,
        DOCUMENT_ACTION_TYPE_MERGE='merge', DOCUMENT_ACTION_TYPE_COMPARISON='comparison',
        WorkflowInputError=ValueError,
    )
    run = namespace['_resolve_task_document_selection']
    first = run(workflow, config, catalog.settings)
    catalog.add_document('second', file_name='Tim-second.pdf', _ts=int(time.time()))
    retry = run(workflow, config, catalog.settings)
    fresh = run({**workflow, '_task_document_selection_snapshots': {}}, config, catalog.settings)
    assert first['document_ids'] == retry['document_ids'] == ['first']
    assert len(fresh['document_ids']) == 2
    with pytest.raises(ValueError, match='changed during this run'):
        run(workflow, {**config, 'recent_window_minutes': 1}, catalog.settings)
