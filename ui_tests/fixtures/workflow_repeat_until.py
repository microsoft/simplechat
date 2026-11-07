# workflow_repeat_until.py
"""
Closed fixtures for typed Repeat until authoring and exact run inspection.
Version: 0.261.120
Implemented in: 0.261.120

The real local SPA and production definition normalizer are used. No live
application, Azure browser, model, document service, or workspace is contacted.
"""

import copy
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone

import pytest

from ui_tests.fixtures.workflow_control_definitions import flow_binding
from ui_tests.fixtures.workflow_editor import GROUP_ID, connect_options, workflow_record  # noqa: F401
from ui_tests.fixtures.workflow_loops import WorkflowLoopsFixture
from ui_tests.fixtures.workspace_authoring import OWNER_ID


REPEAT_WORKFLOW_ID = "repeat-review-workflow"
REPEAT_RUN_ID = "repeat-review-run"
REPEAT_ID = "refine-report"
REPEAT_EXECUTION_ID = "repeat-execution"


def state_binding(name, state_name, kind="text", loop_id=REPEAT_ID):
    return {
        "name": name,
        "source": {"kind": "repeat_state", "loop_id": loop_id, "state_name": state_name, "scope": "current"},
        "required": True, "expected_kind": kind, "allow_partial": False,
    }


def state_contract(kind):
    contract = {"kind": kind, "allow_partial": False, "require_complete_coverage": False}
    if kind == "json":
        contract["schema"] = {
            "type": "object", "properties": {"ready": {"type": "boolean"}}, "required": ["ready"],
        }
    elif kind in {"records", "document_results"}:
        contract["schema"] = {
            "type": "array", "items": {
                "type": "object", "properties": {"finding": {"type": "string"}}, "required": ["finding"],
            },
        }
    return contract


def repeat_workflow_record(*, group=False, collections=False):
    """Every temporal source is an exact earlier output or named current state."""
    tasks = []
    for index, (task_id, name, kind) in enumerate([
        ("seed-draft", "Seed draft", "text"),
        ("seed-review", "Seed review", "json"),
        ("revise", "Revise draft", "text"),
        ("review", "Review draft", "json"),
    ], 1):
        tasks.append({
            "id": task_id, "type": "instructions", "name": name,
            "instructions": f"Produce {name.lower()} with the declared output shape.",
            "order": index, "runner": {"type": "inherit"}, "document_action": {"type": "none"},
            "inputs": [], "reference_ids": [], "output_contract": state_contract(kind),
        })
    tasks[2]["inputs"] = [state_binding("draft", "draft"), state_binding("review", "review", "json")]
    tasks[3]["inputs"] = [flow_binding("draft", "revise", "text", kind="text")]
    repeat = {
        "id": REPEAT_ID, "kind": "repeat_until", "max_iterations": 2,
        "state": [
            {"name": "draft", "initial": flow_binding("draft", "seed-draft", "text", kind="text")["source"],
             "next": "next_draft", "output_contract": state_contract("text")},
            {"name": "review", "initial": flow_binding("review", "seed-review", "json")["source"],
             "next": "next_review", "output_contract": state_contract("json")},
        ],
        "body": {
            "id": "refinement-body",
            "nodes": [{"id": task_id, "kind": "task", "task_id": task_id} for task_id in ("revise", "review")],
            "outputs": [flow_binding("next_draft", "revise", "text", kind="text"), flow_binding("next_review", "review", "json")],
        },
        "until": {"op": "eq", "left": {"input": "review", "path": "/ready"}, "right": {"literal": True}},
        "exports": [{"name": "report", "output": "next_draft"}, {"name": "review", "output": "next_review"}],
    }
    nodes = [{"id": task_id, "kind": "task", "task_id": task_id} for task_id in ("seed-draft", "seed-review")]
    if collections:
        for kind in ("records", "document_results"):
            task_id = f"seed-{kind}"
            tasks.append({
                "id": task_id, "type": "instructions", "name": f"Seed {kind}",
                "instructions": "Keep complete original objects in their saved order.",
                "order": len(tasks) + 1, "runner": {"type": "inherit"}, "document_action": {"type": "none"},
                "inputs": [], "reference_ids": [], "output_contract": state_contract(kind),
            })
            output = "documents" if kind == "document_results" else "records"
            nodes.append({"id": task_id, "kind": "task", "task_id": task_id})
            repeat["state"].append({
                "name": kind, "initial": flow_binding(kind, task_id, output, kind=kind)["source"],
                "next": f"next_{kind}", "output_contract": state_contract(kind),
            })
            repeat["body"]["outputs"].append(state_binding(f"next_{kind}", kind, kind))
            repeat["exports"].append({"name": kind, "output": f"next_{kind}"})
    nodes.append(repeat)
    return workflow_record(
        REPEAT_WORKFLOW_ID, name="Group Repeat review" if group else "Repeat review",
        definition_version=3, durable_execution=True, chat_capabilities_enabled=False,
        tasks=tasks, reference_inputs=[], limits={"max_executions": 5000, "deadline_seconds": 86400},
        flow={"id": "root", "nodes": nodes, "outputs": [flow_binding("report", REPEAT_ID, "report", kind="text")]},
        **({"group_id": GROUP_ID} if group else {}),
    )


def bounded_pages(items, page_size):
    return {
        ("" if offset == 0 else f"offset-{offset}"): {
            "items": copy.deepcopy(items[offset:offset + page_size]),
            "next_cursor": f"offset-{offset + page_size}" if offset + page_size < len(items) else None,
        }
        for offset in range(0, len(items), page_size)
    } or {"": {"items": [], "next_cursor": None}}


def repeat_progress(completed_count=2, batch_size=2, *, running_round=False, partial=False):
    batch_number = completed_count // batch_size if running_round else completed_count // batch_size - 1
    return {
        "execution_id": REPEAT_EXECUTION_ID, "node_id": REPEAT_ID,
        "completed_iteration": completed_count - 1, "next_iteration": completed_count,
        "batch_number": batch_number, "batch_size": batch_size,
        "batch_usage": completed_count % batch_size + 1 if running_round else batch_size,
        "completed_count": completed_count,
        "exhaustion_count": batch_number if running_round else batch_number + 1,
        "continuation_count": batch_number,
        "state": "running" if running_round else "waiting_manual_continue", "partial": partial,
    }


class WorkflowRepeatFixture(WorkflowLoopsFixture):
    """Extend the existing scoped closed server, not the application runtime."""

    def __init__(self, page):
        super().__init__(page)
        self.repeat_ceiling = 25
        self.repeat_hard_ceiling = 1000
        self.repeat_capabilities = True
        self.personal_workflows[REPEAT_WORKFLOW_ID] = repeat_workflow_record()
        self.group_workflows[GROUP_ID][REPEAT_WORKFLOW_ID] = repeat_workflow_record(group=True)
        self.repeat_iteration_pages = {}
        self.nested_repeat_instances = {}
        self.nested_item_instances = {}
        self.repeat_state_override = None
        self.repeat_iterations_override = None
        self.allowed_state_sources = {}
        self.allowed_iteration_executions = {}
        self.frozen_repeat_definitions = {}
        self.repeat_grants = []
        self._seed_repeat_run("user")
        self._seed_repeat_run("group")

    def _options(self, group):
        options = super()._options(group)
        if self.repeat_capabilities:
            options["supported_node_kinds"].append("repeat_until")
            options["supported_binding_sources"].append("repeat_state")
            if self.repeat_ceiling is not None:
                options["flow_limits"]["max_repeat_iterations"] = self.repeat_ceiling
            if self.repeat_hard_ceiling is not None:
                options["flow_limits"]["hard_repeat_iterations"] = self.repeat_hard_ceiling
        options["publication_source_capabilities"] = [{
            "source_kind": "saved_output", "output_kinds": ["records"], "artifact_formats": ["json"],
        }]
        options["supported_publication_completion_policies"] = ["submitted", "approved", "indexed_ready"]
        return options

    def _seed_repeat_run(self, scope, *, completed_count=2, batch_size=2, running_round=False, partial=False):
        key = (scope, REPEAT_WORKFLOW_ID, REPEAT_RUN_ID)
        summary = repeat_progress(completed_count, batch_size, running_round=running_round, partial=partial)
        status = "running" if running_round else "paused"
        self.frozen_repeat_definitions[key] = repeat_workflow_record(group=scope == "group", collections=True)
        self.frozen_repeat_definitions[key]["flow"]["nodes"][-1]["max_iterations"] = batch_size
        if partial:
            snapshot = self.frozen_repeat_definitions[key]
            snapshot["flow"]["nodes"][-1]["state"][2]["output_contract"]["allow_partial"] = True
            snapshot["flow"]["nodes"][-1]["body"]["outputs"][2]["allow_partial"] = True
            snapshot["flow"]["outputs"][0]["allow_partial"] = True
            next(task for task in snapshot["tasks"] if task["id"] == "seed-records")["output_contract"]["allow_partial"] = True
        self.workflow_runs[REPEAT_WORKFLOW_ID] = [{
            "id": REPEAT_RUN_ID, "workflow_id": REPEAT_WORKFLOW_ID, "definition_version": 3,
            "durable_execution": True, "status": status, "started_at": "2026-09-19T12:00:00Z",
        }]
        runtime = {
            "schema_version": 2, "version": 10, "state": status, "phase": REPEAT_ID,
            "repeat_progress": copy.deepcopy(summary),
            "repeat_counts": {"exhaustion_count": summary["exhaustion_count"], "continuation_count": summary["continuation_count"]},
            "memory": {"execution_count": completed_count * 3 + 5, "decision_count": completed_count},
            "limits": {
                "max_executions": 5000, "admitted_count": completed_count * 3 + 5, "deadline_seconds": 86400,
                "deadline_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                "waits_count": True, "max_repeat_iterations": max(25, batch_size),
            },
        }
        if not running_round:
            runtime["gate"] = {
                "id": "repeat-limit-gate-1", "kind": "pause", "reason_code": "repeat_iteration_limit",
                "unit_id": REPEAT_ID, "execution_id": REPEAT_EXECUTION_ID, "node_id": REPEAT_ID,
                "attempt": 1, "iteration_path": [], "choices": ["continue_repeat", "cancel"],
                "reason": "The stop condition is still unmet. Saved state is retained.",
                "repeat": copy.deepcopy(summary),
            }
        self.workflow_runtimes[key] = runtime
        self.runtime_can_decide[key] = True
        self.runtime_get_count[key] = 0
        self.execution_pages[key] = bounded_pages([{
            "execution_id": REPEAT_EXECUTION_ID, "node_id": REPEAT_ID, "node_kind": "repeat_until",
            "state": status, "attempt": 1, "iteration_path": [],
            **({"reason_code": "repeat_iteration_limit"} if not running_round else {}),
        }], 50)
        iterations = [{
            "iteration": iteration, "iteration_path": [{"loop_id": REPEAT_ID, "iteration": iteration}],
            "batch_number": iteration // batch_size, "batch_size": batch_size, "batch_usage": iteration % batch_size + 1,
            "state": "running" if iteration == completed_count else "completed_partial" if partial else "completed",
            "condition_result": None if iteration == completed_count else False,
            "before_available": True, "after_available": iteration < completed_count,
            "partial": partial and iteration < completed_count,
            "execution_ids": [f"revise-round-{iteration}"] if iteration == completed_count
                else [f"revise-round-{iteration}", f"review-round-{iteration}"],
        } for iteration in range(completed_count + int(running_round))]
        self.repeat_iteration_pages[key] = bounded_pages(iterations, 1 if len(iterations) < 10 else 50)
        decisions = [{
            "execution_id": REPEAT_EXECUTION_ID, "node_id": REPEAT_ID, "iteration_path": [],
            "attempt": 1, "decision_kind": "repeat_transition", "iteration": completed_count - 1,
            "batch_number": (completed_count - 1) // batch_size, "condition_result": False,
        }]
        if summary["continuation_count"]:
            grant_summary = repeat_progress(summary["batch_number"] * batch_size, batch_size, partial=partial)
            decisions.append({
                "execution_id": REPEAT_EXECUTION_ID, "node_id": REPEAT_ID, "iteration_path": [],
                "attempt": 1, "choice": "continue_repeat", "actor_user_id": OWNER_ID,
                "gate_id": "previous-repeat-limit", "decided_at": "2026-09-19T12:10:00Z",
                "event_id": "fixture-repeat-grant", "reason_code": "repeat_iteration_limit", "repeat": grant_summary,
            })
        self.decision_pages[key] = bounded_pages(decisions, 50)

    def _state_slots(self, iteration, phase, partial):
        source_iteration = iteration - 1 if phase == "before" else iteration
        slots = []
        for name, kind, node_id in (
            ("draft", "text", "revise"), ("review", "json", "review"),
            ("records", "records", "seed-records"), ("document_results", "document_results", "seed-document_results"),
        ):
            initial = source_iteration < 0 or kind in {"records", "document_results"}
            producer_node = f"seed-{name}" if initial else node_id
            source = {
                "node_id": producer_node, "execution_id": producer_node if initial else f"{node_id}-round-{source_iteration}",
                "attempt": 1 if initial or kind == "text" else 2,
                "iteration_path": [] if initial else [{"loop_id": REPEAT_ID, "iteration": source_iteration}],
                "output_name": "documents" if kind == "document_results" else kind,
            }
            accepted_partial = partial and kind == "records"
            slots.append({
                "name": name, "kind": kind, "source": source,
                "workflow_validation": {
                    "version": 1, "status": "accepted_partial" if accepted_partial else "valid", "eligible": True,
                    "reason_codes": ["producer_coverage_incomplete"] if accepted_partial else [], "counts": {},
                },
                "coverage": {"complete": not accepted_partial, "record_count": 260} if kind == "records" else {},
                "limitations": ["One source could not be analyzed; original accepted records are retained."] if accepted_partial else [],
                **({"prior_coverage": {"complete": False, "record_count": 260}}
                   if accepted_partial and source_iteration >= 0 else {}),
            })
        return slots

    def complete_with_records_export(self, scope="user"):
        key = (scope, REPEAT_WORKFLOW_ID, REPEAT_RUN_ID)
        runtime = self.workflow_runtimes[key]
        runtime.update(state="completed")
        self.workflow_runs[REPEAT_WORKFLOW_ID][0]["status"] = "completed"
        runtime.pop("gate", None)
        runtime["repeat_progress"]["state"] = "completed"
        final_round = list(self.repeat_iteration_pages[key].values())[-1]["items"][-1]
        final_round["condition_result"] = True
        record = self.execution_pages[key][""]["items"][0]
        record.update(
            state="completed",
            workflow_validation={"version": 1, "status": "valid", "eligible": True, "counts": {}},
            workflow_result={
                "authoritative_output": "findings", "outputs": {"findings": {"kind": "records"}},
                "result_ref": {"storage": "cosmos", "size_bytes": 4096, "chunk_count": 2, "sha256": "a" * 64},
            },
        )
        record.pop("reason_code", None)
        self.attempt_pages[(*key, REPEAT_EXECUTION_ID)] = bounded_pages([record], 50)
        slot = self._state_slots(1, "after", False)[2]
        slot["source"] = {
            "node_id": REPEAT_ID, "execution_id": REPEAT_EXECUTION_ID, "attempt": 1, "iteration_path": [], "output_name": "findings",
        }
        self.allowed_state_sources[(*key, REPEAT_EXECUTION_ID, 1, "findings")] = slot
        frozen_repeat = self.frozen_repeat_definitions[key]["flow"]["nodes"][-1]
        frozen_repeat["exports"].append({"name": "findings", "output": "next_records"})

    def add_nested_inspection(self, scope="user"):
        key = (scope, REPEAT_WORKFLOW_ID, REPEAT_RUN_ID)
        first = self.repeat_iteration_pages[key][""]["items"][0]
        first["execution_ids"] = ["nested-repeat-execution", "nested-each-execution"]
        for execution_id, node_id, kind in (
            ("nested-repeat-execution", "nested-refinement", "repeat_until"),
            ("nested-each-execution", "each-saved-finding", "for_each"),
        ):
            self.attempt_pages[(*key, execution_id)] = bounded_pages([{
                "execution_id": execution_id, "node_id": node_id, "node_kind": kind, "attempt": 1,
                "state": "completed", "iteration_path": copy.deepcopy(first["iteration_path"]),
                "workflow_result": {
                    "outputs": {}, "result_ref": {"storage": "cosmos", "size_bytes": 512, "chunk_count": 1, "sha256": "c" * 64},
                },
            }], 50)
        summary = {
            **repeat_progress(1, 1), "execution_id": "nested-repeat-execution", "node_id": "nested-refinement",
            "state": "completed", "exhaustion_count": 0,
        }
        self.nested_repeat_instances[(*key, "nested-repeat-execution")] = {
            "summary": summary,
            "pages": bounded_pages([{
                "iteration": 0, "iteration_path": [*copy.deepcopy(first["iteration_path"]), {"loop_id": "nested-refinement", "iteration": 0}],
                "batch_number": 0, "batch_size": 1, "batch_usage": 1, "state": "completed",
                "condition_result": True, "execution_ids": [], "before_available": True, "after_available": True, "partial": False,
            }], 50),
        }
        self.nested_item_instances[(*key, "nested-each-execution")] = {
            "loop_execution_id": "nested-each-execution", "frozen_at": "2026-09-19T12:00:00Z",
            "total_count": 1, "next_cursor": None, "limit": 500,
            "items": [{
                "item_id": "e" * 64, "index": 0, "label": "Exact saved finding", "state": "completed",
                "iteration_path": [
                    *copy.deepcopy(first["iteration_path"]),
                    {"loop_id": "each-saved-finding", "item_id": "e" * 64, "index": 0},
                ],
                "execution_ids": [], "record_count": 1,
            }],
        }

    def _dispatch(self, route, entry):
        prefix = rf"/api/(user|group)/workflows/{REPEAT_WORKFLOW_ID}/runs/{REPEAT_RUN_ID}/executions"
        if re.fullmatch(prefix + r"/[^/]+/iterations(?:/\d+/state)?", entry.path):
            self._repeat_history_resource(route, entry)
        elif re.fullmatch(prefix + r"/(?:revise|review)-round-\d+/attempts", entry.path):
            self._repeat_attempts_resource(route, entry)
        elif re.fullmatch(prefix + r"/nested-each-execution/items", entry.path):
            assert entry.query.get("limit") == ["50"], entry
            self._json(route, copy.deepcopy(self.nested_item_instances[(*self._key(entry), "nested-each-execution")]))
        elif re.fullmatch(prefix + r"/[^/]+/attempts/\d+/(?:result|records|provenance)", entry.path):
            self._repeat_source_resource(route, entry)
        else:
            super()._dispatch(route, entry)

    def _repeat_history_resource(self, route, entry):
        key = self._key(entry)
        parts = entry.path.split("/")
        execution_id = parts[8]
        assert entry.query.get("limit") == ["50"], entry
        runtime = self.workflow_runtimes[key]
        nested = self.nested_repeat_instances.get((*key, execution_id))
        assert execution_id == REPEAT_EXECUTION_ID or nested is not None, entry
        summary = nested["summary"] if nested else runtime["repeat_progress"]
        pages = nested["pages"] if nested else self.repeat_iteration_pages[key]
        if parts[-1] == "iterations":
            if self.repeat_iterations_override is not None:
                self._json(route, copy.deepcopy(self.repeat_iterations_override))
                return
            page = pages[entry.query.get("cursor", [""])[0]]
            self.allowed_iteration_executions.setdefault(key, set()).update(
                execution_id for item in page["items"] for execution_id in item["execution_ids"]
            )
            self._json(route, {
                "iterations": copy.deepcopy(page["items"]), "next_cursor": page["next_cursor"],
                "total_count": sum(len(value["items"]) for value in pages.values()),
                "repeat_execution_id": execution_id, "repeat": copy.deepcopy(summary),
                "source_snapshot_changed": False,
            })
            return
        iteration, phase = int(parts[10]), entry.query.get("phase", [""])[0]
        assert phase in {"before", "after"}, entry
        assert any(item["iteration"] == iteration for page in pages.values() for item in page["items"]), entry
        if self.repeat_state_override is not None:
            self._json(route, copy.deepcopy(self.repeat_state_override))
            return
        available = phase == "before" or iteration < summary["completed_count"]
        result = {"iteration": iteration, "phase": phase, "repeat_execution_id": execution_id, "available": available}
        if not available:
            self._json(route, {**result, "states": [], "next_cursor": None, "total_count": 0})
            return
        partial = summary["partial"]
        slots = self._state_slots(iteration, phase, partial)
        pages = bounded_pages(slots, 2)
        selected = pages[entry.query.get("cursor", [""])[0]]
        for slot in selected["items"]:
            source = slot["source"]
            self.allowed_state_sources[(*key, source["execution_id"], source["attempt"], source["output_name"])] = copy.deepcopy(slot)
        self._json(route, {
            **result, "states": copy.deepcopy(selected["items"]), "next_cursor": selected["next_cursor"],
            "total_count": len(slots), "partial": partial, "source_snapshot_changed": False,
        })

    def _repeat_attempts_resource(self, route, entry):
        key = self._key(entry)
        execution_id = entry.path.split("/")[8]
        assert execution_id in self.allowed_iteration_executions.get(key, set()), entry
        assert entry.query.get("limit") == ["50"], entry
        node_id, _, round_text = execution_id.partition("-round-")
        iteration = int(round_text)
        if iteration >= self.workflow_runtimes[key]["repeat_progress"]["completed_count"]:
            self._json(route, {
                "attempts": [{
                    "execution_id": execution_id, "node_id": node_id, "task_id": node_id,
                    "attempt": 1, "state": "running", "iteration_path": [{"loop_id": REPEAT_ID, "iteration": iteration}],
                }],
                "next_cursor": None, "total_count": 1,
            })
            return
        slot = self._state_slots(iteration, "after", self.workflow_runtimes[key]["repeat_progress"]["partial"])[
            1 if node_id == "review" else 0
        ]
        source = slot["source"]
        record = {
            "execution_id": execution_id, "node_id": node_id, "task_id": node_id, "attempt": source["attempt"],
            "iteration_path": source["iteration_path"], "state": "completed",
            "workflow_validation": copy.deepcopy(slot["workflow_validation"]),
            "workflow_result": {
                "authoritative_output": source["output_name"], "outputs": {source["output_name"]: {"kind": slot["kind"]}},
                "result_ref": {"storage": "cosmos", "size_bytes": 512, "chunk_count": 1, "sha256": "b" * 64},
            },
        }
        self.allowed_state_sources[(*key, execution_id, source["attempt"], "authoritative")] = slot
        attempts = [record]
        if source["attempt"] == 2:
            attempts.insert(0, {
                "execution_id": execution_id, "node_id": node_id, "task_id": node_id, "attempt": 1,
                "iteration_path": source["iteration_path"], "state": "failed",
            })
        self._json(route, {"attempts": attempts, "next_cursor": None, "total_count": len(attempts)})

    def _repeat_source_resource(self, route, entry):
        key = self._key(entry)
        parts = entry.path.split("/")
        execution_id, attempt, resource = parts[8], int(parts[10]), parts[11]
        output = entry.query.get("output", [""])[0]
        if resource == "provenance":
            assert entry.query.get("limit") == ["50"], entry
            slot = next(slot for source, slot in self.allowed_state_sources.items() if source[:5] == (*key, execution_id, attempt))
            source = copy.deepcopy(slot["source"])
            source.pop("output_name")
            self._json(route, {
                "contributors": [{"producer": source, "output_name": slot["source"]["output_name"],
                                  "record_offset": 0, "record_count": 260, "producer_record_offset": 0}],
                "total_count": 1, "next_cursor": None,
            })
            return
        selected_key = (*key, execution_id, attempt, output)
        assert selected_key in self.allowed_state_sources, f"Unselected producer read: {entry}"
        slot = self.allowed_state_sources[selected_key]
        if resource == "records":
            assert entry.query.get("limit") == ["100"], entry
            assert slot["kind"] in {"records", "document_results"}, entry
            records = [{"finding": f"Original finding {index}", "ready": False, "amount": 0, "details": {"nullable": None}}
                       for index in range(260)]
            pages = bounded_pages(records, 100)
            cursor = entry.query.get("cursor", [""])[0]
            page = pages[cursor]
            self._json(route, {
                "records": page["items"], "next_cursor": page["next_cursor"], "total_count": len(records),
                "record_offset": int(cursor.removeprefix("offset-")) if cursor else 0,
                "output_name": output, "workflow_validation": copy.deepcopy(slot["workflow_validation"]),
                "coverage": copy.deepcopy(slot["coverage"]),
            })
            return
        assert resource == "result" and entry.query.get("limit") == ["2000"], entry
        value = {"ready": False, "note": "Retained exact review"} if slot["kind"] == "json" else "Retained exact draft"
        content = json.dumps({
            "kind": slot["kind"], "output_name": output, "producer": slot["source"], "value": value,
        }, ensure_ascii=True, sort_keys=True)
        offset = int(entry.query.get("offset", ["0"])[0])
        end = min(len(content), offset + 2000)
        self._json(route, {
            "content": content[offset:end], "offset": offset, "next_offset": end if end < len(content) else None,
            "output_name": output, "total_bytes": len(content), "complete": end == len(content),
            "sha256": hashlib.sha256(content.encode("ascii")).hexdigest(),
        })

    def _workflow_runtime(self, route, entry):
        scope = entry.path.split("/")[2]
        key = (scope, REPEAT_WORKFLOW_ID, REPEAT_RUN_ID)
        if (f"/{REPEAT_WORKFLOW_ID}/" in entry.path and entry.path.endswith("/runtime/decision")
                and entry.body.get("choice") == "cancel"):
            self.workflow_runtimes[key]["repeat_progress"]["state"] = "cancelled"
        if f"/{REPEAT_WORKFLOW_ID}/" not in entry.path or not entry.path.endswith("/runtime/decision") or entry.body.get("choice") != "continue_repeat":
            super()._workflow_runtime(route, entry)
            return
        assert entry.query.get("group_id") == ([GROUP_ID] if scope == "group" else None), entry
        runtime = self.workflow_runtimes[key]
        assert set(entry.body) == {"expected_version", "gate_id", "choice", "request_id"}, entry
        assert entry.body["expected_version"] == runtime["version"], entry
        assert entry.body["gate_id"] == runtime["gate"]["id"], entry
        assert re.fullmatch(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}", entry.body["request_id"]), entry
        if not self.runtime_can_decide[key]:
            self.expected_http_errors.add((route.request.url, 403))
            self._json(route, {"error": "Decision permission was revoked."}, 403)
            return
        if self.fail_next_decision_status:
            status, self.fail_next_decision_status = self.fail_next_decision_status, None
            self.expected_http_errors.add((route.request.url, status))
            self._json(route, {"error": "Transient decision failure."}, status)
            return
        if self.stale_next_decision:
            self.stale_next_decision = False
            runtime["version"] += 1
            runtime["gate"]["id"] = "repeat-limit-refreshed"
            self.expected_http_errors.add((route.request.url, 409))
            self._json(route, {"error": "The Repeat gate changed."}, 409)
            return
        gate = runtime.pop("gate")
        self.repeat_grants.append(copy.deepcopy(entry))
        decision = {
            "execution_id": REPEAT_EXECUTION_ID, "node_id": REPEAT_ID, "iteration_path": [], "attempt": 1,
            "gate_id": gate["id"], "choice": "continue_repeat", "actor_user_id": OWNER_ID,
            "decided_at": datetime.now(timezone.utc).isoformat(), "repeat": copy.deepcopy(gate["repeat"]),
            "event_id": "fixture-committed-repeat-grant", "reason_code": "repeat_iteration_limit",
        }
        decisions = [item for page in self.decision_pages[key].values() for item in page["items"]]
        self.decision_pages[key] = bounded_pages([*decisions, decision], 50)
        runtime["version"] += 1
        runtime["state"] = "queued"
        self.workflow_runs[REPEAT_WORKFLOW_ID][0]["status"] = "queued"
        summary = runtime["repeat_progress"]
        summary.update(batch_number=summary["batch_number"] + 1, batch_usage=0,
                       continuation_count=summary["continuation_count"] + 1, state="running")
        runtime["repeat_counts"]["continuation_count"] += 1
        self._json(route, {"runtime": copy.deepcopy(runtime), "can_decide": True})


@pytest.fixture
def workflow_repeat_ui(page):
    fixture = WorkflowRepeatFixture(page)
    yield fixture
    fixture.assert_clean()
