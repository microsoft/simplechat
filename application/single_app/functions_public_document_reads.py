# functions_public_document_reads.py
"""Source-authoritative, read-only public workspace document browsing.

Every read embeds the workspace in the caller's explicit target and revalidates
membership and status independently, so a stale active-workspace preference can
never redirect or widen a read. Public workspaces have no cross-workspace share
relationship in this slice, so a document belongs to exactly one workspace.

A generated artifact awaiting publication is visible only to the workspace's
managers, who see it held; to every other reader it does not exist
(``public_document_visible_to_role``).
"""

from config import cosmos_public_documents_container
from content_screening.access import (
    GENERATED_ARTIFACT_REQUEST_FIELDS,
    HELD_PUBLIC_FIELDS,
    public_document_payload,
)
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
    get_public_document_actions,
    is_current_public_document,
    public_document_family_records,
    require_public_document_read_context,
)
from functions_public_document_collaboration import (
    get_public_document_collaboration_actions,
)
from functions_public_document_policy import (
    public_document_approval_pending,
    public_document_collaboration_operations,
    public_document_visible_to_role,
)
from functions_settings import get_settings


# Public workspaces have no cross-workspace share relationship in M3A, so there
# is deliberately no "shared" place filter here.
PUBLIC_DOCUMENT_PLACE_FILTERS = frozenset({
    "all", "recent", "processing", "errors", "untagged",
})
# The status a manager sees on a generated artifact awaiting publication, as a
# group member sees one.
PUBLIC_ARTIFACT_AWAITING_APPROVAL_STATUS = "Awaiting generated artifact approval"

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


def _project_public_document(
    document, workspace_id, *, role, query_timestamp=False, include_actions=False,
    user_id=None, context=None, settings=None, collaboration_supported=None,
    current_revision=None,
):
    # A pending generated artifact the caller's role may not see is refused
    # exactly as a document that does not exist is.
    if (
        str(document.get("public_workspace_id")) != str(workspace_id)
        or not public_document_visible_to_role(document, role)
    ):
        raise PublicDocumentReadError("Document not found or access denied.", 404)
    normalized = select_current_documents([dict(document)])[0]
    payload = public_document_payload(normalized)
    if public_document_approval_pending(document):
        # A manager sees an artifact awaiting publication as the group read path
        # shows one: its held fields and the request, never its content.
        payload = {
            key: value for key, value in payload.items()
            if key in HELD_PUBLIC_FIELDS or key == "content_screening"
            or key in GENERATED_ARTIFACT_REQUEST_FIELDS
        }
        payload["status"] = PUBLIC_ARTIFACT_AWAITING_APPROVAL_STATUS
        payload["generated_artifact_promotion_status"] = "pending_approval"
        payload["enhanced_citations"] = False
    payload["public_workspace_id"] = document["public_workspace_id"]
    if include_actions:
        # Compute both action-hint arrays fresh from current authorization on
        # every response, never from storage. They are in PRIVATE_DOCUMENT_FIELDS
        # precisely so a stale stored copy cannot leak, and the v2 explorer gates
        # every per-document operation on these inline arrays. Mirrors the group
        # projector; the dedicated management-authorize and publication-state
        # endpoints remain the authoritative per-document detail reads.
        payload["document_actions"] = get_public_document_actions(
            document, user_id, workspace_id, context=context, settings=settings,
            public_payload=payload, current_revision=current_revision,
        )
        payload["document_collaboration_actions"] = get_public_document_collaboration_actions(
            document, user_id, workspace_id, context=context, settings=settings,
            supported=collaboration_supported,
        )
    # Retain a server-only sort/recent key while calculating queries. The final
    # response projection applies the screening allow-list again without it.
    if query_timestamp and "_ts" in document:
        payload["_ts"] = document["_ts"]
    if query_timestamp:
        payload["is_current_version"] = True
    return payload


def current_public_document_records(records):
    """The current revision of every document family in ``records``, as the document list shows them.

    ``select_current_documents`` chooses each family's current revision, and a revision
    marked ``is_current_version: false`` is never shown. Public workspaces share no
    documents with one another, so every record belongs to the workspace it was read for.
    The public document list and ``count_current_public_documents`` both use this, so the
    count always equals what a manager's list shows. A reader's list also leaves out a
    generated artifact awaiting publication (``public_document_visible_to_role``).
    """
    return [
        document
        for document in select_current_documents(records)
        if document.get("is_current_version") is not False
    ]


def count_current_public_documents(workspace_id):
    """The number of the workspace's documents, counted as the public document list shows them.

    Superseded revisions are not counted.
    """
    return len(current_public_document_records(_query_public_document_records(workspace_id)))


def load_public_document_browser_documents(user_id, workspace_id):
    """The current revisions the caller may see, projected. The list, its count,
    the facets and the tag counts are all computed from this one set, so an
    artifact the caller's role may not see is absent from every one of them."""
    require_public_document_read_context(user_id, workspace_id)
    records = _query_public_document_records(workspace_id)
    _workspace, role = require_public_document_read_context(user_id, workspace_id)
    current = [
        document
        for document in current_public_document_records(records)
        if public_document_visible_to_role(document, role)
    ]
    documents = [
        _project_public_document(document, workspace_id, role=role, query_timestamp=True)
        for document in current
    ]
    # Visibility follows the role the final revalidation finds, so a manager
    # demoted during this read is not answered with the manager's set.
    _workspace, current_role = require_public_document_read_context(user_id, workspace_id)
    return [document for document in documents if public_document_visible_to_role(document, current_role)]


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
    _workspace, role = require_public_document_read_context(user_id, workspace_id)
    records = _query_public_document_records(workspace_id, document_ids=[document_id])
    if not records:
        raise PublicDocumentReadError("Document not found or access denied.", 404)
    payload = _project_public_document(records[0], workspace_id, role=role)
    payload["is_current_version"] = is_current_public_document(records[0])
    require_public_document_read_context(user_id, workspace_id)
    return payload


def get_public_document_read_versions(user_id, workspace_id, document_id):
    _workspace, role = require_public_document_read_context(user_id, workspace_id)
    targets = _query_public_document_records(workspace_id, document_ids=[document_id])
    if not targets or not public_document_visible_to_role(targets[0], role):
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
        if (
            str(document.get("public_workspace_id")) != str(workspace_id)
            or not public_document_visible_to_role(document, role)
        ):
            continue
        payload = _project_public_document(document, workspace_id, role=role)
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
    context = require_public_document_read_context(user_id, workspace_id)
    settings = get_settings()
    collaboration_supported = public_document_collaboration_operations(
        context[0], context[1], settings,
    )
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
        payload = _project_public_document(
            fresh, workspace_id, role=context[1], include_actions=True, user_id=user_id,
            context=context, settings=settings,
            collaboration_supported=collaboration_supported,
            current_revision=previous.get("is_current_version"),
        )
        for field in ("revision_family_id", "is_current_version"):
            if field in previous:
                payload[field] = False if field == "is_current_version" and fresh.get(field) is False else previous[field]
        payloads.append(payload)
    require_public_document_read_context(user_id, workspace_id)
    return payloads
