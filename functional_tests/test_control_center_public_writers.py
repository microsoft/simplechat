# test_control_center_public_writers.py
"""
Functional test for the Control Center's public-workspace writers on the etag guard.
Version: 0.261.174
Implemented in: 0.261.174

The Control Center metrics cache, the public-workspace status change, the bulk
action, the two admin add-member routes and the approved take and transfer
ownership actions each read the workspace, changed it and upserted that copy back.
A change landing in between (a membership change, a status change, another approval)
was undone, and a workspace deleted in between was recreated with its old
membership. The scheduled refresh did this for every workspace in turn, from copies
listed at its start.

Each now writes through ``update_public_workspace_document_with_etag_guard``,
deciding and applying its change on the copy it writes. This test runs them for real,
with the real guard over the etag-enforcing ``FakeContainer``, and pins, for each:

- the classic answer and its side effects: the metrics cache with no bootstrap bump,
  the status log, the activity record;
- a concurrent change is kept, and the decision (status unchanged, already a member,
  who owns the workspace) is made on the current copy;
- a deleted workspace is not recreated;
- a workspace that keeps changing gets the one shared conflict answer, with nothing
  written. An approval can't be approved again once it fails, so the approved actions
  answer with their own text, which asks for a new request.

Take and transfer ownership re-check the approval on the current copy. The request
applies when the recorded owner still owns the workspace. It has already been
applied, and succeeds without writing, when the requested new owner owns it. When
anyone else owns it, it's refused. The bulk action guards each workspace on its own,
so one conflict is recorded against that workspace and never aborts the rest.

Only the Cosmos containers, the chat-bootstrap bump and the activity logger are
fakes; no network is touched.
"""

import ast
import copy
import logging
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from azure.core import MatchConditions
from azure.cosmos import exceptions as cosmos_exceptions

from test_file_sync_concurrent_write_safety import FakeContainer
from test_support.agent_delegation import APP_ROOT, module_stub
from test_support.app_source import definitions as source_definitions
from test_support.versioning import assert_app_version_at_least


APP_DIR = Path(APP_ROOT)
SOURCE = "route_backend_control_center.py"
WORKSPACES_FILE = "functions_public_workspaces.py"
REGISTER = "register_route_backend_control_center"
WS = "public-1"

MODULE_LEVEL = {
    "enhance_public_workspace_with_activity", "_PublicChangeAnswer",
    "PUBLIC_OWNERSHIP_CHANGED_MESSAGE", "PUBLIC_NO_LONGER_EXISTS_MESSAGE",
    "PUBLIC_APPROVAL_CONFLICT_MESSAGE",
}
NESTED = {
    "api_update_public_workspace_status", "api_bulk_public_workspace_action",
    "api_admin_add_workspace_member", "api_admin_add_workspace_member_single",
    "_execute_take_workspace_ownership", "_execute_transfer_workspace_ownership",
}
WORKSPACES_DEFINITIONS = {
    "PUBLIC_DOCUMENT_WRITE_ATTEMPTS", "PublicWorkspaceDocumentWriteConflict",
    "PUBLIC_WORKSPACE_WRITE_CONFLICT_CODE", "PUBLIC_WORKSPACE_WRITE_CONFLICT_MESSAGE",
    "_stored_public_workspace_fields", "update_public_workspace_document_with_etag_guard",
}


assert_app_version_at_least("0.261.132")


# --------------------------------------------------------------------------- #
# Source-level AST pins: every Control Center public writer forwards through the
# guard and keeps no raw ``cosmos_public_workspaces_container`` upsert.
# --------------------------------------------------------------------------- #

def _owners_of_call(filename, callee):
    tree = ast.parse((APP_DIR / filename).read_text(encoding="utf-8"))
    owners = []

    def visit(node, owner):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit(child, child.name)
                continue
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name) and child.func.id == callee:
                owners.append(owner)
            visit(child, owner)

    visit(tree, None)
    return owners


def _raw_upsert_owners(filename):
    tree = ast.parse((APP_DIR / filename).read_text(encoding="utf-8"))
    raw = []

    def visit(node, owner):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit(child, child.name)
                continue
            if isinstance(child, ast.Call):
                func = child.func
                if (getattr(func, "attr", "") == "upsert_item"
                        and getattr(getattr(func, "value", None), "id", "") == "cosmos_public_workspaces_container"):
                    raw.append(owner)
            visit(child, owner)

    visit(tree, None)
    return raw


CONVERTED = {
    "enhance_public_workspace_with_activity", "api_update_public_workspace_status",
    "api_bulk_public_workspace_action", "api_admin_add_workspace_member",
    "api_admin_add_workspace_member_single", "_execute_take_workspace_ownership",
    "_execute_transfer_workspace_ownership",
}


def test_every_converted_writer_uses_the_public_guard():
    owners = set(_owners_of_call(SOURCE, "update_public_workspace_document_with_etag_guard"))
    for writer in CONVERTED:
        assert writer in owners, f"{writer} does not write through the public etag guard"


def test_no_converted_writer_keeps_a_raw_container_upsert():
    assert set(_raw_upsert_owners(SOURCE)) & CONVERTED == set()


# --------------------------------------------------------------------------- #
# Behaviour environment: the real guard over the etag-enforcing container.
# --------------------------------------------------------------------------- #

class _Request:
    def __init__(self, body=None):
        self._body = body

    def get_json(self, silent=False):
        return self._body


class PublicDocumentsMetrics:
    """The public documents container, as ``enhance_public_workspace_with_activity`` reads it."""

    def __init__(self):
        self.records = []

    def seed(self, workspace_id, pages, upload_date="2026-09-20T10:00:00"):
        self.records.append({
            "public_workspace_id": workspace_id, "type": "document_metadata",
            "number_of_pages": pages, "upload_date": upload_date,
        })

    def _rows(self, values):
        return [record for record in self.records
                if record.get("public_workspace_id") == values.get("@workspace_id")
                and record.get("type") == "document_metadata"]

    def query_items(self, query, parameters=None, enable_cross_partition_query=None, **kwargs):
        text = " ".join(str(query).split())
        values = {parameter["name"]: parameter["value"] for parameter in parameters or []}
        rows = self._rows(values)
        if text == ("SELECT VALUE COUNT(1) FROM c WHERE c.public_workspace_id = @workspace_id "
                    "AND c.type = 'document_metadata'"):
            return [len(rows)]
        if text == ("SELECT VALUE SUM(c.number_of_pages) FROM c WHERE c.public_workspace_id = @workspace_id "
                    "AND c.type = 'document_metadata'"):
            return [sum(record.get("number_of_pages", 0) for record in rows)]
        if text == ("SELECT c.upload_date FROM c WHERE c.public_workspace_id = @workspace_id "
                    "AND c.type = 'document_metadata'"):
            return [{"upload_date": record["upload_date"]} for record in rows]
        raise AssertionError(f"enhance sent a documents query this test does not model: {text}")


def _build_env():
    workspaces = FakeContainer(name="public", partition_field="id")
    activity_logs = FakeContainer(name="activity", partition_field="id")
    user_settings = FakeContainer(name="user_settings", partition_field="id")
    documents = PublicDocumentsMetrics()
    bumps, logs, status_logs = [], [], []

    # The real guard and role helper over the etag-enforcing container.
    ws_ns = {
        "copy": copy,
        "MatchConditions": MatchConditions,
        "exceptions": cosmos_exceptions,
        "cosmos_public_workspaces_container": workspaces,
        "bump_chat_bootstrap_global_cache_version": lambda *, reason: bumps.append(reason),
    }
    exec(compile(source_definitions(WORKSPACES_FILE, WORKSPACES_DEFINITIONS), WORKSPACES_FILE, "exec"), ws_ns)

    settings_stub = module_stub("functions_settings", get_settings=lambda: {"enable_enhanced_citations": False})
    activity_stub = module_stub(
        "functions_activity_logging",
        log_public_workspace_status_change=lambda **kwargs: status_logs.append(kwargs),
    )

    session = {"user": {"oid": "cc-admin", "preferred_username": "cc.admin@example.test",
                        "name": "Casey Control"}}

    class _Blueprint:
        def route(self, *args, **kwargs):
            return lambda function: function

    route_ns = {
        "bp": _Blueprint(),
        "swagger_route": lambda **kwargs: (lambda function: function),
        "get_auth_security": lambda: [{"sessionAuth": []}],
        "login_required": lambda function: function,
        "control_center_required": lambda *args, **kwargs: (lambda function: function),
        "jsonify": lambda payload=None: payload,
        "request": None,
        "session": session,
        "datetime": datetime, "timedelta": timedelta, "timezone": timezone,
        "uuid": uuid, "logging": logging,
        "cosmos_public_workspaces_container": workspaces,
        "cosmos_public_documents_container": documents,
        "cosmos_activity_logs_container": activity_logs,
        "cosmos_user_settings_container": user_settings,
        "update_public_workspace_document_with_etag_guard": ws_ns["update_public_workspace_document_with_etag_guard"],
        "PublicWorkspaceDocumentWriteConflict": ws_ns["PublicWorkspaceDocumentWriteConflict"],
        "PUBLIC_WORKSPACE_WRITE_CONFLICT_CODE": ws_ns["PUBLIC_WORKSPACE_WRITE_CONFLICT_CODE"],
        "PUBLIC_WORKSPACE_WRITE_CONFLICT_MESSAGE": ws_ns["PUBLIC_WORKSPACE_WRITE_CONFLICT_MESSAGE"],
        "bump_chat_bootstrap_global_cache_version": lambda *, reason: bumps.append(reason),
        "log_event": lambda message, *args, **kw: logs.append((message, kw.get("level"))),
        "debug_print": lambda *args, **kwargs: None,
        "delete_document": lambda *args, **kwargs: None,
        "delete_document_chunks": lambda *args, **kwargs: None,
    }
    exec(compile(source_definitions(SOURCE, MODULE_LEVEL, register=REGISTER, nested=NESTED),
                 SOURCE, "exec"), route_ns)

    return SimpleNamespace(
        workspaces=workspaces, activity_logs=activity_logs, user_settings=user_settings,
        documents=documents, bumps=bumps, logs=logs, status_logs=status_logs,
        session=session, ws_ns=ws_ns, route_ns=route_ns,
        settings_stub=settings_stub, activity_stub=activity_stub,
    )


@pytest.fixture
def env():
    env = _build_env()
    with patch.dict(sys.modules, {
        "functions_settings": env.settings_stub,
        "functions_activity_logging": env.activity_stub,
    }):
        yield env


def seed_workspace(env, *, workspace_id=WS, status="active", owner=None, admins=None,
                   document_managers=None, metrics=None):
    document = {
        "id": workspace_id, "name": "Public One", "status": status,
        "owner": owner if owner is not None else {
            "userId": "owner", "displayName": "Owner", "email": "owner@example.test"},
        "admins": copy.deepcopy(admins) if admins is not None else [
            {"userId": "admin", "displayName": "Admin", "email": "admin@example.test"}],
        "documentManagers": copy.deepcopy(document_managers) if document_managers is not None else [
            {"userId": "manager", "displayName": "Manager", "email": "manager@example.test"}],
    }
    if metrics is not None:
        document["metrics"] = copy.deepcopy(metrics)
    env.workspaces.seed(document)


def stored(env, workspace_id=WS):
    return env.workspaces.get(workspace_id, workspace_id)


def set_body(env, body):
    env.route_ns["request"] = _Request(body)


def concurrently(env, change, workspace_id=WS):
    def land():
        current = env.workspaces.get(workspace_id, workspace_id)
        change(current)
        env.workspaces.seed(current)
    env.workspaces.before_replace.append(land)


def keep_changing(env, workspace_id=WS):
    for index in range(env.ws_ns["PUBLIC_DOCUMENT_WRITE_ATTEMPTS"]):
        concurrently(env, lambda ws, index=index: ws.setdefault("admins", []).append(
            {"userId": f"late-{index}", "displayName": f"Late {index}", "email": f"late{index}@example.test"}),
            workspace_id=workspace_id)


def delete_before_write(env, workspace_id=WS):
    def land():
        env.workspaces.records.pop((workspace_id, workspace_id), None)
    env.workspaces.before_replace.append(land)


def replaces(env, workspace_id=WS):
    return [call for call in env.workspaces.calls if call == ("replace_item", workspace_id)]


def conflict_answer(env):
    return {
        "error": env.ws_ns["PUBLIC_WORKSPACE_WRITE_CONFLICT_MESSAGE"],
        "error_code": env.ws_ns["PUBLIC_WORKSPACE_WRITE_CONFLICT_CODE"],
    }


# --------------------------------------------------------------------------- #
# The metrics cache (D1)
# --------------------------------------------------------------------------- #

def enhance(env, force_refresh=True, workspace_id=WS):
    return env.route_ns["enhance_public_workspace_with_activity"](
        stored(env, workspace_id), force_refresh=force_refresh)


def test_metrics_are_cached_on_the_current_copy_without_a_bump(env):
    seed_workspace(env)
    env.documents.seed(WS, pages=4)
    env.documents.seed(WS, pages=6)

    enhanced = enhance(env)

    cached = stored(env)["metrics"]
    assert cached["document_metrics"]["total_documents"] == 2
    assert enhanced["document_count"] == 2
    assert env.bumps == []  # cache_reason=None, so no chat bootstrap bump
    assert replaces(env) == [("replace_item", WS)]


def test_metrics_keep_a_membership_change_that_landed_meanwhile(env):
    seed_workspace(env)
    env.documents.seed(WS, pages=2)
    concurrently(env, lambda ws: ws["admins"].append(
        {"userId": "late", "displayName": "Late", "email": "late@example.test"}))

    enhance(env)

    admin_ids = [a["userId"] for a in stored(env)["admins"]]
    assert "late" in admin_ids  # the guarded write kept the concurrent change
    assert "metrics" in stored(env)


def test_metrics_skip_a_workspace_deleted_before_the_write(env):
    seed_workspace(env)
    env.documents.seed(WS, pages=2)
    delete_before_write(env)

    enhance(env)  # returns without raising

    assert stored(env) is None  # not recreated


def test_metrics_leave_the_cache_untouched_when_the_workspace_keeps_changing(env):
    seed_workspace(env)
    env.documents.seed(WS, pages=2)
    keep_changing(env)

    enhance(env)  # the conflict is swallowed by enhance's cache-save guard

    assert "metrics" not in stored(env)
    assert env.bumps == []


# --------------------------------------------------------------------------- #
# The status change
# --------------------------------------------------------------------------- #

def put_status(env, status, reason="Quarterly review"):
    set_body(env, {"status": status, "reason": reason})
    return env.route_ns["api_update_public_workspace_status"](WS)


def test_status_change_writes_and_logs_once(env):
    seed_workspace(env, status="active")

    payload, code = put_status(env, "locked")

    assert code == 200
    assert payload["old_status"] == "active" and payload["new_status"] == "locked"
    assert stored(env)["status"] == "locked"
    assert env.bumps == ["public_workspace_status_updated"]
    assert len(env.status_logs) == 1 and env.status_logs[0]["new_status"] == "locked"


def test_status_change_logs_the_status_actually_replaced(env):
    seed_workspace(env, status="active")
    concurrently(env, lambda ws: ws.update(status="upload_disabled"))

    payload, code = put_status(env, "locked")

    assert code == 200
    assert payload["old_status"] == "upload_disabled"  # decided on the copy written
    assert stored(env)["status"] == "locked"


def test_status_unchanged_writes_nothing(env):
    seed_workspace(env, status="locked")

    payload, code = put_status(env, "locked")

    assert code == 200 and payload == {"message": "Status unchanged", "status": "locked"}
    assert replaces(env) == []
    assert env.bumps == [] and env.status_logs == []


def test_status_change_on_a_deleted_workspace_is_404(env):
    seed_workspace(env, status="active")
    delete_before_write(env)

    payload, code = put_status(env, "locked")

    assert code == 404 and payload == {"error": "Public workspace not found"}


def test_status_change_conflict_answers_409_with_nothing_written(env):
    seed_workspace(env, status="active")
    keep_changing(env)

    payload, code = put_status(env, "locked")

    assert code == 409 and payload == conflict_answer(env)
    assert stored(env)["status"] == "active"
    assert env.status_logs == []


# --------------------------------------------------------------------------- #
# The add-member routes
# --------------------------------------------------------------------------- #

def add_member(env, user_id="newcomer", role="user", source="csv"):
    set_body(env, {"userId": user_id, "displayName": f"Name {user_id}",
                   "email": f"{user_id}@example.test", "role": role, "source": source})
    return env.route_ns["api_admin_add_workspace_member"](WS)


def add_member_single(env, user_id="newcomer", role="document_manager"):
    set_body(env, {"userId": user_id, "displayName": f"Name {user_id}",
                   "email": f"{user_id}@example.test", "role": role})
    return env.route_ns["api_admin_add_workspace_member_single"](WS)


def test_add_member_adds_to_the_current_copy(env):
    seed_workspace(env)
    concurrently(env, lambda ws: ws["documentManagers"].append(
        {"userId": "late-dm", "displayName": "Late", "email": "late@example.test"}))

    payload, code = add_member(env, user_id="newcomer", role="admin")

    assert code == 200 and payload["skipped"] is False
    admin_ids = [a["userId"] for a in stored(env)["admins"]]
    dm_ids = [d["userId"] for d in stored(env)["documentManagers"]]
    assert "newcomer" in admin_ids
    assert "late-dm" in dm_ids  # the concurrent change was kept


def test_add_member_already_present_skips_with_200(env):
    seed_workspace(env)

    payload, code = add_member(env, user_id="admin", role="admin")

    assert code == 200 and payload["skipped"] is True
    assert replaces(env) == []


def test_add_member_decides_already_present_on_the_current_copy(env):
    seed_workspace(env)
    concurrently(env, lambda ws: ws["admins"].append(
        {"userId": "newcomer", "displayName": "Name", "email": "newcomer@example.test"}))

    payload, code = add_member(env, user_id="newcomer", role="admin")

    # the writer's own read saw no such member, but the guard re-read did
    assert code == 200 and payload["skipped"] is True


def test_add_member_conflict_answers_409(env):
    seed_workspace(env)
    keep_changing(env)

    payload, code = add_member(env, user_id="newcomer", role="admin")

    assert code == 409 and payload == conflict_answer(env)


def test_add_member_single_already_present_is_400(env):
    seed_workspace(env)

    payload, code = add_member_single(env, user_id="manager", role="document_manager")

    assert code == 400 and "already exists" in payload["error"]
    assert replaces(env) == []


def test_add_member_single_adds_and_answers_success(env):
    seed_workspace(env)

    payload, code = add_member_single(env, user_id="newcomer", role="admin")

    assert code == 200 and payload["success"] is True
    admin_ids = [a["userId"] for a in stored(env)["admins"]]
    assert "newcomer" in admin_ids


# --------------------------------------------------------------------------- #
# The bulk action
# --------------------------------------------------------------------------- #

def bulk(env, workspace_ids, action="lock", reason="Sweep"):
    set_body(env, {"workspace_ids": workspace_ids, "action": action, "reason": reason})
    return env.route_ns["api_bulk_public_workspace_action"]()


def test_bulk_status_change_records_each_workspace(env):
    seed_workspace(env, workspace_id="public-1", status="active")
    seed_workspace(env, workspace_id="public-2", status="active")

    payload, code = bulk(env, ["public-1", "public-2"], action="lock")

    assert code == 200
    assert {entry["workspace_id"] for entry in payload["successful"]} == {"public-1", "public-2"}
    assert payload["failed"] == []
    assert stored(env, "public-1")["status"] == "locked"
    assert stored(env, "public-2")["status"] == "locked"


def test_bulk_one_conflict_does_not_abort_the_rest(env):
    seed_workspace(env, workspace_id="public-1", status="active")
    seed_workspace(env, workspace_id="public-2", status="active")
    keep_changing(env, workspace_id="public-1")

    payload, code = bulk(env, ["public-1", "public-2"], action="lock")

    assert code == 200
    assert [entry["workspace_id"] for entry in payload["successful"]] == ["public-2"]
    assert [entry["workspace_id"] for entry in payload["failed"]] == ["public-1"]
    assert stored(env, "public-2")["status"] == "locked"
    assert stored(env, "public-1")["status"] == "active"


# --------------------------------------------------------------------------- #
# Approved take and transfer ownership (D2)
# --------------------------------------------------------------------------- #

def take_ownership(env, requester_id="requester", recorded_owner_id="owner"):
    approval = {
        "id": "approval-1", "workspace_id": WS,
        "requester_id": requester_id, "requester_email": f"{requester_id}@example.test",
        "requester_name": f"Name {requester_id}",
        "metadata": {"old_owner_id": recorded_owner_id},
    }
    return env.route_ns["_execute_take_workspace_ownership"](
        approval, "executor", "executor@example.test", "Executor")


def transfer_ownership(env, new_owner_id="successor", recorded_owner_id="owner"):
    approval = {
        "id": "approval-2", "workspace_id": WS,
        "requester_id": "owner", "requester_email": "owner@example.test",
        "metadata": {
            "old_owner_id": recorded_owner_id,
            "new_owner_id": new_owner_id, "new_owner_email": f"{new_owner_id}@example.test",
            "new_owner_name": f"Name {new_owner_id}",
        },
    }
    return env.route_ns["_execute_transfer_workspace_ownership"](
        approval, "executor", "executor@example.test", "Executor")


def test_take_ownership_applies_when_the_recorded_owner_still_owns_it(env):
    seed_workspace(env, owner={"userId": "owner", "displayName": "Owner", "email": "owner@example.test"})

    result = take_ownership(env, requester_id="requester", recorded_owner_id="owner")

    assert result["success"] is True
    assert stored(env)["owner"]["userId"] == "requester"
    old_ids = [a["userId"] for a in stored(env)["admins"]]
    assert "owner" in old_ids  # the old owner is demoted to admin


def test_take_ownership_is_idempotent_when_requester_already_owns_it(env):
    seed_workspace(env, owner={"userId": "requester", "displayName": "Req", "email": "requester@example.test"})

    result = take_ownership(env, requester_id="requester", recorded_owner_id="owner")

    assert result["success"] is True
    assert replaces(env) == []  # nothing written


def test_take_ownership_refused_when_someone_else_owns_it(env):
    seed_workspace(env, owner={"userId": "intruder", "displayName": "X", "email": "intruder@example.test"})

    result = take_ownership(env, requester_id="requester", recorded_owner_id="owner")

    assert result == {"success": False, "message": env.route_ns["PUBLIC_OWNERSHIP_CHANGED_MESSAGE"]}
    assert replaces(env) == []


def test_take_ownership_conflict_asks_for_a_new_request(env):
    seed_workspace(env, owner={"userId": "owner", "displayName": "Owner", "email": "owner@example.test"})
    keep_changing(env)

    result = take_ownership(env, requester_id="requester", recorded_owner_id="owner")

    assert result == {"success": False, "message": env.route_ns["PUBLIC_APPROVAL_CONFLICT_MESSAGE"]}


def test_take_ownership_on_a_deleted_workspace_reports_it(env):
    seed_workspace(env, owner={"userId": "owner", "displayName": "Owner", "email": "owner@example.test"})
    delete_before_write(env)

    result = take_ownership(env, requester_id="requester", recorded_owner_id="owner")

    assert result == {"success": False, "message": env.route_ns["PUBLIC_NO_LONGER_EXISTS_MESSAGE"]}


def test_transfer_ownership_applies_when_the_recorded_owner_still_owns_it(env):
    seed_workspace(env, owner={"userId": "owner", "displayName": "Owner", "email": "owner@example.test"})

    result = transfer_ownership(env, new_owner_id="successor", recorded_owner_id="owner")

    assert result["success"] is True
    assert stored(env)["owner"]["userId"] == "successor"


def test_transfer_ownership_is_idempotent_when_new_owner_already_owns_it(env):
    seed_workspace(env, owner={"userId": "successor", "displayName": "S", "email": "successor@example.test"})

    result = transfer_ownership(env, new_owner_id="successor", recorded_owner_id="owner")

    assert result["success"] is True
    assert replaces(env) == []


def test_transfer_ownership_refused_when_someone_else_owns_it(env):
    seed_workspace(env, owner={"userId": "intruder", "displayName": "X", "email": "intruder@example.test"})

    result = transfer_ownership(env, new_owner_id="successor", recorded_owner_id="owner")

    assert result == {"success": False, "message": env.route_ns["PUBLIC_OWNERSHIP_CHANGED_MESSAGE"]}


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
