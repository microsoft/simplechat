# Saved workflow output publication

Implemented in version: **0.261.119**.

Updated in version: **0.261.120** for Repeat final records.

Application version tracking: `application\single_app\config.py`.

## Overview and purpose

A version-3 durable workflow can explicitly select an eligible saved records
output, render every selected record as exact JSON, and submit that file to a
chosen workspace. The producer can be a real task, Collect, or explicit join.
This makes a collected dataset downloadable and publishable without rerunning
Analyze, asking a model to reconstruct rows, or disguising Collect as a native
Analyze task.

This M4C-2 slice uses the existing
[Generated File Export Framework](GENERATED_FILE_EXPORT_FRAMEWORK.md).
There is no workflow-only renderer or second publication service.

In **0.261.120**, a satisfied [Repeat until](WORKFLOW_REPEAT_UNTIL.md) boundary
can also provide a named final records export. It remains a real engine-node
output with its exact selected-producer receipt, not an invented Analyze task.
An unmet batch limit exposes no final Repeat output for publication.

| Representation | Purpose |
| --- | --- |
| Saved task or engine output | Durable data consumed through explicit typed bindings; no workspace upload or indexing is needed for the next task. |
| Generated JSON file | A byte-verified representation of the selected saved records, accessible through existing private generated-file downloads. |
| Published workspace document | An explicitly requested destination copy, with its own permissions, approval, processing and readiness. |

The **Saved workflow output** Publish task creates the downloadable file **and
submits it to its configured destination**. It is not a new download-only task
mode. Merely saving or validating a result does not publish it.

## Dependencies and compatibility

- Personal or group workflows must use definition version **3** and durable
  execution. Existing workflow enablement and role requirements still apply.
- The selected records must have an eligible saved result and an exact
  committed attempt in the existing schema-2 journal.
- Workflow results can use either Cosmos or Blob storage. The generated file
  itself still requires the existing configured **private Blob artifact
  transport**; Cosmos result storage is not a file-storage fallback.
- The existing workflow runner, result reader, generated-file transport,
  publication receipt ledger, destination approval and native ingestion are
  reused. No administrator switch, scheduler, container or definition version
  is added.

Omitting `publication.source_kind` retains native Analyze publication and stays
omitted on a definition round-trip. Explicit `native_analysis` selects the same
native path, with its existing formats and provenance requirements. Nothing
converts legacy tasks into generic exports.

The server advertises source-specific availability through optional
`publication_source_capabilities` entries containing `source_kind`,
`output_kinds` and `artifact_formats`. Saved-output formats come from shared
export-profile support. An older server does not implicitly gain this option;
unsupported saved source/format configurations remain intact and read-only.

## Definition and source eligibility

The publication object gains one optional discriminator, `source_kind`, whose
values are `native_analysis` and `saved_output`. For the latter, the only
supported `artifact_format` is `json`. The task must bind exactly one required
`node_output` input with `expected_kind: "records"`:

```json
{
  "publication": {
    "source_kind": "saved_output",
    "artifact_format": "json",
    "workspace_scope": "group",
    "group_id": "explicit-destination-id",
    "completion_policy": "indexed_ready"
  },
  "inputs": [
    {
      "name": "deliverable",
      "source": {
        "kind": "node_output",
        "node_id": "collect-findings",
        "output": "records",
        "scope": "current"
      },
      "required": true,
      "expected_kind": "records",
      "allow_partial": false
    }
  ]
}
```

Here `collect-findings` and `records` must identify a real node and its selected
records output in the frozen definition. A task's authoritative records output
is also eligible. An explicit join retains its selected-producer receipt and
branch lineage; it is not resolved by looking for a recent task ID.

The adapter rejects direct loop-item or Repeat-state inputs, optional missing
inputs, diagnostics, preview rows, text, scalar or untyped JSON, and
`document_results` bundles.
Nested objects and arrays **inside supported record objects** remain supported.
Invalid, failed, pending or unreadable sources cannot become valid files by
changing the format.

Accepted partial output requires both the existing producer/Collect partial
contract and `allow_partial: true` on the publishing input. Validation and
coverage remain visibly partial; missing work is not relabeled complete.
Duplicates and record order are preserved. A declared uniqueness-contract
violation remains invalid: export never deduplicates it into a passing result.

For Repeat exports, the state-slot and body/downstream partial policies must
also have accepted the carried data. A later true Until condition never removes
its coverage limitations. Body-state receipts are not a shortcut around the
required final `node_output` records binding.

`source_kind` describes the source, not the destination. Personal, group and
public destination fields keep their existing meaning. The selected workspace
is explicit and does not follow the user's active workspace.

## Shared rendering and exact JSON

`WorkflowRecordExportSource` in `functions_workflow_artifacts.py` wraps the
existing authorized `open_workflow_record_input` reader. It verifies the real
node/execution/path/attempt, committed `result_ref`, selected `output_name` and
`output_ref` before invoking the shared renderer:

- `GeneratedRecordExportSource` supplies `kind="records"`, `record_count`,
  `iter_records()` and `recheck()`.
- `GeneratedFileExportRequest(profile="exact_records_v1", output_format="json")`
  explicitly selects the representation at `build_generated_file_export`.
- `GeneratedFileExportStream` owns the completed seekable stream and its media
  type, format, profile, byte size, record count and content SHA-256. Closing it
  releases temporary storage.

The file is one JSON array containing every selected saved record object in
reader order, including nested `values` and retained provenance. It does not
strip the object down to `values`, flatten fields, use just a preview, infer an
action-result envelope, or regenerate missing data from prose. Existing
sanitization for the framework's legacy action-result adapter is unchanged.

The `exact_records_v1` profile uses sorted object keys, compact separators,
ASCII escaping and finite JSON values (`allow_nan=False`). It uses no
`default=str`, generated commentary or BOM. Null, booleans, zero, long strings,
Unicode, nested arrays/objects and repeated records retain their JSON values.
An eligible empty collection produces `[]`. This is value preservation, not
preservation of an original document's lexical JSON formatting.

The complete paged collection is serialized into quota-bounded temporary
storage without building a whole-collection list or string. SHA-256 and length
cover the actual encoded bytes, including commas, brackets and string
escaping. The written record count must equal the declared count. An exact
byte-limit match succeeds; overflow fails rather than exposing a shortened
file. Cancellation/lease and source checks run during the operation and again
at completion.

## Durable file identity and recovery

The source/representation key includes workflow scope, frozen definition
revision, exact producer identity, `result_ref`, `output_name`, `output_ref`,
the authored partial policy, profile and format. It does not include the
publishing task's mutable attempt, destination or current time.

The same source representation therefore keeps:

- Artifact idempotency key: `generated-export:v1:{export_key}`.
- Filename: `workflow-output-{export_key}.json`.
- The existing deterministic generated-artifact address.
- SHA-256 of the completed file bytes, not of a preview or summary.

Materialization persists an immutable descriptor through the existing result
store. Existing root-node journal `unit` records
`["generated-file-prepare", export_key]` and
`["generated-file-ready", export_key]` bind preparation and commitment to the
real root selectors. These units track file creation only; they are not a new
destination ledger.

Preparation fixes the source, address, digest, byte size and count before
upload. The typed transport uses create-only Blob and file-message writes.
A lost acknowledgement is reconciled by verifying the same address, source
binding, actual bytes and digest, not by overwriting a different artifact.
If recreation is needed, the same source must produce the prepared digest.
No uncommitted file is readable or publishable before its ready checkpoint.

The server-authored `generated_artifact_source` binding has
`kind="workflow_saved_output"` and includes the exact source receipt, scope,
partial policy, representation and materialization reference. It is separate
from native `analysis_producer` metadata. Collect and join identities never gain
fabricated task IDs or native Analyze flags.

After commitment, the existing publication service submits the file. Its v3
request identity remains:

```text
workflow-publication:v3:{publishing_execution_id}:{producer_execution_id}:{producer_attempt}
```

The existing sole artifact-message ledger retains destination effects, approval,
notifications and reconciliation. Native receipt identities are unchanged;
generic identities additionally bind the validated saved-output source.
Different publication nodes or destinations may reuse a source artifact while
retaining their own destination receipts.

A genuinely new Repeat round changes the source identity when a new producer
actually runs. Retrying a publication of already materialized output keeps
the same exact source, immutable bytes, and destination receipt; changes to
the publisher's attempt or display order do not select a newer round.
Manual continuation grants no publication permission or completion bypass.

## Authorization and existing APIs

Source receipts, digests and artifact locators are not permissions. Current
workflow/run ownership, group membership/status, conversation access,
contributing sources, frozen input/iteration membership and artifact lifecycle
or approval are rechecked at sensitive boundaries. The run's frozen definition
and exact committed attempt are authoritative, not the currently edited
workflow or a latest-task lookup.

`functions_generated_artifact_sources.py` dispatches native artifacts to their
existing authorization and saved-output files to the workflow adapter. The
shared check covers publication, downloads, previews, history and conversion.
A missing or malformed typed binding fails closed instead of falling back to
an unbound artifact.

No new public endpoint is added. The existing `/api/chat_artifacts/download`
route verifies the entire saved-output file into temporary storage before
streaming response bytes, using the existing private/no-store and attachment
behavior. Publication and approval use the existing stream-capable handoff.
Native document processing still runs in the existing worker; these bounded
file paths do not claim constant-memory behavior for the downstream indexer.

Chat uses existing `generated_tabular_outputs` cards with
`capability="file_export"`, `source_kind="workflow_saved_output"` and
`row_source="saved_records"`. Cards and history expose authorized, allowlisted
file metadata rather than raw bindings, internal locators or Blob URLs.
They identify a generic file export, not a native Analyze result.

Already-published copies remain governed by their independent destination
permissions. Source revocation prevents further private-source reads or
republication; it does not delete completed copies or replace their ACLs.

## Implementation files

Backend modules remain under `application\single_app\`:

| Files | Responsibility |
| --- | --- |
| `functions_generated_file_exports.py` | Shared typed request, records-source protocol, exact renderer and managed stream. |
| `functions_workflow_artifacts.py` | Workflow source authorization, representation identity and journal-backed materialization. |
| `functions_generated_artifact_sources.py` | Native/generic source dispatch and safe history projection. |
| `functions_personal_workflows.py`, `functions_workflow_definitions.py`, `functions_workflow_flow.py`, `functions_workflow_editor.py` | Publication normalization, compilation and server-advertised capabilities. |
| `functions_workflow_runner.py` | Source-specific dispatch into the shared export and existing publication/completion path. |
| `functions_simplechat_operations.py`, `functions_artifact_publication.py` | Existing private file transport, destination ledger, approval and stream-capable processing handoff. |
| `route_enhanced_citations.py`, `route_backend_conversation_export.py` | Existing authorized artifact download and conversion boundaries. |

In `application\v2_ui\src\`, `components\workflows\WorkflowEditorDialog.tsx`,
`lib\workflowEditor.ts` and `lib\workflowFlow.ts` own the source controls,
capability guards and typed binding validation. No new browser transport or
external runtime asset is needed.

## Usage

1. Produce and validate a records output. For per-document work, use For each
   and a real Collect node to retain each eligible saved record; a later task
   binds to Collect rather than the last child to finish.
2. In a later V2 List task, enable **Publish a workflow file**, choose
   **Saved workflow output**, and bind the exact required records output.
   **Existing Analyze file** remains the choice for a previously generated
   native analysis artifact.
3. Use **JSON - exact saved records** and choose the destination explicitly.
   A group/public copy still requires the existing destination review.
4. Choose the completion level for the downstream need. **Submitted** confirms
   handoff, **Approved** confirms destination approval where required, and
   **Indexed and ready** requires native original-content processing,
   screening availability and the complete scoped index proof.
5. Inspect the exact run/attempt and generated-file card. Download the file
   through the existing authorized action; keep later data-processing tasks
   bound to saved records rather than scraping the file card.

For example, a document loop can Analyze each frozen document, Collect its
records, optionally select those records through a branch join, and Publish
the exact JSON. Rendering neither reruns the analysis nor indexes source
results merely to pass them to the publisher.

Personal **Approved** reports approval as `not_required` at confirmed
submission. Queued or approved is not indexed-ready, and a valid empty array
does not prove searchable content. An already-fulfilled completion snapshot
stays immutable; current authorization is checked separately. Uncertain effects
pause on the existing receipt, while permission failures remain distinct.
Resume and continue-on-error cannot convert an unmet policy into success.
See [Workflow publication completion](WORKFLOW_PUBLICATION_COMPLETION.md).

New publication controls default to Submitted only when supported by the
server. Omitted completion policies keep their prior behavior. Source choice
does not silently add a policy or change existing native definitions.

## Format direction in the same framework

Only JSON is enabled for this generic saved-record source. Existing response,
native Analyze and message exporters keep their supported combinations,
including XML. Follow-on formats require explicit mappings in the **same
Generated File Export Framework**, not separate workflow exporters:

| Format | Generic saved-record status and intended mapping |
| --- | --- |
| JSON | Implemented as `exact_records_v1`; additional typed representations remain future work. |
| CSV | Future: declared columns/row unit, nested-value and null rules, formula safety and coverage semantics. |
| Markdown | Future: an explicit report/content projection that does not replace saved engine data. |
| Word/DOCX | Future: shared document layout/content mapping with large-output bounds and the same artifact transport. |
| PDF | Future: shared document layout/content mapping with explicit renderer limits. |
| PowerPoint/PPTX | Future: a declared slide/content mapping. Existing message presentation export is not yet a generic saved-record renderer. |
| XML | Future for this source: explicit schema/field mapping; existing native/generated XML support is unchanged. |

See the [shared format matrix](GENERATED_FILE_EXPORT_FRAMEWORK.md#shared-format-roadmap)
for existing paths. A future orchestration knowledge -> reasoning -> output
phase should use this same source/renderer/transport boundary. This slice adds
neither an orchestration output capability nor automatic report or slide
generation. Human-readable projections must keep the original records durable.

## Testing and validation

The regression suites for this slice target the following contracts; this list
does not report a completed test run:

| Suite | Coverage to validate |
| --- | --- |
| `functional_tests\test_generated_file_saved_record_exports.py` | Deterministic complete JSON, nested values, duplicates, byte/count limits, unsupported values and shared-renderer compatibility. |
| `functional_tests\test_workflow_saved_output_artifacts.py` | Exact attempt/source binding, both result stores, private transport, immutable preparation/recovery, digest checks and access revocation. |
| `functional_tests\test_workflow_collect_publication.py` | Real frozen loop/native Analyze/Collect/join and non-Analyze records through the shared framework and existing publication/completion service. |
| `ui_tests\test_v2_workflow_saved_output_publication.py` | Source choices, eligible record bindings, JSON-only behavior, save/reopen, omitted/unsupported compatibility and local V2 authoring. |

The existing native loop fixture, M4C-1 completion suites, structured
publication, generated-artifact authorization and download-byte tests remain
regression boundaries. Run from the repository root with the repository's
test dependencies and a locally built V2 bundle for browser fixtures:

```powershell
python -m pytest .\functional_tests\test_generated_file_saved_record_exports.py .\functional_tests\test_workflow_saved_output_artifacts.py .\functional_tests\test_workflow_collect_publication.py
python -m pytest .\functional_tests\test_workflow_structured_publication.py .\functional_tests\test_workflow_publication_completion.py .\functional_tests\test_publication_native_processing.py .\functional_tests\test_chat_artifact_download_bytes.py
python -m pytest .\ui_tests\test_v2_workflow_saved_output_publication.py .\ui_tests\test_v2_workflow_publication_completion.py
```

Fixtures use closed service doubles, fictional data and local UI assets. They
do not publish documents to live workspaces or establish deployment acceptance.

## Limits and stopping boundary

- Existing record-tree, result/artifact size, model/context, admission, retry,
  depth and elapsed-deadline limits remain enforced. No silent truncation or
  unsafe context splitting is introduced.
- Loop and saved-record report runners remain locally metered. For each
  defaults to **500 actual selected items**; administrators can set **1-5,000**
  for new runs only. A searchable corpus is not itself a loop selection.
- The owner-deferred cumulative run-token/spend cap is not implemented here.
- Repeat until is added separately in **0.261.120** and reuses this exact source
  and publication contract. M5A read-only Flow and M5B accessible visual
  authoring remain separate future slices. This feature adds no automation of
  those steps, new scheduler, promotion service, or destination ledger.
