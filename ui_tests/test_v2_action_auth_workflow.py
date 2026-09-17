# test_v2_action_auth_workflow.py
"""
Real React SPA workflows for native, private per-user Yamcs authentication.
Version: 0.261.107
Implemented in: 0.261.107

Uses the existing Azure Playwright connection fixture and local fallback.
Only HTTP responses are synthetic; the production UI, CSS, stores, and controller
are bundled unchanged. No live accounts, model calls, or real credentials are used.
"""

import copy
import json
import re
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from ui_tests.fixtures.v2_action_auth import (
    ACTION_REF,
    ActionAuthFixture,
    GLOBAL_ACTION_ID,
    ORIGIN,
    REQUIREMENT_ID,
    SHARED_ID,
    action_auth_build,
    action_auth_ui,
    connect_options,
)


pytestmark = pytest.mark.ui
USERNAME = "synthetic-private-yamcs-user"
PASSWORD = "synthetic-private-yamcs-password"
TOKEN = "synthetic-private-yamcs-token"


def open_admin(ui):
    ui.open("/admin")
    ui.page.get_by_role("searchbox", name="Search settings").fill("Yamcs")
    expect(ui.page.get_by_test_id("admin-yamcs-actions")).to_be_visible()


def credential_fields(ui, *, username=USERNAME, password=PASSWORD):
    expect(ui.card.get_by_role("textbox", name="Username", exact=True)).to_be_visible()
    ui.card.get_by_role("textbox", name="Username", exact=True).fill(username)
    password_input = ui.card.get_by_label(re.compile(r"^Password\*?$"))
    expect(password_input).to_have_attribute("type", "password")
    password_input.fill(password)
    ui.card.get_by_role("checkbox", name=re.compile("^I approve sending")).check()


def stream_calls(ui):
    return [entry for entry in ui.requests if entry.method == "POST" and entry.path.endswith("/stream")]


def test_native_global_yamcs_create_edit_enable_roundtrip(action_auth_ui):
    ui = action_auth_ui
    open_admin(ui)
    ui.page.get_by_role("button", name="Add Yamcs action", exact=True).click()
    form = ui.page.get_by_role("form", name="Create global Yamcs action")
    form.get_by_role("textbox", name="Action name", exact=True).fill("Operations telemetry")
    form.get_by_label("Credential source", exact=True).select_option("current_user")
    form.get_by_label("Authentication profile", exact=True).select_option("http_basic")
    form.get_by_role("textbox", name="Personal identity name", exact=True).fill("Operations Yamcs")
    form.get_by_role("textbox", name="Yamcs server URL", exact=True).fill("https://gateway.example.test/yamcs")
    form.get_by_role("textbox", name="Yamcs instance", exact=True).fill("operations")
    expect(form.get_by_label(re.compile(r"^Password\*?$"))).to_have_count(0)
    form.get_by_role("button", name="Review action", exact=True).click()
    expect(form.get_by_role("heading", name="Review global Yamcs action")).to_be_visible()
    form.get_by_role("button", name="Save global Yamcs action", exact=True).click()
    row = ui.page.get_by_test_id("admin-yamcs-action-row").filter(has=ui.page.get_by_role("heading", name="Operations telemetry", exact=True))
    expect(row).to_be_visible()
    writes = [entry for entry in ui.calls("/api/admin/plugins") if entry.method == "POST"]
    assert len(writes) == 1
    created = writes[0].body
    assert created["auth"] == {"type": "basic"}
    assert created["credential_requirement"] == {
        "source": "current_user", "identity_name": "Operations Yamcs", "profile": "http_basic",
    }
    assert created["additionalFields"]["auth_method"] == "http_basic"
    assert not ui.calls("/api/v2/admin/settings")[1:], "Action resources must not use the settings save bar."

    saved_id = ui.global_actions[-1]["credential_requirement"]["id"]
    row.get_by_role("button", name="Edit Yamcs action Operations telemetry").click()
    ui.page.get_by_role("textbox", name="Personal identity name", exact=True).fill("Renamed identity label")
    ui.page.get_by_role("button", name="Review action", exact=True).click()
    ui.page.get_by_role("button", name="Save global Yamcs action", exact=True).click()
    expect(row).to_be_visible()
    assert ui.global_actions[-1]["credential_requirement"]["id"] == saved_id
    row.get_by_role("button", name="Disable Operations telemetry").click()
    expect(row.get_by_text("Disabled", exact=False)).to_be_visible()
    expect(row.get_by_role("button", name="Test as me", exact=True)).to_be_disabled()
    row.get_by_role("button", name="Enable Operations telemetry").click()
    expect(row.get_by_role("button", name="Test as me", exact=True)).to_be_enabled()


def test_global_source_change_clears_legacy_credentials_but_preserves_hidden_configuration(action_auth_ui):
    ui = action_auth_ui
    legacy = ui.global_actions[0]
    legacy.pop("credential_requirement")
    legacy["auth"] = {"type": "basic", "identity": "legacy-operator", "key": "Stored_In_KeyVault"}
    legacy["additionalFields"]["auth_method"] = "http_basic"
    hidden = copy.deepcopy(legacy["additionalFields"]["hidden_setting"])
    open_admin(ui)
    ui.page.get_by_role("button", name="Edit Yamcs action Published Yamcs").click()
    password = ui.page.get_by_label(re.compile(r"^Password\*?$"))
    expect(password).to_have_value("")
    expect(password).to_have_attribute("placeholder", re.compile("Stored securely"))
    ui.page.get_by_label("Description", exact=True).fill("Only the description changed.")
    ui.page.get_by_role("button", name="Review action", exact=True).click()
    ui.page.get_by_role("button", name="Save global Yamcs action", exact=True).click()
    expect(ui.page.get_by_role("button", name="Edit Yamcs action Published Yamcs")).to_be_visible()
    assert ui.global_actions[0]["auth"] == {"type": "basic", "identity": "legacy-operator", "key": "Stored_In_KeyVault"}
    assert ui.global_actions[0]["additionalFields"]["hidden_setting"] == hidden
    ui.page.get_by_role("button", name="Edit Yamcs action Published Yamcs").click()
    ui.page.get_by_label("Credential source", exact=True).select_option("current_user")
    ui.page.get_by_role("button", name="Review action", exact=True).click()
    ui.page.get_by_role("button", name="Save global Yamcs action", exact=True).click()
    expect(ui.page.get_by_role("button", name="Edit Yamcs action Published Yamcs")).to_be_visible()
    assert ui.global_actions[0]["auth"] == {"type": "username_password"}
    assert "legacy-operator" not in json.dumps(ui.global_actions[0])
    assert "Stored_In_KeyVault" not in json.dumps(ui.global_actions[0])
    assert ui.global_actions[0]["additionalFields"]["hidden_setting"] == hidden


@pytest.mark.parametrize("auth_type", ["username_password", "api_key", "bearer_token"])
def test_personal_identity_create_and_masked_edit_without_action_authoring(action_auth_ui, auth_type):
    ui = action_auth_ui
    ui.disabled_sections["actions"] = "Personal action authoring is disabled."
    ui.open("/workspace/identities")
    ui.page.get_by_role("button", name="Add action identity", exact=True).click()
    dialog = ui.page.get_by_role("dialog", name="Add action identity", exact=True)
    expect(dialog.get_by_role("textbox", name="Identity name", exact=True)).to_have_value("Yamcs")
    dialog.get_by_role("combobox", name="Credential type", exact=True).select_option(auth_type)
    if auth_type == "username_password":
        dialog.get_by_role("textbox", name="Username", exact=True).fill(USERNAME)
        dialog.get_by_label(re.compile(r"^Password\*?$")).fill(PASSWORD)
    else:
        dialog.get_by_label(re.compile(r"^API key\*?$" if auth_type == "api_key" else r"^Bearer token\*?$")).fill(TOKEN)
    dialog.get_by_role("button", name="Save identity", exact=True).click()
    expect(dialog).to_have_count(0)
    ui.page.get_by_role("button", name="Edit Yamcs", exact=True).click()
    edit = ui.page.get_by_role("dialog", name="Edit action identity", exact=True)
    expect(edit.locator('input[type="password"]')).to_have_value("")
    expect(edit.locator('input[type="password"]')).to_have_attribute("placeholder", re.compile("Stored"))
    edit.get_by_label("Description", exact=True).fill("Keep the stored credential.")
    edit.get_by_role("button", name="Save identity", exact=True).click()
    expect(edit).to_have_count(0)
    patch = next(entry for entry in reversed(ui.requests) if entry.method == "PATCH" and "/workspace-identities/" in entry.path)
    assert "password" not in patch.body["credentials"]
    assert "secret" not in patch.body["credentials"]
    ui.assert_private(PASSWORD, TOKEN)


@pytest.mark.parametrize("width,height", [(1440, 1100), (390, 844)])
def test_private_card_defers_draft_and_runs_once_without_secret_messages_or_storage(action_auth_ui, width, height):
    ui = action_auth_ui
    ui.open(width=width, height=height)
    ui.select_agent()
    ui.submit_chat("Preserve this exact unsent message.")
    expect(ui.page.get_by_role("textbox", name="Message", exact=True)).to_have_value("Preserve this exact unsent message.")
    assert not ui.calls("/api/create_conversation")
    assert not stream_calls(ui)
    expect(ui.card.get_by_text("Private to you", exact=True)).to_be_visible()
    expect(ui.card.get_by_label("Do not render this")).to_have_count(0)
    credential_fields(ui)
    ui.card.get_by_role("button", name="Save and continue", exact=True).click()
    expect(ui.card).to_have_count(0)
    expect(ui.page.get_by_text("Read-only Yamcs telemetry result.", exact=True)).to_be_visible()
    expect(ui.page.get_by_role("textbox", name="Message", exact=True)).to_have_value("")
    assert len(stream_calls(ui)) == 1
    assert stream_calls(ui)[0].body["message"] == "Preserve this exact unsent message."
    assert len(ui.calls("/api/action-auth/preflight")) == 2
    assert ui.calls("/api/action-auth/preflight")[0].body["conversation_id"] is None
    assert ui.calls("/api/action-auth/preflight")[1].body["conversation_id"] == stream_calls(ui)[0].body["conversation_id"]
    assert stream_calls(ui)[0].body["action_auth_request_id"] == ui.request_id
    ui.assert_private(PASSWORD)
    ui.assert_no_overflow()


def test_failed_save_is_safe_retryable_and_double_submit_cancel_never_runs(action_auth_ui):
    ui = action_auth_ui
    ui.open()
    ui.select_agent()
    ui.submit_chat("Leave my draft here.")
    path = f"/api/action-auth/requests/{ui.request_id}/credentials"
    ui.reject_next("POST", path, status=403, error="Unsafe upstream details", error_code="action_auth_rejected")
    credential_fields(ui)
    ui.card.get_by_role("button", name="Save and continue", exact=True).click()
    expect(ui.card.get_by_role("alert")).to_contain_text("service rejected")
    expect(ui.card.get_by_label(re.compile(r"^Password\*?$"))).to_have_value("")
    expect(ui.page.get_by_text("Unsafe upstream details", exact=True)).to_have_count(0)
    assert not stream_calls(ui)
    ui.defer_next("POST", path)
    credential_fields(ui)
    ui.card.get_by_role("button", name="Save and continue", exact=True).click()
    expect(ui.card.get_by_role("button", name="Saving…", exact=True)).to_be_disabled()
    ui.card.locator("form").evaluate("form => { form.requestSubmit(); form.requestSubmit(); }")
    assert len(ui.calls(path)) == 2
    ui.card.get_by_role("button", name="Cancel", exact=True).click()
    expect(ui.card).to_have_count(0)
    expect(ui.page.get_by_role("textbox", name="Message", exact=True)).to_have_value("Leave my draft here.")
    ui.release_responses()
    assert not stream_calls(ui)
    ui.assert_private(PASSWORD)


def test_manual_identity_setup_and_existing_binding_never_reload_secret(action_auth_ui):
    ui = action_auth_ui
    ui.open()
    ui.select_agent()
    ui.submit_chat()
    ui.card.get_by_text("Set up this identity manually", exact=True).click()
    with ui.page.expect_popup() as popup:
        ui.card.get_by_role("link", name="My Workspace > Identities", exact=True).click()
    identities_page = popup.value
    identities_page.get_by_role("button", name="Add action identity", exact=True).click()
    dialog = identities_page.get_by_role("dialog", name="Add action identity")
    dialog.get_by_role("textbox", name="Username", exact=True).fill(USERNAME)
    dialog.get_by_label(re.compile(r"^Password\*?$")).fill(PASSWORD)
    dialog.get_by_role("button", name="Save identity", exact=True).click()
    expect(dialog).to_have_count(0)
    identities_page.close()
    ui.card.get_by_role("button", name="Check again", exact=True).click()
    ui.card.get_by_label("Personal identity", exact=True).select_option("identity-1")
    expect(ui.card.locator('input[type="password"]')).to_have_count(0)
    ui.card.get_by_role("checkbox", name=re.compile("^I approve sending")).check()
    credential_path = f"/api/action-auth/requests/{ui.request_id}/credentials"
    ui.card.get_by_role("button", name="Save and continue", exact=True).click()
    expect(ui.card).to_have_count(0)
    saved = ui.calls(credential_path)[-1].body
    assert saved == {"requirement_id": REQUIREMENT_ID, "identity_id": "identity-1", "confirm_destination": True}
    expect(ui.page.get_by_text("Read-only Yamcs telemetry result.", exact=True)).to_be_visible()
    assert len(stream_calls(ui)) == 1
    ui.assert_private(PASSWORD)


def test_reload_and_selection_changes_cancel_private_input_without_auto_send(action_auth_ui):
    ui = action_auth_ui
    ui.open()
    ui.select_agent()
    ui.submit_chat("Do not send after navigation.")
    credential_fields(ui)
    ui.page.get_by_role("textbox", name="Message", exact=True).fill("Updated unsent draft.")
    expect(ui.card).to_have_count(0)
    assert not stream_calls(ui)
    ui.page.get_by_role("button", name="Send message", exact=True).click()
    expect(ui.card).to_be_visible()
    credential_fields(ui)
    ui.page.reload(wait_until="networkidle")
    expect(ui.card).to_have_count(0)
    assert not stream_calls(ui)
    ui.assert_private(PASSWORD)


def test_uploaded_context_survives_authentication_and_own_conversation_adoption(action_auth_ui):
    ui = action_auth_ui
    ui.open()
    ui.select_agent()
    with ui.page.expect_response(lambda response: urlsplit(response.url).path == "/upload"):
        ui.page.locator('input[type="file"]').first.set_input_files({
            "name": "telemetry.pdf", "mimeType": "application/pdf", "buffer": b"%PDF-1.4\nsynthetic telemetry\n",
        })
    expect(ui.page.get_by_text("telemetry.pdf", exact=True)).to_be_visible()
    ui.submit_chat("Use the attached telemetry notes.")
    expect(ui.page.get_by_text("telemetry.pdf", exact=True)).to_be_visible()
    expect(ui.page.get_by_role("textbox", name="Message", exact=True)).to_have_value("Use the attached telemetry notes.")
    assert not stream_calls(ui)
    assert ui.calls("/api/action-auth/preflight")[-1].body["conversation_id"] == "upload-created-conversation"
    credential_fields(ui)
    ui.card.get_by_role("button", name="Save and continue", exact=True).click()
    expect(ui.page.get_by_text("Read-only Yamcs telemetry result.", exact=True)).to_be_visible()
    expect(ui.page.get_by_role("textbox", name="Message", exact=True)).to_have_value("")
    assert stream_calls(ui)[0].body["selected_document_ids"] == ["uploaded-document"]
    assert stream_calls(ui)[0].body["message"] == "Use the attached telemetry notes."
    ui.assert_private(PASSWORD)


def test_shared_notice_is_actor_local_even_with_saved_identity(action_auth_ui, browser, action_auth_build):
    bob = action_auth_ui
    bob.ready_identity = True
    bob.open(f"/chat?conversationId={SHARED_ID}")
    context = browser.new_context(viewport={"width": 1440, "height": 1100})
    alice = ActionAuthFixture(context.new_page(), actor="fixture-alice")
    try:
        alice.open(f"/chat?conversationId={SHARED_ID}")
        bob.select_agent()
        bob.submit_chat("Bob requests telemetry.")
        expect(bob.card.get_by_test_id("action-auth-sharing-notice")).to_be_visible()
        expect(bob.card.locator('input[type="password"]')).to_have_count(0)
        expect(alice.card).to_have_count(0)
        expect(alice.page.get_by_text("Previous shared telemetry result.", exact=True)).to_be_visible()
        assert not stream_calls(bob)
        bob.card.get_by_role("checkbox", name="I understand that my message and returned data are shared.").check()
        bob.card.get_by_role("button", name="Continue with my account", exact=True).click()
        expect(bob.card).to_have_count(0)
        expect(bob.page.get_by_text("Read-only Yamcs telemetry result.", exact=True)).to_be_visible()
        assert len(stream_calls(bob)) == 1
        preflight = bob.calls("/api/action-auth/preflight")[-1].body
        assert preflight["conversation_id"] == SHARED_ID
        assert preflight["conversation_kind"] == "collaboration"
        assert "fixture-alice" not in json.dumps(preflight)
        alice.select_agent()
        alice.submit_chat("Alice requests different telemetry.")
        expect(alice.card.get_by_role("textbox", name="Username", exact=True)).to_be_visible()
        expect(bob.card).to_have_count(0)
        alice.card.get_by_role("button", name="Cancel", exact=True).click()
        expect(alice.card).to_have_count(0)
        alice.assert_clean()
    finally:
        context.close()


def test_admin_test_as_me_uses_private_identity_not_global_action_secret(action_auth_ui):
    ui = action_auth_ui
    open_admin(ui)
    ui.page.get_by_role("button", name="Test as me", exact=True).click()
    expect(ui.card).to_be_visible()
    assert ui.calls("/api/action-auth/preflight")[-1].body["action_ref"].startswith("action:v1:global:")
    credential_fields(ui)
    ui.card.get_by_role("button", name="Save and continue", exact=True).click()
    expect(ui.card).to_have_count(0)
    expect(ui.page.get_by_text("Connected to the saved Yamcs destination using your private personal identity.", exact=True)).to_be_visible()
    body = ui.calls("/api/plugins/test-yamcs-connection")[-1].body
    assert set(body) == {"action_ref"}
    assert body["action_ref"] == ui.calls("/api/action-auth/preflight")[-1].body["action_ref"]
    assert "credentials" not in json.dumps(ui.global_actions)
    ui.assert_private(PASSWORD)


def test_read_only_personal_catalog_keeps_global_requirement_but_no_authoring_controls(action_auth_ui):
    ui = action_auth_ui
    ui.open(f"/workspace/actions/{GLOBAL_ACTION_ID}?scope=global")
    ui.page.get_by_role("navigation", name="Editor sections", exact=True).get_by_role("button", name="Authentication", exact=True).click()
    expect(ui.page.get_by_role("textbox", name="Personal identity name", exact=True)).to_have_value("Yamcs")
    expect(ui.page.get_by_role("textbox", name="Personal identity name", exact=True)).to_be_disabled()
    expect(ui.page.get_by_label("Authentication profile", exact=True)).to_be_disabled()
    expect(ui.page.get_by_label("Credential source", exact=True)).to_have_count(0)
    assert not [entry for entry in ui.writes if "/plugins" in entry.path]


def test_orchestration_waits_before_executable_run_and_runtime_auth_never_replays(action_auth_ui):
    ui = action_auth_ui
    ui.orchestration_enabled = True
    ui.open()
    ui.page.get_by_role("textbox", name="Message", exact=True).fill("Plan a telemetry review.")
    ui.page.get_by_role("button", name="Send message", exact=True).click()
    ui.page.get_by_role("button", name="Approve and run the plan", exact=True).click()
    expect(ui.card).to_be_visible()
    assert ui.calls("/api/action-auth/preflight")[-1].body["run_id"] == "yamcs-run"
    assert not ui.calls("/api/v2/orchestration/run")
    ui.card.get_by_role("button", name="Cancel", exact=True).click()
    expect(ui.card).to_have_count(0)
    assert not ui.calls("/api/v2/orchestration/run")
    ui.page.get_by_role("button", name="Run the saved plan", exact=True).click()
    expect(ui.card).to_be_visible()
    credential_fields(ui)
    ui.card.get_by_role("button", name="Save and continue", exact=True).click()
    expect(ui.card).to_have_count(0)
    expect(ui.page.get_by_text("Completed mission plan.", exact=True)).to_be_visible()
    assert len(ui.calls("/api/v2/orchestration/run")) == 1
    ui.assert_private(PASSWORD)


def test_runtime_credential_control_is_private_not_assistant_or_oauth(action_auth_ui):
    ui = action_auth_ui
    ui.ready_identity = True
    ui.runtime_rejection = True
    ui.open()
    ui.select_agent()
    ui.submit_chat("Read after credential revocation.")
    expect(ui.card.get_by_text(re.compile("started request was interrupted"))).to_be_visible()
    expect(ui.page.get_by_text("This control must not become assistant content.", exact=True)).to_have_count(0)
    credential_fields(ui)
    assert ui.calls("/api/action-auth/preflight")[-1].body == {
        "action_ref": ACTION_REF,
        "conversation_id": stream_calls(ui)[-1].body["conversation_id"],
        "conversation_kind": "personal",
    }
    assert ui.request_id not in ui.consumed
    assert not [
        entry for entry in ui.requests
        if entry.method == "GET" and any(entry.path == f"/api/action-auth/requests/{old_id}" for old_id in ui.consumed)
    ]
    ui.card.get_by_role("button", name="Save connection", exact=True).click()
    expect(ui.card.get_by_text("Your personal connection is ready.", exact=True)).to_be_visible()
    ui.card.get_by_role("button", name="Done — do not replay", exact=True).click()
    expect(ui.card).to_have_count(0)
    assert len(stream_calls(ui)) == 1
    assert not [entry for entry in ui.requests if "reattach" in entry.path or "oauth" in entry.path]
    ui.assert_private(PASSWORD)


def test_type_only_pre_execution_control_keeps_the_draft_for_explicit_retry(action_auth_ui):
    ui = action_auth_ui
    ui.ready_identity = True
    ui.runtime_rejection = True
    ui.execution_started = False
    ui.control_discriminator = "type"
    ui.open()
    ui.select_agent()
    ui.submit_chat("Keep this draft until execution really starts.")
    expect(ui.card.get_by_text(re.compile("This request was not started"))).to_be_visible()
    expect(ui.page.get_by_role("textbox", name="Message", exact=True)).to_have_value("Keep this draft until execution really starts.")
    credential_fields(ui)
    ui.card.get_by_role("button", name="Save connection", exact=True).click()
    expect(ui.card.get_by_text("Your personal connection is ready.", exact=True)).to_be_visible()
    ui.card.get_by_role("button", name="Done — do not replay", exact=True).click()
    expect(ui.card).to_have_count(0)
    assert len(stream_calls(ui)) == 1
    expect(ui.page.get_by_role("textbox", name="Message", exact=True)).to_have_value("Keep this draft until execution really starts.")
    ui.assert_private(PASSWORD)


def test_rejected_saved_identity_defaults_to_replacement_without_auto_selection(action_auth_ui):
    ui = action_auth_ui
    ui._save_identity({
        "name": "Yamcs", "credentials": {
            "auth_type": "username_password", "username": "previous-synthetic-user", "password": "previous-synthetic-password",
        },
    })
    ui.ready_identity = True
    ui.runtime_rejection = True
    ui.control_discriminator = "type"
    ui.open()
    ui.select_agent()
    ui.submit_chat("Repair a rejected Yamcs identity.")
    expect(ui.card.get_by_text(re.compile("The started request was interrupted"))).to_be_visible()
    expect(ui.card.get_by_text(re.compile("Yamcs rejected the saved credential"))).to_be_visible()
    expect(ui.card.get_by_label("Personal identity", exact=True)).to_have_value("")
    ui.card.get_by_label("Personal identity", exact=True).select_option("identity-1")
    expect(ui.card.get_by_role("checkbox", name="Replace this identity’s credential", exact=True)).to_be_checked()
    expect(ui.card.get_by_role("textbox", name="Username", exact=True)).to_have_value("")
    expect(ui.card.get_by_label(re.compile(r"^Password\*?$"))).to_have_value("")
    credential_fields(ui)
    path = f"/api/action-auth/requests/{ui.request_id}/credentials"
    ui.card.get_by_role("button", name="Save connection", exact=True).click()
    expect(ui.card.get_by_text("Your personal connection is ready.", exact=True)).to_be_visible()
    assert ui.calls(path)[-1].body["identity_id"] == "identity-1"
    assert ui.calls(path)[-1].body["credentials"] == {"username": USERNAME, "password": PASSWORD}
    assert len(stream_calls(ui)) == 1
    ui.card.get_by_role("button", name="Done — do not replay", exact=True).click()
    expect(ui.card).to_have_count(0)
    assert len(stream_calls(ui)) == 1
    ui.assert_private(PASSWORD)


def test_requirement_labels_are_text_and_disabled_workspace_has_no_dead_manual_link(action_auth_ui):
    ui = action_auth_ui
    ui.workspace_enabled = False
    ui.global_actions[0]["credential_requirement"]["identity_name"] = '<img src=x onerror="window.actionAuthXss=true">'
    ui.open()
    ui.select_agent()
    ui.submit_chat()
    expect(ui.card.get_by_text('<img src=x onerror="window.actionAuthXss=true">', exact=True)).to_be_visible()
    expect(ui.card.locator("img")).to_have_count(0)
    assert not ui.page.evaluate("Boolean(window.actionAuthXss)")
    ui.card.get_by_text("Set up this identity manually", exact=True).click()
    expect(ui.card.get_by_role("link", name="My Workspace > Identities", exact=True)).to_have_count(0)
    expect(ui.card.get_by_text(re.compile("Use this private form instead"))).to_be_visible()
    ui.card.get_by_role("button", name="Cancel", exact=True).click()
    expect(ui.card).to_have_count(0)


def test_automatic_plan_authentication_cancel_clears_thinking_without_running(action_auth_ui):
    ui = action_auth_ui
    ui.orchestration_enabled = True
    ui.approval_mode = "auto"
    ui.open()
    ui.page.get_by_role("textbox", name="Message", exact=True).fill("Plan a telemetry review automatically.")
    ui.page.get_by_role("button", name="Send message", exact=True).click()
    expect(ui.card).to_be_visible()
    assert not ui.calls("/api/v2/orchestration/run")
    ui.card.get_by_role("button", name="Cancel", exact=True).click()
    expect(ui.card).to_have_count(0)
    expect(ui.page.get_by_role("button", name="Stop response", exact=True)).to_have_count(0)
    expect(ui.page.get_by_role("button", name="Send message", exact=True)).to_be_visible()
    assert not ui.calls("/api/v2/orchestration/run")
