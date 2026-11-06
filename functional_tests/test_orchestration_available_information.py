# test_orchestration_available_information.py
"""Normal answers and narrative files from accepted findings with honest information gaps.

Version: 0.261.417
Implemented in: 0.261.399; 0.261.417

Real contracts, preparation, lineage, execution and file publication run offline.
Scripted model assessments exercise control flow, not factual-accuracy calibration.
"""

import io
import json
import sys
from copy import copy, deepcopy
from dataclasses import replace
from pathlib import Path

import fitz
import pytest
from docx import Document

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))

from functions_generated_export_contracts import GeneratedFileExportError
from functions_task_completeness import (
    CompletenessError, NARRATIVE_OBLIGATIONS, check_and_correct, normalize_assessment,
)
from test_orchestration_dependency_runtime import (  # noqa: F401
    binding, compose, execute, runtime, source_input,
)
from test_orchestration_harness_execution import harness, initialized_application  # noqa: F401
from test_orchestration_deliverables import _claim_retry
from test_orchestration_reason_render_pipeline import download_outputs, narrative_io  # noqa: F401
from test_support.orchestration_harness_execution import compose_step, input_binding, render_step


ANSWER = (
    "# Available findings\n\n"
    "The source describes the original items. The remaining requested conclusion "
    "could not be established from the available results."
)


def analysis_step():
    return {
        "step_id": "analyze", "capability_id": "document_analyze",
        "arguments": {
            "document_ids": ["document-1"], "doc_scope": "personal",
            "analysis_prompt": "Describe supported items and explain unknown requested conclusions.",
            "analysis_options": {"version": "analysis-options-v2", "mode": "source_observations"},
        },
        "outputs": [
            {"name": "findings", "kind": "records-v1"},
            {"name": "coverage", "kind": "structured-v1"},
            {"name": "report", "kind": "markdown-v1"},
        ],
    }


def assessment(candidate, *, status="satisfied", missing_id=None):
    quote = next(line for line in candidate.splitlines() if line.strip())
    return json.dumps({"requirements": [
        {
            "id": identifier, "requirement": requirement,
            "status": status if identifier == "supported_claims" else "satisfied",
            "reason": "The answer must not invent the unavailable fact." if status != "satisfied" else "",
            "evidence_refs": [], "answer_quote": quote if status == "satisfied" or identifier != "supported_claims" else "",
        }
        for identifier, requirement in NARRATIVE_OBLIGATIONS if identifier != missing_id
    ]})


def check_narrative(replies, *, candidate=ANSWER, saved_state=None, checkpoints=None):
    calls = []
    iterator = iter(replies)

    def invoke(messages, stage, *, response_format=None):
        calls.append((stage, deepcopy(messages)))
        return next(iterator)

    result, state = check_and_correct(
        candidate, instruction={"approved_request": "Answer both questions from the provided information."},
        contract={"response_policy": "available_information", "knowledge_basis": "sources"},
        evidence={"record": {"amount": 100}},
        policy={"enabled": True, "max_corrections": 2},
        invoke=invoke, validate=lambda value: [],
        checkpoint=lambda value: checkpoints.append(deepcopy(value)) if checkpoints is not None else None,
        saved_state=saved_state,
    )
    return result, state, calls


@pytest.mark.parametrize("status", ["unsupported", "conflicting", "uncertain"])
def test_narrative_repairs_bad_assertions_without_inventing_missing_facts(status):
    original = "The amount is 100. Approval is guaranteed."
    corrected = "The amount is 100. Approval status was not provided."
    value, state, calls = check_narrative(
        [assessment(original, status=status), corrected, assessment(corrected)],
        candidate=original,
    )
    assert value == corrected and state["status"] == "complete"
    assert state["corrections"] == 1
    assert [stage for stage, _ in calls] == [
        "completeness_check", "completeness_correct", "completeness_check",
    ]
    assert all(
        message["role"] in {"system", "user"}
        for _, messages in calls for message in messages
    )


def test_invalid_assessment_repairs_only_the_assessment_once():
    checkpoints = []
    value, state, calls = check_narrative(
        ["invalid JSON", assessment(ANSWER)], checkpoints=checkpoints,
    )
    assert value == ANSWER and state["status"] == "complete"
    assert state["corrections"] == 0 and state["report_repairs"] == 1
    assert [stage for stage, _ in calls] == ["completeness_check", "completeness_check"]
    assert json.loads(calls[0][1][-1]["content"])["candidate"] == ANSWER
    assert json.loads(calls[1][1][-1]["content"])["candidate"] == ANSWER
    reserved = next(value for value in checkpoints if value["status"] == "repairing_assessment")
    _, resumed, resumed_calls = check_narrative([], saved_state=reserved)
    assert resumed["status"] == "verification_unavailable"
    assert resumed["reason_code"] == "completeness_assessment_interrupted"
    assert resumed_calls == []


def test_invalid_assessment_cannot_loop_or_drop_a_predeclared_obligation():
    _, state, calls = check_narrative([
        assessment(ANSWER, missing_id="requested_content"),
        assessment(ANSWER, missing_id="requested_content"),
    ])
    assert state["status"] == "verification_unavailable"
    assert state["reason_code"] == "completeness_requirements_changed"
    assert state["report_repairs"] == 1 and len(calls) == 2


@pytest.mark.parametrize("reference", ["record.nonexistent", "grant-1", "APPROVAL"])
def test_evidence_aliases_require_real_paths_or_exact_identifiers(reference):
    payload = json.dumps({"requirements": [{
        "id": "r1", "requirement": "State the amount.", "status": "satisfied",
        "reason": "", "evidence_refs": [reference], "answer_quote": "100",
    }]})
    with pytest.raises(CompletenessError, match="completeness_evidence_invalid"):
        normalize_assessment(
            payload, candidate="100",
            evidence={"record": {"grant_id": "grant-100", "text": "APPROVAL is not an evidence identifier."}},
        )


def partial_producer(runtime):
    def run(step, context, **options):
        if step["step_id"] != "upstream":
            return runtime.composition.adapter_compose(step, context, **options)
        partial = runtime.contracts.Completeness(
            "partial", 1, 1, runtime.contracts.Coverage(2, 1, "sources"), "partial",
            ("retained_subset",), ("One requested conclusion could not be established.",),
        )
        task = context.result_service.persist_task_result(
            producer=context.result_producer(step), role="reason", status="partial",
            outputs=[runtime.NamedOutput("answer", "markdown-v1", "The amount is 100.", partial)],
            sources=[], origin="generated", guard_token=context.result_guard_token_for_step(step["step_id"]),
        )
        return runtime.schema.build_step_result(status="partial", task_result=task)
    return run


@pytest.mark.parametrize("verification", [False, True])
def test_accepted_partial_information_finishes_normally_without_promoting_evidence(runtime, verification):
    draft = compose("answer", inputs={"facts": source_input("upstream", "answer")})
    draft["arguments"]["response_policy"] = "available_information"
    steps = runtime.schema.available_information_plan({"steps": [compose("upstream"), draft]})["steps"]
    replies = [ANSWER, assessment(ANSWER)] if verification else [ANSWER]
    case = runtime.make(
        steps, replies, final_response=binding("answer"),
        settings={"enable_chat_orchestration_completeness_check": verification},
    )
    result = execute(runtime, case, get_adapter=lambda capability: partial_producer(runtime))
    assert result["status"] == result["outcome"] == "completed", result
    assert result["message"] == ANSWER and result["failure"] is None
    assert result["steps"][0]["status"] == result["steps"][1]["status"] == "partial"
    reference = case.context.task_results["answer"].output("answer")
    assert reference.completeness.status == "partial"
    ready = runtime.contracts.narrative_result_ready(reference)
    assert ready
    with pytest.raises(runtime.contracts.ResultNotReadyError):
        case.fixture.restart().open_result(reference)
    reader = case.fixture.restart().open_result(reference, allow_partial=True)
    text = reader.read_text()
    assert text == ANSWER


def test_available_information_policy_cannot_be_used_to_complete_a_dataset(runtime):
    output = [{"name": "rows", "kind": "records-v1", "columns": [
        {"name": "amount", "value_type": "number", "nullable": False},
    ]}]
    step = compose(outputs=output)
    step["arguments"]["response_policy"] = "available_information"
    with pytest.raises(runtime.schema.PlanValidationError, match="narrative outputs"):
        runtime.make([step])


def test_an_earlier_answer_alias_cannot_fulfill_unrelated_current_work_with_the_same_step_id(runtime):
    step = compose("upstream")
    case = runtime.make([step])
    producer = replace(case.context.result_producer(step), run_id="earlier-run")
    case.fixture.add_producer(producer)
    completion = runtime.contracts.Completeness(
        "complete", 1, 1, runtime.contracts.Coverage(1, 1, "work_units"), "valid",
        ("prepared_output_schema", "authoritative_input_reads", runtime.contracts.NARRATIVE_READY_CHECK), (),
    )
    earlier = case.fixture.service.persist_task_result(
        producer=producer, role="reason", status="complete",
        outputs=[runtime.NamedOutput("answer", "markdown-v1", "Earlier prepared answer.", completion)],
        sources=[], origin="generated", guard_token="earlier-execution",
    ).output("answer")
    case.context.result_aliases["earlier"] = earlier
    case.plan = runtime.schema.normalize_plan(
        {"steps": [step], "run_id": "run-1", "plan_id": "plan-1", "turn_id": "turn-1",
         "final_response": binding(alias="earlier")},
        "conversation-1", "owner", settings=case.settings, contract_version=2,
        available_capability_ids=["compose"], existing_results={"earlier": earlier},
    )
    case.fixture.runs["run-1"]["plan"] = deepcopy(case.plan)
    result = execute(runtime, case, get_adapter=lambda capability: partial_producer(runtime))
    assert result["status"] == "failed" and result["outcome"] == "partial"
    assert result["message"].startswith("Earlier prepared answer.")
    assert case.context.task_results["upstream"].producer.run_id == "run-1"
    assert earlier.producer.run_id == "earlier-run" and case.model.calls == []


@pytest.mark.parametrize("output_format", ["md", "docx", "pdf"])
def test_actual_partial_analysis_creates_a_qualified_narrative_file(harness, narrative_io, output_format):
    prepare = compose_step(inputs={
        "findings": {"binding": input_binding("analyze", "findings")},
        "coverage": {"binding": input_binding("analyze", "coverage")},
    })
    prepare["arguments"].update(response_policy="available_information", knowledge_basis="sources")
    render = render_step(
        "report", output_format, profile="prepared_text_v1" if output_format == "md" else "prepared_report_v1",
    )
    steps = harness.schema.available_information_plan({"steps": [analysis_step(), prepare, render]})["steps"]

    def reply():
        prompt = harness.model_calls[-1]["messages"][-1]["content"]
        if "<DocumentSlice>\n" in prompt:
            response = json.loads(narrative_io["reply"]())
            response["findings"][0].update(
                status="unresolved", issues=["The requested conclusion is not established."],
                values={"finding": "NEVER_CANONICAL_UNSUPPORTED"},
            )
            return json.dumps(response)
        return ANSWER

    harness.create(
        steps, replies=[reply] * 20,
        final_response=input_binding("prepare"),
        seeds={"document_ids": ["document-1"], "doc_scope": "personal"},
        original_seeds={"document_ids": ["document-1"], "doc_scope": "personal"},
    )
    execution = harness.prepare()
    execution.execute()
    saved = harness.read()
    assert saved["status"] == saved["outcome"] == "completed", saved.get("failure")
    assert saved["message"].startswith(ANSWER)
    assert "only partially completed" not in saved["message"]
    assert execution.context.task_results["analyze"].status == "partial"
    prepared = execution.context.task_results["prepare"].output("answer")
    assert prepared.completeness.status == "partial"
    outputs, artifacts, payloads = download_outputs(harness)
    assert len(outputs) == len(artifacts) == 1
    assert outputs[0]["state"] == "completed" and outputs[0]["available"]
    payload = payloads[f"report.{output_format}"]
    if output_format == "md":
        text = payload.decode("utf-8")
    elif output_format == "docx":
        document = Document(io.BytesIO(payload))
        text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    else:
        with fitz.open(stream=payload, filetype="pdf") as document:
            text = "\n".join(page.get_text() for page in document)
    assert "remaining requested conclusion" in text
    assert "could not be established" in text
    assert "NEVER_CANONICAL_UNSUPPORTED" not in text
    assert "NEVER_CANONICAL_UNSUPPORTED" not in json.dumps(harness.model_calls)
    assert harness.blobs.file_uploads == 1


@pytest.mark.parametrize("render_failure", [False, True])
def test_saved_complete_only_failure_can_continue_without_reanalyzing(harness, narrative_io, render_failure):
    prepare = compose_step(inputs={
        "findings": {"binding": input_binding("analyze", "findings"), "allow_partial": False},
    })
    harness.create(
        [analysis_step(), prepare, render_step("report", "md")],
        replies=[narrative_io["reply"]] * 10,
        final_response=input_binding("prepare"),
        seeds={"document_ids": ["document-1"], "doc_scope": "personal"},
        original_seeds={"document_ids": ["document-1"], "doc_scope": "personal"},
    )

    def partial_reply():
        response = json.loads(narrative_io["reply"]())
        response["findings"][0]["issues"] = ["The remaining conclusion is not established."]
        return json.dumps(response)

    harness.replies = [partial_reply] * 10
    execution = harness.prepare()
    execution.execute()
    parent = harness.read()
    assert parent["status"] == "failed"
    projection = harness.recovery.recovery_projection(parent)
    assert projection["eligible"] is False
    assert projection["can_use_available_information"] is True
    source_reference = execution.context.task_results["analyze"].output("findings")
    previous_calls = len(harness.model_calls)
    previous_chunks = len([entry for entry in narrative_io["reads"] if entry[0] == "chunks"])
    authorize = lambda: harness.bootstrap.read_owned_conversation("owner", "conversation-1")
    probe = copy(execution.context)
    probe.result_service = harness.services().results
    request = {
        "conversation_id": "conversation-1", "submission_id": "available-information-continuation",
        "expected_version": parent["recovery_version"], "use_available_information": True,
    }

    def validate(record):
        return harness.recovery.validate_resume(
            record, probe, harness.settings, authorize, source_run_id=record["id"],
        )

    child = harness.recovery.prepare_retry(
        "run-1", "owner", request, authorize=authorize, validate=validate,
        message_container=harness.messages,
    )
    assert child["available_information_continuation"] is True
    assert child["retry_reused_step_ids"] == ["analyze"]
    assert child["inherited_checkpoints"] == {}
    assert child["plan"]["steps"][1]["arguments"]["response_policy"] == "available_information"
    assert harness.read()["plan"] == parent["plan"]
    harness.replies = [ANSWER]
    resumed = _claim_retry(harness, child)
    if render_failure:
        def unavailable_renderer(**kwargs):
            raise GeneratedFileExportError("invalid_data", "Offline terminal renderer failure.")

        harness.monkeypatch.setattr(resumed.context.rendering_service, "renderer", unavailable_renderer)
    for changed in ("request", "digest", "provenance"):
        invalid = deepcopy(resumed.lease.read())
        if changed == "request":
            invalid["plan"]["steps"][0]["arguments"]["analysis_prompt"] = "Different source work."
        elif changed == "digest":
            invalid["continuation_source_checkpoints"]["analyze"]["payload_digest"] = "0" * 64
        else:
            invalid["continuation_source_checkpoints"]["analyze"]["provenance"]["run_id"] = "another-run"
        with pytest.raises(harness.recovery.CheckpointError):
            harness.recovery.validate_resume(
                invalid, resumed.context, harness.settings, authorize, source_run_id="run-1",
            )
    resumed.execute()
    saved_child = harness.recovery._owned(child["id"], "owner", "conversation-1", authorize)
    final_child = child
    if render_failure:
        assert saved_child["status"] == "failed"
        retry_probe = copy(resumed.context)
        retry_probe.result_service = harness.services().results
        final_child = harness.recovery.prepare_retry(
            child["id"], "owner", {
                "conversation_id": "conversation-1", "submission_id": "retry-narrative-file",
                "expected_version": saved_child["recovery_version"],
            },
            authorize=authorize, message_container=harness.messages,
            validate=lambda record: harness.recovery.validate_resume(
                record, retry_probe, harness.settings, authorize, source_run_id=record["id"],
            ),
        )
        resumed = _claim_retry(harness, final_child)
        resumed.execute()
        saved_child = harness.recovery._owned(final_child["id"], "owner", "conversation-1", authorize)
    assert saved_child["status"] == saved_child["outcome"] == "completed", saved_child.get("failure")
    assert saved_child["message"].startswith(ANSWER)
    assert len(harness.model_calls) == previous_calls + 1
    assert len([entry for entry in narrative_io["reads"] if entry[0] == "chunks"]) == previous_chunks
    assert resumed.context.task_results["analyze"].output("findings") == source_reference
    assert source_reference.completeness.status == "partial"
    message = harness.messages.read_item(saved_child["assistant_message_id"], "conversation-1")
    assert message["metadata"]["saved_analyses"][0]["binding"]["run_id"] == "run-1"
    reloaded_context = copy(resumed.context)
    reloaded_context.result_service = harness.services().results
    recovered = harness.recovery.validate_resume(
        saved_child, reloaded_context, harness.settings, authorize, allow_waiting=True,
    )
    assert set(recovered) == {"analyze", "prepare", "report"}
    assert len(harness.model_calls) == previous_calls + 1
    outputs = harness.services().rendering.list_public_outputs(final_child["id"])
    assert len(outputs) == 1 and outputs[0]["state"] == "completed"
    repeated = harness.recovery.prepare_retry(
        "run-1", "owner", request, authorize=authorize, validate=validate,
        message_container=harness.messages,
    )
    assert repeated["id"] == child["id"] and len(harness.model_calls) == previous_calls + 1


@pytest.mark.parametrize("all_unknown", [False, True])
def test_native_report_with_unknowns_is_checked_without_rewriting_or_faking_records(
    harness, narrative_io, all_unknown,
):
    harness.settings["enable_chat_orchestration_completeness_check"] = True
    steps = harness.schema.available_information_plan({"steps": [
        analysis_step(), render_step("report", "md", source="analyze", output="report"),
    ]})["steps"]

    def reply():
        prompt = harness.model_calls[-1]["messages"][-1]["content"]
        if "<DocumentSlice>\n" in prompt:
            response = json.loads(narrative_io["reply"]())
            unknown = response["findings"] if all_unknown else response["findings"][:1]
            for finding in unknown:
                finding.update(status="unresolved", issues=["The requested conclusion is not established."])
            return json.dumps(response)
        candidate = json.loads(prompt)["candidate"]
        return assessment(candidate)

    harness.create(
        steps, replies=[reply] * 20,
        final_response=input_binding("analyze", "report"),
        seeds={"document_ids": ["document-1"], "doc_scope": "personal"},
        original_seeds={"document_ids": ["document-1"], "doc_scope": "personal"},
    )
    execution = harness.prepare()
    execution.execute()
    saved = harness.read()
    assert saved["status"] == saved["outcome"] == "completed", saved.get("failure")
    task = execution.context.task_results["analyze"]
    assert task.status == "partial"
    assert (task.output("findings").item_count == 0) is all_unknown
    assert "only partially completed" not in saved["message"]
    assert "could not be established" in saved["message"]
    outputs, artifacts, payloads = download_outputs(harness)
    assert len(outputs) == len(artifacts) == 1
    assert "could not be established" in payloads["report.md"].decode("utf-8")
    checks = [
        call for call in harness.model_calls
        if "previous_requirements" in call["messages"][-1]["content"]
    ]
    assert len(checks) == 1
