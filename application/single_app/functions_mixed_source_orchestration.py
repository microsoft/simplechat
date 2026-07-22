# functions_mixed_source_orchestration.py
"""Authorization-safe source manifest and evidence contracts for mixed sources."""

import json
import logging
import math
import os
import time

from functions_appinsights import log_event


SOURCE_KIND_TABULAR = "tabular"
SOURCE_KIND_NARRATIVE = "narrative"
SOURCE_KIND_UNSUPPORTED = "unsupported"
SOURCE_KIND_UNRESOLVED = "unresolved"
SOURCE_KINDS = frozenset({
    SOURCE_KIND_TABULAR,
    SOURCE_KIND_NARRATIVE,
    SOURCE_KIND_UNSUPPORTED,
    SOURCE_KIND_UNRESOLVED,
})

SOURCE_SCOPE_PERSONAL = "personal"
SOURCE_SCOPE_GROUP = "group"
SOURCE_SCOPE_PUBLIC = "public"
SOURCE_SCOPE_CHAT = "chat"
SOURCE_SCOPES = frozenset({
    SOURCE_SCOPE_PERSONAL,
    SOURCE_SCOPE_GROUP,
    SOURCE_SCOPE_PUBLIC,
    SOURCE_SCOPE_CHAT,
})

AUTHORIZATION_STATUS_AUTHORIZED = "authorized"
AUTHORIZATION_STATUS_UNRESOLVED = "unresolved"
SOURCE_MANIFEST_MAX_SOURCES = 100

SELECTION_MODE_SELECTED = "selected"
SELECTION_MODE_ALL = "all"
SELECTION_MODE_HISTORY = "history"
SELECTION_MODE_RELEVANCE = "relevance"
SELECTION_MODES = frozenset({
    SELECTION_MODE_SELECTED,
    SELECTION_MODE_ALL,
    SELECTION_MODE_HISTORY,
    SELECTION_MODE_RELEVANCE,
})

TABULAR_SOURCE_EXTENSIONS = frozenset({".csv", ".xls", ".xlsx", ".xlsm"})
NARRATIVE_SOURCE_EXTENSIONS = frozenset({
    ".txt", ".doc", ".docm", ".docx", ".html", ".htm", ".md", ".markdown",
    ".json", ".xml", ".yaml", ".yml", ".log", ".pdf", ".ppt", ".pptx",
    ".msg", ".vsdx", ".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif",
    ".heif", ".heic", ".3ga", ".aac", ".ac3", ".aif", ".aifc", ".aiff",
    ".amr", ".ape", ".au", ".caf", ".dts", ".f4a", ".flac", ".m4a",
    ".m4b", ".m4r", ".mka", ".mp2", ".mp3", ".mpa", ".oga", ".ogg",
    ".opus", ".spx", ".wav", ".weba", ".wma", ".wv", ".mp4", ".mov",
    ".avi", ".mkv", ".flv", ".mxf", ".gxf", ".ts", ".ps", ".3gp",
    ".3gpp", ".mpg", ".wmv", ".asf", ".m4v", ".isma", ".ismv",
    ".dvr-ms", ".webm", ".mpeg",
})

EVIDENCE_ENGINE_TABULAR_TOOLS = "tabular_tools"
EVIDENCE_ENGINE_DOCUMENT_ANALYSIS = "document_analysis"
EVIDENCE_ENGINE_HYBRID_SEARCH = "hybrid_search"
EVIDENCE_ENGINES = frozenset({
    EVIDENCE_ENGINE_TABULAR_TOOLS,
    EVIDENCE_ENGINE_DOCUMENT_ANALYSIS,
    EVIDENCE_ENGINE_HYBRID_SEARCH,
})

EVIDENCE_STATUS_COMPLETED = "completed"
EVIDENCE_STATUS_PARTIAL = "partial"
EVIDENCE_STATUS_FAILED = "failed"
EVIDENCE_STATUS_SKIPPED = "skipped"
EVIDENCE_STATUSES = frozenset({
    EVIDENCE_STATUS_COMPLETED,
    EVIDENCE_STATUS_PARTIAL,
    EVIDENCE_STATUS_FAILED,
    EVIDENCE_STATUS_SKIPPED,
})

EVIDENCE_ENVELOPE_MAX_BYTES = 65536
EVIDENCE_SUMMARY_MAX_BYTES = 4096
EVIDENCE_ERROR_MAX_BYTES = 1024
EVIDENCE_LIST_MAX_ITEMS = 10
EVIDENCE_ITEM_MAX_BYTES = 1536
EVIDENCE_COVERAGE_MAX_BYTES = 4096
EVIDENCE_JSON_MAX_DEPTH = 4
EVIDENCE_JSON_MAX_COLLECTION_ITEMS = 20
EVIDENCE_JSON_MAX_STRING_BYTES = 1024


def normalize_selection_mode(selection_mode, default=SELECTION_MODE_SELECTED):
    """Return a supported selection mode or raise for an invalid explicit value."""
    normalized_default = str(default or "").strip().lower()
    if normalized_default not in SELECTION_MODES:
        raise ValueError("Invalid default selection_mode")

    normalized_mode = str(selection_mode or "").strip().lower()
    if not normalized_mode:
        return normalized_default
    if normalized_mode not in SELECTION_MODES:
        raise ValueError(
            f"selection_mode must be one of: {', '.join(sorted(SELECTION_MODES))}"
        )
    return normalized_mode


def classify_source_kind(file_name, document_item=None):
    """Classify a resolved source by native capability without reading its content."""
    normalized_file_name = str(file_name or "").strip()
    extension = os.path.splitext(normalized_file_name)[1].lower()
    if extension in TABULAR_SOURCE_EXTENSIONS:
        return SOURCE_KIND_TABULAR
    if extension in NARRATIVE_SOURCE_EXTENSIONS:
        return SOURCE_KIND_NARRATIVE

    document_item = document_item if isinstance(document_item, dict) else {}
    if any(
        document_item.get(field_name)
        for field_name in (
            "num_file_chunks",
            "comparison_text",
            "extracted_text",
            "vision_analysis",
        )
    ):
        return SOURCE_KIND_NARRATIVE
    return SOURCE_KIND_UNSUPPORTED


def _normalize_document_id(requested_source):
    if isinstance(requested_source, dict):
        requested_source = requested_source.get("document_id") or requested_source.get("id")
    return str(requested_source or "").strip()


def _normalize_identifier_list(values):
    if values is None:
        return []
    if isinstance(values, (str, int)):
        values = [values]
    return [
        normalized_value
        for normalized_value in (
            str(value or "").strip()
            for value in list(values)
        )
        if normalized_value
    ]


def _safe_file_name(file_name):
    return str(file_name or "").replace("\\", "/").split("/")[-1].strip()


def _unresolved_manifest_entry(document_id):
    return {
        "document_id": document_id,
        "display_name": None,
        "file_name": None,
        "extension": None,
        "source_kind": SOURCE_KIND_UNRESOLVED,
        "scope": None,
        "scope_id": None,
        "group_id": None,
        "public_workspace_id": None,
        "conversation_id": None,
        "source_version": None,
        "authorization_status": AUTHORIZATION_STATUS_UNRESOLVED,
    }


def _build_authorized_manifest_entry(document_id, user_id, document_context):
    if not isinstance(document_context, dict):
        return _unresolved_manifest_entry(document_id)

    document_item = document_context.get("document")
    if not isinstance(document_item, dict):
        return _unresolved_manifest_entry(document_id)

    resolved_document_id = str(document_item.get("id") or "").strip()
    if resolved_document_id != document_id:
        return _unresolved_manifest_entry(document_id)

    scope = str(document_context.get("scope") or "").strip().lower()
    if scope not in SOURCE_SCOPES:
        return _unresolved_manifest_entry(document_id)

    group_id = None
    public_workspace_id = None
    conversation_id = str(
        document_context.get("conversation_id")
        or document_item.get("conversation_id")
        or ""
    ).strip() or None

    if scope == SOURCE_SCOPE_PERSONAL:
        scope_id = str(document_item.get("user_id") or user_id or "").strip()
    elif scope == SOURCE_SCOPE_GROUP:
        group_id = str(document_context.get("group_id") or "").strip() or None
        scope_id = group_id
    elif scope == SOURCE_SCOPE_PUBLIC:
        public_workspace_id = str(
            document_context.get("public_workspace_id") or ""
        ).strip() or None
        scope_id = public_workspace_id
    else:
        scope_id = conversation_id

    if not scope_id:
        return _unresolved_manifest_entry(document_id)

    file_name = _safe_file_name(
        document_item.get("file_name")
        or document_item.get("filename")
        or document_item.get("title")
    )
    display_name = str(document_item.get("title") or file_name or document_id).strip()
    extension = os.path.splitext(file_name)[1].lower() or None
    source_version = document_item.get("version")
    if source_version is None:
        source_version = document_item.get("source_version")
    if source_version is not None and not isinstance(source_version, (str, int, float)):
        source_version = str(source_version)

    return {
        "document_id": document_id,
        "display_name": display_name,
        "file_name": file_name or None,
        "extension": extension,
        "source_kind": classify_source_kind(file_name, document_item=document_item),
        "scope": scope,
        "scope_id": scope_id,
        "group_id": group_id,
        "public_workspace_id": public_workspace_id,
        "conversation_id": conversation_id,
        "source_version": source_version,
        "authorization_status": AUTHORIZATION_STATUS_AUTHORIZED,
    }


def _default_document_context_batch_resolver(**resolver_arguments):
    # Imported lazily so this contract module remains usable by startup code and isolated tests.
    from functions_search_service import resolve_document_contexts

    resolver_arguments["include_content"] = False
    return resolve_document_contexts(**resolver_arguments)


def resolve_authorized_source_manifest(
    requested_sources,
    user_id,
    selection_mode=SELECTION_MODE_SELECTED,
    conversation_id=None,
    active_group_ids=None,
    active_public_workspace_ids=None,
    context_resolver=None,
):
    """Resolve each unique requested ID once into an ordered, authorized manifest."""
    normalized_selection_mode = normalize_selection_mode(selection_mode)
    normalized_user_id = str(user_id or "").strip()
    if not normalized_user_id:
        raise ValueError("user_id is required")

    if isinstance(requested_sources, (str, int, dict)):
        requested_source_list = [requested_sources]
    else:
        requested_source_list = list(requested_sources or [])
    if len(requested_source_list) > SOURCE_MANIFEST_MAX_SOURCES:
        log_event(
            "[MixedSourceManifest] Rejected over-limit source manifest request.",
            extra={
                "selection_mode": normalized_selection_mode,
                "requested_source_count": len(requested_source_list),
                "source_limit": SOURCE_MANIFEST_MAX_SOURCES,
            },
            level=logging.WARNING,
        )
        raise ValueError(
            f"A source manifest supports at most {SOURCE_MANIFEST_MAX_SOURCES} requested sources"
        )

    unique_document_ids = []
    seen_document_ids = set()
    duplicate_ids_removed = 0
    for requested_source in requested_source_list:
        document_id = _normalize_document_id(requested_source)
        if not document_id:
            continue
        if document_id in seen_document_ids:
            duplicate_ids_removed += 1
            continue
        seen_document_ids.add(document_id)
        unique_document_ids.append(document_id)

    if context_resolver is not None and not callable(context_resolver):
        raise TypeError("context_resolver must be callable")

    started_at = time.perf_counter()
    manifest = []
    resolution_error_count = 0
    normalized_active_group_ids = _normalize_identifier_list(active_group_ids)
    normalized_public_workspace_ids = _normalize_identifier_list(
        active_public_workspace_ids
    )
    normalized_conversation_id = str(conversation_id or "").strip() or None

    resolved_contexts = None
    if context_resolver is None:
        try:
            resolved_contexts = _default_document_context_batch_resolver(
                document_ids=unique_document_ids,
                user_id=normalized_user_id,
                doc_scope="all",
                active_group_ids=normalized_active_group_ids,
                active_public_workspace_id=normalized_public_workspace_ids,
                conversation_id=normalized_conversation_id,
            )
        except Exception:
            resolved_contexts = [None] * len(unique_document_ids)
            resolution_error_count = len(unique_document_ids)
        if (
            not isinstance(resolved_contexts, list)
            or len(resolved_contexts) != len(unique_document_ids)
        ):
            resolved_contexts = [None] * len(unique_document_ids)
            resolution_error_count = len(unique_document_ids)

    for document_index, document_id in enumerate(unique_document_ids):
        document_context = None
        if resolved_contexts is not None:
            document_context = resolved_contexts[document_index]
        else:
            try:
                document_context = context_resolver(
                    document_id=document_id,
                    user_id=normalized_user_id,
                    doc_scope="all",
                    active_group_ids=normalized_active_group_ids,
                    active_public_workspace_id=normalized_public_workspace_ids,
                    conversation_id=normalized_conversation_id,
                )
            except Exception:
                resolution_error_count += 1
        manifest.append(
            _build_authorized_manifest_entry(
                document_id,
                normalized_user_id,
                document_context,
            )
        )

    source_kind_counts = {source_kind: 0 for source_kind in SOURCE_KINDS}
    scope_distribution = {scope: 0 for scope in SOURCE_SCOPES}
    for entry in manifest:
        source_kind_counts[entry["source_kind"]] += 1
        if entry["scope"] in scope_distribution:
            scope_distribution[entry["scope"]] += 1

    duration_ms = round((time.perf_counter() - started_at) * 1000, 3)
    resolved_source_count = len(manifest) - source_kind_counts[SOURCE_KIND_UNRESOLVED]
    log_event(
        "[MixedSourceManifest] Resolved authorized source manifest.",
        extra={
            "selection_mode": normalized_selection_mode,
            "requested_source_count": len(requested_source_list),
            "unique_source_count": len(unique_document_ids),
            "resolved_source_count": resolved_source_count,
            "tabular_source_count": source_kind_counts[SOURCE_KIND_TABULAR],
            "narrative_source_count": source_kind_counts[SOURCE_KIND_NARRATIVE],
            "unsupported_source_count": source_kind_counts[SOURCE_KIND_UNSUPPORTED],
            "unresolved_or_unauthorized_count": source_kind_counts[SOURCE_KIND_UNRESOLVED],
            "duplicate_ids_removed": duplicate_ids_removed,
            "resolution_error_count": resolution_error_count,
            "scope_distribution": scope_distribution,
            "manifest_resolution_duration_ms": duration_ms,
        },
        level=logging.INFO,
    )
    return manifest


def partition_source_manifest(manifest):
    """Partition a manifest by capability while preserving order within each cohort."""
    partitions = {
        "tabular_sources": [],
        "narrative_sources": [],
        "unsupported_sources": [],
        "unresolved_sources": [],
    }
    partition_key_by_source_kind = {
        SOURCE_KIND_TABULAR: "tabular_sources",
        SOURCE_KIND_NARRATIVE: "narrative_sources",
        SOURCE_KIND_UNSUPPORTED: "unsupported_sources",
        SOURCE_KIND_UNRESOLVED: "unresolved_sources",
    }

    for raw_entry in list(manifest or []):
        entry = raw_entry if isinstance(raw_entry, dict) else {}
        document_id = _normalize_document_id(entry)
        if entry.get("authorization_status") != AUTHORIZATION_STATUS_AUTHORIZED:
            partitions["unresolved_sources"].append(
                _unresolved_manifest_entry(document_id)
            )
            continue

        partition_key = partition_key_by_source_kind.get(
            entry.get("source_kind"),
            "unsupported_sources",
        )
        partitions[partition_key].append(entry)

    return partitions


def _truncate_utf8(value, max_bytes):
    normalized_value = str(value or "")
    encoded_value = normalized_value.encode("utf-8")
    if len(encoded_value) <= max_bytes:
        return normalized_value
    if max_bytes <= 3:
        return encoded_value[:max_bytes].decode("utf-8", errors="ignore")
    return (
        encoded_value[:max_bytes - 3].decode("utf-8", errors="ignore").rstrip()
        + "..."
    )


def _make_json_safe(value, depth=0):
    if value is None or isinstance(value, (bool, int)):
        return value, False
    if isinstance(value, float):
        return (value, False) if math.isfinite(value) else (None, True)
    if isinstance(value, str):
        bounded_value = _truncate_utf8(value, EVIDENCE_JSON_MAX_STRING_BYTES)
        return bounded_value, bounded_value != value
    if depth >= EVIDENCE_JSON_MAX_DEPTH:
        return _truncate_utf8(str(value), EVIDENCE_JSON_MAX_STRING_BYTES), True
    if isinstance(value, dict):
        source_items = list(value.items())
        bounded_value = {}
        was_truncated = len(source_items) > EVIDENCE_JSON_MAX_COLLECTION_ITEMS
        for key, item_value in source_items[:EVIDENCE_JSON_MAX_COLLECTION_ITEMS]:
            normalized_key = _truncate_utf8(key, 128)
            bounded_item, item_was_truncated = _make_json_safe(
                item_value,
                depth + 1,
            )
            if (
                not isinstance(key, str)
                or normalized_key != key
                or normalized_key in bounded_value
            ):
                was_truncated = True
            bounded_value[normalized_key] = bounded_item
            was_truncated = was_truncated or item_was_truncated
        return bounded_value, was_truncated
    if isinstance(value, (list, tuple, set)):
        source_items = list(value)
        bounded_value = []
        was_truncated = len(source_items) > EVIDENCE_JSON_MAX_COLLECTION_ITEMS
        for item in source_items[:EVIDENCE_JSON_MAX_COLLECTION_ITEMS]:
            bounded_item, item_was_truncated = _make_json_safe(item, depth + 1)
            bounded_value.append(bounded_item)
            was_truncated = was_truncated or item_was_truncated
        return bounded_value, was_truncated
    return _truncate_utf8(str(value), EVIDENCE_JSON_MAX_STRING_BYTES), True


def _json_size_bytes(value):
    return len(
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _bound_json_value(value, max_bytes):
    safe_value, safe_value_was_truncated = _make_json_safe(value)
    if _json_size_bytes(safe_value) <= max_bytes:
        return safe_value, safe_value_was_truncated

    serialized_preview = json.dumps(
        safe_value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    preview_max_bytes = max(16, max_bytes // 3)
    while preview_max_bytes > 0:
        bounded_value = {
            "truncated": True,
            "preview": _truncate_utf8(serialized_preview, preview_max_bytes),
        }
        if _json_size_bytes(bounded_value) <= max_bytes:
            return bounded_value, True
        preview_max_bytes //= 2
    return {"truncated": True}, True


def _bound_json_list(values):
    if values is None:
        return [], False
    if not isinstance(values, (list, tuple)):
        raise ValueError("Evidence collection values must be lists")

    source_values = list(values)
    bounded_values = []
    was_truncated = len(source_values) > EVIDENCE_LIST_MAX_ITEMS
    for value in source_values[:EVIDENCE_LIST_MAX_ITEMS]:
        bounded_value, value_was_truncated = _bound_json_value(
            value,
            EVIDENCE_ITEM_MAX_BYTES,
        )
        bounded_values.append(bounded_value)
        was_truncated = was_truncated or value_was_truncated
    return bounded_values, was_truncated


def _build_truncated_coverage(coverage, coverage_was_truncated=False):
    normalized_coverage = dict(coverage or {})
    normalized_coverage["evidence_envelope_truncated"] = True
    if coverage_was_truncated:
        normalized_coverage["coverage_truncated"] = True

    bounded_coverage, additional_truncation = _bound_json_value(
        normalized_coverage,
        EVIDENCE_COVERAGE_MAX_BYTES,
    )
    if additional_truncation:
        return {
            "evidence_envelope_truncated": True,
            "coverage_truncated": True,
        }
    return bounded_coverage


def build_evidence_envelope(
    document_id,
    source_kind,
    engine,
    status,
    summary="",
    evidence=None,
    citations=None,
    generated_artifacts=None,
    coverage=None,
    error=None,
):
    """Build a bounded, JSON-safe evidence envelope for later synthesis phases."""
    normalized_document_id = str(document_id or "").strip()
    if not normalized_document_id:
        raise ValueError("document_id is required")

    normalized_source_kind = str(source_kind or "").strip().lower()
    if normalized_source_kind not in {SOURCE_KIND_TABULAR, SOURCE_KIND_NARRATIVE}:
        raise ValueError("Evidence source_kind must be tabular or narrative")

    normalized_engine = str(engine or "").strip().lower()
    if normalized_engine not in EVIDENCE_ENGINES:
        raise ValueError(f"Unsupported evidence engine: {normalized_engine}")

    normalized_status = str(status or "").strip().lower()
    if normalized_status not in EVIDENCE_STATUSES:
        raise ValueError(f"Unsupported evidence status: {normalized_status}")

    if coverage is not None and not isinstance(coverage, dict):
        raise ValueError("coverage must be a dictionary")

    bounded_evidence, evidence_was_truncated = _bound_json_list(evidence)
    bounded_citations, citations_were_truncated = _bound_json_list(citations)
    bounded_artifacts, artifacts_were_truncated = _bound_json_list(generated_artifacts)
    normalized_summary = _truncate_utf8(summary, EVIDENCE_SUMMARY_MAX_BYTES)
    normalized_error = (
        _truncate_utf8(error, EVIDENCE_ERROR_MAX_BYTES)
        if error is not None
        else None
    )
    bounds_applied = bool(
        evidence_was_truncated
        or citations_were_truncated
        or artifacts_were_truncated
        or len(str(summary or "").encode("utf-8")) > EVIDENCE_SUMMARY_MAX_BYTES
        or (
            error is not None
            and len(str(error).encode("utf-8")) > EVIDENCE_ERROR_MAX_BYTES
        )
    )
    normalized_coverage = dict(coverage or {})
    if bounds_applied:
        normalized_coverage["evidence_envelope_truncated"] = True
    bounded_coverage, coverage_was_truncated = _bound_json_value(
        normalized_coverage,
        EVIDENCE_COVERAGE_MAX_BYTES,
    )
    if coverage_was_truncated:
        bounded_coverage = _build_truncated_coverage(
            {},
            coverage_was_truncated=True,
        )

    envelope = {
        "document_id": normalized_document_id,
        "source_kind": normalized_source_kind,
        "engine": normalized_engine,
        "status": normalized_status,
        "summary": normalized_summary,
        "evidence": bounded_evidence,
        "citations": bounded_citations,
        "generated_artifacts": bounded_artifacts,
        "coverage": bounded_coverage,
        "error": normalized_error,
    }

    while _json_size_bytes(envelope) > EVIDENCE_ENVELOPE_MAX_BYTES:
        candidate_field = max(
            ("evidence", "citations", "generated_artifacts"),
            key=lambda field_name: len(envelope[field_name]),
        )
        if envelope[candidate_field]:
            envelope[candidate_field].pop()
            envelope["coverage"] = _build_truncated_coverage(
                envelope["coverage"],
            )
            continue
        envelope["summary"] = _truncate_utf8(
            envelope["summary"],
            max(128, len(envelope["summary"].encode("utf-8")) // 2),
        )
        if len(envelope["summary"].encode("utf-8")) <= 128:
            raise ValueError("Unable to bound evidence envelope")

    return envelope


def serialize_evidence_envelope(envelope):
    """Validate and serialize a bounded evidence envelope."""
    if not isinstance(envelope, dict):
        raise ValueError("Evidence envelope must be a dictionary")

    required_fields = {
        "document_id",
        "source_kind",
        "engine",
        "status",
        "summary",
        "evidence",
        "citations",
        "generated_artifacts",
        "coverage",
        "error",
    }
    if set(envelope) != required_fields:
        raise ValueError("Evidence envelope fields do not match the contract")

    bounded_envelope = build_evidence_envelope(
        document_id=envelope["document_id"],
        source_kind=envelope["source_kind"],
        engine=envelope["engine"],
        status=envelope["status"],
        summary=envelope["summary"],
        evidence=envelope["evidence"],
        citations=envelope["citations"],
        generated_artifacts=envelope["generated_artifacts"],
        coverage=envelope["coverage"],
        error=envelope["error"],
    )

    serialized_envelope = json.dumps(
        bounded_envelope,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    if len(serialized_envelope.encode("utf-8")) > EVIDENCE_ENVELOPE_MAX_BYTES:
        raise ValueError("Evidence envelope exceeds its serialized size bound")
    return serialized_envelope