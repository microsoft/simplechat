#!/usr/bin/env python3
# test_review_assist_policy.py
"""
Functional policy tests for the Review center AI assist routes.
Version: 0.261.299
Implemented in: 0.261.299

This test ensures that ``POST /api/admin/review/feedback/assist`` and
``POST /api/admin/review/safety/assist`` keep their Blueprint, Swagger, authentication and
section reviewer decorators -- the same ones as the records each route reads -- check the
assistant's Admin Settings toggle before any service starts, read records only from their own
section's container, and settle a violation before reading it. Running the real routes on a closed
Flask app, it checks that a disabled assistant and a caller without the section's reviewer role are
refused before the limiter, the model or the store is used, and that every answer is uncached JSON
that never echoes settings. No Azure service is used.
"""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "application" / "single_app"
sys.path.insert(0, str(ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402


ROUTES = {
    "feedback": {
        "file": APP / "route_backend_feedback.py",
        "function": "feedback_review_assist",
        "decorators": [
            "bp.route('/api/admin/review/feedback/assist', methods=['POST'])",
            "swagger_route(security=get_auth_security())",
            "login_required",
            "feedback_admin_required",
            "enabled_required('enable_user_feedback')",
        ],
        "container": "cosmos_feedback_container",
    },
    "safety": {
        "file": APP / "route_backend_safety.py",
        "function": "safety_review_assist",
        "decorators": [
            "bp.route('/api/admin/review/safety/assist', methods=['POST'])",
            "swagger_route(security=get_auth_security())",
            "login_required",
            "safety_violation_admin_required",
            "content_checks_report_enabled",
        ],
        "container": "cosmos_safety_container",
    },
}


def route_function(section):
    spec = ROUTES[section]
    tree = ast.parse(spec["file"].read_text(encoding="utf-8"))
    matches = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == spec["function"]
    ]
    assert len(matches) == 1, f"expected one {spec['function']}, found {len(matches)}"
    return matches[0]


def calls_in_order(function):
    return [
        ast.unparse(node.func) for node in ast.walk(function)
        if isinstance(node, ast.Call)
    ]


@pytest.mark.parametrize("section", sorted(ROUTES))
def test_the_routes_keep_their_blueprint_swagger_auth_and_reviewer_decorators(section):
    assert_app_version_at_least("0.261.299")
    function = route_function(section)
    assert [ast.unparse(decorator) for decorator in function.decorator_list] == ROUTES[section]["decorators"]


@pytest.mark.parametrize("section", sorted(ROUTES))
def test_the_toggle_is_checked_before_any_service_and_records_come_from_the_section(section):
    function = route_function(section)
    body = function.body
    toggle_index = next(
        index for index, statement in enumerate(body)
        if isinstance(statement, ast.If) and "is_admin_review_assistant_enabled" in ast.unparse(statement.test)
    )
    refusal = ast.unparse(body[toggle_index].body[0])
    assert "review_assist_error_response(ReviewAssistError('review_assistant_disabled')" in refusal
    handle_index = next(
        index for index, statement in enumerate(body)
        if "handle_review_assist_request" in ast.unparse(statement)
    )
    assert toggle_index < handle_index
    source = ast.unparse(function)
    other = "cosmos_safety_container" if section == "feedback" else "cosmos_feedback_container"
    assert f"container={ROUTES[section]['container']}" in source
    assert other not in source, "an assist route must read only its own section's records"
    assert "request.get_json" not in source and "request.json" not in source, "the body is read by the runtime, strictly"
    if section == "safety":
        assert "prepare=reconcile_pending_safety_log" in source
        assert "safety_warning_send_in_progress(record)" in source


GATE_PROBE = r'''
import json
import sys
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

root = Path(sys.argv[1])
sys.path.insert(0, str(root / "functional_tests"))
sys.path.insert(0, str(root / "application" / "single_app"))
from test_support.offline_bootstrap import offline_app_imports
from test_support.safety_review_harness import build_feedback_app, build_safety_app, check, sign_in

SECRET = "SECRET-SETTING-VALUE-5c1d"

with offline_app_imports(), ExitStack() as stack:
    import functions_review_assist_runtime as runtime

    built = []

    def refuse_build(**kwargs):
        built.append(kwargs)
        raise AssertionError("a refused request built the assistant's services")

    stack.enter_context(patch.object(runtime, "build_review_assist_services", refuse_build))
    for section, build, path, reviewer_flag, record in (
        ("feedback", build_feedback_app, "/api/admin/review/feedback/assist", "require_member_of_feedback_admin",
         {"id": "fb-1", "userId": "user-1", "feedbackType": "Negative", "prompt": "p", "adminReview": {}}),
        ("safety", build_safety_app, "/api/admin/review/safety/assist", "require_member_of_safety_violation_admin",
         {"id": "log-1", "user_id": "user-1", "status": "New", "action": "None", "message": "m"}),
    ):
        with ExitStack() as inner:
            h = build(inner)
            h.container.seed(record)
            reads = []
            original_read = h.container.read_item

            def counting_read(*args, **kwargs):
                reads.append(args or kwargs)
                return original_read(*args, **kwargs)

            h.container.read_item = counting_read
            h.settings["azure_openai_gpt_key"] = SECRET
            h.settings["admin_review_ai_guidance"] = SECRET
            body = {"mode": "triage", "ids": [record["id"]]}

            # Off by default.
            sign_in(h.client, "reviewer-1", roles=("Admin",))
            response = h.client.post(path, json=body)
            check(response.status_code == 403, f"{section}: {response.status_code}")
            check(response.get_json()["code"] == "review_assistant_disabled", f"{section}: {response.get_json()}")
            check(response.headers["Cache-Control"] == "no-store, private", f"{section}: cacheable refusal")
            check(SECRET not in response.get_data(as_text=True), f"{section}: settings echoed")

            # On, but the caller lacks the section's reviewer role.
            h.settings["enable_admin_review_ai_assistant"] = True
            h.settings[reviewer_flag] = True
            response = h.client.post(path, json=body)
            check(response.status_code == 403, f"{section}: a non-reviewer got {response.status_code}")
            check(SECRET not in response.get_data(as_text=True), f"{section}: settings echoed")
            other = h.new_client()
            sign_in(other, "user-1", roles=("User",))
            check(other.post(path, json=body).status_code == 403, f"{section}: a user reached the assistant")
            check(reads == [] and built == [], f"{section}: a refused request read records or built services")

print("PASS: review assist gates refuse before any service")
'''


@pytest.mark.parametrize("optimized", [False, True])
def test_refused_requests_never_reach_a_service(optimized):
    command = [sys.executable, "-B"]
    if optimized:
        command.append("-O")
    result = subprocess.run(
        command + ["-c", GATE_PROBE, str(ROOT)],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: review assist gates refuse before any service" in result.stdout


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
