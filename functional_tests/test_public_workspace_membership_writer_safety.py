# test_public_workspace_membership_writer_safety.py
"""
Functional test for the guarded public-workspace membership, request and role routes.
Version: 0.261.174
Implemented in: 0.261.174

The six classic writers ``api_request_public_workspace``, ``api_handle_public_request``,
``api_add_public_member``, ``api_remove_public_member``, ``api_update_public_member_role``
and ``api_transfer_public_ownership`` were moved onto
``update_public_workspace_document_with_etag_guard`` so a membership edit never
restores the rest of the workspace document from a stale copy.

Two things are pinned. First, at the source level, that each converted route forwards
the classic ``cache_reason`` through ``_guarded_public_write`` and that only an
approval bumps the shared cache once. Second, by running the **real** nested route
bodies, their real wrapper and the real guard against the etag-enforcing
``FakeContainer``, the writer-safety rulings that reshaped these handlers:

- R5.5: a promoted Admin stored as a ``{"userId": ...}`` dict is recognised through
  ``get_user_role_in_public_workspace`` and can approve a request, add a member and
  receive ownership, where the old string-only ``user_id in ws.get("admins", [])``
  test would have answered 403 or crashed on a dict entry.
- R5.7: whenever a member moves between ``admins``, ``documentManagers`` and
  ``owner``, their stored name and email are carried over rather than blanked; a
  transfer leaves the old owner a DocumentManager with their name and email
  (decision 21).

Only the Cosmos container, the chat-bootstrap bump, Microsoft Graph, notifications
and the Flask ``request``/``jsonify`` shims are fakes; no network is touched.
"""

import ast
import copy
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

import pytest
from azure.core import MatchConditions
from azure.cosmos import exceptions as cosmos_exceptions

from test_file_sync_concurrent_write_safety import FakeContainer
from test_support.agent_delegation import APP_ROOT


APP_DIR = Path(APP_ROOT)
ROUTE_FILE = "route_backend_public_workspaces.py"
WORKSPACES_FILE = "functions_public_workspaces.py"
WS_ID = "ws-1"
REGISTER = "register_route_backend_public_workspaces"


# --------------------------------------------------------------------------- #
# Source-level: every converted route forwards its classic cache_reason.
# --------------------------------------------------------------------------- #

def _forwarded_reasons(writer):
    """``cache_reason`` per innermost calling function for a call to ``writer``."""
    tree = ast.parse((APP_DIR / ROUTE_FILE).read_text(encoding="utf-8"))
    reasons = {}

    def visit(node, owner):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit(child, child.name)
                continue
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name) and child.func.id == writer:
                [value] = [kw.value for kw in child.keywords if kw.arg == "cache_reason"]
                assert owner not in reasons, f"{owner} calls {writer} more than once"
                reasons[owner] = value.value if isinstance(value, ast.Constant) else ast.unparse(value)
            visit(child, owner)

    visit(tree, None)
    return reasons


def test_the_membership_writers_forward_their_classic_cache_reasons():
    """Converted with the bumps they always had: approve bumps once after the commit
    (the action is read inside the change), add/remove/role/transfer forward theirs,
    and the join request commits without a bump. Other guarded writers (settings,
    logo, download) are pinned by their own suite, so this reads only the six here."""
    membership = {
        "api_request_public_workspace", "api_handle_public_request", "api_add_public_member",
        "api_remove_public_member", "api_update_public_member_role", "api_transfer_public_ownership",
    }
    forwarded = _forwarded_reasons("_guarded_public_write")
    assert {name: forwarded[name] for name in membership if name in forwarded} == {
        "api_request_public_workspace": None,
        "api_handle_public_request": None,
        "api_add_public_member": "public_workspace_member_added",
        "api_remove_public_member": "public_workspace_member_removed",
        "api_update_public_member_role": "public_workspace_member_role_updated",
        "api_transfer_public_ownership": "public_workspace_ownership_transferred",
    }
    source = (APP_DIR / ROUTE_FILE).read_text(encoding="utf-8")
    assert source.count(
        'bump_chat_bootstrap_global_cache_version(reason="public_workspace_member_request_approved")'
    ) == 1


def test_the_converted_routes_keep_no_raw_container_upsert():
    """The six converted routes write only through the guard; no raw upsert remains."""
    tree = ast.parse((APP_DIR / ROUTE_FILE).read_text(encoding="utf-8"))
    converted = {
        "api_request_public_workspace", "api_handle_public_request", "api_add_public_member",
        "api_remove_public_member", "api_update_public_member_role", "api_transfer_public_ownership",
    }
    raw = []

    def visit(node, owner):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit(child, child.name)
                continue
            if isinstance(child, ast.Call):
                func = child.func
                name = getattr(func, "attr", "")
                target = getattr(getattr(func, "value", None), "id", "")
                if name == "upsert_item" and target == "cosmos_public_workspaces_container" and owner in converted:
                    raw.append(owner)
            visit(child, owner)

    visit(tree, None)
    assert raw == [], f"converted routes still upsert raw: {raw}"


# --------------------------------------------------------------------------- #
# Behaviour: run the real nested handlers, their wrapper and the real guard.
# --------------------------------------------------------------------------- #

def _exec_names(filename, names, namespace):
    tree = ast.parse((APP_DIR / filename).read_text(encoding="utf-8"))
    selected, found = [], set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name in names:
            selected.append(node)
            found.add(node.name)
        elif isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if any(t in names for t in targets):
                selected.append(node)
                found.update(t for t in targets if t in names)
    assert found == set(names), f"Missing definitions in {filename}: {set(names) - found}"
    exec(compile(ast.Module(body=selected, type_ignores=[]), filename, "exec"), namespace)


def _exec_nested_handlers(filename, container_func, names, namespace):
    """Execute route handlers defined inside ``container_func`` with their decorators stripped."""
    tree = ast.parse((APP_DIR / filename).read_text(encoding="utf-8"))
    register = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == container_func
    )
    found = set()
    for node in register.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
            stripped = copy.deepcopy(node)
            stripped.decorator_list = []
            exec(compile(ast.Module(body=[stripped], type_ignores=[]), filename, "exec"), namespace)
            found.add(node.name)
    assert found == set(names), f"Missing nested handlers: {set(names) - found}"
    return {name: namespace[name] for name in names}


class _Request:
    def __init__(self, body, args=None):
        self._body = body
        self.args = args or {}

    def get_json(self):
        return self._body


def _environment():
    container = FakeContainer(name="public", partition_field="id")
    bumps = []
    notifications = []
    namespace = {
        "copy": copy,
        "MatchConditions": MatchConditions,
        "exceptions": cosmos_exceptions,
        "datetime": datetime,
        "quote": quote,
        "cosmos_public_workspaces_container": container,
        "bump_chat_bootstrap_global_cache_version": lambda *, reason: bumps.append(reason),
        "jsonify": lambda payload=None: payload,
        "create_notification": lambda **kwargs: notifications.append(kwargs),
        "debug_print": lambda *a, **k: None,
        "get_user_details_from_graph": lambda user_id: {"displayName": "", "email": ""},
        "find_public_workspace_by_id": lambda ws_id: container.get(ws_id, ws_id),
    }
    _exec_names(
        WORKSPACES_FILE,
        {
            "PUBLIC_DOCUMENT_WRITE_ATTEMPTS", "PublicWorkspaceDocumentWriteConflict",
            "PUBLIC_WORKSPACE_WRITE_CONFLICT_CODE", "PUBLIC_WORKSPACE_WRITE_CONFLICT_MESSAGE",
            "_stored_public_workspace_fields", "update_public_workspace_document_with_etag_guard",
            "get_user_role_in_public_workspace",
        },
        namespace,
    )
    _exec_names(
        ROUTE_FILE,
        {"is_user_in_admins", "remove_user_from_admins", "_member_user_id",
         "_PublicClassicResponse", "_guarded_public_write"},
        namespace,
    )
    handlers = _exec_nested_handlers(
        ROUTE_FILE, REGISTER,
        {"api_request_public_workspace", "api_view_public_requests", "api_handle_public_request",
         "api_list_public_members", "api_add_public_member", "api_remove_public_member",
         "api_update_public_member_role", "api_transfer_public_ownership"},
        namespace,
    )
    return SimpleNamespace(
        container=container, bumps=bumps, notifications=notifications,
        namespace=namespace, handlers=handlers,
    )


def _as_actor(env, user_id):
    env.namespace["get_current_user_info"] = lambda: {
        "userId": user_id, "email": f"{user_id}@example.test", "displayName": user_id.title(),
    }


def _set_body(env, body):
    env.namespace["request"] = _Request(body)


def _workspace(**extra):
    document = {
        "id": WS_ID,
        "name": "Public One",
        "status": "active",
        "owner": {"userId": "owner", "displayName": "Owner One", "email": "owner@example.test"},
        "admins": [],
        "documentManagers": [],
        "pendingDocumentManagers": [],
    }
    document.update(extra)
    return document


DICT_ADMIN = {"userId": "admin", "displayName": "Admin One", "email": "admin@example.test"}


def test_a_dict_format_admin_can_approve_a_document_manager_request():
    """R5.5: a promoted Admin stored as a dict approves through the role helper."""
    env = _environment()
    env.container.seed(_workspace(
        admins=[DICT_ADMIN],
        pendingDocumentManagers=[{"userId": "req", "displayName": "Requester", "email": "req@example.test"}],
    ))
    _as_actor(env, "admin")
    _set_body(env, {"action": "approve"})

    payload, status = env.handlers["api_handle_public_request"](WS_ID, "req")

    assert status == 200
    stored = env.container.get(WS_ID, WS_ID)
    assert stored["pendingDocumentManagers"] == []
    assert [dm["userId"] for dm in stored["documentManagers"]] == ["req"]
    assert env.bumps == ["public_workspace_member_request_approved"]


def test_a_string_format_admin_still_approves_without_crashing():
    """R5.5: a legacy string admin entry is still recognised and does not raise."""
    env = _environment()
    env.container.seed(_workspace(
        admins=["admin"],
        pendingDocumentManagers=[{"userId": "req", "displayName": "Requester", "email": "req@example.test"}],
    ))
    _as_actor(env, "admin")
    _set_body(env, {"action": "reject"})

    payload, status = env.handlers["api_handle_public_request"](WS_ID, "req")

    assert status == 200
    assert env.container.get(WS_ID, WS_ID)["pendingDocumentManagers"] == []
    assert env.bumps == []


def test_a_dict_format_admin_can_add_a_member():
    """R5.5: a dict Admin adds a document manager directly."""
    env = _environment()
    env.container.seed(_workspace(admins=[DICT_ADMIN]))
    _as_actor(env, "admin")
    _set_body(env, {"userId": "newbie", "displayName": "New Bie", "email": "new@example.test"})

    payload, status = env.handlers["api_add_public_member"](WS_ID)

    assert status == 200
    stored = env.container.get(WS_ID, WS_ID)
    assert [dm["userId"] for dm in stored["documentManagers"]] == ["newbie"]
    assert env.bumps == ["public_workspace_member_added"]
    assert env.notifications and env.notifications[0]["user_id"] == "newbie"


def test_a_non_member_is_refused_adding_a_member():
    """A plain user cannot add members; the role check runs on the fresh copy."""
    env = _environment()
    env.container.seed(_workspace())
    _as_actor(env, "stranger")
    _set_body(env, {"userId": "newbie"})

    payload, status = env.handlers["api_add_public_member"](WS_ID)

    assert status == 403
    assert env.container.get(WS_ID, WS_ID)["documentManagers"] == []
    assert env.bumps == []


def test_a_role_change_to_admin_keeps_the_member_name_and_email():
    """R5.7: promoting a DocumentManager to Admin carries their stored name and email."""
    env = _environment()
    env.container.seed(_workspace(
        documentManagers=[{"userId": "mgr", "displayName": "Manager One", "email": "mgr@example.test"}],
    ))
    _as_actor(env, "owner")
    _set_body(env, {"role": "Admin"})

    payload, status = env.handlers["api_update_public_member_role"](WS_ID, "mgr")

    assert status == 200
    stored = env.container.get(WS_ID, WS_ID)
    assert stored["documentManagers"] == []
    assert stored["admins"] == [{"userId": "mgr", "displayName": "Manager One", "email": "mgr@example.test"}]
    assert env.bumps == ["public_workspace_member_role_updated"]


def test_a_role_change_to_document_manager_keeps_the_member_name_and_email():
    """R5.7: demoting a dict Admin to DocumentManager carries their stored name and email."""
    env = _environment()
    env.container.seed(_workspace(
        admins=[{"userId": "adm", "displayName": "Admin Two", "email": "adm@example.test"}],
    ))
    _as_actor(env, "owner")
    _set_body(env, {"role": "DocumentManager"})

    payload, status = env.handlers["api_update_public_member_role"](WS_ID, "adm")

    assert status == 200
    stored = env.container.get(WS_ID, WS_ID)
    assert stored["admins"] == []
    assert stored["documentManagers"] == [
        {"userId": "adm", "displayName": "Admin Two", "email": "adm@example.test"}
    ]


def test_a_dict_admin_can_receive_ownership_and_the_old_owner_keeps_name_and_email():
    """R5.5 + R5.7 (decision 21): a dict Admin becomes owner; the old owner stays a
    DocumentManager with their name and email."""
    env = _environment()
    env.container.seed(_workspace(admins=[DICT_ADMIN]))
    _as_actor(env, "owner")
    _set_body(env, {"newOwnerId": "admin"})

    payload, status = env.handlers["api_transfer_public_ownership"](WS_ID)

    assert status == 200
    stored = env.container.get(WS_ID, WS_ID)
    assert stored["owner"] == {"userId": "admin", "displayName": "Admin One", "email": "admin@example.test"}
    assert stored["admins"] == []
    assert {"userId": "owner", "displayName": "Owner One", "email": "owner@example.test"} in stored["documentManagers"]
    assert env.bumps == ["public_workspace_ownership_transferred"]


def test_transfer_to_a_non_member_is_refused():
    """A transfer target that is neither admin nor manager is refused on the fresh copy."""
    env = _environment()
    env.container.seed(_workspace())
    _as_actor(env, "owner")
    _set_body(env, {"newOwnerId": "stranger"})

    payload, status = env.handlers["api_transfer_public_ownership"](WS_ID)

    assert status == 400
    stored = env.container.get(WS_ID, WS_ID)
    assert stored["owner"]["userId"] == "owner"
    assert env.bumps == []


# --------------------------------------------------------------------------- #
# R5.5 (second half): a legacy bare-string documentManagers/pendingDocumentManagers
# entry, which the role helper already tolerates, must break no route.
# --------------------------------------------------------------------------- #

STRING_DM = "legacy-mgr"  # a document manager stored as a bare id, not a dict


def test_no_document_manager_entry_is_read_by_a_userid_subscript():
    """Every documentManagers/pendingDocumentManagers read goes through the tolerant
    ``_member_user_id`` accessor, so a legacy bare-string entry never raises a
    ``TypeError``/500. A restored ``dm["userId"]`` or ``p["userId"]`` fails here."""
    tree = ast.parse((APP_DIR / ROUTE_FILE).read_text(encoding="utf-8"))
    offenders = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id in {"dm", "p"}
            and isinstance(node.slice, ast.Constant)
            and node.slice.value == "userId"
        ):
            offenders.append((node.value.id, node.lineno))
    assert offenders == [], f"bare-string-unsafe member reads remain: {offenders}"


def test_a_user_matching_a_string_document_manager_is_told_already_a_manager():
    """The request dedup compares a bare-string documentManagers entry correctly."""
    env = _environment()
    env.container.seed(_workspace(documentManagers=[STRING_DM]))
    _as_actor(env, STRING_DM)
    _set_body(env, {})

    payload, status = env.handlers["api_request_public_workspace"](WS_ID)

    assert status == 400
    assert payload == {"error": "Already a document manager"}
    assert env.container.get(WS_ID, WS_ID)["pendingDocumentManagers"] == []


def test_a_new_request_commits_with_a_string_document_manager_present():
    """A different user still requests cleanly when a bare-string manager is present."""
    env = _environment()
    env.container.seed(_workspace(documentManagers=[STRING_DM]))
    _as_actor(env, "fresh-user")
    _set_body(env, {})

    payload, status = env.handlers["api_request_public_workspace"](WS_ID)

    assert status == 201
    stored = env.container.get(WS_ID, WS_ID)
    assert [_id(p) for p in stored["pendingDocumentManagers"]] == ["fresh-user"]


def test_the_request_list_returns_with_a_string_pending_entry():
    """Listing requests does not read a bare-string pending entry by subscript."""
    env = _environment()
    env.container.seed(_workspace(
        admins=[DICT_ADMIN], pendingDocumentManagers=["pending-str"],
    ))
    _as_actor(env, "admin")
    _set_body(env, {})

    payload, status = env.handlers["api_view_public_requests"](WS_ID)

    assert status == 200
    assert payload == ["pending-str"]


def test_the_members_list_shows_a_string_document_manager_with_blank_name_and_email():
    """A bare-string document manager appears as a member with a blank name and email."""
    env = _environment()
    env.container.seed(_workspace(documentManagers=[STRING_DM]))
    _as_actor(env, "owner")
    _set_body(env, {})

    payload, status = env.handlers["api_list_public_members"](WS_ID)

    assert status == 200
    dm_rows = [m for m in payload if m["role"] == "DocumentManager"]
    assert dm_rows == [{"userId": STRING_DM, "displayName": "", "email": "", "role": "DocumentManager"}]


def test_a_string_document_manager_can_be_removed():
    """Removing a member drops a bare-string documentManagers entry."""
    env = _environment()
    env.container.seed(_workspace(documentManagers=[STRING_DM]))
    _as_actor(env, "owner")
    _set_body(env, {})

    payload, status = env.handlers["api_remove_public_member"](WS_ID, STRING_DM)

    assert status == 200
    assert env.container.get(WS_ID, WS_ID)["documentManagers"] == []


def test_a_string_pending_entry_can_be_approved():
    """Approving a bare-string pending request moves it into documentManagers."""
    env = _environment()
    env.container.seed(_workspace(admins=[DICT_ADMIN], pendingDocumentManagers=["pending-str"]))
    _as_actor(env, "admin")
    _set_body(env, {"action": "approve"})

    payload, status = env.handlers["api_handle_public_request"](WS_ID, "pending-str")

    assert status == 200
    stored = env.container.get(WS_ID, WS_ID)
    assert stored["pendingDocumentManagers"] == []
    assert [_id(dm) for dm in stored["documentManagers"]] == ["pending-str"]


def test_a_string_document_manager_can_be_promoted_to_admin():
    """R5.7 fallback: promoting a bare-string manager keeps a blank name and email."""
    env = _environment()
    env.container.seed(_workspace(documentManagers=[STRING_DM]))
    _as_actor(env, "owner")
    _set_body(env, {"role": "Admin"})

    payload, status = env.handlers["api_update_public_member_role"](WS_ID, STRING_DM)

    assert status == 200
    stored = env.container.get(WS_ID, WS_ID)
    assert stored["documentManagers"] == []
    assert stored["admins"] == [{"userId": STRING_DM, "displayName": "", "email": ""}]


def test_ownership_can_transfer_to_a_string_document_manager():
    """A bare-string manager can receive ownership; the old owner is kept (decision 21)."""
    env = _environment()
    env.container.seed(_workspace(documentManagers=[STRING_DM]))
    _as_actor(env, "owner")
    _set_body(env, {"newOwnerId": STRING_DM})

    payload, status = env.handlers["api_transfer_public_ownership"](WS_ID)

    assert status == 200
    stored = env.container.get(WS_ID, WS_ID)
    assert stored["owner"]["userId"] == STRING_DM
    assert {"userId": "owner", "displayName": "Owner One", "email": "owner@example.test"} in stored["documentManagers"]
    assert [_id(dm) for dm in stored["documentManagers"] if _id(dm) == STRING_DM] == []


def _id(entry):
    """The user id of a member entry stored as a dict or a bare string (test helper)."""
    return entry["userId"] if isinstance(entry, dict) else entry


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
