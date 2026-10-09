# test_personal_identity_apis.py
"""
Native personal identity authorization, credential preservation and conditional writes.
Version: 0.261.315
Implemented in: 0.261.315

Exercises real route, availability, storage, and Key Vault modules with external I/O
stubbed and network access blocked, including read/commit races and safe errors.
"""

import json
from copy import deepcopy

import pytest

from test_support.group_identity_harness import as_user
from test_support.personal_identity_harness import (
    LIST_PATH, create_identity, group_environment, personal_environment,  # noqa: F401
)
from test_support.versioning import assert_app_version_at_least


def test_version():
    assert_app_version_at_least("0.261.315")


@pytest.mark.parametrize("auth_type,uses,extra", [
    ("api_key", ["action"], {"secret": "test-key"}),
    ("bearer_token", ["action"], {"secret": "test-token"}),
    ("client_secret", ["action"], {"secret": "test-client-secret", "client_id": "app", "tenant_id": "tenant"}),
    ("connection_string", ["file_sync"], {"secret": "test-connection"}),
    ("username_password", ["file_sync"], {"username": "svc", "password": "test-password", "domain": "CORP"}),
    ("anonymous", ["file_sync"], {}),
    ("managed_identity", ["action", "file_sync"], {"managed_identity_client_id": "assigned-client"}),
])
def test_create_read_edit_and_delete_preserve_credentials(personal_environment, auth_type, uses, extra):
    env = personal_environment
    created = create_identity(env, credentials={"auth_type": auth_type, **extra}, usage_contexts=uses)
    identifier = created["id"]
    assert created["scope_type"] == "personal" and created["user_id"] == "owner"
    assert created["etag"] and created["identity_actions"] == ["edit", "delete"]
    stored = env.identities.get_workspace_identity("personal", "owner", identifier)
    before_auth = deepcopy(stored["auth"])
    listing = env.client.get(LIST_PATH)
    assert listing.status_code == 200 and listing.headers["Cache-Control"] == "no-store"
    assert listing.get_json()["identities"][0]["credentials"]["auth_type"] == auth_type
    read = env.client.get(f"{LIST_PATH}/{identifier}")
    assert read.get_json()["identity"] == listing.get_json()["identities"][0]
    assert "auth" not in created and "_etag" not in created
    for field in ("password", "secret"):
        if field in extra:
            assert extra[field] not in json.dumps(listing.get_json())
    updated = env.client.patch(f"{LIST_PATH}/{identifier}", json={
        "name": "Renamed", "expected_etag": created["etag"],
        "credentials": {"auth_type": auth_type, "password": "", "secret": ""},
    })
    assert updated.status_code == 200
    record = updated.get_json()["identity"]
    assert record["etag"] != created["etag"]
    assert env.identities.get_workspace_identity("personal", "owner", identifier)["auth"] == before_auth
    deleted = env.client.delete(f"{LIST_PATH}/{identifier}", json={"expected_etag": record["etag"]})
    assert deleted.status_code == 200
    missing = env.client.get(f"{LIST_PATH}/{identifier}")
    assert missing.status_code == 404


def test_other_users_cannot_read_edit_or_delete(personal_environment):
    env = personal_environment
    created = create_identity(env)
    as_user(env, "other-user")
    listing = env.client.get(LIST_PATH)
    assert listing.get_json()["identities"] == []
    for method in ("get", "patch", "delete"):
        options = {} if method == "get" else {"json": {"expected_etag": created["etag"]}}
        response = getattr(env.client, method)(f"{LIST_PATH}/{created['id']}", **options)
        assert response.status_code == 404
    assert env.personal_container.records[("owner", created["id"])]["name"] == created["name"]


@pytest.mark.parametrize("method", ["patch", "delete"])
@pytest.mark.parametrize("token,status", [(None, 400), ("", 400), ("stale", 409)])
def test_native_mutations_require_current_etags(personal_environment, method, token, status):
    env = personal_environment
    created = create_identity(env)
    before = deepcopy(env.personal_container.records)
    body = {} if token is None else {"expected_etag": token}
    response = getattr(env.client, method)(f"{LIST_PATH}/{created['id']}", json=body)
    assert response.status_code == status
    if status == 409:
        assert response.get_json()["error_code"] == "etag_conflict"
    assert env.personal_container.records == before


@pytest.mark.parametrize("method", ["patch", "delete"])
@pytest.mark.parametrize("concurrent_delete", [False, True])
def test_read_commit_races_never_overwrite_or_resurrect(personal_environment, method, concurrent_delete):
    env = personal_environment
    env.settings["enable_key_vault_secret_storage"] = True
    created = create_identity(env)
    vault_before = deepcopy(env.state.vault)

    def concurrent_write(records, key):
        if concurrent_delete:
            records.pop(key)
        else:
            records[key]["_etag"] = "concurrent-token"
            records[key]["description"] = "Another tab"

    env.personal_container.before_replace = concurrent_write
    body = {"expected_etag": created["etag"]}
    if method == "patch":
        body.update({"name": "Rejected rename", "credentials": {"secret": "new-secret"}})
    response = getattr(env.client, method)(f"{LIST_PATH}/{created['id']}", json=body)
    assert response.status_code == (404 if concurrent_delete else 409)
    assert env.state.vault == vault_before
    if concurrent_delete:
        assert ("owner", created["id"]) not in env.personal_container.records
    else:
        assert env.personal_container.records[("owner", created["id"])]["name"] == created["name"]


def test_key_vault_rotation_cleans_up_the_previous_secret(personal_environment):
    env = personal_environment
    env.settings["enable_key_vault_secret_storage"] = True
    created = create_identity(env)
    old_names = set(env.state.vault)
    response = env.client.patch(f"{LIST_PATH}/{created['id']}", json={
        "expected_etag": created["etag"], "credentials": {"secret": "rotated-value"},
    })
    assert response.status_code == 200
    assert not old_names.intersection(env.state.vault)
    assert list(env.state.vault.values()) == ["rotated-value"]
    assert "rotated-value" not in response.get_data(as_text=True)


@pytest.mark.parametrize("kind", ["file_source", "action", "proxy_action"])
def test_referenced_identity_cannot_be_deleted(personal_environment, kind):
    env = personal_environment
    created = create_identity(env)
    if kind == "file_source":
        env.state.file_sync_sources = [{"id": "source", "name": "Archive", "identity_id": created["id"]}]
    else:
        env.state.personal_actions = [{
            "id": "action", "name": "Connector", "type": "yamcs",
            **({"identity_id": created["id"]} if kind == "action" else {
                "additionalFields": {"basic_auth_identity_id": created["id"]},
            }),
        }]
    response = env.client.delete(f"{LIST_PATH}/{created['id']}", json={"expected_etag": created["etag"]})
    assert response.status_code == 409
    assert response.get_json()["error_code"] == "identity_in_use"
    assert response.get_json()["references"]


@pytest.mark.parametrize("body", [
    [], None, {"name": "Name", "user_id": "other"},
    {"name": "Name", "scope_type": "group"}, {"name": "Name", "auth": {}},
    {"name": "Name", "expected_etag": "create-token"},
    {"name": ""}, {"name": "x" * 121},
    {"name": "Name", "usage_contexts": ["model_endpoint"]},
    {"name": "Name", "credentials": {"secret_secret_name": "foreign-vault-ref"}},
    {"name": "Name", "credentials": {"secret": {"bad": "type"}}},
])
def test_invalid_writes_are_refused_before_storage(personal_environment, body):
    env = personal_environment
    response = env.client.post(LIST_PATH, data=json.dumps(body), content_type="application/json")
    assert response.status_code == 400
    assert not env.personal_container.records and not env.state.secret_writes


@pytest.mark.parametrize("data", ['{"name":"one","name":"two"}', '{"credentials":{"secret":"one","secret":"two"}}', '{'])
def test_malformed_or_duplicate_json_is_refused(personal_environment, data):
    response = personal_environment.client.post(LIST_PATH, data=data, content_type="application/json")
    assert response.status_code == 400


def test_reads_reject_body_and_query_parameters(personal_environment):
    env = personal_environment
    for options in ({"query_string": {"user_id": "other"}}, {"json": {"name": "bad"}}):
        response = env.client.get(LIST_PATH, **options)
        assert response.status_code == 400


@pytest.mark.parametrize("workspace,sk,sync,status", [
    (False, True, True, 403), (True, False, False, 403),
    (True, False, True, 200), (True, True, False, 200),
])
def test_routes_revalidate_availability(personal_environment, workspace, sk, sync, status):
    env = personal_environment
    env.settings.update(enable_user_workspace=workspace, enable_semantic_kernel=sk)
    env.state.file_sync_enabled = sync
    response = env.client.get(LIST_PATH)
    assert response.status_code == status


def test_unauthenticated_and_non_user_requests_are_refused(personal_environment):
    env = personal_environment
    as_user(env, "owner", roles=())
    denied = env.client.post(LIST_PATH, json={"name": "No permission"})
    assert denied.status_code == 403
    with env.client.session_transaction() as session:
        session.clear()
    anonymous = env.client.get(LIST_PATH)
    assert anonymous.status_code in (302, 401)
    assert not env.personal_container.records


def test_raw_provider_error_is_not_returned_or_logged(personal_environment, monkeypatch):
    env = personal_environment
    created = create_identity(env)

    def fail(**kwargs):
        raise RuntimeError("provider-password=must-not-leak")

    monkeypatch.setattr(env.personal_container, "replace_item", fail)
    response = env.client.patch(f"{LIST_PATH}/{created['id']}", json={"expected_etag": created["etag"], "name": "Changed"})
    assert response.status_code == 500
    assert response.get_json() == {"error": "Unable to complete the workspace identity request."}
    logged = env.personal_access.log_event.call_args
    assert logged.args == ("[WORKSPACE_IDENTITY] Native personal identity request failed.",)
    assert logged.kwargs["extra"] == {"error_type": "RuntimeError"}


@pytest.mark.parametrize("method", ["post", "patch", "delete"])
def test_disabled_workspace_rejects_writes_without_mutating(personal_environment, method):
    env = personal_environment
    created = create_identity(env)
    before = deepcopy(env.personal_container.records)
    env.settings["enable_user_workspace"] = False
    path = LIST_PATH if method == "post" else f"{LIST_PATH}/{created['id']}"
    body = {"name": "Refused", "credentials": {"secret": "refused-secret"}} if method == "post" else {"expected_etag": created["etag"]}
    response = getattr(env.client, method)(path, json=body)
    assert response.status_code == 403
    assert env.personal_container.records == before


def test_native_created_identity_is_consumed_without_storing_secrets_in_actions(personal_environment):
    env = personal_environment
    env.settings["enable_key_vault_secret_storage"] = True
    created = create_identity(
        env, credentials={"auth_type": "username_password", "username": "svc", "password": "native-password"},
        usage_contexts=["file_sync", "action"],
    )
    stored = env.identities.get_workspace_identity("personal", "owner", created["id"])
    eligible = env.identities.identity_supports_usage(
        stored, "file_sync", source_type="smb", auth_types={"username_password"},
    )
    assert eligible
    action = {"type": "yamcs", "identity_id": created["id"], "auth": {"type": "identity", "identity": created["id"]}}
    original = deepcopy(action)
    projected = env.identities.hydrate_action_identity_reference(action, "personal", "owner")
    runtime = env.identities.hydrate_action_identity_reference(
        action, "personal", "owner", env.keyvault.SecretReturnType.VALUE,
    )
    assert "native-password" not in json.dumps(projected)
    assert runtime["auth"]["key"] == "native-password"
    assert action == original


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
