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


def _query_metadata(container, where, parameters, *, fields, offset=None, limit=None):
    query = f"SELECT {fields} FROM c WHERE {where}"
    if offset is not None:
        query += " ORDER BY c.id OFFSET @offset LIMIT @limit"
        parameters = parameters + [{"name": "@offset", "value": offset}, {"name": "@limit", "value": limit}]
    return list(container.query_items(query=query, parameters=parameters, enable_cross_partition_query=True))


def discover_document_sources(user_id, settings, *, query="", workspace=None, workspace_offset=0,
                              source_offset=0, page_size=40, conversation_id=None):
    # Discovery runs after app initialization; no content/extraction owner is imported at bootstrap.
    from config import cosmos_user_documents_container, cosmos_group_documents_container, cosmos_public_documents_container
    from content_screening.access import public_document_payload

    catalog = source_catalog(user_id, settings, conversation_id)
    containers = {
        "personal": cosmos_user_documents_container,
        "group": cosmos_group_documents_container,
        "public": cosmos_public_documents_container,
    }
    query = query.strip().casefold()
    summaries = []
    predicates = {}
    for kind, container in containers.items():
        scopes = [s for s in catalog if s["kind"] == kind]
        if not scopes:
            continue
        owner_field = {"personal": "user_id", "group": "group_id", "public": "public_workspace_id"}[kind]
        ids = [user_id] if kind == "personal" else [s["id"] for s in scopes]
        named_ids = [user_id if kind == "personal" else s["id"] for s in scopes if query and query in s["name"].casefold()]
        # Source metadata only. Generated outputs awaiting publication are not workspace sources.
        eligibility = (
            "(NOT IS_DEFINED(c.is_deleted) OR c.is_deleted != true) "
            "AND (NOT IS_DEFINED(c.is_current_version) OR c.is_current_version != false) "
            "AND (NOT IS_DEFINED(c.generated_artifact_promotion_status) OR c.generated_artifact_promotion_status != 'pending_approval') "
            "AND (NOT IS_DEFINED(c.status) OR LOWER(c.status) != 'pending approval')"
        )
        access = f"ARRAY_CONTAINS(@owners, c.{owner_field})"
        parameters = [{"name": "@owners", "value": ids}]
        if kind == "personal" and settings.get("enable_file_sharing", False):
            access = f"({access} OR ARRAY_CONTAINS(c.shared_user_ids, @user) OR ARRAY_CONTAINS(c.shared_user_ids, @approved_user))"
            parameters.extend([{"name": "@user", "value": user_id}, {"name": "@approved_user", "value": f"{user_id},approved"}])
        where = f"{access} AND {eligibility}"
        metadata_match = (
            "CONTAINS(c.title, @query, true) OR CONTAINS(c.file_name, @query, true) "
            "OR EXISTS(SELECT VALUE t FROM t IN c.tags WHERE CONTAINS(t, @query, true))"
        )
        if query:
            name_match = "ARRAY_LENGTH(@named) > 0" if kind == "personal" else f"ARRAY_CONTAINS(@named, c.{owner_field})"
            where += f" AND ({name_match} OR {metadata_match})"
            parameters.extend([{"name": "@named", "value": named_ids}, {"name": "@query", "value": query}])
        counts = list(container.query_items(
            query=f"SELECT c.{owner_field} AS owner, COUNT(1) AS count FROM c WHERE {where} GROUP BY c.{owner_field}",
            parameters=parameters, enable_cross_partition_query=True,
        ))
        by_owner = {row["owner"]: row["count"] for row in counts}
        if kind == "personal":
            by_owner = {user_id: sum(row["count"] for row in counts)}
        if kind == "group":
            shared_owner = "REPLACE(s, ',approved', '')"
            shared_where = (
                f"ARRAY_CONTAINS(@owners, {shared_owner}) AND c.group_id != {shared_owner} AND {eligibility}"
            )
            if query:
                shared_where += f" AND (ARRAY_CONTAINS(@named, {shared_owner}) OR {metadata_match})"
            shared_counts = list(container.query_items(
                query=f"SELECT {shared_owner} AS owner, COUNT(1) AS count FROM c JOIN s IN c.shared_group_ids WHERE {shared_where} GROUP BY {shared_owner}",
                parameters=parameters, enable_cross_partition_query=True,
            ))
            for row in shared_counts:
                by_owner[row["owner"]] = by_owner.get(row["owner"], 0) + row["count"]
        for scope in scopes:
            owner = user_id if kind == "personal" else scope["id"]
            count = by_owner.get(owner, 0)
            name_match = bool(query and query in scope["name"].casefold())
            if not query or count or name_match:
                key = f"{kind}:{scope['id'] or ''}"
                summaries.append({**scope, "key": key, "document_count": count,
                                  "match_reason": "workspace name" if name_match else "documents or tags" if query else None})
                scope_access = access if kind == "personal" else f"c.{owner_field} = @owner"
                scope_parameters = parameters + [{"name": "@owner", "value": owner}]
                if kind == "group":
                    scope_access = "(c.group_id = @owner OR ARRAY_CONTAINS(c.shared_group_ids, @owner) OR ARRAY_CONTAINS(c.shared_group_ids, @approved_owner))"
                    scope_parameters.append({"name": "@approved_owner", "value": f"{owner},approved"})
                scoped_where = f"{scope_access} AND {eligibility}"
                if query and not name_match:
                    scoped_where += f" AND ({metadata_match})"
                predicates[key] = (container, scoped_where, scope_parameters)
    summaries.sort(key=lambda s: ({"personal": 0, "group": 1, "public": 2}[s["kind"]], s["name"].casefold(), s["key"]))
    if workspace and workspace not in {s["key"] for s in summaries}:
        raise DocumentSourceSelectionError("That workspace is not available in these results.")
    browsed = [s for s in summaries if not workspace or s["key"] == workspace]
    source_total = sum(s["document_count"] for s in browsed)
    remaining_offset = source_offset
    documents = []
    for scope in browsed:
        count = scope["document_count"]
        if remaining_offset >= count:
            remaining_offset -= count
            continue
        if len(documents) == page_size:
            break
        container, where, parameters = predicates[scope["key"]]
        rows = _query_metadata(
            container, where, parameters,
            fields="c.id, c.file_name, c.title, c.tags, c.version, c.content_screening, c.document_classification",
            offset=remaining_offset, limit=page_size - len(documents),
        )
        documents.extend({"scope": scope, "document": public_document_payload(row)} for row in rows)
        remaining_offset = 0
    tags = []
    if workspace:
        container, where, parameters = predicates[workspace]
        tag_rows = list(container.query_items(
            query=f"SELECT DISTINCT VALUE t FROM c JOIN t IN c.tags WHERE {where}",
            parameters=parameters, enable_cross_partition_query=True,
        ))
        tags = sorted(t for t in tag_rows if isinstance(t, str) and (not query or query in t.casefold()))
    return {
        "workspaces": summaries[workspace_offset:workspace_offset + page_size],
        "eligible_workspace_count": len(catalog), "matching_workspace_count": len(summaries),
        "workspace_next": workspace_offset + page_size if workspace_offset + page_size < len(summaries) else None,
        "documents": documents, "tags": tags, "source_total": source_total,
        "source_next": source_offset + len(documents) if source_offset + len(documents) < source_total else None,
        "complete": True,
        "browsed_workspace": browsed[0] if workspace and browsed else None,
    }
