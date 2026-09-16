# functions_workflow_validation.py
"""Deterministic task-output validation, independent of model prose."""

import json
from collections.abc import Mapping

from jsonschema import Draft202012Validator

from functions_workflow_definitions import normalize_workflow_output_contract, workflow_output_kind_matches


def workflow_output_contract_instruction(contract):
    """Describe trusted authored output requirements without asking for fabricated coverage."""
    if not contract:
        return ""
    normalized = normalize_workflow_output_contract(contract)
    descriptions = {
        "any": "Use the output format requested by the task.",
        "text": "Return the task's final answer as readable text.",
        "records": "Return the finalized records as one JSON array of objects.",
        "json": "Return the finalized output as one JSON object or array.",
        "document_results": "Retain a distinct finalized result for each source document.",
    }
    instructions = [
        "[Workflow output requirements]",
        descriptions[normalized["kind"]],
        "Do not include competing intermediate versions in the final output.",
        "Never invent records or evidence to satisfy the expected count or coverage.",
        "The application validates the result; do not claim validation succeeded in place of producing the data.",
    ]
    if "expected_count" in normalized:
        instructions.append(f"Expected collection size: {normalized['expected_count']}.")
    if "identity_field" in normalized:
        instructions.append(f"Each record requires a unique nonempty identity in: {normalized['identity_field']}.")
    if "schema" in normalized:
        instructions.extend(["Schema for the complete final value:", json.dumps(normalized["schema"], ensure_ascii=True)])
    return "\n".join(instructions)


def workflow_coverage_status(coverage):
    """Recognize explicit completion/count evidence; absent evidence is unknown."""
    if not isinstance(coverage, Mapping) or not coverage:
        return "unknown"
    progress = coverage.get("progress_meta") or {}
    if not isinstance(progress, Mapping):
        return "incomplete"
    state = progress.get("status") or coverage.get("status")
    if state is not None and not isinstance(state, str):
        return "incomplete"
    if state in {"pending", "queued", "running", "processing", "retrying"}:
        return "pending"
    if state in {"failed", "partial", "incomplete", "canceled", "cancelled"}:
        return "incomplete"
    if coverage.get("partial_coverage") is True:
        return "incomplete"
    for field in (
        "failed_windows", "failed_chunks", "failed_documents", "failed_count",
        "missing_count", "missing_document_count", "unprocessed_count",
    ):
        value = coverage.get(field)
        if value is not None and not (
            type(value) is int and value == 0 or isinstance(value, list) and not value
        ):
            return "incomplete"
    observed_counts = False
    for total_key, processed_key in (
        ("total_windows", "processed_windows"),
        ("total_chunks", "processed_chunks"),
        ("expected_count", "processed_count"),
    ):
        total, processed = coverage.get(total_key), coverage.get(processed_key)
        if total_key not in coverage and processed_key not in coverage:
            continue
        if type(total) is not int or type(processed) is not int or total < 0 or processed != total:
            return "incomplete"
        observed_counts = True
    if observed_counts or state in {"completed", "complete", "valid"}:
        return "complete"
    return "unknown"


def validate_workflow_task_output(envelope, contract=None):
    """Return counts/reason codes only; retain a producer's stricter validation."""
    normalized = normalize_workflow_output_contract(contract) if contract is not None else None
    output_name = envelope.get("authoritative_output")
    output = (envelope.get("outputs") or {}).get(output_name)
    reasons = []
    incomplete = []
    counts = {}
    producer_state = (envelope.get("execution") or {}).get("status")
    producer_validation = envelope.get("validation") or {}
    producer_status = producer_validation.get("status")
    if producer_state in {"pending", "queued", "running"}:
        incomplete.append("producer_pending")
    elif producer_state != "succeeded":
        incomplete.append("producer_incomplete")
    if producer_status == "invalid":
        reasons.append("producer_validation_failed")
    elif producer_status in {"partial", "incomplete", "accepted_partial"}:
        incomplete.append("producer_coverage_incomplete")
    elif producer_validation.get("valid") is False:
        reasons.append("producer_validation_failed")
    coverage_state = workflow_coverage_status(envelope.get("coverage"))
    if coverage_state == "incomplete":
        incomplete.append("producer_coverage_incomplete")
    elif coverage_state == "pending":
        incomplete.append("producer_pending")
    if not isinstance(output, Mapping) or "value" not in output:
        reasons.append("missing_authoritative_output")
        value = None
    else:
        value = output["value"]
    kind = (output or {}).get("kind")
    if kind == "records" and (
        not isinstance(value, list) or not all(isinstance(row, Mapping) for row in value)
    ):
        reasons.append("output_not_records")
    elif kind == "text" and not isinstance(value, str):
        reasons.append("output_not_text")
    if normalized is not None:
        required_kind = normalized["kind"]
        if not workflow_output_kind_matches(kind, required_kind):
            reasons.append("output_kind_mismatch")
        if "schema" in normalized:
            validator = Draft202012Validator(normalized["schema"])
            # Avoid unbounded user-visible error messages and never return values
            # from the model output in a validation diagnostic.
            error_count = 0
            for _error in validator.iter_errors(value):
                error_count += 1
                if error_count == 100:
                    break
            if error_count:
                reasons.append("output_schema_mismatch")
                counts["schema_errors"] = error_count
        if isinstance(value, list):
            counts["actual_count"] = len(value)
        if "expected_count" in normalized:
            expected = normalized["expected_count"]
            counts["expected_count"] = expected
            if not isinstance(value, list):
                reasons.append("output_not_collection")
            elif len(value) < expected:
                incomplete.append("missing_output_items")
            elif len(value) > expected:
                reasons.append("unexpected_output_items")
        if "identity_field" in normalized and isinstance(value, list):
            field = normalized["identity_field"]
            identities = set()
            missing = duplicates = 0
            for row in value:
                identity = row.get(field) if isinstance(row, Mapping) else None
                if type(identity) not in {str, int} or isinstance(identity, str) and not identity.strip():
                    missing += 1
                    continue
                canonical = json.dumps(identity, ensure_ascii=True)
                if canonical in identities:
                    duplicates += 1
                identities.add(canonical)
            counts.update(missing_identity_count=missing, duplicate_identity_count=duplicates)
            if missing:
                reasons.append("missing_output_identity")
            if duplicates:
                reasons.append("duplicate_output_identity")
        if normalized["require_complete_coverage"]:
            if coverage_state != "complete":
                incomplete.append(f"coverage_{coverage_state}")
    if reasons:
        status = "invalid"
    elif incomplete:
        # A policy can accept partial data but never an unfinished producer.
        can_accept = (
            normalized is not None and normalized["allow_partial"]
            and producer_state in {"succeeded", "incomplete"}
            and "producer_pending" not in incomplete
        )
        status = "accepted_partial" if can_accept else "incomplete"
    elif normalized is None or not any((
        normalized["kind"] != "any",
        bool(normalized.get("schema")),
        "expected_count" in normalized,
        "identity_field" in normalized,
        normalized["require_complete_coverage"],
    )):
        status = "not_requested"
    else:
        status = "valid"
    return {
        "version": 1,
        "status": status,
        "eligible": status in {"valid", "not_requested", "accepted_partial"},
        "reason_codes": list(dict.fromkeys(reasons + incomplete)),
        "counts": counts,
    }


def workflow_run_outcome(task_results):
    """Completion is derived from all executed tasks, not the last message."""
    states = []
    for task in task_results:
        report = (task.get("result") or {}).get("workflow_validation") or task.get("workflow_validation") or {}
        states.append(report.get("status", "not_requested"))
        if task.get("status") == "failed":
            return {"status": "failed", "success": False}
    if "invalid" in states:
        return {"status": "invalid", "success": False}
    if "incomplete" in states:
        return {"status": "incomplete", "success": False}
    if "accepted_partial" in states:
        return {"status": "completed_partial", "success": True}
    return {"status": "completed", "success": True}
