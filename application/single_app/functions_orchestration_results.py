# functions_orchestration_results.py
"""Authorized retained results for future orchestration adapters, not a new runtime.

Owners inject initialized storage and current access readers. No renderer, route,
settings owner, model, artifact publisher, or global result catalog is imported.
"""

import hashlib
import json
from collections.abc import Iterable
from copy import deepcopy
from dataclasses import dataclass

from functions_analysis_access import analysis_source_snapshot
from functions_orchestration_result_contracts import (
    EXTERNAL_LINEAGE_VERSION,
    MAX_EXTERNAL_SOURCES,
    MAX_DESCRIPTOR_BYTES,
    MAX_OUTPUTS,
    RESULT_KINDS,
    RESULT_MANIFEST_VERSION,
    RESULT_STATES,
    TASK_RESULT_VERSION,
    Completeness,
    ExternalSourceRef,
    InputSpec,
    ProducerIdentity,
    RecordColumn,
    ResultContractError,
    ResultRef,
    TaskResult,
    canonical_bytes,
    choice,
    digest,
    identifier,
    integer,
    output_name,
    validate_columns,
    validate_json,
    validate_record,
    validate_result_role,
)
from functions_orchestration_source_access import authorize_orchestration_sources
from functions_workflow_collections import (
    CollectionWriteBudget,
    RecordTreeWriter,
    iter_record_tree,
)
from functions_workflow_results import read_result_records


MAX_VALUE_BYTES = 8 * 1024 * 1024
MAX_PREVIEW_BYTES = 16 * 1024
MAX_PREVIEW_ITEMS = 20
MAX_UPSTREAM_RESULTS = 64
MAX_LINEAGE_RESULTS = 256
_COLLECTION_KINDS = frozenset({"records-v1", "evidence-set-v1", "source-set-v1"})
_TEXT_KINDS = frozenset({"text-v1", "markdown-v1"})
_MANIFEST_FIELDS = frozenset({"version", "producer", "role", "status", "lineage", "outputs"})
_OUTPUT_FIELDS = frozenset({
    "kind", "columns", "completeness", "content_sha256", "size_bytes", "item_count", "character_count", "storage",
})
_LINEAGE_FIELDS = frozenset({"origin", "source_policy", "sources", "upstream", "allow_partial_inputs"})


class ResultUnavailableError(PermissionError):
    def __init__(self, code="result_unavailable"):
        self.code = code
        super().__init__("This retained result is unavailable under the current access or producer state.")


@dataclass(frozen=True)
class NamedOutput:
    name: str
    kind: str
    value: object
    completeness: Completeness
    columns: tuple[RecordColumn, ...] = ()

    def __post_init__(self):
        output_name(self.name)
        choice(self.kind, RESULT_KINDS)
        if type(self.completeness) is not Completeness or self.completeness.preview:
            raise ResultContractError("result_preview_not_authoritative")
        validate_columns(self.columns, self.kind)


class OrchestrationResultAccess:
    """Server-owned owner/run readers and authorized, screening-aware source I/O.

    ``read_conversation(conversation_id)`` and ``read_run(run_id)`` return current
    server records, not request payloads. ``source_resolver(ids, **scope)`` has the
    existing resolve_authorized_source_manifest protocol. ``source_metadata_reader``
    has content_screening.access's metadata_reader protocol and must enforce the
    current actor's document/workspace access. Source-free results need neither
    source callback. Original-owner, same-conversation reuse is the v1 scope.
    """

    def __init__(
        self, *, user_id, conversation_id, read_conversation, read_run,
        source_resolver=None, source_metadata_reader=None,
        external_source_catalog=None, external_source_authorizer=None,
    ):
        self.user_id = identifier(user_id)
        self.conversation_id = identifier(conversation_id)
        if not callable(read_conversation) or not callable(read_run):
            raise ResultContractError("result_access_reader_required")
        for callback in (source_resolver, source_metadata_reader, external_source_authorizer):
            if callback is not None and not callable(callback):
                raise ResultContractError("result_access_reader_required")
        self.read_conversation = read_conversation
        self.read_run = read_run
        self.source_resolver = source_resolver
        self.source_metadata_reader = source_metadata_reader
        catalog = {} if external_source_catalog is None else external_source_catalog
        if type(catalog) is not dict or len(catalog) > MAX_EXTERNAL_SOURCES:
            raise ResultContractError("result_external_catalog_invalid")
        for alias, reference in catalog.items():
            output_name(alias)
            if type(reference) is not ExternalSourceRef:
                raise ResultContractError("result_external_reference_untrusted")
        self.external_source_catalog = dict(catalog)
        self.external_source_authorizer = external_source_authorizer

    def authorize_producer(self, producer, *, for_write=False):
        if (
            type(producer) is not ProducerIdentity or producer.user_id != self.user_id
            or producer.conversation_id != self.conversation_id
        ):
            raise ResultUnavailableError("result_owner_mismatch")
        conversation = self.read_conversation(self.conversation_id)
        if (
            type(conversation) is not dict or conversation.get("id") != self.conversation_id
            or conversation.get("user_id") != self.user_id or conversation.get("orchestration_deleted")
        ):
            raise ResultUnavailableError("result_conversation_unavailable")
        run = self.read_run(producer.run_id)
        if (
            type(run) is not dict or run.get("id") != producer.run_id
            or run.get("user_id") != self.user_id or run.get("conversation_id") != self.conversation_id
            or run.get("checkpoints_deleted")
        ):
            raise ResultUnavailableError("result_producer_unavailable")
        # Historical v1 runs predate the explicit index; their original attempt is 1.
        attempt = run.get("attempt_index", 1)
        if type(attempt) is not int or attempt != producer.attempt_index:
            raise ResultUnavailableError("result_attempt_mismatch")
        plan = run.get("plan")
        steps = plan.get("steps") if type(plan) is dict else None
        if type(steps) is not list or any(type(step) is not dict for step in steps):
            raise ResultUnavailableError("result_producer_unavailable")
        matching = [step for step in steps if step.get("step_id") == producer.step_id]
        if (
            len(matching) != 1 or matching[0].get("enabled", True) is not True
            or matching[0].get("capability_id") != producer.capability_id
        ):
            raise ResultUnavailableError("result_producer_unavailable")
        if for_write and (
            run.get("status") != "running" or run.get("cancellation_requested_at")
            or run.get("latest_attempt_run_id")
        ):
            raise ResultUnavailableError("result_attempt_stopped")

    def authorize_sources(self, sources, *, require_snapshot):
        if not sources:
            return {"source_count": 0, "source_snapshot_changed": False}
        if self.source_resolver is None or self.source_metadata_reader is None:
            raise ResultUnavailableError("result_source_reader_required")
        originals = {_source_key(source): source for source in sources}
        digest_changed = False

        def resolve(document_ids, **scope):
            nonlocal digest_changed
            fresh = self.source_resolver(document_ids, **scope)
            if type(fresh) is list:
                for source in fresh:
                    if type(source) is not dict or not {"document_id", "scope", "scope_id"}.issubset(source):
                        continue
                    original = originals.get(_source_key(source)) or {}
                    expected = original.get("content_sha256")
                    if expected is not None and source.get("content_sha256") != expected:
                        digest_changed = True
                        if require_snapshot:
                            raise ResultUnavailableError("result_source_snapshot_changed")
            return fresh

        checked = authorize_orchestration_sources(
            self.user_id, sources, require_snapshot=require_snapshot, resolver=resolve,
            metadata_reader=self.source_metadata_reader,
        )
        return {**checked, "source_snapshot_changed": checked["source_snapshot_changed"] or digest_changed}

    def admit_external_sources(self, aliases):
        if type(aliases) not in (list, tuple) or len(aliases) > MAX_EXTERNAL_SOURCES:
            raise ResultContractError("result_external_catalog_invalid")
        bindings = []
        for alias in aliases:
            output_name(alias)
            reference = self.external_source_catalog.get(alias)
            if type(reference) is not ExternalSourceRef:
                raise ResultContractError("result_external_reference_untrusted")
            bindings.append({"alias": alias, "reference": reference.to_dict()})
        _external_bindings(bindings)
        return bindings

    def authorize_external_sources(self, producer, bindings, *, require_snapshot):
        references = _external_bindings(bindings)
        if references and self.external_source_authorizer is None:
            raise ResultUnavailableError("result_external_authorizer_required")
        changed = False
        for reference in references:
            current = self.external_source_authorizer(
                reference, producer=producer, user_id=self.user_id, conversation_id=self.conversation_id,
            )
            if type(current) is not ExternalSourceRef or current.identity() != reference.identity():
                raise ResultUnavailableError("result_external_source_unavailable")
            snapshot_changed = any(
                getattr(reference, field) is not None and getattr(current, field) != getattr(reference, field)
                for field in ("content_sha256", "source_revision")
            )
            if snapshot_changed and require_snapshot:
                raise ResultUnavailableError("result_external_snapshot_changed")
            changed = changed or snapshot_changed
        return changed, set(references)


def _producer_arguments(producer):
    return (producer.user_id, producer.conversation_id, producer.run_id, producer.step_id)


def _source_key(source):
    return source["document_id"], source["scope"], source["scope_id"]


def _sources(value):
    snapshots = analysis_source_snapshot(value)
    if snapshots != value:
        raise ResultContractError("result_source_snapshot_invalid")
    keys = [_source_key(source) for source in snapshots]
    if len(set(keys)) != len(keys):
        raise ResultContractError("result_source_snapshot_invalid")
    return snapshots


def _external_bindings(value):
    if type(value) is not list or len(value) > MAX_EXTERNAL_SOURCES:
        raise ResultContractError("result_external_catalog_invalid")
    aliases, identities, references = set(), set(), []
    for binding in value:
        if type(binding) is not dict or set(binding) != {"alias", "reference"}:
            raise ResultContractError("result_external_catalog_invalid")
        alias = output_name(binding["alias"])
        reference = ExternalSourceRef.from_dict(binding["reference"])
        if alias in aliases or reference.identity() in identities:
            raise ResultContractError("result_external_duplicate_binding")
        aliases.add(alias)
        identities.add(reference.identity())
        references.append(reference)
    return tuple(references)


def _lineage(value):
    if type(value) is not dict:
        raise ResultContractError("result_lineage_invalid")
    expected_fields = _LINEAGE_FIELDS
    external = ()
    if value.get("version") == EXTERNAL_LINEAGE_VERSION:
        expected_fields = expected_fields | {"version", "external_sources"}
        external = _external_bindings(value.get("external_sources"))
        if not external:
            raise ResultContractError("result_lineage_invalid")
    if set(value) != expected_fields:
        raise ResultContractError("result_lineage_invalid")
    choice(value["origin"], {"generated", "grounded"})
    choice(value["source_policy"], {"current", "snapshot"})
    _sources(value["sources"])
    if type(value["allow_partial_inputs"]) is not bool:
        raise ResultContractError("result_lineage_invalid")
    parents = value["upstream"]
    if type(parents) is not list or len(parents) > MAX_UPSTREAM_RESULTS:
        raise ResultContractError("result_lineage_invalid")
    references = tuple(ResultRef.from_dict(item) for item in parents)
    if len(set(references)) != len(references):
        raise ResultContractError("result_lineage_invalid")
    if (value["origin"] == "generated") != (not value["sources"] and not references and not external):
        raise ResultContractError("result_lineage_invalid")
    if len(canonical_bytes(value)) > MAX_DESCRIPTOR_BYTES:
        raise ResultContractError("result_descriptor_too_large")
    return references


def _reference(producer, name, output, manifest_sha256):
    if type(output) is not dict or set(output) != _OUTPUT_FIELDS or type(output["columns"]) is not list:
        raise ResultContractError("result_manifest_invalid")
    reference = ResultRef(
        producer=producer, output_name=name, kind=output["kind"], manifest_sha256=manifest_sha256,
        content_sha256=output["content_sha256"], size_bytes=output["size_bytes"],
        item_count=output["item_count"], completeness=Completeness.from_dict(output["completeness"]),
        columns=tuple(RecordColumn.from_dict(item) for item in output["columns"]),
        character_count=output["character_count"],
    )
    storage = output["storage"]
    if (
        type(storage) is not dict or set(storage) != {"kind", "storage_kind", "result_ref", "record_count"}
        or storage["kind"] != "records" or storage["storage_kind"] != "record_tree"
    ):
        raise ResultContractError("result_manifest_invalid")
    integer(storage["record_count"])
    if reference.kind in _COLLECTION_KINDS and storage["record_count"] != reference.item_count:
        raise ResultContractError("result_count_invalid")
    if reference.kind in _TEXT_KINDS | {"structured-v1"} and reference.item_count != 1:
        raise ResultContractError("result_count_invalid")
    if reference.kind == "comparison-v1" and reference.size_bytes > MAX_VALUE_BYTES:
        raise ResultContractError("result_comparison_too_large")
    return reference


def _task_result(manifest, manifest_sha256):
    if type(manifest) is not dict:
        raise ResultContractError("result_manifest_invalid")
    version = manifest.get("version")
    expected_fields = _MANIFEST_FIELDS
    if version == RESULT_MANIFEST_VERSION:
        expected_fields = expected_fields | {"input_fingerprint", "output_order"}
        if manifest.get("input_fingerprint") is not None:
            digest(manifest["input_fingerprint"])
    elif version != TASK_RESULT_VERSION:
        raise ResultContractError("result_manifest_invalid")
    if set(manifest) != expected_fields:
        raise ResultContractError("result_manifest_invalid")
    if len(canonical_bytes(manifest)) > MAX_DESCRIPTOR_BYTES:
        raise ResultContractError("result_descriptor_too_large")
    producer = ProducerIdentity.from_dict(manifest["producer"])
    _lineage(manifest["lineage"])
    if version == TASK_RESULT_VERSION and "version" in manifest["lineage"]:
        raise ResultContractError("result_manifest_invalid")
    outputs = manifest["outputs"]
    if type(outputs) is not dict or not 1 <= len(outputs) <= MAX_OUTPUTS:
        raise ResultContractError("result_manifest_invalid")
    order = list(outputs)
    if version == RESULT_MANIFEST_VERSION:
        order = manifest["output_order"]
        if (
            type(order) is not list or any(type(name) is not str for name in order)
            or len(order) != len(outputs) or set(order) != set(outputs)
        ):
            raise ResultContractError("result_manifest_invalid")
    return TaskResult(
        producer, manifest["role"], manifest["status"],
        tuple(_reference(producer, name, outputs[name], manifest_sha256) for name in order),
    )


def _collection_manifest(producer, name, storage):
    return {"contract_version": TASK_RESULT_VERSION, "identity": producer.to_dict(), "outputs": {name: storage}}


def _validate_item(kind, item, columns, source_snapshots):
    validate_json(item)
    if kind == "records-v1":
        validate_record(item, columns)
    elif kind == "source-set-v1":
        _sources([item])
        if canonical_bytes(item) not in source_snapshots.get(_source_key(item), ()):
            raise ResultContractError("result_source_not_in_lineage")
    elif kind == "evidence-set-v1":
        if type(item) is not dict or set(item) != {"evidence_id", "source", "text"}:
            raise ResultContractError("result_evidence_invalid")
        identifier(item["evidence_id"])
        if type(item["text"]) is not str:
            raise ResultContractError("result_evidence_invalid")
        _sources([item["source"]])
        if canonical_bytes(item["source"]) not in source_snapshots.get(_source_key(item["source"]), ()):
            raise ResultContractError("result_source_not_in_lineage")


def _validate_value(kind, value, completeness, source_snapshots):
    validate_json(value)
    if kind in _TEXT_KINDS:
        if type(value) is not str:
            raise ResultContractError("result_value_invalid")
        count = 1
    elif kind == "comparison-v1":
        expected_fields = {"left_document_id", "right_document_ids", "items", "failed_document_ids"}
        if type(value) is not dict or set(value) != expected_fields:
            raise ResultContractError("result_comparison_invalid")
        identifier(value["left_document_id"])
        for name in ("right_document_ids", "failed_document_ids", "items"):
            if type(value[name]) is not list:
                raise ResultContractError("result_comparison_invalid")
        targets = value["right_document_ids"]
        failed = value["failed_document_ids"]
        for document_id in targets + failed:
            identifier(document_id)
        completed = []
        for item in value["items"]:
            if type(item) is not dict or set(item) != {"right_document_id", "right_document_name", "text"}:
                raise ResultContractError("result_comparison_invalid")
            identifier(item["right_document_id"])
            identifier(item["right_document_name"])
            identifier(item["text"], limit=MAX_VALUE_BYTES)
            completed.append(item["right_document_id"])
        if (
            not targets or value["left_document_id"] in targets or len(set(targets)) != len(targets)
            or len(set(failed + completed)) != len(failed + completed) or set(failed + completed) != set(targets)
            or not set([value["left_document_id"], *targets]).issubset({key[0] for key in source_snapshots})
            or completeness.expected_count != len(targets)
            or (completeness.status == "complete" and failed)
        ):
            raise ResultContractError("result_comparison_incomplete")
        count = len(completed)
    else:
        count = 1
    if completeness.actual_count != count:
        raise ResultContractError("result_count_invalid")
    return count


class OrchestrationResults:
    """A small facade over an injected WorkflowResultStore, with no client factory."""

    def __init__(self, store, access, *, max_result_bytes=None):
        if type(access) is not OrchestrationResultAccess:
            raise ResultContractError("result_access_reader_required")
        self.store = store
        self.access = access
        self.max_result_bytes = store.max_size_bytes if max_result_bytes is None else max_result_bytes
        integer(self.max_result_bytes, minimum=1)

    def _load_manifest(self, reference):
        self.access.authorize_producer(reference.producer)
        manifest = self.store.load_committed_orchestration_result(
            *_producer_arguments(reference.producer), reference.manifest_sha256,
        )
        task = _task_result(manifest, reference.manifest_sha256)
        if task.producer != reference.producer or task.output(reference.output_name) != reference:
            raise ResultContractError("result_reference_mismatch")
        return manifest

    def _authorize_lineage(self, producer, lineage, *, for_write=False, force_current=False, active=None, visited=None):
        self.access.authorize_producer(producer, for_write=for_write)
        parents = _lineage(lineage)
        current = force_current or lineage["source_policy"] == "current"
        checked = self.access.authorize_sources(lineage["sources"], require_snapshot=current)
        source_snapshots = {
            _source_key(source): {canonical_bytes(source)} for source in lineage["sources"]
        }
        external_changed, external_sources = self.access.authorize_external_sources(
            producer, lineage.get("external_sources", []), require_snapshot=current,
        )
        changed = checked["source_snapshot_changed"] or external_changed
        active = set() if active is None else active
        visited = {} if visited is None else visited
        for parent in parents:
            if parent.producer == producer:
                raise ResultContractError("result_lineage_cycle")
            parent.completeness.require_readable(allow_partial=lineage["allow_partial_inputs"])
            key = (parent.producer, parent.manifest_sha256, current)
            if key in active:
                raise ResultContractError("result_lineage_cycle")
            if len(active) + len(visited) >= MAX_LINEAGE_RESULTS:
                raise ResultContractError("result_lineage_limit")
            manifest = self._load_manifest(parent)
            if key not in visited:
                active.add(key)
                try:
                    visited[key] = self._authorize_lineage(
                        parent.producer, manifest["lineage"], force_current=current, active=active, visited=visited,
                    )
                finally:
                    active.remove(key)
            parent_changed, parent_snapshots, parent_external = visited[key]
            changed = changed or parent_changed
            for source_key, snapshots in parent_snapshots.items():
                source_snapshots.setdefault(source_key, set()).update(snapshots)
            external_sources.update(parent_external)
            if len(external_sources) > MAX_LINEAGE_RESULTS:
                raise ResultContractError("result_lineage_limit")
        return changed, source_snapshots, external_sources

    def persist_task_result(
        self, *, producer, role, status, outputs, sources, origin, guard_token,
        upstream=(), source_policy="current", allow_partial_inputs=False, input_fingerprint=None,
        external_sources=(),
    ):
        """Retain final data/diagnostics and return only immutable named descriptors.

        Collection values can be one-pass iterators. Every write is private and
        fenced; only the last, immutable server commit makes a descriptor readable.
        A pending/invalid descriptor is retained honestly but is not consumable.
        """
        if type(producer) is not ProducerIdentity:
            raise ResultContractError("result_producer_invalid")
        validate_result_role(producer, role)
        choice(status, RESULT_STATES)
        identifier(guard_token)
        if type(outputs) not in (list, tuple) or not 1 <= len(outputs) <= MAX_OUTPUTS:
            raise ResultContractError("result_outputs_invalid")
        if any(type(output) is not NamedOutput for output in outputs):
            raise ResultContractError("result_outputs_invalid")
        if input_fingerprint is not None:
            digest(input_fingerprint)
            if status not in {"complete", "partial"}:
                raise ResultContractError("result_receipt_not_terminal")
        if len({output.name for output in outputs}) != len(outputs):
            raise ResultContractError("result_duplicate_output")
        if type(upstream) not in (list, tuple) or any(type(parent) is not ResultRef for parent in upstream):
            raise ResultContractError("result_lineage_invalid")
        lineage = {
            "origin": origin, "source_policy": source_policy, "sources": deepcopy(sources),
            "upstream": [parent.to_dict() for parent in upstream], "allow_partial_inputs": allow_partial_inputs,
        }
        external_bindings = self.access.admit_external_sources(external_sources)
        if external_bindings:
            lineage.update(version=EXTERNAL_LINEAGE_VERSION, external_sources=external_bindings)
        parents = _lineage(lineage)
        if any(parent.completeness.status == "partial" for parent in parents) and any(
            output.completeness.status == "complete" for output in outputs
        ):
            raise ResultContractError("result_partial_promoted")
        _, source_snapshots, _ = self._authorize_lineage(producer, lineage, for_write=True)
        if status == "complete" and any(output.completeness.status != "complete" for output in outputs):
            raise ResultContractError("result_incomplete")
        self.store.prepare_orchestration_result(*_producer_arguments(producer), guard_token=guard_token)
        budget = CollectionWriteBudget(self.max_result_bytes)

        def save(section):
            self._authorize_lineage(producer, lineage, for_write=True)
            return self.store.save_orchestration(
                *_producer_arguments(producer), section, guard_token=guard_token, require_analysis_guard=True,
            )

        stored_outputs = {}
        for output in outputs:
            writer = RecordTreeWriter(
                producer.to_dict(), output.name, "records", save,
                max_result_bytes=self.max_result_bytes, contract_version=TASK_RESULT_VERSION, budget=budget,
            )
            content_digest = hashlib.sha256()
            size_bytes = 0

            def account(data):
                nonlocal size_bytes
                content_digest.update(data)
                size_bytes += len(data)
                if output.kind == "comparison-v1" and size_bytes > MAX_VALUE_BYTES:
                    raise ResultContractError("result_comparison_too_large")

            if output.kind in _COLLECTION_KINDS:
                if not isinstance(output.value, Iterable) or isinstance(output.value, (str, bytes, dict)):
                    raise ResultContractError("result_records_invalid")
                account(b"[")
                count = 0
                identities = set()
                for item in output.value:
                    if count >= output.completeness.actual_count:
                        raise ResultContractError("result_count_invalid")
                    encoded = canonical_bytes(item)
                    item = json.loads(encoded)
                    _validate_item(output.kind, item, output.columns, source_snapshots)
                    if output.kind != "records-v1":
                        key = item["evidence_id"] if output.kind == "evidence-set-v1" else _source_key(item)
                        if key in identities:
                            raise ResultContractError("result_duplicate_item")
                        identities.add(key)
                    if count:
                        account(b",")
                    account(encoded)
                    writer.append(item)
                    count += 1
                account(b"]")
                if count != output.completeness.actual_count:
                    raise ResultContractError("result_count_invalid")
            else:
                count = _validate_value(output.kind, output.value, output.completeness, source_snapshots)
                if output.kind in _TEXT_KINDS:
                    for offset in range(0, len(output.value), 4096):
                        text = output.value[offset:offset + 4096]
                        account(text.encode("utf-8"))
                        writer.append({"text": text})
                else:
                    encoder = json.JSONEncoder(
                        ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":"),
                    )
                    for fragment in encoder.iterencode(output.value):
                        for offset in range(0, len(fragment), 16384):
                            text = fragment[offset:offset + 16384]
                            account(text.encode("ascii"))
                            writer.append({"data": text})
            stored_outputs[output.name] = {
                "kind": output.kind, "columns": [column.to_dict() for column in output.columns],
                "completeness": output.completeness.to_dict(), "content_sha256": content_digest.hexdigest(),
                "size_bytes": size_bytes, "item_count": count, "storage": writer.finish(),
                "character_count": len(output.value) if output.kind in _TEXT_KINDS else None,
            }
        manifest = {
            "version": TASK_RESULT_VERSION, "producer": producer.to_dict(), "role": role, "status": status,
            "lineage": lineage, "outputs": stored_outputs,
        }
        if input_fingerprint is not None or external_bindings:
            manifest.update(
                version=RESULT_MANIFEST_VERSION, input_fingerprint=input_fingerprint,
                output_order=list(stored_outputs),
            )
        encoded = canonical_bytes(manifest)
        result = _task_result(manifest, hashlib.sha256(encoded).hexdigest())
        reference = budget.save_section(manifest, save, max_section_bytes=MAX_DESCRIPTOR_BYTES)
        if reference["sha256"] != result.outputs[0].manifest_sha256:
            raise ResultContractError("result_digest_invalid")
        self._authorize_lineage(producer, lineage, for_write=True)
        receipt_options = (
            {"producer": producer, "input_fingerprint": input_fingerprint} if input_fingerprint is not None else {}
        )
        self.store.commit_orchestration_result(
            *_producer_arguments(producer), reference, guard_token=guard_token, **receipt_options,
        )
        self._authorize_lineage(producer, lineage, for_write=True)
        return result

    def recover_task_result(self, *, producer, input_fingerprint):
        """Recover one committed terminal result before replaying any producer work."""
        self.access.authorize_producer(producer)
        digest(input_fingerprint)
        receipt = self.store.load_orchestration_result_receipt(producer, input_fingerprint)
        if receipt is None:
            self.access.authorize_producer(producer)
            return None
        manifest_sha256, manifest = receipt
        task = _task_result(manifest, manifest_sha256)
        if task.producer != producer or task.status not in {"complete", "partial"}:
            raise ResultContractError("result_receipt_invalid")
        self._authorize_lineage(producer, manifest["lineage"])
        for reference in task.outputs:
            if reference.completeness.status not in {"complete", "partial"}:
                continue
            reader = self.open_result(reference, allow_partial=True)
            if reference.kind in _COLLECTION_KINDS:
                values = reader.iter_items()
            elif reference.kind in _TEXT_KINDS:
                values = reader.iter_text()
            else:
                values = reader.iter_value_bytes()
            for _ in values:
                pass
        self._authorize_lineage(producer, manifest["lineage"])
        return task

    def open_result(self, reference, *, allow_partial=False, require_current_sources=False):
        if type(reference) is not ResultRef or type(require_current_sources) is not bool:
            raise ResultContractError("result_reference_untrusted")
        reference.completeness.require_readable(allow_partial=allow_partial)
        manifest = self._load_manifest(reference)
        self._authorize_lineage(reference.producer, manifest["lineage"], force_current=require_current_sources)
        return OrchestrationResultReader(
            self, reference, manifest, allow_partial=allow_partial, require_current_sources=require_current_sources,
        )

    def resolve_input(self, spec, *, consumer, task_results, existing_results=None):
        """Resolve only server-selected task outputs or admitted same-conversation aliases."""
        if type(spec) is not InputSpec or type(consumer) is not ProducerIdentity or type(task_results) is not dict:
            raise ResultContractError("result_binding_invalid")
        self.access.authorize_producer(consumer)
        binding = spec.binding
        if binding.existing_result is not None:
            catalog = {} if existing_results is None else existing_results
            if type(catalog) is not dict:
                raise ResultContractError("result_reference_untrusted")
            reference = catalog.get(binding.existing_result)
            if type(reference) is not ResultRef:
                raise ResultContractError("result_reference_untrusted")
        else:
            task = task_results.get(binding.step_id)
            if type(task) is not TaskResult:
                raise ResultContractError("result_producer_missing")
            if (
                task.producer.step_id != binding.step_id or binding.step_id == consumer.step_id
                or any(
                    getattr(task.producer, key) != getattr(consumer, key)
                    for key in ("user_id", "conversation_id", "run_id", "attempt_index")
                )
            ):
                raise ResultContractError("result_attempt_mismatch")
            reference = task.output(binding.output_name)
        if reference.producer == consumer:
            raise ResultContractError("result_binding_cycle")
        if reference.kind not in spec.kinds:
            raise ResultContractError("result_kind_incompatible")
        return self.open_result(reference, allow_partial=spec.allow_partial)


class OrchestrationResultReader:
    """Full readers verify the last item, declared counts, and the complete digest.

    ``kind == 'records'``, ``record_count``, ``iter_records()`` and ``recheck()``
    implement GeneratedRecordExportSource without importing a renderer.
    """

    def __init__(self, service, reference, manifest, *, allow_partial, require_current_sources):
        self._service = service
        self.reference = reference
        self._manifest = deepcopy(manifest)
        self._allow_partial = allow_partial
        self._require_current_sources = require_current_sources
        self.result_kind = reference.kind
        self.kind = "records" if reference.kind == "records-v1" else reference.kind
        self.record_count = reference.item_count if self.kind == "records" else None
        self.character_count = reference.character_count
        self.columns = reference.columns
        self.completeness = reference.completeness
        self._source_snapshots = {}
        self._external_sources = set()
        self._changed = False

    def recheck(self):
        self.reference.completeness.require_readable(allow_partial=self._allow_partial)
        self._service._load_manifest(self.reference)
        self._changed, self._source_snapshots, self._external_sources = self._service._authorize_lineage(
            self.reference.producer, self._manifest["lineage"], force_current=self._require_current_sources,
        )

    def metadata(self):
        self.recheck()
        metadata = {
            "reference": self.reference.to_dict(), "source_count": len(self._source_snapshots),
            "source_snapshot_changed": self._changed, "origin": self._manifest["lineage"]["origin"],
            "source_policy": self._manifest["lineage"]["source_policy"],
        }
        if self._manifest["version"] == RESULT_MANIFEST_VERSION:
            metadata["input_fingerprint"] = self._manifest["input_fingerprint"]
        if self._external_sources:
            metadata.update(
                external_source_count=len({reference.identity() for reference in self._external_sources}),
                external_sources=deepcopy(self._manifest["lineage"].get("external_sources", [])),
            )
        return metadata

    def _collection(self):
        output = self._manifest["outputs"][self.reference.output_name]
        return _collection_manifest(self.reference.producer, self.reference.output_name, output["storage"])

    def _load_section(self, reference):
        self.recheck()
        if type(reference) is not dict or type(reference.get("size_bytes")) is not int:
            raise ResultContractError("result_reference_untrusted")
        if reference["size_bytes"] > MAX_VALUE_BYTES:
            raise ResultContractError("result_section_too_large")
        return self._service.store.load_orchestration(*_producer_arguments(self.reference.producer), reference)

    def _items(self):
        self.recheck()
        yield from iter_record_tree(self._collection(), self.reference.output_name, self._load_section)

    def iter_items(self):
        if self.result_kind not in _COLLECTION_KINDS:
            raise ResultContractError("result_kind_incompatible")
        content_digest, size, count = hashlib.sha256(b"["), 1, 0
        identities = set()
        for item in self._items():
            _validate_item(self.result_kind, item, self.columns, self._source_snapshots)
            if self.result_kind != "records-v1":
                key = item["evidence_id"] if self.result_kind == "evidence-set-v1" else _source_key(item)
                if key in identities:
                    raise ResultContractError("result_duplicate_item")
                identities.add(key)
            encoded = (b"," if count else b"") + canonical_bytes(item)
            content_digest.update(encoded)
            size += len(encoded)
            count += 1
            if count > self.reference.item_count:
                raise ResultContractError("result_content_integrity")
            yield deepcopy(item)
        content_digest.update(b"]")
        self._verify(content_digest, size + 1, count)

    def iter_records(self):
        if self.result_kind != "records-v1":
            raise ResultContractError("result_kind_incompatible")
        for record in self.iter_items():
            yield {column.name: record[column.name] for column in self.columns}

    def _verify(self, content_digest, size, count):
        if (
            content_digest.hexdigest() != self.reference.content_sha256
            or size != self.reference.size_bytes or count != self.reference.item_count
        ):
            raise ResultContractError("result_content_integrity")
        self.recheck()

    def iter_text(self):
        if self.result_kind not in _TEXT_KINDS:
            raise ResultContractError("result_kind_incompatible")
        content_digest, size, characters = hashlib.sha256(), 0, 0
        for item in self._items():
            if type(item) is not dict or set(item) != {"text"} or type(item["text"]) is not str:
                raise ResultContractError("result_value_invalid")
            data = item["text"].encode("utf-8")
            content_digest.update(data)
            size += len(data)
            characters += len(item["text"])
            yield item["text"]
        if characters != self.character_count:
            raise ResultContractError("result_content_integrity")
        self._verify(content_digest, size, 1)

    def iter_value_bytes(self):
        if self.result_kind not in {"structured-v1", "comparison-v1"}:
            raise ResultContractError("result_kind_incompatible")
        content_digest, size = hashlib.sha256(), 0
        comparison = bytearray() if self.result_kind == "comparison-v1" else None
        for item in self._items():
            if (
                type(item) is not dict or set(item) != {"data"} or type(item["data"]) is not str
                or not item["data"].isascii()
            ):
                raise ResultContractError("result_value_invalid")
            data = item["data"].encode("ascii")
            content_digest.update(data)
            size += len(data)
            if comparison is not None:
                if size > MAX_VALUE_BYTES:
                    raise ResultContractError("result_comparison_too_large")
                comparison.extend(data)
            yield data
        if comparison is not None:
            _validate_value(self.result_kind, json.loads(comparison), self.completeness, self._source_snapshots)
        self._verify(content_digest, size, self.reference.item_count)

    def _materialization_limit(self, max_bytes):
        integer(max_bytes, minimum=1)
        if max_bytes > MAX_VALUE_BYTES or self.reference.size_bytes > max_bytes:
            raise ResultContractError("result_requires_streaming")

    def read_text(self, *, max_bytes=MAX_VALUE_BYTES):
        self._materialization_limit(max_bytes)
        return "".join(self.iter_text())

    def read_value(self, *, max_bytes=MAX_VALUE_BYTES):
        self._materialization_limit(max_bytes)
        value = json.loads(b"".join(self.iter_value_bytes()))
        _validate_value(self.result_kind, value, self.completeness, self._source_snapshots)
        return value

    def preview(self, *, max_items=3, max_bytes=4096):
        """Inspection only: never a full-reader replacement or an integrity receipt."""
        integer(max_items, minimum=1)
        integer(max_bytes, minimum=1)
        if max_items > MAX_PREVIEW_ITEMS or max_bytes > MAX_PREVIEW_BYTES:
            raise ResultContractError("result_preview_limit")
        if self.result_kind in _COLLECTION_KINDS and max_bytes < 2:
            raise ResultContractError("result_preview_limit")
        self.recheck()
        if self.result_kind in _COLLECTION_KINDS:
            rows, total = read_result_records(
                self._collection(), self.reference.output_name, self._load_section, limit=max_items,
            )
            value = []
            for row in rows:
                _validate_item(self.result_kind, row, self.columns, self._source_snapshots)
                if len(canonical_bytes([*value, row])) > max_bytes:
                    break
                value.append(row)
            truncated = len(value) != total
        else:
            fragments = self.iter_text() if self.result_kind in _TEXT_KINDS else (
                chunk.decode("ascii") for chunk in self.iter_value_bytes()
            )
            parts, size, truncated = [], 0, False
            for fragment in fragments:
                encoded = fragment.encode("utf-8")
                if size + len(encoded) > max_bytes:
                    parts.append(encoded[:max_bytes - size].decode("utf-8", errors="ignore"))
                    truncated = True
                    break
                parts.append(fragment)
                size += len(encoded)
            value = "".join(parts)
        self.recheck()
        return {
            "kind": self.result_kind, "value": value, "preview": True,
            "truncated": truncated, "integrity_verified": False,
            "item_count": self.reference.item_count,
        }


class SavedAnalysisRecordSource:
    """Explicit public-values projection of an already authorized SavedAnalysisInput.

    Owners call load_orchestration_analysis_input(..., bounded=True) and inject its
    reader. The native manifest, full records, evidence, coverage and source
    snapshots remain intact; no arbitrary content becomes analyze-final-v1.
    """

    kind = "records"

    def __init__(self, reader, *, columns):
        validate_columns(columns, "records-v1")
        manifest = reader.manifest
        output = (manifest.get("outputs") or {}).get(manifest.get("authoritative_output")) or {}
        if (
            manifest.get("contract_version") != "analyze-final-v1" or output.get("kind") != "records"
            or (manifest.get("validation") or {}).get("status") != "valid"
            or (manifest.get("execution") or {}).get("status") != "succeeded"
        ):
            raise ResultContractError("result_native_analysis_incomplete")
        self.record_count = integer(manifest.get("record_count"))
        self.columns = columns
        self._reader = reader
        self.recheck()

    def recheck(self):
        self._reader.recheck()

    def metadata(self):
        self.recheck()
        return {
            **self._reader.metadata(),
            "coverage": deepcopy(self._reader.manifest.get("coverage") or {}),
            "sources": deepcopy((self._reader.manifest.get("analysis_access") or {}).get("sources") or []),
        }

    def iter_units(self):
        self.recheck()
        count = 0
        for unit in self._reader.iter_units():
            record = unit.get("record")
            if type(record) is not dict:
                raise ResultContractError("result_native_analysis_invalid")
            validate_record(record.get("values"), self.columns)
            count += 1
            if count > self.record_count:
                raise ResultContractError("result_count_invalid")
            yield deepcopy(unit)
        if count != self.record_count:
            raise ResultContractError("result_count_invalid")
        self.recheck()

    def iter_records(self):
        for unit in self.iter_units():
            values = unit["record"]["values"]
            yield {column.name: values[column.name] for column in self.columns}
