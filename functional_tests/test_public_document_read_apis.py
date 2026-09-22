# test_public_document_read_apis.py
"""
Functional tests for immutable-target, read-only public workspace document APIs.
Version: 0.261.132
Implemented in: 0.261.132

The real public read module, route registrar, public workspace membership and
status helpers, document query helpers, and the screening response guard run in
an isolated Flask app. Existing functions_documents definitions execute without
their unrelated ingestion imports. Cosmos, authentication configuration, and
telemetry are local test seams; network access and source writes are prohibited.
The workspace identity is always taken from the path, so a stale active-workspace
preference can never redirect or widen a read.
"""

import ast
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from functools import wraps
import importlib.util
import re
import socket
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask import Blueprint, Flask, jsonify, request, session

from test_support.agent_delegation import APP_ROOT, execute_functions, module_stub
from test_support.versioning import assert_app_version_at_least


LIST_PATH = "/api/public-workspaces/public-a/documents"
READ_PATHS = (
    LIST_PATH,
    f"{LIST_PATH}/facets",
    f"{LIST_PATH}/tags",
    f"{LIST_PATH}/doc-b",
    f"{LIST_PATH}/doc-b/versions",
)
NO_PARAM_PATHS = (
    f"{LIST_PATH}/facets",
    f"{LIST_PATH}/tags",
    f"{LIST_PATH}/doc-b",
    f"{LIST_PATH}/doc-b/versions",
)
PRIVATE_TEXT = "PRIVATE-BLOB-PATH"


class MissingRecord(Exception):
    status_code = 404


class PublicReadOnlyContainer:
    """A Cosmos stub that refuses any query not scoped to an explicit workspace."""

    def __init__(self, records=None):
        self.records = records if records is not None else {}
        self.queries = []
        self.reads = Counter()
        self.failure = None
        self.after_query = None

    def read_item(self, item, partition_key):
        self.reads[item] += 1
        if self.failure:
            raise self.failure
        if item not in self.records:
            raise MissingRecord()
        return deepcopy(self.records[item])

    def query_items(self, query, parameters=None, **kwargs):
        self.queries.append((query, deepcopy(parameters or []), kwargs))
        if self.failure:
            raise self.failure
        values = {parameter["name"]: parameter["value"] for parameter in parameters or []}
        if "@workspace_id" in values:
            workspace_id = values["@workspace_id"]
            records = [
                deepcopy(record) for record in self.records.values()
                if str(record.get("public_workspace_id")) == str(workspace_id)
            ]
            if "@document_ids" in values:
                allowed = set(values["@document_ids"])
                records = [record for record in records if record["id"] in allowed]
        elif "@owner_workspace_id" in values:
            owner = values["@owner_workspace_id"]
            field = re.search(r"c\.(\w+) = @family_identity", query).group(1)
            records = [
                deepcopy(record) for record in self.records.values()
                if str(record.get("public_workspace_id")) == str(owner)
                and record.get(field) == values["@family_identity"]
            ]
        else:
            raise AssertionError("A public source query must be explicitly scoped.")
        if self.after_query:
            self.after_query()
        return records


def workspace(workspace_id, status="active"):
    return {
        "id": workspace_id,
        "name": f"Name of {workspace_id}",
        "status": status,
        "owner": {"userId": "owner"},
        "admins": ["admin"],
        "documentManagers": ["manager"],
        "users": [{"userId": "reader"}],
        "tag_definitions": {"reference": {"color": "#abcdef"}, "unused": {"color": "#123456"}},
    }


def document(document_id, workspace_id="public-a", **changes):
    value = {
        "id": document_id,
        "_etag": f"etag-{document_id}",
        "document_id": document_id,
        "public_workspace_id": workspace_id,
        "user_id": "uploader",
        "file_name": f"{document_id}.pdf",
        "title": document_id,
        "abstract": "A useful shared reference.",
        "authors": ["Ada Lovelace"],
        "keywords": ["reference"],
        "version": 1,
        "revision_family_id": document_id,
        "is_current_version": True,
        "percentage_complete": 100,
        "status": "Processing complete",
        "tags": ["reference"],
        "document_classification": "Public",
        "file_size": 100,
        "number_of_pages": 2,
        "upload_date": "2026-09-01T12:00:00Z",
        "_ts": int((datetime.now(timezone.utc) - timedelta(days=2)).timestamp()),
        "blob_path": f"{PRIVATE_TEXT}/{document_id}.pdf",
        "document_actions": ["delete", "manage"],
    }
    value.update(changes)
    return value


def seed_corpus(source):
    for record in (
        document("doc-b", tags=[], document_classification="", title="Beta",
                 authors=["Grace Hopper"], keywords=["alpha"], abstract="alpha overview"),
        document("doc-a-r1", file_name="doc-a.pdf", revision_family_id="fam-a",
                 version=1, is_current_version=False, title="Doc A v1"),
        document("doc-a-r2", file_name="doc-a.pdf", revision_family_id="fam-a",
                 version=2, is_current_version=True, title="Doc A v2"),
        document("doc-processing", percentage_complete=40, status="Processing"),
        document("doc-error", status="Extraction failed", tags=[]),
        document("doc-other", workspace_id="public-b"),
    ):
        source.records[record["id"]] = record


def load_real_module(monkeypatch, name):
    spec = importlib.util.spec_from_file_location(name, APP_ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def environment(monkeypatch):
    settings = {
        "enable_public_workspaces": True,
        "enable_content_screening": False,
    }
    with monkeypatch.context() as scoped:
        scoped.syspath_prepend(str(APP_ROOT))
        network = Mock(side_effect=AssertionError("No network access in read API tests."))
        scoped.setattr(socket, "create_connection", network)
        scoped.setattr(socket.socket, "connect", network)

        workspaces = {
            "public-a": workspace("public-a"),
            "public-b": workspace("public-b"),
            "locked-ws": workspace("locked-ws", status="locked"),
            "inactive-ws": workspace("inactive-ws", status="inactive"),
            "haunted-ws": workspace("haunted-ws", status="haunted"),
        }
        source = PublicReadOnlyContainer()
        seed_corpus(source)
        env = SimpleNamespace(
            settings=settings, workspaces=workspaces, source=source,
            downloads=False, logs=Mock(), network=network, actor="reader",
        )

        user_settings = Mock(side_effect=AssertionError(
            "A read must never consult a stored active-workspace preference.",
        ))
        env.user_settings = user_settings
        settings_module = module_stub(
            "functions_settings", get_settings=lambda: settings,
            get_user_settings=user_settings,
            is_public_workspace_file_download_enabled=lambda _settings, _workspace: env.downloads,
        )
        settings_namespace = {"wraps": wraps, "get_settings": lambda: settings, "jsonify": jsonify}
        execute_functions("functions_settings.py", {"enabled_required"}, settings_namespace)
        settings_module.enabled_required = settings_namespace["enabled_required"]
        scoped.setitem(sys.modules, "functions_settings", settings_module)

        scoped.setitem(sys.modules, "functions_appinsights", module_stub(
            "functions_appinsights", log_event=env.logs,
        ))

        auth_namespace = {
            "wraps": wraps, "session": session, "request": request, "jsonify": jsonify,
            "debug_print": Mock(), "check_user_access_status": Mock(return_value=(True, None)),
        }
        execute_functions("functions_authentication.py", {
            "login_required", "user_required", "get_current_user_id",
            "apply_blueprint_auth", "user_required_blueprint",
        }, auth_namespace)
        auth = module_stub("functions_authentication", **auth_namespace)
        scoped.setitem(sys.modules, "functions_authentication", auth)

        config = module_stub(
            "config", cosmos_public_documents_container=source,
            cosmos_group_documents_container=PublicReadOnlyContainer(),
            cosmos_user_documents_container=PublicReadOnlyContainer(),
            cosmos_content_screening_container=PublicReadOnlyContainer(),
            jsonify=jsonify, request=request, session=session,
            exceptions=SimpleNamespace(CosmosResourceNotFoundError=MissingRecord),
        )
        scoped.setitem(sys.modules, "config", config)

        public_namespace = {}
        execute_functions("functions_public_workspaces.py", {
            "get_user_role_in_public_workspace",
            "check_public_workspace_status_allows_operation",
        }, public_namespace)
        role_reader = Mock(side_effect=public_namespace["get_user_role_in_public_workspace"])
        env.role_reader = role_reader
        public_workspaces = module_stub(
            "functions_public_workspaces",
            find_public_workspace_by_id=lambda workspace_id: deepcopy(workspaces.get(workspace_id)),
            get_user_role_in_public_workspace=role_reader,
            check_public_workspace_status_allows_operation=public_namespace[
                "check_public_workspace_status_allows_operation"
            ],
        )
        scoped.setitem(sys.modules, "functions_public_workspaces", public_workspaces)

        scoped.setitem(sys.modules, "agent_execution_context", module_stub(
            "agent_execution_context", execution_user_id=lambda: None,
        ))
        scoped.setitem(sys.modules, "swagger_wrapper", module_stub(
            "swagger_wrapper",
            swagger_route=lambda **_kwargs: (lambda function: function),
            get_auth_security=lambda: [{"sessionAuth": []}],
        ))

        index_namespace = {}
        execute_functions("functions_document_access_index.py", {
            "document_matches_list_filters", "_matches_shadow_filters", "_normalize_filter_text",
        }, index_namespace)
        scoped.setitem(sys.modules, "functions_document_access_index", module_stub(
            "functions_document_access_index",
            document_matches_list_filters=index_namespace["document_matches_list_filters"],
        ))

        load_real_module(scoped, "functions_document_queries")

        document_namespace = {"re": re}
        tree = ast.parse((APP_ROOT / "functions_documents.py").read_text(encoding="utf-8"))
        constant_names = {
            "NUMERIC_DOCUMENT_SORT_FIELDS", "TEXT_DOCUMENT_SORT_FIELDS",
            "ALLOWED_DOCUMENT_SORT_FIELDS", "DEFAULT_DOCUMENT_SORT_FIELD", "TAG_COLOR_PATTERN",
            "ARCHIVED_REVISION_BLOB_PATH_MODE",
        }
        constants = [
            node for node in tree.body if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id in constant_names for target in node.targets)
        ]
        exec(compile(ast.Module(body=constants, type_ignores=[]), "functions_documents.py", "exec"), document_namespace)
        execute_functions("functions_documents.py", {
            "_safe_int", "_safe_float", "_get_document_family_key", "_document_revision_sort_key",
            "_choose_current_document", "select_current_documents", "sort_documents",
            "_has_persisted_blob_reference", "_normalize_document_enhanced_citations",
            "normalize_tag", "sanitize_tags_for_filter", "normalize_tag_color", "get_safe_tag_color",
            "get_default_tag_color", "get_workspace_tag_definitions", "build_workspace_tags_from_counts",
        }, document_namespace)
        scoped.setitem(sys.modules, "functions_documents", module_stub("functions_documents", **document_namespace))

        # Resolve screening only after replacing application bootstrap dependencies.
        from content_screening import access as screening_access

        env.access = load_real_module(scoped, "functions_public_document_access")
        env.reads = load_real_module(scoped, "functions_public_document_reads")
        route = load_real_module(scoped, "route_backend_public_document_reads")
        env.route = route
        env.screening_access = screening_access

        app = Flask("public_document_read_contract")
        app.config.update(TESTING=True, SECRET_KEY="test-only-session-key")
        blueprint = Blueprint("backend_public_document_reads", __name__)
        blueprint.before_request(auth.user_required_blueprint())
        route.register_route_backend_public_document_reads(blueprint)
        app.register_blueprint(blueprint)
        client = app.test_client()
        with client.session_transaction() as state:
            state["user"] = {"oid": env.actor, "roles": ["User"]}
        env.client = client
        env.app = app
        yield env
        network.assert_not_called()


def login(environment, oid):
    with environment.client.session_transaction() as state:
        state["user"] = {"oid": oid, "roles": ["User"]}


def get(environment, path=LIST_PATH, **query):
    return environment.client.get(path, query_string=query)


def document_ids(payload):
    return [item["id"] for item in payload["documents"]]


def test_implementation_version_is_present():
    assert_app_version_at_least("0.261.132")


@pytest.mark.parametrize("path", READ_PATHS)
def test_reader_reads_without_an_active_workspace_preference(environment, path):
    response = get(environment, path)
    assert response.status_code == 200
    assert "no-store" in response.headers["Cache-Control"]
    assert response.headers.get("ETag") is None
    environment.user_settings.assert_not_called()


@pytest.mark.parametrize("oid", ["owner", "admin", "manager", "anybody-else"])
@pytest.mark.parametrize("path", READ_PATHS)
def test_every_reader_role_is_authorized(environment, oid, path):
    login(environment, oid)
    assert get(environment, path).status_code == 200


@pytest.mark.parametrize("path", READ_PATHS)
def test_unknown_workspace_is_404(environment, path):
    response = get(environment, path.replace("public-a", "no-such-workspace"))
    assert response.status_code == 404


@pytest.mark.parametrize("path", READ_PATHS)
def test_inactive_workspace_is_403(environment, path):
    response = get(environment, path.replace("public-a", "inactive-ws"))
    assert response.status_code == 403


@pytest.mark.parametrize("path", READ_PATHS)
def test_unrecognized_status_is_403(environment, path):
    response = get(environment, path.replace("public-a", "haunted-ws"))
    assert response.status_code == 403


@pytest.mark.parametrize("path", READ_PATHS)
def test_locked_workspace_is_readable(environment, path):
    seed_corpus_for_workspace(environment, "locked-ws")
    response = get(environment, path.replace("public-a", "locked-ws").replace("doc-b", "locked-doc"))
    assert response.status_code == 200


def seed_corpus_for_workspace(environment, workspace_id):
    environment.source.records["locked-doc"] = document("locked-doc", workspace_id=workspace_id)


@pytest.mark.parametrize("path", READ_PATHS)
def test_ineligible_role_is_403(environment, path):
    environment.role_reader.side_effect = lambda _workspace, _user: "Guest"
    assert get(environment, path).status_code == 403


@pytest.mark.parametrize("path", READ_PATHS)
def test_absent_membership_is_403(environment, path):
    environment.role_reader.side_effect = lambda _workspace, _user: None
    assert get(environment, path).status_code == 403


def test_list_returns_only_current_revisions(environment):
    payload = get(environment).get_json()
    ids = document_ids(payload)
    assert "doc-a-r2" in ids
    assert "doc-a-r1" not in ids
    assert payload["total_count"] == 4
    assert payload["file_downloads_enabled"] is False
    assert set(payload) >= {
        "documents", "page", "page_size", "total_count",
        "file_downloads_enabled", "needs_legacy_update_check",
    }


def test_search_filter_narrows_the_set(environment):
    payload = get(environment, search="Beta").get_json()
    assert document_ids(payload) == ["doc-b"]


def test_tag_filter_narrows_the_set(environment):
    payload = get(environment, tags="reference").get_json()
    ids = set(document_ids(payload))
    assert "doc-b" not in ids
    assert "doc-a-r2" in ids


def test_classification_filter_narrows_the_set(environment):
    payload = get(environment, classification="Public").get_json()
    assert "doc-b" not in document_ids(payload)


def test_author_keyword_abstract_filters(environment):
    assert document_ids(get(environment, author="Grace Hopper").get_json()) == ["doc-b"]
    assert document_ids(get(environment, keywords="alpha").get_json()) == ["doc-b"]
    assert document_ids(get(environment, abstract="alpha overview").get_json()) == ["doc-b"]


@pytest.mark.parametrize("place", ["all", "recent", "processing", "errors", "untagged"])
def test_standing_view_places(environment, place):
    assert get(environment, place=place).status_code == 200


def test_processing_place_selects_incomplete(environment):
    payload = get(environment, place="processing").get_json()
    assert document_ids(payload) == ["doc-processing"]


def test_errors_place_selects_failures(environment):
    payload = get(environment, place="errors").get_json()
    assert document_ids(payload) == ["doc-error"]


def test_shared_place_coerces_to_all(environment):
    payload = get(environment, place="shared").get_json()
    assert payload["total_count"] == 4


@pytest.mark.parametrize("sort_by", [
    "file_name", "title", "version", "_ts", "upload_date", "file_size", "document_classification",
])
@pytest.mark.parametrize("sort_order", ["asc", "desc"])
def test_every_allowed_sort(environment, sort_by, sort_order):
    response = get(environment, sort_by=sort_by, sort_order=sort_order)
    assert response.status_code == 200
    assert len(response.get_json()["documents"]) == 4


def test_unknown_sort_field_falls_back_without_error(environment):
    assert get(environment, sort_by="ssn").status_code == 200


def test_pagination_pages_the_set(environment):
    first = get(environment, page=1, page_size=2).get_json()
    second = get(environment, page=2, page_size=2).get_json()
    assert first["total_count"] == 4
    assert len(first["documents"]) == 2
    assert len(second["documents"]) == 2
    assert set(document_ids(first)).isdisjoint(document_ids(second))


def test_facets_expose_the_full_safe_set(environment):
    facets = get(environment, f"{LIST_PATH}/facets").get_json()
    assert facets["total"] == 4
    assert facets["untagged"] == 2
    assert facets["processing"] == 1
    assert facets["errors"] == 1
    assert facets["by_tag"]["reference"] == 2
    assert facets["by_classification"]["Public"] == 3


def test_tags_carry_definition_colors_and_are_sorted(environment):
    tags = get(environment, f"{LIST_PATH}/tags").get_json()["tags"]
    names = [tag["name"] for tag in tags]
    assert names == sorted(names)
    by_name = {tag["name"]: tag for tag in tags}
    assert by_name["reference"]["color"] == "#abcdef"
    assert by_name["reference"]["count"] == 2
    assert by_name["unused"]["count"] == 0


def test_single_document_is_top_level_and_actionable(environment):
    payload = get(environment, f"{LIST_PATH}/doc-b").get_json()
    assert payload["id"] == "doc-b"
    assert payload["document_actions"] == []
    assert "documents" not in payload


def test_single_document_unknown_is_404(environment):
    assert get(environment, f"{LIST_PATH}/no-such-doc").status_code == 404


def test_single_document_from_another_workspace_is_404(environment):
    assert get(environment, f"{LIST_PATH}/doc-other").status_code == 404


def test_versions_only_expose_workspace_revisions(environment):
    payload = get(environment, f"{LIST_PATH}/doc-a-r2/versions").get_json()
    assert payload["document_id"] == "doc-a-r2"
    assert payload["public_workspace_id"] == "public-a"
    current = {item["id"]: item["is_current_version"] for item in payload["versions"]}
    assert current == {"doc-a-r2": True, "doc-a-r1": False}
    for item in payload["versions"]:
        assert item["document_actions"] == []


def test_versions_reject_a_foreign_document(environment):
    assert get(environment, f"{LIST_PATH}/doc-other/versions").status_code == 404


@pytest.mark.parametrize("path", READ_PATHS)
def test_unknown_query_parameter_is_400(environment, path):
    assert get(environment, path, bogus="1").status_code == 400


@pytest.mark.parametrize("path", NO_PARAM_PATHS)
def test_no_parameter_endpoints_reject_known_list_parameters(environment, path):
    assert get(environment, path, page="1").status_code == 400


def test_duplicate_query_parameter_is_400(environment):
    response = environment.client.get(LIST_PATH, query_string="page=1&page=2")
    assert response.status_code == 400


@pytest.mark.parametrize("path", READ_PATHS)
def test_request_body_is_rejected(environment, path):
    response = environment.client.get(path, data=b"{}", content_type="application/json")
    assert response.status_code == 400


@pytest.mark.parametrize("path", READ_PATHS)
def test_feature_flag_gate(environment, path):
    environment.settings["enable_public_workspaces"] = False
    assert get(environment, path).status_code == 400


@pytest.mark.parametrize("path", READ_PATHS)
def test_unauthenticated_request_is_denied(environment, path):
    with environment.client.session_transaction() as state:
        state.clear()
    assert get(environment, path).status_code in (401, 302)


@pytest.mark.parametrize("path", [LIST_PATH, f"{LIST_PATH}/doc-b", f"{LIST_PATH}/doc-a-r2/versions"])
def test_private_fields_never_leak(environment, path):
    response = get(environment, path)
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert PRIVATE_TEXT not in body
    assert "blob_path" not in body


def test_membership_revoked_after_query_denies(environment):
    def revoke():
        environment.workspaces.pop("public-a", None)
    environment.source.after_query = revoke
    assert get(environment).status_code in (403, 404)


def test_provider_failure_does_not_leak(environment):
    environment.source.failure = RuntimeError("cosmos-secret-diagnostic")
    response = get(environment)
    assert response.status_code == 500
    assert "cosmos-secret-diagnostic" not in response.get_data(as_text=True)


def test_source_queries_are_workspace_scoped(environment):
    get(environment)
    assert environment.source.queries
    for _query, parameters, _kwargs in environment.source.queries:
        names = {parameter["name"] for parameter in parameters}
        assert "@workspace_id" in names or "@owner_workspace_id" in names


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
