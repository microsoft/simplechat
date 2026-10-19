---
layout: page
title: "Workspace document discovery and metadata outcomes"
description: "Reliable public filename lookup and independent metadata-analysis outcomes across workspaces."
version: "0.261.347"
---

## Issue and root causes

Fixed/Implemented in version: **0.261.347**.
Related issue: [#1778](https://github.com/microsoft/simplechat/issues/1778).
The application version is updated in `application/single_app/config.py`.

Public chat document lookup previously truncated recent documents before applying
any search, ignored requested pages, and omitted filtered totals. Older matching
files could disappear from the picker even though their content was indexed.
The default route also bypassed the canonical legacy/no-preference visibility
fallback. An application UI fixture implemented filtering that production lacked.

The shared metadata extractor gated search on personal/group workspace settings,
omitting public-only configurations. Some provider and parsing failures returned
previous metadata as if analysis had succeeded. Metadata progress and failure
messages overwrote content-processing status, conflating usable indexed content
with failed analysis. The automatic final pass also omitted the upload's
execution-time authorization guard.

These defects are reproduced locally. They do not establish the precise metadata
failure in an already-deployed instance.

## Technical changes

`route_backend_public_documents.py` resolves current public scope using the
canonical visibility helper, obtains eligible current revisions, filters filename
or title case-insensitively, sorts, computes `total_count`, and then pages.
The same path covers access-index reads and source fallback. Supported sort keys
are `_ts`, `file_name`, and `title`; the existing default page size remains 1000.
Pending generated artifacts remain excluded.

The shared candidate loader and its Documents/`#` interfaces report document or
tag lookup failures without discarding successful sources. Retry preserves scope
and selection. Failed or aborted tag reads do not seed a successful empty cache,
and meaningful workspace-ID changes refresh the picker.

`functions_documents.py` persists `metadata_extraction_status` independently:

| Value | Meaning |
| --- | --- |
| `running` | Analysis is in progress. |
| `succeeded` | A usable response was analyzed and supported metadata persisted. |
| `disabled` | Metadata analysis was disabled when the job ran. |
| `empty` | No usable metadata was returned, or automatic processing indexed no chunks. |
| `failed` | Lookup, provider, parsing, validation, or persistence failed. |

Manual analysis does not reset content progress. Automatic analysis failures leave
successful indexing complete. Empty/model-error results preserve existing fields;
unknown authors are not fabricated. Configured provider resolution is unchanged.
Final extraction receives the upload's operation guard and safe-error policy.
Failed guarded manual jobs remain failed jobs rather than success-shaped receipts.
Safe failure diagnostics use the existing `DOCUMENT_METADATA_EXTRACTION` logging tag.

The access-index projection carries the separate outcome. V2 details display it,
poll running analysis, and offer retry only when the existing extraction operation
is available to the caller. Running analysis disables another extraction action.
Screening and publication holds continue to block unavailable content.

## Usage and impact

Search by filename when a generated title is missing. **Ready** content does not
need successful metadata analysis to be found in chat. A source lookup warning
means a request failed, not that a particular document is unauthorized.

After a failed or empty analysis, authorized users can choose **Retry metadata
analysis** in document details. Populated metadata is preserved; this is not an
overwrite/regenerate-all operation. No public visibility preference is broadened.
Previously saved records are not migrated or automatically retried.

## Validation

Runtime regressions in `functional_tests/test_workspace_metadata_outcomes.py`
execute the real shared extractor, merge, manual worker, final pass, and Markdown/
plain-text upload dispatcher. They cover all three workspace scopes, public-only
feature settings, disabled analysis, absent chunks, provider/JSON/schema failures,
empty responses, preserved fields/readiness, guarded failure, and installed-SDK
Cosmos responses. Projection and public-route checks cover the persisted outcome.

`test_public_chat_document_list_pending_artifacts.py` checks older matches beyond
six unrelated documents, filename/title matching, paging/totals, current revisions,
pending artifacts, source/index parity, and application-fixture parity.
Browser tests exercise older filename selection, per-scope failures and retry in
Documents and `#`, selected-source dispatch, and authorized metadata retry without
changing content readiness. Existing scope, management, and screening suites
protect the corresponding permission and publication boundaries.

Recorded local results:

| Check | Result |
| --- | --- |
| Final query/fixture parity, metadata, and upload-screening regressions | 227 passed. |
| Canonical public scope and public/group document fixture parity | 193 passed. |
| Pinned-SDK boundary/metadata tests and connector dependency-failure reruns, with network blocked | 119 passed. |
| Complete offline Cosmos contract gate with repository-pinned dependencies | 1,088 passed and 244 subtests passed. |
| Native public/group metadata and queue authorization contracts | 88 passed. |
| Route policy, unauthenticated policy, and policy-coverage scripts | 28 passed. |
| Four affected browser suites | 202 passed; four mobile-navigation failures reproduced against unchanged HEAD frontend sources. |
| Shared agent knowledge-source browser workflow | Passed. |
| V2 typecheck and production build | Passed; existing bundle-size warning remains. |
| Cosmos boundary inventory | 1,066 owners, 410 doubles, no review gaps. |

The complete Cosmos matrix passed after restoring the repository's SDK and Yamcs
dependency pins in the isolated validation environment. Separate broader
agent-authoring failures also reproduce against the unchanged frontend and were
not changed by this fix.

Before the fix, a successful HTTP response could contain unrelated public files
and a metadata failure could look like either success or overall content failure.
After the fix, filtered results and separate outcomes represent those conditions
without inventing metadata or silently widening retrieval.

## Limitations and deployment verification

No deployment or state-changing live validation is included. The original
interaction stopped before submitting a prompt, so it cannot prove a downstream
retrieval or model defect. The effective deployed revision and exact historical
metadata-provider failure remain unconfirmed; the available Azure identity could
not read the needed Cosmos processing records.

Validate the deployed revision, authorized document selection, metadata outcome,
and grounded answer/citation in a separately approved live workflow.
