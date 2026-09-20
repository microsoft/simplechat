# SimpleChat M5B completion and next-milestone handoff

Prepared: **2026-09-20**. Repository: **microsoft/simplechat**.

M5B implemented in version: **0.261.122**.
Version source: `application\single_app\config.py`.

**M5B is implemented and verified. The next milestone is a proposal, not
approved implementation.** This handoff supersedes the old
`WORKFLOW_M5B_AND_OPEN_ITEMS_HANDOFF.md` statements that M5A was unmerged and
M5B was not implemented.

The owner authorized committing, pushing, and preparing this handoff.
That does not authorize a new feature implementation, PR creation, merge,
deployment, permission changes, live workflow execution, or live publication.

## 1. Start here

| Item | Verified checkpoint |
| --- | --- |
| M5B implementation commit | `e25e70209eeb7065da73ae9a420f7c1560d62ef2` |
| Implementation branch | `paullizer-workflow-visual-authoring` |
| Intended integration / PR base | `paullizer-react-v2-ui`, **not** default `Development` |
| Fetched integration tip before publication | `befdb6e6e370dc4a0c322f04c1f85386217f01d7` |
| M5A prerequisite | #1505 merged at `2026-09-20T00:31:54Z` |
| Actual M5A merge commit | `befdb6e6e370dc4a0c322f04c1f85386217f01d7` |
| M5B PR at this checkpoint | None; PR creation has not been requested |
| Application version | `0.261.122` |
| Application commit scope | 30 files; 6,596 insertions and 1,805 deletions, including extracted forms and tests |
| Issue association | Session-only tracking; the owner's no-new-issue choice remains in effect |
| Next milestone | Proposed next M5 slice: cross-surface authoring undo/redo |

The handoff is committed separately from the implementation so the feature
commit above remains a stable reference. Refresh remote state before relying
on branch or PR status; a pushed branch is not a merged release.

1. Fetch `origin/paullizer-react-v2-ui` and
   `origin/paullizer-workflow-visual-authoring`.
2. Check whether a PR for the M5B branch now exists and whether it has landed.
   Do not create a duplicate PR or recreate M5B.
3. If M5B is unmerged, perform only authorized closeout or obtain explicit
   approval to stack the next slice on its feature branch.
4. If merged, verify the actual merge/squash commit and implemented code on the
   fetched V2 integration branch. A squash merge is not a reason to cherry-pick
   the old implementation again.
5. Start the next implementation from a worktree containing that verified
   code. Do not silently use `Development`, a stale M4/M5A checkout, or the
   main checkout.
6. Read current repository instructions and the actual version. Obtain
   approval for the next slice before code changes.

The integration history already includes M4A #1496, M4B #1498, M4C-1 #1499,
M4C-2 #1501, M4C-3 #1504, and M5A #1505. There is no approved unfinished M4
implementation slice to restart.

## 2. What M5B delivered

Authorized authors can edit the same supported definition-v3 workflow from
**List authoring** or **Flow authoring** inside the existing editor.

| Capability | Delivered behavior |
| --- | --- |
| Canonical draft | One `WorkflowDefinition`; no graph-to-definition serializer or second persisted executable graph |
| Structured editing | Add, configure, move, remove, and bind tasks, If/else, forward routes, For each, Repeat until, Collect, joins, and root/body outputs |
| Existing configuration | Shared task instructions, runners, references, schemas, approvals, Run when, Analyze, reporting, and publication configuration |
| Semantic controls | Explicit buttons/selectors; dragging and view controls change temporary geometry only |
| Reference safety | Concrete impact confirmation for removals and reference-breaking moves; retained exact selectors, no silent cascade/retargeting, Save blocked until invalid references are repaired |
| Unfinished fields | Invalid schema text/errors, unfinished decision fields, raw query tags, and Repeat-row identities survive form/surface changes |
| Incomplete drafts | Current structure stays editable; old executable arrows disappear until the compiler accepts the exact current candidate |
| Selection and focus | Canonical List/Flow selection, keyboard controls, post-edit focus recovery, and Escape cancellation of impact dialogs without dismissing the editor |
| Mobile/browser behavior | List remains default; stacked Flow configuration, page scrolling, native Ctrl+wheel/pinch, and explicit view controls |
| Save and access | Original saved CAS revision, existing scoped Save, active-run/read-only guards, no dismissal or duplicate write during Save, and protected-data clearing after confirmed access loss |
| Read-only inspection | Saved-definition and frozen-run Flow remain read-only |

Version 3 remains opt-in. Opening Flow does not convert a v1/v2 definition.
Successful Save still closes the editor. Ordinary validation, network, and CAS
failures retain edits; there is no automatic overwrite or rebase.

No scheduler, Repeat transition, backend compiler, exporter, publication-service,
route, dependency, or deployer-version change was made for M5B. The only
application Python change was the application version.

### Important implementation details

- `applyWorkflowEdit` returns applied, confirmation-required, or rejected
  outcomes. Commands resolve current canonical IDs, preserve unaffected IDs,
  and reject invalid structural changes atomically.
- `useWorkflowAuthoring` manages confirmation/reconfirmation, selection,
  focus, and temporary geometry. It is **not an undo manager**.
- `WorkflowFieldDraftStore` holds raw fields and errors outside mounted forms.
  Its `getSnapshot()` returns the React subscription revision, **not a
  restorable authoring snapshot**. No history snapshot/restore API exists yet.
- Field owners use task/node IDs and Map-backed keys. Repeat field-row IDs are
  editor-only, stable through renames/removals, and never saved.
- `workflowForSave` preserves the original envelope and CAS token.
  `workflowForFlowPreview` sends all server-authored revision fields and source
  identity, excluding only opaque envelope/runtime metadata from preview.
  Tests compare the frontend field list with server `WORKFLOW_DEFINITION_FIELDS`
  and prove the authored digest/compiler meaning is unchanged.
- Never strip unsupported nested executable fields to make preview succeed.
  The inspection parser and backend normalizer remain strict.
- Preview uses debounce, abort, generation, and exact-candidate keys. Keep
  memoized payload/error dependencies stable: layout/selection must not cause
  extra preview requests.
- Pinned React Flow `12.11.6` uses `@xyflow/system` `0.0.82`, which cancels
  Ctrl+wheel before its disabled-zoom filter. The canvas capture boundary
  preserves native wheel/pinch behavior without changing the dependency.
- Both modal layers receive Escape. The editor's close handler must cancel a
  pending impact dialog rather than open an unrelated discard dialog.

## 3. Delivery work still to do

These are release/coordination gates, not unfinished M5B implementation.

| Work | Required next action |
| --- | --- |
| M5B PR | Obtain permission to create a PR targeting `paullizer-react-v2-ui`; describe scope, offline evidence, known exclusions, and deferred items |
| Review and CI | Refresh required checks/reviews and handle genuine in-scope findings; local passes are not a remote CI result |
| Intervening changes | Compare current integration code/version before landing; resolve conflicts deliberately without overwriting newer work |
| Release notes | Ask about the M5B entry for `0.261.122`; release notes were not updated in this work |
| Broader announcement work | Keep earlier release-note backfill and Latest Feature/cards/media decisions in O6 |
| Landing | Obtain explicit merge authorization, then verify actual merged code before beginning a dependent milestone |
| Live acceptance | Keep it in O8; no environment, paid-service operation, publication destination, or rollout has been authorized |

The documentation inventory was regenerated and verified current, with no
content delta. No issue, PR, merge, deployment, card/media publication, or live
workflow operation was created/performed by the M5B implementation session.

## 4. Proposed next milestone: cross-surface authoring undo/redo

### Intended outcome and scope

Let a definition-v3 author undo and redo unsaved semantic edits and unfinished
field work across List and Flow, without changing canonical identities, the
saved CAS baseline, or any historical execution.

This is the recommended **next M5 slice**, following the owner's explicit
request to carry undo/redo forward. No M5C/M6 label, delivery date, or new
implementation approval is implied. Confirm the label and scope with the
owner rather than presenting this proposal as an existing commitment.

Recommended scope includes the common workflow fields as well as structured
commands: name/description, runner/schedule, shared references, limits, task
configuration, typed bindings, schemas, joins/outputs, and loop/Repeat fields.
An implementation covering only structural Add/Move/Remove would be incomplete
unless the owner explicitly approves that smaller scope.

Exclude saved/run viewers, server rollback, workflow execution, persistent
history, collaborative editing, v1/v2 history, layout history, direct connection
gestures, and O1-O9/spend-cap implementation.

### Decisions to approve before implementation

| Decision | Recommended proposal / unresolved detail |
| --- | --- |
| Transaction unit | One structural operation or committed field action; canonical and raw-buffer changes from the same action must be atomic |
| Typing/coalescing | Coalesce edits to one canonical owner/field; close a group on blur, owner/surface change, or another semantic action; handle IME composition explicitly |
| History bound | Bound entries and retained memory. Measure realistic maximum-size drafts/buffers and approve exact limits and eviction UX; no arbitrary cap is selected here |
| Reference-breaking replay | Re-run current eligibility and impact checks; conservatively require confirmation when replay would break references |
| Successful Save | Keep close-on-success behavior; clear session history at the successful save/session boundary |
| 400/network/409 failures | Preserve local draft/history appropriately; never auto-rebase or replace the original CAS token |
| Reload/discard/workflow/scope change | Start a new history boundary; do not mix definitions or scopes |
| Confirmed access loss | Invalidate history and protected buffers; history must not restore restricted information |
| Keyboard behavior | Native text undo stays native inside text controls; propose editor Undo/Redo shortcuts outside them and equivalent common toolbar buttons |
| Selection/focus | Restore the affected canonical selection where possible, otherwise a surviving sibling/parent/root; expand ancestors without recording view-only actions |

### Proposed design

Keep a single editor-session history controller beside the canonical draft and
field store. The original saved definition/revision must remain outside the
undoable state.

History must restore the authored state that actually existed, including
invalid raw schema text, errors, unfinished builders, raw spacing, and an unset
Repeat maximum. Do not JSON-round-trip snapshots: that loses values such as
`NaN` used for an explicitly unset maximum.

Store/replay exact canonical identities. Redoing creation must restore the same
IDs, not call a creation helper that generates replacements. Decide between
non-lossy snapshots with sharing and reversible patches after measuring
retention; either approach must use the existing grammar, guards, and compiler.

The integration has two mutation paths to cover:

1. Shared structured commands in `applyWorkflowEdit` / `useWorkflowAuthoring`.
2. Common fields and legacy form callbacks that still update the root draft,
   plus `WorkflowFieldDraftStore.field(...).setValue(...)` and buffer lifecycle
   operations.

Do not record the same user action twice when a field updates both its raw
buffer and parsed canonical value. Form mount/initialization, preview responses,
server errors, selection, pan, zoom, collapse, and geometry are not user edit
transactions.

Add explicit capture/restore support to the field store rather than treating
its subscription revision as a snapshot. Capture buffers before task/contract
removal prunes owners, so Undo can restore them. Restore definition and buffers
atomically, with stable Repeat-row identities and no rollback-induced row-ID
collisions. No history or field metadata enters Save payloads or browser storage.

Recompute dirty state from the restored definition and buffers against the
opening baseline. Undoing back to that baseline should become clean; restoring
an invalid buffer must restore validation and keep Save/preview ineligible.

Reuse current read-only/saving/active-run/scope guards for every replay, not just
disabled toolbar buttons. Pending or rejected operations create no history entry.
An intervening semantic edit invalidates Redo. Exact policy for changed
capabilities and confirmation/reconfirmation belongs in the approved design.

Preserve the current preview contract: invalidate old topology immediately,
debounce only eligible current candidates, reject late responses, and never
replace the draft or saved revision with `DRAFT:` data.

### Implementation sequence after approval

1. Verify the landed/explicitly approved base and settle the decision table.
   Add before/after fixtures for valid, invalid, buffer-only, and structural
   edits; select measurable retention limits.
2. Implement/test a pure bounded history model: transactions, coalescing,
   non-lossy restore, Redo invalidation, and reset boundaries.
3. Add field-store capture/restore and atomic definition/buffer transactions,
   covering owner pruning, contract replacement, and Repeat-row removal/rename.
4. Integrate both mutation paths, preserving current command guards,
   reference-impact confirmation, original CAS, and failure behavior.
5. Add shared Undo/Redo controls, action labels, shortcut routing, and focus
   recovery. Keep saved/run views read-only and native text editing usable.
6. Run new command/compiler and real-bundle browser regressions plus affected
   M5B/M5A/editor tests. Verify no accidental runtime/publication requests.
7. Update feature/guide documentation and the actual current application patch
   version after implementation. Regenerate/check documentation coverage.
   Obtain separate release-note, commit/push, PR, landing, and live-operation
   permissions when they have not been given for that future work.

Planning alone must not change executable code, install dependencies, or bump
the application version. Do not preallocate `0.261.123` from this document.

### Acceptance matrix for the proposed slice

| Area | Required evidence |
| --- | --- |
| Full coverage | Common fields and every supported structured/binding operation participate, not only canvas buttons |
| List/Flow parity | Edit in either surface, switch, Undo/Redo, and get identical canonical/Save meaning |
| Exact identity | Add/remove/move and replay preserve task/node/region/join IDs, including distinct task/catalogue IDs and legal `constructor` IDs |
| Invalid fields | Invalid schema text/errors, builder fields, tag spacing, and unset Repeat limits restore exactly and still gate Save |
| Atomic buffers | Removing a task/contract/Repeat row and undoing restores the right owner's buffers without mixing rows or losing errors |
| References | Cancelled/rejected actions add no entry; confirmed changes and replay preserve exact outside selectors without cascade |
| Dirty/CAS | Undo to the opening baseline becomes clean; no replay changes the original saved revision or rolls back a server save |
| Async/access | Delayed previews, options changes, 400/409/network failures, access loss, close, and scope changes cannot restore stale/protected state |
| Non-semantic actions | Selection, geometry, surface switching, preview completion, and mounting forms do not create history or writes |
| Keyboard/mobile | Common controls, native text undo, shortcuts, confirmation cancellation, focus recovery, scroll, and browser zoom remain usable |
| Bounds | Test the chosen entry/byte limits exactly, including overflow/eviction and large legal definitions; no silent partial restoration |
| Side effects | No Run, Approve, Retry, Resume, Continue Repeat, Publish, readiness reconciliation, source freezing, or admission |

## 5. Future workstreams and open actions

These are separate, unapproved workstreams, not automatic dependencies of
undo/redo and not newly created issues. The owner chooses their priority and
one coherent slice at a time. No M6-or-later milestone numbering is assigned.

| ID | Open action | Work still needed / acceptance boundary |
| --- | --- | --- |
| O1 | Additional saved-source export formats | Select one source/profile/format mapping; define complete values, empty/partial inputs, provenance, authorization, complete-byte digest and quota failure. Reuse the shared exporter rather than creating another one |
| O2 | Orchestration knowledge/reasoning/output producers | Define an authorized real producer adapter, typed output, identities and inspection. Arbitrary model prose is not a saved producer or permission to invent execution IDs |
| O3 | Deterministic aggregates | Select a concrete complete-input use case; define ordering, empty/partial/missing semantics and supported operations before implementation |
| O4 | Office-export test harness/import debt | Identify the exact three historically carried failing selectors and repair the offline harness separately. They were not established as fixed by M5B; do not introduce production credentials or unrelated requirement changes |
| O5 | Revoked-record refresh assertion | Reconcile `ui_tests\test_v2_workflow_loops.py::test_revoked_record_refresh_clears_the_previous_page` with removed-panel UX. Preserve actual restricted-data clearing; do not retain data or weaken authorization to make an old assertion pass |
| O6 | Release notes / Latest Feature strategy | Decide backfill for `0.261.116`-`0.261.120`, M5A `0.261.121`, and M5B `0.261.122`; both M5A/M5B release-note entries remain open. Decide cards/screenshots/videos separately; none were published |
| O7 | Published-guide links to excluded engineering notes | Audit the existing broken-link backlog and repair public navigation or use intentional source links. Current M5B documentation work is not a backlog-wide repair |
| O8 | Non-production live acceptance / rollout | Obtain explicit environment, identity/roles, scope, sources, destinations, allowed paid/runtime/publication operations, budgets, cleanup and success criteria. Offline passes do not establish Azure performance or production readiness |
| O9 | Personal/group Control Center Workflow Monitoring | Define reader/manager/admin visibility, current role policy, scope isolation, queries, paging/retention, refresh and permitted actions. Reuse durable journal facts; do not create another ledger or assume a new monitoring role/setting already exists |

A possible sequencing discussion is: M5B delivery, the proposed undo/redo
slice, individually selected test/documentation hygiene, then a separately
approved monitoring or producer/export/aggregate slice. This is a recommendation,
not authority to start those workstreams or change their priority.

### Separate cumulative run-token/spend cap

This remains an additional deferred requirement, not a new numbered O-item or
part of the proposed undo/redo slice. Existing local metering and admission/time
limits are **not** an enforced cumulative token/spend cap.

Before implementation, define the authoritative accounting scope and units;
model/provider pricing and provenance; reservation/reconciliation; retries,
continuations, native Analyze and multi-call reports; idempotency; concurrent
work; missing/late usage; and the exact pause/fail/recovery policy at the cap.
Usage must not silently become zero when unavailable, and continuation must not
reset lifetime consumption. Define tests and administrative/user documentation
with the selected policy before advertising enforcement.

## 6. Runtime contracts that remain unchanged

- For each is serial: default **500 actual inputs**, administrator range
  **1-5,000**. All matches is not ranked Best N; frozen selection is not a
  transactional workspace snapshot.
- Repeat is serial and post-body, with an explicit finite authored batch,
  separate administrator default **25**, range **1-1,000**, exhaustion pause,
  and authorized same-sized continuation. Only batch usage resets; lifetime
  identity and original budgets do not. True Until on the final permitted
  round succeeds.
- State remains typed `text`/`json`/`records`/`document_results` with explicit initial
  and next producers; no literal-state shortcut, implicit append, coercion, or
  model-prose substitute.
- Preserve **5,000 execution admissions**, **86,400 seconds including waits**,
  **256 structural IDs**, region depth **four**, and **three mixed loop frames**.
- Preserve full For-each `{loop_id, item_id, index}` and Repeat
  `{loop_id, iteration}` paths with zero-based lifetime identity. Attempts are
  separate; root exact lookup uses explicit `[]`.
- Keep default definition v2, opt-in v3, journal schema 2, `workflow-result-v2`,
  and private `workflow-repeat-state-v1`.
- Preserve current source/contributor authorization, accepted-partial limits,
  local loop/report metering, native Analyze IDs, and exact Collect order/lineage.
- `exact_records_v1` preserves duplicates, nesting, Unicode, false, zero, null,
  eligible empty collections and complete-byte digests; quota failure cannot
  publish a prefix artifact.
- Saved-output publication still requires one eligible required records
  `node_output`; no direct Repeat-state publication or invented Analyze IDs.
  Private transport, the destination ledger, immutable fulfilled observations
  and two-fresh-read indexed-readiness proof remain. Download is not completion.
- A view uses one body template per loop, not thousands of items/rounds.
  No cursor draining, inferred execution success, or fallback from a run's
  frozen definition to today's saved definition.

## 7. Code starting points

Frontend paths below are relative to `application\v2_ui\src\`.

| Area | Files / responsibilities |
| --- | --- |
| Root session | `components\workflows\WorkflowEditorDialog.tsx`: original/baseline/draft, dirty state, common fields, surface switch, Save/close and access loss |
| Commands | `lib\workflowAuthoring.ts`: `applyWorkflowEdit`, `indexWorkflowDraft`, `workflowDraftStructure`, `workflowDraftBindings`, reference impacts and hard guards |
| Command controller | `components\workflows\useWorkflowAuthoring.ts`: latest-draft dispatch, confirmation/reconfirmation, focus, selection, geometry reconciliation |
| Field store | `components\workflows\WorkflowFieldDrafts.tsx`: raw buffers/errors, baselines, owner pruning and Repeat-row identities |
| Shared forms | `WorkflowTaskFields.tsx`, `WorkflowStructuredFields.tsx`, `WorkflowConditionEditor.tsx`, `WorkflowLoopFields.tsx`, `WorkflowRepeatFields.tsx` under `components\workflows\` |
| Authoring surfaces | `components\workflows\WorkflowStructuredList.tsx`, `WorkflowFlowAuthoring.tsx` |
| Shared presentation | `components\workflows\WorkflowFlowCanvas.tsx`, `WorkflowFlowView.css`; `lib\workflowFlowLayout.ts` |
| Definition/save/preview | `lib\workflowEditor.ts`: `workflowForSave`, `workflowForFlowPreview`, shared normalization and validation |
| Existing analysis | `lib\workflowFlow.ts`: supported grammar, producers, lexical/definite availability, limits and unsupported-shape checks |
| Read-only inspection | `components\workflows\WorkflowFlowView.tsx`, `WorkflowFlowDialog.tsx`, `WorkflowDefinitionInspector.tsx`; `lib\workflowInspection.ts` |
| Entry/lifecycle | `pages\workspace\WorkflowsSection.tsx`: keyed sessions, options, scope, active-run entry and close-on-save |

Backend authority remains in
`application\single_app\functions_workflow_definitions.py`,
`functions_workflow_flow.py`, `functions_workflow_inspection.py`, and
`route_backend_workflows.py`. Do not modify the scheduler, Repeat transitions,
exporters, or publication service merely to implement authoring history.

Related documentation:
`docs\explanation\features\WORKFLOW_FLOW_AUTHORING.md`,
`WORKFLOW_FLOW_INSPECTION.md`, `WORKFLOW_STRUCTURED_CONTROL_FLOW.md`,
`docs\guides\create-a-workflow.md`, and `docs\guides\trigger-a-workflow.md`.

## 8. Recorded verification and reproduction

These are **completed M5B results**, not tests run by the future conversation.
Selections overlap; do not add them into a unique total or claim a full
repository/live-environment pass.

| Selection | Recorded result |
| --- | --- |
| Command, field-store, Flow semantics and inspection-client Node tests | **84 passed** |
| Authoring compiler contracts plus selected existing schema/digest cases | **67 passed**, 209 deselected |
| Final authoring + M5A real-bundle browser selection | **82 passed**: 30 authoring + 52 inspection; zero failures/errors/skips, 202.46 seconds |
| Legacy editor / saved-output publication / completion browser selection | **140 passed** |
| Structured/Repeat/loop compatibility browser selection | 172 initial passes; two intended Move-confirmation expectation changes then **2/2** focused passes; named O5 excluded |
| M5A backend inspection/policy/layout | **57 passed**, including the selected long-running boundary coverage |
| Selected compiler/CAS/native Analyze/exact JSON/publication/Repeat contracts | **11 passed**, including an actual 1,000-round batch followed by admitted lifetime round 1,001 |
| Local assets / Flow notices | **4/4** standalone local-asset checks; **4** Flow tests plus **25** subtests |
| Documentation | **7/7** inventory/coverage and **6/6** site-quality checks; no inventory content delta |
| Build and guards | Typecheck/build, JS syntax, supported-file XSS/BAC guards and whitespace passed; XSS guard does not classify TSX |

The final UI selection verified the exact local bundle:

```text
index-CW7fmqzz.js
SHA256 AD6261124286ACADCF0B8448CA398F70B7455E03063F7D7B0E5C26B5320C5912

index-XxVl2aY3.css
SHA256 2CD5CCBBA7B8FF58CC5C89D6E18D6F147AD4A5873C6C7C96A988E926A0CFDF2D
```

The verified local report is
`ui_tests\artifacts\m5b-CW7fmqzz-final\results.xml`.
Generated bundles, dependencies, screenshots and reports are not committed.
Rebuild in a fresh checkout; do not assume these files or filenames exist.

The M5B session used Python 3.12.10, pytest 9.0.3, Playwright 1.58.0 and local
Chromium 145.0.7632.6. It did not need the old handoff's absolute virtualenv.
Use a manifest-compatible environment and follow dependency-install rules.
The older Flask/Werkzeug mismatch is not permission to alter global packages.
The existing Vite large-chunk advisory and legacy test warnings were not
feature failures.

Starting commands from the correct worktree:

```powershell
npm --prefix .\application\v2_ui run typecheck
npm --prefix .\application\v2_ui run build
node --test .\functional_tests\test_workflow_flow_authoring_commands.js .\functional_tests\test_workflow_field_drafts.js .\functional_tests\test_workflow_flow_semantics.js .\functional_tests\test_workflow_execution_inspection_client.js
python -m pytest -q .\functional_tests\test_workflow_flow_authoring.py .\functional_tests\test_workflow_loop_schema.py -k "flow_authoring or test_old_empty_path_revisions_and_execution_digests_are_unchanged or test_explicit_input_processing_roundtrips_without_adding_other_task_defaults"
$env:PLAYWRIGHT_SERVICE_URL = ''
$env:PYTHONIOENCODING = 'utf-8'
python -m pytest -q .\ui_tests\test_v2_workflow_flow_authoring.py .\ui_tests\test_v2_workflow_flow_inspection.py
python -m pytest -q .\ui_tests\test_v2_workflow_control_flow.py .\ui_tests\test_v2_workflow_repeat_until.py .\ui_tests\test_v2_workflow_loops.py -k "not test_revoked_record_refresh_clears_the_previous_page"
python -m pytest -q .\ui_tests\test_v2_workflow_editor.py .\ui_tests\test_v2_workflow_saved_output_publication.py .\ui_tests\test_v2_workflow_publication_completion.py
python -m pytest -q .\functional_tests\test_workflow_flow_inspection.py .\functional_tests\route_tests\test_workflow_flow_inspection_policy.py .\functional_tests\test_workflow_flow_layout.py
python -m pytest -q .\functional_tests\test_workflow_flow_assets.py
python .\functional_tests\test_v2_ui_local_assets.py
python .\scripts\build_docs_inventory.py
python .\functional_tests\test_docs_app_surface_coverage.py
python .\functional_tests\test_docs_site_quality.py
git --no-pager diff --check
```

Use the standalone local-asset runner because its legacy tests return booleans.
Keep the named O5 exclusion explicit, not a claim that revocation is untested
or fixed. New authoring and M5A access-loss checks still protect data clearing.
Budget time for real Repeat boundary tests; do not silently replace the
round-1,001 threshold with a small mocked loop.

For affected runtime/export work, retained selectors include:
`test_workflow_definition_concurrency.py::test_racing_definition_edit_is_not_overwritten`,
`test_workflow_definition_concurrency.py::test_active_run_race_blocks_definition_save`,
`test_workflow_loop_native_analysis.py::test_each_document_uses_its_exact_native_producer_and_collects_complete_results`,
`test_generated_file_saved_record_exports.py::test_exact_saved_values_order_multiplicity_and_digest`,
`test_generated_file_saved_record_exports.py::test_quota_counts_delimiters_and_escaped_bytes`,
`test_workflow_publication_completion.py::test_readiness_rejects_archival_on_either_fresh_read`,
and `test_workflow_repeat_execution.py::test_real_thousand_round_batch_then_lifetime_round_1001`,
all under `functional_tests\`.

## 9. Copy-paste kickoff for a new conversation

```text
Continue SimpleChat workflow planning from the attached
WORKFLOW_M5B_COMPLETION_AND_NEXT_STEPS.md.

M5B is implemented in 0.261.122 at
e25e70209eeb7065da73ae9a420f7c1560d62ef2 on
paullizer-workflow-visual-authoring. Do not recreate it. M5A #1505 already
merged as befdb6e6e370dc4a0c322f04c1f85386217f01d7.

First refresh M5B branch/PR status and origin/paullizer-react-v2-ui.
The integration/PR base is that V2 branch, not default Development.
If M5B is unmerged, perform only authorized closeout or obtain explicit
approval to stack on its branch. If merged, verify actual merge/squash code
before starting a dependent slice. Do not merge, create a PR, deploy, or invoke
live services merely because this handoff exists.

Develop a detailed proposal for the next M5 slice: cross-surface authoring
undo/redo. The milestone label and implementation scope are not yet approved.
Cover common workflow fields, shared commands and unfinished field buffers,
not only structural buttons. Define transaction/coalescing rules, measured
history limits, exact ID/buffer restoration, current permission/active-run
guards, reference-impact confirmation, dirty/CAS semantics, reset boundaries,
keyboard/native-text behavior, and focus recovery. Obtain approval before code.

Reuse the single canonical draft, field store, shared commands, strict compiler
preview and existing Save path. Field-store getSnapshot is a subscription
revision, not a history snapshot. Never replay an inspection DTO as a
definition, regenerate IDs on Redo, replace the saved CAS token, restore
restricted data, or record layout/preview activity as semantic history.
Keep saved/run Flow read-only and preserve native scroll/zoom.

Carry O1-O9 and the separate cumulative run-token/spend cap forward without
starting them. Release notes and Latest Feature/card/media decisions remain
open. Honor the no-new-issue choice unless I change it. Do not bulk-create issues.

Preserve existing For-each/Repeat limits, explicit finite batches and same-sized
continuation, full lifetime identities, global budgets, source authorization,
native Analyze, exact Collect/JSON exports and publication-completion semantics.
Use the recorded offline evidence as a baseline, not a claim of new testing.
No live workflow execution, paid acceptance, live publication, permission
changes, deployment, or automatic/PR merge without separate authorization.
Planning alone does not install dependencies, modify executable code or
increment the version.
```
