# test_workflow_loop_native_analysis.py
"""
Functional regression for current-document native Analyze in serial loops.
Version: 0.261.119
Implemented in: 0.261.117

Production task dispatch, native checkpoint adaptation, result transport and
Collect execute over fictional native/source boundaries. No document is uploaded,
published or indexed, and no live provider or workspace is accessed.
"""

import copy
import sys

import pytest

from test_analyze_native_saved_integration import native, native_run  # noqa: F401
from test_analyze_backend_saved_integration import saved
from test_workflow_for_each_execution import loop_definition, loop_runtime
from test_workflow_result_store import FakeBlobService
from test_workflow_task_result_handoff import build_inventory_run
from functions_analysis_access import AnalysisResultUnavailable, authorize_analysis_sources
from functions_document_analysis_checkpoints import analysis_checkpoints_for_workflow
from functions_workflow_execution import current_workflow_execution, workflow_execution_scope
from functions_workflow_node_results import open_workflow_record_input
from functions_workflow_loop_inputs import WorkflowLoopInputError
from functions_workflow_results import authorize_workflow_task_result_read, persist_workflow_task_result
from functions_workflow_result_store import WorkflowResultStore
from functions_workflow_runtime_store import WorkflowRuntimeLease
from functions_workflow_structured_execution import StructuredWorkflowExecution


@pytest.fixture
def native_loop_flow(native_run, monkeypatch, request):
    options = getattr(request, "param", None) or {}
    definition = loop_definition()
    definition["tasks"] = definition["tasks"][1:]
    definition["tasks"][0]["document_action"] = {
        "type": "analyze", "target_mode": "current_item", "loop_id": "each", "analysis_mode": "combined",
    }
    definition["flow"]["nodes"] = definition["flow"]["nodes"][1:]
    loop = definition["flow"]["nodes"][0]
    loop["inputs"] = []
    identifiers = ["native-source-a", "native-source-b"]
    loop["iterable"] = {
        "kind": "documents", "documents": [{"document_id": key, "scope_type": "personal"} for key in identifiers],
    }
    if options.get("partial"):
        loop["body"]["nodes"][0]["run_when"] = {
            "op": "lt", "left": {"input": "item", "path": "/index"}, "right": {"literal": 1},
        }
        loop["body"]["outputs"][0]["required"] = False
        definition["flow"]["nodes"][1]["output_contract"].update(allow_partial=True, require_complete_coverage=False)
        definition["flow"]["outputs"][0]["allow_partial"] = True
    if options.get("publication") is not None:
        publish_binding = {
            "name": "deliverable",
            "source": {"kind": "node_output", "node_id": "collect", "output": "records", "scope": "current"},
            "required": True, "expected_kind": "records",
            **({"allow_partial": options["accept_partial"]} if "accept_partial" in options else {}),
        }
        if options.get("join"):
            definition["flow"]["nodes"].append({
                "id": "choose", "kind": "if", "inputs": [],
                "condition": {"op": "eq", "left": {"literal": True}, "right": {"literal": True}},
                "then": {"id": "then-region", "nodes": []},
                "else": {"id": "else-region", "nodes": []},
                "join": {"id": "selected", "exports": [{
                    "name": "deliverable",
                    "then": {"node_id": "collect", "output": "records"},
                    "else": {"node_id": "collect", "output": "records"},
                    "required": True, "expected_kind": "records",
                }]},
            })
            publish_binding["source"].update(node_id="selected", output="deliverable")
        definition["tasks"].append({
            "id": "publish", "type": "instructions", "name": "Publish records", "instructions": "Publish exact records.",
            "runner": {"type": "inherit"}, "document_action": {"type": "none"},
            "inputs": [publish_binding], "output_contract": {"kind": "json"},
            "publication": copy.deepcopy(options["publication"]),
        })
        definition["flow"]["nodes"].append({"id": "publish-node", "kind": "task", "task_id": "publish"})
    workflow, store, container, _ = loop_runtime(monkeypatch, definition=definition)
    if options.get("storage") == "blob":
        blobs = FakeBlobService()
        configured = lambda *args, **kwargs: WorkflowResultStore(container, blobs, "private-workflow-results")
        monkeypatch.setattr("functions_workflow_result_store._configured_store", configured)
        monkeypatch.setattr("functions_workflow_result_store._configured_result_store", configured)
    sources = {
        key: {
            **copy.deepcopy(native_run.source), "document_id": key, "scope_id": "owner",
            "file_name": f"{key}.csv", "source_revision": f"revision-{key}",
        } for key in identifiers
    }
    allowed = {key: True for key in identifiers}

    def source_resolver(ids, **kwargs):
        assert kwargs["user_id"] == "owner" and all(key in sources for key in ids)
        return [{**sources[key], "authorization_status": "authorized" if allowed[key] else "unresolved"} for key in ids]

    def source_authorizer(user, values, **kwargs):
        return authorize_analysis_sources(user, values, **{**kwargs, "resolver": source_resolver})

    def documents(bound_workflow, iterable, **kwargs):
        assert bound_workflow["id"] == workflow["id"] and kwargs["actor_user_id"] == "owner"
        for key in identifiers:
            source = sources[key]
            yield {
                "document": {"document_id": key, "file_name": source["file_name"], "scope_type": "personal", "scope_id": "owner"},
                "source": {name: source[name] for name in ("document_id", "scope", "scope_id", "source_version", "source_revision")},
                "availability": {"document_id": key, "scope_type": "personal", "scope_id": "owner"},
            }
        kwargs["capture_metadata"].update({"complete": True, "count": len(identifiers), "count_exact": True})

    def reauthorize(bound_workflow, item, *, actor_user_id, **kwargs):
        assert actor_user_id == "owner"
        key = item["document"]["document_id"]
        if not allowed[key]:
            raise WorkflowLoopInputError("The selected source is no longer available.")
        assert item["source"]["source_revision"] == sources[key]["source_revision"]
        return item

    monkeypatch.setattr("functions_workflow_loop_inputs.iter_workflow_loop_documents", documents)
    monkeypatch.setattr("functions_workflow_loop_inputs.reauthorize_workflow_loop_document", reauthorize)
    monkeypatch.setattr("functions_workflow_node_results.authorize_analysis_sources", source_authorizer)
    native_module = sys.modules["functions_tabular_generated_exports"]

    def read_native(user_id, run_id):
        assert user_id == "owner" and run_id in identifiers
        source = sources[run_id]
        return {
            **copy.deepcopy(native_run.run), "id": run_id, "user_id": "owner",
            "source_file_name": source["file_name"], "source_descriptor": {"source": "workspace", "document_id": run_id},
            "final_artifact": {"artifact_message_id": f"artifact-{run_id}", "output_format": "json"},
        }

    monkeypatch.setattr(native_module, "_read_run", read_native)
    monkeypatch.setitem(sys.modules, "functions_saved_analysis", saved)
    runner, _, _, _, _, _ = build_inventory_run()
    calls, bindings = [], []

    def prepare(bound_workflow, run_id, task_id, actor_user_id, settings):
        execution = current_workflow_execution()
        checkpoints = analysis_checkpoints_for_workflow(
            bound_workflow, run_id, task_id, user_id=actor_user_id, authorize=execution.check,
            settings=settings, source_authorizer=source_authorizer, store=WorkflowResultStore(container),
            **execution.selectors(),
        )
        checkpoints.prepare()
        return checkpoints

    def dispatch(execution_workflow, *args, **kwargs):
        action = execution_workflow["document_action"]
        assert action["target_mode"] == "selected" and len(action["document_ids"]) == 1
        key = action["document_ids"][0]
        producer = execution_workflow["_analysis_producer"]
        calls.append((key, copy.deepcopy(producer)))

        def bind(user, conversation, native_id, artifacts, bound_producer):
            assert native_id == key and user == "owner"
            metadata = saved.analysis_artifact_metadata(bound_producer)
            bindings.append(metadata["analysis_producer"])

        result = native.adapt_native_analysis_result(
            user_id="owner", conversation_id="conversation-1", source=sources[key],
            generated_outputs=[{"run_id": key, "status": "completed"}],
            source_resolver=source_resolver, analysis_producer=producer, bind_artifacts=bind,
        )
        return {"reply": result["reply"], "analysis_result": result}

    runner.update(
        _execute_workflow_dispatch=dispatch, _prepare_workflow_analysis_checkpoints=prepare,
        persist_workflow_task_result=persist_workflow_task_result,
        authorize_workflow_task_result_read=lambda *args, **kwargs: authorize_workflow_task_result_read(
            *args, source_resolver=source_resolver, **kwargs,
        ),
    )

    def execute(*, before_publication=None):
        original_publication = runner["_execute_workflow_analysis_publication"]

        def publication_dispatch(*args, **kwargs):
            if before_publication:
                before_publication()
            return original_publication(*args, **kwargs)

        runner["_execute_workflow_analysis_publication"] = publication_dispatch
        with WorkflowRuntimeLease(store, owner_id="native-loop-worker") as lease:
            execution = StructuredWorkflowExecution(store, lease, workflow, "run")
            try:
                with workflow_execution_scope(execution):
                    return runner["_execute_workflow_task_sequence"](
                        workflow, {}, "conversation-1", "run", None, {}, actor_user_id="owner",
                    )
            finally:
                runner["_execute_workflow_analysis_publication"] = original_publication

    return {
        "execute": execute, "workflow": workflow, "store": store, "container": container,
        "calls": calls, "bindings": bindings, "identifiers": identifiers, "allowed": allowed,
        "source_resolver": source_resolver, "native_run": native_run, "options": options,
    }


def test_each_document_uses_its_exact_native_producer_and_collects_complete_results(native_loop_flow):
    fixture = native_loop_flow
    execute, workflow, calls, bindings, identifiers, allowed, source_resolver, native_run = (
        fixture[key] for key in (
            "execute", "workflow", "calls", "bindings", "identifiers", "allowed", "source_resolver", "native_run",
        )
    )

    result = execute()
    assert result["workflow_outcome"] == {"status": "completed", "success": True}
    assert [key for key, _ in calls] == identifiers
    assert [producer["iteration_path"][0]["index"] for _, producer in calls] == [0, 1]
    assert len({producer["execution_id"] for _, producer in calls}) == 2
    assert all(producer["task_id"] == "body" and producer["attempt"] == 1 for producer in bindings)
    assert len(native_run.reads) == 6
    receipt = result["workflow_outputs"][0]
    reader = open_workflow_record_input(
        workflow, "run", receipt["producer"], receipt["result_ref"], output_name="records", source_resolver=source_resolver,
    )
    rows = list(reader.iter_records())
    assert len(rows) == 300
    assert {record["document_id"] for record in rows[:150]} == {identifiers[0]}
    assert {record["document_id"] for record in rows[150:]} == {identifiers[1]}
    assert [record["values"] for record in rows[:150]] == native_run.rows
    assert reader.manifest["analysis_origin"] is False
    execute()
    assert len(calls) == 2 and len(native_run.reads) == 6
    allowed[identifiers[1]] = False
    with pytest.raises(AnalysisResultUnavailable):
        reader.read_records(offset=0, limit=1)
