# test_deployment_configuration.py
"""Postconfig environment, cache publication and create-only Search regressions.

Version: 0.261.028
Implemented in: 0.261.028
Uses the real settings store with fake services; never contacts Azure.
"""

import copy
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import runpy
import shutil
import subprocess
import sys

import pytest
import yaml
from azure.core.exceptions import HttpResponseError, ResourceNotFoundError

from test_app_settings_store_consistency import FakeCosmos, FakeRedis


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "deployment_configuration", ROOT / "deployers" / "bicep" / "deployment_configuration.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


@pytest.fixture
def world(monkeypatch):
    cosmos, redis = FakeCosmos(), FakeRedis()
    redis.ping = Mock(return_value=True)
    redis.close = Mock()
    monkeypatch.setattr(MODULE, "redis_client_for_settings", lambda *_: redis)
    return SimpleNamespace(cosmos=cosmos, redis=redis)


def desired_redis(document, kind="managed", auth="managed_identity"):
    desired = copy.deepcopy(document)
    MODULE.configure_redis(desired, "cache.redis.azure.net", kind, "", auth, {"redis_key": "test-key"})
    return desired


def test_save_publishes_shared_cache_and_preserves_concurrent_edit(world):
    original = copy.deepcopy(world.cosmos.document)
    desired = desired_redis(original)

    def concurrent_write():
        world.cosmos.document["operator_setting"] = "keep"
        world.cosmos.etag += 1
        world.cosmos.document["_etag"] = str(world.cosmos.etag)

    world.cosmos.before_replace = concurrent_write
    stored = MODULE.persist_settings(world.cosmos, original, desired, Mock())
    published = json.loads(world.redis.raw)["document"]
    assert stored["operator_setting"] == "keep"
    assert stored["enable_redis_cache"] is True
    assert stored["redis_port"] == "10000"
    assert published == stored
    assert stored["_settings_revision"] == 1
    world.redis.close.assert_called_once()


def test_existing_disabled_external_settings_are_not_erased(world):
    world.cosmos.document.update(redis_url="external.example", enable_redis_cache=False, redis_key="keep")
    original = copy.deepcopy(world.cosmos.document)
    desired = copy.deepcopy(original)
    MODULE.configure_redis(desired, "", "", "", "managed_identity", {})
    desired["deployment_setting"] = True
    stored = MODULE.persist_settings(world.cosmos, original, desired, Mock())
    assert stored["redis_url"] == "external.example"
    assert stored["redis_key"] == "keep"
    assert stored["enable_redis_cache"] is False


@pytest.mark.parametrize("kind,auth,port,key", [
    ("managed", "managed_identity", "10000", ""),
    ("classic", "key", "6380", "test-key"),
])
def test_redis_mapping_and_authentication(kind, auth, port, key):
    result = desired_redis({"redis_key": "stale"}, kind, auth)
    assert result["redis_port"] == port
    assert result["redis_key"] == key
    assert result["redis_service_type"] == (
        "azure_managed_redis" if kind == "managed" else "azure_cache_for_redis"
    )


def test_first_run_creates_document(world):
    world.cosmos.document = None
    initial = {"id": "app_settings", "partition_key": "app_settings"}
    stored = MODULE.persist_settings(world.cosmos, initial, {**initial, "deployed": True}, Mock())
    assert stored["deployed"]
    assert world.cosmos.writes == 1


def test_redis_failure_prevents_database_write(world):
    world.redis.failed = True
    original = copy.deepcopy(world.cosmos.document)
    with pytest.raises(MODULE.settings_store.SettingsUnavailableError):
        MODULE.persist_settings(world.cosmos, original, desired_redis(original), Mock())
    assert world.cosmos.writes == 0


def test_publication_failure_is_not_reported_as_success(world):
    world.redis.fail_publication = True
    original = copy.deepcopy(world.cosmos.document)
    with pytest.raises(MODULE.settings_store.SettingsUnavailableError):
        MODULE.persist_settings(world.cosmos, original, desired_redis(original), Mock())
    assert world.cosmos.writes == 1
    assert json.loads(world.redis.raw)["state"] == "pending"


def test_active_cache_migration_fails_before_writes(world):
    world.cosmos.document = desired_redis(world.cosmos.document)
    original = copy.deepcopy(world.cosmos.document)
    desired = {**original, "redis_url": "different.redis.azure.net"}
    with pytest.raises(ValueError, match="cache migration"):
        MODULE.persist_settings(world.cosmos, original, desired, Mock())
    assert world.cosmos.writes == 0


def test_concurrent_redis_change_is_not_overwritten(world):
    original = copy.deepcopy(world.cosmos.document)
    world.cosmos.document["redis_url"] = "configured-by-admin"
    with pytest.raises(MODULE.settings_store.SettingsConflictError):
        MODULE.persist_settings(world.cosmos, original, desired_redis(original), Mock())
    assert world.cosmos.document["redis_url"] == "configured-by-admin"
    assert world.cosmos.writes == 0


def test_repeated_redis_configuration_preserves_values(world):
    original = copy.deepcopy(world.cosmos.document)
    first = MODULE.persist_settings(world.cosmos, original, desired_redis(original), Mock())
    repeated = MODULE.persist_settings(world.cosmos, first, desired_redis(first), Mock())
    assert {key: repeated.get(key) for key in MODULE.REDIS_FIELDS} == {
        key: first.get(key) for key in MODULE.REDIS_FIELDS
    }
    assert json.loads(world.redis.raw)["document"] == repeated


def test_enabled_external_cache_is_preserved_and_published(world):
    world.cosmos.document = desired_redis(world.cosmos.document)
    original = copy.deepcopy(world.cosmos.document)
    desired = copy.deepcopy(original)
    MODULE.configure_redis(desired, None, "", "", "managed_identity", {})
    desired["deployment_setting"] = "new"
    stored = MODULE.persist_settings(world.cosmos, original, desired, Mock())
    assert stored["redis_url"] == original["redis_url"]
    assert json.loads(world.redis.raw)["document"]["deployment_setting"] == "new"


def test_equivalent_active_redis_settings_can_be_normalized(world):
    world.cosmos.document = desired_redis(world.cosmos.document)
    world.cosmos.document.update(redis_service_type="auto", redis_port=10000, redis_key="unused-old-key")
    original = copy.deepcopy(world.cosmos.document)
    stored = MODULE.persist_settings(world.cosmos, original, desired_redis(original), Mock())
    assert stored["redis_port"] == "10000"
    assert stored["redis_key"] == ""
    assert stored["redis_service_type"] == "azure_managed_redis"


class FakeSearch:
    def __init__(self):
        self.indexes = {"simplechat-user-index": {"name": "simplechat-user-index", "custom": True}}
        self.created = []
        self.fail_status = None
        self.race = False

    def get_index(self, name):
        if self.fail_status:
            error = HttpResponseError(message="lookup failure")
            error.status_code = self.fail_status
            raise error
        if name not in self.indexes:
            raise ResourceNotFoundError(status_code=404)
        return self.indexes[name]

    def create_index(self, index):
        self.indexes[index.name] = index
        if self.race:
            error = HttpResponseError(message="concurrent creation")
            error.status_code = 409
            raise error
        self.created.append(index)
        return index


def test_search_uses_app_schemas_and_leaves_existing_indexes_untouched():
    client = FakeSearch()
    existing = client.indexes["simplechat-user-index"]
    created = MODULE.ensure_search_indexes(client)
    repeated = MODULE.ensure_search_indexes(client)
    assert created == ["simplechat-group-index", "simplechat-public-index"]
    assert repeated == []
    assert client.indexes["simplechat-user-index"] is existing
    for index in client.created:
        kind = index.name.removeprefix("simplechat-").removesuffix("-index")
        schema = json.loads((MODULE.APP_DIRECTORY / "static" / "json" / f"ai_search-index-{kind}.json").read_text())
        assert [field.name for field in index.fields] == [field["name"] for field in schema["fields"]]


def test_search_create_race_is_idempotent():
    client = FakeSearch()
    client.race = True
    MODULE.ensure_search_indexes(client)
    assert set(client.indexes) == {"simplechat-user-index", "simplechat-group-index", "simplechat-public-index"}


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_search_permission_and_service_errors_do_not_trigger_creation(status):
    client = FakeSearch()
    client.fail_status = status
    with pytest.raises(HttpResponseError):
        MODULE.ensure_search_indexes(client)
    assert not client.created


def test_environment_selection_overrides_stale_outputs(monkeypatch):
    monkeypatch.setenv("AZURE_ENV_NAME", "chosen")
    monkeypatch.setenv("var_redisCacheHostName", "wrong-cache")
    monkeypatch.setenv("var_cosmosDb_key", "stale-key")
    values = {key: "value" for key in MODULE.REQUIRED_VALUES}
    values.update(AZURE_ENV_NAME="chosen", var_authenticationType="managed_identity")
    values["var_openAIGPTModels"] = json.dumps([{"modelName": "model"}])
    values["var_openAIEmbeddingModels"] = json.dumps([{"modelName": "embedding"}])
    output = "\n".join(f"{key}={json.dumps(value)}" for key, value in values.items())
    command = Mock(return_value=SimpleNamespace(returncode=0, stdout=output))
    monkeypatch.setattr(MODULE.shutil, "which", lambda _: "azd")
    monkeypatch.setattr(MODULE.subprocess, "run", command)
    previous = dict(os.environ)
    try:
        resolved = MODULE.load_deployment_environment()
        assert resolved["AZURE_ENV_NAME"] == "chosen"
        assert "var_redisCacheHostName" not in os.environ
        assert "var_cosmosDb_key" not in os.environ
        assert json.loads(os.environ["var_openAIGPTModels"])[0]["modelName"] == "model"
        assert command.call_args.args[0][-2:] == ["--environment", "chosen"]
    finally:
        os.environ.clear()
        os.environ.update(previous)


def test_missing_environment_output_fails_before_mutation(monkeypatch):
    monkeypatch.setenv("AZURE_ENV_NAME", "chosen")
    monkeypatch.setenv("var_rgName", "untouched")
    monkeypatch.setattr(MODULE.shutil, "which", lambda _: "azd")
    monkeypatch.setattr(MODULE.subprocess, "run", lambda *_, **__: SimpleNamespace(returncode=0, stdout='AZURE_ENV_NAME="chosen"'))
    with pytest.raises(ValueError, match="Missing required"):
        MODULE.load_deployment_environment()
    assert os.environ["var_rgName"] == "untouched"


@pytest.mark.parametrize("platform", ["windows", "posix"])
def test_postprovision_has_no_network_mutation_or_key_probe(platform):
    hook = yaml.safe_load((ROOT / "deployers" / "azure.yaml").read_text(encoding="utf-8"))["hooks"]["postprovision"][platform]["run"]
    assert "--ip-range-filter" not in hook
    assert "cosmosdb keys list" not in hook
    assert "api.ipify.org" not in hook
    assert "postconfig.py" in hook


@pytest.mark.parametrize("hook_name", ["postprovision", "predeploy", "postup"])
def test_windows_hydration_executes_with_explicit_environment(hook_name):
    pwsh = shutil.which("pwsh")
    if not pwsh:
        pytest.skip("PowerShell is unavailable")
    source = yaml.safe_load((ROOT / "deployers" / "azure.yaml").read_text(encoding="utf-8"))["hooks"][hook_name]["windows"]["run"]
    helper = source.split("Import-AzdHookEnvironment -Names @(", 1)[0]
    probe = helper + r'''
function azd {
    if ($args[0] -ne 'env' -or $args[1] -ne 'get-value' -or
        $args[3] -ne '--environment' -or $args[4] -ne 'selected') { throw 'Unscoped lookup' }
    if ($args[2] -eq 'missing') { $global:LASTEXITCODE = 1; return }
    $global:LASTEXITCODE = 0
    if ($args[2] -eq 'AZURE_SUBSCRIPTION_ID') { return 'selected-subscription' }
    return 'selected-host'
}
$env:AZURE_ENV_NAME = 'selected'
$env:var_redisCacheHostName = 'wrong-environment-host'
Import-AzdHookEnvironment -Names @('var_redisCacheHostName', 'var_subscriptionId')
if ($env:var_redisCacheHostName -ne 'selected-host') { throw 'Stale host was retained' }
if ($env:var_subscriptionId -ne 'selected-subscription') { throw 'Alias was not resolved' }
$failed = $false
try { Import-AzdHookEnvironment -Names @('missing') } catch { $failed = $true }
if (-not $failed) { throw 'Missing required value was ignored' }
'''
    result = subprocess.run([pwsh, "-NoProfile", "-NonInteractive", "-Command", probe], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_real_postconfig_entrypoint_writes_once_and_initializes_search(monkeypatch, world):
    environment = {
        "AZURE_TENANT_ID": "tenant", "var_authenticationType": "managed_identity",
        "var_openAIEndpoint": "https://example.openai.azure.com/",
        "var_subscriptionId": "subscription", "var_rgName": "group",
        "var_openAIGPTModels": '[{"modelName":"gpt"}]',
        "var_openAIEmbeddingModels": '[{"modelName":"embedding"}]',
        "var_redisCacheHostName": "cache.redis.azure.net", "var_redisCacheKind": "managed",
        "var_redisCachePort": "10000", "var_redisAuthenticationType": "managed_identity",
        "var_blobStorageEndpoint": "https://example.blob.core.windows.net",
        "var_searchServiceEndpoint": "https://example.search.windows.net",
    }
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(MODULE, "load_deployment_environment", lambda: environment)
    search = FakeSearch()
    monkeypatch.setattr(MODULE, "configure_search", lambda *_: MODULE.ensure_search_indexes(search))
    cosmos = Mock()
    cosmos.get_database_client.return_value.get_container_client.return_value = world.cosmos
    access_module = SimpleNamespace(create_deployment_cosmos_client=lambda: cosmos)
    monkeypatch.setitem(sys.modules, "deployment_cosmos", access_module)
    monkeypatch.setitem(sys.modules, "deployment_configuration", MODULE)
    runpy.run_path(str(ROOT / "deployers" / "bicep" / "postconfig.py"), run_name="__main__")
    assert world.cosmos.writes == 1
    assert world.cosmos.document["redis_service_type"] == "azure_managed_redis"
    assert world.cosmos.document["redis_url"] == "cache.redis.azure.net"
    assert json.loads(world.redis.raw)["document"] == world.cosmos.document
    assert set(search.indexes) == {"simplechat-user-index", "simplechat-group-index", "simplechat-public-index"}
    cosmos.close.assert_called_once()


@pytest.mark.parametrize("failure", [False, True])
def test_windows_hook_stops_before_restart_on_postconfig_failure(failure):
    pwsh = shutil.which("pwsh")
    if not pwsh:
        pytest.skip("PowerShell is unavailable")
    hook = yaml.safe_load((ROOT / "deployers" / "azure.yaml").read_text(encoding="utf-8"))["hooks"]["postprovision"]["windows"]["run"]
    mocks = r'''
$env:AZURE_ENV_NAME = 'chosen'
$global:Calls = @()
function azd {
    if ($args[3] -ne '--environment' -or $args[4] -ne 'chosen') { throw 'Wrong environment' }
    $global:LASTEXITCODE = 0
    switch ($args[2]) {
        'AZURE_SUBSCRIPTION_ID' { return 'chosen-sub' }
        'var_configureApplication' { return 'true' }
        'var_cosmosDb_uri' { return 'https://account.documents.azure.com/' }
        'var_rgName' { return 'chosen-group' }
        'var_webService' { return 'chosen-web' }
        default { return 'value' }
    }
}
function az {
    $global:Calls += ($args -join ' ')
    $global:LASTEXITCODE = 0
    if ($args[0] -eq 'group') { return 'true' }
    if ($args[0] -eq 'account') { return 'servicePrincipal' }
    if ($args[0] -eq 'webapp' -and $args[1] -eq 'restart') { return }
    throw 'Unexpected Azure command'
}
function python {
    $global:LASTEXITCODE = 0
    if (($args -join ' ') -match 'postconfig.py' -and $env:TEST_POSTCONFIG_FAILURE -eq 'true') {
        $global:LASTEXITCODE = 1
    }
}
'''
    script = mocks + "\ntry {\n" + hook + "\n} catch { Write-Output 'HOOK_FAILED' }\n$global:Calls | ForEach-Object { Write-Output ('AZCALL=' + $_) }"
    result = subprocess.run(
        [pwsh, "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True,
        env={**os.environ, "TEST_POSTCONFIG_FAILURE": str(failure).lower()},
    )
    assert result.returncode == 0, result.stderr
    assert ("HOOK_FAILED" in result.stdout) is failure
    assert ("AZCALL=webapp restart" in result.stdout) is not failure
    assert "--ip-range-filter" not in result.stdout
    if not failure:
        assert "--subscription chosen-sub" in result.stdout


@pytest.mark.parametrize("failure", [False, True])
def test_posix_hook_stops_before_restart_on_postconfig_failure(failure):
    git_bash = Path("C:/Program Files/Git/bin/bash.exe")
    shell = str(git_bash) if git_bash.exists() else shutil.which("sh")
    if not shell:
        pytest.skip("POSIX shell is unavailable")
    hook = yaml.safe_load((ROOT / "deployers" / "azure.yaml").read_text(encoding="utf-8"))["hooks"]["postprovision"]["posix"]["run"]
    mocks = '''
az() { printf 'AZCALL=%s\\n' "$*"; return 0; }
bash() { return 0; }
python3() {
    case "$*" in
        *postconfig.py*) return "$TEST_POSTCONFIG_FAILURE" ;;
        *) return 0 ;;
    esac
}
'''
    result = subprocess.run(
        [shell], input=(mocks + hook).encode("utf-8"), capture_output=True,
        env={**os.environ, "var_configureApplication": "true", "AZURE_SUBSCRIPTION_ID": "chosen-sub",
             "var_webService": "chosen-web", "var_rgName": "chosen-group",
             "TEST_POSTCONFIG_FAILURE": "1" if failure else "0"},
    )
    assert (result.returncode != 0) is failure, result.stderr
    output = result.stdout.decode("utf-8")
    assert ("AZCALL=webapp restart" in output) is not failure
    assert "--ip-range-filter" not in output
    if not failure:
        assert "--subscription chosen-sub" in output