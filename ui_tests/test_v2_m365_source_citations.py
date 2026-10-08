# test_v2_m365_source_citations.py
"""
UI test for Microsoft 365 items as first-class citations in the V2 and classic chat.
Version: 0.261.303
Implemented in: 0.261.303

This test ensures that an answer citing SharePoint or OneDrive files, emails and calendar events
renders compact citation chips in V2 that open a source card with the item's details and an "Open
in SharePoint / OneDrive / Outlook" link with safe attributes, never calling the workspace
citation endpoint; that a record the message no longer has shows a friendly notice; that the V2
chat request carries the browser time zone; that the Documents pane lists the items under
SharePoint & OneDrive, Email and Calendar with "Open online" links, dropping any non-https link;
and that the classic chat links each item to where it lives without fetching a passage.

It drives the real bundled V2 components and the real classic modules over a local static server
with synthetic HTTP boundaries, so no Azure credentials or network access are needed.
"""

import json
import sys
from pathlib import Path

import pytest
from playwright.sync_api import expect

from ui_tests.fixtures.playwright_connection import connect_options  # noqa: F401
from ui_tests.fixtures.orchestration import harness_build

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402


pytestmark = pytest.mark.ui
IMPLEMENTED_IN = "0.261.303"
CONVERSATION_ID = "conversation-m365"
OUTLOOK_LINK = "https://outlook.office365.com/owa/?ItemID=AAMkAD%2Bx&exvsurl=1&viewmodel=ReadMessageItem"
EVENT_LINK = "https://outlook.office365.com/owa/?itemid=AAMkAE&exvsurl=1&path=/calendar/item"
SPO_LINK = "https://contoso.sharepoint.com/sites/team/Shared%20Documents/20170010188.pdf"
EMAIL_ID = "m365-1a2b3c4d5e6f7a8b"
EVENT_ID = "m365-2b3c4d5e6f7a8b9c"
FILE_ID = "m365-3c4d5e6f7a8b9c0d"
UNSAFE_ID = "m365-4d5e6f7a8b9c0d1e"
MISSING_ID = "m365-ffffffffffffffff"

EMAIL = {
    "citation_id": EMAIL_ID, "kind": "email", "source": "email", "title": "PIM: Role activated",
    "location_label": "Email", "from_name": "Microsoft Security", "from_address": "security@contoso.com",
    "received_at": "2026-10-07T16:52:00Z", "received_display": "Oct 7, 2026, 12:52 PM EDT",
    "is_read": False, "importance": "high", "preview": "Your role assignment was activated.",
    "web_url": OUTLOOK_LINK, "cited": True, "data_user_id": "owner",
}
EVENT = {
    "citation_id": EVENT_ID, "kind": "event", "source": "calendar", "title": "Standup",
    "location_label": "Calendar", "start": "2026-10-08T18:00:00Z", "end": "2026-10-08T18:30:00Z",
    "is_all_day": False, "when_display": "Thu, Oct 8, 2026, 2:00 PM \u2013 2:30 PM EDT",
    "location": "Teams", "organizer_name": "Ann Lee", "web_url": EVENT_LINK, "cited": True,
}
FILE = {
    "citation_id": FILE_ID, "kind": "file", "source": "spo", "title": "20170010188.pdf",
    "file_name": "20170010188.pdf", "location_label": "SharePoint", "mime_type": "application/pdf",
    "size_bytes": 2048, "modified_at": "2026-09-01T10:00:00Z", "modified_display": "Sep 1, 2026",
    "web_url": SPO_LINK, "cited": True,
}
UNSAFE = {
    "citation_id": UNSAFE_ID, "kind": "file", "source": "onedrive", "title": "notes.docx",
    "file_name": "notes.docx", "location_label": "OneDrive", "web_url": "javascript:alert(1)",
    "content_read": True, "cited": False,
}
ANSWER = (
    "2 most recent emails, newest first:\n\n"
    "1. **PIM: Role activated** \u2014 Microsoft Security, Oct 7, 2026, 12:52 PM EDT \u00b7 Unread "
    f"(Source: PIM: Role activated, Location: Email) [#{EMAIL_ID}]\n"
    "2. **Standup** \u2014 Thu, Oct 8, 2026, 2:00 PM \u2013 2:30 PM EDT \u00b7 Teams "
    f"(Source: Standup, Location: Calendar) [#{EVENT_ID}]\n\n"
    "The swab tool supports planetary protection "
    f"(Source: 20170010188.pdf, Location: SharePoint) [#{FILE_ID}]. "
    f"An earlier figure came from a message that is gone (Source: Old budget, Location: Email) [#{MISSING_ID}]."
)


def _open_v2_harness(page, origin):
    response = page.goto(f"{origin}/{harness_build.HARNESS_HTML_REL}")
    assert response is not None and response.ok
    page.wait_for_function("() => Boolean(window.OrchHarness)")


def _citation_requests(page):
    requests = []
    page.on("request", lambda request: requests.append(request.url) if "/api/get_citation" in request.url else None)
    return requests


def _expect_safe_link(link, href):
    expect(link).to_have_attribute("href", href)
    expect(link).to_have_attribute("target", "_blank")
    expect(link).to_have_attribute("rel", "noopener noreferrer")


def test_version_is_at_least_the_implementing_release():
    assert_app_version_at_least(IMPLEMENTED_IN)


def test_streamed_answer_chips_open_source_cards_with_safe_links(page):
    try:
        harness_build.ensure_bundle()
    except harness_build.HarnessUnavailable as exc:
        pytest.skip(str(exc))
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    citation_requests = _citation_requests(page)
    with harness_build.start_static_server() as origin:
        _open_v2_harness(page, origin)
        page.evaluate(
            """() => {
                const encoder = new TextEncoder();
                window.sentChatBodies = [];
                window.fetch = async (url, init) => {
                    if (new URL(String(url), window.location.origin).pathname === '/api/chat/stream') {
                        window.sentChatBodies.push(JSON.parse(init.body));
                        return new Response(new ReadableStream({
                            start(controller) {
                                window.pushChatFrame = (frame) => controller.enqueue(encoder.encode(`data: ${JSON.stringify(frame)}\\n\\n`));
                                window.closeChatFrames = () => controller.close();
                            },
                        }), { headers: { 'Content-Type': 'text/event-stream' } });
                    }
                    return new Response(JSON.stringify({ success: true, messages: [] }), {
                        headers: { 'Content-Type': 'application/json' },
                    });
                };
                const H = window.OrchHarness;
                H.reset();
                H.stores.bootstrap.useBootstrapStore.setState({
                    data: { features: {}, settings: {}, catalogs: { models: [], agents: [], prompts: [] },
                        user: { id: 'owner', display_name: 'Tester' }, scope: {} },
                });
                H.stores.chat.useChatStore.setState({
                    activeConversationId: 'conversation-m365', activeConversationKind: 'personal',
                    messages: [], streaming: false, loadingMessages: false,
                });
                H.mount('mount-a', 'MessageList');
                void H.stores.chat.useChatStore.getState().sendMessage('What are my latest emails?', {});
            }"""
        )
        page.wait_for_function("() => typeof window.pushChatFrame === 'function'")
        sent = page.evaluate("() => window.sentChatBodies[0]")
        assert isinstance(sent.get("time_zone"), str) and sent["time_zone"]
        page.evaluate(
            """({answer, records}) => {
                window.pushChatFrame({
                    done: true, role: 'assistant', replace_content: true, content: answer, full_content: answer,
                    message_id: 'reply-m365', conversation_id: 'conversation-m365', augmented: true,
                    m365_citations: records, metadata: {},
                });
                window.closeChatFrames();
            }""",
            {"answer": ANSWER, "records": [EMAIL, EVENT, FILE]},
        )
        root = page.locator("#mount-a")
        email_chip = root.locator(f"button[data-m365-citation-id='{EMAIL_ID}']")
        expect(email_chip).to_have_text("PIM: Role activated")
        expect(root.locator(f"button[data-m365-citation-id='{FILE_ID}']")).to_have_text("20170010188.pdf")
        expect(root).not_to_contain_text("[#m365-")
        expect(root).not_to_contain_text("(Source:")

        email_chip.click()
        card = page.get_by_role("dialog", name="Microsoft 365 source")
        expect(card).to_contain_text("PIM: Role activated")
        expect(card).to_contain_text("Microsoft Security <security@contoso.com>")
        expect(card).to_contain_text("Oct 7, 2026, 12:52 PM EDT")
        expect(card).to_contain_text("Unread")
        expect(card).to_contain_text("High")
        _expect_safe_link(card.get_by_role("link", name="Open in Outlook: PIM: Role activated"), OUTLOOK_LINK)
        expect(card.get_by_role("button", name="Close source")).to_be_focused()
        page.keyboard.press("Escape")
        expect(card).to_have_count(0)
        expect(email_chip).to_be_focused()

        root.locator(f"button[data-m365-citation-id='{EVENT_ID}']").click()
        expect(card).to_contain_text("Thu, Oct 8, 2026, 2:00 PM \u2013 2:30 PM EDT")
        expect(card).to_contain_text("Ann Lee")
        _expect_safe_link(card.get_by_role("link", name="Open in Outlook: Standup"), EVENT_LINK)
        card.get_by_role("button", name="Close source").click()

        root.locator(f"button[data-m365-citation-id='{FILE_ID}']").click()
        expect(card).to_contain_text("SharePoint")
        expect(card).to_contain_text("Sep 1, 2026")
        expect(card).to_contain_text("2.0 KB")
        _expect_safe_link(card.get_by_role("link", name="Open in SharePoint: 20170010188.pdf"), SPO_LINK)
        card.get_by_role("button", name="Close source").click()

        missing_chip = root.locator(f"button[data-m365-citation-id='{MISSING_ID}']")
        expect(missing_chip).to_have_text("Old budget")
        missing_chip.click()
        expect(card).to_contain_text("This Microsoft 365 source is no longer available in this conversation.")
        expect(card.get_by_role("link")).to_have_count(0)
        card.get_by_role("button", name="Close source").click()

    assert citation_requests == []
    assert errors == []


def test_documents_pane_lists_m365_items_with_open_online_links(page):
    try:
        harness_build.ensure_bundle()
    except harness_build.HarnessUnavailable as exc:
        pytest.skip(str(exc))
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    with harness_build.start_static_server() as origin:
        _open_v2_harness(page, origin)
        page.evaluate(
            """(items) => {
                const H = window.OrchHarness;
                H.reset();
                H.stores.bootstrap.useBootstrapStore.setState({
                    data: { features: {}, settings: {}, catalogs: { models: [], agents: [], prompts: [] },
                        user: { id: 'owner', display_name: 'Tester' }, scope: {} },
                });
                H.stores.chat.useChatStore.setState({
                    activeConversationId: 'conversation-m365', activeConversationKind: 'personal',
                    messages: [], drawerMode: 'documents', metadataLoading: false, metadataError: null,
                    metadata: {
                        conversation_id: 'conversation-m365', title: 'Mail',
                        used_documents_tracking_version: 1,
                        used_documents: [{ document_id: 'doc-1', title: 'Policy.pdf', citation_ids: ['doc-1_2'] }],
                        used_m365_items: items,
                    },
                });
                H.mount('mount-a', 'ConversationDrawer');
            }""",
            [
                {**FILE, "message_ids": ["reply-m365"], "last_used_at": "2026-10-07T17:00:00Z"},
                {**UNSAFE, "message_ids": ["reply-m365"], "last_used_at": "2026-10-07T16:59:00Z"},
                {**EMAIL, "message_ids": ["reply-m365"], "last_used_at": "2026-10-07T16:58:00Z"},
                {**EVENT, "message_ids": ["reply-m365"], "last_used_at": "2026-10-07T16:57:00Z"},
            ],
        )
        drawer = page.locator("#mount-a")
        expect(drawer.get_by_role("region", name="Used in answers")).to_contain_text("Policy.pdf")

        files = drawer.get_by_role("region", name="SharePoint & OneDrive")
        expect(files).to_contain_text("20170010188.pdf")
        expect(files).to_contain_text("SharePoint \u00b7 modified Sep 1, 2026")
        _expect_safe_link(files.get_by_role("link", name="Open online: 20170010188.pdf"), SPO_LINK)
        unsafe_row = files.locator(f"li[data-m365-citation-id='{UNSAFE_ID}']")
        expect(unsafe_row).to_contain_text("notes.docx")
        expect(unsafe_row).to_contain_text("Read while answering")
        expect(unsafe_row.get_by_role("link")).to_have_count(0)

        email = drawer.get_by_role("region", name="Email")
        expect(email).to_contain_text("Microsoft Security \u00b7 Oct 7, 2026, 12:52 PM EDT")
        expect(email).to_contain_text("Cited")
        _expect_safe_link(email.get_by_role("link", name="Open online: PIM: Role activated"), OUTLOOK_LINK)

        calendar = drawer.get_by_role("region", name="Calendar")
        expect(calendar).to_contain_text("Thu, Oct 8, 2026, 2:00 PM \u2013 2:30 PM EDT \u00b7 Teams")
        _expect_safe_link(calendar.get_by_role("link", name="Open online: Standup"), EVENT_LINK)

        # Narrow viewport: each row's link stays reachable in the drawer.
        page.set_viewport_size({"width": 390, "height": 844})
        expect(email.get_by_role("link", name="Open online: PIM: Role activated")).to_be_in_viewport()
    assert errors == []


def test_classic_chat_links_m365_items_and_never_fetches_passages(page):
    citation_requests = _citation_requests(page)
    with harness_build.start_static_server() as origin:
        response = page.goto(f"{origin}/ui_tests/fixtures/chat_thought_progress_harness.html")
        assert response is not None and response.ok
        html = page.evaluate(
            """async ({answer, records}) => {
                window.appSettings = { enable_thoughts: false, enable_text_to_speech: false, documentActionCapabilities: {} };
                const chatbox = document.createElement('div');
                chatbox.id = 'chatbox';
                document.getElementById('test-root').appendChild(chatbox);
                const module = await import('/application/single_app/static/js/chat/chat-citations.js');
                window.classicCitations = module;
                const orphan = module.parseCitations('Loose id [#m365-0123456789abcdef] end.');
                const rendered = module.parseCitations(answer, { m365Citations: records });
                chatbox.innerHTML = rendered;
                return { rendered, orphan };
            }""",
            {"answer": ANSWER, "records": [EMAIL, EVENT, {**FILE, "web_url": "javascript:alert(1)"}]},
        )
        assert "[#m365-" not in html["orphan"] and "Loose id" in html["orphan"]
        chatbox = page.locator("#chatbox")
        email_link = chatbox.locator(f"a.m365-citation-link[data-m365-citation-id='{EMAIL_ID}']")
        expect(email_link).to_have_text("PIM: Role activated")
        _expect_safe_link(email_link, OUTLOOK_LINK)
        expect(chatbox.locator(f"a.m365-citation-link[data-m365-citation-id='{EVENT_ID}']")).to_have_text("Standup")
        expect(chatbox.locator(f"span.m365-citation-text[data-m365-citation-id='{FILE_ID}']")).to_have_text("20170010188.pdf")
        expect(chatbox.locator(f"span.m365-citation-text[data-m365-citation-id='{MISSING_ID}']")).to_have_text("Old budget")
        expect(chatbox.locator("a.citation-link")).to_have_count(0)

        page.evaluate(
            """(citationId) => {
                const legacy = document.createElement('a');
                legacy.href = '#';
                legacy.className = 'citation-link';
                legacy.dataset.citationId = citationId;
                legacy.textContent = 'Email';
                document.getElementById('chatbox').appendChild(legacy);
            }""",
            EMAIL_ID,
        )
        chatbox.locator(f"a.citation-link[data-citation-id='{EMAIL_ID}']").click()
        page.wait_for_timeout(300)
    assert citation_requests == []


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
