# functions_workflow_inspection.py
"""Read-only, compiler-derived workflow topology and bounded authored details."""

import json
import math
import re

from functions_analysis_access import (
    AnalysisResultUnavailable, authorize_analysis_sources, resolve_analysis_source_manifest,
)
from functions_document_analysis_results import normalize_analysis_options
from functions_workflow_bindings import WorkflowInputError, authorize_workflow_reference
from functions_workflow_definitions import (
    WorkflowDefinitionConflict, WorkflowDefinitionError, normalize_workflow_definition,
    normalize_workflow_references, workflow_definition_revision,
)
from functions_workflow_flow import compile_workflow_flow, normalize_flow_bindings
from functions_workflow_identity import canonical_digest
from functions_workflow_loop_history import _next_cursor, _page_position
from functions_workflow_loop_inputs import _default_authorize_scope
from functions_workflow_runtime_store import WorkflowRuntimeConflict, workflow_runtime_store


FLOW_PROJECTION_VERSION = 1
FLOW_DETAIL_MAX_BYTES = 240 * 1024
FLOW_DETAIL_SECTIONS = frozenset({"configuration", "inputs", "condition", "outputs", "state", "selection"})
_PREVIEW_PRESERVED_FIELDS = frozenset({
    "metadata", "alerts", "alert_settings", "document_actions", "publication", "publication_options",
})
_DIGEST = re.compile(r"[a-f0-9]{64}\Z")


class WorkflowFlowUnsupported(ValueError):
    public_message = "Flow inspection requires a supported version-3 structured definition and, for runs, a frozen schema-2 snapshot."
    code = "workflow_flow_unsupported"


class WorkflowFlowDetailTooLarge(ValueError):
    public_message = "This complete definition detail exceeds the inline inspection limit. No shortened detail was returned."
    code = "workflow_flow_detail_limit"


def _text(value, maximum=256):
    if not isinstance(value, str) or len(value) > maximum:
        raise WorkflowDefinitionError("A workflow inspection field exceeds its supported text bound.")
    return value


def _fields(value, *, text=(), boolean=(), numeric=()):
    """Nested configuration is projected by type and field, never copied wholesale."""
    if not isinstance(value, dict):
        raise WorkflowDefinitionError("A workflow configuration section must be an object.")
    result = {}
    for name in text:
        if name in value:
            result[name] = _text(value[name])
    for name in boolean:
        if name in value:
            if type(value[name]) is not bool:
                raise WorkflowDefinitionError("A workflow configuration flag must be boolean.")
            result[name] = value[name]
    for name in numeric:
        if name in value:
            number = value[name]
            if number is not None and not (
                type(number) is int or type(number) is float and math.isfinite(number)
            ):
                raise WorkflowDefinitionError("A workflow configuration number must be finite.")
            result[name] = number
    return result


def _runner(value):
    result = _fields(value, text=("type", "model_endpoint_id", "model_id", "model_provider"))
    if any("://" in item for item in result.values()):
        raise WorkflowDefinitionError("Workflow runners must use configured identifiers, not provider URLs.")
    if "selected_agent" in value and value["selected_agent"] is not None:
        result["selected_agent"] = _fields(
            value["selected_agent"], text=("id", "name", "display_name", "group_id"),
            boolean=("is_global", "is_group"),
        )
    return result


def _action(value):
    result = _fields(
        value, text=("type", "doc_scope", "analysis_mode", "target_mode", "window_unit", "loop_id"),
        numeric=("window_size", "window_percent", "max_retries_per_window", "recent_window_minutes"),
    )
    if "analysis_options" in value or "transformation_spec" in value:
        result["analysis_options"] = normalize_analysis_options(
            value.get("analysis_options"), value.get("transformation_spec"),
        )
    return result


def _row(label, value):
    return {"label": label, "value": value}


def _label(value, fallback):
    return value[:120] if isinstance(value, str) and value.strip() else fallback


def _detail_name(value):
    if not isinstance(value, str):
        raise WorkflowDefinitionError("An authored workflow or task name must be text.")
    if len(value) > FLOW_DETAIL_MAX_BYTES:
        raise WorkflowFlowDetailTooLarge()
    return value


def _task_label(task):
    name = _label(task.get("name"), task["id"])
    if task.get("publication") is not None:
        return f"Publish: {name}"
    if isinstance(task.get("document_action"), dict) and task["document_action"].get("type") == "analyze":
        return f"Analyze: {name}"
    return name


def _inputs(node, tasks):
    if node["kind"] == "task":
        return tasks[node["task_id"]]["inputs"]
    if node["kind"] == "repeat_until":
        return normalize_flow_bindings([{
            "name": slot["name"], "source": slot["initial"], "required": True,
            "expected_kind": slot["output_contract"]["kind"],
            "allow_partial": slot["output_contract"]["allow_partial"],
        } for slot in node["state"]])
    return node.get("inputs", [])


def _outputs(node, tasks):
    kind = node["kind"]
    if kind == "task":
        contract = tasks[node["task_id"]].get("output_contract")
        return [_row("Output contract", contract)] if contract is not None else []
    if kind == "collect":
        return [_row("Output contract", node["output_contract"])]
    if kind == "for_each":
        return [_row(binding["name"], binding) for binding in node["body"]["outputs"]]
    return [_row(item["name"], item) for item in node.get("exports", node.get("outputs", []))]


def _topology(compiled):
    tasks = {task["id"]: task for task in compiled["tasks"]}
    nodes, edges = [], []

    def edge(source, target, kind, label):
        edges.append({
            "id": f"flow-edge:{len(edges)}", "source": source, "target": target, "kind": kind, "label": label,
        })

    def boundary(region_id):
        parent_id = compiled["regions"][region_id]["parent"]
        if parent_id is None:
            return region_id, "complete", "Workflow complete"
        parent = compiled["nodes"][parent_id]["node"]
        if parent["kind"] == "if":
            return parent["join"]["id"], "join", "Branch complete"
        if parent["kind"] == "repeat_until":
            return parent_id, "repeat", f"After body: evaluate Until; false repeats within batch of {parent['max_iterations']}"
        return parent_id, "repeat", "Item complete; next frozen item if available"

    def following(node, region_id):
        target = compiled["successor"].get(node["id"])
        return (target, "sequence", "Next") if target else boundary(region_id)

    def project_node(node, region_id, order):
        kind = node["kind"]
        children = (
            [node["then"]["id"], node["else"]["id"]] if kind == "if"
            else [node["body"]["id"]] if kind in {"for_each", "repeat_until"} else []
        )
        result = {
            "id": node["id"], "kind": kind,
            "label": _task_label(tasks[node["task_id"]]) if kind == "task" else {
                "if": "If", "join": "Join", "route": "Route", "for_each": "For each",
                "repeat_until": "Repeat until", "collect": "Collect",
            }[kind],
            "parent_id": region_id, "region_id": region_id, "order": order,
            "loop_ids": compiled["node_loop_ids"][node["id"]], "child_region_ids": children,
            "inputs_count": len(_inputs(node, tasks)), "outputs_count": len(_outputs(node, tasks)),
            "has_condition": any(key in node for key in ("condition", "run_when", "until")),
        }
        for name in ("task_id", "max_items", "max_iterations"):
            if name in node:
                result[name] = node[name]
        nodes.append(result)

    def region(current, label, order=0):
        identifier = current["id"]
        parent_id = compiled["regions"][identifier]["parent"]
        nodes.append({
            "id": identifier, "kind": "region", "label": label, "parent_id": parent_id,
            "region_id": identifier, "order": order, "loop_ids": compiled["node_loop_ids"][identifier],
            "child_region_ids": [], "inputs_count": 0, "outputs_count": len(current.get("outputs", [])),
            "has_condition": False,
        })
        if parent_id is not None:
            if current["nodes"]:
                edge(identifier, current["nodes"][0]["id"], "sequence", "Enter region")
            else:
                target, kind, completion = boundary(identifier)
                edge(identifier, target, kind, f"Empty region: {completion}")
        position = 0
        for node in current["nodes"]:
            project_node(node, identifier, position)
            position += 1
            target, connection, completion = following(node, identifier)
            kind = node["kind"]
            if kind == "if":
                join = compiled["nodes"][node["join"]["id"]]["node"]
                project_node(join, identifier, position)
                position += 1
                edge(node["id"], node["then"]["id"], "then", "True")
                edge(node["id"], node["else"]["id"], "else", "False")
                region(node["then"], "Then")
                region(node["else"], "Else", 1)
                edge(join["id"], target, connection, completion)
            elif kind in {"for_each", "repeat_until"}:
                repeat = kind == "repeat_until"
                edge(node["id"], node["body"]["id"], "body", "Body before Until" if repeat else "Frozen item body")
                region(node["body"], "Repeat body" if repeat else "For each body")
                edge(node["id"], target, "complete", "After body: Until true" if repeat else "All frozen items complete")
            elif kind == "route":
                destination = node["target"]
                if "node_id" in destination:
                    edge(node["id"], destination["node_id"], "route", "True: route forward")
                else:
                    exit_target, _, _ = boundary(destination["exit_region_id"])
                    edge(node["id"], exit_target, "exit", "True: exit branch region")
                edge(node["id"], target, connection, f"False: {completion}")
            else:
                if "run_when" in node:
                    completion = f"Run when true; otherwise intentionally skip. {completion}"
                edge(node["id"], target, connection, completion)

    region(compiled["flow"], "Workflow")
    return nodes, edges


def _configuration(workflow, node, tasks, compiled):
    kind = node["kind"]
    if kind == "task":
        task = tasks[node["task_id"]]
        rows = [_row("Task", task["id"]), _row("Task name", _detail_name(task.get("name", ""))),
                _row("Instructions", task["instructions"]),
                _row("Runner", _runner(task.get("runner", {"type": "inherit"})))]
        if task.get("output_contract") is not None:
            rows.append(_row("Output contract", task["output_contract"]))
        if "input_processing" in task:
            rows.append(_row("Input processing", task["input_processing"]))
        if task.get("approval") is not None:
            rows.append(_row("Approval", {
                "required": task["approval"].get("required", False),
                "message": _text(task["approval"].get("message", ""), 1000),
            }))
        if task.get("document_action") is not None:
            rows.append(_row("Document action", _action(task["document_action"])))
        if task.get("publication") is not None:
            rows.append(_row("Publication", _fields(
                task["publication"],
                text=("source_kind", "artifact_format", "workspace_scope", "group_id", "public_workspace_id", "completion_policy"),
            )))
        return rows
    if kind == "region":
        rows = [_row("Region", node["id"])]
        if node["id"] == compiled["flow"]["id"]:
            rows.extend([
                _row("Workflow name", _detail_name(workflow.get("name", ""))),
                _row("Run limits", compiled["limits"]),
                _row("Workflow runner", _runner({
                    "type": workflow.get("runner_type", "model"),
                    **{key: workflow[key] for key in ("selected_agent", "model_endpoint_id", "model_id", "model_provider")
                       if key in workflow},
                })),
            ])
        return rows
    if kind == "for_each":
        return [_row("Maximum items", node["max_items"]), _row("Item key", node["item_key"]),
                _row("Execution", "Serial frozen-item body template")]
    if kind == "repeat_until":
        return [_row("Maximum iterations per automatic batch", node["max_iterations"]),
                _row("Condition timing", "Until is evaluated after the body and next-state validation."),
                _row("Batch exhaustion", "Pauses for an explicit authorized continuation; lifetime limits never reset.")]
    if kind == "route":
        return [_row("True target", node["target"]), _row("False path", "Continue to the next sibling or region boundary.")]
    if kind == "collect":
        return [_row("Collection source", node["source"]), _row("Output contract", node["output_contract"])]
    return [_row("Control", "Explicit branch join" if kind == "join" else "Typed conditional branch")]


def _references(workflow, task=None):
    references = normalize_workflow_references(
        workflow.get("reference_inputs", []), user_id=workflow["user_id"], group_id=workflow.get("group_id", ""),
    )
    selected = task.get("reference_ids") if task is not None else None
    if selected is not None:
        if not isinstance(selected, list) or any(not isinstance(value, str) for value in selected):
            raise WorkflowDefinitionError("Selected shared references must be document identifiers.")
        references = [reference for reference in references if reference["id"] in selected]
    return references


def _selection(workflow, node, tasks):
    if node["kind"] == "for_each":
        iterable = node["iterable"]
        rows = [_row("Iterable", {name: iterable[name] for name in ("kind", "name", "filters", "content", "selection")
                                 if name in iterable})]
        rows.extend(_row("Document", value) for value in iterable.get("documents", []))
        rows.extend(_row("Workspace", value) for value in iterable.get("scopes", []))
        return rows
    if node["kind"] not in {"task", "region"}:
        return []
    if node["kind"] == "region" and node["id"] != workflow["flow"]["id"]:
        return []
    task = tasks[node["task_id"]] if node["kind"] == "task" else None
    rows = [_row(reference["name"], reference) for reference in _references(workflow, task)]
    action = (task if task is not None else workflow).get("document_action") or {}
    if not isinstance(action, dict):
        raise WorkflowDefinitionError("Document selection configuration must be an object.")
    for name, label in (
        ("document_ids", "Selected document"), ("right_document_ids", "Comparison document"),
        ("active_group_ids", "Source group"), ("active_public_workspace_id", "Source public workspace"),
    ):
        values = action.get(name, [])
        if not isinstance(values, list) or len(values) > 5000:
            raise WorkflowDefinitionError("Document selections must be bounded identifier lists.")
        rows.extend(_row(label, {name: _text(value)}) for value in values)
    if action.get("left_document_id"):
        rows.append(_row("Comparison source", {"document_id": _text(action["left_document_id"])}))
    return rows


def _detail_rows(workflow, compiled, node_id, section):
    if node_id in compiled["regions"]:
        node = {"kind": "region", **compiled["regions"][node_id]["region"]}
    elif node_id in compiled["nodes"]:
        node = compiled["nodes"][node_id]["node"]
    else:
        raise LookupError("This structural node is not in the selected definition.")
    tasks = {task["id"]: task for task in compiled["tasks"]}
    if section == "configuration":
        return _configuration(workflow, node, tasks, compiled)
    if section == "inputs":
        return [_row(binding["name"], binding) for binding in _inputs(node, tasks)]
    if section == "condition":
        return [_row({"condition": "Condition", "run_when": "Run when", "until": "Until (after body)"}[name], node[name])
                for name in ("condition", "run_when", "until") if name in node]
    if section == "outputs":
        return _outputs(node, tasks)
    if section == "state":
        return [_row(slot["name"], slot) for slot in node.get("state", [])]
    return _selection(workflow, node, tasks)


def _json_size(value):
    try:
        return len(json.dumps(value, ensure_ascii=True, allow_nan=False).encode("ascii"))
    except (ValueError, TypeError, RecursionError) as exc:
        raise WorkflowDefinitionError("Workflow inspection requires bounded finite JSON.") from exc


def workflow_flow_inspection(workflow, *, source_kind="saved", run_id=None, snapshot_sha256=None,
                             node_id=None, section=None, revision=None, cursor=None, limit=50):
    """Pure projection. Callers must first authorize this exact definition source."""
    if not isinstance(workflow, dict) or type(workflow.get("definition_version")) is not int or workflow["definition_version"] != 3:
        raise WorkflowFlowUnsupported()
    if source_kind not in {"saved", "draft", "run"} or (source_kind == "run") != (run_id is not None):
        raise ValueError("Invalid definition source.")
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Inspection pages require a limit between 1 and 100.")
    if (node_id is None) != (section is None) or section is not None and section not in FLOW_DETAIL_SECTIONS:
        raise ValueError("Select an exact structural node and supported detail section.")
    if cursor is not None and (node_id is None or not isinstance(cursor, str) or not cursor):
        raise ValueError("A detail cursor requires a structural node and section.")
    definition_revision = workflow_definition_revision(workflow)
    if source_kind == "draft":
        definition_revision = f"DRAFT:{definition_revision}"
    if (node_id is not None or revision is not None) and revision != definition_revision:
        raise WorkflowDefinitionConflict("This definition changed. Refresh Flow before inspecting its details.")
    group_id = workflow.get("group_id")
    source = {
        "kind": source_kind, "scope_type": "group" if group_id else "personal",
        "scope_id": _text(group_id or workflow.get("user_id")),
        "workflow_id": _text(workflow["id"]) if workflow.get("id") else None,
        "run_id": _text(run_id) if run_id is not None else None, "definition_revision": definition_revision,
    }
    if snapshot_sha256 is not None:
        if source_kind != "run" or not isinstance(snapshot_sha256, str) or not _DIGEST.fullmatch(snapshot_sha256):
            raise ValueError("Invalid frozen definition digest.")
        source["snapshot_sha256"] = snapshot_sha256
    compiled = compile_workflow_flow(workflow)
    if node_id is None:
        nodes, edges = _topology(compiled)
        return {
            "projection_version": FLOW_PROJECTION_VERSION, "definition_version": 3, "source": source,
            "name": _label(workflow.get("name"), "Workflow"), "root_region_id": compiled["flow"]["id"],
            "nodes": nodes, "edges": edges, "limits": compiled["limits"],
        }
    if not isinstance(node_id, str):
        raise ValueError("Select a canonical structural node id.")
    scope = {"projection_version": FLOW_PROJECTION_VERSION, "source": source, "node_id": node_id, "section": section}
    offset = _page_position(scope, cursor, limit)
    rows = _detail_rows(workflow, compiled, node_id, section)
    if offset > len(rows) or cursor and offset == len(rows):
        raise ValueError("The detail cursor exceeds this definition section.")
    result = {**scope, "items": [], "total_count": len(rows), "next_cursor": None}
    used = _json_size(result) + 1024
    for row in rows[offset:offset + limit]:
        size = _json_size(row) + 1
        if size + _json_size({**scope, "total_count": len(rows), "next_cursor": None, "items": []}) + 1024 > FLOW_DETAIL_MAX_BYTES:
            raise WorkflowFlowDetailTooLarge()
        if used + size > FLOW_DETAIL_MAX_BYTES:
            break
        result["items"].append(row)
        used += size
    result["next_cursor"] = _next_cursor(scope, offset + len(result["items"]), len(rows))
    return result


def preview_workflow_flow(definition, *, user_id, group_id=None, **selectors):
    """Normalize authored data only: no stored id, runner, source or admission lookup."""
    if not isinstance(definition, dict):
        raise WorkflowDefinitionError("A Flow preview requires an authored definition object.")
    if type(definition.get("definition_version")) is not int or definition["definition_version"] != 3:
        raise WorkflowFlowUnsupported()
    # List retains these legacy envelope fields verbatim when saving. They are
    # not v3 executable fields or revision inputs; leave the editor copy intact
    # while still rejecting unknown executable fields in the compiler input.
    authored = {key: value for key, value in definition.items() if key not in _PREVIEW_PRESERVED_FIELDS}
    normalized = normalize_workflow_definition(
        authored, {}, authored.get("tasks", []), user_id=user_id, group_id=group_id or "",
    )
    workflow = {**authored, **normalized, "user_id": user_id}
    if group_id:
        workflow["group_id"] = group_id
    else:
        workflow.pop("group_id", None)
    return workflow_flow_inspection(workflow, source_kind="draft", **selectors)


def authorize_workflow_flow_sources(workflow, *, reader_user_id):
    """Recheck declared source metadata, without expanding queries or reading results.

    Whole-run result authorization traverses all historical execution lineage.
    Definition-only inspection instead checks its authored source boundaries;
    execution overlays retain the existing exact payload/lineage authorization.
    """
    if not isinstance(workflow, dict) or type(workflow.get("definition_version")) is not int or workflow["definition_version"] != 3:
        raise WorkflowFlowUnsupported()
    compiled = compile_workflow_flow(workflow)
    try:
        for reference in _references(workflow):
            authorize_workflow_reference(workflow, reference, actor_user_id=reader_user_id)
        sources = {}
        scopes = {}
        for entry in compiled["nodes"].values():
            node = entry["node"]
            if node["kind"] != "for_each":
                continue
            iterable = node["iterable"]
            for value in iterable.get("documents", []):
                source = {
                    "document_id": value["document_id"], "scope": value["scope_type"],
                    "scope_id": value.get("scope_id") or workflow["user_id"],
                }
                sources[canonical_digest(source)] = source
            for value in iterable.get("scopes", []):
                scope = {"scope_type": value["scope_type"], "scope_id": value.get("scope_id") or workflow["user_id"]}
                scopes[canonical_digest(scope)] = scope
        for scope in scopes.values():
            if scope["scope_type"] == "personal" and scope["scope_id"] != reader_user_id:
                raise PermissionError
            if _default_authorize_scope(scope, actor_user_id=reader_user_id) is False:
                raise PermissionError
        if sources:
            authorize_analysis_sources(reader_user_id, list(sources.values()))
        for task in [workflow, *compiled["tasks"]]:
            action = task.get("document_action") or {}
            if not isinstance(action, dict):
                raise WorkflowDefinitionError("Document selection configuration must be an object.")
            if action.get("type", "none") == "none" or action.get("target_mode") == "current_item":
                continue
            for scope_type, field in (("group", "active_group_ids"), ("public", "active_public_workspace_id")):
                for scope_id in action.get(field, []):
                    if _default_authorize_scope(
                        {"scope_type": scope_type, "scope_id": scope_id}, actor_user_id=reader_user_id,
                    ) is False:
                        raise PermissionError
            identifiers = list(dict.fromkeys([
                *action.get("document_ids", []), *action.get("right_document_ids", []),
                *([action["left_document_id"]] if action.get("left_document_id") else []),
            ]))
            if identifiers:
                manifest = resolve_analysis_source_manifest(
                    identifiers, reader_user_id, doc_scope=action.get("doc_scope", "all"),
                    active_group_ids=action.get("active_group_ids", []),
                    active_public_workspace_ids=action.get("active_public_workspace_id", []),
                )
                if any(source.get("authorization_status") != "authorized" for source in manifest):
                    raise AnalysisResultUnavailable()
    except (WorkflowInputError, PermissionError, LookupError) as exc:
        raise AnalysisResultUnavailable() from exc


def workflow_run_flow_inspection(workflow, run_id, *, reader_user_id, **selectors):
    """Read only after the route has proved current workflow/run/scope access."""
    store = workflow_runtime_store(workflow, run_id)
    control = store.read()
    if control.get("schema_version") != 2:
        raise WorkflowFlowUnsupported()
    try:
        snapshot = store.run_definition()
    except (AttributeError, KeyError, TypeError) as exc:
        raise WorkflowFlowUnsupported() from exc
    if not isinstance(snapshot, dict):
        raise WorkflowFlowUnsupported()
    if workflow_definition_revision(snapshot) != control["definition_revision"]:
        raise WorkflowRuntimeConflict("workflow_definition_changed")
    if type(snapshot.get("definition_version")) is not int or snapshot["definition_version"] != 3:
        raise WorkflowFlowUnsupported()
    authorize_workflow_flow_sources(snapshot, reader_user_id=reader_user_id)
    return workflow_flow_inspection(
        snapshot, source_kind="run", run_id=run_id, snapshot_sha256=control["snapshot_ref"]["sha256"], **selectors,
    )
