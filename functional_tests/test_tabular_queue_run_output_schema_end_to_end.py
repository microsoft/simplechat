# test_tabular_queue_run_output_schema_end_to_end.py
#!/usr/bin/env python3
"""
Functional test for queue_tabular_generated_output_run() itself.
Version: 0.250.189
Implemented in: 0.250.189

Unlike the other tabular fix tests, this one calls the *actual*
queue_tabular_generated_output_run() function (the function containing the
output_schema fix), not a re-derivation of its inputs. It recursively extracts
the real function and every real helper it transitively calls from
functions_tabular_generated_exports.py via AST, and stubs only the genuine I/O
boundaries: Cosmos DB, blob storage, and telemetry. Cross-module helpers are
imported for real from modules already proven import-safe elsewhere in this
suite (functions_analysis_deliverables, functions_tabular_transformations).

This test ensures a combined (Analyze) run queued with no upfront output
hints is created with output_schema=None (deferring to batch-1 discovery),
while a run with a known public output schema still locks it up front.
"""

import ast
import builtins
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "application" / "single_app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_support.versioning import assert_app_version_at_least  # noqa: E402

IMPLEMENTED_VERSION = "0.250.189"
EXPORT_MODULE = APP_ROOT / "functions_tabular_generated_exports.py"

# Genuine I/O / cross-cutting boundaries; never pulled from the real module body.
STUB_NAMES = {
    "cosmos_tabular_export_runs_container",
    "cosmos_conversations_container",
    "storage_account_personal_chat_container_name",
    "storage_account_group_documents_container_name",
    "storage_account_public_documents_container_name",
    "storage_account_user_documents_container_name",
    "TABULAR_EXTENSIONS",
    "CLIENTS",
    "log_event",
    "_upload_json_blob",
    "_download_json_blob",
    "_get_blob_service_client",
    "current_app",
    "has_app_context",
    # Submitting to the executor is unreachable in a test (has_app_context() is False),
    # but statically references the entire background processing pipeline; stub it with
    # its real no-executor behavior instead of pulling that unreachable code in.
    "submit_tabular_generated_output_run",
}

# Real, pure, already-proven-import-safe modules to resolve cross-module names from.
SAFE_MODULES = [
    "functions_analysis_deliverables",
    "functions_tabular_transformations",
    "functions_generated_file_exports",
    "functions_assistant_table_exports",
]


def _collect_locally_bound_names(func_node):
    """Return names bound *within* func_node (params, assignments, comprehension targets, etc.)."""
    bound = set()
    args = func_node.args
    for arg_list in (args.posonlyargs, args.args, args.kwonlyargs):
        for arg in arg_list:
            bound.add(arg.arg)
    if args.vararg:
        bound.add(args.vararg.arg)
    if args.kwarg:
        bound.add(args.kwarg.arg)
    for sub in ast.walk(func_node):
        if isinstance(sub, ast.Name) and isinstance(sub.ctx, (ast.Store, ast.Del)):
            bound.add(sub.id)
        elif isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and sub is not func_node:
            bound.add(sub.name)
        elif isinstance(sub, ast.ExceptHandler) and sub.name:
            bound.add(sub.name)
        elif isinstance(sub, (ast.Import, ast.ImportFrom)):
            for alias in sub.names:
                bound.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(sub, ast.comprehension):
            for name_node in ast.walk(sub.target):
                if isinstance(name_node, ast.Name):
                    bound.add(name_node.id)
        elif isinstance(sub, ast.Lambda):
            lambda_args = sub.args
            for arg_list in (lambda_args.posonlyargs, lambda_args.args, lambda_args.kwonlyargs):
                for arg in arg_list:
                    bound.add(arg.arg)
            if lambda_args.vararg:
                bound.add(lambda_args.vararg.arg)
            if lambda_args.kwarg:
                bound.add(lambda_args.kwarg.arg)
    return bound


def _module_node_name(node):
    """Return the bound name for a module-level FunctionDef/ClassDef/simple Assign, else None."""
    if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
        return node.name
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        return node.targets[0].id
    return None


def _collect_local_closure(tree, root_names):
    """Recursively collect module-level FunctionDef/ClassDef/Assign nodes needed by root_names."""
    nodes_by_name = {}
    for node in tree.body:
        name = _module_node_name(node)
        if name:
            nodes_by_name[name] = node

    included = {}
    unresolved = set()
    worklist = list(root_names)
    seen = set()
    while worklist:
        name = worklist.pop()
        if name in seen:
            continue
        seen.add(name)
        if name in STUB_NAMES:
            continue
        node = nodes_by_name.get(name)
        if node is None:
            unresolved.add(name)
            continue
        included[name] = node
        if isinstance(node, ast.FunctionDef):
            local_bound = _collect_locally_bound_names(node)
            walk_target = node
        elif isinstance(node, ast.Assign):
            local_bound = set()
            walk_target = node.value
        else:
            continue
        for sub in ast.walk(walk_target):
            if (
                isinstance(sub, ast.Name)
                and isinstance(sub.ctx, ast.Load)
                and sub.id not in local_bound
                and sub.id not in seen
                and not hasattr(builtins, sub.id)
            ):
                worklist.append(sub.id)
    return included, unresolved


def _resolve_cross_module_names(unresolved):
    import importlib

    resolved = {}
    still_unresolved = set()
    for name in unresolved:
        found = False
        for module_name in SAFE_MODULES:
            module = importlib.import_module(module_name)
            if hasattr(module, name):
                resolved[name] = getattr(module, name)
                found = True
                break
        if not found:
            still_unresolved.add(name)
    return resolved, still_unresolved


class _FakeCosmosContainer:
    def __init__(self):
        self.created_items = []

    def create_item(self, body):
        self.created_items.append(body)
        return body


def _build_namespace():
    import logging
    import math
    import os
    import time
    import uuid
    import json as json_module
    from collections import Counter
    from datetime import datetime, timedelta, timezone
    from flask import current_app, has_app_context
    from azure.core import MatchConditions
    from azure.core.exceptions import ResourceExistsError
    from azure.cosmos.exceptions import CosmosResourceNotFoundError

    source = EXPORT_MODULE.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(EXPORT_MODULE))
    included, unresolved = _collect_local_closure(tree, {"queue_tabular_generated_output_run"})

    fake_container = _FakeCosmosContainer()
    namespace = {
        "__builtins__": __builtins__,
        "os": os,
        "uuid": uuid,
        "json": json_module,
        "math": math,
        "logging": logging,
        "time": time,
        "Counter": Counter,
        "datetime": datetime,
        "timedelta": timedelta,
        "timezone": timezone,
        "current_app": current_app,
        "has_app_context": has_app_context,
        "MatchConditions": MatchConditions,
        "ResourceExistsError": ResourceExistsError,
        "CosmosResourceNotFoundError": CosmosResourceNotFoundError,
        "cosmos_tabular_export_runs_container": fake_container,
        "cosmos_conversations_container": object(),
        "storage_account_personal_chat_container_name": "personal-chat-container",
        "storage_account_group_documents_container_name": "group-documents-container",
        "storage_account_public_documents_container_name": "public-documents-container",
        "storage_account_user_documents_container_name": "user-documents-container",
        "TABULAR_EXTENSIONS": {"csv", "xlsx", "xls", "xlsm"},
        "CLIENTS": {},
        "log_event": lambda *args, **kwargs: None,
        "_upload_json_blob": lambda *args, **kwargs: None,
        "_download_json_blob": lambda *args, **kwargs: {},
        "_get_blob_service_client": lambda: None,
        # Faithful to the real function's own behavior outside a Flask app context.
        "submit_tabular_generated_output_run": lambda run_id, user_id: False,
    }

    still_needed = {name for name in unresolved if name not in namespace}
    resolved_cross_module, still_unresolved = _resolve_cross_module_names(still_needed)
    namespace.update(resolved_cross_module)

    if still_unresolved:
        raise AssertionError(
            f"Could not resolve required names for queue_tabular_generated_output_run "
            f"end-to-end test: {sorted(still_unresolved)}"
        )

    # Preserve original module source order (not discovery order): default-argument
    # values and other top-level expressions are evaluated when each statement runs,
    # so constants must appear before the functions/defaults that reference them.
    included_names = set(included.keys())
    ordered_nodes = [node for node in tree.body if _module_node_name(node) in included_names]

    module = ast.Module(body=ordered_nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, str(EXPORT_MODULE), "exec"), namespace)
    return namespace, fake_container


def _build_financial_review_source_descriptor():
    return {
        "blob_path": "user-1/financial_review.csv",
        "blob_etag": "etag-financial-review-v1",
        "expected_row_count": 200,
        "source": "workspace",
        "scope_id": "user-1",
        "container": "personal-chat-container",
    }


def test_combined_run_with_no_output_hints_is_created_with_deferred_schema():
    """The real queue function must not lock output_schema when no public schema is known."""
    assert_app_version_at_least(IMPLEMENTED_VERSION)
    namespace, fake_container = _build_namespace()
    queue_run = namespace["queue_tabular_generated_output_run"]

    planner_metadata = {
        "planner_contract_version": "tabular-orchestration-v1",
        "execution_contract": "combined",
        "execution_state": "queued",
        "durable_task_type": "combined",
        "reason_code": "active_execution_accepted",
        "deliverable_contract": {
            "contract_version": "analysis-deliverables-v3",
            "action_mode": "analyze",
            "analysis_required": True,
            "primary_artifact_role": "primary_analysis",
            "public_output_schema": [],
            "internal_checkpoint_schema": ["source_row_number", "source_row_identity"],
            "lineage_schema": ["source_row_number", "source_row_identity"],
            "row_cardinality": "one_per_source_row",
            "ordering": "source_order",
            "transformation_mode": "semantic",
            "validation_profile": "exact_rows_schema",
            "publication_policy": "primary_then_sibling",
        },
    }

    run = queue_run(
        user_id="user-1",
        conversation_id="conversation-1",
        user_question="Per-row financial review. Download the result as CSV.",
        source_candidate={"filename": "financial_review.csv"},
        output_format="csv",
        row_batches=None,
        gpt_model="gpt-5.6-luna",
        settings={},
        source_descriptor=_build_financial_review_source_descriptor(),
        task_type="combined",
        analysis_objective="Per-row financial review",
        planner_metadata=planner_metadata,
    )

    assert fake_container.created_items, "the real function must create exactly one Cosmos run item"
    persisted_run = fake_container.created_items[0]
    assert persisted_run["output_schema"] is None, (
        "output_schema must stay None so batch 1 can discover the real schema; "
        f"got {persisted_run['output_schema']!r}"
    )
    assert persisted_run["public_output_schema"] == []
    assert persisted_run["internal_checkpoint_schema"] == ["source_row_number", "source_row_identity"]
    assert run["output_schema"] is None


def test_combined_run_with_known_output_schema_still_locks_it_up_front():
    """When the real business columns are already known, output_schema must still be pre-set."""
    assert_app_version_at_least(IMPLEMENTED_VERSION)
    namespace, fake_container = _build_namespace()
    queue_run = namespace["queue_tabular_generated_output_run"]

    known_columns = ["Item_ID", "Timeline_Status", "Overall_Attention"]
    planner_metadata = {
        "planner_contract_version": "tabular-orchestration-v1",
        "execution_contract": "combined",
        "execution_state": "queued",
        "durable_task_type": "combined",
        "reason_code": "active_execution_accepted",
        "deliverable_contract": {
            "contract_version": "analysis-deliverables-v3",
            "action_mode": "analyze",
            "analysis_required": True,
            "primary_artifact_role": "primary_analysis",
            "public_output_schema": known_columns,
            "internal_checkpoint_schema": ["source_row_number", "source_row_identity"] + known_columns,
            "lineage_schema": ["source_row_number", "source_row_identity"],
            "row_cardinality": "one_per_source_row",
            "ordering": "source_order",
            "transformation_mode": "semantic",
            "validation_profile": "exact_rows_schema",
            "publication_policy": "primary_then_sibling",
        },
    }

    run = queue_run(
        user_id="user-1",
        conversation_id="conversation-1",
        user_question="Per-row financial review. Download the result as CSV.",
        source_candidate={"filename": "financial_review.csv"},
        output_format="csv",
        row_batches=None,
        gpt_model="gpt-5.6-luna",
        settings={},
        source_descriptor=_build_financial_review_source_descriptor(),
        task_type="combined",
        analysis_objective="Per-row financial review",
        planner_metadata=planner_metadata,
    )

    persisted_run = fake_container.created_items[0]
    assert persisted_run["output_schema"] == ["source_row_number", "source_row_identity"] + known_columns
    assert run["output_schema"] == persisted_run["output_schema"]


if __name__ == "__main__":
    tests = [
        test_combined_run_with_no_output_hints_is_created_with_deferred_schema,
        test_combined_run_with_known_output_schema_still_locks_it_up_front,
    ]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except Exception as exc:  # noqa: BLE001 - surface the exact missing-dependency failure
            failures += 1
            print(f"FAIL {test.__name__}: {exc}")
    sys.exit(1 if failures else 0)
