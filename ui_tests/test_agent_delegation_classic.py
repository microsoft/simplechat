# test_agent_delegation_classic.py
"""
UI test for the classic Call agent action modal and Actions step attachment flow.
Version: 0.261.093
Implemented in: 0.261.093

This test runs the REAL `_plugin_modal.html` / `_agent_modal.html` partials and
the REAL `plugin_modal_stepper.js` / `agent_modal_stepper.js` modules in a
genuine Chromium browser, served from a deterministic local static HTTP server
(see `fixtures/agent_delegation_classic/harness.py`). Only network calls to
API/provider endpoints are mocked with Playwright routes; no CDN, no Azure/
Cosmos/auth dependency, and no live app server are required. These tests never
skip for missing environment/credentials.

Covered scenarios:
- Selecting the Call agent type card renders the dedicated target picker with
  no endpoint, credential, identity, or test-connection controls, and hides
  every other action type's configuration section.
- The search box narrows the fetched target catalogue client-side.
- Selecting a target, saving, and reopening the action for edit round-trips
  the exact manifest shape: `type: "agent"`, `endpoint: "internal://agent"`,
  `auth: {"type": "user"}`, and `additionalFields` containing only
  `target_agent` (`id`/`scope_type`/`scope_id`).
- A previously selected target that the catalogue no longer contains renders
  an "unavailable" state without being silently dropped on save.
- Target catalogue loading and fetch-failure states render visibly.
- The target catalogue request's `scope` query parameter follows the action's
  configured scope (personal vs. group).
- The agent modal's Actions step resolves a friendly target label for a Call
  agent action, blocks attaching an action that would delegate back to the
  agent currently being edited (including a group-scoped edit correctly
  distinguishing "same agent, different group"), and renders attacker-supplied
  action names/descriptions as inert text, never as executed markup.
"""

import json
import sys
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(FIXTURES_DIR))

playwright_sync = pytest.importorskip("playwright.sync_api", reason="Install Playwright to run this UI test.")

from agent_delegation_classic.harness import (  # noqa: E402
    AGENT_ACTION_TYPES_RESPONSE,
    SAMPLE_AGENT_TARGETS,
    build_agent_modal_page,
    build_plugin_modal_page,
    read_partial,
    register_static_passthrough,
    start_static_test_server,
)

MALICIOUS_NAME = "<img src=x onerror=window.__xssFired=true>"
MALICIOUS_DESCRIPTION = "\"><script>window.__xssFired=true</script>"


@pytest.mark.parametrize("auth_url,visible", [
    ("/api/agents/foundry-auth?id=remote&scope_type=personal&scope_id=current-user", True),
    ("https://login.microsoftonline.com/tenant/oauth2/v2.0/authorize", True),
    ("javascript:window.__authXss=true", False),
    ("data:text/html,<script>window.__authXss=true</script>", False),
    ("//untrusted.example/authorize", False),
])
def test_streamed_authentication_banner_supports_safe_local_handoffs(plugin_modal_page, auth_url, visible):
    page = plugin_modal_page
    root = Path(__file__).resolve().parents[1]
    source = (root / "application" / "single_app" / "static" / "js" / "chat" / "chat-streaming.js").read_text(encoding="utf-8")
    helpers = source[source.index("function normalizeStreamHttpUrl("):source.index("function reportClientStreamEvent(")]
    page.set_content('<main id="content"></main>')
    page.add_script_tag(content=helpers)
    page.evaluate(
        "(url) => appendStreamErrorBanner(document.getElementById('content'), 'Sign in required.', "
        "{auth_required: true, auth_url: url})",
        auth_url,
    )
    link = page.get_by_role("link", name="Sign in or grant Foundry access")
    assert link.count() == int(visible)
    if visible:
        assert link.get_attribute("rel") == "noopener noreferrer"
        assert link.get_attribute("target") == "_blank"
        assert page.evaluate("document.querySelector('#content a').href.startsWith('http')")
        if auth_url.startswith("/"):
            assert page.evaluate("document.querySelector('#content a').origin === location.origin")
    assert page.evaluate("window.__authXss !== true")


def _json_route(route, payload, status=200):
    route.fulfill(status=status, content_type="application/json", body=json.dumps(payload))


def _action_types_route(route):
    _json_route(route, AGENT_ACTION_TYPES_RESPONSE)


def _agent_targets_route(targets=None, status=200, error="Unable to load available agents."):
    def handler(route):
        if status != 200:
            _json_route(route, {"error": error}, status=status)
            return
        _json_route(route, {
            "targets": SAMPLE_AGENT_TARGETS if targets is None else targets,
            "can_manage": True,
            "scope_type": "personal",
            "scope_id": "current-user",
        })
    return handler


def _valid_validation_route(route):
    _json_route(route, {"valid": True, "errors": [], "warnings": []})


@pytest.fixture
def plugin_modal_page():
    """Open a fresh browser page hosting the real action modal + stepper."""
    with playwright_sync.sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        try:
            with start_static_test_server() as server_base_url:
                register_static_passthrough(page)
                response = page.goto(server_base_url, wait_until="domcontentloaded")
                assert response is not None and response.ok
                yield page
        finally:
            browser.close()


@pytest.fixture
def agent_modal_page():
    """Open a fresh browser page hosting the real agent modal + stepper."""
    with playwright_sync.sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        try:
            with start_static_test_server() as server_base_url:
                register_static_passthrough(page)
                response = page.goto(server_base_url, wait_until="domcontentloaded")
                assert response is not None and response.ok
                yield page
        finally:
            browser.close()


def _load_plugin_modal_page(page, scope="personal"):
    """Load the real modal partial + stepper module exactly once for a test.

    ES module side effects (including the stepper's own
    `bindEvents()`/auto-bootstrap) only run on the first evaluation of a given
    module URL in a browsing context; calling `set_content()` again would
    leave any later `showModal()` bound to elements from a document that no
    longer exists. Reopen the modal within a test via `_show_plugin_modal`
    instead of loading the page twice.
    """
    partial_html = read_partial("_plugin_modal.html")
    page.set_content(build_plugin_modal_page(partial_html))
    page.wait_for_function("() => window.__pluginModalHarnessReady === true")
    api_base = {
        "personal": "/api/workspace-identities/personal",
        "group": "/api/workspace-identities/group",
        "global": "/api/admin/workspace-identities/global",
    }[scope]
    page.evaluate(
        "(cfg) => window.pluginModalStepper.setActionScope(cfg)",
        {"scope": scope, "apiBase": api_base},
    )


def _show_plugin_modal(page, plugin=None):
    """Open (or reopen) the already-loaded real modal for the given plugin."""
    page.evaluate("(plugin) => window.pluginModalStepper.showModal(plugin)", plugin)
    page.wait_for_function("() => window.pluginModalStepper.currentStep >= 1")


def _open_plugin_modal(page, plugin=None, scope="personal"):
    """Convenience wrapper for tests that only open the modal once."""
    _load_plugin_modal_page(page, scope=scope)
    _show_plugin_modal(page, plugin=plugin)


def _wire_save_handler(page):
    """Attach a minimal save handler exercising the real getFormData()/showError().

    Mirrors workspace_plugins.js's own `setupSaveHandler` idiom of assigning
    `saveBtn.onclick = ...` (an idempotent property assignment, safe to call
    again if a test reopens the modal) rather than `addEventListener`, which
    would stack a second handler and double-submit on a second call.
    """
    page.evaluate(
        """
        () => {
            const saveBtn = document.getElementById('save-plugin-btn');
            saveBtn.onclick = async (event) => {
                event.preventDefault();
                try {
                    const formData = window.pluginModalStepper.getFormData();
                    const validateResponse = await fetch('/api/plugins/validate', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(formData)
                    });
                    const validation = await validateResponse.json();
                    if (validation && validation.valid === false) {
                        window.pluginModalStepper.showError((validation.errors || []).join('\\n') || 'Validation error.');
                        return;
                    }
                    const saveResponse = await fetch('/api/user/plugins', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify([formData])
                    });
                    if (!saveResponse.ok) {
                        const body = await saveResponse.json().catch(() => ({}));
                        throw new Error(body.error || 'Save failed');
                    }
                    window.__savedManifest = formData;
                    window.__pluginModalSaved = true;
                } catch (error) {
                    window.pluginModalStepper.showError(error.message || String(error));
                }
            };
        }
        """
    )


@pytest.mark.ui
def test_plugin_modal_create_agent_action_full_manifest(plugin_modal_page):
    """Create flow: type card, config section, search, select, summary, and exact saved manifest."""
    page = plugin_modal_page
    expect = playwright_sync.expect

    saved_payloads = []
    page.route("**/api/user/plugins/types", _action_types_route)
    page.route("**/api/plugins/agent-targets*", _agent_targets_route())
    page.route("**/api/plugins/validate", _valid_validation_route)
    page.route(
        "**/api/user/plugins",
        lambda route: (
            saved_payloads.append(json.loads(route.request.post_data or "[]"))
            or route.fulfill(status=200, content_type="application/json", body='{"success": true}')
        ) if route.request.method == "POST" else route.fulfill(status=200, content_type="application/json", body="[]"),
    )

    _open_plugin_modal(page)
    _wire_save_handler(page)

    modal = page.locator("#plugin-modal")
    expect(modal).to_be_visible()

    agent_card = page.locator('.action-type-card[data-type="agent"]')
    expect(agent_card).to_have_count(1)
    agent_card.click()

    page.locator("#plugin-modal-next").click()
    page.locator("#plugin-display-name").fill("Delegate To Writer")
    page.locator("#plugin-modal-next").click()

    agent_section = page.locator("#agent-config-section")
    expect(agent_section).to_be_visible()
    expect(page.locator("#generic-config-section")).to_be_hidden()
    expect(page.locator("#openapi-config-section")).to_be_hidden()
    expect(page.locator("#sql-config-section")).to_be_hidden()
    # No endpoint, credential, identity, or test-connection controls for this type.
    expect(agent_section.locator("input[type='password']")).to_have_count(0)
    expect(agent_section.locator("input[type='text'][id*='endpoint']")).to_have_count(0)
    expect(agent_section.locator("[id*='identity']")).to_have_count(0)
    expect(agent_section.locator("[id*='test-connection']")).to_have_count(0)

    target_list = page.locator("#agent-target-list")
    expect(target_list).to_be_visible()
    expect(target_list).to_contain_text("Writer Agent")
    expect(target_list).to_contain_text("Researcher Agent")

    page.locator("#agent-target-search").fill("Researcher")
    expect(target_list).to_contain_text("Researcher Agent")
    expect(target_list).not_to_contain_text("Writer Agent")
    page.locator("#agent-target-search").fill("")

    target_list.get_by_text("Writer Agent").click()

    summary = page.locator("#agent-target-selected-summary")
    expect(summary).to_be_visible()
    expect(summary).to_contain_text("Writer Agent")
    expect(summary).to_contain_text("Local (Semantic Kernel)")

    page.locator("#plugin-modal-skip").click()

    expect(page.locator("#summary-agent-section")).to_be_visible()
    expect(page.locator("#summary-agent-target-name")).to_have_text("Writer Agent")
    expect(page.locator("#summary-plugin-database-type")).to_have_text("Call agent action")
    expect(page.locator("#summary-plugin-endpoint-row")).to_be_hidden()

    page.locator("#save-plugin-btn").click()
    page.wait_for_function("() => window.__pluginModalSaved === true")

    assert len(saved_payloads) == 1
    saved_manifest = saved_payloads[0][0]
    assert saved_manifest["type"] == "agent"
    assert saved_manifest["endpoint"] == "internal://agent"
    assert saved_manifest["auth"] == {"type": "user"}
    assert set(saved_manifest["additionalFields"].keys()) == {"target_agent"}
    assert saved_manifest["additionalFields"]["target_agent"] == {
        "id": "agent-writer",
        "scope_type": "personal",
        "scope_id": "current-user",
    }


@pytest.mark.ui
def test_plugin_modal_reopen_edit_preselects_target_and_flags_unavailable(plugin_modal_page):
    """Reopening an existing action preselects its target; a missing target stays unavailable but preserved."""
    page = plugin_modal_page
    expect = playwright_sync.expect

    existing_plugin = {
        "id": "call-writer-action",
        "name": "call_writer",
        "displayName": "Call Writer",
        "type": "agent",
        "description": "Delegate drafting to the writer agent.",
        "endpoint": "internal://agent",
        "auth": {"type": "user"},
        "additionalFields": {
            "target_agent": {
                "id": "agent-writer",
                "scope_type": "personal",
                "scope_id": "current-user",
            }
        },
    }

    page.route("**/api/user/plugins/types", _action_types_route)
    page.route("**/api/plugins/agent-targets*", _agent_targets_route())
    page.route("**/api/plugins/validate", _valid_validation_route)

    _load_plugin_modal_page(page)
    _show_plugin_modal(page, plugin=existing_plugin)

    # Editing skips straight to step 2, matching populateFormFromPlugin()/showModal().
    page.wait_for_function("() => window.pluginModalStepper.currentStep === 2")
    page.locator("#plugin-modal-next").click()

    expect(page.locator("#agent-config-section")).to_be_visible()
    summary = page.locator("#agent-target-selected-summary")
    expect(summary).to_be_visible()
    expect(summary).to_contain_text("Writer Agent")
    expect(page.locator("#agent-target-unavailable")).to_be_hidden()

    # Now reopen with a target the catalogue no longer contains, reusing the same
    # loaded document/instance (a real user reopens the same modal, not a fresh page).
    deleted_plugin = dict(existing_plugin)
    deleted_plugin["additionalFields"] = {
        "target_agent": {"id": "agent-deleted", "scope_type": "personal", "scope_id": "current-user"}
    }

    saved_payloads = []
    page.route(
        "**/api/user/plugins",
        lambda route: (
            saved_payloads.append(json.loads(route.request.post_data or "[]"))
            or route.fulfill(status=200, content_type="application/json", body='{"success": true}')
        ) if route.request.method == "POST" else route.fulfill(status=200, content_type="application/json", body="[]"),
    )

    _wire_save_handler(page)
    _show_plugin_modal(page, plugin=deleted_plugin)
    page.wait_for_function("() => window.pluginModalStepper.currentStep === 2")
    page.locator("#plugin-modal-next").click()

    unavailable = page.locator("#agent-target-unavailable")
    expect(unavailable).to_be_visible()
    expect(unavailable).to_contain_text("agent-deleted")
    expect(page.locator("#agent-target-selected-summary")).to_be_hidden()

    page.locator("#plugin-modal-skip").click()
    page.locator("#save-plugin-btn").click()
    page.wait_for_function("() => window.__pluginModalSaved === true")

    assert len(saved_payloads) == 1
    saved_manifest = saved_payloads[0][0]
    # The unresolved reference is preserved rather than silently cleared or replaced.
    assert saved_manifest["additionalFields"]["target_agent"]["id"] == "agent-deleted"


@pytest.mark.ui
def test_plugin_modal_target_loading_and_error_states(plugin_modal_page):
    """The picker shows a loading indicator, then a visible error state on a failed fetch."""
    page = plugin_modal_page
    expect = playwright_sync.expect

    def slow_then_fail_route(route):
        route.fulfill(status=503, content_type="application/json", body='{"error": "Unable to load available agents."}')

    page.route("**/api/user/plugins/types", _action_types_route)
    page.route("**/api/plugins/agent-targets*", slow_then_fail_route)
    page.route("**/api/plugins/validate", _valid_validation_route)

    _open_plugin_modal(page)

    agent_card = page.locator('.action-type-card[data-type="agent"]')
    expect(agent_card).to_have_count(1)
    agent_card.click()
    page.locator("#plugin-modal-next").click()
    page.locator("#plugin-display-name").fill("Broken Catalogue")
    page.locator("#plugin-modal-next").click()

    error_alert = page.locator("#agent-target-error")
    expect(error_alert).to_be_visible()
    expect(error_alert).to_contain_text("Unable to load available agents.")
    expect(page.locator("#agent-target-list")).to_be_hidden()
    expect(page.locator("#agent-target-loading")).to_be_hidden()

    # Without a selectable target, continuing past step 3 must be blocked.
    page.locator("#plugin-modal-next").click()
    error_div = page.locator("#plugin-modal-error")
    expect(error_div).to_be_visible()
    expect(error_div).to_contain_text("Select an agent to call")
    expect(page.locator("#plugin-step-4")).to_be_hidden()


@pytest.mark.ui
def test_plugin_modal_group_scope_requests_group_targets(plugin_modal_page):
    """The target catalogue request's scope query parameter follows the configured action scope."""
    page = plugin_modal_page
    expect = playwright_sync.expect

    captured_urls = []

    def capturing_route(route):
        captured_urls.append(route.request.url)
        _agent_targets_route()(route)

    page.route("**/api/group/plugins/types", _action_types_route)
    page.route("**/api/plugins/agent-targets*", capturing_route)
    page.route("**/api/plugins/validate", _valid_validation_route)

    _open_plugin_modal(page, scope="group")

    agent_card = page.locator('.action-type-card[data-type="agent"]')
    expect(agent_card).to_have_count(1)
    agent_card.click()
    page.locator("#plugin-modal-next").click()
    page.locator("#plugin-display-name").fill("Group Delegate")
    page.locator("#plugin-modal-next").click()

    expect(page.locator("#agent-target-list")).to_be_visible()
    assert captured_urls, "Expected the agent-targets endpoint to be called."
    assert any("scope=group" in url for url in captured_urls), captured_urls


def _open_agent_modal(page, agent=None, is_admin=False, workspace_scope="personal"):
    partial_html = read_partial("_agent_modal.html")
    page.set_content(build_agent_modal_page(partial_html))
    page.wait_for_function("() => window.__agentModalHarnessReady === true")
    page.evaluate(
        "([isAdmin, scope]) => { window.agentModalStepper = new window.AgentModalStepper(isAdmin, { workspaceScope: scope }); }",
        [is_admin, workspace_scope],
    )
    page.evaluate("(agent) => window.agentModalStepper.showModal(agent)", agent)
    # showModal() shows the real Bootstrap modal, then polls every 50ms (setTimeout)
    # for its fade-in "show" class before running its own step-1 initialization
    # (showStep(1)/updateNavigationButtons()). A real user only reaches the Actions
    # step after that settles; calling goToStep() immediately after the class
    # appears can still race one more 50ms poll tick and get clobbered. Waiting a
    # bit longer than one poll interval avoids that race deterministically.
    page.wait_for_function("() => document.getElementById('agentModal').classList.contains('show')")
    page.wait_for_timeout(200)
    page.evaluate(
        "() => window.agentModalStepper.goToStep(window.agentModalStepper.getStepNumber('actions'))"
    )
    # loadAvailableActions() is asynchronous (fetch + render); wait for the real
    # cards to be in the DOM rather than relying solely on assertion retry timing.
    page.wait_for_function(
        "() => document.getElementById('agent-actions-container').children.length > 0"
    )


@pytest.mark.ui
def test_agent_modal_actions_step_label_self_attachment_and_malicious_names(agent_modal_page):
    """Target label resolution, self-attachment blocking, and inert malicious action names."""
    page = agent_modal_page
    expect = playwright_sync.expect

    editing_agent = {"id": "agent-under-edit", "name": "under_edit", "display_name": "Agent Under Edit", "agent_type": "local"}

    actions_payload = [
        {
            "id": "call-other-agent",
            "name": "call_other_agent",
            "display_name": "Call Other Agent",
            "type": "agent",
            "description": "Delegates to a different agent.",
            "is_global": False,
            "additionalFields": {
                "target_agent": {"id": "agent-writer", "scope_type": "personal", "scope_id": "current-user"}
            },
        },
        {
            "id": "call-self",
            "name": "call_self",
            "display_name": "Call Self",
            "type": "agent",
            "description": "Would delegate back to the agent being edited.",
            "is_global": False,
            "additionalFields": {
                "target_agent": {"id": "agent-under-edit", "scope_type": "personal", "scope_id": "current-user"}
            },
        },
        {
            "id": "call-malicious",
            "name": "call_malicious",
            "display_name": MALICIOUS_NAME,
            "type": "agent",
            "description": MALICIOUS_DESCRIPTION,
            "is_global": False,
            "additionalFields": {
                "target_agent": {"id": "agent-researcher", "scope_type": "personal", "scope_id": "current-user"}
            },
        },
    ]

    page.route(
        "**/api/user/plugins",
        lambda route: _json_route(route, actions_payload),
    )
    page.route("**/api/plugins/agent-targets*", _agent_targets_route())

    page.evaluate("() => { window.__xssFired = false; }")
    _open_agent_modal(page, agent=editing_agent, workspace_scope="personal")

    other_card = page.locator('.action-card[data-action-id="call-other-agent"]')
    self_card = page.locator('.action-card[data-action-id="call-self"]')
    malicious_card = page.locator('.action-card[data-action-id="call-malicious"]')
    expect(other_card).to_be_visible()
    expect(self_card).to_be_visible()
    expect(malicious_card).to_be_visible()

    # The resolved label appears once the target catalogue call completes.
    expect(other_card.locator(".agent-delegation-target-label")).to_have_text("Target: Writer Agent")

    expect(self_card).to_have_attribute("aria-disabled", "true")
    expect(self_card).to_contain_text("cannot attach")
    self_card.click()
    expect(page.locator('.action-card.border-primary[data-action-id="call-self"]')).to_have_count(0)

    # Malicious display name/description must render as literal text, never execute.
    expect(malicious_card.locator(".card-title span").first).to_have_text(MALICIOUS_NAME)
    assert page.evaluate("() => window.__xssFired") is False
    assert malicious_card.locator("img").count() == 0
    assert malicious_card.locator("script").count() == 0

    other_card.click()
    expect(page.locator('.action-card.border-primary[data-action-id="call-other-agent"]')).to_have_count(1)


@pytest.mark.ui
def test_agent_modal_group_scope_self_attachment_considers_group_id(agent_modal_page):
    """A group-scoped edit only blocks self-attachment for the same agent in the same group."""
    page = agent_modal_page
    expect = playwright_sync.expect

    editing_agent = {
        "id": "agent-under-edit",
        "name": "under_edit",
        "display_name": "Agent Under Edit",
        "agent_type": "local",
        "group_id": "group-alpha",
    }

    actions_payload = [
        {
            "id": "call-self-same-group",
            "name": "call_self_same_group",
            "display_name": "Call Self Same Group",
            "type": "agent",
            "description": "Same agent id, same group: must be blocked.",
            "is_global": False,
            "additionalFields": {
                "target_agent": {"id": "agent-under-edit", "scope_type": "group", "scope_id": "group-alpha"}
            },
        },
        {
            "id": "call-same-id-other-group",
            "name": "call_same_id_other_group",
            "display_name": "Call Same ID Other Group",
            "type": "agent",
            "description": "Same agent id, different group: must not be blocked.",
            "is_global": False,
            "additionalFields": {
                "target_agent": {"id": "agent-under-edit", "scope_type": "group", "scope_id": "group-beta"}
            },
        },
    ]

    page.route(
        "**/api/group/plugins",
        lambda route: _json_route(route, {"actions": actions_payload}),
    )
    page.route("**/api/user/plugins", lambda route: _json_route(route, actions_payload))
    page.route("**/api/plugins/agent-targets*", _agent_targets_route())

    _open_agent_modal(page, agent=editing_agent, workspace_scope="group")

    same_group_card = page.locator('.action-card[data-action-id="call-self-same-group"]')
    other_group_card = page.locator('.action-card[data-action-id="call-same-id-other-group"]')
    expect(same_group_card).to_be_visible()
    expect(other_group_card).to_be_visible()

    expect(same_group_card).to_have_attribute("aria-disabled", "true")
    expect(other_group_card).not_to_have_attribute("aria-disabled", "true")

    other_group_card.click()
    expect(page.locator('.action-card.border-primary[data-action-id="call-same-id-other-group"]')).to_have_count(1)
