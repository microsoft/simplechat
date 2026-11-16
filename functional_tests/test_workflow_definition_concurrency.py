# test_workflow_definition_concurrency.py
"""
Functional tests for workflow definition/editor concurrency.
Version: 0.261.108
Implemented in: 0.261.108

Conditional saves protect V2 edits and preserve simultaneous runtime progress.
Retrying a runtime update never restores an old authored task definition.
"""

import copy
import sys
from pathlib import Path

import pytest
from azure.core import MatchConditions
from azure.cosmos.exceptions import CosmosHttpResponseError, CosmosResourceNotFoundError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))

# Application imports follow worktree module-path setup.
from functions_workflow_definition_store import save_workflow_definition_record, update_workflow_runtime_record
from functions_workflow_definitions import WorkflowDefinitionConflict


class Container:
    def __init__(self):
        self.item = {"id": "workflow", "user_id": "owner", "name": "Original", "definition_version": 2,
                     "tasks": [{"id": "one", "instructions": "Original task."}], "run_count": 0, "_etag": "1"}
        self.concurrent = None
        self.writes = 0

    def read_item(self, item, partition_key):
        assert partition_key == "owner"
        if self.item is None:
            raise CosmosResourceNotFoundError(status_code=404)
        return copy.deepcopy(self.item)

    def replace_item(self, *, item, body, etag, match_condition):
        assert match_condition == MatchConditions.IfNotModified
        self.writes += 1
        if self.concurrent is not None:
            self.item.update(self.concurrent)
            self.item["_etag"] = str(int(self.item["_etag"]) + 1)
            self.concurrent = None
        if etag != self.item["_etag"]:
            raise CosmosHttpResponseError(status_code=412)
        self.item = copy.deepcopy(body)
        self.item["_etag"] = str(int(etag) + 1)
        return copy.deepcopy(self.item)


def test_native_save_preserves_runtime_progress_that_changed_during_normalization():
    container = Container()
    existing = copy.deepcopy(container.item)
    updated = {**existing, "name": "Renamed"}
    container.item.update(run_count=3, last_run_status="completed", conversation_id="new-run-conversation", _etag="2")
    saved = save_workflow_definition_record(container, "owner", updated, existing)
    assert saved["name"] == "Renamed"
    assert saved["run_count"] == 3
    assert saved["last_run_status"] == "completed"
    assert saved["conversation_id"] == "new-run-conversation"


def test_racing_definition_edit_is_not_overwritten():
    container = Container()
    existing = copy.deepcopy(container.item)
    container.concurrent = {"name": "Someone else's edit"}
    with pytest.raises(WorkflowDefinitionConflict, match="changed"):
        save_workflow_definition_record(container, "owner", {**existing, "name": "My edit"}, existing)
    assert container.item["name"] == "Someone else's edit"


def test_runtime_update_reloads_a_new_definition_after_conflict():
    container = Container()
    container.concurrent = {"tasks": [{"id": "one", "instructions": "New authored task."}]}
    saved = update_workflow_runtime_record(container, "owner", "workflow", {"run_count": 3}, "later")
    assert saved["tasks"][0]["instructions"] == "New authored task."
    assert saved["run_count"] == 3
    assert container.writes == 2


def test_deleted_workflow_is_not_recreated_by_stale_edit():
    container = Container()
    existing = copy.deepcopy(container.item)
    container.item = None
    with pytest.raises(WorkflowDefinitionConflict, match="deleted"):
        save_workflow_definition_record(container, "owner", existing, existing)


def test_concurrent_delete_has_a_controlled_runtime_not_found():
    container = Container()
    container.item = None
    with pytest.raises(LookupError, match="Workflow not found"):
        update_workflow_runtime_record(container, "owner", "workflow", {"status": "idle"}, "later")


def test_active_run_race_blocks_definition_save():
    container = Container()
    existing = copy.deepcopy(container.item)
    container.concurrent = {"active_run_id": "new-run"}
    with pytest.raises(WorkflowDefinitionConflict, match="active run"):
        save_workflow_definition_record(container, "owner", {**existing, "name": "New name"}, existing)
    assert container.item["name"] == "Original"


def test_schedule_edit_applies_its_new_next_run_not_stale_scheduler_value():
    container = Container()
    existing = copy.deepcopy(container.item)
    container.item["next_run_at"] = "old schedule time"
    saved = save_workflow_definition_record(container, "owner", {
        **existing, "schedule": {"unit": "hours", "value": 2}, "next_run_at": "new schedule time",
    }, existing)
    assert saved["next_run_at"] == "new schedule time"
