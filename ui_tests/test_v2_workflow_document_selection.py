# test_v2_workflow_document_selection.py
"""
Real-bundle UI tests for explanatory per-task document filters and advisory preview.
Version: 0.261.332
Implemented in: 0.261.332

Uses the shared Azure Playwright-compatible closed browser harness. No production
workflow, document, or model is contacted; saved API payloads are inspected.
"""

import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, expect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'functional_tests'))
sys.path.insert(0, str(ROOT / 'ui_tests'))
sys.path.insert(0, str(ROOT / 'ui_tests' / 'fixtures'))

from test_support import workflow_assist as wa
from ui_tests.fixtures.workflow_editor import GROUP_ID, WORKFLOW_ID, workflow_ui
from ui_tests.fixtures.workflow_workbench import create_workflow, edit_workflow
from ui_tests.test_v2_workflow_ask_ai import (
    answered, ask, ask_ui, open_ask_ai, open_classic, undo_button,
)

pytestmark = pytest.mark.ui


def prepare(ui):
    ui.editor_option_overrides = {'document_workspaces': [{'scope_type': 'personal', 'name': 'My workspace'}]}
    ui.page.route('**/api/documents/tags', lambda route: route.fulfill(json={'tags': [{'name': 'X'}, {'name': 'Finance'}]}))
    ui.open('/workspace/workflows')
    create_workflow(ui.page)
    ui.page.get_by_label('Workflow name', exact=True).fill('Recent document review')
    ui.page.get_by_label('Runner type', exact=True).select_option('agent')
    ui.page.get_by_label('Agent', exact=True).select_option(label='Workspace reviewer')
    ui.page.get_by_label('Task name', exact=True).fill('Review matching documents')
    ui.page.get_by_label('Instructions', exact=True).fill('Summarize the matching documents.')
    ui.page.get_by_text('Runner, inputs, references and outputs', exact=True).first.click()
    ui.page.get_by_label('Document action', exact=True).select_option('analyze_recent')
    return ui.page.locator('[data-workflow-document-selection]')


@pytest.mark.parametrize('width', [390, 1280])
def test_guided_nested_filters_preview_and_exact_save(workflow_ui, width):
    ui, page = workflow_ui, workflow_ui.page
    page.set_viewport_size({'width': width, 'height': 1000})
    previews = []

    def preview(route):
        previews.append(route.request.post_data_json)
        route.fulfill(json={'count': 2, 'count_exact': True, 'limit': 10, 'within_limit': True,
                            'cutoff_ts': 1700000000, 'advisory': True,
                            'items': [{'document_id': 'one', 'file_name': 'Tim-report.pdf', 'scope_type': 'personal', 'scope_id': 'owner'},
                                      {'document_id': 'two', 'file_name': '<script>alert(1)</script>.csv', 'scope_type': 'personal', 'scope_id': 'owner'}]})

    page.route('**/workflows/document-selection/preview', preview)
    selector = prepare(ui)
    expect(selector.get_by_text('Workspace and time boundaries always apply', exact=False)).to_be_visible()
    selector.get_by_label('Within the last', exact=True).fill('5')
    selector.get_by_label('Time unit', exact=True).select_option('days')
    selector.get_by_role('button', name='Add AND / OR group', exact=True).click()
    selector.get_by_label('File name value', exact=True).fill('Tim')
    group = selector.get_by_role('group', name='Filter group', exact=True)
    group.get_by_role('button', name='Add filter', exact=True).click()
    group.get_by_label('Filter by', exact=True).nth(1).select_option('tags')
    group.get_by_label('Find tags', exact=True).fill('X')
    group.get_by_role('checkbox', name='X', exact=True).check()
    selector.get_by_role('button', name='Add filter', exact=True).last.click()
    selector.get_by_label('Filter by', exact=True).last.select_option('file_type')
    selector.get_by_role('checkbox', name='PDF', exact=True).check()
    selector.get_by_role('checkbox', name='CSV', exact=True).check()
    expect(selector.get_by_label('Document selection summary', exact=True)).to_contain_text(' OR ')
    expect(selector.get_by_label('Document selection summary', exact=True)).to_contain_text(' AND ')
    selector.get_by_role('button', name='Preview matching documents', exact=True).click()
    expect(selector.get_by_text('2 matching documents (limit 10).', exact=True)).to_be_visible()
    expect(selector.get_by_text('<script>alert(1)</script>.csv', exact=True)).to_be_visible()
    assert previews[-1]['recent_window_minutes'] == 7200
    assert previews[-1]['document_selection']['scopes'] == [{'scope_type': 'personal'}]
    assert len(previews[-1]['document_selection']['filters']['conditions']) == 2
    selector.get_by_label('Within the last', exact=True).fill('6')
    expect(selector.get_by_text('2 matching documents (limit 10).', exact=True)).to_have_count(0)
    selector.get_by_label('Within the last', exact=True).fill('5')
    layout = selector.evaluate('(element) => ({width: element.clientWidth, scroll: element.scrollWidth})')
    assert layout['scroll'] <= layout['width'] + 1
    try:
        with page.expect_response(lambda response: response.request.method == 'POST' and
                                  response.url.endswith('/api/user/workflows')):
            page.get_by_role('button', name='Save workflow', exact=True).click()
    except PlaywrightTimeoutError:
        raise AssertionError(page.get_by_role('alert').all_text_contents()) from None
    writes = [entry for entry in ui.workflow_writes if entry.path == '/api/user/workflows' and entry.method == 'POST']
    assert writes
    saved = writes[-1].body['tasks'][0]['document_action']
    assert saved['recent_window_minutes'] == 7200
    assert saved['document_selection'] == previews[-1]['document_selection']


def test_regex_errors_empty_preview_and_window_validation(workflow_ui):
    ui, page = workflow_ui, workflow_ui.page
    selector = prepare(ui)
    selector.get_by_role('button', name='Add filter', exact=True).click()
    selector.get_by_label('Match rule', exact=True).select_option('regex')
    selector.get_by_label('Filename regular expression', exact=True).fill('[')
    selector.get_by_role('checkbox', name='Match case', exact=True).check()
    page.route('**/workflows/document-selection/preview', lambda route: ui._json(
        route, {'error': 'The filename regular expression is invalid. Review its syntax.', 'code': 'document_selection_regex_invalid'}, 400,
    ))
    selector.get_by_role('button', name='Preview matching documents', exact=True).click()
    expect(selector.get_by_role('alert')).to_contain_text('regular expression is invalid')
    selector.get_by_label('Filename regular expression', exact=True).fill('^Tim.*\\.pdf$')
    expect(selector.get_by_role('alert')).to_have_count(0)
    page.unroute('**/workflows/document-selection/preview')
    page.route('**/workflows/document-selection/preview', lambda route: route.fulfill(
        json={'count': 0, 'count_exact': True, 'limit': 10, 'within_limit': True, 'items': [], 'advisory': True, 'cutoff_ts': 1700000000},
    ))
    selector.get_by_role('button', name='Preview matching documents', exact=True).click()
    expect(selector.get_by_text('No recent documents found for these conditions.', exact=True)).to_be_visible()
    selector.get_by_label('Time unit', exact=True).select_option('days')
    selector.get_by_label('Within the last', exact=True).fill('366')
    expect(selector.get_by_role('alert')).to_contain_text('365 days')
    page.get_by_role('button', name='Save workflow', exact=True).click()
    assert not ui.workflow_writes
    selector.get_by_label('My workspace', exact=True).uncheck()
    expect(selector.get_by_role('alert')).to_contain_text('available workspaces')
    assert not ui.workflow_writes


def test_group_filters_and_preview_keep_explicit_scope_and_independent_tasks(workflow_ui):
    ui, page = workflow_ui, workflow_ui.page
    ui.editor_option_overrides = {'document_workspaces': [
        {'scope_type': 'group', 'scope_id': GROUP_ID, 'name': 'Alpha Group'},
    ]}
    requests = []

    def tags(route):
        assert parse_qs(urlsplit(route.request.url).query) == {'group_id': [GROUP_ID]}
        route.fulfill(json={'tags': [{'name': 'X'}]})

    def preview(route):
        assert parse_qs(urlsplit(route.request.url).query) == {'group_id': [GROUP_ID]}
        requests.append(route.request.post_data_json)
        route.fulfill(json={'count': 0, 'count_exact': True, 'limit': 10, 'within_limit': True,
                            'cutoff_ts': 1700000000, 'items': [], 'advisory': True})

    page.route('**/api/group_documents/tags?group_id=*', tags)
    page.route('**/workflows/document-selection/preview?group_id=*', preview)
    ui.open('/groups')
    ui.select_group(GROUP_ID)
    create_workflow(page)
    page.get_by_label('Workflow name', exact=True).fill('Group rolling review')
    page.get_by_label('Model', exact=True).select_option(label='Workspace GPT · aoai')
    page.get_by_label('Instructions', exact=True).fill('Review tagged documents.')
    page.get_by_text('Runner, inputs, references and outputs', exact=True).first.click()
    page.get_by_label('Document action', exact=True).first.select_option('analyze_recent')
    selector = page.locator('[data-workflow-document-selection]').first
    selector.get_by_role('button', name='Add filter', exact=True).click()
    selector.get_by_label('Filter by', exact=True).select_option('tags')
    selector.get_by_role('checkbox', name='X', exact=True).check()
    selector.get_by_role('button', name='Preview matching documents', exact=True).click()
    expect(selector.get_by_text('No recent documents found for these conditions.', exact=True)).to_be_visible()
    page.get_by_role('button', name='Add task', exact=True).click()
    page.get_by_label('Instructions', exact=True).nth(1).fill('Search different recent documents.')
    page.get_by_text('Runner, inputs, references and outputs', exact=True).nth(1).click()
    page.get_by_label('Document action', exact=True).nth(1).select_option('search_recent')
    other = page.locator('[data-workflow-document-selection]').nth(1)
    other.get_by_label('Within the last', exact=True).fill('3')
    other.get_by_label('Time unit', exact=True).select_option('days')
    expect(selector.get_by_role('checkbox', name='X', exact=True)).to_be_checked()
    with page.expect_response(lambda response: response.request.method == 'POST' and
                              urlsplit(response.url).path == '/api/group/workflows'):
        page.get_by_role('button', name='Save workflow', exact=True).click()
    saved = [entry for entry in ui.workflow_writes if entry.method == 'POST'][-1]
    assert saved.query['group_id'] == [GROUP_ID]
    first, second = [task['document_action'] for task in saved.body['tasks']]
    assert first['document_selection'] == requests[-1]['document_selection']
    assert first['document_selection']['scopes'] == [{'scope_type': 'group', 'scope_id': GROUP_ID}]
    assert first['recent_window_minutes'] == 60 and second['recent_window_minutes'] == 4320
    assert second['document_selection']['filters']['conditions'] == []


def test_ai_selection_clarification_and_undo_rehydrate_guided_fields(ask_ui):
    ui, page = ask_ui, ask_ui.page
    ui.editor_option_overrides = {'document_workspaces': [{'scope_type': 'personal', 'name': 'My workspace'}]}
    page.route('**/api/documents/tags', lambda route: route.fulfill(json={'tags': []}))
    ui.assist.queue(ui.assist.pipeline(wa.reply('changed', 'Prepared the recent-document task.', [{
        'op': 'set_task_document_selection', 'task': 'task_1', 'action': 'analyze',
        'workspaces': ['workspace_1'], 'recent_window_minutes': 7200, 'on_empty': 'report',
        'filters': {'operator': 'and', 'conditions': [
            {'field': 'filename', 'operator': 'starts_with', 'value': 'Tim', 'match_case': False},
        ]},
    }], clarification={'question': 'What time should the workflow run?', 'fields': ['schedule_time']})))
    editor = open_classic(ui)
    panel = open_ask_ai(editor)
    body = ask(ui, panel, 'Review Tim documents from the last five days on Tuesday and Thursday.')
    card = answered(panel, body)
    expect(card.get_by_text('What time should the workflow run?', exact=False)).to_be_visible()
    details = editor.get_by_text('Runner, inputs, references and outputs', exact=True).first
    details.click()
    selector = editor.locator('[data-workflow-document-selection]').first
    expect(selector.get_by_label('File name value', exact=True)).to_have_value('Tim')
    expect(selector.get_by_label('Document selection summary', exact=True)).to_contain_text('Tim')
    undo_button(card).click()
    expect(editor.locator('[data-workflow-document-selection]')).to_have_count(0)
    assert not ui.workflow_writes


@pytest.mark.parametrize('scope', ['personal', 'group'])
def test_malformed_saved_selection_is_resettable_without_crashing(workflow_ui, scope):
    ui, page = workflow_ui, workflow_ui.page
    source = {'scope_type': scope, **({'scope_id': GROUP_ID} if scope == 'group' else {})}
    ui.editor_option_overrides = {'document_workspaces': [{**source, 'name': 'Current workspace'}]}
    record = ui.group_workflows[GROUP_ID]['group-workflow'] if scope == 'group' else ui.personal_workflows[WORKFLOW_ID]
    record['tasks'][0]['document_action'] = {
        'type': 'analyze', 'target_mode': 'recent', 'recent_window_minutes': 60,
        'doc_scope': scope, 'document_selection': {
            'scopes': [None], 'filters': {'operator': 'and', 'conditions': []}, 'on_empty': 'report',
        },
    }
    if scope == 'group':
        ui.open('/groups')
        ui.select_group(GROUP_ID)
    else:
        ui.open('/workspace/workflows')
    editor = edit_workflow(page, record['name'])
    editor.get_by_text('Runner, inputs, references and outputs', exact=True).first.click()
    expect(editor.get_by_text('This saved document selection has an unsupported structure.', exact=False)).to_be_visible()
    page.get_by_role('button', name='Save workflow', exact=True).click()
    assert not ui.workflow_writes
    editor.get_by_role('button', name='Reset document filters and workspaces', exact=True).click()
    selector = editor.locator('[data-workflow-document-selection]').first
    expect(selector.get_by_role('checkbox', name='Current workspace', exact=True)).to_be_checked()
    expect(selector.get_by_label('Within the last', exact=True)).to_have_value('1')


def test_unavailable_workspace_can_be_removed_without_losing_filters(workflow_ui):
    ui, page = workflow_ui, workflow_ui.page
    ui.editor_option_overrides = {'document_workspaces': [{'scope_type': 'personal', 'name': 'My workspace'}]}
    record = ui.personal_workflows[WORKFLOW_ID]
    record['tasks'][0]['document_action'] = {
        'type': 'analyze', 'target_mode': 'recent', 'recent_window_minutes': 7200,
        'doc_scope': 'all', 'document_selection': {
            'scopes': [{'scope_type': 'personal'}, {'scope_type': 'group', 'scope_id': 'unavailable-group'}],
            'filters': {'operator': 'and', 'conditions': [
                {'field': 'filename', 'operator': 'starts_with', 'value': 'Tim'},
            ]},
            'on_empty': 'report',
        },
    }
    ui.open('/workspace/workflows')
    editor = edit_workflow(page, record['name'])
    editor.get_by_text('Runner, inputs, references and outputs', exact=True).first.click()
    selector = editor.locator('[data-workflow-document-selection]').first
    expect(selector.get_by_text('A selected workspace is unavailable.', exact=False)).to_be_visible()
    selector.get_by_role('button', name='Remove unavailable workspace', exact=True).click()
    expect(selector.get_by_text('A selected workspace is unavailable.', exact=False)).to_have_count(0)
    expect(selector.get_by_label('File name value', exact=True)).to_have_value('Tim')
    expect(selector.get_by_role('checkbox', name='My workspace', exact=True)).to_be_checked()
    expect(selector.get_by_label('Within the last', exact=True)).to_have_value('5')
