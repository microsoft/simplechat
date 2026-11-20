#!/usr/bin/env python3
# test_tabular_formatted_numbers_and_column_profile.py
"""
Functional test for formatted numbers in tabular calculations and the per-column value profile.
Version: 0.261.470
Implemented in: 0.261.470

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

from functions_tabular_merge import (  # noqa: E402
    TabularMergeLimits, TabularMergeSource, prepare_tabular_source_context, read_tabular_source_records,
)
from functions_tabular_relational import (  # noqa: E402
    RELATIONAL_EXPRESSION_GRAMMAR, calculate_relational_sources,
)
from functions_tabular_transformations import (  # noqa: E402
    TABULAR_VALUE_KINDS, TabularTransformationEvaluationError, read_formatted_number, tabular_value_kind,
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
])
def test_a_formatted_number_is_read_as_the_number_it_writes(text, expected):
    assert read_formatted_number(text) == Decimal(expected)
    assert tabular_value_kind(text) == "numeric_text"


@pytest.mark.parametrize("text", [
    "1.250,00", "1,25", "12,34,567", "USD 5", "about 5", "$12%", "(-5)", "--5", "$", "$$5", "N/A", "5 units",
])
def test_text_with_more_than_one_reading_or_none_is_not_a_number(text):
    assert read_formatted_number(text) is None
    assert tabular_value_kind(text) == "text"


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
        {"column": "amount", "numeric_text": 3, "text": 1},
        {"column": "paid_on", "blank": 1, "date_text": 3},
        {"column": "note", "blank": 3, "text": 1},
    ]
    # The profile and the calculation agree cell by cell: what it counts as numeric is summed,
    # and the one cell it counts as text is the one that stops a sum.
    assert all(set(item) - {"column"} <= set(TABULAR_VALUE_KINDS) for item in context["column_values"])
    with pytest.raises(TabularTransformationEvaluationError):
        _run(_total_spec(), content)
    assert _run(_total_spec(), content.replace(b"D,pending", b"D,0"))["records"] == [{"total": "1350.25"}]
    # No cell value is in the profile.
    assert "pending" not in json.dumps(context["column_values"]) and "late" not in json.dumps(context["column_values"])


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


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
