# functions_workflow_flow.py
"""Bounded structured workflow compiler and deterministic, data-only predicates."""

import json
import math
import re
from copy import deepcopy

from functions_workflow_definitions import (
    WORKFLOW_BINDABLE_OUTPUTS, WORKFLOW_OUTPUT_KINDS, WorkflowDefinitionError,
    _boolean, _name, _object, normalize_workflow_input_processing, normalize_workflow_output_contract,
    workflow_output_kind_matches,
)
from functions_workflow_loop_schema import WORKFLOW_DOCUMENT_ITEM_SCHEMA, normalize_workflow_iterable


FLOW_LIMITS = {
    "max_nodes": 256, "max_depth": 4, "max_predicate_nodes": 100,
    "max_predicate_depth": 8, "max_executions": 5000, "deadline_seconds": 86400,
}
MISSING = object()
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_BAD_POINTER_ESCAPE = re.compile(r"~(?![01])")


def _id(value):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise WorkflowDefinitionError("Flow ids must be stable letters, numbers, dots, colons, underscores or hyphens.")
    return value


def normalize_flow_bindings(values):
    if not isinstance(values, list) or len(values) > 100:
        raise WorkflowDefinitionError("Flow inputs must be a list of at most 100 bindings; null is not supported.")
    result, names = [], set()
    for value in values:
        binding = _object(value, {"name", "source", "required", "expected_kind", "allow_partial"}, "Flow binding")
        name = _name(binding.get("name"), "Binding name")
        if name in names:
            raise WorkflowDefinitionError("Binding names must be unique.")
        names.add(name)
        source = binding.get("source")
        if not isinstance(source, dict) or source.get("scope", "current") != "current":
            raise WorkflowDefinitionError("Bindings require a node_output or enclosing loop_item in the current scope.")
        if source.get("kind") == "node_output":
            _object(source, {"kind", "node_id", "output", "scope"}, "Binding source")
            output = source.get("output", "authoritative")
            if not isinstance(output, str) or not output or len(output) > 64:
                raise WorkflowDefinitionError("A binding output selector is required.")
            normalized_source = {
                "kind": "node_output", "node_id": _id(source.get("node_id")), "output": output, "scope": "current",
            }
        elif source.get("kind") == "loop_item":
            _object(source, {"kind", "loop_id", "scope"}, "Loop item source")
            normalized_source = {"kind": "loop_item", "loop_id": _id(source.get("loop_id")), "scope": "current"}
        else:
            raise WorkflowDefinitionError("Bindings require a node_output or enclosing loop_item in the current scope.")
        kind = binding.get("expected_kind", "json" if source["kind"] == "loop_item" else "any")
        if not isinstance(kind, str) or kind not in WORKFLOW_OUTPUT_KINDS:
            raise WorkflowDefinitionError("Unsupported binding output kind.")
        result.append({
            "name": name,
            "source": normalized_source,
            "required": _boolean(binding.get("required", True), "Required input"),
            "expected_kind": kind,
            "allow_partial": _boolean(binding.get("allow_partial", False), "Partial input"),
        })
    return result


def normalize_predicate(value, bindings):
    try:
        encoded = json.dumps(value, allow_nan=False, ensure_ascii=True)
    except (ValueError, TypeError, RecursionError) as exc:
        raise WorkflowDefinitionError("A condition must be finite JSON.") from exc
    if len(encoded) > 16384:
        raise WorkflowDefinitionError("A condition must be at most 16 KiB.")
    names = {binding["name"] for binding in bindings}
    count = 0

    def operand(raw, *, reference_only=False):
        nonlocal count
        count += 1
        if count > 100:
            raise WorkflowDefinitionError("Conditions are limited to 100 AST nodes.")
        allowed = {"input", "path"} if reference_only else {"input", "path", "literal"}
        _object(raw, allowed, "Condition operand")
        if "literal" in raw:
            literal = raw["literal"]
            if len(raw) != 1 or not (
                literal is None or type(literal) in {str, bool, int}
                or type(literal) is float and math.isfinite(literal)
            ):
                raise WorkflowDefinitionError("Condition literals must be finite JSON scalars.")
            return {"literal": literal}
        path = raw.get("path", "")
        if not isinstance(raw.get("input"), str) or raw["input"] not in names:
            raise WorkflowDefinitionError("A condition must reference a declared input name.")
        if not isinstance(path, str) or (path and not path.startswith("/")) or _BAD_POINTER_ESCAPE.search(path):
            raise WorkflowDefinitionError("Condition paths must be RFC 6901 JSON pointers.")
        return {"input": raw["input"], "path": path}

    def visit(raw, depth=1):
        nonlocal count
        count += 1
        if count > 100 or depth > 8 or not isinstance(raw, dict):
            raise WorkflowDefinitionError("Conditions are limited to 100 AST nodes and depth 8.")
        op = raw.get("op")
        if not isinstance(op, str):
            raise WorkflowDefinitionError("A condition requires a supported operator.")
        if op in {"all", "any"}:
            _object(raw, {"op", "conditions"}, "Condition")
            children = raw.get("conditions")
            if not isinstance(children, list) or not children:
                raise WorkflowDefinitionError("All/any conditions require a nonempty conditions list.")
            return {"op": op, "conditions": [visit(child, depth + 1) for child in children]}
        if op == "not":
            _object(raw, {"op", "condition"}, "Condition")
            return {"op": op, "condition": visit(raw.get("condition"), depth + 1)}
        if op == "exists":
            _object(raw, {"op", "value"}, "Condition")
            return {"op": op, "value": operand(raw.get("value"), reference_only=True)}
        if op in {"eq", "ne", "lt", "lte", "gt", "gte"}:
            _object(raw, {"op", "left", "right"}, "Condition")
            return {"op": op, "left": operand(raw.get("left")), "right": operand(raw.get("right"))}
        raise WorkflowDefinitionError("Unsupported condition operator.")

    return visit(value)


def evaluate_predicate(predicate, values):
    """Values must already have passed authorization and structural validation."""
    def resolve(operand):
        if "literal" in operand:
            return operand["literal"]
        value = values.get(operand["input"], MISSING)
        pointer = operand["path"]
        for token in pointer.split("/")[1:] if pointer else []:
            token = token.replace("~1", "/").replace("~0", "~")
            if isinstance(value, dict):
                value = value.get(token, MISSING)
            elif isinstance(value, list) and re.fullmatch(r"0|[1-9][0-9]*", token):
                index = int(token)
                value = value[index] if index < len(value) else MISSING
            else:
                value = MISSING
        return value

    def json_type(value):
        if type(value) in {int, float}:
            return "number"
        return type(value)

    def equal(left, right):
        if json_type(left) != json_type(right):
            return False
        if isinstance(left, dict):
            return left.keys() == right.keys() and all(equal(left[key], right[key]) for key in left)
        if isinstance(left, list):
            return len(left) == len(right) and all(equal(a, b) for a, b in zip(left, right))
        return left == right

    def visit(node):
        op = node["op"]
        if op == "all":
            return all(visit(child) for child in node["conditions"])
        if op == "any":
            return any(visit(child) for child in node["conditions"])
        if op == "not":
            return not visit(node["condition"])
        if op == "exists":
            return resolve(node["value"]) is not MISSING
        left, right = resolve(node["left"]), resolve(node["right"])
        if left is MISSING or right is MISSING:
            raise WorkflowDefinitionError("A condition referenced missing data without an exists guard.")
        if op in {"eq", "ne"}:
            if any(isinstance(value, (dict, list)) for value in (left, right)):
                raise WorkflowDefinitionError("Condition comparisons require scalar fields.")
            return equal(left, right) if op == "eq" else not equal(left, right)
        if not all(type(value) is int or type(value) is float and math.isfinite(value) for value in (left, right)):
            raise WorkflowDefinitionError("Ordered condition comparisons require finite numbers.")
        return {"lt": lambda: left < right, "lte": lambda: left <= right,
                "gt": lambda: left > right, "gte": lambda: left >= right}[op]()

    return visit(predicate)


def compile_workflow_flow(workflow):
    """Normalize and prove lexical visibility and definite availability on every path."""
    if (
        not isinstance(workflow, dict) or type(workflow.get("definition_version")) is not int
        or workflow.get("definition_version") != 3 or workflow.get("durable_execution") is not True
    ):
        raise WorkflowDefinitionError("Structured workflows require definition version 3 and durable execution.")
    if isinstance(workflow.get("document_action"), dict) and workflow["document_action"].get("target_mode") == "current_item":
        raise WorkflowDefinitionError("Current-item Analyze must be declared on a task inside a document loop.")
    tasks = workflow.get("tasks")
    if not isinstance(tasks, list) or not tasks or len(tasks) > 100:
        raise WorkflowDefinitionError("A workflow catalogue requires 1 to 100 tasks.")
    catalogue = {}
    for task in tasks:
        if not isinstance(task, dict):
            raise WorkflowDefinitionError("A task catalogue entry must be an object.")
        if task.keys() - {
            "id", "type", "name", "instructions", "order", "runner", "document_action", "inputs",
            "reference_ids", "output_contract", "approval", "publication", "input_processing",
        }:
            raise WorkflowDefinitionError("A catalogue task contains unsupported executable fields.")
        if task.get("type", "instructions") != "instructions":
            raise WorkflowDefinitionError("The task catalogue supports only existing instruction tasks.")
        instructions = task.get("instructions")
        if not isinstance(instructions, str) or not instructions.strip() or len(instructions) > 12000:
            raise WorkflowDefinitionError("Task instructions must be nonempty text of at most 12000 characters.")
        runner = task.get("runner", {"type": "inherit"})
        if not isinstance(runner, dict) or runner.get("type", "inherit") not in ("inherit", "model", "agent"):
            raise WorkflowDefinitionError("A task requires an existing workflow runner.")
        _object(runner, {
            "type", "selected_agent", "model_endpoint_id", "model_id", "model_provider", "model_binding_summary",
        }, "Task runner")
        identifier = _id(task.get("id"))
        if identifier in catalogue:
            raise WorkflowDefinitionError("Task catalogue ids must be unique.")
        catalogue[identifier] = {**deepcopy(task), "inputs": normalize_flow_bindings(task.get("inputs", []))}
        if "input_processing" in task:
            catalogue[identifier]["input_processing"] = normalize_workflow_input_processing(task["input_processing"])
        if task.get("output_contract") is not None:
            catalogue[identifier]["output_contract"] = normalize_workflow_output_contract(task["output_contract"])
        if task.get("approval") is not None:
            approval = _object(task["approval"], {"required", "message"}, "Task approval")
            _boolean(approval.get("required", False), "Task approval requirement")
            if not isinstance(approval.get("message", ""), str) or len(approval.get("message", "")) > 1000:
                raise WorkflowDefinitionError("Task approval text must be at most 1000 characters.")
    error_handling = workflow.get("error_handling") or {}
    _object(error_handling, {"strategy", "retry_count"}, "Error handling")
    retries = error_handling.get("retry_count", 0)
    if type(retries) is not int or not 0 <= retries <= 5 or error_handling.get("strategy", "halt") not in ("halt", "continue"):
        raise WorkflowDefinitionError("Error handling supports halt/continue with zero to five retries.")
    if any(key in workflow for key in ("max_executions", "deadline_seconds")):
        raise WorkflowDefinitionError("Run budgets belong in the explicit limits object.")
    raw_limits = _object(workflow.get("limits", {}), {"max_executions", "deadline_seconds"}, "Run limits")
    limits = {}
    for key in ("max_executions", "deadline_seconds"):
        value = raw_limits.get(key, FLOW_LIMITS[key])
        if type(value) is not int or not 1 <= value <= FLOW_LIMITS[key]:
            raise WorkflowDefinitionError(f"{key} must be an integer between 1 and {FLOW_LIMITS[key]}.")
        limits[key] = value
    ids, nodes, regions, task_nodes, successor, dependencies = set(), {}, {}, {}, {}, {}
    node_loop_ids, loop_item_schemas = {}, {}

    def register(identifier):
        identifier = _id(identifier)
        if identifier in ids or len(ids) >= FLOW_LIMITS["max_nodes"]:
            raise WorkflowDefinitionError("All flow region, node and join ids must be unique; at most 256 are supported.")
        ids.add(identifier)
        return identifier

    def region(raw, depth, *, root=False, body=False, parent=None, loop_ids=()):
        if depth > FLOW_LIMITS["max_depth"]:
            raise WorkflowDefinitionError("Flow regions are limited to depth 4.")
        _object(raw, {"id", "nodes", "outputs"} if root or body else {"id", "nodes"}, "Flow region")
        result = {"id": register(raw.get("id")), "nodes": []}
        node_loop_ids[result["id"]] = list(loop_ids)
        children = raw.get("nodes")
        if not isinstance(children, list) or len(children) > 256:
            raise WorkflowDefinitionError("A flow region requires a bounded nodes list.")
        regions[result["id"]] = {"region": result, "parent": parent}
        for child in children:
            if not isinstance(child, dict):
                raise WorkflowDefinitionError("A flow node must be an object.")
            kind = child.get("kind")
            allowed = {
                "task": {"id", "kind", "task_id", "run_when"},
                "if": {"id", "kind", "inputs", "condition", "then", "else", "join"},
                "route": {"id", "kind", "inputs", "condition", "target"},
                "for_each": {"id", "kind", "inputs", "iterable", "item_key", "max_items", "body"},
                "collect": {"id", "kind", "source", "output_contract"},
            }
            if not isinstance(kind, str) or kind not in allowed:
                raise WorkflowDefinitionError("Only task, if, route, for_each and collect nodes are executable.")
            _object(child, allowed[kind], "Flow node")
            node = {"id": register(child.get("id")), "kind": kind}
            nodes[node["id"]] = {"node": node, "region_id": result["id"]}
            node_loop_ids[node["id"]] = list(loop_ids)
            if kind == "task":
                task_id = _id(child.get("task_id"))
                if task_id not in catalogue or task_id in task_nodes:
                    raise WorkflowDefinitionError("Each catalogue task must occur exactly once in the flow.")
                task_nodes[task_id] = node["id"]
                node["task_id"] = task_id
                if "run_when" in child:
                    node["run_when"] = normalize_predicate(child["run_when"], catalogue[task_id]["inputs"])
            elif kind == "for_each":
                node["inputs"] = normalize_flow_bindings(child.get("inputs"))
                node["iterable"] = normalize_workflow_iterable(child.get("iterable"), max_items=child.get("max_items"))
                if child.get("item_key") != "source_identity":
                    raise WorkflowDefinitionError("For each supports only the source_identity item-key policy.")
                node["item_key"] = "source_identity"
                node["max_items"] = child["max_items"]
                sources = node["iterable"].get("documents", node["iterable"].get("scopes", []))
                if workflow.get("group_id") and any(
                    source["scope_type"] != "group" or source.get("scope_id") != str(workflow["group_id"])
                    for source in sources
                ):
                    raise WorkflowDefinitionError("Group workflow iterables must belong to the workflow's group.")
                node["body"] = region(
                    child.get("body"), depth + 1, body=True, parent=node["id"], loop_ids=(*loop_ids, node["id"]),
                )
            elif kind == "collect":
                source = _object(child.get("source"), {"loop_id", "output"}, "Collect source")
                node["source"] = {
                    "loop_id": _id(source.get("loop_id")), "output": _name(source.get("output"), "Collect output"),
                }
                node["output_contract"] = normalize_workflow_output_contract(child.get("output_contract"))
                if node["output_contract"]["kind"] not in {"records", "document_results"}:
                    raise WorkflowDefinitionError("Collect requires a records or document_results output contract.")
            else:
                node["inputs"] = normalize_flow_bindings(child.get("inputs"))
                node["condition"] = normalize_predicate(child.get("condition"), node["inputs"])
                if kind == "route":
                    target = _object(child.get("target"), {"node_id", "exit_region_id"}, "Route target")
                    if len(target) != 1:
                        raise WorkflowDefinitionError("A route needs one explicit forward or region-exit target.")
                    node["target"] = {key: _id(value) for key, value in target.items()}
                else:
                    node["then"] = region(child.get("then"), depth + 1, parent=node["id"], loop_ids=loop_ids)
                    node["else"] = region(child.get("else"), depth + 1, parent=node["id"], loop_ids=loop_ids)
                    join = _object(child.get("join"), {"id", "exports"}, "If join")
                    join_id = register(join.get("id"))
                    exports = join.get("exports")
                    if not isinstance(exports, list) or len(exports) > 100:
                        raise WorkflowDefinitionError("A join requires an exports list of at most 100 entries.")
                    normalized, names = [], set()
                    for export in exports:
                        _object(export, {"name", "expected_kind", "required", "then", "else"}, "Join export")
                        name = _name(export.get("name"), "Join export name")
                        expected = export.get("expected_kind", "any")
                        if name in names or not isinstance(expected, str) or expected not in WORKFLOW_OUTPUT_KINDS:
                            raise WorkflowDefinitionError("Join exports require unique names and a supported kind.")
                        names.add(name)
                        entry = {"name": name, "expected_kind": expected,
                                 "required": _boolean(export.get("required", True), "Required join export")}
                        for branch in ("then", "else"):
                            source = _object(export.get(branch), {"node_id", "output"}, "Join producer")
                            output = source.get("output", "authoritative")
                            if not isinstance(output, str) or not output or len(output) > 64:
                                raise WorkflowDefinitionError("A join needs an exact output selector.")
                            entry[branch] = {"node_id": _id(source.get("node_id")), "output": output}
                        normalized.append(entry)
                    node["join"] = {"id": join_id, "exports": normalized}
                    nodes[join_id] = {"node": {"id": join_id, "kind": "join", "exports": normalized},
                                      "region_id": result["id"], "if_id": node["id"]}
                    node_loop_ids[join_id] = list(loop_ids)
            result["nodes"].append(node)
        if root or body:
            if "outputs" not in raw:
                raise WorkflowDefinitionError("Root and loop body regions must declare outputs, including an explicit empty list.")
            result["outputs"] = normalize_flow_bindings(raw["outputs"])
        return result

    flow = region(workflow.get("flow"), 1, root=True)
    if set(catalogue) != set(task_nodes):
        raise WorkflowDefinitionError("Every catalogue task must occur exactly once in the executable flow.")

    def output_contract(node):
        if node["kind"] == "collect":
            return node["output_contract"]
        return catalogue[node["task_id"]].get("output_contract") or {}

    def collection_keys(node):
        kind = node["output_contract"]["kind"]
        return {(node["id"], "authoritative"), (node["id"], "records" if kind == "records" else "documents")}

    def descriptor(node_id, output):
        entry = nodes.get(node_id)
        if not entry:
            raise WorkflowDefinitionError("A binding references a missing producer node.")
        node = entry["node"]
        if node["kind"] == "join":
            export = next((item for item in node["exports"] if item["name"] == output), None)
            if export is None:
                raise WorkflowDefinitionError("The selected join output is not declared.")
            return export["expected_kind"]
        if node["kind"] == "collect":
            if (node_id, output) not in collection_keys(node):
                raise WorkflowDefinitionError("Collect exposes only its exact collection kind and authoritative output.")
            return node["output_contract"]["kind"]
        if node["kind"] != "task" or output not in WORKFLOW_BINDABLE_OUTPUTS:
            raise WorkflowDefinitionError("Only task final representations, Collect outputs and declared join exports can supply inputs.")
        contract = catalogue[node["task_id"]].get("output_contract") or {}
        declared = contract.get("kind", "any")
        if output not in {"authoritative", "text"} and declared not in {
            "any", {"records": "records", "json": "json", "documents": "document_results"}[output],
        }:
            raise WorkflowDefinitionError("The selected representation does not match its producer's output contract.")
        kind = {"text": "text", "records": "records", "json": "json", "documents": "document_results"}.get(
            output, contract.get("kind", "any"),
        )
        return kind

    def check_bindings(bindings, definite, possible, consumer):
        dependencies.setdefault(consumer, [])
        for binding in bindings:
            source = binding["source"]
            if source.get("kind") == "loop_item":
                loop_id = source["loop_id"]
                if loop_id not in node_loop_ids[consumer]:
                    raise WorkflowDefinitionError("A loop_item binding must select an enclosing For each loop.")
                if not workflow_output_kind_matches("json", binding["expected_kind"]):
                    raise WorkflowDefinitionError("A loop_item binding supplies a JSON object with value, key and index.")
                dependencies[consumer].append((loop_id, "loop_item"))
                continue
            key = (source["node_id"], source["output"])
            kind = descriptor(*key)
            if key not in possible:
                raise WorkflowDefinitionError("An input references a future, unreachable or out-of-region producer.")
            if binding["required"] and key not in definite:
                raise WorkflowDefinitionError("A required producer is unavailable on a reachable path; use an optional input or join export.")
            if kind != "any" and not workflow_output_kind_matches(kind, binding["expected_kind"]):
                raise WorkflowDefinitionError("A binding's expected kind does not match its producer.")
            dependencies[consumer].append(key)

    def task_keys(node):
        declared = (catalogue[node["task_id"]].get("output_contract") or {}).get("kind", "any")
        selectors = {"authoritative", "text"}
        selectors.update({"json": {"json"}, "records": {"records"}, "document_results": {"documents"}}.get(declared, set()))
        return {(node["id"], output) for output in selectors}

    leaf_cache = {}

    def output_leaves(node_id, output, active=()):
        key = (node_id, output)
        if key in leaf_cache:
            return leaf_cache[key]
        if key in active:
            raise WorkflowDefinitionError("Producer exports must not contain cycles.")
        node = nodes[node_id]["node"]
        if node["kind"] == "join":
            export = next(item for item in node["exports"] if item["name"] == output)
            leaves = tuple(dict.fromkeys(
                leaf for branch in ("then", "else")
                for leaf in output_leaves(export[branch]["node_id"], export[branch]["output"], (*active, key))
            ))
        else:
            leaves = (key,)
        leaf_cache[key] = leaves
        return leaves

    def structured_output(node_id, output):
        for producer_id, selector in output_leaves(node_id, output):
            node = nodes[producer_id]["node"]
            if node["kind"] not in {"task", "collect"}:
                return False
            contract = output_contract(node)
            schema = contract.get("schema") or {}
            root_types = schema.get("type")
            root_types = {root_types} if isinstance(root_types, str) else set(root_types or [])
            if not (
                root_types and root_types <= {"object", "array"}
                and contract.get("kind", "any") in {"any", "json", "records", "document_results"}
                and selector in {"authoritative", "json", "records", "documents"}
            ):
                return False
        return True

    def output_schemas(node_id, output):
        return [output_contract(nodes[producer_id]["node"]).get("schema") or {}
                for producer_id, _ in output_leaves(node_id, output)]

    def collection_kind(source):
        selected = {descriptor(node_id, output) for node_id, output in output_leaves(
            source["node_id"], source["output"],
        )}
        if len(selected) != 1 or not selected <= {"records", "document_results"}:
            raise WorkflowDefinitionError("Loop collections require one exact records or document_results kind on every producer.")
        return next(iter(selected))

    def collection_item_schema(schema):
        if not schema:
            return {}
        root_types = schema.get("type")
        root_types = {root_types} if isinstance(root_types, str) else set(root_types or [])
        if root_types != {"array"}:
            raise WorkflowDefinitionError("A collection output schema must declare an array.")
        items = schema.get("items")
        return items if isinstance(items, dict) else {}

    def prepare_loop(node):
        iterable = node["iterable"]
        if iterable["kind"] == "input":
            binding = next((item for item in node["inputs"] if item["name"] == iterable["name"]), None)
            if binding is None or binding["source"]["kind"] != "node_output" or not binding["required"] or binding["allow_partial"]:
                raise WorkflowDefinitionError("A saved iterable must select a required, nonpartial node-output input.")
            collection_kind(binding["source"])
            values = [collection_item_schema(schema) for schema in output_schemas(
                binding["source"]["node_id"], binding["source"]["output"],
            )]
        else:
            values = [WORKFLOW_DOCUMENT_ITEM_SCHEMA]
        loop_item_schemas[node["id"]] = [{
            "type": "object", "required": ["value", "key", "index"],
            "properties": {
                "value": deepcopy(value), "key": {"type": "string"},
                "index": {"type": "integer", "minimum": 0},
            },
            "additionalProperties": False,
        } for value in values]

    def check_collect(node, definite, possible):
        loop_id = node["source"]["loop_id"]
        loop = nodes.get(loop_id, {}).get("node", {})
        if loop.get("kind") != "for_each":
            raise WorkflowDefinitionError("Collect must select an existing For each loop.")
        if node_loop_ids[loop_id] != node_loop_ids[node["id"]]:
            raise WorkflowDefinitionError("Collect must run in its source loop's enclosing scope.")
        key = (loop_id, "loop_complete")
        if key not in possible:
            raise WorkflowDefinitionError("Collect references a future, unreachable or out-of-region loop.")
        if key not in definite:
            raise WorkflowDefinitionError("A required producer loop is unavailable on a reachable path.")
        export = next((item for item in loop["body"]["outputs"] if item["name"] == node["source"]["output"]), None)
        if export is None:
            raise WorkflowDefinitionError("Collect must select an explicitly declared loop body output.")
        if collection_kind(export["source"]) != node["output_contract"]["kind"]:
            raise WorkflowDefinitionError("Collect must preserve its body export's exact collection kind.")
        for schema in output_schemas(export["source"]["node_id"], export["source"]["output"]):
            collection_item_schema(schema)
        collection_item_schema(node["output_contract"].get("schema") or {})
        if (not export["required"] or export["allow_partial"]) and (
            not node["output_contract"]["allow_partial"] or node["output_contract"]["require_complete_coverage"]
        ):
            raise WorkflowDefinitionError("Optional or partial body exports require an explicit partial Collect policy.")
        dependencies[node["id"]].append((loop_id, export["name"]))

    def check_current_document(node):
        action = catalogue[node["task_id"]].get("document_action")
        if not isinstance(action, dict) or (action.get("target_mode") != "current_item" and "loop_id" not in action):
            return
        _object(action, {"type", "target_mode", "loop_id", "analysis_mode"}, "Current-item Analyze")
        if action.get("type") != "analyze" or action.get("target_mode") != "current_item" or action.get("analysis_mode") != "combined":
            raise WorkflowDefinitionError("Current-item Analyze requires combined analysis of one enclosing document item.")
        loop_id = _id(action.get("loop_id"))
        if loop_id not in node_loop_ids[node["id"]]:
            raise WorkflowDefinitionError("Current-item Analyze must select an enclosing document loop.")
        if nodes[loop_id]["node"]["iterable"]["kind"] not in {"documents", "workspace_query"}:
            raise WorkflowDefinitionError("Current-item Analyze requires a document iterable, not saved records or document results.")

    def check_input_processing(node):
        task = catalogue[node["task_id"]]
        if task.get("input_processing", "full") != "saved_record_report":
            return
        action = task.get("document_action")
        if (
            task.get("publication") is not None or not isinstance(action, dict) or action.get("type") != "none"
            or (task.get("output_contract") or {}).get("kind") != "text"
        ):
            raise WorkflowDefinitionError(
                "saved_record_report requires a non-publication task with document_action none and a text output contract."
            )
        for binding in task["inputs"]:
            source = binding["source"]
            if source["kind"] == "node_output" and all(
                descriptor(producer_id, output) in {"records", "document_results"}
                for producer_id, output in output_leaves(source["node_id"], source["output"])
            ):
                return
        raise WorkflowDefinitionError("saved_record_report requires at least one node-output records or document_results input.")

    def check_predicate(predicate, bindings):
        used = {binding["name"]: binding for binding in bindings}

        def operand_types(operand, *, scalar=True):
            if "literal" in operand:
                value = operand["literal"]
                return [{"null" if value is None else "boolean" if type(value) is bool
                         else "number" if type(value) in {int, float} else "string"}]
            source = used[operand["input"]]["source"]
            if source["kind"] == "loop_item":
                schemas = loop_item_schemas[source["loop_id"]]
            else:
                if not structured_output(source["node_id"], source["output"]):
                    raise WorkflowDefinitionError("Conditions require JSON or record fields with an explicit schema on every possible producer.")
                schemas = output_schemas(source["node_id"], source["output"])
            types = []
            for schema in schemas:
                field = schema
                for token in operand["path"].split("/")[1:] if operand["path"] else []:
                    token = token.replace("~1", "/").replace("~0", "~")
                    if field.get("type") == "array" and re.fullmatch(r"0|[1-9][0-9]*", token):
                        field = field.get("items")
                    else:
                        field = field.get("properties", {}).get(token)
                    if not isinstance(field, dict):
                        raise WorkflowDefinitionError("A condition field must be declared in every possible producer schema.")
                field_type = field.get("type")
                selected = {field_type} if isinstance(field_type, str) else set(field_type or [])
                if not selected or scalar and not selected <= {"string", "boolean", "number", "integer", "null"}:
                    raise WorkflowDefinitionError("Condition comparisons require explicitly typed scalar fields.")
                types.append(selected)
            return types

        def visit(node):
            if node["op"] in {"all", "any"}:
                for child in node["conditions"]:
                    visit(child)
            elif node["op"] == "not":
                visit(node["condition"])
            elif node["op"] == "exists":
                operand_types(node["value"], scalar=False)
            else:
                types = operand_types(node["left"]) + operand_types(node["right"])
                if node["op"] in {"lt", "lte", "gt", "gte"} and any(
                    not values.intersection({"number", "integer"}) for values in types
                ):
                    raise WorkflowDefinitionError("Ordered conditions require numeric fields and literal values.")

        visit(predicate)

    def intersect(states):
        return set.intersection(*(state[0] for state in states)), set.union(*(state[1] for state in states))

    def analyze(current, initial, *, branch=False):
        children = current["nodes"]
        positions = {node["id"]: index for index, node in enumerate(children)}
        incoming = {0: [initial]}
        exits = []
        for index, node in enumerate(children):
            if index not in incoming:
                raise WorkflowDefinitionError("The flow contains an unreachable node.")
            definite, possible = intersect(incoming[index])
            after_definite, after_possible = set(definite), set(possible)
            kind = node["kind"]
            bindings = catalogue[node["task_id"]]["inputs"] if kind == "task" else node.get("inputs", [])
            check_bindings(bindings, definite, possible, node["id"])
            if kind in {"if", "route"} or "run_when" in node:
                check_predicate(node["run_when"] if kind == "task" else node["condition"], bindings)
            if kind == "task":
                check_current_document(node)
                check_input_processing(node)
                keys = task_keys(node)
                after_possible.update({(node["id"], output) for output in WORKFLOW_BINDABLE_OUTPUTS})
                if "run_when" not in node:
                    after_definite.update(keys)
                if catalogue[node["task_id"]].get("publication") is not None and len(bindings) != 1:
                    raise WorkflowDefinitionError("A v3 publication task requires exactly one explicit upstream input.")
            elif kind == "if":
                ends = {name: analyze(node[name], (set(definite), set(possible)), branch=True)
                        for name in ("then", "else")}
                for export in node["join"]["exports"]:
                    for name in ("then", "else"):
                        producer = export[name]
                        binding = {"name": export["name"], "source": producer, "required": export["required"],
                                   "expected_kind": export["expected_kind"]}
                        check_bindings([binding], *ends[name], node["join"]["id"])
                    key = (node["join"]["id"], export["name"])
                    after_possible.add(key)
                    if export["required"]:
                        after_definite.add(key)
            elif kind == "for_each":
                prepare_loop(node)
                ends = analyze(node["body"], (set(definite), set(possible)))
                for export in node["body"]["outputs"]:
                    source = export["source"]
                    if source["kind"] != "node_output" or node_loop_ids.get(source.get("node_id")) != [*node_loop_ids[node["id"]], node["id"]]:
                        raise WorkflowDefinitionError("A loop body export must select a producer in its own body scope.")
                check_bindings(node["body"]["outputs"], *ends, node["body"]["id"])
                after_possible.add((node["id"], "loop_complete"))
                after_definite.add((node["id"], "loop_complete"))
            elif kind == "collect":
                check_collect(node, definite, possible)
                keys = collection_keys(node)
                after_possible.update(keys)
                after_definite.update(keys)
            elif kind == "route":
                target = node["target"]
                if "exit_region_id" in target:
                    if not branch or target["exit_region_id"] != current["id"]:
                        raise WorkflowDefinitionError("A region exit may target only its current structured branch join.")
                    exits.append((set(definite), set(possible)))
                else:
                    destination = positions.get(target["node_id"])
                    if destination is None or destination <= index:
                        raise WorkflowDefinitionError("Routes may target only a later sibling node.")
                    incoming.setdefault(destination, []).append((set(definite), set(possible)))
            successor[node["id"]] = children[index + 1]["id"] if index + 1 < len(children) else None
            incoming.setdefault(index + 1, []).append((after_definite, after_possible))
        exits.extend(incoming.get(len(children), []))
        return intersect(exits or [initial])

    definite, possible = analyze(flow, (set(), set()))
    check_bindings(flow["outputs"], definite, possible, flow["id"])
    return {
        "flow": flow, "tasks": list(catalogue.values()), "limits": limits,
        "nodes": nodes, "regions": regions, "task_nodes": task_nodes,
        "successor": successor, "dependencies": dependencies,
        "definite_outputs": definite, "possible_outputs": possible,
        "node_loop_ids": node_loop_ids, "loop_item_schemas": loop_item_schemas,
    }
