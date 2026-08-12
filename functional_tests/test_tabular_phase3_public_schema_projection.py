#!/usr/bin/env python3
# test_tabular_phase3_public_schema_projection.py
"""
Functional test for Phase 3 public schema projection and passthrough safety.
Version: 0.250.175
Implemented in: 0.250.173

This test ensures generated tabular artifacts expose only the persisted public
schema while retaining internal checkpoint lineage, and that raw row passthrough
is refused for derived generated-output requests.
"""

import ast
import io
import json
import sys
import traceback
from pathlib import Path
from xml.etree import ElementTree
from xml.sax.saxutils import escape as escape_xml_text

from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
TABULAR_EXPORTS = APP_ROOT / "functions_tabular_generated_exports.py"
IMPLEMENTED_VERSION = "0.250.173"
sys.path.insert(0, str(APP_ROOT))

from functions_analysis_deliverables import (  # noqa: E402
    build_analysis_deliverable_contract,
    project_structured_deliverable_row,
)
from functions_assistant_table_exports import (  # noqa: E402
    build_safe_csv_headers,
    neutralize_csv_spreadsheet_formula,
)
from functions_generated_file_exports import (  # noqa: E402
    build_generated_file_export,
    evaluate_generated_file_passthrough_eligibility,
)


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def assert_true(value, label):
    if not value:
        raise AssertionError(f"Expected truthy value for {label}")


def assert_false(value, label):
    if value:
        raise AssertionError(f"Expected falsy value for {label}")


def load_tabular_export_namespace(checkpoint_rows):
    source = TABULAR_EXPORTS.read_text(encoding="utf-8")
    module_tree = ast.parse(source, filename=str(TABULAR_EXPORTS))
    function_names = {
        "_safe_int",
        "_serialize_generated_output_value",
        "_sanitize_generated_xml_tag_name",
        "_write_generated_xml_row",
        "_get_tabular_run_lineage_schema",
        "_get_tabular_run_public_output_schema",
        "_get_tabular_run_internal_checkpoint_schema",
        "_get_tabular_run_serialized_public_schema",
        "_write_ordered_output_stream",
        "_build_structured_export_preview_rows",
    }
    selected_nodes = [
        node
        for node in module_tree.body
        if isinstance(node, ast.FunctionDef) and node.name in function_names
    ]
    assert_equal({node.name for node in selected_nodes}, function_names, "loaded function set")

    namespace = {
        "TABULAR_EXPORT_OUTPUT_ROW_NUMBER_FIELD": "source_row_number",
        "TABULAR_EXPORT_OUTPUT_ROW_IDENTITY_FIELD": "source_row_identity",
        "TABULAR_EXPORT_ARTIFACT_PREVIEW_MAX_ROWS": 10,
        "TABULAR_EXPORT_ARTIFACT_PREVIEW_MAX_CHARS": 24000,
        "TABULAR_EXPORT_ARTIFACT_PREVIEW_CELL_MAX_CHARS": 240,
        "build_safe_csv_headers": build_safe_csv_headers,
        "csv": __import__("csv"),
        "escape_xml_text": escape_xml_text,
        "io": io,
        "is_analysis_internal_lineage_field": lambda field_name: str(field_name or "").strip() in {
            "source_row_number",
            "source_row_identity",
        } or str(field_name or "").strip().startswith("__simplechat"),
        "json": json,
        "neutralize_csv_spreadsheet_formula": neutralize_csv_spreadsheet_formula,
        "project_structured_deliverable_row": project_structured_deliverable_row,
        "re": __import__("re"),
        "_download_json_blob": lambda blob_path: checkpoint_rows[blob_path],
        "_output_blob_path": lambda user_id, conversation_id, run_id, batch_number: f"batch-{batch_number}",
        "_validate_tabular_output_checkpoint_metadata": lambda run, blob_path, batch_number: None,
    }
    exec(compile(ast.Module(body=selected_nodes, type_ignores=[]), str(TABULAR_EXPORTS), "exec"), namespace)
    return namespace


def build_internal_run(output_format):
    return {
        "user_id": "user-1",
        "conversation_id": "conversation-1",
        "id": "run-1",
        "batch_count": 1,
        "row_count": 2,
        "output_format": output_format,
        "output_schema": ["source_row_number", "source_row_identity", "Decision", "Amount"],
        "public_output_schema": ["Decision", "Amount"],
        "lineage_schema": ["source_row_number", "source_row_identity"],
        "internal_checkpoint_schema": ["source_row_number", "source_row_identity", "Decision", "Amount"],
    }


def test_contract_separates_public_internal_and_lineage_schema():
    print("Testing deliverable contract schema separation...")
    assert_app_version_at_least(IMPLEMENTED_VERSION)
    contract = build_analysis_deliverable_contract(
        action_mode="search",
        requested_output_format="csv",
        public_output_schema=["Decision", "Amount"],
        row_cardinality="one_per_source_row",
        ordering="source_order",
    ).to_dict()

    assert_equal(contract["contract_version"], "analysis-deliverables-v3", "contract version")
    assert_equal(contract["public_output_schema"], ["Decision", "Amount"], "public schema")
    assert_equal(contract["lineage_schema"], ["source_row_number", "source_row_identity"], "lineage schema")
    assert_equal(
        contract["internal_checkpoint_schema"],
        ["source_row_number", "source_row_identity", "Decision", "Amount"],
        "internal checkpoint schema",
    )

    for reserved_field in ("source_row_number", "source_row_identity", "__simplechat_row_token"):
        try:
            build_analysis_deliverable_contract(
                action_mode="search",
                requested_output_format="csv",
                public_output_schema=[reserved_field],
            )
        except ValueError:
            continue
        raise AssertionError(f"Reserved field {reserved_field!r} was accepted in the public schema")


def test_public_projection_drives_csv_json_xml_and_preview():
    print("Testing public projection across durable output formats and preview metadata...")
    checkpoint_rows = {
        "batch-1": [
            {
                "source_row_number": 1,
                "source_row_identity": "FRI-001",
                "Decision": "Monitor",
                "Amount": "100",
            },
            {
                "source_row_number": 2,
                "source_row_identity": "FRI-002",
                "Decision": "High <Attention>",
                "Amount": "=2+2",
            },
        ],
    }
    namespace = load_tabular_export_namespace(checkpoint_rows)

    csv_stream = io.StringIO()
    namespace["_write_ordered_output_stream"](build_internal_run("csv"), csv_stream)
    csv_payload = csv_stream.getvalue()
    assert_true(csv_payload.startswith("Decision,Amount\n"), "csv public headers")
    assert_false("source_row_number" in csv_payload, "csv lineage leakage")
    assert_true("'=2+2" in csv_payload, "csv formula neutralization")

    json_stream = io.StringIO()
    namespace["_write_ordered_output_stream"](build_internal_run("json"), json_stream)
    json_rows = json.loads(json_stream.getvalue())
    assert_equal(list(json_rows[0]), ["Decision", "Amount"], "json public field order")
    assert_false("source_row_identity" in json_rows[0], "json lineage leakage")

    xml_stream = io.StringIO()
    namespace["_write_ordered_output_stream"](build_internal_run("xml"), xml_stream)
    xml_payload = xml_stream.getvalue()
    ElementTree.fromstring(xml_payload)
    assert_true("<Decision>High &lt;Attention&gt;</Decision>" in xml_payload, "xml escaping")
    assert_false("source_row_identity" in xml_payload, "xml lineage leakage")

    preview_rows = namespace["_build_structured_export_preview_rows"](build_internal_run("csv"))
    assert_equal(list(preview_rows[0]), ["Decision", "Amount"], "preview columns")
    assert_false("source_row_number" in preview_rows[0], "preview lineage leakage")


def test_passthrough_eligibility_and_generic_finalizer_guard():
    print("Testing passthrough eligibility and generic finalizer guard...")
    rows = [{"Case": "A", "Amount": 100}]
    allowed = evaluate_generated_file_passthrough_eligibility(
        "Export these results as CSV.",
        rows=rows,
    )
    assert_true(allowed["allowed"], "explicit serialization passthrough")
    assert_equal(allowed["reason_code"], "explicit_format_conversion", "serialization reason")

    unchanged = evaluate_generated_file_passthrough_eligibility(
        "Download an unchanged copy of the source rows as CSV.",
        rows=rows,
    )
    assert_true(unchanged["allowed"], "explicit unchanged copy passthrough")
    assert_equal(unchanged["reason_code"], "explicit_unchanged_copy", "unchanged reason")

    derived = evaluate_generated_file_passthrough_eligibility(
        "Create a CSV with exactly one output row for each source row and classify risk.",
        rows=rows,
    )
    assert_false(derived["allowed"], "derived passthrough rejection")
    assert_equal(derived["reason_code"], "derived_output_requires_transform", "derived reason")

    schema_mismatch = evaluate_generated_file_passthrough_eligibility(
        "Export these results as CSV.",
        rows=rows,
        public_output_schema=["Risk"],
    )
    assert_false(schema_mismatch["allowed"], "schema mismatch passthrough rejection")
    assert_equal(schema_mismatch["reason_code"], "schema_not_satisfied", "schema mismatch reason")

    function_results = [{
        "success": True,
        "plugin_name": "SimpleChatPlugin",
        "function_name": "lookup_rows",
        "function_result": json.dumps({"rows": rows}),
    }]
    guarded_payload = build_generated_file_export(
        "Create a CSV with exactly these columns: Risk, Reason.",
        "",
        function_results=function_results,
    )
    assert_equal(guarded_payload, None, "derived function rows are not serialized")

    passthrough_payload = build_generated_file_export(
        "Export these results as CSV.",
        "",
        function_results=function_results,
    )
    assert_true(passthrough_payload, "explicit function row serialization")
    assert_equal(passthrough_payload["row_source"], "structured function result", "function row source")
    assert_equal(
        passthrough_payload["passthrough_reason_code"],
        "explicit_format_conversion",
        "function passthrough reason",
    )


def run_all_tests():
    tests = [
        test_contract_separates_public_internal_and_lineage_schema,
        test_public_projection_drives_csv_json_xml_and_preview,
        test_passthrough_eligibility_and_generic_finalizer_guard,
    ]
    results = []
    for test in tests:
        try:
            test()
            print(f"PASS: {test.__name__}")
            results.append(True)
        except Exception as exc:
            print(f"FAIL: {test.__name__}: {exc}")
            traceback.print_exc()
            results.append(False)
    print(f"Results: {sum(results)}/{len(results)} tests passed")
    return all(results)


if __name__ == "__main__":
    sys.exit(0 if run_all_tests() else 1)
