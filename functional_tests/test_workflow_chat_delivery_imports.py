#!/usr/bin/env python3
# test_workflow_chat_delivery_imports.py
"""
Functional test for the workflow chat delivery import lifecycle.
Version: 0.261.226
Implemented in: 0.261.226

This test ensures chat delivery contract, worker, status, route, and runtime imports stay cold-import safe across normal and optimized interpreters.
The contract-consumer orders start from the app.py bootstrap (config, then functions_settings), because a cold
functions_personal_workflows import already fails on the base branch through an unrelated
functions_document_actions -> functions_settings cycle. The contract and the workflow runtime are also checked
fully cold, in both orders, without loading config.
"""

import itertools
from pathlib import Path
import subprocess
import sys

import pytest

from test_support.versioning import assert_app_version_at_least


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
TESTS = ROOT / "functional_tests"
CONTRACT_MODULE = "functions_workflow_chat_delivery"
STATUS_MODULE = "functions_workflow_chat_delivery_status"
WORKER_MODULE = "functions_workflow_chat_delivery_worker"
PERSONAL_WORKFLOWS_MODULE = "functions_personal_workflows"
RUNTIME_MODULE = "functions_workflow_runtime"
BACKGROUND_TASKS_MODULE = "background_tasks"
ORCHESTRATION_ROUTE_MODULE = "route_backend_orchestration"
CONVERSATIONS_ROUTE_MODULE = "route_backend_conversations"
RUNS_MODULE = "functions_orchestration_workflow_runs"

PROBE = r'''
import faulthandler
import importlib
import os
import socket
import sys
from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

from azure.cosmos.exceptions import CosmosResourceNotFoundError

# A probe normally finishes in seconds. If one stalls, dump every thread's stack and exit before
# the parent's 300 second cap, so the failure shows where it stalled instead of a bare timeout.
faulthandler.dump_traceback_later(240, exit=True)
sys.path[:0] = sys.argv[1:3]

CONTRACT_MODULE = "functions_workflow_chat_delivery"
STATUS_MODULE = "functions_workflow_chat_delivery_status"
WORKER_MODULE = "functions_workflow_chat_delivery_worker"
PERSONAL_WORKFLOWS_MODULE = "functions_personal_workflows"
RUNTIME_MODULE = "functions_workflow_runtime"
BACKGROUND_TASKS_MODULE = "background_tasks"
ORCHESTRATION_ROUTE_MODULE = "route_backend_orchestration"
CONVERSATIONS_ROUTE_MODULE = "route_backend_conversations"
RUNS_MODULE = "functions_orchestration_workflow_runs"
ENV_KEYS = ("SIMPLECHAT_RUN_BACKGROUND_TASKS", "DISABLE_FLASK_INSTRUMENTATION")
# app.py loads config (L24) and functions_settings (through functions_content, L31) before any
# workflow module. functions_personal_workflows cannot be imported ahead of functions_settings on
# the base branch either (functions_document_actions -> ... -> functions_settings -> back), so the
# consumer orders start from that bootstrap instead of pinning an unrelated, pre-existing cycle.
BOOTSTRAP = ("config", "functions_settings")
CONSUMERS = (CONTRACT_MODULE, PERSONAL_WORKFLOWS_MODULE, RUNTIME_MODULE)
PERSONAL_SHARED_NAMES = (
    "delivery_log",
    "merge_stored_run_fields",
    "needs_guarded_run_save",
)
RUNTIME_SHARED_NAMES = (
    "CHAT_DELIVERY_KEY",
    "control_summary",
    "delivery_log",
    "finalize_chat_delivery_seed",
    "reconcile_chat_delivery",
    "signal_workflow_chat_delivery",
)


class OfflineContainer:
    def __init__(self):
        self.items = {}
        self.revision = 0

    def read_item(self, item, partition_key=None, **kwargs):
        if item not in self.items:
            raise CosmosResourceNotFoundError(status_code=404)
        return deepcopy(self.items[item])

    def upsert_item(self, body, **kwargs):
        self.revision += 1
        saved = {**deepcopy(body), "_etag": str(self.revision)}
        self.items[saved["id"]] = saved
        return deepcopy(saved)

    create_item = upsert_item

    def replace_item(self, item, body, **kwargs):
        return self.upsert_item(body)

    def query_items(self, *args, **kwargs):
        return []

    def read(self):
        return {"id": "offline", "partitionKey": {"paths": ["/id"]}}

    def delete_item(self, item, **kwargs):
        self.items.pop(item, None)


class OfflineDatabase:
    def __init__(self):
        self.containers = {}

    def create_container_if_not_exists(self, id, **kwargs):
        return self.containers.setdefault(id, OfflineContainer())

    get_container_client = create_container_if_not_exists

    def read(self):
        return {"id": "SimpleChat"}


class OfflineCosmos:
    def __init__(self, *args, **kwargs):
        self.database = OfflineDatabase()

    def create_database_if_not_exists(self, *args, **kwargs):
        return self.database

    get_database_client = create_database_if_not_exists


@contextmanager
def offline_imports():
    attempts = []
    original_env = {key: os.environ.get(key) for key in ENV_KEYS}
    original_connect = socket.socket.connect

    def no_network(*args, **kwargs):
        attempts.append(True)
        raise AssertionError("Offline import probe attempted network access.")

    with patch.dict(os.environ, {
        "SIMPLECHAT_RUN_BACKGROUND_TASKS": "0",
        "DISABLE_FLASK_INSTRUMENTATION": "1",
    }), patch("azure.cosmos.CosmosClient", OfflineCosmos), patch.object(socket.socket, "connect", no_network):
        yield SimpleNamespace(network_attempts=attempts)
        if attempts:
            raise AssertionError("A cold import swallowed a blocked network attempt.")
    for key, value in original_env.items():
        if os.environ.get(key) != value:
            raise AssertionError(f"Environment key {key} was not restored")
    if socket.socket.connect is not original_connect:
        raise AssertionError("Socket patch was not restored")


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def import_order(names):
    with offline_imports() as environment:
        modules = [importlib.import_module(name) for name in names]
        if environment.network_attempts:
            raise AssertionError("Import order attempted network access")
    return modules


def verify_shared_names(consumer_name, names):
    contract = sys.modules[CONTRACT_MODULE]
    consumer = sys.modules[consumer_name]
    for name in names:
        require(
            getattr(consumer, name) is getattr(contract, name),
            f"{consumer_name}.{name} is not the contract object",
        )


def check_contract_order(names):
    import_order(BOOTSTRAP)
    preloaded = [name for name in CONSUMERS if name in sys.modules]
    require(not preloaded, f"the app bootstrap already imported {preloaded}, so the order is not exercised")
    import_order(names)
    verify_shared_names(PERSONAL_WORKFLOWS_MODULE, PERSONAL_SHARED_NAMES)
    verify_shared_names(RUNTIME_MODULE, RUNTIME_SHARED_NAMES)
    print("PASS: contract consumers share contract objects")


def check_runtime_cold_order(names):
    require("config" not in sys.modules, "probe started after config was imported")
    import_order(names)
    require("config" not in sys.modules, "the contract or the workflow runtime imported config")
    verify_shared_names(RUNTIME_MODULE, RUNTIME_SHARED_NAMES)
    print("PASS: contract and runtime import cold and share contract objects")


def check_import_order(names):
    import_order(names)
    print("PASS: import order " + "+".join(names))


def check_cold_module_does_not_load_config(module_name):
    require("config" not in sys.modules, "probe started after config was imported")
    import_order((module_name,))
    require("config" not in sys.modules, f"{module_name} imported config")
    require(RUNTIME_MODULE not in sys.modules, f"{module_name} imported workflow runtime")
    print(f"PASS: {module_name} stays cold")


def check_route_wiring():
    with offline_imports() as environment:
        from flask import Blueprint, Flask

        route = importlib.import_module(ORCHESTRATION_ROUTE_MODULE)
        conversations = importlib.import_module(CONVERSATIONS_ROUTE_MODULE)
        runs = importlib.import_module(RUNS_MODULE)
        status = importlib.import_module(STATUS_MODULE)
        app = Flask(__name__)
        app.config.update(TESTING=True, SECRET_KEY="workflow-chat-delivery-imports")
        blueprint = Blueprint("backend_orchestration", __name__)
        route.register_route_backend_orchestration(blueprint)
        app.register_blueprint(blueprint)
        rules = {
            rule.rule: rule for rule in app.url_map.iter_rules()
            if rule.endpoint == "backend_orchestration.orchestration_workflow_run_status"
        }
        require(
            "/api/v2/orchestration/workflow-runs/status" in rules,
            "status route was not registered on the orchestration blueprint",
        )
        require("GET" in rules["/api/v2/orchestration/workflow-runs/status"].methods, "status route does not allow GET")
        view = app.view_functions.get("backend_orchestration.orchestration_workflow_run_status")
        require(view is not None, "status route view function is missing")
        require(route._workflow_run_status() is status, "route lazy status import resolved a different module")
        require(hasattr(conversations, "workflow_delivery_refusal_payload"), "conversation route contract import is missing")
        require(hasattr(runs, "started_workflow_run_id"), "workflow run seed module did not import")
        if environment.network_attempts:
            raise AssertionError("Route wiring attempted network access")
    print("PASS: route wiring imports and registers status route")


action = sys.argv[3]
if action == "contract-order":
    check_contract_order(sys.argv[4:])
elif action == "runtime-cold":
    check_runtime_cold_order(sys.argv[4:])
elif action == "import-order":
    check_import_order(sys.argv[4:])
elif action == "cold":
    check_cold_module_does_not_load_config(sys.argv[4])
elif action == "route-wiring":
    check_route_wiring()
else:
    raise AssertionError(f"Unknown probe action: {action}")
'''


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def _output_text(value):
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value or ""


def run_probe(action, *arguments, optimized=False):
    command = [sys.executable, "-B"]
    if optimized:
        command.append("-O")
    label = " ".join((action, *arguments)) + (" (-O)" if optimized else "")
    try:
        process = subprocess.run(
            command + ["-c", PROBE, str(APP), str(TESTS), action, *arguments],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise AssertionError(
            f"import probe {label} did not finish in 300s and its stack-dump watchdog did not fire; "
            f"partial output:\n{_output_text(exc.stdout)[-4000:]}{_output_text(exc.stderr)[-4000:]}"
        ) from exc
    if process.returncode != 0:
        stalled = "Timeout (" in process.stderr and "(most recent call first)" in process.stderr
        lead = (
            f"import probe {label} stalled for 240s; its thread stacks follow:\n"
            if stalled
            else f"import probe {label} exited with {process.returncode}:\n"
        )
        raise AssertionError(lead + process.stdout[-8000:] + process.stderr[-8000:])
    require("PASS:" in process.stdout, f"probe did not print a pass marker: {process.stdout}")
    return process


def test_version_is_at_least_the_chat_delivery_release():
    assert_app_version_at_least("0.261.226")


@pytest.mark.parametrize("optimized", [False, True], ids=["normal", "optimized"])
@pytest.mark.parametrize(
    "order",
    list(itertools.permutations((CONTRACT_MODULE, PERSONAL_WORKFLOWS_MODULE, RUNTIME_MODULE))),
    ids=lambda order: "+".join(name.removeprefix("functions_") for name in order),
)
def test_contract_consumers_import_in_every_order_after_the_app_bootstrap(order, optimized):
    run_probe("contract-order", *order, optimized=optimized)


@pytest.mark.parametrize("optimized", [False, True], ids=["normal", "optimized"])
@pytest.mark.parametrize(
    "order",
    list(itertools.permutations((CONTRACT_MODULE, RUNTIME_MODULE))),
    ids=lambda order: "+".join(name.removeprefix("functions_") for name in order),
)
def test_contract_and_runtime_import_cold_in_both_orders_without_config(order, optimized):
    run_probe("runtime-cold", *order, optimized=optimized)


@pytest.mark.parametrize("optimized", [False, True], ids=["normal", "optimized"])
@pytest.mark.parametrize(
    "order",
    [
        (WORKER_MODULE, STATUS_MODULE, BACKGROUND_TASKS_MODULE),
        (BACKGROUND_TASKS_MODULE, WORKER_MODULE, STATUS_MODULE),
        (WORKER_MODULE, STATUS_MODULE, ORCHESTRATION_ROUTE_MODULE),
        (ORCHESTRATION_ROUTE_MODULE, WORKER_MODULE, STATUS_MODULE),
    ],
    ids=lambda order: "+".join(name.removeprefix("functions_") for name in order),
)
def test_worker_and_status_import_around_background_tasks_and_routes(order, optimized):
    run_probe("import-order", *order, optimized=optimized)


@pytest.mark.parametrize("optimized", [False, True], ids=["normal", "optimized"])
@pytest.mark.parametrize("module_name", [CONTRACT_MODULE, STATUS_MODULE], ids=["contract", "status"])
def test_cold_contract_and_status_imports_do_not_load_config_or_runtime(module_name, optimized):
    run_probe("cold", module_name, optimized=optimized)


@pytest.mark.parametrize("optimized", [False, True], ids=["normal", "optimized"])
def test_route_imports_and_status_route_wiring_load_in_fresh_process(optimized):
    run_probe("route-wiring", optimized=optimized)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
