# offline_bootstrap.py
"""External-I/O-only bootstrap seams for fresh-process application integration tests."""

import asyncio
from contextlib import contextmanager
from copy import deepcopy
import os
import socket
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from azure.cosmos.exceptions import CosmosResourceNotFoundError


class OfflineContainer:
    def __init__(self):
        self.items = {}
        self.revision = 0

    def read_item(self, item, partition_key, **kwargs):
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
def offline_app_imports():
    # Windows creates a loopback socket pair before the network prohibition is installed.
    loop = asyncio.new_event_loop()
    attempts = []

    def no_network(*args, **kwargs):
        attempts.append(True)
        raise AssertionError("Offline integration attempted network access.")

    try:
        with TemporaryDirectory() as session_dir, patch.dict(os.environ, {
            "SESSION_FILE_DIR": session_dir,
            "SIMPLECHAT_RUN_BACKGROUND_TASKS": "0",
            "DISABLE_FLASK_INSTRUMENTATION": "1",
        }), patch("azure.cosmos.CosmosClient", OfflineCosmos), patch.object(socket.socket, "connect", no_network):
            yield SimpleNamespace(loop=loop, network_attempts=attempts)
            if attempts:
                raise AssertionError("Application swallowed a blocked network attempt.")
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
