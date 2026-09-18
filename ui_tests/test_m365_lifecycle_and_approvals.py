# test_m365_lifecycle_and_approvals.py
"""
Azure Playwright-ready UI tests for typed actions, Profile, and saved approvals.
Version: 0.261.029
Implemented in: 0.261.029

Uses the real local templates, Bootstrap, and browser modules with deterministic
same-origin API fixtures. Set AZURE_PLAYWRIGHT_WS_ENDPOINT, AZURE_SUBSCRIPTION_ID,
AZURE_PLAYWRIGHT_RESOURCE_GROUP, AZURE_PLAYWRIGHT_WORKSPACE, and
AZURE_PLAYWRIGHT_TOKEN_SCOPE to connect to an existing Azure Playwright workspace
using DefaultAzureCredential and azure-mgmt-playwright. Without that environment,
the identical workflows run in local Chromium; local runs do not qualify Azure
tenant authentication or live Microsoft 365 access.
"""

import copy
import json
import mimetypes
import os
from pathlib import Path
from urllib.parse import unquote, urlsplit

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
        self.connect_requests = []
        self.fail_decision = False
        self.waiting_requests = []
        self.resume_requests = []
        self.resume_response = {"resume_scheduled": True, "execution_status": "queued"}
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
        body = json.loads(request.post_data or "{}")
        if request.method in ("POST", "PATCH", "PUT") and path.startswith("/api/m365/"):
            if request.headers.get("x-m365-csrf-token") != CSRF_TOKEN:
                self.respond(route, {"message": "Anti-forgery token is required."}, 403)
                return
        if path == "/api/m365/preferences":
            if request.method == "GET":
                self.respond(route, {"preferences": self.preferences, "csrf_token": CSRF_TOKEN})
            else:
                if request.method != "PATCH" or set(body) - {"sources", "extended_analysis"}:
                    self.respond(route, {"message": "Invalid preference fields."}, 400)
                    return
                self.preference_writes.append(body)
                self.preferences.update(copy.deepcopy(body))
                self.respond(route, {"success": True, "preferences": self.preferences})
        elif path == "/api/m365/connections":
            self.respond(route, {"success": True, "connection": self.connection, "csrf_token": CSRF_TOKEN})
        elif path == "/api/m365/connections/connect":
            self.connect_requests.append(body)
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
            self.respond(route, {"items": self.waiting_requests, "continuation_token": None, "csrf_token": CSRF_TOKEN})
        elif path.startswith("/api/m365/requests/") and path.endswith("/resume"):
            self.resume_requests.append(path)
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
        "/workflow-controls": (
            '<div id="workflow-activity-pending-action-controls"></div>'
            '<button id="workflow-activity-cancel-btn" class="d-none"><span>Cancel run</span></button>'
        ),
    }

    def route_request(route):
        parsed = urlsplit(route.request.url)
        path = parsed.path
        if parsed.netloc != "simplechat.test":
            route.abort()
            api.errors.append("Unexpected nonlocal browser request")
            return
        if path.startswith("/api/"):
            api.handle_api(route, path)
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
        "id": "request", "conversation_id": "original-conversation", "status": "awaiting_sign_in",
    }]
    page.goto(f"{ORIGIN}/requests-m365")
    page.get_by_role("button", name="Resume request").click()
    expect(page.locator("#m365-waiting-requests")).to_contain_text("result will appear in the original conversation")
    assert api.resume_requests == ["/api/m365/requests/request/resume"]
    assert not api.errors


@pytest.mark.ui
def test_waiting_request_shows_sign_in_guidance_when_no_consent_link_is_available(ui):
    page, api = ui
    api.waiting_requests = [{
        "id": "request", "conversation_id": "conversation", "status": "awaiting_sign_in",
    }]
    api.resume_response = {"auth_required": True, "message": "Sign in again to restore your session."}
    page.goto(f"{ORIGIN}/requests-m365")
    page.get_by_role("button", name="Resume request").click()
    expect(page.locator("#m365-waiting-requests")).to_contain_text("Sign in again to restore your session.")
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
def test_profile_write_scopes_are_explicit_and_source_bounded(ui):
    page, api = ui
    page.goto(f"{ORIGIN}/profile")
    calendar = page.locator('[data-m365-extra-scope="Calendars.ReadWrite"]')
    mail = page.locator('[data-m365-extra-scope="Mail.Send"]')
    expect(mail).to_be_disabled()
    page.locator("#m365-connect-email").check()
    expect(mail).to_be_enabled()
    expect(calendar).to_be_disabled()
    page.locator('[data-m365-extra-scope="Mail.ReadWrite"]').check()
    mail.check()
    page.locator("#m365-connect-btn").click()
    expect(page.locator("#m365-connection-status")).to_contain_text("Key Vault")
    assert api.connect_requests == [{"sources": ["email"], "scopes": ["Mail.ReadWrite", "Mail.Send"]}]
    page.locator("#m365-connect-email").uncheck()
    expect(mail).not_to_be_checked()
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
