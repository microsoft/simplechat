#!/usr/bin/env python3
# test_data_management_restore_workflow.py
"""
Functional tests for Data Management restore workflow safety.
Version: 0.250.106
Implemented in: 0.250.106

This test ensures restore plans are immutable, destructive restore policies
require explicit confirmation, preflight blocks unsafe backups, and restore
review authorizations are admin-bound and single-use.
"""

import copy
import importlib.util
from pathlib import Path
import sys
import types

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
MODULE_PATH = APP_ROOT / "functions_data_management.py"
sys.path.insert(0, str(APP_ROOT))

from functions_data_management_restore_state import initialize_restore_state


class FakeJobContainer:
    """Store Data Management jobs and review authorizations in memory."""

    def __init__(self, documents=None):
        self.documents = {
            document["id"]: copy.deepcopy(document)
            for document in (documents or [])
        }

    def create_item(self, body):
        if body["id"] in self.documents:
            error = RuntimeError("conflict")
            error.status_code = 409
            raise error
        saved = copy.deepcopy(body)
        saved["_etag"] = f"etag-{len(self.documents) + 1}"
        self.documents[saved["id"]] = saved
        return copy.deepcopy(saved)

    def read_item(self, item, partition_key):
        del partition_key
        if item not in self.documents:
            raise KeyError(item)
        return copy.deepcopy(self.documents[item])

    def replace_item(self, item, body, etag=None, match_condition=None):
        del match_condition
        existing = self.documents[item]
        if etag and existing.get("_etag") and etag != existing.get("_etag"):
            error = RuntimeError("etag mismatch")
            error.status_code = 412
            raise error
        saved = copy.deepcopy(body)
        saved["_etag"] = f"etag-{len(self.documents) + 1}"
        self.documents[item] = saved
        return copy.deepcopy(saved)

    def upsert_item(self, body):
        saved = copy.deepcopy(body)
        saved["_etag"] = f"etag-{len(self.documents) + 1}"
        self.documents[saved["id"]] = saved
        return copy.deepcopy(saved)

    def query_items(self, **_kwargs):
        return iter(copy.deepcopy(list(self.documents.values())))


def build_backup_job(status="completed"):
    """Build a completed backup job with a restore-ready manifest pointer."""
    return {
        "id": "backup-restore-source",
        "type": "data_management_job",
        "operation": "backup",
        "backup_type": "full",
        "status": status,
        "created_at": "2026-07-31T12:00:00+00:00",
        "completed_at": "2026-07-31T12:30:00+00:00",
        "backup_plan": {
            "backup_type": "full",
            "source_scope": "simplechat-primary",
            "source_cutoff_at": "2026-07-31T12:00:00+00:00",
            "differential_mode": "full_snapshot",
            "source_cutoff_semantics": {"deletion_policy": "none"},
            "include_cosmos": True,
            "include_ai_search": True,
            "include_source_blobs": True,
            "backup_storage_container_name": "simplechat-backups",
            "backup_storage_path_prefix": "simplechat-backups",
            "storage_identity": "storage-fingerprint",
            "encryption_enabled": False,
            "encryption_key_storage": "not_configured",
            "encryption_key_reference": "",
            "encryption_key_fingerprint": "",
        },
        "backup_state": {
            "manifest": {"path": "simplechat-backups/full/manifest.json"},
        },
        "result": {
            "manifest_path": "simplechat-backups/full/manifest.json",
            "base_prefix": "simplechat-backups/full",
        },
    }


def load_data_management_module(monkeypatch, job_container):
    """Load production restore helpers with in-memory Cosmos dependencies."""
    config_module = types.ModuleType("config")
    config_module.CLIENTS = {}
    config_module.VERSION = "0.250.106"
    config_module.cosmos_data_management_jobs_container = job_container
    config_module.cosmos_data_management_job_items_container = job_container
    config_module.cosmos_settings_container = job_container
    config_module.SECRET_KEY = "unit-test-secret"
    config_module.storage_account_user_documents_container_name = "user-documents"
    config_module.storage_account_group_documents_container_name = "group-documents"
    config_module.storage_account_public_documents_container_name = "public-documents"
    config_module.storage_account_personal_chat_container_name = "personal-chat"
    config_module.storage_account_group_chat_container_name = "group-chat"
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

    module_name = "data_management_restore_workflow_test_module"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec and spec.loader
    spec.loader.exec_module(module)
    monkeypatch.delitem(sys.modules, module_name, raising=False)
    return module


def test_restore_state_rejects_changed_plan():
    """Verify restore checkpoints cannot resume with changed policy."""
    plan = {
        "source_backup_id": "backup-restore-source",
        "restore_policy": "create_only",
    }
    state = initialize_restore_state(
        None,
        "restore-job",
        plan,
    )

    with pytest.raises(ValueError, match="Restore plan changed"):
        initialize_restore_state(
            state,
            "restore-job",
            {**plan, "restore_policy": "overwrite_existing"},
        )


def test_restore_plan_requires_completed_backup_and_overwrite_confirmation(monkeypatch):
    """Validate backup status and destructive confirmation gates."""
    job_container = FakeJobContainer([build_backup_job()])
    module = load_data_management_module(monkeypatch, job_container)

    create_only = module._normalize_data_management_restore_plan({
        "source_backup_id": "backup-restore-source",
    })
    assert create_only["restore_policy"] == "create_only"
    assert create_only["source_backup_manifest_path"].endswith("manifest.json")

    with pytest.raises(
        module.DataManagementSettingsValidationError,
        match="Overwrite restore requires",
    ):
        module._normalize_data_management_restore_plan(
            {
                "source_backup_id": "backup-restore-source",
                "restore_policy": "overwrite_existing",
            },
            require_confirmation=True,
        )

    overwrite = module._normalize_data_management_restore_plan(
        {
            "source_backup_id": "backup-restore-source",
            "restore_policy": "overwrite_existing",
            "overwrite_confirmed": True,
            "overwrite_confirmation_phrase": "RESTORE WITH OVERWRITE",
        },
        require_confirmation=True,
    )
    assert overwrite["restore_policy"] == "overwrite_existing"

    failed_container = FakeJobContainer([build_backup_job(status="failed")])
    failed_module = load_data_management_module(monkeypatch, failed_container)
    with pytest.raises(
        failed_module.DataManagementSettingsValidationError,
        match="Only completed backups",
    ):
        failed_module._normalize_data_management_restore_plan({
            "source_backup_id": "backup-restore-source",
        })


def test_restore_preflight_blocks_failed_manifest_and_warns_partial(monkeypatch):
    """Validate restore review blocks incomplete backups and documents partial semantics."""
    job_container = FakeJobContainer([build_backup_job()])
    module = load_data_management_module(monkeypatch, job_container)
    restore_plan = module._normalize_data_management_restore_plan({
        "source_backup_id": "backup-restore-source",
        "include_cosmos": False,
        "include_ai_search": False,
        "include_source_blobs": False,
    })
    restore_plan["differential_mode"] = "latest_item_state"
    manifest = {
        "schema_version": 2,
        "app": "SimpleChat",
        "failed_resource_names": ["cosmos:users"],
        "warnings": [],
        "artifacts": [],
    }

    review = module._run_data_management_restore_preflight(
        {},
        restore_plan,
        build_backup_job(),
        manifest,
    )

    assert review["ready"] is False
    assert review["blocker_count"] == 1
    assert any(check["id"] == "manifest_integrity" and check["status"] == "block" for check in review["checks"])
    assert any(check["id"] == "partial_semantics" and check["status"] == "warn" for check in review["checks"])


def test_restore_review_authorization_is_admin_bound_and_single_use(monkeypatch):
    """Verify ready restore review authorizations cannot be replayed by another admin."""
    job_container = FakeJobContainer([build_backup_job()])
    module = load_data_management_module(monkeypatch, job_container)
    authorization = module.create_data_management_restore_review_authorization(
        "admin-user",
        "restore-fingerprint",
    )
    reservation = module.reserve_data_management_restore_review_authorization(
        authorization["authorization_token"],
        "admin-user",
        "restore-fingerprint",
    )

    with pytest.raises(
        module.DataManagementSettingsValidationError,
        match="reserved or used",
    ):
        module.reserve_data_management_restore_review_authorization(
            authorization["authorization_token"],
            "admin-user",
            "restore-fingerprint",
        )

    with pytest.raises(
        module.DataManagementSettingsValidationError,
        match="invalid or expired",
    ):
        module.consume_data_management_restore_review_authorization(
            authorization["authorization_token"],
            "different-admin",
            "restore-fingerprint",
            reservation["reservation_token"],
            reservation["job_id"],
        )

    assert module.consume_data_management_restore_review_authorization(
        authorization["authorization_token"],
        "admin-user",
        "restore-fingerprint",
        reservation["reservation_token"],
        reservation["job_id"],
    ) is True
