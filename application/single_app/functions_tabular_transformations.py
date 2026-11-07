# functions_tabular_transformations.py
"""Bounded transformation specifications for tabular generated outputs."""

from contextlib import nullcontext
from datetime import date, datetime
from decimal import (
    Context,
    Decimal,
    DecimalException,
    DivisionByZero,
    Inexact,
    InvalidOperation,
    Overflow,
    ROUND_HALF_EVEN,
    ROUND_HALF_UP,
    Underflow,
    localcontext,
)
from fractions import Fraction
from graphlib import CycleError, TopologicalSorter
import math
import re


TABULAR_TRANSFORMATION_SPEC_VERSION = "tabular-transform-v1"
TABULAR_TRANSFORMATION_PRECISE_SPEC_VERSION = "tabular-transform-v2"
TABULAR_TRANSFORMATION_SPEC_VERSIONS = frozenset({
    TABULAR_TRANSFORMATION_SPEC_VERSION,
    TABULAR_TRANSFORMATION_PRECISE_SPEC_VERSION,
})
TABULAR_TRANSFORMATION_FIELD_MODE_DETERMINISTIC = "deterministic"
TABULAR_TRANSFORMATION_FIELD_MODE_SEMANTIC = "semantic"
TABULAR_TRANSFORMATION_FIELD_MODE_HYBRID = "hybrid"
TABULAR_TRANSFORMATION_FIELD_MODES = frozenset({
    TABULAR_TRANSFORMATION_FIELD_MODE_DETERMINISTIC,
    TABULAR_TRANSFORMATION_FIELD_MODE_SEMANTIC,
    TABULAR_TRANSFORMATION_FIELD_MODE_HYBRID,
})

TABULAR_TRANSFORMATION_MAX_FIELDS = 200
TABULAR_TRANSFORMATION_MAX_FIELD_NAME_LENGTH = 128
TABULAR_TRANSFORMATION_MAX_EXPRESSION_DEPTH = 24
TABULAR_TRANSFORMATION_MAX_EXPRESSION_STEPS = 2000
TABULAR_TRANSFORMATION_MAX_BRANCHES = 100
TABULAR_TRANSFORMATION_MAX_LIST_ITEMS = 200
TABULAR_TRANSFORMATION_MAX_STRING_LENGTH = 4096
TABULAR_TRANSFORMATION_MAX_NUMERIC_ABS = Decimal("1e18")
TABULAR_TRANSFORMATION_DECIMAL_PRECISION = 64
TABULAR_TRANSFORMATION_MAX_DECIMAL_EXPONENT = 128
TABULAR_TRANSFORMATION_MAX_NUMERIC_TEXT_LENGTH = 256
TABULAR_TRANSFORMATION_MAX_ROUND_SCALE = 12
TABULAR_TRANSFORMATION_MAX_ROUND_RATIO_BITS = 4096
TABULAR_TRANSFORMATION_MAX_JSON_INTEGER = (1 << 53) - 1
TABULAR_TRANSFORMATION_ROUNDING_MODES = {
    "half_up": ROUND_HALF_UP,
    "half_even": ROUND_HALF_EVEN,
}
TABULAR_TRANSFORMATION_INTERNAL_FIELD_PREFIX = "__simplechat"
TABULAR_TRANSFORMATION_INTERNAL_FIELD_NAMES = frozenset({
    "source_row_number",
    "source_row_identity",
})

TABULAR_TRANSFORMATION_COMPARISON_OPS = frozenset({"eq", "ne", "lt", "lte", "gt", "gte"})
TABULAR_TRANSFORMATION_BOOLEAN_OPS = frozenset({"all", "any", "not"})
TABULAR_TRANSFORMATION_ARITHMETIC_OPS = frozenset({"add", "subtract", "multiply", "divide"})
TABULAR_TRANSFORMATION_ALLOWED_OPS = frozenset({
    "case",
    "coalesce",
    "copy",
    "in",
    "is_null",
    *TABULAR_TRANSFORMATION_COMPARISON_OPS,
    *TABULAR_TRANSFORMATION_BOOLEAN_OPS,
    *TABULAR_TRANSFORMATION_ARITHMETIC_OPS,
})

_PRECISE_DECIMAL_CONTEXT = Context(
    prec=TABULAR_TRANSFORMATION_DECIMAL_PRECISION,
    rounding=ROUND_HALF_EVEN,
    Emin=-TABULAR_TRANSFORMATION_MAX_DECIMAL_EXPONENT,
    Emax=18,
    traps=[InvalidOperation, DivisionByZero, Overflow, Underflow, Inexact],
)
_DECIMAL_TEXT_PATTERN = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")


class TabularTransformationSpecError(ValueError):
    """Raised when a tabular transformation spec is unsupported or unsafe."""


class TabularTransformationEvaluationError(ValueError):
    """Raised when a valid transformation spec cannot evaluate one row."""


class _SpecValidationBudget:
    def __init__(self):
        self.step_count = 0

    def consume_step(self, depth):
        self.step_count += 1
        if depth > TABULAR_TRANSFORMATION_MAX_EXPRESSION_DEPTH:
            raise TabularTransformationSpecError("Tabular transformation expression is too deep")
        if self.step_count > TABULAR_TRANSFORMATION_MAX_EXPRESSION_STEPS:
            raise TabularTransformationSpecError("Tabular transformation spec exceeds the step limit")


def _is_internal_field_name(field_name):
    normalized_field = str(field_name or "").strip()
    return (
        normalized_field in TABULAR_TRANSFORMATION_INTERNAL_FIELD_NAMES
        or normalized_field.startswith(TABULAR_TRANSFORMATION_INTERNAL_FIELD_PREFIX)
    )


def _normalize_field_name(field_name, label="field"):
    normalized_field = str(field_name or "").strip()
    if not normalized_field:
        raise TabularTransformationSpecError(f"Tabular transformation {label} name is empty")
    if len(normalized_field) > TABULAR_TRANSFORMATION_MAX_FIELD_NAME_LENGTH:
        raise TabularTransformationSpecError(f"Tabular transformation {label} name is too long")
    if _is_internal_field_name(normalized_field):
        raise TabularTransformationSpecError(f"Tabular transformation {label} uses a reserved field name")
    return normalized_field


def _normalize_field_list(field_names=None, label="field"):
    normalized_fields = []
    seen_fields = set()
    for field_name in list(field_names or []):
        normalized_field = _normalize_field_name(field_name, label=label)
        if normalized_field in seen_fields:
            raise TabularTransformationSpecError(f"Tabular transformation {label} list contains duplicates")
        seen_fields.add(normalized_field)
        normalized_fields.append(normalized_field)
    if len(normalized_fields) > TABULAR_TRANSFORMATION_MAX_FIELDS:
        raise TabularTransformationSpecError(f"Tabular transformation {label} list is too large")
    return normalized_fields


def _normalize_mode(mode, expression=None):
    normalized_mode = str(mode or "").strip().lower()
    if not normalized_mode:
        normalized_mode = (
            TABULAR_TRANSFORMATION_FIELD_MODE_DETERMINISTIC
            if expression is not None
            else TABULAR_TRANSFORMATION_FIELD_MODE_SEMANTIC
        )
    if normalized_mode not in TABULAR_TRANSFORMATION_FIELD_MODES:
        raise TabularTransformationSpecError("Tabular transformation field mode is unsupported")
    return normalized_mode


def _validate_literal_value(value, depth=0, budget=None):
    if budget is not None:
        budget.consume_step(depth)
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        if budget is not None:
            try:
                _parse_decimal_value(value, precise=True)
            except TabularTransformationEvaluationError as exc:
                raise TabularTransformationSpecError("Tabular transformation literal number exceeds numeric limits") from exc
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise TabularTransformationSpecError("Tabular transformation literal number is not finite")
        if budget is not None:
            try:
                _parse_decimal_value(value, precise=True)
            except TabularTransformationEvaluationError as exc:
                raise TabularTransformationSpecError("Tabular transformation literal number exceeds numeric limits") from exc
        return value
    if isinstance(value, str):
        if len(value) > TABULAR_TRANSFORMATION_MAX_STRING_LENGTH:
            raise TabularTransformationSpecError("Tabular transformation literal string is too long")
        return value
    if isinstance(value, list):
        if len(value) > TABULAR_TRANSFORMATION_MAX_LIST_ITEMS:
            raise TabularTransformationSpecError("Tabular transformation literal list is too large")
        return [_validate_literal_value(item, depth=depth + 1, budget=budget) for item in value]
    if isinstance(value, dict):
        if len(value) > TABULAR_TRANSFORMATION_MAX_LIST_ITEMS:
            raise TabularTransformationSpecError("Tabular transformation literal object is too large")
        normalized_object = {}
        for key, item in value.items():
            normalized_key = str(key or "").strip()
            if not normalized_key or len(normalized_key) > TABULAR_TRANSFORMATION_MAX_FIELD_NAME_LENGTH:
                raise TabularTransformationSpecError("Tabular transformation literal object key is invalid")
            normalized_object[normalized_key] = _validate_literal_value(item, depth=depth + 1, budget=budget)
        return normalized_object
    raise TabularTransformationSpecError("Tabular transformation literal type is unsupported")


def _normalize_reference_name(expression, key_name):
    return _normalize_field_name(expression.get(key_name), label=key_name)


def _normalize_value_type(value_type):
    normalized_type = str(value_type or "").strip().lower()
    if normalized_type not in {"", "string", "number", "integer", "date", "boolean"}:
        raise TabularTransformationSpecError("Tabular transformation value type is unsupported")
    return normalized_type


def _normalize_field_type(value_type):
    normalized_type = str(value_type or "").strip().lower()
    if normalized_type not in {"", "string", "number", "integer", "date", "boolean", "object", "array"}:
        raise TabularTransformationSpecError("Tabular transformation field type is unsupported")
    return normalized_type


def _normalize_expression(expression, depth=0, version=TABULAR_TRANSFORMATION_SPEC_VERSION, budget=None):
    if depth > TABULAR_TRANSFORMATION_MAX_EXPRESSION_DEPTH:
        raise TabularTransformationSpecError("Tabular transformation expression is too deep")
    if budget is not None:
        budget.consume_step(depth)
    if not isinstance(expression, dict):
        return _validate_literal_value(expression, depth=depth, budget=budget)

    def normalize_child(value):
        return _normalize_expression(value, depth=depth + 1, version=version, budget=budget)

    if "source" in expression and set(expression) == {"source"}:
        return {"source": _normalize_reference_name(expression, "source")}
    if "field" in expression and set(expression) == {"field"}:
        return {"field": _normalize_reference_name(expression, "field")}
    if "value" in expression and set(expression) == {"value"}:
        return {"value": _validate_literal_value(expression.get("value"), depth=depth + 1, budget=budget)}

    op_name = str(expression.get("op") or "").strip().lower()
    precise = version == TABULAR_TRANSFORMATION_PRECISE_SPEC_VERSION
    if op_name not in TABULAR_TRANSFORMATION_ALLOWED_OPS and not (precise and op_name == "round"):
        raise TabularTransformationSpecError("Tabular transformation expression operation is unsupported")

    if op_name == "round":
        if set(expression) != {"op", "value", "scale", "mode"}:
            raise TabularTransformationSpecError("Tabular transformation round expression has invalid properties")
        scale = expression.get("scale")
        if isinstance(scale, bool) or not isinstance(scale, int) or not 0 <= scale <= TABULAR_TRANSFORMATION_MAX_ROUND_SCALE:
            raise TabularTransformationSpecError("Tabular transformation round scale is unsupported")
        rounding_mode = str(expression.get("mode") or "").strip().lower()
        if rounding_mode not in TABULAR_TRANSFORMATION_ROUNDING_MODES:
            raise TabularTransformationSpecError("Tabular transformation rounding mode is unsupported")
        return {
            "op": op_name,
            "value": normalize_child(expression.get("value")),
            "scale": scale,
            "mode": rounding_mode,
        }

    if op_name == "copy":
        if set(expression) != {"op", "source"}:
            raise TabularTransformationSpecError("Tabular transformation copy expression has invalid properties")
        return {"op": op_name, "source": _normalize_reference_name(expression, "source")}

    if op_name == "case":
        if set(expression) != {"op", "branches", "else"}:
            raise TabularTransformationSpecError("Tabular transformation case expression has invalid properties")
        branches = expression.get("branches")
        if not isinstance(branches, list) or not branches:
            raise TabularTransformationSpecError("Tabular transformation case expression requires branches")
        if len(branches) > TABULAR_TRANSFORMATION_MAX_BRANCHES:
            raise TabularTransformationSpecError("Tabular transformation case expression has too many branches")
        normalized_branches = []
        for branch in branches:
            if not isinstance(branch, dict) or set(branch) != {"when", "then"}:
                raise TabularTransformationSpecError("Tabular transformation case branch is invalid")
            normalized_branches.append({
                "when": normalize_child(branch.get("when")),
                "then": normalize_child(branch.get("then")),
            })
        return {
            "op": op_name,
            "branches": normalized_branches,
            "else": normalize_child(expression.get("else")),
        }

    if op_name == "coalesce":
        if set(expression) != {"op", "values"}:
            raise TabularTransformationSpecError("Tabular transformation coalesce expression has invalid properties")
        values = expression.get("values")
        if not isinstance(values, list) or not values:
            raise TabularTransformationSpecError("Tabular transformation coalesce expression requires values")
        if len(values) > TABULAR_TRANSFORMATION_MAX_LIST_ITEMS:
            raise TabularTransformationSpecError("Tabular transformation coalesce expression has too many values")
        return {
            "op": op_name,
            "values": [normalize_child(value) for value in values],
        }

    if op_name in {"all", "any"}:
        if set(expression) != {"op", "values"}:
            raise TabularTransformationSpecError("Tabular transformation boolean expression has invalid properties")
        values = expression.get("values")
        if not isinstance(values, list) or not values:
            raise TabularTransformationSpecError("Tabular transformation boolean expression requires values")
        if len(values) > TABULAR_TRANSFORMATION_MAX_LIST_ITEMS:
            raise TabularTransformationSpecError("Tabular transformation boolean expression has too many values")
        return {
            "op": op_name,
            "values": [normalize_child(value) for value in values],
        }

    if op_name == "not":
        if set(expression) != {"op", "value"}:
            raise TabularTransformationSpecError("Tabular transformation not expression has invalid properties")
        return {"op": op_name, "value": normalize_child(expression.get("value"))}

    if op_name == "is_null":
        if set(expression) != {"op", "value"}:
            raise TabularTransformationSpecError("Tabular transformation null expression has invalid properties")
        return {"op": op_name, "value": normalize_child(expression.get("value"))}

    if op_name == "in":
        allowed_keys = {"op", "value", "values", "case_sensitive"}
        if set(expression) - allowed_keys or not {"value", "values"}.issubset(expression):
            raise TabularTransformationSpecError("Tabular transformation membership expression has invalid properties")
        values = expression.get("values")
        if not isinstance(values, list) or len(values) > TABULAR_TRANSFORMATION_MAX_LIST_ITEMS:
            raise TabularTransformationSpecError("Tabular transformation membership expression values are invalid")
        return {
            "op": op_name,
            "value": normalize_child(expression.get("value")),
            "values": [normalize_child(value) for value in values],
            "case_sensitive": bool(expression.get("case_sensitive", True)),
        }

    if op_name in TABULAR_TRANSFORMATION_COMPARISON_OPS:
        allowed_keys = {"op", "left", "right", "value_type", "case_sensitive"}
        if set(expression) - allowed_keys or not {"left", "right"}.issubset(expression):
            raise TabularTransformationSpecError("Tabular transformation comparison expression has invalid properties")
        return {
            "op": op_name,
            "left": normalize_child(expression.get("left")),
            "right": normalize_child(expression.get("right")),
            "value_type": _normalize_value_type(expression.get("value_type")),
            "case_sensitive": bool(expression.get("case_sensitive", True)),
        }

    if op_name in TABULAR_TRANSFORMATION_ARITHMETIC_OPS:
        allowed_keys = {"op", "values", "left", "right"}
        if set(expression) - allowed_keys:
            raise TabularTransformationSpecError("Tabular transformation arithmetic expression has invalid properties")
        if "values" in expression:
            if precise and set(expression) != {"op", "values"}:
                raise TabularTransformationSpecError("Tabular transformation arithmetic operands are ambiguous")
            values = expression.get("values")
            if not isinstance(values, list) or not values:
                raise TabularTransformationSpecError("Tabular transformation arithmetic values are invalid")
            if len(values) > TABULAR_TRANSFORMATION_MAX_LIST_ITEMS:
                raise TabularTransformationSpecError("Tabular transformation arithmetic expression has too many values")
            return {
                "op": op_name,
                "values": [normalize_child(value) for value in values],
            }
        if not {"left", "right"}.issubset(expression):
            raise TabularTransformationSpecError("Tabular transformation arithmetic expression requires operands")
        return {
            "op": op_name,
            "left": normalize_child(expression.get("left")),
            "right": normalize_child(expression.get("right")),
        }

    raise TabularTransformationSpecError("Tabular transformation expression operation is unsupported")


def _collect_expression_references(expression, source_refs, field_refs):
    if not isinstance(expression, dict):
        return
    if set(expression) == {"source"}:
        source_refs.add(expression["source"])
        return
    if set(expression) == {"field"}:
        field_refs.add(expression["field"])
        return
    if set(expression) == {"value"}:
        return

    op_name = expression.get("op")
    if op_name == "copy":
        source_refs.add(expression["source"])
    elif op_name == "case":
        for branch in expression.get("branches") or []:
            _collect_expression_references(branch.get("when"), source_refs, field_refs)
            _collect_expression_references(branch.get("then"), source_refs, field_refs)
        _collect_expression_references(expression.get("else"), source_refs, field_refs)
    elif op_name in {"coalesce", "all", "any"}:
        for value in expression.get("values") or []:
            _collect_expression_references(value, source_refs, field_refs)
    elif op_name in {"not", "is_null", "round"}:
        _collect_expression_references(expression.get("value"), source_refs, field_refs)
    elif op_name == "in":
        _collect_expression_references(expression.get("value"), source_refs, field_refs)
        for value in expression.get("values") or []:
            _collect_expression_references(value, source_refs, field_refs)
    elif op_name in TABULAR_TRANSFORMATION_COMPARISON_OPS:
        _collect_expression_references(expression.get("left"), source_refs, field_refs)
        _collect_expression_references(expression.get("right"), source_refs, field_refs)
    elif op_name in TABULAR_TRANSFORMATION_ARITHMETIC_OPS:
        if "values" in expression:
            for value in expression.get("values") or []:
                _collect_expression_references(value, source_refs, field_refs)
        else:
            _collect_expression_references(expression.get("left"), source_refs, field_refs)
            _collect_expression_references(expression.get("right"), source_refs, field_refs)


def _normalize_field_descriptor(field_descriptor, version=TABULAR_TRANSFORMATION_SPEC_VERSION, budget=None):
    if not isinstance(field_descriptor, dict):
        raise TabularTransformationSpecError("Tabular transformation field descriptor is invalid")
    allowed_keys = {"name", "mode", "expression", "type", "nullable", "allowed_values"}
    if set(field_descriptor) - allowed_keys:
        raise TabularTransformationSpecError("Tabular transformation field descriptor has unsupported properties")

    field_name = _normalize_field_name(field_descriptor.get("name"))
    expression_present = "expression" in field_descriptor
    mode = _normalize_mode(field_descriptor.get("mode"), expression=field_descriptor.get("expression"))
    expression = None
    if mode == TABULAR_TRANSFORMATION_FIELD_MODE_DETERMINISTIC:
        if not expression_present:
            raise TabularTransformationSpecError("Deterministic tabular transformation field requires an expression")
        expression = _normalize_expression(field_descriptor.get("expression"), version=version, budget=budget)
    elif expression_present and field_descriptor.get("expression") not in ({}, None):
        expression = _normalize_expression(field_descriptor.get("expression"), version=version, budget=budget)

    normalized_descriptor = {
        "name": field_name,
        "mode": mode,
    }
    if expression is not None or (
        version == TABULAR_TRANSFORMATION_PRECISE_SPEC_VERSION
        and mode == TABULAR_TRANSFORMATION_FIELD_MODE_DETERMINISTIC
    ):
        normalized_descriptor["expression"] = expression
    field_type = _normalize_field_type(field_descriptor.get("type"))
    if field_type:
        normalized_descriptor["type"] = field_type
    if "nullable" in field_descriptor:
        normalized_descriptor["nullable"] = bool(field_descriptor.get("nullable"))
    if "allowed_values" in field_descriptor:
        allowed_values = field_descriptor.get("allowed_values")
        if not isinstance(allowed_values, list) or len(allowed_values) > TABULAR_TRANSFORMATION_MAX_LIST_ITEMS:
            raise TabularTransformationSpecError("Tabular transformation allowed values are invalid")
        normalized_descriptor["allowed_values"] = [_validate_literal_value(value, budget=budget) for value in allowed_values]
        if budget is not None and field_type in {"number", "integer"}:
            for value in allowed_values:
                if value is not None:
                    try:
                        _parse_decimal_value(value, precise=True)
                    except TabularTransformationEvaluationError as exc:
                        raise TabularTransformationSpecError("Tabular transformation allowed numeric value is invalid") from exc
    return normalized_descriptor


def _build_deterministic_field_order(field_descriptors):
    fields_by_name = {field["name"]: field for field in field_descriptors}
    graph = {}
    for field in field_descriptors:
        if field["mode"] != TABULAR_TRANSFORMATION_FIELD_MODE_DETERMINISTIC:
            continue
        source_refs = set()
        field_refs = set()
        _collect_expression_references(field.get("expression"), source_refs, field_refs)
        deterministic_dependencies = set()
        for field_ref in field_refs:
            referenced_field = fields_by_name.get(field_ref)
            if referenced_field is None:
                continue
            if referenced_field["mode"] != TABULAR_TRANSFORMATION_FIELD_MODE_DETERMINISTIC:
                raise TabularTransformationSpecError(
                    "Deterministic tabular transformation field cannot depend on semantic output"
                )
            deterministic_dependencies.add(field_ref)
        graph[field["name"]] = deterministic_dependencies
    try:
        return list(TopologicalSorter(graph).static_order())
    except CycleError as exc:
        raise TabularTransformationSpecError("Tabular transformation field dependencies contain a cycle") from exc


def normalize_tabular_transformation_spec(
    transformation_spec,
    public_output_schema=None,
    source_schema=None,
):
    """Return a bounded normalized transformation spec or an empty spec."""
    if not transformation_spec:
        return {}
    if not isinstance(transformation_spec, dict):
        raise TabularTransformationSpecError("Tabular transformation spec must be an object")
    allowed_keys = {"version", "fields", "deterministic_field_order", "field_mode_counts"}
    if set(transformation_spec) - allowed_keys:
        raise TabularTransformationSpecError("Tabular transformation spec has unsupported properties")
    version = str(transformation_spec.get("version") or "").strip()
    if version not in TABULAR_TRANSFORMATION_SPEC_VERSIONS:
        raise TabularTransformationSpecError("Tabular transformation spec version is unsupported")

    normalized_public_schema = _normalize_field_list(public_output_schema, label="public output field")
    normalized_source_schema = _normalize_field_list(source_schema, label="source field")
    source_schema_set = set(normalized_source_schema)

    raw_fields = transformation_spec.get("fields")
    if not isinstance(raw_fields, list) or not raw_fields:
        raise TabularTransformationSpecError("Tabular transformation spec requires fields")
    if len(raw_fields) > TABULAR_TRANSFORMATION_MAX_FIELDS:
        raise TabularTransformationSpecError("Tabular transformation spec has too many fields")

    normalized_fields = []
    seen_fields = set()
    budget = _SpecValidationBudget() if version == TABULAR_TRANSFORMATION_PRECISE_SPEC_VERSION else None
    for raw_field in raw_fields:
        normalized_field = _normalize_field_descriptor(raw_field, version=version, budget=budget)
        field_name = normalized_field["name"]
        if field_name in seen_fields:
            raise TabularTransformationSpecError("Tabular transformation spec contains duplicate output fields")
        seen_fields.add(field_name)
        normalized_fields.append(normalized_field)

    if normalized_public_schema:
        public_schema_set = set(normalized_public_schema)
        if seen_fields != public_schema_set:
            raise TabularTransformationSpecError("Tabular transformation spec fields must match the public schema")

    for normalized_field in normalized_fields:
        source_refs = set()
        field_refs = set()
        _collect_expression_references(normalized_field.get("expression"), source_refs, field_refs)
        if source_schema_set and source_refs - source_schema_set:
            raise TabularTransformationSpecError("Tabular transformation spec references an unknown source field")
        unknown_field_refs = field_refs - seen_fields
        if unknown_field_refs:
            raise TabularTransformationSpecError("Tabular transformation spec references an unknown output field")

    deterministic_order = _build_deterministic_field_order(normalized_fields)
    mode_counts = {
        mode: sum(1 for field in normalized_fields if field["mode"] == mode)
        for mode in sorted(TABULAR_TRANSFORMATION_FIELD_MODES)
    }
    return {
        "version": version,
        "fields": normalized_fields,
        "deterministic_field_order": deterministic_order,
        "field_mode_counts": mode_counts,
    }


def get_tabular_transformation_deterministic_fields(transformation_spec):
    """Return deterministic output field names in evaluation order."""
    normalized_spec = normalize_tabular_transformation_spec(transformation_spec)
    return list(normalized_spec.get("deterministic_field_order") or [])


def get_tabular_transformation_model_fields(transformation_spec, public_output_schema=None):
    """Return public fields that must still be generated or verified by the model."""
    normalized_spec = normalize_tabular_transformation_spec(
        transformation_spec,
        public_output_schema=public_output_schema,
    )
    if not normalized_spec:
        return list(public_output_schema or [])
    deterministic_fields = set(normalized_spec.get("deterministic_field_order") or [])
    ordered_public_schema = list(public_output_schema or [field["name"] for field in normalized_spec["fields"]])
    return [field_name for field_name in ordered_public_schema if field_name not in deterministic_fields]


def is_tabular_transformation_deterministic_only(transformation_spec, public_output_schema=None):
    """Return True when every public field is server-computable."""
    normalized_spec = normalize_tabular_transformation_spec(
        transformation_spec,
        public_output_schema=public_output_schema,
    )
    if not normalized_spec:
        return False
    return not get_tabular_transformation_model_fields(normalized_spec, public_output_schema=public_output_schema)


def _parse_date_value(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    normalized_value = str(value or "").strip()
    if not normalized_value:
        raise TabularTransformationEvaluationError("Date value is empty")
    try:
        return date.fromisoformat(normalized_value[:10])
    except ValueError as exc:
        raise TabularTransformationEvaluationError("Date value is not ISO formatted") from exc


def _validate_precise_decimal(value):
    if not value.is_finite():
        raise TabularTransformationEvaluationError("Numeric value is not finite")
    if value.copy_abs() > TABULAR_TRANSFORMATION_MAX_NUMERIC_ABS:
        raise TabularTransformationEvaluationError("Numeric value exceeds the bounded range")
    parts = value.as_tuple()
    if (
        len(parts.digits) > TABULAR_TRANSFORMATION_DECIMAL_PRECISION
        or abs(parts.exponent) > TABULAR_TRANSFORMATION_MAX_DECIMAL_EXPONENT
    ):
        raise TabularTransformationEvaluationError("Numeric value exceeds the bounded decimal precision or exponent")
    return value


def _parse_decimal_value(value, precise=False):
    if isinstance(value, bool) or value in (None, ""):
        raise TabularTransformationEvaluationError("Numeric value is empty or boolean")
    if precise:
        if not isinstance(value, (str, int, float, Decimal)):
            raise TabularTransformationEvaluationError("Numeric value has an unsupported type")
        if isinstance(value, int) and abs(value) > TABULAR_TRANSFORMATION_MAX_NUMERIC_ABS:
            raise TabularTransformationEvaluationError("Numeric value exceeds the bounded range")
        if isinstance(value, str):
            if len(value) > TABULAR_TRANSFORMATION_MAX_NUMERIC_TEXT_LENGTH:
                raise TabularTransformationEvaluationError("Numeric value exceeds the bounded text length")
            if not _DECIMAL_TEXT_PATTERN.fullmatch(value.strip()):
                raise TabularTransformationEvaluationError("Numeric value is invalid")
    try:
        parsed_value = value if isinstance(value, Decimal) else Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise TabularTransformationEvaluationError("Numeric value is invalid") from exc
    if not parsed_value.is_finite():
        raise TabularTransformationEvaluationError("Numeric value is not finite")
    if parsed_value.copy_abs() > TABULAR_TRANSFORMATION_MAX_NUMERIC_ABS:
        raise TabularTransformationEvaluationError("Numeric value exceeds the bounded range")
    if precise:
        return _validate_precise_decimal(parsed_value)
    return parsed_value


def _coerce_comparison_value(value, value_type, precise=False):
    if value_type == "date":
        return _parse_date_value(value)
    if value_type in {"number", "integer"}:
        return _parse_decimal_value(value, precise=precise)
    if value_type == "boolean":
        if isinstance(value, bool):
            return value
        normalized_value = str(value or "").strip().lower()
        if normalized_value in {"true", "1", "yes", "y"}:
            return True
        if normalized_value in {"false", "0", "no", "n"}:
            return False
        raise TabularTransformationEvaluationError("Boolean value is invalid")
    return value


def _decimal_to_json_value(value, precise=False):
    if value == value.to_integral_value():
        if precise and value.copy_abs() > TABULAR_TRANSFORMATION_MAX_JSON_INTEGER:
            raise TabularTransformationEvaluationError(
                "Numeric result exceeds the interoperable JSON integer range; use a string field"
            )
        return int(value)
    projected_value = float(value)
    if precise and (not math.isfinite(projected_value) or Decimal(str(projected_value)) != value):
        raise TabularTransformationEvaluationError(
            "Numeric result cannot be represented in JSON without precision loss; declare rounding or a string field"
        )
    return projected_value


def _compare_values(left_value, right_value, op_name, value_type="", case_sensitive=True, precise=False):
    coerced_left = _coerce_comparison_value(left_value, value_type, precise=precise)
    coerced_right = _coerce_comparison_value(right_value, value_type, precise=precise)
    if precise and not value_type:
        numeric_types = (int, float, Decimal)
        if (
            isinstance(coerced_left, numeric_types)
            and isinstance(coerced_right, numeric_types)
            and not (isinstance(coerced_left, bool) and isinstance(coerced_right, bool))
        ):
            coerced_left = _parse_decimal_value(coerced_left, precise=True)
            coerced_right = _parse_decimal_value(coerced_right, precise=True)
    if value_type in {"", "string"} and isinstance(coerced_left, str) and isinstance(coerced_right, str):
        if not case_sensitive:
            coerced_left = coerced_left.casefold()
            coerced_right = coerced_right.casefold()
    try:
        if op_name == "eq":
            return coerced_left == coerced_right
        if op_name == "ne":
            return coerced_left != coerced_right
        if op_name == "lt":
            return coerced_left < coerced_right
        if op_name == "lte":
            return coerced_left <= coerced_right
        if op_name == "gt":
            return coerced_left > coerced_right
        if op_name == "gte":
            return coerced_left >= coerced_right
    except TypeError as exc:
        raise TabularTransformationEvaluationError("Comparison operands have incompatible types") from exc
    raise TabularTransformationEvaluationError("Comparison operation is unsupported")


def _is_empty_value(value):
    return value is None or value == "" or value == [] or value == {}


class _EvaluationContext:
    def __init__(self, source_row, derived_values, version=TABULAR_TRANSFORMATION_SPEC_VERSION):
        self.source_row = source_row if isinstance(source_row, dict) else {}
        self.derived_values = derived_values
        self.precise = version == TABULAR_TRANSFORMATION_PRECISE_SPEC_VERSION
        self.step_count = 0

    def prepare_value(self, value):
        if self.precise and isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
            return _parse_decimal_value(value, precise=True)
        return value

    def consume_step(self):
        self.step_count += 1
        if self.step_count > TABULAR_TRANSFORMATION_MAX_EXPRESSION_STEPS:
            raise TabularTransformationEvaluationError("Transformation evaluation exceeded the step limit")


def _evaluate_numeric_operands(expression, context):
    operands = (
        expression["values"]
        if "values" in expression
        else [expression.get("left"), expression.get("right")]
    )
    return [
        _parse_decimal_value(_evaluate_expression(value, context), precise=context.precise)
        for value in operands
    ]


def _evaluate_precise_arithmetic(op_name, numeric_values):
    result = numeric_values[0]
    for value in numeric_values[1:]:
        if op_name == "add":
            result += value
        elif op_name == "subtract":
            result -= value
        elif op_name == "multiply":
            result *= value
        else:
            if value == 0:
                raise TabularTransformationEvaluationError("Division by zero is not allowed")
            result /= value
        _validate_precise_decimal(result)
    return result


def _evaluate_rounded_division(expression, context, scale, rounding_mode):
    """Round a direct quotient exactly, including non-terminating divisions."""
    context.consume_step()
    numeric_values = _evaluate_numeric_operands(expression, context)
    quotient = Fraction(numeric_values[0])
    negative = numeric_values[0].is_signed()
    for value in numeric_values[1:]:
        if value == 0:
            raise TabularTransformationEvaluationError("Division by zero is not allowed")
        quotient /= Fraction(value)
        negative ^= value.is_signed()
        if max(quotient.numerator.bit_length(), quotient.denominator.bit_length()) > TABULAR_TRANSFORMATION_MAX_ROUND_RATIO_BITS:
            raise TabularTransformationEvaluationError("Rounded division exceeds the bounded precision work limit")
        if abs(quotient) > int(TABULAR_TRANSFORMATION_MAX_NUMERIC_ABS):
            raise TabularTransformationEvaluationError("Numeric result exceeds the bounded range")

    units, remainder = divmod(abs(quotient.numerator) * (10 ** scale), quotient.denominator)
    tie = remainder * 2 == quotient.denominator
    if remainder * 2 > quotient.denominator or (tie and (rounding_mode == "half_up" or units % 2)):
        units += 1
    result = Decimal(units).scaleb(-scale)
    if negative:
        result = result.copy_negate()
    return _validate_precise_decimal(result)


def _evaluate_round_expression(expression, context):
    value_expression = expression["value"]
    scale = expression["scale"]
    rounding_mode = expression["mode"]
    if isinstance(value_expression, dict) and value_expression.get("op") == "divide":
        return _evaluate_rounded_division(value_expression, context, scale, rounding_mode)
    value = _parse_decimal_value(_evaluate_expression(value_expression, context), precise=True)
    with localcontext(_PRECISE_DECIMAL_CONTEXT) as rounding_context:
        rounding_context.traps[Inexact] = False
        result = value.quantize(Decimal((0, (1,), -scale)), rounding=TABULAR_TRANSFORMATION_ROUNDING_MODES[rounding_mode])
    return _validate_precise_decimal(result)


def _evaluate_expression(expression, context):
    context.consume_step()
    if not isinstance(expression, dict):
        return context.prepare_value(expression)
    if set(expression) == {"source"}:
        return context.prepare_value(context.source_row.get(expression["source"]))
    if set(expression) == {"field"}:
        field_name = expression["field"]
        if field_name not in context.derived_values:
            raise TabularTransformationEvaluationError("Referenced derived field has not been evaluated")
        return context.prepare_value(context.derived_values.get(field_name))
    if set(expression) == {"value"}:
        return context.prepare_value(expression.get("value"))

    op_name = expression.get("op")
    if op_name == "copy":
        return context.prepare_value(context.source_row.get(expression["source"]))
    if op_name == "round" and context.precise:
        return _evaluate_round_expression(expression, context)
    if op_name == "case":
        for branch in expression.get("branches") or []:
            if bool(_evaluate_expression(branch.get("when"), context)):
                return _evaluate_expression(branch.get("then"), context)
        return _evaluate_expression(expression.get("else"), context)
    if op_name == "coalesce":
        for value_expression in expression.get("values") or []:
            value = _evaluate_expression(value_expression, context)
            if not _is_empty_value(value):
                return value
        return None
    if op_name == "all":
        return all(bool(_evaluate_expression(value_expression, context)) for value_expression in expression.get("values") or [])
    if op_name == "any":
        return any(bool(_evaluate_expression(value_expression, context)) for value_expression in expression.get("values") or [])
    if op_name == "not":
        return not bool(_evaluate_expression(expression.get("value"), context))
    if op_name == "is_null":
        return _is_empty_value(_evaluate_expression(expression.get("value"), context))
    if op_name == "in":
        member_value = _evaluate_expression(expression.get("value"), context)
        expected_values = [_evaluate_expression(value, context) for value in expression.get("values") or []]
        if not expression.get("case_sensitive", True) and isinstance(member_value, str):
            member_value = member_value.casefold()
            expected_values = [value.casefold() if isinstance(value, str) else value for value in expected_values]
        if context.precise:
            return any(_compare_values(member_value, value, "eq", precise=True) for value in expected_values)
        return member_value in expected_values
    if op_name in TABULAR_TRANSFORMATION_COMPARISON_OPS:
        return _compare_values(
            _evaluate_expression(expression.get("left"), context),
            _evaluate_expression(expression.get("right"), context),
            op_name,
            value_type=expression.get("value_type") or "",
            case_sensitive=expression.get("case_sensitive", True),
            precise=context.precise,
        )
    if op_name in TABULAR_TRANSFORMATION_ARITHMETIC_OPS:
        numeric_values = _evaluate_numeric_operands(expression, context)
        if context.precise:
            return _evaluate_precise_arithmetic(op_name, numeric_values)
        if op_name == "add":
            result = sum(numeric_values, Decimal("0"))
        elif op_name == "subtract":
            result = numeric_values[0]
            for value in numeric_values[1:]:
                result -= value
        elif op_name == "multiply":
            result = Decimal("1")
            for value in numeric_values:
                result *= value
        else:
            result = numeric_values[0]
            for value in numeric_values[1:]:
                if value == 0:
                    raise TabularTransformationEvaluationError("Division by zero is not allowed")
                result /= value
        if abs(result) > TABULAR_TRANSFORMATION_MAX_NUMERIC_ABS:
            raise TabularTransformationEvaluationError("Numeric result exceeds the bounded range")
        return _decimal_to_json_value(result)
    raise TabularTransformationEvaluationError("Transformation operation is unsupported")


def _validate_evaluated_field_value(field_descriptor, field_value, precise=False):
    if field_value is None:
        if field_descriptor.get("nullable") is False:
            raise TabularTransformationEvaluationError("Non-nullable deterministic field evaluated to null")
        return None
    field_type = str(field_descriptor.get("type") or "").strip().lower()
    if field_type == "string" and not isinstance(field_value, str):
        field_value = str(field_value)
    elif field_type == "integer":
        parsed_value = _parse_decimal_value(field_value, precise=precise)
        if parsed_value != parsed_value.to_integral_value():
            raise TabularTransformationEvaluationError("Deterministic integer field evaluated to a fractional value")
        field_value = parsed_value if precise else int(parsed_value)
    elif field_type == "number":
        parsed_value = _parse_decimal_value(field_value, precise=precise)
        field_value = parsed_value if precise else _decimal_to_json_value(parsed_value)
    elif field_type == "boolean" and not isinstance(field_value, bool):
        field_value = _coerce_comparison_value(field_value, "boolean")
    elif field_type == "date":
        field_value = _parse_date_value(field_value).isoformat()
    elif field_type == "object" and not isinstance(field_value, dict):
        raise TabularTransformationEvaluationError("Deterministic object field evaluated to a non-object value")
    elif field_type == "array" and not isinstance(field_value, list):
        raise TabularTransformationEvaluationError("Deterministic array field evaluated to a non-array value")
    allowed_values = field_descriptor.get("allowed_values")
    if allowed_values is not None:
        if precise:
            matches_allowed_value = any(
                _compare_values(
                    field_value,
                    value,
                    "eq",
                    value_type=field_type if field_type in {"number", "integer"} else "",
                    precise=True,
                )
                for value in allowed_values
                if value is not None
            )
        else:
            matches_allowed_value = field_value in allowed_values
        if not matches_allowed_value:
            raise TabularTransformationEvaluationError("Deterministic field evaluated outside allowed values")
    return field_value


def _project_precise_public_value(value, context, depth=0):
    context.consume_step()
    if depth > TABULAR_TRANSFORMATION_MAX_EXPRESSION_DEPTH:
        raise TabularTransformationEvaluationError("Public transformation value is too deep")
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float, Decimal)):
        return _decimal_to_json_value(_parse_decimal_value(value, precise=True), precise=True)
    if isinstance(value, str):
        if len(value) > TABULAR_TRANSFORMATION_MAX_STRING_LENGTH:
            raise TabularTransformationEvaluationError("Public transformation string is too long")
        return value
    if isinstance(value, (dict, list)):
        if len(value) > TABULAR_TRANSFORMATION_MAX_LIST_ITEMS:
            raise TabularTransformationEvaluationError("Public transformation collection is too large")
        if isinstance(value, list):
            return [_project_precise_public_value(item, context, depth=depth + 1) for item in value]
        projected_value = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key or len(key) > TABULAR_TRANSFORMATION_MAX_FIELD_NAME_LENGTH:
                raise TabularTransformationEvaluationError("Public transformation object key is invalid")
            projected_value[key] = _project_precise_public_value(item, context, depth=depth + 1)
        return projected_value
    raise TabularTransformationEvaluationError("Public transformation value is not JSON compatible")


def evaluate_tabular_transformation_row(transformation_spec, source_row):
    """Evaluate deterministic fields, projecting v2 decimals only after dependencies.

    V2 arithmetic must be exact within 64 coefficient digits and an exponent
    magnitude of 128. Non-terminating division requires a directly enclosing
    ``round`` node; other inexact arithmetic fails rather than guessing a rule.
    Numeric JSON output must round-trip through its float decimal text, and
    integers must be within the interoperable 53-bit range. An explicit string
    field preserves decimal text when numeric projection is not representable.
    Supply decimal strings when input precision matters: existing floats are
    interpreted through their decimal text, not recovered to their original value.
    """
    normalized_spec = normalize_tabular_transformation_spec(transformation_spec)
    if not normalized_spec:
        return {}
    normalized_fields = list(normalized_spec.get("fields") or [])
    fields_by_name = {field["name"]: field for field in normalized_fields}
    derived_values = {}
    context = _EvaluationContext(source_row, derived_values, version=normalized_spec["version"])
    try:
        with localcontext(_PRECISE_DECIMAL_CONTEXT) if context.precise else nullcontext():
            for field_name in normalized_spec.get("deterministic_field_order") or []:
                field_descriptor = fields_by_name[field_name]
                derived_values[field_name] = _validate_evaluated_field_value(
                    field_descriptor,
                    _evaluate_expression(field_descriptor.get("expression"), context),
                    precise=context.precise,
                )
            return {
                field["name"]: (
                    _project_precise_public_value(derived_values[field["name"]], context)
                    if context.precise else derived_values[field["name"]]
                )
                for field in normalized_fields
                if field["name"] in derived_values
            }
    except Inexact as exc:
        raise TabularTransformationEvaluationError(
            "Numeric operation is not exact within bounded precision; round a division directly or revise the operands"
        ) from exc
    except DecimalException as exc:
        raise TabularTransformationEvaluationError("Numeric operation exceeds bounded decimal limits") from exc


def evaluate_tabular_transformation_rows(transformation_spec, source_rows):
    """Evaluate deterministic fields for source rows in source order."""
    normalized_spec = normalize_tabular_transformation_spec(transformation_spec)
    return [
        evaluate_tabular_transformation_row(normalized_spec, source_row)
        for source_row in list(source_rows or [])
    ]
