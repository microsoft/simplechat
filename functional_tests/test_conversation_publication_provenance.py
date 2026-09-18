# test_conversation_publication_provenance.py
#!/usr/bin/env python3
"""
Functional tests for safe source approval and historical publication provenance.
Version: 0.261.029
Implemented in: 0.261.029

The real memory store accepts only bounded typed decision/audit references from
its injected publication authorizer. Capture and later publication requests stay
distinct. Expiry is checked for new publication, never for later snapshot reads.
No identity, token, settings, or config service is imported by the memory layer.
"""

from dataclasses import asdict, replace
from datetime import timedelta
import json

import pytest

from test_conversation_working_memory import (
    MemoryAuthorizationError,
    MemoryHarness,
    MemoryLimitError,
)
from functions_conversation_memory import MAX_APPROVAL_REFS, PublicationApprovalReference


def source_reference(harness, **changes):
    reference = PublicationApprovalReference(
        source="spo", approval_id="approval-share", decision_event_id="decision-123",
        audit_id="grant-use-456", effective_duration="today",
        acknowledged_at=harness.now.isoformat(),
        expires_at=(harness.now + timedelta(hours=1)).isoformat(),
        generation=3,
    )
    return replace(reference, **changes)


def complete_capture(harness):
    run_id, source = harness.run(2)
    harness.store.complete_run(harness.context, run_id)
    return run_id, source


def test_source_approval_projection_and_separate_publication_request_are_persisted():
    harness = MemoryHarness()
    run_id, source = complete_capture(harness)
    ctx = replace(harness.context, request_id="later-shared-publication")
    reference = source_reference(harness)
    harness.grant_override = {
        "source_approvals": (reference,), "publication_request_id": ctx.request_id,
    }
    published = harness.store.publish(ctx, run_id, grant_context=harness.grant_context)
    page = harness.store.read_evidence_range(harness.reader, run_id, source["evidence_id"])
    publication = published["publication"]

    assert published["request_id"] == "request-1"
    assert publication["capture_request_id"] == "request-1"
    assert publication["publication_request_id"] == "later-shared-publication"
    assert publication["source_approvals"] == [asdict(reference)]
    assert publication["principal_id"] == "owner"
    assert page["source"]["capture"] == source["capture"]
    assert page["source"]["source"]["version"] == source["source"]["version"]
    encoded = json.dumps(publication)
    assert "access_token" not in encoded
    assert "action_configs" not in encoded
    assert "downloadUrl" not in encoded


def test_legacy_grant_constructors_remain_valid_and_inherit_only_known_current_request():
    harness = MemoryHarness()
    first_run, _ = complete_capture(harness)
    ctx = replace(harness.context, request_id="current-publication-request")
    published = harness.store.publish(ctx, first_run, grant_context=harness.grant_context)
    second_run, _ = complete_capture(harness)
    legacy = harness.store.publish(harness.context, second_run, grant_context=harness.grant_context)

    assert published["publication"]["publication_request_id"] == ctx.request_id
    assert published["publication"]["source_approvals"] == []
    assert legacy["publication"]["publication_request_id"] is None
    assert legacy["publication"]["capture_request_id"] == "request-1"


def test_later_published_reads_do_not_revalidate_source_expiry_or_generation():
    harness = MemoryHarness()
    run_id, source = complete_capture(harness)
    reference = source_reference(harness)
    harness.grant_override = {"source_approvals": (reference,)}
    harness.store.publish(harness.context, run_id, grant_context=harness.grant_context)
    harness.now += timedelta(days=10)

    def no_new_source_grant(*args, **kwargs):
        raise AssertionError("Published snapshot reads cannot request a new source grant.")

    harness.store.authorize_publish = no_new_source_grant
    current_reader = replace(harness.reader, request_id="new-reader-request")
    manifest = harness.store.read_manifest(current_reader, run_id)
    page = harness.store.read_evidence_range(current_reader, run_id, source["evidence_id"])

    assert manifest["publication"]["source_approvals"][0]["generation"] == 3
    assert manifest["publication"]["source_approvals"][0]["expires_at"] == reference.expires_at
    assert len(page["chunks"]) == 2


@pytest.mark.parametrize("overrides", [
    {"approval_id": "another-approval"},
    {"acknowledged_at": "2026-09-18T00:00:00+00:00", "expires_at": "2026-09-19T00:00:00+00:00"},
    {"acknowledged_at": "2026-09-16T00:00:00+00:00", "expires_at": "2026-09-17T00:00:00+00:00"},
])
def test_new_publication_rejects_unbound_or_not_current_source_provenance(overrides):
    harness = MemoryHarness()
    run_id, _ = complete_capture(harness)
    harness.grant_override = {"source_approvals": (source_reference(harness, **overrides),)}
    with pytest.raises(MemoryAuthorizationError):
        harness.store.publish(harness.context, run_id, grant_context=harness.grant_context)
    unpublished = harness.store.read_manifest(harness.context, run_id)
    assert unpublished["publication"] is None


def test_current_publication_request_cannot_replace_original_capture_request_binding():
    harness = MemoryHarness()
    run_id, _ = complete_capture(harness)
    ctx = replace(harness.context, request_id="later-request")
    harness.grant_override = {"request_id": ctx.request_id, "publication_request_id": ctx.request_id}
    with pytest.raises(MemoryAuthorizationError):
        harness.store.publish(ctx, run_id, grant_context=harness.grant_context)
    harness.grant_override = {"publication_request_id": "unrelated-request"}
    with pytest.raises(MemoryAuthorizationError):
        harness.store.publish(ctx, run_id, grant_context=harness.grant_context)


def test_source_provenance_cannot_be_a_raw_decision_or_oversized_mutable_collection():
    harness = MemoryHarness()
    run_id, _ = complete_capture(harness)
    reference = source_reference(harness)
    for values, exception in (
        (({"source": "spo", "allowed": True, "access_token": "do-not-persist"},), MemoryAuthorizationError),
        ([reference], MemoryLimitError),
        ((reference,) * (MAX_APPROVAL_REFS + 1), MemoryLimitError),
        ((reference, reference), MemoryAuthorizationError),
    ):
        harness.grant_override = {"source_approvals": values}
        with pytest.raises(exception):
            harness.store.publish(harness.context, run_id, grant_context=harness.grant_context)
    assert not any(b"do-not-persist" in record.data for record in harness.transport.blobs.values())


@pytest.mark.parametrize("overrides", [
    {"source": "../source"}, {"approval_id": "https://provider/secret"},
    {"decision_event_id": "x" * 201}, {"audit_id": "not\nan\nid"},
    {"generation": -1}, {"generation": True}, {"effective_duration": "no"},
    {"effective_duration": "today", "expires_at": None},
    {"expires_at": "2026-09-16T12:00:00+00:00"},
])
def test_source_provenance_rejects_invalid_fields_and_nonaffirmative_decisions(overrides):
    harness = MemoryHarness()
    with pytest.raises(ValueError):
        source_reference(harness, **overrides)


def test_private_sharing_not_required_result_is_not_a_publication_grant():
    harness = MemoryHarness()
    run_id, _ = complete_capture(harness)
    harness.store.authorize_publish = lambda ctx, run, context: {
        "allowed": True, "source": "spo", "sharing_required": False,
    }
    with pytest.raises(MemoryAuthorizationError):
        harness.store.publish(harness.context, run_id, grant_context=harness.grant_context)
    stored = harness.store.read_manifest(harness.context, run_id)
    assert stored["publication"] is None


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
