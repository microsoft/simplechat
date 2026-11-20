#!/usr/bin/env python3
# test_tabular_formatted_numbers_and_column_profile.py
"""
Functional test for formatted numbers in tabular calculations and the per-column value profile.
Version: 0.261.471
Implemented in: 0.261.470
ISO currency codes, declared comma-decimal columns and listed text values added in: 0.261.471

This test ensures that a number written with presentation marks is calculated as a number,
that text which writes no number is still refused, that the preparation tells the author of a
calculation what each column's cells hold using the same reading the calculation applies, and
that this profile does not grow with the number of rows.
"""

import json
import os
import sys
from decimal import Decimal

import pytest

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import functions_tabular_merge as merge  # noqa: E402
from functions_tabular_merge import (  # noqa: E402
    TabularMergeLimits, TabularMergeSource, prepare_tabular_source_context, read_tabular_source_records,
)
from functions_tabular_relational import (  # noqa: E402
    RELATIONAL_EXPRESSION_GRAMMAR, TabularRelationalError, calculate_relational_sources,
    relational_spec_schema,
)
from functions_tabular_transformations import (  # noqa: E402
    ISO_CURRENCY_CODES, TABULAR_VALUE_KINDS, TabularTransformationEvaluationError, read_formatted_number,
    tabular_value_kind,
)


def _field(name, source=None, *, expression=None, value_type="string"):
    return {
        "name": name, "type": value_type, "nullable": False,
        "expression": {"source": source} if expression is None else expression,
    }


def _transform(*fields):
    return {"version": "tabular-transform-v2", "fields": list(fields)}


def _run(spec, content):
    source = TabularMergeSource("ledger", "ledger.csv", lambda: content)
    limits = TabularMergeLimits()
    return calculate_relational_sources(
        spec, {"ledger": lambda: read_tabular_source_records(source, limits=limits)}, limits=limits,
    )


def _total_spec(column="ledger.amount"):
    return {
        "version": "tabular-relate-v1",
        "datasets": [{"alias": "ledger", "document_id": "ledger"}],
        "steps": [{
            "id": "totals", "op": "aggregate", "input": "ledger", "by": [],
            "measures": [{"name": "total", "operation": "sum", "column": column}],
        }],
        "result": "totals", "output": _transform(_field("total", "totals.total")),
    }


@pytest.mark.parametrize("text,expected", [
    ("1,250.00", "1250.00"), ("$400", "400"), ("(300)", "-300"), ("12%", "0.12"),
    ("-$1,200.50", "-1200.50"), ("$-1,200.50", "-1200.50"), ("€ 5", "5"), ("5 €", "5"),
    ("300-", "-300"), ("(12.5%)", "-0.125"), ("£.50", "0.50"), ("1,234,567", "1234567"), ("+7", "7"),
    ("USD 5", "5"), ("5 EUR", "5"), ("EUR5", "5"), ("(USD 300)", "-300"), ("CHF 1,250.50", "1250.50"),
    ("1 250.00", "1250.00"),
])
def test_a_formatted_number_is_read_as_the_number_it_writes(text, expected):
    assert read_formatted_number(text) == Decimal(expected)
    assert tabular_value_kind(text) == "numeric_text"


@pytest.mark.parametrize("text", [
    "12,34,567", "about 5", "$12%", "(-5)", "--5", "$", "$$5", "N/A", "5 units", "USDA 5", "usd 5",
    "USD EUR 5", "1.2.3",
])
def test_text_that_writes_no_number_is_not_a_number_under_either_convention(text):
    assert read_formatted_number(text) is None and read_formatted_number(text, ",") is None
    assert tabular_value_kind(text) == "text"


@pytest.mark.parametrize("text,expected", [
    ("1.250,00", "1250.00"), ("1,25", "1.25"), ("12,75", "12.75"), ("1 250,00", "1250.00"),
    ("-1.234.567,89 €", "-1234567.89"), ("12,5%", "0.125"), ("EUR 3,5", "3.5"),
])
def test_a_decimal_comma_is_read_only_when_that_convention_is_stated(text, expected):
    assert read_formatted_number(text) is None
    assert read_formatted_number(text, ",") == Decimal(expected)
    assert tabular_value_kind(text) == "comma_decimal_text"


def test_one_cell_cannot_say_which_convention_it_follows():
    # The same characters write two numbers; nothing in the cell chooses between them.
    assert read_formatted_number("1,250") == Decimal("1250")
    assert read_formatted_number("1,250", ",") == Decimal("1.250")
    assert read_formatted_number("1.250") == Decimal("1.250")
    assert read_formatted_number("1.250", ",") == Decimal("1250")
    assert tabular_value_kind("1,250") == "numeric_text"
    assert len(ISO_CURRENCY_CODES) > 150 and {"USD", "EUR", "GBP", "CHF", "JPY"} <= ISO_CURRENCY_CODES


def test_a_calculation_declares_a_comma_decimal_column_and_every_cell_is_read_that_way():
    content = b'vendor,amount,units\nA,"1.250,00","1,250"\nB,"12,75","2,500"\nC,"-300,25 \xe2\x82\xac",10\n'
    undeclared = _total_spec()
    with pytest.raises(TabularTransformationEvaluationError):
        _run(undeclared, content)
    declared = _total_spec()
    declared["datasets"][0]["comma_decimal_columns"] = ["amount"]
    result = _run(declared, content)
    assert result["records"] == [{"total": "962.50"}]
    assert result["coverage"]["sources"][0]["comma_decimal_columns"] == ["amount"]
    # The declaration is per column: units is not declared, so "1,250" is still 1250 there.
    units = _total_spec("ledger.units")
    units["datasets"][0]["comma_decimal_columns"] = ["amount"]
    assert _run(units, content)["records"] == [{"total": "3760"}]
    both = _total_spec("ledger.units")
    both["datasets"][0]["comma_decimal_columns"] = ["amount", "units"]
    assert _run(both, content)["records"] == [{"total": "13.750"}]
    # A declared column that does not exist is refused, and the author is told which.
    missing = _total_spec()
    missing["datasets"][0]["comma_decimal_columns"] = ["betrag"]
    with pytest.raises(TabularRelationalError) as refused:
        _run(missing, content)
    assert refused.value.code == "relational_column_missing"
    assert refused.value.feedback["missing_columns"] == ["ledger.betrag"]
    # A cell written with a decimal point contradicts the declaration. It stops the
    # calculation, whether or not that column is used, and is never read the other way.
    for contradiction in (b'"1,250.00"', b'"12.5"'):
        mixed = content.replace(b'"12,75"', contradiction)
        with pytest.raises(TabularTransformationEvaluationError) as stopped:
            _run(declared, mixed)
        assert stopped.value.detail["role"] == "comma_decimal_column"
    # Text that writes no number is not a contradiction; it stops only a numeric use of it.
    worded = content.replace(b'"12,75"', b'"N/A"')
    with pytest.raises(TabularTransformationEvaluationError) as stopped:
        _run(declared, worded)
    assert stopped.value.detail.get("role") == "aggregate_measure"
    units_only = _total_spec("ledger.units")
    units_only["datasets"][0]["comma_decimal_columns"] = ["amount"]
    assert _run(units_only, worded)["records"] == [{"total": "3760"}]
    selector = relational_spec_schema()["properties"]["datasets"]["items"]["properties"]
    assert "comma_decimal_columns" in selector


def test_a_calculation_sums_formatted_numbers_exactly():
    content = 'vendor,amount\nA,"$1,250.00"\nB,(300)\nC,400.25\nD,"-$1,000"\nE,12%\n'.encode()
    assert _run(_total_spec(), content)["records"] == [{"total": "350.37"}]
    # Arithmetic and a number-typed comparison read the same text the same way.
    spec = {
        "version": "tabular-relate-v1",
        "datasets": [{"alias": "ledger", "document_id": "ledger"}],
        "steps": [{
            "id": "large", "op": "filter", "input": "ledger",
            "predicate": {
                "op": "gt", "left": {"source": "ledger.amount"}, "right": {"value": 1000},
                "value_type": "number",
            },
        }, {
            "id": "doubled", "op": "derive", "input": "large",
            "transform": _transform(_field("twice", expression={
                "op": "multiply", "left": {"source": "ledger.amount"}, "right": {"value": 2},
            })),
        }],
        "result": "doubled",
        "output": _transform(_field("vendor", "ledger.vendor"), _field("twice", "doubled.twice")),
    }
    assert _run(spec, content)["records"] == [{"vendor": "A", "twice": "2500.00"}]


def test_text_that_writes_no_number_still_stops_the_calculation():
    content = b"vendor,amount\nA,100\nB,pending\n"
    with pytest.raises(TabularTransformationEvaluationError) as refused:
        _run(_total_spec(), content)
    assert refused.value.code == "numeric_value_is_invalid"
    assert "pending" not in json.dumps(refused.value.detail)


def _profile(content, **request):
    source = TabularMergeSource("ledger", "ledger.csv", lambda: content)
    return prepare_tabular_source_context(source, {
        "alias": "ledger", "document_id": "ledger", "context_columns": [], "key_profiles": [], **request,
    }, limits=TabularMergeLimits())


def test_preparation_says_what_every_column_holds_without_being_asked():
    content = (
        'vendor,amount,paid_on,note\n'
        'A,"$1,250.00",2026-09-01,\n'
        'B,(300),2026-09-02,late\n'
        'C,400.25,,\n'
        'D,pending,2026-09-04,\n'
    ).encode()
    context = _profile(content)
    assert context["context_columns"] == []
    assert context["column_values"] == [
        {"column": "vendor", "text": 4},
        {
            "column": "amount", "numeric_text": 3, "text": 1,
            "text_values": [{"value": "pending", "count": 1}],
        },
        {"column": "paid_on", "blank": 1, "date_text": 3},
        {"column": "note", "blank": 3, "text": 1},
    ]
    # The profile and the calculation agree cell by cell: what it counts as numeric is summed,
    # and the one cell it counts as text is the one that stops a sum.
    assert all(
        set(item) - {"column", "text_values"} <= set(TABULAR_VALUE_KINDS) for item in context["column_values"]
    )
    with pytest.raises(TabularTransformationEvaluationError):
        _run(_total_spec(), content)
    assert _run(_total_spec(), content.replace(b"D,pending", b"D,0"))["records"] == [{"total": "1350.25"}]
    # Text is listed only where it sits among numbers: a column of text alone is counted, not listed.
    assert "late" not in json.dumps(context["column_values"]) and '"A"' not in json.dumps(context["column_values"])


def test_the_text_among_a_columns_numbers_is_listed_with_how_often_it_occurs():
    rows = ["100"] * 40 + ["N/A"] * 5 + ["pending"] * 2 + ["TBD"] + ["x" * 121] * 3
    context = _profile(("amount\n" + "\n".join(rows) + "\n").encode())
    assert context["column_values"] == [{
        "column": "amount", "numeric_text": 40, "text": 11, "text_longer_than_listed": 3,
        "text_values": [
            {"value": "N/A", "count": 5}, {"value": "pending", "count": 2}, {"value": "TBD", "count": 1},
        ],
    }]
    # With the values named, a calculation can set them aside by name and sum the rest.
    spec = _total_spec()
    spec["steps"].insert(0, {
        "id": "known", "op": "filter", "input": "ledger",
        "predicate": {"op": "not", "value": {
            "op": "in", "value": {"source": "ledger.amount"}, "values": ["N/A", "pending", "TBD", "x" * 121],
        }},
    })
    spec["steps"][1]["input"] = "known"
    assert _run(spec, ("amount\n" + "\n".join(rows) + "\n").encode())["records"] == [{"total": "4000"}]


def test_each_bound_on_the_listed_text_is_reported_not_applied_silently(monkeypatch):
    many = ["7"] + [f"code-{index}" for index in range(merge.TABULAR_COLUMN_TEXT_VALUES_MAX + 1)]
    context = _profile(("amount\n" + "\n".join(many) + "\n").encode())
    assert context["column_values"] == [{
        "column": "amount", "numeric_text": 1, "text": merge.TABULAR_COLUMN_TEXT_VALUES_MAX + 1,
        "text_values_not_listed": "more_distinct_values_than_listed",
    }]
    monkeypatch.setattr(merge, "TABULAR_COLUMN_TEXT_VALUES_MAX_BYTES", 40)
    context = _profile(b"first,second\n1,2\nN/A,pending approval\n")
    assert context["column_values"] == [
        {"column": "first", "numeric_text": 1, "text": 1, "text_values": [{"value": "N/A", "count": 1}]},
        {"column": "second", "numeric_text": 1, "text": 1, "text_values_not_listed": "table_limit"},
    ]


def test_the_profile_counts_cells_that_write_two_different_numbers():
    context = _profile(b'amount,price\n"1,250","1.250,00"\n"2,500","12,75"\n17,"3,5"\n')
    assert context["column_values"] == [
        # Both cells read with a point and with a comma, as different numbers; 17 reads one way.
        {"column": "amount", "numeric_text": 3, "two_readings": 2},
        # No cell reads with a point at all: only the comma convention fits this column.
        {"column": "price", "comma_decimal_text": 3},
    ]


def test_the_profile_does_not_grow_with_the_number_of_rows():
    def table(rows):
        lines = ["vendor,amount,region"] + [f'V{index},"$1,{index % 900 + 100}.00",R{index % 7}' for index in range(rows)]
        return ("\n".join(lines) + "\n").encode()

    small, large = _profile(table(50)), _profile(table(50_000))
    assert large["physical_row_count"] == 50_000
    assert large["column_values"] == [
        {"column": "vendor", "text": 50_000},
        {"column": "amount", "numeric_text": 50_000},
        {"column": "region", "text": 50_000},
    ]
    size = lambda context: len(json.dumps(context, ensure_ascii=False).encode("utf-8"))
    # A thousand times the rows adds only the digits of the counts.
    assert size(large) - size(small) < 100 and size(large) < 1024


def test_the_language_description_states_what_a_numeric_operand_is():
    assert "text that writes one" in RELATIONAL_EXPRESSION_GRAMMAR
    assert "value_type number" in RELATIONAL_EXPRESSION_GRAMMAR
    assert "comma_decimal_columns" in RELATIONAL_EXPRESSION_GRAMMAR


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
