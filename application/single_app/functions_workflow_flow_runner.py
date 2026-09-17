# functions_workflow_flow_runner.py
"""Structured traversal around the existing task dispatcher, with frozen decisions."""

import json
from copy import deepcopy

from functions_workflow_bindings import WorkflowInputError
from functions_analysis_access import AnalysisResultUnavailable
from functions_workflow_definitions import workflow_output_kind_matches
from functions_workflow_flow import MISSING, compile_workflow_flow, evaluate_predicate
from functions_workflow_identity import canonical_digest, workflow_node_identity
from functions_workflow_node_results import load_workflow_node_input
from functions_workflow_results import _build_task_result, persist_workflow_task_result, workflow_result_summary


class WorkflowFlowRunner:
    def __init__(self, workflow, run_id, execution, task_results, *, actor_user_id, settings=None,
                 load_output=load_workflow_node_input, persist=persist_workflow_task_result):
        self.workflow = workflow
        self.run_id = run_id
        self.execution = execution
        self.task_results = task_results
        self.actor_user_id = actor_user_id
        self.settings = settings or {}
        self.load_output = load_output
        self.persist = persist
        self.compiled = compile_workflow_flow(workflow)
        self.catalogue = {task["id"]: task for task in self.compiled["tasks"]}
        self.completed = {}
        self.final_outputs = []
        self.partial = False
        self.failed = False
        self.finished = False
        self.control_receipts = []

    @staticmethod
    def _receipts(values):
        return list({canonical_digest(value): value for value in values}.values())

    @staticmethod
    def _control_receipt(summary):
        name = "decision" if "decision" in summary["outputs"] else summary["authoritative_output"]
        return {"producer": summary["producer"], "result_ref": summary["result_ref"],
                "output_name": name, "output_ref": summary["outputs"][name]["result_ref"],
                "control": True}

    def resolve(self, bindings, *, condition=None):
        inputs, receipts, values = [], [], {}
        for binding in bindings:
            source = binding["source"]
            producer = self.completed.get(source["node_id"])
            if producer is None or producer.get("state") == "skipped":
                if binding["required"]:
                    raise WorkflowInputError("A required producer was intentionally skipped or did not finish.")
                inputs.append({"name": binding["name"], "status": "unavailable"})
                values[binding["name"]] = MISSING
                continue
            if producer.get("state") not in {"succeeded", "completed", "completed_partial"}:
                raise WorkflowInputError("The selected producer is failed, invalid or pending, not optional absence.")
            summary = producer["summary"]
            try:
                prompt, receipt = self.load_output(
                    self.workflow, self.run_id, summary["producer"], summary["result_ref"],
                    output_name=source["output"], allow_partial=binding["allow_partial"],
                    reader_user_id=self.actor_user_id, required=binding["required"],
                )
            except AnalysisResultUnavailable:
                from functions_workflow_execution import execution_fingerprint

                self.execution._pause(self.execution.node["id"], execution_fingerprint(summary))
            if prompt is None:
                inputs.append({"name": binding["name"], "status": "unavailable"})
                values[binding["name"]] = MISSING
                continue
            payload = json.loads(prompt)
            if not workflow_output_kind_matches(payload["kind"], binding["expected_kind"]):
                raise WorkflowInputError("The input does not match its declared output kind.")
            if condition is not None and binding["name"] in condition:
                validation = summary.get("workflow_validation") or {}
                if validation.get("eligible") is not True or not producer.get("structured_validated"):
                    raise WorkflowInputError("Conditions require structurally validated output fields.")
            if (summary.get("workflow_validation") or {}).get("status") == "accepted_partial":
                self.partial = True
            values[binding["name"]] = payload["value"]
            inputs.append({"name": binding["name"], "status": "available", "result": payload})
            receipts.append({**receipt, "input_name": binding["name"]})
        return {
            "task_context": json.dumps({"inputs": inputs}, ensure_ascii=False, sort_keys=True) if inputs else "",
            "consumed_inputs": self._receipts([*receipts, *self.control_receipts]),
            "bound_inputs": receipts, "values": values,
        }

    @staticmethod
    def _predicate_names(predicate):
        names, pending = set(), [predicate]
        while pending:
            value = pending.pop()
            if isinstance(value, dict):
                if "input" in value:
                    names.add(value["input"])
                pending.extend(value.values())
            elif isinstance(value, list):
                pending.extend(value)
        return names

    def _admit_control(self, node):
        admitted_by_condition = node["kind"] == "task" and self.execution.store.journal_read(
            "decision", ["control", self.execution.execution_id()],
        ) is not None
        self.execution.store.journal_commit(
            self.execution.lease.token, "admission", [self.execution.execution_id(), 1],
            {"execution_id": self.execution.execution_id(), "attempt": 1},
            admission=not admitted_by_condition, immutable=True,
            updates={"cursor": {"region_id": self.execution.region_id, "node_id": node["id"]}, "phase": node["id"]},
        )

    def _control_result(self, node, choice, receipts):
        identity = workflow_node_identity(
            self.workflow, self.run_id, node["id"], self.execution.execution_id(), 1,
            task_id=node.get("task_id"),
        )
        envelope = _build_task_result(
            {"reply": "", "authoritative_result": {"kind": "json", "value": choice}},
            identity, "workflow-result-v2",
        )
        envelope["consumed_inputs"] = receipts
        envelope["workflow_validation"] = {"version": 1, "status": "valid", "eligible": True, "reason_codes": []}
        if node["kind"] == "task":
            envelope["outputs"] = {"decision": envelope["outputs"]["json"]}
            envelope["authoritative_output"] = None
            envelope["execution"]["status"] = "skipped" if choice["choice"] == "skip" else "succeeded"
        manifest, reference = self.persist(
            envelope, workflow=self.workflow, run_id=self.run_id, task_id=node.get("task_id"), settings=self.settings,
        )
        return workflow_result_summary(manifest, reference)

    def _decision(self, node, inputs, choose):
        from functions_workflow_execution import execution_fingerprint

        digest = execution_fingerprint({"context": inputs["task_context"], "consumed_inputs": inputs["consumed_inputs"]})
        key = ["control", self.execution.execution_id()]
        saved = self.execution.store.journal_read("decision", key)
        if saved:
            if saved["payload"]["input_digest"] != digest:
                self.execution._pause(node["id"], digest)
            choice = saved["payload"]["decision"]
        else:
            choice = choose()
            self.execution.store.journal_commit(
                self.execution.lease.token, "decision", key, {
                    "execution_id": self.execution.execution_id(), "node_id": node["id"], "attempt": 1,
                    "iteration_path": [], "input_digest": digest, "decision": choice,
                    "consumed_inputs": inputs["consumed_inputs"],
                }, updates={"cursor": {"region_id": self.execution.region_id, "node_id": node["id"]}},
                admission=True, immutable=True,
            )
        return choice

    def _skip(self, node, region_id, reason):
        self.execution.set_node(node, region_id)
        self._admit_control(node)
        decision = self.execution.store.journal_read("decision", ["control", self.execution.execution_id()])
        receipts = self._receipts([*((decision or {}).get("payload", {}).get("consumed_inputs") or []), *self.control_receipts])
        self.execution.finish_node(state="skipped", attempt=0, reason_code=reason, consumed_inputs=receipts)
        self.completed[node["id"]] = {"state": "skipped"}
        if node["kind"] == "if":
            for branch in ("then", "else"):
                for child in node[branch]["nodes"]:
                    self._skip(child, node[branch]["id"], reason)
            join = self.compiled["nodes"][node["join"]["id"]]["node"]
            self._skip(join, region_id, reason)

    def _join(self, node, region_id, branch, decision_summary):
        join = self.compiled["nodes"][node["join"]["id"]]["node"]
        self.execution.set_node(join, region_id)
        receipts = [{
            "producer": decision_summary["producer"], "result_ref": decision_summary["result_ref"],
            "output_name": decision_summary["authoritative_output"],
            "output_ref": decision_summary["outputs"][decision_summary["authoritative_output"]]["result_ref"],
        }]
        exports, structured = {}, True
        for export in node["join"]["exports"]:
            source = export[branch]
            binding = {
                "name": export["name"], "source": source, "expected_kind": export["expected_kind"],
                "required": export["required"], "allow_partial": True,
            }
            resolved = self.resolve([binding])
            if not resolved["bound_inputs"]:
                continue
            selected = resolved["bound_inputs"][0]
            receipts.append(selected)
            producer = self.completed[source["node_id"]]
            structured = structured and producer.get("structured_validated", False)
            descriptor = producer["summary"]["outputs"][selected["output_name"]]
            exports[export["name"]] = {
                "kind": descriptor["kind"], "result_ref": selected["output_ref"],
                "selected_producer": selected,
            }
        self._admit_control(join)
        receipts = self._receipts([*receipts, *self.control_receipts])
        summary = self._control_result(join, {"choice": branch}, receipts)
        # Export descriptors point to the selected producer, never concatenated/reconstructed values.
        identity = summary["producer"]
        from functions_workflow_result_store import load_workflow_node_result, save_workflow_node_result
        from functions_workflow_node_results import result_selectors

        manifest = load_workflow_node_result(
            self.workflow, self.run_id, None, summary["result_ref"], **result_selectors(identity),
        )
        manifest["outputs"] = exports
        manifest["authoritative_output"] = next(iter(exports), None)
        reference = save_workflow_node_result(
            self.workflow, self.run_id, None, manifest, settings=self.settings, **result_selectors(identity),
        )
        summary = workflow_result_summary(manifest, reference)
        self.completed[join["id"]] = {"state": "completed", "summary": summary, "structured_validated": structured}
        self.execution.finish_node(state="completed", attempt=1, decision={"choice": branch}, workflow_result=summary,
                                   consumed_inputs=receipts)

    def _region(self, region):
        children = region["nodes"]
        index = 0
        while index < len(children):
            node = children[index]
            self.execution.set_node(node, region["id"])
            self.execution.check()
            if node["kind"] == "task":
                task = deepcopy(self.catalogue[node["task_id"]])
                if "run_when" in node:
                    inputs = self.resolve(task["inputs"], condition=self._predicate_names(node["run_when"]))
                    choice = self._decision(node, inputs, lambda: {
                        "choice": "run" if evaluate_predicate(node["run_when"], inputs["values"]) else "skip",
                    })
                    control_summary = self._control_result(node, choice, inputs["consumed_inputs"])
                    self.control_receipts.append(self._control_receipt(control_summary))
                    if choice["choice"] == "skip":
                        self._skip(node, region["id"], "run_when_false")
                        index += 1
                        continue
                yield task
                checkpoint = next((item for item in reversed(self.task_results) if item["task"]["id"] == task["id"]), None)
                if checkpoint is None:
                    raise WorkflowInputError("A selected task did not save an execution outcome.")
                result = checkpoint.get("result") or {}
                summary = result.get("workflow_result")
                state = checkpoint["status"]
                if summary:
                    self.completed[node["id"]] = {
                        "state": state, "summary": summary,
                        "structured_validated": bool((task.get("output_contract") or {}).get("schema")),
                    }
                    self.execution.finish_node(
                        state=state, workflow_result=summary, workflow_validation=result.get("workflow_validation"),
                        consumed_inputs=checkpoint.get("consumed_inputs") or [],
                    )
                    self.partial |= (result.get("workflow_validation") or {}).get("status") == "accepted_partial"
                else:
                    self.completed[node["id"]] = {"state": "failed"}
                    self.execution.finish_node(state="failed", reason_code="task_failed")
                self.failed |= state not in {"succeeded", "completed"}
            else:
                inputs = self.resolve(node["inputs"], condition=self._predicate_names(node["condition"]))
                choice = self._decision(node, inputs, lambda: (
                    {"choice": "then" if evaluate_predicate(node["condition"], inputs["values"]) else "else"}
                    if node["kind"] == "if" else
                    {"target": node["target"] if evaluate_predicate(node["condition"], inputs["values"]) else None}
                ))
                summary = self._control_result(node, choice, inputs["consumed_inputs"])
                self.control_receipts.append(self._control_receipt(summary))
                self.completed[node["id"]] = {"state": "completed", "summary": summary, "structured_validated": True}
                self.execution.finish_node(state="completed", attempt=1, decision=choice, workflow_result=summary,
                                           consumed_inputs=inputs["consumed_inputs"])
                if node["kind"] == "if":
                    branch = choice["choice"]
                    other = "else" if branch == "then" else "then"
                    for child in node[other]["nodes"]:
                        self._skip(child, node[other]["id"], "unselected_branch")
                    yield from self._region(node[branch])
                    self._join(node, region["id"], branch, summary)
                elif choice.get("target"):
                    target = choice["target"]
                    destination = next(
                        (position for position, child in enumerate(children) if child["id"] == target.get("node_id")),
                        len(children),
                    )
                    for child in children[index + 1:destination]:
                        self._skip(child, region["id"], "forward_route")
                    index = destination
                    continue
            index += 1

    def tasks(self):
        yield from self._region(self.compiled["flow"])
        self.final_outputs = self.resolve(self.compiled["flow"]["outputs"])["bound_inputs"]
        self.execution._update(self.execution.check(), {"progress": {
            "completed": len(self.completed), "total": len(self.compiled["nodes"]),
        }})
        self.finished = True
