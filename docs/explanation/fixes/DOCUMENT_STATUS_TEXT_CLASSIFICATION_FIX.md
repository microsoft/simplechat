# Document Status Text Classification Fix

Version: **0.261.351**

Fixed/Implemented in version: **0.261.351**

Related configuration update: `application/single_app/config.py`, `VERSION = "0.261.351"`.

The base branch advanced to **0.261.350** during review. Merging it advances
the combined application to **0.261.351** without changing either fix's behavior.

## Issue and root cause

A chat attachment could show **Failed** even though the document processor
successfully saved and indexed it. Document status messages include filenames,
sheet names, and processing details. Consumers searched the entire message for
`error`, `failed`, or `complete`, interpreting those words as lifecycle state.

For example, `Processing file error-budget.md, type: .md` was treated as a
terminal error. React stopped checking the document immediately, so it never
observed the successful completion. Classic views could make the opposite
mistake: a filename such as `incomplete-policy.pdf` enabled completed-document
actions before processing finished. A filename containing `processing complete`
could also force backend progress to 100%.

The incident's Azure console logs confirmed successful indexing of one chunk
after the UI had stopped polling. It failed before plan review or execution;
the incident did not demonstrate an orchestration or model-provider failure.

## Technical changes

Small, bootstrap-independent predicates now recognize explicit lifecycle
phrases rather than arbitrary substrings. Python uses
`functions_document_status.py`; React uses `documentProcessingStatus.ts`; classic
pages load the local `static/js/document-status.js` asset from `base.html`.
A shared test-case matrix keeps the three implementations aligned.

Consumers updated:

- Workspace processing/error filters and facets in `functions_document_queries.py`.
- Percentage calculation, guarded safe-error updates, and screening-related
  completion wording in `functions_documents.py`.
- Chat-upload search-readiness checks in `route_backend_chats.py`.
- React document status and attachment polling in `documentExplorer.ts` and
  `chatUploads.ts`.
- Classic chat attachment cards and task-document readiness, personal workspace
  lists/cards/folders, group document views, and public workspace views.

An explicit failure such as `Error: ...` still takes precedence over 100%
progress. Metadata warnings and known transient retry messages do not become
terminal failures. Completion of an intermediate stage, such as vision analysis,
is not completion of document ingestion.

This changes interpretation, not ingestion or authorization. Publication
approval, screening holds, sharing restrictions, archived/unlinked documents,
and indexed-chunk requirements retain their separate checks. Legacy explorer
records without progress keep their existing behavior; new chat uploads still
require readiness evidence.

No database migration, filename restriction, timeout increase, automatic retry,
live upload, deployment, or external harness change is part of this fix.

## Usage and impact

Upload documents normally. Filenames can contain state-like words without
changing their processing outcome. Processing attachments remain unavailable
for submission until they are ready, and genuine failures remain visible.

For an already processed attachment stuck in the old UI's Failed state, the
existing **Retry** status-check action can retrieve the document's authoritative
state after the fix is deployed. It does not need another file upload.
Historical stored percentages are not automatically rewritten.

## Validation

Regression coverage includes:

- `functional_tests/test_document_processing_status.py`: shared Python/React/
  classic predicate cases, backend progress, safe failures, facets and readiness.
- `functional_tests/test_v2_chat_context_request.ts` and
  `test_v2_documents_explorer_logic.ts`: actual frontend state and polling.
- `functional_tests/test_document_search_metadata_sync.py`: real status updates
  with SDK `CosmosDict` point responses, plain query rows, and ETag protection.
- `ui_tests/test_v2_chat_upload_status.py`: personal/group uploads with misleading
  filenames, retry diagnostics, real failures, status-only Retry and removal.
- `ui_tests/test_document_status_classification.py`: group list/card/folder
  behavior and personal/public/classic status decisions.
- `ui_tests/test_chat_workspace_upload_progress_polling.py`: classic progress
  rendering, status polling and task-document registration.

These tests use local application assets and intercepted external boundaries;
they do not upload to the deployed application or exercise a live plan.

Local results: the affected browser suites passed **101 tests**, the SDK-backed
metadata/status suite passed **42 tests**, and the targeted status/explorer/
screening-readiness suite passed **96 tests**. Frontend typechecking, the
production build, JavaScript syntax checks, route-policy checks and documentation
checks passed. With the application's pinned Cosmos SDK **4.9.0**, the full
network-blocked Cosmos compatibility gate passed **1,163 tests** and **244
subtests**, with no inventory review gaps.

After merging the **0.261.350** base, combined status, SDK-write, explorer and
incoming saved-memory regressions passed **194 tests** and **5 subtests**.
The focused upload/classic browser suites passed **27 tests**, and documentation
checks and the combined Cosmos inventory remained clean.

A broader backend run encountered a pre-existing extracted-function fixture
failure in `test_content_screening_read_boundaries.py`: its `hybrid_search`
namespace omits `current_public_chat_scope`. The same failure reproduces using
the original test at HEAD. That unrelated test-infrastructure repair is not
included here; the directly affected chat-readiness check passes.

Related: [Chat upload conversation task context](CHAT_UPLOAD_CONVERSATION_TASK_CONTEXT_FIX.md).
