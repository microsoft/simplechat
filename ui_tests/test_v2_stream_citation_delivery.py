# test_v2_stream_citation_delivery.py
"""
UI regressions for live tool/web evidence and recorded tool outcomes.
Version: 0.261.417
Implemented in: 0.261.365

Drives the real send/SSE/store/message inspector locally with synthetic HTTP boundaries.
The existing Azure Playwright-compatible fixture also supports local browsers. No live
agents, actions, conversations, model requests, or connector requests are created.
"""

from pathlib import Path
import re

import pytest
from playwright.sync_api import expect

from ui_tests.fixtures.playwright_connection import connect_options  # noqa: F401
from ui_tests.fixtures.orchestration import harness_build


ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.ui
TOOL = {
    "tool_name": "Example.lookupRecord",
    "function_name": "lookupRecord",
    "plugin_name": "Example",
    "function_arguments": {"record_id": "record-42"},
    "function_result": {"amount": 125000, "status": "Awarded"},
    "success": True,
    "artifact_id": "reply_artifact_1",
}
WEB = {"title": "Record reference", "url": "https://example.test/reference"}


@pytest.fixture
def citation_page(page):
    harness_build.ensure_bundle()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    with harness_build.start_static_server() as origin:
        response = page.goto(f"{origin}/{harness_build.HARNESS_HTML_REL}")
        assert response is not None and response.ok
        page.wait_for_function("() => Boolean(window.OrchHarness)")
        styles = sorted((ROOT / "application" / "single_app" / "static" / "v2" / "assets").glob("*.css"))
        assert styles, "Build the V2 UI before checking the citation inspector."
        for stylesheet in styles:
            page.add_style_tag(content=stylesheet.read_text(encoding="utf-8"))
        yield page
    assert not errors, errors


def _send(page, fields):
    page.evaluate(
        """(fields) => {
            const H = window.OrchHarness;
            H.reset();
            window.evidenceRequests = [];
            window.evidenceFinal = {
                done: true, role: 'assistant', message_id: 'reply-evidence',
                conversation_id: 'evidence-chat', full_content: 'Model prose, not tool evidence.',
                metadata: {}, ...fields,
            };
            window.fetch = async (url, init = {}) => {
                const path = new URL(String(url), window.location.origin).pathname;
                window.evidenceRequests.push({ path, method: init.method ?? 'GET' });
                if (path === '/api/chat/stream') {
                    return new Response(`data: ${JSON.stringify(window.evidenceFinal)}\\n\\n`, {
                        headers: { 'Content-Type': 'text/event-stream' },
                    });
                }
                if (path === '/api/get_messages') {
                    return new Response(JSON.stringify({
                        messages: [{
                            ...window.evidenceFinal, id: 'reply-evidence',
                            content: window.evidenceFinal.full_content,
                        }],
                    }), { headers: { 'Content-Type': 'application/json' } });
                }
                return new Response(JSON.stringify({ success: true, messages: [], pending_actions: [] }), {
                    headers: { 'Content-Type': 'application/json' },
                });
            };
            H.stores.bootstrap.useBootstrapStore.setState({
                data: { features: {}, settings: {}, catalogs: { models: [], agents: [], prompts: [] },
                    user: { id: 'owner', display_name: 'Tester' }, scope: {} },
            });
            H.stores.chat.useChatStore.setState({
                activeConversationId: 'evidence-chat', activeConversationKind: 'personal',
                messages: [], streaming: false, loadingMessages: false,
            });
            H.mount('mount-a', 'MessageList');
            void H.stores.chat.useChatStore.getState().sendMessage('Look up record-42.', {});
        }""",
        fields,
    )
    page.wait_for_function(
        "() => window.OrchHarness.stores.chat.useChatStore.getState().messages.some(m => m.id === 'reply-evidence')"
    )
    requests = page.evaluate("() => window.evidenceRequests")
    assert sum(request["path"] == "/api/chat/stream" for request in requests) == 1
    assert not any("get_messages" in request["path"] for request in requests)
    return page.locator("#message-reply-evidence")


def _tool_details(message):
    message.hover()
    message.get_by_role("button", name=re.compile(r"^Show sources")).click()
    details = message.locator("details").filter(has=message.page.locator("summary", has_text="Example.lookupRecord"))
    expect(details).to_have_count(1)
    details.locator("summary").click()
    expect(details).to_contain_text("record-42")
    return details


@pytest.mark.parametrize("viewport", [{"width": 1440, "height": 900}, {"width": 390, "height": 844}])
def test_live_tool_and_web_evidence_match_reopened_message(citation_page, viewport):
    page = citation_page
    page.set_viewport_size(viewport)
    message = _send(page, {"agent_citations": [TOOL], "web_search_citations": [WEB]})
    details = _tool_details(message)
    expect(details).to_contain_text("Tool call succeeded")
    expect(details).to_contain_text("125000")
    expect(details).to_contain_text("Awarded")
    link = message.get_by_role("link", name="Record reference")
    expect(link).to_have_attribute("href", WEB["url"])
    expect(link).to_have_attribute("rel", "noopener noreferrer")
    expect(message).not_to_contain_text("This response did not cite any sources.")
    fits = message.evaluate("element => element.scrollWidth <= element.clientWidth + 1")
    assert fits

    page.evaluate("() => window.OrchHarness.stores.chat.useChatStore.getState().reloadMessages()")
    message.hover()
    # The inspector may remain open through the authoritative refresh.
    if not message.get_by_role("link", name="Record reference").is_visible():
        message.get_by_role("button", name=re.compile(r"^Show sources")).click()
    expect(message).to_contain_text("Example.lookupRecord")
    expect(message.get_by_role("link", name="Record reference")).to_be_visible()


@pytest.mark.parametrize("viewport", [{"width": 1440, "height": 900}, {"width": 390, "height": 844}])
@pytest.mark.parametrize("kind,parent", [("note", None), ("threaded_comment", None), ("threaded_comment", "root-budget")])
def test_native_annotation_first_preserves_streamed_and_saved_identity(citation_page, viewport, kind, parent):
    page = citation_page
    page.set_viewport_size(viewport)
    reference = {
        "producer": {"user_id": "owner", "conversation_id": "evidence-chat", "run_id": "native-run",
                     "step_id": "comments", "attempt_index": 1, "capability_id": "document_search"},
        "output_name": "prepared", "kind": "structured-v1", "manifest_sha256": "a" * 64,
    }
    citation = {
        "citation_id": "workbook:native-comments:2", "document_id": "workbook", "file_name": "review.xlsx",
        "location_label": "Location", "location_value": "Budget!B4", "sheet_name": "Budget",
        "native_evidence": reference, "source_version": 1, "annotation_id": "annotation-2",
    }
    annotation = {
        "id": "annotation-2", "kind": kind, "parent_id": parent, "sheet": "Budget", "cell": "B4",
        "author": "Reviewer A", "date": "2026-01-01T10:00:00Z", "cell_value": 15000, "resolved": False,
    }
    content = "Review (Source: review.xlsx, Worksheet cell: Budget!B4) [#workbook:native-comments:2]"
    message = _send(page, {"full_content": content, "hybrid_citations": [citation], "augmented": True})
    page.evaluate("""({annotation}) => {
        window.nativeRequests = [];
        window.nativeDenied = false;
        const originalFetch = window.fetch;
        window.fetch = async (url, init = {}) => {
            const path = new URL(String(url), location.origin).pathname;
            if (path === '/api/get_citation') {
                window.nativeRequests.push(JSON.parse(init.body));
                return new Response(JSON.stringify(window.nativeDenied
                    ? {error: 'The cited workbook or retained evidence is no longer available.'}
                    : {file_name: 'review.xlsx', document_id: 'workbook', native_annotation: annotation,
                       cited_text: 'Keep cap at 15000. <script>unsafe()</script>'}),
                    {status: window.nativeDenied ? 403 : 200, headers: {'Content-Type': 'application/json'}});
            }
            if (path === '/api/enhanced_citations/tabular_preview') {
                return new Response(JSON.stringify({
                    filename: 'review.xlsx', sheet_names: ['Budget'], selected_sheet: 'Budget',
                    columns: ['Amount'], rows: [['15000']], row_numbers: [4], total_rows: 1,
                    tables: [], start_row: 0, has_more: false,
                }), {headers: {'Content-Type': 'application/json'}});
            }
            return originalFetch(url, init);
        };
        const B = window.OrchHarness.stores.bootstrap.useBootstrapStore;
        B.setState({data: {...B.getState().data, features: {enable_enhanced_citations: true}}});
    }""", {"annotation": annotation})
    chip = message.get_by_role("button", name="review.xlsx Budget!B4", exact=True)
    chip.focus()
    chip.press("Enter")
    dialog = page.get_by_role("dialog", name="Citation", exact=True)
    expect(dialog.get_by_text("Author: Reviewer A", exact=True)).to_be_visible()
    expect(dialog.get_by_text("Saved cell value: 15000", exact=True)).to_be_visible()
    expect(dialog.get_by_text("Keep cap at 15000. <script>unsafe()</script>", exact=True)).to_be_visible()
    assert dialog.locator("script").count() == 0
    expect(page.get_by_role("dialog", name="Cited source", exact=True)).to_have_count(0)
    preview = dialog.get_by_role("button", name="Open workbook preview (separate from annotation evidence)", exact=True)
    expect(preview).to_be_visible()
    assert page.evaluate("() => window.nativeRequests[0]") == {
        "citation_id": citation["citation_id"], "document_id": "workbook", "page_number": "Budget!B4",
        "native_evidence": reference, "conversation_id": "evidence-chat",
    }
    assert dialog.evaluate("element => element.scrollWidth <= element.clientWidth")
    preview.click()
    source = page.get_by_role("dialog", name="Cited source", exact=True)
    expect(source).to_be_visible()
    source.get_by_role("button", name="Close cited source").click()
    expect(dialog.get_by_text("Author: Reviewer A", exact=True)).to_be_visible()
    dialog.get_by_role("button", name="Close citation", exact=True).click()
    page.evaluate("() => window.OrchHarness.stores.chat.useChatStore.getState().reloadMessages()")
    chip.click()
    expect(dialog.get_by_text("Author: Reviewer A", exact=True)).to_be_visible()
    requests = page.evaluate("() => window.nativeRequests")
    assert all(request == requests[0] for request in requests)
    dialog.get_by_role("button", name="Close citation", exact=True).click()
    page.evaluate("() => window.nativeDenied = true")
    chip.click()
    expect(dialog.get_by_text("The cited workbook or retained evidence is no longer available.", exact=True)).to_be_visible()
    expect(dialog.get_by_text("Author: Reviewer A", exact=True)).to_have_count(0)
    expect(dialog.get_by_role("button", name="Open workbook preview (separate from annotation evidence)", exact=True)).to_have_count(0)


@pytest.mark.parametrize("result", [{"error": "HTTP 502", "status_code": 502}, None])
def test_live_failed_tool_retains_error_arguments_and_available_result(citation_page, result):
    failure = {**TOOL, "success": False, "error_message": "Synthetic upstream unavailable.", "function_result": result}
    message = _send(citation_page, {"agent_citations": [failure]})
    details = _tool_details(message)
    expect(details).to_contain_text("Tool call failed")
    expect(details).to_contain_text("Synthetic upstream unavailable.")
    expect(details).not_to_contain_text("Tool call succeeded")
    if result is not None:
        expect(details).to_contain_text("HTTP 502")


def test_unknown_outcome_and_untrusted_error_render_as_text(citation_page):
    historical = {key: value for key, value in TOOL.items() if key != "success"}
    historical["error_message"] = '<img src=x onerror="window.toolInjected=true">'
    message = _send(citation_page, {"agent_citations": [historical]})
    details = _tool_details(message)
    expect(details).to_contain_text("Outcome not recorded")
    expect(details).to_contain_text(historical["error_message"])
    expect(details.locator("img")).to_have_count(0)
    injected = citation_page.evaluate("() => Boolean(window.toolInjected)")
    assert not injected


def test_web_only_reply_exposes_sources_without_reload(citation_page):
    message = _send(citation_page, {"web_search_citations": [WEB]})
    message.hover()
    message.get_by_role("button", name=re.compile(r"^Show sources")).click()
    expect(message.get_by_role("link", name="Record reference")).to_be_visible()


def test_reply_without_evidence_retains_honest_empty_state(citation_page):
    message = _send(citation_page, {})
    message.hover()
    message.get_by_role("button", name="Show sources", exact=True).click()
    expect(message).to_contain_text("This response did not cite any sources.")


@pytest.mark.parametrize("guard", [{"blocked": True}, {"role": "safety"}])
def test_moderated_reply_does_not_offer_suppressed_tool_or_web_evidence(citation_page, guard):
    message = _send(citation_page, {**guard, "agent_citations": [TOOL], "web_search_citations": [WEB]})
    expect(message.get_by_role("button", name=re.compile(r"^Show sources"))).to_have_count(0)
    expect(message).not_to_contain_text("Example.lookupRecord")
    expect(message.get_by_role("link", name="Record reference")).to_have_count(0)
