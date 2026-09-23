# test_orchestration_result_contracts.py
"""
Executable M0 result/binding and compatibility contracts, not a harness rollout.
Version: 0.261.125
Implemented in: 0.261.125

These tests exercise strict new APIs alongside the unchanged v1 plan/checkpoint
and native Analyze contracts. They do not claim later runtime/render milestones.
"""

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import json
from types import SimpleNamespace

import pytest

from functions_orchestration_result_contracts import (
    Completeness,
    Coverage,
    InputBinding,
    InputSpec,
    OutputSpec,
    ProducerIdentity,
    RecordColumn,
    ResultContractError,
    ResultRef,
    StepBindings,
    TaskResult,
    canonical_digest,
    validate_input_bindings,
    validate_json,
    validate_record,
)
from functions_orchestration_results import NamedOutput
from functions_native_analysis_results import adapt_native_analysis_result
from functions_workflow_results import build_orchestration_analysis_result
from test_support.orchestration_results import (
    COLUMNS, ROWS, SOURCE_FREE_VALUE, TABULAR_DURABLE, TABULAR_FOREGROUND,
    ResultFixture, complete, native_analysis,
)
from test_support.versioning import assert_app_version_at_least


def reference():
    return ResultRef(
        ProducerIdentity("owner", "conversation", "run", 1, "analyze", "document_analyze", "analyze-final-v1"),
        "findings", "records-v1", "a" * 64, canonical_digest(ROWS), len(json.dumps(ROWS)), 3, complete(3), COLUMNS,
    )


def steps():
    return [
        StepBindings("prepare", True, (OutputSpec("findings", "records-v1"),)),
        StepBindings("inspect", True, (OutputSpec("notes", "markdown-v1"),), (
            InputSpec("data", InputBinding("prepare", "findings"), ("records-v1",)),
        )),
        StepBindings("gather_again", True, (OutputSpec("sources", "source-set-v1"),), depends_on=("inspect",)),
    ]


def test_version_tracks_foundation():
    assert_app_version_at_least("0.261.125")


def test_frozen_named_outputs_round_trip_and_no_transport_handles():
    saved = reference()
    task = TaskResult(saved.producer, "reason", "complete", (saved,))
    encoded = task.to_dict()
    restored = TaskResult.from_dict(json.loads(json.dumps(encoded)))
    assert restored == task
    with pytest.raises(FrozenInstanceError):
        saved.kind = "structured-v1"
    with pytest.raises(FrozenInstanceError):
        saved.columns[0].name = "changed"
    encoded["outputs"][0]["columns"][0]["name"] = "mutated"
    assert saved.columns[0].name == "id"
    serialized = json.dumps(task.to_dict())
    for forbidden in ("result_ref", "storage", "chunk_count", "blob", "token", "prompt", "callback"):
        assert forbidden not in serialized


@pytest.mark.parametrize("capability", ["document_analyze", "document_compare", "tabular_analyze"])
def test_analysis_capabilities_are_reason_labels_not_a_mandatory_stage(capability):
    saved = reference()
    producer = replace(saved.producer, capability_id=capability)
    saved = replace(saved, producer=producer)
    result = TaskResult(producer, "reason", "complete", (saved,))
    assert result.role == "reason"
    with pytest.raises(ResultContractError):
        replace(result, role="gather")


@pytest.mark.parametrize("changes", [
    {"status": "complete", "validation": "not_validated"},
    {"status": "complete", "checks": ()},
    {"expected_count": None},
    {"actual_count": 2},
    {"coverage": Coverage(None, 1, "sources")},
    {"coverage": Coverage(2, 1, "sources")},
    {"preview": True},
    {"actual_count": True},
    {"status": "successful"},
])
def test_completeness_cannot_invent_success(changes):
    with pytest.raises(ResultContractError):
        replace(complete(3), **changes)


@pytest.mark.parametrize("status", ["pending", "invalid", "unavailable", "failed", "cancelled"])
def test_nonfinal_states_are_not_readable_even_with_partial_opt_in(status):
    state = complete(0, status=status, expected=3)
    with pytest.raises(ResultContractError):
        state.require_readable(allow_partial=True)


def test_partial_requires_explicit_acceptance_and_limitations():
    state = complete(2, status="partial", expected=3)
    with pytest.raises(ResultContractError):
        state.require_readable()
    state.require_readable(allow_partial=True)
    with pytest.raises(ResultContractError):
        replace(state, limitations=())
    with pytest.raises(ResultContractError):
        replace(state, validation="not_validated")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), {1: "coerced"}, (1, 2), object(), lambda: None])
def test_json_rejects_runtime_objects_callbacks_and_lossy_types(value):
    with pytest.raises(ResultContractError):
        validate_json(value)


def test_ordered_schema_rejects_extra_missing_and_wrong_typed_fields():
    for mutation in (
        {**ROWS[0], "hidden_source_id": "not-public"},
        {key: value for key, value in ROWS[0].items() if key != "amount"},
        {**ROWS[0], "enabled": 1},
        {**ROWS[0], "amount": False},
    ):
        with pytest.raises(ResultContractError):
            validate_record(mutation, COLUMNS)
    for record in ROWS:
        validate_record(record, COLUMNS)
    with pytest.raises(ResultContractError):
        replace(reference(), columns=(RecordColumn("id", "string"), RecordColumn("id", "integer")))


@pytest.mark.parametrize("injected", [
    {"storage": "blob"}, {"blob_path": "guessed"}, {"user_id": "foreign"},
    {"projection": {"flatten": True}}, {"result_ref": {"sha256": "a" * 64}},
])
def test_model_bindings_cannot_supply_identity_storage_or_projections(injected):
    value = InputBinding("prepare", "findings").to_dict()
    with pytest.raises(ResultContractError):
        InputBinding.from_dict({**value, **injected})


def test_binding_validation_infers_dependencies_without_stage_sort_or_mutation():
    planned = steps()
    original = deepcopy(planned)
    dependencies = validate_input_bindings(planned)
    assert dependencies == {"prepare": (), "inspect": ("prepare",), "gather_again": ("inspect",)}
    assert planned == original
    assert list(dependencies) == ["prepare", "inspect", "gather_again"]


@pytest.mark.parametrize("case", [
    "missing", "disabled", "disabled_branch", "kind", "cycle", "self", "missing_output", "budget", "duplicate",
])
def test_bad_dependencies_are_rejected_not_dropped(case):
    planned = steps()
    options = {}
    if case == "missing":
        planned = planned[1:]
    elif case == "disabled":
        planned[0] = replace(planned[0], enabled=False)
    elif case == "disabled_branch":
        planned = [replace(step, enabled=False) for step in planned]
    elif case == "kind":
        planned[0] = replace(planned[0], outputs=(OutputSpec("findings", "text-v1"),))
    elif case == "cycle":
        planned[0] = replace(planned[0], depends_on=("gather_again",))
    elif case == "self":
        planned[0] = replace(planned[0], depends_on=("prepare",))
    elif case == "missing_output":
        planned[0] = replace(planned[0], outputs=())
    elif case == "budget":
        options["max_steps"] = 2
    else:
        planned.append(planned[0])
    original = deepcopy(planned)
    with pytest.raises(ResultContractError):
        validate_input_bindings(planned, **options)
    assert planned == original


def test_existing_result_bindings_require_explicit_server_catalog():
    spec = InputSpec("data", InputBinding(existing_result="selected_findings"), ("records-v1",))
    planned = [StepBindings("inspect", True, inputs=(spec,))]
    with pytest.raises(ResultContractError):
        validate_input_bindings(planned)
    with pytest.raises(ResultContractError):
        validate_input_bindings(planned, existing_results={"selected_findings": reference().to_dict()})
    resolved = validate_input_bindings(planned, existing_results={"selected_findings": reference()})
    assert resolved == {"inspect": ()}


def test_narrative_analyze_and_tabular_fixtures_preserve_native_contract():
    native = native_analysis()
    envelope = build_orchestration_analysis_result(
        {"analysis_result": native}, user_id="owner", conversation_id="conversation-1", run_id="run-1", step_id="analyze",
    )
    assert envelope["contract_version"] == "analyze-final-v1"
    assert envelope["outputs"]["records"]["value"] == native["authoritative_result"]["value"]
    assert envelope["presentation"]["artifacts"] == []
    assert envelope["record_count"] == 3
    assert TABULAR_FOREGROUND["value"] == ROWS
    assert TABULAR_DURABLE == {"status": "running", "run_id": "native-job-1"}
    pending = TaskResult(reference().producer, "reason", "pending", ())
    assert pending.outputs == ()
    with pytest.raises(ResultContractError):
        replace(pending, status="complete")


def test_foreground_and_durable_native_api_fixtures_do_not_promote_a_preview():
    fixture = ResultFixture()
    native_source = {**fixture.sources["document-1"], "source_kind": "tabular", "file_name": "inventory.csv"}
    foreground = adapt_native_analysis_result(
        user_id="owner", conversation_id="conversation-1", source=native_source,
        complete_output={
            **deepcopy(TABULAR_FOREGROUND), "source_file_name": "inventory.csv",
            "source_authorization": {"source": "workspace"},
        },
        source_resolver=fixture.resolve,
    )
    values = [record["values"] for record in foreground["authoritative_result"]["value"]]
    assert values == ROWS
    assert foreground["generated_tabular_outputs"] == []
    assert foreground["analysis_validation"]["status"] == "valid"
    calls = []
    native_state = deepcopy(TABULAR_DURABLE)

    def read_native(user_id, conversation_id, run_id, selected_source):
        calls.append((user_id, conversation_id, run_id, selected_source["document_id"]))
        return deepcopy(native_state)

    pending = adapt_native_analysis_result(
        user_id="owner", conversation_id="conversation-1", source=native_source,
        generated_outputs=[{"run_id": "native-job-1", "status": "running"}],
        native_reader=read_native, source_resolver=fixture.resolve,
    )
    assert pending["execution_status"] == "pending"
    assert pending["analysis_validation"]["status"] == "pending"
    assert pending["authoritative_result"]["value"] == []
    assert pending["native_result_references"] == [{"run_id": "native-job-1", "status": "running"}]
    legacy_artifacts = [{"artifact_message_id": "existing-native-output", "output_format": "json"}]
    native_state.update({
        "status": "completed", "kind": "records", "value": ROWS, "source_row_count": 3,
        "batch_count": 1, "completed_batches": 1, "artifacts": legacy_artifacts,
    })
    finished = adapt_native_analysis_result(
        user_id="owner", conversation_id="conversation-1", source=native_source,
        generated_outputs=[{"run_id": "native-job-1", "status": "completed"}],
        native_reader=read_native, source_resolver=fixture.resolve,
    )
    values = [record["values"] for record in finished["authoritative_result"]["value"]]
    assert values == ROWS
    assert finished["generated_tabular_outputs"] == legacy_artifacts
    assert calls == [("owner", "conversation-1", "native-job-1", "document-1")] * 2


def test_source_free_and_multiple_outputs_are_named_data_not_files():
    fixture = ResultFixture()
    task = fixture.save(grounded=False, outputs=[
        NamedOutput("configuration", "structured-v1", SOURCE_FREE_VALUE, complete(1)),
        NamedOutput("report", "markdown-v1", "# Prepared content\n\nNo new source work.", complete(1)),
        NamedOutput("findings", "records-v1", ROWS, complete(3), COLUMNS),
    ])
    restored = TaskResult.from_dict(task.to_dict())
    restarted = fixture.restart()
    value = restarted.open_result(restored.output("configuration")).read_value()
    text = restarted.open_result(restored.output("report")).read_text()
    assert value == SOURCE_FREE_VALUE
    assert text.endswith("No new source work.")
    assert tuple(result.output_name for result in restored.outputs) == ("configuration", "report", "findings")
    assert restored.role == "reason"
    assert all("artifact" not in record for record in fixture.container.items.values())


def test_v1_checkpoint_state_and_fingerprint_ignore_unused_foundation():
    from functions_orchestration_checkpoints import context_binding, context_state, restore_context, step_input_fingerprint

    context = SimpleNamespace(user_message="Review retained findings", memory_context={}, selected_document_ids=[])
    plan = {"steps": [{
        "step_id": "a", "capability_id": "document_analyze", "arguments": {"document_ids": ["d1"]},
        "depends_on": [], "enabled": True, "optional": False,
    }]}
    binding = context_binding(context, plan, {})
    state = context_state(context)
    fingerprint = step_input_fingerprint(plan["steps"][0], context, binding)
    context.saved_analyses = []
    context.analysis_result_contexts = []
    context.unused_foundation_result = reference().to_dict()
    unchanged_binding = context_binding(context, plan, {})
    unchanged_state = context_state(context)
    unchanged_fingerprint = step_input_fingerprint(plan["steps"][0], context, binding)
    restore_context(context, {"state": state})
    restored_state = context_state(context)
    assert unchanged_binding == binding
    assert unchanged_state == restored_state == state
    assert unchanged_fingerprint == fingerprint
    assert "unused_foundation_result" not in restored_state
