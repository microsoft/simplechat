# test_workflow_alert_reviewed_messages.py
#!/usr/bin/env python3
"""
Functional test for reviewed workflow alert validation messages on both save routes.
Version: 0.261.149
Implemented in: 0.261.144

This test ensures that every validation failure of ``normalize_workflow_alert_settings`` reaches
the client as its own reviewed, data-free message: HTTP 400 with
``{"error": <message>, "code": "invalid_workflow_alerts"}``, on both ``POST /api/user/workflows``
and ``POST /api/group/workflows``. A ``ValueError`` outside the reviewed families still returns
the generic "Invalid workflow settings" message; the File Sync, schedule and trigger families are
covered by ``test_workflow_settings_reviewed_messages.py``. The run-time regex check and alert
evaluation are unchanged.

The two route bodies are compiled from ``route_backend_workflows.py`` and call the REAL
``save_personal_workflow`` and ``save_group_workflow``. These run the real alert, definition,
document action, File Sync and schedule normalizers, loaded by the real-module harness of
``test_group_workflow_round_trip_preservation.py``. Only Cosmos, the group role check, the File
Sync source store and settings are doubled.
"""

import ast
import copy
import logging
import sys
from pathlib import Path

import pytest
from flask import Flask, jsonify, request

sys.path.append(str(Path(__file__).resolve().parent))

from test_group_workflow_round_trip_preservation import (  # noqa: E402  (shared real-module harness)
    GROUP_ID,
    OWNER_ID,
    GroupWorkflowStore,
)


ROUTES_FILE = Path(__file__).resolve().parents[1] / "application" / "single_app" / "route_backend_workflows.py"
GENERIC_400 = "Invalid workflow settings. Review the task, runner, trigger, and document inputs."
MARKER = "PRIVATE-MARKER-7f3a"
VALID_RULE = {"name": "Run failed", "condition": {"type": "run_status", "statuses": ["failed"]}}


def _rule(**fields):
    return {"name": "Rule under test", "condition": {"type": "no_output"}, **fields}


def _condition(condition, **fields):
    return _rule(condition=condition, **fields)


# name: (alert fields merged into a valid payload, reviewed message). The rule under test is the
# second rule, so the message names position 2.
CASES = {
    "W1_priority": ({"alert_priority": "urgent"}, "Alert priority must be none, low, medium or high."),
    "W2_mode": ({"alert_mode": "sometimes"}, "Alert mode must be off, every_run or rules."),
    "W3_rules_without_rules": ({"alert_mode": "rules", "alert_rules": []},
                               "Add at least one alert rule, or choose a different alert mode."),
    "W4_every_run_without_priority": ({"alert_mode": "every_run", "alert_priority": "none"},
                                      "Choose a pop-up priority for alerts on every run, or choose a different alert mode."),
    "W5_on_error": ({"alert_evaluation": {"on_error": "retry"}},
                    "Choose skip or alert for model-evaluated conditions that cannot be judged."),
    "W6_rules_not_a_list": ({"alert_rules": MARKER}, "Alert rules must be a list."),
    "W7_too_many_rules": ({"alert_mode": "rules", "alert_rules": [copy.deepcopy(VALID_RULE) for _ in range(21)]},
                          "A workflow can have up to 20 alert rules."),
    "R1_rule_not_an_object": ({"alert_rules": [VALID_RULE, MARKER]}, "Alert rule 2 is invalid."),
    "R2_name_too_long": ({"alert_rules": [VALID_RULE, _rule(name=MARKER * 20)]},
                         "Alert rule 2 name must be 120 characters or fewer."),
    "R3_delivery": ({"alert_rules": [VALID_RULE, _rule(delivery=MARKER)]},
                    "Alert rule 2 delivery must be default, notify_only or popup."),
    "R4_severity": ({"alert_rules": [VALID_RULE, _rule(severity=MARKER)]},
                    "Alert rule 2 severity must be info, low, medium, high or critical."),
    "S1_scope_type": ({"alert_rules": [VALID_RULE, _rule(scope={"type": MARKER})]},
                      "Alert rule 2 must look at the final output, any task output, or a specific task."),
    "S2_scope_task_missing": ({"alert_rules": [VALID_RULE, _rule(scope={"type": "task", "task_id": ""})]},
                              "Alert rule 2 needs a task to watch."),
    "S3_scope_task_removed": ({"alert_rules": [VALID_RULE, _rule(scope={"type": "task", "task_id": MARKER})]},
                              "Alert rule 2 watches a task that is no longer in this workflow."),
    "C1_condition_type": ({"alert_rules": [VALID_RULE, _condition({"type": MARKER})]},
                          "Alert rule 2 has an unsupported condition type."),
    "C2_run_statuses_not_a_list": ({"alert_rules": [VALID_RULE, _condition({"type": "run_status", "statuses": 5})]},
                                   "Alert rule 2 run statuses must be a list."),
    "C3_run_status_unsupported": ({"alert_rules": [VALID_RULE, _condition({"type": "run_status", "statuses": [MARKER]})]},
                                  "Alert rule 2 has an unsupported run status."),
    "C4_run_status_missing": ({"alert_rules": [VALID_RULE, _condition({"type": "run_status", "statuses": ["", " "]})]},
                              "Alert rule 2 needs at least one run status."),
    "C5_task_statuses_not_a_list": ({"alert_rules": [VALID_RULE, _condition({"type": "task_status", "statuses": {}})]},
                                    "Alert rule 2 task statuses must be a list."),
    "C6_task_status_unsupported": ({"alert_rules": [VALID_RULE, _condition({"type": "task_status", "statuses": [MARKER]})]},
                                   "Alert rule 2 has an unsupported task status."),
    "C7_task_status_missing": ({"alert_rules": [VALID_RULE, _condition({"type": "task_status", "statuses": []})]},
                               "Alert rule 2 needs at least one task status."),
    "C8_text_match_mode": ({"alert_rules": [VALID_RULE, _condition({"type": "text_match", "mode": MARKER, "values": ["x"]})]},
                           "Alert rule 2 text match must be contains_any, contains_all, not_contains or regex."),
    "C9_regex_missing": ({"alert_rules": [VALID_RULE, _condition({"type": "text_match", "mode": "regex", "pattern": " "})]},
                         "Alert rule 2 needs a regex pattern."),
    "C10_regex_too_long": ({"alert_rules": [VALID_RULE, _condition({"type": "text_match", "mode": "regex",
                                                                     "pattern": MARKER * 12})]},
                           "Alert rule 2 regex pattern must be 200 characters or fewer."),
    "C11_regex_nested_quantifier": ({"alert_rules": [VALID_RULE, _condition({"type": "text_match", "mode": "regex",
                                                                              "pattern": f"({MARKER}+)+"})]},
                                    "Alert rule 2 regex pattern uses nested quantifiers, which are not allowed."),
    "C12_regex_invalid": ({"alert_rules": [VALID_RULE, _condition({"type": "text_match", "mode": "regex",
                                                                    "pattern": f"({MARKER}"})]},
                          "Alert rule 2 regex pattern is not a valid regular expression."),
    "C13_values_not_a_list": ({"alert_rules": [VALID_RULE, _condition({"type": "text_match", "values": 5})]},
                              "Alert rule 2 match values must be a list of text."),
    "C14_value_too_long": ({"alert_rules": [VALID_RULE, _condition({"type": "text_match", "values": [MARKER * 30]})]},
                           "Alert rule 2 match values must each be 400 characters or fewer."),
    "C15_values_missing": ({"alert_rules": [VALID_RULE, _condition({"type": "text_match", "values": ["", "  "]})]},
                           "Alert rule 2 needs at least one match value."),
    "C16_too_many_values": ({"alert_rules": [VALID_RULE, _condition({"type": "text_match",
                                                                      "values": [f"value {index}" for index in range(26)]})]},
                            "Alert rule 2 can match up to 25 values."),
    "C17_file_sync_outcome": ({"alert_rules": [VALID_RULE, _condition({"type": "file_sync", "outcome": MARKER})]},
                              "Alert rule 2 File Sync result must be changes_found, no_changes or sync_failed."),
    "C18_model_prompt_missing": ({"alert_rules": [VALID_RULE, _condition({"type": "model_evaluation", "prompt": ""})]},
                                 "Alert rule 2 needs a condition for the model to judge."),
    "C19_model_prompt_too_long": ({"alert_rules": [VALID_RULE, _condition({"type": "model_evaluation",
                                                                            "prompt": MARKER * 120})]},
                                  "Alert rule 2 model condition must be 2000 characters or fewer."),
    "C20_signal_name_too_long": ({"alert_rules": [VALID_RULE, _condition({"type": "agent_signal", "signal_name": MARKER * 8})]},
                                 "Alert rule 2 signal name must be 120 characters or fewer."),
}


def _payload(scope, **alert_fields):
    """A valid V2 definition; the alert fields under test are merged in."""
    payload = {
        "name": "Alerted workflow",
        "definition_version": 2,
        "runner_type": "model",
        "trigger_type": "manual",
        "tasks": [
            {"id": "collect", "type": "instructions", "name": "Collect", "instructions": "Collect.",
             "runner": {"type": "inherit"}},
            {"id": "summarize", "type": "instructions", "name": "Summarize", "instructions": "Summarize.",
             "runner": {"type": "inherit"}},
        ],
        "reference_inputs": [],
    }
    if scope == "group":
        payload["group_id"] = GROUP_ID
    payload.update(copy.deepcopy(alert_fields))
    return payload


class SaveRoutes:
    """Both save route bodies over the real personal and group workflow stores."""

    def __init__(self):
        self.store = GroupWorkflowStore()
        # The harness clock serves a few saves; these tests make many, so keep one fixed time.
        self.store.module._utc_now_iso = lambda: "2026-09-21T12:00:00+00:00"
        personal = self.store.modules["functions_personal_workflows"]
        # The personal model catalogue reads the owner's settings; no personal endpoints exist here.
        personal.get_user_settings = lambda user_id: {"id": user_id, "settings": {}}
        self.personal_container = personal.cosmos_personal_workflows_container
        definitions = self.store.modules["functions_workflow_definitions"]
        namespace = {
            "request": request,
            "jsonify": jsonify,
            "logging": logging,
            "log_event": lambda *args, **kwargs: None,
            "get_current_user_id": lambda: OWNER_ID,
            # The real classes the loaded modules raise, so the routes' except clauses see them.
            "WorkflowDefinitionConflict": definitions.WorkflowDefinitionConflict,
            "WorkflowDefinitionError": definitions.WorkflowDefinitionError,
            "WorkflowPublicValidationError": definitions.WorkflowPublicValidationError,
            "_prepare_workflow_url_access_payload": lambda payload, user_id: payload,
            "_resolve_active_group_for_workflow_management": lambda user_id: (GROUP_ID, {}),
            "_get_current_user_info_with_roles": lambda: {"roles": ["User"]},
            "save_personal_workflow": personal.save_personal_workflow,
            "save_group_workflow": self.store.module.save_group_workflow,
            "log_workflow_creation": lambda **kwargs: None,
            "log_workflow_update": lambda **kwargs: None,
            "authorize_workflow_run_read": lambda *args, **kwargs: None,
            "AnalysisResultUnavailable": LookupError,
        }
        names = {"save_user_workflow", "save_group_workflow_route", "_workflow_definition_response"}
        nodes = []
        for node in ast.walk(ast.parse(ROUTES_FILE.read_text(encoding="utf-8"))):
            if isinstance(node, ast.FunctionDef) and node.name in names and node.name not in {n.name for n in nodes}:
                node.decorator_list = []
                nodes.append(node)
        assert {node.name for node in nodes} == names
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(ROUTES_FILE), "exec"), namespace)
        app = Flask("workflow-alert-reviewed-messages")
        app.add_url_rule("/api/user/workflows", endpoint="save_user_workflow",
                         view_func=namespace["save_user_workflow"], methods=["POST"])
        app.add_url_rule("/api/group/workflows", endpoint="save_group_workflow_route",
                         view_func=namespace["save_group_workflow_route"], methods=["POST"])
        self.client = app.test_client()
        self.classes = definitions

    def post(self, scope, payload):
        path = "/api/group/workflows" if scope == "group" else "/api/user/workflows"
        return self.client.post(path, json=payload)

    def writes(self):
        return len(self.store.container.writes) + len(self.personal_container.writes)


@pytest.fixture(scope="module")
def routes():
    return SaveRoutes()


@pytest.mark.parametrize("scope", ["personal", "group"])
@pytest.mark.parametrize("case", sorted(CASES))
def test_each_alert_failure_returns_its_reviewed_message(routes, scope, case):
    """Every normalizer failure is a 400 with its reviewed, data-free message and the alerts code."""
    alert_fields, message = CASES[case]
    writes_before = routes.writes()

    response = routes.post(scope, _payload(scope, **alert_fields))

    assert response.status_code == 400, response.get_data(as_text=True)
    assert response.json == {"error": message, "code": "invalid_workflow_alerts"}
    assert MARKER not in response.get_data(as_text=True)
    assert routes.writes() == writes_before


@pytest.mark.parametrize("scope", ["personal", "group"])
def test_every_condition_type_saves_on_both_routes(routes, scope):
    """The reviewed branch refuses only invalid alerts; each of the seven condition types saves."""
    rules = [
        _condition({"type": "run_status", "statuses": ["failed", "completed"]}),
        _condition({"type": "task_status", "statuses": ["failed"]}, scope={"type": "task", "task_id": "collect"}),
        _condition({"type": "text_match", "mode": "contains_any", "values": ["penalty", "breach"]},
                   scope={"type": "any_task"}),
        _condition({"type": "text_match", "mode": "regex", "pattern": r"expires in \d+ days"}),
        _condition({"type": "file_sync", "outcome": "sync_failed"}),
        _condition({"type": "no_output"}),
        _condition({"type": "model_evaluation", "prompt": "Any certificate expires within 14 days."}),
        _condition({"type": "agent_signal", "signal_name": "expiring", "min_severity": "high"}),
    ]
    response = routes.post(scope, _payload(
        scope, alert_mode="rules", alert_priority="none", alert_rules=rules,
        alert_evaluation={"on_error": "alert"},
    ))

    assert response.status_code == 201, response.get_data(as_text=True)
    saved = response.json["workflow"]
    assert [rule["condition"]["type"] for rule in saved["alert_rules"]] == [
        "run_status", "task_status", "text_match", "text_match", "file_sync", "no_output",
        "model_evaluation", "agent_signal",
    ]
    assert saved["alert_rules"][1]["scope"] == {"type": "task", "task_id": "collect"}
    assert saved["alert_evaluation"] == {"on_error": "alert"}


@pytest.mark.parametrize("scope", ["personal", "group"])
def test_other_value_errors_stay_generic(routes, scope):
    """A ValueError outside the reviewed families keeps the generic message and carries no code."""
    payload = _payload(scope, runner_type="robot")

    response = routes.post(scope, payload)

    assert response.status_code == 400
    assert response.json == {"error": GENERIC_400}


def test_the_reviewed_error_is_still_a_value_error(routes):
    """Every existing caller that handles ValueError keeps working with the reviewed error."""
    assert issubclass(routes.classes.WorkflowPublicValidationError, ValueError)
    assert not issubclass(routes.classes.WorkflowPublicValidationError, routes.classes.WorkflowDefinitionError)
    alerts = routes.store.modules["functions_workflow_alerts"]
    with pytest.raises(ValueError, match="Alert rule 1 needs a task to watch."):
        alerts.normalize_alert_rules([_rule(scope={"type": "task"})], task_ids=["collect"])


def test_the_run_time_regex_check_is_unchanged(routes):
    """validate_alert_regex keeps its plain ValueError and messages, which the runner relies on."""
    alerts = routes.store.modules["functions_workflow_alerts"]
    expected = {
        "": "Alert rule regex pattern is required.",
        "x" * 201: "Alert rule regex pattern must be 200 characters or fewer.",
        "(a+)+": "Alert rule regex pattern uses nested quantifiers that are not allowed.",
    }
    for pattern, message in expected.items():
        with pytest.raises(ValueError) as caught:
            alerts.validate_alert_regex(pattern)
        assert type(caught.value) is ValueError
        assert str(caught.value) == message
    with pytest.raises(ValueError) as caught:
        alerts.validate_alert_regex("(unclosed")
    assert type(caught.value) is ValueError
    assert str(caught.value).startswith("Alert rule regex pattern is invalid: ")
    assert alerts.validate_alert_regex(r"\d+ CRITICAL").search("3 critical")


def test_alert_evaluation_is_unchanged(routes):
    """Normalized rules still evaluate as before: severity, delivery, category and silence."""
    alerts = routes.store.modules["functions_workflow_alerts"]
    workflow = {
        "alert_mode": "rules", "alert_priority": "none",
        "alert_rules": alerts.normalize_alert_rules([
            {"name": "Run failed", "severity": "high", "condition": {"type": "run_status", "statuses": ["failed"]}},
            {"name": "Risk", "severity": "critical", "delivery": "notify_only",
             "condition": {"type": "text_match", "mode": "contains_any", "values": ["penalty"]}},
        ]),
    }
    quiet = alerts.evaluate_workflow_alert_rules(workflow, alerts.build_workflow_alert_facts(
        workflow, {"status": "completed", "success": True}, {"reply": "All good."},
    ))
    failed = alerts.evaluate_workflow_alert_rules(workflow, alerts.build_workflow_alert_facts(
        workflow, {"status": "failed", "success": False}, {},
    ))
    risky = alerts.evaluate_workflow_alert_rules(workflow, alerts.build_workflow_alert_facts(
        workflow, {"status": "completed", "success": True}, {"reply": "A penalty applies."},
    ))

    assert quiet["should_alert"] is False
    assert (failed["should_alert"], failed["severity"], failed["delivery"], failed["category"]) == (
        True, "high", "popup", "failure",
    )
    assert (risky["should_alert"], risky["severity"], risky["delivery"]) == (True, "critical", "notify_only")
