#!/usr/bin/env python3
# test_safety_remediation_approval_state.py
"""
Functional test for settling safety remediation requests and writing reviews safely.
Version: 0.261.298
Implemented in: 0.261.298

This test ensures the three remediation state fixes hold:

1. Denying a warn, suspend or block request, or letting it expire, unlocks its violation:
   the real deny_request and the expiry sweep record 'denied' or 'expired' on the
   violation, which can then be edited and deleted again. Listing or opening violations
   settles one whose request was decided elsewhere, or no longer exists and could no
   longer be pending; a request that is genuinely still pending, or a lookup that fails,
   keeps its violation locked, and a denial never unlocks a violation that moved on to a
   newer request.
2. Saving a violation whose suspension or block was already requested or applied, with
   the same action, creates no second approval request unless the reviewer asks to
   re-issue it; changing the action does request it.
3. Review saves are ETag-conditional: a save never overwrites a user's concurrent
   acknowledgment, and a save that names a version the record no longer has is refused
   with 409 record_changed. Feedback review saves behave the same way.

Real modules run in fresh processes with network access blocked, under normal and
optimized Python.
"""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "application" / "single_app"
sys.path.insert(0, str(ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402


PROBE_HEADER = r'''
import importlib
import sys
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path

root = Path(sys.argv[1])
sys.path.insert(0, str(root / "functional_tests"))
sys.path.insert(0, str(root / "application" / "single_app"))
from test_support.offline_bootstrap import offline_app_imports
from test_support.safety_review_harness import (
    build_feedback_app, build_safety_app, check, patch_approval_decisions, sign_in,
)

NOW = datetime.now(timezone.utc).replace(tzinfo=None)
RECENT = (NOW - timedelta(hours=2)).isoformat()
OLD = (NOW - timedelta(days=4)).isoformat()
BASE = {"status": "In-Review", "created_at": "2026-10-01T00:00:00", "message": "Flagged text",
        "user_id": "user-1", "triggered_categories": [{"category": "Hate", "severity": 4}]}
'''


DECISION_PROBE = PROBE_HEADER + r'''
with offline_app_imports(), ExitStack() as stack:
    importlib.import_module(sys.argv[2])
    h = build_safety_app(stack)
    approvals = patch_approval_decisions(stack, h)
    client, container, store = h.client, h.container, h.approvals_container
    sign_in(client, "reviewer-1", roles=("Admin",))

    def pending_log(log_id, approval_id, requested_at=RECENT):
        container.seed({**BASE, "id": log_id, "action": "SuspendUser", "action_request_status": "pending",
                        "action_request_id": approval_id, "action_request_type": "suspend_user",
                        "action_requested_at": requested_at, "action_datetime_to_allow": "2026-12-01T00:00:00"})

    def approval(approval_id, log_id, status="pending", expires_at=None):
        store.add({"id": approval_id, "group_id": "user-1", "group_name": "User One",
                   "request_type": "suspend_user", "status": status, "requester_id": "reviewer-2",
                   "created_at": RECENT, "expires_at": expires_at or (NOW + timedelta(days=2)).isoformat(),
                   "metadata": {"safety_log_id": log_id}})
        return store.items[approval_id]

    def state(log_id):
        return container.items[log_id].get("action_request_status")

    # A pending request locks its violation: edits and deletes are refused.
    pending_log("log-deny", "approval-deny")
    approval("approval-deny", "log-deny")
    response = client.patch("/api/safety/logs/log-deny", json={"status": "Resolved", "notes": "Done."})
    check(response.status_code == 409 and response.get_json()["code"] == "remediation_pending", str(response.get_json()))
    response = client.delete("/api/safety/logs/log-deny")
    check(response.status_code == 409 and response.get_json()["code"] == "remediation_pending", str(response.get_json()))
    check(state("log-deny") == "pending", "a refused edit changed the request state")

    # 1. A reviewer denies the request: the violation is released as denied and unlocked.
    approvals.deny_request("approval-deny", "user-1", "reviewer-3", "r3@contoso.test", "Reviewer Three",
                           "Not warranted.", approval=dict(store.items["approval-deny"]))
    check(store.items["approval-deny"]["status"] == "denied", "the denial was not stored")
    stored = container.items["log-deny"]
    check(stored["action_request_status"] == "denied" and stored["action_request_decided_at"], str(stored))
    response = client.patch("/api/safety/logs/log-deny", json={"status": "Resolved", "notes": "Denied, closing."})
    check(response.status_code == 200, f"a denied violation stayed locked: {response.get_json()}")
    check(container.items["log-deny"]["status"] == "Resolved", "the edit after denial was not saved")
    check(len(h.approvals) == 0, "saving the denied violation requested the suspension again")

    # 2. The expiry sweep denies an expired request: the violation is released as expired.
    pending_log("log-expire", "approval-expire")
    approval("approval-expire", "log-expire", expires_at=(NOW - timedelta(minutes=5)).isoformat())
    denied = approvals.auto_deny_expired_approvals()
    check(denied == 1 and store.items["approval-expire"]["status"] == "auto_denied", str(store.items["approval-expire"]))
    check(state("log-expire") == "expired", f"expiry left {state('log-expire')}")
    response = client.delete("/api/safety/logs/log-expire")
    check(response.status_code == 200 and "log-expire" not in container.items, f"delete after expiry: {response.get_json()}")

    # A denial never unlocks a violation that moved on to a newer request.
    pending_log("log-moved", "approval-new")
    approval("approval-new", "log-moved")
    old_request = approval("approval-old", "log-moved")
    approvals.deny_request("approval-old", "user-1", "reviewer-3", "r3@contoso.test", "Reviewer Three",
                           "", approval=dict(old_request))
    check(state("log-moved") == "pending" and container.items["log-moved"]["action_request_id"] == "approval-new",
          "denying an older request released the violation's newer one")

    # 3. Listing settles a violation whose request was decided without releasing it.
    pending_log("log-stale-denied", "approval-stale")
    approval("approval-stale", "log-stale-denied", status="denied")
    pending_log("log-stale-executed", "approval-done")
    approval("approval-done", "log-stale-executed", status="executed")
    # A request that no longer exists: expired only once it could no longer be pending.
    pending_log("log-gone-old", "approval-gone-old", requested_at=OLD)
    pending_log("log-gone-recent", "approval-gone-recent", requested_at=RECENT)
    # Still pending: stays locked.
    pending_log("log-still", "approval-still")
    approval("approval-still", "log-still")
    lookups_before = len([query for query in store.queries if "ARRAY_CONTAINS(@ids, c.id)" in query])
    rows = client.get("/api/safety/logs?page=1&page_size=100").get_json()["logs"]
    listed = {row["id"]: row.get("action_request_status") for row in rows}
    check(listed["log-stale-denied"] == "denied" and state("log-stale-denied") == "denied", str(listed))
    check(listed["log-stale-executed"] == "executed" and state("log-stale-executed") == "executed", str(listed))
    check(listed["log-gone-old"] == "expired" and state("log-gone-old") == "expired", str(listed))
    check(listed["log-gone-recent"] == "pending" and state("log-gone-recent") == "pending", str(listed))
    check(listed["log-still"] == "pending" and state("log-still") == "pending", str(listed))
    check(listed["log-moved"] == "pending", str(listed))
    lookups = len([query for query in store.queries if "ARRAY_CONTAINS(@ids, c.id)" in query]) - lookups_before
    check(lookups == 1, f"the list looked requests up {lookups} times instead of once")

    # Opening one violation settles it the same way.
    pending_log("log-open", "approval-open")
    approval("approval-open", "log-open", status="denied")
    detail = client.get("/api/safety/logs/log-open").get_json()
    check(detail["action_request_status"] == "denied" and state("log-open") == "denied", str(detail))

    # A failed lookup keeps every pending violation locked.
    pending_log("log-lookup", "approval-lookup")
    approval("approval-lookup", "log-lookup", status="denied")
    store.fail = True
    rows = client.get("/api/safety/logs?page=1&page_size=100").get_json()["logs"]
    store.fail = False
    check({row["id"]: row for row in rows}["log-lookup"]["action_request_status"] == "pending", "a failed lookup unlocked a violation")
    check(state("log-lookup") == "pending", "a failed lookup wrote the violation")

print("PASS: denied and expired remediation requests unlock their violation")
'''


REISSUE_PROBE = PROBE_HEADER + r'''
with offline_app_imports(), ExitStack() as stack:
    importlib.import_module(sys.argv[2])
    h = build_safety_app(stack)
    client, container = h.client, h.container
    sign_in(client, "reviewer-1", roles=("Admin",))
    UNTIL = (NOW + timedelta(days=7)).isoformat()

    # 2. An applied suspension saved again with the same action requests nothing more.
    container.seed({**BASE, "id": "log-applied", "action": "SuspendUser", "action_request_status": "executed",
                    "action_request_id": "approval-seeded-1", "action_datetime_to_allow": UNTIL})
    response = client.patch("/api/safety/logs/log-applied", json={
        "status": "Resolved", "action": "SuspendUser", "notes": "Closing the review.",
        "notification_message": "Suspended.", "datetime_to_allow": UNTIL,
    })
    body = response.get_json()
    check(response.status_code == 200 and body.get("remediation_already_applied") is True, str(body))
    check(body.get("approval_required") is False and not h.approvals, f"a duplicate request was created: {h.approvals}")
    stored = container.items["log-applied"]
    check(stored["status"] == "Resolved" and stored["notes"] == "Closing the review.", str(stored))
    check(stored["action_request_status"] == "executed" and stored["action_request_id"] == "approval-seeded-1", str(stored))

    # A denied block saved again with the same action: unchanged, and says how to request it.
    container.seed({**BASE, "id": "log-denied", "action": "BlockUser", "action_request_status": "denied",
                    "action_request_id": "approval-seeded-2"})
    response = client.patch("/api/safety/logs/log-denied", json={"status": "Dismissed", "action": "BlockUser"})
    body = response.get_json()
    check(response.status_code == 200 and body.get("remediation_unchanged") is True, str(body))
    check(body.get("remediation_status") == "denied" and not h.approvals, str(body))

    # The reviewer asks to re-issue it: one new request.
    response = client.patch("/api/safety/logs/log-denied", json={
        "status": "In-Review", "action": "BlockUser", "reissue": True, "notification_message": "Blocked.",
    })
    body = response.get_json()
    check(response.status_code == 200 and body.get("approval_required") is True, str(body))
    check(len(h.approvals) == 1 and h.approvals[0]["request_type"] == "block_user", str(h.approvals))
    stored = container.items["log-denied"]
    check(stored["action_request_status"] == "pending" and stored["action_request_id"] == h.approvals[0]["id"], str(stored))

    # Changing the action requests the new one.
    response = client.patch("/api/safety/logs/log-applied", json={
        "status": "In-Review", "action": "BlockUser", "notification_message": "Now blocked.",
    })
    check(response.status_code == 200 and response.get_json().get("approval_required") is True, str(response.get_json()))
    check(len(h.approvals) == 2 and h.approvals[1]["request_type"] == "block_user", str(h.approvals))

    # A suspension asked for again still needs its restore time.
    container.seed({**BASE, "id": "log-suspend", "action": "SuspendUser", "action_request_status": "expired",
                    "action_request_id": "approval-seeded-3"})
    response = client.patch("/api/safety/logs/log-suspend", json={"action": "SuspendUser", "reissue": True})
    check(response.status_code == 400 and len(h.approvals) == 2, f"a suspension without a restore time: {response.get_json()}")
    response = client.patch("/api/safety/logs/log-suspend", json={
        "action": "SuspendUser", "reissue": True, "datetime_to_allow": UNTIL,
    })
    check(response.status_code == 200 and len(h.approvals) == 3, str(response.get_json()))
    check(h.approvals[2]["metadata"]["datetime_to_allow"] == UNTIL, str(h.approvals[2]["metadata"]))

    # A pending request is never duplicated: the violation is locked.
    response = client.patch("/api/safety/logs/log-suspend", json={
        "action": "SuspendUser", "reissue": True, "datetime_to_allow": UNTIL,
    })
    check(response.status_code == 409 and response.get_json()["code"] == "remediation_pending", str(response.get_json()))
    check(len(h.approvals) == 3, "a pending request was duplicated")

print("PASS: an unchanged suspension or block is not requested twice")
'''


ETAG_PROBE = PROBE_HEADER + r'''
with offline_app_imports(), ExitStack() as stack:
    importlib.import_module(sys.argv[2])
    h = build_safety_app(stack)
    client, container = h.client, h.container
    sign_in(client, "reviewer-1", roles=("Admin",))

    # 3. A warned user acknowledges while a reviewer's save is being written: the save is
    # written on top of the acknowledgment, never over it.
    container.seed({**BASE, "id": "log-ack", "action": "WarnUser", "action_request_status": "executed",
                    "warning_requires_acknowledgment": True, "warning_acknowledged_at": None,
                    "warning_issued_at": "2026-10-02T09:00:00+00:00", "warning_message": "Please stop."})

    def user_acknowledges(store):
        item = dict(store.items["log-ack"])
        item["warning_acknowledged_at"] = "2026-10-03T10:00:00+00:00"
        store.seed(item)

    container.before_replace = user_acknowledges
    response = client.patch("/api/safety/logs/log-ack", json={"status": "Resolved", "action": "WarnUser", "notes": "Seen."})
    check(response.status_code == 200 and response.get_json().get("warning_already_sent") is True, str(response.get_json()))
    stored = container.items["log-ack"]
    check(stored["warning_acknowledged_at"] == "2026-10-03T10:00:00+00:00", "the save overwrote the acknowledgment")
    check(stored["status"] == "Resolved" and stored["notes"] == "Seen.", str(stored))

    # A save naming a version the violation no longer has is refused.
    detail = client.get("/api/safety/logs/log-ack").get_json()
    check(detail["etag"] == stored["_etag"], "the detail does not carry the current version")
    container.seed(dict(container.items["log-ack"]))
    response = client.patch("/api/safety/logs/log-ack", json={"status": "Dismissed", "etag": detail["etag"]})
    check(response.status_code == 409 and response.get_json()["code"] == "record_changed", str(response.get_json()))
    check(container.items["log-ack"]["status"] == "Resolved", "a refused save was written")

    # Archiving merges only its own fields, so a concurrent acknowledgment survives it too.
    container.seed({**BASE, "id": "log-archive", "action": "WarnUser", "action_request_status": "executed",
                    "warning_requires_acknowledgment": True, "warning_acknowledged_at": None})

    def acknowledges_archive(store):
        item = dict(store.items["log-archive"])
        item["warning_acknowledged_at"] = "2026-10-04T10:00:00+00:00"
        store.seed(item)

    container.before_replace = acknowledges_archive
    response = client.patch("/api/safety/logs/log-archive/archive", json={"archived": True})
    check(response.status_code == 200, str(response.get_json()))
    stored = container.items["log-archive"]
    check(stored["is_archived"] is True and stored["warning_acknowledged_at"] == "2026-10-04T10:00:00+00:00", str(stored))

    # Feedback review saves are conditional in the same way.
    f = build_feedback_app(stack)
    fclient, feedback = f.client, f.container
    sign_in(fclient, "reviewer-1", roles=("Admin",), name="Riley Reviewer")
    feedback.seed({"id": "fb-1", "userId": "user-1", "prompt": "Why?", "aiResponse": "Because.",
                   "feedbackType": "Negative", "timestamp": "2026-10-01T00:00:00", "adminReview": {"acknowledged": False}})

    def concurrent_archive(store):
        item = dict(store.items["fb-1"])
        item["is_archived"] = True
        store.seed(item)

    feedback.before_replace = concurrent_archive
    response = fclient.patch("/feedback/review/fb-1", json={"acknowledged": True, "analysisNotes": "Looked."})
    check(response.status_code == 200, str(response.get_json()))
    stored = feedback.items["fb-1"]
    check(stored["is_archived"] is True and stored["adminReview"]["acknowledged"] is True, str(stored))
    check(stored["adminReview"]["analyzedBy"] == {"id": "reviewer-1", "displayName": "Riley Reviewer"}, str(stored["adminReview"]))
    check(response.get_json()["etag"] == stored["_etag"], "the save does not return the new version")
    response = fclient.patch("/feedback/review/fb-1", json={"analysisNotes": "Stale.", "etag": "an-old-version"})
    check(response.status_code == 409 and response.get_json()["code"] == "record_changed", str(response.get_json()))
    check(feedback.items["fb-1"]["adminReview"]["analysisNotes"] == "Looked.", "a refused feedback save was written")

print("PASS: review saves never overwrite a newer version")
'''


def _run(probe, first_import, optimized, marker):
    command = [sys.executable, "-B"]
    if optimized:
        command.append("-O")
    result = subprocess.run(
        command + ["-c", probe, str(ROOT), first_import],
        capture_output=True,
        text=True,
        timeout=240,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert marker in result.stdout


@pytest.mark.parametrize("first_import", ["functions_approvals", "route_backend_safety"])
@pytest.mark.parametrize("optimized", [False, True])
def test_denied_and_expired_requests_unlock_their_violation(first_import, optimized):
    _run(DECISION_PROBE, first_import, optimized, "PASS: denied and expired remediation requests unlock their violation")


@pytest.mark.parametrize("optimized", [False, True])
def test_unchanged_restrictions_are_not_requested_twice(optimized):
    _run(REISSUE_PROBE, "route_backend_safety", optimized, "PASS: an unchanged suspension or block is not requested twice")


@pytest.mark.parametrize("optimized", [False, True])
def test_review_saves_never_overwrite_a_newer_version(optimized):
    _run(ETAG_PROBE, "route_backend_safety", optimized, "PASS: review saves never overwrite a newer version")


def test_deny_releases_safety_requests_before_notifying():
    """deny_request settles the violation for every safety request type, and never raises for it."""
    source = (APP_DIR / "functions_approvals.py").read_text(encoding="utf-8")
    assert "if approval.get('request_type') in SAFETY_USER_APPROVAL_TYPES:\n            _release_denied_safety_request(approval, auto_denied)" in source.replace("\r\n", "\n")
    assert "SAFETY_REQUEST_EXPIRED if auto_denied else SAFETY_REQUEST_DENIED" in source


def test_version():
    assert_app_version_at_least("0.261.298")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
