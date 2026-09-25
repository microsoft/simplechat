# public_prompt_harness.py
"""
Extracted backend harness for the immutable-target public prompt API suite (M9C).
Version: 0.261.178
Implemented in: 0.261.178

Mirrors ``group_prompt_harness.py``: it drives the real public prompt policy,
access, projection and route modules over an ETag-enforcing Cosmos stub, so the
API suite and the per-route fixture-shape parity pin share one backend. The only
scope differences are that the workspace document lives in its own container
(read by ``find_public_workspace_by_id``), role is resolved from that document by
the real ``get_user_role_in_public_workspace`` (so any authenticated caller reads
as at least a ``User``), and the prompt records carry ``public_id``.
"""

import re
import socket
import sys
from copy import deepcopy
from functools import wraps
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask import Blueprint, Flask, jsonify, request, session

from test_support.agent_delegation import (
    APP_ROOT,
    CosmosHttpResponseError,
    CosmosResourceNotFoundError,
    MatchConditions,
    execute_functions,
    module_stub,
)


LIST_PATH = "/api/public-workspaces/public-a/prompts"


class PromptConflictError(Exception):
    """Test-local mirror of the data layer's conditional-write conflict."""


class PromptContainer:
    """An in-memory Cosmos stub that enforces ETag conditional writes."""

    def __init__(self):
        self.records = {}
        self._sequence = 0

    def _next_etag(self):
        self._sequence += 1
        return f'"etag-{self._sequence}"'

    def create_item(self, body):
        doc = deepcopy(body)
        doc["_etag"] = self._next_etag()
        self.records[doc["id"]] = doc
        return deepcopy(doc)

    def read_item(self, item, partition_key):
        if item not in self.records:
            raise CosmosResourceNotFoundError()
        return deepcopy(self.records[item])

    def replace_item(self, item, body, etag=None, match_condition=None):
        stored = self.records.get(item)
        if stored is None:
            raise CosmosResourceNotFoundError()
        if etag is not None and stored.get("_etag") != etag:
            raise CosmosHttpResponseError(412)
        doc = deepcopy(body)
        doc["_etag"] = self._next_etag()
        self.records[item] = doc
        return deepcopy(doc)

    def delete_item(self, item, partition_key, etag=None, match_condition=None):
        stored = self.records.get(item)
        if stored is None:
            raise CosmosResourceNotFoundError()
        if etag is not None and stored.get("_etag") != etag:
            raise CosmosHttpResponseError(412)
        del self.records[item]

    def query_items(self, query, parameters=None, **kwargs):
        values = {parameter["name"]: parameter["value"] for parameter in (parameters or [])}
        rows = [deepcopy(record) for record in self.records.values()]
        for field, param in re.findall(r"c\.(\w+)\s*=\s*(@\w+)", query):
            if param in values:
                rows = [record for record in rows if record.get(field) == values[param]]
        if "@search" in values and "CONTAINS" in query:
            term = str(values["@search"]).lower()
            rows = [
                record for record in rows
                if term in str(record.get("name") or "").lower()
                or term in str(record.get("description") or "").lower()
            ]
        if "COUNT(1)" in query:
            return [len(rows)]
        if "ORDER BY c.updated_at DESC" in query:
            rows.sort(key=lambda record: record.get("updated_at") or "", reverse=True)
        match = re.search(r"OFFSET\s+(\d+)\s+LIMIT\s+(\d+)", query)
        if match:
            offset, limit = int(match.group(1)), int(match.group(2))
            rows = rows[offset:offset + limit]
        return rows


class WorkspaceContainer:
    """A minimal public workspaces container: point reads only, by workspace id."""

    def __init__(self, workspaces):
        self.records = workspaces

    def read_item(self, item, partition_key):
        if item not in self.records:
            raise CosmosResourceNotFoundError()
        return deepcopy(self.records[item])


def workspace(workspace_id, status="active"):
    """A public workspace document with the three managing roles seeded."""
    return {
        "id": workspace_id,
        "name": f"Public {workspace_id}",
        "status": status,
        "owner": {"userId": "owner"},
        "admins": ["admin"],
        "documentManagers": [{"userId": "manager"}],
    }


def seed_prompt(container, prompt_id, workspace_id="public-a", **changes):
    doc = {
        "id": prompt_id,
        "name": f"Prompt {prompt_id}",
        "content": f"Body of {prompt_id}",
        "description": "A shared prompt.",
        "is_favorite": True,
        "type": "public_prompt",
        "public_id": workspace_id,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": f"2026-01-01T00:00:0{len(container.records)}Z",
    }
    doc.update(changes)
    return container.create_item(doc)


@pytest.fixture
def environment(monkeypatch):
    settings = {"enable_public_workspaces": True}
    with monkeypatch.context() as scoped:
        scoped.syspath_prepend(str(APP_ROOT))
        network = Mock(side_effect=AssertionError("No network access in public prompt tests."))
        scoped.setattr(socket, "create_connection", network)
        scoped.setattr(socket.socket, "connect", network)

        workspaces = {
            "public-a": workspace("public-a"),
            "public-b": workspace("public-b"),
            "locked-ws": workspace("locked-ws", status="locked"),
            "upload-disabled-ws": workspace("upload-disabled-ws", status="upload_disabled"),
            "inactive-ws": workspace("inactive-ws", status="inactive"),
            "haunted-ws": workspace("haunted-ws", status="haunted"),
        }

        workspace_container = WorkspaceContainer(workspaces)
        public_container = PromptContainer()
        env = SimpleNamespace(
            settings=settings, workspaces=workspaces, public_container=public_container,
            workspace_container=workspace_container, actor="owner",
        )

        # --- settings seam -------------------------------------------------
        settings_namespace = {"wraps": wraps, "get_settings": lambda: settings, "jsonify": jsonify}
        execute_functions("functions_settings.py", {"enabled_required"}, settings_namespace)
        settings_module = module_stub(
            "functions_settings",
            get_settings=lambda: settings,
            enabled_required=settings_namespace["enabled_required"],
        )
        scoped.setitem(sys.modules, "functions_settings", settings_module)

        # --- chat bootstrap cache seam ------------------------------------
        scoped.setitem(sys.modules, "functions_chat_bootstrap_cache", module_stub(
            "functions_chat_bootstrap_cache",
            bump_chat_bootstrap_global_cache_version=Mock(),
            bump_chat_bootstrap_user_cache_version=Mock(),
        ))

        # --- public workspace membership seam (real role/lookup logic) ----
        public_ws_namespace = {
            "cosmos_public_workspaces_container": workspace_container,
            "exceptions": SimpleNamespace(CosmosResourceNotFoundError=CosmosResourceNotFoundError),
        }
        execute_functions("functions_public_workspaces.py", {
            "find_public_workspace_by_id", "get_user_role_in_public_workspace",
        }, public_ws_namespace)
        scoped.setitem(sys.modules, "functions_public_workspaces", module_stub(
            "functions_public_workspaces",
            find_public_workspace_by_id=public_ws_namespace["find_public_workspace_by_id"],
            get_user_role_in_public_workspace=public_ws_namespace["get_user_role_in_public_workspace"],
        ))

        # --- prompt data layer (real functions over the stub) -------------
        prompts_namespace = {
            "MatchConditions": MatchConditions,
            "CosmosHttpResponseError": CosmosHttpResponseError,
            "CosmosResourceNotFoundError": CosmosResourceNotFoundError,
            "PromptConflictError": PromptConflictError,
            "PROMPT_DESCRIPTION_MAX_LENGTH": 200,
            "cosmos_user_prompts_container": PromptContainer(),
            "cosmos_group_prompts_container": PromptContainer(),
            "cosmos_public_prompts_container": public_container,
            "bump_chat_bootstrap_global_cache_version": Mock(),
            "bump_chat_bootstrap_user_cache_version": Mock(),
        }
        import datetime as _datetime_module
        import uuid as _uuid_module
        prompts_namespace["datetime"] = _datetime_module.datetime
        prompts_namespace["timezone"] = _datetime_module.timezone
        prompts_namespace["uuid"] = _uuid_module
        execute_functions("functions_prompts.py", {
            "normalize_prompt_description", "serialize_prompt_summary", "get_pagination_params",
            "_query_prompt_items", "_filter_prompt_items", "_sort_prompt_items",
            "_read_prompt_from_container", "_get_public_prompt_items", "_get_prompt_doc_with_container",
            "_invalidate_prompt_chat_bootstrap_cache", "list_prompts", "get_prompt_doc",
            "create_prompt_doc", "update_prompt_doc", "delete_prompt_doc",
        }, prompts_namespace)
        prompts_module = module_stub("functions_prompts", **{
            name: prompts_namespace[name] for name in (
                "normalize_prompt_description", "list_prompts", "get_prompt_doc",
                "create_prompt_doc", "update_prompt_doc", "delete_prompt_doc",
            )
        })
        prompts_module.PromptConflictError = PromptConflictError
        scoped.setitem(sys.modules, "functions_prompts", prompts_module)

        # --- authentication seam ------------------------------------------
        auth_namespace = {
            "wraps": wraps, "session": session, "request": request, "jsonify": jsonify,
            "debug_print": Mock(), "check_user_access_status": Mock(return_value=(True, None)),
        }
        execute_functions("functions_authentication.py", {
            "login_required", "user_required", "get_current_user_id",
            "apply_blueprint_auth", "user_required_blueprint",
        }, auth_namespace)
        auth = module_stub("functions_authentication", **auth_namespace)
        scoped.setitem(sys.modules, "functions_authentication", auth)

        scoped.setitem(sys.modules, "swagger_wrapper", module_stub(
            "swagger_wrapper",
            swagger_route=lambda **_kwargs: (lambda function: function),
            get_auth_security=lambda: [{"sessionAuth": []}],
        ))

        def load_real(name):
            import importlib.util
            spec = importlib.util.spec_from_file_location(name, APP_ROOT / f"{name}.py")
            module = importlib.util.module_from_spec(spec)
            scoped.setitem(sys.modules, name, module)
            spec.loader.exec_module(module)
            return module

        load_real("functions_public_prompt_policy")
        env.access = load_real("functions_public_prompt_access")
        route = load_real("route_backend_public_prompts_scoped")

        app = Flask("public_prompt_contract")
        app.config.update(TESTING=True, SECRET_KEY="test-only-session-key")
        blueprint = Blueprint("backend_public_prompts_scoped", __name__)
        blueprint.before_request(auth.user_required_blueprint())
        route.register_route_backend_public_prompts_scoped(blueprint)
        app.register_blueprint(blueprint)

        env.app = app
        env.client = app.test_client()
        env.route = route
        as_user(env, "owner")
        yield env
        network.assert_not_called()


def as_user(env, user_id, roles=("User",)):
    env.actor = user_id
    with env.client.session_transaction() as state:
        state["user"] = {"oid": user_id, "roles": list(roles)}


# Role -> the seeded user id that holds it in every workspace fixture.
ROLE_USER = {"Owner": "owner", "Admin": "admin", "DocumentManager": "manager", "User": "stranger"}
READER_ROLES = ("Owner", "Admin", "DocumentManager", "User")
MANAGER_ROLES = ("Owner", "Admin", "DocumentManager")
