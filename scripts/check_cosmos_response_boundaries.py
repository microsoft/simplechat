# check_cosmos_response_boundaries.py
"""Maintain reviewed Cosmos point boundaries and test-double representation contracts.

This is a change/inventory guard, not a static proof of interprocedural safety.
Regeneration retains reviews only for unchanged boundary implementations.
"""

import argparse
import ast
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "functional_tests" / "cosmos_response_boundaries.json"
POINT_METHODS = frozenset({
    "read_item", "create_item", "replace_item", "upsert_item", "patch_item", "delete_item",
})
BATCH_METHODS = frozenset({"execute_item_batch", "read_many"})
CLASSIFICATIONS = frozenset({
    "normalized-strict", "sdk-compatible", "response-unused", "not-cosmos",
})
DOUBLE_CLASSIFICATIONS = frozenset({
    "sdk-default", "legacy-inline", "domain-double", "fault-injection", "explicit-compatibility",
})
COSMOS_DOUBLE_BASES = frozenset({
    "AtomicMemoryContainer", "CosmosContainer", "OfflineContainer", "FakeCosmosContainer", "ResultContainer",
})
DOMAIN_DOUBLE_TARGETS = frozenset({
    "functional_tests/test_support/workflow_chat_delivery_fakes.py::FakeRuntime",
    "functional_tests/test_support/workflow_chat_delivery_fakes.py::FakeRuntime.factory._Store",
    "functional_tests/test_support/workflow_chat_delivery_fakes.py::FakeResultReader",
    "functional_tests/test_support/orchestration_results.py::ResultFixture",
})
CORE_CONTRACT_TESTS = frozenset({
    "functional_tests/test_cosmos_document_boundaries.py",
    "functional_tests/test_orchestration_cosmos_response_contract.py",
    "functional_tests/test_orchestration_operation_runtime.py",
    "functional_tests/test_orchestration_email_review_flow.py",
    "functional_tests/test_orchestration_operation_imports.py",
    "functional_tests/test_orchestration_result_imports.py",
    "functional_tests/test_orchestration_failure_telemetry.py",
    "functional_tests/test_m365_cosmos_sdk_contract.py",
    "functional_tests/test_m365_pending_authorization.py",
    "functional_tests/test_workflow_chat_delivery_concurrency.py",
    "functional_tests/test_workflow_chat_delivery_save_guard.py",
    "functional_tests/test_orchestration_harness_execution.py::test_catalog_and_scheduler_fixtures_share_current_transport_types",
})


def _digest(node):
    return hashlib.sha256(ast.dump(node, include_attributes=False).encode("utf-8")).hexdigest()


def review_digest(boundary):
    return hashlib.sha256(json.dumps(boundary, sort_keys=True).encode("utf-8")).hexdigest()


def _python_files(directory):
    for parent, directories, filenames in os.walk(directory):
        directories[:] = sorted(
            name for name in directories if name not in {".venv", "node_modules", "__pycache__"}
        )
        for name in sorted(filenames):
            if name.endswith(".py"):
                yield Path(parent) / name


class BoundaryVisitor(ast.NodeVisitor):
    def __init__(self):
        self.scope = []
        self.owners = {}

    def visit_ClassDef(self, node):
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node):
        self.scope.append(node.name)
        self._record_scope(node, ".".join(self.scope))
        self.generic_visit(node)
        self.scope.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Module(self, node):
        self._record_scope(node, "<module>")
        self.generic_visit(node)

    def _record_scope(self, node, owner):
        points = []
        queries = []
        batches = []
        parents = {child: parent for parent in ast.walk(node) for child in ast.iter_child_nodes(parent)}
        pending = list(ast.iter_child_nodes(node))
        children = []
        while pending:
            child = pending.pop(0)
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            children.append(child)
            pending.extend(ast.iter_child_nodes(child))
        for child in sorted(children, key=lambda value: (getattr(value, "lineno", 0), getattr(value, "col_offset", 0))):
            methods = POINT_METHODS | BATCH_METHODS | {"query_items", "read_all_items"}
            if isinstance(child, ast.Attribute) and child.attr in methods:
                method, receiver = child.attr, child.value
            elif (
                isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
                and child.func.id == "getattr" and len(child.args) > 1
                and isinstance(child.args[1], ast.Constant) and child.args[1].value in methods
            ):
                method, receiver = child.args[1].value, child.args[0]
            else:
                continue
            parent = parents.get(child)
            called = isinstance(parent, ast.Call) and parent.func is child
            statement = parents.get(parent) if called else parent
            exposure = (
                "unused" if isinstance(statement, ast.Expr)
                else "returned" if isinstance(statement, ast.Return)
                else "consumed" if called else "helper-reference"
            )
            entry = {
                "method": method,
                "receiver": ast.unparse(receiver),
                "response": exposure,
            }
            target = (
                queries if method in {"query_items", "read_all_items"}
                else batches if method in BATCH_METHODS else points
            )
            target.append(entry)
        if points or queries or batches:
            self.owners[owner] = {"sha256": _digest(node), "points": points, "queries": queries, "batches": batches}


def scan_boundaries(root=ROOT):
    owners = {}
    for directory in ("application", "scripts", "deployers"):
        for path in _python_files(root / directory):
            visitor = BoundaryVisitor()
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            visitor.visit(tree)
            module_digest = _digest(tree)
            for name, value in visitor.owners.items():
                value["module_sha256"] = module_digest
                owners[f"{path.relative_to(root).as_posix()}::{name}"] = value
    return owners


def inspect_doubles(filename, source):
    doubles = {}

    class DoubleVisitor(ast.NodeVisitor):
        def __init__(self, filename):
            self.filename = filename
            self.scope = []
            self.seams = {}

        def visit_FunctionDef(self, node):
            self.scope.append(node.name)
            self.generic_visit(node)
            self.scope.pop()

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_ClassDef(self, node):
            self.scope.append(node.name)
            methods = {item.name for item in node.body if isinstance(item, ast.FunctionDef)}
            key = f"{self.filename}::{'.'.join(self.scope)}"
            inherited = [
                ast.unparse(base) for base in node.bases
                if isinstance(base, ast.Name) and base.id in COSMOS_DOUBLE_BASES
            ]
            cosmos = bool(methods & (POINT_METHODS | BATCH_METHODS) or inherited)
            if cosmos or key in DOMAIN_DOUBLE_TARGETS:
                doubles[key] = {
                    "sha256": _digest(node), "methods": sorted(methods & (POINT_METHODS | BATCH_METHODS)),
                    "kind": "class" if cosmos else "domain", "inherited_bases": inherited,
                }
            self.generic_visit(node)
            self.scope.pop()

        def visit_Call(self, node):
            methods = {keyword.arg for keyword in node.keywords} & (POINT_METHODS | BATCH_METHODS)
            patched = (
                isinstance(node.func, ast.Attribute) and node.func.attr in {"setattr", "object"}
                and len(node.args) > 1 and isinstance(node.args[1], ast.Constant)
                and node.args[1].value in POINT_METHODS | BATCH_METHODS
            )
            if patched:
                methods.add(node.args[1].value)
            if methods:
                scope = ".".join(self.scope) or "<module>"
                sequence = self.seams.get(scope, 0) + 1
                self.seams[scope] = sequence
                key = f"{self.filename}::{scope}::point-seam-{sequence}"
                doubles[key] = {"sha256": _digest(node), "methods": sorted(methods), "kind": "seam"}
            self.generic_visit(node)

    tree = ast.parse(source)
    DoubleVisitor(filename).visit(tree)
    for node in ast.walk(tree):
        if (
            not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Constant)
            or not isinstance(node.value.value, str)
            or not any(f"def {method}(" in node.value.value for method in POINT_METHODS | BATCH_METHODS)
        ):
            continue
        targets = [target.id for target in node.targets if isinstance(target, ast.Name)]
        if not targets:
            continue
        try:
            embedded_tree = ast.parse(node.value.value)
        except SyntaxError:
            continue
        embedded = inspect_doubles(f"{filename}::embedded-{targets[0]}", node.value.value)
        for value in embedded.values():
            value["embedded_source_sha256"] = _digest(embedded_tree)
        doubles.update(embedded)
    imports = [
        node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    imports_digest = _digest(ast.Module(body=imports, type_ignores=[]))
    for value in doubles.values():
        value["imports_sha256"] = imports_digest
    return doubles


def scan_doubles(root=ROOT):
    doubles = {}
    for directory in ("functional_tests", "ui_tests"):
        for path in _python_files(root / directory):
            doubles.update(inspect_doubles(
                path.relative_to(root).as_posix(), path.read_text(encoding="utf-8-sig"),
            ))
    return doubles


def validate_inventory(actual, doubles, inventory, root=ROOT, *, domain_targets=()):
    errors = []
    evidence_cache = {}
    for section, current, classifications in (
        ("owners", actual, CLASSIFICATIONS), ("doubles", doubles, DOUBLE_CLASSIFICATIONS),
    ):
        reviewed = inventory.get(section, {})
        for key in sorted(current.keys() | reviewed.keys()):
            if key not in reviewed:
                errors.append(f"Unreviewed {section}: {key}")
                continue
            if key not in current:
                errors.append(f"Stale {section} review: {key}")
                continue
            entry = reviewed[key]
            if entry.get("boundary") != current[key]:
                errors.append(f"Changed {section} requires review: {key}")
            if entry.get("classification") not in classifications or not entry.get("contract", "").strip():
                errors.append(f"Missing classification/consumer contract: {key}")
            if section == "owners" and entry.get("classification") in {"normalized-strict", "sdk-compatible"}:
                if entry.get("evidence_scope") not in {"owner-runtime", "sdk-api-and-source-review"}:
                    errors.append(f"Missing runtime evidence scope: {key}")
                elif entry.get("evidence_scope") == "owner-runtime" and entry.get("tests") == [
                    "functional_tests/test_cosmos_document_boundaries.py"
                ]:
                    errors.append(f"Utility-only test is not owner-runtime evidence: {key}")
            evidence = entry.get("tests", [])
            if entry.get("classification") not in {"response-unused", "not-cosmos", "domain-double", "legacy-inline"}:
                if not evidence:
                    errors.append(f"Missing runtime evidence: {key}")
            for test in evidence:
                filename, _, function = test.partition("::")
                path = root / filename
                if not path.resolve().is_relative_to(root.resolve()) or not filename.startswith(("functional_tests/", "ui_tests/")):
                    errors.append(f"Evidence must be a repository test: {test}")
                    continue
                if filename not in evidence_cache:
                    evidence_cache[filename] = (
                        {node.name for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig")))
                         if isinstance(node, ast.FunctionDef)}
                        if path.is_file() else None
                    )
                names = evidence_cache[filename]
                if names is None:
                    errors.append(f"Missing evidence file: {test}")
                elif function and function not in names:
                    errors.append(f"Stale evidence function: {test}")
    baseline = inventory.get("legacy_double_baseline", {})
    for key, digest in baseline.items():
        if key not in doubles or review_digest(doubles[key]) != digest:
            errors.append(f"Stale legacy double exemption: {key}")
    for key, entry in inventory.get("doubles", {}).items():
        if entry.get("classification") == "legacy-inline" and (
            key not in doubles or baseline.get(key) != review_digest(doubles[key])
        ):
            errors.append(f"New/changed Cosmos double cannot use legacy-inline: {key}")
    seam_baseline = inventory.get("compatibility_seam_baseline", {})
    for key, digest in seam_baseline.items():
        if key not in doubles or review_digest(doubles[key]) != digest:
            errors.append(f"Stale compatibility seam exemption: {key}")
    for key, entry in inventory.get("doubles", {}).items():
        if entry.get("classification") == "explicit-compatibility" and (
            key not in doubles or doubles[key].get("kind") != "seam"
            or seam_baseline.get(key) != review_digest(doubles[key])
        ):
            errors.append(f"New/changed seam needs runtime fault-injection evidence: {key}")
    owner_baseline = inventory.get("source_review_baseline", {})
    for key, digest in owner_baseline.items():
        if key not in actual or review_digest(actual[key]) != digest:
            errors.append(f"Stale source-only owner review: {key}")
    for key, entry in inventory.get("owners", {}).items():
        if entry.get("evidence_scope") == "sdk-api-and-source-review":
            if key not in actual or owner_baseline.get(key) != review_digest(actual[key]):
                errors.append(f"New/changed owner needs owner-runtime SDK evidence: {key}")
    for key in domain_targets:
        if key not in doubles:
            errors.append(f"Stale domain-double classification target: {key}")
    return errors


def refresh_inventory(current, doubles, previous):
    """Never assign a compatibility classification or preserve a changed review automatically."""
    result = {
        **previous,
        "schema_version": 1,
        "legacy_double_baseline": previous.get("legacy_double_baseline", {}),
        "source_review_baseline": previous.get("source_review_baseline", {}),
        "owners": {}, "doubles": {},
    }
    for section, entries in (("owners", current), ("doubles", doubles)):
        for key, boundary in sorted(entries.items()):
            prior = previous.get(section, {}).get(key, {})
            result[section][key] = (
                prior if prior.get("boundary") == boundary else {
                    "boundary": boundary, "classification": "review-required",
                    "contract": "", "tests": [],
                }
            )
    return result


def runtime_test_targets(inventory):
    targets = set(CORE_CONTRACT_TESTS)
    for section in ("owners", "doubles"):
        for entry in inventory.get(section, {}).values():
            if entry.get("evidence_scope") == "owner-runtime" or entry.get("classification") in {
                "sdk-default", "domain-double", "fault-injection",
            }:
                targets.update(entry.get("tests", []))
    return sorted(targets)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--refresh", action="store_true", help="Stage changed boundaries for manual review.")
    mode.add_argument("--run-contracts", action="store_true", help="Run core and reviewed owner/double SDK tests with network blocked.")
    args = parser.parse_args()
    previous = json.loads(INVENTORY.read_text(encoding="utf-8")) if INVENTORY.exists() else {}
    owners, doubles = scan_boundaries(), scan_doubles()
    if args.refresh:
        result = refresh_inventory(owners, doubles, previous)
        INVENTORY.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return 0
    errors = validate_inventory(owners, doubles, previous, domain_targets=DOMAIN_DOUBLE_TARGETS)
    for error in errors:
        print(error)
    print(f"Cosmos boundary review: {len(owners)} owners, {len(doubles)} doubles, {len(errors)} review gaps.")
    if errors:
        return 1
    if args.run_contracts:
        targets = runtime_test_targets(previous)
        environment = {
            **os.environ,
            "PYTHONPATH": os.pathsep.join((
                str(ROOT / "application" / "single_app"), str(ROOT / "functional_tests"),
                os.environ.get("PYTHONPATH", ""),
            )),
        }
        selectors = []
        for target in targets:
            filename, separator, scope = target.partition("::")
            selectors.append(str(ROOT / filename) + (separator + scope if scope else ""))
        return subprocess.run(
            [
                sys.executable, "-m", "pytest", "-p", "test_support.cosmos_network_guard",
                *selectors, "-q", "--disable-warnings", "--tb=short",
            ],
            cwd=ROOT, env=environment, check=False,
        ).returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
