# functions_workflow_flow.py
"""Bounded structured workflow compiler and deterministic, data-only predicates."""

import json
import math
import re
from copy import deepcopy

from functions_workflow_definitions import (
    WORKFLOW_BINDABLE_OUTPUTS, WORKFLOW_OUTPUT_KINDS, WorkflowDefinitionError,
    _boolean, _name, _object, normalize_workflow_output_contract, workflow_output_kind_matches,
)


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
        source = _object(binding.get("source"), {"kind", "node_id", "output", "scope"}, "Binding source")
        if source.get("kind") != "node_output" or source.get("scope", "current") != "current":
            raise WorkflowDefinitionError("M4A bindings support only node_output in the current scope.")
        output = source.get("output", "authoritative")
        if not isinstance(output, str) or not output or len(output) > 64:
            raise WorkflowDefinitionError("A binding output selector is required.")
        kind = binding.get("expected_kind", "any")
        if not isinstance(kind, str) or kind not in WORKFLOW_OUTPUT_KINDS:
            raise WorkflowDefinitionError("Unsupported binding output kind.")
        result.append({
            "name": name,
            "source": {"kind": "node_output", "node_id": _id(source.get("node_id")),
                       "output": output, "scope": "current"},
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
    if workflow.get("definition_version") != 3 or workflow.get("durable_execution") is not True:
        raise WorkflowDefinitionError("Structured workflows require definition version 3 and durable execution.")
    tasks = workflow.get("tasks")
    if not isinstance(tasks, list) or not tasks or len(tasks) > 100:
        raise WorkflowDefinitionError("A workflow catalogue requires 1 to 100 tasks.")
    catalogue = {}
    for task in tasks:
        if not isinstance(task, dict):
            raise WorkflowDefinitionError("A task catalogue entry must be an object.")
        if task.keys() - {
            "id", "type", "name", "instructions", "order", "runner", "document_action", "inputs",
            "reference_ids", "output_contract", "approval", "publication",
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

    def register(identifier):
        identifier = _id(identifier)
        if identifier in ids or len(ids) >= FLOW_LIMITS["max_nodes"]:
            raise WorkflowDefinitionError("All flow region, node and join ids must be unique; at most 256 are supported.")
        ids.add(identifier)
        return identifier

    def region(raw, depth, *, root=False, parent=None):
        if depth > 4:
            raise WorkflowDefinitionError("Flow regions are limited to depth 4.")
        _object(raw, {"id", "nodes", "outputs"} if root else {"id", "nodes"}, "Flow region")
        result = {"id": register(raw.get("id")), "nodes": []}
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
            }
            if not isinstance(kind, str) or kind not in allowed:
                raise WorkflowDefinitionError("Only task, if and route nodes are executable in M4A.")
            _object(child, allowed[kind], "Flow node")
            node = {"id": register(child.get("id")), "kind": kind}
            nodes[node["id"]] = {"node": node, "region_id": result["id"]}
            if kind == "task":
                task_id = _id(child.get("task_id"))
                if task_id not in catalogue or task_id in task_nodes:
                    raise WorkflowDefinitionError("Each catalogue task must occur exactly once in the flow.")
                task_nodes[task_id] = node["id"]
                node["task_id"] = task_id
                if "run_when" in child:
                    node["run_when"] = normalize_predicate(child["run_when"], catalogue[task_id]["inputs"])
            else:
                node["inputs"] = normalize_flow_bindings(child.get("inputs"))
                node["condition"] = normalize_predicate(child.get("condition"), node["inputs"])
                if kind == "route":
                    target = _object(child.get("target"), {"node_id", "exit_region_id"}, "Route target")
                    if len(target) != 1:
                        raise WorkflowDefinitionError("A route needs one explicit forward or region-exit target.")
                    node["target"] = {key: _id(value) for key, value in target.items()}
                else:
                    node["then"] = region(child.get("then"), depth + 1, parent=node["id"])
                    node["else"] = region(child.get("else"), depth + 1, parent=node["id"])
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
            result["nodes"].append(node)
        if root:
            if "outputs" not in raw:
                raise WorkflowDefinitionError("The root flow must declare outputs, including an explicit empty list.")
            result["outputs"] = normalize_flow_bindings(raw["outputs"])
        return result

    flow = region(workflow.get("flow"), 1, root=True)
    if set(catalogue) != set(task_nodes):
        raise WorkflowDefinitionError("Every catalogue task must occur exactly once in the executable flow.")

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
        if node["kind"] != "task" or output not in WORKFLOW_BINDABLE_OUTPUTS:
            raise WorkflowDefinitionError("Only task final representations and declared join exports can supply inputs.")
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

    def structured_output(node_id, output, active=None):
        active = set() if active is None else set(active)
        key = (node_id, output)
        if key in active:
            return False
        active.add(key)
        node = nodes[node_id]["node"]
        if node["kind"] == "join":
            export = next(item for item in node["exports"] if item["name"] == output)
            return all(structured_output(export[branch]["node_id"], export[branch]["output"], active)
                       for branch in ("then", "else"))
        contract = catalogue[node["task_id"]].get("output_contract") or {}
        schema = contract.get("schema") or {}
        root_types = schema.get("type")
        root_types = {root_types} if isinstance(root_types, str) else set(root_types or [])
        return (
            bool(root_types) and root_types <= {"object", "array"}
            and contract.get("kind", "any") in {"any", "json", "records", "document_results"}
            and output in {"authoritative", "json", "records", "documents"}
        )

    def check_predicate(predicate, bindings):
        used = {binding["name"]: binding for binding in bindings}

        def schemas(node_id, output):
            node = nodes[node_id]["node"]
            if node["kind"] == "join":
                export = next(item for item in node["exports"] if item["name"] == output)
                return [schema for branch in ("then", "else")
                        for schema in schemas(export[branch]["node_id"], export[branch]["output"])]
            return [catalogue[node["task_id"]]["output_contract"]["schema"]]

        def operand_types(operand, *, scalar=True):
            if "literal" in operand:
                value = operand["literal"]
                return [{"null" if value is None else "boolean" if type(value) is bool
                         else "number" if type(value) in {int, float} else "string"}]
            source = used[operand["input"]]["source"]
            if not structured_output(source["node_id"], source["output"]):
                raise WorkflowDefinitionError("Conditions require JSON or record fields with an explicit schema on every possible producer.")
            types = []
            for schema in schemas(source["node_id"], source["output"]):
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
            bindings = catalogue[node["task_id"]]["inputs"] if kind == "task" else node["inputs"]
            check_bindings(bindings, definite, possible, node["id"])
            if kind != "task" or "run_when" in node:
                check_predicate(node["run_when"] if kind == "task" else node["condition"], bindings)
            if kind == "task":
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
    }
