# test_document_provenance_versions_and_guards.py
"""
Functional tests for document provenance across versions, client guards, and list scopes.
Version: 0.261.194
Implemented in: 0.261.194

This test ensures that each document version stores only its own origin while
keeping the carried-forward tags (including the removable ``workflow`` tag); that
a malformed origin is refused before any earlier version is archived; that no
update path can write an origin; that every mutating route on the guarded document
blueprints (personal, group, public, search, and the bearer-token external API)
rejects client origin fields in JSON and form bodies; that responses expose at most
``origin_kind`` plus an access-checked ``origin_summary`` on single-document reads,
never on lists or the external API; that held documents expose neither; and that
origin list filters only narrow each list's existing parameterized, scoped query.

Runs the real create_document, update_document, document route guards, and scoped
list queries with in-memory containers. No Azure resources or application startup
are used.
"""

import ast
from copy import deepcopy
from datetime import datetime, timezone
import logging
from pathlib import Path
import re
import sys
from types import SimpleNamespace

from flask import Blueprint, Flask, Response, jsonify, request
import pytest
from werkzeug.datastructures import MultiDict
from werkzeug.test import Client

APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

# Resolve application modules only after configuring the standalone path.
from content_screening import access
from content_screening.contracts import SCREENING_FIELD, ScreeningValidationError
import functions_document_provenance as provenance
from test_support.versioning import assert_app_version_at_least


GUARDED_ROUTE_FILES = (
    "route_backend_documents.py",
    "route_backend_group_documents.py",
    "route_backend_public_document_collaboration.py",
    "route_backend_public_document_management.py",
    "route_backend_public_document_reads.py",
    "route_backend_public_documents.py",
    "route_backend_search.py",
    "route_external_public_documents.py",
)
EXTERNAL_ROUTE_FILE = "route_external_public_documents.py"
MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
SCOPES = {
    "personal": {},
    "group": {"group_id": "group-1"},
    "public": {"public_workspace_id": "public-1"},
}
WORKFLOW_ORIGIN = provenance.build_workflow_origin(
    scope_type="personal", scope_id="user-1", workflow_id="workflow-1", run_id="run-1",
    task_id="summarize", output_key="report",
)
LATER_RUN_ORIGIN = provenance.build_workflow_origin(
    scope_type="personal", scope_id="user-1", workflow_id="workflow-1", run_id="run-2",
)
CHAT_ORIGIN = provenance.build_chat_origin(conversation_id="conversation-1", message_id="message-1")
WORKFLOW_SUMMARY = {
    "kind": "workflow", "label": "Created by Quarterly report",
    "href": "/workspace/workflows?workflow_id=workflow-1&run_id=run-1",
}
CLIENT_ORIGIN_BODIES = (
    {"origin": WORKFLOW_ORIGIN},
    {"origin_kind": "workflow"},
    {"originSummary": {"kind": "chat", "label": "Created in a chat"}},
    {"title": "Quarterly", "metadata": [{"Origin-Kind": "chat"}]},
    {"documents": [{"id": "doc-1", "ORIGIN": CHAT_ORIGIN}]},
)


def app_tree(file_name):
    return ast.parse((APP_ROOT / file_name).read_text(encoding="utf-8-sig"), filename=file_name)


def load_functions(file_name, names, namespace):
    selected = [
        node for node in app_tree(file_name).body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    assert {node.name for node in selected} == set(names)
    exec(compile(ast.Module(body=selected, type_ignores=[]), file_name, "exec"), namespace)
    return namespace


def route_declarations(file_name):
    """Return (blueprint, rule, methods, function) for every route declared in a route module."""
    declarations = []
    for node in ast.walk(app_tree(file_name)):
        if not isinstance(node, ast.FunctionDef):
            continue
        for decorator in node.decorator_list:
            if not (
                isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr == "route"
            ):
                continue
            assert isinstance(decorator.func.value, ast.Name), f"{file_name}:{node.name} route owner"
            methods = ["GET"]
            for keyword in decorator.keywords:
                if keyword.arg == "methods":
                    methods = ast.literal_eval(keyword.value)
            declarations.append((
                decorator.func.value.id, ast.literal_eval(decorator.args[0]), frozenset(methods), node.name,
            ))
    return declarations


MUTATING_ROUTES = [
    (file_name, rule, method, function)
    for file_name in GUARDED_ROUTE_FILES
    for _, rule, methods, function in route_declarations(file_name)
    for method in sorted(methods & MUTATING_METHODS)
]


def calls_named(tree, name):
    return [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and (
            isinstance(node.func, ast.Name) and node.func.id == name
            or isinstance(node.func, ast.Attribute) and node.func.attr == name
        )
    ]


def function_node(tree, name):
    matches = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name]
    assert len(matches) == 1, name
    return matches[0]


def keyword_value(call, name):
    return next((keyword.value for keyword in call.keywords if keyword.arg == name), None)


def test_version_supports_document_provenance():
    assert_app_version_at_least("0.261.194")


# --- Versions -------------------------------------------------------------------------


class DocumentStore:
    """A scope-filtered stand-in for one Cosmos documents container."""

    def __init__(self):
        self.records = {}
        self.writes = []

    def query_items(self, query, parameters, enable_cross_partition_query=True):
        values = {item["name"]: item["value"] for item in parameters}
        fields = {"@file_name": "file_name", "@user_id": "user_id", "@group_id": "group_id",
                  "@public_workspace_id": "public_workspace_id"}
        return [
            deepcopy(record) for record in self.records.values()
            if all(record.get(field) == values[name] for name, field in fields.items() if name in values)
        ]

    def upsert(self, document, operation):
        self.writes.append((operation, document["id"]))
        self.records[document["id"]] = deepcopy(document)


@pytest.fixture
def documents():
    stores = {scope: DocumentStore() for scope in SCOPES}
    namespace = {
        "datetime": datetime, "timezone": timezone, "logging": logging, "re": re,
        "SCREENING_FIELD": SCREENING_FIELD,
        "cosmos_user_documents_container": stores["personal"],
        "cosmos_group_documents_container": stores["group"],
        "cosmos_public_documents_container": stores["public"],
        "require_xsd_ingestion_capability": lambda *args, **kwargs: None,
        "set_document_chunk_visibility": lambda document, active: None,
        "_upsert_document_and_sync_access_index": lambda container, document, operation: container.upsert(
            document, operation,
        ),
        "_get_blob_container_name": lambda **kwargs: "documents",
        "apply_document_provenance": provenance.apply_document_provenance,
        "validate_origin": provenance.validate_origin,
        "initial_document_marker": lambda metadata: None,
        "add_file_task_to_file_processing_log": lambda *args, **kwargs: None,
        "log_event": lambda *args, **kwargs: None,
    }
    load_functions("functions_documents.py", {
        "create_document", "_build_carried_forward_metadata", "_document_revision_sort_key", "_safe_int",
        "ensure_list",
    }, namespace)

    def create(scope, document_id, **values):
        namespace["create_document"](
            file_name="report.md", user_id="user-1", document_id=document_id, num_file_chunks=0,
            status="Queued for processing", **SCOPES[scope], **values,
        )
        return deepcopy(stores[scope].records[document_id])

    return SimpleNamespace(create=create, stores=stores)


@pytest.mark.parametrize("scope", SCOPES)
def test_each_version_keeps_its_own_origin_and_the_carried_forward_tags(documents, scope):
    first = documents.create(scope, "doc-1", origin=WORKFLOW_ORIGIN, server_tags=["workflow"])
    assert first["version"] == 1 and first["origin"] == WORKFLOW_ORIGIN and first["tags"] == ["workflow"]

    manual = documents.create(scope, "doc-2")
    assert manual["version"] == 2 and "origin" not in manual
    assert manual["tags"] == ["workflow"]

    chat = documents.create(scope, "doc-3", origin=CHAT_ORIGIN)
    assert chat["version"] == 3 and chat["origin"] == CHAT_ORIGIN and chat["tags"] == ["workflow"]

    records = documents.stores[scope].records
    assert records["doc-1"]["origin"] == WORKFLOW_ORIGIN and records["doc-1"]["is_current_version"] is False
    assert "origin" not in records["doc-2"] and records["doc-2"]["is_current_version"] is False
    assert records["doc-3"]["is_current_version"] is True
    assert all("origin_kind" not in record and "origin_summary" not in record for record in records.values())


def test_the_workflow_tag_is_merged_once_across_versions(documents):
    documents.create("personal", "doc-1", origin=WORKFLOW_ORIGIN, server_tags=["workflow"])
    documents.stores["personal"].records["doc-1"]["tags"] = ["finance", "workflow"]
    later = documents.create("personal", "doc-2", origin=LATER_RUN_ORIGIN, server_tags=["workflow", "workflow"])
    assert later["tags"] == ["finance", "workflow"]
    assert later["origin"] == LATER_RUN_ORIGIN


def test_a_removed_workflow_tag_stays_removed_on_a_manual_version(documents):
    documents.create("personal", "doc-1", origin=WORKFLOW_ORIGIN, server_tags=["workflow"])
    documents.stores["personal"].records["doc-1"]["tags"] = []
    manual = documents.create("personal", "doc-2")
    assert manual["tags"] == [] and "origin" not in manual


def test_only_valid_server_tags_are_applied(documents):
    document = documents.create(
        "personal", "doc-1", origin=WORKFLOW_ORIGIN, server_tags=["Workflow", "work flow", 7, None, "workflow"],
    )
    assert document["tags"] == ["workflow"]


@pytest.mark.parametrize("origin", [
    {"version": 1, "kind": "workflow"},
    {**CHAT_ORIGIN, "version": 2},
    {**CHAT_ORIGIN, "version": True},
    {**CHAT_ORIGIN, "unexpected": "value"},
    {**CHAT_ORIGIN, "conversation_id": "conversation\n1"},
    {**WORKFLOW_ORIGIN, "workflow_scope": {"type": "public", "id": "public-1"}},
    {**CHAT_ORIGIN, "orchestration_step_id": "step-1"},
    "workflow",
])
def test_a_malformed_origin_is_refused_before_any_version_is_archived(documents, origin):
    documents.create("personal", "doc-1", origin=WORKFLOW_ORIGIN)
    store = documents.stores["personal"]
    before, writes = deepcopy(store.records), list(store.writes)
    with pytest.raises(provenance.DocumentOriginError):
        documents.create("personal", "doc-2", origin=origin)
    assert store.records == before and store.writes == writes
    assert store.records["doc-1"]["is_current_version"] is True


def test_origin_fields_from_a_copied_record_never_survive_creation():
    metadata = {"id": "doc-1", "origin": WORKFLOW_ORIGIN, "origin_kind": "workflow", "origin_summary": {}}
    provenance.apply_document_provenance(metadata)
    assert set(metadata) == {"id"}
    provenance.apply_document_provenance(metadata, origin=CHAT_ORIGIN)
    assert metadata["origin"] == CHAT_ORIGIN and "origin_kind" not in metadata


# --- update_document ------------------------------------------------------------------


class ReachedStorage(Exception):
    """Raised by the operation guard to prove a call got past the origin guard."""


@pytest.fixture
def update_document():
    namespace = load_functions("functions_documents.py", {"update_document"}, {
        "SCREENING_FIELD": SCREENING_FIELD, "ScreeningValidationError": ScreeningValidationError,
        "ORIGIN_FIELD_NAMES": provenance.ORIGIN_FIELD_NAMES, "DocumentOriginError": provenance.DocumentOriginError,
    })
    return namespace["update_document"]


def reach_storage():
    raise ReachedStorage()


@pytest.mark.parametrize("field", provenance.ORIGIN_FIELD_NAMES)
@pytest.mark.parametrize("scope", SCOPES)
def test_update_document_refuses_every_origin_field(update_document, field, scope):
    guarded = []
    with pytest.raises(provenance.DocumentOriginError):
        update_document(
            document_id="doc-1", user_id="user-1", operation_guard=lambda: guarded.append(True),
            **SCOPES[scope], **{field: deepcopy(WORKFLOW_ORIGIN)},
        )
    assert guarded == []


@pytest.mark.parametrize("changes", [
    {"tags": []},
    {"tags": ["finance"]},
    {"title": "Quarterly report"},
    {"status": "Processing", "percentage_complete": 10},
    {"source_metadata": {"origin_note": "not an origin field"}},
])
def test_update_document_accepts_ordinary_changes(update_document, changes):
    with pytest.raises(ReachedStorage):
        update_document(document_id="doc-1", user_id="user-1", operation_guard=reach_storage, **changes)


# --- Route guards ---------------------------------------------------------------------


def test_the_guarded_route_inventory_covers_the_document_mutation_routes():
    routes = {(file_name, rule, method) for file_name, rule, method, _ in MUTATING_ROUTES}
    assert len(MUTATING_ROUTES) >= 40
    for expected in (
        ("route_backend_documents.py", "/api/documents/upload", "POST"),
        ("route_backend_documents.py", "/api/documents/<document_id>", "PATCH"),
        ("route_backend_documents.py", "/api/documents/bulk-tag", "POST"),
        ("route_external_public_documents.py", "/external/public_documents/upload", "POST"),
    ):
        assert expected in routes


@pytest.mark.parametrize("file_name", GUARDED_ROUTE_FILES)
def test_every_document_route_module_guards_the_blueprint_its_routes_use(file_name):
    tree = app_tree(file_name)
    registrations = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("register_route_")
    ]
    assert len(registrations) == 1
    registration = registrations[0]
    blueprint_name = registration.args.args[0].arg
    guards = calls_named(registration, "register_document_api_guards")
    assert len(guards) == 1
    assert isinstance(guards[0].args[0], ast.Name) and guards[0].args[0].id == blueprint_name
    routes = route_declarations(file_name)
    assert routes and {owner for owner, *_ in routes} == {blueprint_name}
    nested = {node.name for node in ast.walk(registration) if isinstance(node, ast.FunctionDef)}
    assert {function for *_, function in routes} <= nested
    attach = keyword_value(guards[0], "attach_origin_summary")
    if file_name == EXTERNAL_ROUTE_FILE:
        assert isinstance(attach, ast.Constant) and attach.value is False
    else:
        assert attach is None


def make_guarded_app(blueprint_name, *, attach_origin_summary=True, records=None):
    """Mount the real document guards; like the real projectors, responses are re-read from storage."""
    stored = records if records is not None else {}
    app = Flask(__name__)
    blueprint = Blueprint(blueprint_name, __name__)
    access.register_document_api_guards(
        blueprint,
        user_resolver=lambda: "user-1",
        document_projector=lambda documents, actor: access.public_documents_payload(
            documents, actor, metadata_reader=lambda document_id, **kwargs: deepcopy(stored[document_id]),
        ),
        source_validator=lambda: None,
        attach_origin_summary=attach_origin_summary,
    )
    return app, blueprint


@pytest.fixture(scope="module")
def mutation_client():
    app, blueprint = make_guarded_app("provenance_mutations")
    reached = []

    def view(**kwargs):
        reached.append(request.endpoint)
        return jsonify({"ok": True})

    endpoints = {}
    for index, (file_name, rule, method, function) in enumerate(MUTATING_ROUTES):
        endpoint = f"route_{index}"
        blueprint.add_url_rule(rule, endpoint=endpoint, view_func=view, methods=[method])
        endpoints[(file_name, rule, method, function)] = f"provenance_mutations.{endpoint}"
    app.register_blueprint(blueprint)
    adapter = app.url_map.bind("localhost")
    paths = {
        route: adapter.build(endpoint, {
            argument: "1" for argument in next(rule for rule in app.url_map.iter_rules(endpoint)).arguments
        }, method=route[2])
        for route, endpoint in endpoints.items()
    }
    return SimpleNamespace(client=Client(app, Response), reached=reached, paths=paths, endpoints=endpoints)


@pytest.mark.parametrize("route", MUTATING_ROUTES, ids=lambda route: f"{route[2]} {route[1]}")
def test_every_guarded_mutation_route_rejects_client_origin_fields(mutation_client, route):
    path, method, endpoint = mutation_client.paths[route], route[2], mutation_client.endpoints[route]
    mutation_client.reached.clear()
    for body in CLIENT_ORIGIN_BODIES:
        response = mutation_client.client.open(path, method=method, json=body)
        assert response.status_code == 400, (route, body)
        assert response.get_json()["error_code"] == provenance.DocumentOriginError.code
    for field in ("origin", "origin_kind", "originSummary"):
        response = mutation_client.client.open(path, method=method, data={field: "workflow", "title": "Quarterly"})
        assert response.status_code == 400, (route, field)
    assert mutation_client.reached == []

    response = mutation_client.client.open(path, method=method, json={
        "title": "Quarterly", "tags": ["workflow"], "origin_workflow_id": "workflow-1",
    })
    assert response.status_code == 200
    assert mutation_client.reached == [endpoint]


def test_metadata_allow_lists_never_name_an_origin_field():
    for file_name, constant in (
        ("functions_group_document_management.py", "GROUP_DOCUMENT_METADATA_FIELDS"),
        ("functions_public_document_management.py", "PUBLIC_DOCUMENT_METADATA_FIELDS"),
    ):
        assignment = next(
            node for node in app_tree(file_name).body
            if isinstance(node, ast.Assign) and any(getattr(target, "id", None) == constant for target in node.targets)
        )
        fields = ast.literal_eval(assignment.value.args[0])
        assert fields and not set(fields) & set(provenance.ORIGIN_FIELD_NAMES)


# --- Responses ------------------------------------------------------------------------


def stored_document(**values):
    return {
        "id": "doc-1", "file_name": "report.md", "user_id": "user-1", "version": 1,
        "is_current_version": True, "origin": deepcopy(WORKFLOW_ORIGIN), **values,
    }


HELD_MARKER = {"state": "pending", "scan_id": "scan-1", "content_fingerprint": "fp-1"}


@pytest.fixture
def read_client(monkeypatch):
    """Serve the real personal get_document behind the real document response guard."""
    resolved = []
    resolved_summary = {"value": deepcopy(WORKFLOW_SUMMARY)}

    def resolve(user_id, document, **kwargs):
        resolved.append((user_id, document["id"]))
        return deepcopy(resolved_summary["value"])

    monkeypatch.setattr(provenance, "resolve_origin_summary", resolve)
    records = {"doc-1": stored_document()}
    namespace = load_functions("functions_documents.py", {"get_document"}, {
        "get_document_record": lambda **kwargs: deepcopy(records[kwargs["document_id"]]),
        "jsonify": jsonify,
        "public_document_payload": access.public_document_payload,
        "ORIGIN_KIND_FIELD": provenance.ORIGIN_KIND_FIELD,
        "remember_document_origin_summary": provenance.remember_document_origin_summary,
    })

    def build(*, attach_origin_summary=True, document=None):
        if document is not None:
            records["doc-1"] = document
        app, blueprint = make_guarded_app(
            "provenance_reads", attach_origin_summary=attach_origin_summary, records=records,
        )

        def detail():
            return namespace["get_document"](
                "user-1", "doc-1", include_origin_summary=provenance.summary_requested(request.args),
            )

        def listing():
            # Even a summary remembered during a list request is never attached to list items.
            provenance.remember_document_origin_summary("user-1", records["doc-1"])
            return jsonify({"documents": [deepcopy(records["doc-1"])], "page": 1})

        blueprint.add_url_rule("/document", view_func=detail)
        blueprint.add_url_rule("/documents", view_func=listing)
        app.register_blueprint(blueprint)
        return Client(app, Response)

    return SimpleNamespace(build=build, resolved=resolved, summary=resolved_summary)


def test_a_detail_read_returns_the_kind_and_its_resolved_summary_but_never_the_origin(read_client):
    payload = read_client.build().get("/document?origin_summary=1").get_json()
    assert payload["origin_kind"] == "workflow"
    assert payload["origin_summary"] == WORKFLOW_SUMMARY
    assert "origin" not in payload
    assert read_client.resolved == [("user-1", "doc-1")]


@pytest.mark.parametrize("query", ["", "?origin_summary=0", "?origin_summary=yes"])
def test_a_detail_read_resolves_a_summary_only_when_asked(read_client, query):
    payload = read_client.build().get(f"/document{query}").get_json()
    assert payload["origin_kind"] == "workflow"
    assert "origin_summary" not in payload and "origin" not in payload
    assert read_client.resolved == []


def test_a_summary_of_another_kind_is_never_attached(read_client):
    read_client.summary["value"] = {"kind": "chat", "label": "Created in a chat"}
    payload = read_client.build().get("/document?origin_summary=true").get_json()
    assert payload["origin_kind"] == "workflow" and "origin_summary" not in payload


def test_a_document_without_an_origin_resolves_nothing(read_client):
    document = stored_document()
    del document["origin"]
    payload = read_client.build(document=document).get("/document?origin_summary=1").get_json()
    assert payload["id"] == "doc-1"
    assert "origin_kind" not in payload and "origin_summary" not in payload
    assert read_client.resolved == []


def test_lists_carry_at_most_the_origin_kind(read_client):
    document = stored_document(origin_summary={"kind": "workflow", "label": "Stored label", "href": "/x"})
    payload = read_client.build(document=document).get("/documents?origin_summary=1").get_json()
    [item] = payload["documents"]
    assert item["id"] == "doc-1" and item["file_name"] == "report.md"
    assert item["origin_kind"] == "workflow"
    assert "origin" not in item and "origin_summary" not in item


def test_the_external_api_never_attaches_a_summary(read_client):
    payload = read_client.build(attach_origin_summary=False).get("/document?origin_summary=1").get_json()
    assert payload["origin_kind"] == "workflow"
    assert "origin_summary" not in payload and "origin" not in payload


@pytest.mark.parametrize("origin", [{"version": 1, "kind": "workflow"}, {"kind": "chat"}, "chat", None])
def test_a_malformed_or_missing_origin_projects_no_kind(origin):
    payload = access.public_document_payload(stored_document(origin=origin))
    assert "origin_kind" not in payload and "origin" not in payload


def test_a_held_document_exposes_no_origin_and_never_resolves_a_summary(read_client):
    held = stored_document(**{SCREENING_FIELD: deepcopy(HELD_MARKER)})
    payload = access.public_document_payload(held)
    assert payload[SCREENING_FIELD]["available"] is False
    assert "origin_kind" not in payload and "origin" not in payload

    detail = read_client.build(document=held).get("/document?origin_summary=1").get_json()
    assert detail[SCREENING_FIELD]["available"] is False
    assert "origin_kind" not in detail and "origin_summary" not in detail and "origin" not in detail
    assert read_client.resolved == []


def test_group_and_public_detail_reads_gate_summaries_on_the_projected_kind():
    for file_name, reader in (
        ("functions_group_document_reads.py", "get_group_document_read_metadata"),
        ("functions_public_document_reads.py", "get_public_document_read_metadata"),
        ("functions_documents.py", "get_document"),
    ):
        node = function_node(app_tree(file_name), reader)
        remembers = calls_named(node, "remember_document_origin_summary")
        assert len(remembers) == 1
        guard = next(
            parent for parent in ast.walk(node)
            if isinstance(parent, ast.If) and remembers[0] in ast.walk(parent)
        )
        assert ast.unparse(guard.test) == "include_origin_summary and payload.get(ORIGIN_KIND_FIELD)"


# --- Server-side wiring ---------------------------------------------------------------


def test_detail_routes_resolve_summaries_only_when_asked_and_never_in_lists():
    for file_name, detail, lists in (
        ("route_backend_documents.py", "api_get_user_document", ("api_get_user_documents",)),
        ("route_backend_group_documents.py", "api_get_group_document", ("api_get_group_documents",)),
        ("route_backend_public_document_reads.py", "api_get_public_workspace_document",
         ("api_get_public_workspace_documents",)),
    ):
        tree = app_tree(file_name)
        detail_calls = calls_named(function_node(tree, detail), "summary_requested")
        assert len(detail_calls) == 1
        for list_route in lists:
            assert calls_named(function_node(tree, list_route), "summary_requested") == []
    assert calls_named(app_tree(EXTERNAL_ROUTE_FILE), "summary_requested") == []
    assert calls_named(app_tree(EXTERNAL_ROUTE_FILE), "remember_document_origin_summary") == []


def test_list_routes_apply_origin_filters_inside_their_own_scope():
    personal = function_node(app_tree("route_backend_documents.py"), "api_get_user_documents")
    filters = calls_named(personal, "origin_list_filter")
    assert len(filters) == 1 and keyword_value(filters[0], "group_id") is None
    extended = {
        (call.func.value.id, ast.unparse(call.args[0]))
        for call in calls_named(personal, "extend") if isinstance(call.func.value, ast.Name)
    }
    assert {("query_conditions", "origin_filter[0]"), ("query_params", "origin_filter[1]")} <= extended
    source = ast.unparse(personal)
    assert "query_conditions = ['(c.user_id = @user_id OR ARRAY_CONTAINS(c.shared_user_ids, @user_id))']" in source

    group = function_node(app_tree("route_backend_group_documents.py"), "api_get_group_documents")
    filters = calls_named(group, "origin_list_filter")
    assert len(filters) == 1
    assert ast.unparse(keyword_value(filters[0], "group_id")) == "requested_group_id"

    public = function_node(app_tree("route_backend_public_document_reads.py"), "api_get_public_workspace_documents")
    filters = calls_named(public, "origin_list_filter")
    assert len(filters) == 1 and keyword_value(filters[0], "group_id") is None


class QueryRecorder:
    def __init__(self, records):
        self.records = records
        self.calls = []

    def query_items(self, query, parameters, enable_cross_partition_query=True):
        self.calls.append((" ".join(query.split()), deepcopy(parameters)))
        return deepcopy(self.records)


@pytest.fixture
def conversation_filter(monkeypatch):
    monkeypatch.setattr(provenance, "_conversation_filter_allowed", lambda *args, **kwargs: True)
    value = "conversation-1' OR 1=1 --"
    return value, provenance.origin_list_filter(
        "user-1", MultiDict({"origin_conversation_id": value}), settings={}, user_roles=[],
    )


def test_public_origin_filters_narrow_the_workspace_query(conversation_filter):
    value, origin_filter = conversation_filter
    container = QueryRecorder([
        {"id": "doc-1", "public_workspace_id": "public-1"},
        {"id": "doc-2", "public_workspace_id": "public-2"},
    ])
    namespace = load_functions("functions_public_document_reads.py", {"_query_public_document_records"}, {
        "cosmos_public_documents_container": container,
    })
    records = namespace["_query_public_document_records"]("public-1", origin_filter=deepcopy(origin_filter))
    query, parameters = container.calls[0]
    assert query.startswith("SELECT * FROM c WHERE c.public_workspace_id = @workspace_id AND c.origin.kind = @origin_kind")
    assert query.endswith("AND c.is_current_version = true")
    assert value not in query
    assert parameters == [{"name": "@workspace_id", "value": "public-1"}, *origin_filter[1]]
    assert {"name": "@origin_conversation_id", "value": value} in parameters
    assert [record["id"] for record in records] == ["doc-1"]


def test_group_origin_filters_narrow_the_group_query(conversation_filter):
    value, origin_filter = conversation_filter
    container = QueryRecorder([
        {"id": "doc-1", "group_id": "group-1"},
        {"id": "doc-2", "group_id": "group-2"},
    ])
    namespace = load_functions("functions_group_document_reads.py", {"_query_group_document_records"}, {
        "cosmos_group_documents_container": container,
        "_group_document_share_status": lambda record, group_id: "owner" if record["group_id"] == group_id else None,
    })
    records = namespace["_query_group_document_records"]("group-1", origin_filter=deepcopy(origin_filter))
    query, parameters = container.calls[0]
    assert query.startswith("SELECT * FROM c WHERE (c.group_id = @group_id OR ARRAY_CONTAINS(c.shared_group_ids, @group_id)")
    assert "AND c.origin.kind = @origin_kind" in query and query.endswith("AND c.is_current_version = true")
    assert value not in query
    assert parameters[:2] == [
        {"name": "@group_id", "value": "group-1"}, {"name": "@group_id_prefix", "value": "group-1,"},
    ]
    assert parameters[2:] == origin_filter[1]
    assert [record["id"] for record in records] == ["doc-1"]


def test_list_queries_without_an_origin_filter_are_unchanged():
    container = QueryRecorder([{"id": "doc-1", "public_workspace_id": "public-1"}])
    namespace = load_functions("functions_public_document_reads.py", {"_query_public_document_records"}, {
        "cosmos_public_documents_container": container,
    })
    namespace["_query_public_document_records"]("public-1")
    assert container.calls == [(
        "SELECT * FROM c WHERE c.public_workspace_id = @workspace_id",
        [{"name": "@workspace_id", "value": "public-1"}],
    )]


def test_chat_uploads_stamp_the_origin_only_from_server_held_values():
    upload = function_node(app_tree("route_frontend_chats.py"), "upload_file")
    builders = calls_named(upload, "chat_upload_origin")
    assert len(builders) == 1
    arguments = {keyword.arg: ast.unparse(keyword.value) for keyword in builders[0].keywords}
    assert arguments == {
        "conversation_id": "conversation_id",
        "message_id": "file_message_id",
        "collaboration_conversation_id": "(collaboration_conversation or {}).get('id')",
    }
    assert not any(
        isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "request"
        for node in ast.walk(builders[0])
    )
    assignments = {
        target.id: ast.unparse(node.value)
        for node in ast.walk(upload) if isinstance(node, ast.Assign)
        for target in node.targets if isinstance(target, ast.Name)
    }
    assert assignments["conversation_id"] == "upload_context['conversation_id']"
    assert assignments["chat_document_origin"].startswith("chat_upload_origin(")
    assert assignments["file_message_id"].startswith("f'{conversation_id}_file_")
    queued = [
        call for name in ("queue_personal_workspace_upload_from_temp_file", "queue_group_workspace_upload_from_temp_file")
        for call in calls_named(upload, name)
    ]
    assert len(queued) == 2
    assert all(ast.unparse(keyword_value(call, "origin")) == "chat_document_origin" for call in queued)


def test_workspace_upload_helpers_pass_the_origin_to_document_creation():
    tree = app_tree("functions_documents.py")
    for helper in ("queue_personal_workspace_upload_from_temp_file", "queue_group_workspace_upload_from_temp_file"):
        node = function_node(tree, helper)
        assert "origin" in [argument.arg for argument in node.args.args + node.args.kwonlyargs]
        creates = calls_named(node, "create_document")
        assert len(creates) == 1 and ast.unparse(keyword_value(creates[0], "origin")) == "origin"


def test_publication_passes_only_server_derived_origin_fields():
    tree = app_tree("functions_artifact_publication.py")
    derived = calls_named(tree, "publication_origin_fields")
    assert len(derived) == 1
    assert [ast.unparse(argument) for argument in derived[0].args] == ["user_id", "artifact"]
    assert {keyword.arg: ast.unparse(keyword.value) for keyword in derived[0].keywords} == {
        "source_receipt": "source_receipt", "destination": "destination",
    }
    creates = [
        call for call in calls_named(tree, "create_document")
        if any(keyword.arg is None and ast.unparse(keyword.value) == "origin_fields" for keyword in call.keywords)
    ]
    assert len(creates) == 1
