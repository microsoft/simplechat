# test_m365_lifecycle_and_approvals.py
"""
Azure Playwright-ready UI tests for typed actions, Profile, and saved approvals.
Version: 0.261.034
Implemented in: 0.261.029
In-chat onboarding regression coverage implemented in: 0.261.032
Independent Profile chat reconnect coverage implemented in: 0.261.034

Uses the real local templates, Bootstrap, and browser modules with deterministic
same-origin API fixtures. Set AZURE_PLAYWRIGHT_WS_ENDPOINT, AZURE_SUBSCRIPTION_ID,
AZURE_PLAYWRIGHT_RESOURCE_GROUP, AZURE_PLAYWRIGHT_WORKSPACE, and
AZURE_PLAYWRIGHT_TOKEN_SCOPE to connect to an existing Azure Playwright workspace
using DefaultAzureCredential and azure-mgmt-playwright. Without that environment,
the identical workflows run in local Chromium; local runs do not qualify Azure
tenant authentication or live Microsoft 365 access.
PKCE/state coverage checks opaque browser navigation through /getAToken and
same-request resume, not the server-side token exchange.
"""

import copy
import json
import mimetypes
import os
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlencode, urlsplit

import pytest
from azure.identity import DefaultAzureCredential
from azure.mgmt.playwright import PlaywrightMgmtClient
from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import expect


APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
ORIGIN = "http://simplechat.test"
CSRF_TOKEN = "ui-test-only-m365-anti-forgery-token-not-a-credential"
SOURCES = ("calendar", "email", "onedrive", "spo")


@pytest.fixture(scope="module")
def m365_browser(playwright):
    endpoint = os.getenv("AZURE_PLAYWRIGHT_WS_ENDPOINT")
    if not endpoint:
        browser = playwright.chromium.launch(headless=True)
        try:
            yield browser
        finally:
            browser.close()
        return
    with DefaultAzureCredential() as credential:
        with PlaywrightMgmtClient(credential, os.environ["AZURE_SUBSCRIPTION_ID"]) as client:
            workspace = client.playwright_workspaces.get(
                os.environ["AZURE_PLAYWRIGHT_RESOURCE_GROUP"],
                os.environ["AZURE_PLAYWRIGHT_WORKSPACE"],
            )
            if not workspace.id:
                raise RuntimeError("The Azure Playwright workspace could not be verified.")
            token = credential.get_token(os.environ["AZURE_PLAYWRIGHT_TOKEN_SCOPE"])
            browser = playwright.chromium.connect(
                endpoint,
                headers={"Authorization": f"Bearer {token.token}"},
                expose_network="<loopback>",
            )
            try:
                yield browser
            finally:
                browser.close()


def approval(record_id="sharing", request_type="m365_source_sharing", shared=True):
    return {
        "id": record_id,
        "request_type": request_type,
        "approval_scope": "user",
        "subject_user_id": "data-user",
        "group_id": "data-user",
        "requester_id": "data-user",
        "status": "pending",
        "execution_status": "awaiting_approval",
        "can_approve": True,
        "can_deny": True,
        "created_at": "2026-09-17T18:00:00Z",
        "expires_at": "2026-09-20T18:00:00Z",
        "context": {"shared": shared, "conversation_id": "conversation"},
        "sources": {
            "calendar": {"maximum_sharing_acknowledgement": "request", "allowed_durations": ["request"]},
            "email": {"maximum_sharing_acknowledgement": "today", "allowed_durations": ["request", "today"]},
        },
    }


class ApiFixture:
    def __init__(self, catalog):
        self.catalog = catalog
        self.records = {}
        self.decisions = []
        self.preference_writes = []
        self.revocations = []
        self.errors = []
        self.connection = None
        self.chat_connection = {"status": "not_connected", "sources": []}
        self.connect_requests = []
        self.chat_connect_requests = []
        self.profile_chat_connect_requests = []
        self.workflow_connect_available = False
        self.authorization_url = "https://login.microsoftonline.com/ui-test-tenant/oauth2/v2.0/authorize?state=fixture"
        self.oauth_navigations = []
        self.chat_callback_url = None
        self.profile_callback_url = None
        self.auth_callbacks = []
        self.api_paths = []
        self.csrf_token = CSRF_TOKEN
        self.preference_reads = 0
        self.m365_posts = []
        self.get_failures = {}
        self.post_failures = {}
        self.fail_decision = False
        self.waiting_requests = []
        self.resume_requests = []
        self.resume_response = {"resume_scheduled": True, "execution_status": "queued"}
        self.chat_requests = []
        self.stream_events = []
        self.stream_json_response = None
        self.stream_http_status = 200
        self.stream_pending = False
        self.queue_stream_on_resume = False
        self.auto_chat_start = False
        self.stream_status_requests = []
        self.reattach_requests = []
        self.message_loads = []
        self.collaboration_requests = []
        self.messages = [{"id": "saved-user-message", "role": "user", "content": "Original saved request."}]
        self.run_as_users = [{"id": "data-user", "display_name": "Connected reader"}]
        self.audit_records = []
        self.preferences = {
            "sources": {source: "ask" for source in SOURCES},
            "extended_analysis": {"onedrive": "ask", "spo": "ask"},
        }

    def respond(self, route, payload, status=200):
        route.fulfill(status=status, content_type="application/json", body=json.dumps(payload))

    def handle_api(self, route, path):
        request = route.request
        self.api_paths.append(path)
        body = json.loads(request.post_data or "{}")
        if request.method == "GET":
            failures = self.get_failures.get(path)
            if failures:
                payload, status = failures.pop(0)
                self.respond(route, payload, status)
                return
        if request.method in ("POST", "PATCH", "PUT") and path.startswith("/api/m365/"):
            self.m365_posts.append({
                "path": path, "body": body, "method": request.method,
                "csrf": request.headers.get("x-m365-csrf-token"),
            })
            failures = self.post_failures.get(path)
            if failures:
                payload, status = failures.pop(0)
                self.respond(route, payload, status)
                return
            if request.headers.get("x-m365-csrf-token") != self.csrf_token:
                self.respond(route, {"error": "m365_csrf_invalid", "message": "Anti-forgery token is required."}, 403)
                return
        if path == "/api/m365/preferences":
            if request.method == "GET":
                self.preference_reads += 1
                self.respond(route, {"preferences": self.preferences, "csrf_token": self.csrf_token})
            else:
                if request.method != "PATCH" or set(body) - {"sources", "extended_analysis"}:
                    self.respond(route, {"message": "Invalid preference fields."}, 400)
                    return
                self.preference_writes.append(body)
                self.preferences.update(copy.deepcopy(body))
                self.respond(route, {"success": True, "preferences": self.preferences})
        elif path == "/api/m365/chat/connection":
            self.respond(route, {"success": True, "connection": self.chat_connection, "csrf_token": self.csrf_token})
        elif path == "/api/m365/chat/connection/connect":
            self.profile_chat_connect_requests.append(body)
            self.respond(route, {"success": True, "authorization_url": self.authorization_url})
        elif path == "/api/m365/connections":
            self.respond(route, {"success": True, "connection": self.connection, "csrf_token": self.csrf_token})
        elif path == "/api/m365/connections/connect":
            self.connect_requests.append(body)
            if self.workflow_connect_available:
                self.respond(route, {"success": True, "authorization_url": self.authorization_url})
            else:
                self.respond(route, {"message": "Key Vault is required for workflow connections."}, 503)
        elif path == "/api/m365/connections/disconnect":
            self.revocations.append((path, body))
            self.connection = {**self.connection, "status": "disconnected", "sources": []}
            self.respond(route, {"success": True, "connection": self.connection})
        elif path.startswith("/api/m365/sources/") and path.endswith("/revoke"):
            source = path.split("/")[-2]
            self.preferences["sources"][source] = "ask"
            self.revocations.append((path, body))
            self.respond(route, {"success": True, "revoked": True})
        elif path == "/api/m365/bindings":
            self.respond(route, {"items": [record for record in self.records.values() if record["request_type"] == "m365_workflow_run_as"], "continuation_token": None})
        elif path == "/api/m365/requests":
            self.respond(route, {"items": self.waiting_requests, "continuation_token": None, "csrf_token": self.csrf_token})
        elif path.startswith("/api/m365/requests/") and path.endswith("/connect"):
            self.chat_connect_requests.append((path, body))
            self.respond(route, {"success": True, "authorization_url": self.authorization_url})
        elif path.startswith("/api/m365/requests/") and path.endswith("/resume"):
            self.resume_requests.append(path)
            if self.queue_stream_on_resume:
                self.stream_pending = True
            self.respond(route, self.resume_response)
        elif path == "/api/workflows/m365-run-as-users":
            self.respond(route, {"users": self.run_as_users})
        elif path.startswith("/api/m365/conversations/") and path.endswith("/audit"):
            self.respond(route, {"items": self.audit_records, "continuation_token": None})
        elif path.startswith("/api/m365/bindings/") and path.endswith("/revoke"):
            record_id = path.split("/")[-2]
            self.records[record_id]["status"] = "revoked"
            self.revocations.append((path, body))
            self.respond(route, {"success": True, "binding": self.records[record_id]})
        elif path.startswith("/api/m365/approvals/"):
            record_id = unquote(path.split("/")[4])
            record = self.records.get(record_id)
            if not record:
                self.respond(route, {"message": "Request not found."}, 404)
                return
            if request.method == "GET":
                self.respond(route, record)
                return
            if self.fail_decision:
                self.respond(route, {"message": "Storage is temporarily unavailable."}, 503)
                return
            if record["status"] != "pending":
                self.respond(route, {"message": "Request already changed."}, 409)
                return
            self.decisions.append((record_id, copy.deepcopy(body)))
            denied = body.get("choice") in ("deny", "fast") or (
                "decisions" in body and all(item["duration"] == "no" for item in body["decisions"].values())
            )
            record.update({
                "status": "denied" if denied else "approved",
                "execution_status": "queued",
                "can_approve": False,
                "can_deny": False,
                "transition_applied": True,
            })
            if "decisions" in body:
                record["decisions"] = copy.deepcopy(body["decisions"])
            if record["request_type"] == "m365_extended_analysis":
                record["analysis_choice"] = body["choice"]
            self.respond(route, record)
        elif path.endswith("/plugins/types"):
            self.respond(route, [{"type": "msgraph", "display": "Legacy Graph"}, *self.catalog])
        elif path.startswith("/api/plugins/") and path.endswith("/auth-types"):
            action_type = path.split("/")[-2]
            definition = next((item for item in self.catalog if item["type"] == action_type), None)
            self.respond(route, {
                "allowedAuthTypes": ["user"],
                **({"m365": {**definition, "display_name": definition["display"]}} if definition else {}),
            })
        elif path == "/api/approvals":
            self.respond(route, {"approvals": list(self.records.values()), "total_count": len(self.records), "page": 1, "page_size": 20})
        elif path == "/api/conversations/feed":
            self.respond(route, {"conversations": [{
                "id": "visible-conversation", "title": "Original conversation",
                "chat_type": "personal_single_user", "last_updated": "2026-09-18T18:00:00Z",
            }], "has_more": False})
        elif path.startswith("/api/conversations/") and path.endswith("/metadata"):
            self.respond(route, {
                "id": "visible-conversation", "title": "Original conversation",
                "chat_type": "personal_single_user", "context": [],
            })
        elif path == "/api/chat/stream":
            self.chat_requests.append(body)
            if self.stream_json_response is not None:
                self.respond(route, self.stream_json_response, self.stream_http_status)
            else:
                route.fulfill(
                    content_type="text/event-stream",
                    body="".join(f"data: {json.dumps(event)}\n\n" for event in self.stream_events),
                )
        elif path.startswith("/api/chat/stream/status/"):
            self.stream_status_requests.append(path)
            self.respond(route, {"pending": self.stream_pending, "reattachable": self.stream_pending})
        elif path.startswith("/api/chat/stream/reattach/"):
            self.reattach_requests.append(path)
            self.stream_pending = False
            final_message = {
                "done": True, "conversation_id": path.split("/")[-1],
                "message_id": "saved-assistant-message", "full_content": "Resumed original saved request.",
            }
            route.fulfill(content_type="text/event-stream", body=f"data: {json.dumps(final_message)}\n\n")
        elif path.startswith("/api/collaboration/conversations/"):
            self.collaboration_requests.append(path)
            conversation_id = path.split("/")[4]
            if path.endswith("/messages"):
                self.respond(route, {"messages": self.messages})
            elif path.endswith("/events"):
                route.fulfill(content_type="text/event-stream", body=": connected\n\n")
            else:
                self.respond(route, {"conversation": {
                    "id": conversation_id, "title": "Shared original conversation",
                    "conversation_kind": "collaborative", "chat_type": "group_multi_user",
                    "can_post_messages": True, "participants": [],
                }})
        elif path.startswith("/api/"):
            self.respond(route, {})
        else:
            raise AssertionError(f"Unexpected fixture API: {path}")


@pytest.fixture
def ui(m365_browser, monkeypatch):
    monkeypatch.syspath_prepend(str(APP_ROOT))
    from functions_m365_operations import M365_PLUGIN_TYPES, get_m365_action_definition, get_m365_default_config

    catalog = []
    for action_type in M365_PLUGIN_TYPES:
        definition = get_m365_action_definition(action_type)
        catalog.append({
            **definition,
            "display": definition["display_name"],
            "defaults": get_m365_default_config(action_type)["additionalFields"],
        })
    api = ApiFixture(catalog)
    environment = Environment(loader=FileSystemLoader(APP_ROOT / "templates"), autoescape=select_autoescape(["html"]))
    environment.globals["url_for"] = lambda endpoint, filename="": f"/static/{filename}"
    context = m365_browser.new_context(viewport={"width": 1440, "height": 900}, timezone_id="America/New_York", locale="en-US")
    page = context.new_page()
    page.on("pageerror", lambda error: api.errors.append(str(error)))
    modal = (APP_ROOT / "templates" / "_m365_approvals_modal.html").read_text(encoding="utf-8")
    profile = (APP_ROOT / "templates" / "profile.html").read_text(encoding="utf-8")
    start = profile.index('<section class="section-card" id="m365-profile-settings"')
    profile_section = profile[start:profile.index("</section>", start) + len("</section>")]
    profile_html = environment.from_string(profile_section).render()
    admin_actions = (APP_ROOT / "templates" / "admin" / "_panes" / "actions.html").read_text(encoding="utf-8")
    admin_start = admin_actions.index('<div class="card p-3 mb-4" id="m365-retrieval-configuration">')
    admin_end = admin_actions.index('<div class="card p-3 mb-4" id="document-action-capabilities-card">')
    admin_m365 = environment.from_string(admin_actions[admin_start:admin_end]).render(settings={})
    harnesses = {
        "/modal": f'<button type="button" id="open">Open approvals</button>{modal}',
        "/profile": profile_html,
        "/plugin": environment.get_template("_plugin_modal.html").render(settings={}),
        "/agent": environment.get_template("_agent_modal.html").render(settings={}),
        "/approvals": f'<table id="approvalsTable"><tbody id="approvalsTableBody"></tbody></table>{modal}',
        "/workflow-m365": '<div><div id="workflow-anchor"></div></div>',
        "/audit-m365": '<div id="conversation-details"></div>',
        "/requests-m365": '<div id="m365-waiting-requests"></div>',
        "/admin-m365": admin_m365,
        "/chats": (
            '<main><div id="conversations-list"></div><h1 id="current-conversation-title">Chat</h1>'
            '<div id="toast-container"></div>'
            '<div id="chat-messages-container"><div id="chatbox"></div></div>'
            '<textarea id="user-input"></textarea><button type="button" id="send-btn">Send</button>'
            '<select id="prompt-select"></select><div id="prompt-selection-container"></div>'
            '<select id="model-select"><option value="test-model">Test model</option></select></main>'
        ),
        "/workflow-controls": (
            '<div id="workflow-activity-pending-action-controls"></div>'
            '<button id="workflow-activity-cancel-btn" class="d-none"><span>Cancel run</span></button>'
        ),
    }

    def route_request(route):
        parsed = urlsplit(route.request.url)
        path = parsed.path
        if parsed.netloc != "simplechat.test":
            if route.request.is_navigation_request() and route.request.url == api.authorization_url:
                api.oauth_navigations.append(route.request.url)
                route.fulfill(content_type="text/html", body="<h1>Microsoft sign-in fixture</h1>")
                return
            route.abort()
            api.errors.append("Unexpected nonlocal browser request")
            return
        if path.startswith("/api/"):
            api.handle_api(route, path)
            return
        callback_destination = api.profile_callback_url or api.chat_callback_url
        if path == "/getAToken" and callback_destination:
            api.auth_callbacks.append(route.request.url)
            # A fulfilled redirect bypasses subsequent Playwright routes. Keep
            # its destination local to this fixture using an inert navigation link.
            callback_html = environment.from_string(
                '<h1>OAuth callback fixture</h1><a href="{{ destination }}">{{ label }}</a>'
            ).render(
                destination=callback_destination,
                label="Return to Microsoft 365 chat connection" if api.profile_callback_url else "Return to original chat",
            )
            route.fulfill(content_type="text/html", body=callback_html)
            return
        if path.startswith("/conversation/") and path.endswith("/messages"):
            api.message_loads.append(path.split("/")[2])
            api.respond(route, {"messages": api.messages})
            return
        if path.startswith("/static/"):
            asset = (APP_ROOT / "static" / unquote(path[len("/static/"):])).resolve()
            if not asset.is_relative_to((APP_ROOT / "static").resolve()) or not asset.is_file():
                route.fulfill(status=404, body="")
                return
            route.fulfill(body=asset.read_bytes(), content_type=mimetypes.guess_type(asset.name)[0] or "application/octet-stream")
            return
        if path not in harnesses:
            route.fulfill(status=404, body="")
            return
        scripts = '<script src="/static/js/chat/chat-m365-approvals.js"></script>'
        if path in ("/chats", "/requests-m365"):
            scripts += '<script src="/static/js/chat/chat-m365-connect.js"></script>'
        if path == "/chats":
            scripts += (
                '<script src="/static/js/toast.js"></script>'
                '<script src="/static/js/chat/marked.min.js"></script>'
                '<script src="/static/js/chat/purify.min.js"></script>'
            )
            if api.auto_chat_start:
                scripts += (
                    '<script src="/static/js/chat/chat-global.js"></script>'
                    '<script type="module" src="/static/js/chat/chat-onload.js"></script>'
                )
        if path == "/profile":
            scripts += '<script src="/static/js/profile/profile-m365.js"></script>'
        if path == "/approvals":
            scripts += '<script src="/static/js/approvals/m365-approvals.js"></script>'
        if path == "/requests-m365":
            scripts += '<script src="/static/js/approvals/m365-requests.js"></script>'
        html = (
            '<!doctype html><html lang="en"><head><meta name="viewport" content="width=device-width, initial-scale=1" />'
            '<link rel="stylesheet" href="/static/css/bootstrap.min.css" /></head><body>'
            f'{harnesses[path]}<script src="/static/js/bootstrap/bootstrap.bundle.min.js"></script>'
            f'{scripts}</body></html>'
        )
        route.fulfill(content_type="text/html", body=html)

    context.route("**/*", route_request)
    yield page, api
    context.close()


def initialize_chat(page, shared=False):
    page.evaluate("""async shared => {
        window.appSettings = {
            enable_thoughts: false, enable_text_to_speech: false,
            enable_collaborative_conversations: shared, documentActionCapabilities: {}
        };
        window.enable_document_classification = false;
        window.currentConversationId = 'visible-conversation';
        window.currentUser = { id: 'data-user', display_name: 'Connected reader' };
        window.scrollChatToBottom = () => {};
        window.streamFailures = [];
        window.finishedStreams = 0;
        window.resumeEvents = [];
        window.addEventListener('m365-chat-resumed', event => window.resumeEvents.push(event.detail));
        const item = document.createElement('div');
        item.className = 'conversation-item active';
        item.dataset.conversationId = 'visible-conversation';
        item.dataset.conversationKind = shared ? 'collaborative' : 'personal';
        item.dataset.chatType = shared ? 'group_multi_user' : 'personal_single_user';
        document.getElementById('conversations-list').appendChild(item);
        window.messagesModule = await import('/static/js/chat/chat-messages.js');
        window.streamingModule = await import('/static/js/chat/chat-streaming.js');
        if (shared) {
            await import('/static/js/chat/chat-collaboration.js');
        }
    }""", shared)


def auth_pause(request_id="saved/request id"):
    return {
        "type": "m365_sign_in_required", "auth_required": True,
        "m365_request_id": request_id, "conversation_id": "private-backing-conversation",
        "sources": list(SOURCES), "scopes": ["Calendars.ReadWrite", "Mail.ReadWrite", "Files.Read.All"],
        "message": 'Connect to continue. <img src=x onerror="window.injected=true">',
        "error": "Microsoft 365 sign-in is required.", "done": True,
        "user_message_id": "saved-user-message", "message_persisted": True,
    }


def start_chat_stream(page):
    page.evaluate("""() => {
        window.messagesModule.appendMessage('You', 'Original saved request.', null, 'temp_user_m365');
        window.streamingModule.sendMessageWithStreaming(
            { message: 'Original saved request.', conversation_id: 'visible-conversation' },
            'temp_user_m365', 'visible-conversation',
            {
                onError: message => window.streamFailures.push(message),
                onFinally: () => { window.finishedStreams += 1; }
            }
        );
    }""")


@pytest.mark.ui
@pytest.mark.parametrize("transport,persisted", [
    ("sse", True), ("sse", False), ("json_error", True), ("json_success", True),
])
def test_chat_auth_pause_preserves_messages_and_never_blindly_retries(ui, transport, persisted):
    page, api = ui
    payload = {**auth_pause(), "message_persisted": persisted}
    if transport == "sse":
        api.stream_events = [{"content": "Saved partial answer."}, payload]
    else:
        api.stream_json_response = {**payload, "partial_content": "Saved partial answer."}
        api.stream_http_status = 403 if transport == "json_error" else 200
    page.goto(f"{ORIGIN}/chats")
    initialize_chat(page)
    start_chat_stream(page)
    prompt = page.get_by_role("region", name="Microsoft 365 connection required")
    expect(prompt.get_by_role("button", name="Connect Microsoft 365", exact=True)).to_be_visible()
    expect(prompt).to_contain_text("Calendar, Email, OneDrive, SharePoint Online (SPO)")
    expect(prompt).to_contain_text("sharing acknowledgements")
    expect(prompt).to_contain_text("workflow Run as approvals")
    expect(prompt).to_contain_text('<img src=x onerror="window.injected=true">')
    expect(prompt.locator("img")).to_have_count(0)
    expect(page.locator("#chatbox")).to_contain_text("Saved partial answer.")
    expect(page.locator("#chatbox")).not_to_contain_text("Foundry")
    expect(page.locator("#chatbox")).not_to_contain_text("Stream interrupted")
    if persisted:
        expect(page.locator('[data-message-id="saved-user-message"]').first).to_be_visible()
        expect(page.locator('[data-message-id="temp_user_m365"]')).to_have_count(0)
    else:
        expect(page.locator('[data-message-id="temp_user_m365"]').first).to_be_visible()
        expect(page.locator('[data-message-id="saved-user-message"]')).to_have_count(0)
    expect(page.locator(".stream-stop-btn")).to_have_count(0)
    state = page.evaluate("({ failures: window.streamFailures, finished: window.finishedStreams, injected: Boolean(window.injected) })")
    assert state == {"failures": [], "finished": 1, "injected": False}
    assert len(api.chat_requests) == 1
    assert not api.stream_status_requests
    assert not api.reattach_requests
    assert not api.errors


@pytest.mark.ui
@pytest.mark.parametrize("authorization_endpoint", [
    "https://login.microsoftonline.com/ui-test-tenant/oauth2/v2.0/authorize",
    "https://login.microsoftonline.us/ui-test-tenant/oauth2/v2.0/authorize",
    "https://login.chinacloudapi.cn/ui-test-tenant/oauth2/v2.0/authorize",
    "https://identity.custom-cloud.test:8443/organizations/ui-test-tenant/authentication/start",
])
def test_chat_connect_posts_only_saved_request_with_csrf_and_uses_server_validated_oauth(ui, authorization_endpoint):
    page, api = ui
    api.authorization_url = f"{authorization_endpoint}?state=fixture"
    api.stream_events = [auth_pause()]
    page.goto(f"{ORIGIN}/chats")
    initialize_chat(page)
    start_chat_stream(page)
    page.get_by_role("button", name="Connect Microsoft 365", exact=True).click()
    expect(page.get_by_role("heading", name="Microsoft sign-in fixture")).to_be_visible()
    assert api.oauth_navigations == [api.authorization_url]
    assert api.chat_connect_requests == [("/api/m365/requests/saved%2Frequest%20id/connect", {})]
    assert api.m365_posts == [{
        "path": "/api/m365/requests/saved%2Frequest%20id/connect",
        "method": "POST", "body": {}, "csrf": CSRF_TOKEN,
    }]
    assert not api.connect_requests
    assert not api.decisions
    assert not api.errors


@pytest.mark.ui
@pytest.mark.parametrize("authorization_endpoint", [
    "https://login.microsoftonline.com/ui-test-tenant/oauth2/v2.0/authorize",
    "https://login.microsoftonline.us/ui-test-tenant/oauth2/v2.0/authorize",
    "https://identity.custom-cloud.test:8443/organizations/ui-test-tenant/authentication/start",
])
def test_chat_pkce_get_token_round_trip_needs_no_workflow_connection(ui, authorization_endpoint):
    """Preserve the opaque server OAuth URL and resume through the existing callback."""
    page, api = ui
    app_origin = "https://simplechat.test"
    request_id = "get-token/request"
    oauth_query = {
        "client_id": "ui-test-client",
        "response_type": "code",
        "redirect_uri": f"{app_origin}/getAToken",
        "scope": "Calendars.ReadWrite Mail.ReadWrite Files.Read.All",
        "state": "ui-test-state.with+reserved/&values",
        "code_challenge": "ui-test-pkce-challenge-not-a-credential",
        "code_challenge_method": "S256",
        "response_mode": "query",
    }
    api.authorization_url = f"{authorization_endpoint}?{urlencode(oauth_query)}"
    api.stream_events = [auth_pause(request_id)]
    page.add_init_script("""
        window.appSettings = { documentActionCapabilities: {} };
        window.enable_document_classification = false;
        window.currentUser = { id: 'data-user', display_name: 'Connected reader' };
    """)
    page.goto(f"{app_origin}/chats")
    initialize_chat(page)
    start_chat_stream(page)
    page.get_by_role("button", name="Connect Microsoft 365", exact=True).click()
    expect(page.get_by_role("heading", name="Microsoft sign-in fixture")).to_be_visible()
    forwarded_query = parse_qs(urlsplit(api.oauth_navigations[0]).query)
    assert forwarded_query == {key: [value] for key, value in oauth_query.items()}

    api.auto_chat_start = True
    api.queue_stream_on_resume = True
    return_query = urlencode({
        "conversationId": "visible-conversation",
        "m365_request_id": request_id,
        "m365_auth": "connected",
    })
    api.chat_callback_url = f"{app_origin}/chats?{return_query}"
    callback_query = urlencode({"code": "ui-test-code-not-a-credential", "state": oauth_query["state"]})
    callback_url = f"{app_origin}/getAToken?{callback_query}"
    page.goto(callback_url)
    page.get_by_role("link", name="Return to original chat", exact=True).click()
    expect(page.locator("#m365-chat-connect-status")).to_contain_text("queued or resuming")
    expect(page.locator("#chatbox")).to_contain_text("Resumed original saved request.")
    expect(page).to_have_url(f"{app_origin}/chats?conversationId=visible-conversation")
    assert api.auth_callbacks == [callback_url]
    expected_request_path = f"/api/m365/requests/{quote(request_id, safe='')}"
    assert api.m365_posts == [
        {"path": f"{expected_request_path}/{action}", "method": "POST", "body": {}, "csrf": CSRF_TOKEN}
        for action in ("connect", "resume")
    ]
    assert not any(path.startswith("/api/m365/connections") for path in api.api_paths)
    assert not api.decisions
    assert len(api.chat_requests) == 1
    assert api.reattach_requests == ["/api/chat/stream/reattach/visible-conversation"]
    storage = page.evaluate("JSON.stringify({ local: { ...localStorage }, session: { ...sessionStorage } })")
    for sensitive_value in (request_id, CSRF_TOKEN, oauth_query["state"], oauth_query["code_challenge"], "ui-test-code-not-a-credential"):
        assert sensitive_value not in storage
    assert not api.errors


@pytest.mark.ui
@pytest.mark.parametrize("url", [
    "javascript:window.injected=true",
    "http://login.microsoftonline.com/tenant/oauth2/v2.0/authorize",
    "https://user:password@login.microsoftonline.com/tenant/oauth2/v2.0/authorize",
    "https://",
    "https://[invalid/authorize",
    "",
    None,
])
def test_chat_connect_rejects_unsafe_or_malformed_oauth_navigation(ui, url):
    page, api = ui
    api.authorization_url = url
    page.goto(f"{ORIGIN}/chats")
    page.evaluate("payload => window.SimpleChatM365Connect.renderPrompt(document.getElementById('chatbox'), payload)", auth_pause())
    page.get_by_role("button", name="Connect Microsoft 365", exact=True).click()
    expect(page.get_by_role("alert")).to_contain_text("valid HTTPS Microsoft 365 sign-in URL")
    expect(page.get_by_role("button", name="Connect Microsoft 365", exact=True)).to_be_enabled()
    assert page.url == f"{ORIGIN}/chats"
    assert not api.oauth_navigations
    assert not api.errors


@pytest.mark.ui
def test_chat_connect_failure_is_visible_text_and_can_be_retried_explicitly(ui):
    page, api = ui
    api.post_failures["/api/m365/requests/saved%2Frequest%20id/connect"] = [
        ({"message": 'Sign-in is unavailable. <img src=x onerror="window.injected=true">'}, 503)
    ]
    page.goto(f"{ORIGIN}/chats")
    page.evaluate("payload => window.SimpleChatM365Connect.renderPrompt(document.getElementById('chatbox'), payload)", auth_pause())
    page.get_by_role("button", name="Connect Microsoft 365", exact=True).click()
    expect(page.get_by_role("alert")).to_contain_text("Sign-in is unavailable.")
    expect(page.get_by_role("alert")).to_be_focused()
    expect(page.locator(".m365-connect-prompt img")).to_have_count(0)
    expect(page.get_by_role("button", name="Connect Microsoft 365", exact=True)).to_be_enabled()
    assert len(api.m365_posts) == 1
    assert not api.oauth_navigations
    assert not api.errors


@pytest.mark.ui
@pytest.mark.parametrize("shared", [False, True])
def test_oauth_callback_after_chat_initialization_resumes_original_request_without_replay(ui, shared):
    page, api = ui
    request_id = auth_pause()["m365_request_id"]
    api.resume_response["conversation_id"] = "private-backing-conversation"
    api.stream_pending = True
    query = urlencode({
        "conversationId": "visible-conversation", "m365_request_id": request_id,
        "m365_auth": "connected", "scope": "group" if shared else "personal",
    })
    page.goto(f"{ORIGIN}/chats?{query}#messages")
    assert not api.resume_requests
    initialize_chat(page, shared=shared)
    expected_reattach = "/api/collaboration/conversations/visible-conversation/events" if shared else "/api/chat/stream/reattach/visible-conversation"
    with page.expect_request(f"{ORIGIN}{expected_reattach}"):
        page.evaluate("window.SimpleChatM365Connect.handleCallback()")
    expect(page.locator("#m365-chat-connect-status")).to_contain_text("queued or resuming")
    expect(page.locator("#chatbox")).to_contain_text("Original saved request.")
    page.evaluate("window.SimpleChatM365Connect.handleCallback()")
    resumed_events = page.evaluate("window.resumeEvents")
    storage = page.evaluate("JSON.stringify({ local: { ...localStorage }, session: { ...sessionStorage } })")
    assert resumed_events == [{"requestId": request_id, "conversationId": "visible-conversation"}]
    assert api.resume_requests == [f"/api/m365/requests/{quote(request_id, safe='')}/resume"]
    assert api.m365_posts[0]["body"] == {}
    assert api.m365_posts[0]["csrf"] == CSRF_TOKEN
    assert "m365_auth" not in page.url and "m365_request_id" not in page.url
    assert "conversationId=visible-conversation" in page.url
    assert "scope=" in page.url and page.url.endswith("#messages")
    assert request_id not in storage and CSRF_TOKEN not in storage
    if shared:
        assert "/api/collaboration/conversations/visible-conversation/messages" in api.collaboration_requests
        assert not api.message_loads
        assert not api.stream_status_requests
    else:
        expect(page.locator("#chatbox")).to_contain_text("Resumed original saved request.")
        assert api.message_loads == ["visible-conversation"]
        assert api.reattach_requests == [expected_reattach]
    page.reload()
    initialize_chat(page, shared=shared)
    page.evaluate("window.SimpleChatM365Connect.handleCallback()")
    assert len(api.resume_requests) == 1
    assert not api.chat_requests
    assert not api.decisions
    assert not api.errors


@pytest.mark.ui
def test_real_chat_startup_handles_oauth_callback_after_deep_link_selection(ui):
    page, api = ui
    api.auto_chat_start = True
    api.queue_stream_on_resume = True
    page.add_init_script("""
        window.appSettings = { documentActionCapabilities: {} };
        window.enable_document_classification = false;
        window.currentUser = { id: 'data-user', display_name: 'Connected reader' };
    """)
    page.goto(f"{ORIGIN}/chats?conversationId=visible-conversation&m365_request_id=request&m365_auth=connected")
    expect(page.locator("#m365-chat-connect-status")).to_contain_text("queued or resuming")
    expect(page.locator("#chatbox")).to_contain_text("Resumed original saved request.")
    assert api.message_loads == ["visible-conversation", "visible-conversation"]
    assert api.resume_requests == ["/api/m365/requests/request/resume"]
    assert api.reattach_requests == ["/api/chat/stream/reattach/visible-conversation"]
    assert "m365_request_id" not in page.url
    assert not api.chat_requests
    assert not api.errors


@pytest.mark.ui
def test_oauth_callback_failure_is_visible_and_only_explicit_retry_resumes(ui):
    page, api = ui
    api.post_failures["/api/m365/requests/request/resume"] = [
        ({"message": 'Resume is unavailable. <svg onload="window.injected=true">'}, 503)
    ]
    page.goto(f"{ORIGIN}/chats?conversationId=visible-conversation&m365_request_id=request&m365_auth=connected")
    initialize_chat(page)
    page.evaluate("window.SimpleChatM365Connect.handleCallback()")
    expect(page.get_by_role("alert")).to_contain_text("Resume is unavailable.")
    expect(page.locator("#m365-chat-connect-status svg")).to_have_count(0)
    expect(page.get_by_role("button", name="Retry resume")).to_be_enabled()
    assert len(api.m365_posts) == 1
    assert "m365_auth" not in page.url and "m365_request_id" not in page.url
    assert not api.message_loads
    page.evaluate("window.SimpleChatM365Connect.handleCallback()")
    assert len(api.m365_posts) == 1
    page.get_by_role("button", name="Retry resume").click()
    expect(page.locator("#m365-chat-connect-status")).to_contain_text("queued or resuming")
    expect(page.get_by_role("button", name="Retry resume")).to_be_hidden()
    assert len(api.m365_posts) == 2
    assert not api.errors


@pytest.mark.ui
@pytest.mark.parametrize("result", [
    {"auth_required": True, "message": "The Microsoft 365 session needs sign-in."},
    {"execution_status": "awaiting_approval", "message": "A separate sharing approval is still needed."},
])
def test_callback_does_not_treat_sign_in_or_separate_approval_as_queued_execution(ui, result):
    page, api = ui
    api.resume_response = result
    page.goto(f"{ORIGIN}/chats?conversationId=visible-conversation&m365_request_id=request&m365_auth=connected")
    initialize_chat(page)
    page.evaluate("window.SimpleChatM365Connect.handleCallback()")
    expect(page.locator("#m365-chat-connect-status")).to_contain_text(result["message"])
    if result.get("auth_required"):
        expect(page.get_by_role("button", name="Connect Microsoft 365", exact=True)).to_be_visible()
    else:
        expect(page.get_by_role("link", name="Review Approvals")).to_be_visible()
    assert not api.message_loads
    assert not api.stream_status_requests
    assert not api.decisions
    assert not api.errors


@pytest.mark.ui
@pytest.mark.parametrize("transport", ["sse", "json_error"])
def test_foundry_auth_prompt_keeps_its_existing_label_and_link(ui, transport):
    page, api = ui
    payload = {
        "error": "Grant access to the Foundry agent.", "auth_required": True,
        "auth_url": "https://login.microsoftonline.com/tenant/oauth2/v2.0/authorize",
        "done": True,
    }
    if transport == "sse":
        api.stream_events = [payload]
    else:
        api.stream_json_response = payload
        api.stream_http_status = 403
    page.goto(f"{ORIGIN}/chats")
    initialize_chat(page)
    start_chat_stream(page)
    expect(page.locator("#chatbox")).to_contain_text("Foundry access required:")
    expect(page.get_by_role("link", name="Sign in or grant Foundry access")).to_have_attribute("target", "_blank")
    expect(page.get_by_role("button", name="Connect Microsoft 365", exact=True)).to_have_count(0)
    state = page.evaluate("({ failures: window.streamFailures, finished: window.finishedStreams })")
    assert state == {"failures": ["Grant access to the Foundry agent."], "finished": 1}
    assert not api.chat_connect_requests
    assert not api.errors


@pytest.mark.ui
def test_waiting_interactive_sign_in_connects_without_profile_or_workflow_consent(ui):
    page, api = ui
    api.waiting_requests = [
        {"id": "chat-request", "conversation_id": "visible-conversation", "status": "awaiting_sign_in", "sources": ["email"]},
        {"id": "workflow-request", "workflow_id": "workflow", "conversation_id": "workflow-conversation", "status": "awaiting_sign_in"},
        {"id": "recovery-request", "conversation_id": "recovery-conversation", "status": "recovery_required"},
    ]
    page.goto(f"{ORIGIN}/requests-m365")
    expect(page.get_by_role("button", name="Connect Microsoft 365", exact=True)).to_have_count(1)
    expect(page.get_by_role("link", name="Review Microsoft 365 connection")).to_have_attribute("href", "/profile?tab=settings")
    expect(page.get_by_role("button", name="Resume request")).to_have_count(0)
    page.get_by_role("button", name="Connect Microsoft 365", exact=True).click()
    expect(page.get_by_role("heading", name="Microsoft sign-in fixture")).to_be_visible()
    assert api.chat_connect_requests == [("/api/m365/requests/chat-request/connect", {})]
    assert not api.resume_requests
    assert not api.connect_requests
    assert not api.decisions
    assert not api.errors


@pytest.mark.ui
def test_m365_mutation_refreshes_an_exact_stale_csrf_token_once(ui):
    page, api = ui
    api.waiting_requests = [{"id": "request", "conversation_id": "conversation", "status": "awaiting_approval"}]
    page.goto(f"{ORIGIN}/requests-m365")
    expect(page.get_by_role("button", name="Resume request")).to_be_visible()
    api.csrf_token = f"{CSRF_TOKEN}-rotated"
    page.get_by_role("button", name="Resume request").click()
    expect(page.locator("#m365-waiting-requests")).to_contain_text("Request queued.")
    assert [request["csrf"] for request in api.m365_posts] == [CSRF_TOKEN, api.csrf_token]
    assert [request["body"] for request in api.m365_posts] == [{}, {}]
    assert api.preference_reads == 1
    assert api.resume_requests == ["/api/m365/requests/request/resume"]
    assert not api.errors


@pytest.mark.ui
@pytest.mark.parametrize("status,code,attempts,refreshes", [
    (403, "forbidden", 1, 0),
    (403, "m365_csrf_invalid", 2, 1),
    (400, "m365_csrf_invalid", 1, 0),
])
def test_m365_csrf_retry_is_bounded_and_does_not_retry_genuine_forbidden(ui, status, code, attempts, refreshes):
    page, api = ui
    api.waiting_requests = [{"id": "request", "conversation_id": "conversation", "status": "awaiting_approval"}]
    api.post_failures["/api/m365/requests/request/resume"] = [
        ({"error": code, "message": "The request was forbidden."}, status) for _ in range(attempts)
    ]
    page.goto(f"{ORIGIN}/requests-m365")
    page.get_by_role("button", name="Resume request").click()
    expect(page.locator("#m365-waiting-requests")).to_contain_text("The request was forbidden.")
    expect(page.get_by_role("button", name="Resume request")).to_be_enabled()
    assert len(api.m365_posts) == attempts
    assert api.preference_reads == refreshes
    assert not api.resume_requests
    assert not api.errors


@pytest.mark.ui
def test_workflow_run_as_selection_preserves_an_unavailable_saved_account(ui):
    page, api = ui
    page.goto(f"{ORIGIN}/workflow-m365")
    page.evaluate("""async () => {
        const module = await import('/static/js/workspace/workspace-m365-workflows.js');
        window.runAsControl = module.createMicrosoft365RunAsControl(
            document.getElementById('workflow-anchor'), () => ({ scope: 'group', groupId: 'group' })
        );
        await window.runAsControl.load({ m365_run_as_user_id: 'removed-reader' });
    }""")
    select = page.get_by_label("Microsoft 365 Run as", exact=True)
    expect(select).to_have_value("removed-reader")
    expect(page.locator("#workflow-m365-run-as-help")).to_contain_text("manual and scheduled")
    select.select_option("data-user")
    selected = page.evaluate("window.runAsControl.getValue()")
    assert selected == "data-user"
    assert not api.errors


@pytest.mark.ui
def test_waiting_request_resumes_through_approvals_with_csrf(ui):
    page, api = ui
    api.waiting_requests = [{
        "id": "request", "conversation_id": "original-conversation", "status": "awaiting_approval",
    }]
    page.goto(f"{ORIGIN}/requests-m365")
    page.get_by_role("button", name="Resume request").click()
    expect(page.locator("#m365-waiting-requests")).to_contain_text("result will appear in the original conversation")
    assert api.resume_requests == ["/api/m365/requests/request/resume"]
    assert not api.errors


@pytest.mark.ui
def test_waiting_request_resume_can_transition_to_in_chat_sign_in(ui):
    page, api = ui
    api.waiting_requests = [{
        "id": "request", "conversation_id": "conversation", "status": "awaiting_approval",
    }]
    api.resume_response = {"auth_required": True, "message": "Sign in again to restore your session."}
    page.goto(f"{ORIGIN}/requests-m365")
    page.get_by_role("button", name="Resume request").click()
    expect(page.locator("#m365-waiting-requests")).to_contain_text("Sign in again to restore your session.")
    expect(page.get_by_role("button", name="Connect Microsoft 365", exact=True)).to_be_visible()
    expect(page.get_by_role("button", name="Resume request")).to_have_count(0)
    expect(page.locator("#m365-waiting-requests a")).to_have_count(0)
    assert not api.errors


@pytest.mark.ui
def test_conversation_acknowledgement_audit_is_lazy_and_text_only(ui):
    page, api = ui
    api.audit_records = [{
        "created_at": "2026-09-17", "source": "<img src=x onerror=alert(1)>",
        "event_type": "approved", "approval_id": "approval-reference",
        "effective_grant": {"effective_duration": "today"},
    }]
    page.goto(f"{ORIGIN}/audit-m365")
    page.evaluate("""async () => {
        const module = await import('/static/js/chat/chat-m365-audit.js');
        module.appendMicrosoft365Audit(document.getElementById('conversation-details'), 'conversation');
    }""")
    page.get_by_text("Microsoft 365 sharing and analysis acknowledgements", exact=True).click()
    expect(page.locator("#conversation-details")).to_contain_text("Approval: approval-reference")
    expect(page.locator("#conversation-details")).to_contain_text("(today)")
    expect(page.locator("#conversation-details img")).to_have_count(0)
    assert not api.errors


@pytest.mark.ui
def test_workflow_delivery_controls_follow_the_run_as_viewer(ui):
    page, api = ui
    page.goto(f"{ORIGIN}/workflow-controls")
    page.add_script_tag(url=f"{ORIGIN}/static/js/workflow/workflow-activity.js")
    action = {
        "id": "delivery", "type": "msgraph_pending_action", "status": "pending",
        "action_mode": "manual", "can_send_now": False, "can_cancel": False,
    }
    page.evaluate("action => renderPendingActionControls({ pending_action: action })", action)
    controls = page.locator("#workflow-activity-pending-action-controls")
    expect(controls.get_by_role("button")).to_have_count(0)
    expect(controls).to_contain_text("Only the selected Run as user")
    page.evaluate("action => renderPendingActionControls({ pending_action: action })", {
        **action, "can_send_now": True, "can_cancel": True,
    })
    expect(controls.get_by_role("button", name="Send", exact=True)).to_be_visible()
    expect(controls.get_by_role("button", name="Cancel", exact=True)).to_be_visible()
    page.evaluate("action => renderPendingActionControls({ pending_action: action })", {
        **action, "status": "recovery_required", "error": "Check Microsoft 365 before retrying.",
    })
    expect(controls.get_by_role("button")).to_have_count(0)
    expect(controls).to_contain_text("Check Microsoft 365 before retrying.")
    page.evaluate("""() => updateWorkflowCancelButton(
        { id: 'workflow' }, { id: 'run', status: 'awaiting_approval' }
    )""")
    expect(page.locator("#workflow-activity-cancel-btn")).to_be_visible()
    expect(page.locator("#workflow-activity-cancel-btn")).to_be_enabled()
    assert not api.errors


@pytest.mark.ui
@pytest.mark.parametrize("viewport", [{"width": 1440, "height": 900}, {"width": 390, "height": 844}])
@pytest.mark.parametrize("status,sources,message", [
    ("available", list(SOURCES), "Sign-in saved for this session"),
    ("not_connected", [], "No Microsoft 365 sign-in is saved for this session"),
    ("reconnect_required", ["email"], "Reconnect Microsoft 365 before using these sources in chat"),
])
def test_profile_chat_reconnect_is_available_without_a_pending_request(ui, viewport, status, sources, message):
    page, api = ui
    api.chat_connection = {"status": status, "sources": sources}
    page.set_viewport_size(viewport)
    page.goto(f"{ORIGIN}/profile?tab=settings")
    region = page.get_by_role("region", name="Microsoft 365 chat connection", exact=True)
    expect(region.get_by_role("button", name="Reconnect Microsoft 365 for chat", exact=True)).to_be_enabled()
    expect(region.locator("#m365-chat-connection-status")).to_contain_text(message)
    expect(region).to_contain_text("Access is checked when a source runs")
    expect(region).to_contain_text("does not require Key Vault")
    expect(region).to_contain_text("sharing approvals")
    expect(region).to_contain_text("saved workflow credentials")
    expect(region).to_contain_text("workflow Run as")
    expect(region).to_contain_text("disabled action capabilities")
    expect(region).to_contain_text("model or storage configuration")
    expect(region.get_by_role("checkbox")).to_have_count(4)
    for source in SOURCES:
        checkbox = region.locator(f"#m365-chat-connect-{source}")
        if source in sources:
            expect(checkbox).to_be_checked()
        else:
            expect(checkbox).not_to_be_checked()
    expect(page.locator("#m365-connection-fields")).to_be_enabled()
    expect(page.locator("#m365-bindings-status")).to_contain_text("No workflow authorizations")
    layout = region.evaluate("""element => ({
        content: element.scrollWidth, width: element.clientWidth,
        left: element.getBoundingClientRect().left,
        right: element.getBoundingClientRect().right, viewport: window.innerWidth
    })""")
    assert layout["content"] <= layout["width"]
    assert 0 <= layout["left"] < layout["right"] <= layout["viewport"]
    assert api.api_paths[0] == "/api/m365/preferences"
    assert "/api/m365/chat/connection" in api.api_paths
    assert "/api/m365/requests" not in api.api_paths
    assert not api.m365_posts
    assert not api.errors


@pytest.mark.ui
@pytest.mark.parametrize("source,description", [
    ("calendar", "reading events, creating invitations"),
    ("email", "reading messages, managing drafts and read state, sending mail"),
    ("onedrive", "file discovery and reading"),
    ("spo", "file discovery and reading"),
])
def test_profile_chat_source_selection_is_separate_from_workflow_and_sharing(ui, source, description):
    page, api = ui
    api.chat_connection = {"status": "available", "sources": list(SOURCES)}
    api.connection = {
        "id": "saved-workflow", "status": "connected", "sources": ["spo"],
        "authorized_scopes": ["Files.Read.All"],
    }
    saved_connection = copy.deepcopy(api.connection)
    saved_preferences = copy.deepcopy(api.preferences)
    page.goto(f"{ORIGIN}/profile")
    expect(page.locator("#m365-chat-connect-btn")).to_be_enabled()
    expect(page.locator("#m365-chat-source-permissions-help")).to_contain_text(description)
    expect(page.locator("#m365-chat-source-permissions-help")).to_contain_text("Microsoft shows the permissions")
    expect(page.locator("#m365-connect-spo")).to_be_checked()
    for selected_source in SOURCES:
        page.locator(f"#m365-chat-connect-{selected_source}").set_checked(selected_source == source)
    page.locator("#m365-chat-connect-btn").click()
    expect(page.get_by_role("heading", name="Microsoft sign-in fixture")).to_be_visible()
    assert api.profile_chat_connect_requests == [{"sources": [source]}]
    assert api.m365_posts == [{
        "path": "/api/m365/chat/connection/connect", "method": "POST",
        "body": {"sources": [source]}, "csrf": CSRF_TOKEN,
    }]
    assert api.connection == saved_connection
    assert api.preferences == saved_preferences
    assert not api.connect_requests
    assert not api.chat_connect_requests
    assert not api.preference_writes
    assert not api.decisions
    assert not api.revocations
    assert not api.errors


@pytest.mark.ui
@pytest.mark.parametrize("authorization_endpoint", [
    "https://login.microsoftonline.com/ui-test-tenant/oauth2/v2.0/authorize",
    "https://login.microsoftonline.us/ui-test-tenant/oauth2/v2.0/authorize",
    "https://login.chinacloudapi.cn/ui-test-tenant/oauth2/v2.0/authorize",
    "https://identity.custom-cloud.test:8443/organizations/ui-test-tenant/authentication/start",
])
def test_profile_chat_reconnect_preserves_server_oauth_for_each_cloud_in_the_same_tab(ui, authorization_endpoint):
    page, api = ui
    oauth_query = {
        "state": "ui-profile-state.with+reserved/&values",
        "nonce": "ui-profile-nonce",
        "code_challenge": "ui-profile-pkce-challenge-not-a-credential",
        "code_challenge_method": "S256",
        "redirect_uri": "https://simplechat.test/getAToken",
    }
    api.authorization_url = f"{authorization_endpoint}?{urlencode(oauth_query)}"
    page.goto(f"{ORIGIN}/profile")
    page.locator("#m365-chat-connect-calendar").check()
    page.locator("#m365-chat-connect-email").check()
    page.locator("#m365-chat-connect-btn").click()
    expect(page.get_by_role("heading", name="Microsoft sign-in fixture")).to_be_visible()
    assert page.context.pages == [page]
    assert api.oauth_navigations == [api.authorization_url]
    forwarded_query = parse_qs(urlsplit(page.url).query)
    assert forwarded_query == {key: [value] for key, value in oauth_query.items()}
    assert api.profile_chat_connect_requests == [{"sources": ["calendar", "email"]}]
    assert not api.chat_connect_requests
    assert not api.resume_requests
    assert not api.errors


@pytest.mark.ui
def test_profile_chat_reconnect_requires_a_source_and_allows_correction(ui):
    page, api = ui
    page.goto(f"{ORIGIN}/profile")
    page.locator("#m365-chat-connect-btn").click()
    status = page.locator("#m365-chat-connection-status")
    expect(status).to_contain_text("Select at least one source to reconnect for chat")
    expect(status).to_have_class("alert alert-warning")
    expect(status).to_be_focused()
    expect(page.locator("#m365-chat-connect-btn")).to_be_enabled()
    assert not api.m365_posts
    page.locator("#m365-chat-connect-calendar").check()
    page.locator("#m365-chat-connect-btn").click()
    expect(page.get_by_role("heading", name="Microsoft sign-in fixture")).to_be_visible()
    assert api.profile_chat_connect_requests == [{"sources": ["calendar"]}]
    assert not api.errors


@pytest.mark.ui
@pytest.mark.parametrize("failure_stage", ["status", "connect"])
def test_profile_chat_reconnect_does_not_depend_on_workflow_key_vault(ui, failure_stage):
    page, api = ui
    if failure_stage == "status":
        api.get_failures["/api/m365/connections"] = [
            ({"message": "Key Vault is unavailable for workflow connections."}, 503)
        ]
    page.goto(f"{ORIGIN}/profile")
    if failure_stage == "connect":
        page.locator("#m365-connect-onedrive").check()
        page.locator("#m365-connect-btn").click()
    expect(page.locator("#m365-connection-status")).to_contain_text("Key Vault")
    expect(page.locator("#m365-chat-connect-btn")).to_be_enabled()
    page.locator("#m365-chat-connect-email").check()
    page.locator("#m365-chat-connect-btn").click()
    expect(page.get_by_role("heading", name="Microsoft sign-in fixture")).to_be_visible()
    assert api.profile_chat_connect_requests == [{"sources": ["email"]}]
    assert not api.chat_connect_requests
    assert not api.errors


@pytest.mark.ui
@pytest.mark.parametrize("failure_stage", ["status", "connect"])
def test_profile_chat_errors_do_not_block_the_existing_workflow_connect_path(ui, failure_stage):
    page, api = ui
    api.workflow_connect_available = True
    message = 'Model context is unavailable. Check model or storage configuration. <img src=x onerror="window.injected=true">'
    failure = ({"error": "model_context_unavailable", "message": message}, 503)
    if failure_stage == "status":
        api.get_failures["/api/m365/chat/connection"] = [failure]
    else:
        api.post_failures["/api/m365/chat/connection/connect"] = [failure]
    page.goto(f"{ORIGIN}/profile")
    if failure_stage == "connect":
        page.locator("#m365-chat-connect-email").check()
        page.locator("#m365-chat-connect-btn").click()
    status = page.locator("#m365-chat-connection-status")
    expect(status).to_have_text(message)
    expect(status).to_have_class("alert alert-danger")
    expect(status.locator("img")).to_have_count(0)
    expect(status).not_to_contain_text("expired")
    expect(page.locator("#m365-connect-btn")).to_be_enabled()
    assert not api.oauth_navigations
    page.locator("#m365-connect-onedrive").check()
    page.locator("#m365-connect-btn").click()
    expect(page.get_by_role("heading", name="Microsoft sign-in fixture")).to_be_visible()
    assert api.connect_requests == [{"sources": ["onedrive"]}]
    assert api.m365_posts[-1] == {
        "path": "/api/m365/connections/connect", "method": "POST",
        "body": {"sources": ["onedrive"]}, "csrf": CSRF_TOKEN,
    }
    assert not api.profile_chat_connect_requests
    assert not api.chat_connect_requests
    assert not api.decisions
    assert not api.revocations
    assert not api.errors


@pytest.mark.ui
def test_profile_chat_connect_failure_allows_only_an_explicit_retry(ui):
    page, api = ui
    api.post_failures["/api/m365/chat/connection/connect"] = [
        ({"message": "Microsoft 365 sign-in could not be started. Try again."}, 503)
    ]
    page.goto(f"{ORIGIN}/profile")
    page.locator("#m365-chat-connect-email").check()
    page.locator("#m365-chat-connect-btn").click()
    expect(page.locator("#m365-chat-connection-status")).to_contain_text("could not be started")
    expect(page.locator("#m365-chat-connection-status")).to_be_focused()
    expect(page.locator("#m365-chat-connect-btn")).to_be_enabled()
    expect(page.locator("#m365-chat-connect-email")).to_be_checked()
    assert len(api.m365_posts) == 1
    assert not api.oauth_navigations
    page.locator("#m365-chat-connect-btn").click()
    expect(page.get_by_role("heading", name="Microsoft sign-in fixture")).to_be_visible()
    assert len(api.m365_posts) == 2
    assert api.profile_chat_connect_requests == [{"sources": ["email"]}]
    assert not api.resume_requests
    assert not api.errors


@pytest.mark.ui
@pytest.mark.parametrize("connection", [
    None,
    {"status": "connected", "sources": ["email"]},
    {"status": "available", "sources": "email"},
    {"status": "available", "sources": [["email"]]},
    {"status": "available", "sources": ['<img src=x onerror="window.injected=true">']},
])
def test_profile_chat_invalid_status_is_visible_without_blocking_workflow_controls(ui, connection):
    page, api = ui
    api.chat_connection = connection
    page.goto(f"{ORIGIN}/profile")
    expect(page.locator("#m365-chat-connection-status")).to_contain_text("chat sign-in status could not be verified")
    expect(page.locator("#m365-chat-connection-status")).to_have_class("alert alert-danger")
    expect(page.locator("#m365-chat-connect-btn")).to_be_disabled()
    expect(page.locator("#m365-chat-connection img")).to_have_count(0)
    expect(page.locator("#m365-connect-btn")).to_be_enabled()
    api.chat_connection = {"status": "not_connected", "sources": []}
    page.locator("#m365-profile-refresh").click()
    expect(page.locator("#m365-chat-connect-btn")).to_be_enabled()
    expect(page.locator("#m365-chat-connection-status")).to_contain_text("No Microsoft 365 sign-in is saved")
    assert not api.m365_posts
    assert not api.errors


@pytest.mark.ui
@pytest.mark.parametrize("url", [
    "javascript:window.injected=true",
    "http://login.microsoftonline.com/tenant/oauth2/v2.0/authorize",
    "https://person@login.microsoftonline.com/tenant/oauth2/v2.0/authorize",
    "https://",
    "https://[invalid/authorize",
    "/relative-sign-in",
    "",
    None,
    ["https://login.microsoftonline.com/tenant/oauth2/v2.0/authorize"],
])
def test_profile_chat_connect_rejects_invalid_oauth_urls_with_a_visible_error(ui, url):
    page, api = ui
    api.authorization_url = url
    page.goto(f"{ORIGIN}/profile")
    page.locator("#m365-chat-connect-email").check()
    page.locator("#m365-chat-connect-btn").click()
    expect(page.locator("#m365-chat-connection-status")).to_contain_text("valid HTTPS Microsoft 365 sign-in URL")
    expect(page.locator("#m365-chat-connection-status")).to_have_class("alert alert-danger")
    expect(page.locator("#m365-chat-connect-btn")).to_be_enabled()
    expect(page.locator("#m365-chat-connect-email")).to_be_checked()
    assert page.url == f"{ORIGIN}/profile"
    assert len(api.m365_posts) == 1
    assert not api.oauth_navigations
    assert not api.resume_requests
    assert not api.errors


@pytest.mark.ui
def test_profile_chat_callback_reports_success_preserves_navigation_and_never_replays(ui):
    page, api = ui
    page.add_init_script("window.history.replaceState({ fixture: 'preserved' }, '', window.location.href)")
    page.goto(f"{ORIGIN}/profile?tab=settings")
    page.locator("#m365-chat-connect-email").check()
    page.locator("#m365-chat-connect-btn").click()
    expect(page.get_by_role("heading", name="Microsoft sign-in fixture")).to_be_visible()
    api.chat_connection = {"status": "available", "sources": ["email"], "connected_at": "2026-09-19T12:00:00Z"}
    api.profile_callback_url = (
        f"{ORIGIN}/profile?tab=settings&keep=one%20two&m365_chat_connection=connected&keep=again#m365-chat-connection"
    )
    callback_url = f"{ORIGIN}/getAToken?code=ui-profile-code&state=fixture"
    page.goto(callback_url)
    page.get_by_role("link", name="Return to Microsoft 365 chat connection", exact=True).click()
    notice = page.locator("#m365-chat-connection-notice")
    expect(notice).to_be_visible()
    expect(notice).to_have_class("alert alert-success")
    expect(notice).to_contain_text("Microsoft 365 sign-in completed")
    expect(notice).to_contain_text("retry your original question")
    expect(notice).to_contain_text("No past requests were retried")
    expect(page.locator("#m365-chat-connection-status")).to_contain_text("Sign-in saved for this session")
    expect(page.locator("#m365-chat-connect-btn")).to_be_enabled()
    returned_url = urlsplit(page.url)
    assert returned_url.path == "/profile"
    assert returned_url.fragment == "m365-chat-connection"
    assert parse_qs(returned_url.query) == {"tab": ["settings"], "keep": ["one two", "again"]}
    history_state = page.evaluate("window.history.state")
    assert history_state == {"fixture": "preserved"}
    assert api.auth_callbacks == [callback_url]
    assert api.m365_posts == [{
        "path": "/api/m365/chat/connection/connect", "method": "POST",
        "body": {"sources": ["email"]}, "csrf": CSRF_TOKEN,
    }]
    assert not api.chat_requests
    assert not api.chat_connect_requests
    assert not api.resume_requests
    assert not api.reattach_requests
    assert not api.connect_requests
    assert not api.decisions
    assert not api.revocations
    page.reload()
    expect(notice).to_be_hidden()
    expect(page.locator("#m365-chat-connect-btn")).to_be_enabled()
    assert len(api.m365_posts) == 1
    assert not api.errors


@pytest.mark.ui
def test_profile_chat_callback_does_not_claim_success_for_an_unknown_result(ui):
    page, api = ui
    page.goto(f"{ORIGIN}/profile?tab=settings&m365_chat_connection=unknown#m365-chat-connection")
    expect(page.locator("#m365-chat-connect-btn")).to_be_enabled()
    expect(page.locator("#m365-chat-connection-notice")).to_be_hidden()
    expect(page).to_have_url(f"{ORIGIN}/profile?tab=settings#m365-chat-connection")
    assert not api.m365_posts
    assert not api.errors


@pytest.mark.ui
@pytest.mark.parametrize("source,description", [
    ("calendar", "reading events, creating invitations"),
    ("email", "reading messages, managing drafts and read state, sending mail"),
    ("onedrive", "file discovery and reading"),
    ("spo", "file discovery and reading"),
])
def test_profile_source_selection_authorizes_supported_bundle_without_extra_checkboxes(ui, source, description):
    page, api = ui
    page.goto(f"{ORIGIN}/profile")
    expect(page.locator('[data-m365-extra-scope]')).to_have_count(0)
    expect(page.locator("#m365-source-permissions-help")).to_contain_text(description)
    expect(page.locator("#m365-source-permissions-help")).to_contain_text("workflow Run as approvals")
    page.locator(f"#m365-connect-{source}").check()
    page.locator("#m365-connect-btn").click()
    expect(page.locator("#m365-connection-status")).to_contain_text("Key Vault")
    assert api.connect_requests == [{"sources": [source]}]
    assert not api.errors


@pytest.mark.ui
def test_admin_provider_and_custom_download_host_controls(ui):
    page, api = ui
    page.goto(f"{ORIGIN}/admin-m365")
    provider = page.get_by_label("Retrieval provider", exact=True)
    expect(provider).to_have_value("auto")
    provider.select_option("graph")
    hosts = page.get_by_label("Additional trusted file-download hosts", exact=True)
    hosts.fill("downloads.internal.example")
    expect(provider).to_have_value("graph")
    expect(hosts).to_have_value("downloads.internal.example")
    expect(page.locator("#m365-download-hosts-help")).to_contain_text("not which folders")
    assert not api.errors


def open_records(page, records, resume_error=False):
    page.locator("#open").focus()
    page.evaluate(
        """({ records, resumeError }) => {
            window.resumeCalls = 0;
            window.approvalResult = null;
            window.approvalPromise = window.SimpleChatM365Approvals.openApprovals({ approvals: records }, {
                onResume: async () => {
                    window.resumeCalls += 1;
                    if (resumeError && window.resumeCalls === 1) {
                        throw new Error('Resume is temporarily unavailable.');
                    }
                }
            });
            window.approvalPromise.then(result => { window.approvalResult = result; });
        }""",
        {"records": [{"id": record["id"]} for record in records], "resumeError": resume_error},
    )
    expect(page.locator("#m365ApprovalsModal")).to_be_visible()
    expect(page.locator("#m365-approvals-status")).to_contain_text("Choose an outcome")
    page.wait_for_function("document.getElementById('m365ApprovalsModal').contains(document.activeElement)")


@pytest.mark.ui
@pytest.mark.parametrize("viewport", [{"width": 1440, "height": 900}, {"width": 390, "height": 844}])
def test_source_sharing_policy_ceiling_disclosure_and_focus(ui, viewport):
    page, api = ui
    record = approval()
    record["reason"] = '<img src=x onerror="window.injected=true"> private evidence'
    api.records[record["id"]] = record
    page.set_viewport_size(viewport)
    page.goto(f"{ORIGIN}/modal")
    open_records(page, [record])
    expect(page.locator("#m365-approvals-title")).to_be_focused()
    expect(page.locator("#m365-sharing-warning")).to_contain_text("entire retained source-evidence snapshot")
    expect(page.locator("#m365-sharing-warning")).to_contain_text("without their own source access")
    expect(page.locator("#m365-approval-records img")).to_have_count(0)
    calendar = page.get_by_role("group", name="Calendar sharing decision")
    email = page.get_by_role("group", name="Email sharing decision")
    expect(calendar.get_by_role("button", name="Always allow", exact=True)).to_have_count(0)
    expect(calendar.get_by_role("button", name="Allow for today", exact=True)).to_have_count(0)
    expect(email.get_by_role("button", name="Always allow", exact=True)).to_have_count(0)
    calendar.get_by_role("button", name="No", exact=True).click()
    email.get_by_role("button", name="Allow for today", exact=True).click()
    page.locator("#m365-approvals-apply").click()
    expect(page.locator("#m365ApprovalsModal")).to_be_hidden()
    expect(page.locator("#open")).to_be_focused()
    result = page.evaluate("window.approvalResult")
    resume_calls = page.evaluate("window.resumeCalls")
    assert result["status"] == "decided"
    assert result["approvals"][0]["execution_status"] == "queued"
    assert resume_calls == 1
    assert api.decisions == [("sharing", {"decisions": {
        "calendar": {"duration": "no"},
        "email": {"duration": "today", "timezone": "America/New_York"},
    }})]
    assert not api.errors


@pytest.mark.ui
def test_all_three_approval_kinds_use_saved_decisions(ui):
    page, api = ui
    sharing = approval()
    analysis = approval("analysis", "m365_extended_analysis", shared=False)
    analysis["sources"] = {"onedrive": {}}
    analysis["proposal"] = {"file_count": 4, "download_count": 4, "total_bytes": 67108864, "context_tokens": 24000}
    workflow = approval("workflow", "m365_workflow_run_as", shared=False)
    workflow["context"]["workflow_id"] = "approved-workflow-revision"
    api.records = {record["id"]: record for record in [sharing, analysis, workflow]}
    page.goto(f"{ORIGIN}/modal")
    open_records(page, [sharing, analysis, workflow])
    analysis_section = page.locator('[data-approval-id="analysis"]')
    expect(analysis_section).to_contain_text("Requested analysis")
    expect(analysis_section).to_contain_text("Content downloads")
    expect(analysis_section).to_contain_text("67,108,864")
    expect(analysis_section).to_contain_text("24,000")
    page.get_by_role("group", name="Calendar sharing decision").get_by_role("button", name="No", exact=True).click()
    page.get_by_role("group", name="Email sharing decision").get_by_role("button", name="Allow this request", exact=True).click()
    page.get_by_role("button", name="Use a faster answer", exact=True).click()
    expect(page.get_by_role("button", name="Allow this workflow revision", exact=True)).to_have_count(0)
    page.get_by_role("group", name="Workflow Run as decision").get_by_role("button", name="No", exact=True).click()
    expect(page.locator("#m365-approval-records svg")).to_have_count(0)
    page.locator("#m365-approvals-apply").click()
    expect(page.locator("#m365ApprovalsModal")).to_be_hidden()
    assert api.decisions[1:] == [("analysis", {"choice": "fast"}), ("workflow", {"choice": "deny"})]
    assert not api.errors


@pytest.mark.ui
def test_workflow_approval_requires_reviewable_revision_and_renders_it_as_text(ui):
    page, api = ui
    record = approval("workflow", "m365_workflow_run_as", shared=False)
    record["binding"] = {"review": {
        "instructions": '<img src=x onerror="window.injected=true">Summarize files',
        "capabilities": "Read OneDrive files only.",
        "runtime_inputs": "User-supplied folder",
        "triggers": "Manual",
        "destinations": "conversation",
    }}
    api.records["workflow"] = record
    page.goto(f"{ORIGIN}/modal")
    open_records(page, [record])
    expect(page.locator("#m365-approval-records")).to_contain_text("Summarize files")
    expect(page.locator("#m365-approval-records img")).to_have_count(0)
    expect(page.locator("#m365-sharing-warning")).to_be_hidden()
    page.get_by_role("button", name="Allow this workflow revision", exact=True).click()
    page.locator("#m365-approvals-apply").click()
    expect(page.locator("#m365ApprovalsModal")).to_be_hidden()
    assert api.decisions == [("workflow", {"choice": "approve"})]
    assert not api.errors


@pytest.mark.ui
def test_repeated_open_and_keyboard_dismissal_do_not_record_permission(ui):
    page, api = ui
    record = approval()
    api.records["sharing"] = record
    page.goto(f"{ORIGIN}/modal")
    open_records(page, [record])
    same_promise = page.evaluate("""() => {
        return window.approvalPromise === window.SimpleChatM365Approvals.openApprovals({
            approvals: [{ id: 'sharing' }]
        });
    }""")
    assert same_promise
    page.keyboard.press("Escape")
    expect(page.locator("#m365ApprovalsModal")).to_be_hidden()
    expect(page.locator("#open")).to_be_focused()
    result = page.evaluate("window.approvalResult")
    assert result["status"] == "dismissed"
    assert not api.decisions
    open_records(page, [record])
    page.get_by_role("group", name="Calendar sharing decision").get_by_role("button", name="No", exact=True).click()
    page.get_by_role("group", name="Email sharing decision").get_by_role("button", name="No", exact=True).click()
    page.locator("#m365-approvals-apply").click()
    expect(page.locator("#m365ApprovalsModal")).to_be_hidden()
    assert len(api.decisions) == 1
    assert not api.errors


@pytest.mark.ui
def test_failed_decision_and_resume_never_implicitly_allow_or_replay(ui):
    page, api = ui
    record = approval("analysis", "m365_extended_analysis", shared=False)
    api.records["analysis"] = record
    api.fail_decision = True
    page.goto(f"{ORIGIN}/modal")
    open_records(page, [record], resume_error=True)
    expect(page.locator("#m365-sharing-warning")).to_be_hidden()
    page.get_by_role("button", name="Analyze more for this request", exact=True).click()
    page.locator("#m365-approvals-apply").click()
    expect(page.locator("#m365-approvals-error")).to_contain_text("Storage")
    expect(page.locator("#m365ApprovalsModal")).to_be_visible()
    calls = page.evaluate("window.resumeCalls")
    assert calls == 0
    assert not api.decisions
    api.fail_decision = False
    page.locator("#m365-approvals-apply").click()
    expect(page.locator("#m365-approvals-error")).to_contain_text("Resume is temporarily unavailable")
    expect(page.locator("#m365-approvals-apply")).to_have_text("Retry resume")
    page.locator("#m365-approvals-apply").click()
    expect(page.locator("#m365ApprovalsModal")).to_be_hidden()
    assert api.decisions == [("analysis", {"choice": "request"})]
    assert not api.errors


@pytest.mark.ui
def test_private_context_and_readonly_records_do_not_offer_sharing(ui):
    page, api = ui
    private = approval(shared=False)
    api.records["sharing"] = private
    page.goto(f"{ORIGIN}/modal")
    open_records(page, [private])
    expect(page.locator("#m365-sharing-warning")).to_be_hidden()
    expect(page.locator("#m365-approvals-error")).to_contain_text("does not describe a shared conversation")
    expect(page.locator("#m365-approvals-apply")).to_be_disabled()
    page.get_by_role("button", name="Leave pending / close", exact=True).click()
    expect(page.locator("#m365ApprovalsModal")).to_be_hidden()
    private["can_approve"] = False
    private["can_deny"] = False
    open_records(page, [private])
    expect(page.locator("#m365-approval-records")).to_contain_text("not actionable by your account")
    expect(page.locator("#m365-approvals-apply")).to_be_disabled()
    assert not api.decisions
    assert not api.errors


@pytest.mark.ui
def test_profile_preferences_revocations_and_unavailable_connection(ui):
    page, api = ui
    api.preferences["sources"]["email"] = "always"
    page.goto(f"{ORIGIN}/profile")
    expect(page.locator("#m365-preferences-fields")).to_be_enabled()
    expect(page.locator("#m365-profile-timezone")).to_have_text("America/New_York")
    expect(page.locator("#m365-profile-timezone-help")).to_contain_text("not stored as a Profile preference")
    page.locator("#m365-sharing-calendar").select_option("request")
    page.locator("#m365-analysis-onedrive").select_option("always")
    page.locator("#m365-preferences-save").click()
    expect(page.locator("#m365-preferences-status")).to_contain_text("Preferences saved")
    assert set(api.preference_writes[-1]) == {"sources", "extended_analysis"}
    assert api.preference_writes[-1]["extended_analysis"]["onedrive"] == "always"
    assert api.preference_writes[-1]["sources"]["email"] == "always"
    page.locator('[data-m365-revoke-source="email"]').click()
    expect(page.locator("#m365RevokeModal")).to_be_visible()
    expect(page.locator("#m365-revoke-description")).to_contain_text("Revoke existing Email")
    page.locator("#m365-revoke-confirm").click()
    expect(page.locator("#m365RevokeModal")).to_be_hidden()
    expect(page.locator("#m365-sharing-email")).to_have_value("ask")
    page.locator("#m365-connect-onedrive").check()
    page.locator("#m365-connect-btn").click()
    expect(page.locator("#m365-connection-status")).to_contain_text("Key Vault")
    assert api.connect_requests == [{"sources": ["onedrive"]}]
    assert not api.errors


@pytest.mark.ui
def test_profile_own_connection_disconnect_and_binding_revoke(ui):
    page, api = ui
    api.connection = {
        "id": "own-connection", "status": "connected", "tenant_id": "tenant",
        "account_username": '<img src=x onerror="window.injected=true">user@example.test',
        "cloud": "government", "sources": ["onedrive"], "authorized_scopes": ["Files.Read.All"],
    }
    binding = approval("binding", "m365_workflow_run_as", shared=False)
    binding["status"] = "approved"
    binding["context"]["workflow_id"] = "workflow"
    api.records["binding"] = binding
    page.goto(f"{ORIGIN}/profile")
    expect(page.locator("#m365-connection-status")).to_contain_text("connected")
    expect(page.locator("#m365-connection-details")).to_contain_text("Files.Read.All")
    expect(page.locator("#m365-connection-details img")).to_have_count(0)
    page.get_by_role("button", name="Revoke workflow authorization", exact=True).click()
    page.locator("#m365-revoke-confirm").click()
    expect(page.locator("#m365RevokeModal")).to_be_hidden()
    expect(page.locator("#m365-workflow-bindings")).to_contain_text("revoked")
    page.locator("#m365-disconnect-btn").click()
    page.locator("#m365-revoke-confirm").click()
    expect(page.locator("#m365RevokeModal")).to_be_hidden()
    expect(page.locator("#m365-connection-status")).to_contain_text("disconnected")
    assert api.revocations[-1] == ("/api/m365/connections/disconnect", {"connection_id": "own-connection"})
    assert not api.errors


@pytest.mark.ui
@pytest.mark.parametrize("action_type", ["m365_calendar", "m365_email", "m365_onedrive", "m365_sharepoint"])
def test_four_source_action_forms_and_inherited_endpoint(ui, action_type):
    page, api = ui
    page.goto(f"{ORIGIN}/plugin")
    page.evaluate("""async () => {
        const module = await import('/static/js/plugin_modal_stepper.js');
        window.stepper = new module.PluginModalStepper();
        await window.stepper.showModal();
    }""")
    expect(page.locator('.action-type-card[data-type="msgraph"]')).to_have_count(0)
    page.locator(f'.action-type-card[data-type="{action_type}"]').click()
    page.locator("#plugin-modal-next").click()
    page.locator("#plugin-display-name").fill("Source action")
    page.locator("#plugin-modal-next").click()
    expect(page.locator(f"#{action_type}-config-section")).to_be_visible()
    expect(page.locator("#generic-config-section")).to_be_hidden()
    for other in ("m365_calendar", "m365_email", "m365_onedrive", "m365_sharepoint"):
        if other != action_type:
            expect(page.locator(f"#{other}-config-section")).to_be_hidden()
    page.locator("#m365-maximum-sharing-acknowledgement").select_option("request")
    result = page.evaluate("window.stepper.getFormData()")
    definition = next(item for item in api.catalog if item["type"] == action_type)
    assert result["type"] == action_type
    assert result["endpoint"] == ""
    assert result["auth"] == {"type": "user"}
    assert result["additionalFields"]["maximum_sharing_acknowledgement"] == "request"
    assert result["additionalFields"]["m365_capabilities"] == definition["defaults"]["m365_capabilities"]
    if action_type == "m365_calendar":
        assert result["additionalFields"]["msgraph_calendar_send_mode"] == "draft_manual"
    assert not api.errors


@pytest.mark.ui
def test_existing_legacy_editor_preserves_id_cloud_and_deletion_warning(ui):
    page, api = ui
    legacy = {
        "id": "stored-legacy", "name": "graph", "displayName": "Legacy Graph", "description": "Existing",
        "type": "msgraph", "endpoint": "https://graph.microsoft.us", "auth": {"type": "user"},
        "metadata": {}, "additionalFields": {"msgraph_capabilities": {"send_mail": False}},
    }
    page.goto(f"{ORIGIN}/plugin")
    page.evaluate("""async legacy => {
        const module = await import('/static/js/plugin_modal_stepper.js');
        window.stepper = new module.PluginModalStepper();
        await window.stepper.showModal(legacy);
        window.stepper.goToStep(3);
    }""", legacy)
    expect(page.locator("#msgraph-legacy-notice")).to_be_visible()
    expect(page.locator("#msgraph-legacy-notice")).to_contain_text("After deletion")
    saved = page.evaluate("window.stepper.getFormData()")
    assert saved["id"] == "stored-legacy"
    assert saved["endpoint"] == "https://graph.microsoft.us"
    assert saved["additionalFields"]["msgraph_capabilities"]["send_mail"] is False
    blocked = page.evaluate("""() => {
        window.stepper.originalPlugin.id = '';
        try { window.stepper.getFormData(); return false; } catch (error) { return true; }
    }""")
    assert blocked
    assert not api.errors


@pytest.mark.ui
def test_agent_capabilities_cannot_enable_a_disabled_source_operation(ui):
    page, api = ui
    page.goto(f"{ORIGIN}/agent")
    page.evaluate("""async () => {
        const module = await import('/static/js/agent_modal_stepper.js');
        window.agentStepper = Object.create(module.AgentModalStepper.prototype);
        window.agentStepper.availableActions = [{
            id: 'calendar', name: 'Calendar', type: 'm365_calendar',
            additionalFields: { m365_capabilities: { get_my_events: false, get_my_timezone: true } }
        }];
        document.getElementById('agent-additional-settings').value = JSON.stringify({
            action_capabilities: { calendar: { get_my_events: true } }
        });
        const card = document.createElement('div');
        card.className = 'action-card border-primary';
        card.dataset.actionId = 'calendar';
        card.dataset.actionName = 'Calendar';
        card.dataset.actionType = 'm365_calendar';
        document.getElementById('agent-actions-container').appendChild(card);
        document.getElementById('agent-step-3').classList.remove('d-none');
        bootstrap.Modal.getOrCreateInstance(document.getElementById('agentModal')).show();
        window.agentStepper.renderMsGraphCapabilitySections();
    }""")
    expect(page.locator("#msgraph-capability-calendar-get_my_events")).to_be_disabled()
    expect(page.locator("#msgraph-capability-calendar-get_my_events")).not_to_be_checked()
    expect(page.locator("#msgraph-capability-calendar-send_mail")).to_have_count(0)
    page.locator("#msgraph-capability-calendar-get_my_timezone").uncheck()
    capabilities = page.evaluate("window.agentStepper.getMsGraphCapabilitiesForAction('calendar', 'Calendar')")
    assert capabilities["get_my_events"] is False
    assert capabilities["get_my_timezone"] is False
    assert not api.errors


@pytest.mark.ui
def test_approvals_page_row_opens_the_same_saved_user_request(ui):
    page, api = ui
    record = approval("analysis", "m365_extended_analysis", shared=False)
    record["context"]["conversation_id"] = '<svg onload="window.injected=true">conversation'
    api.records["analysis"] = record
    page.goto(f"{ORIGIN}/approvals")
    page.evaluate("""record => {
        document.getElementById('approvalsTableBody').appendChild(
            window.SimpleChatM365ApprovalList.renderRow(record, () => { window.listRefreshed = true; })
        );
    }""", record)
    expect(page.locator("#approvalsTableBody svg")).to_have_count(0)
    page.get_by_role("button", name="Review my data request", exact=True).click()
    expect(page.locator("#m365ApprovalsModal")).to_be_visible()
    page.get_by_role("button", name="Always allow deeper analysis", exact=True).click()
    page.locator("#m365-approvals-apply").click()
    expect(page.locator("#m365ApprovalsModal")).to_be_hidden()
    assert api.decisions == [("analysis", {"choice": "always"})]
    refreshed = page.evaluate("window.listRefreshed")
    assert refreshed is True
    assert not api.errors


@pytest.mark.ui
def test_mixed_approval_status_shows_each_source_outcome(ui):
    page, api = ui
    record = approval()
    record.update({
        "status": "approved", "execution_status": "awaiting_sign_in",
        "can_approve": False, "can_deny": False,
        "decisions": {"calendar": {"duration": "no"}, "email": {"duration": "request"}},
    })
    api.records[record["id"]] = record
    page.goto(f"{ORIGIN}/approvals")
    page.evaluate("""record => {
        document.getElementById('approvalsTableBody').appendChild(
            window.SimpleChatM365ApprovalList.renderRow(record)
        );
    }""", record)
    expect(page.locator("#approvalsTableBody")).to_contain_text("Decision: approved")
    expect(page.locator("#approvalsTableBody")).to_contain_text("Calendar: No")
    expect(page.locator("#approvalsTableBody")).to_contain_text("Email: Allow this request")
    expect(page.locator("#approvalsTableBody")).to_contain_text("Execution: awaiting sign in")
    page.get_by_role("button", name="View saved decision", exact=True).click()
    expect(page.locator("#m365-approval-records")).to_contain_text("Calendar: No")
    expect(page.locator("#m365-approvals-apply")).to_be_disabled()
    assert not api.decisions
    assert not api.errors


@pytest.mark.ui
def test_confirmed_timezone_is_sent_only_with_affirmative_decisions(ui):
    page, api = ui
    record = approval()
    api.records[record["id"]] = record
    page.goto(f"{ORIGIN}/modal")
    open_records(page, [record])
    page.get_by_role("group", name="Calendar sharing decision").get_by_role("button", name="No", exact=True).click()
    page.get_by_role("group", name="Email sharing decision").get_by_role("button", name="Allow for today", exact=True).click()
    page.locator("#m365-approval-timezone").fill("Not/A_Timezone")
    page.locator("#m365-approvals-apply").click()
    expect(page.locator("#m365-approvals-error")).to_contain_text("valid IANA timezone")
    assert not api.decisions
    page.locator("#m365-approval-timezone").fill("Europe/London")
    page.locator("#m365-approvals-apply").click()
    expect(page.locator("#m365ApprovalsModal")).to_be_hidden()
    assert api.decisions == [("sharing", {"decisions": {
        "calendar": {"duration": "no"},
        "email": {"duration": "today", "timezone": "Europe/London"},
    }})]
    assert not api.preference_writes
    assert not api.errors


@pytest.mark.ui
def test_analysis_choice_remains_visible_as_a_fast_fallback(ui):
    page, api = ui
    record = approval("analysis", "m365_extended_analysis", shared=False)
    record.update({
        "status": "denied", "execution_status": "queued", "analysis_choice": "fast",
        "can_approve": False, "can_deny": False,
    })
    api.records[record["id"]] = record
    page.goto(f"{ORIGIN}/approvals")
    page.evaluate("""record => {
        document.getElementById('approvalsTableBody').appendChild(
            window.SimpleChatM365ApprovalList.renderRow(record)
        );
    }""", record)
    expect(page.locator("#approvalsTableBody")).to_contain_text("Recorded analysis choice: Use a faster answer")
    page.get_by_role("button", name="View saved decision", exact=True).click()
    expect(page.locator("#m365-approval-records")).to_contain_text("Recorded analysis choice: Use a faster answer")
    assert not api.errors


@pytest.mark.ui
def test_invalid_analysis_counts_fail_explicitly(ui):
    page, api = ui
    record = approval("analysis", "m365_extended_analysis", shared=False)
    record["proposal"] = {"file_count": '<svg onload="window.injected=true">'}
    api.records[record["id"]] = record
    page.goto(f"{ORIGIN}/modal")
    open_records(page, [record])
    expect(page.locator("#m365-approvals-error")).to_contain_text("analysis counts could not be verified")
    expect(page.locator("#m365-approvals-apply")).to_be_disabled()
    expect(page.locator("#m365-approval-records svg")).to_have_count(0)
    assert not api.decisions
    assert not api.errors
