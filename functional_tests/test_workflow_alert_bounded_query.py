#!/usr/bin/env python3
# test_workflow_alert_bounded_query.py
"""
Functional test for the bounded workflow alert pop-up query.
Version: 0.261.199
Implemented in: 0.261.199

This test ensures get_unread_workflow_priority_notifications pushes its unread,
not-dismissed, not-notify-only and optional recency filters into one parameterized,
TOP-limited Cosmos query, keeps the Python re-check and response decoration, validates
the since_hours window, leaves the classic caller unchanged (a failed read is still an
empty list there), raises a failed read for the V2 caller that asks it to, and that new
workflow alerts record the workflow's scope so V2 can link back to the right workflows
list, under keys classic does not read as the group to make active.
"""

import ast
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
import logging
from pathlib import Path
import sys
import types
from unittest.mock import Mock, patch

import pytest


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
sys.path.insert(0, str(APP))
sys.path.insert(0, str(ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least


def load_notifications(records):
    """Load functions_notifications.py with storage and logging replaced by recorders."""
    calls = []

    def query_items(query, parameters=None, partition_key=None, **kwargs):
        calls.append({"query": query, "parameters": parameters or [], "partition_key": partition_key})
        return deepcopy(records)

    debug = Mock()
    replacements = {}
    for name, values in {
        "config": {"cosmos_notifications_container": types.SimpleNamespace(query_items=query_items)},
        "functions_appinsights": {"log_event": Mock()},
        "functions_debug": {"debug_print": debug},
        "functions_group": {"find_group_by_id": Mock(), "get_user_groups": lambda user: []},
        "functions_public_workspaces": {
            "find_public_workspace_by_id": Mock(),
            "get_user_public_workspaces": lambda user: [],
        },
    }.items():
        module = types.ModuleType(name)
        module.__dict__.update(values)
        replacements[name] = module
    spec = importlib.util.spec_from_file_location("test_bounded_alert_notifications", APP / "functions_notifications.py")
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, replacements):
        spec.loader.exec_module(module)
    return module, calls, debug


def alert(alert_id, **overrides):
    record = {
        "id": alert_id,
        "user_id": "owner",
        "notification_type": "workflow_priority_alert",
        "title": f"Alert {alert_id}",
        "message": "Something happened",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "read_by": [],
        "dismissed_by": [],
        "metadata": {"priority": "high", "category": "alert", "delivery": "popup"},
    }
    record.update(overrides)
    return record


def parameters_by_name(call):
    return {parameter["name"]: parameter["value"] for parameter in call["parameters"]}


def test_query_is_parameterized_limited_and_filtered_in_cosmos():
    assert_app_version_at_least("0.261.199")
    notifications, calls, debug = load_notifications([alert("a1")])
    hostile_user = "owner' OR 1=1 --"

    notifications.get_unread_workflow_priority_notifications(hostile_user, limit=3)

    assert len(calls) == 1
    query = calls[0]["query"]
    assert query.startswith("SELECT TOP @limit * FROM c WHERE c.user_id = @user_id")
    assert "AND c.notification_type = @notification_type" in query
    assert "AND (NOT IS_ARRAY(c.read_by) OR NOT ARRAY_CONTAINS(c.read_by, @user_id))" in query
    assert "AND (NOT IS_ARRAY(c.dismissed_by) OR NOT ARRAY_CONTAINS(c.dismissed_by, @user_id))" in query
    assert (
        "AND (NOT IS_STRING(c.metadata.delivery) OR LOWER(TRIM(c.metadata.delivery)) != @notify_only)"
    ) in query
    assert query.endswith("ORDER BY c.created_at DESC")
    assert "@created_after" not in query
    assert hostile_user not in query
    assert "notify_only'" not in query and "workflow_priority_alert" not in query
    assert parameters_by_name(calls[0]) == {
        "@limit": 3,
        "@user_id": hostile_user,
        "@notification_type": "workflow_priority_alert",
        "@notify_only": "notify_only",
    }
    assert calls[0]["partition_key"] == hostile_user
    debug.assert_not_called()


@pytest.mark.parametrize(
    ("requested", "expected"),
    [(None, 5), (0, 5), (1, 1), (5, 5), (10, 10), (11, 10), (500, 10), (-3, 1), ("abc", 5), ("7", 7)],
)
def test_limit_is_clamped_to_between_one_and_ten(requested, expected):
    notifications, calls, _ = load_notifications([])

    notifications.get_unread_workflow_priority_notifications("owner", limit=requested)

    assert parameters_by_name(calls[0])["@limit"] == expected


def test_since_hours_adds_a_bounded_created_after_window():
    notifications, calls, _ = load_notifications([])
    before = datetime.now(timezone.utc)

    notifications.get_unread_workflow_priority_notifications("owner", limit=10, since_hours=24)

    after = datetime.now(timezone.utc)
    query = calls[0]["query"]
    assert "AND c.created_at >= @created_after ORDER BY c.created_at DESC" in query
    created_after = parameters_by_name(calls[0])["@created_after"]
    assert created_after.endswith("+00:00")
    parsed = datetime.fromisoformat(created_after)
    assert before - timedelta(hours=24) <= parsed <= after - timedelta(hours=24)
    assert parameters_by_name(calls[0])["@limit"] == 10


def test_python_recheck_and_response_decoration_are_unchanged():
    records = [
        alert("read", read_by=["owner"]),
        alert("dismissed", dismissed_by=["owner"]),
        alert("quiet", metadata={"priority": "low", "delivery": " Notify_Only "}),
        alert("failure", metadata={"priority": "critical", "category": "failure", "delivery": "popup"}),
        alert("legacy", metadata={"priority": "medium"}),
        alert("other-reader", read_by=["someone-else"]),
    ]
    notifications, _, debug = load_notifications(records)

    popups = notifications.get_unread_workflow_priority_notifications("owner", limit=10)

    assert [item["id"] for item in popups] == ["failure", "legacy", "other-reader"]
    failure = popups[0]
    assert failure["is_read"] is False and failure["is_dismissed"] is False
    assert failure["priority"] == "critical"
    assert failure["category"] == "failure"
    assert failure["delivery"] == "popup"
    assert failure["type_config"] == {"icon": "bi-x-octagon", "color": "danger"}
    assert failure["message"] == "Something happened"
    legacy = popups[1]
    assert legacy["delivery"] == "popup" and legacy["category"] == "alert"
    assert legacy["type_config"] == {"icon": "bi-exclamation-circle", "color": "warning"}
    debug.assert_not_called()


def test_python_recheck_still_stops_at_the_limit():
    notifications, _, _ = load_notifications([alert(f"a{index}") for index in range(8)])

    popups = notifications.get_unread_workflow_priority_notifications("owner", limit=2)

    assert [item["id"] for item in popups] == ["a0", "a1"]


@pytest.mark.parametrize(("value", "expected"), [(None, None), ("1", 1), ("24", 24), ("1440", 1440), (24, 24), (1, 1)])
def test_since_hours_parser_accepts_whole_hours_inside_the_ttl(value, expected):
    notifications, _, _ = load_notifications([])

    parsed = notifications.parse_workflow_alert_since_hours(value)

    assert parsed == expected
    assert notifications.WORKFLOW_ALERT_SINCE_HOURS_MAX == 1440


@pytest.mark.parametrize(
    "value",
    ["", "0", "1441", "9999", "99999", "-1", "+24", " 24", "24 ", "24.5", "2e1", "abc", "\u0661\u0662", "\u00b2",
     0, 1441, -5, True, False, 1.5, [], {}],
)
def test_since_hours_parser_rejects_everything_else(value):
    notifications, _, _ = load_notifications([])

    with pytest.raises(ValueError):
        notifications.parse_workflow_alert_since_hours(value)


def test_invalid_since_hours_raises_instead_of_widening_the_window():
    notifications, calls, _ = load_notifications([alert("a1")])

    with pytest.raises(ValueError):
        notifications.get_unread_workflow_priority_notifications("owner", since_hours="forever")

    assert calls == []


def break_storage(notifications):
    """Make every Cosmos query fail, and record that one was attempted."""
    attempts = []

    def broken_query(*args, **kwargs):
        attempts.append(kwargs.get("query") or (args[0] if args else None))
        raise RuntimeError("storage unavailable")

    notifications.cosmos_notifications_container = types.SimpleNamespace(query_items=broken_query)
    return attempts


def test_query_failure_still_returns_an_empty_list():
    """The classic caller keeps the empty list it has always had for a failed read."""
    notifications, _, debug = load_notifications([])
    attempts = break_storage(notifications)

    popups = notifications.get_unread_workflow_priority_notifications("owner")

    assert popups == []
    assert len(attempts) == 1
    debug.assert_called_once()


def test_query_failure_is_raised_for_a_caller_that_must_not_read_it_as_empty():
    """V2 reads a short list as everything unread, so its failed read is raised, not emptied."""
    notifications, _, debug = load_notifications([])
    attempts = break_storage(notifications)

    with pytest.raises(RuntimeError, match="storage unavailable"):
        notifications.get_unread_workflow_priority_notifications(
            "owner", limit=10, since_hours=24, raise_on_error=True,
        )

    assert len(attempts) == 1
    debug.assert_called_once()


def test_classic_interface_keeps_its_request_and_cadence():
    notifications_js = (APP / "static" / "js" / "notifications.js").read_text(encoding="utf-8")

    assert "/api/notifications/workflow-alerts?limit=5" in notifications_js
    assert "since_hours" not in notifications_js


def load_alert_creator(captured):
    """Exec the runner's real alert builder with its collaborators replaced."""
    runner = APP / "functions_workflow_runner.py"
    names = {"_create_workflow_priority_alert", "_get_workflow_scope", "_get_workflow_group_id"}
    tree = ast.parse(runner.read_text(encoding="utf-8-sig"))
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert len(functions) == len(names)
    decision = {
        "should_alert": True, "severity": "high", "category": "alert", "delivery": "popup",
        "mode": "rules", "matched_rules": [],
    }
    namespace = {
        "logging": logging,
        "log_event": Mock(),
        "get_workflow_alert_signals": lambda: [],
        "resolve_workflow_alert_config": lambda workflow: {"alert_mode": "rules"},
        "build_workflow_alert_facts": lambda *args: {},
        "_workflow_alert_rules_need_model_evaluation": lambda *args: False,
        "_build_workflow_alert_model_evaluator": Mock(),
        "evaluate_workflow_alert_rules": lambda *args, **kwargs: dict(decision),
        "sanitize_workflow_alert_decision": lambda value: value,
        "_record_workflow_alert_decision": Mock(),
        "summarize_alert_decision": lambda value: "A rule matched.",
        "normalize_alert_severity": lambda value: value,
        "_normalize_workflow_alert_title_text": lambda value: value,
        "_build_workflow_alert_target_from_conversation": lambda conversation, default_label: None,
        "_select_preferred_workflow_alert_targets": lambda targets: targets,
        "_build_workflow_alert_content": lambda *args, **kwargs: {"alert_title": "Title"},
        "_summarize_workflow_alert_text": lambda value: value,
        "create_workflow_priority_notification": lambda **kwargs: captured.append(kwargs) or {"id": "n1"},
    }
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(runner), "exec"), namespace)
    return namespace["_create_workflow_priority_alert"]


@pytest.mark.parametrize(
    ("workflow", "scope", "group_id"),
    [
        ({"id": "wf-1", "user_id": "owner", "name": "Mine"}, "personal", ""),
        ({"id": "wf-2", "user_id": "owner", "name": "Team", "group_id": " group-7 "}, "group", "group-7"),
    ],
)
def test_new_alerts_record_the_workflow_scope(workflow, scope, group_id):
    captured = []
    create_alert = load_alert_creator(captured)

    result = create_alert(workflow, {"id": "run-1", "status": "completed"}, {"id": "conversation-1"})

    assert result == {"id": "n1"}
    metadata = captured[0]["metadata"]
    assert metadata["workflow_scope"] == scope
    assert metadata["workflow_group_id"] == group_id
    # Classic's notification click makes metadata.group_id the active group when the link it
    # opens names none, so the workflow's group must not be written under that key.
    assert "group_id" not in metadata
    assert metadata["workflow_id"] == workflow["id"]
    assert metadata["run_id"] == "run-1"


if __name__ == "__main__":
    sys.exit(pytest.main([str(Path(__file__).resolve()), "-q"]))
