# test_personal_workflow_file_sync_sources.py
#!/usr/bin/env python3
"""
Functional test for the File Sync sources a personal workflow can use.
Version: 0.261.207
Implemented in: 0.261.207

This test ensures that ``collect_personal_workflow_file_sync_sources`` lists the sources a personal
workflow may sync, by the rules the personal workflow sources route has always applied:

* the user's own sources, only while File Sync is on for their personal workspace, which respects
  the personal admin-only and ``file_sync_personal_require_app_role`` settings;
* the active group's sources, only when the user holds a File Sync manager role there and File
  Sync is on for that group;
* the active public workspace's sources, by the same two rules, with its id trimmed;
* a missing, unknown or unmanaged workspace skipped rather than failing the list, and sources
  without an id dropped.

It also ensures that the user settings are read once, through the reader a caller passes (the
planner passes a write-free snapshot), that the module imports no Flask, and that the planner's
projection keeps only a source's scope, id, name, type and state. The personal route returns the
collector's result with ``file_sync_enabled`` and never a credential, and a failure returns the
route's own message.

The real module is loaded from its file. ``is_file_sync_enabled_for_user``, ``assert_group_role``
and ``assert_public_workspace_role`` are the real functions, compiled from their modules; only the
File Sync configuration, the group, workspace and source stores, and user settings are doubled.
"""

import ast
import logging
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import pytest
from flask import Flask, jsonify

sys.path.append(str(Path(__file__).resolve().parent))

from test_group_workflow_file_sync_sources_scope import _compile_into, _module_constant  # noqa: E402
from test_group_workflow_round_trip_preservation import (  # noqa: E402
    APP_ROOT,
    _compiled,
    _installed,
    _load,
    _module,
)
from test_support.versioning import assert_app_version_at_least  # noqa: E402


MODULE_NAME = "functions_workflow_file_sync_sources"
MODULE_FILE = APP_ROOT / f"{MODULE_NAME}.py"
FILE_SYNC_FILE = APP_ROOT / "functions_file_sync.py"
GROUP_FILE = APP_ROOT / "functions_group.py"
PUBLIC_FILE = APP_ROOT / "functions_public_workspaces.py"
ROUTES_FILE = APP_ROOT / "route_backend_workflows.py"
SOURCES_PATH = "/api/user/workflows/file-sync-sources"
ROUTE_FUNCTION = "get_user_workflow_file_sync_sources"

OWNER = "owner-1"
GROUP = "group-alpha"
OTHER_GROUP = "group-beta"
PUBLIC = "public-handbook"
SECRET = "never-return-this-password"
FILE_SYNC_MANAGER_ROLES = _module_constant(FILE_SYNC_FILE, "FILE_SYNC_MANAGER_ROLES")
PERSONAL_APP_ROLE = _module_constant(FILE_SYNC_FILE, "FILE_SYNC_PERSONAL_APP_ROLE")
SCOPES = {
    name: _module_constant(FILE_SYNC_FILE, name)
    for name in ("FILE_SYNC_SCOPE_PERSONAL", "FILE_SYNC_SCOPE_GROUP", "FILE_SYNC_SCOPE_PUBLIC")
}


def _source(source_id, name, **fields):
    return {
        "id": source_id, "name": name, "source_type": "smb", "enabled": True,
        "auth": {"password": SECRET}, **fields,
    }


def _serialize(scope_type, scope_id, source):
    return {"scope_type": scope_type, "scope_id": scope_id, "source_id": source.get("id") or "", "name": source.get("name")}


class CollectorHarness:
    """The real collector and role checks over in-memory stores."""

    def __init__(self):
        self.settings = {
            "enable_file_sync": True,
            "enable_file_sync_personal": True,
            "file_sync_personal_admin_only": False,
            "file_sync_personal_require_app_role": False,
        }
        self.user_info = {"roles": ["User"], "email": "owner@example.com"}
        self.user_settings = {"settings": {"activeGroupOid": GROUP, "activePublicWorkspaceOid": f"  {PUBLIC}  "}}
        self.groups = {
            GROUP: {"id": GROUP, "owner": {"id": "someone-else"}, "admins": [OWNER], "documentManagers": [], "users": []},
            OTHER_GROUP: {"id": OTHER_GROUP, "owner": {"id": OWNER}, "admins": [], "documentManagers": [], "users": []},
        }
        self.public_workspaces = {
            PUBLIC: {"id": PUBLIC, "owner": {"userId": "someone-else"}, "admins": [], "documentManagers": [OWNER]},
        }
        self.file_sync_groups = {GROUP, OTHER_GROUP}
        self.file_sync_public_workspaces = {PUBLIC}
        self.sources = {
            ("personal", OWNER): [_source("home-share", "Home share"), {"name": "No identifier"}],
            ("group", GROUP): [_source("finance-share", "Finance share"), _source("paused", "Paused", enabled=False)],
            ("group", OTHER_GROUP): [_source("beta-share", "Beta share")],
            ("public", PUBLIC): [_source("handbook-share", "Handbook share")],
        }
        self.default_settings_reads = []
        self.listings = []

        typing_names = {"Any": Any, "Dict": Dict, "Iterable": Iterable, "Optional": Optional}
        public_namespace = _compiled(PUBLIC_FILE, ("get_user_role_in_public_workspace",), {})
        file_sync_namespace = {
            **typing_names,
            "FILE_SYNC_MANAGER_ROLES": FILE_SYNC_MANAGER_ROLES,
            "FILE_SYNC_PERSONAL_APP_ROLE": PERSONAL_APP_ROLE,
            # Only the four settings the personal gate reads; the real configuration also needs Redis.
            "get_file_sync_config": lambda settings: dict(settings),
            "find_public_workspace_by_id": lambda workspace_id: self.public_workspaces.get(workspace_id),
            "get_user_role_in_public_workspace": public_namespace["get_user_role_in_public_workspace"],
        }
        _compiled(FILE_SYNC_FILE, (
            "_user_info_has_admin_role", "_user_info_has_app_role", "is_file_sync_enabled_for_user",
            "assert_public_workspace_role",
        ), file_sync_namespace)
        group_namespace = {
            "Iterable": tuple,
            "find_group_by_id": lambda group_id: self.groups.get(group_id),
            "functions_settings": _module("functions_settings"),
        }
        _compile_into(GROUP_FILE, ("get_user_role_in_group", "assert_group_role"), group_namespace)

        def list_file_sync_sources(scope_type, scope_id):
            self.listings.append((scope_type, scope_id))
            return [dict(source) for source in self.sources.get((scope_type, scope_id), [])]

        def get_user_settings(user_id):
            self.default_settings_reads.append(user_id)
            return self.user_settings

        stubs = {
            "functions_settings": _module("functions_settings", get_user_settings=get_user_settings),
            "functions_file_sync": _module(
                "functions_file_sync",
                FILE_SYNC_MANAGER_ROLES=FILE_SYNC_MANAGER_ROLES,
                **SCOPES,
                assert_public_workspace_role=file_sync_namespace["assert_public_workspace_role"],
                is_file_sync_enabled_for_user=file_sync_namespace["is_file_sync_enabled_for_user"],
                is_file_sync_enabled_for_group=lambda settings, group_id, user_info=None: group_id in self.file_sync_groups,
                is_file_sync_enabled_for_public_workspace=lambda settings, workspace_id, user_info=None: (
                    workspace_id in self.file_sync_public_workspaces
                ),
                list_file_sync_sources=list_file_sync_sources,
            ),
            "functions_group": _module("functions_group", assert_group_role=group_namespace["assert_group_role"]),
        }
        with _installed((*stubs, MODULE_NAME)):
            sys.modules.update(stubs)
            self.module = _load(MODULE_NAME, MODULE_FILE)

    def collect(self, **kwargs):
        kwargs.setdefault("serialize", _serialize)
        return self.module.collect_personal_workflow_file_sync_sources(OWNER, self.settings, self.user_info, **kwargs)


def _keys(sources):
    return [(source["scope_type"], source["scope_id"], source["source_id"]) for source in sources]


@pytest.fixture
def harness():
    return CollectorHarness()


def test_every_workspace_the_user_manages_is_listed_once_with_trimmed_ids(harness):
    assert_app_version_at_least("0.261.207")
    enabled, sources = harness.collect()
    assert enabled is True
    assert _keys(sources) == [
        ("personal", OWNER, "home-share"),
        ("group", GROUP, "finance-share"),
        ("group", GROUP, "paused"),
        ("public", PUBLIC, "handbook-share"),
    ]
    # Only the active group is read, never another group the user owns.
    assert ("group", OTHER_GROUP) not in harness.listings


@pytest.mark.parametrize("setting,roles,listed", [
    ({}, ["User"], True),
    ({"enable_file_sync_personal": False}, ["User"], False),
    ({"enable_file_sync": False}, ["User"], False),
    ({"file_sync_personal_admin_only": True}, ["User"], False),
    ({"file_sync_personal_admin_only": True}, ["Admin"], True),
    ({"file_sync_personal_require_app_role": True}, ["User"], False),
    ({"file_sync_personal_require_app_role": True}, ["User", PERSONAL_APP_ROLE], True),
])
def test_personal_sources_follow_the_personal_file_sync_gate(harness, setting, roles, listed):
    harness.settings.update(setting)
    harness.user_info["roles"] = roles
    enabled, sources = harness.collect()
    assert enabled is listed
    assert (("personal", OWNER, "home-share") in _keys(sources)) is listed
    assert (("personal", OWNER) in harness.listings) is listed
    # The workspaces the user manages are listed either way.
    assert ("group", GROUP, "finance-share") in _keys(sources)
    assert ("public", PUBLIC, "handbook-share") in _keys(sources)


@pytest.mark.parametrize("change", ["no_active_group", "unknown_group", "member", "file_sync_off"])
def test_the_active_group_needs_a_manager_role_and_file_sync(harness, change):
    if change == "no_active_group":
        harness.user_settings["settings"]["activeGroupOid"] = ""
    elif change == "unknown_group":
        harness.user_settings["settings"]["activeGroupOid"] = "group-missing"
    elif change == "member":
        harness.groups[GROUP]["admins"] = []
        harness.groups[GROUP]["users"] = [{"userId": OWNER}]
    else:
        harness.file_sync_groups.discard(GROUP)
    enabled, sources = harness.collect()
    assert enabled is True
    assert not [key for key in _keys(sources) if key[0] == "group"]
    assert ("group", GROUP) not in harness.listings
    assert ("personal", OWNER, "home-share") in _keys(sources)
    assert ("public", PUBLIC, "handbook-share") in _keys(sources)


@pytest.mark.parametrize("change", ["no_active_workspace", "unknown_workspace", "member", "file_sync_off"])
def test_the_active_public_workspace_needs_a_manager_role_and_file_sync(harness, change):
    if change == "no_active_workspace":
        harness.user_settings["settings"]["activePublicWorkspaceOid"] = "   "
    elif change == "unknown_workspace":
        harness.user_settings["settings"]["activePublicWorkspaceOid"] = "public-missing"
    elif change == "member":
        harness.public_workspaces[PUBLIC]["documentManagers"] = []
    else:
        harness.file_sync_public_workspaces.discard(PUBLIC)
    _, sources = harness.collect()
    assert not [key for key in _keys(sources) if key[0] == "public"]
    assert ("public", PUBLIC) not in harness.listings
    assert ("group", GROUP, "finance-share") in _keys(sources)


def test_user_settings_are_read_once_through_the_given_reader(harness):
    snapshot_reads = []

    def snapshot(user_id):
        snapshot_reads.append(user_id)
        return harness.user_settings

    _, sources = harness.collect(user_settings_reader=snapshot)
    assert snapshot_reads == [OWNER]
    assert harness.default_settings_reads == []
    assert ("group", GROUP, "finance-share") in _keys(sources)

    # The route passes no reader, so the settings module's reader is used, still once.
    harness.collect()
    assert harness.default_settings_reads == [OWNER]


def test_user_settings_without_a_settings_block_list_only_personal_sources(harness):
    for stored in (None, {}, {"settings": None}, {"settings": ["not", "a", "block"]}):
        enabled, sources = harness.collect(user_settings_reader=lambda user_id, stored=stored: stored)
        assert enabled is True
        assert _keys(sources) == [("personal", OWNER, "home-share")]


def test_the_projection_keeps_only_the_planner_fields(harness):
    project = harness.module.project_workflow_file_sync_source
    projected = project("group", GROUP, _source("finance-share", " Finance share ", source_type="onedrive", enabled=False))
    assert projected == {
        "scope_type": "group", "scope_id": GROUP, "source_id": "finance-share",
        "name": "Finance share", "source_type": "onedrive", "enabled": False,
    }
    assert project("personal", OWNER, {"id": "unnamed"})["name"] == "unnamed"
    assert project("personal", OWNER, None) == {
        "scope_type": "personal", "scope_id": OWNER, "source_id": "", "name": "", "source_type": "", "enabled": True,
    }
    _, sources = harness.collect(serialize=project)
    assert all(set(source) == {"scope_type", "scope_id", "source_id", "name", "source_type", "enabled"} for source in sources)
    assert SECRET not in repr(sources)


def test_the_module_imports_no_flask_and_only_its_known_dependencies():
    tree = ast.parse(MODULE_FILE.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module)
    assert imported == {"functions_settings", "functions_file_sync", "functions_group"}, imported


class RouteHarness(CollectorHarness):
    """The real personal sources route body over the real collector."""

    def __init__(self):
        super().__init__()
        self.logged = []
        self.fail = False

        def sanitize_file_sync_source(source):
            sanitized = dict(source or {})
            sanitized.pop("auth", None)
            return sanitized

        def collector(*args, **kwargs):
            if self.fail:
                raise RuntimeError(f"cosmos exploded while reading {SECRET}")
            return self.module.collect_personal_workflow_file_sync_sources(*args, **kwargs)

        namespace = {
            **SCOPES,
            "jsonify": jsonify,
            "logging": logging,
            "log_event": lambda *args, **kwargs: self.logged.append((args, kwargs)),
            "get_current_user_id": lambda: OWNER,
            "get_settings": lambda: self.settings,
            "_get_current_user_info_with_roles": lambda: self.user_info,
            "sanitize_file_sync_source": sanitize_file_sync_source,
            "collect_personal_workflow_file_sync_sources": collector,
        }
        _compile_into(ROUTES_FILE, (
            "_serialize_workflow_file_sync_source", "_collect_workflow_file_sync_sources", ROUTE_FUNCTION,
        ), namespace)
        app = Flask("personal-workflow-file-sync-sources")
        app.add_url_rule(SOURCES_PATH, endpoint=ROUTE_FUNCTION, view_func=namespace[ROUTE_FUNCTION], methods=["GET"])
        self.client = app.test_client()


def test_the_route_returns_the_collected_sources_with_the_personal_gate():
    route = RouteHarness()
    response = route.client.get(SOURCES_PATH)
    payload = response.get_json()
    assert response.status_code == 200
    assert payload["file_sync_enabled"] is True
    assert [source["label"] for source in payload["sources"]] == [
        "Home share (Personal)", "Finance share (Group)", "Paused (Group)", "Handbook share (Public)",
    ]
    assert payload["sources"][2]["enabled"] is False
    assert SECRET not in response.get_data(as_text=True)
    assert all("auth" not in source for source in payload["sources"])

    route.settings["file_sync_personal_require_app_role"] = True
    response = route.client.get(SOURCES_PATH)
    payload = response.get_json()
    assert response.status_code == 200
    assert payload["file_sync_enabled"] is False
    assert [source["scope_type"] for source in payload["sources"]] == ["group", "group", "public"]


def test_a_route_failure_returns_its_own_message():
    route = RouteHarness()
    route.fail = True
    response = route.client.get(SOURCES_PATH)
    assert response.status_code == 500
    assert response.get_json() == {"error": "Unable to load File Sync sources right now."}
    assert SECRET not in response.get_data(as_text=True)
    assert len(route.logged) == 1


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
