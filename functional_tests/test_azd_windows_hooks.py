#!/usr/bin/env python3
# test_azd_windows_hooks.py
"""
Functional test for AZD Windows hook coverage.
Version: 0.261.028
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
    if "--ip-range-filter" in content or "az cosmosdb keys list" in content:
        raise AssertionError("Hooks must not mutate Cosmos firewall rules or force key authentication")
    require_contains(content, "No key-auth fallback will be attempted", "explicit authentication failure")
    require_contains(content, "--subscription $subscriptionId", "subscription-pinned Azure CLI commands")
    require_contains(content, "$env:var_rgName = $resolvedResourceGroup", "resolved RG propagation")

    print("✅ Windows postprovision hook is present")
    print("✅ Windows predeploy hook is present")
    print("✅ Windows postup hook is present")
    print("✅ Windows RG fallback logic is validated")
    print("✅ Windows hooks do not force Cosmos key authentication")
    print("✅ Windows hooks do not mutate Cosmos firewall IP rules")
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