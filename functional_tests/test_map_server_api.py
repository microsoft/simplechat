#!/usr/bin/env python3
# test_map_server_api.py
"""
Functional test for the shared map server API.
Version: 0.261.254
Implemented in: 0.261.254

This test ensures the map server only serves callers holding the map server role, keeps every map inside the
scope that owns it, records each change as one new version tagged with its phase, and can show any earlier version.
"""

import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from cryptography.hazmat.primitives.asymmetric import rsa

from test_support.map_server_harness import (
    ISSUER_V2,
    actor_headers,
    create_map,
    make_client,
    make_settings,
    make_token,
)
from test_support.versioning import assert_app_version_at_least

from fastapi.testclient import TestClient
from mapserver.app import create_app
from mapserver.auth import Actor, encode_actor
from mapserver.engine import MapEngine
from mapserver.models import AddFeaturesRequest, CreateMapRequest
from mapserver.settings import Settings, SettingsError
from mapserver.store import ConflictError, InMemoryMapStore, StoreError

POINT = {
    "latitude": 40.7393,
    "longitude": -73.9368,
    "label": "Storage facility gate",
    "category": "Location",
    "description": "Entry recorded by the gate log.",
    "observed_at": "2026-10-04T06:36:00-04:00",
    "source": {"system": "records", "record_id": "R-1"},
    "image_url": "https://example.org/still.png",
    "image_caption": "Gate camera",
    "fields": {"Unit": "214"},
}
PATH = {"kind": "path", "coordinates": [[-73.95, 40.73], [-73.94, 40.74]], "label": "Route", "line_width": 30}
AREA = {
    "geometry": {"type": "Polygon", "coordinates": [[[-73.9, 40.7], [-73.8, 40.7], [-73.8, 40.8]]]},
    "label": "Search area",
}


def add(client, map_id, headers, features, **body):
    return client.post(f"/v1/maps/{map_id}/features:batch", json={"features": features, **body}, headers=headers)


def features_of(client, map_id, headers, **params):
    response = client.get(f"/v1/maps/{map_id}/features", params=params, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_app_version_includes_the_map_server():
    assert_app_version_at_least("0.261.254")
    return True


def test_callers_need_a_valid_token_with_the_map_server_role():
    print("Checking caller tokens...")
    with make_client() as client:
        assert client.get("/healthz").status_code == 200
        actor_only = {"X-Map-Actor": actor_headers()["X-Map-Actor"]}
        assert client.get("/v1/maps", headers=actor_only).status_code == 401
        rejected_tokens = [
            make_token(audience="api://another-api"),
            make_token(issuer="https://sts.windows.net/another-tenant/"),
            make_token(expires_in=-3600),
            make_token(key=rsa.generate_private_key(public_exponent=65537, key_size=2048)),
        ]
        for token in rejected_tokens:
            response = client.get("/v1/maps", headers=actor_headers(token=token))
            assert response.status_code == 401, response.text
            assert response.json()["error"] == "unauthorized"
        no_role = client.get("/v1/maps", headers=actor_headers(token=make_token(roles=None)))
        assert no_role.status_code == 403 and no_role.json()["error"] == "caller_not_allowed"
        assert client.get("/v1/maps", headers=actor_headers(token=make_token(issuer=ISSUER_V2))).status_code == 200

    allowlisted_id = "22222222-2222-2222-2222-222222222222"
    with make_client(make_settings(allowed_caller_ids=frozenset({allowlisted_id}))) as client:
        token = make_token(roles=None, object_id=allowlisted_id)
        assert client.get("/v1/maps", headers=actor_headers(token=token)).status_code == 200
    print("  Caller tokens passed.")
    return True


def test_actor_context_is_required_and_validated():
    print("Checking the actor context...")
    with make_client() as client:
        token_only = {"Authorization": f"Bearer {make_token()}"}
        response = client.get("/v1/maps", headers=token_only)
        assert response.status_code == 400 and response.json()["error"] == "actor_required"
        for headers in (
            {**token_only, "X-Map-Actor": "not base64!"},
            actor_headers(scope="tenant:everything"),
            actor_headers(access="admin"),
            actor_headers(role="admin"),
            actor_headers(user_id="has spaces"),
        ):
            response = client.get("/v1/maps", headers=headers)
            assert response.status_code == 400 and response.json()["error"] == "invalid_actor", response.text
        # The actor context is only read after the token is checked.
        assert client.get("/v1/maps", headers={"X-Map-Actor": "garbage"}).status_code == 401
    print("  Actor context passed.")
    return True


def test_maps_stay_inside_the_scope_that_owns_them():
    print("Checking scope isolation...")
    with make_client() as client:
        writer = actor_headers(scope="group:team-1")
        map_id = create_map(client, writer, conversation_id="conv-1")
        view = client.get(f"/v1/maps/{map_id}", headers=writer).json()
        assert view["owner_scope"] == "group:team-1" and view["version"] == 1
        assert view["current_phase_id"] == "P1" and view["links"] == ["conv-1"]

        other_scope = actor_headers(scope="group:team-2")
        for path in ("", "/snapshot", "/features", "/changes"):
            response = client.get(f"/v1/maps/{map_id}{path}", headers=other_scope)
            assert response.status_code == 404 and response.json()["error"] == "map_not_found", path
        foreign_write = add(client, map_id, other_scope, [POINT])
        assert foreign_write.status_code == 404

        reader = actor_headers(scope="group:team-1", access="read")
        assert client.get(f"/v1/maps/{map_id}", headers=reader).status_code == 200
        refused = add(client, map_id, reader, [POINT])
        assert refused.status_code == 403 and refused.json()["error"] == "read_only"
        refused_create = client.post("/v1/maps", json={"title": "Not allowed"}, headers=reader)
        assert refused_create.status_code == 403

        other_map = create_map(client, other_scope, conversation_id="conv-1")
        assert [item["map_id"] for item in client.get("/v1/maps", headers=writer).json()["items"]] == [map_id]
        by_conversation = client.get("/v1/maps", params={"conversation_id": "conv-1"}, headers=writer).json()["items"]
        assert [item["map_id"] for item in by_conversation] == [map_id]
        other_listing = client.get("/v1/maps", params={"conversation_id": "conv-1"}, headers=other_scope).json()["items"]
        assert [item["map_id"] for item in other_listing] == [other_map]
        assert client.get("/v1/maps/not-a-map", headers=writer).status_code == 404
    print("  Scope isolation passed.")
    return True


def test_agents_add_points_paths_and_areas_with_limits_enforced():
    print("Checking feature validation...")
    with make_client() as client:
        headers = actor_headers(agent={"id": "agent-1", "name": "Field analyst"}, conversation_id="conv-1", message_id="msg-1")
        map_id = create_map(client, headers)
        insecure = {**POINT, "label": "Insecure photo", "source": {"record_id": "R-2"}, "image_url": "http://example.org/x.png"}
        response = add(client, map_id, headers, [POINT, PATH, AREA, insecure])
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["version"] == 2 and result["change_id"] == "C-000002"
        assert [item["id"] for item in result["added"]] == ["F-0001", "F-0002", "F-0003", "F-0004"]
        assert result["images_dropped"] == 1
        assert result["counts"] == {"active": 4, "retracted": 0, "point": 2, "path": 1, "area": 1}

        point, path, area, no_photo = features_of(client, map_id, headers)["items"]
        assert point["geometry"] == {"type": "Point", "coordinates": [-73.9368, 40.7393]}
        assert point["category"] == "location"
        assert point["observed_at"] == "2026-10-04T06:36:00-04:00"
        assert point["media"] == {"image_url": "https://example.org/still.png", "caption": "Gate camera"}
        assert point["fields"] == [{"label": "Unit", "value": "214"}]
        assert point["phase_id"] == "P1" and point["phase_name"] == "Phase 1"
        assert point["created_by"]["agent"]["name"] == "Field analyst" and point["created_by"]["message_id"] == "msg-1"
        assert path["style"]["line_width"] == 12
        ring = area["geometry"]["coordinates"][0]
        assert ring[0] == ring[-1] and len(ring) == 4
        assert no_photo["media"] is None

        for bad, expected in (
            ({"latitude": 95, "longitude": 0, "label": "x"}, "out of range"),
            ({"latitude": 1, "longitude": 1}, "needs a label"),
            ({"coordinates": [[0, 0], [1, 1]], "label": "x"}, "kind"),
            ({"kind": "path", "coordinates": [[0, 0]], "label": "x"}, "at least two"),
            ({"latitude": "nan", "longitude": 1, "label": "x"}, "finite"),
            ({"latitude": 1, "longitude": 1, "label": "x", "observed_at": "yesterday"}, "ISO 8601"),
            ({"geometry": {"type": "MultiPoint", "coordinates": []}, "label": "x"}, "Point, LineString or Polygon"),
        ):
            response = add(client, map_id, headers, [bad])
            assert response.status_code == 400 and expected in response.json()["message"], (bad, response.text)
        assert client.get(f"/v1/maps/{map_id}", headers=headers).json()["version"] == 2

        too_many = [{"latitude": 1, "longitude": 1 + index * 0.001, "label": f"Point {index}"} for index in range(41)]
        response = add(client, map_id, headers, too_many)
        assert response.status_code == 400 and response.json()["error"] == "too_many_features"
    print("  Feature validation passed.")
    return True


def test_duplicate_source_records_are_skipped_or_updated():
    print("Checking duplicates...")
    with make_client() as client:
        headers = actor_headers()
        map_id = create_map(client, headers)
        first = add(client, map_id, headers, [POINT]).json()
        assert first["added"][0]["id"] == "F-0001"

        again = add(client, map_id, headers, [POINT]).json()
        assert again["unchanged"] is True and again["version"] == 2
        assert [item["id"] for item in again["skipped"]] == ["F-0001"]

        moved = add(client, map_id, headers, [{**POINT, "latitude": 40.75}], on_duplicate="update").json()
        assert moved["version"] == 3 and [item["id"] for item in moved["updated"]] == ["F-0001"]
        feature = features_of(client, map_id, headers)["items"][0]
        assert feature["geometry"]["coordinates"] == [-73.9368, 40.75]
        assert feature["revision"] == 2 and feature["created_version"] == 2 and feature["updated_version"] == 3

        same_record = [{**POINT, "label": "First", "source": {"record_id": "R-9"}}, {**POINT, "label": "Second", "source": {"record_id": "R-9"}}]
        merged = add(client, map_id, headers, same_record, on_duplicate="update").json()
        assert len(merged["added"]) == 1 and merged["added"][0]["label"] == "Second"
        assert features_of(client, map_id, headers)["total"] == 2
    print("  Duplicates passed.")
    return True


def test_phases_order_the_work_and_tag_every_feature():
    print("Checking phases...")
    with make_client() as client:
        headers = actor_headers()
        map_id = create_map(client, headers, first_phase_name="Initial enrichment")
        first = add(client, map_id, headers, [POINT]).json()
        assert first["phase"]["id"] == "P1"

        started = client.post(f"/v1/maps/{map_id}/phases", json={"name": "Follow-up", "description": "Second pass"}, headers=headers)
        assert started.status_code == 201, started.text
        assert started.json()["phase"]["id"] == "P2" and started.json()["phase"]["color"] == "#fd7e14"
        second = add(client, map_id, headers, [PATH]).json()
        assert second["phase"]["id"] == "P2"

        closed = add(client, map_id, headers, [AREA], phase_id="P1")
        assert closed.status_code == 409 and closed.json()["error"] == "phase_closed"
        unknown = add(client, map_id, headers, [AREA], phase_id="P9")
        assert unknown.status_code == 404
        renamed = client.patch(f"/v1/maps/{map_id}/phases/P1", json={"name": "Initial sweep"}, headers=headers)
        assert renamed.status_code == 200 and renamed.json()["phase"]["name"] == "Initial sweep"
        bad_color = client.post(f"/v1/maps/{map_id}/phases", json={"name": "Bad", "color": "javascript:red"}, headers=headers)
        assert bad_color.status_code == 400

        view = client.get(f"/v1/maps/{map_id}", headers=headers).json()
        assert view["current_phase_id"] == "P2"
        first, second = view["phases"]
        assert first["status"] == "closed" and first["closed_version"] == 3 and second["status"] == "open"
        point, path = features_of(client, map_id, headers)["items"]
        assert point["phase_id"] == "P1" and point["phase_name"] == "Initial sweep"
        assert path["phase_id"] == "P2"
        assert [item["id"] for item in features_of(client, map_id, headers, phase_id="P2")["items"]] == ["F-0002"]
    print("  Phases passed.")
    return True


def test_updates_and_retractions_keep_history_and_earlier_versions_can_be_shown():
    print("Checking history...")
    with make_client() as client:
        headers = actor_headers()
        map_id = create_map(client, headers)
        add(client, map_id, headers, [POINT, PATH])

        changes = {"label": "Gate (confirmed)", "latitude": 40.74, "longitude": -73.93}
        updated = client.patch(f"/v1/maps/{map_id}/features/F-0001", json={"changes": changes}, headers=headers)
        assert updated.status_code == 200, updated.text
        assert updated.json()["version"] == 3 and updated.json()["feature"]["revision"] == 2
        stale = client.patch(f"/v1/maps/{map_id}/features/F-0001", json={"changes": {"label": "x"}, "expected_revision": 1}, headers=headers)
        assert stale.status_code == 412 and stale.json()["error"] == "revision_mismatch"
        kind_change = client.patch(f"/v1/maps/{map_id}/features/F-0001", json={"changes": {"kind": "area"}}, headers=headers)
        assert kind_change.status_code == 400

        retracted = client.post(f"/v1/maps/{map_id}/features/F-0002:retract", json={"reason": "Wrong vehicle"}, headers=headers)
        assert retracted.status_code == 200 and retracted.json()["version"] == 4
        blank_reason = client.post(f"/v1/maps/{map_id}/features/F-0001:retract", json={"reason": "   "}, headers=headers)
        assert blank_reason.status_code == 400
        frozen = client.patch(f"/v1/maps/{map_id}/features/F-0002", json={"changes": {"label": "y"}}, headers=headers)
        assert frozen.status_code == 409 and frozen.json()["error"] == "feature_retracted"

        now = client.get(f"/v1/maps/{map_id}/snapshot", headers=headers).json()
        assert [(marker["label"], marker["latitude"]) for marker in now["markers"]] == [("Gate (confirmed)", 40.74)]
        assert now["paths"] == []
        before = client.get(f"/v1/maps/{map_id}/snapshot", params={"as_of_version": 2}, headers=headers).json()
        assert [(marker["label"], marker["latitude"]) for marker in before["markers"]] == [("Storage facility gate", 40.7393)]
        assert [path["id"] for path in before["paths"]] == ["F-0002"]
        assert before["as_of_version"] == 2 and before["version"] == 4 and "as of version 2" in before["summary"]
        middle = client.get(f"/v1/maps/{map_id}/snapshot", params={"as_of_version": 3}, headers=headers).json()
        assert middle["markers"][0]["label"] == "Gate (confirmed)" and len(middle["paths"]) == 1
        assert client.get(f"/v1/maps/{map_id}/snapshot", params={"as_of_version": 9}, headers=headers).status_code == 400

        gone = features_of(client, map_id, headers, status="retracted")["items"]
        assert [item["id"] for item in gone] == ["F-0002"] and gone[0]["retract_reason"] == "Wrong vehicle"
        assert features_of(client, map_id, headers, status="all")["total"] == 2
        same = client.patch(f"/v1/maps/{map_id}/features/F-0001", json={"changes": {"label": "Gate (confirmed)"}}, headers=headers)
        assert same.json()["unchanged"] is True and same.json()["version"] == 4
    print("  History passed.")
    return True


def test_snapshot_matches_the_inline_map_payload_the_chat_already_renders():
    print("Checking the snapshot shape...")
    with make_client() as client:
        headers = actor_headers()
        map_id = create_map(client, headers, basemap="microsoft.base.darkgrey")
        add(client, map_id, headers, [POINT, PATH, AREA])
        snapshot = client.get(f"/v1/maps/{map_id}/snapshot", headers=headers).json()
        for key in ("title", "summary", "tile_attribution", "markers", "paths", "areas", "view", "tileset_id"):
            assert key in snapshot, key
        assert snapshot["tileset_id"] == "microsoft.base.darkgrey" and snapshot["background_color"] == "#000000"
        marker = snapshot["markers"][0]
        for key in ("latitude", "longitude", "label", "description", "color", "image_url", "image_caption", "fields"):
            assert key in marker, key
        assert marker["color"] == "#0d6efd" and marker["phase_name"] == "Phase 1"
        assert {"coordinates", "stroke_color", "line_width", "label"} <= set(snapshot["paths"][0])
        area = snapshot["areas"][0]
        assert area["coordinates"][0] == area["coordinates"][-1]
        assert area["fill_color"] == "rgba(13, 110, 253, 0.20)"
        assert snapshot["view"]["fit_to_features"] is True and len(snapshot["view"]["center"]) == 2
        assert snapshot["summary"] == "1 place, 1 route and 1 area in 1 phase."
        assert snapshot["phases"][0]["feature_count"] == 3

        client.post(f"/v1/maps/{map_id}/phases", json={"name": "Follow-up"}, headers=headers)
        add(client, map_id, headers, [{"latitude": 40.8, "longitude": -73.9, "label": "Later sighting"}])
        only_follow_up = client.get(f"/v1/maps/{map_id}/snapshot", params={"phases": "P2"}, headers=headers).json()
        assert [item["label"] for item in only_follow_up["markers"]] == ["Later sighting"]
        assert only_follow_up["markers"][0]["color"] == "#fd7e14" and only_follow_up["paths"] == []
        assert client.get(f"/v1/maps/{map_id}/snapshot", params={"phases": "P2,<x>"}, headers=headers).status_code == 400

        empty_id = create_map(client, headers)
        empty = client.get(f"/v1/maps/{empty_id}/snapshot", headers=headers).json()
        assert empty["summary"] == "No features yet in 1 phase." and empty["view"]["zoom"] == 2
    print("  Snapshot shape passed.")
    return True


def test_feature_list_filters_and_pages():
    print("Checking feature filters...")
    with make_client() as client:
        headers = actor_headers()
        map_id = create_map(client, headers)
        points = [
            {"latitude": 40 + index * 0.01, "longitude": -74, "label": f"Point {index}", "category": "camera" if index % 2 else "plate"}
            for index in range(30)
        ]
        add(client, map_id, headers, points)
        first = features_of(client, map_id, headers, limit=10)
        assert len(first["items"]) == 10 and first["next_cursor"] == "10" and first["total"] == 30
        second = features_of(client, map_id, headers, limit=10, cursor=first["next_cursor"])
        assert [item["label"] for item in second["items"]][0] == "Point 10"
        assert features_of(client, map_id, headers, category="camera")["total"] == 15
        assert features_of(client, map_id, headers, bbox="-74.1,40.0,-73.9,40.05")["total"] == 6
        add(client, map_id, headers, [{"latitude": 41, "longitude": -74, "label": "Newest"}])
        assert [item["label"] for item in features_of(client, map_id, headers, since_version=2)["items"]] == ["Newest"]
        for params in ({"cursor": "abc"}, {"bbox": "1,2,3"}, {"status": "bogus"}, {"kind": "circle"}):
            response = client.get(f"/v1/maps/{map_id}/features", params=params, headers=headers)
            assert response.status_code == 400, params
    print("  Feature filters passed.")
    return True


def test_change_log_records_each_version_with_its_phase_and_actor():
    print("Checking the change log...")
    with make_client() as client:
        headers = actor_headers(agent={"name": "Field analyst"}, run_id="run-7")
        map_id = create_map(client, headers)
        add(client, map_id, headers, [POINT])
        client.post(f"/v1/maps/{map_id}/phases", json={"name": "Follow-up"}, headers=headers)
        client.post(f"/v1/maps/{map_id}/features/F-0001:retract", json={"reason": "Duplicate"}, headers=headers)

        log = client.get(f"/v1/maps/{map_id}/changes", headers=headers).json()
        assert [item["action"] for item in log["items"]] == ["create_map", "add_features", "start_phase", "retract_feature"]
        assert [item["version"] for item in log["items"]] == [1, 2, 3, 4]
        added = log["items"][1]
        assert added["added"] == ["F-0001"] and added["labels"] == ["Storage facility gate"] and added["phase_id"] == "P1"
        assert added["actor"]["agent"]["name"] == "Field analyst" and added["actor"]["run_id"] == "run-7"
        assert log["items"][2]["phase_id"] == "P2" and log["items"][2]["note"] == "Follow-up"
        assert log["items"][3]["retracted"] == ["F-0001"] and log["items"][3]["note"] == "Duplicate"

        page = client.get(f"/v1/maps/{map_id}/changes", params={"since_version": 1, "limit": 2}, headers=headers).json()
        assert [item["version"] for item in page["items"]] == [2, 3] and page["next_since_version"] == 3
    print("  Change log passed.")
    return True


def test_links_connect_a_map_to_conversations_in_its_scope():
    print("Checking conversation links...")
    with make_client() as client:
        headers = actor_headers()
        map_id = create_map(client, headers)
        linked = client.post(f"/v1/maps/{map_id}/links", json={"conversation_id": "conv-9"}, headers=headers)
        assert linked.status_code == 200 and linked.json()["links"] == ["conv-9"]
        again = client.post(f"/v1/maps/{map_id}/links", json={"conversation_id": "conv-9"}, headers=headers)
        assert again.json()["links"] == ["conv-9"]
        listed = client.get("/v1/maps", params={"conversation_id": "conv-9"}, headers=headers).json()["items"]
        assert [item["map_id"] for item in listed] == [map_id]
        reader = actor_headers(access="read")
        reader_link = client.post(f"/v1/maps/{map_id}/links", json={"conversation_id": "conv-10"}, headers=reader)
        assert reader_link.status_code == 403
        bad_link = client.post(f"/v1/maps/{map_id}/links", json={"conversation_id": "conv 9"}, headers=headers)
        assert bad_link.status_code == 400

        unlinked = client.delete(f"/v1/maps/{map_id}/links/conv-9", headers=headers)
        assert unlinked.status_code == 200 and unlinked.json()["links"] == []
        assert client.get("/v1/maps", params={"conversation_id": "conv-9"}, headers=headers).json()["items"] == []
        assert client.get(f"/v1/maps/{map_id}", headers=headers).json()["version"] == 1
    print("  Conversation links passed.")
    return True


class YieldingStore(InMemoryMapStore):
    """Yields to the event loop on every read and commit, so concurrent writers really interleave."""

    async def read_map(self, map_id):
        await asyncio.sleep(0)
        return await super().read_map(map_id)

    async def commit(self, *args, **kwargs):
        await asyncio.sleep(0)
        return await super().commit(*args, **kwargs)


class FlakyStore(InMemoryMapStore):
    def __init__(self, failures):
        super().__init__()
        self.failures = failures

    async def commit(self, map_id, map_doc, expected_etag, creates, replaces):
        if expected_etag is not None and self.failures > 0:
            self.failures -= 1
            raise ConflictError()
        return await super().commit(map_id, map_doc, expected_etag, creates, replaces)


def test_concurrent_writers_get_consecutive_versions():
    print("Checking concurrent writes...")
    actor = Actor(user_id="user-1", scope="group:team-1", access="write")

    async def scenario(store, writers):
        engine = MapEngine(store, make_settings())
        map_id = (await engine.create_map(actor, CreateMapRequest(title="Busy map")))["map_id"]

        async def write(index):
            request = AddFeaturesRequest(features=[{"latitude": 1, "longitude": 1 + index * 0.01, "label": f"Point {index}"}])
            return await engine.add_features(actor, map_id, request)

        return await asyncio.gather(*(write(index) for index in range(writers)), return_exceptions=True)

    results = asyncio.run(scenario(YieldingStore(), 5))
    assert all(isinstance(result, dict) for result in results), results
    assert sorted(result["version"] for result in results) == [2, 3, 4, 5, 6]
    assert len({result["added"][0]["id"] for result in results}) == 5

    retried = asyncio.run(scenario(FlakyStore(failures=2), 1))[0]
    assert retried["version"] == 2
    gave_up = asyncio.run(scenario(FlakyStore(failures=50), 1))[0]
    assert getattr(gave_up, "code", "") == "map_busy" and gave_up.status_code == 409
    print("  Concurrent writes passed.")
    return True


class BrokenStore(InMemoryMapStore):
    async def read_map(self, map_id):
        raise StoreError("AccountKey=secret-value")


class ExplodingStore(InMemoryMapStore):
    async def list_links(self, scope_key):
        raise RuntimeError("secret-value")


def test_store_failures_never_reach_the_caller():
    print("Checking error responses...")
    with make_client(store=BrokenStore()) as client:
        response = client.get("/v1/maps/map-0123456789abcdef0123", headers=actor_headers())
        assert response.status_code == 503 and response.json()["error"] == "store_unavailable"
        assert "secret" not in response.text
    with make_client(store=ExplodingStore(), raise_server_exceptions=False) as client:
        response = client.get("/v1/maps", headers=actor_headers())
        assert response.status_code == 500 and response.json() == {"error": "internal_error", "message": "Unexpected error."}
    print("  Error responses passed.")
    return True


def test_openapi_is_served_but_cdn_backed_docs_pages_are_not():
    print("Checking the API surface...")
    with make_client() as client:
        assert client.get("/openapi.json").status_code == 200
        assert client.get("/docs").status_code == 404 and client.get("/redoc").status_code == 404
        health = client.get("/healthz")
        assert health.headers["x-content-type-options"] == "nosniff" and health.headers["cache-control"] == "no-store"
        too_big = client.post(
            "/v1/maps", content=b"x" * 1_048_577, headers={**actor_headers(), "Content-Type": "application/json"},
        )
        assert too_big.status_code == 413
        invalid_body = client.post("/v1/maps", json={"title": "x", "owner_scope": "group:other"}, headers=actor_headers())
        assert invalid_body.status_code == 400 and invalid_body.json()["error"] == "invalid_request"
    print("  API surface passed.")
    return True


def test_settings_and_the_local_developer_key():
    print("Checking settings...")
    for settings in (
        Settings(local_dev_key="k" * 32, store="cosmos", cosmos_endpoint="https://example.documents.azure.com"),
        Settings(local_dev_key="short", store="memory"),
        Settings(store="memory"),
    ):
        try:
            settings.validate()
        except SettingsError:
            continue
        raise AssertionError(f"Settings should have been refused: {settings}")
    try:
        Settings.from_env({"MAP_SERVER_STORE": "memory", "MAP_SERVER_TENANT_ID": "tenant"})
        raise AssertionError("Missing audiences should be refused.")
    except SettingsError:
        pass
    from_env = Settings.from_env({"MAP_SERVER_STORE": "memory", "MAP_SERVER_TENANT_ID": "tenant", "MAP_SERVER_AUDIENCES": "api://a, b"})
    assert from_env.audiences == ("api://a", "b")
    assert from_env.issuers == ("https://sts.windows.net/tenant/", "https://login.microsoftonline.com/tenant/v2.0")

    dev_settings = Settings(local_dev_key="k" * 32, store="memory")
    dev_settings.validate()
    actor = encode_actor({"user_id": "dev", "scope": "user:dev", "access": "write"})
    with TestClient(create_app(dev_settings, store=InMemoryMapStore())) as client:
        assert client.get("/v1/maps", headers={"Authorization": f"Bearer {'k' * 32}", "X-Map-Actor": actor}).status_code == 200
        assert client.get("/v1/maps", headers={"Authorization": "Bearer wrong", "X-Map-Actor": actor}).status_code == 401
        assert client.get("/v1/maps", headers={"Authorization": f"Bearer {make_token()}", "X-Map-Actor": actor}).status_code == 401
    print("  Settings passed.")
    return True


if __name__ == "__main__":
    tests = [
        test_app_version_includes_the_map_server,
        test_callers_need_a_valid_token_with_the_map_server_role,
        test_actor_context_is_required_and_validated,
        test_maps_stay_inside_the_scope_that_owns_them,
        test_agents_add_points_paths_and_areas_with_limits_enforced,
        test_duplicate_source_records_are_skipped_or_updated,
        test_phases_order_the_work_and_tag_every_feature,
        test_updates_and_retractions_keep_history_and_earlier_versions_can_be_shown,
        test_snapshot_matches_the_inline_map_payload_the_chat_already_renders,
        test_feature_list_filters_and_pages,
        test_change_log_records_each_version_with_its_phase_and_actor,
        test_links_connect_a_map_to_conversations_in_its_scope,
        test_concurrent_writers_get_consecutive_versions,
        test_store_failures_never_reach_the_caller,
        test_openapi_is_served_but_cdn_backed_docs_pages_are_not,
        test_settings_and_the_local_developer_key,
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
