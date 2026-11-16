# test_group_endpoint_apis.py
"""
Functional test for the immutable-target group model endpoint APIs.
Version: 0.261.160
Implemented in: 0.261.140

The real policy, access, route, group-document, Key Vault and settings modules run
unchanged (see ``test_support/group_endpoint_harness.py``). Cosmos is the
etag-enforcing ``FakeContainer`` from the File Sync concurrency test, and Key Vault
is an in-memory vault that records every secret name. Key Vault storage is enabled
in the settings the helpers read, so no secret assertion can pass vacuously.

Covered: the role, status and availability matrix; the list and endpoint shapes;
strict requests; create, update and delete semantics; ``revision`` conflicts with
nothing written; the shared group-document discipline (a concurrent membership
change is kept, a deleted group is not recreated); credential staging, replacement,
cleanup and deletion by exact name, including staged-credential cleanup when a
write ends in a conflict; the ``endpoint_in_use`` references; audit parity; and the
chat bootstrap cache bump.
"""

import hashlib
import json
import re
import uuid

import pytest
from azure.cosmos.exceptions import CosmosAccessConditionFailedError, CosmosHttpResponseError

from test_support.group_endpoint_harness import (
    GROUP_A,
    GROUP_B,
    NON_WRITER_ROLES,
    READER_ROLES,
    ROLE_USERS,
    WRITER_ROLES,
    aoai_endpoint,
    foundry_endpoint,
    group_endpoint_environment,
)


LIST_PATH = f"/api/groups/{GROUP_A}/model-endpoints"
FLAGS = (
    "enable_semantic_kernel",
    "per_user_semantic_kernel",
    "allow_group_custom_endpoints",
    "enable_multi_model_endpoints",
)
DISABLED_REASON = "Group model endpoints are not enabled."
GOVERNANCE_REASON = "Your administrator has restricted access to this capability."
CONFLICT_BODY = {
    "error": "This model endpoint changed. Reload it before saving.",
    "error_code": "endpoint_conflict",
}
STAGED_NAME = re.compile(r"^(?P<endpoint>.+)--model-endpoint--group--s-[0-9a-f]{16,}$")


def item_path(endpoint_id, group_id=GROUP_A):
    return f"/api/groups/{group_id}/model-endpoints/{endpoint_id}"


def legacy_key_name(endpoint_id, field="api-key"):
    return f"{endpoint_id}--model-endpoint--group--model-endpoint-{field}"


def new_endpoint(**changes):
    payload = aoai_endpoint("", api_key="sk-new")
    payload.pop("id")
    payload["name"] = "New connection"
    payload.update(changes)
    return payload


@pytest.fixture(scope="module")
def module_env():
    with group_endpoint_environment() as env:
        yield env


@pytest.fixture
def env(module_env):
    module_env.reset()
    yield module_env
    module_env.reset()


@pytest.fixture
def seeded(env):
    """Group A with one V1-created endpoint whose key uses the legacy deterministic name."""
    env.seed_group_with_legacy_endpoints(GROUP_A, [aoai_endpoint("ep-a")])
    env.seed_group_with_legacy_endpoints(GROUP_B, [aoai_endpoint("ep-b", url="https://group-b.openai.azure.com")])
    env.vault.writes.clear()
    return env


def create(env, payload, group_id=GROUP_A):
    return env.call("POST", f"/api/groups/{group_id}/model-endpoints", payload)


def patch(env, endpoint_id, payload, group_id=GROUP_A):
    return env.call("PATCH", item_path(endpoint_id, group_id), payload)


def delete(env, endpoint_id, revision, group_id=GROUP_A):
    return env.call("DELETE", item_path(endpoint_id, group_id), {"expected_revision": revision})


def committed_logs(env):
    return [
        entry for entry in env.logs
        if entry[0] in (
            "[MODELS] Group model endpoint created.",
            "[MODELS] Group model endpoint updated.",
            "[MODELS] Group model endpoint deleted.",
        )
    ]


def land_membership_change(env, group_id=GROUP_A, user_id="late-member"):
    def concurrent():
        record = env.stored_group(group_id)
        record["users"].append({"userId": user_id, "email": "", "displayName": "Late"})
        env.groups.seed(record)
    return concurrent


# --------------------------------------------------------------------------
# Reads: role, status and availability
# --------------------------------------------------------------------------

@pytest.mark.parametrize("role", READER_ROLES)
def test_every_member_role_can_list_and_read(seeded, role):
    seeded.as_user(ROLE_USERS[role])
    listing = seeded.client.get(LIST_PATH)
    assert listing.status_code == 200
    assert [endpoint["id"] for endpoint in listing.get_json()["endpoints"]] == ["ep-a"]
    single = seeded.client.get(item_path("ep-a"))
    assert single.status_code == 200
    assert single.get_json()["endpoint"]["id"] == "ep-a"
    assert listing.headers["Cache-Control"] == "no-store"


@pytest.mark.parametrize("user_id,group_id,status", [
    ("outsider", GROUP_A, 403), ("owner", "missing-group", 404),
])
def test_foreign_or_missing_groups_are_refused_without_data(seeded, user_id, group_id, status):
    seeded.as_user(user_id)
    for response in (
        seeded.client.get(f"/api/groups/{group_id}/model-endpoints"),
        seeded.client.get(item_path("ep-a", group_id)),
    ):
        assert response.status_code == status
        assert "endpoints" not in response.get_json() and "endpoint" not in response.get_json()


@pytest.mark.parametrize("status,readable", [
    ("active", True), ("locked", True), ("upload_disabled", True),
    ("inactive", False), ("unexpected-status", False),
])
def test_reads_follow_the_browsable_statuses(env, status, readable):
    env.seed_group_with_legacy_endpoints(GROUP_A, [aoai_endpoint("ep-a")], status=status)
    env.as_user("member")
    response = env.client.get(LIST_PATH)
    assert response.status_code == (200 if readable else 403)


@pytest.mark.parametrize("flag", FLAGS)
def test_each_flag_off_refuses_every_route_with_the_section_reason(seeded, flag):
    seeded.settings[flag] = False
    revision_payload = {"expected_revision": "any"}
    for method, path, body in (
        ("GET", LIST_PATH, None),
        ("POST", LIST_PATH, new_endpoint()),
        ("GET", item_path("ep-a"), None),
        ("PATCH", item_path("ep-a"), {**revision_payload, "name": "x"}),
        ("DELETE", item_path("ep-a"), revision_payload),
        ("POST", f"/api/groups/{GROUP_A}/models/fetch", {"endpoint_id": "ep-a"}),
        ("POST", f"/api/groups/{GROUP_A}/models/test-model", {"endpoint_id": "ep-a"}),
        ("POST", f"/api/groups/{GROUP_A}/models/foundry/agents", {"endpoint_id": "ep-a"}),
    ):
        response = seeded.call(method, path, body)
        assert response.status_code == 403, (method, path)
        assert response.get_json() == {"error": DISABLED_REASON}
    assert seeded.write_calls() == []


def test_governance_denial_refuses_every_route(seeded):
    seeded.denied_features.add("governance_group_endpoints")
    for method, path, body in (
        ("GET", LIST_PATH, None),
        ("POST", LIST_PATH, new_endpoint()),
        ("GET", item_path("ep-a"), None),
    ):
        response = seeded.call(method, path, body)
        assert response.status_code == 403
        assert response.get_json() == {"error": GOVERNANCE_REASON}


def test_group_workspaces_off_is_refused_by_the_route_decorator(seeded):
    seeded.settings["enable_group_workspaces"] = False
    response = seeded.client.get(LIST_PATH)
    assert response.status_code == 400
    assert response.get_json() == {"error": "Enable Group Workspaces is disabled."}


def test_reads_never_consult_the_active_group(seeded):
    seeded.active_group = GROUP_B
    seeded.client.get(LIST_PATH)
    seeded.client.get(item_path("ep-a"))
    seeded.require_active_group.assert_not_called()


# --------------------------------------------------------------------------
# Shapes
# --------------------------------------------------------------------------

def test_list_envelope_carries_only_the_keys_the_manager_needs(seeded):
    body = seeded.client.get(LIST_PATH).get_json()
    assert set(body) == {"endpoints", "multi_endpoint_enabled", "custom_api_types"}
    assert body["multi_endpoint_enabled"] is True
    assert body["custom_api_types"] == seeded.modules.access.get_model_endpoint_provider_ui_options()


def test_each_endpoint_is_the_sanitized_admin_shape_plus_revision_and_actions(seeded):
    listed = seeded.client.get(LIST_PATH).get_json()["endpoints"][0]
    stored = seeded.stored_endpoint(GROUP_A, "ep-a")
    sanitized = seeded.modules.settings.sanitize_model_endpoints_for_frontend([stored])[0]
    assert {key: value for key, value in listed.items() if key not in ("revision", "endpoint_actions")} == sanitized
    assert re.fullmatch(r"[0-9a-f]{64}", listed["revision"])
    assert listed["endpoint_actions"] == ["edit", "delete", "enable", "test"]
    assert "api_key" not in listed["auth"] and listed["has_api_key"] is True
    single = seeded.client.get(item_path("ep-a")).get_json()
    assert set(single) == {"endpoint"} and single["endpoint"] == listed
    assert "model-endpoint" not in json.dumps(single)


def test_providers_the_editor_does_not_offer_are_neither_listed_nor_addressable(env):
    hidden = foundry_endpoint("ep-workflow", provider="foundry_workflow")
    env.seed_group_with_legacy_endpoints(GROUP_A, [aoai_endpoint("ep-a"), hidden])
    ids = [endpoint["id"] for endpoint in env.client.get(LIST_PATH).get_json()["endpoints"]]
    assert ids == ["ep-a"]
    assert env.client.get(item_path("ep-workflow")).status_code == 404
    assert patch(env, "ep-workflow", {"expected_revision": "x", "name": "n"}).status_code == 404
    assert delete(env, "ep-workflow", "x").status_code == 404
    # Every write preserves it.
    assert create(env, new_endpoint()).status_code == 201
    assert env.stored_endpoint(GROUP_A, "ep-workflow") is not None


# --------------------------------------------------------------------------
# Writes: roles, statuses and the stored-document recheck
# --------------------------------------------------------------------------

@pytest.mark.parametrize("role", WRITER_ROLES)
def test_writers_can_create_update_and_delete(seeded, role):
    seeded.as_user(ROLE_USERS[role])
    created = create(seeded, new_endpoint())
    assert created.status_code == 201
    endpoint = created.get_json()["endpoint"]
    updated = patch(seeded, endpoint["id"], {"expected_revision": endpoint["revision"], "name": "Renamed"})
    assert updated.status_code == 200
    assert updated.get_json()["endpoint"]["name"] == "Renamed"
    removed = delete(seeded, endpoint["id"], updated.get_json()["endpoint"]["revision"])
    assert removed.status_code == 200 and removed.get_json() == {"success": True}
    assert seeded.stored_endpoint(GROUP_A, endpoint["id"]) is None


@pytest.mark.parametrize("role", NON_WRITER_ROLES)
def test_non_writers_are_refused_every_write(seeded, role):
    revision = seeded.revision_of(GROUP_A, "ep-a")
    seeded.as_user(ROLE_USERS[role])
    for response in (
        create(seeded, new_endpoint()),
        patch(seeded, "ep-a", {"expected_revision": revision, "name": "x"}),
        delete(seeded, "ep-a", revision),
    ):
        assert response.status_code == 403
        assert response.get_json() == {"error": "You do not have permission to manage this group's model endpoints."}
    assert seeded.write_calls() == [] and seeded.vault.writes == []


@pytest.mark.parametrize("status", ["locked", "upload_disabled", "inactive"])
def test_writes_need_an_active_group(env, status):
    env.seed_group_with_legacy_endpoints(GROUP_A, [aoai_endpoint("ep-a")], status=status)
    response = create(env, new_endpoint())
    assert response.status_code == 403
    assert env.write_calls() == []


def test_a_demotion_that_lands_before_the_replace_refuses_the_write(seeded):
    seeded.as_user("admin")
    revision = seeded.revision_of(GROUP_A, "ep-a")

    def demote():
        record = seeded.stored_group(GROUP_A)
        record["admins"] = []
        seeded.groups.seed(record)

    seeded.groups.before_replace.append(demote)
    response = patch(seeded, "ep-a", {"expected_revision": revision, "name": "x", "auth": {"api_key": "sk-rotated"}})
    assert response.status_code == 403
    stored = seeded.stored_group(GROUP_A)
    assert stored["admins"] == []
    assert seeded.stored_endpoint(GROUP_A, "ep-a")["name"] == "Endpoint ep-a"
    # The first attempt staged a key before losing its race; it is removed again.
    staged = seeded.vault.written_names()
    assert len(staged) == 1 and seeded.vault.deletes == staged


# --------------------------------------------------------------------------
# Create
# --------------------------------------------------------------------------

def test_create_allocates_a_server_id_and_stores_one_endpoint(seeded):
    response = create(seeded, new_endpoint())
    assert response.status_code == 201
    endpoint = response.get_json()["endpoint"]
    assert uuid.UUID(endpoint["id"])
    stored_ids = [item["id"] for item in seeded.stored_group(GROUP_A)["model_endpoints"]]
    assert stored_ids == ["ep-a", endpoint["id"]]
    assert endpoint["endpoint_actions"] == ["edit", "delete", "enable", "test"]
    assert endpoint["revision"] == seeded.revision_of(GROUP_A, endpoint["id"])


def test_create_honours_a_client_id_and_refuses_an_existing_one(seeded):
    assert create(seeded, new_endpoint(id="client-chosen")).status_code == 201
    duplicate = create(seeded, new_endpoint(id="client-chosen"))
    assert duplicate.status_code == 409
    assert duplicate.get_json() == {"error": "A model endpoint with that id already exists."}
    existing = create(seeded, new_endpoint(id="ep-a"))
    assert existing.status_code == 409


@pytest.mark.parametrize("bad_id", ["bad/id", " padded", "a,b", "x" * 65, 42])
def test_create_refuses_an_unusable_client_id(seeded, bad_id):
    response = create(seeded, new_endpoint(id=bad_id))
    assert response.status_code == 400
    assert response.get_json() == {"error": "Invalid model endpoint identifier."}
    assert seeded.write_calls() == []


def test_create_refuses_a_provider_the_editor_does_not_offer(seeded):
    response = create(seeded, new_endpoint(provider="foundry_workflow"))
    assert response.status_code == 400
    assert response.get_json()["code"] == "invalid_custom_endpoint"
    assert seeded.write_calls() == []


def test_projection_only_fields_are_never_stored(seeded):
    response = create(seeded, new_endpoint(revision="client-revision", endpoint_actions=["edit"], has_api_key=False))
    endpoint_id = response.get_json()["endpoint"]["id"]
    stored = seeded.stored_endpoint(GROUP_A, endpoint_id)
    assert not {"revision", "endpoint_actions", "has_api_key"} & set(stored)


def test_expected_revision_is_not_part_of_a_create(seeded):
    response = create(seeded, new_endpoint(expected_revision="x"))
    assert response.status_code == 400
    assert seeded.write_calls() == []


# --------------------------------------------------------------------------
# Validation keeps the admin and legacy shapes
# --------------------------------------------------------------------------

def test_custom_endpoint_validation_errors_use_the_admin_shape(seeded):
    payload = {
        "name": "Custom", "provider": "custom", "api_type": "openai",
        "connection": {"endpoint": "http://models.example.com/v1"},
        "auth": {"type": "api_key", "api_key": "sk-custom"},
        "models": [{"id": "m", "modelName": "model-a"}],
    }
    response = create(seeded, payload)
    assert response.status_code == 400
    body = response.get_json()
    assert body["code"] == "invalid_custom_endpoint"
    assert "HTTPS" in body["error"]
    assert seeded.write_calls() == [] and seeded.vault.writes == []


def test_token_budget_errors_keep_the_legacy_shape(seeded):
    payload = new_endpoint(models=[{"id": "m", "deploymentName": "gpt-4o", "tokenLimitProvider": "unsupported"}])
    response = create(seeded, payload)
    assert response.status_code == 400
    assert response.get_json() == {
        "error": "Select a supported token-limit provider.", "error_code": "model_context_invalid",
    }
    assert seeded.write_calls() == []


def test_an_unexpected_failure_is_a_stable_500(seeded, monkeypatch):
    def broken(endpoints):
        raise RuntimeError("private normalization detail")

    monkeypatch.setattr(seeded.modules.access, "normalize_model_endpoints", broken)
    response = create(seeded, new_endpoint())
    assert response.status_code == 500
    assert response.get_json() == {"error": "Unable to complete the model endpoint request."}
    assert "private normalization detail" not in response.get_data(as_text=True)
    assert seeded.write_calls() == []


def test_connection_errors_return_their_public_message(seeded):
    response = create(seeded, new_endpoint(connection="not-an-object"))
    assert response.status_code == 400
    assert response.get_json() == {
        "error": "Connection configuration must be an object.", "code": "invalid_model_selection",
    }


# --------------------------------------------------------------------------
# Strict requests
# --------------------------------------------------------------------------

@pytest.mark.parametrize("method,path", [
    ("GET", LIST_PATH), ("POST", LIST_PATH), ("GET", item_path("ep-a")),
    ("PATCH", item_path("ep-a")), ("DELETE", item_path("ep-a")),
])
def test_no_route_accepts_query_parameters(seeded, method, path):
    body = None if method == "GET" else {"expected_revision": "x", "name": "n"}
    response = seeded.call(method, path, body, query_string={"group_id": GROUP_B})
    assert response.status_code == 400
    assert response.get_json() == {"error": "This request does not accept query parameters."}


@pytest.mark.parametrize("path", [LIST_PATH, item_path("ep-a")])
def test_reads_take_no_body(seeded, path):
    response = seeded.call("GET", path, raw="{}")
    assert response.status_code == 400


@pytest.mark.parametrize("raw,content_type,message", [
    ('{"name": "a", "name": "b"}', "application/json", "Duplicate fields are not supported."),
    ("[1, 2]", "application/json", "A JSON object is required for this request."),
    ("not json", "application/json", "Provide valid JSON with no duplicate fields."),
    ('{"name": "a"}', "text/plain", "A JSON object is required for this request."),
])
def test_writes_take_one_json_object_without_duplicate_keys(seeded, raw, content_type, message):
    for method, path in (("POST", LIST_PATH), ("PATCH", item_path("ep-a")), ("DELETE", item_path("ep-a"))):
        response = seeded.call(method, path, raw=raw, content_type=content_type)
        assert response.status_code == 400, (method, raw)
        assert response.get_json() == {"error": message}
    assert seeded.write_calls() == []


def test_delete_body_is_exactly_the_expected_revision(seeded):
    revision = seeded.revision_of(GROUP_A, "ep-a")
    extra = seeded.call("DELETE", item_path("ep-a"), {"expected_revision": revision, "force": True})
    assert extra.status_code == 400
    assert extra.get_json() == {"error": "Unsupported field(s): force."}
    missing = seeded.call("DELETE", item_path("ep-a"), {})
    assert missing.status_code == 400
    assert missing.get_json() == {"error": "A non-empty 'expected_revision' is required."}
    assert seeded.write_calls() == []


def test_patch_requires_an_expected_revision_and_a_change(seeded):
    missing = patch(seeded, "ep-a", {"name": "x"})
    assert missing.status_code == 400
    assert missing.get_json() == {"error": "A non-empty 'expected_revision' is required."}
    revision = seeded.revision_of(GROUP_A, "ep-a")
    empty = patch(seeded, "ep-a", {"expected_revision": revision, "revision": revision})
    assert empty.status_code == 400
    assert empty.get_json() == {"error": "No fields provided for update."}


# --------------------------------------------------------------------------
# PATCH semantics
# --------------------------------------------------------------------------

def test_patch_merges_server_side_and_keeps_the_stripped_key(seeded):
    before = seeded.stored_endpoint(GROUP_A, "ep-a")
    revision = seeded.revision_of(GROUP_A, "ep-a")
    response = patch(seeded, "ep-a", {"expected_revision": revision, "name": "Renamed"})
    assert response.status_code == 200
    after = seeded.stored_endpoint(GROUP_A, "ep-a")
    assert after["name"] == "Renamed"
    assert after["auth"]["api_key"] == before["auth"]["api_key"] == legacy_key_name("ep-a")
    assert after["connection"] == before["connection"] and after["models"] == before["models"]
    assert seeded.vault.writes == [] and seeded.vault.deletes == []
    assert response.get_json()["endpoint"]["revision"] != revision


def test_patch_cannot_renumber_the_endpoint(seeded):
    revision = seeded.revision_of(GROUP_A, "ep-a")
    response = patch(seeded, "ep-a", {"expected_revision": revision, "id": "renumbered", "name": "n"})
    assert response.status_code == 200
    assert response.get_json()["endpoint"]["id"] == "ep-a"
    assert seeded.stored_endpoint(GROUP_A, "renumbered") is None


def test_blank_values_are_skipped_rather_than_clearing(seeded):
    revision = seeded.revision_of(GROUP_A, "ep-a")
    response = patch(seeded, "ep-a", {"expected_revision": revision, "name": "", "auth": {"api_key": ""}})
    assert response.status_code == 200
    stored = seeded.stored_endpoint(GROUP_A, "ep-a")
    assert stored["name"] == "Endpoint ep-a"
    assert stored["auth"]["api_key"] == legacy_key_name("ep-a")


def test_disabling_is_the_enable_operation_and_is_stored(seeded):
    revision = seeded.revision_of(GROUP_A, "ep-a")
    response = patch(seeded, "ep-a", {"expected_revision": revision, "enabled": False})
    assert response.status_code == 200
    assert seeded.stored_endpoint(GROUP_A, "ep-a")["enabled"] is False


def test_switching_the_auth_type_clears_the_old_credential(seeded):
    revision = seeded.revision_of(GROUP_A, "ep-a")
    response = patch(seeded, "ep-a", {"expected_revision": revision, "auth": {"type": "managed_identity"}})
    assert response.status_code == 200
    stored = seeded.stored_endpoint(GROUP_A, "ep-a")
    assert "api_key" not in stored["auth"]
    assert seeded.vault.deletes == [legacy_key_name("ep-a")]


# --------------------------------------------------------------------------
# revision
# --------------------------------------------------------------------------

def test_revision_is_the_digest_of_the_stored_endpoint_without_secrets(seeded):
    stored = seeded.stored_endpoint(GROUP_A, "ep-a")
    material = json.loads(json.dumps(stored))
    for field in ("api_key", "client_secret", "bearer_token", "access_token", "refresh_token"):
        material["auth"].pop(field, None)
    expected = hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    assert seeded.revision_of(GROUP_A, "ep-a") == expected


def test_revision_never_hashes_an_inline_secret(env):
    env.settings["enable_key_vault_secret_storage"] = False
    env.seed_group_with_legacy_endpoints(GROUP_A, [aoai_endpoint("ep-a", api_key="sk-inline-one")])
    assert env.stored_endpoint(GROUP_A, "ep-a")["auth"]["api_key"] == "sk-inline-one"
    first = env.revision_of(GROUP_A, "ep-a")
    record = env.stored_group(GROUP_A)
    record["model_endpoints"][0]["auth"]["api_key"] = "sk-inline-two"
    record["model_endpoints"][0]["auth"]["refresh_token"] = "refresh-inline"
    env.groups.seed(record)
    assert env.revision_of(GROUP_A, "ep-a") == first


def test_revision_does_not_move_with_catalogue_settings(env):
    env.settings["model_catalog"] = {"profiles": [{
        "id": "custom-vision", "displayName": "Custom vision", "capabilities": {"processesImages": True},
    }]}
    model = {"id": "chat", "deploymentName": "gpt-4o", "modelName": "gpt-4o", "enabled": True, "catalogProfileId": "custom-vision"}
    env.seed_group_with_legacy_endpoints(GROUP_A, [aoai_endpoint("ep-a", models=[model])])
    first = env.client.get(item_path("ep-a")).get_json()["endpoint"]
    env.settings["model_catalog"]["profiles"][0]["capabilities"]["processesImages"] = False
    second = env.client.get(item_path("ep-a")).get_json()["endpoint"]
    assert first["models"][0]["capability_status"] != second["models"][0]["capability_status"]
    assert first["revision"] == second["revision"]


def test_a_stale_revision_is_a_conflict_with_nothing_written(seeded):
    stale = seeded.revision_of(GROUP_A, "ep-a")
    assert patch(seeded, "ep-a", {"expected_revision": stale, "name": "First"}).status_code == 200
    seeded.groups.calls.clear()
    for response in (
        patch(seeded, "ep-a", {"expected_revision": stale, "name": "Second", "auth": {"api_key": "sk-late"}}),
        delete(seeded, "ep-a", stale),
    ):
        assert response.status_code == 409
        assert response.get_json() == CONFLICT_BODY
    assert seeded.write_calls() == [] and seeded.vault.writes == []
    assert seeded.stored_endpoint(GROUP_A, "ep-a")["name"] == "First"


def test_a_secret_only_change_by_another_writer_keeps_the_revision(seeded):
    revision = seeded.revision_of(GROUP_A, "ep-a")
    rotated = patch(seeded, "ep-a", {"expected_revision": revision, "auth": {"api_key": "sk-rotated"}})
    assert rotated.status_code == 200
    assert rotated.get_json()["endpoint"]["revision"] == revision
    # The first tab still holds the old revision. Its edit lands and keeps the new key.
    edited = patch(seeded, "ep-a", {"expected_revision": revision, "name": "Edited elsewhere"})
    assert edited.status_code == 200
    stored = seeded.stored_endpoint(GROUP_A, "ep-a")
    assert stored["auth"]["api_key"] == seeded.vault.written_names()[0]
    assert seeded.vault.secrets[stored["auth"]["api_key"]] == "sk-rotated"


def test_a_concurrent_edit_of_the_same_endpoint_conflicts_and_discards_the_staged_key(seeded):
    revision = seeded.revision_of(GROUP_A, "ep-a")

    def concurrent_edit():
        record = seeded.stored_group(GROUP_A)
        record["model_endpoints"][0]["name"] = "Changed by another manager"
        seeded.groups.seed(record)

    seeded.groups.before_replace.append(concurrent_edit)
    response = patch(seeded, "ep-a", {"expected_revision": revision, "auth": {"api_key": "sk-lost"}})
    assert response.status_code == 409
    assert response.get_json() == CONFLICT_BODY
    staged = seeded.vault.written_names()
    assert len(staged) == 1 and STAGED_NAME.match(staged[0]).group("endpoint") == "ep-a"
    assert seeded.vault.deletes == staged
    stored = seeded.stored_endpoint(GROUP_A, "ep-a")
    assert stored["name"] == "Changed by another manager"
    assert stored["auth"]["api_key"] == legacy_key_name("ep-a")


# --------------------------------------------------------------------------
# The shared group document
# --------------------------------------------------------------------------

def test_a_membership_change_between_read_and_replace_is_kept_with_no_conflict(seeded):
    revision = seeded.revision_of(GROUP_A, "ep-a")
    seeded.groups.before_replace.append(land_membership_change(seeded))
    response = patch(seeded, "ep-a", {"expected_revision": revision, "name": "Renamed"})
    assert response.status_code == 200
    stored = seeded.stored_group(GROUP_A)
    assert "late-member" in [user["userId"] for user in stored["users"]]
    assert seeded.stored_endpoint(GROUP_A, "ep-a")["name"] == "Renamed"
    assert [call[0] for call in seeded.write_calls()] == ["replace_item", "replace_item"]


def test_a_create_racing_a_membership_change_keeps_both(seeded):
    seeded.groups.before_replace.append(land_membership_change(seeded))
    response = create(seeded, new_endpoint())
    assert response.status_code == 201
    stored = seeded.stored_group(GROUP_A)
    assert "late-member" in [user["userId"] for user in stored["users"]]
    assert len(stored["model_endpoints"]) == 2


def test_a_group_deleted_mid_write_is_404_and_never_recreated(seeded):
    revision = seeded.revision_of(GROUP_A, "ep-a")
    seeded.groups.before_replace.append(lambda: seeded.groups.records.pop((GROUP_A, GROUP_A)))
    response = patch(seeded, "ep-a", {"expected_revision": revision, "auth": {"api_key": "sk-orphan"}})
    assert response.status_code == 404
    assert response.get_json() == {"error": "The selected group was not found."}
    assert seeded.stored_group(GROUP_A) is None
    assert not [call for call in seeded.groups.calls if call[0] in ("create_item", "upsert_item")]
    staged = seeded.vault.written_names()
    assert len(staged) == 1 and seeded.vault.deletes == staged


def test_a_writer_that_keeps_losing_gets_a_409_and_every_staged_key_is_removed(seeded):
    revision = seeded.revision_of(GROUP_A, "ep-a")
    attempts = seeded.modules.group.GROUP_DOCUMENT_WRITE_ATTEMPTS
    seeded.groups.before_replace.extend(
        land_membership_change(seeded, user_id=f"late-{index}") for index in range(attempts)
    )
    response = patch(seeded, "ep-a", {"expected_revision": revision, "auth": {"api_key": "sk-busy"}})
    assert response.status_code == 409
    assert response.get_json() == {
        "error": "The group changed while your request was being saved. Try again.",
        "error_code": "group_write_conflict",
    }
    staged = seeded.vault.written_names()
    assert len(staged) == attempts
    assert sorted(seeded.vault.deletes) == sorted(staged)
    assert legacy_key_name("ep-a") in seeded.vault.secrets
    assert seeded.stored_endpoint(GROUP_A, "ep-a")["auth"]["api_key"] == legacy_key_name("ep-a")


def test_a_lost_response_commit_is_reported_committed_and_its_key_kept(seeded, monkeypatch):
    revision = seeded.revision_of(GROUP_A, "ep-a")
    original = seeded.groups.replace_item

    def replace_then_lose_the_response(item, body, etag=None, match_condition=None, **kwargs):
        original(item, body, etag=etag, match_condition=match_condition, **kwargs)
        monkeypatch.setattr(seeded.groups, "replace_item", original)
        raise CosmosAccessConditionFailedError(status_code=412, message="Precondition failed")

    monkeypatch.setattr(seeded.groups, "replace_item", replace_then_lose_the_response)
    response = patch(seeded, "ep-a", {"expected_revision": revision, "auth": {"api_key": "sk-committed"}})
    assert response.status_code == 200
    staged = seeded.vault.written_names()
    assert len(staged) == 1
    assert seeded.stored_endpoint(GROUP_A, "ep-a")["auth"]["api_key"] == staged[0]
    # Only the superseded legacy name is removed, never the committed staged one.
    assert seeded.vault.deletes == [legacy_key_name("ep-a")]


def test_an_uncertain_failure_keeps_staged_keys(seeded, monkeypatch):
    revision = seeded.revision_of(GROUP_A, "ep-a")

    def transport_failure(*args, **kwargs):
        raise CosmosHttpResponseError(status_code=503, message="private transport detail")

    monkeypatch.setattr(seeded.groups, "replace_item", transport_failure)
    response = patch(seeded, "ep-a", {"expected_revision": revision, "auth": {"api_key": "sk-uncertain"}})
    assert response.status_code == 500
    assert response.get_json() == {"error": "Unable to complete the model endpoint request."}
    assert "private transport detail" not in response.get_data(as_text=True)
    assert len(seeded.vault.written_names()) == 1 and seeded.vault.deletes == []
    assert any("Kept staged group model endpoint credentials" in entry[0] for entry in seeded.logs)


# --------------------------------------------------------------------------
# Credentials (Key Vault enabled)
# --------------------------------------------------------------------------

def test_create_stages_the_key_under_a_fresh_group_scoped_name(seeded):
    response = create(seeded, new_endpoint(id="ep-new"))
    assert response.status_code == 201
    assert len(seeded.vault.writes) == 1
    name, value = seeded.vault.writes[0]
    assert STAGED_NAME.match(name).group("endpoint") == "ep-new" and value == "sk-new"
    stored = seeded.stored_endpoint(GROUP_A, "ep-new")
    assert stored["auth"]["api_key"] == name
    assert seeded.vault.deletes == []
    assert "sk-new" not in response.get_data(as_text=True)


def test_an_edit_without_a_key_keeps_the_stored_reference(seeded):
    revision = seeded.revision_of(GROUP_A, "ep-a")
    assert patch(seeded, "ep-a", {"expected_revision": revision, "description": "d"}).status_code == 200
    assert seeded.stored_endpoint(GROUP_A, "ep-a")["auth"]["api_key"] == legacy_key_name("ep-a")
    assert seeded.vault.writes == [] and seeded.vault.deletes == []


def test_a_new_key_replaces_the_legacy_name_which_is_cleaned_up_after_the_write(seeded):
    revision = seeded.revision_of(GROUP_A, "ep-a")
    assert patch(seeded, "ep-a", {"expected_revision": revision, "auth": {"api_key": "sk-rotated"}}).status_code == 200
    [(name, value)] = seeded.vault.writes
    assert STAGED_NAME.match(name).group("endpoint") == "ep-a" and value == "sk-rotated"
    assert seeded.stored_endpoint(GROUP_A, "ep-a")["auth"]["api_key"] == name
    assert seeded.vault.deletes == [legacy_key_name("ep-a")]
    assert legacy_key_name("ep-a") not in seeded.vault.secrets


def test_delete_removes_the_endpoint_credentials(seeded):
    revision = seeded.revision_of(GROUP_A, "ep-a")
    assert delete(seeded, "ep-a", revision).status_code == 200
    assert seeded.vault.deletes == [legacy_key_name("ep-a")]
    assert seeded.stored_group(GROUP_A)["model_endpoints"] == []


def test_other_endpoints_keep_their_credentials(seeded):
    created = create(seeded, new_endpoint(id="ep-second")).get_json()["endpoint"]
    seeded.vault.writes.clear()
    assert patch(seeded, "ep-second", {"expected_revision": created["revision"], "auth": {"api_key": "sk-2"}}).status_code == 200
    assert seeded.stored_endpoint(GROUP_A, "ep-a")["auth"]["api_key"] == legacy_key_name("ep-a")
    assert legacy_key_name("ep-a") not in seeded.vault.deletes


def test_a_foundry_client_secret_is_staged_and_cleaned_up_the_same_way(env):
    env.seed_group_with_legacy_endpoints(GROUP_A, [foundry_endpoint("ep-f")])
    legacy = legacy_key_name("ep-f", "client-secret")
    assert env.stored_endpoint(GROUP_A, "ep-f")["auth"]["client_secret"] == legacy
    env.vault.writes.clear()
    revision = env.revision_of(GROUP_A, "ep-f")
    assert patch(env, "ep-f", {"expected_revision": revision, "auth": {"client_secret": "sp-rotated"}}).status_code == 200
    [(name, value)] = env.vault.writes
    assert STAGED_NAME.match(name).group("endpoint") == "ep-f" and value == "sp-rotated"
    assert env.vault.deletes == [legacy]


def test_a_client_supplied_reference_is_refused(seeded):
    victim_name = legacy_key_name("ep-b")
    borrowed = create(seeded, new_endpoint(id="ep-b", auth={"type": "api_key", "api_key": victim_name}))
    assert borrowed.status_code == 400
    assert borrowed.get_json() == {"error": "Stored credential references cannot be supplied in a request."}
    revision = seeded.revision_of(GROUP_A, "ep-a")
    swapped = patch(seeded, "ep-a", {"expected_revision": revision, "auth": {"api_key": victim_name}})
    assert swapped.status_code == 400
    own = patch(seeded, "ep-a", {"expected_revision": revision, "auth": {"api_key": legacy_key_name("ep-a")}})
    assert own.status_code == 400
    assert seeded.write_calls() == [] and seeded.vault.writes == []
    assert seeded.vault.secrets[victim_name] == "sk-plain"


def test_a_placeholder_keeps_a_stored_key_and_is_refused_without_one(seeded):
    revision = seeded.revision_of(GROUP_A, "ep-a")
    kept = patch(seeded, "ep-a", {"expected_revision": revision, "auth": {"api_key": "Stored_In_KeyVault"}})
    assert kept.status_code == 200
    assert seeded.stored_endpoint(GROUP_A, "ep-a")["auth"]["api_key"] == legacy_key_name("ep-a")
    for placeholder in ("Stored_In_KeyVault", "***REDACTED***"):
        refused = create(seeded, new_endpoint(auth={"type": "api_key", "api_key": placeholder}))
        assert refused.status_code == 400
        assert refused.get_json() == {"error": "A stored credential is unavailable. Re-enter its value."}
    assert seeded.vault.writes == []


def test_key_vault_off_stores_the_key_inline(env):
    env.settings["enable_key_vault_secret_storage"] = False
    env.seed_group(GROUP_A)
    response = create(env, new_endpoint(id="ep-inline"))
    assert response.status_code == 201
    assert env.stored_endpoint(GROUP_A, "ep-inline")["auth"]["api_key"] == "sk-new"
    assert env.vault.writes == []
    assert "sk-new" not in response.get_data(as_text=True)


# --------------------------------------------------------------------------
# Delete while in use
# --------------------------------------------------------------------------

def seed_agent(env, agent_id, **fields):
    env.agents.seed({
        "id": agent_id, "group_id": GROUP_A, "name": f"agent_{agent_id}",
        "display_name": f"Agent {agent_id}", "agent_type": "local", "other_settings": {}, **fields,
    })


def seed_workflow(env, workflow_id, **fields):
    env.workflows.seed({"id": workflow_id, "group_id": GROUP_A, "name": f"Workflow {workflow_id}", "tasks": [], **fields})


@pytest.mark.parametrize("seed,reference", [
    (lambda env: seed_agent(env, "a1", model_endpoint_id="ep-a"), {"kind": "agent", "id": "a1", "name": "Agent a1"}),
    (lambda env: seed_agent(env, "a2", agent_type="aifoundry", other_settings={"azure_ai_foundry": {"endpoint_id": "ep-a"}}),
     {"kind": "agent", "id": "a2", "name": "Agent a2"}),
    (lambda env: seed_agent(env, "a3", agent_type="new_foundry", other_settings={"new_foundry": {"endpoint_id": "ep-a"}}),
     {"kind": "agent", "id": "a3", "name": "Agent a3"}),
    (lambda env: seed_agent(env, "a4", agent_type="foundry_workflow", other_settings={"foundry_workflow": {"endpoint_id": "ep-a"}}),
     {"kind": "agent", "id": "a4", "name": "Agent a4"}),
    (lambda env: seed_workflow(env, "w1", model_endpoint_id="ep-a"), {"kind": "workflow", "id": "w1", "name": "Workflow w1"}),
    (lambda env: seed_workflow(env, "w2", tasks=[{"id": "t1", "runner": {"type": "model", "model_endpoint_id": "ep-a"}}]),
     {"kind": "workflow", "id": "w2", "name": "Workflow w2"}),
])
def test_delete_is_refused_while_the_endpoint_is_in_use(seeded, seed, reference):
    seed(seeded)
    revision = seeded.revision_of(GROUP_A, "ep-a")
    response = delete(seeded, "ep-a", revision)
    assert response.status_code == 409
    body = response.get_json()
    assert body["error_code"] == "endpoint_in_use"
    assert body["references"] == [reference]
    assert seeded.stored_endpoint(GROUP_A, "ep-a") is not None
    assert seeded.write_calls() == [] and seeded.vault.deletes == []


def test_every_reference_is_listed(seeded):
    seed_agent(seeded, "a1", model_endpoint_id="ep-a")
    seed_workflow(seeded, "w1", model_endpoint_id="ep-a")
    body = delete(seeded, "ep-a", seeded.revision_of(GROUP_A, "ep-a")).get_json()
    assert [(item["kind"], item["id"]) for item in body["references"]] == [("agent", "a1"), ("workflow", "w1")]


def test_a_setting_the_runtime_would_not_read_is_not_a_reference(seeded):
    # A local agent never resolves a Foundry section; another group's agent is not scanned.
    seed_agent(seeded, "a1", other_settings={"azure_ai_foundry": {"endpoint_id": "ep-a"}})
    seeded.agents.seed({"id": "other", "group_id": GROUP_B, "name": "other", "model_endpoint_id": "ep-a"})
    response = delete(seeded, "ep-a", seeded.revision_of(GROUP_A, "ep-a"))
    assert response.status_code == 200


def test_disabling_an_endpoint_in_use_is_always_allowed(seeded):
    seed_agent(seeded, "a1", model_endpoint_id="ep-a")
    response = patch(seeded, "ep-a", {"expected_revision": seeded.revision_of(GROUP_A, "ep-a"), "enabled": False})
    assert response.status_code == 200


def test_a_failed_reference_scan_refuses_the_delete(seeded, monkeypatch):
    def failing_query(*args, **kwargs):
        raise CosmosHttpResponseError(status_code=500, message="private scan detail")

    monkeypatch.setattr(seeded.agents, "query_items", failing_query)
    response = delete(seeded, "ep-a", seeded.revision_of(GROUP_A, "ep-a"))
    assert response.status_code == 503
    assert response.get_json() == {"error": "Unable to confirm this model endpoint is unused. Try again."}
    assert seeded.stored_endpoint(GROUP_A, "ep-a") is not None


# --------------------------------------------------------------------------
# Audit parity and the chat bootstrap cache
# --------------------------------------------------------------------------

def test_each_committed_write_logs_one_tagged_diagnostic_and_no_activity(seeded):
    created = create(seeded, new_endpoint(id="ep-audit")).get_json()["endpoint"]
    updated = patch(seeded, "ep-audit", {"expected_revision": created["revision"], "name": "n"}).get_json()["endpoint"]
    delete(seeded, "ep-audit", updated["revision"])
    entries = committed_logs(seeded)
    assert [entry[0] for entry in entries] == [
        "[MODELS] Group model endpoint created.",
        "[MODELS] Group model endpoint updated.",
        "[MODELS] Group model endpoint deleted.",
    ]
    for _message, level, extra in entries:
        assert extra["group_id"] == GROUP_A and extra["endpoint_id"] == "ep-audit" and extra["user_id"] == "owner"
        assert level == 20
    assert seeded.activity.calls == []
    source = (seeded.modules.access.__file__ and open(seeded.modules.access.__file__, encoding="utf-8").read())
    assert "functions_activity_logging" not in source


def test_refused_writes_log_no_change_and_never_bump_the_cache(seeded):
    revision = seeded.revision_of(GROUP_A, "ep-a")
    patch(seeded, "ep-a", {"expected_revision": "stale", "name": "x"})
    create(seeded, new_endpoint(id="ep-a"))
    seeded.as_user("member")
    delete(seeded, "ep-a", revision)
    assert committed_logs(seeded) == []
    assert seeded.bumps == []


def test_each_committed_write_bumps_the_chat_bootstrap_cache_once(seeded):
    created = create(seeded, new_endpoint(id="ep-cache")).get_json()["endpoint"]
    assert seeded.bumps == ["group_model_endpoints_updated"]
    updated = patch(seeded, "ep-cache", {"expected_revision": created["revision"], "name": "n"}).get_json()["endpoint"]
    delete(seeded, "ep-cache", updated["revision"])
    assert seeded.bumps == ["group_model_endpoints_updated"] * 3


def test_the_legacy_collection_routes_still_resolve_the_active_group(seeded):
    seeded.active_group = GROUP_B
    listing = seeded.client.get("/api/group/model-endpoints")
    assert listing.status_code == 200
    assert [item["id"] for item in listing.get_json()["endpoints"]] == ["ep-b"]
    seeded.require_active_group.assert_called_once_with("owner")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
