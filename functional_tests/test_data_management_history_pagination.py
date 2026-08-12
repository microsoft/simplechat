# test_data_management_history_pagination.py
#!/usr/bin/env python3
"""
Functional test for Data Management history pagination.
Version: 0.250.159
Implemented in: 0.250.103
Updated in: 0.250.104
Updated in: 0.250.105
Updated in: 0.250.106
Updated in: 0.250.159

This test ensures job history and backup inventory use deterministic, filtered,
sanitized Cosmos pages with opaque continuation state and global summaries.
"""

import copy
import importlib.util
from pathlib import Path
import sys
import types

import pytest
import werkzeug


if not hasattr(werkzeug, "__version__"):
    werkzeug.__version__ = "3"


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
MODULE_PATH = APP_ROOT / "functions_data_management.py"
ROUTE_MODULE_PATH = APP_ROOT / "route_backend_data_management.py"
sys.path.insert(0, str(APP_ROOT))


class FakeHistoryContainer:
    """Evaluate the bounded subset of SQL emitted by history helpers."""

    def __init__(self, documents):
        self.documents = copy.deepcopy(documents)
        self.queries = []

    def query_items(
        self,
        query,
        parameters=None,
        max_item_count=None,
        **_kwargs,
    ):
        parameter_map = {
            parameter["name"]: parameter["value"]
            for parameter in (parameters or [])
        }
        self.queries.append({
            "query": query,
            "parameters": copy.deepcopy(parameter_map),
            "max_item_count": max_item_count,
        })
        matching = [
            item
            for item in self.documents
            if self._matches(item, query, parameter_map)
        ]
        if "GROUP BY c.backup_type, c.status" in query:
            grouped = {}
            for item in matching:
                key = (item.get("backup_type"), item.get("status"))
                grouped[key] = grouped.get(key, 0) + 1
            return [
                {
                    "backup_type": backup_type,
                    "status": status,
                    "count": count,
                }
                for (backup_type, status), count in grouped.items()
            ]

        matching.sort(
            key=lambda item: (item.get("created_at", ""), item.get("id", "")),
            reverse=True,
        )
        if "SELECT TOP 1" in query:
            return copy.deepcopy(matching[:1])
        page_limit = int(parameter_map.get("@page_limit", max_item_count or 25))
        return copy.deepcopy(matching[:page_limit])

    @staticmethod
    def _matches(item, query, parameters):
        if item.get("type") != parameters.get("@type"):
            return False
        operation = parameters.get("@backup_operation", parameters.get("@operation"))
        if operation is not None and item.get("operation") != operation:
            return False
        if "@backup_type" in parameters and item.get("backup_type") != parameters["@backup_type"]:
            return False
        if "@status" in parameters and item.get("status") != parameters["@status"]:
            return False
        if (
            "@completed" in parameters
            and "@completed_with_warnings" in parameters
            and item.get("status") not in {
                parameters["@completed"],
                parameters["@completed_with_warnings"],
            }
        ):
            return False
        if "@scheduled" in parameters and item.get("scheduled") is not parameters["@scheduled"]:
            return False
        if "@created_from" in parameters and item.get("created_at", "") < parameters["@created_from"]:
            return False
        if "@created_to" in parameters and item.get("created_at", "") >= parameters["@created_to"]:
            return False
        if "@cursor_created_at" in parameters:
            created_at = item.get("created_at", "")
            cursor_created_at = parameters["@cursor_created_at"]
            cursor_id = parameters["@cursor_id"]
            if not (
                created_at < cursor_created_at
                or (created_at == cursor_created_at and item.get("id", "") < cursor_id)
            ):
                return False
        return True


class FailingHistoryContainer:
    """Raise a configured provider error for history query attempts."""

    def __init__(self):
        self.error = None
        self.queries = []

    def query_items(
        self,
        query,
        parameters=None,
        max_item_count=None,
        **_kwargs,
    ):
        parameter_map = {
            parameter["name"]: parameter["value"]
            for parameter in (parameters or [])
        }
        self.queries.append({
            "query": query,
            "parameters": copy.deepcopy(parameter_map),
            "max_item_count": max_item_count,
        })
        raise self.error or RuntimeError("Configured history query failure.")


def build_job(
    job_id,
    created_at,
    operation="backup",
    backup_type="full",
    status="completed",
    scheduled=False,
):
    """Build a minimal durable job fixture."""
    return {
        "id": job_id,
        "type": "data_management_job",
        "operation": operation,
        "backup_type": backup_type if operation == "backup" else None,
        "status": status,
        "created_at": created_at,
        "updated_at": created_at,
        "completed_at": created_at if status.startswith("completed") else None,
        "scheduled": scheduled,
        "last_message": "Finished safely",
        "options": {"target_cosmos_key": "must-not-render"},
        "progress": {"percent_complete": 100},
        "warnings": [],
        "result": {
            "base_prefix": f"backups/{job_id}",
            "manifest_path": f"backups/{job_id}/manifest.json",
            "artifacts": [],
        },
    }


def load_data_management_module(monkeypatch, container):
    """Load production helpers with an in-memory Data Management job container."""
    config_module = types.ModuleType("config")
    config_module.CLIENTS = {}
    config_module.VERSION = "0.250.159"
    config_module.SECRET_KEY = "history-pagination-functional-test-secret"
    config_module.cosmos_data_management_jobs_container = container
    config_module.cosmos_data_management_job_items_container = container
    config_module.cosmos_settings_container = container
    config_module.cosmos_data_management_backup_item_states_container = container
    monkeypatch.setitem(sys.modules, "config", config_module)

    appinsights_module = types.ModuleType("functions_appinsights")
    appinsights_module.log_event = lambda *_args, **_kwargs: None
    monkeypatch.setitem(sys.modules, "functions_appinsights", appinsights_module)

    throughput_module = types.ModuleType("functions_cosmos_throughput")

    class FakeCosmosThroughputError(Exception):
        pass

    throughput_module.CosmosThroughputError = FakeCosmosThroughputError
    throughput_module.get_container_throughput = lambda *_args, **_kwargs: {}
    throughput_module.get_database_throughput = lambda *_args, **_kwargs: {}
    throughput_module.set_database_throughput = lambda *_args, **_kwargs: {}
    monkeypatch.setitem(sys.modules, "functions_cosmos_throughput", throughput_module)

    module_name = "data_management_history_pagination_test_module"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec and spec.loader
    spec.loader.exec_module(module)
    monkeypatch.delitem(sys.modules, module_name, raising=False)
    return module


def load_route_module(
    monkeypatch,
    jobs_page=None,
    backup_page=None,
    history_error=None,
    history_unavailable=False,
):
    """Load the admin routes with identity auth decorators and captured helpers."""
    data_management_module = types.ModuleType("functions_data_management")

    class FakeSettingsValidationError(ValueError):
        pass

    class FakeCosmosEditorError(ValueError):
        pass

    class FakeHistoryPaginationError(ValueError):
        pass

    class FakeHistoryUnavailableError(RuntimeError):
        def __init__(
            self,
            safe_message=(
                "Data Management history requires an updated Cosmos DB index. Run App "
                "Maintenance with Apply Cosmos indexing policies enabled, wait for indexing "
                "to finish, then refresh this page."
            ),
            reason="missing_history_index",
            status_code=503,
            maintenance_required=True,
        ):
            super().__init__(safe_message)
            self.safe_message = safe_message
            self.reason = reason
            self.status_code = status_code
            self.maintenance_required = maintenance_required

    data_management_module.DataManagementSettingsValidationError = FakeSettingsValidationError
    data_management_module.DataManagementCosmosEditorError = FakeCosmosEditorError
    data_management_module.DataManagementHistoryPaginationError = FakeHistoryPaginationError
    data_management_module.DataManagementHistoryUnavailableError = FakeHistoryUnavailableError
    data_management_module.DATA_MANAGEMENT_OPERATION_BACKUP = "backup"
    data_management_module.DATA_MANAGEMENT_OPERATION_DRY_RUN = "dry_run"
    data_management_module.DATA_MANAGEMENT_OPERATION_MIGRATION = "migration"
    data_management_module.DATA_MANAGEMENT_OPERATION_RESTORE = "restore"

    imported_function_names = [
        "cleanup_expired_data_management_backups",
        "create_data_management_migration_review_authorization",
        "create_data_management_restore_review_authorization",
        "delete_data_management_backup",
        "export_data_management_migration_manifest",
        "generate_data_management_encryption_key",
        "get_data_management_cosmos_editor_containers",
        "get_data_management_cosmos_editor_document",
        "get_data_management_job_detail",
        "get_data_management_job_progress",
        "get_data_management_migration_catalog",
        "get_data_management_migration_review_fingerprint",
        "get_data_management_restore_review_fingerprint",
        "get_data_management_settings",
        "log_data_management_cosmos_editor_activity",
        "preview_data_management_migration_plan",
        "queue_data_management_job",
        "query_data_management_cosmos_editor_documents",
        "request_data_management_job_cancellation",
        "release_data_management_migration_review_reservation",
        "release_data_management_restore_review_reservation",
        "reserve_data_management_migration_review_authorization",
        "reserve_data_management_restore_review_authorization",
        "review_data_management_migration",
        "review_data_management_restore",
        "retry_data_management_backup_job",
        "resolve_data_management_migration_manifest_item",
        "retry_data_management_migration_job",
        "retry_data_management_restore_job",
        "sanitize_data_management_job_for_admin",
        "sanitize_data_management_settings_for_admin",
        "save_data_management_cosmos_editor_document",
        "summarize_data_management_migration_plan",
        "submit_data_management_job",
        "test_backup_storage_connection",
        "test_target_cosmos_capacity_management",
        "test_target_cosmos_connection",
        "test_target_enhanced_citation_storage_connection",
        "test_target_search_connection",
        "update_data_management_settings",
    ]
    for function_name in imported_function_names:
        setattr(data_management_module, function_name, lambda *_args, **_kwargs: {})

    captures = {"jobs": [], "backups": []}

    def get_jobs_page(**kwargs):
        captures["jobs"].append(copy.deepcopy(kwargs))
        if history_unavailable:
            raise FakeHistoryUnavailableError()
        if history_error:
            raise FakeHistoryPaginationError(history_error)
        return copy.deepcopy(jobs_page or {
            "items": [],
            "pagination": {
                "page_size": 25,
                "returned_count": 0,
                "has_more": False,
                "next_token": None,
            },
            "filters": {},
        })

    def get_backup_summary(**kwargs):
        captures["backups"].append(copy.deepcopy(kwargs))
        if history_unavailable:
            raise FakeHistoryUnavailableError()
        if history_error:
            raise FakeHistoryPaginationError(history_error)
        return copy.deepcopy(backup_page or {
            "backups": [],
            "summary": {},
            "pagination": {
                "page_size": 25,
                "returned_count": 0,
                "has_more": False,
                "next_token": None,
            },
            "filters": {},
        })

    data_management_module.get_data_management_jobs_page = get_jobs_page
    data_management_module.get_data_management_backup_summary = get_backup_summary
    monkeypatch.setitem(sys.modules, "functions_data_management", data_management_module)

    authentication_module = types.ModuleType("functions_authentication")
    authentication_module.admin_required = lambda function: function
    authentication_module.login_required = lambda function: function
    authentication_module.get_current_user_id = lambda: "admin-id"
    monkeypatch.setitem(sys.modules, "functions_authentication", authentication_module)

    swagger_module = types.ModuleType("swagger_wrapper")
    swagger_module.get_auth_security = lambda: []
    swagger_module.swagger_route = lambda **_kwargs: lambda function: function
    monkeypatch.setitem(sys.modules, "swagger_wrapper", swagger_module)

    activity_module = types.ModuleType("functions_activity_logging")
    activity_module.log_general_admin_action = lambda *_args, **_kwargs: None
    monkeypatch.setitem(sys.modules, "functions_activity_logging", activity_module)

    appinsights_module = types.ModuleType("functions_appinsights")
    appinsights_module.log_event = lambda *_args, **_kwargs: None
    monkeypatch.setitem(sys.modules, "functions_appinsights", appinsights_module)

    module_name = "data_management_history_pagination_route_test_module"
    spec = importlib.util.spec_from_file_location(module_name, ROUTE_MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec and spec.loader
    spec.loader.exec_module(module)
    monkeypatch.delitem(sys.modules, module_name, raising=False)
    return module, captures


def test_job_history_pages_are_stable_and_filter_bound(monkeypatch):
    """Traverse ties without duplicates and reject continuation reuse across filters."""
    jobs = [
        build_job("job-z", "2026-07-30T12:00:00+00:00"),
        build_job("job-y", "2026-07-30T12:00:00+00:00"),
        build_job("job-x", "2026-07-30T11:00:00+00:00", status="failed"),
        build_job("job-w", "2026-07-29T10:00:00+00:00", operation="migration"),
    ]
    container = FakeHistoryContainer(jobs)
    module = load_data_management_module(monkeypatch, container)

    first = module.get_data_management_jobs_page(page_size=2)
    second = module.get_data_management_jobs_page(
        page_size=2,
        continuation_token=first["pagination"]["next_token"],
    )

    assert [job["id"] for job in first["items"]] == ["job-z", "job-y"]
    assert [job["id"] for job in second["items"]] == ["job-x", "job-w"]
    assert first["pagination"]["has_more"] is True
    assert second["pagination"]["has_more"] is False
    assert "SELECT TOP @page_limit" in container.queries[0]["query"]
    assert "ORDER BY c.created_at DESC, c.id DESC" in container.queries[0]["query"]
    assert container.queries[1]["parameters"]["@cursor_created_at"] == "2026-07-30T12:00:00+00:00"
    assert container.queries[1]["parameters"]["@cursor_id"] == "job-y"
    assert all("options" not in job for job in first["items"] + second["items"])

    with pytest.raises(module.DataManagementHistoryPaginationError, match="active filters"):
        module.get_data_management_jobs_page(
            page_size=2,
            continuation_token=first["pagination"]["next_token"],
            filters={"status": "failed"},
        )
    with pytest.raises(module.DataManagementHistoryPaginationError, match="invalid or expired"):
        module.get_data_management_jobs_page(
            page_size=2,
            continuation_token=f"{first['pagination']['next_token']}tampered",
        )


def test_job_history_filters_and_date_bounds_execute_server_side(monkeypatch):
    """Apply operation, status, schedule, and bounded date filters in Cosmos."""
    jobs = [
        build_job("matching", "2026-07-30T12:00:00+00:00", status="failed"),
        build_job("scheduled", "2026-07-30T11:00:00+00:00", status="failed", scheduled=True),
        build_job("wrong-operation", "2026-07-30T10:00:00+00:00", operation="migration", status="failed"),
        build_job("outside-range", "2025-01-01T10:00:00+00:00", status="failed"),
    ]
    container = FakeHistoryContainer(jobs)
    module = load_data_management_module(monkeypatch, container)

    page = module.get_data_management_jobs_page(
        page_size=500,
        filters={
            "operation": "backup",
            "status": "failed",
            "scheduled": "manual",
            "created_from": "2026-07-01",
            "created_to": "2026-07-30",
        },
    )

    assert [job["id"] for job in page["items"]] == ["matching"]
    assert page["pagination"]["page_size"] == 100
    parameters = container.queries[0]["parameters"]
    assert parameters["@operation"] == "backup"
    assert parameters["@status"] == "failed"
    assert parameters["@scheduled"] is False
    assert parameters["@created_from"] == "2026-07-01T00:00:00+00:00"
    assert parameters["@created_to"] == "2026-07-31T00:00:00+00:00"

    with pytest.raises(module.DataManagementHistoryPaginationError, match="provided together"):
        module.get_data_management_jobs_page(filters={"created_from": "2026-07-01"})
    with pytest.raises(module.DataManagementHistoryPaginationError, match="cannot exceed"):
        module.get_data_management_jobs_page(
            filters={"created_from": "2024-01-01", "created_to": "2026-01-01"}
        )


def test_backup_summary_is_global_and_page_independent(monkeypatch):
    """Keep global counts/latest references stable on a filtered one-row page."""
    jobs = [
        build_job("full-new", "2026-07-30T12:00:00+00:00"),
        build_job(
            "partial-new",
            "2026-07-30T11:00:00+00:00",
            backup_type="partial",
            status="completed_with_warnings",
            scheduled=True,
        ),
        build_job("full-failed", "2026-07-30T10:00:00+00:00", status="failed"),
        build_job("partial-running", "2026-07-30T09:00:00+00:00", backup_type="partial", status="running"),
        build_job("migration", "2026-07-30T08:00:00+00:00", operation="migration"),
    ]
    container = FakeHistoryContainer(jobs)
    module = load_data_management_module(monkeypatch, container)

    result = module.get_data_management_backup_summary(
        limit=1,
        filters={
            "backup_type": "partial",
            "status": "available",
            "scheduled": "scheduled",
        },
    )

    assert [backup["id"] for backup in result["backups"]] == ["partial-new"]
    assert result["pagination"]["returned_count"] == 1
    assert result["summary"]["total"] == 4
    assert result["summary"]["available"] == 2
    assert result["summary"]["full"] == 1
    assert result["summary"]["partial"] == 1
    assert result["summary"]["failed"] == 1
    assert result["summary"]["running"] == 1
    assert result["summary"]["latest_full"]["id"] == "full-new"
    assert result["summary"]["latest_partial"]["id"] == "partial-new"


def test_history_provider_index_errors_are_actionable(monkeypatch):
    """Convert missing Cosmos composite-index failures into admin-safe guidance."""
    container = FailingHistoryContainer()
    module = load_data_management_module(monkeypatch, container)

    class FakeCosmosHttpResponseError(Exception):
        def __init__(self, message, status_code=400):
            super().__init__(message)
            self.status_code = status_code

    module.CosmosHttpResponseError = FakeCosmosHttpResponseError
    container.error = FakeCosmosHttpResponseError(
        "The order by query does not have a corresponding composite index that it can be served from."
    )

    with pytest.raises(module.DataManagementHistoryUnavailableError) as exc_info:
        module.get_data_management_jobs_page(page_size=25)

    error = exc_info.value
    assert error.reason == "missing_history_index"
    assert error.status_code == 503
    assert error.maintenance_required is True
    assert "Apply Cosmos indexing policies" in error.safe_message
    assert "corresponding composite index" not in error.safe_message
    assert "ORDER BY c.created_at DESC, c.id DESC" in container.queries[0]["query"]


def test_expired_and_final_empty_continuations_fail_or_finish_safely(monkeypatch):
    """Reject expired state and return a safe empty final page."""
    jobs = [
        build_job("job-b", "2026-07-30T12:00:00+00:00"),
        build_job("job-a", "2026-07-30T11:00:00+00:00"),
    ]
    module = load_data_management_module(monkeypatch, FakeHistoryContainer(jobs))
    first = module.get_data_management_jobs_page(page_size=1)
    module.DATA_MANAGEMENT_HISTORY_TOKEN_TTL_SECONDS = -1
    with pytest.raises(module.DataManagementHistoryPaginationError, match="invalid or expired"):
        module.get_data_management_jobs_page(
            page_size=1,
            continuation_token=first["pagination"]["next_token"],
        )

    module.DATA_MANAGEMENT_HISTORY_TOKEN_TTL_SECONDS = 3600
    filters = module.normalize_data_management_history_filters("jobs")
    final_token = module._encode_data_management_history_token(
        "jobs",
        filters,
        1,
        {
            "created_at": "2026-07-30T11:00:00+00:00",
            "id": "job-a",
        },
    )
    final_page = module.get_data_management_jobs_page(
        page_size=1,
        continuation_token=final_token,
    )
    assert final_page["items"] == []
    assert final_page["pagination"]["has_more"] is False
    assert final_page["pagination"]["next_token"] is None


def test_admin_history_routes_forward_filters_and_page_metadata(monkeypatch):
    """Validate the Flask contracts pass normalized inputs to paged helpers."""
    from flask import Blueprint, Flask

    jobs_page = {
        "items": [{"id": "job-1"}],
        "pagination": {
            "page_size": 50,
            "returned_count": 1,
            "has_more": True,
            "next_token": "opaque-next",
        },
        "filters": {"operation": "migration", "status": "failed"},
    }
    backup_page = {
        "backups": [{"id": "backup-1"}],
        "summary": {"available": 9},
        "pagination": {
            "page_size": 10,
            "returned_count": 1,
            "has_more": False,
            "next_token": None,
        },
        "filters": {"backup_type": "full", "status": "available"},
    }
    route_module, captures = load_route_module(
        monkeypatch,
        jobs_page=jobs_page,
        backup_page=backup_page,
    )
    app = Flask(__name__)
    app.secret_key = "route-test"
    blueprint = Blueprint("data_management_route_test", __name__)
    route_module.register_route_backend_data_management(blueprint)
    app.register_blueprint(blueprint)
    client = app.test_client()

    jobs_response = client.get(
        "/api/admin/data-management/jobs"
        "?page_size=50&continuation_token=opaque-current"
        "&operation=migration&status=failed&scheduled=manual"
        "&created_from=2026-07-01&created_to=2026-07-30"
    )
    backups_response = client.get(
        "/api/admin/data-management/backups"
        "?page_size=10&backup_type=full&status=available&scheduled=all"
    )

    assert jobs_response.status_code == 200
    assert jobs_response.get_json()["pagination"]["next_token"] == "opaque-next"
    assert captures["jobs"] == [{
        "page_size": "50",
        "continuation_token": "opaque-current",
        "filters": {
            "operation": "migration",
            "status": "failed",
            "scheduled": "manual",
            "created_from": "2026-07-01",
            "created_to": "2026-07-30",
        },
    }]
    assert backups_response.status_code == 200
    assert backups_response.get_json()["summary"]["available"] == 9
    assert captures["backups"][0]["filters"]["backup_type"] == "full"
    assert captures["backups"][0]["filters"]["status"] == "available"


def test_admin_history_routes_fail_safely_for_invalid_tokens(monkeypatch):
    """Return a bounded validation response without provider internals."""
    from flask import Blueprint, Flask

    route_module, _captures = load_route_module(
        monkeypatch,
        history_error="Continuation token is invalid or expired.",
    )
    app = Flask(__name__)
    app.secret_key = "route-test"
    blueprint = Blueprint("data_management_invalid_route_test", __name__)
    route_module.register_route_backend_data_management(blueprint)
    app.register_blueprint(blueprint)
    response = app.test_client().get(
        "/api/admin/data-management/jobs?continuation_token=invalid"
    )

    assert response.status_code == 400
    assert response.get_json() == {
        "success": False,
        "error": "Data Management history filters or continuation token are invalid.",
    }
    assert "SELECT" not in response.get_data(as_text=True)
    assert "Continuation token is invalid or expired." not in response.get_data(as_text=True)


def test_admin_history_routes_return_json_for_missing_history_index(monkeypatch):
    """Return JSON guidance instead of a non-JSON 500 when history indexes lag."""
    from flask import Blueprint, Flask

    route_module, _captures = load_route_module(
        monkeypatch,
        history_unavailable=True,
    )
    app = Flask(__name__)
    app.secret_key = "route-test"
    blueprint = Blueprint("data_management_unavailable_route_test", __name__)
    route_module.register_route_backend_data_management(blueprint)
    app.register_blueprint(blueprint)
    client = app.test_client()

    for path in (
        "/api/admin/data-management/jobs?scheduled=all&page_size=25",
        "/api/admin/data-management/backups?status=available&scheduled=all&page_size=25",
    ):
        response = client.get(path)
        payload = response.get_json()

        assert response.status_code == 503
        assert response.content_type.startswith("application/json")
        assert payload["success"] is False
        assert payload["maintenance_required"] is True
        assert payload["maintenance_action"] == "cosmos_indexing_policy_maintenance"
        assert "Apply Cosmos indexing policies" in payload["error"]
        assert "corresponding composite index" not in response.get_data(as_text=True)


def test_deployers_apply_the_data_management_history_index():
    """Keep Bicep, generated ARM, Terraform, and deployer version aligned."""
    config_source = (APP_ROOT / "config.py").read_text(encoding="utf-8")
    bicep = (
        REPO_ROOT / "deployers" / "bicep" / "modules" / "cosmosDb.bicep"
    ).read_text(encoding="utf-8")
    arm = (
        REPO_ROOT / "deployers" / "bicep" / "main.json"
    ).read_text(encoding="utf-8")
    terraform = (
        REPO_ROOT / "deployers" / "terraform" / "main.tf"
    ).read_text(encoding="utf-8")
    deployer_version = (
        REPO_ROOT / "deployers" / "version.txt"
    ).read_text(encoding="utf-8").strip()

    assert "compositeIndexes: container.compositeIndexes" in bicep
    assert "path: '/created_at'" in bicep
    assert "path: '/id'" in bicep
    assert '"compositeIndexes"' in arm
    assert '"/created_at"' in arm
    assert '"/id"' in arm
    assert "data_management_history_composite_indexes" in terraform
    assert 'each.key == "data_management_jobs"' in terraform
    assert '{ path = "/created_at", order = "Descending" }' in terraform
    assert '{ path = "/id", order = "Descending" }' in terraform
    assert "DATA_MANAGEMENT_HISTORY_INDEXING_POLICY" in config_source
    assert "indexing_policy=DATA_MANAGEMENT_HISTORY_INDEXING_POLICY" in config_source
    assert '"path": "/created_at", "order": "descending"' in config_source
    assert '"path": "/id", "order": "descending"' in config_source
    assert deployer_version == "1.0.24"
