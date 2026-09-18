# test_workflow_loop_reporting.py
"""
Functional tests for exact, bounded saved workflow record reporting.
Version: 0.261.117
Implemented in: 0.261.117

The production compiler, record-tree writer, private result transport, authorized
reader and durable execution journal run against serialized offline storage.
Provider callbacks and original-source authorization I/O are closed doubles.
No Azure resource, live model, publication or fact-memory service is used.
"""

from collections import Counter
from copy import deepcopy
import json
import sys
import tracemalloc
from types import SimpleNamespace

import pytest

from test_saved_analysis_service import saved
from test_support.app_stubs import import_app_module
from test_workflow_structured_flow import create_structured_runtime, task
from test_workflow_loop_schema import frame, nested_definition
from functions_analysis_access import AnalysisResultUnavailable, build_analysis_access
from functions_workflow_collections import RecordTreeWriter
from functions_workflow_execution import workflow_execution_scope
from functions_workflow_identity import workflow_execution_id, workflow_node_identity
from functions_workflow_node_results import open_workflow_record_input
from functions_workflow_result_store import load_workflow_node_result, save_workflow_node_result
from functions_workflow_results import build_workflow_task_result, read_result_records, workflow_result_summary
from functions_workflow_runtime_store import WorkflowRuntimeLease
from functions_workflow_structured_execution import StructuredWorkflowExecution
from functions_workflow_validation import validate_workflow_task_output


reporting = import_app_module("functions_workflow_reporting")
SENTINEL = "MIDDLE-ONLY-SENTINEL"
MESSAGES = [
    {"role": "system", "content": "SYSTEM_REQUIRED: use the declared saved inputs."},
    {"role": "user", "content": "Explain these findings qualitatively. Named input criteria: KEEP-THIS-CRITERION."},
]


@pytest.fixture(autouse=True)
def reporting_module(monkeypatch):
    monkeypatch.setitem(sys.modules, "functions_workflow_reporting", reporting)


def selected_model(context=50000, output=2048):
    return {
        "id": f"offline-deployment-{context}",
        "modelName": "offline-workflow-report-model",
        "contextWindow": context,
        "maxInputTokens": context,
        "maxOutputTokens": output,
        "responseLength": output,
    }


def definition(kind="records"):
    return {
        "id": "reporting-workflow", "user_id": "owner",
        "definition_version": 3, "durable_execution": True,
        "runner_type": "model", "chat_capabilities_enabled": False,
        "tasks": [
            task("produce", contract={"kind": kind}),
            task("report", inputs=[{
                "name": "findings",
                "source": {"kind": "node_output", "node_id": "produce-node", "output": "authoritative"},
                "expected_kind": kind,
            }]),
        ],
        "flow": {"id": "root", "nodes": [
            {"id": "produce-node", "kind": "task", "task_id": "produce"},
            {"id": "report-node", "kind": "task", "task_id": "report"},
        ], "outputs": [{
            "name": "report", "source": {"kind": "node_output", "node_id": "report-node", "output": "text"},
            "expected_kind": "text",
        }]},
    }


def original_record(index, count, width, kind):
    middle = SENTINEL if index == count // 2 else "ORDINARY-SAVED-CONTENT"
    padding = "x" * width
    detail = padding[:14001] + middle + padding[14001:]
    record = {
        "record_id": "same-original-business-key",
        "source": {"document_id": "authorized-source", "location": {"page": index}},
        "values": {"detail": detail, "decimal": "12.3400", "null": None, "unicode": "完整", "enabled": True},
    }
    if kind == "document_results":
        return {"document_id": "authorized-source", "kind": "records", "value": [record]}
    return record


def make_input(monkeypatch, *, count=6, width=16000, kind="records"):
    workflow, store, container, clock = create_structured_runtime(definition(kind), monkeypatch)
    source = {
        "document_id": "authorized-source", "scope": "personal", "scope_id": "owner",
        "source_version": "1", "source_revision": "saved-source-revision", "source_kind": "narrative",
    }
    state = {"allowed": True, "source_checks": 0, "reads": []}

    def resolve(ids, **kwargs):
        assert ids == ["authorized-source"] and kwargs["user_id"] == "owner"
        state["source_checks"] += 1
        return [{**source, "authorization_status": "authorized" if state["allowed"] else "unresolved"}]

    with WorkflowRuntimeLease(store, owner_id="producer") as lease:
        execution = StructuredWorkflowExecution(store, lease, workflow, "run")
        execution.set_node(workflow["flow"]["nodes"][0], "root")
        with workflow_execution_scope(execution):
            result = {
                "reply": "Saved workflow collection.",
                "authoritative_result": {"kind": "records", "value": []},
                "analysis_access": build_analysis_access([source]),
            }
            if kind == "document_results":
                result["analysis_result"] = {"per_document": True, "document_results": []}
            envelope = build_workflow_task_result(
                result, workflow=workflow, run_id="run", task=workflow["tasks"][0],
            )
            output_name = "documents" if kind == "document_results" else "records"
            selectors = execution.selectors()
            writer = RecordTreeWriter(
                envelope["identity"], output_name, kind,
                lambda section: save_workflow_node_result(
                    workflow, "run", "produce", section, **selectors,
                ), max_result_bytes=32 * 1024 * 1024,
            )
            for index in range(count):
                writer.append(original_record(index, count, width, kind))
            descriptor = writer.finish()
            envelope["workflow_validation"] = validate_workflow_task_output(
                envelope, workflow["tasks"][0]["output_contract"],
            )
            envelope.update(
                outputs={output_name: descriptor}, authoritative_output=output_name, record_count=count,
            )
            reference = save_workflow_node_result(workflow, "run", "produce", envelope, **selectors)
            summary = workflow_result_summary(envelope, reference)
            execution.record_execution(state="running", attempt=1)
            execution.finish_node(
                state="succeeded", attempt=1, workflow_result=summary,
                workflow_validation=envelope["workflow_validation"],
            )
    before_manifest = deepcopy(envelope)

    def reader(*, execution=None, bounded=True, name="findings", inspection=False):
        handle = open_workflow_record_input(
            workflow, "run", envelope["identity"], reference, reader_user_id="owner",
            source_resolver=resolve, inspection=inspection,
        )
        read = handle.read_records

        def read_page(*, offset=0, limit=100):
            state["reads"].append((offset, limit))
            return read(offset=offset, limit=limit)

        handle.read_records = read_page
        return reporting.WorkflowRecordReportingInput(
            handle, name=name, execution=execution, allow_bounded_reporting=bounded,
        )

    return SimpleNamespace(
        workflow=workflow, store=store, container=container, clock=clock,
        source=source, resolve=resolve, state=state, reader=reader,
        manifest=envelope, before_manifest=before_manifest, reference=reference,
        identity=envelope["identity"], count=count, width=width, kind=kind, summary=summary,
    )


def explain(fixture, callback, *, model=None, bounded=True, messages=None, budget_messages=None):
    with WorkflowRuntimeLease(fixture.store, owner_id="reporter") as lease:
        execution = StructuredWorkflowExecution(fixture.store, lease, fixture.workflow, "run")
        execution.set_node(fixture.workflow["flow"]["nodes"][1], "root")
        with workflow_execution_scope(execution):
            reader = fixture.reader(execution=execution, bounded=bounded)
            return saved.explain_saved_analysis(
                [reader], messages or MESSAGES, callback,
                model=model or selected_model(), provider="aoai",
                budget_messages=budget_messages,
            )


def oracle(fixture, *, failure=None, crash_page=None, revoke=False, supported=True):
    calls = []
    state = {"pages": 0, "crashed": False, "sentinel_in_page": False, "sentinel_in_synthesis": False}

    def invoke(messages, *, stage, metadata):
        assert metadata["complete_workflow_record_input"] is True
        assert "complete_saved_analysis_input" not in metadata
        assert messages[0]["content"] == MESSAGES[0]["content"]
        assert "KEEP-THIS-CRITERION" in messages[-1]["content"]
        payload = json.loads(messages[-1]["content"].split(reporting.REPORT_DATA_MARKER, 1)[1])
        call = {"stage": stage, "refs": []}
        calls.append(call)
        if stage == "workflow_record_explanation":
            rows = payload["inputs"][0]["records"]
            assert [row["values"] for row in rows] == [
                original_record(index, fixture.count, fixture.width, fixture.kind) for index in range(fixture.count)
            ]
            return "The saved records describe retained findings."
        if stage == "workflow_record_page":
            call["refs"] = [deepcopy(record["record_ref"]) for record in payload["records"]]
            for record in payload["records"]:
                ordinal = int(record["record_ref"]["record_id"].rsplit(":", 1)[1])
                assert record["values"] == original_record(ordinal, fixture.count, fixture.width, fixture.kind)
                state["sentinel_in_page"] |= SENTINEL in json.dumps(record["values"])
            page_number = state["pages"]
            state["pages"] += 1
            if crash_page == page_number and not state["crashed"]:
                state["crashed"] = True
                raise SystemExit("Offline interruption after a completed prior page.")
            entries = [{
                "record_ref": record["record_ref"],
                "text": (
                    f"{SENTINEL} identifies a retained exception."
                    if SENTINEL in json.dumps(record["values"]) else "The saved record describes routine findings."
                ),
            } for record in payload["records"]]
            if revoke:
                fixture.state["allowed"] = False
            if failure == "omitted":
                entries.pop()
            if failure == "invalid_ref":
                entries[0]["record_ref"]["record_id"] += "-forged"
            if failure == "duplicate":
                entries[-1]["record_ref"] = entries[0]["record_ref"]
            if failure == "number":
                entries[0]["text"] = "There are 987654321 newly calculated findings."
            if failure == "json":
                return "{"
            if failure == "unbounded":
                return "x" * (reporting.ANALYSIS_RECORD_PAGE_BYTES + 1)
            result = {"record_explanations": entries}
            if failure == "shape":
                result["execution_state"] = "completed"
            return json.dumps(result)
        if stage in {"workflow_record_reduce", "workflow_record_conclusions"}:
            chunks = payload["chunks"]
            notes = [note for chunk in chunks for note in chunk["notes"]]
            sentinel = next((note for note in notes if SENTINEL in note["text"]), None)
            if stage == "workflow_record_conclusions":
                state["sentinel_in_synthesis"] = sentinel is not None
            note = sentinel or (notes[0] if notes else None)
            conclusions = [{
                "text": note["text"], "supporting_records": deepcopy(note["supporting_records"]),
            }] if note else []
            if failure == "conclusion_ref" and conclusions:
                conclusions[0]["supporting_records"][0]["record_id"] += "-forged"
            if failure == "conclusion_number" and conclusions:
                conclusions[0]["text"] = "There are 987654321 newly calculated findings."
            if failure == "wide_support" and conclusions:
                conclusions[0]["supporting_records"] = [
                    ref for note in notes for ref in note["supporting_records"]
                ]
            covered = [chunk["chunk_id"] for chunk in chunks]
            return json.dumps({
                "covered_chunks": covered[:-1] if failure == "omitted_chunks" else covered,
                "conclusions": conclusions,
            })
        assert stage == "workflow_record_support"
        originals = payload["supporting_records"]
        call["refs"] = [unit["record"]["record_ref"] for unit in originals]
        for unit in originals:
            ordinal = int(unit["record"]["record_ref"]["record_id"].rsplit(":", 1)[1])
            assert unit["record"]["values"] == original_record(ordinal, fixture.count, fixture.width, fixture.kind)
        return json.dumps({"supported": "true" if failure == "support_shape" else supported})

    return invoke, calls, state


@pytest.mark.parametrize("kind", ["records", "document_results"])
def test_adapter_pages_and_reloads_exact_original_records_without_a_global_offset_map(monkeypatch, kind):
    fixture = make_input(monkeypatch, count=5, width=15000, kind=kind)
    reader = fixture.reader()
    units = list(reader.iter_units())
    assert len(units) == fixture.count
    assert len({unit["record"]["record_id"] for unit in units}) == fixture.count
    assert "analysis_origin" not in reader.metadata()
    assert "saved_analysis" not in reader.metadata()
    assert not hasattr(reader, "_record_offsets")
    for index, unit in enumerate(units):
        assert unit["record"]["values"] == original_record(index, fixture.count, fixture.width, fixture.kind)
        assert reader.read_support(unit["record"]["record_ref"]) == unit
    units[0]["record"]["values"]["model_change"] = "This must not change the source."
    assert "model_change" not in reader.read_support(units[0]["record"]["record_ref"])["record"]["values"]
    assert all(limit == 1 for _, limit in fixture.state["reads"])
    assert fixture.manifest == fixture.before_manifest
    bad = {**units[0]["record"]["record_ref"], "record_id": units[0]["record"]["record_id"] + "00"}
    with pytest.raises(reporting.WorkflowRecordReportingError):
        reader.read_support(bad)
    fixture.state["allowed"] = False
    with pytest.raises(AnalysisResultUnavailable):
        reader.read_support(units[0]["record"]["record_ref"])


@pytest.mark.parametrize("count,width", [(3, 40), (1, 18000)])
def test_fitting_whole_input_uses_one_call_and_preserves_named_nonrecord_inputs(monkeypatch, count, width):
    fixture = make_input(monkeypatch, count=count, width=width)
    invoke, calls, _ = oracle(fixture)
    result = explain(fixture, invoke, bounded=False)
    assert [call["stage"] for call in calls] == ["workflow_record_explanation"]
    assert result["analysis_consumption"]["mode"] == "complete_input"
    assert result["analysis_consumption"]["record_count"] == count
    assert result["analysis_consumption"]["input_kind"] == "workflow_records"
    assert not result.get("analysis_result")
    assert not result.get("analysis_origin")
    assert saved.workflow_saved_analysis_descriptor(
        fixture.summary, fixture.workflow, conversation_id="conversation", message_id="message",
    ) is None
    with pytest.raises(ValueError, match="saved analysis"):
        saved.format_saved_analysis(
            [fixture.reader()], "json", conversation_id="conversation", producer=None,
            upload_artifact=lambda **kwargs: pytest.fail("Generic records cannot become native Analyze exports."),
        )


def test_middle_sentinel_survives_pages_synthesis_and_original_support_reload(monkeypatch):
    fixture = make_input(monkeypatch)
    invoke, calls, state = oracle(fixture)
    result = explain(fixture, invoke)
    consumption = result["analysis_consumption"]
    assert consumption["mode"] == "record_pages" and consumption["page_count"] > 1
    refs = [ref["record_id"] for call in calls if call["stage"] == "workflow_record_page" for ref in call["refs"]]
    assert len(refs) == len(set(refs)) == fixture.count
    assert state["sentinel_in_page"] and state["sentinel_in_synthesis"]
    assert SENTINEL in result["reply"]
    assert original_record(fixture.count // 2, fixture.count, fixture.width, fixture.kind)["values"]["detail"].index(SENTINEL) > 12000
    support = next(call for call in calls if call["stage"] == "workflow_record_support")
    assert int(support["refs"][0]["record_id"].rsplit(":", 1)[1]) == fixture.count // 2
    assert fixture.state["reads"].count((fixture.count // 2, 1)) > 1
    assert fixture.manifest == fixture.before_manifest
    assert consumption["checkpoints"]["page_count"] == consumption["page_count"]
    assert len(consumption["context_budgets"]) == 1
    assert consumption["deterministic_values"] == {"accepted_record_count": fixture.count, "accepted_subset_only": False}


def test_effective_task_model_and_extra_instructions_determine_batching(monkeypatch):
    fixture = make_input(monkeypatch, count=4, width=16000)
    wide, wide_calls, _ = oracle(fixture)
    whole = explain(fixture, wide, model=selected_model(150000))
    narrow, narrow_calls, _ = oracle(fixture)
    batched = explain(fixture, narrow, model=selected_model(50000))
    assert len(wide_calls) == 1 and whole["analysis_consumption"]["mode"] == "complete_input"
    assert len(narrow_calls) > 1 and batched["analysis_consumption"]["mode"] == "record_pages"
    for result, ceiling in [(whole, 150000), (batched, 50000)]:
        audit = result["analysis_consumption"]["context_budgets"][0]
        assert audit["context_window_tokens"] == ceiling
        assert audit["limit_source"] == "configured"
        assert audit["output_reserve_tokens"] == 2048
        assert audit["input_tokens"] <= audit["input_budget_tokens"]
        assert audit["truncated"] is False
    refused, calls, _ = oracle(fixture)
    with pytest.raises(reporting.WorkflowRecordReportingError, match="retained unchanged"):
        explain(fixture, refused, budget_messages=[{"role": "system", "content": "x" * 50000}])
    assert not calls


@pytest.mark.parametrize("mode,code", [
    ("omitted", "omitted_records"), ("invalid_ref", "invalid_reference"),
    ("duplicate", "invalid_reference"), ("json", "invalid_stage_json"),
    ("number", "unsupported_values"), ("shape", "invalid_stage_shape"),
    ("unbounded", "unbounded_response"), ("omitted_chunks", "omitted_chunks"),
    ("conclusion_ref", "invalid_reference"), ("support_shape", "invalid_stage_shape"),
    ("conclusion_number", "unsupported_values"), ("wide_support", "indivisible_support"),
])
def test_incomplete_or_invalid_model_stages_never_become_accepted_reports(monkeypatch, mode, code):
    fixture = make_input(monkeypatch)
    invoke, _, _ = oracle(fixture, failure=mode)
    with pytest.raises(reporting.WorkflowRecordReportingError) as failure:
        explain(fixture, invoke)
    assert failure.value.code == code
    assert "retained unchanged" in str(failure.value)
    assert fixture.manifest == fixture.before_manifest


def test_unsafe_transform_or_indivisible_record_fails_without_lossy_fallback(monkeypatch):
    fixture = make_input(monkeypatch, count=2, width=55000)
    invoke, calls, _ = oracle(fixture)
    with pytest.raises(reporting.WorkflowRecordReportingError) as unsafe:
        explain(fixture, invoke, bounded=False)
    assert unsafe.value.code == "unsafe_task"
    with pytest.raises(reporting.WorkflowRecordReportingError) as indivisible:
        explain(fixture, invoke)
    assert indivisible.value.code == "indivisible_record"
    assert not calls
    assert fixture.reader().read_support(fixture.reader().reference(0))["record"]["values"] == original_record(
        0, fixture.count, fixture.width, fixture.kind,
    )


def test_inspection_only_handles_cannot_bypass_output_eligibility(monkeypatch):
    fixture = make_input(monkeypatch)
    with pytest.raises(ValueError, match="inspection-only"):
        fixture.reader(inspection=True)
    with pytest.raises(ValueError, match="authorized"):
        reporting.WorkflowRecordReportingInput(SimpleNamespace())


def test_unreadable_page_cannot_be_interpreted_as_a_completed_empty_input(monkeypatch):
    fixture = make_input(monkeypatch)
    reader = fixture.reader()
    monkeypatch.setattr(reader.handle, "read_records", lambda **kwargs: ([], fixture.count))
    with pytest.raises(reporting.WorkflowRecordReportingError) as failure:
        list(reader.iter_units())
    assert failure.value.code == "incomplete_records"


def test_large_reporting_requires_durable_checkpoints_instead_of_an_in_memory_fallback(monkeypatch):
    fixture = make_input(monkeypatch)
    with pytest.raises(reporting.WorkflowRecordReportingError) as failure:
        reporting.explain_workflow_records(
            [fixture.reader()], MESSAGES,
            lambda *args, **kwargs: pytest.fail("No uncheckpointed large report is allowed."),
            model=selected_model(),
        )
    assert failure.value.code == "durable_execution_required"


def test_nonshrinking_reduction_stops_with_all_data_retained(monkeypatch):
    fixture = make_input(monkeypatch, count=6, width=6000)
    invoke, calls, _ = oracle(fixture)

    def verbose(messages, *, stage, metadata):
        response = invoke(messages, stage=stage, metadata=metadata)
        if stage == "workflow_record_page":
            parsed = json.loads(response)
            for entry in parsed["record_explanations"]:
                entry["text"] = "Retained qualitative observation. " * 220
            return json.dumps(parsed)
        return response

    model = selected_model(50000, output=12000)
    model["maxInputTokens"] = 12000
    with pytest.raises(reporting.WorkflowRecordReportingError) as failure:
        explain(fixture, verbose, model=model)
    assert failure.value.code in {"unsafe_reduction", "indivisible_notes"}
    assert not any(call["stage"] == "workflow_record_support" for call in calls)
    assert fixture.manifest == fixture.before_manifest


def test_revocation_blocks_new_and_checkpointed_report_work(monkeypatch):
    fixture = make_input(monkeypatch)
    invoke, calls, _ = oracle(fixture, revoke=True)
    with pytest.raises(AnalysisResultUnavailable):
        explain(fixture, invoke)
    assert len(calls) == 1
    fixture.state["allowed"] = True
    complete, _, _ = oracle(fixture)
    explain(fixture, complete)
    fixture.state["allowed"] = False
    with pytest.raises(AnalysisResultUnavailable):
        explain(fixture, lambda *args, **kwargs: pytest.fail("Cached notes cannot grant access."))


def test_restart_replays_completed_page_and_reduction_checkpoints(monkeypatch):
    fixture = make_input(monkeypatch)
    invoke, calls, _ = oracle(fixture, crash_page=1)
    with pytest.raises(SystemExit):
        explain(fixture, invoke)
    completed_refs = [ref["record_id"] for ref in calls[0]["refs"]]
    fixture.clock.advance()
    result = explain(fixture, invoke)
    all_refs = Counter(
        ref["record_id"] for call in calls if call["stage"] == "workflow_record_page" for ref in call["refs"]
    )
    assert all(all_refs[ref] == 1 for ref in completed_refs)
    assert result["analysis_consumption"]["checkpoint_replays"] >= 1
    before = len(calls)
    fixture.clock.advance()
    replay = explain(fixture, invoke)
    assert len(calls) == before
    assert replay["reply"] == result["reply"]
    assert replay["analysis_consumption"]["model_calls"] == 0
    assert replay["analysis_consumption"]["checkpoint_replays"] > result["analysis_consumption"]["checkpoint_replays"]


def test_large_aggregate_uses_bounded_spooled_reduction_not_all_notes_or_all_records(monkeypatch):
    fixture = make_input(monkeypatch, count=100, width=100000)
    assert fixture.count * fixture.width > 8 * 1024 * 1024
    loader = lambda reference: load_workflow_node_result(
        fixture.workflow, "run", "produce", reference,
        **{key: fixture.identity[key] for key in ("node_id", "execution_id", "iteration_path", "attempt")},
    )
    with pytest.raises(ValueError):
        read_result_records(fixture.manifest, fixture.manifest["authoritative_output"], loader)
    invoke, calls, state = oracle(fixture)
    tracemalloc.start()
    try:
        result = explain(fixture, invoke, model=selected_model(250000))
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 8 * 1024 * 1024
    consumption = result["analysis_consumption"]
    assert consumption["record_count"] == 100
    assert consumption["page_count"] > reporting.MAX_REDUCTION_CHILDREN
    assert consumption["reduction_levels"] > 1
    assert any(call["stage"] == "workflow_record_reduce" for call in calls)
    assert state["sentinel_in_page"] and state["sentinel_in_synthesis"]
    assert "pages" not in consumption and len(json.dumps(consumption)) < 10000
    assert len(result["reply"]) < 10000
    assert all(limit == 1 for _, limit in fixture.state["reads"])


def nested_producer():
    workflow = nested_definition()
    path = [frame("outer", index=2), frame("inner", index=4, item_id="b" * 64)]
    execution_id = workflow_execution_id(workflow, "run", "yes_node", path)
    identity = workflow_node_identity(
        workflow, "run", "yes_node", execution_id, 2, task_id="yes", iteration_path=path,
    )
    return workflow, {"kind": "workflow", **identity}


def test_nested_native_producer_metadata_and_descriptors_retain_exact_path_attempt():
    workflow, producer = nested_producer()
    metadata = saved.analysis_artifact_metadata(producer)
    assert metadata["analysis_producer"] == producer
    descriptor = saved.workflow_saved_analysis_descriptor({
        "analysis_origin": True, "producer": {key: value for key, value in producer.items() if key != "kind"},
        "result_ref": {"sha256": "c" * 64}, "record_count": 1, "validation_status": "valid",
    }, workflow, conversation_id="conversation", message_id="assistant")
    assert descriptor["binding"] == {**producer, "group_id": None}
    producer["iteration_path"][0]["index"] = 99
    assert metadata["analysis_producer"]["iteration_path"][0]["index"] == 2
    assert descriptor["binding"]["iteration_path"][0]["index"] == 2
    legacy = {"kind": "workflow", "workflow_id": "workflow", "run_id": "run", "task_id": "yes"}
    assert saved.analysis_artifact_metadata(legacy)["analysis_producer"] == legacy
    assert saved.analysis_artifact_metadata({**legacy, "attempt": 1})["analysis_producer"] == legacy


@pytest.mark.parametrize("path", [
    None, {}, [frame("outer"), frame("outer")], [{"iteration": 1}],
    [frame("outer", index=True)], [frame("outer", item_id="not-a-sha256")],
    [{**frame("outer"), "extra": "field"}],
])
def test_malformed_or_orphan_exact_artifact_selectors_are_rejected(path):
    _, producer = nested_producer()
    producer["iteration_path"] = path
    with pytest.raises(ValueError):
        saved.analysis_artifact_metadata(producer)
    producer.pop("execution_id")
    with pytest.raises(ValueError):
        saved.analysis_artifact_metadata(producer)


def test_bound_context_cannot_bypass_exact_nested_artifact_authorization():
    _, producer = nested_producer()
    artifact = {
        "id": "artifact", "conversation_id": "conversation",
        "metadata": {
            **saved.analysis_artifact_metadata(producer),
            "analysis_result_contexts": [{
                "conversation_id": "conversation", "message_id": "assistant", "result_sha256": "c" * 64,
            }],
        },
    }
    checked = []

    def exact_manifest(user, item, binding):
        checked.append(deepcopy(binding))
        raise AnalysisResultUnavailable("analysis_artifact_unbound")

    with pytest.raises(AnalysisResultUnavailable):
        saved.authorize_analysis_artifact(
            "owner", artifact, workflow_manifest_loader=exact_manifest,
            result_reader=lambda *args: pytest.fail("A context cannot replace its exact workflow artifact producer."),
        )
    assert checked == [producer]
