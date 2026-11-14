# test_tabular_relational_calculations.py
"""
Functional tests for complete multi-file calculations and per-row lineage.
Version: 0.261.443
Implemented in: 0.261.437
Planner-visible grammar, column rules and content-free failure locations added in: 0.261.443

These offline cases use unrelated schemas, precise source values and the real
CSV/Excel readers. They do not invoke a model or change source documents.
"""

from contextlib import contextmanager
from dataclasses import replace
import io

import pytest
from jsonschema import Draft202012Validator
from openpyxl import Workbook
from openpyxl.worksheet.table import Table

from functions_schema_diagnostics import schema_error_location
from functions_tabular_merge import (
    TabularMergeError, TabularMergeLimits, TabularMergeSource, display_header_name, read_tabular_source_records,
)
from functions_tabular_relational import (
    RELATIONAL_COLUMN_RULES, RELATIONAL_EXPRESSION_GRAMMAR, TabularRelationalError, calculate_relational_sources,
    check_relational_columns, native_error_diagnostics, normalize_relational_spec, relational_spec_schema,
    safe_native_detail,
)
from functions_tabular_transformations import (
    TABULAR_TRANSFORMATION_ALLOWED_OPS, TabularTransformationEvaluationError, TabularTransformationSpecError,
    normalize_tabular_transformation_spec,
)


def field(name, source=None, *, expression=None, value_type="string", nullable=False):
    return {
        "name": name, "type": value_type, "nullable": nullable,
        "expression": {"source": source} if expression is None else expression,
    }


def transform(*fields):
    return {"version": "tabular-transform-v2", "fields": list(fields)}


def join_spec():
    return {
        "version": "tabular-relate-v1",
        "datasets": [{"alias": "sales", "document_id": "sales"}, {"alias": "catalog", "document_id": "catalog"}],
        "steps": [{
            "id": "matched", "op": "join", "left": "sales", "right": "catalog",
            "how": "left", "cardinality": "many_to_one",
            "on": [{"left": "sales.code", "right": "catalog.sku"}],
        }, {
            "id": "priced", "op": "derive", "input": "matched",
            "transform": transform(field("amount", expression={
                "op": "multiply", "left": {"source": "sales.quantity"}, "right": {"source": "catalog.price"},
            })),
        }],
        "result": "priced",
        "output": transform(field("code", "sales.code"), field("amount", "priced.amount")),
    }


def run(spec, sources, *, limits=None, cancel_requested=None):
    limits = limits or TabularMergeLimits()
    data = {}
    for selected in spec["datasets"]:
        raw = sources[selected["document_id"]]
        filename, raw = raw if isinstance(raw, tuple) else ("source.csv", raw)
        source = TabularMergeSource(selected["document_id"], filename, lambda raw=raw: raw)
        data[selected["alias"]] = lambda source=source, selected=selected: read_tabular_source_records(
            source, sheet=selected.get("sheet"), header_row=selected.get("header_row"), limits=limits,
            cell_range=selected.get("cell_range"), table_id=selected.get("table_id"),
        )
    return calculate_relational_sources(spec, data, limits=limits, cancel_requested=cancel_requested)


def test_keyed_calculation_preserves_zero_prefixed_ids_exact_money_and_lineage():
    result = run(join_spec(), {
        "sales": b"code,quantity\n007,3\n008,2\n\n",
        "catalog": b"sku,price\n008,0.20\n007,0.10\n",
    })
    assert result["records"] == [{"code": "007", "amount": "0.30"}, {"code": "008", "amount": "0.40"}]
    assert result["coverage"]["input_rows"] == 4 and result["coverage"]["output_rows"] == 2
    assert result["lineage"][0]["sources"] == [
        {"dataset": "catalog", "document_id": "catalog", "sheet": "", "row_ranges": [[3, 3]]},
        {"dataset": "sales", "document_id": "sales", "sheet": "", "row_ranges": [[2, 2]]},
    ]


@pytest.mark.parametrize("how,expected", [
    ("left", [("001", "001"), ("002", None), ("", None)]),
    ("inner", [("001", "001")]),
    ("anti", [("002",), ("",)]),
    ("full", [("001", "001"), ("002", None), ("", None), (None, "003"), (None, "")]),
])
def test_join_modes_make_unmatched_and_null_keys_explicit(how, expected):
    spec = join_spec()
    spec["steps"] = [{**spec["steps"][0], "how": how}]
    spec["result"] = "matched"
    fields = [field("left", "sales.code", nullable=True)]
    if how != "anti":
        fields.append(field("right", "catalog.sku", nullable=True))
    spec["output"] = transform(*fields)
    result = run(spec, {"sales": b"code,note\n001,a\n002,b\n,c\n", "catalog": b"sku,note\n001,a\n003,b\n,c\n"})
    assert [tuple(row.values()) for row in result["records"]] == expected


def test_duplicate_lookup_keys_fail_instead_of_multiplying_financial_values():
    with pytest.raises(TabularRelationalError) as error:
        run(join_spec(), {"sales": b"code,quantity\n007,3\n", "catalog": b"sku,price\n007,0.10\n007,0.20\n"})
    assert error.value.code == "relational_match_ambiguous"


def test_date_effective_lookup_and_rounding_use_the_declared_interval():
    spec = join_spec()
    spec["steps"][0]["on"] = [{"left": "sales.currency", "right": "catalog.currency"}]
    spec["steps"][0]["effective"] = {
        "value": "sales.date", "start": "catalog.start", "end": "catalog.end", "end_inclusive": True,
    }
    spec["steps"][1]["transform"] = transform(field("amount", expression={
        "op": "round", "scale": 2, "mode": "half_up",
        "value": {"op": "divide", "left": {"source": "sales.quantity"}, "right": {"source": "catalog.price"}},
    }))
    spec["output"] = transform(field("rate", "catalog.id"), field("amount", "priced.amount"))
    sources = {
        "sales": b"currency,date,quantity\nEUR,2026-03-01,1\nEUR,2026-03-31,1\n",
        "catalog": b"currency,start,end,price,id\nEUR,2026-03-01,2026-03-30,3,old\nEUR,2026-03-31,,6,new\n",
    }
    result = run(spec, sources)
    assert result["records"] == [{"rate": "old", "amount": "0.33"}, {"rate": "new", "amount": "0.17"}]
    sources["catalog"] = sources["catalog"].replace(b"2026-03-30", b"2026-03-31")
    with pytest.raises(TabularRelationalError) as error:
        run(spec, sources)
    assert error.value.code == "relational_match_ambiguous"


def test_grouped_decimal_totals_keep_source_values_and_complete_lineage():
    spec = join_spec()
    spec["steps"].append({
        "id": "totals", "op": "aggregate", "input": "priced", "by": [],
        "measures": [{"name": "amount", "operation": "sum", "column": "priced.amount"},
                     {"name": "count", "operation": "count"}],
    })
    spec["result"] = "totals"
    spec["output"] = transform(field("amount", "totals.amount"), field("count", "totals.count", value_type="integer"))
    result = run(spec, {"sales": b"code,quantity\n007,3\n008,-2\n", "catalog": b"sku,price\n007,0.10\n008,0.20\n"})
    assert result["records"] == [{"amount": "-0.10", "count": 2}]
    assert result["lineage"][0]["sources"][1]["row_ranges"] == [[2, 3]]


def test_projection_and_filter_preserve_original_source_rows_before_a_join():
    spec = join_spec()
    spec["steps"][0]["left"] = "selected"
    spec["steps"][0]["on"][0]["left"] = "keys.code"
    spec["steps"][1]["transform"]["fields"][0]["expression"]["left"] = {"source": "keys.units"}
    spec["steps"] = [{
        "id": "keys", "op": "project", "input": "sales",
        "transform": transform(field("code", "sales.code"), field("units", "sales.quantity")),
    }, {
        "id": "selected", "op": "filter", "input": "keys",
        "predicate": {"op": "gt", "left": {"source": "keys.units"}, "right": {"value": "0"},
                      "value_type": "number"},
    }, *spec["steps"]]
    spec["output"]["fields"][0]["expression"] = {"source": "keys.code"}
    result = run(spec, {
        "sales": b"code,quantity,unneeded\n007,3,ignored\n008,-2,ignored\n",
        "catalog": b"sku,price\n007,0.10\n008,0.20\n",
    })
    assert result["records"] == [{"code": "007", "amount": "0.30"}]
    assert result["lineage"][0]["sources"][1]["row_ranges"] == [[2, 2]]


def source_chain(count):
    datasets = [{"alias": f"data{index}", "document_id": f"source{index}"} for index in range(count)]
    steps = []
    previous = datasets[0]["alias"]
    sources = {f"source{index}": f"key,value{index}\n001,{index}\n".encode() for index in range(count)}
    for index in range(1, count):
        steps.append({
            "id": f"join{index}", "op": "join", "left": previous, "right": f"data{index}",
            "on": [{"left": "data0.key", "right": f"data{index}.key"}],
            "how": "left", "cardinality": "one_to_one",
        })
        previous = f"join{index}"
    steps.append({
        "id": "calculated", "op": "derive", "input": previous,
        "transform": transform(field("total", expression={
            "op": "add", "values": [{"source": f"data{index}.value{index}"} for index in range(count)],
        })),
    })
    spec = {"version": "tabular-relate-v1", "datasets": datasets, "steps": steps, "result": "calculated",
            "output": transform(field("total", "calculated.total"))}
    return spec, sources


@pytest.mark.parametrize("count", [1, 3, 7, 9, 10])
def test_all_declared_sources_participate_with_different_schemas(count):
    spec, sources = source_chain(count)
    result = run(spec, sources)
    assert result["records"] == [{"total": str(sum(range(count)))}]
    assert len(result["lineage"][0]["sources"]) == count
    assert result["coverage"]["input_rows"] == count


def test_source_count_limit_is_checked_before_any_loader_runs():
    spec, _sources = source_chain(3)

    def forbidden_read():
        raise AssertionError("An over-limit source set must fail before file reads.")

    with pytest.raises(TabularRelationalError) as error:
        calculate_relational_sources(
            spec, {dataset["alias"]: forbidden_read for dataset in spec["datasets"]},
            limits=replace(TabularMergeLimits(), max_sources=2),
        )
    assert error.value.code == "relational_source_limit"


def test_explicit_many_to_many_join_still_has_an_expansion_limit():
    spec = join_spec()
    spec["steps"][0]["cardinality"] = "many_to_many"
    with pytest.raises(TabularRelationalError) as error:
        run(spec, {
            "sales": b"code,quantity\n007,1\n007,2\n007,3\n",
            "catalog": b"sku,price\n007,0.10\n007,0.20\n007,0.30\n",
        }, limits=replace(TabularMergeLimits(), max_total_rows=6))
    assert error.value.code == "relational_row_limit"


@pytest.mark.parametrize("fault", ["forward_reference", "unused_source", "unknown_column", "untrusted_code"])
def test_invalid_graphs_or_fields_never_get_successful_results(fault):
    spec = join_spec()
    if fault == "forward_reference":
        spec["steps"][0]["left"] = "priced"
    elif fault == "unused_source":
        spec["datasets"].append({"alias": "extra", "document_id": "extra"})
    elif fault == "unknown_column":
        spec["steps"][0]["on"][0]["right"] = "catalog.missing"
    else:
        spec["output"]["fields"][0]["expression"] = {"python": "__import__('os')"}
    with pytest.raises(TabularRelationalError):
        if fault == "unknown_column":
            run(spec, {"sales": b"code,quantity\n007,3\n", "catalog": b"sku,price\n007,0.10\n"})
        else:
            normalize_relational_spec(spec)


def test_row_source_and_cancellation_limits_fail_explicitly():
    spec = join_spec()
    sources = {"sales": b"code,quantity\n007,3\n008,2\n", "catalog": b"sku,price\n007,0.10\n008,0.20\n"}
    with pytest.raises(TabularRelationalError) as error:
        run(spec, sources, limits=replace(TabularMergeLimits(), max_total_rows=3))
    assert error.value.code == "relational_row_limit"
    with pytest.raises(TabularRelationalError) as error:
        run(spec, sources, cancel_requested=lambda: True)
    assert error.value.code == "relational_cancelled"


def test_multisheet_workbook_needs_an_explicit_sheet_for_calculation():
    book = Workbook()
    book.active.append(["code", "quantity"])
    book.active.append(["007", 3])
    book.create_sheet("Other").append(["unrelated"])
    content = io.BytesIO()
    book.save(content)
    book.close()
    source = TabularMergeSource("sales", "source.xlsx", lambda: content.getvalue())
    with pytest.raises(TabularMergeError) as error:
        with read_tabular_source_records(source) as (_columns, records, _sheet):
            list(records)
    assert error.value.code == "sheet_required"


@pytest.mark.parametrize("selector", ["named_table", "range"])
def test_workbook_selection_keeps_physical_row_lineage_and_ignores_unselected_formulas(selector):
    book = Workbook()
    sheet = book.active
    sheet.title = "Orders"
    sheet["A1"] = "Review title"
    sheet["A2"] = "=1/0"
    for cell, value in {"B3": "code", "C3": "quantity", "B4": "007", "C4": 3,
                        "B5": "008", "C5": 2, "B6": "TOTAL", "C6": 5}.items():
        sheet[cell] = value
    sheet.add_table(Table(displayName="OrdersTable", ref="B3:C6", totalsRowCount=1))
    book.create_sheet("Unrelated").append(["unrelated"])
    output = io.BytesIO()
    book.save(output)
    book.close()
    spec = join_spec()
    spec["datasets"][0].update(sheet="Orders")
    if selector == "named_table":
        spec["datasets"][0]["table_id"] = "OrdersTable"
    else:
        spec["datasets"][0].update(cell_range="B3:C5", header_row=3)
    result = run(spec, {
        "sales": ("orders.xlsx", output.getvalue()), "catalog": b"sku,price\n007,0.10\n008,0.20\n",
    })
    assert result["records"] == [{"code": "007", "amount": "0.30"}, {"code": "008", "amount": "0.40"}]
    assert result["lineage"][0]["sources"][1]["sheet"] == "Orders"
    assert result["lineage"][0]["sources"][1]["row_ranges"] == [[4, 4]]


def test_missing_formula_cache_is_not_an_empty_or_zero_value():
    book = Workbook()
    book.active.append(["code", "quantity"])
    book.active.append(["007", "=1+2"])
    output = io.BytesIO()
    book.save(output)
    book.close()
    with pytest.raises(TabularMergeError) as error:
        run(join_spec(), {
            "sales": ("orders.xlsx", output.getvalue()), "catalog": b"sku,price\n007,0.10\n",
        })
    assert error.value.code == "formula_cache_missing"


def test_source_loaders_are_closed_before_the_next_file_is_opened():
    active = []
    events = []

    @contextmanager
    def table(alias, columns, values):
        assert active == []
        active.append(alias)
        events.append(f"open:{alias}")
        try:
            yield columns, [(2, dict(zip(columns, values)))], None
        finally:
            active.pop()
            events.append(f"close:{alias}")

    result = calculate_relational_sources(join_spec(), {
        "sales": lambda: table("sales", ["code", "quantity"], ["007", "3"]),
        "catalog": lambda: table("catalog", ["sku", "price"], ["007", "0.10"]),
    }, limits=TabularMergeLimits())
    assert result["records"] == [{"code": "007", "amount": "0.30"}]
    assert events == ["open:sales", "close:sales", "open:catalog", "close:catalog"]


# The planner is told this grammar and these column rules; each claim below is pinned to the runtime.
GRAMMAR_EXAMPLES = {
    "copy": {"op": "copy", "source": "sales.code"},
    "round": {"op": "round", "value": {"source": "sales.quantity"}, "scale": 2, "mode": "half_even"},
    "case": {"op": "case", "branches": [{"when": {"value": True}, "then": "a"}], "else": "b"},
    "coalesce": {"op": "coalesce", "values": [{"source": "sales.code"}, ""]},
    "all": {"op": "all", "values": [{"value": True}]},
    "any": {"op": "any", "values": [{"value": False}]},
    "not": {"op": "not", "value": {"value": True}},
    "is_null": {"op": "is_null", "value": {"source": "sales.code"}},
    "in": {"op": "in", "value": {"source": "sales.code"}, "values": ["007"], "case_sensitive": False},
    **{
        name: {
            "op": name, "left": {"source": "sales.quantity"}, "right": 1, "value_type": "number",
            "case_sensitive": True,
        } for name in ("eq", "ne", "lt", "lte", "gt", "gte")
    },
    **{
        name: {"op": name, "values": [{"source": "sales.quantity"}, 2]}
        for name in ("add", "subtract", "multiply", "divide")
    },
}


def test_documented_expression_grammar_covers_every_runtime_operation():
    assert set(GRAMMAR_EXAMPLES) == TABULAR_TRANSFORMATION_ALLOWED_OPS | {"round"}
    assert all(name in RELATIONAL_EXPRESSION_GRAMMAR for name in GRAMMAR_EXAMPLES)
    description = relational_spec_schema()["description"]
    assert RELATIONAL_COLUMN_RULES in description and RELATIONAL_EXPRESSION_GRAMMAR in description


@pytest.mark.parametrize("name", sorted(GRAMMAR_EXAMPLES))
def test_every_documented_expression_shape_is_accepted(name):
    normalized = normalize_tabular_transformation_spec(
        transform(field("x", expression=GRAMMAR_EXAMPLES[name])),
    )
    assert normalized["fields"][0]["expression"]["op"] == name


def test_documented_reference_and_literal_forms_are_accepted():
    for expression in ({"source": "sales.code"}, {"value": 5}, 5, "text"):
        assert normalize_tabular_transformation_spec(transform(field("x", expression=expression)))
    chained = normalize_tabular_transformation_spec(transform(
        field("a", "sales.code"), field("b", expression={"field": "a"}),
    ))
    assert chained["deterministic_field_order"] == ["a", "b"]


@pytest.mark.parametrize("expression", [
    {"op": "round", "value": 1, "scale": 2},
    {"op": "add", "values": [1], "left": 1, "right": 2},
    {"op": "merge", "values": [1]},
    {"python": "__import__('os')"},
])
def test_expression_shapes_outside_the_documented_grammar_are_rejected(expression):
    with pytest.raises(TabularTransformationSpecError):
        normalize_tabular_transformation_spec(transform(field("x", expression=expression)))


def test_documented_division_and_empty_value_rules_match_the_runtime():
    sources = {"sales": b"code,quantity,note\n007,1,\n", "catalog": b"sku,price\n007,0.10\n"}

    def calculate(expression, value_type="number"):
        spec = join_spec()
        spec["steps"][1]["transform"] = transform(field("amount", expression=expression, value_type=value_type))
        spec["output"] = transform(field("amount", "priced.amount", value_type=value_type))
        return run(spec, sources)["records"]

    quotient = {"op": "divide", "values": [{"source": "sales.quantity"}, 3]}
    with pytest.raises(TabularTransformationEvaluationError) as error:
        calculate(quotient)
    assert error.value.code.startswith("numeric_operation_is_not_exact")
    assert calculate({"op": "round", "value": quotient, "scale": 2, "mode": "half_up"}) == [{"amount": 0.33}]
    empty = {"op": "add", "values": [{"source": "sales.note"}, 1]}
    with pytest.raises(TabularTransformationEvaluationError) as error:
        calculate(empty)
    assert error.value.code == "numeric_value_is_empty_or_boolean"
    guarded = {"op": "add", "values": [{"op": "coalesce", "values": [{"source": "sales.note"}, 0]}, 1]}
    assert calculate(guarded) == [{"amount": 1}]


HEADERS = {"sales": ["code", "quantity"], "catalog": ["sku", "price"]}
PIPELINE_SOURCES = {
    "sales": b"code,quantity\n007,3\n008,2\n", "catalog": b"sku,price\n007,0.10\n008,0.20\n",
}


def pipeline():
    return {
        "version": "tabular-relate-v1",
        "datasets": [{"alias": "sales", "document_id": "sales"}, {"alias": "catalog", "document_id": "catalog"}],
        "steps": [{
            "id": "keys", "op": "project", "input": "sales",
            "transform": transform(field("code", "sales.code"), field("units", "sales.quantity")),
        }, {
            "id": "matched", "op": "join", "left": "keys", "right": "catalog", "how": "left",
            "cardinality": "many_to_one", "on": [{"left": "keys.code", "right": "catalog.sku"}],
        }, {
            "id": "priced", "op": "derive", "input": "matched",
            "transform": transform(field("amount", expression={
                "op": "multiply", "values": [{"source": "keys.units"}, {"source": "catalog.price"}],
            })),
        }, {
            "id": "totals", "op": "aggregate", "input": "priced",
            "by": [{"name": "code", "column": "keys.code"}],
            "measures": [{"name": "amount", "operation": "sum", "column": "priced.amount"}],
        }],
        "result": "totals",
        "output": transform(field("code", "totals.code"), field("amount", "totals.amount")),
    }


def mutate(change):
    spec = pipeline()
    change(spec)
    return spec


COLUMN_FAULTS = {
    "join_right_typo": (
        lambda spec: spec["steps"][1]["on"][0].update(right="catalog.skuu"),
        {"role": "join_right_key", "category": "name_not_in_prefix", "step_index": 1, "step_op": "join"},
    ),
    "join_left_unqualified": (
        lambda spec: spec["steps"][1]["on"][0].update(left="code"),
        {"role": "join_left_key", "category": "unqualified_name", "step_index": 1, "step_op": "join"},
    ),
    "join_left_dropped_by_project": (
        lambda spec: spec["steps"][1]["on"][0].update(left="sales.code"),
        {"role": "join_left_key", "category": "prefix_not_in_input", "step_index": 1, "step_op": "join"},
    ),
    "join_right_names_a_left_column": (
        lambda spec: spec["steps"][1]["on"][0].update(right="keys.units"),
        {"role": "join_right_key", "category": "prefix_not_in_input", "step_index": 1, "step_op": "join"},
    ),
    "derive_unknown_column": (
        lambda spec: spec["steps"][2]["transform"]["fields"][0]["expression"]["values"].append({"source": "catalog.cost"}),
        {"role": "derive_expression", "category": "name_not_in_prefix", "step_index": 2, "step_op": "derive"},
    ),
    "aggregate_by_unknown_prefix": (
        lambda spec: spec["steps"][3]["by"][0].update(column="ghost.code"),
        {"role": "aggregate_by", "category": "unknown_prefix", "step_index": 3, "step_op": "aggregate"},
    ),
    "aggregate_measure_unqualified": (
        lambda spec: spec["steps"][3]["measures"][0].update(column="amount"),
        {"role": "aggregate_measure", "category": "unqualified_name", "step_index": 3, "step_op": "aggregate"},
    ),
    "output_uses_a_column_aggregate_dropped": (
        lambda spec: spec["output"]["fields"][1].update(expression={"source": "priced.amount"}),
        {"role": "output_expression", "category": "prefix_not_in_input", "step_op": "output"},
    ),
}


def test_the_documented_pipeline_passes_the_column_preflight_and_the_runtime():
    spec = normalize_relational_spec(pipeline())
    check_relational_columns(spec, HEADERS)
    assert run(pipeline(), PIPELINE_SOURCES)["records"] == [
        {"code": "007", "amount": "0.30"}, {"code": "008", "amount": "0.40"},
    ]


@pytest.mark.parametrize("name", sorted(COLUMN_FAULTS))
def test_column_preflight_and_runtime_reject_the_same_references_with_the_same_location(name):
    change, location = COLUMN_FAULTS[name]
    faulty = mutate(change)
    spec = normalize_relational_spec(faulty)
    expected = {"check": "column_missing", "missing_count": 1, **location}
    with pytest.raises(TabularRelationalError) as preflight:
        check_relational_columns(spec, HEADERS)
    assert preflight.value.code == "relational_column_missing" and preflight.value.detail == expected
    with pytest.raises((TabularRelationalError, TabularTransformationSpecError)) as runtime:
        run(faulty, PIPELINE_SOURCES)
    if isinstance(runtime.value, TabularRelationalError):
        assert runtime.value.code == "relational_column_missing" and runtime.value.detail == expected
    else:
        assert runtime.value.code == "tabular_transformation_spec_references_an_unknown_source_field"
    # An unknown header is never guessed: the same plan is left to the runtime check.
    check_relational_columns(spec, {})


def test_column_preflight_checks_only_sides_whose_complete_header_is_known():
    spec = normalize_relational_spec(mutate(COLUMN_FAULTS["join_right_typo"][0]))
    with pytest.raises(TabularRelationalError):
        check_relational_columns(spec, {"catalog": HEADERS["catalog"]})
    spec = normalize_relational_spec(mutate(COLUMN_FAULTS["join_left_unqualified"][0]))
    check_relational_columns(spec, {"catalog": HEADERS["catalog"]})


def duplicate_step_id(spec):
    spec["steps"][2]["id"] = "matched"


def add_filter(predicate):
    def change(spec):
        spec["steps"].append({"id": "kept", "op": "filter", "input": "priced", "predicate": predicate})
        spec["result"] = "kept"
        spec["output"] = transform(field("code", "keys.code"))
    return change


SEMANTIC_FAULTS = {
    "forward_reference": (lambda spec: spec["steps"][0].update(input="priced"), "relational_spec_invalid",
                          {"check": "unknown_input", "step_index": 0, "step_op": "project"}),
    "unused_source": (lambda spec: spec["datasets"].append({"alias": "extra", "document_id": "extra"}),
                      "relational_source_unused", {"check": "result_sources"}),
    "duplicate_alias": (lambda spec: spec["datasets"][1].update(alias="sales"), "relational_spec_invalid",
                        {"check": "duplicate_dataset"}),
    "duplicate_step_id": (duplicate_step_id, "relational_spec_invalid",
                          {"check": "duplicate_step_id", "step_index": 2, "step_op": "derive"}),
    "unknown_expression_operation": (
        lambda spec: spec["steps"][2]["transform"]["fields"][0].update(expression={"python": "x"}),
        "relational_spec_invalid",
        {"check": "transform", "step_index": 2, "step_op": "derive",
         "transform_code": "tabular_transformation_expression_operation_is_unsupported"},
    ),
    "invalid_predicate": (
        add_filter({"op": "nope"}), "relational_spec_invalid",
        {"check": "predicate", "step_index": 4, "step_op": "filter",
         "transform_code": "tabular_transformation_expression_operation_is_unsupported"},
    ),
    "invalid_output": (
        lambda spec: spec["output"]["fields"][0].update(expression={"op": "round", "value": 1}),
        "relational_spec_invalid",
        {"check": "output", "transform_code": "tabular_transformation_round_expression_has_invalid_properties"},
    ),
    "measure_without_column": (
        lambda spec: spec["steps"][3]["measures"][0].pop("column"), "relational_spec_invalid",
        {"check": "measure_column_required", "step_index": 3, "step_op": "aggregate"},
    ),
    "schema_violation": (lambda spec: spec.pop("output"), "relational_spec_invalid", {"check": "schema"}),
}


@pytest.mark.parametrize("name", sorted(SEMANTIC_FAULTS))
def test_rejected_relational_specs_name_the_failed_check(name):
    change, code, detail = SEMANTIC_FAULTS[name]
    with pytest.raises(TabularRelationalError) as error:
        normalize_relational_spec(mutate(change))
    assert (error.value.code, error.value.detail) == (code, detail)


def test_relational_failure_detail_never_contains_model_supplied_names():
    spec = pipeline()
    spec["steps"][2]["id"] = "private_marker_step"
    spec["steps"][2]["transform"]["fields"][0]["expression"] = {"private_marker_operation": "x"}
    with pytest.raises(TabularRelationalError) as error:
        normalize_relational_spec(spec)
    assert error.value.detail["check"] == "transform"
    text = repr(error.value.detail) + repr(native_error_diagnostics(error.value)) + str(error.value)
    assert "private_marker" not in text


def test_document_selection_mismatch_is_distinguished_from_other_invalid_specs():
    with pytest.raises(TabularRelationalError) as error:
        normalize_relational_spec(pipeline(), ["catalog", "sales"])
    assert error.value.code == "relational_selection_invalid"
    assert error.value.detail == {"check": "document_ids_mismatch"}


def test_failure_detail_keeps_only_closed_tokens_and_counts():
    assert safe_native_detail({
        "check": "column_missing", "role": "Join Left Key", "category": "unqualified_name", "step_index": 2,
        "step_op": "join", "transform_code": "x" * 81, "missing_count": True, "free_text": "token", "extra": 7,
    }) == {"check": "column_missing", "category": "unqualified_name", "step_index": 2, "step_op": "join"}
    assert native_error_diagnostics(TabularRelationalError("relational_column_missing", detail={
        "check": "column_missing", "role": "join_left_key", "missing_count": 2, "step_index": 1,
    })) == {
        "native_check": "column_missing", "native_role": "join_left_key",
        "native_missing_count": 2, "native_step_index": 1,
    }
    assert native_error_diagnostics(ValueError("PRIVATE")) == {}


BAD_TRANSFORM = {"version": "unsupported", "fields": [], "private_marker": True}
# Each step keeps the operation that names its branch and breaks that branch in several ways at once,
# so that an alternative for another operation fails no more often than the intended one.
SEVERAL_FAULTS = {
    "derive": (2, lambda step: step.update(transform=dict(BAD_TRANSFORM))),
    "derive_with_a_step_property_too": (
        2, lambda step: step.update(transform=dict(BAD_TRANSFORM), private_marker_step=True),
    ),
    "project": (0, lambda step: step.update(transform=dict(BAD_TRANSFORM))),
    "aggregate": (3, lambda step: step.update(
        by=[{"name": "code", "private_marker": 1}],
        measures=[{"name": "amount", "operation": "private_marker_operation"}],
    )),
}


def located(spec):
    (error,) = Draft202012Validator(relational_spec_schema()).iter_errors(spec)
    return schema_error_location(error)


@pytest.mark.parametrize("stored", ["price", " price ", "Unit  Price", "Unit\u00a0Price", "cafe\u0301"])
def test_the_reader_names_a_column_the_way_the_planning_preflight_expects(stored):
    source = TabularMergeSource("d", "d.csv", lambda: f"code,{stored}\n1,2\n".encode("utf-8"))
    with read_tabular_source_records(source) as (columns, _records, _selected):
        assert list(columns) == ["code", display_header_name(stored)]


@pytest.mark.parametrize("name", sorted(SEVERAL_FAULTS))
def test_a_step_with_several_faults_is_located_in_the_operation_it_names(name):
    index, damage = SEVERAL_FAULTS[name]
    spec = pipeline()
    operation = spec["steps"][index]["op"]
    damage(spec["steps"][index])
    location = located(spec)
    assert location["argument_branch"] == operation
    # Another operation's fields must never be offered as the correction.
    assert "predicate" not in location.get("allowed_properties", []) + location.get("missing_properties", [])
    assert "private_marker" not in repr(location)


def test_a_step_that_does_not_name_a_known_operation_is_located_by_how_close_it_is():
    spec = pipeline()
    spec["steps"][2]["op"] = "private_marker_operation"
    location = located(spec)
    assert "argument_branch" not in location and location["argument_keyword"] == "const"
    assert location["allowed_values"] == ["join", "filter", "derive", "project", "aggregate"]
    del spec["steps"][2]["op"]
    location = located(spec)
    assert "argument_branch" not in location
    assert (location["argument_keyword"], location["missing_properties"]) == ("required", ["op"])


def test_runtime_transformation_failures_have_a_stable_code_and_a_step_location():
    with pytest.raises(TabularTransformationEvaluationError) as error:
        run(join_spec(), {"sales": b"code,quantity\n007,\n", "catalog": b"sku,price\n007,0.10\n"})
    assert error.value.code == "numeric_value_is_empty_or_boolean"
    assert error.value.detail == {"check": "step_evaluation", "step_op": "derive", "step_index": 1}
    assert native_error_diagnostics(error.value) == {
        "native_check": "step_evaluation", "native_step_op": "derive", "native_step_index": 1,
    }
    spec = join_spec()
    spec["output"] = transform(field("rate", expression={
        "op": "divide", "values": [1, {"source": "priced.amount"}],
    }, value_type="number"))
    with pytest.raises(TabularTransformationEvaluationError) as error:
        run(spec, {"sales": b"code,quantity\n007,0\n", "catalog": b"sku,price\n007,0.10\n"})
    assert error.value.code == "division_by_zero_is_not_allowed"
    assert error.value.detail == {"check": "output_evaluation", "step_op": "output"}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
