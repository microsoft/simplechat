# SimpleChat M5C completion and next-milestone handover

Prepared: **2026-09-20**. Repository: **microsoft/simplechat**.

Implemented in version: **0.261.123**

Application version source: `application\single_app\config.py`.

## 1. Current status and delivery record

**M5C implementation and scoped offline validation are complete.**
The implementation is committed and pushed, and its PR is open for review.
This handover is included in that PR. A PR is not a merged release or a
deployed application.

This is the current workflow-programme handover. It supersedes
[the M5B handover](WORKFLOW_M5B_COMPLETION_AND_NEXT_STEPS.md) as a starting
point, without rewriting that document's historical checkpoint.

| Item | Verified state |
| --- | --- |
| Implementation branch | `paullizer-workflow-m5c` |
| Integration / PR base | `paullizer-react-v2-ui`, **not** repository default `Development` |
| Verified starting merge | `a0b178c8cbf85bc2229e5e2697ecb78d09a16f86` |
| Prerequisite | M5B #1506 merged into the V2 integration branch at `2026-09-20T19:18:47Z` |
| Remote base refresh | The integration branch still matched that starting merge when delivery preparation began |
| M5C implementation commit | [`a474dcd4ca947a7cf070541b6ee41b5772c6160b`](https://github.com/microsoft/simplechat/commit/a474dcd4ca947a7cf070541b6ee41b5772c6160b) |
| M5C PR | [#1507](https://github.com/microsoft/simplechat/pull/1507), open and targeting the V2 integration branch; not merged |
| Remote publication checks | Branch-flow and CLA checks passed on the implementation commit. Refresh the latest head before merging; these are not a full application-CI result. |
| Application version | `0.261.123`; only the patch segment changed |
| Release notes | M5C-only entry added for `0.261.123`; earlier backfill remains O6 |
| Issue association | Session-only M5C tracking; no new issue requested or created |
| Next milestone | No M5D/M6 number or detailed implementation scope has been approved |

The owner has **not** authorized merging, deployment, role changes, live
workflow execution/publication, paid-service acceptance, or implementation of
the next feature merely by asking for this handover.

### Completed milestones are not new work

| Slice | Completed capability |
| --- | --- |
| M4A / #1496 | Structured control flow |
| M4B / #1498 | Serial For each, exact Collect and saved-record reporting |
| M4C-1 / #1499 | Publication completion and durable reconciliation |
| M4C-2 / #1501 | Generic saved-record/Collect JSON publication |
| M4C-3 / #1504 | Finite Repeat until, typed state and explicit continuation |
| M5A / #1505 | Read-only saved/frozen-run Flow inspection |
| M5B / #1506 | Accessible shared-draft List/Flow authoring |
| M5C / this branch | Cross-surface unsaved authoring Undo/Redo |

Older M4 documents sometimes describe the then-future M5 work. That is
historical scope, not evidence that those implementations must be rebuilt.
Refresh actual PR/merge state before starting a dependent slice.

## 2. What M5C delivered

List and Flow share one session-local history for supported definition-v3
authoring. Common fields, structured commands, bindings, schemas, loop/Repeat
configuration and unfinished field buffers participate together.

Typing groups by field visit. Compound actions restore the canonical
definition and raw buffers atomically. Undo/Redo preserves exact task, node,
region, join and Repeat-row identities, invalid text/errors, whitespace and
unset values. Redo never allocates replacement executable IDs.

The agreed limits are **100 actions across both directions combined** and
**32 MiB of additional accounted history data**. Old-step eviction is visible.
A single oversized action requires confirmation before its complete contents
are applied and history is cleared. This is not a total-browser-heap limit.

Replay uses current eligibility and structural constraints, with fresh
confirmation for block removal/reference impact. It preserves the original
CAS revision and never silently repairs selectors. Ordinary failed saves
retain local history; successful Save still closes the editor. Discard,
reload, workflow/scope changes and confirmed access loss reset history.
Confirmed access loss cannot be reversed by Undo.

Text controls keep native undo. Shared toolbar controls and scoped keyboard
shortcuts support both surfaces, including repeated replay when a direction
becomes empty. Presentation state and saved/run viewers are not made editable
history. No runtime, compiler, publication-service, route, dependency, or
deployer change was made; application Python changes only the version.

See [the M5C feature document](WORKFLOW_AUTHORING_UNDO_REDO.md) for accounting,
UX, lifecycle and implementation details, and
[the workflow guide](../../guides/create-a-workflow.md) for user instructions.

### Implementation details worth preserving

| Area | Reuse / important boundary |
| --- | --- |
| `lib\workflowAuthoringHistory.ts` | Immutable shared checkpoints, caller equality, weak accounting caches, exact entry-ID replay; `clear()` must not pin another baseline |
| `components\workflows\WorkflowAuthoringHistory.tsx` | Canonical session, atomic transactions, lifecycle, overflow and replay proposals |
| `components\workflows\WorkflowFieldDrafts.tsx` | `capture()` / `restore()` and copy-on-write Maps; `getSnapshot()` is still only a React subscription revision |
| `lib\workflowAuthoring.ts` | Shared command/candidate eligibility and reference-impact analysis; do not add a competing grammar |
| `components\workflows\useWorkflowAuthoring.ts` | Latest-draft command dispatch, canonical selection and focus recovery |
| `components\workflows\WorkflowEditorDialog.tsx` | Shared controls, original saved baseline, Save, discard, confirmations and access loss |

Paths in this table are relative to `application\v2_ui\src\`.

Native capture and React bubble listeners can have a microtask checkpoint
between them. The stopped-propagation fallback therefore uses a task, not a
microtask. Replacing it with a microtask splits schema-builder/row-removal
actions into partial history entries. Tests reproduce that boundary.

Keep field Maps immutable and compare their contents explicitly; the generic
plain-object equality helper is not a Map comparator. Do not JSON-clone
history: it loses values such as the unset Repeat maximum's `NaN`. Keep
Repeat-row allocation monotonic even when row mappings are restored.

## 3. What to do immediately

1. Review this PR and its current remote CI results. Resolve genuine
   M5C findings without folding unrelated backlog into the change.
2. Obtain merge authorization, then verify the actual merge/squash result on
   `origin/paullizer-react-v2-ui`. Do not cherry-pick an implementation again
   just because its original SHA is absent after a squash.
3. Handle O4/O5 as bounded test-hygiene work, and choose the O6/O7 documentation
   closeout deliberately. They are not evidence that M4/M5 functionality is
   missing.
4. Scope the next feature before coding. The recommended feature direction is
   **O9: personal/group Workflow Monitoring**, not more M5C authoring work.
   The confirmed SimpleChat action parity gap in #1347 is another separately
   prioritizable slice.
5. Plan O8 separately before claiming operational readiness. Local fixtures
   do not authorize a deployment, model invocation or publication.

### Recommended next feature: a bounded Workflow Monitoring slice

This is a proposal, not an approved M6 specification. Start with a design for
read-only personal/group monitoring and deep links to existing run inspection.
Separate any operational actions into explicitly authorized follow-up scope.

The plan must settle the personal-user, group and Control Center entry points;
reader/manager/admin visibility; current scope/role checks; bounded queries,
pagination, filters and retention; stale/unavailable states; and refresh
behavior. Reuse authoritative run/execution/decision records rather than
creating another execution ledger or treating telemetry as authorization.

Useful initial information includes run status, waits, failures, approvals,
publication completion state and bounded Repeat progress/counts. Do not expose
private state values, records, prompts, credentials or result locators merely
to populate a dashboard. Define which existing detail links the current actor
may follow.

Acceptance should cover personal/group isolation, revocation, active runs,
stable paging, accurate counts across retries/replayed acknowledgements,
mobile/keyboard use, and explicit failure states. A read-only screen must not
issue Run, Cancel, Retry, Resume, Continue Repeat, Approve or Publish calls.

**Do not confuse O9 with #949.** Monitoring existing executions and designing
a generic event/connector **Monitor trigger** are different features.

## 4. Carried-forward action register

The existing O-identifiers remain stable. None is automatically authorized by
M5C, and none should be silently dropped when starting the next conversation.

| ID | Still open | Next concrete boundary |
| --- | --- | --- |
| O1 | Additional saved-source export formats | Pick one source/profile/format mapping, including complete values, empty/partial inputs, provenance, authorization, digest and quota behavior. Reuse the shared exporter; do not build another publication service. |
| O2 | Orchestration knowledge/reasoning/output producers | Define a real authorized producer adapter with typed output, durable identities and inspection. Model prose is not an engine result or permission to invent execution IDs. |
| O3 | Deterministic aggregates | Choose a complete-input use case and define ordering, empty/partial/missing semantics and allowed operations before implementing reducers. |
| O4 | Office-export test harness/import debt | Isolate production imports before mocks; identify actual failures in an offline environment. Concrete import-coupled selectors are listed below. Do not install production credentials or change unrelated dependency pins. |
| O5 | Revoked-record refresh assertion | Reconcile the named test with removal of the revoked panel while still proving protected records disappear. Never retain restricted data to satisfy the old locator. |
| O6 | Earlier release-note backfill and Latest Feature/media decisions | Decide coverage for `0.261.116`-`0.261.122`. The new `0.261.123` M5C note does not backfill earlier slices. Cards, screenshots and videos remain separate decisions. |
| O7 | Published-guide links to excluded engineering notes | Audit existing links and move needed user content into published pages or use intentional source links. This handover is not a site-wide link repair. |
| O8 | Authorized non-production acceptance and rollout | Define environment, identities/roles, scopes, data, destinations, paid/runtime/publication permissions, budgets, cleanup and measurable success criteria first. |
| O9 | Personal/group Control Center Workflow Monitoring | Produce the separately approved scope/permission/query design described above; reuse durable facts and existing inspection. |

### O4 and O5: make the existing test debt actionable

The three import-coupled Office selectors identified in
`functional_tests\test_simplechat_generated_office_exports.py` are:

- `test_word_and_powerpoint_upload_helpers_queue_supported_files`
- `test_simplechat_plugin_exports_default_to_current_group_scope`
- `test_simplechat_capability_fallbacks_and_labels`

They import production operation/plugin modules before applying their
operation-level patches. Repair import isolation before rerunning them against
an environment that could have real Azure configuration. The file also has a
separate static frontend-capability contract; do not conflate it with those
three selectors. Missing Office dependencies currently use a printed skip and
return in the rendering test; make skip reporting truthful as part of that
harness work.

These are source-identified follow-ups, **not a new claim that the three
historical failures were reproduced or fixed by M5C**.

O5 is exactly
`ui_tests\test_v2_workflow_loops.py::test_revoked_record_refresh_clears_the_previous_page`.
It expects an alert inside the old Complete record inspection panel after a
403. Align that expectation with removed-panel UX while retaining its
assertion that Complete saved records are gone. M5C deliberately excluded this
one selector; its own access-loss cases and the affected inspection cases
passed.

### Separate cumulative run-token/spend cap

This remains deferred, outside O1-O9 and outside M5C. History's memory limit,
local invocation metering, admission limits and elapsed deadlines are **not**
a cumulative run-token/spend cap.

Define authoritative units/scope and pricing provenance, reservation and
reconciliation, retries and continuations, native Analyze/multi-call reports,
idempotency/concurrency, late or missing usage, and pause/fail/recovery policy.
Unavailable usage must not silently become zero, and continuation must not
reset lifetime consumption. Obtain a separate design decision before coding
or advertising enforcement.

## 5. Additional backlog outside the milestone register

Repository documentation, current source and open GitHub issues were checked
on **2026-09-20**. This covers the workflow programme and known adjacent
requests, not an exhaustive repository-wide audit. An open issue is a triage
record, not proof that all of its reported behavior is still missing.

| Work | Evidence / status | Follow-up |
| --- | --- | --- |
| SimpleChat action task-model parity | [#1347](https://github.com/microsoft/simplechat/issues/1347); current `create_personal_workflow_for_current_user` still constructs `task_prompt` without a `tasks` payload | Align agent-created workflows with the current task model, preserve legacy calls, decide exposed settings and group scope, and reconcile/group capability definitions. Confirmed source-level gap, not fixed here. |
| Alert cooldowns and digests | `WORKFLOW_ALERT_RULES.md` explicitly documents no cooldown and one notification per matching run | Design per-rule suppression/digest scope, timing, persistence, idempotency and delivery before promising reduced notification noise. Not part of O9 by default. |
| Delegated Microsoft 365 workflow execution | [#1493](https://github.com/microsoft/simplechat/issues/1493), open design-first P1 work | Coordinate Run as consent, secure connection storage, source sharing approvals, reauthentication and exact durable resume with that larger action/working-memory workstream. Never infer app-only or owner-token fallback. |
| Generic monitor triggers | [#949](https://github.com/microsoft/simplechat/issues/949) | Design event/connector triggers, scope, permissions and scale separately from the O9 execution dashboard. |
| Many-to-many comparisons | [#967](https://github.com/microsoft/simplechat/issues/967) | Define input selection, batch bounds, artifacts, resumability and output schema. Existing For each is not an automatic implementation of this request. |
| Template population | [#1045](https://github.com/microsoft/simplechat/issues/1045) | Scope authorized, schema-bound filling of user-supplied DOCX/AcroForm templates; template preservation is different from O1 generic export formatting. |
| Max-document numeric-input UX | [#1370](https://github.com/microsoft/simplechat/issues/1370) | Reproduce against current Classic/V2 settings before fixing; entering `11` must not become `21` through premature minimum clamping. Not freshly reproduced here. |
| Default model/connection parity | [#1427](https://github.com/microsoft/simplechat/issues/1427) | Recheck reported classic-only consumers against the newer shared-connections implementation. Separate remaining runtime gaps from issue/documentation closeout before declaring V1 retirement safe. |
| Recent-document window units | [#940](https://github.com/microsoft/simplechat/issues/940) | Verify minutes/hours/days across current forms, saved values and retrieval; triage current behavior rather than assuming the old report is still exact. |
| Foundry workflow sunset | [#1008](https://github.com/microsoft/simplechat/issues/1008) | Decide deprecation messaging and any replacement research without breaking existing users; do not expand hosted loop support incidentally. |
| Generic no-document workflow issue closeout | [#1082](https://github.com/microsoft/simplechat/issues/1082) remains open, but `GENERIC_WORKFLOW_AUTOMATION.md` records implementation in `0.250.063` and enhancements | Reconcile acceptance criteria with implementation/evidence and update/close the issue only when authorized. Do not rebuild the feature simply because the issue is open. |
| Broader approval/governance requests | [#116](https://github.com/microsoft/simplechat/issues/116), [#1089](https://github.com/microsoft/simplechat/issues/1089), [#375](https://github.com/microsoft/simplechat/issues/375) | These concern MCP-server approval/governance, manager feedback/safety review and sensitive-content administration respectively. Triage separately; “workflow” in their titles does not make them unfinished M4/M5 engine slices. |

No existing issue was updated or closed by this handover.

### Intentional limits, not silently promised future milestones

Persistent/collaborative authoring history, v1/v2 Undo/Redo, layout history,
drag-to-connect editing and saved/runtime rollback remain outside M5C.
Parallel loops, general cycles and hosted-agent loop/report execution remain
unsupported. Choose and design a future slice before turning any of these
boundaries into a commitment.

The Vite large-bundle advisory remains. Measure actual load/render/heap
behavior before claiming performance improvements; deterministic history
accounting is not browser-memory profiling. The local browser evidence is
Chromium-based, not live Azure acceptance, a full assistive-technology audit
or real OS-IME qualification on every platform.

## 6. Runtime and authorization contracts to preserve

- Keep default definition v2, explicit v3 opt-in, durable journal schema 2,
  `workflow-result-v2` and private `workflow-repeat-state-v1`.
- For each is serial: default **500 actual inputs**, administrator range
  **1-5,000**. Frozen selection is not a transactional workspace snapshot;
  All matches is not ranked Best N, and overflow is not silent truncation.
- Repeat is serial and post-body, with explicit finite batches; administrator
  default **25**, range **1-1,000**. Exhaustion pauses and authorized same-sized
  continuation resets only batch usage, not lifetime identity or budgets.
- Preserve **5,000 admissions**, **86,400 seconds including waits**,
  **256 structural IDs**, depth **four**, and **three mixed loop frames**.
- Preserve full For-each `{loop_id, item_id, index}` and Repeat
  `{loop_id, iteration}` paths with zero-based lifetime identity; attempts are
  separate and exact root lookup uses `[]`. Keep typed state and exact lineage.
- Recheck current workflow/group/source/result/artifact/destination access.
  IDs, cursors, receipts, cached projections and monitoring logs grant no access.
- Keep complete saved data and `exact_records_v1` values/order/multiplicity,
  complete-byte digests and atomic quota failure. No prefix artifact or
  arbitrary model prose may become a completed engine result.
- Reuse the publication service and sole destination ledger. Submitted,
  Approved and Indexed-and-ready remain distinct; readiness uses two fresh
  reads. Download is not completion and saved records are not native Analyze.
- Keep paged run inspection and one body template per loop. Do not drain
  histories, infer execution success or replace frozen-run definitions with
  today's saved definition to draw a dashboard.

## 7. Completed validation and reproducibility

These are final scoped M5C results, not a full-repository, remote-CI or live
acceptance claim. Earlier development/stale-bundle runs are not included.

| Selection | Final result |
| --- | --- |
| History/session/field store, shared commands, Flow semantics and inspection-client Node contracts | **144 passed** |
| History replay/compiler, authoring and selected existing schema/digest Python contracts | **71 passed**, 209 deselected |
| M5C real-bundle browser suite | **26 passed** |
| M5B authoring, M5A inspection, editor and structured-control browser suites | **100 passed** |
| Saved publication, completion, Repeat and loop browser suites | **296 passed**, only the named O5 selector deselected |
| Local Flow assets / notices | **4 passed**, 25 subtests |
| Local-asset standalone checks | **4/4** |
| Documentation inventory / coverage and site quality | **7/7** and **6/6**; regenerated inventory had no semantic delta |
| Other checks | Typecheck/build, applicable JS/Python syntax, changed-file XSS/BAC guardrails and whitespace passed |

The three browser selections contain **422 passed cases**. The supported-file
XSS scanner does not classify TSX; do not report that as a TSX security audit.
No live workflow, model call, publication, environment change or paid-service
acceptance was performed.

Final local artifacts, not committed:

```text
index-yqlFW6ez.js
SHA256 DA434C2BE3DB4C891B66CE2CDD386D351DF3306AA1564648071E4D201DE2A362
index-M2uzKwH3.css
SHA256 51EF42FB947EA9B15DFC8F0C98853E27983EFFF8686D1524762A54CC4CCB53B2
```

Reports are under `ui_tests\artifacts\m5c-history-final\results.xml`,
`m5c-authoring-final\results.xml` and
`m5c-runtime-boundaries-final\results.xml`. Generated bundles, dependencies and
reports remain ignored. Rebuild in a fresh checkout; do not assume they exist.
The verified local runtime used Node **24.11.0** and Python **3.12.10**.

From the correct worktree, reuse:

```powershell
npm --prefix .\application\v2_ui run typecheck
npm --prefix .\application\v2_ui run build
node --test .\functional_tests\test_workflow_authoring_history.js .\functional_tests\test_workflow_authoring_session.js .\functional_tests\test_workflow_field_drafts.js .\functional_tests\test_workflow_flow_authoring_commands.js .\functional_tests\test_workflow_flow_semantics.js .\functional_tests\test_workflow_execution_inspection_client.js
python -m pytest -q .\functional_tests\test_workflow_authoring_history.py .\functional_tests\test_workflow_flow_authoring.py .\functional_tests\test_workflow_loop_schema.py -k "authoring_history or flow_authoring or test_old_empty_path_revisions_and_execution_digests_are_unchanged or test_explicit_input_processing_roundtrips_without_adding_other_task_defaults"
$env:PLAYWRIGHT_SERVICE_URL = ''
$env:PYTHONIOENCODING = 'utf-8'
python -m pytest -q .\ui_tests\test_v2_workflow_authoring_history.py .\ui_tests\test_v2_workflow_flow_authoring.py .\ui_tests\test_v2_workflow_flow_inspection.py .\ui_tests\test_v2_workflow_editor.py .\ui_tests\test_v2_workflow_control_flow.py
python -m pytest -q .\ui_tests\test_v2_workflow_saved_output_publication.py .\ui_tests\test_v2_workflow_publication_completion.py .\ui_tests\test_v2_workflow_repeat_until.py .\ui_tests\test_v2_workflow_loops.py -k "not test_revoked_record_refresh_clears_the_previous_page"
python .\functional_tests\test_docs_app_surface_coverage.py
python .\functional_tests\test_docs_site_quality.py
git --no-pager diff --check
```

Restore manifest-pinned dependencies only when needed by the chosen validation
command; do not repair unrelated global environments. Build before browser
tests and keep application source frozen during a run: the fixtures reject a
bundle older than source. Do not disguise that check by treating stale-bundle
failures as functional failures or passes.

## 8. Kickoff for the next conversation

```text
Continue SimpleChat workflow work from
docs\explanation\features\WORKFLOW_M5C_COMPLETION_AND_NEXT_STEPS.md.

M4A through M4C-3, M5A and M5B are implemented and merged. M5C is implemented
in 0.261.123 on paullizer-workflow-m5c. Refresh its actual PR/merge/CI status
and origin/paullizer-react-v2-ui before choosing the starting point.
Use the V2 integration branch, not default Development or the main checkout.
Do not rebuild completed authoring or undo/redo, or cherry-pick a squashed
implementation again.

First summarize delivery gates and the carried O1-O9, spend-cap and additional
workflow backlog. Distinguish confirmed gaps from open issues needing
reproduction or closeout. No M5D/M6 name or detailed next-feature plan is
approved merely by this handover.

The recommended feature direction is O9 Workflow Monitoring, initially a
bounded read-only personal/group scope with authorized deep links to existing
inspection. Propose its permission/query/retention/UX/validation contract
before implementation. Keep #949 monitor triggers, #1493 delegated Microsoft
365 work, #1347 action parity, O4/O5 test hygiene and O6/O7 documentation
closeout separately scoped rather than silently bundling them.

Preserve canonical identities, original CAS, current authorization, complete
saved data, runtime budgets and existing publication truth. Keep O8/live
operations separately authorized. Do not merge, deploy, alter roles, run
paid services or start multiple backlog workstreams without authorization.
```
