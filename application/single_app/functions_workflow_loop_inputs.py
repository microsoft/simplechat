# functions_workflow_loop_inputs.py
"""Read-only, currently authorized document selection for workflow loop captures.

The iterator never starts tasks or stores manifests. Its caller must consume it
fully and seal the complete selection before admitting a body. Projection rows,
Search hits, and preview responses are candidates, never authorization tokens.
Dispatch descriptors retain the requested access scope. Analyze source receipts
retain their personal-owner/group-access semantics; availability proofs retain
the actual source owner and screening generation.
"""

from collections.abc import Mapping
from datetime import datetime, timezone
import math

from content_screening.access import (
    assert_document_available,
    assert_document_chunks_available,
    document_provenance,
)
from content_screening.contracts import ScreeningConflictError, ScreeningError
from functions_analysis_access import analysis_source_snapshot
from functions_workflow_limits import (
    WORKFLOW_LOOP_ITEMS_MAX,
    WorkflowLoopInputError,
    WorkflowLoopLimitError,
    assert_workflow_loop_item_count,
    validate_workflow_max_loop_items,
)


READ_GROUP_ROLES = ("Owner", "Admin", "DocumentManager", "User")
HYBRID_CANDIDATE_WINDOW = 1000


def _input_unavailable():
    return WorkflowLoopInputError(
        "The selected workflow input is unavailable or its current access could not be confirmed."
    )


def _source_changed():
    return WorkflowLoopInputError(
        "A workflow input changed after it was selected. Start a new run to use the updated source.",
        code="workflow_loop_source_changed",
    )


def _check(check):
    if check is not None:
        check()


def _actor(workflow, actor_user_id):
    if not isinstance(workflow, Mapping) or not isinstance(actor_user_id, str) or not actor_user_id.strip():
        raise _input_unavailable()
    actor = actor_user_id.strip()
    if not workflow.get("group_id") and workflow.get("user_id") != actor:
        raise _input_unavailable()
    return actor


def _scope(workflow, value, actor):
    kind = value.get("scope_type")
    if not isinstance(kind, str) or kind not in {"personal", "group", "public"}:
        raise _input_unavailable()
    if kind == "personal":
        if value.get("scope_id") not in (None, "", actor):
            raise _input_unavailable()
        scope_id = actor
    else:
        scope_id = value.get("scope_id")
        if not isinstance(scope_id, str) or not scope_id.strip():
            raise _input_unavailable()
        scope_id = scope_id.strip()
    if workflow.get("group_id") and (kind != "group" or scope_id != workflow["group_id"]):
        raise WorkflowLoopInputError(
            "Group workflow inputs must use the workflow's own group.",
            code="workflow_loop_scope_forbidden",
        )
    return {"scope_type": kind, "scope_id": scope_id}


def _default_authorize_scope(scope, *, actor_user_id):
    # Workspace stores initialize clients; import only at an authorized read boundary.
    if scope["scope_type"] == "group":
        from functions_group import assert_group_role, check_group_status_allows_operation, find_group_by_id

        assert_group_role(actor_user_id, scope["scope_id"], allowed_roles=READ_GROUP_ROLES)
        allowed, _reason = check_group_status_allows_operation(find_group_by_id(scope["scope_id"]), "chat")
        if not allowed:
            raise PermissionError("The source group is unavailable.")
    elif scope["scope_type"] == "public":
        from functions_public_workspaces import check_public_workspace_status_allows_operation, find_public_workspace_by_id

        workspace = find_public_workspace_by_id(scope["scope_id"])
        allowed, _reason = check_public_workspace_status_allows_operation(workspace, "chat")
        if not allowed:
            raise PermissionError("The source public workspace is unavailable.")
    return True


def _authorize(scope, actor, authorize_scope, check):
    _check(check)
    try:
        allowed = (authorize_scope or _default_authorize_scope)(scope, actor_user_id=actor)
        if allowed is False:
            raise PermissionError("Source scope access was denied.")
    except WorkflowLoopInputError:
        raise
    except Exception as error:
        raise _input_unavailable() from error


def _default_read_document(*, document_id, user_id, group_id=None, public_workspace_id=None):
    return assert_document_available(
        document_id, user_id=user_id, group_id=group_id,
        public_workspace_id=public_workspace_id, purpose="workflow_loop",
    )


def _approved_share(document, field, scope_id):
    return any(value == f"{scope_id},approved" for value in document.get(field) or [])


def _entry_for_document(workflow, descriptor, *, actor, read_document, authorize_scope, check):
    scope = _scope(workflow, descriptor, actor)
    _authorize(scope, actor, authorize_scope, check)
    document_id = descriptor.get("document_id")
    if not isinstance(document_id, str) or not document_id.strip():
        raise _input_unavailable()
    kind, scope_id = scope["scope_type"], scope["scope_id"]
    _check(check)
    try:
        document = (read_document or _default_read_document)(
            document_id=document_id, user_id=actor,
            group_id=scope_id if kind == "group" else None,
            public_workspace_id=scope_id if kind == "public" else None,
        )
    except ScreeningConflictError as error:
        raise _source_changed() from error
    except Exception as error:
        raise _input_unavailable() from error
    if not isinstance(document, Mapping) or document.get("id") != document_id:
        raise _input_unavailable()
    actual_kind = "public" if document.get("public_workspace_id") else "group" if document.get("group_id") else "personal"
    if actual_kind != kind:
        raise _input_unavailable()
    if kind == "personal":
        if document.get("user_id") != actor and not _approved_share(document, "shared_user_ids", actor):
            raise _input_unavailable()
        source_scope_id = document.get("user_id")
    elif kind == "group":
        if document.get("group_id") != scope_id and not _approved_share(document, "shared_group_ids", scope_id):
            raise _input_unavailable()
        source_scope_id = scope_id
    else:
        if document.get("public_workspace_id") != scope_id:
            raise _input_unavailable()
        source_scope_id = scope_id
    if document.get("is_current_version") is False or document.get("search_visibility_state", "active") != "active":
        raise _source_changed()
    try:
        source_version = document.get("version")
        if source_version is None:
            source_version = document.get("source_version")
        source = analysis_source_snapshot([{
            "document_id": document_id, "scope": kind, "scope_id": source_scope_id,
            "source_version": source_version,
            "source_revision": document.get("_etag") or document.get("updated_at") or document.get("last_updated"),
        }])[0]
        if source["source_version"] is None and not source["source_revision"]:
            raise _source_changed()
        availability = document_provenance(document)
        if (
            not isinstance(availability.get("scope_id"), str)
            or not availability["scope_id"].strip()
            or (
                document.get("revision_family_id") is not None
                and not isinstance(document["revision_family_id"], str)
            )
        ):
            raise _input_unavailable()
    except WorkflowLoopInputError:
        raise
    except Exception as error:
        raise _input_unavailable() from error
    file_name = document.get("file_name")
    entry = {
        "document": {
            "document_id": document_id,
            "file_name": file_name[:1024] if isinstance(file_name, str) else "Document",
            "scope_type": kind,
            "scope_id": scope_id,
        },
        "source": source,
        "availability": availability,
    }
    return entry, document


def reauthorize_workflow_loop_document(
    workflow, entry, *, actor_user_id, check=None, read_document=None, authorize_scope=None,
):
    """Recheck a stored entry and require exact source AND screening-proof equality.

    Frozen entries may include engine-owned kind/index/item_id/item_sha256 fields.
    They are neither mutated nor echoed; the engine separately proves manifest
    membership and item integrity. Only the fresh source projection is returned.

    ``read_document`` is an optional authoritative reader with the same keyword
    arguments as ``_default_read_document``; it must enforce current object access
    and content-screening availability, not read a projection/cache.
    """
    actor = _actor(workflow, actor_user_id)
    if not isinstance(entry, Mapping) or not isinstance(entry.get("document"), Mapping):
        raise _input_unavailable()
    if entry.get("kind", "document") != "document":
        raise _input_unavailable()
    descriptor = entry["document"]
    requested = {
        "document_id": descriptor.get("document_id"),
        "scope_type": descriptor.get("scope_type"),
    }
    if requested["scope_type"] != "personal":
        requested["scope_id"] = descriptor.get("scope_id")
    current, _document = _entry_for_document(
        workflow, requested, actor=actor, read_document=read_document,
        authorize_scope=authorize_scope, check=check,
    )
    if any(entry.get(key) != current[key] for key in ("source", "availability", "document")):
        raise _source_changed()
    _check(check)
    return current


def _qualified_identity(entry):
    proof = entry["availability"]
    return (proof["scope_type"], proof["scope_id"], proof["document_id"])


def _logical_identity(entry, document):
    proof = entry["availability"]
    return (
        proof["scope_type"], proof["scope_id"],
        document.get("revision_family_id") or proof["document_id"],
    )


def _same_revision(left, right):
    return (
        left["availability"] == right["availability"]
        and left["source"]["source_version"] == right["source"]["source_version"]
        and left["source"]["source_revision"] == right["source"]["source_revision"]
    )


def _matches(document, filters, match_filters):
    if not filters:
        return True
    if match_filters is None:
        # Reuse the actual document-list semantics without importing service clients at startup.
        from functions_document_access_index import document_matches_list_filters

        match_filters = document_matches_list_filters
    return match_filters(document, filters)


def _read_catalog(scope, actor, *, settings, read_catalog, check):
    if read_catalog is None:
        # The catalog adapter is page-aware, read-only, and fails closed on backlog.
        from functions_document_access_index import iter_document_access_index_candidates

        read_catalog = iter_document_access_index_candidates
    return read_catalog(
        scope["scope_type"], user_id=actor,
        group_ids=[scope["scope_id"]] if scope["scope_type"] == "group" else [],
        public_workspace_ids=[scope["scope_id"]] if scope["scope_type"] == "public" else [],
        settings=settings, check=check,
    )


def _search_pages(scope, actor, content, *, settings, search_pages, excluded, check):
    if search_pages is None:
        # Do not use chat hybrid_search: its top-N bounds chunks, not documents.
        from functions_search import iter_document_query_search_pages

        search_pages = iter_document_query_search_pages
    return search_pages(
        content["query"], actor, scope_type=scope["scope_type"], scope_id=scope["scope_id"],
        mode=content["mode"], enable_file_sharing=(settings or {}).get("enable_file_sharing", True),
        exclude_document_ids=tuple(sorted(excluded)), check=check,
    )


def _search_score(hit):
    value = hit.get("@search.reranker_score")
    if value is None:
        value = hit.get("@search.score", hit.get("score"))
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise WorkflowLoopInputError(
            "The document query did not return a usable ranking.",
            code="workflow_loop_query_incomplete",
        )
    return float(value)


def _screen_hit(hit, document, scope, actor, validate_chunks, check):
    if not isinstance(hit.get("chunk_text"), str) or not hit["chunk_text"].strip():
        raise WorkflowLoopInputError(
            "The document query returned unreadable indexed content.",
            code="workflow_loop_query_incomplete",
        )
    source_field = {
        "personal": "user_id", "group": "group_id", "public": "public_workspace_id",
    }[scope["scope_type"]]
    if hit.get(source_field) != document.get(source_field):
        raise _input_unavailable()
    if hit.get("version") is None and document.get("version") is not None:
        raise WorkflowLoopInputError(
            "The document query could not confirm an indexed source revision.",
            code="workflow_loop_query_incomplete",
        )
    if hit.get("version") is not None and str(hit["version"]) != str(document.get("version") or 1):
        return False
    _check(check)
    try:
        (validate_chunks or assert_document_chunks_available)(
            [hit], document, user_id=actor,
            group_id=scope["scope_id"] if scope["scope_type"] == "group" else None,
            public_workspace_id=scope["scope_id"] if scope["scope_type"] == "public" else None,
        )
    except ScreeningConflictError as error:
        raise _source_changed() from error
    except ScreeningError as error:
        raise _input_unavailable() from error
    return True


def _keep_candidate(selected, identity, entry, rank):
    prior = selected.get(identity)
    if prior is not None:
        if not _same_revision(prior[1], entry):
            raise _source_changed()
        if rank >= prior[0]:
            return
    selected[identity] = (rank, entry)


def _trim_ranked(selected, count):
    if len(selected) > count:
        retained = sorted(selected.items(), key=lambda value: value[1][0])[:count]
        selected.clear()
        selected.update(retained)


def _query_documents(
    workflow, iterable, *, actor, limit, settings, check, read_document, authorize_scope,
    read_catalog, search_pages, match_filters, validate_chunks, capture,
):
    selection = iterable["selection"]
    ranked = selection["mode"] == "best_n"
    wanted = selection.get("count", limit)
    if wanted > limit:
        raise WorkflowLoopLimitError(
            f"Best N requests {wanted:,} documents, but this loop allows {limit:,} items. "
            f"Choose {limit:,} or fewer documents before starting a new run.",
            code="workflow_loop_item_limit_exceeded",
            limit=limit,
        )
    content = iterable.get("content")
    hybrid = bool(content and content["mode"] == "hybrid")
    capture.update({
        "query_mode": selection["mode"],
        "content_mode": content["mode"] if content else "metadata",
        "exhaustive": False,
        "ranking": "candidate_round_then_max_chunk_score" if hybrid else "max_chunk_score" if ranked else "qualified_document_identity",
        "candidate_limitations": (
            ["Hybrid retrieval uses 1,000-chunk candidate windows and the provider's "
             "50-chunk semantic reranking window. Distinct-document backfill excludes "
             "previous candidates; semantic relevance is not exhaustive corpus coverage."]
            if hybrid else []
        ),
    })
    if hybrid:
        capture.update({
            "candidate_window": HYBRID_CANDIDATE_WINDOW,
            "vector_neighbors_per_request": HYBRID_CANDIDATE_WINDOW,
            "semantic_rerank_window": 50,
            "candidate_expansion": "exclude_processed_document_ids",
        })
    selected = {}
    scopes = sorted(
        (_scope(workflow, value, actor) for value in iterable["scopes"]),
        key=lambda value: (value["scope_type"], value["scope_id"]),
    )
    for scope in scopes:
        _authorize(scope, actor, authorize_scope, check)

        def scope_check():
            _authorize(scope, actor, authorize_scope, check)

        if content is None:
            for candidate in _read_catalog(
                scope, actor, settings=settings, read_catalog=read_catalog, check=scope_check,
            ):
                scope_check()
                if not isinstance(candidate, Mapping):
                    raise _input_unavailable()
                descriptor = {**scope, "document_id": candidate.get("source_document_id") or candidate.get("document_id")}
                entry, document = _entry_for_document(
                    workflow, descriptor, actor=actor, read_document=read_document,
                    authorize_scope=authorize_scope, check=check,
                )
                if not _matches(document, iterable["filters"], match_filters):
                    continue
                _keep_candidate(selected, _logical_identity(entry, document), entry, _qualified_identity(entry))
                assert_workflow_loop_item_count(len(selected), limit=limit, count_exact=False)
            scope_check()
            continue

        local = {}
        excluded = set()
        round_index = 0
        while True:
            hits_read = 0
            new_ids = set()
            for page in _search_pages(
                scope, actor, content, settings=settings, search_pages=search_pages,
                excluded=excluded, check=scope_check,
            ):
                scope_check()
                if not isinstance(page, (list, tuple)):
                    raise WorkflowLoopInputError("The document query is incomplete.", code="workflow_loop_query_incomplete")
                for hit in page:
                    hits_read += 1
                    if not isinstance(hit, Mapping) or not isinstance(hit.get("document_id"), str):
                        raise _input_unavailable()
                    document_id = hit["document_id"]
                    if document_id in excluded:
                        continue
                    if hybrid:
                        new_ids.add(document_id)
                    entry, document = _entry_for_document(
                        workflow, {**scope, "document_id": document_id}, actor=actor,
                        read_document=read_document, authorize_scope=authorize_scope, check=check,
                    )
                    if not _matches(document, iterable["filters"], match_filters):
                        continue
                    if not _screen_hit(hit, document, scope, actor, validate_chunks, check):
                        continue
                    identity = _logical_identity(entry, document)
                    rank = (
                        (round_index, -_search_score(hit), _qualified_identity(entry))
                        if ranked else _qualified_identity(entry)
                    )
                    target = local if hybrid else selected
                    _keep_candidate(target, identity, entry, rank)
                    if not ranked:
                        assert_workflow_loop_item_count(len(selected), limit=limit, count_exact=False)
                if ranked:
                    _trim_ranked(local if hybrid else selected, wanted)
            scope_check()
            if not hybrid:
                break
            if hits_read and not new_ids:
                raise WorkflowLoopInputError(
                    "The document query could not continue to distinct documents.",
                    code="workflow_loop_query_incomplete",
                )
            if len(local) >= wanted or hits_read < HYBRID_CANDIDATE_WINDOW:
                for identity, (rank, entry) in local.items():
                    _keep_candidate(selected, identity, entry, rank)
                _trim_ranked(selected, wanted)
                break
            excluded.update(new_ids)
            round_index += 1
            capture["candidate_expansion_rounds"] = max(
                capture.get("candidate_expansion_rounds", 0), round_index,
            )
    capture["exhaustive"] = not ranked
    return [entry for _rank, entry in sorted(selected.values(), key=lambda value: value[0])]


def iter_workflow_loop_documents(
    workflow, iterable, *, actor_user_id, max_items, settings=None, check=None,
    read_document=None, authorize_scope=None, read_catalog=None, search_pages=None,
    match_filters=None, validate_chunks=None, capture_metadata=None,
):
    """Yield safe document/source/availability entries for a complete loop capture.

    ``max_items`` is the already-effective admitted admin/author ceiling. This
    helper does not reread live policy and thereby change an active run. Optional
    readers are dependency seams, not request parameters. ``capture_metadata``
    receives count precision and retrieval limitations for preview/manifest use.
    """
    actor = _actor(workflow, actor_user_id)
    limit = validate_workflow_max_loop_items(max_items)
    original_check = check
    check_failure = []
    if original_check is not None:
        def check():
            try:
                original_check()
            except Exception as error:
                check_failure.append(error)
                raise
    capture = capture_metadata if capture_metadata is not None else {}
    capture.update({
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "effective_limit": limit, "count": 0, "count_exact": False, "complete": False,
    })
    # The compiler is pure; importing lazily avoids definition/import cycles.
    from functions_workflow_definitions import WorkflowDefinitionError
    from functions_workflow_loop_schema import normalize_workflow_iterable

    if (
        isinstance(iterable, dict) and iterable.get("kind") == "documents"
        and isinstance(iterable.get("documents"), list)
        and len(iterable["documents"]) > WORKFLOW_LOOP_ITEMS_MAX
    ):
        try:
            assert_workflow_loop_item_count(len(iterable["documents"]), limit=limit)
        except WorkflowLoopLimitError as error:
            capture.update({"count": error.count, "count_exact": error.count_exact})
            raise
    try:
        normalized = normalize_workflow_iterable(iterable, max_items=WORKFLOW_LOOP_ITEMS_MAX)
    except (WorkflowDefinitionError, TypeError, ValueError) as error:
        raise WorkflowLoopInputError(
            "The workflow document selection is invalid. Review its source scopes and item limits.",
            code="workflow_loop_input_invalid",
        ) from error
    if normalized["kind"] == "input":
        raise WorkflowLoopInputError(
            "Saved collections must use the authorized workflow record reader.",
            code="workflow_loop_input_invalid",
        )
    try:
        if normalized["kind"] == "documents":
            assert_workflow_loop_item_count(len(normalized["documents"]), limit=limit)
            entries = []
            seen = set()
            for descriptor in normalized["documents"]:
                entry, document = _entry_for_document(
                    workflow, descriptor, actor=actor, read_document=read_document,
                    authorize_scope=authorize_scope, check=check,
                )
                identity = _logical_identity(entry, document)
                if identity in seen:
                    raise WorkflowLoopInputError(
                        "Selected documents must not contain duplicate document identities.",
                        code="workflow_loop_duplicate_document",
                    )
                seen.add(identity)
                entries.append(entry)
        else:
            entries = _query_documents(
                workflow, normalized, actor=actor, limit=limit, settings=settings,
                check=check, read_document=read_document, authorize_scope=authorize_scope,
                read_catalog=read_catalog, search_pages=search_pages,
                match_filters=match_filters, validate_chunks=validate_chunks, capture=capture,
            )
        for entry in entries:
            yield reauthorize_workflow_loop_document(
                workflow, entry, actor_user_id=actor, check=check,
                read_document=read_document, authorize_scope=authorize_scope,
            )
        capture.update({
            "count": len(entries), "count_exact": True, "complete": True,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
    except WorkflowLoopLimitError as error:
        capture.update({
            "count": error.count, "count_exact": error.count_exact,
            "complete": False, "exhaustive": False,
        })
        raise
    except WorkflowLoopInputError:
        capture.update({"complete": False, "exhaustive": False})
        raise
    except Exception as error:
        capture.update({"complete": False, "exhaustive": False})
        if check_failure and error is check_failure[-1]:
            raise
        raise WorkflowLoopInputError(
            "The workflow document query could not be completed. No input collection was accepted. Try again later.",
            code="workflow_loop_query_failed",
        ) from error
