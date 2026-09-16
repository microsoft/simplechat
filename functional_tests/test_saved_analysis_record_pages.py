# test_saved_analysis_record_pages.py
"""
Functional tests for immutable complete-record pages.
Version: 0.261.107
Implemented in: 0.261.107

Large records and evidence use the existing result store without loading
unrelated pages or substituting an index for required model input.
"""

from copy import deepcopy

import pytest

from test_support.app_stubs import import_app_module
from test_workflow_result_contract import RUN_ID, WORKFLOW, SerializedSections


results = import_app_module("functions_workflow_results")


def envelope(count=500, width=1200):
    return {
        "contract_version": results.WORKFLOW_RESULT_CONTRACT_VERSION,
        "identity": {"workflow_id": WORKFLOW["id"], "run_id": RUN_ID, "task_id": "analyze", "attempt": 1},
        "analysis_access": {"version": results.ANALYSIS_SOURCE_ACCESS_VERSION, "sources": []},
        "authoritative_output": "records",
        "outputs": {
            "records": {"kind": "records", "value": [
                {"record_id": f"record-{index}", "values": {"finding": "x" * width, "position": index}}
                for index in range(count)
            ]},
        },
        "presentation": {"summary": "A bounded overview."},
        "diagnostics": {},
    }


def save(value, store, **kwargs):
    return results.persist_result_sections(
        value, lambda data: store.save(WORKFLOW, RUN_ID, "analyze", data), **kwargs
    )


def loader(store):
    return lambda reference: store.load(WORKFLOW, RUN_ID, "analyze", reference)


def test_a_range_loads_only_its_complete_record_pages():
    store = SerializedSections()
    value = envelope()
    manifest, reference = save(value, store)
    assert manifest["outputs"]["records"]["storage_kind"] == "record_pages"
    page, total = results.read_result_records(manifest, "records", loader(store), offset=250, limit=25)
    assert total == 500
    assert page == value["outputs"]["records"]["value"][250:275]
    assert len(store.reads) <= 3


def test_full_consumption_and_iteration_preserve_every_record():
    store = SerializedSections()
    value = envelope()
    manifest, _ = save(value, store)
    full, total = results.read_result_records(manifest, "records", loader(store))
    streamed = list(results.iter_result_records(manifest, "records", loader(store)))
    assert full == streamed == value["outputs"]["records"]["value"]
    assert total == 500
    assert len({row["record_id"] for row in full}) == total


def test_small_results_keep_the_existing_single_section_shape():
    store = SerializedSections()
    value = envelope(count=10, width=10)
    manifest, _ = save(value, store)
    assert "storage_kind" not in manifest["outputs"]["records"]
    rows, total = results.read_result_records(manifest, "records", loader(store))
    assert rows == value["outputs"]["records"]["value"]
    assert total == 10


def test_evidence_uses_the_same_bounded_collection_reader():
    store = SerializedSections()
    value = envelope()
    value["outputs"] = {"evidence": {
        "kind": "evidence",
        "value": [{"evidence_id": f"evidence-{index}", "quote": "Source passage."} for index in range(500)],
    }}
    manifest, _ = save(value, store)
    page, total = results.read_result_records(manifest, "evidence", loader(store), offset=100, limit=3)
    assert [entry["evidence_id"] for entry in page] == ["evidence-100", "evidence-101", "evidence-102"]
    assert total == 500


def test_missing_or_reordered_page_ranges_fail_instead_of_losing_records():
    store = SerializedSections()
    manifest, _ = save(envelope(), store)
    index = loader(store)(manifest["outputs"]["records"]["result_ref"])
    index["value"]["pages"][1]["offset"] += 1
    changed = deepcopy(manifest)
    changed["outputs"]["records"]["result_ref"] = store.save(WORKFLOW, RUN_ID, "analyze", index)
    with pytest.raises(ValueError, match="gap"):
        results.read_result_records(changed, "records", loader(store), offset=0, limit=25)


def test_paging_cannot_bypass_the_logical_result_quota():
    store = SerializedSections()
    with pytest.raises(ValueError, match="configured size limit"):
        save(envelope(), store, max_result_bytes=20000)
    assert store.contents == {}


def test_large_collections_require_batched_consumption_not_a_silent_preview():
    store = SerializedSections()
    value = envelope(width=20000)
    manifest, _ = save(value, store)
    with pytest.raises(ValueError, match="explicit record batches"):
        results.read_result_records(manifest, "records", loader(store))
    page, total = results.read_result_records(manifest, "records", loader(store), offset=490, limit=2)
    assert page == value["outputs"]["records"]["value"][490:492]
    assert total == 500


def test_split_sections_cannot_multiply_the_logical_result_quota():
    store = SerializedSections()
    value = envelope(count=5, width=300)
    value["outputs"]["evidence"] = {
        "kind": "evidence", "value": [{"evidence_id": "evidence-1", "text": "x" * 1500}],
    }
    with pytest.raises(ValueError, match="configured size limit"):
        save(value, store, max_result_bytes=3000)
    assert store.contents == {}


def test_manifest_count_must_agree_with_its_record_index():
    store = SerializedSections()
    manifest, _ = save(envelope(), store)
    manifest["outputs"]["records"]["record_count"] += 1
    with pytest.raises(ValueError, match="index is invalid"):
        results.read_result_records(manifest, "records", loader(store), offset=0, limit=2)
