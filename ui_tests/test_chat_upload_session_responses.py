# test_chat_upload_session_responses.py
"""
Local browser regressions for shared upload authentication responses.
Version: 0.261.351
Implemented in: 0.261.351

Real V2 components/stores and classic upload JavaScript run in Chromium. Only HTTP
and classic peripheral modules are controlled; no live account or upload is used.
The shared browser fixture supports Azure Playwright without provisioning resources.
"""

from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from test_v2_chat_image_uploads import ChatImageApi
from test_v2_orchestration_plan_editor import (  # noqa: F401
    HARNESS,
    ORIGIN,
    connect_options,
    editor_assets,
    editor_browser,
)


pytestmark = pytest.mark.ui
ROOT = Path(__file__).resolve().parents[1]
CHAT_STATIC = ROOT / "application" / "single_app" / "static" / "js" / "chat"
CONVERSATION = "upload-auth-chat"
FILE = {"name": "ledger.csv", "mimeType": "text/csv", "buffer": b"program,amount\nA,10\n"}
DRAFT = "Please summarize this ledger after I finish reviewing it."
BOOTSTRAP = {
    "version": "0.261.351",
    "settings": {"max_file_size_mb": 25},
    "branding": {"app_title": "SimpleChat"},
    "features": {"enable_user_workspace": True, "enable_chat_file_uploads": True},
    "user": {"id": "ui-user", "display_name": "Upload Tester"},
    "scope": {"groups": [], "public_workspaces": []},
    "catalogs": {"models": [], "agents": [], "prompts": []},
}


class UploadApi(ChatImageApi):
    def __init__(self, assets):
        super().__init__(assets)
        self.outcome = "success"
        self.uploads = []

    def handle(self, route):
        request = route.request
        path = urlsplit(request.url).path
        if request.method == "POST" and path == "/upload":
            self.uploads.append({
                "accept": request.headers.get("accept"),
                "content_type": request.headers.get("content-type", ""),
                "body": request.post_data_buffer,
            })
            if self.outcome == "offline":
                route.abort("failed")
            elif self.outcome == "denied":
                route.fulfill(status=403, json={"error": "This conversation does not allow uploads."})
            elif self.outcome in {"missing", "expired"}:
                # Honor the real Flask negotiation contract rather than always giving JSON.
                if request.headers.get("accept") != "application/json":
                    route.fulfill(status=302, headers={"Location": "/login"})
                elif self.outcome == "missing":
                    route.fulfill(status=401, json={
                        "error": "Unauthorized", "message": "Authentication required",
                    })
                else:
                    route.fulfill(status=401, json={
                        "error": "Session expired", "requires_reauth": True,
                    })
            else:
                route.fulfill(json={
                    "success": True,
                    "conversation_id": CONVERSATION,
                    "file_message_id": "ledger-file",
                    "workspace_document_id": "ledger-document",
                    "workspace_scope": "personal",
                    "workspace_document": {
                        "document_id": "ledger-document", "file_name": "ledger.csv",
                        "scope": "personal", "status": "ready", "percentage_complete": 100,
                    },
                })
            return
        if request.method == "GET" and path == "/api/v2/bootstrap":
            self.requests.append({"path": path, "method": "GET"})
            if self.outcome in {"missing", "expired"}:
                route.fulfill(status=401, json={"error": "Session expired", "requires_reauth": True})
            else:
                route.fulfill(json=BOOTSTRAP)
            return
        super().handle(route)


@pytest.fixture
def upload_ui(editor_browser, editor_assets):
    context = editor_browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    api = UploadApi(editor_assets)
    page.route("**/*", api.handle)
    page.on("pageerror", lambda error: api.errors.append(str(error)))

    def check_console(message):
        if message.type != "error":
            return
        if urlsplit(message.location.get("url", "")).path in {"/upload", "/api/v2/bootstrap"}:
            if any(code in message.text for code in ("401", "403", "net::ERR_FAILED")):
                return
        api.errors.append(message.text)

    page.on("console", check_console)
    try:
        yield page, api
    finally:
        context.close()
        assert not api.unexpected, api.unexpected
        assert not api.errors, api.errors


def mount_upload_chat(page, api):
    page.goto(ORIGIN + HARNESS)
    page.wait_for_function("() => Boolean(window.OrchHarness)")
    for url in api.assets:
        if url.endswith(".css"):
            page.add_style_tag(url=ORIGIN + url)
    page.evaluate(
        """(spec) => {
            const H = window.OrchHarness;
            H.reset();
            H.stores.bootstrap.useBootstrapStore.setState({ data: spec.bootstrap });
            H.stores.appSession.useAppSessionStore.setState({
                status: 'ready', viewerId: 'ui-user', revision: 0,
            });
            H.stores.chat.useChatStore.setState({
                activeConversationId: spec.conversation, activeConversationKind: 'personal',
                messagesLoading: false, messagesError: null, messages: [], streaming: false,
                streamingContent: '', streamError: null, thoughts: [],
                conversations: [{ id: spec.conversation, title: 'Upload response test' }],
            });
            H.mount('test-root', 'SessionChatExperience', {}, { strictMode: true });
        }""",
        {"bootstrap": BOOTSTRAP, "conversation": CONVERSATION},
    )


def check_multipart(api, count=1):
    assert len(api.uploads) == count
    for upload in api.uploads:
        assert upload["accept"] == "application/json"
        assert upload["content_type"].startswith("multipart/form-data; boundary=")
        assert b'filename="ledger.csv"' in upload["body"]
        assert FILE["buffer"] in upload["body"]
        assert CONVERSATION.encode() in upload["body"]


@pytest.mark.parametrize("outcome", ["missing", "expired"])
@pytest.mark.parametrize("width", [1440, 390])
def test_auth_failure_keeps_draft_and_only_explicit_retry_uploads(upload_ui, outcome, width):
    page, api = upload_ui
    page.set_viewport_size({"width": width, "height": 900})
    mount_upload_chat(page, api)
    api.outcome = outcome
    composer = page.get_by_role("textbox", name="Message", exact=True)
    composer.fill(DRAFT)
    original_url = page.url
    page.locator("input[type='file']").set_input_files(FILE)
    row = page.get_by_role("list", name="Attached files").get_by_role("listitem")
    expect(row).to_contain_text("Failed")
    notice = page.get_by_test_id("v2-session-notice")
    expect(notice).to_contain_text("Your SimpleChat session needs to be renewed.")
    expect(composer).to_have_value(DRAFT)
    assert page.url == original_url
    check_multipart(api)
    row.get_by_role("button", name="Retry ledger.csv").click()
    expect(row).to_contain_text("Your SimpleChat session needs to be renewed.")
    check_multipart(api)

    api.outcome = "success"
    notice.get_by_role("button", name="Check sign-in").click()
    expect(notice).to_have_count(0)
    expect(composer).to_have_value(DRAFT)
    expect(row).to_contain_text("Failed")
    check_multipart(api)

    row.get_by_role("button", name="Retry ledger.csv").click()
    expect(row).to_contain_text("Ready")
    expect(composer).to_have_value(DRAFT)
    check_multipart(api, count=2)
    assert page.url == original_url


@pytest.mark.parametrize("outcome", ["success", "denied", "offline"])
def test_upload_success_permissions_and_network_failure_stay_distinct(upload_ui, outcome):
    page, api = upload_ui
    mount_upload_chat(page, api)
    api.outcome = outcome
    composer = page.get_by_role("textbox", name="Message", exact=True)
    composer.fill(DRAFT)
    page.locator("input[type='file']").set_input_files(FILE)
    row = page.get_by_role("list", name="Attached files").get_by_role("listitem")
    expected = {
        "success": "Ready",
        "denied": "This conversation does not allow uploads.",
        "offline": "Failed to fetch",
    }[outcome]
    expect(row).to_contain_text(expected)
    if outcome == "offline":
        page.wait_for_function(
            "() => window.OrchHarness.stores.appSession.useAppSessionStore.getState().status === 'ready'"
        )
    expect(page.get_by_test_id("v2-session-notice")).to_have_count(0)
    expect(composer).to_have_value(DRAFT)
    check_multipart(api)


CLASSIC_STUBS = {
    "chat-conversations.js": """
        export function createNewConversation() { throw new Error('Unexpected conversation creation'); }
        export function loadConversations() {}
    """,
    "chat-loading-indicator.js": """
        export function showFileUploadingMessage() { return null; }
        export function hideFileUploadingMessage() {}
        export function showLoadingIndicator() {}
        export function hideLoadingIndicator() {}
    """,
    "chat-messages.js": """
        export function loadMessages() { return Promise.resolve(); }
        export function watchChatWorkspaceUploadDocument() {}
    """,
    "chat-documents.js": """
        export function getEffectiveScopes() { return { personal: true, groupIds: [] }; }
        export function activateUserWorkspaceContextForChatUpload() {}
        export function registerConversationTaskDocument() {}
    """,
    "chat-layout.js": """
        export function loadUserSettings() { return Promise.resolve({}); }
        export function saveUserSetting() {}
    """,
}


def test_classic_upload_negotiates_json_and_shows_a_structured_auth_error(editor_browser):
    """Execute production classic upload and toast adapters with only peripheral seams replaced."""
    context = editor_browser.new_context()
    page = context.new_page()
    errors = []
    uploads = []
    unexpected = []
    page.on("pageerror", lambda error: errors.append(str(error)))

    def handle(route):
        request = route.request
        path = urlsplit(request.url).path
        if path == "/classic-test":
            route.fulfill(content_type="text/html", body="""<!doctype html>
                <textarea id="user-input" aria-label="Message"></textarea>
                <div id="notifications" role="status"></div>
            """)
        elif path == "/upload" and request.method == "POST":
            uploads.append(request)
            if request.headers.get("accept") == "application/json":
                route.fulfill(status=401, json={
                    "error": "Unauthorized", "message": "Authentication required",
                })
            else:
                route.fulfill(status=302, headers={"Location": "/login"})
        elif path.startswith("/static/js/chat/"):
            filename = path.rsplit("/", 1)[-1]
            if filename in {"chat-input-actions.js", "chat-toast.js"}:
                route.fulfill(path=str(CHAT_STATIC / filename))
            elif filename in CLASSIC_STUBS:
                route.fulfill(content_type="text/javascript", body=CLASSIC_STUBS[filename])
            else:
                unexpected.append(path)
                route.abort()
        else:
            unexpected.append(path)
            route.abort()

    page.route("**/*", handle)
    try:
        page.goto(ORIGIN + "/classic-test")
        composer = page.get_by_role("textbox", name="Message")
        composer.fill(DRAFT)
        page.evaluate(
            """async (conversation) => {
                window.currentConversationId = conversation;
                window.showToast = (message) => {
                    document.getElementById('notifications').textContent = message;
                };
                const { uploadFileToConversation } = await import('/static/js/chat/chat-input-actions.js');
                await uploadFileToConversation(new File(['program,amount\\nA,10\\n'], 'ledger.csv',
                    { type: 'text/csv' }));
            }""",
            CONVERSATION,
        )
        expect(page.get_by_role("status")).to_have_text("Error uploading file: Unauthorized")
        expect(composer).to_have_value(DRAFT)
        assert page.url == ORIGIN + "/classic-test"
        assert len(uploads) == 1
        assert uploads[0].headers["accept"] == "application/json"
        assert uploads[0].headers["content-type"].startswith("multipart/form-data; boundary=")
        assert FILE["buffer"] in uploads[0].post_data_buffer
        assert not unexpected, unexpected
        assert not errors, errors
    finally:
        context.close()
