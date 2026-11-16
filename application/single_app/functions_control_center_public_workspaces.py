# functions_control_center_public_workspaces.py
"""Parameterized workspace queries; inventory rows use recorded metrics only."""

import re

from functions_control_center_groups import GroupRequestError, validate_group_id


WORKSPACE_LIMIT = 500
WORKSPACE_EXPORT_LIMIT = 10000
WORKSPACE_STATUSES = ("active", "locked", "upload_disabled", "inactive")
WORKSPACE_SORTS = {
    "name": "c.name",
    "owner": "c.owner.displayName",
    "documents": "c.metrics.document_metrics.total_documents",
    "tokens": "c.metrics.token_metrics.total_tokens",
    "last_activity": "c.metrics.last_activity",
    "created_at": "c.createdDate",
}
WORKSPACE_FIELDS = (
    "c.id, c.name, c.description, c.owner, c.admins, c.documentManagers, "
    "c.status, c.createdDate, c.metrics"
)


def parse_workspace_filters(values):
    filters = {}
    for key in ("search", "owner"):
        value = values.get(key, "")
        if not isinstance(value, str) or len(value) > 200:
            raise GroupRequestError("Search and owner filters may not exceed 200 characters.")
        filters[key] = value.strip().lower()
    for key, default, allowed in (
        ("status", "all", ("all", *WORKSPACE_STATUSES)),
        ("sort", "name", WORKSPACE_SORTS),
        ("direction", "asc", ("asc", "desc")),
    ):
        value = values.get(key, default)
        if value not in allowed:
            raise GroupRequestError(f"Invalid workspace {key}.")
        filters[key] = value
    for key, default, maximum in (("page", 1, 100000), ("per_page", 25, 250)):
        value = values.get(key, default)
        if isinstance(value, bool) or not re.fullmatch(r"\d{1,6}", str(value)):
            raise GroupRequestError("Page and page size must be positive whole numbers.")
        value = int(value)
        if not 1 <= value <= maximum:
            raise GroupRequestError(f"{key} must be between 1 and {maximum}.")
        filters[key] = value
    return filters


def workspace_where(filters):
    clauses, parameters = [], []
    if filters["search"]:
        clauses.append("(CONTAINS(LOWER(c.name), @search) OR CONTAINS(LOWER(c.description), @search))")
        parameters.append({"name": "@search", "value": filters["search"]})
    if filters["owner"]:
        clauses.append(
            "(CONTAINS(LOWER(c.owner.userId), @owner) OR CONTAINS(LOWER(c.owner.displayName), @owner) "
            "OR CONTAINS(LOWER(c.owner.email), @owner) OR (IS_STRING(c.owner) AND CONTAINS(LOWER(c.owner), @owner)))"
        )
        parameters.append({"name": "@owner", "value": filters["owner"]})
    if filters["status"] != "all":
        clause = "c.status = @status"
        if filters["status"] == "active":
            clause = f"(NOT IS_DEFINED(c.status) OR IS_NULL(c.status) OR c.status = '' OR {clause})"
        elif filters["status"] == "inactive":
            clause = "(IS_DEFINED(c.status) AND NOT IS_NULL(c.status) AND c.status != '' AND NOT ARRAY_CONTAINS(@known_statuses, c.status))"
            parameters.append({"name": "@known_statuses", "value": ["active", "locked", "upload_disabled"]})
        clauses.append(clause)
        if filters["status"] != "inactive":
            parameters.append({"name": "@status", "value": filters["status"]})
    return " AND ".join(clauses) or "1=1", parameters


def workspace_members(workspace):
    """Do not perform directory/user lookups for legacy string identities."""
    members = {}
    for role, entries in (
        ("Owner", [workspace.get("owner")]),
        ("Admin", workspace.get("admins") or []),
        ("DocumentManager", workspace.get("documentManagers") or []),
    ):
        for entry in entries:
            identity = entry if isinstance(entry, dict) else {"userId": entry}
            member_id = identity.get("userId")
            if member_id and member_id not in members:
                members[member_id] = {
                    "id": member_id, "display_name": identity.get("displayName") or "",
                    "email": identity.get("email") or "", "role": role,
                }
    return list(members.values())


def workspace_row(workspace):
    members = workspace_members(workspace)
    owner = next((member for member in members if member["role"] == "Owner"), None)
    metrics = workspace.get("metrics") or {}
    status = workspace.get("status") or "active"
    return {
        "id": workspace["id"], "name": workspace.get("name") or "",
        "description": workspace.get("description") or "",
        "owner": owner or {"id": None, "display_name": "", "email": ""},
        "status": status if status in WORKSPACE_STATUSES else "inactive",
        "members": len(members),
        "documents": (metrics.get("document_metrics") or {}).get("total_documents"),
        "tokens": (metrics.get("token_metrics") or {}).get("total_tokens"),
        "created_at": workspace.get("createdDate"),
        "last_activity": metrics.get("last_activity"),
        "metrics_calculated_at": metrics.get("calculated_at"),
    }


def query_workspaces(container, filters):
    """Page in Cosmos, including missing sort values last without a composite index.

    Two populations avoid Cosmos ORDER BY dropping undefined properties. Each
    ordered query uses one indexed property, so existing automatic indexes suffice.
    """
    where, parameters = workspace_where(filters)
    field = WORKSPACE_SORTS[filters["sort"]]
    present = f"IS_DEFINED({field}) AND NOT IS_NULL({field})"
    def count(condition):
        return list(container.query_items(
            query=f"SELECT VALUE COUNT(1) FROM c WHERE ({where}) AND ({condition})",
            parameters=parameters, enable_cross_partition_query=True,
        ))[0]
    total = count("1=1")
    recorded = count(present)
    size = filters["per_page"]
    pages = max(1, (total + size - 1) // size)
    page = min(filters["page"], pages)
    offset = (page - 1) * size
    rows = []
    if offset < recorded:
        take = min(size, recorded - offset)
        rows.extend(container.query_items(
            query=(f"SELECT {WORKSPACE_FIELDS} FROM c WHERE ({where}) AND ({present}) "
                   f"ORDER BY {field} {filters['direction'].upper()} OFFSET @offset LIMIT @limit"),
            parameters=parameters + [{"name": "@offset", "value": offset}, {"name": "@limit", "value": take}],
            enable_cross_partition_query=True,
        ))
    if len(rows) < size and total > recorded:
        rows.extend(container.query_items(
            query=(f"SELECT {WORKSPACE_FIELDS} FROM c WHERE ({where}) AND NOT ({present}) "
                   "ORDER BY c.id ASC OFFSET @offset LIMIT @limit"),
            parameters=parameters + [{"name": "@offset", "value": max(0, offset - recorded)},
                                    {"name": "@limit", "value": size - len(rows)}],
            enable_cross_partition_query=True,
        ))
    return {
        "workspaces": [workspace_row(row) for row in rows],
        "pagination": {"total_items": total, "page": page, "per_page": size, "total_pages": pages},
        "metrics_freshness": {"source": "recorded workspace metrics; missing values are unavailable"},
    }


def select_workspace_ids(container, data):
    """Resolve a bounded population before writing anything, never load all rows."""
    if ("workspace_ids" in data) == ("filter" in data):
        raise GroupRequestError("Provide either workspace_ids or a filter selection.")
    if "workspace_ids" in data:
        ids = data["workspace_ids"]
        if not isinstance(ids, list) or len(ids) > WORKSPACE_LIMIT:
            raise GroupRequestError("Select at most 500 workspaces.")
        ids = list(dict.fromkeys(validate_group_id(value) for value in ids))
    else:
        values = data["filter"]
        if not isinstance(values, dict) or set(values) - {"search", "status", "owner"}:
            raise GroupRequestError("Invalid workspace selection filters.")
        filters = parse_workspace_filters(values)
        where, parameters = workspace_where(filters)
        excluded = data.get("exclude_ids", [])
        if not isinstance(excluded, list) or len(excluded) > WORKSPACE_LIMIT:
            raise GroupRequestError("Provide at most 500 exclusions.")
        excluded = list(dict.fromkeys(validate_group_id(value) for value in excluded))
        parameters.append({"name": "@excluded", "value": excluded})
        ids = [row["id"] for row in container.query_items(
            query=f"SELECT TOP 501 c.id FROM c WHERE ({where}) AND NOT ARRAY_CONTAINS(@excluded, c.id)",
            parameters=parameters, enable_cross_partition_query=True,
        )]
        if len(ids) > WORKSPACE_LIMIT:
            raise GroupRequestError("Select at most 500 workspaces.")
    if not ids:
        raise GroupRequestError("Select at least one workspace.")
    return ids
