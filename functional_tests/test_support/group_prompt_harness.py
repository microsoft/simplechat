# group_prompt_harness.py
"""
Extracted backend harness for the immutable-target group prompt API suite.
Version: 0.261.161
Implemented in: 0.261.136

Moved verbatim out of ``test_group_prompt_apis.py`` so a second test -- the
per-route fixture-shape parity pin ``test_group_prompt_fixture_parity.py`` --
can drive the same real policy, access, projection and route modules over the
same ETag-enforcing Cosmos stub. The extraction is byte-for-byte: the API suite
imports every name from here and its assertions are unchanged.
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
from typing import Iterable

from test_support.agent_delegation import (
    APP_ROOT,
    CosmosHttpResponseError,
    CosmosResourceNotFoundError,
    MatchConditions,
    execute_functions,
    module_stub,
)


LIST_PATH = "/api/groups/group-a/prompts"


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


def group(group_id, status="active"):
    return {
        "id": group_id,
        "name": f"Group {group_id}",
        "status": status,
        "owner": {"id": "owner"},
        "admins": ["admin"],
        "documentManagers": ["manager"],
        "users": [{"userId": "member"}],
    }


def seed_prompt(container, prompt_id, group_id="group-a", **changes):
    doc = {
        "id": prompt_id,
        "name": f"Prompt {prompt_id}",
        "content": f"Body of {prompt_id}",
        "description": "A shared prompt.",
        "is_favorite": True,
        "type": "group_prompt",
        "group_id": group_id,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": f"2026-01-01T00:00:0{len(container.records)}Z",
    }
    doc.update(changes)
    return container.create_item(doc)


@pytest.fixture
def environment(monkeypatch):
    settings = {"enable_group_workspaces": True}
    with monkeypatch.context() as scoped:
        scoped.syspath_prepend(str(APP_ROOT))
        network = Mock(side_effect=AssertionError("No network access in group prompt tests."))
        scoped.setattr(socket, "create_connection", network)
        scoped.setattr(socket.socket, "connect", network)

        groups = {
            "group-a": group("group-a"),
            "group-b": group("group-b"),
            "locked-grp": group("locked-grp", status="locked"),
            "upload-disabled-grp": group("upload-disabled-grp", status="upload_disabled"),
            "inactive-grp": group("inactive-grp", status="inactive"),
            "haunted-grp": group("haunted-grp", status="haunted"),
        }

        group_container = PromptContainer()
        env = SimpleNamespace(
            settings=settings, groups=groups, group_container=group_container, actor="owner",
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

        # --- group membership seam (real role/status logic) ---------------
        group_namespace = {
            "Iterable": Iterable,
            "find_group_by_id": lambda group_id: deepcopy(groups.get(group_id)),
        }
        execute_functions("functions_group.py", {
            "get_user_role_in_group", "assert_group_role", "check_group_status_allows_operation",
        }, group_namespace)
        scoped.setitem(sys.modules, "functions_group", module_stub(
            "functions_group",
            find_group_by_id=group_namespace["find_group_by_id"],
            get_user_role_in_group=group_namespace["get_user_role_in_group"],
            assert_group_role=group_namespace["assert_group_role"],
            check_group_status_allows_operation=group_namespace["check_group_status_allows_operation"],
        ))

        # --- prompt data layer (real functions over the stub) -------------
        prompts_namespace = {
            "MatchConditions": MatchConditions,
            "CosmosHttpResponseError": CosmosHttpResponseError,
            "CosmosResourceNotFoundError": CosmosResourceNotFoundError,
            "PromptConflictError": PromptConflictError,
            "PROMPT_DESCRIPTION_MAX_LENGTH": 200,
            "cosmos_user_prompts_container": PromptContainer(),
            "cosmos_group_prompts_container": group_container,
            "cosmos_public_prompts_container": PromptContainer(),
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

        load_real("functions_group_prompt_policy")
        env.access = load_real("functions_group_prompt_access")
        route = load_real("route_backend_group_prompts_scoped")

        app = Flask("group_prompt_contract")
        app.config.update(TESTING=True, SECRET_KEY="test-only-session-key")
        blueprint = Blueprint("backend_group_prompts_scoped", __name__)
        blueprint.before_request(auth.user_required_blueprint())
        route.register_route_backend_group_prompts_scoped(blueprint)
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


# Role -> the seeded user id that holds it in every group fixture.
ROLE_USER = {"Owner": "owner", "Admin": "admin", "DocumentManager": "manager", "User": "member"}
READER_ROLES = ("Owner", "Admin", "DocumentManager", "User")
MANAGER_ROLES = ("Owner", "Admin", "DocumentManager")
