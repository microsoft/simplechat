# test_v2_personal_endpoints_api.py
"""
Functional tests for native V2 personal endpoint editing.
Version: 0.261.315
Implemented in: 0.261.315

Exercise real registered personal routes, normalization, and Key Vault helpers
through the existing offline harness. Network I/O is blocked and injected state
is restored after every test.
"""

import copy
import json

import pytest

from test_support.group_endpoint_harness import (
    aoai_endpoint,
    foundry_endpoint,
    group_endpoint_environment,
)


BASE = "/api/user/model-endpoints"


@pytest.fixture(scope="module")
def environment():
    with group_endpoint_environment() as env:
        yield env


@pytest.fixture
def personal(environment):
    environment.reset()
    endpoint = aoai_endpoint(
        "personal-one", contextWindow=128000, inputTokenLimit=64000,
        outputTokenLimit=16000, tokenLimitProvider="azure",
        outputTokenAccounting="total_generation",
    )
    endpoint["models"][0].update({
        "contextWindow": 100000, "inputTokenLimit": 60000,
        "outputTokenLimit": 10000, "catalogModelId": "gpt-4o",
        "modelVersion": "2024-08-06", "tokenLimitProvider": "azure",
        "outputTokenAccounting": "total_generation", "responseLength": 512,
        "description": "Keep this model", "icon": {"kind": "bootstrap", "value": "bi-stars"},
        "metadata": {"retain": False},
    })
    environment.seed_personal_endpoints("owner", [endpoint])
    environment.seed_personal_endpoints("other-user", [aoai_endpoint("private-other")])
    environment.vault.writes.clear()
    yield environment
    environment.reset()


def read_endpoint(env):
    response = env.call("GET", f"{BASE}/personal-one")
    assert response.status_code == 200
    return response.get_json()["endpoint"]


def test_personal_list_exposes_registry_not_settings_or_credentials(personal):
    response = personal.call("GET", BASE)
    assert response.status_code == 200
    payload = response.get_json()
    assert set(payload) == {"endpoints", "custom_api_types"}
    assert {entry["value"] for entry in payload["custom_api_types"]} == {
        "openai", "azure_openai", "anthropic", "gemini",
    }
    assert [entry["id"] for entry in payload["endpoints"]] == ["personal-one"]
    assert payload["endpoints"][0]["has_api_key"] is True
    assert "api_key" not in payload["endpoints"][0]["auth"]
    assert "sk-plain" not in json.dumps(payload)
    assert "--model-endpoint--" not in json.dumps(payload)


def test_native_create_edit_reopen_and_secret_rotation(personal):
    payload = aoai_endpoint("", api_key="new-test-only-key")
    response = personal.call("POST", BASE, payload)
    assert response.status_code == 201
    created = response.get_json()["endpoint"]
    assert created["id"] and created["has_api_key"]
    assert "api_key" not in created["auth"]
    created["name"] = "Renamed native endpoint"
    updated = personal.call("PATCH", f"{BASE}/{created['id']}", created)
    assert updated.status_code == 200
    assert updated.get_json()["endpoint"]["name"] == created["name"]
    stored = personal.personal_endpoint("owner", created["id"])
    assert personal.vault.secrets[stored["auth"]["api_key"]] == "new-test-only-key"
    rotated = personal.call("PATCH", f"{BASE}/{created['id']}", {"auth": {"api_key": "replacement-test-only-key"}})
    assert rotated.status_code == 200
    stored = personal.personal_endpoint("owner", created["id"])
    assert personal.vault.secrets[stored["auth"]["api_key"]] == "replacement-test-only-key"


def test_blank_secret_edit_and_toggle_preserve_all_metadata(personal):
    payload = read_endpoint(personal)
    original = copy.deepcopy(personal.personal_endpoint("owner", "personal-one"))
    payload["name"] = "Personal renamed"
    payload["auth"]["api_key"] = ""
    response = personal.call("PATCH", f"{BASE}/personal-one", payload)
    assert response.status_code == 200
    toggled = personal.call("PATCH", f"{BASE}/personal-one", {"enabled": False})
    assert toggled.status_code == 200
    stored = personal.personal_endpoint("owner", "personal-one")
    assert stored["auth"]["api_key"] == original["auth"]["api_key"]
    assert stored["models"] == original["models"]
    assert stored["contextWindow"] == original["contextWindow"]
    assert personal.vault.writes == []


def test_explicit_nulls_restore_capacity_and_response_inheritance(personal):
    payload = read_endpoint(personal)
    for key in ("contextWindow", "inputTokenLimit", "outputTokenLimit", "tokenLimitProvider", "outputTokenAccounting"):
        payload[key] = None
        payload["models"][0][key] = None
    payload["models"][0].update({"catalogModelId": None, "modelVersion": None, "responseLength": None})
    response = personal.call("PATCH", f"{BASE}/personal-one", payload)
    assert response.status_code == 200
    saved = response.get_json()["endpoint"]
    assert saved["contextWindow"] is None
    assert saved["models"][0]["contextWindow"] is None
    assert saved["models"][0]["catalogModelId"] is None
    assert "responseLength" not in saved["models"][0]
    assert saved["models"][0]["description"] == "Keep this model"
    assert saved["models"][0]["icon"] == {"kind": "bootstrap", "value": "bi-stars"}


@pytest.mark.parametrize("value", [True, 0, -1, 1.5, "1e3", "9007199254740992"])
@pytest.mark.parametrize("target", ["endpoint", "model"])
def test_invalid_capacity_fails_before_persistence(personal, value, target):
    before = copy.deepcopy(personal.user_settings)
    payload = {"contextWindow": value}
    if target == "model":
        payload = read_endpoint(personal)
        payload["models"][0]["contextWindow"] = value
    response = personal.call("PATCH", f"{BASE}/personal-one", payload)
    assert response.status_code == 400
    assert response.get_json()["error_code"] == "model_context_invalid"
    assert personal.user_settings == before
    assert personal.vault.writes == []


@pytest.mark.parametrize("method", ["GET", "PATCH", "DELETE"])
def test_other_users_endpoint_is_not_accessible(personal, method):
    response = personal.call(method, f"{BASE}/private-other", {} if method == "PATCH" else None)
    assert response.status_code == 404
    assert personal.personal_endpoint("other-user", "private-other") is not None


def test_governance_denial_blocks_reads_and_writes(personal):
    personal.denied_features.add("governance_user_endpoints")
    for method, path, body in [
        ("GET", BASE, None), ("POST", BASE, aoai_endpoint("blocked")),
        ("PATCH", f"{BASE}/personal-one", {"name": "blocked"}),
        ("DELETE", f"{BASE}/personal-one", None),
    ]:
        response = personal.call(method, path, body)
        assert response.status_code == 403
    assert personal.personal_endpoint("owner", "personal-one")["name"] != "blocked"
    assert personal.vault.writes == []


def test_feature_disabled_blocks_personal_management(personal):
    personal.settings["allow_user_custom_endpoints"] = False
    for method, path, body in [
        ("GET", BASE, None), ("POST", BASE, aoai_endpoint("blocked")),
        ("PATCH", f"{BASE}/personal-one", {"enabled": False}),
        ("DELETE", f"{BASE}/personal-one", None),
    ]:
        response = personal.call(method, path, body)
        assert response.status_code == 400
        assert response.get_json() == {"error": "Allow User Custom Endpoints is disabled."}
    assert personal.personal_endpoint("owner", "personal-one")["enabled"] is True
    assert personal.vault.writes == []


def test_independent_maxima_and_trimmed_model_identity_are_preserved(personal):
    payload = read_endpoint(personal)
    payload.update({"contextWindow": 1000, "inputTokenLimit": 900, "outputTokenLimit": 900})
    payload["models"][0].update({
        "contextWindow": 1000, "inputTokenLimit": 900, "outputTokenLimit": 900,
        "catalogModelId": " \t" + "x" * 256 + "\n ", "modelVersion": " snapshot ",
    })
    response = personal.call("PATCH", f"{BASE}/personal-one", payload)
    assert response.status_code == 200, response.get_json()
    saved = response.get_json()["endpoint"]
    assert saved["inputTokenLimit"] + saved["outputTokenLimit"] > saved["contextWindow"]
    assert saved["models"][0]["catalogModelId"] == "x" * 256
    assert saved["models"][0]["modelVersion"] == "snapshot"


def test_delete_removes_only_one_endpoint_and_its_credential(personal):
    original_secret = personal.personal_endpoint("owner", "personal-one")["auth"]["api_key"]
    response = personal.call("DELETE", f"{BASE}/personal-one")
    assert response.status_code == 200 and response.get_json() == {"success": True}
    assert personal.personal_endpoint("owner", "personal-one") is None
    assert personal.personal_endpoint("other-user", "private-other") is not None
    assert original_secret in personal.vault.deletes


def test_existing_chat_test_uses_saved_binding_not_draft_overrides(personal):
    payload = read_endpoint(personal)
    payload["connection"]["endpoint"] = "https://different.openai.azure.com"
    payload["auth"]["api_key"] = "draft-test-only-key"
    payload["model"] = payload["models"][0]
    response = personal.call("POST", "/api/user/models/test-model", payload)
    assert response.status_code == 200
    assert personal.chat_clients[-1]["endpoint"] == "https://group-a.openai.azure.com"
    assert personal.chat_clients[-1]["auth"]["api_key"] == "sk-plain"


def test_stored_disabled_model_is_not_testable(personal):
    payload = read_endpoint(personal)
    payload["models"][0]["enabled"] = False
    updated = personal.call("PATCH", f"{BASE}/personal-one", payload)
    assert updated.status_code == 200
    response = personal.call("POST", "/api/user/models/test-model", {
        "endpoint_id": "personal-one", "model": {"id": "chat"},
    })
    assert response.status_code == 404
    assert personal.chat_clients == []


def test_new_draft_chat_and_foundry_discovery(personal):
    draft = aoai_endpoint("", api_key="draft-only-key")
    draft["model"] = draft["models"][0]
    tested = personal.call("POST", "/api/user/models/test-model", draft)
    assert tested.status_code == 200
    assert personal.chat_clients[-1]["auth"]["api_key"] == "draft-only-key"
    foundry = foundry_endpoint("")
    discovered = personal.call("POST", "/api/user/models/fetch", foundry)
    assert discovered.status_code == 200
    assert discovered.get_json()["models"][0]["deploymentName"] == "gpt-4o"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
