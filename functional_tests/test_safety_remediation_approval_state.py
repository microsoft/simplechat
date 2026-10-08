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
   re-issue it, whatever the request's state; changing the action does request it.
3. Review saves are ETag-conditional: a save never overwrites a user's concurrent
   acknowledgment, and a save that names a version the record no longer has is refused
   with 409 record_changed. Feedback review saves behave the same way.

It also pins what happens when saves overlap. A suspension or block is recorded only on
the violation as its save read it: when another save sends a warning, claims the violation
to send one, or creates another request while the request is being created, the save is
refused with 409 record_changed and its request is withdrawn, leaving one consistent request
and nothing approvable that the violation doesn't wait on. A save that stopped while sending
a warning can't record it over a later request. Should withdrawing fail, approving the
request changes nothing. A save that names the version it read is never retried onto a
newer version -- for PATCH, archive and bulk update and archive, feedback and safety alike --
while one that doesn't is merged and keeps the other save's change.

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
import ast
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


def refused_as_changed(response):
    body = response.get_json() or {}
    return response.status_code == 409 and body.get("code") == "record_changed"


def lands_meanwhile(store, record_id, **changes):
    """Another save of this record lands just before the next write, as a newer version."""
    def hook(target):
        record = dict(target.items[record_id])
        record.update(changes)
        target.seed(record)
    store.before_replace = hook
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
    check('select "Request this block again"' in body["message"], body["message"])

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

    # A suspension that was approved but could not be applied is requested again only on
    # purpose, with the new restore time and message.
    container.seed({**BASE, "id": "log-failed", "action": "SuspendUser", "action_request_status": "failed",
                    "action_request_id": "approval-seeded-4", "action_datetime_to_allow": UNTIL})
    later = (NOW + timedelta(days=30)).isoformat()
    response = client.patch("/api/safety/logs/log-failed", json={
        "action": "SuspendUser", "notification_message": "New message.", "datetime_to_allow": later,
    })
    body = response.get_json()
    check(response.status_code == 200 and body.get("remediation_unchanged") is True, str(body))
    check(body.get("remediation_status") == "failed" and len(h.approvals) == 3, str(body))
    response = client.patch("/api/safety/logs/log-failed", json={
        "action": "SuspendUser", "reissue": True, "notification_message": "New message.", "datetime_to_allow": later,
    })
    check(response.status_code == 200 and response.get_json().get("approval_required") is True, str(response.get_json()))
    request = h.approvals[3]["metadata"]
    check(request["datetime_to_allow"] == later and request["notification_message"] == "New message.", str(request))
    stored = container.items["log-failed"]
    check(stored["action_request_status"] == "pending" and stored["action_datetime_to_allow"] == later, str(stored))

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


OVERLAP_PROBE = PROBE_HEADER + r'''
with offline_app_imports(), ExitStack() as stack:
    importlib.import_module(sys.argv[2])
    import functions_safety_remediation as remediation
    import route_backend_safety as routes

    h = build_safety_app(stack)
    client, container, store = h.client, h.container, h.approvals_container
    other = h.new_client()
    sign_in(client, "reviewer-1", roles=("Admin",))
    sign_in(other, "reviewer-2", roles=("Admin",))
    UNTIL = (NOW + timedelta(days=7)).isoformat()
    SUSPEND = {"status": "In-Review", "action": "SuspendUser", "notification_message": "Suspended.", "datetime_to_allow": UNTIL}
    BLOCK = {"status": "In-Review", "action": "BlockUser", "notification_message": "Blocked."}
    WARN = {"status": "In-Review", "action": "WarnUser", "notification_message": "Please stop."}
    during = {}

    def violation(log_id, **fields):
        container.seed({**BASE, "id": log_id, "user_id": f"user-{log_id}", "status": "New", "action": "None", **fields})

    def approvable(log_id):
        """Pending requests raised from this violation: what a reviewer could still approve."""
        return sorted(
            item["id"] for item in store.items.values()
            if item["status"] == "pending" and (item.get("metadata") or {}).get("safety_log_id") == log_id
        )

    def withdrawn(approval_id):
        item = store.items[approval_id]
        return (
            item["status"] == "denied"
            and item["approved_by_id"] == "reviewer-1"
            and item["approval_comment"] == routes.SAFETY_REQUEST_WITHDRAWN_COMMENT
        )

    def refused_and_withdrawn(response):
        check(refused_as_changed(response), f"the suspension save: {response.status_code} {response.get_json()}")
        check(response.get_json()["error"] == routes.SAFETY_REQUEST_NOT_RECORDED_MESSAGE, str(response.get_json()))
        request_id = response_request_ids[-1]
        check(withdrawn(request_id), f"the request was not withdrawn: {store.items[request_id]}")
        return request_id

    response_request_ids = []

    def created_then(action):
        """Run ``action`` just after the next request is created, before its save records it."""
        def hook():
            response_request_ids.append(h.approvals[-1]["id"])
            action()
        h.before_approval_recorded = hook

    # 1. A warning is saved while a suspension request is being created. The warning is sent
    # and recorded; the suspension save is refused, and its request withdrawn with the notices
    # it sent, so the requester and reviewers are left with nothing to act on.
    violation("log-warn")
    created_then(lambda: during.__setitem__("warn", other.patch("/api/safety/logs/log-warn", json=WARN)))
    response = client.patch("/api/safety/logs/log-warn", json=SUSPEND)
    check(during["warn"].status_code == 200, f"the warning: {during['warn'].get_json()}")
    request_id = refused_and_withdrawn(response)
    stored = container.items["log-warn"]
    check(stored["action"] == "WarnUser" and stored["action_request_status"] == "executed", str(stored))
    check(stored.get("action_request_id") is None and stored["warning_notification_id"], str(stored))
    check(not approvable("log-warn"), approvable("log-warn"))
    check(remediation.count_pending_safety_warnings("user-log-warn") == 1, "the warning sent is not the user's to acknowledge")
    cleared = [entry["notification_types"] for entry in h.cleared_notifications
               if entry["metadata_filters"] == {"approval_id": request_id}]
    check(["approval_request_pending"] in cleared and ["approval_request_pending_submitter"] in cleared, str(cleared))
    check(not h.decision_notifications, f"withdrawing notified someone: {h.decision_notifications}")

    # 2. The narrowest interleaving: the warning's save claims the violation while the request
    # is being created, and records its send only after the suspension save has finished.
    violation("log-claim")
    claim = {}

    def claim_meanwhile():
        record = dict(container.items["log-claim"])
        record.update({"action": "WarnUser", "status": "In-Review"})
        claim["record"], claim["id"] = remediation.claim_safety_warning_send(record)

    created_then(claim_meanwhile)
    response = client.patch("/api/safety/logs/log-claim", json=SUSPEND)
    refused_and_withdrawn(response)
    stored = container.items["log-claim"]
    check(stored["action_request_status"] == "sending" and stored["warning_send_claim_id"] == claim["id"],
          f"the suspension save overwrote the claim: {stored}")
    recorded = remediation.record_safety_warning_send(
        claim["record"], claim["id"],
        remediation.build_safety_action_execution_updates("WarnUser", {"notification_id": "notification-late"}),
    )
    check(recorded is not None, "the warning could not be recorded after the suspension save")
    stored = container.items["log-claim"]
    check(stored["action"] == "WarnUser" and stored["action_request_status"] == "executed", str(stored))
    check(stored.get("action_request_id") is None and not approvable("log-claim"), str(stored))

    # The same when the suspension save names the version it read, as the V2 editor does.
    violation("log-claim-etag")
    etag = client.get("/api/safety/logs/log-claim-etag").get_json()["etag"]

    def claim_named_meanwhile():
        record = dict(container.items["log-claim-etag"])
        record["action"] = "WarnUser"
        claim["record"], claim["id"] = remediation.claim_safety_warning_send(record)

    created_then(claim_named_meanwhile)
    response = client.patch("/api/safety/logs/log-claim-etag", json={**SUSPEND, "etag": etag})
    refused_and_withdrawn(response)
    check(container.items["log-claim-etag"]["warning_send_claim_id"] == claim["id"], "the claim was overwritten")

    # 3. Two suspension or block saves at once: one request is recorded and stays approvable;
    # the other is withdrawn, so no request is left that the violation doesn't wait on.
    violation("log-two")
    created_then(lambda: during.__setitem__("block", other.patch("/api/safety/logs/log-two", json=BLOCK)))
    response = client.patch("/api/safety/logs/log-two", json=SUSPEND)
    check(during["block"].status_code == 200 and during["block"].get_json()["approval_required"] is True,
          str(during["block"].get_json()))
    suspension_request = refused_and_withdrawn(response)
    block_request = h.approvals[-1]["id"]
    check(block_request != suspension_request, "the two saves shared a request")
    stored = container.items["log-two"]
    check(stored["action"] == "BlockUser" and stored["action_request_status"] == "pending", str(stored))
    check(stored["action_request_id"] == block_request and approvable("log-two") == [block_request], str(stored))
    check(stored["action_notification_message"] == "Blocked.", "the request recorded is not the one that stayed")

    # 4. Another reviewer's notes land while the request is created. A save that names the
    # version it read is refused and requests nothing; one that doesn't keeps their notes.
    violation("log-notes")
    etag = client.get("/api/safety/logs/log-notes").get_json()["etag"]

    def notes_meanwhile(log_id):
        record = dict(container.items[log_id])
        record["notes"] = "Another reviewer's notes."
        container.seed(record)

    created_then(lambda: notes_meanwhile("log-notes"))
    response = client.patch("/api/safety/logs/log-notes", json={**SUSPEND, "etag": etag})
    refused_and_withdrawn(response)
    stored = container.items["log-notes"]
    check(stored["notes"] == "Another reviewer's notes." and stored["action"] == "None", str(stored))
    check(not stored.get("action_request_status") and not approvable("log-notes"), str(stored))

    violation("log-merge", notes="Before.")
    created_then(lambda: notes_meanwhile("log-merge"))
    response = client.patch("/api/safety/logs/log-merge", json={"action": "BlockUser", "notification_message": "Blocked."})
    check(response.status_code == 200 and response.get_json()["approval_required"] is True, str(response.get_json()))
    stored = container.items["log-merge"]
    check(stored["notes"] == "Another reviewer's notes." and stored["action"] == "BlockUser", str(stored))
    check(stored["action_request_status"] == "pending" and approvable("log-merge") == [stored["action_request_id"]], str(stored))

    # 5. A save that stopped while sending a warning can't record it over a request created
    # after its claim went stale, even when the request is merged onto a fresh read.
    stale_at = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    violation("log-stale", action="WarnUser", action_request_status="sending",
              warning_send_claim_id="stale-claim", warning_send_claimed_at=stale_at)
    stale_copy = dict(container.items["log-stale"])
    lands_meanwhile(container, "log-stale", notes="A newer version.")
    response = client.patch("/api/safety/logs/log-stale", json=SUSPEND)
    check(response.status_code == 200 and response.get_json()["approval_required"] is True, str(response.get_json()))
    late = remediation.record_safety_warning_send(
        stale_copy, "stale-claim", remediation.build_safety_action_execution_updates("WarnUser", {"notification_id": "n"}),
    )
    check(late is None, f"a stopped save recorded its warning over the request: {late}")
    stored = container.items["log-stale"]
    check(stored["action_request_status"] == "pending" and stored.get("warning_send_claim_id") is None, str(stored))
    check(stored["action_request_id"] == h.approvals[-1]["id"] and stored["notes"] == "A newer version.", str(stored))

    # 6. Should withdrawing fail, the request stays pending, but approving it changes nothing:
    # the Control Center carries out only the request a violation waits on.
    violation("log-orphan")

    def warn_then_break_the_store():
        during["orphan"] = other.patch("/api/safety/logs/log-orphan", json=WARN)
        store.fail_writes = True

    created_then(warn_then_break_the_store)
    response = client.patch("/api/safety/logs/log-orphan", json=SUSPEND)
    store.fail_writes = False
    check(refused_as_changed(response), str(response.get_json()))
    orphan_request = response_request_ids[-1]
    check(store.items[orphan_request]["status"] == "pending", "withdrawing was expected to fail here")

    source = (root / "application" / "single_app" / "route_backend_control_center.py").read_text(encoding="utf-8")
    registrar = next(node for node in ast.parse(source).body
                     if isinstance(node, ast.FunctionDef) and node.name == "register_route_backend_control_center")
    executor = next(node for node in registrar.body
                    if isinstance(node, ast.FunctionDef) and node.name == "_execute_safety_violation_request")
    carried_out = []

    def execute_safety_violation_action(**kwargs):
        carried_out.append(kwargs["safety_log"]["id"])
        return {"success": True, "message": "Done."}

    namespace = {
        "get_safety_log_item": remediation.get_safety_log_item,
        "safety_log_awaits_request": remediation.safety_log_awaits_request,
        "SAFETY_REQUEST_NOT_CURRENT_MESSAGE": remediation.SAFETY_REQUEST_NOT_CURRENT_MESSAGE,
        "execute_safety_violation_action": execute_safety_violation_action,
        "build_safety_action_execution_updates": remediation.build_safety_action_execution_updates,
        "update_safety_log_action_state": remediation.update_safety_log_action_state,
    }
    exec(compile(ast.Module(body=[executor], type_ignores=[]), "safety-executor", "exec"), namespace)
    execute = namespace["_execute_safety_violation_request"]

    before = dict(container.items["log-orphan"])
    result = execute(dict(store.items[orphan_request]), "approver-1", "approver@contoso.test", "Approver One")
    check(result == {"success": False, "message": remediation.SAFETY_REQUEST_NOT_CURRENT_MESSAGE}, str(result))
    check(not carried_out and container.items["log-orphan"]["_etag"] == before["_etag"], "the orphaned request was carried out")
    check(not h.access_writes, f"the user's access was changed: {h.access_writes}")

    # The request a violation does wait on is still carried out and recorded.
    result = execute(dict(store.items[block_request]), "approver-1", "approver@contoso.test", "Approver One")
    check(result["success"] is True and carried_out == ["log-two"], str(result))
    stored = container.items["log-two"]
    check(stored["action_request_status"] == "executed" and stored["action_request_id"] == block_request, str(stored))

print("PASS: overlapping saves leave one consistent request and nothing orphaned")
'''


VERSION_PROBE = PROBE_HEADER + r'''
with offline_app_imports(), ExitStack() as stack:
    importlib.import_module(sys.argv[2])
    h = build_safety_app(stack)
    client, container = h.client, h.container
    sign_in(client, "reviewer-1", roles=("Admin",))

    def etag_of(log_id):
        return client.get(f"/api/safety/logs/{log_id}").get_json()["etag"]

    def bulk_result(path, operation, http=None):
        response = (http or client).post(path, json={"operations": [operation]})
        check(response.status_code == 200, str(response.get_json()))
        return response.get_json()["results"][0]

    # A save that names the version it read is refused when another save lands between its
    # read and its write, and writes nothing.
    container.seed({**BASE, "id": "log-a", "status": "New", "action": "None", "notes": "Original."})
    etag = etag_of("log-a")
    lands_meanwhile(container, "log-a", notes="Reviewer B's notes.", status="Dismissed")
    response = client.patch("/api/safety/logs/log-a", json={"status": "Resolved", "notes": "Reviewer A's notes.", "etag": etag})
    check(refused_as_changed(response), f"{response.status_code} {response.get_json()}")
    stored = container.items["log-a"]
    check(stored["notes"] == "Reviewer B's notes." and stored["status"] == "Dismissed", f"a refused save was merged: {stored}")

    # Without a version, only what the save changes is written, so the other save's notes stay.
    lands_meanwhile(container, "log-a", notes="Reviewer C's notes.")
    response = client.patch("/api/safety/logs/log-a", json={"status": "Resolved"})
    check(response.status_code == 200, str(response.get_json()))
    stored = container.items["log-a"]
    check(stored["status"] == "Resolved" and stored["notes"] == "Reviewer C's notes.", str(stored))

    # Archive, the same way.
    etag = etag_of("log-a")
    lands_meanwhile(container, "log-a", notes="Later notes.")
    response = client.patch("/api/safety/logs/log-a/archive", json={"archived": True, "etag": etag})
    check(refused_as_changed(response), f"{response.status_code} {response.get_json()}")
    check(not container.items["log-a"].get("is_archived"), "a refused archive was merged")
    lands_meanwhile(container, "log-a", notes="Even later notes.")
    response = client.patch("/api/safety/logs/log-a/archive", json={"archived": True})
    check(response.status_code == 200 and container.items["log-a"]["is_archived"] is True, str(response.get_json()))
    check(container.items["log-a"]["notes"] == "Even later notes.", "archiving dropped the other save's change")

    # Bulk update and archive, with versions.
    container.seed({**BASE, "id": "log-b", "status": "New", "action": "None"})
    etag = etag_of("log-b")
    lands_meanwhile(container, "log-b", notes="B.")
    result = bulk_result("/api/safety/logs/bulk", {"id": "log-b", "op": "update", "changes": {"status": "Resolved"}, "etag": etag})
    check(result["ok"] is False and result["status"] == 409 and result["code"] == "record_changed", str(result))
    check(container.items["log-b"]["status"] == "New", "a refused bulk update was merged")
    etag = etag_of("log-b")
    lands_meanwhile(container, "log-b", notes="B again.")
    result = bulk_result("/api/safety/logs/bulk", {"id": "log-b", "op": "archive", "archived": True, "etag": etag})
    check(result["ok"] is False and result["code"] == "record_changed", str(result))
    check(not container.items["log-b"].get("is_archived"), "a refused bulk archive was merged")
    lands_meanwhile(container, "log-b", notes="B once more.")
    result = bulk_result("/api/safety/logs/bulk", {"id": "log-b", "op": "update", "changes": {"status": "Resolved"}})
    check(result["ok"] is True and container.items["log-b"]["status"] == "Resolved", str(result))
    check(container.items["log-b"]["notes"] == "B once more.", "a bulk update dropped the other save's change")

    # An archive that would land on a warning being sent waits for it instead.
    container.seed({**BASE, "id": "log-c", "status": "New", "action": "None"})
    lands_meanwhile(container, "log-c", action_request_status="sending", warning_send_claim_id="claim-1",
                    warning_send_claimed_at=datetime.now(timezone.utc).isoformat())
    response = client.patch("/api/safety/logs/log-c/archive", json={"archived": True})
    check(response.status_code == 409 and response.get_json()["code"] == "safety_warning_in_progress", str(response.get_json()))
    check(not container.items["log-c"].get("is_archived") and container.items["log-c"]["warning_send_claim_id"] == "claim-1",
          "the archive landed on the warning being sent")

    # Feedback: PATCH, archive and bulk update and archive.
    f = build_feedback_app(stack)
    fclient, feedback = f.client, f.container
    sign_in(fclient, "reviewer-1", roles=("Admin",), name="Riley Reviewer")
    feedback.seed({"id": "fb-1", "userId": "user-1", "prompt": "Why?", "aiResponse": "Because.", "feedbackType": "Negative",
                   "timestamp": "2026-10-01T00:00:00", "adminReview": {"acknowledged": False, "analysisNotes": "Original."}})

    def feedback_etag():
        return fclient.get("/feedback/review/fb-1").get_json()["etag"]

    def notes_meanwhile(text):
        def hook(target):
            record = dict(target.items["fb-1"])
            record["adminReview"] = {**record["adminReview"], "analysisNotes": text}
            target.seed(record)
        feedback.before_replace = hook

    etag = feedback_etag()
    notes_meanwhile("Reviewer B's notes.")
    response = fclient.patch("/feedback/review/fb-1", json={"analysisNotes": "Reviewer A's notes.", "etag": etag})
    check(refused_as_changed(response), f"{response.status_code} {response.get_json()}")
    check(feedback.items["fb-1"]["adminReview"]["analysisNotes"] == "Reviewer B's notes.", "a refused feedback save was merged")

    notes_meanwhile("Reviewer C's notes.")
    response = fclient.patch("/feedback/review/fb-1", json={"acknowledged": True})
    check(response.status_code == 200, str(response.get_json()))
    review = feedback.items["fb-1"]["adminReview"]
    check(review["acknowledged"] is True and review["analysisNotes"] == "Reviewer C's notes.", str(review))

    etag = feedback_etag()
    notes_meanwhile("Archive race.")
    response = fclient.patch("/feedback/review/fb-1/archive", json={"archived": True, "etag": etag})
    check(refused_as_changed(response), f"{response.status_code} {response.get_json()}")
    check(not feedback.items["fb-1"].get("is_archived"), "a refused feedback archive was merged")

    etag = feedback_etag()
    notes_meanwhile("Bulk race.")
    result = bulk_result("/feedback/review/bulk", {"id": "fb-1", "op": "update", "changes": {"actionTaken": "Fixed."}, "etag": etag}, fclient)
    check(result["ok"] is False and result["code"] == "record_changed", str(result))
    check(feedback.items["fb-1"]["adminReview"].get("actionTaken") is None, "a refused bulk feedback update was merged")
    etag = feedback_etag()
    notes_meanwhile("Bulk archive race.")
    result = bulk_result("/feedback/review/bulk", {"id": "fb-1", "op": "archive", "archived": True, "etag": etag}, fclient)
    check(result["ok"] is False and result["code"] == "record_changed", str(result))
    check(not feedback.items["fb-1"].get("is_archived"), "a refused bulk feedback archive was merged")

print("PASS: a save that names its version is never retried onto a newer one")
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


@pytest.mark.parametrize("first_import", ["functions_approvals", "route_backend_safety"])
@pytest.mark.parametrize("optimized", [False, True])
def test_overlapping_saves_leave_one_consistent_request(first_import, optimized):
    _run(OVERLAP_PROBE, first_import, optimized, "PASS: overlapping saves leave one consistent request and nothing orphaned")


@pytest.mark.parametrize("optimized", [False, True])
def test_a_named_version_is_never_retried_onto_a_newer_one(optimized):
    _run(VERSION_PROBE, "route_backend_safety", optimized, "PASS: a save that names its version is never retried onto a newer one")


def test_deny_releases_safety_requests_before_notifying():
    """deny_request settles the violation for every safety request type, and never raises for it."""
    source = (APP_DIR / "functions_approvals.py").read_text(encoding="utf-8")
    assert "if approval.get('request_type') in SAFETY_USER_APPROVAL_TYPES:\n            _release_denied_safety_request(approval, auto_denied)" in source.replace("\r\n", "\n")
    assert "SAFETY_REQUEST_EXPIRED if auto_denied else SAFETY_REQUEST_DENIED" in source


def test_version():
    assert_app_version_at_least("0.261.298")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
