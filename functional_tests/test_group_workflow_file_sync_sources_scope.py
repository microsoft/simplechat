# test_group_workflow_file_sync_sources_scope.py
#!/usr/bin/env python3
"""
Functional test for the group workflow File Sync source list and its explicit group scope.
Version: 0.261.141
Implemented in: 0.261.141

This test ensures that ``GET /api/group/workflows/file-sync-sources`` resolves its group the
same way as every other group workflow route. An explicit ``?group_id`` is authorized with
``assert_group_role`` against the File Sync manager roles, and ``require_active_group`` is
never consulted. Without ``group_id``, the route keeps the legacy active-group behaviour. A
non-manager, a non-member or an unknown group is refused before any source is listed, and the
group workflow feature gates still apply.

The route body and its helpers are compiled from ``route_backend_workflows.py``. The group
role checks (``assert_group_role``, ``get_user_role_in_group`` and ``require_active_group``)
and the workflow feature gate (``is_group_workflows_enabled_for_group``) are the real
functions. Only the group store, user settings and the File Sync source store are doubled, so
no Flask app registration, Cosmos, Key Vault or network is required.
"""

import ast
import importlib.util
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask, jsonify, request


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
ROUTES_FILE = APP_ROOT / "route_backend_workflows.py"
GROUP_FILE = APP_ROOT / "functions_group.py"
SETTINGS_FILE = APP_ROOT / "functions_settings.py"
FILE_SYNC_FILE = APP_ROOT / "functions_file_sync.py"
GROUP_WORKFLOWS_FILE = APP_ROOT / "functions_group_workflows.py"
ASSIGNMENT_IDS_FILE = APP_ROOT / "functions_group_assignment_ids.py"
SOURCES_PATH = "/api/group/workflows/file-sync-sources"

# Group workflow assignment lists hold canonical UUIDs, so the groups use UUID identifiers.
ACTIVE_GROUP = "11111111-1111-4111-8111-111111111111"
PAGE_GROUP = "22222222-2222-4222-8222-222222222222"
MISSING_GROUP = "33333333-3333-4333-8333-333333333333"

ROUTE_HELPERS = (
    "_normalize_identifier",
    "_assert_group_workflow_feature_enabled",
    "_resolve_active_group_for_workflows",
    "_serialize_workflow_file_sync_source",
    "_collect_group_workflow_file_sync_sources",
)
ROUTE_FUNCTION = "get_group_workflow_file_sync_sources"


def _module_constant(source_file, name):
    """Read a literal module constant from source, so the test never drifts from it."""
    tree = ast.parse(Path(source_file).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} is not a literal constant in {source_file.name}")


def _functions(source_file, names):
    """Return the named function definitions, including functions nested in a registrar."""
    tree = ast.parse(Path(source_file).read_text(encoding="utf-8"), filename=str(source_file))
    found = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in names and node.name not in found:
            node.decorator_list = []
            found[node.name] = node
    missing = set(names) - set(found)
    assert not missing, f"Missing functions in {source_file.name}: {sorted(missing)}"
    return [found[name] for name in names]


def _compile_into(source_file, names, namespace):
    module = ast.Module(body=_functions(source_file, names), type_ignores=[])
    exec(compile(module, str(source_file), "exec"), namespace)
    return namespace


def _load_pure_module(name, source_file):
    spec = importlib.util.spec_from_file_location(name, source_file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FILE_SYNC_MANAGER_ROLES = _module_constant(FILE_SYNC_FILE, "FILE_SYNC_MANAGER_ROLES")
GROUP_WORKFLOW_MEMBER_ROLES = _module_constant(GROUP_WORKFLOWS_FILE, "GROUP_WORKFLOW_MEMBER_ROLES")


def _group(group_id, *, owner, admins=(), managers=(), users=()):
    return {
        "id": group_id,
        "name": f"Group {group_id}",
        "owner": {"id": owner},
        "admins": list(admins),
        "documentManagers": list(managers),
        "users": [{"userId": user_id} for user_id in users],
    }


def _source(group_id, source_id, name, **fields):
    return {
        "id": source_id,
        "scope_type": "group",
        "group_id": group_id,
        "name": name,
        "source_type": "smb",
        "enabled": True,
        "auth": {"password": "never-return"},
        **fields,
    }


class SourcesHarness:
    """The real route body and group role checks over in-memory stores."""

    def __init__(self):
        self.state = {"user": "manager", "active_group": ACTIVE_GROUP}
        self.settings = {"allow_group_workflows": True, "enable_group_workspaces": True}
        self.file_sync_groups = {ACTIVE_GROUP, PAGE_GROUP}
        self.groups = {
            ACTIVE_GROUP: _group(ACTIVE_GROUP, owner="owner-a", admins=["manager"], users=["member"]),
            PAGE_GROUP: _group(
                PAGE_GROUP, owner="owner-b", admins=["manager"], managers=["doc-manager"], users=["member"],
            ),
        }
        self.sources = {
            ACTIVE_GROUP: [_source(ACTIVE_GROUP, "source-a1", "Active group share")],
            PAGE_GROUP: [
                _source(PAGE_GROUP, "source-b1", "Finance share"),
                _source(PAGE_GROUP, "source-b2", "Paused share", enabled=False),
                {"scope_type": "group", "group_id": PAGE_GROUP, "name": "No identifier"},
            ],
        }
        self.role_checks = []
        self.active_group_reads = []
        self.source_listings = []
        self.logged = []

        functions_settings = SimpleNamespace(
            get_user_settings=lambda user_id: {
                "id": user_id, "settings": {"activeGroupOid": self.state["active_group"]},
            },
        )
        group_namespace = {
            "Iterable": tuple,
            "find_group_by_id": lambda group_id: self.groups.get(group_id),
            "functions_settings": functions_settings,
        }
        _compile_into(GROUP_FILE, ("get_user_role_in_group", "assert_group_role", "require_active_group"), group_namespace)
        real_assert_group_role = group_namespace["assert_group_role"]
        real_require_active_group = group_namespace["require_active_group"]

        def assert_group_role(user_id, group_id, allowed_roles=("Owner", "Admin")):
            self.role_checks.append((user_id, group_id, tuple(allowed_roles)))
            return real_assert_group_role(user_id, group_id, allowed_roles=allowed_roles)

        # The real require_active_group resolves assert_group_role from its own globals, so the
        # recording wrapper sees the legacy path's role check as well as the explicit one.
        group_namespace["assert_group_role"] = assert_group_role

        def require_active_group(user_id, allowed_roles=GROUP_WORKFLOW_MEMBER_ROLES):
            self.active_group_reads.append((user_id, tuple(allowed_roles)))
            return real_require_active_group(user_id, allowed_roles=allowed_roles)

        assignment_ids = _load_pure_module("functions_group_assignment_ids", ASSIGNMENT_IDS_FILE)
        settings_namespace = {
            "normalize_group_workflow_allowed_group_ids": assignment_ids.normalize_group_workflow_allowed_group_ids,
        }
        _compile_into(SETTINGS_FILE, ("is_group_workflows_enabled_for_group",), settings_namespace)

        def list_file_sync_sources(scope_type, scope_id):
            self.source_listings.append((scope_type, scope_id))
            return [dict(source) for source in self.sources.get(scope_id, [])]

        def sanitize_file_sync_source(source):
            sanitized = dict(source or {})
            sanitized.pop("auth", None)
            return sanitized

        namespace = {
            "request": request,
            "jsonify": jsonify,
            "logging": logging,
            "log_event": lambda *args, **kwargs: self.logged.append((args, kwargs)),
            "get_current_user_id": lambda: self.state["user"],
            "get_settings": lambda: dict(self.settings),
            "is_group_workflows_enabled_for_group": settings_namespace["is_group_workflows_enabled_for_group"],
            "assert_group_role": assert_group_role,
            "require_active_group": require_active_group,
            "GROUP_WORKFLOW_MEMBER_ROLES": GROUP_WORKFLOW_MEMBER_ROLES,
            "FILE_SYNC_MANAGER_ROLES": FILE_SYNC_MANAGER_ROLES,
            "FILE_SYNC_SCOPE_PERSONAL": _module_constant(FILE_SYNC_FILE, "FILE_SYNC_SCOPE_PERSONAL"),
            "FILE_SYNC_SCOPE_GROUP": _module_constant(FILE_SYNC_FILE, "FILE_SYNC_SCOPE_GROUP"),
            "FILE_SYNC_SCOPE_PUBLIC": _module_constant(FILE_SYNC_FILE, "FILE_SYNC_SCOPE_PUBLIC"),
            "is_file_sync_enabled_for_group": lambda settings, group_id, user_info=None: group_id in self.file_sync_groups,
            "list_file_sync_sources": list_file_sync_sources,
            "sanitize_file_sync_source": sanitize_file_sync_source,
            "_get_current_user_info_with_roles": lambda: {"roles": ["User"]},
        }
        _compile_into(ROUTES_FILE, (*ROUTE_HELPERS, ROUTE_FUNCTION), namespace)
        app = Flask("group-workflow-file-sync-sources")
        app.add_url_rule(SOURCES_PATH, endpoint=ROUTE_FUNCTION, view_func=namespace[ROUTE_FUNCTION], methods=["GET"])
        self.client = app.test_client()

    def get(self, query=""):
        return self.client.get(f"{SOURCES_PATH}{query}")


@pytest.fixture
def harness():
    return SourcesHarness()


def test_explicit_group_id_lists_the_named_group_without_reading_the_active_group(harness):
    """An explicit group is authorized with the manager roles and the active group is ignored."""
    response = harness.get(f"?group_id={PAGE_GROUP}")

    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.json == {"sources": [
        {
            "scope_type": "group", "scope_id": PAGE_GROUP, "source_id": "source-b1",
            "name": "Finance share", "source_type": "smb", "enabled": True,
            "label": "Finance share (Group)",
        },
        {
            "scope_type": "group", "scope_id": PAGE_GROUP, "source_id": "source-b2",
            "name": "Paused share", "source_type": "smb", "enabled": False,
            "label": "Paused share (Group)",
        },
    ]}
    assert harness.state["active_group"] == ACTIVE_GROUP
    assert harness.active_group_reads == []
    assert harness.role_checks == [("manager", PAGE_GROUP, FILE_SYNC_MANAGER_ROLES)]
    assert harness.source_listings == [("group", PAGE_GROUP)]
    assert "never-return" not in response.get_data(as_text=True)


@pytest.mark.parametrize("query", [
    f"?group_id={PAGE_GROUP}",
    f"?groupId={PAGE_GROUP}",
    f"?group_id=%20{PAGE_GROUP}%20",
])
def test_explicit_group_spellings_resolve_like_the_sibling_routes(harness, query):
    """The resolver accepts the same explicit group spellings as every other group workflow route."""
    response = harness.get(query)

    assert response.status_code == 200, response.get_data(as_text=True)
    assert {source["scope_id"] for source in response.json["sources"]} == {PAGE_GROUP}
    assert harness.active_group_reads == []


def test_document_managers_may_list_sources_for_their_explicit_group(harness):
    """DocumentManager is a File Sync manager role, so the explicit group is readable."""
    harness.state["user"] = "doc-manager"

    response = harness.get(f"?group_id={PAGE_GROUP}")

    assert response.status_code == 200, response.get_data(as_text=True)
    assert [source["source_id"] for source in response.json["sources"]] == ["source-b1", "source-b2"]
    assert harness.role_checks == [("doc-manager", PAGE_GROUP, FILE_SYNC_MANAGER_ROLES)]


def test_a_member_who_is_not_a_file_sync_manager_is_refused_with_group_id(harness):
    """A plain group member is refused before any source is listed, even though they belong to the group."""
    harness.state["user"] = "member"

    response = harness.get(f"?group_id={PAGE_GROUP}")

    assert response.status_code == 403
    assert response.json == {"error": "Insufficient permissions for this group"}
    assert harness.source_listings == []
    assert harness.active_group_reads == []
    assert harness.role_checks == [("member", PAGE_GROUP, FILE_SYNC_MANAGER_ROLES)]


def test_non_members_and_unknown_groups_are_refused_before_listing(harness):
    """A non-member gets 403 and an unknown group 404, and neither reaches the source store."""
    harness.state["user"] = "outsider"
    outsider = harness.get(f"?group_id={PAGE_GROUP}")
    unknown = harness.get(f"?group_id={MISSING_GROUP}")

    assert outsider.status_code == 403
    assert outsider.json == {"error": "User is not a member of this group"}
    assert unknown.status_code == 404
    assert unknown.json == {"error": "Group not found"}
    assert harness.source_listings == []
    assert harness.active_group_reads == []


def test_without_group_id_the_legacy_active_group_path_is_unchanged(harness):
    """Without group_id the route still lists the active group, authorized with the manager roles."""
    response = harness.get()

    assert response.status_code == 200, response.get_data(as_text=True)
    assert [source["source_id"] for source in response.json["sources"]] == ["source-a1"]
    assert harness.active_group_reads == [("manager", FILE_SYNC_MANAGER_ROLES)]
    assert harness.role_checks == [("manager", ACTIVE_GROUP, FILE_SYNC_MANAGER_ROLES)]
    assert harness.source_listings == [("group", ACTIVE_GROUP)]


def test_without_group_id_legacy_refusals_are_unchanged(harness):
    """The legacy path keeps its 403 for a non-manager and its 400 when no group is active."""
    harness.state["user"] = "member"
    member = harness.get()
    harness.state.update(user="manager", active_group="")
    no_active_group = harness.get()

    assert member.status_code == 403
    assert member.json == {"error": "Insufficient permissions for this group"}
    assert no_active_group.status_code == 400
    assert no_active_group.json == {"error": "No active group selected"}
    assert harness.source_listings == []


def test_group_workflow_feature_gates_still_apply_to_the_explicit_group(harness):
    """Disabled or unassigned group workflows refuse the explicit group like the sibling routes."""
    harness.settings["allow_group_workflows"] = False
    disabled = harness.get(f"?group_id={PAGE_GROUP}")
    harness.settings.update(
        allow_group_workflows=True,
        require_group_assignment_for_group_workflows=True,
        group_workflow_allowed_group_ids=[ACTIVE_GROUP],
    )
    unassigned = harness.get(f"?group_id={PAGE_GROUP}")
    assigned = harness.get(f"?group_id={ACTIVE_GROUP}")

    assert disabled.status_code == 400
    assert disabled.json == {"error": "Group workflows are disabled."}
    assert unassigned.status_code == 403
    assert unassigned.json == {"error": "This group is not assigned to use workflows."}
    assert assigned.status_code == 200, assigned.get_data(as_text=True)
    assert harness.source_listings == [("group", ACTIVE_GROUP)]
    assert harness.active_group_reads == []


def test_group_file_sync_disabled_returns_no_sources_for_the_explicit_group(harness):
    """When File Sync is not enabled for the named group, the list is empty and the store is not read."""
    harness.file_sync_groups = {ACTIVE_GROUP}

    response = harness.get(f"?group_id={PAGE_GROUP}")

    assert response.status_code == 200
    assert response.json == {"sources": []}
    assert harness.source_listings == []
    assert harness.active_group_reads == []


def test_route_body_uses_the_explicit_group_resolver_with_manager_roles():
    """Pin the one-line change: the route resolves through the shared resolver, never the active group directly."""
    route = _functions(ROUTES_FILE, (ROUTE_FUNCTION,))[0]
    calls = [node for node in ast.walk(route) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)]
    called = {node.func.id for node in calls}

    assert "require_active_group" not in called
    assert "_assert_group_workflow_feature_enabled" not in called
    resolver_calls = [node for node in calls if node.func.id == "_resolve_active_group_for_workflows"]
    assert len(resolver_calls) == 1
    keywords = {keyword.arg: keyword.value for keyword in resolver_calls[0].keywords}
    assert isinstance(keywords.get("allowed_roles"), ast.Name)
    assert keywords["allowed_roles"].id == "FILE_SYNC_MANAGER_ROLES"
