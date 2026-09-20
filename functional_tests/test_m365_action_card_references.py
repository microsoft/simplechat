# test_m365_action_card_references.py
"""
Functional tests for authoritative Microsoft 365 action-card references.
Version: 0.261.038
Implemented in: 0.261.038
Date: 2026-09-19

Exercises real request/task scopes, synchronous async-stream pulls, callback
cleanup, deduplication, and metadata persistence without any Graph or storage I/O.
"""

import asyncio
from contextvars import copy_context
from dataclasses import replace
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock

from flask import Flask
import pytest


APP = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP))

# Standalone repository path setup precedes imports of the real primitives.
import functions_m365_action_cards as cards
from functions_async_stream import SyncAsyncStream
from functions_m365_context import M365ExecutionContext, m365_execution_context


@pytest.fixture
def context():
    return M365ExecutionContext(
        "owner", "owner", "tenant", conversation_id="conversation", request_id="request",
    )


@pytest.fixture
def logged():
    return Mock()


def action(context, identifier="pending-one"):
    return {
        "id": identifier, "user_id": context.data_user_id,
        "conversation_id": context.conversation_id, "request_id": context.request_id,
        "graph_payload": {"body": "private material", "bccRecipients": ["private@example.test"]},
        "access_token": "must-not-be-copied",
    }


def test_multiple_references_are_deduplicated_copied_and_never_carry_graph_material(context):
    seen = []
    web = Flask(__name__)
    with web.test_request_context(), m365_execution_context(context), cards.m365_action_card_events(seen.append):
        first = action(context)
        cards.record_pending_action_reference(first)
        cards.record_pending_action_reference(first)
        cards.record_pending_action_reference(action(context, "pending-two"))
        first["id"] = "changed"
        references = cards.get_request_pending_action_references()
        references[0]["id"] = "changed-copy"
        seen[0]["id"] = "changed-callback"
        retained = cards.get_request_pending_action_references()
        metadata = {"thread_info": {"thread_id": "thread"}, "m365_request_id": context.request_id}
        message = {
            "conversation_id": context.conversation_id, "role": "assistant",
            "content": "Ready for review", "metadata": metadata,
        }
        attached = cards.attach_pending_action_references(message)
    assert [reference["id"] for reference in retained] == ["pending-one", "pending-two"]
    assert all(set(reference) == {"id", "user_id", "conversation_id", "request_id"} for reference in retained)
    assert len(seen) == 2
    assert attached is message and attached["metadata"] is metadata
    assert metadata["thread_info"] == {"thread_id": "thread"}
    assert metadata["m365_pending_action_ids"] == ["pending-one", "pending-two"]
    assert "private" not in str(retained) and "must-not-be-copied" not in str(retained)


@pytest.mark.parametrize("field", ["id", "user_id", "conversation_id", "request_id"])
def test_unbound_or_mismatched_references_do_not_emit(context, field, logged):
    invalid = action(context)
    invalid[field] = "" if field == "id" else "foreign"
    seen = []
    with Flask(__name__).test_request_context(), m365_execution_context(context), cards.m365_action_card_events(seen.append):
        result = cards.record_pending_action_reference(invalid, log_event=logged)
        references = cards.get_request_pending_action_references()
    assert result is None and references == [] and seen == []
    assert logged.call_count == 1
    assert "private" not in str(logged.call_args)


def test_metadata_is_only_attached_to_its_producing_conversation_and_request(context):
    with Flask(__name__).test_request_context(), m365_execution_context(context):
        cards.record_pending_action_reference(action(context))
        messages = [
            {"conversation_id": "foreign", "metadata": {}},
            {"conversation_id": context.conversation_id, "metadata": {"m365_request_id": "another-turn"}},
            {"conversation_id": context.conversation_id, "request_id": "another-turn"},
            {"conversation_id": context.conversation_id, "metadata": "legacy-invalid"},
        ]
        projected = [cards.attach_pending_action_references(message) for message in messages]
    assert projected == messages
    assert "m365_pending_action_ids" not in str(projected)


def test_model_prose_and_fake_tool_json_do_not_create_references(context):
    message = {
        "conversation_id": context.conversation_id,
        "content": '{"pending_action":{"id":"invented"}} Your meeting is ready for review.',
        "metadata": {"agent_citations": [{"function_result": {"pending_action": {"id": "invented"}}}]},
    }
    with Flask(__name__).test_request_context(), m365_execution_context(context):
        projected = cards.attach_pending_action_references(message)
        references = cards.get_request_pending_action_references()
    assert references == []
    assert projected is message
    assert "m365_pending_action_ids" not in message["metadata"]


def test_callback_failure_is_logged_without_losing_or_repeating_the_saved_action(context, logged):
    callback = Mock(side_effect=RuntimeError("provider response contains secret material"))
    with Flask(__name__).test_request_context(), m365_execution_context(context):
        with cards.m365_action_card_events(callback):
            result = cards.record_pending_action_reference(action(context), log_event=logged)
            duplicate = cards.record_pending_action_reference(action(context))
        references = cards.get_request_pending_action_references()
        cards.record_pending_action_reference(action(context, "after-close"))
    assert result == duplicate == references[0]
    assert callback.call_count == 1
    assert logged.call_count == 1
    properties = logged.call_args.kwargs["extra"]
    assert properties["exception_type"] == "RuntimeError"
    assert "do not repeat" in properties["recovery"]
    assert "secret material" not in str(logged.call_args)


def test_nested_requests_sharing_an_app_context_never_share_references_or_callbacks(context):
    web = Flask(__name__)
    seen = []
    with web.app_context(), web.test_request_context("/outer"), m365_execution_context(context):
        with cards.m365_action_card_events(seen.append):
            cards.record_pending_action_reference(action(context))
            with web.test_request_context("/inner"), m365_execution_context(context):
                empty = cards.get_request_pending_action_references()
                cards.record_pending_action_reference(action(context, "inner-only"))
                inner = cards.get_request_pending_action_references()
            outer = cards.get_request_pending_action_references()
    with web.test_request_context("/next"), m365_execution_context(context):
        next_request = cards.get_request_pending_action_references()
    assert empty == next_request == []
    assert [reference["id"] for reference in inner] == ["inner-only"]
    assert [reference["id"] for reference in outer] == ["pending-one"]
    assert [reference["id"] for reference in seen] == ["pending-one"]


def test_flask_references_survive_real_sync_async_stream_context_copies(context):
    loop = asyncio.new_event_loop()
    seen = []

    async def producer():
        cards.record_pending_action_reference(action(context))
        yield "first"
        cards.record_pending_action_reference(action(context, "pending-two"))
        yield "second"

    try:
        with Flask(__name__).test_request_context(), m365_execution_context(context):
            with cards.m365_action_card_events(seen.append), SyncAsyncStream(producer(), loop) as stream:
                content = list(stream)
            references = cards.get_request_pending_action_references()
            projected = cards.attach_pending_action_references({"conversation_id": context.conversation_id})
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
    assert content == ["first", "second"]
    assert [reference["id"] for reference in references] == ["pending-one", "pending-two"]
    assert projected["metadata"]["m365_pending_action_ids"] == ["pending-one", "pending-two"]
    assert len(seen) == 2


def test_interleaved_non_http_tasks_have_independent_callback_scopes(context):
    async def execute(label):
        scoped = replace(context, request_id=label)
        seen = []
        with m365_execution_context(scoped), cards.m365_action_card_events(seen.append):
            cards.record_pending_action_reference(action(scoped, label))
            await asyncio.sleep(0)
            references = cards.get_request_pending_action_references()
        return references, seen

    async def run():
        return await asyncio.gather(execute("first"), execute("second"))

    results = asyncio.run(run())
    outside = cards.get_request_pending_action_references()
    for label, (references, seen) in zip(("first", "second"), results):
        assert [reference["id"] for reference in references] == [label]
        assert seen == references
    assert outside == []


@pytest.mark.parametrize("fail", [False, True])
def test_stream_close_and_error_reset_callbacks_in_the_creating_context(context, fail):
    loop = asyncio.new_event_loop()
    seen = []

    async def source():
        with cards.m365_action_card_events(seen.append):
            cards.record_pending_action_reference(action(context))
            yield "first"
            if fail:
                raise RuntimeError("model failed after the pending action was saved")
            yield "second"

    try:
        with Flask(__name__).test_request_context(), m365_execution_context(context):
            with SyncAsyncStream(source(), loop) as stream:
                first = next(stream)
                if fail:
                    with pytest.raises(RuntimeError, match="model failed"):
                        next(stream)
            after = cards._event_subscription.get()
            references = cards.get_request_pending_action_references()
            cards.record_pending_action_reference(action(context, "after-close"))
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
    assert first == "first" and after is None
    assert [reference["id"] for reference in references] == ["pending-one"]
    assert len(seen) == 1


def test_closed_subscription_is_inactive_even_in_an_already_copied_context(context):
    seen = []
    with m365_execution_context(context):
        with cards.m365_action_card_events(seen.append):
            inherited = copy_context()
        inherited.run(cards.record_pending_action_reference, action(context))
        references = cards.get_request_pending_action_references()
    assert seen == []
    assert [reference["id"] for reference in references] == ["pending-one"]


def test_nested_event_scopes_restore_the_outer_callback(context):
    outer, inner = [], []
    with Flask(__name__).test_request_context(), m365_execution_context(context):
        with cards.m365_action_card_events(outer.append):
            with cards.m365_action_card_events(inner.append):
                cards.record_pending_action_reference(action(context, "inner"))
            cards.record_pending_action_reference(action(context, "outer"))
        after = cards._event_subscription.get()
    assert [reference["id"] for reference in outer] == ["outer"]
    assert [reference["id"] for reference in inner] == ["inner"]
    assert after is None


@pytest.mark.parametrize("optimized", [False, True])
def test_reference_primitives_cold_import_without_runtime_owners(optimized):
    probe = r'''
import builtins
import socket
import sys
from unittest.mock import patch

sys.path.insert(0, sys.argv[1])
original = builtins.__import__
forbidden = {
    "config", "functions_settings", "functions_appinsights",
    "functions_msgraph_pending_actions", "functions_m365_runtime",
}

def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    if level == 0 and name in forbidden:
        raise AssertionError("A reference primitive imported its runtime owner: " + name)
    return original(name, globals, locals, fromlist, level)

def no_network(*args, **kwargs):
    raise AssertionError("A reference primitive attempted network access.")

with patch.object(builtins, "__import__", guarded_import), patch.object(socket.socket, "connect", no_network):
    import functions_m365_action_cards as cards
    from functions_m365_context import M365ExecutionContext, m365_execution_context
    context = M365ExecutionContext("owner", "owner", "tenant", conversation_id="conversation", request_id="request")
    seen = []
    with m365_execution_context(context), cards.m365_action_card_events(seen.append):
        cards.record_pending_action_reference({
            "id": "pending", "user_id": "owner", "conversation_id": "conversation", "request_id": "request",
        })
        message = cards.attach_pending_action_references({"conversation_id": "conversation"})
        references = cards.get_request_pending_action_references()
    if len(seen) != 1 or seen != references or message["metadata"]["m365_pending_action_ids"] != ["pending"]:
        raise AssertionError("Reference transport failed before runtime bootstrap.")
    logged = []
    with m365_execution_context(context):
        rejected = cards.record_pending_action_reference(
            {"id": "invalid", "user_id": "another-owner", "conversation_id": "conversation", "request_id": "request"},
            log_event=lambda *args, **kwargs: logged.append(kwargs),
        )
    if rejected is not None or len(logged) != 1:
        raise AssertionError("Reference failure did not use its injected runtime logger.")
    if any(name in sys.modules for name in forbidden):
        raise AssertionError("Reference transport loaded its runtime owner.")
'''
    command = [sys.executable, "-B"]
    if optimized:
        command.append("-O")
    result = subprocess.run(command + ["-c", probe, str(APP)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


if __name__ == "__main__":
    sys.exit(pytest.main([str(Path(__file__).resolve())]))
