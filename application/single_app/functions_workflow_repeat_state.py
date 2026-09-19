# functions_workflow_repeat_state.py
"""Exact, reference-only state and sealed lifetime admissions for Repeat until.

Compiler, validator, reader and logger imports are deferred at bound operations
to avoid the existing definition/runtime/result import cycles and client startup.
"""

import json
from copy import deepcopy

from functions_analysis_access import AnalysisResultUnavailable
from functions_workflow_bindings import WorkflowInputError
from functions_workflow_identity import canonical_digest, workflow_execution_id, workflow_node_identity
from functions_workflow_limits import WORKFLOW_MAX_EXECUTION_ADMISSIONS, WORKFLOW_REPEAT_ITERATIONS_MAX
from functions_workflow_result_store import load_workflow_node_result, _quota_bytes
from functions_workflow_runtime_store import WorkflowRuntimeConflict, workflow_runtime_store


REPEAT_STATE_VERSION = "workflow-repeat-state-v1"
REPEAT_SUMMARY_FIELDS = frozenset({
    "execution_id", "node_id", "completed_iteration", "next_iteration", "batch_number", "batch_size",
    "batch_usage", "completed_count", "exhaustion_count", "continuation_count", "state", "partial",
})


def repeat_summary(head):
    return {
        **{name: deepcopy(head[name]) for name in REPEAT_SUMMARY_FIELDS if name in head},
        "completed_iteration": head["completed_count"] - 1,
    }


def validate_repeat_gate_summary(value):
    if (
        not isinstance(value, dict) or set(value) != REPEAT_SUMMARY_FIELDS
        or any(not isinstance(value.get(name), str) or not value[name] for name in ("execution_id", "node_id"))
        or any(type(value.get(name)) is not int or value[name] < 0 for name in (
            "completed_iteration", "next_iteration", "batch_number", "batch_size", "batch_usage",
            "completed_count", "exhaustion_count", "continuation_count",
        ))
        or not 1 <= value["batch_size"] <= WORKFLOW_REPEAT_ITERATIONS_MAX
        or value["batch_usage"] != value["batch_size"]
        or value["next_iteration"] != value["completed_count"]
        or value["completed_iteration"] + 1 != value["next_iteration"]
        or value["state"] != "waiting_manual_continue" or type(value["partial"]) is not bool
    ):
        raise WorkflowRuntimeConflict("invalid_repeat_gate")
    return value


def _selectors(identity):
    return {name: identity[name] for name in ("node_id", "execution_id", "iteration_path", "attempt")}


def repeat_identity(workflow, run_id, node_id, parent_path):
    return workflow_node_identity(
        workflow, run_id, node_id, workflow_execution_id(workflow, run_id, node_id, parent_path),
        1, iteration_path=parent_path,
    )


def repeat_node(workflow, node_id):
    pending = list(workflow["flow"]["nodes"])
    while pending:
        node = pending.pop()
        if node["id"] == node_id and node["kind"] == "repeat_until":
            return node
        if node["kind"] in {"for_each", "repeat_until"}:
            pending.extend(node["body"]["nodes"])
        elif node["kind"] == "if":
            pending.extend(node["then"]["nodes"])
            pending.extend(node["else"]["nodes"])
    raise AnalysisResultUnavailable("workflow_repeat_identity_invalid")


def load_repeat_head(workflow, run_id, identity, *, store=None):
    store = store or workflow_runtime_store(workflow, run_id)
    if identity != repeat_identity(workflow, run_id, identity["node_id"], identity["iteration_path"]):
        raise AnalysisResultUnavailable("workflow_repeat_identity_invalid")
    node = repeat_node(workflow, identity["node_id"])
    row = store.journal_read("loop", identity["execution_id"])
    head = (row or {}).get("payload") or {}
    policy = store.read().get("repeat_policy") or {}
    if (
        head.get("kind") != "repeat_until" or head.get("identity") != identity
        or head.get("batch_size") != node["max_iterations"] or policy.get("version") != 1
        or type(policy.get("max_iterations")) is not int
        or not node["max_iterations"] <= policy["max_iterations"] <= WORKFLOW_REPEAT_ITERATIONS_MAX
        or any(type(head.get(name)) is not int or not 0 <= head[name] <= WORKFLOW_MAX_EXECUTION_ADMISSIONS for name in (
            "next_iteration", "completed_count", "batch_number", "batch_start_iteration",
            "batch_usage", "exhaustion_count", "continuation_count",
        ))
        or head["completed_count"] != head["next_iteration"]
        or head["batch_usage"] > head["batch_size"]
        or head["batch_number"] != head["continuation_count"]
        or head["batch_start_iteration"] != head["batch_number"] * head["batch_size"]
        or not head["batch_start_iteration"] <= head["next_iteration"] <= head["batch_start_iteration"] + head["batch_usage"]
        or head["batch_start_iteration"] + head["batch_usage"] - head["next_iteration"] not in {0, 1}
        or head.get("state") not in {"running", "waiting_manual_continue", "completed", "cancelled"}
        or type(head.get("partial")) is not bool
        or not isinstance(head.get("initial_state_ref"), dict) or not isinstance(head.get("current_state_ref"), dict)
    ):
        raise AnalysisResultUnavailable("workflow_repeat_head_invalid")
    return node, head, row


def repeat_iteration_receipt(identity, iteration, state_ref):
    return {
        "loop_id": identity["node_id"], "loop_execution_id": identity["execution_id"],
        "iteration": iteration, "state_ref": deepcopy(state_ref),
    }


def _transition(workflow, run_id, identity, iteration, *, store):
    row = store.journal_read("decision", ["repeat-transition", identity["execution_id"], iteration])
    value = (row or {}).get("payload") or {}
    node = repeat_node(workflow, identity["node_id"])
    expected_path = identity["iteration_path"] + [{"loop_id": identity["node_id"], "iteration": iteration}]
    batch, used = divmod(iteration, node["max_iterations"])
    if (
        value.get("decision_kind") != "repeat_transition"
        or value.get("execution_id") != identity["execution_id"] or value.get("node_id") != identity["node_id"]
        or value.get("definition_revision") != store.read()["definition_revision"]
        or value.get("iteration") != iteration or value.get("body_path") != expected_path
        or value.get("iteration_path") != identity["iteration_path"]
        or value.get("predicate_sha256") != canonical_digest(node["until"])
        or value.get("batch_number") != batch or value.get("batch_usage") != used + 1
        or value.get("batch_size") != node["max_iterations"]
        or type(value.get("condition_result")) is not bool
        or value.get("next_iteration") != iteration + 1
        or not isinstance(value.get("before_state_ref"), dict) or not isinstance(value.get("after_state_ref"), dict)
        or value.get("outcome") not in {"continue", "exhausted", "completed"}
        or (value["outcome"] == "completed") != value["condition_result"]
        or not value["condition_result"] and (value["outcome"] == "exhausted") != (used + 1 == node["max_iterations"])
    ):
        raise AnalysisResultUnavailable("workflow_repeat_transition_invalid")
    if value["outcome"] == "exhausted" and (
        value.get("gate_id") != canonical_digest(["repeat-limit", identity, iteration, value["after_state_ref"]])
        or value.get("reason_code") != "repeat_iteration_limit"
    ):
        raise AnalysisResultUnavailable("workflow_repeat_transition_invalid")
    return value


def load_repeat_admission(workflow, run_id, identity, iteration, *, store=None):
    store = store or workflow_runtime_store(workflow, run_id)
    node, head, _ = load_repeat_head(workflow, run_id, identity, store=store)
    if type(iteration) is not int or not 0 <= iteration < store.read()["max_executions"]:
        raise AnalysisResultUnavailable("workflow_repeat_iteration_invalid")
    row = store.journal_read("admission", ["repeat-iteration", identity["execution_id"], iteration])
    admission = (row or {}).get("payload") or {}
    batch, usage = divmod(iteration, node["max_iterations"])
    path = identity["iteration_path"] + [{"loop_id": identity["node_id"], "iteration": iteration}]
    if (
        admission.get("execution_id") != identity["execution_id"] or admission.get("node_id") != node["id"]
        or admission.get("iteration") != iteration or admission.get("iteration_path") != path
        or admission.get("definition_revision") != store.read()["definition_revision"]
        or admission.get("batch_number") != batch or admission.get("batch_usage") != usage + 1
        or admission.get("batch_size") != node["max_iterations"]
        or admission.get("batch_start_iteration") != batch * node["max_iterations"]
        or batch > head["batch_number"] or iteration > head["next_iteration"]
        or not isinstance(admission.get("before_state_ref"), dict)
    ):
        raise AnalysisResultUnavailable("workflow_repeat_admission_invalid")
    if iteration == 0:
        expected_ref = head["initial_state_ref"]
    else:
        previous = _transition(workflow, run_id, identity, iteration - 1, store=store)
        if previous["condition_result"] or previous["outcome"] == "exhausted" and usage != 0:
            raise AnalysisResultUnavailable("workflow_repeat_admission_invalid")
        expected_ref = previous["after_state_ref"]
    if admission["before_state_ref"] != expected_ref:
        raise AnalysisResultUnavailable("workflow_repeat_state_changed")
    if batch:
        gate_id = admission.get("grant_gate_id")
        decision = store.journal_read("decision", ["gate", gate_id]) if gate_id else None
        grant = (decision or {}).get("payload") or {}
        exhausted = _transition(workflow, run_id, identity, batch * node["max_iterations"] - 1, store=store)
        if (
            grant.get("choice") != "continue_repeat" or grant.get("gate_id") != gate_id
            or grant.get("execution_id") != identity["execution_id"]
            or grant.get("definition_revision") != admission["definition_revision"]
            or grant.get("input_digest") != canonical_digest(exhausted)
            or (grant.get("repeat") or {}).get("batch_number") != batch - 1
            or exhausted["outcome"] != "exhausted"
            or exhausted.get("gate_id") != gate_id
        ):
            raise AnalysisResultUnavailable("workflow_repeat_grant_invalid")
    elif admission.get("grant_gate_id") is not None:
        raise AnalysisResultUnavailable("workflow_repeat_grant_invalid")
    outcome = store.journal_read("iteration", [identity["execution_id"], iteration])
    if outcome is None or any(outcome["payload"].get(name) != value for name, value in admission.items()):
        raise AnalysisResultUnavailable("workflow_repeat_iteration_invalid")
    return admission, repeat_iteration_receipt(identity, iteration, expected_ref)


def _plain_receipt(receipt):
    return {name: deepcopy(value) for name, value in receipt.items() if name not in {"input_name", "control"}}


def _check_source(workflow, run_id, source, receipt, path, *, compiled, store, load_result):
    producer = receipt.get("producer") or {}
    if source["kind"] == "repeat_state":
        binding = receipt.get("repeat_state") or {}
        frame_index = next((index for index, frame in enumerate(path) if frame["loop_id"] == source["loop_id"]), None)
        if (
            frame_index is None or "iteration" not in path[frame_index]
            or binding.get("loop_id") != source["loop_id"] or binding.get("state_name") != source["state_name"]
            or binding.get("iteration") != path[frame_index]["iteration"]
        ):
            raise AnalysisResultUnavailable("workflow_repeat_source_invalid")
        enclosing = repeat_identity(workflow, run_id, source["loop_id"], path[:frame_index])
        if binding.get("loop_execution_id") != enclosing["execution_id"]:
            raise AnalysisResultUnavailable("workflow_repeat_source_invalid")
        admission, _ = load_repeat_admission(workflow, run_id, enclosing, binding["iteration"], store=store)
        if binding.get("state_ref") != admission["before_state_ref"]:
            raise AnalysisResultUnavailable("workflow_repeat_state_changed")
        return
    ancestors = compiled["node_loop_ids"][source["node_id"]]
    expected_path = path[:len(ancestors)]
    if (
        [frame["loop_id"] for frame in expected_path] != ancestors
        or producer.get("node_id") != source["node_id"] or producer.get("iteration_path") != expected_path
        or producer.get("execution_id") != workflow_execution_id(workflow, run_id, source["node_id"], expected_path)
    ):
        raise AnalysisResultUnavailable("workflow_repeat_source_invalid")
    committed = store.journal_read("attempt", [producer["execution_id"], producer.get("attempt")])
    summary = ((committed or {}).get("payload") or {}).get("workflow_result") or {}
    name = summary.get("authoritative_output") if source["output"] == "authoritative" else source["output"]
    if (
        summary.get("producer") != producer or summary.get("result_ref") != receipt.get("result_ref")
        or receipt.get("output_name") != name
        or (summary.get("outputs", {}).get(name) or {}).get("result_ref") != receipt.get("output_ref")
    ):
        raise AnalysisResultUnavailable("workflow_repeat_source_uncommitted")


def load_repeat_state(workflow, run_id, identity, reference, *, store=None,
                      load_result=load_workflow_node_result, compiled=None):
    # Compiler imports definition normalization; defer it until a bound read.
    from functions_workflow_flow import compile_workflow_flow

    store = store or workflow_runtime_store(workflow, run_id)
    compiled = compiled or compile_workflow_flow(workflow)
    node, head, _ = load_repeat_head(workflow, run_id, identity, store=store)
    state = load_result(workflow, run_id, None, reference, **_selectors(identity))
    index = state.get("state_index")
    slots = state.get("slots")
    if (
        state.get("contract_version") != REPEAT_STATE_VERSION or state.get("identity") != identity
        or type(index) is not int or not 0 <= index <= head["next_iteration"]
        or not isinstance(slots, dict) or set(slots) != {slot["name"] for slot in node["state"]}
        or type(state.get("partial")) is not bool
    ):
        raise AnalysisResultUnavailable("workflow_repeat_state_invalid")
    transition = None
    if index == 0:
        if reference != head["initial_state_ref"] or state.get("previous_state_ref") is not None:
            raise AnalysisResultUnavailable("workflow_repeat_state_uncommitted")
        path = identity["iteration_path"]
    else:
        transition = _transition(workflow, run_id, identity, index - 1, store=store)
        if reference != transition["after_state_ref"] or state.get("previous_state_ref") != transition["before_state_ref"]:
            raise AnalysisResultUnavailable("workflow_repeat_state_uncommitted")
        admission, _ = load_repeat_admission(workflow, run_id, identity, index - 1, store=store)
        if transition["before_state_ref"] != admission["before_state_ref"]:
            raise AnalysisResultUnavailable("workflow_repeat_transition_invalid")
        path = admission["iteration_path"]
        outputs = state.get("body_outputs")
        declared = {binding["name"]: binding for binding in node["body"]["outputs"]}
        if (
            not isinstance(outputs, dict) or set(outputs) - set(declared)
            or transition.get("body_outputs_sha256") != canonical_digest(outputs)
        ):
            raise AnalysisResultUnavailable("workflow_repeat_state_invalid")
        for name, binding in declared.items():
            if name not in outputs:
                if binding["required"]:
                    raise AnalysisResultUnavailable("workflow_repeat_state_invalid")
                continue
            _check_source(workflow, run_id, binding["source"], outputs[name], path,
                          compiled=compiled, store=store, load_result=load_result)
    for declaration in node["state"]:
        saved = slots[declaration["name"]]
        validation = saved.get("workflow_validation") or {}
        if (
            saved.get("kind") != declaration["output_contract"]["kind"]
            or saved.get("contract_sha256") != canonical_digest(declaration["output_contract"])
            or not isinstance(saved.get("receipt"), dict)
            or validation.get("version") != 1 or validation.get("eligible") is not True
            or validation.get("status") not in {"valid", "accepted_partial"}
            or validation["status"] == "accepted_partial" and not declaration["output_contract"]["allow_partial"]
        ):
            raise AnalysisResultUnavailable("workflow_repeat_state_invalid")
        if index == 0:
            _check_source(workflow, run_id, declaration["initial"], saved["receipt"], path,
                          compiled=compiled, store=store, load_result=load_result)
        elif saved["receipt"] != state["body_outputs"].get(declaration["next"]):
            raise AnalysisResultUnavailable("workflow_repeat_state_invalid")
    if any(slot["workflow_validation"]["status"] == "accepted_partial" for slot in slots.values()) and not state["partial"]:
        raise AnalysisResultUnavailable("workflow_repeat_state_invalid")
    return state, transition


def current_repeat_state(workflow, run_id, path, source, *, reader_user_id, store,
                         load_result=load_workflow_node_result):
    from functions_workflow_node_results import WorkflowLineageAuthorization

    position = next((index for index, frame in enumerate(path) if frame["loop_id"] == source["loop_id"]), None)
    if position is None or "iteration" not in path[position]:
        raise WorkflowInputError("Current Repeat state is outside its admitted body.")
    identity = repeat_identity(workflow, run_id, source["loop_id"], path[:position])
    iteration = path[position]["iteration"]
    admission, _ = load_repeat_admission(workflow, run_id, identity, iteration, store=store)
    authorization = WorkflowLineageAuthorization(
        workflow, run_id, reader_user_id=reader_user_id, load_result=load_result, store=store,
    )
    state = authorization.authorize_repeat(identity, admission["before_state_ref"])
    if authorization.access()["source_snapshot_changed"]:
        raise AnalysisResultUnavailable("analysis_source_snapshot_changed")
    slot = state["slots"].get(source["state_name"])
    if slot is None:
        raise WorkflowInputError("The requested Repeat state slot is not declared.")
    receipt = {
        **_plain_receipt(slot["receipt"]),
        "repeat_state": {
            **repeat_iteration_receipt(identity, iteration, admission["before_state_ref"]),
            "state_name": source["state_name"],
        },
    }
    return slot, receipt


def validate_repeat_source_receipt(workflow, run_id, source, receipt, path, *, store,
                                   load_result=load_workflow_node_result):
    position = next((index for index, frame in enumerate(path) if frame["loop_id"] == source["loop_id"]), None)
    if position is None or "iteration" not in path[position]:
        raise AnalysisResultUnavailable("workflow_repeat_source_invalid")
    identity = repeat_identity(workflow, run_id, source["loop_id"], path[:position])
    admission, expected = load_repeat_admission(workflow, run_id, identity, path[position]["iteration"], store=store)
    state, _ = load_repeat_state(
        workflow, run_id, identity, admission["before_state_ref"], store=store, load_result=load_result,
    )
    selected = (state["slots"].get(source["state_name"]) or {}).get("receipt") or {}
    if (
        receipt.get("repeat_state") != {**expected, "state_name": source["state_name"]}
        or any(receipt.get(name) != selected.get(name) for name in ("producer", "result_ref", "output_name", "output_ref"))
    ):
        raise AnalysisResultUnavailable("workflow_repeat_source_invalid")


def prepare_repeat_state(flow, node, identity, *, previous=None, previous_ref=None, outputs=None, consumed_inputs=None):
    from functions_workflow_collect import _CollectionContract
    from functions_workflow_collections import (
        COLLECTION_MATERIALIZATION_BYTES, CollectionWriteBudget, RecordIdentityValidator,
    )
    from functions_workflow_node_results import (
        authorize_workflow_node_result_read, load_node_result, load_workflow_node_input, open_workflow_record_input,
    )
    from functions_workflow_results import _encoded_result_size, _require_completed_result
    from functions_workflow_validation import validate_workflow_task_output, workflow_coverage_status

    execution = flow.execution
    slots = {}
    outputs = outputs or {}
    maximum = _quota_bytes(execution.settings)
    budget = CollectionWriteBudget(maximum)

    def save(value):
        execution.check()
        return execution.save_result(
            flow.workflow, flow.run_id, None, value, settings=execution.settings, **_selectors(identity),
        )

    for declaration in node["state"]:
        contract = declaration["output_contract"]
        if previous is None:
            resolved = flow.resolve([{
                "name": declaration["name"], "source": declaration["initial"], "required": True,
                "expected_kind": contract["kind"], "allow_partial": contract["allow_partial"],
            }], metadata_only=True)
            receipt = _plain_receipt(resolved["bound_inputs"][0])
        else:
            receipt = deepcopy(outputs.get(declaration["next"]))
            if receipt is None:
                raise WorkflowInputError("A required next-state output did not finish.")
        manifest, access = authorize_workflow_node_result_read(
            flow.workflow, flow.run_id, receipt["producer"], receipt["result_ref"],
            reader_user_id=flow.actor_user_id, load_result=execution.load_result,
        )
        _require_completed_result(manifest, allow_partial=contract["allow_partial"])
        if access["source_snapshot_changed"]:
            raise AnalysisResultUnavailable("analysis_source_snapshot_changed")
        descriptor = manifest["outputs"].get(receipt["output_name"]) or {}
        if descriptor.get("result_ref") != receipt["output_ref"] or descriptor.get("kind") != contract["kind"]:
            raise WorkflowInputError("Repeat state must preserve its exact declared output kind.")
        coverage = deepcopy(manifest.get("coverage") or {})
        inherited = (previous or {}).get("slots", {}).get(declaration["name"], {})
        producer_partial = (manifest.get("workflow_validation") or {}).get("status") == "accepted_partial"
        inherited_partial = (inherited.get("workflow_validation") or {}).get("status") == "accepted_partial"
        if contract["kind"] in {"records", "document_results"}:
            reader = open_workflow_record_input(
                flow.workflow, flow.run_id, receipt["producer"], receipt["result_ref"],
                output_name=receipt["output_name"], reader_user_id=flow.actor_user_id,
                allow_partial=contract["allow_partial"], load_result=execution.load_result,
            )
            validator = _CollectionContract(contract)
            identities = None
            if contract.get("identity_field"):
                identities = RecordIdentityValidator(
                    contract["identity_field"], identity, save,
                    lambda ref: execution.load_result(flow.workflow, flow.run_id, None, ref, **_selectors(identity)),
                    max_result_bytes=maximum, budget=budget, contract_version=REPEAT_STATE_VERSION,
                    output_name=f"state:{declaration['name']}:identity",
                )
            for record in reader.iter_records():
                execution.check()
                validator.add(record)
                if identities is not None:
                    identities.add(record)
            incomplete = ["producer_coverage_incomplete"] if producer_partial or inherited_partial else []
            if contract["require_complete_coverage"] and workflow_coverage_status(coverage) != "complete":
                incomplete.append(f"coverage_{workflow_coverage_status(coverage)}")
            validation = validator.finish(
                invalid=[], incomplete=incomplete, identities=identities.finish() if identities else None,
            )
        else:
            payload, _ = load_workflow_node_input(
                flow.workflow, flow.run_id, receipt["producer"], receipt["result_ref"],
                output_name=receipt["output_name"], reader_user_id=flow.actor_user_id,
                allow_partial=contract["allow_partial"], load_result=execution.load_result,
                max_bytes=COLLECTION_MATERIALIZATION_BYTES,
            )
            output = json.loads(payload)
            validation = validate_workflow_task_output({
                **manifest, "authoritative_output": "state",
                "outputs": {"state": {"kind": output["kind"], "value": output["value"]}},
                "validation": {"status": "accepted_partial"} if producer_partial or inherited_partial else manifest.get("validation", {}),
            }, contract)
        if validation["eligible"] is not True:
            raise WorkflowInputError("Repeat state did not satisfy its declared output contract; the original output was retained.")
        limitations = list(dict.fromkeys([
            *(inherited.get("limitations") or []), *(validation.get("reason_codes") or []),
            *((manifest.get("workflow_validation") or {}).get("reason_codes") or []),
        ]))
        slots[declaration["name"]] = {
            "kind": contract["kind"], "contract_sha256": canonical_digest(contract), "receipt": receipt,
            "workflow_validation": validation, "coverage": coverage, "limitations": limitations,
            **({"prior_coverage": inherited.get("prior_coverage") or inherited.get("coverage") or {}}
               if inherited_partial else {}),
        }
    outputs_partial = any(
        (load_node_result(
            flow.workflow, flow.run_id, receipt["producer"], receipt["result_ref"], load_result=execution.load_result,
        ).get("workflow_validation") or {}).get("status") == "accepted_partial"
        for receipt in outputs.values()
    )
    state = {
        "contract_version": REPEAT_STATE_VERSION, "identity": deepcopy(identity),
        "state_index": 0 if previous is None else previous["state_index"] + 1,
        "slots": slots, "previous_state_ref": deepcopy(previous_ref), "body_outputs": deepcopy(outputs),
        "consumed_inputs": deepcopy(flow.control_receipts if consumed_inputs is None else consumed_inputs),
        "iteration_inputs": deepcopy(execution.iteration_inputs[:len(identity["iteration_path"])]),
        "partial": bool((previous or {}).get("partial")) or outputs_partial or any(
            slot["workflow_validation"]["status"] == "accepted_partial" for slot in slots.values()
        ),
    }
    budget.consume(_encoded_result_size(state))
    return state, save(state)


def prepare_repeat_grant(store, control, gate, *, actor_user_id):
    from functions_workflow_node_results import WorkflowLineageAuthorization

    if gate.get("reason_code") != "repeat_iteration_limit" or gate.get("choices") != ["continue_repeat", "cancel"]:
        raise WorkflowRuntimeConflict("invalid_repeat_gate")
    validate_repeat_gate_summary(gate.get("repeat"))
    workflow = store.run_definition()
    identity = repeat_identity(workflow, store.identity["run_id"], gate["node_id"], gate["iteration_path"])
    _, head, row = load_repeat_head(workflow, store.identity["run_id"], identity, store=store)
    transition = _transition(workflow, store.identity["run_id"], identity, head["next_iteration"] - 1, store=store)
    if (
        control["state"] != "paused" or head["state"] != "waiting_manual_continue"
        or gate.get("execution_id") != identity["execution_id"] or gate.get("attempt") != 1
        or gate.get("definition_revision") != control["definition_revision"]
        or gate["repeat"] != repeat_summary(head) or gate.get("input_digest") != canonical_digest(transition)
        or transition.get("gate_id") != gate["id"] or transition["outcome"] != "exhausted"
        or head["current_state_ref"] != transition["after_state_ref"]
        or head["batch_usage"] != head["batch_size"]
    ):
        raise WorkflowRuntimeConflict("repeat_gate_changed")
    for reader in dict.fromkeys([actor_user_id, control["actor_user_id"]]):
        authorization = WorkflowLineageAuthorization(
            workflow, store.identity["run_id"], reader_user_id=reader, store=store,
        )
        authorization.authorize_repeat(identity, head["current_state_ref"])
        if authorization.access()["source_snapshot_changed"]:
            raise AnalysisResultUnavailable("analysis_source_snapshot_changed")
    return row, {
        **head, "state": "running", "batch_number": head["batch_number"] + 1,
        "batch_start_iteration": head["next_iteration"], "batch_usage": 0,
        "continuation_count": head["continuation_count"] + 1, "grant_gate_id": gate["id"],
    }


def log_repeat_event(store, decision):
    # Logging initialization depends on application configuration; use the existing
    # logger only after an authoritative journal decision has committed.
    from functions_appinsights import log_event

    event = "workflow_repeat_manually_continued" if decision.get("choice") == "continue_repeat" else "workflow_repeat_batch_exhausted"
    log_event(
        f"[WORKFLOW_SCHEDULER] {event}",
        extra={
            "event_name": event, "event_id": decision["event_id"],
            **{name: value for name, value in store.identity.items() if name in {"workflow_id", "run_id", "scope_type", "scope_id"}},
            **{name: decision[name] for name in ("execution_id", "node_id", "gate_id", "request_id", "actor_user_id", "decided_at") if name in decision},
            **{name: value for name, value in (decision.get("repeat") or {}).items()
               if name in {"batch_number", "batch_size", "completed_count", "exhaustion_count", "continuation_count"}},
        },
    )
