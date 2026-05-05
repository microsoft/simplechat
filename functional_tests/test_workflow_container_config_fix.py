#!/usr/bin/env python3
# test_workflow_container_config_fix.py
"""
Functional test for workflow container config fix.
Version: 0.241.036
Implemented in: 0.241.029

This test ensures the workflow container exports in config.py match the
runtime imports and use user-scoped partition keys consistent with the
workflow storage helpers.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_text(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_workflow_container_config_contract():
    config_content = read_text("application/single_app/config.py")
    workflow_store_content = read_text("application/single_app/functions_personal_workflows.py")

    assert 'VERSION = "0.241.036"' in config_content, (
        "Expected config.py version 0.241.036 for the workflow container config fix."
    )
    assert "cosmos_personal_workflows_container," in workflow_store_content, (
        "Expected workflow helpers to import the plural workflows container symbol."
    )
    assert 'cosmos_personal_workflows_container_name = "personal_workflows"' in config_content, (
        "Expected config.py to export the plural workflows container name used by workflow helpers."
    )
    assert 'cosmos_personal_workflow_container_name = cosmos_personal_workflows_container_name' not in config_content, (
        "Expected config.py to use a single workflow container name without a singular alias."
    )
    assert 'cosmos_personal_workflow_container = cosmos_personal_workflows_container' not in config_content, (
        "Expected config.py to expose only the plural workflow container symbol."
    )
    assert (
        'cosmos_personal_workflows_container = cosmos_database.create_container_if_not_exists(\n'
        '    id=cosmos_personal_workflows_container_name,\n'
        '    partition_key=PartitionKey(path="/user_id")'
    ) in config_content, (
        "Expected workflow definitions to be partitioned by user_id."
    )
    assert (
        'cosmos_personal_workflow_runs_container = cosmos_database.create_container_if_not_exists(\n'
        '    id=cosmos_personal_workflow_runs_container_name,\n'
        '    partition_key=PartitionKey(path="/user_id")'
    ) in config_content, (
        "Expected workflow runs to be partitioned by user_id."
    )


if __name__ == "__main__":
    test_workflow_container_config_contract()
    print("Workflow container config checks passed.")