# test_v2_drawer_generated_files.py
"""
UI test for the V2 Documents drawer listing every file a conversation produced.
Version: 0.261.302
Implemented in: 0.261.302

This test ensures that the Documents tab of the conversation drawer, in a personal conversation,
lists every file the replies produced. That includes the CSV an orchestration plan rendered (the
reported case), files that are still rendering or failed, and an Analyze summary, alongside a Word
document an agent created with a SimpleChat upload action, all in conversation order. Ready files
download through their authorized routes; a file that is not ready shows its status and offers no
download. A Markdown summary opens in a preview, and Show in conversation scrolls to the reply that
produced the file. A background export that finishes while the conversation is open becomes
downloadable in the drawer. Agent documents follow the thread: showing another attempt of an
answer or masking a reply re-reads them and hides what the thread no longer shows, and a refused
list is asked again when the drawer reopens. A conversation that produced nothing still says so,
and the chat header's Documents badge counts generated files alongside the documents answers used.
Only HTTP boundaries are mocked; the real ConversationDrawer, ChatPage, MessageList and stores run
in Chromium with production CSS.

Build: npm --prefix .\\application\\v2_ui run build -- --outDir ..\\..\\ui_tests\\artifacts\\orchestration-plan-editor
Run: python -m pytest .\\ui_tests\\test_v2_drawer_generated_files.py -q
"""

import re
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import expect

from test_v2_orchestration_plan_editor import (  # noqa: F401
    HARNESS,
    ORIGIN,
    connect_options,
    editor_assets,
    editor_browser,
)

pytestmark = pytest.mark.ui

CONVERSATION = "states-csv-chat"
CSV_NAME = "us_states_and_capitals.csv"
CSV_ARTIFACT = "artifact-states-csv"
CSV_BYTES = b"State,Capital\nAlabama,Montgomery\n"
WORD_ID = "77777777-8888-9999-aaaa-bbbbbbbbbbbb"
WORD_NAME = "Capitals brief.docx"
SUMMARY_NAME = "capitals-summary.md"
GENERATED = f"/api/conversations/{CONVERSATION}/generated-documents"
RUN_ID = "run-states"
EXPORT_RUN = "export-run-capitals"
EXPORT_NAME = "county-seats.csv"
RETRY_ID = "88888888-9999-aaaa-bbbb-cccccccccccc"
RETRY_NAME = "Capitals brief, second attempt.docx"


def message(message_id, role, content, **extra):
    return {
        "id": message_id,
        "conversation_id": CONVERSATION,
        "role": role,
        "content": content,
        "timestamp": "2026-10-08T14:39:00Z",
        "metadata": extra.pop("metadata", {}),
        **extra,
    }


def output(output_id, file_name, output_format, state, **extra):
    return {
        "output_id": output_id, "step_id": f"render-{output_id}", "file_name": file_name,
        "output_format": output_format, "profile": "tabular_records_v1", "state": state,
        "attempt_count": 1, "automatic_attempts": 1, "max_automatic_attempts": 3,
        "can_retry": False, "available": True, "message": "", **extra,
    }


def agent_document(document_id, file_name, message_id):
    """One entry of the server's list of documents agents created."""
    return {
        "document_id": document_id, "file_name": file_name, "workspace_scope": "personal", "preview": None,
        "message_id": message_id, "created_at": "2026-10-08T14:40:00Z", "can_download": True,
    }


def agent_reply(message_id, document_id, file_name, **metadata):
    """An agent's reply whose upload action created a workspace document."""
    return message(
        message_id, "assistant", "I saved the brief to your workspace.",
        agent_display_name="Report Writer",
        agent_citations=[{
            "plugin_name": "SimpleChatPlugin", "function_name": "upload_word_document",
            "function_result": {"success": True, "workspace_scope": "personal",
                                "document": {"id": document_id, "file_name": file_name}},
        }],
        metadata=metadata,
    )


PLAN_OUTPUTS = [
    output("out-csv", CSV_NAME, "csv", "completed", artifact_message_id=CSV_ARTIFACT, row_count=50, size_bytes=1006),
    output("out-pdf", "Capitals briefing.pdf", "pdf", "rendering"),
    output("out-xlsx", "Capitals workbook.xlsx", "xlsx", "failed", message="The workbook could not be rendered."),
]
CSV_RECEIPT = {
    "capability": "render_file", "source_kind": "orchestration_retained_output", "output_id": "out-csv",
    "artifact_message_id": CSV_ARTIFACT, "conversation_id": CONVERSATION, "storage_scope": "chat",
    "file_name": CSV_NAME, "output_format": "csv", "profile": "tabular_records_v1", "row_count": 50,
}


def conversation_messages():
    return [
        message("u-1", "user", "I want you to create a CSV file of all the states and their capitals."),
        message(
            "a-csv", "assistant", f"Files:\n\n- {CSV_NAME}: ready (50 rows, 1,006 bytes).",
            metadata={"orchestration": {"run_id": RUN_ID, "outputs": PLAN_OUTPUTS}},
            generated_artifacts=[CSV_RECEIPT],
        ),
        agent_reply("a-agent", WORD_ID, WORD_NAME),
        message(
            "a-summary", "assistant", "Here is a short summary.",
            metadata={"generated_analysis_artifacts": [{
                "capability": "analyze", "artifact_message_id": "artifact-summary", "conversation_id": CONVERSATION,
                "storage_scope": "chat", "file_name": SUMMARY_NAME, "output_format": "md",
                "preview_text": "# Capitals\n\nEvery state has exactly one capital city.",
            }]},
        ),
    ]


class GeneratedFilesApi:
    """The HTTP boundary of a personal conversation, with the requests the browser made."""

    def __init__(self, assets):
        self.assets = assets
        self.messages = conversation_messages()
        # What the server's list of agent documents answers, and with which status.
        self.agent_documents = [agent_document(WORD_ID, WORD_NAME, "a-agent")]
        self.list_status = 200
        self.requests = []
        self.unexpected = []
        self.errors = []

    def handle(self, route):
        request = route.request
        parsed = urlsplit(request.url)
        path = parsed.path
        query = parse_qs(parsed.query)
        if f"{parsed.scheme}://{parsed.netloc}" != ORIGIN:
            self.unexpected.append(request.url)
            route.abort()
            return
        if request.method == "GET" and path in self.assets:
            route.fulfill(path=str(self.assets[path]))
            return
        if path == "/favicon.ico":
            route.fulfill(status=204)
            return
        self.requests.append({"method": request.method, "path": path, "query": query})
        if request.method == "GET" and path == GENERATED:
            if self.list_status != 200:
                route.fulfill(status=self.list_status, json={"error": "Conversation not found"})
            else:
                route.fulfill(json={"documents": self.agent_documents})
            return
        if request.method == "GET" and path == f"{GENERATED}/{WORD_ID}/download":
            route.fulfill(status=200, body=b"PK\x03\x04docx", headers={
                "Content-Type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "Content-Disposition": f'attachment; filename="{WORD_NAME}"',
            })
            return
        if request.method == "GET" and path == "/api/chat_artifacts/download":
            if query.get("conversation_id") == [CONVERSATION] and query.get("message_id") == [CSV_ARTIFACT]:
                route.fulfill(status=200, body=CSV_BYTES, headers={
                    "Content-Type": "text/csv; charset=utf-8",
                    "Content-Disposition": f'attachment; filename="{CSV_NAME}"',
                })
            else:
                route.fulfill(status=404, json={"error": "The artifact content is unavailable."})
            return
        if request.method == "GET" and path == f"/api/v2/orchestration/runs/{RUN_ID}":
            route.fulfill(json={"run": {
                "run_id": RUN_ID, "conversation_id": CONVERSATION, "status": "running",
                "outputs": PLAN_OUTPUTS, "generated_artifacts": [CSV_RECEIPT],
            }})
            return
        if request.method == "GET" and path == f"/api/tabular/generated-output/runs/{EXPORT_RUN}":
            route.fulfill(json={"success": True, "run": {
                "run_id": EXPORT_RUN, "status": "completed", "background_export": True,
                "generated_artifacts": [{
                    "capability": "tabular", "artifact_message_id": "artifact-export", "conversation_id": CONVERSATION,
                    "storage_scope": "chat", "file_name": EXPORT_NAME, "output_format": "csv", "row_count": 120000,
                }],
            }})
            return
        # The rest of the chat page, for the header badge test.
        if path == "/api/get_messages":
            route.fulfill(json={"messages": self.messages})
            return
        if path in ("/api/get_conversations", "/api/conversations/feed"):
            route.fulfill(json={"conversations": [{"id": CONVERSATION, "title": "State capitals"}], "has_more": False})
            return
        if path == "/api/user/settings":
            route.fulfill(json={"settings": {}})
            return
        if path == "/api/v2/orchestration/runs":
            route.fulfill(json={"runs": []})
            return
        if path == "/api/collaboration/file-approvals":
            route.fulfill(json={"approvals": []})
            return
        if path == "/api/user/collaboration-suggestions":
            route.fulfill(json={"results": []})
            return
        if path == f"/api/conversations/{CONVERSATION}/metadata":
            route.fulfill(json={
                "conversation_id": CONVERSATION, "title": "State capitals",
                "used_documents": [{"document_id": "doc-cited", "file_name": "Census tables.pdf"}],
            })
            return
        self.unexpected.append(f"{request.method} {path}")
        route.fulfill(status=404, json={"error": "Unmocked request"})

    def calls(self, path):
        return [request for request in self.requests if request["path"] == path]


@pytest.fixture
def drawer_ui(editor_browser, editor_assets):
    context = editor_browser.new_context(viewport={"width": 1280, "height": 1000}, accept_downloads=True)
    page = context.new_page()
    api = GeneratedFilesApi(editor_assets)
    page.route("**/*", api.handle)
    page.on("pageerror", lambda error: api.errors.append(str(error)))
    try:
        yield page, api
    finally:
        context.close()
        assert not api.unexpected, f"Unexpected browser requests: {api.unexpected}"
        assert not api.errors, api.errors


def mount(page, api, component, messages, *, drawer=None, entries=None, used_documents=()):
    page.goto(ORIGIN + HARNESS)
    page.wait_for_function("() => Boolean(window.OrchHarness)")
    for url in api.assets:
        if url.endswith(".css"):
            page.add_style_tag(url=ORIGIN + url)
    page.evaluate(
        """(spec) => {
            const H = window.OrchHarness;
            H.reset();
            H.stores.bootstrap.useBootstrapStore.setState({ data: {
                version: '0.261.302', settings: {}, branding: { app_title: 'SimpleChat' },
                features: {},
                user: { id: 'ui-user', display_name: 'Pat Reader' },
                scope: { groups: [], public_workspaces: [] },
                catalogs: { models: [], agents: [], prompts: [] },
            } });
            // Seeded as an opened conversation has it: its messages and its metadata are loaded.
            H.stores.chat.useChatStore.setState({
                activeConversationId: spec.conversation, activeConversationKind: 'personal',
                conversations: [{ id: spec.conversation, title: 'State capitals' }],
                messagesLoading: false, messagesError: null, streaming: false, streamingContent: '',
                streamError: null, thoughts: [], messages: spec.messages,
                drawerMode: spec.drawer,
                metadata: {
                    conversation_id: spec.conversation, title: 'State capitals',
                    used_documents: spec.usedDocuments,
                },
            });
            H.mount(spec.entries ? 'mount-a' : 'test-root', spec.component, {},
                spec.entries ? { initialEntries: spec.entries } : {});
        }""",
        {
            "conversation": CONVERSATION, "messages": messages, "component": component,
            "drawer": drawer, "entries": entries, "usedDocuments": list(used_documents),
        },
    )


def generated_region(page):
    return page.get_by_role("region", name="Generated documents")


def is_generated_list(request):
    return urlsplit(request.url).path == GENERATED


def set_messages(page, messages):
    """Replace the thread, as reading it again after an attempt switch or a mask does."""
    page.evaluate("(messages) => window.OrchHarness.stores.chat.useChatStore.setState({ messages })", messages)


def set_drawer(page, mode):
    page.evaluate("(mode) => window.OrchHarness.stores.chat.useChatStore.getState().setDrawerMode(mode)", mode)


def test_drawer_lists_every_generated_file_in_conversation_order(drawer_ui):
    page, api = drawer_ui
    mount(page, api, "ConversationDrawer", conversation_messages(), drawer="documents")

    generated = generated_region(page)
    expect(generated.get_by_role("heading", name="Generated")).to_be_visible()
    rows = generated.locator("li")
    expect(rows).to_have_count(5)
    expect(rows.nth(0)).to_contain_text(CSV_NAME)
    expect(rows.nth(1)).to_contain_text("Capitals briefing.pdf")
    expect(rows.nth(2)).to_contain_text("Capitals workbook.xlsx")
    expect(rows.nth(3)).to_contain_text(WORD_NAME)
    expect(rows.nth(4)).to_contain_text(SUMMARY_NAME)
    assert len(api.calls(GENERATED)) == 1, "the agent-document list is read once"

    # The reported case: a plan's CSV is listed as the thread's card describes it, and downloads.
    csv = generated.locator(f"[data-generated-file='artifact:{CSV_ARTIFACT}']")
    expect(csv).to_contain_text("CSV file · 50 rows · 1006 B")
    expect(csv).to_have_attribute("data-generated-file-status", "ready")
    with page.expect_download() as download_info:
        csv.get_by_role("button", name=f"Download {CSV_NAME}").click()
    assert download_info.value.suggested_filename == CSV_NAME
    downloads = api.calls("/api/chat_artifacts/download")
    assert [call["query"].get("message_id") for call in downloads] == [[CSV_ARTIFACT]], downloads

    # Files that are not ready say where they stand and offer nothing to download.
    for name, status, label in (
        ("Capitals briefing.pdf", "pending", "Rendering"),
        ("Capitals workbook.xlsx", "failed", "Failed"),
    ):
        row = generated.locator("[data-generated-file]").filter(has_text=name)
        expect(row).to_have_attribute("data-generated-file-status", status)
        expect(row).to_contain_text(label)
        expect(row.get_by_role("button", name=re.compile(r"^(Download|Preview) "))).to_have_count(0)
        expect(row.get_by_role("button", name=f"Show {name} in the conversation")).to_be_visible()

    # A document an agent created downloads through the personal conversation's own route.
    word = generated.locator(f"[data-generated-document='{WORD_ID}']")
    expect(word).to_contain_text("Personal workspace")
    with page.expect_download() as word_download:
        word.get_by_role("button", name=f"Download {WORD_NAME}").click()
    assert word_download.value.suggested_filename == WORD_NAME
    assert len(api.calls(f"{GENERATED}/{WORD_ID}/download")) == 1

    # An Analyze summary previews in place.
    summary = generated.locator("[data-generated-file]").filter(has_text=SUMMARY_NAME)
    expect(summary).to_contain_text("Markdown file")
    summary.get_by_role("button", name=f"Preview {SUMMARY_NAME}").click()
    dialog = page.get_by_role("dialog", name=f"Preview {SUMMARY_NAME}")
    expect(dialog).to_contain_text("Every state has exactly one capital city.")
    dialog.get_by_role("button", name="Close").click()
    expect(dialog).to_have_count(0)


def test_show_in_conversation_scrolls_to_the_reply_that_made_the_file(drawer_ui):
    page, api = drawer_ui
    mount(page, api, "ConversationDrawer", conversation_messages(), drawer="documents")
    page.evaluate(
        """() => {
            const reply = document.createElement('div');
            reply.id = 'message-a-csv';
            reply.textContent = 'The reply that rendered the CSV';
            document.getElementById('mount-b').appendChild(reply);
        }"""
    )
    generated_region(page).get_by_role("button", name=f"Show {CSV_NAME} in the conversation").click()
    expect(page.locator("#message-a-csv")).to_have_class(re.compile(r"\bring-2\b"))


def test_a_conversation_that_produced_nothing_says_so(drawer_ui):
    page, api = drawer_ui
    mount(page, api, "ConversationDrawer", [conversation_messages()[0]], drawer="documents")
    expect(page.get_by_text("No documents yet", exact=True)).to_be_visible()
    expect(page.get_by_text("Documents used or created while answering will be listed here.")).to_be_visible()
    expect(generated_region(page)).to_have_count(0)
    assert api.calls(GENERATED) == [], "no agent-document request for a thread no agent answered"


def test_header_badge_counts_generated_files(drawer_ui):
    page, api = drawer_ui
    mount(page, api, "ChatExperience", conversation_messages(), entries=["/chat"],
          used_documents=[{"document_id": "doc-cited", "file_name": "Census tables.pdf"}])
    documents_button = page.get_by_role("button", name="Open used documents", exact=True)
    # One document an answer used, the plan's three files, the agent's brief and the summary.
    expect(documents_button).to_have_text("6")
    documents_button.click()
    expect(generated_region(page).locator("li")).to_have_count(5)
    expect(page.get_by_role("complementary", name="Conversation details")).to_contain_text("Census tables.pdf")
    assert len(api.calls(GENERATED)) == 1, "the badge and the drawer share one read of the agent documents"


def test_a_background_export_that_finishes_becomes_downloadable_in_the_drawer(drawer_ui):
    page, api = drawer_ui
    export_reply = message(
        "a-export", "assistant", "The county seats export is running in the background.",
        metadata={"generated_tabular_outputs": [{
            "capability": "tabular", "export_run_id": EXPORT_RUN, "background_export": True,
            "output_format": "csv", "status": "running",
        }]},
    )
    mount(page, api, "ConversationDrawer", [conversation_messages()[0], export_reply], drawer="documents")
    generated = generated_region(page)
    running = generated.locator(f"[data-generated-file='run:{EXPORT_RUN}']")
    expect(running).to_have_attribute("data-generated-file-status", "pending")
    expect(running).to_contain_text("Generating")

    # The thread's card polls the run; the drawer follows it without the conversation being reread.
    page.evaluate("() => window.OrchHarness.mount('mount-a', 'MessageList')")
    finished = generated.locator("[data-generated-file='artifact:artifact-export']")
    expect(finished).to_have_attribute("data-generated-file-status", "ready", timeout=15000)
    expect(finished).to_contain_text(EXPORT_NAME)
    expect(finished.get_by_role("button", name=f"Download {EXPORT_NAME}")).to_be_visible()
    expect(running).to_have_count(0)
    assert api.calls(f"/api/tabular/generated-output/runs/{EXPORT_RUN}"), "the card polled the run"


def test_agent_documents_follow_the_attempt_and_masking_the_thread_shows(drawer_ui):
    page, api = drawer_ui
    question = conversation_messages()[0]
    mount(page, api, "ConversationDrawer", [question, agent_reply("a-agent", WORD_ID, WORD_NAME)],
          drawer="documents")
    generated = generated_region(page)
    expect(generated.locator(f"[data-generated-document='{WORD_ID}']")).to_be_visible()
    assert len(api.calls(GENERATED)) == 1

    # Another attempt of the answer is shown: as many replies as before, but a different one.
    api.agent_documents = [agent_document(RETRY_ID, RETRY_NAME, "a-agent-2")]
    with page.expect_request(is_generated_list):
        set_messages(page, [question, agent_reply("a-agent-2", RETRY_ID, RETRY_NAME)])
    expect(generated.locator(f"[data-generated-document='{RETRY_ID}']")).to_be_visible()
    expect(generated.locator(f"[data-generated-document='{WORD_ID}']")).to_have_count(0)

    # Masking the reply hides what it created at once, and the list is read again.
    api.agent_documents = []
    with page.expect_request(is_generated_list):
        set_messages(page, [question, agent_reply("a-agent-2", RETRY_ID, RETRY_NAME, masked=True)])
    expect(generated_region(page)).to_have_count(0)
    expect(page.get_by_text("No documents yet", exact=True)).to_be_visible()
    assert len(api.calls(GENERATED)) == 3


def test_a_refused_list_is_asked_again_when_the_drawer_reopens(drawer_ui):
    page, api = drawer_ui
    api.list_status = 404
    question = conversation_messages()[0]
    mount(page, api, "ConversationDrawer", [question, agent_reply("a-agent", WORD_ID, WORD_NAME)],
          drawer="documents")
    # The refusal is answered, and not kept as the final word on this conversation.
    page.wait_for_function(
        """() => {
            const state = window.OrchHarness.stores.generatedDocuments.useGeneratedDocumentsStore.getState();
            return state.conversationId !== null && state.requestKey === null;
        }"""
    )
    assert len(api.calls(GENERATED)) == 1
    expect(generated_region(page)).to_have_count(0)

    api.list_status = 200
    set_drawer(page, None)
    expect(page.get_by_role("complementary", name="Conversation details")).to_have_count(0)
    with page.expect_request(is_generated_list):
        set_drawer(page, "documents")
    expect(generated_region(page).locator(f"[data-generated-document='{WORD_ID}']")).to_be_visible()


def test_returning_to_a_conversation_reads_its_documents_again(drawer_ui):
    page, api = drawer_ui
    question = conversation_messages()[0]
    thread = [question, agent_reply("a-agent", WORD_ID, WORD_NAME)]
    mount(page, api, "ConversationDrawer", thread, drawer="documents")
    expect(generated_region(page).locator(f"[data-generated-document='{WORD_ID}']")).to_be_visible()

    # Another conversation, where no agent created anything, so nothing is requested for it.
    page.evaluate(
        """() => window.OrchHarness.stores.chat.useChatStore.setState({
            activeConversationId: 'other-chat',
            messages: [{ id: 'u-other', conversation_id: 'other-chat', role: 'user', content: 'Hello' }],
        })"""
    )
    expect(generated_region(page)).to_have_count(0)

    # Coming back shows the list as it is now, not as it was when the conversation was left.
    api.agent_documents = [agent_document(RETRY_ID, RETRY_NAME, "a-agent")]
    with page.expect_request(is_generated_list):
        page.evaluate(
            """(spec) => window.OrchHarness.stores.chat.useChatStore.setState({
                activeConversationId: spec.conversation, messages: spec.thread,
            })""",
            {"conversation": CONVERSATION, "thread": thread},
        )
    expect(generated_region(page).locator(f"[data-generated-document='{RETRY_ID}']")).to_be_visible()
    expect(generated_region(page).locator(f"[data-generated-document='{WORD_ID}']")).to_have_count(0)
    assert len(api.calls(GENERATED)) == 2
