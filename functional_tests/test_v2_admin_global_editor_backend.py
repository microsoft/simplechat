#!/usr/bin/env python3
# test_v2_admin_global_editor_backend.py
"""
Functional test for the V2 Admin Settings global agent and action editor backend.
Version: 0.261.268
Implemented in: 0.261.268

Global agents and actions used to be authored only through the classic
``/api/admin/agents`` and ``/api/admin/plugins`` routes, which save whole documents
by name with no revision. The V2 editors now serve them through the same editor
engine personal and group records use. This test loads the real engine and the real
orchestration module with the Cosmos, Key Vault and logging boundaries replaced by
in-memory stand-ins, and pins what the global scope adds:

- credentials resolve in the ``global`` Key Vault namespace keyed by the record id,
  the naming the classic global saves use, while personal and group scoping is
  unchanged;
- every write is conditional on the revision the editor opened, and a stale one is
  refused with nothing written;
- names are unique among global records ignoring case, and the default agent
  cannot be deleted;
- the stored shape is the one the classic global saves write;
- the agent editor options offer every agent type and only global connections, with
  secrets masked; and
- renaming the default agent keeps it selected.
"""

import importlib.util
import sys
import uuid
from copy import deepcopy
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.versioning import assert_app_version_at_least


APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"


class CosmosHttpResponseError(Exception):
    def __init__(self, status_code=500):
        super().__init__(f"status {status_code}")
        self.status_code = status_code


class CosmosResourceNotFoundError(CosmosHttpResponseError):
    def __init__(self):
        super().__init__(404)


class FakeContainer:
    """A global container: partitioned by id, every write stamped with a new etag."""

    def __init__(self):
        self.items = {}
        self.writes = []
        self._revision = 0

    def seed(self, record):
        return self._stamp(record)

    def _stamp(self, body):
        self._revision += 1
        stored = deepcopy(body)
        stored["_etag"] = f"etag-{self._revision}"
        self.items[stored["id"]] = stored
        return deepcopy(stored)

    def read_item(self, item, partition_key):
        assert partition_key == item, "Global records are partitioned by their own id."
        if item not in self.items:
            raise CosmosResourceNotFoundError()
        return deepcopy(self.items[item])

    def query_items(self, query, parameters=None, enable_cross_partition_query=False, partition_key=None):
        assert enable_cross_partition_query, "Global queries span every partition."
        if "STRINGEQUALS" in query:
            name = parameters[0]["value"].lower()
            return [{"id": item["id"]} for item in self.items.values() if str(item.get("name", "")).lower() == name]
        return [deepcopy(item) for item in self.items.values()]

    def create_item(self, body):
        if body["id"] in self.items:
            raise CosmosHttpResponseError(409)
        self.writes.append(("create", body["id"]))
        return self._stamp(body)

    def replace_item(self, item, body, etag, match_condition):
        assert match_condition == "IfNotModified"
        current = self.items.get(item)
        if current is None or current["_etag"] != etag:
            raise CosmosHttpResponseError(412)
        self.writes.append(("replace", item, etag))
        return self._stamp(body)

    def delete_item(self, item, partition_key, etag, match_condition):
        assert partition_key == item and match_condition == "IfNotModified"
        current = self.items.get(item)
        if current is None or current["_etag"] != etag:
            raise CosmosHttpResponseError(412)
        self.writes.append(("delete", item))
        del self.items[item]


def _module(name, **attributes):
    module = ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    return module


@pytest.fixture
def engine(monkeypatch):
    """Load the real engine and access module with in-memory service boundaries."""
    monkeypatch.syspath_prepend(str(APP_ROOT))
    agents_container, actions_container = FakeContainer(), FakeContainer()
    calls = SimpleNamespace(cache=[], delegation=[], identities=[], activity=[], settings_updates=[])
    settings = {
        "enable_semantic_kernel": True,
        "global_selected_agent": {"name": "default_agent", "is_global": True, "is_group": False},
        "enable_key_vault_secret_storage": False,
        "enable_agent_template_gallery": True,
        "enable_time_plugin": True,
    }

    def redact(record):
        result = deepcopy(record)
        if isinstance(result.get("auth"), dict) and result["auth"].get("key"):
            result["auth"]["key"] = "***REDACTED***"
        return result

    def activity(name):
        return lambda **kwargs: calls.activity.append((name, kwargs))

    stubs = {
        "functions_ai_connections": _module(
            "functions_ai_connections",
            filter_model_endpoints_by_capability=lambda endpoints, preserve_empty=True: list(endpoints),
        ),
        "config": _module(
            "config",
            cosmos_global_agents_container=agents_container,
            cosmos_global_actions_container=actions_container,
        ),
        "azure.cosmos.exceptions": _module(
            "azure.cosmos.exceptions",
            CosmosHttpResponseError=CosmosHttpResponseError,
            CosmosResourceNotFoundError=CosmosResourceNotFoundError,
        ),
        "azure.core": _module("azure.core", MatchConditions=SimpleNamespace(IfNotModified="IfNotModified")),
        "functions_keyvault": _module(
            "functions_keyvault",
            validate_secret_name_dynamic=lambda value: False,
            redact_plugin_secret_values=redact,
            AGENT_SENSITIVE_SECRET_FIELDS=[],
            SQL_PLUGIN_SENSITIVE_AUTH_FIELDS=set(),
        ),
        "functions_agent_delegation": _module(
            "functions_agent_delegation",
            validate_agent_delegation_bindings=lambda record, **kwargs: calls.delegation.append(("agent", kwargs)),
            validate_agent_action_for_scope=lambda record, **kwargs: calls.delegation.append(("action", kwargs)) or record,
        ),
        "functions_workspace_identities": _module(
            "functions_workspace_identities",
            WORKSPACE_IDENTITY_SCOPE_GLOBAL="global",
            validate_action_identity_reference=lambda record, scope_type, scope_id: calls.identities.append((scope_type, scope_id)),
        ),
        "functions_chat_bootstrap_cache": _module(
            "functions_chat_bootstrap_cache",
            bump_chat_bootstrap_global_cache_version=lambda reason: calls.cache.append(("global", reason)),
            bump_chat_bootstrap_user_cache_version=lambda user_id, reason: calls.cache.append(("user", reason)),
        ),
        "functions_appinsights": _module("functions_appinsights", log_event=lambda *args, **kwargs: None),
        "functions_activity_logging": _module(
            "functions_activity_logging",
            log_agent_creation=activity("agent_creation"),
            log_agent_update=activity("agent_update"),
            log_agent_deletion=activity("agent_deletion"),
            log_action_creation=activity("action_creation"),
            log_action_update=activity("action_update"),
            log_action_deletion=activity("action_deletion"),
        ),
        "json_schema_validation": _module("json_schema_validation", load_schema=lambda name: {}),
        "functions_settings": _module(
            "functions_settings",
            get_settings=lambda: deepcopy(settings),
            update_settings=lambda updates, **kwargs: calls.settings_updates.append(updates) or True,
            sanitize_settings_for_user=lambda values: deepcopy(values),
        ),
        "functions_agent_templates": _module(
            "functions_agent_templates",
            agent_template_submission_decision=lambda current, is_admin: (bool(is_admin), None),
        ),
    }
    for name, module in stubs.items():
        monkeypatch.setitem(sys.modules, name, module)

    loaded = {}
    for name in ("functions_workspace_authoring", "functions_global_editor_access"):
        monkeypatch.delitem(sys.modules, name, raising=False)
        spec = importlib.util.spec_from_file_location(name, APP_ROOT / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, name, module)
        spec.loader.exec_module(module)
        loaded[name] = module

    return SimpleNamespace(
        authoring=loaded["functions_workspace_authoring"],
        access=loaded["functions_global_editor_access"],
        agents=agents_container,
        actions=actions_container,
        settings=settings,
        calls=calls,
    )


def passthrough(user_id, record, settings, existing):
    """A prepare step that accepts the merged record, as the route's would."""
    return deepcopy(record), None


def agent_body(**updates):
    return {"updates": {"id": str(uuid.uuid4()), "name": "research", "display_name": "Research",
                        "instructions": "Help.", "agent_type": "local", **updates}}


def test_version_at_least_implementation():
    assert_app_version_at_least("0.261.268")


def test_global_secrets_use_the_classic_global_namespace(engine):
    secret_scope = engine.authoring._secret_scope
    record = {"id": "record-1", "name": "connector"}
    assert secret_scope("agents", "admin-1", record, ("azure_openai_gpt_key",), global_scope=True) == (
        "record-1", "agent", "global",
    )
    assert secret_scope("actions", "admin-1", record, ("auth", "key"), global_scope=True) == (
        "record-1", "action", "global",
    )
    assert secret_scope("actions", "admin-1", record, ("additionalFields", "token__Secret"), global_scope=True) == (
        "record-1", "action-addset", "global",
    )
    # Personal and group scoping are unchanged.
    assert secret_scope("actions", "admin-1", record, ("auth", "key")) == ("admin-1", "action", "user")
    assert secret_scope("actions", "admin-1", record, ("auth", "key"), group_id="g-1") == ("g-1", "action", "group")


def test_creating_a_global_agent_stores_the_classic_global_shape(engine):
    saved = engine.authoring.apply_global_agent_write("admin-1", None, agent_body(), passthrough, engine.settings)

    stored = engine.agents.items[saved["id"]]
    assert stored["is_global"] is True and stored["is_group"] is False
    assert stored["created_by"] == stored["modified_by"] == "admin-1"
    assert stored["is_enabled"] is True
    assert "user_id" not in stored and "group_id" not in stored
    assert engine.agents.writes == [("create", saved["id"])]
    assert ("global", "global_agent_saved") in engine.calls.cache
    assert engine.calls.delegation[-1][1]["scope_type"] == "global"


def test_a_global_agent_needs_a_client_allocated_id(engine):
    body = agent_body()
    body["updates"]["id"] = "not-a-uuid"
    with pytest.raises(engine.authoring.WorkspaceAuthoringValidation):
        engine.authoring.apply_global_agent_write("admin-1", None, body, passthrough, engine.settings)
    assert engine.agents.writes == []


def test_a_stale_revision_is_refused_with_nothing_written(engine):
    seeded = engine.agents.seed({"id": "a-1", "name": "research", "display_name": "Research",
                                 "instructions": "Help.", "agent_type": "local", "is_global": True})
    existing = engine.authoring.read_global_editor_record("agents", "a-1")
    engine.agents.seed({**seeded, "description": "Changed elsewhere."})

    with pytest.raises(engine.authoring.WorkspaceAuthoringConflict):
        engine.authoring.apply_global_agent_write(
            "admin-1", existing, {"updates": {"description": "Mine."}, "expected_revision": existing["_etag"]},
            passthrough, engine.settings,
        )
    assert engine.agents.writes == []


def test_an_update_is_conditional_on_the_opened_revision(engine):
    engine.agents.seed({"id": "a-1", "name": "research", "display_name": "Research",
                        "instructions": "Help.", "agent_type": "local", "is_global": True,
                        "created_by": "someone", "created_at": "2026-01-01T00:00:00"})
    existing = engine.authoring.read_global_editor_record("agents", "a-1")

    saved = engine.authoring.apply_global_agent_write(
        "admin-1", existing, {"updates": {"description": "Updated."}, "expected_revision": existing["_etag"]},
        passthrough, engine.settings,
    )

    assert engine.agents.writes == [("replace", "a-1", existing["_etag"])]
    assert saved["description"] == "Updated."
    assert saved["created_by"] == "someone", "The original author is kept."
    assert saved["modified_by"] == "admin-1"


def test_global_names_are_unique_ignoring_case(engine):
    engine.agents.seed({"id": "a-1", "name": "Research", "is_global": True})
    with pytest.raises(engine.authoring.WorkspaceAuthoringValidation, match="already exists"):
        engine.authoring.apply_global_agent_write("admin-1", None, agent_body(name="research"), passthrough, engine.settings)
    assert engine.agents.writes == []


def test_the_default_agent_cannot_be_deleted(engine):
    engine.agents.seed({"id": "a-1", "name": "default_agent", "is_global": True})
    engine.agents.seed({"id": "a-2", "name": "other", "is_global": True})

    default = engine.authoring.read_global_editor_record("agents", "a-1")
    with pytest.raises(engine.authoring.WorkspaceAuthoringValidation, match="default agent"):
        engine.authoring.delete_global_editor_record("agents", "admin-1", default, engine.settings)

    other = engine.authoring.read_global_editor_record("agents", "a-2")
    engine.authoring.delete_global_editor_record("agents", "admin-1", other, engine.settings)
    assert engine.agents.writes == [("delete", "a-2")]
    assert ("global", "global_agent_deleted") in engine.calls.cache


def test_a_record_claiming_a_group_is_not_served_as_global(engine):
    engine.agents.seed({"id": "a-1", "name": "stray", "group_id": "g-1", "is_group": True})
    with pytest.raises(LookupError):
        engine.authoring.read_global_editor_record("agents", "a-1")
    assert engine.authoring.list_global_editor_records("agents") == []


def test_creating_a_global_action_stores_the_global_scope(engine):
    body = {"updates": {"name": "weather", "displayName": "Weather", "type": "openapi",
                        "endpoint": "https://example.test", "auth": {"type": "NoAuth"},
                        "additionalFields": {}, "metadata": {}}}

    saved = engine.authoring.apply_global_action_write("admin-1", None, body, passthrough, engine.settings)

    stored = engine.actions.items[saved["id"]]
    uuid.UUID(saved["id"])  # The server allocates the id.
    assert stored["scope"] == "global" and stored["scope_id"] == "global"
    assert stored["is_global"] is True and stored["is_group"] is False
    assert engine.calls.identities == [("global", "global")]
    assert engine.calls.delegation[-1][1]["scope_type"] == "global"
    assert ("global", "global_action_saved") in engine.calls.cache


def test_a_refused_prepare_maps_to_stable_errors(engine):
    def forbidden(user_id, record, settings, existing):
        return None, ("ignored", 403)

    def invalid(user_id, record, settings, existing):
        return None, ("ignored", 400)

    with pytest.raises(PermissionError):
        engine.authoring.apply_global_agent_write("admin-1", None, agent_body(), forbidden, engine.settings)
    with pytest.raises(engine.authoring.WorkspaceAuthoringValidation):
        engine.authoring.apply_global_agent_write("admin-1", None, agent_body(name="other"), invalid, engine.settings)
    assert engine.agents.writes == []


def test_global_agents_may_be_any_type_and_carry_their_own_connection(engine):
    validate = engine.authoring._validate_agent_editor_changes
    for agent_type in ("local", "aifoundry", "new_foundry", "foundry_workflow"):
        validate({"agent_type": agent_type}, None, {}, "admin-1", scope="global")
    # A custom model connection needs no workspace permission on a global agent.
    validate({"agent_type": "local", "azure_openai_gpt_endpoint": "https://x.test"}, None, {}, "admin-1", scope="global")
    # Personal agents still need the permission.
    with pytest.raises(PermissionError):
        validate({"agent_type": "local", "azure_openai_gpt_endpoint": "https://x.test"}, None, {}, "user-1")


def test_global_agent_options_offer_global_connections_with_secrets_masked(engine):
    endpoints = [
        {"id": "e-1", "scope": "global", "models": [{"id": "m-1"}], "auth": {"api_key": "plain-secret"}},
        {"id": "e-2", "scope": "user", "models": [{"id": "m-2"}]},
    ]
    options = engine.authoring.build_global_agent_editor_options(engine.settings, endpoints)

    assert [item["value"] for item in options["agent_types"]] == ["local", "aifoundry", "new_foundry", "foundry_workflow"]
    assert all(item["enabled"] for item in options["agent_types"])
    assert [endpoint["id"] for endpoint in options["model_endpoints"]] == ["e-1"]
    assert options["model_endpoints"][0]["auth"]["api_key"] == engine.authoring.EDITOR_SECRET_MASK
    assert options["settings"]["agent_template_submission_allowed"] is True
    assert options["settings"]["enable_multi_model_endpoints"] is True
    assert [action["id"] for action in options["builtin_actions"]] == ["time"]


def test_editor_resources_are_editable_for_the_administrator(engine):
    resource = engine.access._resource({"id": "a-1", "name": "x", "_etag": "etag-1"}, "agents")
    assert resource["read_only"] is False and resource["revision"] == "etag-1"
    assert resource["record"]["is_global"] is True


def test_renaming_the_default_agent_keeps_it_selected(engine):
    engine.access._follow_default_agent_rename(
        {"name": "default_agent"}, {"id": "a-1", "name": "renamed_agent"}, engine.settings,
    )
    assert engine.calls.settings_updates == [{
        "global_selected_agent": {"name": "renamed_agent", "is_global": True, "is_group": False},
    }]

    engine.calls.settings_updates.clear()
    engine.access._follow_default_agent_rename({"name": "other"}, {"id": "a-2", "name": "other_renamed"}, engine.settings)
    assert engine.calls.settings_updates == [], "Renaming another agent leaves the default alone."


def test_the_agent_list_names_the_default(engine):
    engine.agents.seed({"id": "a-1", "name": "default_agent", "is_global": True})
    payload, status = engine.access.list_global_agents()
    assert status == 200
    assert payload["selected_agent_name"] == "default_agent"
    assert [agent["id"] for agent in payload["agents"]] == ["a-1"]
    assert all("_etag" not in agent for agent in payload["agents"])


def test_routes_register_every_editor_endpoint_and_guard_their_inputs(engine, monkeypatch):
    """Build the real URL map and drive two views in a request context.

    The Admin role is enforced by the decorators, which the route policy inventory
    pins; here they are pass-throughs so the routes themselves can be exercised.
    """
    flask = pytest.importorskip("flask")

    def passthrough_decorator(function):
        return function

    monkeypatch.setitem(sys.modules, "functions_authentication", _module(
        "functions_authentication", admin_required=passthrough_decorator,
        login_required=passthrough_decorator, get_current_user_id=lambda: "admin-1",
    ))
    monkeypatch.setitem(sys.modules, "swagger_wrapper", _module(
        "swagger_wrapper", swagger_route=lambda **kwargs: passthrough_decorator, get_auth_security=lambda: [],
    ))
    monkeypatch.setitem(sys.modules, "route_backend_agents", _module(
        "route_backend_agents", _prepare_global_agent_payload=passthrough,
    ))
    monkeypatch.setitem(sys.modules, "route_backend_plugins", _module(
        "route_backend_plugins", _prepare_global_action_payload=passthrough, get_plugin_types=lambda: None,
    ))
    name = "route_backend_v2_admin_agents_actions"
    monkeypatch.delitem(sys.modules, name, raising=False)
    spec = importlib.util.spec_from_file_location(name, APP_ROOT / f"{name}.py")
    routes = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, routes)
    spec.loader.exec_module(routes)

    app = flask.Flask(__name__)
    blueprint = flask.Blueprint("global_editor", __name__)
    routes.register_route_backend_v2_admin_agents_actions(blueprint)
    app.register_blueprint(blueprint)

    registered = {
        (rule.rule, method)
        for rule in app.url_map.iter_rules() if rule.endpoint.startswith("global_editor.")
        for method in rule.methods - {"HEAD", "OPTIONS"}
    }
    assert registered == {
        ("/api/v2/admin/agents", "GET"), ("/api/v2/admin/agents", "POST"),
        ("/api/v2/admin/agent-options", "GET"),
        ("/api/v2/admin/agents/<agent_id>", "GET"), ("/api/v2/admin/agents/<agent_id>", "PATCH"),
        ("/api/v2/admin/agents/<agent_id>", "DELETE"),
        ("/api/v2/admin/actions", "GET"), ("/api/v2/admin/actions", "POST"),
        ("/api/v2/admin/actions/types", "GET"), ("/api/v2/admin/action-options", "GET"),
        ("/api/v2/admin/actions/<action_id>", "GET"), ("/api/v2/admin/actions/<action_id>", "PATCH"),
        ("/api/v2/admin/actions/<action_id>", "DELETE"),
    }

    engine.agents.seed({"id": "a-1", "name": "default_agent", "is_global": True})
    views = app.view_functions
    with app.test_request_context("/api/v2/admin/agents", method="GET"):
        response, status = views["global_editor.v2_admin_global_agents_list"]()
        assert status == 200
        assert response.headers["Cache-Control"] == "no-store"
        assert response.get_json()["selected_agent_name"] == "default_agent"
    with app.test_request_context("/api/v2/admin/agents?expected_revision=x", method="GET"):
        response, status = views["global_editor.v2_admin_global_agents_list"]()
        assert status == 400, "A stray query parameter is refused, not ignored."
    with app.test_request_context("/api/v2/admin/agents/a-1", method="DELETE"):
        response, status = views["global_editor.v2_admin_global_agent_delete"]("a-1")
        assert status == 400, "The default agent cannot be deleted."
        assert "default agent" in response.get_json()["error"]
    assert "a-1" in engine.agents.items


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
