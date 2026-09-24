# V2 Group Document Management

## Overview

Implemented in version: **0.261.129**, tracked in
`application/single_app/config.py`.
The M2B backend and frontend are integrated with the shared workspace shell.

## Purpose and boundaries

Group document managers can work in the same native explorer used for My
Workspace without changing the meaning of personal operations or relying on
the account's mutable active-group preference.

M2B covers upload/progress, metadata, document tags and vocabulary, permitted
downloads, metadata extraction, reprocessing, and revision-aware deletion.
Sharing and generated-artifact approval decisions remain M2C. Public workspace
migration, group saved-view persistence, content preview, and screening-policy
configuration are not part of this milestone.

Dependencies are the existing shared shell, group read APIs, document storage,
index/chunk helpers, background executor, and Content Screening authorization.
No new cloud resource or deployment setting is required.

The endpoint and outcome reference is
[Group Document Management APIs](GROUP_DOCUMENT_MANAGEMENT_APIS.md).

## Explicit operation boundary

Native group operations use the immutable target family
`/api/groups/<group_id>/documents/...`. They do not call personal APIs or rely
on an old route interpreting a new query parameter. An older worker that lacks
the new route rejects it instead of executing in its active group.

Existing legacy mutation routes keep their contracts. Source operations,
queued jobs, and projection/cache updates carry the captured user, group, and
document identity independently of later active-group changes.

The selected-group context advertises supported operations through
`document_management`; fresh document projections advertise `document_actions`.
Missing support leaves group operations unavailable. These are interface
eligibility hints, not authorization grants: the server revalidates each
operation against current role, group status, source relationship, revision,
screening state, and feature policy.

## Eligibility

Owner, Admin, and DocumentManager retain the content-manager boundary. Ordinary
User membership does not acquire mutations or downloads.

Active groups permit applicable operations. Locked groups remain read-only,
with downloads independently controlled. Upload-disabled groups retain
permitted deletion/reprocessing cleanup, not uploads, metadata/tag editing, or
metadata extraction. Inactive and unknown statuses deny content operations.

Metadata/tag edits, extraction, and reprocessing require a current revision
owned by the selected group. Historical revisions remain available only for
permitted download and explicitly revision-aware deletion. A stale edit target
is rejected rather than redirected to a replacement revision.

Incoming shares do not grant permission to modify the source. Downloading an
approved incoming source requires both recipient and source-owner workspace
policy, current relationship, screening proof, and the actual source bytes.
Recipient membership plus the approved share is the relationship grant; source
group membership is not invented as an extra requirement.

Pending generated artifacts remain restricted even when no screening marker
exists yet. Held-content cleanup follows the existing explicit review/delete
eligibility, not a generic bypass of in-flight scanning. Approval controls are
not introduced here.

## Outcomes and recovery

Metadata requests contain only changed allowed fields and are validated before
side effects. Scope-bound receipts distinguish an applied update from an
accepted screening rescan. A queued update is not described as immediately
available content.

Strict writes claim the source conditionally before downstream projection
changes. A conflict or disappeared source does not recreate a deleted record or
alter projections on behalf of a rejected write. Projection failure after a
source commit is reported explicitly as repair-required; retry must not skip
unfinished work just because the source values already match.

Bulk and queued operations report each requested item. A successful HTTP status
does not override a nonempty error list. Malformed acknowledgements remain
unconfirmed, not successful operations.

Deletion shows the target group/files and current-only versus all-version
intent. File-source choices retain their canonical `delete_only` and
`ignore_remote` meanings. A broad force flag or the personal interface's legacy
retry value does not substitute for those choices. Requested-ID receipts are
separate from the sibling revision IDs actually removed.

Tag vocabulary uses conditional/per-key persistence so it cannot overwrite
membership, group settings, or unrelated tags. Rename/delete propagation
targets current owned revisions and preserves historical revisions. Partial
propagation keeps the old vocabulary for unresolved documents and reports
those failures rather than claiming the rename completed.

## Shared interface behavior

The operation adapter keeps scope identity separate from action eligibility.
Enabling group management does not enable personal URLs, personal saved views,
or sharing controls.

Toolbar, row/detail commands, shortcuts, drag/drop, tag chips, dialogs, and
empty-state actions use the same operation policy. Mixed selections are not
silently filtered into a successful-looking subset.

Failed saves retain usable drafts and clear error/recovery guidance. Dirty and
busy callbacks cooperate with the group shell's navigation guards. Aborting a
request is not treated as proof that a mutation was cancelled on the server.
Late outcomes cannot update a different group or authenticated viewer.

The existing [group browsing](V2_GROUP_DOCUMENT_BROWSING.md) and
[shared shell](V2_SHARED_WORKSPACE_CONTEXT.md) behavior remains in place.
Personal endpoints and their existing management semantics remain separate.

### Working with files and tags

Select the intended group before starting an operation. Use Documents for
uploads and selected-file commands, and Tags for the group's vocabulary.
On compact screens, Upload stays primary while the **Actions** picker exposes
the other eligible commands without shrinking the document viewport. Filters
and details retain the existing compact dialogs.

Use the metadata editor for changed fields, review its queued or applied result,
and keep the draft if saving fails. For bulk work, review the per-item outcome
before retrying: successful items are not automatically submitted again.
Tag rename/delete can retain old vocabulary until unresolved documents or a
definition conflict are reconciled.

Review deletion intent and the exact file-source/conversation confirmation
before proceeding. Changing groups or navigating away does not silently
discard a draft or pretend that an in-flight write was cancelled.

## Verification and limitations

Backend coverage exercises operation/role/status combinations, immutable
targets, malformed requests before side effects, source ownership, current and
historical revisions, screening/pending records, partial outcomes, concurrent
updates/deletion, tag-definition races, exact download sources and mid-read
revocation, worker scope, and legacy compatibility.

Frontend coverage uses the production SPA with closed HTTP fixtures and
exercises capability refusal, exact paths/payloads, drafts and pending writes,
partial receipts/retries, confirmations, Tags management, downloads, compact
layouts, and personal regressions.

The integrated parent verification passed the 498 selected backend/read/
transport cases and all 92 browser cases: management, existing group reads,
shell behavior, and the independent personal success/failure baseline.
The focused operation, reader, and scope-controller executable checks also
passed. The compact management interface meets the existing 160px document
viewport and 180px search-width floors in the tested mobile layouts.

Parent-owned integration baselines are
`functional_tests/test_group_document_management_transport.py` (new bound URLs
cannot match legacy routes) and
`ui_tests/test_v2_personal_document_scope.py` (personal reads and management
remain personal despite an unrelated active group).

`functional_tests/test_group_document_sdk_conditions.py` exercises the real
Cosmos/Blob SDK HTTP pipelines with local capturing transports and blocked
sockets. It verifies that the Cosmos patch predicate and Blob `If-Match` are
sent unchanged and that precondition failures remain failures. It was initially
verified with Cosmos 4.9.0 and Blob Storage 12.19.0; it does not simulate or claim
live service-side compare-and-set execution.

Browser download-error coverage uses actual JSON/HTML responses; exact
`response.redirected=true` rejection is covered by executable adapter checks,
not a fictitious-host HTTP redirect. Multi-service mutations are not distributed
transactions, so repair-required and partial outcomes remain meaningful.

`functional_tests/test_group_document_fixture_parity.py` holds the three group
document fixtures (reads, management and collaboration) to the real routes,
route by route: only server keys, every field the page reads present on both
sides, and matching statuses and error codes. The browser suites script
management receipts from builders that equal the real route's response to the
same request. When it was added, after version **0.261.161**, it corrected the
fixtures in every family, from the read rows' fields and refusal texts to each
management receipt and the collaboration reads' codes. Three product findings
were pinned as strict `xfail` tests in `ui_tests/test_v2_group_document_management.py`.
All three were fixed in version **0.261.164**, and the tests now pass:

- a coded failure's dialog showed its machine code, such as
  `document_propagation_incomplete`. It now shows the server's sentence;
- the conversation delete guard didn't name the conversation the file belongs
  to. The confirmation now names it and links to it in V2 chat
  (`/v2/chat?conversationId=<id>`, in a new tab). The guard's own link is never
  followed, and a link to another site or to classic chat never becomes a link;
- a multi-document download was always saved as `documents.zip`. It's now saved
  under the archive name the server gives (`group-documents.zip`,
  `public-documents.zip`), while a single document keeps its own file name.

See the [V2 Fixture Parity Findings Fix](../fixes/V2_FIXTURE_PARITY_FINDINGS_FIX.md).

No live service mutation, deployment, or large-workspace benchmark is implied.
