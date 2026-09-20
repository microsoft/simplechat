# Accessible workflow Flow authoring

Implemented in version: **0.261.122**

Application version tracking: `application\single_app\config.py`.

## Purpose and scope

M5B lets authorized personal and group workflow authors edit one supported
definition-version-3 draft through **List authoring** or **Flow authoring**.
List is the default. Flow helps authors place work inside the right branch or
loop and inspect its typed dependencies without maintaining a separate graph.
Both surfaces use the same configuration forms and explicit editing commands.

The saved-definition and frozen-run Flow viewers introduced by M5A in
**0.261.121** remain read-only. The authoring switch replaces only the editable
dialog's former **Show Flow preview** entry. It does not turn **View Flow for
...** or **Show Flow for this run** into editors.

The normalized definition and Python compiler remain the executable authority.
There is no second persisted graph, graph-to-definition serializer, validation
language, scheduler, runtime, or result store.

## Dependencies and compatibility

Structured authoring requires V2, durable execution, the existing workflow
feature gates, and management access to the owning personal or group scope.
There is no new capability setting or role policy. Version 3 remains an
explicit conversion; opening Flow never converts a version-1/version-2
workflow, replaces unsupported fields, or invents missing IDs.

The renderer reuses the locally bundled, pinned `@xyflow/react` **12.11.6**,
SimpleChat's layout, and the existing V2 components. M5B adds no dependency,
remote script, worker, companion download, or CSP relaxation. Production
assets and the existing license notices remain under `/static/v2/`.

An incomplete supported draft is editable. An unknown executable shape is
not: it retains its original definition and read-only warning rather than
silently losing data or being converted into an approximation.

## Architecture and state ownership

`WorkflowEditorDialog` owns the canonical definition, original saved revision,
dirty comparison, and Save operation. List and Flow resolve edits against that
same current draft. The `tasks` array remains a task catalogue; executable
order and containment come from `flow`, not catalogue order or box position.
Task-node and task-catalogue IDs need not be identical.

Three kinds of state remain separate:

1. **Authored definition and saved baseline.** Semantic commands update the
   draft; the original `definition_revision` protects the existing save.
2. **Unfinished field buffers and diagnostics.** Raw schema text and its parse
   error, unfinished decision/enum fields, and query-tag text belong to their
   canonical owner and field. Switching surface or selection preserves them.
3. **Presentation state.** Selection, focus, collapse, viewport, and temporary
   positions do not enter the saved definition or browser storage.

Only the first category is eligible for the existing save payload. Unfinished
buffers still participate in unsaved-change protection and validation: changing
selection cannot discard a schema error and save the last valid value instead.
The two surfaces do not mount independently owned copies of editable fields.

### Shared commands and reference safety

Add, configure, move, remove, and typed-binding edits use shared commands over
canonical IDs. Add and move specify a region and a position before or after a
sibling, or at its end. Only creation allocates new executable IDs; movement
preserves every ID in the subtree.

Invalid structural operations leave the draft unchanged. These include stale
targets or anchors, moving a block into itself or its descendants, duplicate
IDs, removing the last required task, unsupported kinds, and exceeded bounds.
Root regions, branch/body regions, and If joins select their owning structure
for configuration; they cannot be independently moved or removed.

Before a reference-breaking move or removal, confirmation identifies the
concrete consumers and selectors affected. Cancelling changes nothing.
Escape cancels the active impact confirmation and returns focus to its block
without closing the workflow editor or opening a discard prompt.
Confirmation does not authorize cascading deletion or retargeting: outside
references retain their exact selectors, even when dangling or out of scope.
The author must repair those errors before saving. A removed block's contained
task configurations are removed with it, not left as executable orphans.
Renaming a binding likewise does not rewrite its consumers silently.

### Current draft boxes and compiler-checked paths

Flow derives current boxes, canonical identities, labels, containment, and
display order directly from the supported draft. Newly added tasks and controls
appear before they are complete. **Unvalidated draft** identifies this state;
boxes are not a successful compiler result or an execution plan.

Executable control arrows appear only after the server compiler accepts the
exact current draft generation in the same editor session and scope. A changed
or rejected candidate cannot keep the previous successful arrows beneath new
labels. Typed bindings describe authored relationships, not additional
execution paths. Unresolved selectors remain visible with their errors;
missing producers are not fabricated as valid-looking nodes or connections.

The active Flow surface uses the existing debounced compiler preview for
eligible candidates. Superseded requests are cancelled, and late responses
cannot attach another draft's topology to the current editor. Preview is
presentation data: it cannot replace or normalize the draft, clear unfinished
buffers, advance the saved revision, mark the draft saved, or invoke work.
Compiler success is not proof of current save or run-admission eligibility.

Preview requests include all server-defined authored revision fields and source
identity, but exclude opaque saved-envelope and runtime metadata. Save still
preserves that metadata unchanged. This keeps the authored digest and compiler
meaning identical without weakening the preview endpoint's strict validation
or introducing a stored-definition lookup. Nested executable fields are never
filtered to make an unsupported definition appear valid.

### Existing APIs and implementation files

M5B introduces no authoring endpoint or persisted schema.

| Existing API | Use |
| --- | --- |
| `POST /api/{user\|group}/workflows` | Explicit Save through the existing definition API |
| `POST /api/{user\|group}/workflows/flow-preview` | Data-only compiler preview; no save or execution |
| `GET /api/{user\|group}/workflows/<workflow_id>/flow` | Separate read-only saved-definition inspection |
| `GET /api/{user\|group}/workflows/<workflow_id>/runs/<run_id>/flow` | Separate read-only frozen-run inspection |

Group requests retain explicit `group_id` and server-authorized management or
reader access as appropriate. A preview's `DRAFT:` digest is not the saved
compare-and-swap revision.

Frontend paths below are relative to `application\v2_ui\src\`.

| Files | Responsibility |
| --- | --- |
| `components\workflows\WorkflowEditorDialog.tsx`, `lib\workflowEditor.ts` | Shared draft, authored preview serialization, dirty/discard protection, and existing scoped Save |
| `components\workflows\WorkflowFieldDrafts.tsx`, `useWorkflowAuthoring.ts` | Session-only field buffers, reference confirmations, canonical selection/focus, and temporary layout state |
| `lib\workflowAuthoring.ts`, `lib\workflowFlow.ts` | Shared commands, structural guards, reference impact, and existing typed-flow analysis |
| `components\workflows\WorkflowStructuredList.tsx`, `WorkflowFlowAuthoring.tsx` | List and Flow editing surfaces over the same draft |
| `components\workflows\WorkflowTaskFields.tsx`, `WorkflowStructuredFields.tsx`, `WorkflowConditionEditor.tsx`, `WorkflowLoopFields.tsx`, `WorkflowRepeatFields.tsx` | Reused task, condition, loop, join, output, and typed-binding forms |
| `components\workflows\WorkflowFlowCanvas.tsx`, `lib\workflowFlowLayout.ts` | Presentation-only geometry and accessible diagram controls |
| `components\workflows\WorkflowFlowView.tsx`, `WorkflowFlowDialog.tsx`, `lib\workflowInspection.ts` | Separate source-bound read-only inspection and strict compiler-projection parsing |

On the server, `application\single_app\functions_workflow_definitions.py`
retains revision and active-run checks. `functions_workflow_inspection.py`
uses the real compiler, and `route_backend_workflows.py` retains the existing
scoped routes and authorization.

## Authoring workflow

The published [Create a workflow guide](https://microsoft.github.io/simplechat/guides/create-a-workflow/)
provides the user procedure alongside structured-flow, loop, and publication
examples.

1. Open personal Workflows or the owning group's Workflows and create or edit
   a workflow. If needed, explicitly enable structured control flow and
   confirm conversion. Conversion alone does not save the workflow.
2. Start in **List authoring**, or choose **Flow authoring** in the editor.
   Workflow basics, runner, schedule, shared references, limits, Save, and
   Cancel remain common to both.
3. Select a block and configure it through the shared fields. Use Add with an
   explicit destination and position to put new work inside the intended
   branch or loop, rather than drawing a connector.
4. To change execution order or containment, use the move controls and choose
   a region and position. Dragging a box or using view-only movement does not
   reorder or reparent executable work.
5. Review affected selectors before confirming a reference-breaking move or
   removal. Repair retained references and unfinished required fields. Keep
   the draft open while doing this; an incomplete supported block stays
   selectable and editable.
6. Use **Save workflow** when the draft is ready. Review any validation or
   conflict response before retrying; a visible diagram is not a saved change.

### Supported configuration

| Target | Shared List and Flow configuration |
| --- | --- |
| Task | Instructions, runner, references, typed inputs, output contract/schema, approval, Run when, existing document actions/native Analyze, saved-record reporting, and publication configuration |
| If/else | Typed condition inputs, condition, Then/Else regions, and explicit join exports |
| Forward route | Typed condition and existing later-sibling or branch-exit target controls |
| For each | Existing source/query/input selection, item ceiling, body, and body outputs |
| Repeat until | Explicit maximum, typed initial/next state, body outputs, post-body Until, and final exports |
| Collect | Existing loop/output selector and supported output contract |
| Root and body outputs | Explicit named typed bindings, configured against the owning region |

A new Repeat maximum remains unset until the author chooses it. Choosing a
source or configuring Analyze/publication does not perform that work. Existing
explicit loop-source preview remains a separately requested, authorized,
non-admitting action, never a consequence of selecting a block.

## Accessibility and temporary layout

Every semantic operation has a button/keyboard path; no connection gesture or
drag is required. There is no arbitrary connector creation, reconnection,
drag-to-reorder, or drag-to-reparent mode. View-only movement is distinguished
from moving a block in execution order.

List and Flow share canonical selection. Switching reveals that selection;
configuration-focus and return controls connect the block with its fields.
After adding, focus moves to the new block's first required field. Moving
retains its identity. Removal recovers to the nearest surviving sibling, then
the parent or root, revealing ancestors as needed.

List is the initial surface, including on narrow screens. Flow's configuration
panel stacks on smaller screens. The chosen surface lasts only for the open
editor; it is not a stored preference. Pan, zoom, fit, collapse, and temporary
positions are view state. Page scrolling and browser zoom remain available,
and movement has non-drag alternatives.

## Save, access, and runtime boundaries

Semantic edits and unfinished buffers retain the existing dirty/discard
behavior. Selection, geometry, surface switches, and successful previews do
not themselves dirty or save the workflow. There is no autosave.

Both surfaces use `workflowForSave` and `saveWorkflowDefinition` with the
original saved revision. Validation, ordinary network errors, and stale
revision conflicts retain unsaved edits; a conflict does not automatically
overwrite or rebase the server definition. Reload/discard remains explicit,
and successful Save retains the existing close-on-success behavior.
Editor dismiss controls cannot close an in-flight Save or start a second write.

Read-only, saving, unsupported-shape, and known active-run restrictions apply
to commands as well as controls. The server remains authoritative if access
or active-run state changes during editing. Confirmed scope/access loss
invalidates pending work and clears protected fetched information rather than
continuing from stale authority or mixing scopes.

Authoring and compiler preview cannot Run, Approve, Retry, Resume, Continue
Repeat, Publish, reconcile readiness, freeze sources, or admit an execution.
The [run's frozen Flow](https://microsoft.github.io/simplechat/guides/trigger-a-workflow/#inspect-a-runs-frozen-flow)
continues to inspect the admitted snapshot, never the current authoring draft.
Existing runtime and publication decisions stay outside the editor.

## Testing and limitations

The M5B offline suites passed against the local production bundle and real
compiler helpers. They validate the following without live-environment acceptance:

| Suite | Coverage |
| --- | --- |
| `functional_tests\test_workflow_flow_authoring_commands.js` | Execute shared commands; preserve IDs and payloads; confirm exact reference impacts; reject invalid operations atomically; keep layout out of semantic edits |
| `functional_tests\test_workflow_field_drafts.js` | Retain raw text and errors across form lifetimes, isolate canonical owners, preserve Repeat-row identity, acknowledge saved fields, and keep buffer metadata out of definitions |
| `functional_tests\test_workflow_flow_authoring.py` | Compare authored definitions with real compiler meaning and rejection boundaries |
| `ui_tests\test_v2_workflow_flow_authoring.py` | Exercise the local V2 bundle with fictional scoped APIs: List/Flow round trips, unfinished buffers, exact Save payloads, delayed/error responses, access guards, keyboard/mobile focus, and absence of side-effect requests |

Existing M5A and affected M4 suites retain saved/run read-only inspection,
source authorization, exact identities and result lineage, and publication
boundaries. Local fixtures do not establish Azure performance, deployment
readiness, or production acceptance.

The configured task maximum and hard 100-task catalogue bound remain, along
with 256 structural IDs, depth four, and three mixed loop frames. Flow renders
one body template per loop rather than expanding frozen items or lifetime
rounds. There is no history-page draining for draft authoring.

For each remains serial with the 500-actual-input administrator default and
1-5,000 range. Repeat retains its separate default ceiling of 25, range
1-1,000, explicit authored batch, and authorized same-sized continuation.
Continuation resets only batch usage, not lifetime identity or the original
5,000-admission and 86,400-second bounds, including waits. Typed state, exact
Collect order/lineage, native Analyze identity, accepted-partial limitations,
`exact_records_v1` JSON, and publication completion observations are unchanged.

## Planned M5C: cross-surface undo/redo

M5B visual authoring is implemented in **0.261.122**. Cross-surface undo/redo
was deliberately outside that completed scope and is now named **M5C**.
M5C is a plan, not an implemented feature or an approval to begin coding.
M5B has no structural undo shortcut; text-input undo remains native.
The M5C design must settle the following decisions before implementation:

| Design consideration | Required decision or boundary |
| --- | --- |
| Command granularity | Define atomic structural edits and coalescing for typing, schema changes, and typed bindings; preserve canonical IDs |
| Buffers and parity | Decide how unfinished text and its diagnostics join history so List and Flow restore the same draft, not just its last valid values |
| History size | Define bounded entry/memory retention and what happens when the bound is reached; no history limit is selected here |
| Save, reload, and discard | Define history clearing/rebasing explicitly; undo must never roll back a server save or historical run or advance/replace the saved CAS baseline |
| Conflict handling | Preserve unsaved intent without automatic overwrite/rebase; define history behavior after a rejected save or an explicit reload |
| Scope and permissions | Define invalidation on workflow/scope changes and access loss; history must not restore protected data or bypass current editing permissions |
| Selection and focus | Restore or recover a canonical selection and its configuration focus, including when undo removes the selected block |
| View state | Keep geometry, viewport, and other temporary presentation choices out of executable-edit history |

The detailed M5C plan and completed M5B handoff are in
`WORKFLOW_M5B_COMPLETION_AND_NEXT_STEPS.md`. M5C's detailed scope still needs
approval; no delivery date or runtime rollback capability is promised.

## Other deferred work

M5B does not consume the existing open-item register:

| Item | Still deferred |
| --- | --- |
| O1 | Additional saved-source export formats |
| O2 | Authorized orchestration knowledge/reasoning/output producer capability |
| O3 | Deterministic aggregates with defined complete/partial/empty semantics |
| O4 | Office-export test harness and import-time configuration debt; separately scoped failing selectors |
| O5 | Revoked-record refresh assertion versus removed-panel UX; restricted-data clearing must remain intact |
| O6 | Earlier workflow release-note coverage and Latest Feature/card/media strategy |
| O7 | Existing published-guide links to excluded engineering notes; no backlog-wide link rewrite |
| O8 | Separately authorized non-production live acceptance and rollout |
| O9 | Personal/group Control Center Workflow Monitoring, including scope, roles, queries, and actions still to be designed |

A cumulative run-token/spend cap also remains deferred. Existing local
metering, admission limits, and elapsed deadlines are not that cap.
