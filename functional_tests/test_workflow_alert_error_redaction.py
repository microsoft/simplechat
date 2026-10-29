# test_workflow_alert_error_redaction.py
"""
Workflow alert exception-disclosure regressions.
Version: 0.261.030
Implemented in: 0.261.030

Exercises real alert evaluation and public projections with isolated logging
and storage I/O, including historical runs and notification payloads.
"""

import ast
from copy import deepcopy
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys
import types
from unittest.mock import Mock, patch

from flask import Flask, jsonify, session
import pytest


APP = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP))

# Standalone tests initialize the source path before importing repository modules.
from functions_m365_workflow_binding import (
    M365_ACTIVE_STATES,
    build_waiting_workflow_result,
    workflow_result_is_waiting,
    workflow_result_runtime_status,
)
from functions_workflow_alert_safety import (
    WORKFLOW_ALERT_EVALUATION_ERROR_CODE,
    WORKFLOW_ALERT_EVALUATION_ERROR_MESSAGE,
    sanitize_workflow_alert_decision,
    sanitize_workflow_alert_record,
)


CANARY = "CODEQL_PRIVATE_DIAGNOSTIC_internal-provider-connection"


def load_alerts():
    logger = types.ModuleType("functions_appinsights")
    logger.log_event = Mock()
    spec = importlib.util.spec_from_file_location("test_safe_alert_evaluation", APP / "functions_workflow_alerts.py")
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"functions_appinsights": logger}):
        spec.loader.exec_module(module)
    return module, logger.log_event


def load_functions(filename, names, namespace):
    tree = ast.parse((APP / filename).read_text(encoding="utf-8-sig"))
    functions = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    if len(functions) != len(names):
        raise AssertionError("The requested production projection functions were not found.")
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(APP / filename), "exec"), namespace)
    return namespace


@pytest.mark.parametrize("on_error", ["alert", "skip"])
def test_evaluation_keeps_diagnostics_in_logs_not_public_decisions(on_error):
    alerts, logger = load_alerts()
    workflow = {
        "id": "workflow", "alert_mode": "rules",
        "alert_evaluation": {"on_error": on_error},
        "alert_rules": alerts.normalize_alert_rules([{
            "id": "model-rule", "name": "Check report", "severity": "medium",
            "condition": {"type": "model_evaluation", "prompt": "Check this report"},
        }]),
    }
    facts = alerts.build_workflow_alert_facts(
        workflow, {"id": "run", "status": "completed", "success": True}, {"reply": "A report"},
    )

    def fail_model(prompt):
        raise RuntimeError(CANARY)

    decision = alerts.evaluate_workflow_alert_rules(workflow, facts, model_evaluator=fail_model)
    assert decision["should_alert"] is (on_error == "alert")
    assert CANARY not in json.dumps(decision)
    assert decision["model_evaluation"]["error_code"] == WORKFLOW_ALERT_EVALUATION_ERROR_CODE
    assert decision["model_evaluation"]["error"] == WORKFLOW_ALERT_EVALUATION_ERROR_MESSAGE
    assert any(CANARY in str(call.args) for call in logger.call_args_list)
    assert logger.call_args.kwargs["extra"] == {"workflow_id": "workflow", "run_id": "run"}
    if on_error == "alert":
        assert decision["category"] == "failure"
        assert decision["matched_rules"][0]["reason_code"] == WORKFLOW_ALERT_EVALUATION_ERROR_CODE


def historical_decision():
    return {
        "should_alert": True, "mode": "rules", "severity": "medium", "category": "failure",
        "matched_rules": [
            {"rule_id": "unsafe", "rule_name": "Model rule", "condition_type": "model_evaluation",
             "reason": f"Alert condition could not be evaluated: {CANARY}"},
            {"rule_id": "useful", "rule_name": "Useful rule", "condition_type": "model_evaluation",
             "reason": "Two certificates expire tomorrow.", "source": "model_evaluation"},
        ],
        "model_evaluation": {"used": True, "error": CANARY},
    }


def test_historical_records_and_notification_details_are_scrubbed_without_mutation():
    decision = historical_decision()
    old_reason = decision["matched_rules"][0]["reason"]
    notification = {
        "notification_type": "workflow_priority_alert",
        "message": "A workflow alert",
        "metadata": {
            **decision,
            "alert_detail": f"Triggered by\n- Model rule: {old_reason}\n\nThe workflow completed.",
        },
    }
    original = deepcopy(notification)
    safe = sanitize_workflow_alert_record(notification)
    assert CANARY not in json.dumps(safe)
    assert "Two certificates expire tomorrow." in json.dumps(safe)
    assert "The workflow completed." in safe["metadata"]["alert_detail"]
    assert notification == original


def test_real_model_explanations_are_not_treated_as_legacy_errors():
    reason = "Alert condition could not be evaluated: this is a quoted statement in the report."
    decision = {
        "matched_rules": [{
            "condition_type": "model_evaluation", "source": "model_evaluation", "reason": reason,
        }],
    }
    safe = sanitize_workflow_alert_decision(decision)
    assert safe["matched_rules"][0]["reason"] == reason


def test_match_provenance_is_preserved_when_error_and_model_reasons_have_identical_text():
    reason = "Alert condition could not be evaluated: a quoted report statement."
    safe = sanitize_workflow_alert_decision({
        "matched_rules": [
            {"source": "model_evaluation_error", "reason": reason},
            {"source": "model_evaluation", "reason": reason},
        ],
    })
    assert safe["matched_rules"][0]["reason"] == WORKFLOW_ALERT_EVALUATION_ERROR_MESSAGE
    assert safe["matched_rules"][1] == {"source": "model_evaluation", "reason": reason}


@pytest.mark.parametrize("scope", ["personal", "group"])
@pytest.mark.parametrize("mode", ["run", "resume"])
@pytest.mark.parametrize("status", ["completed", "failed", "awaiting_approval", "awaiting_sign_in"])
def test_real_run_resume_handlers_preserve_status_and_exclude_diagnostics(scope, mode, status):
    alerts, _ = load_alerts()
    saved = []
    namespace = load_functions(
        "functions_workflow_runner.py", {"_record_workflow_alert_decision"},
        {
            "sanitize_workflow_alert_decision": sanitize_workflow_alert_decision,
            "summarize_alert_decision": alerts.summarize_alert_decision,
            "_save_workflow_run_record": lambda workflow, run: saved.append(deepcopy(run)),
        },
    )
    workflow = {"id": "workflow", "status": "ready", "user_id": "owner"}
    run = {"id": "run", "workflow_id": "workflow", "status": status, "success": status == "completed"}
    namespace["_record_workflow_alert_decision"](workflow, run, historical_decision())
    approval = {
        "status": status, "approval_id": "approval", "profile_url": "/profile",
        "scopes": ["Mail.Read"], "message": "Your Microsoft 365 decision is required.",
    }
    result = (
        build_waiting_workflow_result(workflow, run, approval)
        if status.startswith("awaiting_") else {"success": run["success"], "run": run}
    )
    handlers = {
        ("personal", "run"): "run_user_workflow",
        ("group", "run"): "run_group_workflow_route",
        ("personal", "resume"): "resume_failed_user_workflow_items",
        ("group", "resume"): "resume_failed_group_workflow_items",
    }
    name = handlers[(scope, mode)]
    tree = ast.parse((APP / "route_backend_workflows.py").read_text(encoding="utf-8"))
    handler = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name)
    handler.decorator_list = []
    release = Mock()
    route_namespace = {
        "jsonify": jsonify, "session": session, "datetime": datetime, "timezone": timezone,
        "M365_ACTIVE_STATES": M365_ACTIVE_STATES,
        "get_current_user_id": lambda: "owner",
        "get_personal_workflow": lambda *args: workflow,
        "get_group_workflow": lambda *args: workflow,
        "get_personal_workflow_run": lambda *args: run,
        "get_group_workflow_run": lambda *args: run,
        "list_personal_workflow_run_items": lambda *args, **kwargs: [{"status": "failed", "document_id": "doc"}],
        "list_group_workflow_run_items": lambda *args, **kwargs: [{"status": "failed", "document_id": "doc"}],
        "_normalize_identifier": lambda value: str(value or "").strip(),
        "_resolve_active_group_for_workflows": lambda user: ("group", {}),
        "_build_resume_failed_workflow": lambda original, items: dict(original),
        "acquire_distributed_task_lock": lambda *args, **kwargs: {"id": "lease"},
        "release_distributed_task_lock": release,
        "create_workflow_run_id": lambda: "run",
        "run_personal_workflow": lambda *args, **kwargs: result,
        "run_group_workflow": lambda *args, **kwargs: result,
        "update_personal_workflow_runtime_fields": lambda user, workflow_id, changes: {**workflow, **changes},
        "update_group_workflow_runtime_fields": lambda group, workflow_id, changes: {**workflow, **changes},
        "workflow_result_runtime_status": workflow_result_runtime_status,
        "workflow_result_is_waiting": workflow_result_is_waiting,
    }
    exec(compile(ast.Module(body=[handler], type_ignores=[]), str(APP / "route_backend_workflows.py"), "exec"), route_namespace)
    app = Flask(__name__)
    app.secret_key = "unit-test-only"
    with app.test_request_context(method="POST"):
        session["user"] = {"oid": "owner", "roles": ["User"]}
        arguments = {"run_id": "source-run"} if mode == "resume" else {}
        response = app.make_response(route_namespace[name]("workflow", **arguments))
        body = response.get_data(as_text=True)
        payload = response.get_json()
    assert CANARY not in body
    assert CANARY not in json.dumps(saved)
    assert "Two certificates expire tomorrow." in body
    assert response.status_code == (202 if status.startswith("awaiting_") else 200 if status == "completed" else 500)
    assert payload["run"]["status"] == status
    if status.startswith("awaiting_"):
        assert payload["run"]["m365_approval"] == approval
        assert payload["run"]["completed_at"] is None
    release.assert_called_once_with({"id": "lease"})


def test_shared_store_and_activity_projections_cover_old_run_data():
    namespace = load_functions(
        "functions_personal_workflows.py", {"_strip_cosmos_metadata"},
        {"sanitize_workflow_alert_record": sanitize_workflow_alert_record},
    )
    original = {"id": "run", "status": "completed", "_etag": "old", "alert_decision": historical_decision()}
    stored = namespace["_strip_cosmos_metadata"](original)
    activity = load_functions(
        "functions_workflow_activity.py", {"_serialize_run"},
        {"sanitize_workflow_alert_record": sanitize_workflow_alert_record},
    )["_serialize_run"](original)
    assert CANARY not in json.dumps(stored)
    assert CANARY not in json.dumps(activity)
    assert CANARY in json.dumps(original)


@pytest.mark.parametrize("scope", ["personal", "group"])
def test_activity_stream_uses_scrubbed_historical_run_projection(scope):
    original = {"id": "run", "status": "completed", "alert_decision": historical_decision()}
    activity = load_functions(
        "functions_workflow_activity.py", {"_serialize_run"},
        {"sanitize_workflow_alert_record": sanitize_workflow_alert_record},
    )
    snapshot = {"run": activity["_serialize_run"](original), "live": False}
    functions = load_functions(
        "route_backend_workflows.py", {"_stream_workflow_activity", "_stream_group_workflow_activity"},
        {
            "json": json, "time": types.SimpleNamespace(sleep=Mock()),
            "M365_ACTIVE_STATES": M365_ACTIVE_STATES,
            "_resolve_workflow_activity_context": lambda *args, **kwargs: snapshot,
            "_resolve_group_workflow_activity_context": lambda *args, **kwargs: snapshot,
        },
    )
    events = list(
        functions["_stream_group_workflow_activity"]("owner", "group")
        if scope == "group" else functions["_stream_workflow_activity"]("owner")
    )
    assert CANARY not in "".join(events)
    assert WORKFLOW_ALERT_EVALUATION_ERROR_MESSAGE in "".join(events)
    assert any(event.startswith("data: ") for event in events)


def test_notification_read_boundaries_scrub_old_alerts_but_preserve_approval_payloads():
    decision = historical_decision()
    records = [
        {
            "id": "alert", "user_id": "owner", "notification_type": "workflow_priority_alert",
            "message": "Workflow alert", "metadata": {
                **decision, "priority": "high",
                "alert_detail": decision["matched_rules"][0]["reason"],
            },
        },
        {
            "id": "approval", "user_id": "owner", "notification_type": "m365_approval_pending",
            "message": "Approve sharing your source", "metadata": {
                "approval_id": "approval", "request_type": "m365_source_sharing",
                "execution_status": "awaiting_approval",
            },
        },
    ]
    original = deepcopy(records)

    def query_items(query, **kwargs):
        if "c.scope = 'assignment'" in query:
            return []
        return records[:1] if "@notification_type" in query else records

    logger = Mock()
    replacements = {}
    for name, values in {
        "config": {"cosmos_notifications_container": types.SimpleNamespace(query_items=query_items)},
        "functions_appinsights": {"log_event": Mock()},
        "functions_debug": {"debug_print": logger},
        "functions_group": {"find_group_by_id": Mock(), "get_user_groups": lambda user: []},
        "functions_public_workspaces": {"find_public_workspace_by_id": Mock(), "get_user_public_workspaces": lambda user: []},
    }.items():
        module = types.ModuleType(name)
        module.__dict__.update(values)
        replacements[name] = module
    spec = importlib.util.spec_from_file_location("test_safe_notifications", APP / "functions_notifications.py")
    notifications = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, replacements):
        spec.loader.exec_module(notifications)
        page = notifications.get_user_notifications("owner")
        popups = notifications.get_unread_workflow_priority_notifications("owner")
    assert page["total"] == 2
    assert len(popups) == 1
    assert CANARY not in json.dumps(page)
    assert CANARY not in json.dumps(popups)
    assert page["notifications"][1]["metadata"] == original[1]["metadata"]
    assert records == original
    logger.assert_not_called()


if __name__ == "__main__":
    sys.exit(pytest.main([str(Path(__file__).resolve())]))
