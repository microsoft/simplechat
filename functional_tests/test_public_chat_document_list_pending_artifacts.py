# test_public_chat_document_list_pending_artifacts.py
#!/usr/bin/env python3
"""
Functional test: the public chat document list and its tag counts leave out pending artifacts.
Version: 0.261.183
Implemented in: 0.261.183

GET /api/public_workspace_documents and GET /api/public_workspace_documents/tags serve the V2 and
classic chat pickers, and the tags route also serves the classic public workspace's tag list. A
generated artifact awaiting publication has no chunks until its approval queues processing, so no one
can chat with one, and decision 27 leaves it out of both routes for every caller.

The two route functions and the list they share, _query_public_chat_documents, run unchanged from
route_backend_public_documents.py, for a reader and for a manager, over both of their read paths:

- the document access index: the real functions_document_access_index over fake containers, with
  the documents synced into it by its real sync code;
- the source query, which the routes use while the index backfill has not completed.

The real functions_documents helpers (current-revision selection, sorting, tag normalization and the
tag list) and the real public_document_approval_pending run too. The test pins that no pending
artifact is listed or counted, that the released documents are listed and counted exactly as they are
when no artifact is pending, that the tag counts are the counts over the listed documents, and that the
V2 fixtures answer the list with the route's rule (chat_list). No network is touched.
"""

import ast
import copy
import logging
import re
import sys
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
for candidate in (ROOT, ROOT / "ui_tests", ROOT / "ui_tests" / "fixtures"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from test_cosmos_wave5a_document_access_read_switch import (  # noqa: E402
    _document, _load_document_access_index_module, _succeeded_backfill_state,
)
from test_support.agent_delegation import APP_ROOT, execute_functions, module_stub  # noqa: E402
from test_support.app_source import definitions  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402
from ui_tests.fixtures.public_documents import chat_list  # noqa: E402
from ui_tests.fixtures.workflow_editor import WorkflowEditorFixture  # noqa: E402
from ui_tests.fixtures.workspace_authoring import ORIGIN, ApiRequest  # noqa: E402


ROUTE_FILE = "route_backend_public_documents.py"
REGISTER = "register_route_backend_public_documents"
ROUTES = {"api_list_public_workspace_documents", "api_get_public_workspace_document_tags"}
READER, MANAGER = "reader", "manager"
WORKSPACES = {
    "public-a": {
        "id": "public-a", "name": "Research library", "owner": {"userId": "owner"}, "admins": [],
        "documentManagers": [{"userId": MANAGER}],
        "tag_definitions": {"finance": {"color": "#0078d4"}, "team": {"color": "#059669"}, "embargo": {"color": "#8b5cf6"}},
    },
    "public-b": {
        "id": "public-b", "name": "Field notes", "owner": {"userId": "owner-b"}, "admins": [],
        "documentManagers": [], "tag_definitions": {"team": {"color": "#059669"}},
    },
}
# The caller's directory: both workspaces are shown, and one they hid is never read.
DIRECTORY = {"public-a": True, "public-b": True, "public-hidden": False}
READ_PATHS = {"index": True, "source": False}
DOCUMENT_CONSTANTS = {
    "NUMERIC_DOCUMENT_SORT_FIELDS", "TEXT_DOCUMENT_SORT_FIELDS", "ALLOWED_DOCUMENT_SORT_FIELDS",
    "DEFAULT_DOCUMENT_SORT_FIELD", "TAG_COLOR_PATTERN", "ARCHIVED_REVISION_BLOB_PATH_MODE",
}
DOCUMENT_HELPERS = {
    "_safe_int", "_safe_float", "_get_document_family_key", "_document_revision_sort_key",
    "_choose_current_document", "select_current_documents", "sort_documents",
    "_has_persisted_blob_reference", "_normalize_document_enhanced_citations",
    "normalize_tag", "sanitize_tags_for_filter", "normalize_tag_color", "get_safe_tag_color",
    "get_default_tag_color", "get_workspace_tag_definitions", "build_workspace_tags_from_counts",
    "validate_tags", "validate_tag_color",
}


def released_documents():
    return [
        _document("released-a", "uploader", public_workspace_id="public-a", tags=["finance"], _ts=300),
        _document("approved-a", "requester", public_workspace_id="public-a", tags=["finance", "team"], _ts=200,
                  generated_artifact_promotion_status="approved"),
        _document("released-b", "uploader", public_workspace_id="public-b", tags=["team"], _ts=100),
    ]


def pending_documents():
    """Two requested artifacts, the newest documents of their workspaces: one whose promotion status
    is recorded, carrying tags a manager gave it, and one requested before that status existed."""
    return [
        _document("pending-a", "requester", public_workspace_id="public-a", tags=["finance", "embargo", "restricted"],
                  _ts=400, status="Pending approval", percentage_complete=0,
                  generated_artifact_promotion_status="pending_approval"),
        _document("requested-b", "requester", public_workspace_id="public-b", tags=["team"], _ts=350,
                  status="Pending approval", percentage_complete=0),
    ]


class PublicDocumentsSource:
    """The public documents container, answering the chat list's source query."""

    def __init__(self, documents):
        self.records = {document["id"]: copy.deepcopy(document) for document in documents}
        self.queries = []

    def query_items(self, query, parameters=None, enable_cross_partition_query=None, **kwargs):
        self.queries.append(query)
        assert query.startswith("SELECT * FROM c WHERE c.public_workspace_id = @ws_0"), query
        workspaces = {parameter["value"] for parameter in parameters or [] if parameter["name"].startswith("@ws_")}
        return [
            copy.deepcopy(record) for record in sorted(self.records.values(), key=lambda record: -record["_ts"])
            if record["public_workspace_id"] in workspaces
        ]


class _Blueprint:
    def route(self, *args, **kwargs):
        return lambda function: function


def _passthrough(function):
    return function


def _document_helpers():
    """The real functions_documents helpers the chat routes use, run from their source."""
    namespace = {"re": re}
    tree = ast.parse((APP_ROOT / "functions_documents.py").read_text(encoding="utf-8"))
    constants = [
        node for node in tree.body if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id in DOCUMENT_CONSTANTS for target in node.targets)
    ]
    exec(compile(ast.Module(body=constants, type_ignores=[]), "functions_documents.py", "exec"), namespace)
    execute_functions("functions_documents.py", DOCUMENT_HELPERS, namespace)
    return namespace


@contextmanager
def chat_routes(documents, *, index_ready):
    """The two chat routes, run unchanged from their source over these public documents. The index
    serves them only once its backfill has completed; until then they read the source."""
    with _load_document_access_index_module() as (indexing, _index_container, settings_container):
        if index_ready:
            settings_container.upsert_item(_succeeded_backfill_state())
        for document in documents:
            indexing.sync_document_access_index_for_document(copy.deepcopy(document), force=True)
        helpers = _document_helpers()
        policy = {}
        execute_functions("functions_public_document_policy.py", {"public_document_approval_pending"}, policy)
        env = SimpleNamespace(user=READER, args={}, source=PublicDocumentsSource(documents), logs=[])
        namespace = {
            "bp": _Blueprint(), "swagger_route": lambda **kwargs: _passthrough,
            "get_auth_security": lambda: [{"sessionAuth": []}],
            "login_required": _passthrough, "user_required": _passthrough,
            "enabled_required": lambda *args, **kwargs: _passthrough,
            "jsonify": lambda payload=None: payload,
            "request": SimpleNamespace(args=env.args),
            "get_current_user_id": lambda: env.user,
            "get_user_settings": lambda user_id: {"settings": {"publicDirectorySettings": dict(DIRECTORY)}},
            "get_user_visible_public_workspace_ids_from_settings": lambda user_id: [
                workspace_id for workspace_id, shown in DIRECTORY.items() if shown
            ],
            "logging": logging,
            "log_event": lambda message, **kwargs: env.logs.append(message),
            "cosmos_public_documents_container": env.source,
            "DOCUMENT_ACCESS_SCOPE_PUBLIC": indexing.DOCUMENT_ACCESS_SCOPE_PUBLIC,
            "query_document_access_index_documents": indexing.query_document_access_index_documents,
            "is_document_access_shadow_validation_enabled": indexing.is_document_access_shadow_validation_enabled,
            "query_items_with_cosmos_diagnostics": indexing.query_items_with_cosmos_diagnostics,
            "validate_document_access_index_shadow": indexing.validate_document_access_index_shadow,
            "sort_documents": helpers["sort_documents"],
            "select_current_documents": helpers["select_current_documents"],
            "public_document_approval_pending": policy["public_document_approval_pending"],
        }
        module = definitions(ROUTE_FILE, {"_query_public_chat_documents"}, register=REGISTER, nested=ROUTES)
        exec(compile(module, ROUTE_FILE, "exec"), namespace)
        workspaces = module_stub(
            "functions_public_workspaces",
            find_public_workspace_by_id=lambda workspace_id: copy.deepcopy(WORKSPACES.get(workspace_id)),
        )
        with patch.dict(sys.modules, {
            "functions_documents": module_stub("functions_documents", **helpers),
            "functions_public_workspaces": workspaces,
        }):
            env.list = namespace["api_list_public_workspace_documents"]
            env.tags = namespace["api_get_public_workspace_document_tags"]
            yield env


def answer(route):
    payload, status = route()
    assert status == 200, payload
    return payload


def chat_answers(documents, *, read_path, actor):
    with chat_routes(documents, index_ready=READ_PATHS[read_path]) as env:
        env.user = actor
        listed, tags = answer(env.list), answer(env.tags)
        read_source = bool(env.source.queries)
    assert read_source is (read_path == "source"), f"the routes did not read the {read_path}"
    return listed, tags


def test_version_is_at_least_the_implementing_release():
    assert_app_version_at_least("0.261.176")


@pytest.mark.parametrize("read_path", READ_PATHS)
@pytest.mark.parametrize("actor", [READER, MANAGER])
def test_no_caller_is_offered_an_artifact_awaiting_publication(read_path, actor):
    """Every caller's chat list and tag counts are what they are with no artifact pending: none is
    listed, none of its tags is counted, and every released document is listed unchanged."""
    released_list, released_tags = chat_answers(released_documents(), read_path=read_path, actor=actor)
    listed, tags = chat_answers(released_documents() + pending_documents(), read_path=read_path, actor=actor)

    assert listed == released_list
    assert tags == released_tags
    assert [document["id"] for document in listed["documents"]] == ["released-a", "approved-a", "released-b"]
    counts = {tag["name"]: tag["count"] for tag in tags["tags"]}
    # A defined tag only a pending artifact carries is counted 0; one no workspace defines is absent.
    assert counts == {"embargo": 0, "finance": 2, "team": 2}


@pytest.mark.parametrize("read_path", READ_PATHS)
def test_the_tag_counts_are_the_counts_over_the_listed_documents(read_path):
    listed, tags = chat_answers(released_documents() + pending_documents(), read_path=read_path, actor=READER)

    listed_counts = Counter(tag for document in listed["documents"] for tag in document.get("tags") or [])
    assert {tag["name"]: tag["count"] for tag in tags["tags"] if tag["count"]} == dict(listed_counts)


def test_a_workspace_named_twice_is_counted_once():
    """A caller's workspace_ids may repeat a workspace; its documents are listed once, so they are
    counted once."""
    with chat_routes(released_documents() + pending_documents(), index_ready=True) as env:
        once = answer(env.tags)
        env.args["workspace_ids"] = "public-a,public-a,public-b,public-hidden"
        twice = answer(env.tags)

    assert twice == once


@pytest.mark.parametrize("read_path", READ_PATHS)
def test_the_fixtures_chat_list_is_the_routes(read_path):
    """ui_tests/fixtures/public_documents.chat_list, which the V2 fixtures answer the list with, gives
    the route's keys and leaves out exactly the documents the route leaves out."""
    documents = released_documents() + pending_documents()
    listed, _tags = chat_answers(documents, read_path=read_path, actor=READER)
    served = chat_list(documents)

    assert set(served) == set(listed)
    assert served["workspace_name"] == listed["workspace_name"]
    assert sorted(document["id"] for document in served["documents"]) == sorted(
        document["id"] for document in listed["documents"]
    )


class _FakePage:
    def __init__(self):
        self.url = "about:blank"
        self.context = SimpleNamespace(route=lambda *args, **kwargs: None, on=lambda *args, **kwargs: None)

    def on(self, *args, **kwargs):
        pass


class _RecordedRoute:
    def __init__(self, path):
        self.request = SimpleNamespace(url=f"{ORIGIN}{path}", method="GET", headers={}, post_data_buffer=None)
        self.fulfilled = None

    def fulfill(self, **kwargs):
        self.fulfilled = kwargs


def test_the_workflow_document_picker_is_served_the_chat_list_rule():
    """The V2 workflow editor fixture answers the public document picker with chat_list."""
    fixture = WorkflowEditorFixture(_FakePage())
    pending = _document("pending-handbook", "requester", public_workspace_id="public-handbook",
        status="Pending approval", percentage_complete=0, generated_artifact_promotion_status="pending_approval")
    fixture.public_documents.append(pending)
    route = _RecordedRoute("/api/public_workspace_documents")
    fixture._dispatch(route, ApiRequest(
        method="GET", path="/api/public_workspace_documents", query={"page_size": ["25"]}, body=None,
    ))

    served = route.fulfilled["json"]
    assert served == chat_list(fixture.public_documents)
    assert "pending-handbook" not in [document["id"] for document in served["documents"]]
    assert [document["id"] for document in served["documents"]] == ["public-policy"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
