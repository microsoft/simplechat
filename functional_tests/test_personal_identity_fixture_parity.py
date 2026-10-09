# test_personal_identity_fixture_parity.py
"""
Real-route parity for the personal identity browser fixture.
Version: 0.261.315
Implemented in: 0.261.315

Checks every native route, credential method, conflict, and reference refusal.
"""

import sys
from pathlib import Path

import pytest

# The existing UI fixtures use top-level imports from these test helper directories.
ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT, ROOT / "ui_tests", ROOT / "ui_tests" / "fixtures"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from test_public_identity_fixture_parity import (
    CREDENTIALS_UI_KEYS, _FakePage, assert_error_code, assert_nested_parity,
    assert_no_invented_keys, drive_fixture,
)
from test_support.personal_identity_harness import (
    LIST_PATH, create_identity, group_environment, personal_environment,  # noqa: F401
)
from ui_tests.fixtures.personal_identities import PersonalIdentitiesFixture, SAVED_ID


ITEM_KEYS = {
    "id", "user_id", "scope_type", "etag", "identity_actions",
    "name", "description", "usage_contexts", "credentials",
}


def check_response(real, result, *, status, envelope=None, error_code=None):
    fixture_status, fixture_payload = result
    real_payload = real.get_json()
    assert real.status_code == fixture_status == status
    assert_no_invented_keys("personal response", fixture_payload, real_payload)
    assert_error_code("personal response", fixture_payload, real_payload, error_code)
    if envelope:
        fixture_item, real_item = fixture_payload[envelope], real_payload[envelope]
        if envelope == "identities":
            fixture_item, real_item = fixture_item[0], real_item[0]
        assert_nested_parity("personal item", fixture_item, real_item, ITEM_KEYS)
        assert_nested_parity("personal credentials", fixture_item["credentials"], real_item["credentials"], CREDENTIALS_UI_KEYS)
        assert fixture_item["scope_type"] == real_item["scope_type"] == "personal"
        assert fixture_item["credentials"]["auth_type"] == real_item["credentials"]["auth_type"]
    return fixture_payload


@pytest.mark.parametrize("method", ["list", "read"])
def test_personal_read_projection_matches_backend(personal_environment, method):
    env = personal_environment
    created = create_identity(env)
    fixture = PersonalIdentitiesFixture(_FakePage())
    real_path = LIST_PATH if method == "list" else f"{LIST_PATH}/{created['id']}"
    fixture_path = LIST_PATH if method == "list" else f"{LIST_PATH}/{SAVED_ID}"
    response = env.client.get(real_path)
    result = drive_fixture(fixture, "GET", fixture_path)
    check_response(response, result, status=200, envelope="identities" if method == "list" else "identity")


@pytest.mark.parametrize("auth_type", [
    "api_key", "bearer_token", "client_secret", "connection_string",
    "username_password", "managed_identity", "anonymous",
])
def test_personal_create_and_update_shapes_match_backend(personal_environment, auth_type):
    env = personal_environment
    fixture = PersonalIdentitiesFixture(_FakePage())
    credentials = {"auth_type": auth_type}
    if auth_type == "username_password":
        credentials.update(username="svc", password="fixture-password", domain="CORP")
    elif auth_type == "client_secret":
        credentials.update(client_id="client", tenant_id="tenant", secret="fixture-value")
    elif auth_type not in ("managed_identity", "anonymous"):
        credentials["secret"] = "fixture-value"
    body = {
        "name": "New identity", "usage_contexts": ["file_sync" if auth_type == "anonymous" else "action"],
        "credentials": credentials,
    }
    response = env.client.post(LIST_PATH, json=body)
    result = drive_fixture(fixture, "POST", LIST_PATH, body)
    payload = check_response(response, result, status=201, envelope="identity")
    real_item, fixture_item = response.get_json()["identity"], payload["identity"]
    changes = {"name": "Renamed", "credentials": {"auth_type": auth_type, "secret": "", "password": ""}}
    response = env.client.patch(f"{LIST_PATH}/{real_item['id']}", json={**changes, "expected_etag": real_item["etag"]})
    result = drive_fixture(fixture, "PATCH", f"{LIST_PATH}/{fixture_item['id']}", {**changes, "expected_etag": fixture_item["etag"]})
    check_response(response, result, status=200, envelope="identity")


@pytest.mark.parametrize("method", ["PATCH", "DELETE"])
@pytest.mark.parametrize("token,status", [(None, 400), ("stale", 409), ("current", 200)])
def test_personal_mutation_statuses_match_backend(personal_environment, method, token, status):
    env = personal_environment
    created = create_identity(env)
    fixture = PersonalIdentitiesFixture(_FakePage())
    real_token = created["etag"] if token == "current" else token
    fixture_token = fixture.identities[SAVED_ID]["etag"] if token == "current" else token
    real_body = {"expected_etag": real_token} if token is not None else {}
    fixture_body = {"expected_etag": fixture_token} if token is not None else {}
    response = env.client.open(f"{LIST_PATH}/{created['id']}", method=method, json=real_body)
    result = drive_fixture(fixture, method, f"{LIST_PATH}/{SAVED_ID}", fixture_body)
    check_response(
        response, result, status=status,
        envelope="identity" if method == "PATCH" and status == 200 else None,
        error_code="etag_conflict" if status == 409 else None,
    )


@pytest.mark.parametrize("method", ["GET", "PATCH", "DELETE"])
def test_personal_missing_item_matches_backend(personal_environment, method):
    env = personal_environment
    fixture = PersonalIdentitiesFixture(_FakePage())
    body = {"expected_etag": "removed"} if method != "GET" else None
    response = env.client.open(f"{LIST_PATH}/removed", method=method, **({"json": body} if body else {}))
    result = drive_fixture(fixture, method, f"{LIST_PATH}/removed", body)
    check_response(response, result, status=404)


def test_personal_in_use_delete_reference_shape(personal_environment):
    env = personal_environment
    created = create_identity(env)
    env.state.personal_actions = [{"id": "connector", "name": "Connector", "identity_id": created["id"]}]
    fixture = PersonalIdentitiesFixture(_FakePage())
    fixture.identity_references[SAVED_ID] = [{"kind": "action", "id": "connector", "name": "Connector"}]
    response = env.client.delete(f"{LIST_PATH}/{created['id']}", json={"expected_etag": created["etag"]})
    result = drive_fixture(fixture, "DELETE", f"{LIST_PATH}/{SAVED_ID}", {"expected_etag": fixture.identities[SAVED_ID]["etag"]})
    payload = check_response(response, result, status=409, error_code="identity_in_use")
    assert_nested_parity("personal reference", payload["references"][0], response.get_json()["references"][0], {"kind", "id", "name"})
