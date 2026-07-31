# test_data_management_migration_workflow_contract.py
"""
Functional tests for the Admin Data Management migration workflow contract.
Version: 0.250.103
Implemented in: 0.250.103

This test ensures migration catalogs paginate beyond 50 records, bind
continuations to the current search, and report exhaustive all-mode counts.
"""

import copy
import importlib.util
import json
from pathlib import Path
import sys
import types

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
MODULE_PATH = APP_ROOT / "functions_data_management.py"
sys.path.insert(0, str(APP_ROOT))


class FakeJobContainer:
    """Provide the minimal persistence surface required during import."""

    def __init__(self):
        self.items = {}

    def upsert_item(self, body):
        self.items[body["id"]] = copy.deepcopy(body)
        return copy.deepcopy(body)

    def create_item(self, body):
        created = copy.deepcopy(body)
        created["_etag"] = "1"
        self.items[created["id"]] = created
        return copy.deepcopy(created)

    def read_item(self, item, partition_key):
        assert item == partition_key
        if item not in self.items:
            raise KeyError(item)
        return copy.deepcopy(self.items[item])

    def replace_item(
        self,
        item,
        body,
        etag=None,
        match_condition=None,
    ):
        del match_condition
        existing = self.items[item]
        if etag != existing.get("_etag"):
            error = RuntimeError("etag mismatch")
            error.status_code = 412
            raise error
        replaced = copy.deepcopy(body)
        replaced["_etag"] = str(int(existing["_etag"]) + 1)
        self.items[item] = replaced
        return copy.deepcopy(replaced)


class FakeCatalogContainer:
    """Evaluate the bounded catalog query contract over in-memory records."""

    def __init__(self, items):
        self.items = [copy.deepcopy(item) for item in items]

    def query_items(self, query, parameters=None, **_kwargs):
        parameters = {
            parameter["name"]: parameter["value"]
            for parameter in (parameters or [])
        }
        search = str(parameters.get("@catalog_search") or "").lower()
        after_id = str(parameters.get("@catalog_after_id") or "")
        results = [
            copy.deepcopy(item)
            for item in self.items
            if (
                not search or
                any(search in str(value or "").lower() for value in item.values())
            ) and (
                not after_id or str(item.get("id") or "") > after_id
            )
        ]
        results.sort(key=lambda item: str(item.get("id") or ""))
        if query.startswith("SELECT VALUE COUNT(1)"):
            return iter([len(results)])
        return iter(results)


class FakeDocumentContainer:
    """Return scope and exhaustive document counts."""

    def __init__(self, counts):
        self.counts = dict(counts)

    def query_items(self, query, parameters=None, **_kwargs):
        if "@scope_id" not in query:
            return iter([sum(self.counts.values())])
        parameter_map = {
            parameter["name"]: parameter["value"]
            for parameter in (parameters or [])
        }
        return iter([self.counts.get(parameter_map.get("@scope_id"), 0)])


def load_data_management_module(monkeypatch, users, document_counts):
    """Load production code with deterministic migration catalog containers."""
    job_container = FakeJobContainer()
    config_module = types.ModuleType("config")
    config_module.CLIENTS = {}
    config_module.VERSION = "0.250.103"
    config_module.cosmos_data_management_jobs_container = job_container
    config_module.cosmos_data_management_job_items_container = job_container
    config_module.cosmos_settings_container = job_container
    config_module.cosmos_user_settings_container = FakeCatalogContainer(users)
    config_module.cosmos_user_documents_container = FakeDocumentContainer(
        document_counts
    )
    config_module.cosmos_groups_container = FakeCatalogContainer([])
    config_module.cosmos_group_documents_container = FakeDocumentContainer({})
    config_module.cosmos_public_workspaces_container = FakeCatalogContainer([])
    config_module.cosmos_public_documents_container = FakeDocumentContainer({})
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
    monkeypatch.setitem(
        sys.modules,
        "functions_cosmos_throughput",
        throughput_module,
    )

    module_name = "data_management_migration_workflow_contract_test_module"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec and spec.loader
    spec.loader.exec_module(module)
    monkeypatch.delitem(sys.modules, module_name, raising=False)
    return module


def build_users(count):
    """Create deterministic user catalog records."""
    return [
        {
            "id": f"user-{index:03d}",
            "display_name": f"Person {index:03d}",
            "email": f"person-{index:03d}@example.com",
        }
        for index in range(count)
    ]


def test_catalog_paginates_all_records_without_duplicates(monkeypatch):
    """Navigate three pages and retain authoritative total metadata."""
    users = build_users(61)
    module = load_data_management_module(
        monkeypatch,
        users,
        {user["id"]: 2 for user in users},
    )

    first_page = module.get_data_management_migration_catalog(
        "users",
        limit=25,
    )
    second_page = module.get_data_management_migration_catalog(
        "users",
        limit=25,
        continuation_token=first_page["continuation_token"],
    )
    third_page = module.get_data_management_migration_catalog(
        "users",
        limit=25,
        continuation_token=second_page["continuation_token"],
    )

    combined_ids = [
        item["id"]
        for page in (first_page, second_page, third_page)
        for item in page["items"]
    ]
    assert len(combined_ids) == 61
    assert len(set(combined_ids)) == 61
    assert combined_ids == sorted(combined_ids)
    assert first_page["total_count"] == 61
    assert first_page["has_more"] is True
    assert second_page["has_more"] is True
    assert third_page["has_more"] is False
    assert third_page["continuation_token"] == ""


def test_catalog_search_and_continuation_are_bound_together(monkeypatch):
    """Reject a continuation when its target or normalized search changes."""
    users = build_users(61)
    module = load_data_management_module(monkeypatch, users, {})
    page = module.get_data_management_migration_catalog(
        "users",
        search_text="person",
        limit=10,
    )

    with pytest.raises(
        module.DataManagementSettingsValidationError,
        match="current search",
    ):
        module.get_data_management_migration_catalog(
            "users",
            search_text="different",
            limit=10,
            continuation_token=page["continuation_token"],
        )

    with pytest.raises(
        module.DataManagementSettingsValidationError,
        match="invalid",
    ):
        module.get_data_management_migration_catalog(
            "users",
            continuation_token="not-a-valid-token",
        )


def test_all_mode_summary_uses_exhaustive_principal_and_document_counts(
    monkeypatch,
):
    """Ensure all mode does not inherit a catalog page limit."""
    users = build_users(61)
    module = load_data_management_module(
        monkeypatch,
        users,
        {user["id"]: 2 for user in users},
    )

    summary = module.summarize_data_management_migration_plan({
        "migration_plan": {
            "users": {
                "mode": "all",
                "ids": [],
                "include_documents": True,
            },
        },
    })

    assert summary["users"]["count"] == 61
    assert summary["users"]["document_count"] == 122
    assert summary["users"]["ids"] == []
    assert summary["users"]["ids_truncated"] is False


def test_selected_scope_limit_fails_instead_of_silently_truncating(monkeypatch):
    """Reject over-limit selections without changing requested semantics."""
    module = load_data_management_module(monkeypatch, [], {})
    selected_ids = [
        f"user-{index}"
        for index in range(module.DATA_MANAGEMENT_MIGRATION_MAX_SELECTED_IDS + 1)
    ]

    with pytest.raises(
        module.DataManagementSettingsValidationError,
        match="cannot exceed",
    ):
        module.normalize_data_management_migration_plan({
            "migration_plan": {
                "users": {
                    "mode": "selected",
                    "ids": selected_ids,
                },
            },
        })


def test_review_composes_safe_blocking_preflight_results(monkeypatch):
    """Expose blockers and counts without returning target credentials."""
    users = build_users(1)
    module = load_data_management_module(
        monkeypatch,
        users,
        {"user-000": 3},
    )
    normalized_settings = {
        "target_cosmos_authentication_type": "key",
        "target_cosmos_endpoint": "https://private.documents.azure.com",
        "target_cosmos_key": "never-return-this-key",
        "target_cosmos_database_name": "SimpleChat",
        "target_ai_search_authentication_type": "key",
        "target_ai_search_endpoint": "https://private.search.windows.net",
        "target_ai_search_key": "never-return-this-search-key",
        "target_enhanced_citations_storage_authentication_type": (
            "managed_identity"
        ),
        "migration_max_parallel_operations": 8,
        "migration_retry_count": 5,
        "migration_skip_recent_within_hours": 0,
        "migration_temporary_destination_ru_enabled": False,
        "migration_temporary_destination_ru": 10000,
    }
    monkeypatch.setattr(
        module,
        "_normalize_data_management_settings_from_payload",
        lambda _settings: copy.deepcopy(normalized_settings),
    )
    monkeypatch.setattr(
        module,
        "_preflight_target_cosmos_migration_access",
        lambda *_args: {"container_count": 1},
    )
    monkeypatch.setattr(
        module,
        "_preflight_target_ai_search_migration_access",
        lambda *_args: {"index_count": 1},
    )
    monkeypatch.setattr(
        module,
        "_get_target_cosmos_database",
        lambda _settings: object(),
    )
    monkeypatch.setattr(
        module,
        "_get_target_data_management_search_write_gate_container",
        lambda _database: object(),
    )
    monkeypatch.setattr(
        module,
        "inspect_data_management_target_migration_coordinator",
        lambda _container: {"available": True, "active": False},
    )
    monkeypatch.setattr(
        module,
        "inspect_data_management_search_write_gate",
        lambda _container: {
            "available": True,
            "state": "open",
            "active_writer_count": 0,
        },
    )
    monkeypatch.setattr(
        module,
        "preview_data_management_migration_plan",
        lambda *_args, **_kwargs: {
            "captured_at": "2026-07-30T12:00:00+00:00",
            "estimated_outcomes": {
                "create_count": 1,
                "conflict_count": 2,
                "delete_count": 0,
            },
            "services": [],
        },
    )

    review = module.review_data_management_migration(
        settings=normalized_settings,
        migration_plan={
            "users": {
                "mode": "selected",
                "ids": ["user-000"],
                "include_documents": True,
            },
            "include_ai_search": True,
            "target_ai_search_writes_frozen": True,
        },
    )

    assert review["ready"] is False
    assert review["blocker_count"] == 1
    assert review["summary"]["users"]["count"] == 1
    assert review["summary"]["users"]["document_count"] == 3
    collision_check = next(
        check
        for check in review["checks"]
        if check["id"] == "destination_inventory"
    )
    assert collision_check["status"] == "block"
    serialized_review = json.dumps(review)
    assert "never-return-this-key" not in serialized_review
    assert "private.documents.azure.com" not in serialized_review
    assert "private.search.windows.net" not in serialized_review


def test_review_fingerprint_binds_plan_but_not_confirmation_only_state(
    monkeypatch,
):
    """Allow final destructive confirmation without authorizing plan changes."""
    module = load_data_management_module(monkeypatch, [], {})
    settings = {
        "target_cosmos_endpoint": "https://target.documents.azure.com",
        "migration_max_parallel_operations": 8,
    }
    reviewed_plan = {
        "users": {
            "mode": "selected",
            "ids": ["user-001"],
            "include_documents": True,
        },
        "groups": {"mode": "none", "ids": [], "include_documents": False},
        "public_workspaces": {
            "mode": "none",
            "ids": [],
            "include_documents": False,
        },
        "migration_mode": "mirror_with_deletions",
        "mirror_deletions_confirmed": False,
    }
    confirmed_plan = copy.deepcopy(reviewed_plan)
    confirmed_plan["mirror_deletions_confirmed"] = True
    changed_plan = copy.deepcopy(confirmed_plan)
    changed_plan["users"]["ids"] = ["user-002"]

    reviewed_fingerprint = module._migration_review_fingerprint(
        settings,
        reviewed_plan,
    )

    assert module._migration_review_fingerprint(
        settings,
        confirmed_plan,
    ) == reviewed_fingerprint
    assert module._migration_review_fingerprint(
        settings,
        changed_plan,
    ) != reviewed_fingerprint


def test_ready_review_authorization_is_admin_bound_and_single_use(monkeypatch):
    """Consume a ready review token once and reject replay."""
    module = load_data_management_module(monkeypatch, [], {})
    authorization = (
        module.create_data_management_migration_review_authorization(
            "admin-user",
            "review-fingerprint",
        )
    )

    reservation = (
        module.reserve_data_management_migration_review_authorization(
            authorization["authorization_token"],
            "admin-user",
            "review-fingerprint",
        )
    )
    with pytest.raises(
        module.DataManagementSettingsValidationError,
        match="reserved or used",
    ):
        module.reserve_data_management_migration_review_authorization(
            authorization["authorization_token"],
            "admin-user",
            "review-fingerprint",
        )

    assert module.consume_data_management_migration_review_authorization(
        authorization["authorization_token"],
        "admin-user",
        "review-fingerprint",
        reservation["reservation_token"],
        reservation["job_id"],
    ) is True
    assert module.consume_data_management_migration_review_authorization(
        authorization["authorization_token"],
        "admin-user",
        "review-fingerprint",
        reservation["reservation_token"],
        reservation["job_id"],
    ) is True


def test_review_reservation_can_be_released_after_queue_failure(monkeypatch):
    """Restore a ready authorization when durable job creation fails."""
    module = load_data_management_module(monkeypatch, [], {})
    authorization = (
        module.create_data_management_migration_review_authorization(
            "admin-user",
            "review-fingerprint",
        )
    )
    reservation = (
        module.reserve_data_management_migration_review_authorization(
            authorization["authorization_token"],
            "admin-user",
            "review-fingerprint",
        )
    )

    assert module.release_data_management_migration_review_reservation(
        authorization["authorization_token"],
        reservation["reservation_token"],
    ) is True
    next_reservation = (
        module.reserve_data_management_migration_review_authorization(
            authorization["authorization_token"],
            "admin-user",
            "review-fingerprint",
        )
    )
    assert next_reservation["job_id"] == reservation["job_id"]


def test_worker_rejects_settings_changed_after_review(monkeypatch):
    """Stop before migration work when queue-time settings no longer match."""
    module = load_data_management_module(monkeypatch, [], {})
    migration_plan = {
        "users": {
            "mode": "selected",
            "ids": ["user-001"],
            "include_documents": False,
        },
        "groups": {"mode": "none", "ids": [], "include_documents": False},
        "public_workspaces": {
            "mode": "none",
            "ids": [],
            "include_documents": False,
        },
        "include_ai_search": False,
        "include_source_blobs": False,
        "migration_mode": "new_only",
    }
    reviewed_settings = {
        "target_cosmos_endpoint": "https://reviewed.documents.azure.com",
        "target_cosmos_authentication_type": "managed_identity",
    }
    reviewed_fingerprint = module._migration_review_fingerprint(
        reviewed_settings,
        module.normalize_data_management_migration_plan({
            "migration_plan": migration_plan,
        }),
    )
    job = {
        "id": "11111111-1111-1111-1111-111111111111",
        "options": {
            "migration_plan": migration_plan,
            "review_fingerprint": reviewed_fingerprint,
        },
    }

    with pytest.raises(
        module.DataManagementSettingsValidationError,
        match="settings changed",
    ):
        module.execute_migration_job(
            job,
            {
                "target_cosmos_endpoint": (
                    "https://changed.documents.azure.com"
                ),
                "target_cosmos_authentication_type": "managed_identity",
            },
        )
