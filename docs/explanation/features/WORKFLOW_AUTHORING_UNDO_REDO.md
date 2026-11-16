# Cross-surface workflow authoring undo and redo

Implemented in version: **0.261.123**

Microsoft 365 Run as history integration fixed in version: **0.261.124**.

Application version tracking: `application\single_app\config.py`.

## Purpose and dependencies

M5C adds one session-local history to the definition-version-3 workflow editor.
An author can reverse an unsaved edit in List and restore it in Flow, including
unfinished form text rather than only the last valid executable definition.
It extends [M5B Flow authoring](WORKFLOW_FLOW_AUTHORING.md); saved-definition and
frozen-run viewers remain read-only.

History requires the existing V2 editor, supported structured capabilities,
and management access to the personal or group workflow. There are no new
settings, permissions, endpoints, packages, remote browser assets, or runtime
dependencies. Existing React components and locally bundled assets are reused.

## Using history

Use **Undo** and **Redo** above the shared workflow fields. Each button names
its next retained action. Both surfaces share these controls and the same
draft; switching surfaces does not consume history.

Typing during one visit to a field is one action. Blur, a different field or
owner, a surface switch, another edit, and explicit paste/cut/drop boundaries
end that group. Composition has its own boundary. Discrete choices, schema
builder actions, bindings, and Add/Move/Remove are individual actions, including
all related canonical and buffer changes.

Inside inputs, textareas, and editable text controls, Ctrl/Cmd+Z keeps the
browser's native text undo. Outside those controls, within the editor, use
Ctrl/Cmd+Z for workflow Undo, Ctrl/Cmd+Shift+Z for Redo, or Ctrl+Y on
Windows/Linux. Toolbar focus remains usable when one direction becomes empty.
Workflow replay is not available during composition, Save, or another
confirmation.

Replay that removes blocks or changes outside-reference availability asks for
fresh confirmation. Cancelling keeps the current definition, buffers, and
history. Confirming preserves exact selectors: it does not repair dangling
references or silently choose another producer. Resolve resulting validation
errors before saving.

### What an action restores

| Area | Retained state |
| --- | --- |
| Common fields | Name, description, runner/model/agent, Microsoft 365 Run as, schedule, enabled/chat choices, reliability, shared references, and run limits |
| Tasks and controls | Configuration, bindings, predicates, routes, joins, outputs, For each/Collect, Repeat, Analyze and publication configuration |
| Structural edits | Exact catalogue, node, region and join identities and executable order; Redo does not allocate replacements |
| Unfinished forms | Raw schema text, errors, decision/enum builder inputs, query-tag spacing, accepted baselines, and Repeat-row mappings |

An unset Repeat maximum remains unset. Missing values, explicit `undefined`,
`NaN`, false, zero, null, Unicode, and whitespace are not normalized by replay.
Only ordinary Save serialization produces a transport payload.

Run as history changes only the unsaved account selection. It does not grant
Microsoft 365 consent or restore an approval for a different workflow revision.

Selection recovers to the affected canonical block, or a surviving sibling,
parent, or root. Geometry, collapse, pan/zoom, fetched pages, preview responses,
and other presentation choices are not undoable executable edits.

## Retention limits

History retains at most **100 actions across Undo and Redo combined** and
**32 MiB (33,554,432 bytes) of additional accounted history data**. These are
fixed client limits, not administrator settings.

Ordinary pressure evicts complete oldest steps and displays a visible status
notice. Eviction does not alter the current draft or its original dirty/CAS
baseline. A committed new branch clears Redo; a no-op, rejected edit, cancelled
confirmation, or view change does not.

If a single action cannot fit, **Apply edit and clear history?** offers a
choice. Cancellation retains the prior draft, buffers, selection, and stacks.
Confirmation applies the entire candidate and clears both directions. No text,
schema, subtree, or history step is partially retained or silently truncated.
The temporary proposal can itself be large.

### What the memory number means

The budget is deterministic accounting, **not a total browser-heap guarantee**.
The opening baseline and one live draft are unavoidable editor state.
Accounting takes the unique retained object graph outside that baseline,
subtracts the smallest live-state cost among all reachable checkpoints, and
adds entry/action metadata. Considering every reachable cursor prevents a
large live value from becoming unexpectedly unbudgeted on Undo.

The model charges 64 bytes per container, 8 per array slot, 48 per Map entry,
16 bytes plus two bytes per UTF-16 code unit for strings, and explicit property
and primitive costs. Primitive leaves belong to their containing object;
shared object subgraphs are charged once. Weak caches do not keep evicted,
abandoned-Redo, coalesced, or rejected proposal graphs alive. Clearing history
does not pin a replacement baseline.

Checkpoints use structurally shared immutable objects and copy-on-write Maps,
not a full-definition JSON copy per keystroke. Unsupported non-data objects,
accessors, and cycles are rejected explicitly rather than invoked or silently
discarded.

## Architecture and API boundaries

| File | Responsibility |
| --- | --- |
| `application\v2_ui\src\lib\workflowAuthoringHistory.ts` | Pure bounded entries, grouping, accounting, eviction and exact cursor replay |
| `application\v2_ui\src\components\workflows\WorkflowAuthoringHistory.tsx` | Session ownership, transactions, guarded replay, overflow proposals, lifecycle and keyboard boundary |
| `application\v2_ui\src\components\workflows\WorkflowFieldDrafts.tsx` | Immutable field snapshots, atomic notification, owner pruning and monotonic Repeat-row allocation |
| `application\v2_ui\src\lib\workflowAuthoring.ts` | Shared eligibility, structural ceilings and reference-impact analysis |
| `application\v2_ui\src\components\workflows\WorkflowEditorDialog.tsx` | Shared toolbar, confirmation coordination, Save, dirty state and access-loss handling |
| `application\v2_ui\src\components\workflows\useWorkflowAuthoring.ts` | Current-draft command dispatch and canonical selection/focus recovery |

The session stages canonical and raw changes before publishing one revision.
Native event capture begins compound transactions before form handlers; bubble
completion commits them. A task-queued fallback handles stopped propagation
without committing at the microtask checkpoint between native capture and
React's bubble listener. A schema-builder update or Repeat-row removal
therefore cannot become several partial Undo actions.

Replay overlays only authored fields on the current workflow. Workflow/scope
identity, the original `definition_revision`, runtime metadata, unknown
envelope fields, and editor options are not rewound. Current management,
active-run, supported-shape and structural-limit checks still apply.
Capability changes can reject a replay without consuming it. Pending replay
is bound to its source revision and entry ID; changed capabilities require
another review before confirmation.

Save continues to use `workflowForSave(draft, original, scope)`. Preview uses
the existing compiler-preview path, debounce, abort and candidate fencing.
Neither payload contains history, buffers, selection, or geometry. Raw-only
formatting does not request a semantically identical compiler preview.
The selected Microsoft 365 Run as account is an authored definition field, so
both Save and preview retain it and calculate the same authored digest.

## Save and session lifecycle

Successful Save keeps the existing close-on-success behavior and clears
history. Validation, conflict and ordinary network failures retain local
history and the original CAS token; there is no automatic rebase or overwrite.
Undo to the opening v3 definition and raw-field state becomes clean even if
Redo is available.

Reload, confirmed discard, editor destruction, and workflow/scope changes
start a new session. Explicit v1/v2 conversion begins empty v3 history:
Undo cannot reverse that conversion, and the converted unsaved draft remains
dirty relative to its original ordered definition.

Confirmed authoring-access loss clears retained/proposed states, buffers and
protected authoring controls permanently for that editor instance. Restored
access requires reopening. A disposed editor's late response cannot restore
its history or affect a different workflow.

## Testing and limitations

`functional_tests\test_workflow_authoring_history.js` exercises the actual
100/101-action and exact 32-MiB boundaries, group overflow, whole-step eviction,
shared-graph accounting and garbage collection. Session and field-store tests
cover atomic native events, rejection/error rollback, identity, buffers,
capability changes, Save boundaries and Strict Mode. The companion Python
history tests compile actual replay-produced payloads and compare their
meaning and digests while retaining the original CAS.

`ui_tests\test_v2_workflow_authoring_history.py` uses the real local bundle,
fictional scoped APIs and actual compiler. It covers cross-surface replay,
unfinished fields, compound actions, confirmations, keyboard/mobile behavior,
composition event boundaries, real retention limits, Save failures and access
loss. Existing M5A/M5B, editor, control-flow, loop, Repeat and publication
regressions remain applicable.

Local validation completed with 144 Node contracts, 71 targeted Python
compiler/definition tests, and 422 browser cases across the history and
affected workflow suites. Typecheck, production build, local-asset checks,
documentation coverage/quality and applicable changed-file guardrails passed.
The existing O5 revoked-record-refresh selector was explicitly excluded;
that deferred issue was not fixed by M5C.

This is unsaved authoring history, not rollback of a saved workflow, execution,
approval, Analyze action, or publication. It is neither persistent nor
collaborative history. No Azure/live-environment acceptance is implied.
The O1-O9 register, cumulative run-token/spend cap, and runtime/publication
limitations documented with M5B remain deferred and unchanged.
