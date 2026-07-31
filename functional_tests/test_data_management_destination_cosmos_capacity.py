# test_data_management_destination_cosmos_capacity.py
"""
Functional test for Data Management destination Cosmos migration controls.
Version: 0.250.108
Implemented in: 0.250.075
Updated in: 0.250.106
Updated in: 0.250.108

This test ensures preflight proves destination create/read/delete access and
an opt-in 10,000 RU migration boost restores the original capacity afterward.
It also verifies RU Boost permission testing is separate from data-copy access.
"""

import copy
import importlib.util
from pathlib import Path
import sys
import types


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
MODULE_PATH = APP_ROOT / "functions_data_management.py"
sys.path.insert(0, str(APP_ROOT))

from functions_data_management_migration_state import initialize_migration_state


class FakeJobContainer:
    """Persist deep-copy job state for checkpoint assertions."""

    def __init__(self):
        self.items = {}

    def create_item(self, body):
        self.items[body["id"]] = copy.deepcopy(body)
        return copy.deepcopy(body)

    def read_item(self, item, partition_key):
        del partition_key
        if item in self.items:
            return copy.deepcopy(self.items[item])
        return {"id": item, "type": "data_management_settings"}

    def upsert_item(self, body):
        self.items[body["id"]] = copy.deepcopy(body)
        return copy.deepcopy(body)


class FakeSourceContainer:
    """Return one source item to prove source data-plane access."""

    def query_items(self, **_kwargs):
        return iter([{"id": "source-item"}])


class FakeTargetContainer:
    """Track the temporary preflight item lifecycle."""

    def __init__(self):
        self.created = []
        self.read = []
        self.deleted = []

    def create_item(self, body):
        self.created.append(copy.deepcopy(body))
        return body

    def read_item(self, item, partition_key):
        self.read.append((item, partition_key))
        return {"id": item}

    def delete_item(self, item, partition_key):
        self.deleted.append((item, partition_key))


class FakeTargetDatabase:
    """Return a target container for each requested destination resource."""

    def __init__(self, target_container):
        self.target_container = target_container

    def create_container_if_not_exists(self, **_kwargs):
        return self.target_container

    def read(self):
        return {"id": "SimpleChat"}


def load_data_management_module(monkeypatch, source_container, job_container):
    """Load Data Management with only the fake dependencies this test needs."""
    config_module = types.ModuleType("config")
    config_module.CLIENTS = {}
    config_module.VERSION = "0.250.075"
    config_module.cosmos_data_management_jobs_container = job_container
    config_module.cosmos_data_management_job_items_container = job_container
    config_module.cosmos_settings_container = job_container
    config_module.source_container = source_container
    config_module.target_container_name = "target-container"
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

    module_name = "data_management_destination_capacity_test_module"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec and spec.loader
    spec.loader.exec_module(module)
    monkeypatch.delitem(sys.modules, module_name, raising=False)
    return module


def test_destination_cosmos_preflight_and_temporary_capacity_restore(monkeypatch):
    """Validate destination access probe and safe 10,000 RU boost restoration."""
    migration_id = "11111111-1111-1111-1111-111111111111"
    job_container = FakeJobContainer()
    target_container = FakeTargetContainer()
    module = load_data_management_module(monkeypatch, FakeSourceContainer(), job_container)
    module.DATA_MANAGEMENT_MIGRATION_COSMOS_CONTAINERS = {
        "users": [{
            "name": "user_settings",
            "container_attr": "source_container",
            "container_name_attr": "target_container_name",
            "partition_key_path": "/id",
            "id_field": "id",
        }],
        "groups": [],
        "public_workspaces": [],
    }
    monkeypatch.setattr(module, "_get_target_cosmos_database", lambda _settings: FakeTargetDatabase(target_container))

    migration_plan = {
        "users": {"mode": "all", "ids": [], "include_documents": False},
        "groups": {"mode": "none", "ids": [], "include_documents": False},
        "public_workspaces": {"mode": "none", "ids": [], "include_documents": False},
    }
    preflight = module._preflight_target_cosmos_migration_access({}, migration_plan)
    assert preflight["container_count"] == 1
    assert len(target_container.created) == len(target_container.read) == len(target_container.deleted) == 1
    assert target_container.created[0]["type"] == "simplechat_migration_preflight"

    capacity_calls = []
    monkeypatch.setattr(
        module,
        "_inspect_target_cosmos_migration_capacity",
        lambda _settings, _plan: {
            "target_ru": 10000,
            "management_settings": {"target": "destination"},
            "targets": [{
                "scope": "database",
                "container_name": "",
                "mode": "autoscale",
                "current_ru": 4000,
            }, {
                "scope": "container",
                "container_name": "target-container",
                "mode": "autoscale",
                "current_ru": 5000,
            }],
        },
    )
    monkeypatch.setattr(
        module,
        "get_database_throughput",
        lambda _settings: {"current_ru": 10000, "is_scalable": True},
    )
    monkeypatch.setattr(
        module,
        "get_container_throughput",
        lambda _settings, _container_name: {"current_ru": 10000, "is_scalable": True},
    )

    def set_capacity(_settings, target_ru, **kwargs):
        target_scope = kwargs["decision"]["scope"]
        target_container_name = kwargs["decision"]["container_name"]
        if target_ru == 10000:
            snapshots = job["migration_state"]["capacity"]["targets"]
            assert any(
                snapshot["scope"] == target_scope and
                snapshot["container_name"] == target_container_name and
                snapshot["boost_attempted"] is True and
                snapshot["original_ru"] in {4000, 5000}
                for snapshot in snapshots
            )
        capacity_calls.append((target_ru, kwargs["decision"]["scope"], kwargs["decision"]["target_mode"]))
        return {"to_ru": target_ru}

    monkeypatch.setattr(module, "set_database_throughput", set_capacity)
    settings = {
        "migration_temporary_destination_ru_enabled": True,
        "migration_temporary_destination_ru": 10000,
        "data_management_job_lease_seconds": 900,
    }
    migration_state = initialize_migration_state(None, migration_id, {"test": "capacity"})
    job = {"id": migration_id, "migration_state": migration_state}

    state_after_boost = module._apply_temporary_destination_capacity(
        job,
        migration_state,
        settings,
        migration_plan,
    )
    warnings, restored_state = module._restore_temporary_destination_capacity(
        job,
        state_after_boost,
        settings,
    )

    assert capacity_calls == [
        (10000, "database", "autoscale"),
        (10000, "container", "autoscale"),
        (5000, "container", "autoscale"),
        (4000, "database", "autoscale"),
    ]
    assert not warnings
    assert restored_state["capacity"]["status"] == "restored"
    assert restored_state["capacity"]["targets"][0]["restore_status"] == "restored"
    assert restored_state["capacity"]["targets"][1]["restore_status"] == "restored"


def test_ru_boost_permission_test_is_separate_from_data_copy_access(monkeypatch):
    """Validate RU Boost checks ARM capacity permissions without data-copy probes."""
    job_container = FakeJobContainer()
    module = load_data_management_module(monkeypatch, FakeSourceContainer(), job_container)
    module.DATA_MANAGEMENT_MIGRATION_COSMOS_CONTAINERS = {
        "users": [{
            "name": "user_settings",
            "container_attr": "source_container",
            "container_name_attr": "target_container_name",
            "partition_key_path": "/id",
            "id_field": "id",
        }],
        "groups": [],
        "public_workspaces": [],
    }
    monkeypatch.setattr(
        module,
        "_preflight_target_cosmos_migration_access",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("data copy probe should not run")),
    )
    monkeypatch.setattr(
        module,
        "_inspect_target_cosmos_migration_capacity",
        lambda _settings, _plan: {
            "target_ru": 10000,
            "management_settings": {"target": "destination"},
            "database_mode": "autoscale",
            "database_current_ru": 4000,
            "targets": [{
                "scope": "database",
                "container_name": "",
                "mode": "autoscale",
                "current_ru": 4000,
            }],
        },
    )
    capacity_calls = []

    def validate_capacity(_settings, target_ru, **kwargs):
        capacity_calls.append((target_ru, kwargs["reason"], kwargs["decision"]["scope"]))
        return {"to_ru": target_ru}

    monkeypatch.setattr(module, "set_database_throughput", validate_capacity)

    result = module.test_target_cosmos_capacity_management(
        settings={
            "target_cosmos_endpoint": "https://target.documents.azure.com:443/",
            "target_cosmos_subscription_id": "sub",
            "target_cosmos_resource_group": "rg",
            "migration_temporary_destination_ru": 10000,
        },
        migration_plan={
            "users": {"mode": "all", "ids": [], "include_documents": False},
            "groups": {"mode": "none", "ids": [], "include_documents": False},
            "public_workspaces": {"mode": "none", "ids": [], "include_documents": False},
        },
    )

    assert result["success"] is True
    assert result["target"] == "cosmos_ru_boost"
    assert result["targets"][0]["write_verified"] is True
    assert capacity_calls == [(4000, "validate_data_management_ru_boost_permissions", "database")]


def test_target_cosmos_connection_excludes_ru_boost_permissions(monkeypatch):
    """Validate data-copy access testing does not require ARM capacity permissions."""
    job_container = FakeJobContainer()
    target_container = FakeTargetContainer()
    module = load_data_management_module(monkeypatch, FakeSourceContainer(), job_container)
    module.DATA_MANAGEMENT_MIGRATION_COSMOS_CONTAINERS = {
        "users": [{
            "name": "user_settings",
            "container_attr": "source_container",
            "container_name_attr": "target_container_name",
            "partition_key_path": "/id",
            "id_field": "id",
        }],
        "groups": [],
        "public_workspaces": [],
    }
    monkeypatch.setattr(module, "_get_target_cosmos_database", lambda _settings: FakeTargetDatabase(target_container))
    monkeypatch.setattr(
        module,
        "_inspect_target_cosmos_migration_capacity",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("RU Boost probe should not run")),
    )

    result = module.test_target_cosmos_connection(
        settings={
            "target_cosmos_endpoint": "https://target.documents.azure.com:443/",
            "migration_temporary_destination_ru_enabled": True,
            "target_cosmos_subscription_id": "",
            "target_cosmos_resource_group": "",
        },
        migration_plan={
            "users": {"mode": "all", "ids": [], "include_documents": False},
            "groups": {"mode": "none", "ids": [], "include_documents": False},
            "public_workspaces": {"mode": "none", "ids": [], "include_documents": False},
        },
    )

    assert result["success"] is True
    assert "capacity" not in result
    assert result["migration_access"]["container_count"] == 1


def test_failed_capacity_restore_remains_pending_for_later_recovery(monkeypatch):
    """Validate a failed restore leaves its durable snapshot available for a retry."""
    migration_id = "55555555-5555-5555-5555-555555555555"
    job_container = FakeJobContainer()
    module = load_data_management_module(monkeypatch, FakeSourceContainer(), job_container)
    monkeypatch.setattr(
        module,
        "get_database_throughput",
        lambda _settings: {"current_ru": 10000, "is_scalable": True},
    )
    monkeypatch.setattr(
        module,
        "set_database_throughput",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("restore failed")),
    )
    migration_state = initialize_migration_state(None, migration_id, {"test": "restore-pending"})
    migration_state["capacity"] = {
        "status": "boosted",
        "restore_pending": True,
        "management_settings": {"target": "destination"},
        "targets": [{
            "scope": "database",
            "container_name": "",
            "mode": "autoscale",
            "original_ru": 4000,
            "target_ru": 10000,
            "boosted_to_ru": 10000,
            "boost_attempted": True,
            "changed": True,
            "restore_status": "pending",
        }],
    }
    job = {"id": migration_id, "migration_state": migration_state}

    warnings, restored_state = module._restore_temporary_destination_capacity(
        job,
        migration_state,
        {"data_management_job_lease_seconds": 900},
    )

    assert warnings
    assert restored_state["capacity"]["restore_pending"] is True
    assert restored_state["capacity"]["status"] == "restore_pending"
    assert restored_state["capacity"]["targets"][0]["restore_status"] == "restore_failed"


def test_retry_recovers_pending_capacity_without_reboost(monkeypatch):
    """Restore a durable pending snapshot before any new capacity inspection or boost."""
    migration_id = "66666666-6666-6666-6666-666666666666"
    job_container = FakeJobContainer()
    module = load_data_management_module(monkeypatch, FakeSourceContainer(), job_container)
    monkeypatch.setattr(
        module,
        "get_database_throughput",
        lambda _settings: {"current_ru": 10000, "is_scalable": True},
    )
    capacity_calls = []

    def restore_capacity(_settings, target_ru, **_kwargs):
        capacity_calls.append(target_ru)
        return {"to_ru": target_ru}

    monkeypatch.setattr(module, "set_database_throughput", restore_capacity)
    monkeypatch.setattr(
        module,
        "_inspect_target_cosmos_migration_capacity",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("A recovery retry must not inspect or reapply the capacity boost.")
        ),
    )
    migration_state = initialize_migration_state(None, migration_id, {"test": "restore-retry"})
    migration_state["capacity"] = {
        "status": "restore_pending",
        "restore_pending": True,
        "management_settings": {"target": "destination"},
        "targets": [{
            "scope": "database",
            "container_name": "",
            "mode": "autoscale",
            "original_ru": 4000,
            "target_ru": 10000,
            "boosted_to_ru": 10000,
            "boost_attempted": True,
            "changed": True,
            "restore_status": "restore_failed",
        }],
    }
    job = {"id": migration_id, "migration_state": migration_state}

    recovered_state = module._apply_temporary_destination_capacity(
        job,
        migration_state,
        {
            "migration_temporary_destination_ru_enabled": True,
            "data_management_job_lease_seconds": 900,
        },
        {"users": {"mode": "all", "include_documents": False}},
    )

    assert capacity_calls == [4000]
    assert recovered_state["capacity"]["restore_pending"] is False
    assert recovered_state["capacity"]["status"] == "restored"