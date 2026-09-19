# Generated File Export Framework

Implemented in version: **0.250.072**

Updated through version: **0.261.119**

GitHub issue: [#1071](https://github.com/microsoft/simplechat/issues/1071)

Related config.py update: `VERSION = "0.250.072"`

Saved-record source adapter implemented in version: **0.261.119**, tracked in
`application\single_app\config.py`.

## Overview

Generated file output is a shared representation capability. The existing response path accepts the completed assistant response and successful structured function results from the same turn, selects a requested renderer, and publishes an authorized downloadable chat artifact. Since **0.261.119**, an explicit typed source path also renders authorized saved workflow records without asking a model to recreate them.

CSV, JSON, XML, Word (`.docx`), and PDF are renderer capabilities within this framework, not independent export systems. Producer-specific source adapters share renderer dispatch, artifact transport, authorized downloads, and existing workspace publication. Supported source/format combinations remain explicit: the new generic saved-record adapter supports exact JSON only.

## Purpose

Function results previously remained available as citations, while downloadable output depended on the model reproducing those rows in its final response. That made an action that returned structured data less reliable as an export source than a manually formatted assistant table.

The framework normalizes current-turn structured function results once and makes them available to every supported renderer. CSV remains the first durable renderer; DOCX and PDF provide immediate generated artifacts for supported response-sized outputs.

Saved workflow data, a rendered file, and a published workspace document serve
different purposes. Typed bindings pass durable data to later tasks without
exporting or indexing it. A file is a representation of selected data; workspace
publication is a separate, explicit destination operation. Rendering does not
replace original records, gather missing evidence, or decide workflow control flow.

## Dependencies

- `functions_generated_file_exports.py` for output intent, structured function-result normalization, renderer dispatch, and artifact metadata
- `functions_workflow_artifacts.py` and the existing authorized workflow record reader for the exact saved-record source adapter and durable materialization checkpoints
- `functions_generated_artifact_sources.py` for shared source-authorization dispatch across publication, downloads, previews, history, and conversion
- `functions_assistant_table_exports.py` for CSV intent, table parsing, safe headers, and formula-injection protection
- `functions_simplechat_operations.py` for authorized generated chat-artifact upload, download, promotion, and rollback
- `functions_tabular_generated_exports.py` for durable CSV batching, checkpoints, cancellation, reauthorization, and publication
- `python-docx` for DOCX rendering and PyMuPDF for PDF rendering

## Technical Specifications

### Supported Renderers

- **CSV**: Renders structured rows with safe headers, formula neutralization, quoted/multiline values, and durable background execution when the existing row or batch threshold is exceeded.
- **JSON**: Persists a valid generated JSON payload as a concise completed artifact with `Download JSON`, `View JSON`, and workspace-promotion actions.
- **XML**: Persists one hardened, well-formed XML document as a concise completed artifact with `Download XML`, `View XML`, and workspace-promotion actions.
- **DOCX**: Renders a titled document with final assistant content and, when present, a structured function-result table.
- **PDF**: Renders a titled PDF with final assistant content and, when present, a structured function-result table.

The response request selects the format through natural language such as `create a CSV`, `create a Word document`, or `export to PDF`.

### Function Result Source Contract

Only function results from the current completed response are considered. The adapter:

- accepts successful citation payloads in conventional `rows`, `data`, `items`, `results`, `records`, `value`, `values`, `result`, `body`, `output`, or `payload` envelopes
- supports a row-like result object when no envelope is present
- parses JSON-string payloads when they contain structured values
- defensively excludes sensitive key names and secret-like fields even after plugin invocation sanitization
- labels merged rows with their originating action when more than one action contributes rows
- ignores `TabularProcessingPlugin` results so CSV/XLSX rows continue through the existing coverage-aware, revision-aware tabular export path

A valid assistant-rendered table takes precedence over function-result rows for CSV. For DOCX and PDF, the final assistant response is included alongside normalized function-result tables.

### Explicit Saved-Record Source Contract

The typed branch of the existing `build_generated_file_export` entry point
accepts these shared contracts:

| Contract | Responsibility |
| --- | --- |
| `GeneratedFileExportRequest` | Explicit `profile="exact_records_v1"` and `output_format="json"`; no natural-language format detection or unsupported-format fallback. |
| `GeneratedRecordExportSource` | A records source with its exact `record_count`, `iter_records()` and authorization/integrity `recheck()`. |
| `GeneratedFileExportStream` | A managed seekable file stream with format, media type, byte size, SHA-256, record count and profile; closing it releases temporary storage. |

The caller supplies `max_output_bytes` and a cancellation/lease `check`
callback. The workflow adapter wraps the existing authorized reader for an
exact committed task, Collect, or explicit join output. It does not make a
Collect node pretend to be an Analyze task.

The output is one JSON array of **every selected saved record object**, in
reader order, including nested values and retained provenance. Unlike native
Analyze formatting, it does not project just `record["values"]`. Unlike the
current-turn action adapter, it does not infer envelopes, choose preview rows,
filter arbitrary saved fields, or reconstruct data from a summary. Existing
action-result sanitization remains unchanged.

Encoding uses sorted object keys, compact separators, ASCII escaping and
finite JSON values (`allow_nan=False`), without `default=str`, a BOM or generated
commentary. Null, false, zero, nested arrays/objects, empty collections, long
strings and repeated equal records are retained. This preserves JSON values,
not the lexical formatting of an original uploaded file.

Serialization reads the complete paged source into quota-bounded temporary
storage without building a whole-collection list or string. SHA-256 and size
are calculated from actual encoded bytes, including delimiters and escaping.
A count mismatch, unsupported value, lost authority, cancellation or size
overflow fails instead of exposing a truncated file. Accepted partial sources
require explicit producer and consumer permission and remain visibly partial;
declared uniqueness violations remain invalid rather than being deduplicated.

See [Saved workflow output publication](WORKFLOW_SAVED_OUTPUT_PUBLICATION.md)
for eligibility, source identity, recovery and destination behavior.

### Shared Format Roadmap

Existing renderers do not imply that every source can use every format.
M4C-2 adds one exact saved-record representation; the other generic mappings
below are **future extensions of this same framework**, not implemented
workflow exporters.

| Format | Existing support | Generic saved records in M4C-2 | Intended shared-framework extension |
| --- | --- | --- | --- |
| JSON | Generated-payload and native saved-Analyze paths. | Exact streamed array of selected saved record objects. | Additional explicitly typed source representations. |
| CSV | Response/action tables and native tabular paths. | Not enabled. | Explicit columns and row unit, nested-value/null rules, formula safety and coverage semantics. |
| Markdown | Native saved-Analyze/report and message export paths. | Not enabled. | Declared report/content mapping; prose must not become engine state or replace original data. |
| Word/DOCX | Generated-response, native Analyze and message document renderers. | Not enabled. | Shared document layout/content mapping, large-output bounds and consistent transport. |
| PDF | Generated-response, native Analyze and message document renderers. | Not enabled. | Shared document layout/content mapping with explicit renderer limits. |
| PowerPoint/PPTX | Existing message/conversation presentation export, outside the generated-file dispatcher. | Not enabled. | A declared slide/content mapping through the shared output contract, not a parallel workflow exporter. |
| XML | Existing shared generated-payload and native Analyze paths. | Not enabled. | Explicit schema/field mapping if generic saved-source support is added. |

Human-readable layouts are projections, not a promise that every record shape
can be represented losslessly in every format. Original saved records remain
durable. Existing XML and native formats keep their behavior; this slice does
not migrate the separate presentation exporter or enable its use for arbitrary
saved records.

The same boundary is intended for future orchestration:
**authorized source adapter -> explicit shared renderer -> existing private
artifact transport -> optional existing workspace publication**. Knowledge and
reasoning supply data or approved content; an output phase would render it.
No orchestration output capability is added here. See
[Chat Orchestration](CHAT_ORCHESTRATION.md#outputs).

### Response Paths

The same finalizer is invoked after:

- standard Chat and streaming Chat
- selected agents and action/tool calls
- Chat Search
- Analyze and Compare document actions
- direct-model and agent workflows
- source-free model responses

Each response path supplies the final assistant content plus its current-turn function citations. The framework does not read arbitrary historical citations or externally supplied action identifiers. Explicit saved-output workflow publication instead supplies the typed source and request above; its behavior does not depend on model phrasing.

### Artifact Publication

The existing generated chat-artifact uploader remains the shared file transport. It validates conversation ownership, allowed output extension, content size, and artifact metadata before creating a blob-backed file message. Workspace copies use the existing publication service and its destination receipt ledger.

Generated artifacts retain their format, capability, summary, preview metadata, and source provenance. The existing authorized download and workspace-promotion routes work without a new browser transport or external runtime asset.

Completed CSV, JSON, and XML file-export cards omit inline payloads and supporting diagnostics. They show the generated filename and row count when available, followed by format-specific Download and View actions plus Add to Workspace. View renders only bounded artifact preview metadata in a modal; the full file is read only by Download.

Saved-record files use existing `generated_tabular_outputs` cards with
`capability="file_export"`, `source_kind="workflow_saved_output"` and
`row_source="saved_records"`. Public metadata excludes raw source bindings and
Blob URLs. The server-only `generated_artifact_source` binding is checked for
publication, preview, history and conversion as well as download. The existing
`/api/chat_artifacts/download` path verifies the complete saved-output file in
temporary storage before sending response bytes.

For this typed source, materialization uses a stable source/representation key,
create-only Blob/file-message writes and immutable prepare/ready units in the
existing workflow journal. Retries verify the same address and actual digest;
uncommitted materializations are not readable. This is not a second publication
ledger. Cosmos-backed and Blob-backed workflow results both use the existing
private Blob transport for generated files.

During response-path streaming JSON/XML generation, the browser receives one server-authored status such as `Generating the XML file. It will appear here when ready.` The model payload is accumulated privately for validation and publication rather than rendered token by token. If artifact publication cannot complete, finalization falls back to the accumulated model response instead of leaving the temporary status in place. This legacy response fallback does not apply to explicit saved-record exports.

Structured artifact intent is normalized once for Chat, document Analyze, and workflow output selection. Destination phrasing such as `put the PDF content into the XML`, `place these fields in an XML document`, or `write these records as JSON` selects the existing artifact generation path without requiring words such as `create`, `download`, `file`, or `populate`. Source-only mentions such as `summarize the selected XML` and explicitly negated generation requests do not select an output artifact.

## Usage

Examples:

- `Ask the billing action for invoices and save the action results as one CSV.`
- `Create a Word document from the action results.`
- `Export the agent's findings to PDF.`
- `Create a PDF report from this response.`

When an action returns structured data and the assistant summarizes it instead of reprinting a table, the requested generated file still receives the normalized rows. If a request is ambiguous only for CSV row granularity or columns, the assistant asks the existing single conversation clarification before finalization.

For a version-3 durable workflow, explicitly choose **Saved workflow output**
as the publication source and bind one required records output. **JSON - exact
saved records** produces the downloadable file and submits it to the task's
chosen destination. This is not a new download-only task mode. Omitting
`publication.source_kind` retains existing native Analyze publication.

## Testing and Validation

- M4C-2 regression targets are `functional_tests\test_generated_file_saved_record_exports.py` for exact encoding/counts/quotas, `functional_tests\test_workflow_saved_output_artifacts.py` for source binding and materialization recovery, and `functional_tests\test_workflow_collect_publication.py` for the shared renderer-to-publication path. See the [saved-output validation commands](WORKFLOW_SAVED_OUTPUT_PUBLICATION.md#testing-and-validation); these describe coverage, not a completed test-run result.
- `ui_tests\test_v2_workflow_saved_output_publication.py` targets source choice, typed bindings, format restrictions and compatibility through the local V2 fixture.
- `functional_tests/test_assistant_table_csv_artifact.py` covers CSV, DOCX, PDF, structured function-result normalization, sensitive-field exclusion, multi-action provenance, assistant-table precedence, and tabular-plugin exclusion.
- `functional_tests/test_generated_json_xml_exports.py` covers JSON/XML parsing, hardened XML handling, completed file-export metadata, and format-specific View actions.
- `ui_tests/test_chat_generated_tabular_output_card.py` covers concise completed cards and bounded CSV, JSON, and XML preview modals.
- `functional_tests/test_generated_json_xml_exports.py` also covers payload-only model guidance, private stream gates for agent and direct-model paths, truthful generation status, and safe failure fallback.
- The same test executes a cross-path terminology matrix for Chat, Analyze, and workflow wrappers, including destination disambiguation such as `Convert JSON to XML`.
- `functional_tests/test_mixed_source_hardening.py` covers cancellation and artifact rollback through the generic finalizer.
- `functional_tests/test_document_action_token_usage_aggregation.py` covers workflow assistant-message persistence with the shared finalizer.
- Existing durable CSV, document action, workflow, and generated-artifact tests remain part of validation.

## Performance and Limitations

- CSV retains the existing durable background path for large row sets.
- DOCX and PDF render immediately for response-sized content; durable long-form DOCX work is tracked separately in [#1072](https://github.com/microsoft/simplechat/issues/1072).
- The framework deliberately does not route tabular-plugin rows around source coverage, authorization, or source-version checks.
- Unsupported, failed, unresolved, canceled, or partial source states remain visible through their existing evidence and export contracts; the framework does not fabricate missing rows.
- Exact saved-record serialization and its shared upload, download and publication handoff avoid whole-file buffers. Native destination ingestion still uses the existing worker and format-specific indexing; this does not assert that the downstream native indexer itself has constant memory use.
- JSON file availability, destination approval and index readiness are separate facts. An empty array can be a valid export without being searchable content.
