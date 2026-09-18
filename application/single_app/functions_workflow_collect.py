# functions_workflow_collect.py
"""Exact, model-free collection of declared per-item output receipts."""

from copy import deepcopy

from jsonschema import Draft202012Validator

from functions_analysis_access import AnalysisResultUnavailable
from functions_workflow_identity import workflow_node_identity
from functions_workflow_iterations import read_frozen_item
from functions_workflow_node_results import open_workflow_record_input, result_selectors
from functions_workflow_result_store import _quota_bytes
from functions_workflow_results import _encoded_result_size, workflow_result_summary


class _CollectionContract:
    def __init__(self, contract):
        self.contract = contract
        self.count = 0
        self.schema_errors = 0
        self.schema = contract.get("schema") or {}
        self.item_validator = Draft202012Validator(self.schema.get("items", {}))
        self.enum_candidates = [
            value for value in self.schema.get("enum", []) if isinstance(value, list)
        ] if "enum" in self.schema else None

    def add(self, record):
        if self.schema_errors < 100:
            self.schema_errors += min(
                100 - self.schema_errors, sum(1 for _ in self.item_validator.iter_errors(record)),
            )
        if self.enum_candidates is not None:
            self.enum_candidates = [
                value for value in self.enum_candidates
                if self.count < len(value) and Draft202012Validator({"enum": [value[self.count]]}).is_valid(record)
            ]
        self.count += 1

    def finish(self, *, invalid, incomplete, identities=None):
        reasons = list(invalid)
        missing = list(incomplete)
        counts = {"actual_count": self.count}
        root_type = self.schema.get("type")
        if root_type is not None and "array" not in ([root_type] if isinstance(root_type, str) else root_type):
            self.schema_errors += 1
        if self.count < self.schema.get("minItems", 0) or self.count > self.schema.get("maxItems", self.count):
            self.schema_errors += 1
        if self.enum_candidates is not None and not any(len(value) == self.count for value in self.enum_candidates):
            self.schema_errors += 1
        if self.schema_errors:
            reasons.append("output_schema_mismatch")
            counts["schema_errors"] = min(100, self.schema_errors)
        expected = self.contract.get("expected_count")
        if expected is not None:
            counts["expected_count"] = expected
            if self.count < expected:
                missing.append("missing_output_items")
            elif self.count > expected:
                reasons.append("unexpected_output_items")
        if identities:
            counts.update(identities)
            if identities.get("missing_identity_count"):
                reasons.append("missing_output_identity")
            if identities.get("duplicate_identity_count"):
                reasons.append("duplicate_output_identity")
        status = "invalid" if reasons else (
            "accepted_partial" if self.contract.get("allow_partial") else "incomplete"
        ) if missing else "valid"
        return {
            "version": 1, "status": status, "eligible": status in {"valid", "accepted_partial"},
            "reason_codes": list(dict.fromkeys(reasons + missing)), "counts": counts,
        }


def collect_workflow_loop(execution, node, loop_node, frozen, frozen_ref, loop_state, *, actor_user_id,
                          control_receipts=()):
    from functions_workflow_collections import CollectionWriteBudget, RecordTreeWriter, RecordIdentityValidator

    if loop_state.get("state") != "completed" or loop_state.get("next_index") != frozen["count"]:
        raise ValueError("Collect requires the complete traversal of its frozen loop.")
    export = next(
        (binding for binding in loop_node["body"]["outputs"] if binding["name"] == node["source"]["output"]), None,
    )
    if export is None:
        raise ValueError("The collected body output is not declared.")
    attempt = int(execution.unit("collect").get("attempt") or 1)
    selectors = execution.selectors(attempt=attempt)
    identity = workflow_node_identity(
        execution.workflow, execution.run_id, node["id"], selectors["execution_id"],
        attempt, iteration_path=selectors["iteration_path"],
    )
    maximum = _quota_bytes(execution.settings)
    budget = CollectionWriteBudget(maximum)

    def save(section):
        execution.check()
        return execution.save_result(
            execution.workflow, execution.run_id, None, section, settings=execution.settings, **selectors,
        )

    def load(reference):
        return execution.load_result(
            execution.workflow, execution.run_id, None, reference, **selectors,
        )

    kind = node["output_contract"]["kind"]
    output_name = "documents" if kind == "document_results" else "records"
    records = RecordTreeWriter(identity, output_name, kind, save, max_result_bytes=maximum, budget=budget)
    lineage = RecordTreeWriter(identity, "lineage", "records", save, max_result_bytes=maximum, budget=budget)
    contributors = RecordTreeWriter(identity, "contributors", "records", save, max_result_bytes=maximum, budget=budget)
    coverage_pages = RecordTreeWriter(identity, "item_coverage", "records", save, max_result_bytes=maximum, budget=budget)
    validator = _CollectionContract(node["output_contract"])
    identity_validator = (
        RecordIdentityValidator(
            node["output_contract"]["identity_field"], records, load,
        ) if node["output_contract"].get("identity_field") else None
    )
    counts = {"expected_count": frozen["count"], "processed_count": 0, "empty_count": 0,
              "skipped_count": 0, "failed_count": 0, "partial_count": 0}
    invalid, incomplete = [], []
    for receipt in control_receipts:
        lineage.append(receipt)
    for index in range(frozen["count"]):
        execution.check()
        item = read_frozen_item(
            execution.workflow, execution.run_id, frozen, index, load_result=execution.load_result,
        )
        row = execution.store.journal_read("iteration", [frozen["identity"]["execution_id"], item["item_id"]])
        outcome = (row or {}).get("payload") or {}
        if outcome.get("index") != index or outcome.get("item_sha256") != item["item_sha256"]:
            raise AnalysisResultUnavailable("workflow_iteration_outcome_invalid")
        coverage = {"item_id": item["item_id"], "index": index, "state": outcome.get("state")}
        if outcome.get("state") not in {"completed", "skipped"}:
            counts["failed_count"] += 1
            invalid.append("failed_loop_item")
            coverage_pages.append(coverage)
            continue
        exports = execution.load_result(
            execution.workflow, execution.run_id, None, outcome["exports_ref"], **result_selectors(frozen["identity"]),
        )
        if (
            exports.get("version") != "workflow-loop-exports-v1"
            or exports.get("loop_execution_id") != frozen["identity"]["execution_id"]
            or exports.get("item_id") != item["item_id"] or exports.get("index") != index
        ):
            raise AnalysisResultUnavailable("workflow_iteration_outcome_invalid")
        receipt = exports["exports"].get(export["name"])
        if receipt is None:
            counts["skipped_count"] += 1
            (invalid if export["required"] else incomplete).append(
                "missing_required_body_output" if export["required"] else "optional_body_output_skipped",
            )
            coverage_pages.append({**coverage, "state": "skipped"})
            continue
        producer = receipt.get("producer") or {}
        expected_path = frozen["identity"]["iteration_path"] + [{
            "loop_id": loop_node["id"], "item_id": item["item_id"], "index": index,
        }]
        if producer.get("iteration_path") != expected_path or producer.get("node_id") != export["source"]["node_id"]:
            raise AnalysisResultUnavailable("workflow_body_export_scope_invalid")
        reader = open_workflow_record_input(
            execution.workflow, execution.run_id, producer, receipt["result_ref"],
            output_name=receipt["output_name"], reader_user_id=actor_user_id,
            allow_partial=export["allow_partial"] and node["output_contract"]["allow_partial"],
            load_result=execution.load_result,
        )
        if reader.kind != kind or reader.receipt["output_ref"] != receipt["output_ref"]:
            raise AnalysisResultUnavailable("workflow_body_export_invalid")
        start = validator.count
        for record in reader.iter_records():
            records.append(record)
            validator.add(record)
            if identity_validator is not None:
                identity_validator.add(record)
        reader.recheck()
        length = validator.count - start
        lineage.append(receipt)
        contributors.append({
            **receipt, "item_id": item["item_id"], "item_index": index,
            "record_offset": start, "record_count": length, "producer_record_offset": 0,
        })
        partial = (reader.manifest.get("workflow_validation") or {}).get("status") == "accepted_partial"
        if partial:
            counts["partial_count"] += 1
            incomplete.append("producer_coverage_incomplete")
        counts["processed_count"] += 1
        counts["empty_count"] += int(length == 0)
        coverage_pages.append({
            **coverage, "state": "completed_partial" if partial else "completed_empty" if not length else "completed",
            "record_count": length,
        })
    validation = validator.finish(
        invalid=invalid, incomplete=incomplete,
        identities=identity_validator.finish() if identity_validator is not None else None,
    )
    coverage = {
        **counts, "record_count": validator.count,
        "status": "completed" if validation["status"] == "valid" else "incomplete",
    }
    manifest = {
        "contract_version": "workflow-result-v2", "identity": identity,
        "execution": {"status": "succeeded" if validation["eligible"] else validation["status"]},
        "authoritative_output": output_name, "outputs": {output_name: records.finish()},
        "consumed_inputs_index": lineage.finish(), "contributors_index": contributors.finish(),
        "item_coverage_index": coverage_pages.finish(),
        "coverage": coverage, "workflow_validation": validation,
        "validation": {"status": "partial" if validation["status"] == "accepted_partial" else validation["status"]},
        "record_count": validator.count, "analysis_origin": False,
        "iteration_inputs": deepcopy(execution.iteration_inputs),
        "frozen_loop": {"producer": frozen["identity"], "manifest_ref": frozen_ref},
    }
    if identity_validator is not None:
        manifest["record_identity_index"] = identity_validator.index_descriptor
    budget.consume(_encoded_result_size(manifest))
    reference = save(manifest)
    return workflow_result_summary(manifest, reference)
