# V2 Workspace Upload Queue

## Overview

The V2 workspace document explorer can now take a selection of hundreds of files in one go. Before, every selected file travelled in a single multipart request, so a selection of more than about ten files could exceed what a gateway will carry or the time a request may take, and the whole upload failed.

The explorer now sends the selection as a queue of small requests from the browser, one after another. Nothing changes on the server.

- **Version**: 0.261.492
- **Implemented in**: 0.261.492
- **Dependencies**: the existing upload routes (`/api/documents/upload`, `/api/groups/<id>/documents/upload`, `/api/public-workspaces/<id>/documents/upload`)

## Technical Specifications

### Architecture

- `application/v2_ui/src/lib/documentUploadQueue.ts`
  - `planUploadBatches(files, limits)` splits a selection, in order, into requests of at most `UPLOAD_BATCH_MAX_FILES` (5) files and `UPLOAD_BATCH_MAX_BYTES` (50 MB). A single file larger than the byte limit goes alone, as it always did.
  - `uploadInBatches(files, upload, options)` sends the requests sequentially, merges each answer into one outcome, and reports progress after each request.
- `application/v2_ui/src/components/documents/DocumentExplorer.tsx` calls the queue from `onUploadFiles`, after the file type check, the size check and the user agreement. The progress bar advances as each request is answered.

### Behavior

- Requests never overlap, so the server does the same work in the same order as before, in smaller pieces.
- A request that the server refuses with per-file reasons is an answer; the queue continues with the next request.
- A request with no confirmed outcome (a dropped connection, a lost session) stops the queue. The files in that request are listed, and the feedback says how many files were never sent.
- Leaving the explorer stops the queue before its next request.

### Configuration

None. The two limits are constants in `documentUploadQueue.ts`.

## Usage Instructions

Select or drop any number of files on the Documents page of a personal, group or public workspace. The command bar shows `Uploading files` with a running count. When the queue ends, the summary reads `Accepted N of M files. Processing is queued, not complete.`

## Testing and Validation

- `functional_tests/test_v2_document_upload_queue_logic.mjs` runs the real queue and the real upload adapter against controlled HTTP: batch planning for 250 files, the byte limit, sequential sending, merged answers, refusals, a stopped queue and an interrupted one.
- `functional_tests/test_v2_user_agreement_gate.py` still proves the agreement is asked before anything is sent.

### Limitations

- The queue lives in the page. Closing or reloading the tab ends it; files already accepted keep processing.
- A stopped queue is not resumed automatically. Refresh, then upload the files that are missing.
- Chat attachments are not affected; they were already sent one file per request.
