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
    "generated_artifact_publication_binding": {"source": "conversation-1"},
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


def test_non_mapping_input_still_returns_an_empty_payload():
    assert public_document_payload(None) == {}
    assert public_document_payload("doc-1") == {}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
