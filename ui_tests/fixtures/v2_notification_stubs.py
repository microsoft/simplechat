# v2_notification_stubs.py
"""
The notification requests every real V2 page makes, answered the way the real routes answer.
Version: 0.261.199
Implemented in: 0.261.195

The V2 rail's bell reads the unread count as soon as the signed-in session loads, and again
whenever the tab comes back into view. A chat reply the reader watched finish is marked read,
because the server marks a personal conversation unread as it finishes a reply. Closed-API
fixtures that serve the built SPA answer both with these helpers, as a user with nothing
unread would see them, so a suite about something else is not failed by the bell.

Workflow alerts that pop up (Track N2, 0.261.199) are read from their own route only when that
count is above zero, so a fixture answering a zero count never sees that request. A suite that
does pop alerts up builds them with `workflow_alert_document`, shaped the way the workflow
runner writes them and the route returns them.
"""

import re


NOTIFICATION_COUNT_PATH = "/api/notifications/count"
CONVERSATION_MARK_READ_PATH = re.compile(r"/api/conversations/([^/]+)/mark-read")
WORKFLOW_ALERTS_PATH = "/api/notifications/workflow-alerts"
WORKFLOW_ALERT_NOTIFICATION_TYPE = "workflow_priority_alert"

# WORKFLOW_ALERT_PRIORITY_CONFIG in functions_notifications.py, and the failed-run icon.
WORKFLOW_ALERT_TYPE_CONFIG = {
    "info": {"icon": "bi-info-circle", "color": "info"},
    "low": {"icon": "bi-bell", "color": "info"},
    "medium": {"icon": "bi-exclamation-circle", "color": "warning"},
    "high": {"icon": "bi-exclamation-triangle", "color": "danger"},
    "critical": {"icon": "bi-exclamation-octagon", "color": "danger"},
}
WORKFLOW_ALERT_FAILURE_ICON = "bi-x-octagon"


def notification_count_payload(count=0):
    """The answer of route_backend_notifications.api_get_notification_count."""
    return {
        "success": True,
        "count": count,
        "chat_completion_audio_enabled": False,
        "chat_completion_audio_updated_at": None,
    }


def conversation_mark_read_payload(conversation_id):
    """The answer of route_backend_conversations.mark_conversation_read_api."""
    return {
        "success": True,
        "conversation_id": conversation_id,
        "has_unread_assistant_response": False,
        "notifications_marked_read": 0,
        "conversation_state_changed": True,
    }


def is_notification_count(method, path):
    return method == "GET" and path == NOTIFICATION_COUNT_PATH


def mark_read_conversation(method, path):
    """The conversation a personal mark-read request names, or None for any other request."""
    if method != "POST":
        return None
    match = CONVERSATION_MARK_READ_PATH.fullmatch(path)
    return match.group(1) if match else None


def is_workflow_alerts(method, path):
    return method == "GET" and path == WORKFLOW_ALERTS_PATH


def workflow_alerts_payload(notifications):
    """The answer of route_backend_notifications.api_get_workflow_alert_notifications."""
    return {"success": True, "notifications": list(notifications)}


def workflow_alert_conversation_target(conversation_id, *, label="Open workflow", group_id=None):
    """A link target as the runner builds one for the conversation a workflow posted into."""
    context = {
        "workspace_type": "group" if group_id else "personal",
        "conversation_id": conversation_id,
        "chat_type": "group" if group_id else "personal",
    }
    if group_id:
        context["group_id"] = group_id
    return {
        "label": label,
        "link_url": f"/chats?conversationId={conversation_id}",
        "link_context": context,
        "conversation_id": conversation_id,
    }


def workflow_alert_document(notification_id, *, created_at, user_id="user-1", workflow_id="wf-nightly",
                            workflow_name="Nightly release readiness scan", scope="personal", group_id=None,
                            priority="high", category="alert", delivery="popup", run_id="run-1",
                            title="Release checklist has 3 blocking items", summary="", detail="", error="",
                            trigger_reason=None, matched_rules=None, enrichments=None, link_targets=None,
                            trigger_source="schedule", runner_type="agent", status=None,
                            is_read=False, is_dismissed=False):
    """
    A workflow alert as functions_workflow_runner writes it and the workflow-alerts route
    returns it: the runner's metadata, plus the fields the route adds at the top level.

    `scope` is "personal" or "group"; None leaves `workflow_scope` out, as alerts written
    before it existed do. `link_targets` defaults to the workflow's conversation.
    """
    rules = matched_rules if matched_rules is not None else [
        {
            "rule_id": "rule-1",
            "rule_name": "Blocking items found",
            "severity": priority,
            "condition_type": "response_contains",
            "reason": "The response mentions blocking items.",
        },
    ]
    if trigger_reason is None:
        names = ", ".join(rule["rule_name"] for rule in rules if rule.get("rule_name"))
        trigger_reason = f"{priority.upper()} alert triggered by: {names}" if names else f"{priority.upper()} alert triggered."
    targets = link_targets if link_targets is not None else [workflow_alert_conversation_target(f"conv-{workflow_id}")]
    primary = targets[0] if targets else {}
    summary = summary or f"{workflow_name} needs attention."
    metadata = {
        "workflow_id": workflow_id,
        "workflow_name": workflow_name,
        "workflow_scope": scope,
        "group_id": group_id if scope == "group" else None,
        "priority": priority,
        "category": category,
        "delivery": delivery,
        "alert_mode": "rules",
        "matched_rules": rules,
        "trigger_reason": trigger_reason,
        "trigger_source": trigger_source,
        "run_id": run_id,
        "runner_type": runner_type,
        "status": status or ("failed" if category == "failure" else "completed"),
        "conversation_id": primary.get("conversation_id", ""),
        "assistant_message_id": "",
        "response_preview": detail or summary,
        "error": error,
        "event_title": title,
        "alert_title": title,
        "alert_summary": summary,
        "alert_detail": detail,
        "alert_enrichments": list(enrichments or []),
        "link_targets": targets,
    }
    if scope is None:
        metadata.pop("workflow_scope")
        metadata.pop("group_id")
    type_config = dict(WORKFLOW_ALERT_TYPE_CONFIG.get(priority, WORKFLOW_ALERT_TYPE_CONFIG["medium"]))
    if category == "failure":
        type_config["icon"] = WORKFLOW_ALERT_FAILURE_ICON
    return {
        "id": notification_id,
        "user_id": user_id,
        "notification_type": WORKFLOW_ALERT_NOTIFICATION_TYPE,
        "title": f"{priority.capitalize()} priority workflow alert: {workflow_name}",
        "message": summary,
        "link_url": primary.get("link_url", ""),
        "link_context": primary.get("link_context", {}),
        "metadata": metadata,
        "created_at": created_at,
        "read_by": [user_id] if is_read else [],
        "dismissed_by": [user_id] if is_dismissed else [],
        "is_read": is_read,
        "is_dismissed": is_dismissed,
        "priority": priority,
        "category": category,
        "delivery": delivery,
        "type_config": type_config,
    }
