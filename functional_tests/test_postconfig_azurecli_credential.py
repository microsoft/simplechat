#!/usr/bin/env python3
# test_postconfig_azurecli_credential.py
"""
Functional test for postconfig deployment credential usage.
Version: 0.261.028
Implemented in: 0.237.053

This test ensures postconfig uses tenant-scoped Azure CLI credentials and the
shared Cosmos authentication helper rather than inheriting a stale Cosmos key.
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
    require_contains(content, 'credential = AzureCliCredential(tenant_id=os.environ["AZURE_TENANT_ID"])', "tenant-scoped CLI identity")
    require_contains(content, "client = create_deployment_cosmos_client()", "shared credential-aware Cosmos check")
    require_not_contains(content, 'os.getenv("var_cosmosDb_key")', "stale key precedence")
    require_not_contains(content, "DefaultAzureCredential()", "DefaultAzureCredential initialization")

    print("✅ postconfig imports AzureCliCredential")
    print("✅ postconfig uses explicit deployment authentication selection")
    print("✅ postconfig scopes the Azure CLI credential to the deployment tenant")
    print("✅ postconfig no longer initializes DefaultAzureCredential")
    return True


if __name__ == "__main__":
    try:
        success = test_postconfig_uses_repeatable_deployment_credentials()
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        raise

    sys.exit(0 if success else 1)