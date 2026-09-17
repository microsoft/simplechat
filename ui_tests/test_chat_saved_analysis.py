# test_chat_saved_analysis.py
"""
Saved Analyze findings, evidence, and explanation context in both chat interfaces.
Version: 0.261.115
Implemented in: 0.261.109

Runs the real classic message/stream modules and React MessageList/Composer/store.
Record/evidence requests cross the production Flask reader and serialized result
fixture; only external services, the message feed and model stream are deterministic.
The shared Playwright connection supports local or configured Azure browsers.

Build the existing V2 CSS into ignored test artifacts before running:
npm --prefix .\\application\\v2_ui run build -- --outDir ..\\..\\ui_tests\\artifacts\\saved-analysis
Run: .\\.venv\\Scripts\\python.exe -m pytest .\\ui_tests\\test_chat_saved_analysis.py -q
"""

import copy
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, quote, urlsplit

import pytest
from playwright.sync_api import expect

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "ui_tests" / "fixtures"
BUILD = REPO_ROOT / "ui_tests" / "artifacts" / "saved-analysis"
APP = REPO_ROOT / "application" / "single_app"
sys.path.insert(0, str(FIXTURES / "orchestration"))
sys.path.insert(0, str(FIXTURES))
sys.path.insert(0, str(REPO_ROOT / "functional_tests"))

# Reuse the actual authorized reader fixture and the existing browser bundle.
import harness_build as hb  # noqa: E402
from playwright_connection import connect_options  # noqa: E402,F401
from test_saved_analysis_routes import analysis_client  # noqa: E402,F401
from test_saved_analysis_service import saved_chat  # noqa: E402,F401

pytestmark = pytest.mark.ui
ORIGIN = "http://simplechat.test"
CONVERSATION = "conversation-1"
ANSWER = "The review found controls needing an owner."
EXPLANATION = "This explains the saved review, without a new source pass."


@pytest.fixture(scope="session")
def analysis_assets():
    hb.ensure_bundle()
    index = BUILD / "index.html"
    assert index.is_file(), "Build the V2 UI into ui_tests/artifacts/saved-analysis first."
    styles = re.findall(r'<link\b[^>]*href="([^"]+\.css)"', index.read_text(encoding="utf-8"))
    assert styles, "Run the existing V2 build command in this test's header to produce production CSS."
    return BUILD / "assets" / styles[0].rsplit("/", 1)[-1]


class AnalysisApi:
    """A real record-reader boundary plus deterministic chat transport."""

    def __init__(self, backend, css):
        self.client, self.identity, self.fixture = backend
        self.css = css
        self.message = copy.deepcopy(self.fixture["message"])
        self.message["agent_citations"] = []
        self.message["metadata"]["generated_analysis_artifacts"] = [{
            "capability": "analyze",
            "artifact_message_id": "generated-export",
            "conversation_id": CONVERSATION,
            "storage_scope": "chat",
            "file_name": "saved-findings.csv",
            "output_format": "csv",
            "row_count": 60,
            "suppress_assistant_text": True,
        }]
        self.messages = [self.message]
        self.requests = []
        self.unexpected = []
        self.pending_streams = []
        self.pending_pages = []
        self.hold_stream = False
        self.hold_page = False
        self.reconnect = False
        self.omit_final_text = False
        self.unsafe_values = False
        self.validation_status = None
        self.page_failures = 0
        self.download_failure = None
        self.download_filename = "saved-findings.csv"
        self.long_names = False

    def stream(self, route, *, replay=False):
        body = route.request.post_data_json if route.request.post_data else {}
        follow_up = bool(body.get("analysis_result_context"))
        message = copy.deepcopy(self.message)
        if follow_up:
            message["id"] = "explanation-1"
            message["content"] = EXPLANATION
        self.messages = [item for item in self.messages if item["id"] != message["id"]] + [message]
        final = {
            "done": True, "conversation_id": CONVERSATION, "message_id": message["id"],
            "metadata": message["metadata"],
        }
        if not self.omit_final_text:
            final["full_content"] = message["content"]
        frames = [{"content": message["content"]}, final]
        route.fulfill(
            content_type="text/event-stream",
            body="".join(f"data: {json.dumps(frame)}\n\n" for frame in frames),
        )
        if replay:
            self.reconnect = False

    def records(self, route):
        url = urlsplit(route.request.url)
        response = self.client.get(url.path + (f"?{url.query}" if url.query else ""))
        payload = response.json
        if response.status_code == 200:
            if self.validation_status and "validation" in payload:
                payload["validation"]["status"] = self.validation_status
            if self.unsafe_values:
                if payload.get("records"):
                    payload["records"][0]["values"]["finding"] = "<img src=x onerror=window.analysisXss=true>"
                    payload["records"][0]["source"]["file_name"] = "<script>unsafe()</script>.txt"
                if payload.get("evidence"):
                    payload["evidence"][0]["quote"] = "<img src=x onerror=window.analysisXss=true>"
            if self.long_names and payload.get("records"):
                payload["records"][0]["source"]["file_name"] = "Supplier_very_long_document_name_" * 12 + ".txt"
        route.fulfill(status=response.status_code, json=payload)

    def handle(self, route):
        request = route.request
        url = urlsplit(request.url)
        path = url.path
        if f"{url.scheme}://{url.netloc}" != ORIGIN:
            self.unexpected.append(f"Unexpected origin {url.netloc}")
            route.abort()
            return
        if path == "/harness.html":
            route.fulfill(path=str(hb.HERE / "harness.html"))
            return
        if path == "/harness.bundle.js":
            route.fulfill(path=str(hb.BUNDLE))
            return
        if path == "/classic.html":
            route.fulfill(path=str(FIXTURES / "chat_thought_progress_harness.html"))
            return
        if path == "/assets/chat.css":
            route.fulfill(path=str(self.css))
            return
        if path.startswith("/assets/") and (BUILD / path.lstrip("/")).is_file():
            route.fulfill(path=str(BUILD / path.lstrip("/")))
            return
        if path.startswith("/static/") or path.startswith("/application/single_app/static/"):
            relative = path.split("/static/", 1)[1]
            asset = APP / "static" / relative
            if asset.is_file():
                route.fulfill(path=str(asset))
                return
        if path == "/favicon.ico":
            route.fulfill(status=204)
            return
        self.requests.append({
            "method": request.method, "path": path, "query": parse_qs(url.query),
            "body": request.post_data_json if request.post_data else None,
        })
        if path == "/api/analysis_results":
            if self.page_failures:
                self.page_failures -= 1
                route.fulfill(status=503, json={"error": "PRIVATE_DIAGNOSTIC_NOT_FOR_DISPLAY"})
            elif self.hold_page:
                self.pending_pages.append(route)
            else:
                self.records(route)
            return
        if path == "/api/tabular/generated-output/runs/supporting-export":
            artifact = {
                **self.message["metadata"]["generated_analysis_artifacts"][0],
                "background_export": False, "status": "completed",
            }
            route.fulfill(json={"run": {
                "run_id": "supporting-export", "status": "completed",
                "progress_percent": 100, "generated_artifacts": [artifact],
            }})
            return
        if path == "/api/get_messages" or (path.startswith("/conversation/") and path.endswith("/messages")):
            conversation = parse_qs(url.query).get("conversation_id", [None])[0] or path.split("/")[2]
            route.fulfill(json={"messages": self.messages if conversation == CONVERSATION else []})
            return
        if path in (
            "/api/chat/stream", "/api/chat/document-action/stream",
            f"/api/collaboration/conversations/{CONVERSATION}/stream",
        ):
            if self.hold_stream:
                self.pending_streams.append(route)
            else:
                self.stream(route)
            return
        if path.startswith("/api/chat/stream/status/"):
            route.fulfill(json={"pending": self.reconnect, "status": "running" if self.reconnect else "idle"})
            return
        if path.startswith("/api/chat/stream/reattach/"):
            self.stream(route, replay=True)
            return
        if path.startswith("/api/conversations/") and path.endswith("/metadata"):
            route.fulfill(json={"conversation_id": path.split("/")[3], "title": "Saved review", "used_documents": []})
            return
        if path.endswith("/thoughts"):
            route.fulfill(json={"thoughts": []})
            return
        if path in ("/api/user/settings", "/api/chat/stream/client-event"):
            route.fulfill(json={"settings": {}, "selected_agent": None})
            return
        if path.startswith("/api/conversations/") and path.endswith("/mark-read"):
            route.fulfill(json={"success": True})
            return
        if path in ("/api/get_conversations", "/api/conversations/feed"):
            route.fulfill(json={"conversations": [], "has_more": False, "next_cursor": None})
            return
        if path == "/api/v2/orchestration/runs":
            route.fulfill(json={"runs": []})
            return
        if path in ("/api/documents", "/api/group_documents", "/api/public_workspace_documents"):
            route.fulfill(json={"documents": [], "total_count": 0})
            return
        if path.endswith("/tags"):
            route.fulfill(json={"tags": []})
            return
        if path == "/api/chat_artifacts/download":
            if self.download_failure is not None:
                route.fulfill(status=self.download_failure, json={"error": "PRIVATE_STORAGE_DIAGNOSTIC"})
                return
            route.fulfill(
                headers={"Content-Disposition": (
                    'attachment; filename="saved-findings.csv"; '
                    f"filename*=UTF-8''{quote(self.download_filename, safe='')}"
                )},
                content_type="text/csv", body="control,finding\nControl 0,Owner unassigned\n",
            )
            return
        self.unexpected.append(f"{request.method} {path}")
        route.fulfill(status=404, json={"error": "Unexpected test endpoint."})


@pytest.fixture
def analysis_api_factory():
    return AnalysisApi


@pytest.fixture(params=["classic", "v2"])
def analysis_ui(request, page, analysis_client, analysis_assets, analysis_api_factory):
    renderer = request.param
    errors = []
    api = analysis_api_factory(analysis_client, analysis_assets)
    page.route("**/*", api.handle)
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.set_viewport_size({"width": 1280, "height": 900})

    def mount(*, history=True, orchestration=False, shell=False, renderer_override=None):
        if (renderer_override or renderer) == "v2":
            page.goto(f"{ORIGIN}/harness.html")
            page.add_style_tag(url="/assets/chat.css")
            page.wait_for_function("() => Boolean(window.OrchHarness)")
            page.evaluate(
                """({conversationId, orchestration, shell}) => {
                    const H = window.OrchHarness;
                    H.reset();
                    H.stores.bootstrap.useBootstrapStore.setState({data: {
                        features: {enable_user_workspace: true, enable_chat_orchestration: orchestration},
                        orchestration: {enabled: orchestration, show_manual_controls: true,
                            default_approval_mode: 'manual', allow_user_approval_override: false},
                        catalogs: {prompts: [], models: [], agents: []},
                        settings: {}, user: {id: 'reader', display_name: 'Reader'},
                        scope: {groups: [], public_workspaces: []},
                    }});
                    H.stores.chat.useChatStore.setState({
                        activeConversationId: conversationId, activeConversationKind: 'personal',
                        messages: [], streaming: false, streamError: null,
                        analysisResultContext: null, analysisContextChosen: false, analysisContextRevision: 0,
                    });
                    H.mount('mount-a', shell ? 'ChatExperience' : 'PromptExperience', {},
                        {initialEntries: ['/chat']});
                    if (!shell) H.mount('mount-b', 'Toaster');
                    const store = () => H.stores.chat.useChatStore.getState();
                    window.analysisUI = {
                        reload: () => store().reloadMessages(),
                        open: () => store().selectConversation(conversationId, {kind: 'personal'}),
                        context: () => store().analysisResultContext,
                        change: id => store().selectConversation(id, {kind: 'personal'}),
                        fresh: () => store().startNewConversation(),
                        send: () => store().sendMessage('Explain the risks in these documents', {
                            documentSearch: true, webSearch: false, imageGeneration: false,
                            deepResearch: false, urlAccess: false, contextItems: [],
                        }),
                    };
                }""",
                {"conversationId": CONVERSATION, "orchestration": orchestration, "shell": shell},
            )
        else:
            page.goto(f"{ORIGIN}/classic.html")
            page.add_style_tag(url="/static/css/bootstrap.min.css")
            page.add_script_tag(url="/static/js/bootstrap/bootstrap.bundle.min.js")
            page.add_script_tag(url="/static/js/toast.js")
            page.add_script_tag(url="/static/js/chat/marked.min.js")
            page.add_script_tag(url="/static/js/chat/purify.min.js")
            page.evaluate(
                """(conversationId) => {
                    window.currentConversationId = conversationId;
                    window.currentUserId = 'reader';
                    window.enable_document_classification = false;
                    window.appSettings = {enable_thoughts: false, enable_text_to_speech: false,
                        documentActionCapabilities: {}};
                    window.scrollChatToBottom = () => {};
                    document.getElementById('test-root').innerHTML = `
                        <div id="toast-container" class="toast-container position-fixed top-0 end-0 p-3"></div>
                        <div id="chat-messages-container"><div id="chatbox"></div></div>
                        <div class="chat-input-container"><div id="normal-input-container">
                            <textarea id="user-input" aria-label="Message"></textarea>
                            <button id="send-btn" type="button">Send Message</button>
                        </div></div>
                        <div id="prompt-selection-container"><select id="prompt-select"></select></div>
                        <select id="model-select"><option value="gpt-4o">gpt-4o</option></select>
                        <select id="document-select" multiple></select>
                        <select id="document-action-select" aria-label="Document action">
                            <option value="none">Search</option><option value="analyze">Analyze</option>
                        </select>`;
                }""",
                CONVERSATION,
            )
            page.evaluate(
                """async (conversationId) => {
                    const messages = await import('/static/js/chat/chat-messages.js');
                    const streaming = await import('/static/js/chat/chat-streaming.js');
                    const analysis = await import('/static/js/chat/chat-analysis-results.js');
                    window.analysisUI = {
                        reload: () => messages.loadMessages(conversationId),
                        open: async () => {
                            await messages.loadMessages(conversationId);
                            await streaming.reattachStreamingConversation(conversationId);
                        },
                        context: () => analysis.getSavedAnalysisContext(),
                        change: id => {
                            window.currentConversationId = id;
                            window.dispatchEvent(new CustomEvent('chat:conversation-context-changed',
                                {detail: {conversationId: id, reason: 'select'}}));
                            return messages.loadMessages(id);
                        },
                        fresh: () => {
                            window.currentConversationId = null;
                            window.dispatchEvent(new CustomEvent('chat:conversation-context-changed',
                                {detail: {conversationId: null, reason: 'new'}}));
                        },
                        send: () => streaming.sendMessageWithStreaming(
                            {message: 'Explain the risks in these documents', conversation_id: conversationId},
                            null, conversationId),
                    };
                }""",
                CONVERSATION,
            )
        if history:
            page.evaluate("() => window.analysisUI.open()")

    ui = SimpleNamespace(page=page, api=api, renderer=renderer, mount=mount)
    yield ui
    assert not errors, errors
    assert not api.unexpected, api.unexpected


def result(ui):
    return ui.page.get_by_role("region", name="Saved analysis").first


def context(ui):
    return ui.page.evaluate("() => window.analysisUI.context()")


def expected_context(ui):
    return {key: ui.api.fixture["descriptor"][key] for key in ("conversation_id", "message_id", "result_sha256")}


def download_button(ui):
    name = "Download saved-findings.csv" if ui.renderer == "classic" else "Download CSV"
    return ui.page.get_by_role("button", name=name, exact=True)


def choose_new_source(ui):
    if ui.renderer == "classic":
        ui.page.get_by_label("Document action").select_option("analyze")
    else:
        ui.page.get_by_title("Documents", exact=True).click()


def test_saved_analysis_page_two_evidence_download_and_safe_text(analysis_ui):
    ui = analysis_ui
    ui.api.unsafe_values = True
    ui.mount()
    expect(ui.page.get_by_text(ANSWER, exact=True).first).to_be_visible()
    expect(result(ui)).to_contain_text("0 of 60 records displayed")
    assert context(ui) == expected_context(ui)
    assert not [item for item in ui.api.requests if item["path"] == "/api/analysis_results"]
    diagnostics = result(ui).get_by_role("link", name="View diagnostics as JSON (opens a new tab)")
    expect(diagnostics).to_be_visible()
    diagnostic_url = urlsplit(diagnostics.get_attribute("href"))
    assert diagnostic_url.path == "/api/analysis_results"
    assert parse_qs(diagnostic_url.query) == {
        **{key: [value] for key, value in expected_context(ui).items()},
        "representation": ["diagnostics"],
    }
    expect(diagnostics).to_have_attribute("rel", "noopener noreferrer")
    disclosure = result(ui).locator("summary").filter(has_text="Findings and limitations")
    disclosure.focus()
    disclosure.press("Enter")
    expect(result(ui)).to_contain_text("Showing 1–25 of 60 records")
    expect(result(ui)).to_contain_text("1 of 1 sources on this page")
    expect(result(ui)).to_contain_text("<img src=x onerror=window.analysisXss=true>")
    assert result(ui).locator("img, script").count() == 0
    assert not ui.page.evaluate("Boolean(window.analysisXss)")
    result(ui).get_by_role("button", name="Next findings", exact=True).click()
    expect(result(ui)).to_contain_text("Showing 26–50 of 60 records")
    expect(result(ui)).to_contain_text("Control 25")
    expect(result(ui)).not_to_contain_text("Control 0")
    result(ui).locator("summary").filter(has_text="Evidence for finding record-25").click()
    expect(result(ui).get_by_role("blockquote")).to_contain_text("<img src=x onerror=window.analysisXss=true>")
    expect(result(ui)).to_contain_text("page 26")
    reads = [item["query"] for item in ui.api.requests if item["path"] == "/api/analysis_results"]
    assert reads[1]["offset"] == ["25"]
    assert reads[1]["limit"] == ["25"]
    assert reads[2]["record_id"] == ["record-25"]
    assert all(query["result_sha256"] == [expected_context(ui)["result_sha256"]] for query in reads)
    expect(ui.page.get_by_text(ANSWER, exact=True).first).to_be_visible()
    expect(result(ui)).not_to_contain_text("RAW-NOTE-ONLY")
    ui.page.locator("summary").filter(has_text="Downloads").click()
    with ui.page.expect_download() as downloaded:
        download_button(ui).click()
    assert downloaded.value.suggested_filename == "saved-findings.csv"
    ui.page.set_viewport_size({"width": 390, "height": 844})
    expect(result(ui)).to_be_visible()
    assert ui.page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")


def test_completion_and_reconnect_keep_answer_and_select_followup(analysis_ui):
    ui = analysis_ui
    ui.api.messages = []
    ui.api.omit_final_text = True
    ui.mount(history=False)
    ui.page.evaluate("() => window.analysisUI.send()")
    expect(ui.page.get_by_text(ANSWER, exact=True).first).to_be_visible()
    expect(result(ui)).to_be_visible()
    assert context(ui) == expected_context(ui)
    ui.api.messages = []
    ui.api.reconnect = True
    ui.mount()
    expect(ui.page.get_by_text(ANSWER, exact=True).first).to_be_visible()
    expect(result(ui)).to_be_visible()
    assert context(ui) == expected_context(ui)
    assert len([item for item in ui.api.requests if item["path"].startswith("/api/chat/stream/reattach/")]) == 1


@pytest.mark.parametrize("status", [200, 401, 403, 404, 409, 500, 503])
def test_download_errors_stay_in_chat_and_can_be_retried(analysis_ui, status):
    ui = analysis_ui
    ui.api.download_failure = status
    ui.mount()
    original_url = ui.page.url
    downloads = []
    ui.page.on("download", lambda download: downloads.append(download))
    ui.page.locator("summary").filter(has_text="Downloads").click()
    download_button(ui).click()
    expect(ui.page.get_by_text(
        "The artifact could not be downloaded. Refresh the conversation and try again.", exact=True,
    )).to_be_visible()
    expect(download_button(ui)).to_be_enabled()
    expect(ui.page.get_by_text(ANSWER, exact=True).first).to_be_visible()
    assert ui.page.url == original_url and not downloads
    assert "PRIVATE_STORAGE_DIAGNOSTIC" not in ui.page.locator("body").inner_text()
    ui.api.download_failure = None
    with ui.page.expect_download() as downloaded:
        download_button(ui).click()
    assert downloaded.value.suggested_filename == "saved-findings.csv"
    assert Path(downloaded.value.path()).read_bytes() == b"control,finding\nControl 0,Owner unassigned\n"
    assert ui.page.url == original_url


@pytest.mark.parametrize("analysis_ui", ["v2"], indirect=True)
@pytest.mark.parametrize("width", [390, 1280])
def test_analysis_with_expanded_navigation_has_only_local_table_scrolling(analysis_ui, width):
    ui = analysis_ui
    ui.page.set_viewport_size({"width": width, "height": 844})
    ui.api.long_names = True
    ui.api.message["metadata"]["generated_analysis_artifacts"][0]["file_name"] = (
        "Supplier_very_long_document_name_" * 12 + ".csv"
    )
    ui.mount(shell=True)
    expect(ui.page.get_by_role("navigation", name="Primary")).to_be_visible()
    expand = ui.page.get_by_role("button", name="Expand navigation", exact=True)
    if expand.is_visible():
        expand.click()
    expect(ui.page.get_by_role("button", name="Collapse navigation", exact=True)).to_be_visible()
    dimensions = ui.page.evaluate("({viewport: innerWidth, document: document.documentElement.scrollWidth})")
    assert dimensions["document"] <= width + 1, dimensions
    ui.page.get_by_role("button", name="Collapse navigation", exact=True).click()
    result(ui).locator("summary").filter(has_text="Findings and limitations").click()
    expect(result(ui)).to_contain_text("Showing 1–25 of 60 records")
    result(ui).locator("summary").filter(has_text="Evidence for finding record-0").click()
    expect(result(ui).get_by_role("blockquote")).to_be_visible()
    ui.page.locator("summary").filter(has_text="Downloads").click()
    button = download_button(ui)
    button.scroll_into_view_if_needed()
    expect(button).to_be_in_viewport()
    box = button.bounding_box()
    assert box and box["x"] >= 0 and box["x"] + box["width"] <= width + 1
    assert ui.page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
    with ui.page.expect_download() as downloaded:
        button.click()
    assert Path(downloaded.value.path()).read_bytes() == b"control,finding\nControl 0,Owner unassigned\n"


def test_download_prefers_the_server_utf8_filename(analysis_ui):
    ui = analysis_ui
    ui.api.download_filename = "R\u00e9sum\u00e9 findings.csv"
    ui.mount()
    ui.page.locator("summary").filter(has_text="Downloads").click()
    with ui.page.expect_download() as downloaded:
        download_button(ui).click()
    assert downloaded.value.suggested_filename == ui.api.download_filename


def test_saved_explanation_request_bypasses_sources_and_orchestration(analysis_ui):
    ui = analysis_ui
    ui.mount(orchestration=True)
    result(ui).get_by_role("button", name="Ask about this analysis", exact=True).click()
    expect(ui.page.get_by_text("Explaining the saved analysis", exact=False)).to_be_visible()
    draft = ui.page.get_by_role("textbox", name="Message", exact=True)
    draft.fill("Explain the finding on the second page")
    draft.press("Enter")
    expect(ui.page.get_by_text(EXPLANATION, exact=True).first).to_be_visible()
    posts = [item for item in ui.api.requests if item["method"] == "POST" and item["path"] == "/api/chat/stream"]
    assert len(posts) == 1
    body = posts[0]["body"]
    assert body["analysis_result_context"] == expected_context(ui)
    for key in ("hybrid_search", "web_search_enabled", "source_review_enabled", "deep_research_enabled", "url_access_enabled", "image_generation"):
        assert body[key] is False
    assert not body["selected_document_ids"]
    assert "document_action" not in body and "analyze" not in body
    assert not [item for item in ui.api.requests if item["path"].startswith("/api/v2/orchestration/")]
    assert context(ui) == expected_context(ui), "Explanation messages keep the original result pointer."
    ui.page.get_by_role("button", name="Remove saved analysis context").click()
    assert context(ui) is None
    ui.page.evaluate("() => window.analysisUI.reload()")
    assert context(ui) is None, "History hydration must not undo the user's removal."
    ui.page.evaluate("() => window.analysisUI.open()")
    assert context(ui) is None, "Reselecting the same conversation must preserve explicit context removal."
    result(ui).get_by_role("button", name="Ask about this analysis", exact=True).click()
    choose_new_source(ui)
    assert context(ui) is None
    ui.page.evaluate("() => window.analysisUI.fresh()")
    assert context(ui) is None


@pytest.mark.parametrize("status", [401, 403, 404, 409])
def test_denied_missing_and_stale_results_are_visible_not_empty_success(analysis_ui, status):
    ui = analysis_ui
    if status == 401:
        ui.api.identity["user_id"] = None
    elif status == 403:
        ui.api.fixture["state"]["source_allowed"] = False
    elif status == 404:
        ui.api.message["metadata"]["saved_analysis"]["message_id"] = "missing-message"
    else:
        ui.api.message["metadata"]["saved_analysis"]["result_sha256"] = "0" * 64
    ui.mount()
    result(ui).locator("summary").filter(has_text="Findings and limitations").click()
    expect(result(ui)).to_contain_text("stale" if status == 409 else "unavailable")
    expect(result(ui).get_by_role("button", name="Ask about this analysis")).to_have_count(0)
    expect(download_button(ui)).not_to_be_visible()
    expect(result(ui)).not_to_contain_text("No accepted findings")
    assert context(ui) is None


@pytest.mark.parametrize("status,notice", [
    ("pending", "Validation pending"),
    ("partial", "Partial analysis"),
    ("invalid", "Validation failed"),
    ("not_validated", "Not validated"),
])
def test_validation_state_is_not_execution_completion(analysis_ui, status, notice):
    ui = analysis_ui
    ui.api.validation_status = status
    ui.api.message["metadata"]["saved_analysis"]["validation_status"] = status
    ui.mount()
    expect(result(ui)).to_contain_text(notice)
    result(ui).locator("summary").filter(has_text="Findings and limitations").click()
    expect(result(ui)).to_contain_text("Showing 1–25")
    expect(result(ui)).to_contain_text(notice)
    expect(result(ui)).to_contain_text("Judgments are not independently verified.")


def test_unavailable_or_masked_history_exposes_no_saved_result_controls(analysis_ui):
    ui = analysis_ui
    ui.api.message["content"] = "This saved analysis is unavailable."
    ui.api.message["metadata"]["saved_analysis"]["available"] = False
    ui.mount()
    expect(result(ui)).to_contain_text("unavailable")
    expect(ui.page.get_by_role("button", name="Ask about this analysis")).to_have_count(0)
    assert context(ui) is None
    assert not [item for item in ui.api.requests if item["path"] == "/api/analysis_results"]
    ui.api.message["metadata"]["saved_analysis"]["available"] = True
    ui.api.message["metadata"]["masked"] = True
    ui.page.evaluate("() => window.analysisUI.reload()")
    expect(ui.page.get_by_role("button", name="Ask about this analysis")).not_to_be_visible()
    expect(download_button(ui)).not_to_be_visible()
    assert context(ui) is None


def test_explicit_source_choice_wins_over_late_completion(analysis_ui):
    ui = analysis_ui
    ui.api.hold_stream = True
    ui.api.messages = []
    ui.mount(history=False)
    with ui.page.expect_request("**/api/chat/stream"):
        ui.page.evaluate("() => { void window.analysisUI.send(); }")
    choose_new_source(ui)
    assert context(ui) is None
    assert len(ui.api.pending_streams) == 1
    ui.api.stream(ui.api.pending_streams.pop())
    expect(result(ui)).to_be_visible()
    assert context(ui) is None
    ui.page.evaluate("() => window.analysisUI.reload()")
    assert context(ui) is None


def test_late_findings_response_cannot_follow_conversation_navigation(analysis_ui):
    ui = analysis_ui
    ui.api.hold_page = True
    ui.mount()
    with ui.page.expect_request("**/api/analysis_results?*"):
        result(ui).locator("summary").filter(has_text="Findings and limitations").click()
    ui.page.evaluate("() => window.analysisUI.change('another-conversation')")
    assert context(ui) is None
    for pending in ui.api.pending_pages:
        ui.api.records(pending)
    expect(ui.page.get_by_text("Control 0", exact=True)).to_have_count(0)
    expect(ui.page.get_by_role("region", name="Saved analysis")).to_have_count(0)


def test_supporting_export_completion_never_replaces_the_answer(analysis_ui):
    ui = analysis_ui
    artifact = ui.api.message["metadata"]["generated_analysis_artifacts"][0]
    artifact.update({"background_export": True, "export_run_id": "supporting-export", "status": "running"})
    ui.mount()
    expect(ui.page.get_by_text(ANSWER, exact=True).first).to_be_visible()
    ui.page.locator("summary").filter(has_text="Downloads").click()
    expect(download_button(ui)).to_be_visible(timeout=10000)
    expect(ui.page.get_by_text(ANSWER, exact=True).first).to_be_visible()
    expect(result(ui)).to_be_visible()
    assert context(ui) == expected_context(ui)


def test_evidence_rechecks_access_and_removes_the_previously_loaded_page(analysis_ui):
    ui = analysis_ui
    ui.mount()
    result(ui).locator("summary").filter(has_text="Findings and limitations").click()
    expect(result(ui)).to_contain_text("Control 0")
    ui.api.fixture["state"]["source_allowed"] = False
    result(ui).locator("summary").filter(has_text="Evidence for finding record-0").click()
    expect(result(ui)).to_contain_text("unavailable")
    expect(result(ui)).not_to_contain_text("Control 0")
    expect(download_button(ui)).not_to_be_visible()
    assert context(ui) is None


def test_transient_page_failure_can_retry_without_exposing_diagnostics(analysis_ui):
    ui = analysis_ui
    ui.api.page_failures = 1
    ui.mount()
    result(ui).locator("summary").filter(has_text="Findings and limitations").click()
    expect(result(ui).get_by_role("button", name="Retry findings")).to_be_visible()
    expect(result(ui)).not_to_contain_text("PRIVATE_DIAGNOSTIC")
    result(ui).get_by_role("button", name="Retry findings").click()
    expect(result(ui)).to_contain_text("Showing 1–25")
    result(ui).locator("summary").filter(has_text="Findings and limitations").click()
    expect(result(ui)).to_contain_text("0 of 60 records displayed")


def test_late_stream_completion_cannot_reselect_another_conversations_analysis(analysis_ui):
    ui = analysis_ui
    ui.api.messages = []
    ui.api.hold_stream = True
    ui.mount(history=False)
    with ui.page.expect_request("**/api/chat/stream"):
        ui.page.evaluate("() => { void window.analysisUI.send(); }")
    ui.page.evaluate("() => window.analysisUI.change('another-conversation')")
    for pending in ui.api.pending_streams:
        ui.api.stream(pending)
    expect(ui.page.get_by_role("region", name="Saved analysis")).to_have_count(0)
    expect(ui.page.get_by_text(ANSWER, exact=True)).to_have_count(0)
    assert context(ui) is None


@pytest.mark.parametrize("analysis_ui", ["v2"], indirect=True)
def test_orchestrated_completion_adopts_only_its_saved_public_pointer(analysis_ui):
    ui = analysis_ui
    ui.api.messages = []
    ui.mount(history=False, orchestration=True)
    ui.page.evaluate(
        """(message) => {
            const store = window.OrchHarness.stores.chat.useChatStore.getState;
            store().beginOrchestrationTurn(message.conversation_id, 'Analyze the documents');
            store().settleOrchestrationTurn(message.conversation_id, {
                status: 'completed', accumulated: message.content,
                event: {done: true, message_id: message.id, full_content: message.content,
                    conversation_id: message.conversation_id, metadata: message.metadata},
            });
        }""",
        ui.api.message,
    )
    expect(ui.page.get_by_text(ANSWER, exact=True)).to_be_visible()
    expect(result(ui)).to_be_visible()
    assert context(ui) == expected_context(ui)


@pytest.mark.parametrize("analysis_ui", ["v2"], indirect=True)
def test_saved_records_are_not_misinterpreted_as_answer_mask_offsets(analysis_ui):
    ui = analysis_ui
    ui.mount()
    select_text = """element => {
        const range = document.createRange();
        range.selectNodeContents(element);
        const selection = window.getSelection();
        selection.removeAllRanges();
        selection.addRange(range);
        element.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
    }"""
    ui.page.get_by_text(ANSWER, exact=True).evaluate(select_text)
    expect(ui.page.get_by_role("button", name="Mask selection", exact=True)).to_be_visible()
    result(ui).locator("summary").filter(has_text="Findings and limitations").click()
    result(ui).get_by_text("Control 0", exact=True).evaluate(select_text)
    expect(ui.page.get_by_role("button", name="Mask selection", exact=True)).not_to_be_visible()


def test_shared_followup_uses_the_public_pointer_without_source_invocation(analysis_ui):
    ui = analysis_ui
    ui.mount()
    if ui.renderer == "classic":
        sent = ui.page.evaluate(
            """async () => {
                const messages = await import('/static/js/chat/chat-messages.js');
                const body = messages.buildChatRequestPayload('Explain the saved review', 'conversation-1');
                return {messageData: body, invocationTarget: messages.buildCollaborativeInvocationTarget(body)};
            }"""
        )
        body, target = sent["messageData"], sent["invocationTarget"]
    else:
        ui.page.evaluate(
            """async () => {
                const H = window.OrchHarness;
                H.stores.chat.useChatStore.setState({activeConversationKind: 'collaborative'});
                H.stores.collaboration.useCollaborationStore.getState().setActiveConversation('conversation-1');
                H.stores.collaboration.useCollaborationStore.setState({
                    conversation: {id: 'conversation-1', can_post_messages: true, participants: []},
                });
                await H.stores.chat.useChatStore.getState().sendMessage('Explain the saved review', {
                    documentSearch: true, webSearch: true, imageGeneration: true,
                    deepResearch: true, urlAccess: true, contextItems: [],
                });
            }"""
        )
        expect(ui.page.get_by_text(EXPLANATION, exact=True)).to_be_visible()
        body = next(item["body"] for item in ui.api.requests if item["path"].endswith("/conversation-1/stream"))
        target = body["invocation_target"]
    assert body["analysis_result_context"] == expected_context(ui)
    assert target["target_type"] == "model"
    assert target["source_mode"] == "saved_analysis"
    assert body["hybrid_search"] is False and body["image_generation"] is False
    assert not body["selected_document_ids"]
