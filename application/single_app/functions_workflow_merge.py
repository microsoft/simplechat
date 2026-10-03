# functions_workflow_merge.py
"""Workflow Merge tasks: combine many authorized files into one downloadable file.

Version: 0.261.221
Implemented in: 0.261.220
PDF and workbook merges added in: 0.261.221

A workflow task whose document action is ``merge`` runs here instead of a model or agent.
The runner says which files to merge: the files selected on the task, in that order, or
files found when the run starts (every matching file in a workspace, recently added files,
or the files a File Sync run changed), ordered by file name. This module authorizes every
file again through the source manifest and reads each original through the screening-aware
byte reader. Spreadsheet rows are appended by the tabular merge engine and rendered as one
CSV or Excel file by the shared generated-file export framework; PDFs and workbooks are
assembled by the document merge engine. The file is attached to the run's conversation.
No model is called. A resumed run repeats the merge from its first file; merging is
deterministic, so the resulting file is the same, and the artifact idempotency key keeps
one copy.
"""

import hashlib
import os

from functions_appinsights import log_event
from functions_document_actions import (
    DOCUMENT_ACTION_CONTEXT_WORKFLOW,
    DOCUMENT_ACTION_TARGET_MODE_ALL,
    DOCUMENT_ACTION_TARGET_MODE_RECENT,
    DOCUMENT_ACTION_TARGET_MODE_SELECTED,
    MERGE_KIND_DOCX,
    MERGE_KIND_EXTENSIONS,
    MERGE_KIND_LABELS,
    MERGE_KIND_OUTPUT_FORMATS,
    MERGE_KIND_PDF,
    MERGE_KIND_PPTX,
    MERGE_KIND_TABULAR,
    MERGE_KIND_WORKBOOK,
    MERGE_KINDS_AVAILABLE,
    MERGE_TARGET_MODE_CHANGED,
)
from functions_generated_export_contracts import (
    GeneratedFileExportError,
    GeneratedFileExportReadiness,
    GeneratedFileExportRequest,
)
from functions_mixed_source_orchestration import AUTHORIZATION_STATUS_AUTHORIZED, SOURCE_KIND_TABULAR
from functions_orchestration_merge import (
    build_document_merge_parts,
    build_tabular_merge_sources,
    tabular_merge_limits,
)
from functions_tabular_merge import (
    TabularMergeCancelled,
    TabularMergeError,
    merge_tabular_sources,
    tabular_merge_options_from_arguments,
)


WORKFLOW_MERGE_CAPABILITY = "file_merge"
WORKFLOW_MERGE_DEFAULT_FILE_NAME = "merged"
# A workflow run may assemble more than one chat turn; Excel and PowerPoint cap what opens well.
WORKFLOW_MERGE_MAX_PAGES = 10_000
WORKFLOW_MERGE_MAX_SLIDES = 2_000
WORKFLOW_MERGE_MAX_SHEETS = 500
_EXPORT_PROFILES = {
    "csv": "exact_tabular_records_v1",
    "xlsx": "exact_tabular_workbook_v1",
}
_DOCUMENT_OPTION_KEYS = ("bookmarks", "sheets", "sheet", "formatting", "page_breaks", "source_headings", "sections")
_KIND_FILE_DESCRIPTIONS = {
    MERGE_KIND_TABULAR: "CSV or Excel file (.csv, .xlsx, .xlsm or .xls)",
    MERGE_KIND_WORKBOOK: "CSV or Excel file (.csv, .xlsx, .xlsm or .xls)",
    MERGE_KIND_PDF: "PDF file (.pdf)",
    MERGE_KIND_DOCX: "Word document (.docx)",
    MERGE_KIND_PPTX: "PowerPoint deck (.pptx)",
}
_MAX_LISTED_FILES = 20
_MAX_LISTED_COLUMNS = 12
_EXPORT_FAILURES = {
    "record_limit": "The merged table has more rows than one file can hold. Merge fewer files per run.",
    "value_limit": "The merged table is larger than one generated file can hold. Merge fewer files per run.",
}
_OFFICE_FAILURES = {
    "limit_exceeded": (
        "The merged table is too large for an Excel file (at most 1,048,575 rows, 5,000,000 cells "
        "and 32 MB). Choose CSV output instead."
    ),
}


class WorkflowMergeError(ValueError):
    """A merge task that cannot run; the message is shown on the failed task."""


class WorkflowMergeAccessError(PermissionError):
    """A file the merge needs is not available to the workflow's owner; the message is fixed text."""


class WorkflowMergeCancelled(RuntimeError):
    """The run was cancelled while the merge was in progress."""


class _MergedRecordsSource:
    """The merged rows as a complete record source for the shared CSV and XLSX renderers."""

    kind = "records"

    def __init__(self, merge_result):
        self._result = merge_result
        self.record_count = merge_result.row_count
        self.columns = tuple(merge_result.columns)
        self.readiness = GeneratedFileExportReadiness()

    def iter_records(self):
        return self._result.iter_records()

    def recheck(self):
        if self._result.row_count != self.record_count or tuple(self._result.columns) != self.columns:
            raise GeneratedFileExportError("invalid_source", "The merged rows changed while rendering.")


def merge_output_file_name(action_config, output_format):
    """The file name a merge task creates, from its configured base name."""
    base = str((action_config or {}).get("output_file_name") or "").strip() or WORKFLOW_MERGE_DEFAULT_FILE_NAME
    return f"{base}.{output_format}"


def _target_description(target_mode):
    return {
        DOCUMENT_ACTION_TARGET_MODE_ALL: "No files in the workspace matched this merge",
        DOCUMENT_ACTION_TARGET_MODE_RECENT: "No files were added or updated in the merge's time window",
        MERGE_TARGET_MODE_CHANGED: "No new or changed files arrived with this sync",
    }.get(target_mode, "No files matched this merge")


def _nothing_to_merge_result(target_mode):
    return {
        "reply": f"{_target_description(target_mode)}, so there was nothing to merge and no file was created.",
        "generated_analysis_artifacts": [],
        "generated_tabular_outputs": [],
        "token_usage": {},
        "model_deployment_name": None,
        "provider": None,
        "merge_summary": {"status": "nothing_to_merge", "files": 0, "rows": 0},
    }


def _listed(values, limit):
    values = [str(value) for value in values]
    shown = ", ".join(values[:limit])
    if len(values) > limit:
        shown += f" and {len(values) - limit} more"
    return shown


def build_merge_reply(report, file_name, *, skipped_files=(), unavailable_files=()):
    """A short Markdown summary of what the merge produced and what it left out."""
    totals = report.get("totals") or {}
    lines = [
        f"Merged **{totals.get('rows', 0):,} row(s)** from **{totals.get('sources', 0)} file(s)** into "
        f"**{file_name}** with {totals.get('columns', 0)} column(s).",
        "",
    ]
    details = []
    if totals.get("duplicates_removed"):
        details.append(f"Removed {totals['duplicates_removed']:,} duplicate row(s).")
    left_out = [
        entry for entry in report.get("sources") or []
        if entry.get("status") in ("excluded", "skipped")
    ]
    if left_out:
        labels = [
            f"{entry.get('file_name')}" + (f" ({entry.get('sheet')})" if entry.get("sheet") else "")
            for entry in left_out
        ]
        details.append(f"Left out {len(left_out)} file(s) or sheet(s): {_listed(labels, _MAX_LISTED_FILES)}.")
    if skipped_files:
        details.append(
            f"Skipped {len(skipped_files)} file(s) that aren't the right type: "
            f"{_listed(skipped_files, _MAX_LISTED_FILES)}."
        )
    if unavailable_files:
        details.append(
            f"Skipped {len(unavailable_files)} file(s) that aren't available right now: "
            f"{_listed(unavailable_files, _MAX_LISTED_FILES)}."
        )
    nullable = [name for name in report.get("nullable_columns") or [] if name != report.get("sheet_column")]
    if nullable:
        details.append(
            f"Columns some files don't have are left blank for their rows: {_listed(nullable, _MAX_LISTED_COLUMNS)}."
        )
    if details:
        lines.extend(f"- {detail}" for detail in details)
        lines.append("")
    merged = [
        entry.get("file_name") for entry in report.get("sources") or [] if entry.get("status") == "merged"
    ]
    lines.append(f"Files merged, in order: {_listed(dict.fromkeys(merged), _MAX_LISTED_FILES)}.")
    return "\n".join(lines).strip()


def execute_workflow_merge(
    action_config,
    settings,
    *,
    user_id,
    conversation_id,
    run_id,
    task_id="",
    collect_documents,
    resolve_manifest,
    render_file,
    publish_file,
    byte_reader=None,
    cancel_requested=None,
    report_progress=None,
):
    """Merge a workflow task's files and attach the merged file to the run conversation.

    ``collect_documents(action_config, extensions, max_documents)`` returns document ids, in
    merge order, for files found at run time. ``resolve_manifest`` authorizes ids again.
    ``render_file(source, request, max_output_bytes)`` renders spreadsheet rows through the
    shared export framework, and ``publish_file(...)`` attaches the file; both are injected so
    the merge stays testable. Document kinds are assembled by the document merge engine.
    """
    action_config = action_config if isinstance(action_config, dict) else {}
    kind = action_config.get("merge_kind") or MERGE_KIND_TABULAR
    if kind not in MERGE_KINDS_AVAILABLE:
        raise WorkflowMergeError(f"Merging {MERGE_KIND_LABELS.get(kind, kind)} files is not available yet.")
    target_mode = action_config.get("target_mode") or DOCUMENT_ACTION_TARGET_MODE_SELECTED
    output_formats = MERGE_KIND_OUTPUT_FORMATS[kind]
    output_format = action_config.get("output_format") or output_formats[0]
    if output_format not in output_formats:
        raise WorkflowMergeError(
            f"A {MERGE_KIND_LABELS[kind]} merge creates {' or '.join(value.upper() for value in output_formats)} files."
        )
    limits = tabular_merge_limits(settings, execution_context=DOCUMENT_ACTION_CONTEXT_WORKFLOW)
    extensions = MERGE_KIND_EXTENSIONS[kind]
    selected = target_mode == DOCUMENT_ACTION_TARGET_MODE_SELECTED

    def check_cancel():
        if callable(cancel_requested) and cancel_requested():
            raise WorkflowMergeCancelled("The merge was cancelled.")

    check_cancel()
    if target_mode in (DOCUMENT_ACTION_TARGET_MODE_ALL, DOCUMENT_ACTION_TARGET_MODE_RECENT):
        document_ids = list(collect_documents(action_config, extensions, limits.max_sources))
    else:
        document_ids = list(action_config.get("document_ids") or [])
    if not document_ids:
        if selected:
            raise WorkflowMergeError("Select at least two files to merge.")
        return _nothing_to_merge_result(target_mode)
    if len(document_ids) > limits.max_sources:
        raise WorkflowMergeError(
            f"{len(document_ids)} files match this merge; at most {limits.max_sources} can be merged in one "
            "workflow run. Narrow the files or ask an administrator to raise the Merge workflow file limit."
        )

    check_cancel()
    manifest = resolve_manifest(
        document_ids, user_id=user_id, conversation_id=conversation_id,
        doc_scope=action_config.get("doc_scope", "all"),
        active_group_ids=action_config.get("active_group_ids"),
        active_public_workspace_ids=action_config.get("active_public_workspace_id"),
        cancel_requested=cancel_requested, request_correlation_id=run_id,
    )
    if (
        not isinstance(manifest, list)
        or [source.get("document_id") for source in manifest if isinstance(source, dict)] != document_ids
    ):
        raise WorkflowMergeAccessError("The files in this merge could not be authorized.")
    unavailable = [
        str(source.get("file_name") or source.get("document_id")) for source in manifest
        if source.get("authorization_status") != AUTHORIZATION_STATUS_AUTHORIZED
    ]
    if unavailable and selected:
        raise WorkflowMergeAccessError(
            "A file selected for this merge is no longer available to the workflow's owner."
        )

    usable = []
    skipped = []
    for source in manifest:
        if source.get("authorization_status") != AUTHORIZATION_STATUS_AUTHORIZED:
            continue
        extension = os.path.splitext(str(source.get("file_name") or ""))[1].strip().lower()
        if extension in extensions and (kind != MERGE_KIND_TABULAR or source.get("source_kind") == SOURCE_KIND_TABULAR):
            usable.append(source)
        else:
            skipped.append(str(source.get("file_name") or source.get("document_id")))
    if skipped and selected:
        raise WorkflowMergeError(
            f"{_listed(skipped, 5)} isn't a {_KIND_FILE_DESCRIPTIONS[kind]}, so it can't be merged."
        )
    if not usable:
        return _nothing_to_merge_result(target_mode)

    def progress(update):
        if callable(report_progress):
            report_progress(update)

    run = {
        "kind": kind, "usable": usable, "skipped": skipped, "unavailable": unavailable,
        "user_id": user_id, "conversation_id": conversation_id, "run_id": run_id, "task_id": task_id,
        "file_name": merge_output_file_name(action_config, output_format), "output_format": output_format,
        "min_sources": 2 if selected else 1, "max_sources": limits.max_sources,
    }
    if kind == MERGE_KIND_TABULAR:
        result = _merge_rows(
            run, action_config, settings, limits, render_file=render_file, publish_file=publish_file,
            byte_reader=byte_reader, cancel_requested=cancel_requested, check_cancel=check_cancel,
            progress=progress,
        )
    else:
        result = _merge_files(
            run, action_config, settings, publish_file=publish_file, byte_reader=byte_reader,
            cancel_requested=cancel_requested, check_cancel=check_cancel, progress=progress,
        )
    log_event(
        "[WORKFLOW_MERGE] Merged workflow files.",
        extra={
            "user_id": user_id, "run_id": run_id, "task_id": task_id, "kind": kind,
            "files": len(usable), "output_format": output_format, "skipped": len(skipped),
            "unavailable": len(unavailable),
        },
    )
    return result


def _idempotency_key(run, content_sha256):
    # A replay of the same merge reuses its file; one over files that changed since gets its own.
    return f"workflow-merge:{run['run_id']}:{run['task_id'] or 'task'}:{content_sha256}"


def _merge_rows(run, action_config, settings, limits, *, render_file, publish_file, byte_reader, cancel_requested,
                check_cancel, progress):
    """Append the rows of spreadsheet files into one CSV or Excel file."""
    sources = build_tabular_merge_sources(run["usable"], run["user_id"], byte_reader=byte_reader)
    output_format = run["output_format"]
    try:
        options = tabular_merge_options_from_arguments(action_config.get("merge_options") or {})
        with merge_tabular_sources(
            sources, options=options, limits=limits, min_sources=run["min_sources"],
            cancel_requested=lambda: bool(callable(cancel_requested) and cancel_requested()),
            on_progress=progress,
        ) as merged:
            check_cancel()
            report = merged.report
            request = GeneratedFileExportRequest(output_format, _EXPORT_PROFILES[output_format])
            with render_file(_MergedRecordsSource(merged), request, _max_artifact_bytes(settings)) as rendered:
                check_cancel()
                artifact = publish_file(
                    user_id=run["user_id"], conversation_id=run["conversation_id"], file_name=run["file_name"],
                    output_format=output_format, rendered=rendered, row_count=merged.row_count,
                    summary=f"Merged {merged.row_count:,} row(s) from {report['totals']['sources']} file(s).",
                    idempotency_key=_idempotency_key(run, str(getattr(rendered, "content_sha256", "") or "")),
                )
    except TabularMergeCancelled as exc:
        raise WorkflowMergeCancelled("The merge was cancelled.") from exc
    except TabularMergeError as exc:
        # The owner's own file and column names make the failure actionable on the task.
        raise WorkflowMergeError(exc.message) from exc
    except GeneratedFileExportError as exc:
        raise WorkflowMergeError(
            _EXPORT_FAILURES.get(exc.code, "The merged file couldn't be created.")
        ) from exc
    except ValueError as exc:
        # Office renderer failures carry a stable code; the module loads only when rendering.
        if type(exc).__name__ != "OfficeRenderError":
            raise
        raise WorkflowMergeError(
            _OFFICE_FAILURES.get(getattr(exc, "code", None), "The merged Excel file couldn't be created.")
        ) from exc

    file_name = artifact.get("file_name") or run["file_name"]
    return {
        "reply": build_merge_reply(
            report, file_name, skipped_files=run["skipped"], unavailable_files=run["unavailable"],
        ),
        "generated_analysis_artifacts": [artifact],
        "generated_tabular_outputs": [artifact] if output_format == "csv" else [],
        "token_usage": {},
        "model_deployment_name": None,
        "provider": None,
        "merge_summary": {
            "status": "merged",
            "kind": MERGE_KIND_TABULAR,
            "files": report["totals"]["sources"],
            "rows": report["totals"]["rows"],
            "columns": report["totals"]["columns"],
            "duplicates_removed": report["totals"].get("duplicates_removed", 0),
            "excluded": report["totals"].get("excluded", 0),
            "skipped": len(run["skipped"]) + len(run["unavailable"]),
            "file_name": file_name,
        },
    }


class _MergedFile:
    """An assembled file as the artifact upload reads it: a seekable stream, its size and digest."""

    def __init__(self, result):
        digest = hashlib.sha256()
        for chunk in result.iter_chunks():
            digest.update(chunk)
        self.file_content = result.open_stream()
        self.size_bytes = result.size_bytes
        self.content_sha256 = digest.hexdigest()


def _document_limits(settings, max_sources, kind):
    """Workflow bounds for assembled files: more files, pages and sheets than one chat turn allows.

    A workbook is copied one file at a time to disk, so it may read up to twice the
    generated-file limit. Other kinds hold their merged content in memory until the file
    is written, so they keep the engine's fixed input budget whatever that limit is.
    """
    from functions_document_merge import DocumentMergeLimits

    artifact_bytes = _max_artifact_bytes(settings)
    total_input_bytes = DocumentMergeLimits.max_total_input_bytes
    if kind == MERGE_KIND_WORKBOOK:
        total_input_bytes = max(total_input_bytes, 2 * artifact_bytes)
    return DocumentMergeLimits(
        max_parts=max(2, max_sources),
        max_output_bytes=artifact_bytes,
        max_total_input_bytes=total_input_bytes,
        max_pages=WORKFLOW_MERGE_MAX_PAGES,
        max_slides=WORKFLOW_MERGE_MAX_SLIDES,
        max_sheets=WORKFLOW_MERGE_MAX_SHEETS,
    )


def _merge_files(run, action_config, settings, *, publish_file, byte_reader, cancel_requested, check_cancel,
                 progress):
    """Assemble PDF, Word, PowerPoint or workbook files, in order, into one file."""
    from functions_document_merge import (
        DocumentMergeCancelled,
        DocumentMergeError,
        DocumentMergeOptions,
        merge_documents,
    )

    kind = run["kind"]
    merge_options = action_config.get("merge_options") or {}
    parts = build_document_merge_parts(run["usable"], run["user_id"], byte_reader=byte_reader)
    try:
        options = DocumentMergeOptions(**{
            key: merge_options[key] for key in _DOCUMENT_OPTION_KEYS if key in merge_options
        })
        result = merge_documents(
            kind, parts, options=options, limits=_document_limits(settings, run["max_sources"], kind),
            cancel_requested=lambda: bool(callable(cancel_requested) and cancel_requested()),
            on_progress=progress, min_parts=run["min_sources"],
        )
    except DocumentMergeCancelled as exc:
        raise WorkflowMergeCancelled("The merge was cancelled.") from exc
    except DocumentMergeError as exc:
        # The owner's own file names make the failure actionable on the task.
        raise WorkflowMergeError(exc.message) from exc

    with result:
        check_cancel()
        report = result.report
        merged_file = _MergedFile(result)
        merged = [entry for entry in report.get("parts") or [] if entry.get("status") == "merged"]
        artifact = publish_file(
            user_id=run["user_id"], conversation_id=run["conversation_id"], file_name=run["file_name"],
            output_format=run["output_format"], rendered=merged_file, row_count=None,
            summary=f"Merged {len(merged)} file(s) into one {MERGE_KIND_LABELS[kind]} file.",
            idempotency_key=_idempotency_key(run, merged_file.content_sha256),
        )

    file_name = artifact.get("file_name") or run["file_name"]
    totals = report.get("totals") or {}
    return {
        "reply": build_document_merge_reply(
            report, file_name, skipped_files=run["skipped"], unavailable_files=run["unavailable"],
        ),
        "generated_analysis_artifacts": [artifact],
        "generated_tabular_outputs": [],
        "token_usage": {},
        "model_deployment_name": None,
        "provider": None,
        "merge_summary": {
            "status": "merged",
            "kind": kind,
            "files": len(merged),
            "pages": totals.get("pages", 0),
            "slides": totals.get("slides", 0),
            "sheets": totals.get("sheets", 0),
            "skipped": len(run["skipped"]) + len(run["unavailable"]),
            "file_name": file_name,
        },
    }


def build_document_merge_reply(report, file_name, *, skipped_files=(), unavailable_files=()):
    """A short Markdown summary of an assembled file and what it left out or changed."""
    totals = report.get("totals") or {}
    parts = report.get("parts") or []
    merged = [entry.get("file_name") for entry in parts if entry.get("status") == "merged"]
    size = {
        "pdf": ("pages", "page(s)"), "pptx": ("slides", "slide(s)"), "workbook": ("sheets", "sheet(s)"),
    }.get(report.get("kind"))
    measure = f" with {totals.get(size[0], 0):,} {size[1]}" if size else ""
    lines = [f"Merged **{len(merged)} file(s)** into **{file_name}**{measure}.", ""]
    details = []
    for warning in report.get("warnings") or []:
        details.append(str(warning.get("message") or ""))
    for entry in parts:
        for warning in entry.get("warnings") or []:
            details.append(f"{entry.get('file_name')}: {warning.get('message')}")
    if skipped_files:
        details.append(
            f"Skipped {len(skipped_files)} file(s) that aren't the right type: "
            f"{_listed(skipped_files, _MAX_LISTED_FILES)}."
        )
    if unavailable_files:
        details.append(
            f"Skipped {len(unavailable_files)} file(s) that aren't available right now: "
            f"{_listed(unavailable_files, _MAX_LISTED_FILES)}."
        )
    details.extend(str(limitation) for limitation in report.get("limitations") or [])
    details = [detail for detail in dict.fromkeys(details) if detail]
    if details:
        lines.extend(f"- {detail}" for detail in details)
        lines.append("")
    lines.append(f"Files merged, in order: {_listed(merged, _MAX_LISTED_FILES)}.")
    return "\n".join(lines).strip()


def _max_artifact_bytes(settings):
    try:
        megabytes = max(1, int((settings or {}).get("max_generated_chat_artifact_size_mb", 500)))
    except (TypeError, ValueError):
        megabytes = 500
    return megabytes * 1024 * 1024


def collect_merge_candidates(documents, extensions, max_documents):
    """Current, matching documents ordered by file name; more than the limit fails, never truncates."""
    matches = {}
    for document in documents or ():
        document_id = str(document.get("id") or document.get("document_id") or "").strip()
        file_name = str(document.get("file_name") or "").strip()
        if not document_id or document_id in matches:
            continue
        if os.path.splitext(file_name)[1].lower() not in extensions:
            continue
        matches[document_id] = (file_name.casefold(), file_name, document_id)
    if len(matches) > max_documents:
        raise WorkflowMergeError(
            f"More than {max_documents} files match this merge; at most {max_documents} can be merged in one "
            "workflow run. Narrow the files or ask an administrator to raise the Merge workflow file limit."
        )
    return [document_id for _, _, document_id in sorted(matches.values())]


__all__ = [
    "WORKFLOW_MERGE_CAPABILITY",
    "WorkflowMergeAccessError",
    "WorkflowMergeCancelled",
    "WorkflowMergeError",
    "build_document_merge_reply",
    "build_merge_reply",
    "collect_merge_candidates",
    "execute_workflow_merge",
    "merge_output_file_name",
]
