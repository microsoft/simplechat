# test_deployer_optional_services.py
"""Optional AZD service selection, pending onboarding and CU readiness regressions.

Version: 0.261.405
Implemented in: 0.261.405
Deployer version: 1.0.37
Refs #1887. All service calls are fake; no Azure deployments or paid analyses.
"""

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from azure.core.exceptions import ResourceNotFoundError


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("optional_services_test", ROOT / "deployers" / "bicep" / "optional_services.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
WEB_VALUES = {
    "WEB_SEARCH_PROVIDER": "web_iq", "WEB_SEARCH_TERMS_ACKNOWLEDGED": "true",
    "WEB_IQ_SUBSCRIPTION_ELIGIBLE": "true",
    "var_keyVaultUri": "https://deployment-vault.vault.azure.net/",
    "var_keyVaultName": "deployment-vault",
}
CU_DEFAULTS = {
    "prebuilt-analyzer-completion": "gpt-4.1",
    "prebuilt-analyzer-completion-mini": "gpt-4.1-mini",
    "prebuilt-analyzer-embedding": "text-embedding-3-large",
}
CU_MODELS = [
    {"modelName": name, "modelVersion": version, "skuName": "GlobalStandard", "skuCapacity": 10}
    for name, version in (("gpt-4.1", "2025-04-14"), ("gpt-4.1-mini", "2025-04-14"), ("text-embedding-3-large", "1"))
]
CU_VALUES = {
    "CONTENT_UNDERSTANDING_MODE": "create", "CONTENT_UNDERSTANDING_LOCATION": "eastus2",
    "CONTENT_UNDERSTANDING_MODELS": json.dumps(CU_MODELS),
    "CONTENT_UNDERSTANDING_MODEL_DEFAULTS": json.dumps(CU_DEFAULTS),
    "OPTIONAL_SERVICES_DEPLOYMENT_PRINCIPAL_ID": "runner",
    "AZURE_SUBSCRIPTION_ID": "subscription",
}


class FakeVault:
    def __init__(self, secrets=None):
        self.secrets = dict(secrets or {})
        self.writes = []

    def get_secret(self, name):
        if name not in self.secrets:
            raise ResourceNotFoundError(message="Missing test secret")
        return SimpleNamespace(value=self.secrets[name], properties=SimpleNamespace(enabled=True))

    def set_secret(self, name, value, **attributes):
        self.writes.append(name)
        if name in self.secrets:
            raise AssertionError("A staged or source secret must never be overwritten")
        self.secrets[name] = value
        return self.get_secret(name)


def vault_stager(vault):
    return lambda name, existing, field: MODULE.stage_web_iq_secret(vault, name, existing, field)


@pytest.mark.parametrize("field", ["key", "client_secret"])
def test_secret_staging_is_scoped_immutable_and_idempotent(field):
    vault = FakeVault({"portal-source": "raw-dummy-secret"})
    first = MODULE.stage_web_iq_secret(vault, "portal-source", field=field)
    repeated = MODULE.stage_web_iq_secret(vault, "portal-source", first, field)
    assert first == repeated
    assert MODULE.is_web_iq_secret_reference(first)
    assert vault.writes == [first]
    vault.secrets["portal-source"] = "rotated-dummy-secret"
    rotated = MODULE.stage_web_iq_secret(vault, "portal-source", first, field)
    assert rotated != first
    assert vault.secrets[first] == "raw-dummy-secret"
    assert vault.secrets[rotated] == "rotated-dummy-secret"
    assert vault.secrets["portal-source"] == "rotated-dummy-secret"


def test_existing_scoped_supplied_reference_is_validated_without_rewriting():
    reference = MODULE.WEB_IQ_SECRET_PREFIX + "existing-key"
    vault = FakeVault({reference: "raw-dummy-secret"})
    result = MODULE.stage_web_iq_secret(vault, reference)
    assert result == reference
    assert vault.writes == []
    with pytest.raises(ResourceNotFoundError):
        MODULE.stage_web_iq_secret(vault, MODULE.WEB_IQ_SECRET_PREFIX + "missing")


def test_supplied_secret_from_another_scope_is_copied_not_reused():
    supplied = "other-provider--model-endpoint--global--key"
    vault = FakeVault({supplied: "raw-dummy-secret"})
    result = MODULE.stage_web_iq_secret(vault, supplied)
    assert result != supplied
    assert MODULE.is_web_iq_secret_reference(result)
    assert vault.secrets[supplied] == "raw-dummy-secret"


def test_staging_never_overwrites_a_colliding_generated_name(monkeypatch):
    collision = MODULE.WEB_IQ_SECRET_PREFIX + "key-collision"
    vault = FakeVault({"source": "new-dummy-secret", collision: "existing-dummy-secret"})
    monkeypatch.setattr(MODULE.uuid, "uuid4", lambda: SimpleNamespace(hex="collision"))
    with pytest.raises(ValueError, match="unique staged"):
        MODULE.stage_web_iq_secret(vault, "source")
    assert vault.writes == []
    assert vault.secrets[collision] == "existing-dummy-secret"


def test_staging_preserves_supplied_secret_lifetime_restrictions():
    vault = FakeVault({"source": "raw-dummy-secret"})
    source = vault.get_secret("source")
    source.properties.expires_on = "expires-test-value"
    source.properties.not_before = "not-before-test-value"
    get_secret = vault.get_secret
    vault.get_secret = lambda name: source if name == "source" else get_secret(name)
    set_secret = Mock(wraps=vault.set_secret)
    vault.set_secret = set_secret
    reference = MODULE.stage_web_iq_secret(vault, "source")
    set_secret.assert_called_once_with(
        reference, "raw-dummy-secret", expires_on="expires-test-value", not_before="not-before-test-value",
    )


@pytest.mark.parametrize("settings,overrides", [
    ({"key_vault_name": "other-vault"}, {}),
    ({"enable_key_vault_secret_storage": True}, {}),
    ({}, {"var_keyVaultName": "other-vault"}),
    ({}, {"var_keyVaultUri": "https://deployment-vault.vault.usgovcloudapi.net/"}),
    ({}, {"var_keyVaultUri": "https://deployment-vault.vault.azure.net.evil.example/"}),
    ({}, {"var_keyVaultUri": "https://deployment-vault.vault.azure.net/?secret=unsafe"}),
])
def test_incompatible_vault_context_fails_before_secret_staging(settings, overrides):
    stager = Mock()
    with pytest.raises(ValueError):
        MODULE.configure_optional_settings(
            settings, {**WEB_VALUES, **overrides, "WEB_IQ_KEY_SECRET_NAME": "source"},
            Mock(), stage_secret=stager,
        )
    stager.assert_not_called()


def test_raw_secret_callback_result_cannot_enter_settings():
    settings = {}
    with pytest.raises(ValueError, match="scoped Key Vault reference"):
        MODULE.configure_optional_settings(
            settings, {**WEB_VALUES, "WEB_IQ_KEY_SECRET_NAME": "source"},
            Mock(), stage_secret=Mock(return_value="raw-dummy-secret"),
        )
    assert "raw-dummy-secret" not in json.dumps(settings)


def test_old_environment_preserves_existing_services_and_secrets():
    original = {
        "enable_web_search": True, "web_search_agent": {"external": "keep"},
        "azure_content_understanding_endpoint": "https://configured.services.ai.azure.com",
        "azure_document_intelligence_key": "keep", "web_iq": {"key": "inactive-secret"},
    }
    desired = copy.deepcopy(original)
    MODULE.configure_optional_settings(desired, {}, Mock())
    assert desired == original


@pytest.mark.parametrize("cloud", ["usgovernment", "custom", "AzureUSGovernment", "China"])
@pytest.mark.parametrize("values", [WEB_VALUES, CU_VALUES, {"WEB_SEARCH_PROVIDER": "foundry"}])
def test_incompatible_noninteractive_clouds_fail_before_external_calls(cloud, values):
    query = Mock()
    with pytest.raises(ValueError, match="unavailable"):
        MODULE.preflight({**values, "env_AZURE_CLOUD_ENVIRONMENT": cloud}, query)
    query.assert_not_called()


@pytest.mark.parametrize("key,value", [
    ("WEB_SEARCH_PROVIDER", "auto"), ("CONTENT_UNDERSTANDING_MODE", "false"),
    ("WEB_IQ_NEWS_ENABLED", "on"), ("WEB_IQ_IMAGE_MODE", "media"), ("WEB_IQ_VIDEO_MODE", "auto"),
])
def test_invalid_selections_fail(key, value):
    with pytest.raises(ValueError):
        MODULE.selection({key: value})


def test_web_iq_requires_distinct_deployment_terms_and_paid_access():
    for key in ("WEB_SEARCH_TERMS_ACKNOWLEDGED", "WEB_IQ_SUBSCRIPTION_ELIGIBLE"):
        with pytest.raises(ValueError):
            MODULE.selection({**WEB_VALUES, key: "false"})


@pytest.mark.parametrize("images", MODULE.MEDIA_MODES)
@pytest.mark.parametrize("videos", MODULE.MEDIA_MODES)
@pytest.mark.parametrize("news", ["false", "true"])
def test_pending_web_iq_never_enables_from_terms_or_supplied_credentials(images, videos, news):
    settings = {"enable_web_search": True, "web_search_consent_accepted": True, "web_search_agent": {"keep": "agent"}}
    values = {
        **WEB_VALUES, "WEB_IQ_IMAGE_MODE": images, "WEB_IQ_VIDEO_MODE": videos,
        "WEB_IQ_NEWS_ENABLED": news, "WEB_IQ_KEY_SECRET_NAME": "portal-key",
    }
    vault = FakeVault({"portal-key": "private-key"})
    MODULE.configure_optional_settings(settings, values, Mock(), stage_secret=vault_stager(vault))
    assert settings["enable_web_search"] is False
    assert settings["web_iq_consent_accepted"] is False
    assert MODULE.is_web_iq_secret_reference(settings["web_iq"]["key"])
    assert "private-key" not in json.dumps(settings)
    assert vault.secrets["portal-key"] == "private-key"
    assert settings["enable_key_vault_secret_storage"] is True
    assert settings["key_vault_name"] == "deployment-vault"
    assert settings["web_iq_image_mode"] == images
    assert settings["web_iq_video_mode"] == videos
    assert settings["web_iq_news_enabled"] == (news == "true")
    assert settings["web_search_agent"] == {"keep": "agent"}
    assert settings["web_search_consent_accepted"] is True


def test_repeated_web_iq_configuration_preserves_validated_admin_enablement():
    settings = {}
    MODULE.configure_optional_settings(settings, WEB_VALUES, Mock())
    settings["web_iq"]["key"] = "saved-key"
    settings["web_iq_consent_accepted"] = True
    settings["enable_web_search"] = True
    before = copy.deepcopy(settings)
    MODULE.configure_optional_settings(settings, WEB_VALUES, Mock())
    assert settings == before


def test_changed_credentials_require_fresh_consent_and_test():
    settings = {}
    MODULE.configure_optional_settings(settings, WEB_VALUES, Mock())
    settings["web_iq"].update(key="old-key")
    settings.update(enable_web_search=True, web_iq_consent_accepted=True)
    vault = FakeVault({"replacement": "new-key"})
    MODULE.configure_optional_settings(settings, {**WEB_VALUES, "WEB_IQ_KEY_SECRET_NAME": "replacement"}, Mock(), stage_secret=vault_stager(vault))
    assert settings["enable_web_search"] is False
    assert settings["web_iq_consent_accepted"] is False


@pytest.mark.parametrize("endpoint", ["https://evil.example/v3", "https://api.microsoft.ai.evil/v3", "https://api.microsoft.ai/v3?secret=bad"])
def test_web_iq_endpoint_is_exact(endpoint):
    with pytest.raises(ValueError, match="endpoint"):
        MODULE.configure_optional_settings({}, {**WEB_VALUES, "WEB_IQ_ENDPOINT": endpoint}, Mock())


@pytest.mark.parametrize("key,value", [("WEB_IQ_MAX_RESULTS", "0"), ("WEB_IQ_MAX_RESULTS", "51"), ("WEB_IQ_MAX_LENGTH", "3001")])
def test_web_iq_deployment_limits_match_runtime_contract(key, value):
    with pytest.raises(ValueError):
        MODULE.configure_optional_settings({}, {**WEB_VALUES, key: value}, Mock())


def test_service_principal_without_app_binding_is_disabled():
    settings = {}
    vault = FakeVault({"client-secret": "secret"})
    MODULE.configure_optional_settings(settings, {
        **WEB_VALUES, "WEB_IQ_AUTHENTICATION_TYPE": "service_principal",
        "WEB_IQ_TENANT_ID": "tenant", "WEB_IQ_CLIENT_ID": "client",
        "WEB_IQ_CLIENT_SECRET_SECRET_NAME": "client-secret",
    }, Mock(), stage_secret=vault_stager(vault))
    assert not settings["enable_web_search"]
    assert not settings["web_iq_consent_accepted"]


def test_no_unsupported_foundry_creation_or_runtime_migration():
    with pytest.raises(ValueError, match="not automated"):
        MODULE.selection({"WEB_SEARCH_PROVIDER": "foundry", "WEB_SEARCH_TERMS_ACKNOWLEDGED": "true", "FOUNDRY_RESOURCE_MODE": "create"})


def test_foundry_reuses_agent_but_does_not_automatically_enable():
    settings = {}
    MODULE.configure_optional_settings(settings, {
        "WEB_SEARCH_PROVIDER": "foundry", "WEB_SEARCH_TERMS_ACKNOWLEDGED": "true",
        "FOUNDRY_PROJECT_ENDPOINT": "https://example.services.ai.azure.com/api/projects/existing",
        "FOUNDRY_AGENT_ID": "agent-id",
    }, Mock())
    assert settings["enable_web_search"] is False
    assert settings["web_search_agent"]["other_settings"]["azure_ai_foundry"]["agent_id"] == "agent-id"


def cu_request(defaults, ready=True):
    current = copy.deepcopy(defaults)
    calls = []

    def request(method, url, body=None):
        calls.append((method, url, body))
        if "/defaults?" in url:
            if method == "PATCH":
                current.update(body["modelDeployments"])
            return {"modelDeployments": copy.deepcopy(current)}
        analyzer_id = url.split("/analyzers/")[1].split("?")[0]
        return {
            "analyzerId": analyzer_id, "status": "ready" if ready else "creating",
            "models": {"completion": "prebuilt-analyzer-completion-mini", "embedding": "prebuilt-analyzer-embedding"},
            "supportedModels": {"completion": ["gpt-4.1-mini"], "embedding": ["text-embedding-3-large"]},
        }
    return request, calls


def test_cu_defaults_are_create_only_and_repeated_runs_are_idempotent():
    request, calls = cu_request({})
    deployed = {model["modelName"]: model["modelName"] for model in CU_MODELS}
    MODULE.validate_cu_readiness("https://example.services.ai.azure.com", CU_DEFAULTS, request, deployed, configure=True)
    MODULE.validate_cu_readiness("https://example.services.ai.azure.com", CU_DEFAULTS, request, deployed, configure=True)
    assert sum(method == "PATCH" for method, _, _ in calls) == 1
    assert all(":analyze" not in url for _, url, _ in calls)
    assert {url.split("/analyzers/")[1].split("?")[0] for _, url, _ in calls if "/analyzers/" in url} == set(MODULE.CU_ANALYZERS)


def test_cu_reuse_preserves_configured_model_defaults():
    request, calls = cu_request(CU_DEFAULTS)
    MODULE.validate_cu_readiness("https://example.services.ai.azure.com", {"replacement": "not-written"}, request,
                                 {model["modelName"]: model["modelName"] for model in CU_MODELS})
    assert not any(method == "PATCH" for method, _, _ in calls)


@pytest.mark.parametrize("defaults,ready,deployed", [
    ({}, True, {}), (CU_DEFAULTS, False, {model["modelName"]: model["modelName"] for model in CU_MODELS}),
    (CU_DEFAULTS, True, {"gpt-4.1-mini": "unsupported", "text-embedding-3-large": "text-embedding-3-large"}),
])
def test_cu_missing_defaults_unready_or_incompatible_models_stop_publication(defaults, ready, deployed):
    request, _ = cu_request(defaults, ready)
    with pytest.raises(ValueError):
        MODULE.validate_cu_readiness("https://example.services.ai.azure.com", {}, request, deployed)


@pytest.mark.parametrize("change", [
    {"CONTENT_UNDERSTANDING_LOCATION": "northcentralus"},
    {"CONTENT_UNDERSTANDING_MODELS": "[]"},
    {"CONTENT_UNDERSTANDING_MODEL_DEFAULTS": "{}"},
    {"OPTIONAL_SERVICES_DEPLOYMENT_PRINCIPAL_ID": ""},
])
def test_cu_preconditions_fail_before_any_external_resource_call(change):
    query = Mock()
    with pytest.raises(ValueError):
        MODULE.preflight({**CU_VALUES, **change}, query)
    query.assert_not_called()


def test_provider_registration_and_actual_cloud_cannot_be_bypassed():
    query = Mock(return_value={"name": "AzureUSGovernment"})
    with pytest.raises(ValueError, match="AzureCloud"):
        MODULE.preflight({**WEB_VALUES, "AZURE_SUBSCRIPTION_ID": "subscription"}, query)
    assert query.call_count == 1
    query = Mock(side_effect=[{"name": "AzureCloud"}, {"registrationState": "NotRegistered"}])
    with pytest.raises(ValueError, match="Register"):
        MODULE.preflight({**WEB_VALUES, "AZURE_SUBSCRIPTION_ID": "subscription"}, query)


def test_web_iq_resource_reuse_checks_the_existing_account_without_creation():
    values = {
        **WEB_VALUES, "WEB_IQ_RESOURCE_MODE": "reuse", "EXISTING_WEB_IQ_NAME": "existing",
        "EXISTING_WEB_IQ_RESOURCE_GROUP": "external", "AZURE_SUBSCRIPTION_ID": "sub",
        "EXISTING_WEB_IQ_SUBSCRIPTION_ID": "other-sub",
    }
    query = Mock(side_effect=[
        {"name": "AzureCloud"},
        {"registrationState": "Registered", "resourceTypes": [
            {"resourceType": "accounts", "locations": ["Global"], "apiVersions": [MODULE.WEB_IQ_API_VERSION]},
        ]},
        {"kind": "WebIQ.Grounding", "location": "global", "sku": {"name": "G3"}},
    ])
    MODULE.preflight(values, query)
    assert query.call_count == 3
    assert "other-sub" in query.call_args_list[1].args[0]
    assert all("create" not in call.args[0] and "register" not in call.args[0] for call in query.call_args_list)


@pytest.mark.parametrize("quota", [0, 100])
def test_cu_creation_checks_models_quota_and_role_permissions(quota):
    catalog = [{"model": {"name": model["modelName"], "version": model["modelVersion"],
                "skus": [{"name": "GlobalStandard", "usageName": model["modelName"]}]}} for model in CU_MODELS]
    usage = [{"name": {"value": model["modelName"]}, "limit": quota, "currentValue": 0} for model in CU_MODELS]
    query = Mock(side_effect=[
        {"name": "AzureCloud"},
        {"registrationState": "Registered", "resourceTypes": [
            {"resourceType": "accounts", "locations": ["East US 2"], "apiVersions": ["2025-06-01"]},
        ]},
        catalog, usage, {"value": [{"actions": ["*"], "notActions": []}]},
    ])
    if quota:
        MODULE.preflight(CU_VALUES, query)
        assert query.call_count == 5
    else:
        with pytest.raises(ValueError, match="quota"):
            MODULE.preflight(CU_VALUES, query)
        assert query.call_count == 4


def test_cu_rerun_does_not_require_quota_for_already_owned_capacity():
    catalog = [{"model": {"name": model["modelName"], "version": model["modelVersion"],
                "skus": [{"name": "GlobalStandard", "usageName": model["modelName"]}]}} for model in CU_MODELS]
    deployments = [{"name": model["modelName"], "properties": {"model": {
        "name": model["modelName"], "version": model["modelVersion"],
    }}, "sku": {"name": "GlobalStandard", "capacity": 10}} for model in CU_MODELS]
    usage = [{"name": {"value": model["modelName"]}, "limit": 10, "currentValue": 10} for model in CU_MODELS]
    query = Mock(side_effect=[
        {"name": "AzureCloud"},
        {"registrationState": "Registered", "resourceTypes": [
            {"resourceType": "accounts", "locations": ["East US 2"], "apiVersions": ["2025-06-01"]},
        ]},
        True, [{"name": "app-env-cu"}], deployments, catalog, usage,
        True, {"value": [{"actions": ["*"], "notActions": []}]},
    ])
    MODULE.preflight({**CU_VALUES, "env_DEPLOYMENT_APPNAME": "app", "environment": "env"}, query)
    assert query.call_count == 9


def test_interactive_choices_persist_in_explicit_environment(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["optional_services.py", "--interactive", "--environment", "selected"])
    monkeypatch.setattr(MODULE.os, "environ", {})
    monkeypatch.setattr(MODULE.shutil, "which", lambda _: "azd")
    responses = iter(["web_iq", "preserve", "create", "true", "text_only", "with_media", "true", "true"])
    monkeypatch.setattr("builtins.input", lambda _: next(responses))
    runner = Mock(return_value=subprocess.CompletedProcess([], 0, 'AZURE_ENV_NAME="selected"\n', ""))
    monkeypatch.setattr(MODULE.subprocess, "run", runner)
    result = MODULE.main()
    assert result == 0
    commands = [call.args[0] for call in runner.call_args_list]
    assert all(command[-1] == "selected" for command in commands)
    assert any("WEB_IQ_IMAGE_MODE" in command and "text_only" in command for command in commands)
    assert any("WEB_IQ_VIDEO_MODE" in command and "with_media" in command for command in commands)
    assert not any("web_iq_consent_accepted" in command for command in commands)


def test_preflight_is_preserved_under_optimized_python():
    code = (
        "import importlib.util; "
        f"s=importlib.util.spec_from_file_location('optional', {str(SPEC.origin)!r}); "
        "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
        "\ntry:\n m.selection({'WEB_SEARCH_PROVIDER':'web_iq','env_AZURE_CLOUD_ENVIRONMENT':'usgovernment'})"
        "\nexcept ValueError:\n pass"
        "\nelse:\n raise RuntimeError('Government service selection was accepted')"
    )
    result = subprocess.run([sys.executable, "-O", "-c", code], capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 0, result.stderr


def test_compiled_resource_uses_documented_web_iq_account_and_no_keys():
    template = json.loads((ROOT / "deployers" / "bicep" / "main.json").read_text(encoding="utf-8"))
    module = template["resources"]["webIq"]["properties"]["template"]
    account = next(resource for resource in module["resources"] if resource["type"] == "Microsoft.WebIQ/accounts")
    assert account["type"] == "Microsoft.WebIQ/accounts"
    assert account["apiVersion"] == "2026-06-01-preview"
    assert account["location"] == "global"
    assert account["kind"] == "WebIQ.Grounding"
    assert account["sku"]["name"] == "G3"
    assert account["properties"] == {"statisticsEnabled": False}
    assert set(module["outputs"]) == {"resourceId"}


def test_azd_parameters_have_safe_old_environment_defaults_and_hook_order():
    parameters = json.loads((ROOT / "deployers" / "bicep" / "main.parameters.json").read_text())["parameters"]
    assert parameters["webSearchProvider"]["value"] == "${WEB_SEARCH_PROVIDER=preserve}"
    assert parameters["contentUnderstandingMode"]["value"] == "${CONTENT_UNDERSTANDING_MODE=preserve}"
    script = (ROOT / "deployers" / "Initialize-AzureEnvironment.ps1").read_text()
    assert script.index("python @optionalArguments") < script.index("az group create")
