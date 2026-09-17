# functions_workflow_identity.py
"""Stable authorized node/execution identity, independent of a mutable attempt."""

import hashlib
import json

from functions_workflow_definitions import workflow_definition_revision


def canonical_digest(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def workflow_execution_id(workflow, run_id, node_id, iteration_path=None):
    path = [] if iteration_path is None else iteration_path
    if not isinstance(path, list) or path:
        raise ValueError("M4A executions require an empty iteration path.")
    if not all(isinstance(value, str) and value for value in (workflow.get("id"), workflow.get("user_id"), run_id, node_id)):
        raise ValueError("An execution requires its authorized workflow, run and node.")
    return canonical_digest({
        "scope_type": "group" if workflow.get("group_id") else "personal",
        "scope_id": workflow.get("group_id") or workflow["user_id"],
        "workflow_id": workflow["id"], "run_id": run_id,
        "definition_revision": workflow_definition_revision(workflow),
        "node_id": node_id, "iteration_path": path,
    })


def workflow_node_identity(workflow, run_id, node_id, execution_id, attempt, *, task_id=None, iteration_path=None):
    path = [] if iteration_path is None else iteration_path
    if execution_id != workflow_execution_id(workflow, run_id, node_id, path) or type(attempt) is not int or attempt < 1:
        raise ValueError("The execution or attempt does not match its authorized producer.")
    if workflow.get("definition_version") != 3:
        raise ValueError("Exact node identities require a structured workflow.")
    matched = node_id == workflow.get("flow", {}).get("id") and task_id is None
    pending = list(workflow.get("flow", {}).get("nodes") or [])
    checked = 0
    while pending:
        node = pending.pop()
        checked += 1
        if checked > 256:
            raise ValueError("The saved flow identity is not bounded.")
        if node.get("id") == node_id:
            matched = node.get("task_id") == task_id
        if node.get("kind") == "if":
            matched |= node.get("join", {}).get("id") == node_id and task_id is None
            pending.extend(node.get("then", {}).get("nodes") or [])
            pending.extend(node.get("else", {}).get("nodes") or [])
    if not matched:
        raise ValueError("The node and task identity do not match the saved flow.")
    identity = {
        "workflow_id": workflow["id"], "run_id": run_id, "node_id": node_id,
        "execution_id": execution_id, "iteration_path": list(path), "attempt": attempt,
    }
    if task_id is not None:
        if not isinstance(task_id, str) or not task_id:
            raise ValueError("A task producer requires a real task id.")
        identity["task_id"] = task_id
    return identity
