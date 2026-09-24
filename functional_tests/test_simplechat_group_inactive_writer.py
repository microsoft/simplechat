# test_simplechat_group_inactive_writer.py
"""
Functional test for the SimpleChat group inactive marker on the etag guard.
Version: 0.261.156
Implemented in: 0.261.156

``make_group_inactive_for_current_user``, behind the SimpleChat agent's
``make_group_inactive`` tool, read the group, set it inactive and upserted that copy
back, so a membership or status change landing in between was undone and a group
deleted in between was recreated.

It now writes through ``update_group_document_with_etag_guard`` and decides on the
copy it writes. This test runs it unchanged, with the real ``functions_group`` over
the etag-enforcing groups container from ``test_support/group_directory_harness.py``,
and pins:

- the classic answer, the status history entry, the cache reason, the status change
  log and the event, once, after the commit;
- a concurrent change is kept, and the previous status is the one the write replaced;
- a group already inactive on the current copy, including one made inactive
  meanwhile, gets the classic "already inactive" answer with nothing written;
- a missing or deleted group raises ``LookupError`` and is not recreated, and a group
  that keeps changing raises ``GroupDocumentWriteConflict``, the typed error the
  plugin's existing error path answers, with nothing written or logged;
- the Control Center admin check runs before any read.
"""

import copy
import typing
from datetime import datetime
from unittest.mock import patch

import pytest
from flask import session

from test_support.app_source import run_definitions
from test_support.group_directory_harness import group_directory_environment, person


GROUP = "group-1"
ADMIN = {"oid": "cc-admin", "roles": ["Admin"], "name": "Casey Control", "preferred_username": "cc.admin@example.test"}
DEFINITIONS = {
    "_GroupAlreadyInactive", "make_group_inactive_for_current_user", "_require_current_user_info",
    "_require_control_center_admin_access",
}


@pytest.fixture(scope="module")
def module_env():
    with group_directory_environment() as env:
        env.status_logs = []
        env.inactive = run_definitions("functions_simplechat_operations.py", DEFINITIONS, {
            "Any": typing.Any, "Dict": typing.Dict, "Optional": typing.Optional, "Tuple": typing.Tuple,
            "datetime": datetime, "session": session,
            "get_settings": env.get_settings,
            "get_current_user_info": env.modules.authentication.get_current_user_info,
            "require_active_group": env.modules.group.require_active_group,
            "find_group_by_id": env.modules.group.find_group_by_id,
            "functions_group": env.modules.group,
            "log_group_status_change": lambda **kwargs: env.status_logs.append(kwargs),
            "log_event": env.log_event,
        })
        yield env


@pytest.fixture
def env(module_env):
    module_env.reset()
    module_env.status_logs.clear()
    module_env.seed_group(GROUP, status="active")
    yield module_env


def mark(env, user=ADMIN, **kwargs):
    with env.app.test_request_context("/"):
        session["user"] = copy.deepcopy(user)
        return env.inactive["make_group_inactive_for_current_user"](**kwargs)


def concurrently(env, change):
    def land():
        stored = env.stored_group(GROUP)
        change(stored)
        env.groups.seed(stored)
    env.groups.before_replace.append(land)


def writes(env):
    return [call[0] for call in env.write_calls()]


def events(env):
    return [message for message, _level, _extra in env.logs]


def test_a_group_is_marked_inactive_on_the_current_copy_and_logged_once(env):
    concurrently(env, lambda group: group["pendingUsers"].append(person("applicant-1")))
    result = mark(env, group_id=GROUP, reason="No recent activity")
    stored = env.stored_group(GROUP)
    assert stored["status"] == "inactive"
    assert [entry["userId"] for entry in stored["pendingUsers"]] == ["applicant-1"]
    [entry] = stored["statusHistory"]
    assert entry == {
        "old_status": "active", "new_status": "inactive",
        "changed_by_user_id": "cc-admin", "changed_by_email": "cc.admin@example.test",
        "changed_at": stored["modifiedDate"], "reason": "No recent activity",
    }
    assert (result["old_status"], result["new_status"], result["message"]) == (
        "active", "inactive", "Marked group 'Group group-1' as inactive.",
    )
    assert result["group"]["status"] == "inactive"
    assert env.bumps == ["group_marked_inactive"]
    assert env.status_logs == [{
        "group_id": GROUP, "group_name": "Group group-1", "old_status": "active", "new_status": "inactive",
        "changed_by_user_id": "cc-admin", "changed_by_email": "cc.admin@example.test", "reason": "No recent activity",
    }]
    assert events(env) == ["[SIMPLE_CHAT] Group marked inactive"]


def test_the_previous_status_is_the_one_the_write_replaced(env):
    concurrently(env, lambda group: group.update(status="locked"))
    result = mark(env, group_id=GROUP)
    assert result["old_status"] == "locked"
    assert env.stored_group(GROUP)["statusHistory"][-1]["old_status"] == "locked"
    assert env.status_logs[0]["old_status"] == "locked"


def test_a_concurrent_status_history_entry_is_kept(env):
    concurrently(env, lambda group: group.setdefault("statusHistory", []).append({"new_status": "locked"}))
    mark(env, group_id=GROUP)
    assert [entry["new_status"] for entry in env.stored_group(GROUP)["statusHistory"]] == ["locked", "inactive"]


def test_a_group_already_inactive_is_answered_without_a_write(env):
    env.seed_group(GROUP, status="inactive")
    result = mark(env, group_id=GROUP)
    assert (result["old_status"], result["new_status"], result["message"]) == (
        "inactive", "inactive", "Group 'Group group-1' is already inactive.",
    )
    assert result["group"]["id"] == GROUP
    assert writes(env) == [] and env.bumps == [] and env.status_logs == [] and events(env) == []


def test_a_group_made_inactive_meanwhile_is_answered_without_a_second_write(env):
    concurrently(env, lambda group: group.update(status="inactive", statusHistory=[{"new_status": "inactive"}]))
    result = mark(env, group_id=GROUP)
    assert result["message"] == "Group 'Group group-1' is already inactive."
    assert writes(env) == ["replace_item"], "only the attempt that lost its race"
    assert env.stored_group(GROUP)["statusHistory"] == [{"new_status": "inactive"}]
    assert env.bumps == [] and env.status_logs == []


def test_a_missing_group_is_not_found(env):
    with pytest.raises(LookupError, match="^Group not found$"):
        mark(env, group_id="group-9")
    assert writes(env) == []


def test_a_group_deleted_mid_write_is_not_recreated(env):
    env.groups.before_replace.append(lambda: env.groups.records.clear())
    with pytest.raises(LookupError, match="^Group not found$"):
        mark(env, group_id=GROUP)
    assert env.groups.records == {} and env.bumps == [] and env.status_logs == []


def test_a_group_that_keeps_changing_raises_the_typed_conflict(env):
    for index in range(env.modules.group.GROUP_DOCUMENT_WRITE_ATTEMPTS):
        concurrently(env, lambda group, index=index: group["users"].append(person("applicant-1") | {"userId": f"late-{index}"}))
    with pytest.raises(env.modules.group.GroupDocumentWriteConflict):
        mark(env, group_id=GROUP)
    assert env.stored_group(GROUP)["status"] == "active"
    assert env.bumps == [] and env.status_logs == [] and events(env) == []


def test_a_caller_without_admin_access_is_refused_before_any_read(env):
    env.groups.calls.clear()
    with pytest.raises(PermissionError, match=r"^Insufficient permissions \(Admin role required\)$"):
        mark(env, user={**ADMIN, "roles": ["User"]}, group_id=GROUP)
    assert env.groups.calls == []


def test_the_active_group_is_used_when_no_group_is_named(env):
    owner_admin = {**ADMIN, "oid": "owner-1", "preferred_username": "olive.owner@example.test"}
    settings = {"id": "owner-1", "settings": {"activeGroupOid": GROUP}}
    with patch.object(env.modules.settings, "get_user_settings", lambda user_id, *args, **kwargs: settings):
        result = mark(env, user=owner_admin)
    assert result["new_status"] == "inactive"
    assert env.stored_group(GROUP)["statusHistory"][-1]["changed_by_user_id"] == "owner-1"
