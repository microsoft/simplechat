# functions_workflow_loop_runners.py
"""Current runner eligibility for locally metered workflow loop visits."""

from functions_workflow_bindings import WorkflowInputError
from functions_workflow_execution import current_workflow_execution


def assert_workflow_loop_agent_type(agent_type):
    execution = current_workflow_execution()
    task_id = (getattr(execution, "node", None) or {}).get("task_id")
    reporting = execution is not None and any(
        task.get("id") == task_id and task.get("input_processing") == "saved_record_report"
        for task in (getattr(execution, "workflow", {}) or {}).get("tasks") or []
    )
    if execution is not None and (getattr(execution, "iteration_path", []) or reporting) and (agent_type or "local") != "local":
        raise WorkflowInputError(
            "For each and saved-record reporting require locally metered models or local agents. Hosted agents are not supported for these steps.",
        )


def require_local_loop_runner(workflow, *, actor_user_id, settings, resolve_agent=None):
    if workflow.get("runner_type") != "agent":
        return
    if resolve_agent is None:
        # Resolve current stored agents only at an authorized save/run boundary.
        from functions_agent_delegation import resolve_delegation_agent

        resolve_agent = resolve_delegation_agent
    agent = resolve_agent(workflow.get("selected_agent") or {}, user_id=actor_user_id, settings=settings)
    if agent.get("agent_type", "local") != "local":
        raise WorkflowInputError(
            "For each and saved-record reporting require locally metered models or local agents. Hosted agents are not supported for these steps.",
        )


def validate_workflow_loop_runners(workflow, *, actor_user_id, settings, resolve_agent=None):
    if workflow.get("definition_version") != 3:
        return
    tasks = {task["id"]: task for task in workflow.get("tasks") or []}
    pending = [(node, False) for node in (workflow.get("flow") or {}).get("nodes") or []]
    while pending:
        node, inside = pending.pop()
        if node["kind"] == "for_each":
            pending.extend((child, True) for child in node["body"]["nodes"])
        elif node["kind"] == "if":
            pending.extend((child, inside) for name in ("then", "else") for child in node[name]["nodes"])
        elif node["kind"] == "task" and (
            inside or tasks[node["task_id"]].get("input_processing") == "saved_record_report"
        ):
            task = tasks[node["task_id"]]
            if task.get("publication") is not None:
                continue
            runner = task.get("runner") or {"type": "inherit"}
            resolved = workflow if runner["type"] == "inherit" else {
                **workflow, "runner_type": runner["type"], "selected_agent": runner.get("selected_agent") or {},
            }
            require_local_loop_runner(
                resolved, actor_user_id=actor_user_id, settings=settings, resolve_agent=resolve_agent,
            )
