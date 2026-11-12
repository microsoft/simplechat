# test_tabular_relational_calculations.py
"""
Functional tests for complete multi-file calculations and per-row lineage.
Version: 0.261.437
Implemented in: 0.261.437

These offline cases use unrelated schemas, precise source values and the real
CSV/Excel readers. They do not invoke a model or change source documents.
"""

from contextlib import contextmanager
from dataclasses import replace
import io

import pytest
from openpyxl import Workbook
from openpyxl.worksheet.table import Table

from functions_tabular_merge import TabularMergeError, TabularMergeLimits, TabularMergeSource, read_tabular_source_records
from functions_tabular_relational import (
    TabularRelationalError, calculate_relational_sources, normalize_relational_spec,
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
    spec = join_spec()
    source = TabularMergeSource("sales", "source.xlsx", lambda: content.getvalue())
    with pytest.raises(TabularMergeError) as error:
        with read_tabular_source_records(source):
            raise AssertionError("An ambiguous worksheet must not be used.")
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


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
