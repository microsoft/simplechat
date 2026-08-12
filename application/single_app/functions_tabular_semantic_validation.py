# functions_tabular_semantic_validation.py
"""Bounded field-level verification and repair contracts for tabular outputs."""

import hashlib
import json
from decimal import Decimal, InvalidOperation


TABULAR_SEMANTIC_VALIDATION_CONTRACT_VERSION = "tabular-semantic-validation-v1"
TABULAR_SEMANTIC_VALIDATION_STATUSES = frozenset({"pass", "fail", "uncertain", "unsupported"})
TABULAR_SEMANTIC_REPAIRABLE_STATUSES = frozenset({"fail", "uncertain"})
TABULAR_SEMANTIC_MAX_ROWS = 500
TABULAR_SEMANTIC_MAX_FIELDS = 50
TABULAR_SEMANTIC_MAX_EVIDENCE_FIELDS = 20
TABULAR_SEMANTIC_MAX_REASON_CODE_LENGTH = 80
TABULAR_SEMANTIC_VALIDATION_MODES = frozenset({"off", "shadow", "active"})
TABULAR_SEMANTIC_MAX_STRING_LENGTH = 4096
TABULAR_SEMANTIC_MAX_COLLECTION_ITEMS = 200
TABULAR_SEMANTIC_MAX_COLLECTION_CHARS = 16384
TABULAR_SEMANTIC_MAX_NUMERIC_ABS = Decimal("1e18")


class TabularSemanticValidationError(ValueError):
    """Raised when verifier or repair output violates the bounded contract."""


def _normalize_field_name(value, label):
    normalized_value = str(value or "").strip()
    if not normalized_value or len(normalized_value) > 128:
        raise TabularSemanticValidationError(f"Semantic {label} is invalid")
    return normalized_value


def _normalize_row_key(value):
    normalized_value = str(value or "").strip()
    if not normalized_value or len(normalized_value) > 80:
        raise TabularSemanticValidationError("Semantic row key is invalid")
    return normalized_value


def _semantic_field_contracts(transformation_spec):
    fields = []
    for field in list((transformation_spec or {}).get("fields") or []):
        if not isinstance(field, dict) or str(field.get("mode") or "").strip().lower() == "deterministic":
            continue
        fields.append({
            "name": _normalize_field_name(field.get("name"), "field name"),
            "type": str(field.get("type") or "string").strip().lower() or "string",
            "nullable": bool(field.get("nullable", True)),
            "allowed_values": list(field.get("allowed_values") or []),
        })
    if len(fields) > TABULAR_SEMANTIC_MAX_FIELDS:
        raise TabularSemanticValidationError("Semantic field count exceeds the bounded limit")
    return fields


def build_semantic_verification_request(source_rows, output_rows, transformation_spec):
    """Build a bounded verifier payload with opaque row keys and public values."""
    sources = list(source_rows or [])
    outputs = list(output_rows or [])
    if len(sources) != len(outputs):
        raise TabularSemanticValidationError("Semantic verification row counts do not match")
    if len(outputs) > TABULAR_SEMANTIC_MAX_ROWS:
        raise TabularSemanticValidationError("Semantic verification row count exceeds the bounded limit")
    field_contracts = _semantic_field_contracts(transformation_spec)
    if not field_contracts:
        return {"version": TABULAR_SEMANTIC_VALIDATION_CONTRACT_VERSION, "fields": [], "rows": []}
    rows = []
    for row_index, (source_row, output_row) in enumerate(zip(sources, outputs), start=1):
        if not isinstance(source_row, dict) or not isinstance(output_row, dict):
            raise TabularSemanticValidationError("Semantic verification rows must be objects")
        rows.append({
            "row_key": f"r{row_index}",
            "source": dict(source_row),
            "candidate": {
                field["name"]: output_row.get(field["name"])
                for field in field_contracts
            },
        })
    return {
        "version": TABULAR_SEMANTIC_VALIDATION_CONTRACT_VERSION,
        "fields": field_contracts,
        "rows": rows,
    }


def normalize_semantic_verification_response(response_payload, verification_request):
    """Validate one exact field-level verifier response without retaining reasoning."""
    if not isinstance(response_payload, dict) or set(response_payload) != {"version", "rows"}:
        raise TabularSemanticValidationError("Semantic verifier response shape is invalid")
    if response_payload.get("version") != TABULAR_SEMANTIC_VALIDATION_CONTRACT_VERSION:
        raise TabularSemanticValidationError("Semantic verifier response version is unsupported")

    expected_rows = list((verification_request or {}).get("rows") or [])
    expected_fields = [field["name"] for field in list((verification_request or {}).get("fields") or [])]
    expected_row_keys = [row["row_key"] for row in expected_rows]
    raw_rows = response_payload.get("rows")
    if not isinstance(raw_rows, list) or len(raw_rows) != len(expected_rows):
        raise TabularSemanticValidationError("Semantic verifier response row count is invalid")

    normalized_rows = []
    status_counts = {status: 0 for status in sorted(TABULAR_SEMANTIC_VALIDATION_STATUSES)}
    seen_row_keys = set()
    for raw_row in raw_rows:
        if not isinstance(raw_row, dict) or set(raw_row) != {"row_key", "fields"}:
            raise TabularSemanticValidationError("Semantic verifier row shape is invalid")
        row_key = _normalize_row_key(raw_row.get("row_key"))
        if row_key not in expected_row_keys or row_key in seen_row_keys:
            raise TabularSemanticValidationError("Semantic verifier row identity is invalid")
        seen_row_keys.add(row_key)
        raw_fields = raw_row.get("fields")
        if not isinstance(raw_fields, list) or len(raw_fields) != len(expected_fields):
            raise TabularSemanticValidationError("Semantic verifier field count is invalid")
        normalized_fields = []
        seen_fields = set()
        for raw_field in raw_fields:
            if not isinstance(raw_field, dict) or set(raw_field) != {
                "name",
                "status",
                "reason_code",
                "evidence_fields",
            }:
                raise TabularSemanticValidationError("Semantic verifier field shape is invalid")
            field_name = _normalize_field_name(raw_field.get("name"), "field name")
            if field_name not in expected_fields or field_name in seen_fields:
                raise TabularSemanticValidationError("Semantic verifier field identity is invalid")
            seen_fields.add(field_name)
            status = str(raw_field.get("status") or "").strip().lower()
            if status not in TABULAR_SEMANTIC_VALIDATION_STATUSES:
                raise TabularSemanticValidationError("Semantic verifier field status is unsupported")
            reason_code = str(raw_field.get("reason_code") or "").strip().lower()
            if not reason_code or len(reason_code) > TABULAR_SEMANTIC_MAX_REASON_CODE_LENGTH:
                raise TabularSemanticValidationError("Semantic verifier reason code is invalid")
            evidence_fields = [
                _normalize_field_name(value, "evidence field")
                for value in list(raw_field.get("evidence_fields") or [])
            ]
            if len(evidence_fields) > TABULAR_SEMANTIC_MAX_EVIDENCE_FIELDS:
                raise TabularSemanticValidationError("Semantic verifier evidence field count is too large")
            source_fields = set(expected_rows[expected_row_keys.index(row_key)]["source"])
            if set(evidence_fields) - source_fields:
                raise TabularSemanticValidationError("Semantic verifier referenced unknown evidence fields")
            status_counts[status] += 1
            normalized_fields.append({
                "name": field_name,
                "status": status,
                "reason_code": reason_code,
                "evidence_fields": evidence_fields,
            })
        normalized_rows.append({"row_key": row_key, "fields": normalized_fields})

    if [row["row_key"] for row in normalized_rows] != expected_row_keys:
        raise TabularSemanticValidationError("Semantic verifier row order is invalid")
    return {
        "version": TABULAR_SEMANTIC_VALIDATION_CONTRACT_VERSION,
        "rows": normalized_rows,
        "status_counts": status_counts,
    }


def collect_semantic_repair_targets(verification_report):
    """Return only failed or uncertain row-field pairs eligible for repair."""
    targets = []
    for row in list((verification_report or {}).get("rows") or []):
        for field in list(row.get("fields") or []):
            if field.get("status") in TABULAR_SEMANTIC_REPAIRABLE_STATUSES:
                targets.append({
                    "row_key": row.get("row_key"),
                    "field_name": field.get("name"),
                    "reason_code": field.get("reason_code"),
                })
    return targets


def _value_matches_contract(value, field_contract):
    if value is None:
        return bool(field_contract.get("nullable"))
    value_type = field_contract.get("type")
    if value_type == "string":
        type_valid = isinstance(value, str) and len(value) <= TABULAR_SEMANTIC_MAX_STRING_LENGTH
    elif value_type == "boolean":
        type_valid = isinstance(value, bool)
    elif value_type == "integer":
        type_valid = (
            isinstance(value, int)
            and not isinstance(value, bool)
            and abs(value) <= TABULAR_SEMANTIC_MAX_NUMERIC_ABS
        )
    elif value_type == "number":
        try:
            parsed_value = Decimal(str(value))
            type_valid = (
                not isinstance(value, bool)
                and parsed_value.is_finite()
                and abs(parsed_value) <= TABULAR_SEMANTIC_MAX_NUMERIC_ABS
            )
        except (InvalidOperation, TypeError, ValueError):
            type_valid = False
    elif value_type == "object":
        try:
            serialized_value = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        except (TypeError, ValueError):
            serialized_value = ""
        type_valid = (
            isinstance(value, dict)
            and len(value) <= TABULAR_SEMANTIC_MAX_COLLECTION_ITEMS
            and len(serialized_value) <= TABULAR_SEMANTIC_MAX_COLLECTION_CHARS
        )
    elif value_type == "array":
        try:
            serialized_value = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        except (TypeError, ValueError):
            serialized_value = ""
        type_valid = (
            isinstance(value, list)
            and len(value) <= TABULAR_SEMANTIC_MAX_COLLECTION_ITEMS
            and len(serialized_value) <= TABULAR_SEMANTIC_MAX_COLLECTION_CHARS
        )
    else:
        type_valid = False
    allowed_values = list(field_contract.get("allowed_values") or [])
    return type_valid and (not allowed_values or value in allowed_values)


def apply_semantic_repair_response(output_rows, repair_payload, repair_targets, transformation_spec):
    """Apply an exact targeted repair response and reject extra rows or fields."""
    rows = [dict(row) for row in list(output_rows or [])]
    targets = list(repair_targets or [])
    expected_targets = {
        (target.get("row_key"), target.get("field_name"))
        for target in targets
    }
    if not isinstance(repair_payload, dict) or set(repair_payload) != {"version", "rows"}:
        raise TabularSemanticValidationError("Semantic repair response shape is invalid")
    if repair_payload.get("version") != TABULAR_SEMANTIC_VALIDATION_CONTRACT_VERSION:
        raise TabularSemanticValidationError("Semantic repair response version is unsupported")
    field_contracts = {
        field["name"]: field
        for field in _semantic_field_contracts(transformation_spec)
    }
    applied_targets = set()
    for raw_row in list(repair_payload.get("rows") or []):
        if not isinstance(raw_row, dict) or set(raw_row) != {"row_key", "values"}:
            raise TabularSemanticValidationError("Semantic repair row shape is invalid")
        row_key = _normalize_row_key(raw_row.get("row_key"))
        if not row_key.startswith("r") or not row_key[1:].isdigit():
            raise TabularSemanticValidationError("Semantic repair row key is invalid")
        row_index = int(row_key[1:]) - 1
        if row_index < 0 or row_index >= len(rows):
            raise TabularSemanticValidationError("Semantic repair row key is out of range")
        values = raw_row.get("values")
        if not isinstance(values, dict) or not values:
            raise TabularSemanticValidationError("Semantic repair values are invalid")
        for field_name, field_value in values.items():
            normalized_field = _normalize_field_name(field_name, "repair field")
            target_key = (row_key, normalized_field)
            if target_key not in expected_targets or target_key in applied_targets:
                raise TabularSemanticValidationError("Semantic repair changed an unrequested field")
            field_contract = field_contracts.get(normalized_field)
            if not field_contract or not _value_matches_contract(field_value, field_contract):
                raise TabularSemanticValidationError("Semantic repair value violates its field contract")
            rows[row_index][normalized_field] = field_value
            applied_targets.add(target_key)
    if applied_targets != expected_targets:
        raise TabularSemanticValidationError("Semantic repair response omitted required targets")
    return rows


def build_safe_semantic_validation_counts(verification_report, repair_targets=None, repair_attempt_count=0):
    """Return low-cardinality counts safe for run metadata and telemetry."""
    status_counts = dict((verification_report or {}).get("status_counts") or {})
    return {
        "pass_count": int(status_counts.get("pass") or 0),
        "fail_count": int(status_counts.get("fail") or 0),
        "uncertain_count": int(status_counts.get("uncertain") or 0),
        "unsupported_count": int(status_counts.get("unsupported") or 0),
        "repair_target_count": len(list(repair_targets or [])),
        "repair_attempt_count": max(0, int(repair_attempt_count or 0)),
    }



def _repair_signature(repair_payload):
    return hashlib.sha256(
        json.dumps(repair_payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


async def verify_and_repair_semantic_rows(
    source_rows,
    output_rows,
    transformation_spec,
    mode,
    invoke_verifier,
    invoke_repair,
    max_repair_attempts=2,
    max_repair_rows=100,
    checkpoint_candidate=None,
):
    """Verify semantic fields and repair only failed targets before checkpointing."""
    normalized_mode = str(mode or "off").strip().lower()
    if normalized_mode not in TABULAR_SEMANTIC_VALIDATION_MODES:
        raise TabularSemanticValidationError("Semantic validation mode is unsupported")
    rows = [dict(row) for row in list(output_rows or [])]
    verification_request = build_semantic_verification_request(
        source_rows,
        rows,
        transformation_spec,
    )
    if normalized_mode == "off" or not verification_request["fields"]:
        return rows, build_safe_semantic_validation_counts({}, [], 0), []

    verification_payload = await invoke_verifier(verification_request)
    verification_report = normalize_semantic_verification_response(
        verification_payload,
        verification_request,
    )
    repair_targets = collect_semantic_repair_targets(verification_report)
    attempt_summaries = []
    if normalized_mode == "shadow":
        return (
            rows,
            build_safe_semantic_validation_counts(verification_report, repair_targets, 0),
            attempt_summaries,
        )

    if verification_report["status_counts"].get("unsupported"):
        raise TabularSemanticValidationError("Semantic verification reported unsupported required fields")
    target_row_count = len({target["row_key"] for target in repair_targets})
    if target_row_count > max(0, int(max_repair_rows or 0)):
        raise TabularSemanticValidationError("Semantic repair row count exceeds the bounded limit")

    max_attempts = max(0, min(5, int(max_repair_attempts or 0)))
    seen_repair_signatures = set()
    attempt_number = 0
    while repair_targets and attempt_number < max_attempts:
        attempt_number += 1
        repair_payload = await invoke_repair(verification_request, repair_targets, attempt_number)
        signature = _repair_signature(repair_payload)
        if signature in seen_repair_signatures:
            raise TabularSemanticValidationError("Semantic repair repeated an identical response")
        seen_repair_signatures.add(signature)
        rows = apply_semantic_repair_response(
            rows,
            repair_payload,
            repair_targets,
            transformation_spec,
        )
        verification_request = build_semantic_verification_request(
            source_rows,
            rows,
            transformation_spec,
        )
        verification_payload = await invoke_verifier(verification_request)
        verification_report = normalize_semantic_verification_response(
            verification_payload,
            verification_request,
        )
        repair_targets = collect_semantic_repair_targets(verification_report)
        attempt_summary = build_safe_semantic_validation_counts(
            verification_report,
            repair_targets,
            attempt_number,
        )
        attempt_summaries.append(attempt_summary)
        if callable(checkpoint_candidate):
            await checkpoint_candidate(rows, attempt_summary, attempt_number)
        if verification_report["status_counts"].get("unsupported"):
            raise TabularSemanticValidationError("Semantic verification reported unsupported required fields")

    if repair_targets or verification_report["status_counts"].get("fail") or verification_report["status_counts"].get("uncertain"):
        raise TabularSemanticValidationError("Semantic repair attempts were exhausted")
    return (
        rows,
        build_safe_semantic_validation_counts(
            verification_report,
            repair_targets,
            attempt_number,
        ),
        attempt_summaries,
    )
