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

### The same duplication existed in the artifact allow-list

The generated-artifact request fields were also enumerated twice, as an
identical four-element literal in both `content_screening/access.py` (widening
the held-document allow-list) and `functions_group_document_reads.py` (the
group projection filter for pending or unapproved documents).

Because `_project_group_document` filters the payload that
`public_document_payload` already produced, the two lists are applied in
sequence. Drift there does not leak — it silently *drops* fields, so a pending
generated artifact would lose its requester attribution in the group review
surface. With M2C adding fields to the artifact approval flow, that was a live
risk rather than a theoretical one.

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

The artifact allow-list is consolidated the same way, into an exported
`GENERATED_ARTIFACT_REQUEST_FIELDS` that `functions_group_document_reads.py`
imports rather than re-enumerating.

### Files modified

| File | Change |
|---|---|
| `application/single_app/content_screening/access.py` | Added `is_public_document_field` and `GENERATED_ARTIFACT_REQUEST_FIELDS`; both payload branches now use the shared predicate |
| `application/single_app/functions_group_document_reads.py` | Imports the shared artifact allow-list instead of re-listing it |
| `application/single_app/config.py` | `VERSION` → `0.261.131` |
| `functional_tests/test_public_document_payload_redaction.py` | New regression coverage, including a drift guard |

### Guarding against recurrence

Because the root cause is duplication rather than any single missing field, the
regression file pins the structural property directly:

- Every member of `PRIVATE_DOCUMENT_FIELDS` is rejected by the shared predicate.
- The unscreened payload can never be a superset of the screened one.
- Neither module may re-enumerate `GENERATED_ARTIFACT_REQUEST_FIELDS` as a
  literal; assigning one field remains legitimate, re-listing the group is not.

Any new private field — including M2C collaboration state such as share-target
recipient identities, requester identity, and approval decision records — only
needs to be added to `PRIVATE_DOCUMENT_FIELDS`, and it applies on both paths.

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

- New regression file: **25 passed**, covering per-field redaction, equality of
  redaction with and without a marker, the shared predicate against every member
  of `PRIVATE_DOCUMENT_FIELDS`, the allow-list drift guard, and non-mapping input.
- Screening access, read boundaries, contracts, lifecycle, group document read
  APIs, group document management, multi-workspace access, and public workspace
  visibility: **535 passed, 55 subtests passed**.
- V2 group workspace and personal-scope browser suites: **127 passed**.
- Route policy: **8/8, 4/4, 2/2**. Docs coverage **7/7**, site quality **6/6**,
  app surface inventory unchanged. Broken-access-control scanner: passed.

### Before / after

For a document with no `content_screening` marker:

| | Serialized keys |
|---|---|
| Before | `_etag`, `_rid`, `_self`, `_ts`, `archived_blob_path`, `blob_container`, `blob_etag`, `blob_path`, `download_url`, `file_name`, `group_id`, `id`, `sas_url`, `screening_provenance`, `source_ref` |
| After | `file_name`, `group_id`, `id`, `title` |
