# workflow_flow.py
"""
Closed production-bundle fixtures for read-only M5A Flow inspection.
Version: 0.261.127
Implemented in: 0.261.121

The shared fixture serves only local static assets and fictional API responses.
Topology, preview, details and execution identities use the real pure Python
helpers. Only data-only preview and explicit group-selection requests are allowed;
workflow and unrelated preference mutations remain rejected.
"""

import copy
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from ui_tests.fixtures.workflow_control_definitions import flow_binding, structured_workflow_record
from ui_tests.fixtures.workflow_editor import GROUP_ID, SECOND_GROUP_ID, WORKFLOW_ID, workflow_record
from ui_tests.fixtures.workflow_loops import loop_item, record_contract
from ui_tests.fixtures.workflow_repeat_until import WorkflowRepeatFixture, bounded_pages, state_binding, state_contract
from ui_tests.fixtures.workspace_authoring import OWNER_ID

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "application" / "single_app"))

# Production imports follow the application path setup and initialize no clients.
import functions_workflow_inspection as inspection
from functions_workflow_definitions import WorkflowDefinitionConflict, WorkflowDefinitionError, workflow_definition_revision
from functions_workflow_flow import compile_workflow_flow
from functions_workflow_identity import canonical_digest, workflow_execution_id


FLOW_WORKFLOW_ID = "flow-inspection-workflow"
FLOW_RUN_ID = "flow-frozen-run"
FLOW_NAME = "Read-only branch review"
MIXED_WORKFLOW_ID = "flow-mixed-loops"
MIXED_RUN_ID = "flow-mixed-run"
MIXED_NAME = "Nested instance review"
MALICIOUS_LABEL = '<img src=x onerror="window.flowLabelExecuted=true">'


def flow_workflow_record(*, group_id=None, name=FLOW_NAME):
    record = structured_workflow_record(
        FLOW_WORKFLOW_ID, name=name, user_id=OWNER_ID,
        **({"group_id": group_id} if group_id else {}),
    )
    # Catalogue order intentionally disagrees with executable region order.
    record["tasks"].reverse()
    for index, task in enumerate(record["tasks"], 1):
        task["order"] = index
    record["definition_revision"] = workflow_definition_revision(record)
    return record


def mixed_workflow_record(kinds=("repeat_until", "for_each", "repeat_until"), *, group_id=None):
    """Real depth-four compiler syntax, never one node per item or lifetime round."""
    seed_json = {
        "id": "seed-decision-task", "name": "Seed decision", "type": "instructions",
        "instructions": "Return the typed initial decision; never execute this fixture.",
        "order": 1, "runner": {"type": "inherit"}, "inputs": [], "reference_ids": [],
        "document_action": {"type": "none"}, "output_contract": state_contract("json"),
    }
    seed_records = {
        **copy.deepcopy(seed_json), "id": "seed-records-task", "name": "Seed findings", "order": 2,
        "output_contract": record_contract(),
    }
    leaf = {
        **copy.deepcopy(seed_records), "id": "inspect-record-task", "name": "Inspect exact finding", "order": 3,
        "instructions": "FROZEN_INSTRUCTIONS: preserve false, zero, null, duplicates and complete records.",
        "inputs": [],
    }
    loop_ids = [f"loop-{index}" for index in range(len(kinds))]
    for kind, loop_id in zip(kinds, loop_ids):
        leaf["inputs"].append(
            loop_item(f"item_{loop_id.replace('-', '_')}", loop_id) if kind == "for_each"
            else state_binding(f"state_{loop_id.replace('-', '_')}", "review", "json", loop_id)
        )

    def build(index):
        if index == len(kinds):
            return [{"id": "inspect-record", "kind": "task", "task_id": leaf["id"]}], "inspect-record", "records"
        children, producer_id, output = build(index + 1)
        loop_id, kind = loop_ids[index], kinds[index]
        body = {
            "id": f"body-{index}", "nodes": children,
            "outputs": [flow_binding("findings", producer_id, output, kind="records")],
        }
        if kind == "for_each":
            loop = {
                "id": loop_id, "kind": kind, "max_items": 5000, "item_key": "source_identity",
                "inputs": [flow_binding("rows", "seed-records", "records", kind="records")],
                "iterable": {"kind": "input", "name": "rows"}, "body": body,
            }
            collect_id = f"collect-{index}"
            return [loop, {
                "id": collect_id, "kind": "collect", "source": {"loop_id": loop_id, "output": "findings"},
                "output_contract": record_contract(),
            }], collect_id, "records"
        body["outputs"].append(state_binding("next_review", "review", "json", loop_id))
        loop = {
            "id": loop_id, "kind": kind, "max_iterations": 1000 if index == 0 else 1,
            "state": [{
                "name": "review", "initial": flow_binding("review", "seed-decision", "json")["source"],
                "next": "next_review", "output_contract": state_contract("json"),
            }],
            "body": body,
            "until": {"op": "eq", "left": {"input": "review", "path": "/ready"}, "right": {"literal": True}},
            "exports": [{"name": "findings", "output": "findings"}, {"name": "review", "output": "next_review"}],
        }
        return [loop], loop_id, "findings"

    children, producer, output = build(0)
    record = workflow_record(
        MIXED_WORKFLOW_ID, name=MIXED_NAME, definition_version=3, durable_execution=True,
        user_id=OWNER_ID, tasks=[seed_records, leaf, seed_json], reference_inputs=[],
        chat_capabilities_enabled=False, limits={"max_executions": 5000, "deadline_seconds": 86400},
        flow={
            "id": "root",
            "nodes": [
                {"id": "seed-decision", "kind": "task", "task_id": seed_json["id"]},
                {"id": "seed-records", "kind": "task", "task_id": seed_records["id"]}, *children,
            ],
            "outputs": [flow_binding("findings", producer, output, kind="records")],
        },
        **({"group_id": group_id} if group_id else {}),
    )
    compile_workflow_flow(record)
    record["definition_revision"] = workflow_definition_revision(record)
    return record


class WorkflowFlowFixture(WorkflowRepeatFixture):
    """Keep all existing history fixtures unchanged; add only closed Flow reads."""

    def __init__(self, page):
        super().__init__(page)
        self.inspection = inspection
        self.flow_definitions = {}
        self.exact_executions = {}
        self.loop_pages = {}
        self.flow_attempts = {}
        self.flow_records = {}
        self.flow_payloads = []
        self.held_flow_responses = []
        self.flow_response_gates = []
        self.group_can_manage = True
        self.legacy_workflow = workflow_record(
            "flow-legacy-v1", name="Legacy version one", definition_version=1,
            tasks=[], task_prompt="Keep the legacy prompt unchanged.",
        )
        self.personal_workflows = {
            FLOW_WORKFLOW_ID: flow_workflow_record(),
            WORKFLOW_ID: self.personal_workflows[WORKFLOW_ID],
            self.legacy_workflow["id"]: self.legacy_workflow,
        }
        self.group_workflows = {
            GROUP_ID: {FLOW_WORKFLOW_ID: flow_workflow_record(group_id=GROUP_ID, name="Alpha read-only Flow")},
            SECOND_GROUP_ID: {FLOW_WORKFLOW_ID: flow_workflow_record(group_id=SECOND_GROUP_ID, name="Beta read-only Flow")},
        }
        self._seed_branch_history()
        self._seed_group_history()
        self.seed_mixed()

    @property
    def preview_requests(self):
        return [entry for entry in self.requests if entry.path.endswith("/flow-preview")]

    @property
    def topology_requests(self):
        return [
            entry for entry in self.requests
            if entry.path.endswith("/flow") and "node_id" not in entry.query
        ]

    @property
    def detail_requests(self):
        return [entry for entry in self.requests if entry.path.endswith("/flow") and "node_id" in entry.query]

    @property
    def exact_requests(self):
        return [entry for entry in self.requests if entry.path.endswith("/executions") and "node_id" in entry.query]

    @property
    def evidence_requests(self):
        return [
            entry for entry in self.requests
            if re.search(r"/(?:attempts|result|records|provenance|iterations|state|items)(?:/|$)", entry.path)
        ]

    def _execution_node(self, key, node_id):
        compiled = compile_workflow_flow(self.flow_definitions[key])
        if node_id == compiled["flow"]["id"]:
            return {"node": {"id": node_id, "kind": "root"}, "region_id": node_id}
        assert node_id in compiled["nodes"], f"The selected structural node {node_id} has no execution identity."
        return compiled["nodes"][node_id]

    def execution_for(self, workflow_id, run_id, node_id, path, *, scope="user"):
        key = (scope, workflow_id, run_id)
        self._execution_node(key, node_id)
        frozen = self.flow_definitions[key]
        return workflow_execution_id(frozen, run_id, node_id, path)

    def _add_execution(self, key, node_id, path, *, state="completed", attempt=1, records=None):
        frozen = self.flow_definitions[key]
        compiled_node = self._execution_node(key, node_id)
        node = compiled_node["node"]
        execution_id = workflow_execution_id(frozen, key[2], node_id, path)
        entry = {
            "execution_id": execution_id, "node_id": node_id, "node_kind": node["kind"],
            "region_id": compiled_node["region_id"],
            "iteration_path": copy.deepcopy(path), "state": state, "attempt": attempt,
        }
        if node["kind"] == "task":
            entry["task_id"] = node["task_id"]
        if records is not None:
            identity = {
                "workflow_id": key[1], "run_id": key[2], "execution_id": execution_id,
                "node_id": node_id, "task_id": node["task_id"], "iteration_path": copy.deepcopy(path), "attempt": attempt,
            }
            reference = {
                "storage": "cosmos", "schema_version": 1, "size_bytes": 1024,
                "sha256": canonical_digest(records), "chunk_count": 1,
            }
            entry["workflow_result"] = {
                "contract_version": "workflow-result-v2", "producer": identity,
                "authoritative_output": "records", "outputs": {"records": {"kind": "records", "result_ref": reference}},
                "result_ref": reference,
            }
            entry["workflow_validation"] = {
                "version": 1, "status": "valid", "eligible": True, "reason_codes": [], "counts": {"records": len(records)},
            }
            self.flow_records[(*key, execution_id, attempt)] = copy.deepcopy(records)
        self.exact_executions[(*key, execution_id)] = copy.deepcopy(entry)
        attempts = []
        if attempt > 1:
            attempts.append({
                "execution_id": execution_id, "node_id": node_id, "node_kind": node["kind"],
                "iteration_path": copy.deepcopy(path), "attempt": 1, "state": "failed",
                **({"task_id": node["task_id"]} if node["kind"] == "task" else {}),
            })
        if attempt > 0:
            attempts.append(copy.deepcopy(entry))
        self.flow_attempts[(*key, execution_id)] = attempts
        return entry

    def _seed_branch_history(self):
        key = ("user", FLOW_WORKFLOW_ID, FLOW_RUN_ID)
        frozen = copy.deepcopy(self.personal_workflows[FLOW_WORKFLOW_ID])
        task = next(task for task in frozen["tasks"] if task["id"] == "evaluate")
        task["name"] = "Frozen evaluation"
        task["instructions"] = "FROZEN_INSTRUCTIONS: evaluate the original admitted decision."
        frozen["definition_revision"] = workflow_definition_revision(frozen)
        self.flow_definitions[key] = frozen
        first = self._add_execution(key, "evaluate", [], attempt=2)
        skipped = self._add_execution(key, "review", [], state="skipped", attempt=0)
        skipped["reason_code"] = "branch_not_selected"
        self.exact_executions[(*key, skipped["execution_id"])] = skipped
        self.execution_pages[key] = {
            "": {"items": [first], "next_cursor": "later-unloaded-executions"},
            "later-unloaded-executions": {"items": [skipped], "next_cursor": None},
        }
        self.decision_pages[key] = bounded_pages([], 50)
        self.workflow_runs[FLOW_WORKFLOW_ID] = [{
            "id": FLOW_RUN_ID, "workflow_id": FLOW_WORKFLOW_ID, "definition_version": 3,
            "definition_revision": frozen["definition_revision"], "durable_execution": True,
            "status": "completed", "started_at": "2026-09-19T12:00:00Z",
        }]
        self.workflow_runtimes[key] = {
            "schema_version": 2, "version": 12, "state": "completed",
            "memory": {"execution_count": 2, "decision_count": 0},
        }
        self.runtime_can_decide[key] = False
        live = next(task for task in self.personal_workflows[FLOW_WORKFLOW_ID]["tasks"] if task["id"] == "evaluate")
        live["name"] = "Later live evaluation"
        live["instructions"] = "LIVE_ONLY_INSTRUCTIONS: a different revision reuses the same node id."
        self.personal_workflows[FLOW_WORKFLOW_ID]["definition_revision"] = workflow_definition_revision(
            self.personal_workflows[FLOW_WORKFLOW_ID],
        )

    def _seed_group_history(self):
        key = ("group", FLOW_WORKFLOW_ID, FLOW_RUN_ID)
        frozen = copy.deepcopy(self.group_workflows[GROUP_ID][FLOW_WORKFLOW_ID])
        task = next(task for task in frozen["tasks"] if task["id"] == "evaluate")
        task["name"] = "Frozen group evaluation"
        task["instructions"] = "FROZEN_GROUP_INSTRUCTIONS: the exact authorized group revision."
        frozen["definition_revision"] = workflow_definition_revision(frozen)
        self.flow_definitions[key] = frozen
        entry = self._add_execution(key, "evaluate", [], attempt=2)
        self.execution_pages[key] = bounded_pages([entry], 50)
        self.decision_pages[key] = bounded_pages([], 50)
        self.workflow_runtimes[key] = {
            "schema_version": 2, "version": 7, "state": "completed",
            "memory": {"execution_count": 1, "decision_count": 0},
        }
        self.runtime_can_decide[key] = False

    def seed_mixed(self, kinds=("repeat_until", "for_each", "repeat_until")):
        definition = mixed_workflow_record(kinds)
        self.personal_workflows[MIXED_WORKFLOW_ID] = copy.deepcopy(definition)
        key = ("user", MIXED_WORKFLOW_ID, MIXED_RUN_ID)
        for collection in (self.exact_executions, self.loop_pages, self.flow_attempts, self.flow_records):
            for identity in tuple(collection):
                if identity[:3] == key:
                    del collection[identity]
        self.flow_definitions[key] = copy.deepcopy(definition)
        self.workflow_runs[MIXED_WORKFLOW_ID] = [{
            "id": MIXED_RUN_ID, "workflow_id": MIXED_WORKFLOW_ID, "definition_version": 3,
            "definition_revision": definition["definition_revision"], "durable_execution": True,
            "status": "completed", "started_at": "2026-09-19T12:00:00Z",
        }]
        self.workflow_runtimes[key] = {
            "schema_version": 2, "version": 20, "state": "completed",
            "memory": {"execution_count": 4010, "decision_count": 1001},
        }
        self.runtime_can_decide[key] = False
        self.decision_pages[key] = bounded_pages([], 50)
        self._add_execution(key, "seed-decision", [])
        path = []
        self.mixed_frames = []
        outer = None
        for index, kind in enumerate(kinds):
            node_id = f"loop-{index}"
            execution = self._add_execution(key, node_id, path)
            outer = outer or execution
            execution_id = execution["execution_id"]
            if kind == "repeat_until":
                iteration = 1000 if index == kinds.index("repeat_until") else 0
                frame = {"loop_id": node_id, "iteration": iteration}
                size = 1000 if index == 0 else 1
                summary = {
                    "execution_id": execution_id, "node_id": node_id,
                    "completed_iteration": iteration, "next_iteration": iteration + 1,
                    "batch_number": iteration // size, "batch_size": size, "batch_usage": iteration % size + 1,
                    "completed_count": iteration + 1, "exhaustion_count": iteration // size,
                    "continuation_count": iteration // size, "state": "completed", "partial": False,
                }
                payload = {
                    "repeat_execution_id": execution_id, "repeat": summary, "source_snapshot_changed": False,
                    "iterations": [{
                        "iteration": iteration, "iteration_path": [*copy.deepcopy(path), frame],
                        "batch_number": summary["batch_number"], "batch_size": size, "batch_usage": summary["batch_usage"],
                        "state": "completed", "condition_result": True, "partial": False,
                        "before_available": True, "after_available": True, "execution_ids": [],
                    }],
                    "next_cursor": None, "total_count": iteration + 1,
                }
            else:
                frame = {"loop_id": node_id, "item_id": canonical_digest({"loop": node_id, "path": path}), "index": 0}
                payload = {
                    "loop_execution_id": execution_id, "frozen_at": "2026-09-19T12:00:00Z",
                    "items": [{
                        "item_id": frame["item_id"], "index": frame["index"], "label": "Exact frozen finding",
                        "state": "completed", "iteration_path": [*copy.deepcopy(path), frame],
                        "execution_ids": [], "record_count": 2,
                    }],
                    "next_cursor": "more-frozen-items", "total_count": 5000, "limit": 5000,
                }
            self.loop_pages[(*key, execution_id)] = payload
            path.append(frame)
            self.mixed_frames.append(copy.deepcopy(frame))
        rows = [
            {"finding": "Frozen exact row", "zero": 0, "flag": False, "nested": {"nil": None}},
            {"finding": "Frozen exact row", "zero": 0, "flag": False, "nested": {"nil": None}},
        ]
        self._add_execution(key, "inspect-record", path, attempt=2, records=rows)
        self.execution_pages[key] = {"": {"items": [outer], "next_cursor": "not-automatically-loaded"}}

    def hold_next_flow(self, *, source_kind=None, node_id=None, group_id=None):
        self.flow_response_gates.append({"source_kind": source_kind, "node_id": node_id, "group_id": group_id})

    def hold_next_read(self, path, *, query=None):
        assert re.match(r"/api/(user|group)/workflows/", path), path
        self.flow_response_gates.append({"path": path, "query": copy.deepcopy(query or {})})

    def release_flow_responses(self):
        held, self.held_flow_responses = self.held_flow_responses, []
        for route, payload, status in held:
            super()._json(route, payload, status)

    def _json(self, route, payload, status=200):
        if isinstance(payload, dict) and payload.get("projection_version") == 1:
            self.flow_payloads.append(copy.deepcopy(payload))
        for index, gate in enumerate(self.flow_response_gates):
            if "path" in gate:
                url = urlsplit(route.request.url)
                query = parse_qs(url.query)
                matches = route.request.method == "GET" and url.path == gate["path"] and all(
                    query.get(name) == value for name, value in gate["query"].items()
                )
            else:
                source = payload.get("source") if isinstance(payload, dict) else None
                matches = isinstance(source, dict) and (
                    (gate["source_kind"] is None or gate["source_kind"] == source["kind"])
                    and (gate["node_id"] is None or gate["node_id"] == payload.get("node_id"))
                    and (gate["group_id"] is None or gate["group_id"] == source["scope_id"])
                )
            if matches:
                self.flow_response_gates.pop(index)
                self.held_flow_responses.append((route, copy.deepcopy(payload), status))
                return
        super()._json(route, payload, status)

    def _flow_resource(self, route, entry):
        scope = entry.path.split("/")[2]
        group_id = entry.query.get("group_id", [None])[0]
        assert group_id in self.group_workflows if scope == "group" else group_id is None, entry
        selectors = {
            name: entry.body[name] if entry.method == "POST" else entry.query[name][0]
            for name in ("node_id", "section", "revision", "cursor", "limit")
            if name in (entry.body if entry.method == "POST" else entry.query)
        }
        if "node_id" in selectors:
            if entry.method == "POST":
                assert type(selectors.get("limit")) is int and selectors["limit"] == 50, entry
            else:
                assert selectors.get("limit") == "50", entry
            assert "revision" in selectors and "section" in selectors, entry
        if "limit" in selectors:
            selectors["limit"] = int(selectors["limit"])
        try:
            if entry.method == "POST":
                assert entry.path.endswith("/flow-preview"), entry
                assert set(entry.body) <= {"definition", "node_id", "section", "revision", "cursor", "limit"}, entry
                payload = self.inspection.preview_workflow_flow(
                    entry.body["definition"], user_id=OWNER_ID, group_id=group_id, **selectors,
                )
            else:
                parts = entry.path.split("/")
                workflow_id = parts[4]
                if len(parts) == 8:
                    key = (scope, workflow_id, parts[6])
                    assert key in self.flow_definitions, f"No frozen fixture definition: {entry}"
                    payload = self.inspection.workflow_flow_inspection(
                        self.flow_definitions[key], source_kind="run", run_id=key[2],
                        snapshot_sha256=canonical_digest(self.flow_definitions[key]), **selectors,
                    )
                else:
                    workflows = self.group_workflows[group_id] if group_id else self.personal_workflows
                    assert workflow_id in workflows, entry
                    payload = self.inspection.workflow_flow_inspection(workflows[workflow_id], **selectors)
            self._json(route, payload)
        except WorkflowDefinitionConflict as error:
            self._json(route, {"error": error.public_message, "code": "workflow_flow_revision_changed"}, 409)
        except WorkflowDefinitionError as error:
            self._json(route, {"error": error.public_message, "code": "invalid_workflow_definition"}, 400)

    def _flow_execution_resource(self, route, entry):
        parts = entry.path.split("/")
        key = self._key(entry)
        if len(parts) == 8:
            assert set(entry.query) <= {"group_id", "node_id", "iteration_path", "limit"}, entry
            assert entry.query.get("limit") == ["1"] and "iteration_path" in entry.query, entry
            node_id = entry.query["node_id"][0]
            path = json.loads(entry.query["iteration_path"][0])
            execution_id = self.execution_for(key[1], key[2], node_id, path, scope=key[0])
            saved = self.exact_executions.get((*key, execution_id))
            self._json(route, {"executions": [saved] if saved else [], "next_cursor": None, "total_count": int(saved is not None)})
            return
        execution_id, resource = parts[8], parts[-1]
        assert (*key, execution_id) in self.exact_executions, entry
        if resource == "attempts":
            assert entry.query.get("limit") == ["50"] and "cursor" not in entry.query, entry
            attempts = self.flow_attempts[(*key, execution_id)]
            self._json(route, {"attempts": attempts, "next_cursor": None, "total_count": len(attempts)})
        elif resource in {"items", "iterations"}:
            assert entry.query.get("limit") == ["50"] and "cursor" not in entry.query, entry
            self._json(route, copy.deepcopy(self.loop_pages[(*key, execution_id)]))
        elif resource == "state":
            assert entry.query.get("limit") == ["50"] and "cursor" not in entry.query, entry
            phase = entry.query.get("phase", [None])[0]
            iteration = int(parts[10])
            assert phase in {"before", "after"}, entry
            rounds = self.loop_pages[(*key, execution_id)]["iterations"]
            assert any(item["iteration"] == iteration for item in rounds), entry
            self._json(route, {
                "repeat_execution_id": execution_id, "iteration": iteration, "phase": phase,
                "available": True, "partial": False, "source_snapshot_changed": False,
                "states": [{
                    "name": "review", "kind": "json",
                    "source": {
                        "node_id": "seed-decision",
                        "execution_id": self.execution_for(key[1], key[2], "seed-decision", [], scope=key[0]),
                        "iteration_path": [], "attempt": 1, "output_name": "json",
                    },
                    "workflow_validation": {"version": 1, "status": "valid", "eligible": True, "reason_codes": [], "counts": {}},
                    "coverage": {}, "limitations": [],
                }],
                "total_count": 1, "next_cursor": None,
            })
        elif resource in {"records", "result"}:
            attempt = int(parts[10])
            assert (*key, execution_id, attempt) in self.flow_records, entry
            assert entry.query.get("output") in (["records"], ["authoritative"]), entry
            rows = self.flow_records[(*key, execution_id, attempt)]
            if resource == "records":
                assert entry.query.get("limit") == ["100"] and "cursor" not in entry.query, entry
                self._json(route, {
                    "records": rows, "record_offset": 0, "total_count": len(rows), "next_cursor": None,
                    "output_name": entry.query["output"][0],
                    "workflow_validation": {"version": 1, "status": "valid", "eligible": True, "reason_codes": [], "counts": {}},
                    "coverage": {"complete": True, "record_count": len(rows)},
                })
            else:
                assert entry.query.get("limit") == ["2000"], entry
                content = json.dumps({"kind": "records", "value": rows}, ensure_ascii=True, separators=(",", ":"))
                self._json(route, {
                    "content": content, "offset": 0, "next_offset": None, "total_bytes": len(content),
                    "output_name": "records", "complete": True, "sha256": hashlib.sha256(content.encode("ascii")).hexdigest(),
                })
        else:
            raise AssertionError(f"Unexpected eager Flow evidence read: {entry}")

    def _dispatch(self, route, entry):
        if (entry.method, entry.path) == ("PATCH", "/api/groups/setActive"):
            super()._dispatch(route, entry)
        elif entry.method != "GET" and not (entry.method == "POST" and entry.path.endswith("/flow-preview")):
            self.unexpected_requests.append(f"Read-only Flow issued a mutation: {entry}")
            self._json(route, {"error": "Read-only fixture rejects workflow and preference mutations."}, 405)
        elif re.fullmatch(r"/api/(user|group)/workflows(?:/flow-preview|/[^/]+(?:/runs/[^/]+)?/flow)", entry.path):
            self._flow_resource(route, entry)
        elif (
            re.fullmatch(r"/api/(user|group)/workflows/[^/]+/runs/[^/]+/executions(?:/.*)?", entry.path)
            and (entry.query.get("node_id") or len(entry.path.split("/")) > 8)
            and tuple(entry.path.split("/")[index] for index in (2, 4, 6)) in self.flow_definitions
        ):
            self._flow_execution_resource(route, entry)
        elif entry.path == "/api/groups":
            self._json(route, {
                "groups": [
                    {"id": group_id, "name": name, "userRole": "Admin" if self.group_can_manage else "User"}
                    for group_id, name in ((GROUP_ID, "Alpha Group"), (SECOND_GROUP_ID, "Beta Group"))
                ],
                "page": 1, "page_size": 25, "total_count": 2,
            })
        elif entry.path == "/api/group/workflows":
            group_id = entry.query.get("group_id", [None])[0]
            assert group_id in self.group_workflows, entry
            self._json(route, {"workflows": list(self.group_workflows[group_id].values())})
        elif entry.path == f"/api/group/workflows/{FLOW_WORKFLOW_ID}/runs":
            assert entry.query.get("group_id") == [GROUP_ID], entry
            frozen = self.flow_definitions[("group", FLOW_WORKFLOW_ID, FLOW_RUN_ID)]
            self._json(route, {"runs": [{
                "id": FLOW_RUN_ID, "workflow_id": FLOW_WORKFLOW_ID, "definition_version": 3,
                "definition_revision": frozen["definition_revision"], "durable_execution": True,
                "status": "completed", "started_at": "2026-09-19T12:00:00Z",
            }]})
        elif entry.path in {"/api/group/agents", "/api/group/plugins", "/api/plugins/agent-targets"}:
            assert entry.query.get("group_id", [None])[0] in self.group_workflows, entry
            self._json(route, {
                "agents": [], "actions": [], "targets": [], "can_manage": self.group_can_manage,
                "scope_type": "group", "scope_id": entry.query["group_id"][0],
            })
        else:
            super()._dispatch(route, entry)

    def assert_read_only(self):
        assert not self.workflow_writes
        assert all(entry.method == "POST" and entry.path.endswith("/flow-preview") for entry in self.non_navigation_writes), self.non_navigation_writes
        assert all(entry.path.endswith("/flow") for entry in self.detail_requests)

    def assert_clean(self):
        assert not self.held_flow_responses, "A test left an explicit Flow response gate closed."
        assert not self.flow_response_gates, "A deferred Flow request was never made."
        self.assert_read_only()
        super().assert_clean()


@pytest.fixture(scope="session")
def connect_options():
    assert not os.getenv("PLAYWRIGHT_SERVICE_URL"), "M5A offline tests require PLAYWRIGHT_SERVICE_URL=''."
    return {}


@pytest.fixture
def workflow_flow_ui(page):
    fixture = WorkflowFlowFixture(page)
    yield fixture
    try:
        fixture.assert_clean()
    finally:
        fixture.release_flow_responses()
        fixture.flow_response_gates.clear()
