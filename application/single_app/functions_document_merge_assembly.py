# functions_document_merge_assembly.py
"""The retained description of a document merge, and its exact re-assembly for Render.

Version: 0.261.224
Implemented in: 0.261.224

A chat ``document_merge`` step assembles the authorized files once, to check them and
measure the result, and retains this description instead of the bytes: the kind, every
option, the files in order, and the merged file's size and SHA-256. ``render_file`` then
reads the same files again through a reader that the orchestration supplies and that
admits only the files the result was assembled from, assembles them again, and delivers
the file only when it is byte-for-byte the one that was checked. The assemblers are
deterministic, so it is unless a file changed.

This module imports only the merge engine, so the export layer can use it.
"""

import hashlib
import re

from functions_document_merge import (
    DOCUMENT_MERGE_KINDS,
    DOCUMENT_MERGE_OUTPUTS,
    DocumentMergeError,
    DocumentMergeLimits,
    DocumentMergeOptions,
    DocumentMergePart,
    MERGE_KIND_DOCX,
    MERGE_KIND_PDF,
    MERGE_KIND_PPTX,
    MERGE_KIND_WORKBOOK,
    merge_documents,
)


DOCUMENT_ASSEMBLY_PROFILE = "document_assembly_v1"
# The file format each kind creates, as render_file names it.
ASSEMBLED_OUTPUT_FORMATS = {
    MERGE_KIND_PDF: "pdf",
    MERGE_KIND_DOCX: "docx",
    MERGE_KIND_PPTX: "pptx",
    MERGE_KIND_WORKBOOK: "xlsx",
}
ASSEMBLY_OPTION_FIELDS = ("formatting", "bookmarks", "sections", "page_breaks", "source_headings", "sheets", "sheet")
# The options each kind takes; the same as a workflow Merge task's.
ASSEMBLY_KIND_OPTION_FIELDS = {
    MERGE_KIND_PDF: ("bookmarks",),
    MERGE_KIND_DOCX: ("formatting", "page_breaks", "source_headings"),
    MERGE_KIND_PPTX: ("formatting", "sections"),
    MERGE_KIND_WORKBOOK: ("sheets", "sheet"),
}
MAX_ASSEMBLY_PARTS = 1000
_DIGEST = re.compile(r"[a-f0-9]{64}\Z")
_MAX_IDENTIFIER = 256
_MAX_FILE_NAME = 1024


class DocumentAssemblyError(ValueError):
    """A described merge that can't be delivered; the code is an export failure code."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def document_merge_options_from_arguments(arguments):
    """The kind and engine options a merge step asks for; options of another kind are refused."""
    arguments = arguments if isinstance(arguments, dict) else {}
    kind = arguments.get("kind")
    if kind not in ASSEMBLY_KIND_OPTION_FIELDS:
        raise DocumentMergeError("invalid_options", "Choose pdf, docx, pptx or workbook as the merge kind.")
    present = {name for name in ASSEMBLY_OPTION_FIELDS if arguments.get(name) is not None}
    if present - set(ASSEMBLY_KIND_OPTION_FIELDS[kind]):
        raise DocumentMergeError("invalid_options", f"Some settings don't apply to a {kind} merge.")
    if arguments.get("sheet") is not None and arguments.get("sheets") == "all":
        raise DocumentMergeError("invalid_options", "Name one sheet, or read all sheets, but not both.")
    return kind, DocumentMergeOptions(**{name: arguments[name] for name in present})


def build_document_assembly(kind, options, parts, result, content_sha256):
    """The description a document_merge step retains for the file it checked."""
    if kind not in DOCUMENT_MERGE_KINDS or not isinstance(options, DocumentMergeOptions):
        raise DocumentAssemblyError("invalid_source", "The merge description is invalid.")
    return validate_document_assembly({
        "profile": DOCUMENT_ASSEMBLY_PROFILE,
        "kind": kind,
        "options": {name: getattr(options, name) for name in ASSEMBLY_OPTION_FIELDS},
        "parts": [{"document_id": part.source_id, "file_name": part.display_name()} for part in parts],
        "output": {
            "format": ASSEMBLED_OUTPUT_FORMATS[kind],
            "media_type": result.media_type,
            "size_bytes": result.size_bytes,
            "content_sha256": content_sha256,
        },
    })


def validate_document_assembly(value):
    """A checked copy of a retained description; anything unexpected is refused, never repaired."""
    if not isinstance(value, dict) or set(value) != {"profile", "kind", "options", "parts", "output"}:
        raise DocumentAssemblyError("invalid_source", "The merge description is invalid.")
    kind = value["kind"]
    if value["profile"] != DOCUMENT_ASSEMBLY_PROFILE or kind not in DOCUMENT_MERGE_KINDS:
        raise DocumentAssemblyError("invalid_source", "The merge description is invalid.")
    options = value["options"]
    if not isinstance(options, dict) or set(options) != set(ASSEMBLY_OPTION_FIELDS):
        raise DocumentAssemblyError("invalid_source", "The merge options are invalid.")
    try:
        DocumentMergeOptions(**options)
    except (DocumentMergeError, TypeError) as exc:
        raise DocumentAssemblyError("invalid_source", "The merge options are invalid.") from exc
    parts = value["parts"]
    if not isinstance(parts, list) or not 2 <= len(parts) <= MAX_ASSEMBLY_PARTS:
        raise DocumentAssemblyError("invalid_source", "The merge description names an invalid set of files.")
    seen = set()
    for entry in parts:
        if (
            not isinstance(entry, dict) or set(entry) != {"document_id", "file_name"}
            or not isinstance(entry["document_id"], str) or not entry["document_id"].strip()
            or len(entry["document_id"]) > _MAX_IDENTIFIER or entry["document_id"] in seen
            or not isinstance(entry["file_name"], str) or len(entry["file_name"]) > _MAX_FILE_NAME
        ):
            raise DocumentAssemblyError("invalid_source", "The merge description names an invalid set of files.")
        seen.add(entry["document_id"])
    output = value["output"]
    if (
        not isinstance(output, dict) or set(output) != {"format", "media_type", "size_bytes", "content_sha256"}
        or output["format"] != ASSEMBLED_OUTPUT_FORMATS[kind]
        or output["media_type"] != DOCUMENT_MERGE_OUTPUTS[kind][1]
        or type(output["size_bytes"]) is not int or output["size_bytes"] < 1
        or not isinstance(output["content_sha256"], str) or not _DIGEST.match(output["content_sha256"])
    ):
        raise DocumentAssemblyError("invalid_source", "The merged file's description is invalid.")
    return {
        "profile": DOCUMENT_ASSEMBLY_PROFILE,
        "kind": kind,
        "options": dict(options),
        "parts": [dict(entry) for entry in parts],
        "output": dict(output),
    }


def assembled_output_format(value):
    """The format a described merge creates, after checking the description."""
    return validate_document_assembly(value)["output"]["format"]


def reassemble_document(value, read_document, *, max_output_bytes, check=None):
    """Assemble the described files again; return the result only when it is byte-identical.

    ``read_document(document_id)`` returns one file's current bytes. ``check()`` raises to
    stop; the engine calls it before every file is read and while the file is assembled.
    Returns the merge result, which the caller closes, and its SHA-256.
    """
    assembly = validate_document_assembly(value)
    if not callable(read_document):
        raise DocumentAssemblyError("unsupported_source", "A merged file needs its original files.")
    if type(max_output_bytes) is not int or max_output_bytes < 1:
        raise DocumentAssemblyError("invalid_limit", "A positive output limit is required.")
    if assembly["output"]["size_bytes"] > max_output_bytes:
        raise DocumentAssemblyError("size_limit", "The merged file is larger than this export allows.")

    def stop_requested():
        # check() raises to stop; the engine passes that failure through unchanged.
        if check is not None:
            check()
        return False

    parts = [
        DocumentMergePart(
            entry["document_id"], entry["file_name"],
            lambda document_id=entry["document_id"]: read_document(document_id),
        )
        for entry in assembly["parts"]
    ]
    limits = DocumentMergeLimits(max_parts=max(2, len(parts)), max_output_bytes=max_output_bytes)
    try:
        result = merge_documents(
            assembly["kind"], parts, options=DocumentMergeOptions(**assembly["options"]), limits=limits,
            cancel_requested=stop_requested,
        )
    except DocumentMergeError as exc:
        # The same files assembled once already within these limits; a refusal now means one changed.
        raise DocumentAssemblyError("source_changed", "A merged file no longer matches its sources.") from exc
    try:
        digest = hashlib.sha256()
        for chunk in result.iter_chunks():
            digest.update(chunk)
        if result.size_bytes != assembly["output"]["size_bytes"] or digest.hexdigest() != assembly["output"]["content_sha256"]:
            raise DocumentAssemblyError("source_changed", "A merged file no longer matches its sources.")
    except BaseException:
        result.close()
        raise
    return result, digest.hexdigest()


__all__ = [
    "ASSEMBLED_OUTPUT_FORMATS",
    "ASSEMBLY_KIND_OPTION_FIELDS",
    "ASSEMBLY_OPTION_FIELDS",
    "DOCUMENT_ASSEMBLY_PROFILE",
    "DocumentAssemblyError",
    "assembled_output_format",
    "build_document_assembly",
    "document_merge_options_from_arguments",
    "reassemble_document",
    "validate_document_assembly",
]
