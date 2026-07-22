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
MIXED_SOURCE_HANDOFF_MAX_BYTES = 49152
MIXED_SOURCE_HANDOFF_MAX_ENVELOPES = 20


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


def normalize_document_context_request(
    selection_mode=None,
    selected_document_ids=None,
    document_context_requested=None,
    hybrid_search=False,
):
    """Validate the Phase 2 request contract and derive effective context intent."""
    normalized_document_ids = []
    seen_document_ids = set()
    for document_id in _normalize_identifier_list(selected_document_ids):
        if document_id == "all" or document_id in seen_document_ids:
            continue
        seen_document_ids.add(document_id)
        normalized_document_ids.append(document_id)

    normalized_hybrid_search = _normalize_boolean(
        hybrid_search,
        field_name="hybrid_search",
    )
    normalized_context_requested = _normalize_optional_boolean(
        document_context_requested,
        field_name="document_context_requested",
    )
    has_explicit_selection_mode = str(selection_mode or "").strip() != ""

    if normalized_document_ids:
        normalized_selection_mode = normalize_selection_mode(
            selection_mode,
            default=SELECTION_MODE_SELECTED,
        )
        if normalized_selection_mode != SELECTION_MODE_SELECTED:
            raise ValueError(
                "selection_mode must be selected when selected_document_ids are provided"
            )
        normalized_context_requested = True
    elif has_explicit_selection_mode:
        normalized_selection_mode = normalize_selection_mode(selection_mode)
        if normalized_selection_mode == SELECTION_MODE_SELECTED:
            raise ValueError(
                "selection_mode selected requires at least one selected_document_id"
            )
        if (
            normalized_selection_mode in {SELECTION_MODE_ALL, SELECTION_MODE_RELEVANCE}
            and normalized_context_requested is None
        ):
            normalized_context_requested = True
    elif normalized_context_requested is True or normalized_hybrid_search:
        normalized_selection_mode = SELECTION_MODE_RELEVANCE
        normalized_context_requested = True
    else:
        normalized_selection_mode = None
        normalized_context_requested = False

    return {
        "selection_mode": normalized_selection_mode,
        "selected_document_ids": normalized_document_ids,
        "document_context_requested": bool(normalized_context_requested),
        "hybrid_search": normalized_hybrid_search,
        "explicit_selection": bool(normalized_document_ids),
    }


def should_run_tabular_evidence(user_question, has_narrative_sources=False):
    """Return whether a mixed-source question needs tabular data or schema evidence."""
    normalized_question = " ".join(str(user_question or "").strip().lower().split())
    if not normalized_question:
        return True

    tabular_markers = (
        "calculate", "calculation", "count", "average", "mean", "median",
        "minimum", "maximum", "total", "sum", "percentage", "percent",
        "rows", "columns", "spreadsheet", "workbook", "worksheet", "sheet",
        "csv", "xlsx", "xls", "table", "tabular", "data set", "dataset",
        "trend", "group by", "how many", "highest", "lowest",
    )
    collective_markers = (
        "both files", "both documents", "all files", "all documents",
        "all selected", "each file", "each document", "each source",
        "across the files", "across the documents", "across the sources",
        "mixed sources",
    )
    narrative_markers = (
        "pdf", "docx", "word document", "presentation", "powerpoint",
        "paragraph", "section", "policy", "procedure", "contract",
        "agreement", "memo", "letter", "narrative", "prose", "report",
    )

    if any(marker in normalized_question for marker in tabular_markers):
        return True
    if any(marker in normalized_question for marker in collective_markers):
        return True
    if has_narrative_sources and any(
        marker in normalized_question for marker in narrative_markers
    ):
        return False
    if normalized_question in {"summarize", "summary", "summarize the selected sources"}:
        return True
    if has_narrative_sources:
        return False
    return True


def build_tabular_file_contexts_from_manifest(tabular_sources):
    """Build canonical per-file contexts for the existing tabular runner."""
    contexts = []
    seen_source_identities = set()
    for raw_source in list(tabular_sources or []):
        source = raw_source if isinstance(raw_source, dict) else {}
        if (
            source.get("authorization_status") != AUTHORIZATION_STATUS_AUTHORIZED
            or source.get("source_kind") != SOURCE_KIND_TABULAR
        ):
            continue

        document_id = str(source.get("document_id") or "").strip()
        file_name = str(source.get("file_name") or "").strip()
        scope = str(source.get("scope") or "").strip().lower()
        if not document_id or not file_name or scope not in SOURCE_SCOPES:
            continue
        source_hint = "workspace" if scope == SOURCE_SCOPE_PERSONAL else scope
        source_identity = (
            document_id,
            source_hint,
            str(source.get("scope_id") or "").strip(),
        )
        if source_identity in seen_source_identities:
            continue
        seen_source_identities.add(source_identity)
        contexts.append({
            "document_id": document_id,
            "file_name": file_name,
            "source_hint": source_hint,
            "group_id": source.get("group_id"),
            "public_workspace_id": source.get("public_workspace_id"),
            "conversation_id": source.get("conversation_id"),
            "storage_locator": dict(source.get("storage_locator") or {}),
        })
    return contexts


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


def _normalize_boolean(value, field_name):
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return False
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized_value = value.strip().lower()
        if normalized_value in {"true", "1"}:
            return True
        if normalized_value in {"false", "0"}:
            return False
    raise ValueError(f"{field_name} must be a boolean")


def _normalize_optional_boolean(value, field_name):
    if value is None or value == "":
        return None
    return _normalize_boolean(value, field_name=field_name)


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
        "storage_locator": None,
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
        if scope_id != str(user_id or "").strip() and not any(
            str(shared_entry or "").strip() == f"{user_id},approved"
            for shared_entry in document_item.get("shared_user_ids", []) or []
        ):
            return _unresolved_manifest_entry(document_id)
    elif scope == SOURCE_SCOPE_GROUP:
        group_id = str(document_context.get("group_id") or "").strip() or None
        scope_id = group_id
        document_group_id = str(document_item.get("group_id") or "").strip()
        if document_group_id != group_id and not any(
            str(shared_entry or "").strip() == f"{group_id},approved"
            for shared_entry in document_item.get("shared_group_ids", []) or []
        ):
            return _unresolved_manifest_entry(document_id)
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

    storage_locator = None
    if scope != SOURCE_SCOPE_CHAT:
        try:
            from functions_documents import get_document_blob_storage_info

            blob_container, blob_path = get_document_blob_storage_info(
                document_item,
                user_id=(
                    document_item.get("user_id")
                    if scope == SOURCE_SCOPE_PERSONAL
                    else None
                ),
                group_id=(
                    document_item.get("group_id")
                    if scope == SOURCE_SCOPE_GROUP
                    else None
                ),
                public_workspace_id=(
                    document_item.get("public_workspace_id")
                    if scope == SOURCE_SCOPE_PUBLIC
                    else None
                ),
            )
            if blob_container and blob_path:
                storage_locator = {
                    "container": str(blob_container),
                    "blob_path": str(blob_path),
                }
        except Exception:
            storage_locator = None

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
        "storage_locator": storage_locator,
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
    doc_scope="all",
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
    normalized_doc_scope = str(doc_scope or "all").strip().lower()
    if normalized_doc_scope not in {"all", "personal", "group", "public"}:
        raise ValueError("doc_scope must be all, personal, group, or public")

    resolved_contexts = None
    if context_resolver is None:
        try:
            resolved_contexts = _default_document_context_batch_resolver(
                document_ids=unique_document_ids,
                user_id=normalized_user_id,
                doc_scope=normalized_doc_scope,
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
                    doc_scope=normalized_doc_scope,
                    active_group_ids=normalized_active_group_ids,
                    active_public_workspace_id=normalized_public_workspace_ids,
                    conversation_id=normalized_conversation_id,
                )
            except Exception:
                resolution_error_count += 1
        if (
            isinstance(document_context, dict)
            and normalized_doc_scope != "all"
            and str(document_context.get("scope") or "").strip().lower()
            != normalized_doc_scope
        ):
            document_context = None
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


def build_narrative_evidence_envelopes(
    narrative_sources,
    search_results,
    selection_mode,
):
    """Normalize bounded narrative search results into one envelope per source."""
    normalized_selection_mode = normalize_selection_mode(
        selection_mode,
        default=SELECTION_MODE_RELEVANCE,
    )
    results_by_document_id = {}
    for raw_result in list(search_results or []):
        result = raw_result if isinstance(raw_result, dict) else {}
        document_id = str(result.get("document_id") or "").strip()
        if not document_id:
            continue
        results_by_document_id.setdefault(document_id, []).append(result)

    envelopes = []
    for source in list(narrative_sources or []):
        source = source if isinstance(source, dict) else {}
        document_id = str(source.get("document_id") or "").strip()
        if not document_id:
            continue
        source_results = results_by_document_id.get(document_id, [])
        evidence = []
        citations = []
        for result in source_results:
            evidence.append({
                "chunk_text": result.get("chunk_text"),
                "page_number": result.get("page_number"),
                "chunk_sequence": result.get("chunk_sequence"),
                "score": result.get("score"),
            })
            citations.append({
                "citation_id": result.get("id") or result.get("chunk_id"),
                "page_number": result.get("page_number"),
                "chunk_sequence": result.get("chunk_sequence"),
            })

        result_count = len(source_results)
        envelopes.append(build_evidence_envelope(
            document_id=document_id,
            source_kind=SOURCE_KIND_NARRATIVE,
            engine=EVIDENCE_ENGINE_HYBRID_SEARCH,
            status=(
                EVIDENCE_STATUS_COMPLETED
                if result_count
                else EVIDENCE_STATUS_PARTIAL
            ),
            summary=(
                f"Retrieved {result_count} bounded narrative excerpt(s)."
                if result_count
                else "No relevant narrative excerpts were returned."
            ),
            evidence=evidence,
            citations=citations,
            coverage={
                "selection_mode": normalized_selection_mode,
                "terminal": True,
                "result_count": result_count,
            },
            error=(
                None
                if result_count
                else "Narrative retrieval returned no relevant excerpts."
            ),
        ))
    return envelopes


def execute_tabular_evidence_sources(
    tabular_sources,
    execute_source,
    selection_mode,
    execute=True,
):
    """Execute the existing tabular runner once per source and require terminal coverage."""
    normalized_selection_mode = normalize_selection_mode(
        selection_mode,
        default=SELECTION_MODE_RELEVANCE,
    )
    if execute and not callable(execute_source):
        raise TypeError("execute_source must be callable")

    envelopes = []
    completed_count = 0
    failed_count = 0
    skipped_count = 0
    for raw_source in list(tabular_sources or []):
        source = raw_source if isinstance(raw_source, dict) else {}
        document_id = str(source.get("document_id") or "").strip()
        if not document_id:
            continue

        if not execute:
            skipped_count += 1
            envelopes.append(build_evidence_envelope(
                document_id=document_id,
                source_kind=SOURCE_KIND_TABULAR,
                engine=EVIDENCE_ENGINE_TABULAR_TOOLS,
                status=EVIDENCE_STATUS_SKIPPED,
                summary="Tabular processing was not needed for this narrative-only request.",
                coverage={
                    "selection_mode": normalized_selection_mode,
                    "terminal": True,
                    "reason": "narrative_only_request",
                },
            ))
            continue

        try:
            raw_result = execute_source(source)
            result = raw_result if isinstance(raw_result, dict) else {}
            summary = str(result.get("summary") or "").strip()
            if not summary:
                raise ValueError("Tabular execution returned no bounded summary")
            completed_count += 1
            envelopes.append(build_evidence_envelope(
                document_id=document_id,
                source_kind=SOURCE_KIND_TABULAR,
                engine=EVIDENCE_ENGINE_TABULAR_TOOLS,
                status=EVIDENCE_STATUS_COMPLETED,
                summary=summary,
                evidence=result.get("evidence"),
                citations=result.get("citations"),
                generated_artifacts=result.get("generated_artifacts"),
                coverage={
                    "selection_mode": normalized_selection_mode,
                    "terminal": True,
                    **dict(result.get("coverage") or {}),
                },
            ))
        except Exception:
            failed_count += 1
            envelopes.append(build_evidence_envelope(
                document_id=document_id,
                source_kind=SOURCE_KIND_TABULAR,
                engine=EVIDENCE_ENGINE_TABULAR_TOOLS,
                status=EVIDENCE_STATUS_FAILED,
                summary="Tabular evidence could not be completed for this source.",
                coverage={
                    "selection_mode": normalized_selection_mode,
                    "terminal": True,
                },
                error="Tabular evidence could not be completed.",
            ))

    log_event(
        "[MixedSourceChatSearch] Tabular source execution reached terminal coverage.",
        extra={
            "selection_mode": normalized_selection_mode,
            "tabular_candidate_count": len(list(tabular_sources or [])),
            "tabular_completed_count": completed_count,
            "tabular_failed_count": failed_count,
            "tabular_skipped_count": skipped_count,
        },
        level=logging.INFO,
    )
    return envelopes


def build_mixed_source_evidence_handoff(
    manifest,
    evidence_envelopes,
    selection_mode,
):
    """Build one bounded synthesis handoff from Phase 1 evidence envelopes."""
    normalized_selection_mode = normalize_selection_mode(
        selection_mode,
        default=SELECTION_MODE_RELEVANCE,
    )
    manifest_entries = [entry for entry in list(manifest or []) if isinstance(entry, dict)]
    all_envelopes = [
        envelope
        for envelope in list(evidence_envelopes or [])
        if isinstance(envelope, dict)
    ]
    envelopes = all_envelopes[:MIXED_SOURCE_HANDOFF_MAX_ENVELOPES]
    envelope_by_document_id = {
        str(envelope.get("document_id") or "").strip(): envelope
        for envelope in all_envelopes
        if str(envelope.get("document_id") or "").strip()
    }
    evidence_omitted_count = max(0, len(all_envelopes) - len(envelopes))

    source_coverage = []
    failed_count = 0
    partial_count = 0
    skipped_count = 0
    completed_count = 0
    for source_index, entry in enumerate(manifest_entries, start=1):
        document_id = str(entry.get("document_id") or "").strip()
        envelope = envelope_by_document_id.get(document_id)
        if entry.get("authorization_status") != AUTHORIZATION_STATUS_AUTHORIZED:
            status = EVIDENCE_STATUS_FAILED
            source_label = f"Unavailable selected source {source_index}"
        elif entry.get("source_kind") == SOURCE_KIND_UNSUPPORTED:
            status = EVIDENCE_STATUS_FAILED
            source_label = str(entry.get("display_name") or f"Unsupported source {source_index}")
        elif envelope:
            status = envelope.get("status") or EVIDENCE_STATUS_FAILED
            source_label = str(entry.get("display_name") or f"Source {source_index}")
        else:
            status = EVIDENCE_STATUS_FAILED
            source_label = str(entry.get("display_name") or f"Source {source_index}")

        if status == EVIDENCE_STATUS_COMPLETED:
            completed_count += 1
        elif status == EVIDENCE_STATUS_PARTIAL:
            partial_count += 1
        elif status == EVIDENCE_STATUS_SKIPPED:
            skipped_count += 1
        else:
            failed_count += 1
        source_coverage.append({
            "source": _truncate_utf8(source_label, 128),
            "source_kind": entry.get("source_kind"),
            "status": status,
        })

    coverage = {
        "selection_mode": normalized_selection_mode,
        "requested_source_count": len(manifest_entries),
        "completed_source_count": completed_count,
        "partial_source_count": partial_count,
        "failed_source_count": failed_count,
        "skipped_source_count": skipped_count,
        "partial_coverage": bool(
            failed_count or partial_count or evidence_omitted_count
        ),
        "evidence_omitted_count": evidence_omitted_count,
        "sources": source_coverage,
    }
    payload = {
        "coverage": coverage,
        "evidence_envelopes": envelopes,
    }
    serialized_payload = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    if len(serialized_payload.encode("utf-8")) > MIXED_SOURCE_HANDOFF_MAX_BYTES:
        payload["evidence_envelopes"] = [
            {
                "document_id": envelope.get("document_id"),
                "source_kind": envelope.get("source_kind"),
                "engine": envelope.get("engine"),
                "status": envelope.get("status"),
                "summary": _truncate_utf8(envelope.get("summary"), 512),
                "coverage": {
                    "selection_mode": (envelope.get("coverage") or {}).get("selection_mode"),
                    "terminal": bool((envelope.get("coverage") or {}).get("terminal")),
                    "result_count": (envelope.get("coverage") or {}).get("result_count"),
                    "tool_call_count": (envelope.get("coverage") or {}).get("tool_call_count"),
                },
            }
            for envelope in envelopes
        ]
        payload["coverage"]["handoff_compacted"] = True
        payload["coverage"]["partial_coverage"] = True
        payload["coverage"]["evidence_compacted_count"] = len(envelopes)
        serialized_payload = json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    if len(serialized_payload.encode("utf-8")) > MIXED_SOURCE_HANDOFF_MAX_BYTES:
        raise ValueError("Mixed-source evidence handoff exceeds its size bound")

    partial_coverage_instruction = (
        "State clearly that source coverage was partial and identify unavailable authorized source labels."
        if coverage["partial_coverage"]
        else "Do not claim that selected sources were omitted."
    )
    return {
        "role": "system",
        "content": (
            "Use the mixed-source evidence handoff below with the other bounded narrative excerpts "
            "and computed tabular results. Synthesize one answer. Preserve narrative source citations "
            "and tabular tool citations; do not convert computed table facts into unsupported narrative claims. "
            "When selection_mode is selected, current selected-source evidence supersedes prior document "
            "grounding; do not use prior source claims to fill missing current coverage. "
            f"{partial_coverage_instruction}\n\n{serialized_payload}"
        ),
        "mixed_source_coverage": coverage,
    }