# functions_control_center_groups.py
"""Server-side group inventory and validated selection for Control Center."""

import re
from datetime import datetime, timezone


GROUP_STATUSES = ("active", "locked", "upload_disabled", "inactive")
GROUP_SORTS = ("name", "owner", "members", "documents", "tokens", "last_activity")
GROUP_BULK_LIMIT = 500
GROUP_SNAPSHOT_TTL = 90
GROUP_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
GROUP_FILTER_KEYS = {
    "search", "status", "status_filter", "owner", "members_min", "members_max",
    "has_documents", "created_from", "created_to", "activity_from", "activity_to",
}


class GroupRequestError(ValueError):
    """A reviewed, user-safe validation message, distinct from storage failures."""


def validate_group_id(value):
    if not isinstance(value, str) or not GROUP_ID_PATTERN.fullmatch(value):
        raise GroupRequestError("Invalid group or member ID.")
    return value


def parse_group_filters(values):
    """Accept only documented filters; never interpolate caller values into SQL."""
    filters = {}
    for key in ("search", "owner"):
        value = values.get(key, "")
        if not isinstance(value, str) or len(value) > 200:
            raise GroupRequestError("Search and owner filters may not exceed 200 characters.")
        filters[key] = value.strip().casefold()
    filters["status"] = values.get("status", values.get("status_filter", "all"))
    if filters["status"] not in ("all", *GROUP_STATUSES):
        raise GroupRequestError("Invalid group status filter.")
    filters["has_documents"] = values.get("has_documents", "all")
    if filters["has_documents"] not in ("all", "yes", "no"):
        raise GroupRequestError("Invalid documents filter.")
    for key in ("members_min", "members_max"):
        raw = values.get(key)
        if raw in (None, ""):
            filters[key] = None
        elif isinstance(raw, bool) or not re.fullmatch(r"\d{1,7}", str(raw)):
            raise GroupRequestError("Member bounds must be non-negative whole numbers.")
        else:
            filters[key] = int(raw)
    if (filters["members_min"] is not None and filters["members_max"] is not None
            and filters["members_min"] > filters["members_max"]):
        raise GroupRequestError("Minimum members may not exceed maximum members.")
    for prefix in ("created", "activity"):
        for suffix in ("from", "to"):
            key = f"{prefix}_{suffix}"
            raw = values.get(key)
            if not raw:
                filters[key] = None
                continue
            if not isinstance(raw, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
                raise GroupRequestError("Date filters must use YYYY-MM-DD.")
            try:
                datetime.strptime(raw, "%Y-%m-%d")
            except ValueError as ex:
                raise GroupRequestError("Invalid calendar date.") from ex
            filters[key] = raw
        if filters[f"{prefix}_from"] and filters[f"{prefix}_to"]:
            if filters[f"{prefix}_from"] > filters[f"{prefix}_to"]:
                raise GroupRequestError("Date range start may not follow its end.")
    filters["sort"] = values.get("sort", "name")
    filters["direction"] = values.get("direction", "asc")
    if filters["sort"] not in GROUP_SORTS or filters["direction"] not in ("asc", "desc"):
        raise GroupRequestError("Invalid group sort or direction.")
    return filters


def group_members(group):
    """Project actual membership roles, including an owner omitted from legacy users."""
    owner = group.get("owner") or {}
    users = list(group.get("users") or [])
    if owner.get("id") and not any(user.get("userId") == owner["id"] for user in users):
        users.append({"userId": owner["id"], **{k: owner.get(k, "") for k in ("email", "displayName")}})
    members = {}
    for user in users:
        user_id = user.get("userId")
        if not user_id:
            continue
        role = ("Owner" if user_id == owner.get("id") else
                "Admin" if user_id in (group.get("admins") or []) else
                "DocumentManager" if user_id in (group.get("documentManagers") or []) else "User")
        members[user_id] = {
            "id": user_id, "display_name": user.get("displayName", ""),
            "email": user.get("email", ""), "role": role,
        }
    return list(members.values())


def group_row(group, documents, tokens, last_activity):
    owner = group.get("owner") or {}
    metrics = group.get("metrics") or {}
    return {
        "id": group["id"],
        "name": group.get("name") or "",
        "description": group.get("description") or "",
        "owner": {
            "id": owner.get("id"), "email": owner.get("email") or "",
            "display_name": owner.get("displayName") or owner.get("display_name") or "",
        },
        "status": group.get("status") if group.get("status") in GROUP_STATUSES else "active",
        "members": len(group_members(group)),
        "documents": documents,
        "tokens": tokens,
        "created_at": group.get("createdDate"),
        "last_activity": last_activity,
        "metrics_calculated_at": metrics.get("calculated_at"),
    }


def load_group_inventory(groups_container, documents_container, activity_container):
    """Four batched queries, independent of row count. Fail rather than invent totals."""
    groups = list(groups_container.query_items(
        query=("SELECT c.id, c.name, c.description, c.owner, c.users, c.admins, "
               "c.documentManagers, c.status, c.createdDate, c.metrics FROM c"),
        enable_cross_partition_query=True,
    ))
    documents = {
        row["group_id"]: int(row.get("total") or 0)
        for row in documents_container.query_items(
            query=("SELECT c.group_id, COUNT(1) AS total FROM c "
                   "WHERE c.type = 'document_metadata' AND IS_DEFINED(c.group_id) GROUP BY c.group_id"),
            enable_cross_partition_query=True,
        )
    }
    tokens = {
        row["group_id"]: int(row.get("total") or 0)
        for row in activity_container.query_items(
            query=("SELECT c.workspace_context.group_id AS group_id, SUM(c.usage.total_tokens) AS total "
                   "FROM c WHERE c.activity_type = 'token_usage' "
                   "AND IS_DEFINED(c.workspace_context.group_id) AND IS_NUMBER(c.usage.total_tokens) "
                   "GROUP BY c.workspace_context.group_id"),
            enable_cross_partition_query=True,
        )
    }
    # The writers use three group locations. One coalesced expression avoids duplicate
    # records and includes admin CSV and approval events that use top-level group_id.
    group_expression = (
        "IIF(IS_STRING(c.group_id) AND c.group_id != '', c.group_id, "
        "IIF(IS_STRING(c.group.group_id) AND c.group.group_id != '', "
        "c.group.group_id, c.workspace_context.group_id))"
    )
    activity_times = {
        row["group_id"]: row.get("last_activity")
        for row in activity_container.query_items(
            query=(f"SELECT {group_expression} AS group_id, MAX(c.timestamp) AS last_activity FROM c "
                   f"WHERE IS_STRING({group_expression}) AND {group_expression} != '' "
                   f"GROUP BY {group_expression}"),
            enable_cross_partition_query=True,
        )
    }
    calculated_at = datetime.now(timezone.utc).isoformat()
    return {
        "rows": [group_row(group, documents.get(group["id"], 0), tokens.get(group["id"], 0),
                           activity_times.get(group["id"])) for group in groups],
        "calculated_at": calculated_at,
    }


def filter_group_inventory(rows, filters):
    """Filter before sorting or paging; missing dates do not match a date window."""
    def matches(row):
        if filters["search"] and filters["search"] not in f"{row['name']} {row['description']}".casefold():
            return False
        if filters["status"] != "all" and row["status"] != filters["status"]:
            return False
        owner = row["owner"]
        if filters["owner"] and filters["owner"] not in (
            f"{owner['id'] or ''} {owner['email']} {owner['display_name']}".casefold()
        ):
            return False
        for key, comparator in (("members_min", lambda x, y: x < y), ("members_max", lambda x, y: x > y)):
            if filters[key] is not None and comparator(row["members"], filters[key]):
                return False
        if filters["has_documents"] == "yes" and row["documents"] == 0:
            return False
        if filters["has_documents"] == "no" and row["documents"] != 0:
            return False
        for prefix, field in (("created", "created_at"), ("activity", "last_activity")):
            date = str(row.get(field) or "")[:10]
            if filters[f"{prefix}_from"] and (not date or date < filters[f"{prefix}_from"]):
                return False
            if filters[f"{prefix}_to"] and (not date or date > filters[f"{prefix}_to"]):
                return False
        return True

    selected = [row for row in rows if matches(row)]
    field = filters["sort"]
    def sort_value(row):
        value = row["owner"]["display_name"] or row["owner"]["email"] if field == "owner" else row.get(field)
        return value.casefold() if isinstance(value, str) else value
    present = [row for row in selected if sort_value(row) is not None]
    missing = [row for row in selected if sort_value(row) is None]
    present.sort(key=lambda row: row["id"])
    present.sort(key=sort_value, reverse=filters["direction"] == "desc")
    missing.sort(key=lambda row: row["id"])
    return present + missing


def validate_group_status_payload(data):
    if not isinstance(data, dict):
        raise GroupRequestError("A JSON object is required.")
    status = data.get("status")
    reason = data.get("reason", "")
    if status not in GROUP_STATUSES:
        raise GroupRequestError("Invalid group status.")
    if not isinstance(reason, str) or len(reason) > 2000:
        raise GroupRequestError("Reason must be text no longer than 2000 characters.")
    reason = reason.strip()
    if status in ("locked", "inactive") and not reason:
        raise GroupRequestError("A reason is required for locked or inactive status.")
    return status, reason


def select_group_bulk_ids(data, inventory_loader):
    """Resolve exclusions and cap the complete population before any mutation."""
    if ("group_ids" in data) == ("filter" in data):
        raise GroupRequestError("Provide either group_ids or a filter selection.")
    if "group_ids" in data:
        ids = data["group_ids"]
        if not isinstance(ids, list) or len(ids) > GROUP_BULK_LIMIT:
            raise GroupRequestError("Bulk actions are limited to 500 groups.")
        ids = list(dict.fromkeys(validate_group_id(value) for value in ids))
    else:
        values = data["filter"]
        exclusions = data.get("exclude_ids", [])
        if not isinstance(values, dict) or set(values) - GROUP_FILTER_KEYS:
            raise GroupRequestError("Invalid group selection filters.")
        if not isinstance(exclusions, list) or len(exclusions) > GROUP_BULK_LIMIT:
            raise GroupRequestError("Invalid exclusion list.")
        excluded = {validate_group_id(value) for value in exclusions}
        filters = parse_group_filters(values)
        ids = [row["id"] for row in filter_group_inventory(inventory_loader()["rows"], filters)
               if row["id"] not in excluded]
    if not ids:
        raise GroupRequestError("Select at least one group.")
    if len(ids) > GROUP_BULK_LIMIT:
        raise GroupRequestError("Bulk actions are limited to 500 groups.")
    return ids
