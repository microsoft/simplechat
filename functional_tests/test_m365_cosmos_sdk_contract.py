# test_m365_cosmos_sdk_contract.py
"""
Functional regressions for Microsoft 365 Cosmos replacement calls.
Version: 0.261.031
Implemented in: 0.261.031

Uses the installed Cosmos SDK and RequestsTransport with an autospecced HTTP
session. Only remote responses are faked; the real SDK derives partition routing
and conditional headers. Network access is blocked throughout each SDK test.
"""

import ast
import base64
from contextlib import ExitStack
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import socket
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import unquote, urlsplit

from azure.core import MatchConditions
from azure.core.pipeline.transport import RequestsTransport
from azure.cosmos import CosmosClient
from azure.cosmos.exceptions import CosmosHttpResponseError, CosmosResourceNotFoundError
from flask import Flask, g
import pytest
import requests


APP = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP))
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Standalone tests initialize repository paths before importing application code.
from functions_m365_execution import M365ExecutionContext, m365_execution_context
from test_m365_settings_ingress import writer


class CosmosHttpResponses:
    def __init__(self, partition_field):
        self.partition_field = partition_field
        self.records = {}
        self.calls = []
        self.revision = 0

    def seed(self, body):
        self.revision += 1
        saved = {
            **deepcopy(body), "_etag": f'"revision-{self.revision}"',
            "_rid": "offline-item", "_self": f"dbs/testdb/colls/records/docs/{body['id']}/",
        }
        self.records[(body[self.partition_field], body["id"])] = saved
        return deepcopy(saved)

    def request(self, method, url, *, data=None, headers=None, **kwargs):
        path = unquote(urlsplit(url).path.rstrip("/"))
        headers = requests.structures.CaseInsensitiveDict(headers or {})
        self.calls.append((method, path, headers))
        status = 200
        if method == "GET" and not path:
            locations = [{"name": "offline", "databaseAccountEndpoint": "https://cosmos.invalid/"}]
            payload = {
                "id": "offline", "_rid": "offline", "writableLocations": locations,
                "readableLocations": locations, "userConsistencyPolicy": {"defaultConsistencyLevel": "Session"},
            }
        elif method == "GET" and path == "/dbs/testdb/colls/records":
            payload = {
                "id": "records", "_rid": "offline-container",
                "partitionKey": {"paths": [f"/{self.partition_field}"], "kind": "Hash", "version": 2},
            }
        elif "/docs/" in path and method in {"GET", "PUT"}:
            partition = json.loads(headers["x-ms-documentdb-partitionkey"])[0]
            item_id = path.rsplit("/", 1)[-1]
            existing = self.records.get((partition, item_id))
            if existing is None:
                status, payload = 404, {"code": "NotFound", "message": "The scoped item does not exist."}
            elif method == "GET":
                payload = deepcopy(existing)
            elif headers.get("If-Match") != existing["_etag"]:
                status, payload = 412, {"code": "PreconditionFailed", "message": "The item changed."}
            else:
                body = json.loads(data)
                if body.get(self.partition_field) != partition or body.get("id") != item_id:
                    raise AssertionError("Replacement changed the authorized partition or item ID.")
                payload = self.seed(body)
        else:
            raise AssertionError(f"Unexpected Cosmos HTTP request: {method} {path}")
        response = requests.Response()
        response.status_code = status
        response.headers = {
            "content-type": "application/json", "etag": payload.get("_etag", ""),
            "x-ms-request-charge": "1", "x-ms-activity-id": "offline",
        }
        response._content = json.dumps(payload).encode("utf-8")
        response._content_consumed = True
        response.raw = SimpleNamespace(enforce_content_length=True)
        response.request = requests.Request(method, url).prepare()
        return response


@pytest.fixture
def cosmos_factory():
    def no_network(*args, **kwargs):
        raise AssertionError("SDK contract tests must not contact Azure or any other network service.")

    with ExitStack() as stack:
        stack.enter_context(patch.object(socket.socket, "connect", no_network))

        def create(partition_field):
            http = CosmosHttpResponses(partition_field)
            session = stack.enter_context(requests.Session())
            stack.enter_context(patch.object(session, "request", autospec=True, side_effect=http.request))
            client = stack.enter_context(CosmosClient(
                "https://cosmos.invalid",
                credential=base64.b64encode(b"offline-test-key").decode("ascii"),
                enable_endpoint_discovery=False,
                transport=RequestsTransport(session=session, session_owner=False),
            ))
            container = client.get_database_client("testdb").get_container_client("records")
            return http, container

        yield create


def load_runtime(filename, container):
    dependencies = {}
    for name, values in {
        "config": {
            "CLIENTS": {}, "TENANT_ID": "tenant",
            "cosmos_conversations_container": container, "cosmos_messages_container": Mock(),
            "cosmos_m365_execution_runs_container": container,
            "build_enhanced_citations_blob_service_client": Mock(),
        },
        "functions_appinsights": {"log_event": Mock()},
        "functions_settings": {"get_settings": lambda: {}},
        "functions_collaboration": {
            "build_conversation_participation_context": Mock(return_value={}),
            "assert_user_can_participate_in_collaboration_conversation": Mock(),
            "get_collaboration_conversation": Mock(),
        },
    }.items():
        module = ModuleType(name)
        module.__dict__.update(values)
        dependencies[name] = module
    spec = importlib.util.spec_from_file_location(f"test_sdk_{filename}", APP / f"{filename}.py")
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, dependencies):
        spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("partition_field", ["id", "user_id", "group_id"])
def test_real_sdk_routes_replacements_from_body_and_preserves_etag(cosmos_factory, partition_field):
    http, container = cosmos_factory(partition_field)
    original = http.seed({"id": "record", "user_id": "owner", "group_id": "subject", "status": "running"})
    updated = container.replace_item(
        "record", body={**original, "status": "completed"},
        etag=original["_etag"], match_condition=MatchConditions.IfNotModified,
    )
    method, _path, headers = http.calls[-1]
    assert method == "PUT"
    assert json.loads(headers["x-ms-documentdb-partitionkey"]) == [original[partition_field]]
    assert headers["If-Match"] == original["_etag"]
    assert updated["status"] == "completed"
    assert updated["_etag"] != original["_etag"]
    with pytest.raises(CosmosHttpResponseError) as raised:
        container.replace_item(
            "record", body={**original, "status": "stale"},
            etag=original["_etag"], match_condition=MatchConditions.IfNotModified,
        )
    assert raised.value.status_code == 412
    assert http.records[(original[partition_field], "record")]["status"] == "completed"


def test_real_sdk_rejects_the_unsupported_partition_keyword(cosmos_factory):
    http, container = cosmos_factory("user_id")
    original = http.seed({"id": "record", "user_id": "owner"})
    with pytest.raises(TypeError, match="partition_key"):
        container.replace_item(
            "record", body=original, partition_key="owner",
            etag=original["_etag"], match_condition=MatchConditions.IfNotModified,
        )
    assert not any(method == "PUT" for method, _path, _headers in http.calls)


def test_other_partition_cannot_replace_an_existing_item(cosmos_factory):
    http, container = cosmos_factory("user_id")
    original = http.seed({"id": "record", "user_id": "owner"})
    with pytest.raises(CosmosResourceNotFoundError):
        container.replace_item(
            "record", body={**original, "user_id": "other-user"},
            etag=original["_etag"], match_condition=MatchConditions.IfNotModified,
        )
    assert http.records[("owner", "record")] == original


def test_application_replacements_do_not_forward_unsupported_partition_keywords():
    invalid = []
    for path in APP.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "replace_item"
                and any(keyword.arg == "partition_key" for keyword in node.keywords)
            ):
                invalid.append(f"{path.name}:{node.lineno}")
    assert invalid == [], f"Cosmos replace_item derives its partition from body: {invalid}"


def test_conversation_memory_inventory_write_uses_real_sdk(cosmos_factory):
    http, container = cosmos_factory("id")
    http.seed({"id": "conversation", "user_id": "owner"})
    runtime = load_runtime("conversation_memory_runtime", container)
    store = object()
    execution = M365ExecutionContext("owner", "owner", "tenant", conversation_id="conversation", request_id="request")
    with patch.object(runtime, "get_conversation_memory_store", return_value=store):
        with m365_execution_context(execution):
            result, memory_context = runtime.resolve_m365_memory(execution)
    assert result is store
    assert memory_context.conversation_id == "conversation"
    assert http.records[("conversation", "conversation")]["m365_working_memory"] is True


@pytest.mark.parametrize("success", [False, True])
def test_request_pause_and_completion_writes_use_real_sdk(cosmos_factory, success):
    http, container = cosmos_factory("user_id")
    original = http.seed({
        "id": "request", "user_id": "owner", "actor_user_id": "owner",
        "conversation_id": "conversation", "status": "running",
    })
    runtime = load_runtime("functions_m365_runtime", container)
    execution = M365ExecutionContext("owner", "owner", "tenant", conversation_id="conversation", request_id="request")
    waiting = {**original, "status": "awaiting_approval", "payload": {"message": "saved request"}}
    runtime._save_m365_wait_record(waiting, original, execution)
    assert http.records[("owner", "request")]["status"] == "awaiting_approval"
    with Flask(__name__).test_request_context(), m365_execution_context(execution):
        g.m365_has_pending_record = True
        runtime.complete_m365_request(success=success)
    saved = http.records[("owner", "request")]
    assert saved["status"] == ("completed" if success else "failed")
    assert "payload" not in saved
    assert saved["user_id"] == "owner"


def test_existing_action_settings_save_uses_real_sdk(cosmos_factory):
    http, container = cosmos_factory("id")
    http.seed({
        "id": "owner", "settings": {
            "plugins": [{"id": "old", "type": "msgraph"}],
            "agents": [{"id": "agent", "name": "Agent"}], "selected_agent": {"id": "agent"},
        },
    })
    update, events = writer(container)
    saved = update("owner", {"theme": "dark"})
    assert saved is True, events
    assert http.records[("owner", "owner")]["settings"]["theme"] == "dark"
    assert http.records[("owner", "owner")]["settings"]["plugins"] == [{"id": "old", "type": "msgraph"}]


if __name__ == "__main__":
    sys.exit(pytest.main([str(Path(__file__).resolve())]))
