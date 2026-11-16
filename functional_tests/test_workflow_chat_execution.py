# test_workflow_chat_execution.py
"""Functional regression tests for workflow-owned chat execution.

Version: 0.261.343
Implemented in: 0.261.343

Exercise admitted-plan reuse, required capabilities, identity isolation and the
real initialized chat runtime with only external storage/provider I/O doubled.
"""

import importlib
import json
import sys
from copy import deepcopy
from contextlib import nullcontext
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))

# Application imports follow the worktree module path setup.
from agent_execution_context import capture_execution_identity, current_workflow_identity
from functions_workflow_chat_execution import (
    WorkflowChatExecutionError, WorkflowChatRuntime, build_workflow_chat_seeds,
    child_execution_id, execute_workflow_chat_task, validate_required_outputs,
    workflow_capability_roles, workflow_chat_identity, workflow_chat_result,
)
from test_orchestration_harness_execution import current_metadata, harness, initialized_application
from test_support.orchestration_revisions import AtomicMemoryContainer


WORKFLOW = {
    "id": "workflow-1", "user_id": "owner", "active_task": {"id": "events"},
    "task_prompt": "Search the web for upcoming Washington, DC events.",
    "runner_type": "model", "document_action": {"type": "none"},
}
CONFIGURATION = {
    "version": 1, "mode": "selected", "required_capabilities": ["web_search"], "visual_requirements": [],
}


class BoundedReadContainer(AtomicMemoryContainer):
    def read_item(self, item, partition_key, **kwargs):
        return super().read_item(item, partition_key)


class ChildRuntime:
    """Domain-level boundary double; no Cosmos response is represented here."""

    def __init__(self):
        self.records = {}
        self.search_calls = 0
        self.plan_calls = 0
        self.pending = False
        self.authorize = Mock()
        self.answer = {
            "id": "answer", "conversation_id": "conversation", "role": "assistant",
            "content": "Sourced upcoming events.", "web_search_citations": [{"url": "https://example.org/events"}],
            "generated_artifacts": [{"output_id": "roundup-file"}],
        }
        self.runtime = WorkflowChatRuntime(
            self.authorize, self.plan, lambda key: deepcopy(self.records.get(key)), self.create,
            self.start, self.advance, lambda _key: self.answer,
        )

    def plan(self, child_id, configuration):
        self.plan_calls += 1
        return {
            "run_id": child_id, "steps": [{"capability_id": "web_search"}],
        }, {}

    def create(self, plan, turn, binding):
        record = {
            "id": plan["run_id"], "conversation_id": "conversation", "user_id": "owner",
            "workflow_execution": binding, "status": "approved", "plan": plan,
        }
        self.records[record["id"]] = record
        return deepcopy(record)

    def finish(self, record):
        record.update(
            status="completed", outcome="completed", message_saved=True, finalization_status="saved",
            assistant_message_id="answer",
        )
        self.records[record["id"]] = deepcopy(record)
        return record

    def start(self, record):
        self.search_calls += 1
        record.update(status="waiting", started_at="2026-10-16T12:00:00Z")
        self.records[record["id"]] = deepcopy(record)
        return record if self.pending else self.finish(record)

    def advance(self, record):
        return self.finish(record)


def execute(runtime, **kwargs):
    return execute_workflow_chat_task(
        deepcopy(WORKFLOW), {"enable_chat_orchestration": True}, conversation_id="conversation",
        run_id="workflow-run", configuration=deepcopy(CONFIGURATION),
        check_cancelled=lambda: None, runtime=runtime.runtime, **kwargs,
    )


def test_required_web_runs_and_saved_child_is_adopted_without_new_search():
    runtime = ChildRuntime()
    first = execute(runtime)
    second = execute(runtime)
    assert runtime.plan_calls == 1 and runtime.search_calls == 1
    assert first == second
    assert first["web_search_citations"] == runtime.answer["web_search_citations"]
    assert first["generated_artifacts"] == runtime.answer["generated_artifacts"]


def test_pending_child_resumes_without_replanning_or_repeating_producer():
    runtime = ChildRuntime()
    runtime.pending = True

    class Suspended(BaseException):
        pass

    def wait(key, references):
        assert key == "task:events"
        assert references[0]["kind"] == "workflow_orchestration"
        raise Suspended()

    with pytest.raises(Suspended):
        execute(runtime, execution=SimpleNamespace(wait_for_output=wait))
    result = execute(runtime)
    assert result["reply"] == "Sourced upcoming events."
    assert runtime.plan_calls == 1 and runtime.search_calls == 1


def test_required_search_cannot_be_replaced_by_model_only_plan():
    runtime = ChildRuntime()
    object.__setattr__(runtime.runtime, "plan", lambda *_args: ({"steps": [{"capability_id": "compose"}]}, {}))
    with pytest.raises(WorkflowChatExecutionError, match="omitted"):
        execute(runtime)
    assert runtime.search_calls == 0 and runtime.records == {}


def test_changed_task_cannot_adopt_another_request():
    runtime = ChildRuntime()
    execute(runtime)
    record = next(iter(runtime.records.values()))
    record["workflow_execution"]["request_digest"] = "forged"
    with pytest.raises(WorkflowChatExecutionError, match="does not match"):
        execute(runtime)
    assert runtime.search_calls == 1


def test_failed_search_is_not_a_success_shaped_result():
    runtime = ChildRuntime()
    execute(runtime)
    record = next(iter(runtime.records.values()))
    record.update(status="failed", outcome="failed")
    with pytest.raises(WorkflowChatExecutionError, match="did not complete"):
        execute(runtime)


def test_identity_is_owner_bound_scoped_and_does_not_restore_arbitrary_roles():
    workflow = {
        **WORKFLOW, "roles": ["Admin"], "url_access_authorized": True,
        "url_access_authorized_by": "someone-else", "url_access_authorized_at": "2026-10-16T00:00:00Z",
        "deep_research_authorized": True, "deep_research_authorized_by": "owner",
        "deep_research_authorized_at": "2026-10-16T00:00:00Z",
    }
    assert workflow_capability_roles(workflow) == ("User", "DeepResearchUser")
    with workflow_chat_identity(workflow, "conversation"):
        identity = capture_execution_identity("owner", "conversation")
        assert identity.roles == ("User", "DeepResearchUser")
        assert current_workflow_identity("other", "conversation") is None
        assert current_workflow_identity("owner", "other") is None
    assert current_workflow_identity("owner", "conversation") is None


def test_task_overrides_are_positive_requirements_and_group_scope_stays_bound():
    seeds = build_workflow_chat_seeds({**WORKFLOW, "group_id": "group-one"}, CONFIGURATION)
    assert seeds["required_capabilities"] == ["web_search"]
    assert seeds["active_group_ids"] == ["group-one"] and seeds["doc_scope"] == "group"
    assert seeds["model"] is None


@pytest.mark.parametrize("kind", ["chart", "diagram"])
def test_selected_visual_requires_an_explicit_deliverable(kind):
    configuration = {"required_capabilities": [], "visual_requirements": [kind]}
    with pytest.raises(WorkflowChatExecutionError):
        validate_required_outputs({"steps": [], "deliverables": []}, configuration)
    validate_required_outputs({
        "steps": [], "deliverables": [{"kind": kind, "requested": "explicit", "status": "planned"}],
    }, configuration)


def test_new_runs_and_structured_iterations_get_different_child_identities():
    assert child_execution_id("run-a", "task-a") != child_execution_id("run-b", "task-a")
    assert child_execution_id("run-a", "iteration-a") != child_execution_id("run-a", "iteration-b")
    assert child_execution_id("run-a", "task-a") == child_execution_id("run-a", "task-a")


def test_real_planner_harness_and_sdk_storage_execute_and_reuse_workflow_child(harness):
    conversation = {**harness.conversation, "workflow_id": "workflow-1", "chat_type": "workflow"}
    harness.conversations.upsert_item(conversation)
    harness.settings["allow_user_workflows"] = True
    raw_plan = {
        "steps": [harness_step()], "final_response": {
            "version": "orchestration-input-binding-v1", "step_id": "answer",
            "output_name": "answer", "existing_result": None,
        },
    }
    harness.replies = [json.dumps(raw_plan), "The scheduled task's actual outcome."]
    workflow = {**WORKFLOW, "task_prompt": "Write the scheduled task outcome."}
    configuration = {"version": 1, "mode": "orchestration", "required_capabilities": [], "visual_requirements": []}
    outcomes = []
    for _index in range(2):
        outcome = execute_workflow_chat_task(
            workflow, harness.settings, conversation_id="conversation-1", run_id="parent-run",
            configuration=configuration, check_cancelled=lambda: None,
        )
        outcomes.append(outcome)
    assert outcomes[0]["reply"] == "The scheduled task's actual outcome."
    assert outcomes[0] == outcomes[1]
    assert len(harness.model_calls) == 2
    saved = harness.run_store.get_orchestration_run(
        child_execution_id("parent-run", "events"), "owner", "conversation-1", strict=True,
    )
    assert saved["workflow_execution"]["workflow_run_id"] == "parent-run"
    assert saved["status"] == "completed" and saved["message_saved"] is True


def harness_step():
    return {
        "step_id": "answer", "capability_id": "compose",
        "arguments": {"instruction": "Write the requested outcome."},
        "outputs": [{"name": "answer", "kind": "markdown-v1"}],
    }


def test_workflow_web_search_uses_real_adapter_and_retains_sources_without_session(
    harness, current_metadata, monkeypatch,
):
    harness.conversations.upsert_item({**harness.conversation, "workflow_id": "workflow-1", "chat_type": "workflow"})
    harness.settings.update({
        "allow_user_workflows": True, "enable_web_search": True,
        "web_search_agent": {"other_settings": {"azure_ai_foundry": {
            "agent_id": "metadata-agent",
            "endpoint": "https://metadata.services.ai.azure.com/api/projects/headless",
            "api_version": "2025-05-01", "authentication_type": "managed_identity",
            "managed_identity_type": "system_assigned",
        }}},
    })
    conversations = BoundedReadContainer("id")
    conversations.create_item({**harness.conversation, "workflow_id": "workflow-1", "chat_type": "workflow"})
    monkeypatch.setattr(harness.config, "cosmos_conversations_container", conversations)
    users = BoundedReadContainer("id")
    users.create_item({"id": "owner", "settings": {}})
    monkeypatch.setattr(harness.config, "cosmos_user_settings_container", users)
    monkeypatch.setattr(harness.config, "SECRET_KEY", "workflow-offline-private-digest-key-32")
    chats = importlib.import_module("route_backend_chats")
    searches = []

    def provider_search(**kwargs):
        configuration = current_metadata.configuration
        settings = kwargs["settings"]["web_search_agent"]["other_settings"]["azure_ai_foundry"]
        definition = configuration.foundry_definition_snapshot(current_metadata.definition)
        overrides = {
            key: definition[key] for key in ("model", "instructions", "temperature", "top_p", "response_format")
        }
        kwargs["invocation_capture"]("web", settings=kwargs["settings"], source={
            "version": configuration.EXTERNAL_ACQUISITION_VERSION,
            "kind": "foundry", "phase": "run",
            "endpoint": settings["endpoint"], "api_version": settings["api_version"],
            "foundry_settings": settings, "definition": definition, "overrides": overrides,
            "run": {
                "id": "provider-run", "thread_id": "provider-thread", "agent_id": definition["id"],
                **{key: value for key, value in definition.items() if key != "id"},
            },
        })
        searches.append(kwargs["web_search_query_text"])
        kwargs["system_messages_for_augmentation"].append({"content": "Upcoming event with a confirmed date."})
        kwargs["web_search_citations_list"].append({
            "url": "https://example.org/events", "title": "Upcoming DC events",
        })
        return True

    # The real orchestration adapter, capture, configuration attestation, retained
    # source provider, checkpoints and answer composition remain in use.
    monkeypatch.setattr(chats, "perform_web_search", provider_search)
    answer = harness_step()
    answer["inputs"] = {"source": {"binding": {
        "version": "orchestration-input-binding-v1", "step_id": "search",
        "output_name": "prepared", "existing_result": None,
    }, "allow_partial": False}}
    harness.replies = [json.dumps({
        "steps": [
            {"step_id": "search", "capability_id": "web_search", "arguments": {"query": "Upcoming DC events"}},
            answer,
        ],
        "final_response": {
            "version": "orchestration-input-binding-v1", "step_id": "answer",
            "output_name": "answer", "existing_result": None,
        },
    }), "Upcoming DC events: [confirmed source](https://example.org/events)."]
    result = execute_workflow_chat_task(
        WORKFLOW, harness.settings, conversation_id="conversation-1", run_id="events-run",
        configuration=CONFIGURATION, check_cancelled=lambda: None,
    )
    assert searches == ["Upcoming DC events"]
    assert "https://example.org/events" in result["reply"]
    saved = harness.run_store.get_orchestration_run(
        child_execution_id("events-run", "events"), "owner", "conversation-1", strict=True,
    )
    task_result = importlib.import_module("functions_orchestration_results").TaskResult.from_dict(
        saved["task_results"]["search"],
    )
    with workflow_chat_identity(WORKFLOW, "conversation-1"):
        services = harness.bootstrap.build_orchestration_services("owner", "conversation-1", settings=harness.settings)
        retained = services.results.open_result(task_result.output("prepared")).read_value()
    assert retained["citations"][0]["url"] == "https://example.org/events"
    assert current_metadata.requests


def test_partial_execution_cannot_report_required_output_success():
    runtime = ChildRuntime()
    execute(runtime)
    record = next(iter(runtime.records.values()))
    record["outcome"] = "partial"
    with pytest.raises(WorkflowChatExecutionError, match="did not complete"):
        execute(runtime)


def test_search_seeds_preserve_source_selection_and_require_the_real_search():
    seeds = build_workflow_chat_seeds({
        **WORKFLOW, "group_id": "workflow-group",
        "document_action": {
            "type": "search", "document_ids": ["selected-document"], "doc_scope": "public",
            "active_public_workspace_id": ["selected-public-workspace"],
        },
    }, CONFIGURATION)
    assert seeds["document_ids"] == ["selected-document"]
    assert seeds["required_capabilities"] == ["web_search", "document_search"]
    assert seeds["doc_scope"] == "public" and seeds["active_group_ids"] == []
    assert seeds["active_public_workspace_ids"] == ["selected-public-workspace"]


@pytest.mark.parametrize("action,capability", [
    ("merge", "document_merge"), ("analyze", "document_analyze"), ("comparison", "document_compare"),
])
@pytest.mark.parametrize("extra_capabilities", [[], ["web_search"]])
def test_document_action_is_checkpointed_before_additional_chat_work(
    harness, monkeypatch, action, capability, extra_capabilities,
):
    runner = importlib.import_module("functions_workflow_runner")
    bridge = importlib.import_module("functions_workflow_chat_execution")
    document_calls, children, cached = [], [], {}
    original = {
        "reply": "The full saved document outcome.", "execution_status": "succeeded",
        "workflow_result": {"result_id": "canonical-analysis"},
        "generated_artifacts": [{"output_id": "document-output"}],
    }

    def document_operation(*args, **kwargs):
        document_calls.append(action)
        return deepcopy(original)

    def checkpoint(key, operation, **kwargs):
        if key not in cached:
            cached[key] = operation()
        return deepcopy(cached[key])

    def child(workflow, settings, **kwargs):
        children.append(deepcopy(workflow))
        return {
            "reply": "The document outcome and researched events.", "execution_status": "succeeded",
            "web_search_citations": [{"url": "https://example.org/events"}],
        }

    monkeypatch.setattr(runner, "_get_document_action_config", lambda workflow: deepcopy(workflow["document_action"]))
    monkeypatch.setattr(runner, "_execute_cancelable_workflow_step", lambda workflow, run, operation: operation())
    monkeypatch.setattr(runner, "_raise_if_workflow_run_cancelled", lambda *args: None)
    monkeypatch.setattr(runner, "_resolve_recent_document_action_targets", lambda workflow, config, settings: config)
    monkeypatch.setattr(runner, "_build_run_item_activity_callback", lambda *args, **kwargs: None)
    monkeypatch.setattr(runner, "_initialize_document_run_items", lambda *args, **kwargs: None)
    monkeypatch.setattr(runner, "_execute_document_merge_workflow", document_operation)
    monkeypatch.setattr(runner, "_execute_document_action_workflow", document_operation)
    monkeypatch.setattr(runner, "_workflow_model_core_execution_context", lambda *args: nullcontext())
    monkeypatch.setattr(runner, "workflow_unit", checkpoint)
    monkeypatch.setattr(bridge, "execute_workflow_chat_task", child)
    workflow = {
        **WORKFLOW, "document_action": {"type": action, "document_ids": ["first", "second"]},
        "chat_execution": {**CONFIGURATION, "required_capabilities": [capability, *extra_capabilities]},
    }
    for _index in range(2):
        result = runner._execute_workflow_dispatch(workflow, harness.settings, "conversation-1", "parent", None, {})
        assert result["workflow_result"] == original["workflow_result"]
        assert result["generated_artifacts"] == original["generated_artifacts"]
        assert result["web_search_citations"] == [{"url": "https://example.org/events"}]
    assert document_calls == [action]
    assert all(item["chat_execution"]["required_capabilities"] == extra_capabilities for item in children)
    assert all(
        item["chat_execution"]["mode"] == ("selected" if extra_capabilities else "orchestration")
        for item in children
    )
    assert all(item["document_action"] == {"type": "none"} for item in children)
    assert all(original["reply"] in item["task_prompt"] for item in children)


@pytest.mark.parametrize("cancel", [False, True])
def test_workflow_renderer_continuation_reuses_prepared_content_and_child(harness, cancel, monkeypatch):
    from test_support.orchestration_harness_execution import render_step

    harness.conversations.upsert_item({**harness.conversation, "workflow_id": "workflow-1", "chat_type": "workflow"})
    harness.settings["allow_user_workflows"] = True
    configuration = {**CONFIGURATION, "required_capabilities": ["render_file"]}
    harness.replies = [
        json.dumps({"steps": [harness_step(), render_step("report", "md", source="answer")]}),
        "The complete retained report.",
    ]
    workflow = {**WORKFLOW, "task_prompt": "Write a report and provide it as a Markdown file."}

    class Suspended(BaseException):
        pass

    def wait(key, references):
        raise Suspended()

    def interrupted_upload():
        raise TimeoutError("Offline file transport interruption.")

    harness.blobs.before_file_upload = interrupted_upload
    with pytest.raises(Suspended):
        execute_workflow_chat_task(
            workflow, harness.settings, conversation_id="conversation-1", run_id="render-run",
            configuration=configuration, check_cancelled=lambda: None,
            execution=SimpleNamespace(wait_for_output=wait),
        )
    pending = harness.run_store.get_orchestration_run(
        child_execution_id("render-run", "events"), "owner", "conversation-1", strict=True,
    )
    assert pending["status"] == "waiting" and len(harness.model_calls) == 2
    from test_orchestration_harness_scheduler import tick

    background, _queries, _logs = tick(harness)
    assert background["counts"]["runs_executed"] == 0
    assert background["counts"]["outputs_processed"] == 0
    assert harness.blobs.file_uploads == 0 and len(harness.model_calls) == 2
    if cancel:
        from functions_workflow_chat_execution import cancel_workflow_chat_executions

        original_query = harness.runs.query_items

        def workflow_selectors(query, parameters=None, **kwargs):
            rows = original_query(query, parameters=parameters, **kwargs)
            values = {entry["name"]: entry["value"] for entry in parameters or []}
            if "@workflow_run_id" not in values:
                return rows
            return [
                row for row in rows
                if (row.get("workflow_execution") or {}).get("workflow_run_id") == values["@workflow_run_id"]
                and (row.get("workflow_execution") or {}).get("workflow_id") == values["@workflow_id"]
            ]

        monkeypatch.setattr(harness.runs, "query_items", workflow_selectors)
        cancel_workflow_chat_executions(workflow, "render-run", "conversation-1")
        cancelled = harness.run_store.get_orchestration_run(
            pending["id"], "owner", "conversation-1", strict=True,
        )
        assert cancelled["cancellation_requested_at"]
        assert len(harness.model_calls) == 2 and harness.blobs.file_uploads == 0
        return
    harness.blobs.before_file_upload = None
    result = execute_workflow_chat_task(
        workflow, harness.settings, conversation_id="conversation-1", run_id="render-run",
        configuration=configuration, check_cancelled=lambda: None,
    )
    assert result["orchestration_run_id"] == pending["id"]
    assert len(result["generated_artifacts"]) == 1 and harness.blobs.file_uploads == 1
    assert len(harness.model_calls) == 2


@pytest.mark.parametrize("structured", [False, True])
def test_repeated_output_polls_preserve_one_attempt_and_one_structured_admission(structured):
    from functions_workflow_execution import DurableWorkflowExecution, WorkflowSuspended
    from functions_workflow_runtime_store import WorkflowRuntimeLease, WorkflowRuntimeStore
    from functions_workflow_structured_execution import StructuredWorkflowExecution
    from test_workflow_durable_execution import Clock
    from test_workflow_result_contract import SerializedSections
    from test_workflow_structured_flow import task

    workflow = {**WORKFLOW, "durable_execution": True}
    node = {"id": "events-node", "kind": "task", "task_id": "events"}
    if structured:
        workflow.update(
            definition_version=3, tasks=[task("events")],
            flow={"id": "root", "nodes": [node], "outputs": []},
        )
    clock = Clock()
    store = WorkflowRuntimeStore(AtomicMemoryContainer("run_id"), workflow, "poll-run", clock=clock)
    sections = SerializedSections()
    store.initialize(
        snapshot_ref={"storage": "cosmos", "schema_version": 1, "sha256": "a" * 64,
                      "size_bytes": 100, "chunk_count": 1},
        definition_revision="b" * 64, actor_user_id="owner", request_id="poll-request",
    )

    def controller(lease):
        execution_type = StructuredWorkflowExecution if structured else DurableWorkflowExecution
        execution = execution_type(
            store, lease, workflow, "poll-run", save_result=sections.save,
            load_result=lambda wf, run, key, reference, **kwargs: sections.load(wf, run, key, reference),
        )
        if structured:
            execution.set_node(node, "root")
        return execution

    for index in range(5):
        with WorkflowRuntimeLease(store, owner_id=f"poll-worker-{index}") as lease:
            execution = controller(lease)
            with pytest.raises(WorkflowSuspended, match="waiting_output"):
                execution.run_unit(
                    "task:events",
                    lambda: execution.wait_for_output(
                        "task:events", [{"kind": "workflow_orchestration", "run_id": "child"}],
                    ),
                    inputs={"request": "stable"}, replay_safe=True,
                )
            unit = execution.unit("task:events") if structured else store.read()["units"]["task:events"]
            assert unit["state"] == "waiting_output" and unit["attempt"] == 1
        waiting = store.read()
        if structured:
            assert waiting["admitted_count"] == 1
        store.requeue_output(expected_version=waiting["version"], gate_id=waiting["gate"]["id"])
        clock.advance()
    with WorkflowRuntimeLease(store, owner_id="complete-worker") as lease:
        execution = controller(lease)
        result = execution.run_unit(
            "task:events", lambda: {"reply": "Finished retained output."},
            inputs={"request": "stable"}, replay_safe=True,
        )
        assert result["reply"] == "Finished retained output."
        assert execution.unit("task:events")["attempt"] == 1


def test_concurrent_workflow_identities_never_share_owner_roles_or_conversation():
    barrier = Barrier(2)

    def capture(user_id, conversation_id, grant):
        workflow = {
            "user_id": user_id, f"{grant}_authorized": True,
            f"{grant}_authorized_by": user_id, f"{grant}_authorized_at": "2026-10-16T12:00:00Z",
        }
        with workflow_chat_identity(workflow, conversation_id):
            barrier.wait(timeout=10)
            identity = capture_execution_identity(user_id, conversation_id)
            other = current_workflow_identity("second" if user_id == "first" else "first", conversation_id)
        return identity, other, current_workflow_identity(user_id, conversation_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(capture, "first", "first-conversation", "url_access")
        second = pool.submit(capture, "second", "second-conversation", "deep_research")
        results = [first.result(timeout=15), second.result(timeout=15)]
    assert results[0][0].roles == ("User", "UrlAccessUser")
    assert results[1][0].roles == ("User", "DeepResearchUser")
    assert all(other is None and after is None for _identity, other, after in results)


def test_runtime_queue_projection_and_status_use_sdk_default_documents(monkeypatch):
    from azure.cosmos._cosmos_responses import CosmosDict
    from functions_workflow_runtime_store import WorkflowRuntimeStore
    from test_workflow_durable_execution import Clock
    from test_workflow_result_contract import SerializedSections
    import functions_workflow_runtime as runtime

    workflow = {**WORKFLOW, "definition_version": 2, "durable_execution": True}
    definitions = AtomicMemoryContainer("user_id")
    runs = AtomicMemoryContainer("user_id")
    controls = AtomicMemoryContainer("run_id")
    clock = Clock()
    sections = SerializedSections()
    definitions.create_item(workflow)
    services = {
        "definitions": definitions, "runs": runs, "partition": "owner",
        "load_workflow": lambda: definitions.read_item(item=workflow["id"], partition_key="owner"),
        "settings": lambda: {"allow_user_workflows": True},
    }
    monkeypatch.setattr(runtime, "_services", lambda _workflow: services)
    monkeypatch.setattr(runtime, "_authorize_execution", lambda *args: None)
    monkeypatch.setattr(runtime, "workflow_runtime_store",
                        lambda wf, run: WorkflowRuntimeStore(controls, wf, run, clock=clock))
    monkeypatch.setattr(runtime, "save_workflow_task_result", sections.save)
    monkeypatch.setattr(runtime, "load_workflow_task_result", sections.load)
    request_id = "409db407-5d6f-4496-873b-d587393b9c81"
    first = runtime.queue_durable_workflow_run(workflow, actor_user_id="owner", request_id=request_id)
    second = runtime.queue_durable_workflow_run(workflow, actor_user_id="owner", request_id=request_id)
    assert isinstance(first["run"], CosmosDict)
    assert first["run"]["id"] == second["run"]["id"]
    run_id = first["run"]["id"]
    control = runtime.workflow_runtime_store(workflow, run_id).read()
    projected = runtime._project_runtime_run(services, workflow, run_id, control)
    status = runtime.workflow_runtime_status(workflow, run_id, reader_user_id="owner")
    assert projected["id"] == run_id and projected["status"] == "queued"
    assert status["state"] == "queued"
    stored = definitions.read_item(item=workflow["id"], partition_key="owner")
    assert stored["active_run_id"] == run_id and stored["_etag"]


@pytest.mark.parametrize("optimized", [False, True])
@pytest.mark.parametrize("order", [
    ("functions_workflow_chat_execution", "functions_orchestration_execution"),
    ("functions_orchestration_execution", "functions_workflow_chat_execution"),
])
def test_workflow_chat_cold_imports_preserve_real_bootstrap_boundaries(optimized, order):
    from test_orchestration_harness_execution import EARLY_PROBE, run_probe

    process = run_probe(EARLY_PROBE, order, optimized)
    assert process.returncode == 0, process.stdout[-6000:] + process.stderr[-6000:]
    assert "PASS:" in process.stdout


@pytest.mark.parametrize("optimized", [False, True])
@pytest.mark.parametrize("order", [
    ("functions_workflow_chat_execution", "app", "background_tasks"),
    ("app", "background_tasks", "functions_workflow_chat_execution"),
])
def test_workflow_chat_real_web_scheduler_bootstrap_preserves_required_operations(optimized, order):
    from test_orchestration_harness_execution import BOOTSTRAP_PROBE, run_probe

    process = run_probe(BOOTSTRAP_PROBE, order, optimized)
    assert process.returncode == 0, process.stdout[-6000:] + process.stderr[-6000:]
    assert "PASS: real web/scheduler headless boundary" in process.stdout
