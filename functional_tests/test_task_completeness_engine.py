# test_task_completeness_engine.py
"""Grounded, bounded task checking and recovery.

Version: 0.261.380
Implemented in: 0.261.380
"""

import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest

# The pure module can be exercised without initializing application/cloud clients.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))
from functions_task_completeness import (
    CompletenessError, check_and_correct, completeness_policy, normalize_assessment,
    public_completeness_report,
)


def assessment(status="satisfied", quote="Evaluation", refs=None):
    return json.dumps({"requirements": [{
        "id": "r1", "requirement": "Include the status and requested dates.",
        "status": status, "reason": "Dates omitted." if status == "missing" else "",
        "evidence_refs": ["record"] if refs is None else refs,
        "answer_quote": quote if status == "satisfied" else "",
    }]})


def run(replies, **options):
    calls, saved = [], []
    iterator = iter(replies)

    def invoke(messages, stage):
        calls.append(stage)
        value = next(iterator)
        if isinstance(value, Exception):
            raise value
        return value

    result, state = check_and_correct(
        '{"status":"Evaluation"}',
        instruction="Include status, proposal deadline, target award date and response period.",
        contract={"kind": "json", "schema": {"required": ["status"]}},
        evidence={"record": {"status": "Evaluation", "proposal_due": "2027-02-15", "award_target": "2027-04-01", "response_days": 15}},
        policy=options.pop("policy", {"enabled": True, "max_corrections": 2}),
        invoke=invoke, validate=options.pop("validate", lambda candidate: []),
        checkpoint=lambda state: saved.append(deepcopy(state)), **options,
    )
    return result, state, calls, saved


def test_complete_original_has_no_correction():
    _, state, calls, _ = run([assessment()])
    assert state["status"] == "complete"
    assert calls == ["completeness_check"]
    assert state["corrections"] == 0


def test_actual_missing_tool_facts_are_repaired_and_rechecked():
    corrected = '{"status":"Evaluation","proposal_due":"2027-02-15","award_target":"2027-04-01","response_days":15}'
    result, state, calls, _ = run([assessment("missing"), corrected, assessment()])
    assert json.loads(result)["response_days"] == 15
    assert state["status"] == "complete"
    assert calls == ["completeness_check", "completeness_correct", "completeness_check"]


def test_second_correction_always_has_a_final_check():
    _, state, calls, saved = run([
        assessment("missing"), "Evaluation first", assessment("missing"), "Evaluation final", assessment(),
    ])
    assert calls == ["completeness_check", "completeness_correct", "completeness_check", "completeness_correct", "completeness_check"]
    assert state["corrections"] == 2 and state["checks"] == 3
    assert state["status"] == "complete"
    assert [item["corrections"] for item in saved if item["status"] == "correcting"] == [1, 2]


def test_exhaustion_is_not_success_and_never_a_third_correction():
    _, state, calls, _ = run([
        assessment("missing"), "Evaluation first", assessment("missing"), "Evaluation final", assessment("missing"),
    ])
    assert state["status"] == "incomplete"
    assert len(calls) == 5 and calls[-1] == "completeness_check"


@pytest.mark.parametrize("status", ["unsupported", "conflicting", "uncertain"])
def test_absent_evidence_conflicts_and_uncertainty_do_not_invent_facts(status):
    _, state, calls, _ = run([assessment(status)])
    assert state["status"] == "incomplete" and calls == ["completeness_check"]


def test_zero_still_checks_and_off_makes_no_calls():
    _, checked, calls, _ = run([assessment("missing")], policy={"enabled": True, "max_corrections": 0})
    assert checked["status"] == "incomplete" and calls == ["completeness_check"]
    _, disabled, calls, _ = run([], policy={"enabled": False, "max_corrections": 2})
    assert disabled["status"] == "disabled" and calls == []


@pytest.mark.parametrize("reply", [
    "not json", '{"requirements":[]}', assessment(refs=["invented"]),
    assessment(quote="not in this answer"), RuntimeError("PRIVATE_PROVIDER_MESSAGE"),
])
def test_invalid_verification_is_explicitly_unavailable(reply):
    _, state, calls, _ = run([reply])
    assert state["status"] == "verification_unavailable" and len(calls) == 1
    assert "PRIVATE_PROVIDER_MESSAGE" not in json.dumps(public_completeness_report(state))


def test_structural_and_semantic_repairs_share_allowance():
    def validate(candidate):
        return ["invalid JSON"] if candidate == "broken" else []

    _, state, calls, _ = run([assessment("missing"), "broken", "Evaluation", assessment()], validate=validate)
    assert state["status"] == "complete" and state["corrections"] == 2
    assert calls == ["completeness_check", "completeness_correct", "completeness_correct", "completeness_check"]
    # The structurally invalid candidate was checked between those generation calls.
    assert state["checks"] == 3 and state["attempts"][1]["deficiencies"] == ["invalid JSON"]


def test_dropped_requirements_cannot_make_recheck_pass():
    changed = json.loads(assessment())
    changed["requirements"][0]["requirement"] = "Only status"
    _, state, _, _ = run([assessment("missing"), "Evaluation", json.dumps(changed)])
    assert state["status"] == "verification_unavailable"
    assert state["reason_code"] == "completeness_requirements_changed"


def test_terminal_checkpoint_is_reused_without_model_calls():
    _, state, _, _ = run([assessment()])
    _, resumed, calls, _ = run([], saved_state=state)
    assert resumed == state and calls == []


def test_crash_after_correction_reservation_never_repeats_generation():
    _, _, _, checkpoints = run([assessment("missing"), "Evaluation", assessment()])
    reserved = next(item for item in checkpoints if item["status"] == "correcting")
    _, resumed, calls, _ = run([], saved_state=reserved)
    assert resumed["status"] == "verification_unavailable"
    assert resumed["corrections"] == 1 and calls == []


def test_mismatched_checkpoint_does_not_reset_allowance():
    _, state, _, _ = run([assessment()])
    state["identity"] = "changed"
    with pytest.raises(CompletenessError, match="checkpoint_mismatch"):
        run([], saved_state=state)


def test_default_policy_preserves_off_and_zero_and_rejects_invalid_values():
    assert completeness_policy({}, "workflow") == {"enabled": True, "max_corrections": 2}
    assert completeness_policy({
        "enable_workflow_completeness_check": False, "workflow_completeness_max_corrections": 0,
    }, "workflow") == {"enabled": False, "max_corrections": 0}
    for invalid in (-1, 6, True, "2"):
        with pytest.raises(CompletenessError):
            completeness_policy({"workflow_completeness_max_corrections": invalid}, "workflow")


def test_duplicate_json_keys_are_rejected():
    with pytest.raises(CompletenessError):
        normalize_assessment('{"requirements":[],"requirements":[]}', candidate="x", evidence={})


def test_public_projection_never_contains_candidates_or_evidence():
    _, state, _, _ = run([assessment("missing"), "Evaluation", assessment()])
    public = public_completeness_report(state)
    assert set(public) == {"version", "status", "corrections", "max_corrections", "checks", "reason_code", "requirements"}
    assert all(set(item) == {"id", "requirement", "status", "reason"} for item in public["requirements"])


def test_oversized_evidence_fails_explicitly_without_a_model_call(monkeypatch):
    import functions_task_completeness as engine

    monkeypatch.setattr(engine, "MAX_PAYLOAD_BYTES", 1)
    _, state, calls, checkpoints = run([])
    assert state["status"] == "verification_unavailable"
    assert state["reason_code"] == "completeness_context_limit"
    assert state["corrections"] == 0 and calls == []
    assert checkpoints[-1]["status"] == "verification_unavailable"
