# functions_workflow_node_results.py
"""Exact node result readers, including control provenance and paged lineage."""

import json
from collections import OrderedDict
from collections.abc import Mapping
from copy import deepcopy

from functions_analysis_access import AnalysisResultUnavailable, analysis_source_snapshot, authorize_analysis_sources
from functions_workflow_identity import canonical_digest, workflow_node_identity
from functions_workflow_result_store import load_workflow_node_result


class WorkflowRecordPageTooLarge(ValueError):
    def __init__(self, offset):
        self.code = "workflow_record_inspection_limit"
        self.record_offset = offset
        self.public_message = (
            "This complete record exceeds the inline inspection limit. Its full data is retained unchanged; "
            "no shortened record was returned."
        )
        super().__init__(self.public_message)


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
    load_result=load_workflow_node_result, source_resolver=None, include_sources=True, source_callback=None,
):
    root = manifest if manifest is not None else load_node_result(workflow, run_id, identity, reference, load_result=load_result)
    active, visited, sources = set(), set(), {}
    loaded = OrderedDict()
    source_ids, source_batch = set(), []
    changed = False

    def flush_sources():
        nonlocal changed
        if not source_batch:
            return
        checked = authorize_analysis_sources(
            reader_user_id or workflow["user_id"], source_batch, resolver=source_resolver,
        )
        changed |= checked["source_snapshot_changed"]
        if source_callback is not None:
            for source in source_batch:
                source_callback(source)
        source_batch.clear()

    def source_seen(source):
        source = analysis_source_snapshot([source])[0]
        digest = canonical_digest(source)
        if digest in source_ids:
            return
        source_ids.add(digest)
        if include_sources:
            sources[digest] = source
        source_batch.append(source)
        if len(source_batch) >= 100:
            flush_sources()

    def enter(producer, ref, current):
        nonlocal changed
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
        if current.get("publication"):
            # Result readers own source lineage; publication owns the additional destination boundary.
            from functions_artifact_publication import authorize_publication_status_read
            from functions_workflow_runtime_store import workflow_runtime_store

            actor = workflow_runtime_store(workflow, run_id).read()["actor_user_id"]
            authorize_publication_status_read(
                reader_user_id or workflow["user_id"], current["publication"], actor_user_id=actor,
            )
        if producer["iteration_path"]:
            from functions_workflow_iterations import authorize_iteration_path

            authorize_iteration_path(
                workflow, run_id, producer, reader_user_id=reader_user_id or workflow["user_id"],
                receipts=current.get("iteration_inputs") or [],
                load_result=load_result, source_resolver=source_resolver,
            )
        if current.get("frozen_loop"):
            from functions_workflow_iterations import authorize_frozen_loop

            frozen_access = authorize_frozen_loop(
                workflow, run_id, current["frozen_loop"],
                reader_user_id=reader_user_id or workflow["user_id"],
                load_result=load_result, source_resolver=source_resolver, source_callback=source_seen,
            )
            changed |= frozen_access["source_snapshot_changed"]
        active.add(key)
        access = current.get("analysis_access")
        if access is not None:
            if not isinstance(access, Mapping) or access.get("version") != "analysis-source-access-v1":
                raise AnalysisResultUnavailable("analysis_lineage_invalid")
            direct = analysis_source_snapshot(access.get("sources"))
            if not direct:
                raise AnalysisResultUnavailable("analysis_source_manifest_missing")
            for source in direct:
                source_seen(source)
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
            if len(loaded) > 8:
                loaded.popitem(last=False)
        output = (parent.get("outputs") or {}).get(item.get("output_name")) or {}
        if output.get("result_ref") != item.get("output_ref"):
            raise AnalysisResultUnavailable("analysis_lineage_invalid")
        child = enter(parent_identity, parent_ref, parent)
        if child is not None:
            pending.append(child)
    flush_sources()
    return root, {
        "source_count": len(source_ids), "source_snapshot_changed": changed,
        "sources": list(sources.values()) if include_sources else None,
    }


class AuthorizedWorkflowRecordInput:
    """A source-authorized immutable record range, not a preview or access token."""

    def __init__(self, workflow, run_id, identity, reference, *, output_name="authoritative",
                 reader_user_id=None, allow_partial=False, load_result=load_workflow_node_result,
                 source_resolver=None, inspection=False):
        from functions_workflow_results import _require_completed_result, read_result_records

        if not isinstance(identity, dict) or not isinstance(reference, dict):
            raise AnalysisResultUnavailable("analysis_lineage_invalid")
        self.workflow = workflow
        self.run_id = run_id
        self.identity = deepcopy(identity)
        self.reference = deepcopy(reference)
        self.reader_user_id = reader_user_id or workflow["user_id"]
        self.allow_partial = allow_partial
        self.inspection = inspection
        self.load_result = load_result
        self.source_resolver = source_resolver
        self._sections = OrderedDict()
        self.manifest, self.access = self._authorize()
        if not inspection:
            _require_completed_result(self.manifest, allow_partial=allow_partial)
            validation = self.manifest.get("workflow_validation") or {}
            if validation.get("eligible") is not True:
                raise ValueError("The selected producer did not satisfy its output requirements.")
            if validation.get("status") == "accepted_partial" and not allow_partial:
                raise ValueError("The selected input does not accept partial results.")
        self.name = self.manifest.get("authoritative_output") if output_name == "authoritative" else output_name
        descriptor = (self.manifest.get("outputs") or {}).get(self.name)
        if not isinstance(descriptor, dict):
            raise ValueError("The exact selected collection is unavailable.")
        self.receipt = {
            "producer": deepcopy(identity), "output_name": self.name,
            "result_ref": deepcopy(reference), "output_ref": deepcopy(descriptor["result_ref"]),
        }
        if self.access["source_count"]:
            self.receipt["analysis_result"] = True
        self._selected = None
        if descriptor.get("selected_producer"):
            selected = descriptor["selected_producer"]
            self._selected = AuthorizedWorkflowRecordInput(
                workflow, run_id, selected["producer"], selected["result_ref"],
                output_name=selected["output_name"], reader_user_id=self.reader_user_id,
                allow_partial=allow_partial, load_result=load_result,
                source_resolver=source_resolver, inspection=inspection,
            )
            self.kind = self._selected.kind
            self.record_count = self._selected.record_count
        else:
            self.kind = descriptor.get("kind")
            if self.kind not in {"records", "document_results"}:
                raise ValueError("The selected input must be a complete record collection.")
            if type(descriptor.get("record_count")) is int:
                self.record_count = descriptor["record_count"]
            else:
                _, self.record_count = read_result_records(self.manifest, self.name, self._load, offset=0, limit=1)

    def _authorize(self):
        manifest, access = authorize_workflow_node_result_read(
            self.workflow, self.run_id, self.identity, self.reference,
            reader_user_id=self.reader_user_id, load_result=self.load_result,
            source_resolver=self.source_resolver, include_sources=False,
        )
        if access["source_snapshot_changed"] and not self.inspection:
            raise AnalysisResultUnavailable("analysis_source_snapshot_changed")
        return manifest, access

    def _load(self, reference):
        key = canonical_digest(reference)
        if key not in self._sections:
            self._sections[key] = load_node_result(
                self.workflow, self.run_id, self.identity, reference, load_result=self.load_result,
            )
            if len(self._sections) > 4:
                self._sections.popitem(last=False)
        self._sections.move_to_end(key)
        return self._sections[key]

    def recheck(self):
        _, self.access = self._authorize()
        return self.access

    def read_records(self, *, offset=0, limit=100):
        from functions_workflow_results import read_result_records

        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Complete record pages support between 1 and 100 records.")
        self.recheck()
        if self._selected is not None:
            return self._selected.read_records(offset=offset, limit=limit)
        rows, total = read_result_records(self.manifest, self.name, self._load, offset=offset, limit=limit)
        if total != self.record_count:
            raise ValueError("The complete record count changed.")
        return rows, total

    def iter_records(self):
        offset = 0
        while True:
            records, total = self.read_records(offset=offset, limit=100)
            yield from records
            offset += len(records)
            if offset >= total:
                break
            if not records:
                raise ValueError("The selected collection has an unreadable gap.")

    def record_page(self, *, offset=0, limit=100, max_bytes=240 * 1024):
        from functions_workflow_results import read_result_records

        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Invalid complete-record page.")
        self.recheck()
        if self._selected is not None:
            return self._selected.record_page(offset=offset, limit=limit, max_bytes=max_bytes)
        records, used = [], 2
        for index in range(offset, min(self.record_count, offset + limit)):
            rows, total = read_result_records(self.manifest, self.name, self._load, offset=index, limit=1)
            if len(rows) != 1 or total != self.record_count:
                raise ValueError("The complete record page is invalid.")
            size = len(json.dumps(rows[0], ensure_ascii=True, allow_nan=False).encode("ascii")) + 1
            if used + size > max_bytes:
                if not records:
                    raise WorkflowRecordPageTooLarge(index)
                break
            records.append(rows[0])
            used += size
        if offset > self.record_count:
            raise ValueError("The record cursor exceeds the result.")
        return records, self.record_count


def open_workflow_record_input(workflow, run_id, identity, reference, **options):
    return AuthorizedWorkflowRecordInput(workflow, run_id, identity, reference, **options)


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
    if descriptor.get("storage_kind") in {"record_pages", "record_tree"}:
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
