# test_chat_content_checks.py
"""
Browser regressions for chat content controls, reply replacement, and admin rechecks.
Version: 0.261.127
Implemented in: 0.261.127

Use real local classic assets and React components with synthetic, closed HTTP
boundaries. The shared connection fixture supports Azure Playwright with
DefaultAzureCredential or its existing local-browser fallback.
"""

import ast
import copy
import re
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import pytest
from jinja2 import ChoiceLoader, DictLoader
from playwright.sync_api import expect
from werkzeug.datastructures import MultiDict

from ui_tests.fixtures.playwright_connection import connect_options  # noqa: F401
from ui_tests.fixtures.content_screening_classic import ClassicScreeningFixture, ORIGIN
from ui_tests.test_v2_content_screening import ScreeningUiFixture, screening_admin_schema
from ui_tests.fixtures.orchestration import harness_build


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
sys.path.insert(0, str(APP))

from functions_chat_content_checks import CHAT_CONTENT_FORM_DEFAULTS, chat_content_form_updates


pytestmark = pytest.mark.ui
REMOVED = "This AI reply was removed because it did not meet the application's content rules."
CANARY = "private-reply-canary@example.test"
FORM = """
{% extends "base.html" %}
{% block content %}
<main class="container py-3"><form method="post" action="/chat-check-settings">
<input type="checkbox" id="enable_enhanced_citations" aria-label="Enhanced Citations" checked />
<ul class="nav nav-tabs">
  <li class="nav-item"><button type="button" id="content-screening-tab" class="nav-link active"
    data-bs-toggle="tab" data-bs-target="#content-screening">Content Screening</button></li>
  <li class="nav-item"><button type="button" id="content-safety-tab" class="nav-link"
    data-bs-toggle="tab" data-bs-target="#content-safety">Content Safety</button></li>
</ul>
<div class="tab-content">
{% include "admin/_panes/content-screening.html" %}
{% include "admin/_panes/content-safety.html" %}
</div>
<button type="submit" class="btn btn-primary">Save changes</button>
</form></main>
{% endblock %}
"""


class ClassicChecksUi(ClassicScreeningFixture):
    def __init__(self, page):
        super().__init__(page)
        self.values = {
            **CHAT_CONTENT_FORM_DEFAULTS, "enable_content_screening": True,
            "enable_content_safety": True, "enable_enhanced_citations": True,
        }
        self.form_saves = []
        self.rechecks = []
        self.check_fails = False
        self.unchecked = [{
            "source": "chat", "conversation_id": "conversation-1", "message_id": "reply-1",
            "role": "assistant", "etag": '"message-1"',
            "check": {
                "checkpoint": "chat_output", "status": "not_checked",
                "attempted_at": "2026-01-01T00:00:00+00:00",
                "scanners": [{
                    "scanner": "content_safety", "complete": False,
                    "error_code": "content_safety_unavailable",
                }],
            },
        }]

    def _environment(self):
        environment = super()._environment()
        environment.loader = ChoiceLoader([DictLoader({"chat-check-settings.html": FORM}), environment.loader])
        return environment

    def _markup(self, template):
        environment = self._environment()
        environment.globals["url_for"] = lambda endpoint, **values: "/static/" + values.get("filename", "")
        return environment.get_template(template).render(
            settings=self.values, app_settings={"app_title": "Synthetic content checks"},
            config={"VERSION": "0.261.127"}, admin_landing_tab="content-screening",
            session={"user": {"oid": "reviewer", "roles": ["Admin"]}},
        )

    def _route(self, route):
        path = urlsplit(route.request.url).path
        if path == "/chat-check-settings":
            if route.request.method == "POST":
                form = MultiDict(parse_qsl(route.request.post_data or "", keep_blank_values=True))
                updates = chat_content_form_updates(form, self.values)
                self.form_saves.append(updates)
                self.values.update(updates)
            route.fulfill(body=self._markup("chat-check-settings.html"), content_type="text/html")
        elif path == "/admin/safety_violations":
            route.fulfill(body=self._markup("admin_safety_violations.html"), content_type="text/html")
        elif path == "/api/safety/chat-checks":
            route.fulfill(json={"items": self.unchecked, "continuation": None})
        elif path == "/api/safety/chat-checks/recheck":
            self.rechecks.append(route.request.post_data_json)
            if self.check_fails:
                route.fulfill(json={"removed": False, "check": {"status": "not_checked"}})
            else:
                self.unchecked = []
                route.fulfill(json={"removed": True, "check": {"status": "findings"}})
        elif path == "/api/safety/logs/stats":
            route.fulfill(json={"total_count": 0, "new_count": 0, "in_review_count": 0, "actions": {}, "statuses": {}})
        elif path == "/api/safety/logs":
            route.fulfill(json={"logs": [], "page": 1, "page_size": 10, "total_count": 0})
        else:
            super()._route(route)


class V2ChecksUi(ScreeningUiFixture):
    def __init__(self, page):
        super().__init__(page)
        self.admin = True
        self.scan_enabled = True
        self.enhanced_citations_enabled = True
        self.content_safety_enabled = True
        self.values = {
            **CHAT_CONTENT_FORM_DEFAULTS, "enable_content_screening": True,
            "enable_content_safety": True, "enable_enhanced_citations": True,
        }

    def _dispatch(self, route, entry):
        if entry.path == "/api/v2/admin/settings" and entry.method == "GET":
            tree = ast.parse((APP / "admin_settings_fields.py").read_text(encoding="utf-8"))
            declaration = next(
                node.value for node in tree.body if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "ADMIN_SETTINGS_FIELDS" for target in node.targets)
            )
            safety = next(
                value for key, value in zip(declaration.keys, declaration.values)
                if isinstance(key, ast.Constant) and key.value == "content-safety-section"
            )
            schema = copy.deepcopy(screening_admin_schema())
            schema["content-safety-section"] = [ast.literal_eval(field) for field in safety.elts[:3]]
            self._json(route, {
                "settings": self.values,
                "field_schema": schema,
                "admin_nav": [{"id": "security", "label": "Security", "tabs": [
                    {"id": "content-screening", "label": "Content Screening", "sections": [
                        {"id": "content-screening-section", "label": "Content Screening"},
                    ]},
                    {"id": "content-safety", "label": "Content Safety", "sections": [
                        {"id": "content-safety-section", "label": "Content Safety"},
                    ]},
                ]}],
                "section_status": {}, "runtime_flags": {}, "suppressed_capabilities": [],
            })
        elif entry.path == "/api/v2/admin/settings" and entry.method == "PATCH":
            self.settings_writes.append(copy.deepcopy(entry.body))
            self.values.update(entry.body["settings"])
            self._json(route, {
                "success": True, "updated_keys": list(entry.body["settings"]),
                "settings": self.values, "warnings": {},
            })
        else:
            super()._dispatch(route, entry)


@pytest.mark.parametrize("width", [390, 1280])
def test_classic_checkpoint_switches_and_behaviors_round_trip(page, width):
    ui = ClassicChecksUi(page)
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(f"{ORIGIN}/chat-check-settings")
    expect(page.get_by_label("Screen workspace uploads", exact=True)).to_be_checked()
    page.get_by_label("Screen submitted chat messages", exact=True).check()
    page.get_by_label("Screen AI replies", exact=True).check()
    page.get_by_label("When to show AI replies", exact=True).select_option("check_before_display")
    page.get_by_label("When a chat check cannot finish", exact=True).select_option("block")
    page.get_by_role("tab", name="Content Safety", exact=True).click()
    expect(page.get_by_label("Check submitted messages with Content Safety", exact=True)).to_be_checked()
    page.get_by_label("Check AI replies with Content Safety", exact=True).check()
    page.get_by_role("button", name="Save changes", exact=True).click()
    expect(page.get_by_label("Screen AI replies", exact=True)).to_be_checked()
    expect(page.get_by_label("When to show AI replies", exact=True)).to_have_value("check_before_display")
    assert ui.form_saves[-1]["enable_content_safety_chat_output"] is True
    assert ui.form_saves[-1]["chat_content_scan_failure_action"] == "block"
    assert not ui.errors and not ui.unexpected and not ui.dialogs


def test_v2_checkpoint_switches_save_and_reload(page):
    ui = V2ChecksUi(page)
    ui.open("/admin")
    section = page.locator("#content-screening-section")
    section.get_by_role("button", name=re.compile("^Where to check")).click()
    section.get_by_role("button", name=re.compile("^Chat check behavior")).click()
    for label in ("Screen submitted chat messages", "Screen AI replies"):
        toggle = page.get_by_role("checkbox", name=re.compile(f"^{re.escape(label)}"))
        toggle.focus()
        toggle.press("Space")
        expect(toggle).to_be_checked()
    page.get_by_label("When to show AI replies", exact=True).select_option("check_before_display")
    page.get_by_label("When a chat check cannot finish", exact=True).select_option("block")
    page.get_by_role("button", name="Save changes", exact=True).click()
    expect(page.get_by_text("Saved 4 settings.", exact=True)).to_be_visible()
    page.reload()
    section.get_by_role("button", name=re.compile("^Where to check")).click()
    section.get_by_role("button", name=re.compile("^Chat check behavior")).click()
    expect(page.get_by_role("checkbox", name=re.compile("^Screen AI replies"))).to_be_checked()
    expect(page.get_by_label("When a chat check cannot finish", exact=True)).to_have_value("block")
    assert ui.values["enable_content_screening_chat_input"] is True
    assert not ui.errors and not ui.unexpected_requests


@pytest.mark.parametrize("check_fails", [False, True])
def test_admin_recheck_confirms_removal_or_keeps_unchecked_message(page, check_fails):
    ui = ClassicChecksUi(page)
    ui.check_fails = check_fails
    page.goto(f"{ORIGIN}/admin/safety_violations#unchecked-chat-content")
    region = page.get_by_role("region", name="Unchecked chat content")
    expect(region.get_by_text("reply-1", exact=True)).to_be_visible()
    region.get_by_role("button", name="Recheck", exact=True).click()
    dialog = page.get_by_role("dialog", name="Recheck this message?", exact=True)
    expect(dialog).to_be_visible()
    dialog.get_by_role("button", name="Recheck and apply rules", exact=True).click()
    if check_fails:
        expect(region.get_by_role("status")).to_contain_text("remains marked not checked")
        expect(region.get_by_text("reply-1", exact=True)).to_be_visible()
    else:
        expect(region.get_by_role("status")).to_contain_text("removed from saved chat")
        expect(region.get_by_text("reply-1", exact=True)).to_have_count(0)
    assert ui.rechecks == [{
        "source": "chat", "conversation_id": "conversation-1", "message_id": "reply-1", "etag": '"message-1"',
    }]
    assert not ui.errors and not ui.unexpected and not ui.dialogs


@pytest.mark.parametrize("interface", ["classic", "v2"])
@pytest.mark.parametrize("blocked", [False, True])
def test_streamed_answer_is_replaced_without_leaving_old_text(page, interface, blocked):
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    if interface == "v2":
        harness_build.ensure_bundle()
    with harness_build.start_static_server() as origin:
        path = (
            harness_build.HARNESS_HTML_REL if interface == "v2"
            else "ui_tests/fixtures/chat_thought_progress_harness.html"
        )
        response = page.goto(f"{origin}/{path}")
        assert response is not None and response.ok
        page.evaluate(
            """() => {
                const encoder = new TextEncoder();
                window.fetch = async (url) => {
                    if (new URL(String(url), window.location.origin).pathname === '/api/chat/stream') {
                        return new Response(new ReadableStream({
                            start(controller) {
                                window.pushChatFrame = (frame) => controller.enqueue(encoder.encode(`data: ${JSON.stringify(frame)}\\n\\n`));
                                window.closeChatFrames = () => controller.close();
                            },
                        }), { headers: { 'Content-Type': 'text/event-stream' } });
                    }
                    return new Response(JSON.stringify({ success: true, messages: [], scope_locked: false }), {
                        headers: { 'Content-Type': 'application/json' },
                    });
                };
            }"""
        )
        if interface == "v2":
            page.wait_for_function("() => Boolean(window.OrchHarness)")
            page.evaluate(
                """() => {
                    const H = window.OrchHarness;
                    H.reset();
                    H.stores.bootstrap.useBootstrapStore.setState({
                        data: { features: {}, settings: {}, catalogs: { models: [], agents: [], prompts: [] },
                            user: { id: 'owner', display_name: 'Tester' }, scope: {} },
                    });
                    H.stores.chat.useChatStore.setState({
                        activeConversationId: 'conversation-1', activeConversationKind: 'personal',
                        messages: [], streaming: false, loadingMessages: false,
                    });
                    H.mount('mount-a', 'MessageList');
                    void H.stores.chat.useChatStore.getState().sendMessage('Give a synthetic reply', {});
                }"""
            )
            root = page.locator("#mount-a")
        else:
            page.evaluate(
                """async () => {
                    window.appSettings = { enable_thoughts: false, enable_text_to_speech: false, documentActionCapabilities: {} };
                    window.enable_document_classification = false;
                    window.currentConversationId = 'conversation-1';
                    window.marked = { parse: text => String(text || '') };
                    window.DOMPurify = { sanitize: text => String(text || '') };
                    window.scrollChatToBottom = () => {};
                    const root = document.getElementById('test-root');
                    for (const [tag, id] of [['div', 'chatbox'], ['textarea', 'user-input'], ['button', 'send-btn'],
                        ['select', 'prompt-select'], ['div', 'prompt-selection-container'], ['select', 'model-select']]) {
                        const element = document.createElement(tag);
                        element.id = id;
                        root.appendChild(element);
                    }
                    const streaming = await import('/application/single_app/static/js/chat/chat-streaming.js');
                    void streaming.sendMessageWithStreaming(
                        { message: 'Give a synthetic reply', conversation_id: 'conversation-1' },
                        'pending-user', 'conversation-1', { allowRecovery: false },
                    );
                }"""
            )
            root = page.locator("#chatbox")
        page.wait_for_function("() => typeof window.pushChatFrame === 'function'")
        page.evaluate("(content) => window.pushChatFrame({ content })", CANARY)
        expect(root).to_contain_text(CANARY)
        final_text = REMOVED if blocked else "An allowed reply without a technical warning."
        page.evaluate(
            """({content, blocked}) => {
                window.pushChatFrame({
                    done: true, blocked, role: blocked ? 'safety' : 'assistant',
                    replace_content: true, content, full_content: content,
                    message_id: 'reply-1', conversation_id: 'conversation-1',
                    metadata: { content_moderation: { removed: blocked, revision: '2' } },
                });
                window.closeChatFrames();
            }""",
            {"content": final_text, "blocked": blocked},
        )
        expect(root).to_contain_text(final_text)
        expect(root).not_to_contain_text(CANARY)
        expect(root).not_to_contain_text("not_checked")
        expect(root).not_to_contain_text("not checked")
        if interface == "v2" and blocked:
            expect(root.get_by_role("status")).to_contain_text("Content check")
        assert not errors
