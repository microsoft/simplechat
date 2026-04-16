# functions_search_service.py
"""Shared search, retrieval, and summarization services for documents."""

import logging
import math
from typing import Any, Dict, List, Optional

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import AzureOpenAI

from config import cognitive_services_scope
from functions_appinsights import log_event
from functions_debug import debug_print
from functions_documents import get_document_record, get_ordered_document_chunks
from functions_group import get_user_groups
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


def _resolve_active_group_ids(user_id, active_group_ids=None, fallback_to_memberships=False):
    normalized_group_ids = normalize_search_id_list(active_group_ids)
    if normalized_group_ids:
        return normalized_group_ids

    user_settings = get_user_settings(user_id)
    active_group_id = str(user_settings.get("settings", {}).get("activeGroupOid") or "").strip()
    if active_group_id:
        return [active_group_id]

    if not fallback_to_memberships:
        return []

    try:
        user_groups = get_user_groups(user_id)
    except Exception:
        return []

    return normalize_search_id_list([group.get("id") for group in user_groups if group.get("id")])


def _resolve_public_workspace_ids(user_id, active_public_workspace_id=None):
    normalized_workspace_ids = normalize_search_id_list(active_public_workspace_id)
    if normalized_workspace_ids:
        return normalized_workspace_ids

    try:
        return normalize_search_id_list(get_user_visible_public_workspace_ids_from_settings(user_id))
    except Exception:
        return []


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
    }


def resolve_document_context(
    document_id,
    user_id,
    doc_scope="all",
    active_group_ids=None,
    active_public_workspace_id=None,
):
    normalized_scope = normalize_search_scope(doc_scope)

    if normalized_scope in ("all", "personal"):
        personal_document = get_document_record(user_id=user_id, document_id=document_id)
        if personal_document:
            return {
                "scope": "personal",
                "group_id": None,
                "public_workspace_id": None,
                "document": personal_document,
            }

    if normalized_scope in ("all", "group"):
        for group_id in _resolve_active_group_ids(
            user_id,
            active_group_ids=active_group_ids,
            fallback_to_memberships=True,
        ):
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

    if normalized_scope in ("all", "public"):
        for public_workspace_id in _resolve_public_workspace_ids(
            user_id,
            active_public_workspace_id=active_public_workspace_id,
        ):
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
        search_request["active_public_workspace_id"] = resolved_public_workspace_ids[0]

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
    )
    if not document_context:
        raise LookupError("Document not found or access denied")

    chunks = get_ordered_document_chunks(
        document_id=document_id,
        user_id=user_id,
        group_id=document_context.get("group_id"),
        public_workspace_id=document_context.get("public_workspace_id"),
    )
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
            document_context.get("public_workspace_id")
            or document_context.get("group_id")
            or document_context.get("document", {}).get("user_id")
        ),
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


def _create_summary_client(settings):
    if settings.get('enable_gpt_apim', False):
        return AzureOpenAI(
            api_version=settings.get('azure_apim_gpt_api_version'),
            azure_endpoint=settings.get('azure_apim_gpt_endpoint'),
            api_key=settings.get('azure_apim_gpt_subscription_key'),
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
        )

    return AzureOpenAI(
        api_version=settings.get('azure_openai_gpt_api_version'),
        azure_endpoint=settings.get('azure_openai_gpt_endpoint'),
        api_key=settings.get('azure_openai_gpt_key'),
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
    gpt_client = _create_summary_client(settings)
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
            f"[SearchService] Summarization stage {stage_number} for {file_name} with {len(current_stage_inputs)} input windows"
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
        '[SearchService] Document summarization completed',
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