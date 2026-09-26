# test_orchestration_failure_telemetry.py
"""Specific orchestration failure rules reach telemetry without private plan text.

Version: 0.261.140
Implemented in: 0.261.140

Uses real planner/validation/logging modules with offline provider replies.
The synthetic invalid proposals test diagnostics, not the unknown historical
provider responses from the September 25 incident.
"""

import ast
import hashlib
import importlib
import json
import logging
from pathlib import Path

import pytest
from azure.cosmos._cosmos_responses import CosmosDict

from test_orchestration_deliverables import _csv_plan
from test_orchestration_harness_execution import harness, initialized_application  # noqa: F401
from test_support.orchestration_harness_execution import compose_step, input_binding


RULES = (
    "file_format_mismatch", "non_file_format", "invalid_quantity",
    "answer_producer_mismatch", "missing_final_response",
    "unsupported_deliverable_field", "invalid_requested_value",
)


def invalid_proposal(rule):
    if rule == "file_format_mismatch":
        return _csv_plan(render_format="xlsx")
    identifier = "PRIVATE_DELIVERABLE"
    plan = {
        "kind": "plan", "intent": {"summary": "PRIVATE_INTENT"},
        "deliverables": [{
            "id": identifier, "kind": "answer", "requested": "explicit",
            "description": "PRIVATE_DESCRIPTION", "status": "planned",
        }],
        "steps": [{**compose_step(), "delivers": [identifier]}],
        "final_response": input_binding("prepare"),
    }
    declaration = plan["deliverables"][0]
    if rule == "non_file_format":
        declaration["format"] = "PRIVATE_FORMAT"
    elif rule == "invalid_quantity":
        declaration["quantity"] = 1
    elif rule in ("answer_producer_mismatch", "missing_final_response"):
        plan.pop("final_response")
        if rule == "missing_final_response":
            plan["steps"][0].pop("delivers")
    elif rule == "unsupported_deliverable_field":
        declaration["PRIVATE_FIELD"] = "PRIVATE_FIELD_VALUE"
    elif rule == "invalid_requested_value":
        declaration["requested"] = "PRIVATE_REQUESTED"
    else:
        raise AssertionError(f"Unknown diagnostic case: {rule}")
    return plan


@pytest.mark.parametrize("debug", [False, True])
@pytest.mark.parametrize("rule", RULES)
def test_repair_and_terminal_failure_retain_safe_specific_rule(
    harness, monkeypatch, caplog, capsys, rule, debug,
):
    telemetry = importlib.import_module("functions_appinsights")
    logger = logging.getLogger("test.orchestration.failure")
    monkeypatch.setattr(telemetry, "get_appinsights_logger", lambda: logger)
    monkeypatch.setattr(telemetry, "_load_logging_settings", lambda: {"enable_debug_logging": debug})
    proposal = invalid_proposal(rule)
    harness.replies = [json.dumps(proposal), json.dumps(proposal)]
    with caplog.at_level(logging.INFO, logger=logger.name):
        with pytest.raises(harness.planner.PlannerError) as failure:
            harness.planner.plan_request(
                "PRIVATE_PROMPT", {"message": "PRIVATE_PROMPT"},
                "conversation-1", "owner", turn_id="PRIVATE_TURN",
                settings=harness.settings,
                request_context=harness.services().capability_request_bindings(),
            )
    records = [
        record for record in caplog.records
        if getattr(record, "sc_message", "") in {
            "[ORCHESTRATION_PLANNER] Asking the planner to correct a rejected plan.",
            "[ORCHESTRATION_PLANNER] The request could not be planned.",
        }
    ]
    assert len(records) == len(harness.model_calls) == 2
    assert [record.sc_attempt for record in records] == [1, 2]
    for record in records:
        assert record.sc_validation_rule == rule
        assert record.sc_validation_code == "deliverables_invalid"
        assert record.sc_stage == "plan_normalization"
        assert record.sc_conversation_id_hash == hashlib.sha256(b"conversation-1").hexdigest()
        assert record.sc_turn_id_hash == hashlib.sha256(b"PRIVATE_TURN").hexdigest()
    properties = [
        {key: value for key, value in record.__dict__.items() if key.startswith("sc_")}
        for record in caplog.records
    ]
    captured = capsys.readouterr()
    assert "PRIVATE_" not in json.dumps(properties) + captured.out + captured.err
    assert failure.value.message == harness.planner.DELIVERABLES_FAILURE_MESSAGE


def test_all_deliverable_rejections_have_literal_rule_identifiers():
    source = Path(__file__).resolve().parents[1] / "application" / "single_app" / "functions_orchestration_deliverables.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id == "DeliverableError"
    ]
    assert calls
    for call in calls:
        rules = [keyword.value for keyword in call.keywords if keyword.arg == "rule"]
        assert len(rules) == 1 and isinstance(rules[0], ast.Constant), call.lineno
        assert isinstance(rules[0].value, str) and rules[0].value, call.lineno


def test_workflow_hash_and_code_fields_do_not_preserve_arbitrary_text(harness):
    telemetry = importlib.import_module("functions_appinsights")
    correlation = telemetry.workflow_log_context(
        conversation_id="PRIVATE_CONVERSATION", turn_id="PRIVATE_TURN", run_id="PRIVATE_RUN",
    )
    properties = telemetry._build_logger_extra("[ORCHESTRATION_RUNS] Failure.", {
        **correlation, "validation_code": "deliverables_invalid",
        "validation_rule": "non_file_format", "execution_code": "context_unavailable",
        "response_failure": "model_refusal",
        "output_code": "output_record_invalid", "durable_status": "failed",
        "response_type": "CosmosDict", "api_key": "PRIVATE_KEY",
        "prompt": "PRIVATE_PROMPT", "run_id": "PRIVATE_RUN",
    })
    assert properties["sc_run_id_hash"] == hashlib.sha256(b"PRIVATE_RUN").hexdigest()
    assert properties["sc_validation_rule"] == "non_file_format"
    assert properties["sc_execution_code"] == "context_unavailable"
    assert properties["sc_response_failure"] == "model_refusal"
    assert properties["sc_response_type"] == "CosmosDict"
    assert properties["sc_durable_status"] == "failed"
    assert "PRIVATE_" not in json.dumps(properties)
    for key in (*telemetry.LOGGER_WORKFLOW_HASH_KEYS, *telemetry.LOGGER_WORKFLOW_CODE_KEYS):
        invalid = telemetry._build_logger_extra("Failure.", {key: "PRIVATE_VALUE"})
        assert f"sc_{key}" not in invalid


def test_admission_diagnostic_identifies_sdk_type_without_private_record(harness, monkeypatch):
    records = []
    monkeypatch.setattr(
        harness.execution, "log_event", lambda message, **kwargs: records.append((message, kwargs)),
    )
    raw = CosmosDict({
        "id": "PRIVATE_RUN", "conversation_id": "PRIVATE_CONVERSATION",
        "user_id": "PRIVATE_USER", "plan": {"planner_contract_version": 2},
    }, response_headers={})
    with pytest.raises(harness.execution.HarnessExecutionError):
        harness.execution.prepare_harness_execution(raw)
    details = records[-1][1]["extra"]
    assert details["stage"] == "claim_validation"
    assert details["response_type"] == "CosmosDict"
    assert details["execution_code"] == "context_unavailable"
    assert "PRIVATE_" not in json.dumps(records)
    assert harness.model_calls == []


def test_preparation_diagnostic_identifies_stage_and_confirmed_failure(harness, monkeypatch):
    records = []
    monkeypatch.setattr(
        harness.execution, "log_event", lambda message, **kwargs: records.append((message, kwargs)),
    )
    harness.create()
    claimed, lease = harness.claim()
    harness.settings["enable_chat_orchestration"] = False
    try:
        with pytest.raises(harness.execution.HarnessExecutionError) as failure:
            harness.execution.prepare_harness_execution(claimed, settings=harness.settings, lease=lease)
    finally:
        if not lease.stopped.is_set():
            lease.close(release=True)
    details = next(
        values["extra"] for message, values in records
        if message == "[ORCHESTRATION_RUNS] Headless execution preparation failed."
    )
    assert details["stage"] == "settings"
    assert details["execution_code"] == "context_unavailable"
    assert details["response_type"] == "dict"
    assert failure.value.durable_status == "failed"
    assert "run_id" not in details and "user_id" not in details
