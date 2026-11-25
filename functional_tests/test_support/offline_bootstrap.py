# offline_bootstrap.py
"""External-I/O-only bootstrap seams for fresh-process application integration tests.

Version: 0.261.485
Implemented in: 0.261.324 (SDK-shaped point response default)
Conditional partial updates implemented in: 0.261.485
"""

import asyncio
from contextlib import contextmanager
from copy import deepcopy
import os
import socket
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from azure.core import MatchConditions
from azure.cosmos.exceptions import CosmosAccessConditionFailedError, CosmosResourceNotFoundError
from azure.cosmos._cosmos_responses import CosmosDict

from test_support.cosmos_patch import patch_document


class OfflineContainer:
    def __init__(self, *, sdk_responses=True):
        self.sdk_responses = sdk_responses
        self.items = {}
        self.revision = 0

    def _response(self, body):
        value = deepcopy(dict(body))
        return CosmosDict(value, response_headers={}) if self.sdk_responses else value

    def read_item(self, item, partition_key, **kwargs):
        if item not in self.items:
            raise CosmosResourceNotFoundError(status_code=404)
        return self._response(self.items[item])

    def upsert_item(self, body, **kwargs):
        self.revision += 1
        saved = {**deepcopy(body), "_etag": str(self.revision)}
        self.items[saved["id"]] = saved
        return self._response(saved)

    create_item = upsert_item

    def replace_item(self, item, body, **kwargs):
        return self.upsert_item(body)

    def patch_item(
        self, item, partition_key, patch_operations, *, filter_predicate=None,
        etag=None, match_condition=None, no_response=False, **kwargs,
    ):
        if item not in self.items:
            raise CosmosResourceNotFoundError(status_code=404)
        current = self.items[item]
        if match_condition is not None:
            if match_condition is not MatchConditions.IfNotModified:
                raise AssertionError(f"Unsupported patch match condition: {match_condition}")
            if etag != current.get("_etag"):
                raise CosmosAccessConditionFailedError(status_code=412, message="Precondition failed.")
        saved = self.upsert_item(patch_document(current, patch_operations, filter_predicate=filter_predicate))
        return self._response({}) if no_response else saved

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
