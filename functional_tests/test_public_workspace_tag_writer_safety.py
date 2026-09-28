# test_public_workspace_tag_writer_safety.py
"""
Functional test for the public-workspace tag definition writers on the etag guard.
Version: 0.261.173
Implemented in: 0.261.173

The classic public tag routes (create, rename or recolour, delete) and
``get_or_create_tag_definition`` read the public workspace, changed its
``tag_definitions`` and upserted that copy back. A change landing in between (a
membership or status change, another tag) was undone, a workspace deleted in
between was recreated, and the caller's tag role was checked only on the copy read
first.

Each now changes the definitions on the copy it writes, through
``update_public_workspace_document_with_etag_guard``. This test runs them for real,
with the real guard over the etag-enforcing ``FakeContainer`` and the real tag
helpers from ``functions_documents``, and pins:

- a tag is created on the workspace's current copy, and "already exists" is decided
  there, so a definition added meanwhile is kept, not replaced;
- the caller's tag role is checked again on the current copy, so a manager removed
  meanwhile is refused with nothing written;
- a deleted workspace is not recreated, and a workspace that keeps changing gets the
  one shared conflict answer (message and ``public_workspace_write_conflict`` code)
  with nothing written and no bootstrap bump;
- rename and delete change the definition before any document, so a refusal leaves
  every document untouched, and repeating the request after a document failed
  finishes the documents that still carry the old tag, while every other failure
  keeps the classic ``{"error": str(e)}`` 500 shape;
- ``get_or_create_tag_definition`` adds a definition only while the current copy
  lacks it, answers one added meanwhile, and, for a workspace that keeps changing,
  answers the tag's default colour and logs a data-free warning.

Only the Cosmos containers, the chat-bootstrap bump and the ``functions_documents``
document writes are fakes; no network is touched.
"""

import ast
import copy
import logging
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from azure.core import MatchConditions
from azure.cosmos import exceptions as cosmos_exceptions

from test_file_sync_concurrent_write_safety import FakeContainer
from test_support.agent_delegation import APP_ROOT, module_stub
from test_support.app_source import definitions as source_definitions, refusing_module_stub
from test_support.versioning import assert_app_version_at_least


APP_DIR = Path(APP_ROOT)
ROUTE_FILE = "route_backend_public_documents.py"
WORKSPACES_FILE = "functions_public_workspaces.py"
DOCUMENTS_FILE = "functions_documents.py"
REGISTER = "register_route_backend_public_documents"
WS = "public-1"
TAGS = "/api/public_workspace_documents/tags"
DEFINED = {"color": "#112233", "created_at": "2026-09-01T00:00:00+00:00"}

ROUTE_MODULE_LEVEL = {
    "PUBLIC_WORKSPACE_MANAGER_ROLES", "PUBLIC_TAG_PERMISSION_MESSAGE", "_PublicTagAnswer",
    "_save_public_tag_definitions", "_require_active_public_workspace_response",
}
ROUTE_NESTED = {
    "api_create_public_workspace_tag", "api_update_public_workspace_tag", "api_delete_public_workspace_tag",
}
WORKSPACES_DEFINITIONS = {
    "PUBLIC_DOCUMENT_WRITE_ATTEMPTS", "PublicWorkspaceDocumentWriteConflict",
    "PUBLIC_WORKSPACE_WRITE_CONFLICT_CODE", "PUBLIC_WORKSPACE_WRITE_CONFLICT_MESSAGE",
    "_stored_public_workspace_fields", "update_public_workspace_document_with_etag_guard",
    "get_user_role_in_public_workspace",
}
DOCUMENT_DEFINITIONS = {
    "TAG_COLOR_PATTERN", "normalize_tag", "validate_tags", "normalize_tag_color", "get_safe_tag_color",
    "validate_tag_color", "get_default_tag_color", "_PublicTagDefinitionPresent", "get_or_create_tag_definition",
}


assert_app_version_at_least("0.261.132")


# --------------------------------------------------------------------------- #
# Source-level AST pins: the writers forward through the guard and keep no raw
# ``cosmos_public_workspaces_container`` upsert.
# --------------------------------------------------------------------------- #

def _owner_calls_to(filename, writer):
    tree = ast.parse((APP_DIR / filename).read_text(encoding="utf-8"))
    owners = []

    def visit(node, owner):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit(child, child.name)
                continue
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Name) and child.func.id == writer:
                owners.append(owner)
            visit(child, owner)

    visit(tree, None)
    return owners


def _raw_upserts(filename, targets):
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
                        and getattr(getattr(func, "value", None), "id", "") == "cosmos_public_workspaces_container"
                        and owner in targets):
                    raw.append(owner)
            visit(child, owner)

    visit(tree, None)
    return raw


def test_the_tag_writers_forward_through_the_guard_wrapper():
    owners = _owner_calls_to(ROUTE_FILE, "_save_public_tag_definitions")
    for handler in ROUTE_NESTED:
        assert handler in owners, f"{handler} does not forward through _save_public_tag_definitions"


def test_the_tag_writers_keep_no_raw_container_upsert():
    assert _raw_upserts(ROUTE_FILE, ROUTE_NESTED) == []


def test_the_guard_wrapper_uses_the_public_etag_guard():
    assert "_save_public_tag_definitions" in _owner_calls_to(ROUTE_FILE, "update_public_workspace_document_with_etag_guard")


def test_get_or_create_uses_the_public_guard_and_keeps_no_raw_upsert():
    assert "get_or_create_tag_definition" in _owner_calls_to(
        DOCUMENTS_FILE, "update_public_workspace_document_with_etag_guard")
    assert _raw_upserts(DOCUMENTS_FILE, {"get_or_create_tag_definition"}) == []


# --------------------------------------------------------------------------- #
# Behaviour environment: the real guard and real tag helpers over fakes.
# --------------------------------------------------------------------------- #

class _Request:
    def __init__(self, body=None):
        self._body = body

    def get_json(self, silent=False):
        return self._body


class PublicDocuments:
    """The workspace documents the classic rename and delete read, and their tag writes."""

    QUERY = "SELECT * FROM c WHERE c.public_workspace_id = @ws_id"

    def __init__(self, events):
        self.records = {}
        self.events = events
        self.fail_on = set()

    def seed(self, document_id, tags, public_workspace_id=WS):
        self.records[document_id] = {
            "id": document_id, "public_workspace_id": public_workspace_id,
            "file_name": f"{document_id}.pdf", "version": 1, "tags": list(tags),
        }

    def query_items(self, query, parameters=None, enable_cross_partition_query=None, **kwargs):
        if " ".join(query.split()) != self.QUERY:
            raise AssertionError("The tag routes sent a documents query this test does not model")
        values = {parameter["name"]: parameter["value"] for parameter in parameters or []}
        return [copy.deepcopy(record) for record in self.records.values()
                if record["public_workspace_id"] == values["@ws_id"]]

    def update_document(self, document_id, public_workspace_id, user_id, tags, **kwargs):
        self.events.append(("update_document", document_id))
        if document_id in self.fail_on:
            self.fail_on.discard(document_id)
            raise RuntimeError("The document store is unavailable.")
        self.records[document_id]["tags"] = list(tags)

    def tags(self):
        return {document_id: record["tags"] for document_id, record in self.records.items()}


def _build_env():
    container = FakeContainer(name="public", partition_field="id")
    events, bumps, logs = [], [], []
    documents = PublicDocuments(events)

    # The real guard and role helper over the etag-enforcing container.
    ws_ns = {
        "copy": copy,
        "MatchConditions": MatchConditions,
        "exceptions": cosmos_exceptions,
        "cosmos_public_workspaces_container": container,
        "bump_chat_bootstrap_global_cache_version": lambda *, reason: bumps.append(reason),
    }
    exec(compile(source_definitions(WORKSPACES_FILE, WORKSPACES_DEFINITIONS), WORKSPACES_FILE, "exec"), ws_ns)

    ws_module = refusing_module_stub(
        WORKSPACES_FILE, "functions_public_workspaces",
        update_public_workspace_document_with_etag_guard=ws_ns["update_public_workspace_document_with_etag_guard"],
        PublicWorkspaceDocumentWriteConflict=ws_ns["PublicWorkspaceDocumentWriteConflict"],
        find_public_workspace_by_id=lambda ws_id: container.get(ws_id, ws_id),
        get_user_role_in_public_workspace=ws_ns["get_user_role_in_public_workspace"],
    )

    # The real tag helpers, with the document writes faked.
    document_ns = {
        "re": __import__("re"), "datetime": datetime, "logging": logging,
        "log_event": lambda message, **kw: logs.append((message, kw.get("level"))),
    }
    exec(compile(source_definitions(DOCUMENTS_FILE, DOCUMENT_DEFINITIONS), DOCUMENTS_FILE, "exec"), document_ns)
    documents_module = refusing_module_stub(
        DOCUMENTS_FILE, "functions_documents",
        normalize_tag=document_ns["normalize_tag"],
        validate_tags=document_ns["validate_tags"],
        validate_tag_color=document_ns["validate_tag_color"],
        update_document=documents.update_document,
        propagate_tags_to_chunks=lambda document_id, tags, user_id, **kwargs: events.append(
            ("propagate_tags_to_chunks", document_id)),
        get_or_create_tag_definition=document_ns["get_or_create_tag_definition"],
    )

    state = {"user_id": "owner"}

    def require_active_public_workspace(user_id, allowed_roles):
        current = container.get(WS, WS)
        if current is None:
            raise LookupError("Active public workspace not found")
        role = ws_ns["get_user_role_in_public_workspace"](current, user_id)
        if role not in allowed_roles:
            raise PermissionError("Access denied")
        return WS, current, role

    class _Blueprint:
        def route(self, *args, **kwargs):
            return lambda function: function

    route_ns = {
        "bp": _Blueprint(),
        "swagger_route": lambda **kwargs: (lambda function: function),
        "get_auth_security": lambda: [{"sessionAuth": []}],
        "login_required": lambda function: function,
        "user_required": lambda function: function,
        "enabled_required": lambda *args, **kwargs: (lambda function: function),
        "jsonify": lambda payload=None: payload,
        "request": None,
        "get_current_user_id": lambda: state["user_id"],
        "require_active_public_workspace": require_active_public_workspace,
        "update_public_workspace_document_with_etag_guard": ws_ns["update_public_workspace_document_with_etag_guard"],
        "get_user_role_in_public_workspace": ws_ns["get_user_role_in_public_workspace"],
        "PublicWorkspaceDocumentWriteConflict": ws_ns["PublicWorkspaceDocumentWriteConflict"],
        "PUBLIC_WORKSPACE_WRITE_CONFLICT_MESSAGE": ws_ns["PUBLIC_WORKSPACE_WRITE_CONFLICT_MESSAGE"],
        "PUBLIC_WORKSPACE_WRITE_CONFLICT_CODE": ws_ns["PUBLIC_WORKSPACE_WRITE_CONFLICT_CODE"],
        "cosmos_public_documents_container": documents,
        "invalidate_public_workspace_search_cache": lambda ws_id: events.append(("invalidate", ws_id)),
    }
    exec(compile(source_definitions(ROUTE_FILE, ROUTE_MODULE_LEVEL, register=REGISTER, nested=ROUTE_NESTED),
                 ROUTE_FILE, "exec"), route_ns)

    return SimpleNamespace(
        container=container, documents=documents, events=events, bumps=bumps, logs=logs, state=state,
        ws_ns=ws_ns, document_ns=document_ns, route_ns=route_ns, ws_module=ws_module,
        documents_module=documents_module,
    )


@pytest.fixture
def env():
    env = _build_env()
    with patch.dict(sys.modules, {
        "functions_documents": env.documents_module,
        "functions_public_workspaces": env.ws_module,
    }):
        yield env


def seed_workspace(env, *, tag_definitions=None, status="active"):
    document = {
        "id": WS, "name": "Public One", "status": status,
        "owner": {"userId": "owner", "displayName": "Owner", "email": "owner@example.test"},
        "admins": [{"userId": "admin", "displayName": "Admin", "email": "admin@example.test"}],
        "documentManagers": [{"userId": "manager", "displayName": "Manager", "email": "manager@example.test"}],
    }
    if tag_definitions is not None:
        document["tag_definitions"] = copy.deepcopy(tag_definitions)
    env.container.seed(document)


def as_user(env, user_id):
    env.state["user_id"] = user_id


def set_body(env, body):
    env.route_ns["request"] = _Request(body)


def concurrently(env, change):
    def land():
        stored = env.container.get(WS, WS)
        change(stored)
        env.container.seed(stored)
    env.container.before_replace.append(land)


def keep_changing(env):
    for index in range(env.ws_ns["PUBLIC_DOCUMENT_WRITE_ATTEMPTS"]):
        concurrently(env, lambda ws, index=index: ws.setdefault("admins", []).append(
            {"userId": f"late-{index}", "displayName": f"Late {index}", "email": f"late{index}@example.test"}))


def demote(ws):
    ws["documentManagers"] = [manager for manager in ws.get("documentManagers", [])
                              if manager.get("userId") != "manager"]


def definitions(env):
    return env.container.get(WS, WS).get("tag_definitions", {})


def workspace_writes(env):
    return [call for call in env.container.calls if call[0] == "replace_item"]


def document_updates(env):
    return [event for event in env.events if event[0] == "update_document"]


def conflict(env):
    return {
        "error": env.ws_ns["PUBLIC_WORKSPACE_WRITE_CONFLICT_MESSAGE"],
        "error_code": "public_workspace_write_conflict",
    }


def create(env, tag="alpha", color="#abcdef"):
    set_body(env, {"tag_name": tag, "color": color})
    return env.route_ns["api_create_public_workspace_tag"]()


def rename(env, old="alpha", new="gamma"):
    set_body(env, {"new_name": new})
    return env.route_ns["api_update_public_workspace_tag"](old)


def recolor(env, tag="alpha", color="#445566"):
    set_body(env, {"color": color})
    return env.route_ns["api_update_public_workspace_tag"](tag)


def delete(env, tag="alpha"):
    set_body(env, {})
    return env.route_ns["api_delete_public_workspace_tag"](tag)


def seed_tagged_documents(env):
    env.documents.seed("d1", ["alpha"])
    env.documents.seed("d2", ["alpha", "beta"])
    env.documents.seed("d3", ["beta"])
    env.documents.seed("other", ["alpha"], public_workspace_id="public-2")


# --------------------------------------------------------------------------- #
# Create
# --------------------------------------------------------------------------- #

def test_a_tag_is_created_on_the_current_copy(env):
    seed_workspace(env)
    concurrently(env, lambda ws: ws.setdefault("pendingDocumentManagers", []).append({"userId": "applicant"}))
    payload, status = create(env)
    assert (status, payload["tag"]) == (201, {"name": "alpha", "color": "#abcdef"})
    stored = env.container.get(WS, WS)
    assert stored["tag_definitions"]["alpha"]["color"] == "#abcdef"
    assert datetime.fromisoformat(stored["tag_definitions"]["alpha"]["created_at"]).tzinfo is not None
    assert [entry["userId"] for entry in stored["pendingDocumentManagers"]] == ["applicant"]
    assert len(workspace_writes(env)) == 2 and env.bumps == []


def test_a_tag_created_meanwhile_is_refused_not_replaced(env):
    seed_workspace(env)
    concurrently(env, lambda ws: ws.update(tag_definitions={"alpha": dict(DEFINED)}))
    payload, status = create(env)
    assert (status, payload) == (409, {"error": "Tag already exists"})
    assert definitions(env) == {"alpha": DEFINED}


def test_an_existing_tag_is_refused_without_a_write(env):
    seed_workspace(env, tag_definitions={"alpha": DEFINED})
    payload, status = create(env)
    assert (status, payload) == (409, {"error": "Tag already exists"})
    assert workspace_writes(env) == [] and definitions(env) == {"alpha": DEFINED}


def test_a_manager_who_lost_the_role_meanwhile_cannot_create(env):
    seed_workspace(env)
    as_user(env, "manager")
    concurrently(env, demote)
    payload, status = create(env)
    assert (status, payload) == (403, {"error": "You do not have permission to manage tags"})
    assert definitions(env) == {}


def test_creating_on_a_deleted_workspace_does_not_recreate_it(env):
    seed_workspace(env)
    env.container.before_replace.append(lambda: env.container.records.clear())
    payload, status = create(env)
    assert (status, payload) == (404, {"error": "Active public workspace not found"})
    assert env.container.records == {}


def test_creating_on_a_workspace_that_keeps_changing_answers_the_conflict(env):
    seed_workspace(env)
    keep_changing(env)
    payload, status = create(env)
    assert (status, payload) == (409, conflict(env))
    assert definitions(env) == {} and env.bumps == []


@pytest.mark.parametrize("user_id", ["owner", "admin", "manager"])
def test_every_tag_manager_role_can_create(env, user_id):
    seed_workspace(env)
    as_user(env, user_id)
    assert create(env)[1] == 201


def test_a_reader_cannot_manage_tags(env):
    seed_workspace(env)
    as_user(env, "reader")
    for call in (create, rename, recolor, delete):
        payload, status = call(env)
        assert (status, payload) == (403, {"error": "You do not have permission to manage tags"})
    assert workspace_writes(env) == [] and document_updates(env) == []


# --------------------------------------------------------------------------- #
# Rename and recolour
# --------------------------------------------------------------------------- #

def test_a_rename_moves_the_definition_before_any_document(env):
    seed_workspace(env, tag_definitions={"alpha": DEFINED, "beta": DEFINED})
    seed_tagged_documents(env)
    payload, status = rename(env)
    assert (status, payload) == (200, {
        "message": 'Tag renamed from "alpha" to "gamma"', "documents_updated": 2,
    })
    assert definitions(env) == {"beta": DEFINED, "gamma": DEFINED}
    assert env.documents.tags() == {"d1": ["gamma"], "d2": ["gamma", "beta"], "d3": ["beta"], "other": ["alpha"]}
    assert [event[0] for event in env.events] == [
        "update_document", "propagate_tags_to_chunks", "update_document", "propagate_tags_to_chunks", "invalidate",
    ]
    assert workspace_writes(env) == [("replace_item", WS)] and env.bumps == []


def test_a_rename_after_a_document_failed_finishes_when_repeated(env):
    seed_workspace(env, tag_definitions={"alpha": DEFINED})
    seed_tagged_documents(env)
    env.documents.fail_on.add("d2")
    payload, status = rename(env)
    assert status == 500 and payload == {"error": "The document store is unavailable."}
    assert definitions(env) == {"gamma": DEFINED}
    assert env.documents.tags()["d2"] == ["alpha", "beta"]

    env.events.clear()
    env.container.calls.clear()
    payload, status = rename(env)
    assert (status, payload["documents_updated"]) == (200, 1)
    assert env.documents.tags() == {"d1": ["gamma"], "d2": ["gamma", "beta"], "d3": ["beta"], "other": ["alpha"]}
    assert definitions(env) == {"gamma": DEFINED}
    assert workspace_writes(env) == []


def test_a_rename_refused_on_the_current_copy_leaves_every_document_untouched(env):
    seed_workspace(env, tag_definitions={"alpha": DEFINED})
    as_user(env, "manager")
    seed_tagged_documents(env)
    before = env.documents.tags()
    concurrently(env, demote)
    payload, status = rename(env)
    assert (status, payload) == (403, {"error": "You do not have permission to manage tags"})
    assert env.documents.tags() == before and document_updates(env) == []


def test_a_rename_on_a_workspace_that_keeps_changing_leaves_every_document_untouched(env):
    seed_workspace(env, tag_definitions={"alpha": DEFINED})
    seed_tagged_documents(env)
    before = env.documents.tags()
    keep_changing(env)
    payload, status = rename(env)
    assert (status, payload) == (409, conflict(env))
    assert env.documents.tags() == before and definitions(env) == {"alpha": DEFINED}


def test_renaming_an_undefined_tag_renames_the_documents_without_a_workspace_write(env):
    seed_workspace(env)
    seed_tagged_documents(env)
    payload, status = rename(env)
    assert (status, payload["documents_updated"]) == (200, 2)
    assert workspace_writes(env) == [] and "tag_definitions" not in env.container.get(WS, WS)


def test_a_recolour_keeps_a_concurrent_definition(env):
    seed_workspace(env, tag_definitions={"alpha": DEFINED})
    concurrently(env, lambda ws: ws["tag_definitions"].update(beta=dict(DEFINED)))
    payload, status = recolor(env)
    assert (status, payload["tag"]) == (200, {"name": "alpha", "color": "#445566"})
    assert definitions(env) == {"alpha": {**DEFINED, "color": "#445566"}, "beta": DEFINED}


def test_recolouring_an_undefined_tag_defines_it(env):
    seed_workspace(env)
    recolor(env)
    assert definitions(env)["alpha"]["color"] == "#445566"


def test_a_recolour_refused_on_the_current_copy_writes_nothing(env):
    seed_workspace(env, tag_definitions={"alpha": DEFINED})
    as_user(env, "manager")
    concurrently(env, demote)
    payload, status = recolor(env)
    assert (status, payload) == (403, {"error": "You do not have permission to manage tags"})
    assert definitions(env) == {"alpha": DEFINED}


# --------------------------------------------------------------------------- #
# Delete
# --------------------------------------------------------------------------- #

def test_a_delete_removes_the_definition_before_any_document(env):
    seed_workspace(env, tag_definitions={"alpha": DEFINED, "beta": DEFINED})
    seed_tagged_documents(env)
    payload, status = delete(env)
    assert (status, payload) == (200, {"message": 'Tag "alpha" deleted from 2 document(s)'})
    assert definitions(env) == {"beta": DEFINED}
    assert env.documents.tags() == {"d1": [], "d2": ["beta"], "d3": ["beta"], "other": ["alpha"]}
    assert [event[0] for event in env.events][:1] == ["update_document"]
    assert workspace_writes(env) == [("replace_item", WS)] and env.bumps == []


def test_a_delete_after_a_document_failed_finishes_when_repeated(env):
    seed_workspace(env, tag_definitions={"alpha": DEFINED})
    seed_tagged_documents(env)
    env.documents.fail_on.add("d2")
    payload, status = delete(env)
    assert status == 500 and payload == {"error": "The document store is unavailable."}
    assert definitions(env) == {} and env.documents.tags()["d2"] == ["alpha", "beta"]

    env.events.clear()
    env.container.calls.clear()
    payload, status = delete(env)
    assert (status, payload) == (200, {"message": 'Tag "alpha" deleted from 1 document(s)'})
    assert env.documents.tags() == {"d1": [], "d2": ["beta"], "d3": ["beta"], "other": ["alpha"]}
    assert workspace_writes(env) == []


def test_a_delete_refused_on_the_current_copy_leaves_every_document_untouched(env):
    seed_workspace(env, tag_definitions={"alpha": DEFINED})
    as_user(env, "manager")
    seed_tagged_documents(env)
    before = env.documents.tags()
    concurrently(env, demote)
    payload, status = delete(env)
    assert (status, payload) == (403, {"error": "You do not have permission to manage tags"})
    assert env.documents.tags() == before and document_updates(env) == []


def test_a_delete_on_a_workspace_that_keeps_changing_leaves_every_document_untouched(env):
    seed_workspace(env, tag_definitions={"alpha": DEFINED})
    seed_tagged_documents(env)
    before = env.documents.tags()
    keep_changing(env)
    payload, status = delete(env)
    assert (status, payload) == (409, conflict(env))
    assert env.documents.tags() == before and definitions(env) == {"alpha": DEFINED}


def test_deleting_an_undefined_tag_updates_the_documents_without_a_workspace_write(env):
    seed_workspace(env)
    seed_tagged_documents(env)
    payload, status = delete(env)
    assert payload == {"message": 'Tag "alpha" deleted from 2 document(s)'}
    assert workspace_writes(env) == []


# --------------------------------------------------------------------------- #
# get_or_create_tag_definition (public branch)
# --------------------------------------------------------------------------- #

def get_or_create(env, tag="alpha", public_workspace_id=WS):
    return env.document_ns["get_or_create_tag_definition"](
        "manager", tag, workspace_type="public", public_workspace_id=public_workspace_id)


def default_color(env, tag="alpha"):
    return env.document_ns["get_default_tag_color"](tag)


def test_a_missing_definition_is_added_to_the_current_copy(env):
    seed_workspace(env)
    concurrently(env, lambda ws: ws.setdefault("pendingDocumentManagers", []).append({"userId": "applicant"}))
    answer = get_or_create(env)
    stored = env.container.get(WS, WS)
    assert answer == stored["tag_definitions"]["alpha"]
    assert answer["color"] == default_color(env)
    assert [entry["userId"] for entry in stored["pendingDocumentManagers"]] == ["applicant"]
    assert env.bumps == []


def test_a_definition_added_meanwhile_is_kept_and_answered(env):
    seed_workspace(env)
    concurrently(env, lambda ws: ws.update(tag_definitions={"alpha": dict(DEFINED)}))
    answer = get_or_create(env)
    assert answer == DEFINED
    assert definitions(env) == {"alpha": DEFINED}
    assert len(workspace_writes(env)) == 1, "the definition found on the current copy is not written again"


def test_an_existing_definition_is_answered_without_a_write(env):
    seed_workspace(env, tag_definitions={"alpha": {**DEFINED, "color": "#ABC"}})
    assert get_or_create(env) == {**DEFINED, "color": "#aabbcc"}
    assert workspace_writes(env) == []


def test_a_workspace_deleted_meanwhile_is_not_recreated(env):
    seed_workspace(env)
    env.container.before_replace.append(lambda: env.container.records.clear())
    assert get_or_create(env) == {"color": default_color(env)}
    assert env.container.records == {}


def test_a_missing_workspace_answers_the_default_colour(env):
    seed_workspace(env)
    assert get_or_create(env, public_workspace_id="public-9") == {"color": default_color(env)}
    assert workspace_writes(env) == []


def test_a_workspace_that_keeps_changing_answers_the_default_colour_with_a_data_free_warning(env):
    seed_workspace(env)
    keep_changing(env)
    assert get_or_create(env) == {"color": default_color(env)}
    assert definitions(env) == {} and env.bumps == []
    assert env.logs == [(
        "[PUBLIC_DOCUMENTS] A public workspace tag definition was not saved because the workspace kept changing.",
        logging.WARNING,
    )]
