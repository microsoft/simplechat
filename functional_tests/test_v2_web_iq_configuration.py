# test_v2_web_iq_configuration.py
"""Web IQ V2 configuration, consent and secret regression tests.

Version: 0.261.405
Implemented in: 0.261.405

Uses the real schema and Web IQ validator with only app bootstrap/external I/O stubbed.
"""

import json
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

from test_support.app_stubs import import_app_module, stubbed_app_imports
from test_web_search_admin_connection_test import load_module_with_stubs


APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
FIELDS = import_app_module("admin_settings_fields")
SECRETS = import_app_module("admin_settings_secret_utils")
MASK = SECRETS.ADMIN_SETTINGS_SECRET_REDACTED_VALUE


def test_nested_connection_preserves_inactive_fields_and_masks():
    current = {
        "web_search_provider": "foundry",
        "web_iq": {"key": "saved-key", "client_secret": "saved-secret", "client_id": "saved-client"},
        "web_search_agent": {"other_settings": {"azure_ai_foundry": {"client_secret": "foundry-secret"}}},
    }
    with stubbed_app_imports():
        normalized, errors, _ = FIELDS.normalize_admin_settings_updates({
            "web_search_provider": "web_iq", "web_iq_key": MASK,
            "web_iq_client_secret": MASK, "web_iq_region": "GB",
        }, current)
    assert not errors
    assert normalized["web_iq"]["key"] == "saved-key"
    assert normalized["web_iq"]["client_secret"] == "saved-secret"
    assert normalized["web_iq"]["client_id"] == "saved-client"
    assert normalized["web_iq"]["region"] == "GB"
    masked = SECRETS.redact_admin_settings_secrets_for_form({**current, **normalized})
    assert masked["web_iq"]["key"] == MASK
    assert masked["web_iq"]["client_secret"] == MASK
    assert masked["web_search_agent"]["other_settings"]["azure_ai_foundry"]["client_secret"] == MASK
    assert "saved-key" not in json.dumps(masked)
    assert current["web_iq"]["key"] == "saved-key"


def test_nested_object_and_flat_field_merge_and_clear_secret():
    with stubbed_app_imports():
        normalized, errors, _ = FIELDS.normalize_admin_settings_updates({
            "web_iq": {"key": MASK, "region": "CA"},
            "web_iq_client_secret": "",
        }, {"web_iq": {"key": "original", "client_secret": "delete-me", "app_id": "keep"}})
    assert not errors
    assert normalized["web_iq"] == {
        "key": "original", "region": "CA", "client_secret": "", "app_id": "keep",
    }


def test_provider_consent_is_separate_and_persisted():
    with stubbed_app_imports():
        rejected, errors, _ = FIELDS.normalize_admin_settings_updates({
            "web_search_provider": "web_iq", "enable_web_search": True,
        }, {"web_search_consent_accepted": True})
        accepted, accepted_errors, _ = FIELDS.normalize_admin_settings_updates({
            "web_search_provider": "web_iq", "enable_web_search": True,
            "web_iq_consent_accepted": True, "web_iq_terms_acknowledged": True,
        }, {})
    assert "web_iq_consent_accepted" in errors
    assert not accepted_errors
    assert accepted["web_iq_consent_accepted"] is True
    assert "web_iq_terms_acknowledged" not in accepted
    assert "web_search_consent_accepted" not in accepted


@pytest.mark.parametrize("updates", [
    {"web_search_provider": "unknown"},
    {"web_iq_image_mode": "embed"},
    {"web_iq_video_mode": "script"},
    {"web_iq_endpoint": "https://attacker.test"},
    {"web_iq_authentication_type": "managed_identity"},
    {"web_iq_language": "english"},
    {"web_iq_region": "USA"},
    {"web_iq": {"unknown": "value"}},
])
def test_invalid_configuration_is_rejected(updates):
    with stubbed_app_imports():
        _, errors, _ = FIELDS.normalize_admin_settings_updates(updates, {"web_search_provider": "web_iq"})
    assert errors


def test_web_iq_admin_test_restores_secrets_and_returns_only_safe_counts():
    module = load_module_with_stubs()
    config = types.ModuleType("config")
    config.AZURE_ENVIRONMENT = "public"
    observed = []

    def search(settings, query, **kwargs):
        observed.append((settings, query, kwargs))
        return {"message": "DO NOT ECHO PROVIDER OUTPUT", "citations": [{"url": "https://example.test"}]}

    with stubbed_app_imports(), patch.dict(sys.modules, {"config": config}):
        result, status = module.run_web_iq_connection_test({
            "enabled": True, "web_iq_consent_accepted": True,
            "web_iq": {"key": MASK}, "query": "test",
        }, global_settings={"web_iq": {"key": "stored-credential"}}, search=search)
    assert status == 200 and result["success"]
    assert observed[0][0]["web_iq"]["key"] == "stored-credential"
    assert observed[0][2]["result_types"] == ["web"]
    assert "stored-credential" not in json.dumps(result)
    assert "DO NOT ECHO" not in json.dumps(result)


@pytest.mark.parametrize("cloud,consent", [("usgovernment", True), ("custom", True), ("public", False)])
def test_admin_test_rejects_cloud_and_missing_consent_before_search(cloud, consent):
    module = load_module_with_stubs()
    config = types.ModuleType("config")
    config.AZURE_ENVIRONMENT = cloud
    calls = []
    with stubbed_app_imports(), patch.dict(sys.modules, {"config": config}):
        result, status = module.run_web_iq_connection_test({
            "enabled": True, "web_iq_consent_accepted": consent,
            "azure_environment": "public", "web_iq": {"key": "key"},
        }, global_settings={}, search=lambda *args, **kwargs: calls.append(args))
    assert status == 400 and not result["success"]
    assert not calls


def test_admin_test_never_echoes_unexpected_errors():
    module = load_module_with_stubs()
    config = types.ModuleType("config")
    config.AZURE_ENVIRONMENT = "public"

    def search(*args, **kwargs):
        raise RuntimeError("sensitive-key-and-response")

    with stubbed_app_imports(), patch.dict(sys.modules, {"config": config}):
        result, status = module.run_web_iq_connection_test({
            "enabled": True, "web_iq_consent_accepted": True, "web_iq": {"key": "key"},
        }, global_settings={}, search=search)
    assert status == 502
    assert "sensitive-key" not in json.dumps(result)
