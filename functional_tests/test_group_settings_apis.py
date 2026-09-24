# test_group_settings_apis.py
"""
Functional test for the native group settings read and writes.
Version: 0.261.154
Implemented in: 0.261.154

``GET /api/groups/<group_id>/settings`` and the writes under it run for real in
``test_support/group_settings_harness.py``, over the etag-enforcing groups container,
with the real group, branding and directory helpers. This test pins:

- the read: built from stored fields only, with no email, member list, secret or
  Cosmos field, each section present only when its feature is on, and retention
  values resolved as the retention job resolves them;
- each write: its validation and reviewed messages, the per-section revision (409
  ``group_settings_changed``), the refusals (403 with the decision's reason, decided
  before the body is read), and its cache, audit and notification effects;
- each write through the etag guard: a concurrent membership change is kept, a group
  deleted mid-write is 404 and never recreated, one that keeps changing is 409
  ``group_write_conflict``, and a role, status or section change landing mid-write
  is refused on the fresh copy with nothing stored;
- the boundary: ``no-store`` on every answer, the session, role and feature gates,
  and a data-free 500 for anything unexpected.
"""

import base64
import copy
from io import BytesIO

import pytest
from azure.cosmos import exceptions as cosmos_exceptions
from PIL import Image

from test_support.agent_delegation import execute_functions
from test_support.group_directory_harness import person
from test_support.group_settings_harness import (
    decompression_bomb_png,
    group_settings_environment,
    jpeg_bytes,
    png_bytes,
)


GROUP = "group-1"
# Download assignment lists hold canonical group GUIDs.
ASSIGNED_GROUP = "5b6d0c5e-4f3a-4b8e-9d2c-1a7e3f9b2c41"
OTHER_GROUP = "d3b07384-d9a7-4f3b-8c2e-6f1a2b3c4d5e"
SETTINGS_PATH = f"/api/groups/{GROUP}/settings"
PROFILE_PATH = f"{SETTINGS_PATH}/profile"
LOGO_PATH = f"{SETTINGS_PATH}/logo"
DOWNLOADS_PATH = f"{SETTINGS_PATH}/downloads"
RETENTION_PATH = f"{SETTINGS_PATH}/retention"
SEEDED_MODIFIED = "2026-09-01T00:00:00"
CHANGED = {"error": "These settings changed since you opened them. Reload them before saving.",
           "error_code": "group_settings_changed"}
NOT_FOUND = {"error": "Group not found.", "error_code": "group_not_found"}
WRITE_CONFLICT = {"error": "The group changed while your request was being saved. Try again.",
                  "error_code": "group_write_conflict"}
NO_REVISION = "Include the revision of the settings you loaded."
UNREADABLE_LOGO = "The logo image could not be read. Upload a PNG or JPEG image."


@pytest.fixture(scope="module")
def module_env():
    with group_settings_environment() as env:
        yield env


@pytest.fixture
def env(module_env):
    module_env.reset()
    module_env.seed_group(GROUP, status="active")
    module_env.as_user("owner-1")
    yield module_env
    module_env.reset()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def answer(response):
    assert response.headers["Cache-Control"] == "no-store", dict(response.headers)
    return response.get_json()


def assert_error(response, status, error_code, message=None):
    body = answer(response)
    assert response.status_code == status, body
    assert set(body) == {"error", "error_code"}, body
    assert body["error_code"] == error_code, body
    if message is not None:
        assert body["error"] == message
    return body


def assert_invalid(response, message):
    return assert_error(response, 400, "invalid_request", message)


def assert_untouched(env, before=None):
    assert env.write_calls() == []
    if before is not None:
        assert env.stored_group(GROUP) == before


def assert_quiet(env):
    """No write here records activity, notifies anyone or touches user settings."""
    assert env.notifications == []
    assert env.activity.calls == []
    assert env.user_settings_writes == []


def written(env, response):
    body = answer(response)
    assert response.status_code == 200, body
    assert set(body) == {"settings"}
    assert body["settings"] == answer(env.settings_read())["settings"]
    assert env.stored_group(GROUP)["modifiedDate"] != SEEDED_MODIFIED
    assert_quiet(env)
    return body["settings"]


def patch_profile(env, revision=None, **fields):
    return env.call("PATCH", PROFILE_PATH, {"revision": revision or env.revision("profile"), **fields})


def patch_downloads(env, value, revision=None):
    return env.call("PATCH", DOWNLOADS_PATH, {"revision": revision or env.revision("downloads"),
                                              "disable_file_downloads": value})


def patch_retention(env, revision=None, **fields):
    return env.call("PATCH", RETENTION_PATH, {"revision": revision or env.revision("retention"), **fields})


def put_logo(env, content=None, filename="logo.png", revision=None, **extra):
    data = {"logo_file": (BytesIO(png_bytes() if content is None else content), filename),
            "revision": revision or env.revision("logo"), **extra}
    return env.call("PUT", LOGO_PATH, data=data)


def delete_logo(env, revision=None):
    return env.call("DELETE", LOGO_PATH, {"revision": revision or env.revision("logo")})


def reseed(env, **fields):
    env.groups.records.clear()
    return env.seed_group(GROUP, status=fields.pop("status", "active"), **fields)


def concurrently(env, change):
    """Land ``change`` on the stored group between the writer's read and its write."""
    def land():
        stored = env.stored_group(GROUP)
        change(stored)
        env.groups.seed(stored)
    env.groups.before_replace.append(land)


def gif_bytes():
    output = BytesIO()
    Image.new("RGB", (4, 4), (10, 10, 10)).save(output, format="GIF")
    return output.getvalue()


def stored_logo_image(env):
    return Image.open(BytesIO(base64.b64decode(env.stored_group(GROUP)["logoBase64"])))


# ---------------------------------------------------------------------------
# The read
# ---------------------------------------------------------------------------

def test_the_read_is_built_from_stored_fields_only(env):
    reseed(env, status="upload_disabled", pending=("applicant-1",), heroColor="#123abc",
           logoBase64="c3RvcmVkLWxvZ28=", logoVersion=4,
           retention_policy={"conversation_retention_days": 30, "document_retention_days": "none"})
    response = env.settings_read()
    body = answer(response)
    assert response.status_code == 200
    assert set(body) == {"settings"}
    settings = body["settings"]
    assert set(settings) == {"schema_version", "group_id", "viewer_role", "status", "profile", "logo",
                             "downloads", "retention", "settings_management"}
    assert settings["schema_version"] == 1
    assert settings["group_id"] == GROUP
    assert settings["viewer_role"] == "Owner"
    assert settings["status"] == "upload_disabled"
    assert settings["profile"] == {"name": "Group group-1", "description": "A shared workspace",
                                   "hero_color": "#123abc", "revision": env.revision("profile")}
    assert settings["logo"] == {"has_logo": True, "logo_version": 4, "logo_url": "/api/groups/group-1/logo?v=4",
                                "revision": env.revision("logo")}
    assert settings["downloads"] == {"disable_file_downloads": False, "file_downloads_enabled": True,
                                     "revision": env.revision("downloads")}
    assert settings["retention"] == {
        "conversation_retention_days": 30,
        "document_retention_days": "none",
        "bounds": {"conversation": {"min_days": 1, "max_days": 3650}, "document": {"min_days": 1, "max_days": 3650}},
        "organization_defaults": {"conversation_retention_days": "none", "document_retention_days": 30},
        "revision": env.revision("retention"),
    }
    text = response.get_data(as_text=True)
    for private in ("@example.test", "Olive Owner", "Adam Admin", "Ana Applicant", "applicant-1", "member-1",
                    "manager-1", "sk-secret-endpoint-key", "model_endpoints", "_etag", "c3RvcmVkLWxvZ28=",
                    "pendingUsers", "createdDate", "modifiedDate"):
        assert private not in text, private
    assert env.write_calls() == []


@pytest.mark.parametrize("caller,role", [("owner-1", "Owner"), ("admin-1", "Admin")])
def test_the_owner_and_admins_read_the_settings(env, caller, role):
    env.as_user(caller)
    settings = answer(env.settings_read())["settings"]
    assert settings["viewer_role"] == role


@pytest.mark.parametrize("caller", ["manager-1", "member-1"])
def test_other_members_are_refused_the_read(env, caller):
    env.as_user(caller)
    assert_error(env.settings_read(), 403, "group_manager_required", "Only the group owner or an admin can do this.")


def test_the_downloads_section_is_present_only_when_an_administrator_allows_downloads(env):
    env.seed_group(ASSIGNED_GROUP, status="active", disable_file_downloads=True)
    env.settings["allow_group_workspace_file_downloads"] = False
    assert "downloads" not in answer(env.settings_read(ASSIGNED_GROUP))["settings"]
    env.settings.update({"allow_group_workspace_file_downloads": True,
                         "require_group_assignment_for_file_downloads": True,
                         "file_download_allowed_group_ids": [OTHER_GROUP]})
    assert "downloads" not in answer(env.settings_read(ASSIGNED_GROUP))["settings"]
    env.settings["file_download_allowed_group_ids"] = [ASSIGNED_GROUP]
    downloads = answer(env.settings_read(ASSIGNED_GROUP))["settings"]["downloads"]
    assert downloads["disable_file_downloads"] is True
    assert downloads["file_downloads_enabled"] is False


@pytest.mark.parametrize("changes", [
    {"enable_retention_policy_group": False},
    {"enable_retention_policy_group": None},
])
def test_the_retention_section_is_present_only_when_group_retention_is_on(env, changes):
    env.settings.update(changes)
    assert "retention" not in answer(env.settings_read())["settings"]


RETENTION_CASES = [None, "", "default", "none", 45, "45", "soon", True, 0, -3]


@pytest.mark.parametrize("stored", RETENTION_CASES)
def test_stored_retention_values_read_as_the_retention_job_resolves_them(env, stored):
    namespace = {"get_settings": env.get_settings}
    execute_functions("functions_retention_policy.py", {"resolve_retention_value"}, namespace)
    job = namespace["resolve_retention_value"]
    reseed(env, retention_policy={"conversation_retention_days": stored, "document_retention_days": stored})
    retention = answer(env.settings_read())["settings"]["retention"]
    for kind in ("conversation", "document"):
        value = retention[f"{kind}_retention_days"]
        resolved = job(stored, "group", kind, env.get_settings())
        if value == "default":
            assert resolved == retention["organization_defaults"][f"{kind}_retention_days"]
            assert stored in (None, "", "default")
        else:
            assert value == resolved


@pytest.mark.parametrize("policy", ["missing", None, "none", ["default"], {}])
def test_a_missing_or_malformed_policy_reads_as_the_organization_default(env, policy):
    if policy == "missing":
        reseed(env)
        env.groups.records[(GROUP, GROUP)].pop("retention_policy")
    else:
        reseed(env, retention_policy=policy)
    retention = answer(env.settings_read())["settings"]["retention"]
    assert retention["conversation_retention_days"] == "default"
    assert retention["document_retention_days"] == "default"


def test_the_bounds_and_organization_defaults_come_from_the_settings(env):
    env.settings.update({"retention_conversation_min_days": 7, "retention_conversation_max_days": "90",
                         "retention_document_min_days": True, "retention_document_max_days": "lots",
                         "default_retention_conversation_group": 14, "default_retention_document_group": "never"})
    retention = answer(env.settings_read())["settings"]["retention"]
    assert retention["bounds"] == {"conversation": {"min_days": 7, "max_days": 90},
                                   "document": {"min_days": 1, "max_days": 3650}}
    assert retention["organization_defaults"] == {"conversation_retention_days": 14, "document_retention_days": "none"}


@pytest.mark.parametrize("stored,shown", [("#ABCDEF", "#ABCDEF"), ("teal", "#0078d4"), (None, "#0078d4")])
def test_the_hero_color_reads_as_the_classic_pages_show_it(env, stored, shown):
    reseed(env, heroColor=stored)
    assert answer(env.settings_read())["settings"]["profile"]["hero_color"] == shown


@pytest.mark.parametrize("stored,shown", [("locked", "locked"), ("inactive", "inactive"), ("archived", "unknown"),
                                          (None, "unknown")])
def test_the_status_is_reported_from_a_fixed_vocabulary(env, stored, shown):
    reseed(env, status=stored)
    assert answer(env.settings_read())["settings"]["status"] == shown


def test_a_group_without_a_status_reads_as_active(env):
    reseed(env)
    env.groups.records[(GROUP, GROUP)].pop("status")
    assert answer(env.settings_read())["settings"]["status"] == "active"


def test_revisions_cover_only_their_own_section(env):
    before = {section: env.revision(section) for section in ("profile", "logo", "downloads", "retention")}
    stored = env.stored_group(GROUP)
    stored["users"].append(person("applicant-1"))
    stored["status"] = "upload_disabled"
    stored["admins"] = []
    stored["modifiedDate"] = "2026-09-02T00:00:00"
    env.groups.seed(stored)
    assert {section: env.revision(section) for section in before} == before
    for section, field, value in (("profile", "name", "Renamed"), ("logo", "logoVersion", 9),
                                  ("downloads", "disable_file_downloads", True),
                                  ("retention", "retention_policy", {"conversation_retention_days": 5})):
        stored = env.stored_group(GROUP)
        stored[field] = value
        env.groups.seed(stored)
        assert env.revision(section) != before[section], section
        before[section] = env.revision(section)


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

def test_the_owner_changes_the_name_description_and_color(env):
    settings = written(env, patch_profile(env, name="  Research  ", description=" Notes ", hero_color="#AA00bb"))
    stored = env.stored_group(GROUP)
    assert (stored["name"], stored["description"], stored["heroColor"]) == ("Research", "Notes", "#AA00bb")
    assert settings["profile"] == {"name": "Research", "description": "Notes", "hero_color": "#AA00bb",
                                   "revision": env.revision("profile")}
    assert env.bumps == ["group_updated"]
    assert [call[0] for call in env.write_calls()] == ["replace_item"]


def test_only_the_fields_sent_are_changed(env):
    written(env, patch_profile(env, description="Only this"))
    stored = env.stored_group(GROUP)
    assert (stored["name"], stored["description"], stored["heroColor"]) == ("Group group-1", "Only this", "#0078d4")


def test_a_stored_name_or_description_is_kept_when_it_is_sent_back_unchanged(env):
    long_name, long_description = "N" * 120, "D" * 700
    reseed(env, name=long_name, description=long_description)
    written(env, patch_profile(env, name=long_name, description=long_description, hero_color="#101010"))
    stored = env.stored_group(GROUP)
    assert (stored["name"], stored["description"], stored["heroColor"]) == (long_name, long_description, "#101010")
    assert_invalid(patch_profile(env, name=long_name + "x"), "Group names can be at most 80 characters.")


@pytest.mark.parametrize("fields,message", [
    ({"name": ""}, "Enter a group name."),
    ({"name": "   "}, "Enter a group name."),
    ({"name": None}, "Enter a group name."),
    ({"name": 7}, "The group name must be text."),
    ({"name": "N" * 81}, "Group names can be at most 80 characters."),
    ({"name": "Tab\there"}, "Group names cannot contain control characters."),
    ({"description": None}, "The group description must be text."),
    ({"description": ["text"]}, "The group description must be text."),
    ({"description": "D" * 501}, "Group descriptions can be at most 500 characters."),
    ({"hero_color": None}, "The hero color must be text, such as #0078d4."),
    ({"hero_color": 123456}, "The hero color must be text, such as #0078d4."),
    ({}, "Include a name, description or hero_color to change."),
    ({"heroColor": "#101010"}, "Only the name, description and hero_color can be changed here."),
    ({"name": "Fine", "owner": "admin-1"}, "Only the name, description and hero_color can be changed here."),
])
def test_profile_values_are_validated_with_reviewed_messages(env, fields, message):
    before = env.stored_group(GROUP)
    assert_invalid(patch_profile(env, **fields), message)
    assert_untouched(env, before)
    assert env.bumps == []


def test_a_color_that_is_not_a_hex_color_keeps_the_stored_color(env):
    reseed(env, heroColor="#223344")
    written(env, patch_profile(env, hero_color="rebeccapurple"))
    assert env.stored_group(GROUP)["heroColor"] == "#223344"


@pytest.mark.parametrize("raw,content_type,message", [
    ("not json", "application/json", "Provide valid JSON with no duplicate fields."),
    ('["name"]', "application/json", "A JSON object is required for this request."),
    ('{"name": "One", "name": "Two", "revision": "r"}', "application/json", "Duplicate fields are not supported."),
    ('{"name": "One"}', "text/plain", "A JSON object is required for this request."),
])
def test_malformed_profile_bodies_are_refused(env, raw, content_type, message):
    assert_invalid(env.call("PATCH", PROFILE_PATH, raw=raw, content_type=content_type), message)
    assert_untouched(env)


@pytest.mark.parametrize("revision", [None, "", 5, ["r"]])
def test_every_write_names_the_revision_it_was_opened_at(env, revision):
    body = {"name": "Renamed"}
    if revision is not None:
        body["revision"] = revision
    assert_invalid(env.call("PATCH", PROFILE_PATH, body), NO_REVISION)
    assert_untouched(env)


def test_a_stale_or_foreign_revision_is_refused_with_nothing_stored(env):
    before = env.stored_group(GROUP)
    assert answer(patch_profile(env, revision="0" * 64, name="Renamed")) == CHANGED
    assert answer(patch_profile(env, revision=env.revision("logo"), name="Renamed")) == CHANGED
    assert_untouched(env, before)


def test_a_classic_save_moves_the_revision_on(env):
    opened = env.revision("profile")
    classic = env.call("PATCH", f"/api/groups/{GROUP}", {"name": "Classic"})
    assert classic.status_code == 200
    response = patch_profile(env, revision=opened, name="Native")
    assert response.status_code == 409
    assert answer(response) == CHANGED
    assert env.stored_group(GROUP)["name"] == "Classic"


def test_a_write_to_another_section_does_not_refuse_a_profile_write(env):
    opened = env.revision("profile")
    written(env, patch_downloads(env, True))
    written(env, patch_profile(env, revision=opened, name="Still fine"))
    assert env.stored_group(GROUP)["name"] == "Still fine"


@pytest.mark.parametrize("caller,roles,narrowed,status,reason", [
    ("admin-1", ["User"], False, "active", "group_owner_required"),
    ("manager-1", ["User"], False, "active", "group_owner_required"),
    ("member-1", ["User"], False, "active", "group_owner_required"),
    ("owner-1", ["User"], True, "active", "create_groups_role_required"),
    ("owner-1", ["Admin"], True, "active", "create_groups_role_required"),
    ("owner-1", ["User", "CreateGroups"], True, "locked", "group_status_unavailable"),
    ("owner-1", ["User"], False, "inactive", "group_status_unavailable"),
    ("owner-1", ["User"], False, "archived", "group_status_unavailable"),
])
def test_profile_refusals_are_decided_before_the_body_is_read(env, caller, roles, narrowed, status, reason):
    reseed(env, status=status)
    env.settings["require_member_of_create_group"] = narrowed
    env.as_user(caller, roles)
    before = env.stored_group(GROUP)
    assert_error(env.call("PATCH", PROFILE_PATH, raw="not json"), 403, reason)
    assert_error(patch_profile(env, name="Renamed"), 403, reason)
    assert_untouched(env, before)
    assert env.bumps == []


def test_the_owner_holding_the_creation_role_may_rename_when_creation_is_narrowed(env):
    env.settings["require_member_of_create_group"] = True
    env.as_user("owner-1", ["User", "CreateGroups"])
    written(env, patch_profile(env, name="Allowed"))


def test_an_upload_disabled_group_can_still_be_renamed(env):
    reseed(env, status="upload_disabled")
    written(env, patch_profile(env, name="Renamed"))


def test_the_profile_route_takes_no_query_parameters(env):
    response = env.call("PATCH", PROFILE_PATH, {"revision": env.revision("profile"), "name": "x"},
                        query_string={"group_id": "group-2"})
    assert_invalid(response, "This request does not accept query parameters.")
    assert_untouched(env)


# ---------------------------------------------------------------------------
# The etag guard
# ---------------------------------------------------------------------------

def test_a_membership_change_landing_mid_write_is_kept(env):
    concurrently(env, lambda group: group["pendingUsers"].append(person("applicant-1")))
    written(env, patch_profile(env, name="Renamed"))
    stored = env.stored_group(GROUP)
    assert stored["name"] == "Renamed"
    assert [entry["userId"] for entry in stored["pendingUsers"]] == ["applicant-1"]
    assert [call[0] for call in env.write_calls()] == ["replace_item", "replace_item"]


def test_a_group_deleted_mid_write_is_not_recreated(env):
    env.groups.before_replace.append(lambda: env.groups.records.clear())
    response = patch_profile(env, name="Renamed")
    assert response.status_code == 404
    assert answer(response) == NOT_FOUND
    assert env.groups.records == {}
    assert [call[0] for call in env.write_calls()] == ["replace_item"]
    assert env.bumps == []


def test_a_group_that_keeps_changing_is_a_conflict(env):
    for _ in range(3):
        concurrently(env, lambda group: group["users"].append(person("applicant-1")))
    response = patch_profile(env, name="Renamed")
    assert response.status_code == 409
    assert answer(response) == WRITE_CONFLICT
    assert env.stored_group(GROUP)["name"] == "Group group-1"
    assert env.bumps == []


@pytest.mark.parametrize("change,expected", [
    (lambda group: group.update(owner={"id": "admin-1", "displayName": "Adam Admin"}), (403, "group_owner_required")),
    (lambda group: group.update(status="locked"), (403, "group_status_unavailable")),
    (lambda group: group.update(name="Someone else's rename"), (409, "group_settings_changed")),
    (lambda group: group.update(owner={"id": "admin-1"}, users=[person("admin-1")]), (403, "group_access_denied")),
])
def test_a_change_landing_mid_write_is_checked_on_the_fresh_copy(env, change, expected):
    concurrently(env, change)
    response = patch_profile(env, name="Renamed")
    assert_error(response, *expected)
    assert env.stored_group(GROUP)["name"] != "Renamed"
    assert env.bumps == []


def test_a_storage_failure_mid_write_is_a_data_free_500(env, monkeypatch):
    def unavailable(*args, **kwargs):
        raise cosmos_exceptions.CosmosHttpResponseError(status_code=503, message="account-key-in-a-cosmos-message")
    monkeypatch.setattr(env.groups, "replace_item", unavailable)
    response = patch_profile(env, name="Renamed")
    body = assert_error(response, 500, "group_settings_unavailable",
                        "The group settings request could not be completed. Try again.")
    assert "account-key" not in response.get_data(as_text=True)
    assert env.logs[-1] == ("[WORKSPACE_ROUTE] Group settings request failed.", 40,
                            {"error_type": "CosmosHttpResponseError"})
    assert body and env.stored_group(GROUP)["name"] == "Group group-1"


# ---------------------------------------------------------------------------
# Logo
# ---------------------------------------------------------------------------

def test_the_owner_replaces_the_logo_through_the_shared_branding_helper(env):
    reseed(env, logoVersion=7)
    settings = written(env, put_logo(env, png_bytes(40, 900)))
    image = stored_logo_image(env)
    assert image.format == "PNG" and image.height == 500
    assert env.stored_group(GROUP)["logoVersion"] == 8
    assert settings["logo"] == {"has_logo": True, "logo_version": 8, "logo_url": "/api/groups/group-1/logo?v=8",
                                "revision": env.revision("logo")}
    assert env.bumps == []


def test_a_jpeg_logo_is_stored_as_png(env):
    written(env, put_logo(env, jpeg_bytes(), "photo.JPEG"))
    assert stored_logo_image(env).format == "PNG"
    assert env.stored_group(GROUP)["logoVersion"] == 2


def test_an_unreadable_stored_logo_version_restarts_from_one(env):
    reseed(env, logoVersion="seven")
    written(env, put_logo(env))
    assert env.stored_group(GROUP)["logoVersion"] == 2


def truncated_png():
    return png_bytes(64, 64)[:60]


@pytest.mark.parametrize("content,filename,message", [
    (b"not an image", "brandmark.png", UNREADABLE_LOGO),
    (None, "brandmark.gif", "The logo must be a PNG or JPEG image."),
    (None, "brandmark", "The logo must be a PNG or JPEG image."),
    ("gif", "brandmark.png", UNREADABLE_LOGO),
    ("bomb", "brandmark.png", UNREADABLE_LOGO),
    ("truncated", "brandmark.png", UNREADABLE_LOGO),
    (None, "", "Choose a PNG or JPEG image for the logo."),
])
def test_logo_files_that_cannot_be_used_are_refused_without_their_details(env, content, filename, message):
    content = {"gif": gif_bytes, "bomb": decompression_bomb_png, "truncated": truncated_png}.get(content, lambda: content)()
    before = env.stored_group(GROUP)
    response = put_logo(env, content, filename)
    assert_invalid(response, message)
    text = response.get_data(as_text=True).lower()
    for detail in ("pil", "identify", "decompression", "truncated", "pixels", "brandmark"):
        assert detail not in text, detail
    assert_untouched(env, before)


def test_a_logo_too_large_to_store_on_the_group_is_refused(env, monkeypatch):
    monkeypatch.setattr(env.modules.settings, "GROUP_LOGO_MAX_STORED_LENGTH", 16)
    assert_invalid(put_logo(env), "This logo is too large to store. Use a smaller image.")
    assert_untouched(env)


def test_the_logo_limit_keeps_the_group_document_well_inside_the_item_limit(env):
    assert env.modules.settings.GROUP_LOGO_MAX_STORED_LENGTH == 1024 * 1024


@pytest.mark.parametrize("case,message", [
    ("json", "Upload the logo as multipart form data with a logo_file and the logo revision."),
    ("no_file", "Choose a PNG or JPEG image for the logo."),
    ("extra_field", "Only a logo_file and the logo revision can be sent."),
    ("extra_file", "Only a logo_file and the logo revision can be sent."),
    ("two_files", "Send one logo_file and one revision."),
    ("two_revisions", "Send one logo_file and one revision."),
    ("no_revision", NO_REVISION),
])
def test_logo_uploads_must_be_one_file_and_one_revision(env, case, message):
    revision = env.revision("logo")
    upload = (BytesIO(png_bytes()), "logo.png")
    data = {
        "no_file": {"revision": revision},
        "extra_field": {"logo_file": upload, "revision": revision, "name": "x"},
        "extra_file": {"logo_file": upload, "revision": revision, "other": (BytesIO(b"x"), "x.png")},
        "two_files": {"logo_file": [upload, (BytesIO(png_bytes()), "second.png")], "revision": revision},
        "two_revisions": {"logo_file": upload, "revision": [revision, revision]},
        "no_revision": {"logo_file": upload},
    }.get(case)
    if case == "json":
        response = env.call("PUT", LOGO_PATH, {"revision": revision})
    else:
        response = env.call("PUT", LOGO_PATH, data=data)
    assert_invalid(response, message)
    assert_untouched(env)


def test_a_stale_logo_revision_is_refused(env):
    opened = env.revision("logo")
    written(env, put_logo(env))
    response = put_logo(env, revision=opened)
    assert response.status_code == 409 and answer(response) == CHANGED
    assert env.stored_group(GROUP)["logoVersion"] == 2


@pytest.mark.parametrize("caller,status,reason", [
    ("admin-1", "active", "group_owner_required"),
    ("member-1", "active", "group_owner_required"),
    ("owner-1", "locked", "group_status_unavailable"),
    ("owner-1", "inactive", "group_status_unavailable"),
    ("owner-1", "archived", "group_status_unavailable"),
])
def test_logo_refusals_are_decided_before_the_upload_is_read(env, caller, status, reason):
    reseed(env, status=status, logoBase64="c3RvcmVk")
    env.as_user(caller)
    before = env.stored_group(GROUP)
    assert_error(env.call("PUT", LOGO_PATH, {"not": "multipart"}), 403, reason)
    assert_error(put_logo(env), 403, reason)
    assert_error(delete_logo(env), 403, reason)
    assert_untouched(env, before)


def test_the_logo_ignores_the_creation_narrowing(env):
    env.settings["require_member_of_create_group"] = True
    written(env, put_logo(env))


def test_the_owner_removes_the_logo(env):
    reseed(env, logoBase64="c3RvcmVk", logoVersion=3)
    settings = written(env, delete_logo(env))
    stored = env.stored_group(GROUP)
    assert (stored["logoBase64"], stored["logoVersion"]) == ("", 4)
    assert settings["logo"] == {"has_logo": False, "logo_version": 4, "logo_url": None,
                                "revision": env.revision("logo")}
    assert env.bumps == []


@pytest.mark.parametrize("stored_logo", ["", "   ", None])
def test_removing_a_logo_that_is_not_there_is_a_conflict(env, stored_logo):
    reseed(env, logoBase64=stored_logo)
    before = env.stored_group(GROUP)
    response = delete_logo(env)
    assert response.status_code == 409
    assert answer(response) == {"error": "This group has no logo to remove.", "error_code": "no_group_logo"}
    assert env.stored_group(GROUP) == before


@pytest.mark.parametrize("body,message", [
    ({}, NO_REVISION),
    ({"revision": "r", "logo_file": "x"}, "Only the logo revision can be sent to remove the logo."),
])
def test_logo_removal_takes_only_the_revision(env, body, message):
    reseed(env, logoBase64="c3RvcmVk")
    assert_invalid(env.call("DELETE", LOGO_PATH, body), message)
    assert_untouched(env)


def test_a_logo_removed_by_someone_else_mid_write_is_a_changed_section(env):
    reseed(env, logoBase64="c3RvcmVk", logoVersion=3)
    concurrently(env, lambda group: group.update(logoBase64="", logoVersion=4))
    assert answer(delete_logo(env)) == CHANGED


# ---------------------------------------------------------------------------
# Downloads
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("caller", ["owner-1", "admin-1"])
def test_the_owner_or_an_admin_sets_the_download_switch(env, caller):
    env.as_user(caller)
    settings = written(env, patch_downloads(env, True))
    assert env.stored_group(GROUP)["disable_file_downloads"] is True
    assert settings["downloads"] == {"disable_file_downloads": True, "file_downloads_enabled": False,
                                     "revision": env.revision("downloads")}
    assert env.bumps == ["group_updated"]
    written(env, patch_downloads(env, False))
    assert env.stored_group(GROUP)["disable_file_downloads"] is False


@pytest.mark.parametrize("value", ["true", 1, 0, None, [], {"value": True}])
def test_the_download_switch_is_a_boolean_only(env, value):
    assert_invalid(patch_downloads(env, value), "Set disable_file_downloads to true or false.")
    assert_untouched(env)


def test_the_download_body_takes_only_the_switch(env):
    assert_invalid(env.call("PATCH", DOWNLOADS_PATH, {"revision": env.revision("downloads")}),
                   "Set disable_file_downloads to true or false.")
    assert_invalid(env.call("PATCH", DOWNLOADS_PATH, {"revision": env.revision("downloads"),
                                                      "disable_file_downloads": True, "name": "x"}),
                   "Only disable_file_downloads can be changed here.")
    assert_untouched(env)


@pytest.mark.parametrize("caller,changes,reason", [
    ("owner-1", {"allow_group_workspace_file_downloads": False}, "group_downloads_not_enabled"),
    ("admin-1", {"require_group_assignment_for_file_downloads": True,
                 "file_download_allowed_group_ids": [OTHER_GROUP]}, "group_downloads_not_enabled"),
    ("manager-1", {}, "group_manager_required"),
    ("member-1", {}, "group_manager_required"),
])
def test_download_refusals(env, caller, changes, reason):
    env.settings.update(changes)
    env.as_user(caller)
    assert_error(env.call("PATCH", DOWNLOADS_PATH, raw="not json"), 403, reason)
    assert_error(patch_downloads(env, True), 403, reason)
    assert_untouched(env)


def test_the_download_refusal_is_reviewed(env):
    env.settings["allow_group_workspace_file_downloads"] = False
    assert_error(patch_downloads(env, True), 403, "group_downloads_not_enabled",
                 "An administrator hasn't turned on file downloads for this group.")


def test_an_assigned_group_may_change_its_download_switch(env):
    env.seed_group(ASSIGNED_GROUP, status="active")
    env.settings.update({"require_group_assignment_for_file_downloads": True,
                         "file_download_allowed_group_ids": [ASSIGNED_GROUP]})
    env.as_user("admin-1")
    response = env.call("PATCH", f"/api/groups/{ASSIGNED_GROUP}/settings/downloads", {
        "revision": env.revision("downloads", ASSIGNED_GROUP), "disable_file_downloads": True,
    })
    assert answer(response)["settings"]["downloads"]["disable_file_downloads"] is True
    assert env.stored_group(ASSIGNED_GROUP)["disable_file_downloads"] is True


@pytest.mark.parametrize("status", ["locked", "inactive", "upload_disabled", "archived"])
def test_downloads_can_be_changed_in_every_status(env, status):
    reseed(env, status=status)
    written(env, patch_downloads(env, True))


def test_an_admin_demoted_mid_write_is_refused(env):
    env.as_user("admin-1")
    concurrently(env, lambda group: group.update(admins=[]))
    assert_error(patch_downloads(env, True), 403, "group_manager_required")
    assert env.stored_group(GROUP)["disable_file_downloads"] is False


# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------

def test_retention_values_are_merged_into_the_stored_policy(env):
    reseed(env, retention_policy={"conversation_retention_days": 30, "document_retention_days": 60,
                                  "kept_from_elsewhere": "yes"})
    settings = written(env, patch_retention(env, conversation_retention_days=90))
    assert env.stored_group(GROUP)["retention_policy"] == {
        "conversation_retention_days": 90, "document_retention_days": 60, "kept_from_elsewhere": "yes",
    }
    assert (settings["retention"]["conversation_retention_days"], settings["retention"]["document_retention_days"]) == (90, 60)
    assert env.bumps == []


@pytest.mark.parametrize("value", ["default", "none"])
def test_default_and_none_are_stored_as_the_strings_seeding_uses(env, value):
    written(env, patch_retention(env, conversation_retention_days=value, document_retention_days=value))
    assert env.stored_group(GROUP)["retention_policy"] == {"conversation_retention_days": value,
                                                          "document_retention_days": value}


@pytest.mark.parametrize("stored", [None, "none", ["x"]])
def test_a_malformed_stored_policy_is_replaced_by_the_values_sent(env, stored):
    reseed(env, retention_policy=stored)
    written(env, patch_retention(env, document_retention_days=45))
    assert env.stored_group(GROUP)["retention_policy"] == {"document_retention_days": 45}


WHOLE_DAYS = 'retention must be a whole number of days, "none" or "default".'


@pytest.mark.parametrize("value", ["30", True, False, 30.0, 30.5, None, [], {}, "Default", "NONE", ""])
@pytest.mark.parametrize("field,label", [("conversation_retention_days", "Conversation"),
                                         ("document_retention_days", "Document")])
def test_retention_values_are_strictly_typed(env, field, label, value):
    assert_invalid(patch_retention(env, **{field: value}), f"{label} {WHOLE_DAYS}")
    assert_untouched(env)


@pytest.mark.parametrize("literal", ["Infinity", "-Infinity", "NaN"])
def test_non_finite_json_numbers_are_refused(env, literal):
    raw = '{"revision": "%s", "conversation_retention_days": %s}' % (env.revision("retention"), literal)
    assert_invalid(env.call("PATCH", RETENTION_PATH, raw=raw), f"Conversation {WHOLE_DAYS}")
    assert_untouched(env)


@pytest.mark.parametrize("field,label,value", [
    ("conversation_retention_days", "Conversation", 0),
    ("conversation_retention_days", "Conversation", 3651),
    ("document_retention_days", "Document", -1),
    ("document_retention_days", "Document", 10 ** 30),
])
def test_retention_days_must_be_within_the_bounds(env, field, label, value):
    assert_invalid(patch_retention(env, **{field: value}), f"{label} retention must be between 1 and 3650 days.")
    assert_untouched(env)


def test_the_bounds_are_read_from_the_settings_for_each_kind(env):
    env.settings.update({"retention_conversation_min_days": 7, "retention_conversation_max_days": 90,
                         "retention_document_min_days": 30, "retention_document_max_days": 365})
    assert_invalid(patch_retention(env, conversation_retention_days=6),
                   "Conversation retention must be between 7 and 90 days.")
    assert_invalid(patch_retention(env, document_retention_days=366),
                   "Document retention must be between 30 and 365 days.")
    written(env, patch_retention(env, conversation_retention_days=7, document_retention_days=365))


def test_the_retention_body_names_what_it_changes(env):
    assert_invalid(patch_retention(env), "Include conversation_retention_days or document_retention_days to change.")
    assert_invalid(patch_retention(env, retention_policy={}),
                   "Only conversation_retention_days and document_retention_days can be changed here.")
    assert_untouched(env)


@pytest.mark.parametrize("caller,changes,reason", [
    ("owner-1", {"enable_retention_policy_group": False}, "group_retention_disabled"),
    ("admin-1", {"enable_retention_policy_group": False}, "group_retention_disabled"),
    ("manager-1", {}, "group_manager_required"),
    ("member-1", {}, "group_manager_required"),
])
def test_retention_refusals(env, caller, changes, reason):
    env.settings.update(changes)
    env.as_user(caller)
    assert_error(env.call("PATCH", RETENTION_PATH, raw="not json"), 403, reason)
    assert_error(patch_retention(env, conversation_retention_days=30), 403, reason)
    assert_untouched(env)


def test_the_retention_refusal_is_reviewed(env):
    env.settings["enable_retention_policy_group"] = False
    assert_error(patch_retention(env, conversation_retention_days=30), 403, "group_retention_disabled",
                 "Retention policies aren't turned on for group workspaces.")


@pytest.mark.parametrize("status", ["locked", "inactive", "archived"])
def test_retention_can_be_changed_in_every_status(env, status):
    reseed(env, status=status)
    written(env, patch_retention(env, conversation_retention_days="none"))


@pytest.mark.parametrize("status,message", [
    ("locked", "This group is locked or inactive, so its name, description, color and logo can't be changed."),
    ("inactive", "This group is locked or inactive, so its name, description, color and logo can't be changed."),
    ("archived", "This group's status isn't recognized, so its name, description, color and logo can't be changed."),
])
def test_a_status_refusal_names_its_cause(env, status, message):
    """A status this version doesn't recognize fails closed for the profile and logo, as the
    workspace context and adding a member do, and says so rather than calling it locked."""
    reseed(env, status=status, logoBase64="c3RvcmVk")
    before = env.stored_group(GROUP)
    assert_error(patch_profile(env, name="Renamed"), 403, "group_status_unavailable", message)
    assert_error(put_logo(env), 403, "group_status_unavailable", message)
    assert_untouched(env, before)


# ---------------------------------------------------------------------------
# The boundary
# ---------------------------------------------------------------------------

ROUTES = [
    ("GET", SETTINGS_PATH),
    ("PATCH", PROFILE_PATH),
    ("PUT", LOGO_PATH),
    ("DELETE", LOGO_PATH),
    ("PATCH", DOWNLOADS_PATH),
    ("PATCH", RETENTION_PATH),
]


@pytest.mark.parametrize("method,path", ROUTES)
def test_every_route_needs_a_session_the_user_role_and_group_workspaces(env, method, path):
    env.sign_out()
    signed_out = env.call(method, path)
    assert signed_out.status_code == 401
    assert signed_out.get_json() == {"error": "Unauthorized", "message": "Authentication required"}

    env.as_user("owner-1", ["CreateGroups"])
    no_role = env.call(method, path)
    assert no_role.status_code == 403
    assert no_role.get_json()["message"] == "Insufficient permissions (User/Admin role required)"

    env.as_user("owner-1")
    env.settings["enable_group_workspaces"] = False
    disabled = env.call(method, path)
    assert disabled.status_code == 400
    assert disabled.get_json() == {"error": "Enable Group Workspaces is disabled."}
    assert_untouched(env)


@pytest.mark.parametrize("method,path", ROUTES)
def test_every_route_answers_a_missing_group_and_a_non_member_alike(env, method, path):
    env.as_user("outsider-1")
    assert_error(env.call(method, path), 403, "group_access_denied", "You do not have access to the selected group.")
    env.as_user("owner-1")
    assert_error(env.call(method, path.replace(GROUP, "group-9")), 404, "group_not_found", "Group not found.")
    assert_untouched(env)


@pytest.mark.parametrize("method,path", ROUTES)
def test_an_invalid_group_id_never_reaches_storage(env, method, path):
    assert_invalid(env.call(method, path.replace(GROUP, "group,1")), "Invalid group identifier.")
    assert [call for call in env.groups.calls if call[0] == "read_item"] == []


def test_the_read_takes_no_query_parameters_or_body(env):
    assert_invalid(env.settings_read(query_string={"group_id": "group-2"}),
                   "This request does not accept query parameters.")
    assert_invalid(env.call("GET", SETTINGS_PATH, {"x": 1}), "This request does not accept a request body.")


def test_an_unexpected_failure_is_a_logged_data_free_500(env, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("internal detail: https://account.documents.azure.com")
    monkeypatch.setattr(env.groups, "read_item", broken)
    response = env.settings_read()
    assert_error(response, 500, "group_settings_unavailable",
                 "The group settings request could not be completed. Try again.")
    assert "internal detail" not in response.get_data(as_text=True)
    message, level, extra = env.logs[-1]
    assert (message, extra) == ("[WORKSPACE_ROUTE] Group settings request failed.", {"error_type": "RuntimeError"})
    assert "internal detail" not in repr(env.logs)


def test_no_write_records_activity_or_notifies(env):
    reseed(env, logoBase64="c3RvcmVk")
    for response in (patch_profile(env, name="A"), put_logo(env), delete_logo(env), patch_downloads(env, True),
                     patch_retention(env, conversation_retention_days=30)):
        assert response.status_code == 200, response.get_json()
    assert_quiet(env)
    assert env.bumps == ["group_updated", "group_updated"]
    stored = env.stored_group(GROUP)
    assert [entry["userId"] for entry in stored["users"]] == ["owner-1", "admin-1", "manager-1", "member-1"]
    assert stored["model_endpoints"] == copy.deepcopy(
        [{"id": "ep-1", "auth": {"type": "api_key", "api_key": "sk-secret-endpoint-key"}}]
    )
