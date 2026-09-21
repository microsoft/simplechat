# Gather / Reason / Render result foundation

**Version: 0.261.126**

Foundation implemented in version: **0.261.125**; shared export source bindings
implemented in version: **0.261.126**, recorded in
`application/single_app/config.py`.

Refs [#1509](https://github.com/microsoft/simplechat/issues/1509).
This documents the **M0 contract baseline, M1 retained-result facade, and shared
export source bindings**, not the complete orchestration/rendering epic.

## Purpose and availability

The foundation gives future orchestration adapters a common way to retain exact
results and bind a later consumer to a named output. A narrative finding, a
comparison, a table, and prepared source-free content do not have to masquerade
as a native Analyze result or be reconstructed from a preview.

Gather, Reason, and Render are purpose labels, not a required stage order.
Knowledge collection belongs to Gather. Analyze, Compare, tabular analysis,
synthesis, and drafting belong to Reason. Render will turn prepared results into
messages or files without undisclosed source retrieval or model work. The new
task contract rejects a Gather/Render label for the existing
`document_analyze`, `document_compare`, and `tabular_analyze` capabilities.

There is **no user-facing enablement or new setting** in this layer. Existing
v1 plans, capability phases, executor behavior, `RunContext`, checkpoint fields,
standalone tools, workflows, and download routes are unchanged. The following
APIs are internal foundation interfaces; production adapters and the scheduler
do not automatically call them.

New result writes are private retained data. They do not create chat artifacts,
download links, workspace documents, or published files. Existing native tool
artifact behavior remains compatible; that is not an implementation of the
future orchestration file-publication policy.

## Dependencies and ownership

| Component | Responsibility |
| --- | --- |
| `functions_orchestration_result_contracts.py` | Standard-library-only frozen descriptors, completeness, ordered schemas, named bindings, and dependency validation. |
| `functions_orchestration_results.py` | Injected producer/source authorization, private result persistence, complete readers, bounded previews, and explicit saved-Analyze projection. |
| `functions_workflow_result_store.py` | Existing immutable Cosmos/Blob transport and cancellation/deletion fences, plus three generic orchestration commit methods. |
| `functions_workflow_collections.py` | Bounded record-tree leaves/indexes and one aggregate write budget. |
| `functions_workflow_results.py` | Existing bounded section readers, including collection previews. |
| `functions_saved_analysis.py` | Existing native Analyze owner and authorized `SavedAnalysisInput`; no weakened `analyze-final-v1` validation. |
| `functions_analysis_access.py` and `content_screening.access` | Current source authorization, revision checks, and screening holds. |

Runtime owners supply initialized storage and access readers. The new modules do
not import `config`, routes, settings owners, saved-analysis owners, renderers,
artifact publishers, or model clients. They do not create another Cosmos/Blob
client, fabricate a workflow, or introduce global memory.

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

Prepared report/slide document schemas are **not** supported result kinds yet.
Storing arbitrary JSON does not advertise a validated Office/PDF layout contract.

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
)  # -> TaskResult

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
)
store.load_committed_orchestration_result(
    user_id, conversation_id, run_id, step_id, manifest_sha256,
)
```

Private sections reuse the existing orchestration result namespace, including
its historical `orchestration_analysis_result_chunk` name. This is a transport
name, not a claim that generic content satisfies Analyze's native schema.
Only the final immutable commit makes a descriptor readable. A caller-provided
digest for an uncommitted section cannot bypass that boundary.

### Access, lineage, and attempt boundaries

Reuse is original-owner and same-conversation only. Every read checks the
conversation and run owners, deletion state, exact attempt, and one matching
enabled producer step/capability. Historical v1 runs without `attempt_index`
retain their established original-attempt value of 1. Writes also require a
running run with no cancellation request or successor attempt.

`sources` contains exact `analysis_source_snapshot` dictionaries:
`document_id`, `scope`, `scope_id`, `source_version`, `source_revision`, and
optional `content_sha256`. Cached authorization decisions and storage locators
are not accepted as source snapshots.

`origin="generated"` requires no source/upstream lineage. `origin="grounded"`
requires actual sources or upstream results. Upstream references are recursively
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

This example does not add a field to existing production checkpoints. Wiring
descriptor retention into new runtime adapters is later work. Reconstructing an
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

## Verification and remaining scope

The new regression suites are:

```powershell
python -m pytest .\functional_tests\test_orchestration_result_contracts.py .\functional_tests\test_orchestration_results.py .\functional_tests\test_orchestration_result_imports.py -q
```

They exercise real production contracts/transport with external I/O doubles:
narrative Analyze and native foreground/durable fixtures; pending versus complete
data; source-free and multiple outputs; strict schemas/bindings; first/last-record
reuse by two readers after persistence/restart; a 30,000-row dataset exceeding
8 MiB; large text/structured data; count/digest/final-record corruption; current
source/producer/screening checks; explicit historical snapshots; stale tokens;
cancel/delete races; no artifact publication; unchanged v1 checkpoint
fingerprints; and the existing JSON export protocol.

Cold-import checks use fresh normal and optimized interpreters with network
blocked. They cover both lower-level import orders, required storage operations
and failure paths, and normal web and separate scheduler imports using real
runtime modules rather than a fake `config`.

Focused existing regressions cover Analyze storage/source access, orchestration
saved-result integration, checkpoint recovery/access, generated-file saved-record
exports, and the standalone v1 plan-schema runner. Legacy boolean-return scripts
must use their script runner; a pytest invocation alone is not evidence that
their returned result was successful.

There is no M2+ adapter rollout, new graph scheduler, semantic compilation,
message/file rendering, render-task UI, automatic file retry policy, or
per-file publication in this foundation. CSV/XLSX/DOCX/PPTX/PDF/JSON/XML/YAML/
Markdown/TXT orchestration output activation, prepared report/slide schemas,
independent file-task outcomes, and initial-plus-two automatic render attempts
follow in later reviewable layers. Workflows, media generation, cross-conversation
memory, and external delivery are outside this harness scope.
