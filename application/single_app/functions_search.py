# functions_search.py

from config import *
from functions_content import *
from functions_public_workspaces import get_user_visible_public_workspace_docs, get_user_visible_public_workspace_ids_from_settings

def hybrid_search(query, user_id, document_id=None, top_n=12, doc_scope="all", active_group_id=None, active_public_workspace_id=None, enable_file_sharing=True):
    """
    Hybrid search that queries the user doc index, group doc index, or public doc index
    depending on doc type.
    If document_id is None, we just search the user index for the user's docs
    OR you could unify that logic further (maybe search both).
    enable_file_sharing: If False, do not include shared_user_ids in filters.
    """
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

        user_results_final = extract_search_results(user_results, top_n)
        group_results_final = extract_search_results(group_results, top_n)
        public_results_final = extract_search_results(public_results, top_n)
        results = user_results_final + group_results_final + public_results_final

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
    
    results = sorted(results, key=lambda x: x['score'], reverse=True)[:top_n]

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