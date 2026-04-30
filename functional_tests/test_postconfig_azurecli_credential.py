#!/usr/bin/env python3
# test_postconfig_azurecli_credential.py
"""
Functional test for postconfig deployment credential usage.
Version: 0.237.053
Implemented in: 0.237.053

This test ensures the AZD post-deployment configuration script supports a
deployment-time Cosmos DB key fallback while still using Azure CLI credentials
for other Azure resource access such as Key Vault.
"""

from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
POSTCONFIG = REPO_ROOT / "deployers" / "bicep" / "postconfig.py"


def require_contains(content: str, expected: str, description: str) -> None:
    if expected not in content:
        raise AssertionError(f"Missing {description}: {expected}")


def require_not_contains(content: str, unexpected: str, description: str) -> None:
    if unexpected in content:
        raise AssertionError(f"Unexpected {description}: {unexpected}")


def test_postconfig_uses_repeatable_deployment_credentials() -> bool:
    print("🧪 Testing postconfig deployment credential usage")
    print("=" * 70)

    content = POSTCONFIG.read_text(encoding="utf-8")

    require_contains(content, "from azure.identity import AzureCliCredential", "Azure CLI credential import")
    require_contains(content, "credential = AzureCliCredential()", "Azure CLI credential initialization")
    require_contains(content, "cosmosKey = os.getenv(\"var_cosmosDb_key\")", "deployment Cosmos key input")
    require_contains(content, "if cosmosKey:", "Cosmos key fallback branch")
    require_contains(content, "client = CosmosClient(cosmosEndpoint, cosmosKey)", "Cosmos key client initialization")
    require_contains(content, "credential.get_token(\"https://cosmos.azure.com/.default\")", "Azure CLI token fallback")
    require_not_contains(content, "DefaultAzureCredential()", "DefaultAzureCredential initialization")

    print("✅ postconfig imports AzureCliCredential")
    print("✅ postconfig accepts a deployment Cosmos DB key fallback")
    print("✅ postconfig retains Azure CLI credential fallback for Cosmos and Key Vault")
    print("✅ postconfig no longer initializes DefaultAzureCredential")
    return True


if __name__ == "__main__":
    try:
        success = test_postconfig_uses_repeatable_deployment_credentials()
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        raise

    sys.exit(0 if success else 1)