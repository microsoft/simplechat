# functions_tabular_relational.py
"""Bounded, deterministic relationships over complete tabular sources.

Expressions use the existing precise transformation grammar, never executable
Python or SQL. Source authorization and result persistence belong to the caller.
"""

from collections import defaultdict
from contextlib import nullcontext
from copy import deepcopy
from dataclasses import dataclass
from datetime import date
import hashlib
import json
import re

from jsonschema import Draft202012Validator

from functions_tabular_transformations import (
    aggregate_precise_tabular_values,
    evaluate_tabular_transformation_row,
    get_tabular_transformation_model_fields,
    normalize_tabular_transformation_spec,
)


RELATIONAL_VERSION = "tabular-relate-v1"
MAX_RELATIONAL_STEPS = 32
MAX_RELATIONAL_SOURCES = 100
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
                "mode": {"const": "deterministic"}, "nullable": {"type": "boolean"}, "expression": {},
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
        "columns": {"type": "array", "minItems": 1, "maxItems": 256, "uniqueItems": True, "items": _COLUMN},
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
        "id": _NAME, "op": {"const": "filter"}, "input": _NAME, "predicate": {},
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
    return _object({
        "version": {"const": RELATIONAL_VERSION},
        "datasets": {"type": "array", "minItems": 1, "maxItems": MAX_RELATIONAL_SOURCES, "items": selector},
        "steps": {
            "type": "array", "minItems": 1, "maxItems": MAX_RELATIONAL_STEPS,
            "items": {"oneOf": [join, filtering, deriving, projecting, aggregate]},
        },
        "result": _NAME, "output": _TRANSFORM,
    }, ["version", "datasets", "steps", "result", "output"])


class TabularRelationalError(ValueError):
    """A stable failure code, without source values or storage locations."""

    def __init__(self, code):
        self.code = code
        super().__init__("The complete cross-file calculation could not be completed.")


def _require(condition, code="relational_spec_invalid"):
    if not condition:
        raise TabularRelationalError(code)


def _precise_spec(value, columns=None):
    normalized = normalize_tabular_transformation_spec(value, source_schema=columns)
    _require(
        normalized.get("version") == "tabular-transform-v2"
        and not get_tabular_transformation_model_fields(normalized),
        "relational_expression_invalid",
    )
    return normalized


def normalize_relational_spec(value, document_ids=None):
    """Reject malformed/ambiguous graphs before any file is read."""
    try:
        valid = isinstance(value, dict) and next(
            Draft202012Validator(relational_spec_schema()).iter_errors(value), None,
        ) is None
        _require(valid)
        _require(len(json.dumps(value, allow_nan=False).encode("utf-8")) <= 65536)
        spec = deepcopy(value)
        datasets = spec["datasets"]
        identifiers = [item["document_id"] for item in datasets]
        aliases = [item["alias"] for item in datasets]
        _require(len(set(identifiers)) == len(identifiers) and len(set(aliases)) == len(aliases))
        _require(all(
            not ("cell_range" in item and ("header_row" not in item or "table_id" in item))
            for item in datasets
        ))
        if document_ids is not None:
            _require(identifiers == document_ids, "relational_selection_invalid")
        origins = {alias: {alias} for alias in aliases}
        for step in spec["steps"]:
            name = step["id"]
            _require(name not in origins)
            inputs = [step["left"], step["right"]] if step["op"] == "join" else [step["input"]]
            _require(all(item in origins for item in inputs))
            if step["op"] == "join":
                _require(not (origins[inputs[0]] & origins[inputs[1]]))
            elif step["op"] in ("derive", "project"):
                _precise_spec(step["transform"])
            elif step["op"] == "filter":
                _precise_spec(_predicate_spec(step["predicate"]))
            else:
                names = [item["name"] for item in step["by"] + step["measures"]]
                _require(len(names) == len(set(names)))
                _require(all(
                    item["operation"] == "count" or "column" in item
                    for item in step["measures"]
                ))
            origins[name] = set().union(*(origins[item] for item in inputs))
        _require(spec["result"] in origins and origins[spec["result"]] == set(aliases), "relational_source_unused")
        _precise_spec(spec["output"])
        return spec
    except (TypeError, ValueError, RecursionError) as exc:
        if isinstance(exc, TabularRelationalError):
            raise
        raise TabularRelationalError("relational_spec_invalid") from exc


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


def _require_columns(columns, requested):
    _require(set(requested) <= set(columns), "relational_column_missing")


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


def _date(value, *, optional=False):
    if optional and value in (None, ""):
        return None
    _require(isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is not None,
             "relational_date_invalid")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise TabularRelationalError("relational_date_invalid") from exc


def _join(step, left, right, budget):
    left_keys = [item["left"] for item in step["on"]]
    right_keys = [item["right"] for item in step["on"]]
    _require_columns(left.columns, left_keys)
    _require_columns(right.columns, right_keys)
    _require(not (set(left.columns) & set(right.columns)), "relational_columns_ambiguous")
    _require(step["how"] == "anti" or len(left.columns) + len(right.columns) <= budget.limits.max_columns,
             "relational_column_limit")
    normalization = step.get("normalization", "exact")
    index = defaultdict(list)
    effective = step.get("effective")
    if effective:
        _require_columns(left.columns, [effective["value"]])
        _require_columns(right.columns, [effective["start"], effective["end"]])
    intervals = {}
    for position, row in enumerate(right.rows):
        budget.check()
        key = _key(row, right_keys, normalization)
        if key is not None:
            index[key].append((position, row))
        if effective:
            start = _date(row.values[effective["start"]])
            end = _date(row.values[effective["end"]], optional=True)
            _require(end is None or start <= end, "relational_date_invalid")
            intervals[position] = (start, end)
    right_unique = step["cardinality"] in ("one_to_one", "many_to_one")
    left_unique = step["cardinality"] in ("one_to_one", "one_to_many")
    if not effective and right_unique:
        _require(all(len(rows) == 1 for rows in index.values()), "relational_match_ambiguous")
    if effective and right_unique:
        for group in index.values():
            ordered = sorted((intervals[position] for position, _row in group), key=lambda item: item[0])
            for previous, current in zip(ordered, ordered[1:]):
                _require(
                    previous[1] is not None and (
                        previous[1] < current[0] if effective["end_inclusive"] else previous[1] <= current[0]
                    ), "relational_match_ambiguous",
                )
    used = defaultdict(int)
    rows = []
    matched = unmatched = 0
    for row in left.rows:
        budget.check()
        key = _key(row, left_keys, normalization)
        matches = list(index.get(key, ())) if key is not None else []
        if effective:
            point = _date(row.values[effective["value"]])
            filtered = []
            for position, candidate in matches:
                budget.check()
                start, end = intervals[position]
                if point >= start and (end is None or (point <= end if effective["end_inclusive"] else point < end)):
                    filtered.append((position, candidate))
            matches = filtered
        _require(not right_unique or len(matches) <= 1, "relational_match_ambiguous")
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
                _require(not left_unique or used[position] == 1, "relational_match_ambiguous")
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
    _require_columns(table.columns, names + [
        item["column"] for item in step["measures"] if "column" in item
    ])
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
        for measure in step["measures"]:
            operation = measure["operation"]
            if operation == "count":
                value = len(group)
            elif operation == "distinct_count":
                value = len(set(measure_values(group, measure["column"])))
            else:
                value = aggregate_precise_tabular_values(
                    measure_values(group, measure["column"]), operation,
                )
            values[f'{step["id"]}.{measure["name"]}'] = value
        lineage = tuple(sorted({source for row in group for source in row.lineage}))
        budget.append(result, RelationalRow(values, lineage))
    return budget.table(columns, result)


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
    for step in spec["steps"]:
        budget.check()
        if step["op"] == "join":
            result, details = _join(step, tables[step["left"]], tables[step["right"]], budget)
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
    projection = _precise_spec(spec["output"], final.columns)
    records, lineage = [], []
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
        "coverage": {"version": RELATIONAL_VERSION, "sources": sources, "steps": diagnostics,
                     "operation_spec": deepcopy(spec),
                     "operation_sha256": hashlib.sha256(
                         json.dumps(spec, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                     ).hexdigest(),
                     "input_rows": total_rows, "output_rows": len(records), "complete": True},
    }
