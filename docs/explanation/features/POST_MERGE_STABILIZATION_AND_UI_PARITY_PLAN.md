# Post-Merge Stabilization and V1/V2 UI Parity Plan

## Header Information

- Status: **0.261.438 is live on staging; V2 native dropdowns use the shared theme and the Catalog reproduction passed in both themes.**
- Planning version: **0.261.428**
- Prepared: **2026-11-14**
- Initial implementation version: **0.261.429**
- Corrective tranche: **0.261.430–0.261.438**
- Staging application version: authenticated bootstrap reported **0.261.438**.
  The local Development merge uses **0.261.460** in
  `application/single_app/config.py`; it has not been deployed.
- Latest live validation: **2026-11-19 UTC**.
- Pre-merge feature tip: `a8c17078a4e684e2f036eb02afbe7bd5c5b0cf44`
  (`.438`), preserved at `backup/feature-customendpoints-before-development-20261119`.
- Working branch: `feature/customendpoints`
- Reviewed feature base: `a3f9df38470b8e7c6475028bc4464f27c9f3e64e`
- Pinned Development source for the original content integration:
  `5f2390160f1c3274d55ddc311b3b102fdfa415a7`
- Preserved reviewed merge:
  `bf923068ab3d8ae2e286060246ecb9ad6e671f60`
- Pinned Development parent of the local merge:
  `1137910e57d094b5ea97018f3e0b1debc5c25530` (`origin/Development`, `.459`)
- Known tracking issue:
  [microsoft/simplechat#1928](https://github.com/microsoft/simplechat/issues/1928),
  "Embedding-only models appear in V1 and V2 chat model pickers"
- Owner: **TBD**
- Approval scope: post-merge stabilization plus V1/V2 functional parity

This is the durable implementation plan for the failures and UI parity gaps
found after combining the custom-endpoint branch with Development. Keep
`5f2390160f1c3274d55ddc311b3b102fdfa415a7` as the reviewed source for this
effort. Refreshing from a newer Development tip is a separate, reviewed
operation and must not be folded into individual fixes without updating the
baseline and rerunning merge validation.

## Current State — Read This First

The originally resolved source and Responses integration are in the feature
branch. The earlier two-parent merge is preserved on
`wip/feature-customendpoints-development-merge-20261112`, but is not an
ancestor of `.438`. The feature branch picked up the resolved code in
single-parent commit `864bfe8eb`; the only differences from the preserved
merge are a dependency pin and its compatibility test.

On November 19, 2026, a new real Git merge started on `feature/customendpoints`
with `.438` as `HEAD` and `.459` as `MERGE_HEAD`. The ordinary merge reported 491
unmerged paths. Comparing the same two trees against the earlier reviewed
Development snapshot reused existing resolutions for 464 paths and identified
one incorrectly combined clean path. The remaining 27 paths were reconciled
without changing `MERGE_HEAD`. The result was left staged at handoff and is
now recorded locally as two-parent merge `3278ba9bd` with the same reviewed
tree. The live checks below establish staging behavior for their listed builds,
not for the new merged tree.

### Development Merge Handoff (0.261.460)

- All conflicts resolved. The local merge has parents `a8c17078a` and
  `1137910e5`. No push, PR, or deployment was performed during validation.
- Local verification: V2 typecheck and production build; 120 Chromium tests
  for Retry/Stop, credential recovery, catalog, embeddings, workflow history,
  theme behavior, Classic math, and local assets. Focused offline backend,
  route-policy, MCP fingerprint, request-boundary, dependency, and Terms
  checks passed. The two generated docs checks, browser-asset gate, and
  PR-scoped XSS/access-control guards also passed.
- Not PR-green: the Cosmos review gate reports 280 owners and four test doubles
  without matching review evidence (568 diagnostics). The inventory records
  these as `review-required`; no check was weakened. Existing endpoint and
  workflow test-harness failures were reproduced against `.438` and are not
  counted as new merge regressions. The Cosmos gate is the first slice of the
  [Python backend test revamp](./PYTHON_BACKEND_TEST_REVAMP_PLAN.md#first-slice-cosmos-response-contracts),
  which also owns collection and the remaining backend test cleanup.
- The remote `Development` tip advanced to `6613136e` while validating. This
  merge includes the approved `1137910e5` parent, not the later tip.

### Already complete

- [x] Merge reviewed and all conflict regions resolved without dropping either
  reviewed feature set.
- [x] The reviewed stabilization code is deployed and live-tested as **0.261.434**.
- [x] The CP9 dependency conflict is fixed; staging is running the deployed
  image on the reviewed dependency set.
- [x] Embedding-only models are excluded from both visible chat pickers and
  remain available for embeddings.
- [x] Direct chat and Claude/Luna/Terra APIM agents pass in V1 and V2.
- [x] Ordinary and Responses partial Stop, reload and later-turn persistence
  pass for the tested personal paths. Early Stop is accepted once and does not
  continue or attach an older reply incorrectly.
- [x] Shared APIM Responses now has an in-place compatible
  `POST /openai/v1/responses` operation in existing revision 2. No new revision
  or version was created.
- [x] Luna and Terra pass saved-model diagnostics and real V1/V2 Responses
  inference, including V2 SSE and reload persistence.
- [x] CSV `TOTAL=35` passes in staging.
- [x] Workflow provider failures are terminal, safely classified and visible in
  legacy and structured histories.
- [x] Focused Python, affected-owner SDK, browser, route and frontend build
  checks for the .430 scope pass. These checks are not the full repository gate.
- [x] Immediate V2 Retry works without a full reload and preserves the original
  route and attempt chain.
- [x] Claude Legacy core resolves the exact catalog's `toolCalling` capability
  and completes through the existing Messages route.
- [x] Saved APIM Responses editor routing round-trips without the application
  409; both persisted models remain selected as Responses.
- [x] Verified GPT-6 Luna/Terra capacities are available to workflow budgeting:
  1,050,000 context, 922,000 input, 128,000 output and total-generation
  accounting. Luna Chat Completions tools use `reasoning_effort=none`.

### Original implementation defects — resolved

1. [x] **A2-R3:** Fix immediate V2 Retry without requiring a reload.
2. [x] **A4-R4:** Resolve Claude Legacy core's required `toolCalling`
   capability without weakening policy or dropping tools.
3. [x] **UI-R1:** Fix the saved Responses editor/Test Connection 409.
4. [x] **A3:** Supply verified Luna/Terra workflow capacities and add
   capacity-aware workflow limits.

### Remaining validation and closeout

4a. [x] **UI-R2: Unreadable default chat model menu in V2 dark mode.**
    Reproduced on .433 in the expanded Admin Settings → AI Connections menu.
    Verified the **opened** .434 popup in both themes: options and group
    labels are readable, and the saved default was unchanged. Track here only.
5. [x] **GPT-6 mandatory review for text-only tasks.** On .434, Luna Chat
   Completions and Terra Responses both finished with Review complete and
   exact durable artifacts. The older `completeness_no_progress` remains
   valid evidence for its original input. Mandatory review remains enabled.
6. [x] **Reusable staging agent:** Created `Staging Responses Math Smoke Test`
   using the existing SharedAPIM Terra Responses binding and the existing
   built-in Math capability. Retain the agent; it is not the default and no
   global permissions were changed.
7. [x] **Agent/action acceptance:** The retained agent completed a real .435
   Responses run. The persisted .435 message shows one successful
   `MathPlugin.Multiply` invocation and the matching final answer. The
   separate workflow review's missing action identity/count remains open.
8. [x] **Classic route-preview assertions:** All six admin/personal/group
   desktop/mobile cases pass locally on .435. Preview remains opt-in. The
   server rejects invalid routing on Save, preserves the stored endpoint,
   and the modal shows a focused inline error.
9. [x] Record the .434 ACR run, tested digest and rollback candidate.
10. [x] **Stage .435 and verify** classic invalid-route feedback and the V2
    global agent editor's saved-model options on the running image.
11. [x] **Custom Endpoints UI (B0):** Both editors have one per-model
    Request API selector for explicit Custom routes. V2 can author advanced
    routes, and both editors manage optional embedding overrides on the model.
    Dated Azure Responses is deferred.
    - [x] **0.261.436 staging retest:** Saved routes, mixed connection editing,
      the embedding default, native Responses streaming and the retained agent
      were exercised in the shared browser.
    - [x] **0.261.437 staging retest:** Classic and V2 agent editors loaded
      with a disabled explicit route saved. The V2 Method popup was readable
      in both themes (B0-R1 and B0-R2 below).
    - [x] **0.261.438 staging retest:** Shared native dropdown styling passed
      the Catalog reproduction and checks on other V2 surfaces.
12. [ ] Complete two-user collaboration with a second authorized participant.
    TSV upload, live hard-error budgets, and source revocation remain open
    acceptance items. Finish reviewed source-control closeout separately.

### Scope boundaries and follow-ups

- Direct Foundry authentication/401 is **out of scope**. APIM is the approved
  working Responses path, and the direct fallback remains disabled.
- Root pytest collection, the stale workflow access-count assertion, and Cosmos
  review were deferred from stabilization on 2026-11-18. They now belong to the
  [Python backend test revamp](./PYTHON_BACKEND_TEST_REVAMP_PLAN.md): review every
  backend test and aim for near-complete unit, API, functional, and regression
  coverage. UI interactions and browser tests stay outside the revamp. The
  Cosmos review is its first slice because the PR check remains red; no checks
  were waived.
- Dated Azure Responses (`/openai/responses?api-version=...`) is **deferred**.
  Leave the working v1 routes and existing APIM operations unchanged.
- The other B-series parity items remain a separate product backlog, not
  evidence that the original merge failed.

## Purpose

Preserve both reviewed feature sets while correcting the post-merge defects
that affect routing correctness, cancellation persistence, workflow execution,
tabular analysis, and V1/V2 task parity.

The existing routing architecture is the correct direction. Endpoint CRUD,
schema-v2 per-model APIM routing, direct chat, Responses baseline behavior,
agent model selection, API-key handling, and XSS-safe rendering passed the live
review. This plan corrects the surrounding contracts instead of replacing
the merged routing design.

## Evidence Baseline

The initial, pre-stabilization deployed review completed 46 tracked checks:

| Result | Count |
|---|---:|
| Passed | 36 |
| Failed | 9 |
| Blocked by missing safe staging fixture | 1 |

Original confirmed failures, before the 0.261.429 stabilization deployment:

1. V1 and V2 expose `text-embedding-3-small` as a chat model.
2. V2 Stop terminates a stream but discards ordinary partial assistant output.
3. V2 Responses cancellation also discards partial output.
4. SharedAPIM GPT-6 Luna and GPT-6.1 Terra workflows resolve the correct route
   and protocol but are blocked by missing token-capacity metadata.
5. SharedAPIM Claude Messages workflows enter `Waiting for recovery` without
   a durable, user-safe provider diagnostic.
6. CSV aggregate/query tools repeatedly receive Excel-only selectors.
7. CSV analysis retries until the source becomes unavailable and never returns
   the expected `TOTAL=35`.
8. Responses tool execution lacks a staging fixture even though the test seam
   exists locally.
9. V1/V2 cancellation behavior is inconsistent after a partial response.

Three independent read-only analyst passes reviewed the merge failures, and
three analyst passes ran for V1/V2 parity. The two code-backed UI reviews
converged on the material parity recommendations; the Sonnet UI pass was
partial and is retained only as a verification backlog. The course below
reconciles the completed reviews against the current staged source.

The current results are recorded under
[Staging retest: 0.261.429](#staging-retest-0261429). The initial results above
remain historical evidence, not the current pass/fail inventory. The admin
deferred GitHub issue creation and updates for this tranche; this document
records the follow-ups without making GitHub changes.

## How to Maintain This Plan

Use the checkboxes in this document as the implementation ledger.

- Mark an implementation checkbox only after the behavior and its tests are in
  the reviewed branch.
- Record the pull request, commit, test command, and validation evidence in the
  progress log.
- Do not mark a staging checkbox without the ACR run or image digest and the
  application version actually tested.
- Keep blockers visible. Do not remove a failed acceptance criterion by moving
  it to a later phase.
- Add one issue reference for every release-blocking work item. Use
  `microsoft/simplechat#1928` for the model-eligibility item; create or link the
  remaining task issues before implementation begins.
- This plan is documentation. A code change still requires the repository's
  normal version increment in `application/single_app/config.py`.

Status vocabulary:

- **Not started**
- **In progress**
- **Blocked: <reason>**
- **Implemented locally**
- **Staging verified**
- **Done**

## Release Gates

The merge must not be promoted while any of the following is open:

- [x] V2 retains and labels partial assistant output after Stop in staging
  for personal ordinary chat and the known staging-resource Responses route.
- [x] V1/V2 ordinary and Responses cancellation has equivalent tested
  stopped/incomplete semantics for the personal staging scenarios covered.
- [x] Known embedding-only models are absent from deployed chat selection
  payloads.
- [ ] SharedAPIM GPT-6 Luna/Terra workflows use verified limits and reach
  inference, or fail with a deliberate configuration error before queuing work.
- [x] SharedAPIM Claude workflow failures become durable and diagnosable without
  unsafe replay.
- [x] A synthetic staging CSV returns exactly `TOTAL=35`.
- [ ] Repeated identical tabular tool errors terminate within one request-wide
  retry budget in staging.
- [x] Responses tool-call, continuation, denial, cancellation, malformed-
  argument and exact-once automated tests pass locally. Live action evidence
  remains a separate staging gate.
- [x] V1 and V2 preserve the tested original, authorized endpoint/model/scope
  route.
- [ ] No secrets, raw provider bodies, private reasoning, or unsafe URLs appear
  in browser responses, audit records, workflow recovery payloads, or logs.
- [x] The reviewed dependency set deployed successfully through the repository's
  ACR/App Service path.
- [ ] Full Python and relevant V2 frontend/browser validation passes.
- [ ] The tested image digest and rollback digest are recorded.

## Workstream A: Post-Merge Stabilization

### A0. Preserve the Reviewed Merge and Build State

Priority: **P0**  
Status: **.430 deployed by admin; reviewed commits and rollback evidence remain**  
Dependencies: None

The merge and source pin are themselves part of the safety contract. Do not
rebase, recommit, push, or deploy the staged merge as an incidental side effect
of fixing a post-merge issue.

#### Checklist

- [x] Preserve the original reviewed merge tree on
  `wip/feature-customendpoints-development-merge-20261112`.
- [x] Independently advance to the reviewed current repository checkpoint
  `864bfe8eb` (`init merge v2`); do not reset to an obsolete feature head.
- [x] Confirm there are no unresolved merge paths or active Git merge operation.
- [x] Diagnose the CP9 dependency conflict.
- [x] Set `cryptography==46.0.7` in the staged tree and verify local
  resolution with Snowflake 4.7.3.
- [ ] Apply the stabilization fixes in reviewed implementation commits.
- [x] Rebuild through ACR; do not use a local container build as acceptance.
- [x] Record the tested ACR run and immutable image digest. Final .433 run:
  `cpf`.
- [x] Deploy/update staging and verify the configured SimpleChat health route,
  `/external/healthcheck`. `/api/health` and `/api/ready` are not applicable
  SimpleChat health routes.
- [ ] Record the previous digest and verify the rollback command.

#### Acceptance Criteria

- No dependency resolver failure occurs in ACR.
- The deployed image digest exactly matches the tested ACR output.
- App Service continues to use managed identity for ACR access.
- No ACR password, admin credential, or SCM publishing credential is introduced.

---

### A1. Centralize Chat Model Eligibility

Priority: **P1**  
Status: **Staging verified for the configured global chat menus; broader scope gates remain**  
Tracking: `microsoft/simplechat#1928`  
Dependencies: None

#### Confirmed Root Cause

`application/single_app/functions_chat_model_catalog.py` contains the shared
catalog builder and has the capability-filtering machinery available.
`application/single_app/route_frontend_chats.py` shadows the imported helper
with a local `_build_chat_model_catalog` that iterates endpoint models without
calling `filter_model_endpoints_by_capability`. V2 bootstrap consumes the
V1-route catalog, so both UIs inherit the same leak.

The legacy single-endpoint branch in the shared builder must also apply a
model-level chat-capability rule. The multi-endpoint branch must remain the
source of truth for global, personal, and group scopes.

#### Required Changes

- [x] Remove the duplicate local `_build_chat_model_catalog` in
  `route_frontend_chats.py`, or replace it with a thin delegation to the shared
  helper with identical arguments and output.
- [x] In `functions_chat_model_catalog.py`, apply the same authoritative
  capability predicate in legacy, global, personal, and group branches.
- [x] Reuse `filter_model_endpoints_by_capability(..., "chat")` and the
  established `supports_model_capability`/`resolve_model_capability` path.
- [x] Filter disabled and explicitly non-chat-capable models before selection
  metadata is serialized.
- [x] Apply the same filtering to `_build_initial_chat_model_selection` and
  V2 bootstrap.
- [x] Preserve server-side `require_model_capability` checks at request,
  retry, edit/resend, agent, workflow, and orchestration boundaries.
- [ ] For an unavailable saved selection, show an actionable unavailable state.
  Do not silently substitute another endpoint or model.
- [ ] Do not use display-name substring matching as the primary filter.

#### Affected Components

- `application/single_app/functions_chat_model_catalog.py`
- `application/single_app/route_frontend_chats.py`
- `application/single_app/functions_ai_connections.py`
- `application/single_app/route_backend_v2.py`
- V1 chat model selector
- V2 bootstrap and model/agent pickers

#### Acceptance Criteria

- [x] V1 and V2 chat picker payloads contain the same eligible configured global
  chat models.
- [x] `text-embedding-3-small`, Ada embedding deployments, Cohere embedding
  deployments, and other explicit embedding-only models are absent.
- [x] Embedding-only models remain available in embedding workflows.
- [ ] A model supporting chat and embeddings remains in both capabilities.
- [ ] Unknown legacy deployment names remain supported only under the existing
  compatibility policy.
- [ ] A manually submitted embedding-only chat selection is rejected
  server-side.
- [ ] Personal and group scopes apply the same rule after governance filtering.
- [ ] Stale, disabled, or revoked selections fail safely without fallback to an
  unrelated model.

#### Validation

- [ ] Add catalog unit coverage for legacy, global, personal, group, mixed-
  capability, disabled, and stale-selection cases.
- [ ] Add V1 and V2 picker/bootstrap assertions.
- [ ] Add request-time rejection coverage.
- [x] Rerun endpoint CRUD and APIM chat regressions to prove routing was not
  weakened.
- [x] Verify the configured global V1/V2 menus omit `text-embedding-3-small`
  while its saved embedding capability remains available.

---

### A2. Preserve V2 Partial Content on Stop

Priority: **P0**  
Status: **Personal Stop/reload and early Stop live verified; immediate Retry and collaborative acceptance remain open**  
Dependencies: Stable server cancellation behavior

#### Confirmed Root Cause

`application/v2_ui/src/stores/chatStore.ts` preserves `streamingContent` only
for an admitted retry presentation. Ordinary Stop calls detach the stream and
clear the active stream state. The server may persist the partial reply later,
but the user-visible V2 message is removed immediately. The same path affects
normal and Responses streams.

#### Required Behavior

Stopping is a terminal UI transition, not only an abort operation.

1. Snapshot the accumulated assistant content, thought entries, citations,
   reasoning adjustments, originating conversation, user-message identity, and
   retry presentation before detaching.
2. Cancel the correct personal or collaborative server stream.
3. Keep a provisional assistant message when partial text exists.
4. Mark the message or turn as stopped/incomplete.
5. Reconcile the provisional message with the server's eventual persisted
   message by stable turn/message identity, replacing rather than duplicating.
6. Preserve V1 behavior and leave explicit navigation detach-only.

If Stop occurs before any assistant text arrives, do not fabricate an assistant
answer. Show a stopped-turn state associated with the user message.

#### Required Changes

- [x] Add one cancellation finalizer in `application/v2_ui/src/stores/chatStore.ts`
  used by ordinary, retry, Responses, and collaborative streams.
- [x] Apply the same status metadata to all tested personal partial-stop paths:
  - `status: interrupted` or `stopped`
  - `complete: false`
  - `stop_reason: user_cancelled`
- [x] Reconcile provisional and persisted messages by conversation and turn
  identity.
- [x] Do not allow late deltas from the stopped request to overwrite another
  conversation or resurrect a completed stream.
- [x] Preserve cancellation errors separately. If the server cannot confirm
  cancellation, retain the partial response and show uncertainty.
- [x] Re-run sanitization/rendering on retained partial content.

The historical .429 staging retest reopened the four contracts above: its
stopped label was lost during reconciliation/reload, and early cancellation
returned 404 while generation continued. The .430 live retest below verifies
the corrected personal paths. It does not establish live collaborative or
every completion-race outcome.

#### Acceptance Criteria

- [x] V2 visibly shows the partial text before and after reload.
- [x] The tested partial message remains labeled stopped/incomplete after
  reload and a later turn.
- [x] Stop before first content shows an interrupted-turn state without a blank
  assistant answer.
- [x] A stop/completion race resolves deterministically in focused owner
  tests; completed server output wins once completion is known.
- [x] Navigating away while one stream is active detaches without
  cancelling the background request.
- [x] Tested normal and Responses streams behave consistently in staging.
- [x] Tested V1 behavior remains correct.

#### Validation

- [x] Browser tests cover normal chat, Responses, pre-token Stop, post-token
  Stop, completion races and navigation detach. Immediate Retry and live
  two-user collaboration remain separate open checks.
- [ ] Hostile partial content remains inert.
- [x] V1 regression check for partial retention.
- [x] Add a full reload assertion for persisted stopped/incomplete metadata.
- [x] Add a pre-admission Stop/404 regression that checks eventual server
  completion and prevents reassociation of an older reply.

---

### A3. Propagate Verified Workflow Token Limits

Priority: **P0**  
Status: **Live routing and verified-capacity gates passed; completeness remains separately tracked**  
Dependencies: Administratively verified model limits

#### Confirmed Root Cause

The schema-v2 route correctly preserves the endpoint, model, protocol, and
request target. However, `gpt-6-luna` and `gpt-6.1-terra` do not have matching
catalog records or saved token-limit overrides. Workflow budgeting therefore
resolves all limits as unknown and applies the disclosed 8,192-token
compatibility policy. After the 256-token safety margin, the observed available
input budget is 7,936 tokens.

The 12,289-token input is blocked before provider inference. This is expected
fallback behavior, not proof that the APIM route is wrong.

#### Required Changes

- [x] Add or complete schema-v2 model metadata support for:
  - `contextWindow`
  - `inputTokenLimit`
  - `outputTokenLimit`
  - `outputTokenAccounting`
  - `modelVersion` when required
  - `catalogModelId` when a verified exact catalog profile exists
- [x] Expose verified text-generation limit overrides in the AI Connections
  model metadata/capacity surface for catalog-unknown custom models.
- [x] Round-trip these values through normalization, revisioning, Key Vault
  hydration, route resolution, workflow client construction, and background
  execution.
- [x] Ensure `wrap_workflow_model_client` resolves limits from the authoritative
  model and endpoint records without changing the route protocol.
- [x] For unknown workflow models, return an explicit configuration error
  before inference when the application cannot verify safe request and
  response limits. Do not silently assume GPT-5 or another model's capacities.
- [x] Add reviewed exact catalog profiles only after the provider capacities,
  tokenizer/accounting, and version semantics are verified.

#### Open Decision

- [x] Supply verified context, input, output, and total-generation limits for
  GPT-6 Luna and GPT-6.1 Terra. No implementation may infer these from names,
  aliases, or neighboring model families.

#### Affected Components

- `application/single_app/functions_model_capabilities.py`
- `application/single_app/functions_workflow_context.py`
- `application/single_app/functions_workflow_runner.py`
- Schema-v2 model endpoint normalization and routing
- AI Connections model capacity metadata
- Workflow model-binding summaries

#### Acceptance Criteria

- [x] A request larger than the historical 12,289-token blocker reaches
  inference when the verified configured limit permits it. Live .433 producer
  inputs were about 60,700 tokens.
- [x] Endpoint/model/route identity remains unchanged. Luna uses its existing
  Chat Completions route; Terra's tool workflow uses the selected Responses route.
- [x] An input beyond the verified boundary is durably blocked and not
  truncated.
- [x] Output reservation, safety margin, and total-generation accounting remain
  explicit.
- [x] Unknown custom models produce `model_context_unavailable`-class guidance
  instead of silently assuming a sufficiently large window.
- [x] Legacy gpt-5.6-terra control behavior remains unchanged.

#### Validation

- [x] Extend `functional_tests/test_workflow_context_budget.py`.
- [x] Add schema-v2 custom model round-trip tests.
- [x] Test model-over-endpoint-over-catalog precedence.
- [x] Test exact numeric boundaries and invalid overrides.
- [x] Run live Luna and Terra workflows after staging verified limits. Producer
  outputs and known budgets were visible; the existing mandatory completeness
  checker remained a separate outcome, not a routing/capacity failure.

---

### A4. Make Workflow Provider Failures Durable and Safe

Priority: **P0**  
Status: **Claude core and legacy/structured failure diagnostics live verified**  
Dependencies: None

#### Confirmed Root Cause

`functions_workflow_structured_execution.py` records a failed non-replay-safe
unit and enters recovery when `workflow_policy_failure(exc)` returns no
application-owned classification. Provider/protocol exceptions can therefore
leave a Claude Messages task in `Waiting for recovery` with no durable,
user-safe result. Recovery is correct for ambiguous effects but is not an
adequate substitute for classifying definitive provider failures.

#### Required Changes

- [x] Introduce a typed model-provider/workflow failure classification.
- [x] Include:
  - stable public error code
  - safe public message
  - correlation reference
  - failure phase
  - effect certainty: `none`, `possible`, or `confirmed`
  - retry guidance
- [x] Map deterministic failures to terminal states:
  - request construction/validation failure
  - unsupported operation
  - 400/401/403-style rejection
  - malformed deterministic response
  - redacted provider configuration error
- [x] Preserve recovery for uncertain outcomes after a possible external
  action, interruption, or crash.
- [x] Persist and expose the safe classification before the UI is placed into
  recovery.
- [x] Never automatically replay the full action-capable task merely because
  inference failed.
- [x] Keep arbitrary provider exception bodies, headers, URLs, and credentials
  out of browser, audit, and workflow-recovery serialization.
- [x] Render stored task error codes and safe messages in V2 run history,
  including failures without a durable successful result.
- [x] Resolve the Claude legacy-capability/completeness-verification failure.
- [x] Trace the isolated missing-deployment recovery case to its actual
  failure phase and provider status before deciding whether replay is safe.

#### Affected Components

- `application/single_app/functions_workflow_policy_errors.py`
- `application/single_app/functions_workflow_structured_execution.py`
- `application/single_app/functions_workflow_execution.py`
- `application/single_app/functions_workflow_runner.py`
- Model endpoint diagnostics and client adapters
- Workflow run history/runtime UI

#### Acceptance Criteria

- [x] Definitive failure before external effects finishes as a terminal,
  diagnosable failure.
- [x] Ambiguous post-effect failure remains recoverable and non-replay-safe in
  focused owner tests.
- [x] The run history states what is safe to do next.
- [x] Cancellation from recovery remains idempotent in focused owner tests.
- [x] A completed result cannot later be replaced by a recovery gate in
  focused owner tests.
- [x] Refresh/reconnect produces the same tested terminal state.
- [x] The tested diagnostics contract covers Claude Messages, custom Chat
  Completions and legacy Azure. Responses provider diagnostics remain covered
  by the same adapter boundary; live action-specific evidence is separate.

#### Validation

- [ ] Extend `functional_tests/test_workflow_policy_failures.py`.
- [ ] Add deterministic Claude 400/401/403/429 and malformed-response tests.
- [ ] Add timeout-before-effect and timeout-after-possible-effect tests.
- [ ] Add crash checkpoint and cancellation-race tests.
- [ ] Add redaction/XSS tests for provider error bodies.
- [x] Re-run a safe SharedAPIM Claude workflow in staging and record its
  correlation reference and terminal result.

---

### A5. Make Tabular Tools Format-Aware and Bounded

Priority: **P0**  
Status: **Staging verified for the three-row CSV; schema and error-budget gates remain**  
Dependencies: A4 safe failure taxonomy recommended

#### Confirmed Root Cause

The public tabular tool contract exposes worksheet selectors generically.
For a CSV, the model sent `header_row=0`; normalization accepted the value,
and the later CSV reader rejected it as an Excel-only selector. The model
retried alternate invalid selector combinations. Before 0.261.429, the retry loop allowed
up to three analysis passes and up to 20 auto-invocations per pass. Repeated
error feedback did not terminate the request early, and the source eventually
became unavailable.

#### Required Changes

- [ ] Supply format-aware tool schemas and instructions:
  - CSV/TSV calls omit `table_id`, `cell_range`, `sheet_name`,
    `sheet_index`, and `header_row`.
  - Excel calls retain genuine worksheet/table/range/header selectors.
- [x] At the format boundary, normalize empty, `None`, `0`, and `"0"` header
  values as "selector omitted" for CSV.
- [x] Preserve `header_row=0` as "no header" for Excel worksheets.
- [x] Reject non-zero CSV header rows and non-empty table/range selectors with
  one structured, non-retryable `excel_only_selector` error.
- [x] Include the corrected valid call shape in the tool error.
- [x] Bound repeated-equivalent failures across the entire user request, not
  once per outer retry pass.
- [x] Do not repeat an identical function+arguments+error combination.
- [x] Keep the source authorization binding and blob context stable across
  corrected attempts.
- [x] Terminate with a clear user-safe result when the request-wide budget is
  exhausted. Do not continue to synthesize from missing or lost evidence.
- [x] Allow the existing deterministic CSV aggregation path to proceed without
  Excel metadata selection.

The implementation updates selector descriptions and boundary normalization.
The successful live CSV test does not establish that Excel-only fields are
removed from every advertised CSV tool schema, that TSV is supported end to
end, or that pathological live retries respect the hard invocation ceiling.

#### Affected Components

- `application/single_app/semantic_kernel_plugins/tabular_processing_plugin.py`
- `application/single_app/route_backend_chats.py`
- Tabular system-prompt/schema construction
- Native analysis result and coverage reporting
- Document/source authorization continuity

#### Acceptance Criteria

- [x] The supplied three-row CSV returns exactly `TOTAL=35`.
- [ ] A CSV call with `header_row=0` is normalized or rejected once and never
  loops.
- [ ] CSV selectors do not appear in the model's advertised valid tool schema.
- [x] A workbook with a standard header preserves worksheet/table/range
  selection: the live .434 `FixtureTotals`/`StageValues` `B2:B3` test
  returned `XLSX_TOTAL=38` and did not include the other sheet or B4.
- [ ] Repeated identical errors terminate within the request-wide invocation
  budget.
- [ ] Failed tabular analysis retains the source coverage record and does not
  claim successful evidence.
- [ ] A revoked source remains revoked; retries do not restore access.

#### Validation

- [ ] Extend `functional_tests/test_v2_tabular_parity.py`.
- [ ] Add CSV, TSV, XLSX, multi-sheet, table, and explicit-range tests.
- [ ] Add `0`, `"0"`, empty, null, float, boolean, and non-zero header cases.
- [ ] Add repeated-identical-error and total-invocation-budget tests.
- [x] Re-run the synthetic CSV through V2 after deployment.

---

### A6. Complete Responses Tool-Execution Coverage

Priority: **P1**  
Status: **Live .436 Responses agent invocation and direct streaming verified; workflow review evidence remains open**  
Dependencies: A2 cancellation fix recommended

#### Finding

The Responses tool seam exists. Local tests already exercise the real SDK and
Semantic Kernel tool loop with mock HTTP. The live gap was fixture availability:
no staged agent had a configured action.

On .434, a disposable Legacy-core workflow on Terra Responses produced the
correct tool-backed Math value from one successful result and two producer
requests. The mandatory checker could not establish the tool's identity or
complete invocation history and ended `completeness_no_progress`. This was a
workflow smoke test, not the dedicated local-agent acceptance test. Do not
replay actions or waive review to make a run pass.

#### Required Changes

- [x] Extend
  `functional_tests/test_responses_model_tool_execution.py` for:
  - application action registration
  - authorization denial
  - exact endpoint/model preservation
  - complete and partial tool arguments
  - duplicate tool calls
  - malformed arguments
  - tool exception
  - cancellation before and during tool execution
  - private continuation isolation
  - final response after tool output
- [x] Use a deterministic local-only action with no network, filesystem,
  database, or external side effect.
- [x] Retain the staging-only `Staging Responses Math Smoke Test` local
  agent, with no assigned knowledge or configured external actions. It uses
  the already-enabled Math capability; do not broaden workspace or
  built-in tool policy to make the test pass.
  [Open the fixture on staging](https://simplechat-2026stage-app.azurewebsites.net/v2/chat?agent_id=e8d5a44d-2510-415d-8b9a-05c6611139ed&agent_scope=global&new=1).

#### Acceptance Criteria

- [x] A complete tool call executes exactly once in the automated SDK test.
- [x] Partial tool arguments never execute.
- [x] A denied or invalid action is not retried as an allowed action.
- [x] Private reasoning continuation never reaches browser JSON, exports,
  logs, or subsequent user turns.
- [x] Cancellation does not replay a completed tool call in the automated test.
- [x] Removed the failed synthetic conversation; retained the reusable agent
  and its one successful synthetic example for future validation.

#### Streaming Follow-Up (0.261.435 baseline and 0.261.436 retest)

Offline probes using the real SDK adapters on a mock HTTP transport delivered
the first text delta before the upstream terminal event was allowed, for both
direct chat and the Semantic Kernel agent. Both still reported terminal
usage. The App Service chat handler forwards ordinary text chunks while
also accumulating a copy for persistence; it does not wait for that copy
to be complete.

In .435, the direct Responses adapter's completed-object fallback split an
already-finished reply into synthetic chunks. In .436 it emits the accepted
text, terminal metadata and any complete tool calls together, matching the
agent's one-chunk treatment. Native upstream deltas are unchanged. A plain HTTP JSON
response to `stream=True` through the installed SDK is a different case:
it ended without a terminal event in the probe.

- [x] Observe first visible text and completion in the browser. Direct Terra
  Responses produced visible partial text at about 3.0 s and finished at about
  5.0 s; the Stop control was still visible at first text. The retained agent's
  short Math reply appeared at about 7.2 s and finished at about 7.4 s, including
  the tool round trip. These are sample browser timings, not a latency comparison
  between equivalent requests.
- [ ] Measure App Service receipt of first provider text and its first outgoing
  text event separately. Browser timings do not establish those server timings.
- [x] Keep native Responses text incremental. When the direct adapter
  accepts an already-completed reply, emit it once, as the Responses
  agent does. Report incompatible responses explicitly; do not silently
  issue a second model request or change other adapters.
- [ ] Keep tests for genuine early text with a gated terminal event, late
  usage, Stop and partial persistence, and one complete authorized tool
  invocation. Preserve private reasoning and deliberate output holds
  such as raw structured file generation.
- [x] Recheck the one-chunk completed-object fallback in the
  [focused regression](../../../functional_tests/test_responses_model_tool_execution.py).
  The staging provider returned native streams; the completed object was forced
  only in the local test.

---

## Workstream B: V1/V2 Functional Parity

### Parity Principles

1. V2 is the canonical authoring and deep-link experience for agents, actions,
   workflows, reviews, approvals, and workspace administration.
2. V1 remains a supported compatibility chat surface. Do not duplicate React
   editors into V1.
3. A control being present is not proof of parity. Compare authorization,
   route identity, persistence, cancellation, recovery, and resulting state.
4. Backend contracts, authorization, capabilities, revisions, and audit records
   are shared; presentation components may remain framework-specific.
5. V2 route guards are not authorization. Every backend endpoint remains the
   authority.
6. Do not classify a V1 feature as missing from V2 without a route, test, and
   backend contract check.

---

### B0. Port Advanced Custom Endpoint Authoring to V2

Status: **0.261.436 main flows, 0.261.437 agent settings and 0.261.438 native dropdown fixes verified on staging.**

Earlier publisher preflight attempts were denied registry read access and
performed no deployment. The later shared-browser pass confirmed **0.261.436**
was already running and returned `200` for authenticated bootstrap and
`/external/healthcheck`. The retest did not build, deploy, or confirm an ACR digest.

| Capability | V2 status in the local 0.261.436 build |
|---|---|
| Add a Custom connection | Admin → AI Models → AI Connections, or the authorized personal or group Endpoints section. New Custom connections use explicit model routes and start disabled. |
| Change an existing connection | Credentials still belong to the connection. Legacy connections keep their existing controls and routing; saving does not silently convert them. |
| Author or inspect different routes per model | Request API, gateway path/order, URL handling and version are editable on each model. Preview Route is read-only and requires no provider credentials. Explicit diagnostics use the saved route. |

#### Request API Changes

- [x] Replace the competing API Type and Chat API labels with one
  per-model **Request API** choice in Classic and V2. Use the existing
  supported combinations, including OpenAI-compatible `/v1/responses`,
  Azure/Foundry `/openai/v1/responses`, and a separate Anthropic Messages
  option. Keep versioned Chat Completions; do not add dated Responses.
- [x] Port per-model routing and Preview Route to the shared React editor.
  At desktop and mobile widths, local browser tests create a mixed gateway
  fixture, preview the exact Responses URL, save once, reopen, and test the
  saved model. Existing scope and concurrency checks remain in force.
- [x] Reopen the real saved APIM route in both editors on staging and
  verify the exact preview and saved-model diagnostics without editing it.

#### Embedding Model Refactor

Models own their optional embedding route, dimensions, token limits, and
revision metadata. `ModelBinding.operation_settings` honors the selected model
first and inherits legacy connection operation settings when no override exists.

- [x] Remove the standalone **Embedding inference** panel from the
  Classic and V2 AI Connections editors. Move its editing, validation,
  and runtime routing code into the AI Connection model's embedding
  configuration. Add a regular model, publish it for embeddings, and put
  optional route overrides under that model's advanced settings.
- [x] Keep default-model selection and testing in the Embeddings view.
  Show the selected model's effective route and validation there, with a
  link back to its AI Connection model for edits rather than a second
  routing form.
- [x] Preserve effective routes for imported and mixed connections. An
  embedding model with no override must still inherit any already-saved
  embedding operation settings before falling back to connection defaults.
  Keep credentials on the connection and enforce existing outbound and
  credential rules. Do not copy secrets into model rows, switch defaults,
  change vector-space identity, or rebuild existing vectors on upgrade.
- [x] Verify locally a regular model using inherited defaults, an imported model
  with a preserved override, and two embedding models on one connection
  using independent routes. Keep unsupported combinations unavailable and
  embedding-only models out of chat choices.
- [x] Verify the existing embedding default's route, jump to its model,
  and run its saved inference test on staging without changing the default.
- [x] Record the .436 ACR run and immutable image digest. Run `cpj` was
  confirmed from the .437 pre-deployment image and ACR run history; .436 was
  not republished.

#### 0.261.436 Local Validation

- **59 focused Chromium cases passed**, covering Classic and React,
  desktop/mobile, Classic scopes, preview and single-save behavior,
  model-owned embedding overrides, and both links from Embeddings.
- **273 focused functional and documentation tests and 108 subtests
  passed**, plus **30 route-policy tests**. Coverage includes actual SDK
  request URLs and headers with synthetic transports, equivalent embedding
  profile identity, rejected invalid overrides, and the one-chunk Responses
  fallback. React typecheck and production build also passed.
- Repository-wide collection and the global Cosmos review remain deferred.
  Live checks used the signed-in global admin; personal and named-group
  routing coverage was local, not live in this pass.

#### 0.261.436 Shared-Browser Staging Evidence

| Check | Result |
|---|---|
| V1/V2 saved Responses | Both editors exposed one **Request API** per model with both v1 Responses formats, dated Chat Completions, and separate Anthropic Messages. Luna and Terra previews and saved tests all returned 200 at `POST /shared-foundry;rev=2/openai/v1/responses`, with saved path order intact. No permanent route was edited. |
| Other saved APIM operations | V2 saved diagnostics returned 200 for Terra Chat Completions and Claude Anthropic Messages on their distinct routes. |
| Mixed connection authoring | A disposable disabled connection held OpenAI `/v1/responses`, Anthropic Messages, and two model-specific embedding bases. V2 previews matched the exact composed paths; an invalid full URL returned typed 400 and kept the editor open. Corrected Save was one POST (201), without an automatic preview. Classic reopened all four rows and cleared one embedding override in one PATCH (200) without changing the other, the wire routes, model IDs, or stored credential marker. V2 reopened the result. No provider inference was sent to the synthetic host. |
| Existing embedding default | Both UIs showed the effective versioned Azure route and opened the correct `text-embedding-3-small` model. Both saved tests returned 1,536 dimensions and left the default and vectors untouched. The embedding-only model was absent from the V2 chat picker. |
| Native Responses and Stop | Direct Terra used the saved Responses endpoint/model with HTTP 200 SSE. Text grew after first render, Stop returned 200, the partial reply survived reload, and the next turn used the same route. |
| Retained Responses agent | V2 received HTTP 200 SSE. After reload, Sources showed exactly one successful `MathPlugin.Multiply` for `26741 × 593` and the matching final answer `15857413`. The conversation-context entries were not additional Math calls. |
| Cleanup | The disposable connection and two new test conversations were removed. The prior .435 example and reusable agent remain. The original personal chat model selection was restored; the shared browser was returned to Classic AI Connections. No APIM, roles, saved defaults, production, or GitHub changes. |

#### B0-R1. Classic Agent Settings Fail With an Empty Explicit-Route Projection

- [x] Normalize and redact authorized saved connections before filtering chat
  choices. V2 global, personal and group option builders reproduced the same
  defect locally; they now also use complete saved records rather than
  revalidating a redacted projection. Keep strict save validation and existing
  access and credential rules.
- [x] While a disabled schema-v2 connection was still saved, Classic Agents
  settings and V2 global agent options returned 200. Both model lists loaded
  and omitted the fixture model. Local regressions cover the same projection
  and saved-route validator, including the personal and group option builders.

Classic `GET /api/admin/agent/settings` failed with 500 while the disposable
connection existed and returned 200 after deletion. A local probe using the
actual filter and route validator reproduced the failure: filtering a disabled
connection with `preserve_empty=True` keeps its schema marker but gives it
`models: []`; the subsequent sanitizer tries to normalize that projection as
a complete saved route and rejects it with “Add at least one model to the
connection.” The connection saves correctly, but Classic agent settings can
fail to load. App health, the AI Connections editors, Embeddings, and the
retained agent's chat all passed their checks.

#### B0-R2. V2 Native Dropdown Contrast

- [x] Apply the same opaque theme surface to native option rows in the
  shared AI Connections editor and default-model pickers. Keep the native
  control, labels, keyboard behavior and save flow.
- [x] Visually verify the open **Authentication → Method** menu in dark and
  light modes in the .437 staging browser without saving a connection change.
- [x] Fix the shared V2 theme so all native `<select>` option lists get
  readable colors without per-component wrappers.
- [x] Verify the actual opened Catalog popup on staging after the fix,
  plus a representative menu outside Admin Settings and the previously
  tested connection and default-model pickers.

The .434 fix styled only default-model picker rows. On .436, Method
options had pale text and no opaque background; the operating system
could render that text against a white popup. The .437 browser regression
opens the affected menus and checks opaque backgrounds and at least 4.5:1
contrast for enabled options in both themes.

The .437 pass verified only the named menus, not V2 as a whole. The
user-reported **Model Catalog → Connections** menu still showed nearly
invisible options. Reproduced on .437: the option foreground is correct
for dark mode, but its own background is transparent because the menu is
outside both opt-in wrappers.

#### 0.261.438 Local Dropdown Validation

- The V2 theme now supplies foreground and opaque background colors directly
  to native option and optgroup rows. It does not depend on editor-specific
  wrappers, so new native selects also inherit the treatment. Native
  interaction and disabled states are retained; Classic and custom listbox
  implementations are unchanged.
- Catalog and personal-agent regressions failed on the .437 build with
  transparent option rows. After rebuilding .438, **10 focused Chromium
  cases passed**: the Catalog Connections filter, a My Workspace agent model
  picker at desktop and mobile widths, and the previous Method and default
  model menus, all in light and dark themes. Checks include opaque option
  backgrounds, at least 4.5:1 contrast, and keyboard filter selection.
- V2 typecheck and production build passed. The .437 popup screenshots
  cover only the earlier, narrower fix.

#### 0.261.438 Staging Dropdown Verification

| Check | Result |
|---|---|
| Build and runtime | ACR `cpm` succeeded on 2026-11-19 UTC. App Service was pinned to `sha256:3dda69cb96070cbb93bf976ecc9dcf43cb611fc97d98b6724e5f7b3009b80504`; .437 image `cpk` remains the rollback candidate. Authenticated health and bootstrap both returned 200; bootstrap and the refreshed V2 header showed .438. |
| Reported Catalog menu | Opened **Model Catalog → Connections** in the shared browser. All three native options were visibly readable in dark and light, including the unselected options shown in the report. Keyboard selection updated the profile list; the filter was restored. |
| Admin Settings | Audited 161 enabled option/optgroup rows across 34 enabled native selects in the rendered dark **All settings** view. None had transparent backgrounds or contrast below 4.5:1. Visually checked the opened grouped Default chat model and Authentication Method menus; no defaults or connections were saved. |
| Outside Admin Settings | Visually checked **My Workspace → New workflow → Runner type** in dark mode. All 34 enabled rows across 12 enabled selects in that editor used the dark theme colors, and disabled capability options stayed disabled. Cancelled without creating a workflow. The separate custom Chat model picker still opened and closed normally. |
| Cleanup | Returned the shared tab to the Catalog with the original dark theme and **All profiles** selection. No model calls, permanent configuration changes, or GitHub issue. These are representative UI checks, not a claim that every route or browser was exercised. |

#### 0.261.437 Local Validation

- **33 focused backend cases** and **30 route-policy cases** passed. The
  regressions reproduce the Classic HTTP 500 and the same V2 option-building
  failure, then verify both keep the active Responses model, exclude disabled
  and embedding-only models from chat, and omit connection details and keys.
- **6 focused Chromium cases** passed, including the open Method, Provider,
  Identity and Management cloud menus in both themes and the existing grouped
  default picker. React typecheck, production build and docs checks passed.
- Legacy live-app tests and unrelated text-consumer harness failures are not
  counted as passes. The previously deferred full-suite work remains separate.

#### 0.261.437 Staging Retest

| Check | Result |
|---|---|
| Build and runtime | ACR run `cpk` succeeded on 2026-11-19 UTC. App Service was pinned to `sha256:b326b4133ba1acd279688233e15d2d79d7c2cc13cb73e99c3d23e5e8d7bf00ed`. Authenticated bootstrap reported .437; bootstrap and `/external/healthcheck` both returned 200. The existing registry-scoped `AcrPull` assignment was verified. |
| Rollback candidate | .436 ACR run `cpj`, `sha256:c3dc3d940839d9bb86de53c8872669fbf73a33259fb3caa467789fccfd09e7ac`; manifest verified before publishing. No rollback performed. |
| Classic and V2 agents | With one disabled schema-v2 connection saved, both global agent settings requests returned 200, returned no connection or authentication details, and projected the fixture with zero models. Both model pickers offered the saved Luna and Terra Responses choices without offering the fixture or the embedding-only model. Personal and named-group option builders were tested locally, not live. |
| Dropdown | Visually checked the opened Method menu in the shared browser. All three options were readable in dark and light modes, with opaque theme backgrounds. Selecting Service principal revealed its fields in a draft; no change was saved. |
| Cleanup | Deleted the approved disabled fixture and verified it was absent after reload. Cancelled both agent drafts, restored the original dark theme, and returned the shared tab to its starting page. No inference ran; no saved defaults, permanent connections, APIM, roles, release notes, or GitHub changes. |

---

### B1. Add the V2 Notification Workbench

Priority: **P1**  
Status: **Not started**  
Dependencies: Existing notification APIs

#### Current Gap

V1 has native notification search and read/unread filtering. V2 has the compact
notification panel and delegates some work to a classic destination.

#### Required Changes

- [ ] Add a routed V2 notification page.
- [ ] Support search, status filters, paging, empty/no-match distinction,
  unread counts, mark-read, and links to exact records.
- [ ] Keep the compact bell/panel as the quick-access surface.
- [ ] Preserve keyboard focus and screen-reader announcements across updates.
- [ ] Reuse the existing backend notification contract.

#### Acceptance Criteria

- [ ] A user can find an old notification without leaving V2.
- [ ] Deep links open the authorized approval, review, workflow, or conversation.
- [ ] Filter/search state survives normal navigation.
- [ ] Fetch failure is distinguishable from zero results.

---

### B2. Add Safe V2 Workspace Deletion

Priority: **P1**  
Status: **Blocked by deletion-policy decision**  
Dependencies: Backend dependency and cascade/archive policy

#### Required Decisions

- [ ] Decide archive versus hard delete for personal workspaces.
- [ ] Decide cascade, block, detach, or retain behavior for group/public
  resources.
- [ ] Define treatment of documents, workflows, agents, actions, conversations,
  shares, approvals, generated artifacts, and audit evidence.
- [ ] Define idempotency and rollback behavior.

#### Required Changes

- [ ] Implement authoritative server-side prerequisite checks.
- [ ] Add a dependency preview.
- [ ] Add V2 confirmation with explicit scope and irreversible consequences.
- [ ] Use the same backend behavior for personal, group, and public workspaces
  except where a documented policy differs.
- [ ] Do not rely on UI document counts as a security check.

#### Acceptance Criteria

- [ ] Unauthorized users cannot delete or enumerate hidden dependencies.
- [ ] No orphaned sensitive resource survives a completed deletion.
- [ ] Repeated deletion is safe and idempotent.
- [ ] A deletion failure reports what remains and what did not change.

---

### B3. Replace V2 Legacy-Document Handoffs

Priority: **P1**  
Status: **Not started**  
Dependencies: Legacy-document retirement decision

#### Current Gap

Some V2 group/public document paths still send users to classic tooling for
legacy document upgrade or migration.

#### Required Changes

- [ ] Add a V2 migration/readiness view for eligible legacy documents.
- [ ] Keep authorization, interrupted upgrade, partial success, and duplicate-
  indexing states visible.
- [ ] Provide a bounded retirement or redirect plan for the classic tool if all
  supported legacy operations move to V2.
- [ ] If the legacy path is retained, document the supported handoff rather than
  leaving an unexplained interface switch.

#### Acceptance Criteria

- [ ] A user can complete supported migration entirely in V2.
- [ ] Partial/interrupted operations can be inspected and resumed safely.
- [ ] Re-running an upgrade does not duplicate indexed content.

---

### B4. Define V2 Retry Model/Agent Semantics

Priority: **P1**  
Status: **Not started**  
Dependencies: A2 cancellation finalizer

#### Current Gap

V1 offers more explicit retry route selection. V2 preserves attempt history, but
the product contract for changing the endpoint/model/agent/reasoning policy on
retry is not yet explicit.

#### Required Behavior

- [ ] Default Retry preserves the original authorized endpoint, model, agent,
  protocol, scope, and reasoning policy.
- [ ] Add an explicit **Retry with model/agent** path when the user intentionally
  changes route.
- [ ] Do not silently inherit the currently selected composer model when retry
  is expected to preserve the original turn.
- [ ] Show route differences before resend when cost or protocol changes.
- [ ] Keep the attempt chain and original message visible.

#### Acceptance Criteria

- [ ] Retry and edit/resend preserve route by default.
- [ ] Agent mode never sends a conflicting direct model identity unless the user
  explicitly chose an override supported by the backend contract.
- [ ] V1 and V2 preserve the same server-side resulting state.

---

### B5. Add V1 Links to Canonical V2 Editors

Priority: **P2**  
Status: **Not started**  
Dependencies: Stable V2 route contracts

#### Required Changes

- [ ] Add V1 links for:
  - workflow editor
  - agent editor
  - action editor
  - approvals and review-center records
  - workspace settings and destructive operations
  - chart/diagram revision editors
- [ ] Preserve context in deep links using stable resource IDs.
- [ ] Make links available to only the users authorized for the destination.
- [ ] Do not duplicate the V2 editor implementation in V1.

#### Acceptance Criteria

- [ ] A V1 user can continue a task in V2 without recreating it.
- [ ] Deep links remain safe after membership, role, or policy changes.
- [ ] Unsupported or removed V1 controls show a supported destination or
  explicit unavailable state.

---

### B6. Port V2 Accessibility and Mobile Interaction Contracts to V1

Priority: **P1**  
Status: **Not started**  
Dependencies: None

#### Required Changes

- [ ] Audit icon-only controls for accessible names.
- [ ] Standardize keyboard focus for dropdowns, dialogs, drawers, and toasts.
- [ ] Add live-region announcements for save, loading, failure, stream start,
  Stop, completion, and source coverage.
- [ ] Preserve 44-pixel touch targets where V1 mobile controls are interactive.
- [ ] Preserve zoom and avoid viewport-locking behavior.
- [ ] Keep mobile drawers and model/agent selectors dismissible by keyboard.
- [ ] Align loading indicators with repository loading-feedback requirements.

#### Acceptance Criteria

- [ ] The V1 chat and endpoint editor complete their major tasks by keyboard.
- [ ] Focus returns predictably after modal and drawer dismissal.
- [ ] Loading, failure, and completed states are announced.
- [ ] V1 and V2 use equivalent authorization and state semantics even where
  presentation differs.

---

### B7. Keep V2 Visual Editors Canonical

Priority: **P2**  
Status: **Not started**  
Dependencies: Stable chart/diagram revision APIs

V2 provides richer chart and diagram revision authoring; V1 can display the
saved revisions. Do not duplicate canvas editors in V1.

- [ ] Add a contextual V1 **Edit in V2** path where appropriate.
- [ ] Keep one revision schema, authorization model, export pipeline, and
  accessible fallback for both UIs.
- [ ] Test that V1-rendered revisions match V2 export and copy behavior.

---

## V2 Verification Backlog

Do not implement the following solely from the partial UI inventory. Verify
routes, tests, role enforcement, and product intent first:

- [ ] Personal safety-violation history and remediation surface
- [ ] Workflow activity surface
- [ ] Semantic Search health warning
- [ ] Health, Key Vault, Front Door, and governance information panels
- [ ] Group/public management action-by-action parity
- [ ] M365 approval and profile workflows

Record confirmed gaps as new B-series work items with acceptance criteria
before implementation.

## Shared Backend Contracts

The following contracts should be reused by V1 and V2:

### Model Catalog Contract

- Endpoint and model IDs are stable.
- Eligibility is evaluated server-side by capability.
- Default and stale selections are validated with the same rule as requests.
- Picker payloads do not expose secrets.
- Revocation takes effect on retry, edit/resend, agent, workflow, and
  orchestration execution.

### Cancellation Contract

- Navigation detach and explicit Stop are different operations.
- Stop snapshots and preserves partial content.
- Cancellation is scoped to the conversation and originating turn.
- Late events cannot cross conversations.
- Persisted status is explicit and reload-safe.

### Workflow Failure Contract

- Every failure is terminal, recoverable, or retryable by a typed rule.
- Provider errors have a stable public code and correlation reference.
- Effect certainty controls replay.
- Recovery never becomes a substitute for missing diagnostics.
- Arbitrary exception/provider text is never exposed.

### Tabular Tool Contract

- File format is resolved before tool argument validation.
- Tool schemas advertise only selectors valid for that format.
- CSV is never asked for worksheet selectors.
- Excel retains explicit sheet/table/range/header semantics.
- A repeated-equivalent error and request-wide invocation budget terminate the
  request safely.

### UI/API Authorization Contract

- V1 and V2 perform the same server-authoritative checks.
- Client visibility cannot grant access.
- Masking is not itself authorization.
- Object-level authorization applies to retry, share, delete, download,
  export, recovery, and workflow result access.
- Credentials and private reasoning remain server-side.

## Implementation and PR Sequence

Keep the implementation reviewable. Suggested sequence:

1. **PR 1 — Merge invariant guardrails**
   - dependency pin and regression
   - chat model eligibility
   - no UI redesign

2. **PR 2 — V2 cancellation persistence**
   - one finalizer
   - normal/Responses/collaborative coverage

3. **PR 3 — Workflow capacity and failure contracts**
   - verified token-limit metadata
   - typed provider errors
   - route identity and replay protections

4. **PR 4 — Tabular format-aware execution**
   - CSV selector normalization
   - request-wide retry containment
   - `TOTAL=35` staging proof

5. **PR 5 — Responses action regressions**
   - local action fixture and authorization tests
   - optional approved staging smoke test

6. **PR 6 — V2 parity foundations**
   - notification workbench
   - shared retry semantics

7. **PR 7 — Workspace deletion and legacy migration**
   - only after backend policy decisions

8. **PR 8 — V1 deep links and accessibility**
   - no duplicate React editors

Each PR must:

- [ ] update `application/single_app/config.py` for a code change
- [ ] include focused regression tests
- [ ] include release notes only if approved for that change
- [ ] update this plan's status and progress log
- [ ] reference the associated issue
- [ ] state the exact ACR/staging evidence when applicable

## Validation Matrix

### Focused Python

Run from the repository root:

```powershell
python -m pytest functional_tests\test_workflow_context_budget.py
python -m pytest functional_tests\test_workflow_policy_failures.py
python -m pytest functional_tests\test_v2_tabular_parity.py
python -m pytest functional_tests\test_responses_model_tool_execution.py
python -m pytest functional_tests\test_custom_model_endpoint_foundation.py
python -m pytest functional_tests\test_model_endpoint_protocol_inference.py
```

Add and run focused picker/cancellation tests in the files nearest their
affected behavior.

### V2 Frontend

Run from `application\v2_ui`:

```powershell
npm run typecheck
npm run build
```

Add browser coverage in `ui_tests` for each visible V1/V2 behavior change.

### Full Repository

```powershell
python -m pytest
```

### Staging

For every blocking staging run, record:

- ACR run ID
- image repository/tag and digest
- App Service resource and slot
- application version
- browser and role
- exact scenario
- expected and observed result
- screenshot/trace or safe server correlation reference
- previous digest for rollback

## Staging Retest: 0.261.429

Retested on **2026-11-16 UTC** through the shared browser's actual V1/V2
pickers, message controls, upload dialog, workflow editor and run history.
Full page reloads were used to distinguish persisted behavior from local
provisional state. No application code, credentials, commits, pushes or
deployment changes were made during this validation.

### Deployment Identity

- Host: `https://simplechat-2026stage-app.azurewebsites.net`
- App Service: `simplechat-2026stage-app`, production slot in the staging
  resource group `simplechat-2026stage-rg`.
- Visible V1 and V2 application version: **0.261.429**.
- Read-only App Service configuration:
  `simplechat2026stageacr.azurecr.io/simplechat@sha256:7295681b21a4652f3dcaa3ec7d675cf37e7d736292f031635db6a150c7d28bce`.
- Verification command, **passed**:
  `az webapp config show --resource-group simplechat-2026stage-rg --name simplechat-2026stage-app --subscription 65eeb30f-e539-47a6-a160-f6629cae3d4b --query linuxFxVersion --output tsv`.
- The ACR run ID, previous rollback image and health/readiness endpoints were
  not verified in this browser pass. The configured image and visible version
  are evidence of the tested deployment, not proof of those separate gates.

### Results

The session ledger contains **20 check entries: 12 passed, 7 failed and
1 blocked**. Some entries are aggregate or cross-UI checks; the seven failures
are not seven independent root causes.

| Area | Result | Observed evidence |
|---|---|---|
| V1/V2 chat menus | Pass | Both show the same four configured chat models and omit the embedding model. The saved embedding model remains enabled and available for embeddings, not chat. |
| Direct chat | Pass | V1 and V2 returned their exact unique direct-chat tokens using `gpt-5.6-terra`. |
| APIM agents | Pass | Claude, Luna and Terra each returned their unique token in both UIs with the corresponding agent identity. |
| CSV computation | Pass | The uploaded three-row CSV produced total 35, North 15, South 20 and row count 3. The first request used three actual tools with no selector retry loop and completed in 12.6 seconds. A follow-up returned `TOTAL=35`, which survived reload. No expected totals were supplied in the prompts. |
| Responses baseline | Pass | An isolated managed-identity connection saved `use_responses_api=true`. Its visible V2 selection sent that connection/model identity and returned the exact token; V1 also returned its exact token. Original connections were not changed. |
| Post-token Stop | Partial / fail | Ordinary and Responses streams retain partial text, including after reload and a subsequent turn. Their stopped/incomplete labels disappear during reconciliation/reload. V1 also loses its stopped label after reload. |
| Pre-token Stop | Fail | The local blank bubble was removed, but cancellation returned 404. The provider continued and persisted all 150 requested items, 14,809 characters. V2 temporarily moved the original direct-chat reply beneath the stopped turn after reload. |
| Claude workflow | Fail | Legacy core capabilities produced `model_endpoint_configuration_invalid`. With chat capabilities Off, the exact task token was generated, but the run ended `incomplete` with `completeness_verification_unavailable`. This is not a universally broken Claude inference route. |
| Isolated failure workflow | Fail | A managed-identity connection with a nonexistent deployment, chat capabilities Off and retry count 2 entered `waiting_recovery` at attempt 1 without a specific failure diagnostic. The workflow's actual provider HTTP status was not observable; do not label it a proven provider-404 classification defect yet. |
| Workflow diagnostic UI | Fail | A safe error code/message exists in the Claude task API item but is absent from the V2 failed-task display. Loading its result excerpt returns 409 and calls this new failed task an older run without a durable result. |
| Live Responses actions | Blocked | No approved action-bearing live Responses agent fixture was created. Local duplicate/malformed/unregistered-action tests are not live verification. |
| Cleanup | Pass | Original settings and three connections restored/verified; temporary objects removed; original direct-model preference restored after reload. |

The first CSV request was explicitly pinned to the synthetic source. Its
unpinned follow-up also inspected the pre-existing `merge-tabular-test.csv`;
the initial three-tool computation is the evidence for the synthetic source.
That pre-existing document was not deleted or changed.

### Follow-Ups Before Promotion

- [ ] **A2-R1:** Persist stopped/incomplete metadata through server storage,
  reconciliation and reload in both UIs and Responses.
- [ ] **A2-R2:** Handle cancellation before server admission without losing the
  cancellation request, continuing generation silently, or reusing an older
  reply's identity/presentation.
- [ ] **A4-R1:** Resolve Claude's legacy capability and completeness-verifier
  compatibility while preserving its working direct/agent inference route.
- [ ] **A4-R2:** Diagnose the isolated missing-deployment workflow at the
  adapter boundary and retain a specific safe failure reason in recovery.
- [ ] **A4-R3:** Display stored safe task diagnostics for failed tasks without
  requiring a successful durable result.
- [ ] Retest these scenarios after implementation; do not promote on the
  successful picker, CSV and direct-chat checks alone.

### Safe Evidence Identifiers

The disposable objects were deleted after testing. These identifiers locate
the corresponding safe test evidence in this record and retained service
telemetry; they are not links to surviving test objects.

| Scenario | Identifier |
|---|---|
| V1 smoke and post-token Stop | Conversation `aae55140-dac1-46d5-b350-b2c430879748` |
| V2 smoke, Stop and early-cancellation race | Conversation `68dfcd20-53cb-47bc-aa3f-31133da157e1` |
| CSV calculation | Conversation `bf74851d-3192-401f-97ba-ed24f5624e96` |
| Responses smoke and Stop | Conversation `475b0f89-91dd-47ab-9cc5-1cb5ab827740` |
| Claude legacy-capability failure | Run `7b510a38-d440-5683-9c4f-0df4810da4d1`; task `ff475d72-8398-5978-b3ca-297f9030b967` |
| Claude no-tools/completeness failure | Run `c211324e-fb40-55c8-930c-e59669db7978`; task `32841ffc-c733-5701-a840-ee483e670126` |
| Isolated recovery/cancellation | Run `fd047d4a-99a8-54b7-af56-f5fdb1378545` |
| Older reply temporarily shown under the early-stopped turn | Message `68dfcd20-53cb-47bc-aa3f-31133da157e1_assistant_1794851216_8623`, originally timestamped 17:46:58 UTC |

### Cleanup and Remaining Validation

- [x] Restore personal/group workflow, personal agent and custom-endpoint
  settings to their captured baseline values.
- [x] Remove both disposable workflows, the isolated connection, all seven
  generated test conversations and the synthetic CSV.
- [x] Verify no test conversation IDs remain in the feed and the synthetic
  CSV remains absent after reload.
- [x] Preserve the three original connections, SharedAPIM schema-v2
  paths/protocols and embedding publication.
- [x] Restore direct `gpt-5.6-terra`, an empty message draft and expanded
  navigation.
- [ ] Verify GPT-6 workflow capacities under A3; no limits were guessed or
  changed.
- [ ] Complete live Responses action testing if a safe fixture is approved.
- [ ] Complete hard error-budget, additional file-format, collaborative and
  cancellation-race coverage not established by this pass.
- [ ] Obtain a clean full-suite result. The earlier broad pytest runs stopped
  on collection/setup errors outside the changed test files; no clean
  baseline comparison establishes that every broader failure is unrelated.

**Disposition: not ready for staging sign-off or promotion.**

## Approved Corrective Tranche: 0.261.430

Implemented in version: **0.261.430** (locally tested; remaining gates below).
The patch increment belongs to `application/single_app/config.py`; it does not
supersede the deployment identity or live evidence in the .429 retest above.

The coordinator completed the independent read-only analyses and bounded
follow-ups. Approval is `decision=implement`,
`verification_policy=capability_aware_json`, `attempt_control=cosmos_cas`.
One implementation owner is responsible for code, tests, contract inventory
and these living documents. No further delegation, source refresh, Git state
changes, deployment, live settings changes, new resources or action fixtures
are authorized. Release notes and GitHub issue updates remain deferred.

### Reconciled Implementation and Acceptance

| Follow-up | Approved implementation | Required local acceptance evidence |
|---|---|---|
| A2-R1 | Persist a backward-compatible interruption projection and render legacy canceled/incomplete records in V1/V2, including Responses. Distinguish user cancellation from provider/transport interruption. | Real persisted API payload followed by browser reload and a later turn retains partial text, exact identity and truthful status; zero-content interruptions create no blank assistant. |
| A2-R2 | Extend the existing `submission_id` and durable thread/attempt binding to ordinary sends. Authorize the actor and server-resolved destination before intent access. Cosmos ETag transitions, not process/Redis state, decide the terminal outcome. Use atomic publication only within an actual container/partition boundary; otherwise require fenced, recoverable, idempotent materialization. | Timing barriers before admission/dispatch, during provider work, before/after commit, replacement/late cancellation, stale worker/cache and storage failure. Accepted cancellation prevents later success; committed completion wins over late cancellation. Unconfirmed requests retain partial output without claiming confirmed Stop. Retry/edit and collaborator authority remain intact; navigation only detaches. |
| A4-R1 | Repair the actual requested capability/adapter contract without changing endpoint/model/protocol/APIM paths or removing required tools. Choose native structured output when supported, otherwise schema-validated prompted JSON on the same route. Reuse candidate-only completeness correction/checkpointing. | Real-module invocation tests name unsupported required capabilities and stage. Strict closed-schema parsing, malformed/unavailable verification and bounded corrections never falsely complete or replay a producer/tool. Preserve direct Claude and all three APIM agents. |
| A4-R2 | Normalize genuine provider/SDK errors at narrow invocation boundaries through shared safe helpers. Keep observed numeric status, type, protocol, stage and safe correlation only. Determine whole-operation effects from prior execution, independently of request rejection. | Real invocation boundaries cover 400/401/403/404/429/503 and transport uncertainty. Definitive pre-effect failures terminate; safe transients retry boundedly; after-tool/unknown effects remain recoverable without effectful replay. No raw provider body, URL, credentials or private continuation reaches the client. |
| A4-R3 | Carry an allowlisted failure summary through run items, runtime gates, legacy task history and structured execution/attempt history. Use exact execution selectors and truthful artifact-unavailability reasons. | Both history shapes show safe diagnostics without a result artifact. Missing results do not trigger excerpt fetches or misleading legacy messages. XSS payloads remain text; authorization/source rechecks and failure HTTP semantics remain enforced. |

Preservation gates include embedding-only chat exclusion (embeddings stay
enabled), SharedAPIM schema-v2 `shared-foundry;rev=2` and
`shared-foundry;rev=2/anthropic` routing, meaningful CSV tools producing total
35/North 15/South 20/three rows, Responses baseline/private continuation and
duplicate/malformed-action guards. GPT-6 limits are not guessed. The optional
live Responses action fixture remains blocked and unauthorized.

### Execution Ledger

- [x] Read the actual repository rules and existing .429 working-tree changes;
  preserve both untracked living documents and all prior implementation.
- [x] Record this reconciled corrective tranche before production edits.
- [x] Add failing-first real-module/route/storage/browser regressions where
  practical, then implement the five follow-ups locally.
- [x] Execute focused Python suites under the Cosmos network guard, relevant
  V1 `node --check`, V2 typecheck/build and Python Playwright tests. See the fix
  record for exact commands, green groups and the retained failing baseline guard.
- [x] Refresh and manually review changed Cosmos boundary classifications and
  real owner-runtime/SDK-default evidence; execute the exact affected subset and
  attempt `--run-contracts`, retaining its unrelated global review failure.
- [x] Run applicable route-policy, access-control, XSS, local-assets and docs
  guards; record exact commands/results and retained failures in the fix document.
- [x] Handoff changed files, proven causes, red/green evidence and limitations
  for independent coordinator validation.

### Corrective Implementation Notes

The existing `conversation_handoffs` container is reused for submission control;
no resources or settings were added. Its `/destination_conversation_id`
partition holds an actor/submission record. Collaborative control uses the
authorized public destination before the hidden source exists, then binds that
same record to server-created source message/thread IDs. Cache keys include
the submission; cache discovery remains advisory. Messages live in a different
container, so a conditional terminal decision retains an outbox until
idempotent materialization succeeds. Completed decisions cannot become canceled
successes, and canceled decisions cannot publish later success frames.

The verifier selects supported JSON representation before local capability
validation. It retains the existing closed-schema parsing, candidate-only
correction, repair budgets and checkpoints. Required tools remain required;
unsupported capabilities are named rather than silently disabled. The actual
missing capability in the .429 Claude deployment remains unobserved.

Native SDK and legacy Anthropic errors are normalized at their invocation
boundaries. Request rejection is separate from enclosing operation effects:
tool-result history and uncertainty persisted before nested non-replay-safe
units prevent a later model rejection from authorizing automatic replay.
Both history shapes and runtime gates use typed public diagnostics. Missing
artifacts have explicit unavailability reasons instead of successful empty
responses or misleading older-run messaging.

The inventory refresh also exposed pre-existing merge-baseline review gaps in
untouched modules. Python 3.13's omission of empty AST fields was separately
reproduced and corrected without reapproving unchanged source. Exact unchanged
reviews were retained; inherited stale reviews are not blanket-approved.
The final fix record must distinguish focused runtime evidence from the
repository-wide inventory/contract gate.

### Initial Local Corrective Validation Disposition (Before Independent Review)

- Stop/retry/SDK/checker/CSP: **61 passed**.
- Protocol: **64 passed**; completeness: **47 passed**; result routes:
  **32 passed**; Claude/Responses/routing/CSV preservation: **55 passed**.
- Workflow execution/journal/history/access: **135 passed, one failed**.
  The remaining access wiring assertion expects 14 personal gates; both HEAD
  and the current source contain 33. No routes were added.
- Final browser suites: **27 passed**, including a reproduced lost-user-ack
  placement race, fresh persisted API reload/later turn, uncertain Stop,
  provider interruptions and both text-only diagnostic history shapes.
- V2 typecheck/build, both changed V1 syntax checks, and all three route-policy
  scripts passed. Final docs/local-assets selection: **21 passed**. Official
  added-line XSS/access inspectors: **35/22 files, zero findings**.
  No source was committed, staged, pushed or deployed.
- The initial Cosmos refresh and limited explicit owner reviews left
  the required contract gate **blocked** by 595 review gaps:
  266 review-required owners and four doubles, including 81 still-pending
  owners in the five edited modules. These were not all inherited gaps.
- The coordinator must disposition the wider review/access-test baseline and
  compare the identical post-change root pytest command with its existing
  80-collection-error baseline. Staging sign-off remains blocked pending
  separately authorized deployment and fresh retest.

The full-suite pre-change baseline is **not green**: the coordinator's guarded
root pytest command exited 2 with **80 collection errors, 17 warnings, no
executed tests (54.69 seconds)**. The coordinator retains the baseline XML and
will compare the identical post-change command. Focused success cannot replace
that gate or establish staging success. No live retest is authorized here.

### Independent Review Follow-up: .430 Lifecycle and Affected Owners

The coordinator independently reproduced the pre-follow-up focused results:
61 Stop/retry/checker, 47 completeness, 64 protocol, 32 result-route,
55 preservation and 27 browser cases passed; frontend checks passed. Workflow
validation retained 135 passes and the unchanged 14-versus-33 count assertion.
The identical root command collected the same 80 failing modules with no added,
removed or changed normalized error signatures. Neither root run was green.

The coordinator explicitly unfroze this same approved .430 scope after review.
The single implementation owner will reproduce and correct these concrete
lifecycle defects before claiming the storage control complete:

1. Recover an exactly matching admitted-but-undispatched submission after initial
   question publication fails, retaining request-conflict checks and one-time
   dispatch CAS.
2. Recover collaborative outboxes through the verified canonical public
   destination and recorded source binding. Shared history must recheck current
   membership/source relationships; publication grants no execution or cancellation
   authority over another actor's operation.
3. Stop revisiting settled outboxes after intentional question/partial deletion.
   Never resurrect deleted messages or hide unexpected storage failures.
4. Publish late partials with visibility derived from the authoritative current
   attempt selection, including selection/publication races rather than a stale
   admission snapshot or another check-then-write.
5. Make duplicate publication create-only. A conflict verifies immutable identity,
   never replaces an existing legitimate message using a freshly read ETag.

Acceptance requires failing-first real production-owner/installed-SDK tests for
all five defects, including question-write failure, shared crash recovery,
settled soft/hard deletion, retry selection races and concurrent materializers
with intervening edits/deletion. Existing cancellation, authorization, safety,
retry/edit, persisted reload and later-turn behavior must remain covered.

The remaining 81 owners in the five .430-edited files require actual
consumer/dependency review and valid representative installed-SDK owner-runtime
evidence. Their 162 missing-classification/evidence messages are not inherited
scope. Review all affected entries individually; do not approve function hashes
or expand the closed source-only baseline. Execute the exact affected-owner SDK
selection separately and report it distinctly from the global gate. Leave the
185 untouched owners, four unrelated doubles and stale access-count test alone.
Investigate the 25,568 Stop/checker and 5,258 browser warnings only for a narrow
touched AST-constructor cause, with a warnings/digest regression if confirmed.

- [x] Capture five lifecycle regressions before production fixes.
- [x] Complete lifecycle corrections and focused green evidence.
- [x] Complete affected-owner consumer contracts and SDK evidence.
- [x] Check the narrow AST warning cause without unrelated cleanup.
- [x] Record exact scoped/global gate results and remaining affected gaps.

The follow-up also reproduced two related end-to-end manifestations before
fixing them: shared HTTP admission retried with a different public-question ID,
and deletion-based attempt promotion missed a concurrently published partial.
Both now reuse the existing submission/question identity and the same atomic
question/publication selection fence.

Affected review closeout is consumer-specific: the original 81 pending owners,
five previously classified scopes and three new shared scopes total **89**
reviewed owners in the five edited modules; `functions_chat_retry.py` has
**17** reviewed boundaries. Including the 12 prior journal/runtime-store owners
and four SDK-default doubles, the exact selector union is **71 selectors**:
**229 tests passed**, exit 0. No source-only baseline was expanded or
utility-only reference represented as real owner execution.

The global gate separately reports **1,114 owners / 429 doubles / 433 review
messages**, exit 1, and its guarded contract child did not run. All remaining
review-required entries are the **185 untouched owners/four unrelated doubles**;
their semantic inventory snapshot hash is unchanged. **Zero .430-affected
owners/doubles remain review-required.** The stale access-count test is also
unchanged. Neither these unrelated blockers nor the root collection gate was
waived.

The supplied root command was repeated after the follow-up. Baseline/current
both contain **80 collector modules**, with zero added/removed modules and zero
changed normalized full-error signatures, agreeing with the coordinator's
independent pre-follow-up comparison. This is retained failure evidence, not a
green full suite.

The original 61-case warning run reproduced 25,568 warnings, 25,519 at unchanged
Swagger legacy AST-class references. The touched digest emitted zero warnings
and now has an explicit no-constructor-deprecation regression while preserving
empty-field fingerprint semantics. No broad warning cleanup was performed.
Exact commands, reports and final focused/frontend/browser checks are retained
in the existing fix ledger.

Final complete follow-up selections passed **119** lifecycle/retry/deletion/
checker cases, **229** exact affected-owner SDK cases, **12** SDK API/pin/
atomic-double cases, **27** browser cases after build completion, and **21**
docs/local-assets cases. Protocol/completeness/result/preservation repeats passed
**64/47/32/55**. Workflow validation still reports **135 passed / one unchanged
access-count failure**. V2 typecheck/build, V1 syntax, route-policy and actual
added-line XSS/access checks passed. The initial browser run overlapped the SPA
build and was not accepted; the complete post-build rerun is the final evidence.
No deployment or fresh staging verification was claimed by that local phase.

That follow-up did not authorize a version increment beyond .430, release-note
update, Git write, deployment, resource creation or live configuration change.
The subsequent explicit live-configuration approvals are recorded separately
below.

## Staging Retest: 0.261.430

This section records **actual staging behavior**, not the local pytest/browser
results above. Testing used the signed-in shared browser's visible controls,
real provider requests, full reloads, later turns, uploads, workflow authoring,
and both legacy and structured run histories. Read-only API and Azure telemetry
inspection supplied scoped evidence; hidden selectors or application stores
were not assigned to simulate success.

### Deployment and Acceptance Boundary

- Visible V1/V2 version: **0.261.430**.
- Host: `https://simplechat-2026stage-app.azurewebsites.net`.
- Configured App Service image:
  `simplechat2026stageacr.azurecr.io/simplechat@sha256:9674b77ca3945513fc91ccede6ed01053c890bc716239c9be6a391821e48fd69`.
- App Service reported **Running**. Its configured health route,
  `/external/healthcheck`, returned **HTTP 200**.
- Browser baseline timestamp: `2026-11-17T21:32:45.460Z`.
- The admin deployed this image. The assistant did not deploy, restart, change
  APIM policies, commit, stage or push.
- The ACR run ID and rollback target were not verified in this pass.

The live ledger has **25 check entries: 19 passed, 3 failed and 3 blocked**.
Entries include aggregate and configuration checks, not 25 independent root
causes. The 80 unchanged local collection errors, stale 14-versus-33 access
assertion and 433 untouched Cosmos review messages are **separate local
validation blockers**, not failing staging scenarios. Local passes do not
establish deployed acceptance.

### Live Results

| Area | Result | Actual observation |
|---|---|---|
| Menus and original routes | Pass | Both menus show the four original chat models without embeddings. Direct chat and Claude/Luna/Terra agents returned unique tokens in both UIs with their expected identities. Embedding capability remains enabled separately. |
| V1 ordinary Stop | Pass | Visible output grew from 189 to 237 characters. Cancellation returned 200/accepted for the exact submission. Partial text and its stopped label survived reload and a later successful turn, without duplication. |
| V2 ordinary Stop | Pass | Visible output grew from 222 to 276 characters. Cancellation returned 200/accepted. Partial text and label survived reload and a later successful turn, unchanged and present once. |
| V2 early Stop | Pass, with wording limitation | While the bubble said Thinking, cancellation returned 200/accepted with `dispatch_prevented=true` and matching submission identity. No blank assistant or delayed answer appeared after reload, three agent turns and another reload; the earlier answer stayed in its original position. The immediate stopped wording becomes a generic interrupted/retry notice after reload. |
| Retry/edit/deletion | Partial / fail | Immediate Retry on a newly completed Terra agent reply says the original question is unavailable and requires reload. After reload, Retry preserves Terra and creates attempt 2; edit/resend produces the edited token on Terra at attempt 3. Deleting the stopped partial remains effective after reload, without history failure or resurrection. |
| Active navigation detach | Pass | Navigated through My Workspace while partial text and Stop were visible. On return, one completed answer contained all 40 numbered paragraphs and the final marker, with no stopped label. |
| Fresh CSV | Pass | New values 11, 17 and 7 produced `TOTAL=35`, North 18, South 17 and 3 rows. Three actual successful tools ran in 148/199/197 ms; completion took 12.7 seconds without a selector loop. Expected totals were not supplied in the prompt. |
| Claude completeness, capabilities Off | Pass | Exact output was loaded from the durable artifact. Mandatory answer checking remained enabled, with format/review complete and zero adjustments. The selected SharedAPIM Claude identity and Messages protocol were retained. |
| Claude Legacy core | Fail | The actual failure now identifies required capability `toolCalling`, request phase and capability-validation stage. No capability flag was flipped and no required tool was silently removed. The successful no-tools run does not satisfy this core-mode acceptance gate. |
| Definitive provider rejection | Pass | A deliberately missing deployment produced observed upstream 404/NotFoundError, terminal failure, effect certainty none and a safe correlation reference. The configured retry count was 2, but the task had one attempt and did not enter recovery. |
| Legacy failure history | Pass | Safe code/message/stage/capability or provider status is visible immediately and after reload. Resultless failed tasks do not offer an excerpt fetch or claim to be older runs. |
| Structured failure history | Pass | A separate definition-v3 run shows the same safe 404 facts in the execution summary and explicit attempt-1 expansion. No result fetch is offered; the UI truthfully states that no result was committed. |
| Responses on known staging Azure | Pass | Actual V1/V2 inference passed. V2 Responses output grew from 203 to 260 characters; Stop returned 200/accepted. One partial and its label survived reload and a successful follow-up, and were still labeled in a fresh V1 route load. |
| Saved Responses editor test | Fail | Reopening the saved APIM Responses connection and testing either model without intentionally changing it returns application 409, asking to save changes first. The saved model's actual route works; this is an editor round-trip defect. |
| Permanent shared Luna/Terra Responses | Resolved by follow-up | The original pass was blocked by the missing compatible operation. The approved follow-up added `POST /openai/v1/responses` only to existing revision 2. Luna/Terra diagnostics and V1/V2 chat then passed. The disabled direct fallback is out of scope. |
| Live Responses actions | Blocked | No approved action-bearing live fixture was supplied. Local action tests are not live exactly-once verification. |
| Cross-user collaboration | Blocked | No second authenticated participant was supplied. Local authorization and multi-worker tests are not live two-user acceptance. |
| Cleanup | Pass | Eleven disposable conversations, two workflows, one temporary connection and the uploaded/local synthetic CSV were removed and checked. Original flags, original connections and the default user model were preserved. Explicit permanent changes are listed separately below. |

The CSV source was explicitly selected. Its data were:

```csv
Region,Device,Amount
North,Phone,11
South,Phone,17
North,Tablet,7
```

### Permanent Responses Configuration and Explicit Approval

The admin requested permanent Responses configuration, preferred SharedAPIM
and allowed direct Foundry as fallback, but explicitly excluded retaining the
deliberate failure fixture.

Adding duplicate request-model identifiers for different APIs inside one
connection was rejected by current application validation. That is a current
configuration limitation; it was not bypassed or assumed to be a new .430
defect. The unsaved draft was cancelled. A separate connection was then
explicitly selected, and the admin entered its key through the protected UI.
The assistant did not read or print that credential.

| Retained connection | ID | State at the original retest |
|---|---|---|
| SharedAPIM Responses | `0b47a96f-e0c8-46a3-9c2b-663169af221b` | Disabled; Luna and Terra retain explicit v1 Responses routing under `shared-foundry;rev=2`. |
| Shared Foundry Responses (Direct) | `2c9b2519-9667-4119-8a5a-0d39cb4b01b6` | Disabled; native managed identity, shared resource-root URL and Use Responses API enabled. |

Read-only Azure discovery verified that exact APIM revision
`shared-foundry;rev=2` has:

```text
POST /openai/responses?api-version={api-version}
```

At that retest, it did **not** expose `/openai/v1/responses`. The application requires
an OpenAI-compatible v1 Responses inference route. Existing APIM Chat
Completions and Anthropic operations were not modified. Model support in
[Microsoft's Responses documentation](https://learn.microsoft.com/azure/foundry/openai/how-to/responses)
does not establish gateway-operation availability.

The shared Foundry account and both existing deployments were verified:
`gpt-6-luna` version `2026-09-22` and `gpt-6.1-terra` version `2026-10-26`.
Direct connection tests acquired a managed-identity token but received
upstream 401 at the actual `/openai/v1/responses` operation. The same
application's known staging-resource Responses control passed, so this is not
evidence that Responses universally fails on .430.

After an explicit structured approval, **Cognitive Services OpenAI User**
(`5e0bd9bd-7b93-4f28-af87-19fc36ad61bd`) was assigned to staging system identity
`d287a674-975e-4d7b-873a-7bcf3c416aec`, at only:

```text
/subscriptions/7a62dc7b-d781-4236-91a6-2abf50e62fbe/resourceGroups/simplechat2026-shared-rg/providers/Microsoft.CognitiveServices/accounts/simplechat-shared
```

Assignment `d313c325-68bf-4ef1-b6ac-862b032dc612` was verified. No administrative
or broader role was granted. The grant remains as approved; it was not silently
revoked during cleanup. Post-grant inference still failed, so neither the
grant nor connection creation is described as functional success.

Both new connections were left disabled at the end of that retest to keep broken
choices out of normal chat menus. The subsequently approved APIM change and
connection enablement are recorded below. The three original connections,
original model IDs, APIM paths, protocols, authentication choices and embedding
publication remain unchanged.

### Approved In-Place APIM Responses Operation: 2026-11-17

This is a configuration-only follow-up on **0.261.430**, not a new application
version. The admin explicitly authorized adding one operation to the existing
`shared-foundry;rev=2` API, **without creating any revision or version**.
The admin separately approved enabling the existing `SharedAPIM Responses`
connection for Luna/Terra testing and retaining it enabled if both passed.

- [x] Created operation `OpenAI_v1_Responses`, `POST /openai/v1/responses`.
  ARM returned HTTP 201. Its contract describes native Responses JSON requests,
  JSON response objects and `text/event-stream`; no Chat Completions conversion
  or body-transform policy was added.
- [x] Inherited the existing `beta-shared-foundry` backend, managed-identity
  authentication and 180-second, unbuffered forwarding policy unchanged.
  No new operation policy, backend, role assignment or parent-policy change
  was needed.
- [x] Verified before/after metadata and hashes: revision 1 retains its 50
  original operations; revision 2 retains all 51 original operations and has
  exactly the one new operation, for 52 total. API/revision/version metadata
  and global/API policies are unchanged.
- [x] Both authenticated saved-model diagnostics returned HTTP 200 and
  `success: true` for `gpt-6-luna` and `gpt-6.1-terra`, reporting the exact
  `/shared-foundry;rev=2/openai/v1/responses` gateway URL. Credentials remained
  server-side; none were extracted or entered again.
- [x] Visible V1 model selection and Send produced `APIM-V1-LUNA-OK` and 20
  requested tips. Visible V2 selection and Send produced `APIM-V2-TERRA-OK`,
  30 tips and `APIM-V2-TERRA-END`. The V2 stream returned HTTP 200 with
  `text/event-stream; charset=utf-8`.
- [x] A full reload retained exactly one of each reply marker and all 50
  numbered tips, with an empty composer and no active generation.
- [x] Retained `SharedAPIM Responses` **enabled**, as approved. Kept
  `Shared Foundry Responses (Direct)` **disabled**. Direct Foundry is explicitly
  out of scope and is not an active sign-off dependency.
- [x] Removed the single disposable conversation
  `7841cafe-d597-4eec-8191-c4e79191d7d0` and restored the original direct
  `gpt-5.6-terra` selection.

The visible saved editor still returned application 409, including after
explicitly selecting Responses. Its unsaved draft was cancelled; no model
editor changes were saved. The successful saved-ID diagnostic tests the
authorized backend using its stored routing and credentials, **not** the
editor round trip. UI-R1 was open at the end of the .430 retest and is closed
by the .432/.433 saved path-order fix below.

The historical 19/3/3 retest ledger above is unchanged as a .430 record. **CFG-R1 is now satisfied
through APIM**, but the remaining application, live-action and collaboration
gates still prevent overall staging sign-off. No application source, version,
release notes, GitHub issue, Git commit or deployment was changed by this
configuration follow-up.

### Resolution Deployment: 0.261.433

The remaining three application defects and the GPT-6 workflow-capacity gate
were corrected locally, deployed through the repository ACR publisher and
live-tested in staging. This is the current acceptance baseline.

| Identity | Value |
|---|---|
| Application version | `0.261.433` |
| ACR run | `cpf` |
| Tested App Service image | `simplechat2026stageacr.azurecr.io/simplechat@sha256:2eaaf3fefe9fcca072dd48dba3962bf89a37fbb967870523404324487a914cf9` |
| Previous/rollback image | `simplechat2026stageacr.azurecr.io/simplechat@sha256:5b68eb83dccc189394f80657e216dc0d0a97e19f81e297ceab5bdff5d3e5f735` |
| App Service | `simplechat-2026stage-app`, production slot, `simplechat-2026stage-rg` |
| Health | Authenticated configured `/external/healthcheck` returned HTTP 200 |

- [x] **Immediate V2 Retry (.431 and .432):** A newly completed `gpt-6.1-terra` answer retried
  immediately, without reload, at attempt 2/2. The original route/model was
  retained and no user-safe error appeared.
- [x] **Saved Responses editor (.432):** Reopening `SharedAPIM Responses` retained
  `Responses` for both Luna and Terra. Test Connection returned HTTP 200 and
  the exact `/shared-foundry;rev=2/openai/v1/responses` URL without saving
  the draft. No 409 occurred.
- [x] **Claude Legacy core (.432):** A new manual Legacy-core workflow completed 1/1
  task through `claude-opus-4-6`, with Review complete and exact result
  `CLAUDE-432-LEGACY-OK.` Exact catalog metadata now supplies the required
  `toolCalling` capability without changing flags or dropping tools.
- [x] **GPT-6 capacities:** Exact Azure/OpenAI specifications were added:
  1,050,000 context, 922,000 input, 128,000 output and total-generation
  accounting. Luna Chat Completions tool requests use the verified
  `reasoning_effort=none` contract.
- [x] **Luna workflow:** The live run reached inference with one request and
  a known 922,000-token input ceiling; the old provider 400 disappeared.
  It was incomplete only at the existing mandatory
  `completeness_no_progress` checker, not at routing or capacity validation.
- [x] **Terra Responses workflow:** The live Responses producer returned exact
  text `TERRA-433-RESPONSES-CAPACITY-OK` with the same verified known budget.
  The run was incomplete only because the existing mandatory checker reported
  `completeness_verification_unavailable`.
- [x] Focused local evidence passed: 15 V2 Retry browser tests, 9 endpoint
  editor/browser tests, 95 catalog/workflow tests with 25 subtests, 52
  retry/Responses tests, V2 typecheck/build and changed-file diagnostics.
- [x] Removed the single temporary workflow and all six generated
  workflow/retry conversations. Restored `gpt-5.6-terra`, empty composer and
  the original permanent connection/default state.

The two GPT-6 producer results prove route, capacity and inference success.
Those original runs were incomplete; the reruns below are separate evidence.
No direct Foundry fallback was retested or broadened.

### Final Batch Deployment: 0.261.434

| Item | Evidence |
|---|---|
| Staging build and health | ACR `cpg` succeeded with the Node.js 24 React build stage. App Service was `Running`/`Normal`; authenticated `/external/healthcheck` and `/api/v2/bootstrap` both returned 200, with bootstrap reporting `0.261.434`. |
| Tested image | `simplechat2026stageacr.azurecr.io/simplechat@sha256:5be5e4fb30f6dbd5dfa13d4fce0c0a3b5828d559cca323d640ece836407a568f` |
| Previous image (rollback candidate) | `simplechat2026stageacr.azurecr.io/simplechat@sha256:2eaaf3fefe9fcca072dd48dba3962bf89a37fbb967870523404324487a914cf9` (.433). No rollback exercised. |

- [x] **Native dropdown:** Opened V2 Admin → AI Models in the shared browser
  and visually verified option and optgroup contrast in dark and light mode.
  The original dark preference and unset default were retained.
- [x] **Terra Responses review:** The same task was incomplete on .433
  (`2778d6f1-b0ea-5175-9aed-ee3f5ec8a60e`) and completed 1/1 on .434
  (`cac9904a-80d3-5598-8929-bea28d48571b`) with Review complete and the
  digest-verified `STAGE-TERRA-ANSWER-OK`. The mock-transport regression
  independently verifies the exact v1 route, strict JSON schema and
  timeout as SDK transport metadata. The runtime producer budget label
  is not evidence of its wire protocol.
- [x] **Luna and Claude:** Legacy-core runs `7da07011-b297-5d31-ae15-369953e1d176`
  and `670e4df8-4259-58b7-a66f-29d5b47cef81` each completed 1/1, with Review
  complete and exact artifacts `STAGE-LUNA-ANSWER-OK` and `STAGE434-CLAUDE-OK`.
  This does not claim either run invoked a tool.
- [x] **V2 Retry and Stop:** Shared APIM Terra Responses chat
  `3b0fbfeb-836c-4737-ad06-7268cb360813` retried immediately without reload,
  kept its model and showed attempt 2/2. Stop preserved partial text and the
  stopped label after reload and a subsequent successful turn.
- [x] **Classic editor:** Both saved model selectors stayed on Responses.
  Luna Test Connection returned 200 on the exact `/shared-foundry;rev=2/openai/v1/responses`
  operation; the draft was closed without saving.
- [x] **XLSX:** V2 chat attached a synthetic two-sheet workbook and returned
  `XLSX_TOTAL=38` for `FixtureTotals`, `B2:B3` in `StageValues`. Earlier
  staging evidence still covers CSV `TOTAL=35`.
- [ ] **TSV:** V2 chat attachment returned “This file type is not supported
  for chat uploads.” No end-to-end TSV inference result.
- [ ] **Tool-dependent answer review:** Terra run
  `10e632e0-ec3b-5094-8013-e116cade1ba6` returned `MATH=293764357`, but
  the reviewer could not verify the action's identity or complete history.
  Do not treat the numeric result as exactly-once proof.
- [x] **Cleanup:** Removed the disposable workflow and seven test
  conversations, including the XLSX chat attachment's conversation. Removed
  the failed TSV draft. Verified zero matching rows, dark theme, original
  `gpt-5.6-terra` composer selection, and a blank draft. No permanent
  model connection, APIM, policy, or GitHub changes.

Local validation: 279 focused backend, 42 isolated tabular compute, and 15
Retry browser tests passed. The combined admin/classic browser run had
146 passes and six failures of `test_routing_preview_validation_and_mobile_layout`
(admin, personal and group, at both widths): the invalid-route message
was not shown in the expected preview output. This does not contradict the
successful live **valid** Responses probe. The multisheet offline test also
failed to collect at an existing Cosmos import boundary; its live XLSX
fixture passed. Full guarded collection gave the same 80 errors before
and after; Cosmos still reported 433 review gaps and did not run its
contract child; the legacy access-count expectation still reads 14 versus
33 in both sources. These are not green release gates.

### Evidence Identifiers

Disposable objects were deleted after collecting evidence. These IDs identify
the tested operations and retained service telemetry, not surviving test links.

| Scenario | Evidence |
|---|---|
| V1 direct/agents/Stop | Conversation `f457fba6-1530-4c4d-a261-3db3120e7c3b` |
| V2 direct/agents/Stop/Retry/edit/deletion | Conversation `a5f4c1e3-6ac6-411d-afc6-941576292d27` |
| Early Stop | Submission `154f8199-b19d-441d-9c98-c353709164cb` |
| Fresh CSV | Conversation `58334712-28aa-4bbd-841a-6f9ec2c8103d` |
| Active navigation | Conversation `c21a97c1-97ad-4a05-a33a-a3fe50c03c5e` |
| Claude verified result | Workflow `a249e938-8b5d-453c-805f-43e0d4f397c0`; run `a017cde5-96f3-5ede-97e3-47788e10b91c` |
| Legacy provider rejection | Run `4e850b8d-60b3-582a-94d6-6eb621b32638`; reference `c8438f8d` |
| Structured provider rejection | Run `bee1cd9b-b6ac-5906-a4a9-34c90e2f3c06`; execution `a52074d473475a1e54f72b1f0e08134fe5f6745d6c9c2782a50860798386ea28`; reference `bb242d9e` |
| Known staging Responses/Stop | Conversation `7db373fb-f477-4366-99e7-28910d3d47ed`; Stop submission `22f7ef94-c82c-4695-bfe7-a3783398cf5c` |
| Shared APIM Responses, before operation | Conversation `7f31edb7-63ac-422c-8760-561f59478b0a` |
| Shared APIM Responses, after operation | Conversation `7841cafe-d597-4eec-8191-c4e79191d7d0` |
| Direct shared Responses fallback, not active scope | Conversation `1e4c2230-cd0d-4e2b-a441-07d9ba656056` |

The newly observed 404 on .430 does not retroactively establish the unknown
provider status of the historical .429 fixture.

### Cleanup and Remaining Gates

- [x] Remove exactly the 11 disposable conversations and both test workflows.
- [x] Remove the temporary failure connection, subsequently reused only as the
  known staging Responses control, and the synthetic CSV.
- [x] Verify no test rows remain in the feed, no test workflows remain, and the
  test document remains absent after reload.
- [x] Preserve the pre-existing `merge-tabular-test.csv`.
- [x] Preserve the current baseline: personal/group workflows already enabled;
  personal agents and personal/group custom endpoints disabled; global
  Semantic Kernel, multi-endpoint mode and thoughts enabled.
- [x] Keep mandatory completeness checking enabled, with two maximum corrections.
- [x] Restore direct `gpt-5.6-terra`, empty draft, closed mobile Tools and no
  active generation.
- [x] Retain only the explicitly approved permanent configuration and scoped
  role grant above; both connections were disabled at the original retest.
  The later explicit approval enables only the now-verified APIM connection.
- [x] **A2-R3:** Fix immediate Retry for a newly completed answer without
  requiring a full reload; retain correct route and attempt history.
- [x] **A4-R4:** Verify the exact Claude route's real tool capability and resolve
  core-mode support without blindly changing capability flags or dropping tools.
- [x] **UI-R1:** Correct the saved Responses editor/Test Connection round trip;
  distinguish application 409 from upstream operation failures.
- [x] **CFG-R1:** Establish a working shared Luna/Terra Responses route through
  the explicitly approved compatible operation in existing APIM revision 2;
  saved-model diagnostics and V1/V2 chat passed. Direct Foundry is not in scope.
- [ ] Obtain live action-bearing Responses and two-participant collaboration
  evidence before claiming those acceptance cases.
- [x] Resolve GPT-6-capacity routing and record the .433 rollback target.
- [x] Move root collection, the Cosmos review inventory, and the stale workflow
  access-count expectation into the
  [Python backend test revamp](./PYTHON_BACKEND_TEST_REVAMP_PLAN.md), per the
  2026-11-18 deferral. Their historical results were not passes.

The bundled App Service diagnostic script could not run its deprecated
deployment-list command, but did collect Running/image metadata; the real
health GET passed. That CLI failure is not an application health failure.
Foundry's required readiness script installed the missing
`azure.ai.evaluations` tooling extension `1.0.0-beta.2`; no project/Python
dependencies were changed during live testing.

**Disposition: live validation complete, staging sign-off withheld.**

### Endpoint and Responses Agent Staging Retest: 0.261.435

| Item | Evidence |
|---|---|
| Staging build | ACR `cph` succeeded; App Service image pinned to `simplechat2026stageacr.azurecr.io/simplechat@sha256:8cdfa74121d89df9eee62dab249fcb0b8e39d817088947a9a52f2cd83b446871`. |
| Previous image | `.434`: `simplechat2026stageacr.azurecr.io/simplechat@sha256:5be5e4fb30f6dbd5dfa13d4fce0c0a3b5828d559cca323d640ece836407a568f`. |
| Runtime | The old worker initially answered .434. After a staging-only restart, authenticated health and bootstrap both returned 200; bootstrap reported .435. |
| Classic admin | An invalid synthetic draft returned 400, kept the editor open with focus on the inline routing error, and created no connection. All six classic scope/viewport regressions passed locally. |
| V2 agent editor | The same New agent flow now loads options with HTTP 200 and shows the two saved SharedAPIM Responses models. The picker response excludes connection details and auth. No second agent was saved. |
| Retained agent | [Staging Responses Math Smoke Test](https://simplechat-2026stage-app.azurewebsites.net/v2/chat?agent_id=e8d5a44d-2510-415d-8b9a-05c6611139ed&agent_scope=global&new=1) (saved via classic; exercised through V2). |
| Persisted action proof | [Passing example](https://simplechat-2026stage-app.azurewebsites.net/v2/chat?conversationId=8403fefa-4b78-4a7b-aea0-26cf13c96687) survived reload; Sources shows one successful `MathPlugin.Multiply` with inputs `13729`, `42893`, result `588877997`, and matching answer `MATH=588877997`. The other listed entries are conversation context/history, not duplicate Math invocations. |

No existing agent, connection, default, permission, APIM operation, or
production resource was changed. The failing synthetic chat was removed.

## Risks and Mitigations

| ID | Risk | Mitigation |
|---|---|---|
| R1 | V2 preserves partial text but duplicates the persisted message | Reconcile by stable turn/message identity and test terminal races |
| R2 | GPT-6 catalog limits drift from a future deployed version | Keep exact model/version evidence, run workflow budget tests and verify live deployments before changing profiles |
| R3 | Workflow provider failures are automatically replayed | Classify effect certainty; replay only explicitly safe work |
| R4 | CSV tolerance weakens Excel semantics | Apply format detection before normalization and preserve Excel `header_row=0` |
| R5 | Retry containment truncates useful multi-step analysis | Dedupe exact failures and cap repeated-equivalent work; do not remove useful distinct calls |
| R6 | UI filtering hides models while server requests still accept them | Enforce the same capability resolver at picker, request, replay, agent, and workflow boundaries |
| R7 | V2 deletion UI exposes or deletes unauthorized resources | Backend prerequisite/authorization checks and dependency preview are mandatory |
| R8 | V1/V2 parity work creates duplicated authoring stacks | V2 remains canonical; V1 receives links, accessibility, and compatibility behavior |
| R9 | Raw provider errors or private reasoning leak into recovery | Stable public error projection, no raw body serialization, and redaction tests |
| R10 | The pinned merge silently absorbs newer Development behavior | Treat source refresh as a separate reviewed merge/rebase operation |

## Progress Log

| Date (UTC) | Work item | Status | Evidence / PR / commit / digest | Owner |
|---|---|---|---|---|
| 2026-11-14 | Planning and six-agent review | Done | This plan; 36/9/1 focused staging result summary; partial Sonnet UI output retained as verification leads only | TBD |
| 2026-11-13 | Model picker defect | Open | `microsoft/simplechat#1928` | TBD |
| 2026-11-13 | Staging cleanup | Done | Temporary endpoints/groups/workflows removed; Responses restored off; original flags restored | TBD |
| 2026-11-16 | Ready stabilization tranche | Implemented locally | 0.261.429; 102 focused Python tests passed; 3 V1/V2 browser tests passed; V2 typecheck/build passed. Full-repository collection remains blocked by module-path/live-Cosmos setup errors. | TBD |
| 2026-11-16 | Staging retest and cleanup | Release gates failed | Version 0.261.429; configured image digest `7295681b21a4652f3dcaa3ec7d675cf37e7d736292f031635db6a150c7d28bce`; 12/7/1 check entries. Picker, direct/APIM chat and CSV fixes verified; cancellation persistence/race and workflow follow-ups remain. Temporary settings and objects removed. | TBD |
| 2026-11-16 | Approved .430 corrective tranche | Implemented locally; gates open | Exact submission/Cosmos terminal authority, truthful persisted interruption status, same-route JSON verification and safe workflow diagnostics; focused results in the fix record. 27 browser tests pass. Wider Cosmos inventory, stale access-count assertion and root collection/staging gates remain unresolved. No commit/push/deployment. | Single implementation owner |
| 2026-11-17 | .430 actual staging acceptance | Sign-off withheld | Visible .430; image `9674b77ca3945513fc91ccede6ed01053c890bc716239c9be6a391821e48fd69`; 19/3/3 live entries. Personal cancellation, CSV, checked Claude no-tools results and legacy/structured failure histories verified. Immediate Retry, Claude core and shared Responses/editor follow-ups remain. | Coordinator |
| 2026-11-17 | Permanent Responses configuration | APIM follow-up completed | Original retest retained the APIM configuration disabled because the compatible operation was absent. The in-place operation was added later and the APIM connection enabled. Direct fallback is disabled and explicitly out of scope. | Admin approval / coordinator |
| 2026-11-17 | Approved in-place APIM Responses operation | Gateway gate passed | Added only `POST /openai/v1/responses` to existing revision 2; no new revision/version or parent-policy changes. Luna/Terra saved-model tests returned 200; V1 Luna and V2 Terra SSE chat/reload passed. APIM connection retained enabled as approved; direct fallback disabled. The later .432 fix closed the editor 409. | Admin approval / coordinator |
| 2026-11-18 | .431–.433 stabilization resolution | Original defects live verified | Retry, Claude core, Responses editor and verified GPT-6 routing/capacity passed. Final ACR run `cpf`; image `sha256:2eaaf3fefe9fcca072dd48dba3962bf89a37fbb967870523404324487a914cf9`; rollback .432 image recorded. Temporary fixtures removed. | Admin deployment / coordinator |
| 2026-11-18 | .436 shared-browser validation | Main flows pass; B0-R1 open | Authenticated .436 health/bootstrap, Classic/V2 request routing and embedding tests, V2 native streaming/Stop, and persisted Math action. All .436 fixtures removed; no build or deployment initiated by this pass. | Coordinator |
| 2026-11-19 | .437 agent settings and native dropdown follow-up | Live staging retest passed | ACR `cpk`; authenticated .437 health/bootstrap, both global agent editors with a disabled saved route, and opened Method popup in both themes. Fixture removed; .436 rollback digest recorded. | Coordinator |
| 2026-11-19 | .438 app-wide V2 native dropdown fix | Live staging retest passed | ACR `cpm`; exact Catalog menu in both themes, grouped default and Method popups, and My Workspace workflow menu. Ten focused Chromium cases and the production build also passed. | Coordinator |
|  |  |  |  |  |

## Sign-Off

### Engineering

- [x] The original P0 implementation defects are satisfied: immediate Retry,
  Claude Legacy core, saved Responses editing and verified workflow capacities.
- [x] All focused Python, V2, and relevant browser suites for this resolution pass.
- [ ] Full repository pytest passes.
- [ ] No authorization, secret, privacy, or XSS regression is open.
- [ ] The reviewed source commit and final implementation commits are recorded.

### Staging

- [x] ACR build run, immutable image digest and rollback image recorded together.
- [ ] `/api/health` and `/api/ready` pass.
- [x] The actual configured SimpleChat `/external/healthcheck` returns 200.
  The two assumed paths above were not tested in this pass.
- [x] V1 and V2 direct chat pass.
- [x] APIM Claude, Luna, and Terra pass.
- [x] Responses baseline and tested Stop behavior pass.
  Shared-APIM inference, V1/V2 history, V2 SSE, Stop, reload and follow-up pass.
  The retained local agent's live Math action passed on .435 and .436;
  tool-dependent workflow review remains a separate gate.
- [x] Retest B0-R1 and B0-R2 on the running .437 staging image.
- [x] Retest the broader B0-R2 fix on .438 across multiple V2 surfaces.
- [x] Luna/Terra routing and capacities reach inference with verified limits.
  Claude Legacy core passed; GPT-6 producer results are retained. Mandatory
  checker completeness remains separately open.
- [x] CSV `TOTAL=35` passes.
- [x] Test settings and temporary objects are removed.
- [x] The previous .437 image is available and documented for rollback from .438.

### Product/UI

- [ ] V2 confirmed gaps are accepted or deferred with an owner.
- [ ] V1 compatibility links are sufficient for canonical V2 editors.
- [ ] Retry, deletion, migration, and cancellation behavior have documented user
  experience.
- [ ] Unverified UI leads remain explicitly unimplemented until confirmed.

Final disposition: **.437 agent settings and .438 native dropdown fixes
accepted on staging.** Broader acceptance, deferred test-suite work and
source-control closeout are tracked separately.
