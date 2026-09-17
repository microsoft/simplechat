# functions_workflow_node_results.py
"""Exact node result readers, including control provenance and paged lineage."""

import json
from collections.abc import Mapping

from functions_analysis_access import AnalysisResultUnavailable, analysis_source_snapshot, authorize_analysis_sources
from functions_workflow_identity import canonical_digest, workflow_node_identity
from functions_workflow_result_store import load_workflow_node_result


def result_selectors(identity):
    return {key: identity[key] for key in ("node_id", "execution_id", "iteration_path", "attempt")}


def load_node_result(workflow, run_id, identity, reference, *, load_result=load_workflow_node_result):
    expected = workflow_node_identity(
        workflow, run_id, identity.get("node_id"), identity.get("execution_id"), identity.get("attempt"),
        task_id=identity.get("task_id"), iteration_path=identity.get("iteration_path"),
    )
    if expected != identity:
        raise AnalysisResultUnavailable("analysis_lineage_invalid")
    return load_result(workflow, run_id, identity.get("task_id"), reference, **result_selectors(identity))


def iter_consumed_inputs(manifest, load_section):
    from functions_workflow_results import iter_result_records

    if "consumed_inputs_index" not in manifest:
        values = manifest.get("consumed_inputs") or []
        if not isinstance(values, list):
            raise AnalysisResultUnavailable("analysis_lineage_invalid")
    else:
        synthetic = {**manifest, "outputs": {"lineage": manifest["consumed_inputs_index"]}}
        values = iter_result_records(synthetic, "lineage", load_section)
    for item in values:
        if not isinstance(item, Mapping):
            raise AnalysisResultUnavailable("analysis_lineage_invalid")
        yield item


def read_consumed_inputs(manifest, load_section):
    return list(iter_consumed_inputs(manifest, load_section))


def authorize_workflow_node_result_read(
    workflow, run_id, identity, reference, *, reader_user_id=None, manifest=None,
    load_result=load_workflow_node_result, source_resolver=None,
):
    root = manifest if manifest is not None else load_node_result(workflow, run_id, identity, reference, load_result=load_result)
    active, visited, sources = set(), set(), {}
    loaded = {}

    def enter(producer, ref, current):
        key = (canonical_digest(producer), canonical_digest(ref))
        if key in active or len(visited) + len(active) > 100000:
            raise AnalysisResultUnavailable("analysis_lineage_invalid")
        if key in visited:
            return None
        expected = workflow_node_identity(
            workflow, run_id, producer.get("node_id"), producer.get("execution_id"), producer.get("attempt"),
            task_id=producer.get("task_id"), iteration_path=producer.get("iteration_path"),
        )
        if producer != expected or not isinstance(current, Mapping) or (
            current.get("contract_version") != "workflow-result-v2" or current.get("identity") != expected
        ):
            raise AnalysisResultUnavailable("analysis_lineage_invalid")
        active.add(key)
        access = current.get("analysis_access")
        if access is not None:
            if not isinstance(access, Mapping) or access.get("version") != "analysis-source-access-v1":
                raise AnalysisResultUnavailable("analysis_lineage_invalid")
            direct = analysis_source_snapshot(access.get("sources"))
            if not direct:
                raise AnalysisResultUnavailable("analysis_source_manifest_missing")
            sources.update({canonical_digest(source): source for source in direct})
        selected = set()
        for descriptor in (current.get("outputs") or {}).values():
            if not isinstance(descriptor, Mapping):
                raise AnalysisResultUnavailable("analysis_lineage_invalid")
            if descriptor.get("selected_producer"):
                receipt = descriptor["selected_producer"]
                if not isinstance(receipt, Mapping) or receipt.get("output_ref") != descriptor.get("result_ref"):
                    raise AnalysisResultUnavailable("analysis_lineage_invalid")
                selected.add(canonical_digest(receipt))
        consumed = iter_consumed_inputs(
            current, lambda section: load_node_result(workflow, run_id, producer, section, load_result=load_result),
        )
        return key, iter(consumed), selected

    pending = [enter(identity, reference, root)]
    while pending:
        key, children, selected = pending[-1]
        item = next(children, None)
        if item is None:
            if selected:
                raise AnalysisResultUnavailable("analysis_lineage_invalid")
            active.remove(key)
            visited.add(key)
            pending.pop()
            continue
        selected.discard(canonical_digest(item))
        parent_identity, parent_ref = item.get("producer"), item.get("result_ref")
        if not isinstance(parent_identity, dict) or not isinstance(parent_ref, dict):
            raise AnalysisResultUnavailable("analysis_lineage_invalid")
        parent_key = (canonical_digest(parent_identity), canonical_digest(parent_ref))
        parent = loaded.get(parent_key)
        if parent is None:
            parent = load_node_result(workflow, run_id, parent_identity, parent_ref, load_result=load_result)
            loaded[parent_key] = parent
        output = (parent.get("outputs") or {}).get(item.get("output_name")) or {}
        if output.get("result_ref") != item.get("output_ref"):
            raise AnalysisResultUnavailable("analysis_lineage_invalid")
        child = enter(parent_identity, parent_ref, parent)
        if child is not None:
            pending.append(child)
    snapshots = analysis_source_snapshot(list(sources.values()))
    access = authorize_analysis_sources(
        reader_user_id or workflow["user_id"], snapshots, resolver=source_resolver,
    ) if snapshots else {"source_count": 0, "source_snapshot_changed": False}
    return root, {**access, "sources": snapshots}


def load_workflow_node_input(
    workflow, run_id, identity, reference, *, output_name="authoritative", allow_partial=False,
    reader_user_id=None, load_result=load_workflow_node_result, source_resolver=None, required=True,
):
    from functions_workflow_results import _require_completed_result, read_result_records

    manifest, access = authorize_workflow_node_result_read(
        workflow, run_id, identity, reference, reader_user_id=reader_user_id,
        load_result=load_result, source_resolver=source_resolver,
    )
    _require_completed_result(manifest, allow_partial=allow_partial)
    if access["source_snapshot_changed"]:
        raise AnalysisResultUnavailable("analysis_source_snapshot_changed")
    validation = manifest.get("workflow_validation") or {}
    if validation.get("eligible") is not True:
        raise ValueError("The producer's output contract is not eligible.")
    if validation.get("status") == "accepted_partial" and not allow_partial:
        raise ValueError("This input does not accept partial results.")
    name = manifest.get("authoritative_output") if output_name == "authoritative" else output_name
    descriptor = (manifest.get("outputs") or {}).get(name)
    if not isinstance(descriptor, dict):
        if required is False:
            return None, None
        raise ValueError("The exact selected output is unavailable.")
    receipt = {"producer": identity, "output_name": name, "result_ref": reference,
               "output_ref": descriptor["result_ref"]}
    if access["source_count"]:
        receipt["analysis_result"] = True
    loader = lambda ref: load_node_result(workflow, run_id, identity, ref, load_result=load_result)
    if descriptor.get("selected_producer"):
        selected = descriptor["selected_producer"]
        payload, _ = load_workflow_node_input(
            workflow, run_id, selected["producer"], selected["result_ref"],
            output_name=selected["output_name"], allow_partial=allow_partial,
            reader_user_id=reader_user_id, load_result=load_result, source_resolver=source_resolver,
        )
        return payload, receipt
    if descriptor.get("storage_kind") == "record_pages":
        value, _ = read_result_records(manifest, name, loader)
        output = {"producer": identity, "contract_version": "workflow-result-v2",
                  "output_name": name, "kind": descriptor["kind"], "value": value}
    else:
        output = loader(descriptor["result_ref"])
    if (
        output.get("producer") != identity or output.get("contract_version") != "workflow-result-v2"
        or output.get("output_name") != name or output.get("kind") != descriptor.get("kind")
    ):
        raise ValueError("Saved output section does not match its exact manifest.")
    return json.dumps({
        "consumed_result": receipt, "provenance": manifest.get("provenance") or {},
        "coverage": manifest.get("coverage") or {}, "validation": manifest.get("validation") or {},
        "kind": output["kind"], "value": output["value"],
        "source_snapshot_changed": access["source_snapshot_changed"],
    }, ensure_ascii=False, allow_nan=False, sort_keys=True), receipt
