# functions_public_insights.py
"""Native public workspace insights: the activity feed and the statistics.

This backs ``GET /api/public-workspaces/<workspace_id>/insights/activity``,
``/insights/stats`` and ``/insights/file-count`` (``route_backend_public_settings``). The
classic ``/api/public_workspaces/<ws_id>/activity``, ``/stats`` and ``/fileCount`` are
separate and unchanged here. Access follows ``public_settings_decisions``: the owner or an
admin reads the activity, the owner, an admin or a document manager reads the statistics,
as the classic reads allow, and the owner reads the document count, in every workspace
status.

Activity
--------
The feed reads the records the classic feed reads (those whose
``workspace_context.public_workspace_id`` names the workspace, newest first) but selects
only the aliased fields its projection needs, so no other part of a record leaves
Cosmos. Each record becomes ``{id, occurred_at, type, summary, actor}``:

- ``type`` is one of ``ACTIVITY_TYPES``, or ``other``;
- ``summary`` is a reviewed sentence for that type. The only values it takes from a
  record are a token count and the workspace's old and new status, both drawn from fixed
  vocabularies. No name, title, file name, email, content, error text, model or
  conversation id appears;
- ``actor`` is ``{"kind": "member", "display_name": ...}`` for the workspace's owner, an
  admin or a document manager, named as the workspace document names them (an entry
  stored as a bare id has no name to show), ``{"kind": "non_member"}`` for anyone else,
  and ``{"kind": "system"}`` for work with no person behind it: an empty actor, the
  workspace's own id (a scheduled File Sync run falls back to it), or a status change made
  by someone outside the workspace, which only an administrator can do. Every signed-in
  user can read a public workspace and chat with its documents, and chat usage is
  recorded against the caller's active public workspace, so a person outside the member
  lists is usually a reader who never held a role: ``non_member`` claims no more than that.

The public workspace records no membership or ownership events, and any record that
names the workspace elsewhere than ``workspace_context`` is not in this feed, as it is
not in the classic one. A read that fails is a 503, never an empty feed.

Statistics
----------
The statistics answer with the classic ``/stats`` figures, computed by the same queries
over the same window, apart from two changes: the invented ``storageLimit`` is gone, and
a query that fails makes the whole response a 503 rather than a figure of zero.
``totalMembers`` is the classic count: the owner, the admins and the document managers.
The window is ``days`` (7, 30 or 90, 30 when neither form is given) or a custom
``start_date`` and ``end_date`` of at most 366 days, between 2000-01-01 and 9998-12-31.
A window that can't be used is a 400 before the workspace is read, so the 503 only ever
means that storage failed.

Document count
--------------
The count is the workspace's current documents, counted as the public document list
shows them, for the Settings danger zone. The classic ``/fileCount``, which the classic
manage page checks before it offers to delete a workspace, counts every stored document
record instead, superseded revisions included.
"""

import logging
import math
import re
from datetime import datetime, timezone

from flask import request

from config import cosmos_activity_logs_container
from functions_appinsights import log_event
from functions_public_directory import _require_user_id
from functions_public_document_reads import count_current_public_documents
from functions_public_settings import (
    PublicSettingsError,
    _invalid,
    load_public_workspace,
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


PUBLIC_ACTIVITY_LIMITS = (10, 20, 50)
PUBLIC_ACTIVITY_DEFAULT_LIMIT = 50
# The custom-span cap lives in the shared bounded resolver; this alias records the
# public-facing name for the same value.
PUBLIC_STATS_MAX_CUSTOM_DAYS = STATS_MAX_CUSTOM_DAYS
PUBLIC_STATS_UNAVAILABLE_MESSAGE = "Workspace statistics are unavailable right now. Try again."
PUBLIC_ACTIVITY_UNAVAILABLE_MESSAGE = "Workspace activity is unavailable right now. Try again."
WHOLE_NUMBER = re.compile(r"[1-9][0-9]{0,5}")

# The activity query. Only these aliased fields are read.
PUBLIC_ACTIVITY_QUERY = (
    "SELECT TOP @limit a.id AS id, a.activity_type AS activity_type, a.timestamp AS timestamp, "
    "a.user_id AS user_id, a.changed_by.user_id AS changed_by_user_id, a.token_type AS token_type, "
    "a.usage.total_tokens AS total_tokens, a.status_change.old_status AS old_status, "
    "a.status_change.new_status AS new_status, a.action AS action "
    "FROM a WHERE a.workspace_context.public_workspace_id = @workspace_id ORDER BY a.timestamp DESC"
)

# The classic statistics queries, verbatim, so the figures are the classic ones.
PUBLIC_STATS_WINDOW_FILTER = """
            AND (
                (IS_DEFINED(a.timestamp) AND a.timestamp >= @startDate AND a.timestamp <= @endDate)
                OR (IS_DEFINED(a.created_at) AND a.created_at >= @startDate AND a.created_at <= @endDate)
            )"""
PUBLIC_STATS_TOKEN_TOTAL_QUERY = (
    "SELECT a.usage FROM a WHERE a.workspace_context.public_workspace_id = @wsId"
    + PUBLIC_STATS_WINDOW_FILTER + " AND a.activity_type = 'token_usage'"
)
PUBLIC_STATS_UPLOAD_QUERY = (
    "SELECT a.timestamp, a.created_at FROM a WHERE a.workspace_context.public_workspace_id = @wsId"
    + PUBLIC_STATS_WINDOW_FILTER + " AND a.activity_type = 'document_creation'"
)
PUBLIC_STATS_DELETE_QUERY = (
    "SELECT a.timestamp, a.created_at FROM a WHERE a.workspace_context.public_workspace_id = @wsId"
    + PUBLIC_STATS_WINDOW_FILTER + " AND a.activity_type = 'document_deletion'"
)
PUBLIC_STATS_TOKEN_SERIES_QUERY = (
    "SELECT a.timestamp, a.created_at, a.usage FROM a WHERE a.workspace_context.public_workspace_id = @wsId"
    + PUBLIC_STATS_WINDOW_FILTER + " AND a.activity_type = 'token_usage'"
)

PUBLIC_STATUS_LABELS = {
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
# The event types the application records with a public workspace context.
ACTIVITY_SUMMARIES = {
    "document_creation": "Uploaded a document",
    "document_deletion": "Deleted a document",
    "document_metadata_update": "Updated a document's details",
    "conversation_creation": "Started a conversation",
    "conversation_deletion": "Deleted a conversation",
    "conversation_archival": "Archived a conversation",
    "workflow_creation": "Created a workflow",
    "workflow_update": "Updated a workflow",
    "workflow_deletion": "Deleted a workflow",
    "workflow_run": "Ran a workflow",
}
ACTIVITY_TYPES = (*ACTIVITY_SUMMARIES, "token_usage", "public_workspace_status_change", "file_sync")


def _refuse_unavailable(message, error_code):
    return PublicSettingsError(message, 503, error_code=error_code)


def _log_storage_failure(message, error):
    extra = {"error_type": type(error).__name__}
    status_code = getattr(error, "status_code", None)
    if isinstance(status_code, int) and not isinstance(status_code, bool):
        extra["status_code"] = status_code
    log_event(message, extra=extra, level=logging.ERROR)


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
        return PUBLIC_ACTIVITY_DEFAULT_LIMIT
    if not WHOLE_NUMBER.fullmatch(raw) or int(raw) not in PUBLIC_ACTIVITY_LIMITS:
        raise _invalid("The limit must be 10, 20 or 50.")
    return int(raw)


def read_stats_window():
    """The window from ``days`` or ``start_date``/``end_date``, refused when malformed, out of range or too long.

    Every refusal is a reviewed 400 raised before the workspace is read.
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
    if activity_type == "public_workspace_status_change":
        old = PUBLIC_STATUS_LABELS.get(record.get("old_status"))
        new = PUBLIC_STATUS_LABELS.get(record.get("new_status"))
        return f"Changed the workspace status from {old} to {new}" if old and new else "Changed the workspace status"
    if activity_type == "file_sync":
        return FILE_SYNC_SUMMARIES.get(record.get("action"), "File Sync activity")
    return "Other activity"


def _member_names(workspace):
    """``{user_id: display name}`` for the owner, the admins and the document managers.

    An entry stored as a bare id has no name; a stored name wins over a bare id, and the
    owner's stored name wins over both.
    """
    names = {}
    for key in ("admins", "documentManagers"):
        entries = workspace.get(key)
        for entry in entries if isinstance(entries, list) else []:
            if isinstance(entry, str) and entry:
                names.setdefault(entry, "")
            elif isinstance(entry, dict) and isinstance(entry.get("userId"), str) and entry["userId"]:
                display_name = entry.get("displayName")
                if isinstance(display_name, str) and display_name:
                    names[entry["userId"]] = display_name
                else:
                    names.setdefault(entry["userId"], "")
    owner = workspace.get("owner") if isinstance(workspace.get("owner"), dict) else {}
    if isinstance(owner.get("userId"), str) and owner["userId"]:
        display_name = owner.get("displayName")
        names[owner["userId"]] = display_name if isinstance(display_name, str) else names.get(owner["userId"], "")
    return names


def activity_actor(record, workspace, names):
    """Who a record says acted, as the workspace knows them."""
    status_change = record.get("activity_type") == "public_workspace_status_change"
    actor_id = record.get("changed_by_user_id") if status_change else record.get("user_id")
    if not isinstance(actor_id, str) or not actor_id or actor_id == workspace.get("id"):
        return {"kind": "system"}
    if actor_id in names:
        return {"kind": "member", "display_name": names[actor_id]}
    return {"kind": "system"} if status_change else {"kind": "non_member"}


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
    try:
        return parsed.astimezone(timezone.utc).replace(tzinfo=None).isoformat() + "Z"
    except OverflowError:
        return None


def project_public_activity(records, workspace):
    names = _member_names(workspace)
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
            "actor": activity_actor(record, workspace, names),
        })
    return projected


def read_public_activity(user_id, workspace_id):
    """Return ``({"activity": [...], "limit": n}, 200)`` for the owner or an admin."""
    user_id = _require_user_id(user_id)
    limit = read_activity_limit()
    workspace, role = load_public_workspace(user_id, workspace_id)
    require_operation(workspace, role, get_settings(), "view_activity")
    try:
        records = list(cosmos_activity_logs_container.query_items(
            query=PUBLIC_ACTIVITY_QUERY,
            parameters=[{"name": "@limit", "value": limit}, {"name": "@workspace_id", "value": workspace_id}],
            enable_cross_partition_query=True,
        ))
    except Exception as error:  # noqa: BLE001 - every storage failure is the same data-free 503
        _log_storage_failure("[PUBLIC_SETTINGS] Public workspace activity read failed.", error)
        raise _refuse_unavailable(
            PUBLIC_ACTIVITY_UNAVAILABLE_MESSAGE, "public_workspace_activity_unavailable",
        ) from error
    return {"activity": project_public_activity(records, workspace), "limit": limit}, 200


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

    A timestamp whose UTC offset moves it past the calendar's first or last day can't be
    read either, and is left out of the series as any other unreadable timestamp is.
    """
    try:
        return timestamp_to_stats_date_key(timestamp)
    except (OverflowError, ValueError):
        return None


def _member_count(workspace):
    """The classic member count: the owner, the admins and the document managers."""
    count = 1
    for key in ("admins", "documentManagers"):
        entries = workspace.get(key)
        count += len(entries) if isinstance(entries, list) else 0
    return count


# The classic statistics queries, in the order the classic route sends them.
PUBLIC_STATS_QUERIES = (
    ("token_total", PUBLIC_STATS_TOKEN_TOTAL_QUERY),
    ("uploads", PUBLIC_STATS_UPLOAD_QUERY),
    ("deletes", PUBLIC_STATS_DELETE_QUERY),
    ("token_series", PUBLIC_STATS_TOKEN_SERIES_QUERY),
)


def read_public_stats_rows(workspace, window):
    """The rows each classic statistics query returns for ``workspace`` over ``window``.

    This is the only storage read behind the statistics, so any exception it raises is a
    storage failure.
    """
    parameters = [
        {"name": "@wsId", "value": workspace.get("id")},
        {"name": "@startDate", "value": window["start_date_iso"]},
        {"name": "@endDate", "value": window["end_date_iso"]},
    ]
    return {
        name: list(cosmos_activity_logs_container.query_items(
            query=text, parameters=[dict(parameter) for parameter in parameters], enable_cross_partition_query=True,
        ))
        for name, text in PUBLIC_STATS_QUERIES
    }


def build_public_stats(workspace, window, date_series, rows):
    """The classic figures for ``workspace`` from its statistics rows, without reading storage."""
    metrics = workspace.get("metrics") if isinstance(workspace.get("metrics"), dict) else {}
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

    storage_account_size = _stored_figure(document_metrics, "storage_account_size")
    return {
        "totalDocuments": _stored_figure(document_metrics, "total_documents"),
        "storageUsed": storage_account_size,
        "totalTokens": total_tokens,
        "totalMembers": _member_count(workspace),
        "storage": {
            "ai_search_size": _stored_figure(document_metrics, "ai_search_size"),
            "storage_account_size": storage_account_size,
        },
        "documentActivity": {"labels": labels, "uploads": uploads, "deletes": deletes},
        "tokenUsage": {"labels": list(labels), "data": tokens},
        "dateRange": [day["date"] for day in date_series],
        "window": stats_window_response_payload(window),
    }


def read_public_stats(user_id, workspace_id):
    """Return ``({"stats": ...}, 200)`` for the owner, an admin or a document manager."""
    user_id = _require_user_id(user_id)
    # Everything derived from the request is settled before the workspace is read, so a
    # window that can't be used is a 400 and never reaches the storage 503 below.
    window = read_stats_window()
    date_series = build_stats_date_series(window["start_date"], window["end_date"])
    workspace, role = load_public_workspace(user_id, workspace_id)
    require_operation(workspace, role, get_settings(), "view_stats")
    try:
        rows = read_public_stats_rows(workspace, window)
    except Exception as error:  # noqa: BLE001 - every storage failure is the same data-free 503
        _log_storage_failure("[PUBLIC_SETTINGS] Public workspace statistics read failed.", error)
        raise _refuse_unavailable(PUBLIC_STATS_UNAVAILABLE_MESSAGE, "public_workspace_stats_unavailable") from error
    return {"stats": build_public_stats(workspace, window, date_series, rows)}, 200


def read_public_file_count(user_id, workspace_id):
    """Return ``({"file_count": n}, 200)`` for the owner."""
    user_id = _require_user_id(user_id)
    _single_arguments((), "This request does not accept query parameters.")
    workspace, role = load_public_workspace(user_id, workspace_id)
    require_operation(workspace, role, get_settings(), "view_file_count")
    return {"file_count": count_current_public_documents(workspace_id)}, 200
