# Document Payload Redaction Independent Of The Screening Toggle

## Issue

`public_document_payload()` is the serializer behind the document list and
detail APIs (`get_documents`, `get_document`, group document projections, and
the assigned-knowledge catalog). It returned two different shapes depending on
whether the document carried a `content_screening` marker.

When the marker was absent — which is the normal state for a deployment with
content screening disabled, and for any document that was never enrolled — the
function took an early return that redacted only three fields. Everything else
on the stored Cosmos record was serialized into the JSON response, including:

- `blob_path`, `archived_blob_path`, `blob_container`, `blob_etag`, `blob_url`
- `sas_url` and `download_url`
- `source_ref`, `canonical_ref`, `units_ref`, `result_ref`
- `original_blob_path`, `original_blob_container`, `active_manifest_id`
- `screening_provenance` and any other `screening_*` key
- Cosmos internals `_rid`, `_self`, `_etag`, `_ts`

With screening **enabled**, the same document correctly redacted all of those.
The exposure therefore depended entirely on an unrelated administrative toggle.

Fixed in version: **0.261.131**

## Root cause

The redaction rule was written twice. The screened branch composed it from
`PRIVATE_DOCUMENT_FIELDS` plus the `_` and `screening_` prefix rules, while the
unscreened early return carried a hand-maintained literal set:

```python
if SCREENING_FIELD not in document:
    return {key: deepcopy(value) for key, value in document.items() if key not in {
        "generated_artifact_publication_binding", "generated_artifact_publication_processing",
        "group_document_projection_writer",
    }}
```

That literal is a strict subset of `PRIVATE_DOCUMENT_FIELDS`, so it had no
independent purpose — it was a copy that fell behind. Every field added to
`PRIVATE_DOCUMENT_FIELDS` over time silently failed to apply to unscreened
documents, and each new private field had to be remembered in two places.

This directly contradicts the module contract, which opens with
"Authoritative ordinary-content access, **independent of the screening
toggle**."

## Fix

`content_screening/access.py` now derives both branches from one predicate:

```python
def is_public_document_field(key):
    """Redaction is a property of the field, never of the screening toggle."""
    return (
        key not in PRIVATE_DOCUMENT_FIELDS and key != SCREENING_FIELD
        and not key.startswith("_") and not key.startswith("screening_")
    )
```

The unscreened early return applies `is_public_document_field` directly. The
screened branch keeps its additional held-document gate
(`available or key in public_fields`) and then applies the same predicate, so
the two paths can no longer drift apart.

### Files modified

| File | Change |
|---|---|
| `application/single_app/content_screening/access.py` | Added `is_public_document_field`; both payload branches now use it |
| `application/single_app/config.py` | `VERSION` → `0.261.131` |
| `functional_tests/test_public_document_payload_redaction.py` | New regression coverage |

## Compatibility

No caller loses a field it could previously rely on. Every field newly redacted
here was **already** redacted whenever content screening was enabled, so no
client, template, or downstream consumer could depend on it without being
broken in screening-enabled deployments.

The internal consumers were each confirmed to read their sensitive inputs from
the original document rather than from the payload:

- `functions_assigned_knowledge._serialize_catalog_document` reads provenance via
  `document_provenance(document)` before serializing, then selects named fields.
- `functions_group_document_access.get_group_document_actions` uses the payload
  only for `content_screening`, and resolves blobs via `_active_blob_reference(document)`.
- `functions_group_document_reads._project_group_document` re-adds `_ts` from the
  original document when a server-side sort needs it, which the existing comment
  already documented as the expected behavior of the allow-list.

## Validation

```powershell
python -m pytest .\functional_tests\test_public_document_payload_redaction.py -q
```

- New regression file: **22 passed**, covering per-field redaction, equality of
  redaction with and without a marker, the shared predicate against every member
  of `PRIVATE_DOCUMENT_FIELDS`, and non-mapping input.
- Screening access, read boundaries, contracts, lifecycle, group document read
  APIs, multi-workspace access, and public workspace visibility:
  **306 passed, 55 subtests passed**.
- V2 group workspace and personal-scope browser suites: **127 passed**.
- Route policy: **8/8, 4/4, 2/2**. Broken-access-control scanner: passed.

### Before / after

For a document with no `content_screening` marker:

| | Serialized keys |
|---|---|
| Before | `_etag`, `_rid`, `_self`, `_ts`, `archived_blob_path`, `blob_container`, `blob_etag`, `blob_path`, `download_url`, `file_name`, `group_id`, `id`, `sas_url`, `screening_provenance`, `source_ref` |
| After | `file_name`, `group_id`, `id`, `title` |
