# test_m365_runtime_imports.py
"""
Cold-import regression for Microsoft 365 web/scheduler integration.
Version: 0.261.029
Implemented in: 0.261.029

Imports real application/configuration modules in fresh normal and optimized
interpreters. Only external Cosmos I/O is faked; every network socket is blocked.
"""

from pathlib import Path
import subprocess
import sys

import pytest


APP = Path(__file__).resolve().parents[1] / "application" / "single_app"
PROBE = r'''
import copy
import importlib
import socket
import sys
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

def no_network(*args, **kwargs):
    raise AssertionError("A cold import attempted network access")

with patch("azure.cosmos.CosmosClient", Cosmos), patch.object(socket.socket, "connect", no_network):
    for module in sys.argv[2:]:
        imported = importlib.import_module(module)
        if imported is None:
            raise AssertionError("Module import failed")
    import config
    if config.cosmos_m365_connections_container is config.cosmos_m365_execution_runs_container:
        raise AssertionError("Credentials and conversation jobs must have different stores")
    import background_tasks
    pending = background_tasks.check_m365_workflow_continuations_once()
    if pending != []:
        raise AssertionError("An empty scheduler must not invent workflow continuations")
'''


@pytest.mark.parametrize("optimized", [False, True])
@pytest.mark.parametrize("first", ["config", "functions_m365_execution", "functions_collaboration"])
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
