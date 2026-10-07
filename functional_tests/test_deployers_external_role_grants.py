#!/usr/bin/env python3
# test_deployers_external_role_grants.py
"""
Functional test for optional deployer role grants on existing Azure Files storage accounts and Azure AI Search services.
Version: 0.261.294
Implemented in: 0.261.294

This test ensures that all deployers expose optional empty-by-default inputs for external Azure Files
storage accounts and Azure AI Search services, grant the expected RBAC roles at the supplied resource
scopes, and keep the deployer version aligned with the permission change.
"""

from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from test_support.versioning import assert_app_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[1]
ROLE_STORAGE_FILE_PRIVILEGED_READER = "b8eda974-7b85-4f76-af95-65846b26df6d"
ROLE_READER = "acdd72a7-3385-48ef-bd42-f606fba81ae7"
ROLE_SEARCH_INDEX_DATA_READER = "1407120a-92aa-4202-b7e9-c0e197c71c8f"


def read_file(relative_path: str) -> str:
    """Read a repository file as UTF-8 text."""
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def parse_version(version: str) -> tuple[int, int, int]:
    """Parse a semantic version string for comparisons."""
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version.strip())
    assert match, f"Expected semantic version, got {version!r}."
    return tuple(int(part) for part in match.groups())


def require_contains(content: str, expected: str, description: str) -> None:
    """Assert that a snippet exists with a useful failure message."""
    assert expected in content, f"Missing {description}: {expected}"


def test_application_version_floor() -> None:
    """Validate the functional test is running against the implemented app version or newer."""
    assert_app_version_at_least("0.261.294")


def test_bicep_external_role_grants() -> None:
    """Validate Bicep/azd inputs, cross-scope modules, role IDs, and compiled ARM output."""
    main_bicep = read_file("deployers/bicep/main.bicep")
    parameters_json = read_file("deployers/bicep/main.parameters.json")
    permissions_bicep = read_file("deployers/bicep/modules/setPermissions.bicep")
    native_permissions_bicep = read_file("deployers/bicep/modules/setNativeWebAppPermissions.bicep")
    storage_module = read_file("deployers/bicep/modules/setPermissions-externalAzureFilesStorage.bicep")
    search_module = read_file("deployers/bicep/modules/setPermissions-externalSearchService.bicep")
    compiled_arm = read_file("deployers/bicep/main.json")

    for content in (main_bicep, permissions_bicep, native_permissions_bicep):
        require_contains(content, "param azureFilesStorageAccountResourceIds array = []", "Bicep Azure Files parameter default")
        require_contains(content, "param externalSearchServiceResourceIds array = []", "Bicep external search parameter default")
        require_contains(content, "param externalSearchServiceEnableReaderRole bool = false", "Bicep search Reader opt-in default")

    require_contains(parameters_json, "AZURE_FILES_STORAGE_ACCOUNT_RESOURCE_IDS", "AZD Azure Files environment mapping")
    require_contains(parameters_json, "EXTERNAL_SEARCH_SERVICE_RESOURCE_IDS", "AZD search environment mapping")
    require_contains(parameters_json, "EXTERNAL_SEARCH_SERVICE_ENABLE_READER_ROLE", "AZD search Reader opt-in mapping")

    for content in (permissions_bicep, native_permissions_bicep):
        require_contains(content, "resourceGroup(storage.subscriptionId, storage.resourceGroupName)", "Bicep storage cross-subscription scope")
        require_contains(content, "resourceGroup(search.subscriptionId, search.resourceGroupName)", "Bicep search cross-subscription scope")
        require_contains(content, "microsoft.storage", "Bicep storage provider validation")
        require_contains(content, "storageaccounts", "Bicep storage type validation")
        require_contains(content, "microsoft.search", "Bicep search provider validation")
        require_contains(content, "searchservices", "Bicep search type validation")
        # File Sync and Azure Files Search always use the app managed identity for these external
        # resources, so key-based internal service auth must not suppress the explicitly requested grants.
        external_module_lines = [
            line for line in content.splitlines()
            if line.startswith(("module externalAzureFilesStoragePermissions", "module externalSearchServicePermissions"))
        ]
        assert len(external_module_lines) == 2, "Expected both external permission module declarations."
        for line in external_module_lines:
            assert "authenticationType" not in line, f"External grants must not depend on internal auth type: {line}"

    for role_id in (ROLE_STORAGE_FILE_PRIVILEGED_READER, ROLE_READER):
        require_contains(storage_module, role_id, "Bicep external storage role GUID")
    for role_id in (ROLE_SEARCH_INDEX_DATA_READER, ROLE_READER):
        require_contains(search_module, role_id, "Bicep external search role GUID")
    require_contains(storage_module, "principalType: 'ServicePrincipal'", "Bicep storage principal type")
    require_contains(search_module, "principalType: 'ServicePrincipal'", "Bicep search principal type")

    for role_id in (ROLE_STORAGE_FILE_PRIVILEGED_READER, ROLE_READER, ROLE_SEARCH_INDEX_DATA_READER):
        require_contains(compiled_arm, role_id, "compiled ARM external role GUID")


def test_azurecli_external_role_grants() -> None:
    """Validate Azure CLI deployer parameters, validation, identity choice, and role grants."""
    content = read_file("deployers/azurecli/deploy-simplechat.ps1")

    require_contains(content, "[string[]]$AzureFilesStorageAccountResourceIds = @()", "Azure CLI Azure Files parameter default")
    require_contains(content, "[string[]]$ExternalSearchServiceResourceIds = @()", "Azure CLI external search parameter default")
    require_contains(content, "[bool]$ExternalSearchServiceEnableReaderRole = $false", "Azure CLI search Reader opt-in parameter default")
    require_contains(content, "$param_AzureFilesStorageAccountResourceIds = $AzureFilesStorageAccountResourceIds", "Azure CLI Azure Files config binding")
    require_contains(content, "Assert-ResourceIdsByType", "Azure CLI resource ID validation helper")
    require_contains(content, "Microsoft.Storage/storageAccounts", "Azure CLI storage type validation")
    require_contains(content, "Microsoft.Search/searchServices", "Azure CLI search type validation")
    require_contains(content, "DefaultAzureCredential", "Azure CLI runtime identity explanation")
    require_contains(content, "$appService_SystemManagedIdentity_ObjectId", "Azure CLI App Service system identity grant target")

    for role_id in (ROLE_STORAGE_FILE_PRIVILEGED_READER, ROLE_READER, ROLE_SEARCH_INDEX_DATA_READER):
        require_contains(content, role_id, "Azure CLI external role GUID")


def test_azurecli_resource_id_validation_accepts_empty_defaults() -> None:
    """Validate the CLI resource ID helper accepts the empty defaults and still rejects wrong resource types.

    PowerShell refuses to bind an empty array to a mandatory parameter unless it allows empty
    collections, which would break every deployment that leaves these optional inputs unset.
    """
    content = read_file("deployers/azurecli/deploy-simplechat.ps1")
    match = re.search(r"^function Assert-ResourceIdsByType \{.*?^\}", content, re.DOTALL | re.MULTILINE)
    assert match, "Missing Assert-ResourceIdsByType helper in the Azure CLI deployer."
    helper = match.group(0)
    require_contains(helper, "[AllowEmptyCollection()]", "Azure CLI helper empty-list binding")

    shell = shutil.which("pwsh") or shutil.which("powershell")
    if not shell:
        print("PowerShell not available; skipped the behavioral helper check.")
        return

    script = "\n".join([
        helper,
        "Assert-ResourceIdsByType -ResourceIds @() -ExpectedType 'Microsoft.Storage/storageAccounts' -ParameterName 'p'",
        "'EMPTY_OK'",
        "try {",
        "    Assert-ResourceIdsByType -ResourceIds @('/subscriptions/s/resourceGroups/rg/providers/Microsoft.Search/searchServices/x') "
        "-ExpectedType 'Microsoft.Storage/storageAccounts' -ParameterName 'p'",
        "    'WRONG_TYPE_ACCEPTED'",
        "} catch { 'WRONG_TYPE_REJECTED' }",
    ])
    completed = None
    with tempfile.TemporaryDirectory() as temp_dir:
        script_path = Path(temp_dir) / "assert_resource_ids.ps1"
        script_path.write_text(script, encoding="utf-8")
        completed = subprocess.run(
            [shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script_path)],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    output = completed.stdout + completed.stderr
    assert "EMPTY_OK" in output, f"Helper rejected the empty default list: {output}"
    assert "WRONG_TYPE_REJECTED" in output, f"Helper accepted a mismatched resource type: {output}"


def test_terraform_external_role_grants() -> None:
    """Validate Terraform variables, validation, role IDs, and supplied resource scopes."""
    content = read_file("deployers/terraform/main.tf")

    require_contains(content, 'variable "azure_files_storage_account_resource_ids"', "Terraform Azure Files variable")
    require_contains(content, 'variable "external_search_service_resource_ids"', "Terraform external search variable")
    require_contains(content, 'variable "external_search_service_enable_reader_role"', "Terraform search Reader opt-in variable")
    require_contains(content, "default     = []", "Terraform empty list default")
    require_contains(content, "default     = false", "Terraform Reader opt-in default")
    require_contains(content, "microsoft\\\\.storage/storageaccounts", "Terraform storage type validation")
    require_contains(content, "microsoft\\\\.search/searchservices", "Terraform search type validation")
    require_contains(content, "for_each           = toset(var.azure_files_storage_account_resource_ids)", "Terraform storage scope iteration")
    require_contains(content, "for_each           = toset(var.external_search_service_resource_ids)", "Terraform search scope iteration")
    require_contains(content, "scope              = each.value", "Terraform role assignment uses supplied resource ID scope")
    require_contains(content, "azurerm_linux_web_app.app.identity[0].principal_id", "Terraform App Service system identity grant target")

    for role_id in (ROLE_STORAGE_FILE_PRIVILEGED_READER, ROLE_READER, ROLE_SEARCH_INDEX_DATA_READER):
        require_contains(content, role_id, "Terraform external role GUID")


def test_deployer_version() -> None:
    """Validate the deployer version was bumped for the RBAC parameter change."""
    version = read_file("deployers/version.txt").strip()
    assert parse_version(version) >= (1, 0, 34), "Expected deployers/version.txt to be at least 1.0.34."


if __name__ == "__main__":
    tests = [
        test_application_version_floor,
        test_bicep_external_role_grants,
        test_azurecli_external_role_grants,
        test_azurecli_resource_id_validation_accepts_empty_defaults,
        test_terraform_external_role_grants,
        test_deployer_version,
    ]
    for test in tests:
        print(f"Running {test.__name__}...")
        test()

    print("External deployer role grants validated.")
    sys.exit(0)
