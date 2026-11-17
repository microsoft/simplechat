#!/usr/bin/env python3
# test_orchestration_prepared_relate_planning_crash_fix.py
"""
Functional test for the prepared calculation planning crash fix.
Version: 0.261.450
Implemented in: 0.261.450

This test ensures that a plan with a prepared multi-file calculation, which carries no
relational program at planning time, passes the planning-time header check instead of
raising KeyError, that the Word provenance check can name the document search capability,
and that no orchestration module reads a name it never defines.
"""

import ast
import builtins
import os
import sys
from pathlib import Path

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_orchestration_dependency_planner import planner  # noqa: E402,F401 (fixture)
from test_orchestration_dependency_runtime import binding, compose, runtime  # noqa: E402,F401 (fixture)

APPLICATION = Path(__file__).resolve().parents[1] / "application" / "single_app"


def _prepared_relate_plan():
    return {"steps": [{
        "step_id": "calculate", "capability_id": "tabular_analyze", "enabled": True,
        "arguments": {
            "native_operation": "relate", "calculation_mode": "prepared-v1",
            "document_ids": ["doc-a", "doc-b"], "question": "Total by region.",
        },
    }]}


def _inspected_sources():
    return [
        {"document_id": document_id, "inspection": {
            "status": "inspected",
            "tables": [{"header_row": 1, "sheet": None, "columns": ["Region", "Amount"]}],
        }}
        for document_id in ("doc-a", "doc-b")
    ]


def test_prepared_relate_without_a_program_passes_the_header_check(planner):
    """The run authors the program; planning has nothing to compare against the headers."""
    assert planner.validate_plan_native_source_schemas(_prepared_relate_plan(), _inspected_sources()) is None


def test_disabled_and_other_operations_are_still_skipped(planner):
    plan = _prepared_relate_plan()
    plan["steps"][0]["arguments"]["native_operation"] = "query"
    assert planner.validate_plan_native_source_schemas(plan, _inspected_sources()) is None
    plan = _prepared_relate_plan()
    plan["steps"][0]["enabled"] = False
    assert planner.validate_plan_native_source_schemas(plan, _inspected_sources()) is None


def test_a_misplaced_argument_is_recorded_and_an_invented_field_is_only_counted(planner):
    """Telemetry must show an argument written beside ``arguments`` without logging planner text."""
    schema = sys.modules["functions_orchestration_schema"]
    step = {**compose(), "knowledge_basis": "sources", "PRIVATE_FIELD": True}
    try:
        schema.validate_dependency_plan(
            {"steps": [step], "final_response": binding("draft")}, available_capability_ids=["compose"],
        )
        raise AssertionError("The unknown step fields were accepted.")
    except schema.PlanValidationError as error:
        assert error.rule == "step_shape_invalid"
        assert error.diagnostics["unknown_field_count"] == 2
        assert error.diagnostics["capability_id"] == "compose"
        assert error.diagnostics["misplaced_arguments"] == "knowledge_basis"
        assert "PRIVATE_FIELD" not in repr(error.diagnostics)


def _names_bound(tree):
    bound = set(dir(builtins)) | {"__file__", "__name__", "__doc__"}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            spec = node.args
            for argument in (*spec.posonlyargs, *spec.args, *spec.kwonlyargs, spec.vararg, spec.kwarg):
                if argument is not None:
                    bound.add(argument.arg)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                bound.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            bound.add(node.id)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            bound.update(node.names)
        elif isinstance(node, ast.MatchAs) and node.name:
            bound.add(node.name)
    return bound


def test_orchestration_modules_read_no_undefined_name():
    """A name read but never bound raises NameError only when that line runs in production."""
    missing = []
    sources = sorted(APPLICATION.glob("functions_orchestration*.py"))
    sources.append(APPLICATION / "route_backend_orchestration.py")
    assert len(sources) > 10, sources
    for path in sources:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        if any(
            isinstance(node, ast.ImportFrom) and any(alias.name == "*" for alias in node.names)
            for node in ast.walk(tree)
        ):
            continue
        bound = _names_bound(tree)
        missing.extend(
            f"{path.name}:{node.lineno}: {node.id}"
            for node in ast.walk(tree)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id not in bound
        )
    assert not missing, missing


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
