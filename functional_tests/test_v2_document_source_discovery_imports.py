# test_v2_document_source_discovery_imports.py
"""Cold document-source discovery and route failures against real configuration.

Version: 0.261.404
Implemented in: 0.261.400
DAI-first discovery and source fallback implemented in: 0.261.404

Only external storage/cache I/O is replaced. Real config, discovery, DAI,
authorization, public payload projection and route registration execute with
network blocked in both normal and optimized Python.
"""

from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "application" / "single_app"
TESTS = ROOT / "functional_tests"
PROBE = r'''
import importlib
import sys
from contextlib import ExitStack
from unittest.mock import patch

sys.path[:0] = sys.argv[1:3]
from flask import Blueprint, Flask
from test_cosmos_wave6_document_access_cache import FakeRedisClient, FailingRedisClient
from test_support.cosmos_query_guard import assert_cosmos_query_supported
from test_support.offline_bootstrap import offline_app_imports

with offline_app_imports() as environment:
    for name in sys.argv[3:]:
        importlib.import_module(name)
    import config
    import functions_document_source_discovery as discovery
    import functions_document_access_index as indexing
    import route_backend_v2 as routes
    from functions_authentication import user_required_blueprint

    config.cosmos_user_settings_container.upsert_item(body={
        "id": "reader", "settings": {
            "profileImage": None, "personal_model_endpoints": [],
            "showTutorialButtons": True, "desktopNotificationsEnabled": True,
        },
    })
    settings = {
        "enable_group_workspaces": True, "enable_public_workspaces": True,
        "enable_document_access_index_cache": False,
    }
    owners = {"personal": "reader", "group": "group-1", "public": "public-1"}
    containers = {
        "personal": config.cosmos_user_documents_container,
        "group": config.cosmos_group_documents_container,
        "public": config.cosmos_public_documents_container,
    }

    records = {}
    for kind, field in (("personal", "user_id"), ("group", "group_id"), ("public", "public_workspace_id")):
        records[kind] = {
            "id": f"{kind}-document", "file_name": f"{kind}.pdf", "tags": ["policy"],
            field: owners[kind], "type": "document_metadata", "version": 1,
            "revision_family_id": f"{kind}-document", "is_current_version": True,
            "status": "Processing complete", "user_id": "reader",
        }
        containers[kind].upsert_item(body=records[kind])
        for row in indexing.build_document_access_index_rows(records[kind]):
            config.cosmos_document_access_index_container.upsert_item(body=row)

    group = {"id": "group-1", "name": "Policy group", "owner": {"id": "reader"},
             "users": [{"userId": "reader"}]}
    public = {"id": "public-1", "name": "Policy library", "status": "active"}
    config.cosmos_groups_container.upsert_item(body=group)
    config.cosmos_public_workspaces_container.upsert_item(body=public)
    source_reads = []
    index_reads = []

    def metadata_query(kind, *, query, parameters, **kwargs):
        assert_cosmos_query_supported(query)
        parameters = {parameter["name"]: parameter["value"] for parameter in parameters}
        if parameters.get("@owners") != [owners[kind]]:
            raise AssertionError("Discovery queried the wrong workspace owner.")
        if "SELECT *" in query or "chunk_text" in query:
            raise AssertionError("Fallback fetched content instead of required metadata.")
        source_reads.append(kind)
        return [dict(records[kind])]

    def index_query(*, query, parameters, partition_key=None, **kwargs):
        assert_cosmos_query_supported(query)
        parameters = {parameter["name"]: parameter["value"] for parameter in parameters}
        if parameters.get("@type") != indexing.DOCUMENT_ACCESS_INDEX_TYPE:
            return []
        if partition_key != parameters.get("@scope_key"):
            raise AssertionError("DAI lost its single-partition scope.")
        index_reads.append(parameters["@source_scope"])
        return [
            dict(row) for row in config.cosmos_document_access_index_container.items.values()
            if row["scope_key"] == partition_key and row["source_scope"] == parameters["@source_scope"]
        ]

    def backfill(*, status="succeeded", schema=None, completed=None, repairs=False):
        config.cosmos_settings_container.upsert_item(body={
            "id": indexing.DOCUMENT_ACCESS_BACKFILL_STATE_DOC_ID,
            "type": indexing.DOCUMENT_ACCESS_BACKFILL_STATE_TYPE,
            "status": status, "schema_version": indexing.DOCUMENT_ACCESS_INDEX_SCHEMA_VERSION if schema is None else schema,
            "completed_source_scopes": list(containers) if completed is None else completed,
        })
        config.cosmos_settings_container.upsert_item(body={
            "id": indexing.DOCUMENT_ACCESS_REPAIR_BACKLOG_STATE_DOC_ID,
            "type": indexing.DOCUMENT_ACCESS_REPAIR_BACKLOG_STATE_TYPE,
            "has_repair_backlog": repairs,
        })
        indexing._document_access_state_cache.clear()

    app = Flask("document_source_discovery_imports")
    app.config.update(TESTING=True, SECRET_KEY="fixture-only-signing")
    bp = Blueprint("backend_v2", __name__)
    bp.before_request(user_required_blueprint())
    routes.register_route_backend_v2(bp)
    app.register_blueprint(bp)
    client = app.test_client()
    with client.session_transaction() as state:
        state["user"] = {"oid": "reader", "roles": ["User"]}

    with ExitStack() as stack:
        stack.enter_context(patch.object(config.cosmos_groups_container, "query_items", return_value=[group]))
        stack.enter_context(patch.object(config.cosmos_public_workspaces_container, "query_items", return_value=[public]))
        stack.enter_context(patch.object(config.cosmos_document_access_index_container, "query_items", side_effect=index_query))
        for kind, container in containers.items():
            stack.enter_context(patch.object(
                container, "query_items",
                side_effect=lambda kind=kind, **kwargs: metadata_query(kind, **kwargs),
            ))
        stack.enter_context(patch.object(routes, "get_settings", return_value=settings))
        logs = stack.enter_context(patch.object(routes, "log_event"))

        response = client.get("/api/v2/document-sources?query=")
        payload = response.get_json()
        if response.status_code != 200:
            raise AssertionError(f"Initial directory failed: {response.status_code}, {payload}")
        if payload["source_total"] != 3 or payload["matching_workspace_count"] != 3:
            raise AssertionError("Directory lost authorized workspaces or document counts.")
        if [row["document"]["id"] for row in payload["documents"]] != [
            "personal-document", "group-document", "public-document",
        ]:
            raise AssertionError("Discovery did not read all three configured document containers.")

        page = discovery.discover_document_sources("reader", settings, page_size=1, source_offset=1)
        if page["documents"][0]["document"]["id"] != "group-document" or page["source_next"] != 2:
            raise AssertionError("Document pagination no longer crosses workspace boundaries.")
        for kind in containers:
            key = f"{kind}:{'' if kind == 'personal' else owners[kind]}"
            response = client.get("/api/v2/document-sources", query_string={"query": "policy", "workspace": key})
            page = response.get_json()
            if response.status_code != 200 or page["source_total"] != 1 or page["tags"] != ["policy"]:
                raise AssertionError("Scoped document/tag discovery failed.")
            if page["documents"][0]["document"]["id"] != f"{kind}-document":
                raise AssertionError("Workspace browsing read a different document container.")

        for readiness in (
            {"status": "running"}, {"schema": 0}, {"repairs": True}, {"completed": ["personal", "public"]},
        ):
            backfill(**readiness)
            source_reads.clear()
            response = client.get("/api/v2/document-sources")
            if response.status_code != 200 or response.get_json() != payload:
                raise AssertionError(f"DAI readiness fallback changed the discovery result: {readiness}")
            expected = ["group"] if readiness.get("completed") else list(containers)
            if source_reads != expected:
                raise AssertionError(f"Fallback did not respect per-kind readiness: {source_reads}, {readiness}")

        backfill()
        source_reads.clear()
        response = client.get("/api/v2/document-sources")
        if response.status_code != 200 or response.get_json() != payload or source_reads:
            raise AssertionError("Ready DAI was bypassed, or its result differs from source fallback.")
        if any("shared_user_ids" in item["document"] or "user_id" in item["document"] for item in payload["documents"]):
            raise AssertionError("Picker metadata expanded to expose source ownership or sharing fields.")
        for kind in containers:
            key = f"{kind}:{'' if kind == 'personal' else owners[kind]}"
            page = discovery.discover_document_sources("reader", settings, query="policy", workspace=key)
            if page["source_total"] != 1 or page["tags"] != ["policy"] or source_reads:
                raise AssertionError("DAI-backed browsing or tags fell back to source-list queries.")

        cache_settings = {**settings, "enable_document_access_index_cache": True, "enable_redis_cache": True}
        for redis in (FakeRedisClient(), FailingRedisClient()):
            index_reads.clear()
            with patch.object(indexing.app_settings_cache, "get_app_cache_redis_client", return_value=redis):
                first = discovery.discover_document_sources("reader", cache_settings)
                second = discovery.discover_document_sources("reader", cache_settings)
                if first != payload or second != payload or source_reads:
                    raise AssertionError("Discovery caching or Redis failure changed source results.")
                expected_reads = 6 if isinstance(redis, FailingRedisClient) else 3
                if len(index_reads) != expected_reads:
                    raise AssertionError("Redis hits/outages did not retain the shared DAI cache behavior.")
                if not isinstance(redis, FailingRedisClient):
                    invalidated = indexing.invalidate_document_access_index_cache_scope_keys(
                        ["user:reader"], reason="discovery regression", settings=cache_settings,
                    )
                    index_reads.clear()
                    refreshed = discovery.discover_document_sources("reader", cache_settings)
                    if not invalidated["success"] or refreshed != payload or index_reads != ["personal"]:
                        raise AssertionError("Discovery bypassed scoped DAI cache invalidation.")

        with patch.object(config.cosmos_document_access_index_container, "query_items", return_value=[]):
            page = discovery.discover_document_sources("reader", settings)
        if page["documents"] or page["source_total"] or source_reads:
            raise AssertionError("A successful empty index incorrectly triggered source fallback.")

        def partial_index_failure(**kwargs):
            parameters = {parameter["name"]: parameter["value"] for parameter in kwargs["parameters"]}
            if parameters.get("@source_scope") == "group":
                raise RuntimeError("PRIVATE_INDEX_DIAGNOSTIC")
            return index_query(**kwargs)

        with patch.object(config.cosmos_document_access_index_container, "query_items", side_effect=partial_index_failure):
            response = client.get("/api/v2/document-sources")
        if response.status_code != 200 or response.get_json() != payload or source_reads != ["group"]:
            raise AssertionError("A failed group index did not fall back independently.")

        containers["personal"].upsert_item(body={
            **records["personal"], "content_screening": {"state": "pending"},
            "abstract": "PRIVATE_HELD_CONTENT",
        })
        page = discovery.discover_document_sources("reader", settings)
        held = page["documents"][0]["document"]
        if held.get("content_screening", {}).get("available") is not False or "PRIVATE_HELD_CONTENT" in str(held):
            raise AssertionError("Indexed metadata bypassed live screening or leaked held content.")
        containers["personal"].upsert_item(body=records["personal"])

        containers["group"].upsert_item(body={
            **records["group"], "group_id": "outside", "shared_group_ids": ["group-1,not_approved"],
        })
        page = discovery.discover_document_sources("reader", settings, workspace="group:group-1")
        if page["documents"] or page["source_next"] is not None:
            raise AssertionError("Live share revocation was bypassed by an indexed owner row.")
        containers["group"].upsert_item(body=records["group"])

        containers["personal"].delete_item(item="personal-document", partition_key="personal-document")
        containers["group"].upsert_item(body={
            **records["group"], "id": "personal-document", "file_name": "WRONG_CONTAINER.pdf",
        })
        page = discovery.discover_document_sources("reader", settings, workspace="personal:")
        if page["documents"] or page["source_next"] is not None:
            raise AssertionError("A deleted personal candidate was refreshed from a different container.")
        containers["personal"].upsert_item(body=records["personal"])

        backfill(status="running")
        logs.reset_mock()
        with patch.object(config.cosmos_user_documents_container, "query_items",
                          side_effect=RuntimeError("PRIVATE_STORAGE_DIAGNOSTIC")):
            response = client.get("/api/v2/document-sources")
        if response.status_code != 503 or response.get_json() != {
            "error": "Could not load document sources. Please retry.",
        }:
            raise AssertionError("Storage failure was hidden or exposed private diagnostics.")
        logs.assert_called_once()
        if logs.call_args.kwargs.get("exceptionTraceback") is not True:
            raise AssertionError("Discovery failure did not request a server-side traceback.")
        if logs.call_args.kwargs["extra"] != {"error_type": "RuntimeError"}:
            raise AssertionError("Discovery failure lost its safe error-type dimension.")

    if environment.network_attempts:
        raise AssertionError("Discovery attempted external I/O.")
print("PASS: real configured document discovery and safe route failure")
'''


@pytest.mark.parametrize("optimized", [False, True])
@pytest.mark.parametrize("order", [
    ("config", "functions_document_source_discovery"),
    ("functions_document_source_discovery", "config"),
])
def test_real_config_discovery_and_route_failure(order, optimized):
    command = [sys.executable, "-B"] + (["-O"] if optimized else [])
    process = subprocess.run(
        command + ["-c", PROBE, str(APP), str(TESTS), *order],
        cwd=ROOT, capture_output=True, text=True, timeout=180, check=False,
    )
    assert process.returncode == 0, process.stdout[-6000:] + process.stderr[-6000:]
    assert "PASS: real configured document discovery and safe route failure" in process.stdout
