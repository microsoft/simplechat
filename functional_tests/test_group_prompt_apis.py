# test_group_prompt_apis.py
"""
Functional tests for the immutable-target group prompt APIs.
Version: 0.261.136
Implemented in: 0.261.136

The real policy, access, projection and route modules run against the real
prompt data-layer functions, executed unchanged over an in-memory Cosmos stub
that honours ETag conditional writes. Group membership, status and settings are
local test seams; the group is always taken from the path, so a stale active
group can never redirect or widen a request. Network access is prohibited.
"""

import json
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
from test_support.versioning import assert_app_version_at_least


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


# --------------------------------------------------------------------------
# Versioning
# --------------------------------------------------------------------------

def test_version_at_least_implementation():
    assert_app_version_at_least("0.261.136")


# --------------------------------------------------------------------------
# Reads: role and status
# --------------------------------------------------------------------------

@pytest.mark.parametrize("role", READER_ROLES)
def test_every_member_role_can_list_and_read(environment, role):
    seed_prompt(environment.group_container, "p1")
    as_user(environment, ROLE_USER[role])
    listing = environment.client.get(LIST_PATH)
    assert listing.status_code == 200
    body = listing.get_json()
    assert [item["id"] for item in body["prompts"]] == ["p1"]
    single = environment.client.get(f"{LIST_PATH}/p1")
    assert single.status_code == 200
    assert single.get_json()["id"] == "p1"


def test_list_envelope_and_single_top_level_shape(environment):
    seed_prompt(environment.group_container, "p1")
    as_user(environment, "owner")
    body = environment.client.get(LIST_PATH).get_json()
    assert set(body) == {"prompts", "page", "page_size", "total_count"}
    item = body["prompts"][0]
    assert item["id"] == "p1" and item["group_id"] == "group-a"
    single = environment.client.get(f"{LIST_PATH}/p1").get_json()
    assert single["id"] == "p1"
    assert "prompts" not in single


def test_list_supports_pagination_and_search(environment):
    for index in range(5):
        seed_prompt(environment.group_container, f"p{index}", name=f"Prompt {index}")
    seed_prompt(environment.group_container, "needle", name="Findable marker")
    as_user(environment, "owner")

    first = environment.client.get(f"{LIST_PATH}?page=1&page_size=2").get_json()
    assert first["page"] == 1 and first["page_size"] == 2
    assert first["total_count"] == 6
    assert len(first["prompts"]) == 2

    found = environment.client.get(f"{LIST_PATH}?search=Findable").get_json()
    assert [item["id"] for item in found["prompts"]] == ["needle"]


def test_reads_omit_private_fields_and_expose_etag(environment):
    seed_prompt(environment.group_container, "p1")
    as_user(environment, "owner")
    item = environment.client.get(f"{LIST_PATH}/p1").get_json()
    assert "is_favorite" not in item
    assert "user_id" not in item
    assert "_etag" not in item
    assert item["etag"] == environment.group_container.records["p1"]["_etag"]


@pytest.mark.parametrize("status", ["locked", "upload_disabled"])
def test_reads_allowed_on_readable_non_active_status(environment, status):
    container = environment.group_container
    seed_prompt(container, "p1", group_id=f"{status}-grp" if status != "upload_disabled" else "upload-disabled-grp")
    grp = "locked-grp" if status == "locked" else "upload-disabled-grp"
    seed_prompt(container, "px", group_id=grp)
    as_user(environment, "owner")
    response = environment.client.get(f"/api/groups/{grp}/prompts")
    assert response.status_code == 200


@pytest.mark.parametrize("grp", ["inactive-grp", "haunted-grp"])
def test_reads_denied_on_inactive_or_unknown_status(environment, grp):
    as_user(environment, "owner")
    assert environment.client.get(f"/api/groups/{grp}/prompts").status_code == 403
    assert environment.client.get(f"/api/groups/{grp}/prompts/anything").status_code == 403


def test_unknown_group_is_404_and_non_member_is_403(environment):
    seed_prompt(environment.group_container, "p1")
    as_user(environment, "owner")
    assert environment.client.get("/api/groups/no-such-group/prompts").status_code == 404
    as_user(environment, "stranger")
    assert environment.client.get(LIST_PATH).status_code == 403


def test_cross_group_prompt_is_not_readable(environment):
    seed_prompt(environment.group_container, "owned-by-b", group_id="group-b")
    as_user(environment, "owner")
    # The prompt exists, but not in group-a's path.
    assert environment.client.get(f"{LIST_PATH}/owned-by-b").status_code == 404


def test_list_is_scoped_to_the_path_group(environment):
    seed_prompt(environment.group_container, "a1", group_id="group-a")
    seed_prompt(environment.group_container, "b1", group_id="group-b")
    as_user(environment, "owner")
    ids = [item["id"] for item in environment.client.get(LIST_PATH).get_json()["prompts"]]
    assert ids == ["a1"]


# --------------------------------------------------------------------------
# Writes: role policy
# --------------------------------------------------------------------------

@pytest.mark.parametrize("role", MANAGER_ROLES)
def test_managers_can_create_update_delete(environment, role):
    as_user(environment, ROLE_USER[role])
    created = environment.client.post(LIST_PATH, json={"name": "New", "content": "Body"})
    assert created.status_code == 201, created.get_json()
    prompt = created.get_json()
    assert "is_favorite" not in prompt
    assert prompt["prompt_actions"] == ["edit", "delete"]
    prompt_id = prompt["id"]

    updated = environment.client.patch(
        f"{LIST_PATH}/{prompt_id}",
        json={"name": "Renamed", "expected_etag": prompt["etag"]},
    )
    assert updated.status_code == 200
    assert updated.get_json()["name"] == "Renamed"

    deleted = environment.client.delete(
        f"{LIST_PATH}/{prompt_id}",
        json={"expected_etag": updated.get_json()["etag"]},
    )
    assert deleted.status_code == 200
    assert prompt_id not in environment.group_container.records


def test_user_is_refused_all_three_writes(environment):
    seed_prompt(environment.group_container, "p1")
    etag = environment.group_container.records["p1"]["_etag"]
    as_user(environment, "member")
    assert environment.client.post(LIST_PATH, json={"name": "x", "content": "y"}).status_code == 403
    assert environment.client.patch(
        f"{LIST_PATH}/p1", json={"name": "z", "expected_etag": etag}
    ).status_code == 403
    assert environment.client.delete(
        f"{LIST_PATH}/p1", json={"expected_etag": etag}
    ).status_code == 403
    # No write reached storage.
    assert environment.group_container.records["p1"]["name"] == "Prompt p1"


@pytest.mark.parametrize("grp", ["locked-grp", "upload-disabled-grp"])
def test_writes_denied_when_not_active(environment, grp):
    seed_prompt(environment.group_container, "p1", group_id=grp)
    etag = environment.group_container.records["p1"]["_etag"]
    as_user(environment, "owner")
    assert environment.client.post(
        f"/api/groups/{grp}/prompts", json={"name": "x", "content": "y"}
    ).status_code == 403
    assert environment.client.patch(
        f"/api/groups/{grp}/prompts/p1", json={"name": "z", "expected_etag": etag}
    ).status_code == 403
    assert environment.client.delete(
        f"/api/groups/{grp}/prompts/p1", json={"expected_etag": etag}
    ).status_code == 403


def test_reader_prompt_actions_are_empty(environment):
    seed_prompt(environment.group_container, "p1")
    as_user(environment, "member")
    item = environment.client.get(f"{LIST_PATH}/p1").get_json()
    assert item["prompt_actions"] == []


# --------------------------------------------------------------------------
# Conditional writes
# --------------------------------------------------------------------------

def test_patch_missing_expected_etag_is_400(environment):
    seed_prompt(environment.group_container, "p1")
    as_user(environment, "owner")
    response = environment.client.patch(f"{LIST_PATH}/p1", json={"name": "z"})
    assert response.status_code == 400


def test_patch_stale_etag_is_409_with_no_partial_write(environment):
    seed_prompt(environment.group_container, "p1")
    as_user(environment, "owner")
    response = environment.client.patch(
        f"{LIST_PATH}/p1", json={"name": "z", "content": "new", "expected_etag": '"stale"'},
    )
    assert response.status_code == 409
    assert response.get_json()["error_code"] == "prompt_changed"
    stored = environment.group_container.records["p1"]
    assert stored["name"] == "Prompt p1" and stored["content"] == "Body of p1"


def test_delete_missing_expected_etag_is_400(environment):
    seed_prompt(environment.group_container, "p1")
    as_user(environment, "owner")
    assert environment.client.delete(f"{LIST_PATH}/p1", json={}).status_code == 400
    assert "p1" in environment.group_container.records


def test_delete_expected_etag_as_query_parameter_is_rejected(environment):
    seed_prompt(environment.group_container, "p1")
    etag = environment.group_container.records["p1"]["_etag"]
    as_user(environment, "owner")
    # Sending expected_etag as a query parameter must be a 400, never honoured.
    response = environment.client.delete(f"{LIST_PATH}/p1?expected_etag={etag}", json={"expected_etag": etag})
    assert response.status_code == 400
    assert "p1" in environment.group_container.records


def test_delete_stale_etag_is_409_and_prompt_survives(environment):
    seed_prompt(environment.group_container, "p1")
    as_user(environment, "owner")
    response = environment.client.delete(f"{LIST_PATH}/p1", json={"expected_etag": '"stale"'})
    assert response.status_code == 409
    assert response.get_json()["error_code"] == "prompt_changed"
    assert "p1" in environment.group_container.records


def test_update_and_delete_of_missing_prompt_is_404(environment):
    as_user(environment, "owner")
    assert environment.client.patch(
        f"{LIST_PATH}/ghost", json={"name": "z", "expected_etag": '"x"'}
    ).status_code == 404
    assert environment.client.delete(
        f"{LIST_PATH}/ghost", json={"expected_etag": '"x"'}
    ).status_code == 404


# --------------------------------------------------------------------------
# Body and query validation
# --------------------------------------------------------------------------

def test_is_favorite_is_rejected_on_create_and_update(environment):
    seed_prompt(environment.group_container, "p1")
    etag = environment.group_container.records["p1"]["_etag"]
    as_user(environment, "owner")
    created = environment.client.post(
        LIST_PATH, json={"name": "n", "content": "c", "is_favorite": True},
    )
    assert created.status_code == 400
    updated = environment.client.patch(
        f"{LIST_PATH}/p1", json={"is_favorite": False, "expected_etag": etag},
    )
    assert updated.status_code == 400


def test_unknown_fields_are_rejected(environment):
    seed_prompt(environment.group_container, "p1")
    etag = environment.group_container.records["p1"]["_etag"]
    as_user(environment, "owner")
    assert environment.client.post(
        LIST_PATH, json={"name": "n", "content": "c", "colour": "red"}
    ).status_code == 400
    assert environment.client.patch(
        f"{LIST_PATH}/p1", json={"name": "n", "colour": "red", "expected_etag": etag}
    ).status_code == 400


def test_missing_required_create_fields_is_400(environment):
    as_user(environment, "owner")
    assert environment.client.post(LIST_PATH, json={"name": "  "}).status_code == 400
    assert environment.client.post(LIST_PATH, json={"content": "c"}).status_code == 400


def test_duplicate_json_keys_are_rejected(environment):
    as_user(environment, "owner")
    response = environment.client.post(
        LIST_PATH, data='{"name": "a", "name": "b", "content": "c"}',
        content_type="application/json",
    )
    assert response.status_code == 400


def test_list_rejects_unknown_and_duplicate_query_parameters(environment):
    as_user(environment, "owner")
    assert environment.client.get(f"{LIST_PATH}?colour=red").status_code == 400
    assert environment.client.get(f"{LIST_PATH}?page=1&page=2").status_code == 400


def test_non_list_routes_reject_query_parameters(environment):
    seed_prompt(environment.group_container, "p1")
    as_user(environment, "owner")
    assert environment.client.get(f"{LIST_PATH}/p1?x=1").status_code == 400
    assert environment.client.post(f"{LIST_PATH}?x=1", json={"name": "n", "content": "c"}).status_code == 400


def test_reads_reject_a_request_body(environment):
    seed_prompt(environment.group_container, "p1")
    as_user(environment, "owner")
    response = environment.client.get(
        f"{LIST_PATH}/p1", data='{"unexpected": true}', content_type="application/json",
    )
    assert response.status_code == 400


def test_feature_disabled_returns_400(environment):
    environment.settings["enable_group_workspaces"] = False
    as_user(environment, "owner")
    assert environment.client.get(LIST_PATH).status_code == 400


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
