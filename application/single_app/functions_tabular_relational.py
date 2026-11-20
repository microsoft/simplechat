# functions_tabular_relational.py
"""Bounded, deterministic relationships over complete tabular sources.

Expressions use the existing precise transformation grammar, never executable
Python or SQL. Source authorization and result persistence belong to the caller.
"""

from collections import defaultdict
from contextlib import contextmanager, nullcontext
from copy import deepcopy
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, DecimalException, InvalidOperation, ROUND_HALF_UP, localcontext
import hashlib
import json
import math
import re

from jsonschema import Draft202012Validator

from functions_tabular_transformations import (
    TabularTransformationEvaluationError,
    TabularTransformationSpecError,
    aggregate_precise_tabular_values,
    evaluate_tabular_transformation_row,
    get_tabular_transformation_model_fields,
    get_tabular_transformation_source_references,
    normalize_tabular_transformation_spec,
    read_formatted_number,
)


RELATIONAL_VERSION = "tabular-relate-v1"
RELATIONAL_VERSION_V2 = "tabular-relate-v2"
MAX_RELATIONAL_STEPS = 32
MAX_RELATIONAL_SOURCES = 100
# What the planner is told about columns and expressions. Both mirror the runtime below and are
# pinned to it by functional tests, so they must change with it.
RELATIONAL_COLUMN_RULES = (
    "Every dataset column is named alias.header. A join outputs the left columns then the right "
    "columns (how=anti outputs only the left) and its two inputs must share no column name; on[].left "
    "and effective.value name left columns, on[].right and effective.start/end name right columns. "
    "filter keeps its input columns. derive keeps its input columns and adds stepid.field for every "
    "transform field. project replaces all columns with stepid.field. aggregate outputs only "
    "stepid.name for each by/measures name. A step may use only the columns its input has, and output "
    "may use only the result step's columns, so a column dropped by project or aggregate cannot be "
    "used later. allocate preserves both inputs and adds stepid.allocated_amount and "
    "stepid.allocation_status; cumulative_sum preserves its input and adds stepid.cumulative_value "
    "and stepid.cumulative_status. Shared-ancestor branches may rejoin only after their output column namespaces are "
    "provably disjoint, usually through project or aggregate. Aggregated sum/min/max values are "
    "decimal strings."
)
RELATIONAL_EXPRESSION_GRAMMAR = (
    "Expressions (filter predicate, transform and output fields) are deterministic "
    "tabular-transform-v2: a literal, {\"source\":\"alias.header\"} for a column of the step input, "
    "{\"field\":\"name\"} for an earlier field of the same transform, {\"value\":literal}, or an object "
    "with exactly these keys: copy{op,source}; round{op,value,scale 0-12,mode half_up|half_even}; "
    "case{op,branches:[{when,then}],else}; coalesce{op,values}; all|any{op,values}; not|is_null{op,value}; "
    "in{op,value,values,case_sensitive?}; eq|ne|lt|lte|gt|gte{op,left,right,value_type?,case_sensitive?}; "
    "add|subtract|multiply|divide{op,values} or {op,left,right}. Operands nest with the same grammar. "
    "Arithmetic on an empty or boolean operand fails, so guard it with coalesce or case with is_null. "
    "A numeric operand is a number or text that writes one: a currency symbol, commas between groups "
    "of three digits, a minus sign or parentheses for a negative, and a trailing percent sign (divided "
    "by 100) are read. Comparing text that writes a number with a number needs value_type number. "
    "A division whose exact quotient does not terminate must be the direct value of a round expression. "
    "A numeric output must be exactly representable as a JSON number; otherwise round it or declare "
    "type string."
)
RELATIONAL_EXPRESSION_POINTER = "A deterministic expression; its grammar is in the relational_spec description."
_NAME = {"type": "string", "pattern": r"^[A-Za-z][A-Za-z0-9_]{0,47}$"}
_COLUMN = {"type": "string", "minLength": 1, "maxLength": 128}
_TRANSFORM = {
    "type": "object", "required": ["version", "fields"], "additionalProperties": False,
    "properties": {
        "version": {"const": "tabular-transform-v2"},
        "fields": {"type": "array", "minItems": 1, "maxItems": 50, "items": {
            "type": "object", "additionalProperties": False,
            "required": ["name", "type", "expression"],
            "properties": {
                "name": _COLUMN, "type": {"enum": ["string", "number", "integer", "date", "boolean", "object", "array"]},
                "mode": {"const": "deterministic"}, "nullable": {"type": "boolean"},
                "expression": {"description": RELATIONAL_EXPRESSION_POINTER},
            },
        }},
    },
}


def _object(properties, required):
    return {
        "type": "object", "additionalProperties": False,
        "properties": properties, "required": required,
    }


def relational_spec_schema():
    """The versioned, model-visible executable contract."""
    selector = _object({
        "alias": _NAME, "document_id": {"type": "string", "minLength": 1, "maxLength": 256},
        "sheet": {"type": "string", "minLength": 1, "maxLength": 128},
        "header_row": {"type": "integer", "minimum": 1, "maximum": 1000},
        "cell_range": {"type": "string", "pattern": r"^[A-Z]{1,3}[1-9][0-9]{0,6}:[A-Z]{1,3}[1-9][0-9]{0,6}$"},
        "table_id": {"type": "string", "minLength": 1, "maxLength": 128},
        "columns": {
            "type": "array", "minItems": 1, "maxItems": 256, "uniqueItems": True, "items": _COLUMN,
            "description": (
                "Optional assertion of the complete ordered native header, including unused columns. "
                "This is not a projection or a list of columns needed by the calculation. "
                "Omit it when the complete header is not known; use a project step to select fields."
            ),
        },
    }, ["alias", "document_id"])
    join = _object({
        "id": _NAME, "op": {"const": "join"}, "left": _NAME, "right": _NAME,
        "how": {"enum": ["left", "inner", "anti", "full"]},
        "cardinality": {"enum": ["one_to_one", "many_to_one", "one_to_many", "many_to_many"]},
        "on": {
            "type": "array", "minItems": 1, "maxItems": 8,
            "items": _object({"left": _COLUMN, "right": _COLUMN}, ["left", "right"]),
        },
        "normalization": {"enum": ["exact", "trim_casefold"]},
        "unmatched": {"enum": ["allow", "error"]},
        "effective": _object({
            "value": _COLUMN, "start": _COLUMN, "end": _COLUMN, "end_inclusive": {"type": "boolean"},
        }, ["value", "start", "end", "end_inclusive"]),
    }, ["id", "op", "left", "right", "how", "cardinality", "on"])
    filtering = _object({
        "id": _NAME, "op": {"const": "filter"}, "input": _NAME,
        "predicate": {"description": RELATIONAL_EXPRESSION_POINTER},
    }, ["id", "op", "input", "predicate"])
    deriving = _object({
        "id": _NAME, "op": {"const": "derive"}, "input": _NAME, "transform": _TRANSFORM,
    }, ["id", "op", "input", "transform"])
    projecting = _object({
        "id": _NAME, "op": {"const": "project"}, "input": _NAME, "transform": _TRANSFORM,
    }, ["id", "op", "input", "transform"])
    aggregate = _object({
        "id": _NAME, "op": {"const": "aggregate"}, "input": _NAME,
        "by": {
            "type": "array", "maxItems": 8,
            "items": _object({"name": _NAME, "column": _COLUMN}, ["name", "column"]),
        },
        "measures": {
            "type": "array", "minItems": 1, "maxItems": 32,
            "items": _object({
                "name": _NAME, "operation": {"enum": ["count", "sum", "min", "max", "distinct_count"]},
                "column": _COLUMN,
            }, ["name", "operation"]),
        },
    }, ["id", "op", "input", "by", "measures"])
    allocate = _object({
        "id": _NAME, "op": {"const": "allocate"}, "left": _NAME, "right": _NAME,
        "on": {
            "type": "array", "minItems": 1, "maxItems": 8,
            "items": _object({"left": _COLUMN, "right": _COLUMN}, ["left", "right"]),
        },
        "event_key": _COLUMN, "detail_key": _COLUMN, "amount": _COLUMN, "weight": _COLUMN,
        "detail_order": {"type": "array", "minItems": 1, "maxItems": 8, "uniqueItems": True, "items": _COLUMN},
        "weight_mode": {"const": "absolute"}, "scale": {"type": "integer", "minimum": 0, "maximum": 12},
        "rounding": {"const": "half_up"},
    }, [
        "id", "op", "left", "right", "on", "event_key", "detail_key", "amount", "weight",
        "detail_order", "weight_mode", "scale", "rounding",
    ])
    cumulative = _object({
        "id": _NAME, "op": {"const": "cumulative_sum"}, "input": _NAME,
        "partition_by": {"type": "array", "maxItems": 8, "uniqueItems": True, "items": _COLUMN},
        "order_by": _COLUMN, "value": _COLUMN,
        "include_when": {"description": RELATIONAL_EXPRESSION_POINTER},
        "frame": {"const": "unbounded_preceding_through_date_peers"},
    }, ["id", "op", "input", "partition_by", "order_by", "value", "include_when", "frame"])
    schema = _object({
        "version": {"enum": [RELATIONAL_VERSION, RELATIONAL_VERSION_V2]},
        "datasets": {"type": "array", "minItems": 1, "maxItems": MAX_RELATIONAL_SOURCES, "items": selector},
        "steps": {
            "type": "array", "minItems": 1, "maxItems": MAX_RELATIONAL_STEPS,
            "items": {"oneOf": [join, filtering, deriving, projecting, aggregate, allocate, cumulative]},
        },
        "result": _NAME, "output": _TRANSFORM,
    }, ["version", "datasets", "steps", "result", "output"])
    schema["description"] = f"{RELATIONAL_COLUMN_RULES} {RELATIONAL_EXPRESSION_GRAMMAR}"
    return schema


_DETAIL_TOKEN = re.compile(r"[a-z][a-z0-9_]{0,79}")
# Detail is limited to code-owned names: a check, a role, a category, an operation and positions.
_DETAIL_KEYS = frozenset({
    "check", "role", "category", "step_index", "step_op", "transform_code", "missing_count",
    "field_index", "expression_index", "value_index", "measure_index",
    "left_category", "right_category", "expected_type",
})
NATIVE_DIAGNOSTIC_KEYS = {
    "check": "native_check", "role": "native_role", "category": "native_category",
    "step_index": "native_step_index", "step_op": "native_step_op",
    "transform_code": "native_transform_code", "missing_count": "native_missing_count",
    "field_index": "native_field_index", "expression_index": "native_expression_index",
    "value_index": "native_value_index", "measure_index": "native_measure_index",
    "left_category": "native_left_category", "right_category": "native_right_category",
    "expected_type": "expected_type",
}


MODEL_FEEDBACK_MAX_NAMES = 200


def safe_native_detail(detail):
    """Keep only closed tokens and counts, so a source value or model-supplied name never rides along."""
    safe = {}
    for key, value in (detail or {}).items():
        if key not in _DETAIL_KEYS or isinstance(value, bool):
            continue
        if isinstance(value, int) and 0 <= value <= 1_000_000:
            safe[key] = value
        elif isinstance(value, str) and _DETAIL_TOKEN.fullmatch(value):
            safe[key] = value
    return safe


class TabularRelationalError(ValueError):
    """A stable failure code and content-free location, without source values or storage locations.

    ``feedback`` is for the model that authored the rejected program only. It may name columns
    that model was already given, so it must never be logged or shown outside that correction.
    """

    def __init__(self, code, *, detail=None, feedback=None):
        self.code = code
        self.detail = safe_native_detail(detail)
        self.feedback = deepcopy(feedback) if isinstance(feedback, dict) and feedback else None
        super().__init__("The complete cross-file calculation could not be completed.")


def native_error_diagnostics(error):
    """Loggable keys for a failure's detail, or nothing when it has none."""
    detail = getattr(error, "detail", None)
    safe = safe_native_detail(detail) if isinstance(detail, dict) else {}
    return {NATIVE_DIAGNOSTIC_KEYS[key]: value for key, value in safe.items()}


@contextmanager
def _locating(check, operation, position=None):
    """Merge a step location into a transformation or relational failure."""
    try:
        yield
    except (
        TabularTransformationSpecError,
        TabularTransformationEvaluationError,
        TabularRelationalError,
    ) as exc:
        detail = {"check": check, "step_op": operation, "step_index": position}
        detail.update(getattr(exc, "detail", {}) if isinstance(getattr(exc, "detail", None), dict) else {})
        exc.detail = safe_native_detail(detail)
        raise


def _require(condition, code="relational_spec_invalid", **detail):
    if not condition:
        raise TabularRelationalError(code, detail=detail)


def _precise_spec(value, columns=None, **detail):
    """Normalize a deterministic spec. With ``detail`` (planning time) a grammar failure names its rule."""
    try:
        normalized = normalize_tabular_transformation_spec(value, source_schema=columns)
    except TabularTransformationSpecError as exc:
        if not detail:
            raise
        raise TabularRelationalError(
            "relational_spec_invalid", detail={**detail, "transform_code": exc.code},
        ) from exc
    _require(
        normalized.get("version") == "tabular-transform-v2"
        and not get_tabular_transformation_model_fields(normalized),
        "relational_expression_invalid", **detail,
    )
    return normalized


V2_OPERATIONS = ("allocate", "cumulative_sum")


def with_operation_version(value):
    """Return the program with the format version its operations determine.

    The version is not a choice: a program that uses ``allocate`` or ``cumulative_sum`` is the
    second format and any other program is the first. Where a program may use either set, the
    server states the version instead of asking its author to restate what the operations
    already say. A value that is not a program with a list of step objects is returned
    unchanged, for the normalizer to reject.

    Returns ``(program, authored_version)``.
    """
    if not isinstance(value, dict) or not isinstance(value.get("steps"), list) or not all(
        isinstance(step, dict) for step in value["steps"]
    ):
        return value, None
    authored = value.get("version")
    derived = RELATIONAL_VERSION_V2 if any(
        step.get("op") in V2_OPERATIONS for step in value["steps"]
    ) else RELATIONAL_VERSION
    return {**value, "version": derived}, authored


def normalize_relational_spec(value, document_ids=None):
    """Reject malformed/ambiguous graphs before any file is read."""
    try:
        valid = isinstance(value, dict) and next(
            Draft202012Validator(relational_spec_schema()).iter_errors(value), None,
        ) is None
        _require(valid, check="schema")
        _require(len(json.dumps(value, allow_nan=False).encode("utf-8")) <= 65536, check="size_limit")
        spec = deepcopy(value)
        datasets = spec["datasets"]
        identifiers = [item["document_id"] for item in datasets]
        aliases = [item["alias"] for item in datasets]
        _require(
            len(set(identifiers)) == len(identifiers) and len(set(aliases)) == len(aliases),
            check="duplicate_dataset",
        )
        _require(all(
            not ("cell_range" in item and ("header_row" not in item or "table_id" in item))
            for item in datasets
        ), check="cell_range_selector")
        if document_ids is not None:
            _require(identifiers == document_ids, "relational_selection_invalid", check="document_ids_mismatch")
        origins = {alias: {alias} for alias in aliases}
        namespaces = {alias: {alias} for alias in aliases}
        for position, step in enumerate(spec["steps"]):
            where = {"step_index": position, "step_op": step["op"]}
            name = step["id"]
            _require(name not in origins, check="duplicate_step_id", **where)
            inputs = (
                [step["left"], step["right"]]
                if step["op"] in ("join", "allocate") else [step["input"]]
            )
            _require(all(item in origins for item in inputs), check="unknown_input", **where)
            if step["op"] == "join":
                overlap = origins[inputs[0]] & origins[inputs[1]]
                if overlap:
                    _require(
                        not (namespaces[inputs[0]] & namespaces[inputs[1]]),
                        check="join_inputs_overlap",
                        **where,
                    )
                next_namespaces = namespaces[inputs[0]] if step["how"] == "anti" else (
                    namespaces[inputs[0]] | namespaces[inputs[1]]
                )
            elif step["op"] in ("allocate", "cumulative_sum"):
                if step["op"] == "allocate":
                    _require(
                        step["detail_key"] in step["detail_order"],
                        check="allocation_detail_order", **where,
                    )
                next_namespaces = (
                    namespaces[inputs[0]] | namespaces[inputs[1]] | {name}
                    if step["op"] == "allocate"
                    else namespaces[inputs[0]] | {name}
                )
                if step["op"] == "cumulative_sum":
                    _precise_spec(_predicate_spec(step["include_when"]), check="include_when", **where)
            elif step["op"] in ("derive", "project"):
                _precise_spec(step["transform"], check="transform", **where)
                next_namespaces = ({name} if step["op"] == "project"
                                   else namespaces[inputs[0]] | {name})
            elif step["op"] == "filter":
                _precise_spec(_predicate_spec(step["predicate"]), check="predicate", **where)
                next_namespaces = namespaces[inputs[0]]
            else:
                names = [item["name"] for item in step["by"] + step["measures"]]
                _require(len(names) == len(set(names)), check="duplicate_output_name", **where)
                _require(all(
                    item["operation"] == "count" or "column" in item
                    for item in step["measures"]
                ), check="measure_column_required", **where)
                next_namespaces = {name}
            origins[name] = set().union(*(origins[item] for item in inputs))
            namespaces[name] = next_namespaces
        _require(
            spec["result"] in origins and origins[spec["result"]] == set(aliases), "relational_source_unused",
            check="result_sources",
        )
        new_operations = any(step["op"] in V2_OPERATIONS for step in spec["steps"])
        _require(
            new_operations == (spec["version"] == RELATIONAL_VERSION_V2),
            check="version_operations",
        )
        _precise_spec(spec["output"], check="output")
        return spec
    except (TypeError, ValueError, RecursionError) as exc:
        if isinstance(exc, TabularRelationalError):
            raise
        raise TabularRelationalError("relational_spec_invalid", detail={"check": "unexpected"}) from exc


def _predicate_spec(expression):
    return {"version": "tabular-transform-v2", "fields": [{
        "name": "keep", "type": "boolean", "nullable": False, "expression": expression,
    }]}


@dataclass(frozen=True)
class RelationalRow:
    values: dict
    lineage: tuple


@dataclass(frozen=True)
class RelationalTable:
    columns: tuple
    rows: tuple


class _Budget:
    def __init__(self, limits, cancel_requested):
        self.limits = limits
        self.cancel_requested = cancel_requested
        self.work = 0
        self.bytes = 0
        # Aliases and step ids, and the running step's position, only to describe a missing column.
        self.prefixes = frozenset()
        self.position = None

    def check(self, amount=1):
        self.work += amount
        _require(self.work <= self.limits.max_total_rows * MAX_RELATIONAL_STEPS * 3, "relational_work_limit")
        if self.cancel_requested is not None and self.cancel_requested():
            raise TabularRelationalError("relational_cancelled")

    def account(self, value):
        self.bytes += len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8"))
        _require(self.bytes <= self.limits.max_source_bytes, "relational_memory_limit")

    def append(self, rows, row):
        self.check()
        _require(len(rows) < self.limits.max_total_rows, "relational_row_limit")
        self.account(row.values)
        self.account(row.lineage)
        rows.append(row)

    def table(self, columns, rows):
        _require(len(columns) <= self.limits.max_columns, "relational_column_limit")
        _require(len(rows) <= self.limits.max_total_rows, "relational_row_limit")
        return RelationalTable(tuple(columns), tuple(rows))


def _column_category(name, columns, prefixes):
    """Why a requested column is absent, judged only from names the plan itself declared."""
    if "." not in name:
        return "unqualified_name"
    prefix = name.split(".", 1)[0]
    if prefix not in prefixes:
        return "unknown_prefix"
    if any(column.startswith(f"{prefix}.") for column in columns):
        return "name_not_in_prefix"
    return "prefix_not_in_input"


def _missing_columns_error(columns, requested, role, prefixes, where):
    """The failure for requested names a table does not have, or None when it has them all."""
    available = set(columns)
    missing = [name for name in requested if name not in available]
    if not missing:
        return None
    return TabularRelationalError("relational_column_missing", detail={
        "check": "column_missing", "role": role, "missing_count": len(missing),
        "category": _column_category(missing[0], columns, prefixes), **where,
    }, feedback={
        "missing_columns": missing[:MODEL_FEEDBACK_MAX_NAMES],
        "available_columns": list(columns)[:MODEL_FEEDBACK_MAX_NAMES],
    })


def _require_columns(columns, requested, role, budget, step):
    where = {"step_op": step["op"], **({} if budget.position is None else {"step_index": budget.position})}
    error = _missing_columns_error(columns, requested, role, budget.prefixes, where)
    if error is not None:
        raise error


def _key(row, columns, normalization):
    values = tuple(row.values[name] for name in columns)
    if any(value is None or value == "" for value in values):
        return None
    _require(all(type(value) in (str, int, float, bool) for value in values), "relational_key_invalid")
    if normalization == "trim_casefold":
        values = tuple(value.strip().casefold() if isinstance(value, str) else value for value in values)
    if any(value == "" for value in values):
        return None
    return tuple((type(value).__name__, value) for value in values)


def _date(value, *, optional=False, detail=None):
    if optional and value in (None, ""):
        return None
    _require(isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is not None,
             "relational_date_invalid", **(detail or {}))
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise TabularRelationalError("relational_date_invalid", detail=detail) from exc


def _decimal(value, *, role, position, scale=None):
    if type(value) is bool:
        raise TabularRelationalError(
            "relational_numeric_invalid",
            detail={"check": role, "value_index": position},
        )
    if value in (None, ""):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        raise TabularRelationalError(
            "relational_numeric_invalid", detail={"check": role, "value_index": position},
        )
    try:
        text = str(value).strip()
        if not text or len(text) > 256:
            return None
        try:
            number = Decimal(text)
        except InvalidOperation:
            number = read_formatted_number(text)
            if number is None:
                raise
        if not number.is_finite() or abs(number) > Decimal("1e18"):
            raise InvalidOperation
        if scale is not None:
            quantum = Decimal(1).scaleb(-scale)
            with localcontext() as precise:
                precise.prec = 64
                quantized = number.quantize(quantum, rounding=ROUND_HALF_UP)
            if number != quantized:
                raise TabularRelationalError(
                    "relational_numeric_scale_invalid",
                    detail={"check": role, "value_index": position},
                )
        return number
    except (DecimalException, ValueError):
        raise TabularRelationalError(
            "relational_numeric_invalid", detail={"check": role, "value_index": position},
        ) from None


def _typed_key(value, role, position):
    if value in (None, ""):
        raise TabularRelationalError(
            "relational_key_invalid", detail={"check": role, "value_index": position},
        )
    if type(value) not in (str, int, float):
        raise TabularRelationalError(
            "relational_key_invalid", detail={"check": role, "value_index": position},
        )
    if isinstance(value, float) and not math.isfinite(value):
        raise TabularRelationalError(
            "relational_key_invalid", detail={"check": role, "value_index": position},
        )
    return (type(value).__name__, value)


def _join(step, left, right, budget):
    left_keys = [item["left"] for item in step["on"]]
    right_keys = [item["right"] for item in step["on"]]
    _require_columns(left.columns, left_keys, "join_left_key", budget, step)
    _require_columns(right.columns, right_keys, "join_right_key", budget, step)
    _require(not (set(left.columns) & set(right.columns)), "relational_columns_ambiguous")
    _require(step["how"] == "anti" or len(left.columns) + len(right.columns) <= budget.limits.max_columns,
             "relational_column_limit")
    normalization = step.get("normalization", "exact")
    index = defaultdict(list)
    effective = step.get("effective")
    if effective:
        _require_columns(left.columns, [effective["value"]], "effective_value", budget, step)
        _require_columns(right.columns, [effective["start"]], "effective_start", budget, step)
        _require_columns(right.columns, [effective["end"]], "effective_end", budget, step)
    intervals = {}
    for position, row in enumerate(right.rows):
        budget.check()
        key = _key(row, right_keys, normalization)
        if key is not None:
            index[key].append((position, row))
        if effective:
            start = _date(
                row.values[effective["start"]],
                detail={"check": "effective_start", "role": "effective_interval", "value_index": position},
            )
            end = _date(
                row.values[effective["end"]], optional=True,
                detail={"check": "effective_end", "role": "effective_interval", "value_index": position},
            )
            _require(
                end is None or start <= end, "relational_date_invalid",
                check="effective_interval", role="effective_interval", value_index=position,
            )
            intervals[position] = (start, end)
    right_unique = step["cardinality"] in ("one_to_one", "many_to_one")
    left_unique = step["cardinality"] in ("one_to_one", "one_to_many")
    if not effective and right_unique:
        _require(
            all(len(rows) == 1 for rows in index.values()), "relational_match_ambiguous",
            check="right_cardinality", role="join_right_cardinality",
        )
    if effective and right_unique:
        for group in index.values():
            ordered = sorted((intervals[position] for position, _row in group), key=lambda item: item[0])
            for previous, current in zip(ordered, ordered[1:]):
                _require(
                    previous[1] is not None and (
                        previous[1] < current[0] if effective["end_inclusive"] else previous[1] <= current[0]
                    ), "relational_match_ambiguous",
                    check="effective_interval_overlap", role="join_right_interval",
                )
    used = defaultdict(int)
    rows = []
    matched = unmatched = 0
    for left_position, row in enumerate(left.rows):
        budget.check()
        key = _key(row, left_keys, normalization)
        matches = list(index.get(key, ())) if key is not None else []
        if effective:
            point = _date(
                row.values[effective["value"]],
                detail={"check": "effective_value", "role": "effective_point", "value_index": left_position},
            )
            filtered = []
            for position, candidate in matches:
                budget.check()
                start, end = intervals[position]
                if point >= start and (end is None or (point <= end if effective["end_inclusive"] else point < end)):
                    filtered.append((position, candidate))
            matches = filtered
        _require(
            not right_unique or len(matches) <= 1, "relational_match_ambiguous",
            check="right_match_cardinality", role="join_right_cardinality",
        )
        if not matches:
            unmatched += 1
            _require(step.get("unmatched", "allow") != "error", "relational_match_missing")
            if step["how"] in ("left", "full", "anti"):
                values = dict(row.values)
                if step["how"] != "anti":
                    values.update(dict.fromkeys(right.columns))
                budget.append(rows, RelationalRow(values, row.lineage))
        else:
            matched += 1
            for position, candidate in matches:
                budget.check()
                used[position] += 1
                _require(
                    not left_unique or used[position] == 1, "relational_match_ambiguous",
                    check="left_reuse", role="join_left_cardinality",
                )
                if step["how"] != "anti":
                    budget.append(rows, RelationalRow(
                        {**row.values, **candidate.values}, tuple(sorted(set(row.lineage + candidate.lineage))),
                    ))
                _require(len(rows) <= budget.limits.max_total_rows, "relational_row_limit")
    unmatched_right = len(right.rows) - len(used)
    if step["how"] == "full":
        _require(not unmatched_right or step.get("unmatched", "allow") != "error", "relational_match_missing")
        for position, row in enumerate(right.rows):
            if position not in used:
                budget.append(rows, RelationalRow({**dict.fromkeys(left.columns), **row.values}, row.lineage))
    columns = left.columns if step["how"] == "anti" else left.columns + right.columns
    return budget.table(columns, rows), {
        "matched_left_rows": matched, "unmatched_left_rows": unmatched, "unmatched_right_rows": unmatched_right,
    }


def _aggregate(step, table, budget):
    names = [item["column"] for item in step["by"]]
    _require_columns(table.columns, names, "aggregate_by", budget, step)
    _require_columns(table.columns, [
        item["column"] for item in step["measures"] if "column" in item
    ], "aggregate_measure", budget, step)
    groups = defaultdict(list)
    for row in table.rows:
        budget.check()
        key = tuple(row.values[name] for name in names)
        _require(all(value is None or type(value) in (str, int, float, bool) for value in key),
                 "relational_key_invalid")
        groups[key].append(row)
    if not names and not table.rows:
        groups[()] = []
    columns = tuple(f'{step["id"]}.{item["name"]}' for item in step["by"] + step["measures"])
    result = []

    def measure_values(group, column):
        for row in group:
            budget.check()
            yield row.values[column]

    for key, group in groups.items():
        values = {f'{step["id"]}.{item["name"]}': value for item, value in zip(step["by"], key)}
        for measure_index, measure in enumerate(step["measures"]):
            operation = measure["operation"]
            if operation == "count":
                value = len(group)
            elif operation == "distinct_count":
                value = len(set(measure_values(group, measure["column"])))
            else:
                value = aggregate_precise_tabular_values(
                    measure_values(group, measure["column"]), operation,
                    diagnostic_detail={"measure_index": measure_index},
                )
            values[f'{step["id"]}.{measure["name"]}'] = value
        lineage = tuple(sorted({source for row in group for source in row.lineage}))
        budget.append(result, RelationalRow(values, lineage))
    return budget.table(columns, result)


def _allocation_value(amount, weight, denominator, scale):
    quantum = Decimal(1).scaleb(-scale)
    with localcontext() as precise:
        precise.prec = 64
        return (amount * weight / denominator).quantize(quantum, rounding=ROUND_HALF_UP)


def _precise_add(left, right):
    with localcontext() as precise:
        precise.prec = 64
        return left + right


def _precise_subtract(left, right):
    with localcontext() as precise:
        precise.prec = 64
        return left - right


def _allocate(step, left, right, budget):
    left_keys = [item["left"] for item in step["on"]]
    right_keys = [item["right"] for item in step["on"]]
    requested_left = [*left_keys, step["event_key"], step["amount"]]
    requested_right = [*right_keys, step["detail_key"], step["weight"], *step["detail_order"]]
    _require_columns(left.columns, requested_left, "allocate_left", budget, step)
    _require_columns(right.columns, requested_right, "allocate_right", budget, step)
    _require(not (set(left.columns) & set(right.columns)), "relational_columns_ambiguous")
    _require(
        len(left.columns) + len(right.columns) + 2 <= budget.limits.max_columns,
        "relational_column_limit",
    )
    identities = set()
    for position, row in enumerate(left.rows):
        budget.check()
        identity = _typed_key(row.values[step["event_key"]], "event_key", position)
        _require(identity not in identities, "relational_identity_ambiguous",
                 check="allocate_event_key", role="allocation_event", value_index=position)
        identities.add(identity)
    details = defaultdict(list)
    detail_identities = set()
    for position, row in enumerate(right.rows):
        budget.check()
        identity = _typed_key(row.values[step["detail_key"]], "detail_key", position)
        _require(identity not in detail_identities, "relational_identity_ambiguous",
                 check="allocate_detail_key", role="allocation_detail", value_index=position)
        detail_identities.add(identity)
        key = _key(row, right_keys, "exact")
        if key is not None:
            details[key].append((position, row))
    output_columns = left.columns + right.columns + (
        f'{step["id"]}.allocated_amount', f'{step["id"]}.allocation_status',
    )
    result = []
    scale = step["scale"]
    for left_position, event in enumerate(left.rows):
        budget.check()
        matches = details.get(_key(event, left_keys, "exact"), ())
        lineage = event.lineage
        if not matches:
            values = {
                **event.values,
                **dict.fromkeys(right.columns),
                f'{step["id"]}.allocated_amount': None,
                f'{step["id"]}.allocation_status': "unknown_no_detail",
            }
            budget.append(result, RelationalRow(values, lineage))
            continue
        denominator = Decimal(0)
        weights = {}
        unknown = False
        for position, detail in matches:
            budget.check()
            weight = _decimal(detail.values[step["weight"]], role="allocation_weight", position=position)
            if weight is None:
                unknown = True
                continue
            weights[position] = abs(weight)
            denominator = _precise_add(denominator, abs(weight))
        amount = _decimal(
            event.values[step["amount"]], role="allocation_amount",
            position=left_position, scale=scale,
        )
        if amount is None or unknown or denominator <= 0:
            lineage = tuple(sorted(set(event.lineage + tuple(
                source for _position, detail in matches for source in detail.lineage
            ))))
            values = {
                **event.values,
                **dict.fromkeys(right.columns),
                f'{step["id"]}.allocated_amount': None,
                f'{step["id"]}.allocation_status': (
                    "unknown_missing_amount" if amount is None
                    else "unknown_weight" if unknown else "unknown_nonpositive_denominator"
                ),
            }
            budget.append(result, RelationalRow(values, lineage))
            continue

        ordered = sorted(
            matches,
            key=lambda item: tuple(
                (type(item[1].values[column]).__name__, str(item[1].values[column] or ""))
                for column in step["detail_order"]
            ),
        )
        allocated = Decimal(0)
        all_lineage = tuple(sorted(set(event.lineage + tuple(
            source for _position, detail in ordered for source in detail.lineage
        ))))
        for order_index, (position, detail) in enumerate(ordered):
            budget.check()
            if order_index == len(ordered) - 1:
                share = _precise_subtract(amount, allocated)
            else:
                share = _allocation_value(amount, weights[position], denominator, scale)
                allocated = _precise_add(allocated, share)
            quantum = Decimal(1).scaleb(-scale)
            with localcontext() as precise:
                precise.prec = 64
                share = share.quantize(quantum, rounding=ROUND_HALF_UP)
            values = {
                **event.values, **detail.values,
                f'{step["id"]}.allocated_amount': format(share, "f"),
                f'{step["id"]}.allocation_status': "complete",
            }
            budget.append(result, RelationalRow(values, all_lineage))
    return budget.table(output_columns, result)


def _cumulative_sum(step, table, budget):
    requested = [*step["partition_by"], step["order_by"], step["value"]]
    _require_columns(table.columns, requested, "cumulative_input", budget, step)
    predicate = _precise_spec(_predicate_spec(step["include_when"]), table.columns)
    output_columns = table.columns + (
        f'{step["id"]}.cumulative_value', f'{step["id"]}.cumulative_status',
    )
    result_by_position = {}
    groups = defaultdict(list)
    for position, row in enumerate(table.rows):
        budget.check()
        keep = evaluate_tabular_transformation_row(predicate, row.values)["keep"]
        if type(keep) is not bool:
            raise TabularRelationalError(
                "relational_boolean_invalid",
                detail={"check": "cumulative_include", "value_index": position},
            )
        if not keep:
            calculated = RelationalRow({
                **row.values,
                f'{step["id"]}.cumulative_value': None,
                f'{step["id"]}.cumulative_status': "excluded",
            }, row.lineage)
            budget.check()
            budget.account(calculated.values)
            budget.account(calculated.lineage)
            result_by_position[position] = calculated
            continue
        partition = []
        for column in step["partition_by"]:
            value = row.values[column]
            if value in (None, ""):
                partition = None
                break
            partition.append(_typed_key(value, "cumulative_partition", position))
        if partition is None:
            calculated = RelationalRow({
                **row.values,
                f'{step["id"]}.cumulative_value': None,
                f'{step["id"]}.cumulative_status': "unknown_partition",
            }, row.lineage)
            budget.check()
            budget.account(calculated.values)
            budget.account(calculated.lineage)
            result_by_position[position] = calculated
            continue
        if row.values[step["order_by"]] in (None, ""):
            calculated = RelationalRow({
                **row.values,
                f'{step["id"]}.cumulative_value': None,
                f'{step["id"]}.cumulative_status': "unknown_order",
            }, row.lineage)
            budget.check()
            budget.account(calculated.values)
            budget.account(calculated.lineage)
            result_by_position[position] = calculated
            continue
        date_value = _date(
            row.values[step["order_by"]],
            detail={"check": "cumulative_order", "value_index": position},
        )
        groups[tuple(partition)].append((date_value, position, row))
    for group in groups.values():
        group.sort(key=lambda item: (item[0], item[1]))
        running = Decimal(0)
        unknown = False
        prefix_lineage = []
        for _date_value, positions in _date_peer_groups(group):
            contribution = Decimal(0)
            peers = []
            for position, row in positions:
                budget.check()
                amount = _decimal(row.values[step["value"]], role="cumulative_value", position=position)
                if amount is None:
                    unknown = True
                else:
                    contribution = _precise_add(contribution, amount)
                peers.append((position, row))
            running = _precise_add(running, contribution)
            prefix_lineage.extend(
                source for _position, row in positions for source in row.lineage
            )
            for position, row in peers:
                calculated = RelationalRow({
                    **row.values,
                    f'{step["id"]}.cumulative_value': None if unknown else format(running, "f"),
                    f'{step["id"]}.cumulative_status': "unknown_amount" if unknown else "complete",
                }, tuple(sorted(set(prefix_lineage + list(row.lineage)))))
                budget.check()
                budget.account(calculated.values)
                budget.account(calculated.lineage)
                result_by_position[position] = calculated
    result = []
    for position, row in enumerate(table.rows):
        budget.check()
        calculated = result_by_position[position]
        budget.append(result, RelationalRow(calculated.values, tuple(dict.fromkeys(calculated.lineage))))
    return budget.table(output_columns, result)


def _date_peer_groups(group):
    current_date = None
    positions = []
    for date_value, position, row in group:
        if current_date is not None and date_value != current_date:
            yield current_date, positions
            positions = []
        current_date = date_value
        positions.append((position, row))
    if current_date is not None:
        yield current_date, positions


def _lineage(ranges):
    grouped = defaultdict(list)
    for alias, document_id, sheet, row in ranges:
        grouped[(alias, document_id, sheet)].append(row)
    result = []
    for (alias, document_id, sheet), values in sorted(grouped.items()):
        spans = []
        for value in sorted(set(values)):
            if spans and value == spans[-1][1] + 1:
                spans[-1][1] = value
            else:
                spans.append([value, value])
        result.append({"dataset": alias, "document_id": document_id, "sheet": sheet, "row_ranges": spans})
    return result


def check_relational_columns(spec, headers):
    """Reject a column reference no run can satisfy, from complete headers already known.

    ``spec`` is a normalized relational spec. ``headers`` maps a dataset alias to its complete
    ordered native header; a dataset without one, and every table derived from it, is left to the
    runtime check. References are judged by the same propagation the runtime applies, so a plan the
    runtime would accept is never rejected here.
    """
    tables = {
        alias: tuple(f"{alias}.{name}" for name in names)
        for alias, names in headers.items() if isinstance(names, (list, tuple))
    }
    prefixes = (
        frozenset(item["alias"] for item in spec["datasets"]) | frozenset(step["id"] for step in spec["steps"])
    )

    def require(columns, requested, role, where):
        error = _missing_columns_error(columns, requested, role, prefixes, where)
        if error is not None:
            raise error

    def require_references(columns, expression, role, where):
        # The runtime applies no source-column check to a table without columns.
        if columns:
            require(columns, get_tabular_transformation_source_references(expression), role, where)

    for position, step in enumerate(spec["steps"]):
        operation = step["op"]
        where = {"step_index": position, "step_op": operation}
        if operation == "join":
            left, right = tables.get(step["left"]), tables.get(step["right"])
            effective = step.get("effective")
            if left is not None:
                require(left, [item["left"] for item in step["on"]], "join_left_key", where)
                if effective:
                    require(left, [effective["value"]], "effective_value", where)
            if right is not None:
                require(right, [item["right"] for item in step["on"]], "join_right_key", where)
                if effective:
                    require(right, [effective["start"]], "effective_start", where)
                    require(right, [effective["end"]], "effective_end", where)
            if left is not None and right is not None:
                _require(
                    step["how"] == "anti" or not set(left) & set(right),
                    "relational_columns_ambiguous",
                    check="join_columns_ambiguous", step_index=position, step_op=operation,
                )
                tables[step["id"]] = left if step["how"] == "anti" else left + right
            continue
        if operation == "allocate":
            left, right = tables.get(step["left"]), tables.get(step["right"])
            if left is not None:
                require(left, [
                    *[item["left"] for item in step["on"]], step["event_key"], step["amount"],
                ], "allocate_left", where)
            if right is not None:
                require(right, [
                    *[item["right"] for item in step["on"]], step["detail_key"],
                    step["weight"], *step["detail_order"],
                ], "allocate_right", where)
            if left is not None and right is not None:
                _require(
                    not set(left) & set(right),
                    "relational_columns_ambiguous",
                    check="allocate_columns_ambiguous", **where,
                )
                tables[step["id"]] = left + right + (
                    f'{step["id"]}.allocated_amount', f'{step["id"]}.allocation_status',
                )
            continue
        table = tables.get(step["input"])
        if table is None:
            continue
        if operation == "aggregate":
            require(table, [item["column"] for item in step["by"]], "aggregate_by", where)
            require(
                table, [item["column"] for item in step["measures"] if "column" in item],
                "aggregate_measure", where,
            )
            tables[step["id"]] = tuple(f'{step["id"]}.{item["name"]}' for item in step["by"] + step["measures"])
            continue
        if operation == "cumulative_sum":
            require(table, [
                *step["partition_by"], step["order_by"], step["value"],
            ], "cumulative_input", where)
            require_references(
                table, _predicate_spec(step["include_when"]), "cumulative_include", where,
            )
            tables[step["id"]] = table + (
                f'{step["id"]}.cumulative_value', f'{step["id"]}.cumulative_status',
            )
            continue
        expression = step["transform"] if operation in ("derive", "project") else _predicate_spec(step["predicate"])
        require_references(
            table, expression, "filter_predicate" if operation == "filter" else f"{operation}_expression", where,
        )
        if operation == "filter":
            tables[step["id"]] = table
        else:
            added = tuple(f'{step["id"]}.{field["name"]}' for field in _precise_spec(expression)["fields"])
            tables[step["id"]] = table + added if operation == "derive" else added
    require_references(tables.get(spec["result"]), spec["output"], "output_expression", {"step_op": "output"})


def calculate_relational_sources(spec, datasets, *, limits, cancel_requested=None):
    """Compute from complete authorized tables without models or persistent effects.

    Each dataset is (columns, (row_number, values) rows, sheet), or a caller-owned
    context-manager factory returning that tuple. Factories are opened one at a
    time; the caller owns authorization and byte/workbook limits.
    """
    spec = normalize_relational_spec(spec)
    _require(set(datasets) == {item["alias"] for item in spec["datasets"]}, "relational_selection_invalid")
    _require(len(datasets) <= limits.max_sources, "relational_source_limit")
    budget = _Budget(limits, cancel_requested)
    budget.prefixes = (
        frozenset(item["alias"] for item in spec["datasets"]) | frozenset(step["id"] for step in spec["steps"])
    )
    tables = {}
    sources = []
    total_rows = 0
    for selected in spec["datasets"]:
        alias = selected["alias"]
        loader = datasets[alias]
        with loader() if callable(loader) else nullcontext(loader) as data:
            columns, raw_rows, sheet = data
            _require(len(columns) == len(set(columns)), "relational_columns_ambiguous")
            _require(not selected.get("columns") or list(columns) == selected["columns"], "relational_schema_changed")
            qualified = tuple(f"{alias}.{name}" for name in columns)
            _require(all(len(name) <= 128 for name in qualified), "relational_column_limit")
            rows = []
            for number, values in raw_rows:
                budget.check()
                _require(isinstance(number, int) and not isinstance(number, bool) and number >= 1)
                _require(set(values) == set(columns), "relational_schema_changed")
                budget.append(rows, RelationalRow(
                    {f"{alias}.{name}": values[name] for name in columns},
                    ((alias, selected["document_id"], sheet or "", number),),
                ))
                total_rows += 1
                _require(total_rows <= limits.max_total_rows, "relational_row_limit")
        tables[alias] = budget.table(qualified, rows)
        sources.append({
            "dataset": alias, "document_id": selected["document_id"], "sheet": sheet,
            "row_count": len(rows), "columns": list(columns),
            "selection": {name: selected[name] for name in ("header_row", "cell_range", "table_id") if name in selected},
            "schema_sha256": hashlib.sha256(json.dumps(list(columns)).encode()).hexdigest(),
        })
    diagnostics = []
    for position, step in enumerate(spec["steps"]):
        budget.check()
        budget.position = position
        with _locating("step_evaluation", step["op"], position):
            if step["op"] == "join":
                result, details = _join(step, tables[step["left"]], tables[step["right"]], budget)
            elif step["op"] == "allocate":
                result = _allocate(step, tables[step["left"]], tables[step["right"]], budget)
                details = {}
            elif step["op"] == "cumulative_sum":
                result = _cumulative_sum(step, tables[step["input"]], budget)
                details = {}
            else:
                table = tables[step["input"]]
                details = {}
                if step["op"] == "aggregate":
                    result = _aggregate(step, table, budget)
                else:
                    expression = (
                        step["transform"] if step["op"] in ("derive", "project")
                        else _predicate_spec(step["predicate"])
                    )
                    normalized = _precise_spec(expression, table.columns)
                    columns = [] if step["op"] == "project" else list(table.columns)
                    if step["op"] in ("derive", "project"):
                        columns.extend(f'{step["id"]}.{field["name"]}' for field in normalized["fields"])
                    _require(len(columns) <= limits.max_columns, "relational_column_limit")
                    rows = []
                    for row in table.rows:
                        budget.check()
                        calculated = evaluate_tabular_transformation_row(normalized, row.values)
                        if step["op"] in ("derive", "project"):
                            budget.append(rows, RelationalRow({
                                **({} if step["op"] == "project" else row.values),
                                **{f'{step["id"]}.{name}': value for name, value in calculated.items()},
                            }, row.lineage))
                        elif calculated["keep"]:
                            budget.append(rows, row)
                    result = budget.table(columns, rows)
        tables[step["id"]] = result
        diagnostics.append({"step_id": step["id"], "operation": step["op"], "row_count": len(result.rows), **details})
    final = tables[spec["result"]]
    records, lineage = [], []
    with _locating("output_evaluation", "output"):
        projection = _precise_spec(spec["output"], final.columns)
        for index, row in enumerate(final.rows, 1):
            budget.check()
            record = evaluate_tabular_transformation_row(projection, row.values)
            source_rows = {"result_row": index, "sources": _lineage(row.lineage)}
            budget.account(record)
            budget.account(source_rows)
            records.append(record)
            lineage.append(source_rows)
    return {
        "records": records, "lineage": lineage,
        "columns": [
            {"name": field["name"], "value_type": "string" if field["type"] == "date" else field["type"],
             "nullable": field.get("nullable", False)}
            for field in projection["fields"]
        ],
        "coverage": {"version": spec["version"], "sources": sources, "steps": diagnostics,
                     "operation_spec": deepcopy(spec),
                     "operation_sha256": hashlib.sha256(
                         json.dumps(spec, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                     ).hexdigest(),
                     "input_rows": total_rows, "output_rows": len(records), "complete": True},
    }
