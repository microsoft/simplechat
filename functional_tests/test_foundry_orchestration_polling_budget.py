# test_foundry_orchestration_polling_budget.py
"""
Functional tests for Foundry polling within the existing orchestration budgets.
Version: 0.261.370
Implemented in: 0.261.370

Real web-search adapters, shared wrapper, capture and pinned Semantic Kernel polling
run against fake Azure operations and a virtual clock. No live service is accessed.
"""

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib
import json
from types import SimpleNamespace
from unittest.mock import Mock

from azure.ai.agents.models import AgentThread, RunStep, ThreadMessage, ThreadRun
from azure.core.exceptions import HttpResponseError
from azure.cosmos._cosmos_responses import CosmosDict
import pytest
from semantic_kernel.agents import AzureAIAgent as SdkAzureAIAgent

from test_orchestration_external_configuration_capture import (
    _web_attestor, capture_runtime, gather_modules, run_gather,
)
from test_support.offline_bootstrap import OfflineContainer


class VirtualClock:
    def __init__(self):
        self.elapsed = 0.0
        self.epoch = datetime(2026, 10, 21, tzinfo=timezone.utc)

    def monotonic(self):
        return 1000 + self.elapsed

    def utcnow(self):
        return self.epoch + timedelta(seconds=self.elapsed)

    def advance(self, seconds):
        self.elapsed += seconds

    def sleep(self, seconds):
        self.advance(seconds)


@pytest.fixture
def polling_runtime(capture_runtime, monkeypatch):
    runtime = capture_runtime
    state = SimpleNamespace(
        clock=VirtualClock(), calls=[], clients=[], polling_options=[],
        complete_after=90, failures=[], stall=None, mutation=None, creation_times=[],
        cancel_after=None, tokens=[], definitions=0, cleanup_failure=None, message_delay=0,
    )
    timing = importlib.import_module("functions_orchestration_timing")
    loop = asyncio.run.__self__
    state.loop = loop
    state.real_loop_time = loop.time
    original_sleep = asyncio.sleep

    async def virtual_sleep(seconds, result=None):
        state.clock.advance(seconds)
        await original_sleep(0)
        return result

    monkeypatch.setattr(loop, "time", state.clock.monotonic)
    monkeypatch.setattr(asyncio, "sleep", virtual_sleep)
    monkeypatch.setattr(runtime.modules.foundry, "log_event", Mock())
    create_client = SdkAzureAIAgent.create_client
    initialize_agent = SdkAzureAIAgent.__init__

    def initialize(self, **kwargs):
        state.polling_options.append(kwargs.get("polling_options"))
        initialize_agent(self, **kwargs)

    async def stall_at(phase):
        if state.cleanup_failure == phase:
            raise RuntimeError("PRIVATE_CLEANUP_FAILURE")
        if state.stall == phase:
            await asyncio.Event().wait()

    def factory(**kwargs):
        client = create_client(**kwargs)
        operations = client.agents
        original_runs = operations.runs
        entry = SimpleNamespace(client=client, operations=operations, runs=original_runs, closed=False)
        state.clients.append(entry)
        run = None

        async def get_agent(agent_id):
            state.definitions += 1
            await stall_at("definition")
            return runtime.state.definition

        async def create_thread(**_kwargs):
            state.calls.append("thread")
            return AgentThread({"id": "actual-thread"})

        async def create_message(**_kwargs):
            state.calls.append("message")
            return ThreadMessage({"id": "input", "thread_id": "actual-thread", "role": "user", "content": []})

        async def create_run(**kwargs):
            nonlocal run
            state.calls.append("create-run")
            state.creation_times.append(state.clock.elapsed)
            state.tokens.append(kwargs.get("max_completion_tokens"))
            state.metadata = deepcopy(kwargs.get("metadata"))
            await stall_at("create-run")
            if state.failures:
                error, advance = state.failures.pop(0)
                state.clock.advance(advance)
                if error is not None:
                    raise error
            run = {
                "id": "actual-run", "thread_id": kwargs["thread_id"], "assistant_id": kwargs["agent_id"],
                "status": "queued", "tool_resources": None,
                **{key: value for key, value in kwargs.items() if key not in ("thread_id", "agent_id", "metadata")},
            }
            if state.mutation is not None:
                state.mutation(run)
            return ThreadRun(run)

        async def get_run(**_kwargs):
            state.calls.append("get-run")
            await stall_at("get-run")
            return ThreadRun({
                **run, "status": "completed" if state.clock.elapsed >= state.complete_after else "in_progress",
            })

        async def cancel_run(**kwargs):
            state.calls.append("cancel-run")
            state.cancelled_identity = kwargs
            await stall_at("cancel-run")

        async def list_steps(**_kwargs):
            yield RunStep({
                "id": "message-step", "type": "message_creation", "completed_at": 1700000000,
                "step_details": {"type": "message_creation", "message_creation": {"message_id": "output"}},
            })

        async def get_message(**_kwargs):
            state.clock.advance(state.message_delay)
            return ThreadMessage({
                "id": "output", "thread_id": "actual-thread", "run_id": "actual-run", "role": "assistant",
                "content": [{"type": "text", "text": {
                    "value": "Budgeted SDK answer. [Source](https://example.com/source)", "annotations": [],
                }}],
            })

        async def delete_thread(*_args, **_kwargs):
            state.calls.append("delete-thread")
            await stall_at("delete-thread")

        async def close():
            state.calls.append("close-client")
            await stall_at("close-client")
            entry.closed = True
            await client_close()

        client_close = client.close
        monkeypatch.setattr(operations, "get_agent", get_agent)
        monkeypatch.setattr(operations.threads, "create", create_thread)
        monkeypatch.setattr(operations.threads, "delete", delete_thread)
        monkeypatch.setattr(operations.messages, "create", create_message)
        monkeypatch.setattr(operations.messages, "get", get_message)
        monkeypatch.setattr(original_runs, "create", create_run)
        monkeypatch.setattr(original_runs, "get", get_run)
        monkeypatch.setattr(original_runs, "cancel", cancel_run)
        monkeypatch.setattr(operations.run_steps, "list", list_steps)
        monkeypatch.setattr(client, "close", close)
        return client

    monkeypatch.setattr(runtime.modules.foundry, "AzureAIAgent", SdkAzureAIAgent)
    monkeypatch.setattr(SdkAzureAIAgent, "create_client", staticmethod(factory))
    monkeypatch.setattr(SdkAzureAIAgent, "__init__", initialize)
    attestor = _web_attestor(runtime)
    runtime.context.capture_external_source_configuration = attestor.capture

    def control(step=180, run=600, *, cancelled=None):
        probe = cancelled or (lambda: state.cancel_after is not None and state.clock.elapsed >= state.cancel_after)
        value = timing.OrchestrationExecutionControl(
            step_deadline=1000 + step, run_deadline=state.clock.epoch + timedelta(seconds=run),
            cancel_requested=probe, monotonic=state.clock.monotonic, utcnow=state.clock.utcnow,
        )
        runtime.context._execution_control = value
        return value

    runtime.polling = state
    runtime.control = control
    runtime.timing = timing
    runtime.attestor = attestor
    return runtime


def _assert_closed(runtime):
    assert all(entry.closed for entry in runtime.polling.clients)
    assert all(credential.closed for credential in runtime.state.credentials)
    assert all(entry.operations.runs is entry.runs for entry in runtime.polling.clients)


def test_real_sdk_waits_beyond_one_minute_on_one_captured_run(polling_runtime):
    runtime = polling_runtime
    runtime.control()
    step, result = run_gather(runtime)
    state = runtime.polling
    assert result["status"] == "completed", result
    assert 60 < state.clock.elapsed < 180
    assert state.calls.count("create-run") == 1
    assert state.calls.count("get-run") > 2
    assert state.calls.count("delete-thread") == 1
    assert "cancel-run" not in state.calls
    assert state.polling_options[0].run_polling_timeout.total_seconds() > 60
    assert "Budgeted SDK answer." in "\n".join(result["notes"])
    proof = runtime.attestor.for_admission(
        "web", producer=runtime.context.result_producer(step), settings=runtime.settings, source=None, selector=None,
    )
    current = runtime.attestor.current(
        "web", producer=runtime.context.result_producer(step), settings=runtime.settings, source=None,
    )
    assert proof == current
    assert state.metadata == {}
    assert "_execution_control" not in json.dumps(runtime.settings)
    _assert_closed(runtime)


@pytest.mark.parametrize("phase", ["definition", "create-run", "get-run", None])
def test_cancellation_is_effective_during_sdk_awaits(polling_runtime, phase):
    runtime = polling_runtime
    runtime.polling.stall = phase
    runtime.polling.cancel_after = 3
    runtime.control()
    with pytest.raises(runtime.timing.OrchestrationExecutionStopped):
        run_gather(runtime)
    assert runtime.polling.clock.elapsed < 10
    assert runtime.polling.calls.count("create-run") <= 1
    if phase not in ("definition", "create-run"):
        assert runtime.polling.cancelled_identity == {"thread_id": "actual-thread", "run_id": "actual-run"}
    _assert_closed(runtime)


def test_cancel_before_start_creates_no_provider_resources(polling_runtime):
    runtime = polling_runtime
    runtime.control(cancelled=lambda: True)
    with pytest.raises(runtime.timing.OrchestrationExecutionStopped):
        run_gather(runtime)
    assert runtime.polling.clients == []
    assert runtime.state.credentials == []


@pytest.mark.parametrize("step,run", [(4, 600), (180, 4), (0, 600), (180, 0)])
def test_exhausted_budget_stops_the_same_run(polling_runtime, step, run):
    runtime = polling_runtime
    runtime.control(step=step, run=run)
    with pytest.raises(runtime.timing.OrchestrationExecutionStopped):
        run_gather(runtime)
    assert runtime.polling.clock.elapsed < 10
    assert runtime.polling.calls.count("create-run") == (1 if min(step, run) > 0 else 0)
    if min(step, run) > 0:
        assert runtime.polling.calls.count("cancel-run") == 1
        assert runtime.polling.calls.count("delete-thread") == 1
    _assert_closed(runtime)


def test_no_control_keeps_sdk_defaults_and_token_limit(polling_runtime):
    runtime = polling_runtime
    runtime.polling.complete_after = 1
    foundry_settings = runtime.settings["web_search_agent"]["other_settings"]["azure_ai_foundry"]
    result = asyncio.run(runtime.modules.foundry.execute_foundry_agent(
        foundry_settings=foundry_settings, global_settings=runtime.settings,
        message_history=[], metadata={}, max_completion_tokens=321,
    ))
    assert "Budgeted SDK answer." in result.message
    assert runtime.polling.polling_options == [None]
    assert runtime.polling.tokens == [321]
    _assert_closed(runtime)


@pytest.mark.parametrize("error,code,retryable", [
    (ConnectionResetError("PRIVATE_TRANSPORT"), "connection_failed", True),
    (TimeoutError("PRIVATE_TIMEOUT"), "provider_timeout", True),
    (HttpResponseError(message="PRIVATE_429", response=SimpleNamespace(
        status_code=429, reason="throttled", headers={}, content_type="application/json",
    )), "provider_http_error", True),
    (HttpResponseError(message="PRIVATE_400", response=SimpleNamespace(
        status_code=400, reason="bad request", headers={}, content_type="application/json",
    )), "provider_http_error", False),
])
def test_provider_errors_keep_existing_retry_classification(polling_runtime, error, code, retryable):
    runtime = polling_runtime
    runtime.control()
    runtime.polling.failures = [(error, 1)]
    _, result = run_gather(runtime)
    schema = importlib.import_module("functions_orchestration_schema")
    assert result["failure"]["code"] == code
    assert schema.failure_is_transient(result["failure"]) is retryable
    assert runtime.polling.calls.count("create-run") == 1
    assert "PRIVATE_" not in json.dumps(result)
    _assert_closed(runtime)


def test_changed_actual_run_remains_refused(polling_runtime):
    runtime = polling_runtime
    runtime.control()
    runtime.polling.mutation = lambda run: run.update(instructions="Unapproved provider configuration.")
    _, result = run_gather(runtime)
    assert result["status"] == "failed"
    assert "Budgeted SDK answer." not in json.dumps(result)
    assert runtime.polling.calls.count("create-run") == 1
    _assert_closed(runtime)


def _execute_web_plan(runtime, monkeypatch, *, step_budget=180, run_budget=600, configured_run_budget=None):
    executor = runtime.modules.runtime
    schema = importlib.import_module("functions_orchestration_schema")
    settings = {
        **runtime.settings, "chat_orchestration_step_timeout_seconds": step_budget,
        "chat_orchestration_total_timeout_seconds": configured_run_budget or run_budget,
    }
    plan = schema.normalize_plan(
        {
            "run_id": runtime.context.run_id,
            "steps": [{"step_id": "gather", "capability_id": "web_search", "arguments": {"query": "Current facts"}}],
        },
        "conversation-1", "owner", settings=settings, contract_version=2,
        available_capability_ids=["web_search"],
    )
    clock = runtime.polling.clock

    class ExecutionClock(datetime):
        @classmethod
        def now(cls, tz=None):
            value = clock.utcnow()
            return value if tz is not None else value.replace(tzinfo=None)

    monkeypatch.setattr(executor, "time", clock)
    monkeypatch.setattr(executor, "datetime", ExecutionClock)
    context = runtime.context
    context.execution_deadline_at = (clock.epoch + timedelta(seconds=run_budget)).isoformat()
    context._result_guard_token_for_step = lambda step_id: "server-attempt-token"
    world = runtime.authorization_world
    world.fixture.producer = context.result_producer(plan["steps"][0])
    world.run["plan"] = deepcopy(plan)
    world.run["memory_audience"] = {"kind": "personal", "owner_id": "owner", "collaboration_id": ""}
    world.settings.update(settings)
    provider = world.provider(
        read_configuration=runtime.attestor.current, configuration_admitter=runtime.attestor.for_admission,
    )
    context.result_service = world.service(provider)
    context.resolve_source_manifest = world.fixture.resolve
    context.external_source_admission = provider.admit_gather_result
    context.external_source_preflight = provider.preflight_gather_invocation
    events = []
    persisted = []
    with world:
        result = executor.execute_plan(
            plan, context, settings=settings, user_id="owner", emit=events.append,
            persist=lambda *args: persisted.append(args),
            cancel_requested=lambda: (
                runtime.polling.cancel_after is not None and clock.elapsed >= runtime.polling.cancel_after
            ),
        )
    assert "_execution_control" not in json.dumps([events, persisted], default=str)
    assert not hasattr(context, "_execution_control")
    return result


def test_executor_supplies_real_control_and_retains_captured_result(polling_runtime, monkeypatch):
    runtime = polling_runtime
    result = _execute_web_plan(runtime, monkeypatch)
    assert result["steps"][0]["status"] == "completed", result
    assert runtime.polling.clock.elapsed > 60
    assert runtime.polling.calls.count("create-run") == 1
    contracts = importlib.import_module("functions_orchestration_result_contracts")
    task = contracts.TaskResult.from_dict(result["task_results"]["gather"])
    with runtime.authorization_world:
        prepared = runtime.context.result_service.open_result(task.output("prepared")).read_value()
    assert "Budgeted SDK answer." in "\n".join(prepared["notes"])
    _assert_closed(runtime)


@pytest.mark.parametrize("step_budget,run_budget,code", [(4, 600, "step_timeout"), (180, 4, "run_timeout")])
def test_executor_preserves_deadline_reason_without_retry(polling_runtime, monkeypatch, step_budget, run_budget, code):
    runtime = polling_runtime
    result = _execute_web_plan(runtime, monkeypatch, step_budget=step_budget, run_budget=run_budget)
    assert result["status"] == "failed", result
    assert result["steps"][0]["failure"]["code"] == code
    assert runtime.polling.calls.count("create-run") == 1
    assert runtime.polling.calls.count("cancel-run") == 1
    _assert_closed(runtime)


def test_executor_preserves_user_cancellation_reason(polling_runtime, monkeypatch):
    runtime = polling_runtime
    runtime.polling.cancel_after = 3
    result = _execute_web_plan(runtime, monkeypatch)
    assert result["status"] == "cancelled", result
    assert result["steps"][0]["failure"]["code"] == "user_cancelled"
    assert runtime.polling.calls.count("create-run") == 1
    _assert_closed(runtime)


def test_existing_durable_run_deadline_wins_over_changed_settings(polling_runtime, monkeypatch):
    runtime = polling_runtime
    result = _execute_web_plan(runtime, monkeypatch, run_budget=4, configured_run_budget=7200)
    assert result["steps"][0]["failure"]["code"] == "run_timeout", result
    assert runtime.polling.polling_options[0].run_polling_timeout.total_seconds() <= 4
    assert runtime.polling.calls.count("create-run") == 1
    _assert_closed(runtime)


@pytest.mark.parametrize("run_budget", [600, 100])
def test_transient_retry_has_only_remaining_budget(polling_runtime, monkeypatch, run_budget):
    runtime = polling_runtime
    runtime.polling.failures = [(ConnectionResetError("PRIVATE_TRANSIENT"), 80)]
    result = _execute_web_plan(runtime, monkeypatch, run_budget=run_budget)
    assert result["steps"][0]["status"] == "completed", result
    assert runtime.polling.calls.count("create-run") == 2
    options = runtime.polling.polling_options
    assert options[1].run_polling_timeout < options[0].run_polling_timeout - timedelta(seconds=80)
    assert runtime.polling.creation_times[1] >= 81.5
    _assert_closed(runtime)


def test_nontransient_provider_failure_is_not_retried(polling_runtime, monkeypatch):
    runtime = polling_runtime
    error = HttpResponseError(message="PRIVATE_REJECTED", response=SimpleNamespace(
        status_code=400, reason="bad request", headers={}, content_type="application/json",
    ))
    runtime.polling.failures = [(error, 1)]
    result = _execute_web_plan(runtime, monkeypatch)
    assert result["steps"][0]["failure"]["code"] == "provider_http_error", result
    assert runtime.polling.calls.count("create-run") == 1
    assert "PRIVATE_" not in json.dumps(result)
    _assert_closed(runtime)


@pytest.mark.parametrize("advance,expected_runs", [(179, 1), (180, 1), (170, 2)])
def test_retry_cannot_reset_or_outlive_original_step_budget(polling_runtime, monkeypatch, advance, expected_runs):
    runtime = polling_runtime
    runtime.polling.complete_after = 9999
    runtime.polling.failures = [(ConnectionResetError("PRIVATE_TRANSIENT"), advance)]
    result = _execute_web_plan(runtime, monkeypatch)
    assert result["steps"][0]["failure"]["code"] == "step_timeout", result
    assert runtime.polling.calls.count("create-run") == expected_runs
    assert runtime.polling.clock.elapsed < 182
    _assert_closed(runtime)


def test_retry_delay_cannot_outlive_run_deadline(polling_runtime, monkeypatch):
    runtime = polling_runtime
    runtime.polling.failures = [(ConnectionResetError("PRIVATE_TRANSIENT"), 99)]
    result = _execute_web_plan(runtime, monkeypatch, run_budget=100)
    assert result["steps"][0]["failure"]["code"] == "run_timeout", result
    assert runtime.polling.calls.count("create-run") == 1
    assert runtime.polling.clock.elapsed < 102
    _assert_closed(runtime)


def test_transient_failure_is_retried_only_once(polling_runtime, monkeypatch):
    runtime = polling_runtime
    runtime.polling.failures = [(ConnectionResetError("PRIVATE_TRANSIENT"), 1)] * 3
    result = _execute_web_plan(runtime, monkeypatch)
    assert result["steps"][0]["failure"]["code"] == "connection_failed", result
    assert runtime.polling.calls.count("create-run") == 2
    assert len(runtime.polling.failures) == 1
    _assert_closed(runtime)


@pytest.mark.parametrize("phase", ["cancel-run", "delete-thread", "close-client"])
def test_hanging_cleanup_is_bounded_and_other_resources_still_close(polling_runtime, monkeypatch, phase):
    runtime = polling_runtime
    state = runtime.polling
    monkeypatch.setattr(state.loop, "time", state.real_loop_time)
    monkeypatch.setattr(runtime.modules.foundry, "_FOUNDRY_CLEANUP_TIMEOUT_SECONDS", 0.01)
    runtime.polling.stall = phase
    runtime.polling.cancel_after = 3
    runtime.control()
    with pytest.raises(runtime.timing.OrchestrationExecutionStopped):
        run_gather(runtime)
    assert state.calls.count(phase) == 1
    assert state.calls.count("close-client") == 1
    assert all(credential.closed for credential in runtime.state.credentials)
    assert all(entry.operations.runs is entry.runs for entry in state.clients)
    assert asyncio.all_tasks(state.loop) == set()
    assert runtime.modules.foundry.log_event.call_count > 0


def test_research_searches_forward_the_same_budget_to_shared_runtime(polling_runtime):
    runtime = polling_runtime
    control = runtime.control()
    messages = []
    result = runtime.modules.web.perform_research_web_searches(
        settings=runtime.settings, conversation_id="conversation-1", user_id="owner",
        user_message="Current facts", user_message_id=None, chat_type="personal", document_scope="all",
        active_group_id=None, active_public_workspace_id=None, web_search_query_text="Current facts",
        system_messages_for_augmentation=messages, agent_citations_list=[], web_search_citations_list=[],
        _execution_control=control,
    )
    assert result["query_results"][0]["success"] is True
    assert runtime.polling.clock.elapsed > 60
    assert runtime.polling.calls.count("create-run") == 1
    assert runtime.polling.polling_options[0].run_polling_timeout.total_seconds() > 60
    _assert_closed(runtime)


@pytest.mark.parametrize("phase", ["cancel-run", "delete-thread", "close-client"])
def test_cleanup_error_never_replaces_stop_or_skips_credential_close(polling_runtime, phase):
    runtime = polling_runtime
    runtime.polling.cleanup_failure = phase
    runtime.polling.cancel_after = 3
    runtime.control()
    with pytest.raises(runtime.timing.OrchestrationExecutionStopped):
        run_gather(runtime)
    assert runtime.polling.calls.count(phase) == 1
    assert runtime.polling.calls.count("close-client") == 1
    assert all(credential.closed for credential in runtime.state.credentials)
    assert all(entry.operations.runs is entry.runs for entry in runtime.polling.clients)
    assert "PRIVATE_CLEANUP_FAILURE" not in repr(runtime.modules.foundry.log_event.call_args_list)


def test_client_construction_failure_still_closes_credential(polling_runtime, monkeypatch):
    runtime = polling_runtime
    runtime.control()

    def fail_client(**_kwargs):
        raise ConnectionResetError("PRIVATE_CONSTRUCTION_FAILURE")

    monkeypatch.setattr(SdkAzureAIAgent, "create_client", staticmethod(fail_client))
    _, result = run_gather(runtime)
    assert result["failure"]["code"] == "connection_failed"
    assert runtime.polling.clients == []
    assert len(runtime.state.credentials) == 1
    assert runtime.state.credentials[0].closed
    assert "PRIVATE_" not in json.dumps(result)


def test_deadline_cancellation_during_run_cleanup_still_closes_resources(polling_runtime, monkeypatch):
    runtime = polling_runtime
    state = runtime.polling
    state.complete_after = 1
    state.message_delay = 4
    state.stall = "cancel-run"
    monkeypatch.setattr(state.loop, "time", state.real_loop_time)
    monkeypatch.setattr(runtime.modules.foundry, "_FOUNDRY_CLEANUP_TIMEOUT_SECONDS", 0.01)
    runtime.control(step=4)
    with pytest.raises(runtime.timing.OrchestrationExecutionStopped):
        run_gather(runtime)
    assert state.calls.count("cancel-run") == 1
    assert state.calls.count("delete-thread") == 1
    _assert_closed(runtime)


def test_recent_chat_upload_inputs_consume_sdk_query_rows(capture_runtime, monkeypatch):
    """The unchanged Cosmos query owner consumes plain rows from an SDK-default container."""
    container = OfflineContainer()
    rows = [
        {
            "id": "upload", "conversation_id": "conversation-1", "role": "file", "timestamp": "2026-10-21T03:00:00Z",
            "filename": "report.pdf", "mime_type": "application/pdf", "metadata": {"is_user_upload": True},
            "blob_container": "chat", "blob_path": "report",
        },
        {
            "id": "generated", "conversation_id": "conversation-1", "role": "file", "timestamp": "2026-10-21T02:00:00Z",
            "filename": "generated.txt", "metadata": {"is_user_upload": False},
            "blob_container": "chat", "blob_path": "must-not-download",
        },
        {
            "id": "image", "conversation_id": "conversation-1", "role": "image", "timestamp": "2026-10-21T01:00:00Z",
            "title": "image.png", "file_content_source": "blob", "metadata": {"content_type": "image/png"},
            "blob_container": "chat", "blob_path": "image",
        },
        {
            "id": "oversized", "conversation_id": "conversation-1", "role": "file", "timestamp": "2026-10-20T00:00:00Z",
            "filename": "large.txt", "metadata": {"is_user_upload": True},
            "blob_container": "chat", "blob_path": "large",
        },
        {
            "id": "other", "conversation_id": "another-conversation", "role": "file", "timestamp": "2026-10-21T04:00:00Z",
            "filename": "other.pdf", "metadata": {"is_user_upload": True},
            "blob_container": "chat", "blob_path": "must-not-download",
        },
    ]
    for row in rows:
        saved = container.upsert_item(row)
        assert type(saved) is CosmosDict
    point = container.read_item("upload", partition_key="conversation-1")
    assert type(point) is CosmosDict
    assert point["_etag"]
    queried = []

    def query_items(*, query, parameters, partition_key, enable_cross_partition_query):
        assert "ORDER BY c.timestamp DESC" in query
        assert parameters == [{"name": "@conversation_id", "value": "conversation-1"}]
        assert partition_key == "conversation-1" and enable_cross_partition_query is True
        values = [
            deepcopy(value) for value in container.items.values()
            if value["conversation_id"] == partition_key and value["role"] in ("file", "image")
        ]
        values.sort(key=lambda value: value["timestamp"], reverse=True)
        queried.append(values)
        return values

    monkeypatch.setattr(container, "query_items", query_items)
    config = importlib.import_module("config")
    monkeypatch.setattr(config, "cosmos_messages_container", container)
    blobs = {"report": b"PDF bytes", "image": b"PNG bytes", "large": b"x" * 2048}
    downloads = []

    def download(blob_container, blob_path):
        downloads.append((blob_container, blob_path))
        return blobs[blob_path]

    foundry = capture_runtime.modules.foundry
    monkeypatch.setattr(foundry, "_download_foundry_source_blob", download)
    file_inputs, file_metadata, seen = [], [], set()
    kwargs = {
        "conversation_id": "conversation-1", "file_inputs": file_inputs,
        "file_metadata": file_metadata, "seen_sources": seen, "max_files": 3, "max_file_bytes": 1024,
    }
    foundry._collect_recent_chat_upload_file_inputs(**kwargs)
    assert all(type(row) is dict for row in queried[0])
    assert [value["filename"] for value in file_inputs] == ["report.pdf", "image.png"]
    assert file_inputs[0]["file_data"] == "data:application/pdf;base64,UERGIGJ5dGVz"
    assert [value["source_type"] for value in file_metadata] == ["chat_upload", "chat_upload"]
    assert [value["file_size"] for value in file_metadata] == [9, 9]
    assert downloads == [("chat", "report"), ("chat", "image"), ("chat", "large")]
    assert seen == {"chat:upload", "chat:image", "chat:oversized"}
    foundry._collect_recent_chat_upload_file_inputs(**kwargs)
    assert len(downloads) == 3
    assert len(file_inputs) == 2
    foundry._collect_recent_chat_upload_file_inputs(**{**kwargs, "max_files": 2})
    foundry._collect_recent_chat_upload_file_inputs(**{**kwargs, "conversation_id": ""})
    assert len(queried) == 2
