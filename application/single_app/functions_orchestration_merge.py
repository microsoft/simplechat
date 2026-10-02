# functions_orchestration_merge.py
"""Deterministic spreadsheet merging for Gather / Reason / Render orchestration.

Version: 0.261.218

``tabular_merge`` is a Reason capability. Its adapter, ``run_tabular_merge`` in
``functions_orchestration_adapters``, authorizes the sources. This module reads each
original file through the screening-aware byte reader, merges the files with
``functions_tabular_merge`` and retains the merged rows plus a merge report. It creates no
file and calls no model: ``render_file`` delivers a file from the retained ``records``.
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
    DEFAULT_SOURCE_COLUMN_NAME,
    SCHEMA_POLICY_BY_NAME,
    TabularMergeError,
    TabularMergeLimits,
    TabularMergeOptions,
    TabularMergeSource,
    tabular_merge_format_for_file_name,
)


TABULAR_MERGE_CAPABILITY_ID = "tabular_merge"
TABULAR_MERGE_SOURCE_PURPOSE = "native"
TABULAR_MERGE_CHECKS = (
    "authorized_source_snapshots",
    "deterministic_row_append",
    "exact_row_count",
    "schema_policy_enforced",
)
# Engine codes become application-owned failure codes; their text never reaches a user.
MERGE_FAILURE_CODES = {
    "schema_mismatch": "merge_schema_mismatch",
    "duplicate_columns": "merge_columns_invalid",
    "header_too_long": "merge_columns_invalid",
    "too_many_columns": "merge_columns_invalid",
    "empty_source": "merge_columns_invalid",
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
    "too_many_sources": "merge_limit_exceeded",
    "row_limit_exceeded": "merge_limit_exceeded",
    "source_too_large": "merge_limit_exceeded",
    "workbook_too_large": "merge_limit_exceeded",
}


def merge_failure_code(error):
    """The application-owned failure code for an engine error, or the generic step failure."""
    return MERGE_FAILURE_CODES.get(getattr(error, "code", None), "step_failed")


def tabular_merge_limits(settings, *, execution_context=DOCUMENT_ACTION_CONTEXT_CHAT):
    """The administrator's Merge limits for chat or workflows as engine limits."""
    max_sources = get_document_action_max_documents(
        DOCUMENT_ACTION_TYPE_MERGE, execution_context, settings=settings,
    )
    max_rows = get_document_action_max_rows(DOCUMENT_ACTION_TYPE_MERGE, execution_context, settings=settings)
    return TabularMergeLimits(max_sources=max(2, int(max_sources)), max_total_rows=int(max_rows))


def tabular_merge_options(arguments):
    """Engine options from validated step arguments."""
    arguments = arguments if isinstance(arguments, dict) else {}
    return TabularMergeOptions(
        schema_policy=arguments.get("schema_policy") or SCHEMA_POLICY_BY_NAME,
        sheet=arguments.get("sheet") or None,
        include_source_column=arguments.get("include_source_column", True) is not False,
        source_column_name=arguments.get("source_column_name") or DEFAULT_SOURCE_COLUMN_NAME,
    )


def require_tabular_merge_manifest(manifest, document_ids):
    """The authorized manifest in merge order, with every source a CSV or Excel file."""
    document_ids = list(document_ids or ())
    if (
        not isinstance(manifest, list) or len(document_ids) < 2
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


def persist_tabular_merge_result(*, service, producer, merge_result, sources, guard_token, input_fingerprint):
    """Retain the merged rows and the merge report as one complete Reason result."""
    if producer.capability_id != TABULAR_MERGE_CAPABILITY_ID:
        raise ResultContractError("result_merge_invalid")
    snapshots = analysis_source_snapshot(sources)
    columns = tuple(RecordColumn(name, "string") for name in merge_result.columns)
    row_count = merge_result.row_count
    coverage = Coverage(len(snapshots), len(snapshots), "sources")
    report = merge_result.report
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


def merge_step_summary(merge_result):
    """A short, application-owned description of a completed merge."""
    totals = (merge_result.report or {}).get("totals") or {}
    return (
        f"Merged {totals.get('rows', merge_result.row_count):,} row(s) from "
        f"{totals.get('sources', 0)} file(s) into {totals.get('columns', len(merge_result.columns))} column(s)."
    )
