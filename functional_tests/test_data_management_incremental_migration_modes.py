# test_data_management_incremental_migration_modes.py
"""
Functional test for explicit Data Management incremental migration modes.
Version: 0.250.078
Implemented in: 0.250.077
Updated in: 0.250.078

This test ensures mode defaults, baseline lineage, and destructive mirror
confirmation are normalized into the immutable migration plan.
"""

import importlib.util
from pathlib import Path
import sys
import types

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
MODULE_PATH = APP_ROOT / "functions_data_management.py"
sys.path.insert(0, str(APP_ROOT))


class FakeJobContainer:
    """Provide explicit reads and ordered completed migration candidates."""

    def __init__(self, jobs=None):
        self.jobs = {job["id"]: job for job in (jobs or [])}

    def read_item(self, item, partition_key):
        assert item == partition_key
        return self.jobs[item]

    def query_items(self, **_kwargs):
        return iter(sorted(
            self.jobs.values(),
            key=lambda job: job.get("completed_at") or "",
            reverse=True,
        ))


def load_data_management_module(monkeypatch, job_container=None):
    """Load the production module with lightweight configuration dependencies."""
    config_module = types.ModuleType("config")
    config_module.CLIENTS = {}
    config_module.VERSION = "0.250.077"
    config_module.cosmos_data_management_jobs_container = job_container or FakeJobContainer()
    config_module.cosmos_data_management_job_items_container = object()
    config_module.cosmos_settings_container = object()
    monkeypatch.setitem(sys.modules, "config", config_module)

    appinsights_module = types.ModuleType("functions_appinsights")
    appinsights_module.log_event = lambda *_args, **_kwargs: None
    monkeypatch.setitem(sys.modules, "functions_appinsights", appinsights_module)

    throughput_module = types.ModuleType("functions_cosmos_throughput")
    throughput_module.CosmosThroughputError = RuntimeError
    throughput_module.get_container_throughput = lambda *_args, **_kwargs: {}
    throughput_module.get_database_throughput = lambda *_args, **_kwargs: {}
    throughput_module.set_database_throughput = lambda *_args, **_kwargs: {}
    monkeypatch.setitem(sys.modules, "functions_cosmos_throughput", throughput_module)

    module_name = "data_management_incremental_modes_test_module"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec and spec.loader
    spec.loader.exec_module(module)
    monkeypatch.delitem(sys.modules, module_name, raising=False)
    return module


def base_plan():
    """Return the smallest valid all-user migration plan."""
    return {
        "users": {"mode": "all", "ids": [], "include_documents": True},
        "groups": {"mode": "none", "ids": [], "include_documents": False},
        "public_workspaces": {"mode": "none", "ids": [], "include_documents": False},
        "include_ai_search": True,
        "include_source_blobs": True,
    }


def test_incremental_migration_mode_contract(monkeypatch):
    """Validate the safe default, baseline GUID, and mirror confirmation guard."""
    module = load_data_management_module(monkeypatch)

    normalized_default = module.normalize_data_management_migration_plan({
        "migration_plan": base_plan(),
    })
    assert normalized_default["migration_mode"] == "new_only"
    assert normalized_default["baseline_job_id"] == ""
    assert normalized_default["mirror_deletions_confirmed"] is False
    assert normalized_default["target_ai_search_writes_frozen"] is False

    frozen_plan = base_plan()
    frozen_plan["target_ai_search_writes_frozen"] = True
    normalized_frozen_plan = module.normalize_data_management_migration_plan({
        "migration_plan": frozen_plan,
    })
    assert normalized_frozen_plan["target_ai_search_writes_frozen"] is True

    baseline_job_id = "11111111-1111-1111-1111-111111111111"
    delta_plan = base_plan()
    delta_plan.update({
        "migration_mode": "delta_upsert",
        "baseline_job_id": baseline_job_id,
    })
    normalized_delta = module.normalize_data_management_migration_plan({
        "migration_plan": delta_plan,
    })
    assert normalized_delta["migration_mode"] == "delta_upsert"
    assert normalized_delta["baseline_job_id"] == baseline_job_id

    mirror_plan = base_plan()
    mirror_plan["migration_mode"] = "mirror_with_deletions"
    with pytest.raises(module.DataManagementSettingsValidationError, match="exact confirmation phrase"):
        module.normalize_data_management_migration_plan({"migration_plan": mirror_plan})

    mirror_plan["mirror_confirmation"] = "MIRROR WITH DELETIONS"
    normalized_mirror = module.normalize_data_management_migration_plan({
        "migration_plan": mirror_plan,
    })
    assert normalized_mirror["mirror_deletions_confirmed"] is True

    invalid_plan = base_plan()
    invalid_plan["migration_mode"] = "overwrite_everything"
    with pytest.raises(module.DataManagementSettingsValidationError, match="Migration mode"):
        module.normalize_data_management_migration_plan({"migration_plan": invalid_plan})


def completed_baseline_job(
    module,
    job_id,
    migration_plan,
    endpoint="https://target.documents.azure.com",
    readiness="ready",
):
    """Build a completed migration record with a durable cutoff and configuration."""
    return {
        "id": job_id,
        "type": module.DATA_MANAGEMENT_JOB_TYPE,
        "operation": module.DATA_MANAGEMENT_OPERATION_MIGRATION,
        "status": module.DATA_MANAGEMENT_STATUS_COMPLETED,
        "completed_at": "2026-07-28T12:30:00+00:00",
        "result": {"dry_run": False},
        "migration_state": {
            "status": "completed",
            "source_cutoff_at": "2026-07-28T12:00:00+00:00",
            "resources": {
                "reconciliation:cutover": {
                    "status": "completed",
                    "result": {"readiness": readiness},
                },
            },
            "configuration": {
                "migration_plan": migration_plan,
                "target_cosmos_endpoint": endpoint,
                "target_ai_search_endpoint": "https://target.search.windows.net",
                "target_enhanced_citations_storage_endpoint": "https://target.blob.core.windows.net",
            },
        },
    }


def test_incremental_baseline_resolution_and_resume(monkeypatch):
    """Resolve the latest compatible cutoff and reuse it on a retried job."""
    baseline_job_id = "22222222-2222-2222-2222-222222222222"
    initial_module = load_data_management_module(monkeypatch)
    baseline_plan = initial_module.normalize_data_management_migration_plan({
        "migration_plan": base_plan(),
    })
    baseline_job = completed_baseline_job(initial_module, baseline_job_id, baseline_plan)
    job_container = FakeJobContainer([baseline_job])
    module = load_data_management_module(monkeypatch, job_container=job_container)
    delta_plan = base_plan()
    delta_plan["migration_mode"] = "delta_upsert"
    normalized_delta = module.normalize_data_management_migration_plan({
        "migration_plan": delta_plan,
    })
    settings = {
        "target_cosmos_endpoint": "https://target.documents.azure.com",
        "target_ai_search_endpoint": "https://target.search.windows.net",
        "target_enhanced_citations_storage_blob_endpoint": "https://target.blob.core.windows.net",
    }
    current_job = {"id": "33333333-3333-3333-3333-333333333333"}

    resolved = module._resolve_data_management_migration_baseline(
        current_job,
        settings,
        normalized_delta,
    )

    assert resolved["baseline_job_id"] == baseline_job_id
    assert resolved["baseline_source_cutoff_at"] == "2026-07-28T12:00:00+00:00"

    current_job["migration_state"] = {
        "configuration": {"migration_plan": resolved},
    }
    job_container.jobs.clear()
    resumed = module._resolve_data_management_migration_baseline(
        current_job,
        settings,
        normalized_delta,
    )
    assert resumed["baseline_job_id"] == baseline_job_id
    assert resumed["baseline_source_cutoff_at"] == resolved["baseline_source_cutoff_at"]


def test_incremental_baseline_rejects_incompatible_destination(monkeypatch):
    """Reject an explicit baseline that targeted another destination account."""
    baseline_job_id = "44444444-4444-4444-4444-444444444444"
    initial_module = load_data_management_module(monkeypatch)
    baseline_plan = initial_module.normalize_data_management_migration_plan({
        "migration_plan": base_plan(),
    })
    baseline_job = completed_baseline_job(
        initial_module,
        baseline_job_id,
        baseline_plan,
        endpoint="https://other.documents.azure.com",
    )
    module = load_data_management_module(
        monkeypatch,
        job_container=FakeJobContainer([baseline_job]),
    )
    delta_plan = base_plan()
    delta_plan.update({
        "migration_mode": "delta_upsert",
        "baseline_job_id": baseline_job_id,
    })
    normalized_delta = module.normalize_data_management_migration_plan({
        "migration_plan": delta_plan,
    })

    with pytest.raises(module.DataManagementSettingsValidationError, match="different destination"):
        module._resolve_data_management_migration_baseline(
            {"id": "55555555-5555-5555-5555-555555555555"},
            {
                "target_cosmos_endpoint": "https://target.documents.azure.com",
                "target_ai_search_endpoint": "https://target.search.windows.net",
                "target_enhanced_citations_storage_blob_endpoint": "https://target.blob.core.windows.net",
            },
            normalized_delta,
        )


def test_migration_preview_aggregates_services_without_deletions(monkeypatch):
    """Build server-owned estimates while keeping every reconciliation read-only."""
    module = load_data_management_module(monkeypatch)
    deletion_flags = []
    monkeypatch.setattr(module, "_get_existing_target_cosmos_database", lambda _settings: object())
    monkeypatch.setattr(
        module,
        "_reconcile_cosmos_migration",
        lambda *_args, **kwargs: deletion_flags.append(kwargs.get("apply_deletions")) or {
            "service": "cosmos",
            "create_count": 2,
            "update_count": 1,
            "unchanged_count": 3,
            "delete_candidate_count": 0,
            "conflict_count": 1,
            "missing_count": 0,
        },
    )
    monkeypatch.setattr(
        module,
        "_reconcile_ai_search_migration",
        lambda *_args, **kwargs: deletion_flags.append(kwargs.get("apply_deletions")) or {
            "service": "ai_search",
            "create_count": 4,
            "update_count": 2,
            "unchanged_count": 6,
            "delete_candidate_count": 0,
            "conflict_count": 0,
            "missing_count": 0,
        },
    )
    monkeypatch.setattr(
        module,
        "_reconcile_blob_migration",
        lambda *_args, **kwargs: deletion_flags.append(kwargs.get("apply_deletions")) or {
            "service": "source_blobs",
            "create_count": 1,
            "update_count": 1,
            "unchanged_count": 1,
            "delete_candidate_count": 0,
            "not_applicable_count": 2,
            "source_missing_count": 1,
            "conflict_count": 0,
            "missing_count": 0,
        },
    )

    preview = module.preview_data_management_migration_plan(
        {},
        {"migration_plan": base_plan()},
    )

    assert deletion_flags == [False, False, False]
    assert preview["estimated_outcomes"] == {
        "create_count": 7,
        "update_count": 4,
        "unchanged_count": 10,
        "delete_count": 0,
        "not_applicable_count": 2,
        "missing_count": 1,
        "conflict_count": 1,
        "failed_count": 0,
    }
    assert len(preview["plan_fingerprint"]) == 64


def test_incremental_scope_signature_uses_all_two_thousand_ids(monkeypatch):
    """Keep every supported selected ID in baseline compatibility decisions."""
    module = load_data_management_module(monkeypatch)
    selected_ids = [f"user-{index:04d}" for index in range(2000)]
    migration_plan = module.normalize_data_management_migration_plan({
        "migration_plan": {
            **base_plan(),
            "users": {
                "mode": "selected",
                "ids": selected_ids,
                "include_documents": True,
            },
        },
    })

    signature = module._migration_plan_scope_signature(migration_plan)

    assert len(signature["users"]["ids"]) == 2000
    assert signature["users"]["ids"][-1] == "user-1999"


def test_non_destructive_warning_baseline_can_advance_watermark(monkeypatch):
    """Allow retained destination-only data to remain the newest delta baseline."""
    baseline_job_id = "77777777-7777-7777-7777-777777777777"
    initial_module = load_data_management_module(monkeypatch)
    baseline_plan = initial_module.normalize_data_management_migration_plan({
        "migration_plan": base_plan(),
    })
    baseline_job = completed_baseline_job(
        initial_module,
        baseline_job_id,
        baseline_plan,
        readiness="ready_with_warnings",
    )
    module = load_data_management_module(
        monkeypatch,
        job_container=FakeJobContainer([baseline_job]),
    )
    delta_plan = base_plan()
    delta_plan["migration_mode"] = "delta_upsert"

    resolved = module._resolve_data_management_migration_baseline(
        {"id": "88888888-8888-8888-8888-888888888888"},
        {
            "target_cosmos_endpoint": "https://target.documents.azure.com",
            "target_ai_search_endpoint": "https://target.search.windows.net",
            "target_enhanced_citations_storage_blob_endpoint": "https://target.blob.core.windows.net",
        },
        module.normalize_data_management_migration_plan({"migration_plan": delta_plan}),
    )

    assert resolved["baseline_job_id"] == baseline_job_id