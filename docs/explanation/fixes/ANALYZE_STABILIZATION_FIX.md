# Analyze planning, Retry, downloads, and responsive stabilization

Fixed in version: **0.261.113**, recorded in
`application/single_app/config.py`.

## Scope and reproduction baseline

This stabilization builds on `paullizer-react-v2-ui` at
`c728f62b9a4cd05f4c18fde850082ed76db14168`, application **0.261.112**, after
#1483 and #1484. It does not reintroduce those feature commits or add workflow
conditions, loops, aggregation semantics, or another execution/storage engine.

On 2026-09-17, the named Azure test application was still configured for image
`simplechat:0.261.107-f007187d`. Commit
`f007187d844a032eaa9aaec26633c9dc4959c513` contains the separate content-screening
implementation; it is not the integrated V2 baseline. A version string alone
does not establish matching code or frontend assets.

No deployment, live workspace publication, or permission change is part of this
fix. Fresh live acceptance requires an explicitly authorized matching target.

## Planning and Retry

The optimistic question had a `pending-user-*` ID and an
`orchestration_turn_id`, but message Retry only recognized saved orchestration
attempt metadata. It therefore sent the temporary ID to the persisted-message
retry API and received 404.

`orchestrationController.ts` now retains an immutable copy of the original
planning selections. `chatStore.ts` routes an unsaved planning Retry through
the existing planning dispatcher with the same conversation and turn, without
another user bubble. Concurrent work prevents another submission. Stop,
conversation deletion, and superseded responses cannot deliver a late plan
into another conversation. Missing context requires deliberate composer recovery;
an existing plan or question cannot be silently replaced. Persisted message Retry
and checkpoint-based orchestration recovery remain separate.

The controller also rejects missing, malformed, wrong-conversation, and unusable
plan payloads before treating them as a successful plan.

### Planner validation evidence and correction

The historical console event at **2026-09-17 14:40:06 UTC** recorded
`invalid_plan_or_missing_requirement`. The preceding capability event required
`document_search`, although `document_analyze` was available. The historical
model completion was not captured, so its precise proposed steps remain unknown.

A deterministic local reproduction established an input-contract defect:
pinning documents automatically required Search, causing a valid Analyze-only
plan over those documents to fail the selected-operation requirement.
`Composer.tsx` no longer converts pinned sources or a workspace handoff into
an implicit Search operation. Explicit Search remains required, and existing
backend validation still requires all selected documents.

`functions_orchestration_planner.py` retains the existing safe error response
and adds conversation/turn identity, stage, exception type, and incomplete/refused
completion classification to failure diagnostics. Normalization failures and
missing selected work are distinguishable without logging prompts, provider
response bodies, credentials, or raw SDK exception text. A failed request does
not become an empty successful plan or switch models.

## Authorized artifact byte delivery

Historical console events at **14:44:31 UTC** and **14:47:48 UTC** reported:

> This document is unavailable until content screening and review are complete.

The deployed screening revision passed only filename, container, and blob path
from an already-authorized generated artifact into a workspace-only citation
reader. That reader required a workspace document identity and raised a hold
before metadata or blob access. Its route converted the hold into a generic 500.
This deterministic identity mismatch is not evidence of a Blob permission error
or proof that the source documents were actually quarantined.

`route_enhanced_citations.py` now serves standalone chat artifacts through the
existing internal `download_blob_content` reader, not through workspace-document
admission. It obtains container and path only from the authorized stored message.
Conversation participation, generated-file approval, committed publication, and
saved-analysis source access run before and after the byte read. Changed message
identity, blob reference, ETag, or recorded digest prevents delivery; available
content hashes are checked against the actual bytes.

Successful CSV and Markdown responses contain the actual file bytes, appropriate
content types, safe attachment filenames, and private `no-store` headers. Missing
content returns a safe 404, lost access a safe 403, and unavailable storage a safe
503. Other unexpected failures remain errors, without exposing exception text.

The screening-free baseline does not add screening-specific imports or disable
screening. When combined with screening, its existing source-evidence check in
`_get_authorized_chat_artifact_message` must remain on both sides of the read,
and genuine screening holds must retain that branch's explicit error handling.
Workspace-linked documents still use their own admitted representation.
Already-published workspace copies keep their independent destination ACL.

Classic and V2 download buttons now fetch and validate the attachment response
before saving it. An HTTP error, successful-status JSON error without an attachment,
or sign-in redirect does not become a downloaded file or replace the chat page.
The button becomes usable again after failure.

Separately hosted V2 frontends can read `Content-Disposition` through the
existing exact-origin CORS allowlist. No wildcard origin or additional
credential exposure is introduced.

## Responsive behavior

The current integrated UI reproduced **457 pixels** of document width at a
**390 by 844** viewport with expanded navigation. That is a separate current-code
reproduction, not reuse of the older deployment's 754-pixel observation.

`AppShell.tsx` and `Sidebar.tsx` use the existing mobile navigation state to
overlay expanded navigation without changing the desktop collapse preference.
The underlying chat is inert while the mobile rail is open; Escape, navigation,
and the backdrop dismiss it. Opening Share or People also closes the rail so
the participants dialog does not remain inside inert content.
`ChatPage.tsx` and `ConversationDrawer.tsx` keep
smaller-screen drawers within the chat's width rather than squeezing it beside
a fixed-width panel. Generated artifact text wraps long names; tables retain
local scrolling instead of hiding content at page level.

## Regression coverage and acceptance boundaries

The focused regressions execute production functions/components with isolated
provider, storage, and authentication boundaries:

| Coverage | Regression |
| --- | --- |
| Failed planning, exact request reuse, repeated clicks, Stop, deletion/navigation, missing context, ordinary Retry | `ui_tests/test_v2_orchestration_planning_retry.py` |
| Pinned sources versus explicit operations and safe provider/validation diagnostics | `functional_tests/test_orchestration_planner_failure_diagnostics.py`, `ui_tests/test_v2_chat_context_selection.py` |
| Exact CSV/Markdown bytes, legacy files, staged/denied access, changed references/digests, and revocation during reads | `functional_tests/test_chat_artifact_download_bytes.py` |
| Attachment header access for the configured split-origin frontend only | `functional_tests/test_v2_artifact_download_cors.py` |
| Error recovery without navigation, saved findings/evidence, and full-shell narrow-screen behavior | `ui_tests/test_chat_saved_analysis.py` |
| Fresh Supplier/Terms/Governance source text, four factual anchors, accepted findings, saved reload, evidence, and Markdown/CSV values | `functional_tests/test_analyze_three_document_smoke.py` |

Existing saved-analysis, workflow result handoff, publication, calculation,
paging, checkpoint, write-fence, and route-policy regressions remain the
contracts for those unchanged execution/storage surfaces. Deterministic scale
fixtures are not hundreds of live model calls.

The three-document regression runs the real narrative producer with scripted
model responses grounded in the original fictional passages. It checks the
sole-supplier dependency, one-time USD 10,000 convenience termination fee,
unstated dates without claiming absent clauses, and Maya Chen's existing
ownership/quarterly-review controls. It proves data-flow and representation
contracts, not live model judgment or the complete deployed browser workflow.

A new three-document live result, cross-interface reload, factual-oracle review,
and controlled second-account authorization check remain separate live gates.
Opening an old result or completing a production build cannot satisfy them.
Native/mixed deferred-completion limitations remain unchanged.
