# test_data_management_restore_workflow_contract.py
"""
Functional test for Data Management restore workflow contract.
Version: 0.250.106
Implemented in: 0.250.106

This test ensures restore preflight reports backup readiness while explicitly
blocking execution when the backend restore application layer is unavailable.
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


class FakeContainer:
    """Provide enough Cosmos-like behavior for restore review tests."""

    def __init__(self, items=None):
        self.items = {item["id"]: copy.deepcopy(item) for item in (items or [])}

    def read_item(self, item, partition_key):
        del partition_key
        if item not in self.items:
            raise KeyError(item)
        return copy.deepcopy(self.items[item])

    def create_item(self, body):
        self.items[body["id"]] = copy.deepcopy(body)
        return copy.deepcopy(body)

    def upsert_item(self, body):
        self.items[body["id"]] = copy.deepcopy(body)
        return copy.deepcopy(body)

    def query_items(self, **_kwargs):
        return iter(copy.deepcopy(list(self.items.values())))


def load_data_management_module(monkeypatch, backup_job):
    """Load production code with deterministic restore-review persistence."""
    settings_container = FakeContainer([{"id": "backup_settings", "type": "data_management_settings"}])
    jobs_container = FakeContainer([backup_job])
    config_module = types.ModuleType("config")
    config_module.CLIENTS = {}
    config_module.VERSION = "0.250.106"
    config_module.cosmos_data_management_jobs_container = jobs_container
    config_module.cosmos_data_management_job_items_container = FakeContainer([])
    config_module.cosmos_settings_container = settings_container
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

    module_name = "data_management_restore_workflow_contract_test_module"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec and spec.loader
    spec.loader.exec_module(module)
    monkeypatch.delitem(sys.modules, module_name, raising=False)
    return module


def test_restore_review_blocks_placeholder_execution(monkeypatch):
    """Validate restore review is explicit about unsupported execution."""
    backup_job = {
        "id": "backup-001",
        "type": "data_management_job",
        "operation": "backup",
        "backup_type": "full",
        "status": "completed",
        "created_at": "2026-07-31T12:00:00+00:00",
        "completed_at": "2026-07-31T12:10:00+00:00",
        "source_cutoff_at": "2026-07-31T12:00:00+00:00",
        "backup_plan": {
            "include_cosmos": True,
            "include_ai_search": True,
            "include_source_blobs": False,
            "encryption_enabled": True,
        },
        "backup_state": {"phase": "complete"},
        "warnings": [],
        "progress": {"percent_complete": 100},
        "result": {
            "manifest_path": "simplechat-backups/manifest.json",
            "artifacts": [{
                "name": "users",
                "type": "cosmos",
                "path": "cosmos/users.jsonl",
                "item_count": 3,
            }],
        },
    }
    module = load_data_management_module(monkeypatch, backup_job)

    review = module.review_data_management_restore({"backup_job_id": "backup-001"})

    assert review["supported"] is False
    assert review["ready"] is False
    assert review["blocker_count"] == 1
    assert review["summary"]["backup_type"] == "full"
    assert review["summary"]["include_cosmos"] is True
    assert any(check["id"] == "restore_execution" and check["status"] == "block" for check in review["checks"])


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__]))
