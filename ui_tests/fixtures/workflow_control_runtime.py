# workflow_control_runtime.py
"""
Closed API fixtures for actual M4A control-flow inspection contracts.
Version: 0.261.116
Implemented in: 0.261.116

Definitions share the authoring fixture's valid If/else, Run when and route
tree. M4A paths are empty: no invented loops, control-node approvals, or
completed runs containing pending work. Payload pages contain real serialized
JSON bytes and immutable content digests; no live service is contacted.
"""

import copy
import hashlib
import json
import re

import pytest

from ui_tests.fixtures.workflow_control_definitions import structured_workflow_record
from ui_tests.fixtures.workflow_editor import (
    GROUP_ID,
    WorkflowEditorFixture,
    connect_options,  # noqa: F401
)


V3_WORKFLOW_ID = "structured-branch-workflow"
V3_RUN_ID = "structured-run-1"
GROUP_V3_WORKFLOW_ID = "group-structured-branch-workflow"
GROUP_V3_RUN_ID = "group-structured-run-1"


def _digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def execution_id(workflow_id, run_id, node_id):
    """Opaque fixture IDs have the production digest shape, never list positions."""
    return _digest(f"{workflow_id}:{run_id}:{node_id}")


def _identity(workflow_id, run_id, node_id, attempt):
    identity = {
        "workflow_id": workflow_id, "run_id": run_id, "node_id": node_id,
        "execution_id": execution_id(workflow_id, run_id, node_id),
        "iteration_path": [], "attempt": attempt,
    }
    if node_id in {"evaluate", "accept", "review", "note", "finish"}:
        identity["task_id"] = node_id
    return identity


def _encoded(value):
    return json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":"))


def _reference(content):
    return {
        "storage": "cosmos", "schema_version": 1, "sha256": _digest(content),
        "size_bytes": len(content.encode("ascii")), "chunk_count": 1,
    }


def _output(workflow_id, run_id, node_id, attempt, *, group=False):
    identity = _identity(workflow_id, run_id, node_id, attempt)
    kind = "json" if node_id == "evaluate" else "text"
    message = f"Authoritative output excerpt from execution {identity['execution_id']} attempt {attempt}"
    value = {"pass": not group, "add_note": False, "details": f"{message}. " + "record " * 340} if kind == "json" else message
    return _encoded({
        "contract_version": "workflow-result-v2", "producer": identity,
        "output_name": kind, "kind": kind, "value": value,
    })


def _result(workflow_id, run_id, node_id, attempt, *, group=False):
    content = _output(workflow_id, run_id, node_id, attempt, group=group)
    output_name = "json" if node_id == "evaluate" else "text"
    manifest = {
        "contract_version": "workflow-result-v2", "identity": _identity(workflow_id, run_id, node_id, attempt),
        "authoritative_output": output_name,
        "outputs": {output_name: {"kind": output_name, "result_ref": _reference(content)}},
    }
    return {**manifest, "result_ref": _reference(_encoded(manifest))}


def _receipt(workflow_id, run_id, *, group=False):
    result = _result(workflow_id, run_id, "evaluate", 2, group=group)
    return {
        "input_name": "decision", "output_name": "json", "producer": result["identity"],
        "result_ref": result["result_ref"], "output_ref": result["outputs"]["json"]["result_ref"],
    }


def _pages(records, first_size):
    return {
        "": {"items": records[:first_size], "next_cursor": "page-2" if len(records) > first_size else None},
        **({"page-2": {"items": records[first_size:], "next_cursor": None}} if len(records) > first_size else {}),
    }


class WorkflowControlRuntimeFixture(WorkflowEditorFixture):
    """Small server pages exercise cursor navigation independently of UI page size."""

    def __init__(self, page):
        super().__init__(page)
        self.execution_pages = {}
        self.attempt_pages = {}
        self.decision_pages = {}
        self.execution_nodes = {}
        for scope, workflow_id, run_id in (
            ("user", V3_WORKFLOW_ID, V3_RUN_ID),
            ("group", GROUP_V3_WORKFLOW_ID, GROUP_V3_RUN_ID),
        ):
            group = scope == "group"
            record = structured_workflow_record(
                workflow_id, name="Group structured branch workflow" if group else "Structured branch workflow",
                **({"group_id": GROUP_ID} if group else {}),
            )
            record["tasks"][2]["approval"] = {"required": True, "message": "Review this selected task before execution."}
            workflows = self.group_workflows[GROUP_ID] if group else self.personal_workflows
            workflows[workflow_id] = record
            status = "waiting_approval" if group else "completed"
            self.workflow_runs[workflow_id] = [{
                "id": run_id, "workflow_id": workflow_id, "definition_version": 3,
                "status": status, "durable_execution": True,
                "started_at": "2026-09-17T14:00:00Z",
                "completed_at": None if group else "2026-09-17T14:05:00Z",
            }]
            key = (scope, workflow_id, run_id)
            runtime = {
                "schema_version": 2, "version": 12, "state": status,
                "phase": "Review approval" if group else "Completed selected path",
                "memory": {"units": [], "decisions": []},
            }
            if group:
                runtime["gate"] = {
                    "id": "review-approval-gate", "kind": "approval", "unit_id": "task:review",
                    "execution_id": execution_id(workflow_id, run_id, "review"), "node_id": "review",
                    "attempt": 1, "iteration_path": [], "input_digest": _digest("review-input"),
                    "reason": "Approval is required before the selected Review task.",
                    "choices": ["approve", "reject"],
                }
            self.workflow_runtimes[key] = runtime
            self.runtime_can_decide[key] = True
            rows = [
                ("evaluate", "task", "completed", 2, None, None),
                ("choose", "if", "completed", 1, None, {"choice": "else" if group else "then", "selected_branch": "else" if group else "then"}),
                ("accept" if group else "review", "task", "skipped", 0, "branch_not_selected", None),
                ("review" if group else "accept", "task", "waiting_approval" if group else "completed", 1, None, None),
            ]
            if not group:
                rows.extend([
                    ("decision-join", "join", "completed", 1, None, None),
                    ("bypass-note", "route", "completed", 1, None, {"choice": "route", "target_node_id": "finish"}),
                    ("note", "task", "skipped", 0, "forward_route", None),
                    ("finish", "task", "completed", 1, None, None),
                ])
            executions = []
            for index, (node_id, kind, state, attempt, reason, decision) in enumerate(rows):
                eid = execution_id(workflow_id, run_id, node_id)
                execution = {
                    "execution_id": eid, "node_id": node_id, "node_kind": kind,
                    "iteration_path": [], "region_id": "review-path" if node_id == "review" else "accepted-path" if node_id == "accept" else "root",
                    "sequence": index + 1, "state": state, "attempt": attempt,
                }
                if kind == "task":
                    execution["task_id"] = node_id
                if reason:
                    execution["reason_code"] = reason
                if decision:
                    execution["decision"] = decision
                    execution["consumed_inputs"] = [_receipt(workflow_id, run_id, group=group)]
                attempts = []
                if node_id == "evaluate":
                    attempts.append({
                        "execution_id": eid, "node_id": node_id, "task_id": node_id,
                        "attempt": 1, "state": "failed",
                    })
                if attempt and kind == "task":
                    item = {
                        "execution_id": eid, "node_id": node_id, "task_id": node_id,
                        "attempt": attempt, "state": state,
                    }
                    if state == "completed":
                        item["workflow_result"] = _result(workflow_id, run_id, node_id, attempt, group=group)
                        item["workflow_validation"] = {"version": 1, "status": "valid", "eligible": True, "reason_codes": [], "counts": {}}
                        execution.update(workflow_result=item["workflow_result"], workflow_validation=item["workflow_validation"])
                    attempts.append(item)
                self.attempt_pages[(*key, eid)] = _pages(attempts, 50)
                self.execution_nodes[(*key, eid)] = node_id
                executions.append(execution)
            self.execution_pages[key] = _pages(executions, 3 if group else 4)
            decisions = [{
                "execution_id": execution_id(workflow_id, run_id, "evaluate"), "node_id": "evaluate",
                "attempt": 1, "gate_id": "evaluate-recovery-gate", "choice": "retry",
                "input_digest": _digest("evaluate-input"), "decided_at": "2026-09-17T14:01:00Z",
            }, {
                "execution_id": execution_id(workflow_id, run_id, "choose"), "node_id": "choose",
                "attempt": 1, "choice": "else" if group else "then", "selected_branch": "else" if group else "then",
                "input_digest": _digest("decision-input"), "decided_at": "2026-09-17T14:03:00Z",
            }]
            if not group:
                decisions.append({
                    "execution_id": execution_id(workflow_id, run_id, "bypass-note"), "node_id": "bypass-note",
                    "attempt": 1, "choice": "route", "target_node_id": "finish",
                    "input_digest": _digest("route-input"), "decided_at": "2026-09-17T14:04:00Z",
                })
            self.decision_pages[key] = _pages(decisions, 1)

    def _dispatch(self, route, entry):
        if re.fullmatch(r"/api/(user|group)/workflows/[^/]+/runs/[^/]+/executions(?:/[^/]+/attempts(?:/\d+/result)?)?", entry.path):
            self._execution_resource(route, entry)
        elif re.fullmatch(r"/api/(user|group)/workflows/[^/]+/runs/[^/]+/runtime/decisions", entry.path):
            self._read_page(route, entry, self.decision_pages, "decisions")
        else:
            super()._dispatch(route, entry)

    def _key(self, entry):
        parts = entry.path.split("/")
        scope, workflow_id, run_id = parts[2], parts[4], parts[6]
        assert entry.method == "GET", entry
        assert entry.query.get("group_id") == ([GROUP_ID] if scope == "group" else None), entry
        return scope, workflow_id, run_id

    def _read_page(self, route, entry, collection, name, execution=None):
        key = self._key(entry)
        if execution is not None:
            key = (*key, execution)
        assert key in collection, f"Unexpected {name} lookup: {entry}"
        assert 1 <= int(entry.query.get("limit", ["50"])[0]) <= 100, entry
        pages = collection[key]
        cursor = entry.query.get("cursor", [""])[0]
        assert cursor in pages, f"Unexpected cursor: {entry}"
        page = copy.deepcopy(pages[cursor])
        self._json(route, {
            name: page["items"], "next_cursor": page["next_cursor"],
            "total_count": sum(len(item["items"]) for item in pages.values()),
        })

    def _execution_resource(self, route, entry):
        parts = entry.path.split("/")
        key = self._key(entry)
        if len(parts) == 8:
            self._read_page(route, entry, self.execution_pages, "executions")
        elif len(parts) == 10:
            self._read_page(route, entry, self.attempt_pages, "attempts", parts[8])
        elif len(parts) == 12 and parts[11] == "result":
            eid, attempt = parts[8], int(parts[10])
            assert (*key, eid) in self.execution_nodes, entry
            attempts = self.attempt_pages[(*key, eid)][""]["items"]
            selected = next((item for item in attempts if item["attempt"] == attempt), None)
            assert selected and selected.get("workflow_result"), f"No committed output for {entry}"
            assert entry.query.get("output") == ["authoritative"], entry
            offset = int(entry.query.get("offset", ["0"])[0])
            limit = int(entry.query.get("limit", ["2000"])[0])
            assert 0 <= offset and 1 <= limit <= 2000, entry
            content = _output(key[1], key[2], self.execution_nodes[(*key, eid)], attempt, group=key[0] == "group")
            assert offset < len(content), entry
            end = min(len(content), offset + limit)
            self._json(route, {
                "content": content[offset:end], "output_name": selected["workflow_result"]["authoritative_output"],
                "offset": offset, "next_offset": end if end < len(content) else None,
                "total_bytes": len(content), "complete": end == len(content), "sha256": _digest(content),
            })
        else:
            raise AssertionError(f"Unexpected execution route: {entry}")


@pytest.fixture
def workflow_control_ui(page):
    fixture = WorkflowControlRuntimeFixture(page)
    yield fixture
    fixture.assert_clean()
