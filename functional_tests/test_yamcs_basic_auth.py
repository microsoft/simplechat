# test_yamcs_basic_auth.py
#!/usr/bin/env python3
"""
Functional test for Yamcs reverse-proxy HTTP Basic authentication.
Version: 0.261.012
Implemented in: 0.261.012

This test ensures a Yamcs action can authenticate against a reverse proxy (such as the
Apache front end on a ground-segment dev server) that enforces HTTP Basic authentication
before the request reaches Yamcs. It covers additionalFields normalization, Authorization
header construction, the auth-method compatibility rules, credential selection at connect
time, manifest health validation, Key Vault secret classification, and the reusable
identity reference used to supply the proxy credential without editing the action.
"""

import base64
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
        YAMCS_BASIC_AUTH_COMPATIBLE_AUTH_METHODS,
        YAMCS_PLUGIN_TYPE,
        YAMCS_SENSITIVE_ADDITIONAL_FIELDS,
        build_yamcs_basic_auth_header,
        normalize_yamcs_additional_fields,
        yamcs_basic_auth_conflicts_with_auth_method,
    )
    from functions_keyvault import _is_sensitive_plugin_additional_field  # noqa: E402
    from functions_workspace_identities import (  # noqa: E402
        ACTION_PROXY_IDENTITY_AUTH_TYPES,
        ACTION_PROXY_IDENTITY_FIELD,
        ACTION_PROXY_IDENTITY_TYPES,
        get_action_proxy_identity_reference_id,
    )
    from semantic_kernel_plugins.plugin_health_checker import PluginHealthChecker  # noqa: E402
    from semantic_kernel_plugins.yamcs_plugin_factory import YamcsPluginFactory  # noqa: E402
finally:
    azure_cosmos.CosmosClient = original_cosmos_client


class FakeSession:
    """requests.Session stand-in that records the headers the plugin applies."""

    def __init__(self):
        self.headers = {}

    def request(self, *args, **kwargs):
        return None


class FakeContext:
    def __init__(self):
        self.session = FakeSession()


class FakeYamcsClient:
    def __init__(self, address, credentials=None, tls_verify=True, user_agent=None, **kwargs):
        self.address = address
        self.credentials = credentials
        self.tls_verify = tls_verify
        self.user_agent = user_agent
        self.ctx = FakeContext()
        self.closed = False

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


class FakeBasicAuthCredentials:
    """Mirrors yamcs.client.BasicAuthCredentials, which sends an Authorization header."""

    def __init__(self, username, password):
        self.username = username
        self.password = password


def install_fake_yamcs_client(include_basic_auth=True):
    """Install a fake yamcs.client module so the plugin's lazy imports resolve in tests."""
    yamcs_package = sys.modules.get("yamcs") or types.ModuleType("yamcs")
    client_module = types.ModuleType("yamcs.client")
    client_module.YamcsClient = FakeYamcsClient
    client_module.Credentials = FakeCredentials
    client_module.APIKeyCredentials = FakeAPIKeyCredentials
    if include_basic_auth:
        client_module.BasicAuthCredentials = FakeBasicAuthCredentials
    yamcs_package.client = client_module
    sys.modules["yamcs"] = yamcs_package
    sys.modules["yamcs.client"] = client_module


def build_basic_auth_manifest(**additional_field_overrides):
    """Build a Yamcs manifest for an unauthenticated server behind an authenticating proxy."""
    additional_fields = {
        "server_url": "https://dev.example.gov:8090",
        "instance": "simulator",
        "processor": "realtime",
        "auth_method": YAMCS_AUTH_METHOD_NONE,
        "enable_basic_auth": True,
        "basic_auth_username": "jdoe",
        "basic_auth_password": "temp-password",
        "max_rows": 100,
        "timeout": 30,
    }
    additional_fields.update(additional_field_overrides)
    return {
        "name": "yamcs_dev_server",
        "type": YAMCS_PLUGIN_TYPE,
        "endpoint": "https://dev.example.gov:8090",
        "auth": {"type": "NoAuth"},
        "additionalFields": additional_fields,
        "metadata": {"description": "Yamcs dev server behind an Apache proxy"},
    }


def test_basic_auth_normalization_defaults():
    """Basic auth fields normalize with safe defaults and preserve stored values."""
    print("Testing Yamcs basic auth normalization...")

    defaults = normalize_yamcs_additional_fields(
        {"server_url": "yamcs.example.com:8090", "instance": "simulator"},
        auth_type="NoAuth",
    )
    assert defaults["enable_basic_auth"] is False
    assert defaults["basic_auth_username"] == ""
    assert defaults["basic_auth_password"] == ""
    assert defaults[ACTION_PROXY_IDENTITY_FIELD] == ""

    enabled = normalize_yamcs_additional_fields(
        {
            "server_url": "dev.example.gov:8090",
            "instance": "simulator",
            "enable_basic_auth": "true",
            "basic_auth_username": "  jdoe  ",
            "basic_auth_password": "temp-password",
            "basic_auth_identity_id": " identity-123 ",
        },
        auth_type="NoAuth",
    )
    assert enabled["enable_basic_auth"] is True
    assert enabled["basic_auth_username"] == "jdoe"
    assert enabled["basic_auth_password"] == "temp-password"
    assert enabled[ACTION_PROXY_IDENTITY_FIELD] == "identity-123"

    # Turning the toggle off must not discard the stored credential, otherwise the Key
    # Vault secret backing it would be orphaned on the next save.
    disabled = normalize_yamcs_additional_fields(
        {
            "server_url": "dev.example.gov:8090",
            "instance": "simulator",
            "enable_basic_auth": False,
            "basic_auth_username": "jdoe",
            "basic_auth_password": "temp-password",
        },
        auth_type="NoAuth",
    )
    assert disabled["enable_basic_auth"] is False
    assert disabled["basic_auth_username"] == "jdoe"
    assert disabled["basic_auth_password"] == "temp-password"

    print("Yamcs basic auth normalization passed.")
    return True


def test_basic_auth_header_encoding():
    """The Authorization header is a correctly encoded HTTP Basic credential."""
    print("Testing Yamcs basic auth header encoding...")

    header = build_yamcs_basic_auth_header("jdoe", "p@ss:word")
    assert header.startswith("Basic ")
    decoded = base64.b64decode(header.split(" ", 1)[1]).decode("utf-8")
    assert decoded == "jdoe:p@ss:word"

    # Non-ASCII passwords must survive the round trip rather than raising.
    unicode_header = build_yamcs_basic_auth_header("jdoe", "pässwörd")
    unicode_decoded = base64.b64decode(unicode_header.split(" ", 1)[1]).decode("utf-8")
    assert unicode_decoded == "jdoe:pässwörd"

    print("Yamcs basic auth header encoding passed.")
    return True


def test_basic_auth_compatibility_rules():
    """Basic auth is allowed only where it does not fight for the Authorization header."""
    print("Testing Yamcs basic auth compatibility rules...")

    assert YAMCS_BASIC_AUTH_COMPATIBLE_AUTH_METHODS == {
        YAMCS_AUTH_METHOD_NONE,
        YAMCS_AUTH_METHOD_API_KEY,
    }
    assert yamcs_basic_auth_conflicts_with_auth_method(YAMCS_AUTH_METHOD_NONE) is False
    assert yamcs_basic_auth_conflicts_with_auth_method(YAMCS_AUTH_METHOD_API_KEY) is False
    assert yamcs_basic_auth_conflicts_with_auth_method(YAMCS_AUTH_METHOD_USERNAME_PASSWORD) is True
    assert yamcs_basic_auth_conflicts_with_auth_method(YAMCS_AUTH_METHOD_BEARER_TOKEN) is True

    print("Yamcs basic auth compatibility rules passed.")
    return True


def test_plugin_validation_rejects_incomplete_and_conflicting_configurations():
    """The plugin refuses to build when basic auth is enabled but unusable."""
    print("Testing Yamcs basic auth plugin validation...")

    install_fake_yamcs_client()

    plugin = YamcsPluginFactory.create_from_config(build_basic_auth_manifest())
    assert plugin.enable_basic_auth is True
    assert plugin.basic_auth_username == "jdoe"

    for missing_field in ("basic_auth_username", "basic_auth_password"):
        try:
            YamcsPluginFactory.create_from_config(
                build_basic_auth_manifest(**{missing_field: ""})
            )
        except ValueError as exc:
            assert missing_field in str(exc)
        else:
            raise AssertionError(f"Missing {missing_field} should raise a configuration error")

    conflicting_manifest = build_basic_auth_manifest(auth_method=YAMCS_AUTH_METHOD_BEARER_TOKEN)
    conflicting_manifest["auth"] = {"type": "key", "key": "token-value"}
    try:
        YamcsPluginFactory.create_from_config(conflicting_manifest)
    except ValueError as exc:
        assert "Authorization header" in str(exc)
    else:
        raise AssertionError("Bearer token plus basic auth should raise a configuration error")

    print("Yamcs basic auth plugin validation passed.")
    return True


def test_unauthenticated_yamcs_uses_basic_auth_credentials():
    """An unauthenticated Yamcs server behind a proxy uses BasicAuthCredentials."""
    print("Testing Yamcs basic auth credential selection...")

    install_fake_yamcs_client()

    plugin = YamcsPluginFactory.create_from_config(build_basic_auth_manifest())
    credentials = plugin._build_credentials()
    assert isinstance(credentials, FakeBasicAuthCredentials)
    assert credentials.username == "jdoe"
    assert credentials.password == "temp-password"

    client = plugin._connect()
    assert isinstance(client.credentials, FakeBasicAuthCredentials)
    # BasicAuthCredentials already sends Authorization, so the plugin must not double-apply it.
    assert "Authorization" not in client.ctx.session.headers

    # With the toggle off the plugin must stay fully anonymous.
    anonymous_plugin = YamcsPluginFactory.create_from_config(
        build_basic_auth_manifest(enable_basic_auth=False)
    )
    assert anonymous_plugin._build_credentials() is None

    print("Yamcs basic auth credential selection passed.")
    return True


def test_api_key_auth_sets_basic_header_on_session():
    """API key auth keeps x-api-key while the proxy credential rides on Authorization."""
    print("Testing Yamcs basic auth alongside API key auth...")

    install_fake_yamcs_client()

    manifest = build_basic_auth_manifest(auth_method=YAMCS_AUTH_METHOD_API_KEY)
    manifest["auth"] = {"type": "key", "key": "api-key-value"}
    plugin = YamcsPluginFactory.create_from_config(manifest)

    credentials = plugin._build_credentials()
    assert isinstance(credentials, FakeAPIKeyCredentials)
    assert credentials.password == "api-key-value"

    client = plugin._connect()
    expected_header = build_yamcs_basic_auth_header("jdoe", "temp-password")
    assert client.ctx.session.headers["Authorization"] == expected_header

    print("Yamcs basic auth alongside API key auth passed.")
    return True


def test_missing_basic_auth_client_support_is_reported():
    """An older yamcs-client without BasicAuthCredentials produces an actionable error."""
    print("Testing Yamcs basic auth dependency handling...")

    install_fake_yamcs_client(include_basic_auth=False)
    plugin = YamcsPluginFactory.create_from_config(build_basic_auth_manifest())

    try:
        plugin._build_credentials()
    except ImportError as exc:
        assert "yamcs-client" in str(exc)
    else:
        raise AssertionError("A client without BasicAuthCredentials should raise ImportError")

    # Every other auth method must keep working on that same older client.
    install_fake_yamcs_client(include_basic_auth=False)
    api_key_manifest = build_basic_auth_manifest(
        auth_method=YAMCS_AUTH_METHOD_API_KEY,
        enable_basic_auth=False,
    )
    api_key_manifest["auth"] = {"type": "key", "key": "api-key-value"}
    api_key_plugin = YamcsPluginFactory.create_from_config(api_key_manifest)
    assert isinstance(api_key_plugin._build_credentials(), FakeAPIKeyCredentials)

    install_fake_yamcs_client()
    print("Yamcs basic auth dependency handling passed.")
    return True


def test_health_checker_matches_runtime_rules():
    """Manifest validation reports the same basic auth problems the plugin enforces."""
    print("Testing Yamcs basic auth manifest validation...")

    is_valid, errors = PluginHealthChecker.validate_plugin_manifest(
        build_basic_auth_manifest(), YAMCS_PLUGIN_TYPE
    )
    assert is_valid, f"Expected a valid manifest, got: {errors}"

    is_valid, errors = PluginHealthChecker.validate_plugin_manifest(
        build_basic_auth_manifest(basic_auth_password=""), YAMCS_PLUGIN_TYPE
    )
    assert is_valid is False
    assert any("basic_auth_password" in error for error in errors)

    conflicting_manifest = build_basic_auth_manifest(auth_method=YAMCS_AUTH_METHOD_USERNAME_PASSWORD)
    conflicting_manifest["auth"] = {"type": "username_password", "identity": "operator", "key": "secret"}
    is_valid, errors = PluginHealthChecker.validate_plugin_manifest(
        conflicting_manifest, YAMCS_PLUGIN_TYPE
    )
    assert is_valid is False
    assert any("Authorization header" in error for error in errors)

    # A referenced identity supplies both values at runtime, so inline values are optional.
    identity_manifest = build_basic_auth_manifest(
        basic_auth_username="",
        basic_auth_password="",
        basic_auth_identity_id="identity-123",
    )
    is_valid, errors = PluginHealthChecker.validate_plugin_manifest(
        identity_manifest, YAMCS_PLUGIN_TYPE
    )
    assert is_valid, f"Expected an identity-backed manifest to be valid, got: {errors}"

    print("Yamcs basic auth manifest validation passed.")
    return True


def test_basic_auth_password_is_treated_as_a_secret():
    """The proxy password routes through the same Key Vault handling as other secrets."""
    print("Testing Yamcs basic auth secret classification...")

    assert "basic_auth_password" in YAMCS_SENSITIVE_ADDITIONAL_FIELDS
    yamcs_action = {"type": YAMCS_PLUGIN_TYPE}
    assert _is_sensitive_plugin_additional_field(yamcs_action, "basic_auth_password") is True
    # The username and toggle are configuration, not secrets.
    assert _is_sensitive_plugin_additional_field(yamcs_action, "basic_auth_username") is False
    assert _is_sensitive_plugin_additional_field(yamcs_action, "enable_basic_auth") is False

    print("Yamcs basic auth secret classification passed.")
    return True


def test_proxy_identity_reference_contract():
    """The proxy credential has its own username/password identity reference."""
    print("Testing Yamcs proxy identity reference contract...")

    assert ACTION_PROXY_IDENTITY_FIELD == "basic_auth_identity_id"
    assert ACTION_PROXY_IDENTITY_AUTH_TYPES == {"username_password"}
    assert YAMCS_PLUGIN_TYPE in ACTION_PROXY_IDENTITY_TYPES

    referenced_action = build_basic_auth_manifest(basic_auth_identity_id="identity-123")
    assert get_action_proxy_identity_reference_id(referenced_action) == "identity-123"

    assert get_action_proxy_identity_reference_id(build_basic_auth_manifest()) == ""
    assert get_action_proxy_identity_reference_id({}) == ""
    assert get_action_proxy_identity_reference_id(None) == ""

    # The proxy reference must be independent of the primary Yamcs credential reference.
    primary_only = build_basic_auth_manifest()
    primary_only["identity_id"] = "primary-identity"
    assert get_action_proxy_identity_reference_id(primary_only) == ""

    print("Yamcs proxy identity reference contract passed.")
    return True


def test_modal_payload_preserves_stored_credential_when_disabled():
    """Turning the toggle off must not blank the stored proxy credential on save.

    ``keyvault_plugin_save_helper`` skips falsy additionalFields values, so a payload that
    sends an empty ``basic_auth_password`` replaces the stored Key Vault reference with an
    empty string without deleting the secret. That orphans the secret and forces the user to
    retype the password just to re-enable the toggle. Only selecting a reusable identity may
    blank the inline fields.
    """
    print("Testing Yamcs basic auth modal payload preservation...")

    stepper_source = (APP_DIR / "static" / "js" / "plugin_modal_stepper.js").read_text(encoding="utf-8")

    block_start = stepper_source.index("getYamcsConfiguration()")
    block_end = stepper_source.index("const auth = {};", block_start)
    configuration_block = stepper_source[block_start:block_end]

    # The credential fields are declared together and end at the next unrelated field.
    credential_region = configuration_block[
        configuration_block.index("basic_auth_identity_id:"):configuration_block.index("max_rows:")
    ]

    for field_name in ("basic_auth_identity_id", "basic_auth_username", "basic_auth_password"):
        assert f"{field_name}:" in credential_region, f"{field_name} must be sent to the server"

    assert "basicAuthIdentity" in credential_region, (
        "Proxy credential fields should be blanked only when a reusable identity is selected"
    )
    assert "enableBasicAuth" not in credential_region, (
        "Proxy credential fields must not be blanked when enable_basic_auth is false; "
        "doing so drops the Key Vault reference and orphans the stored secret."
    )

    # The toggle itself still has to be sent.
    assert "enable_basic_auth: enableBasicAuth" in configuration_block

    print("Yamcs basic auth modal payload preservation passed.")
    return True


def test_app_version():
    """The application version is at least the release that added basic auth support."""
    print("Testing SimpleChat version floor...")
    assert_app_version_at_least("0.261.012")
    print("SimpleChat version floor passed.")
    return True


if __name__ == "__main__":
    tests = [
        test_basic_auth_normalization_defaults,
        test_basic_auth_header_encoding,
        test_basic_auth_compatibility_rules,
        test_plugin_validation_rejects_incomplete_and_conflicting_configurations,
        test_unauthenticated_yamcs_uses_basic_auth_credentials,
        test_api_key_auth_sets_basic_header_on_session,
        test_missing_basic_auth_client_support_is_reported,
        test_health_checker_matches_runtime_rules,
        test_basic_auth_password_is_treated_as_a_secret,
        test_proxy_identity_reference_contract,
        test_modal_payload_preserves_stored_credential_when_disabled,
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
    sys.exit(0 if all(results) else 1)
