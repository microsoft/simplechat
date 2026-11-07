#!/usr/bin/env python3
# test_safety_warning_send_claim.py
"""
Functional test for sending a safety warning exactly once when saves overlap.
Version: 0.261.297
Implemented in: 0.261.297

This test ensures that a reviewer's save claims the violation, with a write conditional on
the version it read, before it sends a warning; that of two overlapping saves -- a
double-click, or two reviewers -- only one sends, and the other is refused with 409
safety_warning_in_progress and sends nothing; that while a warning is being sent, other
saves and deletes wait, and the violation never counts as a warning to acknowledge; that a
claim left by a save that never finished stops blocking after its time to live, reads as a
failed send, and is retried by only one of two saves; and that a send whose claim was lost
is reported and audited rather than recorded over another writer. Real modules run in fresh
processes with network access blocked, under normal and optimized Python.
"""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "application" / "single_app"
sys.path.insert(0, str(ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402


CLAIM_PROBE = r'''
import importlib
import sys
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path

root = Path(sys.argv[1])
sys.path.insert(0, str(root / "functional_tests"))
sys.path.insert(0, str(root / "application" / "single_app"))
from azure.cosmos import exceptions as cosmos_exceptions
from test_support.offline_bootstrap import offline_app_imports
from test_support.safety_review_harness import build_safety_app, check, sign_in

WARN = {"status": "In-Review", "action": "WarnUser", "notes": "Warned.", "notification_message": "Please stop."}

with offline_app_imports(), ExitStack() as stack:
    importlib.import_module(sys.argv[2])
    import functions_safety_remediation as remediation
    import route_backend_safety as routes

    CLAIM_FIELDS = remediation.SAFETY_WARNING_SEND_CLAIM_FIELDS
    h = build_safety_app(stack)
    client, container = h.client, h.container
    other = h.new_client()
    warned_user = h.new_client()
    sign_in(client, "reviewer-1", roles=("Admin",))
    sign_in(other, "reviewer-2", roles=("Admin",))
    sign_in(warned_user, "user-1")
    base = {"status": "New", "action": "None", "created_at": "2026-10-01T00:00:00", "message": "Flagged text",
            "user_id": "user-1", "triggered_categories": [{"category": "Hate", "severity": 4}]}

    def sent_for(log_id):
        return [item for item in h.notifications if item["metadata"]["safety_log_id"] == log_id]

    def audited_for(log_id):
        return [item for item in h.audits if item["additional_context"]["record_id"] == log_id]

    def listed(log_id):
        logs = other.get("/api/safety/logs?page=1&page_size=100").get_json()["logs"]
        return {row["id"]: row for row in logs}[log_id]

    def unclaimed(record):
        return not any(field in record for field in CLAIM_FIELDS)

    def refused_in_progress(response):
        body = response.get_json() or {}
        return response.status_code == 409 and body.get("code") == "safety_warning_in_progress"

    # 1. Two saves read the same version (a double-click, or two reviewers). The one that
    # claims the violation first sends the warning; the other sends nothing.
    container.seed({**base, "id": "log-race"})
    overlapping = {}

    def overlapping_save(store):
        overlapping["response"] = other.patch("/api/safety/logs/log-race", json=WARN)

    container.before_replace = overlapping_save
    response = client.patch("/api/safety/logs/log-race", json=WARN)
    check(overlapping["response"].status_code == 200, f"the first save failed: {overlapping['response'].get_json()}")
    check(refused_in_progress(response), f"the overlapping save: {response.status_code} {response.get_json()}")
    check(response.get_json()["error"] == routes.SAFETY_WARNING_CLAIM_CONFLICT_MESSAGE, str(response.get_json()))
    check(len(sent_for("log-race")) == 1, f"expected one warning, sent {len(sent_for('log-race'))}")
    stored = container.items["log-race"]
    check(stored["action_request_status"] == "executed" and unclaimed(stored), str(stored))
    check(stored["warning_notification_id"] == sent_for("log-race")[0]["id"], str(stored))
    audits = audited_for("log-race")
    check(len(audits) == 1 and audits[0]["admin_user_id"] == "reviewer-2", str(audits))

    # 2. While a warning is being sent, the violation is claimed and waits: other saves and
    # deletes are refused, and it never counts as a warning to acknowledge -- even when it
    # still holds the fields of a warning sent and withdrawn before.
    container.seed({**base, "id": "log-busy", "action_request_status": "executed",
                    "warning_requires_acknowledgment": True, "warning_acknowledged_at": None,
                    "warning_issued_at": "2026-10-02T09:00:00+00:00", "warning_message": "Earlier."})
    during = {}

    def while_sending():
        record = container.items["log-busy"]
        during["record"] = dict(record)
        during["warn"] = other.patch("/api/safety/logs/log-busy", json=WARN)
        during["notes"] = other.patch("/api/safety/logs/log-busy", json={
            "status": "Dismissed", "action": "None", "notes": "Changed my mind.",
        })
        during["delete"] = other.delete("/api/safety/logs/log-busy")
        during["count"] = remediation.count_pending_safety_warnings("user-1")
        during["pending"] = warned_user.get("/api/safety/warnings/pending").get_json()["warnings"]
        during["ack"] = warned_user.post("/api/safety/warnings/log-busy/acknowledge", json={})
        during["listed"] = listed("log-busy")

    h.before_notification = while_sending
    count_before = remediation.count_pending_safety_warnings("user-1")
    response = client.patch("/api/safety/logs/log-busy", json=WARN)
    check(response.status_code == 200, f"the send failed: {response.get_json()}")
    claimed = during["record"]
    check(claimed["action_request_status"] == "sending" and claimed["action"] == "WarnUser", str(claimed))
    check(all(claimed.get(field) for field in CLAIM_FIELDS), f"no claim before sending: {claimed}")
    check(claimed["notes"] == "Warned.", "the claim did not store the review")
    for key in ("warn", "notes", "delete"):
        check(refused_in_progress(during[key]), f"{key}: {during[key].status_code} {during[key].get_json()}")
    check(during["warn"].get_json()["error"] == routes.SAFETY_WARNING_SENDING_MESSAGE, str(during["warn"].get_json()))
    pending_ids = [warning["id"] for warning in during["pending"]]
    check(during["count"] == count_before and "log-busy" not in pending_ids, "a warning being sent counted as pending")
    check("c.action_request_status = 'executed'" in remediation._PENDING_WARNING_CONDITIONS, "count not scoped")
    check(during["ack"].status_code == 404, "a warning being sent was acknowledgeable")
    row = during["listed"]
    check(row["action_request_status"] == "sending" and row["warning_acknowledgment_status"] is None, str(row))
    check(unclaimed(row), "the claim was listed")
    stored = container.items["log-busy"]
    check(stored["action_request_status"] == "executed" and stored["notes"] == "Warned." and unclaimed(stored), str(stored))
    check(stored["warning_message"] == "Please stop." and stored["warning_acknowledged_at"] is None, str(stored))
    check(len(sent_for("log-busy")) == 1, "a refused save sent a warning")
    check(remediation.count_pending_safety_warnings("user-1") == count_before + 1, "the sent warning is not pending")

    # 3. A claim's time to live: a fresh claim blocks; an old, future or unreadable one does not.
    now = datetime.now(timezone.utc)
    sending = lambda claimed_at: {"action_request_status": "sending", "warning_send_claimed_at": claimed_at}
    check(remediation.safety_warning_send_in_progress(sending((now - timedelta(seconds=30)).isoformat()), now), "fresh")
    naive = (now - timedelta(seconds=5)).replace(tzinfo=None).isoformat()
    check(remediation.safety_warning_send_in_progress({**sending(naive), "action_request_status": "Sending"}, now), "naive")
    for claimed_at in ((now - timedelta(minutes=6)).isoformat(), (now + timedelta(minutes=6)).isoformat(), "soon", "", None):
        check(not remediation.safety_warning_send_in_progress(sending(claimed_at), now), f"{claimed_at!r} blocked")
        check(remediation.is_interrupted_safety_warning_send(sending(claimed_at), now), f"{claimed_at!r} not stale")
    executed = {"action_request_status": "executed", "warning_send_claimed_at": now.isoformat()}
    check(not remediation.safety_warning_send_in_progress(executed, now), "only 'sending' is a claim")
    check(not remediation.is_interrupted_safety_warning_send(executed, now), "only 'sending' is interrupted")

    container.seed({**base, "id": "log-fresh", "action": "WarnUser", "action_request_status": "sending",
                    "warning_send_claim_id": "another-save",
                    "warning_send_claimed_at": (now - timedelta(seconds=20)).isoformat()})
    response = client.patch("/api/safety/logs/log-fresh", json=WARN)
    check(refused_in_progress(response) and not sent_for("log-fresh"), f"a fresh claim: {response.get_json()}")
    check(container.items["log-fresh"]["warning_send_claim_id"] == "another-save", "a fresh claim was replaced")

    # 4. A claim left by a save that never finished reads as a failed send and stops blocking.
    # Two saves that retry it at once send it once.
    stale = (now - timedelta(minutes=10)).isoformat()
    container.seed({**base, "id": "log-stale", "action": "WarnUser", "action_request_status": "sending",
                    "warning_send_claim_id": "crashed-save", "warning_send_claimed_at": stale})
    row = listed("log-stale")
    check(row["action_request_status"] == "failed" and unclaimed(row), str(row))
    check(row["action_execution_error"] == remediation.SAFETY_WARNING_SEND_INTERRUPTED_MESSAGE, str(row))
    overlapping.clear()

    def overlapping_retry(store):
        overlapping["response"] = other.patch("/api/safety/logs/log-stale", json=WARN)

    container.before_replace = overlapping_retry
    response = client.patch("/api/safety/logs/log-stale", json=WARN)
    check(overlapping["response"].status_code == 200, f"a stale claim blocked: {overlapping['response'].get_json()}")
    check(refused_in_progress(response), f"the second retry: {response.status_code} {response.get_json()}")
    check(len(sent_for("log-stale")) == 1, f"a stale claim was retried {len(sent_for('log-stale'))} times")
    stored = container.items["log-stale"]
    check(stored["action_request_status"] == "executed" and unclaimed(stored), str(stored))
    check(stored["warning_requires_acknowledgment"] is True and stored["action_execution_error"] is None, str(stored))

    # A stale claim is also cleared by a save that doesn't warn, as a failed send.
    container.seed({**base, "id": "log-stale-none", "action": "WarnUser", "action_request_status": "sending",
                    "warning_send_claim_id": "crashed-save", "warning_send_claimed_at": "not a time"})
    response = client.patch("/api/safety/logs/log-stale-none", json={"status": "Dismissed", "action": "None"})
    check(response.status_code == 200, f"a stale claim blocked a save: {response.get_json()}")
    stored = container.items["log-stale-none"]
    check(stored["action"] == "None" and stored["action_request_status"] == "failed" and unclaimed(stored), str(stored))
    check(not sent_for("log-stale-none"), "a save that doesn't warn sent a warning")

    # 5. A writer that keeps the claim -- archiving, which reads and writes the whole record --
    # is kept, and the warning is recorded on its version.
    container.seed({**base, "id": "log-archived"})

    def archive_meanwhile():
        record = container.read_item("log-archived", "log-archived")
        record["is_archived"] = True
        container.upsert_item(record)

    h.before_notification = archive_meanwhile
    response = client.patch("/api/safety/logs/log-archived", json=WARN)
    check(response.status_code == 200, f"a concurrent archive failed the send: {response.get_json()}")
    stored = container.items["log-archived"]
    check(stored["is_archived"] is True and stored["action_request_status"] == "executed" and unclaimed(stored), str(stored))
    check(stored["warning_notification_id"] == sent_for("log-archived")[0]["id"], str(stored))

    # 6. A writer that replaced the record without the claim, or deleted it, is never
    # overwritten. The warning was sent once, so it is audited and the reviewer is told.
    container.seed({**base, "id": "log-lost"})

    def overwrite_without_claim():
        record = container.read_item("log-lost", "log-lost")
        for field in CLAIM_FIELDS:
            record.pop(field)
        record.update({"action": "None", "action_request_status": None, "notes": "Another reviewer's save"})
        container.upsert_item(record)

    h.before_notification = overwrite_without_claim
    response = client.patch("/api/safety/logs/log-lost", json=WARN)
    body = response.get_json()
    check(response.status_code == 409 and body["code"] == "safety_warning_not_recorded", f"{response.status_code} {body}")
    check(body["error"] == routes.SAFETY_WARNING_NOT_RECORDED_MESSAGE and body["audit_logged"] is True, str(body))
    stored = container.items["log-lost"]
    check(stored["notes"] == "Another reviewer's save" and "warning_notification_id" not in stored, str(stored))
    check(len(sent_for("log-lost")) == 1 and len(audited_for("log-lost")) == 1, "not sent and audited once")

    container.seed({**base, "id": "log-deleted"})
    h.before_notification = lambda: container.delete_item("log-deleted", "log-deleted")
    response = client.patch("/api/safety/logs/log-deleted", json=WARN)
    check(response.status_code == 409 and response.get_json()["code"] == "safety_warning_not_recorded", "deleted")
    check("log-deleted" not in container.items and len(sent_for("log-deleted")) == 1, "a deleted record came back")

    # 7. When the outcome can't be written, the claim stays, so a quick retry can't send the
    # warning twice; it stops blocking once its time to live passes.
    container.seed({**base, "id": "log-unwritten"})

    def unavailable(store):
        raise cosmos_exceptions.CosmosHttpResponseError(status_code=503, message="Unavailable")

    h.before_notification = lambda: setattr(container, "before_replace", unavailable)
    response = client.patch("/api/safety/logs/log-unwritten", json=WARN)
    check(response.status_code == 500 and response.get_json()["code"] == "safety_warning_not_recorded", "503")
    check(container.items["log-unwritten"]["action_request_status"] == "sending", "the claim was dropped")
    check(refused_in_progress(client.patch("/api/safety/logs/log-unwritten", json=WARN)), "a quick retry was allowed")
    check(len(sent_for("log-unwritten")) == 1, "a quick retry sent the warning again")

    # 8. A send that fails releases its claim, so saving again retries it at once.
    container.seed({**base, "id": "log-failed"})
    h.fail_notifications = True
    response = client.patch("/api/safety/logs/log-failed", json=WARN)
    h.fail_notifications = False
    stored = container.items["log-failed"]
    check(response.status_code == 500 and stored["action_request_status"] == "failed" and unclaimed(stored), str(stored))
    check(stored["notes"] == "Warned.", "the rest of the review was not saved")
    response = client.patch("/api/safety/logs/log-failed", json=WARN)
    check(response.status_code == 200 and len(sent_for("log-failed")) == 1, f"retry: {response.get_json()}")

print("PASS: a safety warning is sent once when saves overlap")
'''


@pytest.mark.parametrize("first_import", ["functions_safety_remediation", "route_backend_safety"])
@pytest.mark.parametrize("optimized", [False, True])
def test_overlapping_saves_send_one_warning(first_import, optimized):
    command = [sys.executable, "-B"]
    if optimized:
        command.append("-O")
    result = subprocess.run(
        command + ["-c", CLAIM_PROBE, str(ROOT), first_import],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: a safety warning is sent once when saves overlap" in result.stdout


def test_classic_save_button_waits_for_its_request():
    """The classic review disables Save while its request is in flight."""
    script = (APP_DIR / "static" / "js" / "admin" / "admin-safety-violations.js").read_text(encoding="utf-8")
    assert "saveButton.disabled = true;" in script
    assert "}).finally(function () {\n                    saveButton.disabled = false;" in script.replace("\r\n", "\n")


def test_version():
    assert_app_version_at_least("0.261.297")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
