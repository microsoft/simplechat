#!/usr/bin/env python3
# test_v2_control_center_action.py
"""
Functional test for the Control Center action and "Chat with this dashboard".
Version: 0.261.300
Implemented in: 0.261.300

This test ensures that the read-only Control Center action answers only for Control Center
dashboard viewers and refuses runs without a signed-in session, validates its arguments,
returns bounded chartable rows without writing data or exposing storage errors, and registers
as an action type that runs as the signed-in user. It also checks that the dashboard chat
readiness check reports each requirement with the right remedy, links Admin Settings only for
administrators, and that its route answers without caching or leaking storage errors.
"""

import ast
import importlib
import inspect
import json
import logging
import re
import sys
import types
from contextlib import contextmanager
from importlib.metadata import version as package_version
from pathlib import Path
from unittest.mock import Mock, patch

import werkzeug
from flask import Blueprint, Flask, has_request_context, jsonify, session

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
ROUTE = APP / "route_backend_control_center.py"
AUTH = APP / "functions_authentication.py"
for path in (ROOT / "functional_tests", APP):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

# Imported up front so they stay loaded when each test restores sys.modules.
import semantic_kernel.functions  # noqa: E402,F401
import semantic_kernel_plugins.base_plugin  # noqa: E402,F401

from test_support.app_stubs import stubbed_app_imports  # noqa: E402
from test_support.cosmos_query_guard import cosmos_query_problems  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402


PLUGIN_FUNCTIONS = (
    "get_dashboard_summary",
    "get_daily_activity",
    "get_token_usage",
    "get_top_activity",
    "get_sign_in_pattern",
    "find_entities",
)
OWNER_PARAMETER_NAMES = {"user_id", "group_id", "public_workspace_id", "workspace_id", "conversation_id", "document_id"}


class ReadOnlyContainer:
    """Answer reads by query shape after proving the Python SDK could run each query."""

    def __init__(self, respond=None, documents=None, error=None):
        self.respond = respond or (lambda query, values: [])
        self.documents = documents or {}
        self.error = error
        self.queries = []

    def query_items(self, query, parameters=None, **kwargs):
        if self.error is not None:
            raise self.error
        problems = cosmos_query_problems(query)
        assert not problems, f"Cosmos would reject {query!r}: {problems}"
        self.queries.append({"query": query, "parameters": parameters or [], **kwargs})
        return iter(self.respond(query, {item["name"]: item["value"] for item in parameters or []}))

    def read_item(self, item, partition_key):
        if self.error is not None:
            raise self.error
        assert item == partition_key
        if item not in self.documents:
            raise LookupError(item)
        return self.documents[item]

    def _refuse_write(self, *args, **kwargs):
        raise AssertionError("The Control Center action must never write to storage.")

    create_item = upsert_item = replace_item = delete_item = patch_item = execute_item_batch = _refuse_write


def _activity(query, values):
    if "SELECT DISTINCT VALUE c.user_id" in query:
        return ["u1", "u2"]
    if "SELECT VALUE SUM(c.usage.total_tokens)" in query:
        return [1234]
    if "document_creation" in query and "SELECT VALUE COUNT(1)" in query:
        return [{"group": 2, "public": 1}.get(values.get("@workspace_type"), 5)]
    if "SELECT VALUE COUNT(1)" in query:
        return [3]
    if "c.usage.total_tokens AS tokens" in query:
        return [{
            "timestamp": f"{values['@start_date'][:10]}T10:00:00", "model": "gpt-4o", "tokens": 40,
            "token_type": "chat", "user_id": "u1", "group_id": "g1",
        }]
    if "c.activity_type," in query:
        day = values["@start_date"][:10]
        return [
            {"timestamp": f"{day}T08:00:00", "activity_type": "user_login", "user_id": "u1"},
            {"timestamp": f"{day}T08:30:00", "activity_type": "conversation_creation", "user_id": "u1"},
            {"timestamp": f"{day}T09:00:00", "activity_type": "document_creation", "workspace_type": "group",
             "user_id": "u1", "group_id": "g1"},
        ]
    raise AssertionError(f"Unexpected activity query: {query}")


def _users(query, values):
    if "CONTAINS(LOWER(c.display_name), @search)" in query:
        return [{"id": "u1", "display_name": "Jane Doe", "email": "jane@contoso.com"}]
    if "c.settings.access.status = 'deny'" in query:
        return [1]
    return [4]


def _statuses(query, values):
    if "SELECT VALUE c.status" in query:
        return ["locked", None]
    return [3]


def make_stores(dashboard, *, error=None):
    containers = {
        "activity_logs": ReadOnlyContainer(_activity, error=error),
        "user_settings": ReadOnlyContainer(
            _users, documents={"u1": {"id": "u1", "display_name": "Jane Doe", "email": "jane@contoso.com"}},
        ),
        "groups": ReadOnlyContainer(_statuses, documents={"g1": {"id": "g1", "name": "Finance"}}),
        "public_workspaces": ReadOnlyContainer(_statuses),
        "user_documents": ReadOnlyContainer(lambda query, values: [1]),
        "group_documents": ReadOnlyContainer(lambda query, values: [0]),
        "public_documents": ReadOnlyContainer(lambda query, values: [0]),
        "approvals": ReadOnlyContainer(lambda query, values: [2]),
    }
    return dashboard.DashboardStores(**containers), containers


@contextmanager
def control_center_plugin(extra_modules=None):
    """Import the plugin with the application bootstrap unavailable, recording log_event calls."""
    events = []
    appinsights = types.ModuleType("functions_appinsights")
    appinsights.log_event = lambda message, *args, **kwargs: events.append((message, kwargs))
    invocation_logger = types.ModuleType("semantic_kernel_plugins.plugin_invocation_logger")
    invocation_logger.plugin_function_logger = lambda name: (lambda function: function)
    modules = {
        "functions_appinsights": appinsights,
        "semantic_kernel_plugins.plugin_invocation_logger": invocation_logger,
        # Importing either would build Azure clients; the plugin must load without them.
        "config": None,
        "functions_authentication": None,
        **(extra_modules or {}),
    }
    with stubbed_app_imports(), patch.dict(sys.modules, modules):
        for name in ("semantic_kernel_plugins.control_center_plugin", "functions_control_center_dashboard"):
            sys.modules.pop(name, None)
        plugin_module = importlib.import_module("semantic_kernel_plugins.control_center_plugin")
        dashboard = sys.modules["functions_control_center_dashboard"]
        dashboard._control_center_dashboard_cache.clear()
        dashboard._control_center_entity_name_cache.clear()
        yield plugin_module, dashboard, events


def _call(plugin, name, **arguments):
    defaults = {"find_entities": {"search": "jane"}}
    return getattr(plugin, name)(**{**defaults.get(name, {}), **arguments})


def _auth_functions(get_settings=lambda: {}):
    """The shipped Control Center capability functions, without the authentication bootstrap."""
    tree = ast.parse(AUTH.read_text(encoding="utf-8"))
    nodes = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name in {"get_control_center_capabilities", "get_request_control_center_capabilities"}
    ]
    assert len(nodes) == 2
    namespace = {"session": session, "has_request_context": has_request_context, "get_settings": get_settings}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(AUTH), "exec"), namespace)
    module = types.ModuleType("functions_authentication")
    module.get_control_center_capabilities = namespace["get_control_center_capabilities"]
    module.get_request_control_center_capabilities = namespace["get_request_control_center_capabilities"]
    return module


# --------------------------------------------------------------------------------------
# The action
# --------------------------------------------------------------------------------------

def test_every_function_refuses_callers_without_dashboard_access():
    with control_center_plugin() as (plugin_module, _dashboard, events):
        stores_factory = Mock(side_effect=AssertionError("Storage must not be opened for a refused call."))
        plugin = plugin_module.ControlCenterPlugin(
            stores_factory=stores_factory, capabilities=lambda: {"can_view_dashboard": False},
        )
        for name in PLUGIN_FUNCTIONS:
            result = _call(plugin, name)
            assert result == {
                "success": False,
                "error": plugin_module.CONTROL_CENTER_ACCESS_DENIED,
                "error_type": "permission",
            }, name
        stores_factory.assert_not_called()
        refusals = [event for event in events if event[0].startswith("[CONTROL_CENTER_ACTION] Refused")]
        assert len(refusals) == len(PLUGIN_FUNCTIONS)


def test_access_check_failures_fail_closed():
    with control_center_plugin() as (plugin_module, _dashboard, events):
        stores_factory = Mock()

        def broken_capabilities():
            raise RuntimeError("PRIVATE-IDENTITY-DETAIL")

        plugin = plugin_module.ControlCenterPlugin(stores_factory=stores_factory, capabilities=broken_capabilities)
        result = plugin.get_dashboard_summary()
        assert result["error_type"] == "permission"
        stores_factory.assert_not_called()
        assert "PRIVATE-IDENTITY-DETAIL" not in json.dumps(events, default=str)
        assert any(kwargs.get("extra", {}).get("error_type") == "RuntimeError" for _message, kwargs in events)


def test_default_access_follows_the_signed_in_session_and_refuses_scheduled_runs():
    settings = {}
    auth = _auth_functions(get_settings=lambda: settings)
    with control_center_plugin({"functions_authentication": auth}) as (plugin_module, dashboard, _events):
        stores, _containers = make_stores(dashboard)
        plugin = plugin_module.ControlCenterPlugin(stores_factory=lambda: stores)

        # A scheduled run has no request, so it has no signed-in viewer.
        scheduled = plugin.get_dashboard_summary(days=7)
        assert scheduled["error_type"] == "permission"

        app = Flask("control_center_action_test")
        app.secret_key = "test-only"
        cases = [
            ({}, ["Admin"], True),
            ({}, ["User"], False),
            ({}, ["ControlCenterDashboardReader"], False),
            ({"require_member_of_control_center_admin": True,
              "require_member_of_control_center_dashboard_reader": True}, ["ControlCenterDashboardReader"], True),
            ({"require_member_of_control_center_admin": True}, ["Admin"], False),
        ]
        for case_settings, roles, allowed in cases:
            settings.clear()
            settings.update(case_settings)
            with app.test_request_context("/"):
                session["user"] = {"oid": "u1", "roles": roles}
                result = plugin.get_dashboard_summary(days=7)
            assert result["success"] is allowed, (case_settings, roles, result)


def test_dashboard_viewers_get_bounded_chartable_rows_without_writes():
    with control_center_plugin() as (plugin_module, dashboard, _events):
        stores, containers = make_stores(dashboard)
        plugin = plugin_module.ControlCenterPlugin(
            stores_factory=lambda: stores, capabilities=lambda: {"can_view_dashboard": True},
        )
        dates = {"start_date": "2026-09-01", "end_date": "2026-09-07"}

        summary = plugin.get_dashboard_summary(**dates)
        assert summary["success"] is True
        assert summary["period"]["start_date"] == "2026-09-01"
        assert summary["previous_period"]["end_date"] == "2026-08-31"
        metrics = {row["metric"]: row for row in summary["rows"]}
        assert metrics["Signed-in users"]["value"] == 2
        assert metrics["Tokens used"]["value"] == 1234
        assert all(row["definition"] for row in summary["rows"])

        daily = plugin.get_daily_activity(**dates)
        assert len(daily["rows"]) == 7
        assert daily["totals"] == {
            "sign_ins": 1, "conversations_created": 1, "uploads_personal": 0, "uploads_group": 1, "uploads_public": 0,
        }

        narrowed = plugin.get_daily_activity(**dates, user="u1", workspace_type="group")
        assert narrowed["filters"] == {"user": {"id": "u1", "name": "Jane Doe"}, "workspace_type": "group"}
        assert any("Sign-ins are not recorded against a workspace" in note for note in narrowed["notes"])

        by_model = plugin.get_token_usage(group_by="model", **dates)
        assert by_model["rows"] == [{"model": "gpt-4o", "tokens": 40}]
        by_user = plugin.get_token_usage(group_by="user", group="g1", **dates)
        assert by_user["rows"][0]["name"] == "Jane Doe"
        # A group filter implies group workspaces, as it does on the dashboard.
        assert by_user["filters"] == {"group": {"id": "g1", "name": "Finance"}, "workspace_type": "group"}

        top = plugin.get_top_activity(entity="groups", limit=5, **dates)
        assert top["rows"] == [{"id": "g1", "activity_count": 1, "name": "Finance", "detail": "", "found": True}]

        pattern = plugin.get_sign_in_pattern(**dates)
        assert pattern["rows"] == [{"weekday": "Tuesday", "hour_utc": 8, "sign_ins": 1}]

        found = plugin.find_entities(kind="users", search="Jane")
        assert found["rows"] == [{"id": "u1", "name": "Jane Doe", "email": "jane@contoso.com"}]
        search = containers["user_settings"].queries[-1]
        assert {"name": "@search", "value": "jane"} in search["parameters"]
        assert "jane" not in search["query"].lower().replace("@search", "")


def test_invalid_arguments_are_refused_before_reading_activity():
    with control_center_plugin() as (plugin_module, dashboard, _events):
        stores, containers = make_stores(dashboard)
        plugin = plugin_module.ControlCenterPlugin(
            stores_factory=lambda: stores, capabilities=lambda: {"can_view_dashboard": True},
        )
        invalid_calls = [
            ("get_token_usage", {"group_by": "conversation"}),
            ("get_token_usage", {"user": "Jane Doe"}),
            ("get_token_usage", {"token_type": "images"}),
            ("get_token_usage", {"model": "m" * 201}),
            ("get_token_usage", {"limit": 0}),
            ("get_token_usage", {"limit": 51}),
            ("get_token_usage", {"limit": True}),
            ("get_daily_activity", {"workspace_type": "shared"}),
            ("get_daily_activity", {"group": "x" * 200}),
            ("get_dashboard_summary", {"days": 0}),
            ("get_dashboard_summary", {"days": 367}),
            ("get_dashboard_summary", {"start_date": "2026-09-01"}),
            ("get_dashboard_summary", {"start_date": "2026-09-07", "end_date": "2026-09-01"}),
            ("get_top_activity", {"entity": "conversations"}),
            ("find_entities", {"kind": "documents"}),
            ("find_entities", {"search": "j"}),
        ]
        for name, arguments in invalid_calls:
            result = _call(plugin, name, **arguments)
            assert result["success"] is False and result["error_type"] == "validation", (name, arguments, result)
            assert isinstance(result["error"], str) and result["error"]
        name_instead_of_id = _call(plugin, "get_token_usage", user="Jane Doe")
        assert "find_entities" in name_instead_of_id["error"]
        assert all(not container.queries for container in containers.values())


def test_storage_failures_return_a_generic_error():
    with control_center_plugin() as (plugin_module, dashboard, events):
        stores, _containers = make_stores(dashboard, error=RuntimeError("PRIVATE-CONNECTION-DETAIL"))
        plugin = plugin_module.ControlCenterPlugin(
            stores_factory=lambda: stores, capabilities=lambda: {"can_view_dashboard": True},
        )
        result = plugin.get_token_usage(days=7)
        assert result == {
            "success": False, "error": plugin_module.CONTROL_CENTER_READ_FAILED, "error_type": "unexpected",
        }
        assert "PRIVATE-CONNECTION-DETAIL" not in json.dumps(events, default=str)
        failures = [kwargs for message, kwargs in events if message.startswith("[CONTROL_CENTER_ACTION] A Control Center tool call failed")]
        assert failures and failures[0]["extra"] == {"operation": "get_token_usage", "error_type": "RuntimeError"}
        assert failures[0]["level"] == logging.ERROR


def test_plugin_exposes_six_kernel_functions_without_owner_parameters():
    with control_center_plugin() as (plugin_module, _dashboard, _events):
        plugin = plugin_module.ControlCenterPlugin()
        assert plugin.display_name == "Control Center"
        assert tuple(plugin.get_functions()) == PLUGIN_FUNCTIONS
        assert plugin.metadata["type"] == "control_center"
        assert [method["name"] for method in plugin.metadata["methods"]] == list(PLUGIN_FUNCTIONS)
        for name in PLUGIN_FUNCTIONS:
            method = getattr(plugin, name)
            assert getattr(method, "__kernel_function__", False) is True, name
            parameters = set(inspect.signature(method).parameters)
            assert not parameters & OWNER_PARAMETER_NAMES, (name, parameters)


def test_action_type_registration_runs_as_the_signed_in_user():
    from json_schema_validation import PLUGIN_ENDPOINT_DEFAULTS, validate_plugin

    definition = json.loads((APP / "static" / "json" / "schemas" / "control_center.definition.json").read_text(encoding="utf-8"))
    assert definition["allowedAuthTypes"] == ["user"]
    assert definition["defaultAuthType"] == "user"
    assert PLUGIN_ENDPOINT_DEFAULTS["control_center"] == "control_center://internal"

    manifest = {
        "name": "control_center", "displayName": "Control Center", "type": "control_center",
        "description": "Usage insights", "endpoint": "control_center://internal",
        "auth": {"type": "user"}, "metadata": {}, "additionalFields": {},
    }
    valid = validate_plugin(dict(manifest))
    blank_endpoint = validate_plugin({**manifest, "endpoint": ""})
    key_auth = validate_plugin({**manifest, "auth": {"type": "key", "key": "secret"}})
    assert valid is None
    assert blank_endpoint is None
    assert key_auth and "not supported" in key_auth

    plugins_route = (APP / "route_backend_plugins.py").read_text(encoding="utf-8")
    branch = plugins_route.split("elif plugin_type == CONTROL_CENTER_ACTION_TYPE:", 1)[1].split("elif plugin_type ==", 1)[0]
    assert "plugin_payload['auth'] = {'type': 'user'}" in branch
    assert "CONTROL_CENTER_ACTION_DEFAULT_ENDPOINT" in branch
    assert "CONTROL_CENTER_ACTION_DEFAULT_DESCRIPTION" in branch

    stepper = (APP / "static" / "js" / "plugin_modal_stepper.js").read_text(encoding="utf-8")
    assert "'control_center'" in stepper.split("HIDDEN_ACTION_TYPES", 1)[1].split(";", 1)[0]
    registry = (ROOT / "application" / "v2_ui" / "src" / "lib" / "workspaceActionRegistry.ts").read_text(encoding="utf-8")
    entry = registry.split("control_center: {", 1)[1].split("},\n", 1)[0]
    assert "internal: true" in entry and "control_center://internal" in entry and "type: 'user'" in entry


# --------------------------------------------------------------------------------------
# Chat with this dashboard: readiness
# --------------------------------------------------------------------------------------

def _readiness_module():
    sys.modules.pop("functions_control_center_dashboard_chat", None)
    return importlib.import_module("functions_control_center_dashboard_chat")


def readiness(**overrides):
    arguments = {
        "settings": {
            "enable_semantic_kernel": True,
            "enable_chat_orchestration": True,
            "enable_chat_orchestration_actions": True,
        },
        "user_roles": ["Admin"],
        "is_admin": True,
        "stored_actions": [{"id": "cc", "name": "control_center", "display_name": "Usage insights",
                            "type": "control_center", "is_enabled": True}],
        "available_actions": [{"action_ref": "ref-1", "display_name": "Usage insights", "type": "control_center"}],
        "governance_allows": lambda action: True,
        "action_invoke_allowlisted": True,
    }
    arguments.update(overrides)
    return _readiness_module().build_dashboard_chat_readiness(**arguments)


def _requirement(result, requirement_id):
    return next(item for item in result["requirements"] if item["id"] == requirement_id)


def test_readiness_is_ready_when_every_requirement_is_met():
    result = readiness()
    assert result["ready"] is True
    assert result["action"] == {"name": "Usage insights"}
    assert [item["id"] for item in result["requirements"]] == [
        "agents", "orchestration", "action_access", "control_center_action",
    ]
    for item in result["requirements"]:
        assert item["met"] is True
        assert item["detail"] == item["remedy"] == ""
        assert item["settings_link"] is None

    chosen = readiness(available_actions=[
        {"action_ref": "b", "display_name": "zeta insights", "type": "control_center"},
        {"action_ref": "a", "display_name": "Alpha insights", "type": "control_center"},
    ])
    assert chosen["action"] == {"name": "Alpha insights"}


def test_each_setting_names_its_remedy_and_links_only_for_administrators():
    links = _readiness_module().DASHBOARD_CHAT_SETTINGS_LINKS
    cases = [
        ("agents", {"enable_semantic_kernel": False}, links["agents"], "Enable Agents"),
        ("orchestration", {"enable_chat_orchestration": False}, links["orchestration"], "Enable Chat Orchestration"),
        ("action_access", {"enable_chat_orchestration_actions": False}, links["action_access"], "Enable Action Access"),
    ]
    base = readiness()
    assert base["ready"] is True
    for requirement_id, change, link, label in cases:
        settings = {**{
            "enable_semantic_kernel": True,
            "enable_chat_orchestration": True,
            "enable_chat_orchestration_actions": True,
        }, **change}
        admin = _requirement(readiness(settings=settings), requirement_id)
        assert admin["met"] is False and admin["settings_link"] == link and label in admin["remedy"], admin
        reader = _requirement(
            readiness(settings=settings, is_admin=False, user_roles=["User", "ControlCenterDashboardReader"]),
            requirement_id,
        )
        assert reader["settings_link"] is None
        assert reader["remedy"].startswith("Ask a SimpleChat administrator") and label in reader["remedy"]

    capability = _requirement(readiness(action_invoke_allowlisted=False), "action_access")
    assert capability["met"] is False and "Use an action" in capability["detail"]


def test_missing_control_center_action_explains_the_exact_reason():
    links = _readiness_module().DASHBOARD_CHAT_SETTINGS_LINKS
    enabled = [{"id": "cc", "name": "control_center", "type": "control_center", "is_enabled": True}]
    cases = [
        ({"stored_actions": []}, "No Control Center action exists yet.", links["new_action"]),
        ({"stored_actions": [{**enabled[0], "is_enabled": False}]}, "turned off", links["actions"]),
        ({"settings": {"enable_semantic_kernel": False, "enable_chat_orchestration": True,
                       "enable_chat_orchestration_actions": True}}, "once agents and actions are on", links["agents"]),
        ({"settings": {"enable_semantic_kernel": True, "enable_chat_orchestration": True,
                       "enable_chat_orchestration_actions": True, "per_user_semantic_kernel": True}},
         "Workspace Mode", links["agents"]),
        ({"governance_allows": lambda action: False}, "Governance", links["governance"]),
        ({}, "not available to your account", links["actions"]),
    ]
    for overrides, detail, link in cases:
        result = readiness(**{"stored_actions": enabled, **overrides, "available_actions": []})
        requirement = _requirement(result, "control_center_action")
        assert result["ready"] is False and result["action"] is None
        assert requirement["met"] is False and detail in requirement["detail"], (overrides, requirement)
        assert requirement["settings_link"] == link

    merged = readiness(
        settings={"enable_semantic_kernel": True, "enable_chat_orchestration": True,
                  "enable_chat_orchestration_actions": True, "per_user_semantic_kernel": True,
                  "merge_global_semantic_kernel_with_workspace": True},
        stored_actions=enabled, available_actions=[],
    )
    assert "Workspace Mode" not in _requirement(merged, "control_center_action")["detail"]


def test_dashboard_readers_without_chat_access_are_told_so():
    result = readiness(user_roles=["ControlCenterDashboardReader"], is_admin=False)
    access = _requirement(result, "chat_access")
    assert result["ready"] is False
    assert access["met"] is False and "User app role" in access["remedy"]
    assert access["settings_link"] is None


def test_settings_links_open_real_admin_sections_and_pass_the_frontend_allowlist():
    module = _readiness_module()
    nav = (APP / "admin_settings_nav.py").read_text(encoding="utf-8")
    section_ids = set(re.findall(r'"id": "([a-z0-9-]+)"', nav))
    dashboard_chat = (ROOT / "application" / "v2_ui" / "src" / "components" / "controlCenter" / "DashboardChat.tsx").read_text(encoding="utf-8")
    allowlist_source = re.search(r"const ADMIN_SETTINGS_PATH = /(.+)/;", dashboard_chat).group(1)
    allowlist = re.compile(allowlist_source)
    for link in module.DASHBOARD_CHAT_SETTINGS_LINKS.values():
        assert allowlist.fullmatch(link), link
        if link.startswith("/admin/settings/"):
            assert link.rsplit("/", 1)[1] in section_ids, link
    assert not allowlist.fullmatch("/admin/settings/../../logout")
    assert not allowlist.fullmatch("https://example.com/admin/actions")


def test_action_records_keep_only_control_center_fields():
    records = _readiness_module().control_center_action_records([
        {"id": "cc", "name": "insights", "displayName": "Usage", "type": " Control_Center ",
         "auth": {"type": "key", "key": "secret"}, "additionalFields": {"token": "secret"}},
        {"id": "other", "type": "openapi"},
        "not-a-record",
        {"id": "untyped"},
    ], "control_center")
    assert records == [{
        "id": "cc", "name": "insights", "display_name": "Usage", "type": " Control_Center ", "is_enabled": True,
    }]


# --------------------------------------------------------------------------------------
# Chat with this dashboard: route
# --------------------------------------------------------------------------------------

def readiness_route(*, roles, settings, stored=None, catalog=None, user_id="u1", error=None):
    tree = ast.parse(ROUTE.read_text(encoding="utf-8"))
    node = next(
        item for item in ast.walk(tree)
        if isinstance(item, ast.FunctionDef) and item.name == "api_v2_control_center_dashboard_chat_readiness"
    )
    module = _readiness_module()
    blueprint = Blueprint("dashboard_chat_readiness_test", __name__)
    events = []
    container = ReadOnlyContainer(lambda query, values: list(stored or []), error=error)
    catalog_builder = Mock(return_value=list(catalog or []))

    def passthrough(*_args, **_kwargs):
        return lambda function: function

    namespace = {
        "bp": blueprint, "swagger_route": passthrough, "get_auth_security": lambda: None,
        "login_required": lambda function: function, "control_center_required": passthrough,
        "get_settings": lambda: dict(settings),
        "session": {"user": {"oid": user_id, "roles": roles}},
        "get_current_user_id": lambda: user_id,
        "control_center_action_records": module.control_center_action_records,
        "cosmos_global_actions_container": container,
        "build_accessible_action_catalog": catalog_builder,
        "CONTROL_CENTER_ACTION_TYPE": "control_center",
        "build_dashboard_chat_readiness": module.build_dashboard_chat_readiness,
        "is_global_action_access_allowed": lambda actor, action: True,
        "capability_allowlisted": lambda values, capability: capability == "action_invoke",
        "CAPABILITY_ACTION_INVOKE": "action_invoke",
        "jsonify": jsonify,
        "log_event": lambda *args, **kwargs: events.append((args, kwargs)),
        "logging": logging,
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(ROUTE), "exec"), namespace)
    app = Flask("dashboard_chat_readiness_test")
    app.config.update(TESTING=True)
    app.register_blueprint(blueprint)
    # Flask 2.x test clients read werkzeug.__version__, which Werkzeug 3 no longer defines.
    with patch.object(werkzeug, "__version__", package_version("werkzeug"), create=True):
        client = app.test_client()
    decorators = [ast.unparse(item) for item in node.decorator_list]
    return client, catalog_builder, container, events, decorators


def test_readiness_route_is_dashboard_gated_and_never_cached():
    enabled_settings = {
        "enable_semantic_kernel": True, "enable_chat_orchestration": True, "enable_chat_orchestration_actions": True,
    }
    client, catalog_builder, container, _events, decorators = readiness_route(
        roles=["Admin"], settings=enabled_settings,
        stored=[{"id": "cc", "name": "control_center", "type": "control_center", "is_enabled": True}],
        catalog=[{"action_ref": "r", "display_name": "Usage insights", "type": "Control_Center"},
                 {"action_ref": "x", "display_name": "Tickets", "type": "openapi"}],
    )
    assert decorators[:4] == [
        "bp.route('/api/v2/control-center/dashboard/chat-readiness', methods=['GET'])",
        "swagger_route(security=get_auth_security())",
        "login_required",
        "control_center_required('dashboard')",
    ]
    response = client.get("/api/v2/control-center/dashboard/chat-readiness")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    payload = response.get_json()
    assert payload["ready"] is True and payload["action"] == {"name": "Usage insights"}
    catalog_builder.assert_called_once_with("u1", settings=enabled_settings, user_roles=["Admin"])
    query = container.queries[0]
    assert "LOWER(c.type) = @action_type" in query["query"]
    assert query["parameters"] == [{"name": "@action_type", "value": "control_center"}]


def test_readiness_route_links_settings_only_for_administrators():
    client, *_rest = readiness_route(
        roles=["ControlCenterAdmin", "User"], settings={"enable_semantic_kernel": False},
    )
    payload = client.get("/api/v2/control-center/dashboard/chat-readiness").get_json()
    assert payload["ready"] is False
    assert all(item["settings_link"] is None for item in payload["requirements"])
    assert all(item["remedy"].startswith("Ask") for item in payload["requirements"] if not item["met"])

    client, catalog_builder, *_rest = readiness_route(roles=["Admin"], settings={}, user_id=None)
    payload = client.get("/api/v2/control-center/dashboard/chat-readiness").get_json()
    catalog_builder.assert_not_called()
    assert payload["ready"] is False
    assert any(item["settings_link"] for item in payload["requirements"])


def test_readiness_route_failures_do_not_expose_details():
    client, _catalog, _container, events, _decorators = readiness_route(
        roles=["Admin"], settings={}, error=RuntimeError("PRIVATE-STORAGE-DETAIL"),
    )
    response = client.get("/api/v2/control-center/dashboard/chat-readiness")
    assert response.status_code == 500
    assert "PRIVATE-STORAGE-DETAIL" not in response.get_data(as_text=True)
    assert events and events[0][1]["extra"] == {"error_type": "RuntimeError"}


def test_version_is_at_least_implementation_version():
    assert_app_version_at_least("0.261.300")


TESTS = [
    test_every_function_refuses_callers_without_dashboard_access,
    test_access_check_failures_fail_closed,
    test_default_access_follows_the_signed_in_session_and_refuses_scheduled_runs,
    test_dashboard_viewers_get_bounded_chartable_rows_without_writes,
    test_invalid_arguments_are_refused_before_reading_activity,
    test_storage_failures_return_a_generic_error,
    test_plugin_exposes_six_kernel_functions_without_owner_parameters,
    test_action_type_registration_runs_as_the_signed_in_user,
    test_readiness_is_ready_when_every_requirement_is_met,
    test_each_setting_names_its_remedy_and_links_only_for_administrators,
    test_missing_control_center_action_explains_the_exact_reason,
    test_dashboard_readers_without_chat_access_are_told_so,
    test_settings_links_open_real_admin_sections_and_pass_the_frontend_allowlist,
    test_action_records_keep_only_control_center_fields,
    test_readiness_route_is_dashboard_gated_and_never_cached,
    test_readiness_route_links_settings_only_for_administrators,
    test_readiness_route_failures_do_not_expose_details,
    test_version_is_at_least_implementation_version,
]


if __name__ == "__main__":
    for test in TESTS:
        test()
        print(f"PASS {test.__name__}")
    print(f"{len(TESTS)}/{len(TESTS)} Control Center action checks passed")
