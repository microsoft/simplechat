# test_azd_windows_hook_environment.py
#!/usr/bin/env python3
"""
Functional test for azd Windows hook environment hydration.
Version: 0.241.101
Implemented in: 0.241.101

This test ensures Windows azd hooks import missing var_* values from the
active azd environment before resolving resource names or running deployer
commands, and that Azure CLI interactive-auth failures are not hidden behind
generic resource lookup errors.
"""

from pathlib import Path
import re
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
AZURE_YAML = REPO_ROOT / "deployers" / "azure.yaml"


HOOK_VARIABLES = {
    "postprovision": [
        "AZURE_SUBSCRIPTION_ID",
        "var_authenticationType",
        "var_blobStorageEndpoint",
        "var_configureApplication",
        "var_cosmosDb_accountName",
        "var_cosmosDb_uri",
        "var_openAIGPTModels",
        "var_openAIEmbeddingModels",
        "var_rgName",
        "var_subscriptionId",
        "var_webService",
    ],
    "predeploy": [
        "AZURE_SUBSCRIPTION_ID",
        "SIMPLECHAT_INSTALL_CHROMIUM",
        "var_acrName",
        "var_containerRegistry",
        "var_cosmosDb_accountName",
        "var_cosmosDb_uri",
        "var_enablePrivateNetworking",
        "var_imageName",
        "var_rgName",
        "var_subscriptionId",
        "var_webService",
    ],
    "postup": [
        "AZURE_SUBSCRIPTION_ID",
        "var_acrName",
        "var_cosmosDb_accountName",
        "var_cosmosDb_uri",
        "var_enablePrivateNetworking",
        "var_keyVaultName",
        "var_rgName",
        "var_subscriptionId",
        "var_webService",
    ],
}


def read_text(path: Path) -> str:
    """Read a workspace file as UTF-8 text."""
    return path.read_text(encoding="utf-8")


def get_hook_section(content: str, hook_name: str) -> str:
    """Return a top-level azd hook section from azure.yaml."""
    hook_markers = list(re.finditer(r"^  ([a-z][A-Za-z0-9_-]*):\s*$", content, re.MULTILINE))
    for index, marker in enumerate(hook_markers):
        if marker.group(1) != hook_name:
            continue

        section_end = hook_markers[index + 1].start() if index + 1 < len(hook_markers) else len(content)
        return content[marker.start():section_end]

    raise AssertionError(f"Hook section not found: {hook_name}")


def assert_windows_hook_imports_environment(hook_name: str, section: str) -> None:
    """Validate a Windows hook imports required azd environment values."""
    assert "windows:" in section, f"Expected {hook_name} to define a Windows hook."
    assert section.count("function Import-AzdHookEnvironment") == 1, (
        f"Expected {hook_name} to define the azd environment import helper once."
    )
    assert "azd env get-value $name 2>$null" in section, (
        f"Expected {hook_name} to read missing values from azd env get-value."
    )
    assert "[Environment]::SetEnvironmentVariable($name, $resolvedText, 'Process')" in section, (
        f"Expected {hook_name} to set missing values in the process environment."
    )
    assert section.index("Import-AzdHookEnvironment -Names @(") < section.index("function Get-TargetSubscriptionId"), (
        f"Expected {hook_name} to hydrate the environment before resolving the subscription."
    )
    assert "function Test-AzureCliAuthRequired" in section, (
        f"Expected {hook_name} to detect Azure CLI interactive-auth failures."
    )
    assert "function Assert-ResourceLookupSucceeded" in section, (
        f"Expected {hook_name} to inspect Azure CLI resource lookup failures."
    )
    assert "Azure CLI requires interactive authentication while" in section, (
        f"Expected {hook_name} to report the Azure CLI login requirement clearly."
    )
    assert "https://management.core.windows.net//.default" in section, (
        f"Expected {hook_name} to include the management scope login command."
    )
    assert "az group exists --name $env:var_rgName" in section, (
        f"Expected {hook_name} to verify var_rgName through Azure CLI."
    )
    assert "2>&1 | Out-String" in section, (
        f"Expected {hook_name} to preserve Azure CLI error output for diagnostics."
    )

    for variable_name in HOOK_VARIABLES[hook_name]:
        assert f"'{variable_name}'" in section, f"Expected {hook_name} to import {variable_name}."


def test_azd_windows_hook_environment_hydration() -> bool:
    """Validate Windows azd hooks hydrate var_* values from azd environment storage."""
    print("Testing azd Windows hook environment hydration")
    print("=" * 70)

    azure_yaml = read_text(AZURE_YAML)
    for hook_name in HOOK_VARIABLES:
        section = get_hook_section(azure_yaml, hook_name)
        assert_windows_hook_imports_environment(hook_name, section)
        print(f"PASS {hook_name} imports required azd environment values")

    print("Windows azd hooks can resolve stored deployment outputs and surface Azure CLI auth failures.")
    return True


if __name__ == "__main__":
    try:
        success = test_azd_windows_hook_environment_hydration()
    except Exception as ex:
        print(f"Test failed: {ex}")
        raise

    sys.exit(0 if success else 1)