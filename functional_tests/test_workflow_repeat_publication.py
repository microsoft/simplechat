# test_workflow_repeat_publication.py
"""
Functional tests for mixed Repeat native Analyze and exact saved-output publication.
Version: 0.261.120
Implemented in: 0.261.120

The production task dispatcher, native checkpoints, shared JSON renderer and sole
publication ledger use existing closed fictional source, Blob and Cosmos fixtures.
"""

from copy import deepcopy
import hashlib
import json

import pytest

import test_workflow_loop_native_analysis as native_loops
from test_analyze_native_saved_integration import native_run  # noqa: F401
from test_analysis_artifact_publication import publication, normalizers  # noqa: F401
from test_workflow_saved_output_artifacts import artifact_services  # noqa: F401
from functions_analysis_access import AnalysisResultUnavailable
from functions_workflow_node_results import open_workflow_record_input


def repeat_node(initial_node, body_nodes, output_node, contract):
    return {
        "id": "repeat", "kind": "repeat_until", "max_iterations": 1,
        "state": [{
            "name": "findings", "initial": {"kind": "node_output", "node_id": initial_node, "output": "records", "scope": "current"},
            "next": "findings", "output_contract": deepcopy(contract),
        }],
        "body": {"id": "repeat-body", "nodes": body_nodes, "outputs": [{
            "name": "findings", "source": {"kind": "node_output", "node_id": output_node, "output": "records", "scope": "current"},
            "required": True, "expected_kind": "records", "allow_partial": False,
        }]},
        "until": {"op": "eq", "left": {"literal": True}, "right": {"literal": True}},
        "exports": [{"name": "findings", "output": "findings"}],
    }


def redirect_collect(value):
    if isinstance(value, dict):
        if value.get("node_id") == "collect":
            value.update(node_id="repeat", output="findings")
        for child in value.values():
            redirect_collect(child)
    elif isinstance(value, list):
        for child in value:
            redirect_collect(child)


@pytest.fixture
def native_repeat_flow(native_run, monkeypatch, request):
    options = getattr(request, "param", None) or {}
    original = native_loops.loop_runtime

    def runtime(patch, *, definition):
        definition = deepcopy(definition)
        each, collect, *following = definition["flow"]["nodes"]
        body_task = next(task for task in definition["tasks"] if task["id"] == "body")
        contract = body_task["output_contract"]
        if options.get("nesting") == "repeat_in_each":
            refine = deepcopy(body_task)
            refine.update(id="refine", name="Refine fictional document")
            definition["tasks"].append(refine)
            boundary = repeat_node(
                "body-node", [{"id": "refine-node", "kind": "task", "task_id": "refine"}], "refine-node", contract,
            )
            each["body"]["nodes"].append(boundary)
            each["body"]["outputs"][0]["source"].update(node_id="repeat", output="findings")
        else:
            seed_each, seed_collect, seed_task = deepcopy(each), deepcopy(collect), deepcopy(body_task)
            seed_task.update(id="seed-body", name="Seed fictional document")
            seed_task["document_action"]["loop_id"] = "seed-each"
            for binding in seed_task["inputs"]:
                if binding["source"]["kind"] == "loop_item":
                    binding["source"]["loop_id"] = "seed-each"
            seed_each["id"] = "seed-each"
            seed_each["body"].update(id="seed-body-region", nodes=[
                {"id": "seed-body-node", "kind": "task", "task_id": "seed-body"},
            ])
            seed_each["body"]["outputs"][0]["source"]["node_id"] = "seed-body-node"
            seed_collect["id"] = "seed-collect"
            seed_collect["source"]["loop_id"] = "seed-each"
            definition["tasks"].append(seed_task)
            boundary = repeat_node("seed-collect", [each, collect], "collect", contract)
            redirect_collect(following)
            redirect_collect(definition["flow"]["outputs"])
            for task in definition["tasks"]:
                if task["id"] != "body":
                    redirect_collect(task.get("inputs", []))
            definition["flow"]["nodes"] = [seed_each, seed_collect, boundary, *following]
        return original(patch, definition=definition)

    monkeypatch.setattr(native_loops, "loop_runtime", runtime)
    return native_loops.native_loop_flow.__wrapped__(native_run, monkeypatch, request)


@pytest.mark.parametrize("native_repeat_flow", [
    {"nesting": nesting, "storage": storage}
    for nesting in ("repeat_in_each", "each_in_repeat") for storage in ("cosmos", "blob")
], indirect=True)
def test_native_analyze_keeps_exact_mixed_producers_and_original_records(native_repeat_flow):
    fixture = native_repeat_flow
    completed = fixture["execute"]()
    assert completed["workflow_outcome"] == {"status": "completed", "success": True}
    assert len(fixture["calls"]) == 4 and len({producer["execution_id"] for _, producer in fixture["calls"]}) == 4
    mixed = [producer for _, producer in fixture["calls"] if len(producer["iteration_path"]) == 2]
    assert len(mixed) == 2
    assert all(any(frame.get("iteration") == 0 for frame in producer["iteration_path"]) for producer in mixed)
    assert all(any("item_id" in frame for frame in producer["iteration_path"]) for producer in mixed)
    receipt = completed["workflow_outputs"][0]
    reader = open_workflow_record_input(
        fixture["workflow"], "run", receipt["producer"], receipt["result_ref"],
        output_name=receipt["output_name"], source_resolver=fixture["source_resolver"],
    )
    rows = list(reader.iter_records())
    assert len(rows) == 300 and [row["values"] for row in rows[:150]] == fixture["native_run"].rows
    before = len(fixture["native_run"].reads)
    fixture["execute"]()
    assert len(fixture["calls"]) == 4 and len(fixture["native_run"].reads) == before
    fixture["allowed"]["native-source-a"] = False
    with pytest.raises(AnalysisResultUnavailable):
        reader.read_records(offset=0, limit=1)


@pytest.mark.parametrize("native_repeat_flow", [
    {"storage": storage, "join": join, "publication": {
        "source_kind": "saved_output", "artifact_format": "json", "workspace_scope": "personal", "completion_policy": "submitted",
    }}
    for storage in ("cosmos", "blob") for join in (False, True)
], indirect=True)
def test_repeat_final_records_use_unchanged_shared_export_and_destination_ledger(artifact_services, native_repeat_flow):
    fixture, services = native_repeat_flow, artifact_services
    services.bind(fixture["workflow"], fixture["store"])

    def interrupt():
        raise SystemExit("Fictional restart after Repeat completion, before publication.")

    with pytest.raises(SystemExit):
        fixture["execute"](before_publication=interrupt)
    assert len(fixture["calls"]) == 4 and services.blobs.writes == 0
    completed = fixture["execute"]()
    assert completed["workflow_outcome"] == {"status": "completed", "success": True}
    assert completed["publication"]["state"] == "submitted" and completed["publication"]["policy_satisfied"]
    card = completed["generated_tabular_outputs"][-1]
    artifact = services.publication.messages.records[card["artifact_message_id"]]
    source = artifact["metadata"]["generated_artifact_source"]
    assert source["producer"]["node_id"] == ("selected" if fixture["options"]["join"] else "repeat")
    assert "task_id" not in source["producer"]
    content = services.blobs.data[(artifact["blob_container"], artifact["blob_path"])]
    rows = json.loads(content)
    assert len(rows) == 300 and [row["values"] for row in rows[:150]] == fixture["native_run"].rows
    assert artifact["metadata"]["generated_artifact_content_sha256"] == hashlib.sha256(content).hexdigest()
    assert services.publication.calls["queue"][0]["file_content_bytes"] == content
    before = deepcopy(services.publication.calls)
    assert fixture["execute"]()["publication"] == completed["publication"]
    assert services.publication.calls["create"] == before["create"] and services.publication.calls["queue"] == before["queue"]
    assert services.blobs.writes == 1 and len(fixture["calls"]) == 4
    fixture["allowed"]["native-source-b"] = False
    with pytest.raises((PermissionError, AnalysisResultUnavailable, ValueError)):
        services.download("owner", "conversation-1", card["artifact_message_id"])


@pytest.mark.parametrize("native_repeat_flow", [
    {"storage": storage, "publication": {
        "source_kind": "saved_output", "artifact_format": "json", "workspace_scope": "personal", "completion_policy": "submitted",
    }} for storage in ("cosmos", "blob")
], indirect=True)
def test_repeat_restart_after_destination_submission_reuses_the_existing_ledger(
    artifact_services, native_repeat_flow, monkeypatch,
):
    fixture, services = native_repeat_flow, artifact_services
    services.bind(fixture["workflow"], fixture["store"])
    original = services.publication.module.publish_generated_chat_artifact_for_user
    interrupted = []

    def submit_then_interrupt(*args, **kwargs):
        submitted = original(*args, **kwargs)
        if not interrupted:
            interrupted.append(True)
            raise SystemExit("Fictional restart after the sole destination ledger committed.")
        return submitted

    monkeypatch.setattr(services.publication.module, "publish_generated_chat_artifact_for_user", submit_then_interrupt)
    with pytest.raises(SystemExit):
        fixture["execute"]()
    assert len(services.publication.calls["create"]) == len(services.publication.calls["queue"]) == 1
    completed = fixture["execute"]()
    assert completed["workflow_outcome"] == {"status": "completed", "success": True}
    assert completed["publication"]["state"] == "submitted" and completed["publication"]["policy_satisfied"]
    assert len(services.publication.calls["create"]) == len(services.publication.calls["queue"]) == 1
    assert len(fixture["calls"]) == 4 and services.blobs.writes == 1
