# functions_tabular_transformations.py
"""Bounded transformation specifications for tabular generated outputs."""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from graphlib import CycleError, TopologicalSorter
import math


TABULAR_TRANSFORMATION_SPEC_VERSION = "tabular-transform-v1"
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


class TabularTransformationSpecError(ValueError):
    """Raised when a tabular transformation spec is unsupported or unsafe."""


class TabularTransformationEvaluationError(ValueError):
    """Raised when a valid transformation spec cannot evaluate one row."""


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


def _validate_literal_value(value):
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise TabularTransformationSpecError("Tabular transformation literal number is not finite")
        return value
    if isinstance(value, str):
        if len(value) > TABULAR_TRANSFORMATION_MAX_STRING_LENGTH:
            raise TabularTransformationSpecError("Tabular transformation literal string is too long")
        return value
    if isinstance(value, list):
        if len(value) > TABULAR_TRANSFORMATION_MAX_LIST_ITEMS:
            raise TabularTransformationSpecError("Tabular transformation literal list is too large")
        return [_validate_literal_value(item) for item in value]
    if isinstance(value, dict):
        if len(value) > TABULAR_TRANSFORMATION_MAX_LIST_ITEMS:
            raise TabularTransformationSpecError("Tabular transformation literal object is too large")
        normalized_object = {}
        for key, item in value.items():
            normalized_key = str(key or "").strip()
            if not normalized_key or len(normalized_key) > TABULAR_TRANSFORMATION_MAX_FIELD_NAME_LENGTH:
                raise TabularTransformationSpecError("Tabular transformation literal object key is invalid")
            normalized_object[normalized_key] = _validate_literal_value(item)
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


def _normalize_expression(expression, depth=0):
    if depth > TABULAR_TRANSFORMATION_MAX_EXPRESSION_DEPTH:
        raise TabularTransformationSpecError("Tabular transformation expression is too deep")
    if not isinstance(expression, dict):
        return _validate_literal_value(expression)

    if "source" in expression and set(expression) == {"source"}:
        return {"source": _normalize_reference_name(expression, "source")}
    if "field" in expression and set(expression) == {"field"}:
        return {"field": _normalize_reference_name(expression, "field")}
    if "value" in expression and set(expression) == {"value"}:
        return {"value": _validate_literal_value(expression.get("value"))}

    op_name = str(expression.get("op") or "").strip().lower()
    if op_name not in TABULAR_TRANSFORMATION_ALLOWED_OPS:
        raise TabularTransformationSpecError("Tabular transformation expression operation is unsupported")

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
                "when": _normalize_expression(branch.get("when"), depth=depth + 1),
                "then": _normalize_expression(branch.get("then"), depth=depth + 1),
            })
        return {
            "op": op_name,
            "branches": normalized_branches,
            "else": _normalize_expression(expression.get("else"), depth=depth + 1),
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
            "values": [_normalize_expression(value, depth=depth + 1) for value in values],
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
            "values": [_normalize_expression(value, depth=depth + 1) for value in values],
        }

    if op_name == "not":
        if set(expression) != {"op", "value"}:
            raise TabularTransformationSpecError("Tabular transformation not expression has invalid properties")
        return {"op": op_name, "value": _normalize_expression(expression.get("value"), depth=depth + 1)}

    if op_name == "is_null":
        if set(expression) != {"op", "value"}:
            raise TabularTransformationSpecError("Tabular transformation null expression has invalid properties")
        return {"op": op_name, "value": _normalize_expression(expression.get("value"), depth=depth + 1)}

    if op_name == "in":
        allowed_keys = {"op", "value", "values", "case_sensitive"}
        if set(expression) - allowed_keys or not {"value", "values"}.issubset(expression):
            raise TabularTransformationSpecError("Tabular transformation membership expression has invalid properties")
        values = expression.get("values")
        if not isinstance(values, list) or len(values) > TABULAR_TRANSFORMATION_MAX_LIST_ITEMS:
            raise TabularTransformationSpecError("Tabular transformation membership expression values are invalid")
        return {
            "op": op_name,
            "value": _normalize_expression(expression.get("value"), depth=depth + 1),
            "values": [_normalize_expression(value, depth=depth + 1) for value in values],
            "case_sensitive": bool(expression.get("case_sensitive", True)),
        }

    if op_name in TABULAR_TRANSFORMATION_COMPARISON_OPS:
        allowed_keys = {"op", "left", "right", "value_type", "case_sensitive"}
        if set(expression) - allowed_keys or not {"left", "right"}.issubset(expression):
            raise TabularTransformationSpecError("Tabular transformation comparison expression has invalid properties")
        return {
            "op": op_name,
            "left": _normalize_expression(expression.get("left"), depth=depth + 1),
            "right": _normalize_expression(expression.get("right"), depth=depth + 1),
            "value_type": _normalize_value_type(expression.get("value_type")),
            "case_sensitive": bool(expression.get("case_sensitive", True)),
        }

    if op_name in TABULAR_TRANSFORMATION_ARITHMETIC_OPS:
        allowed_keys = {"op", "values", "left", "right"}
        if set(expression) - allowed_keys:
            raise TabularTransformationSpecError("Tabular transformation arithmetic expression has invalid properties")
        if "values" in expression:
            values = expression.get("values")
            if not isinstance(values, list) or not values:
                raise TabularTransformationSpecError("Tabular transformation arithmetic values are invalid")
            if len(values) > TABULAR_TRANSFORMATION_MAX_LIST_ITEMS:
                raise TabularTransformationSpecError("Tabular transformation arithmetic expression has too many values")
            return {
                "op": op_name,
                "values": [_normalize_expression(value, depth=depth + 1) for value in values],
            }
        if not {"left", "right"}.issubset(expression):
            raise TabularTransformationSpecError("Tabular transformation arithmetic expression requires operands")
        return {
            "op": op_name,
            "left": _normalize_expression(expression.get("left"), depth=depth + 1),
            "right": _normalize_expression(expression.get("right"), depth=depth + 1),
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
    elif op_name in {"not", "is_null"}:
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


def _normalize_field_descriptor(field_descriptor):
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
        expression = _normalize_expression(field_descriptor.get("expression"))
    elif expression_present and field_descriptor.get("expression") not in ({}, None):
        expression = _normalize_expression(field_descriptor.get("expression"))

    normalized_descriptor = {
        "name": field_name,
        "mode": mode,
    }
    if expression is not None:
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
        normalized_descriptor["allowed_values"] = [_validate_literal_value(value) for value in allowed_values]
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
    if str(transformation_spec.get("version") or "").strip() != TABULAR_TRANSFORMATION_SPEC_VERSION:
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
    for raw_field in raw_fields:
        normalized_field = _normalize_field_descriptor(raw_field)
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
        "version": TABULAR_TRANSFORMATION_SPEC_VERSION,
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


def _parse_decimal_value(value):
    if isinstance(value, bool) or value in (None, ""):
        raise TabularTransformationEvaluationError("Numeric value is empty or boolean")
    try:
        parsed_value = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise TabularTransformationEvaluationError("Numeric value is invalid") from exc
    if abs(parsed_value) > TABULAR_TRANSFORMATION_MAX_NUMERIC_ABS:
        raise TabularTransformationEvaluationError("Numeric value exceeds the bounded range")
    return parsed_value


def _coerce_comparison_value(value, value_type):
    if value_type == "date":
        return _parse_date_value(value)
    if value_type in {"number", "integer"}:
        return _parse_decimal_value(value)
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


def _decimal_to_json_value(value):
    if value == value.to_integral_value():
        return int(value)
    return float(value)


def _compare_values(left_value, right_value, op_name, value_type="", case_sensitive=True):
    coerced_left = _coerce_comparison_value(left_value, value_type)
    coerced_right = _coerce_comparison_value(right_value, value_type)
    if value_type in {"", "string"} and isinstance(coerced_left, str) and isinstance(coerced_right, str):
        if not case_sensitive:
            coerced_left = coerced_left.casefold()
            coerced_right = coerced_right.casefold()
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
    raise TabularTransformationEvaluationError("Comparison operation is unsupported")


def _is_empty_value(value):
    return value is None or value == "" or value == [] or value == {}


class _EvaluationContext:
    def __init__(self, source_row, derived_values):
        self.source_row = source_row if isinstance(source_row, dict) else {}
        self.derived_values = derived_values
        self.step_count = 0

    def consume_step(self):
        self.step_count += 1
        if self.step_count > TABULAR_TRANSFORMATION_MAX_EXPRESSION_STEPS:
            raise TabularTransformationEvaluationError("Transformation evaluation exceeded the step limit")


def _evaluate_expression(expression, context):
    context.consume_step()
    if not isinstance(expression, dict):
        return expression
    if set(expression) == {"source"}:
        return context.source_row.get(expression["source"])
    if set(expression) == {"field"}:
        field_name = expression["field"]
        if field_name not in context.derived_values:
            raise TabularTransformationEvaluationError("Referenced derived field has not been evaluated")
        return context.derived_values.get(field_name)
    if set(expression) == {"value"}:
        return expression.get("value")

    op_name = expression.get("op")
    if op_name == "copy":
        return context.source_row.get(expression["source"])
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
        return member_value in expected_values
    if op_name in TABULAR_TRANSFORMATION_COMPARISON_OPS:
        return _compare_values(
            _evaluate_expression(expression.get("left"), context),
            _evaluate_expression(expression.get("right"), context),
            op_name,
            value_type=expression.get("value_type") or "",
            case_sensitive=expression.get("case_sensitive", True),
        )
    if op_name in TABULAR_TRANSFORMATION_ARITHMETIC_OPS:
        if "values" in expression:
            numeric_values = [_parse_decimal_value(_evaluate_expression(value, context)) for value in expression.get("values") or []]
        else:
            numeric_values = [
                _parse_decimal_value(_evaluate_expression(expression.get("left"), context)),
                _parse_decimal_value(_evaluate_expression(expression.get("right"), context)),
            ]
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


def _validate_evaluated_field_value(field_descriptor, field_value):
    if field_value is None:
        if field_descriptor.get("nullable") is False:
            raise TabularTransformationEvaluationError("Non-nullable deterministic field evaluated to null")
        return None
    field_type = str(field_descriptor.get("type") or "").strip().lower()
    if field_type == "string" and not isinstance(field_value, str):
        field_value = str(field_value)
    elif field_type == "integer":
        field_value = int(_parse_decimal_value(field_value))
    elif field_type == "number":
        field_value = _decimal_to_json_value(_parse_decimal_value(field_value))
    elif field_type == "boolean" and not isinstance(field_value, bool):
        field_value = _coerce_comparison_value(field_value, "boolean")
    elif field_type == "date":
        field_value = _parse_date_value(field_value).isoformat()
    elif field_type == "object" and not isinstance(field_value, dict):
        raise TabularTransformationEvaluationError("Deterministic object field evaluated to a non-object value")
    elif field_type == "array" and not isinstance(field_value, list):
        raise TabularTransformationEvaluationError("Deterministic array field evaluated to a non-array value")
    allowed_values = field_descriptor.get("allowed_values")
    if allowed_values is not None and field_value not in allowed_values:
        raise TabularTransformationEvaluationError("Deterministic field evaluated outside allowed values")
    return field_value


def evaluate_tabular_transformation_row(transformation_spec, source_row):
    """Evaluate deterministic fields for one source row."""
    normalized_spec = normalize_tabular_transformation_spec(transformation_spec)
    if not normalized_spec:
        return {}
    normalized_fields = list(normalized_spec.get("fields") or [])
    fields_by_name = {field["name"]: field for field in normalized_fields}
    derived_values = {}
    context = _EvaluationContext(source_row, derived_values)
    for field_name in normalized_spec.get("deterministic_field_order") or []:
        field_descriptor = fields_by_name[field_name]
        derived_values[field_name] = _validate_evaluated_field_value(
            field_descriptor,
            _evaluate_expression(field_descriptor.get("expression"), context),
        )
    return {
        field["name"]: derived_values[field["name"]]
        for field in normalized_fields
        if field["name"] in derived_values
    }


def evaluate_tabular_transformation_rows(transformation_spec, source_rows):
    """Evaluate deterministic fields for source rows in source order."""
    normalized_spec = normalize_tabular_transformation_spec(transformation_spec)
    return [
        evaluate_tabular_transformation_row(normalized_spec, source_row)
        for source_row in list(source_rows or [])
    ]
