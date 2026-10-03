# functions_orchestration_document_merge.py
"""Deterministic document merging for Gather / Reason / Render orchestration.

Version: 0.261.224
Implemented in: 0.261.224

``document_merge`` is a Reason capability. Its adapter in ``functions_orchestration_adapters``
authorizes the sources; this module reads each original file through the screening-aware
byte reader, assembles them once with ``functions_document_merge`` to check them and to
measure the result, and retains a description of the merge and its report. It creates no
file and calls no model: ``render_file`` assembles the same files again with the
``assembled_document_v1`` profile and delivers the file only when it is byte-identical.
"""

from copy import deepcopy
import hashlib
import os

from functions_analysis_access import analysis_source_snapshot
from functions_document_actions import (
    DOCUMENT_ACTION_CONTEXT_CHAT,
    DOCUMENT_ACTION_TYPE_MERGE,
    get_document_action_max_documents,
)
from functions_document_merge import (
    DOCUMENT_MERGE_SOURCE_EXTENSIONS,
    DocumentMergeError,
    DocumentMergeLimits,
    MERGE_KIND_DOCX,
    MERGE_KIND_PDF,
    MERGE_KIND_PPTX,
    MERGE_KIND_WORKBOOK,
)
from functions_document_merge_assembly import build_document_assembly, document_merge_options_from_arguments
from functions_mixed_source_orchestration import AUTHORIZATION_STATUS_AUTHORIZED
from functions_orchestration_result_contracts import Completeness, Coverage, ResultContractError
from functions_orchestration_results import NamedOutput


DOCUMENT_MERGE_CAPABILITY_ID = "document_merge"
DOCUMENT_MERGE_KINDS = (MERGE_KIND_PDF, MERGE_KIND_DOCX, MERGE_KIND_PPTX, MERGE_KIND_WORKBOOK)
DOCUMENT_MERGE_CHECKS = (
    "authorized_source_snapshots",
    "deterministic_assembly",
    "assembled_output_digest",
)
# Render's own limit for a chat file, so a merge it checked is one Render can deliver.
_MAX_OUTPUT_MEGABYTES = 500
_MIB = 1024 * 1024
_KIND_RESULTS = {
    MERGE_KIND_PDF: ("one PDF", ("pages", "page")),
    MERGE_KIND_DOCX: ("one Word document", None),
    MERGE_KIND_PPTX: ("one PowerPoint deck", ("slides", "slide")),
    MERGE_KIND_WORKBOOK: ("one Excel workbook", ("sheets", "sheet")),
}
# Engine codes become application-owned failure codes; their text never reaches a user.
DOCUMENT_MERGE_FAILURE_CODES = {
    "unsupported_format": "document_merge_sources_invalid",
    "too_few_sources": "document_merge_sources_invalid",
    "duplicate_source": "document_merge_sources_invalid",
    "invalid_source": "document_merge_sources_invalid",
    "encrypted_document": "document_merge_source_unreadable",
    "unreadable_document": "document_merge_source_unreadable",
    "empty_source": "document_merge_source_unreadable",
    "source_unavailable": "document_merge_source_unreadable",
    "active_content": "document_merge_active_content",
    "too_many_sources": "document_merge_limit_exceeded",
    "source_too_large": "document_merge_limit_exceeded",
    "input_too_large": "document_merge_limit_exceeded",
    "output_too_large": "document_merge_limit_exceeded",
    "page_limit_exceeded": "document_merge_limit_exceeded",
    "slide_limit_exceeded": "document_merge_limit_exceeded",
    "sheet_limit_exceeded": "document_merge_limit_exceeded",
    "row_limit_exceeded": "document_merge_limit_exceeded",
    "cell_limit_exceeded": "document_merge_limit_exceeded",
    "cell_too_large": "document_merge_limit_exceeded",
    "sheet_not_found": "merge_sheet_not_found",
    "invalid_options": "merge_options_invalid",
    "range_invalid": "merge_options_invalid",
    "merge_failed": "document_merge_failed",
}


def document_merge_failure_code(error):
    """The application-owned failure code for an engine error, or the generic step failure."""
    return DOCUMENT_MERGE_FAILURE_CODES.get(getattr(error, "code", None), "step_failed")


def document_merge_max_output_bytes(settings):
    """The largest merged file chat delivers, the same limit Render applies."""
    try:
        megabytes = int((settings or {}).get("max_generated_chat_artifact_size_mb", _MAX_OUTPUT_MEGABYTES))
    except (TypeError, ValueError):
        megabytes = _MAX_OUTPUT_MEGABYTES
    return max(1, min(megabytes, _MAX_OUTPUT_MEGABYTES)) * _MIB


def document_merge_limits(settings):
    """The administrator's chat Merge file limit and Render's file size as engine limits."""
    max_parts = get_document_action_max_documents(
        DOCUMENT_ACTION_TYPE_MERGE, DOCUMENT_ACTION_CONTEXT_CHAT, settings=settings,
    )
    return DocumentMergeLimits(
        max_parts=max(2, int(max_parts)), max_output_bytes=document_merge_max_output_bytes(settings),
    )


def require_document_merge_manifest(manifest, document_ids, kind):
    """The authorized manifest in the planned order, with every file one the kind merges."""
    document_ids = list(document_ids or ())
    if (
        not isinstance(manifest, list) or len(document_ids) < 2
        or [source.get("document_id") for source in manifest if isinstance(source, dict)] != document_ids
        or any(source.get("authorization_status") != AUTHORIZATION_STATUS_AUTHORIZED for source in manifest)
    ):
        raise PermissionError("The complete merge source selection is unavailable.")
    allowed = DOCUMENT_MERGE_SOURCE_EXTENSIONS[kind]
    for source in manifest:
        extension = os.path.splitext(str(source.get("file_name") or ""))[1].strip().lower()
        if extension not in allowed:
            raise DocumentMergeError("unsupported_format", "A selected file isn't the kind of file being merged.")
    return manifest


def assembled_file_digest(merge_result):
    """The SHA-256 of an assembled file, read from its bounded spool."""
    digest = hashlib.sha256()
    for chunk in merge_result.iter_chunks():
        digest.update(chunk)
    return digest.hexdigest()


def persist_document_merge_result(
    *, service, producer, kind, options, parts, merge_result, sources, guard_token, input_fingerprint,
):
    """Retain the merge description and its report as one complete Reason result."""
    if producer.capability_id != DOCUMENT_MERGE_CAPABILITY_ID:
        raise ResultContractError("result_merge_invalid")
    snapshots = analysis_source_snapshot(sources)
    coverage = Coverage(len(snapshots), len(snapshots), "sources")
    report = deepcopy(merge_result.report)
    limitations = tuple(report.get("limitations") or ())
    assembly = build_document_assembly(kind, options, parts, merge_result, assembled_file_digest(merge_result))
    outputs = [
        NamedOutput(
            "assembly", "structured-v1", assembly,
            Completeness("complete", 1, 1, coverage, "valid", DOCUMENT_MERGE_CHECKS, limitations),
        ),
        NamedOutput(
            "report", "structured-v1", report,
            Completeness("complete", 1, 1, coverage, "valid", DOCUMENT_MERGE_CHECKS, limitations),
        ),
    ]
    return service.persist_task_result(
        producer=producer, role="reason", status="complete", outputs=outputs,
        sources=snapshots, origin="grounded", guard_token=guard_token, input_fingerprint=input_fingerprint,
    )


def document_merge_step_summary(kind, report):
    """A short, application-owned description of a completed document merge."""
    totals = (report or {}).get("totals") or {}
    merged = sum(entry.get("status") == "merged" for entry in (report or {}).get("parts") or ())
    label, measure = _KIND_RESULTS[kind]
    summary = f"Merged {merged} file(s) into {label}"
    if measure:
        summary += f" with {totals.get(measure[0], 0):,} {measure[1]}(s)"
    return f"{summary}."


__all__ = [
    "DOCUMENT_MERGE_CAPABILITY_ID",
    "DOCUMENT_MERGE_CHECKS",
    "DOCUMENT_MERGE_FAILURE_CODES",
    "DOCUMENT_MERGE_KINDS",
    "document_merge_failure_code",
    "document_merge_limits",
    "document_merge_max_output_bytes",
    "document_merge_options_from_arguments",
    "document_merge_step_summary",
    "persist_document_merge_result",
    "require_document_merge_manifest",
]
