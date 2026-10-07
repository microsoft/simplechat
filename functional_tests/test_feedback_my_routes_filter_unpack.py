#!/usr/bin/env python3
# test_feedback_my_routes_filter_unpack.py
"""
Functional test for the user feedback routes filter unpack fix.
Version: 0.261.277
Implemented in: 0.261.277

_parse_feedback_filters() returns three values (type, acknowledged, archive state), but the
user-facing /feedback/my, /feedback/my/stats and /feedback/my/export routes unpacked two,
so every request failed with "too many values to unpack" and the Feedback tab in both
interfaces showed an error. This test pins the helper's arity and that every caller
unpacks all three values.
"""

import ast
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
FEEDBACK_ROUTE = REPO_ROOT / "application" / "single_app" / "route_backend_feedback.py"


def _module():
    return ast.parse(FEEDBACK_ROUTE.read_text(encoding="utf-8"))


def _helper_return_arity(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_parse_feedback_filters":
            arities = {
                len(ret.value.elts)
                for ret in ast.walk(node)
                if isinstance(ret, ast.Return) and isinstance(ret.value, ast.Tuple)
            }
            assert len(arities) == 1, f"_parse_feedback_filters returns mixed tuple sizes: {arities}"
            return arities.pop()
    raise AssertionError("_parse_feedback_filters was not found")


def test_version_is_at_least_the_implementing_release():
    print("Testing the application version...")
    assert_app_version_at_least("0.261.277")
    return True


def test_every_caller_unpacks_every_filter_value():
    print("Testing _parse_feedback_filters callers...")
    tree = _module()
    arity = _helper_return_arity(tree)

    callers = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        call = node.value
        if not (isinstance(call, ast.Call) and getattr(call.func, "id", None) == "_parse_feedback_filters"):
            continue
        target = node.targets[0]
        assert isinstance(target, ast.Tuple), f"Line {node.lineno} should unpack the filter tuple"
        assert len(target.elts) == arity, (
            f"Line {node.lineno} unpacks {len(target.elts)} values but the helper returns {arity}"
        )
        callers.append(node.lineno)

    assert len(callers) >= 3, "The user feedback list, stats and export routes should all use the helper"
    print(f"  ok  {len(callers)} callers unpack {arity} values")
    return True


if __name__ == "__main__":
    tests = [test_version_is_at_least_the_implementing_release, test_every_caller_unpacks_every_filter_value]
    results = []
    for test in tests:
        try:
            results.append(test())
        except Exception as exc:
            print(f"FAILED {test.__name__}: {exc}")
            results.append(False)
    print(f"Results: {sum(bool(r) for r in results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
