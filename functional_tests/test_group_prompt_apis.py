# test_group_prompt_apis.py
"""
Functional tests for the immutable-target group prompt APIs.
Version: 0.261.136
Implemented in: 0.261.136

The real policy, access, projection and route modules run against the real
prompt data-layer functions, executed unchanged over an in-memory Cosmos stub
that honours ETag conditional writes. Group membership, status and settings are
local test seams; the group is always taken from the path, so a stale active
group can never redirect or widen a request. Network access is prohibited.
"""

import pytest

from test_support.versioning import assert_app_version_at_least
from test_support.group_prompt_harness import (
    LIST_PATH,
    MANAGER_ROLES,
    READER_ROLES,
    ROLE_USER,
    as_user,
    environment,
    seed_prompt,
)


# --------------------------------------------------------------------------
# Versioning
# --------------------------------------------------------------------------

def test_version_at_least_implementation():
    assert_app_version_at_least("0.261.136")


# --------------------------------------------------------------------------
# Reads: role and status
# --------------------------------------------------------------------------

@pytest.mark.parametrize("role", READER_ROLES)
def test_every_member_role_can_list_and_read(environment, role):
    seed_prompt(environment.group_container, "p1")
    as_user(environment, ROLE_USER[role])
    listing = environment.client.get(LIST_PATH)
    assert listing.status_code == 200
    body = listing.get_json()
    assert [item["id"] for item in body["prompts"]] == ["p1"]
    single = environment.client.get(f"{LIST_PATH}/p1")
    assert single.status_code == 200
    assert single.get_json()["id"] == "p1"


def test_list_envelope_and_single_top_level_shape(environment):
    seed_prompt(environment.group_container, "p1")
    as_user(environment, "owner")
    body = environment.client.get(LIST_PATH).get_json()
    assert set(body) == {"prompts", "page", "page_size", "total_count"}
    item = body["prompts"][0]
    assert item["id"] == "p1" and item["group_id"] == "group-a"
    single = environment.client.get(f"{LIST_PATH}/p1").get_json()
    assert single["id"] == "p1"
    assert "prompts" not in single


def test_list_supports_pagination_and_search(environment):
    for index in range(5):
        seed_prompt(environment.group_container, f"p{index}", name=f"Prompt {index}")
    seed_prompt(environment.group_container, "needle", name="Findable marker")
    as_user(environment, "owner")

    first = environment.client.get(f"{LIST_PATH}?page=1&page_size=2").get_json()
    assert first["page"] == 1 and first["page_size"] == 2
    assert first["total_count"] == 6
    assert len(first["prompts"]) == 2

    found = environment.client.get(f"{LIST_PATH}?search=Findable").get_json()
    assert [item["id"] for item in found["prompts"]] == ["needle"]


def test_reads_omit_private_fields_and_expose_etag(environment):
    seed_prompt(environment.group_container, "p1")
    as_user(environment, "owner")
    item = environment.client.get(f"{LIST_PATH}/p1").get_json()
    assert "is_favorite" not in item
    assert "user_id" not in item
    assert "_etag" not in item
    assert item["etag"] == environment.group_container.records["p1"]["_etag"]


@pytest.mark.parametrize("status", ["locked", "upload_disabled"])
def test_reads_allowed_on_readable_non_active_status(environment, status):
    container = environment.group_container
    seed_prompt(container, "p1", group_id=f"{status}-grp" if status != "upload_disabled" else "upload-disabled-grp")
    grp = "locked-grp" if status == "locked" else "upload-disabled-grp"
    seed_prompt(container, "px", group_id=grp)
    as_user(environment, "owner")
    response = environment.client.get(f"/api/groups/{grp}/prompts")
    assert response.status_code == 200


@pytest.mark.parametrize("grp", ["inactive-grp", "haunted-grp"])
def test_reads_denied_on_inactive_or_unknown_status(environment, grp):
    as_user(environment, "owner")
    assert environment.client.get(f"/api/groups/{grp}/prompts").status_code == 403
    assert environment.client.get(f"/api/groups/{grp}/prompts/anything").status_code == 403


def test_unknown_group_is_404_and_non_member_is_403(environment):
    seed_prompt(environment.group_container, "p1")
    as_user(environment, "owner")
    assert environment.client.get("/api/groups/no-such-group/prompts").status_code == 404
    as_user(environment, "stranger")
    assert environment.client.get(LIST_PATH).status_code == 403


def test_cross_group_prompt_is_not_readable(environment):
    seed_prompt(environment.group_container, "owned-by-b", group_id="group-b")
    as_user(environment, "owner")
    # The prompt exists, but not in group-a's path.
    assert environment.client.get(f"{LIST_PATH}/owned-by-b").status_code == 404


def test_list_is_scoped_to_the_path_group(environment):
    seed_prompt(environment.group_container, "a1", group_id="group-a")
    seed_prompt(environment.group_container, "b1", group_id="group-b")
    as_user(environment, "owner")
    ids = [item["id"] for item in environment.client.get(LIST_PATH).get_json()["prompts"]]
    assert ids == ["a1"]


# --------------------------------------------------------------------------
# Writes: role policy
# --------------------------------------------------------------------------

@pytest.mark.parametrize("role", MANAGER_ROLES)
def test_managers_can_create_update_delete(environment, role):
    as_user(environment, ROLE_USER[role])
    created = environment.client.post(LIST_PATH, json={"name": "New", "content": "Body"})
    assert created.status_code == 201, created.get_json()
    prompt = created.get_json()
    assert "is_favorite" not in prompt
    assert prompt["prompt_actions"] == ["edit", "delete"]
    prompt_id = prompt["id"]

    updated = environment.client.patch(
        f"{LIST_PATH}/{prompt_id}",
        json={"name": "Renamed", "expected_etag": prompt["etag"]},
    )
    assert updated.status_code == 200
    assert updated.get_json()["name"] == "Renamed"

    deleted = environment.client.delete(
        f"{LIST_PATH}/{prompt_id}",
        json={"expected_etag": updated.get_json()["etag"]},
    )
    assert deleted.status_code == 200
    assert prompt_id not in environment.group_container.records


def test_user_is_refused_all_three_writes(environment):
    seed_prompt(environment.group_container, "p1")
    etag = environment.group_container.records["p1"]["_etag"]
    as_user(environment, "member")
    assert environment.client.post(LIST_PATH, json={"name": "x", "content": "y"}).status_code == 403
    assert environment.client.patch(
        f"{LIST_PATH}/p1", json={"name": "z", "expected_etag": etag}
    ).status_code == 403
    assert environment.client.delete(
        f"{LIST_PATH}/p1", json={"expected_etag": etag}
    ).status_code == 403
    # No write reached storage.
    assert environment.group_container.records["p1"]["name"] == "Prompt p1"


@pytest.mark.parametrize("grp", ["locked-grp", "upload-disabled-grp"])
def test_writes_denied_when_not_active(environment, grp):
    seed_prompt(environment.group_container, "p1", group_id=grp)
    etag = environment.group_container.records["p1"]["_etag"]
    as_user(environment, "owner")
    assert environment.client.post(
        f"/api/groups/{grp}/prompts", json={"name": "x", "content": "y"}
    ).status_code == 403
    assert environment.client.patch(
        f"/api/groups/{grp}/prompts/p1", json={"name": "z", "expected_etag": etag}
    ).status_code == 403
    assert environment.client.delete(
        f"/api/groups/{grp}/prompts/p1", json={"expected_etag": etag}
    ).status_code == 403


def test_reader_prompt_actions_are_empty(environment):
    seed_prompt(environment.group_container, "p1")
    as_user(environment, "member")
    item = environment.client.get(f"{LIST_PATH}/p1").get_json()
    assert item["prompt_actions"] == []


# --------------------------------------------------------------------------
# Conditional writes
# --------------------------------------------------------------------------

def test_patch_missing_expected_etag_is_400(environment):
    seed_prompt(environment.group_container, "p1")
    as_user(environment, "owner")
    response = environment.client.patch(f"{LIST_PATH}/p1", json={"name": "z"})
    assert response.status_code == 400


def test_patch_stale_etag_is_409_with_no_partial_write(environment):
    seed_prompt(environment.group_container, "p1")
    as_user(environment, "owner")
    response = environment.client.patch(
        f"{LIST_PATH}/p1", json={"name": "z", "content": "new", "expected_etag": '"stale"'},
    )
    assert response.status_code == 409
    assert response.get_json()["error_code"] == "prompt_changed"
    stored = environment.group_container.records["p1"]
    assert stored["name"] == "Prompt p1" and stored["content"] == "Body of p1"


def test_delete_missing_expected_etag_is_400(environment):
    seed_prompt(environment.group_container, "p1")
    as_user(environment, "owner")
    assert environment.client.delete(f"{LIST_PATH}/p1", json={}).status_code == 400
    assert "p1" in environment.group_container.records


def test_delete_expected_etag_as_query_parameter_is_rejected(environment):
    seed_prompt(environment.group_container, "p1")
    etag = environment.group_container.records["p1"]["_etag"]
    as_user(environment, "owner")
    # Sending expected_etag as a query parameter must be a 400, never honoured.
    response = environment.client.delete(f"{LIST_PATH}/p1?expected_etag={etag}", json={"expected_etag": etag})
    assert response.status_code == 400
    assert "p1" in environment.group_container.records


def test_delete_stale_etag_is_409_and_prompt_survives(environment):
    seed_prompt(environment.group_container, "p1")
    as_user(environment, "owner")
    response = environment.client.delete(f"{LIST_PATH}/p1", json={"expected_etag": '"stale"'})
    assert response.status_code == 409
    assert response.get_json()["error_code"] == "prompt_changed"
    assert "p1" in environment.group_container.records


def test_update_and_delete_of_missing_prompt_is_404(environment):
    as_user(environment, "owner")
    assert environment.client.patch(
        f"{LIST_PATH}/ghost", json={"name": "z", "expected_etag": '"x"'}
    ).status_code == 404
    assert environment.client.delete(
        f"{LIST_PATH}/ghost", json={"expected_etag": '"x"'}
    ).status_code == 404


# --------------------------------------------------------------------------
# Body and query validation
# --------------------------------------------------------------------------

def test_is_favorite_is_rejected_on_create_and_update(environment):
    seed_prompt(environment.group_container, "p1")
    etag = environment.group_container.records["p1"]["_etag"]
    as_user(environment, "owner")
    created = environment.client.post(
        LIST_PATH, json={"name": "n", "content": "c", "is_favorite": True},
    )
    assert created.status_code == 400
    updated = environment.client.patch(
        f"{LIST_PATH}/p1", json={"is_favorite": False, "expected_etag": etag},
    )
    assert updated.status_code == 400


def test_unknown_fields_are_rejected(environment):
    seed_prompt(environment.group_container, "p1")
    etag = environment.group_container.records["p1"]["_etag"]
    as_user(environment, "owner")
    assert environment.client.post(
        LIST_PATH, json={"name": "n", "content": "c", "colour": "red"}
    ).status_code == 400
    assert environment.client.patch(
        f"{LIST_PATH}/p1", json={"name": "n", "colour": "red", "expected_etag": etag}
    ).status_code == 400


def test_missing_required_create_fields_is_400(environment):
    as_user(environment, "owner")
    assert environment.client.post(LIST_PATH, json={"name": "  "}).status_code == 400
    assert environment.client.post(LIST_PATH, json={"content": "c"}).status_code == 400


def test_duplicate_json_keys_are_rejected(environment):
    as_user(environment, "owner")
    response = environment.client.post(
        LIST_PATH, data='{"name": "a", "name": "b", "content": "c"}',
        content_type="application/json",
    )
    assert response.status_code == 400


def test_list_rejects_unknown_and_duplicate_query_parameters(environment):
    as_user(environment, "owner")
    assert environment.client.get(f"{LIST_PATH}?colour=red").status_code == 400
    assert environment.client.get(f"{LIST_PATH}?page=1&page=2").status_code == 400


def test_non_list_routes_reject_query_parameters(environment):
    seed_prompt(environment.group_container, "p1")
    as_user(environment, "owner")
    assert environment.client.get(f"{LIST_PATH}/p1?x=1").status_code == 400
    assert environment.client.post(f"{LIST_PATH}?x=1", json={"name": "n", "content": "c"}).status_code == 400


def test_reads_reject_a_request_body(environment):
    seed_prompt(environment.group_container, "p1")
    as_user(environment, "owner")
    response = environment.client.get(
        f"{LIST_PATH}/p1", data='{"unexpected": true}', content_type="application/json",
    )
    assert response.status_code == 400


def test_feature_disabled_returns_400(environment):
    environment.settings["enable_group_workspaces"] = False
    as_user(environment, "owner")
    assert environment.client.get(LIST_PATH).status_code == 400


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
