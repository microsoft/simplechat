# test_group_workflow_file_sync_enabled_seam.py
#!/usr/bin/env python3
"""
Functional test for the File Sync gate shared by the group workflow sources route and the save.
Version: 0.261.148
Implemented in: 0.261.148

This test ensures that ``file_sync_enabled`` from ``GET /api/group/workflows/file-sync-sources``
is exactly the gate ``POST /api/group/workflows`` applies before a workflow can use File Sync
("Group File Sync must be enabled before a group workflow can use File Sync sources."). The V2
editor trusts the flag to decide whether a selected source is missing or merely unlisted, so the
two must never disagree.

Both route bodies are compiled from ``route_backend_workflows.py``. The save route calls the real
``save_group_workflow`` from the real-module harness of
``test_group_workflow_round_trip_preservation.py``. Both call the real
``is_file_sync_enabled_for_group``, compiled with everything it needs from
``functions_file_sync.py`` and ``functions_settings.py``, over the same settings and the same
caller. The matrix covers File Sync on and off, Redis readiness, the admin-only restriction,
group assignment, and the caller's app role.
"""

import ast
import copy
import importlib.util
import itertools
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import pytest
from flask import Flask, jsonify, request

sys.path.append(str(Path(__file__).resolve().parent))

from test_group_workflow_round_trip_preservation import (  # noqa: E402  (shared real-module harness)
    GROUP_ID,
    OWNER_ID,
    SOURCE_ID,
    GroupWorkflowStore,
)


APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
ROUTES_FILE = APP_ROOT / "route_backend_workflows.py"
FILE_SYNC_FILE = APP_ROOT / "functions_file_sync.py"
SETTINGS_FILE = APP_ROOT / "functions_settings.py"
F4_MESSAGE = "Group File Sync must be enabled before a group workflow can use File Sync sources."
SOURCES_PATH = f"/api/group/workflows/file-sync-sources?group_id={GROUP_ID}"
ROUTE_FUNCTIONS = (
    "_normalize_identifier",
    "_assert_group_workflow_feature_enabled",
    "_resolve_active_group_for_workflows",
    "_serialize_workflow_file_sync_source",
    "_group_workflow_file_sync_enabled",
    "_collect_group_workflow_file_sync_sources",
    "get_group_workflow_file_sync_sources",
    "save_group_workflow_route",
    "_workflow_definition_response",
)
FILE_SYNC_NAMES = (
    "FILE_SYNC_ADMIN_VISIBLE_SOURCE_TYPES", "FILE_SYNC_DEFAULTS", "FILE_SYNC_KNOWN_SOURCE_TYPES",
    "FILE_SYNC_REMOTE_DELETE_POLICIES", "FILE_SYNC_SOURCE_TYPE_AZURE_BLOB", "FILE_SYNC_SOURCE_TYPE_AZURE_FILES",
    "FILE_SYNC_SOURCE_TYPE_GOOGLE_WORKSPACE", "FILE_SYNC_SOURCE_TYPE_ONEDRIVE",
    "FILE_SYNC_SOURCE_TYPE_SHAREPOINT_ON_PREM", "FILE_SYNC_SOURCE_TYPE_SMB", "FILE_SYNC_MANAGER_ROLES",
    "FILE_SYNC_SCOPE_PERSONAL", "FILE_SYNC_SCOPE_GROUP", "FILE_SYNC_SCOPE_PUBLIC",
    "_as_bool", "_is_redis_ready", "_normalize_source_type_list", "_safe_int", "_user_info_has_admin_role",
    "_user_info_has_app_role", "get_file_sync_config", "is_file_sync_enabled_for_group", "parse_file_sync_list",
)
REDIS_READY = {"enable_redis_cache": True, "redis_url": "redis://cache.test:6380", "redis_auth_type": "key",
               "redis_key": "test-key"}


def _compile(source_file, names, namespace, nested=False):
    """Compile named definitions and constants from a heavy module, without importing it."""
    tree = ast.parse(Path(source_file).read_text(encoding="utf-8"), filename=str(source_file))
    nodes, found = [], set()
    for node in (ast.walk(tree) if nested else tree.body):
        if isinstance(node, ast.FunctionDef) and node.name in names and node.name not in found:
            node.decorator_list = []
            nodes.append(node)
            found.add(node.name)
        elif not nested and isinstance(node, ast.Assign):
            targets = {target.id for target in node.targets if isinstance(target, ast.Name)} & set(names)
            if targets:
                nodes.append(node)
                found |= targets
    missing = set(names) - found
    assert not missing, f"Missing definitions in {Path(source_file).name}: {sorted(missing)}"
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source_file), "exec"), namespace)
    return namespace


def _real_predicate():
    spec = importlib.util.spec_from_file_location(
        "functions_group_assignment_ids", APP_ROOT / "functions_group_assignment_ids.py",
    )
    assignment_ids = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(assignment_ids)
    settings = _compile(SETTINGS_FILE, (
        "normalize_file_sync_allowed_group_ids", "normalize_file_sync_allowed_public_workspace_ids",
    ), {"json": json, "normalize_group_workflow_allowed_group_ids": assignment_ids.normalize_group_workflow_allowed_group_ids})
    namespace = {
        "Any": Any, "Dict": Dict, "Iterable": Iterable, "List": List, "Optional": Optional, "json": json, "re": re,
        "get_settings": lambda: pytest.fail("The gate must use the settings it is given."),
        "normalize_file_sync_allowed_group_ids": settings["normalize_file_sync_allowed_group_ids"],
        "normalize_file_sync_allowed_public_workspace_ids": settings["normalize_file_sync_allowed_public_workspace_ids"],
    }
    return _compile(FILE_SYNC_FILE, FILE_SYNC_NAMES, namespace)


class SeamRoutes:
    """The sources route and the save route over one store, one settings object and one caller."""

    def __init__(self):
        self.file_sync = _real_predicate()
        self.store = GroupWorkflowStore()
        self.store.module._utc_now_iso = lambda: "2026-09-21T12:00:00+00:00"
        self.caller = {"roles": ["User"]}
        self.gate_calls = []
        real_gate = self.file_sync["is_file_sync_enabled_for_group"]

        def gate(settings, group_id, user_info=None, **kwargs):
            self.gate_calls.append((json.dumps(settings, sort_keys=True), group_id, json.dumps(user_info, sort_keys=True)))
            return real_gate(settings, group_id, user_info=user_info, **kwargs)

        # One gate object, used by the save's File Sync check and by the sources route alike.
        self.store.module.is_file_sync_enabled_for_group = gate
        definitions = self.store.modules["functions_workflow_definitions"]

        def assert_group_role(user_id, group_id, allowed_roles=("Owner", "Admin")):
            role = self.store.roles.get((group_id, user_id))
            if not role or role.lower() not in {allowed.lower() for allowed in allowed_roles}:
                raise PermissionError("Insufficient permissions for this group")
            return role

        namespace = {
            "request": request, "jsonify": jsonify, "logging": logging,
            "log_event": lambda *args, **kwargs: None,
            "get_current_user_id": lambda: OWNER_ID,
            "get_settings": lambda: copy.deepcopy(self.store.settings),
            "is_group_workflows_enabled_for_group": lambda settings, group_id: True,
            "assert_group_role": assert_group_role,
            "require_active_group": lambda *args, **kwargs: pytest.fail("The explicit group must be used."),
            "GROUP_WORKFLOW_MEMBER_ROLES": ("Owner", "Admin", "DocumentManager", "User"),
            "FILE_SYNC_MANAGER_ROLES": self.file_sync["FILE_SYNC_MANAGER_ROLES"],
            "FILE_SYNC_SCOPE_PERSONAL": self.file_sync["FILE_SYNC_SCOPE_PERSONAL"],
            "FILE_SYNC_SCOPE_GROUP": self.file_sync["FILE_SYNC_SCOPE_GROUP"],
            "FILE_SYNC_SCOPE_PUBLIC": self.file_sync["FILE_SYNC_SCOPE_PUBLIC"],
            "is_file_sync_enabled_for_group": gate,
            "list_file_sync_sources": lambda scope_type, scope_id: [
                copy.deepcopy(source) for (group_id, _), source in self.store.sources.items() if group_id == scope_id
            ],
            "sanitize_file_sync_source": lambda source: {key: value for key, value in source.items() if key != "auth"},
            "_get_current_user_info_with_roles": lambda: copy.deepcopy(self.caller),
            "WorkflowDefinitionConflict": definitions.WorkflowDefinitionConflict,
            "WorkflowDefinitionError": definitions.WorkflowDefinitionError,
            "WorkflowPublicValidationError": definitions.WorkflowPublicValidationError,
            "_prepare_workflow_url_access_payload": lambda payload, user_id: payload,
            "_resolve_active_group_for_workflow_management": lambda user_id: (GROUP_ID, copy.deepcopy(self.store.settings)),
            "save_group_workflow": self.store.module.save_group_workflow,
            "log_workflow_creation": lambda **kwargs: None,
            "log_workflow_update": lambda **kwargs: None,
            "authorize_workflow_run_read": lambda *args, **kwargs: None,
            "AnalysisResultUnavailable": LookupError,
        }
        _compile(ROUTES_FILE, ROUTE_FUNCTIONS, namespace, nested=True)
        app = Flask("group-workflow-file-sync-enabled-seam")
        app.add_url_rule("/api/group/workflows/file-sync-sources", endpoint="sources",
                         view_func=namespace["get_group_workflow_file_sync_sources"], methods=["GET"])
        app.add_url_rule("/api/group/workflows", endpoint="save",
                         view_func=namespace["save_group_workflow_route"], methods=["POST"])
        self.client = app.test_client()

    def configure(self, settings, caller_roles):
        self.store.settings = {
            **copy.deepcopy(self.store.settings), "allow_group_workflows": True, **copy.deepcopy(settings),
        }
        self.caller = {"roles": list(caller_roles)}

    def listed(self):
        response = self.client.get(SOURCES_PATH)
        assert response.status_code == 200, response.get_data(as_text=True)
        return response.json

    def save_passes_the_gate(self):
        payload = {
            "name": "Sync before run", "definition_version": 2, "runner_type": "model", "trigger_type": "manual",
            "tasks": [{"id": "collect", "type": "instructions", "name": "Collect", "instructions": "Collect.",
                       "runner": {"type": "inherit"}}],
            "reference_inputs": [], "group_id": GROUP_ID,
            "file_sync": {"enabled": True, "wait_mode": "complete", "continue_mode": "always",
                          "use_changed_documents": True,
                          "sources": [{"scope_type": "group", "scope_id": GROUP_ID, "source_id": SOURCE_ID}]},
        }
        response = self.client.post("/api/group/workflows", json=payload)
        if response.status_code == 201:
            return True
        # Any refusal other than the File Sync gate would make this comparison meaningless.
        assert response.status_code == 400, response.get_data(as_text=True)
        assert response.json == {"error": F4_MESSAGE, "code": "invalid_workflow_settings"}
        return False


FILE_SYNC_STATES = {
    "on": {"enable_file_sync": True, "enable_file_sync_group": True, **REDIS_READY},
    "group_off": {"enable_file_sync": True, "enable_file_sync_group": False, **REDIS_READY},
    "app_off": {"enable_file_sync": False, "enable_file_sync_group": True, **REDIS_READY},
    "redis_not_ready": {"enable_file_sync": True, "enable_file_sync_group": True, "enable_redis_cache": False},
    "unassigned_group": {"enable_file_sync": True, "enable_file_sync_group": True, **REDIS_READY,
                         "require_group_assignment_for_file_sync": True, "file_sync_allowed_group_ids": []},
}
ADMIN_ONLY = {"admin_only": {"file_sync_group_admin_only": True}, "everyone": {"file_sync_group_admin_only": False}}
CALLERS = {"app_admin": ["Admin"], "app_user": ["User"]}
MATRIX = list(itertools.product(sorted(FILE_SYNC_STATES), sorted(ADMIN_ONLY), sorted(CALLERS)))


@pytest.mark.parametrize("state, restriction, caller", MATRIX)
def test_the_sources_flag_is_the_gate_the_save_applies(state, restriction, caller):
    routes = SeamRoutes()
    routes.configure({**FILE_SYNC_STATES[state], **ADMIN_ONLY[restriction]}, CALLERS[caller])

    listed = routes.listed()
    saved = routes.save_passes_the_gate()

    assert listed["file_sync_enabled"] is saved
    assert bool(listed["sources"]) is saved
    # Both calls reached the one gate with identical settings, group and caller.
    assert len(routes.gate_calls) >= 2
    assert len(set(routes.gate_calls)) == 1, routes.gate_calls


def test_the_matrix_is_not_vacuous():
    """Each gate input changes the outcome somewhere in the matrix, so the seam is really exercised."""
    outcomes = {}
    for state, restriction, caller in MATRIX:
        routes = SeamRoutes()
        routes.configure({**FILE_SYNC_STATES[state], **ADMIN_ONLY[restriction]}, CALLERS[caller])
        outcomes[(state, restriction, caller)] = routes.listed()["file_sync_enabled"]

    assert outcomes[("on", "everyone", "app_user")] is True
    assert outcomes[("on", "admin_only", "app_user")] is False
    assert outcomes[("on", "admin_only", "app_admin")] is True
    for state in ("group_off", "app_off", "redis_not_ready", "unassigned_group"):
        assert not any(value for (name, _, _), value in outcomes.items() if name == state), state


def test_the_route_asks_the_gate_with_the_callers_roles():
    """Pin the call shape: the route passes the caller's roles, like the save route does for F4."""
    tree = ast.parse(ROUTES_FILE.read_text(encoding="utf-8"))
    helper = next(node for node in ast.walk(tree)
                  if isinstance(node, ast.FunctionDef) and node.name == "_group_workflow_file_sync_enabled")
    gate_calls = [node for node in ast.walk(helper) if isinstance(node, ast.Call)
                  and isinstance(node.func, ast.Name) and node.func.id == "is_file_sync_enabled_for_group"]
    assert len(gate_calls) == 1
    user_info = {keyword.arg: keyword.value for keyword in gate_calls[0].keywords}["user_info"]
    assert isinstance(user_info, ast.Call) and user_info.func.id == "_get_current_user_info_with_roles"
    save_route = next(node for node in ast.walk(tree)
                      if isinstance(node, ast.FunctionDef) and node.name == "save_group_workflow_route")
    save_calls = [node for node in ast.walk(save_route) if isinstance(node, ast.Call)
                  and isinstance(node.func, ast.Name) and node.func.id == "save_group_workflow"]
    save_user_info = {keyword.arg: keyword.value for keyword in save_calls[0].keywords}["user_info"]
    assert isinstance(save_user_info, ast.Call) and save_user_info.func.id == "_get_current_user_info_with_roles"
