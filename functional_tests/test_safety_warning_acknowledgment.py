#!/usr/bin/env python3
# test_safety_warning_acknowledgment.py
"""
Functional test for immediate, must-acknowledge safety warnings.
Version: 0.261.296
Implemented in: 0.261.296

This test ensures that a safety reviewer's warning is sent as the review is saved, without
an approval request, and is sent once per violation; that the warned user can list and
acknowledge only their own warnings, with only what they were sent; that acknowledging is
idempotent, marks the delivering notification read and never overwrites a concurrent
reviewer save; that warnings sent before acknowledgment was tracked never ask for it; that
the user-facing routes are not gated on the content checks report; and that a failed send
is recorded and can be retried. Real modules run in fresh processes with network access
blocked, under normal and optimized Python.
"""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "application" / "single_app"
sys.path.insert(0, str(ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402


WARNING_PROBE = r'''
import importlib
import json
import sys
from contextlib import ExitStack
from pathlib import Path

root = Path(sys.argv[1])
sys.path.insert(0, str(root / "functional_tests"))
sys.path.insert(0, str(root / "application" / "single_app"))
from test_support.offline_bootstrap import offline_app_imports
from test_support.safety_review_harness import build_safety_app, check, sign_in, sign_out

USER_FIELDS = {"id", "violation_id", "title", "message", "issued_at", "acknowledged_at", "triggered_categories"}

with offline_app_imports(), ExitStack() as stack:
    importlib.import_module(sys.argv[2])
    import functions_safety_remediation as remediation

    h = build_safety_app(stack)
    client, container = h.client, h.container
    base = {"status": "New", "action": "None", "created_at": "2026-10-01T00:00:00", "message": "Flagged text",
            "triggered_categories": [{"category": "Hate", "severity": 4}, {"category": "Violence", "severity": 2}]}
    container.seed({**base, "id": "log-warn", "user_id": "user-1", "notes": "Reviewer-only notes"})
    container.seed({**base, "id": "log-legacy", "user_id": "user-1", "action": "WarnUser",
                    "action_request_status": "executed", "status": "Resolved"})
    container.seed({**base, "id": "log-other", "user_id": "user-2"})
    container.seed({**base, "id": "log-ai", "user_id": "user-1", "content_origin": "assistant"})

    # A reviewer's warning is sent as the review is saved: no approval, no restriction.
    sign_in(client, "reviewer-1", roles=("Admin",))
    response = client.patch("/api/safety/logs/log-warn", json={
        "status": "In-Review", "action": "WarnUser", "notes": "Reviewer-only notes", "notification_message": "",
    })
    body = response.get_json()
    check(response.status_code == 200, f"warning save failed: {response.status_code} {body}")
    check(body["approval_required"] is False and body["message"] == "Warning sent to the user.", str(body))
    check(body["audit_logged"] is True and h.approvals == [], "A warning created an approval request")
    check(h.access_writes == [], "A warning restricted access")
    check(len(h.notifications) == 1, f"expected one notification, got {len(h.notifications)}")
    sent = h.notifications[0]
    check(sent["notification_type"] == "safety_violation_warning" and sent["user_id"] == "user-1", str(sent))
    stored = container.items["log-warn"]
    check(stored["action_request_status"] == "executed" and stored["action_request_id"] is None, str(stored))
    check(stored["warning_requires_acknowledgment"] is True and stored["warning_acknowledged_at"] is None, str(stored))
    check(stored["warning_notification_id"] == sent["id"], str(stored))
    check(stored["warning_title"] == sent["title"] and stored["warning_message"] == sent["message"], str(stored))
    check(stored["warning_issued_at"] == stored["action_executed_at"], str(stored))
    audit = h.audits[-1]
    check(audit["action"] == "safety_violation_warning_sent" and audit["admin_user_id"] == "reviewer-1", str(audit))
    check(audit["additional_context"]["record_id"] == "log-warn", str(audit))

    # Saving the warned record again, here to resolve it, does not warn twice.
    response = client.patch("/api/safety/logs/log-warn", json={
        "status": "Resolved", "action": "WarnUser", "notes": "Resolved after the warning.",
    })
    body = response.get_json()
    check(response.status_code == 200 and body.get("warning_already_sent") is True, str(body))
    check(len(h.notifications) == 1, "A re-save sent the warning again")
    check(container.items["log-warn"]["status"] == "Resolved", "the re-save was not stored")
    check(container.items["log-warn"]["warning_notification_id"] == sent["id"], "the warning record changed")

    # Reviewers see the acknowledgment state on the list.
    logs = {row["id"]: row for row in client.get("/api/safety/logs?page=1&page_size=100").get_json()["logs"]}
    check(logs["log-warn"]["warning_acknowledgment_status"] == "pending", str(logs["log-warn"]))
    check(logs["log-legacy"]["warning_acknowledgment_status"] == "not_tracked", str(logs["log-legacy"]))
    check(logs["log-other"]["warning_acknowledgment_status"] is None, str(logs["log-other"]))

    # The warned user sees only what they were sent, and legacy warnings never ask.
    sign_in(client, "user-1")
    response = client.get("/api/safety/warnings/pending")
    body = response.get_json()
    check(response.status_code == 200 and response.headers.get("Cache-Control") == "no-store", str(body))
    check([warning["id"] for warning in body["warnings"]] == ["log-warn"] and body["count"] == 1, str(body))
    warning = body["warnings"][0]
    check(set(warning) == USER_FIELDS, f"unexpected warning fields: {sorted(warning)}")
    check(warning["message"] == sent["message"] and warning["title"] == sent["title"], str(warning))
    check(warning["triggered_categories"] == [{"category": "Hate", "severity": 4},
                                              {"category": "Violence", "severity": 2}], str(warning))
    serialized = json.dumps(body)
    check("Resolved after the warning." not in serialized and "Flagged text" not in serialized, "Record data leaked")
    check("notification-" not in serialized and "user-1" not in serialized, "Internal fields leaked")
    check(remediation.count_pending_safety_warnings("user-1") == 1, "bootstrap count differs from the list")
    check(remediation.count_pending_safety_warnings("user-2") == 0, "another user's warning was counted")
    check(any(query.startswith("SELECT VALUE COUNT(1) FROM c WHERE c.user_id = @user_id") for query in container.queries),
          "the count is not scoped to the caller")

    # Another user can neither see nor acknowledge it, and can't tell it exists.
    sign_in(client, "user-2")
    check(client.get("/api/safety/warnings/pending").get_json()["warnings"] == [], "cross-user listing")
    for log_id in ("log-warn", "does-not-exist"):
        response = client.post(f"/api/safety/warnings/{log_id}/acknowledge", json={})
        check(response.status_code == 404 and response.get_json() == {"error": "Warning not found."}, log_id)
    check(container.items["log-warn"]["warning_acknowledged_at"] is None, "cross-user acknowledgment")

    # The owner acknowledges once; a reviewer saving at the same moment is kept.
    sign_in(client, "user-1")

    def reviewer_saves(store):
        item = store.read_item("log-warn", "log-warn")
        item["notes"] = "Concurrent reviewer note"
        store.upsert_item(item)

    container.before_replace = reviewer_saves
    response = client.post("/api/safety/warnings/log-warn/acknowledge", json={})
    body = response.get_json()
    check(response.status_code == 200 and body["already_acknowledged"] is False, str(body))
    check(body["warning"]["acknowledged_at"] and set(body["warning"]) == USER_FIELDS, str(body))
    stored = container.items["log-warn"]
    check(stored["notes"] == "Concurrent reviewer note", "The acknowledgment overwrote a reviewer save")
    first_acknowledgment = stored["warning_acknowledged_at"]
    check(bool(first_acknowledgment), "acknowledgment not stored")
    check((sent["id"], "user-1") in h.read_marks, "The warning notification was not marked read")

    response = client.post("/api/safety/warnings/log-warn/acknowledge", json={})
    check(response.status_code == 200 and response.get_json()["already_acknowledged"] is True, "not idempotent")
    check(container.items["log-warn"]["warning_acknowledged_at"] == first_acknowledgment, "A repeat moved the time")
    check(client.get("/api/safety/warnings/pending").get_json()["warnings"] == [], "acknowledged warning pending")
    check(remediation.count_pending_safety_warnings("user-1") == 0, "an acknowledged warning is still counted")
    for log_id in ("log-legacy", "log-ai", "log-other"):
        response = client.post(f"/api/safety/warnings/{log_id}/acknowledge", json={})
        check(response.status_code == 404, f"{log_id} was acknowledgeable")

    # A sent warning stays acknowledgeable when content checks reporting is turned off.
    h.settings["enable_content_safety"] = False
    check(client.get("/api/safety/warnings/pending").status_code == 200, "warnings gated on the report")
    check(client.post("/api/safety/warnings/log-warn/acknowledge", json={}).status_code == 200, "ack gated")
    check(client.get("/api/safety/logs/my").status_code == 403, "the violation list lost its gate")
    h.settings["enable_content_safety"] = True

    sign_in(client, "reviewer-1", roles=("Admin",))
    logs = {row["id"]: row for row in client.get("/api/safety/logs?page=1&page_size=100").get_json()["logs"]}
    check(logs["log-warn"]["warning_acknowledgment_status"] == "acknowledged", str(logs["log-warn"]))
    check(logs["log-warn"]["warning_acknowledged_at"] == first_acknowledgment, str(logs["log-warn"]))

    # A failed send is recorded without exception text, and saving again retries it.
    container.seed({**base, "id": "log-fail", "user_id": "user-1"})
    h.fail_notifications = True
    response = client.patch("/api/safety/logs/log-fail", json={"status": "In-Review", "action": "WarnUser"})
    text = response.get_data(as_text=True)
    check(response.status_code == 500 and "could not be sent" in response.get_json()["error"], text)
    check("RuntimeError" not in text and "Failed to create" not in text, "exception text reached the browser")
    failed = container.items["log-fail"]
    check(failed["action_request_status"] == "failed" and failed["status"] == "In-Review", str(failed))
    check(not failed.get("warning_requires_acknowledgment"), "a failed warning asks for acknowledgment")
    h.fail_notifications = False
    response = client.patch("/api/safety/logs/log-fail", json={"status": "In-Review", "action": "WarnUser"})
    check(response.status_code == 200 and container.items["log-fail"]["action_request_status"] == "executed", "retry")

    # A warn_user approval created before this change still completes, through the same
    # three steps the Control Center approval path takes, and asks for acknowledgment.
    container.seed({**base, "id": "log-approved", "user_id": "user-1", "action": "WarnUser",
                    "action_request_status": "pending", "action_request_id": "approval-legacy"})
    log_item = remediation.get_safety_log_item("log-approved")
    result = remediation.execute_safety_violation_action(
        action="WarnUser", safety_log=log_item, notification_title="", notification_message="",
        datetime_to_allow=None, actor={"id": "approver-2", "email": "approver@contoso.test"},
    )
    updates = remediation.build_safety_action_execution_updates("WarnUser", result)
    updates.update({"action_request_id": "approval-legacy", "action_request_type": "warn_user"})
    remediation.update_safety_log_action_state("log-approved", updates)
    approved = container.items["log-approved"]
    check(approved["action_request_status"] == "executed" and approved["warning_requires_acknowledgment"] is True, str(approved))
    check(approved["warning_notification_id"] == result["notification_id"], str(approved))
    sign_in(client, "user-1")
    pending = client.get("/api/safety/warnings/pending").get_json()["warnings"]
    check([item["id"] for item in pending] == ["log-fail", "log-approved"], str(pending))

    suspend_updates = remediation.build_safety_action_execution_updates("SuspendUser", {"notification_id": "n"})
    check(not any(key.startswith("warning_") for key in suspend_updates), str(suspend_updates))

    # Signed out, nothing is answered; restricted, the warning waits until access returns.
    sign_out(client)
    check(client.get("/api/safety/warnings/pending").status_code == 401, "anonymous read")
    h.user_docs["user-1"] = {"id": "user-1", "settings": {"access": {"status": "deny", "datetime_to_allow": None}}}
    sign_in(client, "user-1")
    response = client.get("/api/safety/warnings/pending")
    check(response.status_code == 403 and response.get_json()["error"] == "access_restricted", "restricted read")

    from test_support.cosmos_query_guard import cosmos_query_problems
    for query in container.queries:
        check(not cosmos_query_problems(query), f"unsupported cross-partition query: {query}")

print("PASS: immediate, must-acknowledge safety warnings")
'''


@pytest.mark.parametrize("first_import", ["functions_safety_remediation", "route_backend_safety"])
@pytest.mark.parametrize("optimized", [False, True])
def test_real_warning_send_and_acknowledgment(first_import, optimized):
    command = [sys.executable, "-B"]
    if optimized:
        command.append("-O")
    result = subprocess.run(
        command + ["-c", WARNING_PROBE, str(ROOT), first_import],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: immediate, must-acknowledge safety warnings" in result.stdout


def _function_source(path, name):
    source = path.read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(source, node)
    raise AssertionError(f"{name} not found in {path.name}")


def test_route_contracts_for_the_user_warning_routes():
    """The user routes require a user session and are not gated on the content checks report."""
    tree = ast.parse((APP_DIR / "route_backend_safety.py").read_text(encoding="utf-8"))
    expected = {
        "get_pending_safety_warnings": "bp.route('/api/safety/warnings/pending', methods=['GET'])",
        "acknowledge_pending_safety_warning": (
            "bp.route('/api/safety/warnings/<string:log_id>/acknowledge', methods=['POST'])"
        ),
    }
    found = {
        node.name: [ast.unparse(item) for item in node.decorator_list]
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name in expected
    }
    assert set(found) == set(expected)
    for name, route in expected.items():
        assert found[name] == [
            route,
            "swagger_route(security=get_auth_security())",
            "login_required",
            "user_required",
        ], found[name]


def test_control_center_approval_path_marks_warnings_for_acknowledgment():
    """Approvals created before warnings stopped needing one finish the same way."""
    source = _function_source(APP_DIR / "route_backend_control_center.py", "_execute_safety_violation_request")
    assert "build_safety_action_execution_updates(action, result)" in source
    assert "update_safety_log_action_state(safety_log_id, execution_updates)" in source


def test_v2_warning_dialog_and_settings_are_wired():
    v2 = ROOT / "application" / "v2_ui" / "src"
    app_tsx = (v2 / "App.tsx").read_text(encoding="utf-8")
    # Read only when bootstrap counts some, so a user with none costs no extra request.
    assert "data && !error && !standalonePage ? data.safety_warnings?.pending ?? 0 : null," in app_tsx
    runtime = (v2 / "lib" / "useSafetyWarningRuntime.ts").read_text(encoding="utf-8")
    assert "if (pending <= 0) {" in runtime and "}, [pending, revision]);" in runtime
    bootstrap = (APP_DIR / "route_backend_v2.py").read_text(encoding="utf-8")
    assert "pending_safety_warnings = count_pending_safety_warnings(user_id)" in bootstrap
    assert '"safety_warnings": {"pending": pending_safety_warnings},' in bootstrap
    shell = (v2 / "components" / "layout" / "AppShell.tsx").read_text(encoding="utf-8")
    assert "<SafetyWarningDialogHost />" in shell
    dialog = (v2 / "components" / "notifications" / "SafetyWarningDialog.tsx").read_text(encoding="utf-8")
    assert "A warning from your administrators" in dialog and "I understand" in dialog
    assert "dangerouslySetInnerHTML" not in dialog
    client = (v2 / "lib" / "safetyWarnings.ts").read_text(encoding="utf-8")
    assert "/api/safety/warnings/pending" in client
    assert "/api/safety/warnings/${encodeURIComponent(id)}/acknowledge" in client
    violations = (v2 / "components" / "settings" / "ViolationsTab.tsx").read_text(encoding="utf-8")
    assert "warning_acknowledgment_status" in violations
    admin_page = (v2 / "pages" / "AdminSafetyViolationsPage.tsx").read_text(encoding="utf-8")
    assert "Warning acknowledged" in admin_page and "Not yet acknowledged" in admin_page
    assert "The warning is sent to the user as soon as you save" in admin_page
    assert "otherwise it becomes a pending request" not in admin_page


def test_version():
    assert_app_version_at_least("0.261.296")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
