# functions_group_insights.py
"""Native group insights: the activity feed, the statistics and the document count.

This backs ``GET /api/groups/<group_id>/insights/activity``, ``/insights/stats`` and
``/insights/file-count`` (``route_backend_group_settings``). The classic
``/api/groups/<group_id>/activity``, ``/stats`` and ``/fileCount`` are separate and
unchanged here. Access follows ``group_settings_decisions``: the owner or an admin
reads the activity and the statistics, and the owner reads the document count, in
every group status.

Activity
--------
The feed reads the records the classic feed reads (those whose
``workspace_context.group_id`` names the group, newest first) but selects only the
aliased fields its projection needs, so no other part of a record leaves Cosmos.
Each record becomes ``{id, occurred_at, type, summary, actor}``:

- ``type`` is one of ``ACTIVITY_TYPES``, or ``other``;
- ``summary`` is a reviewed sentence for that type. The only values it takes from a
  record are a token count and the group's old and new status, both drawn from fixed
  vocabularies. No name, title, file name, email, content, error text, model or
  conversation id appears;
- ``actor`` is ``{"kind": "member", "display_name": ...}`` for a current member of the
  group, named as the group document names them, ``{"kind": "former_member"}`` for
  anyone else, and ``{"kind": "system"}`` for work with no person behind it: an empty
  actor, the group's own id (a scheduled File Sync run falls back to it), or a
  status change made by someone outside the group, which only an administrator can do.

Membership, ownership and administrator records name the group elsewhere, so they
are not in this feed, as they are not in the classic one.

Statistics
----------
The statistics answer with the classic ``/stats`` figures, computed by the same
queries over the same window, apart from two changes: the invented ``storageLimit``
is gone, and a query that fails makes the whole response a 503 rather than a figure
of zero. The window is ``days`` (7, 30 or 90, 30 when neither form is given) or a
custom ``start_date`` and ``end_date`` of at most 366 days, between 2000-01-01 and
9998-12-31. A window that can't be used is a 400 before the group is read, so the 503
only ever means that storage failed.

The document count is the group's own current documents, counted as the group
document list shows them.
"""

import logging
import math
import re
from datetime import datetime, timezone

from flask import request

from config import cosmos_activity_logs_container
from functions_appinsights import log_event
from functions_group_directory import _require_user_id, current_session_roles
from functions_group_document_reads import count_current_group_documents
from functions_group_settings import (
    GroupSettingsError,
    _invalid,
    load_group_for_member,
    require_operation,
)
from functions_settings import get_settings
from functions_stats_windows import (
    ALLOWED_STATS_WINDOW_DAYS,
    STATS_MAX_CUSTOM_DAYS,
    build_stats_date_series,
    resolve_bounded_stats_time_window,
    stats_window_response_payload,
    timestamp_to_stats_date_key,
)


GROUP_ACTIVITY_LIMITS = (10, 20, 50)
GROUP_ACTIVITY_DEFAULT_LIMIT = 50
# The custom-span cap now lives in the shared bounded resolver; this alias records the
# group-facing name for the same value.
GROUP_STATS_MAX_CUSTOM_DAYS = STATS_MAX_CUSTOM_DAYS
GROUP_STATS_UNAVAILABLE_MESSAGE = "Group statistics are unavailable right now. Try again."
GROUP_ACTIVITY_UNAVAILABLE_MESSAGE = "Group activity is unavailable right now. Try again."
WHOLE_NUMBER = re.compile(r"[1-9][0-9]{0,5}")

# The activity query. Only these aliased fields are read.
GROUP_ACTIVITY_QUERY = (
    "SELECT TOP @limit a.id AS id, a.activity_type AS activity_type, a.timestamp AS timestamp, "
    "a.user_id AS user_id, a.changed_by.user_id AS changed_by_user_id, a.token_type AS token_type, "
    "a.usage.total_tokens AS total_tokens, a.status_change.old_status AS old_status, "
    "a.status_change.new_status AS new_status, a.action AS action "
    "FROM a WHERE a.workspace_context.group_id = @group_id ORDER BY a.timestamp DESC"
)

# The classic statistics queries, verbatim, so the figures are the classic ones.
GROUP_STATS_WINDOW_FILTER = """
            AND (
                (IS_DEFINED(a.timestamp) AND a.timestamp >= @startDate AND a.timestamp <= @endDate)
                OR (IS_DEFINED(a.created_at) AND a.created_at >= @startDate AND a.created_at <= @endDate)
            )"""
GROUP_STATS_TOKEN_TOTAL_QUERY = (
    "SELECT a.usage FROM a WHERE a.workspace_context.group_id = @groupId"
    + GROUP_STATS_WINDOW_FILTER + " AND a.activity_type = 'token_usage'"
)
GROUP_STATS_UPLOAD_QUERY = (
    "SELECT a.timestamp, a.created_at FROM a WHERE a.workspace_context.group_id = @groupId"
    + GROUP_STATS_WINDOW_FILTER + " AND a.activity_type = 'document_creation'"
)
GROUP_STATS_DELETE_QUERY = (
    "SELECT a.timestamp, a.created_at FROM a WHERE a.workspace_context.group_id = @groupId"
    + GROUP_STATS_WINDOW_FILTER + " AND a.activity_type = 'document_deletion'"
)
GROUP_STATS_TOKEN_SERIES_QUERY = (
    "SELECT a.timestamp, a.created_at, a.usage FROM a WHERE a.workspace_context.group_id = @groupId"
    + GROUP_STATS_WINDOW_FILTER + " AND a.activity_type = 'token_usage'"
)

GROUP_STATUS_LABELS = {
    "active": "Active",
    "locked": "Locked",
    "upload_disabled": "Uploads disabled",
    "inactive": "Inactive",
}
FILE_SYNC_SUMMARIES = {
    "source_created": "Added a File Sync source",
    "source_updated": "Updated a File Sync source",
    "source_deleted": "Removed a File Sync source",
    "run_completed": "File Sync finished",
    "run_failed": "File Sync failed",
}
ACTIVITY_SUMMARIES = {
    "document_creation": "Uploaded a document",
    "document_deletion": "Deleted a document",
    "document_metadata_update": "Updated a document's details",
    "conversation_creation": "Started a conversation",
    "conversation_deletion": "Deleted a conversation",
    "conversation_archival": "Archived a conversation",
    "agent_creation": "Created an agent",
    "agent_update": "Updated an agent",
    "agent_deletion": "Deleted an agent",
    "agent_run": "Ran an agent",
    "action_creation": "Created an action",
    "action_update": "Updated an action",
    "action_deletion": "Deleted an action",
    "workflow_creation": "Created a workflow",
    "workflow_update": "Updated a workflow",
    "workflow_deletion": "Deleted a workflow",
    "workflow_run": "Ran a workflow",
}
ACTIVITY_TYPES = (*ACTIVITY_SUMMARIES, "token_usage", "group_status_change", "file_sync")


def _refuse_unavailable(message, error_code):
    return GroupSettingsError(message, 503, error_code=error_code)


# ---------------------------------------------------------------------------
# Query parameters
# ---------------------------------------------------------------------------

def _single_arguments(allowed, message):
    for key in request.args.keys():
        if key not in allowed:
            raise _invalid(message)
        if len(request.args.getlist(key)) > 1:
            raise _invalid("Give each query parameter only once.")
    return request.args


def read_activity_limit():
    arguments = _single_arguments(("limit",), "Use only the limit query parameter.")
    raw = arguments.get("limit")
    if raw is None:
        return GROUP_ACTIVITY_DEFAULT_LIMIT
    if not WHOLE_NUMBER.fullmatch(raw) or int(raw) not in GROUP_ACTIVITY_LIMITS:
        raise _invalid("The limit must be 10, 20 or 50.")
    return int(raw)


def read_stats_window():
    """The window from ``days`` or ``start_date``/``end_date``, refused when malformed, out of range or too long.

    Every refusal is a reviewed 400 raised before the group is read.
    """
    arguments = _single_arguments(
        ("days", "start_date", "end_date"), "Use only the days, start_date and end_date query parameters.",
    )
    custom = "start_date" in arguments or "end_date" in arguments
    if custom and "days" in arguments:
        raise _invalid("Use days or a start_date and end_date, not both.")
    if custom:
        # The window helper reads empty dates as absent and falls back to its default window.
        for field in ("start_date", "end_date"):
            if not (arguments.get(field) or "").strip():
                raise _invalid(f"{field} is required.")
    if not custom and "days" in arguments:
        raw = arguments.get("days")
        if not WHOLE_NUMBER.fullmatch(raw) or int(raw) not in ALLOWED_STATS_WINDOW_DAYS:
            raise _invalid("The days must be 7, 30 or 90.")
    try:
        # The shared bounded resolver refuses a custom date outside 2000-01-01 to
        # 9998-12-31 (including one whose UTC offset carries it past the calendar's
        # edge) and a custom span longer than STATS_MAX_CUSTOM_DAYS days. The window
        # helpers' messages name only their own fields, formats and range.
        window = resolve_bounded_stats_time_window(arguments)
    except ValueError as error:
        raise _invalid(str(error)) from error
    return window


# ---------------------------------------------------------------------------
# Activity
# ---------------------------------------------------------------------------

def _whole_count(value):
    """A finite, non-negative token count as a whole number, or ``None`` for anything else."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return int(value) if value >= 0 else None


def activity_summary(record):
    """The reviewed sentence for one projected activity record."""
    activity_type = record.get("activity_type")
    if activity_type in ACTIVITY_SUMMARIES:
        return ACTIVITY_SUMMARIES[activity_type]
    if activity_type == "token_usage":
        count = _whole_count(record.get("total_tokens"))
        where = {"chat": " in chat", "embedding": " processing a document"}.get(record.get("token_type"), "")
        if count is None:
            return f"Used tokens{where}"
        return f"Used {count:,} {'token' if count == 1 else 'tokens'}{where}"
    if activity_type == "group_status_change":
        old = GROUP_STATUS_LABELS.get(record.get("old_status"))
        new = GROUP_STATUS_LABELS.get(record.get("new_status"))
        return f"Changed the group status from {old} to {new}" if old and new else "Changed the group status"
    if activity_type == "file_sync":
        return FILE_SYNC_SUMMARIES.get(record.get("action"), "File Sync activity")
    return "Other activity"


def _member_names(group):
    names = {}
    for entry in group.get("users") or []:
        if isinstance(entry, dict) and isinstance(entry.get("userId"), str) and entry["userId"]:
            display_name = entry.get("displayName")
            names[entry["userId"]] = display_name if isinstance(display_name, str) else ""
    owner = group.get("owner") if isinstance(group.get("owner"), dict) else {}
    if isinstance(owner.get("id"), str) and owner["id"]:
        display_name = owner.get("displayName")
        names[owner["id"]] = display_name if isinstance(display_name, str) else names.get(owner["id"], "")
    return names


def activity_actor(record, group, names):
    """Who a record says acted, as the group knows them."""
    status_change = record.get("activity_type") == "group_status_change"
    actor_id = record.get("changed_by_user_id") if status_change else record.get("user_id")
    if not isinstance(actor_id, str) or not actor_id or actor_id == group.get("id"):
        return {"kind": "system"}
    if actor_id in names:
        return {"kind": "member", "display_name": names[actor_id]}
    return {"kind": "system"} if status_change else {"kind": "former_member"}


def occurred_at(value):
    """A stored activity timestamp as UTC ISO 8601 with ``Z``, or ``None`` when unreadable."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(tzinfo=None).isoformat() + "Z"


def project_group_activity(records, group):
    names = _member_names(group)
    projected = []
    for record in records:
        if not isinstance(record, dict):
            continue
        activity_type = record.get("activity_type")
        projected.append({
            "id": record.get("id") if isinstance(record.get("id"), str) else None,
            "occurred_at": occurred_at(record.get("timestamp")),
            "type": activity_type if activity_type in ACTIVITY_TYPES else "other",
            "summary": activity_summary(record),
            "actor": activity_actor(record, group, names),
        })
    return projected


def read_group_activity(user_id, group_id):
    """Return ``({"activity": [...], "limit": n}, 200)`` for the owner or an admin."""
    user_id = _require_user_id(user_id)
    limit = read_activity_limit()
    group, role = load_group_for_member(user_id, group_id)
    require_operation(group, role, get_settings(), current_session_roles(), "view_activity")
    try:
        records = list(cosmos_activity_logs_container.query_items(
            query=GROUP_ACTIVITY_QUERY,
            parameters=[{"name": "@limit", "value": limit}, {"name": "@group_id", "value": group_id}],
            enable_cross_partition_query=True,
        ))
    except Exception as error:  # noqa: BLE001 - every storage failure is the same data-free 503
        log_event(
            "[WORKSPACE_ROUTE] Group activity read failed.",
            extra={"error_type": type(error).__name__},
            level=logging.ERROR,
        )
        raise _refuse_unavailable(GROUP_ACTIVITY_UNAVAILABLE_MESSAGE, "group_activity_unavailable") from error
    return {"activity": project_group_activity(records, group), "limit": limit}, 200


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def _usage_tokens(item):
    usage = item.get("usage") if isinstance(item, dict) else None
    count = _whole_count(usage.get("total_tokens")) if isinstance(usage, dict) else None
    return count or 0


def _stored_figure(metrics, key):
    value = metrics.get(key, 0)
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def _stats_date_key(timestamp):
    """A stored timestamp's day, or ``None`` when it can't be read.

    A timestamp whose UTC offset moves it past the calendar's first or last day can't
    be read either, and is left out of the series as any other unreadable timestamp is.
    """
    try:
        return timestamp_to_stats_date_key(timestamp)
    except (OverflowError, ValueError):
        return None


# The classic statistics queries, in the order the classic route sends them.
GROUP_STATS_QUERIES = (
    ("token_total", GROUP_STATS_TOKEN_TOTAL_QUERY),
    ("uploads", GROUP_STATS_UPLOAD_QUERY),
    ("deletes", GROUP_STATS_DELETE_QUERY),
    ("token_series", GROUP_STATS_TOKEN_SERIES_QUERY),
)


def read_group_stats_rows(group, window):
    """The rows each classic statistics query returns for ``group`` over ``window``.

    This is the only storage read behind the statistics, so any exception it raises is
    a storage failure.
    """
    parameters = [
        {"name": "@groupId", "value": group.get("id")},
        {"name": "@startDate", "value": window["start_date_iso"]},
        {"name": "@endDate", "value": window["end_date_iso"]},
    ]
    return {
        name: list(cosmos_activity_logs_container.query_items(
            query=text, parameters=[dict(parameter) for parameter in parameters], enable_cross_partition_query=True,
        ))
        for name, text in GROUP_STATS_QUERIES
    }


def build_group_stats(group, window, date_series, rows):
    """The classic figures for ``group`` from its statistics rows, without reading storage."""
    metrics = group.get("metrics") if isinstance(group.get("metrics"), dict) else {}
    document_metrics = metrics.get("document_metrics") if isinstance(metrics.get("document_metrics"), dict) else {}
    index_by_date = {day["date"]: index for index, day in enumerate(date_series)}
    labels = [day["label"] for day in date_series]
    uploads, deletes, tokens = [0] * len(date_series), [0] * len(date_series), [0] * len(date_series)

    def bucket(item):
        timestamp = item.get("timestamp") or item.get("created_at") if isinstance(item, dict) else None
        return index_by_date.get(_stats_date_key(timestamp)) if timestamp else None

    total_tokens = sum(_usage_tokens(item) for item in rows["token_total"])
    for item in rows["uploads"]:
        index = bucket(item)
        if index is not None:
            uploads[index] += 1
    for item in rows["deletes"]:
        index = bucket(item)
        if index is not None:
            deletes[index] += 1
    for item in rows["token_series"]:
        index = bucket(item)
        if index is not None:
            tokens[index] += _usage_tokens(item)

    users = group.get("users")
    storage_account_size = _stored_figure(document_metrics, "storage_account_size")
    return {
        "totalDocuments": _stored_figure(document_metrics, "total_documents"),
        "storageUsed": storage_account_size,
        "totalTokens": total_tokens,
        "totalMembers": len(users) if isinstance(users, list) else 0,
        "storage": {
            "ai_search_size": _stored_figure(document_metrics, "ai_search_size"),
            "storage_account_size": storage_account_size,
        },
        "documentActivity": {"labels": labels, "uploads": uploads, "deletes": deletes},
        "tokenUsage": {"labels": list(labels), "data": tokens},
        "dateRange": [day["date"] for day in date_series],
        "window": stats_window_response_payload(window),
    }


def read_group_stats(user_id, group_id):
    """Return ``({"stats": ...}, 200)`` for the owner or an admin."""
    user_id = _require_user_id(user_id)
    # Everything derived from the request is settled before the group is read, so a
    # window that can't be used is a 400 and never reaches the storage 503 below.
    window = read_stats_window()
    date_series = build_stats_date_series(window["start_date"], window["end_date"])
    group, role = load_group_for_member(user_id, group_id)
    require_operation(group, role, get_settings(), current_session_roles(), "view_stats")
    try:
        rows = read_group_stats_rows(group, window)
    except Exception as error:  # noqa: BLE001 - every storage failure is the same data-free 503
        log_event(
            "[WORKSPACE_ROUTE] Group statistics read failed.",
            extra={"error_type": type(error).__name__},
            level=logging.ERROR,
        )
        raise _refuse_unavailable(GROUP_STATS_UNAVAILABLE_MESSAGE, "group_stats_unavailable") from error
    return {"stats": build_group_stats(group, window, date_series, rows)}, 200


def read_group_file_count(user_id, group_id):
    """Return ``({"file_count": n}, 200)`` for the owner."""
    user_id = _require_user_id(user_id)
    _single_arguments((), "This request does not accept query parameters.")
    group, role = load_group_for_member(user_id, group_id)
    require_operation(group, role, get_settings(), current_session_roles(), "view_file_count")
    return {"file_count": count_current_group_documents(group_id)}, 200
