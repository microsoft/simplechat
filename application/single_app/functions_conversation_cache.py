# functions_conversation_cache.py
"""Versioned conversation list/search cache helpers."""

import copy
import hashlib
import json
import logging
from typing import Any, Dict, Iterable, Optional

import app_settings_cache
from functions_appinsights import log_event
from functions_group import find_group_by_id
from functions_shared_cache import (
    bump_shared_cache_version,
    get_shared_cache_entry,
    get_shared_cache_version,
    set_shared_cache_entry,
)


CONVERSATION_CACHE_NAMESPACE = "conversation_cache"
CONVERSATION_CACHE_VERSION_DOC_PREFIX = "conversation_cache_version:"
CONVERSATION_CACHE_DEFAULT_TTL_SECONDS = 120


def get_conversation_cache_ttl_seconds(settings: Optional[Dict[str, Any]] = None) -> int:
    """Return a safe positive TTL for conversation cache entries."""
    raw_ttl_seconds = CONVERSATION_CACHE_DEFAULT_TTL_SECONDS
    if isinstance(settings, dict):
        raw_ttl_seconds = settings.get(
            "conversation_cache_ttl_seconds",
            CONVERSATION_CACHE_DEFAULT_TTL_SECONDS,
        )
    try:
        return max(int(raw_ttl_seconds), 0)
    except (TypeError, ValueError):
        log_event(
            "[ConversationCache] Invalid conversation cache TTL; using default.",
            extra={"ttl_seconds": raw_ttl_seconds},
            level=logging.WARNING,
        )
        return CONVERSATION_CACHE_DEFAULT_TTL_SECONDS


def _stable_hash(payload: Any) -> str:
    serialized = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _get_redis_client():
    try:
        return app_settings_cache.get_app_cache_redis_client()
    except Exception as ex:
        log_event(
            "[ConversationCache] Redis client lookup failed; using Cosmos cache fallback.",
            extra={"error": str(ex)},
            level=logging.WARNING,
        )
        return None


def _get_version_doc_id(user_id: str) -> str:
    normalized_user_id = str(user_id or "").strip()
    if not normalized_user_id:
        raise ValueError("user_id is required for conversation cache versioning.")
    return f"{CONVERSATION_CACHE_VERSION_DOC_PREFIX}{normalized_user_id}"


def get_conversation_cache_version(user_id: str) -> int:
    """Return the current user-scoped conversation cache version."""
    return get_shared_cache_version(_get_version_doc_id(user_id), default_version=0, use_local_cache=False)


def bump_conversation_cache_version(user_id: str, reason: str = "conversation_changed") -> Optional[int]:
    """Invalidate a user's conversation list/search cache without failing callers."""
    if not user_id:
        return None
    try:
        version = bump_shared_cache_version(
            _get_version_doc_id(user_id),
            description="User conversation list and search cache version.",
        )
        log_event(
            "[ConversationCache] Conversation cache invalidated.",
            extra={"reason": reason, "user_id": user_id, "version": version},
            level=logging.INFO,
            debug_only=True,
        )
        return version
    except Exception as ex:
        log_event(
            "[ConversationCache] Failed to invalidate conversation cache.",
            extra={"reason": reason, "user_id": user_id, "error": str(ex)},
            level=logging.WARNING,
            exceptionTraceback=True,
        )
        return None


def _participant_user_ids_from_tags(tags: Iterable[Dict[str, Any]]) -> set[str]:
    user_ids = set()
    for tag in tags or []:
        if not isinstance(tag, dict):
            continue
        if tag.get("category") != "participant":
            continue
        user_id = str(tag.get("user_id") or "").strip()
        if user_id:
            user_ids.add(user_id)
    return user_ids


def _add_user_id(user_ids: set[str], user_id: Any) -> None:
    normalized_user_id = str(user_id or "").strip()
    if normalized_user_id:
        user_ids.add(normalized_user_id)


def _add_user_ids(user_ids: set[str], candidate_user_ids: Iterable[Any]) -> None:
    for user_id in candidate_user_ids or []:
        _add_user_id(user_ids, user_id)


def _add_participant_user_ids(user_ids: set[str], participants: Iterable[Dict[str, Any]]) -> None:
    for participant in participants or []:
        if not isinstance(participant, dict):
            continue
        if str(participant.get("status") or "").strip().lower() == "removed":
            continue
        _add_user_id(user_ids, participant.get("user_id"))


def _add_group_member_user_ids(user_ids: set[str], group_id: Any) -> None:
    normalized_group_id = str(group_id or "").strip()
    if not normalized_group_id:
        return
    try:
        group_doc = find_group_by_id(normalized_group_id)
    except Exception as ex:
        log_event(
            "[ConversationCache] Failed to load group members for cache invalidation.",
            extra={"group_id": normalized_group_id, "error": str(ex)},
            level=logging.WARNING,
            exceptionTraceback=True,
            debug_only=True,
        )
        return
    if not isinstance(group_doc, dict):
        return

    owner_doc = group_doc.get("owner") if isinstance(group_doc.get("owner"), dict) else {}
    _add_user_id(user_ids, owner_doc.get("id") or owner_doc.get("userId"))
    for collection_name in ("admins", "documentManagers", "users"):
        for member in group_doc.get(collection_name, []) or []:
            if not isinstance(member, dict):
                continue
            _add_user_id(user_ids, member.get("userId") or member.get("id"))


def get_conversation_cache_user_ids(conversation_item: Dict[str, Any]) -> set[str]:
    """Return users whose conversation list/search cache can include this item."""
    user_ids = set()
    if not isinstance(conversation_item, dict):
        return user_ids

    _add_user_id(user_ids, conversation_item.get("user_id"))
    _add_user_id(user_ids, conversation_item.get("created_by_user_id"))
    user_ids.update(_participant_user_ids_from_tags(conversation_item.get("tags") or []))
    _add_participant_user_ids(user_ids, conversation_item.get("participants") or [])
    for field_name in ("accepted_participant_ids", "pending_participant_ids", "owner_user_ids", "admin_user_ids"):
        _add_user_ids(user_ids, conversation_item.get(field_name) or [])

    scope = conversation_item.get("scope") if isinstance(conversation_item.get("scope"), dict) else {}
    _add_group_member_user_ids(user_ids, scope.get("group_id") or conversation_item.get("group_id"))
    return user_ids


def invalidate_conversation_cache_for_item(conversation_item: Dict[str, Any], reason: str = "conversation_changed") -> None:
    """Invalidate cache versions for the owner and known participants on a conversation item."""
    for user_id in get_conversation_cache_user_ids(conversation_item):
        bump_conversation_cache_version(user_id, reason=reason)


def build_conversation_cache_key(user_id: str, operation: str, parameters: Dict[str, Any] = None) -> str:
    """Build a stable user-scoped cache key for conversation list/search payloads."""
    version = get_conversation_cache_version(user_id)
    fingerprint = _stable_hash({
        "user_id": user_id,
        "operation": operation,
        "version": version,
        "parameters": parameters or {},
    })
    return f"{operation}:{user_id}:{fingerprint}"


def get_cached_conversation_payload(cache_key: str) -> Optional[Dict[str, Any]]:
    """Return a cached conversation payload or None on cache miss/failure."""
    cached = get_shared_cache_entry(
        CONVERSATION_CACHE_NAMESPACE,
        cache_key,
        redis_client=_get_redis_client(),
    )
    if not isinstance(cached, dict):
        log_event(
            "[ConversationCache] Conversation cache miss.",
            extra={"cache_key_hash": _stable_hash(cache_key)[:16]},
            level=logging.INFO,
            debug_only=True,
        )
        return None

    log_event(
        "[ConversationCache] Conversation cache hit.",
        extra={"cache_key_hash": _stable_hash(cache_key)[:16]},
        level=logging.INFO,
        debug_only=True,
    )
    return copy.deepcopy(cached)


def set_cached_conversation_payload(cache_key: str, payload: Dict[str, Any], ttl_seconds: int = None) -> bool:
    """Persist a conversation payload without failing the caller on cache errors."""
    safe_ttl_seconds = get_conversation_cache_ttl_seconds(
        {"conversation_cache_ttl_seconds": ttl_seconds}
        if ttl_seconds is not None
        else None
    )
    try:
        return set_shared_cache_entry(
            CONVERSATION_CACHE_NAMESPACE,
            cache_key,
            copy.deepcopy(payload or {}),
            ttl_seconds=safe_ttl_seconds,
            redis_client=_get_redis_client(),
        )
    except Exception as ex:
        log_event(
            "[ConversationCache] Failed to write conversation cache payload.",
            extra={"cache_key_hash": _stable_hash(cache_key)[:16], "error": str(ex)},
            level=logging.WARNING,
            exceptionTraceback=True,
        )
        return False
