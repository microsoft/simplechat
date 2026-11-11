# test_agent_credential_reentry.py
"""Agent credential recovery notices and explicit replacement.

Version: 0.261.434
Implemented in: 0.261.428
Permission-aware chat recovery links implemented in: 0.261.429
Recovery button and in-button guidance implemented in: 0.261.430
Guided recovery implemented in: 0.261.431
Fixture import consistency reviewed in: 0.261.434

Uses the production SPA and existing Azure Playwright/local-browser fixture.
All application responses and credentials are synthetic.
"""

from pathlib import Path
import json
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

import ui_tests.fixtures.workspace_authoring as authoring_fixture
from ui_tests.test_v2_workspace_authoring import editor_section, save_resource


connect_options = authoring_fixture.connect_options
workspace_ui = authoring_fixture.workspace_ui

pytestmark = pytest.mark.ui
AGENT_ID = authoring_fixture.AGENT_ID
ORIGIN = authoring_fixture.ORIGIN
STORED_KEY = authoring_fixture.STORED_KEY


@pytest.mark.parametrize("theme,width,height", [
    ("light", 1440, 900),
    ("dark", 390, 844),
])
def test_agent_owner_can_identify_and_replace_a_legacy_credential(workspace_ui, monkeypatch, theme, width, height):
    ui = workspace_ui
    ui.agents[AGENT_ID].update({
        "model_endpoint_id": "", "model_id": "", "model_provider": "",
        "azure_openai_gpt_endpoint": "https://owned.example.test",
        "azure_openai_gpt_key": STORED_KEY,
        "azure_openai_gpt_api_version": "2024-02-01",
    })
    ui.secret_paths[AGENT_ID] = ["/azure_openai_gpt_key"]
    original_envelope = ui.envelope

    def envelope(record):
        resource = original_envelope(record)
        resource["credential_reentry_required"] = (
            [{"path": "/azure_openai_gpt_key", "label": "Azure OpenAI API key"}]
            if record["id"] == AGENT_ID and record.get("azure_openai_gpt_key") == STORED_KEY else []
        )
        return resource

    monkeypatch.setattr(ui, "envelope", envelope)
    ui.open(f"/workspace/agents/{AGENT_ID}", theme=theme, width=width, height=height)
    notice = ui.page.get_by_role("status").filter(has_text="Agent credentials need updating")
    expect(notice).to_be_visible()
    expect(notice).to_contain_text("Azure OpenAI API key")
    ui.page.get_by_role("button", name="Update credentials", exact=True).click()
    editor_section(ui.page, "Model & connection")
    intent = ui.page.get_by_label("Azure OpenAI API key", exact=True)
    expect(intent).to_have_value("replace")
    expect(intent.get_by_role("option", name="Keep saved value")).to_have_count(0)
    replacement = ui.page.get_by_label("Replacement azure openai api key", exact=True)
    expect(replacement).to_have_value("")
    replacement.fill("synthetic-new-agent-credential")
    result = save_resource(ui, "agent", identifier=AGENT_ID)
    assert result.ok
    assert ui.editor_writes[-1].body["updates"]["azure_openai_gpt_key"] == "synthetic-new-agent-credential"
    assert "credential_reentry_required" not in ui.editor_writes[-1].body["updates"]
    ui.assert_no_secret_storage("synthetic-new-agent-credential")
    ui.open(f"/workspace/agents/{AGENT_ID}", theme=theme, width=width, height=height)
    expect(ui.page.get_by_text("Agent credentials need updating", exact=True)).to_have_count(0)


def test_reentry_notice_does_not_disappear_for_an_unrelated_edit(workspace_ui, monkeypatch):
    ui = workspace_ui
    original_envelope = ui.envelope

    def envelope(record):
        resource = original_envelope(record)
        if record["id"] == AGENT_ID:
            resource["credential_reentry_required"] = [{
                "path": "/other_settings/new_foundry/client_secret", "label": "New Foundry client secret",
            }]
        return resource

    monkeypatch.setattr(ui, "envelope", envelope)
    ui.open(f"/workspace/agents/{AGENT_ID}")
    expect(ui.page.get_by_text("Agent credentials need updating", exact=True)).to_be_visible()
    ui.page.get_by_label("Display name", exact=True).fill("Renamed agent")
    result = save_resource(ui, "agent", identifier=AGENT_ID)
    assert result.ok
    ui.open(f"/workspace/agents/{AGENT_ID}")
    expect(ui.page.get_by_text("Agent credentials need updating", exact=True)).to_be_visible()


def test_classic_reentry_notice_uses_inert_labels_and_empty_replacement_fields(page):
    static = Path(__file__).resolve().parents[1] / "application" / "single_app" / "static"
    unexpected = []

    def serve(route):
        path = urlsplit(route.request.url).path
        if path == "/classic-credential-fixture":
            route.fulfill(content_type="text/html", body=(
                '<!doctype html><html lang="en"><body>'
                '<div id="agent-credential-reentry-notice" class="alert d-none" role="status"></div>'
                '<label for="agent-gpt-key">Azure OpenAI API key</label>'
                '<input id="agent-gpt-key" value="Stored_In_KeyVault">'
                '</body></html>'
            ))
        elif path.startswith("/static/"):
            target = static.joinpath(*path[len("/static/"):].split("/")).resolve()
            if target.is_relative_to(static.resolve()) and target.is_file():
                route.fulfill(path=str(target), content_type="application/javascript")
            else:
                unexpected.append(path)
                route.abort()
        elif path == "/favicon.ico":
            route.fulfill(status=204)
        else:
            unexpected.append(path)
            route.abort()

    page.route(f"{ORIGIN}/**", serve)
    page.goto(f"{ORIGIN}/classic-credential-fixture")
    page.evaluate("""async () => {
        const { AgentModalStepper } = await import('/static/js/agent_modal_stepper.js');
        window.credentialStepper = Object.create(AgentModalStepper.prototype);
        window.credentialStepper.showCredentialReentryNotice({
            credential_reentry_required: [
                { path: '/azure_openai_gpt_key', label: 'Azure OpenAI API key <img src=x>' },
                { path: '/other_settings/new_foundry/client_secret', label: 'New Foundry client secret' }
            ]
        });
    }""")
    notice = page.get_by_role("status")
    expect(notice).to_contain_text("Agent credentials need updating")
    expect(notice).to_contain_text("<img src=x>")
    expect(notice.locator("img")).to_have_count(0)
    expect(page.get_by_label("Azure OpenAI API key", exact=True)).to_have_value("")
    expect(page.get_by_label("Re-enter New Foundry client secret", exact=True)).to_have_attribute("type", "password")
    page.evaluate("window.credentialStepper.showCredentialReentryNotice(null)")
    assert "d-none" in notice.get_attribute("class").split()
    assert not unexpected
    writes = []

    def agents_api(route):
        if route.request.method == "GET":
            route.fulfill(json=[{
                "id": "agent-a", "name": "agent_a", "azure_openai_gpt_key": "Stored_In_KeyVault",
                "credential_reentry_required": [{"path": "/azure_openai_gpt_key", "label": "Azure OpenAI API key"}],
            }, {"id": "agent-b", "name": "unchanged_agent"}])
        else:
            writes.append(route.request.post_data_json)
            route.fulfill(json={"success": True})

    page.route(f"{ORIGIN}/api/user/agents", agents_api)
    page.evaluate("""async () => {
        const editor = window.credentialStepper;
        editor.isEditMode = true;
        editor.originalAgent = { id: 'agent-a' };
        editor.handleSaveSuccess = () => {};
        await editor.savePersonalAgent({ id: 'agent-a', name: 'agent_a', description: 'Unrelated edit' });
    }""")
    assert len(writes) == 1
    assert writes[0][0]["azure_openai_gpt_key"] == "Stored_In_KeyVault"
    assert writes[0][1]["id"] == "agent-b"


def test_foundry_reentry_preserves_service_principal_during_other_edits(workspace_ui, monkeypatch):
    ui = workspace_ui
    ui.agents[AGENT_ID].update({
        "agent_type": "new_foundry", "actions_to_load": [],
        "model_endpoint_id": "", "model_id": "", "model_provider": "new_foundry",
        "azure_openai_gpt_endpoint": "https://approved.example.test/api/projects/review",
        "azure_openai_gpt_api_version": "2025-11-15-preview",
        "other_settings": {"new_foundry": {
            "application_id": "sample-application",
            "endpoint": "https://approved.example.test/api/projects/review",
            "responses_api_version": "2025-11-15-preview",
            "authentication_type": "service_principal",
            "tenant_id": "sample-tenant", "client_id": "sample-client", "client_secret": STORED_KEY,
        }},
    })
    ui.secret_paths[AGENT_ID] = ["/other_settings/new_foundry/client_secret"]
    original = ui.envelope

    def envelope(record):
        resource = original(record)
        resource["credential_reentry_required"] = [{
            "path": "/other_settings/new_foundry/client_secret", "label": "New Foundry client secret",
        }]
        return resource

    monkeypatch.setattr(ui, "envelope", envelope)
    ui.open(f"/workspace/agents/{AGENT_ID}")
    editor_section(ui.page, "Model & connection")
    ui.page.get_by_label("Foundry notes", exact=True).fill("Updated notes")
    replacement = ui.page.get_by_label("Replacement foundry client secret", exact=True)
    expect(replacement).to_be_visible()
    replacement.fill("synthetic-new-foundry-secret")
    result = save_resource(ui, "agent", identifier=AGENT_ID)
    assert result.ok
    current = ui.agents[AGENT_ID]["other_settings"]["new_foundry"]
    assert current["authentication_type"] == "service_principal"
    assert current["client_secret"] == "synthetic-new-foundry-secret"
    ui.assert_no_secret_storage("synthetic-new-foundry-secret")


def _chat_failure(
    ui, monkeypatch, recovery, message, *, transport="sse", width=1440,
    agent_id=AGENT_ID, agent_scope="personal",
):
    monkeypatch.setattr(authoring_fixture, "ORIGIN", "http://localhost")
    ui.page.route("**/api/action-recovery/context", lambda route: route.fulfill(json={"csrf_token": "synthetic-test"}))
    ui.page.route("**/api/chat/action-health", lambda route: route.fulfill(json={"state": "ready"}))
    ui.page.route("**/api/action-credentials/pending*", lambda route: route.fulfill(json={"requests": [], "csrf_token": "synthetic-test"}))
    ui.page.route("**/api/v2/user-input/pending*", lambda route: route.fulfill(json={"requests": [], "csrf_token": "synthetic-test"}))
    ui.page.route("**/api/v2/orchestration/questions*", lambda route: route.fulfill(json={"questions": [], "csrf_token": "synthetic-test"}))
    requests = []

    def blocked(route):
        body = route.request.post_data_json
        requests.append(body)
        ui.messages[body["conversation_id"]].append({
            "id": "blocked-question", "role": "user", "content": body["message"],
            "conversation_id": body["conversation_id"],
        })
        payload = {
            "error": message, "error_code": "model_configuration_invalid",
            "agent_credential_recovery": recovery,
        }
        if transport == "json":
            ui.expected_http_errors.add((route.request.url, 400))
            route.fulfill(status=400, json=payload)
        else:
            route.fulfill(content_type="text/event-stream", body=f"data: {json.dumps({**payload, 'done': True})}\n\n")

    ui.page.route("**/api/chat/stream", blocked)
    ui.open(f"/chat?agent_id={agent_id}&agent_scope={agent_scope}&new=1",
            theme="dark" if width < 600 else "light", width=width, height=900)
    ui.page.get_by_role("textbox", name="Message").fill("Summarize the policy changes.")
    ui.page.get_by_role("button", name="Send message", exact=True).click()
    notice = ui.page.get_by_role("alert").filter(has_text=message.split(". ", 1)[0].rstrip("."))
    expect(notice).to_be_visible()
    return notice, requests


@pytest.mark.parametrize("transport,width", [("sse", 1440), ("json", 390)])
def test_chat_owner_button_opens_exact_agent_connection_in_new_tab(workspace_ui, monkeypatch, transport, width):
    ui = workspace_ui
    edit_url = f"/v2/workspace/agents/{AGENT_ID}?section=model"
    notice, requests = _chat_failure(ui, monkeypatch, {
        "scope": "personal", "can_edit": True, "edit_url": edit_url,
    }, "Agent credentials need updating. Update this agent's Model & connection settings.",
        transport=transport, width=width)
    button = notice.get_by_role("button", name="Update agent credentials", exact=False)
    expect(button).to_have_attribute("type", "button")
    steps = notice.get_by_role("list", name="Agent credential recovery").get_by_role("listitem")
    expect(steps).to_have_count(2)
    expect(steps.nth(0)).to_contain_text("Update the connection")
    expect(steps.nth(1)).to_contain_text("Return to this chat")
    expect(steps.nth(1)).to_contain_text("After saving, select Retry on your message, or start a new conversation.")
    expect(notice).to_contain_text("Nothing retries automatically")
    expect(button).to_have_accessible_description(
        "The agent editor opens in a new tab. After saving, select Retry on your message, or start a new conversation."
    )
    expect(notice.get_by_role("link")).to_have_count(0)
    chat_url = ui.page.url
    with ui.page.expect_popup() as opened:
        if width > 600:
            button.focus()
            button.press("Enter")
        else:
            button.click()
    editor = opened.value
    expect(editor).to_have_url(f"http://localhost{edit_url}")
    expect(editor.get_by_label("Model", exact=True)).to_be_visible()
    opener = editor.evaluate("window.opener")
    assert opener is None
    assert ui.page.url == chat_url
    assert len(requests) == 1
    ui.assert_no_overflow()
    thread = ui.page.locator('[data-tour="message-list"] > div').bounding_box()
    composer = ui.page.get_by_role("textbox", name="Message").evaluate(
        "node => node.closest('.mx-auto').getBoundingClientRect().width"
    )
    assert thread["width"] <= 721
    assert abs(composer - thread["width"]) <= 1
    first, second = steps.nth(0).bounding_box(), steps.nth(1).bounding_box()
    if width > 600:
        assert abs(first["y"] - second["y"]) <= 1
    else:
        assert second["y"] >= first["y"] + first["height"]
    editor.close()


@pytest.mark.parametrize("scope,contact", [("group", "a group owner"), ("global", "a site administrator")])
def test_chat_noneditor_gets_scope_specific_contact_not_a_link(workspace_ui, monkeypatch, scope, contact):
    ui = workspace_ui
    message = f"Agent credentials need updating. Please contact {contact} to update this agent."
    notice, requests = _chat_failure(ui, monkeypatch, {"scope": scope, "can_edit": False}, message)
    expect(notice).to_contain_text(contact)
    expect(notice.get_by_role("link")).to_have_count(0)
    expect(notice.get_by_role("button", name="Update agent credentials", exact=False)).to_have_count(0)
    expect(notice.get_by_role("list", name="Agent credential recovery").get_by_role("listitem")).to_have_count(2)
    expect(notice).to_contain_text("Request an update")
    assert len(requests) == 1


@pytest.mark.parametrize("scope,url,can_edit", [
    ("personal", "javascript:alert(1)", True),
    ("personal", "//external.example/agent", True),
    ("personal", "/v2/workspace/agents/../settings?section=model", True),
    ("personal", "/v2/workspace/agents/%2e%2e?section=model", True),
    ("personal", "/v2/workspace/agents/%2Fexternal?section=model", True),
    ("personal", "/v2/workspace/agents/%ZZ?section=model", True),
    ("personal", "/v2/admin/agents/agent-a?section=model", True),
    ("personal", "/v2/workspace/agents/agent-a?section=model&redirect=external", True),
    ("global", "/v2/admin/agents/agent-a?section=model", False),
])
def test_chat_recovery_never_promotes_an_unsafe_or_unpermitted_url(workspace_ui, monkeypatch, scope, url, can_edit):
    notice, _requests = _chat_failure(workspace_ui, monkeypatch, {
        "scope": scope, "can_edit": can_edit, "edit_url": url,
    }, "Agent credentials need updating.")
    expect(notice.get_by_role("link")).to_have_count(0)
    expect(notice.get_by_role("button", name="Update agent credentials", exact=False)).to_have_count(0)


@pytest.mark.parametrize("scope,url,can_edit,expected", [
    ("personal", "/v2/workspace/agents/agent-a?section=model", True, True),
    ("group", "/v2/groups/group-a/agents/agent-a?section=model", True, True),
    ("global", "/v2/admin/agents/agent-a?section=model", True, True),
    ("group", "/v2/groups/group-a/agents/agent-a?section=model", False, False),
    ("global", "//external.example/agent", True, False),
    ("personal", "javascript:alert(1)", True, False),
    ("personal", "/v2/workspace/agents/%2e%2e?section=model", True, False),
    ("personal", "/v2/workspace/agents/%2fexternal?section=model", True, False),
    ("personal", "/v2/workspace/agents/%ZZ?section=model", True, False),
])
def test_classic_chat_recovery_uses_real_inert_dom_renderer(page, scope, url, can_edit, expected):
    source = (
        Path(__file__).resolve().parents[1] / "application" / "single_app" / "static" / "js" / "chat" / "chat-streaming.js"
    ).read_text(encoding="utf-8-sig")
    # These real rendering functions have no module-initialization dependencies.
    functions = source[source.index("function normalizeStreamErrorMessage("):source.index("function reportClientStreamEvent(")]
    page.route(f"{ORIGIN}/classic-recovery", lambda route: route.fulfill(
        content_type="text/html", body='<!doctype html><html lang="en"><body><main></main></body></html>',
    ))
    page.context.route(f"{ORIGIN}/v2/**", lambda route: route.fulfill(
        content_type="text/html", body='<!doctype html><html lang="en"><body><h1>Agent editor fixture</h1></body></html>',
    ))
    page.context.route(f"{ORIGIN}/favicon.ico", lambda route: route.fulfill(status=204))
    page.goto(f"{ORIGIN}/classic-recovery")
    page.add_script_tag(content=functions)
    page.evaluate("""({scope, url, canEdit}) => appendStreamErrorBanner(document.querySelector('main'),
        'Agent credentials need updating. <img src=x onerror=alert(1)>', {
            streamErrorData: {agent_credential_recovery: {scope, can_edit: canEdit, edit_url: url}}
        })""", {"scope": scope, "url": url, "canEdit": can_edit})
    notice = page.get_by_role("alert")
    expect(notice).to_contain_text("<img src=x")
    expect(notice.locator("img")).to_have_count(0)
    button = notice.get_by_role("button", name="Update agent credentials", exact=False)
    expect(notice.get_by_role("link")).to_have_count(0)
    expect(button).to_have_count(1 if expected else 0)
    if expected:
        expect(notice.get_by_role("list", name="Agent credential recovery").get_by_role("listitem")).to_have_count(2)
        expect(notice).to_contain_text("select Retry on your message, or start a new conversation")
        expect(notice).to_contain_text("Nothing retries automatically")
        with page.expect_popup() as opened:
            button.focus()
            button.press("Enter")
        editor = opened.value
        expect(editor).to_have_url(f"{ORIGIN}{url}")
        opener = editor.evaluate("window.opener")
        assert opener is None
        editor.close()
    elif can_edit is False and scope in ("personal", "group", "global"):
        expect(notice).to_contain_text("Request an update")
        expect(notice).to_contain_text("Nothing retries automatically")
    else:
        expect(notice).to_contain_text("It will not retry automatically")


def test_guided_recovery_preserves_explicit_wide_preference(workspace_ui, monkeypatch):
    ui = workspace_ui
    ui.page.add_init_script("localStorage.setItem('simplechat.v2.chat-width', 'wide')")
    notice, _requests = _chat_failure(ui, monkeypatch, {
        "scope": "personal", "can_edit": True,
        "edit_url": f"/v2/workspace/agents/{AGENT_ID}?section=model",
    }, "Agent credentials need updating.")
    expect(notice.get_by_role("list", name="Agent credential recovery")).to_be_visible()
    thread = ui.page.locator('[data-tour="message-list"] > div').bounding_box()
    composer = ui.page.get_by_role("textbox", name="Message").evaluate(
        "node => node.closest('.mx-auto').getBoundingClientRect().width"
    )
    assert thread["width"] > 720
    assert abs(thread["width"] - composer) <= 1
