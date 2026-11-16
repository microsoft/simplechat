# test_public_workspace_status_compatibility.py
"""
Functional regressions for public workspace status compatibility.
Version: 0.261.355
Implemented in: 0.261.355

Exercise the real creator, native directory API, directory mutation projector,
chat status policy, and membership request/cancel routes without cloud access.
Only an absent status inherits active; explicit invalid values remain unavailable.
"""

from copy import deepcopy

import pytest
from azure.cosmos._cosmos_responses import CosmosDict
from flask import session

from test_public_membership_apis import (
    OUTSIDER,
    REQUESTS_PATH,
    environment as membership_environment,
    login,
)
from test_support.m365 import CosmosContainer
from test_support.public_directory_harness import (
    public_directory_environment,
    public_workspace_document,
)
from test_support.public_settings_harness import PublicDocumentsContainer


MISSING = object()
STATUS_CASES = [
    pytest.param(MISSING, "active", True, id="absent"),
    pytest.param("active", "active", True, id="active"),
    pytest.param("locked", "locked", True, id="locked"),
    pytest.param("upload_disabled", "upload_disabled", True, id="upload-disabled"),
    pytest.param("inactive", "inactive", False, id="inactive"),
    pytest.param(None, "unknown", False, id="null"),
    pytest.param("", "unknown", False, id="empty"),
    pytest.param("future-status", "unknown", False, id="unrecognized"),
]


@pytest.fixture
def directory():
    with public_directory_environment() as env:
        yield env


def test_real_creator_persists_active_with_sdk_response(directory, monkeypatch):
    """The writer's actual output, not an idealized seed, is immediately usable."""
    storage = CosmosContainer(partition_field="id")
    monkeypatch.setattr(directory.modules.public_workspaces, "cosmos_public_workspaces_container", storage)
    cache_reasons = []
    monkeypatch.setattr(directory.modules.public_workspaces, "bump_chat_bootstrap_global_cache_version",
                        lambda **kwargs: cache_reasons.append(kwargs["reason"]))
    with directory.app.test_request_context():
        session["user"] = {
            "oid": "owner-1", "name": "Olive Owner",
            "preferred_username": "olive.owner@example.test",
        }
        created = directory.modules.public_workspaces.create_public_workspace(
            "New public library", "Published reference material",
        )
    stored = storage.read_item(created["id"], partition_key=created["id"])
    assert type(stored) is CosmosDict
    assert type(created) is dict and "_etag" not in created
    assert stored["status"] == created["status"] == "active"
    assert stored["_etag"] and stored["owner"]["userId"] == "owner-1"
    assert cache_reasons == ["public_workspace_created"]

    directory.seed_document(stored)
    directory.as_user("owner-1")
    response = directory.directory()
    assert response.status_code == 200
    row = response.get_json()["workspaces"][0]
    assert row["status"] == "active"
    assert row["userRole"] == "Owner" and row["membership"] == "member"


def test_workspace_storage_consumers_preserve_sdk_and_query_shapes(directory, monkeypatch):
    """Runtime evidence for the storage module's invalidated whole-module review.

    This checks response consumption, not the query predicates: the existing SDK
    container returns plain query rows and wrapped point responses for one record.
    """
    public = directory.modules.public_workspaces
    storage = CosmosContainer(partition_field="id")
    monkeypatch.setattr(public, "cosmos_public_workspaces_container", storage)
    seeded = storage.create_item(public_workspace_document("library", "Public library"))
    found = public.find_public_workspace_by_id("library")
    missing = public.find_public_workspace_by_id("missing")
    assert type(found) is CosmosDict and found["_etag"] == seeded["_etag"]
    assert missing is None

    listings = [
        public.get_all_public_workspaces(),
        public.get_user_public_workspaces("owner-1"),
        public.search_public_workspaces("library", "owner-1"),
        public.search_all_public_workspaces("library"),
    ]
    for rows in listings:
        assert len(rows) == 1 and type(rows[0]) is dict
        assert rows[0]["id"] == "library" and rows[0]["_etag"] == seeded["_etag"]
    selected = public.find_public_workspaces_by_ids(["library"])
    admin_rows, truncated = public.list_public_workspaces_for_admin_directory("library")
    expected = [{"id": "library", "name": "Public library", "description": "A shared public workspace"}]
    assert selected == admin_rows == expected and not truncated

    def rename(fresh):
        fresh["name"] = "Renamed library"
        return fresh

    updated = public.update_public_workspace_document_with_etag_guard(
        "library", rename, cache_reason=None,
    )
    assert type(updated) is CosmosDict and updated["_etag"] != seeded["_etag"]
    assert updated["name"] == "Renamed library"
    assert updated["status"] == "active" and updated["owner"] == seeded["owner"]

    documents = PublicDocumentsContainer()
    documents.seed({"id": "guide", "public_workspace_id": "library"})
    monkeypatch.setattr(public, "cosmos_public_documents_container", documents, raising=False)
    count = public.count_public_workspace_documents("library")
    assert type(count) is int and count == 1
    public.delete_public_workspace("library")
    deleted = public.find_public_workspace_by_id("library")
    assert deleted is None


@pytest.mark.parametrize("stored_status,expected,allowed", STATUS_CASES)
@pytest.mark.parametrize("caller,role,membership", [
    ("owner-1", "Owner", "member"), ("outsider-1", "User", "none"),
])
def test_directory_projections_match_chat_without_writes(
    directory, stored_status, expected, allowed, caller, role, membership,
):
    document = public_workspace_document("library", "Public library")
    if stored_status is MISSING:
        del document["status"]
    else:
        document["status"] = stored_status
    directory.seed_document(document)
    directory.as_user(caller)
    before = deepcopy(directory.public_workspaces.records)

    response = directory.directory()
    mutation_row = directory.modules.directory.build_public_directory_row(
        CosmosDict(document, response_headers={}), caller,
    )
    chat_allowed, _reason = directory.modules.public_workspaces.check_public_workspace_status_allows_operation(
        document, "chat",
    )
    assert response.status_code == 200
    row = response.get_json()["workspaces"][0]
    assert row == mutation_row
    assert row["status"] == expected and chat_allowed is allowed
    assert row["userRole"] == role and row["membership"] == membership
    assert set(row) == {
        "id", "name", "description", "heroColor", "hasLogo", "logoVersion",
        "userRole", "membership", "status",
    }
    assert directory.public_workspaces.records == before
    assert directory.write_calls() == [] and directory.user_settings_writes == []


def test_membership_response_replacement_preserves_legacy_active_status(membership_environment):
    env = membership_environment
    del env.store["ws-a"]["status"]
    login(env, OUTSIDER)

    requested = env.client.post(REQUESTS_PATH)
    assert requested.status_code == 201
    request_row = requested.get_json()["workspace"]
    assert request_row["status"] == "active" and request_row["membership"] == "pending"
    assert "status" not in env.store["ws-a"]

    cancelled = env.client.delete(REQUESTS_PATH)
    assert cancelled.status_code == 200
    cancel_row = cancelled.get_json()["workspace"]
    assert cancel_row["status"] == "active" and cancel_row["membership"] == "none"
    assert "status" not in env.store["ws-a"]
    assert request_row["id"] == cancel_row["id"] == "ws-a"
    assert request_row["userRole"] == cancel_row["userRole"] == "User"
