#!/usr/bin/env python3
# test_acr_trusted_services_bypass.py
"""
Functional test for ACR trusted Azure services bypass.
Version: 0.237.063
Implemented in: 0.237.063

This test ensures private-network Azure Container Registry deployments keep the
registry reachable for az acr build until the final postup lockdown step and avoid
Windows log-streaming failures by polling run status instead.
"""

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
ACR_MODULE = REPO_ROOT / "deployers" / "bicep" / "modules" / "azureContainerRegistry.bicep"
AZURE_YAML = REPO_ROOT / "deployers" / "azure.yaml"


def require_contains(content: str, expected: str, description: str) -> None:
    if expected not in content:
        raise AssertionError(f"Missing {description}: {expected}")


def test_acr_trusted_services_bypass() -> bool:
    print("🧪 Testing ACR trusted Azure services bypass")
    print("=" * 70)

    content = ACR_MODULE.read_text(encoding="utf-8")
    hook_content = AZURE_YAML.read_text(encoding="utf-8")

    require_contains(content, "networkRuleBypassOptions: enablePrivateNetworking ? 'AzureServices' : 'None'", "trusted Azure services bypass")
    require_contains(content, "networkRuleSet: enablePrivateNetworking ? {", "private-network registry rule set")
    require_contains(content, "defaultAction: 'Allow'", "deployment-time ACR public access")
    require_contains(content, "ipRules: allowedIpAddresses", "registry IP allow list wiring")
    require_contains(hook_content, "ACR public access remains enabled until POST-UP", "deployment-time ACR access message")
    require_contains(hook_content, "--public-network-enabled false", "postup ACR public access disable step")
    require_contains(hook_content, "--no-logs --query runId -o tsv", "Windows non-streaming ACR build invocation")
    require_contains(hook_content, "Wait-ForAcrBuildRun", "Windows ACR run polling helper")
    require_contains(hook_content, "az acr task show-run", "Windows ACR run status polling command")

    print("✅ ACR module enables trusted Azure services when private networking is on")
    print("✅ ACR module keeps the registry firewall rule set in place")
    print("✅ ACR module keeps public access enabled during deployment-time builds")
    print("✅ ACR module still honors explicit allowed IP addresses")
    print("✅ Predeploy relies on deployment-time ACR access instead of live firewall edits")
    print("✅ POST-UP still disables ACR public access after deployment")
    print("✅ Windows predeploy queues ACR builds without streaming logs")
    print("✅ Windows predeploy polls ACR run status instead of streaming Unicode logs")
    return True


if __name__ == "__main__":
    try:
        success = test_acr_trusted_services_bypass()
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        raise

    sys.exit(0 if success else 1)