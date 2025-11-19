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
    debug_print,
    DEBUG_ENABLED
)

logger = logging.getLogger(__name__)


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
        debug_print(f"[DEBUG] No results to normalize from {index_name}", "NORMALIZE")
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
        f"[DEBUG] Score distribution AFTER normalization ({index_name})",
        "NORMALIZE",
        index=index_name,
        count=len(results),
        min=f"{min(normalized_scores):.4f}",
        max=f"{max(normalized_scores):.4f}"
    )
    
    return results

def hybrid_search(query, user_id, document_id=None, top_n=12, doc_scope="all", active_group_id=None, active_public_workspace_id=None, enable_file_sharing=True):
    """
    Hybrid search that queries the user doc index, group doc index, or public doc index
    depending on doc type.
    If document_id is None, we just search the user index for the user's docs
    OR you could unify that logic further (maybe search both).
    enable_file_sharing: If False, do not include shared_user_ids in filters.
    
    This function uses document-set-aware caching to ensure consistent results
    across identical queries against the same document set.
    """
    
    # Generate cache key including document set fingerprints
    cache_key = generate_search_cache_key(
        query=query,
        user_id=user_id,
        document_id=document_id,
        doc_scope=doc_scope,
        active_group_id=active_group_id,
        active_public_workspace_id=active_public_workspace_id,
        top_n=top_n,
        enable_file_sharing=enable_file_sharing
    )
    
    # Check cache first (pass scope parameters for correct partition key)
    cached_results = get_cached_search_results(
        cache_key, 
        user_id, 
        doc_scope, 
        active_group_id, 
        active_public_workspace_id
    )
    if cached_results is not None:
        debug_print(
            "[DEBUG] Returning CACHED search results",
            "SEARCH",
            query=query[:40],
            scope=doc_scope,
            result_count=len(cached_results)
        )
        logger.info(f"Returning cached search results for query: '{query[:50]}...'")
        return cached_results
    
    # Cache miss - proceed with search
    debug_print(
        "[DEBUG] Cache MISS - Executing Azure AI Search",
        "SEARCH",
        query=query[:40],
        scope=doc_scope,
        top_n=top_n
    )
    logger.info(f"Cache miss - executing search for query: '{query[:50]}...'")
    
    query_embedding = generate_embedding(query)
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

    if doc_scope == "all":
        if document_id:
            user_results = search_client_user.search(
                search_text=query,
                vector_queries=[vector_query],
                filter=(
                    (
                        f"(user_id eq '{user_id}' or shared_user_ids/any(u: u eq '{user_id},approved')) "
                        if enable_file_sharing else
                        f"user_id eq '{user_id}' "
                    ) +
                    f"and document_id eq '{document_id}'"
                ),
                query_type="semantic",
                semantic_configuration_name="nexus-user-index-semantic-configuration",
                query_caption="extractive",
                query_answer="extractive",
                select=["id", "chunk_text", "chunk_id", "file_name", "user_id", "version", "chunk_sequence", "upload_date", "document_classification", "page_number", "author", "chunk_keywords", "title", "chunk_summary"]
            )

            group_results = search_client_group.search(
                search_text=query,
                vector_queries=[vector_query],
                filter=(
                    f"(group_id eq '{active_group_id}' or shared_group_ids/any(g: g eq '{active_group_id},approved')) and document_id eq '{document_id}'"
                ),
                query_type="semantic",
                semantic_configuration_name="nexus-group-index-semantic-configuration",
                query_caption="extractive",
                query_answer="extractive",
                select=["id", "chunk_text", "chunk_id", "file_name", "group_id", "version", "chunk_sequence", "upload_date", "document_classification", "page_number", "author", "chunk_keywords", "title", "chunk_summary"]
            )

            # Get visible public workspace IDs from user settings
            visible_public_workspace_ids = get_user_visible_public_workspace_ids_from_settings(user_id)
            
            # Create filter for visible public workspaces
            if visible_public_workspace_ids:
                # Use 'or' conditions instead of 'in' operator for OData compatibility
                workspace_conditions = " or ".join([f"public_workspace_id eq '{id}'" for id in visible_public_workspace_ids])
                public_filter = f"({workspace_conditions}) and document_id eq '{document_id}'"
            else:
                # Fallback to active_public_workspace_id if no visible workspaces
                public_filter = f"public_workspace_id eq '{active_public_workspace_id}' and document_id eq '{document_id}'"
                
            public_results = search_client_public.search(
                search_text=query,
                vector_queries=[vector_query],
                filter=public_filter,
                query_type="semantic",
                semantic_configuration_name="nexus-public-index-semantic-configuration",
                query_caption="extractive",
                query_answer="extractive",
                select=["id", "chunk_text", "chunk_id", "file_name", "public_workspace_id", "version", "chunk_sequence", "upload_date", "document_classification", "page_number", "author", "chunk_keywords", "title", "chunk_summary"]
            )
        else:
            user_results = search_client_user.search(
                search_text=query,
                vector_queries=[vector_query],
                filter=(
                    f"(user_id eq '{user_id}' or shared_user_ids/any(u: u eq '{user_id},approved')) "
                    if enable_file_sharing else
                    f"user_id eq '{user_id}' "
                ),
                query_type="semantic",
                semantic_configuration_name="nexus-user-index-semantic-configuration",
                query_caption="extractive",
                query_answer="extractive",
                select=["id", "chunk_text", "chunk_id", "file_name", "user_id", "version", "chunk_sequence", "upload_date", "document_classification", "page_number", "author", "chunk_keywords", "title", "chunk_summary"]
            )

            group_results = search_client_group.search(
                search_text=query,
                vector_queries=[vector_query],
                filter=(
                    f"(group_id eq '{active_group_id}' or shared_group_ids/any(g: g eq '{active_group_id},approved'))"
                ),
                query_type="semantic",
                semantic_configuration_name="nexus-group-index-semantic-configuration",
                query_caption="extractive",
                query_answer="extractive",
                select=["id", "chunk_text", "chunk_id", "file_name", "group_id", "version", "chunk_sequence", "upload_date", "document_classification", "page_number", "author", "chunk_keywords", "title", "chunk_summary"]
            )

            # Get visible public workspace IDs from user settings
            visible_public_workspace_ids = get_user_visible_public_workspace_ids_from_settings(user_id)
            
            # Create filter for visible public workspaces
            if visible_public_workspace_ids:
                # Use 'or' conditions instead of 'in' operator for OData compatibility
                workspace_conditions = " or ".join([f"public_workspace_id eq '{id}'" for id in visible_public_workspace_ids])
                public_filter = f"({workspace_conditions})"
            else:
                # Fallback to active_public_workspace_id if no visible workspaces
                public_filter = f"public_workspace_id eq '{active_public_workspace_id}'"
                
            public_results = search_client_public.search(
                search_text=query,
                vector_queries=[vector_query],
                filter=public_filter,
                query_type="semantic",
                semantic_configuration_name="nexus-public-index-semantic-configuration",
                query_caption="extractive",
                query_answer="extractive",
                select=["id", "chunk_text", "chunk_id", "file_name", "public_workspace_id", "version", "chunk_sequence", "upload_date", "document_classification", "page_number", "author", "chunk_keywords", "title", "chunk_summary"]
            )

        # Extract results from each index
        user_results_final = extract_search_results(user_results, top_n)
        group_results_final = extract_search_results(group_results, top_n)
        public_results_final = extract_search_results(public_results, top_n)
        
        debug_print(
            "[DEBUG] Extracted raw results from indexes",
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
            "[DEBUG] Merged results from all indexes",
            "SEARCH",
            total_count=len(results)
        )

    elif doc_scope == "personal":
        if document_id:
            user_results = search_client_user.search(
                search_text=query,
                vector_queries=[vector_query],
                filter=(
                    (
                        f"(user_id eq '{user_id}' or shared_user_ids/any(u: u eq '{user_id},approved')) "
                        if enable_file_sharing else
                        f"user_id eq '{user_id}' "
                    ) +
                    f"and document_id eq '{document_id}'"
                ),
                query_type="semantic",
                semantic_configuration_name="nexus-user-index-semantic-configuration",
                query_caption="extractive",
                query_answer="extractive",
                select=["id", "chunk_text", "chunk_id", "file_name", "user_id", "version", "chunk_sequence", "upload_date", "document_classification", "page_number", "author", "chunk_keywords", "title", "chunk_summary"]
            )
            results = extract_search_results(user_results, top_n)
        else:
            user_results = search_client_user.search(
                search_text=query,
                vector_queries=[vector_query],
                filter=(
                    f"(user_id eq '{user_id}' or shared_user_ids/any(u: u eq '{user_id},approved')) "
                    if enable_file_sharing else
                    f"user_id eq '{user_id}' "
                ),
                query_type="semantic",
                semantic_configuration_name="nexus-user-index-semantic-configuration",
                query_caption="extractive",
                query_answer="extractive",
                select=["id", "chunk_text", "chunk_id", "file_name", "user_id", "version", "chunk_sequence", "upload_date", "document_classification", "page_number", "author", "chunk_keywords", "title", "chunk_summary"]
            )
            results = extract_search_results(user_results, top_n)

    elif doc_scope == "group":
        if document_id:
            group_results = search_client_group.search(
                search_text=query,
                vector_queries=[vector_query],
                filter=(
                    f"(group_id eq '{active_group_id}' or shared_group_ids/any(g: g eq '{active_group_id},approved')) and document_id eq '{document_id}'"
                ),
                query_type="semantic",
                semantic_configuration_name="nexus-group-index-semantic-configuration",
                query_caption="extractive",
                query_answer="extractive",
                select=["id", "chunk_text", "chunk_id", "file_name", "group_id", "version", "chunk_sequence", "upload_date", "document_classification", "page_number", "author", "chunk_keywords", "title", "chunk_summary"]
            )
            results = extract_search_results(group_results, top_n)
        else:
            group_results = search_client_group.search(
                search_text=query,
                vector_queries=[vector_query],
                filter=(
                    f"(group_id eq '{active_group_id}' or shared_group_ids/any(g: g eq '{active_group_id},approved'))"
                ),
                query_type="semantic",
                semantic_configuration_name="nexus-group-index-semantic-configuration",
                query_caption="extractive",
                query_answer="extractive",
                select=["id", "chunk_text", "chunk_id", "file_name", "group_id", "version", "chunk_sequence", "upload_date", "document_classification", "page_number", "author", "chunk_keywords", "title", "chunk_summary"]
            )
            results = extract_search_results(group_results, top_n)
    
    elif doc_scope == "public":
        if document_id:
            # Get visible public workspace IDs from user settings
            visible_public_workspace_ids = get_user_visible_public_workspace_ids_from_settings(user_id)
            
            # Create filter for visible public workspaces
            if visible_public_workspace_ids:
                # Use 'or' conditions instead of 'in' operator for OData compatibility
                workspace_conditions = " or ".join([f"public_workspace_id eq '{id}'" for id in visible_public_workspace_ids])
                public_filter = f"({workspace_conditions}) and document_id eq '{document_id}'"
            else:
                # Fallback to active_public_workspace_id if no visible workspaces
                public_filter = f"public_workspace_id eq '{active_public_workspace_id}' and document_id eq '{document_id}'"
                
            public_results = search_client_public.search(
                search_text=query,
                vector_queries=[vector_query],
                filter=public_filter,
                query_type="semantic",
                semantic_configuration_name="nexus-public-index-semantic-configuration",
                query_caption="extractive",
                query_answer="extractive",
                select=["id", "chunk_text", "chunk_id", "file_name", "public_workspace_id", "version", "chunk_sequence", "upload_date", "document_classification", "page_number", "author", "chunk_keywords", "title", "chunk_summary"]
            )
            results = extract_search_results(public_results, top_n)
        else:
            # Get visible public workspace IDs from user settings
            visible_public_workspace_ids = get_user_visible_public_workspace_ids_from_settings(user_id)
            
            # Create filter for visible public workspaces
            if visible_public_workspace_ids:
                # Use 'or' conditions instead of 'in' operator for OData compatibility
                workspace_conditions = " or ".join([f"public_workspace_id eq '{id}'" for id in visible_public_workspace_ids])
                public_filter = f"({workspace_conditions})"
            else:
                # Fallback to active_public_workspace_id if no visible workspaces
                public_filter = f"public_workspace_id eq '{active_public_workspace_id}'"
                
            public_results = search_client_public.search(
                search_text=query,
                vector_queries=[vector_query],
                filter=public_filter,
                query_type="semantic",
                semantic_configuration_name="nexus-public-index-semantic-configuration",
                query_caption="extractive",
                query_answer="extractive",
                select=["id", "chunk_text", "chunk_id", "file_name", "public_workspace_id", "version", "chunk_sequence", "upload_date", "document_classification", "page_number", "author", "chunk_keywords", "title", "chunk_summary"]
            )
            results = extract_search_results(public_results, top_n)
    
    # Log pre-sort statistics
    if results:
        scores = [r['score'] for r in results]
        debug_print(
            "[DEBUG] Results BEFORE final sorting",
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
                        f"[DEBUG] Pre-sort #{i+1}",
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
        f"[DEBUG] Results AFTER sorting (top {top_n})",
        "SORT",
        final_count=len(results)
    )
    
    # Show top results after sorting
    if DEBUG_ENABLED and len(results) > 0:
        import os
        if os.environ.get('DEBUG_SEARCH_CACHE', '0') == '1':
            for i, r in enumerate(results[:5]):
                debug_print(
                    f"[DEBUG] Final #{i+1}",
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
        active_group_id, 
        active_public_workspace_id
    )
    
    debug_print(
        "[DEBUG] Search complete - returning results",
        "SEARCH",
        query=query[:40],
        final_result_count=len(results)
    )
    
    return results

def extract_search_results(paged_results, top_n):
    extracted = []
    for i, r in enumerate(paged_results):
        if i >= top_n:
            break
        extracted.append({
            "id": r["id"],
            "chunk_text": r["chunk_text"],
            "chunk_id": r["chunk_id"],
            "file_name": r["file_name"],
            "group_id": r.get("group_id"),
            "public_workspace_id": r.get("public_workspace_id"),
            "version": r["version"],
            "chunk_sequence": r["chunk_sequence"],
            "upload_date": r["upload_date"],
            "document_classification": r["document_classification"],
            "page_number": r["page_number"],
            "author": r["author"],
            "chunk_keywords": r["chunk_keywords"],
            "title": r["title"],
            "chunk_summary": r["chunk_summary"],
            "score": r["@search.score"]
        })
    return extracted