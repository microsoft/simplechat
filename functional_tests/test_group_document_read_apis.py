# test_group_document_read_apis.py
"""
Functional tests for explicitly scoped group document browsing.
Version: 0.261.128
Implemented in: 0.261.128

The real group read module, route registrar, group membership helpers, document
query helpers, DAI reader, and screening response guard run in an isolated Flask
app. Existing functions_documents definitions execute unchanged without its
unrelated ingestion imports. Cosmos, authentication configuration, and telemetry
are local test seams; network access and source writes are prohibited.
"""

import ast
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from functools import wraps
import importlib.util
import logging
from pathlib import Path
import re
import socket
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask import Blueprint, Flask, jsonify, request, session

from test_cosmos_wave5a_document_access_read_switch import (
    _load_document_access_index_module,
    _settings,
    _succeeded_backfill_state,
)
from test_support.agent_delegation import APP_ROOT, execute_functions, module_stub
from test_support.versioning import assert_app_version_at_least


READ_PATHS = (
    "/api/group_documents",
    "/api/group_documents/facets",
    "/api/group_documents/tags",
    "/api/group_documents/document-a",
    "/api/group_documents/document-a/versions",
)
PRIVATE_TEXT = "PRIVATE-EXTRACTED-CONTENT"


class MissingRecord(Exception):
    status_code = 404


class ReadOnlyContainer:
    def __init__(self, records=None):
        self.records = records if records is not None else {}
        self.queries = []
        self.reads = Counter()
        self.failure = None
        self.after_query = None
        self.after_read = None

    def read_item(self, item, partition_key):
        self.reads[item] += 1
        if self.failure:
            raise self.failure
        if item not in self.records:
            raise MissingRecord()
        record = deepcopy(self.records[item])
        if self.after_read:
            self.after_read(item)
        return record

    def query_items(self, query, parameters=None, **kwargs):
        self.queries.append((query, deepcopy(parameters or []), kwargs))
        if self.failure:
            raise self.failure
        values = {parameter["name"]: parameter["value"] for parameter in parameters or []}
        group_ids = [
            value for name, value in values.items()
            if name == "@group_id" or re.fullmatch(r"@group_id_\d+", name)
        ]
        if "@partition_key" in values:
            group_ids.append(values["@partition_key"])
        if not group_ids and "@owner_group_id" not in values:
            raise AssertionError("A group source query must be explicitly scoped.")
        records = []
        for record in self.records.values():
            if "@owner_group_id" in values:
                if record.get("group_id") != values["@owner_group_id"]:
                    continue
                field = re.search(r"c\.(\w+) = @family_identity", query).group(1)
                if record.get(field) != values["@family_identity"]:
                    continue
            else:
                owned = record.get("group_id") in group_ids
                shared = "c.shared_group_ids" in query and any(
                    str(entry).split(",", 1)[0] in group_ids
                    for entry in record.get("shared_group_ids") or []
                )
                if not owned and not shared:
                    continue
            if "@document_ids" in values and record["id"] not in values["@document_ids"]:
                continue
            if "NOT IS_DEFINED(c.percentage_complete)" in query and "percentage_complete" in record:
                continue
            if "ARRAY_LENGTH(c.tags) > 0" in query and not record.get("tags"):
                continue
            records.append(deepcopy(record))
        if self.after_query:
            self.after_query()
        return [len(records)] if "COUNT(1)" in query else records


def document(document_id, group_id="group-a", **changes):
    value = {
        "id": document_id,
        "document_id": document_id,
        "group_id": group_id,
        "user_id": "unrelated-uploader",
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
        "document_classification": "Internal",
        "file_size": 100,
        "number_of_pages": 2,
        "upload_date": "2026-09-01T12:00:00Z",
        "_ts": int((datetime.now(timezone.utc) - timedelta(days=2)).timestamp()),
        "shared_group_ids": [],
    }
    value.update(changes)
    return value


def load_real_module(monkeypatch, name):
    spec = importlib.util.spec_from_file_location(name, APP_ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def environment(monkeypatch):
    settings = {
        **_settings(),
        "enable_group_workspaces": True,
        "enable_document_access_index_cache": False,
        "enable_content_screening": False,
    }
    with _load_document_access_index_module(settings=settings) as (index, index_container, index_settings):
        with monkeypatch.context() as scoped:
            scoped.syspath_prepend(str(APP_ROOT))
            network = Mock(side_effect=AssertionError("No network access in read API tests."))
            scoped.setattr(socket, "create_connection", network)
            scoped.setattr(socket.socket, "connect", network)
            index_settings.upsert_item(_succeeded_backfill_state())
            groups = {
                group_id: {
                    "id": group_id, "name": f"Name of {group_id}", "status": "active",
                    "owner": {"id": "owner"}, "admins": ["admin"],
                    "documentManagers": ["manager"], "users": [{"userId": "reader"}],
                    "pendingUsers": [{"userId": "pending-member"}],
                    "tag_definitions": {"unused": {"color": "#123456"}, "reference": {"color": "#abc"}},
                }
                for group_id in ("group-a", "group-b", "source-group")
            }
            source = ReadOnlyContainer({
                "document-a": document("document-a"),
                "document-b": document("document-b", "group-b"),
            })
            group_container = ReadOnlyContainer(groups)
            personal = ReadOnlyContainer()
            scans = ReadOnlyContainer()
            env = SimpleNamespace(
                settings=settings, groups=groups, source=source, group_container=group_container,
                personal=personal, scans=scans, index=index, index_container=index_container,
                index_settings=index_settings,
                active_group="group-b", downloads=True, logs=Mock(), network=network,
            )
            user_settings = Mock(side_effect=lambda _user: {"settings": {"activeGroupOid": env.active_group}})
            settings_module = module_stub(
                "functions_settings", get_settings=lambda: settings,
                get_user_settings=user_settings,
                is_group_workspace_file_download_enabled=lambda _settings, _group: env.downloads,
            )
            settings_namespace = {"wraps": wraps, "get_settings": lambda: settings, "jsonify": jsonify}
            execute_functions("functions_settings.py", {"enabled_required"}, settings_namespace)
            settings_module.enabled_required = settings_namespace["enabled_required"]
            scoped.setitem(sys.modules, "functions_settings", settings_module)
            scoped.setitem(sys.modules, "functions_appinsights", module_stub("functions_appinsights", log_event=env.logs))
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
                "config", cosmos_group_documents_container=source, cosmos_groups_container=group_container,
                cosmos_user_documents_container=personal, cosmos_public_documents_container=ReadOnlyContainer(),
                cosmos_content_screening_container=scans, jsonify=jsonify, request=request, session=session,
                exceptions=SimpleNamespace(CosmosResourceNotFoundError=MissingRecord),
            )
            scoped.setitem(sys.modules, "config", config)
            scoped.setitem(sys.modules, "functions_chat_bootstrap_cache", module_stub(
                "functions_chat_bootstrap_cache", bump_chat_bootstrap_global_cache_version=Mock(),
            ))
            scoped.setitem(sys.modules, "functions_workspace_branding", module_stub(
                "functions_workspace_branding", DEFAULT_WORKSPACE_HERO_COLOR="#0078d4",
            ))
            real_groups = load_real_module(scoped, "functions_group")
            queries = load_real_module(scoped, "functions_document_queries")
            document_namespace = {"re": re, "cosmos_group_documents_container": source}
            tree = ast.parse((APP_ROOT / "functions_documents.py").read_text(encoding="utf-8"))
            constant_names = {
                "NUMERIC_DOCUMENT_SORT_FIELDS", "TEXT_DOCUMENT_SORT_FIELDS", "ALLOWED_DOCUMENT_SORT_FIELDS",
                "DEFAULT_DOCUMENT_SORT_FIELD", "ARCHIVED_REVISION_BLOB_PATH_MODE", "TAG_COLOR_PATTERN",
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
                "get_workspace_tags",
            }, document_namespace)
            document_namespace["validate_document_access_index_shadow"] = Mock()
            scoped.setitem(sys.modules, "functions_documents", module_stub("functions_documents", **document_namespace))
            # Resolve screening only after replacing application bootstrap dependencies.
            from content_screening import access
            from content_screening.contracts import (
                ContentUnit, content_fingerprint, hash_payload, metadata_fingerprint, subject_from_document,
            )

            def seed_release(record):
                policy = {"test_policy": "approved"}
                marker = {
                    "state": "cleared", "scan_id": f"scan-{record['id']}",
                    "source_revision": str(record["version"]), "review_required": False,
                    "content_fingerprint": content_fingerprint([ContentUnit("unit-1", "safe", {})]),
                    "policy_fingerprint": hash_payload(policy), "canonical_ref": {"name": "canonical"},
                    "active_blob": {"container": "group-documents", "path": f"{record['id']}/cleared.pdf"},
                }
                record["content_screening"] = marker
                scans.records[marker["scan_id"]] = {
                    "id": marker["scan_id"], "kind": "scan", "subject": subject_from_document(record).to_dict(),
                    "state": "cleared", "coverage_complete": True, "result_status": "pass",
                    "content_fingerprint": marker["content_fingerprint"], "policy": policy,
                    "policy_fingerprint": marker["policy_fingerprint"], "units_ref": marker["canonical_ref"],
                    "publication": {
                        "active_blob": marker["active_blob"], "metadata_fingerprint": metadata_fingerprint(record),
                        "content_fingerprint": marker["content_fingerprint"],
                    },
                }

            stubs = {
                "content_screening.service": {"prepare_document_upload": Mock()},
                "agent_execution_context": {"execution_user_id": lambda: None},
                "functions_artifact_publication": {"decide_artifact_publication": Mock()},
                "functions_file_sync": {
                    "FILE_SYNC_SCOPE_GROUP": "group", "apply_synced_document_delete_action": Mock(),
                    "build_synced_document_delete_guard": Mock(),
                },
                "functions_notifications": {"create_notification": Mock(), "delete_notifications_by_metadata": Mock()},
                "functions_simplechat_operations": {
                    "download_blob_content": Mock(), "queue_generated_document_processing": Mock(),
                },
                "utils_cache": {"invalidate_group_search_cache": Mock()},
                "functions_debug": {"debug_print": Mock()},
                "functions_activity_logging": {"log_document_upload": Mock()},
                "swagger_wrapper": {
                    "swagger_route": lambda **_kwargs: lambda function: function,
                    "get_auth_security": lambda: [{"sessionAuth": []}],
                },
            }
            for name, values in stubs.items():
                scoped.setitem(sys.modules, name, module_stub(name, **values))
            helper = load_real_module(scoped, "functions_group_document_reads")
            route = load_real_module(scoped, "route_backend_group_documents")
            app = Flask("group_document_read_contract")
            app.config.update(TESTING=True, SECRET_KEY="test-only-session-key")
            blueprint = Blueprint("backend_group_documents", __name__)
            blueprint.before_request(auth.user_required_blueprint())
            route.register_route_backend_group_documents(blueprint)
            app.register_blueprint(blueprint)
            client = app.test_client()
            with client.session_transaction() as state:
                state["user"] = {"oid": "reader", "roles": ["User"]}

            env.client = client
            env.app = app
            env.helper = helper
            env.route = route
            env.access = access
            env.queries = queries
            env.real_groups = real_groups
            env.user_settings = user_settings
            env.seed_release = seed_release
            env.document_helpers = document_namespace
            yield env
            network.assert_not_called()


def get(environment, path=READ_PATHS[0], **args):
    return environment.client.get(path, query_string={"group_id": "group-a", **args})


def seed_index(environment):
    for record in environment.source.records.values():
        rows = environment.index.build_document_access_index_rows(record)
        for row in rows:
            environment.index_container.upsert_item(row)
    environment.index_container.queries.clear()


def set_index_ready(environment, ready):
    state = _succeeded_backfill_state()
    if not ready:
        state["status"] = "running"
    environment.index_settings.upsert_item(state)


@pytest.mark.parametrize("path", READ_PATHS)
def test_explicit_scope_never_reads_active_preference(environment, path):
    environment.active_group = "missing-active-group"
    response = get(environment, path)
    assert response.status_code == 200
    assert "no-store" in response.headers["Cache-Control"]
    assert response.headers.get("ETag") is None
    environment.user_settings.assert_not_called()


@pytest.mark.parametrize("path", READ_PATHS)
@pytest.mark.parametrize("query", [
    "group_id=", "group_id=%20", "group_id=group-a%20", "group_id=.", "group_id=..",
    "group_id=group%2Fa", "group_id=group%5Ca", "group_id=group%3Fa", "group_id=group%23a",
    "group_id=group%00a", "group_id=group-a,group-b",
    "group_id=group-a&group_id=group-b", "group_id=group-a&group_ids=",
    "group_id=&group_ids=group-b",
])
def test_bad_explicit_scope_cannot_fall_back(environment, path, query):
    response = environment.client.get(f"{path}?{query}")
    assert response.status_code == 400
    assert response.get_json().get("error")
    assert not environment.source.queries
    environment.user_settings.assert_not_called()


@pytest.mark.parametrize("path", READ_PATHS)
@pytest.mark.parametrize("actor,expected", [
    ("owner", 200), ("admin", 200), ("manager", 200), ("reader", 200),
    ("stranger", 403), ("pending-member", 403),
])
def test_current_membership_and_all_four_read_roles(environment, path, actor, expected):
    with environment.client.session_transaction() as state:
        state["user"] = {**state["user"], "oid": actor}
    response = get(environment, path)
    assert response.status_code == expected
    if expected == 403:
        assert not environment.source.queries


@pytest.mark.parametrize("path", READ_PATHS)
@pytest.mark.parametrize("status,expected", [
    ("active", 200), ("locked", 200), ("upload_disabled", 200), ("inactive", 403), ("unknown", 403),
])
def test_read_status_is_the_selected_group_not_the_active_group(environment, path, status, expected):
    environment.groups["group-a"]["status"] = status
    environment.groups["group-b"]["status"] = "inactive"
    response = get(environment, path)
    assert response.status_code == expected


@pytest.mark.parametrize("path", READ_PATHS)
def test_missing_group_and_revoked_membership_are_not_empty_success(environment, path):
    missing = get(environment, path, group_id="missing")
    environment.groups["group-a"]["users"] = []
    revoked = get(environment, path)
    assert missing.status_code == 404
    assert revoked.status_code == 403
    assert "documents" not in revoked.get_json()


@pytest.mark.parametrize("path", READ_PATHS)
def test_membership_rechecked_after_a_source_query(environment, path):
    environment.source.after_query = lambda: environment.groups["group-a"].update(users=[])
    response = get(environment, path)
    assert response.status_code == 403


@pytest.mark.parametrize("path", READ_PATHS)
def test_unauthenticated_feature_and_app_role_guards(environment, path):
    with environment.client.session_transaction() as state:
        state.clear()
    unauthenticated = get(environment, path)
    with environment.client.session_transaction() as state:
        state["user"] = {"oid": "owner", "roles": []}
    no_app_role = get(environment, path)
    with environment.client.session_transaction() as state:
        state["user"] = {**state["user"], "roles": ["User"]}
    environment.settings["enable_group_workspaces"] = False
    disabled = get(environment, path)
    assert unauthenticated.status_code == 401
    assert no_app_role.status_code == 403
    assert disabled.status_code == 400
    assert not environment.source.queries


@pytest.mark.parametrize("suffix", ["", "/versions"])
def test_exact_target_must_belong_to_requested_group_even_for_dual_members(environment, suffix):
    response = get(environment, f"/api/group_documents/document-b{suffix}")
    assert response.status_code == 404
    assert len(environment.source.queries) == 1


def test_malformed_or_unrecognized_share_entries_do_not_grant_access(environment):
    for shared_group_ids in ("group-a", ["group-a,unknown"], ["group-aa,approved"], [{"group_id": "group-a"}]):
        environment.source.records["wrong-share"] = document(
            "wrong-share", "source-group", shared_group_ids=shared_group_ids,
        )
        response = get(environment, "/api/group_documents/wrong-share")
        assert response.status_code == 404


@pytest.mark.parametrize("suffix", ["", "/versions"])
def test_colliding_personal_and_group_ids_keep_group_metadata_and_screening(environment, suffix):
    environment.personal.records["document-a"] = {
        **document("document-a"), "group_id": None, "user_id": "reader", "abstract": PRIVATE_TEXT,
    }
    environment.source.records["document-a"].update(
        abstract=PRIVATE_TEXT, title=PRIVATE_TEXT, tags=[PRIVATE_TEXT], blob_path=PRIVATE_TEXT,
        content_screening={"state": "pending_review", "scan_id": "held-a", "source_revision": "1"},
    )
    response = get(environment, f"/api/group_documents/document-a{suffix}")
    body = response.get_json()
    record = body["versions"][0] if suffix else body
    assert response.status_code == 200
    assert record["group_id"] == "group-a"
    assert record["shared_approval_status"] == "owner"
    assert record["content_screening"]["available"] is False
    assert PRIVATE_TEXT not in response.get_data(as_text=True)
    assert not environment.personal.reads
    assert not environment.personal.queries


def test_owned_approved_pending_and_held_relationships_match_across_reads(environment):
    environment.source.records.update({
        "shared": document("shared", "source-group", shared_group_ids=["group-a,approved"]),
        "pending": document(
            "pending", "source-group", shared_group_ids=["group-a,not_approved"],
            title=PRIVATE_TEXT, abstract=PRIVATE_TEXT, tags=[PRIVATE_TEXT], blob_path=PRIVATE_TEXT, status=PRIVATE_TEXT,
        ),
        "held": document(
            "held", "source-group", shared_group_ids=["group-a,approved"],
            title=PRIVATE_TEXT, abstract=PRIVATE_TEXT, tags=[PRIVATE_TEXT], blob_path=PRIVATE_TEXT,
            content_screening={"state": "pending_review", "scan_id": "scan-held", "source_revision": "1"},
        ),
        "bare": document("bare", "source-group", shared_group_ids=["group-a"]),
        "not-related": document("not-related", "source-group", shared_group_ids=["group-aa,approved"]),
    })
    environment.groups["source-group"]["users"] = []
    listed = get(environment, page_size=50)
    rows = {row["id"]: row for row in listed.get_json()["documents"]}
    assert set(rows) == {"document-a", "shared", "pending", "held", "bare"}
    assert rows["document-a"]["shared_approval_status"] == "owner"
    for document_id, approval in (
        ("shared", "approved"), ("bare", "approved"), ("pending", "not_approved"), ("held", "approved"),
    ):
        detail = get(environment, f"/api/group_documents/{document_id}")
        versions = get(environment, f"/api/group_documents/{document_id}/versions")
        for row in (rows[document_id], detail.get_json(), versions.get_json()["versions"][0]):
            assert row["group_id"] == "source-group"
            assert row["owner_group_id"] == "source-group"
            assert row["shared_group_active_id"] == "group-a"
            assert row["shared_approval_status"] == approval
            assert row["owner_group_name"] == "Name of source-group"
    assert PRIVATE_TEXT not in listed.get_data(as_text=True)
    assert rows["pending"]["status"] == "Awaiting group share approval"


def test_versions_authorize_target_and_each_revision_independently(environment):
    environment.source.records.update({
        "old-shared": document(
            "old-shared", "source-group", revision_family_id="shared-family", version=1,
            file_name="old-name.pdf", is_current_version=False, shared_group_ids=["group-a,approved"],
        ),
        "private-sibling": document(
            "private-sibling", "source-group", revision_family_id="shared-family", version=2,
            is_current_version=False, abstract=PRIVATE_TEXT,
        ),
        "pending-sibling": document(
            "pending-sibling", "source-group", revision_family_id="shared-family", version=3,
            is_current_version=False, shared_group_ids=["group-a,not_approved"], abstract=PRIVATE_TEXT,
        ),
        "shared-current": document(
            "shared-current", "source-group", revision_family_id="shared-family", version=4,
            shared_group_ids=["group-a,approved"],
        ),
        "different-origin": document(
            "different-origin", "group-b", revision_family_id="shared-family", version=99,
        ),
    })
    response = get(environment, "/api/group_documents/old-shared/versions")
    body = response.get_json()
    denied_target = get(environment, "/api/group_documents/private-sibling/versions")
    assert response.status_code == 200
    assert body["document_id"] == "old-shared"
    assert body["group_id"] == "group-a"
    assert body["revision_family_id"] == "shared-family"
    assert [row["id"] for row in body["versions"]] == ["shared-current", "pending-sibling", "old-shared"]
    assert [row["shared_approval_status"] for row in body["versions"]] == ["approved", "not_approved", "approved"]
    assert [row["is_current_version"] for row in body["versions"]] == [True, False, False]
    assert PRIVATE_TEXT not in response.get_data(as_text=True)
    assert denied_target.status_code == 404


def test_versions_keep_one_derived_current_revision_for_legacy_metadata(environment):
    old = document("legacy-old", file_name="legacy.pdf", version=1)
    current = document("legacy-current", file_name="legacy.pdf", version=2)
    for record in (old, current):
        record.pop("revision_family_id")
        record.pop("is_current_version")
    environment.source.records.update({old["id"]: old, current["id"]: current})
    legacy = get(environment, "/api/group_documents/legacy-old/versions")
    for record in (old, current):
        record["is_current_version"] = True
    duplicate_markers = get(environment, "/api/group_documents/legacy-old/versions")
    for response in (legacy, duplicate_markers):
        body = response.get_json()
        assert response.status_code == 200
        assert body["revision_family_id"] == "legacy-current"
        assert [row["is_current_version"] for row in body["versions"]] == [True, False]


def test_versions_cannot_borrow_a_siblings_share_after_target_revocation(environment):
    target = document("target", "source-group", revision_family_id="family", shared_group_ids=["group-a,approved"])
    sibling = document(
        "sibling", "source-group", revision_family_id="family", version=2, shared_group_ids=["group-a,approved"],
    )
    environment.source.records.update(target=target, sibling=sibling)
    environment.source.after_query = lambda: target.update(shared_group_ids=[])
    response = get(environment, "/api/group_documents/target/versions")
    assert response.status_code == 404
    assert "versions" not in response.get_json()


def test_equal_family_ids_in_different_origin_groups_do_not_collapse(environment):
    environment.source.records = {
        "owned": document("owned", revision_family_id="same-family"),
        "shared": document(
            "shared", "source-group", revision_family_id="same-family", shared_group_ids=["group-a,approved"],
        ),
    }
    response = get(environment)
    assert response.get_json()["total_count"] == 2
    assert {row["id"] for row in response.get_json()["documents"]} == {"owned", "shared"}


@pytest.mark.parametrize("index_ready", [False, True])
def test_strict_reads_are_complete_when_index_is_stale_or_missing(environment, index_ready):
    seed_index(environment)
    set_index_ready(environment, index_ready)
    old = environment.source.records["document-a"]
    old.update(is_current_version=False)
    environment.source.records["new-current"] = document(
        "new-current", revision_family_id="document-a", version=2,
        title="new title", tags=["new-tag"], file_size=4096,
    )
    environment.source.records["new-share"] = document(
        "new-share", "source-group", shared_group_ids=["group-a,approved"], tags=["new-tag"],
    )
    listed = get(environment, search="new", tags="new-tag", sort_by="file_size", sort_order="desc")
    facets = get(environment, READ_PATHS[1])
    tags = get(environment, READ_PATHS[2])
    assert listed.status_code == 200
    assert [row["id"] for row in listed.get_json()["documents"]] == ["new-current", "new-share"]
    assert listed.get_json()["total_count"] == 2
    assert facets.get_json()["total"] == 2
    assert facets.get_json()["by_tag"] == {"new-tag": 2}
    tag_counts = {tag["name"]: tag["count"] for tag in tags.get_json()["tags"]}
    assert tag_counts["new-tag"] == 2
    assert not environment.index_container.queries


def test_share_revocation_is_not_a_dai_authorization(environment):
    shared = document("shared", "source-group", shared_group_ids=["group-a,approved"])
    environment.source.records["shared"] = shared
    seed_index(environment)
    shared["shared_group_ids"] = ["group-b,approved"]
    listed = get(environment)
    detail = get(environment, "/api/group_documents/shared")
    versions = get(environment, "/api/group_documents/shared/versions")
    assert [row["id"] for row in listed.get_json()["documents"]] == ["document-a"]
    assert detail.status_code == 404
    assert versions.status_code == 404


def test_final_batch_projection_rechecks_share_revocation_without_falling_back(environment):
    shared = document("shared", "source-group", shared_group_ids=["group-a,approved"])
    environment.source.records["shared"] = shared
    calls = []

    def revoke_after_snapshot():
        calls.append(True)
        if len(calls) == 1:
            shared["shared_group_ids"] = ["group-b,approved"]

    environment.source.after_query = revoke_after_snapshot
    response = get(environment)
    assert response.status_code == 404
    assert "documents" not in response.get_json()
    assert not environment.personal.reads


def test_final_batch_projection_redacts_a_new_hold(environment):
    record = environment.source.records["document-a"]
    record["abstract"] = PRIVATE_TEXT
    environment.source.after_query = lambda: record.update(
        content_screening={"state": "pending_review", "source_revision": "1", "scan_id": "held"},
    )
    response = get(environment)
    assert response.status_code == 200
    assert response.get_json()["total_count"] == 1
    assert response.get_json()["documents"][0]["content_screening"]["available"] is False
    assert PRIVATE_TEXT not in response.get_data(as_text=True)


def test_final_batch_projection_reports_storage_failure_and_changed_identity(environment):
    environment.source.after_query = lambda: setattr(
        environment.source, "failure", RuntimeError("AccountKey=PRIVATE-PROVIDER-ERROR"),
    )
    failed = get(environment)
    environment.source.failure = None
    record = environment.source.records["document-a"]
    environment.source.after_query = lambda: record.update(group_id="source-group", shared_group_ids=["group-a,approved"])
    changed = get(environment)
    assert failed.status_code == 500
    assert failed.get_json() == {"error": "Unable to retrieve group documents."}
    assert changed.status_code == 409
    assert "documents" not in changed.get_json()


def test_release_proof_is_from_the_source_even_when_recipient_differs(environment):
    shared = document("shared", "source-group", shared_group_ids=["group-a,approved"])
    environment.source.records["shared"] = shared
    environment.seed_release(shared)
    available = get(environment, "/api/group_documents/shared")
    environment.scans.records["scan-shared"]["subject"]["scope_id"] = "group-a"
    forged = get(environment, "/api/group_documents/shared")
    assert available.get_json()["content_screening"]["available"] is True
    assert forged.get_json()["content_screening"]["available"] is False
    assert "abstract" not in forged.get_json()


def test_full_set_queries_facets_and_tags_are_not_limited_to_a_page(environment):
    environment.source.records = {
        f"item-{number:02}": document(
            f"item-{number:02}",
            tags=["alpha", "beta"] if number % 2 else ["alpha"],
            file_size=number * 100, title=f"Report {number:02}",
            percentage_complete=25 if number == 13 else 100,
            status="Error: conversion failed" if number == 15 else "Processing complete",
            document_classification="Restricted" if number > 10 else "Internal",
        )
        for number in range(1, 26)
    }
    environment.source.records["untagged"] = document("untagged", tags=[" "], _ts=1)
    environment.source.records["shared"] = document("shared", "source-group", shared_group_ids=["group-a,approved"])
    environment.source.records["old-match"] = document(
        "old-match", revision_family_id="item-02", version=0, is_current_version=False, tags=["historical"],
    )
    filtered = get(
        environment, tags="ALPHA,beta", search="report", classification="Restricted",
        author="ada", keywords="ref", abstract="useful", sort_by="file_size",
        sort_order="desc", page=2, page_size=3,
    )
    facets_response = get(environment, READ_PATHS[1], search="no-match", tags="historical", page=99, place="errors")
    tags_response = get(environment, READ_PATHS[2], search="no-match", page_size=1)
    body = filtered.get_json()
    facets = facets_response.get_json()
    tag_counts = {tag["name"]: tag["count"] for tag in tags_response.get_json()["tags"]}
    assert filtered.status_code == 200
    assert body["total_count"] == 8
    assert body["page"] == 2 and body["page_size"] == 3
    assert [row["id"] for row in body["documents"]] == ["item-19", "item-17", "item-15"]
    assert facets == {
        "total": 27, "untagged": 1, "processing": 1, "errors": 1,
        "recent": 26, "shared_with_me": 1, "by_tag": {"alpha": 25, "beta": 13, "reference": 1},
        "by_classification": {"Internal": 12, "Restricted": 15},
    }
    assert tag_counts == {"alpha": 25, "beta": 13, "reference": 1, "unused": 0}
    assert all("OFFSET" not in query and "LIMIT" not in query for query, _params, _kwargs in environment.source.queries)
    assert len(environment.source.queries) == 4
    assert not environment.source.reads


@pytest.mark.parametrize("field", [
    "_ts", "file_name", "title", "upload_date", "file_size",
    "number_of_pages", "version", "document_classification",
])
@pytest.mark.parametrize("order", ["asc", "desc"])
def test_every_sort_orders_the_full_set_before_paging(environment, field, order):
    numeric = field in environment.document_helpers["NUMERIC_DOCUMENT_SORT_FIELDS"]
    values = [3, 1, 4, 2] if numeric else ["Charlie", "alpha", "delta", "Bravo"]
    environment.source.records = {
        f"sort-{number}": document(f"sort-{number}", **{field: value})
        for number, value in enumerate(values)
    }
    response = get(environment, sort_by=field, sort_order=order, page=2, page_size=2)
    expected = ["sort-0", "sort-2"] if order == "asc" else ["sort-3", "sort-1"]
    assert response.status_code == 200
    assert [row["id"] for row in response.get_json()["documents"]] == expected
    assert response.get_json()["total_count"] == 4


@pytest.mark.parametrize("args,expected", [
    ({"author": "missing"}, []), ({"keywords": "missing"}, []), ({"abstract": "missing"}, []),
    ({"author": "LOVELACE", "keywords": "REF", "abstract": "SHARED"}, ["document-a"]),
    ({"classification": "none"}, ["empty", "unset"]),
    ({"classification": "Internal"}, ["document-a"]),
    ({"tags": "historical"}, []), ({"search": "historical-title"}, []),
])
def test_metadata_filters_use_current_records_with_legacy_matching_semantics(environment, args, expected):
    empty = document("empty", document_classification="")
    unset = document("unset")
    unset.pop("document_classification")
    literal_none = document("literal-none", document_classification="None")
    for record in (empty, unset, literal_none):
        record.update(authors=[], keywords=[], abstract="")
    environment.source.records.update(
        empty=empty, unset=unset, literal_none=literal_none,
        historical=document(
            "historical", revision_family_id="document-a", is_current_version=False, version=0,
            tags=["historical"], title="historical-title",
        ),
    )
    response = get(environment, sort_by="file_name", sort_order="asc", **args)
    assert response.status_code == 200
    assert [row["id"] for row in response.get_json()["documents"]] == expected


def test_empty_results_defaults_and_download_policy_metadata(environment):
    defaults = get(environment, page="invalid", page_size=0, sort_by="invalid", sort_order="invalid", place="invalid")
    no_matches = get(environment, search="missing", page=3, page_size=5)
    assert defaults.status_code == 200
    assert defaults.get_json()["page"] == 1 and defaults.get_json()["page_size"] == 10
    assert defaults.get_json()["file_downloads_enabled"] is False
    assert defaults.get_json()["file_download_enabled_group_ids"] == []
    assert no_matches.status_code == 200
    assert no_matches.get_json()["documents"] == [] and no_matches.get_json()["total_count"] == 0
    assert no_matches.get_json()["page"] == 3 and no_matches.get_json()["page_size"] == 5
    with environment.client.session_transaction() as state:
        state["user"] = {**state["user"], "oid": "manager"}
    enabled = get(environment)
    environment.downloads = False
    disabled = get(environment)
    assert enabled.get_json()["file_download_enabled_group_ids"] == ["group-a"]
    assert enabled.get_json()["file_downloads_enabled"] is True
    assert disabled.get_json()["file_download_enabled_group_ids"] == []
    assert disabled.get_json()["file_downloads_enabled"] is False


@pytest.mark.parametrize("place,expected", [
    ("all", {"ready", "processing", "failed", "shared", "legacy"}),
    ("recent", {"ready", "processing", "failed", "shared"}),
    ("shared", {"shared"}), ("processing", {"processing"}),
    ("errors", {"failed"}), ("untagged", {"legacy"}),
])
def test_standing_views_are_group_relative(environment, place, expected):
    environment.source.records = {
        "ready": document("ready"),
        "processing": document("processing", percentage_complete=50),
        "failed": document("failed", status="Processing failed", percentage_complete=50),
        "shared": document("shared", "source-group", user_id="reader", shared_group_ids=["group-a,approved"]),
        "legacy": document("legacy", tags=[], _ts=1),
    }
    environment.source.records["legacy"].pop("percentage_complete")
    response = get(environment, place=place, page_size=50)
    assert response.status_code == 200
    assert {row["id"] for row in response.get_json()["documents"]} == expected


def test_pending_and_held_content_cannot_leak_through_filters_or_facets(environment):
    held = document(
        "held", title=PRIVATE_TEXT, abstract=PRIVATE_TEXT, tags=[PRIVATE_TEXT],
        document_classification=PRIVATE_TEXT,
        content_screening={"state": "pending_review", "scan_id": "held", "source_revision": "1"},
    )
    pending = document(
        "pending", "source-group", shared_group_ids=["group-a,not_approved"],
        title=PRIVATE_TEXT, abstract=PRIVATE_TEXT, tags=[PRIVATE_TEXT], document_classification=PRIVATE_TEXT,
    )
    environment.source.records.update(held=held, pending=pending)
    for argument in ("search", "tags", "classification", "abstract"):
        response = get(environment, **{argument: PRIVATE_TEXT})
        assert response.get_json()["total_count"] == 0
    facets = get(environment, READ_PATHS[1])
    tags = get(environment, READ_PATHS[2])
    assert facets.get_json()["total"] == 3
    assert facets.get_json()["untagged"] == 2
    assert PRIVATE_TEXT not in facets.get_data(as_text=True)
    assert PRIVATE_TEXT not in tags.get_data(as_text=True)


@pytest.mark.parametrize("path", READ_PATHS)
def test_provider_failures_are_safe_errors_not_empty_success(environment, path):
    environment.source.failure = RuntimeError("AccountKey=PRIVATE-PROVIDER-ERROR")
    response = get(environment, path)
    assert response.status_code == 500
    assert response.get_json() == {"error": "Unable to retrieve group documents."}
    assert "PRIVATE-PROVIDER" not in response.get_data(as_text=True)
    environment.logs.assert_called()


def test_strict_tags_use_recipient_definitions_with_safe_colors(environment):
    environment.groups["group-a"]["tag_definitions"]["reference"]["color"] = "url(javascript:private)"
    environment.source.records["shared"] = document(
        "shared", "source-group", shared_group_ids=["group-a,approved"], tags=["reference", "incoming"],
    )
    response = get(environment, READ_PATHS[2])
    tags = {tag["name"]: tag for tag in response.get_json()["tags"]}
    assert tags["reference"]["count"] == 2
    assert tags["incoming"]["count"] == 1
    assert tags["unused"] == {"name": "unused", "count": 0, "color": "#123456"}
    assert all(re.fullmatch(r"#[0-9a-f]{6}", tag["color"]) for tag in tags.values())


@pytest.mark.parametrize("index_ready", [False, True])
def test_legacy_active_and_multi_group_lists_keep_both_data_paths(environment, index_ready):
    seed_index(environment)
    set_index_ready(environment, index_ready)
    active = environment.client.get(READ_PATHS[0])
    multi = environment.client.get(READ_PATHS[0], query_string={"group_ids": "group-a,missing,group-b"})
    excluded = environment.client.get(READ_PATHS[0], query_string={"group_ids": "missing"})
    assert active.status_code == 200 and multi.status_code == 200
    assert [row["id"] for row in active.get_json()["documents"]] == ["document-b"]
    assert {row["id"] for row in multi.get_json()["documents"]} == {"document-a", "document-b"}
    assert excluded.status_code == 200 and excluded.get_json()["documents"] == []
    environment.user_settings.assert_called()
    candidate_queries = [
        query for query in environment.index_container.queries
        if "c.source_document_id" in query["query"]
    ]
    assert bool(candidate_queries) is index_ready


def test_legacy_tags_detail_and_required_facets_versions_contract(environment):
    detail = environment.client.get("/api/group_documents/document-b")
    tags = environment.client.get(READ_PATHS[2], query_string={"group_ids": "group-a,missing,group-b"})
    facets = environment.client.get(READ_PATHS[1])
    versions = environment.client.get(READ_PATHS[4])
    assert detail.status_code == 200
    assert detail.get_json()["group_id"] == "group-b"
    assert tags.status_code == 200 and isinstance(tags.get_json()["tags"], list)
    assert facets.status_code == 400 and versions.status_code == 400


def test_query_parameters_do_not_retarget_existing_mutations(environment):
    with environment.client.session_transaction() as state:
        state["user"] = {**state["user"], "oid": "owner"}
    original = environment.route._require_active_group_document_context
    calls = []

    def capture(*args, **kwargs):
        result = original(*args, **kwargs)
        calls.append(result[0])
        return result

    environment.route._require_active_group_document_context = capture
    try:
        response = environment.client.post("/api/group_documents/upload?group_id=group-a")
    finally:
        environment.route._require_active_group_document_context = original
    assert response.status_code == 400
    assert calls == ["group-b"]
    assert not environment.source.queries


def test_extracted_personal_helpers_keep_keyword_compatibility(environment):
    namespace = {
        "DOCUMENT_RECENT_DAYS": environment.queries.DOCUMENT_RECENT_DAYS,
        "build_document_facets": environment.queries.build_document_facets,
        "filter_workspace_documents_by_place": environment.queries.filter_documents_by_place,
    }
    execute_functions("route_backend_documents.py", {
        "build_personal_document_facets", "filter_documents_by_place",
    }, namespace)
    documents = [document("owned", user_id="reader"), document("shared", user_id="another-user")]
    facets = namespace["build_personal_document_facets"](documents=documents, user_id="reader", recent_days=1)
    filtered = namespace["filter_documents_by_place"](
        documents=documents, place="shared", user_id="reader", recent_days=1,
    )
    assert facets["shared_with_me"] == 1
    assert facets["recent"] == 0
    assert [row["id"] for row in filtered] == ["shared"]


def test_group_document_identity_is_container_wide_not_owner_partitioned():
    root = APP_ROOT.parents[1]
    tree = ast.parse((APP_ROOT / "config.py").read_text(encoding="utf-8"))
    container = next(
        node.value for node in tree.body if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "cosmos_group_documents_container"
            for target in node.targets
        )
    )
    partition = next(keyword.value for keyword in container.keywords if keyword.arg == "partition_key")
    partition_path = next(keyword.value for keyword in partition.keywords if keyword.arg == "path")
    configured_path = ast.literal_eval(partition_path)
    bicep = (root / "deployers" / "bicep" / "modules" / "cosmosDb.bicep").read_text(encoding="utf-8")
    terraform = (root / "deployers" / "terraform" / "main.tf").read_text(encoding="utf-8")
    bicep_partition = re.search(r"name:\s*'group_documents'\s+partitionKeyPath:\s*'([^']+)'", bicep)
    terraform_partition = re.search(r'group_documents\s*=\s*\{\s*partition_key_path\s*=\s*"([^"]+)"', terraform)
    assert configured_path == "/id"
    assert bicep_partition and bicep_partition.group(1) == "/id"
    assert terraform_partition and terraform_partition.group(1) == "/id"


def test_read_implementation_version():
    assert_app_version_at_least("0.261.128")


if __name__ == "__main__":
    raise SystemExit(pytest.main([str(Path(__file__).resolve()), "-q"]))
