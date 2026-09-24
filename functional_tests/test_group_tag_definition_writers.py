# test_group_tag_definition_writers.py
"""
Functional test for the group tag definition writers on the etag guard.
Version: 0.261.160
Implemented in: 0.261.160

The classic group tag routes (create, rename or recolour, delete) and
``get_or_create_tag_definition`` read the group, changed its ``tag_definitions`` and
upserted that copy back. A change landing in between (a membership or status
change, another tag) was undone, a group deleted in between was recreated, and the
caller's tag role was checked only on the copy read first.

Each now changes the definitions on the copy it writes, through
``update_group_document_with_etag_guard``. This test runs them for real, with the
real ``functions_group`` over the etag-enforcing groups container from
``test_support/group_directory_harness.py``, and pins:

- a concurrent change is kept, and "already exists" is decided on the current copy;
- the caller's tag role is checked again on the current copy, even when no definition
  changes, so a role removed meanwhile refuses the request;
- a deleted group is not recreated, and a group that keeps changing gets the one
  conflict answer with nothing written; nothing is bumped, as before;
- rename and delete change the definition before any document, so a refusal leaves
  every document untouched, and repeating the request after a document failed
  finishes the documents that still carry the old tag;
- ``get_or_create_tag_definition`` adds a definition only while the current copy
  lacks it, answers one added meanwhile, and, for a group that keeps changing,
  answers the tag's default colour and logs a data-free warning.
"""

import copy
import logging
import re
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from flask import Blueprint, Flask, jsonify, request

from test_support.app_source import definitions as source_definitions, refusing_module_stub
from test_support.group_directory_harness import PEOPLE, group_directory_environment, person


GROUP = "group-1"
TAGS = "/api/group_documents/tags"
DEFINED = {"color": "#112233", "created_at": "2026-09-01T00:00:00+00:00"}

ROUTE_MODULE_LEVEL = {
    "_require_active_group_document_context", "GROUP_TAG_MANAGER_ROLES", "GROUP_TAG_PERMISSION_MESSAGE",
    "_GroupTagAnswer", "_save_group_tag_definitions",
}
ROUTE_NESTED = {"api_create_group_tag", "api_update_group_tag", "api_delete_group_tag"}
DOCUMENT_DEFINITIONS = {
    "TAG_COLOR_PATTERN", "normalize_tag", "validate_tags", "normalize_tag_color", "get_safe_tag_color",
    "validate_tag_color", "get_default_tag_color", "_GroupTagDefinitionPresent", "get_or_create_tag_definition",
}


class GroupDocuments:
    """The group documents the classic rename and delete read, and ``update_document`` over them."""

    QUERY = "SELECT * FROM c WHERE c.group_id = @group_id"

    def __init__(self, events):
        self.records = {}
        self.events = events
        self.fail_on = set()

    def seed(self, document_id, tags, group_id=GROUP):
        self.records[document_id] = {
            "id": document_id, "group_id": group_id, "file_name": f"{document_id}.pdf", "version": 1,
            "tags": list(tags),
        }

    def query_items(self, query, parameters=None, enable_cross_partition_query=None, **kwargs):
        if " ".join(query.split()) != self.QUERY:
            raise AssertionError("The tag routes sent a documents query this test does not model")
        values = {parameter["name"]: parameter["value"] for parameter in parameters or []}
        return [copy.deepcopy(record) for record in self.records.values() if record["group_id"] == values["@group_id"]]

    def update_document(self, document_id, group_id, user_id, tags, **kwargs):
        self.events.append(("update_document", document_id))
        if document_id in self.fail_on:
            self.fail_on.discard(document_id)
            raise RuntimeError("The document store is unavailable.")
        self.records[document_id]["tags"] = list(tags)

    def tags(self):
        return {document_id: record["tags"] for document_id, record in self.records.items()}


@contextmanager
def tag_environment():
    with group_directory_environment() as env:
        events = []
        documents = GroupDocuments(events)
        group = env.modules.group
        auth = env.modules.authentication
        active_groups = {}

        document_namespace = {
            "re": re, "datetime": datetime, "timezone": timezone, "logging": logging,
            "log_event": env.log_event, "cosmos_groups_container": env.groups,
        }
        exec(compile(source_definitions("functions_documents.py", DOCUMENT_DEFINITIONS), "functions_documents.py", "exec"),
             document_namespace)
        documents_module = refusing_module_stub(
            "functions_documents.py", "functions_documents",
            normalize_tag=document_namespace["normalize_tag"],
            validate_tags=document_namespace["validate_tags"],
            validate_tag_color=document_namespace["validate_tag_color"],
            update_document=documents.update_document,
            propagate_tags_to_chunks=lambda document_id, tags, user_id, **kwargs: events.append(
                ("propagate_tags_to_chunks", document_id)),
            get_or_create_tag_definition=document_namespace["get_or_create_tag_definition"],
        )

        blueprint = Blueprint("group_tag_writers", __name__)
        namespace = {
            "bp": blueprint,
            "swagger_route": lambda **kwargs: (lambda function: function),
            "get_auth_security": lambda: [{"sessionAuth": []}],
            "login_required": auth.login_required, "user_required": auth.user_required,
            "enabled_required": auth.enabled_required, "get_current_user_id": auth.get_current_user_id,
            "request": request, "jsonify": jsonify,
            "require_active_group": group.require_active_group,
            "find_group_by_id": group.find_group_by_id,
            "get_user_role_in_group": group.get_user_role_in_group,
            "update_group_document_with_etag_guard": group.update_group_document_with_etag_guard,
            "GroupDocumentWriteConflict": group.GroupDocumentWriteConflict,
            "GROUP_WRITE_CONFLICT_MESSAGE": group.GROUP_WRITE_CONFLICT_MESSAGE,
            "GROUP_WRITE_CONFLICT_CODE": group.GROUP_WRITE_CONFLICT_CODE,
            "cosmos_group_documents_container": documents,
            "invalidate_group_search_cache": lambda group_id: events.append(("invalidate", group_id)),
        }
        routes = source_definitions(
            "route_backend_group_documents.py", ROUTE_MODULE_LEVEL,
            register="register_route_backend_group_documents", nested=ROUTE_NESTED,
        )
        exec(compile(routes, "route_backend_group_documents.py", "exec"), namespace)

        app = Flask("group_tag_writers")
        app.config.update(TESTING=True, SECRET_KEY="test-only-session-key")
        app.register_blueprint(blueprint)
        client = app.test_client()

        real_replace = env.groups.replace_item

        def replace_item(item, body, **kwargs):
            events.append(("group_write", item))
            return real_replace(item, body, **kwargs)

        def as_user(user_id, group_id=GROUP):
            name, email = PEOPLE.get(user_id, (f"Name {user_id}", f"{user_id}@example.test"))
            active_groups[user_id] = group_id
            with client.session_transaction() as state:
                state["user"] = {"oid": user_id, "roles": ["User"], "name": name, "preferred_username": email}

        def reset():
            env.reset()
            events.clear()
            documents.records.clear()
            documents.fail_on.clear()
            active_groups.clear()
            env.seed_group(GROUP, status="active")
            as_user("manager-1")

        user_settings = lambda user_id, *args, **kwargs: {  # noqa: E731
            "id": user_id, "settings": {"activeGroupOid": active_groups.get(user_id)},
        }
        with patch.object(env.modules.settings, "get_user_settings", user_settings), \
                patch.object(env.groups, "replace_item", replace_item, create=True), \
                patch.dict(sys.modules, {"functions_documents": documents_module}):
            env.tags = SimpleNamespace(
                client=client, documents=documents, events=events, as_user=as_user, reset=reset,
                definitions=document_namespace, namespace=namespace,
            )
            yield env


@pytest.fixture(scope="module")
def module_env():
    with tag_environment() as env:
        yield env


@pytest.fixture
def env(module_env):
    module_env.tags.reset()
    yield module_env
    module_env.tags.reset()


def definitions(env):
    return env.stored_group(GROUP).get("tag_definitions", {})


def define(env, **tags):
    stored = env.stored_group(GROUP)
    stored["tag_definitions"] = copy.deepcopy(tags)
    env.groups.seed(stored)


def concurrently(env, change):
    def land():
        stored = env.stored_group(GROUP)
        change(stored)
        env.groups.seed(stored)
    env.groups.before_replace.append(land)


def keep_changing(env):
    for index in range(env.modules.group.GROUP_DOCUMENT_WRITE_ATTEMPTS):
        concurrently(env, lambda group, index=index: group["users"].append(person("applicant-1") | {"userId": f"late-{index}"}))


def after_read(env, monkeypatch, number, change):
    """Land ``change`` on the stored group right after the Nth read of it."""
    real_read = env.groups.read_item
    reads = []

    def read_item(item, partition_key, **kwargs):
        record = real_read(item, partition_key, **kwargs)
        reads.append(item)
        if len(reads) == number:
            stored = env.stored_group(GROUP)
            if change is None:
                env.groups.records.clear()
            else:
                change(stored)
                env.groups.seed(stored)
        return record

    monkeypatch.setattr(env.groups, "read_item", read_item)


# The route reads the group twice (the role check, then the context) before the
# guarded write reads it, so a change after read 2 lands between them.
BEFORE_THE_WRITE = 2


def demote(group):
    group["documentManagers"].remove("manager-1")


def group_writes(env):
    return [event for event in env.tags.events if event[0] == "group_write"]


def document_updates(env):
    return [event for event in env.tags.events if event[0] == "update_document"]


def conflict(env):
    return {"error": env.modules.group.GROUP_WRITE_CONFLICT_MESSAGE, "error_code": "group_write_conflict"}


def create(env, tag="alpha", color="#abcdef"):
    return env.tags.client.post(TAGS, json={"tag_name": tag, "color": color})


def rename(env, old="alpha", new="gamma"):
    return env.tags.client.patch(f"{TAGS}/{old}", json={"new_name": new})


def recolor(env, tag="alpha", color="#445566"):
    return env.tags.client.patch(f"{TAGS}/{tag}", json={"color": color})


def delete(env, tag="alpha"):
    return env.tags.client.delete(f"{TAGS}/{tag}")


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

def test_a_tag_is_created_on_the_current_copy(env):
    concurrently(env, lambda group: group["pendingUsers"].append(person("applicant-1")))
    response = create(env)
    assert (response.status_code, response.get_json()) == (201, {
        "message": 'Tag "alpha" created successfully', "tag": {"name": "alpha", "color": "#abcdef"},
    })
    stored = env.stored_group(GROUP)
    assert stored["tag_definitions"]["alpha"]["color"] == "#abcdef"
    assert datetime.fromisoformat(stored["tag_definitions"]["alpha"]["created_at"]).tzinfo is not None
    assert [entry["userId"] for entry in stored["pendingUsers"]] == ["applicant-1"]
    assert len(group_writes(env)) == 2 and env.bumps == []


def test_a_tag_created_meanwhile_is_refused_not_replaced(env):
    concurrently(env, lambda group: group.update(tag_definitions={"alpha": dict(DEFINED)}))
    response = create(env)
    assert (response.status_code, response.get_json()) == (409, {"error": "Tag already exists"})
    assert definitions(env) == {"alpha": DEFINED}


def test_an_existing_tag_is_refused_without_a_write(env):
    define(env, alpha=DEFINED)
    response = create(env)
    assert (response.status_code, response.get_json()) == (409, {"error": "Tag already exists"})
    assert group_writes(env) == [] and definitions(env) == {"alpha": DEFINED}


def test_other_definitions_on_the_current_copy_are_kept(env):
    define(env, beta=DEFINED)
    concurrently(env, lambda group: group["tag_definitions"].update(delta=dict(DEFINED)))
    create(env)
    assert sorted(definitions(env)) == ["alpha", "beta", "delta"]


def test_a_manager_who_lost_the_role_meanwhile_cannot_create(env):
    concurrently(env, demote)
    response = create(env)
    assert (response.status_code, response.get_json()) == (403, {"error": "You do not have permission to manage tags"})
    assert definitions(env) == {}


def test_creating_on_a_deleted_group_does_not_recreate_it(env):
    env.groups.before_replace.append(lambda: env.groups.records.clear())
    response = create(env)
    assert (response.status_code, response.get_json()) == (404, {"error": "Active group not found"})
    assert env.groups.records == {}


def test_creating_on_a_group_that_keeps_changing_answers_the_conflict(env):
    keep_changing(env)
    response = create(env)
    assert (response.status_code, response.get_json()) == (409, conflict(env))
    assert definitions(env) == {} and env.bumps == []


@pytest.mark.parametrize("user_id", ["owner-1", "admin-1", "manager-1"])
def test_every_tag_manager_role_can_create(env, user_id):
    env.tags.as_user(user_id)
    assert create(env).status_code == 201


@pytest.mark.parametrize("call,expected", [
    (lambda env: env.tags.client.post(TAGS, json={"color": "#abcdef"}), (400, {"error": "tag_name is required"})),
    (lambda env: create(env, color="blue"), (400, {"error": "Tag color must be a valid 3- or 6-digit hex color"})),
    (lambda env: env.tags.client.patch(f"{TAGS}/alpha", json={}), (400, {"error": "No updates specified"})),
])
def test_the_classic_refusals_are_unchanged(env, call, expected):
    response = call(env)
    assert (response.status_code, response.get_json()) == expected
    assert group_writes(env) == []


def test_a_member_still_cannot_manage_tags(env):
    env.tags.as_user("member-1")
    for response in (create(env), rename(env), recolor(env), delete(env)):
        assert (response.status_code, response.get_json()) == (403, {"error": "You do not have permission to manage tags"})
    assert group_writes(env) == [] and document_updates(env) == []


# ---------------------------------------------------------------------------
# Rename and recolour
# ---------------------------------------------------------------------------

def seed_tagged_documents(env):
    env.tags.documents.seed("d1", ["alpha"])
    env.tags.documents.seed("d2", ["alpha", "beta"])
    env.tags.documents.seed("d3", ["beta"])
    env.tags.documents.seed("other", ["alpha"], group_id="group-2")


def test_a_rename_moves_the_definition_before_any_document(env):
    define(env, alpha=DEFINED, beta=DEFINED)
    seed_tagged_documents(env)
    response = rename(env)
    assert (response.status_code, response.get_json()) == (200, {
        "message": 'Tag renamed from "alpha" to "gamma"', "documents_updated": 2,
    })
    assert definitions(env) == {"beta": DEFINED, "gamma": DEFINED}
    assert env.tags.documents.tags() == {"d1": ["gamma"], "d2": ["gamma", "beta"], "d3": ["beta"], "other": ["alpha"]}
    assert [event[0] for event in env.tags.events] == [
        "group_write", "update_document", "propagate_tags_to_chunks", "update_document", "propagate_tags_to_chunks",
        "invalidate",
    ]
    assert env.bumps == []


def test_a_rename_after_a_document_failed_finishes_when_repeated(env):
    define(env, alpha=DEFINED)
    seed_tagged_documents(env)
    env.tags.documents.fail_on.add("d2")
    assert rename(env).status_code == 500
    assert definitions(env) == {"gamma": DEFINED}
    assert env.tags.documents.tags()["d2"] == ["alpha", "beta"]

    env.tags.events.clear()
    response = rename(env)
    assert (response.status_code, response.get_json()["documents_updated"]) == (200, 1)
    assert env.tags.documents.tags() == {"d1": ["gamma"], "d2": ["gamma", "beta"], "d3": ["beta"], "other": ["alpha"]}
    assert definitions(env) == {"gamma": DEFINED}
    assert group_writes(env) == []


@pytest.mark.parametrize("landing,expected", [
    ("demoted", (403, {"error": "You do not have permission to manage tags"})),
    ("deleted", (404, {"error": "Active group not found"})),
])
def test_a_rename_refused_on_the_current_copy_leaves_every_document_untouched(env, monkeypatch, landing, expected):
    define(env, alpha=DEFINED)
    seed_tagged_documents(env)
    before = env.tags.documents.tags()
    after_read(env, monkeypatch, BEFORE_THE_WRITE, demote if landing == "demoted" else None)
    response = rename(env)
    assert (response.status_code, response.get_json()) == expected
    assert env.tags.documents.tags() == before and document_updates(env) == []


def test_a_rename_on_a_group_that_keeps_changing_leaves_every_document_untouched(env):
    define(env, alpha=DEFINED)
    seed_tagged_documents(env)
    before = env.tags.documents.tags()
    keep_changing(env)
    response = rename(env)
    assert (response.status_code, response.get_json()) == (409, conflict(env))
    assert env.tags.documents.tags() == before and definitions(env) == {"alpha": DEFINED}


def test_the_role_is_checked_on_the_current_copy_even_when_no_definition_changes(env, monkeypatch):
    seed_tagged_documents(env)
    after_read(env, monkeypatch, BEFORE_THE_WRITE, demote)
    response = rename(env)
    assert (response.status_code, response.get_json()) == (403, {"error": "You do not have permission to manage tags"})
    assert document_updates(env) == [] and group_writes(env) == []


def test_renaming_an_undefined_tag_renames_the_documents_without_a_group_write(env):
    seed_tagged_documents(env)
    response = rename(env)
    assert (response.status_code, response.get_json()["documents_updated"]) == (200, 2)
    assert group_writes(env) == [] and "tag_definitions" not in env.stored_group(GROUP)


def test_a_recolour_keeps_a_concurrent_definition(env):
    define(env, alpha=DEFINED)
    concurrently(env, lambda group: group["tag_definitions"].update(beta=dict(DEFINED)))
    response = recolor(env)
    assert (response.status_code, response.get_json()) == (200, {
        "message": 'Tag color updated for "alpha"', "tag": {"name": "alpha", "color": "#445566"},
    })
    assert definitions(env) == {"alpha": {**DEFINED, "color": "#445566"}, "beta": DEFINED}


def test_recolouring_an_undefined_tag_defines_it(env):
    recolor(env)
    assert definitions(env)["alpha"]["color"] == "#445566"


@pytest.mark.parametrize("landing,expected", [
    ("demoted", (403, {"error": "You do not have permission to manage tags"})),
    ("deleted", (404, {"error": "Active group not found"})),
])
def test_a_recolour_refused_on_the_current_copy_writes_nothing(env, monkeypatch, landing, expected):
    define(env, alpha=DEFINED)
    after_read(env, monkeypatch, BEFORE_THE_WRITE, demote if landing == "demoted" else None)
    response = recolor(env)
    assert (response.status_code, response.get_json()) == expected
    assert group_writes(env) == []


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

def test_a_delete_removes_the_definition_before_any_document(env):
    define(env, alpha=DEFINED, beta=DEFINED)
    seed_tagged_documents(env)
    response = delete(env)
    assert (response.status_code, response.get_json()) == (200, {"message": 'Tag "alpha" deleted from 2 document(s)'})
    assert definitions(env) == {"beta": DEFINED}
    assert env.tags.documents.tags() == {"d1": [], "d2": ["beta"], "d3": ["beta"], "other": ["alpha"]}
    assert [event[0] for event in env.tags.events][:2] == ["group_write", "update_document"]
    assert env.bumps == []


def test_a_delete_after_a_document_failed_finishes_when_repeated(env):
    define(env, alpha=DEFINED)
    seed_tagged_documents(env)
    env.tags.documents.fail_on.add("d2")
    assert delete(env).status_code == 500
    assert definitions(env) == {} and env.tags.documents.tags()["d2"] == ["alpha", "beta"]

    env.tags.events.clear()
    response = delete(env)
    assert (response.status_code, response.get_json()) == (200, {"message": 'Tag "alpha" deleted from 1 document(s)'})
    assert env.tags.documents.tags() == {"d1": [], "d2": ["beta"], "d3": ["beta"], "other": ["alpha"]}
    assert group_writes(env) == []


@pytest.mark.parametrize("landing,expected", [
    ("demoted", (403, {"error": "You do not have permission to manage tags"})),
    ("deleted", (404, {"error": "Active group not found"})),
])
def test_a_delete_refused_on_the_current_copy_leaves_every_document_untouched(env, monkeypatch, landing, expected):
    define(env, alpha=DEFINED)
    seed_tagged_documents(env)
    before = env.tags.documents.tags()
    after_read(env, monkeypatch, BEFORE_THE_WRITE, demote if landing == "demoted" else None)
    response = delete(env)
    assert (response.status_code, response.get_json()) == expected
    assert env.tags.documents.tags() == before and document_updates(env) == []


def test_a_delete_on_a_group_that_keeps_changing_leaves_every_document_untouched(env):
    define(env, alpha=DEFINED)
    seed_tagged_documents(env)
    before = env.tags.documents.tags()
    keep_changing(env)
    response = delete(env)
    assert (response.status_code, response.get_json()) == (409, conflict(env))
    assert env.tags.documents.tags() == before and definitions(env) == {"alpha": DEFINED}


def test_deleting_an_undefined_tag_updates_the_documents_without_a_group_write(env):
    seed_tagged_documents(env)
    response = delete(env)
    assert response.get_json() == {"message": 'Tag "alpha" deleted from 2 document(s)'}
    assert group_writes(env) == []


# ---------------------------------------------------------------------------
# get_or_create_tag_definition
# ---------------------------------------------------------------------------

def get_or_create(env, tag="alpha", group_id=GROUP):
    return env.tags.definitions["get_or_create_tag_definition"]("manager-1", tag, workspace_type="group", group_id=group_id)


def default_color(env, tag="alpha"):
    return env.tags.definitions["get_default_tag_color"](tag)


def test_a_missing_definition_is_added_to_the_current_copy(env):
    concurrently(env, lambda group: group["pendingUsers"].append(person("applicant-1")))
    answer = get_or_create(env)
    stored = env.stored_group(GROUP)
    assert answer == stored["tag_definitions"]["alpha"]
    assert answer["color"] == default_color(env)
    assert [entry["userId"] for entry in stored["pendingUsers"]] == ["applicant-1"]
    assert env.bumps == []


def test_a_definition_added_meanwhile_is_kept_and_answered(env):
    concurrently(env, lambda group: group.update(tag_definitions={"alpha": dict(DEFINED)}))
    answer = get_or_create(env)
    assert answer == DEFINED
    assert definitions(env) == {"alpha": DEFINED}
    assert len(group_writes(env)) == 1, "the definition found on the current copy is not written again"


def test_an_existing_definition_is_answered_without_a_write(env):
    define(env, alpha={**DEFINED, "color": "#ABC"})
    assert get_or_create(env) == {**DEFINED, "color": "#aabbcc"}
    assert group_writes(env) == []


def test_other_definitions_are_kept(env):
    define(env, beta=DEFINED)
    concurrently(env, lambda group: group["tag_definitions"].update(delta=dict(DEFINED)))
    get_or_create(env)
    assert sorted(definitions(env)) == ["alpha", "beta", "delta"]


def test_a_group_deleted_meanwhile_is_not_recreated(env):
    env.groups.before_replace.append(lambda: env.groups.records.clear())
    assert get_or_create(env) == {"color": default_color(env)}
    assert env.groups.records == {}


def test_a_missing_group_answers_the_default_colour(env):
    assert get_or_create(env, group_id="group-9") == {"color": default_color(env)}
    assert group_writes(env) == []


def test_a_group_that_keeps_changing_answers_the_default_colour_with_a_data_free_warning(env):
    keep_changing(env)
    assert get_or_create(env) == {"color": default_color(env)}
    assert definitions(env) == {} and env.bumps == []
    assert env.logs == [(
        "[Tags] A group tag definition was not saved because the group kept changing.", logging.WARNING, {},
    )]
