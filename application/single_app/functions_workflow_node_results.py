# functions_workflow_node_results.py
"""Exact node result readers, including control provenance and paged lineage."""

import json
from collections import OrderedDict
from collections.abc import Mapping
from copy import deepcopy

from functions_analysis_access import AnalysisResultUnavailable, analysis_source_snapshot, authorize_analysis_sources
from functions_workflow_bindings import WorkflowInputError
from functions_workflow_identity import canonical_digest, workflow_node_identity
from functions_workflow_limits import WORKFLOW_MAX_EXECUTION_ADMISSIONS
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


class WorkflowLineageAuthorization:
    """One bounded iterative graph for results, mixed paths and temporal state proofs."""

    def __init__(self, workflow, run_id, *, reader_user_id=None, load_result=load_workflow_node_result,
                 source_resolver=None, include_sources=True, source_callback=None, store=None):
        self.workflow, self.run_id = workflow, run_id
        self.reader_user_id = reader_user_id or workflow["user_id"]
        self.load_result, self.source_resolver = load_result, source_resolver
        self.include_sources, self.source_callback = include_sources, source_callback
        self._store = store
        self._compiled = None
        self.loaded = OrderedDict()
        self.active, self.visited = set(), set()
        self.sources, self.source_ids, self.source_batch = {}, set(), []
        self.changed = False
        self._recording = None
        self._proof_cache = None
        # Reuse immutable graph structure only within this active worker request;
        # source, document and publication authority is never cached.
        from functions_workflow_execution import current_workflow_execution

        execution = current_workflow_execution()
        if execution and execution.run_id == run_id and execution.workflow == workflow:
            self._proof_cache = getattr(execution, "lineage_proof_cache", None)

    @property
    def store(self):
        if self._store is None:
            from functions_workflow_execution import current_workflow_execution
            from functions_workflow_iterations import workflow_runtime_store

            current = current_workflow_execution()
            self._store = (
                current.store if current and current.workflow["id"] == self.workflow["id"] and current.run_id == self.run_id
                else workflow_runtime_store(self.workflow, self.run_id)
            )
        return self._store

    @property
    def compiled(self):
        if self._compiled is None:
            from functions_workflow_flow import compile_workflow_flow

            self._compiled = compile_workflow_flow(self.workflow)
        return self._compiled

    def load(self, identity, reference):
        key = (canonical_digest(identity), canonical_digest(reference))
        if key not in self.loaded:
            self.loaded[key] = load_node_result(
                self.workflow, self.run_id, identity, reference, load_result=self.load_result,
            )
            if len(self.loaded) > 32:
                self.loaded.popitem(last=False)
        self.loaded.move_to_end(key)
        return self.loaded[key]

    def _flush_sources(self):
        if not self.source_batch:
            return
        checked = authorize_analysis_sources(self.reader_user_id, self.source_batch, resolver=self.source_resolver)
        self.changed |= checked["source_snapshot_changed"]
        if self.source_callback is not None:
            for source in self.source_batch:
                self.source_callback(source)
        self.source_batch.clear()

    def source_seen(self, source):
        source = analysis_source_snapshot([source])[0]
        if self._recording is not None:
            self._recording["sources"].append(source)
        digest = canonical_digest(source)
        if digest in self.source_ids:
            return
        self.source_ids.add(digest)
        if self.include_sources:
            self.sources[digest] = source
        self.source_batch.append(source)
        if len(self.source_batch) >= 100:
            self._flush_sources()

    def _document_access(self, item):
        from functions_workflow_iterations import _authorize_frozen_document

        _authorize_frozen_document(self.workflow, item, self.reader_user_id)
        if self._recording is not None:
            self._recording["documents"].append(item)

    def _publication_access(self, publication):
        from functions_artifact_publication import authorize_publication_status_read

        authorize_publication_status_read(
            self.reader_user_id, publication, actor_user_id=self.store.read()["actor_user_id"],
        )
        if self._recording is not None:
            self._recording["publications"].append(publication)

    def _cached_children(self, key, proof):
        cache = self._proof_cache
        cached = cache["entries"].get(key) if cache is not None else None
        if cached is not None:
            cache["entries"].move_to_end(key)
            entry, _ = cached
            for source in entry["sources"]:
                self.source_seen(source)
            for item in entry["documents"]:
                self._document_access(item)
            for publication in entry["publications"]:
                self._publication_access(publication)
            yield from entry["dependencies"]
            return
        entry = {"dependencies": [], "sources": [], "documents": [], "publications": []}
        children = iter(self._children(proof))
        while True:
            self._recording = entry if cache is not None else None
            try:
                child = next(children, None)
            finally:
                self._recording = None
            if child is None:
                break
            if cache is not None:
                entry["dependencies"].append(child)
            yield child
        if cache is not None:
            size = len(json.dumps(entry, ensure_ascii=True).encode("ascii"))
            if size <= 1024 * 1024:
                cache["entries"][key] = (entry, size)
                cache["bytes"] += size
                while cache["bytes"] > 32 * 1024 * 1024 or len(cache["entries"]) > 32768:
                    _, (_, removed_size) = cache["entries"].popitem(last=False)
                    cache["bytes"] -= removed_size

    def access(self):
        self._flush_sources()
        return {
            "source_count": len(self.source_ids), "source_snapshot_changed": self.changed,
            "sources": list(self.sources.values()) if self.include_sources else None,
        }

    def walk(self, roots):
        if self._proof_cache is not None:
            self.store.read()
        pending = [(None, iter(roots))]
        while pending:
            key, children = pending[-1]
            proof = next(children, None)
            if proof is None:
                if key is not None:
                    self.active.remove(key)
                    self.visited.add(key)
                pending.pop()
                continue
            child_key = canonical_digest(proof)
            if child_key in self.active or len(self.visited) + len(self.active) >= 100000:
                raise AnalysisResultUnavailable("analysis_lineage_invalid")
            if child_key in self.visited:
                continue
            self.active.add(child_key)
            pending.append((child_key, iter(self._cached_children(child_key, proof))))
        self._flush_sources()

    def _children(self, proof):
        kind, *arguments = proof
        if kind == "result":
            identity, reference = arguments
            current = self.load(identity, reference)
            expected = workflow_node_identity(
                self.workflow, self.run_id, identity.get("node_id"), identity.get("execution_id"), identity.get("attempt"),
                task_id=identity.get("task_id"), iteration_path=identity.get("iteration_path"),
            )
            if (
                identity != expected or not isinstance(current, Mapping)
                or current.get("contract_version") != "workflow-result-v2" or current.get("identity") != expected
            ):
                raise AnalysisResultUnavailable("analysis_lineage_invalid")
            if current.get("publication"):
                self._publication_access(current["publication"])
            if identity["iteration_path"]:
                yield ("path", identity, current.get("iteration_inputs") or [])
            if current.get("frozen_loop"):
                yield ("frozen", current["frozen_loop"])
            if current.get("repeat_state_proof"):
                binding = current["repeat_state_proof"]
                if binding.get("producer") != identity:
                    raise AnalysisResultUnavailable("workflow_repeat_identity_invalid")
                yield ("state", identity, binding["state_ref"])
            access = current.get("analysis_access")
            if access is not None:
                if not isinstance(access, Mapping) or access.get("version") != "analysis-source-access-v1":
                    raise AnalysisResultUnavailable("analysis_lineage_invalid")
                direct = analysis_source_snapshot(access.get("sources"))
                if not direct:
                    raise AnalysisResultUnavailable("analysis_source_manifest_missing")
                for source in direct:
                    self.source_seen(source)
            selected = set()
            for descriptor in (current.get("outputs") or {}).values():
                if not isinstance(descriptor, Mapping):
                    raise AnalysisResultUnavailable("analysis_lineage_invalid")
                if descriptor.get("selected_producer"):
                    receipt = descriptor["selected_producer"]
                    if not isinstance(receipt, Mapping) or receipt.get("output_ref") != descriptor.get("result_ref"):
                        raise AnalysisResultUnavailable("analysis_lineage_invalid")
                    selected.add(canonical_digest(receipt))
            for receipt in iter_consumed_inputs(current, lambda section: self.load(identity, section)):
                selected.discard(canonical_digest(receipt))
                yield ("receipt", receipt)
            if selected:
                raise AnalysisResultUnavailable("analysis_lineage_invalid")
        elif kind == "receipt":
            receipt = arguments[0]
            producer, reference = receipt.get("producer"), receipt.get("result_ref")
            if not isinstance(producer, dict) or not isinstance(reference, dict):
                raise AnalysisResultUnavailable("analysis_lineage_invalid")
            parent = self.load(producer, reference)
            output = (parent.get("outputs") or {}).get(receipt.get("output_name")) or {}
            if output.get("result_ref") != receipt.get("output_ref"):
                raise AnalysisResultUnavailable("analysis_lineage_invalid")
            if receipt.get("repeat_state"):
                from functions_workflow_repeat_state import load_repeat_admission, load_repeat_state

                binding = receipt["repeat_state"]
                row = self.store.journal_read("loop", binding.get("loop_execution_id"))
                identity = ((row or {}).get("payload") or {}).get("identity")
                if not identity or identity["node_id"] != binding.get("loop_id"):
                    raise AnalysisResultUnavailable("workflow_repeat_source_invalid")
                admission, expected = load_repeat_admission(
                    self.workflow, self.run_id, identity, binding.get("iteration"), store=self.store,
                )
                if binding != {**expected, "state_name": binding.get("state_name")}:
                    raise AnalysisResultUnavailable("workflow_repeat_source_invalid")
                state, _ = load_repeat_state(
                    self.workflow, self.run_id, identity, admission["before_state_ref"],
                    store=self.store, load_result=self.load_result, compiled=self.compiled,
                )
                slot = (state["slots"].get(binding.get("state_name")) or {}).get("receipt") or {}
                if any(receipt.get(name) != slot.get(name) for name in ("producer", "result_ref", "output_name", "output_ref")):
                    raise AnalysisResultUnavailable("workflow_repeat_source_invalid")
                yield ("admission", identity, binding["iteration"])
            yield ("result", producer, reference)
        elif kind == "state":
            from functions_workflow_repeat_state import load_repeat_state

            identity, reference = arguments
            state, _ = load_repeat_state(
                self.workflow, self.run_id, identity, reference,
                store=self.store, load_result=self.load_result, compiled=self.compiled,
            )
            if identity["iteration_path"]:
                yield ("path", identity, state.get("iteration_inputs") or [])
            if state["state_index"]:
                yield ("admission", identity, state["state_index"] - 1)
            for slot in state["slots"].values():
                yield ("receipt", slot["receipt"])
            for receipt in state["body_outputs"].values():
                yield ("receipt", receipt)
            for receipt in state.get("consumed_inputs") or []:
                yield ("receipt", receipt)
        elif kind == "admission":
            from functions_workflow_repeat_state import load_repeat_admission

            identity, iteration = arguments
            admission, _ = load_repeat_admission(self.workflow, self.run_id, identity, iteration, store=self.store)
            yield ("state", identity, admission["before_state_ref"])
        elif kind == "path":
            from functions_workflow_iterations import iteration_path_proofs

            identity, receipts = arguments
            _, dependencies = iteration_path_proofs(
                self.workflow, self.run_id, identity, receipts=receipts, store=self.store, load_result=self.load_result,
            )
            yield from dependencies
        elif kind in {"frozen", "frozen_item"}:
            from functions_workflow_iterations import (
                load_frozen_loop, read_frozen_item,
            )

            binding = arguments[0]
            if not isinstance(binding, dict) or not isinstance(binding.get("producer"), dict):
                raise AnalysisResultUnavailable("workflow_loop_identity_invalid")
            identity = binding["producer"]
            manifest, reference, _ = load_frozen_loop(
                self.workflow, self.run_id, identity, store=self.store, load_result=self.load_result,
            )
            if reference != binding.get("manifest_ref"):
                raise AnalysisResultUnavailable("workflow_loop_manifest_invalid")
            if identity["iteration_path"]:
                yield ("path", identity, manifest.get("iteration_inputs") or [])
            for receipt in manifest.get("consumed_inputs") or []:
                yield ("receipt", receipt)
            if manifest.get("source_receipt"):
                yield ("receipt", manifest["source_receipt"])
            indices = [arguments[1]] if kind == "frozen_item" else (
                range(manifest["count"]) if manifest["selection"]["kind"] != "input" else []
            )
            for index in indices:
                item = read_frozen_item(self.workflow, self.run_id, manifest, index, load_result=self.load_result)
                if kind == "frozen_item" and item["item_id"] != arguments[2]:
                    raise AnalysisResultUnavailable("workflow_loop_item_invalid")
                if item["kind"] == "document":
                    self._document_access(item)
                    self.source_seen(item["source"])
                elif kind == "frozen_item":
                    receipt = manifest["source_receipt"]
                    producer, current, name = self._selected_output(receipt)
                    from functions_workflow_results import read_result_records

                    rows, _ = read_result_records(
                        current, name, lambda ref: self.load(producer, ref), offset=item["source_ordinal"], limit=1,
                    )
                    if len(rows) != 1 or canonical_digest(rows[0]) != item["record_sha256"]:
                        raise AnalysisResultUnavailable("workflow_loop_item_changed")
        else:
            raise AnalysisResultUnavailable("analysis_lineage_invalid")

    def _selected_output(self, receipt):
        seen = set()
        while True:
            key = canonical_digest(receipt)
            if key in seen or len(seen) >= WORKFLOW_MAX_EXECUTION_ADMISSIONS:
                raise AnalysisResultUnavailable("analysis_lineage_invalid")
            seen.add(key)
            identity = receipt["producer"]
            manifest = self.load(identity, receipt["result_ref"])
            descriptor = manifest["outputs"].get(receipt["output_name"]) or {}
            if descriptor.get("result_ref") != receipt.get("output_ref"):
                raise AnalysisResultUnavailable("analysis_lineage_invalid")
            selected = descriptor.get("selected_producer")
            if not selected:
                return identity, manifest, receipt["output_name"]
            receipt = selected

    def authorize_result(self, identity, reference, *, manifest=None):
        if manifest is not None:
            if self._proof_cache is not None:
                key = canonical_digest(("result", identity, reference))
                removed = self._proof_cache["entries"].pop(key, None)
                if removed is not None:
                    self._proof_cache["bytes"] -= removed[1]
            self.loaded[(canonical_digest(identity), canonical_digest(reference))] = manifest
        self.walk([("result", identity, reference)])
        return self.load(identity, reference)

    def authorize_repeat(self, identity, reference):
        from functions_workflow_repeat_state import load_repeat_state

        self.walk([("state", identity, reference)])
        return load_repeat_state(
            self.workflow, self.run_id, identity, reference,
            store=self.store, load_result=self.load_result, compiled=self.compiled,
        )[0]


def authorize_workflow_node_result_read(
    workflow, run_id, identity, reference, *, reader_user_id=None, manifest=None,
    load_result=load_workflow_node_result, source_resolver=None, include_sources=True, source_callback=None,
    authorization=None,
):
    authorization = authorization or WorkflowLineageAuthorization(
        workflow, run_id, reader_user_id=reader_user_id, load_result=load_result,
        source_resolver=source_resolver, include_sources=include_sources, source_callback=source_callback,
    )
    root = authorization.authorize_result(identity, reference, manifest=manifest)
    return root, authorization.access()


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
        self._data_identity, self._data_manifest, self._data_name = self.identity, self.manifest, self.name
        seen = set()
        while descriptor.get("selected_producer"):
            selected = descriptor["selected_producer"]
            key = canonical_digest(selected)
            if key in seen or len(seen) >= WORKFLOW_MAX_EXECUTION_ADMISSIONS:
                raise AnalysisResultUnavailable("analysis_lineage_invalid")
            seen.add(key)
            self._data_identity = selected["producer"]
            self._data_manifest = load_node_result(
                workflow, run_id, self._data_identity, selected["result_ref"], load_result=load_result,
            )
            if not inspection:
                _require_completed_result(self._data_manifest, allow_partial=allow_partial)
                if (self._data_manifest.get("workflow_validation") or {}).get("eligible") is not True:
                    raise ValueError("The selected producer did not satisfy its output requirements.")
            self._data_name = selected["output_name"]
            descriptor = (self._data_manifest.get("outputs") or {}).get(self._data_name) or {}
            if descriptor.get("result_ref") != selected.get("output_ref"):
                raise AnalysisResultUnavailable("analysis_lineage_invalid")
        self.kind = descriptor.get("kind")
        if self.kind not in {"records", "document_results"}:
            raise ValueError("The selected input must be a complete record collection.")
        if type(descriptor.get("record_count")) is int:
            self.record_count = descriptor["record_count"]
        else:
            _, self.record_count = read_result_records(
                self._data_manifest, self._data_name, self._load, offset=0, limit=1,
            )

    def _authorize(self):
        authorization = WorkflowLineageAuthorization(
            self.workflow, self.run_id, reader_user_id=self.reader_user_id,
            load_result=self.load_result, source_resolver=self.source_resolver, include_sources=False,
        )
        manifest, access = authorize_workflow_node_result_read(
            self.workflow, self.run_id, self.identity, self.reference,
            reader_user_id=self.reader_user_id, load_result=self.load_result,
            source_resolver=self.source_resolver, include_sources=False, authorization=authorization,
        )
        if getattr(self, "receipt", {}).get("repeat_state"):
            authorization.walk([("receipt", self.receipt)])
            access = authorization.access()
        if access["source_snapshot_changed"] and not self.inspection:
            raise AnalysisResultUnavailable("analysis_source_snapshot_changed")
        return manifest, access

    def _load(self, reference):
        key = canonical_digest(reference)
        if key not in self._sections:
            self._sections[key] = load_node_result(
                self.workflow, self.run_id, self._data_identity, reference, load_result=self.load_result,
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
        rows, total = read_result_records(self._data_manifest, self._data_name, self._load, offset=offset, limit=limit)
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
        records, used = [], 2
        for index in range(offset, min(self.record_count, offset + limit)):
            rows, total = read_result_records(self._data_manifest, self._data_name, self._load, offset=index, limit=1)
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
    max_bytes=None,
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
    value_receipt = receipt
    seen = set()
    while descriptor.get("selected_producer"):
        selected = descriptor["selected_producer"]
        key = canonical_digest(selected)
        if key in seen or len(seen) >= WORKFLOW_MAX_EXECUTION_ADMISSIONS:
            raise AnalysisResultUnavailable("analysis_lineage_invalid")
        seen.add(key)
        identity, reference, name = selected["producer"], selected["result_ref"], selected["output_name"]
        manifest = load_node_result(workflow, run_id, identity, reference, load_result=load_result)
        _require_completed_result(manifest, allow_partial=allow_partial)
        if (manifest.get("workflow_validation") or {}).get("eligible") is not True:
            raise ValueError("The producer's output contract is not eligible.")
        descriptor = (manifest.get("outputs") or {}).get(name) or {}
        if descriptor.get("result_ref") != selected.get("output_ref"):
            raise AnalysisResultUnavailable("analysis_lineage_invalid")
        value_receipt = {
            "producer": identity, "output_name": name, "result_ref": reference, "output_ref": descriptor["result_ref"],
        }
    if seen and receipt.get("analysis_result"):
        _, leaf_access = authorize_workflow_node_result_read(
            workflow, run_id, identity, reference, reader_user_id=reader_user_id,
            load_result=load_result, source_resolver=source_resolver, include_sources=False,
        )
        if leaf_access["source_count"]:
            value_receipt["analysis_result"] = True
    loader = lambda ref: load_node_result(workflow, run_id, identity, ref, load_result=load_result)
    if max_bytes is not None and descriptor.get("storage_kind") not in {"record_pages", "record_tree"}:
        if type(descriptor["result_ref"].get("size_bytes")) is not int or descriptor["result_ref"]["size_bytes"] > max_bytes:
            raise WorkflowInputError("This saved state is too large for a complete bounded read; its original data was retained.")
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
        "consumed_result": value_receipt, "provenance": manifest.get("provenance") or {},
        "coverage": manifest.get("coverage") or {}, "validation": manifest.get("validation") or {},
        "kind": output["kind"], "value": output["value"],
        "source_snapshot_changed": access["source_snapshot_changed"],
    }, ensure_ascii=False, allow_nan=False, sort_keys=True), receipt
