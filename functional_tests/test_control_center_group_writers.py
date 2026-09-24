# test_control_center_group_writers.py
"""
Functional test for the Control Center's group-document writers on the etag guard.
Version: 0.261.160
Implemented in: 0.261.160

The Control Center metrics cache, the group status change, the admin add-member
route and the approved take and transfer ownership actions each read the group,
changed it and upserted that copy back. A change landing in between (a membership
change, a status change, another approval) was undone, and a group deleted in between
was recreated with its old membership. The scheduled daily refresh did this for every
group, one after another, from copies listed at its start.

Each now writes through ``update_group_document_with_etag_guard``, deciding and
applying its change on the copy it writes. This test runs them for real in
``test_support/control_center_group_harness.py`` and pins, for each:

- the classic answer and its side effects, once, after the commit: the cache reason,
  the activity record and, for the approved actions, the approval's final state;
- a concurrent change is kept, and the decision (status unchanged, already a member,
  who owns the group) is made on the current copy;
- a deleted group is not recreated;
- a group that keeps changing gets the one conflict answer, with nothing written.

Take and transfer ownership re-check the approval on the current copy. The request
applies when the recorded owner still owns the group. It has already been applied,
and succeeds without writing, when the requested new owner owns it; a second approval
of the same request lands here. When anyone else owns it, it's refused. Each ends the
approval ``executed`` or ``failed`` with its reason, which an admin can see.
"""

import ast
import copy
from pathlib import Path

import pytest

from test_support.control_center_group_harness import control_center_group_environment
from test_support.group_directory_harness import person


APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
GROUP = "group-1"
STATUS_PATH = f"/api/admin/control-center/groups/{GROUP}/status"
ADD_PATH = f"/api/admin/control-center/groups/{GROUP}/add-member"


@pytest.fixture(scope="module")
def module_env():
    with control_center_group_environment() as env:
        yield env


@pytest.fixture
def env(module_env):
    module_env.cc.reset()
    module_env.seed_group(GROUP, status="active")
    yield module_env
    module_env.cc.reset()


def ns(env):
    return env.cc.namespace


def conflict(env):
    return {"error": env.modules.group.GROUP_WRITE_CONFLICT_MESSAGE, "error_code": "group_write_conflict"}


def concurrently(env, change, group_id=GROUP):
    """Land ``change`` on the stored group between a writer's read and its write."""
    def land():
        stored = env.stored_group(group_id)
        change(stored)
        env.groups.seed(stored)
    env.groups.before_replace.append(land)


def keep_changing(env):
    for index in range(env.modules.group.GROUP_DOCUMENT_WRITE_ATTEMPTS):
        concurrently(env, lambda group, index=index: group["users"].append(person("applicant-1") | {"userId": f"late-{index}"}))


def after_first_read(env, monkeypatch, change, group_id=GROUP):
    """Land ``change`` right after the writer's own first read, before the guard reads."""
    real_read = env.groups.read_item
    reads = []

    def read_item(item, partition_key, **kwargs):
        record = real_read(item, partition_key, **kwargs)
        reads.append(item)
        if len(reads) == 1:
            stored = env.stored_group(group_id)
            change(stored)
            env.groups.seed(stored)
        return record

    monkeypatch.setattr(env.groups, "read_item", read_item)


def writes(env):
    return [call[0] for call in env.write_calls()]


def status_logs(env):
    return [kwargs for name, _args, kwargs in env.activity.calls if name == "log_group_status_change"]


def event_messages(env):
    return [message for message, _level, _extra in env.logs]


def activity_types(env):
    return [record.get("activity_type") for record in env.activity_records()]


def put_status(env, status, reason="Quarterly review"):
    return env.cc.client.put(STATUS_PATH, json={"status": status, "reason": reason})


def add_member(env, user_id="newcomer-1", role="user", source="single"):
    return env.cc.client.post(ADD_PATH, json={
        "userId": user_id, "displayName": f"Name {user_id}", "email": f"{user_id}@example.test",
        "role": role, "source": source,
    })


# ---------------------------------------------------------------------------
# The metrics cache
# ---------------------------------------------------------------------------

def seed_documents(env):
    env.cc.documents.records.extend([
        {"group_id": GROUP, "type": "document_metadata", "number_of_pages": 3, "upload_date": "2026-09-20T10:00:00"},
        {"group_id": GROUP, "type": "document_metadata", "number_of_pages": 5, "upload_date": "2026-09-22T10:00:00"},
        {"group_id": "group-2", "type": "document_metadata", "number_of_pages": 9},
    ])


def test_a_forced_refresh_caches_the_metrics_on_the_current_copy(env):
    seed_documents(env)
    listed = env.stored_group(GROUP)
    # The refresh lists every group first; this membership change lands after the listing.
    stored = env.stored_group(GROUP)
    stored["pendingUsers"].append(person("applicant-1"))
    env.groups.seed(stored)
    before = env.stored_group(GROUP)

    enhanced = ns(env)["enhance_group_with_activity"](listed, force_refresh=True)

    after = env.stored_group(GROUP)
    assert after["metrics"]["document_metrics"] == {
        "total_documents": 2, "ai_search_size": 8 * 22 * 1024, "storage_account_size": 0,
    }
    assert after["metrics"]["calculated_at"]
    assert [entry["userId"] for entry in after["pendingUsers"]] == ["applicant-1"]
    assert {key: value for key, value in after.items() if key not in ("metrics", "_etag")} == \
        {key: value for key, value in before.items() if key != "_etag"}
    assert writes(env) == ["replace_item"]
    assert env.bumps == []
    assert enhanced["document_count"] == 2 and enhanced["id"] == GROUP
    assert listed["metrics"] == after["metrics"]


def test_a_group_deleted_after_the_listing_is_not_recreated(env):
    listed = env.stored_group(GROUP)
    env.groups.records.clear()
    enhanced = ns(env)["enhance_group_with_activity"](listed, force_refresh=True)
    assert env.groups.records == {}
    assert writes(env) == []
    assert enhanced["id"] == GROUP


def test_a_group_that_keeps_changing_is_left_uncached(env):
    listed = env.stored_group(GROUP)
    keep_changing(env)
    enhanced = ns(env)["enhance_group_with_activity"](listed, force_refresh=True)
    assert "metrics" not in env.stored_group(GROUP)
    assert enhanced["id"] == GROUP
    assert env.bumps == []


def test_a_plain_read_writes_nothing(env):
    seed_documents(env)
    enhanced = ns(env)["enhance_group_with_activity"](env.stored_group(GROUP))
    assert writes(env) == [] and enhanced["document_count"] == 2


class _EnhanceCalls(ast.NodeVisitor):
    """Each call of ``enhance_group_with_activity``: its enclosing function and ``force_refresh``."""

    def __init__(self):
        self.functions, self.calls = [], []

    def visit_FunctionDef(self, node):
        self.functions.append(node.name)
        self.generic_visit(node)
        self.functions.pop()

    def visit_Call(self, node):
        if isinstance(node.func, ast.Name) and node.func.id == "enhance_group_with_activity":
            force = next((keyword.value for keyword in node.keywords if keyword.arg == "force_refresh"), None)
            self.calls.append((self.functions[-1], None if force is None else ast.unparse(force)))
        self.generic_visit(node)


def test_every_metrics_write_goes_through_enhance_group_with_activity():
    """Every caller that can cache metrics reaches the one guarded write.

    Both refreshes force it, and the Control Center groups list (and its export) does
    too when asked with ``?force_refresh=true``; the shipped page asks for ``false``.
    The detail view never writes.
    """
    found = {}
    for path in sorted(APP_ROOT.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "enhance_group_with_activity(" not in text:
            continue
        visitor = _EnhanceCalls()
        visitor.visit(ast.parse(text))
        if visitor.calls:
            found[path.relative_to(APP_ROOT).as_posix()] = visitor.calls
    assert found == {
        "functions_control_center.py": [("execute_control_center_refresh", "True")],
        "route_backend_control_center.py": [
            ("api_get_all_groups", "force_refresh"),
            ("api_get_all_groups", "force_refresh"),
            ("api_get_group_details_admin", None),
            ("api_refresh_control_center_data", "True"),
        ],
    }


# ---------------------------------------------------------------------------
# The group status change
# ---------------------------------------------------------------------------

def test_a_status_change_is_applied_to_the_current_copy_and_logged_once(env):
    concurrently(env, lambda group: group["users"].append(person("applicant-1")))
    response = put_status(env, "locked")
    assert (response.status_code, response.get_json()) == (200, {
        "message": "Group status updated successfully", "old_status": "active", "new_status": "locked",
    })
    stored = env.stored_group(GROUP)
    assert stored["status"] == "locked"
    assert "applicant-1" in [entry["userId"] for entry in stored["users"]]
    [entry] = stored["statusHistory"]
    assert (entry["old_status"], entry["new_status"], entry["reason"]) == ("active", "locked", "Quarterly review")
    assert (entry["changed_by_user_id"], entry["changed_by_email"]) == ("cc-admin", "cc.admin@example.test")
    assert entry["changed_at"] == stored["modifiedDate"]
    assert env.bumps == ["group_status_updated"]
    assert status_logs(env) == [{
        "group_id": GROUP, "group_name": "Group group-1", "old_status": "active", "new_status": "locked",
        "changed_by_user_id": "cc-admin", "changed_by_email": "cc.admin@example.test", "reason": "Quarterly review",
    }]
    assert event_messages(env).count("[CONTROL_CENTER] Group Status Update") == 1


def test_the_old_status_is_the_one_the_write_replaced(env, monkeypatch):
    after_first_read(env, monkeypatch, lambda group: group.update(status="upload_disabled"))
    response = put_status(env, "locked")
    assert response.get_json()["old_status"] == "upload_disabled"
    assert env.stored_group(GROUP)["statusHistory"][-1]["old_status"] == "upload_disabled"
    assert status_logs(env)[0]["old_status"] == "upload_disabled"


def test_a_concurrent_status_history_entry_is_kept(env):
    concurrently(env, lambda group: group.setdefault("statusHistory", []).append({"new_status": "upload_disabled"}))
    put_status(env, "locked")
    assert [entry["new_status"] for entry in env.stored_group(GROUP)["statusHistory"]] == ["upload_disabled", "locked"]


def test_a_status_already_set_on_the_current_copy_is_unchanged(env, monkeypatch):
    after_first_read(env, monkeypatch, lambda group: group.update(status="locked"))
    response = put_status(env, "locked")
    assert (response.status_code, response.get_json()) == (200, {"message": "Group status unchanged", "status": "locked"})
    assert writes(env) == [] and env.bumps == [] and status_logs(env) == []


def test_the_classic_unchanged_answer_is_kept(env):
    response = put_status(env, "active")
    assert (response.status_code, response.get_json()) == (200, {"message": "Group status unchanged", "status": "active"})
    assert writes(env) == [] and env.bumps == []


def test_a_missing_group_keeps_its_404(env):
    response = env.cc.client.put("/api/admin/control-center/groups/group-9/status", json={"status": "locked"})
    assert (response.status_code, response.get_json()) == (404, {"error": "Group not found"})
    assert writes(env) == []


def test_a_group_deleted_mid_status_change_is_not_recreated(env):
    env.groups.before_replace.append(lambda: env.groups.records.clear())
    response = put_status(env, "locked")
    assert (response.status_code, response.get_json()) == (404, {"error": "Group not found"})
    assert env.groups.records == {} and writes(env) == ["replace_item"]
    assert env.bumps == [] and status_logs(env) == []


def test_a_group_that_keeps_changing_refuses_the_status_change(env):
    keep_changing(env)
    response = put_status(env, "locked")
    assert (response.status_code, response.get_json()) == (409, conflict(env))
    assert env.stored_group(GROUP)["status"] == "active"
    assert env.bumps == [] and status_logs(env) == []


@pytest.mark.parametrize("body,expected", [
    ({"status": "archived"}, (400, {"error": "Invalid status. Must be one of: active, locked, upload_disabled, inactive"})),
    ({"reason": "x"}, (400, {"error": "Status is required"})),
])
def test_the_classic_status_refusals_are_unchanged(env, body, expected):
    response = env.cc.client.put(STATUS_PATH, json=body)
    assert (response.status_code, response.get_json()) == expected
    assert writes(env) == []


def test_the_status_change_needs_a_control_center_admin(env):
    env.cc.as_cc_admin({"oid": "member-1", "roles": ["User"]})
    response = put_status(env, "locked")
    assert response.status_code == 403
    assert writes(env) == []


# ---------------------------------------------------------------------------
# Admin add member
# ---------------------------------------------------------------------------

def test_a_member_is_added_to_the_current_copy_and_logged_once(env):
    concurrently(env, lambda group: group["pendingUsers"].append(person("applicant-1")))
    response = add_member(env, role="admin", source="single")
    assert (response.status_code, response.get_json()) == (200, {
        "message": "Member newcomer-1@example.test added successfully", "skipped": False,
    })
    stored = env.stored_group(GROUP)
    assert stored["users"][-1] == {"userId": "newcomer-1", "email": "newcomer-1@example.test",
                                   "displayName": "Name newcomer-1"}
    assert "newcomer-1" in stored["admins"]
    assert [entry["userId"] for entry in stored["pendingUsers"]] == ["applicant-1"]
    assert env.bumps == ["group_member_added"]
    [record] = env.activity_records()
    assert (record["activity_type"], record["member_user_id"], record["member_role"], record["group_name"]) == (
        "add_member_directly", "newcomer-1", "admin", "Group group-1",
    )
    assert event_messages(env).count("[CONTROL_CENTER] Admin Add Group Member") == 1


@pytest.mark.parametrize("role,array", [("document_manager", "documentManagers"), ("user", None)])
def test_the_member_role_arrays_are_unchanged(env, role, array):
    add_member(env, role=role, source="csv")
    stored = env.stored_group(GROUP)
    assert ("newcomer-1" in stored["documentManagers"]) == (array == "documentManagers")
    assert "newcomer-1" not in stored["admins"]
    assert activity_types(env) == ["admin_add_member_csv"]


def test_a_member_added_meanwhile_is_skipped_on_the_current_copy(env, monkeypatch):
    after_first_read(env, monkeypatch, lambda group: group["users"].append(
        {"userId": "newcomer-1", "email": "newcomer-1@example.test", "displayName": "Name newcomer-1"}))
    response = add_member(env)
    assert (response.status_code, response.get_json()) == (200, {
        "message": "User newcomer-1@example.test already exists in group", "skipped": True,
    })
    assert writes(env) == [] and env.bumps == [] and env.activity_records() == []


def test_an_existing_member_is_still_skipped(env):
    response = add_member(env, user_id="member-1")
    assert response.get_json()["skipped"] is True
    assert writes(env) == []


def test_a_group_deleted_mid_add_is_not_recreated(env):
    env.groups.before_replace.append(lambda: env.groups.records.clear())
    response = add_member(env)
    assert (response.status_code, response.get_json()) == (404, {"error": "Group not found"})
    assert env.groups.records == {} and env.bumps == [] and env.activity_records() == []


def test_a_group_that_keeps_changing_refuses_the_add(env):
    keep_changing(env)
    response = add_member(env)
    assert (response.status_code, response.get_json()) == (409, conflict(env))
    assert "newcomer-1" not in [entry["userId"] for entry in env.stored_group(GROUP)["users"]]
    assert env.bumps == [] and env.activity_records() == []


@pytest.mark.parametrize("body,status", [
    ({"userId": "x", "email": "x@example.test"}, 400),
    ({"userId": "x", "displayName": "X", "email": "x@example.test", "role": "owner"}, 400),
])
def test_the_classic_add_refusals_are_unchanged(env, body, status):
    response = env.cc.client.post(ADD_PATH, json=body)
    assert response.status_code == status
    assert writes(env) == []


def test_adding_to_a_missing_group_keeps_its_404(env):
    response = env.cc.client.post("/api/admin/control-center/groups/group-9/add-member", json={
        "userId": "x", "displayName": "X", "email": "x@example.test",
    })
    assert (response.status_code, response.get_json()) == (404, {"error": "Group not found"})


# ---------------------------------------------------------------------------
# Approved take and transfer ownership
# ---------------------------------------------------------------------------

TAKE = "take_ownership"
TRANSFER = "transfer_ownership"
OWNER_METADATA = {"old_owner_id": "owner-1", "old_owner_email": "olive.owner@example.test"}
TRANSFER_METADATA = {**OWNER_METADATA, "new_owner_id": "member-1", "new_owner_email": "max.member@example.test",
                     "new_owner_name": "Max Member"}


def execute(env, approval):
    return ns(env)["_execute_approved_action"](approval, "approver-1", "approver@example.test", "Approver One")


def stored_approval(env, approval_id):
    record = env.cc.approvals.get(approval_id, GROUP)
    return record["status"], record["execution_result"]


def take(env):
    return env.cc.approval("approval-take", TAKE, metadata=OWNER_METADATA)


def transfer(env):
    return env.cc.approval("approval-transfer", TRANSFER, metadata=TRANSFER_METADATA)


def test_take_ownership_applies_to_the_current_copy_and_logs_once(env):
    concurrently(env, lambda group: group["pendingUsers"].append(person("applicant-1")))
    result = execute(env, take(env))
    assert result == {"success": True, "message": "Ownership transferred to adam.admin@example.test"}
    stored = env.stored_group(GROUP)
    assert stored["owner"] == {"id": "admin-1", "email": "adam.admin@example.test", "displayName": "Adam Admin"}
    assert "admin-1" not in stored["admins"] and "owner-1" not in stored["admins"]
    assert "owner-1" in [entry["userId"] for entry in stored["users"]]
    assert [entry["userId"] for entry in stored["pendingUsers"]] == ["applicant-1"]
    assert env.bumps == ["group_ownership_transferred"]
    [record] = env.activity_records()
    assert (record["activity_type"], record["old_owner_id"], record["new_owner_id"], record["approval_id"]) == (
        "admin_take_ownership_approved", "owner-1", "admin-1", "approval-take",
    )
    assert stored_approval(env, "approval-take") == ("executed", result["message"])


def test_take_ownership_already_applied_succeeds_without_writing(env):
    stored = env.stored_group(GROUP)
    stored["owner"] = {"id": "admin-1", "email": "adam.admin@example.test", "displayName": "Adam Admin"}
    env.groups.seed(stored)
    result = execute(env, take(env))
    assert result == {"success": True, "message": "Ownership transferred to adam.admin@example.test"}
    assert writes(env) == [] and env.bumps == [] and env.activity_records() == []
    assert stored_approval(env, "approval-take") == ("executed", result["message"])


def test_take_ownership_is_refused_when_someone_else_now_owns_the_group(env):
    stored = env.stored_group(GROUP)
    stored["owner"] = {"id": "manager-1", "email": "mia.manager@example.test", "displayName": "Mia Manager"}
    env.groups.seed(stored)
    result = execute(env, take(env))
    assert result == {"success": False, "message": ns(env)["GROUP_OWNERSHIP_CHANGED_MESSAGE"]}
    assert result["message"] == (
        "The group's owner changed after this request was made, so it wasn't applied. Submit a new request."
    )
    assert writes(env) == [] and env.bumps == [] and env.activity_records() == []
    assert env.stored_group(GROUP)["owner"]["id"] == "manager-1"
    assert stored_approval(env, "approval-take") == ("failed", result["message"])


def test_an_owner_change_landing_mid_write_refuses_the_take(env):
    concurrently(env, lambda group: group.update(owner={"id": "manager-1", "email": "mia.manager@example.test"}))
    result = execute(env, take(env))
    assert result["message"] == ns(env)["GROUP_OWNERSHIP_CHANGED_MESSAGE"]
    assert env.stored_group(GROUP)["owner"]["id"] == "manager-1"
    assert env.bumps == [] and env.activity_records() == []


def test_take_ownership_of_a_deleted_group_fails_without_recreating_it(env):
    env.groups.records.clear()
    result = execute(env, take(env))
    assert result == {"success": False, "message": "The group no longer exists."}
    assert env.groups.records == {} and writes(env) == []
    assert stored_approval(env, "approval-take") == ("failed", "The group no longer exists.")


def test_take_ownership_of_a_group_that_keeps_changing_fails_with_the_conflict_text(env):
    keep_changing(env)
    result = execute(env, take(env))
    assert result == {"success": False, "message": env.modules.group.GROUP_WRITE_CONFLICT_MESSAGE}
    assert env.stored_group(GROUP)["owner"]["id"] == "owner-1"
    assert env.bumps == [] and env.activity_records() == []
    assert stored_approval(env, "approval-take") == ("failed", result["message"])


def test_transfer_ownership_applies_to_the_current_copy_and_logs_once(env):
    concurrently(env, lambda group: group["pendingUsers"].append(person("applicant-1")))
    result = execute(env, transfer(env))
    assert result == {"success": True, "message": "Ownership transferred to max.member@example.test"}
    stored = env.stored_group(GROUP)
    assert stored["owner"] == {"id": "member-1", "email": "max.member@example.test", "displayName": "Max Member"}
    assert "owner-1" in [entry["userId"] for entry in stored["users"]]
    assert [entry["userId"] for entry in stored["pendingUsers"]] == ["applicant-1"]
    assert env.bumps == ["group_ownership_transferred"]
    [record] = env.activity_records()
    assert (record["activity_type"], record["old_owner_id"], record["new_owner_id"]) == (
        "transfer_ownership_approved", "owner-1", "member-1",
    )
    assert stored_approval(env, "approval-transfer") == ("executed", result["message"])


def test_transfer_ownership_already_applied_succeeds_without_writing(env):
    stored = env.stored_group(GROUP)
    stored["owner"] = {"id": "member-1", "email": "max.member@example.test", "displayName": "Max Member"}
    env.groups.seed(stored)
    result = execute(env, transfer(env))
    assert result == {"success": True, "message": "Ownership transferred to max.member@example.test"}
    assert writes(env) == [] and env.bumps == [] and env.activity_records() == []
    assert stored_approval(env, "approval-transfer") == ("executed", result["message"])


def test_transfer_ownership_is_refused_when_someone_else_now_owns_the_group(env):
    stored = env.stored_group(GROUP)
    stored["owner"] = {"id": "manager-1", "email": "mia.manager@example.test", "displayName": "Mia Manager"}
    env.groups.seed(stored)
    result = execute(env, transfer(env))
    assert result == {"success": False, "message": ns(env)["GROUP_OWNERSHIP_CHANGED_MESSAGE"]}
    assert writes(env) == [] and env.activity_records() == []
    assert stored_approval(env, "approval-transfer") == ("failed", result["message"])


def test_transfer_to_someone_no_longer_a_member_keeps_its_refusal(env):
    stored = env.stored_group(GROUP)
    stored["users"] = [entry for entry in stored["users"] if entry["userId"] != "member-1"]
    env.groups.seed(stored)
    result = execute(env, transfer(env))
    assert result == {"success": False, "message": "New owner not found in group members"}
    assert writes(env) == [] and env.activity_records() == []
    assert stored_approval(env, "approval-transfer") == ("failed", "New owner not found in group members")


def test_transfer_ownership_of_a_deleted_group_fails_without_recreating_it(env):
    env.groups.before_replace.append(lambda: env.groups.records.clear())
    result = execute(env, transfer(env))
    assert result == {"success": False, "message": "The group no longer exists."}
    assert env.groups.records == {} and env.bumps == [] and env.activity_records() == []


def test_transfer_ownership_of_a_group_that_keeps_changing_fails_with_the_conflict_text(env):
    keep_changing(env)
    result = execute(env, transfer(env))
    assert result == {"success": False, "message": env.modules.group.GROUP_WRITE_CONFLICT_MESSAGE}
    assert env.stored_group(GROUP)["owner"]["id"] == "owner-1"


@pytest.mark.parametrize("request_type,metadata", [(TAKE, OWNER_METADATA), (TRANSFER, TRANSFER_METADATA)])
def test_a_second_approval_of_the_same_request_keeps_it_executed(env, request_type, metadata):
    """Two approvers can both execute one request; the second finds it applied."""
    first = execute(env, env.cc.approval("approval-twice", request_type, metadata=metadata))
    second = execute(env, env.cc.approval("approval-twice", request_type, metadata=metadata))
    assert first["success"] is True and second == first
    assert len(env.activity_records()) == 1
    assert env.bumps == ["group_ownership_transferred"]
    assert stored_approval(env, "approval-twice") == ("executed", first["message"])
