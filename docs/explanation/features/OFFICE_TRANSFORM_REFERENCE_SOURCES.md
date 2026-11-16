# Native Office transformation references

Implemented in version: **0.261.321** (`application/single_app/config.py`).

## Purpose and supported inputs

Existing selected uploads and previously generated Office files in the same
conversation can supply native formatting and structure for a new draft. Inputs
are DOCX, DOTX, PPTX and POTX. Transformation outputs remain DOCX or PPTX; the
reference is never overwritten.

Use the existing File picker or workspace document selection. A generated file
does not need to be promoted, downloaded or uploaded again for a follow-up edit.
Files from another conversation are not offered as references.

## Native intake

DOTX and POTX intake validates the package's actual native main content type and
uses the shared bounded OOXML guard. A renamed DOCX/PPTX is not a template.
Macros, active content and unsafe package structures are rejected.

The original template bytes are retained through existing document Blob retention.
Template XML text is extracted locally, so Document Intelligence accepting template
extensions is not a prerequisite. Embedded images use the existing Office image
analysis configuration. Empty templates remain available for structural inspection
and show **no narrative content indexed**, rather than claiming successful RAG
indexing.

Content-screened templates still pass through private extraction, inspection,
review and release. Structural metadata and supplemental package XML text are
screening-only; custom properties do not become synthetic RAG chunks. An unsanitized,
reviewed native template can be released with zero searchable chunks. Sanitized
sources never fall back to their quarantined originals; if their active format is
no longer native Office, structural transformation is unavailable.

## Reference and authorization contract

`functions_document_transform_sources.py` exposes actor/conversation-bound
`DocumentTransformSources` services:

- `read_reference(handle)` reads native bytes for inspection.
- `read_reference({handle, content_sha256, extension})` additionally checks the
  exact inspected revision for transformation/replay.
- `describe_reference(handle)` returns safe format, name and scope metadata,
  including authorized document `source` provenance or `None` for an artifact.
- `resolve_reference(handle)` returns `{file_name, source}`. `source` is currently
  authorized document identity, scope and revision provenance without storage
  locators, or `None` for a same-conversation generated artifact.
- `planning_candidates(document_ids=())` offers selected native documents and
  bounded, authorized generated Office files from the current conversation.

Handles are `{kind: "document", document_id}` or
`{kind: "artifact", conversation_id, message_id}`. They are identities, not access
tokens. Browser-supplied paths, Blob locations and SAS URLs are rejected.

Document consumption rechecks current authorization and screening and reads only
the approved active representation. Generated-file consumption uses the existing
conversation, publication and approval boundaries, verifies exact byte bindings
and rechecks after reading. Deleted/masked files, revoked access, changed bytes
and other-conversation handles are not consumable. Original document permissions
are not rechecked when consuming a retained generated file.

## Runtime integration and validation

The application composition root binds
`document_transform_source_reader`,
`document_transform_source_resolver` and
`document_transform_candidate_reader` in `functions_orchestration_bootstrap.py`.
The strict orchestration service/context owners carry those explicit runtime
callbacks; private storage metadata is never placed in planning candidates.
`resolve_reference` projects `{file_name, source}` from `describe_reference`;
either helper supplies those fields to the runtime resolver. Document inspection uses
`analysis_source_snapshot([resolved["source"]])` for document provenance, while
artifact inspection has no original-document source snapshot.

Regression coverage:

- `functional_tests/test_document_transform_sources.py` — template intake,
  native package types, empty-template release, safe handles, current source
  authority, artifact approval/publication, deletion, digest and scope isolation.
- `ui_tests/test_office_template_upload_selection.py` — existing chat File picker
  on desktop/mobile and React template-extension validation, using the shared
  local/Azure Playwright fixture.

Generated files without the existing digest/size byte binding cannot be used as
native references. Missing native storage is reported as unavailable; narrative
chunks alone cannot preserve Office formatting.
