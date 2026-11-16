# test_inline_citation_filename_fallback.py
"""
Real React/classic rendering and passage lookup for placeholder citation labels.
Version: 0.261.355
Implemented in: 0.261.355

Uses the existing Azure/local Playwright connection fixture and real local assets.
Only HTTP data boundaries are synthetic. No live conversation or document is changed.
"""

import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from ui_tests.fixtures.orchestration import harness_build
from ui_tests.fixtures.playwright_connection import connect_options  # noqa: F401


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "application" / "single_app" / "static"
ORIGIN = "http://simplechat.test"
CONVERSATION = "citation-fallback-conversation"
DOCUMENT = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
CITATION = f"{DOCUMENT}_1"
CONTENT = (
    'No reserve authorization code is published in this guide.\n\n'
    f'(Source: Untitled Document, Page: 1) [#{CITATION}]\n\n'
    'Next paragraph.'
)
FILENAME = "Public guide " + "long filename " * 12 + ".md"
RECORDS = [{"citation_id": CITATION, "document_id": DOCUMENT, "file_name": FILENAME, "page_number": 1}]


def message(identifier="saved-reply", content=CONTENT, records=None):
    return {
        "id": identifier, "conversation_id": CONVERSATION, "role": "assistant",
        "content": content, "hybrid_citations": RECORDS if records is None else records,
        "augmented": True, "metadata": {},
    }


class CitationPage:
    def __init__(self, page, client):
        self.page = page
        self.client = client
        self.errors = []
        self.requests = []
        self.saved = [message()]
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.route(f"{ORIGIN}/**", self.route)
        if client == "react":
            harness_build.ensure_bundle()

    def route(self, route):
        path = urlsplit(route.request.url).path
        if path.startswith(("/api/", "/conversation/")):
            self.requests.append({"path": path, "body": route.request.post_data_json if route.request.post_data else None})
            if path == "/api/get_citation":
                value = {"file_name": FILENAME, "page_number": 1, "cited_text": "No reserve authorization code is published in this guide."}
            elif path == "/api/get_messages" or path == f"/conversation/{CONVERSATION}/messages":
                value = {"messages": self.saved}
            else:
                value = {"success": True, "messages": [], "requests": [], "pending_actions": []}
            route.fulfill(content_type="application/json", body=json.dumps(value))
            return
        if path == "/harness":
            if self.client == "react":
                styles = sorted((STATIC / "v2" / "assets").glob("*.css"))
                assert styles, "Build the production V2 UI before running these browser tests."
                document = (harness_build.HERE / "harness.html").read_text(encoding="utf-8")
                document = document.replace("./harness.bundle.js", "/ui_tests/fixtures/orchestration/harness.bundle.js")
                document = document.replace("</head>", f'<link rel="stylesheet" href="/static/v2/assets/{styles[0].name}"></head>')
            else:
                document = """<!doctype html><html lang="en"><head><meta charset="utf-8">
                    <meta name="viewport" content="width=device-width, initial-scale=1">
                    <link rel="stylesheet" href="/static/css/bootstrap.min.css">
                    <link rel="stylesheet" href="/static/css/chats.css">
                    <script src="/static/js/chat/marked.min.js"></script>
                    <script src="/static/js/chat/purify.min.js"></script>
                    <script src="/static/js/bootstrap/bootstrap.bundle.min.js"></script>
                    </head><body><main id="chatbox"></main><textarea id="user-input"></textarea>
                    <button id="send-btn">Send</button><select id="prompt-select"></select>
                    <div id="prompt-selection-container"></div>
                    <select id="model-select"><option value="fixture-model">Fixture model</option></select>
                    </body></html>"""
            route.fulfill(content_type="text/html", body=document)
            return
        asset = STATIC / path.removeprefix("/static/") if path.startswith("/static/") else ROOT / path.lstrip("/")
        if asset.is_file():
            route.fulfill(path=str(asset))
        else:
            route.fulfill(status=404)

    def open(self):
        self.page.goto(f"{ORIGIN}/harness")
        if self.client == "react":
            self.page.wait_for_function("() => Boolean(window.OrchHarness)")
            self.page.evaluate(
                """(id) => {
                    const H = window.OrchHarness;
                    H.reset();
                    H.stores.bootstrap.useBootstrapStore.setState({data: {
                        features: {}, settings: {}, catalogs: {models: [], agents: [], prompts: []},
                        user: {id: 'owner', display_name: 'Reader'}, scope: {},
                    }});
                    H.stores.chat.useChatStore.setState({
                        activeConversationId: id, activeConversationKind: 'personal',
                        messages: [], streaming: false, loadingMessages: false,
                    });
                    H.mount('mount-a', 'MessageList');
                }""", CONVERSATION,
            )
        else:
            self.page.evaluate(
                """async (id) => {
                    window.currentConversationId = id;
                    window.appSettings = {enable_thoughts: false, enable_text_to_speech: false, documentActionCapabilities: {}};
                    window.enableEnhancedCitations = false;
                    window.chatMessages = await import('/static/js/chat/chat-messages.js');
                    window.classicStreaming = await import('/static/js/chat/chat-streaming.js');
                    window.currentConversationId = id;
                }""", CONVERSATION,
            )

    def load(self, messages):
        self.saved = messages
        self.page.evaluate(
            """async ({client, id}) => {
                if (client === 'react') {
                    await window.OrchHarness.stores.chat.useChatStore.getState().reloadMessages();
                } else {
                    await window.chatMessages.loadMessages(id);
                }
            }""", {"client": self.client, "id": CONVERSATION},
        )

    def row(self, identifier="saved-reply"):
        if self.client == "react":
            return self.page.locator(f"#message-{identifier}")
        return self.page.locator(f'.message[data-message-id="{identifier}"]')

    def source(self, identifier="saved-reply"):
        row = self.row(identifier)
        return row.get_by_role("button", name=f"{FILENAME} 1", exact=True) if self.client == "react" else row.locator(".message-text a.citation-link")


@pytest.fixture(params=["react", "classic"])
def citation_page(page, request):
    fixture = CitationPage(page, request.param)
    fixture.open()
    yield fixture
    assert fixture.errors == []


@pytest.mark.ui
@pytest.mark.parametrize("width", [390, 1440])
def test_saved_citations_fall_back_without_changing_answers_or_other_messages(citation_page, width):
    fixture = citation_page
    page = fixture.page
    page.set_viewport_size({"width": width, "height": 900})
    meaningful = message("meaningful-reply", CONTENT.replace("Untitled Document", "Civic resilience guide"))
    old = message("legacy-reply", records=[])
    literal = message("literal-reply", records=[{**RECORDS[0], "file_name": '<img src=x onerror="window.injected=true">.md'}])
    fixture.load([message(), meaningful, old, literal])
    row = fixture.row()
    body = row if fixture.client == "react" else row.locator(".message-text")
    expect(body).to_contain_text(FILENAME)
    expect(body).not_to_contain_text("Untitled Document")
    expect(fixture.row("meaningful-reply")).to_contain_text("Civic resilience guide")
    expect(fixture.row("legacy-reply")).to_contain_text("Untitled Document")
    expect(fixture.row("literal-reply")).to_contain_text('<img src=x onerror="window.injected=true">.md')
    expect(fixture.row("literal-reply").locator(".message-text img" if fixture.client == "classic" else "img")).to_have_count(0)
    assert page.evaluate("window.injected === undefined")
    assert not any(call["path"].startswith(("/api/get_citation", "/api/enhanced_citations/")) for call in fixture.requests)
    expect(body).to_contain_text("Next paragraph.")
    source = fixture.source()
    expect(source).to_be_visible()
    if fixture.client == "react":
        expect(source).to_have_attribute("title", f"{FILENAME} \u2014 Page 1")
        assert source.evaluate("element => element.getBoundingClientRect().width") <= width
        source.focus()
        page.keyboard.press("Enter")
        dialog = page.get_by_role("dialog", name="Citation", exact=True)
        expect(dialog).to_contain_text("No reserve authorization code is published in this guide.")
        dialog.get_by_role("button", name="Close citation").click()
    else:
        source.click()
        dialog = page.locator("#citation-modal")
        expect(dialog).to_contain_text("No reserve authorization code is published in this guide.")
        dialog.get_by_role("button", name="Close", exact=True).click()
    lookup = next(call["body"] for call in fixture.requests if call["path"] == "/api/get_citation")
    assert lookup["citation_id"] == CITATION
    assert lookup["document_id"] == DOCUMENT
    fixture.open()
    fixture.load([message()])
    expect(fixture.row()).to_contain_text(FILENAME)
    if fixture.client == "react":
        saved = page.evaluate("window.OrchHarness.stores.chat.useChatStore.getState().messages[0].content")
        assert saved == CONTENT


@pytest.mark.ui
def test_stream_completion_uses_final_metadata_without_rewriting_content(citation_page):
    fixture = citation_page
    page = fixture.page
    page.evaluate(
        """({client, id}) => {
            const nativeFetch = window.fetch.bind(window);
            const encoder = new TextEncoder();
            window.fetch = async (url, init) => {
                if (new URL(String(url), location.origin).pathname === '/api/chat/stream') {
                    return new Response(new ReadableStream({start(controller) {
                        window.pushCitationFrame = frame => controller.enqueue(encoder.encode(`data: ${JSON.stringify(frame)}\\n\\n`));
                        window.closeCitationFrames = () => controller.close();
                    }}), {headers: {'Content-Type': 'text/event-stream'}});
                }
                return nativeFetch(url, init);
            };
            if (client === 'react') {
                void window.OrchHarness.stores.chat.useChatStore.getState().sendMessage('Read the public guide', {});
            } else {
                void window.classicStreaming.sendMessageWithStreaming(
                    {message: 'Read the public guide', conversation_id: id}, 'user-pending', id);
            }
        }""", {"client": fixture.client, "id": CONVERSATION},
    )
    page.wait_for_function("typeof window.pushCitationFrame === 'function'")
    page.evaluate("content => window.pushCitationFrame({content})", CONTENT)
    page.evaluate(
        """message => {
            window.pushCitationFrame({
                ...message, done: true, message_id: message.id, replace_content: true,
                full_content: message.content,
            });
            window.closeCitationFrames();
        }""", message(),
    )
    expect(fixture.source()).to_be_visible()
    expect(fixture.row()).to_contain_text(FILENAME)
    if fixture.client == "react":
        saved = page.evaluate("window.OrchHarness.stores.chat.useChatStore.getState().messages.find(message => message.id === 'saved-reply')")
        assert saved["content"] == CONTENT
        assert saved["hybrid_citations"] == RECORDS
    assert not any(call["path"].startswith(("/api/get_citation", "/api/enhanced_citations/")) for call in fixture.requests)
