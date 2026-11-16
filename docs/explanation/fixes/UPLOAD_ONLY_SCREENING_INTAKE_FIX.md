# Upload-Only Screening Intake Fix

Fixed in version: **0.261.230**

Related issue: [#1621](https://github.com/microsoft/simplechat/issues/1621) (second step). The first step is the [Workflow Run History Source Re-check Fix](WORKFLOW_RUN_HISTORY_SOURCE_RECHECK_FIX.md).

## Issue

Content screening was meant to check documents when they enter a workspace. With screening on, it also held documents that SimpleChat itself produced, and it held documents again whenever their metadata changed:

- A Markdown, Word or PowerPoint file that an agent saved to a workspace was held as **Content screening pending** and went through a full scan before anyone could use it.
- A chat or workflow artifact published into a group or public workspace was created with a screening marker. Approving it had to pass a receipt-bound screening reservation, and a request whose reservation couldn't be proven was refused with "This screening reservation cannot start publication."
- Editing a cleared document's title, abstract, keywords or tags started a new scan and held the document again. The group and public metadata APIs answered `queued` (202) instead of `updated`.
- Metadata the model generated for a newly released upload did the same: the document was held again until its metadata was re-inspected.
- The release proof included a fingerprint of the document's metadata, so a metadata change that didn't go through a rescan made a cleared document unavailable.

## Root Cause

- **Intake.** `document_requires_screening` enrolled every new document while screening was on and the effective policy had checks. `create_document` chose the initial screening marker without knowing who created the document, so generated documents were enrolled like uploads.
- **Publication.** Because publication destinations were enrolled, approval needed proof that it was starting the destination's first scan. `functions_artifact_publication.py` recorded a `screening_reservation` in the receipt, and `begin_scan`/`inspect_scan` consumed it through `_consume_publication_reservation` and `consume_artifact_publication_screening_scan`.
- **Metadata.** `update_document` sent any change to a content metadata field of a screened document to `queue_metadata_rescan`, which began a new scan and held the document. Model-generated metadata is written through `update_document`, so it took the same path.
- **Release proof.** `_require_release_proof`, `finalize_publication_checkpoint` and the scan-job publication match compared a `metadata_fingerprint` recorded at release with the document's current metadata, so any metadata change invalidated the release.

Under the agreed upload-only model, screening checks only documents that enter a workspace by a user upload or File Sync, generated content is never checked, and metadata edits are not screened.

## Technical Details

Files modified:

- `application/single_app/content_screening/contracts.py`
- `application/single_app/content_screening/service.py`
- `application/single_app/content_screening/jobs.py`
- `application/single_app/content_screening/access.py`
- `application/single_app/functions_documents.py`
- `application/single_app/functions_simplechat_operations.py`
- `application/single_app/functions_artifact_publication.py`
- `application/single_app/functions_artifact_publication_readiness.py`
- `application/single_app/functions_group_document_publication.py`
- `application/single_app/functions_public_document_publication.py`
- `application/single_app/functions_group_document_management.py`
- `application/single_app/functions_public_document_management.py`
- `application/single_app/route_backend_group_documents.py`
- `application/single_app/route_backend_public_document_management.py`
- `application/single_app/config.py`
- `application/v2_ui/src/lib/documentOperations.ts`
- `application/v2_ui/src/components/documents/DocumentExplorer.tsx`
- `functional_tests/test_content_screening_upload_only_intake.py` (new)
- `functional_tests/test_content_screening_jobs.py`
- `functional_tests/test_content_screening_pipeline.py`
- `functional_tests/test_content_screening_history.py`
- `functional_tests/test_group_document_management.py`
- `functional_tests/test_public_document_publication.py`
- `functional_tests/test_group_document_fixture_parity.py`
- `functional_tests/test_public_document_fixture_parity.py`
- `functional_tests/test_group_document_publication_screening_bootstrap.py` (removed)
- `ui_tests/fixtures/group_document_management.py`
- `ui_tests/fixtures/public_document_management.py`
- `ui_tests/test_v2_group_document_management.py`

### Marking generated documents

- `contracts.py` defines `SCREENING_EXEMPTION_FIELD` (`screening_exemption`), `generated_screening_exemption()` (`{"reason": "generated", "version": 1}`) and `is_generated_screening_exempt()`, which accepts only that exact value.
- `create_document` takes a server-only `screening_exemption` argument. It is validated before any earlier revision is archived and stored on the new version before `initial_document_marker` runs. It is not carried forward to later versions.
- `_upload_generated_document_for_current_user` (used by the Markdown, generated-document, Word and PowerPoint agent uploads) and `_publish_generated_chat_artifact_for_user` pass the exemption. These are the only `create_document` callers that do. User uploads, chat uploads saved to a workspace and File Sync don't, so they are screened as before. The provenance `origin` field is not used, because a `chat` origin also marks a user's chat upload.
- The name starts with `screening`, so `reject_screening_fields` rejects it in any client request to the document APIs, and `is_public_document_field` keeps it out of every document response. `update_document` refuses every `screening_*` keyword, so no update path can set or change it. The upload routes build their records from explicit arguments and never copy client fields.

### Skipping screening at intake

- `document_requires_screening` returns `False` for an exempt document that has no `content_screening` marker. An existing marker still wins. `initial_document_marker`, `prepare_document_upload`, `process_document_upload_background` and `process_document_reprocess_extraction_background` all follow it.
- `begin_scan` and the scan-job hold step raise `ScreeningNotRequiredError` (`screening_not_required`, a conflict error) for an exempt document without a marker, so scan jobs record it as skipped and never write a marker.

### Removing the publication screening reservation

- Removed `_consume_publication_reservation`, `consume_artifact_publication_screening_scan`, `_enroll_screening_reservation`, `_reservation_has_screening_history`, `publication_screening_reservation`, the `screening_reservation`/`screening_reservation_consumption` receipt fields and the bootstrap retry in the group and public publication adapters.
- `_publication_destination_admits_approval` admits a destination with no screening marker, and one whose screening release is available. A destination held by screening is refused with `PUBLICATION_SCREENING_HOLD_MESSAGE`, which tells the requester to cancel and request publication again. Only destinations created before this version can carry a marker.
- `inspect_publication_readiness` already reports a marker-free destination as `screening: not_required` and still confirms access to the destination before it reports index readiness.

### Metadata

- `update_document` applies metadata edits to a screened document directly, including model-generated metadata from `process_metadata_extraction_background`. `queue_metadata_rescan` is replaced by `validate_screened_metadata_update`, which keeps the rule that a rename cannot change a screened file's extension.
- Chunk metadata (title, authors, file name, classification and tags) is now propagated for a screened document while its release is available. Held documents have no released chunks; publication rebuilds them.
- `propagate_tags_to_blob_metadata` no longer writes to a screened document's blob. The release pins that blob by ETag and content hash, so rewriting its metadata would have made the released file unreadable.
- `_require_release_proof`, `finalize_publication_checkpoint` and `_publication_matches_document` no longer compare the metadata fingerprint. The release still records it. The scan-job reconciliation no longer has a special case for metadata-triggered child scans, because there are none.
- `update_group_document_metadata` and `update_public_document_metadata` always return `updated`, and their routes always answer 200. The routes no longer have a 202 branch for a `queued` receipt.

### V2 Documents explorer

- `documentOperations.ts` accepts a metadata save only when the receipt is `updated` with HTTP 200. Any other receipt is unconfirmed, including the `queued` (202) receipt screened documents used to get, and the dialog keeps the draft.
- `DocumentExplorer.tsx` has one outcome for a confirmed save: it shows **Metadata saved.** and refreshes the list and details, and the document stays listed and available. Before, a `queued` receipt removed the document from the list and showed "Metadata saved. Screening is queued; the document remains unavailable until released."
- The group and public UI test fixtures no longer build a `queued` metadata receipt.

### Impact

- Generated documents are processed and searchable as soon as processing finishes, whether or not screening is on.
- Users can edit metadata of released documents without losing access to them.
- Existing data is not migrated. Documents keep their current screening state, nothing already screened or held is released, and a publication destination held by screening before this version must be requested again.

### Known limitations

- Release publishes the metadata captured from the inspected copy. A metadata edit made through the API while a document is still held is replaced by that copy when the document is released. The workspace interfaces don't offer metadata edits on held documents.

## Validation

`functional_tests/test_content_screening_upload_only_intake.py` (127 cases) runs the real `create_document`, `update_document`, metadata extraction, upload dispatch, generated-upload, scan-job, publication and document-guard code against in-memory stores, with screening on and an active policy:

- Generated and published documents get no marker and keep the exemption; user uploads, chat uploads and File Sync documents in all three scopes still get a `pending_scan` marker. The exemption belongs to one version, a malformed exemption is refused before anything is written, and an existing marker still wins.
- `prepare_document_upload` and the upload dispatcher process a generated document without screening. An agent upload in a personal or group workspace creates an unscreened document.
- Only the two generated creation sites pass the exemption; the upload and File Sync sites don't.
- Every guarded document mutation route rejects a client exemption in JSON and form bodies, `update_document` refuses it, and responses never include it.
- A scan job skips a generated document with `screening_not_required` and still scans an uploaded one; `begin_scan` refuses a generated document.
- Editing metadata after release keeps the release proof, a rename can't change a screened file's extension, and model-generated metadata applies to a released group document without a hold, updates its chunks and leaves its blob alone.
- A group publication creates an unscreened destination, records no screening reservation in its receipt, and is approved and queued without a scan.
- The reservation and metadata-rescan functions no longer exist, and the screening and readiness modules still import without network access or application owners.

With the application changes reverted and only the test changes applied, 22 cases in that file fail and 3 cannot set up; the rest are the existing client guards, readiness and import checks, which pass either way.

Existing tests that asserted the removed behavior were rewritten:

- `test_content_screening_jobs.py`: metadata-triggered child scans became generated metadata that applies without a new hold, including crash recovery; a title or publication-metadata change no longer blocks an interrupted release from finishing.
- `test_content_screening_pipeline.py`: a metadata edit keeps a release, recovery finalizes a release after a metadata edit, and only the source-format rule remains.
- `test_group_document_management.py`: a screened metadata edit returns `updated` and keeps the release; a screened tag edit updates chunks but not the release blob.
- `test_public_document_publication.py`: approval records no screening reservation, and a held legacy destination blocks approval.
- `test_content_screening_history.py`: a release proof that doesn't match the content still leaves only the screening status, and metadata edited after a release stays available.
- `test_group_document_fixture_parity.py` and `test_public_document_fixture_parity.py`: a released screened document's metadata change returns the ordinary `updated` receipt (200), not `queued` (202).
- `ui_tests/test_v2_group_document_management.py`: `test_queued_metadata_acknowledgement_keeps_saved_content_held_for_screening` became `test_screened_metadata_edit_applies_directly_and_keeps_the_document_available`. After a released screened document's metadata is saved, the explorer shows **Metadata saved.**, the details show the edit, and Chat, Tag, Extract, Download, Delete and Edit stay enabled. `test_malformed_metadata_success_never_discards_the_draft` gained a `legacy-queued-202` case. With the V2 explorer change reverted and the SPA rebuilt, that case fails, because the old explorer accepted the receipt and closed the dialog.
- `test_group_document_publication_screening_bootstrap.py` tested only the removed reservation and was removed. Its import check moved to the new file.

The 258 functional test files present on both branches were run on the base branch and with this change. No test that passes on the base branch fails with this change; the remaining failures already fail on the base branch for unrelated reasons, such as harnesses that need Azure configuration.

The V2 change was checked with `npm run typecheck` and `npm run build` in `application/v2_ui`, then with the V2 browser suites against the built SPA and local Playwright:

- All tests pass in `test_v2_group_document_management.py`, `test_v2_public_documents.py`, `test_v2_personal_document_scope.py`, `test_v2_group_document_collaboration.py` and `test_v2_group_documents.py`.
- `test_v2_content_screening.py` passes except `test_admin_policy_is_discoverable_and_editable_before_citations_are_enabled`, which fails the same way against a build of the base branch's V2 source.
