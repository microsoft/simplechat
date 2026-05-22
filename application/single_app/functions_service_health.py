# functions_service_health.py

from datetime import datetime, timezone
import logging

from functions_appinsights import log_event


SEMANTIC_SEARCH_HEALTH_KEY = "semantic_search"
SEMANTIC_SEARCH_OK_STATUS = "ok"
SEMANTIC_SEARCH_QUOTA_STATUS = "quota_exceeded"
SEMANTIC_SEARCH_QUOTA_WARNING_TYPE = "semantic_search_quota_exceeded"
SEMANTIC_SEARCH_QUOTA_USER_MESSAGE = (
    "Azure AI Search Semantic Ranker free query usage has been exceeded for the month. "
    "Workspace search may return no document context until the quota resets or an admin upgrades Semantic Ranker to Standard."
)
SEMANTIC_SEARCH_QUOTA_ADMIN_RESOLUTION = (
    "Upgrade Azure AI Search Semantic Ranker to Standard or wait for the monthly free semantic query quota reset."
)


class SemanticSearchQuotaExceededError(RuntimeError):
    """Raised when Azure AI Search reports exhausted free semantic query usage."""

    def __init__(self, message=SEMANTIC_SEARCH_QUOTA_USER_MESSAGE):
        super().__init__(message)
        self.warning_type = SEMANTIC_SEARCH_QUOTA_WARNING_TYPE
        self.user_message = message


def get_default_service_health():
    """Return the default service-health structure persisted in app settings."""
    return {
        SEMANTIC_SEARCH_HEALTH_KEY: {
            "status": SEMANTIC_SEARCH_OK_STATUS,
            "severity": "info",
            "last_seen_at": None,
            "message": "",
            "user_message": "",
            "admin_resolution": "",
            "source": "",
            "occurrence_count": 0,
        }
    }


def is_semantic_search_quota_error(error):
    """Return True when an exception looks like exhausted Azure AI Search semantic quota."""
    error_text = str(error or "").lower()
    if "semantic" not in error_text:
        return False

    direct_patterns = (
        "free query semantic usage exceeded",
        "query semantic usage exceeded",
        "semantic usage exceeded",
        "semantic ranker usage exceeded",
    )
    if any(pattern in error_text for pattern in direct_patterns):
        return True

    return (
        ("quota" in error_text or "usage" in error_text)
        and ("exceed" in error_text or "exceeded" in error_text)
    )


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def _sanitize_error_summary(error):
    error_text = str(error or "").strip()
    if not error_text:
        return "Azure AI Search semantic query usage exceeded."

    if "Free Query Semantic Usage" in error_text:
        return "Free Query Semantic Usage exceeded for the month."

    return "Azure AI Search Semantic Ranker free query usage exceeded."


def record_semantic_search_quota_exceeded(error=None, source="hybrid_search"):
    """Persist a global semantic-search health warning for frontend pages."""
    try:
        from functions_settings import get_settings, update_settings

        settings = get_settings() or {}
        service_health = dict(settings.get("service_health") or {})
        existing_health = dict(service_health.get(SEMANTIC_SEARCH_HEALTH_KEY) or {})
        timestamp = _utc_now_iso()

        try:
            occurrence_count = int(existing_health.get("occurrence_count") or 0) + 1
        except (TypeError, ValueError):
            occurrence_count = 1

        service_health[SEMANTIC_SEARCH_HEALTH_KEY] = {
            "status": SEMANTIC_SEARCH_QUOTA_STATUS,
            "severity": "warning",
            "warning_type": SEMANTIC_SEARCH_QUOTA_WARNING_TYPE,
            "first_seen_at": existing_health.get("first_seen_at") or timestamp,
            "last_seen_at": timestamp,
            "message": _sanitize_error_summary(error),
            "user_message": SEMANTIC_SEARCH_QUOTA_USER_MESSAGE,
            "admin_resolution": SEMANTIC_SEARCH_QUOTA_ADMIN_RESOLUTION,
            "source": source,
            "occurrence_count": occurrence_count,
        }
        if not update_settings({"service_health": service_health}):
            raise RuntimeError("update_settings returned False while recording semantic quota warning.")
        log_event(
            "[ServiceHealth] Azure AI Search semantic quota exceeded.",
            extra={
                "service": SEMANTIC_SEARCH_HEALTH_KEY,
                "source": source,
                "occurrence_count": occurrence_count,
            },
            level=logging.WARNING,
        )
        return service_health[SEMANTIC_SEARCH_HEALTH_KEY]
    except Exception as ex:
        log_event(
            "[ServiceHealth] Failed to record semantic search quota warning.",
            extra={"error": str(ex), "source": source},
            level=logging.ERROR,
            exceptionTraceback=True,
        )
        return None


def clear_semantic_search_quota_warning(source="hybrid_search"):
    """Clear a persisted semantic quota warning after semantic search succeeds again."""
    try:
        from functions_settings import get_settings, update_settings

        settings = get_settings() or {}
        service_health = dict(settings.get("service_health") or {})
        existing_health = dict(service_health.get(SEMANTIC_SEARCH_HEALTH_KEY) or {})
        if existing_health.get("status") != SEMANTIC_SEARCH_QUOTA_STATUS:
            return False

        cleared_health = get_default_service_health()[SEMANTIC_SEARCH_HEALTH_KEY]
        cleared_health["last_cleared_at"] = _utc_now_iso()
        cleared_health["source"] = source
        service_health[SEMANTIC_SEARCH_HEALTH_KEY] = cleared_health
        if not update_settings({"service_health": service_health}):
            raise RuntimeError("update_settings returned False while clearing semantic quota warning.")
        log_event(
            "[ServiceHealth] Azure AI Search semantic quota warning cleared after successful search.",
            extra={"service": SEMANTIC_SEARCH_HEALTH_KEY, "source": source},
            level=logging.INFO,
        )
        return True
    except Exception as ex:
        log_event(
            "[ServiceHealth] Failed to clear semantic search quota warning.",
            extra={"error": str(ex), "source": source},
            level=logging.ERROR,
            exceptionTraceback=True,
        )
        return False
