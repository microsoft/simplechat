# functions_mcp_server_tools.py

import json
import logging
from datetime import datetime, timezone

from azure.cosmos.exceptions import CosmosResourceNotFoundError

from background_tasks import acquire_distributed_task_lock, release_distributed_task_lock
from collaboration_models import MEMBERSHIP_STATUS_ACCEPTED
from config import (
    cosmos_conversations_container,
    cosmos_messages_container,
    cosmos_user_prompts_container,
)
from functions_appinsights import log_event
from functions_collaboration import (
    assert_user_can_view_collaboration_conversation,
    get_collaboration_conversation,
    is_personal_collaboration_conversation,
    list_collaboration_messages,
    list_personal_collaboration_conversations_for_user,
    serialize_collaboration_conversation,
)
from functions_documents import (
    _query_accessible_documents,
    get_workspace_tags,
    normalize_tag,
    sanitize_tags_for_filter,
    select_current_documents,
    sort_documents,
)
from functions_message_artifacts import filter_assistant_artifact_items
from functions_personal_workflows import (
    compute_next_run_at,
    get_personal_workflow,
    get_personal_workflows,
    save_personal_workflow_run,
    update_personal_workflow_runtime_fields,
)
from functions_search_service import search_documents as run_document_search
from functions_settings import get_settings, is_user_workflows_enabled_for_user
from functions_workflow_runner import run_personal_workflow


INBOUND_MCP_TOOL_RESULT_LIMIT_DEFAULT = 100
INBOUND_MCP_TOOL_RESULT_LIMIT_MAX = 100
INBOUND_MCP_CONVERSATION_LIMIT_DEFAULT = 25
INBOUND_MCP_CONVERSATION_LIMIT_MAX = 50
INBOUND_MCP_DOCUMENT_LIMIT_DEFAULT = 50
INBOUND_MCP_DOCUMENT_LIMIT_MAX = 100
INBOUND_MCP_MESSAGE_LIMIT_DEFAULT = 50
INBOUND_MCP_PROMPT_LIMIT_DEFAULT = 50
INBOUND_MCP_PROMPT_LIMIT_MAX = 100
INBOUND_MCP_SEARCH_TOP_N_DEFAULT = 5
INBOUND_MCP_SEARCH_TOP_N_MAX = 20
INBOUND_MCP_SEARCH_SNIPPET_MAX_CHARS = 1000
INBOUND_MCP_SEARCH_SUMMARY_MAX_CHARS = 500
INBOUND_MCP_OFFSET_MAX = 10000
INBOUND_MCP_MESSAGE_CONTENT_MAX_CHARS = 4000
INBOUND_MCP_WORKFLOW_LIMIT_DEFAULT = 50
INBOUND_MCP_WORKFLOW_LIMIT_MAX = 100
INBOUND_MCP_WORKFLOW_DESCRIPTION_MAX_CHARS = 500
INBOUND_MCP_WORKFLOW_RUN_LOCK_SECONDS = 900
INBOUND_MCP_WORKFLOW_ERROR_MAX_CHARS = 500


class InboundMcpToolConflict(Exception):
    """Raised when a governed inbound MCP tool cannot proceed due to state conflict."""


def _coerce_limit(
    value,
    default_value=INBOUND_MCP_TOOL_RESULT_LIMIT_DEFAULT,
    max_value=INBOUND_MCP_TOOL_RESULT_LIMIT_MAX,
):
    try:
        limit = int(value)
    except (TypeError, ValueError):
        limit = default_value
    return min(max(limit, 1), int(max_value or INBOUND_MCP_TOOL_RESULT_LIMIT_MAX))


def _coerce_offset(value):
    try:
        offset = int(value)
    except (TypeError, ValueError):
        offset = 0
    return min(max(offset, 0), INBOUND_MCP_OFFSET_MAX)


def _coerce_bool(value, default_value=False):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized_value = value.strip().lower()
        if normalized_value in {"1", "true", "yes", "on"}:
            return True
        if normalized_value in {"0", "false", "no", "off", ""}:
            return False
    return default_value


def _require_delegated_user_id(auth_context):
    delegated_user_id = str(getattr(auth_context, "delegated_user_id", "") or "").strip()
    if not delegated_user_id:
        raise PermissionError("Inbound MCP tool requires a delegated user identity.")
    return delegated_user_id


def _conversation_timestamp(conversation_item):
    return str(
        (conversation_item or {}).get("last_updated")
        or (conversation_item or {}).get("updated_at")
        or (conversation_item or {}).get("last_message_at")
        or (conversation_item or {}).get("created_at")
        or ""
    )


def _normalize_list(value):
    if isinstance(value, list):
        return value
    if isinstance(value, (tuple, set)):
        return list(value)
    return []


def _coerce_nonnegative_int(value):
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _serialize_conversation(conversation_item, source):
    conversation_item = conversation_item if isinstance(conversation_item, dict) else {}
    return {
        "id": str(conversation_item.get("id") or "").strip(),
        "title": str(conversation_item.get("title") or "Untitled").strip() or "Untitled",
        "scope": "personal",
        "source": source,
        "chat_type": str(conversation_item.get("chat_type") or "personal_single_user").strip(),
        "last_updated": _conversation_timestamp(conversation_item),
        "created_at": str(conversation_item.get("created_at") or "").strip(),
        "is_pinned": bool(conversation_item.get("is_pinned", False)),
        "is_hidden": bool(conversation_item.get("is_hidden", False)),
        "tags": _normalize_list(conversation_item.get("tags")),
        "classification": _normalize_list(conversation_item.get("classification")),
        "message_count": _coerce_nonnegative_int(conversation_item.get("message_count")),
    }


def _load_legacy_personal_conversations(delegated_user_id, include_hidden, fetch_limit):
    query_conditions = ["c.user_id = @user_id"]
    if not include_hidden:
        query_conditions.append("(NOT IS_DEFINED(c.is_hidden) OR c.is_hidden = false)")

    normalized_fetch_limit = max(1, int(fetch_limit or 1))
    query = (
        f"SELECT * FROM c WHERE {' AND '.join(query_conditions)} "
        f"ORDER BY c.last_updated DESC OFFSET 0 LIMIT {normalized_fetch_limit}"
    )
    return list(cosmos_conversations_container.query_items(
        query=query,
        parameters=[{"name": "@user_id", "value": delegated_user_id}],
        enable_cross_partition_query=True,
    ))


def _load_personal_collaboration_conversations(delegated_user_id, include_hidden):
    conversations = []
    for conversation_doc, user_state in list_personal_collaboration_conversations_for_user(delegated_user_id):
        if str(user_state.get("membership_status") or "").strip() != MEMBERSHIP_STATUS_ACCEPTED:
            continue
        serialized = serialize_collaboration_conversation(
            conversation_doc,
            current_user_id=delegated_user_id,
            user_state=user_state,
        )
        if not include_hidden and bool(serialized.get("is_hidden", False)):
            continue
        conversations.append(serialized)
    return conversations


def list_conversations(auth_context, arguments=None):
    """List personal conversations visible to the delegated user."""
    delegated_user_id = _require_delegated_user_id(auth_context)
    arguments = arguments if isinstance(arguments, dict) else {}
    limit = _coerce_limit(
        arguments.get("limit"),
        default_value=INBOUND_MCP_CONVERSATION_LIMIT_DEFAULT,
        max_value=INBOUND_MCP_CONVERSATION_LIMIT_MAX,
    )
    offset = _coerce_offset(arguments.get("offset"))
    include_hidden = _coerce_bool(arguments.get("include_hidden"), default_value=False)

    collaboration_conversations = _load_personal_collaboration_conversations(
        delegated_user_id,
        include_hidden,
    )
    collaboration_source_ids = {
        str(conversation.get("source_conversation_id") or "").strip()
        for conversation in collaboration_conversations
        if str(conversation.get("source_conversation_id") or "").strip()
    }
    legacy_fetch_limit = offset + limit + len(collaboration_source_ids) + 1
    legacy_conversations = _load_legacy_personal_conversations(
        delegated_user_id,
        include_hidden,
        fetch_limit=legacy_fetch_limit,
    )

    candidates = [
        _serialize_conversation(conversation, "legacy")
        for conversation in legacy_conversations
        if str(conversation.get("id") or "").strip() not in collaboration_source_ids
    ]
    candidates.extend(
        _serialize_conversation(conversation, "collaboration")
        for conversation in collaboration_conversations
    )
    candidates.sort(
        key=lambda conversation: (
            str(conversation.get("last_updated") or ""),
            str(conversation.get("id") or ""),
        ),
        reverse=True,
    )

    page = candidates[offset:offset + limit]
    next_offset = offset + len(page)
    has_more = len(candidates) > next_offset
    return {
        "scope": "personal",
        "conversations": page,
        "count": len(page),
        "limit": limit,
        "offset": offset,
        "has_more": has_more,
        "next_offset": next_offset if has_more else None,
    }


def _authorize_personal_conversation_read(delegated_user_id, conversation_id):
    normalized_conversation_id = str(conversation_id or "").strip()
    if not normalized_conversation_id:
        raise ValueError("conversation_id is required.")

    try:
        conversation_item = cosmos_conversations_container.read_item(
            item=normalized_conversation_id,
            partition_key=normalized_conversation_id,
        )
    except CosmosResourceNotFoundError:
        conversation_item = None

    if conversation_item is not None:
        if str(conversation_item.get("user_id") or "").strip() != delegated_user_id:
            raise PermissionError("Inbound MCP conversation access denied.")
        return conversation_item, "legacy"

    try:
        conversation_item = get_collaboration_conversation(normalized_conversation_id)
    except CosmosResourceNotFoundError as exc:
        raise LookupError("Inbound MCP conversation not found.") from exc

    if not is_personal_collaboration_conversation(conversation_item):
        raise PermissionError("Inbound MCP group conversation access is not enabled.")

    assert_user_can_view_collaboration_conversation(delegated_user_id, conversation_item)
    return conversation_item, "collaboration"


def _legacy_message_is_visible(message_item):
    if not isinstance(message_item, dict):
        return False
    if str(message_item.get("role") or "").strip() in {
        "assistant_artifact",
        "assistant_artifact_chunk",
        "image_chunk",
    }:
        return False
    metadata = message_item.get("metadata", {}) if isinstance(message_item.get("metadata"), dict) else {}
    if metadata.get("is_generated_chat_artifact", False):
        return False
    thread_info = metadata.get("thread_info", {}) if isinstance(metadata.get("thread_info"), dict) else {}
    active_thread = thread_info.get("active_thread")
    return active_thread is True or active_thread is None or "active_thread" not in thread_info


def _load_legacy_messages(conversation_id):
    query = """
        SELECT * FROM c
        WHERE c.conversation_id = @conversation_id
        ORDER BY c.timestamp ASC
    """
    all_items = list(cosmos_messages_container.query_items(
        query=query,
        parameters=[{"name": "@conversation_id", "value": conversation_id}],
        partition_key=conversation_id,
    ))
    primary_items = filter_assistant_artifact_items(all_items)
    return [
        message_item
        for message_item in primary_items
        if _legacy_message_is_visible(message_item)
    ]


def _stringify_message_content(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=True, default=str)


def _truncate_text(value, max_chars):
    normalized_value = _stringify_message_content(value).strip()
    truncated_value = normalized_value[:max_chars]
    return truncated_value, len(normalized_value) > len(truncated_value)


def _serialize_message(message_item):
    message_item = message_item if isinstance(message_item, dict) else {}
    raw_content = _stringify_message_content(message_item.get("content"))
    truncated_content = raw_content[:INBOUND_MCP_MESSAGE_CONTENT_MAX_CHARS]
    content_truncated = len(raw_content) > len(truncated_content)
    serialized_message = {
        "id": str(message_item.get("id") or "").strip(),
        "role": str(message_item.get("role") or "").strip(),
        "content": truncated_content,
        "timestamp": str(message_item.get("timestamp") or "").strip(),
        "content_truncated": content_truncated,
    }
    message_kind = str(message_item.get("message_kind") or "").strip()
    if message_kind:
        serialized_message["message_kind"] = message_kind
    reply_to_message_id = str(message_item.get("reply_to_message_id") or "").strip()
    if reply_to_message_id:
        serialized_message["reply_to_message_id"] = reply_to_message_id
    return serialized_message


def get_conversation_messages(auth_context, arguments=None):
    """Retrieve bounded personal conversation messages for the delegated user."""
    delegated_user_id = _require_delegated_user_id(auth_context)
    arguments = arguments if isinstance(arguments, dict) else {}
    conversation_id = str(arguments.get("conversation_id") or "").strip()
    limit = _coerce_limit(
        arguments.get("limit"),
        default_value=INBOUND_MCP_MESSAGE_LIMIT_DEFAULT,
        max_value=INBOUND_MCP_TOOL_RESULT_LIMIT_MAX,
    )
    offset = _coerce_offset(arguments.get("offset"))
    conversation_item, source = _authorize_personal_conversation_read(
        delegated_user_id,
        conversation_id,
    )

    if source == "collaboration":
        raw_messages = list_collaboration_messages(conversation_item.get("id"))
    else:
        raw_messages = _load_legacy_messages(conversation_item.get("id"))

    page = raw_messages[offset:offset + limit]
    next_offset = offset + len(page)
    has_more = len(raw_messages) > next_offset
    return {
        "scope": "personal",
        "conversation_id": str(conversation_item.get("id") or "").strip(),
        "source": source,
        "messages": [_serialize_message(message) for message in page],
        "count": len(page),
        "limit": limit,
        "offset": offset,
        "has_more": has_more,
        "next_offset": next_offset if has_more else None,
    }


def _normalize_document_tags(document_item):
    tags = []
    seen_tags = set()
    for tag in _normalize_list((document_item or {}).get("tags")):
        normalized_tag = normalize_tag(tag)
        if normalized_tag and normalized_tag not in seen_tags:
            seen_tags.add(normalized_tag)
            tags.append(normalized_tag)
    return tags


def _get_shared_approval_status(document_item, delegated_user_id):
    if str((document_item or {}).get("user_id") or "").strip() == delegated_user_id:
        return "owner"

    for shared_entry in _normalize_list((document_item or {}).get("shared_user_ids")):
        normalized_entry = str(shared_entry or "").strip()
        if normalized_entry == delegated_user_id:
            return "none"
        if normalized_entry.startswith(f"{delegated_user_id},"):
            return normalized_entry.split(",", 1)[1].strip() or "none"
    return "none"


def _serialize_personal_document(document_item, delegated_user_id):
    document_item = document_item if isinstance(document_item, dict) else {}
    owner_user_id = str(document_item.get("user_id") or "").strip()
    relationship = "owner" if owner_user_id == delegated_user_id else "shared"
    return {
        "id": str(document_item.get("id") or "").strip(),
        "file_name": str(document_item.get("file_name") or "").strip(),
        "title": str(document_item.get("title") or document_item.get("file_name") or "").strip(),
        "version": _coerce_nonnegative_int(document_item.get("version") or 1),
        "status": str(document_item.get("status") or "").strip(),
        "percentage_complete": _coerce_nonnegative_int(document_item.get("percentage_complete")),
        "upload_date": str(document_item.get("upload_date") or "").strip(),
        "last_updated": str(document_item.get("updated_at") or document_item.get("upload_date") or "").strip(),
        "tags": _normalize_document_tags(document_item),
        "document_classification": str(document_item.get("document_classification") or "").strip(),
        "relationship": relationship,
        "shared_approval_status": _get_shared_approval_status(document_item, delegated_user_id),
    }


def _document_matches_tag(document_item, tag_filter):
    if not tag_filter:
        return True
    return tag_filter in set(_normalize_document_tags(document_item))


def list_personal_documents(auth_context, arguments=None):
    """List personal workspace document metadata visible to the delegated user."""
    delegated_user_id = _require_delegated_user_id(auth_context)
    arguments = arguments if isinstance(arguments, dict) else {}
    limit = _coerce_limit(
        arguments.get("limit"),
        default_value=INBOUND_MCP_DOCUMENT_LIMIT_DEFAULT,
        max_value=INBOUND_MCP_DOCUMENT_LIMIT_MAX,
    )
    offset = _coerce_offset(arguments.get("offset"))
    requested_tag = str(arguments.get("tag") or "").strip()
    tag_filter = None
    if requested_tag:
        sanitized_tags = sanitize_tags_for_filter(requested_tag)
        if len(sanitized_tags) != 1:
            raise ValueError("tag must contain exactly one valid tag.")
        tag_filter = sanitized_tags[0]

    documents = sort_documents(
        select_current_documents(_query_accessible_documents(delegated_user_id)),
        sort_by="_ts",
        sort_order="DESC",
    )
    if tag_filter:
        documents = [
            document_item
            for document_item in documents
            if _document_matches_tag(document_item, tag_filter)
        ]

    page = documents[offset:offset + limit]
    next_offset = offset + len(page)
    has_more = len(documents) > next_offset
    return {
        "scope": "personal",
        "documents": [
            _serialize_personal_document(document_item, delegated_user_id)
            for document_item in page
        ],
        "count": len(page),
        "limit": limit,
        "offset": offset,
        "has_more": has_more,
        "next_offset": next_offset if has_more else None,
    }


def _load_personal_prompt_page(delegated_user_id, offset, limit):
    fetch_limit = limit + 1
    query = f"""
        SELECT c.id, c.name, c.type, c.created_at, c.updated_at
        FROM c
        WHERE c.user_id = @user_id
            AND c.type = @prompt_type
        ORDER BY c.updated_at DESC
        OFFSET {offset} LIMIT {fetch_limit}
    """
    return list(cosmos_user_prompts_container.query_items(
        query=query,
        parameters=[
            {"name": "@user_id", "value": delegated_user_id},
            {"name": "@prompt_type", "value": "user_prompt"},
        ],
        enable_cross_partition_query=True,
    ))


def _serialize_personal_prompt(prompt_item):
    prompt_item = prompt_item if isinstance(prompt_item, dict) else {}
    return {
        "id": str(prompt_item.get("id") or "").strip(),
        "name": str(prompt_item.get("name") or "").strip(),
        "created_at": str(prompt_item.get("created_at") or "").strip(),
        "updated_at": str(prompt_item.get("updated_at") or "").strip(),
    }


def list_personal_prompts(auth_context, arguments=None):
    """List personal prompt metadata visible to the delegated user."""
    delegated_user_id = _require_delegated_user_id(auth_context)
    arguments = arguments if isinstance(arguments, dict) else {}
    limit = _coerce_limit(
        arguments.get("limit"),
        default_value=INBOUND_MCP_PROMPT_LIMIT_DEFAULT,
        max_value=INBOUND_MCP_PROMPT_LIMIT_MAX,
    )
    offset = _coerce_offset(arguments.get("offset"))

    prompt_items = _load_personal_prompt_page(delegated_user_id, offset, limit)
    page = prompt_items[:limit]
    next_offset = offset + len(page)
    has_more = len(prompt_items) > limit
    return {
        "scope": "personal",
        "prompts": [_serialize_personal_prompt(prompt_item) for prompt_item in page],
        "count": len(page),
        "limit": limit,
        "offset": offset,
        "has_more": has_more,
        "next_offset": next_offset if has_more else None,
    }


def _coerce_search_query(arguments):
    query = str((arguments or {}).get("query") or "").strip()
    if not query:
        raise ValueError("query is required.")
    if len(query) > 1000:
        raise ValueError("query must be 1000 characters or fewer.")
    return query


def _serialize_search_result(search_result):
    search_result = search_result if isinstance(search_result, dict) else {}
    snippet, snippet_truncated = _truncate_text(
        search_result.get("chunk_text"),
        INBOUND_MCP_SEARCH_SNIPPET_MAX_CHARS,
    )
    chunk_summary, chunk_summary_truncated = _truncate_text(
        search_result.get("chunk_summary"),
        INBOUND_MCP_SEARCH_SUMMARY_MAX_CHARS,
    )
    return {
        "document_id": str(search_result.get("document_id") or "").strip(),
        "chunk_id": str(search_result.get("chunk_id") or "").strip(),
        "file_name": str(search_result.get("file_name") or "").strip(),
        "title": str(search_result.get("title") or search_result.get("file_name") or "").strip(),
        "score": search_result.get("score"),
        "page_number": search_result.get("page_number"),
        "chunk_sequence": search_result.get("chunk_sequence"),
        "version": search_result.get("version"),
        "upload_date": str(search_result.get("upload_date") or "").strip(),
        "document_classification": str(search_result.get("document_classification") or "").strip(),
        "document_tags": _normalize_list(search_result.get("document_tags")),
        "author": str(search_result.get("author") or "").strip(),
        "chunk_keywords": _normalize_list(search_result.get("chunk_keywords")),
        "snippet": snippet,
        "snippet_truncated": snippet_truncated,
        "chunk_summary": chunk_summary,
        "chunk_summary_truncated": chunk_summary_truncated,
    }


def search_personal_documents(auth_context, arguments=None):
    """Search personal workspace documents visible to the delegated user."""
    delegated_user_id = _require_delegated_user_id(auth_context)
    arguments = arguments if isinstance(arguments, dict) else {}
    query = _coerce_search_query(arguments)
    top_n = _coerce_limit(
        arguments.get("top_n"),
        default_value=INBOUND_MCP_SEARCH_TOP_N_DEFAULT,
        max_value=INBOUND_MCP_SEARCH_TOP_N_MAX,
    )
    search_payload = run_document_search(
        query=query,
        user_id=delegated_user_id,
        top_n=top_n,
        doc_scope="personal",
        enable_file_sharing=True,
    )
    raw_results = _normalize_list((search_payload or {}).get("results"))
    return {
        "scope": "personal",
        "query": query,
        "top_n": top_n,
        "result_count": len(raw_results),
        "document_count": _coerce_nonnegative_int((search_payload or {}).get("document_count")),
        "results": [_serialize_search_result(result) for result in raw_results[:top_n]],
    }


def list_personal_tags(auth_context, arguments=None):
    """List personal workspace tags for the delegated user."""
    delegated_user_id = _require_delegated_user_id(auth_context)
    arguments = arguments if isinstance(arguments, dict) else {}
    limit = _coerce_limit(arguments.get("limit"))
    tags = []
    for tag in (get_workspace_tags(delegated_user_id) or [])[:limit]:
        if not isinstance(tag, dict):
            continue
        tag_name = str(tag.get("name") or "").strip()
        if not tag_name:
            continue
        tags.append({
            "name": tag_name,
            "count": int(tag.get("count") or 0),
            "color": str(tag.get("color") or "").strip(),
        })
    return {
        "scope": "personal",
        "tags": tags,
        "count": len(tags),
        "limit": limit,
    }


def _require_personal_workflow_execution_enabled(auth_context):
    roles = tuple(getattr(auth_context, "roles", ()) or ())
    if is_user_workflows_enabled_for_user(get_settings(), user_roles=roles):
        return

    raise PermissionError("Personal workflow execution is not available to this delegated user.")


def _serialize_personal_workflow_summary(workflow):
    workflow = workflow if isinstance(workflow, dict) else {}
    description, description_truncated = _truncate_text(
        workflow.get("description"),
        INBOUND_MCP_WORKFLOW_DESCRIPTION_MAX_CHARS,
    )
    return {
        "id": str(workflow.get("id") or "").strip(),
        "name": str(workflow.get("name") or "").strip(),
        "description": description,
        "description_truncated": description_truncated,
        "runner_type": str(workflow.get("runner_type") or "").strip(),
        "trigger_type": str(workflow.get("trigger_type") or "").strip(),
        "is_enabled": bool(workflow.get("is_enabled", False)),
        "status": str(workflow.get("status") or "").strip(),
        "created_at": str(workflow.get("created_at") or "").strip(),
        "updated_at": str(workflow.get("updated_at") or "").strip(),
        "modified_at": str(workflow.get("modified_at") or "").strip(),
        "next_run_at": str(workflow.get("next_run_at") or "").strip(),
        "last_run_at": str(workflow.get("last_run_at") or "").strip(),
        "last_run_status": str(workflow.get("last_run_status") or "").strip(),
        "last_run_trigger_source": str(workflow.get("last_run_trigger_source") or "").strip(),
        "run_count": _coerce_nonnegative_int(workflow.get("run_count")),
        "conversation_id": str(workflow.get("conversation_id") or "").strip(),
    }


def list_personal_workflows(auth_context, arguments=None):
    """List personal workflow metadata for the delegated user."""
    delegated_user_id = _require_delegated_user_id(auth_context)
    _require_personal_workflow_execution_enabled(auth_context)
    arguments = arguments if isinstance(arguments, dict) else {}
    limit = _coerce_limit(
        arguments.get("limit"),
        default_value=INBOUND_MCP_WORKFLOW_LIMIT_DEFAULT,
        max_value=INBOUND_MCP_WORKFLOW_LIMIT_MAX,
    )
    offset = _coerce_offset(arguments.get("offset"))
    workflow_items = get_personal_workflows(delegated_user_id)
    page = workflow_items[offset:offset + limit]
    has_more = offset + len(page) < len(workflow_items)
    return {
        "scope": "personal",
        "workflows": [_serialize_personal_workflow_summary(workflow) for workflow in page],
        "count": len(page),
        "total_count": len(workflow_items),
        "limit": limit,
        "offset": offset,
        "has_more": has_more,
        "next_offset": offset + len(page) if has_more else None,
    }


def _coerce_workflow_id(arguments):
    workflow_id = str((arguments or {}).get("workflow_id") or "").strip()
    if not workflow_id:
        raise ValueError("workflow_id is required.")
    if len(workflow_id) > 128:
        raise ValueError("workflow_id must be 128 characters or fewer.")
    return workflow_id


def _build_mcp_workflow_invocation_metadata(auth_context):
    return {
        "source": "inbound_mcp",
        "caller_app_id": str(getattr(auth_context, "caller_app_id", "") or "").strip(),
        "source_id": str(getattr(auth_context, "source_id", "") or "").strip(),
        "source_signal_type": str(getattr(auth_context, "source_signal_type", "") or "").strip(),
        "source_trust_level": str(getattr(auth_context, "source_trust_level", "") or "").strip(),
        "correlation_id": str(getattr(auth_context, "correlation_id", "") or "").strip(),
        "invoked_at": datetime.now(timezone.utc).isoformat(),
    }


def _truncate_workflow_error(error_text):
    error_text = str(error_text or "").strip()
    if len(error_text) <= INBOUND_MCP_WORKFLOW_ERROR_MAX_CHARS:
        return error_text
    return f"{error_text[:INBOUND_MCP_WORKFLOW_ERROR_MAX_CHARS].rstrip()}..."


def _persist_mcp_workflow_run_metadata(delegated_user_id, run_record, auth_context):
    run_record = dict(run_record or {})
    if not run_record.get("id"):
        return run_record

    run_record["mcp_invocation"] = _build_mcp_workflow_invocation_metadata(auth_context)
    save_personal_workflow_run(delegated_user_id, run_record)
    return run_record


def _serialize_workflow_execution_result(workflow, run_record, success):
    workflow = workflow if isinstance(workflow, dict) else {}
    run_record = run_record if isinstance(run_record, dict) else {}
    error_text = _truncate_workflow_error(run_record.get("error"))
    return {
        "scope": "personal",
        "workflow": {
            "id": str(workflow.get("id") or "").strip(),
            "name": str(workflow.get("name") or "").strip(),
            "runner_type": str(workflow.get("runner_type") or "").strip(),
            "trigger_type": str(workflow.get("trigger_type") or "").strip(),
        },
        "run": {
            "id": str(run_record.get("id") or "").strip(),
            "status": str(run_record.get("status") or "").strip(),
            "success": bool(success),
            "trigger_source": str(run_record.get("trigger_source") or "").strip(),
            "started_at": str(run_record.get("started_at") or "").strip(),
            "completed_at": str(run_record.get("completed_at") or "").strip(),
            "conversation_id": str(run_record.get("conversation_id") or "").strip(),
            "user_message_id": str(run_record.get("user_message_id") or "").strip(),
            "assistant_message_id": str(run_record.get("assistant_message_id") or "").strip(),
            "response_preview_available": bool(str(run_record.get("response_preview") or "").strip()),
            "error": error_text,
            "error_truncated": bool(error_text and error_text != str(run_record.get("error") or "").strip()),
        },
    }


def execute_workflow(auth_context, arguments=None):
    """Execute a personal workflow owned by the delegated user."""
    delegated_user_id = _require_delegated_user_id(auth_context)
    _require_personal_workflow_execution_enabled(auth_context)
    arguments = arguments if isinstance(arguments, dict) else {}
    workflow_id = _coerce_workflow_id(arguments)
    workflow = get_personal_workflow(delegated_user_id, workflow_id)
    if not workflow:
        raise LookupError(
            "Workflow not found. Use list_personal_workflows to find the generated workflow id; "
            "workflow display names are not accepted."
        )

    lock_document = acquire_distributed_task_lock(
        f"workflow_run_{workflow_id}",
        lease_seconds=INBOUND_MCP_WORKFLOW_RUN_LOCK_SECONDS,
    )
    if not lock_document:
        raise InboundMcpToolConflict("This workflow is already running.")

    try:
        started_at = datetime.now(timezone.utc).isoformat()
        update_personal_workflow_runtime_fields(
            delegated_user_id,
            workflow_id,
            {
                "status": "running",
                "last_run_started_at": started_at,
                "last_run_trigger_source": "inbound_mcp",
                "last_run_error": "",
            },
        )

        result = run_personal_workflow(
            workflow,
            trigger_source="inbound_mcp",
            user_roles=tuple(getattr(auth_context, "roles", ()) or ()),
            actor_user_id=delegated_user_id,
        )
        run_record = _persist_mcp_workflow_run_metadata(
            delegated_user_id,
            result.get("run"),
            auth_context,
        )
        update_fields = dict(result.get("workflow_updates") or {})
        update_fields["status"] = "idle"
        if (
            workflow.get("trigger_type") in {"interval", "file_sync"}
            and workflow.get("is_enabled", False)
            and not workflow.get("next_run_at")
        ):
            update_fields["next_run_at"] = compute_next_run_at(
                workflow,
                from_time=datetime.now(timezone.utc),
            )
        update_personal_workflow_runtime_fields(delegated_user_id, workflow_id, update_fields)

        log_event(
            "[InboundMCP] Personal workflow executed through inbound MCP.",
            extra={
                "workflow_id": workflow_id,
                "run_id": str(run_record.get("id") or "").strip(),
                "success": bool(result.get("success")),
                "caller_app_id": str(getattr(auth_context, "caller_app_id", "") or "").strip(),
                "source_id": str(getattr(auth_context, "source_id", "") or "").strip(),
                "delegated_user_id": delegated_user_id,
            },
            level=logging.INFO,
            debug_only=True,
            category="InboundMCP",
        )
        return _serialize_workflow_execution_result(workflow, run_record, result.get("success"))
    except Exception as exc:
        failed_at = datetime.now(timezone.utc).isoformat()
        try:
            update_personal_workflow_runtime_fields(
                delegated_user_id,
                workflow_id,
                {
                    "status": "idle",
                    "last_run_status": "failed",
                    "last_run_error": str(exc),
                    "last_run_at": failed_at,
                    "last_run_trigger_source": "inbound_mcp",
                },
            )
        except Exception as update_exc:
            log_event(
                "[InboundMCP] Failed to reset workflow status after inbound MCP execution error.",
                extra={
                    "workflow_id": workflow_id,
                    "delegated_user_id": delegated_user_id,
                    "error": str(update_exc),
                },
                level=logging.ERROR,
                debug_only=True,
                category="InboundMCP",
                exceptionTraceback=True,
            )
        raise
    finally:
        release_distributed_task_lock(lock_document)


def execute_inbound_mcp_tool(tool_id, auth_context, arguments=None):
    """Dispatch an implemented inbound MCP tool."""
    normalized_tool_id = str(tool_id or "").strip()
    if normalized_tool_id == "list_conversations":
        return list_conversations(auth_context, arguments)
    if normalized_tool_id == "get_conversation_messages":
        return get_conversation_messages(auth_context, arguments)
    if normalized_tool_id == "list_personal_documents":
        return list_personal_documents(auth_context, arguments)
    if normalized_tool_id == "list_personal_prompts":
        return list_personal_prompts(auth_context, arguments)
    if normalized_tool_id == "list_personal_tags":
        return list_personal_tags(auth_context, arguments)
    if normalized_tool_id == "search_personal_documents":
        return search_personal_documents(auth_context, arguments)
    if normalized_tool_id == "list_personal_workflows":
        return list_personal_workflows(auth_context, arguments)
    if normalized_tool_id == "execute_workflow":
        return execute_workflow(auth_context, arguments)
    raise LookupError(f"Inbound MCP tool '{normalized_tool_id}' is not implemented.")
