# test_workflow_definition_store_integration.py
"""
Functional tests for real workflow store normalization and conditional saves.
Version: 0.261.122
Implemented in: 0.261.108

Production store functions run against a JSON-copying Cosmos double. External
agent/document authorization is isolated; versioning, task normalization, field
retention, revision handling and runtime updates use their real implementations.
"""

import ast
import copy
import logging
import sys
import uuid
from pathlib import Path

import pytest
from azure.cosmos import exceptions

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))

# Worktree modules are imported after module-path setup.
from functions_m365_workflow_binding import normalize_workflow_run_as
from functions_workflow_alert_safety import sanitize_workflow_alert_record
from functions_workflow_definition_store import save_workflow_definition_record, update_workflow_runtime_record
from functions_workflow_definitions import (
    WorkflowDefinitionConflict,
    normalize_workflow_definition,
    workflow_definition_for_editor,
)


APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"


class WorkflowContainer:
    def __init__(self, scope_field):
        self.scope_field = scope_field
        self.items = {}
        self.writes = 0

    def read_item(self, *, item, partition_key):
        try:
            return copy.deepcopy(self.items[(partition_key, item)])
        except KeyError:
            raise exceptions.CosmosResourceNotFoundError(status_code=404) from None

    def create_item(self, *, body):
        key = (body[self.scope_field], body["id"])
        if key in self.items:
            raise exceptions.CosmosResourceExistsError(status_code=409)
        self.items[key] = {**copy.deepcopy(body), "_etag": "1"}
        self.writes += 1
        return copy.deepcopy(self.items[key])

    def replace_item(self, *, item, body, etag, match_condition):
        key = (body[self.scope_field], item)
        if self.items[key]["_etag"] != etag:
            raise exceptions.CosmosHttpResponseError(status_code=412)
        self.items[key] = {**copy.deepcopy(body), "_etag": str(int(etag) + 1)}
        self.writes += 1
        return copy.deepcopy(self.items[key])

    def query_items(self, *, parameters, partition_key, **kwargs):
        return iter(copy.deepcopy([
            item for (partition, _), item in self.items.items() if partition == partition_key
        ]))


def load_group_store():
    container = WorkflowContainer("group_id")
    reference_reads = []
    namespace = {
        "uuid": uuid, "logging": logging, "exceptions": exceptions,
        "cosmos_group_workflows_container": container,
        "get_settings": lambda: {},
        "debug_print": lambda *args, **kwargs: None,
        "log_event": lambda *args, **kwargs: None,
        "_utc_now_iso": lambda: "2026-09-16T20:00:00+00:00",
        "get_workflow_max_tasks": lambda settings: 50,
        "_normalize_file_sync_config": lambda *args, **kwargs: {"enabled": False},
        "_normalize_group_document_action_config": lambda *args, **kwargs: {"type": "none"},
        "_normalize_task_document_action_config": lambda action, **kwargs: action or {"type": "none"},
        "_normalize_group_workflow_conversation_id": lambda *args, **kwargs: "",
        "normalize_group_workflow_task_runner": lambda *args, **kwargs: {"type": "inherit"},
        "normalize_workflow_alert_settings": lambda *args, **kwargs: {
            "alert_priority": "none", "alert_mode": "none", "alert_rules": [], "alert_evaluation": {},
        },
        "build_analyze_config": lambda action: {"enabled": action.get("type") == "analyze"},
        "_build_model_endpoint_candidates": lambda *args: [],
        "_build_default_model_summary": lambda settings: {"valid": True, "label": "Default model"},
        "WORKFLOW_RUNNER_TYPES": {"model", "agent"},
        "WORKFLOW_TRIGGER_TYPES": {"manual", "interval", "file_sync"},
        "WORKFLOW_TASK_LIMIT_DEFAULT": 50, "WORKFLOW_TASK_LIMIT_MIN": 1, "WORKFLOW_TASK_LIMIT_MAX": 100,
        "WORKFLOW_MAX_TASKS": 50, "WORKFLOW_TASK_NAME_MAX_LENGTH": 120,
        "WORKFLOW_TASK_INSTRUCTIONS_MAX_LENGTH": 12000,
        "WORKFLOW_TASK_RUNNER_TYPES": {"inherit", "agent", "model"},
        "WORKFLOW_ERROR_STRATEGIES": {"halt", "continue"},
        "normalize_workflow_definition": normalize_workflow_definition,
        "normalize_workflow_run_as": normalize_workflow_run_as,
        "sanitize_workflow_alert_record": sanitize_workflow_alert_record,
        "workflow_definition_for_editor": workflow_definition_for_editor,
        "save_workflow_definition_record": save_workflow_definition_record,
        "update_workflow_runtime_record": update_workflow_runtime_record,
        "authorize_workflow_reference": lambda workflow, reference, **kwargs: reference_reads.append(
            (workflow, reference, kwargs)
        ),
    }
    names = {
        "_normalize_text", "_normalize_bool", "_strip_cosmos_metadata", "_normalize_workflow_tasks",
        "normalize_workflow_max_tasks", "_normalize_workflow_error_handling",
        "_apply_group_document_action_scope", "save_group_workflow", "get_group_workflow",
        "get_group_workflows", "update_group_workflow_runtime_fields",
    }
    nodes = []
    for file_name in ("functions_personal_workflows.py", "functions_group_workflows.py"):
        for node in ast.parse((APP_ROOT / file_name).read_text(encoding="utf-8")).body:
            if isinstance(node, ast.FunctionDef) and node.name in names:
                nodes.append(node)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "workflow-store-integration", "exec"), namespace)
    return namespace, container, reference_reads


def load_personal_store():
    namespace, _, reference_reads = load_group_store()
    container = WorkflowContainer("user_id")
    namespace.update({
        "cosmos_personal_workflows_container": container,
        "_normalize_document_action_config": lambda *args, **kwargs: {"type": "none"},
        "_normalize_personal_workflow_conversation_id": lambda *args, **kwargs: "",
        "normalize_personal_workflow_task_runner": lambda *args, **kwargs: {"type": "inherit"},
    })
    names = {
        "save_personal_workflow", "get_personal_workflow", "get_personal_workflows",
        "update_personal_workflow_runtime_fields",
    }
    nodes = [
        node for node in ast.parse((APP_ROOT / "functions_personal_workflows.py").read_text(encoding="utf-8")).body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "personal-workflow-store-integration", "exec"), namespace)
    return namespace, container, reference_reads


def definition():
    return {
        "name": "Group evidence workflow", "definition_version": 2,
        "runner_type": "model", "trigger_type": "manual",
        "reference_inputs": [{
            "id": "criteria", "name": "criteria", "document_id": "policy",
            "scope_type": "group", "scope_id": "group-one",
        }],
        "tasks": [
            {"id": "extract", "name": "Extract", "instructions": "Extract.", "output_contract": {"kind": "records"}},
            {"id": "interim", "name": "Interim", "instructions": "Explain."},
            {"id": "final", "name": "Final", "instructions": "Synthesize.", "inputs": [{
                "name": "findings", "task_id": "extract", "output": "authoritative", "expected_kind": "records",
            }]},
        ],
    }


def test_group_store_preserves_real_data_flow_and_returns_edit_revision():
    helpers, container, reference_reads = load_group_store()
    saved = helpers["save_group_workflow"]("group-one", definition(), "editor")
    assert saved["definition_version"] == 2
    assert saved["tasks"][2]["inputs"][0]["task_id"] == "extract"
    assert saved["tasks"][0]["output_contract"]["kind"] == "records"
    assert saved["reference_inputs"][0]["document_id"] == "policy"
    assert reference_reads[0][2]["actor_user_id"] == "editor"
    assert len(saved["definition_revision"]) == 64
    loaded = helpers["get_group_workflow"]("group-one", saved["id"])
    assert loaded["definition_revision"] == saved["definition_revision"]
    assert helpers["get_group_workflows"]("group-one")[0] == loaded
    assert container.writes == 1


def test_native_metadata_update_retains_binding_fields_and_classic_save_cannot_erase_them():
    helpers, container, reads = load_group_store()
    saved = helpers["save_group_workflow"]("group-one", definition(), "editor")
    updated = helpers["save_group_workflow"]("group-one", {**saved, "description": "Updated description"}, "editor")
    assert updated["tasks"][2]["inputs"] == saved["tasks"][2]["inputs"]
    classic = {**updated}
    classic.pop("definition_version")
    classic.pop("reference_inputs")
    with pytest.raises(WorkflowDefinitionConflict, match="V2"):
        helpers["save_group_workflow"]("group-one", classic, "editor")
    assert container.writes == 2


def test_stale_native_editor_does_not_replace_a_new_definition():
    helpers, container, reads = load_group_store()
    saved = helpers["save_group_workflow"]("group-one", definition(), "editor")
    helpers["save_group_workflow"]("group-one", {**saved, "name": "Concurrent new name"}, "editor")
    with pytest.raises(WorkflowDefinitionConflict, match="Reload"):
        helpers["save_group_workflow"]("group-one", {**saved, "description": "Stale edit"}, "editor")
    assert helpers["get_group_workflow"]("group-one", saved["id"])["name"] == "Concurrent new name"


def test_reference_authorization_failure_prevents_the_write():
    helpers, container, reads = load_group_store()

    def denied(*args, **kwargs):
        raise PermissionError("Reference access denied.")

    helpers["authorize_workflow_reference"] = denied
    with pytest.raises(PermissionError):
        helpers["save_group_workflow"]("group-one", definition(), "editor")
    assert container.items == {}


def test_runtime_updates_leave_authoring_revision_and_data_flow_unchanged():
    helpers, container, reads = load_group_store()
    saved = helpers["save_group_workflow"]("group-one", definition(), "editor")
    updated = helpers["update_group_workflow_runtime_fields"]("group-one", saved["id"], {
        "status": "running", "active_run_id": "run",
    })
    assert updated["definition_revision"] == saved["definition_revision"]
    assert updated["tasks"] == saved["tasks"]
    assert updated["active_run_id"] == "run"


def test_personal_real_save_read_and_runtime_paths_preserve_new_definition_fields():
    helpers, container, reads = load_personal_store()
    payload = definition()
    payload["reference_inputs"][0].update(scope_type="personal", scope_id="owner")
    saved = helpers["save_personal_workflow"]("owner", payload)
    assert saved["tasks"][2]["inputs"][0]["task_id"] == "extract"
    assert reads[0][2]["actor_user_id"] == "owner"
    assert helpers["get_personal_workflow"]("owner", saved["id"])["definition_revision"] == saved["definition_revision"]
    assert helpers["get_personal_workflows"]("owner")[0]["definition_revision"] == saved["definition_revision"]
    updated = helpers["update_personal_workflow_runtime_fields"]("owner", saved["id"], {"run_count": 3})
    assert updated["definition_revision"] == saved["definition_revision"]
    assert updated["run_count"] == 3
    assert container.writes == 2


def test_personal_classic_downgrade_and_stale_native_save_are_rejected():
    helpers, container, reads = load_personal_store()
    saved = helpers["save_personal_workflow"]("owner", definition())
    classic = dict(saved)
    classic.pop("definition_version")
    with pytest.raises(WorkflowDefinitionConflict, match="V2"):
        helpers["save_personal_workflow"]("owner", classic)
    helpers["save_personal_workflow"]("owner", {**saved, "name": "A new name"})
    with pytest.raises(WorkflowDefinitionConflict, match="Reload"):
        helpers["save_personal_workflow"]("owner", {**saved, "description": "Stale edit"})
    assert container.writes == 2
