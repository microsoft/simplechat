#!/usr/bin/env python3
# test_rocksdb_plugin.py
"""
Functional test for the RocksDB action (plugin).
Version: 0.250.209
Implemented in: 0.250.209

This test ensures that the RocksDB plugin validates embedded and remote manifests,
enforces the ROCKSDB_ALLOWED_ROOTS path allowlist, blocks writes while the action is
read-only, reads real embedded RocksDB data across the supported key and value
encodings, shapes remote HTTP service calls and auth headers correctly, and is
discoverable by the shared plugin loader.
"""

import importlib
import os
import shutil
import sys
import tempfile

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


def rocksdict_is_available():
    try:
        importlib.import_module("rocksdict")
        return True
    except ImportError:
        return False


def close_cached_embedded_handles():
    """Close cached RocksDB handles so temporary directories can be removed."""
    RocksDbPlugin = get_rocksdb_plugin_class()
    for cached_handle in list(RocksDbPlugin._embedded_handle_cache.values()):
        try:
            cached_handle.close()
        except Exception:
            pass
    RocksDbPlugin._embedded_handle_cache.clear()


def build_embedded_manifest(db_path, **additional_overrides):
    additional_fields = {
        "connection_mode": "embedded",
        "db_path": db_path,
        "access_mode": "read_only",
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
    return {
        "name": "test_rocksdb",
        "displayName": "Test RocksDB",
        "type": "rocksdb",
        "description": "RocksDB test action",
        "endpoint": "rocksdb://embedded",
        "auth": {"type": "NoAuth"},
        "metadata": {"description": "RocksDB plugin for tests"},
        "additionalFields": additional_fields,
    }


def build_remote_manifest(auth_key="", **additional_overrides):
    additional_fields = {
        "connection_mode": "remote",
        "base_url": "https://rocksdb.example.com/api",
        "auth_scheme": "none",
        "api_key_header": "X-API-Key",
        "verify_tls": True,
        "column_family": "default",
        "key_encoding": "utf8",
        "value_encoding": "utf8",
        "read_only": True,
        "max_results": 10,
        "max_value_bytes": 1024,
        "timeout": 10,
    }
    additional_fields.update(additional_overrides)
    auth = {"type": "key", "key": auth_key} if auth_key else {"type": "NoAuth"}
    return {
        "name": "test_rocksdb_remote",
        "displayName": "Test RocksDB Remote",
        "type": "rocksdb",
        "description": "RocksDB remote test action",
        "endpoint": additional_fields["base_url"],
        "auth": auth,
        "metadata": {"description": "RocksDB remote plugin for tests"},
        "additionalFields": additional_fields,
    }


class FakeResponse:
    """Minimal requests.Response stand-in for remote RocksDB service calls."""

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


def seed_rocksdb(db_path):
    """Create a small raw-mode RocksDB database for embedded read tests."""
    from rocksdict import Options, Rdict

    options = Options(raw_mode=True)
    options.create_if_missing(True)
    database = Rdict(db_path, options=options)
    database[b"event:001"] = b'{"kind": "login"}'
    database[b"user:001"] = b"alice"
    database[b"user:002"] = b"bob"
    database[b"user:003"] = b"carol"
    database.close()


def test_manifest_validation_rules():
    """Test that invalid RocksDB manifests are rejected with actionable errors."""
    print("🔍 Testing RocksDB manifest validation...")

    try:
        RocksDbPlugin = get_rocksdb_plugin_class()
        original_roots = os.environ.get("ROCKSDB_ALLOWED_ROOTS")
        os.environ["ROCKSDB_ALLOWED_ROOTS"] = tempfile.gettempdir()

        invalid_cases = [
            (build_embedded_manifest(""), "database path"),
            (build_embedded_manifest("db", connection_mode="sideways"), "connection_mode"),
            (build_embedded_manifest("db", key_encoding="hex"), "key_encoding"),
            (build_embedded_manifest("db", value_encoding="yaml"), "value_encoding"),
            (build_embedded_manifest("db", max_results=0), "max_results"),
            (build_embedded_manifest("db", max_value_bytes=0), "max_value_bytes"),
            (build_embedded_manifest("db", timeout=0), "timeout"),
            (build_embedded_manifest("db", access_mode="tertiary"), "access_mode"),
            (build_embedded_manifest("db", access_mode="secondary"), "secondary_path"),
            (
                build_embedded_manifest(
                    "db", access_mode="secondary", secondary_path="s", read_only=False
                ),
                "read-only",
            ),
            (build_remote_manifest(base_url=""), "base_url"),
            (build_remote_manifest(base_url="ftp://rocks.example.com"), "http"),
            (build_remote_manifest(auth_scheme="mtls"), "auth_scheme"),
            (build_remote_manifest(auth_scheme="bearer"), "auth.key"),
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

        # A valid remote manifest must construct cleanly.
        remote_plugin = RocksDbPlugin(build_remote_manifest(auth_key="token", auth_scheme="bearer"))
        assert remote_plugin.connection_mode == "remote"
        assert remote_plugin.base_url == "https://rocksdb.example.com/api"
        assert remote_plugin.read_only is True

        if original_roots is None:
            os.environ.pop("ROCKSDB_ALLOWED_ROOTS", None)
        else:
            os.environ["ROCKSDB_ALLOWED_ROOTS"] = original_roots

        print("✅ RocksDB manifest validation rejects invalid configurations.")
        return True
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


def test_path_allowlist_enforcement():
    """Test that embedded paths must resolve inside ROCKSDB_ALLOWED_ROOTS."""
    print("🔍 Testing RocksDB embedded path allowlist...")

    workdir = tempfile.mkdtemp(prefix="rocksdb-allowlist-")
    original_roots = os.environ.get("ROCKSDB_ALLOWED_ROOTS")
    try:
        rocksdb_module = get_rocksdb_module()
        resolve_allowed_rocksdb_path = rocksdb_module.resolve_allowed_rocksdb_path
        allowed_root = os.path.join(workdir, "allowed")
        os.makedirs(os.path.join(allowed_root, "nested"), exist_ok=True)

        os.environ.pop("ROCKSDB_ALLOWED_ROOTS", None)
        try:
            resolve_allowed_rocksdb_path(os.path.join(allowed_root, "nested"))
            raise AssertionError("Embedded paths must be rejected when the allowlist is unset")
        except ValueError as unset_error:
            assert "ROCKSDB_ALLOWED_ROOTS" in str(unset_error)

        os.environ["ROCKSDB_ALLOWED_ROOTS"] = allowed_root

        resolved = resolve_allowed_rocksdb_path(os.path.join(allowed_root, "nested"))
        assert resolved == os.path.realpath(os.path.join(allowed_root, "nested"))

        # The root itself is allowed.
        assert resolve_allowed_rocksdb_path(allowed_root) == os.path.realpath(allowed_root)

        traversal_candidates = [
            os.path.join(allowed_root, "..", "escape"),
            os.path.join(allowed_root, "nested", "..", "..", "escape"),
            os.path.join(workdir, "other"),
            "",
        ]
        for traversal_path in traversal_candidates:
            try:
                resolve_allowed_rocksdb_path(traversal_path)
                raise AssertionError(f"Path should have been rejected: {traversal_path!r}")
            except ValueError:
                pass

        # A sibling directory that merely shares a name prefix must not be treated as inside.
        sibling_prefix = allowed_root + "-other"
        os.makedirs(sibling_prefix, exist_ok=True)
        try:
            resolve_allowed_rocksdb_path(sibling_prefix)
            raise AssertionError("A path sharing a name prefix must not pass the allowlist")
        except ValueError:
            pass

        # Multiple roots are supported.
        second_root = os.path.join(workdir, "second")
        os.makedirs(second_root, exist_ok=True)
        os.environ["ROCKSDB_ALLOWED_ROOTS"] = os.pathsep.join([allowed_root, second_root])
        assert resolve_allowed_rocksdb_path(second_root) == os.path.realpath(second_root)

        print("✅ RocksDB path allowlist blocks traversal and unlisted directories.")
        return True
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        if original_roots is None:
            os.environ.pop("ROCKSDB_ALLOWED_ROOTS", None)
        else:
            os.environ["ROCKSDB_ALLOWED_ROOTS"] = original_roots
        shutil.rmtree(workdir, ignore_errors=True)


def test_read_only_blocks_writes():
    """Test that write operations are refused while the action is read-only."""
    print("🔍 Testing RocksDB read-only write guard...")

    original_roots = os.environ.get("ROCKSDB_ALLOWED_ROOTS")
    try:
        RocksDbPlugin = get_rocksdb_plugin_class()
        os.environ["ROCKSDB_ALLOWED_ROOTS"] = tempfile.gettempdir()

        plugin = RocksDbPlugin(build_remote_manifest(read_only=True))
        blocking_session = FakeSession()
        plugin.set_http_session(blocking_session)

        blocked_results = [
            plugin.put_value("user:001", "alice"),
            plugin.delete_value("user:001"),
            plugin.write_batch([{"op": "put", "key": "user:001", "value": "alice"}]),
        ]

        for blocked_result in blocked_results:
            assert blocked_result.data.get("read_only") is True, "Write guard must report read_only"
            assert "read-only" in blocked_result.data.get("error", ""), "Write guard must explain the refusal"

        assert blocking_session.calls == [], "Read-only writes must never reach the RocksDB service"

        if original_roots is None:
            os.environ.pop("ROCKSDB_ALLOWED_ROOTS", None)
        else:
            os.environ["ROCKSDB_ALLOWED_ROOTS"] = original_roots

        print("✅ RocksDB read-only actions refuse put, delete, and batch operations.")
        return True
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


def test_remote_request_shaping():
    """Test remote RocksDB service request paths, payloads, and auth headers."""
    print("🔍 Testing RocksDB remote request shaping...")

    original_roots = os.environ.get("ROCKSDB_ALLOWED_ROOTS")
    try:
        RocksDbPlugin = get_rocksdb_plugin_class()
        os.environ["ROCKSDB_ALLOWED_ROOTS"] = tempfile.gettempdir()

        plugin = RocksDbPlugin(build_remote_manifest(auth_key="secret-token", auth_scheme="bearer"))
        session = FakeSession(FakeResponse(payload={"found": True, "value": "alice"}))
        plugin.set_http_session(session)

        result = plugin.get_value("user:001")
        assert result.data["found"] is True
        assert result.data["value"] == "alice"

        call = session.calls[-1]
        assert call["method"] == "POST"
        assert call["url"] == "https://rocksdb.example.com/api/get"
        assert call["payload"] == {"key": "user:001", "column_family": "default"}
        assert call["headers"]["Authorization"] == "Bearer secret-token"
        assert call["timeout"] == 10
        assert call["verify"] is True

        # API key header auth uses the configured header name.
        api_key_plugin = RocksDbPlugin(
            build_remote_manifest(
                auth_key="header-token", auth_scheme="api_key", api_key_header="X-Rocks-Key"
            )
        )
        api_key_session = FakeSession(FakeResponse(payload={"exists": True}))
        api_key_plugin.set_http_session(api_key_session)
        exists_result = api_key_plugin.key_exists("user:001")
        assert exists_result.data["exists"] is True
        assert api_key_session.calls[-1]["headers"]["X-Rocks-Key"] == "header-token"
        assert "Authorization" not in api_key_session.calls[-1]["headers"]

        # Scans post the range arguments and honour the configured result cap.
        scan_session = FakeSession(
            FakeResponse(payload={"items": [{"key": f"user:{index}", "value": "v"} for index in range(20)]})
        )
        plugin.set_http_session(scan_session)
        scan_result = plugin.scan_prefix("user:")
        assert scan_result.data["item_count"] == 10, "max_results must cap remote scan output"
        assert scan_result.data["is_truncated"] is True
        assert scan_session.calls[-1]["url"] == "https://rocksdb.example.com/api/scan"
        assert scan_session.calls[-1]["payload"]["prefix"] == "user:"
        assert scan_session.calls[-1]["payload"]["limit"] == 10

        # Column families and stats use GET endpoints.
        cf_session = FakeSession(FakeResponse(payload={"column_families": ["default", "events"]}))
        plugin.set_http_session(cf_session)
        cf_result = plugin.list_column_families()
        assert cf_result.data["column_families"] == ["default", "events"]
        assert cf_session.calls[-1]["method"] == "GET"
        assert cf_session.calls[-1]["url"] == "https://rocksdb.example.com/api/column_families"

        # HTTP failures surface as structured errors without leaking the body.
        error_session = FakeSession(FakeResponse(status_code=503, payload={"secret": "leak"}))
        plugin.set_http_session(error_session)
        error_result = plugin.get_value("user:001")
        assert "503" in error_result.data["error"]
        assert "leak" not in error_result.data["error"]

        # Non-JSON responses are reported clearly.
        invalid_session = FakeSession(FakeResponse(invalid_json=True))
        plugin.set_http_session(invalid_session)
        invalid_result = plugin.get_value("user:001")
        assert "non-JSON" in invalid_result.data["error"]

        # Writes are allowed once read_only is disabled.
        writable_plugin = RocksDbPlugin(
            build_remote_manifest(auth_key="secret-token", auth_scheme="bearer", read_only=False)
        )
        writable_session = FakeSession(FakeResponse(payload={"success": True}))
        writable_plugin.set_http_session(writable_session)
        put_result = writable_plugin.put_value("user:009", "ivan")
        assert put_result.data["written"] is True
        assert writable_session.calls[-1]["url"] == "https://rocksdb.example.com/api/put"
        assert writable_session.calls[-1]["payload"]["value"] == "ivan"

        if original_roots is None:
            os.environ.pop("ROCKSDB_ALLOWED_ROOTS", None)
        else:
            os.environ["ROCKSDB_ALLOWED_ROOTS"] = original_roots

        print("✅ RocksDB remote calls use the expected paths, payloads, and auth headers.")
        return True
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


def test_embedded_reads_and_encodings():
    """Test embedded reads, scans, encodings, truncation, and write mode."""
    print("🔍 Testing RocksDB embedded reads and encodings...")

    if not rocksdict_is_available():
        print("⏭️  Skipping embedded test: the 'rocksdict' package is not installed.")
        return True

    workdir = tempfile.mkdtemp(prefix="rocksdb-embedded-")
    original_roots = os.environ.get("ROCKSDB_ALLOWED_ROOTS")
    try:
        RocksDbPlugin = get_rocksdb_plugin_class()
        db_path = os.path.join(workdir, "testdb")
        seed_rocksdb(db_path)
        os.environ["ROCKSDB_ALLOWED_ROOTS"] = workdir

        plugin = RocksDbPlugin(build_embedded_manifest(db_path))

        single = plugin.get_value("user:002")
        assert single.data["found"] is True
        assert single.data["value"] == "bob"
        assert single.data["value_truncated"] is False

        missing = plugin.get_value("user:999")
        assert missing.data["found"] is False
        assert missing.data["value"] is None

        multi = plugin.get_values(["user:001", "user:999"])
        assert multi.data["requested_key_count"] == 2
        assert multi.data["found_count"] == 1
        assert multi.data["results"][0]["value"] == "alice"

        multi_from_json = plugin.get_values('["user:001", "user:003"]')
        assert multi_from_json.data["found_count"] == 2

        assert plugin.key_exists("user:003").data["exists"] is True
        assert plugin.key_exists("user:404").data["exists"] is False

        prefix_scan = plugin.scan_prefix("user:")
        assert prefix_scan.data["item_count"] == 3
        assert prefix_scan.data["is_truncated"] is False
        assert [item["key"] for item in prefix_scan.data["items"]] == ["user:001", "user:002", "user:003"]

        limited_scan = plugin.scan_prefix("user:", limit=2)
        assert limited_scan.data["item_count"] == 2
        assert limited_scan.data["is_truncated"] is True

        # The prefix scan must not bleed into neighbouring key spaces.
        event_scan = plugin.scan_prefix("event:")
        assert [item["key"] for item in event_scan.data["items"]] == ["event:001"]

        range_scan = plugin.scan_range(start_key="user:001", end_key="user:003")
        assert [item["key"] for item in range_scan.data["items"]] == ["user:001", "user:002"], (
            "end_key must be exclusive"
        )

        reverse_scan = plugin.scan_range(start_key="user:", reverse=True, limit=2)
        assert [item["key"] for item in reverse_scan.data["items"]] == ["user:003", "user:002"]

        assert "default" in plugin.list_column_families().data["column_families"]
        assert "rocksdb.estimate-num-keys" in plugin.get_database_stats().data["stats"]

        # JSON value decoding.
        json_plugin = RocksDbPlugin(build_embedded_manifest(db_path, value_encoding="json"))
        assert json_plugin.get_value("event:001").data["value"] == {"kind": "login"}

        # Base64 value encoding.
        base64_plugin = RocksDbPlugin(build_embedded_manifest(db_path, value_encoding="base64"))
        assert base64_plugin.get_value("user:001").data["value"] == "YWxpY2U="

        # Base64 key encoding round-trips through both directions.
        base64_key_plugin = RocksDbPlugin(build_embedded_manifest(db_path, key_encoding="base64"))
        base64_key_result = base64_key_plugin.get_value("dXNlcjowMDE=")
        assert base64_key_result.data["found"] is True
        assert base64_key_result.data["value"] == "alice"
        base64_prefix_scan = base64_key_plugin.scan_prefix("dXNlcjo=")
        assert base64_prefix_scan.data["items"][0]["key"] == "dXNlcjowMDE="

        # Oversized values are truncated and flagged.
        truncating_plugin = RocksDbPlugin(build_embedded_manifest(db_path, max_value_bytes=2))
        truncated = truncating_plugin.get_value("user:001")
        assert truncated.data["value"] == "al"
        assert truncated.data["value_truncated"] is True
        assert truncated.data["value_bytes"] == 5

        # Instruction context surfaces the configured prefix hints.
        instruction_context = plugin.build_instruction_context()
        assert "user:" in instruction_context
        assert "read-only" in instruction_context

        close_cached_embedded_handles()

        # Write mode round trip.
        writable_plugin = RocksDbPlugin(build_embedded_manifest(db_path, read_only=False))
        assert writable_plugin.put_value("user:004", "dave").data["written"] is True
        assert writable_plugin.get_value("user:004").data["value"] == "dave"

        batch_result = writable_plugin.write_batch(
            '[{"op": "put", "key": "user:005", "value": "erin"}, {"op": "delete", "key": "user:004"}]'
        )
        assert batch_result.data["applied"] is True
        assert batch_result.data["operation_count"] == 2
        assert writable_plugin.get_value("user:005").data["value"] == "erin"
        assert writable_plugin.get_value("user:004").data["found"] is False

        assert writable_plugin.delete_value("user:005").data["deleted"] is True
        assert writable_plugin.get_value("user:005").data["found"] is False

        # Malformed batch operations are rejected.
        bad_batch = writable_plugin.write_batch('[{"op": "drop", "key": "user:001"}]')
        assert "put" in bad_batch.data["error"] and "delete" in bad_batch.data["error"]

        print("✅ RocksDB embedded reads, encodings, and write mode behave correctly.")
        return True
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        close_cached_embedded_handles()
        if original_roots is None:
            os.environ.pop("ROCKSDB_ALLOWED_ROOTS", None)
        else:
            os.environ["ROCKSDB_ALLOWED_ROOTS"] = original_roots
        shutil.rmtree(workdir, ignore_errors=True)


def test_connection_error_sanitization():
    """Test that embedded connection-test failures never leak filesystem details."""
    print("🔍 Testing RocksDB connection error sanitization...")

    try:
        try:
            routes = import_app_module_without_live_cosmos("route_backend_plugins")
        except Exception as import_error:
            print(f"⏭️  Skipping sanitization test: route module unavailable ({import_error}).")
            return True

        sanitize = routes._sanitize_rocksdb_error

        cases = [
            (Exception("IO error: lock hold by current process on /srv/secret/db/LOCK"), "read_only", "locked by another process"),
            (Exception("Resource temporarily unavailable: /srv/secret/db"), "read_only", "locked by another process"),
            (Exception("No such file or directory: /etc/shadow"), "read_only", "No RocksDB database was found"),
            (Exception("Corruption: bad block in /srv/secret/db/000123.sst"), "read_only", "corrupted"),
            (Exception("Permission denied: /srv/secret/db"), "secondary", "does not have permission"),
            (Exception("weird internal detail /srv/secret/path"), "secondary", "secondary mode"),
            (Exception("weird internal detail /srv/secret/path"), "read_only", "read-only mode"),
        ]

        for raw_error, access_mode, expected_fragment in cases:
            message = sanitize(raw_error, access_mode)
            assert expected_fragment in message, f"Expected '{expected_fragment}' in: {message}"
            for secret in ("/srv/secret", "/etc/shadow", ".sst", "LOCK"):
                assert secret not in message, f"Sanitized message leaked '{secret}': {message}"

        # A corrupted-block error must not be mistaken for a lock error just because
        # the word "block" contains "lock".
        corruption_message = sanitize(Exception("Corruption: bad block"), "read_only")
        assert "locked by another process" not in corruption_message, corruption_message

        print("✅ RocksDB connection errors are sanitized before reaching the browser.")
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

        valid_manifest = build_remote_manifest(auth_key="token", auth_scheme="bearer")
        is_valid, errors = PluginHealthChecker.validate_plugin_manifest(valid_manifest, "rocksdb")
        assert is_valid, f"Valid RocksDB manifest was rejected: {errors}"

        invalid_cases = [
            (build_embedded_manifest(""), "db_path"),
            (build_embedded_manifest("db", access_mode="secondary"), "secondary_path"),
            (build_remote_manifest(base_url=""), "base_url"),
            (build_remote_manifest(base_url="ftp://rocks.example.com"), "base_url"),
            (build_remote_manifest(auth_scheme="bearer"), "auth.key"),
            (build_remote_manifest(max_results=99999), "max_results"),
            (build_remote_manifest(value_encoding="yaml"), "value_encoding"),
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

    original_roots = os.environ.get("ROCKSDB_ALLOWED_ROOTS")
    try:
        assert_app_version_at_least("0.250.209")

        loader_module = import_app_module_without_live_cosmos(
            "semantic_kernel_plugins.plugin_loader"
        )
        discovered_plugins = loader_module.discover_plugins()
        assert "RocksDbPlugin" in discovered_plugins, (
            f"RocksDbPlugin must be discoverable, found: {sorted(discovered_plugins)}"
        )

        RocksDbPlugin = get_rocksdb_plugin_class()
        os.environ["ROCKSDB_ALLOWED_ROOTS"] = tempfile.gettempdir()
        plugin = RocksDbPlugin(build_remote_manifest())

        assert plugin.display_name == "RocksDB"
        assert plugin.metadata["type"] == "rocksdb"
        assert "read-only" in plugin.metadata["description"]

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

        writable_plugin = RocksDbPlugin(build_remote_manifest(read_only=False))
        assert "Write operations are enabled" in writable_plugin.metadata["description"]

        print("✅ RocksDB plugin is discoverable and exposes complete metadata.")
        return True
    except Exception as exc:
        print(f"❌ Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        if original_roots is None:
            os.environ.pop("ROCKSDB_ALLOWED_ROOTS", None)
        else:
            os.environ["ROCKSDB_ALLOWED_ROOTS"] = original_roots


if __name__ == "__main__":
    tests = [
        test_manifest_validation_rules,
        test_path_allowlist_enforcement,
        test_read_only_blocks_writes,
        test_remote_request_shaping,
        test_embedded_reads_and_encodings,
        test_connection_error_sanitization,
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
