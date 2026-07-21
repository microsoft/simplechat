# functions_mcp_server_tools.py

import json

from azure.cosmos.exceptions import CosmosResourceNotFoundError

from collaboration_models import MEMBERSHIP_STATUS_ACCEPTED
from config import (
    cosmos_conversations_container,
    cosmos_messages_container,
    cosmos_user_prompts_container,
)
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


INBOUND_MCP_TOOL_RESULT_LIMIT_DEFAULT = 100
INBOUND_MCP_TOOL_RESULT_LIMIT_MAX = 100
INBOUND_MCP_CONVERSATION_LIMIT_DEFAULT = 25
INBOUND_MCP_CONVERSATION_LIMIT_MAX = 50
INBOUND_MCP_DOCUMENT_LIMIT_DEFAULT = 50
INBOUND_MCP_DOCUMENT_LIMIT_MAX = 100
INBOUND_MCP_MESSAGE_LIMIT_DEFAULT = 50
INBOUND_MCP_PROMPT_LIMIT_DEFAULT = 50
INBOUND_MCP_PROMPT_LIMIT_MAX = 100
INBOUND_MCP_OFFSET_MAX = 10000
INBOUND_MCP_MESSAGE_CONTENT_MAX_CHARS = 4000


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
    raise LookupError(f"Inbound MCP tool '{normalized_tool_id}' is not implemented.")
