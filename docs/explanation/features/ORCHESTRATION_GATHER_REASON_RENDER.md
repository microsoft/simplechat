# Gather / Reason / Render orchestration

**Version: 0.261.140**

Foundation implemented in version: **0.261.125**; shared export source bindings
implemented in version: **0.261.126**; application integration implemented in
version: **0.261.127**; single-contract rollout implemented in version:
**0.261.139**, recorded in
`application/single_app/config.py`.

Runtime boundary hardening implemented in version: **0.261.129**. See
[the invocation, retained-state, recovery, and delivery fixes](../fixes/ORCHESTRATION_RUNTIME_BOUNDARY_HARDENING_FIX.md).

Direct initial result-store binding implemented in version: **0.261.130**.
Initial preparation uses the initialized store owner without importing the
continuation module, while retaining a fresh check of the approved run, actor,
conversation, and attempt. See
[the initial binding fix](../fixes/ORCHESTRATION_INITIAL_RESULT_BINDING_FIX.md).

Chat content checks and model-catalog routing integrated in version:
**0.261.131**. Gather / Reason / Render replies use chat's output checkpoint before publication,
and Auto model routing uses the same orchestration contract. See
[the integration fix](../fixes/ORCHESTRATION_HARNESS_CHAT_CHECKS_ROUTING_INTEGRATION_FIX.md).

Answer parity implemented in version **0.261.134**:

- Auto model routing now binds and enforces per-step models on Gather / Reason / Render plans.
- `compose` receives saved memory, the resolved conversation references, a declared
  `knowledge_basis`, and guidance for planner-named visuals.
- A compose step whose basis allows general knowledge can mark a named input
  `optional`. It then discloses the input's failed producer instead of failing the plan.
- Read-only gathering retries once after a transient provider failure.

See [the deliverable planning fix](../fixes/ORCHESTRATION_DELIVERABLE_PLANNING_FIX.md).

Cosmos SDK response compatibility and specific failure diagnostics implemented in
version **0.261.140**, recorded in `application/single_app/config.py`. Storage
owners normalize `CosmosDict` responses before strict execution, result, and
output contracts while retaining ETags and authorization checks. This prevents
a valid saved run from being rejected at admission or hidden during status
recovery. See [the compatibility fix](../fixes/ORCHESTRATION_COSMOS_RESPONSE_COMPATIBILITY_FIX.md)
and [the planner declaration fix](../fixes/ORCHESTRATION_PLANNER_DELIVERABLE_FIELDS_FIX.md).
Answer declarations omit file-only fields, and an optional null `final_response`
is canonicalized to absence for work without a selected chat-text output.
Planning and editing use authorized source-kind metadata to keep native tabular
inputs out of narrative-only Analyze/Compare steps. Mixed-source answers compose
compatible prepared results without granting a new capability or source access.

Refs [#1509](https://github.com/microsoft/simplechat/issues/1509).
This documents the retained-result contracts, shared ten-format exports,
dependency execution, durable recovery, and the single orchestration plan contract.

The single-contract rollout and this page's version are the React V2 branch's 0.261.139 and 0.261.140. The V2 shared workspaces branch had already assigned those numbers to its native group identities and its group model endpoint APIs, so there both arrive with the React V2 base merge in version **0.261.181**.

## Purpose and availability

The foundation gives orchestration adapters a common way to retain exact
results and bind a later consumer to a named output. A narrative finding, a
comparison, a table, and prepared source-free content do not have to masquerade
as a native Analyze result or be reconstructed from a preview.

Gather, Reason, and Render are purpose labels, not a required stage order.
Knowledge collection belongs to Gather. Analyze, Compare, tabular analysis,
synthesis, and drafting belong to Reason. Render turns prepared results into
messages or files without undisclosed source retrieval or model work. The new
task contract rejects a Gather/Render label for the existing
`document_analyze`, `document_compare`, and `tabular_analyze` capabilities.

Since **0.261.139**, this is the only orchestration plan contract. New plans use
Gather / Reason / Render whenever **Enable Chat Orchestration** is on; the
separate preview/admission setting was removed, and stored
`enable_chat_orchestration_harness` values are dropped when settings load or
save. Current capability, model, source, and budget checks still apply. Plans
created by an earlier orchestration version fail closed with the standard
message telling the user to start a new request.

New result writes are private retained data. They do not create chat artifacts,
download links, workspace documents, or published files. Only explicit Render
tasks create downloadable files; orchestration publishes their committed
outcomes. Existing native tool artifact behavior remains compatible outside this
contract.

## Dependencies and ownership

| Component | Responsibility |
| --- | --- |
| `functions_orchestration_result_contracts.py` | Standard-library-only frozen descriptors, completeness, ordered schemas, named bindings, and dependency validation. |
| `functions_orchestration_results.py` | Injected producer/source authorization, private result persistence, complete readers, bounded previews, and explicit saved-Analyze projection. |
| `functions_workflow_result_store.py` | Existing immutable Cosmos/Blob transport and cancellation/deletion fences, plus additive orchestration commit and receipt methods. |
| `functions_workflow_collections.py` | Bounded record-tree leaves/indexes and one aggregate write budget. |
| `functions_workflow_results.py` | Existing bounded section readers, including collection previews. |
| `functions_saved_analysis.py` | Existing native Analyze owner and authorized `SavedAnalysisInput`; no weakened `analyze-final-v1` validation. |
| `functions_analysis_access.py` and `content_screening.access` | Current source authorization, revision checks, and screening holds. |
| `functions_orchestration_timing.py` | Bootstrap-independent timeout policy shared by claims and executors; same-attempt recovery retains the original durable deadline. |

Runtime owners supply initialized storage and access readers. The result facade
and contract modules do
not import `config`, routes, settings owners, saved-analysis owners, renderers,
artifact publishers, or model clients. They do not create another Cosmos/Blob
client, fabricate a workflow, or introduce global memory.

## Application integration boundaries

`functions_orchestration_bootstrap.py` is the application composition root. It
supplies initialized private storage, the current conversation/run readers,
source authorization, and generated-artifact transport to
`functions_orchestration_services.py`. Lower-level result and renderer services
do not discover configuration or clients themselves.

Document-source resolution and screening metadata use the strict callbacks in
`functions_orchestration_source_access.py`. A temporary authority outage and a
malformed/unverified authority response remain distinct from a real denial or
screening hold; neither becomes an omitted result or a successful empty source
set. The metadata reader checks current ownership and screening rather than
accepting cached permission fields. These callbacks do not change the existing
resolver defaults. Headless owners that catch an error must keep the strict
source-authority scope around the complete source/model decision so a fallback
cannot consume unverified data.

The same root supplies the server-only `native_bridge_for_step` callable to
runtime binding and capability discovery. The default factory validates the
explicit native arguments and binds the real compute-only request builder with
current-source policy; it does not submit work while planning or binding.
Missing hooks keep native Gather / Reason / Render work unavailable, non-callable readiness flags are
rejected, and rebinding a context clears any previous service's hook. The
callable is not a plan field, persisted checkpoint value, or browser selector.
Direct native adapters, dependency execution and saved native waits use the same
native infrastructure classifier before converting errors into step outcomes.
Transport, storage and current-authority uncertainty remain operational errors;
they do not discard an existing job handle or pretend that retained work failed
permanently. Genuine denial, invalid native arguments and cancellation retain
their distinct outcomes.

Render discovery uses the actual actor-bound `OrchestrationRenderingService`
instance in the private `rendering_service` request/context field. A boolean,
browser descriptor or arbitrary factory is not readiness evidence. The executor
owns its service-factory adapter and checks that the renderer shares the runtime
result service, actor and conversation. The root also binds output authorization
to that same initialized service and refuses a foreign scope before storage
access. Saved-plan editing and revision validation receive the same actual service
privately; plans created by an earlier orchestration version do not construct it, and no plan or checkpoint persists
the instance. Discovery performs no rendering or publication. Saved waiting and
completed Render tasks call the shared `resume_render_file` implementation with
the same input resolver and actor-bound service factory. This read verifies the
original producer, source, approved specification and deadline without claiming,
rendering, uploading, admitting a retry or expiring a sibling output. Operational
read failures remain exceptions rather than fabricated terminal file outcomes.

Internal callers can narrow the shared format/profile catalog without defining
new serializers. `None` keeps the canonical catalog; an explicit empty list
admits no file pairs. A subset must retain the shared descriptors unchanged
apart from filtering formats or profiles. Current server metadata is supplied
to planning, editing, execution validation, the claim boundary and runtime
binding. A removed requested pair rejects the work before generation instead
of dropping the file or choosing another format. These permissions are not
checkpointed or included in execution fingerprints, and a stale saved or
previously bound catalog cannot replace the current service catalog.
Malformed server catalog metadata remains an operational configuration error:
HTTP callers return a safe 503 rather than reporting changed sources or
claiming the plan. Valid but unadmitted pairs remain explicit plan refusals.

For retained external sources, the root also provides a lazy current-directory
identity reader using the configured application and Graph cloud. It reads
current account/app-role authority and uncached, read-only user restrictions;
it never substitutes saved session roles. Credential, directory, and metadata
I/O have explicit bounds, and temporary service failures remain distinct from
denied access. Document/source-free service construction does not acquire a
Graph token. This optional path requires operator-consented application
permissions as described in
[external source access](ORCHESTRATION_EXTERNAL_SOURCE_ACCESS.md); it does not
grant permissions or alter interactive sign-in scopes.

Initialized services compose the independent current-metadata reader,
configuration attestor and external-source provider. Before capture, the provider
rechecks current authority and verifies that both current and actual acquisition
configuration use a supported mode. Agent/action preparation without an actual
source performs this check but does not fabricate an attestation. Admission uses
the original captured selector; the runtime validates returned aliases and
installs them in the result facade's copied catalog before retaining data.
Restarted readers reconstruct current authority and configuration without the
old capture map or another acquisition. Unsupported local, resource-dependent,
custom and implicit modes remain unavailable rather than receiving guessed
configuration proof.

Current conversation, run and settings lookups preserve the shared metadata
reader's operational error classification across invocation capture. Timeouts,
service outages and malformed current metadata are not converted into permission
denial, missing sources or successful cached authorization. Confirmed ownership
changes, deletion, missing conversations and lost roles still deny access.

The initialized service supplies entry authorization (`external_source_preflight`),
external admission, current authorization, and acquisition-configuration capture
only as a complete group of four callables. The entry callback is the real
`preflight_gather_invocation` operation: it checks the original producer and
selector before engine setup or invocation-budget effects, returns synchronously
with `None`, and does not create acquisition proof. Capture independently checks
fresh authority and supported current/actual configuration before recording proof.
Read-only or incomplete services do not advertise acquisition; discovery never
invokes these callbacks or stores them in a plan.
Saved-plan editing and revision validation receive the same complete group from
the initialized service. Plans created by an earlier orchestration version do not construct these services or receive
the external bindings.
Read-only whole-run retry reconstruction retains the same initialized callbacks
and current catalog without invoking acquisition, writing a plan or making a
model request.

The root's configuration-digest helper uses a purpose-separated SHA-256 HMAC
with the existing configured `SECRET_KEY`. It refuses the public development
default, invalid values, and keys shorter than 32 bytes; it never substitutes
an unkeyed hash or an automatically generated key. The digest takes canonical
bytes and performs no directory or source I/O. This helper and the callback
contract are used by the default bound attestor; non-URL configuration revisions
cannot fall back to a public digest. Source-free and document-only construction
still performs no directory or configuration-metadata I/O. Execution-claim
fencing, dependency continuation and overall rollout remain separate runtime
gates.

Recorded HTTP execution uses the shared headless
`functions_orchestration_execution.py` runner before entering model
setup. The runner owns the actual claimed lease, model resources, and stable
assistant-message identity. Losing the browser stream detaches the event sink;
it does not cancel the approved durable work. Confirmed preparation failures
return their saved outcome. If terminal persistence cannot be confirmed, the
HTTP route returns an explicit temporary failure rather than claiming that a
run completed.

The authenticated export catalog is scoped to an owned conversation and the
currently available `render_file` capability. A disabled capability or missing
runtime resumer returns `rendering_unavailable`, not an executable-looking list
of formats. Planner and plan/editor event catalogs use the same filter; private
server-side validation still uses the canonical shared format contracts. A saved current-version plan keeps catalog access when its current capability
and runtime remain available.

File retry accepts one exact output and a canonical UUID submission ID; retrying an
uncertain response uses the same ID. It admits durable work without executing a
producer, replaying the plan, or rendering in the request. Detailed run reads and
retry responses rebuild per-file status from current output records instead of
trusting stored artifact links. They also return the currently authorized
committed artifact descriptors, so polling can attach a download card for a file
that finished after the stream closed. A current status/card lookup outage is an
explicit temporary error, not an empty successful response or cached file link.
Lean run listings also include current output states: shared map/resume
hydration can discover pending file work even when the aggregate run status is
already terminal. They do not load full plans or artifact cards. Plans from the removed earlier
contract are omitted and do not construct orchestration services.

Conversation message history refreshes both nested output states and committed
cards through the same actor-bound service. The outer screening/history
pipeline preserves those services' operational errors: a temporary authority or
storage failure returns HTTP 503, not a false document-review placeholder or
"conversation not found" response. Genuine source restrictions still withhold
only affected files, preserving accessible siblings and ordinary message text.
History reads do not acquire a rendering lease or modify saved messages. See
[the history outage fix](../fixes/ORCHESTRATION_HISTORY_OUTAGE_FIX.md).

Private retained-output downloads use the media type in the freshly authorized
committed descriptor, including YAML and filename aliases. The host operating
system's MIME registry is not authoritative. Active workspace representations
and legacy/native download behavior remain separate.

The root exposes a separate `build_orchestration_cleanup_service` for
deletion-only work. Its raw conversation reader preserves real tombstones,
Cosmos not-found responses, and storage failures. Its `read_run_tombstone`
callback reads the actual `checkpoint:lifecycle` record from the initialized
run-steps container. A missing conversation alone is not deletion authority:
physical deletion also requires the matching irreversible checkpoint tombstone
and retained parent deletion state. Cleanup requires the original-owner run,
output admission and immutable intents; it does not reconstruct a readable
conversation or invoke normal result, directory or model services.

Both single and bulk conversation deletion supply a lazy, run-scoped enrollment
callback to `cleanup_conversation_checkpoints`, together with the actual archive
retention policy. Recovery creates the irreversible checkpoint guard before the
parent deletion CAS, freezes the admitted output IDs and policy in that CAS, and
confirms every run's enrollment before source or message payload cleanup. A lost
acknowledgment leaves durable intent for the scheduler; a missing output, failed
fence or unconfirmed enrollment stops physical deletion rather than skipping it.

Ordinary message and Blob purges exclude retained orchestration files only after
this enrollment boundary succeeds. Their conditional cleanup remains owned by
the output lifecycle, including outputs whose Blob exists before a file message
does. Archiving preserves committed files while cancelling unfinished staging.
Without archival retention, enrollment explicitly withdraws committed outputs.
Tombstoned files and late staging wait for the existing lease grace period before
physical cleanup. Conversations with only earlier-version orchestration records construct no output cleanup service.
Storage uncertainty never substitutes for deletion proof, and the ordinary
history/download factory remains strict.

See [the output lifecycle contract](ORCHESTRATION_OUTPUT_LIFECYCLE.md) and
[orchestration administration](../../admin/orchestration.md). These service and
HTTP boundaries are covered by `test_orchestration_services.py`,
`test_orchestration_harness_routes.py`, and
`test_orchestration_output_downloads.py`. The initialized external-source root,
current Graph authority, full retained URL results after restart and operational
storage errors are covered by `test_orchestration_external_bootstrap.py`; the
deletion-only root is covered by `test_orchestration_cleanup_bootstrap.py`.
`test_orchestration_external_root_runtime.py` exercises authenticated URL Gather
through the actual default root, retained complete content, JSON rendering,
restarted history/download reads and current revocation, without reacquisition
or rendering during observation.
`test_orchestration_output_resume_runtime.py` verifies actual shared-resumer
dispatch, unchanged saved state and zero writes for target/sibling deadlines and
nonretryable metadata failures.
`test_orchestration_deletion_enrollment.py` and
`test_orchestration_output_deletion_pipeline.py` cover the real guard/CAS,
single/bulk callers, archive retention, interrupted enrollment, conditional
cleanup after grace, and legacy factory-free behavior.

The HTTP suite runs a claimed headless plan that creates Markdown and PDF from
one retained Unicode draft with one content-generation call. Current detail,
history, and downloaded-byte checks forbid model, native, rendering, and
publication replay. A transient second-file upload failure leaves the first
file committed and downloadable while the other output truthfully waits for
its next admitted attempt. An authenticated Stop request also preserves that
committed sibling's bytes. A pending output's `available` value describes
current authorization, not a committed download; only committed artifact
descriptors supply file cards. Changed approved filenames withhold the affected
file without hiding its unchanged sibling.

The actual planning endpoint is also covered with the shipped server readiness
and both administrator opt-ins, without injecting a saved run. It resolves the
conversation request, persists a Gather / Reason / Render plan despite a browser-supplied obsolete
contract marker, and exposes the ten-format catalog. Planning creates no
files; approval executes one prepared draft into Markdown and PDF. Fresh
detail and download reads do not repeat planning, composition, or publication.

`test_orchestration_reason_render_pipeline.py` also executes the real initialized
Analyze and Compare adapters through dependency execution, retained readers,
multiple explicit files, private commit, and the actual download handler.
Analyze's native sections use the existing saved-analysis injection API with
the same lease-bound result store as its checkpoints; constructing a new
token-only store would correctly fail the execution fence. CSV preserves the
native retained record order, not an invented source-order projection.
The native pipeline resumes one computation job and renders all 37 transformed
rows to CSV and JSON with no content-generation call.

The joined continuation, scheduler, headless, deletion, and metadata-recovery
suites cover restart, exactly three automatic file attempts, separate manual
retry, committed siblings, lost acknowledgments, and immutable claim fencing.
These are isolated production-boundary checks, not live tenant/model validation
or a throughput guarantee.

## Versioned contracts

| Contract | Wire version |
| --- | --- |
| `TaskResult` | `orchestration-task-result-v1` |
| `ResultRef` | `orchestration-result-ref-v1` |
| `InputBinding` | `orchestration-input-binding-v1` |
| `Completeness` | `orchestration-completeness-v1` |

The public frozen descriptors are:

```python
ProducerIdentity(
    user_id, conversation_id, run_id, attempt_index,
    step_id, capability_id, contract_version,
)
Coverage(expected, completed, unit)
Completeness(
    status, expected_count, actual_count, coverage,
    validation, checks, limitations, preview=False,
)
RecordColumn(name, value_type, nullable=False)
ResultRef(
    producer, output_name, kind, manifest_sha256, content_sha256,
    size_bytes, item_count, completeness, columns=(), character_count=None,
)
TaskResult(producer, role, status, outputs)
InputBinding(step_id=None, output_name=None, existing_result=None)
```

Descriptors use `to_dict()` and strict `from_dict()` methods. Tuples serialize as
JSON arrays; unknown fields, missing fields, unsupported versions, coercible but
incorrect types, and duplicate names are errors. An `InputBinding` dictionary
contains all three alternative fields, with unused fields explicitly `null`.
`task.output(name)` selects one exact output; a missing name is not an empty
result.

`ResultRef` contains no backend name, blob path, storage handle, client,
credential, callback, prompt, or retained dataset. The server resolves its
manifest digest through a producer-bound committed pointer. The manifest digest
binds all named outputs and their lineage. Each content digest covers canonical
compact JSON for collections/structured values, or original UTF-8 bytes for
text. These are data-integrity digests, not future exported-file digests.

### Honest completeness

The states are `pending`, `partial`, `complete`, `invalid`, `cancelled`, `failed`,
and `unavailable`. Completion is never inferred from nonempty prose or a
successful storage operation.

`complete` requires `validation="valid"`, explicit nonempty checks, equal known
expected/actual item counts, fully known completed coverage, and `preview=False`.
Coverage units are `sources`, `work_units`, `records`, or `items`. A legitimate
empty collection can therefore be complete; an unavailable collection cannot
be substituted with an empty one.

`partial` requires valid/partial validation and explicit limitations. It is not
readable unless the caller deliberately supplies `allow_partial=True`.
Pending/invalid/failed/cancelled/unavailable outputs remain unreadable even with
that option. Accepting a partial upstream result cannot promote a child output
to complete.

Counts, schemas, persisted content, and final-item presence are checked by the
facade. Producer checks and coverage describe work the producer actually
performed; they are not an independent factual review or proof that every
possible finding was identified.

### Implemented result kinds

| Kind | Retained value and complete reader |
| --- | --- |
| `records-v1` | JSON objects with an explicit ordered schema; `iter_records()`. |
| `text-v1` | Exact text; `iter_text()` or bounded `read_text()`. |
| `markdown-v1` | Exact prepared Markdown; the same text readers, with a distinct kind. |
| `structured-v1` | Strict JSON values, including nested objects/arrays, scalars and null; `iter_value_bytes()` or bounded `read_value()`. |
| `source-set-v1` | Exact authorized source snapshots; `iter_items()`. |
| `evidence-set-v1` | Objects containing exactly `evidence_id`, `source`, and `text`; `iter_items()`. |
| `comparison-v1` | Explicit completed/failed comparisons and target identities; `iter_value_bytes()` or `read_value()`. |

Records must contain exactly the declared columns. Supported column types are
`string`, `integer`, `number`, `boolean`, `object`, `array`, and `json`, with null
accepted only when `nullable=True`. Boolean values are not integers. Readers
restore declared column order and preserve leading zeros, formula-like strings,
Unicode, nested values, nulls, and booleans without flattening or coercion.

Source and evidence entries must match the full retained lineage snapshot,
including revision/version and any recorded content digest, not just a document
ID. Source identities and evidence IDs must not repeat within their collections.

The `comparison-v1` value has exactly this shape:

```json
{
    "left_document_id": "left-id",
    "right_document_ids": ["right-id"],
    "items": [
        {
            "right_document_id": "right-id",
            "right_document_name": "Comparison source",
            "text": "Prepared comparison findings."
        }
    ],
    "failed_document_ids": []
}
```

Targets must be unique, authorized in the lineage, and accounted for exactly
once as completed or failed. `expected_count` counts requested right-hand
targets; `actual_count` counts completed comparisons. Failure prose is not a
completed comparison. A complete result cannot contain failed targets.

Prepared reports use the text/Markdown kinds; prepared slide decks use
`structured-v1` with the shared `prepared_slide_deck_v1` profile. These are not
additional generic result kinds. The composition/export boundary validates the
prepared deck; storing arbitrary JSON does not prove that it is a valid deck.

## Injected access and storage interfaces

```python
OrchestrationResultAccess(
    *,
    user_id,
    conversation_id,
    read_conversation,
    read_run,
    source_resolver=None,
    source_metadata_reader=None,
    external_source_catalog=None,
    external_source_authorizer=None,
)
OrchestrationResults(store, access, *, max_result_bytes=None)
```

The callbacks are server-owned:

| Callback | Required behavior |
| --- | --- |
| `read_conversation(conversation_id)` | Return the current conversation record, including its true owner and deletion state. |
| `read_run(run_id)` | Return the current run record, including owner, conversation, attempt, current plan steps, cancellation and deletion state. |
| `source_resolver(document_ids, **scope)` | Implement the existing `resolve_authorized_source_manifest` protocol; current access/scope/version/revision information must come from authorized source metadata, not the request. |
| `source_metadata_reader(document_id, user_id, group_id=None, public_workspace_id=None)` | Enforce the actor's current source/workspace access and return current screening metadata using the existing screening reader protocol. |
| `external_source_authorizer(reference, *, producer, user_id, conversation_id)` | Return a current `ExternalSourceRef` only after checking current capability, integration/resource access, and the original audience. Required for every external source type, including public web results. |

Source-free results need no source callbacks. Grounded results fail closed if a
required callback or source is unavailable. There is no application-settings or
client-factory fallback.

The facade methods are:

```python
service.persist_task_result(
    *,
    producer,
    role,
    status,
    outputs,
    sources,
    origin,
    guard_token,
    upstream=(),
    source_policy="current",
    allow_partial_inputs=False,
    input_fingerprint=None,
    external_sources=(),
)  # -> TaskResult

service.recover_task_result(
    *, producer, input_fingerprint,
)  # -> TaskResult | None

service.open_result(
    reference, *, allow_partial=False, require_current_sources=False,
)  # -> OrchestrationResultReader

service.resolve_input(
    spec, *, consumer, task_results, existing_results=None,
)  # -> OrchestrationResultReader
```

Each output is `NamedOutput(name, kind, value, completeness, columns=())`.
Collection values may be one-pass iterators. The guard token must be the
server-owned token for that actual producer attempt; it is not a model argument
or part of a serialized result reference.

The shared `WorkflowResultStore` adds only:

```python
store.prepare_orchestration_result(
    user_id, conversation_id, run_id, step_id, *, guard_token,
)
store.commit_orchestration_result(
    user_id, conversation_id, run_id, step_id, reference, *, guard_token,
    producer=None, input_fingerprint=None,
)
store.load_committed_orchestration_result(
    user_id, conversation_id, run_id, step_id, manifest_sha256,
)
store.load_orchestration_result_receipt(producer, input_fingerprint)
```

Private sections reuse the existing orchestration result namespace, including
its historical `orchestration_analysis_result_chunk` name. This is a transport
name, not a claim that generic content satisfies Analyze's native schema.
Only the final immutable commit makes a descriptor readable. A caller-provided
digest for an uncommitted section cannot bypass that boundary.

### Native resume and committed-result recovery

Generic saving shares the native step's **existing active token and resume
binding**. It does not call native preparation again with a default
`resume_from=None`, replace the original request/source digests, or start another
attempt. A missing guard is initialized normally; an existing guard must still
be writable by the owning token. Cancelled, deleted, superseded, or differently
tokened workers are rejected.

An owning runtime may provide its server-computed, 64-hex `input_fingerprint` for
a terminal `complete` or `partial` task result. The store writes one deterministic
producer/input receipt and the digest commit in the **same lifecycle-CAS
transaction**. The key includes the complete `ProducerIdentity`, including
attempt and producer contract version, plus the input fingerprint.

| Write/recovery condition | Result |
| --- | --- |
| Same exact identity and same committed digest | Idempotent success. |
| Same identity but a different result digest | `OrchestrationResultConflictError`, code `orchestration_result_commit_collision`; no replacement or latest-result selection. |
| No receipt for the exact producer/input identity | `recover_task_result()` returns `None`; other inputs/attempts are not scanned. |
| A receipt exists but its binding, commit, manifest or data is corrupt/unavailable | Explicit failure, not `None`, a preview, or permission to replay a model. |
| Cancellation/deletion wins the commit CAS | Neither receipt nor digest commit becomes visible. |
| Commit succeeds and the runtime stops before saving its checkpoint | The same authenticated lookup recovers the original result without needing the lost manifest digest. |

Recovery reauthorizes the original producer, document sources/screening,
external sources and upstream lineage, then fully streams and verifies every
readable output before returning. It preserves output order, partial coverage
and nonreadable failure descriptors. Consumers still cannot bind a failed
output as data. Recovery performs retained-storage/metadata I/O, not model work,
source-content fetching, or reconstruction from previews.

A completed result remains recoverable after a later sibling fails or the
original attempt is stopped. It retains its **original** run/attempt identity.
Cross-attempt use requires the normal explicit result alias; recovery does not
relabel the old result as a new producer. Pending native jobs stay in their
existing job/wait lifecycle and do not receive completed-result receipts.

The optional private manifest version is
`orchestration-result-manifest-v2`, with `input_fingerprint` and `output_order`.
The fingerprint is nullable when only external lineage opts into this version.
The receipt binding version is `orchestration-result-receipt-v1`. Public
`TaskResult` and `ResultRef` wire schemas remain version 1. With neither extension used,
the original manifest and descriptor bytes remain unchanged; no old result is
silently assigned a new input identity.

### External Gather provenance

Web, URL, deep-research, agent, action, and Fact Memory results can carry explicit
external provenance rather than fake document IDs or a source-free label:

```python
ExternalSourceRef(
    source_type,
    capability_id,
    reference_id,
    audience,
    content_sha256=None,
    source_revision=None,
)
```

This frozen descriptor has strict `to_dict()` / `from_dict()` methods and wire
version `orchestration-external-source-v1`. `source_type` is one of `web`, `url`,
`deep_research`, `agent`, `action`, or `fact_memory`. Capability, reference, and
audience are opaque ASCII identifiers of at most 256 characters, using letters,
digits, `_`, `.`, `:`, and `-`; they must start with a letter or digit. They are
not URLs, storage paths, credentials, callbacks or raw memory prompts. A bounded
source revision or SHA-256 digest is required. A revision may retain an ETag,
but cannot contain control characters or exceed 256 UTF-8 bytes.

The owner supplies `external_source_catalog` as an explicitly authorized
`dict[str, ExternalSourceRef]`. `external_sources` passed to persistence is a
list/tuple of aliases from this catalog, not model-supplied descriptors. Catalogs
and direct bindings are limited to 64 entries. Aliases and exact external
resource identities cannot repeat in one result's bindings.

The committed lineage uses `version="orchestration-lineage-v2"` and stores:

```json
{
    "external_sources": [
        {
            "alias": "admitted_source",
            "reference": {
                "version": "orchestration-external-source-v1",
                "source_type": "web",
                "capability_id": "web_search",
                "reference_id": "server-owned-search-result",
                "audience": "personal:original-owner",
                "content_sha256": null,
                "source_revision": "retained-revision-1"
            }
        }
    ]
}
```

This is the external-binding portion of the lineage; its ordinary origin,
policy, document sources, upstream references and partial-input policy remain
required. A grounded lineage can contain documents, external bindings, upstream
results, or a combination. Generated content must contain none of them.

Every external descriptor is reauthorized by the injected callback on saving,
reading, recovery and transitive reuse. Returning `True`, a dictionary or `None`
does not grant access. The callback must return a current typed descriptor or
raise. Its source type, capability, reference ID and audience must exactly match
the original. A source revision/digest change fails under `current`; explicit
`snapshot` access retains the original data and reports the change, without
relaxing current permission, capability or audience checks.

Current here means **current authorized server resource metadata**, not a hidden
re-fetch or rerun of the gathered content. Public display URLs may be retained in prepared content, but
are neither fetch instructions nor permission to use a tool. The callback must
enforce current integration/agent access or memory audience as applicable. This
does not expand Fact Memory across conversations or introduce global memory.

Aliases and original descriptors are durable server manifest data, not a
Python-only cache. Reads after restart reauthorize those committed bindings
without requiring the old admission catalog. `metadata()["external_sources"]`
returns the **direct** persisted bindings so an authorized owner can rebuild its
catalog with `ExternalSourceRef.from_dict()`. New writes still require catalog
admission. Upstream references preserve their own producer-bound aliases; they
are not flattened into a potentially ambiguous global catalog.

Existing `source_count` retains its document-source meaning. Optional
`external_source_count` includes distinct inherited external resources, and
`source_snapshot_changed` covers either source class. Traversal permits at most
256 retained external snapshots. Existing document-only lineages are not
reinterpreted.

External content uses existing text/Markdown, records or structured-value kinds
as appropriate. `evidence-set-v1` and `source-set-v1` remain document-scoped.
Adding provenance does not advertise a new renderer or make an external
integration call.

### Access, lineage, and attempt boundaries

Reuse is original-owner and same-conversation only. Every read checks the
conversation and run owners, deletion state, exact attempt, and one matching
enabled producer step/capability. Historical runs without `attempt_index`
retain their established original-attempt value of 1. Writes also require a
running run with no cancellation request or successor attempt.

`sources` contains exact `analysis_source_snapshot` dictionaries:
`document_id`, `scope`, `scope_id`, `source_version`, `source_revision`, and
optional `content_sha256`. Cached authorization decisions and storage locators
are not accepted as source snapshots.

`origin="generated"` requires no document/external/upstream lineage.
`origin="grounded"` requires actual sources or upstream results. Upstream references are recursively
reauthorized, cycle-checked, and bounded. Their source snapshots remain part of
the child's authorization boundary.

The default `source_policy="current"` rejects changed source versions,
revisions, and recorded content digests. Explicit `source_policy="snapshot"`
allows the historical retained content while reporting
`source_snapshot_changed=True`. It never skips current source access or screening.
`require_current_sources=True` can impose current-snapshot validation on a reader,
including its upstream lineage.

Opening a reader is not a permanent access grant. Authorization is repeated when
loading sections and after full reads. Deletion preserves existing lifecycle
tombstones; a late or differently tokened worker cannot recreate deleted results.
Cancellation fences new writes without deleting already completed readable
results. No fence is replaced by a permissive fallback.

## Named bindings without a runtime rewrite

```python
InputSpec(name, binding, kinds, allow_partial=False)
OutputSpec(name, kind)
StepBindings(step_id, enabled, outputs=(), inputs=(), depends_on=())
validate_input_bindings(steps, *, existing_results=None, max_steps=64)
```

The server supplies these specifications and accepted kinds. A model binding can
select a producing step plus output name, or a named alias in an explicitly
admitted existing-result catalog. It cannot supply storage references, actor
identity, projections, or arbitrary callbacks.

Validation returns dependency tuples without mutating, sorting, repairing,
trimming, or executing a production plan. Missing/disabled producers, unknown
outputs, incompatible kinds, duplicate names, cycles, and step-budget overflow
are errors. It does not make a requested output disappear to fit a limit.

At consumption, a step/output binding must match the consumer's actual run and
attempt. Reuse across attempts requires an explicit server-admitted existing
result alias; it is not silently rebound to a similarly named step. Alias
resolution still rechecks the original producer and every source. An alias
cannot introduce a direct self-binding.

## Using retained results from an owning adapter

The following internal pattern assumes the producer has completed and validated
the prepared value, and that the owner has already supplied its authorized
producer identity, access callbacks, store, and lifecycle token:

```python
from functions_orchestration_result_contracts import Completeness, Coverage, TaskResult
from functions_orchestration_results import NamedOutput, OrchestrationResults

service = OrchestrationResults(store, access)
task = service.persist_task_result(
    producer=producer,
    role="reason",
    status="complete",
    outputs=[
        NamedOutput(
            "prepared",
            "structured-v1",
            {"title": "Prepared content", "sections": []},
            Completeness(
                "complete", 1, 1, Coverage(1, 1, "work_units"), "valid",
                ("prepared_value_schema",), (),
            ),
        ),
    ],
    sources=[],
    origin="generated",
    guard_token=guard_token,
)

# The owning layer retains only this small descriptor, not the dataset.
descriptor = task.to_dict()
restored = TaskResult.from_dict(descriptor)
reader = service.open_result(restored.output("prepared"))
prepared_value = reader.read_value()
```

This example uses the facade directly; it does not activate the versioned
runtime or alter legacy checkpoints. Reconstructing an
`OrchestrationResults` instance with initialized handles and the same persisted
descriptor reads the original retained data, rather than rerunning its producer.

### Reader protocol and integrity

Records readers implement the existing export-source protocol:
`kind == "records"`, `record_count`, `columns`, `iter_records()`, and `recheck()`.
`columns` is a tuple of `RecordColumn` objects, not an array of inferred names.
Other reader `kind` values remain their explicit versioned result kinds.
`result_kind` always retains the versioned kind.

Text/Markdown readers expose `character_count` as the verified Unicode character
count, distinct from UTF-8 byte size. Structured/comparison readers expose
`read_value()` and streamed canonical JSON through `iter_value_bytes()`.
`metadata()` returns the reference, distinct source count, origin, source policy,
and source-change flag.
For an extended manifest it also includes the optional input fingerprint. External
lineage metadata is described above; it does not expose executable fetch handles.

**Consumers must exhaust a full iterator before accepting or publishing its
result.** Final count/digest checks and the last access recheck run at exhaustion.
A preview or a partially consumed iterator is not an integrity receipt.
Exhausting an explicitly allowed partial result verifies that retained subset,
not complete original coverage. Export adapters preserve this distinction
rather than infer readiness from a record count.

`preview(max_items=3, max_bytes=4096)` returns an explicitly marked preview with
`integrity_verified=False`. Collection previews contain bounded records;
text/Markdown and structured/comparison previews contain text fragments. A JSON
preview need not be a parseable complete JSON value.

### Shared export source bindings

`functions_orchestration_export_sources.py` adapts authorized full readers to the
shared generated-file framework without adding a serializer or publishing a
file. These service APIs do not enable orchestration Render tasks by themselves.

- `build_orchestration_export_source(reader, *, columns=None, max_value_bytes=...)`
  adapts an already authorized reader.
- `open_orchestration_export_source(service, reference, *, columns=None,
  max_value_bytes=..., require_current_sources=False)` opens through the result
  service before adapting it. It never opts partial data into a complete export.
- `build_saved_analysis_export_source(source, *, completeness, columns=None)`
  retains the native saved-Analyze reader and authorization. Its owner must
  validate native coverage into an explicit `Completeness` contract; a successful
  legacy status or nonempty record list is not sufficient proof of full coverage.

Records become a `records` source with explicit ordered public column names.
Text and Markdown use their verified Unicode character counts and full chunk
iterators, without a preliminary counting read. Structured and comparison values
use the bounded `structured_value` source; source/evidence sets require an
explicit supported representation rather than automatic flattening.

Column selection is an allowlisted projection over the retained schema. It may
select or reorder public fields, but it does not invent columns, flatten nested
values, change row order, or replace the original result. The chosen projection
must be part of the owning render specification and its retry identity.

Create a fresh binding per render attempt. After rendering, the publisher must
call `require_complete_consumption()` before accepting the stream. That method
requires an exhausted, count-verified input and rechecks current access. Merely
opening a reader, inspecting a preview, or stopping after its first row does not
produce a receipt. Renderer/transport failures still require their own cleanup
and publication guards.

The integration coverage is in
`functional_tests/test_orchestration_export_sources.py`, including two exports
of 30,000 retained rows after restart, no producer replay, strict projections,
partial-data refusal, current versus historical source policy, and revocation.

### Bounds and performance

| Bound | Value |
| --- | --- |
| Outputs per task / inputs per step | 32 |
| Ordered record columns | 256 |
| Binding steps | At most 64; an owning layer can pass a smaller budget. |
| Serialized descriptor / final manifest / lineage | 128 KiB each. |
| Collection leaf budget | Existing 100-record / 128-KiB pages and bounded indexes. |
| Text / JSON fragment size | 4,096 Unicode characters / 16,384 ASCII characters. |
| Materialized text or structured value | At most 8 MiB; larger results require streaming. |
| Comparison value | At most 8 MiB, including semantic count validation during streamed reads. |
| Preview | At most 20 items / 16 KiB. |
| Upstream references / traversed lineage results | 64 / 256. |
| External admission catalog / direct external bindings / retained external snapshots | 64 / 64 / 256. |
| Aggregate retained bytes | `max_result_bytes`, defaulting to the injected store's `max_size_bytes`; sections and indexes share one budget. |

Oversized records, manifests, or aggregate data fail rather than being shortened.
Large datasets live in bounded private sections, not an 8-MiB orchestration
checkpoint. Reauthorization has real metadata-I/O cost, especially with many
sources or upstream results; offline scale fixtures do not claim cloud throughput.

## Existing saved Analyze and JSON compatibility

An owner can pass the real bounded reader returned by
`load_orchestration_analysis_input(..., bounded=True)` to:

```python
SavedAnalysisRecordSource(reader, *, columns)
```

This adapter requires a succeeded, valid `analyze-final-v1` records result.
`iter_records()` explicitly projects each original record's `values` through the
supplied ordered schema. `iter_units()` preserves full original record identities
and evidence; `metadata()` retains native coverage and source snapshots. All
reads delegate to the existing authorized native reader.

This is a separate compatibility interface, not a conversion of arbitrary
prose or Compare output into Analyze. It does not modify native persistence,
standalone generated artifacts, or workflow behavior.

The existing `exact_records_v1` JSON export accepts a complete generic records
reader without any new export profile. Other formats use explicit shared export
profiles; passing CSV to the unchanged `exact_records_v1` profile still fails.
Neither the result facade nor its compatibility adapter invokes an export or
publishes a file automatically.

See [Saved Analyze results](ANALYZE_RESULTS.md),
[Chat orchestration](CHAT_ORCHESTRATION.md), and
[Checkpoint recovery](ORCHESTRATION_CHECKPOINT_RECOVERY.md).

## Verification and limitations

The new regression suites are:

```powershell
python -m pytest .\functional_tests\test_orchestration_result_contracts.py .\functional_tests\test_orchestration_results.py .\functional_tests\test_orchestration_result_imports.py -q
python -m pytest .\functional_tests\test_orchestration_result_recovery.py .\functional_tests\test_orchestration_external_results.py -q
```

They exercise real production contracts/transport with external I/O doubles:
narrative Analyze and native foreground/durable fixtures; pending versus complete
data; source-free and multiple outputs; strict schemas/bindings; first/last-record
reuse by two readers after persistence/restart; a 30,000-row dataset exceeding
8 MiB; large text/structured data; count/digest/final-record corruption; current
source/producer/screening checks; explicit historical snapshots; stale tokens;
cancel/delete races; no artifact publication; unchanged checkpoint
fingerprints; and the existing JSON export protocol.
The follow-up cases also cover real native resumed work-unit guards, atomic
receipt rollback/collision races, commit-before-checkpoint crashes, recovery
after sibling failure, complete readable-data verification, exact published-v1
byte fingerprints, all external source types, lost audience/capability/resource
access, explicit historical external snapshots, and catalog restoration.

Cold-import checks use fresh normal and optimized interpreters with network
blocked. They cover both lower-level import orders, required storage operations
and failure paths, and normal web and separate scheduler imports using real
runtime modules rather than a fake `config`.
The early normal/optimized probes execute native resumed preparation, receipt
recovery and external-source reauthorization with explicit checks that cannot
disappear under `-O`.

Root causes and before/after behavior for these integration seams are recorded in
[the foundation integration fix](../fixes/ORCHESTRATION_FOUNDATION_INTEGRATION_FIX.md).

Focused existing regressions cover Analyze storage/source access, orchestration
saved-result integration, checkpoint recovery/access, generated-file saved-record
exports, and the standalone plan-schema runner. Legacy boolean-return scripts
must use their script runner; a pytest invocation alone is not evidence that
their returned result was successful.

Integration coverage adds the real producer pipelines, HTTP planning/execution
boundaries, shared Render resumer, scheduler, deletion enrollment, and V2
authoring/output/retry UI. All ten formats reopen through independent readers;
two complete 30,000-row exports exceed 8 MiB after restart.

The existing scheduler-first mixed-bootstrap probes retain their documented
`enabled_required` startup xfails. The unrelated legacy tabular scale runner has
unchanged AST-fixture dependency omissions and an unbounded fixture wait; it is
not reported as passing. No live tenant, paid model, or cloud throughput test was
performed. Deployment-specific permissions and provider configurations still
need an administrator's validation before rollout.

Workflow integration, new media generation, cross-conversation memory, and
external delivery remain outside this orchestration scope. The result store is not
a global memory library, and rendering does not grant access to a source.
