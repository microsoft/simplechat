#!/usr/bin/env python3
# test_map_server_storage_tiles_events.py
"""
Functional test for the map server's Cosmos DB store, tile proxy and live change events.
Version: 0.261.254
Implemented in: 0.261.254

This test ensures each map write reaches Cosmos DB as one ETag-conditioned transactional batch with parameterized
queries, that map tiles are fetched only with the server's own credentials and cached, and that the event stream
replays changes in order to callers that can read the map.
"""

import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import httpx
from azure.core.credentials import AccessToken
from azure.cosmos import exceptions as cosmos_exceptions

from test_support.map_server_harness import actor_headers, create_map, make_client, make_settings

from mapserver.cosmos_store import CosmosMapStore
from mapserver.store import ConflictError, StoreError
from mapserver.tiles import TileService

PNG_BYTES = b"\x89PNG\r\n\x1a\nfake-tile"


class FakeContainer:
    def __init__(self):
        self.batches = []
        self.queries = []
        self.items = {}
        self.query_results = []
        self.batch_error = None
        self.upserts = []
        self.deletes = []

    async def execute_item_batch(self, batch_operations, partition_key):
        self.batches.append((list(batch_operations), partition_key))
        if self.batch_error is not None:
            raise self.batch_error
        return [{"statusCode": 200, "eTag": '"etag-2"', "resourceBody": {"_etag": '"etag-2"'}}]

    async def read_item(self, item, partition_key):
        if (item, partition_key) not in self.items:
            raise cosmos_exceptions.CosmosResourceNotFoundError(status_code=404, message="Not found")
        return dict(self.items[(item, partition_key)])

    def query_items(self, query, parameters, partition_key):
        self.queries.append((query, parameters, partition_key))
        results = list(self.query_results)

        async def iterate():
            for result in results:
                yield result

        return iterate()

    async def upsert_item(self, body):
        self.upserts.append(body)

    async def delete_item(self, item, partition_key):
        self.deletes.append((item, partition_key))
        raise cosmos_exceptions.CosmosResourceNotFoundError(status_code=404, message="Not found")


class FakeDatabase:
    def __init__(self, containers):
        self.containers = containers

    def get_container_client(self, name):
        return self.containers[name]


class FakeCosmosClient:
    def __init__(self):
        self.containers = {"maps": FakeContainer(), "map_links": FakeContainer()}
        self.closed = False

    def get_database_client(self, name):
        assert name == "mapserver"
        return FakeDatabase(self.containers)

    async def close(self):
        self.closed = True


def make_store():
    client = FakeCosmosClient()
    return CosmosMapStore(client, "mapserver", "maps", "map_links"), client.containers["maps"], client.containers["map_links"], client


def test_cosmos_commit_is_one_etag_conditioned_batch():
    print("Checking Cosmos batches...")
    store, maps, _, client = make_store()
    map_id = "map-0123456789abcdef0123"
    map_doc = {"id": map_id, "map_id": map_id, "type": "map", "version": 3}
    feature = {"id": "F-0001", "map_id": map_id, "type": "feature"}
    revision = {"id": "F-0002@r1", "map_id": map_id, "type": "feature_rev"}
    replaced = {"id": "F-0002", "map_id": map_id, "type": "feature"}

    etag = asyncio.run(store.commit(map_id, map_doc, '"etag-1"', [revision, feature], [replaced]))
    operations, partition_key = maps.batches[-1]
    assert etag == '"etag-2"' and partition_key == map_id
    assert operations[0] == ("replace", (map_id, map_doc), {"if_match_etag": '"etag-1"'})
    assert operations[1:] == [("create", (revision,)), ("create", (feature,)), ("replace", ("F-0002", replaced))]

    asyncio.run(store.commit(map_id, map_doc, None, [], []))
    assert maps.batches[-1][0] == [("create", (map_doc,))]

    for status, expected in ((412, ConflictError), (409, ConflictError), (500, StoreError)):
        maps.batch_error = cosmos_exceptions.CosmosBatchOperationError(
            error_index=0, headers={}, status_code=status, message="failed",
        )
        try:
            asyncio.run(store.commit(map_id, map_doc, '"etag-1"', [], []))
            raise AssertionError(f"Status {status} should have raised.")
        except expected:
            pass
    maps.batch_error = None

    calls = len(maps.batches)
    try:
        asyncio.run(store.commit(map_id, map_doc, '"etag-1"', [feature] * 100, []))
        raise AssertionError("An oversized batch should be refused.")
    except StoreError:
        pass
    assert len(maps.batches) == calls

    asyncio.run(store.close())
    assert client.closed
    print("  Cosmos batches passed.")
    return True


def test_cosmos_reads_and_queries_are_partitioned_and_parameterized():
    print("Checking Cosmos reads...")
    store, maps, links, _ = make_store()
    map_id = "map-0123456789abcdef0123"
    maps.items[(map_id, map_id)] = {"id": map_id, "type": "map", "_etag": '"e1"', "_rid": "r", "_ts": 1, "_self": "s"}
    doc, etag = asyncio.run(store.read_map(map_id))
    assert etag == '"e1"' and doc == {"id": map_id, "type": "map"}
    assert asyncio.run(store.read_map("map-ffffffffffffffffffff")) is None
    maps.items[("map-1", "map-1")] = {"id": "map-1", "type": "feature", "_etag": '"e"'}
    assert asyncio.run(store.read_map("map-1")) is None

    hostile_key = "point|records|R-1' OR 1=1 --"
    asyncio.run(store.query_features(map_id, dup_keys=[hostile_key]))
    query, parameters, partition_key = maps.queries[-1]
    assert hostile_key not in query and parameters == [{"name": "@keys", "value": [hostile_key]}] and partition_key == map_id
    assert asyncio.run(store.query_features(map_id, dup_keys=[])) == []

    asyncio.run(store.query_changes(map_id, 5, 50))
    query, parameters, _ = maps.queries[-1]
    assert "SELECT TOP 50 " in query and parameters == [{"name": "@since", "value": 5}]

    asyncio.run(store.query_feature_revisions(map_id, ["F-0001"], 4))
    _, parameters, _ = maps.queries[-1]
    assert {"name": "@version", "value": 4} in parameters

    asyncio.run(store.delete_link("conversation:c1", map_id))
    assert links.deletes == [(map_id, "conversation:c1")]
    asyncio.run(store.list_links("group:g1"))
    assert links.queries[-1][2] == "group:g1"
    print("  Cosmos reads passed.")
    return True


class TileUpstream:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def handler(self, request):
        self.requests.append(request)
        result = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(result, Exception):
            raise result
        return result


class FakeCredential:
    def __init__(self):
        self.calls = 0

    async def get_token(self, *scopes):
        self.calls += 1
        assert scopes == ("https://atlas.microsoft.com/.default",)
        return AccessToken("maps-token", 4102444800)


def tile_client(settings, upstream, credential=None):
    tiles = TileService(settings, http_client=httpx.AsyncClient(transport=httpx.MockTransport(upstream.handler)), credential=credential)
    return make_client(settings, tile_service=tiles)


def test_tiles_use_the_servers_own_credentials_and_are_cached():
    print("Checking tiles...")
    headers = {"Authorization": actor_headers()["Authorization"]}
    with make_client() as client:
        unconfigured = client.get("/v1/tiles/microsoft.base.road/1/0/0", headers=headers)
        assert unconfigured.status_code == 404 and unconfigured.json()["error"] == "tiles_unavailable"
        assert client.get("/v1/tiles/microsoft.base.road/1/0/0").status_code == 401

    image = httpx.Response(200, content=PNG_BYTES, headers={"content-type": "image/png"})
    upstream = TileUpstream([image])
    with tile_client(make_settings(azure_maps_key="maps-key"), upstream) as client:
        first = client.get("/v1/tiles/microsoft.base.road/3/2/1", headers=headers)
        second = client.get("/v1/tiles/microsoft.base.road/3/2/1", headers=headers)
        assert first.status_code == 200 and first.content == PNG_BYTES and second.content == PNG_BYTES
        assert first.headers["content-type"] == "image/png" and first.headers["cache-control"] == "private, max-age=3600"
        assert len(upstream.requests) == 1
        request = upstream.requests[0]
        assert request.headers["subscription-key"] == "maps-key"
        assert request.url.path == "/map/tile"
        assert request.url.params["tilesetId"] == "microsoft.base.road" and request.url.params["zoom"] == "3"
        for path in ("/v1/tiles/microsoft.base.road/1/2/0", "/v1/tiles/bad$tileset/1/0/0", "/v1/tiles/microsoft.base.road/23/0/0"):
            response = client.get(path, headers=headers)
            assert response.status_code == 400 and response.json()["error"] == "invalid_tile", path

    credential = FakeCredential()
    upstream = TileUpstream([image])
    with tile_client(make_settings(azure_maps_client_id="maps-account-id"), upstream, credential) as client:
        first = client.get("/v1/tiles/microsoft.base.road/1/0/0", headers=headers)
        second = client.get("/v1/tiles/microsoft.base.road/1/1/0", headers=headers)
        assert first.status_code == 200 and second.status_code == 200
        assert credential.calls == 1
        assert upstream.requests[0].headers["authorization"] == "Bearer maps-token"
        assert upstream.requests[0].headers["x-ms-client-id"] == "maps-account-id"

    for failure in (
        httpx.Response(200, content=b"<html>", headers={"content-type": "text/html"}),
        httpx.Response(403, content=b"denied"),
        httpx.ConnectError("unreachable"),
    ):
        with tile_client(make_settings(azure_maps_key="maps-key"), TileUpstream([failure])) as client:
            response = client.get("/v1/tiles/microsoft.base.road/1/0/0", headers=headers)
            assert response.status_code == 502 and response.json()["error"] == "tile_upstream_error"
            assert "maps-key" not in response.text
    print("  Tiles passed.")
    return True


def read_events(client, map_id, headers, **params):
    with client.stream("GET", f"/v1/maps/{map_id}/events", params=params, headers=headers) as response:
        assert response.status_code == 200, response.read()
        assert response.headers["content-type"].startswith("text/event-stream")
        return "".join(response.iter_text())


def test_event_stream_replays_changes_in_order_and_checks_access():
    print("Checking live events...")
    with make_client() as client:
        headers = actor_headers()
        map_id = create_map(client, headers)
        client.post(f"/v1/maps/{map_id}/features:batch", json={"features": [{"latitude": 1, "longitude": 1, "label": "A"}]}, headers=headers)
        client.post(f"/v1/maps/{map_id}/phases", json={"name": "Follow-up"}, headers=headers)

        body = read_events(client, map_id, headers, since_version=1)
        assert body.startswith("retry: 5000")
        assert "id: 2\nevent: change\n" in body and "id: 3\nevent: change\n" in body
        assert body.index("id: 2\n") < body.index("id: 3\n")
        assert '"action":"add_features"' in body and '"action":"start_phase"' in body
        assert "event: end" in body

        resumed = read_events(client, map_id, {**headers, "Last-Event-ID": "2"})
        assert "id: 2\n" not in resumed and "id: 3\n" in resumed
        caught_up = read_events(client, map_id, headers)
        assert "event: change" not in caught_up

        reader = actor_headers(access="read")
        assert "id: 3\n" in read_events(client, map_id, reader, since_version=2)
        assert client.get(f"/v1/maps/{map_id}/events", headers=actor_headers(scope="group:team-2")).status_code == 404
    print("  Live events passed.")
    return True


if __name__ == "__main__":
    tests = [
        test_cosmos_commit_is_one_etag_conditioned_batch,
        test_cosmos_reads_and_queries_are_partitioned_and_parameterized,
        test_tiles_use_the_servers_own_credentials_and_are_cached,
        test_event_stream_replays_changes_in_order_and_checks_access,
    ]
    results = []
    for test in tests:
        try:
            results.append(bool(test()))
        except Exception as exc:
            import traceback

            print(f"Test {test.__name__} failed: {exc}")
            traceback.print_exc()
            results.append(False)
    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
