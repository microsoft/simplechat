# functions_workflow_flow_runner.py
"""Structured traversal around the existing task dispatcher, with frozen decisions."""

import json
from copy import deepcopy

from functions_workflow_bindings import WorkflowInputError
from functions_analysis_access import AnalysisResultUnavailable
from functions_workflow_definitions import workflow_output_kind_matches
from functions_workflow_flow import MISSING, compile_workflow_flow, evaluate_predicate
from functions_workflow_identity import canonical_digest, workflow_execution_id, workflow_node_identity
from functions_workflow_node_results import (
    authorize_workflow_node_result_read, load_workflow_node_input, open_workflow_record_input,
)
from functions_workflow_results import (
    WorkflowResultNotReadyError, _build_task_result, persist_workflow_task_result, workflow_result_summary,
)


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
        self.loop_frames = []
        self.has_loops = any(entry["node"]["kind"] == "for_each" for entry in self.compiled["nodes"].values())

    def _producer_path(self, node_id):
        ancestors = self.compiled.get("node_loop_ids", {}).get(node_id, [])
        path = self.execution.iteration_path
        if [frame["loop_id"] for frame in path[:len(ancestors)]] != ancestors:
            raise WorkflowInputError("An input cannot select a different loop item or body scope.")
        return path[:len(ancestors)]

    def producer(self, node_id):
        path = self._producer_path(node_id)
        if not path and node_id in self.completed:
            return self.completed[node_id]
        identifier = workflow_execution_id(self.workflow, self.run_id, node_id, path)
        row = self.execution.store.journal_read("execution", identifier)
        if row is None:
            return None
        payload = row["payload"]
        node = self.compiled["nodes"][node_id]["node"]
        contract = self.catalogue[node["task_id"]].get("output_contract") if node["kind"] == "task" else node.get("output_contract")
        return {
            "state": payload["state"], "summary": payload.get("workflow_result"),
            "structured_validated": payload.get("structured_validated", bool((contract or {}).get("schema"))),
        }

    def _remember(self, node_id, value):
        if not self.execution.iteration_path:
            self.completed[node_id] = value

    def current_item(self, loop_id):
        from functions_workflow_iterations import load_frozen_item_value

        frame = next((frame for frame in self.loop_frames if frame["node"]["id"] == loop_id), None)
        if frame is None:
            raise WorkflowInputError("The current item is outside its declared loop.")
        return load_frozen_item_value(
            self.workflow, self.run_id, frame["manifest"], frame["item"],
            reader_user_id=self.actor_user_id, load_result=self.execution.load_result,
        )

    def current_document_action(self, action):
        frame = next((frame for frame in self.loop_frames if frame["node"]["id"] == action.get("loop_id")), None)
        if frame is None or frame["item"]["kind"] != "document":
            raise WorkflowInputError("Current-document Analyze requires an authorized document loop item.")
        document = self.current_item(action["loop_id"])["value"]
        scope = document["scope_type"]
        return {
            "type": "analyze", "target_mode": "selected", "analysis_mode": "combined",
            "document_ids": [document["document_id"]], "doc_scope": scope,
            "active_group_ids": [document["scope_id"]] if scope == "group" else [],
            "active_public_workspace_id": [document["scope_id"]] if scope == "public" else [],
        }

    @staticmethod
    def _receipts(values):
        return list({canonical_digest(value): value for value in values}.values())

    @staticmethod
    def _control_receipt(summary):
        name = "decision" if "decision" in summary["outputs"] else summary["authoritative_output"]
        return {"producer": summary["producer"], "result_ref": summary["result_ref"],
                "output_name": name, "output_ref": summary["outputs"][name]["result_ref"],
                "control": True}

    def resolve(self, bindings, *, condition=None, stream_collections=False, metadata_only=False):
        from functions_workflow_results import _require_completed_result

        inputs, receipts, values, record_inputs = [], [], {}, []
        for binding in bindings:
            source = binding["source"]
            if source.get("kind") == "loop_item":
                value = self.current_item(source["loop_id"])
                values[binding["name"]] = value
                inputs.append({"name": binding["name"], "status": "available", "result": {
                    "kind": "json", "value": value,
                }})
                continue
            producer = self.producer(source["node_id"])
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
                name = summary.get("authoritative_output") if source["output"] == "authoritative" else source["output"]
                descriptor = summary.get("outputs", {}).get(name) or {}
                if stream_collections and descriptor.get("kind") in {"records", "document_results"}:
                    reader = open_workflow_record_input(
                        self.workflow, self.run_id, summary["producer"], summary["result_ref"],
                        output_name=source["output"], allow_partial=binding["allow_partial"],
                        reader_user_id=self.actor_user_id, load_result=self.execution.load_result,
                    )
                    if not workflow_output_kind_matches(reader.kind, binding["expected_kind"]):
                        raise WorkflowInputError("The selected collection does not match the declared input kind.")
                    receipts.append({**reader.receipt, "input_name": binding["name"]})
                    values[binding["name"]] = reader
                    record_inputs.append({"name": binding["name"], "reader": reader})
                    inputs.append({"name": binding["name"], "status": "available", "result": {
                        "kind": reader.kind, "record_count": reader.record_count,
                        "consumed_result": reader.receipt, "complete_records_supplied_separately": True,
                    }})
                    self.partial |= (summary.get("workflow_validation") or {}).get("status") == "accepted_partial"
                    continue
                if metadata_only:
                    manifest, access = authorize_workflow_node_result_read(
                        self.workflow, self.run_id, summary["producer"], summary["result_ref"],
                        reader_user_id=self.actor_user_id, load_result=self.execution.load_result,
                    )
                    _require_completed_result(manifest, allow_partial=binding["allow_partial"])
                    if access["source_snapshot_changed"]:
                        raise AnalysisResultUnavailable("analysis_source_snapshot_changed")
                    if (manifest.get("workflow_validation") or {}).get("eligible") is not True:
                        raise WorkflowInputError("The selected output is not eligible.")
                    descriptor = manifest.get("outputs", {}).get(name)
                    prompt = None if descriptor is None else json.dumps({"kind": descriptor["kind"], "value": None})
                    receipt = None if descriptor is None else {
                        "producer": summary["producer"], "result_ref": summary["result_ref"],
                        "output_name": name, "output_ref": descriptor["result_ref"],
                    }
                    if descriptor is None and binding["required"]:
                        raise WorkflowInputError("The required selected output is unavailable.")
                else:
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
            "bound_inputs": receipts, "values": values, "record_inputs": record_inputs,
            "iteration_inputs": deepcopy(self.execution.iteration_inputs),
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
            updates={"cursor": self.execution.cursor(), "phase": node["id"]},
        )

    def _control_result(self, node, choice, receipts):
        identity = workflow_node_identity(
            self.workflow, self.run_id, node["id"], self.execution.execution_id(), 1,
            task_id=node.get("task_id"), iteration_path=self.execution.iteration_path,
        )
        envelope = _build_task_result(
            {"reply": "", "authoritative_result": {"kind": "json", "value": choice}},
            identity, "workflow-result-v2",
        )
        envelope["consumed_inputs"] = receipts
        if self.execution.iteration_inputs:
            envelope["iteration_inputs"] = deepcopy(self.execution.iteration_inputs)
        if node["kind"] == "for_each":
            loop = self.execution.store.journal_read("loop", self.execution.execution_id())
            if loop:
                envelope["frozen_loop"] = {
                    "producer": loop["payload"]["identity"], "manifest_ref": loop["payload"]["manifest_ref"],
                }
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
                    "iteration_path": deepcopy(self.execution.iteration_path), "input_digest": digest, "decision": choice,
                    "consumed_inputs": inputs["consumed_inputs"],
                    "iteration_inputs": deepcopy(self.execution.iteration_inputs),
                }, updates={"cursor": self.execution.cursor()},
                admission=True, immutable=True,
            )
        return choice

    def _skip(self, node, region_id, reason):
        self.execution.set_node(node, region_id)
        self._admit_control(node)
        decision = self.execution.store.journal_read("decision", ["control", self.execution.execution_id()])
        receipts = self._receipts([*((decision or {}).get("payload", {}).get("consumed_inputs") or []), *self.control_receipts])
        self.execution.finish_node(state="skipped", attempt=0, reason_code=reason, consumed_inputs=receipts)
        self._remember(node["id"], {"state": "skipped"})
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
            resolved = self.resolve([binding], metadata_only=True)
            if not resolved["bound_inputs"]:
                continue
            selected = resolved["bound_inputs"][0]
            receipts.append(selected)
            producer = self.producer(source["node_id"])
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
        self._remember(join["id"], {"state": "completed", "summary": summary, "structured_validated": structured})
        self.execution.finish_node(state="completed", attempt=1, decision={"choice": branch}, workflow_result=summary,
                                   consumed_inputs=receipts, structured_validated=structured)

    def note_item_failure(self, state="failed"):
        if not self.loop_frames:
            return
        frame = self.loop_frames[-1]
        key = [frame["manifest"]["identity"]["execution_id"], frame["item"]["item_id"]]
        row = self.execution.store.journal_read("iteration", key)
        if row:
            self.execution.store.journal_commit(
                self.execution.lease.token, "iteration", key, {**row["payload"], "state": state},
            )

    def _for_each(self, node, region_id):
        from functions_workflow_iterations import (
            freeze_workflow_loop, frozen_item_receipt, read_frozen_item,
        )
        from functions_workflow_loop_inputs import WorkflowLoopInputError

        parent_path = deepcopy(self.execution.iteration_path)
        parent_receipts = deepcopy(self.execution.iteration_inputs)
        controls = list(self.control_receipts)
        self._admit_control(node)
        previous = self.execution.store.journal_read("execution", self.execution.execution_id())
        if previous and previous["payload"].get("state") == "completed":
            summary = previous["payload"]["workflow_result"]
            authorize_workflow_node_result_read(
                self.workflow, self.run_id, summary["producer"], summary["result_ref"],
                reader_user_id=self.actor_user_id, load_result=self.execution.load_result,
            )
            state = self.execution.store.journal_read("loop", self.execution.execution_id())["payload"]
            self.failed |= state.get("failed", 0) > 0
            self._remember(node["id"], {"state": "completed", "summary": summary, "structured_validated": False})
            return
        self.execution.record_execution(state="running", attempt=1)
        self.execution._attempt(1, state="running")
        try:
            inputs = self.resolve(node["inputs"], stream_collections=True)
            reader = inputs["values"].get(node["iterable"].get("name")) if node["iterable"]["kind"] == "input" else None
            manifest, reference, state = freeze_workflow_loop(
                self.execution, node, actor_user_id=self.actor_user_id,
                record_input=reader, consumed_inputs=inputs["consumed_inputs"],
            )
        except WorkflowLoopInputError as exc:
            self.execution.pause_input(exc.public_message, code=getattr(exc, "code", "workflow_loop_input_unavailable"))
        except AnalysisResultUnavailable:
            self.execution.pause_input("The loop's original input sources are no longer available.", code="workflow_loop_source_unavailable")
        for index in range(state["next_index"], manifest["count"]):
            self.execution.set_node(node, region_id, iteration_path=parent_path, iteration_inputs=parent_receipts)
            self.execution.check()
            item = read_frozen_item(
                self.workflow, self.run_id, manifest, index, load_result=self.execution.load_result,
            )
            path = parent_path + [{"loop_id": node["id"], "item_id": item["item_id"], "index": index}]
            item_receipts = parent_receipts + [frozen_item_receipt(manifest, reference, item)]
            key = [manifest["identity"]["execution_id"], item["item_id"]]
            saved = self.execution.store.journal_read("iteration", key)
            prior = (saved or {}).get("payload") or {}
            if prior.get("state") not in {"completed", "skipped"}:
                self.execution.store.journal_commit(
                    self.execution.lease.token, "admission", ["iteration", *key],
                    {"execution_id": manifest["identity"]["execution_id"], "item_id": item["item_id"], "index": index},
                    admission=True, immutable=True,
                )
                self.execution.store.journal_commit(self.execution.lease.token, "iteration", key, {
                    "execution_id": manifest["identity"]["execution_id"], "item_id": item["item_id"],
                    "item_sha256": item["item_sha256"], "index": index, "iteration_path": path, "state": "running",
                }, updates={"loop_progress": {
                    "loop_id": node["id"], "loop_execution_id": manifest["identity"]["execution_id"],
                    "total": manifest["count"], "current_index": index, "limit": manifest["max_items"],
                    **{name: state.get(name, 0) for name in ("completed", "skipped", "failed")},
                    "pending": manifest["count"] - index,
                }})
                self.loop_frames.append({"node": node, "manifest": manifest, "reference": reference, "item": item})
                try:
                    self.current_item(node["id"])
                    self.execution.set_node(None, node["body"]["id"], iteration_path=path, iteration_inputs=item_receipts)
                    yield from self._region(node["body"])
                    bindings = node["body"]["outputs"]
                    resolved = self.resolve(bindings, metadata_only=True)
                    exports = {receipt["input_name"]: receipt for receipt in resolved["bound_inputs"]}
                    item_state = "completed" if len(exports) == len(bindings) else "skipped"
                    current = self.execution.store.journal_read("iteration", key)
                    if current["payload"].get("state") not in {"running", "completed", "skipped"}:
                        item_state = "failed"
                except AnalysisResultUnavailable:
                    self.execution.pause_input(
                        "The current loop item's original source is no longer available.", code="workflow_loop_source_unavailable",
                    )
                except WorkflowInputError:
                    exports, item_state = {}, "failed"
                    self.failed = True
                finally:
                    self.loop_frames.pop()
                    self.control_receipts = list(controls)
                    self.execution.set_node(node, region_id, iteration_path=parent_path, iteration_inputs=parent_receipts)
                exports_ref = self.execution.save_result(
                    self.workflow, self.run_id, None, {
                        "version": "workflow-loop-exports-v1", "loop_execution_id": manifest["identity"]["execution_id"],
                        "item_id": item["item_id"], "index": index, "exports": exports,
                    }, settings=self.settings, **self.execution.selectors(attempt=1),
                )
                prior = {
                    "execution_id": manifest["identity"]["execution_id"], "item_id": item["item_id"],
                    "item_sha256": item["item_sha256"], "index": index, "iteration_path": path,
                    "state": item_state, "exports_ref": exports_ref,
                }
                self.execution.store.journal_commit(self.execution.lease.token, "iteration", key, prior)
            state = {
                **state, "next_index": index + 1,
                "completed": state["completed"] + int(prior["state"] == "completed"),
                "skipped": state["skipped"] + int(prior["state"] == "skipped"),
                "failed": state["failed"] + int(prior["state"] not in {"completed", "skipped"}),
            }
            self.execution.store.journal_commit(
                self.execution.lease.token, "loop", manifest["identity"]["execution_id"], state,
                updates={"cursor": self.execution.cursor(), "loop_progress": {
                    "loop_id": node["id"], "loop_execution_id": manifest["identity"]["execution_id"],
                    "total": manifest["count"], "current_index": index, "limit": manifest["max_items"],
                    **{name: state[name] for name in ("completed", "skipped", "failed")},
                    "pending": manifest["count"] - index - 1,
                }},
            )
            self.task_results[:] = [
                result for result in self.task_results
                if not ((result.get("result") or {}).get("workflow_result") or {}).get("producer", {}).get("iteration_path")
                and not result.get("iteration_path")
            ]
        self.execution.set_node(node, region_id, iteration_path=parent_path, iteration_inputs=parent_receipts)
        state = {**state, "state": "completed"}
        self.execution.store.journal_commit(self.execution.lease.token, "loop", manifest["identity"]["execution_id"], state)
        self.failed |= state["failed"] > 0
        summary = self._control_result(node, {"choice": "complete", "item_count": manifest["count"]}, inputs["consumed_inputs"])
        self._remember(node["id"], {"state": "completed", "summary": summary, "structured_validated": False})
        self.execution.finish_node(state="completed", attempt=1, workflow_result=summary, consumed_inputs=inputs["consumed_inputs"])

    def _collect(self, node, region_id):
        from functions_workflow_collect import collect_workflow_loop
        from functions_workflow_iterations import load_frozen_loop, loop_execution_identity

        loop_node = self.compiled["nodes"][node["source"]["loop_id"]]["node"]
        identity = loop_execution_identity(
            self.workflow, self.run_id, loop_node["id"], self._producer_path(loop_node["id"]),
        )
        frozen, reference, loop_state = load_frozen_loop(
            self.workflow, self.run_id, identity, store=self.execution.store, load_result=self.execution.load_result,
        )
        self.execution.set_node(node, region_id)

        def write():
            attempt = self.execution.unit("collect")["attempt"]
            self.execution.store.journal_commit(
                self.execution.lease.token, "admission", [self.execution.execution_id(), attempt],
                {"execution_id": self.execution.execution_id(), "attempt": attempt}, admission=True, immutable=True,
            )
            self.execution.record_execution(state="running", attempt=attempt)
            self.execution._attempt(attempt, state="running")
            return collect_workflow_loop(
                self.execution, node, loop_node, frozen, reference, loop_state,
                actor_user_id=self.actor_user_id, control_receipts=self.control_receipts,
            )

        summary = self.execution.run_unit(
            "collect", write, inputs={"source": identity, "manifest_ref": reference, "contract": node["output_contract"]},
            replay_safe=True,
        )
        manifest, access = authorize_workflow_node_result_read(
            self.workflow, self.run_id, summary["producer"], summary["result_ref"],
            reader_user_id=self.actor_user_id, load_result=self.execution.load_result,
        )
        if access["source_snapshot_changed"]:
            self.execution.pause_input("A collected source changed. The saved records were retained.", code="workflow_loop_source_changed")
        validation = manifest["workflow_validation"]
        state = "completed" if validation["eligible"] else validation["status"]
        self.partial |= validation["status"] == "accepted_partial"
        self.failed |= not validation["eligible"]
        self._remember(node["id"], {"state": state, "summary": summary, "structured_validated": bool(node["output_contract"].get("schema"))})
        self.execution.finish_node(
            state=state, attempt=summary["producer"]["attempt"], workflow_result=summary, workflow_validation=validation,
            structured_validated=bool(node["output_contract"].get("schema")),
        )

    def _region(self, region):
        children = region["nodes"]
        index = 0
        while index < len(children):
            node = children[index]
            self.execution.set_node(node, region["id"])
            self.execution.check()
            if node["kind"] == "for_each":
                yield from self._for_each(node, region["id"])
            elif node["kind"] == "collect":
                self._collect(node, region["id"])
            elif node["kind"] == "task":
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
                current_id = self.execution.execution_id()
                checkpoint = next((
                    item for item in reversed(self.task_results) if item["task"]["id"] == task["id"] and (
                        not self.execution.iteration_path or
                        (((item.get("result") or {}).get("workflow_result") or {}).get("producer") or {}).get("execution_id") == current_id
                        or item.get("execution_id") == current_id
                    )
                ), None)
                if checkpoint is None:
                    raise WorkflowInputError("A selected task did not save an execution outcome.")
                result = checkpoint.get("result") or {}
                summary = result.get("workflow_result")
                state = checkpoint["status"]
                if summary:
                    self._remember(node["id"], {
                        "state": state, "summary": summary,
                        "structured_validated": bool((task.get("output_contract") or {}).get("schema")),
                    })
                    self.execution.finish_node(
                        state=state, workflow_result=summary, workflow_validation=result.get("workflow_validation"),
                        consumed_inputs=checkpoint.get("consumed_inputs") or [],
                    )
                    self.partial |= (result.get("workflow_validation") or {}).get("status") == "accepted_partial"
                else:
                    self._remember(node["id"], {"state": "failed"})
                    self.execution.finish_node(state="failed", attempt=max(1, checkpoint.get("attempt_count", 1)), reason_code="task_failed")
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
                self._remember(node["id"], {"state": "completed", "summary": summary, "structured_validated": True})
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
        try:
            yield from self._region(self.compiled["flow"])
            self.final_outputs = self.resolve(self.compiled["flow"]["outputs"], metadata_only=self.has_loops)["bound_inputs"]
        except WorkflowResultNotReadyError as exc:
            if self.has_loops:
                self.execution.pause_input(str(exc), code="workflow_input_unavailable")
            raise
        self.execution._update(self.execution.check(), {"progress": {
            "completed": len(self.completed), "total": len(self.compiled["nodes"]),
        }})
        self.finished = True
