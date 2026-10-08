#!/usr/bin/env python3
# test_approvals_dashboard_stats.py
"""
Functional test for the Approvals dashboard summary, GET /api/approvals/stats.
Version: 0.261.298
Implemented in: 0.261.298

This test ensures the summary counts only the approval requests the caller can see, as
GET /api/approvals reads them: requests waiting on the caller are the pending ones the
caller may approve, never the caller's own requests; the caller's own pending requests,
those expiring within a day, decided requests by outcome inside the 7, 30 or 90 day window,
pending requests by type and the oldest waiting on the caller are counted from that same
list. The route reads requests through get_pending_approvals for the signed-in user with
its own roles, refuses an unsupported window, needs a session, and keeps the swagger and
login decorators. Real modules run in a fresh process with network access blocked, under
normal and optimized Python.
"""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402


STATS_PROBE = r'''
import ast
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

root = Path(sys.argv[1])
sys.path.insert(0, str(root / "functional_tests"))
sys.path.insert(0, str(root / "application" / "single_app"))
from test_support.offline_bootstrap import offline_app_imports
from test_support.safety_review_harness import _test_client, check, sign_in, sign_out

with offline_app_imports():
    import functions_approvals as approvals
    import functions_authentication as auth
    import functions_review_center as review_center
    from flask import Blueprint, Flask, jsonify, request, session

    now = datetime(2026, 10, 8, 12, 0, 0)

    def at(**delta):
        return (now + timedelta(**delta)).isoformat()

    requests = [
        {"id": "group-soon", "status": "pending", "request_type": "delete_group", "group_id": "g1", "group_name": "Research",
         "requester_id": "owner-2", "created_at": at(days=-2), "expires_at": at(hours=12)},
        {"id": "suspend-mine", "status": "pending", "request_type": "suspend_user", "group_id": "u9",
         "requester_id": "admin-1", "created_at": at(days=-1), "expires_at": at(days=2)},
        {"id": "suspend-other", "status": "pending", "request_type": "suspend_user", "group_id": "u8",
         "requester_id": "safety-2", "created_at": at(hours=-20), "expires_at": at(days=2)},
        {"id": "approved", "status": "approved", "request_type": "delete_group", "approved_at": at(days=-2)},
        {"id": "denied-old", "status": "denied", "request_type": "block_user", "approved_at": at(days=-10)},
        {"id": "auto-denied", "status": "auto_denied", "request_type": "warn_user", "approved_at": at(days=-1)},
        {"id": "executed", "status": "executed", "request_type": "block_user", "approved_at": at(days=-4), "executed_at": at(days=-3)},
        {"id": "failed", "status": "failed", "request_type": "suspend_user", "executed_at": at(days=-1)},
    ]

    with patch.object(approvals, "get_settings", lambda: {}):
        summary = approvals.summarize_visible_approvals(requests, "admin-1", ["Admin"], 7, now=now)
        check(summary["waiting_on_me"] == 2, f"waiting on me: {summary['waiting_on_me']}")
        check(summary["my_pending_requests"] == 1 and summary["pending_visible"] == 3, str(summary))
        check(summary["expiring_within_24h"] == 1, str(summary))
        check(summary["decided_in_window"] == {"approved": 1, "denied": 0, "executed": 1, "failed": 1, "expired": 1},
              str(summary["decided_in_window"]))
        check(summary["pending_by_type"] == [{"request_type": "suspend_user", "count": 2},
                                             {"request_type": "delete_group", "count": 1}], str(summary["pending_by_type"]))
        check([entry["id"] for entry in summary["oldest_actionable"]] == ["group-soon", "suspend-other"],
              str(summary["oldest_actionable"]))
        check(summary["window"] == {"days": 7}, str(summary["window"]))
        wider = approvals.summarize_visible_approvals(requests, "admin-1", ["Admin"], 30, now=now)
        check(wider["decided_in_window"]["denied"] == 1, "a decision inside 30 days was not counted")

        # Without an approving role, nothing waits on the caller, though their own request is theirs.
        reader = approvals.summarize_visible_approvals(requests, "safety-2", ["User", "SafetyViolationAdmin"], 7, now=now)
        check(reader["waiting_on_me"] == 0 and reader["my_pending_requests"] == 1, str(reader))
        # Only the list given is ever counted: a request the caller cannot see is not there.
        hidden = approvals.summarize_visible_approvals(requests[:1], "admin-1", ["Admin"], 7, now=now)
        check(hidden["pending_visible"] == 1 and hidden["waiting_on_me"] == 1, str(hidden))

    # The route, with its real decorators, reading through get_pending_approvals.
    source = (root / "application" / "single_app" / "route_backend_control_center.py").read_text(encoding="utf-8")
    registrar = next(node for node in ast.parse(source).body
                     if isinstance(node, ast.FunctionDef) and node.name == "register_route_backend_control_center")
    names = [node.name for node in registrar.body if isinstance(node, ast.FunctionDef)]
    check(names.index("api_get_approval_stats") < names.index("api_get_approval_by_id"),
          "the stats route must be registered before /api/approvals/<approval_id>")
    handler = next(node for node in registrar.body
                   if isinstance(node, ast.FunctionDef) and node.name == "api_get_approval_stats")
    decorators = [ast.unparse(item) for item in handler.decorator_list]
    check(decorators == ["bp.route('/api/approvals/stats', methods=['GET'])",
                         "swagger_route(security=get_auth_security())", "login_required"], str(decorators))

    calls = []

    def get_pending_approvals(**kwargs):
        calls.append(kwargs)
        return {"approvals": requests if kwargs["user_id"] == "admin-1" else requests[2:3]}

    bp = Blueprint("backend_control_center", "approvals_stats_probe")
    namespace = {
        "bp": bp, "swagger_route": lambda **kwargs: (lambda function: function), "get_auth_security": lambda: [],
        "login_required": auth.login_required, "request": request, "session": session, "jsonify": jsonify,
        "parse_review_window": review_center.parse_review_window, "get_pending_approvals": get_pending_approvals,
        "summarize_visible_approvals": approvals.summarize_visible_approvals,
        "APPROVAL_STATS_SCAN_LIMIT": approvals.APPROVAL_STATS_SCAN_LIMIT,
        "log_event": lambda *args, **kwargs: None, "logging": logging,
    }
    exec(compile(ast.Module(body=[handler], type_ignores=[]), "approvals-stats-route", "exec"), namespace)
    app = Flask("approvals-stats-probe")
    app.secret_key = "offline-test-only"
    app.register_blueprint(bp)
    client = _test_client(app)

    with patch.object(approvals, "get_settings", lambda: {}), patch.object(auth, "debug_print", lambda *a, **k: None):
        response = client.get("/api/approvals/stats")
        check(response.status_code == 401 and not calls, f"an anonymous caller was answered: {response.status_code}")
        sign_in(client, "admin-1", roles=("Admin",))
        response = client.get("/api/approvals/stats?days=90")
        body = response.get_json()
        check(response.status_code == 200 and body["window"] == {"days": 90}, str(body))
        check(body["pending_visible"] == 3 and body["my_pending_requests"] == 1, str(body))
        call = calls[-1]
        check(call["user_id"] == "admin-1" and list(call["user_roles"]) == ["Admin"], str(call))
        check(call["include_completed"] is True and call["status_filter"] == "all", str(call))
        check(call["per_page"] == approvals.APPROVAL_STATS_SCAN_LIMIT, str(call))
        check(client.get("/api/approvals/stats").get_json()["window"] == {"days": 30}, "the default window is not 30 days")
        check(client.get("/api/approvals/stats?days=14").status_code == 400, "an unsupported window was accepted")
        sign_in(client, "safety-2", roles=("User", "SafetyViolationAdmin"))
        body = client.get("/api/approvals/stats?days=7").get_json()
        check(body["pending_visible"] == 1 and body["waiting_on_me"] == 0, f"another user's view: {body}")
        sign_out(client)

print("PASS: the approvals summary counts only what the caller can see")
'''


@pytest.mark.parametrize("optimized", [False, True])
def test_approvals_summary_counts_only_visible_requests(optimized):
    command = [sys.executable, "-B"]
    if optimized:
        command.append("-O")
    result = subprocess.run(
        command + ["-c", STATS_PROBE, str(ROOT)],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: the approvals summary counts only what the caller can see" in result.stdout


def test_version():
    assert_app_version_at_least("0.261.298")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
