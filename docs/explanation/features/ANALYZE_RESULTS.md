# Saved Analyze results

**Version: 0.261.127**

Implemented in version: **0.261.109**, recorded in
`application/single_app/config.py`.

Planning, download, and responsive stabilization updated in version:
**0.261.115**. See [Analyze stabilization](../fixes/ANALYZE_STABILIZATION_FIX.md).

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

The [orchestration result foundation](ORCHESTRATION_RENDERING_HARNESS.md),
implemented in **0.261.125** (Refs #1509), can wrap an already authorized bounded
`SavedAnalysisInput` in `SavedAnalysisRecordSource`. Its ordered public-values
projection retains complete records, evidence, coverage, and source snapshots
through the original reader. Generic text, comparisons, and structured values
have separate versioned kinds; they do not weaken `analyze-final-v1` validation.
This internal compatibility API does not change standalone Analyze or workflows.

## Internal orchestration producers

The M2 producer boundary in **0.261.127** (Refs #1509) is selected by the
server-owned `RunContext.plan_contract_version == 2`, not by tool arguments.
The Analyze adapter calls the real `analyze-final-v1` engine and work-unit checkpoints, saves the
native result, then reads its complete authorized `SavedAnalysisInput` into the
orchestration result facade. No Markdown download, generated-artifact message,
or workspace copy is created by this path.

The adapter requires the owning attempt's `analysis_checkpoint_factory`,
`result_service`, `result_producer(step)`, and
`result_guard_token_for_step(step_id)`, together with the runtime's exact
`result_input_fingerprint_for_step(step_id)`. The result token must match the
actual Analyze checkpoint token. Missing runtime wiring, an invalid input digest,
or a stale guard fails before source analysis; the adapter never invents a token,
fingerprint or workflow identity.

`get_adapter(name, contract_version=2)` lazily resolves `compose` and excludes
legacy `respond`. The default `get_adapter(name)` and `name=` keyword calls keep
the existing version-1 registry unchanged. The runtime owns selecting the plan
contract; model arguments cannot select this dispatch policy.

For v2 tabular steps, the adapter delegates only to the existing
`NativeOrchestrationBridge` returned by the private server callback
`context.native_bridge_for_step(step, context)`. Missing or invalid binding fails
before legacy planning or publication. The bridge owns strict single-source
admission, native execution and full named-result retention; its typed pending
result and opaque wait handle are returned unchanged. Runtime continuation uses
that bridge's `resume`, not another adapter execution. Version-1 tabular behavior
is unchanged.

`StepResult.task_result` carries a frozen `TaskResult`, not retained data or a
storage locator. Its outputs are:

| Name | Kind | Contents |
| --- | --- | --- |
| `findings` | `records-v1` | Every native reader unit, with the ordered columns `record` (object) and `evidence` (array). Record identities, public values, evidence links, and supporting passages remain intact. |
| `records` | `records-v1`, optional | Exact public values through `SavedAnalysisRecordSource`, only when a complete result has one consistent field set across every record. Columns are explicitly ordered JSON-valued fields; values are not flattened or coerced. |
| `report` | `markdown-v1`, optional | The complete saved text section when the native formatter reports it ready. A presentation summary or report-formatting failure paragraph is not substituted. |
| `coverage` | `structured-v1` | Native coverage, validation checks and limitations, normalized source snapshots, and availability of the report/public-record projection. |

Flexible findings may have different public fields. Such results retain every
original `record.values` object in `findings` rather than padding absent fields
with invented nulls. Empty findings remain a legitimate complete collection
when the native coverage proves that all assigned work finished. Accepted
partial findings retain partial completeness on every output; an explicit
partial read does not make a downstream result complete.

`SavedAnalysisInput.read_report_text()` reads the complete `text` section and
checks its producer, contract, output name, and current source access. It never
reads `presentation.summary`. The generic readers recheck source revisions,
access and screening after restart as well as during consumption.

The pure `functions_orchestration_execution_policy.py` module provides
`orchestration_file_policy(allow_generated_files=False)` for Gather/Reason.
SimpleChat-managed workspace uploads, Word/PowerPoint upload helpers, generated
chat byte/stream uploads (including workbooks), queued generated-document
processing, chat image writes, and staged artifact publication commits reject
creation in that scope. Captured agent execution frames preserve the restriction
when re-entered in delegated tasks or worker threads. An inner scope cannot
grant publication against an outer denial.

The direct publication guards, implemented in **0.261.127** and recorded in
`application/single_app/config.py`, also reject workspace publication, approval
or denial decisions, automatic approval expiry, and write-side reconciliation
before destination, receipt, notification or processing effects. Read-only
receipt/status/authorization checks remain available in a denied scope and do
not repair acknowledgements or mutate approval state.

The producer helpers accept an optional server-computed `input_fingerprint`.
The v2 Analyze/Compare adapters require the owning runtime's declaration-scoped
digest and pass it unchanged to the result facade for authenticated
committed-result recovery, including a lost acknowledgement after commit.
The owning getter is resolved once before checkpoint preparation or result
writes. Missing, malformed, unbound or wrong-step fingerprints do not prepare
or cancel analysis checkpoints, and later context changes do not replace the
captured digest.
Only complete or partial accepted results receive that completion receipt;
failed comparison diagnostics remain persisted but are not recoverable as an
accepted result. This is not a model argument or a substitute for the owning
write guard.

Outside that scope, the default standalone Markdown/download behavior and normal
workflow operations are unchanged. Private saved results and checkpoints are
still permitted. External action destinations and their broader side-effect
governance are not redesigned by this policy. This boundary does not enable a
new planner contract by itself; runtime admission, optional-output binding,
native compute-only handoff, and explicit rendering remain separately owned
integration work.

Cross-attempt native resume also requires the generic result preparation to
preserve the owning checkpoint's existing `resume_from` binding. Re-preparing
that same token as a fresh attempt is rejected by the shared lifecycle store;
the adapter does not bypass this fence or substitute another token.

### Private external configuration capture

Before engine setup or acquisition capture, all five v2 external adapters call
`context.external_source_preflight(producer=producer, selector=selector)`.
The producer is the owning server step; the selector is the original scoped
agent catalog key or action reference, and is `None` for web, URL and research.
This fourth private runtime binding uses
`provider.preflight_gather_invocation` to check fresh account/app-role authority,
the current enabled saved step/capability, scoped integration access and
user-authored URL provenance. Cached context roles or an old catalog cannot
override that decision. Only a synchronous return of exactly `None` permits
execution; missing hooks, asynchronous hooks and returned authorization payloads
are refused before engine work.
The call precedes loading action/delegation engine modules and initializing
their invocation loggers or budgets; it is not merely a discovery-readiness flag.

This preflight creates no acquisition proof, content alias or configuration
attestation. It does not replace the subsequent supported-configuration checks,
actual engine capture, retention-time admission or current-read authorization.
Operational failures and cancellation keep their typed meaning rather than
becoming source-access denial. V1 adapters do not call this hook.

The v2 external adapters also require the server callback
`context.capture_external_source_configuration(source_type, *, producer, settings, source=None, selector=None)`
at the actual acquisition boundary. They validate the complete owning producer
identity and preserve the original selector. Engines receive a private,
producer-bound `OrchestrationInvocationCapture`, not callback arguments supplied
by a model. Callback settings and source records are independent copies; callback
return values never enter a model prompt, `StepResult`, or persisted settings.

Optional engine hooks were implemented in **0.261.127**, recorded in
`application/single_app/config.py`:

| Engine | Captured configuration |
| --- | --- |
| Direct action | The actual authorized scoped manifest, the prepared loader input, and the constructed model transport/deployment/API version, factory protocol, model selectors and execution parameters. Each tool call repeats current authorization and capture before execution; changed configuration or refused capture stops the remaining calls. |
| Local agent | The optional loader hook captures the actual effective configuration, prepared inline OpenAPI manifests and constructed Azure model binding for a fresh, explicit-tools-only kernel. The ordinary orchestration local-agent path remains withheld because its implicit core tools do not have complete configuration/source proofs. |
| Classic Foundry agent/web search | The existing `get_agent` definition followed by the actual `ThreadRun` returned by the invocation's existing create/poll operations. Scoped remote agents first capture the actual `resolve_agent_config` result. Model, instructions, sampling and response format are explicit overrides; the SDK takes tools from an isolated definition. |
| Bounded research | The owning planner's actual constructor envelope, followed by each real Foundry search definition/run under the same `deep_research` producer. Query and link planning must not require planner-model calls. |
| Direct URL access | The effective bounded fetch and URL-access policy supplied to the real page reader. |

These engine events use `orchestration-external-acquisition-v1`. A preparation
event or a fetched Foundry definition is provisional: neither can authorize new
Gather output. Foundry uses `observed-run-v1`; a matching real run snapshot is
required before accepting any response. A proxy observes only the freshly owned
client's existing run operations, then restores them during cleanup. No global
SDK changes or extra provider/model requests manufacture execution proof.

Agent/action engines emit an authorization-only preparation before resolving
configuration, hydrating secrets, loading plugins or constructing model clients.
The root callback first calls `provider.preflight_gather_acquisition` with the
owning producer, exact original selector and actual preparation/configuration
event. This checks current access and supported configuration without creating
content authority. For agent/action preparation it does not call
`attestor.capture`; actual resolved engine evidence follows separately.
Preparation does not count as completed capture and invalidates earlier
per-invocation readiness. URL capture is different: its effective fetch policy
is the complete configuration, with no model-construction evidence required.

Captured runs permit no tools or at most 64 fully specified Bing grounding tools,
matching the subset whose current configuration can be independently verified.
Known unsupported tools or resource-backed definitions preserve a nonretryable
`result_unavailable` denial even when the earlier engine check stops them before
the definition callback. Malformed metadata remains a distinct verification
error. Neither failure can start a model run, create completion proof or admit
content; an unsupported definition is not forwarded merely to manufacture a
second policy decision.

Azure AI Search, function/file-search/code-interpreter/MCP tools, mutable
`tool_resources`, incomplete Bing configuration, missing definition fields and
templated instructions are refused after the existing definition metadata read
and before agent invocation or run creation. Unsupported resource modes cannot
spend a model call and then rely on post-result admission to reject them.
This restriction does not change standalone or version-1 execution.
A missing or changed run field, wrong agent/thread/run identity, or
refused observation also fails the invocation. Owned threads and clients are
cleaned up on failure. This proves the configuration used for the observed run,
**not** an immutable remote-definition revision or a page revision. There is no
fallback from missing run data to preparation or definition-only proof.

Direct-action model capture currently supports explicitly configured Azure
OpenAI transports. Captured execution settings explicitly bind
`parallel_tool_calls=False` and `tool_choice="auto"` before the first acquisition
event; the model descriptor contains both actual values. Unknown/custom protocols and implicit endpoint/API-version
construction are withheld before plugin or model work rather than inferred from
catalog labels or environment defaults. Ordinary action execution is unchanged.

New Foundry application and workflow response protocols expose no execution-bound
definition snapshot through these entrypoints; they refuse capture-required
execution before creating credentials, threads, or requests. Ordinary callers
retain those modes.

Local-agent admission needs the loader's actual resolved configuration,
prepared plugins and model-construction capture; outer agent attributes are not
a substitute. The narrowly scoped loader API is
`load_single_agent_for_kernel(..., execution_user_id=..., invocation_capture=...)`.
The callback must already be bound to the owning producer. A captured call
requires an empty kernel and an explicit execution user; a surrounding captured
execution cannot omit or replace its owning hook. Authorization-only preparation
precedes configuration resolution and client construction.

The bounded loader path admits explicit Azure OpenAI API-key construction and
origin-bearing OpenAPI manifests containing fully parsed inline specifications.
It captures each actual prepared
manifest before loading and verifies loading succeeded without a fallback. The
model descriptor records the constructed transport and the effective budget
arguments, including the actual automatic tool choice when plugins are bound.
Unknown request controls, remote schema references, runtime token-provider
bindings, preloaded tools, delegated agents and resource-derived SQL/Cosmos
configuration remain unavailable. Refused or failed loading poisons the owning
capture; safe service and cancellation errors retain their classification.
The existing per-service source validator and a fresh-kernel function filter
repeat capture before model/tool work and after returned data. They reject a
changed client, instructions, argument controls or plugin binding. Existing
model-budget guards keep their own typed failures rather than becoming
configuration denials.

`local_agent_configuration()` in
`functions_orchestration_model_capture.py` provides the deterministic private
configuration projection for current metadata reconstruction: omit only the
resolver's runtime `token_provider` handle, retain the bound instructions, and
record the actual `max_auto_invoke_attempts`. Other values must be JSON data.
No client, callable or callback return value becomes result metadata.

The normal local-agent builder still loads implicit core tools, including
document search and embedding-dependent tools. These have no complete prepared
manifest/source proof, so captured orchestration continues to refuse that path
before loading them. It does not silently remove ordinary core tools or activate
local agents merely because the optional loader hook exists. Parent-owned
current metadata reconstruction and admission are still required. Agents with
assigned knowledge remain withheld. Captured dynamic child delegation
is refused before resolving the child or consuming its execution budget.
Direct agent entrypoints cannot omit or rebind an already active capture to
another actor or conversation.
Supporting those configurations requires
the corresponding acquisition hooks and dependency bindings, not a
post-execution catalog lookup.

Research additionally needs the owning runner's actual planner-client
construction attestation and configuration capture for its search dependencies.
A later settings document is not proof of an existing client's construction.
The adapter calls
`get_planner_acquisition_configuration(context.planner_client)` with the
original, pinned client. The owning M2 helper checks that the pinned
`context.planner_deployment` is an exact string matching the returned deployment
and wraps the eight-field descriptor in the private planner/resolved envelope.
It neither resolves a replacement nor uses the answer's `model_context` or a
compatibility accessor. The envelope goes to the same capture as the real search
definition/run events. Missing, closed, replaced
or mutated construction bindings refuse execution; preparation alone cannot
replace that proof or a missing search run.

The supported version-2 research subset uses deterministic query/link planning.
It refuses server profiles with web search, more than one search query and
`deep_research_enable_query_planning`, or both `enable_deep_source_review` and
`source_review_enable_llm_planning`. The legacy planner tries different token and
temperature controls, and its model wrapper can further transform them.
Constructor defaults do not prove those effective request controls, so these
modes remain unavailable before search/page effects; the adapter does not
silently disable the configured planner. A one-query profile never invokes the
query planner. Multiple deterministic searches and deterministic link traversal
remain subject to the existing bounded review policy.

Optional `invocation_capture` flows through `perform_research_web_searches` and
`perform_source_review`; the web helper forwards the existing
`invocation_source_type="deep_research"` to Foundry. The helpers recheck pinned
construction and current authority around searches and page reads. The
synchronous review wrapper cannot turn a captured runtime/service failure into
an empty event-loop fallback. Version-1, standalone and workflow callers that
omit the hook keep their normal planning and fallback behavior. Independent
current metadata support still excludes APIM, implicit/custom transports and
unsupported Foundry resources; this engine wiring does not activate discovery.

Refusal is sticky across SDK tool-error handling, asynchronous tasks, worker
threads and reused execution frames. Catching a child exception cannot turn an
unattested result into success, and an inner frame cannot replace the owning
capture callback, actor or conversation. Version-1, standalone and workflow calls without the optional
hook retain their existing behavior.

Safe authority-service failures and explicit authorization cancellation remain
distinct from invalid capture. The pure capture state retains only the safe
exception class and stable code, not the original exception, traceback or
private details, and preserves that failure across later SDK containment.
Callback failures are classified before leaving their exception handler, and
engine failure arguments are released before rethrowing. Safe rethrows also
detach implicit exception context when an SDK caller is still handling another
error: `raise ... from None` alone hides that chain but keeps the original
exception reachable. Initial and sticky checks preserve the public exception
contract without retaining either private exception payload.
Unknown callback exceptions remain sanitized. Adapters return cancelled results
for authorization cancellation and propagate typed operational failures for the
runtime's retryable-service classification. Current metadata timeouts,
unavailability and throttling remain retryable configuration-service failures;
malformed or oversized metadata remains nonretryable verification failure.
Neither becomes permission denial. Genuine access refusal and document holds
instead retain safe `PermissionError` and `DocumentHeldError` classifications,
including after the SDK catches a failure. The owned Foundry observer records
failures from actual SDK snapshot validation as well as the capture callback.
Lifecycle owners with safe code-only exceptions can opt into the pure
`OrchestrationInvocationControlError` base so lease and execution-budget failures
keep their original type and code without importing runtime owners into capture.
Plain `InterruptedError` from an owning metadata/control check is normalized to
the safe capture cancellation type, without retaining its private message.
These classifications do not add retries or change the existing file-attempt budget.

New Gather admission requires captured configuration, whereas authorized reads
of committed results use their retained external bindings without requiring the
original process's capture map. Source-specific projections and current metadata
readers are independently required. Capture hooks alone do not enable these
capabilities; runtime/source-catalog admission remains separately gated.

Regression coverage includes
`test_orchestration_external_configuration_capture.py`,
`test_orchestration_capture_metadata_errors.py`,
`test_orchestration_invocation_capture.py`,
`test_orchestration_action_runtime.py`, and
`test_agent_delegation_runtime.py`, with bounded loader coverage in
`test_orchestration_local_agent_capture.py` and constructor-to-restart research
coverage in `test_orchestration_research_capture.py`. The checks exercise actual SDK invocation and
run polling, real action model construction and the Semantic Kernel tool loop,
strict private configuration attestation, and real retained-result
admission/readers after restart. External I/O is doubled; no live model is called
and no user file is published.

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

Committed orchestration exports retain their `orchestration_retained_output`
source binding during manual workspace publication. They use the same destination
approvals and retry receipts without inventing a workflow source receipt.
Workflow publication tasks still require their native Analyze or
`workflow_saved_output` source contract; an orchestration export cannot substitute
for either one.

Version **0.261.118** adds an optional
[workflow publication completion policy](WORKFLOW_PUBLICATION_COMPLETION.md)
for existing native Analyze artifacts. A version-3 durable workflow may require
confirmed submission, approval, or exact destination index readiness before
continuing. The absent policy retains its previous behavior. This does not
turn generic saved results or Collect outputs into native Analyze artifacts.

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

`test_orchestration_internal_analysis.py` exercises the real adapter, native
producer, work-unit checkpoints, saved reader, and generic facade/store with
external I/O doubles. It checks final-record/full-report survival after restart,
zero managed uploads, heterogeneous and partial findings, report absence,
source revocation/screening, cancellation and failed result commits.
`test_orchestration_file_policy.py` checks async/thread isolation and real
managed-operation guards in fresh normal and optimized interpreters.
`test_orchestration_publication_policy.py` covers direct publication, approval
and reconciliation denial with zero side effects, read-only observation,
default-allow compatibility, and real cold web/scheduler imports.
`test_orchestration_artifact_publication.py` covers real retained-result rendering,
upload, source authorization, manual promotion and workspace approval without
workflow receipts, including retries and source revocation.
`test_orchestration_external_configuration_capture.py` exercises real web and
source-review engines with external I/O doubles, checking invocation-time capture,
all producer identity fields, isolated execution settings, planner binding,
configuration denial, cancellation, and unchanged v1 behavior.

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
