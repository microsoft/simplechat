# test_group_document_sdk_conditions.py
"""
Verify conditional management writes through the real SDK HTTP pipelines.

Version: 0.261.129
Implemented in: 0.261.129

Initially verified with azure-cosmos 4.9.0 and azure-storage-blob 12.19.0.
All HTTP is captured by a local transport; socket connections are prohibited.
This pins serialization and precondition-failure propagation, not live-service
execution or the application's separate authorization/business rules.
"""

import base64
import json
import socket
from urllib.parse import parse_qs, urlsplit

import pytest
from azure.core import MatchConditions
from azure.core.exceptions import ResourceModifiedError
from azure.core.pipeline.transport import HttpResponse, HttpTransport
from azure.cosmos import CosmosClient
from azure.cosmos.exceptions import CosmosHttpResponseError
from azure.storage.blob import BlobClient
from requests.structures import CaseInsensitiveDict


class WireResponse(HttpResponse):
    def __init__(self, request, body, status=200, headers=None):
        super().__init__(request, None)
        self.status_code = status
        self.reason = "OK" if status == 200 else "Precondition Failed"
        self.content_type = "application/json"
        self.headers = CaseInsensitiveDict({
            "content-type": self.content_type,
            "etag": '"result-etag"',
            "last-modified": "Mon, 21 Sep 2026 12:00:00 GMT",
            "x-ms-activity-id": "fixture-activity",
            "x-ms-request-charge": "1",
            **(headers or {}),
        })
        self._body = json.dumps(body).encode("utf-8") if body is not None else b""

    def body(self):
        return self._body

    def text(self, encoding=None):
        return self._body.decode(encoding or "utf-8")


class ConditionalWireTransport(HttpTransport):
    def __init__(self, *, stale=False):
        self.stale = stale
        self.requests = []

    def open(self):
        pass

    def close(self):
        pass

    def __exit__(self, *args):
        self.close()

    def send(self, request, **kwargs):
        self.requests.append(request)
        url = urlsplit(request.url)
        path = url.path.rstrip("/")
        if url.hostname == "fixture.documents.azure.com":
            if request.method == "GET" and not path:
                return WireResponse(request, {
                    "id": "fixture", "_rid": "fixture",
                    "consistencyPolicy": {"defaultConsistencyLevel": "Session"},
                    "writableLocations": [], "readableLocations": [],
                    "enableMultipleWriteLocations": False,
                })
            if request.method == "GET" and path == "/dbs/fixture/colls/groups":
                return WireResponse(request, {
                    "id": "groups", "_rid": "ZmFrZQ==",
                    "partitionKey": {"paths": ["/id"], "kind": "Hash", "version": 2},
                })
            if request.method == "PATCH" and path == "/dbs/fixture/colls/groups/docs/group-a":
                if self.stale:
                    return WireResponse(request, {"code": "PreconditionFailed", "message": "Fixture condition failed."}, 412)
                return WireResponse(request, {"id": "group-a", "_etag": '"result-etag"', "tag_definitions": {}})
        if url.hostname == "fixture.blob.core.windows.net" and request.method == "PUT":
            if path == "/documents/source.txt" and parse_qs(url.query).get("comp") == ["metadata"]:
                return WireResponse(
                    request, None, 412 if self.stale else 200,
                    {"x-ms-error-code": "ConditionNotMet"} if self.stale else None,
                )
        raise AssertionError(f"Unexpected SDK request: {request.method} {request.url}")


@pytest.fixture(autouse=True)
def prohibit_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("SDK condition tests must never open a network connection.")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "create_connection", denied)


@pytest.mark.parametrize("stale", [False, True])
def test_cosmos_patch_serializes_the_etag_predicate_and_propagates_conflicts(stale):
    transport = ConditionalWireTransport(stale=stale)
    fixture_key = base64.b64encode(b"fixture-only-not-an-account-key").decode("ascii")
    etag = '"fixture-etag"'
    predicate = f"FROM c WHERE c._etag = {json.dumps(etag)}"
    operations = [{"op": "set", "path": "/tag_definitions/a~1b~0c", "value": {"color": "#0078d4"}}]
    with CosmosClient(
        "https://fixture.documents.azure.com", credential=fixture_key,
        transport=transport, enable_endpoint_discovery=False,
    ) as client:
        container = client.get_database_client("fixture").get_container_client("groups")
        if stale:
            with pytest.raises(CosmosHttpResponseError) as failure:
                container.patch_item(
                    item="group-a", partition_key="group-a",
                    patch_operations=operations, filter_predicate=predicate,
                )
            assert failure.value.status_code == 412
        else:
            result = container.patch_item(
                item="group-a", partition_key="group-a",
                patch_operations=operations, filter_predicate=predicate,
            )
            assert result["id"] == "group-a"

    patches = [request for request in transport.requests if request.method == "PATCH"]
    assert len(patches) == 1
    body = json.loads(patches[0].body)
    assert body == {"operations": operations, "condition": predicate}
    assert json.loads(patches[0].headers["x-ms-documentdb-partitionkey"]) == ["group-a"]


@pytest.mark.parametrize("stale", [False, True])
def test_blob_metadata_serializes_if_match_and_propagates_conflicts(stale):
    transport = ConditionalWireTransport(stale=stale)
    etag = '"fixture-blob-etag"'
    with BlobClient(
        account_url="https://fixture.blob.core.windows.net",
        container_name="documents", blob_name="source.txt",
        credential=None, transport=transport,
    ) as blob:
        if stale:
            with pytest.raises(ResourceModifiedError) as failure:
                blob.set_blob_metadata(
                    {"tags": "finance"}, etag=etag, match_condition=MatchConditions.IfNotModified,
                )
            assert failure.value.status_code == 412
        else:
            result = blob.set_blob_metadata(
                {"tags": "finance"}, etag=etag, match_condition=MatchConditions.IfNotModified,
            )
            assert result["etag"] == '"result-etag"'

    assert len(transport.requests) == 1
    request = transport.requests[0]
    assert request.headers["If-Match"] == etag
    assert request.headers["x-ms-meta-tags"] == "finance"
    assert parse_qs(urlsplit(request.url).query)["comp"] == ["metadata"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
