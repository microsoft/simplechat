# functions_group_document_reads.py
"""Source-authoritative, read-only group document browsing.

The access index is not a completeness proof: a missing share or new revision
cannot be recovered by hydrating its hits. Explicit reads therefore use the
existing scoped source query, independently of index readiness and caches.
"""

from config import cosmos_group_documents_container
from content_screening.access import HELD_PUBLIC_FIELDS, public_document_payload
from functions_document_access_index import document_matches_list_filters
from functions_document_queries import (
    DOCUMENT_PLACE_FILTERS,
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
from functions_group import (
    find_group_by_id,
)
from functions_group_document_access import (
    GroupDocumentReadError,
    _group_document_share_status,
    _validate_group_read_id,
    get_group_document_actions,
    group_document_family_records,
    is_current_group_document,
    require_group_document_read_context,
)
from functions_settings import get_settings
from functions_group_document_policy import group_document_approval_pending
from functions_group_document_policy import GROUP_DOCUMENT_MANAGER_ROLES
from functions_group_document_collaboration import (
    COLLABORATION_OPERATION,
    get_group_document_collaboration_actions,
)
from functions_group_document_projection_fence import GROUP_DOCUMENT_PROJECTION_WRITER


def explicit_group_document_read_id(args, *, required=False):
    if "group_id" in args and "group_ids" in args:
        raise GroupDocumentReadError("Use group_id or group_ids, not both.", 400)
    if "group_id" not in args:
        if required:
            raise GroupDocumentReadError("group_id is required.", 400)
        return None
    values = args.getlist("group_id")
    if len(values) != 1:
        raise GroupDocumentReadError("Specify exactly one group_id.", 400)
    group_id = values[0]
    _validate_group_read_id(group_id)
    return group_id


def _query_group_document_records(group_id, *, document_ids=None):
    query = """
        SELECT * FROM c
        WHERE (c.group_id = @group_id
            OR ARRAY_CONTAINS(c.shared_group_ids, @group_id)
            OR EXISTS(SELECT VALUE s FROM s IN c.shared_group_ids WHERE STARTSWITH(s, @group_id_prefix)))
    """
    parameters = [
        {"name": "@group_id", "value": group_id},
        {"name": "@group_id_prefix", "value": f"{group_id},"},
    ]
    if document_ids is not None:
        if not document_ids:
            return []
        query += " AND ARRAY_CONTAINS(@document_ids, c.id)"
        parameters.append({"name": "@document_ids", "value": list(document_ids)})
    records = list(cosmos_group_documents_container.query_items(
        query=query, parameters=parameters, enable_cross_partition_query=True,
    ))
    if any(not isinstance(record, dict) or not record.get("id") or not record.get("group_id") for record in records):
        raise ValueError("Invalid group document metadata.")
    return [
        record for record in records
        if _group_document_share_status(record, group_id) is not None
        and (document_ids is None or record["id"] in document_ids)
    ]


def _project_group_document(
    document, group_id, source_groups, *, user_id, context=None, settings=None,
    query_timestamp=False, include_actions=False, current_revision=None,
):
    approval = _group_document_share_status(document, group_id)
    if approval is None:
        raise GroupDocumentReadError("Document not found or access denied.", 404)
    normalized = select_current_documents([dict(document)])[0]
    payload = public_document_payload(normalized)
    artifact_pending = group_document_approval_pending(document)
    if approval == "not_approved" or artifact_pending:
        request_fields = {
            "generated_artifact_promotion_status", "generated_artifact_requested_by_user_id",
            "generated_artifact_requested_by_display_name", "generated_artifact_requested_at",
        }
        payload = {
            key: value for key, value in payload.items()
            if key in HELD_PUBLIC_FIELDS or key == "content_screening" or (artifact_pending and key in request_fields)
        }
        payload["status"] = "Awaiting generated artifact approval" if artifact_pending else "Awaiting group share approval"
        if artifact_pending:
            payload["generated_artifact_promotion_status"] = "pending_approval"
        payload["enhanced_citations"] = False
    owner_group_id = document["group_id"]
    payload["group_id"] = owner_group_id
    payload["owner_group_id"] = owner_group_id
    payload["shared_approval_status"] = approval
    payload.pop("document_actions", None)
    payload.pop("document_collaboration_actions", None)
    payload.pop(COLLABORATION_OPERATION, None)
    payload.pop(GROUP_DOCUMENT_PROJECTION_WRITER, None)
    payload.pop("document_share_details", None)
    for private_field in (
        "generated_artifact_source_conversation_id", "generated_artifact_source_message_id",
        "generated_artifact_source_blob_container", "generated_artifact_source_blob_path",
        "generated_artifact_publication_receipt_id",
    ):
        payload.pop(private_field, None)
    owner_manager = approval == "owner" and context is not None and context[1] in GROUP_DOCUMENT_MANAGER_ROLES
    if not owner_manager:
        payload["shared_group_ids"] = (
            [f"{group_id},{approval}"] if approval in {"approved", "not_approved"} else []
        )
    payload.pop("owner_group_name", None)
    if approval != "owner":
        payload["shared_group_active_id"] = group_id
        if include_actions:
            if owner_group_id not in source_groups:
                source_groups[owner_group_id] = find_group_by_id(owner_group_id)
            payload["owner_group_name"] = str((source_groups[owner_group_id] or {}).get("name") or "Unknown Group").strip()
    else:
        payload.pop("shared_group_active_id", None)
        payload.pop("owner_group_name", None)
    if include_actions:
        payload["document_actions"] = get_group_document_actions(
            document, user_id, group_id, context=context, settings=settings,
            public_payload=payload, source_groups=source_groups,
            current_revision=current_revision,
        )
        payload["document_collaboration_actions"] = get_group_document_collaboration_actions(
            document, user_id, group_id, context=context, settings=settings,
            public_payload=payload, source_groups=source_groups, current_revision=current_revision,
        )
    # Retain a server-only sort/recent key while calculating queries. The final
    # response projection applies the screening allow-list again without it.
    if query_timestamp and "_ts" in document:
        payload["_ts"] = document["_ts"]
    if query_timestamp:
        payload["is_current_version"] = True
    return payload


def load_group_document_browser_documents(user_id, group_id):
    require_group_document_read_context(user_id, group_id)
    records = _query_group_document_records(group_id)
    context = require_group_document_read_context(user_id, group_id)
    by_owner = {}
    for record in records:
        by_owner.setdefault(record["group_id"], []).append(record)
    current = [
        document
        for family_records in by_owner.values()
        for document in select_current_documents(family_records)
        if document.get("is_current_version") is not False
    ]
    group_names = {}
    documents = [
        _project_group_document(document, group_id, group_names, user_id=user_id, context=context, query_timestamp=True)
        for document in current
    ]
    require_group_document_read_context(user_id, group_id)
    return documents


def query_group_document_list(documents, group_id, args):
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
    if place not in DOCUMENT_PLACE_FILTERS:
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
    matching = filter_documents_by_place(matching, place, group_id, owner_field="group_id")
    matching.sort(key=lambda document: (document["group_id"], document["id"]))
    matching = sort_documents(matching, sort_by=sort_by, sort_order=sort_order)
    offset = (page - 1) * page_size
    return {
        "documents": matching[offset:offset + page_size],
        "page": page,
        "page_size": page_size,
        "total_count": len(matching),
        "needs_legacy_update_check": any(
            document["group_id"] == group_id and "percentage_complete" not in document
            for document in documents
        ),
    }


def get_group_document_facets(user_id, group_id):
    documents = load_group_document_browser_documents(user_id, group_id)
    return build_document_facets(documents, group_id, owner_field="group_id")


def get_group_document_read_tags(user_id, group_id):
    facets = get_group_document_facets(user_id, group_id)
    tags = build_workspace_tags_from_counts(facets["by_tag"], user_id, group_id=group_id)
    require_group_document_read_context(user_id, group_id)
    return sorted(tags, key=lambda tag: tag["name"])


def get_group_document_read_metadata(user_id, group_id, document_id):
    require_group_document_read_context(user_id, group_id)
    records = _query_group_document_records(group_id, document_ids=[document_id])
    if not records:
        raise GroupDocumentReadError("Document not found or access denied.", 404)
    payload = _project_group_document(records[0], group_id, {}, user_id=user_id)
    payload["is_current_version"] = is_current_group_document(records[0])
    require_group_document_read_context(user_id, group_id)
    return payload


def get_group_document_read_versions(user_id, group_id, document_id):
    require_group_document_read_context(user_id, group_id)
    targets = _query_group_document_records(group_id, document_ids=[document_id])
    if not targets:
        raise GroupDocumentReadError("Document not found or access denied.", 404)
    target = targets[0]
    family = group_document_family_records(target)
    if not any(
        document.get("id") == document_id and _group_document_share_status(document, group_id) is not None
        for document in family
    ):
        raise GroupDocumentReadError("Document not found or access denied.", 404)
    current = select_current_documents(family)[0]
    current_id = current["id"] if current.get("is_current_version") is not False else None
    visible_current_id = current_id if _group_document_share_status(current, group_id) is not None else None
    family_id = target.get("revision_family_id") or visible_current_id or document_id
    group_names = {}
    versions = []
    for document in sorted(
        family, key=lambda item: (*_document_revision_sort_key(item), item["id"]), reverse=True,
    ):
        if _group_document_share_status(document, group_id) is None:
            continue
        payload = _project_group_document(document, group_id, group_names, user_id=user_id)
        payload["revision_family_id"] = family_id
        payload["is_current_version"] = document["id"] == current_id
        versions.append(payload)
    require_group_document_read_context(user_id, group_id)
    return {
        "document_id": document_id,
        "group_id": group_id,
        "revision_family_id": family_id,
        "versions": versions,
    }


def refresh_group_document_read_payloads(documents, user_id, group_id):
    """Batch-revalidate final responses in the recipient scope, never personal scope."""
    require_group_document_read_context(user_id, group_id)
    records = _query_group_document_records(
        group_id, document_ids=[document["id"] for document in documents],
    )
    context = require_group_document_read_context(user_id, group_id)
    settings = get_settings()
    by_id = {record["id"]: record for record in records}
    group_names = {}
    payloads = []
    for previous in documents:
        fresh = by_id.get(previous["id"])
        if fresh is None:
            raise GroupDocumentReadError("Document not found or access denied.", 404)
        version_changed = (
            fresh.get("version") is not None and previous.get("version") is not None
            and _document_revision_sort_key(fresh)[0] != _document_revision_sort_key(previous)[0]
        )
        if fresh["group_id"] != previous.get("group_id") or version_changed:
            raise GroupDocumentReadError("Document changed while reading. Refresh and try again.", 409)
        payload = _project_group_document(
            fresh, group_id, group_names, user_id=user_id, context=context,
            settings=settings, include_actions=True, current_revision=previous.get("is_current_version"),
        )
        for field in ("revision_family_id", "is_current_version"):
            if field in previous:
                payload[field] = False if field == "is_current_version" and fresh.get(field) is False else previous[field]
        payloads.append(payload)
    require_group_document_read_context(user_id, group_id)
    return payloads
