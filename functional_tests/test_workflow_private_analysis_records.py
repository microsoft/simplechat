# test_workflow_private_analysis_records.py
"""
Functional tests for private Analyze records in workflow history and cleanup.
Version: 0.261.111
Implemented in: 0.261.109

Writer guards and payloads cannot appear in history, consume a public page
limit, or lose their deletion tombstones during workflow cleanup.
"""

import ast
from copy import deepcopy
from datetime import datetime, timezone
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
from azure.cosmos import exceptions


APP = Path(__file__).resolve().parents[1] / "application" / "single_app"
PRIVATE_TYPES = (
    "workflow_result_chunk", "chat_analysis_result_chunk",
    "orchestration_analysis_result_chunk", "analysis_work_unit_checkpoint", "workflow_runtime_control",
)


class Items:
    def __init__(self, records):
        self.records = {row["id"]: deepcopy(row) for row in records}
        self.queries = []
        self.deleted = []

    def read_item(self, item, partition_key):
        return deepcopy(self.records[item])

    def query_items(self, **kwargs):
        self.queries.append(kwargs)
        return [deepcopy(row) for row in self.records.values()]

    def delete_item(self, item, partition_key):
        self.deleted.append(item)
        self.records.pop(item, None)


def helpers(scope, records):
    items = Items(records)
    workflow = {"id": "workflow-1", "user_id": "owner"}
    if scope == "group":
        workflow["group_id"] = "group-1"
    cleaned = []
    admission = []
    namespace = {
        "exceptions": exceptions, "logging": logging,
        "log_event": lambda *args, **kwargs: None,
        "_strip_cosmos_metadata": lambda row: {key: value for key, value in row.items() if not key.startswith("_")},
        f"cosmos_{scope}_workflow_run_items_container": items,
        f"cosmos_{scope}_workflow_runs_container": Items([{"id": "run-1"}]),
        f"cosmos_{scope}_workflows_container": Items([workflow]),
        f"get_{scope}_workflow": lambda *args: workflow,
        "delete_workflow_run_results": lambda *args: cleaned.append(args),
        "workflow_runtime_store": lambda *args: SimpleNamespace(tombstone=lambda: admission.append("fenced")),
        "update_workflow_runtime_record": lambda *args: admission.append("deleting"),
        "datetime": datetime, "timezone": timezone,
    }
    common = ast.parse((APP / "functions_personal_workflows.py").read_text(encoding="utf-8"))
    nodes = [
        node for node in common.body
        if (isinstance(node, ast.FunctionDef) and node.name == "is_public_workflow_run_item")
        or (isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "WORKFLOW_PUBLIC_RUN_ITEMS_FILTER"
            for target in node.targets
        ))
    ]
    source = ast.parse((APP / f"functions_{scope}_workflows.py").read_text(encoding="utf-8"))
    names = {f"get_{scope}_workflow_run_item", f"list_{scope}_workflow_run_items", f"delete_{scope}_workflow"}
    nodes.extend(node for node in source.body if isinstance(node, ast.FunctionDef) and node.name in names)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "<workflow store functions>", "exec"), namespace)
    return SimpleNamespace(namespace=namespace, items=items, workflow=workflow, cleaned=cleaned, admission=admission)


@pytest.mark.parametrize("scope", ["personal", "group"])
@pytest.mark.parametrize("field", ["type", "item_type"])
def test_history_excludes_every_private_kind_before_applying_page_limits(scope, field):
    rows = [
        {"id": f"private-{index}", field: kind, "token": "fixture-token"}
        for index, kind in enumerate(PRIVATE_TYPES)
    ] + [{"id": "visible-task", "type": "workflow_task", "output_summary": "Readable result."}]
    fixture = helpers(scope, rows)
    visible = fixture.namespace[f"list_{scope}_workflow_run_items"]("run-1", limit=1)
    assert visible == [rows[-1]]
    query = fixture.items.queries[0]["query"]
    assert all(kind in query for kind in PRIVATE_TYPES)
    assert "c.item_type" in query and "c.type" in query


@pytest.mark.parametrize("scope", ["personal", "group"])
@pytest.mark.parametrize("kind", PRIVATE_TYPES)
def test_direct_item_lookup_does_not_return_private_payloads(scope, kind):
    fixture = helpers(scope, [{"id": "private", "type": kind, "token": "fixture-token"}])
    assert fixture.namespace[f"get_{scope}_workflow_run_item"]("run-1", "private") is None


@pytest.mark.parametrize("scope", ["personal", "group"])
def test_workflow_deletion_retains_the_private_writer_tombstone(scope):
    tombstone = {
        "id": "guard", "type": "analysis_work_unit_checkpoint", "item_type": "analysis_work_unit_checkpoint",
        "record_kind": "lifecycle", "deleted": True, "token": None,
    }
    fixture = helpers(scope, [tombstone, {"id": "ordinary-task", "type": "workflow_task"}])
    owner = "owner" if scope == "personal" else "group-1"
    assert fixture.namespace[f"delete_{scope}_workflow"](owner, "workflow-1") is True
    assert fixture.cleaned == [(fixture.workflow, "run-1")]
    assert fixture.items.deleted == ["ordinary-task"]
    assert fixture.items.records == {"guard": tombstone}
    assert fixture.admission == ["deleting", "fenced"]


@pytest.mark.parametrize("scope", ["personal", "group"])
def test_result_cleanup_failure_preserves_history_for_retry(scope):
    fixture = helpers(scope, [{"id": "ordinary-task", "type": "workflow_task"}])

    def fail(*args):
        raise RuntimeError("Result cleanup unavailable.")

    fixture.namespace["delete_workflow_run_results"] = fail
    with pytest.raises(RuntimeError):
        fixture.namespace[f"delete_{scope}_workflow"]("owner", "workflow-1")
    assert fixture.items.deleted == []
