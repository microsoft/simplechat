# test_excel_preview_route.py
"""
Functional tests for the real bounded Excel/CSV preview handler.
Version: 0.261.405
Implemented in: 0.261.405

The route body and shared reader execute against real workbook packages.
Only authenticated-document lookup and external blob I/O are isolated.
"""

import ast
import io
from pathlib import Path
import sys
from types import SimpleNamespace
import zipfile

from flask import Flask, jsonify, request
import pandas
import pytest

APP = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP))

from content_screening.contracts import ScreeningError  # noqa: E402
from excel_workbook_reader import ExcelWorkbookReader, build_excel_table_preview  # noqa: E402
from test_excel_table_discovery_and_scale import five_tables  # noqa: E402


__all__ = ["five_tables"]


def preview_app(content, filename="tables.xlsx", allowed=True, failure=None):
    source = (APP / "route_enhanced_citations.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = {"reads": 0, "lookups": 0, "errors": []}
    app = Flask(__name__)
    document = {"id": "workbook", "file_name": filename, "user_id": "owner"}

    def get_document(user_id, document_id):
        calls["lookups"] += 1
        assert user_id == "owner" and document_id == "workbook"
        return (jsonify(document), 200) if allowed else (jsonify({"error": "Access denied."}), 403)

    def read_bytes(doc, **kwargs):
        calls["reads"] += 1
        if failure is not None:
            raise failure
        return document, content

    namespace = {
        "pandas": pandas, "io": io, "zipfile": zipfile, "jsonify": jsonify, "request": request,
        "get_document": get_document, "get_current_user_id": lambda: "owner",
        "get_settings": lambda: {}, "ScreeningError": ScreeningError,
        "build_excel_table_preview": build_excel_table_preview,
        "read_available_document_bytes": read_bytes,
        "_resolve_document_blob_reference": lambda doc: ("container", "source"),
        "_log_enhanced_citations_error": lambda *args, **kwargs: calls["errors"].append(args),
        "CLIENTS": {"storage_account_office_docs_client": SimpleNamespace(
            get_blob_client=lambda **kwargs: SimpleNamespace(
                get_blob_properties=lambda: SimpleNamespace(size=len(content)),
            ),
        )},
    }
    names = {"_sanitize_tabular_preview_value", "_serialize_tabular_preview_table", "_preview_integer"}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            exec(compile(ast.Module(body=[node], type_ignores=[]), "preview_helpers", "exec"), namespace)
    registrar = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "register_enhanced_citations_routes")
    handler = next(node for node in registrar.body if isinstance(node, ast.FunctionDef) and node.name == "get_enhanced_citation_tabular_preview")
    handler.decorator_list = []
    exec(compile(ast.Module(body=[handler], type_ignores=[]), "preview_route", "exec"), namespace)
    app.add_url_rule("/preview", view_func=namespace[handler.name])
    return app.test_client(), calls


def test_real_route_selects_each_table_and_retains_physical_rows(five_tables):
    path, _, origins = five_tables
    with ExcelWorkbookReader(path) as reader:
        tables = reader.build_manifest()["sheets"][0]["tables"]
    client, calls = preview_app(path.read_bytes())
    for index, (table, (header_row, _)) in enumerate(zip(tables, origins), start=1):
        response = client.get("/preview", query_string={
            "doc_id": "workbook", "sheet_name": "Five tables", "table_id": table["id"],
            "start_row": "2", "max_rows": "1",
        })
        assert response.status_code == 200
        payload = response.get_json()
        assert payload["columns"] == ["Case", "Amount"]
        assert payload["rows"] == [[f"T{index}-3", str(index * 100 + 3)]]
        assert payload["row_numbers"] == [header_row + 3]
        assert payload["table_count"] == 5 and payload["has_more"] is False
    assert calls["reads"] == 5


def test_csv_paging_keeps_headers_and_reaches_late_records():
    content = ("Case,Amount\n" + "".join(f"C{index},{index}\n" for index in range(1, 15001))).encode()
    client, _ = preview_app(content, "data.csv")
    response = client.get("/preview", query_string={"doc_id": "workbook", "start_row": "14999", "max_rows": "2"})
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["columns"] == ["Case", "Amount"]
    assert payload["rows"] == [["C15000", "15000"]]
    assert payload["total_rows"] == 15000 and payload["row_numbers"] == [15001]


@pytest.mark.parametrize("query", [{"max_rows": "0"}, {"max_rows": "501"}, {"start_row": "-1"}, {"header_row": "bad"}])
def test_invalid_windows_are_explicit_errors(query):
    client, calls = preview_app(b"Case,Amount\nA,1\n", "data.csv")
    response = client.get("/preview", query_string={"doc_id": "workbook", **query})
    assert response.status_code == 400
    assert calls["reads"] == 0 and calls["errors"]


def test_permission_denial_precedes_blob_access():
    client, calls = preview_app(b"private", allowed=False)
    response = client.get("/preview", query_string={"doc_id": "workbook"})
    assert response.status_code == 403
    assert calls["reads"] == 0


def test_provider_failure_never_reaches_browser():
    client, calls = preview_app(b"private", failure=RuntimeError("private-provider-secret-canary"))
    response = client.get("/preview", query_string={"doc_id": "workbook"})
    assert response.status_code == 500
    assert "private-provider-secret-canary" not in response.get_data(as_text=True)
    assert calls["errors"]
