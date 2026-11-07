# workflow_publication_completion.py
"""
Closed publication-completion API fixtures for the real V2 SPA.
Version: 0.261.118
Implemented in: 0.261.118

Reuse production definition validation and the existing scoped history fixture.
Only fictional receipt/document identities and serialized public status cross the
API boundary. No model, publication endpoint, or live document is contacted.
"""

import copy
import hashlib
import json

import pytest

from ui_tests.fixtures.workflow_control_definitions import flow_binding
from ui_tests.fixtures.workflow_control_runtime import (
    WorkflowControlRuntimeFixture,
    execution_id,
)
from ui_tests.fixtures.workflow_editor import (
    GROUP_ID,
    connect_options,  # noqa: F401
    editor_options,
    workflow_record,
)


PUBLICATION_WORKFLOW_ID = "publication-completion"
PUBLICATION_RUN_ID = "publication-run"
GROUP_PUBLICATION_WORKFLOW_ID = "group-publication-completion"
GROUP_PUBLICATION_RUN_ID = "group-publication-run"


def publication_key(scope="user"):
    return (
        (scope, GROUP_PUBLICATION_WORKFLOW_ID, GROUP_PUBLICATION_RUN_ID)
        if scope == "group" else (scope, PUBLICATION_WORKFLOW_ID, PUBLICATION_RUN_ID)
    )


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def publication_status(scope="personal", **overrides):
    status = {
        "version": 1,
        "id": digest(f"fixture-receipt:{scope}"),
        "document_id": f"published-{scope}-document",
        "document_version": 1,
        "destination": {
            "workspace_scope": scope,
            **({"group_id": GROUP_ID} if scope == "group" else {}),
            **({"public_workspace_id": "public-handbook"} if scope == "public" else {}),
        },
        "completion_policy": "indexed_ready",
        "policy_satisfied": False,
        "state": "waiting_approval" if scope != "personal" else "waiting_processing",
        "submission": "confirmed",
        "approval": "pending" if scope != "personal" else "not_required",
        "processing": "not_started" if scope != "personal" else "queued",
        "screening": "not_required",
        "index": "pending",
        "reason_code": "publication_waiting_approval" if scope != "personal" else "publication_waiting_processing",
        "retryable": False,
        "unresolved_stages": ["approval"] if scope != "personal" else ["processing"],
    }
    status.update(copy.deepcopy(overrides))
    return status


def publication_workflow_record(scope="user"):
    _, workflow_id, _ = publication_key(scope)
    shared = scope == "group"
    tasks = [
        {
            "id": task_id, "type": "instructions", "name": name,
            "instructions": instructions, "order": index + 1,
            "runner": {"type": "inherit"}, "reference_ids": [], "inputs": [],
            "document_action": {"type": "none"},
            "output_contract": {"kind": "json", "allow_partial": False, "require_complete_coverage": False},
        }
        for index, (task_id, name, instructions) in enumerate([
            ("analyze", "Analyze source", "Analyze the selected source and save its native artifact."),
            ("publish", "Publish artifact", "Publish the existing analysis artifact without invoking a model."),
        ])
    ]
    tasks[0]["document_action"] = {
        "type": "analyze", "doc_scope": "group" if shared else "personal",
        "document_ids": ["group-brief" if shared else "personal-brief"],
        **({"active_group_ids": [GROUP_ID]} if shared else {}),
    }
    tasks[1]["inputs"] = [flow_binding("analysis", "analyze", "authoritative", kind="any")]
    tasks[1]["publication"] = {
        "artifact_format": "md", "workspace_scope": "group" if shared else "personal",
        "completion_policy": "indexed_ready",
        **({"group_id": GROUP_ID} if shared else {}),
    }
    return workflow_record(
        workflow_id, name="Group publication workflow" if shared else "Publication workflow",
        definition_version=3, durable_execution=True, tasks=tasks,
        flow={
            "id": "root",
            "nodes": [{"id": task["id"], "kind": "task", "task_id": task["id"]} for task in tasks],
            "outputs": [flow_binding("publication", "publish")],
        },
        limits={"max_executions": 5000, "deadline_seconds": 86400},
        **({"group_id": GROUP_ID} if shared else {}),
    )


class WorkflowPublicationFixture(WorkflowControlRuntimeFixture):
    """Publication authoring plus exact run/attempt pages on a closed boundary."""

    def __init__(self, page):
        super().__init__(page)
        self.publication_policies = ["submitted", "approved", "indexed_ready"]
        self.stale_publication_decision = False
        self.publication_outputs = {}
        self.personal_workflows = {PUBLICATION_WORKFLOW_ID: publication_workflow_record()}
        self.group_workflows[GROUP_ID] = {GROUP_PUBLICATION_WORKFLOW_ID: publication_workflow_record("group")}
        for scope in ("user", "group"):
            self.set_publication_status(publication_status("group" if scope == "group" else "personal"), scope=scope)

    def set_publication_status(self, status, *, scope="user", attempt=1):
        key = publication_key(scope)
        _, workflow_id, run_id = key
        eid = execution_id(workflow_id, run_id, "publish")
        state = "completed" if status["policy_satisfied"] else (
            "waiting_output" if status["state"].startswith("waiting_") else "paused"
        )
        runtime = {
            "schema_version": 2, "version": self.workflow_runtimes.get(key, {}).get("version", 4) + 1, "state": state,
            "phase": "Publication checkpoint", "progress": {"completed": 1, "total": 2},
            "memory": {"unit_count": 2, "decision_count": 0},
        }
        if state != "completed":
            runtime["gate"] = {
                "id": digest(f"{eid}:gate:{attempt}"),
                "kind": "output" if state == "waiting_output" else "pause",
                "unit_id": "task:publish", "execution_id": eid, "node_id": "publish",
                "attempt": attempt, "iteration_path": [], "input_digest": digest(f"{eid}:input"),
                "choices": [] if state == "waiting_output" else (
                    ["resume", "cancel"] if status["retryable"] else ["cancel"]
                ),
                "reason": "The requested publication completion level has not been met.",
                "publication": copy.deepcopy(status),
            }
        self.workflow_runtimes[key] = runtime
        self.runtime_can_decide[key] = True
        self.workflow_runs[workflow_id] = [{
            "id": run_id, "workflow_id": workflow_id, "definition_version": 3,
            "status": state, "durable_execution": True,
            "started_at": "2026-09-18T12:00:00Z",
            "completed_at": "2026-09-18T12:05:00Z" if state == "completed" else None,
        }]
        workflow = self.group_workflows[GROUP_ID][workflow_id] if scope == "group" else self.personal_workflows[workflow_id]
        workflow["status"] = state
        workflow["active_run_id"] = run_id if state != "completed" else None
        workflow["tasks"][1]["publication"] = {
            "artifact_format": "md", **copy.deepcopy(status["destination"]),
            "completion_policy": status["completion_policy"],
        }
        result = {"publication": copy.deepcopy(status)}
        if state == "completed":
            identity = {
                "workflow_id": workflow_id, "run_id": run_id, "node_id": "publish",
                "task_id": "publish", "execution_id": eid, "iteration_path": [], "attempt": attempt,
            }
            content = json.dumps({
                "contract_version": "workflow-result-v2", "producer": identity,
                "output_name": "json", "kind": "json", "value": {"publication": status},
            }, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
            self.publication_outputs[(*key, eid, attempt)] = content
            result.update(
                authoritative_output="json", outputs={"json": {"kind": "json"}},
                result_ref={
                    "storage": "cosmos", "schema_version": 1,
                    "sha256": digest(content), "size_bytes": len(content), "chunk_count": 1,
                },
            )
        record = {
            "execution_id": eid, "node_id": "publish", "node_kind": "task", "task_id": "publish",
            "iteration_path": [], "region_id": "root", "sequence": 2, "state": state,
            "attempt": attempt, "workflow_result": result,
        }
        self.execution_pages[key] = {"": {"items": [copy.deepcopy(record)], "next_cursor": None}}
        self.attempt_pages[(*key, eid)] = {"": {"items": [copy.deepcopy(record)], "next_cursor": None}}
        self.execution_nodes[(*key, eid)] = "publish"
        self.decision_pages[key] = {"": {"items": [], "next_cursor": None}}

    def _dispatch(self, route, entry):
        if entry.path in {"/api/user/workflows/editor-options", "/api/group/workflows/editor-options"}:
            assert entry.method == "GET", entry
            shared = entry.path.startswith("/api/group/")
            assert entry.query.get("group_id") == ([GROUP_ID] if shared else None), entry
            options = editor_options("group" if shared else "personal", GROUP_ID if shared else None)
            if self.publication_policies is not None:
                options["supported_publication_completion_policies"] = copy.deepcopy(self.publication_policies)
            self._json(route, options)
        else:
            super()._dispatch(route, entry)

    def _execution_resource(self, route, entry):
        if not entry.path.endswith("/result"):
            super()._execution_resource(route, entry)
            return
        key = self._key(entry)
        parts = entry.path.split("/")
        eid, attempt = parts[8], int(parts[10])
        assert (*key, eid, attempt) in self.publication_outputs, entry
        assert entry.query.get("output") == ["authoritative"], entry
        content = self.publication_outputs[(*key, eid, attempt)]
        offset = int(entry.query.get("offset", ["0"])[0])
        limit = int(entry.query.get("limit", ["2000"])[0])
        assert 0 <= offset < len(content) and 1 <= limit <= 2000, entry
        end = min(len(content), offset + limit)
        self._json(route, {
            "content": content[offset:end], "output_name": "json", "offset": offset,
            "next_offset": end if end < len(content) else None,
            "total_bytes": len(content), "complete": end == len(content), "sha256": digest(content),
        })

    def _workflow_runtime(self, route, entry):
        if entry.method == "POST" and entry.path.endswith("/decision"):
            parts = entry.path.split("/")
            key = (parts[2], parts[4], parts[6])
            assert key == publication_key(parts[2]), entry
            runtime = self.workflow_runtimes[key]
            assert set(entry.body) == {"expected_version", "gate_id", "choice", "request_id"}, entry
            assert entry.body["choice"] in {"resume", "cancel"}, entry
            if self.stale_publication_decision:
                self.stale_publication_decision = False
                runtime["version"] += 1
                runtime["gate"]["id"] = digest(f"{runtime['gate']['id']}:refreshed")
            if entry.body["expected_version"] != runtime["version"] or entry.body["gate_id"] != runtime["gate"]["id"]:
                self._json(route, {"error": "Runtime changed. Review the current gate."}, 409)
                return
            assert entry.body["choice"] in runtime["gate"]["choices"], entry
        super()._workflow_runtime(route, entry)


@pytest.fixture
def publication_ui(page):
    fixture = WorkflowPublicationFixture(page)
    yield fixture
    fixture.assert_clean()
