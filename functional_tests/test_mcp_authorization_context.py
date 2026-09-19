# test_mcp_authorization_context.py
#!/usr/bin/env python3
"""
Offline functional tests for trusted outbound MCP execution context.
Version: 0.261.036
Implemented in: 0.261.029

Exercise real normalization, destination/preconfiguration policy, descriptors,
factory operations and loaders with fake native connectors. Network, process,
settings storage and credential providers cannot reach external resources.
All injected modules, environment values and callbacks are scoped to each test.
"""

import ast
import asyncio
import base64
import copy
import importlib
import os
import sys
import types
import unittest
from contextlib import ExitStack, contextmanager
from enum import Enum
from itertools import product
from pathlib import Path
from unittest.mock import patch

from flask import Flask, session


APP_DIR = Path(__file__).resolve().parents[1] / "application" / "single_app"
MCP_ENVIRONMENT = {
    "ENABLE_MCP_DESTINATION_GOVERNANCE": "false",
    "MCP_BLOCK_UNSAFE_DESTINATIONS": "false",
    "MCP_ALLOWED_DESTINATIONS": "",
    "MCP_ALLOWED_PERSONAL_DESTINATIONS": "",
    "MCP_ALLOWED_GROUP_DESTINATIONS": "",
    "MCP_ALLOWED_GLOBAL_DESTINATIONS": "",
    "SIMPLECHAT_MCP_PRECONFIGURATION_PATHS": "",
    "SIMPLECHAT_MCP_PRESET_PATHS": "",
    "ENABLE_LOCAL_MCP_PRECONFIGURATION": "false",
}


def _noop(*_args, **_kwargs):
    return None


def _decorator(*_args, **_kwargs):
    return lambda function: function


class _InertPlugin:
    def __init__(self, manifest=None, **_kwargs):
        self.manifest = manifest

    def get_functions(self):
        return []


class _KernelPlugin:
    @classmethod
    def from_object(cls, name, functions, description=None):
        plugin = cls()
        plugin.name = name
        plugin.functions = functions
        return plugin


class _Kernel:
    def __init__(self):
        self.plugins = {}

    def add_plugin(self, plugin):
        self.plugins[plugin.name] = plugin


class _SecretReturnType(Enum):
    NAME = "name"
    VALUE = "value"
    TRIGGER = "trigger"


class McpAuthorizationContextTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(sys.modules, {}))
        self.stack.enter_context(patch.object(sys, "path", [str(APP_DIR), *sys.path]))
        self.stack.enter_context(patch.dict(os.environ, MCP_ENVIRONMENT))
        for module_name in list(sys.modules):
            if (
                module_name.startswith(("functions_mcp_", "semantic_kernel.", "semantic_kernel_plugins."))
                or module_name in {
                    "functions_action_manifest", "semantic_kernel", "semantic_kernel_plugins",
                    "semantic_kernel_loader", "functions_action_connection_tests",
                    "functions_settings", "config",
                }
            ):
                sys.modules.pop(module_name, None)

        self.events = []
        self.logs = []
        self.debug_messages = []
        self.credentials = []
        self.settings = {}
        self.settings_reads = 0
        self.policies = {}
        self.connect_hook = None
        self.group_grants = {}
        self.sleep_calls = []
        self.app = Flask(__name__)
        self.app.secret_key = "offline-mcp-test"
        # Windows creates its internal event-loop socket pair before outbound I/O is blocked.
        loop = asyncio.new_event_loop()
        self.stack.callback(loop.close)
        self.stack.enter_context(patch("asyncio.run", side_effect=loop.run_until_complete))

        for target in (
            "socket.create_connection", "socket.getaddrinfo", "socket.socket.connect",
            "subprocess.Popen", "subprocess.run", "asyncio.create_subprocess_exec",
            "asyncio.create_subprocess_shell",
        ):
            self.stack.enter_context(patch(target, side_effect=AssertionError("External activity is forbidden")))

        async def fake_sleep(delay):
            self.sleep_calls.append(delay)

        self.stack.enter_context(patch("asyncio.sleep", side_effect=fake_sleep))
        self._stub(
            "functions_appinsights",
            log_event=lambda message, *args, **kwargs: self.logs.append((message, kwargs)),
            get_appinsights_logger=lambda: types.SimpleNamespace(info=_noop, error=_noop, warning=_noop),
        )
        self._stub("functions_debug", debug_print=lambda *args, **kwargs: self.debug_messages.append((args, kwargs)))
        self._stub(
            "semantic_kernel_plugins.plugin_invocation_logger",
            plugin_function_logger=_decorator,
            get_plugin_logger=lambda: types.SimpleNamespace(get_plugin_stats=lambda: {}),
            auto_wrap_plugin_functions=_noop,
        )
        self._stub("semantic_kernel", Kernel=_Kernel, __path__=[])
        self._stub("semantic_kernel.functions", kernel_function=_decorator, __path__=[])
        self._stub("semantic_kernel.functions.kernel_plugin", KernelPlugin=_KernelPlugin)
        self._stub("semantic_kernel.connectors", __path__=[])
        self._stub("semantic_kernel_plugins", __path__=[str(APP_DIR / "semantic_kernel_plugins")])
        self._install_connectors()
        self._stub(
            "functions_governance",
            list_item_policies=lambda entity_type: copy.deepcopy(self.policies.get(entity_type, [])),
            get_user_governance_group_ids=lambda user_id: self.group_grants.get(user_id, set()),
        )

        self.manifests = importlib.import_module("functions_action_manifest")
        self.operations = importlib.import_module("functions_mcp_operations")
        self.destinations = importlib.import_module("functions_mcp_destinations")
        self.preconfigurations = importlib.import_module("functions_mcp_preconfigurations")
        self.plugin_module = importlib.import_module("semantic_kernel_plugins.mcp_plugin")
        self.factory = importlib.import_module("semantic_kernel_plugins.mcp_plugin_factory").McpPluginFactory
        self.assertNotIn("config", sys.modules)
        self.assertNotIn("functions_settings", sys.modules)
        self._stub("functions_settings", get_settings=self._get_settings)
        self._stub(
            "functions_azure_maps",
            AZURE_MAPS_DEFAULT_ENDPOINT="https://maps.example",
            AZURE_MAPS_DEFAULT_LANGUAGE="en-US",
            AZURE_MAPS_DEFAULT_TILESET_ID="test",
            AZURE_MAPS_DEFAULT_VIEW="Auto",
            AZURE_MAPS_TILE_API_VERSION="test",
        )
        self.tester = importlib.import_module("functions_action_connection_tests")

    def _stub(self, name, **attributes):
        module = types.ModuleType(name)
        module.__dict__.update(attributes)
        sys.modules[name] = module
        return module

    def _get_settings(self):
        self.settings_reads += 1
        return copy.deepcopy(self.settings)

    def _install_connectors(self):
        owner = self

        class RemoteSession:
            async def list_tools(self):
                owner.events.append(("list_tools",))
                return types.SimpleNamespace(tools=[
                    types.SimpleNamespace(
                        name="echo",
                        description="Echo supplied text.",
                        inputSchema={"type": "object", "properties": {"text": {"type": "string"}}},
                    )
                ])

        class RemoteConnector:
            transport = ""

            def __init__(self, **kwargs):
                self.kwargs = kwargs
                self.session = RemoteSession()
                owner.events.append(("construct", self.transport, kwargs))

            async def connect(self):
                owner.events.append(("connect", self.transport))
                if owner.connect_hook is not None:
                    owner.connect_hook()

            async def close(self):
                owner.events.append(("close", self.transport))

            async def call_tool(self, name, **arguments):
                owner.events.append(("call_tool", name, arguments))
                return {"echo": arguments}

        self.connector_types = {
            transport: type(class_name, (RemoteConnector,), {"transport": transport})
            for transport, class_name in {
                "streamable_http": "MCPStreamableHttpPlugin",
                "sse": "MCPSsePlugin",
                "websocket": "MCPWebsocketPlugin",
            }.items()
        }
        self._stub(
            "semantic_kernel.connectors.mcp",
            **{connector.__name__: connector for connector in self.connector_types.values()},
        )

    @contextmanager
    def caller(self, user_id="alice", roles=None, workflow=False):
        path = "/api/internal/workflows/run" if workflow else "/api/chat"
        with self.app.test_request_context(path):
            if user_id is not None:
                session["user"] = {"oid": user_id, "roles": roles or ["User"]}
            yield

    def manifest(self, scope="global", scope_id=None, transport="streamable_http", **overrides):
        manifest = {
            "id": "action-1",
            "name": "remote_action",
            "type": "mcp",
            "endpoint": "wss://allowed.example/mcp" if transport == "websocket" else "https://allowed.example/mcp",
            "auth": {"type": "NoAuth"},
            "additionalFields": {"transport": transport, "retry_count": 0},
        }
        manifest.update(overrides)
        if scope is None:
            return manifest
        scope_id = scope_id or {"personal": "alice", "group": "group-1", "global": "global"}[scope]
        return self.manifests.bind_action_origin(manifest, scope, scope_id)

    def _load_loaders(self):
        """Import both real loader modules while replacing unrelated app integrations."""
        real_modules = {
            "functions_action_manifest", "functions_mcp_operations", "functions_mcp_destinations",
            "functions_mcp_preconfigurations", "semantic_kernel_plugins.base_plugin",
            "semantic_kernel_plugins.mcp_plugin", "semantic_kernel_plugins.mcp_plugin_factory",
            "semantic_kernel_plugins.logged_plugin_loader",
            "functions_m365_context", "functions_m365_approvals",
            "functions_m365_execution", "functions_m365_operations",
        }
        standard_modules = {"typing", "datetime", "flask", "azure.core.exceptions"}
        paths = [
            APP_DIR / "semantic_kernel_loader.py",
            APP_DIR / "semantic_kernel_plugins" / "logged_plugin_loader.py",
        ]
        for path in paths:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"))
            import_nodes = [node for node in tree.body if isinstance(node, ast.ImportFrom)]
            for node in tree.body:
                if isinstance(node, ast.Try):
                    import_nodes.extend(child for child in node.body if isinstance(child, ast.ImportFrom))
            for node in import_nodes:
                if node.module in real_modules or node.module in standard_modules:
                    continue
                dependency = sys.modules.get(node.module)
                if dependency is None:
                    dependency = self._stub(node.module)
                for name in node.names:
                    if hasattr(dependency, name.name):
                        continue
                    if name.name.endswith("_PLUGIN_TYPE"):
                        value = name.name[:-len("_PLUGIN_TYPE")].lower()
                    elif name.name.isupper():
                        value = ()
                    elif name.name[:1].isupper():
                        value = type(name.name, (_InertPlugin,), {})
                    else:
                        value = _noop
                    setattr(dependency, name.name, value)

        self._stub("app_settings_cache", get_settings_cache=_noop)
        keyvault = sys.modules["functions_keyvault"]
        keyvault.SecretReturnType = _SecretReturnType
        keyvault.SQL_PLUGIN_SENSITIVE_AUTH_FIELDS = ()
        keyvault.SQL_PLUGIN_SENSITIVE_ADDITIONAL_FIELDS = ()
        keyvault.validate_secret_name_dynamic = lambda value: value.startswith("kv:")

        def resolve_secret(value, **context):
            self.credentials.append(("keyvault", value, context))
            return "resolved-offline-secret"

        def hydrate_identity(manifest, scope_type, scope_id, **_kwargs):
            self.credentials.append(("identity", scope_type, scope_id))
            hydrated = dict(manifest)
            hydrated["auth"] = {"type": "key", "key": "resolved-identity-secret"}
            return hydrated

        keyvault.resolve_secret_reference_for_context = resolve_secret
        identities = sys.modules["functions_workspace_identities"]
        identities.WORKSPACE_IDENTITY_SCOPE_GLOBAL = "global"
        identities.WORKSPACE_IDENTITY_SCOPE_GROUP = "group"
        identities.WORKSPACE_IDENTITY_SCOPE_PERSONAL = "personal"
        identities.get_action_identity_reference_id = lambda manifest: manifest.get("identity_id", "")
        identities.hydrate_action_identity_reference = hydrate_identity
        sys.modules["functions_governance"].filter_actions_by_action_type_access = lambda _user, actions, *_args: actions
        sys.modules["functions_governance"].filter_governed_global_actions_for_user = lambda _user, actions: actions
        plugin_loader = sys.modules["semantic_kernel_plugins.plugin_loader"]
        plugin_loader.discover_plugins = lambda: {
            "McpPlugin": self.plugin_module.McpPlugin,
            "SQLQueryPlugin": sys.modules["semantic_kernel_plugins.sql_query_plugin"].SQLQueryPlugin,
            "SQLSchemaPlugin": sys.modules["semantic_kernel_plugins.sql_schema_plugin"].SQLSchemaPlugin,
        }
        health = sys.modules["semantic_kernel_plugins.plugin_health_checker"]
        health.PluginHealthChecker.create_plugin_safely = staticmethod(
            lambda plugin_class, manifest, _name: (plugin_class(manifest), [])
        )
        health.PluginErrorRecovery.create_fallback_plugin = staticmethod(lambda *_args: None)
        logged = importlib.import_module("semantic_kernel_plugins.logged_plugin_loader")
        loader = importlib.import_module("semantic_kernel_loader")
        return loader, logged

    def test_native_factory_import_needs_no_stdio_or_settings_owner(self):
        connector_module = sys.modules["semantic_kernel.connectors.mcp"]
        self.assertFalse(hasattr(connector_module, "MCPStdioPlugin"))
        descriptor = self.factory.create_from_config(self.manifest(scope=None))
        self.assertEqual(descriptor.metadata["type"], "mcp")
        self.assertEqual(self.settings_reads, 0)
        self.assertEqual(self.events, [])

    def test_missing_origin_or_current_identity_is_denied_before_settings(self):
        forged = self.manifest(
            scope=None, scope_id="global", is_global=True, is_group=True,
            user_id="alice", runtime_user_id="alice", action_origin={"scope_type": "global"},
        )
        with self.caller():
            for origin in (None, {"scope_type": "global", "scope_id": "global"}):
                with self.subTest(origin=origin), self.assertRaises(PermissionError):
                    self.factory.create_connector(forged, origin=origin)
        trusted = self.manifest()
        with self.assertRaises(PermissionError):
            self.factory.create_connector(trusted)
        with self.caller(None), self.assertRaises(PermissionError):
            self.factory.create_connector(trusted)
        self.assertEqual(self.settings_reads, 0)
        self.assertEqual(self.events, [])

    def test_explicit_origin_and_aliases_follow_same_boundary(self):
        aliases = ("mcp", "MCP", " McpPlugin ", "model-context-protocol", "model_context_protocol")
        origin = self.manifests.McpActionOrigin("global", "global", "action-1")
        with self.caller():
            for alias in aliases:
                with self.subTest(alias=alias):
                    raw = self.manifest(scope=None, type=alias)
                    connector = self.factory.create_connector(raw, origin=origin)
                    self.assertIsInstance(connector, self.connector_types["streamable_http"])
            metadata_only = self.manifest(scope=None, type="", metadata={"type": "McpPlugin"})
            connector = self.factory.create_connector(metadata_only, origin=origin)
            self.assertIsInstance(connector, self.connector_types["streamable_http"])
            for invalid in ("mc", "cp", "mcp_unrelated", "python", "sql_query", "sql_schema", [], True):
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    self.factory.create_connector(
                        self.manifest(scope=None, type=invalid, metadata={"type": "mcp"}), origin=origin
                    )

    def test_explicit_origin_reaches_every_public_operation(self):
        raw = self.manifest(scope=None)
        origin = self.manifests.McpActionOrigin("global", "global", "action-1")
        descriptor = self.factory.create_from_config(raw, origin=origin)
        with self.caller():
            probe = asyncio.run(self.factory.probe_server_from_config(raw, origin=origin))
            tools = asyncio.run(self.factory.discover_tools_from_config(raw, origin=origin))
            invocation = asyncio.run(self.factory.call_tool_from_config(raw, "echo", {}, origin=origin))
            connection_test = self.tester.test_mcp_connection(raw, origin=origin)
            cached_invocation = asyncio.run(descriptor.invoke_tool("echo", {}))
        self.assertEqual(probe["tool_count"], 1)
        self.assertEqual(len(tools), 1)
        self.assertTrue(invocation["success"])
        self.assertTrue(connection_test["success"])
        self.assertTrue(cached_invocation["success"])
        constructions = [event for event in self.events if event[0] == "construct"]
        self.assertEqual(len(constructions), 5)

    def test_forged_scope_fields_cannot_change_personal_origin(self):
        self.settings = {
            "enable_mcp_destination_governance": True,
            "mcp_allowed_global_destinations": ["*"],
        }
        manifest = self.manifest("personal")
        manifest.update(
            scope="global", scope_id="global", is_global=True, is_group=True,
            group_id="other-group", user_id="creator", runtime_user_id="privileged",
        )
        with self.caller(), self.assertRaises(PermissionError):
            self.factory.create_connector(manifest)
        self.settings["mcp_allowed_personal_destinations"] = ["allowed.example"]
        with self.caller():
            connector = self.factory.create_connector(manifest)
        self.assertIsInstance(connector, self.connector_types["streamable_http"])
        self.settings["enable_mcp_destination_governance"] = False
        with self.caller("bob"), self.assertRaises(PermissionError):
            self.factory.create_connector(manifest)

    def test_scope_policy_requires_explicit_valid_ids(self):
        raw = self.manifest(scope=None, is_global=True, user_id="alice")
        for scope, scope_id in ((None, ""), ("unknown", "alice"), ("", "alice"), ("personal", ""),
                                ("group", ""), ("global", "action-1")):
            with self.subTest(scope=scope, scope_id=scope_id), self.assertRaises(PermissionError):
                self.destinations.evaluate_mcp_destination_policy(
                    raw, scope_type=scope, scope_id=scope_id, policy_config={"enabled": False}
                )
        trusted = self.manifest()
        with self.assertRaises(PermissionError):
            self.destinations.evaluate_mcp_destination_policy(
                trusted, scope_type="personal", scope_id="alice", policy_config={"enabled": False}
            )
        with self.caller(), self.assertRaises(PermissionError):
            self.factory.create_connector(
                trusted, origin=self.manifests.McpActionOrigin("personal", "alice", "action-1")
            )

    def test_all_remote_transports_keep_auth_headers_and_timeouts(self):
        with self.caller():
            for scope in ("personal", "group", "global"):
                for transport in self.connector_types:
                    with self.subTest(scope=scope, transport=transport):
                        manifest = self.manifest(scope, transport=transport)
                        manifest["additionalFields"].update(
                            request_timeout=29, connect_timeout=8, sse_read_timeout=210,
                            load_tools=False, load_prompts=True,
                        )
                        if transport != "websocket":
                            manifest["auth"] = {"type": "key", "key": "offline-secret", "identity": "test-user"}
                            manifest["additionalFields"].update(
                                auth_method="basic", custom_headers={"X-Correlation": "offline"}
                            )
                        connector = self.factory.create_connector(manifest)
                        self.assertIsInstance(connector, self.connector_types[transport])
                        self.assertEqual(connector.kwargs["request_timeout"], 29)
                        self.assertFalse(connector.kwargs["load_tools"])
                        self.assertTrue(connector.kwargs["load_prompts"])
                        if transport != "websocket":
                            expected = base64.b64encode(b"test-user:offline-secret").decode("ascii")
                            self.assertEqual(connector.kwargs["headers"]["Authorization"], f"Basic {expected}")
                            self.assertEqual(connector.kwargs["headers"]["X-Correlation"], "offline")
                            self.assertEqual(connector.kwargs["timeout"], 8)
                            self.assertEqual(connector.kwargs["sse_read_timeout"], 210)
        normalized = self.operations.normalize_mcp_transport("server-sent-events")
        repeated = self.operations.normalize_mcp_transport(normalized)
        self.assertEqual((normalized, repeated), ("sse", "sse"))

    def test_remote_bearer_api_key_and_workspace_identity_auth_are_preserved(self):
        with self.caller():
            for method, identity_type, header, expected in (
                ("bearer", "", "Authorization", "Bearer offline-secret"),
                ("api_key", "", "X-Offline-Key", "offline-secret"),
                ("identity", "bearer_token", "Authorization", "Bearer offline-secret"),
                ("identity", "api_key", "X-Offline-Key", "offline-secret"),
            ):
                with self.subTest(method=method, identity_type=identity_type):
                    manifest = self.manifest()
                    manifest["auth"] = {"type": "key", "key": "offline-secret"}
                    manifest["additionalFields"].update(
                        auth_method=method, identity_auth_type=identity_type, api_key_header_name="X-Offline-Key"
                    )
                    connector = self.factory.create_connector(manifest)
                    self.assertEqual(connector.kwargs["headers"][header], expected)
            websocket = self.manifest(transport="websocket")
            websocket["additionalFields"]["custom_headers"] = {"X-Offline": "not-supported"}
            before = len(self.events)
            with self.assertRaises(ValueError):
                self.factory.create_connector(websocket)
        self.assertEqual(len(self.events), before)

    def test_group_destination_target_and_current_group_grants_are_enforced(self):
        self.settings["enable_mcp_destination_governance"] = True
        self.policies["mcp_group_destination"] = [{
            "item_id": "group:group-1::allowed.example", "allow_all": False, "allowed_groups": ["grant-group"],
        }]
        self.group_grants["alice"] = {"grant-group"}
        with self.caller():
            allowed = self.factory.create_connector(self.manifest("group"))
            with self.assertRaises(PermissionError):
                self.factory.create_connector(self.manifest("group", scope_id="group-2"))
        with self.caller("bob"), self.assertRaises(PermissionError):
            self.factory.create_connector(self.manifest("group", runtime_user_id="alice"))
        self.assertIsInstance(allowed, self.connector_types["streamable_http"])

    def test_retired_transports_reject_every_entry_point_without_activity(self):
        for roles, enabled, environment_enabled in product((["User"], ["Admin"]), (False, True), (False, True)):
            self.settings["enable_mcp_destination_governance"] = enabled
            os.environ["ENABLE_MCP_DESTINATION_GOVERNANCE"] = str(environment_enabled).lower()
            with self.caller(roles=roles):
                for scope in (None, "personal", "group", "global"):
                    for transport, endpoint in (
                        ("stdio", "https://allowed.example/mcp"),
                        (" \tStDiO ", ""),
                        ("sse", " STDIO://retired-command "),
                    ):
                        with self.subTest(
                            roles=roles, scope=scope, transport=transport,
                            enabled=enabled, environment_enabled=environment_enabled,
                        ):
                            manifest = self.manifest(scope, transport=transport, endpoint=endpoint)
                            manifest["additionalFields"].update(
                                command="never-run", args=["sensitive"], env={"TOKEN": "never-resolve"}, retry_count=3
                            )
                            operations = [
                                lambda: self.plugin_module.McpPlugin(manifest),
                                lambda: self.factory.create_from_config(manifest),
                                lambda: self.factory.create_connector(manifest),
                                lambda: asyncio.run(self.factory.probe_server_from_config(manifest)),
                                lambda: asyncio.run(self.factory.discover_tools_from_config(manifest)),
                                lambda: asyncio.run(self.factory.call_tool_from_config(manifest, "echo", {})),
                            ]
                            for operation in operations:
                                with self.assertRaises(self.manifests.McpStdioRemovedError) as raised:
                                    operation()
                                self.assertEqual(raised.exception.code, "mcp_stdio_removed")
                            result = self.tester.test_mcp_connection(manifest)
                            self.assertEqual(result["status"], 400)
                            self.assertEqual(result["details"]["error_type"], "mcp_stdio_removed")
        self.assertEqual(self.settings_reads, 0)
        self.assertEqual(self.events, [])
        self.assertEqual(self.credentials, [])
        self.assertEqual(self.sleep_calls, [])

    def test_remote_legacy_process_fields_are_inert_without_changing_tool_arguments(self):
        manifest = self.manifest()
        manifest["additionalFields"].update(
            command="inert", args=["inert"], env={"TOKEN": "inert"},
            additionalSettings={"command": "provider-setting", "env": {"name": "provider-value"}},
            mcp_tools=[{
                "original_name": "echo",
                "input_schema": {"type": "object", "properties": {"env": {"type": "object"}, "args": {"type": "array"}}},
            }],
        )
        plugin = self.factory.create_from_config(manifest)
        for field in ("command", "args", "env"):
            self.assertNotIn(field, plugin.manifest["additionalFields"])
        self.assertEqual(plugin.manifest["additionalFields"]["additionalSettings"]["command"], "provider-setting")
        arguments = {"env": {"name": "tool-value"}, "args": ["tool-value"]}
        with self.caller():
            result = asyncio.run(plugin.call_tool("echo", arguments))
        calls = [event for event in self.events if event[0] == "call_tool"]
        self.assertTrue(result["success"])
        self.assertEqual(calls[0][2], arguments)

    def test_cached_tool_wrappers_and_retry_helper_reject_newly_retired_config(self):
        manifest = self.manifest()
        manifest["additionalFields"]["mcp_tools"] = [{"original_name": "echo"}]
        plugin = self.factory.create_from_config(manifest)
        wrapper = plugin._create_tool_function(plugin._tools[0])
        plugin.manifest["endpoint"] = "stdio://retired"
        with self.caller():
            result = asyncio.run(wrapper(text="test"))
            direct_result = asyncio.run(plugin.invoke_tool("echo", {}))
            with self.assertRaises(self.manifests.McpStdioRemovedError):
                asyncio.run(self.factory._run_with_retries(
                    plugin.manifest, "tool_call", lambda: self.events.append(("unexpected-operation",))
                ))
        self.assertEqual(result["error_type"], "mcp_stdio_removed")
        self.assertEqual(direct_result["error_type"], "mcp_stdio_removed")
        self.assertEqual(self.events, [])
        self.assertEqual(self.settings_reads, 0)

    def test_unknown_transport_is_nonretryable_configuration_failure(self):
        with self.caller():
            result = self.tester.test_mcp_connection(self.manifest(transport="unsupported-transport"))
        self.assertEqual(result["status"], 400)
        self.assertEqual(result["details"]["error_type"], "validation")
        self.assertFalse(result["details"]["retryable"])
        self.assertEqual(self.events, [])
        self.assertEqual(self.sleep_calls, [])

    def test_deployment_allowlist_and_unsafe_floor_cannot_be_disabled_or_widened(self):
        self.settings = {
            "enable_mcp_destination_governance": False,
            "mcp_allowed_destinations": ["*"],
            "mcp_block_unsafe_destinations": False,
        }
        os.environ["ENABLE_MCP_DESTINATION_GOVERNANCE"] = "true"
        os.environ["MCP_ALLOWED_DESTINATIONS"] = "https://allowed.example/mcp"
        with self.caller():
            allowed = self.factory.create_connector(self.manifest())
            with self.assertRaises(PermissionError):
                self.factory.create_connector(self.manifest(endpoint="https://blocked.example/mcp"))
            self.settings["mcp_allowed_destinations"] = ["https://different.example/mcp"]
            with self.assertRaises(PermissionError):
                self.factory.create_connector(self.manifest())
        self.assertIsInstance(allowed, self.connector_types["streamable_http"])
        os.environ["ENABLE_MCP_DESTINATION_GOVERNANCE"] = "false"
        os.environ["MCP_BLOCK_UNSAFE_DESTINATIONS"] = "true"
        with self.caller(), self.assertRaises(PermissionError):
            self.factory.create_connector(self.manifest(endpoint="http://127.0.0.1:9000/mcp"))

    def test_cached_global_plugin_checks_two_callers_and_current_grants(self):
        self.settings["enable_mcp_destination_governance"] = True
        policy = {"item_id": "allowed.example", "allow_all": False, "allowed_users": ["alice"]}
        self.policies["mcp_global_destination"] = [policy]
        manifest = self.manifest(runtime_user_id="alice", user_id="alice")
        plugin = self.factory.create_from_config(manifest)
        plugin.manifest["runtime_user_id"] = "alice"
        plugin.manifest["user_id"] = "alice"
        with self.caller("alice"):
            first = asyncio.run(plugin.call_tool("echo", {"text": "first"}))
        with self.caller("bob"):
            denied = asyncio.run(plugin.call_tool("echo", {"text": "second"}))
        policy["allowed_users"] = ["bob"]
        with self.caller("bob"):
            granted = asyncio.run(plugin.call_tool("echo", {"text": "third"}))
        self.assertTrue(first["success"])
        self.assertFalse(denied["success"])
        self.assertEqual(denied["error_type"], "authorization")
        self.assertTrue(granted["success"])
        calls = [event for event in self.events if event[0] == "call_tool"]
        self.assertEqual(len(calls), 2)

    def test_application_deployment_policy_config_remains_a_floor(self):
        for key in (
            "ENABLE_MCP_DESTINATION_GOVERNANCE", "MCP_BLOCK_UNSAFE_DESTINATIONS",
            "MCP_ALLOWED_DESTINATIONS", "MCP_ALLOWED_PERSONAL_DESTINATIONS",
            "MCP_ALLOWED_GROUP_DESTINATIONS", "MCP_ALLOWED_GLOBAL_DESTINATIONS",
        ):
            os.environ.pop(key, None)
        self.app.config.update(
            ENABLE_MCP_DESTINATION_GOVERNANCE=True, MCP_ALLOWED_DESTINATIONS=["allowed.example"]
        )
        self.settings = {"enable_mcp_destination_governance": False, "mcp_allowed_destinations": ["*"]}
        with self.caller():
            allowed = self.factory.create_connector(self.manifest())
            with self.assertRaises(PermissionError):
                self.factory.create_connector(self.manifest(endpoint="https://blocked.example/mcp"))
        self.assertIsInstance(allowed, self.connector_types["streamable_http"])

    def test_cached_plugin_checks_current_persisted_settings_without_reload(self):
        plugin = self.factory.create_from_config(self.manifest())
        with self.caller():
            first = asyncio.run(plugin.call_tool("echo", {}))
        self.settings.update(
            enable_mcp_destination_governance=True,
            mcp_allowed_global_destinations=["different.example"],
        )
        with self.caller():
            denied = asyncio.run(plugin.call_tool("echo", {}))
        self.settings["mcp_allowed_global_destinations"] = ["allowed.example"]
        with self.caller():
            allowed = asyncio.run(plugin.call_tool("echo", {}))
        self.assertTrue(first["success"])
        self.assertEqual(denied["error_type"], "authorization")
        self.assertTrue(allowed["success"])
        self.assertEqual(self.settings_reads, 3)

    def test_preconfiguration_grants_and_scope_apply_before_connectors(self):
        self.settings = {"enable_mcp_destination_governance": True, "mcp_allowed_destinations": ["*"]}
        manifest = self.manifest()
        manifest["additionalFields"]["preconfiguration_id"] = "azure_mcp_server"
        with self.caller(), self.assertRaises(PermissionError):
            self.factory.create_connector(manifest)
        self.policies["mcp_global_destination"] = [
            {"item_id": "preconfiguration:azure_mcp_server", "allow_all": False, "allowed_users": ["alice"]},
            {"item_id": "https://allowed.example/mcp", "allow_all": True},
        ]
        with self.caller():
            connector = self.factory.create_connector(manifest)
        with self.caller("bob"), self.assertRaises(PermissionError):
            self.factory.create_connector(manifest)
        restricted = {"id": "restricted", "scopeEligibility": ["group"]}
        with patch.object(self.preconfigurations, "get_mcp_server_preconfiguration", return_value=restricted):
            with self.caller(), self.assertRaises(PermissionError):
                self.factory.create_connector(manifest)
        self.assertIsInstance(connector, self.connector_types["streamable_http"])

    def test_policy_read_failure_is_closed_and_secret_safe(self):
        self.settings = {"enable_mcp_destination_governance": True, "mcp_allowed_destinations": ["*"]}
        with patch.object(
            sys.modules["functions_governance"], "list_item_policies",
            side_effect=RuntimeError("unlabelled-provider-secret"),
        ):
            with self.caller():
                result = self.tester.test_mcp_connection(self.manifest())
        self.assertEqual(result["status"], 403)
        self.assertNotIn("unlabelled-provider-secret", repr(result))
        self.assertEqual(self.events, [])

    def test_retries_reauthorize_and_do_not_leak_provider_errors(self):
        manifest = self.manifest()
        manifest["additionalFields"]["retry_count"] = 3

        def fail_and_revoke():
            self.settings.update(enable_mcp_destination_governance=True)
            raise TimeoutError("upstream unlabelled-provider-secret timeout")

        self.connect_hook = fail_and_revoke
        with self.caller():
            result = self.tester.test_mcp_connection(manifest)
        self.assertEqual(result["status"], 403)
        self.assertNotIn("unlabelled-provider-secret", repr(result))
        constructions = [event for event in self.events if event[0] == "construct"]
        self.assertEqual(len(constructions), 1)
        self.assertEqual(self.sleep_calls, [1])

    def test_direct_remote_error_has_stable_safe_failure_payload(self):
        def fail():
            raise ValueError("unlabelled-provider-secret")

        self.connect_hook = fail
        with self.caller():
            result = self.tester.test_mcp_connection(self.manifest())
            plugin_result = asyncio.run(self.factory.create_from_config(self.manifest()).invoke_tool("echo", {}))
        self.assertEqual(result["status"], 400)
        self.assertFalse(plugin_result["success"])
        self.assertNotIn("unlabelled-provider-secret", repr(result))
        self.assertNotIn("unlabelled-provider-secret", repr(plugin_result))

    def test_workflow_synthetic_request_uses_execution_user_not_creator(self):
        plugin = self.factory.create_from_config(self.manifest("personal", scope_id="workflow-user"))
        plugin.manifest["runtime_user_id"] = "creator"
        with self.caller("workflow-user", workflow=True):
            result = asyncio.run(plugin.invoke_tool("echo", {}))
            plugin.manifest["additionalFields"]["transport"] = "stdio"
            retired = asyncio.run(plugin.invoke_tool("echo", {}))
            plugin.manifest["additionalFields"]["transport"] = "streamable_http"
        without_context = asyncio.run(plugin.invoke_tool("echo", {}))
        self.assertTrue(result["success"])
        self.assertEqual(retired["error_type"], "mcp_stdio_removed")
        self.assertFalse(without_context["success"])
        self.assertEqual(without_context["error_type"], "authorization")

    def test_credential_hydration_preserves_origin_and_separate_global_secret_id(self):
        loader, _ = self._load_loaders()
        self.settings = {"enable_key_vault_secret_storage": True, "key_vault_name": "offline-vault"}
        with self.caller():
            for scope, expected_secret_scope, expected_scope_id in (
                ("personal", "user", "alice"), ("group", "group", "group-1"), ("global", "global", "action-1")
            ):
                with self.subTest(scope=scope):
                    manifest = self.manifest(scope, identity_id="identity-1")
                    manifest["auth"] = {"type": "key", "key": "kv:action"}
                    manifest.update(scope="personal", scope_id="forged", is_group=False, is_global=False, user_id="forged")
                    origin = self.manifests.get_action_origin(manifest)
                    resolved = loader.resolve_key_vault_secrets_in_plugins(manifest, self.settings)
                    hydrated = loader.hydrate_workspace_identity_in_plugin(resolved)
                    overlaid = loader._apply_agent_plugin_runtime_overlays([hydrated], group_id="agent-group")[0]
                    self.assertEqual(self.manifests.get_action_origin(overlaid), origin)
                    keyvault_call = self.credentials[-2]
                    self.assertEqual(keyvault_call[2]["scope"], expected_secret_scope)
                    self.assertEqual(keyvault_call[2]["scope_value"], expected_scope_id)
                    self.assertEqual(self.credentials[-1], ("identity", scope, origin.scope_id))

    def test_denied_or_retired_records_never_hydrate_credentials(self):
        loader, _ = self._load_loaders()
        self.settings = {
            "enable_key_vault_secret_storage": True, "key_vault_name": "offline-vault",
            "enable_mcp_destination_governance": True,
        }
        with self.caller():
            for manifest in (
                self.manifest(transport="stdio"),
                self.manifest(scope=None, is_global=True, runtime_user_id="alice"),
                self.manifest(),
            ):
                manifest["auth"] = {"type": "key", "key": "kv:action"}
                manifest["identity_id"] = "identity-1"
                with self.assertRaises((PermissionError, self.manifests.McpStdioRemovedError)):
                    loader.resolve_key_vault_secrets_in_plugins(manifest, {})
                with self.assertRaises((PermissionError, self.manifests.McpStdioRemovedError)):
                    loader.hydrate_workspace_identity_in_plugin(manifest)
        self.assertEqual(self.credentials, [])
        self.assertEqual(self.events, [])

    def test_failed_identity_hydration_cannot_fall_back_to_manifest_credentials(self):
        loader, _ = self._load_loaders()
        manifest = self.manifest(identity_id="identity-1")
        manifest["auth"] = {"type": "key", "key": "untrusted-fallback"}
        with patch.object(loader, "hydrate_action_identity_reference", side_effect=RuntimeError("provider-secret")):
            with self.caller():
                prepared = loader._prepare_plugin_manifests_for_runtime([manifest], {})
        self.assertEqual(prepared, [])
        self.assertEqual(self.events, [])

    def test_credential_hydration_rechecks_settings_floor_and_global_action_id(self):
        loader, _ = self._load_loaders()
        stale_settings = {"enable_key_vault_secret_storage": True, "key_vault_name": "offline-vault"}
        self.settings = {
            **stale_settings, "enable_mcp_destination_governance": True,
            "mcp_allowed_destinations": ["other.example"],
        }
        manifest = self.manifest()
        manifest["auth"] = {"type": "key", "key": "kv:action"}
        with self.caller(), self.assertRaises(PermissionError):
            loader.resolve_key_vault_secrets_in_plugins(manifest, stale_settings)
        self.settings.update(enable_mcp_destination_governance=False, mcp_allowed_destinations=["*"])
        os.environ["ENABLE_MCP_DESTINATION_GOVERNANCE"] = "true"
        os.environ["MCP_ALLOWED_DESTINATIONS"] = "other.example"
        with self.caller(), self.assertRaises(PermissionError):
            loader.resolve_key_vault_secrets_in_plugins(manifest, stale_settings)
        os.environ["ENABLE_MCP_DESTINATION_GOVERNANCE"] = "false"
        missing_id = self.manifest(id="")
        missing_id["auth"] = {"type": "key", "key": "kv:action"}
        with self.caller(), self.assertRaises(PermissionError):
            loader.resolve_key_vault_secrets_in_plugins(missing_id, stale_settings)
        self.assertEqual(self.credentials, [])

    def test_logged_and_fallback_loaders_keep_remote_actions_and_reject_fuzzy_mcp(self):
        loader, logged = self._load_loaders()
        self.stack.enter_context(self.caller())
        self.settings = {"enable_key_vault_secret_storage": True, "key_vault_name": "offline-vault"}
        retired = self.manifest("personal", transport="stdio", name="retired", identity_id="retired-identity")
        retired["auth"] = {"type": "key", "key": "kv:retired-auth-reference"}
        retired["additionalFields"].update(
            command="retired-command-value", args=["retired-argument-value"],
            env={"TOKEN": "retired-environment-value"},
        )
        remote = self.manifest(name="remote")
        remote["type"] = "model-context-protocol"
        fuzzy = self.manifest(name="fuzzy")
        fuzzy["type"] = "mc"
        prepared = loader._prepare_plugin_manifests_for_runtime([retired, remote, fuzzy], self.settings)
        kernel = _Kernel()
        logged_loader = logged.LoggedPluginLoader(kernel)
        results = logged_loader.load_multiple_plugins(prepared, "alice")
        self.assertEqual(results, {"retired": False, "remote": True, "fuzzy": False})
        printed_calls = []
        for fallback in (
            lambda target: loader._load_agent_plugins_original_method(target, prepared),
            lambda target: loader._load_plugins_original_method(target, prepared, {}),
        ):
            target = _Kernel()
            with patch("builtins.print") as printed:
                fallback(target)
            printed_calls.extend(printed.call_args_list)
            self.assertEqual(set(target.plugins), {"remote"})
        self.assertEqual(self.credentials, [])
        self.assertEqual(self.events, [])
        status_logs = [entry for entry in self.logs if entry[1].get("extra", {}).get("code") == "mcp_stdio_removed"]
        self.assertTrue(status_logs)
        diagnostics = repr((self.logs, self.debug_messages, printed_calls))
        for secret in (
            "kv:retired-auth-reference", "retired-command-value",
            "retired-argument-value", "retired-environment-value",
        ):
            self.assertNotIn(secret, diagnostics)
        for plugin_type in ("sql_query", "sql_schema"):
            sql = logged_loader._create_plugin_instance({"name": plugin_type, "type": plugin_type})
            self.assertEqual(sql.manifest["type"], plugin_type)

    def test_python_loader_cannot_relabel_an_mcp_descriptor(self):
        _, logged = self._load_loaders()
        loader = logged.LoggedPluginLoader(_Kernel())
        with self.assertRaises(self.manifests.McpConfigurationError):
            loader._create_plugin_instance({
                "name": "disguised", "type": "python", "module": "mcp_plugin", "class": "McpPlugin",
            })
        self.assertEqual(self.events, [])

    def test_agent_merges_keep_global_source_destination_policy(self):
        loader, _ = self._load_loaders()
        manifest = self.manifest()
        self.settings = {
            "enable_mcp_destination_governance": True,
            "mcp_allowed_global_destinations": ["allowed.example"],
        }
        overlay = loader._apply_agent_plugin_runtime_overlays([manifest], group_id="group-1")[0]
        with self.caller():
            connector = self.factory.create_connector(overlay)
        origin = self.manifests.get_action_origin(overlay)
        self.assertEqual(origin.scope_type, "global")
        self.assertEqual(origin.scope_id, "global")
        self.assertIsInstance(connector, self.connector_types["streamable_http"])
        settings = {**self.settings, "merge_global_semantic_kernel_with_workspace": True}
        for mode in ("group", "per-user"):
            retired = self.manifest(
                "group" if mode == "group" else "personal", transport="stdio", name="retired"
            )
            kernel = _Kernel()
            with (
                self.caller(),
                patch("builtins.print"),
                patch.object(loader, "_get_governed_group_plugin_manifests", return_value=[retired]),
                patch.object(loader, "_get_governed_personal_plugin_manifests", return_value=[retired]),
                patch.object(loader, "_get_governed_global_plugin_manifests", return_value=[manifest]),
            ):
                loader.load_agent_specific_plugins(
                    kernel, ["remote_action", "retired"], settings,
                    mode_label=mode, user_id="alice", group_id="group-1" if mode == "group" else None,
                )
                self.assertEqual(set(kernel.plugins), {"remote_action"})
                result = asyncio.run(kernel.plugins["remote_action"].functions["call_tool"]("echo", {}))
            self.assertTrue(result["success"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
