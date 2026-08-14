# functions_search_service.py
"""Shared search, retrieval, and summarization services for documents."""

import io
import json
import logging
import math
import os
from typing import Any, Dict, List, Optional

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from azure.cosmos.exceptions import CosmosResourceNotFoundError
from openai import AzureOpenAI

from config import (
    CLIENTS,
    cognitive_services_scope,
    cosmos_conversations_container,
    cosmos_messages_container,
)
from functions_appinsights import log_event
from functions_debug import debug_print
from functions_documents import get_document_record, get_ordered_document_chunks
from functions_group import get_user_groups
from functions_model_endpoint_identity_header import build_model_endpoint_identity_headers
from functions_public_workspaces import get_user_visible_public_workspace_ids_from_settings
from functions_search import (
    SEARCH_DEFAULT_TOP_N,
    SEARCH_MAX_TOP_N,
    hybrid_search,
    normalize_search_id_list,
    normalize_search_scope,
    normalize_search_top_n,
)
from functions_settings import get_settings, get_user_settings


SUMMARY_DEFAULT_WINDOW_UNIT = "pages"
SUMMARY_DEFAULT_WINDOW_SUMMARY_TARGET = "2 pages"
SUMMARY_DEFAULT_FINAL_TARGET = "2 pages"
SUMMARY_DEFAULT_REDUCTION_BATCH_SIZE = 4
SUMMARY_DEFAULT_MAX_REDUCTION_ROUNDS = 4
SUMMARY_DEFAULT_MIN_PAGE_WINDOW = 5
SUMMARY_DEFAULT_MAX_PAGE_WINDOW = 25
SUMMARY_DEFAULT_CHUNK_WINDOW = 20
SUMMARY_MAX_WINDOW_SIZE = 50
CHAT_UPLOAD_CHUNK_WORD_SIZE = 400
CHAT_UPLOAD_CHUNK_WORD_OVERLAP = 40
MIXED_SOURCE_TABULAR_CANDIDATE_TOP_N = 50
MIXED_SOURCE_TABULAR_CANDIDATE_LIMIT = 100
MIXED_SOURCE_TABULAR_EXTENSIONS = frozenset({".csv", ".xls", ".xlsx", ".xlsm"})


def _coerce_positive_int(value, default_value, min_value=1, max_value=None):
    try:
        normalized_value = int(value)
    except (TypeError, ValueError):
        normalized_value = default_value

    if normalized_value < min_value:
        normalized_value = default_value
    if max_value is not None:
        normalized_value = min(normalized_value, max_value)
    return normalized_value


def _normalize_window_unit(window_unit, chunks):
    normalized_window_unit = str(window_unit or SUMMARY_DEFAULT_WINDOW_UNIT).strip().lower()
    if normalized_window_unit == "pages":
        has_page_numbers = any(chunk.get("page_number") is not None for chunk in chunks or [])
        if has_page_numbers:
            return "pages"
    return "chunks"


def _get_user_accessible_group_ids(user_id):
    if not user_id:
        return []

    try:
        return normalize_search_id_list([
            group.get("id")
            for group in get_user_groups(user_id)
            if group.get("id")
        ])
    except Exception as exc:
        log_event(
            f"[SEARCH_SERVICE] Failed to resolve authorized group ids: {exc}",
            extra={"user_id": user_id},
            level=logging.WARNING,
            exceptionTraceback=True,
        )
        return []


def _resolve_active_group_ids(user_id, active_group_ids=None, fallback_to_memberships=False):
    accessible_group_ids = _get_user_accessible_group_ids(user_id)
    authorized_group_ids = set(accessible_group_ids)
    requested_group_ids = normalize_search_id_list(active_group_ids)
    if requested_group_ids:
        return [group_id for group_id in requested_group_ids if group_id in authorized_group_ids]

    user_settings = get_user_settings(user_id)
    active_group_id = str(user_settings.get("settings", {}).get("activeGroupOid") or "").strip()
    if active_group_id and active_group_id in authorized_group_ids:
        return [active_group_id]

    if not fallback_to_memberships:
        return []

    return accessible_group_ids


def _resolve_public_workspace_ids(user_id, active_public_workspace_id=None):
    try:
        visible_workspace_ids = normalize_search_id_list(get_user_visible_public_workspace_ids_from_settings(user_id))
    except Exception as exc:
        log_event(
            f"[SEARCH_SERVICE] Failed to resolve visible public workspace ids: {exc}",
            extra={"user_id": user_id},
            level=logging.WARNING,
            exceptionTraceback=True,
        )
        return []

    requested_workspace_ids = normalize_search_id_list(active_public_workspace_id)
    if requested_workspace_ids:
        visible_workspace_id_set = set(visible_workspace_ids)
        return [
            workspace_id
            for workspace_id in requested_workspace_ids
            if workspace_id in visible_workspace_id_set
        ]

    return visible_workspace_ids


def _serialize_document(document_item, scope_name):
    return {
        "id": document_item.get("id"),
        "file_name": document_item.get("file_name"),
        "title": document_item.get("title"),
        "abstract": document_item.get("abstract"),
        "version": document_item.get("version"),
        "revision_family_id": document_item.get("revision_family_id"),
        "document_classification": document_item.get("document_classification"),
        "tags": document_item.get("tags", []),
        "scope": scope_name,
        "scope_id": (
            document_item.get("public_workspace_id")
            or document_item.get("group_id")
            or document_item.get("user_id")
        ),
        "group_id": document_item.get("group_id"),
        "public_workspace_id": document_item.get("public_workspace_id"),
        "user_id": document_item.get("user_id"),
        "conversation_id": document_item.get("conversation_id"),
        "source_type": document_item.get("source_type") or ("chat_upload" if scope_name == "chat" else "workspace_document"),
    }


def _load_chat_upload_blob_text(message_item):
    if str(message_item.get("file_content_source") or "").strip().lower() != "blob":
        return ""

    blob_container = str(message_item.get("blob_container") or "").strip()
    blob_path = str(message_item.get("blob_path") or "").strip()
    if not blob_container or not blob_path:
        return ""

    blob_service_client = CLIENTS.get("storage_account_office_docs_client")
    if not blob_service_client:
        return ""

    try:
        blob_client = blob_service_client.get_blob_client(container=blob_container, blob=blob_path)
        blob_data = blob_client.download_blob().readall()
        file_ext = os.path.splitext(str(message_item.get("filename") or ""))[1].lower()

        if file_ext in {".xlsx", ".xlsm", ".xls"}:
            # Import locally because spreadsheet parsing is only needed for blob-backed chat uploads.
            import pandas as pd

            if file_ext == ".xls":
                dataframe = pd.read_excel(io.BytesIO(blob_data), engine="xlrd")
            else:
                dataframe = pd.read_excel(io.BytesIO(blob_data), engine="openpyxl")
            return dataframe.to_csv(index=False)

        return blob_data.decode("utf-8", errors="replace")
    except Exception as exc:
        debug_print(
            "[SEARCH_SERVICE] Failed to load chat upload blob content | "
            f"message_id={message_item.get('id')} | error={exc}"
        )
        return ""


def _coerce_chat_upload_text(message_item):
    for field_name in ("file_content", "extracted_text"):
        field_value = message_item.get(field_name)
        if isinstance(field_value, str) and field_value.strip():
            return field_value.strip()

    blob_text = _load_chat_upload_blob_text(message_item)
    if blob_text:
        return blob_text.strip()

    vision_analysis = message_item.get("vision_analysis")
    if isinstance(vision_analysis, str) and vision_analysis.strip():
        return vision_analysis.strip()
    if vision_analysis not in (None, "", [], {}):
        try:
            return json.dumps(vision_analysis, ensure_ascii=False, indent=2).strip()
        except (TypeError, ValueError):
            return ""

    return ""


def _build_chat_upload_chunks(text_content, max_chunks=None):
    normalized_text = str(text_content or "").strip()
    if not normalized_text:
        return []

    words = normalized_text.split()
    if not words:
        return []

    step_size = max(1, CHAT_UPLOAD_CHUNK_WORD_SIZE - CHAT_UPLOAD_CHUNK_WORD_OVERLAP)
    chunks = []

    for chunk_index, start_offset in enumerate(range(0, len(words), step_size), start=1):
        chunk_text = " ".join(words[start_offset:start_offset + CHAT_UPLOAD_CHUNK_WORD_SIZE]).strip()
        if not chunk_text:
            continue

        chunks.append({
            "chunk_id": str(chunk_index),
            "chunk_text": chunk_text,
            "page_number": chunk_index,
            "chunk_sequence": chunk_index,
        })
        if max_chunks is not None and len(chunks) >= max_chunks:
            break

    return chunks


def _authorize_chat_upload_conversation(user_id, conversation_id):
    normalized_user_id = str(user_id or "").strip()
    normalized_conversation_id = str(conversation_id or "").strip()
    if not normalized_user_id or not normalized_conversation_id:
        return False

    try:
        conversation_item = cosmos_conversations_container.read_item(
            item=normalized_conversation_id,
            partition_key=normalized_conversation_id,
        )
    except CosmosResourceNotFoundError:
        return False
    except Exception as exc:
        log_event(
            "[SEARCH_SERVICE] Failed to authorize chat upload conversation.",
            extra={"exception_type": type(exc).__name__},
            level=logging.WARNING,
            exceptionTraceback=True,
            debug_only=True,
        )
        return False

    return str(conversation_item.get("user_id") or "").strip() == normalized_user_id


def _resolve_chat_upload_context(
    document_id,
    user_id=None,
    conversation_id=None,
    include_content=True,
    authorization_prechecked=False,
):
    normalized_conversation_id = str(conversation_id or "").strip()
    normalized_document_id = str(document_id or "").strip()
    if not normalized_conversation_id or not normalized_document_id:
        return None
    if (
        not authorization_prechecked
        and not _authorize_chat_upload_conversation(user_id, normalized_conversation_id)
    ):
        return None

    try:
        if include_content:
            message_item = cosmos_messages_container.read_item(
                item=normalized_document_id,
                partition_key=normalized_conversation_id,
            )
        else:
            metadata_items = list(cosmos_messages_container.query_items(
                query="""
                    SELECT TOP 1
                        c.id,
                        c.role,
                        c.filename,
                        c.title,
                        c.version,
                        c.metadata.is_user_upload AS is_user_upload,
                        c.metadata.is_generated_chat_artifact AS is_generated_chat_artifact,
                        c.metadata.generated_artifact_capability AS generated_artifact_capability,
                        c.metadata.generated_artifact_output_format AS generated_artifact_output_format
                    FROM c
                    WHERE c.id = @document_id
                """,
                parameters=[
                    {"name": "@document_id", "value": normalized_document_id},
                ],
                partition_key=normalized_conversation_id,
            ))
            if not metadata_items:
                return None
            message_item = metadata_items[0]
    except CosmosResourceNotFoundError:
        return None
    except Exception as exc:
        log_event(
            "[SEARCH_SERVICE] Failed to resolve authorized chat upload context.",
            extra={"exception_type": type(exc).__name__},
            level=logging.WARNING,
            exceptionTraceback=True,
            debug_only=True,
        )
        return None

    role_name = str(message_item.get("role") or "").strip().lower()
    metadata = message_item.get("metadata", {}) or {}
    is_uploaded_image = role_name == "image" and bool(
        metadata.get("is_user_upload") or message_item.get("is_user_upload")
    )
    if role_name not in {"file", "image"} or (role_name == "image" and not is_uploaded_image):
        return None

    comparison_text = _coerce_chat_upload_text(message_item) if include_content else ""
    if include_content and not comparison_text:
        return None

    message_title = str(message_item.get("filename") or message_item.get("title") or normalized_document_id).strip() or normalized_document_id
    resolved_document = {
        "id": normalized_document_id,
        "file_name": message_title,
        "title": message_title,
        "conversation_id": normalized_conversation_id,
        "source_type": "chat_upload",
        "source_subtype": "generated_chat_artifact" if (
            metadata.get("is_generated_chat_artifact")
            or message_item.get("is_generated_chat_artifact")
        ) else "chat_upload",
        "artifact_capability": str(
            metadata.get("generated_artifact_capability")
            or message_item.get("generated_artifact_capability")
            or ""
        ).strip().lower() or None,
        "artifact_output_format": str(
            metadata.get("generated_artifact_output_format")
            or message_item.get("generated_artifact_output_format")
            or ""
        ).strip().lower() or None,
        "version": message_item.get("version"),
    }
    if include_content:
        resolved_document["comparison_text"] = comparison_text
    return {
        "scope": "chat",
        "group_id": None,
        "public_workspace_id": None,
        "conversation_id": normalized_conversation_id,
        "document": resolved_document,
    }


def _resolve_personal_document_context(document_id, user_id):
    personal_document = get_document_record(
        user_id=user_id,
        document_id=document_id,
    )
    if not personal_document:
        return None
    return {
        "scope": "personal",
        "group_id": None,
        "public_workspace_id": None,
        "document": personal_document,
    }


def _resolve_group_document_context(document_id, user_id, authorized_group_ids):
    for group_id in authorized_group_ids or []:
        group_document = get_document_record(
            user_id=user_id,
            document_id=document_id,
            group_id=group_id,
        )
        if group_document:
            return {
                "scope": "group",
                "group_id": group_id,
                "public_workspace_id": None,
                "document": group_document,
            }
    return None


def _resolve_public_document_context(
    document_id,
    user_id,
    authorized_public_workspace_ids,
):
    for public_workspace_id in authorized_public_workspace_ids or []:
        public_document = get_document_record(
            user_id=user_id,
            document_id=document_id,
            public_workspace_id=public_workspace_id,
        )
        if public_document:
            return {
                "scope": "public",
                "group_id": None,
                "public_workspace_id": public_workspace_id,
                "document": public_document,
            }
    return None


def resolve_document_context(
    document_id,
    user_id,
    doc_scope="all",
    active_group_ids=None,
    active_public_workspace_id=None,
    conversation_id=None,
    include_content=True,
):
    normalized_scope = normalize_search_scope(doc_scope)

    if normalized_scope in ("all", "personal"):
        personal_context = _resolve_personal_document_context(document_id, user_id)
        if personal_context:
            return personal_context

    if normalized_scope in ("all", "group"):
        group_context = _resolve_group_document_context(
            document_id,
            user_id,
            _resolve_active_group_ids(
                user_id,
                active_group_ids=active_group_ids,
                fallback_to_memberships=True,
            ),
        )
        if group_context:
            return group_context

    if normalized_scope in ("all", "public"):
        public_context = _resolve_public_document_context(
            document_id,
            user_id,
            _resolve_public_workspace_ids(
                user_id,
                active_public_workspace_id=active_public_workspace_id,
            ),
        )
        if public_context:
            return public_context

    chat_upload_context = _resolve_chat_upload_context(
        document_id=document_id,
        user_id=user_id,
        conversation_id=conversation_id,
        include_content=include_content,
    )
    if chat_upload_context:
        return chat_upload_context

    return None


def resolve_document_contexts(
    document_ids,
    user_id,
    doc_scope="all",
    active_group_ids=None,
    active_public_workspace_id=None,
    conversation_id=None,
    include_content=True,
):
    """Resolve ordered document contexts using one current authorization snapshot."""
    normalized_scope = normalize_search_scope(doc_scope)
    normalized_document_ids = normalize_search_id_list(document_ids)
    authorized_group_ids = []
    if normalized_scope in ("all", "group"):
        authorized_group_ids = _resolve_active_group_ids(
            user_id,
            active_group_ids=active_group_ids,
            fallback_to_memberships=True,
        )
    authorized_public_workspace_ids = []
    if normalized_scope in ("all", "public"):
        authorized_public_workspace_ids = _resolve_public_workspace_ids(
            user_id,
            active_public_workspace_id=active_public_workspace_id,
        )

    normalized_conversation_id = str(conversation_id or "").strip()
    chat_conversation_authorized = bool(
        normalized_conversation_id
        and _authorize_chat_upload_conversation(user_id, normalized_conversation_id)
    )

    resolved_contexts = []
    for document_id in normalized_document_ids:
        document_context = None
        if normalized_scope in ("all", "personal"):
            document_context = _resolve_personal_document_context(document_id, user_id)
        if not document_context and normalized_scope in ("all", "group"):
            document_context = _resolve_group_document_context(
                document_id,
                user_id,
                authorized_group_ids,
            )
        if not document_context and normalized_scope in ("all", "public"):
            document_context = _resolve_public_document_context(
                document_id,
                user_id,
                authorized_public_workspace_ids,
            )
        if not document_context and chat_conversation_authorized:
            document_context = _resolve_chat_upload_context(
                document_id=document_id,
                user_id=user_id,
                conversation_id=normalized_conversation_id,
                include_content=include_content,
                authorization_prechecked=True,
            )
        resolved_contexts.append(document_context)

    return resolved_contexts


def build_search_request(
    query,
    user_id,
    top_n=None,
    doc_scope="all",
    document_id=None,
    document_ids=None,
    tags_filter=None,
    active_group_ids=None,
    active_public_workspace_id=None,
    enable_file_sharing=True,
    include_all_public_workspaces=False,
):
    normalized_query = str(query or "").strip()
    if not normalized_query:
        raise ValueError("Query is required")

    normalized_scope = normalize_search_scope(doc_scope)
    normalized_top_n = normalize_search_top_n(top_n, SEARCH_DEFAULT_TOP_N, SEARCH_MAX_TOP_N)
    normalized_document_ids = normalize_search_id_list(document_ids)
    if document_id and not normalized_document_ids:
        normalized_document_ids = [str(document_id).strip()]

    search_request = {
        "query": normalized_query,
        "user_id": user_id,
        "top_n": normalized_top_n,
        "doc_scope": normalized_scope,
        "enable_file_sharing": bool(enable_file_sharing),
    }

    if normalized_document_ids:
        search_request["document_ids"] = normalized_document_ids

    normalized_tags = normalize_search_id_list(tags_filter)
    if normalized_tags:
        search_request["tags_filter"] = normalized_tags

    resolved_group_ids = _resolve_active_group_ids(
        user_id,
        active_group_ids=active_group_ids,
        fallback_to_memberships=False,
    )
    if resolved_group_ids and normalized_scope in ("all", "group"):
        search_request["active_group_ids"] = resolved_group_ids

    resolved_public_workspace_ids = _resolve_public_workspace_ids(
        user_id,
        active_public_workspace_id=active_public_workspace_id,
    )
    if resolved_public_workspace_ids and normalized_scope in ("all", "public"):
        search_request["active_public_workspace_id"] = (
            resolved_public_workspace_ids
            if include_all_public_workspaces
            else resolved_public_workspace_ids[0]
        )

    return search_request


def search_documents(
    query,
    user_id,
    top_n=None,
    doc_scope="all",
    document_id=None,
    document_ids=None,
    tags_filter=None,
    active_group_ids=None,
    active_public_workspace_id=None,
    enable_file_sharing=True,
    include_all_public_workspaces=False,
):
    search_request = build_search_request(
        query=query,
        user_id=user_id,
        top_n=top_n,
        doc_scope=doc_scope,
        document_id=document_id,
        document_ids=document_ids,
        tags_filter=tags_filter,
        active_group_ids=active_group_ids,
        active_public_workspace_id=active_public_workspace_id,
        enable_file_sharing=enable_file_sharing,
        include_all_public_workspaces=include_all_public_workspaces,
    )
    results = hybrid_search(**search_request) or []
    unique_document_ids = {
        result.get("document_id")
        for result in results
        if result.get("document_id")
    }

    return {
        "query": search_request.get("query"),
        "scope": search_request.get("doc_scope"),
        "top_n": search_request.get("top_n"),
        "document_ids": search_request.get("document_ids", []),
        "tags_filter": search_request.get("tags_filter", []),
        "group_ids": search_request.get("active_group_ids", []),
        "active_public_workspace_id": search_request.get("active_public_workspace_id"),
        "result_count": len(results),
        "document_count": len(unique_document_ids),
        "results": results,
    }


def search_relevant_tabular_candidates(
    query,
    user_id,
    doc_scope="all",
    document_ids=None,
    tags_filter=None,
    active_group_ids=None,
    active_public_workspace_id=None,
    max_candidates=MIXED_SOURCE_TABULAR_CANDIDATE_LIMIT,
):
    """Find a bounded set of authorized table candidates from indexed schema chunks."""
    normalized_limit = _coerce_positive_int(
        max_candidates,
        MIXED_SOURCE_TABULAR_CANDIDATE_LIMIT,
        min_value=1,
        max_value=MIXED_SOURCE_TABULAR_CANDIDATE_LIMIT,
    )
    candidate_query = (
        f"{str(query or '').strip()}\n"
        "Relevant spreadsheet, workbook, worksheet, CSV, table schema, columns, and data fields."
    ).strip()
    search_result = search_documents(
        query=candidate_query,
        user_id=user_id,
        top_n=MIXED_SOURCE_TABULAR_CANDIDATE_TOP_N,
        doc_scope=doc_scope,
        document_ids=document_ids,
        tags_filter=tags_filter,
        active_group_ids=active_group_ids,
        active_public_workspace_id=active_public_workspace_id,
        include_all_public_workspaces=True,
    )

    candidate_document_ids = []
    seen_document_ids = set()
    for result in search_result.get("results") or []:
        file_name = str(result.get("file_name") or "").strip()
        if os.path.splitext(file_name)[1].lower() not in MIXED_SOURCE_TABULAR_EXTENSIONS:
            continue
        document_id = str(result.get("document_id") or "").strip()
        if not document_id or document_id in seen_document_ids:
            continue
        seen_document_ids.add(document_id)
        candidate_document_ids.append(document_id)
        if len(candidate_document_ids) >= normalized_limit:
            break

    log_event(
        "[MIXED_SOURCE_CHAT_SEARCH] Completed bounded authorized tabular candidate search.",
        extra={
            "candidate_search_result_count": search_result.get("result_count", 0),
            "tabular_candidate_count": len(candidate_document_ids),
            "candidate_limit": normalized_limit,
        },
        level=logging.INFO,
    )
    return {
        "document_ids": candidate_document_ids,
        "candidate_count": len(candidate_document_ids),
        "search_result_count": search_result.get("result_count", 0),
        "query": search_result.get("query"),
    }


def _derive_window_size(chunks, window_unit, window_size=None, window_percent=None):
    if not chunks:
        return 0

    if window_unit == "pages":
        total_units = len({chunk.get("page_number") for chunk in chunks if chunk.get("page_number") is not None})
        if total_units <= 0:
            return 0

        if window_size is not None and str(window_size).strip() != "":
            return _coerce_positive_int(
                window_size,
                default_value=min(total_units, SUMMARY_DEFAULT_MAX_PAGE_WINDOW),
                min_value=1,
                max_value=min(total_units, SUMMARY_MAX_WINDOW_SIZE),
            )

        if window_percent:
            computed_size = int(math.ceil(total_units * (float(window_percent) / 100.0)))
        else:
            computed_size = int(math.ceil(total_units / 4.0))

        computed_size = max(SUMMARY_DEFAULT_MIN_PAGE_WINDOW, computed_size)
        computed_size = min(SUMMARY_DEFAULT_MAX_PAGE_WINDOW, computed_size)
        return min(total_units, computed_size)

    total_units = len(chunks)
    if total_units <= 0:
        return 0

    default_chunk_window = min(total_units, SUMMARY_DEFAULT_CHUNK_WINDOW)
    if window_size is not None and str(window_size).strip() != "":
        return _coerce_positive_int(
            window_size,
            default_value=default_chunk_window,
            min_value=1,
            max_value=min(total_units, SUMMARY_MAX_WINDOW_SIZE),
        )

    if window_percent:
        computed_size = int(math.ceil(total_units * (float(window_percent) / 100.0)))
        return min(total_units, max(1, computed_size))

    return default_chunk_window


def build_document_chunk_windows(chunks, window_unit="pages", window_size=None, window_percent=None):
    if not chunks:
        return []

    normalized_window_unit = _normalize_window_unit(window_unit, chunks)
    resolved_window_size = _derive_window_size(
        chunks,
        normalized_window_unit,
        window_size=window_size,
        window_percent=window_percent,
    )
    if resolved_window_size <= 0:
        return []

    windows = []
    if normalized_window_unit == "pages":
        ordered_pages = sorted({chunk.get("page_number") for chunk in chunks if chunk.get("page_number") is not None})
        for window_index, page_offset in enumerate(range(0, len(ordered_pages), resolved_window_size), start=1):
            window_pages = ordered_pages[page_offset:page_offset + resolved_window_size]
            window_chunks = [
                chunk for chunk in chunks
                if chunk.get("page_number") in window_pages
            ]
            windows.append({
                "window_number": window_index,
                "window_unit": normalized_window_unit,
                "window_size": resolved_window_size,
                "chunk_count": len(window_chunks),
                "page_count": len(window_pages),
                "start_page": window_pages[0],
                "end_page": window_pages[-1],
                "start_chunk_sequence": window_chunks[0].get("chunk_sequence") if window_chunks else None,
                "end_chunk_sequence": window_chunks[-1].get("chunk_sequence") if window_chunks else None,
                "chunks": window_chunks,
            })
    else:
        for window_index, chunk_offset in enumerate(range(0, len(chunks), resolved_window_size), start=1):
            window_chunks = chunks[chunk_offset:chunk_offset + resolved_window_size]
            page_numbers = [chunk.get("page_number") for chunk in window_chunks if chunk.get("page_number") is not None]
            windows.append({
                "window_number": window_index,
                "window_unit": normalized_window_unit,
                "window_size": resolved_window_size,
                "chunk_count": len(window_chunks),
                "page_count": len(set(page_numbers)) if page_numbers else 0,
                "start_page": min(page_numbers) if page_numbers else None,
                "end_page": max(page_numbers) if page_numbers else None,
                "start_chunk_sequence": window_chunks[0].get("chunk_sequence") if window_chunks else None,
                "end_chunk_sequence": window_chunks[-1].get("chunk_sequence") if window_chunks else None,
                "chunks": window_chunks,
            })

    return windows


def get_document_chunks_payload(
    document_id,
    user_id,
    doc_scope="all",
    active_group_ids=None,
    active_public_workspace_id=None,
    conversation_id=None,
    window_unit="pages",
    window_size=None,
    window_percent=None,
    window_number=None,
):
    document_context = resolve_document_context(
        document_id=document_id,
        user_id=user_id,
        doc_scope=doc_scope,
        active_group_ids=active_group_ids,
        active_public_workspace_id=active_public_workspace_id,
        conversation_id=conversation_id,
    )
    if not document_context:
        raise LookupError("Document not found or access denied")

    if document_context.get("scope") == "chat":
        chunks = _build_chat_upload_chunks(document_context.get("document", {}).get("comparison_text"))
    else:
        chunks = get_ordered_document_chunks(
            document_id=document_id,
            user_id=user_id,
            group_id=document_context.get("group_id"),
            public_workspace_id=document_context.get("public_workspace_id"),
        )

    if not chunks:
        raise LookupError("Document content is not available for review")

    windows = build_document_chunk_windows(
        chunks,
        window_unit=window_unit,
        window_size=window_size,
        window_percent=window_percent,
    )
    selected_window = None
    selected_chunks = chunks

    if window_number not in (None, ""):
        resolved_window_number = _coerce_positive_int(window_number, default_value=1)
        selected_window = next(
            (window for window in windows if window.get("window_number") == resolved_window_number),
            None,
        )
        if not selected_window:
            raise LookupError(f"Window {resolved_window_number} was not found for this document")
        selected_chunks = selected_window.get("chunks", [])

    return {
        "document": _serialize_document(document_context.get("document"), document_context.get("scope")),
        "scope": document_context.get("scope"),
        "scope_id": (
            document_context.get("conversation_id")
            or document_context.get("document", {}).get("conversation_id")
            or document_context.get("public_workspace_id")
            or document_context.get("group_id")
            or document_context.get("document", {}).get("user_id")
        ),
        "conversation_id": document_context.get("conversation_id") or document_context.get("document", {}).get("conversation_id"),
        "chunk_count": len(chunks),
        "returned_chunk_count": len(selected_chunks),
        "window_count": len(windows),
        "windowing": {
            "window_unit": windows[0].get("window_unit") if windows else _normalize_window_unit(window_unit, chunks),
            "window_size": windows[0].get("window_size") if windows else None,
            "window_percent": window_percent,
            "selected_window_number": selected_window.get("window_number") if selected_window else None,
        },
        "windows": [
            {
                "window_number": window.get("window_number"),
                "window_unit": window.get("window_unit"),
                "window_size": window.get("window_size"),
                "chunk_count": window.get("chunk_count"),
                "page_count": window.get("page_count"),
                "start_page": window.get("start_page"),
                "end_page": window.get("end_page"),
                "start_chunk_sequence": window.get("start_chunk_sequence"),
                "end_chunk_sequence": window.get("end_chunk_sequence"),
            }
            for window in windows
        ],
        "chunks": selected_chunks,
    }


def _render_window_source_text(window_payload):
    source_parts = []
    for chunk in window_payload.get("chunks", []):
        chunk_text = str(chunk.get("chunk_text") or "").strip()
        if not chunk_text:
            continue

        chunk_labels = []
        if chunk.get("page_number") is not None:
            chunk_labels.append(f"Page {chunk.get('page_number')}")
        if chunk.get("chunk_sequence") is not None:
            chunk_labels.append(f"Chunk {chunk.get('chunk_sequence')}")
        prefix = f"[{', '.join(chunk_labels)}] " if chunk_labels else ""
        source_parts.append(f"{prefix}{chunk_text}")

    return "\n\n".join(source_parts)


def _create_summary_client(settings, user_id=None):
    extra_headers = build_model_endpoint_identity_headers(
        settings,
        identity_context={'user_id': user_id},
    )
    if settings.get('enable_gpt_apim', False):
        return AzureOpenAI(
            api_version=settings.get('azure_apim_gpt_api_version'),
            azure_endpoint=settings.get('azure_apim_gpt_endpoint'),
            api_key=settings.get('azure_apim_gpt_subscription_key'),
            default_headers=extra_headers or None,
        )

    auth_type = settings.get('azure_openai_gpt_authentication_type', 'key')
    if auth_type == 'managed_identity':
        token_provider = get_bearer_token_provider(
            DefaultAzureCredential(),
            cognitive_services_scope,
        )
        return AzureOpenAI(
            api_version=settings.get('azure_openai_gpt_api_version'),
            azure_endpoint=settings.get('azure_openai_gpt_endpoint'),
            azure_ad_token_provider=token_provider,
            default_headers=extra_headers or None,
        )

    return AzureOpenAI(
        api_version=settings.get('azure_openai_gpt_api_version'),
        azure_endpoint=settings.get('azure_openai_gpt_endpoint'),
        api_key=settings.get('azure_openai_gpt_key'),
        default_headers=extra_headers or None,
    )


def _resolve_summary_model(settings):
    selected_model = settings.get('gpt_model', {}).get('selected', [{}])
    selected_model = selected_model[0] if selected_model else {}
    model_name = (
        settings.get('metadata_extraction_model')
        or settings.get('azure_openai_gpt_deployment')
        or selected_model.get('deploymentName')
    )
    if not model_name:
        raise RuntimeError('No GPT deployment is configured for document summarization')
    return model_name


def _build_summary_api_params(model_name, messages, max_output_tokens=1600):
    uses_completion_tokens = any(
        marker in model_name.lower()
        for marker in ('o1', 'o3', 'gpt-5')
    )
    api_params = {
        'model': model_name,
        'messages': messages,
    }
    if uses_completion_tokens:
        api_params['max_completion_tokens'] = max_output_tokens
    else:
        api_params['temperature'] = 0.2
        api_params['max_tokens'] = max_output_tokens
    return api_params


def _summarize_text_block(
    gpt_client,
    model_name,
    file_name,
    stage_label,
    target_length,
    focus_instructions,
    coverage_note,
    source_text,
):
    messages = [
        {
            'role': 'system',
            'content': (
                'You summarize document content accurately and conservatively. '
                'Do not invent details. Preserve factual meaning, decisions, risks, dates, and action items when present.'
            ),
        },
        {
            'role': 'user',
            'content': (
                f'Document: {file_name}\n'
                f'Stage: {stage_label}\n'
                f'Coverage: {coverage_note}\n'
                f'Target length: {target_length}\n'
                f'Focus instructions: {focus_instructions or "Summarize the most important facts, decisions, risks, dependencies, and open questions."}\n\n'
                'Write a clear summary with short section headers when useful. '
                'Call out important caveats or ambiguities explicitly.\n\n'
                f'<DocumentContent>\n{source_text}\n</DocumentContent>'
            ),
        },
    ]
    response = gpt_client.chat.completions.create(
        **_build_summary_api_params(model_name, messages)
    )
    return str(response.choices[0].message.content or '').strip()


def _build_reduction_windows(summary_items, batch_size):
    reduction_windows = []
    for window_number, index in enumerate(range(0, len(summary_items), batch_size), start=1):
        batch_items = summary_items[index:index + batch_size]
        source_text = []
        for batch_item in batch_items:
            source_text.append(
                f"[Section {batch_item.get('source_window_numbers')}]\n{batch_item.get('summary', '')}"
            )
        reduction_windows.append({
            'window_number': window_number,
            'window_unit': 'summaries',
            'window_size': batch_size,
            'chunk_count': sum(item.get('chunk_count', 0) for item in batch_items),
            'page_count': sum(item.get('page_count', 0) for item in batch_items),
            'start_page': batch_items[0].get('start_page') if batch_items else None,
            'end_page': batch_items[-1].get('end_page') if batch_items else None,
            'source_text': '\n\n'.join(source_text),
            'source_window_numbers': [item.get('source_window_numbers') for item in batch_items],
        })
    return reduction_windows


def summarize_document_content(
    document_id,
    user_id,
    doc_scope='all',
    active_group_ids=None,
    active_public_workspace_id=None,
    focus_instructions='',
    final_target_length=SUMMARY_DEFAULT_FINAL_TARGET,
    window_target_length=SUMMARY_DEFAULT_WINDOW_SUMMARY_TARGET,
    window_unit=SUMMARY_DEFAULT_WINDOW_UNIT,
    window_size=None,
    window_percent=None,
    reduction_batch_size=SUMMARY_DEFAULT_REDUCTION_BATCH_SIZE,
    max_reduction_rounds=SUMMARY_DEFAULT_MAX_REDUCTION_ROUNDS,
):
    chunk_payload = get_document_chunks_payload(
        document_id=document_id,
        user_id=user_id,
        doc_scope=doc_scope,
        active_group_ids=active_group_ids,
        active_public_workspace_id=active_public_workspace_id,
        window_unit=window_unit,
        window_size=window_size,
        window_percent=window_percent,
    )
    windows = build_document_chunk_windows(
        chunk_payload.get('chunks', []),
        window_unit=window_unit,
        window_size=window_size,
        window_percent=window_percent,
    )
    if not windows:
        raise LookupError('No document chunks were available for summarization')

    settings = get_settings()
    model_name = _resolve_summary_model(settings)
    gpt_client = _create_summary_client(settings, user_id=user_id)
    reduction_batch_size = _coerce_positive_int(
        reduction_batch_size,
        SUMMARY_DEFAULT_REDUCTION_BATCH_SIZE,
        min_value=1,
        max_value=8,
    )
    max_reduction_rounds = _coerce_positive_int(
        max_reduction_rounds,
        SUMMARY_DEFAULT_MAX_REDUCTION_ROUNDS,
        min_value=1,
        max_value=8,
    )
    file_name = chunk_payload.get('document', {}).get('file_name') or document_id

    stage_records = []
    current_stage_inputs = windows
    stage_number = 1
    final_summary = ''

    while current_stage_inputs and stage_number <= max_reduction_rounds:
        debug_print(
            f"[SEARCH_SERVICE] Summarization stage {stage_number} for {file_name} with {len(current_stage_inputs)} input windows"
        )
        output_items = []

        for stage_input in current_stage_inputs:
            if stage_number == 1:
                coverage_note = (
                    f"pages {stage_input.get('start_page')} to {stage_input.get('end_page')}"
                    if stage_input.get('start_page') is not None else
                    f"chunks {stage_input.get('start_chunk_sequence')} to {stage_input.get('end_chunk_sequence')}"
                )
                source_text = _render_window_source_text(stage_input)
                source_window_numbers = [stage_input.get('window_number')]
                target_length = window_target_length
                page_count = stage_input.get('page_count', 0)
                chunk_count = stage_input.get('chunk_count', 0)
                start_page = stage_input.get('start_page')
                end_page = stage_input.get('end_page')
            else:
                coverage_note = f"summary windows {stage_input.get('source_window_numbers')}"
                source_text = stage_input.get('source_text', '')
                source_window_numbers = stage_input.get('source_window_numbers', [])
                target_length = final_target_length
                page_count = stage_input.get('page_count', 0)
                chunk_count = stage_input.get('chunk_count', 0)
                start_page = stage_input.get('start_page')
                end_page = stage_input.get('end_page')

            if not source_text.strip():
                continue

            summary_text = _summarize_text_block(
                gpt_client=gpt_client,
                model_name=model_name,
                file_name=file_name,
                stage_label=f'stage-{stage_number}',
                target_length=target_length,
                focus_instructions=focus_instructions,
                coverage_note=coverage_note,
                source_text=source_text,
            )
            output_items.append({
                'window_number': stage_input.get('window_number'),
                'source_window_numbers': source_window_numbers,
                'chunk_count': chunk_count,
                'page_count': page_count,
                'start_page': start_page,
                'end_page': end_page,
                'summary': summary_text,
            })

        stage_records.append({
            'stage_number': stage_number,
            'input_count': len(current_stage_inputs),
            'output_count': len(output_items),
            'target_length': window_target_length if stage_number == 1 else final_target_length,
            'outputs': output_items,
        })

        if len(output_items) <= 1:
            final_summary = output_items[0].get('summary', '') if output_items else ''
            break

        current_stage_inputs = _build_reduction_windows(output_items, reduction_batch_size)
        stage_number += 1

    log_event(
        '[SEARCH_SERVICE] Document summarization completed',
        extra={
            'document_id': document_id,
            'file_name': file_name,
            'stage_count': len(stage_records),
            'window_count': len(windows),
            'scope': chunk_payload.get('scope'),
        },
        level=logging.INFO,
    )

    return {
        'document': chunk_payload.get('document'),
        'scope': chunk_payload.get('scope'),
        'scope_id': chunk_payload.get('scope_id'),
        'chunk_count': chunk_payload.get('chunk_count'),
        'window_count': len(windows),
        'windowing': chunk_payload.get('windowing'),
        'focus_instructions': focus_instructions,
        'window_target_length': window_target_length,
        'final_target_length': final_target_length,
        'stage_count': len(stage_records),
        'stages': stage_records,
        'summary': final_summary,
    }