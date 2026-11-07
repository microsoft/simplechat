# workflow_loops.py
"""
Closed, source-backed M4B workflow fixtures for the production V2 SPA.
Version: 0.261.117
Implemented in: 0.261.117

Authoring writes use WorkflowEditorFixture's production definition normalizer.
All source selection and history requests are intercepted; no model, storage,
search service, or authenticated application is contacted.
"""

import copy
import hashlib
import json
import re

import pytest

from ui_tests.fixtures.workflow_control_definitions import flow_binding
from ui_tests.fixtures.workflow_control_runtime import WorkflowControlRuntimeFixture, _pages
from ui_tests.fixtures.workflow_editor import (
    GROUP_ID,
    connect_options,  # noqa: F401
    editor_options,
    workflow_record,
)
# The shared fixtures above configure isolated application imports.
from functions_workflow_results import workflow_result_summary


LOOP_WORKFLOW_ID = "source-loop-review"
LOOP_RUN_ID = "loop-run"
LOOP_ID = "each-source"
LOOP_EXECUTION_ID = "loop-execution"
COLLECT_EXECUTION_ID = "collect-execution"
ITEM_A_EXECUTION_ID = "analyze-source-a"
ITEM_B_EXECUTION_ID = "analyze-source-b"
REPORT_EXECUTION_ID = "report-execution"


def loop_item(name="item", loop_id=LOOP_ID):
    return {
        "name": name,
        "source": {"kind": "loop_item", "loop_id": loop_id, "scope": "current"},
        "required": True,
        "expected_kind": "json",
        "allow_partial": False,
    }


def record_contract():
    return {
        "kind": "records",
        "schema": {"type": "array", "items": {
            "type": "object", "properties": {"finding": {"type": "string"}},
            "required": ["finding"],
        }},
        "require_complete_coverage": True,
        "allow_partial": False,
    }


def loop_workflow_record(*, group=False, saved_collection=False):
    scope = {"scope_type": "group", "scope_id": GROUP_ID} if group else {"scope_type": "personal"}
    documents = [{"document_id": "group-brief" if group else "personal-brief", **scope}]
    if not group:
        documents.append({"document_id": "personal-second", **scope})
    task = {
        "id": "analyze-task", "type": "instructions", "name": "Analyze current source",
        "instructions": "Produce records with findings from this current item.",
        "order": 1, "runner": {"type": "inherit"}, "reference_ids": [],
        "inputs": [loop_item()], "output_contract": record_contract(),
        "document_action": {"type": "none"} if saved_collection else {
            "type": "analyze", "target_mode": "current_item", "loop_id": LOOP_ID,
            "analysis_mode": "combined",
        },
    }
    source = {
        "id": LOOP_ID, "kind": "for_each", "inputs": [],
        "iterable": {"kind": "documents", "documents": documents},
        "max_items": 500, "item_key": "source_identity",
        "body": {
            "id": "source-body", "nodes": [{"id": "analyze-one", "kind": "task", "task_id": task["id"]}],
            "outputs": [flow_binding("findings", "analyze-one", "records", kind="records")],
        },
    }
    nodes = [
        source,
        {
            "id": "collect-findings", "kind": "collect",
            "source": {"loop_id": LOOP_ID, "output": "findings"},
            "output_contract": record_contract(),
        },
    ]
    tasks = [task]
    if saved_collection:
        seed = {
            "id": "seed-task", "type": "instructions", "name": "Prepare saved rows",
            "instructions": "Prepare a complete collection of finding records.",
            "order": 1, "runner": {"type": "inherit"}, "reference_ids": [],
            "inputs": [], "output_contract": record_contract(), "document_action": {"type": "none"},
        }
        tasks.insert(0, seed)
        task["order"] = 2
        nodes.insert(0, {"id": "seed", "kind": "task", "task_id": "seed-task"})
        source["inputs"] = [flow_binding("rows", "seed", "records", kind="records")]
        source["iterable"] = {"kind": "input", "name": "rows"}
    return workflow_record(
        LOOP_WORKFLOW_ID,
        name="Group source loop" if group else "Source loop review",
        definition_version=3, durable_execution=True, chat_capabilities_enabled=False,
        tasks=tasks, reference_inputs=[], limits={"max_executions": 5000, "deadline_seconds": 86400},
        flow={"id": "root", "nodes": nodes,
              "outputs": [flow_binding("findings", "collect-findings", "records", kind="records")]},
        **({"group_id": GROUP_ID} if group else {}),
    )


def reporting_loop_workflow_record(*, input_processing=None, collection_kind="records", group=False):
    record = loop_workflow_record(group=group)
    output = "documents" if collection_kind == "document_results" else "records"
    record["tasks"][0]["output_contract"]["kind"] = collection_kind
    loop, collect = record["flow"]["nodes"]
    loop["body"]["outputs"][0]["source"]["output"] = output
    loop["body"]["outputs"][0]["expected_kind"] = collection_kind
    collect["output_contract"]["kind"] = collection_kind
    task = {
        "id": "report-task", "type": "instructions", "name": "Explain saved findings",
        "instructions": "Read all saved findings and provide a qualitative source-linked explanation.",
        "order": 2, "runner": {"type": "inherit"}, "document_action": {"type": "none"},
        "inputs": [flow_binding("findings", "collect-findings", output, kind=collection_kind)],
        "reference_ids": [],
        "output_contract": {"kind": "text", "require_complete_coverage": False, "allow_partial": False},
    }
    if input_processing is not None:
        task["input_processing"] = input_processing
    record["tasks"].append(task)
    record["flow"]["nodes"].append({"id": "explain", "kind": "task", "task_id": "report-task"})
    record["flow"]["outputs"] = [flow_binding("report", "explain", "text", kind="text")]
    return record


def nested_loop_workflow_record():
    record = loop_workflow_record()
    outer = record["flow"]["nodes"][0]
    inner = {
        "id": "each-finding", "kind": "for_each", "max_items": 20, "item_key": "source_identity",
        "inputs": [flow_binding("rows", "analyze-one", "records", kind="records")],
        "iterable": {"kind": "input", "name": "rows"},
        "body": {"id": "finding-body", "nodes": [{
            "id": "check-index", "kind": "if", "inputs": [loop_item("row", "each-finding")],
            "condition": {"op": "eq", "left": {"input": "row", "path": "/index"}, "right": {"literal": 0}},
            "then": {"id": "first-row", "nodes": [{"id": "first", "kind": "task", "task_id": "first-task"}]},
            "else": {"id": "other-row", "nodes": [{"id": "other", "kind": "task", "task_id": "other-task"}]},
            "join": {"id": "row-join", "exports": [{
                "name": "checked", "expected_kind": "records", "required": True,
                "then": {"node_id": "first", "output": "records"},
                "else": {"node_id": "other", "output": "records"},
            }]},
        }], "outputs": [flow_binding("checked", "row-join", "checked", kind="records")]},
    }
    outer["body"]["nodes"].extend([inner, {
        "id": "collect-checked", "kind": "collect",
        "source": {"loop_id": "each-finding", "output": "checked"},
        "output_contract": record_contract(),
    }])
    outer["body"]["outputs"] = [flow_binding("findings", "collect-checked", "records", kind="records")]
    for index, task_id in enumerate(("first-task", "other-task"), 2):
        record["tasks"].append({
            "id": task_id, "type": "instructions", "name": f"Review {task_id}",
            "instructions": "Inspect this exact record and the current source item.",
            "order": index, "runner": {"type": "inherit"}, "reference_ids": [],
            "inputs": [loop_item("row", "each-finding"), loop_item("source", LOOP_ID)],
            "document_action": {"type": "none"}, "output_contract": record_contract(),
        })
    return record


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode("utf-8")).hexdigest()


def query_selection_metadata(*, mode="best_n", hybrid=True):
    return {
        "query_mode": mode, "exhaustive": mode == "all_matches",
        "ranking": "candidate_round_then_max_chunk_score" if hybrid else "max_chunk_score" if mode == "best_n" else "qualified_document_identity",
        "candidate_limitations": [
            "Hybrid retrieval uses 1,000-chunk candidate windows and the provider's "
            "50-chunk semantic reranking window. Distinct-document backfill excludes "
            "previous candidates; semantic relevance is not exhaustive corpus coverage.",
        ] if hybrid else [],
        **({
            "candidate_window": 1000, "semantic_rerank_window": 50,
            "candidate_expansion": "exclude_processed_document_ids", "candidate_expansion_rounds": 2,
        } if hybrid else {}),
    }


class WorkflowLoopsFixture(WorkflowControlRuntimeFixture):
    """Loop-specific capabilities and bounded pages on the existing closed server."""

    def __init__(self, page):
        super().__init__(page)
        self.ceiling = 500
        self.loop_capabilities = True
        self.input_processing_modes = ["full", "saved_record_report"]
        self.query_count = 2
        self.query_exact = True
        self.preview_selection = None
        self.pending_preview = []
        self.defer_preview = False
        self.personal_workflows[LOOP_WORKFLOW_ID] = loop_workflow_record()
        self.group_workflows[GROUP_ID][LOOP_WORKFLOW_ID] = loop_workflow_record(group=True)
        self.item_pages = {}
        self.item_selections = {}
        self.record_pages = {}
        self.provenance_pages = {}
        self._seed_loop_run("user")
        self._seed_loop_run("group")

    def _seed_loop_run(self, scope):
        group = scope == "group"
        key = (scope, LOOP_WORKFLOW_ID, LOOP_RUN_ID)
        self.workflow_runs[LOOP_WORKFLOW_ID] = [{
            "id": LOOP_RUN_ID, "workflow_id": LOOP_WORKFLOW_ID, "definition_version": 3,
            "durable_execution": True, "status": "completed", "started_at": "2026-09-18T12:00:00Z",
        }]
        descriptors = (self.group_workflows[GROUP_ID] if group else self.personal_workflows)[LOOP_WORKFLOW_ID]["flow"]["nodes"][0]["iterable"]["documents"]
        items = []
        contributors = []
        executions = [{"execution_id": LOOP_EXECUTION_ID, "node_id": LOOP_ID, "node_kind": "for_each",
                       "iteration_path": [], "state": "completed", "attempt": 1}]
        all_records = []
        for index, descriptor in enumerate(descriptors):
            item_id = _digest(descriptor)
            frame = {"loop_id": LOOP_ID, "item_id": item_id, "index": index}
            execution_id = ITEM_A_EXECUTION_ID if index == 0 else ITEM_B_EXECUTION_ID
            label = "Group brief" if group else "Private brief" if index == 0 else "Second brief"
            rows = [{"finding": f"Finding from {label}", "document_id": descriptor["document_id"]},
                    {"finding": f"Second finding from {label}", "document_id": descriptor["document_id"]}]
            all_records.extend(rows)
            item = {
                "item_id": item_id, "index": index, "label": label, "state": "completed",
                "iteration_path": [copy.deepcopy(frame)], "execution_ids": [execution_id], "record_count": len(rows),
            }
            items.append(item)
            result = {
                "authoritative_output": "records",
                "outputs": {"records": {"kind": "records", "count": len(rows)}},
                "result_ref": {"storage": "cosmos", "sha256": _digest(rows), "size_bytes": 256, "chunk_count": 1},
            }
            attempt = {
                "execution_id": execution_id, "node_id": "analyze-one", "task_id": "analyze-task",
                "iteration_path": [copy.deepcopy(frame)], "state": "completed", "attempt": 1,
                "workflow_result": result,
                "workflow_validation": {"version": 1, "status": "valid", "eligible": True, "counts": {}},
            }
            self.attempt_pages[(*key, execution_id)] = _pages([attempt], 50)
            self.record_pages[(*key, execution_id, 1)] = _pages(rows, 1)
            contributors.append({
                "input_name": "findings", "output_name": "records",
                "producer": {
                    "workflow_id": LOOP_WORKFLOW_ID, "run_id": LOOP_RUN_ID,
                    "execution_id": execution_id, "node_id": "analyze-one",
                    "task_id": "analyze-task", "attempt": 1, "iteration_path": [copy.deepcopy(frame)],
                },
                "item_id": item_id, "item_index": index,
                "record_offset": index * 2, "record_count": len(rows), "producer_record_offset": 0,
                "result_ref": result["result_ref"],
                "private_journal": "must-not-render-private-journal",
            })
        result = {
            "authoritative_output": "records",
            "outputs": {"records": {"kind": "records", "count": len(all_records)}},
            "result_ref": {"storage": "cosmos", "sha256": _digest(all_records), "size_bytes": 1024, "chunk_count": 2},
        }
        collect = {
            "execution_id": COLLECT_EXECUTION_ID, "node_id": "collect-findings", "node_kind": "collect",
            "iteration_path": [], "state": "completed", "attempt": 1, "workflow_result": result,
            "workflow_validation": {"version": 1, "status": "valid", "eligible": True, "counts": {"records": len(all_records)}},
        }
        executions.append(collect)
        self.execution_pages[key] = _pages(executions, 50)
        self.attempt_pages[(*key, COLLECT_EXECUTION_ID)] = _pages([collect], 50)
        self.item_pages[key] = _pages(items, 1)
        self.record_pages[(*key, COLLECT_EXECUTION_ID, 1)] = _pages(all_records, 2)
        self.provenance_pages[(*key, COLLECT_EXECUTION_ID, 1)] = _pages(contributors, 1)
        self.decision_pages[key] = _pages([{
            "execution_id": ITEM_A_EXECUTION_ID, "node_id": "analyze-one", "attempt": 1,
            "iteration_path": copy.deepcopy(items[0]["iteration_path"]), "choice": "approve", "gate_id": "item-a-gate",
        }], 50)
        self.workflow_runtimes[key] = {
            "schema_version": 2, "version": 12, "state": "completed",
            "memory": {"execution_count": len(items) + 2, "decision_count": 1},
            "loop_progress": {
                "loop_id": LOOP_ID, "loop_execution_id": LOOP_EXECUTION_ID, "total": len(items),
                "current_index": len(items) - 1, "completed": len(items), "skipped": 0,
                "failed": 0, "pending": 0, "limit": 500,
            },
        }
        self.runtime_can_decide[key] = True

    def _options(self, group):
        options = editor_options("group" if group else "personal", GROUP_ID if group else None)
        if self.loop_capabilities:
            options.update(
                supported_node_kinds=["task", "if", "route", "for_each", "collect"],
                supported_iterable_kinds=["input", "documents", "workspace_query"],
                supported_binding_sources=["node_output", "loop_item"],
                supported_input_processing_modes=list(self.input_processing_modes),
                supported_query_modes=["all_matches", "best_n"],
            )
            options["flow_limits"]["max_loop_items"] = self.ceiling
            for runner in [*options["agents"], *options["models"], options["default_model"]]:
                runner["loop_eligible"] = True
            options["agents"].append({
                "id": "hosted-reviewer", "name": "hosted-reviewer", "display_name": "Hosted reviewer",
                "is_global": True, "is_group": False, "loop_eligible": False,
            })
        return options

    def add_reporting_history(self, *, group=False, mode="record_pages", partial=False, known_limits=True):
        scope = "group" if group else "user"
        key = (scope, LOOP_WORKFLOW_ID, LOOP_RUN_ID)
        workflows = self.group_workflows[GROUP_ID] if group else self.personal_workflows
        workflows[LOOP_WORKFLOW_ID] = reporting_loop_workflow_record(input_processing="saved_record_report", group=group)
        count = sum(len(page["items"]) for page in self.record_pages[(*key, COLLECT_EXECUTION_ID, 1)].values())
        budget = {
            "model_id": "workspace-model", "limit_status": "verified" if known_limits else "unverified",
            "limit_source": "catalog+configured" if known_limits else "compatibility_policy",
            "context_window_tokens": 8192 if known_limits else None,
            "max_input_tokens": 6000 if known_limits else None,
            "max_output_tokens": 2048 if known_limits else None,
            "output_reserve_tokens": 2048, "output_reservation": "automatic",
            "safety_tokens": 256, "input_tokens": 2048, "input_budget_tokens": 5744,
            "token_estimator": "fixture-token-estimate", "decision": "full_input", "truncated": False,
        }
        consumption = {
            "input_kind": "workflow_records", "version": "workflow-record-report-v1",
            "mode": mode, "record_count": count, "page_count": count if mode == "record_pages" else 0,
            "reduction_levels": 1 if mode == "record_pages" else 0,
            "model_calls": 0 if mode == "record_pages" else 1,
            "checkpoint_replays": count + 3 if mode == "record_pages" else 0,
            "original_sources_reanalyzed": False, "peak_input_tokens": 5280,
            "deterministic_values": {"accepted_record_count": count, "accepted_subset_only": partial},
            "unsupported_conclusion_count": 1,
            "context_budgets": [budget],
            "input_coverage": [{"name": "findings", "kind": "records", "record_count": count, "binding_digest": "private-input-digest"}],
            "checkpoints": {"prefix": "private-checkpoint-prefix"},
            "supported_conclusions": [{"text": "private-stage-conclusion"}],
            "original_values": ["private-original-value"],
        }
        identity = {
            "workflow_id": LOOP_WORKFLOW_ID, "run_id": LOOP_RUN_ID, "node_id": "explain",
            "execution_id": REPORT_EXECUTION_ID, "task_id": "report-task", "attempt": 1, "iteration_path": [],
        }
        manifest = {
            "contract_version": "workflow-result-v2", "identity": identity,
            "authoritative_output": "text", "outputs": {"text": {"kind": "text", "value": "Saved qualitative explanation."}},
            "execution": {"status": "succeeded"},
            "validation": {"status": "not_requested"},
            "analysis_consumption": consumption,
        }
        summary = workflow_result_summary(manifest, {
            "storage": "cosmos", "sha256": _digest(manifest), "size_bytes": 1024, "chunk_count": 1,
        })
        record = {
            **identity, "node_kind": "task", "state": "completed",
            "workflow_result": summary,
            "workflow_validation": {"version": 1, "status": "valid", "eligible": True, "counts": {}},
        }
        self.execution_pages[key][""]["items"].append(copy.deepcopy(record))
        self.attempt_pages[(*key, REPORT_EXECUTION_ID)] = _pages([copy.deepcopy(record)], 50)
        return self.attempt_pages[(*key, REPORT_EXECUTION_ID)][""]["items"][0]

    def _dispatch(self, route, entry):
        if entry.path.endswith("/workflows/editor-options"):
            group = entry.path.startswith("/api/group/")
            assert entry.query.get("group_id") == ([GROUP_ID] if group else None), entry
            self._json(route, self._options(group))
        elif entry.path.endswith("/workflows/loop-inputs/preview"):
            assert entry.method == "POST", entry
            assert entry.query.get("group_id") == ([GROUP_ID] if entry.path.startswith("/api/group/") else None), entry
            assert set(entry.body) == {"iterable", "max_items"}, entry
            if self.defer_preview:
                self.pending_preview.append((route, copy.deepcopy(entry)))
                self.defer_preview = False
                return
            self._preview(route, entry)
        elif re.fullmatch(r"/api/(user|group)/workflows/[^/]+/runs/[^/]+/executions/[^/]+/items", entry.path):
            key = self._key(entry)
            assert entry.path.split("/")[8] == LOOP_EXECUTION_ID, entry
            assert entry.query.get("limit") == ["50"], entry
            pages = self.item_pages[key]
            cursor = entry.query.get("cursor", [""])[0]
            selected = pages[cursor]
            self._json(route, {
                "items": copy.deepcopy(selected["items"]), "next_cursor": selected["next_cursor"],
                "total_count": sum(len(page["items"]) for page in pages.values()),
                "loop_execution_id": LOOP_EXECUTION_ID, "limit": 500, "frozen_at": "2026-09-18T12:00:00Z",
                "selection": copy.deepcopy(self.item_selections.get(key, {})),
            })
        elif re.fullmatch(r"/api/(user|group)/workflows/[^/]+/runs/[^/]+/executions/[^/]+/attempts/\d+/records", entry.path):
            key = self._key(entry)
            parts = entry.path.split("/")
            assert entry.query.get("limit") == ["100"], entry
            assert entry.query.get("output") == ["records"], entry
            pages = self.record_pages[(*key, parts[8], int(parts[10]))]
            cursor = entry.query.get("cursor", [""])[0]
            selected = pages[cursor]
            self._json(route, {
                "records": copy.deepcopy(selected["items"]), "next_cursor": selected["next_cursor"],
                "total_count": sum(len(page["items"]) for page in pages.values()),
                "record_offset": 0 if not cursor else len(pages[""]["items"]),
                "output_name": "records", "workflow_validation": {
                    "version": 1, "status": "valid", "eligible": True, "counts": {},
                }, "coverage": {"complete": True, "completed": 2, "failed": 0},
            })
        elif re.fullmatch(r"/api/(user|group)/workflows/[^/]+/runs/[^/]+/executions/[^/]+/attempts/\d+/provenance", entry.path):
            key = self._key(entry)
            parts = entry.path.split("/")
            assert entry.query.get("limit") == ["50"], entry
            pages = self.provenance_pages[(*key, parts[8], int(parts[10]))]
            selected = pages[entry.query.get("cursor", [""])[0]]
            self._json(route, {
                "contributors": copy.deepcopy(selected["items"]), "next_cursor": selected["next_cursor"],
                "total_count": sum(len(page["items"]) for page in pages.values()),
            })
        else:
            super()._dispatch(route, entry)

    def _preview(self, route, entry):
        iterable = entry.body["iterable"]
        assert iterable["kind"] in {"documents", "workspace_query"}, entry
        limit = min(self.ceiling, entry.body["max_items"])
        if iterable["kind"] == "documents":
            count, exact = len(iterable["documents"]), True
            items = iterable["documents"][:50]
        else:
            assert set(iterable["filters"]) <= {"search", "classification", "author", "keywords", "abstract", "tags"}
            selection = iterable["selection"]
            assert not (iterable.get("content", {}).get("mode") == "hybrid" and selection["mode"] != "best_n")
            count = min(self.query_count, selection["count"]) if selection["mode"] == "best_n" else self.query_count
            exact = selection["mode"] == "best_n" or self.query_exact
            preview_document = (
                {"document_id": "group-brief", "title": "Group brief", "scope_type": "group", "scope_id": GROUP_ID}
                if entry.path.startswith("/api/group/")
                else {"document_id": "personal-brief", "title": "Private brief", "scope_type": "personal"}
            )
            items = [preview_document] if count else []
        if count > limit:
            self._json(route, {
                "error": "The selected input exceeds this loop's admitted item limit.",
                "code": "workflow_loop_item_limit_exceeded",
                "count": count, "count_exact": exact, "limit": limit, "within_limit": False,
            }, 422)
        else:
            selection = self.preview_selection
            if selection is None:
                selection = query_selection_metadata(
                    mode=iterable["selection"]["mode"], hybrid=iterable.get("content", {}).get("mode") == "hybrid",
                ) if iterable["kind"] == "workspace_query" else {}
            self._json(route, {"count": count, "count_exact": exact, "limit": limit,
                               "within_limit": exact and count <= limit, "items": items,
                               "selection": copy.deepcopy(selection)})

    def release_preview(self):
        pending, self.pending_preview = self.pending_preview, []
        for route, entry in pending:
            self._preview(route, entry)

    def assert_clean(self):
        assert not self.pending_preview, "The preview test left a response pending."
        super().assert_clean()


@pytest.fixture
def workflow_loops_ui(page):
    fixture = WorkflowLoopsFixture(page)
    yield fixture
    fixture.assert_clean()
