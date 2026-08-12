#!/usr/bin/env python3
# test_route_policy_test_coverage.py
"""
Functional test for route policy test coverage completeness.
Version: 0.250.055
Implemented in: 0.242.069

This test ensures the route inventory and unauthenticated access policy tests
cover the same route set, so adding or removing a route requires both policy
contracts to stay in sync.
"""

import importlib.util
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
ROUTE_TEST_DIR = Path(__file__).resolve().parent
INVENTORY_TEST_FILE = ROUTE_TEST_DIR / "test_route_blueprint_policy_inventory.py"
UNAUTHENTICATED_TEST_FILE = ROUTE_TEST_DIR / "test_route_unauthenticated_policy_contract.py"


def load_test_module(module_name: str, file_path: Path):
    """Import a route test module from disk."""
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    assert spec is not None and spec.loader is not None, f"Expected module spec for {file_path}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def route_key(route) -> tuple[str, str, str, str]:
    """Return a stable route identity key from a route test object."""
    return (route.file_name, route.function_name, route.route_target, route.path)


def test_route_policy_tests_cover_identical_route_sets() -> None:
    """Verify every route discovered by one route policy test is discovered by the other."""
    inventory_module = load_test_module("route_blueprint_policy_inventory", INVENTORY_TEST_FILE)
    unauthenticated_module = load_test_module("route_unauthenticated_policy_contract", UNAUTHENTICATED_TEST_FILE)

    inventory_routes = {route_key(route) for route in inventory_module.iter_route_functions()}
    unauthenticated_routes = {route_key(route) for route in unauthenticated_module.iter_route_functions()}

    missing_from_inventory = sorted(unauthenticated_routes - inventory_routes)
    missing_from_unauthenticated = sorted(inventory_routes - unauthenticated_routes)

    assert missing_from_inventory == [], f"Routes missing from inventory policy test: {missing_from_inventory}"
    assert missing_from_unauthenticated == [], (
        f"Routes missing from unauthenticated policy test: {missing_from_unauthenticated}"
    )


def test_route_policy_test_files_are_documented_in_repo_instructions() -> None:
    """Verify repo instructions explicitly name every route policy test file."""
    instruction_files = [
        ROOT_DIR / ".github" / "instructions" / "python-lang.instructions.md",
        ROOT_DIR / ".github" / "prompts" / "route-authentication-audit.prompt.md",
        ROOT_DIR / ".github" / "prompts" / "prepare-for-pull-request.prompt.md",
    ]
    instruction_source = "\n".join(path.read_text(encoding="utf-8") for path in instruction_files)

    for route_test_file in sorted(ROUTE_TEST_DIR.glob("test_route_*.py")):
        expected_reference = f"functional_tests/route_tests/{route_test_file.name}"
        assert expected_reference in instruction_source, f"Missing route test instruction reference: {expected_reference}"


if __name__ == "__main__":
    tests = [
        test_route_policy_tests_cover_identical_route_sets,
        test_route_policy_test_files_are_documented_in_repo_instructions,
    ]
    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            test()
            print("PASS")
            results.append(True)
        except Exception as exc:
            print(f"FAIL: {exc}")
            results.append(False)

    passed = sum(results)
    print(f"\nResults: {passed}/{len(results)} tests passed")
    raise SystemExit(0 if all(results) else 1)
