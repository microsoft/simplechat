# test_public_membership_apis.py
"""
Functional tests for the immutable-target native public workspace membership APIs.
Version: 0.261.177
Implemented in: 0.261.177

The real public membership logic module, its route registrar, the pure policy and
disclosure projectors, and the real ``get_user_role_in_public_workspace`` resolver run
in an isolated Flask app. The public workspace document store is an in-memory seam and
its conditional-write guard is a faithful local stand-in; Cosmos, authentication
configuration, notifications, and telemetry are local test seams; network access and
Microsoft Graph are prohibited. The workspace identity is always taken from the path,
so a stale active-workspace preference can never redirect or widen a write.
"""

import socket
import sys
from copy import deepcopy
from functools import wraps
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import importlib.util

import pytest
from flask import Blueprint, Flask, jsonify, request, session

from test_support.agent_delegation import APP_ROOT, execute_functions, module_stub
from test_support.versioning import assert_app_version_at_least


MEMBERS_PATH = "/api/public-workspaces/ws-a/membership/members"
REQUESTS_PATH = "/api/public-workspaces/ws-a/membership/requests"
OWNER_PATH = "/api/public-workspaces/ws-a/membership/owner"

OWNER = "owner-1"
ADMIN = "admin-1"
LEGACY_ADMIN = "legacy-admin"
MANAGER = "dm-1"
PENDING = "pending-1"
OUTSIDER = "outsider-1"


class MissingRecord(Exception):
    status_code = 404


class PublicWorkspaceDocumentWriteConflict(RuntimeError):
    """Local stand-in matching the module's imported conflict class."""


def workspace(workspace_id, status="active"):
    return {
        "id": workspace_id,
        "_etag": f"etag-{workspace_id}-0",
        "name": f"Name of {workspace_id}",
        "status": status,
        "owner": {"userId": OWNER, "displayName": "Olivia Owner", "email": "olivia@example.com"},
        "admins": [
            {"userId": ADMIN, "displayName": "Adam Admin", "email": "adam@example.com"},
            LEGACY_ADMIN,
        ],
        "documentManagers": [
            {"userId": MANAGER, "displayName": "Mona Manager", "email": "mona@example.com"},
        ],
        "pendingDocumentManagers": [
            {"userId": PENDING, "displayName": "Percy Pending", "email": "percy@example.com"},
        ],
    }


def load_real_module(monkeypatch, name):
    spec = importlib.util.spec_from_file_location(name, APP_ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def environment(monkeypatch):
    assert_app_version_at_least("0.261.132")
    settings = {"enable_public_workspaces": True}
    with monkeypatch.context() as scoped:
        scoped.syspath_prepend(str(APP_ROOT))
        network = Mock(side_effect=AssertionError("No network access in membership API tests."))
        scoped.setattr(socket, "create_connection", network)
        scoped.setattr(socket.socket, "connect", network)

        store = {
            "ws-a": workspace("ws-a"),
            "locked-ws": workspace("locked-ws", status="locked"),
            "inactive-ws": workspace("inactive-ws", status="inactive"),
            "haunted-ws": workspace("haunted-ws", status="haunted"),
        }
        cache_reasons = []
        notifications = []
        activity_records = []
        conflict = {"raise": False}
        audit_fault = {"raise": False}

        def find_public_workspace_by_id(workspace_id):
            found = store.get(workspace_id)
            return deepcopy(found) if found is not None else None

        def guard(ws_id, apply_changes, *, cache_reason, attempts=3):
            if conflict["raise"]:
                raise PublicWorkspaceDocumentWriteConflict("kept changing")
            current = store.get(ws_id)
            if current is None:
                return None
            result = apply_changes(deepcopy(current))
            stored = deepcopy(result)
            stored["_etag"] = f"etag-{ws_id}-{uuid4()}"
            store[ws_id] = stored
            if cache_reason is not None:
                cache_reasons.append(cache_reason)
            return deepcopy(stored)

        role_namespace = {}
        execute_functions(
            "functions_public_workspaces.py",
            {"get_user_role_in_public_workspace"},
            role_namespace,
        )
        role_reader = Mock(side_effect=role_namespace["get_user_role_in_public_workspace"])

        graph_guard = Mock(side_effect=AssertionError("A membership read or write must never call Graph."))
        env = SimpleNamespace(
            settings=settings, store=store, cache_reasons=cache_reasons,
            notifications=notifications, conflict=conflict, network=network,
            role_reader=role_reader, graph=graph_guard, activity_records=activity_records,
            audit_fault=audit_fault,
        )

        scoped.setitem(sys.modules, "functions_appinsights", module_stub(
            "functions_appinsights", log_event=Mock(),
        ))
        scoped.setitem(sys.modules, "functions_notifications", module_stub(
            "functions_notifications",
            create_notification=lambda **kwargs: notifications.append(kwargs),
        ))
        scoped.setitem(sys.modules, "functions_msgraph", module_stub(
            "functions_msgraph", get_user_by_id=graph_guard,
        ))

        settings_namespace = {"wraps": wraps, "get_settings": lambda: settings, "jsonify": jsonify}
        execute_functions("functions_settings.py", {"enabled_required"}, settings_namespace)
        settings_module = module_stub(
            "functions_settings",
            get_settings=lambda: settings,
            enabled_required=settings_namespace["enabled_required"],
        )
        scoped.setitem(sys.modules, "functions_settings", settings_module)

        auth_namespace = {
            "wraps": wraps, "session": session, "request": request, "jsonify": jsonify,
            "debug_print": Mock(), "check_user_access_status": Mock(return_value=(True, None)),
        }
        execute_functions("functions_authentication.py", {
            "login_required", "user_required", "user_required_blueprint", "apply_blueprint_auth",
            "get_current_user_id", "get_current_user_info",
        }, auth_namespace)
        auth = module_stub(
            "functions_authentication",
            login_required=auth_namespace["login_required"],
            user_required=auth_namespace["user_required"],
            user_required_blueprint=auth_namespace["user_required_blueprint"],
            get_current_user_id=auth_namespace["get_current_user_id"],
            get_current_user_info=auth_namespace["get_current_user_info"],
        )
        scoped.setitem(sys.modules, "functions_authentication", auth)

        scoped.setitem(sys.modules, "swagger_wrapper", module_stub(
            "swagger_wrapper",
            swagger_route=lambda **_kwargs: (lambda function: function),
            get_auth_security=lambda: [{"sessionAuth": []}],
        ))

        scoped.setitem(sys.modules, "functions_public_workspaces", module_stub(
            "functions_public_workspaces",
            PUBLIC_WORKSPACE_WRITE_CONFLICT_CODE="public_workspace_write_conflict",
            PUBLIC_WORKSPACE_WRITE_CONFLICT_MESSAGE="The public workspace changed while your request was being saved. Try again.",
            PublicWorkspaceDocumentWriteConflict=PublicWorkspaceDocumentWriteConflict,
            find_public_workspace_by_id=find_public_workspace_by_id,
            get_user_role_in_public_workspace=role_reader,
            update_public_workspace_document_with_etag_guard=guard,
        ))

        def record_activity(body):
            if audit_fault["raise"]:
                raise RuntimeError("activity log unavailable")
            activity_records.append(deepcopy(body))

        activity_container = SimpleNamespace(create_item=record_activity)
        scoped.setitem(sys.modules, "config", module_stub(
            "config", cosmos_activity_logs_container=activity_container,
        ))

        load_real_module(scoped, "functions_public_membership_policy")
        load_real_module(scoped, "functions_public_membership_disclosure")
        load_real_module(scoped, "functions_public_membership_audit")
        load_real_module(scoped, "functions_public_membership")
        route = load_real_module(scoped, "route_backend_public_membership")

        app = Flask("public_membership_contract")
        app.config.update(TESTING=True, SECRET_KEY="test-only-session-key")
        blueprint = Blueprint("backend_public_membership", __name__)
        blueprint.before_request(auth.user_required_blueprint())
        route.register_route_backend_public_membership(blueprint)
        app.register_blueprint(blueprint)
        env.client = app.test_client()
        env.route = route
        login(env, OWNER)
        yield env
        network.assert_not_called()
        graph_guard.assert_not_called()


def login(environment, oid, name="Signed In", email=None):
    with environment.client.session_transaction() as state:
        state["user"] = {
            "oid": oid,
            "name": name,
            "preferred_username": email or f"{oid}@example.com",
            "roles": ["User"],
        }


def emails_in(members):
    return {row["userId"]: row["email"] for row in members}


# ---------------------------------------------------------------------------
# Reads and authorization
# ---------------------------------------------------------------------------

def test_owner_lists_members_sorted_with_management_hint(environment):
    response = environment.client.get(MEMBERS_PATH)
    assert response.status_code == 200
    payload = response.get_json()
    assert response.headers["Cache-Control"] == "no-store"
    roles = [row["role"] for row in payload["members"]]
    assert roles == ["Owner", "Admin", "Admin", "DocumentManager"]
    hint = payload["membership_management"]
    assert "transfer_ownership" in hint["operations"]
    assert "add_member" in hint["operations"]
    assert "review_requests" in hint["operations"]


def test_owner_and_admin_see_member_emails(environment):
    login(environment, ADMIN)
    payload = environment.client.get(MEMBERS_PATH).get_json()
    assert emails_in(payload["members"])[MANAGER] == "mona@example.com"


def test_document_manager_viewer_never_sees_emails(environment):
    login(environment, MANAGER)
    response = environment.client.get(MEMBERS_PATH)
    assert response.status_code == 200
    payload = response.get_json()
    assert all(row["email"] == "" for row in payload["members"])
    assert {row["userId"] for row in payload["members"]} == {OWNER, ADMIN, LEGACY_ADMIN, MANAGER}


def test_legacy_bare_string_member_shows_blank_name_and_email_without_graph(environment):
    payload = environment.client.get(MEMBERS_PATH).get_json()
    legacy = next(row for row in payload["members"] if row["userId"] == LEGACY_ADMIN)
    assert legacy["displayName"] == "" and legacy["email"] == ""
    assert legacy["role"] == "Admin"


def test_non_member_cannot_list_members(environment):
    login(environment, OUTSIDER)
    response = environment.client.get(MEMBERS_PATH)
    assert response.status_code == 403
    assert response.get_json()["error_code"] == "not_a_member"


def test_unknown_workspace_is_not_found(environment):
    response = environment.client.get("/api/public-workspaces/no-such-ws/membership/members")
    assert response.status_code == 404
    assert response.get_json()["error_code"] == "workspace_not_found"


def test_unknown_query_parameter_is_rejected(environment):
    response = environment.client.get(MEMBERS_PATH, query_string={"surprise": "1"})
    assert response.status_code == 400
    assert response.get_json()["error_code"] == "invalid_request"


def test_role_filter_limits_the_list(environment):
    payload = environment.client.get(MEMBERS_PATH, query_string={"role": "Admin"}).get_json()
    assert {row["userId"] for row in payload["members"]} == {ADMIN, LEGACY_ADMIN}
    assert payload["total_count"] == 2


# ---------------------------------------------------------------------------
# Add member
# ---------------------------------------------------------------------------

def test_owner_adds_document_manager_and_notifies(environment):
    response = environment.client.post(MEMBERS_PATH, json={
        "userId": OUTSIDER, "displayName": "Nia New", "email": "nia@example.com", "role": "DocumentManager",
    })
    assert response.status_code == 201
    member = response.get_json()["member"]
    assert member["userId"] == OUTSIDER and member["role"] == "DocumentManager"
    assert "public_workspace_member_added" in environment.cache_reasons
    assert any(note["user_id"] == OUTSIDER for note in environment.notifications)
    stored_ids = {entry["userId"] for entry in environment.store["ws-a"]["documentManagers"]}
    assert OUTSIDER in stored_ids


def test_adding_an_existing_member_conflicts(environment):
    response = environment.client.post(MEMBERS_PATH, json={"userId": ADMIN, "role": "Admin"})
    assert response.status_code == 409
    assert response.get_json()["error_code"] == "already_member"


def test_add_member_rejects_an_unknown_role(environment):
    response = environment.client.post(MEMBERS_PATH, json={"userId": OUTSIDER, "role": "Owner"})
    assert response.status_code == 400


def test_add_member_rejects_extra_fields(environment):
    response = environment.client.post(MEMBERS_PATH, json={
        "userId": OUTSIDER, "role": "Admin", "smuggled": "x",
    })
    assert response.status_code == 400


def test_add_member_rejects_query_parameters(environment):
    response = environment.client.post(
        MEMBERS_PATH, query_string={"role": "Admin"}, json={"userId": OUTSIDER, "role": "Admin"},
    )
    assert response.status_code == 400


def test_add_member_denied_on_inactive_workspace(environment):
    response = environment.client.post(
        "/api/public-workspaces/inactive-ws/membership/members",
        json={"userId": OUTSIDER, "role": "Admin"},
    )
    assert response.status_code == 403
    assert response.get_json()["error_code"] == "public_status_unavailable"


def test_add_member_denied_on_locked_workspace(environment):
    response = environment.client.post(
        "/api/public-workspaces/locked-ws/membership/members",
        json={"userId": OUTSIDER, "role": "Admin"},
    )
    assert response.status_code == 403
    assert response.get_json()["error_code"] == "public_status_unavailable"


def test_document_manager_cannot_add_members(environment):
    login(environment, MANAGER)
    response = environment.client.post(MEMBERS_PATH, json={"userId": OUTSIDER, "role": "Admin"})
    assert response.status_code == 403
    assert response.get_json()["error_code"] == "membership_permission"


def test_add_member_normalizes_legacy_string_entries_on_write(environment):
    environment.client.post(MEMBERS_PATH, json={"userId": OUTSIDER, "role": "Admin"})
    admins = environment.store["ws-a"]["admins"]
    assert all(isinstance(entry, dict) for entry in admins)
    assert any(entry["userId"] == LEGACY_ADMIN for entry in admins)


def test_add_member_reports_a_write_conflict(environment):
    environment.conflict["raise"] = True
    response = environment.client.post(MEMBERS_PATH, json={"userId": OUTSIDER, "role": "Admin"})
    assert response.status_code == 409
    assert response.get_json()["error_code"] == "public_workspace_write_conflict"


# ---------------------------------------------------------------------------
# Change role
# ---------------------------------------------------------------------------

def test_owner_promotes_manager_carrying_name_and_email(environment):
    response = environment.client.patch(
        f"{MEMBERS_PATH}/{MANAGER}", json={"role": "Admin"},
    )
    assert response.status_code == 200
    assert response.get_json()["changed"] is True
    promoted = next(entry for entry in environment.store["ws-a"]["admins"] if entry["userId"] == MANAGER)
    assert promoted["displayName"] == "Mona Manager" and promoted["email"] == "mona@example.com"


def test_change_role_to_current_role_writes_nothing(environment):
    before = len(environment.cache_reasons)
    response = environment.client.patch(f"{MEMBERS_PATH}/{ADMIN}", json={"role": "Admin"})
    assert response.status_code == 200
    assert response.get_json()["changed"] is False
    assert len(environment.cache_reasons) == before


def test_change_role_of_owner_conflicts(environment):
    response = environment.client.patch(f"{MEMBERS_PATH}/{OWNER}", json={"role": "Admin"})
    assert response.status_code == 409
    assert response.get_json()["error_code"] == "owner_target"


def test_change_role_of_non_member_is_not_found(environment):
    response = environment.client.patch(f"{MEMBERS_PATH}/{OUTSIDER}", json={"role": "Admin"})
    assert response.status_code == 404
    assert response.get_json()["error_code"] == "member_not_found"


def test_change_role_denied_on_inactive_workspace(environment):
    response = environment.client.patch(
        f"/api/public-workspaces/inactive-ws/membership/members/{MANAGER}", json={"role": "Admin"},
    )
    assert response.status_code == 403
    assert response.get_json()["error_code"] == "public_status_unavailable"


# ---------------------------------------------------------------------------
# Remove member
# ---------------------------------------------------------------------------

def test_owner_removes_a_member(environment):
    response = environment.client.delete(f"{MEMBERS_PATH}/{MANAGER}")
    assert response.status_code == 200
    assert response.get_json()["userId"] == MANAGER
    remaining = {entry["userId"] for entry in environment.store["ws-a"]["documentManagers"]}
    assert MANAGER not in remaining


def test_self_removal_is_refused_there_is_no_leave(environment):
    response = environment.client.delete(f"{MEMBERS_PATH}/{OWNER}")
    assert response.status_code == 403
    assert response.get_json()["error_code"] == "cannot_leave"


def test_removing_the_owner_conflicts(environment):
    login(environment, ADMIN)
    response = environment.client.delete(f"{MEMBERS_PATH}/{OWNER}")
    assert response.status_code == 409
    assert response.get_json()["error_code"] == "owner_target"


def test_removing_a_non_member_is_not_found(environment):
    response = environment.client.delete(f"{MEMBERS_PATH}/{OUTSIDER}")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------

def test_owner_lists_pending_requests(environment):
    payload = environment.client.get(REQUESTS_PATH).get_json()
    assert [row["userId"] for row in payload["requests"]] == [PENDING]


def test_document_manager_cannot_list_requests(environment):
    login(environment, MANAGER)
    response = environment.client.get(REQUESTS_PATH)
    assert response.status_code == 403
    assert response.get_json()["error_code"] == "membership_permission"


def test_owner_approves_a_request(environment):
    response = environment.client.post(f"{REQUESTS_PATH}/{PENDING}/approve")
    assert response.status_code == 200
    manager_ids = {entry["userId"] for entry in environment.store["ws-a"]["documentManagers"]}
    assert PENDING in manager_ids
    assert not environment.store["ws-a"]["pendingDocumentManagers"]
    assert "public_workspace_member_request_approved" in environment.cache_reasons


def test_approving_without_a_pending_request_conflicts(environment):
    response = environment.client.post(f"{REQUESTS_PATH}/{OUTSIDER}/approve")
    assert response.status_code == 409
    assert response.get_json()["error_code"] == "no_pending_request"


def test_owner_rejects_a_request_without_a_cache_bump(environment):
    before = list(environment.cache_reasons)
    response = environment.client.post(f"{REQUESTS_PATH}/{PENDING}/reject")
    assert response.status_code == 200
    assert not environment.store["ws-a"]["pendingDocumentManagers"]
    assert environment.cache_reasons == before


def test_rejecting_without_a_pending_request_conflicts(environment):
    response = environment.client.post(f"{REQUESTS_PATH}/{OUTSIDER}/reject")
    assert response.status_code == 409


# ---------------------------------------------------------------------------
# Transfer ownership
# ---------------------------------------------------------------------------

def test_owner_transfers_ownership_and_demotes_the_old_owner(environment):
    response = environment.client.put(OWNER_PATH, json={"userId": ADMIN})
    assert response.status_code == 200
    assert response.get_json()["changed"] is True
    stored = environment.store["ws-a"]
    assert stored["owner"]["userId"] == ADMIN
    demoted = next(entry for entry in stored["documentManagers"] if entry["userId"] == OWNER)
    assert demoted["displayName"] == "Olivia Owner" and demoted["email"] == "olivia@example.com"


def test_transfer_to_a_non_member_is_not_found(environment):
    response = environment.client.put(OWNER_PATH, json={"userId": OUTSIDER})
    assert response.status_code == 404
    assert response.get_json()["error_code"] == "member_not_found"


def test_transfer_by_a_non_owner_is_refused(environment):
    login(environment, ADMIN)
    response = environment.client.put(OWNER_PATH, json={"userId": MANAGER})
    assert response.status_code == 403
    assert response.get_json()["error_code"] == "owner_only"


def test_transfer_to_the_current_owner_writes_nothing(environment):
    before = len(environment.cache_reasons)
    response = environment.client.put(OWNER_PATH, json={"userId": OWNER})
    assert response.status_code == 200
    assert response.get_json()["changed"] is False
    assert len(environment.cache_reasons) == before


# ---------------------------------------------------------------------------
# Feature gate
# ---------------------------------------------------------------------------

def test_routes_are_gated_by_the_public_workspaces_feature_flag(environment):
    environment.settings["enable_public_workspaces"] = False
    response = environment.client.get(MEMBERS_PATH)
    assert response.status_code == 400
    assert "disabled" in response.get_json()["error"].casefold()


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------

def _records_of(environment, activity_type):
    return [r for r in environment.activity_records if r.get("activity_type") == activity_type]


def test_adding_a_member_writes_one_audit_record(environment):
    response = environment.client.post(MEMBERS_PATH, json={
        "userId": OUTSIDER, "displayName": "Nia New", "email": "nia@example.com", "role": "DocumentManager",
    })
    assert response.status_code == 201
    records = _records_of(environment, "public_add_member_directly")
    assert len(records) == 1
    record = records[0]
    assert record["public_workspace_id"] == "ws-a"
    assert record["added_by_user_id"] == OWNER and record["added_by_role"] == "Owner"
    assert record["member_user_id"] == OUTSIDER and record["member_role"] == "DocumentManager"
    assert record["member_name"] == "Nia New" and record["member_email"] == "nia@example.com"


def test_changing_a_role_writes_one_audit_record_with_both_roles(environment):
    response = environment.client.patch(f"{MEMBERS_PATH}/{MANAGER}", json={"role": "Admin"})
    assert response.status_code == 200
    records = _records_of(environment, "public_update_member_role")
    assert len(records) == 1
    record = records[0]
    assert record["type"] == "public_workspace_member_role_changed"
    assert record["old_role"] == "DocumentManager" and record["new_role"] == "Admin"
    assert record["member_user_id"] == MANAGER
    assert record["member_name"] == "Mona Manager" and record["member_email"] == "mona@example.com"
    assert record["changed_by_user_id"] == OWNER and record["changed_by_role"] == "Owner"


def test_an_unchanged_role_writes_no_audit_record(environment):
    response = environment.client.patch(f"{MEMBERS_PATH}/{ADMIN}", json={"role": "Admin"})
    assert response.status_code == 200 and response.get_json()["changed"] is False
    assert _records_of(environment, "public_update_member_role") == []


def test_removing_a_member_writes_one_audit_record(environment):
    response = environment.client.delete(f"{MEMBERS_PATH}/{MANAGER}")
    assert response.status_code == 200
    records = _records_of(environment, "public_member_removed")
    assert len(records) == 1
    record = records[0]
    assert record["removed_by"]["user_id"] == OWNER and record["removed_by"]["role"] == "Owner"
    assert record["removed_member"]["user_id"] == MANAGER
    assert record["removed_member"]["name"] == "Mona Manager"
    assert record["removed_member"]["email"] == "mona@example.com"
    assert record["public_workspace"]["public_workspace_id"] == "ws-a"


def test_approve_reject_and_transfer_write_no_audit_records(environment):
    environment.client.post(f"{REQUESTS_PATH}/{PENDING}/approve")
    environment.client.put(OWNER_PATH, json={"userId": ADMIN})
    login(environment, ADMIN)
    environment.client.post(MEMBERS_PATH, json={"userId": OUTSIDER, "role": "DocumentManager"})
    # Approve and transfer write no audit record; only the final add does.
    assert _records_of(environment, "public_add_member_directly")
    assert all(
        r.get("activity_type") == "public_add_member_directly"
        for r in environment.activity_records
    )


def test_a_failed_audit_write_never_fails_a_committed_change(environment):
    environment.audit_fault["raise"] = True
    response = environment.client.post(MEMBERS_PATH, json={"userId": OUTSIDER, "role": "Admin"})
    assert response.status_code == 201
    stored_ids = {entry["userId"] for entry in environment.store["ws-a"]["admins"]}
    assert OUTSIDER in stored_ids
    assert environment.activity_records == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
