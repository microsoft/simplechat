#!/usr/bin/env python3
# test_rocksdb_plugin.py
"""
Functional test for the RocksDB action (plugin).
Version: 0.250.215
Implemented in: 0.250.215

This test ensures that the RocksDB plugin validates its manifest, blocks writes while the
action is read-only, shapes RocksDB HTTP service calls and auth headers correctly, caps
result counts and oversized values, and is discoverable by the shared plugin loader.

The plugin only talks to a remote RocksDB HTTP service; SimpleChat never opens a RocksDB
database directory locally.
"""

import importlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))

from test_support.versioning import assert_app_version_at_least


class FakeConfigCosmosContainer:
    """Minimal Cosmos container stand-in for importing config.py without live I/O."""

    def read_item(self, item, partition_key=None):
        if item == "app_settings":
            return {"id": "app_settings", "settings": {}}
        raise KeyError(item)

    def upsert_item(self, item):
        return item

    def query_items(self, *args, **kwargs):
        return []


class FakeConfigCosmosDatabase:
    """Minimal Cosmos database stand-in for config.py import-time container setup."""

    def __init__(self):
        self.containers = {}

    def create_container_if_not_exists(self, id, **kwargs):
        self.containers.setdefault(id, FakeConfigCosmosContainer())
        return self.containers[id]


class FakeConfigCosmosClient:
    """Minimal Cosmos client stand-in for config.py import-time client setup."""

    def __init__(self, *args, **kwargs):
        self.database = FakeConfigCosmosDatabase()

    def create_database_if_not_exists(self, *args, **kwargs):
        return self.database


def import_app_module_without_live_cosmos(module_name):
    """Import app modules without letting config.py connect to live Cosmos."""
    if module_name in sys.modules:
        return sys.modules[module_name]

    import azure.cosmos as azure_cosmos

    original_cosmos_client = azure_cosmos.CosmosClient
    azure_cosmos.CosmosClient = FakeConfigCosmosClient
    try:
        return importlib.import_module(module_name)
    finally:
        azure_cosmos.CosmosClient = original_cosmos_client


def get_rocksdb_module():
    return import_app_module_without_live_cosmos("semantic_kernel_plugins.rocksdb_plugin")


def get_rocksdb_plugin_class():
    return get_rocksdb_module().RocksDbPlugin


def build_manifest(auth_key="", **additional_overrides):
    additional_fields = {
        "base_url": "https://rocksdb.example.com/api",
        "auth_scheme": "none",
        "api_key_header": "X-API-Key",
        "verify_tls": True,
        "column_family": "default",
        "key_encoding": "utf8",
        "value_encoding": "utf8",
        "key_prefix_hints": ["user:", "event:"],
        "read_only": True,
        "max_results": 10,
        "max_value_bytes": 1024,
        "timeout": 10,
    }
    additional_fields.update(additional_overrides)
    auth = {"type": "key", "key": auth_key} if auth_key else {"type": "NoAuth"}
    return {
        "name": "test_rocksdb",
        "displayName": "Test RocksDB",
        "type": "rocksdb",
        "description": "RocksDB test action",
        "endpoint": additional_fields["base_url"],
        "auth": auth,
        "metadata": {"description": "RocksDB plugin for tests"},
        "additionalFields": additional_fields,
    }


class FakeResponse:
    """Minimal requests.Response stand-in for RocksDB service calls."""

    def __init__(self, status_code=200, payload=None, invalid_json=False):
        self.status_code = status_code
        self._payload = {} if payload is None else payload
        self._invalid_json = invalid_json

    def json(self):
        if self._invalid_json:
            raise ValueError("Response body is not JSON")
        return self._payload


class FakeSession:
    """Records outbound RocksDB service calls and returns scripted responses."""

    def __init__(self, response=None):
        self.calls = []
        self.response = response or FakeResponse()

    def request(self, method, url, json=None, headers=None, timeout=None, verify=None):
        self.calls.append({
            "method": method,
            "url": url,
            "payload": json,
            "headers": headers or {},
            "timeout": timeout,
            "verify": verify,
        })
        return self.response


def make_plugin(response=None, **manifest_overrides):
    """Build a plugin wired to a fake HTTP session."""
    RocksDbPlugin = get_rocksdb_plugin_class()
    auth_key = manifest_overrides.pop("auth_key", "")
    plugin = RocksDbPlugin(build_manifest(auth_key=auth_key, **manifest_overrides))
    session = FakeSession(response)
    plugin.set_http_session(session)
    return plugin, session


def test_manifest_validation_rules():
    """Test that invalid RocksDB manifests are rejected with actionable errors."""
    print("🔍 Testing RocksDB manifest validation...")

    try:
        RocksDbPlugin = get_rocksdb_plugin_class()

        invalid_cases = [
            (build_manifest(base_url=""), "base_url"),
            (build_manifest(base_url="ftp://rocks.example.com"), "http"),
            (build_manifest(base_url="https://"), "host name"),
            (build_manifest(key_encoding="hex"), "key_encoding"),
            (build_manifest(value_encoding="yaml"), "value_encoding"),
            (build_manifest(max_results=0), "max_results"),
            (build_manifest(max_results=99999), "max_results"),
            (build_manifest(max_value_bytes=0), "max_value_bytes"),
            (build_manifest(timeout=0), "timeout"),
            (build_manifest(timeout=9999), "timeout"),
            (build_manifest(auth_scheme="mtls"), "auth_scheme"),
            (build_manifest(auth_scheme="bearer"), "auth.key"),
            (build_manifest(auth_scheme="api_key"), "auth.key"),
        ]

        for manifest, expected_fragment in invalid_cases:
            try:
                RocksDbPlugin(manifest)
                raise AssertionError(
                    f"Manifest should have been rejected for '{expected_fragment}': {manifest['additionalFields']}"
                )
            except ValueError as validation_error:
                assert expected_fragment in str(validation_error), (
                    f"Expected '{expected_fragment}' in error, got: {validation_error}"
                )

        # A valid manifest constructs cleanly and normalizes the base URL.
        plugin = RocksDbPlugin(
            build_manifest(auth_key="token", auth_scheme="bearer", base_url="https://rocksdb.example.com/api/")
        )
        assert plugin.base_url == "https://rocksdb.example.com/api", "Trailing slashes must be stripped"
        assert plugin.read_only is True
        assert plugin.key_prefix_hints == ["user:", "event:"]

        # The plugin must not expose any embedded/local database configuration.
        for removed_attribute in ("db_path", "access_mode", "secondary_path", "connection_mode"):
            assert not hasattr(plugin, removed_attribute), (
                f"Embedded attribute '{removed_attribute}' must not exist on the remote-only plugin"
            )

        print("✅ RocksDB manifest validation rejects invalid configurations.")
        return True
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


def test_module_has_no_local_database_support():
    """Test that the plugin module carries no embedded RocksDB code paths."""
    print("🔍 Testing that the RocksDB plugin has no local database support...")

    try:
        rocksdb_module = get_rocksdb_module()

        for removed_symbol in (
            "import_rocksdict",
            "resolve_allowed_rocksdb_path",
            "get_allowed_rocksdb_roots",
            "CONNECTION_MODE_EMBEDDED",
            "CONNECTION_MODE_REMOTE",
            "SUPPORTED_ACCESS_MODES",
            "ACCESS_MODE_SECONDARY",
        ):
            assert not hasattr(rocksdb_module, removed_symbol), (
                f"Embedded symbol '{removed_symbol}' must not exist in the remote-only module"
            )

        module_source = open(rocksdb_module.__file__, encoding="utf-8").read()
        assert "rocksdict" not in module_source, "The module must not reference the rocksdict binding"
        assert "ROCKSDB_ALLOWED_ROOTS" not in module_source, (
            "The module must not reference the removed path allowlist"
        )

        # The dependency must be gone from the application requirements too.
        requirements_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "..", "application", "single_app", "requirements.txt"
        )
        requirements = open(requirements_path, encoding="utf-8").read()
        assert "rocksdict" not in requirements, "rocksdict must not be pinned in requirements.txt"

        print("✅ RocksDB plugin contains no embedded database code or dependency.")
        return True
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


def test_read_only_blocks_writes():
    """Test that write operations are refused while the action is read-only."""
    print("🔍 Testing RocksDB read-only write guard...")

    try:
        plugin, session = make_plugin(read_only=True)

        blocked_results = [
            plugin.put_value("user:001", "alice"),
            plugin.delete_value("user:001"),
            plugin.write_batch([{"op": "put", "key": "user:001", "value": "alice"}]),
        ]

        for blocked_result in blocked_results:
            assert blocked_result.data.get("read_only") is True, "Write guard must report read_only"
            assert "read-only" in blocked_result.data.get("error", ""), "Write guard must explain the refusal"

        assert session.calls == [], "Read-only writes must never reach the RocksDB service"

        print("✅ RocksDB read-only actions refuse put, delete, and batch operations.")
        return True
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


def test_read_request_shaping():
    """Test RocksDB service request paths and payloads for read operations."""
    print("🔍 Testing RocksDB read request shaping...")

    try:
        plugin, session = make_plugin(FakeResponse(payload={"found": True, "value": "alice"}))

        result = plugin.get_value("user:001")
        assert result.data["found"] is True
        assert result.data["value"] == "alice"

        call = session.calls[-1]
        assert call["method"] == "POST"
        assert call["url"] == "https://rocksdb.example.com/api/get"
        assert call["payload"]["key"] == "user:001"
        assert call["payload"]["column_family"] == "default"
        assert call["payload"]["key_encoding"] == "utf8", "The service needs the key wire encoding"
        assert call["payload"]["value_encoding"] == "utf8", "The service needs the value wire encoding"
        assert call["timeout"] == 10
        assert call["verify"] is True

        # A column family override is forwarded per call.
        plugin.get_value("user:001", column_family="events")
        assert session.calls[-1]["payload"]["column_family"] == "events"

        # Multi-get posts the key list.
        multi_plugin, multi_session = make_plugin(
            FakeResponse(payload={"results": [
                {"key": "user:001", "found": True, "value": "alice"},
                {"key": "user:404", "found": False, "value": None},
            ]})
        )
        multi_result = multi_plugin.get_values(["user:001", "user:404"])
        assert multi_result.data["requested_key_count"] == 2
        assert multi_result.data["found_count"] == 1
        assert multi_session.calls[-1]["url"] == "https://rocksdb.example.com/api/multi_get"
        assert multi_session.calls[-1]["payload"]["keys"] == ["user:001", "user:404"]

        # Keys may arrive as a JSON array string from the model.
        multi_plugin.get_values('["user:001", "user:002"]')
        assert multi_session.calls[-1]["payload"]["keys"] == ["user:001", "user:002"]

        # Existence checks use the dedicated endpoint.
        exists_plugin, exists_session = make_plugin(FakeResponse(payload={"exists": True}))
        assert exists_plugin.key_exists("user:001").data["exists"] is True
        assert exists_session.calls[-1]["url"] == "https://rocksdb.example.com/api/exists"

        # Range scans forward the range arguments.
        scan_plugin, scan_session = make_plugin(
            FakeResponse(payload={"items": [{"key": "user:001", "value": "alice"}]})
        )
        range_result = scan_plugin.scan_range(start_key="user:001", end_key="user:009", reverse=True)
        assert range_result.data["reverse"] is True
        scan_payload = scan_session.calls[-1]["payload"]
        assert scan_payload["start_key"] == "user:001"
        assert scan_payload["end_key"] == "user:009"
        assert scan_payload["reverse"] is True
        assert "prefix" not in scan_payload, "Range scans must not send an empty prefix"

        # Prefix scans send the prefix and omit range bounds.
        scan_plugin.scan_prefix("user:")
        prefix_payload = scan_session.calls[-1]["payload"]
        assert prefix_payload["prefix"] == "user:"
        assert "start_key" not in prefix_payload and "end_key" not in prefix_payload

        # Column families and stats use GET endpoints.
        cf_plugin, cf_session = make_plugin(FakeResponse(payload={"column_families": ["default", "events"]}))
        assert cf_plugin.list_column_families().data["column_families"] == ["default", "events"]
        assert cf_session.calls[-1]["method"] == "GET"
        assert cf_session.calls[-1]["url"] == "https://rocksdb.example.com/api/column_families"

        stats_plugin, stats_session = make_plugin(FakeResponse(payload={"stats": {"keys": 42}}))
        assert stats_plugin.get_database_stats().data["stats"] == {"keys": 42}
        assert stats_session.calls[-1]["url"] == "https://rocksdb.example.com/api/stats"

        print("✅ RocksDB read calls use the expected paths and payloads.")
        return True
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


def test_auth_header_shaping():
    """Test that each auth scheme sends the correct credential header."""
    print("🔍 Testing RocksDB auth header shaping...")

    try:
        # No authentication sends no credential header.
        anon_plugin, anon_session = make_plugin(FakeResponse(payload={"found": False}))
        anon_plugin.get_value("user:001")
        anon_headers = anon_session.calls[-1]["headers"]
        assert "Authorization" not in anon_headers
        assert "X-API-Key" not in anon_headers

        # Bearer authentication.
        bearer_plugin, bearer_session = make_plugin(
            FakeResponse(payload={"found": False}), auth_key="secret-token", auth_scheme="bearer"
        )
        bearer_plugin.get_value("user:001")
        assert bearer_session.calls[-1]["headers"]["Authorization"] == "Bearer secret-token"

        # API key header authentication honours a custom header name.
        api_key_plugin, api_key_session = make_plugin(
            FakeResponse(payload={"found": False}),
            auth_key="header-token",
            auth_scheme="api_key",
            api_key_header="X-Rocks-Key",
        )
        api_key_plugin.get_value("user:001")
        api_key_headers = api_key_session.calls[-1]["headers"]
        assert api_key_headers["X-Rocks-Key"] == "header-token"
        assert "Authorization" not in api_key_headers

        # TLS verification is forwarded to the transport.
        insecure_plugin, insecure_session = make_plugin(
            FakeResponse(payload={"found": False}), verify_tls=False
        )
        insecure_plugin.get_value("user:001")
        assert insecure_session.calls[-1]["verify"] is False

        print("✅ RocksDB auth schemes send the expected headers.")
        return True
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


def test_result_caps_and_truncation():
    """Test that result counts and oversized values are capped."""
    print("🔍 Testing RocksDB result caps and value truncation...")

    try:
        # max_results caps scan output even when the service returns more.
        scan_plugin, scan_session = make_plugin(
            FakeResponse(payload={"items": [{"key": f"user:{i:03d}", "value": "v"} for i in range(25)]})
        )
        scan_result = scan_plugin.scan_prefix("user:")
        assert scan_result.data["item_count"] == 10, "max_results must cap scan output"
        assert scan_result.data["is_truncated"] is True
        assert scan_session.calls[-1]["payload"]["limit"] == 10

        # A per-call limit cannot exceed the configured cap.
        scan_plugin.scan_prefix("user:", limit=500)
        assert scan_session.calls[-1]["payload"]["limit"] == 10
        scan_plugin.scan_prefix("user:", limit=3)
        assert scan_session.calls[-1]["payload"]["limit"] == 3

        # max_results also caps the requested key list.
        multi_plugin, multi_session = make_plugin(FakeResponse(payload={"results": []}))
        multi_plugin.get_values([f"user:{i:03d}" for i in range(50)])
        assert len(multi_session.calls[-1]["payload"]["keys"]) == 10

        # Oversized values are truncated and flagged with the original byte length.
        oversized_value = "x" * 100
        truncating_plugin, _ = make_plugin(
            FakeResponse(payload={"found": True, "value": oversized_value}), max_value_bytes=10
        )
        truncated = truncating_plugin.get_value("user:001")
        assert truncated.data["value"] == "x" * 10
        assert truncated.data["value_truncated"] is True
        assert truncated.data["value_bytes"] == 100

        # Values within the cap pass through untouched, including structured JSON.
        json_plugin, _ = make_plugin(FakeResponse(payload={"found": True, "value": {"kind": "login"}}))
        json_result = json_plugin.get_value("event:001")
        assert json_result.data["value"] == {"kind": "login"}
        assert json_result.data["value_truncated"] is False

        # Batch size is bounded by max_results.
        batch_plugin, _ = make_plugin(FakeResponse(payload={"success": True}), read_only=False)
        oversized_batch = [{"op": "put", "key": f"k{i}", "value": "v"} for i in range(50)]
        batch_result = batch_plugin.write_batch(oversized_batch)
        assert "limited to 10" in batch_result.data["error"]

        print("✅ RocksDB caps result counts, key lists, batches, and oversized values.")
        return True
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


def test_write_operations_when_enabled():
    """Test that writes reach the service once the action allows them."""
    print("🔍 Testing RocksDB write operations...")

    try:
        plugin, session = make_plugin(FakeResponse(payload={"success": True}), read_only=False)

        put_result = plugin.put_value("user:009", "ivan")
        assert put_result.data["written"] is True
        assert session.calls[-1]["url"] == "https://rocksdb.example.com/api/put"
        assert session.calls[-1]["payload"]["value"] == "ivan"

        delete_result = plugin.delete_value("user:009")
        assert delete_result.data["deleted"] is True
        assert session.calls[-1]["url"] == "https://rocksdb.example.com/api/delete"

        batch_result = plugin.write_batch(
            '[{"op": "put", "key": "user:005", "value": "erin"}, {"op": "delete", "key": "user:004"}]'
        )
        assert batch_result.data["applied"] is True
        assert batch_result.data["operation_count"] == 2
        assert session.calls[-1]["url"] == "https://rocksdb.example.com/api/batch"
        assert session.calls[-1]["payload"]["operations"][0]["op"] == "put"
        assert session.calls[-1]["payload"]["operations"][1]["op"] == "delete"

        # Malformed batch operations are rejected before any request is sent.
        call_count = len(session.calls)
        bad_batch = plugin.write_batch('[{"op": "drop", "key": "user:001"}]')
        assert "put" in bad_batch.data["error"] and "delete" in bad_batch.data["error"]
        assert len(session.calls) == call_count, "Invalid batches must not reach the service"

        missing_key_batch = plugin.write_batch([{"op": "put", "value": "v"}])
        assert "key" in missing_key_batch.data["error"]

        print("✅ RocksDB write operations reach the service when writes are enabled.")
        return True
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


def test_service_error_handling():
    """Test that service failures surface as structured errors without leaking bodies."""
    print("🔍 Testing RocksDB service error handling...")

    try:
        # HTTP failures report the status code only.
        error_plugin, _ = make_plugin(FakeResponse(status_code=503, payload={"secret": "leak"}))
        error_result = error_plugin.get_value("user:001")
        assert "503" in error_result.data["error"]
        assert "leak" not in error_result.data["error"], "Response bodies must never be echoed"

        # Non-JSON responses are reported clearly.
        invalid_plugin, _ = make_plugin(FakeResponse(invalid_json=True))
        assert "non-JSON" in invalid_plugin.get_value("user:001").data["error"]

        # Unexpected payload shapes are rejected rather than silently mishandled.
        shape_plugin, _ = make_plugin(FakeResponse(payload={"items": "not-a-list"}))
        assert "unexpected scan payload" in shape_plugin.scan_prefix("user:").data["error"]

        multi_shape_plugin, _ = make_plugin(FakeResponse(payload={"results": "nope"}))
        assert "unexpected multi_get payload" in multi_shape_plugin.get_values(["a"]).data["error"]

        cf_shape_plugin, _ = make_plugin(FakeResponse(payload={"column_families": "nope"}))
        assert "unexpected column_families payload" in cf_shape_plugin.list_column_families().data["error"]

        # Transport exceptions are captured instead of propagating to the kernel.
        class ExplodingSession:
            def request(self, *args, **kwargs):
                raise ConnectionError("connection refused")

        RocksDbPlugin = get_rocksdb_plugin_class()
        exploding_plugin = RocksDbPlugin(build_manifest())
        exploding_plugin.set_http_session(ExplodingSession())
        assert "connection refused" in exploding_plugin.get_value("user:001").data["error"]

        print("✅ RocksDB service failures produce structured, non-leaking errors.")
        return True
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


def test_health_checker_validation():
    """Test that the shared plugin health checker validates RocksDB manifests."""
    print("🔍 Testing RocksDB manifest validation in the plugin health checker...")

    try:
        health_module = import_app_module_without_live_cosmos(
            "semantic_kernel_plugins.plugin_health_checker"
        )
        PluginHealthChecker = health_module.PluginHealthChecker

        valid_manifest = build_manifest(auth_key="token", auth_scheme="bearer")
        is_valid, errors = PluginHealthChecker.validate_plugin_manifest(valid_manifest, "rocksdb")
        assert is_valid, f"Valid RocksDB manifest was rejected: {errors}"

        invalid_cases = [
            (build_manifest(base_url=""), "base_url"),
            (build_manifest(base_url="ftp://rocks.example.com"), "base_url"),
            (build_manifest(auth_scheme="bearer"), "auth.key"),
            (build_manifest(auth_scheme="mtls"), "auth_scheme"),
            (build_manifest(max_results=99999), "max_results"),
            (build_manifest(timeout="soon"), "timeout"),
            (build_manifest(value_encoding="yaml"), "value_encoding"),
            (build_manifest(key_encoding="hex"), "key_encoding"),
        ]

        for manifest, expected_fragment in invalid_cases:
            is_valid, errors = PluginHealthChecker.validate_plugin_manifest(manifest, "rocksdb")
            assert not is_valid, f"Manifest should be invalid for '{expected_fragment}'"
            assert any(expected_fragment in error for error in errors), (
                f"Expected '{expected_fragment}' in {errors}"
            )

        print("✅ Plugin health checker validates RocksDB manifests.")
        return True
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


def test_plugin_discovery_and_metadata():
    """Test that the RocksDB plugin is discoverable and exposes its expected surface."""
    print("🔍 Testing RocksDB plugin discovery and metadata...")

    try:
        assert_app_version_at_least("0.250.215")

        loader_module = import_app_module_without_live_cosmos(
            "semantic_kernel_plugins.plugin_loader"
        )
        discovered_plugins = loader_module.discover_plugins()
        assert "RocksDbPlugin" in discovered_plugins, (
            f"RocksDbPlugin must be discoverable, found: {sorted(discovered_plugins)}"
        )

        RocksDbPlugin = get_rocksdb_plugin_class()
        plugin = RocksDbPlugin(build_manifest())

        assert plugin.display_name == "RocksDB"
        assert plugin.metadata["type"] == "rocksdb"
        assert "read-only" in plugin.metadata["description"]
        assert "HTTP service" in plugin.metadata["description"]

        expected_functions = {
            "get_value",
            "get_values",
            "key_exists",
            "scan_prefix",
            "scan_range",
            "list_column_families",
            "get_database_stats",
            "put_value",
            "delete_value",
            "write_batch",
        }
        assert set(plugin.get_functions()) == expected_functions
        documented_methods = {method["name"] for method in plugin.metadata["methods"]}
        assert documented_methods == expected_functions, (
            "Every exposed function must be documented in plugin metadata"
        )

        writable_plugin = RocksDbPlugin(build_manifest(read_only=False))
        assert "Write operations are enabled" in writable_plugin.metadata["description"]

        # Instruction context surfaces the service target and prefix hints.
        instruction_context = plugin.build_instruction_context()
        assert "https://rocksdb.example.com/api" in instruction_context
        assert "user:" in instruction_context
        assert "read-only" in instruction_context

        print("✅ RocksDB plugin is discoverable and exposes complete metadata.")
        return True
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    tests = [
        test_manifest_validation_rules,
        test_module_has_no_local_database_support,
        test_read_only_blocks_writes,
        test_read_request_shaping,
        test_auth_header_shaping,
        test_result_caps_and_truncation,
        test_write_operations_when_enabled,
        test_service_error_handling,
        test_health_checker_validation,
        test_plugin_discovery_and_metadata,
    ]

    results = []
    for test in tests:
        print(f"\n🧪 Running {test.__name__}...")
        results.append(test())

    success = all(results)
    print(f"\n📊 Results: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)
