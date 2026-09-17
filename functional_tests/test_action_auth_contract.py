# test_action_auth_contract.py
"""Functional regressions for the lightweight per-user action contract.

Version: 0.261.107
Implemented in: 0.261.107

Validates stable server-owned IDs, strict credential sources, registered profiles,
safe HTTPS recipient fingerprints, and unchanged legacy manifests.
"""

import importlib.util
import sys
import uuid
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pytest


APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
SPEC = importlib.util.spec_from_file_location("_action_auth_contract_tests", APP_ROOT / "functions_action_auth.py")
AUTH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUTH)


def action(profile="yamcs_login"):
    return {
        "id": str(uuid.uuid4()), "name": "Telemetry", "type": "yamcs",
        "endpoint": "https://yamcs.example",
        "auth": {"type": "username_password"},
        "additionalFields": {"instance": "simulator", "tls_verify": True},
        "credential_requirement": {"source": "current_user", "identity_name": "Yamcs", "profile": profile},
    }


def test_pure_contract_does_not_bootstrap_storage():
    with patch.dict(sys.modules, {"config": None, "functions_keyvault": None, "functions_workspace_identities": None}):
        spec = importlib.util.spec_from_file_location("_isolated_auth_contract", APP_ROOT / "functions_action_auth.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.validate_action_credential_requirement(action())
        assert module.normalize_action_credential_requirement(action())["credential_requirement"].get("id") is None


@pytest.mark.parametrize("legacy", [
    {"type": "yamcs", "auth": {"type": "NoAuth"}, "endpoint": "http://localhost:8090"},
    {"type": "yamcs", "identity_id": "global-identity", "auth": {"type": "identity"}},
    {"type": "openapi", "auth": {"type": "key", "key": "legacy-secret"}},
])
def test_legacy_manifests_unchanged_and_copied(legacy):
    copy = AUTH.normalize_action_credential_requirement(legacy, assign_id=True)
    assert copy == legacy and copy is not legacy
    AUTH.validate_action_credential_requirement(legacy, scope_type="personal")
    assert AUTH.get_action_credential_requirement(legacy) is None


@pytest.mark.parametrize("profile,native,identity,method", [
    ("yamcs_login", "username_password", "username_password", "username_password"),
    ("http_basic", "basic", "username_password", "http_basic"),
    ("bearer_token", "key", "bearer_token", "bearer_token"),
    ("api_key", "key", "api_key", "api_key"),
])
def test_profile_is_authoritative(profile, native, identity, method):
    original = action(profile)
    original["additionalFields"]["auth_method"] = "old-value"
    result = AUTH.normalize_action_credential_requirement(original, assign_id=True)
    assert result["auth"] == {"type": native}
    assert result["additionalFields"]["auth_method"] == method
    assert AUTH.ACTION_AUTH_PROFILES[profile]["auth_type"] == identity
    assert "id" not in original["credential_requirement"]
    assert uuid.UUID(result["credential_requirement"]["id"])


def test_id_survives_edits_and_label_rename_but_is_not_client_assignable():
    saved = AUTH.normalize_action_credential_requirement(action(), assign_id=True)
    draft = deepcopy(saved)
    draft["name"] = "Renamed action"
    draft["credential_requirement"].pop("id")
    draft["credential_requirement"]["identity_name"] = "Mission login"
    result = AUTH.normalize_action_credential_requirement(draft, saved, assign_id=True)
    assert result["credential_requirement"]["id"] == saved["credential_requirement"]["id"]
    forged = deepcopy(draft)
    forged["credential_requirement"]["id"] = str(uuid.uuid4())
    with pytest.raises(ValueError, match="cannot be changed"):
        AUTH.normalize_action_credential_requirement(forged, saved, assign_id=True)
    with pytest.raises(ValueError, match="assigned by the server"):
        AUTH.normalize_action_credential_requirement(forged, assign_id=True)


@pytest.mark.parametrize("scope", ["personal", "user", "group", "public"])
def test_scoped_authoring_cannot_use_current_user_requirement(scope):
    with pytest.raises(ValueError):
        AUTH.validate_action_credential_requirement(action(), scope_type=scope)


@pytest.mark.parametrize("change", [
    {"credential_requirement": None},
    {"credential_requirement": {"source": "action_owner", "identity_name": "Yamcs", "profile": "yamcs_login"}},
    {"credential_requirement": {"source": "current_user", "identity_name": "Yamcs", "profile": "oauth"}},
    {"credential_requirement": {"source": "current_user", "identity_name": "Yamcs", "profile": ["http_basic"]}},
    {"credential_requirement": {"source": "current_user", "identity_name": "Yamcs", "profile": {"type": "http_basic"}}},
    {"credential_requirement": {"source": "current_user", "identity_name": "Yamcs", "profile": "yamcs_login", "schema": {}}},
    {"credential_requirement": {"source": "current_user", "identity_name": "Yamcs", "profile": "yamcs_login", "id": "not-a-uuid"}},
    {"user_id": "someone-else"},
    {"is_group": True},
    {"scope": "personal"},
    {"type": "openapi"},
])
def test_invalid_requirement_never_falls_back(change):
    with pytest.raises(ValueError):
        AUTH.normalize_action_credential_requirement({**action(), **change})


@pytest.mark.parametrize("field", ["identity_id", "password", "username", "api_key", "token", "secret", "headers", "password_secret_name"])
def test_inline_credentials_and_references_rejected(field):
    for location in ("auth", "additionalFields", None):
        draft = action()
        (draft[location] if location else draft)[field] = "private-value"
        with pytest.raises(ValueError) as error:
            AUTH.normalize_action_credential_requirement(draft)
        assert "private-value" not in str(error.value)


def test_nested_and_case_variant_credentials_cannot_hide_in_additional_fields():
    for fields in ({"Password": "private-value"}, {"gateway": {"auth": {"key": "private-value"}}}):
        draft = action()
        draft["additionalFields"].update(fields)
        with pytest.raises(ValueError):
            AUTH.validate_action_credential_requirement(draft)


@pytest.mark.parametrize("url", [
    "http://yamcs.example", "https://name:password@yamcs.example", "https://yamcs.example/?token=private",
    "https://yamcs.example/#private", "https://yamcs.example:0", "https://yamcs.example:65536",
    "https://yamcs.example/a/../b", "https://yamcs.example/%2e%2e/x", "https://yamcs.example/a%2fb",
    "https://yamcs.example/%252e%252e/x", "https://yamcs.example/a%252fb",
    "https://yamcs.example/a\\b", "https://yamcs.example/\n", "https://", "file://yamcs.example",
])
def test_recipient_rejects_unsafe_or_ambiguous_urls(url):
    with pytest.raises(ValueError):
        AUTH.validate_action_credential_requirement({**action(), "endpoint": url})


def test_destination_and_profile_fingerprints_are_stable_but_separate():
    original = action()
    canonical = deepcopy(original)
    canonical["endpoint"] = "https://YAMCS.EXAMPLE:443/"
    canonical["name"] = "Renamed action"
    canonical["credential_requirement"]["identity_name"] = "New label"
    assert AUTH.action_auth_fingerprint(original) == AUTH.action_auth_fingerprint(canonical)
    for destination in ("https://other.example", "https://yamcs.example:8443", "https://yamcs.example/gateway"):
        assert AUTH.action_auth_fingerprint({**original, "endpoint": destination}) != AUTH.action_auth_fingerprint(original)
    basic = action("http_basic")
    assert AUTH.action_auth_fingerprint(basic) != AUTH.action_auth_fingerprint(original)
    bad = deepcopy(original)
    bad["additionalFields"]["tls_verify"] = False
    with pytest.raises(ValueError):
        AUTH.validate_action_credential_requirement(bad)
    bad["additionalFields"] = {"server_url": "https://other.example"}
    with pytest.raises(ValueError, match="destinations must agree"):
        AUTH.validate_action_credential_requirement(bad)


def test_control_signal_has_only_registered_input_fields_and_no_credentials():
    error = AUTH.ActionCredentialsRequired({
        "request_id": "opaque", "shared_conversation": True, "password": "private-value",
        "requirements": [{
            "id": str(uuid.uuid4()), "profile": "yamcs_login", "identity_name": "Yamcs",
            "fields": [{"name": "secret-exfiltration"}], "password": "private-value",
            "identities": [{"id": "own", "name": "Yamcs", "auth_type": "username_password", "password": "private-value"}],
        }],
    }, action_ref="canonical-action")
    payload = error.to_payload()
    assert payload["error_code"] == "action_credentials_required"
    assert payload["sharing_notice"] == AUTH.ACTION_AUTH_SHARING_NOTICE
    assert {field["name"] for field in payload["requirements"][0]["fields"]} == {"username", "password"}
    assert "private-value" not in str(payload)
    payload["requirements"].clear()
    assert error.auth_response["requirements"]


def test_control_signal_drops_nested_objects_and_credential_bearing_destinations():
    error = AUTH.ActionCredentialsRequired({
        "request_id": {"password": "private-value"},
        "requirements": [{
            "profile": "yamcs_login", "action_name": {"password": "private-value"},
            "destination": "https://user:private-value@yamcs.example",
            "identities": [{"id": {"password": "private-value"}, "name": "Yamcs"}],
        }],
    })
    assert "private-value" not in str(error.to_payload())
