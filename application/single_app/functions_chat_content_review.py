# functions_chat_content_review.py
"""Revision-bound chat check review and authoritative message projections.

Callers must authorize the conversation or the administrator review operation
before passing stored message references here. Infrastructure is resolved at the
operation boundary so ordinary serializers do not introduce bootstrap cycles.
"""

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import wraps

from azure.core import MatchConditions
from azure.cosmos.exceptions import (
    CosmosAccessConditionFailedError, CosmosResourceExistsError, CosmosResourceNotFoundError,
)

from content_screening.contracts import (
    ScreeningError, ScreeningValidationError, hash_payload, normalize_identifier,
    text_fingerprint,
)
from content_screening.repository import _cursor, _encode_cursor, _read_page
from functions_chat_content_checks import (
    CHECK_METADATA, SCANNERS, ChatContentDecision, REMOVED_REPLY_MESSAGE,
    attach_chat_check, check_chat_content, enabled_chat_scanners, orchestration_input_text,
    remember_checked_reply, retract_message_content, strip_private_chat_checks,
)


class ChatContentReviewError(ScreeningError):
    code = "chat_content_check_unavailable"
    public_message = "The chat content check could not be completed. Reload and try again."


class ChatContentReviewConflict(ChatContentReviewError):
    code = "chat_content_check_changed"
    status_code = 409
    public_message = "This message or its check changed. Reload the list before rechecking it."


@dataclass
class ChatReviewStores:
    messages: object
    conversations: object
    shared_messages: object
    shared_conversations: object
    safety: object | None = None
    notifications: object | None = None

    def message_container(self, source):
        if source not in ("chat", "shared"):
            raise ScreeningValidationError("The chat message source is invalid.")
        return self.messages if source == "chat" else self.shared_messages

    def conversation_container(self, source):
        self.message_container(source)
        return self.conversations if source == "chat" else self.shared_conversations


def get_chat_review_stores():
    from config import (
        cosmos_messages_container, cosmos_conversations_container,
        cosmos_collaboration_messages_container, cosmos_collaboration_conversations_container,
        cosmos_safety_container, cosmos_notifications_container,
    )

    return ChatReviewStores(
        cosmos_messages_container, cosmos_conversations_container,
        cosmos_collaboration_messages_container, cosmos_collaboration_conversations_container,
        cosmos_safety_container, cosmos_notifications_container,
    )


def content_checks_report_enabled(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        from flask import abort
        from functions_settings import get_settings

        settings = get_settings()
        if not (settings.get("enable_content_safety") or settings.get("enable_content_screening")):
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def _summary(message):
    return (message.get("metadata") or {}).get(CHECK_METADATA) or {}


def reply_is_retracted(message):
    return bool(((message or {}).get("metadata") or {}).get("content_moderation", {}).get("removed"))


def persist_chat_reply(container, message):
    """A late writer cannot overwrite an administrator's committed retraction."""
    try:
        previous = container.read_item(item=message["id"], partition_key=message["conversation_id"])
    except CosmosResourceNotFoundError:
        previous = None
    if previous is not None and reply_is_retracted(previous):
        return remember_checked_reply(previous)
    if previous is not None and message.get("_etag") not in (None, previous["_etag"]):
        raise ChatContentReviewConflict()
    try:
        if previous is None:
            return container.create_item(body=message)
        return container.replace_item(
            item=message["id"], body=message, etag=previous["_etag"],
            match_condition=MatchConditions.IfNotModified,
        )
    except (CosmosAccessConditionFailedError, CosmosResourceExistsError):
        current = container.read_item(item=message["id"], partition_key=message["conversation_id"])
        if reply_is_retracted(current):
            return remember_checked_reply(current)
        raise ChatContentReviewConflict() from None


def patch_chat_message_metadata(container, message, fields=("thread_info",)):
    """Apply only intended metadata edits to a fresh body, preserving check decisions."""
    incoming = message.get("metadata") or {}
    for _attempt in range(3):
        current = container.read_item(item=message["id"], partition_key=message["conversation_id"])
        updated = deepcopy(current)
        metadata = updated.setdefault("metadata", {})
        for key in fields:
            if key not in incoming:
                continue
            if key == "thread_info":
                metadata.setdefault("thread_info", {}).update(deepcopy(incoming[key]))
            else:
                metadata[key] = deepcopy(incoming[key])
        try:
            return container.replace_item(
                item=current["id"], body=updated, etag=current["_etag"],
                match_condition=MatchConditions.IfNotModified,
            )
        except CosmosAccessConditionFailedError:
            continue
    raise ChatContentReviewConflict()


def refresh_checked_message(message, *, source=None, stores=None):
    """Refresh already-authorized marked messages, including stale shared/cache copies."""
    if not isinstance(message, dict):
        return message
    metadata = message.get("metadata") or {}
    if not metadata.get("content_moderation") and not metadata.get(CHECK_METADATA):
        return message
    stores = stores or get_chat_review_stores()
    source = source or ("shared" if "message_kind" in message and "sender" in metadata else "chat")
    source_conversation = metadata.get("source_conversation_id")
    source_message = metadata.get("source_message_id")
    mirrored = source == "shared" and bool(source_conversation and source_message)
    conversation_id = source_conversation if mirrored else message.get("conversation_id")
    message_id = source_message if mirrored else message.get("id")
    if not conversation_id or not message_id:
        raise ChatContentReviewError()
    try:
        current = stores.message_container("chat" if mirrored else source).read_item(
            item=message_id, partition_key=conversation_id,
        )
    except CosmosResourceNotFoundError:
        raise ChatContentReviewError("This message is no longer available.") from None
    if current.get("conversation_id") != conversation_id:
        raise ChatContentReviewError()
    if mirrored:
        if reply_is_retracted(current):
            summary = _summary(current)
            decision = ChatContentDecision(
                "chat_output", "findings", "block", summary,
                current.get("content") or REMOVED_REPLY_MESSAGE,
            )
            return retract_message_content(message, decision)
        return message
    return current


def checked_history_messages(messages, *, stores=None, for_model=False):
    result = []
    for message in messages or []:
        current = refresh_checked_message(message, stores=stores)
        if for_model and _summary(current).get("decision") == "block":
            continue
        result.append(current)
    return result


def retracted_stream_payload(conversation_id, message_id, *, stores=None):
    if not conversation_id or not message_id:
        return None
    stores = stores or get_chat_review_stores()
    try:
        message = stores.messages.read_item(item=message_id, partition_key=conversation_id)
    except CosmosResourceNotFoundError:
        return None
    if message.get("conversation_id") != conversation_id or not reply_is_retracted(message):
        return None
    return {
        "done": True, "role": "safety", "blocked": True, "replace_content": True,
        "conversation_id": conversation_id, "message_id": message_id,
        "content": message["content"], "full_content": message["content"],
        "metadata": strip_private_chat_checks(message.get("metadata") or {}, metadata=True),
        "hybrid_citations": [], "web_search_citations": [], "agent_citations": [],
    }


def list_unchecked_chat_content(
    *, source="all", checkpoint=None, scanner=None, continuation=None, page_size=25, stores=None,
):
    if type(page_size) is not int or not 1 <= page_size <= 100:
        raise ScreeningValidationError("The chat check page size is invalid.")
    if source not in ("all", "chat", "shared") or checkpoint not in (None, "chat_input", "chat_output"):
        raise ScreeningValidationError("The chat check filters are invalid.")
    if scanner not in (None, *SCANNERS):
        raise ScreeningValidationError("The chat scanner filter is invalid.")
    sources = ["chat", "shared"] if source == "all" else [source]
    signature = hash_payload({"source": source, "checkpoint": checkpoint, "scanner": scanner})
    cursor = _cursor(continuation, signature) or {"source": sources[0], "page": None}
    if not isinstance(cursor, dict) or set(cursor) != {"source", "page"} or cursor["source"] not in sources:
        raise ScreeningValidationError("The chat check continuation is invalid.")
    stores = stores or get_chat_review_stores()
    index = sources.index(cursor["source"])
    items = []
    next_cursor = None
    while index < len(sources) and len(items) < page_size:
        current_source = sources[index]
        query = (
            "SELECT * FROM c WHERE c.metadata.chat_content_checks.status = 'not_checked' "
            "AND c.metadata.chat_content_checks.decision = 'allow_unchecked' "
            "AND c.role IN ('user', 'assistant')"
        )
        parameters = []
        if current_source == "shared":
            query += " AND NOT IS_DEFINED(c.metadata.source_message_id)"
        if checkpoint:
            query += " AND c.metadata.chat_content_checks.checkpoint = @checkpoint"
            parameters.append({"name": "@checkpoint", "value": checkpoint})
        if scanner:
            query += (
                " AND EXISTS(SELECT VALUE s FROM s IN c.metadata.chat_content_checks.scanners "
                "WHERE s.scanner = @scanner AND s.complete = false)"
            )
            parameters.append({"name": "@scanner", "value": scanner})
        page = _read_page(
            stores.message_container(current_source), query + " ORDER BY c.id",
            parameters, cursor["page"], page_size - len(items),
        )
        items.extend({
            "source": current_source, "conversation_id": message["conversation_id"],
            "message_id": message["id"], "role": message.get("role"),
            "timestamp": message.get("timestamp"), "etag": message.get("_etag"),
            "check": deepcopy(_summary(message)),
        } for message in page["items"])
        if page["continuation"]:
            next_cursor = {"source": current_source, "page": page["continuation"]}
            break
        index += 1
        cursor = {"source": sources[index], "page": None} if index < len(sources) else None
        next_cursor = cursor
    return {"items": items, "continuation": _encode_cursor(next_cursor, signature)}


def _recheck_text(message, conversation, summary):
    source = summary.get("source") or {}
    if source.get("kind") == "orchestration_turn":
        from functions_orchestration_runs import get_orchestration_run

        run = get_orchestration_run(source.get("run_id"), conversation.get("user_id"), conversation_id=conversation["id"])
        if not run or run.get("user_message_id") != message["id"]:
            raise ChatContentReviewConflict()
        return orchestration_input_text(run.get("user_message"), run.get("answered_questions"))
    return message.get("content") or ""


def recheck_chat_message(
    *, source, conversation_id, message_id, etag, actor_id, settings,
    stores=None, checker=check_chat_content, on_retracted=None,
):
    """Recheck a queued exact revision; only a finding retracts an old AI reply."""
    stores = stores or get_chat_review_stores()
    container = stores.message_container(source)
    conversation_id = normalize_identifier(conversation_id, "conversation_id")
    message_id = normalize_identifier(message_id, "message_id")
    actor_id = normalize_identifier(actor_id, "actor_id")
    if not isinstance(etag, str) or not etag:
        raise ChatContentReviewConflict()
    message = container.read_item(item=message_id, partition_key=conversation_id)
    conversation = stores.conversation_container(source).read_item(item=conversation_id, partition_key=conversation_id)
    summary = _summary(message)
    if (
        message.get("conversation_id") != conversation_id or message.get("_etag") != etag
        or message.get("role") not in ("user", "assistant")
        or summary.get("status") != "not_checked" or summary.get("decision") != "allow_unchecked"
        or summary.get("checkpoint") not in ("chat_input", "chat_output")
        or conversation.get("orchestration_deleted")
    ):
        raise ChatContentReviewConflict()
    text = _recheck_text(message, conversation, summary)
    if not isinstance(text, str) or text_fingerprint(text) != summary.get("content_fingerprint"):
        raise ChatContentReviewConflict()
    originally_required = {item.get("scanner") for item in summary.get("scanners") or []}
    required = [
        scanner for scanner in SCANNERS
        if scanner in originally_required or scanner in enabled_chat_scanners(settings, summary["checkpoint"])
    ]
    if not required:
        raise ChatContentReviewConflict()
    owner = summary.get("actor_user_id") or conversation.get("user_id") or conversation.get("created_by_user_id")
    if not owner:
        raise ChatContentReviewError()
    result = checker(text, summary["checkpoint"], user_id=owner, settings=settings, required_scanners=required)
    if result.status == "not_required":
        raise ChatContentReviewError()
    metadata = {
        **deepcopy(result.metadata),
        "actor_user_id": owner, "rechecked_by": actor_id,
        "initial_check": deepcopy(summary.get("initial_check") or {
            key: summary.get(key) for key in ("status", "decision", "attempted_at", "scanners")
        }),
    }
    if summary.get("source"):
        metadata["source"] = deepcopy(summary["source"])
    if result.status == "not_checked":
        metadata["decision"] = "allow_unchecked"
    result = ChatContentDecision(
        result.checkpoint, result.status, metadata["decision"], metadata, result.notice,
    )
    retract = result.status == "findings" and message.get("role") == "assistant"
    updated = retract_message_content(message, result) if retract else attach_chat_check(deepcopy(message), result)
    saved = container.replace_item(
        item=message_id, body=updated, etag=etag, match_condition=MatchConditions.IfNotModified,
    )
    if retract:
        (on_retracted or propagate_chat_retraction)(message, saved, source=source, stores=stores)
    if result.status == "findings":
        record_chat_content_incident(saved, owner, stores=stores)
    return {
        "source": source, "conversation_id": conversation_id, "message_id": message_id,
        "etag": saved.get("_etag"), "check": deepcopy(_summary(saved)), "removed": retract,
    }


def record_chat_content_incident(message, user_id, *, stores=None):
    summary = _summary(message)
    if summary.get("status") != "findings":
        return
    stores = stores or get_chat_review_stores()
    if stores.safety is None:
        raise ChatContentReviewError()
    categories = []
    for scanner in summary.get("scanners") or []:
        for category in scanner.get("categories") or []:
            categories.append(deepcopy(category) if isinstance(category, dict) else {"category": category})
    record = {
        "id": f"chat-check-{hash_payload([message['conversation_id'], message.get('id'), summary.get('attempted_at'), summary.get('content_fingerprint')])}",
        "user_id": user_id, "conversation_id": message["conversation_id"],
        "message": (
            "An AI reply was removed because it did not meet the application's content rules."
            if summary.get("origin") == "assistant"
            else "A submitted message did not meet the application's content rules."
        ),
        "content_origin": summary.get("origin"), "record_type": "chat_content_check",
        "status": "New", "action": "None", "triggered_categories": categories,
        "blocklist_matches": [], "reason": "Chat content check findings",
        "timestamp": summary.get("attempted_at"), "created_at": summary.get("attempted_at"),
        "metadata": {
            **({"message_id": message["id"]} if message.get("id") else {"attempt_only": True}),
            CHECK_METADATA: deepcopy(summary),
        },
    }
    try:
        stores.safety.create_item(body=record)
    except CosmosResourceExistsError:
        return


def record_blocked_chat_attempt(result, user_id, conversation_id):
    if result.status == "findings":
        record_chat_content_incident({
            "conversation_id": conversation_id, "metadata": {CHECK_METADATA: result.metadata},
        }, user_id)


def _clear_conversation_projection(container, conversation_id):
    from functions_conversation_cache import invalidate_conversation_cache_for_item

    conversation = container.read_item(item=conversation_id, partition_key=conversation_id)
    conversation["summary"] = None
    if "last_message_preview" in conversation:
        conversation["last_message_preview"] = ""
    saved = container.replace_item(
        item=conversation_id, body=conversation,
        etag=conversation["_etag"], match_condition=MatchConditions.IfNotModified,
    )
    invalidate_conversation_cache_for_item(saved, reason="chat_content_retracted")
    return saved


def propagate_chat_retraction(previous, replacement, *, source="chat", stores=None):
    """Invalidate derived copies after the conditional canonical replacement commits."""
    from functions_collaboration import publish_collaboration_event, serialize_collaboration_message
    from functions_thoughts import delete_scoped_thoughts_for_message

    stores = stores or get_chat_review_stores()
    conversation_id, message_id = replacement["conversation_id"], replacement["id"]
    conversation = _clear_conversation_projection(stores.conversation_container(source), conversation_id)
    summary = _summary(replacement)
    actor_id = summary.get("actor_user_id") or conversation.get("user_id") or conversation.get("created_by_user_id")
    references = [(source, conversation_id, message_id)]
    if source == "chat":
        mirrors = stores.shared_messages.query_items(
            query=(
                "SELECT * FROM c WHERE c.metadata.source_conversation_id = @conversation "
                "AND c.metadata.source_message_id = @message"
            ),
            parameters=[{"name": "@conversation", "value": conversation_id}, {"name": "@message", "value": message_id}],
            enable_cross_partition_query=True,
        )
        decision = ChatContentDecision("chat_output", "findings", "block", summary, replacement["content"])
        for mirror in mirrors:
            updated = retract_message_content(mirror, decision)
            saved = stores.shared_messages.replace_item(
                item=mirror["id"], body=updated, etag=mirror["_etag"],
                match_condition=MatchConditions.IfNotModified,
            )
            _clear_conversation_projection(stores.shared_conversations, mirror["conversation_id"])
            references.append(("shared", mirror["conversation_id"], mirror["id"]))
            publish_collaboration_event(mirror["conversation_id"], {
                "conversation_id": mirror["conversation_id"], "event_type": "collaboration.message.updated",
                "occurred_at": datetime.now(timezone.utc).isoformat(),
                "payload": {"message": serialize_collaboration_message(saved)},
            })
        if actor_id:
            delete_scoped_thoughts_for_message(conversation_id, message_id, actor_id)
        from route_backend_chats import CHAT_STREAM_REGISTRY

        for stream_user_id in {actor_id, conversation.get("user_id")} - {None, ""}:
            stream = CHAT_STREAM_REGISTRY.get_session(stream_user_id, conversation_id, active_only=False)
            if stream:
                stream.retract(retracted_stream_payload(conversation_id, message_id, stores=stores))
    else:
        publish_collaboration_event(conversation_id, {
            "conversation_id": conversation_id, "event_type": "collaboration.message.updated",
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "payload": {"message": serialize_collaboration_message(replacement)},
        })
    if stores.notifications is not None:
        for _kind, ref_conversation, ref_message in references:
            notifications = stores.notifications.query_items(
                query="SELECT * FROM c WHERE c.metadata.conversation_id = @conversation AND c.metadata.message_id = @message",
                parameters=[{"name": "@conversation", "value": ref_conversation}, {"name": "@message", "value": ref_message}],
                enable_cross_partition_query=True,
            )
            for notification in notifications:
                partition = notification.get("user_id") or notification.get("group_id") or notification.get("public_workspace_id")
                if not partition:
                    raise ChatContentReviewError()
                stores.notifications.delete_item(item=notification["id"], partition_key=partition)
