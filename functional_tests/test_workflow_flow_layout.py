# test_workflow_flow_layout.py
"""
Offline regressions for the production Flow projection, TypeScript guard and layout.
Version: 0.261.121
Implemented in: 0.261.121

Imports the real compiler and projection functions, and executes the actual
TypeScript through test_support/tsResolve.mjs. A fresh-process audit rejects
application configuration imports and network access during saved/draft detail
reads. No bundle, browser, workflow invocation or storage write is needed.
"""

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "application" / "single_app"
sys.path.insert(0, str(APP_ROOT))

# Production pure modules require the application import path, not config.py.
import functions_workflow_inspection as inspection
from functions_workflow_definitions import workflow_definition_revision
from functions_workflow_flow import compile_workflow_flow


def maximum_structured_definition():
    """256 canonical IDs, region depth four, and three collapsed loop templates."""
    binding = {
        "name": "decision",
        "source": {"kind": "node_output", "node_id": "seed", "output": "json", "scope": "current"},
        "required": True, "expected_kind": "json", "allow_partial": False,
    }
    nodes = [{"id": "seed", "kind": "task", "task_id": "seed-task"}]
    for index in range(62):
        nodes.append({
            "id": f"if-{index}", "kind": "if", "inputs": [copy.deepcopy(binding)],
            "condition": {"op": "eq", "left": {"input": "decision", "path": "/ready"}, "right": {"literal": True}},
            "then": {"id": f"then-{index}", "nodes": []},
            "else": {"id": f"else-{index}", "nodes": []},
            "join": {"id": f"join-{index}", "exports": []},
        })
    current = nodes
    for index in range(3):
        loop = {
            "id": f"each-{index}", "kind": "for_each", "max_items": 5000,
            "item_key": "source_identity", "inputs": [],
            "iterable": {"kind": "documents", "documents": [{
                "document_id": f"fictional-source-{index}", "scope_type": "personal",
            }]},
            "body": {"id": f"body-{index}", "nodes": [], "outputs": []},
        }
        current.append(loop)
        current = loop["body"]["nodes"]
    return {
        "id": "maximum-flow", "user_id": "fictional-flow-reader",
        "name": "Maximum bounded Flow", "definition_version": 3, "durable_execution": True,
        "tasks": [{
            "id": "seed-task", "type": "instructions", "name": "Seed decision",
            "instructions": "Return a typed ready Boolean; this fixture never runs.",
            "inputs": [], "reference_ids": [], "runner": {"type": "inherit"},
            "output_contract": {
                "kind": "json", "allow_partial": False, "require_complete_coverage": False,
                "schema": {"type": "object", "properties": {"ready": {"type": "boolean"}}, "required": ["ready"]},
            },
        }],
        "flow": {"id": "root", "nodes": nodes, "outputs": []},
        "limits": {"max_executions": 5000, "deadline_seconds": 86400},
    }


def binding_structured_definition():
    """Compiler-authored branches, loop state, item inputs and collection exports."""
    definition = maximum_structured_definition()
    template = definition["tasks"][0]
    tasks = {
        identifier: {
            **copy.deepcopy(template), "id": f"{identifier}-task", "name": f"Inspect {identifier}",
        }
        for identifier in ("seed", "accepted", "reviewed", "update", "process-document")
    }

    def binding(name, node_id, output="json", kind="json"):
        return {
            "name": name,
            "source": {"kind": "node_output", "node_id": node_id, "output": output, "scope": "current"},
            "required": True, "expected_kind": kind, "allow_partial": False,
        }

    tasks["update"]["inputs"] = [{
        **binding("current_review", "review-loop"),
        "source": {"kind": "repeat_state", "loop_id": "review-loop", "state_name": "review", "scope": "current"},
    }, binding("seed_decision", "seed")]
    records = {
        "kind": "records", "allow_partial": False, "require_complete_coverage": False,
        "schema": {"type": "array", "items": {
            "type": "object", "properties": {"finding": {"type": "string"}}, "required": ["finding"],
        }},
    }
    tasks["process-document"]["output_contract"] = records
    tasks["process-document"]["inputs"] = [{
        **binding("document", "each"),
        "source": {"kind": "loop_item", "loop_id": "each", "scope": "current"},
    }, binding("latest_review", "review-loop", "review")]
    definition.update(
        id="binding-flow", name="Typed inspection boundaries", tasks=list(reversed(list(tasks.values()))),
        reference_inputs=[{
            "id": f"ref-{index}", "name": f"reference_{index}", "document_id": f"reference-document-{index}",
            "scope_type": "personal",
        } for index in range(2)],
        flow={
            "id": "root",
            "nodes": [
                {"id": "seed", "kind": "task", "task_id": "seed-task"},
                {
                    "id": "choose", "kind": "if", "inputs": [binding("decision", "seed")],
                    "condition": {
                        "op": "eq", "left": {"input": "decision", "path": "/ready"}, "right": {"literal": True},
                    },
                    "then": {"id": "then-path", "nodes": [{"id": "accepted", "kind": "task", "task_id": "accepted-task"}]},
                    "else": {"id": "else-path", "nodes": [{"id": "reviewed", "kind": "task", "task_id": "reviewed-task"}]},
                    "join": {
                        "id": "decision-join",
                        "exports": [{
                            "name": "review", "expected_kind": "json", "required": True,
                            "then": {"node_id": "accepted", "output": "json"},
                            "else": {"node_id": "reviewed", "output": "json"},
                        }],
                    },
                },
                {
                    "id": "review-loop", "kind": "repeat_until", "max_iterations": 1,
                    "state": [{
                        "name": "review", "initial": binding("review", "decision-join", "review")["source"],
                        "next": "next_review", "output_contract": copy.deepcopy(template["output_contract"]),
                    }],
                    "body": {
                        "id": "review-body", "nodes": [{"id": "update", "kind": "task", "task_id": "update-task"}],
                        "outputs": [binding("next_review", "update")],
                    },
                    "until": {
                        "op": "eq", "left": {"input": "review", "path": "/ready"}, "right": {"literal": True},
                    },
                    "exports": [{"name": "review", "output": "next_review"}],
                },
                {
                    "id": "each", "kind": "for_each", "max_items": 5000, "item_key": "source_identity", "inputs": [],
                    "iterable": {"kind": "documents", "documents": [{
                        "document_id": "fictional-source", "scope_type": "personal",
                    }]},
                    "body": {
                        "id": "each-body",
                        "nodes": [{"id": "process-document", "kind": "task", "task_id": "process-document-task"}],
                        "outputs": [binding("rows", "process-document", "records", "records")],
                    },
                },
                {
                    "id": "all-records", "kind": "collect", "source": {"loop_id": "each", "output": "rows"},
                    "output_contract": copy.deepcopy(records),
                },
            ],
            "outputs": [binding("results", "all-records", "records", "records")],
        },
    )
    tasks["seed"]["reference_ids"] = ["ref-1"]
    return definition


NODE_CHECKS = r"""
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const root = process.argv[1];
const input = JSON.parse(readFileSync(0, 'utf8'));
await import(pathToFileURL(path.join(root, 'functional_tests', 'test_support', 'tsResolve.mjs')));
const moduleUrl = (name) => pathToFileURL(path.join(root, 'application', 'v2_ui', 'src', 'lib', `${name}.ts`));
const inspection = await import(moduleUrl('workflowInspection'));
const layout = await import(moduleUrl('workflowFlowLayout'));
const personal = { type: 'personal' };
const target = { kind: 'saved', workflowId: input.projection.source.workflow_id };
const projection = inspection.parseWorkflowFlowProjection(input.projection, personal, target);

function frozen(value) {
    if (value && typeof value === 'object') {
        Object.values(value).forEach(frozen);
        Object.freeze(value);
    }
    return value;
}

if (input.check === 'layout') {
    const before = JSON.stringify(projection);
    frozen(projection);
    const started = performance.now();
    const boxes = layout.layoutWorkflowFlow(projection, new Set());
    assert.equal(boxes.length, 256);
    assert.ok(performance.now() - started < 2000, '256-node pure layout exceeded two seconds.');
    assert.deepEqual(layout.layoutWorkflowFlow(projection, new Set()), boxes);
    const positioned = new Map();
    for (const box of boxes) {
        for (const value of [box.position.x, box.position.y, box.width, box.height]) assert.ok(Number.isFinite(value));
        assert.ok(box.width > 0 && box.height > 0);
        if (box.parentId) {
            const parent = positioned.get(box.parentId);
            assert.ok(parent, `Parent must precede ${box.id}.`);
            assert.ok(box.position.x >= 0 && box.position.y >= 0);
            assert.ok(box.position.x + box.width <= parent.width);
            assert.ok(box.position.y + box.height <= parent.height);
        }
        for (const sibling of positioned.values()) {
            if (!box.parentId || sibling.parentId !== box.parentId) continue;
            assert.ok(
                box.position.x + box.width <= sibling.position.x ||
                sibling.position.x + sibling.width <= box.position.x ||
                box.position.y + box.height <= sibling.position.y ||
                sibling.position.y + sibling.height <= box.position.y,
                `${box.id} overlaps sibling ${sibling.id}.`,
            );
        }
        positioned.set(box.id, box);
    }
    for (let index = 0; index < 62; index += 1) {
        const then = positioned.get(`then-${index}`);
        const otherwise = positioned.get(`else-${index}`);
        const branch = positioned.get(`if-${index}`);
        const join = positioned.get(`join-${index}`);
        assert.equal(then.position.y, otherwise.position.y);
        assert.ok(then.position.x + then.width < otherwise.position.x);
        assert.ok(join.position.y >= branch.position.y + branch.height);
    }
    const renamed = structuredClone(projection);
    renamed.nodes.forEach((node) => { node.label = '<img src=x onerror="never()">'; });
    assert.deepEqual(layout.layoutWorkflowFlow(renamed, new Set()), boxes);
    assert.equal(JSON.stringify(projection), before, 'Layout mutated executable projection data.');
} else if (input.check === 'collapse') {
    const collapsed = new Set(['each-0', 'each-1', 'each-2']);
    const boxes = layout.layoutWorkflowFlow(projection, collapsed);
    assert.equal(boxes.length, 251, 'Loop instances must not become graph nodes.');
    assert.ok(!boxes.some((box) => box.id === 'body-0' || box.id === 'each-1'));
    const visibleIds = new Set(boxes.map((box) => box.id));
    const edges = layout.visibleWorkflowEdges(projection, collapsed);
    const keys = new Set();
    for (const edge of edges) {
        assert.ok(visibleIds.has(edge.source) && visibleIds.has(edge.target));
        assert.notEqual(edge.source, edge.target);
        const key = JSON.stringify([edge.source, edge.target, edge.kind, edge.label]);
        assert.ok(!keys.has(key), 'Collapsed relationships must not be duplicated.');
        keys.add(key);
    }
    const byId = new Map(projection.nodes.map((node) => [node.id, node]));
    assert.equal(layout.visibleWorkflowNode('body-2', byId, collapsed), 'each-0');
    assert.throws(() => layout.visibleWorkflowNode('missing', byId, collapsed), /unavailable/);
    assert.ok(edges.some((edge) => edge.label.startsWith('Empty region:')));
    assert.equal(layout.layoutWorkflowFlow(projection, new Set()).length, 256);
} else if (input.check === 'guards') {
    assert.deepEqual(
        projection.nodes.filter((node) => inspection.inspectionNodeHasExecution(node, projection.root_region_id))
            .map((node) => node.id).sort(),
        [...input.execution_node_ids].sort(),
        'Only compiler nodes and the engine root can have execution records; nested regions cannot.',
    );
    const reject = (change) => {
        const value = structuredClone(projection);
        change(value);
        assert.throws(() => inspection.parseWorkflowFlowProjection(value, personal, target), /unsupported|mismatched/);
    };
    reject((value) => { value.settings = { private_key: 'must-not-cross' }; });
    reject((value) => { value.nodes[1].instructions = 'No eager task instructions'; });
    reject((value) => { value.nodes.push(structuredClone(value.nodes[1])); });
    reject((value) => { value.nodes[1].id = value.nodes[0].id; });
    reject((value) => { value.nodes[1].parent_id = value.nodes[1].id; });
    reject((value) => { value.nodes[1].parent_id = null; });
    reject((value) => { value.nodes[1].loop_ids = ['each-0']; });
    reject((value) => { value.edges[0].target = 'missing'; });
    reject((value) => { value.edges.push(structuredClone(value.edges[0])); });
    reject((value) => { value.source.workflow_id = 'another-workflow'; });
    reject((value) => { value.source.definition_revision = 'not-a-revision'; });
    reject((value) => { value.limits.max_executions = 5001; });
    reject((value) => { value.definition_version = 2; });
    reject((value) => { value.nodes.find((node) => node.id === 'each-0').max_items = 5001; });
    const group = { type: 'group', groupId: 'group-alpha' };
    const grouped = structuredClone(projection);
    grouped.source.scope_type = 'group';
    grouped.source.scope_id = 'group-alpha';
    inspection.parseWorkflowFlowProjection(grouped, group, target);
    assert.throws(() => inspection.parseWorkflowFlowProjection(grouped, { ...group, groupId: 'group-beta' }, target));
    const run = structuredClone(projection);
    run.source.kind = 'run';
    run.source.run_id = 'frozen-run';
    run.source.snapshot_sha256 = 'a'.repeat(64);
    inspection.parseWorkflowFlowProjection(run, personal, { ...target, kind: 'run', runId: 'frozen-run' });
    assert.throws(() => inspection.parseWorkflowFlowProjection(run, personal, { ...target, kind: 'run', runId: 'other-run' }));
    assert.throws(() => inspection.parseWorkflowFlowProjection(run, personal, target));
    const draft = { kind: 'draft', definition: input.definition };
    inspection.parseWorkflowFlowProjection(input.preview, personal, draft);
    assert.match(input.preview.source.definition_revision, /^DRAFT:[a-f0-9]{64}$/);
    assert.throws(() => inspection.parseWorkflowFlowProjection(input.preview, personal, target));
    const unmarkedDraft = structuredClone(input.preview);
    unmarkedDraft.source.definition_revision = unmarkedDraft.source.definition_revision.slice(6);
    assert.throws(() => inspection.parseWorkflowFlowProjection(unmarkedDraft, personal, draft));
    reject((value) => { value.source.definition_revision = input.preview.source.definition_revision; });
    const prefixedRun = structuredClone(run);
    prefixedRun.source.definition_revision = input.preview.source.definition_revision;
    assert.throws(() => inspection.parseWorkflowFlowProjection(
        prefixedRun, personal, { ...target, kind: 'run', runId: 'frozen-run' },
    ));
} else if (input.check === 'details') {
    const source = projection.source;
    const details = {
        projection_version: 1, source, node_id: 'seed', section: 'configuration',
        items: [{ label: 'Exact JSON', value: { zero: 0, false: false, empty: [], nil: null } }],
        total_count: 1, next_cursor: null,
    };
    assert.deepEqual(inspection.parseWorkflowInspectionDetails(details, source, 'seed', 'configuration').items, details.items);
    assert.equal(inspection.parseWorkflowInspectionDetails(
        { ...details, total_count: Number.MAX_SAFE_INTEGER, next_cursor: 'more-details' },
        source, 'seed', 'configuration',
    ).total_count, Number.MAX_SAFE_INTEGER);
    const reject = (change) => {
        const value = structuredClone(details);
        change(value);
        assert.throws(() => inspection.parseWorkflowInspectionDetails(value, source, 'seed', 'configuration'), /unsupported|mismatched/);
    };
    reject((value) => { value.source.definition_revision = 'b'.repeat(64); });
    reject((value) => { value.source.scope_id = 'another-reader'; });
    reject((value) => { value.node_id = 'other'; });
    reject((value) => { value.section = 'outputs'; });
    reject((value) => { value.private_snapshot = {}; });
    reject((value) => { value.items[0].raw_state = {}; });
    reject((value) => { value.items[0].value = 'x'.repeat(256 * 1024); });
    reject((value) => { value.items = Array.from({ length: 51 }, () => details.items[0]); value.total_count = 51; });
    reject((value) => { value.total_count = 0; });
    for (const total of [-1, 0.5, NaN, Infinity, Number.MAX_SAFE_INTEGER + 1, '5001', null]) {
        reject((value) => { value.total_count = total; });
    }
    reject((value) => { value.next_cursor = 42; });
    const nested = projection.nodes.find((node) => node.id === 'body-2');
    const frames = [0, 1, 2].map((index) => ({ loop_id: `each-${index}`, item_id: 'a'.repeat(64), index }));
    assert.deepEqual(inspection.inspectionNodePath(nested, frames), frames);
    assert.equal(inspection.inspectionNodePath(nested, frames.slice(1)), null);
    assert.equal(inspection.inspectionNodePath(nested, []), null);
    assert.deepEqual(inspection.inspectionNodePath(projection.nodes[0], frames), []);
} else if (input.check === 'bindings') {
    const nodes = new Map(projection.nodes.map((node) => [node.id, node]));
    frozen(projection);
    for (const entry of input.binding_cases) {
        const node = nodes.get(entry.node_id);
        assert.ok(node);
        const details = inspection.parseWorkflowInspectionDetails(
            entry.details, projection.source, node.id, entry.section,
        );
        const before = JSON.stringify(details);
        frozen(details);
        const bindings = inspection.workflowInspectionBindings(node, details);
        assert.deepEqual(bindings, entry.expected, `${node.id}: ${entry.section}`);
        assert.ok(bindings.every((binding) => nodes.has(binding.sourceId)));
        assert.deepEqual(inspection.workflowInspectionBindings(node, null), []);
        assert.deepEqual(inspection.workflowInspectionBindings(node, { ...details, node_id: 'another-node' }), []);
        assert.equal(JSON.stringify(details), before);
    }
    const malformed = [
        ['decision-join', 'outputs', (value) => ({ ...value, else: { node_id: null, output: 'json' } })],
        ['review-loop', 'state', (value) => ({ ...value, next: 2 })],
        ['all-records', 'configuration', (value) => ({ ...value, private_snapshot: {} })],
        ['update', 'inputs', (value) => ({ ...value, source: { ...value.source, kind: 'future-source' } })],
    ];
    for (const [id, section, change] of malformed) {
        const details = input.binding_cases.find((entry) => entry.node_id === id && entry.section === section).details;
        const item = details.items[0];
        assert.deepEqual(inspection.workflowInspectionBindings(nodes.get(id), {
            ...details, items: [{ ...item, value: change(item.value) }],
        }), []);
    }
} else if (input.check === 'selection') {
    const parsed = input.selection_pages.map((page) => inspection.parseWorkflowInspectionDetails(
        page, projection.source, 'each-0', 'selection',
    ));
    for (const page of parsed) {
        assert.equal(page.total_count, 5001, '5000 documents plus the Iterable row must remain inspectable.');
        assert.equal(page.items.length, 50);
        assert.ok(page.next_cursor);
    }
    assert.equal(parsed[0].items[0].label, 'Iterable');
    assert.equal(parsed[0].items[1].value.document_id, 'selection-document-0000');
    assert.equal(parsed[1].items[0].value.document_id, 'selection-document-0049');
    assert.equal(parsed[1].items[49].value.document_id, 'selection-document-0098');
    const firstIds = new Set(parsed[0].items.slice(1).map((item) => item.value.document_id));
    assert.ok(parsed[1].items.every((item) => !firstIds.has(item.value.document_id)));
    const tooMany = structuredClone(input.selection_pages[0]);
    tooMany.items.push(structuredClone(tooMany.items[1]));
    assert.throws(() => inspection.parseWorkflowInspectionDetails(tooMany, projection.source, 'each-0', 'selection'));
    const tooLarge = structuredClone(input.selection_pages[0]);
    tooLarge.items[1].value.document_id = 'x'.repeat(256 * 1024);
    assert.throws(() => inspection.parseWorkflowInspectionDetails(tooLarge, projection.source, 'each-0', 'selection'));
    const references = input.reference_pages.map((page) => inspection.parseWorkflowInspectionDetails(
        page, projection.source, page.node_id, 'selection',
    ));
    assert.deepEqual(references.map((page) => [page.node_id, page.items.length, page.total_count]), [
        ['root', 50, 60], ['root', 10, 60], ['seed', 2, 2],
    ]);
    assert.equal(references[1].next_cursor, null);
    assert.deepEqual(references[2].items.map((item) => item.label), ['reference_0', 'reference_59']);
} else if (input.check === 'transport') {
    const calls = [];
    let response = projection;
    globalThis.fetch = async (url, options) => {
        calls.push({ url: new URL(url, 'http://simplechat.test'), ...options });
        return new Response(JSON.stringify(response), { headers: { 'Content-Type': 'application/json' } });
    };
    const controller = new AbortController();
    await inspection.fetchWorkflowFlowProjection(personal, target, controller.signal);
    assert.equal(calls.at(-1).method, 'GET');
    assert.equal(calls.at(-1).url.pathname, `/api/user/workflows/${target.workflowId}/flow`);
    assert.equal(calls.at(-1).signal, controller.signal);
    const source = { ...projection.source, kind: 'run', scope_type: 'group', scope_id: 'group/alpha',
        run_id: 'frozen/run', snapshot_sha256: 'a'.repeat(64) };
    const group = { type: 'group', groupId: source.scope_id };
    const selectedRun = { kind: 'run', workflowId: target.workflowId, runId: source.run_id };
    response = { ...projection, source };
    await inspection.fetchWorkflowFlowProjection(group, selectedRun, controller.signal);
    assert.equal(calls.at(-1).url.pathname, `/api/group/workflows/${target.workflowId}/runs/frozen%2Frun/flow`);
    assert.equal(calls.at(-1).url.searchParams.get('group_id'), 'group/alpha');
    response = { projection_version: 1, source, node_id: 'seed', section: 'inputs', items: [], total_count: 0, next_cursor: null };
    await inspection.fetchWorkflowInspectionDetails(group, selectedRun, source, 'seed', 'inputs', 'exact-page', controller.signal);
    assert.equal(calls.at(-1).url.searchParams.get('node_id'), 'seed');
    assert.equal(calls.at(-1).url.searchParams.get('section'), 'inputs');
    assert.equal(calls.at(-1).url.searchParams.get('revision'), source.definition_revision);
    assert.equal(calls.at(-1).url.searchParams.get('cursor'), 'exact-page');
    assert.equal(calls.at(-1).url.searchParams.get('limit'), '50');
    assert.equal(calls.at(-1).url.searchParams.get('group_id'), 'group/alpha');
    const draft = { kind: 'draft', definition: input.definition };
    response = input.preview;
    await inspection.fetchWorkflowFlowProjection(personal, draft, controller.signal);
    assert.equal(calls.at(-1).method, 'POST');
    assert.equal(calls.at(-1).url.pathname, '/api/user/workflows/flow-preview');
    assert.deepEqual(JSON.parse(calls.at(-1).body), { definition: input.definition });
    response = input.preview_details;
    await inspection.fetchWorkflowInspectionDetails(
        personal, draft, input.preview.source, 'seed', 'configuration', null, controller.signal,
    );
    assert.equal(calls.at(-1).method, 'POST');
    assert.equal(calls.at(-1).url.pathname, '/api/user/workflows/flow-preview');
    assert.deepEqual(JSON.parse(calls.at(-1).body), {
        definition: input.definition, node_id: 'seed', section: 'configuration',
        revision: input.preview.source.definition_revision, limit: 50,
    });
    assert.ok(calls.every((call) => call.signal === controller.signal));
    assert.equal(calls.length, 5, 'Inspection must not scan history or trigger workflow writes.');
}
console.log(JSON.stringify({ check: input.check, nodes: projection.nodes.length }));
"""


def run_typescript(script, payload, label):
    result = subprocess.run(
        ["node", "--input-type=module", "--eval", script, str(ROOT)],
        input=json.dumps(payload), cwd=ROOT, text=True, capture_output=True, timeout=30, check=False,
    )
    assert result.returncode == 0, f"Production TypeScript {label} check failed:\n{result.stdout}\n{result.stderr}"
    return json.loads(result.stdout)


@pytest.mark.parametrize("check", ["layout", "collapse", "guards", "details", "transport"])
def test_production_projection_layout_and_guard(check):
    definition = maximum_structured_definition()
    original = copy.deepcopy(definition)
    compiled = compile_workflow_flow(definition)
    helpers = inspection
    projection = helpers.workflow_flow_inspection(definition)
    assert len(compiled["nodes"]) + len(compiled["regions"]) == 256
    assert len(projection["nodes"]) == 256
    assert set(node["id"] for node in projection["nodes"]) == set(compiled["nodes"]) | set(compiled["regions"])
    assert max(len(node["loop_ids"]) for node in projection["nodes"]) == 3
    depths = []
    for region_id in compiled["regions"]:
        depth = 1
        parent = compiled["regions"][region_id]["parent"]
        while parent is not None:
            depth += 1
            parent = compiled["regions"][compiled["nodes"][parent]["region_id"]]["parent"]
        depths.append(depth)
    assert max(depths) == 4
    assert "instructions" not in json.dumps(projection)
    assert "fictional-source" not in json.dumps(projection)
    preview = helpers.preview_workflow_flow(definition, user_id=definition["user_id"])
    preview_details = helpers.preview_workflow_flow(
        definition, user_id=definition["user_id"], node_id="seed", section="configuration",
        revision=preview["source"]["definition_revision"], limit=50,
    )
    assert definition == original
    assert workflow_definition_revision(definition) == workflow_definition_revision(original)
    result = run_typescript(NODE_CHECKS, {
        "check": check, "projection": projection, "preview": preview,
        "preview_details": preview_details, "definition": definition,
        "execution_node_ids": [*compiled["nodes"], compiled["flow"]["id"]],
    }, check)
    assert result["nodes"] == 256


def test_binding_helper_uses_actual_compiled_inputs_and_boundary_exports():
    definition = binding_structured_definition()
    original = copy.deepcopy(definition)
    helpers = inspection
    projection = helpers.workflow_flow_inspection(definition)
    cases = [
        ("choose", "inputs", [{"sourceId": "seed", "label": "decision: json"}]),
        ("update", "inputs", [
            {"sourceId": "review-loop", "label": "current_review: json"},
            {"sourceId": "seed", "label": "seed_decision: json"},
        ]),
        ("process-document", "inputs", [
            {"sourceId": "each", "label": "document: json"},
            {"sourceId": "review-loop", "label": "latest_review: json"},
        ]),
        ("decision-join", "outputs", [
            {"sourceId": "accepted", "label": "review (Then): json"},
            {"sourceId": "reviewed", "label": "review (Else): json"},
        ]),
        ("review-loop", "state", [
            {"sourceId": "decision-join", "label": "review initial: json"},
            {"sourceId": "review-body", "label": "review next: body export next_review"},
        ]),
        ("review-body", "outputs", [{"sourceId": "update", "label": "next_review: json"}]),
        ("each", "outputs", [{"sourceId": "process-document", "label": "rows: records"}]),
        ("each-body", "outputs", [{"sourceId": "process-document", "label": "rows: records"}]),
        ("root", "outputs", [{"sourceId": "all-records", "label": "results: records"}]),
        ("all-records", "configuration", [{"sourceId": "each", "label": "Every frozen item: rows"}]),
        ("seed", "configuration", []),
        ("seed", "outputs", []),
        ("seed", "selection", []),
        ("root", "selection", []),
    ]
    details = [{
        "node_id": node_id, "section": section, "expected": expected,
        "details": helpers.workflow_flow_inspection(
            definition, node_id=node_id, section=section, revision=projection["source"]["definition_revision"], limit=50,
        ),
    } for node_id, section, expected in cases]
    result = run_typescript(NODE_CHECKS, {
        "check": "bindings", "projection": projection, "binding_cases": details,
    }, "compiler-derived binding boundaries")
    assert result["nodes"] == len(projection["nodes"])
    assert definition == original


def test_source_selection_accepts_5001_total_but_keeps_detail_pages_bounded():
    definition = maximum_structured_definition()
    definition["flow"]["nodes"][-1]["iterable"]["documents"] = [{
        "document_id": f"selection-document-{index:04d}", "scope_type": "personal",
    } for index in range(5000)]
    definition["reference_inputs"] = [{
        "id": f"ref-{index}", "name": f"reference_{index}", "document_id": f"reference-document-{index}",
        "scope_type": "personal",
    } for index in range(60)]
    definition["tasks"][0]["reference_ids"] = ["ref-0", "ref-59"]
    original = copy.deepcopy(definition)
    helpers = inspection
    projection = helpers.workflow_flow_inspection(definition)
    revision = projection["source"]["definition_revision"]

    def page(node_id, cursor=None):
        return helpers.workflow_flow_inspection(
            definition, node_id=node_id, section="selection", revision=revision, cursor=cursor, limit=50,
        )

    selection = page("each-0")
    references = page("root")
    assert "selection-document-" not in json.dumps(projection)
    assert "reference-document-" not in json.dumps(projection)
    result = run_typescript(NODE_CHECKS, {
        "check": "selection", "projection": projection,
        "selection_pages": [selection, page("each-0", selection["next_cursor"])],
        "reference_pages": [references, page("root", references["next_cursor"]), page("seed")],
    }, "bounded source selections")
    assert result["nodes"] == 256
    assert definition == original


def test_production_inspection_import_and_details_require_no_config_or_network():
    definition = binding_structured_definition()
    next(task for task in definition["tasks"] if task["id"] == "seed-task")["document_action"] = {
        "type": "analyze", "analysis_options": {},
    }
    script = r"""
import importlib.abc
import json
import sys

config_attempts = []
network_attempts = []

class RejectApplicationConfig(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "config" or fullname.startswith("config."):
            config_attempts.append(fullname)
            raise AssertionError("Pure Flow inspection imported application configuration.")
        return None

def reject_network(event, arguments):
    if event in {"socket.connect", "socket.getaddrinfo", "http.client.connect"}:
        network_attempts.append(event)
        raise AssertionError(f"Pure Flow inspection attempted network access: {event}")

assert "config" not in sys.modules
sys.meta_path.insert(0, RejectApplicationConfig())
sys.addaudithook(reject_network)
sys.path.insert(0, sys.argv[1])

# The production import deliberately follows the offline guards and path setup.
from functions_workflow_inspection import FLOW_DETAIL_SECTIONS, preview_workflow_flow, workflow_flow_inspection

definition = json.load(sys.stdin)
before = json.dumps(definition, sort_keys=True)
new_draft = json.loads(before)
new_draft.pop("id")
checked = 0
nodes = 0
for authored, draft in ((definition, False), (definition, True), (new_draft, True)):
    reader = preview_workflow_flow if draft else workflow_flow_inspection
    options = {"user_id": authored["user_id"]} if draft else {}
    projection = reader(authored, **options)
    nodes = len(projection["nodes"])
    if draft:
        assert projection["source"]["definition_revision"].startswith("DRAFT:")
        assert projection["source"]["workflow_id"] == authored.get("id")
    for node in projection["nodes"]:
        for section in FLOW_DETAIL_SECTIONS:
            detail = reader(
                authored, node_id=node["id"], section=section,
                revision=projection["source"]["definition_revision"], limit=50, **options,
            )
            assert detail["source"] == projection["source"]
            assert detail["node_id"] == node["id"] and detail["section"] == section
            assert len(detail["items"]) <= 50
            checked += 1
assert json.dumps(definition, sort_keys=True) == before
assert not config_attempts and not network_attempts
assert "config" not in sys.modules
print(json.dumps({"details": checked, "nodes": nodes, "sections": len(FLOW_DETAIL_SECTIONS)}))
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", script, str(APP_ROOT)],
        input=json.dumps(definition), cwd=ROOT, text=True, capture_output=True, timeout=90, check=False,
    )
    assert result.returncode == 0, f"Pure inspection crossed its import/read boundary:\n{result.stdout}\n{result.stderr}"
    checked = json.loads(result.stdout)
    assert checked["sections"] == 6
    assert checked["details"] == 3 * 6 * checked["nodes"]


def test_existing_list_save_payload_can_preview_preserved_metadata_without_a_write():
    definition = maximum_structured_definition()
    definition.update(
        metadata={"legacy": {"retained": False}},
        alert_settings={"owner_on_failure": True},
        publication_options={"publish_to_public_workspace": False},
    )
    definition["definition_revision"] = workflow_definition_revision(definition)
    original = copy.deepcopy(definition)
    script = r"""
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
const root = process.argv[1];
await import(pathToFileURL(path.join(root, 'functional_tests', 'test_support', 'tsResolve.mjs')));
const { normalizeWorkflowDefinition, workflowForSave } = await import(
    pathToFileURL(path.join(root, 'application', 'v2_ui', 'src', 'lib', 'workflowEditor.ts')),
);
const input = JSON.parse(readFileSync(0, 'utf8'));
const scope = { type: 'personal' };
const original = normalizeWorkflowDefinition(input, scope);
const payload = workflowForSave(original, original, scope);
assert.deepEqual(payload.metadata, input.metadata);
assert.deepEqual(payload.alert_settings, input.alert_settings);
assert.deepEqual(payload.publication_options, input.publication_options);
assert.equal(payload.definition_revision, input.definition_revision);
console.log(JSON.stringify(payload));
"""
    payload = run_typescript(script, definition, "preserved List save payload")
    preview = inspection.preview_workflow_flow(payload, user_id=definition["user_id"])
    assert preview["source"]["kind"] == "draft"
    assert preview["source"]["definition_revision"].startswith("DRAFT:")
    assert len(preview["nodes"]) == 256
    assert payload["definition_revision"] == original["definition_revision"]
    assert definition == original
    assert "metadata" not in preview and "alert_settings" not in preview and "publication_options" not in preview


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
