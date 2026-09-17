# test_analyze_workflow_publication_integration.py
"""
Analyze -> save -> reload -> explain -> optional publish in one workflow run.
Version: 0.261.109
Implemented in: 0.261.109

The native adapter, section contract, task sequence, model consumer, artifact
authorization and publication receipt service are production code. Only native
run/blob, Cosmos, queue, selected-model and source-access I/O are doubled.
"""

from copy import deepcopy
import hashlib
import json
import sys
from types import SimpleNamespace

import pytest

from test_analysis_artifact_publication import publication
from test_analyze_backend_saved_integration import budget, load_functions, saved
from test_analyze_native_saved_integration import adapt, native_run
from test_support.app_stubs import import_app_module
from test_support.document_analysis import USER_ID
from test_workflow_result_contract import SerializedSections
from test_workflow_task_sequence import load_runner_helpers


results = import_app_module("functions_workflow_results")


@pytest.fixture
def sequence(native_run, publication, monkeypatch):
    native_fixture, publishing = native_run, publication
    source_result = adapt(native_fixture)
    producer = {"kind": "workflow", "workflow_id": "workflow-1", "run_id": "run-1", "task_id": "analyze"}
    artifact = deepcopy(publishing.artifact)
    artifact["metadata"].update(saved.analysis_artifact_metadata(producer))
    publishing.state["content"] = source_result["analysis_reply"].encode("utf-8")
    artifact["metadata"]["generated_artifact_content_sha256"] = hashlib.sha256(publishing.state["content"]).hexdigest()
    publishing.messages.put(artifact)
    publishing.conversations.put({"id": "conversation-1", "user_id": USER_ID})
    publishing.state["parents"] = []
    model_calls = []
    loaded = []
    phase = {"value": "analysis"}
    store = SerializedSections()

    def load(workflow, run_id, task_id, reference):
        value = store.load(workflow, run_id, task_id, reference)
        loaded.append((phase["value"], value.get("output_name")))
        return value

    def authorized(workflow, run_id, task_id, reference, **kwargs):
        return results.authorize_workflow_task_result_read(
            workflow, run_id, task_id, reference, load_result=load,
            source_resolver=native_fixture.resolve, **kwargs,
        )

    def completion(**kwargs):
        model_calls.append(deepcopy(kwargs))
        payload = json.loads(kwargs["messages"][-1]["content"].split("[Saved Analyze result — complete data]\n", 1)[1])
        assert [record["values"] for record in payload["records"]] == native_fixture.rows
        assert payload["original_sources_reanalyzed"] is False
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="The complete saved inventory has consistent amounts."))],
            usage=None,
        )

    model = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=completion)))
    monkeypatch.setattr(budget, "resolve_model_token_limits", lambda *args, **kwargs: {
        "context_window_tokens": 1000000, "max_input_tokens": 1000000, "max_output_tokens": 2048,
        "tokenizer": None, "source": "configured", "model_id": "task-selected-model", "status": "known",
    })

    def dispatch(workflow, settings, conversation_id, run_id, thought_tracker, url_access_context, **kwargs):
        if workflow["active_task"]["id"] == "analyze":
            return {
                "reply": source_result["reply"], "analysis_result": deepcopy(source_result),
                "generated_analysis_artifacts": [{
                    "artifact_message_id": "artifact-1", "conversation_id": conversation_id,
                    "output_format": "md", "file_name": "accepted.md",
                }],
            }
        phase["value"] = "report"
        return runner["_execute_raw_model_workflow"](workflow, settings, run_id=run_id)

    runner, run_items = load_runner_helpers(dispatch)
    runner.update({
        "SavedAnalysisInput": saved.SavedAnalysisInput,
        "explain_saved_analysis": saved.explain_saved_analysis,
        "authorize_workflow_task_result_read": authorized,
        "persist_workflow_task_result": lambda envelope, **kwargs: results.persist_workflow_task_result(
            envelope, save_result=store.save, **kwargs,
        ),
        "load_workflow_task_input": lambda workflow, run_id, task_id, reference, **kwargs: results.load_workflow_task_input(
            workflow, run_id, task_id, reference, load_result=load, source_resolver=native_fixture.resolve, **kwargs,
        ),
        "_build_workflow_chat_messages": lambda prompt, **kwargs: [{"role": "user", "content": prompt}],
        "_resolve_model_workflow_client": lambda *args: (
            budget.WorkflowModelClient(model, {"id": "task-selected-model"}, "aoai"), "chosen-deployment", "aoai",
        ),
        "_is_workflow_run_cancellation_requested": lambda *args: False,
    })
    load_functions("functions_workflow_runner.py", {
        "_execute_raw_model_workflow", "_create_token_usage_aggregate", "_accumulate_token_usage",
        "_accumulate_token_usage_summary", "_extract_token_usage", "_finalize_token_usage",
        "_coerce_token_count", "_extract_message_text", "_execute_workflow_analysis_publication",
    }, runner)
    publish_task = runner["_execute_workflow_analysis_publication"]

    def dispatch_publication(*args, **kwargs):
        phase["value"] = "publication"
        return publish_task(*args, **kwargs)

    runner["_execute_workflow_analysis_publication"] = dispatch_publication
    workflow = {
        "id": "workflow-1", "user_id": USER_ID, "runner_type": "model", "model_id": "task-selected-model",
        "tasks": [
            {"id": "analyze", "name": "Analyze", "instructions": "Analyze the inventory."},
            {"id": "explain", "name": "Explain", "instructions": "Explain the previous saved inventory."},
            {"id": "publish", "name": "Publish", "instructions": "Publish the saved Markdown artifact.",
             "publication": {"artifact_format": "md", "workspace_scope": "personal"}},
        ],
    }
    monkeypatch.setitem(sys.modules, "functions_artifact_publication", publishing.module)
    monkeypatch.setitem(sys.modules, "functions_saved_analysis", saved)
    monkeypatch.setitem(sys.modules, "functions_workflow_runner", SimpleNamespace(
        _workflow_task_run_item_id=runner["_workflow_task_run_item_id"],
    ))
    personal = sys.modules["functions_personal_workflows"]
    monkeypatch.setattr(personal, "get_personal_workflow", lambda user, key: deepcopy(workflow), raising=False)
    monkeypatch.setattr(personal, "get_personal_workflow_run", lambda user, key: {
        "id": "run-1", "workflow_id": workflow["id"], "conversation_id": "conversation-1",
    }, raising=False)
    monkeypatch.setattr(personal, "get_personal_workflow_run_item", lambda run, key: next((
        deepcopy(item) for item in reversed(run_items) if item["id"] == key
    ), None), raising=False)
    monkeypatch.setitem(sys.modules, "functions_group_workflows", SimpleNamespace(
        get_group_workflow=lambda *args: None, get_group_workflow_run=lambda *args: None,
        get_group_workflow_run_item=lambda *args: None,
    ))
    monkeypatch.setattr(saved, "authorize_workflow_task_result_read", authorized)
    monkeypatch.setattr(publishing.module, "authorize_analysis_artifact", saved.authorize_analysis_artifact)
    return SimpleNamespace(
        runner=runner, workflow=workflow, native=native_fixture, publishing=publishing,
        model_calls=model_calls, loaded=loaded, store=store, run_items=run_items,
    )


def execute(fixture):
    return fixture.runner["_execute_workflow_task_sequence"](
        fixture.workflow, {}, "conversation-1", "run-1", None, {},
    )


def test_publish_uses_real_prior_manifest_before_final_assistant_and_skips_model_budget(sequence):
    fixture = sequence
    result = execute(fixture)
    assert result["task_error_count"] == 0
    assert result["publication"]["state"] == "queued"
    assert len(fixture.model_calls) == 1
    assert fixture.publishing.state["parents"] == []
    assert len(fixture.publishing.calls["create"]) == len(fixture.publishing.calls["queue"]) == 1
    assert fixture.publishing.calls["queue"][0]["file_content_bytes"] == fixture.publishing.state["content"]
    assert all(output is None for phase, output in fixture.loaded if phase == "publication")
    task = result["task_results"][-1]
    assert task["consumed_inputs"][0]["producer"]["task_id"] == "analyze"
    repeated, _ = fixture.runner["_execute_workflow_analysis_publication"](
        fixture.workflow, "run-1", fixture.workflow["tasks"][-1],
        result["task_results"][1]["task_id"], result["task_results"][1]["workflow_result"]["result_ref"],
    )
    assert repeated["publication"] == result["publication"]
    assert len(fixture.publishing.calls["create"]) == 1


def test_absent_publication_request_has_zero_workspace_side_effects(sequence):
    sequence.workflow["tasks"].pop()
    result = execute(sequence)
    assert result["task_error_count"] == 0
    assert len(sequence.model_calls) == 1
    assert all(not values for values in sequence.publishing.calls.values())


def test_shared_destination_approval_remains_pending(sequence):
    sequence.workflow["tasks"][-1]["publication"] = {
        "artifact_format": "md", "workspace_scope": "group", "group_id": "fixed-group",
    }
    result = execute(sequence)
    assert result["publication"]["state"] == "pending_approval"
    assert result["task_results"][-1]["workflow_result"]["output_state"] == "pending"
    assert sequence.publishing.calls["queue"] == []
    assert len(sequence.model_calls) == 1


def test_unknown_publication_acknowledgement_is_explicit_and_not_recreated(sequence):
    sequence.publishing.state["failure"] = "queue_after"
    result = execute(sequence)
    assert result["publication"]["state"] == "uncertain"
    assert result["task_results"][-1]["workflow_result"]["output_state"] == "blocked"
    assert len(sequence.publishing.calls["create"]) == 1


def test_native_source_revocation_blocks_saved_report_and_publication(sequence):
    sequence.native.state["allowed"] = False
    with pytest.raises(RuntimeError, match="input could not be resolved"):
        execute(sequence)
    assert sequence.model_calls == []
    assert all(not values for values in sequence.publishing.calls.values())


def test_report_of_a_report_reloads_original_records_instead_of_using_summary_as_data(sequence):
    sequence.workflow["tasks"].insert(2, {
        "id": "explain-again", "name": "Explain again", "instructions": "Explain the saved inventory again.",
    })
    result = execute(sequence)
    assert result["publication"]["state"] == "queued"
    assert len(sequence.model_calls) == 2
    assert len(sequence.native.reads) == 3
    assert result["task_results"][2]["consumed_inputs"][0]["producer"]["task_id"] == "explain"


def test_format_then_publish_a_selected_existing_format_uses_zero_model_calls(sequence):
    fixture = sequence
    original_dispatch = fixture.runner["_execute_workflow_dispatch"]
    load_functions("functions_workflow_runner.py", {"_execute_workflow_dispatch"}, fixture.runner)
    production_dispatch = fixture.runner["_execute_workflow_dispatch"]

    def upload(**kwargs):
        artifact = deepcopy(fixture.publishing.artifact)
        artifact["id"] = "formatted-json"
        content = kwargs["file_content"]
        fixture.publishing.state["content"] = content.encode("utf-8") if isinstance(content, str) else content
        artifact["metadata"].update({
            **saved.analysis_artifact_metadata(kwargs["analysis_producer"]),
            "generated_artifact_output_format": kwargs["output_format"],
            "generated_artifact_content_sha256": hashlib.sha256(fixture.publishing.state["content"]).hexdigest(),
        })
        fixture.publishing.messages.put(artifact)
        return {"message": {"id": artifact["id"], "file_name": kwargs["file_name"]}}

    fixture.runner.update({
        "saved_analysis_format_request": saved.saved_analysis_format_request,
        "format_saved_analysis": lambda inputs, output_format, **kwargs: saved.format_saved_analysis(
            inputs, output_format, upload_artifact=upload, **kwargs,
        ),
        "_execute_workflow_dispatch": lambda workflow, *args, **kwargs: (
            production_dispatch(workflow, *args, **kwargs) if workflow["active_task"]["id"] == "format"
            else original_dispatch(workflow, *args, **kwargs)
        ),
    })
    fixture.workflow["tasks"][1] = {
        "id": "format", "name": "Format", "instructions": "Export this saved result as JSON.",
    }
    fixture.workflow["tasks"][-1]["publication"]["artifact_format"] = "json"
    result = execute(fixture)
    assert result["publication"]["state"] == "queued"
    assert fixture.model_calls == []
    assert json.loads(fixture.publishing.calls["queue"][0]["file_content_bytes"]) == fixture.native.rows
    assert result["task_results"][1]["workflow_result"]["analysis_origin"] is False
    assert result["task_results"][-1]["consumed_inputs"][0]["producer"]["task_id"] == "format"


def test_large_workflow_report_pages_records_but_publication_only_reads_manifests(sequence, monkeypatch):
    fixture = sequence
    seen = []
    monkeypatch.setattr(budget, "resolve_model_token_limits", lambda *args, **kwargs: {
        "context_window_tokens": 16000, "max_input_tokens": 16000, "max_output_tokens": 2048,
        "tokenizer": None, "source": "configured", "model_id": "small-selected-model", "status": "known",
    })

    def complete(**kwargs):
        fixture.model_calls.append(deepcopy(kwargs))
        data = json.loads(kwargs["messages"][-1]["content"].split("[Saved Analyze result — complete data]\n", 1)[1])
        if "records" in data:
            seen.extend(record["record_id"] for record in data["records"])
            response = {"record_explanations": [{
                "record_ref": record["record_ref"], "text": "The saved amount is 12.3400.",
            } for record in data["records"]]}
        else:
            response = {"conclusions": []}
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(response)))], usage=None)

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=complete)))
    fixture.runner["_resolve_model_workflow_client"] = lambda *args: (
        budget.WorkflowModelClient(client, {"id": "small-selected-model", "responseLength": 2048}, "aoai"),
        "chosen-small-deployment", "aoai",
    )
    result = execute(fixture)
    assert len(seen) == len(set(seen)) == 150
    assert result["publication"]["state"] == "queued"
    assert len(fixture.model_calls) > 1
    assert all(output is None for phase, output in fixture.loaded if phase == "publication")
