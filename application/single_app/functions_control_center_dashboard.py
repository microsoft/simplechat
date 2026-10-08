# functions_control_center_dashboard.py
"""Aggregate V2 Control Center dashboard metrics from recorded activity.

The dashboard routes and the Control Center action both read through these functions, so a
figure on the dashboard and the same figure reported in chat come from the same queries.
Storage handles arrive in a ``DashboardStores`` bundle and logging through a callback, so this
module never imports the Azure bootstrap and tests can drive it with fake containers.

The azure-cosmos Python SDK cannot run a cross-partition GROUP BY or COUNT over DISTINCT
values. Grouped figures are therefore totalled here from narrow streamed projections, and
distinct values are counted after ``SELECT DISTINCT VALUE``.
"""

import json
import logging
import threading
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Tuple


CONTROL_CENTER_DASHBOARD_CACHE_TTL_SECONDS = 90
CONTROL_CENTER_DASHBOARD_CACHE_MAX_ENTRIES = 128
CONTROL_CENTER_DASHBOARD_NAME_CACHE_MAX_ENTRIES = 1024
CONTROL_CENTER_DASHBOARD_RANKING_LIMIT = 10
CONTROL_CENTER_DASHBOARD_MAX_RANGE_DAYS = 366
CONTROL_CENTER_DASHBOARD_PRESET_DAYS = (7, 30, 90)
CONTROL_CENTER_DASHBOARD_RANKED_FIELDS = (
    ("users", "user_id"),
    ("groups", "group_id"),
    ("public_workspaces", "public_workspace_id"),
)
DASHBOARD_INVALID_RANGE_ERROR = (
    "Invalid dashboard date range. Use 7, 30, or 90 days or a valid custom range of up to 366 days."
)
DASHBOARD_TOKEN_TYPES = ("chat", "embedding", "web_search")
DASHBOARD_WORKSPACE_TYPES = ("personal", "group", "public")
DASHBOARD_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
DASHBOARD_DAILY_ACTIVITY_FIELDS = (
    "sign_ins",
    "conversations_created",
    "uploads_personal",
    "uploads_group",
    "uploads_public",
)
DASHBOARD_ENTITY_KINDS = ("users", "groups", "public_workspaces")
DASHBOARD_ENTITY_MISSING_NAMES = {
    "users": "Unknown user",
    "groups": "Deleted group",
    "public_workspaces": "Deleted public workspace",
}
DASHBOARD_ENTITY_UNNAMED = {
    "users": "Unnamed user",
    "groups": "Unnamed group",
    "public_workspaces": "Unnamed public workspace",
}
DASHBOARD_ENTITY_SEARCH_MIN_LENGTH = 2
DASHBOARD_ENTITY_SEARCH_MAX_LENGTH = 100
DASHBOARD_ENTITY_SEARCH_MAX_RESULTS = 10
DASHBOARD_REPORT_MAX_ROWS = 50
DASHBOARD_TOKEN_GROUPINGS = ("day", "model", "token_type", "user", "group", "public_workspace")
DASHBOARD_LOGIN_HEATMAP_CONVENTION = "Monday=0 through Sunday=6"

# The read-only Control Center action type. Declared here, with no runtime dependencies, so
# validation, governance and action discovery can name it without loading Semantic Kernel.
CONTROL_CENTER_ACTION_TYPE = "control_center"
CONTROL_CENTER_ACTION_DEFAULT_ENDPOINT = "control_center://internal"
# What chat orchestration reads when it decides whether this action can answer a question.
CONTROL_CENTER_ACTION_DEFAULT_DESCRIPTION = (
    "Read-only SimpleChat usage insights from the Control Center dashboard: sign-ins, daily, "
    "weekly and monthly active users, conversations, document uploads, token usage by day, model "
    "and usage type, the most active users, groups and public workspaces, and sign-in times. "
    "Available only to Control Center administrators and dashboard readers."
)

# A record counts toward a period when either recorded time falls inside it. Older records
# carry only created_at, newer ones carry timestamp, and many carry both.
RECORDED_IN_WINDOW = """(
            (c.timestamp >= @start_date AND c.timestamp <= @end_date)
            OR (c.created_at >= @start_date AND c.created_at <= @end_date)
        )"""

_control_center_dashboard_cache = {}
_control_center_entity_name_cache = {}
_cache_lock = threading.Lock()


@dataclass(frozen=True)
class DashboardStores:
    """The containers the dashboard reads, supplied by the caller that owns configuration."""

    activity_logs: Any
    user_settings: Any = None
    groups: Any = None
    public_workspaces: Any = None
    user_documents: Any = None
    group_documents: Any = None
    public_documents: Any = None
    approvals: Any = None


@dataclass(frozen=True)
class DashboardPeriod:
    """A range of whole UTC calendar days and the equally long range just before it."""

    start: datetime
    end: datetime
    previous_start: datetime
    previous_end: datetime
    days: int

    @property
    def start_day(self) -> str:
        return self.start.date().isoformat()

    @property
    def end_day(self) -> str:
        return self.end.date().isoformat()

    def cache_key(self) -> Tuple[str, str]:
        return (self.start.isoformat(), self.end.isoformat())

    def describe(self) -> Dict[str, Any]:
        return {
            "start_date": self.start_day,
            "end_date": self.end_day,
            "days": self.days,
            "timezone": "UTC",
        }

    def describe_previous(self) -> Dict[str, Any]:
        return {
            "start_date": self.previous_start.date().isoformat(),
            "end_date": self.previous_end.date().isoformat(),
            "days": self.days,
            "timezone": "UTC",
        }

    def dates(self) -> List[str]:
        first_day = self.start.date()
        return [(first_day + timedelta(days=offset)).isoformat() for offset in range(self.days)]


# --------------------------------------------------------------------------------------
# Periods
# --------------------------------------------------------------------------------------

def build_dashboard_period(start_day: date, end_day: date) -> DashboardPeriod:
    """Return the UTC range covering whole calendar days, with its comparison range."""
    if end_day < start_day:
        raise ValueError("end_date must be on or after start_date.")
    days = (end_day - start_day).days + 1
    if days > CONTROL_CENTER_DASHBOARD_MAX_RANGE_DAYS:
        raise ValueError(f"Ranges may not exceed {CONTROL_CENTER_DASHBOARD_MAX_RANGE_DAYS} days.")
    start = datetime.combine(start_day, datetime.min.time())
    end = datetime.combine(end_day, datetime.max.time())
    previous_end = start - timedelta(microseconds=1)
    previous_start = previous_end - timedelta(days=days) + timedelta(microseconds=1)
    return DashboardPeriod(start, end, previous_start, previous_end, days)


def _parse_day(value: Any) -> date:
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d").date()
    except (TypeError, ValueError) as ex:
        raise ValueError("Dates must use YYYY-MM-DD format.") from ex


def parse_dashboard_period(args: Mapping[str, Any], *, today: Optional[date] = None) -> DashboardPeriod:
    """Resolve the dashboard's 7, 30 or 90 day preset, or a custom range of up to 366 days."""
    custom_start = args.get("start_date")
    custom_end = args.get("end_date")
    if custom_start or custom_end:
        if not custom_start or not custom_end:
            raise ValueError("Both start_date and end_date are required.")
        return build_dashboard_period(_parse_day(custom_start), _parse_day(custom_end))
    try:
        days = int(args.get("days", 30))
    except (TypeError, ValueError) as ex:
        raise ValueError("days must be 7, 30, or 90.") from ex
    if days not in CONTROL_CENTER_DASHBOARD_PRESET_DAYS:
        raise ValueError("days must be 7, 30, or 90.")
    end_day = today or datetime.utcnow().date()
    return build_dashboard_period(end_day - timedelta(days=days - 1), end_day)


def resolve_requested_period(
    start_date: Any = "",
    end_date: Any = "",
    days: Any = None,
    *,
    today: Optional[date] = None,
) -> DashboardPeriod:
    """Resolve explicit dates, or a number of whole days ending today (UTC)."""
    start_text = str(start_date or "").strip()
    end_text = str(end_date or "").strip()
    if start_text or end_text:
        if not start_text or not end_text:
            raise ValueError("Provide both start_date and end_date, or neither.")
        return build_dashboard_period(_parse_day(start_text), _parse_day(end_text))
    if days is None or (isinstance(days, str) and not days.strip()):
        days = 30
    if isinstance(days, bool):
        raise ValueError(f"days must be a whole number from 1 to {CONTROL_CENTER_DASHBOARD_MAX_RANGE_DAYS}.")
    try:
        day_count = int(str(days).strip())
    except (TypeError, ValueError) as ex:
        raise ValueError(
            f"days must be a whole number from 1 to {CONTROL_CENTER_DASHBOARD_MAX_RANGE_DAYS}."
        ) from ex
    if not 1 <= day_count <= CONTROL_CENTER_DASHBOARD_MAX_RANGE_DAYS:
        raise ValueError(f"days must be a whole number from 1 to {CONTROL_CENTER_DASHBOARD_MAX_RANGE_DAYS}.")
    end_day = today or datetime.utcnow().date()
    return build_dashboard_period(end_day - timedelta(days=day_count - 1), end_day)


# --------------------------------------------------------------------------------------
# Cache
# --------------------------------------------------------------------------------------

def _cache_get(cache, key, force_refresh=False, now=None):
    if force_refresh:
        return None
    current_time = time.monotonic() if now is None else now
    with _cache_lock:
        entry = cache.get(key)
        if not entry:
            return None
        expires_at, payload = entry
        if expires_at <= current_time:
            cache.pop(key, None)
            return None
        return payload


def _cache_set(cache, key, payload, max_entries, now=None):
    current_time = time.monotonic() if now is None else now
    with _cache_lock:
        expired_keys = [
            cache_key
            for cache_key, (expires_at, _) in cache.items()
            if expires_at <= current_time
        ]
        for cache_key in expired_keys:
            cache.pop(cache_key, None)
        if key not in cache and len(cache) >= max_entries:
            cache.pop(next(iter(cache)))
        cache[key] = (current_time + CONTROL_CENTER_DASHBOARD_CACHE_TTL_SECONDS, payload)


def dashboard_cache_get(key, force_refresh=False, now=None):
    """Return an unexpired dashboard cache entry, if one is available."""
    return _cache_get(_control_center_dashboard_cache, key, force_refresh=force_refresh, now=now)


def dashboard_cache_set(key, payload, now=None):
    """Store a short-lived dashboard result and bound cache growth."""
    _cache_set(
        _control_center_dashboard_cache,
        key,
        payload,
        CONTROL_CENTER_DASHBOARD_CACHE_MAX_ENTRIES,
        now=now,
    )


def _filters_cache_key(filters: Optional[Mapping[str, Any]]) -> str:
    return json.dumps(
        {key: value for key, value in (filters or {}).items() if value},
        sort_keys=True,
    )


def _utc_now_text() -> str:
    return datetime.utcnow().isoformat() + "Z"


# --------------------------------------------------------------------------------------
# Metric formatting
# --------------------------------------------------------------------------------------

def dashboard_metric(current_value, previous_value=None):
    """Format a current-period value with a comparable prior-period delta."""
    current_value = int(current_value or 0)
    if previous_value is None:
        return {"value": current_value, "delta": None, "percent_change": None}
    previous_value = int(previous_value or 0)
    delta = current_value - previous_value
    percent_change = (
        round((delta / previous_value) * 100, 1)
        if previous_value
        else (0.0 if delta == 0 else None)
    )
    return {
        "value": current_value,
        "delta": delta,
        "previous": previous_value,
        "percent_change": percent_change,
    }


def dashboard_status_counts(total, grouped_statuses, unknown_status="active"):
    """Normalize stored status counts while preserving each workspace type's default."""
    counts = {
        "active": 0,
        "locked": 0,
        "upload_disabled": 0,
        "inactive": 0,
    }
    for row in grouped_statuses:
        raw_status = row.get("status")
        status = str(raw_status or "active").strip().lower()
        count = int(row.get("count") or 0)
        if status in {"locked", "upload_disabled", "inactive"}:
            counts[status] += count
        elif status != "active" and raw_status and unknown_status == "inactive":
            counts["inactive"] += count
    counts["active"] = max(
        int(total or 0) - counts["locked"] - counts["upload_disabled"] - counts["inactive"],
        0,
    )
    return counts


# --------------------------------------------------------------------------------------
# Token filters
# --------------------------------------------------------------------------------------

def normalize_token_filter_value(value):
    """Normalize optional token filter values from query params or request JSON."""
    if value is None:
        return None

    normalized = str(value).strip()
    if not normalized or normalized.lower() == "all":
        return None

    return normalized


def extract_token_filters(source):
    """Extract supported token filters from a query string or JSON payload."""
    if not source:
        return {}

    token_source = source
    nested_filters = source.get("token_filters") if hasattr(source, "get") else None
    if isinstance(nested_filters, dict):
        token_source = nested_filters

    token_filters = {
        "user_id": normalize_token_filter_value(token_source.get("user_id")),
        "workspace_type": normalize_token_filter_value(token_source.get("workspace_type")),
        "group_id": normalize_token_filter_value(token_source.get("group_id")),
        "public_workspace_id": normalize_token_filter_value(token_source.get("public_workspace_id")),
        "model": normalize_token_filter_value(token_source.get("model")),
        "token_type": normalize_token_filter_value(token_source.get("token_type")),
    }

    if token_filters["workspace_type"] not in {None, "personal", "group", "public"}:
        token_filters["workspace_type"] = None

    if token_filters["token_type"] not in {None, "embedding", "chat", "web_search"}:
        token_filters["token_type"] = None

    if token_filters["group_id"] and not token_filters["workspace_type"]:
        token_filters["workspace_type"] = "group"

    if token_filters["public_workspace_id"] and not token_filters["workspace_type"]:
        token_filters["workspace_type"] = "public"

    return token_filters


def append_token_usage_filters(query_conditions, parameters, token_filters):
    """Append optional token usage filters to the Cosmos query state."""
    if not token_filters:
        return

    user_id = token_filters.get("user_id")
    if user_id:
        query_conditions.append("c.user_id = @token_user_id")
        parameters.append({"name": "@token_user_id", "value": user_id})

    workspace_type = token_filters.get("workspace_type")
    if workspace_type:
        query_conditions.append("c.workspace_type = @token_workspace_type")
        parameters.append({"name": "@token_workspace_type", "value": workspace_type})

    group_id = token_filters.get("group_id")
    if group_id:
        query_conditions.append("c.workspace_context.group_id = @token_group_id")
        parameters.append({"name": "@token_group_id", "value": group_id})

    public_workspace_id = token_filters.get("public_workspace_id")
    if public_workspace_id:
        query_conditions.append("c.workspace_context.public_workspace_id = @token_public_workspace_id")
        parameters.append({"name": "@token_public_workspace_id", "value": public_workspace_id})

    model = token_filters.get("model")
    if model:
        query_conditions.append("c.usage.model = @token_model")
        parameters.append({"name": "@token_model", "value": model})

    token_type = token_filters.get("token_type")
    if token_type:
        query_conditions.append("c.token_type = @token_type")
        parameters.append({"name": "@token_type", "value": token_type})


def build_token_usage_query_context(start_date, end_date, token_filters=None):
    """Build shared WHERE-clause state for token usage queries."""
    parameters = [
        {"name": "@start_date", "value": start_date.isoformat()},
        {"name": "@end_date", "value": end_date.isoformat()}
    ]
    query_conditions = [
        "c.activity_type = 'token_usage'",
        "((c.timestamp >= @start_date AND c.timestamp <= @end_date) OR (c.created_at >= @start_date AND c.created_at <= @end_date))"
    ]

    append_token_usage_filters(query_conditions, parameters, token_filters or {})
    return " AND ".join(query_conditions), parameters


# --------------------------------------------------------------------------------------
# Counts
# --------------------------------------------------------------------------------------

def _period_parameters(start: datetime, end: datetime) -> List[Dict[str, Any]]:
    return [
        {"name": "@start_date", "value": start.isoformat()},
        {"name": "@end_date", "value": end.isoformat()},
    ]


def query_count(container, query, parameters=None):
    """Execute a cross-partition aggregate count."""
    rows = list(container.query_items(
        query=query,
        parameters=parameters or [],
        enable_cross_partition_query=True,
    ))
    return int(rows[0] or 0) if rows else 0


def count_active_users(container, start_date, end_date):
    """Count distinct users with recorded login activity in a UTC interval.

    The Python Cosmos SDK cannot run COUNT over a DISTINCT subquery across partitions,
    so the distinct user IDs are read with SELECT DISTINCT VALUE and counted here.
    """
    user_ids = container.query_items(
        query="""
        SELECT DISTINCT VALUE c.user_id FROM c
        WHERE c.activity_type = 'user_login'
          AND IS_DEFINED(c.user_id)
          AND c.timestamp >= @start_date
          AND c.timestamp <= @end_date
        """,
        parameters=_period_parameters(start_date, end_date),
        enable_cross_partition_query=True,
    )
    return len(set(user_ids))


def count_activity(container, activity_type, start_date, end_date):
    """Count recorded events of one activity type in a UTC interval."""
    return query_count(
        container,
        f"""
        SELECT VALUE COUNT(1) FROM c
        WHERE c.activity_type = @activity_type
          AND {RECORDED_IN_WINDOW}
        """,
        [{"name": "@activity_type", "value": activity_type}] + _period_parameters(start_date, end_date),
    )


def count_document_uploads(container, start_date, end_date):
    """Count document-creation activity by the recorded workspace type.

    Cross-partition GROUP BY is unavailable to the Python Cosmos SDK, so group and
    public uploads are counted directly. Every other recorded or missing type is
    personal, so personal is the remainder of the period total.
    """
    window = f"""
        c.activity_type = 'document_creation'
        AND {RECORDED_IN_WINDOW}
    """
    parameters = _period_parameters(start_date, end_date)
    total = query_count(
        container,
        f"SELECT VALUE COUNT(1) FROM c WHERE {window}",
        parameters,
    )
    counts = {
        workspace_type: query_count(
            container,
            f"SELECT VALUE COUNT(1) FROM c WHERE {window} AND c.workspace_type = @workspace_type",
            parameters + [{"name": "@workspace_type", "value": workspace_type}],
        )
        for workspace_type in ("group", "public")
    }
    return {"personal": max(total - counts["group"] - counts["public"], 0), **counts}


def status_rows(container):
    """Tally stored status values for dashboard_status_counts without a GROUP BY query."""
    statuses = Counter(
        status if status is None or isinstance(status, str) else str(status)
        for status in container.query_items(
            query="SELECT VALUE c.status FROM c WHERE IS_DEFINED(c.status)",
            enable_cross_partition_query=True,
        )
    )
    return [{"status": status, "count": count} for status, count in statuses.items()]


def token_total(container, start_date, end_date, token_filters):
    """Aggregate token usage without returning individual activity records."""
    where_clause, parameters = build_token_usage_query_context(
        start_date,
        end_date,
        token_filters=token_filters,
    )
    rows = list(container.query_items(
        query=f"SELECT VALUE SUM(c.usage.total_tokens) FROM c WHERE {where_clause}",
        parameters=parameters,
        enable_cross_partition_query=True,
    ))
    return int(rows[0] or 0) if rows else 0


def count_document_failures(container, start_date, end_date):
    """Count stored document processing states that explicitly report failure."""
    return query_count(
        container,
        """
        SELECT VALUE COUNT(1) FROM c
        WHERE IS_STRING(c.status)
          AND (CONTAINS(LOWER(c.status), 'failed') OR CONTAINS(LOWER(c.status), 'error'))
          AND (
              (c.upload_date >= @start_date AND c.upload_date <= @end_date)
              OR (c.created_at >= @start_date AND c.created_at <= @end_date)
          )
        """,
        _period_parameters(start_date, end_date),
    )


def count_all_document_failures(stores: DashboardStores, start_date, end_date):
    """Count failed processing records across personal, group, and public workspaces."""
    return sum(
        count_document_failures(container, start_date, end_date)
        for container in (stores.user_documents, stores.group_documents, stores.public_documents)
        if container is not None
    )


def count_pending_approvals(container):
    """Count approval requests that are still waiting for a decision."""
    return query_count(
        container,
        """
        SELECT VALUE COUNT(1) FROM c
        WHERE c.status = 'pending'
        """,
    )


# --------------------------------------------------------------------------------------
# Streamed aggregation
# --------------------------------------------------------------------------------------

def token_value(value):
    """Return the numeric token count Cosmos SUM would add; other values count as zero."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return value


def rank_totals(totals, value_key, limit=CONTROL_CENTER_DASHBOARD_RANKING_LIMIT):
    """Return the largest totals, with ties ordered by ID so the ranking is stable."""
    ranked = sorted(totals.items(), key=lambda item: (-item[1], item[0]))
    return [
        {"id": entity_id, value_key: int(total)}
        for entity_id, total in ranked[:limit]
    ]


def _row_moment(row: Mapping[str, Any]) -> Optional[str]:
    """The recorded time of an activity row as an ISO string, preferring ``timestamp``."""
    for field in ("timestamp", "created_at"):
        value = row.get(field)
        if isinstance(value, str) and value:
            return value
    return None


def _row_day(row: Mapping[str, Any]) -> Optional[str]:
    moment = _row_moment(row)
    if moment is None or len(moment) < 10:
        return None
    day = moment[:10]
    try:
        datetime.strptime(day, "%Y-%m-%d")
    except ValueError:
        return None
    return day


def _row_weekday_hour(row: Mapping[str, Any]) -> Optional[Tuple[int, int]]:
    moment = _row_moment(row)
    if moment is None:
        return None
    try:
        weekday = datetime.strptime(moment[:10], "%Y-%m-%d").weekday()
        hour = int(moment[11:13])
    except ValueError:
        return None
    if 0 <= hour <= 23:
        return weekday, hour
    return None


def _upload_field(workspace_type: Any) -> str:
    if workspace_type == "group":
        return "uploads_group"
    if workspace_type == "public":
        return "uploads_public"
    return "uploads_personal"


def _workspace_kind(workspace_type: Any) -> str:
    if workspace_type in {"group", "public"}:
        return workspace_type
    return "personal"


def aggregate_token_usage(container, period: DashboardPeriod, token_filters=None) -> Dict[str, Any]:
    """Total the filtered token records by day, model, usage type and consumer.

    The Python Cosmos SDK cannot run cross-partition GROUP BY, so one narrow projection of
    the filtered token records is streamed and totalled here.
    """
    where_clause, parameters = build_token_usage_query_context(
        period.start,
        period.end,
        token_filters=token_filters,
    )
    by_day_model = defaultdict(int)
    by_day_type = defaultdict(int)
    by_model = defaultdict(int)
    by_type = defaultdict(int)
    consumers = {key: defaultdict(int) for key, _ in CONTROL_CENTER_DASHBOARD_RANKED_FIELDS}
    total = 0
    rows = container.query_items(
        query=f"""
        SELECT c.timestamp,
               c.created_at,
               c.token_type AS token_type,
               c.usage.model AS model,
               c.usage.total_tokens AS tokens,
               c.user_id AS user_id,
               c.workspace_context.group_id AS group_id,
               c.workspace_context.public_workspace_id AS public_workspace_id
        FROM c
        WHERE {where_clause}
        """,
        parameters=parameters,
        enable_cross_partition_query=True,
    )
    for row in rows:
        tokens = token_value(row.get("tokens"))
        total += tokens
        day = _row_day(row)
        if "model" in row:
            model = str(row.get("model") or "Unknown model")
            by_model[model] += tokens
            if day:
                by_day_model[(day, model)] += tokens
        token_type = row.get("token_type")
        if token_type in DASHBOARD_TOKEN_TYPES:
            by_type[token_type] += tokens
            if day:
                by_day_type[(day, token_type)] += tokens
        for key, field in CONTROL_CENTER_DASHBOARD_RANKED_FIELDS:
            entity_id = row.get(field)
            if isinstance(entity_id, str) and entity_id:
                consumers[key][entity_id] += tokens

    daily_by_type = {day: dict.fromkeys(DASHBOARD_TOKEN_TYPES, 0) for day in period.dates()}
    for (day, token_type), tokens in by_day_type.items():
        if day in daily_by_type:
            daily_by_type[day][token_type] += int(tokens)
    return {
        "total": int(total),
        "token_usage_by_model": [
            {"date": day, "model": model, "tokens": int(tokens)}
            for (day, model), tokens in sorted(by_day_model.items())
        ],
        "token_usage_by_type": [
            {"date": day, **types} for day, types in daily_by_type.items()
        ],
        "by_model": {model: int(tokens) for model, tokens in by_model.items()},
        "by_type": {token_type: int(by_type.get(token_type, 0)) for token_type in DASHBOARD_TOKEN_TYPES},
        "consumers": {key: dict(values) for key, values in consumers.items()},
    }


def _daily_activity_template(period: DashboardPeriod) -> Dict[str, Dict[str, int]]:
    return {day: dict.fromkeys(DASHBOARD_DAILY_ACTIVITY_FIELDS, 0) for day in period.dates()}


def _count_daily_activity(daily, row) -> None:
    counts = daily.get(_row_day(row))
    if counts is None:
        return
    activity_type = row.get("activity_type")
    if activity_type == "user_login":
        counts["sign_ins"] += 1
    elif activity_type == "conversation_creation":
        counts["conversations_created"] += 1
    elif activity_type == "document_creation":
        counts[_upload_field(row.get("workspace_type"))] += 1


def _activity_rows(container, period: DashboardPeriod, user_id: Optional[str] = None):
    conditions = [RECORDED_IN_WINDOW]
    parameters = _period_parameters(period.start, period.end)
    if user_id:
        conditions.append("c.user_id = @activity_user_id")
        parameters.append({"name": "@activity_user_id", "value": user_id})
    where_clause = "\n          AND ".join(conditions)
    return container.query_items(
        query=f"""
        SELECT c.timestamp,
               c.created_at,
               c.activity_type,
               c.workspace_type,
               c.user_id AS user_id,
               c.workspace_context.group_id AS group_id,
               c.workspace_context.public_workspace_id AS public_workspace_id
        FROM c
        WHERE {where_clause}
        """,
        parameters=parameters,
        enable_cross_partition_query=True,
    )


def aggregate_activity(container, period: DashboardPeriod) -> Dict[str, Any]:
    """Count recorded activity by day, actor and sign-in hour from one streamed projection.

    Each heatmap cell totals every sign-in in the period for one UTC weekday and hour.
    """
    daily = _daily_activity_template(period)
    actors = {key: defaultdict(int) for key, _ in CONTROL_CENTER_DASHBOARD_RANKED_FIELDS}
    logins = Counter()
    for row in _activity_rows(container, period):
        for key, field in CONTROL_CENTER_DASHBOARD_RANKED_FIELDS:
            entity_id = row.get(field)
            if isinstance(entity_id, str) and entity_id:
                actors[key][entity_id] += 1
        _count_daily_activity(daily, row)
        if row.get("activity_type") == "user_login":
            weekday_hour = _row_weekday_hour(row)
            if weekday_hour is not None:
                logins[weekday_hour] += 1
    return {
        "daily_activity": [{"date": day, **counts} for day, counts in daily.items()],
        "actors": {key: dict(values) for key, values in actors.items()},
        "login_cells": [
            {"weekday": weekday, "hour": hour, "count": count}
            for (weekday, hour), count in sorted(logins.items())
        ],
    }


def _matches_workspace_filters(row: Mapping[str, Any], filters: Mapping[str, Any]) -> bool:
    workspace_type = filters.get("workspace_type")
    if workspace_type and _workspace_kind(row.get("workspace_type")) != workspace_type:
        return False
    group_id = filters.get("group_id")
    if group_id and row.get("group_id") != group_id:
        return False
    public_workspace_id = filters.get("public_workspace_id")
    if public_workspace_id and row.get("public_workspace_id") != public_workspace_id:
        return False
    return True


def filtered_daily_activity(container, period: DashboardPeriod, filters: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Daily activity narrowed to one user and/or workspace.

    Sign-ins are not recorded against a workspace, so the workspace filters narrow
    conversations and uploads only; sign-ins honor the user filter alone.
    """
    daily = _daily_activity_template(period)
    for row in _activity_rows(container, period, user_id=filters.get("user_id")):
        if row.get("activity_type") != "user_login" and not _matches_workspace_filters(row, filters):
            continue
        _count_daily_activity(daily, row)
    return [{"date": day, **counts} for day, counts in daily.items()]


# --------------------------------------------------------------------------------------
# Names
# --------------------------------------------------------------------------------------

def _clean_text(value: Any, limit: int = 200) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit]


def _entity_container(stores: DashboardStores, kind: str):
    return {
        "users": stores.user_settings,
        "groups": stores.groups,
        "public_workspaces": stores.public_workspaces,
    }.get(kind)


def _describe_entity(kind: str, document: Any) -> Dict[str, Any]:
    if not isinstance(document, dict):
        return {"name": DASHBOARD_ENTITY_MISSING_NAMES[kind], "detail": "", "found": False}
    if kind == "users":
        display_name = _clean_text(document.get("display_name"))
        email = _clean_text(document.get("email"))
        return {
            "name": display_name or email or DASHBOARD_ENTITY_UNNAMED[kind],
            "detail": email if display_name else "",
            "found": True,
        }
    return {
        "name": _clean_text(document.get("name")) or DASHBOARD_ENTITY_UNNAMED[kind],
        "detail": "",
        "found": True,
    }


def resolve_entity_names(
    stores: DashboardStores,
    ids_by_kind: Mapping[str, Iterable[str]],
    *,
    log: Optional[Callable[..., Any]] = None,
    now=None,
) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """Look up display names for ranked IDs, caching each answer as briefly as the dashboard.

    A user, group or workspace that cannot be read is reported with a fallback name rather
    than failing the dashboard: rankings are built from activity that can outlive the record.
    """
    resolved = {kind: {} for kind in DASHBOARD_ENTITY_KINDS}
    for kind, entity_ids in ids_by_kind.items():
        if kind not in DASHBOARD_ENTITY_KINDS:
            continue
        container = _entity_container(stores, kind)
        for entity_id in dict.fromkeys(entity_ids or ()):
            if not isinstance(entity_id, str) or not entity_id:
                continue
            cache_key = (kind, entity_id)
            described = _cache_get(_control_center_entity_name_cache, cache_key, now=now)
            if described is None:
                document = None
                if container is not None:
                    try:
                        document = container.read_item(item=entity_id, partition_key=entity_id)
                    except Exception as ex:
                        if log is not None:
                            log(
                                "[CONTROL_CENTER] A ranked dashboard entity could not be resolved.",
                                extra={"entity_kind": kind, "error_type": type(ex).__name__},
                                level=logging.DEBUG,
                                debug_only=True,
                            )
                described = _describe_entity(kind, document)
                _cache_set(
                    _control_center_entity_name_cache,
                    cache_key,
                    described,
                    CONTROL_CENTER_DASHBOARD_NAME_CACHE_MAX_ENTRIES,
                    now=now,
                )
            resolved[kind][entity_id] = described
    return resolved


def name_ranked_rows(rows: Iterable[Mapping[str, Any]], names: Mapping[str, Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Return ranked rows with each entity's name, detail and whether it still exists."""
    named = []
    for row in rows:
        described = names.get(row.get("id")) or {}
        named.append({
            **row,
            "name": described.get("name") or "",
            "detail": described.get("detail") or "",
            "found": bool(described.get("found")),
        })
    return named


def _name_rankings(stores, rankings, *, log=None, now=None):
    names = resolve_entity_names(
        stores,
        {kind: [row["id"] for row in rows] for kind, rows in rankings.items()},
        log=log,
        now=now,
    )
    return {kind: name_ranked_rows(rows, names.get(kind, {})) for kind, rows in rankings.items()}


# --------------------------------------------------------------------------------------
# Summary
# --------------------------------------------------------------------------------------

def _summary_base(stores: DashboardStores, period: DashboardPeriod, *, log=None) -> Dict[str, Any]:
    total_users = query_count(stores.user_settings, "SELECT VALUE COUNT(1) FROM c")
    blocked_users = query_count(
        stores.user_settings,
        """
        SELECT VALUE COUNT(1) FROM c
        WHERE c.settings.access.status = 'deny'
        """,
    )

    groups_total = query_count(stores.groups, "SELECT VALUE COUNT(1) FROM c")
    groups_by_status = dashboard_status_counts(groups_total, status_rows(stores.groups))

    workspaces_total = query_count(stores.public_workspaces, "SELECT VALUE COUNT(1) FROM c")
    workspaces_by_status = dashboard_status_counts(
        workspaces_total,
        status_rows(stores.public_workspaces),
        unknown_status="inactive",
    )

    activity = stores.activity_logs
    end_day = period.end.date()
    active_users = count_active_users(activity, period.start, period.end)
    previous_active_users = count_active_users(activity, period.previous_start, period.previous_end)
    current_dau = count_active_users(activity, datetime.combine(end_day, datetime.min.time()), period.end)
    current_wau = count_active_users(
        activity,
        datetime.combine(end_day - timedelta(days=6), datetime.min.time()),
        period.end,
    )
    current_mau = count_active_users(
        activity,
        datetime.combine(end_day - timedelta(days=29), datetime.min.time()),
        period.end,
    )

    conversations = count_activity(activity, "conversation_creation", period.start, period.end)
    previous_conversations = count_activity(
        activity,
        "conversation_creation",
        period.previous_start,
        period.previous_end,
    )
    document_uploads = count_document_uploads(activity, period.start, period.end)
    previous_document_uploads = count_document_uploads(activity, period.previous_start, period.previous_end)

    try:
        failure_metric = {
            **dashboard_metric(
                count_all_document_failures(stores, period.start, period.end),
                count_all_document_failures(stores, period.previous_start, period.previous_end),
            ),
            "available": True,
        }
    except Exception as ex:
        if log is not None:
            log(
                "[CONTROL_CENTER] Document failure metrics are unavailable.",
                extra={"error_type": type(ex).__name__},
                level=logging.WARNING,
            )
        failure_metric = {
            "value": None,
            "delta": None,
            "percent_change": None,
            "available": False,
        }

    pending_approvals = None
    if stores.approvals is not None:
        try:
            pending_approvals = count_pending_approvals(stores.approvals)
        except Exception as ex:
            if log is not None:
                log(
                    "[CONTROL_CENTER] Pending approval count is unavailable.",
                    extra={"error_type": type(ex).__name__},
                    level=logging.WARNING,
                )

    return {
        "computed_at": _utc_now_text(),
        "users": {
            "total": dashboard_metric(total_users),
            "active": dashboard_metric(active_users, previous_active_users),
            "dau": dashboard_metric(current_dau),
            "wau": dashboard_metric(current_wau),
            "mau": dashboard_metric(current_mau),
            "blocked": dashboard_metric(blocked_users),
        },
        "groups": {
            "total": dashboard_metric(groups_total),
            "by_status": {status: dashboard_metric(count) for status, count in groups_by_status.items()},
        },
        "public_workspaces": {
            "total": dashboard_metric(workspaces_total),
            "by_status": {status: dashboard_metric(count) for status, count in workspaces_by_status.items()},
        },
        "conversations": dashboard_metric(conversations, previous_conversations),
        "document_uploads": {
            "total": dashboard_metric(sum(document_uploads.values()), sum(previous_document_uploads.values())),
            "by_workspace_type": {
                workspace_type: dashboard_metric(count, previous_document_uploads.get(workspace_type, 0))
                for workspace_type, count in document_uploads.items()
            },
        },
        "document_processing_failures": failure_metric,
        "pending_approvals": (
            dashboard_metric(pending_approvals) if pending_approvals is not None else None
        ),
    }


def _summary_tokens(stores: DashboardStores, period: DashboardPeriod, token_filters) -> Dict[str, Any]:
    return {
        "computed_at": _utc_now_text(),
        "tokens": dashboard_metric(
            token_total(stores.activity_logs, period.start, period.end, token_filters),
            token_total(stores.activity_logs, period.previous_start, period.previous_end, token_filters),
        ),
    }


def _cached_half(key, build, *, force_refresh=False, now=None):
    cached = dashboard_cache_get(key, force_refresh=force_refresh, now=now)
    if cached is not None:
        return cached, True
    payload = build()
    dashboard_cache_set(key, payload, now=now)
    return payload, False


def get_dashboard_summary(
    stores: DashboardStores,
    period: DashboardPeriod,
    token_filters=None,
    *,
    force_refresh: bool = False,
    log: Optional[Callable[..., Any]] = None,
    now=None,
) -> Tuple[Dict[str, Any], bool]:
    """Return the dashboard's KPI metrics and whether every part came from the cache.

    The token figures are cached separately from the rest, so changing a token filter
    recalculates only the token totals.
    """
    base, base_cached = _cached_half(
        ("summary-base", *period.cache_key()),
        lambda: _summary_base(stores, period, log=log),
        force_refresh=force_refresh,
        now=now,
    )
    tokens, tokens_cached = _cached_half(
        ("summary-tokens", *period.cache_key(), _filters_cache_key(token_filters)),
        lambda: _summary_tokens(stores, period, token_filters),
        force_refresh=force_refresh,
        now=now,
    )
    payload = {
        "period": period.describe(),
        "refreshed_at": min(base["computed_at"], tokens["computed_at"]),
        "users": base["users"],
        "groups": base["groups"],
        "public_workspaces": base["public_workspaces"],
        "conversations": base["conversations"],
        "document_uploads": base["document_uploads"],
        "document_processing_failures": base["document_processing_failures"],
        "tokens": tokens["tokens"],
        "pending_approvals": base["pending_approvals"],
        "status_history_available": False,
    }
    return payload, base_cached and tokens_cached


# --------------------------------------------------------------------------------------
# Insights
# --------------------------------------------------------------------------------------

def _activity_half(stores, period, *, force_refresh=False, log=None, now=None):
    def build():
        aggregate = aggregate_activity(stores.activity_logs, period)
        rankings = {
            key: rank_totals(aggregate["actors"][key], "activity_count")
            for key, _ in CONTROL_CENTER_DASHBOARD_RANKED_FIELDS
        }
        return {
            "computed_at": _utc_now_text(),
            "daily_activity": aggregate["daily_activity"],
            "actors": aggregate["actors"],
            "top_activity": _name_rankings(stores, rankings, log=log, now=now),
            "login_cells": aggregate["login_cells"],
        }

    return _cached_half(
        ("insights-activity", *period.cache_key()),
        build,
        force_refresh=force_refresh,
        now=now,
    )


def _token_half(stores, period, token_filters, *, force_refresh=False, log=None, now=None):
    def build():
        aggregate = aggregate_token_usage(stores.activity_logs, period, token_filters)
        rankings = {
            key: rank_totals(aggregate["consumers"][key], "tokens")
            for key, _ in CONTROL_CENTER_DASHBOARD_RANKED_FIELDS
        }
        return {
            "computed_at": _utc_now_text(),
            "aggregate": aggregate,
            "top_tokens": _name_rankings(stores, rankings, log=log, now=now),
        }

    return _cached_half(
        ("insights-tokens", *period.cache_key(), _filters_cache_key(token_filters)),
        build,
        force_refresh=force_refresh,
        now=now,
    )


def get_dashboard_insights(
    stores: DashboardStores,
    period: DashboardPeriod,
    token_filters=None,
    *,
    force_refresh: bool = False,
    log: Optional[Callable[..., Any]] = None,
    now=None,
) -> Tuple[Dict[str, Any], bool]:
    """Return the dashboard's chart data and rankings, and whether all of it was cached.

    Activity (sign-ins, conversations, uploads, rankings and the sign-in heatmap) is cached
    by period. Token data is cached by period and token filters, so changing a token filter
    does not re-read the rest of the period's activity.
    """
    activity, activity_cached = _activity_half(
        stores, period, force_refresh=force_refresh, log=log, now=now,
    )
    tokens, tokens_cached = _token_half(
        stores, period, token_filters, force_refresh=force_refresh, log=log, now=now,
    )
    payload = {
        "period": period.describe(),
        "refreshed_at": min(activity["computed_at"], tokens["computed_at"]),
        "daily_activity": activity["daily_activity"],
        "token_usage_by_type": tokens["aggregate"]["token_usage_by_type"],
        "token_usage_by_model": tokens["aggregate"]["token_usage_by_model"],
        "top_tokens": tokens["top_tokens"],
        "top_activity": activity["top_activity"],
        "login_heatmap": {
            "weekday_convention": DASHBOARD_LOGIN_HEATMAP_CONVENTION,
            "timezone": "UTC",
            "cells": activity["login_cells"],
        },
    }
    return payload, activity_cached and tokens_cached


# --------------------------------------------------------------------------------------
# Reports for the Control Center action
# --------------------------------------------------------------------------------------

def summary_report_rows(summary: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Flatten a dashboard summary into one row per figure, with what each figure counts."""
    period = summary.get("period") or {}
    end_day = period.get("end_date") or "the end date"
    users = summary.get("users") or {}
    uploads = summary.get("document_uploads") or {}
    rows = []

    def add(metric, figure, definition, *, comparable=True):
        figure = figure or {}
        row = {"metric": metric, "value": figure.get("value"), "definition": definition}
        if comparable:
            row.update({
                "previous_period_value": figure.get("previous"),
                "change": figure.get("delta"),
                "percent_change": figure.get("percent_change"),
            })
        rows.append(row)

    add("Total users", users.get("total"), "Accounts with a SimpleChat profile today.", comparable=False)
    add("Blocked users", users.get("blocked"), "Accounts currently denied access.", comparable=False)
    add(
        "Signed-in users",
        users.get("active"),
        "People who signed in at least once in the period; each person counts once.",
    )
    add(
        "Daily active users",
        users.get("dau"),
        f"People who signed in on {end_day} (UTC).",
        comparable=False,
    )
    add(
        "Weekly active users",
        users.get("wau"),
        f"People who signed in during the 7 days ending {end_day} (UTC).",
        comparable=False,
    )
    add(
        "Monthly active users",
        users.get("mau"),
        f"People who signed in during the 30 days ending {end_day} (UTC).",
        comparable=False,
    )
    add("Conversations created", summary.get("conversations"), "New conversations started in the period.")
    add("Document uploads", uploads.get("total"), "Documents added to any workspace in the period.")
    for workspace_type, figure in (uploads.get("by_workspace_type") or {}).items():
        add(
            f"Document uploads ({workspace_type})",
            figure,
            f"Documents added to {workspace_type} workspaces in the period.",
        )
    failures = summary.get("document_processing_failures") or {}
    if failures.get("available", True):
        add(
            "Processing failures",
            failures,
            "Documents uploaded in the period whose processing reports a failure.",
        )
    add("Tokens used", summary.get("tokens"), "Model tokens recorded in the period.")
    for label, section in (("Groups", summary.get("groups")), ("Public workspaces", summary.get("public_workspaces"))):
        section = section or {}
        add(label, section.get("total"), f"{label} that exist today.", comparable=False)
        for status, figure in (section.get("by_status") or {}).items():
            add(
                f"{label} ({status.replace('_', ' ')})",
                figure,
                f"{label} whose current status is {status.replace('_', ' ')}.",
                comparable=False,
            )
    if summary.get("pending_approvals") is not None:
        add(
            "Pending approvals",
            summary.get("pending_approvals"),
            "Approval requests waiting for a decision now.",
            comparable=False,
        )
    return rows


def daily_activity_report(
    stores: DashboardStores,
    period: DashboardPeriod,
    filters: Optional[Mapping[str, Any]] = None,
    *,
    force_refresh: bool = False,
    log: Optional[Callable[..., Any]] = None,
    now=None,
) -> List[Dict[str, Any]]:
    """Daily sign-ins, conversations and uploads, optionally narrowed to a user or workspace."""
    filters = {key: value for key, value in (filters or {}).items() if value}
    if not filters:
        activity, _ = _activity_half(stores, period, force_refresh=force_refresh, log=log, now=now)
        rows = activity["daily_activity"]
    else:
        rows, _ = _cached_half(
            ("report-daily-activity", *period.cache_key(), _filters_cache_key(filters)),
            lambda: filtered_daily_activity(stores.activity_logs, period, filters),
            force_refresh=force_refresh,
            now=now,
        )
    # Copies, so a caller that reshapes a row cannot change the cached answer.
    return [dict(row) for row in rows]


_TOKEN_ENTITY_GROUPINGS = {
    "user": "users",
    "group": "groups",
    "public_workspace": "public_workspaces",
}


def token_usage_report(
    stores: DashboardStores,
    period: DashboardPeriod,
    token_filters=None,
    *,
    group_by: str = "day",
    limit: int = CONTROL_CENTER_DASHBOARD_RANKING_LIMIT,
    force_refresh: bool = False,
    log: Optional[Callable[..., Any]] = None,
    now=None,
) -> Dict[str, Any]:
    """Token usage totalled one way: by day, model, usage type, user, group or workspace."""
    if group_by not in DASHBOARD_TOKEN_GROUPINGS:
        raise ValueError(f"group_by must be one of: {', '.join(DASHBOARD_TOKEN_GROUPINGS)}.")
    limit = max(1, min(int(limit), DASHBOARD_REPORT_MAX_ROWS))
    tokens, _ = _token_half(
        stores, period, token_filters, force_refresh=force_refresh, log=log, now=now,
    )
    aggregate = tokens["aggregate"]
    if group_by == "day":
        rows = [
            {
                "date": row["date"],
                "total_tokens": sum(int(row.get(token_type) or 0) for token_type in DASHBOARD_TOKEN_TYPES),
                **{token_type: int(row.get(token_type) or 0) for token_type in DASHBOARD_TOKEN_TYPES},
            }
            for row in aggregate["token_usage_by_type"]
        ]
    elif group_by == "model":
        rows = [
            {"model": model, "tokens": int(total)}
            for model, total in sorted(aggregate["by_model"].items(), key=lambda item: (-item[1], item[0]))[:limit]
        ]
    elif group_by == "token_type":
        rows = [
            {"token_type": token_type, "tokens": int(aggregate["by_type"].get(token_type, 0))}
            for token_type in DASHBOARD_TOKEN_TYPES
        ]
    else:
        kind = _TOKEN_ENTITY_GROUPINGS[group_by]
        ranked = rank_totals(aggregate["consumers"][kind], "tokens", limit=limit)
        names = resolve_entity_names(stores, {kind: [row["id"] for row in ranked]}, log=log, now=now)
        rows = name_ranked_rows(ranked, names.get(kind, {}))
    return {"total_tokens": int(aggregate["total"]), "rows": rows}


def top_activity_report(
    stores: DashboardStores,
    period: DashboardPeriod,
    *,
    entity: str = "users",
    limit: int = CONTROL_CENTER_DASHBOARD_RANKING_LIMIT,
    force_refresh: bool = False,
    log: Optional[Callable[..., Any]] = None,
    now=None,
) -> List[Dict[str, Any]]:
    """The users, groups or public workspaces with the most recorded actions in a period."""
    if entity not in DASHBOARD_ENTITY_KINDS:
        raise ValueError(f"entity must be one of: {', '.join(DASHBOARD_ENTITY_KINDS)}.")
    limit = max(1, min(int(limit), DASHBOARD_REPORT_MAX_ROWS))
    activity, _ = _activity_half(stores, period, force_refresh=force_refresh, log=log, now=now)
    ranked = rank_totals(activity["actors"][entity], "activity_count", limit=limit)
    names = resolve_entity_names(stores, {entity: [row["id"] for row in ranked]}, log=log, now=now)
    return name_ranked_rows(ranked, names.get(entity, {}))


def sign_in_pattern_report(
    stores: DashboardStores,
    period: DashboardPeriod,
    *,
    force_refresh: bool = False,
    log: Optional[Callable[..., Any]] = None,
    now=None,
) -> List[Dict[str, Any]]:
    """Sign-ins totalled by UTC weekday and hour across the whole period."""
    activity, _ = _activity_half(stores, period, force_refresh=force_refresh, log=log, now=now)
    return [
        {
            "weekday": DASHBOARD_WEEKDAYS[cell["weekday"]],
            "hour_utc": cell["hour"],
            "sign_ins": cell["count"],
        }
        for cell in activity["login_cells"]
    ]


def find_entities(stores: DashboardStores, kind: str, search: Any, *, limit: int = DASHBOARD_ENTITY_SEARCH_MAX_RESULTS):
    """Find users by display name or email, or groups and public workspaces by name."""
    if kind not in DASHBOARD_ENTITY_KINDS:
        raise ValueError(f"kind must be one of: {', '.join(DASHBOARD_ENTITY_KINDS)}.")
    normalized = " ".join(str(search or "").split()).lower()
    if len(normalized) < DASHBOARD_ENTITY_SEARCH_MIN_LENGTH:
        raise ValueError(f"Search for at least {DASHBOARD_ENTITY_SEARCH_MIN_LENGTH} characters.")
    if len(normalized) > DASHBOARD_ENTITY_SEARCH_MAX_LENGTH:
        raise ValueError(f"Search text may not exceed {DASHBOARD_ENTITY_SEARCH_MAX_LENGTH} characters.")
    limit = max(1, min(int(limit), DASHBOARD_ENTITY_SEARCH_MAX_RESULTS))
    container = _entity_container(stores, kind)
    if container is None:
        return []
    if kind == "users":
        query = """
        SELECT TOP @limit c.id, c.display_name, c.email FROM c
        WHERE (IS_STRING(c.display_name) AND CONTAINS(LOWER(c.display_name), @search))
           OR (IS_STRING(c.email) AND CONTAINS(LOWER(c.email), @search))
        """
    else:
        query = """
        SELECT TOP @limit c.id, c.name FROM c
        WHERE IS_STRING(c.name) AND CONTAINS(LOWER(c.name), @search)
        """
    matches = container.query_items(
        query=query,
        parameters=[
            {"name": "@limit", "value": limit},
            {"name": "@search", "value": normalized},
        ],
        enable_cross_partition_query=True,
    )
    results = []
    for document in matches:
        entity_id = document.get("id") if isinstance(document, dict) else None
        if not isinstance(entity_id, str) or not entity_id:
            continue
        described = _describe_entity(kind, document)
        result = {"id": entity_id, "name": described["name"]}
        if kind == "users":
            result["email"] = _clean_text(document.get("email"))
        results.append(result)
        if len(results) >= limit:
            break
    return results
