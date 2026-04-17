# test_cosmos_query_plugin.py
#!/usr/bin/env python3
"""
Functional test for the Cosmos query plugin.
Version: 0.241.024
Implemented in: 0.241.024

This test ensures that the Cosmos query plugin enforces read-only query rules,
normalizes query parameters, supports account-key authentication, exposes
container guidance to the model, and can be discovered by the shared plugin
loader.
"""

import os
import sys
import importlib


sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))


def build_manifest(max_items=2, timeout=15, field_hints=None, auth_type="identity", auth_key=""):
    auth = {"type": auth_type}
    if auth_type == "key":
        auth["key"] = auth_key
    else:
        auth["identity"] = "managed_identity"

    return {
        "name": "test_cosmos_query",
        "displayName": "Test Cosmos Query",
        "type": "cosmos_query",
        "description": "Read-only Cosmos DB test plugin",
        "endpoint": "https://example.documents.azure.com:443/",
        "auth": auth,
        "metadata": {
            "description": "Cosmos query plugin for tests"
        },
        "additionalFields": {
            "database_name": "SimpleChat",
            "container_name": "documents",
            "partition_key_path": "/tenant_id",
            "field_hints": field_hints or ["id", "title", "tenant_id"],
            "max_items": max_items,
            "timeout": timeout
        }
    }


class FakeContainerClient:
    def __init__(self, items):
        self.items = items
        self.query_kwargs = None

    def query_items(self, **kwargs):
        self.query_kwargs = kwargs
        response_hook = kwargs.get("response_hook")
        if callable(response_hook):
            response_hook(
                {
                    "x-ms-request-charge": "2.5",
                    "x-ms-documentdb-query-metrics": "retrievedDocumentCount=2",
                    "x-ms-activity-id": "activity-123"
                },
                {}
            )
        return iter(self.items)


class FakeCosmosSdkDatabaseClient:
    def get_container_client(self, container_name):
        FakeCosmosSdkClient.last_call["container_name"] = container_name
        return FakeContainerClient([])


class FakeCosmosSdkClient:
    last_call = {}

    def __init__(self, endpoint, credential, timeout=None, connection_timeout=None):
        FakeCosmosSdkClient.last_call = {
            "endpoint": endpoint,
            "credential": credential,
            "timeout": timeout,
            "connection_timeout": connection_timeout,
        }

    @classmethod
    def reset(cls):
        cls.last_call = {}

    def get_database_client(self, database_name):
        FakeCosmosSdkClient.last_call["database_name"] = database_name
        return FakeCosmosSdkDatabaseClient()


def get_cosmos_query_plugin_class():
    module = importlib.import_module("semantic_kernel_plugins.cosmos_query_plugin")
    return module.CosmosQueryPlugin


def get_discover_plugins_function():
    module = importlib.import_module("semantic_kernel_plugins.plugin_loader")
    return module.discover_plugins


def test_cosmos_query_validation_blocks_mutations():
    """Test that non-SELECT and mutation queries are rejected."""
    print("🔍 Testing Cosmos query validation rules...")

    try:
        CosmosQueryPlugin = get_cosmos_query_plugin_class()
        plugin = CosmosQueryPlugin(build_manifest())
        validation = plugin.validate_query("DELETE FROM c WHERE c.id = '1'")

        assert validation.data["is_valid"] is False, "Mutation queries must be rejected"
        assert any("SELECT" in issue for issue in validation.data["issues"]), "Validation should require SELECT queries"
        assert any("not allowed" in issue for issue in validation.data["issues"]), "Validation should flag mutation keywords"

        print("✅ Cosmos query validation rejects mutation queries.")
        return True
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


def test_cosmos_query_execute_normalizes_parameters_and_limits_results():
    """Test that query execution normalizes parameters and enforces item caps."""
    print("🔍 Testing Cosmos query execution normalization...")

    try:
        CosmosQueryPlugin = get_cosmos_query_plugin_class()
        plugin = CosmosQueryPlugin(build_manifest(max_items=2))
        fake_container = FakeContainerClient(
            [
                {"id": "1", "title": "One"},
                {"id": "2", "title": "Two"},
                {"id": "3", "title": "Three"}
            ]
        )
        plugin._container_client = fake_container

        result = plugin.execute_query(
            query="SELECT c.id, c.title FROM c WHERE c.tenant_id = @tenant_id",
            parameters={"tenant_id": "tenant-a"},
            max_items=5,
            partition_key="tenant-a"
        )
        payload = result.data

        assert payload["item_count"] == 2, "Plugin should cap results at the configured max_items value"
        assert payload["is_truncated"] is True, "Plugin should mark responses truncated when extra rows exist"
        assert payload["partition_key_applied"] is True, "Partition key usage should be reported"
        assert payload["request_charge"] == "2.5", "Request charge should be captured from Cosmos response headers"

        assert fake_container.query_kwargs["parameters"] == [{"name": "@tenant_id", "value": "tenant-a"}], "Dict parameters should normalize to Cosmos parameter objects"
        assert fake_container.query_kwargs["partition_key"] == "tenant-a", "Known partition keys should be passed to the SDK"
        assert fake_container.query_kwargs["enable_cross_partition_query"] is False, "Partition-scoped queries should disable cross-partition execution"
        assert fake_container.query_kwargs["max_item_count"] == 2, "SDK call should enforce the effective max item count"

        print("✅ Cosmos query execution normalizes parameters and limits results.")
        return True
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


def test_cosmos_query_key_auth_uses_account_key_credentials():
    """Test that account-key auth wires the configured key into the Cosmos SDK client."""
    print("🔍 Testing Cosmos account key authentication wiring...")

    module = None
    original_client = None
    CosmosQueryPlugin = None

    try:
        module = importlib.import_module("semantic_kernel_plugins.cosmos_query_plugin")
        CosmosQueryPlugin = module.CosmosQueryPlugin
        original_client = module.CosmosClient
        module.CosmosClient = FakeCosmosSdkClient
        FakeCosmosSdkClient.reset()
        CosmosQueryPlugin._client_cache = {}

        plugin = CosmosQueryPlugin(build_manifest(auth_type="key", auth_key="primary-key-value"))
        plugin._get_container_client()

        assert FakeCosmosSdkClient.last_call["credential"] == "primary-key-value", "Key auth should pass the configured account key to CosmosClient"
        assert FakeCosmosSdkClient.last_call["endpoint"] == "https://example.documents.azure.com:443/", "CosmosClient should use the configured endpoint"
        assert FakeCosmosSdkClient.last_call["database_name"] == "SimpleChat", "CosmosClient should target the configured database"
        assert FakeCosmosSdkClient.last_call["container_name"] == "documents", "CosmosClient should target the configured container"

        print("✅ Cosmos account key auth uses the configured account key.")
        return True
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        if module is not None and original_client is not None:
            module.CosmosClient = original_client
        if CosmosQueryPlugin is not None:
            CosmosQueryPlugin._client_cache = {}


def test_cosmos_instruction_context_and_loader_discovery():
    """Test that instruction context and dynamic loader discovery expose Cosmos hints."""
    print("🔍 Testing Cosmos instruction context and loader discovery...")

    try:
        CosmosQueryPlugin = get_cosmos_query_plugin_class()
        discover_plugins = get_discover_plugins_function()
        plugin = CosmosQueryPlugin(build_manifest(field_hints=["id", "title", "tenant_id", "category"]))
        instruction_context = plugin.build_instruction_context()

        assert "SimpleChat.documents" in instruction_context, "Instruction context should include the target database and container"
        assert "Partition key path: /tenant_id" in instruction_context, "Instruction context should include the partition key path"
        assert "- category" in instruction_context, "Instruction context should include configured field hints"

        discovered_plugins = discover_plugins()
        assert "CosmosQueryPlugin" in discovered_plugins, "Dynamic plugin discovery should include CosmosQueryPlugin"

        print("✅ Cosmos instruction context and loader discovery are available.")
        return True
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    tests = [
        test_cosmos_query_validation_blocks_mutations,
        test_cosmos_query_execute_normalizes_parameters_and_limits_results,
        test_cosmos_query_key_auth_uses_account_key_credentials,
        test_cosmos_instruction_context_and_loader_discovery,
    ]
    results = []

    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)