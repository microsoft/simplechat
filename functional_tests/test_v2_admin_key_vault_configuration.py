# test_v2_admin_key_vault_configuration.py
"""
Functional regressions for V2 Key Vault configuration.
Version: 0.261.396
Implemented in: 0.261.396

Pin the production field metadata that keeps the storage switch reachable and
opens an incomplete connection. Exercise the real settings normalizer and secret
redaction helpers without contacting Azure or modifying persisted settings.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_support.app_stubs import import_app_module  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402


fields_module = import_app_module("admin_settings_fields")
secret_utils = import_app_module("admin_settings_secret_utils")
STORAGE_KEY = "enable_key_vault_secret_storage"
VAULT_NAME = "v2-test-vault"
CLIENT_ID = "11111111-2222-3333-4444-555555555555"


def test_key_vault_capability_is_not_inside_a_collapsed_group():
    assert_app_version_at_least("0.261.396")
    field = fields_module.get_field_definition(STORAGE_KEY)
    assert field["type"] == "switch"
    assert field["role"] == "capability"
    assert not field.get("group")
    assert not field.get("depends_on")
    assert field["default"] is False
    assert field["notice_level"] == "warning"
    assert "effectively one-way" in field["notice"]


def test_key_vault_connection_metadata_reveals_the_existing_controls():
    section = fields_module.get_admin_settings_fields()["keyvault-section"]
    connection = [
        field for field in section
        if field.get("key") in {"key_vault_name", "key_vault_identity"}
        or field.get("test_type") == "key_vault"
    ]
    assert len(connection) == 3
    for field in connection:
        assert field["group"] == {
            "id": "vault-connection", "label": "Vault connection", "variant": "connection",
        }
        assert field["depends_on"] == {"key": STORAGE_KEY, "equals": True}
        assert not field.get("legacy")

    name = fields_module.get_field_definition("key_vault_name")
    identity = fields_module.get_field_definition("key_vault_identity")
    assert name["required"] is True
    assert name["type"] == identity["type"] == "text"
    assert not identity.get("required")
    test = next(field for field in connection if field.get("test_type") == "key_vault")
    assert test["component"] == "connection-test"
    assert test["test_payload"] == {
        "vault_name": {"key": "key_vault_name"},
        "client_id": {"key": "key_vault_identity"},
    }


@pytest.mark.parametrize("client_id", ["", CLIENT_ID])
def test_enabling_saves_the_vault_name_and_optional_identity(client_id):
    normalized, errors, warnings = fields_module.normalize_admin_settings_updates({
        STORAGE_KEY: True,
        "key_vault_name": f"  {VAULT_NAME}  ",
        "key_vault_identity": f"  {client_id}  ",
    }, {STORAGE_KEY: False})
    assert not errors
    assert not warnings
    assert normalized == {
        STORAGE_KEY: True, "key_vault_name": VAULT_NAME, "key_vault_identity": client_id,
    }


@pytest.mark.parametrize("enabled", [None, False, True], ids=["baseline", "disabled", "enabled"])
def test_partial_updates_do_not_clear_or_invent_vault_configuration(enabled):
    current = {} if enabled is None else {
        STORAGE_KEY: enabled, "key_vault_name": VAULT_NAME, "key_vault_identity": CLIENT_ID,
    }
    original = dict(current)
    updates = {"enable_search_result_caching": False}
    normalized, errors, _ = fields_module.normalize_admin_settings_updates(updates, current)
    assert not errors
    assert normalized == updates
    assert current == original

    disabled, errors, _ = fields_module.normalize_admin_settings_updates({STORAGE_KEY: False}, current)
    assert not errors
    assert disabled == {STORAGE_KEY: False}


def test_an_identity_can_be_cleared_without_changing_the_vault():
    current = {
        STORAGE_KEY: True, "key_vault_name": VAULT_NAME, "key_vault_identity": CLIENT_ID,
    }
    normalized, errors, _ = fields_module.normalize_admin_settings_updates(
        {"key_vault_identity": ""}, current,
    )
    assert not errors
    assert normalized == {"key_vault_identity": ""}
    assert current["key_vault_name"] == VAULT_NAME
    assert current[STORAGE_KEY] is True


def test_vault_configuration_is_not_a_credential_but_secrets_stay_redacted():
    current = {
        STORAGE_KEY: True,
        "key_vault_name": VAULT_NAME,
        "key_vault_identity": CLIENT_ID,
        "content_safety_key": "existing-test-credential",
    }
    redacted = secret_utils.redact_admin_settings_secrets_for_api(current)
    assert redacted[STORAGE_KEY] is True
    assert redacted["key_vault_name"] == VAULT_NAME
    assert redacted["key_vault_identity"] == CLIENT_ID
    assert redacted["content_safety_key"] == secret_utils.ADMIN_SETTINGS_SECRET_REDACTED_VALUE
    assert current["content_safety_key"] == "existing-test-credential"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__]))
