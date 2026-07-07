# functions_conversation_cache.py
"""Versioned conversation list/search cache helpers."""

import copy
import hashlib
import json
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, Optional

import app_settings_cache
from functions_appinsights import log_event
from functions_group import find_group_by_id
from functions_shared_cache import (
    get_shared_cache_entry,
    set_shared_cache_entry,
)


CONVERSATION_CACHE_NAMESPACE = "conversation_cache"
CONVERSATION_CACHE_VERSION_DOC_PREFIX = "conversation_cache_version:"
CONVERSATION_CACHE_ENABLED_SETTING = "enable_conversation_cache"
CONVERSATION_CACHE_TTL_SECONDS_SETTING = "conversation_cache_ttl_seconds"
CONVERSATION_CACHE_DEFAULT_TTL_SECONDS = 120
CONVERSATION_CACHE_METRIC_WINDOWS_MINUTES = (5, 15, 60)
CONVERSATION_CACHE_METRIC_RETENTION_MINUTES = 60
CONVERSATION_CACHE_METRIC_MAX_SAMPLES = 2000

_conversation_cache_metric_samples = []
_conversation_cache_metric_lock = threading.Lock()


def _normalize_bool(value: Any, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return bool(value)


def get_conversation_cache_ttl_seconds(settings: Optional[Dict[str, Any]] = None) -> int:
    """Return a safe positive TTL for conversation cache entries."""
    raw_ttl_seconds = CONVERSATION_CACHE_DEFAULT_TTL_SECONDS
    if isinstance(settings, dict):
        raw_ttl_seconds = settings.get(
            CONVERSATION_CACHE_TTL_SECONDS_SETTING,
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


def get_conversation_cache_settings(settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Return normalized conversation cache settings with Redis remaining optional."""
    settings = settings if isinstance(settings, dict) else {}
    return {
        "enabled": _normalize_bool(settings.get(CONVERSATION_CACHE_ENABLED_SETTING), default=True),
        "ttl_seconds": get_conversation_cache_ttl_seconds(settings),
    }


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_utc_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value or ""))
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _metric_percent(numerator: int, denominator: int) -> Optional[float]:
    if denominator <= 0:
        return None
    return round((float(numerator) / float(denominator)) * 100, 2)


def _safe_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _increment_count(counts: Dict[str, int], key: Any) -> None:
    normalized_key = str(key or "unknown").strip().lower() or "unknown"
    counts[normalized_key] = int(counts.get(normalized_key) or 0) + 1


def _get_cache_operation_from_key(cache_key: Any) -> str:
    normalized_key = str(cache_key or "").strip()
    operation = normalized_key.split(":", 1)[0].strip().lower()
    return operation or "conversation_cache"


def _empty_conversation_cache_metric_window(window_minutes: int) -> Dict[str, Any]:
    return {
        "window_minutes": window_minutes,
        "sample_count": 0,
        "hit_count": 0,
        "miss_count": 0,
        "bypass_count": 0,
        "write_count": 0,
        "invalidation_count": 0,
        "error_count": 0,
        "hit_rate_percent": None,
        "operation_counts": {},
        "event_counts": {},
        "reason_counts": {},
        "first_checked_at": None,
        "last_checked_at": None,
    }


def _prune_conversation_cache_metric_samples(samples: Iterable[Dict[str, Any]], now: datetime) -> list:
    cutoff = now - timedelta(minutes=CONVERSATION_CACHE_METRIC_RETENTION_MINUTES)
    pruned_samples = []
    for sample in samples or []:
        if not isinstance(sample, dict):
            continue
        checked_at = _parse_utc_datetime(sample.get("checked_at"))
        if not checked_at or checked_at < cutoff:
            continue
        pruned_samples.append(copy.deepcopy(sample))

    pruned_samples.sort(key=lambda sample: sample.get("checked_at") or "")
    return pruned_samples[-CONVERSATION_CACHE_METRIC_MAX_SAMPLES:]


def _conversation_cache_metric_matches(sample: Dict[str, Any], event_types: set) -> bool:
    return str(sample.get("event_type") or "").strip().lower() in event_types


def _build_conversation_cache_metric_window(
    samples: Iterable[Dict[str, Any]],
    now: datetime,
    window_minutes: int,
) -> Dict[str, Any]:
    cutoff = now - timedelta(minutes=window_minutes)
    window_samples = [
        sample
        for sample in samples or []
        if (_parse_utc_datetime(sample.get("checked_at")) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff
    ]
    if not window_samples:
        return _empty_conversation_cache_metric_window(window_minutes)

    operation_counts = {}
    event_counts = {}
    reason_counts = {}
    for sample in window_samples:
        _increment_count(operation_counts, sample.get("operation"))
        _increment_count(event_counts, sample.get("event_type"))
        _increment_count(reason_counts, sample.get("reason"))

    hit_count = sum(1 for sample in window_samples if _conversation_cache_metric_matches(sample, {"hit"}))
    miss_count = sum(1 for sample in window_samples if _conversation_cache_metric_matches(sample, {"miss"}))
    bypass_count = sum(1 for sample in window_samples if _conversation_cache_metric_matches(sample, {"bypass"}))
    write_count = sum(1 for sample in window_samples if _conversation_cache_metric_matches(sample, {"write"}))
    invalidation_count = sum(
        1 for sample in window_samples if _conversation_cache_metric_matches(sample, {"invalidate"})
    )
    error_count = sum(
        1
        for sample in window_samples
        if _conversation_cache_metric_matches(sample, {"read_failed", "write_failed", "invalidate_failed"})
    )
    return {
        "window_minutes": window_minutes,
        "sample_count": len(window_samples),
        "hit_count": hit_count,
        "miss_count": miss_count,
        "bypass_count": bypass_count,
        "write_count": write_count,
        "invalidation_count": invalidation_count,
        "error_count": error_count,
        "hit_rate_percent": _metric_percent(hit_count, hit_count + miss_count),
        "operation_counts": operation_counts,
        "event_counts": event_counts,
        "reason_counts": reason_counts,
        "first_checked_at": window_samples[0].get("checked_at"),
        "last_checked_at": window_samples[-1].get("checked_at"),
    }


def _build_conversation_cache_metrics(samples: Iterable[Dict[str, Any]], now: datetime) -> Dict[str, Any]:
    error_samples = [
        sample
        for sample in samples or []
        if str(sample.get("event_type") or "").strip().lower().endswith("_failed")
    ]
    invalidation_samples = [
        sample
        for sample in samples or []
        if str(sample.get("event_type") or "").strip().lower() == "invalidate"
    ]
    return {
        "updated_at": now.isoformat(),
        "retention_minutes": CONVERSATION_CACHE_METRIC_RETENTION_MINUTES,
        "sample_limit": CONVERSATION_CACHE_METRIC_MAX_SAMPLES,
        "sample_count": len(samples or []),
        "last_event": copy.deepcopy(samples[-1]) if samples else None,
        "last_error": copy.deepcopy(error_samples[-1]) if error_samples else None,
        "last_invalidation": copy.deepcopy(invalidation_samples[-1]) if invalidation_samples else None,
        "windows": {
            f"{window_minutes}m": _build_conversation_cache_metric_window(samples, now, window_minutes)
            for window_minutes in CONVERSATION_CACHE_METRIC_WINDOWS_MINUTES
        },
    }


def _record_conversation_cache_metric(
    event_type: str,
    operation: str = None,
    reason: str = None,
    ttl_seconds: int = None,
    error: Exception = None,
) -> Dict[str, Any]:
    sample = {
        "checked_at": _utc_now_iso(),
        "event_type": str(event_type or "unknown").strip().lower() or "unknown",
        "operation": str(operation or "conversation_cache").strip().lower() or "conversation_cache",
        "reason": str(reason or "").strip().lower() or None,
        "ttl_seconds": _safe_int(ttl_seconds),
    }
    if error:
        sample["error_type"] = type(error).__name__

    with _conversation_cache_metric_lock:
        now = datetime.now(timezone.utc)
        samples = _prune_conversation_cache_metric_samples(_conversation_cache_metric_samples, now)
        samples.append(sample)
        del samples[:-CONVERSATION_CACHE_METRIC_MAX_SAMPLES]
        _conversation_cache_metric_samples[:] = samples
    return sample


def get_conversation_cache_metrics() -> Dict[str, Any]:
    """Return lightweight in-process rolling metrics for conversation cache reads/writes."""
    with _conversation_cache_metric_lock:
        samples = copy.deepcopy(_conversation_cache_metric_samples)
    now = datetime.now(timezone.utc)
    samples = _prune_conversation_cache_metric_samples(samples, now)
    return _build_conversation_cache_metrics(samples, now)


def reset_conversation_cache_metrics() -> None:
    """Reset lightweight conversation cache counters for deterministic functional tests."""
    with _conversation_cache_metric_lock:
        _conversation_cache_metric_samples[:] = []


def _stable_hash(payload: Any) -> str:
    serialized = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _get_redis_client():
    try:
        return app_settings_cache.get_app_cache_redis_client()
    except Exception as ex:
        log_event(
            "[ConversationCache] Redis client lookup failed; bypassing conversation cache.",
            extra={"error": str(ex)},
            level=logging.WARNING,
        )
        return None


def _get_version_doc_id(user_id: str) -> str:
    normalized_user_id = str(user_id or "").strip()
    if not normalized_user_id:
        raise ValueError("user_id is required for conversation cache versioning.")
    return f"{CONVERSATION_CACHE_VERSION_DOC_PREFIX}{normalized_user_id}"


def get_conversation_cache_version(user_id: str) -> Optional[int]:
    """Return the current Redis-backed user-scoped conversation cache version."""
    redis_client = _get_redis_client()
    if redis_client is None:
        _record_conversation_cache_metric("bypass", operation="version", reason="redis_unavailable")
        return None
    try:
        version = redis_client.get(_get_version_doc_id(user_id))
        if version is None:
            return 0
        if isinstance(version, bytes):
            version = version.decode("utf-8")
        return int(version)
    except Exception as ex:
        _record_conversation_cache_metric("read_failed", operation="version", reason="version_read_failed", error=ex)
        log_event(
            "[ConversationCache] Failed to read conversation cache version.",
            extra={"user_id": user_id, "error": str(ex)},
            level=logging.WARNING,
            exceptionTraceback=True,
        )
        return None


def bump_conversation_cache_version(user_id: str, reason: str = "conversation_changed") -> Optional[int]:
    """Invalidate a user's conversation list/search cache without failing callers."""
    if not user_id:
        return None
    redis_client = _get_redis_client()
    if redis_client is None:
        _record_conversation_cache_metric("bypass", operation="version", reason="redis_unavailable")
        return None
    try:
        version = int(redis_client.incr(_get_version_doc_id(user_id)) or 0)
        log_event(
            "[ConversationCache] Conversation cache invalidated.",
            extra={"reason": reason, "user_id": user_id, "version": version},
            level=logging.INFO,
            debug_only=True,
        )
        _record_conversation_cache_metric("invalidate", operation="version", reason=reason)
        return version
    except Exception as ex:
        _record_conversation_cache_metric("invalidate_failed", operation="version", reason=reason, error=ex)
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


def build_conversation_cache_key(user_id: str, operation: str, parameters: Dict[str, Any] = None) -> Optional[str]:
    """Build a stable user-scoped cache key for conversation list/search payloads."""
    version = get_conversation_cache_version(user_id)
    if version is None:
        return None
    fingerprint = _stable_hash({
        "user_id": user_id,
        "operation": operation,
        "version": version,
        "parameters": parameters or {},
    })
    return f"{operation}:{user_id}:{fingerprint}"


def get_cached_conversation_payload(cache_key: str, settings: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Return a cached conversation payload or None on cache miss/failure."""
    cache_settings = get_conversation_cache_settings(settings)
    operation = _get_cache_operation_from_key(cache_key)
    if not cache_settings.get("enabled"):
        _record_conversation_cache_metric("bypass", operation=operation, reason="disabled")
        log_event(
            "[ConversationCache] Conversation cache read bypassed because cache is disabled.",
            extra={"cache_key_hash": _stable_hash(cache_key)[:16] if cache_key else ""},
            level=logging.INFO,
            debug_only=True,
        )
        return None

    redis_client = _get_redis_client()
    if redis_client is None:
        _record_conversation_cache_metric("bypass", operation=operation, reason="redis_unavailable")
        return None

    try:
        cached = get_shared_cache_entry(
            CONVERSATION_CACHE_NAMESPACE,
            cache_key,
            redis_client=redis_client,
            allow_cosmos_fallback=False,
        )
    except Exception as ex:
        _record_conversation_cache_metric("read_failed", operation=operation, error=ex)
        log_event(
            "[ConversationCache] Failed to read conversation cache payload.",
            extra={"cache_key_hash": _stable_hash(cache_key)[:16], "error": str(ex)},
            level=logging.WARNING,
            exceptionTraceback=True,
        )
        return None

    if not isinstance(cached, dict):
        _record_conversation_cache_metric("miss", operation=operation)
        log_event(
            "[ConversationCache] Conversation cache miss.",
            extra={"cache_key_hash": _stable_hash(cache_key)[:16]},
            level=logging.INFO,
            debug_only=True,
        )
        return None

    _record_conversation_cache_metric("hit", operation=operation)
    log_event(
        "[ConversationCache] Conversation cache hit.",
        extra={"cache_key_hash": _stable_hash(cache_key)[:16]},
        level=logging.INFO,
        debug_only=True,
    )
    return copy.deepcopy(cached)


def set_cached_conversation_payload(
    cache_key: str,
    payload: Dict[str, Any],
    ttl_seconds: int = None,
    settings: Optional[Dict[str, Any]] = None,
) -> bool:
    """Persist a conversation payload without failing the caller on cache errors."""
    cache_settings = get_conversation_cache_settings(settings)
    operation = _get_cache_operation_from_key(cache_key)
    if not cache_settings.get("enabled"):
        _record_conversation_cache_metric("bypass", operation=operation, reason="disabled")
        log_event(
            "[ConversationCache] Conversation cache write bypassed because cache is disabled.",
            extra={"cache_key_hash": _stable_hash(cache_key)[:16] if cache_key else ""},
            level=logging.INFO,
            debug_only=True,
        )
        return False

    safe_ttl_seconds = (
        get_conversation_cache_ttl_seconds({CONVERSATION_CACHE_TTL_SECONDS_SETTING: ttl_seconds})
        if ttl_seconds is not None
        else cache_settings.get("ttl_seconds", CONVERSATION_CACHE_DEFAULT_TTL_SECONDS)
    )
    if safe_ttl_seconds <= 0:
        _record_conversation_cache_metric(
            "bypass",
            operation=operation,
            reason="ttl_disabled",
            ttl_seconds=safe_ttl_seconds,
        )
        log_event(
            "[ConversationCache] Conversation cache write bypassed because TTL is disabled.",
            extra={"cache_key_hash": _stable_hash(cache_key)[:16] if cache_key else ""},
            level=logging.INFO,
            debug_only=True,
        )
        return False

    redis_client = _get_redis_client()
    if redis_client is None:
        _record_conversation_cache_metric("bypass", operation=operation, reason="redis_unavailable")
        return False

    try:
        cache_written = set_shared_cache_entry(
            CONVERSATION_CACHE_NAMESPACE,
            cache_key,
            copy.deepcopy(payload or {}),
            ttl_seconds=safe_ttl_seconds,
            redis_client=redis_client,
            allow_cosmos_fallback=False,
        )
        _record_conversation_cache_metric(
            "write" if cache_written else "write_failed",
            operation=operation,
            ttl_seconds=safe_ttl_seconds,
        )
        return cache_written
    except Exception as ex:
        _record_conversation_cache_metric(
            "write_failed",
            operation=operation,
            ttl_seconds=safe_ttl_seconds,
            error=ex,
        )
        log_event(
            "[ConversationCache] Failed to write conversation cache payload.",
            extra={"cache_key_hash": _stable_hash(cache_key)[:16], "error": str(ex)},
            level=logging.WARNING,
            exceptionTraceback=True,
        )
        return False
