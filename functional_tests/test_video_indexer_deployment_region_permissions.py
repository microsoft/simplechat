# test_video_indexer_deployment_region_permissions.py
#!/usr/bin/env python3
"""
Functional test for the Video Indexer deployment region and permission fix.
Version: 0.261.264
Implemented in: 0.261.264

This test ensures the deployers can place Azure Video Indexer in a supported region
other than the application region, with a storage account in that region; grant the
App Service identity the role SimpleChat needs to call generateAccessToken; and stop
azd before provisioning, with guidance, when Video Indexer is unavailable in the
chosen region. Postconfig behavior is covered in test_deployment_configuration.py.
"""

import contextlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
BICEP_DIR = REPO_ROOT / "deployers" / "bicep"
TERRAFORM_MAIN = REPO_ROOT / "deployers" / "terraform" / "main.tf"
AZURECLI_SCRIPT = REPO_ROOT / "deployers" / "azurecli" / "deploy-simplechat.ps1"
VIDEO_INDEXER_ACCOUNT_CONTRIBUTOR_ROLE_ID = "3f99eaab-6f59-4877-adf5-1cacd22e20b0"
CONTRIBUTOR_ROLE_ID = "b24988ac-6180-42a0-ab88-20f7382dd24c"
PREFLIGHT_ENVIRONMENT_NAMES = (
    "AZURE_ENV_DEPLOY_VIDEO_INDEXER_SERVICE",
    "DEPLOY_VIDEO_INDEXER_SERVICE",
    "AZURE_ENV_VIDEO_INDEXER_LOCATION",
    "VIDEO_INDEXER_LOCATION",
    "AZURE_ENV_AZURE_LOCATION",
    "AZURE_LOCATION",
    "AZURE_ENV_AUTHENTICATION_TYPE",
    "AUTHENTICATION_TYPE",
    "var_authenticationType",
    "AZURE_ENV_ENABLE_PRIVATE_NETWORKING",
    "ENABLE_PRIVATE_NETWORKING",
)
SUPPORTED_REGIONS_JSON = json.dumps(["Central US", "East US 2", "West US 2"])


def read_text(path):
    return path.read_text(encoding="utf-8")


def terraform_block(content, header):
    """Return one top-level Terraform block, which ends at the first unindented closing brace."""
    start = content.index(header)
    return content[start:content.index("\n}", start)]


def load_preflight_module():
    spec = importlib.util.spec_from_file_location(
        "validate_azd_prerequisites_under_test", BICEP_DIR / "validate_azd_prerequisites.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@contextlib.contextmanager
def patched_environment(values):
    """Run with only the given preflight variables set, then restore the caller's environment."""
    names = set(PREFLIGHT_ENVIRONMENT_NAMES) | set(values)
    saved = {name: os.environ.get(name) for name in names}
    try:
        for name in names:
            os.environ.pop(name, None)
        os.environ.update(values)
        yield
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


@contextlib.contextmanager
def fake_azure_cli(module, exit_code=0, stdout=SUPPORTED_REGIONS_JSON, stderr=""):
    """Replace the preflight Azure CLI runner and record each command it receives."""
    calls = []
    original = module._run_command

    def run(command):
        calls.append(command)
        return exit_code, stdout, stderr

    module._run_command = run
    try:
        yield calls
    finally:
        module._run_command = original


def test_bicep_places_video_indexer_in_its_own_region():
    """The azd template accepts a Video Indexer region and pairs it with same-region storage."""
    main_bicep = read_text(BICEP_DIR / "main.bicep")
    video_indexer_module = read_text(BICEP_DIR / "modules" / "videoIndexer.bicep")
    parameters = json.loads(read_text(BICEP_DIR / "main.parameters.json"))["parameters"]
    template = json.loads(read_text(BICEP_DIR / "main.json"))

    assert "param videoIndexerLocation string = location" in main_bicep
    assert parameters["videoIndexerLocation"]["value"] == "${VIDEO_INDEXER_LOCATION}"
    assert "var videoIndexerUsesDedicatedStorage = normalizedVideoIndexerLocation != normalizedLocation" in main_bicep

    assert (
        "resource videoIndexerStorage 'Microsoft.Storage/storageAccounts@2022-09-01' = if (useDedicatedStorageAccount)"
        in video_indexer_module
    )
    assert "kind: 'StorageV2'" in video_indexer_module
    assert "bypass: 'AzureServices'" in video_indexer_module
    assert "publicNetworkAccess: 'Enabled'" in video_indexer_module
    assert video_indexer_module.count("resourceId: videoIndexerStorageAccountId") == 2, (
        "Both Video Indexer API profiles must use the selected storage account."
    )
    assert "output videoIndexerLocation string = toLower(replace(location, ' ', ''))" in video_indexer_module

    module_parameters = template["resources"]["videoIndexerService"]["properties"]["parameters"]
    assert template["parameters"]["videoIndexerLocation"]["defaultValue"] == "[parameters('location')]"
    assert module_parameters["location"]["value"] == "[parameters('videoIndexerLocation')]"
    assert module_parameters["useDedicatedStorageAccount"]["value"] == "[variables('videoIndexerUsesDedicatedStorage')]"
    assert "var_videoIndexerLocation" in template["outputs"], "Generated main.json is stale; rebuild it from main.bicep."


def test_bicep_grants_app_identity_video_indexer_access():
    """The app identity can call generateAccessToken without colliding with existing grants."""
    main_bicep = read_text(BICEP_DIR / "main.bicep")
    permissions = read_text(BICEP_DIR / "modules" / "setVideoIndexerPermissions.bicep")
    set_permissions = read_text(BICEP_DIR / "modules" / "setPermissions.bicep")
    native_permissions = read_text(BICEP_DIR / "modules" / "setNativeWebAppPermissions.bicep")
    template = json.loads(read_text(BICEP_DIR / "main.json"))

    assert "var videoIndexerAppRoleDefinitionId = scCloudEnvironment == 'public'" in main_bicep
    assert f"? '{VIDEO_INDEXER_ACCOUNT_CONTRIBUTOR_ROLE_ID}'" in main_bicep
    assert f": '{CONTRIBUTOR_ROLE_ID}'" in main_bicep
    role_variable = template["variables"]["videoIndexerAppRoleDefinitionId"]
    assert VIDEO_INDEXER_ACCOUNT_CONTRIBUTOR_ROLE_ID in role_variable and CONTRIBUTOR_ROLE_ID in role_variable

    assert "scope: videoIndexerService" in permissions
    assert "principalId: webApp.identity.principalId" in permissions
    # SimpleChat uses managed identity for Video Indexer in every auth mode, so nothing may gate the grant on it.
    assert "param authenticationType" not in permissions
    assert "authenticationType ==" not in permissions
    assert "guid(videoIndexerService.id, webApp.id, 'video-indexer-app-access', webAppRoleDefinitionId)" in permissions

    # Moving the storage grant must keep the assignment name existing deployments already have.
    assert (
        "guid(videoIndexerStorageAccount.id, videoIndexerService.id, 'video-indexer-storage-blob-data-contributor')"
        in permissions
    )
    assert "module videoIndexerPermissions 'setVideoIndexerPermissions.bicep' = if (videoIndexerName != '')" in set_permissions
    assert "'video-indexer-storage-blob-data-contributor'" not in set_permissions

    assert (
        "resource videoIndexerAppAccessRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (videoIndexerName != '')"
        in native_permissions
    )
    assert "video-indexer-app-access" in read_text(BICEP_DIR / "main.json")


def test_terraform_places_and_authorizes_video_indexer():
    """Terraform mirrors the region override, dedicated storage, and app identity grant."""
    terraform = read_text(TERRAFORM_MAIN)

    assert 'variable "param_video_indexer_location"' in terraform
    video_indexer = terraform_block(terraform, 'resource "azapi_resource" "video_indexer"')
    assert re.search(r"^\s*location\s*=\s*local\.video_indexer_location\s*$", video_indexer, re.M)

    storage = terraform_block(terraform, 'resource "azurerm_storage_account" "video_indexer_sa"')
    assert re.search(r"^\s*count\s*=\s*local\.video_indexer_uses_dedicated_storage \? 1 : 0\s*$", storage, re.M)
    assert re.search(r"^\s*location\s*=\s*local\.video_indexer_location\s*$", storage, re.M)

    app_access = terraform_block(terraform, 'resource "azurerm_role_assignment" "app_service_smi_video_indexer_access"')
    assert re.search(r"^\s*scope\s*=\s*azapi_resource\.video_indexer\[0\]\.id\s*$", app_access, re.M)
    assert re.search(r"^\s*principal_id\s*=\s*azurerm_linux_web_app\.app\.identity\[0\]\.principal_id\s*$", app_access, re.M)
    assert '"Video Indexer Account Contributor"' in terraform

    # azapi 2.x returns output as an object, and jsondecode on an object fails at plan time.
    assert "jsondecode(azapi_resource.video_indexer" not in terraform
    assert 'output "video_indexer_account_id"' in terraform


def test_azurecli_places_and_authorizes_video_indexer():
    """The Azure CLI deployer mirrors the region override and app identity grant."""
    script = read_text(AZURECLI_SCRIPT)

    assert '$param_VideoIndexerLocation = ""' in script
    assert "location = $videoIndexerLocation" in script
    assert (
        '$videoIndexerAppRoleName = if ($globalWhichAzurePlatform -eq "AzureCloud") '
        '{ "Video Indexer Account Contributor" } else { "Contributor" }'
    ) in script
    assert "--assignee-object-id $appService_SystemManagedIdentity_ObjectId" in script
    assert '--scope "$videoIndexerResourceId"' in script


def test_preflight_blocks_unsupported_video_indexer_region():
    """azd stops before provisioning when Video Indexer is unavailable in the app region."""
    module = load_preflight_module()
    with patched_environment({"DEPLOY_VIDEO_INDEXER_SERVICE": "true", "AZURE_LOCATION": "northcentralus"}):
        with fake_azure_cli(module) as calls:
            allowed = module._validate_video_indexer_region()

    assert allowed is False
    assert calls and calls[0][:5] == ["az", "provider", "show", "--namespace", "Microsoft.VideoIndexer"]


def test_preflight_accepts_supported_override_region():
    """A display-name override such as 'Central US' is normalized before comparison."""
    module = load_preflight_module()
    environment = {
        "DEPLOY_VIDEO_INDEXER_SERVICE": "true",
        "AZURE_LOCATION": "northcentralus",
        "VIDEO_INDEXER_LOCATION": "Central US",
    }
    with patched_environment(environment):
        with fake_azure_cli(module):
            allowed = module._validate_video_indexer_region()

    assert allowed is True


def test_preflight_skips_when_video_indexer_disabled():
    """No Azure CLI lookup runs when Video Indexer is not being deployed."""
    module = load_preflight_module()
    with patched_environment({"DEPLOY_VIDEO_INDEXER_SERVICE": "false", "AZURE_LOCATION": "northcentralus"}):
        with fake_azure_cli(module) as calls:
            allowed = module._validate_video_indexer_region()

    assert allowed is True
    assert calls == []


def test_preflight_does_not_block_when_region_lookup_fails():
    """A failed lookup only warns, because Azure Resource Manager still validates the region."""
    module = load_preflight_module()
    with patched_environment({"DEPLOY_VIDEO_INDEXER_SERVICE": "true", "AZURE_LOCATION": "northcentralus"}):
        with fake_azure_cli(module, exit_code=1, stdout="", stderr="provider lookup failed"):
            allowed = module._validate_video_indexer_region()

    assert allowed is True


def test_preflight_main_stops_before_provisioning():
    """The preprovision entry point returns a failure code for an unsupported region."""
    module = load_preflight_module()
    environment = {
        "DEPLOY_VIDEO_INDEXER_SERVICE": "true",
        "AZURE_LOCATION": "northcentralus",
        "AUTHENTICATION_TYPE": "key",
    }
    with patched_environment(environment):
        with fake_azure_cli(module):
            exit_code = module.main()

    assert exit_code == 1


def test_version_includes_fix():
    """The application version includes this deployer fix."""
    assert_app_version_at_least("0.261.264")


if __name__ == "__main__":
    tests = [
        test_bicep_places_video_indexer_in_its_own_region,
        test_bicep_grants_app_identity_video_indexer_access,
        test_terraform_places_and_authorizes_video_indexer,
        test_azurecli_places_and_authorizes_video_indexer,
        test_preflight_blocks_unsupported_video_indexer_region,
        test_preflight_accepts_supported_override_region,
        test_preflight_skips_when_video_indexer_disabled,
        test_preflight_does_not_block_when_region_lookup_fails,
        test_preflight_main_stops_before_provisioning,
        test_version_includes_fix,
    ]
    results = []

    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            test()
        except AssertionError as ex:
            print(f"FAIL {test.__name__}: {ex}")
            results.append(False)
        else:
            print(f"PASS {test.__name__}")
            results.append(True)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
