# test_v2_evidence_status.py
"""Rendered V2 evidence status, source scoping, and raw citation regressions.

Version: 0.261.389
Implemented in: 0.261.388

Uses the shared local/Azure Playwright connection and real bundled components.
HTTP responses are synthetic; no production conversations or models are used.
"""

import json
from pathlib import Path

import pytest
from playwright.sync_api import expect

from ui_tests.fixtures.orchestration import harness_build
from ui_tests.fixtures.playwright_connection import connect_options


ROOT = Path(__file__).resolve().parents[1]
DOCUMENT = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
CITATION = f"{DOCUMENT}_1"
CONVERSATION = "evidence-status-conversation"
LABELS = {
    "partial": "Partial document evidence",
    "missing": "No supporting document evidence returned",
    "unavailable": "Some sources could not be checked",
}

__all__ = ["connect_options"]


def reply(state, identifier="evidence-answer"):
    sources = [{"name": "Guide.md", "document_id": DOCUMENT,
                "state": "complete" if state == "partial" else state,
                **({"evidence_count": 1 if state == "partial" else 0} if state != "unavailable" else {})}]
    if state == "partial":
        sources.append({"name": "Additional notes.md", "document_id": "other-document", "state": "missing", "evidence_count": 0})
    return {
        "id": identifier, "conversation_id": CONVERSATION, "role": "assistant",
        "content": f"The supported retention period is 30 days. \u3010{CITATION}\u3011" if state == "partial"
        else "The selected sources did not provide enough information to answer.",
        "augmented": True,
        "hybrid_citations": [{"citation_id": CITATION, "document_id": DOCUMENT,
                              "file_name": "Guide.md", "page_number": 1}] if state == "partial" else [],
        "metadata": {"evidence_status": {
            "version": 1, "scope": "returned_evidence", "state": state, "sources": sources,
            "suggestions": ["Add a relevant document or select another authorized source."],
        }},
    }


@pytest.mark.ui
@pytest.mark.parametrize("width", [390, 1440])
@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("state", ["partial", "missing", "unavailable"])
def test_evidence_notice_opens_scoped_source_details_and_document_pane(page, width, theme, state):
    harness_build.ensure_bundle()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.route("**/api/**", lambda route: route.fulfill(
        content_type="application/json", body=json.dumps({
            "success": True, "messages": [], "documents": [], "requests": [], "pending_actions": [], "actions": [],
        }),
    ))
    page.set_viewport_size({"width": width, "height": 1000})
    with harness_build.start_static_server() as origin:
        page.goto(f"{origin}/{harness_build.HARNESS_HTML_REL}")
        css = sorted((ROOT / "application" / "single_app" / "static" / "v2" / "assets").glob("*.css"))
        assert css, "Build V2 production assets before the browser regression."
        page.add_style_tag(url=f"{origin}/application/single_app/static/v2/assets/{css[0].name}")
        page.wait_for_function("() => Boolean(window.OrchHarness)")
        page.evaluate("""({message, conversation}) => {
            const H = window.OrchHarness;
            H.reset();
            H.stores.bootstrap.useBootstrapStore.setState({data: {
                user: {id: 'owner'}, settings: {}, features: {}, scope: {},
                catalogs: {models: [], agents: [], prompts: []},
            }});
            H.stores.chat.useChatStore.setState({
                activeConversationId: conversation, activeConversationKind: 'personal',
                messages: [message], streaming: false, loadingMessages: false,
                metadata: {}, metadataLoading: false, metadataError: null,
            });
            H.mount('mount-a', 'MessageList');
        }""", {"message": reply(state), "conversation": CONVERSATION})
        button = page.get_by_role("button", name=f"{LABELS[state]}. View source coverage", exact=True)
        expect(button).to_be_visible()
        page.evaluate("(dark) => document.documentElement.classList.toggle('dark', dark)", theme == "dark")
        expect(button).to_have_attribute("data-evidence-state", state)
        expect(button).to_have_attribute("aria-controls", "message-inspector-evidence-answer")
        button.focus()
        page.keyboard.press("Enter")
        expect(button).to_have_attribute("aria-expanded", "true")
        details = page.locator("#mount-a").get_by_role("region", name="Evidence for this answer")
        expect(details).to_be_visible()
        expect(details).to_contain_text("Guide.md")
        expect(details).to_contain_text("Add a relevant document")
        if (state, width, theme) == ("missing", 390, "dark"):
            artifacts = ROOT / "ui_tests" / "artifacts"
            artifacts.mkdir(exist_ok=True)
            page.screenshot(path=str(artifacts / "v2-evidence-missing-390.png"), full_page=True)
        page.evaluate("""() => {
            const H = window.OrchHarness;
            const layout = document.createElement('main');
            layout.className = 'relative flex h-screen min-w-0 overflow-hidden';
            const answer = document.getElementById('mount-a');
            const drawer = document.getElementById('mount-b');
            answer.className = 'min-w-0 flex-1 overflow-y-auto';
            drawer.className = 'h-full shrink-0';
            layout.append(answer, drawer);
            document.body.append(layout);
            H.stores.chat.useChatStore.setState({drawerMode: 'documents'});
            H.mount('mount-b', 'ConversationDrawer');
        }""")
        drawer = page.get_by_role("complementary", name="Conversation details")
        expect(drawer.get_by_role("region", name="Evidence for this answer")).to_be_visible()
        expect(drawer).to_contain_text("Guide.md")
        if state == "partial":
            expect(page.locator("#message-evidence-answer")).not_to_contain_text(CITATION)
            expect(drawer).to_contain_text("Additional notes.md")
        if state == "unavailable":
            expect(details).not_to_contain_text("No supporting document evidence returned")
        if (state, width, theme) == ("partial", 1440, "light"):
            artifacts = ROOT / "ui_tests" / "artifacts"
            artifacts.mkdir(exist_ok=True)
            page.screenshot(path=str(artifacts / f"v2-evidence-{state}-{width}.png"), full_page=True)
        for mask in ("partial", "full"):
            page.evaluate("""(mask) => {
                const H = window.OrchHarness;
                H.stores.chat.useChatStore.setState((current) => ({
                    messages: current.messages.map((message) => ({
                        ...message, metadata: {
                            ...message.metadata, masked: mask === 'full',
                            masked_ranges: mask === 'partial' ? [{start: 0, end: 4}] : [],
                        },
                    })),
                }));
            }""", mask)
            expect(page.locator("#mount-a").get_by_role("region", name="Evidence for this answer")).to_have_count(0)
            expect(drawer.get_by_role("region", name="Evidence for this answer")).to_have_count(0)
            expect(button).to_have_count(0)
        page.evaluate("""() => {
            const H = window.OrchHarness;
            H.stores.chat.useChatStore.setState({
                activeConversationId: 'another-conversation',
                messages: [{id: 'new-answer', conversation_id: 'another-conversation',
                            role: 'assistant', content: 'Ordinary chat.', metadata: {}}],
            });
        }""")
        expect(drawer.get_by_role("region", name="Evidence for this answer")).to_have_count(0)
    assert errors == []
