# functions_control_center_activity.py
"""Bounded, parameterized activity queries independent of Flask and Azure bootstrap."""

import base64
import binascii
import csv
import hashlib
import json
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from io import StringIO


ACTIVITY_PAGE_MAX = 200
ACTIVITY_SUMMARY_MAX = 5000
ACTIVITY_EXPORT_MAX = 10000
ACTIVITY_EXPORT_HEADER = (
    "timestamp", "id", "user_id", "activity_type", "workspace_type", "user_name", "user_email",
    "activity", "summary", "workspace_id", "workspace_name", "raw_json",
)
ACTIVITY_EXPORT_READABLE_COLUMNS = 6
ACTIVITY_ORDER = " ORDER BY c.timestamp DESC, c.id DESC, c.user_id DESC"
ACTIVITY_COMPOSITE_INDEX = [
    {"path": "/timestamp", "order": "descending"},
    {"path": "/id", "order": "descending"},
    {"path": "/user_id", "order": "descending"},
]
ACTIVITY_SEARCH_FIELDS = (
    "id", "activity_type", "user_id", "admin_email", "requester_email",
    "member_email", "member_name", "description", "action", "group_name",
    "workspace_name", "public_workspace_name", "conversation_id",
    "document.file_name", "conversation.title", "usage.model",
    "group.group_name", "workspace_context.group_id",
    "workspace_context.public_workspace_id",
)
# Cosmos SQL keywords that cannot be used as dotted property names; the query grammar only
# accepts ALL, FIRST and LAST there. A dotted reserved word (c.group.group_id) is a syntax
# error that rejects the whole query, so those segments are written as c['group'].
COSMOS_RESERVED_WORDS = frozenset({
    "AND", "ARRAY", "AS", "ASC", "BETWEEN", "BY", "DESC", "DISTINCT", "ESCAPE", "EXISTS",
    "FALSE", "FROM", "GROUP", "IN", "JOIN", "LEFT", "LIKE", "LIMIT", "NOT", "NULL", "OFFSET",
    "OR", "ORDER", "RANK", "RIGHT", "SELECT", "TOP", "TRUE", "UDF", "UNDEFINED", "VALUE", "WHERE",
})


def cosmos_property_path(path, root="c"):
    """Return a Cosmos property reference that is valid even when a segment is a keyword."""
    expression = root
    for segment in path.split("."):
        expression += f"['{segment}']" if segment.upper() in COSMOS_RESERVED_WORDS else f".{segment}"
    return expression


NESTED_GROUP_ID = cosmos_property_path("group.group_id")
# Where the writers record who acted. Records from approvals, membership and status changes
# often have no top-level user_id, so the person filter and the people search match all of
# them. The display module resolves the table's Person column from the same fields.
ACTIVITY_ACTOR_FIELDS = (
    "user_id", "admin_user_id", "requester_id", "added_by_user_id", "changed_by_user_id",
    "changed_by.user_id", "removed_by.user_id", "admin.user_id", "actor.user_id",
)
# Where the writers record a group or public workspace. Status changes and member removals
# nest it (group.group_id, public_workspace.*), approvals and membership audits store it at
# the top level, user agreements store workspace_context.<type>_workspace_id, and public
# workspace ownership approvals store only a bare workspace_id. The display module resolves
# the Workspace column from the same locations.
GROUP_REFERENCE_FIELDS = (
    "workspace_context.group_id", "group_id", "group.group_id", "workspace_context.group_workspace_id",
)
PUBLIC_REFERENCE_FIELDS = (
    "workspace_context.public_workspace_id", "public_workspace_id", "public_workspace.public_workspace_id",
    "public_workspace.workspace_id", "workspace_id",
)


def parse_activity_filters(args, now=None):
    """Inclusive UTC dates, at most 366 days; normalize the dashboard link contract."""
    today = (now or datetime.now(timezone.utc)).date()
    single_date = args.get("date", "")
    end = date.fromisoformat(args.get("end_date") or single_date or today.isoformat())
    start = date.fromisoformat(
        args.get("start_date") or single_date or (end - timedelta(days=29)).isoformat()
    )
    if not 0 <= (end - start).days < 366:
        raise ValueError("Invalid date range")
    types = args.getlist("activity_type") if hasattr(args, "getlist") else [args.get("activity_type", "")]
    types = sorted({item.strip() for value in types for item in value.split(",") if item.strip() and item != "all"})
    if len(types) > 30 or any(len(item) > 100 for item in types):
        raise ValueError("Invalid activity types")
    result = {"start_date": start.isoformat(), "end_date": end.isoformat(), "activity_types": types}
    for key in ("user_id", "workspace_type", "workspace_id", "group_id", "public_workspace_id",
                "search", "token_type", "model", "status"):
        value = (args.get(key) or "").strip()
        if len(value) > (200 if key == "search" else 256):
            raise ValueError("Filter too long")
        result[key] = value
    if result["workspace_type"] == "public_workspace":
        result["workspace_type"] = "public"
    if result["workspace_type"] not in ("", "personal", "group", "public"):
        raise ValueError("Invalid workspace type")
    if result["workspace_id"] and not result["workspace_type"]:
        raise ValueError("Workspace ID needs a workspace type")
    return result


def _either(fields, template):
    """OR the same predicate over several property paths, bracket-quoting reserved words."""
    return " OR ".join(template.format(path=cosmos_property_path(field)) for field in fields)


def activity_query_context(filters, search_user_ids=()):
    """Build the WHERE clause. search_user_ids are people whose name or email matched the
    search; they widen the search only and stay outside the cursor's filter scope."""
    end_exclusive = (date.fromisoformat(filters["end_date"]) + timedelta(days=1)).isoformat()
    clauses = ["IS_STRING(c.timestamp)", "IS_STRING(c.id)",
               "(IS_STRING(c.user_id) OR IS_NULL(c.user_id) OR NOT IS_DEFINED(c.user_id))",
               "c.timestamp >= @start", "c.timestamp < @end"]
    parameters = [{"name": "@start", "value": filters["start_date"]},
                  {"name": "@end", "value": end_exclusive}]

    def add(clause, name, value):
        if value:
            clauses.append(clause)
            parameters.append({"name": name, "value": value})

    add("ARRAY_CONTAINS(@types, c.activity_type)", "@types", filters["activity_types"])
    add(f"({_either(ACTIVITY_ACTOR_FIELDS, '{path} = @user')})", "@user", filters["user_id"])
    workspace_type = filters["workspace_type"]
    group_id = filters["group_id"] or (filters["workspace_id"] if workspace_type == "group" else "")
    public_id = filters["public_workspace_id"] or (filters["workspace_id"] if workspace_type == "public" else "")
    # A specific group or public workspace matches every record that references it, however
    # its writer recorded the workspace type; a type on its own matches the same references.
    if workspace_type == "personal":
        add("c.workspace_type = @workspace_type", "@workspace_type", workspace_type)
        add("c.user_id = @personal", "@personal", filters["workspace_id"])
    elif workspace_type == "group" and not group_id:
        clauses.append(f"(c.workspace_type = 'group' OR {_either(GROUP_REFERENCE_FIELDS, 'IS_STRING({path})')})")
    elif workspace_type == "public" and not public_id:
        clauses.append("(c.workspace_type IN ('public', 'public_workspace') OR "
                       f"{_either(PUBLIC_REFERENCE_FIELDS, 'IS_STRING({path})')})")
    add(f"({_either(GROUP_REFERENCE_FIELDS, '{path} = @group')})", "@group", group_id)
    add(f"({_either(PUBLIC_REFERENCE_FIELDS, '{path} = @public')})", "@public", public_id)
    add("c.token_type = @token_type", "@token_type", filters["token_type"])
    add("c.usage.model = @model", "@model", filters["model"])
    if filters["status"] == "failed":
        add("(CONTAINS(c.status, @status, true) OR CONTAINS(c.status, 'error', true) "
            "OR CONTAINS(c.document.status, @status, true) OR CONTAINS(c.document.status, 'error', true))",
            "@status", filters["status"])
    else:
        add("(c.status = @status OR c.status_change.new_status = @status OR c.document.status = @status)",
            "@status", filters["status"])
    if filters["search"]:
        search = _either(ACTIVITY_SEARCH_FIELDS, "CONTAINS({path}, @search, true)")
        if search_user_ids:
            search += " OR " + _either(ACTIVITY_ACTOR_FIELDS, "ARRAY_CONTAINS(@search_people, {path})")
            parameters.append({"name": "@search_people", "value": list(search_user_ids)})
        add(f"({search})", "@search", filters["search"])
    return " AND ".join(clauses), parameters


def activity_filter_scope(filters):
    return hashlib.sha256(json.dumps(filters, sort_keys=True).encode("utf-8")).hexdigest()


def encode_activity_cursor(record, filters, snapshot):
    envelope = {"v": 1, "scope": activity_filter_scope(filters), "snapshot": snapshot,
                "timestamp": record["timestamp"], "id": record["id"], "user_id": record.get("user_id"),
                "user_defined": "user_id" in record}
    return base64.urlsafe_b64encode(json.dumps(envelope, separators=(",", ":")).encode()).decode()


def decode_activity_cursor(value, filters):
    try:
        if not isinstance(value, str) or len(value) > 4096:
            raise ValueError("Invalid cursor")
        cursor = json.loads(base64.b64decode(value.encode("ascii"), altchars=b"-_", validate=True))
        if not isinstance(cursor, dict) or cursor.get("v") != 1 or cursor.get("scope") != activity_filter_scope(filters):
            raise ValueError("Wrong cursor scope")
        for key in ("timestamp", "id", "snapshot"):
            if not isinstance(cursor.get(key), str) or not 1 <= len(cursor[key]) <= 256:
                raise ValueError("Invalid cursor field")
        if cursor.get("user_id") is not None and (
            not isinstance(cursor["user_id"], str) or len(cursor["user_id"]) > 256
        ):
            raise ValueError("Invalid partition")
        if not isinstance(cursor.get("user_defined"), bool):
            raise ValueError("Invalid partition presence")
        datetime.fromisoformat(cursor["timestamp"].replace("Z", "+00:00"))
        datetime.fromisoformat(cursor["snapshot"].replace("Z", "+00:00"))
        return cursor
    except (ValueError, TypeError, UnicodeError, binascii.Error) as ex:
        raise ValueError("Invalid activity cursor") from ex


def query_activity_rows(container, filters, limit, cursor=None, snapshot=None, projection="*", search_user_ids=()):
    """Three-part key: IDs are only unique inside a user partition, not globally."""
    where, parameters = activity_query_context(filters, search_user_ids)
    snapshot = cursor["snapshot"] if cursor else snapshot or datetime.now(timezone.utc).isoformat()
    # Compare calendar instants from both legacy naive-UTC and aware-UTC writers.
    # The cursor keeps the stored timestamp verbatim so lexical ordering and seeking agree.
    snapshot = snapshot.removesuffix("+00:00").removesuffix("Z")
    where += " AND c.timestamp <= @snapshot"
    parameters.append({"name": "@snapshot", "value": snapshot})
    if cursor:
        partition_tie = "(NOT IS_DEFINED(c.user_id) OR IS_NULL(c.user_id))"
        if cursor["user_id"] is not None:
            partition_tie = f"(c.user_id < @cursor_user OR {partition_tie})"
            parameters.append({"name": "@cursor_user", "value": cursor["user_id"]})
        elif cursor["user_defined"]:
            partition_tie = "NOT IS_DEFINED(c.user_id)"
        else:
            partition_tie = "false"
        where += (
            " AND (c.timestamp < @cursor_time OR (c.timestamp = @cursor_time AND "
            f"(c.id < @cursor_id OR (c.id = @cursor_id AND {partition_tie}))))"
        )
        parameters.extend([{"name": "@cursor_time", "value": cursor["timestamp"]},
                           {"name": "@cursor_id", "value": cursor["id"]}])
    parameters.append({"name": "@limit", "value": limit})
    rows = list(container.query_items(
        query=f"SELECT TOP @limit {projection} FROM c WHERE {where}{ACTIVITY_ORDER}",
        parameters=parameters, enable_cross_partition_query=True, max_item_count=min(limit, ACTIVITY_PAGE_MAX),
    ))
    return rows, snapshot


def activity_page(container, filters, page_size=50, cursor_value=None, search_user_ids=()):
    if not 1 <= page_size <= ACTIVITY_PAGE_MAX:
        raise ValueError("Invalid page size")
    cursor = decode_activity_cursor(cursor_value, filters) if cursor_value else None
    rows, snapshot = query_activity_rows(
        container, filters, page_size + 1, cursor=cursor, search_user_ids=search_user_ids,
    )
    more = len(rows) > page_size
    records = rows[:page_size]
    return {
        "items": records, "page_size": page_size, "snapshot": snapshot,
        "next_cursor": encode_activity_cursor(records[-1], filters, snapshot) if more else None,
    }


def activity_summary(container, filters, search_user_ids=()):
    """Bounded projection, not COUNT/GROUP BY scans. Disclose sampling in the contract."""
    rows, snapshot = query_activity_rows(
        container, filters, ACTIVITY_SUMMARY_MAX + 1, projection="c.timestamp, c.id, c.user_id, c.activity_type",
        search_user_ids=search_user_ids,
    )
    truncated = len(rows) > ACTIVITY_SUMMARY_MAX
    rows = rows[:ACTIVITY_SUMMARY_MAX]
    facets = Counter(
        row["activity_type"] if isinstance(row.get("activity_type"), str) and row["activity_type"] else "unknown"
        for row in rows
    )
    start = date.fromisoformat(filters["start_date"])
    days = (date.fromisoformat(filters["end_date"]) - start).days + 1
    width = max(1, (days + 30) // 31)
    bins = { (start + timedelta(days=offset)).isoformat(): 0 for offset in range(0, days, width) }
    for row in rows:
        day = date.fromisoformat(row["timestamp"][:10])
        key = (start + timedelta(days=((day - start).days // width) * width)).isoformat()
        if key in bins:
            bins[key] += 1
    return {"facets": [{"activity_type": key, "count": value} for key, value in sorted(facets.items())],
            "histogram": [{"date": key, "count": value} for key, value in bins.items()],
            "bucket_days": width, "sample_size": len(rows), "sample_limit": ACTIVITY_SUMMARY_MAX,
            "truncated": truncated, "snapshot": snapshot}


def activity_csv_cell(value):
    text = "" if value is None else str(value)
    if text.startswith(("=", "+", "-", "@", "\t", "\r")) or text.lstrip().startswith(("=", "+", "-", "@")):
        text = "'" + text
    return text


def activity_csv_stream(container, filters, first_rows, snapshot, search_user_ids=(), present_rows=None):
    """Stream page-sized reads with a final status row when the export hits its cap.

    The first five columns and the trailing raw JSON keep their 0.261.284 positions. The
    readable columns between them come from present_rows(rows), which returns one
    (user_name, user_email, activity, summary, workspace_id, workspace_name) per row.
    """
    output = StringIO()
    writer = csv.writer(output)
    blank = ("",) * ACTIVITY_EXPORT_READABLE_COLUMNS

    def line(values):
        output.seek(0)
        output.truncate(0)
        writer.writerow([activity_csv_cell(value) for value in values])
        return output.getvalue()

    yield line(ACTIVITY_EXPORT_HEADER)
    rows = first_rows
    count = 0
    while rows:
        batch = rows[:ACTIVITY_EXPORT_MAX - count]
        readable = list(present_rows(batch)) if present_rows else []
        if len(readable) != len(batch):
            readable = [blank] * len(batch)
        for row, columns in zip(batch, readable):
            yield line((row.get("timestamp"), row.get("id"), row.get("user_id"), row.get("activity_type"),
                        row.get("workspace_type"), *columns, json.dumps(row, ensure_ascii=False)))
            count += 1
        if count >= ACTIVITY_EXPORT_MAX:
            yield line(("", "", "", "export_limit_reached", "", *blank,
                        f"Export capped at {ACTIVITY_EXPORT_MAX} rows; narrow the filters."))
            return
        cursor = decode_activity_cursor(encode_activity_cursor(rows[-1], filters, snapshot), filters)
        rows, _ = query_activity_rows(
            container, filters, min(ACTIVITY_PAGE_MAX, ACTIVITY_EXPORT_MAX - count), cursor,
            search_user_ids=search_user_ids,
        )
