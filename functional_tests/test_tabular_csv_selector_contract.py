"""
Offline regressions for format-aware CSV tabular selectors and retry bounds.
Version: 0.261.429
Implemented in: 0.261.429

The test extracts the production method bodies so CSV behavior is exercised
without importing Flask, Azure, or the configured Cosmos client.
"""

import ast
import copy
import io
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

import pandas
import pytest


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
PLUGIN = APP / "semantic_kernel_plugins" / "tabular_processing_plugin.py"
ROUTE = APP / "route_backend_chats.py"


def _plugin_harness():
    tree = ast.parse(PLUGIN.read_text(encoding="utf-8"), filename=str(PLUGIN))
    selection_error = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "TabularSelectionError"
    )
    plugin_class = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "TabularProcessingPlugin"
    )
    method_names = {
        "_normalize_table_selectors",
        "_tabular_error_payload",
        "_read_tabular_blob_to_dataframe",
    }
    methods = [
        copy.deepcopy(node)
        for node in plugin_class.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in method_names
    ]
    harness_class = ast.ClassDef(
        name="CsvHarness",
        bases=[],
        keywords=[],
        body=methods,
        decorator_list=[],
    )
    module = ast.Module(
        body=[copy.deepcopy(selection_error), harness_class],
        type_ignores=[],
    )
    namespace = {
        "copy": copy,
        "io": io,
        "pandas": pandas,
        "Optional": Optional,
        "logging": __import__("logging"),
        "read_tabular_csv": lambda source, **kwargs: pandas.read_csv(source, **kwargs),
        "log_event": lambda *args, **kwargs: None,
    }
    exec(compile(ast.fix_missing_locations(module), str(PLUGIN), "exec"), namespace)
    harness = namespace["CsvHarness"]()
    harness._df_cache = {}
    harness._assert_blob_screening_access = lambda *args, **kwargs: None
    harness._resolve_sheet_selection = lambda *args, **kwargs: (
        None,
        {
            "is_workbook": False,
            "blob_etag": "csv-etag",
            "sheet_names": [],
        },
    )
    harness._download_tabular_blob_bytes = lambda *args, **kwargs: (
        b"Region,Device,Amount\nNorth,Phone,10\nSouth,Phone,20\nNorth,Tablet,5\n"
    )
    harness._get_excel_engine = lambda blob_name: None
    harness._normalize_dataframe_columns = lambda dataframe: dataframe.copy()
    harness._last_table_reads = {}
    return harness, namespace["TabularSelectionError"]


def _route_helpers():
    tree = ast.parse(ROUTE.read_text(encoding="utf-8"), filename=str(ROUTE))
    names = {
        "get_tabular_invocation_result_payload",
        "get_tabular_invocation_error_message",
        "get_non_retryable_tabular_invocation_failures",
        "get_remaining_tabular_invocation_budget",
        "append_unique_tabular_invocations",
    }
    functions = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    constant = next(
        node for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name)
            and target.id == "TABULAR_SK_MAX_INVOCATIONS_PER_REQUEST"
            for target in node.targets
        )
    )
    namespace = {"json": json}
    exec(
        compile(
            ast.fix_missing_locations(ast.Module(body=[constant, *functions], type_ignores=[])),
            str(ROUTE),
            "exec",
        ),
        namespace,
    )
    return namespace


@pytest.mark.parametrize("header_row", [None, "", " ", 0, "0"])
def test_csv_omits_excel_only_header_selector_and_returns_exact_total(header_row):
    harness, _error_type = _plugin_harness()
    dataframe = harness._read_tabular_blob_to_dataframe(
        "documents",
        "user/amounts.csv",
        header_row=header_row,
    )

    assert dataframe.columns.tolist() == ["Region", "Device", "Amount"]
    assert pandas.to_numeric(dataframe["Amount"]).sum() == 35


@pytest.mark.parametrize("header_row", [1, 0.0, True, "one"])
def test_csv_rejects_real_or_invalid_header_selector_without_retry(header_row):
    harness, error_type = _plugin_harness()

    with pytest.raises(error_type) as exc:
        harness._read_tabular_blob_to_dataframe(
            "documents",
            "user/amounts.csv",
            header_row=header_row,
        )

    payload = harness._tabular_error_payload(exc.value)
    assert payload["retryable"] in {False, True}
    if type(header_row) is int and header_row == 1:
        assert payload == {
            "error": (
                "Sheet, table, range, and header selectors apply only to Excel "
                "workbooks. Omit those arguments for CSV and TSV files."
            ),
            "error_code": "tabular_selector_not_applicable",
            "selection_required": True,
            "table_choices": [],
            "retryable": False,
            "source_format": "csv",
            "corrected_arguments": {
                "sheet_name": None,
                "sheet_index": None,
                "table_id": None,
                "cell_range": None,
                "header_row": None,
            },
        }


def test_excel_zero_header_semantics_remain_explicit():
    harness, _error_type = _plugin_harness()
    table_id, cell_range, header_row = harness._normalize_table_selectors(
        header_row=0,
    )

    assert table_id is None
    assert cell_range is None
    assert header_row == 0


def test_non_retryable_selector_failures_stop_and_budget_is_request_wide():
    helpers = _route_helpers()
    invocation = SimpleNamespace(
        function_name="aggregate_column",
        result=json.dumps({
            "error": "CSV does not accept Excel selectors.",
            "error_code": "tabular_selector_not_applicable",
            "retryable": False,
            "source_format": "csv",
        }),
        error_message=None,
    )

    assert helpers["get_non_retryable_tabular_invocation_failures"]([invocation]) == [{
        "function_name": "aggregate_column",
        "error_message": "CSV does not accept Excel selectors.",
        "error_code": "tabular_selector_not_applicable",
        "source_format": "csv",
    }]
    assert helpers["get_remaining_tabular_invocation_budget"]([]) == 24
    assert helpers["get_remaining_tabular_invocation_budget"]([object()] * 24) == 0
    assert helpers["get_remaining_tabular_invocation_budget"]([object()] * 25) == 0
    first = SimpleNamespace(invocation_id="invocation-1")
    second = SimpleNamespace(invocation_id="invocation-2")
    duplicate_read = SimpleNamespace(invocation_id="invocation-1")
    assert helpers["append_unique_tabular_invocations"](
        [first],
        [duplicate_read, second],
    ) == [first, second]
