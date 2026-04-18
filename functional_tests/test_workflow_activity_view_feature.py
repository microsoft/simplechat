# test_workflow_activity_view_feature.py
#!/usr/bin/env python3
"""
Functional test for workflow activity view snapshot aggregation.
Version: 0.241.039
Implemented in: 0.241.039

This test ensures that workflow activity snapshots merge lifecycle events,
preserve branch lanes for tool calls, and fall back to a summary card for
legacy workflow runs without structured thought activity.
"""

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_ROOT = os.path.join(REPO_ROOT, "application", "single_app")
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

from functions_workflow_activity import build_workflow_activity_snapshot


RUN_ID = "run-123"
WORKFLOW_ID = "workflow-abc"
CONVERSATION_ID = "conversation-xyz"


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def test_activity_merging():
    print("Testing workflow activity merge behavior...")

    workflow = {
        "id": WORKFLOW_ID,
        "name": "Security Events",
        "runner_type": "agent",
        "conversation_id": CONVERSATION_ID,
    }
    conversation = {
        "id": CONVERSATION_ID,
        "title": "Workflow: Security Events",
        "chat_type": "workflow",
        "workflow_id": WORKFLOW_ID,
    }
    run_record = {
        "id": RUN_ID,
        "workflow_id": WORKFLOW_ID,
        "workflow_name": "Security Events",
        "conversation_id": CONVERSATION_ID,
        "assistant_message_id": "assistant-message-1",
        "status": "completed",
        "success": True,
        "started_at": "2025-01-01T00:00:00+00:00",
        "completed_at": "2025-01-01T00:00:04+00:00",
        "trigger_source": "manual",
        "response_preview": "Security events workflow completed.",
    }
    thoughts = [
        {
            "id": "thought-1",
            "step_index": 0,
            "step_type": "workflow",
            "content": "Workflow run started",
            "detail": "trigger_source=manual",
            "timestamp": "2025-01-01T00:00:00+00:00",
            "duration_ms": None,
            "activity": {
                "activity_key": f"run:{RUN_ID}",
                "workflow_id": WORKFLOW_ID,
                "run_id": RUN_ID,
                "kind": "workflow_run",
                "title": "Workflow run",
                "status": "running",
                "lane_key": "main",
                "lane_label": "Main",
            },
        },
        {
            "id": "thought-2",
            "step_index": 1,
            "step_type": "agent_tool_call",
            "content": "Invoking SecurityPlugin.fetch_events",
            "detail": "severity=high",
            "timestamp": "2025-01-01T00:00:01+00:00",
            "duration_ms": None,
            "activity": {
                "activity_key": "plugin-invocation-1",
                "workflow_id": WORKFLOW_ID,
                "run_id": RUN_ID,
                "kind": "tool_invocation",
                "title": "SecurityPlugin.fetch_events",
                "status": "running",
                "lane_key": "SecurityPlugin",
                "lane_label": "SecurityPlugin",
            },
        },
        {
            "id": "thought-3",
            "step_index": 2,
            "step_type": "agent_tool_call",
            "content": "Workflow agent executed SecurityPlugin.fetch_events (450ms)",
            "detail": "severity=high; success=True",
            "timestamp": "2025-01-01T00:00:02+00:00",
            "duration_ms": 450,
            "activity": {
                "activity_key": "plugin-invocation-1",
                "workflow_id": WORKFLOW_ID,
                "run_id": RUN_ID,
                "kind": "tool_invocation",
                "title": "SecurityPlugin.fetch_events",
                "status": "completed",
                "lane_key": "SecurityPlugin",
                "lane_label": "SecurityPlugin",
            },
        },
        {
            "id": "thought-4",
            "step_index": 3,
            "step_type": "workflow",
            "content": "Workflow run completed",
            "detail": "message_id=assistant-message-1",
            "timestamp": "2025-01-01T00:00:04+00:00",
            "duration_ms": None,
            "activity": {
                "activity_key": f"run:{RUN_ID}",
                "workflow_id": WORKFLOW_ID,
                "run_id": RUN_ID,
                "kind": "workflow_run",
                "title": "Workflow run",
                "status": "completed",
                "lane_key": "main",
                "lane_label": "Main",
            },
        },
    ]

    snapshot = build_workflow_activity_snapshot(
        run_record=run_record,
        workflow=workflow,
        conversation=conversation,
        thoughts=thoughts,
    )

    assert_equal(snapshot["live"], False, "snapshot live state")
    assert_equal(len(snapshot["activities"]), 2, "activity count")

    run_activity = next(activity for activity in snapshot["activities"] if activity["kind"] == "workflow_run")
    tool_activity = next(activity for activity in snapshot["activities"] if activity["kind"] == "tool_invocation")

    assert_equal(run_activity["status"], "completed", "workflow activity status")
    assert_equal(len(run_activity["events"]), 2, "workflow event count")
    assert_equal(tool_activity["status"], "completed", "tool activity status")
    assert_equal(len(tool_activity["events"]), 2, "tool event count")
    assert_equal(tool_activity["lane_index"], 1, "tool lane index")
    assert_equal(tool_activity["duration_ms"], 450, "tool duration")

    print("Workflow activity merge behavior passed.")
    return True


def test_legacy_run_fallback():
    print("Testing workflow activity fallback behavior...")

    snapshot = build_workflow_activity_snapshot(
        run_record={
            "id": "legacy-run-1",
            "workflow_id": WORKFLOW_ID,
            "workflow_name": "Security Events",
            "status": "failed",
            "success": False,
            "started_at": "2025-01-02T00:00:00+00:00",
            "completed_at": "2025-01-02T00:00:03+00:00",
            "error": "Workflow agent timed out.",
        },
        workflow={
            "id": WORKFLOW_ID,
            "name": "Security Events",
        },
        conversation={
            "id": CONVERSATION_ID,
            "title": "Workflow: Security Events",
        },
        thoughts=[],
    )

    assert_equal(len(snapshot["activities"]), 1, "fallback activity count")
    assert_equal(snapshot["activities"][0]["status"], "failed", "fallback activity status")
    assert_equal(snapshot["activities"][0]["summary"], "Workflow run summary", "fallback summary")

    print("Workflow activity fallback behavior passed.")
    return True


if __name__ == "__main__":
    tests = [test_activity_merging, test_legacy_run_fallback]
    results = []

    for test in tests:
        try:
            results.append(test())
        except Exception as exc:
            results.append(False)
            print(f"Test failed: {exc}")
            import traceback
            traceback.print_exc()

    success = all(results)
    print(f"Results: {sum(1 for result in results if result)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)
