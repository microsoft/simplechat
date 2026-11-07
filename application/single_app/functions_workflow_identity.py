# functions_workflow_identity.py
"""Stable authorized node/execution identity, independent of a mutable attempt."""

import hashlib
import json
import re

from functions_workflow_definitions import workflow_definition_revision
from functions_workflow_limits import WORKFLOW_MAX_EXECUTION_ADMISSIONS, WORKFLOW_REPEAT_ITERATIONS_MAX
from functions_workflow_loop_schema import WORKFLOW_LOOP_MAX_ITEMS


_NODE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_ITEM_ID = re.compile(r"[a-f0-9]{64}\Z")


def canonical_digest(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def normalize_workflow_iteration_path(path):
    """Validate shape only; readers must additionally prove sealed iteration admission."""
    if path is None:
        return []
    if not isinstance(path, list) or len(path) > 3:
        raise ValueError("An iteration path requires at most three enclosing loop frames.")
    normalized, loops = [], set()
    for frame in path:
        if not isinstance(frame, dict) or frame.keys() not in (
            {"loop_id", "item_id", "index"}, {"loop_id", "iteration"},
        ):
            raise ValueError("An iteration frame requires an exact For-each item or Repeat round.")
        loop_id = frame["loop_id"]
        if not isinstance(loop_id, str) or not _NODE_ID.fullmatch(loop_id) or loop_id in loops:
            raise ValueError("Iteration loop ids must be stable and unique within a path.")
        loops.add(loop_id)
        if "iteration" in frame:
            iteration = frame["iteration"]
            if type(iteration) is not int or not 0 <= iteration < WORKFLOW_MAX_EXECUTION_ADMISSIONS:
                raise ValueError("A Repeat iteration must be a zero-based lifetime index within the execution limit.")
            normalized.append({"loop_id": loop_id, "iteration": iteration})
        else:
            item_id, index = frame["item_id"], frame["index"]
            if not isinstance(item_id, str) or not _ITEM_ID.fullmatch(item_id):
                raise ValueError("Iteration item ids must be lowercase SHA256 digests.")
            if type(index) is not int or not 0 <= index < WORKFLOW_LOOP_MAX_ITEMS:
                raise ValueError("An iteration index must be a zero-based integer within the technical item limit.")
            normalized.append({"loop_id": loop_id, "item_id": item_id, "index": index})
    return normalized


def _flow_node(workflow, node_id):
    seen, matched = set(), None

    def register(identifier):
        if not isinstance(identifier, str) or not _NODE_ID.fullmatch(identifier) or identifier in seen or len(seen) >= 256:
            raise ValueError("The saved flow identity requires at most 256 unique structural ids.")
        seen.add(identifier)

    def visit(region, ancestors, depth):
        nonlocal matched
        if not isinstance(region, dict) or depth > 4 or not isinstance(region.get("nodes"), list):
            raise ValueError("The saved flow identity is not a bounded region tree.")
        register(region.get("id"))
        if depth == 1 and region["id"] == node_id:
            matched = ({"id": node_id, "kind": "root"}, ancestors)
        if len(region["nodes"]) > 256:
            raise ValueError("The saved flow identity is not bounded.")
        for node in region["nodes"]:
            if not isinstance(node, dict):
                raise ValueError("A saved flow node must be an object.")
            register(node.get("id"))
            kind = node.get("kind")
            if not isinstance(kind, str) or kind not in {"task", "if", "route", "for_each", "collect", "repeat_until"}:
                raise ValueError("The saved flow node kind is unsupported.")
            if kind == "task":
                task_id = node.get("task_id")
                if not isinstance(task_id, str) or not _NODE_ID.fullmatch(task_id):
                    raise ValueError("A task node requires a real catalogue task id.")
            elif "task_id" in node:
                raise ValueError("Engine nodes cannot have task ids.")
            if node["id"] == node_id:
                matched = (node, ancestors)
            if kind == "if":
                join = node.get("join")
                if not isinstance(join, dict) or "task_id" in join:
                    raise ValueError("A branch join requires an engine identity.")
                register(join.get("id"))
                if join["id"] == node_id:
                    matched = ({"id": node_id, "kind": "join"}, ancestors)
                visit(node.get("then"), ancestors, depth + 1)
                visit(node.get("else"), ancestors, depth + 1)
            elif kind in {"for_each", "repeat_until"}:
                limit = node.get("max_items" if kind == "for_each" else "max_iterations")
                maximum = WORKFLOW_LOOP_MAX_ITEMS if kind == "for_each" else WORKFLOW_REPEAT_ITERATIONS_MAX
                if type(limit) is not int or not 1 <= limit <= maximum:
                    raise ValueError("A saved loop requires an explicit bounded iteration limit.")
                visit(node.get("body"), (*ancestors, (node["id"], kind, limit)), depth + 1)

    visit(workflow.get("flow"), (), 1)
    if matched is None:
        raise ValueError("The node identity does not match the saved flow.")
    return matched


def _execution_parts(workflow, run_id, node_id, iteration_path):
    if not isinstance(workflow, dict):
        raise ValueError("An execution requires its authorized workflow.")
    if not all(isinstance(value, str) and value for value in (workflow.get("id"), workflow.get("user_id"), run_id, node_id)):
        raise ValueError("An execution requires its authorized workflow, run and node.")
    path = normalize_workflow_iteration_path(iteration_path)
    version = workflow.get("definition_version", 1)
    if type(version) is not int or version not in {1, 2, 3}:
        raise ValueError("The execution's workflow definition version is unsupported.")
    if version != 3:
        if path:
            raise ValueError("Iteration paths require a structured workflow.")
        return path, None
    node, ancestors = _flow_node(workflow, node_id)
    if [frame["loop_id"] for frame in path] != [loop_id for loop_id, _, _ in ancestors]:
        raise ValueError("The iteration path does not match the node's enclosing loop ancestors.")
    for frame, (_, kind, limit) in zip(path, ancestors):
        if kind == "for_each":
            if "index" not in frame or frame["index"] >= limit:
                raise ValueError("An iteration index exceeds its enclosing For-each loop's authored item limit.")
        else:
            run_limit = (workflow.get("limits") or {}).get("max_executions", WORKFLOW_MAX_EXECUTION_ADMISSIONS)
            if (
                "iteration" not in frame or type(run_limit) is not int
                or not 1 <= run_limit <= WORKFLOW_MAX_EXECUTION_ADMISSIONS
                or frame["iteration"] >= run_limit
            ):
                raise ValueError("A Repeat lifetime iteration exceeds its enclosing run's execution limit.")
    return path, node


def _execution_digest(workflow, run_id, node_id, path):
    return canonical_digest({
        "scope_type": "group" if workflow.get("group_id") else "personal",
        "scope_id": workflow.get("group_id") or workflow["user_id"],
        "workflow_id": workflow["id"], "run_id": run_id,
        "definition_revision": workflow_definition_revision(workflow),
        "node_id": node_id, "iteration_path": path,
    })


def workflow_execution_id(workflow, run_id, node_id, iteration_path=None):
    path, _ = _execution_parts(workflow, run_id, node_id, iteration_path)
    return _execution_digest(workflow, run_id, node_id, path)


def workflow_node_identity(workflow, run_id, node_id, execution_id, attempt, *, task_id=None, iteration_path=None):
    path, node = _execution_parts(workflow, run_id, node_id, iteration_path)
    if execution_id != _execution_digest(workflow, run_id, node_id, path) or type(attempt) is not int or attempt < 1:
        raise ValueError("The execution or attempt does not match its authorized producer.")
    if workflow.get("definition_version") != 3:
        raise ValueError("Exact node identities require a structured workflow.")
    if node.get("task_id") != task_id:
        raise ValueError("The node and task identity do not match the saved flow.")
    identity = {
        "workflow_id": workflow["id"], "run_id": run_id, "node_id": node_id,
        "execution_id": execution_id, "iteration_path": path, "attempt": attempt,
    }
    if task_id is not None:
        if not isinstance(task_id, str) or not task_id:
            raise ValueError("A task producer requires a real task id.")
        identity["task_id"] = task_id
    return identity
