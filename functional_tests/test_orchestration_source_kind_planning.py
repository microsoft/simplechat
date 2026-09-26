# test_orchestration_source_kind_planning.py
"""Plan mixed document types from authorized metadata, not user-facing labels.

Version: 0.261.140
Implemented in: 0.261.140

The real manifest classifier, context projection, planner, compiler and HTTP
routes run with metadata storage and model completions doubled. No document
contents, native jobs or generated files are read or produced while planning.
"""

import importlib
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from azure.core.exceptions import AzureError

from test_orchestration_harness_routes import modules, real_http_harness  # noqa: F401
from test_support.orchestration_harness_execution import compose_step, input_binding
from test_support.orchestration_revisions import AtomicMemoryContainer


LEFT = "narrative-doc"
RIGHT = "tabular-doc"


@pytest.fixture
def source_runtime(real_http_harness, monkeypatch):
    runtime = real_http_harness
    mixed = importlib.import_module("functions_mixed_source_orchestration")
    context = importlib.import_module("functions_orchestration_context")
    state = SimpleNamespace(reads=[], denied=set(), failure=None)
    documents = AtomicMemoryContainer("id")
    for identifier in (LEFT, RIGHT, *(f"document-{index}" for index in range(101))):
        documents.create_item({
            "id": identifier, "user_id": "owner",
            "file_name": "actual-data.csv" if identifier == RIGHT else "actual-report.pdf",
            "title": "Authorized document", "version": 1,
            "blob_container": "PRIVATE_CONTAINER", "blob_path": "PRIVATE_PATH",
        })
    monkeypatch.setattr(runtime.harness.config, "cosmos_user_documents_container", documents)

    def read_contexts(**kwargs):
        state.reads.append(deepcopy(kwargs))
        if state.failure is not None:
            raise state.failure
        return [
            None if document_id in state.denied else {
                "scope": "personal",
                "document": documents.read_item(document_id, document_id),
            }
            for document_id in kwargs["document_ids"]
        ]

    monkeypatch.setattr(mixed, "_default_document_context_batch_resolver", read_contexts)
    runtime.source_state = state
    runtime.context = context
    return runtime


def candidates(runtime, identifiers=(LEFT, RIGHT)):
    seeds = {
        "document_ids": list(identifiers), "doc_scope": "all",
        "document_labels": {identifier: "Display label, not a file type" for identifier in identifiers},
    }
    selected, _ = runtime.context.resolve_candidate_documents(
        "Compare selected sources.", "owner", seeds=seeds,
    )
    return selected, seeds


def proposal(*, narrative_comparison):
    producer = {
        "step_id": "gather",
        "capability_id": "document_compare" if narrative_comparison else "document_search",
        "arguments": {
            "comparison_prompt": "Compare the selected documents.",
            "left_document_id": LEFT, "right_document_ids": [RIGHT],
        } if narrative_comparison else {
            "query": "Compare the selected documents at an overview level.",
            "document_ids": [LEFT, RIGHT],
        },
    }
    answer = compose_step("draft", inputs={
        "evidence": {
            "binding": input_binding("gather", "comparison" if narrative_comparison else "prepared"),
            "allow_partial": False,
        },
    })
    answer["arguments"]["knowledge_basis"] = "sources"
    answer["delivers"] = ["answer"]
    return {
        "kind": "plan",
        "deliverables": [{
            "id": "answer", "kind": "answer", "requested": "explicit",
            "description": "An overview grounded in both selected sources.", "status": "planned",
        }],
        "steps": [producer, answer], "final_response": input_binding("draft"),
    }


def enrich(runtime, selected, seeds):
    return runtime.context.enrich_planner_candidates(
        selected, "owner", conversation_id="conversation-1", seeds=seeds,
    )


def test_kind_and_filename_come_from_authorized_metadata(source_runtime):
    runtime = source_runtime
    selected, seeds = candidates(runtime)
    selected[1]["source_kind"] = "narrative"
    selected[1]["file_name"] = "pretend.pdf"
    result = enrich(runtime, selected, seeds)
    by_id = {item["document_id"]: item for item in result}
    assert by_id[LEFT]["source_kind"] == "narrative"
    assert by_id[RIGHT]["source_kind"] == "tabular"
    assert by_id[RIGHT]["file_name"] == "actual-data.csv"
    assert "PRIVATE_" not in json.dumps(result)
    assert "storage_locator" not in json.dumps(result)
    assert runtime.source_state.reads[0]["user_id"] == "owner"
    assert runtime.source_state.reads[0]["conversation_id"] == "conversation-1"
    assert runtime.harness.model_calls == [] and runtime.harness.blobs.file_uploads == 0


def test_selected_inaccessible_source_is_not_silently_omitted(source_runtime):
    runtime = source_runtime
    selected, seeds = candidates(runtime)
    runtime.source_state.denied.add(RIGHT)
    with pytest.raises(runtime.context.CatalogResolutionError) as failure:
        enrich(runtime, selected, seeds)
    assert failure.value.code == "selected_source_unavailable"
    assert runtime.harness.model_calls == []


def test_optional_inaccessible_probe_candidate_is_not_offered(source_runtime):
    runtime = source_runtime
    selected, seeds = candidates(runtime)
    seeds["document_ids"] = [LEFT]
    runtime.source_state.denied.add(RIGHT)
    result = enrich(runtime, selected, seeds)
    assert [item["document_id"] for item in result] == [LEFT]


@pytest.mark.parametrize("error", [
    AzureError("PRIVATE_STORAGE"), TimeoutError("PRIVATE_TIMEOUT"),
    KeyError("PRIVATE_METADATA_FIELD"), IndexError("PRIVATE_METADATA_SHAPE"),
])
def test_metadata_outage_is_not_a_guessed_source_kind(source_runtime, error):
    runtime = source_runtime
    selected, seeds = candidates(runtime)
    runtime.source_state.failure = error
    with pytest.raises(runtime.context.CatalogResolutionError) as failure:
        enrich(runtime, selected, seeds)
    assert failure.value.code == "source_metadata_unavailable"
    assert "PRIVATE_" not in str(failure.value)
    assert runtime.harness.model_calls == []


def test_metadata_batches_preserve_all_explicit_sources(source_runtime):
    runtime = source_runtime
    identifiers = [f"document-{index}" for index in range(101)]
    selected, seeds = candidates(runtime, identifiers)
    result = enrich(runtime, selected, seeds)
    assert [item["document_id"] for item in result] == identifiers
    assert [len(read["document_ids"]) for read in runtime.source_state.reads] == [100, 1]


def test_source_free_planning_never_reads_document_metadata(source_runtime):
    result = enrich(source_runtime, [], {})
    assert result == []
    assert source_runtime.source_state.reads == []


@pytest.mark.parametrize("capability", ["document_compare", "document_analyze"])
def test_known_tabular_sources_cannot_use_narrative_steps(source_runtime, capability):
    schema = source_runtime.harness.schema
    step = proposal(narrative_comparison=True)["steps"][0]
    if capability == "document_analyze":
        step.update(capability_id=capability, arguments={"analysis_prompt": "Analyze.", "document_ids": [RIGHT]})
    with pytest.raises(schema.PlanValidationError) as failure:
        schema.validate_plan_document_source_kinds(
            {"steps": [step]}, {LEFT: "narrative", RIGHT: "tabular"},
        )
    assert failure.value.code == "source_kind_invalid"
    assert failure.value.rule == "narrative_source_required"
    schema.validate_plan_document_source_kinds(
        {"steps": [step]}, {LEFT: "narrative", RIGHT: "narrative"},
    )


def test_http_planning_sees_source_kinds_and_repairs_the_mismatch(source_runtime):
    runtime, harness = source_runtime, source_runtime.harness
    harness.settings["document_action_capabilities"] = {
        "comparison": {"enabled": True, "chat_max_documents": 2},
    }
    request = "Compare these two documents."
    harness.replies = [
        json.dumps({
            "relationship": "new_topic", "resolved_message": request, "message_ids": [],
            "requires_retrieval": True, "clarification": "",
        }),
        json.dumps(proposal(narrative_comparison=True)),
        json.dumps(proposal(narrative_comparison=False)),
    ]
    response = runtime.client.post("/api/v2/orchestration/plan", json={
        "conversation_id": "conversation-1", "turn_id": "typed-source-turn",
        "message": request, "selected_document_ids": [LEFT, RIGHT],
        "context_documents": [
            {"id": LEFT, "label": "Friendly report"},
            {"id": RIGHT, "label": "Pretend PDF.pdf", "source_kind": "narrative"},
        ],
        "approval_mode": "manual",
    }, buffered=True)
    frames = [
        json.loads(frame.partition("data:")[2].strip())
        for frame in response.get_data(as_text=True).split("\n\n") if frame.startswith("data:")
    ]
    assert response.status_code == 200 and "plan" in frames[-1], frames
    plan = frames[-1]["plan"]
    calls = [
        call for call in harness.model_calls
        if call["messages"][0]["content"].startswith("Plan bounded work")
    ]
    assert len(calls) == 2
    payload = json.loads(calls[0]["messages"][1]["content"])
    offered = {item["document_id"]: item for item in payload["candidate_documents"]}
    assert offered[RIGHT]["source_kind"] == "tabular"
    assert offered[RIGHT]["file_name"] == "actual-data.csv"
    assert "PRIVATE_" not in json.dumps(payload)
    assert "narrative document analysis cannot process" in calls[1]["messages"][-1]["content"]
    assert plan["steps"][0]["capability_id"] == "document_search"
    used = harness.schema.plan_document_ids(plan)
    assert set(used) == {LEFT, RIGHT}
    assert harness.blobs.file_uploads == 0 and harness.assistant_messages() == []


def test_missing_analyze_binding_gets_one_repair_without_inventing_sources(source_runtime):
    runtime, harness = source_runtime, source_runtime.harness
    selected, seeds = candidates(runtime, (LEFT,))
    offered = enrich(runtime, selected, seeds)
    read = {
        "step_id": "read", "capability_id": "document_analyze",
        "arguments": {"analysis_prompt": "Analyze the selected report.", "document_ids": [LEFT]},
    }
    answer = compose_step("draft", inputs={
        "findings": {"binding": input_binding("read", "findings"), "allow_partial": False},
    })
    answer["arguments"]["knowledge_basis"] = "sources"
    answer["delivers"] = ["answer"]
    corrected = {
        **proposal(narrative_comparison=False),
        "steps": [read, answer],
    }
    rejected = deepcopy(corrected)
    rejected["steps"][0]["arguments"].pop("document_ids")
    harness.replies = [json.dumps(rejected), json.dumps(corrected)]
    payload = runtime.context.build_planner_context("Analyze the selected report.", candidates=offered, seeds=seeds)
    kind, plan = harness.planner.plan_request(
        "Analyze the selected report.", payload, "conversation-1", "owner",
        settings=harness.settings, seeds=seeds, authorized_document_ids=[LEFT],
        request_context=harness.services().capability_request_bindings(),
    )
    used = harness.schema.plan_document_ids(plan)
    assert kind == "plan" and len(harness.model_calls) == 2
    assert used == [LEFT]
    assert "arguments.document_ids" in harness.model_calls[1]["messages"][-1]["content"]


def test_source_kind_repair_stays_bounded_and_never_drops_selected_sources(source_runtime):
    runtime, harness = source_runtime, source_runtime.harness
    harness.settings["document_action_capabilities"] = {"comparison": {"enabled": True, "chat_max_documents": 2}}
    selected, seeds = candidates(runtime)
    offered = enrich(runtime, selected, seeds)
    payload = runtime.context.build_planner_context("Compare the documents.", candidates=offered, seeds=seeds)
    rejected = proposal(narrative_comparison=True)
    harness.replies = [json.dumps(rejected), json.dumps(rejected)]
    with pytest.raises(harness.planner.PlannerError) as failure:
        harness.planner.plan_request(
            "Compare the documents.", payload, "conversation-1", "owner",
            settings=harness.settings, seeds=seeds, authorized_document_ids=[LEFT, RIGHT],
            request_context=harness.services().capability_request_bindings(),
        )
    assert len(harness.model_calls) == 2
    assert failure.value.message == harness.planner.SOURCE_KIND_FAILURE_MESSAGE
    assert harness.blobs.file_uploads == 0 and harness.assistant_messages() == []


def test_editor_revalidates_actual_source_kinds_before_accepting_a_version(source_runtime):
    runtime, harness = source_runtime, source_runtime.harness
    harness.settings["document_action_capabilities"] = {"comparison": {"enabled": True, "chat_max_documents": 2}}
    record = harness.create(
        steps=proposal(narrative_comparison=True)["steps"],
        final_response=input_binding("draft"), seeds={"document_ids": [LEFT, RIGHT]},
    )
    editing = importlib.import_module("functions_orchestration_plan_editing")
    context = editing._turn_context(record)
    original = deepcopy(record["plan"])
    with pytest.raises(editing.PlanRevisionError) as failure:
        editing.validate_edited_plan(
            record["plan"], context, "owner", harness.settings,
            {"user_roles": ["Admin"], "user_enable_agents": False},
            **harness.services().capability_request_bindings(),
        )
    assert failure.value.code == "source_changed"
    assert record["plan"] == original
    assert harness.model_calls == [] and harness.blobs.file_uploads == 0
