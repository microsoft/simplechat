# test_task_completeness_engine.py
"""Grounded, bounded task checking and recovery.

Version: 0.261.417
Implemented in: 0.261.382; 0.261.384; 0.261.416; 0.261.417
"""

import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

# The pure module can be exercised without initializing application/cloud clients.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))
from functions_task_completeness import (
    CompletenessError, NARRATIVE_OBLIGATIONS, assessment_response_format,
    check_and_correct, completeness_policy, context_only_review_step_ids,
    normalize_assessment, public_completeness_report,
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

    def invoke(messages, stage, *, response_format=None):
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
    corrected = "Evaluation; requested dates cannot be determined from the available evidence."
    _, state, calls, _ = run([assessment(status), corrected, assessment()])
    assert state["status"] == "complete"
    assert calls == ["completeness_check", "completeness_correct", "completeness_check"]


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
    _, state, calls, _ = run([reply, reply])
    assert state["status"] == "verification_unavailable"
    assert len(calls) == (1 if isinstance(reply, Exception) else 2)
    assert "PRIVATE_PROVIDER_MESSAGE" not in json.dumps(public_completeness_report(state))


def test_structural_and_semantic_repairs_share_allowance():
    def validate(candidate):
        return ["invalid JSON"] if candidate == "broken" else []

    _, state, calls, _ = run([assessment("missing"), "broken", "Evaluation", assessment()], validate=validate)
    assert state["status"] == "complete" and state["corrections"] == 2
    assert calls == ["completeness_check", "completeness_correct", "completeness_correct", "completeness_check"]
    # The structurally invalid candidate was checked between those generation calls.
    assert state["checks"] == 3 and state["attempts"][1]["deficiencies"] == ["invalid JSON"]


@pytest.mark.parametrize("change", ["drop", "add", "rename"])
def test_dropped_requirements_cannot_make_recheck_pass(change):
    original = json.loads(assessment("missing"))
    second = deepcopy(original["requirements"][0])
    second.update(id="dates", requirement="Include every requested date.")
    original["requirements"].append(second)
    changed = deepcopy(original)
    for requirement in changed["requirements"]:
        requirement.update(status="satisfied", reason="", answer_quote="Evaluation")
    if change == "drop":
        changed["requirements"].pop()
    elif change == "add":
        added = deepcopy(changed["requirements"][0])
        added["id"] = "unapproved"
        changed["requirements"].append(added)
    else:
        changed["requirements"][0]["id"] = "different_obligation"
    _, state, _, _ = run([json.dumps(original), "Evaluation", json.dumps(changed), json.dumps(changed)])
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
    assert set(public) == {
        "version", "status", "corrections", "max_corrections", "checks", "reason_code", "requirements",
        "preparation_status", "check_kind", "deterministic_status", "semantic_enabled", "stages",
    }
    assert all(set(item) == {"id", "requirement", "status", "reason"} for item in public["requirements"])


def test_paraphrased_requirements_use_canonical_scope_not_exact_prose():
    changed = json.loads(assessment())
    changed["requirements"][0]["requirement"] = "Give the status along with the dates that were requested."
    _, state, calls, _ = run([assessment("missing"), "Evaluation with dates", json.dumps(changed)])
    assert state["status"] == "complete"
    assert state["requirements"][0]["requirement"] == "Include the status and requested dates."
    assert len(calls) == 3


def test_semantic_off_still_repairs_and_rechecks_required_format():
    policy = completeness_policy({}, "chat_orchestration", semantic_review="off")
    result, state, calls, _ = run(
        ["valid"], policy=policy,
        validate=lambda candidate: [] if candidate == "valid" else ["Required field: dates"],
    )
    assert result == "valid" and state["status"] == "complete"
    assert calls == ["completeness_correct"] and state["checks"] == 2
    public = public_completeness_report(state)
    assert public["deterministic_status"] == "passed"
    assert public["stages"][-1]["status"] == "skipped"


def test_correction_receives_the_actual_findings_and_original_scope():
    messages = []
    responses = iter([assessment("missing"), "Evaluation with dates", assessment()])

    def invoke(prompt, stage, *, response_format=None):
        messages.append((stage, json.loads(prompt[-1]["content"])))
        return next(responses)

    _, state = check_and_correct(
        "Evaluation", instruction="Include the date", contract={"kind": "text"}, evidence={"record": "date"},
        policy={"enabled": True, "max_corrections": 1}, invoke=invoke, validate=lambda value: [],
    )
    correction = messages[1][1]
    assert correction["deficiencies"][0]["reason"] == "Dates omitted."
    assert correction["candidate"] == "Evaluation" and correction["instruction"] == "Include the date"
    assert correction["previous_attempts"][0]["deficiencies"] == correction["deficiencies"]
    assert state["status"] == "complete" and messages[-1][0] == "completeness_check"


def test_no_progress_correction_stops_without_a_blind_retry():
    _, state, calls, _ = run([assessment("missing"), '{"status":"Evaluation"}'])
    assert state["status"] == "incomplete" and state["reason_code"] == "completeness_no_progress"
    assert calls == ["completeness_check", "completeness_correct"]


def test_policy_change_cannot_reuse_previously_checked_candidate():
    _, state, _, _ = run([assessment()])
    with pytest.raises(CompletenessError, match="checkpoint_mismatch"):
        run([], saved_state=state, policy={"enabled": True, "max_corrections": 2, "semantic_enabled": False})


def test_failed_format_does_not_claim_semantic_review_failed():
    _, state, _, _ = run(
        [], policy={"enabled": True, "max_corrections": 0}, validate=lambda candidate: ["invalid schema"],
    )
    report = public_completeness_report(state)
    assert report["stages"][0]["status"] == "completed"
    assert report["stages"][1]["status"] == "failed"
    assert report["stages"][2]["status"] == "pending"


def test_historical_report_does_not_invent_new_stage_history():
    historical = {"version": 1, "status": "complete", "policy": {"enabled": True, "max_corrections": 2}}
    projected = public_completeness_report(historical)
    assert projected["version"] == 1 and projected["status"] == "complete"
    assert "stages" not in projected and "preparation_status" not in projected


def test_historical_checkpoint_keeps_its_original_identity(monkeypatch):
    import functions_task_completeness as engine

    with monkeypatch.context() as legacy:
        legacy.setattr(engine, "REPORT_VERSION", 1)
        _, state, _, _ = run([assessment()])
    _, resumed, calls, _ = run([], saved_state=state)
    assert resumed == state and calls == []


def test_candidate_revisions_advance_only_after_a_changed_answer_is_retained():
    _, state, _, saved = run([
        assessment("missing"), "Evaluation with date", assessment("missing"), "Evaluation with dates", assessment(),
    ])
    reserved = next(item for item in saved if item["status"] == "correcting")
    assert reserved["candidate_revision"] == 0 and reserved["corrections"] == 1
    assert state["candidate_revision"] == 2 and len(state["attempts"]) == 3
    assert state["original"] == '{"status":"Evaluation"}'
    assert state["attempts"][1]["candidate"] == "Evaluation with date"
    assert state["candidate"] == "Evaluation with dates"


def test_oversized_evidence_fails_explicitly_without_a_model_call(monkeypatch):
    import functions_task_completeness as engine

    monkeypatch.setattr(engine, "MAX_PAYLOAD_BYTES", 1)
    _, state, calls, checkpoints = run([])
    assert state["status"] == "verification_unavailable"
    assert state["reason_code"] == "completeness_context_limit"
    assert state["corrections"] == 0 and calls == []
    assert checkpoints[-1]["status"] == "verification_unavailable"


def test_discontiguous_heading_quotes_and_negative_constraints_pass_normalization():
    candidate = (
        "Civic Bridge desk brief (CB-27-983413)\n\n"
        "## Decision\n"
        "Avery, readiness reviewer: maintain amber readiness for Civic Bridge review CB-27-983413 "
        "and proceed with focused review of the Civic Bridge training brief, FED-PROGRAM-027.\n\n"
        "## Evidence\n"
        "The established baseline is a $200,000 budget, amber readiness, and Rowan as mission owner. "
        "The amber rating indicates that readiness requires continued attention and validation before "
        "full confidence can be established.\n\n"
        "## Next step\n"
        "Review outstanding readiness dependencies with Rowan, confirm budget alignment to the "
        "$200,000 baseline, and identify actions needed to progress beyond amber status."
    )
    payload = json.dumps({
        "requirements": [
            {
                "id": "first_line",
                "requirement": "The very first plain paragraph line must be exactly: Civic Bridge desk brief (CB-27-983413).",
                "status": "satisfied",
                "reason": "Starts with the required plain paragraph line.",
                "evidence_refs": ["approved_request", "instruction"],
                "answer_quote": "Civic Bridge desk brief (CB-27-983413)",
            },
            {
                "id": "headings_order",
                "requirement": "Then use exactly these Markdown section headings in this order: ## Decision, ## Evidence, ## Next step.",
                "status": "satisfied",
                "reason": "All three Markdown headings appear in the exact required order.",
                "evidence_refs": [],
                "answer_quote": "## Decision ... ## Evidence ... ## Next step",
            },
            {
                "id": "baseline_facts",
                "requirement": "State the established baseline facts explicitly: Civic Bridge review CB-27-983413; Civic Bridge training brief FED-PROGRAM-027; budget $200,000; readiness amber; mission owner Rowan.",
                "status": "satisfied",
                "reason": "Every baseline fact is stated explicitly.",
                "evidence_refs": [],
                "answer_quote": "Civic Bridge review CB-27-983413; FED-PROGRAM-027; $200,000 budget; amber readiness; Rowan as mission owner",
            },
            {
                "id": "no_em_dashes",
                "requirement": "Do not use em dashes.",
                "status": "satisfied",
                "reason": "No em dashes appear in the response.",
                "evidence_refs": [],
                "answer_quote": "",
            },
            {
                "id": "concise_tone",
                "requirement": "Keep the tone concise and professional.",
                "status": "satisfied",
                "reason": "The brief is concise and professional.",
                "evidence_refs": [],
                "answer_quote": "",
            },
        ]
    })
    requirements = normalize_assessment(f"```json\n{payload}\n```", candidate=candidate, evidence={})
    assert len(requirements) == 5
    assert all(item["status"] == "satisfied" for item in requirements)
    assert all(item["answer_quote"] and item["answer_quote"] in candidate for item in requirements)
    assert all(item["evidence_refs"] == [] for item in requirements)


def test_nested_evidence_identifiers_and_citations_resolve_to_top_level_evidence_keys():
    candidate = (
        "## Decision\n"
        "- **Policy reference:** FCRA-ACQ-027\n"
        "- **Revision marker:** FED-POLICY-V1-027\n"
        "(Source: FED-7d616b930e5474d0-policy-v1.md, Page: 1) [#01fed089-baca-4422-a2e8-f1e039e1b8c0_1]"
    )
    evidence = {
        "policy_findings": {
            "kind": "records-v1",
            "value": [{
                "document_id": "01fed089-baca-4422-a2e8-f1e039e1b8c0",
                "file_name": "FED-7d616b930e5474d0-policy-v1.md",
                "policy_id": "FCRA-ACQ-027",
                "marker": "FED-POLICY-V1-027",
            }],
            "document_citations": [{
                "citation_id": "01fed089-baca-4422-a2e8-f1e039e1b8c0_1",
                "citation": "(Source: FED-7d616b930e5474d0-policy-v1.md, Page: 1) [#01fed089-baca-4422-a2e8-f1e039e1b8c0_1]",
            }],
        },
        "grant_record": {
            "kind": "structured-v1",
            "value": {"grant_id": "DEMO-GRANT-001", "amount": 125000},
        },
    }
    payload = json.dumps({
        "requirements": [
            {
                "id": "policy_ref",
                "requirement": "Include the policy reference and revision marker.",
                "status": "satisfied",
                "reason": "Stated from policy findings.",
                "evidence_refs": [
                    "[#01fed089-baca-4422-a2e8-f1e039e1b8c0_1]",
                    "FED-7d616b930e5474d0-policy-v1.md",
                    "policy_findings.value[0]",
                    "DEMO-GRANT-001",
                    "instruction",
                ],
                "answer_quote": "Policy reference: FCRA-ACQ-027",
            },
        ]
    })
    requirements = normalize_assessment(payload, candidate=candidate, evidence=evidence)
    assert requirements[0]["evidence_refs"] == ["policy_findings", "grant_record"]
    assert requirements[0]["answer_quote"] in candidate


SUPPLIED_NOTE = (
    "Our project demonstration went well. Alex asked whether the service is already deployed. "
    "It is deployed, and the team was pleased with the reception."
)
TEXT_CONTRACT = {
    "response_policy": "available_information",
    "outputs": [{"name": "answer", "kind": "markdown-v1"}],
    "knowledge_basis": "sources_only",
}


def text_assessment(candidate=SUPPLIED_NOTE, *, status="satisfied"):
    return json.dumps({"requirements": {
        identifier: {
            "status": status if identifier == "supported_claims" else "satisfied",
            "reason": "An added fact lacks support." if status != "satisfied" else "",
            "evidence_refs": ["user_provided_content"],
            "answer_quote": candidate if status == "satisfied" or identifier != "supported_claims" else "",
        }
        for identifier, _ in NARRATIVE_OBLIGATIONS
    }})


def check_supplied_text(replies, *, policy=None, evidence=None, saved_state=None, legacy_evidence=None,
                        instruction=None, validate=None):
    calls, checkpoints = [], []
    responses = iter(replies)

    def invoke(messages, stage, *, response_format=None):
        calls.append({"stage": stage, "messages": deepcopy(messages), "response_format": response_format})
        reply = next(responses)
        if isinstance(reply, Exception):
            raise reply
        return reply

    value, state = check_and_correct(
        SUPPLIED_NOTE,
        instruction=instruction if instruction is not None else {
            "instruction": "Rewrite the supplied account without adding facts.",
            "approved_request": SUPPLIED_NOTE,
        },
        contract=TEXT_CONTRACT,
        evidence=evidence if evidence is not None else {"user_provided_content": SUPPLIED_NOTE},
        policy=policy if policy is not None else completeness_policy(
            {}, "chat_orchestration", allow_semantic_error_skip=True,
        ),
        invoke=invoke, validate=validate if validate is not None else lambda value: [],
        checkpoint=lambda checkpoint: checkpoints.append(deepcopy(checkpoint)),
        saved_state=saved_state, legacy_evidence=legacy_evidence, evidence_basis="user_message",
    )
    return value, state, calls, checkpoints


def test_review_transport_closes_canonical_ids_and_preserves_all_source_text():
    value, state, calls, _ = check_supplied_text([text_assessment()])
    assert value == SUPPLIED_NOTE and state["status"] == "complete"
    schema = calls[0]["response_format"]["json_schema"]["schema"]
    requirements_schema = schema["properties"]["requirements"]
    expected_ids = [identifier for identifier, _ in NARRATIVE_OBLIGATIONS]
    assert requirements_schema["type"] == "object"
    assert requirements_schema["required"] == expected_ids
    assert requirements_schema["additionalProperties"] is False
    payload = json.loads(calls[0]["messages"][-1]["content"])
    assert payload["evidence"]["user_provided_content"] == SUPPLIED_NOTE
    assert payload["instruction"]["approved_request"] == SUPPLIED_NOTE
    assert payload["assessment_schema"] == schema
    valid = json.loads(text_assessment())
    errors = list(Draft202012Validator(schema).iter_errors(valid))
    assert errors == []
    valid["requirements"]["unapproved"] = valid["requirements"][expected_ids[0]]
    errors = list(Draft202012Validator(schema).iter_errors(valid))
    assert errors
    assert [item["id"] for item in state["requirements"]] == expected_ids
    assert [item["requirement"] for item in state["requirements"]] == [
        requirement for _, requirement in NARRATIVE_OBLIGATIONS
    ]


def test_fixed_report_mismatch_provides_concrete_protocol_repair_feedback():
    malformed = json.loads(text_assessment())
    malformed["requirements"]["personalized_check"] = malformed["requirements"].pop("requested_content")
    strict = completeness_policy({}, "chat_orchestration", semantic_review="on")
    _, state, calls, _ = check_supplied_text([json.dumps(malformed), text_assessment()], policy=strict)
    assert state["status"] == "complete" and state["corrections"] == 0
    problem = json.loads(calls[1]["messages"][-1]["content"])["assessment_problem"]
    assert problem["code"] == "completeness_requirements_changed"
    assert problem["missing_ids"] == ["requested_content"]
    assert problem["unexpected_ids"] == ["personalized_check"]
    assert problem["expected_ids"] == [identifier for identifier, _ in NARRATIVE_OBLIGATIONS]


def test_legacy_report_description_cannot_relax_application_owned_quote_requirements():
    payload = json.dumps({"requirements": [{
        "id": "deadline", "requirement": "Keep the answer concise.",
        "status": "satisfied", "reason": "", "evidence_refs": [], "answer_quote": "",
    }]})
    with pytest.raises(CompletenessError, match="completeness_candidate_reference_invalid"):
        normalize_assessment(
            payload, candidate="No date was supplied.", evidence={},
            previous=[{"id": "deadline", "requirement": "State the proposal deadline."}],
        )


@pytest.mark.parametrize("failure", [
    "Not JSON", '{"requirements":{}}',
    CompletenessError("completeness_checker_unavailable"),
])
def test_context_only_auto_recovers_from_checker_error_without_rewriting(failure):
    value, state, calls, checkpoints = check_supplied_text([failure])
    report = public_completeness_report(state)
    assert value == SUPPLIED_NOTE and state["original"] == SUPPLIED_NOTE
    assert state["status"] == "complete" and state["semantic_status"] == "skipped"
    assert state["deterministic_status"] == "passed" and state["corrections"] == 0
    assert len(calls) == 1 and calls[0]["stage"] == "completeness_check"
    assert report["semantic_enabled"] is True
    assert report["stages"][-1]["status"] == "skipped"
    assert report["requirements"] == []
    assert report["semantic_skip_reason"].startswith("completeness_")
    assert checkpoints[-1]["candidate"] == SUPPLIED_NOTE


def test_context_only_checking_retry_skips_known_checker_error_after_required_validation():
    _, _, _, checkpoints = check_supplied_text(["Not JSON"])
    retained = next(item for item in checkpoints if item.get("semantic_status") == "running")
    retained.update(
        status="checking", deterministic_status="pending", semantic_status="pending",
        retry_semantic_error="completeness_requirements_changed",
    )
    validated = []
    value, state, calls, _ = check_supplied_text(
        [], saved_state=retained, validate=lambda candidate: validated.append(candidate) or [],
    )
    assert value == SUPPLIED_NOTE and validated == [SUPPLIED_NOTE] and calls == []
    assert state["semantic_status"] == "skipped" and state["corrections"] == retained["corrections"]
    assert state["checks"] == retained["checks"] + 1


@pytest.mark.parametrize("failure", [
    PermissionError("PRIVATE_PERMISSION"), RuntimeError("PRIVATE_REFUSAL"),
    CompletenessError("completeness_context_limit"), CompletenessError("completeness_correction_interrupted"),
])
def test_auto_does_not_skip_nonoptional_failures(failure):
    _, state, calls, _ = check_supplied_text([failure])
    assert state["status"] == "verification_unavailable" and len(calls) == 1
    assert "semantic_skip_reason" not in state
    assert "PRIVATE_" not in json.dumps(public_completeness_report(state))


def test_auto_checker_outage_does_not_erase_real_content_findings():
    _, state, calls, _ = check_supplied_text([
        text_assessment(status="unsupported"), "A revised account.",
        "Not JSON", "Not JSON",
    ])
    assert state["status"] == "verification_unavailable" and state["corrections"] == 1
    assert "semantic_skip_reason" not in state and len(calls) == 4


@pytest.mark.parametrize("scope", ["on", "workflow"])
def test_explicit_on_and_workflow_never_inherit_context_only_fallback(scope):
    policy = completeness_policy(
        {}, "workflow" if scope == "workflow" else "chat_orchestration",
        semantic_review="on", allow_semantic_error_skip=scope != "workflow",
    )
    _, state, calls, _ = check_supplied_text(["Not JSON", "Not JSON"], policy=policy)
    assert state["status"] == "verification_unavailable" and len(calls) == 2
    assert "semantic_error_policy" not in policy


def test_legacy_user_source_representation_upgrade_preserves_identity_and_allowance():
    policy = completeness_policy({}, "chat_orchestration", semantic_review="on")
    legacy_report = json.dumps({"requirements": [
        {"id": identifier, "requirement": requirement, "status": "satisfied",
         "reason": "", "evidence_refs": [], "answer_quote": SUPPLIED_NOTE}
        for identifier, requirement in NARRATIVE_OBLIGATIONS
    ]})
    _, retained, _, _ = check_supplied_text([legacy_report], policy=policy, evidence={})
    retained.update(status="checking", deterministic_status="pending", semantic_status="pending")
    _, state, calls, _ = check_supplied_text(
        [text_assessment()], policy=policy, saved_state=retained, legacy_evidence={},
    )
    assert state["identity"] != retained["identity"]
    assert state["original"] == retained["original"] and state["corrections"] == retained["corrections"]
    assert state["checks"] == retained["checks"] + 1 and len(calls) == 1
    changed_request = {"approved_request": "A different message.", "instruction": "Rewrite it."}
    with pytest.raises(CompletenessError, match="completeness_checkpoint_mismatch"):
        check_supplied_text(
            [], policy=policy, saved_state=retained, legacy_evidence={}, instruction=changed_request,
            evidence={"user_provided_content": "A different message."},
        )


def test_context_only_eligibility_requires_declared_intent_and_actual_plain_text_plan():
    step = {
        "step_id": "draft", "enabled": True, "capability_id": "compose", "inputs": {},
        "arguments": {"content_intent": "transform_supplied_text", "response_policy": "available_information"},
        "outputs": [{"name": "answer", "kind": "markdown-v1"}],
    }
    eligible = context_only_review_step_ids([step])
    assert eligible == frozenset(("draft",))
    for change in (
        {"capability_id": "document_analyze"},
        {"inputs": {"facts": {"binding": "gathered"}}},
        {"arguments": {"response_policy": "available_information"}},
        {"arguments": {"content_intent": "substantive", "response_policy": "available_information"}},
        {"arguments": {"content_intent": "transform_supplied_text", "response_policy": "complete_inputs"}},
        {"arguments": {
            "content_intent": "transform_supplied_text", "response_policy": "available_information",
            "visuals": ["diagram"],
        }},
        {"outputs": [{"name": "answer", "kind": "structured-v1"}]},
    ):
        eligible = context_only_review_step_ids([{**step, **change}])
        assert eligible == frozenset()
    eligible = context_only_review_step_ids([step, {
        "step_id": "search", "enabled": True, "capability_id": "web_search",
    }])
    assert eligible == frozenset()
