# test_v2_orchestration_plan_editor_backend.py
"""
Browser-to-Flask regression for editing and running an orchestration plan.
Version: 0.261.102
Implemented in: 0.261.102

The browser's real HTTP requests are forwarded to the actual Flask route test client.
Unlike the frontend-only suite, no orchestration response is fabricated by the browser
fixture. Model, source lookup, and Cosmos service boundaries remain deterministic.
The shared browser fixture supports local Chromium and configured Azure Playwright.
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / 'functional_tests'))

# Reuse the versioned HTTP fixture and the real-component browser harness.
import test_orchestration_plan_revision_routes as backend_tests  # noqa: E402
import test_v2_orchestration_plan_editor as editor_tests  # noqa: E402
from test_v2_orchestration_plan_editor import (  # noqa: E402, F401
    connect_options,
    editor_assets,
    editor_browser,
)


pytestmark = pytest.mark.ui


@pytest.fixture
def integrated_editor(editor_browser, editor_assets):
    backend = backend_tests.PlanRevisionRouteTests()
    backend.setUp()
    context = editor_browser.new_context(viewport={'width': 1440, 'height': 900})
    page = context.new_page()
    errors = []
    requests = []

    def forward(route):
        request = route.request
        url = urlsplit(request.url)
        if f'{url.scheme}://{url.netloc}' != editor_tests.ORIGIN:
            errors.append(f'Unexpected browser origin: {request.url}')
            route.abort()
            return
        if request.method == 'GET' and url.path in editor_assets:
            route.fulfill(path=str(editor_assets[url.path]))
            return
        if url.path == '/favicon.ico':
            route.fulfill(status=204)
            return
        if not url.path.startswith('/api/v2/orchestration/'):
            errors.append(f'Unexpected browser request: {request.method} {url.path}')
            route.abort()
            return
        response = backend.client.open(
            url.path + (f'?{url.query}' if url.query else ''),
            method=request.method, data=request.post_data,
            content_type=request.headers.get('content-type'), buffered=True,
        )
        requests.append({
            'path': url.path, 'status': response.status_code,
            'body': request.post_data_json if request.post_data else None,
        })
        if response.status_code >= 400:
            errors.append(f'Flask rejected {url.path}: {response.get_data(as_text=True)}')
        route.fulfill(
            status=response.status_code, content_type=response.content_type,
            body=response.get_data(),
        )

    page.route('**/*', forward)
    page.on('pageerror', lambda error: errors.append(str(error)))
    try:
        plan = backend.planned(approval_mode='timed')
        seeded = SimpleNamespace(assets=editor_assets, editors={'conv1': {'plan': plan}})
        editor_tests.mount(page, seeded, 'conv1', 'turn1')
        record = backend.runs.read_item(plan['run_id'], 'conv1')
        page.evaluate(
            """(record) => {
                const H = window.OrchHarness;
                H.stores.chat.useChatStore.setState({
                    messages: [{
                        id: record.user_message_id, role: 'user', content: record.user_message,
                        metadata: { orchestration_turn_id: record.turn_id },
                    }],
                });
                H.stores.bootstrap.useBootstrapStore.setState(state => ({
                    data: { ...state.data, user: { id: 'user1', display_name: 'Plan Tester' } },
                }));
            }""",
            {key: record[key] for key in ('user_message_id', 'user_message', 'turn_id')},
        )
        yield page, backend, requests, plan
    finally:
        context.close()
        backend.doCleanups()
        assert not errors, errors


def test_real_editor_add_remove_question_restore_and_run(integrated_editor):
    page, backend, requests, original = integrated_editor
    initial_message_count = len(backend.messages.items)
    dialog = editor_tests.open_editor(page)
    expect(dialog.get_by_role('button', name='Run saved revision')).to_be_enabled()
    held = backend.runs.read_item(original['run_id'], 'conv1')
    assert held['approval']['mode'] == 'manual'
    assert held['started_at'] is None
    expect(page.get_by_role('timer')).to_have_count(0)

    backend.edit_responses.append(backend_tests.revised_plan(searches=2))
    editor_tests.ask(page, 'Add another document search focused on winery prices.')
    editor_tests.wait_revision(page, 1, 'conv1', 'turn1')
    assert len(editor_tests.state(page, 'conv1', 'turn1')['plan']['steps']) == 3

    backend.edit_responses.append(backend_tests.revised_plan('Summarize the available comparison.', searches=0))
    editor_tests.ask(page, 'Remove the searches and summarize the available comparison.')
    editor_tests.wait_revision(page, 2, 'conv1', 'turn1')
    assert len(editor_tests.state(page, 'conv1', 'turn1')['plan']['steps']) == 1

    question = backend_tests.question()
    question['requested_schema']['properties']['day']['enum'] = ['Friday', 'Saturday']
    backend.edit_responses.append(question)
    editor_tests.ask(page, 'Compare winery prices on a different weekday.')
    questions = dialog.get_by_role('region', name='Planner edit questions')
    expect(questions).to_be_visible()
    expect(dialog.get_by_role('button', name='Run saved revision')).to_be_disabled()
    questions.get_by_role('radio', name='Friday', exact=True).check()
    backend.edit_responses.append(backend_tests.revised_plan('Compare winery prices on Friday.', searches=1))
    questions.get_by_role('button', name='Finish', exact=True).click()
    editor_tests.wait_revision(page, 3, 'conv1', 'turn1')
    expect(questions).to_have_count(0)
    answer = next(entry['body'] for entry in requests if entry['body'] and entry['body'].get('action') == 'answer')
    assert answer['elicitation_response']['content']['day'] == 'Friday'

    dialog.get_by_role('tab', name='History', exact=True).click()
    dialog.get_by_role('button', name='Preview revision 0', exact=True).click()
    expect(dialog.get_by_role('button', name='Run saved revision')).to_be_disabled()
    dialog.get_by_role('button', name='Restore revision 0', exact=True).click()
    editor_tests.wait_revision(page, 4, 'conv1', 'turn1')

    task = 'Compare only Friday prices for the wineries near Grants Pass.'
    backend.edit_responses.append(backend_tests.revised_plan(task, searches=1))
    editor_tests.ask(page, task)
    editor_tests.wait_revision(page, 5, 'conv1', 'turn1')
    current = editor_tests.state(page, 'conv1', 'turn1')
    assert len(current['messages']) == 1
    assert not current['mainQuestions'] and not current['thoughts']
    assert len(backend.messages.items) == initial_message_count

    backend.search_queries.clear()
    dialog.get_by_role('button', name='Run saved revision').click()
    expect(dialog).to_have_count(0)
    page.wait_for_function(
        "() => window.OrchHarness.stores.chat.useChatStore.getState().messages.length === 2",
    )
    executions = [entry for entry in requests if entry['path'] == '/api/v2/orchestration/run']
    assert len(executions) == 1
    assert executions[0]['body']['run_id'] == current['plan']['run_id']
    assert executions[0]['body']['expected_version'] == current['plan']['edit_version']
    assert backend.search_queries == [task]
    assert task in json.dumps(backend.model.calls[-1]['messages'])
    saved = backend.runs.read_item(current['plan']['run_id'], 'conv1')
    assert saved['status'] == 'completed'
    assert len(backend.messages.items) == initial_message_count + 1


def test_stale_cancel_does_not_discard_another_tabs_new_question(integrated_editor):
    page, backend, requests, _original = integrated_editor
    dialog = editor_tests.open_editor(page)
    backend.edit_responses.append(backend_tests.question())
    editor_tests.ask(page, 'Compare on another weekday.')
    expect(dialog.get_by_role('region', name='Planner edit questions')).to_be_visible()
    shown = editor_tests.state(page, 'conv1', 'turn1')['editor']['state']
    old_question = shown['pending']

    updated, _body = backend.revise(
        shown, backend_tests.revised_plan('Compare prices on Friday.', searches=1),
        action='answer', elicitation_id=old_question['elicitation_id'],
        elicitation_revision=old_question['revision'],
        elicitation_response={'action': 'accept', 'content': {'day': 'Friday'}},
    )
    question = backend_tests.question()
    question['message'] = 'Which weekday should the newer request cover?'
    newest, _body = backend.revise(updated, question, instruction='Plan another comparison.')

    dialog.get_by_role('button', name='Cancel change', exact=True).click()
    expect(dialog.get_by_role('alert')).to_contain_text('Review the current change')
    assert not [
        entry for entry in requests
        if entry['body'] and entry['body'].get('action') == 'discard'
    ]
    saved = backend.editor(newest['plan']['run_id'])
    assert saved['pending']['elicitation_id'] == newest['pending']['elicitation_id']

    dialog.get_by_role('button', name='Cancel change', exact=True).click()
    expect(dialog.get_by_role('button', name='Run saved revision')).to_be_enabled()
    discard = next(
        entry['body'] for entry in requests
        if entry['body'] and entry['body'].get('action') == 'discard'
    )
    assert discard['expected_version'] == newest['version']
    assert discard['elicitation_id'] == newest['pending']['elicitation_id']
    assert discard['elicitation_id'] != old_question['elicitation_id']
    assert backend.editor(newest['plan']['run_id'])['pending'] is None
