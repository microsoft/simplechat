# test_core_service_key_deployment_path.py
#!/usr/bin/env python3
"""
Functional test for core service key deployment path.
Version: 0.240.003
Implemented in: 0.240.002

This test ensures that core service key authentication is populated directly from
Azure resources during deployment instead of depending on Key Vault secret reads.
"""

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
POSTCONFIG_PATH = REPO_ROOT / "deployers" / "bicep" / "postconfig.py"
APP_SERVICE_BICEP_PATH = REPO_ROOT / "deployers" / "bicep" / "modules" / "appService.bicep"
CONFIG_PATH = REPO_ROOT / "application" / "single_app" / "config.py"
CORE_MODULE_PATHS = [
    REPO_ROOT / "deployers" / "bicep" / "modules" / "azureContainerRegistry.bicep",
    REPO_ROOT / "deployers" / "bicep" / "modules" / "contentSafety.bicep",
    REPO_ROOT / "deployers" / "bicep" / "modules" / "cosmosDb.bicep",
    REPO_ROOT / "deployers" / "bicep" / "modules" / "documentIntelligence.bicep",
    REPO_ROOT / "deployers" / "bicep" / "modules" / "openAI.bicep",
    REPO_ROOT / "deployers" / "bicep" / "modules" / "redisCache.bicep",
    REPO_ROOT / "deployers" / "bicep" / "modules" / "search.bicep",
    REPO_ROOT / "deployers" / "bicep" / "modules" / "speechService.bicep",
]


def read_text(path):
    return path.read_text(encoding="utf-8")


def test_postconfig_uses_direct_core_key_retrieval():
    """Verify postconfig retrieves core keys from Azure resources instead of Key Vault."""
    print("🔍 Testing postconfig core key retrieval path...")

    content = read_text(POSTCONFIG_PATH)

    required_snippets = [
        "get_azure_cli_executable()",
        'candidate_names = ["az.cmd", "az.exe", "az"]',
        "cognitiveservices",
        "search",
        "admin-key",
        "redis",
        "list-keys",
        "get_core_service_keys(",
    ]
    forbidden_snippets = [
        'get_secret("openAi-key")',
        'get_secret("content-safety-key")',
        'get_secret("redis-cache-key")',
        'get_secret("search-service-key")',
        'get_secret("document-intelligence-key")',
        'get_secret("speech-service-key")',
        "SecretClient",
    ]

    for snippet in required_snippets:
        if snippet not in content:
            print(f"❌ Missing expected postconfig snippet: {snippet}")
            return False

    for snippet in forbidden_snippets:
        if snippet in content:
            print(f"❌ Found forbidden Key Vault dependency in postconfig: {snippet}")
            return False

    print("✅ Postconfig retrieves core keys directly from Azure resources")
    return True


def test_app_service_uses_direct_core_key_values():
    """Verify App Service no longer depends on Key Vault references for core key auth."""
    print("🔍 Testing App Service core key wiring...")

    content = read_text(APP_SERVICE_BICEP_PATH)

    required_snippets = [
        "AZURE_COSMOS_KEY', value: cosmosDb.listKeys().primaryMasterKey",
        "DOCKER_REGISTRY_SERVER_PASSWORD",
        "value: acrService.listCredentials().passwords[0].value",
        "AZURE_SEARCH_API_KEY",
        "value: searchService.listAdminKeys().primaryKey",
        "AZURE_DOCUMENT_INTELLIGENCE_API_KEY",
        "value: documentIntelligence.listKeys().key1",
    ]
    forbidden_snippets = [
        "secrets/cosmos-db-key",
        "secrets/container-registry-key",
        "secrets/search-service-key",
        "secrets/document-intelligence-key",
    ]

    for snippet in required_snippets:
        if snippet not in content:
            print(f"❌ Missing expected App Service wiring snippet: {snippet}")
            return False

    for snippet in forbidden_snippets:
        if snippet in content:
            print(f"❌ Found forbidden Key Vault App Service reference: {snippet}")
            return False

    print("✅ App Service uses direct core resource values for key auth")
    return True


def test_core_modules_stop_storing_core_keys_in_key_vault():
    """Verify core service modules no longer write deployment-time core secrets to Key Vault."""
    print("🔍 Testing core module Key Vault secret removal...")

    forbidden_secret_names = [
        "container-registry-key",
        "content-safety-key",
        "cosmos-db-key",
        "document-intelligence-key",
        "openAi-key",
        "redis-cache-key",
        "search-service-key",
        "speech-service-key",
    ]

    for module_path in CORE_MODULE_PATHS:
        content = read_text(module_path)
        for secret_name in forbidden_secret_names:
            if secret_name in content:
                print(f"❌ Found forbidden core secret storage in {module_path.name}: {secret_name}")
                return False

    print("✅ Core service modules no longer store deployment-time core keys in Key Vault")
    return True


def test_version_updated():
    """Verify the config version matches this deployment fix."""
    print("🔍 Testing config version update...")

    content = read_text(CONFIG_PATH)
    expected_version = 'VERSION = "0.240.003"'

    if expected_version not in content:
        print(f"❌ Expected version not found in config.py: {expected_version}")
        return False

    print("✅ Config version updated for deployment fix")
    return True


if __name__ == "__main__":
    tests = [
        test_postconfig_uses_direct_core_key_retrieval,
        test_app_service_uses_direct_core_key_values,
        test_core_modules_stop_storing_core_keys_in_key_vault,
        test_version_updated,
    ]
    results = []

    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)