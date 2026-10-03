# test_workflow_saved_results_container_access.py
"""
Functional test for workflow saved results taking their access from their container.
Version: 0.261.231
Implemented in: 0.261.231

This test ensures that saved and generated workflow results are never re-checked
against the documents they came from. Deleting, re-uploading or holding a source
document does not hide or fail saved task results, node results, execution,
Repeat or loop history, run history previews or chat follow-ups on a workflow
result, and a later task can still consume an earlier task's output. The checks
that stay still hold: a held uploaded document is refused when a workflow reads
it as an input (loop document selection and items, reference inputs, File Sync
and other configured sources), each task's model fence covers only its own input
reads, group results stay limited to group members, someone else's run reads like
a missing one, and forged lineage or hash mismatches are still refused.

Real workflow modules run over the existing in-memory result, journal and Cosmos
fixtures. Only document, group and storage boundaries are doubled.
"""

import ast
import copy
import json
import logging
import sys
from pathlib import Path

import pytest
from azure.core.exceptions import AzureError
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from flask import Flask, jsonify, request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "application" / "single_app"))
sys.path.insert(0, str(ROOT / "functional_tests"))

# Production imports follow the isolated worktree import setup.
from content_screening import access as screening_access  # noqa: E402
from content_screening.contracts import DocumentHeldError  # noqa: E402
import functions_saved_analysis as saved  # noqa: E402
import functions_workflow_result_reader as reader  # noqa: E402
from functions_analysis_access import (  # noqa: E402
    AnalysisResultUnavailable, analysis_source_snapshot, build_analysis_access,
)
from functions_workflow_bindings import load_workflow_reference  # noqa: E402
from functions_workflow_execution_history import workflow_execution_history, workflow_execution_result_page  # noqa: E402
from functions_workflow_identity import workflow_execution_id  # noqa: E402
from functions_workflow_inspection import workflow_flow_inspection  # noqa: E402
from functions_workflow_iterations import (  # noqa: E402
    load_frozen_item_value, load_frozen_loop, loop_execution_identity, read_frozen_item,
)
from functions_workflow_loop_history import (  # noqa: E402
    workflow_execution_provenance_page, workflow_execution_records_page, workflow_loop_items_page,
)
from functions_workflow_loop_inputs import WorkflowLoopInputError, iter_workflow_loop_documents  # noqa: E402
from functions_workflow_node_results import (  # noqa: E402
    WorkflowRecordPageTooLarge, authorize_workflow_node_result_read, load_workflow_node_input,
    open_workflow_record_input,
)
from functions_workflow_readiness import reconcile_workflow_pending_output  # noqa: E402
from functions_workflow_repeat_history import workflow_repeat_iterations_page, workflow_repeat_state_page  # noqa: E402
from functions_workflow_result_store import WorkflowResultStorageUnavailableError  # noqa: E402
from functions_workflow_results import (  # noqa: E402
    authorize_workflow_run_read, authorize_workflow_task_result_read, build_workflow_task_result,
    load_workflow_task_input, persist_workflow_task_result, workflow_result_summary,
)
from functions_workflow_runtime_store import RuntimeUnavailable, WorkflowRuntimeConflict  # noqa: E402
from functions_workflow_definitions import workflow_definition_revision  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402
from test_support.workflow_result_chat import (  # noqa: E402
    OTHER_USER, RUN_ID as CHAT_RUN_ID, USER, WORKFLOW_ID as CHAT_WORKFLOW_ID, RunFixture,
    analysis_result as chat_analysis_result,
)
from test_workflow_for_each_execution import execute_loop, loop_definition, loop_runtime  # noqa: E402
from test_workflow_repeat_execution import execute_repeat, repeat_definition, repeat_head, repeat_runtime  # noqa: E402
from test_workflow_result_contract import RUN_ID, WORKFLOW, SerializedSections  # noqa: E402
from test_workflow_structured_flow import binding, definition as structured_definition, task  # noqa: E402
from test_workflow_task_sequence import load_functions, load_runner_helpers  # noqa: E402


FIX_VERSION = "0.261.231"
ROUTES = ROOT / "application" / "single_app" / "route_backend_workflows.py"
RUNNER = ROOT / "application" / "single_app" / "functions_workflow_runner.py"
SOURCE = {
    "document_id": "source-1", "scope": "personal", "scope_id": "owner",
    "source_version": "1", "source_revision": "etag-1",
}
CHANGES = ["deleted", "reuploaded", "held"]


class SourceChanges:
    """The documents behind saved results, as a current reader would now find them.

    A saved result must never ask: every call is recorded so the tests can prove
    that no source is re-resolved, whatever happened to the document.
    """

    def __init__(self, monkeypatch):
        self.state = "current"
        self.calls = []
        monkeypatch.setattr("functions_analysis_access.resolve_authorized_source_manifest", self)

    def __call__(self, document_ids, **context):
        self.calls.append((list(document_ids), context.get("user_id")))
        if self.state == "held":
            raise DocumentHeldError()
        revision = "etag-2" if self.state == "reuploaded" else SOURCE["source_revision"]
        version = "2" if self.state == "reuploaded" else SOURCE["source_version"]
        status = "unresolved" if self.state == "deleted" else "authorized"
        return [
            {**SOURCE, "document_id": document_id, "source_version": version, "source_revision": revision,
             "authorization_status": status}
            for document_id in document_ids
        ]


@pytest.fixture
def changes(monkeypatch):
    return SourceChanges(monkeypatch)


def test_fix_version_is_present():
    assert_app_version_at_least(FIX_VERSION)


# --- Saved task results (contract v1) ----------------------------------------------------


def save_task(store, result, task_id, consumed=()):
    envelope = build_workflow_task_result(result, workflow=WORKFLOW, run_id=RUN_ID, task={"id": task_id})
    envelope["consumed_inputs"] = list(consumed)
    return persist_workflow_task_result(envelope, workflow=WORKFLOW, run_id=RUN_ID, task_id=task_id, save_result=store.save)


def analysis_output():
    return {
        "reply": "Two controls have no owner.",
        "analysis_access": build_analysis_access([SOURCE]),
        "authoritative_result": {"kind": "records", "value": [{"finding": "No owner"}, {"finding": "Stale review"}]},
    }


def run_item(task_id, manifest, reference, consumed=()):
    return {
        "workflow_id": WORKFLOW["id"], "run_id": RUN_ID, "task_id": task_id, "item_type": "task",
        "status": "succeeded", "output_summary": f"{task_id} preview",
        "workflow_result": workflow_result_summary(manifest, reference), "consumed_inputs": list(consumed),
    }


@pytest.fixture
def v1_run(changes):
    store = SerializedSections()
    analyze_manifest, analyze_ref = save_task(store, analysis_output(), "analyze")
    _, consumed = load_workflow_task_input(
        WORKFLOW, RUN_ID, "analyze", analyze_ref, load_result=store.load, source_resolver=changes,
    )
    explain_manifest, explain_ref = save_task(store, {"reply": "Both findings need an owner."}, "explain", [consumed])
    items = [
        run_item("analyze", analyze_manifest, analyze_ref),
        run_item("explain", explain_manifest, explain_ref, [consumed]),
    ]
    changes.calls.clear()
    return store, analyze_ref, explain_ref, consumed, items


@pytest.mark.parametrize("change", CHANGES)
def test_saved_task_results_ignore_source_changes_and_keep_provenance(v1_run, changes, change):
    store, analyze_ref, explain_ref, consumed, items = v1_run
    changes.state = change
    manifest, access = authorize_workflow_task_result_read(
        WORKFLOW, RUN_ID, "explain", explain_ref, reader_user_id="owner",
        load_result=store.load, source_resolver=changes,
    )
    assert manifest["identity"]["task_id"] == "explain"
    assert access["sources"] == analysis_source_snapshot([SOURCE]) and access["source_count"] == 1
    assert access["source_snapshot_changed"] is False
    authorize_workflow_run_read(
        WORKFLOW, RUN_ID, reader_user_id="owner", result_items=items,
        load_result=store.load, source_resolver=changes,
    )
    assert consumed["analysis_result"] is True
    assert changes.calls == []


@pytest.mark.parametrize("change", CHANGES)
def test_a_later_task_consumes_an_earlier_output_after_its_source_changed(v1_run, changes, change):
    store, analyze_ref, explain_ref, _, _ = v1_run
    changes.state = change
    records, receipt = load_workflow_task_input(
        WORKFLOW, RUN_ID, "analyze", analyze_ref, load_result=store.load, source_resolver=changes,
    )
    payload = json.loads(records)
    assert payload["value"] == [{"finding": "No owner"}, {"finding": "Stale review"}]
    assert payload["source_snapshot_changed"] is False and receipt["analysis_result"] is True
    report, report_receipt = load_workflow_task_input(
        WORKFLOW, RUN_ID, "explain", explain_ref, load_result=store.load, source_resolver=changes,
    )
    assert json.loads(report)["value"] == "Both findings need an owner."
    # Provenance still travels with the derived result; it just isn't re-checked.
    assert report_receipt["analysis_result"] is True
    assert changes.calls == []


@pytest.mark.parametrize("change", CHANGES)
def test_run_history_previews_stay_visible_after_a_source_changes(v1_run, changes, change):
    store, _, _, _, items = v1_run
    changes.state = change
    run_record = {
        "id": RUN_ID, "workflow_id": WORKFLOW["id"], "response_preview": "Both findings need an owner.",
        "error": "", "task_results": copy.deepcopy(items),
    }

    def read(*args, **kwargs):
        return authorize_workflow_task_result_read(*args, load_result=store.load, source_resolver=changes, **kwargs)

    sanitized, sanitized_items, available = saved.sanitize_workflow_analysis_history(
        WORKFLOW, run_record, "owner", items=copy.deepcopy(items), result_reader=read,
    )
    assert available is True
    assert sanitized == run_record and sanitized_items == items
    assert changes.calls == []


@pytest.mark.parametrize("forgery", ["producer", "output_ref"])
def test_forged_lineage_and_hash_mismatches_are_still_refused(v1_run, changes, forgery):
    store, _, _, consumed, items = v1_run
    forged = copy.deepcopy(consumed)
    if forgery == "producer":
        forged["producer"]["workflow_id"] = "foreign-workflow"
    else:
        forged["output_ref"] = {**forged["output_ref"], "sha256": "0" * 64}
    manifest, reference = save_task(store, {"reply": "A purported explanation."}, "forged", [forged])
    with pytest.raises(AnalysisResultUnavailable) as refused:
        authorize_workflow_task_result_read(
            WORKFLOW, RUN_ID, "forged", reference, load_result=store.load, source_resolver=changes,
        )
    assert refused.value.code == "analysis_lineage_invalid"
    forged_item = run_item("forged", manifest, reference, [forged])
    run_record = {"id": RUN_ID, "workflow_id": WORKFLOW["id"], "response_preview": "Final.", "task_results": [forged_item]}

    def read(*args, **kwargs):
        return authorize_workflow_task_result_read(*args, load_result=store.load, source_resolver=changes, **kwargs)

    withheld, _, available = saved.sanitize_workflow_analysis_history(WORKFLOW, run_record, "owner", result_reader=read)
    assert available is False
    assert withheld["task_results"][0]["output_summary"] == saved.UNVERIFIED_WORKFLOW_OUTPUT_MESSAGE
    assert "source" not in saved.UNVERIFIED_WORKFLOW_OUTPUT_MESSAGE.lower()


# --- Chat follow-ups on a workflow result -------------------------------------------------


def chat_world():
    fixture = RunFixture()
    _, reference = fixture.add_task("task-analyze-1", chat_analysis_result(), order=1, label="Analyze the sources")
    fixture.add_task(
        "task-explain-2", {"reply": "The analysis found one owner gap."}, order=2, label="Explain",
        consumed=[fixture.receipt("task-analyze-1", reference)],
    )
    descriptor = fixture.read()["descriptor"]
    context = {"workflow_id": CHAT_WORKFLOW_ID, "run_id": CHAT_RUN_ID, "result_sha256": descriptor["result_sha256"]}
    fixture.reset_counters()
    return fixture, descriptor, context


def authorize_context(fixture):
    def authorize(user_id, context):
        return reader.authorize_workflow_result_context(
            user_id, context, containers=fixture.containers, load_result=fixture.store.load,
            read_page=fixture.store.read_page, source_resolver=fixture.sources,
        )
    return authorize


def test_chat_follow_ups_read_and_keep_answers_after_source_access_is_lost():
    fixture, descriptor, context = chat_world()
    fixture.sources.allowed = False
    result = fixture.read(include_excerpts=True)
    assert result["descriptor"]["result_sha256"] == descriptor["result_sha256"]
    assert result["saved_inputs"] or result["excerpts"]
    assert authorize_context(fixture)(USER, context)["result_sha256"] == descriptor["result_sha256"]
    answer = {
        "id": "msg-answer", "conversation_id": "conv-private", "role": "assistant",
        "content": "The analysis found one owner gap.",
        "metadata": {"workflow_result": dict(descriptor), "workflow_result_contexts": [dict(context)]},
    }
    shown = saved.sanitize_saved_analysis_messages(
        [answer], USER, workflow_result_reader=authorize_context(fixture),
        conversation_reader=lambda conversation_id: {
            "id": conversation_id, "user_id": USER, "chat_type": "new", "title": "Digest",
        },
        result_reader=lambda *args: None,
    )
    assert shown == [answer]
    assert fixture.sources.readers == []


def test_someone_elses_run_and_a_changed_result_are_still_refused():
    fixture, _, context = chat_world()
    missing = pytest.raises(reader.WorkflowResultUnavailable)
    with missing as other:
        fixture.read(user_id=OTHER_USER)
    assert other.value.code == "workflow_result_not_found"
    with pytest.raises(reader.WorkflowResultUnavailable) as changed:
        authorize_context(fixture)(USER, {**context, "result_sha256": "e" * 64})
    assert changed.value.code == "workflow_result_changed"
    message = reader.workflow_result_error_payload(reader.WorkflowResultUnavailable("workflow_result_access_denied"))[0]
    assert "source" not in message["error"].lower()


def test_a_forged_chat_result_is_invalid_not_a_source_denial():
    fixture, _, _ = chat_world()

    def forge(envelope):
        envelope["identity"]["task_id"] = "someone-elses-task"

    fixture.add_task("task-forged-3", {"reply": "Forged."}, order=3, edit=forge)
    with pytest.raises(reader.WorkflowResultUnavailable) as refused:
        fixture.read()
    assert refused.value.code == "workflow_result_invalid"


# --- Structured node results, execution history and records ------------------------------


def analysis_flow():
    records = {"kind": "records", "schema": {"type": "array", "items": {"type": "object"}}}
    return {
        "id": "workflow", "user_id": "owner", "definition_version": 3, "durable_execution": True,
        "runner_type": "model", "chat_capabilities_enabled": False,
        "limits": {"max_executions": 5000, "deadline_seconds": 86400},
        "error_handling": {"strategy": "halt", "retry_count": 0},
        "tasks": [
            task("analyze", contract=records),
            task("explain", inputs=[binding("analyze-node", "findings", "records")]),
        ],
        "flow": {"id": "root", "nodes": [
            {"id": "analyze-node", "kind": "task", "task_id": "analyze"},
            {"id": "explain-node", "kind": "task", "task_id": "explain"},
        ], "outputs": [binding("explain-node", "report", "text")]},
    }


def run_analysis_flow(workflow, store, changes, *, change_after_analysis=None):
    def produce(current, resolved, execution):
        if current["id"] == "analyze":
            return {"reply": "Two findings.", "authoritative_result": {
                "kind": "records", "value": [{"finding": "No owner"}, {"finding": "Stale review"}],
            }}
        return {"reply": f"Explained {len(resolved['values']['findings'])} saved findings."}

    def provenance(current, envelope):
        if current["id"] == "analyze":
            envelope["analysis_access"] = build_analysis_access([SOURCE])
            if change_after_analysis:
                # The document changes after the producer read it, before the consumer runs.
                changes.state = change_after_analysis

    return execute_repeat(workflow, store, result_for_task=produce, envelope_transform=provenance)


@pytest.mark.parametrize("change", CHANGES)
def test_a_later_structured_task_consumes_an_output_whose_source_changed(monkeypatch, changes, change):
    workflow, store, _, _, _ = repeat_runtime(monkeypatch, definition=analysis_flow())
    flow, calls = run_analysis_flow(workflow, store, changes, change_after_analysis=change)
    assert [call[0] for call in calls] == ["analyze", "explain"]
    assert flow.finished and not flow.failed
    final = flow.final_outputs[0]
    report, _ = load_workflow_node_input(workflow, "run", final["producer"], final["result_ref"])
    assert json.loads(report)["value"] == "Explained 2 saved findings."
    assert changes.calls == []


@pytest.mark.parametrize("change", CHANGES)
def test_structured_results_history_and_records_ignore_source_changes(monkeypatch, changes, change):
    workflow, store, _, _, _ = repeat_runtime(monkeypatch, definition=analysis_flow())
    flow, _ = run_analysis_flow(workflow, store, changes)
    changes.state = change
    changes.calls.clear()
    analyze_id = workflow_execution_id(workflow, "run", "analyze-node")
    explain_id = workflow_execution_id(workflow, "run", "explain-node")
    history = workflow_execution_history(workflow, "run", reader_user_id="owner")
    assert {row["execution_id"] for row in history["executions"]} >= {analyze_id, explain_id}
    page = workflow_execution_result_page(workflow, "run", explain_id, 1, reader_user_id="owner")
    assert "Explained 2 saved findings." in page["content"]
    records = workflow_execution_records_page(workflow, "run", analyze_id, 1, reader_user_id="owner")
    assert records["records"] == [{"finding": "No owner"}, {"finding": "Stale review"}]
    contributors = workflow_execution_provenance_page(workflow, "run", explain_id, 1, reader_user_id="owner")
    assert contributors["contributors"][0]["producer"]["node_id"] == "analyze-node"
    analysis = flow.completed["analyze-node"]["summary"]
    manifest, access = authorize_workflow_node_result_read(
        workflow, "run", analysis["producer"], analysis["result_ref"], reader_user_id="a-group-member",
    )
    assert access["sources"] == analysis_source_snapshot([SOURCE]) and access["source_snapshot_changed"] is False
    rows = open_workflow_record_input(workflow, "run", analysis["producer"], analysis["result_ref"]).read_records()
    assert rows[1] == 2
    assert changes.calls == []


def test_forged_structured_identity_is_still_refused(monkeypatch, changes):
    workflow, store, _, _, _ = repeat_runtime(monkeypatch, definition=analysis_flow())
    flow, _ = run_analysis_flow(workflow, store, changes)
    final = flow.final_outputs[0]
    analysis = flow.completed["analyze-node"]["summary"]
    refused = (AnalysisResultUnavailable, ValueError, CosmosResourceNotFoundError)
    for forged in ({"task_id": "analyze"}, {"node_id": "analyze-node"}, {"attempt": 2}, {"execution_id": "f" * 64}):
        with pytest.raises(refused):
            authorize_workflow_node_result_read(workflow, "run", {**final["producer"], **forged}, final["result_ref"])
    # A producer identity bound to another result's hash is refused too.
    with pytest.raises(refused):
        authorize_workflow_node_result_read(workflow, "run", analysis["producer"], final["result_ref"])
    with pytest.raises(refused):
        load_workflow_node_input(workflow, "run", final["producer"], {**final["result_ref"], "sha256": "0" * 64})


# --- Repeat history -----------------------------------------------------------------------


@pytest.mark.parametrize("change", CHANGES)
def test_repeat_rounds_state_and_history_ignore_source_changes(monkeypatch, changes, change):
    workflow, store, _, _, _ = repeat_runtime(monkeypatch, definition=repeat_definition())

    def provenance(current, envelope):
        if current["id"] == "source":
            envelope["analysis_access"] = build_analysis_access([SOURCE])
            # The Repeat state is consumed after its source document changed.
            changes.state = change

    flow, calls = execute_repeat(workflow, store, target=2, envelope_transform=provenance)
    assert [call[0] for call in calls] == ["source", "body", "body"] and flow.finished
    repeat_id = repeat_head(workflow, store)["execution_id"]
    rounds = workflow_repeat_iterations_page(workflow, "run", repeat_id, reader_user_id="owner")
    assert rounds["total_count"] == 2 and rounds["source_snapshot_changed"] is False
    state = workflow_repeat_state_page(workflow, "run", repeat_id, 0, reader_user_id="owner")
    assert state["available"] is True and state["states"][0]["name"] == "state"
    assert workflow_execution_history(workflow, "run", reader_user_id="owner")["total_count"] >= 3
    assert changes.calls == []


# --- Document loops: history ignores changes, item reads still check ---------------------


DOCUMENTS = ("doc-a", "doc-b")


def document_loop():
    workflow = loop_definition()
    workflow["tasks"] = workflow["tasks"][1:]
    workflow["flow"]["nodes"] = workflow["flow"]["nodes"][1:]
    loop = workflow["flow"]["nodes"][0]
    loop["inputs"] = []
    loop["iterable"] = {
        "kind": "documents", "documents": [{"document_id": key, "scope_type": "personal"} for key in DOCUMENTS],
    }
    return workflow


@pytest.fixture
def documents(monkeypatch):
    held = set()

    def read_document(*, document_id, user_id, group_id=None, public_workspace_id=None):
        if document_id in held:
            raise DocumentHeldError()
        return {
            "id": document_id, "user_id": user_id, "file_name": f"{document_id}.pdf",
            "version": 1, "_etag": f"etag-{document_id}",
        }

    monkeypatch.setattr("functions_workflow_loop_inputs._default_read_document", read_document)
    return held


def test_document_loop_history_lists_items_after_a_document_is_held_but_reads_refuse_it(
    monkeypatch, changes, documents,
):
    workflow, store, _, _ = loop_runtime(monkeypatch, definition=document_loop())
    flow, calls = execute_loop(workflow, store, None)
    assert [call[0] for call in calls] == ["body", "body"] and flow.finished
    documents.add("doc-a")
    changes.state = "held"
    changes.calls.clear()
    identity = loop_execution_identity(workflow, "run", "each", [])
    items = workflow_loop_items_page(workflow, "run", identity["execution_id"], reader_user_id="owner")
    assert [item["label"] for item in items["items"]] == ["doc-a.pdf", "doc-b.pdf"]
    assert workflow_execution_history(workflow, "run", reader_user_id="owner")["total_count"] >= 3
    final = flow.final_outputs[0]
    collected, _ = load_workflow_node_input(workflow, "run", final["producer"], final["result_ref"])
    assert [row["document_id"] for row in json.loads(collected)["value"]] == list(DOCUMENTS)
    assert changes.calls == []
    # The input check stays: the held document is refused when it is read as a loop input.
    manifest, _, _ = load_frozen_loop(workflow, "run", identity, store=store)
    held_item, open_item = (read_frozen_item(workflow, "run", manifest, index) for index in range(2))
    with pytest.raises(AnalysisResultUnavailable):
        load_frozen_item_value(workflow, "run", manifest, held_item, reader_user_id="owner")
    assert load_frozen_item_value(workflow, "run", manifest, open_item, reader_user_id="owner")["value"]["document_id"] == "doc-b"
    with pytest.raises(WorkflowLoopInputError):
        list(iter_workflow_loop_documents(
            workflow, document_loop()["flow"]["nodes"][0]["iterable"], actor_user_id="owner",
            max_items=10, settings={}, capture_metadata={},
        ))


# --- Reference inputs, definition inspection and configured sources ----------------------


REFERENCE_WORKFLOW = {"id": "workflow", "user_id": "owner"}
HELD_REFERENCE = {
    "id": "held-reference", "name": "held-reference", "document_id": "held-document",
    "scope_type": "personal", "scope_id": "owner",
}
OPEN_REFERENCE = {**HELD_REFERENCE, "id": "open-reference", "name": "open-reference", "document_id": "open-document"}


def resolve_reference(**arguments):
    if arguments["document_id"] == "held-document":
        raise DocumentHeldError()
    return {"scope": arguments["doc_scope"], "document": {"id": arguments["document_id"], "user_id": "owner"}}


def test_a_held_reference_is_refused_as_a_run_input():
    with pytest.raises(DocumentHeldError):
        load_workflow_reference(
            REFERENCE_WORKFLOW, HELD_REFERENCE, actor_user_id="owner", resolve_document=resolve_reference,
            load_chunks=lambda **kwargs: pytest.fail("A held reference must not be read."),
        )


def test_inspecting_a_definition_marks_a_held_reference_instead_of_denying_it(monkeypatch):
    def no_content(**kwargs):
        raise AssertionError("Inspection must not load document content.")

    monkeypatch.setattr("functions_workflow_bindings._source_helpers", lambda: (resolve_reference, no_content))
    workflow = structured_definition()
    workflow["reference_inputs"] = [HELD_REFERENCE, OPEN_REFERENCE]
    topology = workflow_flow_inspection(workflow, reader_user_id="owner")
    assert topology["nodes"] and topology["source"]["kind"] == "saved"
    selection = workflow_flow_inspection(
        workflow, reader_user_id="owner", node_id="root", section="selection",
        revision=workflow_definition_revision(workflow),
    )
    rows = {row["label"]: row["value"] for row in selection["items"]}
    assert rows["held-reference"]["available"] is False
    assert "available" not in rows["open-reference"]
    assert all("_source" not in row for row in selection["items"])


def test_a_held_configured_source_is_still_refused_before_its_output_is_adopted():
    source = {**SOURCE, "file_name": "inventory.csv", "source_kind": "tabular"}
    result = {
        "reply": "The analysis is being prepared.",
        "generated_tabular_outputs": [{"export_run_id": "native-run", "background_export": True}],
        "analysis_result": {"execution_status": "pending", "analysis_sources": [source]},
    }
    with pytest.raises(AnalysisResultUnavailable):
        reconcile_workflow_pending_output(
            REFERENCE_WORKFLOW, result, conversation_id="conversation", actor_user_id="owner",
            get_status=lambda *args: {"run_id": "native-run", "conversation_id": "conversation", "status": "completed"},
            native_adapter=lambda **kwargs: pytest.fail("A held source's output must not be adopted."),
            source_resolver=lambda ids, **kwargs: [{**source, "authorization_status": "unresolved"} for _ in ids],
        )


def test_the_file_sync_trigger_still_refuses_an_unavailable_source():
    queued = []

    def unavailable_source(scope_type, source_id, user_id, scope_id=None):
        raise PermissionError("This File Sync source is not available to you.")

    helpers = load_functions(RUNNER, {
        "_get_workflow_file_sync_config", "_merge_file_sync_counts", "_summarize_file_sync_run",
        "_execute_workflow_file_sync",
    }, {
        "get_authorized_sync_source": unavailable_source,
        "queue_file_sync_source_run": lambda *args, **kwargs: queued.append(args) or {},
    })
    workflow = {"id": "workflow", "user_id": "owner", "file_sync": {
        "enabled": True, "sources": [{"scope_type": "group", "scope_id": "group-1", "source_id": "sync-1"}],
    }}
    with pytest.raises(PermissionError):
        helpers["_execute_workflow_file_sync"](workflow, "run", "schedule")
    assert queued == []


# --- The model fence covers each task's own input reads -----------------------------------


def fenced_workflow():
    return {
        "id": "workflow-1", "name": "Fenced", "user_id": "owner", "runner_type": "model",
        "document_action": {"type": "none"},
        "tasks": [
            {"id": "read", "name": "Read", "instructions": "Read the uploaded report."},
            {"id": "explain", "name": "Explain", "instructions": "Explain the previous output."},
        ],
        "error_handling": {"strategy": "continue", "retry_count": 0},
    }


def test_each_task_has_its_own_model_fence(monkeypatch):
    states = {"doc-a": "available", "doc-b": "available"}

    def read_document(document_id, user_id, group_id=None, public_workspace_id=None, **kwargs):
        if states[document_id] == "held":
            raise DocumentHeldError()
        return {"id": document_id, "user_id": user_id, "version": 1}

    monkeypatch.setattr(screening_access, "_read_authorized_document", read_document)

    def dispatch(workflow, *args, **kwargs):
        task_id = workflow["active_task"]["id"]
        if task_id == "read":
            screening_access.assert_document_available("doc-a", user_id="owner")
            screening_access.assert_current_request_sources_available("owner")
            # The document is held after this task read it and answered from it.
            states["doc-a"] = "held"
            return {"reply": "The report lists two findings."}
        # The later task reads only the earlier task's saved output before its model call.
        screening_access.assert_current_request_sources_available("owner")
        return {"reply": "Both findings need an owner."}

    helpers, _ = load_runner_helpers(dispatch)
    with Flask("model-fence").test_request_context("/"):
        result = helpers["_execute_workflow_task_sequence"](fenced_workflow(), {}, "conversation-1", "run-1", None, {})
    assert [task["status"] for task in result["task_results"]] == ["succeeded", "succeeded"]
    assert result["task_error_count"] == 0


def test_a_held_input_still_blocks_its_own_tasks_model_call(monkeypatch):
    states = {"doc-b": "available"}
    model_calls = []

    def read_document(document_id, user_id, group_id=None, public_workspace_id=None, **kwargs):
        if states[document_id] == "held":
            raise DocumentHeldError()
        return {"id": document_id, "user_id": user_id, "version": 1}

    monkeypatch.setattr(screening_access, "_read_authorized_document", read_document)

    def dispatch(workflow, *args, **kwargs):
        if workflow["active_task"]["id"] == "explain":
            screening_access.assert_document_available("doc-b", user_id="owner")
            # Held between this task's input read and its model call.
            states["doc-b"] = "held"
            screening_access.assert_current_request_sources_available("owner")
            model_calls.append("explain")
        return {"reply": "Answer."}

    helpers, _ = load_runner_helpers(dispatch)
    with Flask("model-fence-held").test_request_context("/"):
        result = helpers["_execute_workflow_task_sequence"](fenced_workflow(), {}, "conversation-1", "run-1", None, {})
    assert [task["status"] for task in result["task_results"]] == ["succeeded", "failed"]
    assert model_calls == []


# --- Group results stay limited to group members -----------------------------------------


@pytest.fixture
def group_history_api(monkeypatch, changes):
    workflow, store, _, _, _ = repeat_runtime(monkeypatch, definition=analysis_flow())
    flow, _ = run_analysis_flow(workflow, store, changes)
    membership = {"member": True}

    def group_scope(user_id):
        if not membership["member"]:
            raise PermissionError("Not a member of this group.")
        return "group-one", {}

    namespace = {
        "get_current_user_id": lambda: "member", "jsonify": jsonify, "request": request, "logging": logging,
        "get_personal_workflow": lambda user, key: None, "get_personal_workflow_run": lambda user, key: None,
        "get_group_workflow": lambda group, key: workflow if key == workflow["id"] else None,
        "get_group_workflow_run": lambda group, run: {"id": run, "workflow_id": workflow["id"]} if run == "run" else None,
        "_resolve_group_workflow_request_group": group_scope,
        "workflow_execution_history": workflow_execution_history,
        "workflow_execution_result_page": workflow_execution_result_page,
        "workflow_execution_records_page": workflow_execution_records_page,
        "workflow_execution_provenance_page": workflow_execution_provenance_page,
        "workflow_loop_items_page": workflow_loop_items_page,
        "WorkflowRuntimeConflict": WorkflowRuntimeConflict, "RuntimeUnavailable": RuntimeUnavailable,
        "WorkflowResultStorageUnavailableError": WorkflowResultStorageUnavailableError,
        "WorkflowRecordPageTooLarge": WorkflowRecordPageTooLarge,
        "AnalysisResultUnavailable": AnalysisResultUnavailable,
        "AzureError": AzureError, "CosmosResourceNotFoundError": CosmosResourceNotFoundError,
        "log_event": lambda *args, **kwargs: None,
    }
    function = next(node for node in ast.parse(ROUTES.read_text(encoding="utf-8")).body
                    if isinstance(node, ast.FunctionDef) and node.name == "_workflow_execution_history_response")
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(ROUTES), "exec"), namespace)
    app = Flask("group-results")

    def inspect(execution_id, representation):
        return namespace["_workflow_execution_history_response"](
            "workflow", "run", group=True, execution_id=execution_id or None,
            attempt=1 if representation != "history" else None,
            representation=representation if representation in {"records", "provenance"} else None,
        )

    app.add_url_rule("/group/<execution_id>/<representation>", endpoint="inspect", view_func=inspect)
    return app.test_client(), workflow, flow, membership


def test_group_results_stay_limited_to_group_members_whatever_happened_to_sources(group_history_api, changes):
    client, workflow, _, membership = group_history_api
    analyze_id = workflow_execution_id(workflow, "run", "analyze-node")
    changes.state = "deleted"
    records = client.get(f"/group/{analyze_id}/records?group_id=group-one")
    assert records.status_code == 200 and len(records.json["records"]) == 2
    membership["member"] = False
    denied = client.get(f"/group/{analyze_id}/records?group_id=group-one")
    assert denied.status_code == 403 and "records" not in denied.json
    assert "source" not in denied.json["error"].lower()


def test_an_integrity_failure_in_history_is_unverifiable_not_a_source_denial(group_history_api, monkeypatch):
    client, workflow, _, _ = group_history_api
    analyze_id = workflow_execution_id(workflow, "run", "analyze-node")

    def forged(*args, **kwargs):
        raise AnalysisResultUnavailable("analysis_lineage_invalid")

    monkeypatch.setattr("functions_workflow_loop_history.open_workflow_record_input", forged)
    response = client.get(f"/group/{analyze_id}/records?group_id=group-one")
    assert response.status_code == 409 and "records" not in response.json
    assert "source" not in response.json["error"].lower()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
