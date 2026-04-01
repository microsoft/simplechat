#!/usr/bin/env python3
# test_azd_windows_hooks.py
"""
Functional test for AZD Windows hook coverage.
Version: 0.237.060
Implemented in: 0.237.060

This test ensures that azure.yaml defines Windows run hooks for the AZD lifecycle
stages that are used after infrastructure provisioning.
"""

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
AZURE_YAML = REPO_ROOT / "deployers" / "azure.yaml"


def require_contains(content: str, expected: str, description: str) -> None:
    if expected not in content:
        raise AssertionError(f"Missing {description}: {expected}")


def test_azd_windows_hooks() -> bool:
    print("🧪 Testing AZD Windows hook coverage")
    print("=" * 60)

    content = AZURE_YAML.read_text(encoding="utf-8")

    require_contains(content, "postprovision:\n", "postprovision hook section")
    require_contains(content, "predeploy:\n", "predeploy hook section")
    require_contains(content, "postup:\n", "postup hook section")
    require_contains(content, "shell: pwsh", "Windows shell declarations")
    require_contains(content, "POST-PROVISION: Starting configuration", "Windows postprovision hook")
    require_contains(content, "PRE-DEPLOY: Building and pushing image", "Windows predeploy hook")
    require_contains(content, "POST-UP: Final configuration", "Windows postup hook")
    require_contains(content, "function Resolve-ResourceGroupName", "helper function for RG fallback")
    require_contains(content, "function Get-TargetSubscriptionId", "helper function for subscription targeting")
    require_contains(content, "az group exists --name", "resource group validation")
    require_contains(content, "az cosmosdb list", "Cosmos DB RG discovery fallback")
    require_contains(content, "az cosmosdb keys list", "Cosmos DB key retrieval for postconfig")
    require_contains(content, "Ensure-CosmosRunnerAccess", "Cosmos firewall helper")
    require_contains(content, "Test-CosmosRunnerAccess", "Cosmos access probe helper")
    require_contains(content, "Test-RunnerIpMatchesRules", "Cosmos firewall CIDR coverage helper")
    require_contains(content, "Wait-ForCosmosRunnerAccess", "Cosmos firewall propagation wait helper")
    require_contains(content, "api.ipify.org", "deployment runner public IP lookup")
    require_contains(content, "az cosmosdb update", "Cosmos firewall update command")
    require_contains(content, "Manually add IP $runnerPublicIp", "manual Cosmos firewall guidance")
    require_contains(content, "Azure CLI requires multi-factor authentication", "explicit MFA guidance")
    require_contains(content, "Checking whether CosmosDB access is already available without an Azure CLI firewall update", "Cosmos MFA fallback access check")
    require_contains(content, "Deployment runner already has CosmosDB data-plane access", "Cosmos access short-circuit")
    require_contains(content, "Waiting for CosmosDB firewall propagation", "Cosmos propagation wait messaging")
    require_contains(content, "$env:var_cosmosDb_key", "Cosmos DB key propagation")
    require_contains(content, "--subscription $subscriptionId", "subscription-pinned Azure CLI commands")
    require_contains(content, "$env:var_rgName = $resolvedResourceGroup", "resolved RG propagation")

    print("✅ Windows postprovision hook is present")
    print("✅ Windows predeploy hook is present")
    print("✅ Windows postup hook is present")
    print("✅ Windows RG fallback logic is validated")
    print("✅ Windows postconfig Cosmos key fallback is validated")
    print("✅ Windows Cosmos firewall runner access handling is validated")
    print("✅ Windows Cosmos access short-circuit is validated")
    print("✅ Windows Cosmos firewall propagation handling is validated")
    print("✅ Windows Cosmos MFA fallback access handling is validated")
    print("✅ Windows MFA recovery guidance is validated")
    print("✅ Windows subscription targeting is validated")
    print("✅ Environment variable propagation is covered")
    return True


if __name__ == "__main__":
    try:
        success = test_azd_windows_hooks()
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        raise

    sys.exit(0 if success else 1)