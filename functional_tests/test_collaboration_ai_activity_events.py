#!/usr/bin/env python3
# test_collaboration_ai_activity_events.py
"""
Functional test for the agent activity events of a shared conversation.
Version: 0.261.255
Implemented in: 0.261.255

This test ensures that an AI request in a shared conversation tells every participant that it is
running, what it is doing and when it ends: `collaboration.ai.started` before the run,
`collaboration.ai.progress` with the latest step in plain words (never a plugin, function or model
name, an argument or a timing), and exactly one `collaboration.ai.finished` however the request
ends, including when the requester disconnects. Publishing failures must never break the answer.
"""

import ast
import logging
import os
import sys
import uuid

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_support.versioning import assert_app_version_at_least

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(ROOT_DIR, "application", "single_app")
ROUTE_PATH = os.path.join(APP_DIR, "route_backend_collaboration.py")
IMPLEMENTED_IN_VERSION = "0.261.255"
DEFINITIONS = {
    "AI_ACTIVITY_STEP_MAX_LENGTH",
    "AI_ACTIVITY_NAME_MAX_LENGTH",
    "_build_collaboration_event",
    "_describe_collaboration_ai_target",
    "CollaborationAiActivity",
}


def read_route_source():
    with open(ROUTE_PATH, "r", encoding="utf-8") as file_handle:
        return file_handle.read()


def load_activity_definitions(logged):
    """Compile just the activity definitions, since the route module needs live Azure clients."""
    module_ast = ast.parse(read_route_source())
    nodes = []
    for node in module_ast.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in DEFINITIONS:
            nodes.append(node)
        elif isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id in DEFINITIONS for target in node.targets
        ):
            nodes.append(node)
    found = {
        getattr(node, "name", None) or node.targets[0].id
        for node in nodes
    }
    assert found == DEFINITIONS, f"missing definitions: {sorted(DEFINITIONS - found)}"

    namespace = {
        "uuid": uuid,
        "logging": logging,
        "utc_now_iso": lambda: "2026-05-01T12:00:00.000000+00:00",
        "log_event": lambda message, **kwargs: logged.append(message),
        "COLLABORATION_EVENT_REGISTRY": None,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), ROUTE_PATH, "exec"), namespace)
    return namespace


def test_a_run_is_bracketed_and_reports_its_latest_step():
    print("Testing the activity event lifecycle...")
    logged = []
    namespace = load_activity_definitions(logged)
    published = []
    activity = namespace["CollaborationAiActivity"](
        "conv-1",
        "Watch Officer",
        "agent",
        requested_by={"user_id": "u-sam", "display_name": "Sam Lee", "email": "sam@example.com"},
        request_message_id="msg-7",
        publish=lambda conversation_id, event: published.append((conversation_id, event)),
    )

    activity.started()
    activity.step("Calling   BorderEntryRecords.search")
    activity.step("Calling BorderEntryRecords.search")
    activity.step("")
    activity.step("x" * 400)
    activity.status = "completed"
    activity.finished()
    activity.finished()
    activity.step("after the end")

    kinds = [event["event_type"] for _, event in published]
    assert kinds == [
        "collaboration.ai.started",
        "collaboration.ai.progress",
        "collaboration.ai.progress",
        "collaboration.ai.finished",
    ], kinds
    assert all(conversation_id == "conv-1" for conversation_id, _ in published)

    started = published[0][1]["payload"]["run"]
    assert started["display_name"] == "Watch Officer"
    assert started["target_type"] == "agent"
    assert started["requested_by"] == {"user_id": "u-sam", "display_name": "Sam Lee"}, (
        "only the requester's id and name are broadcast"
    )
    assert started["request_message_id"] == "msg-7"
    assert started["started_at"]
    run_id = started["run_id"]
    assert len(run_id) == 32

    first_step = published[1][1]["payload"]["run"]
    assert first_step == {"run_id": run_id, "step": "Calling BorderEntryRecords.search"}, first_step
    assert len(published[2][1]["payload"]["run"]["step"]) == namespace["AI_ACTIVITY_STEP_MAX_LENGTH"]
    assert published[3][1]["payload"]["run"] == {"run_id": run_id, "status": "completed"}
    assert not logged
    print("  ok  started, deduplicated steps, one finished")


def test_publishing_failures_never_raise():
    print("Testing that activity publishing is advisory...")
    logged = []
    namespace = load_activity_definitions(logged)

    def broken_publish(conversation_id, event):
        raise RuntimeError("cache unavailable")

    activity = namespace["CollaborationAiActivity"](
        "conv-1", "Watch Officer", "agent", requested_by=None, request_message_id=None, publish=broken_publish,
    )
    activity.started()
    activity.step("Working")
    activity.finished()
    assert activity.status == "failed", "a run that never completed is reported as failed"
    assert len(logged) == 3 and all("Could not publish" in message for message in logged), logged
    print("  ok  failures are logged, not raised")


def test_target_description():
    print("Testing how the asked target is named...")
    namespace = load_activity_definitions([])
    describe = namespace["_describe_collaboration_ai_target"]
    assert describe({"display_name": "Watch Officer", "target_type": "agent"}, None) == ("Watch Officer", "agent")
    assert describe({"display_name": "gpt-6", "target_type": "MODEL"}, None) == ("gpt-6", "model")
    assert describe({"display_name": "Image", "target_type": "image"}, None) == ("Image", "image")
    assert describe({"display_name": "Odd", "target_type": "spaceship"}, None) == ("Odd", "model")
    assert describe(None, {"display_name": "Response Cell Officer"}) == ("Response Cell Officer", "agent")
    assert describe(None, None) == ("Assistant", "model")
    assert describe({"display_name": "n" * 300}, None)[0] == "n" * namespace["AI_ACTIVITY_NAME_MAX_LENGTH"]
    print("  ok  names and kinds are normalised")


def _find_function(node, name):
    for child in ast.walk(node):
        if isinstance(child, ast.FunctionDef) and child.name == name:
            return child
    return None


def test_the_stream_route_brackets_every_request():
    print("Testing the stream route wiring...")
    module_ast = ast.parse(read_route_source())
    generators = [
        node for node in ast.walk(module_ast)
        if isinstance(node, ast.FunctionDef) and node.name == "generate_stream"
        and "ai_activity" in ast.unparse(node)
    ]
    assert len(generators) == 1, "the collaboration AI stream must report its activity"
    generate_stream = generators[0]

    first = ast.unparse(generate_stream.body[0])
    assert first == "ai_activity.started()", f"the run must be announced first, found: {first}"
    try_nodes = [node for node in generate_stream.body if isinstance(node, ast.Try)]
    assert len(try_nodes) == 1 and try_nodes[0].finalbody, "the run must end in a finally block"
    assert ast.unparse(try_nodes[0].finalbody[-1]) == "ai_activity.finished()"

    transform = _find_function(generate_stream, "transform_event_block")
    assert transform is not None
    transform_source = ast.unparse(transform)
    assert "ai_activity.step(describe_ai_activity_step(stream_payload))" in transform_source, (
        "every stream event is described in plain words before it is broadcast"
    )
    assert "ai_activity.status = 'cancelled'" in transform_source
    assert "ai_activity.status = 'completed'" in transform_source
    print("  ok  started first, finished in finally, steps described in plain words")


def _tool(status, function_name, plugin_name="OpenApiPlugin", target=None):
    activity = {"kind": "tool_invocation", "status": status, "plugin_name": plugin_name,
                "function_name": function_name}
    if target:
        activity["delegation"] = {"target_label": target}
    return {"type": "thought", "step_type": "agent_tool_call",
            "content": f"Invoking {plugin_name}.{function_name}", "activity": activity}


def _thought(step_type, content):
    return {"type": "thought", "step_type": step_type, "content": content}


def test_steps_are_described_in_plain_words():
    print("Testing the plain-language steps...")
    sys.path.insert(0, APP_DIR)
    try:
        from functions_collaboration_ai_activity import describe_ai_activity_step, describe_function_name
    finally:
        sys.path.remove(APP_DIR)

    cases = [
        (_thought("history_context", "Prepared 9 model history messages from 9 stored messages"), "Reading the conversation"),
        (_thought("agent_tool_call", "Sending to agent 'Data Analyst'"), "Getting started"),
        (_thought("generation", "Sending to 'gpt-4o'"), "Thinking"),
        (_tool("running", "getOrderStatus"), "Looking up order status"),
        (_tool("running", "listInvoices"), "Reviewing invoices"),
        (_tool("running", "search_documents", "DocumentSearchPlugin"), "Searching documents"),
        (_tool("running", "add_to_map", "SharedMapPlugin"), "Updating the map"),
        (_tool("running", "upload_word_document", "SimpleChatPlugin"), "Saving Word document"),
        (_tool("completed", "getOrderStatus"), "Reviewing what it found"),
        (_tool("failed", "getOrderStatus"), ""),
        (_tool("running", "call", "AgentPlugin", target="Data Analyst"), "Asking Data Analyst"),
        (_tool("completed", "call", "AgentPlugin", target="Data Analyst"), "Reviewing Data Analyst's reply"),
        (_tool("running", "call", "AgentPlugin"), "Asking another agent"),
        (_thought("web_search", "Searching the web for 'weather forecast'"), "Searching the web"),
        (_thought("generation", 'Generating image based on "a bridge"'), "Creating the image"),
        ({"content": "The truck stopped at"}, "Writing the answer"),
        (_thought("generation", "'gpt-4o' responded (56.4s from initial message)"), "Finishing up"),
    ]
    for payload, expected in cases:
        described = describe_ai_activity_step(payload)
        assert described == expected, (payload, described)
        for technical in ("Plugin", "gpt-", "ms)", "kwargs", "_", "="):
            assert technical not in described, (payload, described)

    for payload in ({"content": "   "}, {"done": True, "full_content": "x"}, {"error": "boom"},
                    {"type": "m365_pending_action"}, _thought("mystery", "x"), None, "text"):
        assert describe_ai_activity_step(payload) == "", payload

    assert describe_function_name("getHTMLReport") == "Looking up HTML report"
    assert describe_function_name("orderStatus") == "Using order status"
    assert describe_function_name("") == ""
    print("  ok  thoughts, tool calls and answer text read as plain words")


def test_a_run_reads_as_plain_progress():
    print("Testing a described run end to end...")
    namespace = load_activity_definitions([])
    sys.path.insert(0, APP_DIR)
    try:
        from functions_collaboration_ai_activity import describe_ai_activity_step
    finally:
        sys.path.remove(APP_DIR)
    published = []
    activity = namespace["CollaborationAiActivity"](
        "conv-1", "Logistics Analyst", "agent", requested_by=None, request_message_id="m-1",
        publish=lambda conversation_id, event: published.append(event),
    )
    for payload in (
        _thought("history_context", "Prepared 9 model history messages"),
        _thought("generation", "Sending to 'gpt-4o'"),
        _tool("running", "getOrderStatus"),
        _tool("completed", "getOrderStatus"),
        _tool("completed", "getShipment"),
        {"content": "The truck"},
        {"content": " stopped"},
        _thought("generation", "'gpt-4o' responded (56.4s from initial message)"),
        {"done": True},
    ):
        activity.step(describe_ai_activity_step(payload))
    steps = [event["payload"]["run"]["step"] for event in published]
    assert steps == [
        "Reading the conversation",
        "Thinking",
        "Looking up order status",
        "Reviewing what it found",
        "Writing the answer",
        "Finishing up",
    ], steps
    print("  ok  one plain step per change, none repeated")


if __name__ == "__main__":
    assert_app_version_at_least(IMPLEMENTED_IN_VERSION)
    tests = [
        test_a_run_is_bracketed_and_reports_its_latest_step,
        test_publishing_failures_never_raise,
        test_target_description,
        test_the_stream_route_brackets_every_request,
        test_steps_are_described_in_plain_words,
        test_a_run_reads_as_plain_progress,
    ]
    for test in tests:
        test()
    print(f"\n{len(tests)} activity event checks passed")
