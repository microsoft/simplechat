# functions_search.py

import logging
from typing import List, Dict, Any
from config import *
from functions_content import *
from functions_public_workspaces import get_user_visible_public_workspace_docs, get_user_visible_public_workspace_ids_from_settings
from utils_cache import (
    generate_search_cache_key,
    get_cached_search_results,
    cache_search_results,
    DEBUG_ENABLED
)
from functions_debug import *
from functions_service_health import (
    SemanticSearchQuotaExceededError,
    clear_semantic_search_quota_warning,
    is_semantic_search_quota_error,
    record_semantic_search_quota_exceeded,
)

logger = logging.getLogger(__name__)


SEARCH_DEFAULT_TOP_N = 12
SEARCH_MAX_TOP_N = 500
VALID_SEARCH_SCOPES = {"all", "personal", "group", "public"}
BASE_SEARCH_SELECT_FIELDS = [
    "id",
    "document_id",
    "chunk_text",
    "chunk_id",
    "file_name",
    "version",
    "chunk_sequence",
    "upload_date",
    "document_classification",
    "document_tags",
    "page_number",
    "author",
    "chunk_keywords",
    "title",
    "chunk_summary",
]
SEARCH_SELECT_FIELDS_BY_SCOPE = {
    "personal": BASE_SEARCH_SELECT_FIELDS + ["user_id"],
    "group": BASE_SEARCH_SELECT_FIELDS + ["group_id"],
    "public": BASE_SEARCH_SELECT_FIELDS + ["public_workspace_id"],
}


def normalize_search_top_n(top_n, default_top_n=SEARCH_DEFAULT_TOP_N, max_top_n=SEARCH_MAX_TOP_N):
    """Return a bounded integer top-N value for search-style operations."""
    try:
        normalized_top_n = int(top_n)
    except (TypeError, ValueError):
        return default_top_n

    if normalized_top_n < 1:
        return default_top_n

    return min(normalized_top_n, max_top_n)


def normalize_search_scope(doc_scope, default_scope="all"):
    """Normalize search scope values to the supported set."""
    normalized_scope = str(doc_scope or default_scope).strip().lower()
    if normalized_scope not in VALID_SEARCH_SCOPES:
        return default_scope
    return normalized_scope


def normalize_search_id_list(raw_ids):
    """Normalize an optional list or comma-separated string of ids."""
    if raw_ids is None:
        return []

    if isinstance(raw_ids, str):
        candidate_ids = [value.strip() for value in raw_ids.split(",") if value.strip()]
    elif isinstance(raw_ids, list):
        candidate_ids = [str(value).strip() for value in raw_ids if str(value).strip()]
    else:
        candidate_ids = [str(raw_ids).strip()] if str(raw_ids).strip() else []

    normalized_ids = []
    seen_ids = set()
    for candidate_id in candidate_ids:
        if candidate_id in seen_ids:
            continue
        seen_ids.add(candidate_id)
        normalized_ids.append(candidate_id)

    return normalized_ids


def _resolve_public_workspace_ids_for_search(
    user_id,
    active_public_workspace_id=None,
    enforce_public_workspace_visibility=True,
):
    requested_workspace_ids = normalize_search_id_list(active_public_workspace_id)
    if requested_workspace_ids and not enforce_public_workspace_visibility:
        return requested_workspace_ids

    visible_workspace_ids = normalize_search_id_list(
        get_user_visible_public_workspace_ids_from_settings(user_id) or []
    )
    if requested_workspace_ids:
        visible_workspace_id_set = set(visible_workspace_ids)
        return [
            workspace_id
            for workspace_id in requested_workspace_ids
            if workspace_id in visible_workspace_id_set
        ]
    return visible_workspace_ids


def _build_public_workspace_filter_clause(public_workspace_ids):
    if not public_workspace_ids:
        return None
    workspace_conditions = " or ".join([
        _build_odata_eq("public_workspace_id", workspace_id)
        for workspace_id in public_workspace_ids
    ])
    return f"({workspace_conditions})"


def _normalize_document_filter_mode(document_filter_mode):
    normalized_mode = str(document_filter_mode or "intersection").strip().lower()
    if normalized_mode in {"union", "or", "additive"}:
        return "union"
    return "intersection"


def _combine_odata_filters(*filter_clauses):
    normalized_clauses = [str(clause).strip() for clause in filter_clauses if str(clause or "").strip()]
    return " and ".join(normalized_clauses)


def _build_document_content_filter(doc_id_filter, tags_filter_clause, document_filter_mode="intersection"):
    if doc_id_filter and tags_filter_clause:
        if _normalize_document_filter_mode(document_filter_mode) == "union":
            return f"({doc_id_filter} or ({tags_filter_clause}))"
        return f"{doc_id_filter} and {tags_filter_clause}"
    return doc_id_filter or tags_filter_clause or ""


def get_search_select_fields(scope_name):
    return SEARCH_SELECT_FIELDS_BY_SCOPE.get(scope_name, SEARCH_SELECT_FIELDS_BY_SCOPE["personal"])


def get_search_result_scope(result_item):
    if result_item.get("public_workspace_id"):
        return "public"
    if result_item.get("group_id"):
        return "group"
    return "personal"


def get_search_result_scope_id(result_item):
    return (
        result_item.get("public_workspace_id")
        or result_item.get("group_id")
        or result_item.get("user_id")
    )


def normalize_scores(results: List[Dict[str, Any]], index_name: str = "unknown") -> List[Dict[str, Any]]:
    """
    Normalize search scores to [0, 1] range using min-max normalization.

    This ensures scores from different indexes (user, group, public) are comparable
    when merged together. Without normalization, scores from indexes with different
    document counts or characteristics may not be directly comparable.

    Args:
        results: List of search results with 'score' field
        index_name: Name of the index for debug logging

    Returns:
        Same results list with normalized scores (original score preserved)
    """
    if not results or len(results) == 0:
        debug_print(f"No results to normalize from {index_name}", "NORMALIZE")
        return results

    scores = [r['score'] for r in results]
    min_score = min(scores)
    max_score = max(scores)
    score_range = max_score - min_score if max_score > min_score else 1.0

    debug_print(
        f"Score distribution BEFORE normalization ({index_name})",
        "NORMALIZE",
        index=index_name,
        count=len(results),
        min=f"{min_score:.4f}",
        max=f"{max_score:.4f}",
        range=f"{score_range:.4f}"
    )

    # Apply min-max normalization
    for r in results:
        original_score = r['score']
        normalized_score = (original_score - min_score) / score_range if score_range > 0 else 0.5

        # Store both scores for transparency
        r['original_score'] = original_score
        r['original_index'] = index_name
        r['score'] = normalized_score

    # Log normalized distribution
    normalized_scores = [r['score'] for r in results]
    debug_print(
        f"Score distribution AFTER normalization ({index_name})",
        "NORMALIZE",
        index=index_name,
        count=len(results),
        min=f"{min(normalized_scores):.4f}",
        max=f"{max(normalized_scores):.4f}"
    )

    return results

def build_tags_filter(tags_filter):
    """
    Build OData filter clause for tags.
    tags_filter: List of tag names (already normalized)
    Returns: String like "document_tags/any(t: t eq 'tag1') and ..." or empty string

    Tags are validated to contain only [a-z0-9_-] characters before
    being interpolated into the OData expression.
    """
    if not tags_filter or not isinstance(tags_filter, list) or len(tags_filter) == 0:
        return ""

    from functions_documents import sanitize_tags_for_filter
    safe_tags = sanitize_tags_for_filter(tags_filter)

    if not safe_tags:
        return ""

    tag_conditions = [f"document_tags/any(t: t eq '{tag}')" for tag in safe_tags]
    return " and ".join(tag_conditions)


def _escape_odata_literal(value: Any) -> str:
    """Escape a value for safe inclusion inside an OData single-quoted literal."""
    return str(value or "").replace("'", "''")


def _build_odata_eq(field_name: str, value: Any) -> str:
    """Build a simple equality clause with an escaped OData literal."""
    return f"{field_name} eq '{_escape_odata_literal(value)}'"


def _build_odata_any_eq(collection_field: str, iterator_name: str, value: Any) -> str:
    """Build an OData any(...) equality clause with an escaped literal."""
    escaped_value = _escape_odata_literal(value)
    return f"{collection_field}/any({iterator_name}: {iterator_name} eq '{escaped_value}')"

def hybrid_search(query, user_id, document_id=None, document_ids=None, top_n=12, doc_scope="all", active_group_id=None, active_group_ids=None, active_public_workspace_id=None, enable_file_sharing=True, tags_filter=None, document_filter_mode="intersection", enforce_public_workspace_visibility=True):
    """
    Hybrid search that queries the user doc index, group doc index, or public doc index
    depending on doc type.
    If document_id is None, we just search the user index for the user's docs
    OR you could unify that logic further (maybe search both).
    enable_file_sharing: If False, do not include shared_user_ids in filters.
    tags_filter: Optional list of tag names to filter documents by (AND logic - all tags must match)
    document_ids: Optional list of document IDs to filter by (OR logic - any document matches)
    document_filter_mode: "intersection" keeps document IDs and tags conjunctive; "union" makes them additive
    active_group_ids: Optional list of group IDs for multi-group search (OR logic)
    enforce_public_workspace_visibility: If False, requested public workspace IDs bypass the user's directory-visible preference.

    This function uses document-set-aware caching to ensure consistent results
    across identical queries against the same document set.
    """

    top_n = normalize_search_top_n(top_n)
    doc_scope = normalize_search_scope(doc_scope)
    document_ids = normalize_search_id_list(document_ids)
    document_filter_mode = _normalize_document_filter_mode(document_filter_mode)

    # Backwards compat: wrap single group ID into list
    if not active_group_ids and active_group_id:
        active_group_ids = [active_group_id]
    active_public_workspace_ids = _resolve_public_workspace_ids_for_search(
        user_id,
        active_public_workspace_id=active_public_workspace_id,
        enforce_public_workspace_visibility=enforce_public_workspace_visibility,
    )

    # Resolve document_ids from single document_id for backwards compat
    if document_ids and len(document_ids) > 0:
        # Use the list; also set document_id to first for any legacy code paths
        document_id = document_ids[0] if not document_id else document_id
    elif document_id:
        document_ids = [document_id]

    normalization_changed = False
    try:
        from functions_documents import normalize_document_revision_families

        if doc_scope in ("all", "personal"):
            normalization_changed = normalize_document_revision_families(user_id=user_id) or normalization_changed

        if doc_scope in ("all", "group") and active_group_ids:
            for current_group_id in active_group_ids:
                normalization_changed = normalize_document_revision_families(
                    user_id=user_id,
                    group_id=current_group_id,
                ) or normalization_changed

        if doc_scope in ("all", "public"):
            for workspace_id in active_public_workspace_ids:
                normalization_changed = normalize_document_revision_families(
                    user_id=user_id,
                    public_workspace_id=workspace_id,
                ) or normalization_changed
    except Exception as normalization_error:
        debug_print(
            f"Revision normalization failed before search: {normalization_error}",
            "SEARCH",
        )

    # Build document ID filter clause
    doc_id_filter = None
    if document_ids and len(document_ids) > 0:
        if len(document_ids) == 1:
            doc_id_filter = _build_odata_eq("document_id", document_ids[0])
        else:
            conditions = " or ".join([_build_odata_eq("document_id", did) for did in document_ids])
            doc_id_filter = f"({conditions})"

    # Generate cache key including document set fingerprints and tags filter
    cache_key = generate_search_cache_key(
        query=query,
        user_id=user_id,
        document_id=document_id,
        document_ids=document_ids,
        doc_scope=doc_scope,
        active_group_ids=active_group_ids,
        active_public_workspace_id=active_public_workspace_ids,
        top_n=top_n,
        enable_file_sharing=enable_file_sharing,
        tags_filter=tags_filter,
        document_filter_mode=document_filter_mode
    )

    # Check cache first (pass scope parameters for correct partition key)
    cached_results = None
    if not normalization_changed:
        cached_results = get_cached_search_results(
            cache_key,
            user_id,
            doc_scope,
            active_group_ids=active_group_ids,
            active_public_workspace_id=active_public_workspace_ids
        )
    if cached_results is not None:
        debug_print(
            "Returning CACHED search results",
            "SEARCH",
            query=query[:40],
            scope=doc_scope,
            result_count=len(cached_results)
        )
        logger.info(f"Returning cached search results for query: '{query[:50]}...'")
        return cached_results

    # Cache miss - proceed with search
    debug_print(
        "Cache MISS - Executing Azure AI Search",
        "SEARCH",
        query=query[:40],
        scope=doc_scope,
        top_n=top_n
    )
    logger.info(f"Cache miss - executing search for query: '{query[:50]}...'")

    # Unpack tuple from generate_embedding (returns embedding, token_usage)
    result = generate_embedding(query)
    if result is None:
        return None

    # Handle both tuple (new) and single value (backward compatibility)
    if isinstance(result, tuple):
        query_embedding, _ = result  # Ignore token_usage for search
    else:
        query_embedding = result

    if query_embedding is None:
        return None

    search_client_user = CLIENTS['search_client_user']
    search_client_group = CLIENTS['search_client_group']
    search_client_public = CLIENTS['search_client_public']

    vector_query = VectorizedQuery(
        vector=query_embedding,
        k_nearest_neighbors=top_n,
        fields="embedding"
    )

    # Build document/tag content filter. Default behavior remains intersection;
    # Assigned Knowledge passes union so explicit documents add to tag matches.
    tags_filter_clause = build_tags_filter(tags_filter)
    content_filter = _build_document_content_filter(
        doc_id_filter,
        tags_filter_clause,
        document_filter_mode=document_filter_mode,
    )

    user_access_filter = (
        f"({_build_odata_eq('user_id', user_id)} or {_build_odata_any_eq('shared_user_ids', 'u', f'{user_id},approved')})"
        if enable_file_sharing else
        _build_odata_eq('user_id', user_id)
    )
    group_access_filter = None
    if active_group_ids:
        group_conditions = " or ".join([_build_odata_eq("group_id", gid) for gid in active_group_ids])
        shared_conditions = " or ".join([
            _build_odata_any_eq("shared_group_ids", "g", f"{gid},approved")
            for gid in active_group_ids
        ])
        group_access_filter = f"({group_conditions} or {shared_conditions})"
    public_workspace_filter = _build_public_workspace_filter_clause(active_public_workspace_ids)

    try:
        if doc_scope == "all":
            user_filter = _combine_odata_filters(user_access_filter, content_filter)
            user_results = search_client_user.search(
                search_text=query,
                vector_queries=[vector_query],
                filter=user_filter,
                query_type="semantic",
                semantic_configuration_name="nexus-user-index-semantic-configuration",
                query_caption="extractive",
                query_answer="extractive",
                select=get_search_select_fields("personal")
            )

            if group_access_filter:
                group_filter = _combine_odata_filters(group_access_filter, content_filter)
                group_results = search_client_group.search(
                    search_text=query,
                    vector_queries=[vector_query],
                    filter=group_filter,
                    query_type="semantic",
                    semantic_configuration_name="nexus-group-index-semantic-configuration",
                    query_caption="extractive",
                    query_answer="extractive",
                    select=get_search_select_fields("group")
                )
            else:
                group_results = []

            if public_workspace_filter:
                public_filter = _combine_odata_filters(public_workspace_filter, content_filter)
                public_results = search_client_public.search(
                    search_text=query,
                    vector_queries=[vector_query],
                    filter=public_filter,
                    query_type="semantic",
                    semantic_configuration_name="nexus-public-index-semantic-configuration",
                    query_caption="extractive",
                    query_answer="extractive",
                    select=get_search_select_fields("public")
                )
            else:
                public_results = []

            # Extract results from each index
            user_results_final = extract_search_results(user_results, top_n)
            group_results_final = extract_search_results(group_results, top_n)
            public_results_final = extract_search_results(public_results, top_n)

            debug_print(
                "Extracted raw results from indexes",
                "SEARCH",
                user_count=len(user_results_final),
                group_count=len(group_results_final),
                public_count=len(public_results_final)
            )

            # Normalize scores from each index to [0, 1] range for fair comparison
            user_results_normalized = normalize_scores(user_results_final, "user_index")
            group_results_normalized = normalize_scores(group_results_final, "group_index")
            public_results_normalized = normalize_scores(public_results_final, "public_index")

            # Merge normalized results
            results = user_results_normalized + group_results_normalized + public_results_normalized

            debug_print(
                "Merged results from all indexes",
                "SEARCH",
                total_count=len(results)
            )

        elif doc_scope == "personal":
            user_filter = _combine_odata_filters(user_access_filter, content_filter)
            user_results = search_client_user.search(
                search_text=query,
                vector_queries=[vector_query],
                filter=user_filter,
                query_type="semantic",
                semantic_configuration_name="nexus-user-index-semantic-configuration",
                query_caption="extractive",
                query_answer="extractive",
                select=get_search_select_fields("personal")
            )
            results = extract_search_results(user_results, top_n)

        elif doc_scope == "group":
            if not group_access_filter:
                results = []
            else:
                group_filter = _combine_odata_filters(group_access_filter, content_filter)
                group_results = search_client_group.search(
                    search_text=query,
                    vector_queries=[vector_query],
                    filter=group_filter,
                    query_type="semantic",
                    semantic_configuration_name="nexus-group-index-semantic-configuration",
                    query_caption="extractive",
                    query_answer="extractive",
                    select=get_search_select_fields("group")
                )
                results = extract_search_results(group_results, top_n)

        elif doc_scope == "public":
            if public_workspace_filter:
                public_filter = _combine_odata_filters(public_workspace_filter, content_filter)
                public_results = search_client_public.search(
                    search_text=query,
                    vector_queries=[vector_query],
                    filter=public_filter,
                    query_type="semantic",
                    semantic_configuration_name="nexus-public-index-semantic-configuration",
                    query_caption="extractive",
                    query_answer="extractive",
                    select=get_search_select_fields("public")
                )
                results = extract_search_results(public_results, top_n)
            else:
                results = []
    except Exception as search_error:
        if is_semantic_search_quota_error(search_error):
            record_semantic_search_quota_exceeded(search_error, source="hybrid_search")
            raise SemanticSearchQuotaExceededError() from search_error
        raise

    # Log pre-sort statistics
    if results:
        scores = [r['score'] for r in results]
        debug_print(
            "Results BEFORE final sorting",
            "SORT",
            total_results=len(results),
            min_score=f"{min(scores):.4f}",
            max_score=f"{max(scores):.4f}",
            avg_score=f"{sum(scores)/len(scores):.4f}"
        )

        # Show top 5 results before sorting (for debugging)
        if DEBUG_ENABLED and len(results) > 0:
            import os
            if os.environ.get('DEBUG_SEARCH_CACHE', '0') == '1':
                for i, r in enumerate(results[:5]):
                    debug_print(
                        f"Pre-sort #{i+1}",
                        "SORT",
                        file=r['file_name'][:30],
                        score=f"{r['score']:.4f}",
                        original_score=f"{r.get('original_score', r['score']):.4f}",
                        index=r.get('original_index', 'N/A'),
                        chunk=r['chunk_sequence']
                    )

    # Sort with deterministic tie-breaking to ensure consistent ordering
    # Primary: score (descending)
    # Secondary: file_name (ascending) - ensures consistent order when scores are equal
    # Tertiary: chunk_sequence (ascending) - final tie-breaker for same file
    results = sorted(
        results,
        key=lambda x: (
            -x['score'],           # Negative for descending order
            x['file_name'],        # Alphabetical for tie-breaking
            x['chunk_sequence']    # Chunk order for same file
        )
    )[:top_n]

    # Log post-sort results
    debug_print(
        f"Results AFTER sorting (top {top_n})",
        "SORT",
        final_count=len(results)
    )

    # Show top results after sorting
    if DEBUG_ENABLED and len(results) > 0:
        import os
        if os.environ.get('DEBUG_SEARCH_CACHE', '0') == '1':
            for i, r in enumerate(results[:5]):
                debug_print(
                    f"Final #{i+1}",
                    "SORT",
                    file=r['file_name'][:30],
                    score=f"{r['score']:.4f}",
                    original_score=f"{r.get('original_score', r['score']):.4f}",
                    index=r.get('original_index', 'N/A'),
                    chunk=r['chunk_sequence']
                )

    # Cache the results before returning (pass scope parameters for correct partition key)
    cache_search_results(
        cache_key,
        results,
        user_id,
        doc_scope,
        active_group_ids=active_group_ids,
        active_public_workspace_id=active_public_workspace_ids
    )

    debug_print(
        "Search complete - returning results",
        "SEARCH",
        query=query[:40],
        final_result_count=len(results)
    )
    clear_semantic_search_quota_warning(source="hybrid_search")

    return results

def extract_search_results(paged_results, top_n):
    extracted = []
    for i, r in enumerate(paged_results):
        if i >= top_n:
            break
        result_scope = get_search_result_scope(r)
        extracted.append({
            "id": r["id"],
            "document_id": r.get("document_id"),
            "chunk_text": r["chunk_text"],
            "chunk_id": r["chunk_id"],
            "file_name": r["file_name"],
            "user_id": r.get("user_id"),
            "group_id": r.get("group_id"),
            "public_workspace_id": r.get("public_workspace_id"),
            "scope": result_scope,
            "scope_id": get_search_result_scope_id(r),
            "version": r["version"],
            "chunk_sequence": r["chunk_sequence"],
            "upload_date": r["upload_date"],
            "document_classification": r["document_classification"],
            "document_tags": r.get("document_tags", []),
            "page_number": r["page_number"],
            "author": r["author"],
            "chunk_keywords": r["chunk_keywords"],
            "title": r["title"],
            "chunk_summary": r["chunk_summary"],
            "score": r["@search.score"]
        })
    return extracted