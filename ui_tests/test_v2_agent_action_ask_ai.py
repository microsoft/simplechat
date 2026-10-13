# test_v2_agent_action_ask_ai.py
"""
Offline real-bundle browser regressions for Ask AI in the agent and action editors.
Version: 0.261.329
Implemented in: 0.261.288
SQL draft and debug-diagnostic coverage extended in: 0.261.329

Covers the agent editor applying a proposal to the unsaved draft with Undo, an agent turn that
drafts a new action that blocks saving until the person finishes it in the action editor and is
created only through a save, the action editor keeping
stored credentials out of the request, and both toggles hiding Ask AI when the admin turns it off.

`POST /api/agents/assist` and `POST /api/actions/assist` are answered in the page by the real
`run_editor_assist` pipeline with a scripted model, so no live model or Azure service is contacted.
Reuses the closed My Workspace authoring harness and its local production assets. Run with
PLAYWRIGHT_SERVICE_URL='' after building the V2 bundle.
"""

import copy
import json
import re
import sys
from pathlib import Path

import pytest
from playwright.sync_api import expect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "application" / "single_app"))

from functions_editor_assist import (  # noqa: E402
    ChoiceHandles,
    EditorAssistError,
    EditorAssistServices,
    parse_editor_assist_request,
    run_editor_assist,
)
from functions_assist_diagnostics import AssistDiagnostics  # noqa: E402
from ui_tests.fixtures.workspace_authoring import (  # noqa: E402
    ACTION_ID,
    AGENT_ID,
    CREATED_ACTION_ID,
    OWNER_ID,
    STORED_KEY,
    WorkspaceAuthoringFixture,
    connect_options,  # noqa: F401
)


pytestmark = pytest.mark.ui
ASSIST_PATHS = {"/api/agents/assist": "agent", "/api/actions/assist": "action"}
NEW_DESCRIPTION = "Reviews pull requests for security and style problems."
NEW_ACTION_NAME = "Ticket lookup"


class _Limiter:
    def acquire(self, _user_id):
        return object()

    def release(self, _lease, refund=False):
        return None


class AskAiWorkspaceFixture(WorkspaceAuthoringFixture):
    """The workspace authoring harness with both assist routes answered by the real pipeline."""

    def __init__(self, page):
        super().__init__(page)
        self.agent_assist_enabled = True
        self.action_assist_enabled = True
        self.assist_requests = []
        self.assist_diagnostics = []
        self.script = None

    def _bootstrap(self):
        payload = super()._bootstrap()
        payload["features"]["enable_agent_ai_assistant"] = self.agent_assist_enabled
        payload["features"]["enable_action_ai_assistant"] = self.action_assist_enabled
        return payload

    def _dispatch(self, route, entry):
        kind = ASSIST_PATHS.get(entry.path)
        if kind is None or entry.method != "POST":
            super()._dispatch(route, entry)
            return
        body = copy.deepcopy(entry.body)
        self.assist_requests.append((kind, copy.deepcopy(body)))
        scope = body.pop("scope", "personal")
        body.pop("group_id", None)
        script = self.script

        def call_model(_messages, _timeout):
            request = parse_editor_assist_request(copy.deepcopy(body), kind=kind, scope=scope)
            return json.dumps(script(request, ChoiceHandles(request))), "stop"

        services = EditorAssistServices(limiter=_Limiter(), call_model=call_model,
                                       diagnostics=AssistDiagnostics(self.assist_diagnostics.append))
        try:
            result = run_editor_assist(body, kind=kind, scope=scope, user_id=OWNER_ID, services=services)
        except EditorAssistError as error:
            self._json(route, error.payload(), error.status)
            return
        self._json(route, result)


@pytest.fixture
def ask_ai_ui(page):
    fixture = AskAiWorkspaceFixture(page)
    yield fixture
    fixture.assert_clean()


def ask(page, instruction):
    page.get_by_role("button", name="Ask AI", exact=True).click()
    panel = page.get_by_role("complementary", name="Ask AI", exact=True)
    expect(panel).to_be_visible()
    panel.get_by_role("textbox", name="Message Ask AI", exact=True).fill(instruction)
    panel.get_by_role("button", name="Send to Ask AI", exact=True).click()
    expect(panel.get_by_role("list", name="Changes in this turn")).to_be_visible()
    return panel


def test_agent_ask_ai_applies_to_draft_and_undo_restores_it(ask_ai_ui):
    ui, page = ask_ai_ui, ask_ai_ui.page
    original = ui.agents[AGENT_ID]["description"]
    ui.script = lambda _request, _handles: {
        "reply": "I rewrote the description.",
        "operations": [{"op": "set", "path": "/description", "value": NEW_DESCRIPTION}],
    }
    ui.open(f"/workspace/agents/{AGENT_ID}")
    description = page.get_by_label("Description", exact=True)
    expect(description).to_have_value(original)

    panel = ask(page, "Make the description about pull request reviews.")
    expect(description).to_have_value(NEW_DESCRIPTION)
    expect(panel.get_by_text("I rewrote the description.")).to_be_visible()
    assert not ui.editor_writes, "Ask AI must never save the agent."

    kind, body = ui.assist_requests[-1]
    assert kind == "agent"
    assert body["instruction"] == "Make the description about pull request reviews."
    assert body.get("scope", "personal") == "personal"

    panel.get_by_role("button", name=re.compile(r"^Undo this change")).click()
    expect(description).to_have_value(original)
    assert not ui.editor_writes


def test_agent_ask_ai_drafts_an_action_created_only_on_save(ask_ai_ui):
    ui, page = ask_ai_ui, ask_ai_ui.page

    def script(request, _handles):
        assert request.new_items is not None, "The agent editor must offer new actions."
        assert "fixture_custom" in {option["value"] for option in request.new_items.type_options}
        assert "agent" not in {option["value"] for option in request.new_items.type_options}
        return {
            "reply": "I drafted a ticket lookup action and assigned it.",
            "operations": [{
                "op": "create_item", "handle": "N1", "type": "fixture_custom",
                "values": {"/displayName": NEW_ACTION_NAME, "/description": "Look up support tickets."},
            }],
        }

    ui.script = script
    ui.open(f"/workspace/agents/{AGENT_ID}")
    ask(page, "Add an action that looks up support tickets.")
    pending = page.get_by_role("list", name="New actions from Ask AI", exact=True)
    expect(pending.get_by_role("listitem")).to_have_count(1)
    expect(pending).to_contain_text(NEW_ACTION_NAME)
    expect(pending.get_by_role("button", name=f"Finish {NEW_ACTION_NAME} in the action editor")).to_be_visible()
    expect(pending.get_by_role("button", name=f"Remove new action {NEW_ACTION_NAME}")).to_be_visible()
    expect(pending.get_by_text("Needs attention before saving: Endpoint is required.")).to_be_visible()
    assert not ui.editor_writes, "A drafted action must not be created before the agent is saved."

    # Saving is blocked until the drafted action is complete, and nothing is written.
    page.get_by_role("button", name="Save agent", exact=True).click()
    expect(page.get_by_text(re.compile("Endpoint is required")).first).to_be_visible()
    assert not ui.editor_writes

    # The person finishes it in the action editor, which returns to the agent with it assigned.
    pending.get_by_role("button", name=f"Finish {NEW_ACTION_NAME} in the action editor").click()
    expect(page).to_have_url(re.compile(r"/v2/workspace/actions/new\?"))
    expect(page.get_by_label(re.compile(r"^Action name(?:\s*\*)?\s*$"))).to_have_value(NEW_ACTION_NAME)
    page.get_by_role("navigation", name="Editor sections", exact=True).get_by_role(
        "button", name="Configuration", exact=True
    ).click()
    page.get_by_label(re.compile(r"^Endpoint(?:\s*\*)?\s*$")).fill("https://tickets.example.test/api")
    with page.expect_response(lambda response: response.request.method == "POST"
                              and response.url.endswith("/api/user/plugins?view=editor")) as created:
        page.get_by_role("button", name="Save action", exact=True).click()
    assert created.value.status == 201
    expect(page).to_have_url(re.compile(rf"/v2/workspace/agents/{AGENT_ID}$"))
    expect(page.get_by_role("list", name="New actions from Ask AI", exact=True)).to_have_count(0)
    assert ui.actions[CREATED_ACTION_ID]["displayName"] == NEW_ACTION_NAME
    assert ui.actions[CREATED_ACTION_ID]["type"] == "fixture_custom"

    with page.expect_response(lambda response: response.request.method == "PATCH"
                              and response.url.endswith(f"/api/user/agents/{AGENT_ID}?view=editor")) as saved:
        page.get_by_role("button", name="Save agent", exact=True).click()
    assert saved.value.ok
    assert [(write.method, write.path) for write in ui.editor_writes] == [
        ("POST", "/api/user/plugins"), ("PATCH", f"/api/user/agents/{AGENT_ID}"),
    ]
    assert CREATED_ACTION_ID in ui.agents[AGENT_ID]["actions_to_load"]
    assert not any(str(item).startswith("new:") for item in ui.agents[AGENT_ID]["actions_to_load"])


def test_action_ask_ai_never_sends_stored_credentials(ask_ai_ui):
    ui, page = ask_ai_ui, ask_ai_ui.page
    ui.script = lambda _request, _handles: {
        "reply": "I clarified when agents should call this action.",
        "operations": [{"op": "set", "path": "/description", "value": "List approved workspace items."}],
    }
    ui.open(f"/workspace/actions/{ACTION_ID}")
    ask(page, "Explain when an agent should call this.")
    expect(page.get_by_label("Description", exact=True)).to_have_value("List approved workspace items.")
    assert not ui.editor_writes, "Ask AI must never save the action."

    kind, body = ui.assist_requests[-1]
    assert kind == "action"
    serialized = json.dumps(body)
    assert STORED_KEY not in serialized
    assert '"/auth/key"' not in serialized


@pytest.mark.parametrize('first_defect', [None, 'blank_connection', 'unprefixed_common_fields'])
def test_new_sql_agent_drafts_an_action_without_inventing_connection_details(ask_ai_ui, first_defect):
    ui, page = ask_ai_ui, ask_ai_ui.page
    attempts = []

    def script(request, _handles):
        attempts.append(True)
        assert request.new_items is not None
        assert 'sql_query' in request.new_items.variants
        fields = request.new_items.variants['sql_query']
        assert '/additionalFields/server' in fields
        assert not any('password' in path or 'connection_string' in path for path in fields)
        values = {'/displayName': 'SQL lookup', '/additionalFields/read_only': True}
        if first_defect == 'blank_connection' and len(attempts) == 1:
            values['/additionalFields/server'] = ''
        elif first_defect == 'unprefixed_common_fields' and len(attempts) == 1:
            values['displayName'] = values.pop('/displayName')
            values['description'] = 'Read SQL rows.'
        return {
            'reply': 'I drafted a read-only SQL action. Enter the database details before saving.',
            'operations': [{'op': 'create_item', 'handle': 'N1', 'type': 'sql_query', 'values': values}],
        }

    ui.script = script
    ui.open('/workspace/agents/new')
    panel = ask(page, 'i want to connect to a sql database')
    pending = page.get_by_role('list', name='New actions from Ask AI', exact=True)
    expect(pending).to_contain_text('SQL lookup')
    expect(pending.get_by_text(re.compile('Needs attention before saving'))).to_be_visible()
    assert not ui.editor_writes
    assert len(attempts) == (2 if first_defect else 1)
    rejected = [event for event in ui.assist_diagnostics if event['assist_event'] == 'validation_rejected']
    if first_defect == 'blank_connection':
        assert len(rejected) == 1
        assert rejected[0]['assist_rule'] == 'required_value'
        assert rejected[0]['assist_field'] == '/additionalFields/server'
    elif first_defect == 'unprefixed_common_fields':
        assert [event['assist_rule'] for event in rejected] == [
            'new_field_unknown', 'new_field_unknown', 'new_required_field',
        ]
    else:
        assert rejected == []
    panel.get_by_role('button', name=re.compile(r'^Undo this change')).click()
    expect(page.get_by_role('list', name='New actions from Ask AI', exact=True)).to_have_count(0)
    assert not ui.editor_writes


def test_failed_new_sql_agent_turn_keeps_the_draft_and_records_the_rule(ask_ai_ui):
    ui, page = ask_ai_ui, ask_ai_ui.page
    ui.script = lambda _request, _handles: {
        'reply': 'I configured SQL.',
        'operations': [{'op': 'create_item', 'handle': 'N1', 'type': 'sql_query', 'values': {}}],
    }
    ui.open('/workspace/agents/new')
    original = page.get_by_label('Display name', exact=True).input_value()
    page.get_by_role('button', name='Ask AI', exact=True).click()
    panel = page.get_by_role('complementary', name='Ask AI', exact=True)
    panel.get_by_role('textbox', name='Message Ask AI', exact=True).fill('i want to connect to a sql database')
    panel.get_by_role('button', name='Send to Ask AI', exact=True).click()
    expect(panel.get_by_text(re.compile("couldn't produce a valid change"))).to_be_visible()
    expect(page.get_by_label('Display name', exact=True)).to_have_value(original)
    expect(page.get_by_role('list', name='New actions from Ask AI', exact=True)).to_have_count(0)
    assert not ui.editor_writes
    rejected = [event for event in ui.assist_diagnostics if event['assist_event'] == 'validation_rejected']
    assert [event['attempt'] for event in rejected] == [1, 2]
    assert all(event['assist_rule'] == 'new_required_field' for event in rejected)


def test_new_sql_agent_can_assign_an_existing_action_without_running_it(ask_ai_ui):
    ui, page = ask_ai_ui, ask_ai_ui.page
    ui.actions[ACTION_ID].update({
        "displayName": "SQL lookup", "type": "sql_query",
        "additionalFields": {"server": "sql.example.test", "database": "fixture", "read_only": True},
    })

    def script(request, handles):
        assert any(option["value"] == ACTION_ID for option in request.fields["/actions"].options)
        handle = handles.handle("/actions", ACTION_ID)
        assert handle is not None
        return {
            "reply": "I assigned the existing SQL lookup action.",
            "operations": [{"op": "set", "path": "/actions", "value": [handle]}],
        }

    ui.script = script
    ui.open("/workspace/agents/new")
    panel = ask(page, "i want to connect to a sql database")
    expect(page.get_by_role("checkbox", name=re.compile("SQL lookup")).first).to_be_checked()
    assert not ui.editor_writes
    expect(page.get_by_role("list", name="New actions from Ask AI", exact=True)).to_have_count(0)
    panel.get_by_role("button", name=re.compile(r"^Undo this change")).click()
    expect(page.get_by_role("checkbox", name=re.compile("SQL lookup")).first).not_to_be_checked()
    assert not ui.editor_writes


def test_new_sql_agent_can_ask_for_connection_details_without_mutation(ask_ai_ui):
    ui, page = ask_ai_ui, ask_ai_ui.page
    question = "Which SQL database engine will you use? Enter its connection details in the action editor."
    ui.script = lambda _request, _handles: {"reply": question, "operations": []}
    ui.open("/workspace/agents/new")
    original = page.get_by_label("Display name", exact=True).input_value()
    page.get_by_role("button", name="Ask AI", exact=True).click()
    panel = page.get_by_role("complementary", name="Ask AI", exact=True)
    panel.get_by_role("textbox", name="Message Ask AI", exact=True).fill("i want to connect to a sql database")
    panel.get_by_role("button", name="Send to Ask AI", exact=True).click()
    expect(panel.get_by_text(question, exact=True)).to_be_visible()
    expect(page.get_by_label("Display name", exact=True)).to_have_value(original)
    expect(page.get_by_role("list", name="New actions from Ask AI", exact=True)).to_have_count(0)
    assert not ui.editor_writes
    assert ui.assist_diagnostics[-1]["assist_outcome"] == "explained"


@pytest.mark.parametrize("path", [f"/workspace/agents/{AGENT_ID}", f"/workspace/actions/{ACTION_ID}"])
def test_ask_ai_is_hidden_when_the_admin_turns_it_off(ask_ai_ui, path):
    ui, page = ask_ai_ui, ask_ai_ui.page
    ui.agent_assist_enabled = False
    ui.action_assist_enabled = False
    ui.open(path)
    expect(page.get_by_label("Description", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Ask AI", exact=True)).to_have_count(0)
    assert not ui.assist_requests
