# Selected-source orchestration planning fix

Current version: **0.261.357**

Fixed in version: **0.261.355**

## Issue and root cause

An orchestration request could ask for the contents of a selected upload instead
of planning work against it. The conversation resolver received selected IDs
without their authorized filenames or availability. The full planner received
source kinds but not the ordered columns needed for executable native queries
and original-row exports.

The investigated production uploads completed processing before submission.
Both initial requests reached full planning; subsequent clarification answers
stopped in conversation resolution. Exact initial model questions and the
deployed commit were unavailable, so this fix addresses the reproducible
contract gaps without claiming a proven initial model rationale or an upload
race. Harness observations are recorded separately, outside this product fix.

## Technical changes

`functions_orchestration_source_context.py` defines a server-owned selection
projection and typed clarification reasons. The resolver sees identity, kind
and availability; full planning also sees bounded table structure. A source
being available does not imply its contents are already in the prompt.

`functions_orchestration_bootstrap.py` injects an actor-bound reader through
`functions_orchestration_services.py`. Reads use strict current authority and
content-screening boundaries for personal, group and public scopes. Blob size
is checked before download; downloads are range-bounded and ETag-pinned.
Metadata revisions are checked around the read. Private storage locators and
callbacks never enter the model projection.

`functions_tabular_merge.py` reuses its CSV/Excel parsers and archive safeguards
for a planning-only preview. It reads the first header row and at most three
sample rows per visible sheet, not the entire dataset to count rows. Exact
headers are not clipped or invented. Duplicate, blank, non-text or overlong
headers produce an explicit inspection limit rather than fabricated columns.

Planning allows at most 8 MiB per source, 16 MiB downloaded across sources,
eight inspected sources, eight worksheets per workbook, 50 columns and 32 KiB
of projected JSON. Workbook expansion is limited to 32 MiB and 1,000 entries.
A 15-second discovery budget prevents starting additional reads after the
budget expires; it is not a hard timeout on an already-running SDK call.
Samples are removed first if needed to fit the context budget. Selected
identities are never silently dropped.

`route_backend_orchestration.py` prepares explicit selections before the
resolver, without moving broad workspace search ahead of disambiguation.
`functions_orchestration_plan_editing.py` rebuilds the same context for editor
replanning. Continuations preserve the saved request and accepted answers.

`functions_orchestration_planner.py` requires a typed, source-referenced reason
for new selected-source questions. A question claiming available selected
contents are missing receives the existing bounded repair opportunity in both
planning stages. Repeated contradictions fail safely. Genuine worksheet,
source-selection and business-rule questions remain possible. Existing saved
question schemas and source-free callers keep their contracts.

The planner is instructed to export complete native query records in exact
column order, not reconstruct rows through composition. Source revision hashes
are persisted separately from previews and checked by
`functions_orchestration_native_results.py` before native submission and
resumption. A changed document metadata revision requires a fresh plan. This
fence does not replace the execution-time blob-version, access and replay
checks, which remain authoritative.

Diagnostics reuse `ORCHESTRATION_CONTEXT` and `ORCHESTRATION_PLANNER`, with
conversation/turn hashes, stage, counts, typed reason and repair attempt. They
do not log headers, samples, filenames or question text. Application versioning
is updated in `application/single_app/config.py`.

## Validation

`functional_tests/test_orchestration_selected_source_planning.py` exercises real
parsers, initialized HTTP planning, continuation, editor revisions, native
execution and rendering with external storage/model I/O doubled and network
access blocked. Version **0.261.356** explicitly re-exports the three shared
pytest fixtures so static analysis recognizes their use without suppressing
unused-import checks or changing fixture discovery.
The CSV/XLSX input and CSV/XLSX output matrix compares all 37
records in original order, well beyond the three-row preview. It also covers
source-free/narrative requests, inspection limits, hostile sample text,
pre-download size refusal, ETag replacement, scope propagation and revision
rejection before native work.

Additional checks exercise typed malformed responses, genuine source/worksheet
choices, privacy-safe log properties, accepted clarification references and
idempotent resubmission. Native analysis receives all 37 execution rows: its
controlled model computes total **703** and subtotals **171** and **532**, not
the three-row preview's total. The retained results feed the real chart plugin,
whose bar values and accompanying data table are compared with those subtotals.
The model is doubled; this is not evidence of live-model numerical accuracy.

The selected-source suite passed **43 tests** with network access blocked:

```powershell
python -m pytest -q -p no:cacheprovider -p test_support.cosmos_network_guard --tb=short functional_tests\test_orchestration_selected_source_planning.py
```

The final combined selection includes the new suite plus related planning,
conversation, source-kind, reconciliation, native adapter, initialized HTTP,
render, chart-delivery, storage-owner, request-memory and planner/store revision
suites: **468 tests** and **66 subtests** passed.

Route Blueprint inventory, unauthenticated access policy, route-policy coverage,
application-surface documentation coverage and documentation quality checks
passed together: **43 tests**. Cosmos inventory review reports **1,067 owners**,
**412 doubles** and **zero review gaps**.

With the application's pinned Cosmos SDK installed in the isolated validation
environment, the full reviewed storage-contract gate also passed: **1,241 tests**
and **244 subtests**, with socket/DNS access blocked.

```powershell
python scripts\check_cosmos_response_boundaries.py --run-contracts
```

An older reconciliation profile-list assertion was excluded from the focused
combined run after reproducing the same failure against the original source.
Other legacy fixture limitations are recorded in the separate harness-findings
artifact rather than changed or included in this product fix.

Production investigation remains read-only. This does not claim successful
live-model or deployed UI validation; no production uploads, chats, settings
changes or deployment were performed.

See [Create files with orchestration](../../guides/create-files-with-orchestration.md)
for the user workflow.
