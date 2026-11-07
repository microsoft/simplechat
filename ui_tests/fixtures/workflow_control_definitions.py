# workflow_control_definitions.py
"""
Shared valid M4A definitions for closed V2 authoring and inspection fixtures.
Version: 0.261.116
Implemented in: 0.261.116
"""

from ui_tests.fixtures.workflow_editor import workflow_record


STRUCTURED_ID = "structured-review"


def flow_binding(name, node_id, output="json", *, required=True, kind="json"):
    return {
        "name": name,
        "source": {"kind": "node_output", "node_id": node_id, "output": output, "scope": "current"},
        "required": required,
        "expected_kind": kind,
        "allow_partial": False,
    }


def flow_condition(field):
    return {
        "op": "eq",
        "left": {"input": "decision", "path": f"/{field}"},
        "right": {"literal": True},
    }


def structured_workflow_record(identifier=STRUCTURED_ID, name="Structured review", **overrides):
    tasks = [
        {
            "id": task_id, "type": "instructions", "name": task_name,
            "instructions": f"Produce the {task_name.lower()} result.",
            "order": index + 1, "runner": {"type": "inherit"}, "inputs": [],
            "reference_ids": [], "document_action": {"type": "none"},
            "output_contract": {"kind": "text", "allow_partial": False, "require_complete_coverage": False},
        }
        for index, (task_id, task_name) in enumerate([
            ("evaluate", "Evaluate"), ("accept", "Accept"), ("review", "Review"),
            ("note", "Optional note"), ("finish", "Finish"),
        ])
    ]
    tasks[0]["output_contract"] = {
        "kind": "json", "allow_partial": False, "require_complete_coverage": False,
        "schema": {
            "type": "object",
            "properties": {"pass": {"type": "boolean"}, "add_note": {"type": "boolean"}},
            "required": ["pass", "add_note"],
        },
    }
    tasks[3]["inputs"] = [flow_binding("decision", "evaluate")]
    tasks[4]["inputs"] = [
        flow_binding("report", "decision-join", "report", kind="text"),
        flow_binding("note", "note", "text", required=False, kind="text"),
    ]
    flow = {
        "id": "root",
        "nodes": [
            {"id": "evaluate", "kind": "task", "task_id": "evaluate"},
            {
                "id": "choose", "kind": "if", "inputs": [flow_binding("decision", "evaluate")],
                "condition": flow_condition("pass"),
                "then": {"id": "accepted-path", "nodes": [{"id": "accept", "kind": "task", "task_id": "accept"}]},
                "else": {"id": "review-path", "nodes": [{"id": "review", "kind": "task", "task_id": "review"}]},
                "join": {
                    "id": "decision-join",
                    "exports": [{
                        "name": "report", "expected_kind": "text", "required": True,
                        "then": {"node_id": "accept", "output": "text"},
                        "else": {"node_id": "review", "output": "text"},
                    }],
                },
            },
            {
                "id": "bypass-note", "kind": "route", "inputs": [flow_binding("decision", "evaluate")],
                "condition": flow_condition("pass"), "target": {"node_id": "finish"},
            },
            {"id": "note", "kind": "task", "task_id": "note", "run_when": flow_condition("add_note")},
            {"id": "finish", "kind": "task", "task_id": "finish"},
        ],
        "outputs": [flow_binding("report", "finish", "text", kind="text")],
    }
    return workflow_record(
        identifier, name=name, definition_version=3, durable_execution=True,
        tasks=tasks, flow=flow, limits={"max_executions": 5000, "deadline_seconds": 86400},
        **overrides,
    )
