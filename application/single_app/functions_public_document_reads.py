# functions_public_document_reads.py
"""Source-authoritative, read-only public workspace document browsing.

Every read embeds the workspace in the caller's explicit target and revalidates
membership and status independently, so a stale active-workspace preference can
never redirect or widen a read. Public workspaces have no cross-workspace share
relationship in this slice, so a document belongs to exactly one workspace.
"""

from config import cosmos_public_documents_container
from content_screening.access import public_document_payload
from functions_document_access_index import document_matches_list_filters
from functions_document_queries import (
    build_document_facets,
    filter_documents_by_place,
)
from functions_documents import (
    ALLOWED_DOCUMENT_SORT_FIELDS,
    _document_revision_sort_key,
    build_workspace_tags_from_counts,
    sanitize_tags_for_filter,
    select_current_documents,
    sort_documents,
)
from functions_public_document_access import (
    PublicDocumentReadError,
    is_current_public_document,
    public_document_family_records,
    require_public_document_read_context,
)


# Public workspaces have no cross-workspace share relationship in M3A, so there
# is deliberately no "shared" place filter here.
PUBLIC_DOCUMENT_PLACE_FILTERS = frozenset({
    "all", "recent", "processing", "errors", "untagged",
})

PUBLIC_DOCUMENT_LIST_QUERY_PARAMS = frozenset({
    "place", "search", "tags", "classification", "page", "page_size",
    "sort_by", "sort_order", "author", "keywords", "abstract",
})
PUBLIC_DOCUMENT_NO_QUERY_PARAMS = frozenset()


def validate_public_read_query(args, allowed):
    """Reject unknown or duplicated query parameters with no silent fallback."""
    for key, values in args.lists():
        if key not in allowed:
            raise PublicDocumentReadError("Unrecognized query parameter.", 400)
        if len(values) != 1:
            raise PublicDocumentReadError("Duplicate query parameter.", 400)


def _query_public_document_records(workspace_id, *, document_ids=None):
    query = "SELECT * FROM c WHERE c.public_workspace_id = @workspace_id"
    parameters = [{"name": "@workspace_id", "value": workspace_id}]
    if document_ids is not None:
        if not document_ids:
            return []
        query += " AND ARRAY_CONTAINS(@document_ids, c.id)"
        parameters.append({"name": "@document_ids", "value": list(document_ids)})
    records = list(cosmos_public_documents_container.query_items(
        query=query, parameters=parameters, enable_cross_partition_query=True,
    ))
    if any(
        not isinstance(record, dict) or not record.get("id") or not record.get("public_workspace_id")
        for record in records
    ):
        raise ValueError("Invalid public document metadata.")
    return [record for record in records if str(record["public_workspace_id"]) == str(workspace_id)]


def _project_public_document(document, workspace_id, *, query_timestamp=False, include_actions=False):
    if str(document.get("public_workspace_id")) != str(workspace_id):
        raise PublicDocumentReadError("Document not found or access denied.", 404)
    normalized = select_current_documents([dict(document)])[0]
    payload = public_document_payload(normalized)
    payload["public_workspace_id"] = document["public_workspace_id"]
    if include_actions:
        # Read-only slice: no management verbs are advertised yet, but the key
        # is present so the client always reads a concrete action list.
        payload["document_actions"] = []
    # Retain a server-only sort/recent key while calculating queries. The final
    # response projection applies the screening allow-list again without it.
    if query_timestamp and "_ts" in document:
        payload["_ts"] = document["_ts"]
    if query_timestamp:
        payload["is_current_version"] = True
    return payload


def load_public_document_browser_documents(user_id, workspace_id):
    require_public_document_read_context(user_id, workspace_id)
    records = _query_public_document_records(workspace_id)
    require_public_document_read_context(user_id, workspace_id)
    current = [
        document
        for document in select_current_documents(records)
        if document.get("is_current_version") is not False
    ]
    documents = [
        _project_public_document(document, workspace_id, query_timestamp=True)
        for document in current
    ]
    require_public_document_read_context(user_id, workspace_id)
    return documents


def query_public_document_list(documents, workspace_id, args):
    page = max(1, args.get("page", default=1, type=int))
    page_size = args.get("page_size", default=10, type=int)
    if page_size < 1:
        page_size = 10
    sort_by = args.get("sort_by", "_ts")
    if sort_by not in ALLOWED_DOCUMENT_SORT_FIELDS:
        sort_by = "_ts"
    sort_order = args.get("sort_order", "desc").lower()
    if sort_order not in ("asc", "desc"):
        sort_order = "desc"
    place = args.get("place", "all").strip().lower()
    if place not in PUBLIC_DOCUMENT_PLACE_FILTERS:
        place = "all"
    filters = {
        name: args.get(name) for name in ("search", "classification", "author", "keywords", "abstract")
    }
    filters.update({
        "tags": sanitize_tags_for_filter(args.get("tags")),
        "classification_none_matches_literal": False,
        "array_match_mode": "contains",
    })
    matching = [
        document for document in documents
        if document_matches_list_filters(document, filters)
    ]
    matching = filter_documents_by_place(matching, place, workspace_id, owner_field="public_workspace_id")
    matching.sort(key=lambda document: (document["public_workspace_id"], document["id"]))
    matching = sort_documents(matching, sort_by=sort_by, sort_order=sort_order)
    offset = (page - 1) * page_size
    return {
        "documents": matching[offset:offset + page_size],
        "page": page,
        "page_size": page_size,
        "total_count": len(matching),
        "needs_legacy_update_check": any(
            "percentage_complete" not in document for document in documents
        ),
    }


def get_public_document_facets(user_id, workspace_id):
    documents = load_public_document_browser_documents(user_id, workspace_id)
    return build_document_facets(documents, workspace_id, owner_field="public_workspace_id")


def get_public_document_read_tags(user_id, workspace_id):
    facets = get_public_document_facets(user_id, workspace_id)
    tags = build_workspace_tags_from_counts(facets["by_tag"], user_id, public_workspace_id=workspace_id)
    require_public_document_read_context(user_id, workspace_id)
    return sorted(tags, key=lambda tag: tag["name"])


def get_public_document_read_metadata(user_id, workspace_id, document_id):
    require_public_document_read_context(user_id, workspace_id)
    records = _query_public_document_records(workspace_id, document_ids=[document_id])
    if not records:
        raise PublicDocumentReadError("Document not found or access denied.", 404)
    payload = _project_public_document(records[0], workspace_id)
    payload["is_current_version"] = is_current_public_document(records[0])
    require_public_document_read_context(user_id, workspace_id)
    return payload


def get_public_document_read_versions(user_id, workspace_id, document_id):
    require_public_document_read_context(user_id, workspace_id)
    targets = _query_public_document_records(workspace_id, document_ids=[document_id])
    if not targets:
        raise PublicDocumentReadError("Document not found or access denied.", 404)
    target = targets[0]
    family = public_document_family_records(target)
    if not any(
        document.get("id") == document_id and str(document.get("public_workspace_id")) == str(workspace_id)
        for document in family
    ):
        raise PublicDocumentReadError("Document not found or access denied.", 404)
    current = select_current_documents(family)[0]
    current_id = current["id"] if current.get("is_current_version") is not False else None
    family_id = target.get("revision_family_id") or current_id or document_id
    versions = []
    for document in sorted(
        family, key=lambda item: (*_document_revision_sort_key(item), item["id"]), reverse=True,
    ):
        if str(document.get("public_workspace_id")) != str(workspace_id):
            continue
        payload = _project_public_document(document, workspace_id)
        payload["revision_family_id"] = family_id
        payload["is_current_version"] = document["id"] == current_id
        versions.append(payload)
    require_public_document_read_context(user_id, workspace_id)
    return {
        "document_id": document_id,
        "public_workspace_id": workspace_id,
        "revision_family_id": family_id,
        "versions": versions,
    }


def refresh_public_document_read_payloads(documents, user_id, workspace_id):
    """Batch-revalidate final responses in the explicit target workspace scope."""
    require_public_document_read_context(user_id, workspace_id)
    records = _query_public_document_records(
        workspace_id, document_ids=[document["id"] for document in documents],
    )
    require_public_document_read_context(user_id, workspace_id)
    by_id = {record["id"]: record for record in records}
    payloads = []
    for previous in documents:
        fresh = by_id.get(previous["id"])
        if fresh is None:
            raise PublicDocumentReadError("Document not found or access denied.", 404)
        version_changed = (
            fresh.get("version") is not None and previous.get("version") is not None
            and _document_revision_sort_key(fresh)[0] != _document_revision_sort_key(previous)[0]
        )
        if str(fresh.get("public_workspace_id")) != str(workspace_id) or version_changed:
            raise PublicDocumentReadError("Document changed while reading. Refresh and try again.", 409)
        payload = _project_public_document(fresh, workspace_id, include_actions=True)
        for field in ("revision_family_id", "is_current_version"):
            if field in previous:
                payload[field] = False if field == "is_current_version" and fresh.get(field) is False else previous[field]
        payloads.append(payload)
    require_public_document_read_context(user_id, workspace_id)
    return payloads
