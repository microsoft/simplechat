# test_group_settings_legacy_fixes.py
"""
Functional test for the classic group settings fixes: the file count, data-free errors and retention.
Version: 0.261.153
Implemented in: 0.261.153

Run for real in ``test_support/group_settings_harness.py``:

- ``GET /api/groups/<group_id>/fileCount`` counted ``f.groupId``, a field group
  documents never carry, so it always answered 0 and the classic manage page never
  asked the owner to remove the group's documents before deleting it. It now counts
  the group's own current documents with ``count_current_group_documents``, the
  predicate the group document list uses (``test_group_document_count_predicate.py``),
  as the native ``/insights/file-count`` does;
- the classic rename, download settings and logo routes put exception text (Pillow and
  Cosmos messages) in their errors. They now answer reviewed, data-free text, and log
  only the error type and status;
- ``POST /api/retention-policy/group/<group_id>`` replaced the whole policy with the
  values sent, refused ``"default"`` (which the classic page offers, posts on every
  save, and new groups are seeded with), stored ``true`` as 1 day, answered a list, an
  object or a non-finite number with a 500, and checked neither group workspaces nor
  group retention policies. It now merges, accepts ``"default"``, answers those values
  with its existing 400 texts, and is gated as the native route is: 400 when group
  workspaces are off, 403 ``group_retention_disabled`` when group retention policies
  are, before the group is read. The defaults route stays ungated.
"""

import logging
from io import BytesIO

import pytest
from azure.cosmos import exceptions as cosmos_exceptions
from PIL import Image

from test_support.group_settings_harness import group_settings_environment, png_bytes


GROUP = "group-1"
RETENTION_PATH = f"/api/retention-policy/group/{GROUP}"
SECRET = "AccountKey=abc123; https://account.documents.azure.com:443/"
RETENTION_DISABLED = {"success": False, "error": "Retention policies aren't turned on for group workspaces.",
                      "error_code": "group_retention_disabled"}


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


def outcome(response):
    return response.status_code, response.get_json()


def reseed(env, **fields):
    env.groups.records.clear()
    return env.seed_group(GROUP, status="active", **fields)


def reads(env):
    return [call for call in env.groups.calls if call[0] == "read_item"]


# ---------------------------------------------------------------------------
# D2: the classic document count
# ---------------------------------------------------------------------------

def test_the_classic_count_is_the_groups_current_documents(env):
    env.file_count = 5
    assert outcome(env.call("GET", f"/api/groups/{GROUP}/fileCount")) == (200, {"fileCount": 5})
    assert env.file_count_calls == [GROUP]
    assert env.group_documents.queries == []


def test_the_classic_and_native_counts_agree(env):
    env.file_count = 3
    classic = env.call("GET", f"/api/groups/{GROUP}/fileCount").get_json()["fileCount"]
    native = env.call("GET", f"/api/groups/{GROUP}/insights/file-count").get_json()["file_count"]
    assert classic == native == 3


@pytest.mark.parametrize("caller,expected", [
    ("admin-1", (403, {"error": "Only the owner can check file count"})),
    ("member-1", (403, {"error": "Only the owner can check file count"})),
])
def test_only_the_owner_reads_the_classic_count(env, caller, expected):
    env.as_user(caller)
    assert outcome(env.call("GET", f"/api/groups/{GROUP}/fileCount")) == expected
    assert env.file_count_calls == []


def test_a_missing_group_has_no_classic_count(env):
    assert outcome(env.call("GET", "/api/groups/group-9/fileCount")) == (404, {"error": "Group not found"})
    assert env.file_count_calls == []


# ---------------------------------------------------------------------------
# D3(i): data-free errors
# ---------------------------------------------------------------------------

def logo_upload(content=None, filename="brandmark.png"):
    return {"logo_file": (BytesIO(png_bytes() if content is None else content), filename)}


STORAGE_FAILURES = [
    ("PATCH", f"/api/groups/{GROUP}", {"name": "Renamed"}, "The group could not be saved. Try again.",
     "[GROUP_SETTINGS] Classic group update failed."),
    ("PUT", f"/api/groups/{GROUP}", {"name": "Renamed"}, "The group could not be saved. Try again.",
     "[GROUP_SETTINGS] Classic group update failed."),
    ("PATCH", f"/api/groups/{GROUP}/download-settings", {"disable_file_downloads": True},
     "The download settings could not be saved. Try again.", "[GROUP_SETTINGS] Classic download settings save failed."),
    ("POST", f"/api/groups/{GROUP}/logo", None, "The logo could not be saved. Try again.",
     "[GROUP_SETTINGS] Classic group logo save failed."),
]


@pytest.mark.parametrize("method,path,body,message,log", STORAGE_FAILURES)
def test_a_storage_failure_answers_reviewed_text_and_logs_no_detail(env, monkeypatch, method, path, body, message, log):
    def unavailable(*args, **kwargs):
        raise cosmos_exceptions.CosmosHttpResponseError(status_code=503, message=SECRET)
    monkeypatch.setattr(env.groups, "replace_item", unavailable)
    response = env.call(method, path, body) if body is not None else env.call(method, path, data=logo_upload())
    assert outcome(response) == (400, {"error": message})
    assert "AccountKey" not in response.get_data(as_text=True)
    assert env.logs[-1] == (log, logging.ERROR,
                            {"group_id": GROUP, "error_type": "CosmosHttpResponseError", "status_code": 503})
    assert "AccountKey" not in repr(env.logs)
    assert env.bumps == []


def gif_bytes():
    output = BytesIO()
    Image.new("RGB", (4, 4)).save(output, format="GIF")
    return output.getvalue()


@pytest.mark.parametrize("content", [b"not an image", png_bytes(64, 64)[:60], gif_bytes()],
                         ids=["text", "truncated_png", "gif"])
def test_an_unreadable_logo_answers_reviewed_text(env, content):
    response = env.call("POST", f"/api/groups/{GROUP}/logo", data=logo_upload(content))
    assert outcome(response) == (400, {"error": "The logo image could not be read. Upload a PNG or JPEG image."})
    text = response.get_data(as_text=True).lower()
    for detail in ("cannot identify", "truncated", "brandmark", "pil"):
        assert detail not in text
    assert env.write_calls() == []


# ---------------------------------------------------------------------------
# D4: classic group retention
# ---------------------------------------------------------------------------

def post_retention(env, body, caller="owner-1"):
    env.as_user(caller)
    return env.call("POST", RETENTION_PATH, body)


SAVED = (200, {"success": True, "message": "Group retention settings updated successfully"})


def test_the_values_sent_are_merged_into_the_stored_policy(env):
    reseed(env, retention_policy={"conversation_retention_days": 30, "document_retention_days": 90,
                                  "kept_from_elsewhere": "yes"})
    assert outcome(post_retention(env, {"conversation_retention_days": 45})) == SAVED
    assert env.stored_group(GROUP)["retention_policy"] == {
        "conversation_retention_days": 45, "document_retention_days": 90, "kept_from_elsewhere": "yes",
    }


@pytest.mark.parametrize("stored", [None, "none", ["x"]])
def test_a_malformed_stored_policy_is_replaced_by_the_values_sent(env, stored):
    reseed(env, retention_policy=stored)
    assert outcome(post_retention(env, {"document_retention_days": 60})) == SAVED
    assert env.stored_group(GROUP)["retention_policy"] == {"document_retention_days": 60}


def test_the_classic_page_can_save_both_organization_defaults(env):
    reseed(env, retention_policy={"conversation_retention_days": 30, "document_retention_days": 90})
    body = {"conversation_retention_days": "default", "document_retention_days": "default"}
    assert outcome(post_retention(env, body)) == SAVED
    assert env.stored_group(GROUP)["retention_policy"] == body


@pytest.mark.parametrize("field", ["conversation_retention_days", "document_retention_days"])
def test_default_is_stored_as_the_string_seeding_uses(env, field):
    reseed(env, retention_policy={"conversation_retention_days": 30, "document_retention_days": 90})
    assert outcome(post_retention(env, {field: "default"})) == SAVED
    assert env.stored_group(GROUP)["retention_policy"][field] == "default"


FIELDS = [("conversation_retention_days", "conversation"), ("document_retention_days", "document")]


@pytest.mark.parametrize("value", [True, False, [30], [], {"days": 30}, {}], ids=repr)
@pytest.mark.parametrize("field,kind", FIELDS)
def test_values_that_are_not_a_number_of_days_get_the_existing_400(env, field, kind, value):
    before = env.stored_group(GROUP)
    assert outcome(post_retention(env, {field: value})) == (
        400, {"success": False, "error": f"Invalid {kind} retention value"},
    )
    assert env.stored_group(GROUP) == before and env.write_calls() == []


@pytest.mark.parametrize("literal", ["Infinity", "-Infinity", "NaN"])
@pytest.mark.parametrize("field,kind", FIELDS)
def test_non_finite_numbers_get_the_existing_400(env, field, kind, literal):
    env.as_user("owner-1")
    response = env.call("POST", RETENTION_PATH, raw='{"%s": %s}' % (field, literal))
    assert outcome(response) == (400, {"success": False, "error": f"Invalid {kind} retention value"})
    assert env.write_calls() == []


@pytest.mark.parametrize("value,stored", [("30", 30), (30, 30), (45.9, 45), (" 60 ", 60), ("none", "none"), (None, "none")])
def test_the_classic_values_are_still_accepted(env, value, stored):
    assert outcome(post_retention(env, {"conversation_retention_days": value})) == SAVED
    assert env.stored_group(GROUP)["retention_policy"]["conversation_retention_days"] == stored


@pytest.mark.parametrize("body,error", [
    ({"conversation_retention_days": "abc"}, "Invalid conversation retention value"),
    ({"document_retention_days": "Default"}, "Invalid document retention value"),
    ({"conversation_retention_days": 0}, "Conversation retention must be between 1 and 3650 days"),
    ({"document_retention_days": "4000"}, "Document retention must be between 1 and 3650 days"),
    ({}, "No retention settings provided"),
    ({"retention": "default"}, "No retention settings provided"),
])
def test_the_classic_refusals_are_unchanged(env, body, error):
    assert outcome(post_retention(env, body)) == (400, {"success": False, "error": error})
    assert env.write_calls() == []


def test_the_route_needs_group_workspaces(env):
    env.settings["enable_group_workspaces"] = False
    assert outcome(post_retention(env, {"conversation_retention_days": 30})) == (
        400, {"error": "Enable Group Workspaces is disabled."},
    )
    assert reads(env) == [] and env.write_calls() == []


@pytest.mark.parametrize("caller", ["owner-1", "admin-1", "member-1", "outsider-1"])
def test_the_route_needs_group_retention_before_the_group_is_read(env, caller):
    env.settings["enable_retention_policy_group"] = False
    assert outcome(post_retention(env, {"conversation_retention_days": 30}, caller)) == (403, RETENTION_DISABLED)
    assert reads(env) == [] and env.write_calls() == []


def test_the_retention_gate_answers_before_the_body_is_read(env):
    env.settings["enable_retention_policy_group"] = False
    env.as_user("owner-1")
    response = env.call("POST", RETENTION_PATH, raw="not json")
    assert outcome(response) == (403, RETENTION_DISABLED)


def test_the_defaults_route_stays_ungated(env):
    env.settings["enable_retention_policy_group"] = False
    env.settings["enable_group_workspaces"] = False
    response = env.call("GET", "/api/retention-policy/defaults/group")
    assert response.status_code == 200
    assert response.get_json()["success"] is True
