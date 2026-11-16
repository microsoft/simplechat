# test_group_settings_legacy_writers.py
"""
Functional test for the classic group settings writers, moved onto the etag guard.
Version: 0.261.154
Implemented in: 0.261.154

The classic manage page and the admin retention push write through:

- ``PATCH`` and ``PUT /api/groups/<group_id>`` (name, description and hero color);
- ``PATCH /api/groups/<group_id>/download-settings``;
- ``POST /api/groups/<group_id>/logo``;
- ``POST /api/retention-policy/group/<group_id>``;
- ``POST /api/admin/retention-policy/force-push``, for groups.

Each read the group, changed it and upserted the whole copy, so a write racing a
membership change restored the older member list, and a group deleted in between was
recreated. Each now writes through ``update_group_document_with_etag_guard``. This test
runs them for real in ``test_support/group_settings_harness.py`` and pins, for each:

- the classic responses, messages and cache effects are unchanged;
- a membership change landing between the read and the write is kept, and fields the
  request leaves out come from the copy being written;
- a group deleted in between is 404 and never recreated;
- a group that keeps changing is 409 ``group_write_conflict`` with nothing stored;
- the owner or admin check is made again on the copy being written;
- no group upsert is left in them.
"""

import ast
from io import BytesIO
from pathlib import Path

import pytest

from test_support.group_directory_harness import person
from test_support.group_settings_harness import group_settings_environment, png_bytes


APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
GROUP = "group-1"
CONFLICT_MESSAGE = "The group changed while your request was being saved. Try again."
CONFLICT = {"error": CONFLICT_MESSAGE, "error_code": "group_write_conflict"}


def logo_upload():
    return {"logo_file": (BytesIO(png_bytes()), "logo.png")}


WRITERS = {
    "rename_patch": {
        "request": ("PATCH", f"/api/groups/{GROUP}", {"name": "Renamed"}, None),
        "caller": "owner-1",
        "success": {"message": "Group updated", "id": GROUP},
        "stored": lambda group: group["name"] == "Renamed",
        "bumps": ["group_updated"],
        "not_found": {"error": "Group not found"},
        "conflict": CONFLICT,
        "demote": lambda group: group.update(owner={"id": "admin-1", "displayName": "Adam Admin"}),
        "refused": {"error": "Only the owner can rename/edit the group"},
    },
    "rename_put": {
        "request": ("PUT", f"/api/groups/{GROUP}", {"name": "Renamed"}, None),
        "caller": "owner-1",
        "success": {"message": "Group updated", "id": GROUP},
        "stored": lambda group: group["name"] == "Renamed",
        "bumps": ["group_updated"],
        "not_found": {"error": "Group not found"},
        "conflict": CONFLICT,
        "demote": lambda group: group.update(owner={"id": "admin-1", "displayName": "Adam Admin"}),
        "refused": {"error": "Only the owner can rename/edit the group"},
    },
    "downloads": {
        "request": ("PATCH", f"/api/groups/{GROUP}/download-settings", {"disable_file_downloads": True}, None),
        "caller": "admin-1",
        "success": {"success": True, "message": "Download settings updated", "disable_file_downloads": True},
        "stored": lambda group: group["disable_file_downloads"] is True,
        "bumps": ["group_updated"],
        "not_found": {"error": "Group not found"},
        "conflict": CONFLICT,
        "demote": lambda group: group.update(admins=[]),
        "refused": {"error": "Only group owners and admins can update download settings"},
    },
    "logo": {
        "request": ("POST", f"/api/groups/{GROUP}/logo", None, logo_upload),
        "caller": "owner-1",
        "success": {"message": "Group logo updated", "logoVersion": 2},
        "stored": lambda group: bool(group["logoBase64"]) and group["logoVersion"] == 2,
        "bumps": [],
        "not_found": {"error": "Group not found"},
        "conflict": CONFLICT,
        "demote": lambda group: group.update(owner={"id": "admin-1", "displayName": "Adam Admin"}),
        "refused": {"error": "Only the owner can update the group logo"},
    },
    "retention": {
        "request": ("POST", f"/api/retention-policy/group/{GROUP}",
                    {"conversation_retention_days": 30, "document_retention_days": 60}, None),
        "caller": "admin-1",
        "success": {"success": True, "message": "Group retention settings updated successfully"},
        "stored": lambda group: group["retention_policy"] == {"conversation_retention_days": 30,
                                                              "document_retention_days": 60},
        "bumps": [],
        "not_found": {"success": False, "error": "Group not found"},
        "conflict": {"success": False, **CONFLICT},
        "demote": lambda group: group.update(admins=[]),
        "refused": {"success": False, "error": "Insufficient permissions. Must be group owner or admin."},
    },
}


@pytest.fixture(scope="module")
def module_env():
    with group_settings_environment() as env:
        yield env


@pytest.fixture
def env(module_env):
    module_env.reset()
    module_env.seed_group(GROUP, status="active")
    yield module_env
    module_env.reset()


def send(env, name):
    writer = WRITERS[name]
    env.as_user(writer["caller"])
    method, path, body, upload = writer["request"]
    if upload is not None:
        return env.call(method, path, data=upload())
    return env.call(method, path, body)


def outcome(response):
    return response.status_code, response.get_json()


def concurrently(env, change, group_id=GROUP):
    """Land ``change`` on the stored group between the writer's read and its write."""
    def land():
        stored = env.stored_group(group_id)
        change(stored)
        env.groups.seed(stored)
    env.groups.before_replace.append(land)


def group_writes(env):
    return [call[0] for call in env.write_calls()]


@pytest.mark.parametrize("name", WRITERS)
def test_the_classic_response_and_cache_effects_are_unchanged(env, name):
    writer = WRITERS[name]
    assert outcome(send(env, name)) == (200, writer["success"])
    assert writer["stored"](env.stored_group(GROUP))
    assert env.bumps == writer["bumps"]
    assert group_writes(env) == ["replace_item"]


@pytest.mark.parametrize("name", WRITERS)
def test_a_membership_change_landing_mid_write_is_kept(env, name):
    writer = WRITERS[name]
    concurrently(env, lambda group: group["pendingUsers"].append(person("applicant-1")))
    assert outcome(send(env, name)) == (200, writer["success"])
    stored = env.stored_group(GROUP)
    assert writer["stored"](stored)
    assert [entry["userId"] for entry in stored["pendingUsers"]] == ["applicant-1"]
    assert group_writes(env) == ["replace_item", "replace_item"]
    assert env.bumps == writer["bumps"]


@pytest.mark.parametrize("name", WRITERS)
def test_a_group_deleted_mid_write_is_not_recreated(env, name):
    writer = WRITERS[name]
    env.groups.before_replace.append(lambda: env.groups.records.clear())
    assert outcome(send(env, name)) == (404, writer["not_found"])
    assert env.groups.records == {}
    assert group_writes(env) == ["replace_item"]
    assert env.bumps == []


@pytest.mark.parametrize("name", WRITERS)
def test_a_group_that_keeps_changing_is_a_conflict(env, name):
    writer = WRITERS[name]
    for _ in range(3):
        concurrently(env, lambda group: group["users"].append(person("applicant-1")))
    assert outcome(send(env, name)) == (409, writer["conflict"])
    assert not writer["stored"](env.stored_group(GROUP))
    assert env.bumps == []


@pytest.mark.parametrize("name", WRITERS)
def test_the_role_is_checked_again_on_the_copy_being_written(env, name):
    writer = WRITERS[name]
    concurrently(env, writer["demote"])
    assert outcome(send(env, name)) == (403, writer["refused"])
    assert not writer["stored"](env.stored_group(GROUP))
    assert env.bumps == []


def test_fields_a_rename_leaves_out_come_from_the_copy_being_written(env):
    concurrently(env, lambda group: group.update(description="Changed elsewhere", heroColor="#111111"))
    env.as_user("owner-1")
    assert outcome(env.call("PATCH", f"/api/groups/{GROUP}", {"name": "Renamed"}))[0] == 200
    stored = env.stored_group(GROUP)
    assert (stored["name"], stored["description"], stored["heroColor"]) == ("Renamed", "Changed elsewhere", "#111111")


def test_a_rename_still_normalizes_the_color_against_the_stored_one(env):
    env.as_user("owner-1")
    env.call("PATCH", f"/api/groups/{GROUP}", {"heroColor": "not-a-color"})
    assert env.stored_group(GROUP)["heroColor"] == "#0078d4"
    env.call("PATCH", f"/api/groups/{GROUP}", {"heroColor": "#ABCDEF", "description": "New"})
    stored = env.stored_group(GROUP)
    assert (stored["heroColor"], stored["description"], stored["name"]) == ("#ABCDEF", "New", "Group group-1")


def test_the_logo_version_follows_the_copy_being_written(env):
    concurrently(env, lambda group: group.update(logoVersion=5))
    env.as_user("owner-1")
    assert outcome(env.call("POST", f"/api/groups/{GROUP}/logo", data=logo_upload())) == (
        200, {"message": "Group logo updated", "logoVersion": 6},
    )
    assert env.stored_group(GROUP)["logoVersion"] == 6


@pytest.mark.parametrize("caller,request_,expected", [
    ("admin-1", ("PATCH", f"/api/groups/{GROUP}", {"name": "x"}), (403, {"error": "Only the owner can rename/edit the group"})),
    ("admin-1", ("POST", f"/api/groups/{GROUP}/logo", None), (403, {"error": "Only the owner can update the group logo"})),
    ("member-1", ("PATCH", f"/api/groups/{GROUP}/download-settings", {"disable_file_downloads": True}),
     (403, {"error": "Only group owners and admins can update download settings"})),
    ("member-1", ("POST", f"/api/retention-policy/group/{GROUP}", {"conversation_retention_days": 30}),
     (403, {"success": False, "error": "Insufficient permissions. Must be group owner or admin."})),
    ("owner-1", ("PATCH", "/api/groups/group-9", {"name": "x"}), (404, {"error": "Group not found"})),
    ("owner-1", ("PATCH", "/api/groups/group-9/download-settings", {}), (404, {"error": "Group not found"})),
    ("owner-1", ("POST", "/api/groups/group-9/logo", None), (404, {"error": "Group not found"})),
    ("owner-1", ("POST", "/api/retention-policy/group/group-9", {"conversation_retention_days": 30}),
     (404, {"success": False, "error": "Group not found"})),
])
def test_the_classic_refusals_before_the_write_are_unchanged(env, caller, request_, expected):
    env.as_user(caller)
    method, path, body = request_
    response = env.call(method, path, body) if body is not None else env.call(method, path, data=logo_upload())
    assert outcome(response) == expected
    assert env.write_calls() == []


# ---------------------------------------------------------------------------
# The admin retention push
# ---------------------------------------------------------------------------

def seed_three_groups(env):
    env.groups.records.clear()
    for group_id in ("group-1", "group-2", "group-3"):
        env.seed_group(group_id, status="active",
                       retention_policy={"conversation_retention_days": 30, "document_retention_days": 90})


def force_push(env):
    env.as_user("app-admin", ["Admin"])
    return env.call("POST", "/api/admin/retention-policy/force-push", {"scopes": ["group"]})


DEFAULT_POLICY = {"conversation_retention_days": "default", "document_retention_days": "default"}


def test_the_push_writes_each_group_on_its_current_copy(env):
    seed_three_groups(env)
    concurrently(env, lambda group: group["pendingUsers"].append(person("applicant-1")), "group-1")
    env.groups.before_replace.append(lambda: None)
    env.groups.before_replace.append(lambda: env.groups.records.pop(("group-2", "group-2")))
    response = force_push(env)
    assert outcome(response) == (200, {
        "success": True, "message": "Defaults pushed to 2 items", "updated_count": 2,
        "scopes": ["group"], "details": {"group": 2},
    })
    first = env.stored_group("group-1")
    assert first["retention_policy"] == DEFAULT_POLICY
    assert [entry["userId"] for entry in first["pendingUsers"]] == ["applicant-1"]
    assert env.stored_group("group-2") is None
    assert env.stored_group("group-3")["retention_policy"] == DEFAULT_POLICY
    assert "upsert_item" not in group_writes(env) and "create_item" not in group_writes(env)
    assert env.bumps == []


def test_a_group_that_keeps_changing_is_skipped_and_logged(env):
    seed_three_groups(env)
    for _ in range(3):
        concurrently(env, lambda group: group["users"].append(person("applicant-1")), "group-1")
    response = force_push(env)
    assert outcome(response)[1]["details"] == {"group": 2}
    assert env.stored_group("group-1")["retention_policy"] == {"conversation_retention_days": 30,
                                                              "document_retention_days": 90}
    assert env.stored_group("group-2")["retention_policy"] == DEFAULT_POLICY
    assert any(message.startswith("Error updating group group-1 during force push") for message, _, _ in env.logs)


def test_the_push_keeps_every_other_group_field(env):
    seed_three_groups(env)
    before = {group_id: env.stored_group(group_id) for group_id in ("group-1", "group-2", "group-3")}
    force_push(env)
    for group_id, original in before.items():
        stored = env.stored_group(group_id)
        for field in ("users", "admins", "documentManagers", "pendingUsers", "name", "status", "model_endpoints",
                      "logoVersion", "modifiedDate"):
            assert stored[field] == original[field], (group_id, field)


# ---------------------------------------------------------------------------
# No raw group writer is left
# ---------------------------------------------------------------------------

CONVERTED = [
    ("route_backend_groups.py", "api_update_group"),
    ("route_backend_groups.py", "api_update_group_download_settings"),
    ("route_backend_groups.py", "api_upload_group_logo"),
    ("route_backend_retention_policy.py", "update_group_retention_settings"),
    ("route_backend_retention_policy.py", "force_push_retention_defaults"),
]


def _function(file_name, name):
    tree = ast.parse((APP_ROOT / file_name).read_text(encoding="utf-8"))
    return next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name)


@pytest.mark.parametrize("file_name,name", CONVERTED)
def test_the_converted_writers_use_the_guard_and_never_upsert_a_group(file_name, name):
    function = _function(file_name, name)
    names = {node.id for node in ast.walk(function) if isinstance(node, ast.Name)}
    assert "update_group_document_with_etag_guard" in names
    assert "cosmos_groups_container" not in names
    attributes = {node.attr for node in ast.walk(function) if isinstance(node, ast.Attribute)}
    if name != "force_push_retention_defaults":
        assert "upsert_item" not in attributes
