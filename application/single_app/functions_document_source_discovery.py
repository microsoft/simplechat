# functions_document_source_discovery.py
"""Authorized metadata discovery and admission for the v2 workspace picker."""

from document_source_selection import (
    DocumentSourceSelectionError,
    normalize_document_source_selection,
    selection_scope_fields,
    document_matches_source,
)


def source_catalog(user_id, settings, conversation_id=None):
    # These owners initialize application clients. Delay imports until a request/worker,
    # rather than making the bootstrap-free selection contract initialize config.
    from config import cosmos_conversations_container
    from functions_group import get_user_groups
    from functions_public_workspaces import get_all_public_workspaces, resolve_public_chat_workspace_ids

    catalog = [{"kind": "personal", "id": None, "name": "My workspace"}] if settings.get("enable_user_workspace", True) else []
    if settings.get("enable_group_workspaces", False):
        catalog.extend(
            {"kind": "group", "id": group["id"], "name": group.get("name") or "Group"}
            for group in get_user_groups(user_id)
        )
    if settings.get("enable_public_workspaces", False):
        allowed = set(resolve_public_chat_workspace_ids(user_id, "all", settings=settings))
        catalog.extend(
            {"kind": "public", "id": workspace["id"], "name": workspace.get("name") or "Public workspace"}
            for workspace in get_all_public_workspaces() if workspace.get("id") in allowed
        )
    if conversation_id:
        rows = list(cosmos_conversations_container.query_items(
            query="SELECT c.scope_locked, c.locked_contexts, c.context FROM c WHERE c.id = @id AND c.user_id = @user",
            parameters=[{"name": "@id", "value": conversation_id}, {"name": "@user", "value": user_id}],
            partition_key=conversation_id,
        ))
        if not rows:
            raise DocumentSourceSelectionError("That conversation is no longer available.")
        conversation = rows[0]
        if conversation.get("scope_locked"):
            contexts = conversation.get("locked_contexts") or conversation.get("context") or []
            catalog = [
                scope for scope in catalog if any(
                    item.get("scope") == scope["kind"]
                    and (scope["kind"] == "personal" or item.get("id") == scope["id"])
                    for item in contexts if isinstance(item, dict)
                )
            ]
    return catalog


def admit_document_source_selection(value, user_id, *, settings=None, conversation_id=None):
    selection = normalize_document_source_selection(value)
    if selection is None:
        return None, []
    # Runtime owner imports are delayed for the same initialization boundary as source_catalog.
    from functions_settings import get_settings
    from content_screening.access import assert_document_available

    settings = get_settings() if settings is None else settings
    catalog = source_catalog(user_id, settings, conversation_id)
    scopes = {(s["kind"], s["id"]) for s in catalog}
    if selection["mode"] == "all":
        sources = [
            {"kind": "workspace", "scope": {"kind": s["kind"], **({"id": s["id"]} if s["id"] else {})}}
            for s in catalog
        ]
    else:
        sources = selection["sources"]
        for source in sources:
            scope = source["scope"]
            if (scope["kind"], scope.get("id")) not in scopes:
                raise DocumentSourceSelectionError("A selected workspace is no longer available. Review your sources.")
            if source["kind"] == "document":
                document = assert_document_available(
                    source["id"], user_id=user_id, purpose="selection",
                    group_id=scope.get("id") if scope["kind"] == "group" else None,
                    public_workspace_id=scope.get("id") if scope["kind"] == "public" else None,
                )
                if not document_matches_source(document, source):
                    raise DocumentSourceSelectionError("A selected document does not belong to that workspace.")
    if not sources:
        raise DocumentSourceSelectionError("No document workspaces are available for this conversation.")
    return selection, sources


def prepare_document_source_selection(data, user_id, settings, conversation_id=None):
    selection, sources = admit_document_source_selection(
        data.get("document_source_selection"), user_id, settings=settings, conversation_id=conversation_id,
    )
    if selection is None:
        return
    if data.get("public_workspace_selection") is not None:
        raise DocumentSourceSelectionError("Choose either public search or document sources, not both.")
    projection = selection_scope_fields(sources)
    if any(
        field in data and data[field] not in (None, [], "")
        and data[field] != projection[field]
        for field in (
            "doc_scope", "active_group_id", "active_group_ids", "active_public_workspace_id",
            "active_public_workspace_ids", "selected_document_id", "selected_document_ids", "tags",
        )
    ):
        raise DocumentSourceSelectionError("Document sources conflict with the legacy search options.")
    data["document_source_selection"] = selection
    data.update(projection)
    return sources


def _query_metadata(container, kind, owners, user_id, settings):
    owner_field = {"personal": "user_id", "group": "group_id", "public": "public_workspace_id"}[kind]
    access = f"ARRAY_CONTAINS(@owners, c.{owner_field})"
    parameters = [{"name": "@owners", "value": owners}]
    if kind == "personal" and settings.get("enable_file_sharing", False):
        access = f"({access} OR ARRAY_CONTAINS(c.shared_user_ids, @user) OR ARRAY_CONTAINS(c.shared_user_ids, @approved_user))"
        parameters.extend([{"name": "@user", "value": user_id}, {"name": "@approved_user", "value": f"{user_id},approved"}])
    elif kind == "group":
        access = (
            f"({access} OR EXISTS(SELECT VALUE s FROM s IN c.shared_group_ids "
            "WHERE ARRAY_CONTAINS(@owners, s) OR ARRAY_CONTAINS(@approved_owners, s)))"
        )
        parameters.append({"name": "@approved_owners", "value": [f"{owner},approved" for owner in owners]})
    query = (
        "SELECT c.id, c.user_id, c.group_id, c.public_workspace_id, c.shared_user_ids, c.shared_group_ids, "
        "c.file_name, c.title, c.tags, c.version, c.revision_family_id, c.is_current_version, "
        "c.is_deleted, c.upload_date, c._ts, c.generated_artifact_promotion_status, c.status "
        f"FROM c WHERE {access} "
        "AND (NOT IS_DEFINED(c.is_deleted) OR c.is_deleted != true) "
        "AND (NOT IS_DEFINED(c.is_current_version) OR c.is_current_version != false) "
        "AND (NOT IS_DEFINED(c.generated_artifact_promotion_status) OR c.generated_artifact_promotion_status != 'pending_approval') "
        "AND (NOT IS_DEFINED(c.status) OR LOWER(c.status) != 'pending approval')"
    )
    return list(container.query_items(query=query, parameters=parameters, enable_cross_partition_query=True))


def _eligible_source_document(document):
    return (
        document.get("is_deleted") is not True
        and document.get("is_current_version") is not False
        and document.get("generated_artifact_promotion_status") != "pending_approval"
        and str(document.get("status") or "").casefold() != "pending approval"
    )


def _matches_source_workspace(document, scope, user_id, settings):
    if not document_matches_source(document, {"kind": "workspace", "scope": scope}):
        return False
    return scope["kind"] != "personal" or document.get("user_id") == user_id or (
        settings.get("enable_file_sharing", False)
        and any(entry in (user_id, f"{user_id},approved") for entry in document.get("shared_user_ids") or [])
    )


def _matches_source_query(document, query):
    return not query or any(
        isinstance(value, str) and query in value.casefold()
        for value in (document.get("file_name"), document.get("title"), *(document.get("tags") or []))
    )


def _load_source_documents(container, kind, scopes, user_id, settings):
    # These owners initialize application clients; discovery imports them only after bootstrap.
    from functions_document_access_index import query_document_access_index_documents
    from functions_documents import select_current_documents

    owners = [user_id] if kind == "personal" else [scope["id"] for scope in scopes]
    arguments = {"source_scope": kind, "settings": settings}
    arguments[{"personal": "user_id", "group": "group_ids", "public": "public_workspace_ids"}[kind]] = (
        user_id if kind == "personal" else owners
    )
    result = query_document_access_index_documents(**arguments)
    rows = result["documents"] if result.get("success") else _query_metadata(
        container, kind, owners, user_id, settings,
    )
    owner_field = {"personal": "user_id", "group": "group_id", "public": "public_workspace_id"}[kind]
    by_owner = {}
    for row in rows:
        if _eligible_source_document(row) and any(
            _matches_source_workspace(row, scope, user_id, settings) for scope in scopes
        ):
            by_owner.setdefault(row.get(owner_field), []).append(row)
    return [
        document for owner_documents in by_owner.values()
        for document in select_current_documents(owner_documents)
    ]


def discover_document_sources(user_id, settings, *, query="", workspace=None, workspace_offset=0,
                              source_offset=0, page_size=40, conversation_id=None):
    # Discovery runs after app initialization; no content/extraction owner is imported at bootstrap.
    from config import cosmos_user_documents_container, cosmos_group_documents_container, cosmos_public_documents_container
    from content_screening.access import _read_authorized_document, public_document_payload

    catalog = source_catalog(user_id, settings, conversation_id)
    containers = {
        "personal": cosmos_user_documents_container,
        "group": cosmos_group_documents_container,
        "public": cosmos_public_documents_container,
    }
    query = query.strip().casefold()
    summaries = []
    matching_documents = {}
    for kind, container in containers.items():
        scopes = [s for s in catalog if s["kind"] == kind]
        if not scopes:
            continue
        rows = _load_source_documents(container, kind, scopes, user_id, settings)
        for scope in scopes:
            name_match = bool(query and query in scope["name"].casefold())
            scoped_documents = sorted(
                (row for row in rows if _matches_source_workspace(row, scope, user_id, settings)
                 and (name_match or _matches_source_query(row, query))),
                key=lambda row: row["id"],
            )
            count = len(scoped_documents)
            if not query or count or name_match:
                key = f"{kind}:{scope['id'] or ''}"
                summaries.append({**scope, "key": key, "document_count": count,
                                  "match_reason": "workspace name" if name_match else "documents or tags" if query else None})
                matching_documents[key] = scoped_documents
    summaries.sort(key=lambda s: ({"personal": 0, "group": 1, "public": 2}[s["kind"]], s["name"].casefold(), s["key"]))
    if workspace and workspace not in {s["key"] for s in summaries}:
        raise DocumentSourceSelectionError("That workspace is not available in these results.")
    browsed = [s for s in summaries if not workspace or s["key"] == workspace]
    source_total = sum(s["document_count"] for s in browsed)
    remaining_offset = source_offset
    documents = []
    consumed = source_offset
    for scope in browsed:
        count = scope["document_count"]
        if remaining_offset >= count:
            remaining_offset -= count
            continue
        if len(documents) == page_size:
            break
        for row in matching_documents[scope["key"]][remaining_offset:]:
            if len(documents) == page_size:
                break
            consumed += 1
            try:
                fresh = _read_authorized_document(
                    row["id"], user_id, metadata_only=True, scope_type=scope["kind"],
                    group_id=scope["id"] if scope["kind"] == "group" else None,
                    public_workspace_id=scope["id"] if scope["kind"] == "public" else None,
                )
            except (LookupError, PermissionError):
                continue
            if (_eligible_source_document(fresh)
                    and _matches_source_workspace(fresh, scope, user_id, settings)
                    and (scope["match_reason"] == "workspace name" or _matches_source_query(fresh, query))):
                payload = public_document_payload(fresh)
                documents.append({"scope": scope, "document": {
                    field: payload[field] for field in (
                        "id", "file_name", "title", "tags", "version", "content_screening",
                        "document_classification", "num_chunks", "status", "enhanced_citations",
                    ) if field in payload
                }})
        remaining_offset = 0
    tags = []
    if workspace:
        tags = sorted({
            tag for row in matching_documents[workspace] for tag in row.get("tags") or []
            if isinstance(tag, str) and (not query or query in tag.casefold())
        })
    return {
        "workspaces": summaries[workspace_offset:workspace_offset + page_size],
        "eligible_workspace_count": len(catalog), "matching_workspace_count": len(summaries),
        "workspace_next": workspace_offset + page_size if workspace_offset + page_size < len(summaries) else None,
        "documents": documents, "tags": tags, "source_total": source_total,
        "source_next": consumed if consumed < source_total else None,
        "complete": True,
        "browsed_workspace": browsed[0] if workspace and browsed else None,
    }
