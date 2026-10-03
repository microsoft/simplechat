# functions_orchestration_merge.py
"""Deterministic spreadsheet merging and inspection for Gather / Reason / Render orchestration.

Version: 0.261.221
Implemented in: 0.261.218
Inspection, reconciliation policies and prepared column mappings added in: 0.261.219

``tabular_merge`` is a Reason capability and ``tabular_inspect`` a Gather capability. Their
adapters in ``functions_orchestration_adapters`` authorize the sources. This module reads
each original file through the screening-aware byte reader, merges or inspects the files
with ``functions_tabular_merge``, and retains the results. It creates no file and calls no
model: ``render_file`` delivers a file from the retained ``records``, and a compose step
prepares any column mapping.
"""

from copy import deepcopy

from content_screening.access import read_available_document_bytes
from functions_analysis_access import analysis_source_snapshot
from functions_document_actions import (
    DOCUMENT_ACTION_CONTEXT_CHAT,
    DOCUMENT_ACTION_TYPE_MERGE,
    get_document_action_max_documents,
    get_document_action_max_rows,
)
from functions_mixed_source_orchestration import AUTHORIZATION_STATUS_AUTHORIZED, SOURCE_KIND_TABULAR
from functions_orchestration_result_contracts import Completeness, Coverage, RecordColumn, ResultContractError
from functions_orchestration_results import NamedOutput
from functions_tabular_merge import (
    TABULAR_COLUMN_MAPPING_PROFILE,
    TabularMergeError,
    TabularMergeLimits,
    TabularMergeSource,
    tabular_inspect_options_from_arguments,
    tabular_merge_format_for_file_name,
    tabular_merge_options_from_arguments,
)


TABULAR_MERGE_CAPABILITY_ID = "tabular_merge"
TABULAR_INSPECT_CAPABILITY_ID = "tabular_inspect"
TABULAR_MERGE_SOURCE_PURPOSE = "native"
TABULAR_MERGE_CHECKS = (
    "authorized_source_snapshots",
    "deterministic_row_append",
    "exact_row_count",
    "schema_policy_enforced",
)
TABULAR_INSPECT_CHECKS = (
    "authorized_source_snapshots",
    "bounded_inspection",
)
# Engine codes become application-owned failure codes; their text never reaches a user.
MERGE_FAILURE_CODES = {
    "schema_mismatch": "merge_schema_mismatch",
    "nothing_to_merge": "merge_nothing_to_merge",
    "duplicate_columns": "merge_columns_invalid",
    "header_too_long": "merge_columns_invalid",
    "too_many_columns": "merge_columns_invalid",
    "empty_source": "merge_columns_invalid",
    "dedupe_column_not_found": "merge_columns_not_found",
    "sort_column_not_found": "merge_columns_not_found",
    "row_has_extra_values": "merge_rows_invalid",
    "cell_too_large": "merge_rows_invalid",
    "unreadable_csv": "merge_source_unreadable",
    "unreadable_workbook": "merge_source_unreadable",
    "encrypted_workbook": "merge_source_unreadable",
    "source_unavailable": "merge_source_unreadable",
    "sheet_not_found": "merge_sheet_not_found",
    "too_few_sources": "merge_sources_invalid",
    "duplicate_source": "merge_sources_invalid",
    "unsupported_format": "merge_sources_invalid",
    "invalid_source": "merge_sources_invalid",
    "invalid_options": "merge_options_invalid",
    "invalid_mapping": "merge_mapping_invalid",
    "too_many_sources": "merge_limit_exceeded",
    "row_limit_exceeded": "merge_limit_exceeded",
    "sort_limit_exceeded": "merge_limit_exceeded",
    "too_many_sheets": "merge_limit_exceeded",
    "source_too_large": "merge_limit_exceeded",
    "workbook_too_large": "merge_limit_exceeded",
}
# Inspection reports unreadable files inside its result; only these refuse the whole step.
INSPECT_FAILURE_CODES = {
    "too_few_sources": "inspect_sources_invalid",
    "duplicate_source": "inspect_sources_invalid",
    "unsupported_format": "inspect_sources_invalid",
    "invalid_source": "inspect_sources_invalid",
    "invalid_options": "inspect_sources_invalid",
    "too_many_sources": "inspect_limit_exceeded",
    "inspection_too_large": "inspect_limit_exceeded",
}


def merge_failure_code(error):
    """The application-owned failure code for an engine error, or the generic step failure."""
    return MERGE_FAILURE_CODES.get(getattr(error, "code", None), "step_failed")


def inspect_failure_code(error):
    """The application-owned failure code for an inspection error, or the generic step failure."""
    return INSPECT_FAILURE_CODES.get(getattr(error, "code", None), "step_failed")


def tabular_merge_limits(settings, *, execution_context=DOCUMENT_ACTION_CONTEXT_CHAT):
    """The administrator's Merge limits for chat or workflows as engine limits."""
    max_sources = get_document_action_max_documents(
        DOCUMENT_ACTION_TYPE_MERGE, execution_context, settings=settings,
    )
    max_rows = get_document_action_max_rows(DOCUMENT_ACTION_TYPE_MERGE, execution_context, settings=settings)
    return TabularMergeLimits(
        max_sources=max(2, int(max_sources)), max_total_rows=int(max_rows),
        max_sort_rows=min(int(max_rows), TabularMergeLimits.max_sort_rows),
    )


def tabular_merge_options(arguments, mapping=None):
    """Engine options from validated step arguments and an optional validated mapping."""
    return tabular_merge_options_from_arguments(arguments, mapping=mapping)


def tabular_inspect_options(arguments):
    """Inspection options from validated step arguments."""
    return tabular_inspect_options_from_arguments(arguments)


def require_tabular_merge_manifest(manifest, document_ids, *, minimum=2):
    """The authorized manifest in the planned order, with every source a CSV or Excel file."""
    document_ids = list(document_ids or ())
    if (
        not isinstance(manifest, list) or len(document_ids) < minimum
        or [source.get("document_id") for source in manifest if isinstance(source, dict)] != document_ids
        or any(source.get("authorization_status") != AUTHORIZATION_STATUS_AUTHORIZED for source in manifest)
    ):
        raise PermissionError("The complete merge source selection is unavailable.")
    for source in manifest:
        if (
            source.get("source_kind") != SOURCE_KIND_TABULAR
            or tabular_merge_format_for_file_name(source.get("file_name")) is None
        ):
            raise TabularMergeError("unsupported_format", "Only CSV and Excel files can be merged.")
    return manifest


def build_tabular_merge_sources(manifest, user_id, *, byte_reader=None):
    """Engine sources whose bytes are read, one file at a time, through the access boundary."""
    reader = byte_reader or read_available_document_bytes
    sources = []
    for entry in manifest:
        source = deepcopy(entry)

        def load(source=source):
            _document, content = reader(
                source, user_id, source.get("group_id"), source.get("public_workspace_id"),
                purpose=TABULAR_MERGE_SOURCE_PURPOSE,
            )
            return content

        sources.append(TabularMergeSource(
            source_id=source["document_id"],
            file_name=source.get("file_name") or source.get("display_name") or source["document_id"],
            load_bytes=load,
        ))
    return sources


def build_document_merge_parts(manifest, user_id, *, byte_reader=None):
    """Document merge parts whose bytes are read, one file at a time, through the access boundary."""
    # The document merge engine loads only when files are assembled.
    from functions_document_merge import DocumentMergePart

    reader = byte_reader or read_available_document_bytes
    parts = []
    for entry in manifest:
        source = deepcopy(entry)

        def load(source=source):
            _document, content = reader(
                source, user_id, source.get("group_id"), source.get("public_workspace_id"),
                purpose=TABULAR_MERGE_SOURCE_PURPOSE,
            )
            return content

        parts.append(DocumentMergePart(
            source_id=source["document_id"],
            file_name=source.get("file_name") or source.get("display_name") or source["document_id"],
            load_bytes=load,
        ))
    return parts


def merge_report_with_mapping(report, mapping):
    """The merge report, recording what a prepared column mapping asked for."""
    if mapping is not None:
        report["mapping"] = {
            "profile": TABULAR_COLUMN_MAPPING_PROFILE,
            "explicitly_ignored": list(mapping["ignored"]),
            "low_confidence": deepcopy(mapping["low_confidence"]),
            "notes": mapping["notes"],
        }
    return report


def persist_tabular_merge_result(
    *, service, producer, merge_result, sources, guard_token, input_fingerprint, mapping=None,
):
    """Retain the merged rows and the merge report as one complete Reason result."""
    if producer.capability_id != TABULAR_MERGE_CAPABILITY_ID:
        raise ResultContractError("result_merge_invalid")
    snapshots = analysis_source_snapshot(sources)
    nullable = merge_result.nullable_columns
    columns = tuple(RecordColumn(name, "string", name in nullable) for name in merge_result.columns)
    row_count = merge_result.row_count
    coverage = Coverage(len(snapshots), len(snapshots), "sources")
    report = merge_report_with_mapping(merge_result.report, mapping)
    limitations = tuple(report.get("limitations") or ())
    outputs = [
        NamedOutput(
            "records", "records-v1", merge_result.iter_records(),
            Completeness("complete", row_count, row_count, coverage, "valid", TABULAR_MERGE_CHECKS, limitations),
            columns,
        ),
        NamedOutput(
            "report", "structured-v1", report,
            Completeness("complete", 1, 1, coverage, "valid", TABULAR_MERGE_CHECKS, limitations),
        ),
    ]
    return service.persist_task_result(
        producer=producer, role="reason", status="complete", outputs=outputs,
        sources=snapshots, origin="grounded", guard_token=guard_token, input_fingerprint=input_fingerprint,
    )


def persist_tabular_inspection_result(*, service, producer, inspection, sources, guard_token, input_fingerprint):
    """Retain the inspection as one complete Gather result."""
    if producer.capability_id != TABULAR_INSPECT_CAPABILITY_ID:
        raise ResultContractError("result_inspection_invalid")
    snapshots = analysis_source_snapshot(sources)
    coverage = Coverage(len(snapshots), len(snapshots), "sources")
    limitations = list(inspection.get("limitations") or ())
    problems = sum(entry.get("status") == "problem" for entry in inspection.get("sources") or ())
    if problems:
        limitations.append(f"{problems} file(s) couldn't be read; the inspection reports why.")
    outputs = [
        NamedOutput(
            "inspection", "structured-v1", inspection,
            Completeness("complete", 1, 1, coverage, "valid", TABULAR_INSPECT_CHECKS, tuple(limitations)),
        ),
    ]
    return service.persist_task_result(
        producer=producer, role="gather", status="complete", outputs=outputs,
        sources=snapshots, origin="grounded", guard_token=guard_token, input_fingerprint=input_fingerprint,
    )


def merge_step_summary(merge_result):
    """A short, application-owned description of a completed merge."""
    totals = (merge_result.report or {}).get("totals") or {}
    summary = (
        f"Merged {totals.get('rows', merge_result.row_count):,} row(s) from "
        f"{totals.get('sources', 0)} file(s) into {totals.get('columns', len(merge_result.columns))} column(s)"
    )
    details = []
    if totals.get("duplicates_removed"):
        details.append(f"removed {totals['duplicates_removed']:,} duplicate row(s)")
    if totals.get("excluded"):
        details.append(f"left out {totals['excluded']} file(s) or sheet(s) whose columns don't fit")
    return f"{summary}; {'; '.join(details)}." if details else f"{summary}."


def inspection_step_summary(inspection):
    """A short, application-owned description of a completed inspection."""
    sources = inspection.get("sources") or []
    compatibility = inspection.get("compatibility") or {}
    problems = sum(entry.get("status") == "problem" for entry in sources)
    if compatibility.get("identical_columns"):
        fit = "they all have the same columns"
    elif compatibility.get("tables"):
        fit = "their columns differ"
    else:
        fit = "no columns could be read"
    summary = f"Inspected {len(sources)} file(s); {fit}"
    if problems:
        summary += f"; {problems} couldn't be read"
    return f"{summary}."
