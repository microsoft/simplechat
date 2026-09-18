# functions_workflow_iterations.py
"""Immutable loop membership and execution-scoped current-item receipts."""

import hashlib
import json
from copy import deepcopy

from functions_analysis_access import AnalysisResultUnavailable
from functions_workflow_identity import canonical_digest, workflow_execution_id, workflow_node_identity
from functions_workflow_result_store import load_workflow_node_result, _quota_bytes
from functions_workflow_runtime_store import workflow_runtime_store


FROZEN_ITEMS_VERSION = "workflow-frozen-items-v1"


def _selectors(identity):
    return {name: identity[name] for name in ("node_id", "execution_id", "iteration_path", "attempt")}


def loop_execution_identity(workflow, run_id, loop_id, parent_path):
    return workflow_node_identity(
        workflow, run_id, loop_id, workflow_execution_id(workflow, run_id, loop_id, parent_path),
        1, iteration_path=parent_path,
    )


def _item_digest(item):
    return canonical_digest({key: value for key, value in item.items() if key not in {"item_id", "item_sha256"}})


def _item_id(identity, index, digest):
    return canonical_digest({"loop_execution_id": identity["execution_id"], "index": index, "item_sha256": digest})


def freeze_workflow_loop(execution, node, *, actor_user_id, record_input=None, consumed_inputs=()):
    """Seal membership before admitting any body invocation; never save a prefix."""
    from functions_workflow_collections import CollectionWriteBudget, RecordTreeWriter
    from functions_workflow_loop_inputs import (
        WorkflowLoopInputError, iter_workflow_loop_documents, reauthorize_workflow_loop_document,
    )
    from functions_workflow_results import _encoded_result_size, iter_result_records

    identity = loop_execution_identity(
        execution.workflow, execution.run_id, node["id"], execution.iteration_path,
    )
    saved = execution.store.journal_read("loop", identity["execution_id"])
    if saved is not None:
        return load_frozen_loop(
            execution.workflow, execution.run_id, identity, store=execution.store,
            load_result=execution.load_result,
        )
    control = execution.check()
    limit = min(node["max_items"], (control.get("loop_policy") or {}).get("max_items", 500))
    iterable = node["iterable"]
    capture = {}
    source_receipt = deepcopy(record_input.receipt) if record_input is not None else None
    if iterable["kind"] == "input":
        if record_input is None:
            raise ValueError("A saved-record loop requires its exact authorized collection.")
        if record_input.record_count > limit:
            execution.pause_input(
                f"This collection contains {record_input.record_count} items. This run allows {limit}. "
                f"Select {limit} or fewer items before starting a new run.",
                code="loop_item_limit_exceeded",
            )
        entries = (
            {"kind": "record", "source_ordinal": index, "record_sha256": canonical_digest(value)}
            for index, value in enumerate(record_input.iter_records())
        )
    else:
        entries = (
            {"kind": "document", **entry}
            for entry in iter_workflow_loop_documents(
                execution.workflow, iterable, actor_user_id=actor_user_id, max_items=limit,
                settings={**execution.settings, "workflow_max_loop_items": (control.get("loop_policy") or {}).get("max_items", 500)},
                check=execution.check, capture_metadata=capture,
            )
        )

    def save(section):
        execution.check()
        return execution.save_result(
            execution.workflow, execution.run_id, None, section, settings=execution.settings,
            **_selectors(identity),
        )

    maximum = _quota_bytes(execution.settings)
    budget = CollectionWriteBudget(maximum)
    writer = RecordTreeWriter(
        identity, "items", "records", save, max_result_bytes=_quota_bytes(execution.settings),
        contract_version=FROZEN_ITEMS_VERSION, budget=budget,
    )
    membership = hashlib.sha256()
    count = 0
    for count, value in enumerate(entries, start=1):
        if count > limit:
            execution.pause_input(
                f"This selection contains at least {count} items. This run allows {limit}. "
                f"Narrow the query or select {limit} or fewer documents before starting a new run.",
                code="loop_item_limit_exceeded",
            )
        item = {**deepcopy(value), "index": count - 1}
        digest = _item_digest(item)
        item.update(item_sha256=digest, item_id=_item_id(identity, count - 1, digest))
        writer.append(item)
        membership.update(json.dumps(
            [item["index"], item["item_id"], digest], ensure_ascii=True, separators=(",", ":"),
        ).encode("ascii") + b"\n")
    if record_input is None and (
        capture.get("complete") is not True or capture.get("count") != count or capture.get("count_exact") is not True
    ):
        raise WorkflowLoopInputError(
            "The complete document selection could not be confirmed. No loop body work was admitted.",
            code="workflow_loop_capture_incomplete",
        )
    descriptor = writer.finish()
    if record_input is not None:
        record_input.recheck()
    else:
        captured = {"contract_version": FROZEN_ITEMS_VERSION, "identity": identity, "outputs": {"items": descriptor}}
        for item in iter_result_records(
            captured, "items",
            lambda ref: execution.load_result(execution.workflow, execution.run_id, None, ref, **_selectors(identity)),
        ):
            execution.check()
            reauthorize_workflow_loop_document(execution.workflow, item, actor_user_id=actor_user_id)
    manifest = {
        "contract_version": FROZEN_ITEMS_VERSION, "identity": identity,
        "outputs": {"items": descriptor}, "count": count, "max_items": limit,
        "item_key": node["item_key"], "selection": deepcopy(iterable),
        "selection_sha256": canonical_digest(iterable), "membership_sha256": membership.hexdigest(),
        "source_receipt": source_receipt, "consumed_inputs": list(consumed_inputs),
        "source_allow_partial": bool(record_input is not None and record_input.allow_partial),
        "capture": capture if record_input is None else {
            "complete": True, "count": count, "count_exact": True, "query_mode": "saved_output",
        },
        "iteration_inputs": deepcopy(execution.iteration_inputs),
        "frozen_at": execution.store._now().isoformat(),
    }
    budget.consume(_encoded_result_size(manifest))
    reference = save(manifest)
    payload = {
        "execution_id": identity["execution_id"], "node_id": node["id"],
        "identity": identity, "manifest_ref": reference, "count": count, "max_items": limit,
        "next_index": 0, "state": "running", "completed": 0, "skipped": 0, "failed": 0,
        "frozen_at": manifest["frozen_at"],
    }
    execution.store.journal_commit(
        execution.lease.token, "loop", identity["execution_id"], payload, immutable=True,
        updates={"cursor": execution.cursor()},
    )
    return manifest, reference, payload


def load_frozen_loop(workflow, run_id, identity, *, store=None, load_result=load_workflow_node_result):
    expected = loop_execution_identity(workflow, run_id, identity["node_id"], identity["iteration_path"])
    if identity != expected:
        raise AnalysisResultUnavailable("workflow_loop_identity_invalid")
    store = store or workflow_runtime_store(workflow, run_id)
    row = store.journal_read("loop", identity["execution_id"])
    payload = (row or {}).get("payload") or {}
    reference = payload.get("manifest_ref")
    if payload.get("identity") != identity or not isinstance(reference, dict):
        raise AnalysisResultUnavailable("workflow_loop_manifest_unavailable")
    manifest = load_result(workflow, run_id, None, reference, **_selectors(identity))
    pending = list(workflow["flow"]["nodes"])
    node = None
    while pending:
        candidate = pending.pop()
        if candidate["id"] == identity["node_id"] and candidate["kind"] == "for_each":
            node = candidate
            break
        if candidate["kind"] == "for_each":
            pending.extend(candidate["body"]["nodes"])
        elif candidate["kind"] == "if":
            pending.extend(candidate["then"]["nodes"])
            pending.extend(candidate["else"]["nodes"])
    if (
        node is None or manifest.get("contract_version") != FROZEN_ITEMS_VERSION or manifest.get("identity") != identity
        or type(manifest.get("count")) is not int or manifest["count"] != payload.get("count")
        or manifest.get("max_items") != payload.get("max_items")
        or not 0 <= manifest["count"] <= manifest["max_items"]
        or manifest.get("selection") != node["iterable"]
        or manifest["max_items"] != min(node["max_items"], (store.read().get("loop_policy") or {}).get("max_items", 500))
        or (manifest.get("outputs", {}).get("items") or {}).get("record_count") != manifest["count"]
        or manifest.get("selection_sha256") != canonical_digest(manifest.get("selection"))
    ):
        raise AnalysisResultUnavailable("workflow_loop_manifest_invalid")
    if node["iterable"]["kind"] == "input":
        binding = next((value for value in node["inputs"] if value["name"] == node["iterable"]["name"]), None)
        source = manifest.get("source_receipt") or {}
        producer = source.get("producer") or {}
        if (
            binding is None or producer.get("node_id") != binding["source"]["node_id"]
            or producer.get("workflow_id") != workflow["id"] or producer.get("run_id") != run_id
            or len(producer.get("iteration_path") or []) > len(identity["iteration_path"])
            or (producer.get("iteration_path") or []) != identity["iteration_path"][:len(producer.get("iteration_path") or [])]
            or manifest.get("source_allow_partial") != binding["allow_partial"]
        ):
            raise AnalysisResultUnavailable("workflow_loop_source_receipt_invalid")
    elif manifest.get("source_receipt") is not None:
        raise AnalysisResultUnavailable("workflow_loop_source_receipt_invalid")
    return manifest, reference, payload


def read_frozen_item(workflow, run_id, manifest, index, *, load_result=load_workflow_node_result):
    from functions_workflow_results import read_result_records

    if type(index) is not int or not 0 <= index < manifest["count"]:
        raise AnalysisResultUnavailable("workflow_loop_item_invalid")
    identity = manifest["identity"]
    rows, total = read_result_records(
        manifest, "items",
        lambda ref: load_result(workflow, run_id, None, ref, **_selectors(identity)),
        offset=index, limit=1,
    )
    if total != manifest["count"] or len(rows) != 1:
        raise AnalysisResultUnavailable("workflow_loop_item_invalid")
    item = rows[0]
    if (
        item.get("index") != index or item.get("item_sha256") != _item_digest(item)
        or item.get("item_id") != _item_id(identity, index, item["item_sha256"])
        or item.get("kind") not in {"record", "document"}
    ):
        raise AnalysisResultUnavailable("workflow_loop_item_invalid")
    return item


def frozen_item_receipt(manifest, reference, item):
    return {
        "loop_id": manifest["identity"]["node_id"],
        "loop_execution_id": manifest["identity"]["execution_id"],
        "manifest_ref": deepcopy(reference), "item_id": item["item_id"], "index": item["index"],
        "item_sha256": item["item_sha256"],
    }


def _authorize_frozen_document(workflow, item, reader_user_id):
    from functions_workflow_loop_inputs import WorkflowLoopInputError, reauthorize_workflow_loop_document

    try:
        return reauthorize_workflow_loop_document(workflow, item, actor_user_id=reader_user_id)
    except WorkflowLoopInputError as exc:
        raise AnalysisResultUnavailable(exc.code) from exc


def load_frozen_item_value(workflow, run_id, manifest, item, *, reader_user_id,
                           load_result=load_workflow_node_result, source_resolver=None):
    if item["kind"] == "record":
        from functions_workflow_node_results import open_workflow_record_input

        receipt = manifest.get("source_receipt") or {}
        reader = open_workflow_record_input(
            workflow, run_id, receipt.get("producer"), receipt.get("result_ref"),
            output_name=receipt.get("output_name"), reader_user_id=reader_user_id,
            allow_partial=manifest.get("source_allow_partial", False),
            load_result=load_result, source_resolver=source_resolver,
        )
        rows, _ = reader.read_records(offset=item["source_ordinal"], limit=1)
        if len(rows) != 1 or canonical_digest(rows[0]) != item["record_sha256"]:
            raise AnalysisResultUnavailable("workflow_loop_item_changed")
        value = rows[0]
    else:
        _authorize_frozen_document(workflow, item, reader_user_id)
        value = item["document"]
    return {"value": deepcopy(value), "key": item["item_id"], "index": item["index"]}


def authorize_frozen_loop(workflow, run_id, binding, *, reader_user_id,
                          load_result=load_workflow_node_result, source_resolver=None, store=None, source_callback=None):
    from functions_workflow_node_results import authorize_workflow_node_result_read

    if not isinstance(binding, dict) or not isinstance(binding.get("producer"), dict):
        raise AnalysisResultUnavailable("workflow_loop_identity_invalid")
    manifest, reference, _ = load_frozen_loop(
        workflow, run_id, binding["producer"], store=store, load_result=load_result,
    )
    if reference != binding.get("manifest_ref"):
        raise AnalysisResultUnavailable("workflow_loop_manifest_invalid")
    sources, changed = {}, False
    source_ids = set()

    def source_seen(source):
        key = canonical_digest(source)
        if key in source_ids:
            return
        source_ids.add(key)
        if source_callback is not None:
            source_callback(source)
        else:
            sources[key] = source

    for receipt in manifest.get("consumed_inputs") or []:
        _, access = authorize_workflow_node_result_read(
            workflow, run_id, receipt["producer"], receipt["result_ref"],
            reader_user_id=reader_user_id, load_result=load_result, source_resolver=source_resolver,
            include_sources=False, source_callback=source_seen,
        )
        changed |= access["source_snapshot_changed"]
    if manifest["selection"]["kind"] != "input":
        for index in range(manifest["count"]):
            item = read_frozen_item(workflow, run_id, manifest, index, load_result=load_result)
            _authorize_frozen_document(workflow, item, reader_user_id)
            source_seen(item["source"])
    return {
        "sources": list(sources.values()) if source_callback is None else None,
        "source_count": len(source_ids), "source_snapshot_changed": changed,
    }


def authorize_iteration_path(workflow, run_id, identity, *, reader_user_id, receipts=None,
                             load_result=load_workflow_node_result, source_resolver=None, store=None):
    path = identity.get("iteration_path") or []
    if receipts is not None and (not isinstance(receipts, list) or len(receipts) != len(path)):
        raise AnalysisResultUnavailable("workflow_iteration_receipt_invalid")
    verified = []
    for index, frame in enumerate(path):
        producer = loop_execution_identity(workflow, run_id, frame["loop_id"], path[:index])
        manifest, reference, _ = load_frozen_loop(
            workflow, run_id, producer, store=store, load_result=load_result,
        )
        item = read_frozen_item(workflow, run_id, manifest, frame["index"], load_result=load_result)
        if frame["item_id"] != item["item_id"]:
            raise AnalysisResultUnavailable("workflow_loop_item_invalid")
        expected = frozen_item_receipt(manifest, reference, item)
        if receipts is not None and receipts[index] != expected:
            raise AnalysisResultUnavailable("workflow_iteration_receipt_invalid")
        load_frozen_item_value(
            workflow, run_id, manifest, item, reader_user_id=reader_user_id,
            load_result=load_result, source_resolver=source_resolver,
        )
        verified.append(expected)
    return verified
