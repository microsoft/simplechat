# v2_workflow_activity_stubs.py
"""
Workflow-activity snapshots and event-stream bodies for the V2 Workflow Activity page's browser tests.
Version: 0.261.448
Implemented in: 0.261.448

The page reads one snapshot object from `GET /api/{user|group}/workflows/activity` and the same
object again, whole, on every frame of the stream beside it. The snapshots here are built by the
server's own `build_workflow_activity_snapshot` from thoughts and pending actions shaped as the
server stores them, so a test reads what the server writes and not a description of it. Nothing
here reaches the network, a database or a model.
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2] / "application" / "single_app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from functions_workflow_activity import build_workflow_activity_snapshot  # noqa: E402

ACTIVITY_PATH = "/api/user/workflows/activity"
GROUP_ACTIVITY_PATH = "/api/group/workflows/activity"
STREAM_SUFFIX = "/stream"

WORKFLOW_ID = "wf-weekly"
CONVERSATION_ID = "conv-weekly"
RUN_ID = "run-1234567890"
GROUP_ID = "grp-1"
WORKFLOW_NAME = "Weekly security digest"
RUNNER = "Security Agent"
RESPONSE_PREVIEW = "Security events workflow completed with two findings."

START = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
# The lanes tool calls are dealt into, in turn: one sub-lane per plugin, beside the workflow's own.
TOOL_LANES = ("SecurityPlugin", "ReportPlugin")
TOOL_NAMES = ("fetch_events", "compile_report")

# Written into a field the page draws as text, to prove it is never read as markup.
XSS_TEXT = '<img src=x onerror="window.__xss=1"><b>bold</b>'


def stamp(seconds):
    return (START + timedelta(seconds=seconds)).isoformat()


def _thought(thought_id, index, step_type, content, detail, seconds, duration, activity):
    return {
        "id": thought_id,
        "step_index": index,
        "step_type": step_type,
        "content": content,
        "detail": detail,
        "timestamp": stamp(seconds),
        "duration_ms": duration,
        "activity": activity,
    }


def _activity(key, kind, title, status, lane_key, lane_label, run_id, workflow_id):
    return {
        "activity_key": key,
        "workflow_id": workflow_id,
        "run_id": run_id,
        "kind": kind,
        "title": title,
        "status": status,
        "lane_key": lane_key,
        "lane_label": lane_label,
    }


def pending_action(action_id="pending-mail-1", *, run_id=RUN_ID, workflow_id=WORKFLOW_ID, status="pending", **overrides):
    """A saved outgoing email, in the shape the V2 card reads it."""
    action = {
        "type": "msgraph_pending_action",
        "id": action_id,
        "version": "v1",
        "status": status,
        "operation": "send_mail",
        "graph_resource_type": "mail",
        "action_mode": "manual",
        "subject": "Weekly security digest",
        "summary": {
            "subject": "Weekly security digest",
            "body_preview": "Two high-severity findings need a look.",
            "body_preview_truncated": False,
            "to_recipients": ["ops@example.com"],
        },
        "workflow_id": workflow_id,
        "run_id": run_id,
        "conversation_id": CONVERSATION_ID,
        "can_cancel": status == "pending",
        "can_send_now": status == "pending",
        "viewer_is_owner": True,
        "review_details_required": False,
        "created_at": stamp(5),
        "updated_at": stamp(5),
    }
    action.update(overrides)
    return action


def run_snapshot(
    *,
    status="completed",
    finished_tools=2,
    running_tools=0,
    run_id=RUN_ID,
    workflow_id=WORKFLOW_ID,
    conversation_id=CONVERSATION_ID,
    workflow_name=WORKFLOW_NAME,
    runner=RUNNER,
    response_preview=RESPONSE_PREVIEW,
    error=None,
    task_results=None,
    pending_actions=None,
    tool_detail="severity=high",
):
    """A snapshot as the server builds it: the run, its tool calls (some finished, some running)."""
    run = {
        "id": run_id,
        "workflow_id": workflow_id,
        "workflow_name": workflow_name,
        "conversation_id": conversation_id,
        "status": status,
        "success": status == "completed",
        "started_at": stamp(0),
        "trigger_source": "manual",
        "agent_display_name": runner,
        "response_preview": response_preview,
    }
    if error:
        run["error"] = error
    if task_results is not None:
        run["task_results"] = task_results

    def run_activity(state):
        return _activity(f"run:{run_id}", "workflow_run", "Workflow run", state, "main", "Main", run_id, workflow_id)

    index = 0
    thoughts = [
        _thought(
            f"{run_id}-start", index, "workflow", "Workflow run started", "trigger_source=manual", 0, None,
            run_activity("running"),
        )
    ]
    seconds = 1
    for tool in range(finished_tools + running_tools):
        lane = TOOL_LANES[tool % len(TOOL_LANES)]
        title = f"{lane}.{TOOL_NAMES[tool % len(TOOL_NAMES)]}"
        key = f"tool-{run_id}-{tool}"
        index += 1
        thoughts.append(_thought(
            f"{key}-start", index, "agent_tool_call", f"Invoking {title}", tool_detail, seconds, None,
            _activity(key, "tool_invocation", title, "running", lane, lane, run_id, workflow_id),
        ))
        seconds += 1
        if tool < finished_tools:
            index += 1
            thoughts.append(_thought(
                f"{key}-done", index, "agent_tool_call", f"Workflow agent executed {title} (450ms)",
                f"{tool_detail}; success=True", seconds, 450,
                _activity(key, "tool_invocation", title, "completed", lane, lane, run_id, workflow_id),
            ))
            seconds += 1
    if status in {"completed", "failed", "cancelled"}:
        index += 1
        thoughts.append(_thought(
            f"{run_id}-end", index, "workflow", f"Workflow run {status}", "message_id=assistant-message-1", seconds, None,
            run_activity(status),
        ))

    snapshot = build_workflow_activity_snapshot(
        run_record=run,
        workflow={"id": workflow_id, "name": workflow_name, "runner_type": "agent", "conversation_id": conversation_id},
        conversation={
            "id": conversation_id, "title": f"Workflow: {workflow_name}", "chat_type": "workflow",
            "workflow_id": workflow_id,
        },
        thoughts=thoughts,
        pending_actions=pending_actions,
    )
    # Exactly what a client receives: JSON, with every value already text or a number.
    return json.loads(json.dumps(snapshot, default=str))


def many_tools_snapshot(count=14, **kwargs):
    """A long run whose timeline is taller than the panel it scrolls in."""
    return run_snapshot(finished_tools=count, **kwargs)


def conversation_only_snapshot(conversation_id=CONVERSATION_ID, workflow_name=WORKFLOW_NAME):
    """What the server answers for a workflow's conversation that has no run on record yet."""
    snapshot = build_workflow_activity_snapshot(
        conversation={
            "id": conversation_id, "title": f"Workflow: {workflow_name}", "chat_type": "workflow",
            "workflow_id": WORKFLOW_ID,
        },
    )
    return json.loads(json.dumps(snapshot, default=str))


def event_stream(*snapshots, retry_ms=100):
    """The body of one stream connection: a retry hint, then each snapshot as a `data:` message."""
    frames = "".join(f"data: {json.dumps(snapshot)}\n\n" for snapshot in snapshots)
    return f"retry: {retry_ms}\n\n{frames}"


def stream_refusal():
    """What the server's stream sends, and then ends with, when the run is no longer readable."""
    return 'event: error\ndata: {"error":"Workflow activity is no longer available.","code":"activity_unavailable"}\n\n'
