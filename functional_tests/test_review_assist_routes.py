#!/usr/bin/env python3
# test_review_assist_routes.py
"""
Functional test for the Review center AI assist routes and AI suggestion operations.
Version: 0.261.299
Implemented in: 0.261.299

This test ensures that POST /api/admin/review/feedback/assist and /api/admin/review/safety/assist
answer only a reviewer of that section while the Admin Settings toggle is on, refusing before any
record is read or any model or limiter is used otherwise; read records by id on the server and send
the model no user ids, emails or names, but a server-computed count of the user's earlier
violations; skip violations held by a pending remediation request or a warning being sent; retry a
content-filter refusal one record at a time; store triage suggestions on their records with an
ETag-conditional write, never cached, never echoing the organization guidance; count requests on a
limiter of their own, refunding requests that never reached the model; list pending suggestions,
stale ones flagged, through ai=pending; apply a suggestion only through the normal save, with the
reviewer's edits, crediting it in the audit log, so a warning is sent and a suspension still needs
a second reviewer; refuse stale and already-decided suggestions; dismiss suggestions; keep
suggestions and reviewer-only classifications out of what users read about themselves; and record
feedback themes for the dashboard. It also ensures that a triage never puts two users' records in
one model call and that "select all matching" says whose each record is; that the lists and the
single-record reads carry each record's version and fingerprint, so an editor's save still goes
ahead when only an AI suggestion was stored or dismissed meanwhile, but is refused with 409
record_changed when someone else edited the record, a warning is being sent, a new request was
made, the user acknowledged a warning, or a write lands between the read and the save; and that a
suggestion operation whose record can't be read fails on its own with operation_failed while the
rest of the bulk request runs. Real modules run in fresh processes with network access blocked,
under normal and optimized Python.
"""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402


PROBE_HEADER = r'''
import copy
import importlib
import json
import sys
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

root = Path(sys.argv[1])
sys.path.insert(0, str(root / "functional_tests"))
sys.path.insert(0, str(root / "application" / "single_app"))
from test_support.offline_bootstrap import offline_app_imports
from test_support.safety_review_harness import build_feedback_app, build_safety_app, check, sign_in, sign_out

NOW = datetime.now(timezone.utc).replace(tzinfo=None)
EARLIER = (NOW - timedelta(days=3)).isoformat()
RECENT = (NOW - timedelta(hours=3)).isoformat()
GUIDANCE = "SECRET-GUIDANCE-7731: warn on a first minor violation."
USER_EMAIL = "uma.user@contoso.test"
USER_NAME = "Uma Unique-Person"


class MemoryLimitStore:
    """The rate-limit store, in memory, with the compare-and-swap the Cosmos store has."""

    def __init__(self):
        from functions_workflow_assist_limits import AssistLimitConflict
        self.conflict = AssistLimitConflict
        self.docs = {}
        self.version = 0

    def read(self, document_id):
        doc = self.docs.get(document_id)
        return copy.deepcopy(doc) if doc else None

    def _store(self, document):
        self.version += 1
        self.docs[document["id"]] = {**copy.deepcopy(document), "_etag": str(self.version)}

    def create(self, document):
        if document["id"] in self.docs:
            raise self.conflict()
        self._store(document)

    def replace(self, document, etag):
        current = self.docs.get(document["id"])
        if current is None or current.get("_etag") != etag:
            raise self.conflict()
        self._store(document)


class Model:
    """A scripted model: answers each record by its handle, or as a test says."""

    def __init__(self, section):
        self.section = section
        self.calls = []
        self.answer = None

    def __call__(self, messages, timeout):
        self.calls.append(copy.deepcopy(messages))
        document = json.loads(messages[1]["content"])
        if self.answer is not None:
            return self.answer(document)
        return json.dumps({"suggestions": [self.suggest(view) for view in document["records"]]}), "stop"

    def suggest(self, view):
        if self.section == "feedback":
            return {
                "handle": view["handle"], "acknowledged": True, "analysisNotes": "The response missed the per diem rules.",
                "actionTaken": "", "responseToUser": "Thanks for the feedback.", "theme": "retrieval",
                "archive": False, "rationale": "The user named missing content.", "confidence": "medium",
            }
        if view["content_origin"] != "user":
            return {
                "handle": view["handle"], "status": "Dismissed", "action": "None", "notes": "An AI response finding.",
                "archive": True, "rationale": "Not the user's content.", "confidence": "high",
            }
        return {
            "handle": view["handle"], "status": "Resolved", "action": "WarnUser", "notes": "A hateful remark.",
            "notification_title": "Safety warning",
            "notification_message": "A message you sent broke the hate speech policy. Please keep messages respectful.",
            "archive": False, "rationale": "First clear breach.", "confidence": "high",
        }


def install_assistant(stack, section, max_requests=60):
    """Use the real runtime with a scripted model and a real limiter over an in-memory store."""
    import functions_review_assist_runtime as runtime
    from functions_workflow_assist_limits import WorkflowAssistLimiter

    model = Model(section)
    limit_store = MemoryLimitStore()
    limiter = WorkflowAssistLimiter(
        limit_store, max_requests=max_requests, document_type=runtime.REVIEW_ASSIST_LIMIT_DOCUMENT_TYPE,
    )
    built = []
    telemetry = []
    original = runtime.build_review_assist_services

    def build(*, store, client_factory, limiter=None, call_model=None):
        built.append(store)
        return original(store=store, client_factory=client_factory, limiter=assistant.limiter,
                        call_model=assistant.model)

    def record_log(message, extra=None, level=None, **kwargs):
        telemetry.append((message, copy.deepcopy(extra)))

    assistant = SimpleNamespace(model=model, limiter=limiter, limit_store=limit_store, built=built, telemetry=telemetry)
    stack.enter_context(patch.object(runtime, "build_review_assist_services", build))
    stack.enter_context(patch.object(runtime, "log_event", record_log))
    return assistant


def post_assist(client, section, body, **kwargs):
    if "data" in kwargs:
        return client.post(f"/api/admin/review/{section}/assist", **kwargs)
    return client.post(f"/api/admin/review/{section}/assist", json=body)


def closed(response, status, code=None):
    body = response.get_json(silent=True) or {}
    check(response.status_code == status, f"expected {status}, got {response.status_code}: {body}")
    if code is not None:
        check(body.get("code") == code, f"expected {code}: {body}")
    return body


def bulk(client, path, operations):
    response = client.post(path, json={"operations": operations})
    check(response.status_code == 200, str(response.get_json()))
    return {result["id"]: result for result in response.get_json()["results"]}
'''


FEEDBACK_PROBE = PROBE_HEADER + r'''
with offline_app_imports(), ExitStack() as stack:
    importlib.import_module(sys.argv[2])
    h = build_feedback_app(stack)
    assistant = install_assistant(stack, "feedback", max_requests=3)
    client, container = h.client, h.container
    h.user_docs["user-1"] = {"id": "user-1", "display_name": USER_NAME, "email": USER_EMAIL, "settings": {}}
    for index in (1, 2, 3):
        container.seed({
            "id": f"fb-{index}", "userId": "user-1", "conversationId": f"conv-{index}", "messageId": f"msg-{index}",
            "feedbackType": "Negative", "prompt": f"Policy question {index} from {USER_EMAIL}",
            "aiResponse": "An answer.", "reason": "Incomplete", "timestamp": RECENT,
            "adminReview": {"acknowledged": False},
        })
    h.settings["admin_review_ai_guidance"] = GUIDANCE

    # The toggle is off by default: refused before anything is read or counted.
    sign_in(client, "reviewer-1", roles=("Admin",), name="Rita Reviewer")
    body = closed(post_assist(client, "feedback", {"mode": "triage", "ids": ["fb-1"]}), 403, "review_assistant_disabled")
    check(assistant.built == [] and assistant.model.calls == [] and assistant.limit_store.docs == {}, "a disabled assistant did work")
    h.settings["enable_admin_review_ai_assistant"] = True

    # Only the section's reviewer role: the general Admin role is not enough once FeedbackAdmin is required.
    h.settings["require_member_of_feedback_admin"] = True
    closed(post_assist(client, "feedback", {"mode": "triage", "ids": ["fb-1"]}), 403)
    sign_in(client, "reviewer-1", roles=("User", "FeedbackAdmin"), name="Rita Reviewer")
    other = h.new_client()
    sign_in(other, "user-1", roles=("User",))
    closed(post_assist(other, "feedback", {"mode": "triage", "ids": ["fb-1"]}), 403)
    check(assistant.built == [] and assistant.model.calls == [], "a non-reviewer reached the assistant")

    # Strict JSON, bounded, refused unread.
    closed(post_assist(client, "feedback", None, data="fb-1", content_type="text/plain"), 400, "invalid_request")
    closed(post_assist(client, "feedback", None, data=b"{" + b" " * 20000 + b"}", content_type="application/json"), 413, "request_too_large")
    closed(post_assist(client, "feedback", {"mode": "triage", "ids": [f"fb-{i}" for i in range(11)]}), 400, "too_many_records")

    # Analyze: a suggestion for the editor's draft, nothing stored.
    response = post_assist(client, "feedback", {"mode": "analyze", "ids": ["fb-3"]})
    body = closed(response, 200)
    check(response.headers["Cache-Control"] == "no-store, private", "an assist answer was cacheable")
    check(body["results"][0]["suggestion"]["status"] == "unsaved", str(body))
    check("ai_suggestion" not in container.items["fb-3"], "analyze stored a suggestion")

    # Triage: stored on each record, identity never reaches the model.
    response = post_assist(client, "feedback", {"mode": "triage", "ids": ["fb-1", "fb-2", "fb-missing"]})
    body = closed(response, 200)
    outcomes = {entry["id"]: entry["outcome"] for entry in body["results"]}
    check(outcomes == {"fb-1": "suggested", "fb-2": "suggested", "fb-missing": "not_found"}, str(outcomes))
    for message in assistant.model.calls:
        dumped = json.dumps(message)
        for secret in ("user-1", USER_EMAIL, USER_NAME, "fb-1", "conv-1", "msg-1"):
            check(secret not in dumped, f"{secret} reached the model")
    check(GUIDANCE in json.loads(assistant.model.calls[-1][1]["content"])["organization_guidance"], "the guidance was not sent")
    check(GUIDANCE not in response.get_data(as_text=True), "the guidance was echoed to the browser")
    stored = container.items["fb-1"]["ai_suggestion"]
    check(stored["status"] == "pending" and len(stored["fingerprint"]) == 32, str(stored))
    check(stored["created_by"]["name"] == "Rita Reviewer", str(stored))
    check(body["results"][0]["suggestion"]["id"] == stored["id"] and "fingerprint" not in body["results"][0]["suggestion"], "presented badly")
    limit_docs = list(assistant.limit_store.docs)
    check(len(limit_docs) == 1 and limit_docs[0].startswith("admin_review_assist_rate_limit:"), str(limit_docs))
    check("reviewer-1" not in limit_docs[0], "the limiter document named the user")

    # The queue lists pending suggestions; a review saved meanwhile makes one stale.
    listed = client.get("/feedback/review?ai=pending&archive=all").get_json()["feedback"]
    check(sorted(item["id"] for item in listed) == ["fb-1", "fb-2"], str([item["id"] for item in listed]))
    check(all("fingerprint" not in item["ai_suggestion"] for item in listed), "the fingerprint left the server")
    matching = client.get("/feedback/review/ids?ai=pending").get_json()
    check(sorted(matching["ids"]) == ["fb-1", "fb-2"] and matching["total"] == 2, str(matching))
    response = client.patch("/feedback/review/fb-2", json={"acknowledged": True, "analysisNotes": "Handled by hand."})
    check(response.status_code == 200, str(response.get_json()))
    states = {item["id"]: item["ai_suggestion"]["status"] for item in client.get("/feedback/review?ai=pending").get_json()["feedback"]}
    check(states == {"fb-1": "pending", "fb-2": "stale"}, str(states))
    check(client.get("/feedback/review?ai=maybe").status_code == 400, "an unknown AI state was accepted")

    # Apply fb-1 with the reviewer's edit: the normal save, attributed, audited.
    fb1 = client.get("/feedback/review/fb-1").get_json()
    suggestion_id = fb1["ai_suggestion"]["id"]
    payload = fb1["ai_suggestion"]["payload"]
    changes = {key: payload[key] for key in ("acknowledged", "analysisNotes", "actionTaken", "responseToUser")}
    changes["theme"] = "accuracy"
    results = bulk(client, "/feedback/review/bulk", [
        {"id": "fb-1", "op": "update", "changes": changes, "suggestion_id": suggestion_id, "etag": fb1["etag"]},
        {"id": "fb-2", "op": "update", "changes": {"acknowledged": True}, "suggestion_id": container.items["fb-2"]["ai_suggestion"]["id"]},
    ])
    check(results["fb-1"]["ok"] and results["fb-1"]["suggestion"] == {"id": suggestion_id, "status": "applied", "edited": True}, str(results["fb-1"]))
    check(results["fb-2"]["status"] == 409 and results["fb-2"]["code"] == "suggestion_stale", str(results["fb-2"]))
    applied = container.items["fb-1"]
    check(applied["adminReview"]["theme"] == "accuracy" and applied["adminReview"]["acknowledged"] is True, str(applied["adminReview"]))
    check(applied["ai_suggestion"]["status"] == "applied" and applied["ai_suggestion"]["edited"] is True, str(applied["ai_suggestion"]))
    check(applied["ai_suggestion"]["applied_by"]["id"] == "reviewer-1", str(applied["ai_suggestion"]))
    check(h.notifications == [], "applying a feedback suggestion notified the user")
    audit = [entry for entry in h.audits if entry["action"] == "feedback_ai_suggestion_applied"]
    check(len(audit) == 1 and audit[0]["additional_context"]["suggestion_id"] == suggestion_id, str(h.audits))
    check(audit[0]["additional_context"]["edited"] is True, str(audit))
    again = bulk(client, "/feedback/review/bulk", [{"id": "fb-1", "op": "update", "changes": changes, "suggestion_id": suggestion_id}])
    check(again["fb-1"]["code"] == "suggestion_not_pending", str(again))

    # Dismissal: a stale suggestion can be dismissed; malformed operations are refused.
    fb2_suggestion = container.items["fb-2"]["ai_suggestion"]["id"]
    results = bulk(client, "/feedback/review/bulk", [
        {"id": "fb-2", "op": "dismiss_suggestion", "suggestion_id": fb2_suggestion},
        {"id": "fb-3", "op": "dismiss_suggestion"},
        {"id": "fb-x", "op": "archive", "archived": True, "suggestion_id": "a" * 32},
        {"id": "fb-y", "op": "dismiss_suggestion", "suggestion_id": "not-an-id"},
    ])
    check(results["fb-2"]["ok"] and container.items["fb-2"]["ai_suggestion"]["status"] == "dismissed", str(results["fb-2"]))
    for record_id in ("fb-3", "fb-x", "fb-y"):
        check(results[record_id]["code"] == "invalid_operation", str(results[record_id]))
    check(any(entry["action"] == "feedback_ai_suggestion_dismissed" for entry in h.audits), "the dismissal was not audited")
    check(client.get("/feedback/review?ai=pending").get_json()["feedback"] == [], "decided suggestions are still queued")

    # While AI assist is off, suggestion operations are refused; the rest of the request runs.
    h.settings["enable_admin_review_ai_assistant"] = False
    results = bulk(client, "/feedback/review/bulk", [
        {"id": "fb-3", "op": "dismiss_suggestion", "suggestion_id": "a" * 32},
        {"id": "fb-2", "op": "update", "changes": {"acknowledged": True}},
    ])
    check(results["fb-3"]["status"] == 403 and results["fb-3"]["code"] == "review_assistant_disabled", str(results["fb-3"]))
    check(results["fb-2"]["ok"] and container.items["fb-2"]["adminReview"]["acknowledged"] is True, str(results["fb-2"]))
    h.settings["enable_admin_review_ai_assistant"] = True

    # Themes: a filter and a dashboard breakdown; users never see the classification or the suggestion.
    themed = client.get("/feedback/review?theme=accuracy&archive=all").get_json()["feedback"]
    check([item["id"] for item in themed] == ["fb-1"], str([item["id"] for item in themed]))
    check(client.get("/feedback/review?theme=weather").status_code == 400, "an unknown theme was accepted")
    stats = client.get("/feedback/review/stats?days=30").get_json()
    check(stats["theme_mix"] == [{"theme": "accuracy", "count": 1}] and stats["unthemed_count_in_window"] == 2, str(stats["theme_mix"]))
    check(client.patch("/feedback/review/fb-3", json={"theme": "weather"}).status_code == 400, "an unknown theme was saved")
    mine = h.new_client()
    sign_in(mine, "user-1", roles=("User",))
    for item in mine.get("/feedback/my").get_json()["feedback"]:
        check("ai_suggestion" not in item, "a user saw an AI suggestion")
        check("theme" not in item["adminReview"] and "analyzedBy" not in item["adminReview"], str(item["adminReview"]))

    # The limiter: its own window, refunding requests that never reached the model. Two requests
    # reached the model so far, and the window allows three.
    for _attempt in range(3):
        closed(post_assist(client, "feedback", {"mode": "triage", "ids": ["fb-gone"]}), 200)
    closed(post_assist(client, "feedback", {"mode": "analyze", "ids": ["fb-3"]}), 200)
    response = post_assist(client, "feedback", {"mode": "analyze", "ids": ["fb-3"]})
    body = closed(response, 429, "assistant_rate_limited")
    check(int(response.headers["Retry-After"]) > 0 and body["rate_limited"] is True, str(body))

    for message, extra in assistant.telemetry:
        dumped = json.dumps(extra)
        for text in ("Policy question", USER_EMAIL, GUIDANCE, "per diem"):
            check(text not in dumped, f"telemetry recorded {text}")

print("PASS: feedback assist routes and suggestions")
'''


SAFETY_PROBE = PROBE_HEADER + r'''
import functions_review_assist as core

with offline_app_imports(), ExitStack() as stack:
    importlib.import_module(sys.argv[2])
    h = build_safety_app(stack)
    assistant = install_assistant(stack, "safety")
    client, container = h.client, h.container
    h.settings["enable_admin_review_ai_assistant"] = True
    h.settings["admin_review_ai_guidance"] = GUIDANCE
    h.user_docs["user-1"] = {"id": "user-1", "display_name": USER_NAME, "email": USER_EMAIL, "settings": {}}
    base = {"status": "New", "action": "None", "created_at": RECENT, "user_id": "user-1", "content_origin": "user",
            "message": f"Hateful text sent by {USER_EMAIL}", "triggered_categories": [{"category": "Hate", "severity": 4}]}
    container.seed({**base, "id": "log-1"})
    container.seed({**base, "id": "log-2", "content_origin": "assistant", "message": "An AI response that was flagged"})
    container.seed({**base, "id": "log-3", "action": "BlockUser", "action_request_status": "pending",
                    "action_request_id": "approval-x", "action_requested_at": RECENT})
    h.approvals_container.add({"id": "approval-x", "status": "pending", "request_type": "block_user",
                               "metadata": {"safety_log_id": "log-3"}})
    container.seed({**base, "id": "log-4", "message": "FILTER-TRIGGER flagged text"})
    container.seed({**base, "id": "log-5", "created_at": EARLIER, "status": "Resolved"})
    container.seed({**base, "id": "log-6", "action": "WarnUser", "action_request_status": "sending",
                    "warning_send_claim_id": "claim-1", "warning_send_claimed_at": datetime.now(timezone.utc).isoformat()})

    def answer(document):
        if any("FILTER-TRIGGER" in view["flagged_text_excerpt"] for view in document["records"]):
            return None, "content_filter"
        return json.dumps({"suggestions": [assistant.model.suggest(view) for view in document["records"]]}), "stop"

    assistant.model.answer = answer
    sign_in(client, "reviewer-1", roles=("Admin",), name="Rita Reviewer")
    response = post_assist(client, "safety", {"mode": "triage", "ids": ["log-1", "log-2", "log-3", "log-4", "log-6"]})
    body = closed(response, 200)
    outcomes = {entry["id"]: entry["outcome"] for entry in body["results"]}
    check(outcomes == {"log-1": "suggested", "log-2": "suggested", "log-3": "locked", "log-4": "content_filtered",
                       "log-6": "locked"}, str(outcomes))
    first = json.loads(assistant.model.calls[0][1]["content"])
    check([view["handle"] for view in first["records"]] == ["r1", "r2", "r3"], "locked records reached the model")
    views = {view["handle"]: view for view in first["records"]}
    check(views["r1"]["prior_violations_by_same_user"] == 1, str(views["r1"]))
    check(views["r2"]["allowed_actions"] == ["None"] and views["r2"]["content_origin"] == "ai_generated", str(views["r2"]))
    check(len(assistant.model.calls) == 4, f"expected one group call and three single retries, got {len(assistant.model.calls)}")
    for message in assistant.model.calls:
        dumped = json.dumps(message)
        for secret in ("user-1", USER_EMAIL, USER_NAME, "log-1", "approval-x"):
            check(secret not in dumped, f"{secret} reached the model")
    check("ai_suggestion" not in container.items["log-4"], "a filtered record got a suggestion")
    check(GUIDANCE not in response.get_data(as_text=True), "the guidance was echoed")

    # The queue, and what the warned user reads about themselves.
    listed = client.get("/api/safety/logs?ai=pending&archive=all").get_json()["logs"]
    check(sorted(item["id"] for item in listed) == ["log-1", "log-2"], str([item["id"] for item in listed]))
    check(all(item["ai_suggestion"]["status"] == "pending" and "fingerprint" not in item["ai_suggestion"] for item in listed), "queue")
    detail = client.get("/api/safety/logs/log-1").get_json()
    check(detail["ai_suggestion"]["payload"]["action"] == "WarnUser", str(detail["ai_suggestion"]))
    mine = h.new_client()
    sign_in(mine, "user-1", roles=("User",))
    for item in mine.get("/api/safety/logs/my").get_json()["logs"]:
        check("ai_suggestion" not in item, "a user saw an AI suggestion about themselves")

    # Apply log-1: the warning is sent through the normal save, with the reviewer's text.
    payload = detail["ai_suggestion"]["payload"]
    edited_message = "Edited by the reviewer: please keep messages respectful."
    results = bulk(client, "/api/safety/logs/bulk", [{
        "id": "log-1", "op": "update", "suggestion_id": detail["ai_suggestion"]["id"], "etag": detail["etag"],
        "changes": {"status": payload["status"], "action": payload["action"], "notes": payload["notes"],
                    "notification_title": payload["notification_title"], "notification_message": edited_message},
    }])
    check(results["log-1"]["ok"] and results["log-1"]["message"] == "Warning sent to the user.", str(results["log-1"]))
    check(results["log-1"]["suggestion"]["status"] == "applied" and results["log-1"]["suggestion"]["edited"] is True, str(results))
    check(len(h.notifications) == 1 and h.notifications[0]["message"] == edited_message, str(h.notifications))
    actions = sorted(entry["action"] for entry in h.audits)
    check(actions == ["safety_violation_ai_suggestion_applied", "safety_violation_warning_sent"], str(actions))
    check(container.items["log-1"]["ai_suggestion"]["status"] == "applied", "the suggestion was not marked")

    # An AI-generated finding: the normal save still refuses a warning, so the suggestion stays pending.
    log2 = client.get("/api/safety/logs/log-2").get_json()
    results = bulk(client, "/api/safety/logs/bulk", [{
        "id": "log-2", "op": "update", "suggestion_id": log2["ai_suggestion"]["id"],
        "changes": {"status": "Resolved", "action": "WarnUser", "notes": "x"},
    }])
    check(results["log-2"]["status"] == 400 and "AI-generated" in results["log-2"]["error"], str(results["log-2"]))
    check(container.items["log-2"]["ai_suggestion"]["status"] == "pending" and not h.notifications[1:], "a refused save changed things")
    results = bulk(client, "/api/safety/logs/bulk", [{
        "id": "log-2", "op": "update", "suggestion_id": log2["ai_suggestion"]["id"],
        "changes": {"status": "Resolved", "action": "Escalate", "notes": "x"},
    }])
    check(results["log-2"]["status"] == 400 and "Escalate" in results["log-2"]["error"], str(results["log-2"]))

    # A suspension suggestion: applying it creates an approval request, nothing more.
    record = container.items["log-5"]
    suggestion = core.Suggestion({"status": "Resolved", "action": "SuspendUser", "notes": "Repeated.",
                                  "notification_title": "Suspended", "notification_message": "Your access is suspended.",
                                  "suspend_duration": "7d", "archive": False}, "Repeat pattern.", "medium")
    document = core.build_suggestion_document(suggestion, suggestion_id="d" * 32,
                                              fingerprint=core.review_record_fingerprint("safety", record),
                                              actor={"id": "reviewer-2", "name": "Other"}, model="m", created_at=RECENT)
    container.seed({**record, "ai_suggestion": document})
    results = bulk(client, "/api/safety/logs/bulk", [{
        "id": "log-5", "op": "update", "suggestion_id": "d" * 32,
        "changes": {"status": "Resolved", "action": "SuspendUser", "notes": "Repeated.", "notification_title": "Suspended",
                    "notification_message": "Your access is suspended.", "datetime_to_allow": (NOW + timedelta(days=7)).isoformat()},
    }])
    check(results["log-5"]["ok"] and results["log-5"]["approval_required"] is True, str(results["log-5"]))
    check(len(h.approvals) == 1 and container.items["log-5"]["action_request_status"] == "pending", "no approval request")
    check(not [write for write in h.access_writes if write["user_id"] == "user-1"], "a suspension applied without a second reviewer")
    check(results["log-5"]["suggestion"] == {"id": "d" * 32, "status": "applied", "edited": False}, str(results["log-5"]))

    # A suggestion made before a request locked its violation is stale; dismissing still works.
    locked = container.items["log-3"]
    old = dict(locked, action="None", action_request_status=None)
    stale_doc = dict(document, id="e" * 32, fingerprint=core.review_record_fingerprint("safety", old))
    container.seed({**locked, "ai_suggestion": stale_doc})
    states = {item["id"]: item["ai_suggestion"]["status"] for item in client.get("/api/safety/logs?ai=pending").get_json()["logs"]}
    check(states.get("log-3") == "stale", str(states))
    results = bulk(client, "/api/safety/logs/bulk", [
        {"id": "log-3", "op": "update", "suggestion_id": "e" * 32, "changes": {"status": "Resolved"}},
    ])
    check(results["log-3"]["code"] == "suggestion_stale", str(results["log-3"]))
    results = bulk(client, "/api/safety/logs/bulk", [
        {"id": "log-3", "op": "dismiss_suggestion", "suggestion_id": "e" * 32},
        {"id": "log-2", "op": "dismiss_suggestion", "suggestion_id": log2["ai_suggestion"]["id"], "etag": "an-old-version"},
    ])
    check(results["log-3"]["ok"] and container.items["log-3"]["ai_suggestion"]["status"] == "dismissed", str(results["log-3"]))
    check(results["log-2"]["code"] == "record_changed", str(results["log-2"]))

    # Analyze a locked violation: an outcome, nothing stored, no model call.
    calls = len(assistant.model.calls)
    body = closed(post_assist(client, "safety", {"mode": "analyze", "ids": ["log-6"]}), 200)
    check(body["results"][0]["outcome"] == "locked" and len(assistant.model.calls) == calls, str(body))

    # The section's reviewer role, the toggle, and the report itself gate the route.
    h.settings["require_member_of_safety_violation_admin"] = True
    closed(post_assist(client, "safety", {"mode": "analyze", "ids": ["log-1"]}), 403)
    h.settings["require_member_of_safety_violation_admin"] = False
    h.settings["enable_admin_review_ai_assistant"] = False
    closed(post_assist(client, "safety", {"mode": "analyze", "ids": ["log-1"]}), 403, "review_assistant_disabled")
    # While it is off, stored suggestions can be neither applied nor dismissed; other operations still run.
    log2_pending = container.items["log-2"]["ai_suggestion"]["id"]
    results = bulk(client, "/api/safety/logs/bulk", [
        {"id": "log-2", "op": "dismiss_suggestion", "suggestion_id": log2_pending},
        {"id": "log-1", "op": "update", "suggestion_id": "f" * 32, "changes": {"status": "Resolved"}},
        {"id": "log-4", "op": "archive", "archived": True},
    ])
    for record_id in ("log-2", "log-1"):
        check(results[record_id]["status"] == 403 and results[record_id]["code"] == "review_assistant_disabled",
              str(results[record_id]))
    check(container.items["log-2"]["ai_suggestion"]["status"] == "pending", "a suggestion was dismissed while AI assist was off")
    check(results["log-4"]["ok"] and container.items["log-4"]["is_archived"] is True, str(results["log-4"]))
    h.settings["enable_admin_review_ai_assistant"] = True
    h.settings["enable_content_safety"] = False
    response = post_assist(client, "safety", {"mode": "analyze", "ids": ["log-1"]})
    check(response.status_code in (403, 404), f"the closed report still answered: {response.status_code}")
    check(len(assistant.model.calls) == calls, "a refused request reached the model")

print("PASS: safety assist routes and suggestions")
'''


REAL_INVOKER_PROBE = PROBE_HEADER + r'''
import functions_review_assist_runtime as runtime


class Message:
    def __init__(self, content=None, refusal=None):
        self.content = content
        self.refusal = refusal


class Choice:
    def __init__(self, message, finish_reason="stop"):
        self.message = message
        self.finish_reason = finish_reason


class Response:
    def __init__(self, choice):
        self.choices = [choice]


class Completions:
    def __init__(self, owner):
        self.owner = owner

    def create(self, **parameters):
        self.owner.requests.append(parameters)
        document = json.loads(parameters["messages"][1]["content"])
        if any("FILTER-TRIGGER" in view["prompt_excerpt"] for view in document["records"]):
            return Response(Choice(Message(refusal="I can't help with that.")))
        return Response(Choice(Message(json.dumps({"suggestions": [Model("feedback").suggest(view) for view in document["records"]]}))))


class Client:
    def __init__(self):
        self.requests = []
        self.chat = SimpleNamespace(completions=Completions(self))

    def with_options(self, **options):
        return self


with offline_app_imports(), ExitStack() as stack:
    import route_backend_feedback as feedback_routes
    h = build_feedback_app(stack)
    h.settings["enable_admin_review_ai_assistant"] = True
    fake = Client()
    stack.enter_context(patch.object(feedback_routes, "_review_assist_client", lambda settings: (fake, "review-deployment")))
    from functions_workflow_assist_limits import WorkflowAssistLimiter
    review_limiter = WorkflowAssistLimiter(MemoryLimitStore(), document_type=runtime.REVIEW_ASSIST_LIMIT_DOCUMENT_TYPE)
    original = runtime.build_review_assist_services
    stack.enter_context(patch.object(
        runtime, "build_review_assist_services",
        lambda *, store, client_factory, limiter=None, call_model=None: original(
            store=store, client_factory=client_factory, limiter=review_limiter,
        ),
    ))
    stack.enter_context(patch.object(runtime, "log_event", lambda *args, **kwargs: None))
    for index, prompt in ((1, "A question"), (2, "FILTER-TRIGGER question")):
        h.container.seed({"id": f"fb-{index}", "userId": "user-1", "feedbackType": "Negative", "prompt": prompt,
                          "aiResponse": "An answer.", "reason": "", "timestamp": RECENT, "adminReview": {}})
    sign_in(h.client, "reviewer-1", roles=("Admin",))
    body = closed(post_assist(h.client, "feedback", {"mode": "triage", "ids": ["fb-1", "fb-2"]}), 200)
    outcomes = {entry["id"]: entry["outcome"] for entry in body["results"]}
    check(outcomes == {"fb-1": "suggested", "fb-2": "content_filtered"}, str(outcomes))
    check(all(request.get("response_format") == {"type": "json_object"} for request in fake.requests), "JSON mode was not asked for")
    check(all(request["model"] == "review-deployment" for request in fake.requests), "the wrong deployment answered")
    check(h.container.items["fb-1"]["ai_suggestion"]["model"] == "review-deployment", "the model was not recorded")
    check(body["results"][0]["suggestion"]["model"] == "review-deployment", str(body["results"][0]))

print("PASS: the real model invoker isolates a refusal and records the deployment")
'''


FEEDBACK_VERSIONS_PROBE = PROBE_HEADER + r'''
from azure.cosmos import exceptions as cosmos_exceptions

with offline_app_imports(), ExitStack() as stack:
    importlib.import_module(sys.argv[2])
    import functions_review_center as review_center
    h = build_feedback_app(stack)
    assistant = install_assistant(stack, "feedback")
    client, container = h.client, h.container
    h.settings["enable_admin_review_ai_assistant"] = True
    for index, owner in ((1, "user-1"), (2, "user-2"), (3, "user-1"), (4, "user-3"), (5, "user-4")):
        container.seed({
            "id": f"fb-{index}", "userId": owner, "feedbackType": "Negative",
            "prompt": f"Question from {owner} number {index}", "aiResponse": "An answer.", "reason": "Incomplete",
            "timestamp": RECENT, "adminReview": {"acknowledged": False},
        })
    sign_in(client, "reviewer-1", roles=("Admin",), name="Rita Reviewer")

    # "Select all matching" says whose each record is, so the browser can send a user's records together.
    ids = client.get("/feedback/review/ids").get_json()
    check(ids["owners"] == {f"fb-{index}": owner for index, owner in
                            ((1, "user-1"), (2, "user-2"), (3, "user-1"), (4, "user-3"), (5, "user-4"))}, str(ids))

    # Editors opened before the triage; the list carries the same version and fingerprint.
    opened = {f"fb-{index}": client.get(f"/feedback/review/fb-{index}").get_json() for index in range(1, 6)}
    listed = {item["id"]: item for item in client.get("/feedback/review").get_json()["feedback"]}
    for record_id, record in opened.items():
        check(len(record["fingerprint"]) == 32 and listed[record_id]["fingerprint"] == record["fingerprint"], record_id)
        check(listed[record_id]["etag"] == record["etag"], record_id)
    mine = h.new_client()
    sign_in(mine, "user-1", roles=("User",))
    for item in mine.get("/feedback/my").get_json()["feedback"]:
        check("fingerprint" not in item and "etag" not in item, "a user read review bookkeeping")

    # One model call per user: user-1's two records together, user-2's alone.
    body = closed(post_assist(client, "feedback", {"mode": "triage", "ids": ["fb-1", "fb-2", "fb-3"]}), 200)
    check([entry["outcome"] for entry in body["results"]] == ["suggested"] * 3, str(body))
    calls = [[view["prompt_excerpt"] for view in json.loads(call[1]["content"])["records"]] for call in assistant.model.calls]
    check(calls == [["Question from user-1 number 1", "Question from user-1 number 3"],
                    ["Question from user-2 number 2"]], str(calls))
    check(container.items["fb-1"]["_etag"] != opened["fb-1"]["etag"], "storing the suggestion kept the version")

    # The editor's save goes ahead across the stored suggestion, and leaves it on the record.
    save = {"acknowledged": True, "analysisNotes": "Checked by hand.",
            "etag": opened["fb-1"]["etag"], "fingerprint": opened["fb-1"]["fingerprint"]}
    closed(client.patch("/feedback/review/fb-1", json=save), 200)
    check(container.items["fb-1"]["adminReview"]["analysisNotes"] == "Checked by hand.", "the save was lost")
    check(container.items["fb-1"]["ai_suggestion"]["status"] == "pending", "the save dropped the suggestion")
    check(client.get("/feedback/review/fb-1").get_json()["ai_suggestion"]["status"] == "stale", "a reviewed record kept a fresh suggestion")

    # Across a colleague's dismissal too; without the fingerprint the version alone decides, as before.
    other = h.new_client()
    sign_in(other, "reviewer-2", roles=("Admin",), name="Omar Other")
    fb2_suggestion = container.items["fb-2"]["ai_suggestion"]["id"]
    check(bulk(other, "/feedback/review/bulk", [
        {"id": "fb-2", "op": "dismiss_suggestion", "suggestion_id": fb2_suggestion},
    ])["fb-2"]["ok"], "the dismissal failed")
    closed(client.patch("/feedback/review/fb-2", json={"acknowledged": True, "etag": opened["fb-2"]["etag"]}), 409, "record_changed")
    closed(client.patch("/feedback/review/fb-2", json={
        "acknowledged": True, "etag": opened["fb-2"]["etag"], "fingerprint": opened["fb-2"]["fingerprint"],
    }), 200)

    # A real edit by someone else still refuses the save, and survives it.
    check(other.patch("/feedback/review/fb-3", json={"analysisNotes": "Another reviewer's notes."}).status_code == 200, "edit")
    closed(client.patch("/feedback/review/fb-3", json={
        "acknowledged": True, "etag": opened["fb-3"]["etag"], "fingerprint": opened["fb-3"]["fingerprint"],
    }), 409, "record_changed")
    check(container.items["fb-3"]["adminReview"]["analysisNotes"] == "Another reviewer's notes.", "a real edit was overwritten")
    closed(client.patch("/feedback/review/fb-3", json={"acknowledged": True, "fingerprint": 7}), 400)

    # A write landing between the fresh read and the save is refused: the save names that version.
    container.seed({**container.items["fb-4"], "bookkeeping": "touched"})
    container.before_replace = lambda fake: fake.seed({
        **fake.items["fb-4"], "adminReview": {"acknowledged": False, "analysisNotes": "Raced in."},
    })
    closed(client.patch("/feedback/review/fb-4", json={
        "acknowledged": True, "etag": opened["fb-4"]["etag"], "fingerprint": opened["fb-4"]["fingerprint"],
    }), 409, "record_changed")
    check(container.items["fb-4"]["adminReview"]["analysisNotes"] == "Raced in.", "the racing write was overwritten")

    # Approving from the queue sends the list's version and fingerprint; bookkeeping since doesn't refuse it.
    closed(post_assist(client, "feedback", {"mode": "triage", "ids": ["fb-5"]}), 200)
    queued = {item["id"]: item for item in client.get("/feedback/review?ai=pending").get_json()["feedback"]}["fb-5"]
    container.seed({**container.items["fb-5"], "bookkeeping": "touched"})
    payload = queued["ai_suggestion"]["payload"]
    results = bulk(client, "/feedback/review/bulk", [{
        "id": "fb-5", "op": "update", "suggestion_id": queued["ai_suggestion"]["id"], "etag": queued["etag"],
        "changes": {**{key: payload[key] for key in ("acknowledged", "analysisNotes", "actionTaken", "responseToUser", "theme")},
                    "fingerprint": queued["fingerprint"]},
    }])
    check(results["fb-5"]["ok"] and results["fb-5"]["suggestion"]["status"] == "applied", str(results["fb-5"]))

    # A record that can't be read fails its own operation; the rest of the request still runs.
    read_item = container.read_item

    def flaky(item, partition_key, **kwargs):
        if item in ("fb-2", "fb-3"):
            raise cosmos_exceptions.CosmosHttpResponseError(status_code=503, message="Service unavailable")
        return read_item(item, partition_key, **kwargs)

    container.read_item = flaky
    results = bulk(client, "/feedback/review/bulk", [
        {"id": "fb-1", "op": "update", "changes": {"actionTaken": "Re-indexed."}},
        {"id": "fb-2", "op": "dismiss_suggestion", "suggestion_id": "a" * 32},
        {"id": "fb-3", "op": "update", "suggestion_id": "b" * 32, "changes": {"acknowledged": True}},
        {"id": "fb-4", "op": "archive", "archived": True},
    ])
    container.read_item = read_item
    check(results["fb-1"]["ok"] and results["fb-4"]["ok"], str(results))
    for record_id in ("fb-2", "fb-3"):
        check(results[record_id]["status"] == 500 and results[record_id]["code"] == "operation_failed", str(results[record_id]))
        check("Service unavailable" not in json.dumps(results[record_id]), "provider text reached the browser")

    # Anything else unexpected in a suggestion operation fails only that operation as well.
    with patch.object(review_center, "suggestion_problem", side_effect=RuntimeError("boom")):
        results = bulk(client, "/feedback/review/bulk", [
            {"id": "fb-1", "op": "update", "suggestion_id": "c" * 32, "changes": {"acknowledged": True}},
            {"id": "fb-4", "op": "archive", "archived": False},
        ])
    check(results["fb-1"]["code"] == "operation_failed" and results["fb-4"]["ok"], str(results))

print("PASS: feedback owners, versions and failed operations")
'''


SAFETY_VERSIONS_PROBE = PROBE_HEADER + r'''
from azure.cosmos import exceptions as cosmos_exceptions

with offline_app_imports(), ExitStack() as stack:
    importlib.import_module(sys.argv[2])
    h = build_safety_app(stack)
    assistant = install_assistant(stack, "safety")
    client, container = h.client, h.container
    h.settings["enable_admin_review_ai_assistant"] = True
    base = {"status": "New", "action": "None", "created_at": RECENT, "content_origin": "user",
            "message": "Hateful text", "triggered_categories": [{"category": "Hate", "severity": 4}]}
    owners = {"log-1": "user-1", "log-2": "user-2", "log-3": "user-1", "log-4": "user-3", "log-5": "user-4"}
    for log_id, owner in owners.items():
        container.seed({**base, "id": log_id, "user_id": owner, "message": f"Hateful text from {owner} in {log_id}"})
    warned = {"action": "WarnUser", "action_request_status": "executed", "warning_requires_acknowledgment": True,
              "warning_issued_at": RECENT, "warning_notification_id": "notification-0", "status": "Resolved"}
    container.seed({**container.items["log-4"], **warned})
    sign_in(client, "reviewer-1", roles=("Admin",), name="Rita Reviewer")

    ids = client.get("/api/safety/logs/ids").get_json()
    check(ids["owners"] == owners, str(ids))
    opened = {log_id: client.get(f"/api/safety/logs/{log_id}").get_json() for log_id in owners}
    listed = {item["id"]: item for item in client.get("/api/safety/logs").get_json()["logs"]}
    for log_id, record in opened.items():
        check(len(record["fingerprint"]) == 32 and listed[log_id]["fingerprint"] == record["fingerprint"], log_id)
        check(listed[log_id]["etag"] == record["etag"], log_id)
    mine = h.new_client()
    sign_in(mine, "user-1", roles=("User",))
    for item in mine.get("/api/safety/logs/my").get_json()["logs"]:
        check("fingerprint" not in item and "ai_suggestion" not in item, "a user read review bookkeeping")

    # One model call per user.
    body = closed(post_assist(client, "safety", {"mode": "triage", "ids": ["log-1", "log-2", "log-3"]}), 200)
    check([entry["outcome"] for entry in body["results"]] == ["suggested"] * 3, str(body))
    calls = [[view["flagged_text_excerpt"] for view in json.loads(call[1]["content"])["records"]] for call in assistant.model.calls]
    check(calls == [["Hateful text from user-1 in log-1", "Hateful text from user-1 in log-3"],
                    ["Hateful text from user-2 in log-2"]], str(calls))

    def save(log_id, **fields):
        return client.patch(f"/api/safety/logs/{log_id}", json={
            "status": "Resolved", "action": "None", "notes": "Reviewed.",
            "etag": opened[log_id]["etag"], "fingerprint": opened[log_id]["fingerprint"], **fields,
        })

    # Across the stored suggestion, the editor's save goes ahead -- here sending a warning, which
    # claims the violation on the version just read and is sent once.
    closed(save("log-1", action="WarnUser", notification_title="Safety warning",
                notification_message="Please keep messages respectful."), 200)
    check(len(h.notifications) == 1 and container.items["log-1"]["action_request_status"] == "executed", str(h.notifications))
    check(container.items["log-1"]["ai_suggestion"]["status"] == "pending", "the save dropped the suggestion")

    # Across a colleague's dismissal too.
    other = h.new_client()
    sign_in(other, "reviewer-2", roles=("Admin",), name="Omar Other")
    check(bulk(other, "/api/safety/logs/bulk", [
        {"id": "log-2", "op": "dismiss_suggestion", "suggestion_id": container.items["log-2"]["ai_suggestion"]["id"]},
    ])["log-2"]["ok"], "the dismissal failed")
    closed(save("log-2"), 200)
    check(container.items["log-2"]["notes"] == "Reviewed.", "the save was lost")

    # A warning being sent, a new request, the user's acknowledgment, or a real edit still refuse it.
    now = datetime.now(timezone.utc).isoformat()
    container.seed({**container.items["log-3"], "action": "WarnUser", "action_request_status": "sending",
                    "warning_send_claim_id": "claim-1", "warning_send_claimed_at": now})
    closed(save("log-3"), 409, "record_changed")
    container.seed({**container.items["log-4"], "warning_acknowledged_at": now})
    closed(save("log-4", action="WarnUser"), 409, "record_changed")
    container.seed({**container.items["log-5"], "action": "SuspendUser", "action_request_status": "pending",
                    "action_request_id": "approval-9", "action_requested_at": now})
    closed(save("log-5"), 409, "record_changed")
    check(container.items["log-5"]["action_request_status"] == "pending" and not container.items["log-5"].get("notes"),
          "a new request was overwritten")
    check(container.items["log-4"]["warning_acknowledged_at"] == now, "an acknowledgment was overwritten")
    opened["log-2"] = client.get("/api/safety/logs/log-2").get_json()
    check(other.patch("/api/safety/logs/log-2", json={"notes": "Another reviewer's notes."}).status_code == 200, "edit")
    closed(save("log-2"), 409, "record_changed")
    check(len(h.notifications) == 1, "a refused save sent something")

    # A record that can't be read fails its own operation; the rest of the request still runs.
    read_item = container.read_item

    def flaky(item, partition_key, **kwargs):
        if item == "log-3":
            raise cosmos_exceptions.CosmosHttpResponseError(status_code=503, message="Service unavailable")
        return read_item(item, partition_key, **kwargs)

    container.read_item = flaky
    results = bulk(client, "/api/safety/logs/bulk", [
        {"id": "log-1", "op": "update", "changes": {"status": "Resolved", "notes": "Closed."}},
        {"id": "log-3", "op": "update", "suggestion_id": "a" * 32, "changes": {"status": "Resolved"}},
        {"id": "log-2", "op": "archive", "archived": True},
    ])
    container.read_item = read_item
    check(results["log-1"]["ok"] and results["log-2"]["ok"], str(results))
    check(results["log-3"]["status"] == 500 and results["log-3"]["code"] == "operation_failed", str(results["log-3"]))

print("PASS: safety owners, versions and failed operations")
'''


def _run(probe, first_import, optimized, marker):
    command = [sys.executable, "-B"]
    if optimized:
        command.append("-O")
    result = subprocess.run(
        command + ["-c", probe, str(ROOT), first_import],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert marker in result.stdout


@pytest.mark.parametrize("first_import", ["functions_review_assist_runtime", "route_backend_feedback"])
@pytest.mark.parametrize("optimized", [False, True])
def test_feedback_assist_routes_and_suggestions(first_import, optimized):
    _run(FEEDBACK_PROBE, first_import, optimized, "PASS: feedback assist routes and suggestions")


@pytest.mark.parametrize("first_import", ["functions_review_center", "route_backend_safety"])
@pytest.mark.parametrize("optimized", [False, True])
def test_safety_assist_routes_and_suggestions(first_import, optimized):
    _run(SAFETY_PROBE, first_import, optimized, "PASS: safety assist routes and suggestions")


def test_the_real_model_invoker_isolates_a_refusal():
    _run(REAL_INVOKER_PROBE, "route_backend_feedback", False,
         "PASS: the real model invoker isolates a refusal and records the deployment")


@pytest.mark.parametrize("optimized", [False, True])
def test_feedback_owners_versions_and_failed_operations(optimized):
    _run(FEEDBACK_VERSIONS_PROBE, "route_backend_feedback", optimized, "PASS: feedback owners, versions and failed operations")


@pytest.mark.parametrize("optimized", [False, True])
def test_safety_owners_versions_and_failed_operations(optimized):
    _run(SAFETY_VERSIONS_PROBE, "route_backend_safety", optimized, "PASS: safety owners, versions and failed operations")


def test_version():
    assert_app_version_at_least("0.261.299")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
