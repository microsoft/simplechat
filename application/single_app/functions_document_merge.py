# functions_document_merge.py
"""Ordered assembly of several PDF, Word or spreadsheet files into one file.

Version: 0.261.222

The engine is pure: it receives already-authorized byte loaders, never resolves
documents, settings, storage or routes, and performs no model work. Each assembler reads
one source at a time, checks a package's size before parsing it, and writes the output to
a bounded spooled file whose size is checked before it is returned. The same files and
options always produce the same bytes, so a replayed merge reuses its file.
"""

from dataclasses import dataclass, field
import io
import os
import tempfile
from typing import Callable, Optional, Sequence, Tuple
import zipfile


DOCUMENT_MERGE_REPORT_VERSION = "document-merge-report-v1"

MERGE_KIND_PDF = "pdf"
MERGE_KIND_DOCX = "docx"
MERGE_KIND_PPTX = "pptx"
MERGE_KIND_WORKBOOK = "workbook"
# The kinds that have an assembler. PowerPoint joins with its assembler.
DOCUMENT_MERGE_KINDS = (MERGE_KIND_PDF, MERGE_KIND_DOCX, MERGE_KIND_WORKBOOK)

DOCUMENT_MERGE_SOURCE_EXTENSIONS = {
    MERGE_KIND_PDF: (".pdf",),
    MERGE_KIND_DOCX: (".docx",),
    MERGE_KIND_PPTX: (".pptx",),
    MERGE_KIND_WORKBOOK: (".xlsx", ".xlsm", ".xls", ".csv"),
}
DOCUMENT_MERGE_OUTPUTS = {
    MERGE_KIND_PDF: (".pdf", "application/pdf"),
    MERGE_KIND_DOCX: (".docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    MERGE_KIND_PPTX: (".pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
    MERGE_KIND_WORKBOOK: (".xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
}

FORMATTING_KEEP_SOURCE = "keep_source"
FORMATTING_USE_FIRST = "use_first"
DOCUMENT_MERGE_FORMATTING = (FORMATTING_KEEP_SOURCE, FORMATTING_USE_FIRST)

WORKBOOK_SHEETS_FIRST = "first"
WORKBOOK_SHEETS_ALL = "all"
WORKBOOK_SHEET_MODES = (WORKBOOK_SHEETS_FIRST, WORKBOOK_SHEETS_ALL)

PART_STATUS_MERGED = "merged"
PART_STATUS_NOT_PROCESSED = "not_processed"

MAX_PAGE_RANGES = 64
_SPOOL_MEMORY_BYTES = 16 * 1024 * 1024
_COPY_CHUNK_BYTES = 64 * 1024
_PACKAGE_DATE_TIME = (2000, 1, 1, 0, 0, 0)
_ZIP_MAGIC = b"PK\x03\x04"
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_MIB = 1024 * 1024


class DocumentMergeError(ValueError):
    """A safe, user-presentable merge failure with a stable code."""

    def __init__(self, code, message, *, report=None, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.report = report
        self.details = dict(details or {})


class DocumentMergeCancelled(DocumentMergeError):
    """The caller asked the merge to stop."""

    def __init__(self):
        super().__init__("cancelled", "The merge was cancelled.")


@dataclass(frozen=True)
class DocumentMergePart:
    """One authorized source and, for PDFs and decks, the 1-based inclusive ranges to keep."""

    source_id: str
    file_name: str
    load_bytes: Callable[[], bytes] = field(repr=False)
    extension: str = ""
    pages: Optional[Tuple[Tuple[int, int], ...]] = None

    def resolved_extension(self):
        extension = (self.extension or os.path.splitext(self.file_name or "")[1]).strip().lower()
        if extension and not extension.startswith("."):
            extension = f".{extension}"
        return extension

    def display_name(self):
        return str(self.file_name or "").strip() or "A selected file"


@dataclass(frozen=True)
class DocumentMergeOptions:
    """Per-kind presentation choices; options a kind does not use are ignored."""

    formatting: str = FORMATTING_KEEP_SOURCE
    bookmarks: bool = True
    sections: bool = True
    page_breaks: bool = True
    source_headings: bool = False
    sheets: str = WORKBOOK_SHEETS_FIRST
    sheet: Optional[str] = None

    def __post_init__(self):
        if self.formatting not in DOCUMENT_MERGE_FORMATTING:
            raise DocumentMergeError("invalid_options", "Formatting must be keep_source or use_first.")
        if self.sheets not in WORKBOOK_SHEET_MODES:
            raise DocumentMergeError("invalid_options", "Sheets must be first or all.")
        for name in ("bookmarks", "sections", "page_breaks", "source_headings"):
            if type(getattr(self, name)) is not bool:
                raise DocumentMergeError("invalid_options", f"{name} must be true or false.")
        if self.sheet is not None and (not isinstance(self.sheet, str) or not self.sheet.strip() or len(self.sheet) > 31):
            raise DocumentMergeError("invalid_options", "A sheet name must be 1 to 31 characters.")


@dataclass(frozen=True)
class DocumentMergeLimits:
    """Bounds for one merge; every value must be a positive integer."""

    max_parts: int = 10
    max_source_bytes: int = 100 * _MIB
    max_total_input_bytes: int = 300 * _MIB
    max_output_bytes: int = 100 * _MIB
    max_pages: int = 2000
    max_slides: int = 1000
    max_sheets: int = 100
    max_sheet_rows: int = 1_048_576
    max_total_cells: int = 10_000_000
    max_package_uncompressed_bytes: int = 1024 * _MIB
    max_package_entries: int = 50_000

    def __post_init__(self):
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer.")
        if self.max_parts < 2:
            raise ValueError("max_parts must allow at least two parts.")


class DocumentMergeResult:
    """The assembled file, its metadata and the merge report. Close it when done."""

    def __init__(self, kind, spool, size_bytes, report):
        self.kind = kind
        self.file_extension, self.media_type = DOCUMENT_MERGE_OUTPUTS[kind]
        self._spool = spool
        self.size_bytes = size_bytes
        self.report = report

    def read_bytes(self):
        self._spool.seek(0)
        return self._spool.read()

    def open_stream(self):
        """The assembled file as a seekable stream at its start; it closes with the result."""
        self._spool.seek(0)
        return self._spool

    def iter_chunks(self, chunk_size=1024 * 1024):
        self._spool.seek(0)
        while True:
            chunk = self._spool.read(chunk_size)
            if not chunk:
                return
            yield chunk

    def close(self):
        self._spool.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()
        return False


class MergeContext:
    """Shared state for one assembler run: limits, report, cancellation and byte budget."""

    def __init__(self, kind, parts, options, limits, cancel_requested, on_progress):
        self.kind = kind
        self.parts = parts
        self.options = options
        self.limits = limits
        self._cancel_requested = cancel_requested
        self._on_progress = on_progress
        self._callback_error = None
        self.input_bytes = 0
        self.report = {
            "version": DOCUMENT_MERGE_REPORT_VERSION,
            "kind": kind,
            "status": "running",
            "options": _option_summary(kind, options),
            "parts": [_new_part_entry(part) for part in parts],
            "totals": {"parts": len(parts), "pages": 0, "slides": 0, "sheets": 0, "bytes": 0},
            "warnings": [],
            "limitations": [],
        }

    def check_cancel(self):
        if self._cancel_requested is None:
            return
        try:
            requested = self._cancel_requested()
        except Exception as exc:
            # Remembered so an assembler never reports the caller's own failure as a bad file.
            self._callback_error = exc
            raise
        if requested:
            raise DocumentMergeCancelled()

    def blames_file(self, error):
        """Whether an unexpected error inside an assembler may be reported as a problem with a file.

        A failing cancellation check and storage errors, such as a full temporary disk, come from
        the caller or the host, so they pass through unchanged and the caller can retry.
        """
        return error is not self._callback_error and not isinstance(error, OSError)

    def load(self, index):
        """Read one part's bytes within the per-file and total input budgets."""
        self.check_cancel()
        part = self.parts[index]
        content = part.load_bytes()
        if isinstance(content, bytearray):
            content = bytes(content)
        if not isinstance(content, bytes):
            raise DocumentMergeError("source_unavailable", f"{part.display_name()} could not be read.")
        if len(content) > self.limits.max_source_bytes:
            raise DocumentMergeError(
                "source_too_large",
                f"{part.display_name()} is larger than the {self.limits.max_source_bytes // _MIB} MB merge limit.",
            )
        self.input_bytes += len(content)
        if self.input_bytes > self.limits.max_total_input_bytes:
            raise DocumentMergeError("input_too_large", "The selected files are too large to merge together.")
        return content

    def part_entry(self, index):
        return self.report["parts"][index]

    def warn(self, code, message, index=None):
        target = self.report["warnings"] if index is None else self.report["parts"][index]["warnings"]
        warning = {"code": code, "message": message}
        if warning not in target:
            target.append(warning)

    def limit(self, message):
        if message not in self.report["limitations"]:
            self.report["limitations"].append(message)

    def progress(self, index):
        entry = self.report["parts"][index]
        entry["status"] = PART_STATUS_MERGED
        if self._on_progress is not None:
            self._on_progress({
                "index": index + 1, "total": len(self.parts), "file_name": entry["file_name"],
                "pages": entry.get("pages", 0), "slides": entry.get("slides", 0), "sheets": entry.get("sheets", 0),
            })


def _option_summary(kind, options):
    if kind == MERGE_KIND_PDF:
        return {"bookmarks": options.bookmarks}
    if kind == MERGE_KIND_DOCX:
        return {
            "formatting": options.formatting, "page_breaks": options.page_breaks,
            "source_headings": options.source_headings,
        }
    if kind == MERGE_KIND_PPTX:
        return {"formatting": options.formatting, "sections": options.sections}
    return {"sheets": options.sheets, "sheet": options.sheet}


def _new_part_entry(part):
    entry = {
        "source_id": part.source_id,
        "file_name": part.display_name(),
        "status": PART_STATUS_NOT_PROCESSED,
        "warnings": [],
    }
    if part.pages:
        entry["ranges"] = [list(item) for item in part.pages]
    return entry


def new_output_spool():
    return tempfile.SpooledTemporaryFile(max_size=_SPOOL_MEMORY_BYTES, mode="w+b")


def normalized_package(package, context):
    """Copy a written Office package into a new spool with fixed ZIP dates and attributes.

    Office writers stamp the current time into every entry, so without this the same files
    merged twice would differ and a replayed workflow would attach a second copy.
    """
    package.seek(0)
    spool = new_output_spool()
    try:
        with zipfile.ZipFile(package, "r") as source, zipfile.ZipFile(
            spool, "w", zipfile.ZIP_DEFLATED, allowZip64=True,
        ) as target:
            for entry in source.infolist():
                context.check_cancel()
                info = zipfile.ZipInfo(entry.filename, date_time=_PACKAGE_DATE_TIME)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 0
                # A known size lets zipfile add ZIP64 fields only to entries that need them.
                info.file_size = entry.file_size
                with source.open(entry) as reader, target.open(info, "w") as writer:
                    while chunk := reader.read(_COPY_CHUNK_BYTES):
                        writer.write(chunk)
    except BaseException:
        spool.close()
        raise
    return spool


def finish_output(context, spool):
    """Check the written size and return the merge result."""
    spool.flush()
    size = spool.seek(0, io.SEEK_END)
    if size > context.limits.max_output_bytes:
        spool.close()
        raise DocumentMergeError(
            "output_too_large",
            f"The merged file would be larger than {context.limits.max_output_bytes // _MIB} MB.",
        )
    spool.seek(0)
    context.report["status"] = "merged"
    context.report["totals"]["bytes"] = size
    return DocumentMergeResult(context.kind, spool, size, context.report)


def selected_indices(part, total, unit):
    """0-based indices for a part's 1-based inclusive ranges; every page or slide when None."""
    if not part.pages:
        return list(range(total))
    if len(part.pages) > MAX_PAGE_RANGES:
        raise DocumentMergeError("range_invalid", f"Too many {unit} ranges were requested for {part.display_name()}.")
    indices = []
    for item in part.pages:
        if (
            not isinstance(item, (tuple, list)) or len(item) != 2
            or any(type(value) is not int for value in item)
            or item[0] < 1 or item[1] < item[0] or item[1] > total
        ):
            raise DocumentMergeError(
                "range_invalid",
                f"A requested {unit} range is outside {part.display_name()}, which has {total} {unit}s.",
            )
        indices.extend(range(item[0] - 1, item[1]))
    if len(set(indices)) != len(indices):
        raise DocumentMergeError("range_invalid", f"Each {unit} of {part.display_name()} can be included only once.")
    return indices


def guard_ooxml_package(content, part, limits, label):
    """Refuse encrypted, damaged or oversized Office Open XML packages before parsing."""
    if content[:8] == _OLE_MAGIC:
        raise DocumentMergeError(
            "encrypted_document",
            f"{part.display_name()} is password-protected or encrypted, so it can't be merged.",
        )
    if content[:4] != _ZIP_MAGIC:
        raise DocumentMergeError("unreadable_document", f"{part.display_name()} isn't a valid {label}.")
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
    except zipfile.BadZipFile as exc:
        raise DocumentMergeError("unreadable_document", f"{part.display_name()} isn't a valid {label}.") from exc
    if len(entries) > limits.max_package_entries:
        raise DocumentMergeError("source_too_large", f"{part.display_name()} has too many internal parts to merge.")
    if sum(entry.file_size for entry in entries) > limits.max_package_uncompressed_bytes:
        raise DocumentMergeError("source_too_large", f"{part.display_name()} is too large to merge once uncompressed.")
    names = {entry.filename for entry in entries}
    return names


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
