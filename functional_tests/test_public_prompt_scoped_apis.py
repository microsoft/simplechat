# test_public_prompt_scoped_apis.py
"""
Functional tests for immutable-target, workspace-bound public prompt APIs (M9C).
Version: 0.261.178
Implemented in: 0.261.178

The real public prompt policy, access, projection and route modules run in an
isolated Flask app over an ETag-enforcing Cosmos stub (``public_prompt_harness``).
The workspace identity is always taken from the path, so a stale active-workspace
preference can never redirect or widen a read or a write. Reads are open to any
authenticated caller of a browsable workspace; writes are limited to
Owner/Admin/DocumentManager on an active workspace and are conditional on
``expected_etag``.
"""

import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.public_prompt_harness import (  # noqa: F401  (environment is a pytest fixture)
    LIST_PATH,
    MANAGER_ROLES,
    READER_ROLES,
    ROLE_USER,
    as_user,
    environment,
    seed_prompt,
)


def item_path(prompt_id, workspace_id="public-a"):
    return f"/api/public-workspaces/{workspace_id}/prompts/{prompt_id}"


def etag_of(environment, prompt_id):
    as_user(environment, "owner")
    payload = environment.client.get(LIST_PATH).get_json()
    return next(item["etag"] for item in payload["prompts"] if item["id"] == prompt_id)


# --------------------------------------------------------------------------
# Reads and projection.
# --------------------------------------------------------------------------

def test_list_projects_scoped_prompts_and_strips_private_fields(environment):
    seed_prompt(environment.public_container, "p1")
    as_user(environment, "owner")
    response = environment.client.get(LIST_PATH)

    assert response.status_code == 200
    item = response.get_json()["prompts"][0]
    assert item["public_id"] == "public-a"
    assert item["etag"]
    assert item["prompt_actions"] == ["edit", "delete"]
    for stripped in ("is_favorite", "user_id", "group_id", "_etag"):
        assert stripped not in item


def test_list_never_leaks_another_workspaces_prompts(environment):
    seed_prompt(environment.public_container, "here", workspace_id="public-a")
    seed_prompt(environment.public_container, "elsewhere", workspace_id="public-b")
    as_user(environment, "owner")

    ids = [item["id"] for item in environment.client.get(LIST_PATH).get_json()["prompts"]]
    assert ids == ["here"]


def test_reading_another_workspaces_prompt_through_this_path_is_404(environment):
    seed_prompt(environment.public_container, "elsewhere", workspace_id="public-b")
    as_user(environment, "owner")

    response = environment.client.get(item_path("elsewhere", "public-a"))
    assert response.status_code == 404


@pytest.mark.parametrize("role", READER_ROLES)
def test_every_role_including_a_stranger_may_read(environment, role):
    seed_prompt(environment.public_container, "p1")
    as_user(environment, ROLE_USER[role])

    assert environment.client.get(LIST_PATH).status_code == 200


# --------------------------------------------------------------------------
# Writes: creation, conditional update and delete.
# --------------------------------------------------------------------------

def test_manager_create_returns_projected_prompt(environment):
    as_user(environment, "manager")
    response = environment.client.post(LIST_PATH, json={
        "name": "Standup", "content": "Body", "description": "A note.",
    })

    assert response.status_code == 201
    created = response.get_json()
    assert created["public_id"] == "public-a"
    assert created["prompt_actions"] == ["edit", "delete"]
    assert "is_favorite" not in created


def test_conditional_update_succeeds_with_the_current_etag(environment):
    seed_prompt(environment.public_container, "p1")
    response = environment.client.patch(item_path("p1"), json={
        "name": "Renamed", "expected_etag": etag_of(environment, "p1"),
    })

    assert response.status_code == 200
    assert response.get_json()["name"] == "Renamed"


def test_update_with_a_stale_etag_is_a_409_prompt_changed(environment):
    seed_prompt(environment.public_container, "p1")
    as_user(environment, "owner")
    response = environment.client.patch(item_path("p1"), json={
        "name": "Renamed", "expected_etag": '"stale"',
    })

    assert response.status_code == 409
    assert response.get_json()["error_code"] == "prompt_changed"


def test_delete_with_a_stale_etag_is_a_409_prompt_changed(environment):
    seed_prompt(environment.public_container, "p1")
    as_user(environment, "owner")
    response = environment.client.delete(item_path("p1"), json={"expected_etag": '"stale"'})

    assert response.status_code == 409
    assert response.get_json()["error_code"] == "prompt_changed"


def test_delete_succeeds_with_the_current_etag(environment):
    seed_prompt(environment.public_container, "p1")
    response = environment.client.delete(item_path("p1"), json={"expected_etag": etag_of(environment, "p1")})

    assert response.status_code == 200
    as_user(environment, "owner")
    assert environment.client.get(LIST_PATH).get_json()["prompts"] == []


# --------------------------------------------------------------------------
# Write authorization: role and status.
# --------------------------------------------------------------------------

def test_a_reader_may_not_create_update_or_delete(environment):
    seed_prompt(environment.public_container, "p1")
    etag = etag_of(environment, "p1")
    as_user(environment, "stranger")

    assert environment.client.post(LIST_PATH, json={"name": "n", "content": "c"}).status_code == 403
    assert environment.client.patch(item_path("p1"), json={"name": "n", "expected_etag": etag}).status_code == 403
    assert environment.client.delete(item_path("p1"), json={"expected_etag": etag}).status_code == 403


@pytest.mark.parametrize("role", MANAGER_ROLES)
def test_every_manager_role_may_create(environment, role):
    as_user(environment, ROLE_USER[role])
    response = environment.client.post(LIST_PATH, json={"name": "n", "content": "c"})
    assert response.status_code == 201


@pytest.mark.parametrize("workspace_id", ["locked-ws", "upload-disabled-ws"])
def test_a_browsable_but_non_active_workspace_is_read_only(environment, workspace_id):
    seed_prompt(environment.public_container, "p1", workspace_id=workspace_id)
    list_path = f"/api/public-workspaces/{workspace_id}/prompts"
    as_user(environment, "owner")

    assert environment.client.get(list_path).status_code == 200
    assert environment.client.post(list_path, json={"name": "n", "content": "c"}).status_code == 403


@pytest.mark.parametrize("workspace_id", ["inactive-ws", "haunted-ws"])
def test_an_inactive_or_unknown_status_workspace_denies_reads(environment, workspace_id):
    list_path = f"/api/public-workspaces/{workspace_id}/prompts"
    as_user(environment, "owner")

    assert environment.client.get(list_path).status_code == 403


# --------------------------------------------------------------------------
# Strict transport: query, body and field rejection.
# --------------------------------------------------------------------------

def test_create_rejects_query_parameters(environment):
    as_user(environment, "owner")
    response = environment.client.post(f"{LIST_PATH}?foo=bar", json={"name": "n", "content": "c"})
    assert response.status_code == 400


def test_create_rejects_a_smuggled_favorite(environment):
    as_user(environment, "owner")
    response = environment.client.post(LIST_PATH, json={"name": "n", "content": "c", "is_favorite": True})
    assert response.status_code == 400


def test_update_requires_a_non_empty_expected_etag(environment):
    seed_prompt(environment.public_container, "p1")
    as_user(environment, "owner")
    response = environment.client.patch(item_path("p1"), json={"name": "Renamed"})
    assert response.status_code == 400


def test_delete_requires_a_non_empty_expected_etag(environment):
    seed_prompt(environment.public_container, "p1")
    as_user(environment, "owner")
    response = environment.client.delete(item_path("p1"), json={})
    assert response.status_code == 400


def test_duplicate_json_keys_are_rejected(environment):
    as_user(environment, "owner")
    response = environment.client.post(
        LIST_PATH, data='{"name": "a", "name": "b", "content": "c"}', content_type="application/json",
    )
    assert response.status_code == 400


def test_editing_a_missing_prompt_is_404(environment):
    as_user(environment, "owner")
    response = environment.client.patch(item_path("ghost"), json={"name": "n", "expected_etag": '"x"'})
    assert response.status_code == 404


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
