# functions_dlp.py

import hashlib
import logging
import re
from collections import OrderedDict

from functions_dlp_presidio import analyze_with_presidio_endpoint
from functions_dlp_rules import get_effective_dlp_regex_rules, scan_text_with_dlp_regex_rules

try:
    from functions_appinsights import log_event
except Exception:
    def log_event(message, extra=None, level=logging.INFO, exceptionTraceback=False):
        logging.log(level, "%s %s", message, extra or {})


WEB_SEARCH_BLOCKED_MESSAGE = "Web search was blocked because the message appears to contain non-public information."
WEB_SEARCH_REDACTED_MESSAGE = "Sensitive details were removed before web search."

DEFAULT_MAX_SCAN_CHARS = 200000
DEFAULT_SCANNER_TIMEOUT_SECONDS = 5
SUPPORTED_WEB_SEARCH_MODES = {"monitor", "redact", "block"}
UNKNOWN_DLP_ENTITY_TYPE = "UNKNOWN_ENTITY"
SAFE_DLP_ENTITY_TYPE_PATTERN = re.compile(r"^[A-Z0-9_]{1,64}$")

def _bool_setting(settings, key, default=False):
    return bool((settings or {}).get(key, default))


def _safe_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_engine(settings):
    """Return the configured DLP engine."""
    requested = str((settings or {}).get("dlp_default_engine", "regex") or "regex").strip().lower()
    if requested in {"regex", "presidio_endpoint"}:
        return requested
    return "regex"


def _normalize_mode(settings, surface):
    if surface == "web_search":
        mode = str((settings or {}).get("web_search_dlp_mode", "monitor") or "monitor").lower()
    elif surface == "upload":
        mode = str((settings or {}).get("upload_dlp_mode", "monitor") or "monitor").lower()
    else:
        mode = str((settings or {}).get("dlp_mode", "monitor") or "monitor").lower()

    return mode if mode in SUPPORTED_WEB_SEARCH_MODES else "monitor"


def _empty_result(text, enabled=False, engine="regex", mode="monitor", decision="allow", scanner_status="ok"):
    safe_text = str(text or "")
    return {
        "enabled": enabled,
        "engine": engine,
        "mode": mode,
        "decision": decision,
        "text": safe_text,
        "redacted_text": safe_text,
        "total_replacements": 0,
        "match_counts": {},
        "matches": [],
        "metadata": {},
        "scanner_status": scanner_status,
    }


def _apply_regex_engine(text, settings=None, surface="generic"):
    rules, rule_errors = get_effective_dlp_regex_rules(settings or {})
    redacted_text, match_counts, matches, rule_metadata = scan_text_with_dlp_regex_rules(
        text,
        rules,
        surface,
    )
    return redacted_text, match_counts, matches, {
        "rule_errors": len(rule_errors),
        **rule_metadata,
    }


def _apply_presidio_endpoint_engine(text, settings=None, surface="generic"):
    recognizer_results = analyze_with_presidio_endpoint(text, settings or {})
    normalized = normalize_external_analyzer_results(
        text,
        recognizer_results,
        mode=_normalize_mode(settings or {}, surface),
        engine="presidio_endpoint",
    )
    return (
        normalized["redacted_text"],
        normalized["match_counts"],
        normalized["matches"],
        {"adapter": "presidio_endpoint"},
    )


def _decision_from_counts(match_counts, mode):
    if not match_counts:
        return "allow"
    if mode == "block":
        return "block"
    if mode == "redact":
        return "redact"
    return "monitor"


def normalize_dlp_entity_type(entity_type):
    """Normalize untrusted analyzer entity labels before they reach outputs."""
    normalized = str(entity_type or "").strip().upper()
    if SAFE_DLP_ENTITY_TYPE_PATTERN.fullmatch(normalized):
        return normalized
    return UNKNOWN_DLP_ENTITY_TYPE


def _safe_result_start(item):
    try:
        return int(item.get("start"))
    except (TypeError, ValueError):
        return 0


def normalize_external_analyzer_results(text, recognizer_results, mode="redact", engine="external_analyzer"):
    """Normalize external analyzer entity offsets into the shared counts-only result."""
    source_text = str(text or "")
    sorted_results = sorted(
        [
            item for item in (recognizer_results or [])
            if isinstance(item, dict) and item.get("start") is not None and item.get("end") is not None
        ],
        key=_safe_result_start,
    )
    match_counts = OrderedDict()
    redacted_parts = []
    cursor = 0

    for item in sorted_results:
        start = max(0, min(len(source_text), int(item.get("start"))))
        end = max(start, min(len(source_text), int(item.get("end"))))
        entity_type = normalize_dlp_entity_type(item.get("entity_type"))
        if start < cursor:
            continue
        redacted_parts.append(source_text[cursor:start])
        redacted_parts.append(f"[REDACTED_{entity_type}]")
        cursor = end
        match_counts[entity_type] = match_counts.get(entity_type, 0) + 1

    redacted_parts.append(source_text[cursor:])
    redacted_text = "".join(redacted_parts)
    counts = dict(match_counts)
    decision = _decision_from_counts(counts, mode)

    return {
        "enabled": True,
        "engine": engine,
        "mode": mode,
        "decision": decision,
        "text": redacted_text if counts else source_text,
        "redacted_text": redacted_text if counts else source_text,
        "total_replacements": sum(counts.values()),
        "match_counts": counts,
        "matches": [{"entity_type": key, "count": value} for key, value in counts.items()],
        "metadata": {"adapter": "external_analyzer"},
        "scanner_status": "ok",
    }


def evaluate_dlp_text(text, settings=None, context=None, surface="generic"):
    """Evaluate text against the configured DLP policy and return a safe result."""
    settings = settings or {}
    context = context or {}
    original_text = str(text or "")
    engine = _normalize_engine(settings)
    mode = _normalize_mode(settings, surface)
    max_scan_chars = _safe_int(settings.get("dlp_max_scan_chars"), DEFAULT_MAX_SCAN_CHARS)

    if not _bool_setting(settings, "enable_dlp_control_plane", False):
        return _empty_result(original_text, enabled=False, engine=engine, mode=mode, decision="allow")

    scan_text = original_text[:max_scan_chars]
    skipped_chars = max(0, len(original_text) - len(scan_text))
    upload_fail_on_match = surface == "upload" and _bool_setting(settings, "upload_dlp_fail_upload_on_match", False)

    if skipped_chars and surface in {"web_search", "upload"} and (mode in {"redact", "block"} or upload_fail_on_match):
        return {
            "enabled": True,
            "engine": engine,
            "mode": mode,
            "decision": "block",
            "text": "",
            "redacted_text": "",
            "total_replacements": 0,
            "match_counts": {},
            "matches": [],
            "metadata": {"skipped_chars": skipped_chars},
            "scanner_status": "truncated",
        }

    try:
        if engine == "presidio_endpoint":
            redacted_text, match_counts, matches, scanner_metadata = _apply_presidio_endpoint_engine(
                scan_text,
                settings,
                surface,
            )
        else:
            redacted_text, match_counts, matches, scanner_metadata = _apply_regex_engine(scan_text, settings, surface)
    except Exception as exc:
        log_event(
            "[DLP] Scanner error",
            extra={
                "dlp_surface": surface,
                "dlp_engine": engine,
                "scanner_status": "error",
                "error_type": type(exc).__name__,
            },
            level=logging.WARNING,
            exceptionTraceback=False,
        )
        fail_closed = _bool_setting(settings, "dlp_fail_closed_on_scanner_error", True)
        return {
            "enabled": True,
            "engine": engine,
            "mode": mode,
            "decision": "block" if fail_closed else "allow",
            "text": "" if fail_closed else original_text,
            "redacted_text": "" if fail_closed else original_text,
            "total_replacements": 0,
            "match_counts": {},
            "matches": [],
            "metadata": {"error_hash": hashlib.sha256(str(exc).encode("utf-8")).hexdigest()[:16]},
            "scanner_status": "error",
        }

    if skipped_chars and mode == "monitor":
        metadata = dict(scanner_metadata)
        metadata["skipped_chars"] = skipped_chars
        metadata = {key: value for key, value in metadata.items() if value not in ("", None, {}, [])}
        return {
            "enabled": True,
            "engine": engine,
            "mode": mode,
            "decision": "allow",
            "text": original_text,
            "redacted_text": original_text,
            "total_replacements": sum(match_counts.values()),
            "match_counts": dict(match_counts),
            "matches": matches,
            "metadata": metadata,
            "scanner_status": "truncated",
        }

    decision = _decision_from_counts(match_counts, mode)
    safe_text = "" if decision == "block" else (redacted_text if match_counts else original_text)
    safe_redacted_text = "" if decision == "block" else (redacted_text if match_counts else original_text)
    metadata = dict(scanner_metadata)
    if skipped_chars:
        metadata["skipped_chars"] = skipped_chars
    metadata = {key: value for key, value in metadata.items() if value not in ("", None, {}, [])}

    return {
        "enabled": True,
        "engine": engine,
        "mode": mode,
        "decision": decision,
        "text": safe_text,
        "redacted_text": safe_redacted_text,
        "total_replacements": sum(match_counts.values()),
        "match_counts": dict(match_counts),
        "matches": matches,
        "metadata": metadata,
        "scanner_status": "truncated" if skipped_chars else "ok",
    }


def evaluate_web_search_egress(text, settings=None, context=None):
    """Evaluate and shape DLP decisions for web-search egress."""
    settings = settings or {}
    context = context or {}

    if not _bool_setting(settings, "enable_web_search_dlp", False):
        result = _empty_result(
            text,
            enabled=_bool_setting(settings, "enable_dlp_control_plane", False),
            engine=_normalize_engine(settings),
            mode=_normalize_mode(settings, "web_search"),
            decision="allow",
        )
    else:
        result = evaluate_dlp_text(text, settings=settings, context=context, surface="web_search")

    decision = result.get("decision", "allow")
    web_search_allowed = decision != "block"
    if decision == "block":
        status_message = WEB_SEARCH_BLOCKED_MESSAGE
        web_search_query_text = ""
    elif decision == "redact":
        status_message = WEB_SEARCH_REDACTED_MESSAGE
        web_search_query_text = result.get("redacted_text", "")
    else:
        status_message = ""
        web_search_query_text = str(text or "")

    shaped = dict(result)
    shaped.update(
        {
            "web_search_allowed": web_search_allowed,
            "web_search_query_text": web_search_query_text,
            "status_message": status_message,
        }
    )
    return shaped


def _safe_entity_counts(match_counts):
    counts = OrderedDict()
    for entity_type, count in (match_counts or {}).items():
        try:
            normalized_count = int(count)
        except (TypeError, ValueError):
            continue
        if normalized_count <= 0:
            continue
        safe_entity_type = normalize_dlp_entity_type(entity_type)
        counts[safe_entity_type] = counts.get(safe_entity_type, 0) + normalized_count
    return dict(counts)


def _error_hash(result):
    metadata = result.get("metadata") if isinstance(result, dict) else {}
    raw_error = ""
    if isinstance(metadata, dict):
        raw_error = str(metadata.get("error") or metadata.get("error_hash") or "")
    if not raw_error:
        raw_error = "scanner_error"
    return hashlib.sha256(raw_error.encode("utf-8")).hexdigest()[:16]


def build_dlp_telemetry_properties(result, surface, context=None):
    """Build App Insights-safe DLP telemetry properties."""
    result = result or {}
    context = context or {}
    properties = {
        "activity_type": "dlp_decision",
        "dlp_surface": str(surface or "unknown"),
        "dlp_action": str(result.get("decision") or "allow"),
        "dlp_engine": str(result.get("engine") or "unknown"),
        "dlp_mode": str(result.get("mode") or "monitor"),
        "workspace_scope": str(context.get("workspace_scope") or context.get("document_scope") or "unknown"),
        "scanner_status": str(result.get("scanner_status") or "ok"),
        "dlp_total_replacements": int(result.get("total_replacements") or 0),
        "dlp_entity_counts": _safe_entity_counts(result.get("match_counts")),
    }

    for key in ("conversation_id", "chat_type", "document_scope", "document_id"):
        if context.get(key):
            properties[key] = str(context.get(key))

    if properties["scanner_status"] != "ok":
        properties["scanner_error"] = _error_hash(result)

    return properties


def should_emit_dlp_telemetry(result, settings=None):
    settings = settings or {}
    result = result or {}
    if not _bool_setting(settings, "dlp_enable_structured_telemetry", True):
        return False
    action = str(result.get("decision") or "allow")
    if action in {"block", "redact"}:
        return True
    if str(result.get("scanner_status") or "ok") != "ok":
        return True
    if _safe_int(result.get("total_replacements"), 0) > 0:
        return True
    if _safe_entity_counts(result.get("match_counts")):
        return True
    return _bool_setting(settings, "dlp_telemetry_sample_allow_events", False)


def build_dlp_review_event_summary(result, surface, context=None):
    """Build a counts-only review payload for optional DLP review routing."""
    result = result or {}
    context = context or {}
    normalized_surface = str(surface or "unknown")
    policy_type = "dlp_web_search" if normalized_surface == "web_search" else f"dlp_{normalized_surface}"

    summary = {
        "policy_type": policy_type,
        "violation_type": "dlp",
        "surface": normalized_surface,
        "action": str(result.get("decision") or "allow"),
        "engine": str(result.get("engine") or "unknown"),
        "mode": str(result.get("mode") or "monitor"),
        "entity_counts": _safe_entity_counts(result.get("match_counts")),
        "total_replacements": int(result.get("total_replacements") or 0),
        "scanner_status": str(result.get("scanner_status") or "ok"),
        "raw_matches": None,
    }

    for key in ("conversation_id", "user_id", "document_id", "chat_type", "document_scope"):
        if context.get(key):
            summary[key] = str(context.get(key))

    return summary


def evaluate_upload_content(text, settings=None, context=None):
    """PR2-facing helper for upload DLP; upload wiring is added later."""
    settings = settings or {}
    context = context or {}

    if not _bool_setting(settings, "enable_upload_dlp", False):
        result = _empty_result(
            text,
            enabled=_bool_setting(settings, "enable_dlp_control_plane", False),
            engine=str(settings.get("dlp_default_engine", "regex") or "regex"),
            mode=_normalize_mode(settings, "upload"),
            decision="allow",
        )
    else:
        result = evaluate_dlp_text(text, settings=settings, context=context, surface="upload")

    if (
        _bool_setting(settings, "upload_dlp_fail_upload_on_match", False)
        and int(result.get("total_replacements") or 0) > 0
    ):
        result = dict(result)
        result["decision"] = "block"
        result["text"] = ""
        result["redacted_text"] = ""

    decision = result.get("decision", "allow")
    scanner_status = result.get("scanner_status", "ok")
    upload_allowed = decision != "block" and scanner_status != "blocked"
    if scanner_status != "ok" and decision == "block":
        status = "scanner_failed"
    elif decision == "block":
        status = "blocked"
    elif decision == "redact":
        status = "accepted_with_redactions"
    elif decision == "monitor":
        status = "accepted_with_dlp_monitoring"
    else:
        status = "accepted"

    if decision == "block":
        sanitized_text = ""
    elif decision == "redact":
        sanitized_text = result.get("redacted_text", "")
    else:
        sanitized_text = str(text or "")

    shaped = dict(result)
    shaped.update(
        {
            "upload_allowed": upload_allowed,
            "sanitized_text": sanitized_text,
            "status": status,
            "dlp_metadata": build_dlp_metadata_summary(result, surface="upload", context=context),
        }
    )
    return shaped


def build_dlp_metadata_summary(result, surface, context=None):
    """Build counts-only DLP metadata safe for document records."""
    result = result or {}
    context = context or {}
    summary = {
        "dlp_surface": str(surface or "unknown"),
        "dlp_action": str(result.get("decision") or "allow"),
        "dlp_engine": str(result.get("engine") or "unknown"),
        "dlp_mode": str(result.get("mode") or "monitor"),
        "scanner_status": str(result.get("scanner_status") or "ok"),
        "total_replacements": int(result.get("total_replacements") or 0),
        "entity_counts": _safe_entity_counts(result.get("match_counts")),
    }
    for key in ("workspace_scope", "document_id"):
        if context.get(key):
            summary[key] = str(context.get(key))
    return summary


def build_upload_dlp_file_log_summary(result, context=None):
    """Build a safe file-processing log summary for upload DLP decisions."""
    result = result or {}
    context = context or {}
    summary = build_dlp_metadata_summary(result, surface="upload", context=context)
    for key in ("document_id", "workspace_scope", "page_number", "text_length"):
        if context.get(key) is not None:
            summary[key] = context.get(key)
    return summary
