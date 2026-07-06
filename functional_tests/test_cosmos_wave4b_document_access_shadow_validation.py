# test_cosmos_wave4b_document_access_shadow_validation.py
#!/usr/bin/env python3
"""
Functional test for Cosmos Wave 4B document access shadow validation.
Version: 0.250.031
Implemented in: 0.250.012
Metrics added in: 0.250.013
Candidate read metrics added in: 0.250.014
Candidate read scope query corrected in: 0.250.015
Settings fail-open and source timestamp projection added in: 0.250.016
Lazy Cosmos diagnostics hook filtering added in: 0.250.017
Rolling aggregate metrics added in: 0.250.021
Read switch canary added in: 0.250.022
Default read enablement updated in: 0.250.027
Redis DAI cache metrics updated in: 0.250.029
Family-identity shadow validation updated in: 0.250.030

This test ensures document_access_index shadow validation compares source
document list results with projection rows, records parity and estimated
RU/latency diagnostics, and does not enable read-path switchover.
"""

import copy
import importlib
import os
import sys
import types
from contextlib import contextmanager
from datetime import datetime, timezone


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SINGLE_APP_DIR = os.path.join(ROOT_DIR, "application", "single_app")
if SINGLE_APP_DIR not in sys.path:
    sys.path.insert(0, SINGLE_APP_DIR)


class FakeCosmosError(Exception):
    def __init__(self, status_code, message):
        super().__init__(message)
        self.status_code = status_code


class FakePagedResponse:
    def by_page(self):
        return []


class FakeCosmosContainer:
    def __init__(self, fail_query=False, request_charge=1.0, simulate_lazy_response_hook=False):
        self.items = {}
        self.fail_query = fail_query
        self.request_charge = request_charge
        self.simulate_lazy_response_hook = simulate_lazy_response_hook
        self.etag_counter = 0

    def _body_with_next_etag(self, body):
        stored_body = copy.deepcopy(body)
        self.etag_counter += 1
        stored_body["_etag"] = str(self.etag_counter)
        return stored_body

    def _partition_key_for_body(self, body):
        return body.get("scope_key") or body.get("id")

    def upsert_item(self, body):
        partition_key = self._partition_key_for_body(body)
        stored_body = self._body_with_next_etag(body)
        self.items[(partition_key, body["id"])] = stored_body
        return copy.deepcopy(stored_body)

    def create_item(self, body):
        partition_key = self._partition_key_for_body(body)
        key = (partition_key, body["id"])
        if key in self.items:
            raise FakeCosmosError(409, f"Item already exists {body['id']}")
        stored_body = self._body_with_next_etag(body)
        self.items[key] = stored_body
        return copy.deepcopy(stored_body)

    def replace_item(self, item, body, etag=None, match_condition=None):
        partition_key = self._partition_key_for_body(body)
        key = (partition_key, item)
        if key not in self.items:
            raise FakeCosmosError(404, f"Missing item {item}")
        if etag and self.items[key].get("_etag") != etag:
            raise FakeCosmosError(412, f"ETag conflict for {item}")
        stored_body = self._body_with_next_etag(body)
        self.items[key] = stored_body
        return copy.deepcopy(stored_body)

    def read_item(self, item, partition_key):
        key = (partition_key, item)
        if key not in self.items:
            raise FakeCosmosError(404, f"Missing item {item}")
        return copy.deepcopy(self.items[key])

    def delete_item(self, item, partition_key, **kwargs):
        key = (partition_key, item)
        if key not in self.items:
            raise FakeCosmosError(404, f"Missing item {item}")
        del self.items[key]

    def query_items(self, query, parameters=None, partition_key=None, **kwargs):
        if self.fail_query:
            raise RuntimeError("projection query unavailable")

        response_hook = kwargs.get("response_hook")
        if response_hook:
            if self.simulate_lazy_response_hook:
                response_hook(
                    {
                        "x-ms-request-charge": "99.9",
                        "x-ms-activity-id": "stale-activity-id",
                        "x-ms-documentdb-query-metrics": "stale-query-metrics",
                    },
                    FakePagedResponse(),
                )
            response_hook(
                {
                    "x-ms-request-charge": str(self.request_charge),
                    "x-ms-activity-id": "fake-activity-id",
                    "x-ms-documentdb-query-metrics": "fake-query-metrics",
                },
                {},
            )

        parameter_map = {
            parameter["name"]: parameter["value"]
            for parameter in list(parameters or [])
        }
        item_type = parameter_map.get("@type")
        source_scope = parameter_map.get("@source_scope")
        scope_key = parameter_map.get("@scope_key") or partition_key
        document_id = parameter_map.get("@document_id")
        results = []

        for (item_partition_key, _item_id), item in self.items.items():
            if scope_key is not None and item_partition_key != scope_key:
                continue
            if item_type is not None and item.get("type") != item_type:
                continue
            if source_scope is not None and item.get("source_scope") != source_scope:
                continue
            if document_id is not None and item.get("source_document_id") != document_id:
                continue
            if (
                "AND c.access_granted = true" in query
                and "OR c.approval_status = @approval_not_approved" not in query
                and item.get("access_granted") is not True
            ):
                continue
            if (
                "OR c.approval_status = @approval_not_approved" in query
                and item.get("access_granted") is not True
                and item.get("approval_status") != parameter_map.get("@approval_not_approved")
            ):
                continue
            results.append(copy.deepcopy(item))

        if "SELECT VALUE COUNT" in query.upper():
            return [len(results)]
        return results


class ConflictOnceShadowStateContainer(FakeCosmosContainer):
    def __init__(self, conflict_sample):
        super().__init__()
        self.conflict_sample = conflict_sample
        self.inject_conflict_once = True

    def replace_item(self, item, body, etag=None, match_condition=None):
        if self.inject_conflict_once:
            self.inject_conflict_once = False
            current_body = self.read_item(item, item)
            current_body.setdefault("recent_metric_samples", []).append(copy.deepcopy(self.conflict_sample))
            self.upsert_item(current_body)
        return super().replace_item(item, body, etag=etag, match_condition=match_condition)


def _document(document_id, owner_id, **overrides):
    document = {
        "id": document_id,
        "type": "document_metadata",
        "user_id": owner_id,
        "file_name": f"{document_id}.pdf",
        "title": document_id.title(),
        "version": 1,
        "revision_family_id": document_id,
        "is_current_version": True,
        "search_visibility_state": "active",
        "status": "Processing complete",
        "percentage_complete": 100,
        "authors": [],
        "keywords": [],
        "abstract": "",
        "tags": [],
        "shared_user_ids": [],
    }
    document.update(overrides)
    return document


@contextmanager
def _load_document_access_index_module(index_container=None, settings_container=None, settings=None):
    original_modules = {}
    for module_name in [
        "config",
        "functions_appinsights",
        "functions_settings",
        "functions_document_access_index",
    ]:
        if module_name in sys.modules:
            original_modules[module_name] = sys.modules[module_name]
            del sys.modules[module_name]

    index_container = index_container or FakeCosmosContainer()
    settings_container = settings_container or FakeCosmosContainer()
    fake_config = types.ModuleType("config")
    fake_config.cosmos_document_access_index_container = index_container
    fake_config.cosmos_settings_container = settings_container
    fake_config.cosmos_user_documents_container = FakeCosmosContainer()
    fake_config.cosmos_user_documents_container_name = "documents"
    fake_config.cosmos_group_documents_container = FakeCosmosContainer()
    fake_config.cosmos_group_documents_container_name = "group_documents"
    fake_config.cosmos_public_documents_container = FakeCosmosContainer()
    fake_config.cosmos_public_documents_container_name = "public_documents"
    sys.modules["config"] = fake_config

    fake_appinsights = types.ModuleType("functions_appinsights")
    fake_appinsights.log_event = lambda *args, **kwargs: None
    sys.modules["functions_appinsights"] = fake_appinsights

    fake_settings = types.ModuleType("functions_settings")
    fake_settings.get_settings = lambda: settings or {
        "enable_document_access_index_container": True,
        "enable_document_access_index_write_through": True,
        "enable_document_access_index_reads": True,
        "enable_document_access_index_shadow_validation": True,
        "enable_startup_document_access_index_backfill": False,
    }
    sys.modules["functions_settings"] = fake_settings

    try:
        yield importlib.import_module("functions_document_access_index"), index_container, settings_container
    finally:
        for module_name in [
            "config",
            "functions_appinsights",
            "functions_settings",
            "functions_document_access_index",
        ]:
            sys.modules.pop(module_name, None)
        sys.modules.update(original_modules)


def test_shadow_validation_matches_projection_rows():
    """Shadow validation should pass when source and projection identities match."""
    document = _document("doc-1", "owner-1", title="Quarterly Report")

    with _load_document_access_index_module() as (indexing, _index_container, settings_container):
        indexing.sync_document_access_index_for_document(document, force=True)
        result = indexing.validate_document_access_index_shadow(
            [document],
            source_scope="personal",
            user_id="owner-1",
            filters={"search": "report"},
            context="test_personal_match",
        )

    assert result["success"] is True
    assert result["status"] == "matched"
    assert result["authoritative_count"] == 1
    assert result["projection_count"] == 1
    state_doc = settings_container.read_item(
        "document_access_index_shadow_validation_state",
        "document_access_index_shadow_validation_state",
    )
    assert state_doc["status"] == "matched"


def test_shadow_validation_reports_missing_and_extra_projection_rows():
    """Shadow validation should record missing and extra projection identities."""
    authoritative_document = _document("doc-source", "owner-1")
    projection_only_document = _document("doc-projection", "owner-1")

    with _load_document_access_index_module() as (indexing, _index_container, _settings_container):
        indexing.sync_document_access_index_for_document(projection_only_document, force=True)
        result = indexing.validate_document_access_index_shadow(
            [authoritative_document],
            source_scope="personal",
            user_id="owner-1",
            context="test_personal_mismatch",
        )

    assert result["success"] is False
    assert result["status"] == "mismatch"
    assert result["missing_count"] == 1
    assert result["extra_count"] == 1
    assert "doc-source" in result["missing_sample"]
    assert "doc-projection" in result["extra_sample"]


def test_shadow_validation_applies_projected_filter_fields():
    """Projected authors, keywords, abstracts, and tags should support filter parity."""
    matching_document = _document(
        "doc-match",
        "owner-1",
        authors=["Ada Lovelace"],
        keywords=["Cosmos"],
        abstract="Projection validation notes",
        tags=["planning", "wave4b"],
    )
    filtered_document = _document(
        "doc-filtered",
        "owner-1",
        authors=["Grace Hopper"],
        keywords=["Compiler"],
        abstract="Different content",
        tags=["other"],
    )

    with _load_document_access_index_module() as (indexing, _index_container, _settings_container):
        indexing.sync_document_access_index_for_document(matching_document, force=True)
        indexing.sync_document_access_index_for_document(filtered_document, force=True)
        result = indexing.validate_document_access_index_shadow(
            [matching_document],
            source_scope="personal",
            user_id="owner-1",
            filters={
                "author": "ada",
                "keywords": "cosmos",
                "abstract": "validation",
                "tags": ["planning", "wave4b"],
            },
            context="test_personal_filters",
        )

    assert result["success"] is True
    assert result["projection_count"] == 1


def test_shadow_validation_preserves_missing_group_classification_for_none_filter():
    """Group/public classification=none parity should preserve missing source values."""
    legacy_group_document = _document(
        "doc-legacy",
        "owner-1",
        group_id="group-1",
    )

    with _load_document_access_index_module() as (indexing, index_container, _settings_container):
        indexing.sync_document_access_index_for_document(legacy_group_document, force=True)
        projection_rows = list(index_container.items.values())
        assert projection_rows[0].get("document_classification") is None
        result = indexing.validate_document_access_index_shadow(
            [legacy_group_document],
            source_scope="group",
            group_ids=["group-1"],
            filters={
                "classification": "none",
                "classification_none_matches_literal": False,
            },
            context="test_group_classification_none",
        )

    assert result["success"] is True
    assert result["projection_count"] == 1


def test_shadow_validation_fails_open_on_projection_query_errors():
    """Projection query errors should be recorded and should not raise to callers."""
    document = _document("doc-1", "owner-1")

    with _load_document_access_index_module(index_container=FakeCosmosContainer(fail_query=True)) as (
        indexing,
        _index_container,
        settings_container,
    ):
        result = indexing.validate_document_access_index_shadow(
            [document],
            source_scope="personal",
            user_id="owner-1",
            context="test_query_error",
        )

    assert result["success"] is False
    assert result["status"] == "error"
    state_doc = settings_container.read_item(
        "document_access_index_shadow_validation_state",
        "document_access_index_shadow_validation_state",
    )
    assert state_doc["status"] == "error"


def test_shadow_validation_records_ru_and_latency_estimates():
    """Shadow validation should persist source/index RU and latency comparison fields."""
    document = _document("doc-1", "owner-1", _ts=12345)
    source_container = FakeCosmosContainer(request_charge=12.5, simulate_lazy_response_hook=True)
    index_container = FakeCosmosContainer(request_charge=2.25, simulate_lazy_response_hook=True)
    source_container.upsert_item(document)

    with _load_document_access_index_module(index_container=index_container) as (
        indexing,
        _index_container,
        settings_container,
    ):
        indexing.sync_document_access_index_for_document(document, force=True)
        projection_rows = list(index_container.items.values())
        assert any(row.get("source_ts") == 12345 for row in projection_rows)
        source_documents, source_query_metrics = indexing.query_items_with_cosmos_diagnostics(
            source_container,
            diagnostics_label="source_documents",
            query="SELECT * FROM c",
            parameters=[],
            enable_cross_partition_query=True,
        )
        result = indexing.validate_document_access_index_shadow(
            source_documents,
            source_scope="personal",
            user_id="owner-1",
            source_query_metrics=source_query_metrics,
            context="test_shadow_metrics",
        )

    assert result["success"] is True
    assert result["source_query_ru"] == 12.5
    assert result["projection_query_ru"] == 2.25
    assert result["validation_index_ru"] == 2.25
    assert result["candidate_read_ru"] == 2.25
    assert result["estimated_ru_savings"] == 10.25
    assert result["estimated_wave5_ru_savings"] == 10.25
    assert result["shadow_overhead_ru"] == 2.25
    assert result["source_query_ms"] is not None
    assert result["projection_query_ms"] is not None
    assert result["validation_index_ms"] is not None
    assert result["candidate_read_ms"] is not None
    assert result["estimated_ms_savings"] is not None
    assert result["estimated_wave5_ms_savings"] is not None
    assert result["source_query_page_count"] == 1
    assert result["candidate_read_page_count"] == 1
    state_doc = settings_container.read_item(
        "document_access_index_shadow_validation_state",
        "document_access_index_shadow_validation_state",
    )
    assert state_doc["estimated_ru_savings"] == 10.25
    assert state_doc["estimated_wave5_ru_savings"] == 10.25
    rolling_15m = state_doc["rolling_metrics"]["windows"]["15m"]
    assert rolling_15m["sample_count"] == 1
    assert rolling_15m["matched_count"] == 1
    assert rolling_15m["source_query_ru"] == 12.5
    assert rolling_15m["candidate_read_ru"] == 2.25
    assert rolling_15m["estimated_wave5_ru_savings"] == 10.25
    assert rolling_15m["validation_index_ru"] == 2.25


def test_shadow_validation_rolls_up_multiple_samples_for_admin_decisions():
    """Rolling metrics should aggregate multiple validations for workflow-level decisions."""
    document = _document("doc-1", "owner-1", _ts=12345)
    source_container = FakeCosmosContainer(request_charge=12.5)
    index_container = FakeCosmosContainer(request_charge=2.25)
    source_container.upsert_item(document)

    with _load_document_access_index_module(index_container=index_container) as (
        indexing,
        _index_container,
        settings_container,
    ):
        indexing.sync_document_access_index_for_document(document, force=True)
        source_documents, source_query_metrics = indexing.query_items_with_cosmos_diagnostics(
            source_container,
            diagnostics_label="source_documents",
            query="SELECT * FROM c",
            parameters=[],
            enable_cross_partition_query=True,
        )
        indexing.validate_document_access_index_shadow(
            source_documents,
            source_scope="personal",
            user_id="owner-1",
            source_query_metrics=source_query_metrics,
            context="test_shadow_metrics_first",
        )

        source_container.request_charge = 7.5
        index_container.request_charge = 1.5
        source_documents, source_query_metrics = indexing.query_items_with_cosmos_diagnostics(
            source_container,
            diagnostics_label="source_documents",
            query="SELECT * FROM c",
            parameters=[],
            enable_cross_partition_query=True,
        )
        indexing.validate_document_access_index_shadow(
            source_documents,
            source_scope="personal",
            user_id="owner-1",
            source_query_metrics=source_query_metrics,
            context="test_shadow_metrics_second",
        )
        partial_candidate_fields = indexing._build_shadow_metric_fields(
            {"request_charge": 5.0, "elapsed_ms": 2.0, "item_count": 1, "page_count": 1},
            {"request_charge": 1.0, "elapsed_ms": 1.0, "item_count": 1, "page_count": 1},
            {
                "request_charge": 0.5,
                "elapsed_ms": 1.0,
                "item_count": 1,
                "page_count": 1,
                "partial_failure": True,
            },
        )
        assert partial_candidate_fields["candidate_read_ru"] is None
        assert partial_candidate_fields["estimated_wave5_ru_savings"] is None
        indexing._write_shadow_validation_state({
            "success": False,
            "status": "error",
            "context": "test_partial_candidate_metrics",
            "source_scope": "personal",
            "scope_keys": ["user:owner-1"],
            "authoritative_count": 1,
            "projection_count": 1,
            "missing_count": 0,
            "extra_count": 0,
            "checked_at": indexing._utc_now_iso(),
            "source_query_ru": 5.0,
            "validation_index_ru": 1.0,
            "candidate_read_ru": None,
            "estimated_wave5_ru_savings": None,
            "source_query_item_count": 1,
            "candidate_read_item_count": 0,
            "source_query_page_count": 1,
            "candidate_read_page_count": 0,
        })

    state_doc = settings_container.read_item(
        "document_access_index_shadow_validation_state",
        "document_access_index_shadow_validation_state",
    )
    assert len(state_doc["recent_metric_samples"]) == 3
    rolling_5m = state_doc["rolling_metrics"]["windows"]["5m"]
    rolling_15m = state_doc["rolling_metrics"]["windows"]["15m"]
    for rolling_window in [rolling_5m, rolling_15m]:
        assert rolling_window["sample_count"] == 3
        assert rolling_window["comparable_sample_count"] == 2
        assert rolling_window["matched_count"] == 2
        assert rolling_window["error_count"] == 1
        assert rolling_window["source_query_ru"] == 20.0
        assert rolling_window["candidate_read_ru"] == 3.75
        assert rolling_window["validation_index_ru"] == 4.75
        assert rolling_window["estimated_wave5_ru_savings"] == 16.25
        assert rolling_window["source_query_item_count"] == 2
        assert rolling_window["candidate_read_item_count"] == 2


def test_shadow_validation_retries_state_write_conflicts_without_losing_samples():
    """Concurrent shadow state updates should be retried without dropping metric samples."""
    conflict_sample = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "status": "matched",
        "context": "concurrent_shadow_sample",
        "source_scope": "personal",
        "scope_key_count": 1,
        "authoritative_count": 1,
        "projection_count": 1,
        "missing_count": 0,
        "extra_count": 0,
        "source_query_ru": 3.0,
        "validation_index_ru": 1.0,
        "candidate_read_ru": 1.0,
        "estimated_wave5_ru_savings": 2.0,
        "shadow_overhead_ru": 1.0,
        "source_query_item_count": 1,
        "candidate_read_item_count": 1,
        "source_query_page_count": 1,
        "candidate_read_page_count": 1,
    }
    settings_container = ConflictOnceShadowStateContainer(conflict_sample)

    with _load_document_access_index_module(settings_container=settings_container) as (
        indexing,
        _index_container,
        _settings_container,
    ):
        indexing._write_shadow_validation_state({
            "success": True,
            "status": "matched",
            "context": "first_shadow_sample",
            "source_scope": "personal",
            "scope_keys": ["user:owner-1"],
            "authoritative_count": 1,
            "projection_count": 1,
            "missing_count": 0,
            "extra_count": 0,
            "checked_at": indexing._utc_now_iso(),
            "source_query_ru": 2.0,
            "validation_index_ru": 0.5,
            "candidate_read_ru": 0.5,
            "estimated_wave5_ru_savings": 1.5,
            "shadow_overhead_ru": 0.5,
            "source_query_item_count": 1,
            "candidate_read_item_count": 1,
            "source_query_page_count": 1,
            "candidate_read_page_count": 1,
        })
        indexing._write_shadow_validation_state({
            "success": True,
            "status": "matched",
            "context": "second_shadow_sample",
            "source_scope": "personal",
            "scope_keys": ["user:owner-1"],
            "authoritative_count": 1,
            "projection_count": 1,
            "missing_count": 0,
            "extra_count": 0,
            "checked_at": indexing._utc_now_iso(),
            "source_query_ru": 4.0,
            "validation_index_ru": 1.5,
            "candidate_read_ru": 1.5,
            "estimated_wave5_ru_savings": 2.5,
            "shadow_overhead_ru": 1.5,
            "source_query_item_count": 1,
            "candidate_read_item_count": 1,
            "source_query_page_count": 1,
            "candidate_read_page_count": 1,
        })

    state_doc = settings_container.read_item(
        "document_access_index_shadow_validation_state",
        "document_access_index_shadow_validation_state",
    )
    contexts = {sample["context"] for sample in state_doc["recent_metric_samples"]}
    assert contexts == {
        "first_shadow_sample",
        "concurrent_shadow_sample",
        "second_shadow_sample",
    }
    rolling_15m = state_doc["rolling_metrics"]["windows"]["15m"]
    assert rolling_15m["sample_count"] == 3
    assert rolling_15m["comparable_sample_count"] == 3
    assert rolling_15m["source_query_ru"] == 9.0
    assert rolling_15m["candidate_read_ru"] == 3.0
    assert rolling_15m["estimated_wave5_ru_savings"] == 6.0


def test_shadow_validation_skips_when_settings_are_unavailable():
    """Settings failures should disable optional shadow validation instead of failing source reads."""
    document = _document("doc-1", "owner-1")

    with _load_document_access_index_module() as (indexing, _index_container, _settings_container):
        def raise_settings_error():
            raise RuntimeError("settings unavailable")

        indexing.get_settings = raise_settings_error
        result = indexing.validate_document_access_index_shadow(
            [document],
            source_scope="personal",
            user_id="owner-1",
            context="test_settings_unavailable",
        )

    assert result["success"] is True
    assert result["status"] == "skipped_disabled"


def test_wave4b_admin_routes_and_version_are_wired():
    """Contract test for Wave 4B UI setting, route hooks, and version."""
    config_source = open(os.path.join(SINGLE_APP_DIR, "config.py"), "r", encoding="utf-8").read()
    route_settings_source = open(
        os.path.join(SINGLE_APP_DIR, "route_frontend_admin_settings.py"),
        "r",
        encoding="utf-8",
    ).read()
    admin_template = open(
        os.path.join(SINGLE_APP_DIR, "templates", "admin_settings.html"),
        "r",
        encoding="utf-8",
    ).read()
    personal_route = open(os.path.join(SINGLE_APP_DIR, "route_backend_documents.py"), "r", encoding="utf-8").read()
    group_route = open(os.path.join(SINGLE_APP_DIR, "route_backend_group_documents.py"), "r", encoding="utf-8").read()
    public_route = open(os.path.join(SINGLE_APP_DIR, "route_external_public_documents.py"), "r", encoding="utf-8").read()
    functions_documents = open(os.path.join(SINGLE_APP_DIR, "functions_documents.py"), "r", encoding="utf-8").read()

    assert 'VERSION = "0.250.031"' in config_source
    assert "'enable_dai_debug': dai_debug_enabled" in route_settings_source
    assert "'enable_document_access_index_shadow_validation': document_access_index_shadow_validation_enabled" in route_settings_source
    assert "if enable_dai_debug" in admin_template
    assert 'name="enable_document_access_index_shadow_validation"' in admin_template
    assert 'name="enable_document_access_index_reads"' in admin_template
    assert "Wave 5B default" in admin_template
    assert "Wave 6" in admin_template
    assert "enable_document_access_index_shadow_validation_preview" not in admin_template
    assert "validate_document_access_index_shadow(" in personal_route
    assert "validate_document_access_index_shadow(" in group_route
    assert "validate_document_access_index_shadow(" in public_route
    assert "if collect_shadow_metrics:" in functions_documents
    assert "source_query_metrics = None" in functions_documents
    assert "def _upsert_document_and_sync_access_index" in functions_documents
    assert "persisted_document if isinstance(persisted_document, dict) else document_item" in functions_documents
    normalize_source = functions_documents[
        functions_documents.index("def normalize_document_revision_families"):
        functions_documents.index("def _get_document_family_items_from_document")
    ]
    assert "operation='document_revision_normalized'" in normalize_source
    assert "cosmos_container.upsert_item(document_item)" not in normalize_source
    assert "cosmos_container.upsert_item(document_metadata)\n        sync_document_access_index_for_document_fail_open" not in functions_documents
    assert "document_for_sync = persisted_document if isinstance(persisted_document, dict) else document_item" in personal_route
    index_source = open(os.path.join(SINGLE_APP_DIR, "functions_document_access_index.py"), "r", encoding="utf-8").read()
    candidate_query_source = index_source[
        index_source.index("def _query_candidate_projection_rows_for_scope"):
        index_source.index("def _collect_candidate_read_metrics")
    ]
    assert "ORDER BY" not in candidate_query_source
    assert "OFFSET" not in candidate_query_source
    assert "LIMIT" not in candidate_query_source
    assert "TOP" not in candidate_query_source
    assert "c.source_ts" in candidate_query_source
    assert "partition_key=scope_key" in candidate_query_source
    assert "DOCUMENT_ACCESS_SHADOW_METRIC_WINDOWS_MINUTES = (5, 15)" in index_source
    assert "shadow_validation['rolling_metrics'] = _empty_shadow_rolling_metrics()" in index_source
    assert "state_body = _merge_shadow_rolling_metrics(state_body, previous_state=previous_state)" in index_source
    assert "MatchConditions.IfNotModified" in index_source


if __name__ == "__main__":
    tests = [
        test_shadow_validation_matches_projection_rows,
        test_shadow_validation_reports_missing_and_extra_projection_rows,
        test_shadow_validation_applies_projected_filter_fields,
        test_shadow_validation_preserves_missing_group_classification_for_none_filter,
        test_shadow_validation_fails_open_on_projection_query_errors,
        test_shadow_validation_records_ru_and_latency_estimates,
        test_shadow_validation_rolls_up_multiple_samples_for_admin_decisions,
        test_shadow_validation_retries_state_write_conflicts_without_losing_samples,
        test_shadow_validation_skips_when_settings_are_unavailable,
        test_wave4b_admin_routes_and_version_are_wired,
    ]
    results = []
    for test in tests:
        print(f"Running {test.__name__}...")
        try:
            test()
            print("Test passed.")
            results.append(True)
        except Exception as exc:
            print(f"Test failed: {exc}")
            results.append(False)

    sys.exit(0 if all(results) else 1)
