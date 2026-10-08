#!/usr/bin/env python3
# test_review_center_bulk_and_dashboards.py
"""
Functional test for the Review center's bulk, select-all-matching and dashboard APIs.
Version: 0.261.298
Implemented in: 0.261.298

This test ensures that POST /api/safety/logs/bulk and POST /feedback/review/bulk accept at
most 100 operations, refuse unknown fields, report every operation in request order with
its own outcome, and apply each exactly as the single-record route would: a warning is sent
at once, a suspension creates an approval request, a violation waiting on a request is left
alone, a stale etag is refused, and archives and deletes are audited. It checks that the
ids endpoints cap "select all matching" at 500 and honour the list filters; that list
search matches server-resolved display names, looked up in one batch; that the stats
endpoints keep every existing field and add the dashboard window only when asked; that
feedback saves record the reviewer and can notify the user, whose own list never shows who
reviewed it; and that every endpoint stays inside its section's reviewer role. Real modules
run in fresh processes with network access blocked, under normal and optimized Python.
"""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
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
from test_support.safety_review_harness import build_feedback_app, build_safety_app, check, sign_in, sign_out

NOW = datetime.now(timezone.utc).replace(tzinfo=None)
RECENT = (NOW - timedelta(hours=3)).isoformat()


def by_id(results):
    return {result["id"]: result for result in results}
'''


SAFETY_BULK_PROBE = PROBE_HEADER + r'''
with offline_app_imports(), ExitStack() as stack:
    importlib.import_module(sys.argv[2])
    h = build_safety_app(stack)
    client, container = h.client, h.container
    sign_in(client, "reviewer-1", roles=("Admin",))
    base = {"status": "New", "action": "None", "created_at": RECENT, "message": "Flagged text", "user_id": "user-1",
            "triggered_categories": [{"category": "Hate", "severity": 4}]}
    for log_id in ("log-status", "log-archive", "log-delete", "log-warn", "log-suspend", "log-stale"):
        container.seed({**base, "id": log_id})
    container.seed({**base, "id": "log-pending", "action": "BlockUser", "action_request_status": "pending",
                    "action_request_id": "approval-x", "action_requested_at": RECENT})
    container.seed({**base, "id": "log-pending-2", "action": "SuspendUser", "action_request_status": "pending",
                    "action_request_id": "approval-y", "action_requested_at": RECENT})
    for approval_id, log_id in (("approval-x", "log-pending"), ("approval-y", "log-pending-2")):
        h.approvals_container.add({"id": approval_id, "status": "pending", "request_type": "block_user",
                                   "metadata": {"safety_log_id": log_id}})

    # The envelope: an object with 1 to 100 operations, nothing else.
    for payload in (None, [], {"operations": []}, {"operations": [{}], "extra": 1}):
        response = client.post("/api/safety/logs/bulk", json=payload)
        check(response.status_code == 400 and response.get_json()["code"] == "invalid_request", f"{payload}: {response.get_json()}")
    response = client.post("/api/safety/logs/bulk", json={
        "operations": [{"id": f"log-{index}", "op": "delete"} for index in range(101)],
    })
    check(response.status_code == 400 and response.get_json()["code"] == "too_many_operations", str(response.get_json()))
    check("log-status" in container.items and len(h.audits) == 0, "a refused request changed something")

    operations = [
        {"id": "log-status", "op": "update", "changes": {"status": "Resolved"}},
        {"id": "log-archive", "op": "archive", "archived": True},
        {"id": "log-delete", "op": "delete"},
        {"id": "log-warn", "op": "update", "changes": {"action": "WarnUser", "notification_message": "Please stop."}},
        {"id": "log-suspend", "op": "update", "changes": {
            "action": "SuspendUser", "datetime_to_allow": (NOW + timedelta(days=7)).isoformat(),
        }},
        {"id": "log-pending", "op": "update", "changes": {"status": "Resolved"}},
        {"id": "log-pending-2", "op": "delete"},
        {"id": "log-stale", "op": "archive", "archived": True, "etag": "an-old-version"},
        {"id": "log-missing", "op": "update", "changes": {"status": "Resolved"}},
        {"id": "log-status", "op": "archive", "archived": True},
        {"id": "log-other", "op": "explode"},
        {"id": "log-fields", "op": "delete", "suggestion": "not yet"},
    ]
    response = client.post("/api/safety/logs/bulk", json={"operations": operations})
    check(response.status_code == 200, str(response.get_json()))
    body = response.get_json()
    results = body["results"]
    check([result["index"] for result in results] == list(range(len(operations))), "results are not in request order")
    check(body["succeeded"] == 5 and body["failed"] == 7, f"{body['succeeded']} succeeded, {body['failed']} failed")
    check([result["ok"] for result in results[:5]] == [True] * 5, str(results[:5]))

    # Each applied as its single route would.
    check(container.items["log-status"]["status"] == "Resolved", "the status update was not saved")
    check(container.items["log-archive"]["is_archived"] is True, "the archive was not saved")
    check("log-delete" not in container.items, "the delete was not applied")
    actions = sorted(audit["action"] for audit in h.audits)
    check(actions == ["safety_violation_archived", "safety_violation_deleted", "safety_violation_warning_sent"], str(actions))
    check(results[3]["message"] == "Warning sent to the user." and results[3]["approval_required"] is False, str(results[3]))
    check(len(h.notifications) == 1 and h.notifications[0]["metadata"]["safety_log_id"] == "log-warn", str(h.notifications))
    check(container.items["log-warn"]["action_request_status"] == "executed", "the warning was not recorded as sent")
    check(results[4]["approval_required"] is True and len(h.approvals) == 1, str(results[4]))
    check(container.items["log-suspend"]["action_request_status"] == "pending", "the suspension request was not recorded")

    # Refusals, each with its own code, and nothing changed for them.
    check(results[5]["status"] == 409 and results[5]["code"] == "remediation_pending", str(results[5]))
    check(results[6]["status"] == 409 and results[6]["code"] == "remediation_pending", str(results[6]))
    check("log-pending-2" in container.items, "a violation waiting on a request was deleted")
    check(results[7]["status"] == 409 and results[7]["code"] == "record_changed", str(results[7]))
    check(not container.items["log-stale"].get("is_archived"), "a stale archive was applied")
    check(results[8]["status"] == 404 and results[8]["code"] == "not_found", str(results[8]))
    check(results[9]["code"] == "duplicate_operation" and not container.items["log-status"].get("is_archived"), str(results[9]))
    check(results[10]["code"] == "invalid_operation" and results[11]["code"] == "invalid_operation", str(results[10:]))
    check(container.items["log-pending"]["status"] == "New", "a violation waiting on a request was changed")

    # A matching etag is accepted.
    etag = client.get("/api/safety/logs/log-stale").get_json()["etag"]
    response = client.post("/api/safety/logs/bulk", json={"operations": [
        {"id": "log-stale", "op": "archive", "archived": True, "etag": etag},
    ]})
    check(response.get_json()["results"][0]["ok"] is True, str(response.get_json()))

    # Only safety reviewers, and only while safety checks are on.
    sign_in(client, "user-2", roles=("User",))
    for path in ("/api/safety/logs/bulk", "/api/safety/logs/ids", "/api/safety/logs/stats?days=7"):
        response = client.post(path, json={"operations": [{"id": "log-status", "op": "delete"}]}) if path.endswith("bulk") else client.get(path)
        check(response.status_code == 403, f"{path} answered a user without the role: {response.status_code}")
    h.settings["require_member_of_safety_violation_admin"] = True
    sign_in(client, "admin-2", roles=("Admin", "FeedbackAdmin"))
    response = client.post("/api/safety/logs/bulk", json={"operations": [{"id": "log-status", "op": "delete"}]})
    check(response.status_code == 403 and "log-status" in container.items, "an admin without the safety role used bulk")
    sign_in(client, "safety-1", roles=("User", "SafetyViolationAdmin"))
    check(client.get("/api/safety/logs/ids").status_code == 200, "the safety role was refused")
    h.settings["enable_content_safety"] = False
    check(client.get("/api/safety/logs/ids").status_code == 403, "the ids endpoint answered with safety checks off")
    sign_out(client)
    check(client.get("/api/safety/logs/ids").status_code in (401, 302), "an anonymous caller was answered")

print("PASS: safety bulk review applies each operation as its own save")
'''


FEEDBACK_BULK_PROBE = PROBE_HEADER + r'''
with offline_app_imports(), ExitStack() as stack:
    importlib.import_module(sys.argv[2])
    h = build_feedback_app(stack)
    client, container = h.client, h.container
    h.user_docs["user-1"] = {"id": "user-1", "display_name": "Uma User", "email": "uma@contoso.test", "settings": {}}
    sign_in(client, "reviewer-1", roles=("Admin",), name="Riley Reviewer")
    base = {"userId": "user-1", "prompt": "Why is the sky blue?", "aiResponse": "Rayleigh scattering.",
            "feedbackType": "Negative", "reason": "Too short", "timestamp": RECENT, "adminReview": {"acknowledged": False}}
    for feedback_id in ("fb-ack", "fb-notify", "fb-archive", "fb-delete"):
        container.seed({**base, "id": feedback_id})

    response = client.post("/feedback/review/bulk", json={"operations": [{"id": "x", "op": "delete"}] * 101})
    check(response.status_code == 400 and response.get_json()["code"] == "too_many_operations", str(response.get_json()))

    response = client.post("/feedback/review/bulk", json={"operations": [
        {"id": "fb-ack", "op": "update", "changes": {"acknowledged": True}},
        {"id": "fb-notify", "op": "update", "changes": {"acknowledged": True, "responseToUser": "Thanks, fixed.", "notify_user": True}},
        {"id": "fb-archive", "op": "archive", "archived": True},
        {"id": "fb-delete", "op": "delete"},
        {"id": "fb-missing", "op": "update", "changes": {"acknowledged": True}},
        {"id": "fb-ack", "op": "delete"},
        {"id": "fb-bad", "op": "update", "changes": {"acknowledged": "yes"}},
    ]})
    body = response.get_json()
    check(response.status_code == 200 and body["succeeded"] == 4 and body["failed"] == 3, str(body))
    results = body["results"]
    review = container.items["fb-ack"]["adminReview"]
    check(review["acknowledged"] is True and review["analyzedBy"] == {"id": "reviewer-1", "displayName": "Riley Reviewer"}, str(review))
    check(results[1]["notified"] is True and len(h.notifications) == 1, str(results[1]))
    notice = h.notifications[0]
    check(notice["user_id"] == "user-1" and notice["notification_type"] == "feedback_response", str(notice))
    check(notice["link_url"] == "/profile?tab=feedback" and notice["message"] == "Thanks, fixed.", str(notice))
    check(container.items["fb-notify"]["adminReview"]["userNotifiedAt"], "the notification time was not recorded")
    check(container.items["fb-archive"]["is_archived"] is True and "fb-delete" not in container.items, "archive or delete missing")
    check(sorted(audit["action"] for audit in h.audits) == ["feedback_archived", "feedback_deleted"], str(h.audits))
    check(results[4]["code"] == "not_found" and results[5]["code"] == "duplicate_operation", str(results[4:6]))
    check(results[6]["status"] == 400 and "fb-ack" in container.items, str(results[6]))

    # A notification that can't be created leaves the review saved and says so.
    h.fail_notifications = True
    response = client.patch("/feedback/review/fb-archive", json={"notify_user": True})
    h.fail_notifications = False
    check(response.status_code == 200 and response.get_json()["notified"] is False, str(response.get_json()))
    check(response.get_json()["notification_warning"], "the failed notification was not reported")

    # The list carries names, and search matches them; the user's own list never says who reviewed it.
    page = client.get("/feedback/review?page=1&page_size=10&search=uma&archive=all").get_json()
    check(page["total_count"] == 3 and all(item["userDisplayName"] == "Uma User" for item in page["feedback"]), str(page))
    ids = client.get("/feedback/review/ids?ack=false").get_json()
    check(ids == {"ids": [], "total": 0, "capped": False, "cap": 500}, str(ids))
    sign_in(client, "user-1", roles=("User",))
    mine = client.get("/feedback/my").get_json()
    reviews = [item.get("adminReview") or {} for item in mine.get("feedback", mine if isinstance(mine, list) else [])]
    check(reviews and all("analyzedBy" not in review for review in reviews), f"the user saw the reviewer: {mine}")

    # Only feedback reviewers.
    check(client.post("/feedback/review/bulk", json={"operations": [{"id": "fb-ack", "op": "delete"}]}).status_code == 403,
          "a user without the role used bulk")
    h.settings["require_member_of_feedback_admin"] = True
    sign_in(client, "admin-2", roles=("Admin", "SafetyViolationAdmin"))
    check(client.get("/feedback/review/ids").status_code == 403, "an admin without the feedback role listed ids")
    sign_in(client, "feedback-1", roles=("User", "FeedbackAdmin"))
    check(client.get("/feedback/review/ids").status_code == 200, "the feedback role was refused")
    h.settings["enable_user_feedback"] = False
    check(client.get("/feedback/review/ids").status_code != 200, "the ids endpoint answered with feedback off")

print("PASS: feedback bulk review applies each operation as its own save")
'''


IDS_AND_STATS_PROBE = PROBE_HEADER + r'''
with offline_app_imports(), ExitStack() as stack:
    importlib.import_module(sys.argv[2])
    import functions_review_center as review_center
    h = build_safety_app(stack)
    client, container = h.client, h.container
    sign_in(client, "reviewer-1", roles=("Admin",))
    h.unchecked_count = 4
    h.user_docs["user-1"] = {"id": "user-1", "display_name": "Uma User", "email": "uma@contoso.test", "settings": {}}
    h.user_docs["user-r"] = {"id": "user-r", "display_name": "Rae Restricted", "email": "rae@contoso.test",
                             "settings": {"access": {"status": "deny"}}}
    base = {"status": "Resolved", "action": "None", "message": "Older text", "user_id": "user-9",
            "created_at": (NOW - timedelta(days=60)).isoformat(), "triggered_categories": [{"category": "Violence", "severity": 2}]}
    for index in range(501):
        container.seed({**base, "id": f"log-{index:03d}"})
    container.seed({**base, "id": "open-1", "status": "New", "user_id": "user-1", "created_at": RECENT,
                    "message": "Recent text", "triggered_categories": [{"category": "Hate", "severity": 6}]})
    container.seed({**base, "id": "open-2", "status": "In-Review", "user_id": "user-1", "created_at": RECENT,
                    "action": "WarnUser", "action_request_status": "executed", "warning_requires_acknowledgment": True,
                    "warning_issued_at": RECENT, "warning_acknowledged_at": RECENT,
                    "triggered_categories": [{"category": "Hate", "severity": 4}]})
    container.seed({**base, "id": "blocked", "user_id": "user-r", "action": "BlockUser",
                    "action_request_status": "executed", "created_at": RECENT})

    # "Select all matching": capped at 500, and the same filters as the list.
    ids = client.get("/api/safety/logs/ids").get_json()
    check(len(ids["ids"]) == 500 and ids["total"] == 504 and ids["capped"] is True and ids["cap"] == 500, str({**ids, "ids": len(ids["ids"])}))
    check(len(set(ids["ids"])) == 500, "the capped ids repeat")
    ids = client.get("/api/safety/logs/ids?status=open").get_json()
    check(sorted(ids["ids"]) == ["open-1", "open-2"] and ids["capped"] is False, str(ids))
    check(client.get("/api/safety/logs/ids?request=sideways").status_code == 400, "an unknown request state was accepted")

    # Search reaches display names, looked up in one batch per page.
    lookups_before = len(review_center.cosmos_user_settings_container.queries)
    page = client.get("/api/safety/logs?page=1&page_size=10&search=uma").get_json()
    check(sorted(log["id"] for log in page["logs"]) == ["open-1", "open-2"], str([log["id"] for log in page["logs"]]))
    check(all(log["user_display_name"] == "Uma User" for log in page["logs"]), str(page["logs"]))
    lookups = len(review_center.cosmos_user_settings_container.queries) - lookups_before
    check(lookups == 1, f"names were looked up {lookups} times for one page")
    page = client.get("/api/safety/logs?page=1&page_size=10&restricted=1&archive=all").get_json()
    check([log["id"] for log in page["logs"]] == ["blocked"], str(page))

    # Stats keep every existing field; the window is added only when asked for.
    legacy = client.get("/api/safety/logs/stats").get_json()
    for field in ("total_count", "new_count", "in_review_count", "resolved_count", "dismissed_count", "warn_user_count",
                  "suspend_user_count", "escalate_count", "block_user_count", "none_action_count", "recent_30_day_count"):
        check(field in legacy, f"the stats lost {field}")
    check("window" not in legacy and "daily_by_category" not in legacy, "the window was added unasked")
    windowed = client.get("/api/safety/logs/stats?days=7").get_json()
    check({key: windowed[key] for key in legacy} == legacy, "the window changed an existing field")
    check(windowed["window"]["days"] == 7 and len(windowed["daily_by_category"]["dates"]) == 7, str(windowed["window"]))
    check(windowed["received_count"] == 3 and windowed["open_count"] == 2, str(windowed))
    check(windowed["restricted_user_count"] == 1 and windowed["unchecked_chat_count"] == 4, str(windowed))
    check(windowed["warnings_sent_count"] == 1 and windowed["warnings_acknowledged_count"] == 1, str(windowed))
    check(windowed["repeat_users"] == [{"user_id": "user-1", "display_name": "Uma User", "email": "uma@contoso.test", "count": 2}],
          str(windowed["repeat_users"]))
    series = {entry["key"]: sum(entry["counts"]) for entry in windowed["daily_by_category"]["series"]}
    check(series == {"Hate": 2, "Violence": 1}, str(windowed["daily_by_category"]))
    check(client.get("/api/safety/logs/stats?days=5").status_code == 400, "an unsupported window was accepted")

    # The same for feedback.
    f = build_feedback_app(stack)
    fclient = f.client
    sign_in(fclient, "reviewer-1", roles=("Admin",))
    for index, rating in enumerate(("Positive", "Negative", "Negative")):
        f.container.seed({"id": f"fb-{index}", "userId": "user-1", "prompt": f"Prompt {index}", "feedbackType": rating,
                          "timestamp": RECENT, "adminReview": {"acknowledged": index == 0}})
    f.container.seed({"id": "fb-archived", "userId": "user-1", "prompt": "Old", "feedbackType": "Neutral",
                      "timestamp": RECENT, "is_archived": True, "adminReview": {"acknowledged": True}})
    legacy = fclient.get("/feedback/review/stats").get_json()
    for field in ("total_count", "positive_count", "negative_count", "neutral_count", "acknowledged_count",
                  "unacknowledged_count", "recent_30_day_count", "latest_timestamp"):
        check(field in legacy, f"the feedback stats lost {field}")
    check("window" not in legacy, "the feedback window was added unasked")
    windowed = fclient.get("/feedback/review/stats?days=30").get_json()
    check({key: windowed[key] for key in legacy} == legacy, "the feedback window changed an existing field")
    check(windowed["awaiting_review_count"] == 2 and windowed["negative_count_in_window"] == 2, str(windowed))
    check(windowed["received_count"] == 4 and windowed["archived_count"] == 1, str(windowed))
    check(windowed["acknowledgement_rate"] == 0.5 and len(windowed["oldest_awaiting"]) == 2, str(windowed))
    check(len(windowed["daily_by_rating"]["dates"]) == 30, "the feedback series does not span the window")
    check(fclient.get("/feedback/review/stats?days=12").status_code == 400, "an unsupported feedback window was accepted")

print("PASS: ids, search and dashboard windows")
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


@pytest.mark.parametrize("first_import", ["functions_review_center", "route_backend_safety"])
@pytest.mark.parametrize("optimized", [False, True])
def test_safety_bulk_applies_each_operation_as_its_own_save(first_import, optimized):
    _run(SAFETY_BULK_PROBE, first_import, optimized, "PASS: safety bulk review applies each operation as its own save")


@pytest.mark.parametrize("optimized", [False, True])
def test_feedback_bulk_applies_each_operation_as_its_own_save(optimized):
    _run(FEEDBACK_BULK_PROBE, "route_backend_feedback", optimized, "PASS: feedback bulk review applies each operation as its own save")


def test_ids_search_and_dashboard_windows():
    _run(IDS_AND_STATS_PROBE, "route_backend_safety", False, "PASS: ids, search and dashboard windows")


def test_version():
    assert_app_version_at_least("0.261.298")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
