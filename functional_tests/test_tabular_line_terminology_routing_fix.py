#!/usr/bin/env python3
# test_tabular_line_terminology_routing_fix.py
"""
Functional test for tabular exhaustive per-line terminology routing.
Version: 0.250.199
Implemented in: 0.250.197; updated in 0.250.199

A customer reported that a prompt phrased as "For each line in this document,
I need eight questions answered... Go line by line and make sure all eight
questions are answered for each line" did not trigger the durable tabular
Analyze/Search parity pipeline for either Analyze or Search, and instead fell
back to the old bounded foreground TabularProcessingPlugin tool-calling path,
which truncated the response after only a handful of rows.

Two independent root causes combined to produce this failure:

1. Every exhaustive/per-row intent-detection keyword list across the codebase
   (functions_tabular_orchestration.py, functions_tabular_parity_contract.py,
   route_backend_chats.py, functions_document_analysis.py) recognized "row"
   phrasing ("each row", "every row", "for each row", "one row per", ...) but
   not the equally natural "line" synonym ("each line", "line by line", ...),
   so a prompt using "line" terminology was never classified as an exhaustive
   per-row request at all.
2. Even when hierarchical-analysis intent *was* recognized, the backend-only
   `enable_tabular_hierarchical_analysis` setting defaulted to False with no
   admin UI toggle, so `get_tabular_generated_output_task_type()` could never
   return the `hierarchical_analysis` durable task type for narrative
   (non-CSV/JSON/XML-export) per-row requests.

This test verifies both fixes and the exact customer prompt end to end.
"""

import sys
import types
from pathlib import Path

from test_support.versioning import assert_app_version_at_least

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

IMPLEMENTED_VERSION = "0.250.197"

CUSTOMER_PROMPT = (
    "For each line in this document, I need eight questions answered. I want "
    "the questions to be answered individually for each line item. Do not "
    "consolidate by bank or by activity. Go line by line and make sure all "
    "eight questions are answered for each line. The questions are as "
    "follows:\n"
    "What is this and what is it trying to accomplish?\n"
    "Why are we doing it?\n"
    "What value does it produce?\n"
    "What resources are identified or implied?\n"
    "What is the timeline or schedule?\n"
    "What happens if we stop?\n"
    "Does this appear reasonable? Concerns / duplication / measurable outcomes\n"
    "What information is missing to assess this activity?"
)


def _install_lightweight_planner_dependency_stubs():
    assistant_exports_module = types.ModuleType("functions_assistant_table_exports")
    assistant_exports_module.assistant_table_export_requested = (
        lambda prompt: "csv" in str(prompt or "").lower()
    )
    generated_exports_module = types.ModuleType("functions_generated_file_exports")

    def get_requested_artifact_formats(prompt):
        normalized_prompt = str(prompt or "").lower()
        return [output_format for output_format in ("json", "xml", "csv") if output_format in normalized_prompt]

    generated_exports_module.get_requested_artifact_formats = get_requested_artifact_formats
    generated_exports_module.get_requested_structured_artifact_format = (
        lambda prompt: next(iter(get_requested_artifact_formats(prompt)), None)
    )
    generated_exports_module.get_requested_structured_artifact_formats = get_requested_artifact_formats
    sys.modules.setdefault("functions_assistant_table_exports", assistant_exports_module)
    sys.modules.setdefault("functions_generated_file_exports", generated_exports_module)


_install_lightweight_planner_dependency_stubs()

from functions_tabular_orchestration import (  # noqa: E402
    get_tabular_generated_output_task_type,
    plan_tabular_request,
    question_requests_tabular_generated_output,
    question_requests_tabular_hierarchical_analysis,
)
from functions_tabular_parity_contract import _question_requests_full_source  # noqa: E402


def test_line_phrasing_is_recognized_as_hierarchical_analysis_intent():
    """'For each line'/'line by line' must be recognized the same as 'row' phrasing."""
    print("Testing line-terminology intent detection...")
    assert_app_version_at_least(IMPLEMENTED_VERSION)

    assert question_requests_tabular_hierarchical_analysis(CUSTOMER_PROMPT) is True, CUSTOMER_PROMPT
    assert _question_requests_full_source(CUSTOMER_PROMPT.strip().lower()) is True, CUSTOMER_PROMPT
    # The prompt never asks for a CSV/JSON/XML export, so this must stay False.
    assert question_requests_tabular_generated_output(CUSTOMER_PROMPT) is False, CUSTOMER_PROMPT

    # Row phrasing must keep working (no regression from the added markers).
    row_prompt = "For each row in this document, answer these eight questions. Go row by row."
    assert question_requests_tabular_hierarchical_analysis(row_prompt) is True, row_prompt


def test_customer_prompt_routes_to_durable_hierarchical_analysis_for_analyze_and_search():
    """The exact reported prompt must resolve to the hierarchical_analysis task
    type for both Analyze and Search action modes once the feature default is
    active, and must fall back to no durable routing when the flag is off
    (reproducing the reported bug)."""
    print("Testing customer prompt routes to durable hierarchical analysis...")
    assert_app_version_at_least(IMPLEMENTED_VERSION)

    generated_output_requested = question_requests_tabular_generated_output(CUSTOMER_PROMPT)
    hierarchical_analysis_requested = question_requests_tabular_hierarchical_analysis(CUSTOMER_PROMPT)
    assert hierarchical_analysis_requested is True

    active_settings = {"enable_tabular_hierarchical_analysis": True}
    assert get_tabular_generated_output_task_type(
        generated_output_requested, hierarchical_analysis_requested, active_settings, action_mode="analyze"
    ) == "hierarchical_analysis"
    assert get_tabular_generated_output_task_type(
        generated_output_requested, hierarchical_analysis_requested, active_settings, action_mode="search"
    ) == "hierarchical_analysis"
    for action_mode in ("analyze", "search"):
        plan = plan_tabular_request(
            CUSTOMER_PROMPT,
            [{"file_name": "simple_financial_review_test_200.csv", "document_id": "doc-1"}],
            action_mode=action_mode,
            settings=active_settings,
        )
        assert plan["durable_task_type"] == "hierarchical_analysis"
        assert plan["deliverable_contract"]["analysis_required"] is True
        assert [
            artifact["format"]
            for artifact in plan["deliverable_contract"]["requested_artifacts"]
        ] == ["md"]

    # Reproduce the reported bug: with the flag off, no durable task type is selected.
    disabled_settings = {"enable_tabular_hierarchical_analysis": False}
    assert get_tabular_generated_output_task_type(
        generated_output_requested, hierarchical_analysis_requested, disabled_settings, action_mode="analyze"
    ) is None
    assert get_tabular_generated_output_task_type(
        generated_output_requested, hierarchical_analysis_requested, disabled_settings, action_mode="search"
    ) is None


def test_enable_tabular_hierarchical_analysis_defaults_active():
    """The backend-only hierarchical-analysis flag must default to active, like
    the other durable Analyze/Search parity controls, with no admin UI
    toggle, and must be forced off by the existing emergency env kill switch."""
    print("Testing enable_tabular_hierarchical_analysis defaults active...")
    assert_app_version_at_least(IMPLEMENTED_VERSION)

    import ast

    settings_file = APP_ROOT / "functions_settings.py"
    source = settings_file.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(settings_file))

    default_settings_dict = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "get_settings":
            for stmt in node.body:
                if (
                    isinstance(stmt, ast.Assign)
                    and len(stmt.targets) == 1
                    and isinstance(stmt.targets[0], ast.Name)
                    and stmt.targets[0].id == "default_settings"
                ):
                    default_settings_dict = stmt.value
    assert default_settings_dict is not None, "Could not locate default_settings dict in get_settings()"

    found_value = None
    for key_node, value_node in zip(default_settings_dict.keys, default_settings_dict.values):
        if isinstance(key_node, ast.Constant) and key_node.value == "enable_tabular_hierarchical_analysis":
            found_value = ast.literal_eval(value_node)
    assert found_value is True, "enable_tabular_hierarchical_analysis must default to True"

    admin_settings_html = (APP_ROOT / "templates" / "admin_settings.html").read_text(encoding="utf-8")
    assert "enable_tabular_hierarchical_analysis" not in admin_settings_html, (
        "Always-on backend-only setting should not gain an admin UI toggle"
    )

    selected_nodes = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name in {"_env_flag_enabled", "_apply_tabular_parity_env_kill_switch"}
    ]
    assert len(selected_nodes) == 2
    namespace = {"os": __import__("os")}
    exec(
        compile(ast.Module(body=selected_nodes, type_ignores=[]), str(settings_file), "exec"),
        namespace,
    )
    apply_kill_switch = namespace["_apply_tabular_parity_env_kill_switch"]

    import os

    os.environ["SIMPLECHAT_DISABLE_TABULAR_PARITY_DURABLE_PREFLIGHT"] = "true"
    try:
        settings = {
            "tabular_request_planner_mode": "active",
            "enable_tabular_search_shared_preflight": True,
            "enable_tabular_analyze_durable_preflight": True,
            "enable_tabular_hierarchical_analysis": True,
        }
        result = apply_kill_switch(settings)
        assert result["enable_tabular_hierarchical_analysis"] is False
    finally:
        del os.environ["SIMPLECHAT_DISABLE_TABULAR_PARITY_DURABLE_PREFLIGHT"]


if __name__ == "__main__":
    tests = [
        test_line_phrasing_is_recognized_as_hierarchical_analysis_intent,
        test_customer_prompt_routes_to_durable_hierarchical_analysis_for_analyze_and_search,
        test_enable_tabular_hierarchical_analysis_defaults_active,
    ]
    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            test()
            results.append(True)
            print(f"PASS {test.__name__}")
        except Exception as exc:
            print(f"FAIL {test.__name__}: {exc}")
            import traceback
            traceback.print_exc()
            results.append(False)
    passed_count = sum(1 for result in results if result)
    print(f"\nResults: {passed_count}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
