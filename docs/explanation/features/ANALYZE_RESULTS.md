# Saved Analyze results

Implemented in version: **0.261.109**, recorded in
`application/single_app/config.py`.

Planning, download, and responsive stabilization updated in version:
**0.261.113**. See [Analyze stabilization](../fixes/ANALYZE_STABILIZATION_FIX.md).

## Overview

Analyze separates accepted findings from window-level candidates, source
evidence, readable presentation, and processing diagnostics. Chat and downstream
workflow tasks use the same saved result. A user does not need to download a
report, upload it, and analyze it again to ask what its findings mean.

Ordinary narrative requests use flexible findings without requiring a schema or
an extra planning call. The application does not invent a scoring system.
Explicit output requirements and supported calculation rules remain separate
from the narrative default.

The user-facing workflow is documented in
[Read and discuss saved Analyze results](../../guides/analyze-results.md).

## Dependencies and implementation

This extends the existing document-analysis runner, workflow result store, source
access resolvers, and chat renderers. It does not add a storage resource or a
second workflow engine.

| Component | Responsibility |
| --- | --- |
| `functions_document_analysis.py` | Read assigned source windows, preserve processing outcomes, and produce the final Analyze result. |
| `functions_document_analysis_results.py` | Candidate identity, evidence binding, deterministic collection, source coverage, and readable report formatting. |
| `functions_workflow_results.py` | Separate final outputs from presentation/diagnostics and identify the exact output consumed by a later task. |
| `functions_workflow_result_store.py` | Immutable JSON sections using the existing Blob/Cosmos infrastructure and real workflow, chat, or orchestration identities. |
| `functions_saved_analysis.py` | Authorized result reading, complete-record pages, saved-result explanations, and source-bound history. |
| `functions_analysis_access.py` | Current access to every contributor, including large selections resolved in bounded source batches. |
| `functions_analysis_deliverables.py` and `functions_tabular_transformations.py` | Public output projection and explicitly declared deterministic calculations. |
| `functions_artifact_publication.py` | Publish existing artifact bytes to an explicit destination, preserving approvals and retry receipts. |

Storage version, result version, and calculation-specification version are
independent. They are internal compatibility boundaries, not settings users
must choose before asking a question.

## Final data and coverage

Window outputs are candidates, not automatically final records. Each accepted
finding retains a stable identity, its public values, contributing source
identity, and evidence references. Duplicate delivery of completed work does not
create another finding. Conflicting values remain unresolved rather than being
silently overwritten by the longest or latest response.

Each batch is accountable for its assigned inputs. Global coverage is computed
from source/work-unit outcomes, not from a model's statement that another batch
was missing. Sources, windows, chunks, and findings are counted separately. A
fully processed source can have zero accepted findings without being missing.

Structural checks, evidence-location checks, calculation checks, and model
judgments are not interchangeable. Reports disclose unsupported or unperformed
checks. Complete source processing does not prove that every possible issue was
found or that a qualitative conclusion is factually correct.

## Presentation and reuse

Both classic chat and React V2 show the readable answer before supporting file
actions. Large result views identify the displayed subset and load additional
complete records. Evidence and limitations belong to the saved result;
processing diagnostics are not appended to its normal Markdown report.

The result reader is
`GET /api/analysis_results`, using the advertised conversation ID, message ID,
and result digest. Record requests use bounded `offset`/`limit` values; evidence
requests identify a saved record. The server derives storage identity from the
authorized message, not from a browser-supplied blob path.

**Ask about this analysis** selects a saved-result context. An explanation
retains its originating result identity and does not claim to have performed
another independent review of the original sources. Model budgets still apply:
no preview or storage reference can silently stand in for required findings.

Markdown, structured exports, and tables use accepted values. Format-only work
does not need another source-analysis call. Changing a report's wording does not
change its saved findings.

## Access and publication

New reads and reuse require current access to every contributing source. If a
source becomes unavailable to the reader, the entire original result and its
derived explanations, evidence, and original exports become unavailable. This
also applies to workflow result readers and mixed-source results. A conversation
permission alone does not override that rule.

Workspace publication is separate from saving a result in its originating chat.
Passing required checks makes a projection eligible; it does not authorize a
publication side effect. A user action or configured workflow publication request
must identify a destination the actor may use. Group/public approval policies
continue to apply.

Publication reuses the artifact bytes rather than a model-generated
reconstruction. A saved receipt identifies the request, source projection, and
destination. A retry reconciles an existing document or pending approval; an
uncertain outcome is not treated as permission to create a second copy.

Already published workspace copies have their own destination permissions and
lifecycle. They do not inherit later access changes to the original sources.
Previously delivered or downloaded bytes cannot be recalled.

Original chat artifacts use their own authorized byte reader rather than the
workspace-document citation reader. Conversation participation, generated-file
approval, publication state, and saved-source access are checked before and
after reading the persisted blob reference. Changed identity, revision, or
recorded content digest prevents delivery. Legacy artifacts without a saved
analysis binding retain their existing authorization contract.

Classic and V2 download controls fetch the attachment before invoking browser
download handling. An error response or sign-in page is not saved as a file and
does not navigate away from chat. Original artifact responses are not cached for
reuse after an authorization change.

## Validation and limitations

Functional coverage includes source fixtures at 1, 10, 100, 300, and 500 inputs,
candidate conflicts and replay, exact result reload, declared calculation
precision, complete-record paging, source revocation, and publication
authorization/retry behavior. Scale fixtures use supported configured limits;
they do not raise default limits for users.

The local browser harness exercises both chat interfaces and the classic
workflow publication controls, including keyboard/mobile behavior and
unavailable results. Principal regression files include
`test_document_analysis_final_results.py`, `test_saved_analysis_store_integration.py`,
`test_saved_analysis_record_pages.py`, `test_analysis_calculations.py`,
`test_analysis_artifact_publication.py`, and `ui_tests/test_chat_saved_analysis.py`.

Stage durations and observable model-call counts distinguish source analysis
from collection, reporting, and exports. Provider-managed internal calls may be
unobservable; they are not reported as zero. Deterministic fixtures are not a
claim of a particular deployment's end-to-end latency.

Narrative work units use the shared result store for completed-window reuse.
Chat retries bind to the prior server-recorded assistant attempt; a workflow
task reuses its prepared checkpoint object across its configured retries.
Stop and deletion fence further checkpoint writes, while deletion retains
private tombstones so a late worker cannot recreate those payloads.

Live source execution defaults to serial processing. Isolated concurrency is
bounded when an invocation owner explicitly supplies that support; this change
does not introduce an admin concurrency setting. The existing content getter
still materializes the largest individual source.

Pending native outputs are not substituted with previews. Native completion
can be read through its existing validated output checkpoints, but automatic
continuation of mixed deferred composition is not added here. Saved-only
explanations reject hosted agents that cannot enforce read-only execution.
An individual record or required supporting set that exceeds the selected
model's budget fails explicitly rather than being clipped.

An authenticated live deployment was not configured during local development.
Deployment-specific integration remains a separate validation gate.
