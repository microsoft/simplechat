# test_yamcs_action_plugin.py
#!/usr/bin/env python3
"""
Functional test for the Yamcs mission control action plugin.
Version: 0.250.212
Implemented in: 0.250.212

This test ensures the Yamcs action operations helpers, factory, plugin metadata,
manifest health validation, reusable identity contract, read-only archive SQL
guard, and result normalization work without requiring a live Yamcs server.
"""

import sys
import traceback
import types
from pathlib import Path

from test_support.versioning import assert_app_version_at_least


APP_DIR = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP_DIR))

simplechat_operations_stub = types.ModuleType("functions_simplechat_operations")
simplechat_operations_stub.SIMPLECHAT_DEFAULT_ENDPOINT = "simplechat://internal"
sys.modules.setdefault("functions_simplechat_operations", simplechat_operations_stub)


def plugin_function_logger(_plugin_name):
    def decorator(function):
        return function

    return decorator


plugin_invocation_logger_stub = types.ModuleType("semantic_kernel_plugins.plugin_invocation_logger")
plugin_invocation_logger_stub.plugin_function_logger = plugin_function_logger
sys.modules.setdefault("semantic_kernel_plugins.plugin_invocation_logger", plugin_invocation_logger_stub)


class FakeConfigCosmosContainer:
    """Minimal Cosmos container stand-in for importing app config in tests."""

    def __init__(self):
        self.items = {}

    def read_item(self, item, partition_key=None):
        if item in self.items:
            return self.items[item]
        if item == "app_settings":
            return {"id": "app_settings", "settings": {}}
        raise KeyError(item)

    def upsert_item(self, item):
        self.items[item["id"]] = item
        return item

    def query_items(self, *args, **kwargs):
        return []


class FakeConfigCosmosDatabase:
    """Minimal Cosmos database stand-in for importing config.py without live I/O."""

    def __init__(self):
        self.containers = {}

    def create_container_if_not_exists(self, id, **kwargs):
        self.containers.setdefault(id, FakeConfigCosmosContainer())
        return self.containers[id]


class FakeConfigCosmosClient:
    """Minimal Cosmos client stand-in for config.py import-time container setup."""

    def __init__(self, *args, **kwargs):
        self.database = FakeConfigCosmosDatabase()

    def create_database_if_not_exists(self, *args, **kwargs):
        return self.database


import azure.cosmos as azure_cosmos  # noqa: E402

original_cosmos_client = azure_cosmos.CosmosClient
azure_cosmos.CosmosClient = FakeConfigCosmosClient
try:
    from functions_yamcs_operations import (  # noqa: E402
        YAMCS_AUTH_METHOD_API_KEY,
        YAMCS_AUTH_METHOD_BEARER_TOKEN,
        YAMCS_AUTH_METHOD_NONE,
        YAMCS_AUTH_METHOD_USERNAME_PASSWORD,
        YAMCS_DEFAULT_PROCESSOR,
        YAMCS_PLUGIN_TYPE,
        normalize_yamcs_additional_fields,
        normalize_yamcs_server_url,
    )
    from functions_workspace_identities import (  # noqa: E402
        ACTION_IDENTITY_YAMCS_AUTH_TYPES,
        ACTION_IDENTITY_YAMCS_TYPES,
    )
    from semantic_kernel_plugins.plugin_health_checker import PluginHealthChecker  # noqa: E402
    from semantic_kernel_plugins.yamcs_plugin_factory import YamcsPluginFactory  # noqa: E402
finally:
    azure_cosmos.CosmosClient = original_cosmos_client


class FakeYamcsObject:
    """Small Yamcs model stand-in for plugin result normalization tests."""

    def __init__(self, **fields):
        self.__dict__.update(fields)


class FakeSession:
    def request(self, *args, **kwargs):
        return None


class FakeContext:
    def __init__(self):
        self.session = FakeSession()


class FakeMdbClient:
    def __init__(self, instance):
        self.instance = instance

    def list_parameters(self, parameter_type=None, page_size=None):
        parameters = [
            FakeYamcsObject(
                name="BatteryVoltage1",
                qualified_name="/YSS/SIMULATOR/BatteryVoltage1",
                type="float",
                units=["V"],
                data_source="TELEMETERED",
                description="Primary battery voltage",
            ),
            FakeYamcsObject(
                name="PrimaryBusCurrent",
                qualified_name="/YSS/SIMULATOR/PrimaryBusCurrent",
                type="float",
                units=["A"],
                data_source="TELEMETERED",
                description="Primary bus current",
            ),
        ]
        if parameter_type:
            return iter([item for item in parameters if item.type == parameter_type])
        return iter(parameters)

    def get_parameter(self, name):
        return FakeYamcsObject(
            name="BatteryVoltage1",
            qualified_name=name,
            type="float",
            units=["V"],
            data_source="TELEMETERED",
            description="Primary battery voltage",
            long_description="Voltage measured across the primary battery bus.",
            aliases={"MDB:OPS Name": "SIM_BATT_V1"},
            enum_values=[],
        )

    def list_commands(self, page_size=None):
        return iter([
            FakeYamcsObject(
                name="SWITCH_VOLTAGE_ON",
                qualified_name="/YSS/SIMULATOR/SWITCH_VOLTAGE_ON",
                description="Switch battery voltage on",
                abstract=False,
                arguments=[FakeYamcsObject(name="voltage_num", description="Battery number", initial_value="1")],
            ),
        ])


class FakeProcessorClient:
    def __init__(self, instance, processor):
        self.instance = instance
        self.processor = processor

    def get_parameter_values(self, parameters, from_cache=True, timeout=10):
        return [
            FakeYamcsObject(
                name=name,
                generation_time=None,
                reception_time=None,
                eng_value=7.4,
                raw_value=740,
                monitoring_result="IN_LIMITS",
                validity_status="VALID",
            )
            for name in parameters
        ]


class FakeArchiveClient:
    last_sql_statement = None

    def __init__(self, instance):
        self.instance = instance

    def list_parameter_values(self, parameter, **kwargs):
        return iter([
            FakeYamcsObject(
                generation_time=None,
                reception_time=None,
                eng_value=7.4,
                raw_value=740,
                monitoring_result="IN_LIMITS",
                validity_status="VALID",
            ),
        ])

    def list_events(self, **kwargs):
        return iter([
            FakeYamcsObject(
                generation_time=None,
                reception_time=None,
                severity="WARNING",
                message="Battery voltage low",
                event_type="TM",
                source="SIMULATOR",
                sequence_number=1,
            ),
        ])

    def list_packets(self, **kwargs):
        return iter([
            FakeYamcsObject(
                name="/YSS/SIMULATOR/FlightData",
                generation_time=None,
                reception_time=None,
                sequence_number=12,
                link="tm_realtime",
                size=128,
            ),
        ])

    def list_alarms(self, **kwargs):
        return iter([
            FakeYamcsObject(
                name="/YSS/SIMULATOR/BatteryVoltage1",
                severity="CRITICAL",
                trigger_time=None,
                update_time=None,
                is_acknowledged=False,
                acknowledged_by=None,
                violation_count=3,
                count=3,
            ),
        ])

    def execute_sql(self, statement):
        FakeArchiveClient.last_sql_statement = statement
        return iter([{"name": "tm_realtime", "packets": 42}])


class FakeYamcsClient:
    last_instance = None

    def __init__(self, address, credentials=None, tls_verify=True, user_agent=None, **kwargs):
        self.address = address
        self.credentials = credentials
        self.tls_verify = tls_verify
        self.user_agent = user_agent
        self.ctx = FakeContext()
        self.closed = False
        FakeYamcsClient.last_instance = self

    def get_server_info(self):
        return FakeYamcsObject(id="yamcs", version="5.10.0", default_yamcs_instance="simulator")

    def list_instances(self):
        return iter([
            FakeYamcsObject(name="simulator", state="RUNNING", failure_cause=None, mission_time=None),
        ])

    def list_links(self, instance):
        return iter([
            FakeYamcsObject(
                name="tm_realtime",
                class_name="org.yamcs.tctm.TcpTmDataLink",
                enabled=True,
                status="OK",
                in_count=1024,
                out_count=0,
            ),
        ])

    def get_mdb(self, instance):
        return FakeMdbClient(instance)

    def get_processor(self, instance, processor):
        return FakeProcessorClient(instance, processor)

    def get_archive(self, instance):
        return FakeArchiveClient(instance)

    def close(self):
        self.closed = True


class FakeCredentials:
    def __init__(self, username=None, password=None, access_token=None, **kwargs):
        self.username = username
        self.password = password
        self.access_token = access_token


class FakeAPIKeyCredentials:
    """Mirrors yamcs.client.APIKeyCredentials, which stores the key on `password`."""

    def __init__(self, key):
        self.password = key


def install_fake_yamcs_client():
    """Install a fake yamcs.client module so the plugin's lazy import resolves in tests."""
    yamcs_package = sys.modules.get("yamcs") or types.ModuleType("yamcs")
    client_module = types.ModuleType("yamcs.client")
    client_module.YamcsClient = FakeYamcsClient
    client_module.Credentials = FakeCredentials
    client_module.APIKeyCredentials = FakeAPIKeyCredentials
    yamcs_package.client = client_module
    sys.modules["yamcs"] = yamcs_package
    sys.modules["yamcs.client"] = client_module


def build_manifest(**overrides):
    manifest = {
        "name": "yamcs_ground_segment",
        "type": YAMCS_PLUGIN_TYPE,
        "endpoint": "https://yamcs.example.com:8090",
        "auth": {"type": "username_password", "identity": "operator", "key": "secret"},
        "additionalFields": {
            "server_url": "https://yamcs.example.com:8090",
            "instance": "simulator",
            "processor": "realtime",
            "auth_method": YAMCS_AUTH_METHOD_USERNAME_PASSWORD,
            "max_rows": 100,
            "timeout": 30,
        },
        "metadata": {"description": "Yamcs mission control action"},
    }
    manifest.update(overrides)
    return manifest


def test_operations_constants_and_normalization():
    """Yamcs constants and additionalFields normalization apply bounded defaults."""
    print("Testing Yamcs operations helpers...")

    assert YAMCS_PLUGIN_TYPE == "yamcs"
    assert YAMCS_DEFAULT_PROCESSOR == "realtime"

    assert normalize_yamcs_server_url("yamcs.example.com:8090") == "https://yamcs.example.com:8090"
    assert normalize_yamcs_server_url("http://localhost:8090/") == "http://localhost:8090"
    assert normalize_yamcs_server_url("") == ""

    fields = normalize_yamcs_additional_fields({}, auth_type="username_password")
    assert fields["processor"] == YAMCS_DEFAULT_PROCESSOR
    assert fields["auth_method"] == YAMCS_AUTH_METHOD_USERNAME_PASSWORD
    assert fields["read_only"] is True
    assert fields["enable_archive_sql"] is False
    assert fields["tls_verify"] is True
    assert fields["max_rows"] == 500
    assert fields["timeout"] == 30

    clamped = normalize_yamcs_additional_fields(
        {"max_rows": 99999, "timeout": -5, "byte_limit": 10},
        auth_type="key",
    )
    assert clamped["max_rows"] == 5000
    assert clamped["timeout"] == 1
    assert clamped["byte_limit"] == 1000
    assert clamped["auth_method"] == YAMCS_AUTH_METHOD_API_KEY

    no_auth = normalize_yamcs_additional_fields({}, auth_type="NoAuth")
    assert no_auth["auth_method"] == YAMCS_AUTH_METHOD_NONE

    identity_fields = normalize_yamcs_additional_fields(
        {"identity_auth_type": "bearer_token"},
        auth_type="identity",
    )
    assert identity_fields["auth_method"] == YAMCS_AUTH_METHOD_BEARER_TOKEN

    # read_only can never be turned off from a stored manifest.
    forced = normalize_yamcs_additional_fields({"read_only": False}, auth_type="username_password")
    assert forced["read_only"] is True

    print("Yamcs operations helpers passed.")
    return True


def test_factory_normalizes_manifest():
    """The factory normalizes the endpoint, type, and auth method."""
    print("Testing YamcsPluginFactory manifest normalization...")

    normalized = YamcsPluginFactory.normalize_manifest({
        "name": "minimal",
        "auth": {"type": "key"},
        "additionalFields": {"server_url": "yamcs.example.com:8090", "instance": "simulator"},
    })

    assert normalized["type"] == YAMCS_PLUGIN_TYPE
    assert normalized["endpoint"] == "https://yamcs.example.com:8090"
    assert normalized["additionalFields"]["server_url"] == "https://yamcs.example.com:8090"
    assert normalized["additionalFields"]["auth_method"] == YAMCS_AUTH_METHOD_API_KEY
    assert "metadata" in normalized

    no_auth = YamcsPluginFactory.normalize_manifest({
        "auth": {"type": "NoAuth"},
        "additionalFields": {"server_url": "http://localhost:8090", "instance": "simulator"},
    })
    assert no_auth["additionalFields"]["auth_method"] == YAMCS_AUTH_METHOD_NONE

    print("YamcsPluginFactory manifest normalization passed.")
    return True


def test_plugin_metadata_and_functions():
    """Plugin metadata advertises read-only functions and never advertises commanding."""
    print("Testing Yamcs plugin metadata...")

    plugin = YamcsPluginFactory.create_from_config(build_manifest())

    assert plugin.display_name == "Yamcs"
    metadata = plugin.metadata
    assert metadata["type"] == YAMCS_PLUGIN_TYPE
    assert "read-only" in metadata["description"].lower()

    functions = plugin.get_functions()
    expected_functions = {
        "list_instances",
        "list_links",
        "list_parameters",
        "describe_parameter",
        "list_commands",
        "get_parameter_values",
        "list_parameter_history",
        "list_events",
        "list_packets",
        "list_alarms",
        "execute_archive_sql",
    }
    assert set(functions) == expected_functions

    metadata_method_names = {method["name"] for method in metadata["methods"]}
    assert metadata_method_names == expected_functions

    # Commanding and parameter writes must never be exposed.
    forbidden_functions = {"issue_command", "set_parameter_value", "run_script", "enable_link", "disable_link"}
    assert not forbidden_functions & set(functions)
    assert not any(hasattr(plugin, name) for name in forbidden_functions)

    print("Yamcs plugin metadata passed.")
    return True


def test_auth_mapping_matrix():
    """Each auth method builds the expected Yamcs credentials object."""
    print("Testing Yamcs auth mapping...")

    install_fake_yamcs_client()

    password_plugin = YamcsPluginFactory.create_from_config(build_manifest())
    password_credentials = password_plugin._build_credentials()
    assert isinstance(password_credentials, FakeCredentials)
    assert password_credentials.username == "operator"
    assert password_credentials.password == "secret"

    api_key_plugin = YamcsPluginFactory.create_from_config(build_manifest(
        auth={"type": "key", "key": "api-key-value"},
        additionalFields={
            "server_url": "https://yamcs.example.com:8090",
            "instance": "simulator",
            "auth_method": YAMCS_AUTH_METHOD_API_KEY,
        },
    ))
    api_key_credentials = api_key_plugin._build_credentials()
    assert isinstance(api_key_credentials, FakeAPIKeyCredentials)
    assert api_key_credentials.password == "api-key-value"

    bearer_plugin = YamcsPluginFactory.create_from_config(build_manifest(
        auth={"type": "key", "key": "token-value"},
        additionalFields={
            "server_url": "https://yamcs.example.com:8090",
            "instance": "simulator",
            "auth_method": YAMCS_AUTH_METHOD_BEARER_TOKEN,
        },
    ))
    bearer_credentials = bearer_plugin._build_credentials()
    assert isinstance(bearer_credentials, FakeCredentials)
    assert bearer_credentials.access_token == "token-value"

    no_auth_plugin = YamcsPluginFactory.create_from_config(build_manifest(
        auth={"type": "NoAuth"},
        additionalFields={
            "server_url": "http://localhost:8090",
            "instance": "simulator",
        },
    ))
    assert no_auth_plugin._build_credentials() is None

    print("Yamcs auth mapping passed.")
    return True


def test_plugin_configuration_validation():
    """Invalid manifests are rejected when the plugin is constructed."""
    print("Testing Yamcs plugin configuration validation...")

    invalid_cases = [
        ("missing server url", {"endpoint": "", "additionalFields": {"instance": "simulator"}}),
        ("missing instance", {"additionalFields": {"server_url": "https://yamcs.example.com:8090"}}),
        ("missing password", {"auth": {"type": "username_password", "identity": "operator"}}),
        ("missing username", {"auth": {"type": "username_password", "key": "secret"}}),
        ("unsupported auth type", {"auth": {"type": "connection_string", "key": "secret"}}),
    ]

    for label, overrides in invalid_cases:
        try:
            YamcsPluginFactory.create_from_config(build_manifest(**overrides))
        except ValueError:
            continue
        raise AssertionError(f"Expected ValueError for invalid Yamcs manifest: {label}")

    # A reusable identity manifest is valid even without inline credentials.
    identity_plugin = YamcsPluginFactory.create_from_config(build_manifest(
        auth={"type": "identity", "identity": "identity-123"},
        identity_id="identity-123",
    ))
    assert identity_plugin.auth_type == "identity"

    print("Yamcs plugin configuration validation passed.")
    return True


def test_health_checker_validation():
    """PluginHealthChecker accepts valid Yamcs manifests and reports specific errors."""
    print("Testing Yamcs manifest health validation...")

    is_valid, errors = PluginHealthChecker.validate_plugin_manifest(build_manifest(), YAMCS_PLUGIN_TYPE)
    assert is_valid is True, f"Valid Yamcs manifest failed validation: {errors}"
    assert not errors

    _, missing_instance_errors = PluginHealthChecker.validate_plugin_manifest(
        build_manifest(additionalFields={"server_url": "https://yamcs.example.com:8090"}),
        YAMCS_PLUGIN_TYPE,
    )
    assert any("instance" in error for error in missing_instance_errors)

    _, missing_url_errors = PluginHealthChecker.validate_plugin_manifest(
        build_manifest(endpoint="", additionalFields={"instance": "simulator"}),
        YAMCS_PLUGIN_TYPE,
    )
    assert any("server URL" in error for error in missing_url_errors)

    _, bad_auth_type_errors = PluginHealthChecker.validate_plugin_manifest(
        build_manifest(auth={"type": "connection_string", "key": "secret"}),
        YAMCS_PLUGIN_TYPE,
    )
    assert any("auth.type" in error for error in bad_auth_type_errors)

    _, bad_auth_method_errors = PluginHealthChecker.validate_plugin_manifest(
        build_manifest(additionalFields={
            "server_url": "https://yamcs.example.com:8090",
            "instance": "simulator",
            "auth_method": "kerberos",
        }),
        YAMCS_PLUGIN_TYPE,
    )
    assert any("auth_method" in error for error in bad_auth_method_errors)

    _, out_of_range_errors = PluginHealthChecker.validate_plugin_manifest(
        build_manifest(additionalFields={
            "server_url": "https://yamcs.example.com:8090",
            "instance": "simulator",
            "auth_method": YAMCS_AUTH_METHOD_USERNAME_PASSWORD,
            "max_rows": 99999,
        }),
        YAMCS_PLUGIN_TYPE,
    )
    assert any("max_rows" in error for error in out_of_range_errors)

    print("Yamcs manifest health validation passed.")
    return True


def test_reusable_identity_contract():
    """Yamcs actions accept only the credential-bearing reusable identity auth types."""
    print("Testing Yamcs reusable identity contract...")

    assert ACTION_IDENTITY_YAMCS_TYPES == {"yamcs"}
    assert ACTION_IDENTITY_YAMCS_AUTH_TYPES == {"api_key", "bearer_token", "username_password"}

    print("Yamcs reusable identity contract passed.")
    return True


def test_read_only_retrievals():
    """Read-only retrieval functions normalize Yamcs results into bounded row sets."""
    print("Testing Yamcs read-only retrievals...")

    install_fake_yamcs_client()
    plugin = YamcsPluginFactory.create_from_config(build_manifest())

    instances = plugin.list_instances()
    assert instances["success"] is True
    assert instances["rows"][0]["name"] == "simulator"

    links = plugin.list_links()
    assert links["success"] is True
    assert links["rows"][0]["name"] == "tm_realtime"
    assert links["instance"] == "simulator"

    parameters = plugin.list_parameters()
    assert parameters["success"] is True
    assert parameters["row_count"] == 2

    filtered = plugin.list_parameters(search="battery")
    assert filtered["success"] is True
    assert filtered["row_count"] == 1
    assert filtered["rows"][0]["name"] == "BatteryVoltage1"

    described = plugin.describe_parameter("/YSS/SIMULATOR/BatteryVoltage1")
    assert described["success"] is True
    assert described["parameter"]["type"] == "float"

    commands = plugin.list_commands()
    assert commands["success"] is True
    assert commands["rows"][0]["arguments"][0]["name"] == "voltage_num"

    values = plugin.get_parameter_values("/YSS/SIMULATOR/BatteryVoltage1,/YSS/SIMULATOR/PrimaryBusCurrent")
    assert values["success"] is True
    assert values["row_count"] == 2
    assert values["processor"] == "realtime"
    assert all(row["available"] is True for row in values["rows"])

    history = plugin.list_parameter_history("/YSS/SIMULATOR/BatteryVoltage1")
    assert history["success"] is True
    assert history["parameter"] == "/YSS/SIMULATOR/BatteryVoltage1"

    events = plugin.list_events(severity="warning")
    assert events["success"] is True
    assert events["rows"][0]["severity"] == "WARNING"

    packets = plugin.list_packets()
    assert packets["success"] is True
    assert packets["rows"][0]["size"] == 128

    alarms = plugin.list_alarms()
    assert alarms["success"] is True
    assert alarms["rows"][0]["severity"] == "CRITICAL"

    # The client must be closed after every operation.
    assert FakeYamcsClient.last_instance.closed is True

    print("Yamcs read-only retrievals passed.")
    return True


def test_invalid_arguments_are_reported():
    """Bad arguments produce validation errors instead of raising."""
    print("Testing Yamcs argument validation...")

    install_fake_yamcs_client()
    plugin = YamcsPluginFactory.create_from_config(build_manifest())

    missing_parameter = plugin.describe_parameter("")
    assert missing_parameter["success"] is False
    assert missing_parameter["error_type"] == "validation"

    missing_parameters = plugin.get_parameter_values("  ")
    assert missing_parameters["success"] is False
    assert missing_parameters["error_type"] == "validation"

    bad_time = plugin.list_events(start="not-a-timestamp")
    assert bad_time["success"] is False
    assert bad_time["error_type"] == "validation"
    assert "ISO-8601" in bad_time["error"]

    print("Yamcs argument validation passed.")
    return True


def test_archive_sql_is_disabled_by_default():
    """Archive SQL is refused unless explicitly enabled on the action."""
    print("Testing Yamcs archive SQL default gate...")

    install_fake_yamcs_client()
    plugin = YamcsPluginFactory.create_from_config(build_manifest())
    assert plugin.enable_archive_sql is False

    result = plugin.execute_archive_sql("select * from tm")
    assert result["success"] is False
    assert result["error_type"] == "disabled"

    print("Yamcs archive SQL default gate passed.")
    return True


def test_archive_sql_read_only_guard():
    """Enabled archive SQL still rejects writes and bounds SELECT statements."""
    print("Testing Yamcs archive SQL read-only guard...")

    install_fake_yamcs_client()
    plugin = YamcsPluginFactory.create_from_config(build_manifest(additionalFields={
        "server_url": "https://yamcs.example.com:8090",
        "instance": "simulator",
        "auth_method": YAMCS_AUTH_METHOD_USERNAME_PASSWORD,
        "enable_archive_sql": True,
        "max_rows": 25,
    }))
    assert plugin.enable_archive_sql is True

    blocked_statements = [
        "",
        "delete from tm_realtime",
        "drop table tm_realtime",
        "insert into tm_realtime values (1)",
        "create table foo(a int)",
        "update tm_realtime set a = 1",
        "select * from tm; drop table tm",
    ]
    for statement in blocked_statements:
        blocked = plugin.execute_archive_sql(statement)
        assert blocked["success"] is False, f"Statement should have been blocked: {statement!r}"
        assert blocked["error_type"] == "validation"

    allowed = plugin.execute_archive_sql("select * from tm_realtime")
    assert allowed["success"] is True
    assert allowed["rows"][0]["name"] == "tm_realtime"
    assert FakeArchiveClient.last_sql_statement == "select * from tm_realtime limit 25"

    # An explicit limit is preserved rather than duplicated.
    plugin.execute_archive_sql("select * from tm_realtime limit 5")
    assert FakeArchiveClient.last_sql_statement == "select * from tm_realtime limit 5"

    print("Yamcs archive SQL read-only guard passed.")
    return True


def test_result_truncation_and_error_redaction():
    """Row limits, byte limits, and secret redaction protect agent output."""
    print("Testing Yamcs truncation and redaction...")

    install_fake_yamcs_client()
    plugin = YamcsPluginFactory.create_from_config(build_manifest(additionalFields={
        "server_url": "https://yamcs.example.com:8090",
        "instance": "simulator",
        "auth_method": YAMCS_AUTH_METHOD_USERNAME_PASSWORD,
        "max_rows": 1,
        "byte_limit": 1000,
    }))

    bounded = plugin.list_parameters()
    assert bounded["row_count"] == 1
    assert bounded["truncated"] is True

    byte_limited = plugin._truncate_rows([{"value": "x" * 400} for _ in range(20)])
    assert byte_limited["truncated_by_bytes"] is True
    assert len(byte_limited["rows"]) < 20

    redacted = plugin._safe_error_message(Exception("login failed password=hunter2"), "fallback")
    assert "hunter2" not in redacted
    assert "[REDACTED]" in redacted

    token_redacted = plugin._safe_error_message(Exception("api key: abc123"), "fallback")
    assert "abc123" not in token_redacted

    print("Yamcs truncation and redaction passed.")
    return True


def test_missing_client_library_is_reported():
    """A missing yamcs-client install produces an actionable dependency error."""
    print("Testing Yamcs missing dependency handling...")

    install_fake_yamcs_client()
    plugin = YamcsPluginFactory.create_from_config(build_manifest())

    saved_package = sys.modules.pop("yamcs", None)
    saved_client = sys.modules.pop("yamcs.client", None)
    sys.modules["yamcs.client"] = None
    try:
        result = plugin.list_instances()
        assert result["success"] is False
        assert result["error_type"] == "dependency"
        assert "yamcs-client" in result["error"]
    finally:
        sys.modules.pop("yamcs.client", None)
        if saved_package is not None:
            sys.modules["yamcs"] = saved_package
        if saved_client is not None:
            sys.modules["yamcs.client"] = saved_client

    print("Yamcs missing dependency handling passed.")
    return True


def test_app_version():
    """The Yamcs action ships in at least its implementation version."""
    print("Testing SimpleChat version floor...")
    assert_app_version_at_least("0.250.212")
    print("SimpleChat version floor passed.")
    return True


def run_all_tests():
    tests = [
        test_operations_constants_and_normalization,
        test_factory_normalizes_manifest,
        test_plugin_metadata_and_functions,
        test_auth_mapping_matrix,
        test_plugin_configuration_validation,
        test_health_checker_validation,
        test_reusable_identity_contract,
        test_read_only_retrievals,
        test_invalid_arguments_are_reported,
        test_archive_sql_is_disabled_by_default,
        test_archive_sql_read_only_guard,
        test_result_truncation_and_error_redaction,
        test_missing_client_library_is_reported,
        test_app_version,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            results.append(bool(test()))
        except Exception as exc:
            print(f"{test.__name__} failed: {exc}")
            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    return all(results)


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
