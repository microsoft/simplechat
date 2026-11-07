# test_content_screening_checkpoints.py
"""
Functional tests for private model-window checkpoints.
Version: 0.261.106
Implemented in: 0.261.106

Completed windows are immutable, revision/policy/check bound, and available only
to the active scan lease. Sensitive evidence is kept out of Cosmos metadata.
"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest
import json

from test_content_screening_lifecycle import MemoryRepository, MemoryStorage
from content_screening.checkpoints import ModelWindowCheckpoints
from content_screening.contracts import ContentUnit, ScreeningConflictError, Subject, content_fingerprint, hash_payload
from content_screening.policies import compose_policy, default_policy


class CheckpointRepository(MemoryRepository):
    def get(self, record_id, partition_key):
        record = self.records.get(record_id)
        return deepcopy(record) if record and record.get("partition_key") == partition_key else None


@pytest.fixture
def checkpoint_runtime():
    repository, storage = CheckpointRepository(), MemoryStorage()
    subject = Subject("personal", "owner", "document", "1")
    raw = default_policy()
    raw["enabled"] = True
    raw["ai"].update({"enabled": True, "model_selection": {"endpoint_id": "endpoint", "model_id": "model"}})
    policy = compose_policy(raw)
    check = policy["ai_checks"][0]
    content_hash = content_fingerprint([ContentUnit("unit", "source")])
    scan = repository.create({
        "id": "scan", "partition_key": "scan", "kind": "scan",
        "subject": subject.to_dict(), "state": "scanning",
        "content_fingerprint": content_hash, "policy": policy, "policy_fingerprint": hash_payload(policy),
        "lease": {"owner": "worker", "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()},
    })
    repository.document["content_screening"] = {
        "state": "scanning", "scan_id": "scan", "source_revision": "1",
        "content_fingerprint": content_hash,
    }
    store = ModelWindowCheckpoints(subject, "scan", check, "worker", repository=repository, storage=storage)
    return repository, storage, subject, check, store


def test_checkpoint_is_immutable_and_keeps_evidence_private(checkpoint_runtime):
    repository, storage, _subject, _check, store = checkpoint_runtime
    payload = {"window_id": "window", "findings": [{"evidence": "PRIVATE_CANARY"}]}
    assert store.get("window") is None
    store.put("window", payload)
    store.put("window", payload)
    assert store.get("window") == payload
    records = [record for record in repository.records.values() if record.get("kind") == "model_window"]
    assert len(records) == 1
    assert "PRIVATE_CANARY" not in repr(records)
    assert "PRIVATE_CANARY" in repr(storage.items)


def test_different_response_cannot_overwrite_a_completed_window(checkpoint_runtime):
    _repository, _storage, _subject, _check, store = checkpoint_runtime
    store.put("window", {"matched": True})
    with pytest.raises(ScreeningConflictError):
        store.put("window", {"matched": False})
    assert store.get("window") == {"matched": True}


def test_stale_lease_cannot_read_or_write_checkpoints(checkpoint_runtime):
    repository, _storage, _subject, _check, store = checkpoint_runtime
    scan = repository.get_scan("scan")
    repository.replace({**scan, "lease": {**scan["lease"], "owner": "replacement-worker"}}, scan["_etag"])
    with pytest.raises(ScreeningConflictError):
        store.get("window")
    with pytest.raises(ScreeningConflictError):
        store.put("window", {"matched": False})


def test_policy_or_source_changes_do_not_borrow_completed_windows(checkpoint_runtime):
    repository, _storage, _subject, _check, store = checkpoint_runtime
    store.put("window", {"matched": True})
    scan = repository.get_scan("scan")
    repository.replace({**scan, "content_fingerprint": hash_payload("replacement-source")}, scan["_etag"])
    with pytest.raises(ScreeningConflictError):
        store.get("window")


def test_transient_limits_do_not_change_window_identity(checkpoint_runtime):
    repository, storage, subject, check, store = checkpoint_runtime
    store.put("window", {"matched": True})
    resumed = ModelWindowCheckpoints(
        subject, "scan", {**check, "limits": {"max_runtime_seconds": 1}},
        "worker", repository=repository, storage=storage,
    )
    assert resumed.get("window") == {"matched": True}


def test_evidence_tampering_never_becomes_a_cache_miss(checkpoint_runtime):
    repository, storage, _subject, _check, store = checkpoint_runtime
    store.put("window", {"matched": True})
    record = next(record for record in repository.records.values() if record.get("kind") == "model_window")
    storage.items[record["result_ref"]["key"]] = {"matched": False}
    with pytest.raises(ScreeningConflictError):
        store.get("window")


def test_completed_window_finding_latches_review_before_the_full_scan_finishes(checkpoint_runtime):
    repository, _storage, _subject, _check, store = checkpoint_runtime
    store.put("window", {"result": json.dumps({
        "window_id": "window", "results": [{"matched": True, "findings": []}],
    })})
    assert repository.get_scan("scan")["review_required"] is True
    assert repository.document["content_screening"]["review_required"] is True
    assert repository.document["content_screening"]["state"] == "scanning"
