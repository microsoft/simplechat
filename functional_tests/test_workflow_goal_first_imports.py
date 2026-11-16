# test_workflow_goal_first_imports.py
"""
Real-module lifecycle coverage for deferred workflow document-action dependencies.
Version: 0.261.336
Implemented in: 0.261.336

CodeQL's py/cyclic-import includes deferred service-to-runner paths. These tests
verify the existing lifecycle, not disappearance of every static graph cycle:
pure contracts before bootstrap, both consumer orders after the real settings
bootstrap, web/scheduler startup and real scoped-search authorization failures.
No configuration, runtime owner or selector module is replaced.
"""

import ast
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
TESTS = ROOT / "functional_tests"

PURE_PROBE = r'''
import socket
import sys
from unittest.mock import patch

sys.path[:0] = sys.argv[1:3]

def no_network(*args, **kwargs):
    raise AssertionError("Pure workflow contract attempted external I/O.")

with patch.object(socket.socket, "connect", no_network), patch.object(socket, "getaddrinfo", no_network), \
     patch("azure.cosmos.CosmosClient", side_effect=AssertionError("Pure contracts constructed a Cosmos client.")):
    import functions_workflow_action_choice as choice
    import functions_workflow_document_selection as selection
    from functions_workflow_limits import WorkflowLoopInputError

    if any(name in sys.modules for name in ("config", "functions_settings", "functions_workflow_runner")):
        raise AssertionError("Pure workflow contracts initialized application services.")
    try:
        selection.DocumentSelectionMatcher({"scopes": []}, 60)
    except selection.DocumentSelectionError:
        pass
    else:
        raise AssertionError("Uninitialized selection accepted missing scopes.")
    try:
        choice.parse_choice('{"action":"external_tool","summary":"Not allowed."}')
    except choice.WorkflowActionChoiceError:
        pass
    else:
        raise AssertionError("The pure choice contract accepted an external action.")
    if not issubclass(WorkflowLoopInputError, ValueError):
        raise AssertionError("The loop input failure contract changed.")
print("PASS: pure workflow contracts before bootstrap")
'''

RUNTIME_PROBE = r'''
import faulthandler
import importlib
import socket
import sys
from unittest.mock import patch

faulthandler.dump_traceback_later(240, exit=True)
sys.path[:0] = sys.argv[1:3]
from test_support.offline_bootstrap import offline_app_imports

with offline_app_imports() as environment, \
     patch.object(socket, "getaddrinfo", side_effect=AssertionError("Workflow startup attempted DNS access.")):
    for name in sys.argv[3].split(","):
        importlib.import_module(name)
    runner = importlib.import_module("functions_workflow_runner")
    actions = importlib.import_module("functions_document_actions")
    loops = importlib.import_module("functions_workflow_loop_inputs")
    groups = importlib.import_module("functions_group")
    public = importlib.import_module("functions_public_workspaces")
    from functions_workflow_limits import WorkflowLoopInputError

    settings = {"document_action_capabilities": {
        "analyze": {"enabled": True, "workflow_max_documents": 11},
        "comparison": {"enabled": True, "workflow_max_documents": 3},
        "merge": {"enabled": True, "workflow_max_documents": 8},
    }}
    runtime_limit = runner._get_recent_workflow_document_limit("choose", settings)
    preview_limit = actions.get_workflow_document_selection_limit("choose", settings=settings)
    if runtime_limit != 3 or preview_limit != runtime_limit:
        raise AssertionError("Runtime choice no longer shares the conservative preview limit.")

    calls = []
    authorizations = []

    def authorize_group(actor, scope_id, *, allowed_roles):
        authorizations.append((actor, scope_id, allowed_roles))
        return True

    def search(**kwargs):
        calls.append(kwargs)
        return {"results": []}

    workflow = {"user_id": "owner", "task_prompt": "Find relevant retention passages."}
    action = {
        "type": "search", "target_mode": "selected", "document_ids": [],
        "relevance_scopes": [
            {"scope_type": "group", "scope_id": "group-one"},
            {"scope_type": "public", "scope_id": "public-one"},
        ],
    }
    with patch.object(groups, "assert_group_role", authorize_group), \
         patch.object(groups, "find_group_by_id", return_value={"id": "group-one"}), \
         patch.object(groups, "check_group_status_allows_operation", return_value=(True, "")), \
         patch.object(public, "find_public_workspace_by_id", return_value={"id": "public-one"}), \
         patch.object(public, "check_public_workspace_status_allows_operation", return_value=(True, "")), \
         patch.object(runner, "search_documents", search):
        result = runner._prepare_workflow_search_context(workflow, action, settings)
        if result["result_count"] != 0 or [call["doc_scope"] for call in calls] != ["group", "public"]:
            raise AssertionError("Real scoped Search broadened or changed its source scopes.")
        if authorizations != [("owner", "group-one", loops.READ_GROUP_ROLES)]:
            raise AssertionError("Real scoped Search did not use the shared group authorization.")
        if calls[0]["active_group_ids"] != ["group-one"] or calls[1]["active_public_workspace_id"] != ["public-one"]:
            raise AssertionError("Real scoped Search changed the authorized workspace identifiers.")
        with patch.object(groups, "assert_group_role", side_effect=PermissionError("denied")):
            try:
                runner._prepare_workflow_search_context(workflow, action, settings)
            except WorkflowLoopInputError:
                pass
            else:
                raise AssertionError("Group authorization failure became a successful Search.")
        if len(calls) != 2:
            raise AssertionError("Denied source access reached the Search transport.")
        with patch.object(public, "check_public_workspace_status_allows_operation", return_value=(False, "closed")):
            try:
                runner._prepare_workflow_search_context(
                    workflow, {**action, "relevance_scopes": action["relevance_scopes"][1:]}, settings,
                )
            except WorkflowLoopInputError:
                pass
            else:
                raise AssertionError("Unavailable public workspace became a successful Search.")
        if len(calls) != 2:
            raise AssertionError("Unavailable workspace reached the Search transport.")

    scheduler = importlib.import_module("background_tasks")
    if not callable(scheduler.check_m365_workflow_continuations_once):
        raise AssertionError("Real scheduler bootstrap did not complete.")
    if "app" in sys.argv[3].split(",") and not hasattr(sys.modules["app"], "app"):
        raise AssertionError("Real web bootstrap did not complete.")
    if environment.network_attempts:
        raise AssertionError("The workflow lifecycle swallowed a network failure.")
faulthandler.cancel_dump_traceback_later()
print("PASS: real workflow runtime imports, limits, source authorization and web/scheduler wiring")
'''


def run_probe(probe, optimized, *arguments):
    result = subprocess.run(
        [sys.executable, "-B", *(["-O"] if optimized else []), "-c", probe, str(APP), str(TESTS), *arguments],
        cwd=ROOT, capture_output=True, text=True, timeout=300, check=False,
    )
    assert result.returncode == 0, result.stdout[-8000:] + result.stderr[-8000:]
    assert "PASS:" in result.stdout


@pytest.mark.parametrize("optimized", [False, True], ids=["normal", "optimized"])
def test_pure_choice_and_selection_contracts_do_not_bootstrap_services(optimized):
    run_probe(PURE_PROBE, optimized)


@pytest.mark.parametrize("optimized", [False, True], ids=["normal", "optimized"])
@pytest.mark.parametrize("order", [
    "config,functions_settings,functions_document_actions,functions_workflow_loop_inputs,functions_workflow_runner",
    "config,functions_settings,functions_workflow_runner,functions_workflow_loop_inputs,functions_document_actions",
    "app,background_tasks",
    "background_tasks",
], ids=["contracts-first", "runner-first", "web-first", "scheduler-first"])
def test_real_workflow_imports_and_scoped_search_fail_closed(order, optimized):
    run_probe(RUNTIME_PROBE, optimized, order)


def test_reviewed_service_dependencies_remain_at_runtime_boundaries():
    tree = ast.parse((APP / "functions_workflow_runner.py").read_text(encoding="utf-8"))
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    for owner, dependency in [
        ("_get_recent_workflow_document_limit", "functions_document_actions"),
        ("_prepare_workflow_search_context", "functions_workflow_loop_inputs"),
    ]:
        imports = [node for node in ast.walk(functions[owner]) if isinstance(node, ast.ImportFrom)]
        assert any(node.module == dependency for node in imports)
