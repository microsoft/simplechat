# test_v2_prompt_composer_experience.py
"""
Focused browser regressions for the approved V2 prompt composer experience.
Version: 0.261.099
Implemented in: 0.261.096

The existing harness bundles the real Composer, MessageList, editors, and stores.
Only HTTP boundaries are mocked. Canonical messages use the real Python metadata
builder and the captured outgoing request, never a fabricated browser attachment.
Backend persistence/authorization lifecycles have their own functional tests.

Use local Chromium or configure Azure
Playwright through PLAYWRIGHT_SERVICE_URL and PLAYWRIGHT_WORKSPACE_RESOURCE_ID.
The existing connect_options fixture uses DefaultAzureCredential and
azure-mgmt-playwright. No credentials, resource creation, or live model calls are
needed locally. Missing dependencies/build assets fail instead of being skipped.
The module-scoped browser and per-test contexts coexist with the existing harness
fixtures when these suites run together in one pytest invocation.

Run: python -m pytest .\\ui_tests\\test_v2_prompt_composer_experience.py -q
"""

import copy
import importlib.util
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import Route, expect, sync_playwright

# Reuse the repository's real-component build, Azure connection, and context picker.
REPO_ROOT = Path(__file__).resolve().parents[1]
UI_ROOT = REPO_ROOT / "ui_tests"
STATIC_ROOT = REPO_ROOT / "application" / "single_app" / "static"
sys.path.insert(0, str(UI_ROOT))
sys.path.insert(0, str(UI_ROOT / "fixtures"))
sys.path.insert(0, str(UI_ROOT / "fixtures" / "orchestration"))
sys.path.insert(0, str(REPO_ROOT / "application" / "single_app"))

import harness_build as hb  # noqa: E402
from functions_prompt_metadata import build_prompt_selection_metadata  # noqa: E402
from test_v2_chat_context_selection import ContextApi, open_picker, pick_context  # noqa: E402
from v2_admin_settings import connect_options  # noqa: E402, F401


pytestmark = pytest.mark.ui

ORIGIN = "https://simplechat.test"
HARNESS_PATH = f"/{hb.HARNESS_HTML_REL}"
BUNDLE_PATH = "/ui_tests/fixtures/orchestration/harness.bundle.js"
CONVERSATION_ID = "prompt-experience-chat"
FILL_PATH = "/api/v2/prompts/fill-variables"
SEND_PATHS = {"chat": "/api/chat/stream", "plan": "/api/v2/orchestration/plan"}
RUN_PATH = "/api/v2/orchestration/run"
MEMORY_KEY = "simplechat.v2.prompt-vars"
PROMPT_HINT = "Tip: type / in your message to choose a prompt."
MODEL = {
    "selection_key": "personal::fixture-endpoint:fixture-model",
    "id": "fixture-model",
    "endpoint_id": "fixture-endpoint",
    "deployment_name": "gpt-4o",
    "display_name": "Fixture model",
    "provider": "azure_openai",
}
SOURCE = {
    "document_id": "personal-brief",
    "chunk_id": "brief-page-3",
    "title": "Quarterly brief",
    "page_number": 3,
    "excerpt": "Acme's account owner is Alex. The review is due on Friday.",
}


def prompt(content="Write to {{customer}} about {{topic}}.", *, name="Weekly brief", **extra):
    return {
        "id": "weekly",
        "name": name,
        "content": content,
        "description": "A reusable customer brief",
        "scope_type": "personal",
        "scope_name": "My workspace",
        **extra,
    }


def filled(key, value, *, source=None):
    return {"key": key, "value": value, "sources": [copy.deepcopy(source or SOURCE)]}


def normalize_captured_fill(payload):
    """Validate the real browser request with the backend's isolated service fixture."""
    fixture_path = REPO_ROOT / "functional_tests" / "test_prompt_variable_knowledge_fill.py"
    spec = importlib.util.spec_from_file_location("_prompt_fill_contract_fixture", fixture_path)
    fixture_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture_module)
    service, _client = fixture_module.load_service()
    return service.normalize_fill_request(payload)


class PromptApi:
    """Closed HTTP fixture with explicit gates for optimistic and stale-response checks."""

    def __init__(self, assets):
        self.assets = assets
        self.context = ContextApi()
        self.requests = []
        self.unexpected = []
        self.fills = []
        self.sends = []
        self.runs = []
        self.pending_fills = []
        self.pending_sends = []
        self.hold_fills = False
        self.hold_sends = False
        self.fill_response = {"values": [], "unresolved": []}
        self.fill_status = 200
        self.expected_http_errors = set()
        self.messages = {}
        self.bootstrap = None
        self.plans = {}
        self.tag_names = {}

    def handle(self, route: Route):
        request = route.request
        url = urlsplit(request.url)
        path = url.path
        if f"{url.scheme}://{url.netloc}" != ORIGIN:
            self.unexpected.append(request.url)
            route.abort()
            return
        if request.method == "GET" and path in self.assets:
            route.fulfill(path=str(self.assets[path]))
            return
        if path == "/favicon.ico":
            route.fulfill(status=204)
            return

        self.requests.append((request.method, path))
        if request.method == "POST" and path == FILL_PATH:
            self.fills.append(copy.deepcopy(request.post_data_json))
            if self.hold_fills:
                self.pending_fills.append(route)
            else:
                self.fulfill_fill(route)
            return
        if request.method == "POST" and path in SEND_PATHS.values():
            body = copy.deepcopy(request.post_data_json)
            self.sends.append(body)
            if path == SEND_PATHS["plan"]:
                self.plans["prompt-run"] = body
            if self.hold_sends:
                self.pending_sends.append((route, body))
            else:
                self.fulfill_send(route, body)
            return
        if request.method == "POST" and path == RUN_PATH:
            self.runs.append(copy.deepcopy(request.post_data_json))
            body = self.plans[request.post_data_json["run_id"]]
            user = self.persist(body)
            self.stream(route, [
                {"content": "A grounded fixture answer."},
                {"done": True, "message_id": "assistant-canonical", "user_message_id": user["id"]},
            ])
            return
        if request.method == "GET" and path == "/api/get_messages":
            conversation_id = parse_qs(url.query)["conversation_id"][0]
            route.fulfill(json={"messages": self.messages.get(conversation_id, [])})
            return
        if request.method == "GET" and path == "/api/conversations/feed":
            route.fulfill(json={"conversations": [], "has_more": False})
            return
        if request.method == "GET" and path == "/api/v2/bootstrap":
            route.fulfill(json=self.bootstrap)
            return
        if path == "/api/user/settings":
            route.fulfill(json={"settings": {}})
            return
        if request.method == "POST" and re.fullmatch(
            r"/api/collaboration/conversations/[^/]+/typing", path
        ):
            route.fulfill(json={"success": True})
            return
        if request.method == "GET" and path in self.tag_names:
            route.fulfill(json={"tags": [{"name": name} for name in self.tag_names[path]]})
            return
        if request.method == "GET" and path.startswith((
            "/api/documents", "/api/group_documents", "/api/public_workspace_documents"
        )):
            self.context.handle(route)
            return
        self.unexpected.append(f"{request.method} {path}")
        route.fulfill(status=404, json={"error": "Unexpected prompt fixture request."})

    @staticmethod
    def stream(route, frames):
        route.fulfill(
            content_type="text/event-stream",
            body="".join(f"data: {json.dumps(frame)}\n\n" for frame in frames),
        )

    def persist(self, body):
        """Use the production contract builder over the real request, not UI-created metadata."""
        metadata = {}
        if body.get("prompt_info"):
            selection = build_prompt_selection_metadata(body["prompt_info"], body["message"])
            assert selection is not None, f"Outgoing prompt snapshot was rejected: {body}"
            metadata["prompt_selection"] = selection
        if body.get("turn_id"):
            metadata["orchestration_turn_id"] = body["turn_id"]
        user = {
            "id": f"user-canonical-{len(self.sends)}",
            "conversation_id": body["conversation_id"],
            "role": "user",
            "content": body["message"],
            "timestamp": "2026-09-05T12:00:00Z",
            "metadata": metadata,
        }
        self.messages.setdefault(body["conversation_id"], []).append(user)
        return user

    def fulfill_send(self, route, body):
        if urlsplit(route.request.url).path == SEND_PATHS["chat"]:
            user = self.persist(body)
            self.stream(route, [
                {"type": "user_message_persisted", "user_message_id": user["id"]},
                {"response": "A grounded fixture answer."},
                {"done": True, "message_id": "assistant-canonical"},
            ])
            return
        self.stream(route, [{
            "type": "orchestration_plan",
            "plan": {
                "plan_id": "prompt-plan",
                "run_id": "prompt-run",
                "turn_id": body["turn_id"],
                "intent": {"summary": "Use the attached prompt", "complexity": "simple"},
                "steps": [{
                    "step_id": "answer",
                    "capability_id": "respond",
                    "title": "Answer",
                    "arguments": {},
                    "estimated_cost": "low",
                }],
                "approval": {"mode": "manual", "timeout_seconds": 0, "state": "pending"},
                "status": "awaiting_approval",
            },
        }])

    def fulfill_fill(self, route):
        if self.fill_status >= 400:
            self.expected_http_errors.add((FILL_PATH, self.fill_status))
        route.fulfill(status=self.fill_status, json=self.fill_response)

    def release_fills(self):
        pending, self.pending_fills = self.pending_fills, []
        for route in pending:
            self.fulfill_fill(route)

    def release_sends(self):
        pending, self.pending_sends = self.pending_sends, []
        for route, body in pending:
            self.fulfill_send(route, body)


@pytest.fixture(scope="module")
def prompt_assets():
    """Build real JS and serve the real production CSS, including on an Azure browser."""
    bundle = hb.ensure_bundle()
    index = STATIC_ROOT / "v2" / "index.html"
    assert index.is_file(), (
        "Prompt layout tests need the V2 production CSS. Run the existing V2 npm run build."
    )
    stylesheet_urls = re.findall(r'<link\b[^>]*href="([^"]+\.css)"', index.read_text("utf-8"))
    assert stylesheet_urls, "The production V2 index must reference a local stylesheet."
    assets = {HARNESS_PATH: hb.HERE / "harness.html", BUNDLE_PATH: bundle}
    for url in stylesheet_urls:
        parsed = urlsplit(url)
        assert not parsed.netloc and parsed.path.startswith("/static/")
        asset = (STATIC_ROOT / parsed.path.removeprefix("/static/")).resolve()
        assert asset.is_relative_to(STATIC_ROOT.resolve()) and asset.is_file()
        assets[parsed.path] = asset
    return assets


@pytest.fixture(scope="module")
def prompt_browser(connect_options):
    with sync_playwright() as playwright:
        browser = (
            playwright.chromium.connect(**connect_options)
            if connect_options else playwright.chromium.launch()
        )
        try:
            yield browser
        finally:
            browser.close()


@pytest.fixture
def prompt_ui(prompt_browser, prompt_assets):
    context = prompt_browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    api = PromptApi(prompt_assets)
    errors = []
    page.route("**/*", api.handle)
    page.on("pageerror", lambda error: errors.append(str(error)))

    def console_error(message):
        if message.type != "error":
            return
        path = urlsplit(message.location.get("url", "")).path
        if any(
            path == expected_path and f"status of {status}" in message.text
            for expected_path, status in api.expected_http_errors
        ):
            return
        errors.append(message.text)

    page.on("console", console_error)
    try:
        yield page, api
    finally:
        try:
            if not page.is_closed():
                page.evaluate("() => window.OrchHarness?.reset()")
                api.release_fills()
                api.release_sends()
        finally:
            context.close()
        assert not api.unexpected + api.context.unexpected, (
            f"Unmocked workflow requests: {api.unexpected + api.context.unexpected}"
        )
        assert not errors, f"Unexpected workflow browser errors: {errors}"


def mount(
    page, api, *, prompts=None, orchestration=False, shared=False,
    can_post=True, messages=None, theme="light", entry="/chat", preserve_memory=False
):
    api.bootstrap = {
        "features": {
            "enable_user_workspace": True,
            "enable_group_workspaces": True,
            "enable_public_workspaces": True,
            "enable_chat_orchestration": orchestration,
        },
        "orchestration": {
            "enabled": orchestration,
            "show_manual_controls": True,
            "default_approval_mode": "manual",
            "allow_user_approval_override": True,
            "timed_approval_seconds": 8,
        },
        "branding": {"app_title": "SimpleChat"},
        "catalogs": {
            "prompts": prompts or [prompt(), prompt("Alternate {{customer}}.", id="alternate", name="Alternate")],
            "models": [MODEL],
            "initial_model_selection": MODEL,
            "agents": [],
        },
        "settings": {},
        "user": {"id": "prompt-tester", "display_name": "Prompt Tester"},
        "scope": {
            "groups": [{"id": "group-1", "name": "Marketing"}],
            "public_workspaces": [{"id": "public-1", "name": "Handbook"}],
            "active_group_id": None,
            "active_public_workspace_id": None,
        },
    }
    if page.url != f"{ORIGIN}{HARNESS_PATH}":
        page.goto(f"{ORIGIN}{HARNESS_PATH}", wait_until="domcontentloaded")
        page.wait_for_function("() => Boolean(window.OrchHarness)")
        for asset in api.assets:
            if asset.endswith(".css"):
                page.add_style_tag(url=f"{ORIGIN}{asset}")
    page.clock.set_fixed_time(datetime(2026, 9, 5, 12, tzinfo=timezone.utc))
    page.evaluate(
        """(spec) => {
            const H = window.OrchHarness;
            const memory = localStorage.getItem(spec.memoryKey);
            H.reset();
            if (spec.preserveMemory && memory) localStorage.setItem(spec.memoryKey, memory);
            document.documentElement.dataset.theme = spec.theme;
            document.documentElement.classList.toggle('dark', spec.theme === 'dark');
            H.stores.bootstrap.useBootstrapStore.setState({ data: spec.bootstrap });
            H.stores.chat.useChatStore.setState({
                activeConversationId: spec.conversationId,
                activeConversationKind: spec.shared ? 'collaborative' : 'personal',
                messages: spec.messages,
                conversations: [{ id: spec.conversationId, title: 'Customer review' }],
                messagesLoading: false,
                messagesError: null,
                streaming: false,
                streamingContent: '',
                streamError: null,
                thoughts: [],
            });
            H.stores.collaboration.useCollaborationStore.setState({
                conversation: spec.shared ? {
                    id: spec.conversationId,
                    can_post_messages: spec.canPost,
                    participants: [],
                } : null,
                replyTo: null,
            });
            H.stores.orchestration.useOrchestrationStore.getState()
                .setVisibleConversation(spec.conversationId);
            H.mount('mount-a', 'PromptExperience', {}, { initialEntries: [spec.entry] });
        }""",
        {
            "bootstrap": api.bootstrap,
            "conversationId": CONVERSATION_ID,
            "shared": shared,
            "canPost": can_post,
            "messages": messages or [],
            "theme": theme,
            "entry": entry,
            "preserveMemory": preserve_memory,
            "memoryKey": MEMORY_KEY,
        },
    )
    expect(message_box(page)).to_be_visible()


def message_box(page):
    return page.get_by_role("textbox", name="Message", exact=True)


def variable(page, key):
    return page.locator('[data-composer-editor="composer-input"]').locator(f'[id$="-var-{key}"]')


def field_box(page, key):
    return variable(page, key).locator("..")


def pick_prompt(page, name="Weekly brief", *, method="dropdown"):
    if method == "slash":
        draft = message_box(page)
        draft.fill(f"{draft.input_value()}/{name}")
        menu = page.get_by_role("listbox", name="Prompt suggestions")
        expect(menu.get_by_role("option", name=re.compile(re.escape(name)))).to_be_visible()
        draft.press("Enter")
    else:
        picker = page.locator('button[aria-haspopup="listbox"]').filter(
            has_text=re.compile(r"^(Prompt|Weekly brief|Alternate)$")
        ).last
        if not picker.is_visible():
            page.get_by_title("Manual controls", exact=True).click()
        picker.click()
        page.get_by_role("listbox", name="Prompt options").get_by_role(
            "option", name=re.compile(f"^{re.escape(name)}")
        ).click()
    draft_header = page.get_by_role(
        "button", name=f"Edit {name} for this message", exact=True
    ).locator("..")
    expect(draft_header.get_by_role("button", name=f"Expand prompt {name}", exact=True)).to_be_visible()


def edit_prompt(page, name="Weekly brief"):
    page.get_by_role("button", name=f"Edit {name} for this message", exact=True).click()
    editor = page.get_by_role("textbox", name="Prompt text", exact=True)
    expect(editor).to_be_visible()
    return editor


def lookup(page, api, *, key=None, hold=False):
    api.hold_fills = hold
    button = (
        field_box(page, key).get_by_role("button", name="Find in knowledge", exact=True)
        if key else page.get_by_role("button", name="Fill missing fields", exact=True).first
    )
    with page.expect_request(lambda request: urlsplit(request.url).path == FILL_PATH) as sent:
        button.click()
    return sent.value.post_data_json


def send(page, *, flow="chat", anyway=False, keyboard=False):
    with page.expect_request(
        lambda request: request.method == "POST"
        and urlsplit(request.url).path == SEND_PATHS[flow]
    ) as sent:
        if keyboard:
            message_box(page).press("Enter")
        else:
            page.get_by_role(
                "button", name="Send anyway" if anyway else "Send message", exact=True
            ).click()
    expect(message_box(page)).to_have_value("")
    return sent.value.post_data_json


def settle(page, api, flow="chat"):
    api.release_sends()
    page.wait_for_function(
        "() => !window.OrchHarness.stores.chat.useChatStore.getState().streaming"
    )
    if flow == "plan":
        with page.expect_request(lambda request: urlsplit(request.url).path == RUN_PATH):
            page.get_by_role("button", name="Approve and run the plan", exact=True).click()
        page.wait_for_function(
            "() => !window.OrchHarness.stores.chat.useChatStore.getState().streaming"
        )
    page.evaluate("() => window.OrchHarness.stores.chat.useChatStore.getState().reloadMessages()")
    assert page.evaluate(
        "() => window.OrchHarness.stores.chat.useChatStore.getState().streamError"
    ) is None


def expect_snapshot(page, name, resolved, own_text, *, edited=False):
    header = page.get_by_role("button", name=f"Expand prompt {name}", exact=True)
    expect(header).to_have_count(1)
    expect(header).to_have_attribute("aria-expanded", "false")
    if edited:
        expect(header).to_contain_text("Edited")
    expect(header).to_contain_text("My workspace")
    if own_text:
        expect(page.locator('[id^="message-"]').get_by_text(own_text, exact=True)).to_be_visible()
    header.click()
    preview = page.get_by_label(f"Prompt preview: {name}", exact=True)
    expect(preview).to_have_text(resolved)
    expect(preview.locator("textarea, input, button")).to_have_count(0)
    expect(page.get_by_role("button", name=f"Edit {name} for this message")).to_have_count(0)
    page.get_by_role("button", name=f"Collapse prompt {name}", exact=True).click()


@pytest.mark.parametrize("method", ["slash", "dropdown"])
def test_prompt_selection_preserves_words_and_exposes_fields_without_opening_preview(prompt_ui, method):
    page, api = prompt_ui
    mount(page, api)
    message_box(page).fill("Keep my own words. ")
    pick_prompt(page, method=method)
    expect(message_box(page)).to_be_focused()
    expect(message_box(page)).to_have_value("Keep my own words. ")
    expect(variable(page, "customer")).to_be_visible()
    expect(variable(page, "topic")).to_be_visible()
    expect(page.get_by_label("Prompt preview: Weekly brief", exact=True)).to_have_count(0)
    expect(page.get_by_role("button", name="Variables (2)", exact=True)).to_have_attribute(
        "aria-expanded", "true"
    )
    assert not api.fills and not api.sends


def test_slash_keyboard_and_hint_are_scoped_to_the_prompt_picker(prompt_ui):
    page, api = prompt_ui
    mount(page, api)
    page.get_by_role("button", name="Prompt", exact=True).click()
    expect(page.get_by_text(PROMPT_HINT, exact=True)).to_be_visible()
    message_box(page).press("Escape")
    page.get_by_role("button", name="Fixture model", exact=True).click()
    expect(page.get_by_role("listbox", name="Model options")).to_be_visible()
    expect(page.get_by_text(PROMPT_HINT, exact=True)).to_have_count(0)
    message_box(page).press("Escape")

    draft = message_box(page)
    for text in ("https://example.test/weekly", "and/or"):
        draft.fill(text)
        expect(page.get_by_role("listbox", name="Prompt suggestions")).to_have_count(0)
    draft.fill("/")
    menu = page.get_by_role("listbox", name="Prompt suggestions")
    expect(menu).to_be_visible()
    draft.press("ArrowDown")
    selected_name = menu.get_by_role("option", selected=True).inner_text()
    draft.press("Tab")
    expect(menu).to_have_count(0)
    expect(draft).to_be_focused()
    assert any(name in selected_name for name in ("Weekly brief", "Alternate"))
    expect(draft).to_have_value("")
    assert not api.sends and not api.fills


def test_defaults_builtins_repeated_and_literal_tokens_agree_with_live_preview(prompt_ui):
    page, api = prompt_ui
    template = (
        "Dear {{customer_name}}, {{customer-name}}. Tone: {{tone|friendly}}.\n"
        "Date {{today}}; user {{me}}; files {{selected_documents}}.\n"
        "Reply {{last_response|No previous reply}}; message {{last_message}}.\n"
        "`{{inline_example}}` and \\{{escaped_example}}\n```\n{{fenced_example}}\n```"
    )
    mount(page, api, prompts=[prompt(template)])
    pick_prompt(page)
    expect(page.get_by_role("textbox", name="customer name", exact=True)).to_have_count(1)
    expect(variable(page, "tone")).to_have_value("friendly")
    expect(field_box(page, "tone").get_by_text("Default", exact=True)).to_be_visible()
    for key in ("today", "me", "selected_documents", "last_response", "last_message"):
        expect(variable(page, key)).to_be_visible()
        assert variable(page, key).evaluate("element => element.tagName") == "P"
    expect(variable(page, "me")).to_contain_text("Prompt Tester")
    expect(variable(page, "last_response")).to_contain_text("No previous reply")
    expect(variable(page, "last_message")).to_contain_text("Not available in this chat yet")
    expect(variable(page, "selected_documents")).to_contain_text("Not available")
    for key in ("inline_example", "escaped_example", "fenced_example"):
        expect(variable(page, key)).to_have_count(0)

    pick_context(page, "Quarterly brief", "Budget notes")
    expect(variable(page, "selected_documents")).to_contain_text("Quarterly brief, Budget notes")
    variable(page, "customer_name").fill("Acme")
    page.get_by_role("button", name="Expand prompt Weekly brief", exact=True).click()
    preview = page.get_by_label("Prompt preview: Weekly brief", exact=True)
    expect(preview).to_contain_text("Dear Acme, Acme. Tone: friendly.")
    expect(preview).to_contain_text("files Quarterly brief, Budget notes")
    expect(preview).to_contain_text("Reply No previous reply; message {{last_message}}")
    expect(preview).to_contain_text("{{inline_example}}")
    page.get_by_role("button", name="Collapse prompt Weekly brief", exact=True).click()
    expect(variable(page, "customer_name")).to_be_visible()
    assert not api.fills


@pytest.mark.parametrize("width", [1440, 390], ids=["desktop", "mobile"])
def test_turn_editor_inserts_at_selection_restores_focus_and_reset_does_not_save(prompt_ui, width):
    page, api = prompt_ui
    page.set_viewport_size({"width": width, "height": 844})
    original = "Hello TARGET. {{topic}}"
    mount(page, api, prompts=[prompt(original)])
    message_box(page).fill("My own note.")
    pick_prompt(page)
    editor = edit_prompt(page)
    editor.evaluate("element => { element.focus(); element.setSelectionRange(6, 12); }")
    page.get_by_role("button", name="Insert variable", exact=True).click()
    picker = page.get_by_role("dialog", name="Insert a prompt variable", exact=True)
    expect(picker.get_by_role("textbox", name="Variable name", exact=True)).to_be_focused()
    bounds = picker.bounding_box()
    assert bounds and bounds["x"] >= 0 and bounds["x"] + bounds["width"] <= width
    assert bounds["y"] >= 0 and bounds["y"] + bounds["height"] <= 844
    picker.get_by_role("textbox", name="Variable name", exact=True).fill("today")
    expect(picker.get_by_role("button", name="Add custom variable")).to_be_disabled()
    picker.get_by_role("textbox", name="Variable name", exact=True).fill("customer name")
    picker.get_by_role("textbox", name="Default value (optional)", exact=True).fill("{{unsafe}}")
    expect(picker.get_by_role("button", name="Add custom variable")).to_be_disabled()
    picker.get_by_role("textbox", name="Default value (optional)", exact=True).fill("Acme")
    picker.get_by_role("button", name="Add custom variable").click()
    token = "{{customer name|Acme}}"
    expect(editor).to_have_value(f"Hello {token}. {{{{topic}}}}")
    expect(editor).to_be_focused()
    assert editor.evaluate("element => element.selectionStart") == 6 + len(token)
    expect(variable(page, "customer_name")).to_have_value("Acme")
    expect(page.get_by_role("button", name="Collapse prompt Weekly brief")).to_contain_text("Edited")
    page.get_by_role("button", name="Insert variable", exact=True).click()
    picker.press("Escape")
    expect(page.get_by_role("button", name="Insert variable", exact=True)).to_be_focused()
    expect(editor).to_be_visible()
    page.get_by_role("button", name="Reset", exact=True).click()
    expect(editor).to_have_value(original)
    expect(variable(page, "customer_name")).to_have_count(0)
    expect(message_box(page)).to_have_value("My own note.")
    catalog = page.evaluate(
        "() => window.OrchHarness.stores.bootstrap.useBootstrapStore.getState().data.catalogs.prompts"
    )
    assert catalog[0]["content"] == original
    assert not [item for item in api.requests if item[0] != "GET"]


@pytest.mark.parametrize("width", [1440, 390], ids=["desktop", "mobile"])
def test_saved_prompt_editor_uses_the_same_caret_picker_without_inventing_chat_values(prompt_ui, width):
    page, api = prompt_ui
    page.set_viewport_size({"width": width, "height": 844})
    mount(page, api)
    message_box(page).fill("Hello TARGET.")
    page.get_by_role("button", name="Save as prompt", exact=True).click()
    dialog = page.get_by_role("dialog", name="New prompt", exact=True)
    editor = dialog.locator("#prompt-content")
    editor.evaluate("element => { element.focus(); element.setSelectionRange(6, 12); }")
    dialog.get_by_role("button", name="Insert variable", exact=True).click()
    picker = page.get_by_role("dialog", name="Insert a prompt variable", exact=True)
    expect(picker.get_by_text("Filled from context when used in chat", exact=True)).to_have_count(8)
    bounds = picker.bounding_box()
    assert bounds and bounds["x"] >= 0 and bounds["x"] + bounds["width"] <= width
    assert bounds["y"] >= 0 and bounds["y"] + bounds["height"] <= 844
    picker.get_by_role("textbox", name="Variable name", exact=True).fill("audience")
    picker.get_by_role("button", name="Add custom variable").click()
    expect(editor).to_have_value("Hello {{audience}}.")
    expect(editor).to_be_focused()
    dialog.get_by_role("button", name="Insert variable", exact=True).click()
    picker.get_by_role("button").filter(has_text="{{composer}}").click()
    expect(editor).to_have_value("Hello {{audience}}{{composer}}.")
    expect(editor).to_be_focused()
    dialog.get_by_role("button", name="Cancel", exact=True).click()
    expect(dialog.get_by_text("Discard your unsaved changes?", exact=True)).to_be_visible()
    dialog.get_by_role("button", name="Keep editing", exact=True).click()
    expect(editor).to_have_value("Hello {{audience}}{{composer}}.")
    dialog.get_by_role("button", name="Cancel", exact=True).click()
    dialog.get_by_role("button", name="Discard", exact=True).click()
    expect(dialog).to_have_count(0)
    expect(message_box(page)).to_have_value("Hello TARGET.")
    assert not api.fills and not api.sends


def test_chat_quick_fill_requires_a_click_and_stays_distinct_from_ai_fill(prompt_ui):
    page, api = prompt_ui
    messages = [
        {
            "id": "previous-user", "role": "user", "content": "My previous request.",
            "conversation_id": CONVERSATION_ID, "timestamp": "2026-09-05T10:00:00Z",
        },
        {
            "id": "previous-assistant", "role": "assistant", "content": "A previous answer.",
            "conversation_id": CONVERSATION_ID, "timestamp": "2026-09-05T10:01:00Z",
        },
    ]
    mount(page, api, prompts=[prompt("Use {{context}}.")], messages=messages)
    pick_prompt(page)
    message_box(page).fill("My current draft.")
    box = field_box(page, "context")
    expect(variable(page, "context")).to_have_value("")
    box.get_by_role("button", name="Last reply", exact=True).click()
    expect(variable(page, "context")).to_have_value("A previous answer.")
    box.get_by_role("button", name="My last message", exact=True).click()
    expect(variable(page, "context")).to_have_value("My previous request.")
    box.get_by_role("button", name="What I have typed", exact=True).click()
    expect(variable(page, "context")).to_have_value("My current draft.")
    expect(box.get_by_text("AI-filled", exact=True)).to_have_count(0)
    expect(box.get_by_role("button", name=re.compile("^Sources"))).to_have_count(0)
    assert not api.fills and not api.sends


def test_plain_message_without_a_prompt_keeps_its_existing_send_contract(prompt_ui):
    page, api = prompt_ui
    mount(page, api)
    message_box(page).fill("An ordinary question without a prompt.")
    body = send(page, keyboard=True)
    assert body["message"] == "An ordinary question without a prompt."
    assert not body.get("prompt_info")
    settle(page, api)
    expect(page.get_by_role("button", name=re.compile(r"^Expand prompt "))).to_have_count(0)
    expect(page.locator('[id^="message-"]').get_by_text(body["message"], exact=True)).to_be_visible()
    assert not api.fills


@pytest.mark.parametrize("flow", ["chat", "plan"])
@pytest.mark.parametrize("composition", ["prompt-only", "appended", "embedded", "edited-defaults"])
def test_real_send_retains_snapshot_optimistically_after_echo_and_after_reload(
    prompt_ui, flow, composition
):
    page, api = prompt_ui
    template = "Follow the saved instructions."
    own_text = "" if composition == "prompt-only" else "These are my own words."
    edited = composition == "edited-defaults"
    if composition == "embedded":
        template = "Rephrase: {{composer}}"
    if edited:
        template = "Write for {{audience|colleagues}}."
    mount(page, api, prompts=[prompt(template)], orchestration=flow == "plan")
    pick_prompt(page)
    message_box(page).fill(own_text)
    if edited:
        edit_prompt(page).fill("Edited for {{audience|colleagues}} by {{me}}.")
        variable(page, "audience").fill("reviewers")
        resolved = "Edited for reviewers by Prompt Tester."
    elif composition == "embedded":
        resolved = f"Rephrase: {own_text}"
    else:
        resolved = template

    api.hold_sends = True
    body = send(page, flow=flow)
    expected_model = resolved if not own_text or composition == "embedded" else f"{resolved}\n\n{own_text}"
    assert body["message"] == expected_model
    assert body["prompt_info"]["content"] == resolved
    assert body["prompt_info"]["composer_text"] == own_text
    assert body["prompt_info"]["composer_embedded"] is (composition == "embedded")
    assert body["prompt_info"]["user_text"] == ("" if composition == "embedded" else own_text)
    assert body["prompt_info"]["edited"] is edited
    if own_text:
        assert body["message"].count(own_text) == 1
    expect_snapshot(page, "Weekly brief", resolved, own_text, edited=edited)
    settle(page, api, flow)
    expect_snapshot(page, "Weekly brief", resolved, own_text, edited=edited)
    if flow == "plan":
        assert len(api.runs) == 1

    page.reload(wait_until="domcontentloaded")
    page.wait_for_function("() => Boolean(window.OrchHarness)")
    for asset in api.assets:
        if asset.endswith(".css"):
            page.add_style_tag(url=f"{ORIGIN}{asset}")
    mount(page, api, prompts=[prompt("A completely different saved prompt now.")])
    page.evaluate("() => window.OrchHarness.stores.chat.useChatStore.getState().reloadMessages()")
    expect_snapshot(page, "Weekly brief", resolved, own_text, edited=edited)
    assert len(api.sends) == 1 and not api.fills


@pytest.mark.parametrize("flow", ["chat", "plan"])
@pytest.mark.parametrize("keyboard", [False, True], ids=["button", "enter"])
def test_missing_values_warn_review_and_send_anyway_is_only_for_one_turn(prompt_ui, flow, keyboard):
    page, api = prompt_ui
    mount(page, api, prompts=[prompt("For {{customer}}; {{last_message}}.")], orchestration=flow == "plan")
    pick_prompt(page)
    message_box(page).fill("My question.")
    if keyboard:
        message_box(page).press("Enter")
    else:
        page.get_by_role("button", name="Send message", exact=True).click()
    warning = page.get_by_role("alert").filter(has_text="Some prompt variables")
    expect(warning).to_contain_text("{{customer}}, {{last_message}}")
    expect(warning).to_contain_text("literal placeholders")
    expect(warning.get_by_role("button", name="Fill missing fields", exact=True)).to_be_disabled()
    assert not api.sends
    page.get_by_role("button", name="Variables (2)", exact=True).click()
    warning.get_by_role("button", name="Review fields", exact=True).click()
    expect(variable(page, "customer")).to_be_focused()
    body = send(page, flow=flow, anyway=True)
    assert body["message"] == "For {{customer}}; {{last_message}}.\n\nMy question."
    settle(page, api, flow)
    pick_prompt(page)
    page.get_by_role("button", name="Send message", exact=True).click()
    expect(warning).to_be_visible()
    assert len(api.sends) == 1, "Send anyway must not become a remembered preference."


def test_reattaching_after_send_anyway_does_not_replay_the_previous_field_focus_request(prompt_ui):
    page, api = prompt_ui
    mount(page, api, prompts=[prompt("For {{customer}}.")])
    pick_prompt(page)
    page.get_by_role("button", name="Send message", exact=True).click()
    page.get_by_role("button", name="Review fields", exact=True).click()
    expect(variable(page, "customer")).to_be_focused()
    send(page, anyway=True)
    settle(page, api)
    pick_prompt(page)
    try:
        expect(message_box(page)).to_be_focused()
    except AssertionError as error:
        focused_id = page.evaluate("() => document.activeElement?.id")
        raise AssertionError(
            f"The new prompt replayed the previous review focus: {focused_id}. "
            "Selecting a new attachment should restore focus to the Message field."
        ) from error


def test_unfilled_prompt_warning_respects_the_hosts_busy_send_gate(prompt_ui):
    page, api = prompt_ui
    mount(page, api, prompts=[prompt("For {{customer}}.")])
    pick_prompt(page)
    page.get_by_role("button", name="Send message", exact=True).click()
    warning = page.get_by_role("alert").filter(has_text="Some prompt variables")
    expect(warning).to_be_visible()
    page.evaluate("() => window.OrchHarness.stores.chat.useChatStore.setState({streaming: true})")
    expect(warning.get_by_role("button", name="Send anyway", exact=True)).to_be_disabled()
    assert not api.sends
    page.evaluate("() => window.OrchHarness.stores.chat.useChatStore.setState({streaming: false})")
    expect(warning.get_by_role("button", name="Send anyway", exact=True)).to_be_enabled()


def test_warning_fill_is_explicit_scoped_and_does_not_send_after_success(prompt_ui):
    page, api = prompt_ui
    mount(page, api, prompts=[prompt("For {{customer}}.")])
    pick_prompt(page)
    expect(page.get_by_role("button", name="Fill missing fields", exact=True)).to_be_disabled()
    expect(page.get_by_role("button", name="Find in knowledge", exact=True)).to_have_count(0)
    page.get_by_role("button", name="Choose knowledge", exact=True).click()
    expect(page.get_by_role("searchbox", name="Search documents")).to_be_visible()
    expect(page.get_by_text(PROMPT_HINT, exact=True)).to_have_count(0)
    page.get_by_role("button", name="Done", exact=True).click()
    pick_context(page, "Quarterly brief", "urgent")
    expect(page.get_by_text("AI fill searches: Quarterly brief, urgent", exact=True)).to_be_visible()
    message_box(page).fill("Review the account.")
    page.get_by_role("button", name="Send message", exact=True).click()
    warning = page.get_by_role("alert").filter(has_text="Some prompt variables")
    api.fill_response = {"values": [filled("customer", "Acme")], "unresolved": []}
    with page.expect_request(lambda request: urlsplit(request.url).path == FILL_PATH) as sent:
        warning.get_by_role("button", name="Fill missing fields", exact=True).click()
    request = sent.value.post_data_json
    assert request["selected_document_ids"] == ["personal-brief"]
    assert request["tags"] == ["urgent"]
    assert request["document_filter_mode"] == "union"
    assert request["search_all"] is False and request["doc_scope"] == "personal"
    assert request["variables"] == [{"key": "customer", "name": "customer"}]
    assert request["composer_text"] == "Review the account."
    expect(variable(page, "customer")).to_have_value("Acme")
    expect(warning).to_have_count(0)
    expect(message_box(page)).to_have_value("Review the account.")
    assert not api.sends, "Completing an AI fill must never send automatically."


def test_single_ai_value_sources_undo_and_manual_edits_are_visible_and_turn_local(prompt_ui):
    page, api = prompt_ui
    mount(page, api, prompts=[prompt("For {{customer}}.")])
    pick_prompt(page)
    variable(page, "customer").fill("   ")
    pick_context(page, "Quarterly brief")
    source = {**SOURCE, "title": "<b>Quarterly brief</b>", "excerpt": "<b>Acme</b> is the customer."}
    api.fill_response = {"values": [filled("customer", "Acme", source=source)], "unresolved": []}
    lookup(page, api, key="customer")
    expect(variable(page, "customer")).to_have_value("Acme")
    box = field_box(page, "customer")
    expect(box.get_by_text("AI-filled", exact=True)).to_be_visible()
    box.get_by_role("button", name="Sources (1)", exact=True).click()
    sources = page.get_by_role("list", name="Sources for customer", exact=True)
    expect(sources).to_contain_text("<b>Quarterly brief</b>, page 3")
    expect(sources).to_contain_text("<b>Acme</b> is the customer.")
    expect(sources.locator("b, script, img")).to_have_count(0)
    page.get_by_role("button", name="Undo AI fill for customer", exact=True).click()
    expect(variable(page, "customer")).to_have_value("   ")
    expect(box.get_by_text("AI-filled", exact=True)).to_have_count(0)

    lookup(page, api, key="customer")
    expect(variable(page, "customer")).to_have_value("Acme")
    variable(page, "customer").fill("My correction")
    expect(box.get_by_text("AI-filled", exact=True)).to_have_count(0)
    expect(box.get_by_role("button", name="Sources (1)", exact=True)).to_have_count(0)
    expect(box.get_by_text("Your value", exact=True)).to_be_visible()
    variable(page, "customer").fill("")
    lookup(page, api, key="customer")
    expect(variable(page, "customer")).to_have_value("Acme")
    send(page)
    settle(page, api)
    memory = page.evaluate("(key) => localStorage.getItem(key)", MEMORY_KEY) or ""
    assert "Acme" not in memory and SOURCE["excerpt"] not in memory
    pick_prompt(page)
    expect(variable(page, "customer")).to_have_value("")


@pytest.mark.parametrize("key", ["constructor", "__proto__"])
@pytest.mark.parametrize("origin", ["manual", "knowledge"])
def test_prototype_named_variables_are_editable_fillable_and_send_as_plain_data(prompt_ui, key, origin):
    page, api = prompt_ui
    template = f"Value {{{{{key}}}}}; repeated {{{{{key}}}}}."
    mount(page, api, prompts=[prompt(template)])
    pick_prompt(page)
    expect(variable(page, key)).to_be_visible()
    expect(variable(page, key)).to_have_value("")
    expect(page.get_by_role("button", name="Variables (1)", exact=True)).to_be_visible()
    value = f"{origin} value"
    if origin == "manual":
        variable(page, key).fill(value)
    else:
        pick_context(page, "Quarterly brief")
        api.fill_response = {"values": [filled(key, value)], "unresolved": []}
        request = lookup(page, api, key=key)
        assert request["variables"] == [{"key": key, "name": key}]
        assert request["known_values"] == {}
        expect(variable(page, key)).to_have_value(value)
        box = field_box(page, key)
        expect(box.get_by_text("AI-filled", exact=True)).to_be_visible()
        box.get_by_role("button", name=re.compile("^Undo AI fill for ")).click()
        expect(variable(page, key)).to_have_value("")
        lookup(page, api, key=key)
    expect(variable(page, key)).to_have_value(value)
    body = send(page)
    resolved = f"Value {value}; repeated {value}."
    assert body["message"] == resolved
    assert body["prompt_info"]["variables"] == {key: value}
    settle(page, api)
    expect_snapshot(page, "Weekly brief", resolved, "")
    pick_prompt(page)
    expect(variable(page, key)).to_have_value(value if origin == "manual" else "")


def test_batch_never_overwrites_manual_or_default_fields_and_partial_conflicts_need_a_choice(prompt_ui):
    page, api = prompt_ui
    mount(page, api, prompts=[prompt("{{customer}}; {{tone|friendly}}; {{owner}}; {{deadline}}.")])
    pick_prompt(page)
    variable(page, "customer").fill("Manual customer")
    pick_context(page, "Quarterly brief")
    api.fill_response = {
        "values": [
            filled("owner", "Alex"),
            filled("customer", "Unrequested overwrite"),
            filled("tone", "Unrequested default overwrite"),
        ],
        "unresolved": [{"key": "deadline", "reason": "No due date was found in these sources."}],
    }
    request = lookup(page, api)
    assert {item["key"] for item in request["variables"]} == {"owner", "deadline"}
    assert request["known_values"]["customer"] == "Manual customer"
    assert request["known_values"]["tone"] == "friendly"
    expect(variable(page, "customer")).to_have_value("Manual customer")
    expect(variable(page, "tone")).to_have_value("friendly")
    expect(variable(page, "owner")).to_have_value("Alex")
    expect(variable(page, "deadline")).to_have_value("")
    expect(field_box(page, "deadline")).to_contain_text("No due date was found")
    expect(field_box(page, "customer").get_by_role("button", name="Find in knowledge")).to_be_disabled()
    expect(field_box(page, "tone").get_by_role("button", name="Find in knowledge")).to_be_disabled()
    expect(page.get_by_role("button", name="Variables (4)", exact=True)).to_have_attribute("aria-expanded", "true")

    api.fill_response = {
        "values": [],
        "unresolved": [{
            "key": "deadline",
            "reason": "The selected documents give different dates. Choose the one you intend.",
            "alternatives": [
                {"value": "Friday", "sources": [SOURCE]},
                {"value": "Monday", "sources": [{**SOURCE, "title": "Budget notes"}]},
            ],
        }],
    }
    lookup(page, api, key="deadline")
    box = field_box(page, "deadline")
    expect(box.get_by_text("The selected documents give different dates. Choose the one you intend.")).to_be_visible()
    expect(variable(page, "deadline")).to_have_value("")
    expect(box).not_to_contain_text(re.compile(r"confidence|\d+%", re.I))
    box.get_by_role("button", name=re.compile("^Use Monday")).click()
    expect(variable(page, "deadline")).to_have_value("Monday")
    expect(box.get_by_text("AI-filled", exact=True)).to_be_visible()
    box.get_by_role("button", name="Sources (1)", exact=True).click()
    expect(page.get_by_role("list", name="Sources for deadline")).to_contain_text("Budget notes")
    assert not api.sends


def test_only_explicit_widening_changes_ai_scope_not_the_send_document_selection(prompt_ui):
    page, api = prompt_ui
    mount(page, api, prompts=[prompt("For {{customer}}.")])
    pick_prompt(page)
    pick_context(page, "Quarterly brief", "Campaign outline", "urgent")
    assert not api.fills
    request = lookup(page, api)
    assert request["selected_document_ids"] == ["personal-brief", "group-campaign"]
    assert request["tags"] == ["urgent"] and request["active_group_ids"] == ["group-1"]
    assert request["doc_scope"] == "all" and request["search_all"] is False
    assert request["scope_selected"] is False
    assert request["context_items"] == [
        {"kind": "document", "id": "personal-brief", "scope": {"kind": "personal", "id": None}},
        {"kind": "document", "id": "group-campaign", "scope": {"kind": "group", "id": "group-1"}},
        {"kind": "tag", "id": "urgent", "scope": {"kind": "personal", "id": None}},
    ]
    assert normalize_captured_fill(request)["context_items"] == request["context_items"]
    expect(page.get_by_role("status").filter(has_text="No values were filled")).to_be_visible()
    page.get_by_role("checkbox", name="Search all accessible knowledge for AI fill", exact=True).check()
    expect(page.get_by_text("Only widens AI fill, not your message's document selection.", exact=True)).to_be_visible()
    assert len(api.fills) == 1
    api.fill_response = {"values": [filled("customer", "Acme")], "unresolved": []}
    request = lookup(page, api)
    assert request["search_all"] is True and request["doc_scope"] == "all"
    assert request["scope_selected"] is False
    assert request["selected_document_ids"] == request["tags"] == request["active_group_ids"] == []
    assert request["context_items"] == []
    assert normalize_captured_fill(request)["search_all"] is True
    expect(variable(page, "customer")).to_have_value("Acme")
    body = send(page)
    assert body["selected_document_ids"] == ["personal-brief", "group-campaign"]
    assert body["tags"] == ["urgent"] and body["document_filter_mode"] == "union"
    settle(page, api)


def test_personal_workspace_chip_is_an_explicit_scope_without_global_widening(prompt_ui):
    page, api = prompt_ui
    mount(page, api, prompts=[prompt("For {{customer}}.")])
    pick_prompt(page)
    expect(page.get_by_role("button", name="Fill missing fields", exact=True)).to_be_disabled()
    pick_context(page, "My workspace")
    assert not api.fills
    request = lookup(page, api)
    assert request["scope_selected"] is True
    assert request["doc_scope"] == "personal" and request["search_all"] is False
    assert request["selected_document_ids"] == request["tags"] == []
    assert request["active_group_ids"] == request["active_public_workspace_ids"] == []
    assert request["context_items"] == [
        {"kind": "scope", "id": "", "scope": {"kind": "personal", "id": None}},
    ]
    assert normalize_captured_fill(request)["personal_scope_selected"] is True
    expect(page.get_by_role("status").filter(has_text="No values were filled")).to_be_visible()
    page.get_by_role("checkbox", name="Search all accessible knowledge for AI fill").check()
    assert len(api.fills) == 1, "Widening the scope must not itself start a lookup."
    request = lookup(page, api)
    assert request["scope_selected"] is False
    assert request["search_all"] is True and request["doc_scope"] == "all"
    assert not api.sends


def test_same_name_tag_swap_invalidates_lookup_even_when_flattened_scope_is_identical(prompt_ui):
    page, api = prompt_ui
    api.tag_names = {
        "/api/documents/tags": ["review-tag"],
        "/api/group_documents/tags": ["review-tag"],
    }
    mount(page, api, prompts=[prompt("For {{customer}}.")])
    pick_prompt(page)
    pick_context(page, "My workspace", "Marketing")

    def tag_option(scope_name):
        return page.get_by_role(
            "button", name=re.compile(f"^review-tag.*{re.escape(scope_name)}$")
        ).and_(page.locator("button[aria-pressed]"))

    open_picker(page)
    tag_option("My workspace").click()
    expect(tag_option("My workspace")).to_have_attribute("aria-pressed", "true")
    page.get_by_role("button", name="Done", exact=True).click()
    api.fill_response = {"values": [filled("customer", "Stale scope result")], "unresolved": []}
    first_request = lookup(page, api, hold=True)
    assert first_request["tags"] == ["review-tag"]
    assert first_request["active_group_ids"] == ["group-1"]
    assert first_request["scope_selected"] is True

    open_picker(page)
    expect(page.get_by_role("button", name="Cancel lookup", exact=True)).to_be_visible()
    # Add first: removing the only tag first would change flattened tags and hide this race.
    tag_option("Marketing").click()
    expect(tag_option("Marketing")).to_have_attribute("aria-pressed", "true")
    tag_option("My workspace").click()
    expect(tag_option("My workspace")).to_have_attribute("aria-pressed", "false")
    page.get_by_role("button", name="Done", exact=True).click()
    expect(page.get_by_role("button", name="Cancel lookup", exact=True)).to_have_count(0)
    api.release_fills()
    page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
    expect(variable(page, "customer")).to_have_value("")
    expect(field_box(page, "customer").get_by_text("AI-filled", exact=True)).to_have_count(0)

    api.fill_response = {"values": [filled("customer", "Fresh scope result")], "unresolved": []}
    second_request = lookup(page, api)
    assert {
        key: value for key, value in second_request.items() if key != "context_items"
    } == {
        key: value for key, value in first_request.items() if key != "context_items"
    }, "The flattened filters remain identical."
    first_tag = next(item for item in first_request["context_items"] if item["kind"] == "tag")
    second_tag = next(item for item in second_request["context_items"] if item["kind"] == "tag")
    assert first_tag["scope"] == {"kind": "personal", "id": None}
    assert second_tag["scope"] == {"kind": "group", "id": "group-1"}
    assert normalize_captured_fill(second_request)["context_items"] == second_request["context_items"]
    expect(variable(page, "customer")).to_have_value("Fresh scope result")
    assert len(api.fills) == 2 and not api.sends


@pytest.mark.parametrize("status", [400, 503])
def test_lookup_failure_is_actionable_preserves_the_draft_and_can_be_retried(prompt_ui, status):
    page, api = prompt_ui
    mount(page, api, prompts=[prompt("For {{customer}}.")])
    pick_prompt(page)
    pick_context(page, "Quarterly brief")
    message_box(page).fill("Keep this question.")
    api.fill_status = status
    api.fill_response = {"error": "Unable to fill variables from knowledge. Try again later."}
    lookup(page, api)
    expect(page.get_by_role("alert")).to_contain_text("Unable to fill variables from knowledge")
    expect(variable(page, "customer")).to_have_value("")
    expect(message_box(page)).to_have_value("Keep this question.")
    api.fill_status = 200
    api.fill_response = {"values": [filled("customer", "Acme")], "unresolved": []}
    lookup(page, api)
    expect(variable(page, "customer")).to_have_value("Acme")
    expect(page.get_by_role("alert")).to_have_count(0)
    assert not api.sends


@pytest.mark.parametrize("change", [
    "cancel", "field-edit", "template-edit", "reset", "remove-variable",
    "remove-prompt", "prompt-switch", "same-prompt", "conversation-switch", "scope-change", "send",
])
def test_late_fill_cannot_mutate_a_newer_draft(prompt_ui, change):
    page, api = prompt_ui
    mount(page, api)
    pick_prompt(page)
    message_box(page).fill("Keep this draft.")
    pick_context(page, "Quarterly brief")
    if change == "reset":
        edit_prompt(page).fill("Edited {{customer}} and {{topic}}.")
    api.fill_response = {
        "values": [filled("customer", "Stale customer"), filled("topic", "Stale topic")],
        "unresolved": [],
    }
    lookup(page, api, hold=True)
    expect(page.get_by_role("button", name="Cancel lookup", exact=True)).to_be_visible()
    expect(page.get_by_role("status")).to_contain_text("Searching knowledge")

    if change == "cancel":
        page.get_by_role("button", name="Cancel lookup", exact=True).click()
        expect(page.get_by_role("status")).to_contain_text("cancelled")
    elif change == "field-edit":
        variable(page, "customer").fill("Human wins")
    elif change == "template-edit":
        edit_prompt(page).fill("New wording for {{customer}} and {{topic}}.")
    elif change == "reset":
        page.get_by_role("button", name="Reset", exact=True).click()
    elif change == "remove-variable":
        edit_prompt(page).fill("Only {{topic}} remains.")
    elif change == "remove-prompt":
        page.get_by_role("button", name="Remove Weekly brief", exact=True).click()
    elif change in ("prompt-switch", "same-prompt"):
        pick_prompt(page, "Alternate" if change == "prompt-switch" else "Weekly brief")
    elif change == "conversation-switch":
        page.evaluate(
            """() => window.OrchHarness.stores.chat.useChatStore.setState({
                activeConversationId: 'another-chat', messages: [],
            })"""
        )
    elif change == "scope-change":
        page.get_by_role("checkbox", name="Search all accessible knowledge for AI fill", exact=True).check()
    else:
        page.get_by_role("button", name="Send message", exact=True).click()
        body = send(page, anyway=True)
        assert "Stale" not in body["message"]
        settle(page, api)

    api.release_fills()
    page.evaluate("() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))")
    expect(page.get_by_text("AI-filled", exact=True)).to_have_count(0)
    expect(page.get_by_role("button", name="Cancel lookup", exact=True)).to_have_count(0)
    if change in ("remove-prompt", "send"):
        expect(page.get_by_role("button", name="Edit Weekly brief for this message")).to_have_count(0)
    else:
        if change == "remove-variable":
            expect(variable(page, "customer")).to_have_count(0)
        else:
            expect(variable(page, "customer")).to_have_value("Human wins" if change == "field-edit" else "")
        if change != "prompt-switch":
            expect(variable(page, "topic")).to_have_value("")
    assert len(api.fills) == 1
    if change != "send":
        expect(message_box(page)).to_have_value("Keep this draft.")
        assert not api.sends


@pytest.mark.parametrize("transition", ["remount", "in-place"])
def test_private_remembered_values_are_not_offered_or_sent_to_ai_in_shared_chat(prompt_ui, transition):
    page, api = prompt_ui
    catalog = [prompt("For {{customer}}.")]
    mount(page, api, prompts=catalog)
    pick_prompt(page)
    variable(page, "customer").fill("Private remembered customer")
    send(page)
    settle(page, api)
    pick_prompt(page)
    expect(variable(page, "customer")).to_have_value("Private remembered customer")
    expect(field_box(page, "customer").get_by_text("Reused", exact=True)).to_be_visible()

    if transition == "remount":
        mount(page, api, prompts=catalog, shared=True, preserve_memory=True)
        pick_prompt(page)
    else:
        page.evaluate(
            """() => {
                const H = window.OrchHarness;
                H.stores.chat.useChatStore.setState({
                    activeConversationId: 'shared-prompt-chat',
                    activeConversationKind: 'collaborative',
                    messages: [],
                });
                H.stores.collaboration.useCollaborationStore.setState({
                    conversation: {
                        id: 'shared-prompt-chat', can_post_messages: true, participants: [],
                    },
                });
            }"""
        )
    expect(variable(page, "customer")).to_have_value("")
    expect(page.get_by_text("Private remembered customer", exact=True)).to_have_count(0)
    expect(page.get_by_text("Filled values will be visible to participants when you send.", exact=True)).to_be_visible()
    pick_context(page, "Quarterly brief")
    request = lookup(page, api)
    assert request["conversation_kind"] == "collaborative"
    assert "Private remembered customer" not in json.dumps(request)
    if transition == "in-place":
        page.evaluate(
            """(conversationId) => window.OrchHarness.stores.chat.useChatStore.setState({
                activeConversationId: conversationId, activeConversationKind: 'personal',
            })""",
            CONVERSATION_ID,
        )
        expect(variable(page, "customer")).to_have_value("Private remembered customer")
        expect(field_box(page, "customer").get_by_text("Reused", exact=True)).to_be_visible()


def test_shared_read_only_access_disables_new_edit_and_fill_controls(prompt_ui):
    page, api = prompt_ui
    mount(page, api, shared=True, can_post=False, entry="/chat?prompt=weekly")
    expect(variable(page, "customer")).to_be_disabled()
    expect(message_box(page)).to_be_disabled()
    for label in ("Edit Weekly brief for this message", "Remove Weekly brief", "Choose knowledge"):
        expect(page.get_by_role("button", name=label, exact=True)).to_be_disabled()
    expect(page.get_by_role("button", name="Fill missing fields", exact=True)).to_be_disabled()
    expect(page.get_by_role("checkbox", name="Search all accessible knowledge for AI fill")).to_be_disabled()
    assert not api.fills and not api.sends


def test_large_run_continuation_preserves_the_explicit_warning_decision_and_snapshot(prompt_ui):
    page, api = prompt_ui
    template = "Export every row of 4,000 rows to csv for {{customer}}."
    mount(page, api, prompts=[prompt(template)])
    pick_prompt(page)
    message_box(page).fill("Keep the full export.")
    message_box(page).press("Enter")
    warning = page.get_by_role("alert").filter(has_text="Some prompt variables")
    expect(warning).to_be_visible()
    page.get_by_role("button", name="Send anyway", exact=True).click()
    dialog = page.get_by_role("dialog", name="Large tabular run", exact=True)
    expect(dialog).to_be_visible()
    assert not api.sends
    dialog.get_by_role("button", name="Narrow scope", exact=True).click()
    expect(message_box(page)).to_have_value("Keep the full export.")
    page.get_by_role("button", name="Send message", exact=True).click()
    expect(warning).to_be_visible()
    page.get_by_role("button", name="Send anyway", exact=True).click()
    with page.expect_request(lambda request: urlsplit(request.url).path == SEND_PATHS["chat"]) as sent:
        dialog.get_by_role("button", name="Continue run", exact=True).click()
    assert sent.value.post_data_json["message"] == f"{template}\n\nKeep the full export."
    settle(page, api)
    expect_snapshot(page, "Weekly brief", template, "Keep the full export.")
    assert len(api.sends) == 1


def test_large_run_confirmation_keeps_approved_now_snapshot_when_only_the_clock_changes(prompt_ui):
    page, api = prompt_ui
    template = "Export every row of 4,000 rows to csv. Started {{now}}."
    mount(page, api, prompts=[prompt(template)])
    pick_prompt(page)
    message_box(page).fill("Keep the approved export.")
    initial_now = variable(page, "now").evaluate("element => element.firstChild.textContent")
    resolved = template.replace("{{now}}", initial_now)
    page.get_by_role("button", name="Send message", exact=True).click()
    dialog = page.get_by_role("dialog", name="Large tabular run", exact=True)
    expect(dialog).to_be_visible()
    assert not api.sends

    page.clock.set_fixed_time(datetime(2026, 9, 5, 12, 1, 1, tzinfo=timezone.utc))
    with page.expect_request(
        lambda request: request.method == "POST"
        and urlsplit(request.url).path == SEND_PATHS["chat"]
    ) as sent:
        dialog.get_by_role("button", name="Continue run", exact=True).click()
    body = sent.value.post_data_json
    expect(dialog).to_have_count(0)
    assert body["prompt_info"]["content"] == resolved
    assert body["message"] == f"{resolved}\n\nKeep the approved export."
    settle(page, api)
    expect_snapshot(page, "Weekly brief", resolved, "Keep the approved export.")
    assert len(api.sends) == 1


@pytest.mark.parametrize("width", [1440, 390], ids=["desktop", "mobile"])
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_long_prompt_and_many_fields_have_bounded_scroll_and_keyboard_reachable_input(prompt_ui, width, theme):
    page, api = prompt_ui
    page.set_viewport_size({"width": width, "height": 844})
    name = " ".join(["Long customer guidance"] * 8)
    content = "\n".join([f"Detailed instruction {index}: " + "context " * 40 for index in range(35)])
    content += "\n" + "\n".join(f"Field {{{{field_{index}}}}}" for index in range(12))
    mount(page, api, prompts=[prompt(content, name=name)], theme=theme)
    pick_prompt(page, name)
    draft = message_box(page)
    expect(variable(page, "field_0")).to_be_visible()
    header = page.get_by_role("button", name=f"Expand prompt {name}", exact=True)
    header.focus()
    header.press("Enter")
    preview = page.get_by_label(f"Prompt preview: {name}", exact=True)
    expect(preview).to_be_visible()
    assert preview.evaluate("element => element.scrollHeight > element.clientHeight")
    assert preview.bounding_box()["height"] <= 210
    card = page.get_by_role(
        "button", name=f"Edit {name} for this message", exact=True
    ).locator("..").locator("..")
    assert card.bounding_box()["height"] <= 844 * 0.4 + 1
    assert card.evaluate("element => element.scrollHeight > element.clientHeight")
    for target in (draft, page.get_by_role("button", name="Send message", exact=True)):
        box = target.bounding_box()
        assert box and box["y"] >= 0 and box["y"] + box["height"] <= 844
    page.get_by_role("button", name=f"Collapse prompt {name}", exact=True).press("Space")
    draft.focus()
    draft.press_sequentially("My words stay reachable.")
    draft.press("Shift+Enter")
    draft.press_sequentially("Second line.")
    expect(draft).to_have_value("My words stay reachable.\nSecond line.")
    send_button = page.get_by_role("button", name="Send message", exact=True)
    for target in (draft, send_button):
        box = target.bounding_box()
        assert box and box["x"] >= 0 and box["x"] + box["width"] <= width + 1
        assert box["y"] >= 0 and box["y"] + box["height"] <= 844
    assert page.evaluate(
        "() => document.documentElement.scrollWidth <= window.innerWidth + 1"
    ), "The attached prompt must not create horizontal page overflow."
    assert not api.sends and not api.fills


if __name__ == "__main__":
    sys.exit(pytest.main([str(Path(__file__).resolve()), "-q"]))
