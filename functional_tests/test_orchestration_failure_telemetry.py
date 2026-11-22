# test_orchestration_failure_telemetry.py
"""Specific orchestration failure rules reach telemetry without private plan text.

Version: 0.261.480
Implemented in: 0.261.140
Step, capability, format, and authority-reason codes covered in: 0.261.141
Partial-input producer capability and step hash fields covered in: 0.261.191
Semantic chat outcomes and persisted-state correlation implemented in: 0.261.341
Bounded, non-regex application-version validation implemented in: 0.261.342
Two shared planning corrections covered in: 0.261.422
Recovery guard detail through the Warning logger covered in: 0.261.444
Diagnostic rule and code fields added in 0.261.478 reaching telemetry covered in: 0.261.480

Uses real planner/validation/logging modules with offline provider replies.
The synthetic invalid proposals test diagnostics, not the unknown historical
provider responses from the September 25 incident.
"""

import ast
import hashlib
import importlib
import json
import logging
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from azure.cosmos._cosmos_responses import CosmosDict

from test_orchestration_deliverables import _csv_plan
from test_orchestration_harness_execution import harness, initialized_application  # noqa: F401
from test_support.orchestration_harness_execution import compose_step, decoded_frames, input_binding


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
        # A second unread text output: the server selects an answer only when exactly one exists.
        plan["steps"].append(compose_step("second"))
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
    harness.replies = [json.dumps(proposal)] * 3
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
    assert len(records) == len(harness.model_calls) == 3
    assert [record.sc_attempt for record in records] == [1, 2, 3]
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
        step_id="PRIVATE_STEP",
    )
    properties = telemetry._build_logger_extra("[ORCHESTRATION_RUNS] Failure.", {
        **correlation, "validation_code": "deliverables_invalid",
        "validation_rule": "non_file_format", "execution_code": "context_unavailable",
        "response_failure": "model_refusal",
        "output_code": "output_record_invalid", "durable_status": "failed",
        "failure_code": "source_authority_unverified", "authority_reason": "manifest_revision_invalid",
        "capability_id": "render_file", "output_format": "docx",
        "producer_capability_id": "document_analyze",
        "producer_step_id_hash": hashlib.sha256(b"PRIVATE_PRODUCER_STEP").hexdigest(),
        "response_type": "CosmosDict", "api_key": "PRIVATE_KEY",
        "prompt": "PRIVATE_PROMPT", "run_id": "PRIVATE_RUN",
    })
    assert properties["sc_run_id_hash"] == hashlib.sha256(b"PRIVATE_RUN").hexdigest()
    assert properties["sc_step_id_hash"] == hashlib.sha256(b"PRIVATE_STEP").hexdigest()
    assert properties["sc_validation_rule"] == "non_file_format"
    assert properties["sc_execution_code"] == "context_unavailable"
    assert properties["sc_response_failure"] == "model_refusal"
    assert properties["sc_response_type"] == "CosmosDict"
    assert properties["sc_durable_status"] == "failed"
    assert properties["sc_failure_code"] == "source_authority_unverified"
    assert properties["sc_authority_reason"] == "manifest_revision_invalid"
    assert properties["sc_capability_id"] == "render_file"
    assert properties["sc_output_format"] == "docx"
    assert properties["sc_producer_capability_id"] == "document_analyze"
    assert properties["sc_producer_step_id_hash"] == hashlib.sha256(b"PRIVATE_PRODUCER_STEP").hexdigest()
    assert "PRIVATE_" not in json.dumps(properties)
    assert {
        "stepidhash", "failurecode", "authorityreason", "capabilityid", "outputformat",
        "producerstepidhash", "producercapabilityid",
    } <= (
        telemetry.LOGGER_WORKFLOW_HASH_KEYS | telemetry.LOGGER_WORKFLOW_CODE_KEYS
    )
    for key in (*telemetry.LOGGER_WORKFLOW_HASH_KEYS, *telemetry.LOGGER_WORKFLOW_CODE_KEYS):
        invalid = telemetry._build_logger_extra("Failure.", {key: "PRIVATE_VALUE"})
        assert f"sc_{key}" not in invalid


def test_the_rule_and_code_fields_added_for_troubleshooting_reach_telemetry(harness):
    """0.261.480: these were logged from 0.261.478 and dropped at this boundary."""
    telemetry = importlib.import_module("functions_appinsights")
    properties = telemetry._build_logger_extra("[ORCHESTRATION_ADAPTERS] Failure.", {
        "failure_rule": "read_document_unselected", "execution_rule": "reply_empty",
        "error_code": "sheet_selection_required", "calculation_cause": "generation_incomplete",
        "limit_source": "compatibility_policy", "limit_status": "unknown",
    })
    assert properties["sc_failure_rule"] == "read_document_unselected"
    assert properties["sc_execution_rule"] == "reply_empty"
    assert properties["sc_error_code"] == "sheet_selection_required"
    assert properties["sc_calculation_cause"] == "generation_incomplete"
    assert (properties["sc_limit_source"], properties["sc_limit_status"]) == ("compatibility_policy", "unknown")
    for key in ("failure_rule", "execution_rule", "error_code", "calculation_cause", "limit_source"):
        assert f"sc_{key}" not in telemetry._build_logger_extra("Failure.", {key: "PRIVATE text"})


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


def test_recovery_guard_detail_survives_the_real_warning_logger_with_debug_off(
    harness, monkeypatch, caplog,
):
    telemetry = importlib.import_module("functions_appinsights")
    checkpoints = importlib.import_module("functions_orchestration_checkpoints")
    from test_support.orchestration_results import ResultFixture

    logger = logging.getLogger("test.orchestration.recovery_guard")
    monkeypatch.setattr(telemetry, "_load_logging_settings", lambda: {"enable_debug_logging": False})
    monkeypatch.setattr(telemetry, "get_appinsights_logger", lambda: logger)
    monkeypatch.setattr(harness.execution, "log_event", telemetry.log_event)
    task = ResultFixture().save()
    step_id = task.producer.step_id
    context = SimpleNamespace(
        user_message="Review", memory_context={}, selected_document_ids=[],
        plan_contract_version=2, task_results={step_id: task}, result_aliases={},
        pending_results={}, execution_deadline_at="2030-01-01T00:00:00+00:00",
        composition_profiles={},
    )
    changed_producer = replace(task.producer, run_id="run-2")
    changed_task = replace(
        task, producer=changed_producer,
        outputs=tuple(replace(reference, producer=changed_producer) for reference in task.outputs),
    )
    state = checkpoints.context_state(context)
    state["task_results"][step_id] = changed_task.to_dict()
    with pytest.raises(checkpoints.CheckpointError) as caught:
        checkpoints.restore_context(context, {"state": state})
    error = caught.value
    assert error.validation_rule == "task_result_producer_changed"
    assert error.stage == "checkpoint_result_restore"
    assert error.producer_capability_id == task.producer.capability_id
    record = {
        "id": "PRIVATE_RUN", "conversation_id": "PRIVATE_CONVERSATION",
        "turn_id": "PRIVATE_TURN",
    }
    with caplog.at_level(logging.WARNING, logger=logger.name):
        harness.execution._log_failure(
            "Headless execution preparation failed.", record, error,
            stage="execution_prepare",
        )
    event = next(
        item for item in caplog.records
        if getattr(item, "sc_message", None)
        == "[ORCHESTRATION_RUNS] Headless execution preparation failed."
    )
    assert event.sc_validation_rule == "task_result_producer_changed"
    assert event.sc_stage == "checkpoint_result_restore"
    assert event.sc_producer_capability_id == task.producer.capability_id
    assert event.sc_execution_code == "recovery_changed"
    assert "PRIVATE_" not in json.dumps({
        key: value for key, value in event.__dict__.items() if key.startswith("sc_")
    })


def test_delivery_without_plan_final_response_uses_closed_recovery_refusal(
    harness, monkeypatch,
):
    from types import SimpleNamespace

    harness.create()
    record = harness.read()
    record.update(
        status="waiting",
        started_at="2030-01-01T00:00:00+00:00",
        execution_deadline_at="2030-01-01T00:05:00+00:00",
        execution_binding="saved-execution-binding",
        task_results={},
        pending_results={},
        final_response={"producer": {"capability_id": "PRIVATE_CAPABILITY"}},
    )
    record["plan"].pop("final_response", None)
    execution = harness.execution.HarnessExecution(record, SimpleNamespace())
    principal = SimpleNamespace(email="owner@example.test", bridge=None)
    def initialize_resources(settings, services):
        execution.services = services
        return principal, {"user_roles": [], "user_email": principal.email}

    monkeypatch.setattr(execution, "_initialize_delivery_resources", initialize_resources)
    monkeypatch.setattr(execution, "_read_delivery_metadata", lambda: None)
    monkeypatch.setattr(execution, "_revalidate_context", lambda: {})
    monkeypatch.setattr(
        execution, "_read_conversation",
        lambda: {"user_id": "owner", "id": "conversation-1"},
    )
    monkeypatch.setattr(execution, "_bind_public_chat_scope", lambda *args: None)
    with pytest.raises(harness.execution.HarnessExecutionError) as failure:
        execution._initialize_delivery(harness.settings, harness.services())
    assert failure.value.code == "recovery_changed"
    assert failure.value.validation_rule == "final_response_reference_changed"
    assert failure.value.stage == "final_response_binding"
    assert failure.value.producer_capability_id is None


@pytest.mark.parametrize("outcome", ["completed", "partial", "failed", "waiting", "cancelled"])
@pytest.mark.parametrize("debug", [False, True])
def test_chat_outcome_dimensions_survive_sanitization_without_private_text(
    harness, monkeypatch, caplog, outcome, debug,
):
    telemetry = importlib.import_module("functions_appinsights")
    logger = logging.getLogger("test.chat.outcome")
    monkeypatch.setattr(telemetry, "get_appinsights_logger", lambda: logger)
    monkeypatch.setattr(telemetry, "_load_logging_settings", lambda: {"enable_debug_logging": debug})
    status = "failed" if outcome == "partial" else outcome
    with caplog.at_level(logging.INFO, logger=logger.name):
        telemetry.log_chat_execution_outcome(
            execution_path="orchestration", status=status, outcome=outcome,
            conversation_id="PRIVATE_CONVERSATION", turn_id="PRIVATE_TURN", run_id="PRIVATE_RUN",
            failure={
                "code": "input_partial_not_accepted", "step_id": "PRIVATE_STEP",
                "capability_id": "document_analyze", "message": "PRIVATE_DIAGNOSTIC",
            },
            application_version="0.261.341", attempt_index=2, message_saved=True,
        )
    records = [record for record in caplog.records if getattr(record, "sc_message", "") == "[CHAT_EXECUTION] Execution outcome recorded."]
    assert len(records) == 1
    record = records[0]
    assert record.sc_execution_path == "orchestration"
    assert record.sc_status == status and record.sc_outcome == outcome
    assert record.sc_application_version == "0.261.341"
    assert record.sc_attempt_index == 2 and record.sc_message_saved is True
    assert record.sc_conversation_id_hash == hashlib.sha256(b"PRIVATE_CONVERSATION").hexdigest()
    assert record.sc_turn_id_hash == hashlib.sha256(b"PRIVATE_TURN").hexdigest()
    assert record.sc_run_id_hash == hashlib.sha256(b"PRIVATE_RUN").hexdigest()
    assert record.sc_step_id_hash == hashlib.sha256(b"PRIVATE_STEP").hexdigest()
    assert record.sc_failure_code == "input_partial_not_accepted"
    assert record.sc_capability_id == "document_analyze"
    properties = {key: value for key, value in record.__dict__.items() if key.startswith("sc_")}
    assert "PRIVATE_" not in json.dumps(properties)
    assert record.levelno < logging.ERROR
    invalid = telemetry._build_logger_extra("Outcome.", {"application_version": "PRIVATE_VERSION"})
    assert "sc_application_version" not in invalid


@pytest.mark.parametrize(
    "version",
    ["0.261.342", "1.2.3", "00.001.0002", "١.٢.٣", f"{'0' * 60}.1.2"],
    ids=["current", "short", "leading-zeroes", "decimal-unicode", "length-limit"],
)
def test_application_version_is_preserved_in_both_telemetry_boundaries(harness, monkeypatch, version):
    telemetry = importlib.import_module("functions_appinsights")
    events = []
    monkeypatch.setattr(telemetry, "log_event", lambda message, **kwargs: events.append(kwargs))
    telemetry.log_chat_execution_outcome(
        execution_path="direct", status="completed", outcome="completed",
        conversation_id="PRIVATE_CONVERSATION", application_version=version,
    )
    assert events[0]["extra"]["application_version"] == version
    properties = telemetry._build_logger_extra("Outcome.", {"application_version": version})
    assert properties["sc_application_version"] == version
    assert properties["sc_application_version_length"] == len(version)
    assert "PRIVATE_" not in json.dumps(events)


@pytest.mark.parametrize(
    "version",
    [
        "", "1.2", "1.2.3.4", ".1.2", "1..2", "1.2.", "1.2.3\n", " 1.2.3",
        "1.2.3-private", "¹.2.3", "PRIVATE_VERSION",
        f"{'0' * 61}.1.2", "0" * 100_000, f"1.2.{'0' * 100_000}",
        f"1.2.3{'0' * 100_000}PRIVATE_VERSION",
    ],
    ids=[
        "empty", "two-parts", "four-parts", "empty-major", "empty-minor", "empty-patch",
        "newline", "whitespace", "suffix", "non-decimal-digit", "private",
        "over-limit", "long-numeric", "long-last-part", "long-valid-prefix-private-suffix",
    ],
)
def test_invalid_application_version_is_omitted_without_truncation(harness, monkeypatch, version):
    telemetry = importlib.import_module("functions_appinsights")
    events = []
    monkeypatch.setattr(telemetry, "log_event", lambda message, **kwargs: events.append(kwargs))
    telemetry.log_chat_execution_outcome(
        execution_path="direct", status="completed", outcome="completed",
        conversation_id="PRIVATE_CONVERSATION", application_version=version,
    )
    assert "application_version" not in events[0]["extra"]
    properties = telemetry._build_logger_extra("Outcome.", {"application_version": version})
    assert "sc_application_version" not in properties
    assert properties["sc_application_version_length"] == len(version)
    assert "PRIVATE_" not in json.dumps(events) + json.dumps(properties)


def test_application_version_length_is_checked_before_parsing(harness):
    telemetry = importlib.import_module("functions_appinsights")

    class OversizedVersion(str):
        def split(self, *args, **kwargs):
            raise AssertionError("Oversized application version must not be parsed.")

    version = OversizedVersion("0" * 100_000)
    accepted = telemetry._is_application_version(version)
    assert accepted is False
    properties = telemetry._build_logger_extra("Outcome.", {"application_version": version})
    assert "sc_application_version" not in properties


@pytest.mark.parametrize("version", [None, 123, True, {}, []])
def test_outcome_omits_non_string_application_versions(harness, monkeypatch, version):
    telemetry = importlib.import_module("functions_appinsights")
    events = []
    monkeypatch.setattr(telemetry, "log_event", lambda message, **kwargs: events.append(kwargs))
    telemetry.log_chat_execution_outcome(
        execution_path="direct", status="completed", outcome="completed",
        conversation_id="PRIVATE_CONVERSATION", application_version=version,
    )
    assert "application_version" not in events[0]["extra"]


@pytest.mark.parametrize("failed", [False, True])
def test_durable_execution_outcome_is_recorded_once_not_on_sse_replay(harness, monkeypatch, failed):
    telemetry = importlib.import_module("functions_appinsights")
    execution_module = harness.execution
    observations = []

    def observe(**kwargs):
        saved = harness.read()
        observations.append((kwargs, saved["status"], saved.get("message_saved")))
        telemetry.log_chat_execution_outcome(**kwargs)

    monkeypatch.setattr(execution_module, "log_chat_execution_outcome", observe)
    harness.create(replies=["Exact prepared answer."], final_response=input_binding("prepare"))
    execution = harness.prepare()
    if failed:
        def fail_plan(*args, **kwargs):
            raise execution_module.HarnessExecutionError("execution_interrupted")
        monkeypatch.setattr(execution_module, "execute_plan", fail_plan)
    frames = execution.execute()
    replay = execution.execute()
    done = decoded_frames(frames)[-1]
    record = harness.read()
    assert replay == frames and len(observations) == 1
    fields, saved_status, message_saved = observations[0]
    assert fields["status"] == fields["outcome"] == saved_status == done["status"]
    assert saved_status == ("failed" if failed else "completed")
    assert message_saved is True and fields["message_saved"] is True
    assert fields["conversation_id"] == record["conversation_id"]
    if failed:
        assert fields["failure"]["code"] == "execution_interrupted"
