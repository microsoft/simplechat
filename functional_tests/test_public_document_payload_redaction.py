# test_public_document_payload_redaction.py
"""
Functional test for screening-toggle-independent document payload redaction.
Version: 0.261.131
Implemented in: 0.261.131

``public_document_payload`` is the serializer behind the document list/detail
APIs. Redaction must be a property of the field, not of whether the document
carries a content screening marker, so a deployment with screening disabled
cannot return blob paths, SAS URLs, provenance, or Cosmos internals.
"""

import sys
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parents[1] / "application" / "single_app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from content_screening.access import (  # noqa: E402
    GENERATED_ARTIFACT_REQUEST_FIELDS,
    PRIVATE_DOCUMENT_FIELDS,
    is_public_document_field,
    public_document_payload,
)
from content_screening.contracts import SCREENING_FIELD  # noqa: E402

sys.path.append(str(Path(__file__).resolve().parent))
from test_support.versioning import assert_app_version_at_least  # noqa: E402


SECRET_FIELDS = {
    "blob_path": "group-a/family/doc-1/q4.pdf",
    "archived_blob_path": "group-a/family/doc-1/superseded.pdf",
    "blob_container": "group-documents",
    "blob_etag": "0x8DABCDEF",
    "blob_url": "https://acct.blob.core.windows.net/group-documents/q4.pdf",
    "sas_url": "https://acct.blob.core.windows.net/group-documents/q4.pdf?sig=SECRET",
    "download_url": "https://acct.blob.core.windows.net/group-documents/q4.pdf",
    "source_ref": "canonical/doc-1",
    "canonical_ref": "canonical/doc-1/units",
    "original_blob_path": "group-a/original/q4.pdf",
    "screening_provenance": {"scan_id": "internal-scan"},
    "group_document_projection_writer": {"operation_id": "op-1"},
    "group_document_collaboration_operation": {"operation_id": "op-1"},
    "generated_artifact_publication_binding": {"source": "conversation-1"},
    "generated_artifact_publication_receipt_id": "receipt-1",
    "generated_artifact_source_conversation_id": "conversation-1",
    "generated_artifact_source_message_id": "message-1",
    "generated_artifact_source_blob_container": "conversation-artifacts",
    "generated_artifact_source_blob_path": "user-1/conversation-1/generated/chart.png",
    "document_share_details": {"groups": {"group-b": {"approval_status": "approved"}}},
    "_rid": "RID==",
    "_self": "dbs/db/colls/docs/docs/doc-1",
    "_etag": '"0x8D9"',
    "_ts": 1727000000,
}

SAFE_FIELDS = {
    "id": "doc-1",
    "document_id": "doc-1",
    "file_name": "q4.pdf",
    "title": "Q4 results",
    "group_id": "group-a",
    "version": 3,
}


def test_version_is_at_least_the_implementing_release():
    assert_app_version_at_least("0.261.131")


def test_unscreened_document_never_serializes_private_fields():
    """A deployment with screening disabled must redact exactly as much."""
    payload = public_document_payload({**SAFE_FIELDS, **SECRET_FIELDS})

    leaked = sorted(set(payload) & set(SECRET_FIELDS))
    assert leaked == [], f"unscreened payload leaked private fields: {leaked}"
    assert set(payload) == set(SAFE_FIELDS)
    assert payload["file_name"] == "q4.pdf"


@pytest.mark.parametrize("field", sorted(SECRET_FIELDS))
def test_each_private_field_is_redacted_without_a_marker(field):
    payload = public_document_payload({**SAFE_FIELDS, field: SECRET_FIELDS[field]})

    assert field not in payload


def test_redaction_does_not_depend_on_the_screening_marker():
    """The unscreened payload may never be a superset of the screened one."""
    document = {**SAFE_FIELDS, **SECRET_FIELDS}
    screened = {
        **document,
        SCREENING_FIELD: {
            "state": "cleared", "scan_id": "scan-1", "content_fingerprint": "fp-1",
        },
    }

    unscreened_keys = set(public_document_payload(document))
    screened_keys = set(public_document_payload(screened))

    assert not (unscreened_keys - screened_keys) & set(SECRET_FIELDS)
    assert not any(key.startswith("_") for key in unscreened_keys)
    assert not any(key.startswith("screening_") for key in unscreened_keys)


def test_every_private_field_is_rejected_by_the_shared_predicate():
    """The predicate is the single rule both payload branches must share."""
    assert [field for field in PRIVATE_DOCUMENT_FIELDS if is_public_document_field(field)] == []
    assert not is_public_document_field(SCREENING_FIELD)
    assert not is_public_document_field("_ts")
    assert not is_public_document_field("screening_provenance")
    assert is_public_document_field("file_name")


def test_collaboration_state_is_never_serialized_into_a_document_payload():
    """M2C sharing state and artifact sources must not ride along on a document.

    ``_project_group_document`` used to pop these itself, which meant any other
    caller of ``public_document_payload`` — including the group document detail
    endpoint — still emitted them.
    """
    collaboration_fields = {
        "document_share_details", "group_document_collaboration_operation",
        "generated_artifact_publication_receipt_id",
        "generated_artifact_source_conversation_id", "generated_artifact_source_message_id",
        "generated_artifact_source_blob_container", "generated_artifact_source_blob_path",
    }
    assert collaboration_fields <= PRIVATE_DOCUMENT_FIELDS

    payload = public_document_payload({
        **SAFE_FIELDS, **{field: SECRET_FIELDS[field] for field in collaboration_fields},
    })

    assert set(payload) == set(SAFE_FIELDS)


def test_group_projection_does_not_keep_its_own_privacy_pop_list():
    """Privacy belongs in PRIVATE_DOCUMENT_FIELDS, not in one projection."""
    reads_source = (APP_DIR / "functions_group_document_reads.py").read_text(encoding="utf-8")

    for field in ("document_share_details", "generated_artifact_source_blob_path",
                  "generated_artifact_publication_receipt_id"):
        assert f'"{field}"' not in reads_source, (
            f"{field} is redacted only in functions_group_document_reads.py; add it to "
            "PRIVATE_DOCUMENT_FIELDS so every caller of public_document_payload is covered"
        )


def test_share_rosters_stay_serializable_for_the_surfaces_that_render_them():
    """`shared_user_ids` and `shared_group_ids` must NOT be globally private.

    Live UI reads both straight off the document payload to render share
    status and share counts: V2's DocumentDetailsPane, the legacy personal
    workspace scripts, and the legacy group workspace template. Marking them
    private silently turns every share badge into 0.

    Per-audience narrowing belongs in the projection that knows the audience —
    `_project_group_document` already rewrites `shared_group_ids` for
    non-owner-managers — not in the global redaction set.
    """
    assert "shared_user_ids" not in PRIVATE_DOCUMENT_FIELDS
    assert "shared_group_ids" not in PRIVATE_DOCUMENT_FIELDS
    assert is_public_document_field("shared_user_ids")
    assert is_public_document_field("shared_group_ids")

    payload = public_document_payload({
        **SAFE_FIELDS,
        "shared_user_ids": ["user-2,approved"],
        "shared_group_ids": ["group-b,approved"],
    })

    assert payload["shared_user_ids"] == ["user-2,approved"]
    assert payload["shared_group_ids"] == ["group-b,approved"]


def test_recomputed_action_hints_are_never_served_from_storage():
    """A stored copy is always stale; the projection re-adds fresh values."""
    payload = public_document_payload({
        **SAFE_FIELDS,
        "document_actions": ["delete"],
        "document_collaboration_actions": ["share"],
    })

    assert "document_actions" not in payload
    assert "document_collaboration_actions" not in payload


def test_non_mapping_input_still_returns_an_empty_payload():
    assert public_document_payload(None) == {}
    assert public_document_payload("doc-1") == {}


def test_generated_artifact_request_fields_have_exactly_one_definition():
    """The group projection and the payload allow-list must never drift apart.

    ``_project_group_document`` filters the payload that ``public_document_payload``
    produced, so a field named by only one of the two silently disappears from a
    pending generated artifact review. Assigning a single field stays legitimate;
    re-enumerating the group as a literal is the drift this guards against.
    """
    reads_source = (APP_DIR / "functions_group_document_reads.py").read_text(encoding="utf-8")
    access_source = (APP_DIR / "content_screening" / "access.py").read_text(encoding="utf-8")

    assert "GENERATED_ARTIFACT_REQUEST_FIELDS" in reads_source, (
        "functions_group_document_reads.py must take the allow-list from the shared constant"
    )
    relisted = [
        line.strip() for line in reads_source.splitlines()
        if sum(1 for field in GENERATED_ARTIFACT_REQUEST_FIELDS if f'"{field}"' in line) > 1
    ]
    assert relisted == [], f"allow-list re-enumerated instead of imported: {relisted}"

    definitions = [
        line.strip() for line in access_source.splitlines()
        if sum(1 for field in GENERATED_ARTIFACT_REQUEST_FIELDS if f'"{field}"' in line) > 1
    ]
    assert len(definitions) == 2, (
        f"expected only the two lines of GENERATED_ARTIFACT_REQUEST_FIELDS, got {definitions}"
    )


def test_request_fields_are_not_simultaneously_private():
    """A field cannot be both held-review-visible and redacted."""
    assert not (GENERATED_ARTIFACT_REQUEST_FIELDS & PRIVATE_DOCUMENT_FIELDS)
    assert all(is_public_document_field(field) for field in GENERATED_ARTIFACT_REQUEST_FIELDS)


def test_pending_artifact_exposes_requester_fields_but_not_its_binding():
    """The binding stays private while the request attribution stays visible."""
    document = {
        **SAFE_FIELDS,
        "generated_artifact_publication_binding": {"source": "conversation-1"},
        "generated_artifact_promotion_status": "pending_approval",
        "generated_artifact_requested_by_display_name": "Dana Owner",
        SCREENING_FIELD: {"state": "pending", "scan_id": "scan-1", "content_fingerprint": "fp-1"},
    }

    payload = public_document_payload(document)

    assert "generated_artifact_publication_binding" not in payload
    assert payload["generated_artifact_requested_by_display_name"] == "Dana Owner"
    assert payload["generated_artifact_promotion_status"] == "pending_approval"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
