# functions_document_merge.py
"""Ordered assembly of several PDF, Word, PowerPoint or spreadsheet files into one file.

Version: 0.261.246

The engine is pure: it receives already-authorized byte loaders, never resolves
documents, settings, storage or routes, and performs no model work. Each assembler reads
one source at a time, checks a package's size and refuses XML parts that declare a document
type or aren't UTF-8 or UTF-16 before parsing it, and writes the output to a bounded spooled
file whose size is checked before it is returned; a spool larger than 16 MiB spills into the
container's scratch directory (0.261.245). The same files and options always produce the
same bytes, so a replayed merge reuses its file. CodeQL import-cycle cleanup added in
0.261.246.
"""

from typing import Callable, Optional, Sequence

from functions_document_merge_core import (
    DOCUMENT_MERGE_KINDS,
    DOCUMENT_MERGE_OUTPUTS,
    DOCUMENT_MERGE_REPORT_VERSION,
    DOCUMENT_MERGE_SOURCE_EXTENSIONS,
    DocumentMergeCancelled,
    DocumentMergeError,
    DocumentMergeLimits,
    DocumentMergeOptions,
    DocumentMergePart,
    DocumentMergeResult,
    FORMATTING_KEEP_SOURCE,
    FORMATTING_USE_FIRST,
    MERGE_KIND_DOCX,
    MERGE_KIND_PDF,
    MERGE_KIND_PPTX,
    MERGE_KIND_WORKBOOK,
    MergeContext,
    WORKBOOK_SHEETS_ALL,
    WORKBOOK_SHEETS_FIRST,
)


def merge_documents(
    kind,
    parts: Sequence[DocumentMergePart],
    *,
    options: Optional[DocumentMergeOptions] = None,
    limits: Optional[DocumentMergeLimits] = None,
    cancel_requested: Optional[Callable[[], bool]] = None,
    on_progress: Optional[Callable[[dict], None]] = None,
    min_parts: int = 2,
) -> DocumentMergeResult:
    """Assemble the parts, in order, into one file of the given kind.

    ``min_parts`` is 1 only for a scheduled merge of whatever files arrived, which may be one.
    """
    if kind not in DOCUMENT_MERGE_KINDS:
        raise DocumentMergeError("unsupported_format", "This kind of file can't be merged.")
    if min_parts not in (1, 2):
        raise ValueError("min_parts must be 1 or 2.")
    options = options or DocumentMergeOptions()
    limits = limits or DocumentMergeLimits()
    parts = list(parts or ())
    _validate_parts(kind, parts, limits, min_parts)
    context = MergeContext(kind, parts, options, limits, cancel_requested, on_progress)
    # Each assembler loads only when its kind is merged; the Office stacks are large.
    if kind == MERGE_KIND_PDF:
        from functions_document_merge_pdf import assemble_pdf as assemble
    elif kind == MERGE_KIND_DOCX:
        from functions_document_merge_docx import assemble_docx as assemble
    elif kind == MERGE_KIND_PPTX:
        from functions_document_merge_pptx import assemble_pptx as assemble
    else:
        from functions_document_merge_workbook import assemble_workbook as assemble
    try:
        return assemble(context)
    except DocumentMergeError as error:
        context.report["status"] = "failed"
        if error.report is None:
            error.report = context.report
        raise


def _validate_parts(kind, parts, limits, min_parts=2):
    if len(parts) < min_parts:
        raise DocumentMergeError("too_few_sources", "Merging needs at least two files.")
    if len(parts) > limits.max_parts:
        raise DocumentMergeError(
            "too_many_sources", f"{len(parts)} files were selected; at most {limits.max_parts} can be merged here.",
        )
    allowed = DOCUMENT_MERGE_SOURCE_EXTENSIONS[kind]
    seen = set()
    for part in parts:
        if not isinstance(part, DocumentMergePart):
            raise DocumentMergeError("invalid_source", "Each merge source must be a DocumentMergePart.")
        if not isinstance(part.source_id, str) or not part.source_id.strip():
            raise DocumentMergeError("invalid_source", "Each merge source needs an identifier.")
        if part.source_id in seen:
            raise DocumentMergeError("duplicate_source", "The same file was selected more than once.")
        seen.add(part.source_id)
        if not callable(part.load_bytes):
            raise DocumentMergeError("invalid_source", "Each merge source needs a byte loader.")
        if part.resolved_extension() not in allowed:
            raise DocumentMergeError(
                "unsupported_format",
                f"{part.display_name()} can't be merged into a {kind.upper() if kind != MERGE_KIND_WORKBOOK else 'workbook'} "
                f"file. Allowed: {', '.join(allowed)}.",
            )
        if part.pages is not None and kind not in (MERGE_KIND_PDF, MERGE_KIND_PPTX):
            raise DocumentMergeError("range_invalid", "Page ranges apply only to PDF and PowerPoint merges.")


def document_merge_kind_for_extension(extension):
    """The merge kinds a file extension can take part in."""
    extension = str(extension or "").strip().lower()
    if extension and not extension.startswith("."):
        extension = f".{extension}"
    return tuple(kind for kind in DOCUMENT_MERGE_KINDS if extension in DOCUMENT_MERGE_SOURCE_EXTENSIONS[kind])


__all__ = [
    "DOCUMENT_MERGE_KINDS",
    "DOCUMENT_MERGE_OUTPUTS",
    "DOCUMENT_MERGE_REPORT_VERSION",
    "DOCUMENT_MERGE_SOURCE_EXTENSIONS",
    "DocumentMergeCancelled",
    "DocumentMergeError",
    "DocumentMergeLimits",
    "DocumentMergeOptions",
    "DocumentMergePart",
    "DocumentMergeResult",
    "FORMATTING_KEEP_SOURCE",
    "FORMATTING_USE_FIRST",
    "MERGE_KIND_DOCX",
    "MERGE_KIND_PDF",
    "MERGE_KIND_PPTX",
    "MERGE_KIND_WORKBOOK",
    "WORKBOOK_SHEETS_ALL",
    "WORKBOOK_SHEETS_FIRST",
    "document_merge_kind_for_extension",
    "merge_documents",
]
