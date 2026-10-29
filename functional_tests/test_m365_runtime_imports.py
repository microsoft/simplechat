# test_m365_runtime_imports.py
"""
Cold-import regression for Microsoft 365 web/scheduler integration.
Version: 0.261.030
Implemented in: 0.261.029

Imports real application/configuration modules in fresh normal and optimized
interpreters. Only external Cosmos I/O is faked; every network socket is blocked.
"""

import ast
from pathlib import Path
import subprocess
import sys

import pytest


APP = Path(__file__).resolve().parents[1] / "application" / "single_app"
PROBE = r'''
import copy
import importlib
import os
import socket
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch
from azure.cosmos.exceptions import CosmosResourceNotFoundError

sys.path.insert(0, sys.argv[1])

class Container:
    def __init__(self):
        self.items = {}
    def read_item(self, item, partition_key, **kwargs):
        if item not in self.items:
            raise CosmosResourceNotFoundError(status_code=404)
        return copy.deepcopy(self.items[item])
    def upsert_item(self, body, **kwargs):
        self.items[body["id"]] = copy.deepcopy(body)
        return copy.deepcopy(body)
    create_item = upsert_item
    def query_items(self, *args, **kwargs):
        return []
    def read(self):
        return {"id": "test", "partitionKey": {"paths": ["/id"]}}
    def delete_item(self, item, **kwargs):
        self.items.pop(item, None)

class Database:
    def __init__(self):
        self.containers = {}
    def create_container_if_not_exists(self, id, **kwargs):
        return self.containers.setdefault(id, Container())
    def get_container_client(self, id):
        return self.create_container_if_not_exists(id)
    def read(self):
        return {"id": "SimpleChat"}

class Cosmos:
    def __init__(self, *args, **kwargs):
        self.database = Database()
    def create_database_if_not_exists(self, *args, **kwargs):
        return self.database
    get_database_client = create_database_if_not_exists

network_attempts = []

def no_network(*args, **kwargs):
    network_attempts.append(True)
    raise AssertionError("A cold import attempted network access")

with TemporaryDirectory() as session_dir, patch.dict(os.environ, {
    "SESSION_FILE_DIR": session_dir,
    "SIMPLECHAT_RUN_BACKGROUND_TASKS": "0",
    "DISABLE_FLASK_INSTRUMENTATION": "1",
}), patch("azure.cosmos.CosmosClient", Cosmos), patch.object(socket.socket, "connect", no_network):
    for module in sys.argv[2:]:
        imported = importlib.import_module(module)
        if imported is None:
            raise AssertionError("Module import failed")
    import config
    if config.cosmos_m365_connections_container is config.cosmos_m365_execution_runs_container:
        raise AssertionError("Credentials and conversation jobs must have different stores")
    import app
    import functions_m365_connections as connections
    import functions_m365_execution as execution
    service = connections.get_m365_connection_service()
    if service.workflow_authorizer is not execution.validate_m365_workflow_context:
        raise AssertionError("The web bootstrap did not wire live workflow authorization")
    service.workflow_authorizer = None
    import background_tasks
    pending = background_tasks.check_m365_workflow_continuations_once()
    if pending != []:
        raise AssertionError("An empty scheduler must not invent workflow continuations")
    if connections.get_m365_connection_service() is not service:
        raise AssertionError("The scheduler replaced the configured connection service")
    if service.workflow_authorizer is not execution.validate_m365_workflow_context:
        raise AssertionError("The scheduler did not wire live workflow authorization")
    if network_attempts:
        raise AssertionError("Bootstrap swallowed a blocked network attempt")
'''
EARLY_PROBE = r'''
import builtins
import hashlib
import importlib
import socket
import sys
from unittest.mock import patch

sys.path.insert(0, sys.argv[1])
real_import = builtins.__import__
forbidden = {"config", "functions_settings", "functions_appinsights", "functions_notifications"}

def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    if level == 0 and name in forbidden:
        raise AssertionError("The context/connection boundary imported its runtime owner: " + name)
    return real_import(name, globals, locals, fromlist, level)

def no_network(*args, **kwargs):
    raise AssertionError("An early context import attempted network access")

with patch.object(builtins, "__import__", guarded_import), patch.object(socket.socket, "connect", no_network):
    for module in sys.argv[2:]:
        importlib.import_module(module)
    import functions_m365_context as context_scope
    import functions_m365_connections as connections
    import functions_m365_execution as execution
    import functions_m365_approvals as approvals
    if execution.M365ExecutionContext is not context_scope.M365ExecutionContext:
        raise AssertionError("The execution facade changed context identity")
    if approvals.M365PolicyError is not context_scope.M365PolicyError:
        raise AssertionError("The approval facade changed error identity")
    material = {"b": ("two", 2), "a": {"enabled": True, "none": None}}
    canonical = b'{"a":{"enabled":true,"none":null},"b":["two",2]}'
    fingerprint = approvals.material_fingerprint(material)
    if fingerprint != hashlib.sha256(canonical).hexdigest():
        raise AssertionError("Existing approval/connection fingerprint encoding changed")
    context = context_scope.M365ExecutionContext(
        "owner", "subject", "tenant", workflow_id="workflow", run_id="run",
        request_id="request", workflow_fingerprint="revision",
        binding_id="binding", connection_id="connection",
    )
    with execution.m365_execution_context(context):
        scoped = context_scope.get_m365_execution_context()
        if scoped is not context:
            raise AssertionError("The facade does not share the same context state")
        result = connections.get_m365_access_token(["Mail.Read"])
        if result.get("error") != "m365_authorization_unavailable" or "access_token" in result:
            raise AssertionError("An unconfigured connection did not fail closed")
    cleared = context_scope.get_m365_execution_context()
    if cleared is not None:
        raise AssertionError("The context was not restored")
    if any(name in sys.modules for name in forbidden):
        raise AssertionError("Early access loaded a runtime owner")
'''


@pytest.mark.parametrize("optimized", [False, True])
@pytest.mark.parametrize("first", [
    "config", "functions_m365_execution", "functions_m365_connections", "functions_collaboration",
])
def test_web_scheduler_modules_import_without_reversed_bootstrap_or_network(optimized, first):
    command = [sys.executable]
    if optimized:
        command.append("-O")
    command += [
        "-c", PROBE, str(APP), first, "functions_m365_runtime",
        "conversation_memory_runtime", "functions_workflow_runner",
        "route_backend_m365", "route_backend_collaboration", "route_backend_chats", "background_tasks",
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-8000:]


@pytest.mark.parametrize("optimized", [False, True])
@pytest.mark.parametrize("order", [
    ("functions_m365_execution", "functions_m365_connections"),
    ("functions_m365_connections", "functions_m365_execution"),
])
def test_early_context_and_connections_have_no_runtime_owner_or_credential_fallback(optimized, order):
    command = [sys.executable, "-B"]
    if optimized:
        command.append("-O")
    result = subprocess.run(
        command + ["-c", EARLY_PROBE, str(APP), *order],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def imported_modules(filename):
    tree = ast.parse((APP / filename).read_text(encoding="utf-8-sig"))
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])
        elif isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
    return imports


def test_context_and_connection_dependencies_do_not_import_execution_owner():
    context_imports = imported_modules("functions_m365_context.py")
    repository_imports = [name for name in context_imports if (APP / f"{name}.py").is_file()]
    assert repository_imports == []
    connection_imports = imported_modules("functions_m365_connections.py")
    assert "functions_m365_context" in connection_imports
    assert "functions_m365_execution" not in connection_imports
    execution_imports = imported_modules("functions_m365_execution.py")
    assert "functions_m365_connections" in execution_imports
