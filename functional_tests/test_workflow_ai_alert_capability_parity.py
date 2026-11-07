# test_workflow_ai_alert_capability_parity.py
"""
Functional tests for native alert authoring through chat and AI Assist.
Version: 0.261.315
Implemented in: 0.261.315

Real draft/save and assistant operation paths run offline with scoped service doubles.
Scripted model replies prove contract plumbing, not live model selection quality.
"""

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))

from functions_workflow_alerts import build_workflow_alert_facts, evaluate_workflow_alert_rules
from functions_workflow_assist import ASSIST_SYSTEM_PROMPT
from test_support import workflow_assist as wa
from test_workflow_draft_service import harness  # noqa: F401


RULE = {
    "name": "Active telemetry faults", "severity": "critical", "delivery": "popup",
    "require_acknowledgment": True, "sound": "repeat", "size": "large",
    "scope": {"type": "task", "task": 1},
    "condition": {
        "type": "model_evaluation",
        "prompt": "An actual active fault or unhealthy state was reported. Exclude healthy results and no active alerts.",
    },
}
BLUEPRINT = {
    "name": "Telemetry monitor", "trigger": {"type": "interval", "unit": "hours", "value": 1},
    "tasks": [{"title": "Read telemetry", "instructions": "Read current telemetry and report actual active faults."}],
    "alerts": {"mode": "rules", "rules": [RULE]},
}


def _assist(operations, *, rules=None):
    stored = wa.stored_workflow(
        alert_mode="rules", alert_priority="none",
        alert_rules=rules or [
            {"id": "alert-first", "name": "Same name", "enabled": True, "severity": "low",
             "delivery": "notify_only", "scope": {"type": "final", "task_id": ""},
             "condition": {"type": "run_status", "statuses": ["failed"]}},
            {"id": "alert-second", "name": "Same name", "enabled": True, "severity": "critical",
             "delivery": "default", "scope": {"type": "task", "task_id": wa.REVIEW_ID},
             "condition": {"type": "task_status", "statuses": ["failed"]}},
        ],
    )
    body = wa.request_body(stored=stored, instruction="Require acknowledgment on Rule 2.")
    reply = wa.reply("changed", "Updated the requested rule.", operations)
    model = wa.ScriptedModel(reply, reply)
    services = wa.services(model, stored=stored)
    return body, model, services


def test_acknowledgment_updates_only_the_requested_rule_and_exposes_options():
    body, model, services = _assist([
        {"op": "update_alert_rule", "rule": "alert_2", "require_acknowledgment": True},
    ])
    result = wa.run(body, services)
    expected = copy.deepcopy(body["draft"])
    expected["alert_evaluation"] = {"on_error": "skip"}
    expected["alert_rules"][1]["require_acknowledgment"] = True
    assert result["candidate"] == expected
    assert result["warnings"] == []
    assert [change["key"] for change in result["changes"]] == ["alerts"]
    visible = model.envelope()["draft"]["alerts"]["rules"][1]
    assert (visible["require_acknowledgment"], visible["sound"], visible["size"]) == (False, "off", "small")
    assert "alert-second" not in model.text()


def test_pop_up_options_can_be_explicitly_cleared_without_changing_identity():
    rules = [{
        "id": "alert-existing", **{key: value for key, value in RULE.items() if key != "scope"},
        "scope": {"type": "final", "task_id": ""}, "enabled": True,
    }]
    body, model, services = _assist([
        {"op": "update_alert_rule", "rule": "alert_1",
         "require_acknowledgment": False, "sound": "off", "size": "small"},
    ], rules=rules)
    result = wa.run(body, services)
    candidate = result["candidate"]["alert_rules"][0]
    assert candidate == {**body["draft"]["alert_rules"][0],
                         "require_acknowledgment": False, "sound": "off", "size": "small"}
    visible = model.envelope()["draft"]["alerts"]["rules"][0]
    assert (visible["require_acknowledgment"], visible["sound"], visible["size"]) == (True, "repeat", "large")


def test_assist_adds_the_strongest_supported_rule_and_preserves_other_rules():
    body, _model, services = _assist([{
        "op": "add_alert_rule", **{key: value for key, value in RULE.items() if key != "scope"},
        "scope": {"type": "task", "task": "task_2"},
    }])
    result = wa.run(body, services)
    rules = result["candidate"]["alert_rules"]
    assert rules[:2] == body["draft"]["alert_rules"]
    assert rules[2]["scope"] == {"type": "task", "task_id": wa.REVIEW_ID}
    for key in ("severity", "delivery", "require_acknowledgment", "sound", "size", "condition"):
        assert rules[2][key] == RULE[key]


def test_assist_can_edit_file_sync_alerts_without_configuring_the_trigger():
    rules = [{
        "id": "alert-sync", "name": "Sync failed", "enabled": True, "severity": "critical",
        "delivery": "default", "scope": {"type": "final", "task_id": ""},
        "condition": {"type": "file_sync", "outcome": "sync_failed"},
    }]
    body, model, services = _assist([
        {"op": "update_alert_rule", "rule": "alert_1", "require_acknowledgment": True},
    ], rules=rules)
    result = wa.run(body, services)
    assert result["candidate"]["alert_rules"][0]["condition"] == rules[0]["condition"]
    assert result["candidate"]["alert_rules"][0]["require_acknowledgment"] is True
    assert result["candidate"]["trigger_type"] == body["draft"]["trigger_type"]
    assert model.envelope()["draft"]["alerts"]["rules"][0]["condition"] == rules[0]["condition"]
    body, _model, services = _assist([{
        "op": "add_alert_rule", "severity": "high",
        "condition": {"type": "file_sync", "outcome": "sync_failed"},
    }])
    result = wa.run(body, services)
    assert result["candidate"]["alert_rules"][-1]["condition"] == rules[0]["condition"]


def test_untouched_pre_existing_invalid_rules_do_not_block_a_valid_option_edit():
    rules = [
        {"id": "alert-old", "name": "Old invalid rule", "enabled": True, "severity": "critical",
         "delivery": "notify_only", "require_acknowledgment": True,
         "scope": {"type": "final", "task_id": ""}, "condition": {"type": "run_status", "statuses": ["failed"]}},
        {"id": "alert-good", "name": "New rule", "enabled": True, "severity": "critical", "delivery": "popup",
         "scope": {"type": "final", "task_id": ""}, "condition": {"type": "run_status", "statuses": ["failed"]}},
    ]
    body, _model, services = _assist([
        {"op": "update_alert_rule", "rule": "alert_2", "require_acknowledgment": True},
    ], rules=rules)
    result = wa.run(body, services)
    assert result["candidate"]["alert_rules"][0] == body["draft"]["alert_rules"][0]
    assert result["candidate"]["alert_rules"][1]["require_acknowledgment"] is True


@pytest.mark.parametrize("change,expected", [
    ({"name": "Updated name"}, {"name": "Updated name"}),
    ({"enabled": False}, {"enabled": False}),
    ({"severity": "high", "delivery": "popup"}, {"severity": "high", "delivery": "popup"}),
    ({"scope": {"type": "task", "task": "task_1"}},
     {"scope": {"type": "task", "task_id": wa.COLLECT_ID}}),
    ({"condition": {"type": "text_match", "mode": "contains_any", "values": ["FAULT"]}},
     {"condition": {"type": "text_match", "mode": "contains_any", "values": ["FAULT"], "case_sensitive": False}}),
])
def test_existing_rule_fields_are_updated_in_place(change, expected):
    body, _model, services = _assist([{"op": "update_alert_rule", "rule": "alert_2", **change}])
    result = wa.run(body, services)
    assert result["candidate"]["alert_rules"][1] == {**body["draft"]["alert_rules"][1], **expected}
    assert result["candidate"]["alert_rules"][0] == body["draft"]["alert_rules"][0]


@pytest.mark.parametrize("operation", [
    {"rule": "alert_99", "require_acknowledgment": True},
    {"rule": "alert_1", "require_acknowledgment": True},
    {"rule": "alert_2", "sound": "repeat"},
    {"rule": "alert_2", "size": "huge"},
    {"rule": "alert_2", "audience": "group"},
    {"rule": "alert_2"},
    {"rule": "alert-second", "require_acknowledgment": True},
])
def test_invalid_assist_edits_are_corrected_then_refused_without_a_write(operation):
    body, model, services = _assist([{"op": "update_alert_rule", **operation}])
    error = wa.refusal(body, services)
    assert error.code == "assistant_output_invalid"
    assert len(model.calls) == 2
    assert model.envelope(1)["previous_attempt_errors"]
    assert services.recorder.named("dry_run") == []


def test_an_update_cannot_target_a_rule_removed_earlier_in_the_reply():
    body, _model, services = _assist([
        {"op": "remove_alert_rule", "rule": "alert_2"},
        {"op": "update_alert_rule", "rule": "alert_2", "require_acknowledgment": True},
    ])
    error = wa.refusal(body, services)
    assert error.code == "assistant_output_invalid"


def test_rules_survive_real_dry_run_create_and_review_summary(harness):
    preview = harness.dry_run(BLUEPRINT)
    assert preview["ok"], preview["errors"]
    assert harness.writes() == {}
    again = harness.dry_run(BLUEPRINT)
    assert again["workflow"]["alert_rules"] == preview["workflow"]["alert_rules"]
    rule = preview["workflow"]["alert_rules"][0]
    assert rule["scope"]["task_id"] == preview["workflow"]["tasks"][0]["id"]
    for key in ("severity", "delivery", "require_acknowledgment", "sound", "size", "condition"):
        assert rule[key] == RULE[key]
    summary = harness.call("blueprint_alert_summary", BLUEPRINT)
    disclosure = summary["rules"][0]
    assert disclosure["condition"].endswith(RULE["condition"]["prompt"])
    assert disclosure["scope"] == "Read telemetry"
    assert disclosure["delivery"] == "popup"
    created = harness.create(BLUEPRINT)
    assert created["ok"], created["errors"]
    assert created["workflow"]["alert_rules"] == preview["workflow"]["alert_rules"]


@pytest.mark.parametrize("condition,scope", [
    ({"type": "run_status", "statuses": ["failed"]}, {"type": "final"}),
    ({"type": "task_status", "statuses": ["failed"]}, {"type": "task", "task": 1}),
    ({"type": "text_match", "mode": "contains_all", "values": ["ACTIVE", "FAULT"], "case_sensitive": True},
     {"type": "any_task"}),
    ({"type": "text_match", "mode": "regex", "pattern": "^FAULT:"}, {"type": "final"}),
    ({"type": "file_sync", "outcome": "sync_failed"}, {"type": "final"}),
    ({"type": "no_output"}, {"type": "any_task"}),
    ({"type": "agent_signal", "signal_name": "fault", "min_severity": "high"}, {"type": "final"}),
])
def test_native_condition_variants_share_validation_and_accurate_disclosure(harness, condition, scope):
    blueprint = copy.deepcopy(BLUEPRINT)
    blueprint["alerts"]["rules"][0].update(condition=condition, scope=scope)
    result = harness.dry_run(blueprint)
    assert result["ok"], result["errors"]
    summary = harness.call("blueprint_alert_summary", blueprint)
    text = summary["rules"][0]["condition"]
    if condition.get("case_sensitive"):
        assert "case-sensitive" in text
    if condition["type"] == "agent_signal":
        assert "minimum severity: high" in text


@pytest.mark.parametrize("change", [
    {"delivery": "notify_only"},
    {"require_acknowledgment": False},
    {"scope": {"type": "task", "task": 2}},
    {"scope": {"type": "task", "task": "raw-id"}},
    {"scope": {"type": "any_task"}, "condition": {"type": "run_status", "statuses": ["failed"]}},
    {"audience": "group"},
    {"id": "raw-rule-id"},
    {"sound": "louder"},
    {"condition": {"type": "text_match", "mode": "regex", "pattern": "["}},
])
def test_invalid_blueprint_rules_fail_before_any_write(harness, change):
    blueprint = copy.deepcopy(BLUEPRINT)
    blueprint["alerts"]["rules"][0].update(change)
    result = harness.dry_run(blueprint)
    assert not result["ok"]
    assert result["errors"]
    assert harness.writes() == {}


@pytest.mark.parametrize("alerts", [
    {"mode": "rules", "rules": []},
    {"mode": "rules", "rules": [RULE] * 21},
    {"mode": "rules", "rules": [RULE], "severity": "low"},
    {"mode": "every_run", "rules": [RULE]},
    {"rules": [RULE]},
])
def test_rules_mode_is_explicit_bounded_and_not_mixed_with_legacy_options(harness, alerts):
    result = harness.dry_run({**BLUEPRINT, "alerts": alerts})
    assert not result["ok"]
    assert harness.writes() == {}


@pytest.mark.parametrize("matched", [True, False])
def test_domain_faults_can_alert_after_successful_telemetry_acquisition(harness, matched):
    preview = harness.dry_run(BLUEPRINT)
    assert preview["ok"]
    workflow = preview["workflow"]
    rule_id = workflow["alert_rules"][0]["id"]
    output = "Active fault detected" if matched else "No active alerts"
    facts = build_workflow_alert_facts(
        workflow, {"status": "completed", "success": True},
        {"task_results": [{"task": workflow["tasks"][0], "status": "succeeded", "result": {"reply": output}}]},
    )
    prompts = []

    def evaluate(prompt):
        prompts.append(prompt)
        return json.dumps({"results": [{"rule_id": rule_id, "matched": matched, "reason": "Synthetic evaluation"}]})

    decision = evaluate_workflow_alert_rules(
        workflow, facts, model_evaluator=evaluate,
    )
    assert len(prompts) == 1 and output in prompts[0]
    assert decision["should_alert"] is matched
    if matched:
        assert decision["severity"] == "critical"
        assert decision["require_acknowledgment"] is True
        assert (decision["sound"], decision["size"], decision["delivery"]) == ("repeat", "large", "popup")


def test_assist_prompt_distinguishes_supported_alerts_from_email_and_task_approval():
    assert "update_alert_rule" in ASSIST_SYSTEM_PROMPT
    assert "Alert acknowledgment is different from task approval" in ASSIST_SYSTEM_PROMPT
    assert "not email" in ASSIST_SYSTEM_PROMPT
    assert "read-only agent" in ASSIST_SYSTEM_PROMPT
    assert 'size "large"' in ASSIST_SYSTEM_PROMPT


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
