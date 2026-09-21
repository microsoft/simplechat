# test_m365_agent_streaming.py
"""
Functional regressions for Microsoft 365 agent streaming context lifetime.
Version: 0.261.031
Implemented in: 0.261.031

Exercises synchronous pulls through real Semantic Kernel agent streaming with
an offline model. Covers context isolation, approvals/sign-in, and early close.
"""

import ast
import asyncio
from contextvars import ContextVar
from pathlib import Path
import socket
import sys
from types import SimpleNamespace
from unittest.mock import Mock

from flask import Flask
from pydantic import Field
import pytest
from semantic_kernel import Kernel
from semantic_kernel.connectors.ai.chat_completion_client_base import ChatCompletionClientBase
from semantic_kernel.contents import AuthorRole, StreamingChatMessageContent


APP = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP))
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Standalone tests initialize repository paths before importing application code.
from agent_logging_chat_completion import LoggingChatCompletionAgent
from functions_async_stream import SyncAsyncStream
from functions_m365_approvals import M365ApprovalRequired
import functions_m365_agent_continuation as continuation
from functions_m365_execution import M365ExecutionContext, get_m365_execution_context, m365_execution_context
from m365_interaction import M365SignInRequired
from test_m365_agent_continuation import Memory
from test_support.m365 import CosmosContainer


class OfflineStreamingModel(ChatCompletionClientBase):
    journal_ids: list[int | None] = Field(default_factory=list)
    principals: list[str] = Field(default_factory=list)

    async def _inner_get_streaming_chat_message_contents(self, chat_history, settings, function_invoke_attempt=0):
        for text in ("First ", "second"):
            journal = continuation._current_journal.get()
            context = get_m365_execution_context()
            self.journal_ids.append(id(journal) if journal is not None else None)
            self.principals.append(context.data_user_id)
            yield [StreamingChatMessageContent(role=AuthorRole.ASSISTANT, content=text, choice_index=0)]


@pytest.fixture
def stream_loop(monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("Agent streaming regressions must not contact a model or cloud service.")

    # Windows constructs a loopback socket pair while creating the event loop.
    loop = asyncio.new_event_loop()
    monkeypatch.setattr(socket.socket, "connect", no_network)
    try:
        yield loop
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()


@pytest.fixture
def runtime(monkeypatch):
    memory = Memory()
    jobs = CosmosContainer("user_id")
    monkeypatch.setattr(continuation, "_dependencies", {})
    continuation.configure_m365_agent_continuation(
        memory_resolver=lambda context: (memory, object()),
        jobs_factory=lambda: jobs, model_context_setter=Mock(),
    )
    context = M365ExecutionContext(
        "owner", "owner", "tenant", request_id="request", conversation_id="conversation",
        action_configs={"files": {"source": "spo"}},
    )
    return SimpleNamespace(memory=memory, jobs=jobs, context=context)


def test_real_agent_stream_keeps_journal_and_identity_until_completion(stream_loop, runtime, caplog):
    model = OfflineStreamingModel(ai_model_id="offline-model")
    agent = LoggingChatCompletionAgent(name="offline-agent", instructions="Test only", service=model)
    with Flask(__name__).test_request_context(), m365_execution_context(runtime.context):
        with SyncAsyncStream(agent.invoke_stream(messages="Test request"), stream_loop) as stream:
            responses = list(stream)
        after = continuation._current_journal.get()
    assert "".join(str(response.content) for response in responses) == "First second"
    assert model.journal_ids[0] is not None
    assert model.journal_ids[0] == model.journal_ids[1]
    assert model.principals == ["owner", "owner"]
    assert after is None
    assert "Failed to detach context" not in caplog.text


def test_real_agent_stream_can_close_before_the_next_model_chunk(stream_loop, runtime, caplog):
    model = OfflineStreamingModel(ai_model_id="offline-model")
    agent = LoggingChatCompletionAgent(name="offline-agent", instructions="Test only", service=model)
    with Flask(__name__).test_request_context(), m365_execution_context(runtime.context):
        with SyncAsyncStream(agent.invoke_stream(messages="Test request"), stream_loop) as stream:
            first = next(stream)
        stream_loop.run_until_complete(stream_loop.shutdown_asyncgens())
        after = continuation._current_journal.get()
    assert str(first.content) == "First "
    assert len(model.journal_ids) == 1
    assert after is None
    assert "Failed to detach context" not in caplog.text


def test_context_changes_do_not_leak_to_the_synchronous_caller(stream_loop):
    scope = ContextVar("stream-scope", default="caller")
    closed = []

    async def source():
        token = scope.set("stream")
        try:
            yield scope.get()
            yield scope.get()
        finally:
            closed.append(scope.get())
            scope.reset(token)

    with SyncAsyncStream(source(), stream_loop) as stream:
        first = next(stream)
        caller_after_first = scope.get()
        second = next(stream)
        remaining = list(stream)
    caller_after_close = scope.get()
    assert first == second == "stream"
    assert caller_after_first == caller_after_close == "caller"
    assert remaining == []
    assert closed == ["stream"]


def test_interleaved_streams_have_independent_contexts(stream_loop):
    scope = ContextVar("interleaved-stream-scope", default=None)

    async def source(value):
        token = scope.set(value)
        try:
            yield scope.get()
            yield scope.get()
        finally:
            scope.reset(token)

    with SyncAsyncStream(source("one"), stream_loop) as first, SyncAsyncStream(source("two"), stream_loop) as second:
        values = [next(first), next(second), next(first), next(second)]
    parent = scope.get()
    assert values == ["one", "two", "one", "two"]
    assert parent is None


def test_early_close_preserves_context_and_does_not_prefetch(stream_loop, runtime):
    seen = []
    agent = SimpleNamespace(name="agent", instructions="Test only", kernel=Kernel())

    @continuation.m365_agent_stream_continuation
    async def source(agent, **kwargs):
        try:
            seen.append("first")
            yield "first"
            seen.append("second")
            yield "second"
        finally:
            seen.append(("closed", continuation._current_journal.get() is not None))

    with m365_execution_context(runtime.context):
        with SyncAsyncStream(source(agent, messages=[]), stream_loop) as stream:
            first = next(stream)
        stream.close()
        after = continuation._current_journal.get()
    assert first == "first"
    assert seen == ["first", ("closed", True)]
    assert after is None
    assert runtime.memory.checkpoints == {}


@pytest.mark.parametrize("wait_type", ["approval", "sign_in"])
def test_wait_exceptions_keep_identity_and_checkpoint_after_a_streamed_chunk(stream_loop, runtime, wait_type):
    pending = (
        M365ApprovalRequired({
            "id": "approval", "request_type": "m365_extended_analysis",
            "subject_user_id": "owner", "group_id": "owner", "approval_scope": "user",
            "status": "pending", "resume_key": "resume", "execution_status": "awaiting_approval",
            "sources": {"spo": {}},
        })
        if wait_type == "approval" else M365SignInRequired("m365_reconnect_required")
    )
    agent = SimpleNamespace(name="agent", instructions="Test only", kernel=Kernel())

    @continuation.m365_agent_stream_continuation
    async def source(agent, **kwargs):
        yield "Preparing"
        continuation._current_journal.get().pending = pending
        yield "Do not disclose pending source data"

    with m365_execution_context(runtime.context):
        with SyncAsyncStream(source(agent, messages=[]), stream_loop) as stream:
            first = next(stream)
            with pytest.raises(type(pending)) as raised:
                next(stream)
        after = continuation._current_journal.get()
    assert first == "Preparing"
    assert raised.value is pending
    assert runtime.memory.checkpoints
    assert after is None


def test_stream_error_propagates_unchanged_and_closes_in_scope(stream_loop):
    failure = RuntimeError("offline model failed")
    closed = []
    scope = ContextVar("failing-stream-scope", default=None)

    async def source():
        token = scope.set("stream")
        try:
            yield "first"
            raise failure
        finally:
            closed.append(scope.get())
            scope.reset(token)

    with SyncAsyncStream(source(), stream_loop) as stream:
        first = next(stream)
        with pytest.raises(RuntimeError) as raised:
            next(stream)
    after = scope.get()
    assert first == "first"
    assert raised.value is failure
    assert closed == ["stream"]
    assert after is None


def test_chat_route_uses_the_context_preserving_bridge_for_agent_streams():
    tree = ast.parse((APP / "route_backend_chats.py").read_text(encoding="utf-8-sig"))
    bridges = [
        item for node in ast.walk(tree) if isinstance(node, ast.With) for item in node.items
        if isinstance(item.context_expr, ast.Call)
        and isinstance(item.context_expr.func, ast.Name) and item.context_expr.func.id == "SyncAsyncStream"
    ]
    assert len(bridges) == 1
    assert ast.unparse(bridges[0].context_expr.args[0]) == "agent_stream"
    direct_pulls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and node.func.attr == "run_until_complete"
        and any(isinstance(child, ast.Attribute) and child.attr == "__anext__" for child in ast.walk(node))
    ]
    assert direct_pulls == []


def test_agent_stream_failure_is_logged_without_debug_mode():
    tree = ast.parse((APP / "route_backend_chats.py").read_text(encoding="utf-8-sig"))
    calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id == "log_event" and node.args
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "[STREAMING] Agent streaming failed."
    ]
    assert len(calls) == 1
    options = {keyword.arg: ast.unparse(keyword.value) for keyword in calls[0].keywords}
    assert options["exceptionTraceback"] == "True"
    assert options["level"] == "logging.ERROR"
    assert "exception_type" in options["extra"]
    assert "conversation_id" in options["extra"]


if __name__ == "__main__":
    sys.exit(pytest.main([str(Path(__file__).resolve())]))
