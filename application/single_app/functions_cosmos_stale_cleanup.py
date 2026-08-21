# functions_cosmos_stale_cleanup.py
"""Allowlisted Cosmos settings-container cleanup helpers for stale cache artifacts."""

import copy
import hashlib
import logging
from datetime import datetime, timezone

from config import cosmos_settings_container
from functions_appinsights import log_event


COSMOS_STALE_CACHE_CLEANUP_DEFINITION_VERSION = 1
COSMOS_STALE_CACHE_CLEANUP_RUN_SETTING = "app_maintenance_run_stale_cache_cleanup"
COSMOS_STALE_CACHE_CLEANUP_APPLY_SETTING = "app_maintenance_apply_stale_cache_cleanup"
COSMOS_STALE_CACHE_CLEANUP_BATCH_SIZE_SETTING = "app_maintenance_stale_cache_cleanup_batch_size"
COSMOS_STALE_CACHE_CLEANUP_DEFAULT_BATCH_SIZE = 100
COSMOS_STALE_CACHE_CLEANUP_MAX_BATCH_SIZE = 500

SHARED_CACHE_ENTRY_DOC_TYPE = "shared_cache_entry"
SHARED_CACHE_ENTRY_PREFIX = "shared_cache_entry:"
SHARED_CACHE_VERSION_DOC_TYPE = "cache_version"
CONVERSATION_CACHE_NAMESPACE = "conversation_cache"
CHAT_BOOTSTRAP_NAMESPACE = "chat_bootstrap"
CONVERSATION_CACHE_VERSION_DOC_PREFIX = "conversation_cache_version:"
CONVERSATION_CACHE_ENTRY_PREFIX = f"{SHARED_CACHE_ENTRY_PREFIX}{CONVERSATION_CACHE_NAMESPACE}:"
CHAT_BOOTSTRAP_ENTRY_PREFIX = f"{SHARED_CACHE_ENTRY_PREFIX}{CHAT_BOOTSTRAP_NAMESPACE}:"

CLEANUP_CATEGORIES = {
    "legacy_conversation_cache_versions": {
        "description": "Redis-only conversation cache version documents from the retired Cosmos fallback path.",
    },
    "redis_only_shared_cache_entries": {
        "description": "Volatile conversation/chat bootstrap cache payloads that no longer use Cosmos fallback.",
    },
    "expired_shared_cache_entries": {
        "description": "Expired Cosmos fallback cache payloads that can be recomputed on demand.",
    },
}


def _utc_now():
    return datetime.now(timezone.utc)


def _utc_now_iso():
    return _utc_now().isoformat()


def _is_not_found_error(exc):
    return getattr(exc, "status_code", None) == 404


def _hash_document_id(document_id):
    normalized_id = str(document_id or "").strip()
    if not normalized_id:
        return ""
    return hashlib.sha256(normalized_id.encode("utf-8")).hexdigest()[:16]


def _normalize_batch_size(batch_size):
    try:
        normalized_batch_size = int(batch_size or COSMOS_STALE_CACHE_CLEANUP_DEFAULT_BATCH_SIZE)
    except (TypeError, ValueError):
        normalized_batch_size = COSMOS_STALE_CACHE_CLEANUP_DEFAULT_BATCH_SIZE
    return min(max(normalized_batch_size, 1), COSMOS_STALE_CACHE_CLEANUP_MAX_BATCH_SIZE)


def _parse_utc_datetime(value):
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


def _is_expired_shared_cache_entry(document, now):
    if not isinstance(document, dict) or document.get("type") != SHARED_CACHE_ENTRY_DOC_TYPE:
        return False
    expires_at = document.get("expires_at")
    if not expires_at:
        return False
    parsed_expires_at = _parse_utc_datetime(expires_at)
    if parsed_expires_at is None:
        return True
    return parsed_expires_at <= now


def _classify_cleanup_candidate(document, now):
    if not isinstance(document, dict):
        return None

    document_id = str(document.get("id") or "")
    document_type = str(document.get("type") or "")
    namespace = str(document.get("namespace") or "")
    if (
        document_type == SHARED_CACHE_VERSION_DOC_TYPE
        and document_id.startswith(CONVERSATION_CACHE_VERSION_DOC_PREFIX)
    ):
        return "legacy_conversation_cache_versions"

    if document_type == SHARED_CACHE_ENTRY_DOC_TYPE and (
        namespace in {CONVERSATION_CACHE_NAMESPACE, CHAT_BOOTSTRAP_NAMESPACE}
        or document_id.startswith(CONVERSATION_CACHE_ENTRY_PREFIX)
        or document_id.startswith(CHAT_BOOTSTRAP_ENTRY_PREFIX)
    ):
        return "redis_only_shared_cache_entries"

    if _is_expired_shared_cache_entry(document, now):
        return "expired_shared_cache_entries"

    return None


def _empty_category_counts():
    return {
        category_id: {
            "candidate_count": 0,
            "deleted_count": 0,
            "skipped_count": 0,
            "failed_count": 0,
        }
        for category_id in CLEANUP_CATEGORIES
    }


def _increment_category_count(category_counts, category_id, count_name):
    if category_id not in category_counts:
        return
    category_counts[category_id][count_name] = int(category_counts[category_id].get(count_name) or 0) + 1


def _build_category_summary(category_counts):
    return [
        {
            "category": category_id,
            "description": CLEANUP_CATEGORIES[category_id]["description"],
            **counts,
        }
        for category_id, counts in category_counts.items()
    ]


def _query_stale_cache_cleanup_candidates(container, batch_size, now_iso):
    query_limit = _normalize_batch_size(batch_size)
    query = f"""
        SELECT TOP {query_limit}
            c.id,
            c.type,
            c.namespace,
            c.key,
            c.expires_at,
            c.updated_at
        FROM c
        WHERE
            (
                c.type = @cacheVersionType
                AND STARTSWITH(c.id, @conversationVersionPrefix)
            )
            OR
            (
                c.type = @entryType
                AND (
                    c.namespace = @conversationNamespace
                    OR c.namespace = @chatBootstrapNamespace
                    OR STARTSWITH(c.id, @conversationEntryPrefix)
                    OR STARTSWITH(c.id, @chatBootstrapEntryPrefix)
                    OR (
                        IS_DEFINED(c.expires_at)
                        AND c.expires_at != null
                        AND c.expires_at <= @nowIso
                    )
                )
            )
    """
    parameters = [
        {"name": "@cacheVersionType", "value": SHARED_CACHE_VERSION_DOC_TYPE},
        {"name": "@entryType", "value": SHARED_CACHE_ENTRY_DOC_TYPE},
        {"name": "@conversationVersionPrefix", "value": CONVERSATION_CACHE_VERSION_DOC_PREFIX},
        {"name": "@conversationNamespace", "value": CONVERSATION_CACHE_NAMESPACE},
        {"name": "@chatBootstrapNamespace", "value": CHAT_BOOTSTRAP_NAMESPACE},
        {"name": "@conversationEntryPrefix", "value": CONVERSATION_CACHE_ENTRY_PREFIX},
        {"name": "@chatBootstrapEntryPrefix", "value": CHAT_BOOTSTRAP_ENTRY_PREFIX},
        {"name": "@nowIso", "value": now_iso},
    ]
    return list(container.query_items(
        query=query,
        parameters=parameters,
        enable_cross_partition_query=True,
    ))


def build_stale_cache_cleanup_status(last_result=None):
    """Return a JSON-safe stale cleanup status without querying Cosmos."""
    if isinstance(last_result, dict):
        result = copy.deepcopy(last_result)
        result.setdefault("success", result.get("failed_count", 0) == 0)
        result.setdefault("status", "completed" if result.get("success") else "completed_with_errors")
        result.setdefault("mode", "apply" if result.get("apply_requested") else "dry_run")
        result.setdefault("categories", _build_category_summary(_empty_category_counts()))
        return result

    return {
        "success": True,
        "status": "not_run",
        "mode": "not_run",
        "apply_requested": False,
        "definition_version": COSMOS_STALE_CACHE_CLEANUP_DEFINITION_VERSION,
        "candidate_count": 0,
        "deleted_count": 0,
        "skipped_count": 0,
        "failed_count": 0,
        "has_more_candidates": False,
        "categories": _build_category_summary(_empty_category_counts()),
        "evaluated_at": None,
    }


def build_skipped_stale_cache_cleanup_result(reason="not_requested"):
    """Return a skipped cleanup step result for maintenance runs that should not scan Cosmos."""
    result = build_stale_cache_cleanup_status()
    result.update({
        "status": "skipped_disabled",
        "mode": "skipped",
        "skip_reason": reason,
        "evaluated_at": _utc_now_iso(),
    })
    return result


def run_stale_cache_document_cleanup(apply_changes=False, batch_size=None, container=None):
    """Report or delete allowlisted stale operational cache artifacts from settings."""
    cleanup_container = container or cosmos_settings_container
    now = _utc_now()
    now_iso = now.isoformat()
    safe_batch_size = _normalize_batch_size(batch_size)
    category_counts = _empty_category_counts()
    candidate_count = 0
    deleted_count = 0
    skipped_count = 0
    failed_count = 0

    try:
        candidate_documents = _query_stale_cache_cleanup_candidates(
            cleanup_container,
            safe_batch_size,
            now_iso,
        )
    except Exception as exc:
        log_event(
            "[COSMOS_STALE_CLEANUP] Failed to query stale cache cleanup candidates.",
            extra={"error": str(exc), "batch_size": safe_batch_size},
            level=logging.ERROR,
            exceptionTraceback=True,
        )
        return {
            "success": False,
            "status": "failed",
            "mode": "apply" if apply_changes else "dry_run",
            "apply_requested": bool(apply_changes),
            "definition_version": COSMOS_STALE_CACHE_CLEANUP_DEFINITION_VERSION,
            "batch_size": safe_batch_size,
            "candidate_count": 0,
            "deleted_count": 0,
            "skipped_count": 0,
            "failed_count": 1,
            "has_more_candidates": False,
            "categories": _build_category_summary(category_counts),
            "evaluated_at": now_iso,
            "error": str(exc),
        }

    for document in candidate_documents:
        category_id = _classify_cleanup_candidate(document, now)
        if not category_id:
            skipped_count += 1
            continue

        candidate_count += 1
        _increment_category_count(category_counts, category_id, "candidate_count")
        document_id = str(document.get("id") or "").strip()
        if not document_id:
            skipped_count += 1
            _increment_category_count(category_counts, category_id, "skipped_count")
            continue

        if not apply_changes:
            continue

        try:
            cleanup_container.delete_item(item=document_id, partition_key=document_id)
            deleted_count += 1
            _increment_category_count(category_counts, category_id, "deleted_count")
        except Exception as exc:
            if _is_not_found_error(exc):
                skipped_count += 1
                _increment_category_count(category_counts, category_id, "skipped_count")
                continue
            failed_count += 1
            _increment_category_count(category_counts, category_id, "failed_count")
            log_event(
                "[COSMOS_STALE_CLEANUP] Failed to delete stale cache document.",
                extra={
                    "category": category_id,
                    "document_id_hash": _hash_document_id(document_id),
                    "error": str(exc),
                },
                level=logging.ERROR,
                exceptionTraceback=True,
            )

    status = "completed"
    if failed_count:
        status = "completed_with_errors"
    elif not apply_changes:
        status = "dry_run_completed"

    result = {
        "success": failed_count == 0,
        "status": status,
        "mode": "apply" if apply_changes else "dry_run",
        "apply_requested": bool(apply_changes),
        "definition_version": COSMOS_STALE_CACHE_CLEANUP_DEFINITION_VERSION,
        "batch_size": safe_batch_size,
        "candidate_count": candidate_count,
        "deleted_count": deleted_count,
        "skipped_count": skipped_count,
        "failed_count": failed_count,
        "has_more_candidates": len(candidate_documents) >= safe_batch_size,
        "categories": _build_category_summary(category_counts),
        "evaluated_at": now_iso,
    }
    log_event(
        "[COSMOS_STALE_CLEANUP] Stale cache cleanup completed.",
        extra={
            "mode": result["mode"],
            "candidate_count": candidate_count,
            "deleted_count": deleted_count,
            "failed_count": failed_count,
            "has_more_candidates": result["has_more_candidates"],
        },
        level=logging.INFO if result["success"] else logging.WARNING,
    )
    return result
