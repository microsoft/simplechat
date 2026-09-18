# test_workflow_collection_pages.py
"""
Functional tests for bounded, immutable workflow record trees and business keys.
Version: 0.261.117
Implemented in: 0.261.117

JSON-copying, content-addressed callbacks exercise the production primitives
without application initialization, Azure clients, network calls, or local data
files. Tests cover exact payload retention, tree integrity, cumulative quotas,
failed completion, bounded buffers, selective reads, and external key merging.
"""

import hashlib
import json
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1].joinpath("application", "single_app")))

# Establish the application import path before importing its standalone module.
import functions_workflow_collections as collections
from functions_workflow_collections import (
    COLLECTION_MATERIALIZATION_BYTES,
    MAX_IDENTITY_RUN_LEVELS,
    MAX_RECORD_COUNT,
    MAX_RECORD_TREE_LEVEL,
    RECORD_INDEX_FANOUT,
    RECORD_PAGE_BYTES,
    RECORD_PAGE_SIZE,
    CollectionIntegrityError,
    CollectionSizeError,
    CollectionWriteBudget,
    RecordIdentityValidator,
    RecordTreeWriter,
    iter_record_tree,
    read_record_tree,
)


IDENTITY = {
    "scope_type": "personal", "scope_id": "owner", "workflow_id": "workflow-collection",
    "run_id": "run-collection", "node_id": "collect-findings", "execution_id": "execution-collection",
    "attempt": 1, "iteration_path": [{"loop_id": "outer", "item_id": "frozen-item", "index": 3}],
}
MAX_RESULT_BYTES = 128 * 1024 * 1024


def encoded(value):
    return json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":"))


def copied(value):
    return json.loads(encoded(value))


class JsonSections:
    def __init__(self):
        self.contents = {}
        self.reads = []
        self.writes = []
        self.fail_name = None
        self.fail_at = None
        self.attempts = 0

    def save(self, section):
        self.attempts += 1
        if self.fail_name is not None and section.get("output_name") == self.fail_name or self.attempts == self.fail_at:
            raise OSError("Synthetic section write failure.")
        payload = encoded(section)
        digest = hashlib.sha256(payload.encode("ascii")).hexdigest()
        self.contents[digest] = payload
        reference = {
            "storage": "cosmos", "schema_version": 1, "sha256": digest,
            "size_bytes": len(payload), "chunk_count": math.ceil(len(payload) / (256 * 1024)),
        }
        self.writes.append({
            "name": section.get("output_name"), "kind": section.get("kind"),
            "reference": copied(reference),
        })
        return copied(reference)

    def load(self, reference):
        payload = self.contents[reference["sha256"]]
        assert len(payload) == reference["size_bytes"]
        assert hashlib.sha256(payload.encode("ascii")).hexdigest() == reference["sha256"]
        section = json.loads(payload)
        self.reads.append(section["output_name"])
        return section

    def get(self, reference):
        return json.loads(self.contents[reference["sha256"]])

    def replace(self, reference, mutate):
        section = self.get(reference)
        mutate(section)
        return self.save(section)


def writer_for(store, *, name="records", kind="records", **kwargs):
    return RecordTreeWriter(
        IDENTITY, name, kind, store.save,
        max_result_bytes=kwargs.pop("max_result_bytes", MAX_RESULT_BYTES), **kwargs,
    )


def manifest_for(writer, descriptor=None):
    return {
        "contract_version": writer.contract_version, "identity": copied(IDENTITY),
        "outputs": {writer.output_name: descriptor if descriptor is not None else writer.finish()},
    }


def save_rows(rows, *, name="records", kind="records", **kwargs):
    store = JsonSections()
    writer = writer_for(store, name=name, kind=kind, **kwargs)
    for row in rows:
        writer.append(row)
    return store, writer, manifest_for(writer)


def replace_root(store, manifest, mutate, name="records"):
    manifest = copied(manifest)
    output = manifest["outputs"][name]
    output["result_ref"] = store.replace(output["result_ref"], mutate)
    store.reads.clear()
    return manifest


def replace_leaf(store, manifest, mutate, name="records"):
    manifest = copied(manifest)
    output = manifest["outputs"][name]
    root = store.get(output["result_ref"])
    child = root["value"]["children"][0]
    assert child["level"] == 0
    child["result_ref"] = store.replace(child["result_ref"], mutate)
    output["result_ref"] = store.save(root)
    store.reads.clear()
    return manifest


@pytest.mark.parametrize("kind", ["records", "document_results"])
@pytest.mark.parametrize("count", [0, 1, 100, 101, 10001, 10157])
def test_complete_record_counts_order_and_kind(count, kind):
    store = JsonSections()
    writer = writer_for(store, kind=kind)
    for index in range(count):
        writer.append({"ordinal": index, "original": {"items": [None, False, "caf\u00e9", index]}})
    assert writer.descriptor is None
    assert all(write["name"] != "records" for write in store.writes)
    if count >= RECORD_PAGE_SIZE:
        assert store.writes

    manifest = manifest_for(writer)
    descriptor = manifest["outputs"]["records"]
    assert set(descriptor) == {"kind", "storage_kind", "result_ref", "record_count"}
    assert descriptor["kind"] == kind
    assert descriptor["storage_kind"] == "record_tree"
    assert descriptor["record_count"] == count
    assert len(encoded(descriptor)) < 512
    actual_count = 0
    for index, row in enumerate(iter_record_tree(manifest, "records", store.load)):
        assert row == {"ordinal": index, "original": {"items": [None, False, "caf\u00e9", index]}}
        actual_count += 1
    assert actual_count == count
    rows, total = read_record_tree(manifest, "records", store.load)
    assert len(rows) == min(count, 100)
    assert total == count
    root = store.get(descriptor["result_ref"])
    assert root["value"]["record_kind"] == kind
    assert root["value"]["offset"] == 0
    if count > 10000:
        assert root["value"]["level"] >= 2
    assert "analysis_access" not in root and "analysis_origin" not in root


def test_many_index_levels_use_the_same_contiguous_format(monkeypatch):
    monkeypatch.setattr(collections, "RECORD_INDEX_FANOUT", 3)
    store, writer, manifest = save_rows({"index": index} for index in range(10001))
    root = store.get(manifest["outputs"]["records"]["result_ref"])
    assert root["value"]["level"] >= 5
    for payload in store.contents.values():
        section = json.loads(payload)
        if section["kind"] == "record_tree":
            assert len(section["value"]["children"]) <= 3
            assert len(payload) <= RECORD_PAGE_BYTES
    assert sum(1 for _ in iter_record_tree(manifest, "records", store.load)) == 10001
    store.reads.clear()
    rows, total = read_record_tree(manifest, "records", store.load, offset=9999, limit=2)
    assert rows == [{"index": 9999}, {"index": 10000}]
    assert total == 10001
    assert {name for name in store.reads if ":leaf:" in name} == {"records:leaf:9900", "records:leaf:10000"}
    assert writer.buffered_index_entries == 0


def test_repeated_equal_records_remain_distinct_and_are_not_rewritten():
    row = {
        "item_id": "same", "document_id": "data-not-authorization", "role": "system",
        "authoritative_output": "not-engine-state", "value": ["same", {"nested": True}],
    }
    store, _, manifest = save_rows(copied(row) for _ in range(250))
    rows, total = read_record_tree(manifest, "records", store.load, limit=None)
    assert total == 250
    assert rows == [row] * 250
    assert set(manifest) == {"identity", "contract_version", "outputs"}


def test_large_records_stand_alone_without_splitting_or_truncation():
    large = {"original": "a" * 12000 + "MIDDLE-ONLY-SENTINEL" + "z" * RECORD_PAGE_BYTES}
    expected = [{"small": "before"}, large, {"small": "after"}]
    store, _, manifest = save_rows(expected, kind="document_results")
    leaf_sections = [
        store.get(write["reference"])
        for write in store.writes if write["kind"] == "document_results"
    ]
    assert [len(section["value"]) for section in leaf_sections] == [1, 1, 1]
    rows, total = read_record_tree(manifest, "records", store.load)
    assert rows == expected
    assert total == 3


def test_single_record_at_the_materialization_boundary_is_allowed():
    empty_leaf = {
        "contract_version": "workflow-result-v2", "producer": IDENTITY,
        "output_name": "records:leaf:0", "kind": "records", "value": [],
    }
    filler = COLLECTION_MATERIALIZATION_BYTES - len(encoded(empty_leaf)) - len(encoded({"payload": ""}))
    row = {"payload": "x" * filler}
    store, _, manifest = save_rows([row])
    assert store.writes[0]["reference"]["size_bytes"] == COLLECTION_MATERIALIZATION_BYTES
    assert read_record_tree(manifest, "records", store.load) == ([row], 1)


def test_oversized_record_fails_without_a_completed_descriptor():
    store = JsonSections()
    writer = writer_for(store)
    with pytest.raises(CollectionSizeError, match="byte limit"):
        writer.append({"payload": "x" * COLLECTION_MATERIALIZATION_BYTES})
    assert writer.descriptor is None
    assert not store.writes
    with pytest.raises(CollectionIntegrityError, match="failed"):
        writer.finish()


@pytest.mark.parametrize("row", [
    [], "not-an-object", None, {"number": float("nan")}, {"number": float("inf")},
    {"bytes": b"not-json"}, {"tuple": (1, 2)}, {1: "coerced-key"},
])
def test_non_json_or_non_object_records_are_rejected(row):
    store = JsonSections()
    writer = writer_for(store)
    with pytest.raises(ValueError):
        writer.append(row)
    assert writer.descriptor is None
    with pytest.raises(CollectionIntegrityError, match="failed"):
        writer.finish()


def test_input_and_transport_mutation_cannot_change_completed_records():
    store = JsonSections()
    identity = copied(IDENTITY)

    def mutating_save(section):
        reference = store.save(section)
        section["producer"]["attempt"] = 99
        section["value"] = {"not": "the saved value"}
        return reference

    writer = RecordTreeWriter(identity, "records", "records", mutating_save, max_result_bytes=MAX_RESULT_BYTES)
    row = {"nested": {"value": ["original"]}}
    writer.append(row)
    row["nested"]["value"].append("later mutation")
    identity["attempt"] = 88
    manifest = manifest_for(writer)
    assert read_record_tree(manifest, "records", store.load) == ([{"nested": {"value": ["original"]}}], 1)
    descriptor = writer.finish()
    before = len(store.writes)
    descriptor["record_count"] = 999
    assert writer.finish()["record_count"] == 1
    assert len(store.writes) == before
    with pytest.raises(CollectionIntegrityError, match="already finished"):
        writer.append({"too": "late"})


@pytest.mark.parametrize("mutate", [
    lambda section: section.update(unexpected="extra"),
    lambda section: section.update(contract_version="workflow-result-v1"),
    lambda section: section.update(output_name="other:leaf:0"),
    lambda section: section.update(kind="document_results"),
    lambda section: section["producer"].update(attempt=True),
    lambda section: section["producer"].update(iteration_path=[]),
    lambda section: section.update(value=[123]),
    lambda section: section.update(value=[]),
    lambda section: section.pop("value"),
])
def test_leaf_envelopes_and_record_shapes_are_exact(mutate):
    store, _, manifest = save_rows([{"value": "retained"}])
    invalid = replace_leaf(store, manifest, mutate)
    with pytest.raises(CollectionIntegrityError):
        read_record_tree(invalid, "records", store.load)


@pytest.mark.parametrize("mutate", [
    lambda section: section.update(unexpected="extra"),
    lambda section: section.update(kind="records"),
    lambda section: section["producer"].update(attempt=True),
    lambda section: section["value"].update(version=True),
    lambda section: section["value"].update(record_kind="document_results"),
    lambda section: section["value"].update(record_count=101),
    lambda section: section["value"].update(record_count=True),
    lambda section: section["value"].update(offset=1),
    lambda section: section["value"].update(level=0),
    lambda section: section["value"].update(level=MAX_RECORD_TREE_LEVEL + 1),
    lambda section: section["value"].update(children={}),
    lambda section: section["value"].update(children=[]),
    lambda section: section["value"].update(extra="field"),
    lambda section: section["value"]["children"].reverse(),
    lambda section: section["value"]["children"][1].update(offset=99),
    lambda section: section["value"]["children"][1].update(count=0),
    lambda section: section["value"]["children"][1].update(count=True),
    lambda section: section["value"]["children"][1].update(count=101),
    lambda section: section["value"]["children"][1].update(level=1),
    lambda section: section["value"]["children"][1].update(output_name="records:leaf:999"),
    lambda section: section["value"]["children"][1].update(extra="field"),
    lambda section: section["value"]["children"].append(copied(section["value"]["children"][1])),
    lambda section: section["value"]["children"][1].update(
        result_ref=copied(section["value"]["children"][0]["result_ref"]),
    ),
])
def test_malformed_indexes_fail_before_loading_any_leaf(mutate):
    store, _, manifest = save_rows({"index": index} for index in range(150))
    invalid = replace_root(store, manifest, mutate)
    with pytest.raises(ValueError):
        read_record_tree(invalid, "records", store.load, offset=0, limit=1)
    assert store.reads == ["records"]


def test_index_fanout_bound_is_checked_before_descending():
    store, _, manifest = save_rows([{"value": 1}])
    invalid = replace_root(
        store, manifest,
        lambda section: section["value"].update(
            children=section["value"]["children"] * (RECORD_INDEX_FANOUT + 1),
        ),
    )
    with pytest.raises(CollectionIntegrityError, match="fanout"):
        read_record_tree(invalid, "records", store.load)
    assert store.reads == ["records"]


def test_cycle_is_rejected_even_when_a_callback_does_not_check_its_digest():
    store, _, manifest = save_rows([{"value": 1}])
    root_ref = manifest["outputs"]["records"]["result_ref"]
    root = store.get(root_ref)
    root["value"]["children"][0]["result_ref"] = copied(root_ref)

    def unverified_json_callback(_reference):
        return copied(root)

    with pytest.raises(CollectionIntegrityError, match="cycle"):
        read_record_tree(manifest, "records", unverified_json_callback)


def test_deep_index_count_and_cross_subtree_reference_reuse_are_rejected():
    store, _, manifest = save_rows({"index": index} for index in range(10101))
    root = store.get(manifest["outputs"]["records"]["result_ref"])
    first_index = store.get(root["value"]["children"][0]["result_ref"])
    second_child = root["value"]["children"][1]
    second_index = store.get(second_child["result_ref"])
    second_index["value"]["record_count"] += 1
    second_child["result_ref"] = store.save(second_index)
    invalid = copied(manifest)
    invalid["outputs"]["records"]["result_ref"] = store.save(root)
    with pytest.raises(CollectionIntegrityError, match="count"):
        read_record_tree(invalid, "records", store.load, offset=10000, limit=1)

    second_index["value"]["record_count"] -= 1
    second_index["value"]["children"][0]["result_ref"] = first_index["value"]["children"][0]["result_ref"]
    second_child["result_ref"] = store.save(second_index)
    invalid["outputs"]["records"]["result_ref"] = store.save(root)
    with pytest.raises(CollectionIntegrityError, match="envelope"):
        read_record_tree(invalid, "records", store.load, offset=10000, limit=1)


@pytest.mark.parametrize("change", [
    {"sha256": "not-a-digest"}, {"sha256": "F" * 64},
    {"size_bytes": True}, {"size_bytes": 0}, {"size_bytes": -1},
    {"size_bytes": RECORD_PAGE_BYTES + 1}, {"storage": "http"},
    {"schema_version": True}, {"schema_version": 2}, {"chunk_count": 0},
    {"chunk_count": True}, {"path": "untrusted-storage-address"},
])
def test_invalid_root_references_fail_before_storage_access(change):
    store, _, manifest = save_rows([{"value": 1}])
    manifest["outputs"]["records"]["result_ref"].update(change)
    with pytest.raises(ValueError):
        read_record_tree(manifest, "records", store.load)
    assert store.reads == []


def test_compact_callback_references_remain_supported_without_backend_fields():
    store = JsonSections()

    def save(section):
        reference = store.save(section)
        return {field: reference[field] for field in ("sha256", "size_bytes")}

    writer = RecordTreeWriter(IDENTITY, "records", "records", save, max_result_bytes=MAX_RESULT_BYTES)
    writer.append({"exact": "value"})
    assert read_record_tree(manifest_for(writer), "records", store.load) == ([{"exact": "value"}], 1)


@pytest.mark.parametrize("offset,limit", [
    (-1, 100), (True, 100), (1.0, 100), ("0", 100), (MAX_RECORD_COUNT + 1, 100),
    (0, 0), (0, -1), (0, True), (0, 1.5), (0, "100"), (0, MAX_RECORD_COUNT + 1),
])
def test_invalid_ranges_are_not_silently_coerced(offset, limit):
    store, _, manifest = save_rows([{"index": 0}])
    with pytest.raises(ValueError, match="range"):
        read_record_tree(manifest, "records", store.load, offset=offset, limit=limit)
    assert not store.reads


def test_selective_offsets_load_only_intersecting_leaves():
    store, _, manifest = save_rows({"index": index} for index in range(10501))
    rows, total = read_record_tree(manifest, "records", store.load, offset=10317, limit=2)
    assert rows == [{"index": 10317}, {"index": 10318}]
    assert total == 10501
    assert store.reads == ["records", "records:index:1:10000", "records:leaf:10300"]
    store.reads.clear()
    rows, total = read_record_tree(manifest, "records", store.load, offset=9999, limit=4)
    assert rows == [{"index": index} for index in range(9999, 10003)]
    assert {name for name in store.reads if ":leaf:" in name} == {"records:leaf:9900", "records:leaf:10000"}
    store.reads.clear()
    assert read_record_tree(manifest, "records", store.load, offset=10501) == ([], 10501)
    assert store.reads == ["records"]
    with pytest.raises(CollectionIntegrityError, match="offset"):
        read_record_tree(manifest, "records", store.load, offset=10502)


def test_aggregate_larger_than_materialization_bound_still_streams_completely():
    payload = "x" * (100 * 1024)
    store, _, manifest = save_rows({"index": index, "payload": payload} for index in range(110))
    with pytest.raises(CollectionSizeError, match="not truncated"):
        read_record_tree(manifest, "records", store.load, limit=None)
    with pytest.raises(CollectionSizeError, match="not truncated"):
        read_record_tree(manifest, "records", store.load, limit=100)
    rows, total = read_record_tree(manifest, "records", store.load, offset=72, limit=1)
    assert rows == [{"index": 72, "payload": payload}]
    assert total == 110
    observed = 0
    for index, row in enumerate(iter_record_tree(manifest, "records", store.load)):
        assert row == {"index": index, "payload": payload}
        observed += 1
    assert observed == 110


def test_late_root_write_failure_never_yields_a_completed_descriptor():
    store = JsonSections()
    writer = writer_for(store)
    for index in range(150):
        writer.append({"index": index})
    assert len(store.writes) == 1
    store.fail_name = "records"
    with pytest.raises(OSError, match="Synthetic"):
        writer.finish()
    assert writer.descriptor is None
    assert [write["name"] for write in store.writes] == ["records:leaf:0", "records:leaf:100"]
    attempts = store.attempts
    with pytest.raises(CollectionIntegrityError, match="failed"):
        writer.finish()
    with pytest.raises(CollectionIntegrityError, match="failed"):
        writer.append({"not": "admitted"})
    assert store.attempts == attempts


def test_index_write_failure_during_append_cannot_be_recovered_as_a_prefix(monkeypatch):
    monkeypatch.setattr(collections, "RECORD_INDEX_FANOUT", 2)
    store = JsonSections()
    store.fail_name = "records:index:1:0"
    writer = writer_for(store)
    with pytest.raises(OSError):
        for index in range(200):
            writer.append({"index": index})
    assert writer.descriptor is None
    assert all(write["name"] != "records" for write in store.writes)
    with pytest.raises(CollectionIntegrityError, match="failed"):
        writer.finish()


def test_quota_includes_root_index_and_not_only_record_values():
    probe, _, _ = save_rows([{"payload": "x" * 1000}])
    total_bytes = sum(write["reference"]["size_bytes"] for write in probe.writes)
    store = JsonSections()
    writer = writer_for(store, max_result_bytes=total_bytes - 1)
    writer.append({"payload": "x" * 1000})
    with pytest.raises(CollectionSizeError, match="cumulative"):
        writer.finish()
    assert writer.descriptor is None
    assert [write["kind"] for write in store.writes] == ["records"]
    assert writer.budget.used_bytes == store.writes[0]["reference"]["size_bytes"]


def test_shared_quota_covers_collection_lineage_coverage_and_final_manifest():
    probe_budget = CollectionWriteBudget(MAX_RESULT_BYTES)
    probe_store = JsonSections()
    for name in ("records", "lineage", "coverage"):
        writer = writer_for(probe_store, name=name, budget=probe_budget)
        writer.append({"payload": "x" * 1000})
        writer.finish()
    exact_sections_bytes = probe_budget.used_bytes
    assert exact_sections_bytes == sum(write["reference"]["size_bytes"] for write in probe_store.writes)

    budget = CollectionWriteBudget(exact_sections_bytes - 1)
    store = JsonSections()
    for name in ("records", "lineage"):
        writer = writer_for(store, name=name, budget=budget, max_result_bytes=exact_sections_bytes)
        writer.append({"payload": "x" * 1000})
        writer.finish()
    coverage = writer_for(store, name="coverage", budget=budget, max_result_bytes=exact_sections_bytes)
    coverage.append({"payload": "x" * 1000})
    with pytest.raises(CollectionSizeError, match="cumulative"):
        coverage.finish()
    assert coverage.descriptor is None
    assert "coverage" not in [write["name"] for write in store.writes]
    with pytest.raises(CollectionSizeError, match="failed"):
        budget.save_section({"outputs": {}}, store.save)

    complete_budget = CollectionWriteBudget(exact_sections_bytes + 1)
    complete_store = JsonSections()
    for name in ("records", "lineage", "coverage"):
        writer = writer_for(complete_store, name=name, budget=complete_budget)
        writer.append({"payload": "x" * 1000})
        writer.finish()
    with pytest.raises(CollectionSizeError, match="cumulative"):
        complete_budget.save_section({"outputs": {}}, complete_store.save)
    assert len(complete_store.writes) == len(probe_store.writes)


def test_unknown_write_outcome_does_not_refund_the_shared_budget():
    store = JsonSections()
    budget = CollectionWriteBudget(MAX_RESULT_BYTES)

    def lost_acknowledgment(section):
        store.save(section)
        raise OSError("Synthetic acknowledgment loss.")

    writer = RecordTreeWriter(
        IDENTITY, "records", "records", lost_acknowledgment,
        max_result_bytes=MAX_RESULT_BYTES, budget=budget,
    )
    writer.append({"original": "retained but uncommitted"})
    with pytest.raises(OSError):
        writer.finish()
    assert budget.used_bytes == store.writes[0]["reference"]["size_bytes"]
    assert writer.descriptor is None
    with pytest.raises(CollectionSizeError, match="failed"):
        budget.consume(1)


def test_invalid_save_reference_cannot_complete_a_collection():
    writer = RecordTreeWriter(
        IDENTITY, "records", "records", lambda section: {"sha256": "not-a-reference", "size_bytes": 1},
        max_result_bytes=MAX_RESULT_BYTES,
    )
    writer.append({"record": "retained"})
    with pytest.raises(CollectionIntegrityError, match="digest"):
        writer.finish()
    assert writer.descriptor is None


def test_underreported_serialized_bytes_cannot_be_saved_or_read():
    store = JsonSections()

    def save_underreported(section):
        reference = store.save(section)
        reference["size_bytes"] = 1
        return reference

    writer = RecordTreeWriter(
        IDENTITY, "records", "records", save_underreported, max_result_bytes=MAX_RESULT_BYTES,
    )
    writer.append({"retained": "record"})
    with pytest.raises(CollectionIntegrityError, match="underreports"):
        writer.finish()
    assert writer.descriptor is None

    store, _, manifest = save_rows([{"retained": "record"}])
    reference = manifest["outputs"]["records"]["result_ref"]
    root = store.get(reference)
    reference["size_bytes"] = 1
    with pytest.raises(CollectionIntegrityError, match="underreports"):
        read_record_tree(manifest, "records", lambda _reference: copied(root))


def test_alternative_json_spacing_is_charged_without_assuming_callback_serialization():
    contents = {}
    total_bytes = 0

    def spaced_save(section):
        nonlocal total_bytes
        payload = json.dumps(section, ensure_ascii=True, allow_nan=False)
        digest = hashlib.sha256(payload.encode("ascii")).hexdigest()
        contents[digest] = payload
        total_bytes += len(payload)
        return {"sha256": digest, "size_bytes": len(payload)}

    writer = RecordTreeWriter(IDENTITY, "records", "records", spaced_save, max_result_bytes=MAX_RESULT_BYTES)
    for index in range(205):
        writer.append({"index": index})
    manifest = manifest_for(writer)
    assert writer.budget.used_bytes == writer.written_bytes == total_bytes
    assert sum(1 for _ in iter_record_tree(
        manifest, "records", lambda reference: json.loads(contents[reference["sha256"]]),
    )) == 205


@pytest.mark.parametrize("kind", [None, [], {}, True, "evidence", "text"])
def test_invalid_collection_kinds_fail_cleanly(kind):
    store = JsonSections()
    with pytest.raises(ValueError, match="records or document_results"):
        writer_for(store, kind=kind)
    store, _, manifest = save_rows([{"value": 1}])
    manifest["outputs"]["records"]["kind"] = kind
    with pytest.raises(CollectionIntegrityError, match="valid record tree"):
        read_record_tree(manifest, "records", store.load)
    assert not store.reads


def test_root_cannot_claim_more_records_than_its_bounded_children_can_hold():
    store, _, manifest = save_rows([{"value": 1}])
    invalid = replace_root(
        store, manifest,
        lambda section: section["value"].update(record_count=RECORD_PAGE_SIZE * RECORD_INDEX_FANOUT + 1),
    )
    invalid["outputs"]["records"]["record_count"] = RECORD_PAGE_SIZE * RECORD_INDEX_FANOUT + 1
    with pytest.raises(CollectionIntegrityError, match="count"):
        read_record_tree(invalid, "records", store.load)
    assert store.reads == ["records"]


def test_budget_can_commit_the_final_manifest_only_after_all_sections():
    store = JsonSections()
    budget = CollectionWriteBudget(MAX_RESULT_BYTES)
    writer = writer_for(store, budget=budget)
    writer.append({"value": "complete"})
    manifest = manifest_for(writer)
    final_reference = budget.save_section(manifest, store.save)
    assert store.writes[-1]["name"] is None
    assert store.get(final_reference) == manifest
    assert budget.used_bytes == sum(write["reference"]["size_bytes"] for write in store.writes)


def test_writer_buffers_do_not_grow_with_all_records_or_leaf_references():
    writes = 0
    maximum_section_bytes = 0

    def discard_after_json_copy(section):
        nonlocal writes, maximum_section_bytes
        payload = encoded(copied(section))
        writes += 1
        maximum_section_bytes = max(maximum_section_bytes, len(payload))
        return {"sha256": hashlib.sha256(payload.encode("ascii")).hexdigest(), "size_bytes": len(payload)}

    writer = RecordTreeWriter(
        IDENTITY, "records", "records", discard_after_json_copy, max_result_bytes=MAX_RESULT_BYTES,
    )
    peak_entries = 0
    for index in range(100501):
        writer.append({"index": index})
        assert writer.buffered_record_count < RECORD_PAGE_SIZE
        assert writer.buffered_record_bytes < RECORD_PAGE_BYTES
        assert writer.index_level_count <= MAX_RECORD_TREE_LEVEL
        assert all(len(entries) < RECORD_INDEX_FANOUT for entries in writer._levels)
        peak_entries = max(peak_entries, writer.buffered_index_entries)
    descriptor = writer.finish()
    assert descriptor["record_count"] == 100501
    assert writes > 1000
    assert peak_entries < 2 * RECORD_INDEX_FANOUT
    assert maximum_section_bytes <= RECORD_PAGE_BYTES
    assert writer.buffered_record_count == writer.buffered_index_entries == 0


def test_business_key_type_empty_and_duplicate_semantics_match_existing_validation():
    rows = [
        {"id": 1}, {"id": "1"}, {"id": 1}, {"id": "1"},
        {}, {"id": None}, {"id": True}, {"id": 1.0},
        {"id": ""}, {"id": " "}, {"id": {"nested": 1}}, {"id": [1]},
        {"id": "  kept "}, {"id": "kept"}, {"id": "  kept "},
    ]
    store = JsonSections()
    writer = writer_for(store)
    validator = RecordIdentityValidator("id", writer, store.load)
    for row in rows:
        writer.append(row)
        validator.add(row)
    assert validator.finish() == {"missing_identity_count": 8, "duplicate_identity_count": 3}
    manifest = manifest_for(writer)
    assert read_record_tree(manifest, "records", store.load, limit=None) == (rows, len(rows))
    key_manifest = {
        "identity": IDENTITY, "contract_version": "workflow-result-v2",
        "outputs": {validator.output_name: validator.index_descriptor},
    }
    keys = list(iter_record_tree(key_manifest, validator.output_name, store.load))
    assert len(keys) == 7
    assert keys == sorted(keys, key=lambda row: row["key"])
    assert writer.budget.used_bytes == sum(write["reference"]["size_bytes"] for write in store.writes)


def test_business_key_merges_detect_duplicates_across_all_runs_with_bounded_buffers():
    store = JsonSections()
    writer = writer_for(store)
    validator = RecordIdentityValidator("id", writer, store.load)
    count = 10017
    unique_count = 1023
    for index in range(count):
        row = {"id": f"key-{index % unique_count}", "ordinal": index}
        writer.append(row)
        validator.add(row)
        assert validator.buffered_key_count < RECORD_PAGE_SIZE
        assert validator.buffered_key_bytes < RECORD_PAGE_BYTES
        assert validator.buffered_run_count <= MAX_IDENTITY_RUN_LEVELS
        assert len(validator._runs) <= MAX_IDENTITY_RUN_LEVELS
    assert validator.finish() == {
        "missing_identity_count": 0, "duplicate_identity_count": count - unique_count,
    }
    assert validator.index_descriptor["record_count"] == count
    assert validator.buffered_run_count == validator.buffered_key_count == 0
    before = len(store.writes)
    assert validator.finish()["duplicate_identity_count"] == count - unique_count
    assert len(store.writes) == before
    with pytest.raises(CollectionIntegrityError, match="already finished"):
        validator.add({"id": "too-late"})
    manifest = manifest_for(writer)
    observed = 0
    for index, row in enumerate(iter_record_tree(manifest, "records", store.load)):
        assert row == {"id": f"key-{index % unique_count}", "ordinal": index}
        observed += 1
    assert observed == count


def test_default_contributor_ordinal_identity_needs_no_global_index_or_deduplication():
    store = JsonSections()
    writer = writer_for(store)
    validator = RecordIdentityValidator(None, writer, store.load)
    for _ in range(501):
        row = {"same": "payload"}
        writer.append(row)
        validator.add(row)
    assert validator.finish() == {"missing_identity_count": 0, "duplicate_identity_count": 0}
    assert validator.index_descriptor is None
    assert validator.buffered_run_count == validator.buffered_key_count == 0
    manifest = manifest_for(writer)
    assert sum(1 for _ in iter_record_tree(manifest, "records", store.load)) == 501
    assert all(":identity" not in write["name"] for write in store.writes)


@pytest.mark.parametrize("rows,missing", [([], 0), ([{}, {"id": None}], 2)])
def test_empty_business_key_index_is_valid_and_missing_records_are_counted(rows, missing):
    store = JsonSections()
    writer = writer_for(store)
    validator = RecordIdentityValidator("id", writer, store.load)
    for row in rows:
        validator.add(row)
    assert validator.finish() == {"missing_identity_count": missing, "duplicate_identity_count": 0}
    assert validator.index_descriptor["record_count"] == 0


def test_large_business_keys_use_singleton_pages_without_an_unbounded_key_buffer():
    store = JsonSections()
    writer = writer_for(store)
    validator = RecordIdentityValidator("id", writer, store.load)
    for _ in range(2):
        row = {"id": "\u00e9" * 30000}
        writer.append(row)
        validator.add(row)
        assert validator.buffered_key_count == 0
    assert validator.finish() == {"missing_identity_count": 0, "duplicate_identity_count": 1}
    assert validator.index_descriptor["record_count"] == 2


@pytest.mark.parametrize("transport_form", [False, True])
def test_business_key_sidecar_is_charged_to_the_original_collection_budget(transport_form):
    store = JsonSections()
    budget = CollectionWriteBudget(10000)
    writer = writer_for(store, budget=budget)
    validator = (
        RecordIdentityValidator(
            "id", IDENTITY, store.save, store.load, max_result_bytes=MAX_RESULT_BYTES, budget=budget,
        )
        if transport_form else RecordIdentityValidator("id", writer, store.load)
    )
    for index in range(20):
        row = {"id": f"key-{index}-" + "x" * 100}
        writer.append(row)
        validator.add(row)
    writer.finish()
    with pytest.raises(CollectionSizeError, match="cumulative"):
        validator.finish()
    assert validator.index_descriptor is None
    assert writer.budget is budget
    with pytest.raises(CollectionIntegrityError, match="failed"):
        validator.finish()


def test_business_key_final_index_write_failure_does_not_report_success():
    store = JsonSections()
    writer = writer_for(store)
    validator = RecordIdentityValidator("id", writer, store.load)
    validator.add({"id": "retained"})
    store.fail_name = validator.output_name
    with pytest.raises(OSError):
        validator.finish()
    assert validator.index_descriptor is None
    with pytest.raises(CollectionIntegrityError, match="failed"):
        validator.finish()


@pytest.mark.parametrize("contract_version", ["workflow-result-v2", "workflow-frozen-items-v1"])
@pytest.mark.parametrize("kind,name", [("records", "items"), ("document_results", "documents")])
def test_transport_validator_and_frozen_item_contract_share_the_exact_envelope(contract_version, kind, name):
    store = JsonSections()
    budget = CollectionWriteBudget(MAX_RESULT_BYTES)
    writer = writer_for(store, name=name, kind=kind, budget=budget, contract_version=contract_version)
    validator = RecordIdentityValidator(
        "id", IDENTITY, store.save, store.load, max_result_bytes=MAX_RESULT_BYTES,
        budget=budget, contract_version=contract_version,
    )
    rows = [{"id": f"key-{index % 137}", "value": index} for index in range(205)] + [{}]
    for row in rows:
        writer.append(row)
        validator.add(row)
    assert validator.finish() == {"missing_identity_count": 1, "duplicate_identity_count": 68}
    assert validator.output_name == "identity"
    manifest = manifest_for(writer)
    assert read_record_tree(manifest, name, store.load, limit=None) == (rows, 206)
    for payload in store.contents.values():
        section = json.loads(payload)
        assert set(section) == {"contract_version", "producer", "output_name", "kind", "value"}
        assert section["contract_version"] == contract_version
        assert section["producer"] == IDENTITY
    assert budget.used_bytes == sum(write["reference"]["size_bytes"] for write in store.writes)
    key_manifest = {
        "identity": IDENTITY, "contract_version": contract_version,
        "outputs": {validator.output_name: validator.index_descriptor},
    }
    assert sum(1 for _ in iter_record_tree(key_manifest, validator.output_name, store.load)) == 205
    if contract_version == "workflow-frozen-items-v1":
        manifest["contract_version"] = "workflow-result-v2"
        with pytest.raises(CollectionIntegrityError, match="envelope"):
            read_record_tree(manifest, name, store.load)


def test_transport_validator_keywords_allow_named_sidecars_and_disabled_identity():
    store = JsonSections()
    budget = CollectionWriteBudget(MAX_RESULT_BYTES)
    validator = RecordIdentityValidator(
        identity_field=None, identity=IDENTITY, save_section=store.save, load_section=store.load,
        max_result_bytes=MAX_RESULT_BYTES, budget=budget, output_name="business_keys",
    )
    validator.add({"id": "duplicate"})
    validator.add({"id": "duplicate"})
    assert validator.finish() == {"missing_identity_count": 0, "duplicate_identity_count": 0}
    assert validator.output_name == "business_keys"
    assert validator.index_descriptor is None
    assert not store.writes
    assert budget.used_bytes == 0


def test_writer_validator_supports_keyword_reader_and_inherits_frozen_contract():
    store = JsonSections()
    writer = writer_for(store, name="items", contract_version="workflow-frozen-items-v1")
    validator = RecordIdentityValidator(
        "id", writer, load_section=store.load, budget=writer.budget,
        max_result_bytes=writer.max_result_bytes, contract_version=writer.contract_version,
    )
    validator.add({"id": "item-0"})
    assert validator.finish() == {"missing_identity_count": 0, "duplicate_identity_count": 0}
    assert validator.output_name == "items:identity"
    assert all(json.loads(payload)["contract_version"] == "workflow-frozen-items-v1"
               for payload in store.contents.values())


@pytest.mark.parametrize("overrides", [
    {"budget": CollectionWriteBudget(MAX_RESULT_BYTES)},
    {"max_result_bytes": MAX_RESULT_BYTES - 1},
    {"contract_version": "workflow-frozen-items-v1"},
])
def test_writer_validator_rejects_inconsistent_budget_or_contract_overrides(overrides):
    store = JsonSections()
    writer = writer_for(store)
    with pytest.raises(ValueError, match="same writer"):
        RecordIdentityValidator("id", writer, store.load, **overrides)
    assert not store.writes


def test_transport_validator_requires_quota_and_unambiguous_callbacks():
    store = JsonSections()
    with pytest.raises(ValueError, match="explicit byte quota"):
        RecordIdentityValidator("id", IDENTITY, store.save, store.load)
    with pytest.raises(ValueError, match="section reader"):
        RecordIdentityValidator("id", IDENTITY, store.save, max_result_bytes=MAX_RESULT_BYTES)
    writer = writer_for(store)
    with pytest.raises(ValueError, match="only one section reader"):
        RecordIdentityValidator("id", writer, store.save, store.load)
    assert not store.writes


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
