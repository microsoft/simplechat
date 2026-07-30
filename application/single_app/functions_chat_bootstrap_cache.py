# functions_chat_bootstrap_cache.py
"""Versioned chat bootstrap cache helpers for low-churn catalog payloads."""

import copy
import hashlib
import json
import logging
from typing import Any, Dict, Iterable, Optional

import app_settings_cache
from functions_appinsights import log_event
from functions_shared_cache import (
    bump_shared_cache_version,
    get_shared_cache_entry,
    get_shared_cache_version,
    set_shared_cache_entry,
)


CHAT_BOOTSTRAP_CACHE_NAMESPACE = "chat_bootstrap"
CHAT_BOOTSTRAP_GLOBAL_VERSION_DOC_ID = "chat_bootstrap_global_cache_version"
CHAT_BOOTSTRAP_USER_VERSION_DOC_PREFIX = "chat_bootstrap_user_cache_version:"
CHAT_BOOTSTRAP_DEFAULT_TTL_SECONDS = 300


def _stable_hash(payload: Any) -> str:
    serialized = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _normalize_id_list(items: Iterable[Dict[str, Any]]) -> list[str]:
    normalized = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or "").strip()
        if item_id:
            normalized.append(item_id)
    return sorted(set(normalized))


def _get_redis_client():
    try:
        return app_settings_cache.get_app_cache_redis_client()
    except Exception as ex:
        log_event(
            "[ChatBootstrapCache] Redis client lookup failed; using Cosmos cache fallback.",
            extra={"error": str(ex)},
            level=logging.WARNING,
        )
        return None


def _get_app_settings_version() -> int:
    getter = getattr(app_settings_cache, "get_app_settings_cache_version", None)
    if not callable(getter):
        return 0
    try:
        return int(getter() or 0)
    except Exception as ex:
        log_event(
            "[ChatBootstrapCache] App settings version lookup failed.",
            extra={"error": str(ex)},
            level=logging.WARNING,
        )
        return 0


def _get_governance_version() -> int:
    getter = getattr(app_settings_cache, "get_governance_cache_version", None)
    if not callable(getter):
        return 0
    try:
        return int(getter() or 0)
    except Exception as ex:
        log_event(
            "[ChatBootstrapCache] Governance cache version lookup failed.",
            extra={"error": str(ex)},
            level=logging.WARNING,
        )
        return 0


def _get_user_version_doc_id(user_id: str) -> str:
    normalized_user_id = str(user_id or "").strip()
    if not normalized_user_id:
        raise ValueError("user_id is required for chat bootstrap user cache versioning.")
    return f"{CHAT_BOOTSTRAP_USER_VERSION_DOC_PREFIX}{normalized_user_id}"


def get_chat_bootstrap_versions(user_id: str) -> Dict[str, int]:
    """Return shared versions that make chat bootstrap cache keys cross-worker safe."""
    return {
        "global": get_shared_cache_version(CHAT_BOOTSTRAP_GLOBAL_VERSION_DOC_ID, default_version=0),
        "user": get_shared_cache_version(_get_user_version_doc_id(user_id), default_version=0),
        "settings": _get_app_settings_version(),
        "governance": _get_governance_version(),
    }


def build_chat_bootstrap_cache_key(
    user_id: str,
    *,
    settings: Dict[str, Any],
    user_settings_dict: Dict[str, Any],
    user_groups_raw: Iterable[Dict[str, Any]],
    user_visible_public_workspaces: Iterable[Dict[str, Any]],
) -> str:
    """Build a stable user-scoped cache key for chat bootstrap catalog fragments."""
    versions = get_chat_bootstrap_versions(user_id)
    relevant_settings = {
        key: settings.get(key)
        for key in (
            "allow_user_agents",
            "enable_semantic_kernel",
            "enable_group_workspaces",
            "allow_group_agents",
            "enable_multi_model_endpoints",
            "allow_user_custom_endpoints",
            "allow_group_custom_endpoints",
            "enable_public_workspaces",
            "enable_user_workspace",
            "allow_user_plugins",
            "allow_group_plugins",
        )
    }
    fingerprint = _stable_hash({
        "user_id": user_id,
        "versions": versions,
        "settings": relevant_settings,
        "personal_model_endpoints": user_settings_dict.get("personal_model_endpoints", []),
        "group_ids": _normalize_id_list(user_groups_raw),
        "public_workspace_ids": _normalize_id_list(user_visible_public_workspaces),
    })
    return f"user:{user_id}:{fingerprint}"


def get_cached_chat_bootstrap_payload(cache_key: str) -> Optional[Dict[str, Any]]:
    """Return a cached chat bootstrap payload or None on miss/failure."""
    cached = get_shared_cache_entry(
        CHAT_BOOTSTRAP_CACHE_NAMESPACE,
        cache_key,
        redis_client=_get_redis_client(),
        allow_cosmos_fallback=False,
    )
    if not isinstance(cached, dict):
        log_event(
            "[ChatBootstrapCache] Chat bootstrap cache miss.",
            extra={"cache_key_hash": _stable_hash(cache_key)[:16]},
            level=logging.INFO,
            debug_only=True,
        )
        return None

    log_event(
        "[ChatBootstrapCache] Chat bootstrap cache hit.",
        extra={"cache_key_hash": _stable_hash(cache_key)[:16]},
        level=logging.INFO,
        debug_only=True,
    )
    return copy.deepcopy(cached)


def set_cached_chat_bootstrap_payload(cache_key: str, payload: Dict[str, Any], ttl_seconds: int = None) -> bool:
    """Persist a chat bootstrap payload without failing the caller on cache errors."""
    return set_shared_cache_entry(
        CHAT_BOOTSTRAP_CACHE_NAMESPACE,
        cache_key,
        copy.deepcopy(payload or {}),
        ttl_seconds=ttl_seconds or CHAT_BOOTSTRAP_DEFAULT_TTL_SECONDS,
        redis_client=_get_redis_client(),
        allow_cosmos_fallback=False,
    )


def bump_chat_bootstrap_global_cache_version(reason: str = "global_bootstrap_change") -> Optional[int]:
    """Invalidate all chat bootstrap payloads by bumping the global version."""
    try:
        version = bump_shared_cache_version(
            CHAT_BOOTSTRAP_GLOBAL_VERSION_DOC_ID,
            description="Global chat bootstrap catalog cache version.",
        )
        log_event(
            "[ChatBootstrapCache] Global chat bootstrap cache invalidated.",
            extra={"reason": reason, "version": version},
            level=logging.INFO,
            debug_only=True,
        )
        return version
    except Exception as ex:
        log_event(
            "[ChatBootstrapCache] Failed to invalidate global chat bootstrap cache.",
            extra={"reason": reason, "error": str(ex)},
            level=logging.WARNING,
            exceptionTraceback=True,
        )
        return None


def bump_chat_bootstrap_user_cache_version(user_id: str, reason: str = "user_bootstrap_change") -> Optional[int]:
    """Invalidate one user's chat bootstrap payloads by bumping the user version."""
    try:
        version = bump_shared_cache_version(
            _get_user_version_doc_id(user_id),
            description="User chat bootstrap catalog cache version.",
        )
        log_event(
            "[ChatBootstrapCache] User chat bootstrap cache invalidated.",
            extra={"reason": reason, "user_id": user_id, "version": version},
            level=logging.INFO,
            debug_only=True,
        )
        return version
    except Exception as ex:
        log_event(
            "[ChatBootstrapCache] Failed to invalidate user chat bootstrap cache.",
            extra={"reason": reason, "user_id": user_id, "error": str(ex)},
            level=logging.WARNING,
            exceptionTraceback=True,
        )
        return None
