# functions_orchestration_analysis_results.py
"""Lossless internal Analyze/Compare projections, separate from user artifacts.

Readers and lifecycle tokens are supplied by the owning orchestration attempt.
No source is reconstructed from a preview, report paragraph, or document name.
"""

from copy import deepcopy

from functions_analysis_access import analysis_source_snapshot
from functions_orchestration_result_contracts import (
    Completeness,
    Coverage,
    RecordColumn,
    ResultContractError,
)
from functions_orchestration_results import NamedOutput, SavedAnalysisRecordSource


FINDING_COLUMNS = (
    RecordColumn("record", "object"),
    RecordColumn("evidence", "array"),
)


def _count(value):
    if type(value) is not int or value < 0:
        raise ResultContractError("result_analysis_coverage_invalid")
    return value


def _native_completeness(reader):
    manifest = reader.manifest
    validation = manifest.get("validation") or {}
    native_coverage = validation.get("coverage") or {}
    assigned = _count(native_coverage.get("assigned_work_units"))
    completed = _count(native_coverage.get("completed_work_units"))
    failed = _count(native_coverage.get("failed_work_units"))
    pending = _count(native_coverage.get("pending_work_units"))
    if completed + failed + pending != assigned:
        raise ResultContractError("result_analysis_coverage_invalid")
    coverage = Coverage(assigned, completed, "work_units")
    state = (manifest.get("execution") or {}).get("status")
    if validation.get("status") == "valid" and state == "succeeded":
        if (
            native_coverage.get("status") != "complete"
            or _count(native_coverage.get("assigned_sources")) == 0
            or native_coverage["assigned_sources"] != _count(native_coverage.get("completed_sources"))
        ):
            raise ResultContractError("result_analysis_coverage_invalid")
        status = "complete"
    elif validation.get("status") == "partial" and state in {"succeeded", "incomplete", "pending"}:
        status = "partial"
    else:
        raise ResultContractError("result_native_analysis_incomplete")
    checks = ["saved_native_record_identity", "complete_saved_record_iteration"]
    for check in validation.get("checks") or []:
        if type(check) is not dict or type(check.get("name")) is not str or type(check.get("status")) is not str:
            raise ResultContractError("result_analysis_validation_invalid")
        checks.append(f'{check["name"]}:{check["status"]}')
    limitations = list(validation.get("limitations") or [])
    if status == "partial":
        limitations.append("Only accepted native findings are retained; unresolved or unfinished work is not complete.")
    return status, coverage, tuple(checks), tuple(limitations)


def _completeness(status, count, coverage, checks, limitations, *, expected=None):
    return Completeness(
        status, count if expected is None else expected, count, coverage,
        {"complete": "valid", "partial": "partial", "failed": "invalid"}[status],
        checks, limitations,
    )


def _public_columns(reader):
    """Declare a JSON-valued projection only after checking every complete record."""
    names = None
    homogeneous = True
    count = 0
    reader.recheck()
    for unit in reader.iter_units():
        record = unit.get("record")
        values = record.get("values") if type(record) is dict else None
        if type(values) is not dict:
            raise ResultContractError("result_native_analysis_invalid")
        if names is None:
            names = tuple(values)
        elif set(values) != set(names):
            homogeneous = False
        count += 1
    if count != _count(reader.manifest.get("record_count")):
        raise ResultContractError("result_count_invalid")
    reader.recheck()
    if not homogeneous or not names:
        return ()
    return tuple(RecordColumn(name, "json", nullable=True) for name in names)


def _finding_units(reader):
    reader.recheck()
    yield from reader.iter_units()
    reader.recheck()


def persist_saved_analysis_result(*, service, producer, reader, guard_token, input_fingerprint=None):
    """Retain native units, optional exact public rows, and actual report text.

    ``findings`` always has the ordered record/evidence schema, so heterogeneous
    native finding values need no invented fields or null-padding. ``records``
    is an additional public-values projection only for a complete homogeneous
    result accepted by SavedAnalysisRecordSource. Partial native results never
    pass through that stricter complete-only compatibility adapter.
    """
    manifest = reader.manifest
    expected_identity = {
        "kind": "orchestration", "user_id": producer.user_id,
        "conversation_id": producer.conversation_id, "run_id": producer.run_id,
        "step_id": producer.step_id,
    }
    authoritative = (manifest.get("outputs") or {}).get(manifest.get("authoritative_output")) or {}
    if (
        manifest.get("contract_version") != "analyze-final-v1"
        or manifest.get("identity") != expected_identity
        or authoritative.get("kind") != "records"
        or producer.capability_id != "document_analyze"
    ):
        raise ResultContractError("result_native_analysis_invalid")
    sources = analysis_source_snapshot((manifest.get("analysis_access") or {}).get("sources"))
    status, coverage, checks, limitations = _native_completeness(reader)
    count = _count(manifest.get("record_count"))
    columns = _public_columns(reader)
    projection = SavedAnalysisRecordSource(reader, columns=columns) if status == "complete" and columns else None
    findings = projection.iter_units() if projection is not None else _finding_units(reader)
    outputs = [
        NamedOutput("findings", "records-v1", findings,
                    _completeness(status, count, coverage, checks, limitations), FINDING_COLUMNS),
    ]
    if projection is not None:
        outputs.append(NamedOutput(
            "records", "records-v1", projection.iter_records(),
            _completeness(status, count, coverage, checks, limitations), columns,
        ))
    report_available = (manifest.get("validation") or {}).get("presentation_status") == "ready"
    if report_available:
        report = reader.read_report_text()
        if not report.strip():
            raise ResultContractError("result_analysis_report_missing")
        outputs.append(NamedOutput(
            "report", "markdown-v1", report,
            _completeness(status, 1, coverage, checks, limitations),
        ))
    outputs.append(NamedOutput(
        "coverage", "structured-v1", {
            "coverage": deepcopy(manifest.get("coverage") or {}),
            "validation": deepcopy(manifest.get("validation") or {}),
            "sources": sources,
            "report_available": report_available,
            "public_records_available": projection is not None,
        },
        _completeness(status, 1, coverage, checks, limitations),
    ))
    return service.persist_task_result(
        producer=producer, role="reason", status=status, outputs=outputs,
        sources=sources, origin="grounded", guard_token=guard_token, input_fingerprint=input_fingerprint,
    )


def persist_comparison_result(*, service, producer, result, sources, guard_token, input_fingerprint=None):
    """Retain outcomes; only accepted results claim an input completion receipt."""
    if (
        type(result) is not dict or result.get("comparison_result_version") != "comparison-v1"
        or producer.capability_id != "document_compare"
    ):
        raise ResultContractError("result_comparison_invalid")
    status = result.get("execution_status")
    if status not in {"complete", "partial", "failed"}:
        raise ResultContractError("result_comparison_incomplete")
    value = result.get("comparison")
    if type(value) is not dict or type(value.get("items")) is not list or type(value.get("right_document_ids")) is not list:
        raise ResultContractError("result_comparison_invalid")
    expected = len(value["right_document_ids"])
    actual = len(value["items"])
    coverage = Coverage(expected, actual, "items")
    limitations = tuple(result.get("limitations") or ())
    checks = ("authorized_source_snapshots", "explicit_target_outcomes", "complete_pairwise_text")
    snapshots = analysis_source_snapshot(sources)
    outputs = [
        NamedOutput(
            "comparison", "comparison-v1", deepcopy(value),
            _completeness(status, actual, coverage, checks, limitations, expected=expected),
        ),
        NamedOutput(
            "coverage", "structured-v1", {
                "coverage": deepcopy(result.get("coverage") or {}),
                "failures": deepcopy(result.get("failures") or []),
                "limitations": list(limitations),
                "sources": snapshots,
                "left_document": deepcopy(result.get("left_document")),
                "right_documents": deepcopy(result.get("right_documents")),
                "report_available": result.get("report_status") == "ready",
            },
            _completeness(status, 1, coverage, checks, limitations),
        ),
    ]
    if result.get("report_status") == "ready":
        report = result.get("analysis_reply")
        if type(report) is not str or not report.strip() or not actual:
            raise ResultContractError("result_comparison_report_missing")
        outputs.append(NamedOutput(
            "report", "markdown-v1", report,
            _completeness(status, 1, coverage, checks, limitations),
        ))
    receipt_options = {"input_fingerprint": input_fingerprint} if status in {"complete", "partial"} else {}
    return service.persist_task_result(
        producer=producer, role="reason", status=status, outputs=outputs,
        sources=snapshots, origin="grounded", guard_token=guard_token, **receipt_options,
    )
