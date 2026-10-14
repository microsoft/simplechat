# test_v2_workflow_document_selection.py
"""
Real-bundle UI tests for explanatory per-task document filters and advisory preview.
Version: 0.261.333
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
from test_workflow_goal_first_authoring import PROMPT, goal_operations
from ui_tests.fixtures.workflow_editor import GROUP_ID, WORKFLOW_ID, workflow_ui
from ui_tests.fixtures.workflow_workbench import create_workflow, edit_workflow, open_workflow_runs
from ui_tests.test_v2_workflow_ask_ai import (
    answered, ask, ask_ui, open_ask_ai, open_classic, undo_button,
)

pytestmark = pytest.mark.ui


def prepare(ui, workspaces=None, *, width=1440):
    ui.editor_option_overrides = {'document_workspaces': workspaces or [{'scope_type': 'personal', 'name': 'My workspace'}]}
    ui.page.route('**/api/documents/tags', lambda route: route.fulfill(json={'tags': [{'name': 'X'}, {'name': 'Finance'}]}))
    ui.open('/workspace/workflows', width=width, height=1000)
    create_workflow(ui.page)
    ui.page.get_by_label('Workflow name', exact=True).fill('Recent document review')
    ui.page.get_by_label('Runner type', exact=True).select_option('agent')
    ui.page.get_by_label('Agent', exact=True).select_option(label='Workspace reviewer')
    ui.page.get_by_label('Task name', exact=True).fill('Review matching documents')
    ui.page.get_by_label('Instructions', exact=True).fill('Summarize the matching documents.')
    ui.page.get_by_label('Document action', exact=True).select_option('analyze')
    ui.page.get_by_label('Document source', exact=True).select_option('recent')
    return ui.page.locator('[data-workflow-document-selection]')


@pytest.mark.parametrize('width', [390, 1280])
def test_guided_nested_filters_preview_and_exact_save(workflow_ui, width):
    ui, page = workflow_ui, workflow_ui.page
    previews = []

    def preview(route):
        previews.append(route.request.post_data_json)
        route.fulfill(json={'count': 2, 'count_exact': True, 'limit': 10, 'within_limit': True,
                            'cutoff_ts': 1700000000, 'advisory': True,
                            'items': [{'document_id': 'one', 'file_name': 'Tim-report.pdf', 'scope_type': 'personal', 'scope_id': 'owner'},
                                      {'document_id': 'two', 'file_name': '<script>alert(1)</script>.csv', 'scope_type': 'personal', 'scope_id': 'owner'}]})

    page.route('**/workflows/document-selection/preview', preview)
    selector = prepare(ui, width=width)
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
    selector.get_by_role('button', name='Remove My workspace', exact=False).click()
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
    page.get_by_label('Document action', exact=True).first.select_option('analyze')
    page.get_by_label('Document source', exact=True).first.select_option('recent')
    selector = page.locator('[data-workflow-document-selection]').first
    selector.get_by_role('button', name='Add filter', exact=True).click()
    selector.get_by_label('Filter by', exact=True).select_option('tags')
    selector.get_by_role('checkbox', name='X', exact=True).check()
    selector.get_by_role('button', name='Preview matching documents', exact=True).click()
    expect(selector.get_by_text('No recent documents found for these conditions.', exact=True)).to_be_visible()
    page.get_by_role('button', name='Add task', exact=True).click()
    page.get_by_label('Instructions', exact=True).nth(1).fill('Search different recent documents.')
    page.get_by_label('Document action', exact=True).nth(1).select_option('search')
    page.get_by_label('Document source', exact=True).nth(1).select_option('recent')
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
    expect(editor.get_by_text('This saved document selection has an unsupported structure.', exact=False)).to_be_visible()
    page.get_by_role('button', name='Save workflow', exact=True).click()
    assert not ui.workflow_writes
    editor.get_by_role('button', name='Reset document filters and workspaces', exact=True).click()
    selector = editor.locator('[data-workflow-document-selection]').first
    expect(selector.get_by_role('button', name='Remove Current workspace', exact=False)).to_be_visible()
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
    selector = editor.locator('[data-workflow-document-selection]').first
    expect(selector.get_by_text('Remove this source or restore access before running.', exact=False)).to_be_visible()
    selector.get_by_role('button', name='Remove unavailable workspace', exact=True).click()
    expect(selector.get_by_text('Remove this source or restore access before running.', exact=False)).to_have_count(0)
    expect(selector.get_by_label('File name value', exact=True)).to_have_value('Tim')
    expect(selector.get_by_role('button', name='Remove My workspace', exact=False)).to_be_visible()
    expect(selector.get_by_label('Within the last', exact=True)).to_have_value('5')


@pytest.mark.parametrize('width', [390, 1280])
def test_hundreds_of_sources_are_discoverable_without_hundreds_of_controls(workflow_ui, width):
    ui, page = workflow_ui, workflow_ui.page
    tag_requests = []

    def tags(route):
        tag_requests.append(route.request.url)
        route.fulfill(json={'tags': []})

    page.route('**/api/group_documents/tags?group_id=*', tags)
    page.route('**/api/public-workspaces/*/documents/tags', tags)
    sources = [{'scope_type': 'personal', 'name': 'My workspace'}]
    sources += [{'scope_type': 'group', 'scope_id': f'g-{index}', 'name': f'Team {index:03}'}
                for index in range(110)]
    sources += [{'scope_type': 'public', 'scope_id': f'p-{index}', 'name': f'Public {index:03}'}
                for index in range(110)]
    sources += [{'scope_type': 'group', 'scope_id': identity, 'name': 'Same name'} for identity in ['duplicate-1', 'duplicate-2']]
    selector = prepare(ui, sources, width=width)
    assert not tag_requests
    available = selector.get_by_role('list', name='Available source workspaces')
    expect(available.get_by_role('button')).to_have_count(25)
    expect(selector.get_by_role('checkbox')).to_have_count(0)
    search = selector.get_by_label('Find workspaces', exact=True)
    search.fill('Public 109')
    expect(available.get_by_role('button')).to_have_count(1)
    add = available.get_by_role('button', name=re.compile('^Add Public 109'))
    add.focus()
    page.keyboard.press('Enter')
    expect(selector.get_by_role('list', name='Selected source workspaces')).to_contain_text('Public 109')
    search.fill('Same name')
    expect(available.get_by_role('button')).to_have_count(2)
    expect(available).to_contain_text('duplicate-1')
    expect(available).to_contain_text('duplicate-2')
    selector.get_by_label('Source kind', exact=True).select_option('public')
    expect(available.get_by_role('button')).to_have_count(0)
    selector.get_by_label('Source kind', exact=True).select_option('group')
    search.fill('Team')
    for _index in range(18):
        available.locator('button:not(:disabled)').first.click()
    expect(selector.get_by_text('Selected workspaces (20 / 20)', exact=True)).to_be_visible()
    expect(available.locator('button:not(:disabled)')).to_have_count(0)
    selector.get_by_role('button', name=re.compile('^Remove Public 109')).click()
    expect(search).to_be_focused()
    expect(available.locator('button:not(:disabled)').first).to_be_enabled()
    search.fill('No workspace with this name')
    expect(selector.get_by_text('No matching authorized workspace.', exact=False)).to_be_visible()
    layout = selector.evaluate('(element) => ({width: element.clientWidth, scroll: element.scrollWidth})')
    assert layout['scroll'] <= layout['width'] + 1
    assert all('p-109' in url or 'group_id=g-' in url for url in tag_requests)
    assert not ui.workflow_writes


def test_ai_goal_exposes_documents_and_missing_time_then_completes_without_reset(ask_ui):
    ui, page = ask_ui, ask_ui.page
    ui.editor_option_overrides = {'document_workspaces': [{'scope_type': 'personal', 'name': 'My workspace'}]}
    page.route('**/api/documents/tags', lambda route: route.fulfill(json={'tags': []}))
    ui.assist.queue(ui.assist.pipeline(wa.reply('changed', 'Prepared the Tuesday document summary.', goal_operations(),
        clarification={'question': 'What time should it run on Tuesday?', 'fields': ['schedule_time']})))
    editor = open_classic(ui)
    panel = open_ask_ai(editor)
    body = ask(ui, panel, PROMPT)
    card = answered(panel, body)
    expect(card.get_by_text('What time should it run on Tuesday?', exact=False)).to_be_visible()
    expect(editor.get_by_label('Document action', exact=True).first).to_be_visible()
    expect(editor.get_by_label('Document action', exact=True).first).to_have_value('analyze')
    expect(editor.get_by_label('Document source', exact=True).first).to_have_value('recent')
    selector = editor.locator('[data-workflow-document-selection]').first
    expect(selector.get_by_label('Document event', exact=True)).to_have_value('added')
    expect(selector.get_by_label('Document selection summary')).to_contain_text(re.compile(r'added within the last (7 days|1 weeks?)'))
    expect(editor.get_by_label('Trigger', exact=True)).to_have_value('interval')
    expect(editor.get_by_label('Time', exact=True)).to_have_value('')
    expect(editor.get_by_text('Choose a run time. This recurrence is incomplete', exact=False)).to_be_visible()
    expect(editor.get_by_text('tuesday · run time needed', exact=False).first).to_be_visible()
    page.get_by_role('button', name='Save workflow', exact=True).click()
    confirm = page.get_by_role('button', name='Confirm and save', exact=True)
    if confirm.is_visible():
        confirm.click()
    assert not ui.workflow_writes
    ui.assist.queue(ui.assist.pipeline(wa.reply('changed', 'Set Tuesday at 09:30.', [{
        'op': 'set_schedule_calendar', 'frequency': 'weekly', 'days_of_week': ['tuesday'], 'time_of_day': '09:30',
    }])))
    panel.get_by_role('tab', name='Ask AI', exact=True).click()
    followup = ask(ui, panel, '09:30')
    answered(panel, followup)
    expect(selector.get_by_label('Document event', exact=True)).to_have_value('added')
    expect(editor.get_by_label('Instructions', exact=True).first).to_have_value(re.compile('Read all selected documents'))
    expect(editor.get_by_label('Time', exact=True)).to_have_value('09:30')
    assert not ui.workflow_writes


def test_action_and_source_change_keep_recent_filters_but_never_hidden_ids(workflow_ui):
    ui, page = workflow_ui, workflow_ui.page
    selector = prepare(ui)
    selector.get_by_label('Document event', exact=True).select_option('added')
    selector.get_by_label('Within the last', exact=True).fill('7')
    selector.get_by_label('Time unit', exact=True).select_option('days')
    page.get_by_label('Document action', exact=True).select_option('choose')
    expect(page.get_by_label('Document source', exact=True)).to_have_value('recent')
    expect(selector.get_by_label('Document event', exact=True)).to_have_value('added')
    expect(page.get_by_text('This adds a selection-model call', exact=False)).to_be_visible()
    page.get_by_label('Document action', exact=True).select_option('search')
    expect(selector.get_by_label('Within the last', exact=True)).to_have_value('7')
    page.get_by_label('Document source', exact=True).select_option('relevance')
    expect(page.locator('[data-workflow-document-selection]')).to_have_count(0)
    expect(page.get_by_role('list', name='Selected source workspaces')).to_contain_text('My workspace')
    expect(page.get_by_text('Only the chosen workspaces are searched.', exact=False)).to_be_visible()
    page.get_by_label('Document source', exact=True).select_option('recent')
    expect(selector.get_by_label('Within the last', exact=True)).to_have_value('1')


@pytest.mark.parametrize('kind', ['analyze', 'merge'])
def test_all_files_source_keeps_recent_workspace_without_adding_personal(workflow_ui, kind):
    ui, page = workflow_ui, workflow_ui.page
    selector = prepare(ui, [
        {'scope_type': 'personal', 'name': 'My workspace'},
        {'scope_type': 'group', 'scope_id': GROUP_ID, 'name': 'Chosen group'},
    ])
    selector.get_by_role('button', name=re.compile('^Remove My workspace')).click()
    selector.get_by_role('button', name=re.compile('^Add Chosen group')).click()
    page.get_by_label('Document action', exact=True).select_option(kind)
    page.get_by_label('Document source', exact=True).select_option('all')
    expect(page.get_by_text('All eligible files in: Chosen group.', exact=False)).to_be_visible()
    page.get_by_role('button', name='Save workflow', exact=True).click()
    expect(page.get_by_role('region', name='Edit workflow', exact=True)).to_have_count(0)
    config = ui.workflow_writes[-1].body['tasks'][0]['document_action']
    assert config['doc_scope'] == 'group' and config['active_group_ids'] == [GROUP_ID]
    assert not config.get('document_ids') and 'document_selection' not in config


def test_unrepresentable_all_files_scope_never_silently_adds_personal(workflow_ui):
    ui, page = workflow_ui, workflow_ui.page
    page.route('**/api/public-workspaces/*/documents/tags', lambda route: route.fulfill(json={'tags': []}))
    selector = prepare(ui, [
        {'scope_type': 'personal', 'name': 'My workspace'},
        {'scope_type': 'group', 'scope_id': GROUP_ID, 'name': 'Chosen group'},
        {'scope_type': 'public', 'scope_id': 'public-1', 'name': 'Chosen public'},
    ])
    selector.get_by_role('button', name=re.compile('^Remove My workspace')).click()
    selector.get_by_role('button', name=re.compile('^Add Chosen group')).click()
    selector.get_by_role('button', name=re.compile('^Add Chosen public')).click()
    page.get_by_label('Document source', exact=True).select_option('all')
    expect(page.get_by_role('alert').filter(has_text='no sources were changed')).to_be_visible()
    expect(page.get_by_label('Document source', exact=True)).to_have_value('recent')
    expect(selector.get_by_role('list', name='Selected source workspaces')).not_to_contain_text('My workspace')
    assert not ui.workflow_writes


@pytest.mark.parametrize('kind', ['analyze', 'refuse'])
@pytest.mark.parametrize('version', [1, 3])
def test_run_history_exposes_safe_runtime_action_and_separate_selection_cost(workflow_ui, kind, version):
    ui, page = workflow_ui, workflow_ui.page
    summary = '<img src=x onerror="window.untrustedChoice=true">'
    public_result = {'document_action_choice': {
        'action': kind, 'summary': summary, 'input_count': 2,
        'selection_token_usage': {'total_tokens': 15},
    }}
    ui.workflow_runs[WORKFLOW_ID] = [{
        'id': 'choice-run', 'workflow_id': WORKFLOW_ID, 'status': 'completed',
        'started_at': '2026-10-14T12:00:00Z', 'definition_version': version,
    }]
    page.route('**/api/user/workflows/*/runs/choice-run/items*', lambda route: route.fulfill(json={
        'items': [{
            'id': 'choice-item', 'item_type': 'task', 'task_id': 'review', 'label': 'Review',
            'status': 'succeeded' if kind == 'analyze' else 'failed',
            'workflow_result': public_result,
        }],
    }))
    execution = {
        'execution_id': 'choice-execution', 'node_id': 'review-node', 'node_kind': 'task',
        'task_id': 'review', 'iteration_path': [], 'attempt': 1,
        'state': 'completed' if kind == 'analyze' else 'failed', 'workflow_result': public_result,
    }
    page.route('**/api/user/workflows/*/runs/choice-run/executions?*', lambda route: route.fulfill(json={
        'executions': [execution], 'next_cursor': None,
    }))
    page.route('**/api/user/workflows/*/runs/choice-run/runtime/decisions?*', lambda route: route.fulfill(json={
        'decisions': [], 'next_cursor': None,
    }))
    page.route('**/api/user/workflows/*/runs/choice-run/executions/choice-execution/attempts?*',
               lambda route: route.fulfill(json={'attempts': [execution], 'next_cursor': None}))
    ui.open('/workspace/workflows')
    runs = open_workflow_runs(page, 'Quarterly review workflow')
    runs.get_by_role('button', name='Show run task results', exact=True).click()
    expect(runs.get_by_text(f'Runtime document action: {"Analyze" if kind == "analyze" else "Refused"}', exact=True)).to_be_visible()
    expect(runs.get_by_text(summary, exact=True)).to_be_visible()
    expect(runs.get_by_text('Selection-model tokens: 15.', exact=False)).to_be_visible()
    expect(runs.locator('img')).to_have_count(0)
    if version == 3:
        runs.get_by_role('button', name='Show execution attempts for choice-execution', exact=True).click()
        attempts = runs.get_by_role('list', name='Attempts for execution choice-execution', exact=True)
        expect(attempts.get_by_text(summary, exact=True)).to_be_visible()
