# test_enhanced_citations_storage_deployment_fix.py
#!/usr/bin/env python3
"""
Functional test for enhanced citations storage deployment fix.
Version: 0.240.003
Implemented in: 0.240.003

This test ensures the azd post-provision configuration persists the storage
account connection string required for enhanced citations key authentication.
"""

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
POSTCONFIG_PATH = REPO_ROOT / "deployers" / "bicep" / "postconfig.py"
CONFIG_PATH = REPO_ROOT / "application" / "single_app" / "config.py"


def read_text(path):
    return path.read_text(encoding="utf-8")


def test_postconfig_populates_storage_connection_string():
    """Verify postconfig writes the enhanced citations storage connection string."""
    print("🔍 Testing enhanced citations storage connection string deployment path...")

    content = read_text(POSTCONFIG_PATH)

    required_snippets = [
        "def get_storage_account_connection_string(resource_name, resource_group, subscription_id):",
        '"storage",',
        '"show-connection-string",',
        'item["office_docs_storage_account_url"] = get_storage_account_connection_string(',
        'storage_account_name = extract_resource_name_from_endpoint(var_blobStorageEndpoint)',
    ]

    for snippet in required_snippets:
        if snippet not in content:
            print(f"❌ Missing expected postconfig snippet: {snippet}")
            return False

    print("✅ Postconfig retrieves and stores the enhanced citations storage connection string")
    return True


def test_version_updated():
    """Verify the config version matches this enhanced citations deployment fix."""
    print("🔍 Testing config version update...")

    content = read_text(CONFIG_PATH)
    expected_version = 'VERSION = "0.240.003"'

    if expected_version not in content:
        print(f"❌ Expected version not found in config.py: {expected_version}")
        return False

    print("✅ Config version updated for enhanced citations deployment fix")
    return True


if __name__ == "__main__":
    tests = [
        test_postconfig_populates_storage_connection_string,
        test_version_updated,
    ]
    results = []

    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)