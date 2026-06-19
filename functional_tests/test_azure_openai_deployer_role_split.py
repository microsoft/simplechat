# test_azure_openai_deployer_role_split.py
#!/usr/bin/env python3
"""
Functional test for Azure OpenAI deployer role split.
Version: 0.250.001
Implemented in: 0.250.001

This test ensures deployers assign the service principal the management-plane
Cognitive Services User role for model discovery and preserve the App Service
managed identity data-plane Cognitive Services OpenAI User role for inference.
"""

from pathlib import Path
import re
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]


def read_workspace_file(relative_path):
    """Read a workspace file as UTF-8 text."""
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def assert_contains(content, expected, description):
    """Assert expected text is present with a useful failure message."""
    assert expected in content, f"Missing {description}: {expected}"


def test_deployer_openai_role_split():
    """Validate Bicep, ARM JSON, Azure CLI, and Terraform OpenAI role coverage."""
    print("Testing Azure OpenAI deployer role split...")

    bicep_content = read_workspace_file("deployers/bicep/modules/setPermissions.bicep")
    bicep_external_content = read_workspace_file("deployers/bicep/modules/setPermissions-openAIExternal.bicep")
    arm_content = read_workspace_file("deployers/bicep/main.json")
    azurecli_content = read_workspace_file("deployers/azurecli/deploy-simplechat.ps1")
    terraform_content = read_workspace_file("deployers/terraform/main.tf")
    deployer_version = read_workspace_file("deployers/version.txt").strip()

    for content, name in (
        (bicep_content, "internal Bicep permissions"),
        (bicep_external_content, "external Bicep permissions"),
    ):
        assert_contains(content, "openAIenterpriseAppCognitiveServicesUserRole", name)
        assert_contains(content, "enterpriseApp-CognitiveServicesUserRole", name)
        assert_contains(content, "a97b65f3-24c7-4388-baec-2e87135dc908", name)
        assert_contains(content, "enterpriseAppServicePrincipalId", name)

    assert_contains(arm_content, "enterpriseApp-CognitiveServicesUserRole", "compiled ARM service principal discovery role")
    assert_contains(arm_content, "a97b65f3-24c7-4388-baec-2e87135dc908", "compiled ARM Cognitive Services User role id")

    assert re.search(
        r'\$roleName\s*=\s*"Cognitive Services User"[\s\S]{0,700}\$assigneeObjectId\s*=\s*\$appRegistrationIdentity_SP_AppId',
        azurecli_content,
    ) or re.search(
        r'\$assigneeObjectId\s*=\s*\$appRegistrationIdentity_SP_AppId[\s\S]{0,700}\$roleName\s*=\s*"Cognitive Services User"',
        azurecli_content,
    ), "Azure CLI deployer should assign Cognitive Services User to the app registration service principal."

    assert_contains(terraform_content, 'resource "azurerm_role_assignment" "app_reg_sp_openai_management_user"', "Terraform app registration discovery role")
    assert_contains(terraform_content, 'role_definition_name = "Cognitive Services User"', "Terraform Cognitive Services User role")
    assert_contains(terraform_content, "azuread_service_principal.app_registration_sp.object_id", "Terraform app registration principal")
    assert_contains(terraform_content, 'resource "azurerm_role_assignment" "app_service_smi_openai_user"', "Terraform app service data-plane role")
    assert_contains(terraform_content, 'role_definition_name = "Cognitive Services OpenAI User"', "Terraform OpenAI User role")

    version_match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", deployer_version)
    assert version_match, "Expected deployer version to use semantic version format."
    version_tuple = tuple(int(part) for part in version_match.groups())
    assert version_tuple >= (1, 0, 17), "Expected deployer version to be bumped for OpenAI RBAC changes."

    print("Azure OpenAI deployer role split validated.")
    return True


if __name__ == "__main__":
    try:
        success = test_deployer_openai_role_split()
    except Exception as ex:
        print(f"Test failed: {ex}")
        raise

    sys.exit(0 if success else 1)