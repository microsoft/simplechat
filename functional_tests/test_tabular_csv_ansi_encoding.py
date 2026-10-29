# test_tabular_csv_ansi_encoding.py
#!/usr/bin/env python3
"""
Functional test for ANSI-encoded CSV tabular analysis.
Version: 0.261.030
Implemented in: 0.261.030

This test ensures Windows-1252 CSV content is decoded correctly for metadata
and bounded tabular row queries, and that repeated tool failures are rerouted.
"""

import io
import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APPLICATION_DIR = os.path.join(ROOT_DIR, "application", "single_app")
if APPLICATION_DIR not in sys.path:
    sys.path.insert(0, APPLICATION_DIR)

from functions_tabular_csv_query import read_tabular_csv
from test_support.versioning import assert_app_version_at_least


ROUTE_BACKEND_CHATS_FILE = os.path.join(
    APPLICATION_DIR,
    "route_backend_chats.py",
)


def test_windows1252_csv_content_is_read_without_replacement_characters():
    """Verify ANSI bytes survive CSV parsing as their intended characters."""
    csv_bytes = "Name,Comment\nAndre,Crème brûlée\n".encode("cp1252")

    dataframe = read_tabular_csv(
        io.BytesIO(csv_bytes),
        keep_default_na=False,
        dtype=str,
    )

    assert dataframe.iloc[0]["Comment"] == "Crème brûlée"
    assert "�" not in dataframe.iloc[0]["Comment"]


def test_tabular_analysis_routes_repeated_failures_without_cutting_analysis_depth():
    """Verify analysis retains depth while repeated calls receive routing feedback."""
    with open(ROUTE_BACKEND_CHATS_FILE, "r", encoding="utf-8") as file_handle:
        route_source = file_handle.read()

    execution_settings_start = route_source.index("execution_settings = AzureChatPromptExecutionSettings(")
    execution_settings_end = route_source.index("result = None", execution_settings_start)
    tabular_analysis_source = route_source[execution_settings_start:execution_settings_end]
    assert tabular_analysis_source.count("maximum_auto_invoke_attempts=20") == 2
    assert "get_repeated_tabular_invocation_failures" in route_source
    assert "Do not repeat that exact call." in route_source
    assert "Tabular analysis needs a different query path" in route_source
    assert_app_version_at_least("0.261.030")


if __name__ == "__main__":
    test_windows1252_csv_content_is_read_without_replacement_characters()
    test_tabular_analysis_routes_repeated_failures_without_cutting_analysis_depth()
    print("All ANSI CSV tabular regression tests passed")
