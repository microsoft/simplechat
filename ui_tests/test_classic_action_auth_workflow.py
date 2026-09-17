# test_classic_action_auth_workflow.py
"""
Classic private identity and global Yamcs authoring browser regressions.
Version: 0.261.107
Implemented in: 0.261.107

Uses the existing local/Azure Playwright connection fixture and real classic
modal/controller assets. Only application API responses are replaced. Credentials
are synthetic; no live Azure, Yamcs, identity data, or signed-in state is required.
"""

import copy
import json
import mimetypes
import sys
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

# The existing standalone UI harness and Azure connection fixture live here.
sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
from agent_delegation_classic.harness import build_plugin_modal_page, read_partial
from playwright_connection import connect_options  # noqa: F401


pytestmark = pytest.mark.ui
ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "application" / "single_app" / "static"
ORIGIN = "http://simplechat.test"
SYNTHETIC_SECRET = "SYNTHETIC-CLASSIC-PRIVATE-PASSWORD"

HARNESS_MODULE = """
import { prepareActionAuthExecution, handleActionAuthRequired } from '/static/js/chat/chat-action-auth.js';
import { openViewModal } from '/static/js/workspace/view-utils.js';
window.openActionDetails = action => openViewModal(action, 'action');
window.currentConversationId = 'shared-conversation';
window.executionPayloads = [];
window.harnessShared = false;
window.chatCollaboration = { isCollaborationConversation: () => window.harnessShared };
window.repairPrivateAuth = control => handleActionAuthRequired(control, {
    payload: { agent_info: { id: 'mission-agent', is_global: true } },
    conversationId: window.currentConversationId,
});
window.startPrivateAuth = async () => {
    const input = document.getElementById('user-input');
    const draft = input.value;
    const agentId = document.getElementById('harness-agent').value;
    const payload = { message: draft, conversation_id: window.currentConversationId, agent_info: { id: agentId, is_global: true } };
    if (!await prepareActionAuthExecution(payload, {
        isCurrent: () => input.value === draft && document.getElementById('harness-agent').value === agentId,
    })) return;
    const response = await fetch(window.harnessShared
        ? '/api/collaboration/conversations/shared-conversation/stream' : '/api/chat/stream',
        { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    const data = await response.json();
    if (handleActionAuthRequired(data, { payload })) return;
    if (response.ok) {
        window.executionPayloads.push(payload);
        const message = document.createElement('p');
        message.textContent = draft;
        document.getElementById('chatbox').appendChild(message);
        input.value = '';
    }
};
document.getElementById('harness-send').addEventListener('click', window.startPrivateAuth);
window.classicActionAuthHarnessReady = true;
"""


def auth_requirement(profile="yamcs_login", **overrides):
    auth_type = "username_password" if profile in ("yamcs_login", "http_basic") else profile
    fields = (
        [
            {"name": "username", "label": "Username", "type": "text", "required": True},
            {"name": "password", "label": "Password", "type": "password", "required": True},
        ]
        if auth_type == "username_password"
        else [{"name": "secret", "label": "Token", "type": "password", "required": True}]
    )
    return {
        "id": "requirement-1", "action_id": "global-yamcs", "action_name": "Mission telemetry",
        "identity_name": "Yamcs", "profile": profile, "auth_type": auth_type,
        "destination": "https://yamcs.example.test/api", "reason": "missing",
        "fields": fields, "identities": [], **overrides,
    }


class ClassicAuthHarness:
    def __init__(self, page):
        self.page = page
        self.saved = False
        self.shared = False
        self.fail_save = False
        self.requirements = [auth_requirement()]
        self.requests = []
        self.page_errors = []
        page.on("pageerror", lambda error: self.page_errors.append(error))
        page.route("**/*", self.handle)

    def state(self):
        return {
            "status": "ready" if self.saved else "credentials_required",
            "request_id": "private-request", "uses_personal_credentials": True,
            "shared_conversation": self.shared,
            "requirements": [] if self.saved else copy.deepcopy(self.requirements),
        }

    def handle(self, route):
        path = urlsplit(route.request.url).path
        if path.startswith("/application/single_app/static/"):
            relative = path.removeprefix("/application/single_app/static/")
        elif path.startswith("/static/"):
            relative = path.removeprefix("/static/")
        else:
            relative = None
        if relative is not None:
            file_path = (STATIC / relative).resolve()
            assert file_path.is_relative_to(STATIC)
            if file_path.is_file():
                route.fulfill(path=str(file_path), content_type=mimetypes.guess_type(str(file_path))[0] or "application/octet-stream")
            else:
                route.fulfill(status=404, body="")
            return
        if path == "/classic-action-auth-harness.js":
            route.fulfill(content_type="application/javascript", body=HARNESS_MODULE)
            return
        if path in ("/classic-action-auth", "/workspace"):
            markup = build_plugin_modal_page(read_partial("_plugin_modal.html"))
            controls = """
                <main>
                    <div id="chatbox"></div>
                    <div id="chat-action-auth-root" class="d-none" data-identity-setup-url="/workspace?tab=identities"></div>
                    <label for="user-input">Message</label><textarea id="user-input"></textarea>
                    <label for="harness-agent">Agent</label>
                    <select id="harness-agent"><option value="mission-agent">Mission agent</option><option value="different-agent">Other agent</option></select>
                    <button id="harness-send" type="button">Send draft</button>
                </main>
                <script type="module" src="/classic-action-auth-harness.js"></script>
            """
            route.fulfill(content_type="text/html", body=markup.replace("</body>", f"{controls}</body>"))
            return
        if path.startswith("/api/"):
            payload = json.loads(route.request.post_data or "{}") if route.request.method != "GET" else None
            self.requests.append({"path": path, "method": route.request.method, "body": payload})
            if path == "/api/action-auth/preflight" or (path.startswith("/api/action-auth/requests/") and route.request.method == "GET"):
                route.fulfill(json=self.state())
            elif path.endswith("/credentials"):
                if self.fail_save:
                    route.fulfill(status=403, json={"error_code": "action_auth_rejected", "error": SYNTHETIC_SECRET})
                else:
                    self.saved = True
                    route.fulfill(json=self.state())
            elif path.endswith("/cancel"):
                route.fulfill(json={"status": "cancelled"})
            elif path in ("/api/chat/stream", "/api/collaboration/conversations/shared-conversation/stream", "/api/plugins/test-yamcs-connection"):
                route.fulfill(json={"success": True})
            elif path.endswith("/plugins/types"):
                route.fulfill(json=[{"type": "yamcs", "display": "Yamcs", "description": "Read-only telemetry"}])
            elif path.endswith("/identities"):
                route.fulfill(json={"identities": []})
            elif path.endswith("/auth-types"):
                route.fulfill(json={"allowedAuthTypes": ["NoAuth", "username_password", "basic", "key", "identity"]})
            else:
                route.fulfill(json={})
            return
        route.fulfill(status=404, body="")

    def open(self):
        self.page.goto(f"{ORIGIN}/classic-action-auth", wait_until="networkidle")
        self.page.wait_for_function("window.classicActionAuthHarnessReady && window.pluginModalStepper")
        self.page.evaluate("(shared) => { window.harnessShared = shared; }", self.shared)

    def assert_private(self):
        assert self.page_errors == []
        assert self.page.locator("#chatbox [data-private-credential]").count() == 0
        assert SYNTHETIC_SECRET not in self.page.locator("body").inner_text()
        stored = self.page.evaluate("JSON.stringify({local: {...localStorage}, session: {...sessionStorage}})")
        assert SYNTHETIC_SECRET not in stored
        assert "synthetic-operator" not in stored
        for request in self.requests:
            if not request["path"].endswith("/credentials"):
                assert SYNTHETIC_SECRET not in json.dumps(request)
                assert "synthetic-operator" not in json.dumps(request)


@pytest.fixture
def auth_ui(page):
    harness = ClassicAuthHarness(page)
    yield harness
    harness.assert_private()


def _start_card(harness):
    harness.open()
    harness.page.locator("#user-input").fill("Read the latest telemetry")
    harness.page.locator("#harness-send").click()
    card = harness.page.locator("#chat-action-auth-root")
    expect(card).to_be_visible()
    expect(card.get_by_role("heading", name="Connect Yamcs")).to_be_visible()
    expect(card.get_by_text("Private to you", exact=True)).to_be_visible()
    return card


def _fill_new_credentials(card, shared=False):
    card.get_by_label("Username", exact=True).fill("synthetic-operator")
    card.get_by_label("Password", exact=True).fill(SYNTHETIC_SECRET)
    card.get_by_label("I approve sending this identity’s credentials to the destination shown above.", exact=True).check()
    if shared:
        card.get_by_label("I understand that my message and returned data will be shared.", exact=True).check()


def test_private_card_saves_once_without_messages_storage_or_shared_broadcast(auth_ui, browser):
    auth_ui.shared = True
    observer_context = browser.new_context()
    try:
        observer = ClassicAuthHarness(observer_context.new_page())
        observer.shared = True
        observer.open()
        card = _start_card(auth_ui)
        expect(card).to_contain_text("Your message and returned data will be visible")
        expect(auth_ui.page.locator("#user-input")).to_have_value("Read the latest telemetry")
        expect(auth_ui.page.locator("#chatbox")).to_be_empty()
        _fill_new_credentials(card, shared=True)
        assert not any("/collaboration/" in request["path"] for request in auth_ui.requests)
        expect(observer.page.locator("#chat-action-auth-root")).to_be_hidden()
        expect(observer.page.locator("#chatbox")).to_be_empty()
        card.locator("form").evaluate("""form => {
            form.dispatchEvent(new Event('submit', {bubbles: true, cancelable: true}));
            form.dispatchEvent(new Event('submit', {bubbles: true, cancelable: true}));
        }""")
        expect(card).to_be_hidden()
        auth_ui.page.wait_for_function("window.executionPayloads.length === 1")
        assert len([request for request in auth_ui.requests if request["path"].endswith("/credentials")]) == 1
        assert len([request for request in auth_ui.requests if "/collaboration/" in request["path"]]) == 1
        assert auth_ui.page.evaluate("window.executionPayloads[0].action_auth_request_id") == "private-request"
        expect(auth_ui.page.locator("#user-input")).to_have_value("")
        expect(observer.page.locator("#chat-action-auth-root")).to_be_hidden()
        observer.assert_private()
    finally:
        observer_context.close()


def test_cancel_escape_and_reload_leave_draft_unsent_and_drop_private_values(auth_ui):
    card = _start_card(auth_ui)
    _fill_new_credentials(card)
    card.get_by_role("button", name="Cancel", exact=True).click()
    expect(card).to_be_hidden()
    expect(auth_ui.page.locator("#user-input")).to_have_value("Read the latest telemetry")
    auth_ui.page.locator("#harness-send").click()
    expect(card).to_be_visible()
    expect(card.get_by_label("Password", exact=True)).to_have_value("")
    _fill_new_credentials(card)
    card.get_by_label("Password", exact=True).press("Escape")
    expect(card).to_be_hidden()
    auth_ui.page.reload(wait_until="networkidle")
    expect(card).to_be_hidden()
    assert auth_ui.page.evaluate("window.executionPayloads") == []
    assert not any(request["path"].endswith("/credentials") for request in auth_ui.requests)


def test_ready_shared_credentials_still_require_notice_and_user_confirmation(auth_ui):
    auth_ui.shared = True
    auth_ui.saved = True
    card = _start_card(auth_ui)
    expect(card.get_by_text("Your account is used for this request.", exact=False)).to_be_visible()
    expect(card.locator("[data-private-credential]")).to_have_count(0)
    card.get_by_role("button", name="Continue with my account").click()
    assert auth_ui.page.evaluate("window.executionPayloads") == []
    card.get_by_label("I understand that my message and returned data will be shared.", exact=True).check()
    card.get_by_role("button", name="Continue with my account").click()
    auth_ui.page.wait_for_function("window.executionPayloads.length === 1")

def test_confirmed_rejection_requires_replacement_and_explicit_retry(auth_ui):
    auth_ui.requirements = [auth_requirement("http_basic", reason="authentication_rejected", identities=[
        {"id": "rejected-owned-identity", "name": "My gateway identity", "auth_type": "username_password"},
    ])]
    auth_ui.open()
    auth_ui.page.locator("#user-input").fill("A draft that must not be replayed")
    auth_ui.page.evaluate("""window.repairPrivateAuth({
        type: 'action_credentials_required',
        request_id: 'private-request',
        execution_started: true,
    })""")
    card = auth_ui.page.locator("#chat-action-auth-root")
    expect(card).to_contain_text("Yamcs rejected the saved credentials")
    expect(card.locator("#action-auth-identity")).to_have_value("")
    card.get_by_label("Your personal identity", exact=True).select_option("rejected-owned-identity")
    expect(card.get_by_label("Replace the selected identity’s credentials", exact=True)).to_be_checked()
    expect(card.get_by_label("Replace the selected identity’s credentials", exact=True)).to_be_disabled()
    expect(card.get_by_label("Password", exact=True)).to_be_visible()
    card.get_by_label("I approve sending this identity’s credentials to the destination shown above.", exact=True).check()
    card.get_by_role("button", name="Save connection", exact=True).click()
    assert not any(request["path"].endswith("/credentials") for request in auth_ui.requests)
    _fill_new_credentials(card)
    card.get_by_role("button", name="Save connection", exact=True).click()
    expect(card).to_contain_text("Use Retry or submit your draft")
    assert auth_ui.page.evaluate("window.executionPayloads") == []
    assert not any(request["path"].endswith("/stream") for request in auth_ui.requests)
    expect(auth_ui.page.locator("#user-input")).to_have_value("A draft that must not be replayed")
    saved = next(request["body"] for request in auth_ui.requests if request["path"].endswith("/credentials"))
    assert saved["identity_id"] == "rejected-owned-identity"
    assert saved["credentials"] == {"username": "synthetic-operator", "password": SYNTHETIC_SECRET}
    card.get_by_role("button", name="Done", exact=True).click()
    expect(card).to_be_hidden()


def test_owned_candidate_and_gateway_profile_need_destination_approval_not_inline_secrets(auth_ui):
    auth_ui.requirements = [auth_requirement("http_basic", reason="approval_required", identities=[
        {"id": "owned-identity", "name": "Existing gateway login", "auth_type": "username_password"},
    ])]
    card = _start_card(auth_ui)
    expect(card).to_contain_text("Gateway HTTP Basic (not Yamcs login)")
    expect(card.locator("#action-auth-identity")).to_have_value("")
    card.get_by_label("Your personal identity", exact=True).select_option("owned-identity")
    expect(card.get_by_label("Password", exact=True)).to_be_hidden()
    card.get_by_role("button", name="Save and continue").click()
    assert not any(request["path"].endswith("/credentials") for request in auth_ui.requests)
    card.get_by_label("I approve sending this identity’s credentials to the destination shown above.", exact=True).check()
    card.get_by_role("button", name="Save and continue").click()
    expect(card).to_be_hidden()
    save = next(request["body"] for request in auth_ui.requests if request["path"].endswith("/credentials"))
    assert save == {"requirement_id": "requirement-1", "identity_id": "owned-identity", "confirm_destination": True}


def test_failed_save_wipes_fields_and_unsupported_schema_is_visible_without_unsafe_markup(auth_ui):
    auth_ui.fail_save = True
    card = _start_card(auth_ui)
    _fill_new_credentials(card)
    card.get_by_role("button", name="Save and continue").click()
    expect(card.get_by_role("alert")).to_contain_text("The service rejected these credentials")
    expect(card.get_by_label("Password", exact=True)).to_have_value("")
    expect(card.get_by_label("Username", exact=True)).to_have_value("")
    expect(auth_ui.page.locator("#user-input")).to_have_value("Read the latest telemetry")
    card.get_by_role("button", name="Cancel", exact=True).click()
    auth_ui.requirements = [auth_requirement(action_name='<img src=x onerror="window.authXss=true">')]
    auth_ui.requirements[0]["fields"].append({"name": "model_defined", "label": "unsafe", "type": "text", "required": True})
    auth_ui.page.locator("#harness-send").click()
    expect(card.get_by_role("alert")).to_contain_text("unsupported credential fields")
    expect(card.locator("[data-private-credential]")).to_have_count(0)
    expect(auth_ui.page.locator('img[src="x"]')).to_have_count(0)
    assert auth_ui.page.evaluate("window.authXss") is None


def test_selection_change_cancels_and_disabled_workspace_has_no_dead_manual_link(auth_ui):
    card = _start_card(auth_ui)
    _fill_new_credentials(card)
    auth_ui.page.locator("#harness-agent").select_option("different-agent")
    expect(card).to_be_hidden()
    expect(auth_ui.page.locator("#user-input")).to_have_value("Read the latest telemetry")
    auth_ui.page.evaluate("delete document.getElementById('chat-action-auth-root').dataset.identitySetupUrl")
    auth_ui.page.locator("#harness-send").click()
    expect(card).to_be_visible()
    expect(card.get_by_role("link")).to_have_count(0)
    assert auth_ui.page.evaluate("window.executionPayloads") == []


def _open_editor(harness, action=None, scope="global"):
    harness.open()
    harness.page.evaluate("""async ({action, scope}) => {
        window.pluginModalStepper.setActionScope({
            scope, apiBase: scope === 'global' ? '/api/admin/workspace-identities/global' : '/api/workspace-identities/personal',
            allowCurrentUser: scope === 'global',
        });
        await window.pluginModalStepper.showModal(action);
    }""", {"action": action, "scope": scope})
    modal = harness.page.locator("#plugin-modal")
    expect(modal).to_be_visible()
    if action is None:
        modal.locator('.action-type-card[data-type="yamcs"]').click()
        modal.get_by_role("button", name="Next", exact=True).click()
        modal.locator("#plugin-display-name").fill("Mission telemetry")
        modal.get_by_role("button", name="Next", exact=True).click()
        modal.locator("#yamcs-server-url").fill("https://yamcs.example.test")
        modal.locator("#yamcs-instance").fill("simulator")
    else:
        harness.page.evaluate("window.pluginModalStepper.goToStep(3)")
    return modal


@pytest.mark.parametrize("profile,native_type,method", [
    ("yamcs_login", "username_password", "username_password"),
    ("http_basic", "basic", "http_basic"),
    ("bearer_token", "key", "bearer_token"),
    ("api_key", "key", "api_key"),
])
def test_global_editor_source_profiles_and_summary_round_trip(auth_ui, profile, native_type, method):
    modal = _open_editor(auth_ui)
    modal.locator("#yamcs-username").fill("stale-action-user")
    modal.locator("#yamcs-password").fill(SYNTHETIC_SECRET)
    modal.get_by_label("Credential source", exact=True).select_option("current_user")
    expect(modal.locator("#yamcs-password")).to_have_value("")
    expect(modal.locator("#yamcs-username-password-group")).to_be_hidden()
    expect(modal.locator("#yamcs-identity-select")).to_be_hidden()
    expect(modal.locator("#yamcs-identity-name")).to_have_value("Yamcs")
    modal.locator("#yamcs-auth-profile").select_option(profile)
    data = auth_ui.page.evaluate("window.pluginModalStepper.getFormData()")
    assert data["credential_requirement"] == {"source": "current_user", "identity_name": "Yamcs", "profile": profile}
    assert data["auth"] == {"type": native_type}
    assert data["additionalFields"]["auth_method"] == method
    assert "identity_id" not in data
    modal.locator("#plugin-modal-skip").click()
    expect(modal.locator("#summary-yamcs-auth-method")).to_contain_text("Each user's personal identity: Yamcs")
    assert SYNTHETIC_SECRET not in json.dumps(data)


def saved_action():
    return {
        "id": "global-yamcs", "name": "mission", "displayName": "Mission telemetry",
        "type": "yamcs", "endpoint": "https://yamcs.example.test", "is_global": True,
        "auth": {"type": "username_password"},
        "credential_requirement": {"id": "requirement-1", "source": "current_user", "identity_name": "Yamcs", "profile": "yamcs_login"},
        "additionalFields": {"server_url": "https://yamcs.example.test", "instance": "simulator", "processor": "realtime", "tls_verify": True, "auth_method": "username_password"},
    }


def test_saved_label_edit_preserves_id_and_test_as_me_never_mutates_global_auth(auth_ui):
    modal = _open_editor(auth_ui, saved_action())
    modal.locator("#yamcs-identity-name").fill("Mission identity")
    data = auth_ui.page.evaluate("window.pluginModalStepper.getFormData()")
    assert data["credential_requirement"]["id"] == "requirement-1"
    modal.get_by_role("button", name="Test as me", exact=True).click()
    expect(modal.locator("#yamcs-test-connection-alert")).to_contain_text("Save this global action first")
    assert not any(request["path"] == "/api/action-auth/preflight" for request in auth_ui.requests)
    modal.locator("#yamcs-identity-name").fill("Yamcs")
    modal.get_by_role("button", name="Test as me", exact=True).click()
    card = auth_ui.page.locator("#yamcs-private-auth-root")
    expect(card).to_be_visible()
    assert card.locator("form").evaluate("form => form.closest('#plugin-modal-form') === null")
    _fill_new_credentials(card)
    card.get_by_role("button", name="Save and continue").click()
    expect(modal.locator("#yamcs-test-connection-alert")).to_contain_text("Global credentials were not changed")
    tested = next(request["body"] for request in auth_ui.requests if request["path"] == "/api/plugins/test-yamcs-connection")
    assert tested == {"action_ref": "action:v1:global:Z2xvYmFs:Z2xvYmFsLXlhbWNz"}
    assert not any(request["method"] in ("POST", "PUT", "PATCH") and request["path"] == "/api/admin/plugins" for request in auth_ui.requests)


@pytest.mark.parametrize("scope", ["personal", "group"])
def test_non_admin_scopes_keep_legacy_credentials_and_hide_current_user_source(auth_ui, scope):
    action = saved_action()
    del action["credential_requirement"]
    action["auth"] = {"type": "username_password", "identity": "legacy-user", "key": "synthetic-legacy-password"}
    modal = _open_editor(auth_ui, action, scope)
    expect(modal.locator("#yamcs-credential-source-group")).to_be_hidden()
    expect(modal.locator("#yamcs-username-password-group")).to_be_visible()
    data = auth_ui.page.evaluate("window.pluginModalStepper.getFormData()")
    assert "credential_requirement" not in data
    assert data["auth"] == action["auth"]


def test_action_details_explain_actor_binding_and_render_identity_label_as_text(auth_ui):
    auth_ui.open()
    action = saved_action()
    action["credential_requirement"]["profile"] = "http_basic"
    action["credential_requirement"]["identity_name"] = '<img src=x onerror="window.authXss=true">'
    auth_ui.page.evaluate("action => window.openActionDetails(action)", action)
    details = auth_ui.page.locator("#item-view-modal")
    expect(details).to_be_visible()
    expect(details).to_contain_text("submitting person’s private identity")
    expect(details).to_contain_text("Gateway HTTP Basic (not Yamcs login)")
    expect(details).to_contain_text(action["credential_requirement"]["identity_name"])
    expect(details.locator('img[src="x"]')).to_have_count(0)
    assert auth_ui.page.evaluate("window.authXss") is None


def test_private_card_remains_accessible_on_mobile(auth_ui):
    auth_ui.page.set_viewport_size({"width": 390, "height": 720})
    card = _start_card(auth_ui)
    expect(card.get_by_label("Username", exact=True)).to_be_focused()
    _fill_new_credentials(card)
    expect(card.get_by_role("button", name="Cancel", exact=True)).to_be_visible()
    assert card.evaluate("element => element.getBoundingClientRect().right <= innerWidth")
    card.get_by_role("button", name="Save and continue", exact=True).click()
    expect(card).to_be_hidden()
    auth_ui.page.wait_for_function("window.executionPayloads.length === 1")
