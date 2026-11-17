# test_agent_workflow_runtime_usage.py
"""Behavioral coverage for metadata-only agent and workflow runtime telemetry.

Version: 0.261.447
Implemented in: 0.261.447

Real runtime facades, delegated execution and activity projections execute with
provider calls and the activity persistence repository replaced, without Azure.
"""

import asyncio
import ast
from dataclasses import replace
import importlib
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from test_agent_delegation_runtime import agent, frame, runtime
from test_support.app_stubs import stubbed_config


@pytest.fixture
def activity(monkeypatch):
    with stubbed_config(cosmos_activity_logs_container=None):
        with monkeypatch.context() as scoped:
            debug = ModuleType("functions_debug")
            debug.debug_print = lambda *args, **kwargs: None
            scoped.setitem(sys.modules, "functions_debug", debug)
            scoped.delitem(sys.modules, "functions_activity_logging", raising=False)
            service = importlib.import_module("functions_activity_logging")
            records = {}
            writes = []

            def save(record, idempotency_key=None):
                writes.append(idempotency_key)
                return records.setdefault((record["user_id"], idempotency_key), record)

            scoped.setattr(service, "_create_activity_record", save)
            yield SimpleNamespace(service=service, records=records, writes=writes)


def test_classic_attempts_count_retries_before_message_persistence(runtime, activity):
    calls = []

    class LocalAgent:
        id = "A"
        name = "A"
        deployment_name = "model"

        async def invoke(self, messages):
            calls.append(messages)
            if len(calls) == 1:
                raise TimeoutError("PRIVATE provider response and token")
            return "PRIVATE assistant response"

    identity = runtime.contexts.ExecutionIdentity("actor", "conversation")
    wrapped = runtime.prepare_agent_execution(
        LocalAgent(), agent("A", "actor"), user_id="actor", settings={}, identity=identity,
    )

    async def execute():
        with pytest.raises(TimeoutError):
            await wrapped.invoke(["PRIVATE user prompt"])
        return await wrapped.invoke(["PRIVATE user prompt"])

    result = asyncio.run(execute())
    assert result == "PRIVATE assistant response"
    records = list(activity.records.values())
    assert [row["runtime_usage"]["outcome"] for row in records] == ["timeout", "succeeded"]
    assert len(set(activity.writes)) == 2
    assert all(row["runtime_usage"]["duration_ms"] >= 0 for row in records)
    assert all(row["user_id"] == "actor" for row in records)
    assert "PRIVATE" not in json.dumps(records)


@pytest.mark.parametrize("agent_type", ["local", "new_foundry"])
@pytest.mark.parametrize("mode", ["complete", "close", "failure", "cancel"])
def test_stream_attempt_tracks_terminal_outcome_once(runtime, activity, agent_type, mode):
    closed = []

    class StreamAgent:
        id = "A"
        name = "A"

        async def invoke_stream(self, messages):
            try:
                yield "PRIVATE first chunk"
                if mode == "failure":
                    raise ValueError("PRIVATE failure payload")
                if mode == "cancel":
                    raise asyncio.CancelledError()
                yield "PRIVATE second chunk"
            finally:
                closed.append(True)

    selected = StreamAgent()
    selected.agent_type = agent_type
    wrapped = runtime.prepare_agent_execution(
        selected, agent("A"), user_id="user-1", settings={},
        identity=runtime.contexts.ExecutionIdentity("user-1", "conversation"),
    )

    async def execute():
        stream = wrapped.invoke_stream(["PRIVATE prompt"])
        if mode == "close":
            await anext(stream)
            await stream.aclose()
        elif mode == "failure":
            with pytest.raises(ValueError):
                async for _ in stream:
                    pass
        elif mode == "cancel":
            with pytest.raises(asyncio.CancelledError):
                async for _ in stream:
                    pass
        else:
            async for _ in stream:
                pass

    asyncio.run(execute())
    records = list(activity.records.values())
    assert len(records) == 1
    expected = {"complete": "succeeded", "close": "cancelled", "failure": "failed", "cancel": "cancelled"}
    assert records[0]["runtime_usage"]["outcome"] == expected[mode]
    assert closed == [True]
    assert "PRIVATE" not in json.dumps(records)


def test_external_sync_agent_uses_same_actual_execution_boundary(runtime, activity):
    class ExternalAgent:
        id = "external"
        name = "External"
        agent_type = "aifoundry"

        def invoke(self, messages, **kwargs):
            raise RuntimeError("PRIVATE credentials in upstream error")

    wrapped = runtime.prepare_agent_execution(
        ExternalAgent(), agent("external", is_global=True, scope_type="global", scope_id="global"),
        user_id="actor", settings={},
        identity=runtime.contexts.ExecutionIdentity("actor", "conversation"),
    )
    with pytest.raises(RuntimeError):
        wrapped.invoke(["PRIVATE request"])
    row, = activity.records.values()
    assert row["runtime_usage"]["outcome"] == "failed"
    assert row["runtime_usage"]["entity_type"] == "aifoundry"
    assert row["runtime_usage"]["scope_type"] == "global"
    assert row["user_id"] == "actor"
    assert "PRIVATE" not in json.dumps(row)


@pytest.mark.parametrize("entry", ["scoped", "delegated"])
@pytest.mark.parametrize("error,outcome", [
    (None, "succeeded"), (ValueError, "failed"), (TimeoutError, "timeout"),
    (asyncio.CancelledError, "cancelled"),
])
def test_scoped_agent_does_not_duplicate_delegated_execution(runtime, activity, monkeypatch, entry, error, outcome):
    identity = runtime.contexts.ExecutionIdentity(
        "user-1", "conversation", workspace_type="group", group_id="execution-group",
    )
    canonical = agent("B")
    monkeypatch.setattr(runtime, "resolve_delegation_agent", lambda *args, **kwargs: canonical)
    monkeypatch.setattr(runtime, "resolve_delegation_call", lambda *args, **kwargs: (
        kwargs["caller_agent"], {"id": "call"}, canonical,
    ))
    monkeypatch.setattr(runtime, "_target_messages", AsyncMock(return_value=([], [])))
    monkeypatch.setattr(runtime, "_preflight_captured_agent", lambda *args: None)
    operations = ModuleType("functions_orchestration_operations")
    operations.current_operation_journal = lambda: None
    operations.integration_inputs_require_budget = lambda: False
    operations.require_integration_model_budget = lambda *args: None
    monkeypatch.setitem(sys.modules, "functions_orchestration_operations", operations)
    provider = SimpleNamespace(invoke=AsyncMock(
        return_value="PRIVATE answer", side_effect=error("PRIVATE provider detail") if error else None,
    ))
    monkeypatch.setattr(runtime, "_build_local_agent", lambda *args: (SimpleNamespace(services={}), provider))

    async def execute():
        if entry == "scoped":
            return await runtime.invoke_scoped_agent(
                canonical, "PRIVATE task", identity=identity, budget=runtime.contexts.DelegationBudget(),
            )
        with runtime.contexts.agent_execution(replace(frame(runtime), identity=identity)):
            return json.loads(await runtime.call_agent("call", "PRIVATE task"))

    if error:
        expected = error if entry == "scoped" or error is asyncio.CancelledError else runtime.AgentDelegationError
        with pytest.raises(expected):
            asyncio.run(execute())
    else:
        result = asyncio.run(execute())
        assert result["response"] == "PRIVATE answer"
    row, = activity.records.values()
    assert row["runtime_usage"]["outcome"] == outcome
    assert row["agent"]["id"] == "B"
    assert row["runtime_usage"]["scope_type"] == "personal"
    assert row["workspace_type"] == "group"
    assert row["workspace_context"] == {"group_id": "execution-group"}
    assert "PRIVATE" not in json.dumps(row)


def test_scoped_runtime_preparation_failure_is_an_attempt_after_access_validation(runtime, activity, monkeypatch):
    canonical = agent("B")
    monkeypatch.setattr(runtime, "resolve_delegation_agent", lambda *args, **kwargs: canonical)
    monkeypatch.setattr(runtime, "_preflight_captured_agent", lambda *args: None)
    monkeypatch.setattr(runtime, "_target_messages", AsyncMock(side_effect=RuntimeError("PRIVATE retrieval failure")))
    with pytest.raises(RuntimeError):
        asyncio.run(runtime.invoke_scoped_agent(
            canonical, "PRIVATE task", identity=runtime.contexts.ExecutionIdentity("user-1", "conversation"),
            budget=runtime.contexts.DelegationBudget(),
        ))
    row, = activity.records.values()
    assert row["runtime_usage"]["outcome"] == "failed"
    assert row["runtime_usage"]["duration_ms"] >= 0
    assert "PRIVATE" not in json.dumps(row)


@pytest.mark.parametrize("status,outcome", [
    ("completed", "succeeded"), ("completed_partial", "partial"),
    ("failed", "failed"), ("cancelled", "cancelled"), ("skipped", "succeeded"),
    ("invalid", "failed"), ("incomplete", "partial"),
])
def test_workflow_projection_is_safe_timed_and_idempotent(activity, status, outcome):
    for _ in range(2):
        activity.service.log_workflow_run(
            user_id="actor", workflow_id="workflow", workflow_name="Digest",
            status=status, trigger_source="scheduled", run_id="run",
            error="PRIVATE upstream response", workspace_type="group", group_id="group",
            started_at="2026-11-16T18:00:00+00:00", completed_at="2026-11-16T18:00:02+00:00",
        )
    row, = activity.records.values()
    assert len(activity.writes) == 2
    assert len(set(activity.writes)) == 1
    assert row["runtime_usage"]["outcome"] == outcome
    assert row["runtime_usage"]["duration_ms"] == 2000
    assert row["runtime_usage"]["run_id"] == "run"
    assert row["runtime_usage"]["trigger_type"] == "scheduled"
    assert row["run"]["status"] == status
    assert row["entity"]["id"] == "workflow"
    assert row["workspace_context"] == {"group_id": "group"}
    assert "PRIVATE" not in json.dumps(row)


def test_activity_failure_never_changes_invocation_result(runtime, activity, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("PRIVATE storage connection")

    monkeypatch.setattr(activity.service, "_create_activity_record", fail)
    identity = runtime.contexts.ExecutionIdentity("actor", "conversation")
    with runtime.agent_usage_attempt(agent("A", "actor"), agent("A", "actor"), identity):
        result = "success"
    assert result == "success"
    with pytest.raises(ValueError, match="original failure"):
        with runtime.agent_usage_attempt(agent("A", "actor"), agent("A", "actor"), identity):
            raise ValueError("original failure")


@pytest.mark.parametrize("started_at,completed_at", [
    (None, None), ("bad date", "also bad"), (123, 456),
    ("2026-11-16T18:00:02+00:00", "2026-11-16T18:00:00+00:00"),
])
def test_workflow_unavailable_duration_remains_unknown(activity, started_at, completed_at):
    activity.service.log_workflow_run(
        "actor", "workflow", "Digest", "completed", "manual",
        run_id="run", started_at=started_at, completed_at=completed_at,
    )
    row, = activity.records.values()
    assert row["runtime_usage"]["duration_ms"] is None


def test_agent_records_workflow_correlation_without_inheriting_other_principal(runtime, activity):
    from action_usage import action_usage_identity

    identity = runtime.contexts.ExecutionIdentity("actor", "conversation")
    with action_usage_identity("workflow-owner", workflow_id="workflow", run_id="run", trigger_type="manual"):
        with runtime.agent_usage_attempt(agent("A", "actor"), agent("A", "actor"), identity):
            pass
    with runtime.agent_usage_attempt(agent("A", "actor"), agent("A", "actor"), identity):
        pass
    first, second = activity.records.values()
    assert first["user_id"] == "actor"
    assert first["runtime_usage"]["workflow_id"] == "workflow"
    assert first["runtime_usage"]["run_id"] == "run"
    assert first["runtime_usage"]["trigger_type"] == "manual"
    assert second["runtime_usage"]["workflow_id"] == ""


@pytest.mark.parametrize("configured_scope", ["global", "group"])
@pytest.mark.parametrize("execution_scope", ["personal", "group", "public", ""])
def test_agent_configuration_scope_is_not_execution_workspace(runtime, activity, configured_scope, execution_scope):
    identity = runtime.contexts.ExecutionIdentity(
        "actor", "conversation", workspace_type=execution_scope,
        group_id="execution-group" if execution_scope == "group" else "",
        public_workspace_id="execution-public" if execution_scope == "public" else "",
    )
    reference = {
        "id": "agent", "scope_type": configured_scope,
        "scope_id": "global" if configured_scope == "global" else "configuration-group",
    }
    with runtime.agent_usage_attempt({"id": "agent", "name": "Agent"}, reference, identity):
        pass
    row, = activity.records.values()
    assert row["runtime_usage"]["scope_type"] == configured_scope
    assert row["runtime_usage"]["scope_id"] == reference["scope_id"]
    assert row["workspace_type"] == execution_scope
    expected_context = (
        {"group_id": "execution-group"} if execution_scope == "group" else
        {"public_workspace_id": "execution-public"} if execution_scope == "public" else {}
    )
    assert row["workspace_context"] == expected_context


@pytest.mark.parametrize("scope", ["personal", "group", "public"])
def test_conversation_workspace_is_captured_before_cross_scope_execution(runtime, activity, scope):
    from action_usage import current_action_usage_identity

    observed = []

    async def invoke(messages):
        observed.append(current_action_usage_identity())
        return "PRIVATE answer"

    conversation = {"id": "conversation", "user_id": "actor"}
    if scope != "personal":
        conversation["context"] = [{"type": "primary", "scope": scope, "id": "execution-workspace"}]
    reference = {"id": "global-agent", "scope_type": "global", "scope_id": "global"}
    selected = runtime.prepare_agent_execution(
        SimpleNamespace(id="global-agent", name="Global", invoke=invoke),
        reference, user_id="actor", settings={},
        identity=runtime.contexts.ExecutionIdentity("actor", "conversation"),
        usage_workspace=runtime.conversation_usage_workspace(conversation),
    )
    result = asyncio.run(selected.invoke(["PRIVATE request"]))
    assert result == "PRIVATE answer"
    row, = activity.records.values()
    assert row["runtime_usage"]["scope_type"] == "global"
    assert row["workspace_type"] == scope
    expected_context = {f"{scope if scope == 'group' else 'public_workspace'}_id": "execution-workspace"} if scope != "personal" else {}
    assert row["workspace_context"] == expected_context
    assert observed[0]["workspace_type"] == scope
    assert current_action_usage_identity() == {}


@pytest.mark.parametrize("fail_first", [False, True])
def test_legacy_group_chat_actual_sdk_actor_attempts_are_counted(runtime, activity, monkeypatch, fail_first):
    from flask import Flask, session
    from semantic_kernel.agents import AgentResponseItem, ChatCompletionAgent, ChatHistoryAgentThread
    from semantic_kernel.agents.orchestration.group_chat import RoundRobinGroupChatManager
    from semantic_kernel.agents.runtime import InProcessRuntime
    from semantic_kernel.contents import StreamingChatMessageContent

    for name in ("agent_logging_chat_completion", "agent_orchestrator_groupchat"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.setattr(
        sys.modules["functions_appinsights"], "get_appinsights_logger",
        lambda: logging.getLogger("legacy-usage-test"), raising=False,
    )
    logging_agent = importlib.import_module("agent_logging_chat_completion").LoggingChatCompletionAgent
    orchestrator_type = importlib.import_module("agent_orchestrator_groupchat").OrchestratorAgent
    calls = []

    async def provider(self, *args, **kwargs):
        calls.append(self.id)
        if fail_first and len(calls) == 1:
            raise TimeoutError("PRIVATE upstream failure")
        yield AgentResponseItem(
            message=StreamingChatMessageContent(
                role="assistant", name=self.name, content="PRIVATE answer", choice_index=0,
            ),
            thread=ChatHistoryAgentThread(),
        )

    monkeypatch.setattr(ChatCompletionAgent, "invoke_stream", provider)
    member = logging_agent(
        id="global-member", name="Specialist", description="Global specialist", instructions="PRIVATE instructions",
    )

    async def execute():
        worker = InProcessRuntime()
        orchestrator = orchestrator_type(
            members=[member], manager=RoundRobinGroupChatManager(max_rounds=1), name="orchestrator",
        )
        orchestrator.id = "global-orchestrator"
        with runtime.legacy_group_chat_usage("actor", "conversation", agent=orchestrator):
            worker.start()
            try:
                result = await orchestrator.invoke(task="PRIVATE prompt", runtime=worker)
                return await result.get(timeout=5)
            finally:
                await worker.stop_when_idle()

    app = Flask("legacy-group-chat-usage")
    app.secret_key = "test-only"
    with app.test_request_context("/api/chat"):
        session["user"] = {"oid": "actor", "roles": ["User"]}
        if fail_first:
            with pytest.raises(TimeoutError):
                asyncio.run(execute())
        result = asyncio.run(execute())
    assert str(result) == "PRIVATE answer"
    rows = list(activity.records.values())
    expected = ["timeout", "succeeded"] if fail_first else ["succeeded"]
    assert [row["runtime_usage"]["outcome"] for row in rows] == [value for outcome in expected for value in (outcome, outcome)]
    assert len(set(activity.writes)) == len(expected) * 2
    assert {row["runtime_usage"]["entity_id"] for row in rows} == {"global-member", "global-orchestrator"}
    assert all(row["runtime_usage"]["scope_type"] == "global" for row in rows)
    assert all(row["user_id"] == "actor" for row in rows)
    assert "PRIVATE" not in json.dumps(rows)
    before = len(rows)
    selected = runtime.prepare_agent_execution(
        member, {"id": member.id, "scope_type": "global", "scope_id": "global"},
        user_id="actor", settings={}, identity=runtime.contexts.ExecutionIdentity("actor", "conversation"),
    )

    async def scoped():
        async for _ in selected.invoke_stream([]):
            pass

    with app.test_request_context("/api/chat"):
        session["user"] = {"oid": "actor", "roles": ["User"]}
        with runtime.legacy_group_chat_usage("actor", "conversation"):
            asyncio.run(scoped())
    assert len(activity.records) == before + 1


def test_classic_orchestration_safe_fallback_retains_failed_usage_outcome(runtime, activity):
    from flask import Flask, session
    from runtime_usage import exception_outcome

    root = Path(__file__).resolve().parents[1]
    source = ast.parse((root / "application" / "single_app" / "route_backend_chats.py").read_text(encoding="utf-8"))
    node, = [node for node in ast.walk(source) if isinstance(node, ast.AsyncFunctionDef) and node.name == "run_sk_call"]
    namespace = {
        "asyncio": asyncio, "logging": logging, "user_id": "actor",
        "assert_current_request_sources_available": lambda *args: None,
        "log_event": lambda *args, **kwargs: None, "exception_outcome": exception_outcome,
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), "classic_runtime_dispatch", "exec"), namespace)

    async def get():
        raise TimeoutError("PRIVATE upstream failure")

    async def invoke():
        return SimpleNamespace(get=get)

    app = Flask("legacy-orchestration-fallback")
    app.secret_key = "test-only"
    with app.test_request_context("/api/chat"):
        session["user"] = {"oid": "actor", "roles": ["User"]}
        with runtime.legacy_group_chat_usage(
            "actor", "conversation", agent=SimpleNamespace(id="orchestrator", name="Orchestrator"),
        ) as state:
            response = asyncio.run(namespace["run_sk_call"](invoke, _usage_outcome=state))
    assert response == "Sorry, the orchestration failed."
    row, = activity.records.values()
    assert row["runtime_usage"]["outcome"] == "timeout"
    assert "PRIVATE" not in json.dumps(row)


def test_real_workflow_owner_and_popularity_offline():
    """Boot real modules in a fresh process; replace workflow services, not telemetry."""
    root = Path(__file__).resolve().parents[1]
    script = r'''
from datetime import datetime, timedelta, timezone
from test_support.workflow_result_offline_app import offline_workflow_result_app
from unittest.mock import patch
from action_usage import current_action_usage_identity
from azure.cosmos._cosmos_responses import CosmosDict
from azure.cosmos.exceptions import CosmosResourceExistsError
from runtime_usage import UsageTarget
import json

with offline_workflow_result_app() as harness:
    import functions_workflow_runner as runner
    import functions_activity_logging as activity
    import functions_agent_catalog as catalog
    container = harness.config.cosmos_activity_logs_container
    target = UsageTarget("agent", "sink-agent", "Sink agent")
    activity.log_runtime_usage(
        target, user_id="sink-actor", attempt_id="sink-attempt", outcome="succeeded", duration_ms=12,
    )
    identifier = activity.build_activity_log_id("agent_run", "sink-actor", "runtime:sink-attempt")
    point = container.read_item(item=identifier, partition_key="sink-actor")
    assert isinstance(point, CosmosDict)
    with patch.object(container, "create_item", side_effect=CosmosResourceExistsError(status_code=409)):
        with patch.object(container, "read_item", wraps=container.read_item) as read:
            activity.log_runtime_usage(
                target, user_id="sink-actor", attempt_id="sink-attempt", outcome="succeeded", duration_ms=12,
            )
            assert read.call_args.kwargs == {"item": identifier, "partition_key": "sink-actor"}
            assert read.call_count == 1
    sink_rows = list(container.query_items(
        query="SELECT * FROM c WHERE c.user_id = @user",
        parameters=[{"name": "@user", "value": "sink-actor"}],
    ))
    assert len(sink_rows) == 1
    for index, timestamp in enumerate(("2026-11-15T10:00:00+00:00", "2026-11-16T10:00:00+00:00")):
        activity._create_activity_record({
            "id": f"login-{index}", "user_id": "login-actor", "activity_type": "user_login",
            "timestamp": timestamp, "created_at": timestamp,
        })
    summary = activity.get_user_login_activity_summary({"oid": "login-actor"})
    assert summary == {
        "total_logins": 2, "last_login": "2026-11-16T10:00:00+00:00",
        "total_logins_lookup_succeeded": True, "last_login_lookup_succeeded": True,
    }
    activity.log_user_agreement_accepted("agreement-actor", "group", "group")
    accepted = activity.has_user_accepted_agreement_today("agreement-actor", "group", "group")
    missing = activity.has_user_accepted_agreement_today("missing-actor", "group", "group")
    assert accepted is True and missing is False
    contexts = []
    def file_sync(*args):
        contexts.append(current_action_usage_identity())
        return {"enabled": True, "should_continue": False}
    stack = harness.stack
    stack.enter_context(patch.object(runner, "_get_workflow_run_record", return_value=None))
    stack.enter_context(patch.object(runner, "_save_workflow_run_record"))
    stack.enter_context(patch.object(runner, "_raise_if_workflow_run_cancelled"))
    stack.enter_context(patch.object(runner, "_is_workflow_run_cancellation_requested", return_value=False))
    stack.enter_context(patch.object(runner, "_execute_workflow_file_sync", side_effect=file_sync))
    stack.enter_context(patch.object(runner, "_create_workflow_priority_alert", return_value=None))
    stack.enter_context(patch.object(runner, "_get_workflow_conversation_for_alert", return_value=None))
    stack.enter_context(patch.object(runner, "_get_current_workflow_runtime", return_value={}))
    stack.enter_context(patch.object(runner, "_mark_unfinished_workflow_run_items_cancelled"))
    workflow = {"id": "telemetry-workflow", "name": "Digest", "user_id": "owner", "runner_type": "agent"}
    result = runner.run_personal_workflow(workflow, actor_user_id="actor", run_id="telemetry-skip")
    assert result["run"]["status"] == "skipped"
    assert contexts[-1]["user_id"] == "actor"
    assert contexts[-1]["run_id"] == "telemetry-skip"
    assert current_action_usage_identity() == {}
    with patch.object(runner, "_execute_workflow_file_sync", side_effect=TimeoutError("PRIVATE upstream content")):
        failed = runner.run_personal_workflow(workflow, actor_user_id="actor", run_id="telemetry-fail")
    assert failed["run"]["status"] == "failed"
    started = (datetime.now(timezone.utc) - timedelta(seconds=2)).isoformat()
    cancelled = runner._finalize_cancelled_workflow_run(
        workflow, {"triggered_by": "actor"}, "telemetry-cancel", started, "scheduled", workflow,
    )
    assert cancelled["run"]["status"] == "cancelled"
    rows = list(harness.config.cosmos_activity_logs_container.query_items(
        query="SELECT * FROM c WHERE c.activity_type = 'workflow_run'",
        enable_cross_partition_query=True,
    ))
    selected = {row["runtime_usage"]["run_id"]: row for row in rows
                if row.get("runtime_usage", {}).get("workflow_id") == "telemetry-workflow"}
    assert len(selected) == 3
    assert selected["telemetry-skip"]["runtime_usage"]["outcome"] == "succeeded"
    assert selected["telemetry-fail"]["runtime_usage"]["outcome"] == "timeout"
    assert selected["telemetry-cancel"]["runtime_usage"]["outcome"] == "cancelled"
    assert all(row["user_id"] == "actor" for row in selected.values())
    assert all(row["runtime_usage"]["scope_id"] == "owner" for row in selected.values())
    assert all(row["runtime_usage"]["duration_ms"] >= 0 for row in selected.values())
    assert "PRIVATE" not in json.dumps(list(selected.values()))
    for outcome in ("failed", "cancelled", "timeout", "succeeded"):
        activity.log_agent_run("actor", "telemetry-agent", "Agent", outcome=outcome)
    legacy = {
        "id": "telemetry-legacy", "user_id": "actor", "activity_type": "agent_run",
        "agent": {"id": "telemetry-agent", "name": "Agent"},
        "workspace_type": "personal", "workspace_context": {},
    }
    activity._create_activity_record(legacy)
    key = catalog.build_agent_catalog_key({"id": "telemetry-agent", "user_id": "actor"})
    counts = catalog._load_agent_usage_counts([key])
    assert counts[key] == 2, counts
    for workspace in ("personal", "group"):
        activity.log_agent_run(
            "actor", "global-telemetry-agent", "Global", scope="global", outcome="succeeded",
            workspace_type=workspace, workspace_group_id="execution-group" if workspace == "group" else None,
        )
    global_key = catalog.build_agent_catalog_key({
        "id": "global-telemetry-agent", "scope_type": "global", "scope_id": "global",
    })
    global_counts = catalog._load_agent_usage_counts([global_key])
    assert global_counts[global_key] == 2, global_counts
    group_workflow = {**workflow, "id": "group-telemetry-workflow", "group_id": "workflow-group"}
    group_result = runner.run_personal_workflow(
        group_workflow, actor_user_id="actor", run_id="telemetry-group",
    )
    assert group_result["run"]["status"] == "skipped"
    group_rows = list(container.query_items(
        query="SELECT * FROM c WHERE c.activity_type = 'workflow_run'",
        enable_cross_partition_query=True,
    ))
    group_row, = [row for row in group_rows if row.get("runtime_usage", {}).get("run_id") == "telemetry-group"]
    assert group_row["runtime_usage"]["scope_type"] == "group"
    assert group_row["runtime_usage"]["scope_id"] == "workflow-group"
    assert group_row["workspace_type"] == "group"
    assert group_row["workspace_context"] == {"group_id": "workflow-group"}
    assert not harness.network_attempts, harness.network_attempts
print("WORKFLOW_USAGE_RUNTIME_OK")
'''
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join([
        str(root / "application" / "single_app"), str(root / "functional_tests"),
        environment.get("PYTHONPATH", ""),
    ])
    completed = subprocess.run(
        [sys.executable, "-c", script], cwd=root, env=environment,
        capture_output=True, text=True, timeout=180,
    )
    assert completed.returncode == 0, completed.stdout[-6000:] + completed.stderr[-6000:]
    assert "WORKFLOW_USAGE_RUNTIME_OK" in completed.stdout
