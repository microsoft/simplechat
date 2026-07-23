# Universal CSV Generation

Implemented in version: **0.250.072**

GitHub issue: [#1071](https://github.com/microsoft/simplechat/issues/1071)

Related config.py update: `VERSION = "0.250.072"`

## Overview

CSV is a shared response-output capability rather than a CSV/XLSX-only feature. When a user requests CSV and a response contains valid structured rows, SimpleChat creates one downloadable CSV artifact through the existing authorized chat-artifact contract.

CSV is the durable tabular renderer in the broader [Generated File Export Framework](GENERATED_FILE_EXPORT_FRAMEWORK.md). The framework can also render DOCX and PDF artifacts from final responses and current-turn structured function results.

The finalizer is source-neutral. Native evidence adapters continue to handle PDF, Office, text, image/media-derived, CSV, XLSX, and mixed-source evidence; once a response has a valid Markdown table, tab-separated table, or CSV-shaped result, the same CSV artifact path is used.

## Purpose

Previously, natural requests such as "turn these into a single CSV" could miss the shared intent detector, and workflow replies did not pass through the assistant-table artifact finalizer. Analyze and Compare could also replace a structured analysis response with a concise existing-artifact message before CSV finalization.

This implementation gives ordinary Chat, streaming Chat, Chat Search, selected agents, Analyze, Compare, workflows, and source-free prompts the same final structured-response CSV contract.

## Dependencies

- `functions_assistant_table_exports.py` for CSV intent detection, structured-row parsing, formula protection, duplicate suppression, and authoritative document-action reply selection
- `functions_simplechat_operations.py` for owner-authorized chat artifact uploads and downloads
- `functions_tabular_generated_exports.py` for shared row batching, durable queueing, checkpoints, cancellation, reauthorization, and final artifact publication
- Existing mixed-source manifest and evidence-envelope contracts for selected-source authorization and coverage semantics
- Azure Cosmos DB `tabular_export_runs` and personal chat blob storage for oversized exports

## Technical Specifications

### Unified Intent and Structured Rows

The shared intent detector recognizes direct CSV requests plus natural variants including `single CSV`, `combined CSV`, and `one CSV`. It excludes negated requests and prompts that merely discuss an input CSV.

The exporter accepts valid structured response forms:

- Markdown tables
- Tab-separated tables
- CSV, including quoted commas, multiline values, and escaped quotes
- CSV-shaped output in supported fenced blocks

Every generated CSV uses safe headers and neutralizes spreadsheet formula-like values while preserving signed numeric text.

Successful current-turn structured function results are also accepted through the generated file export framework when the assistant summarizes an action rather than reproducing its rows. Sensitive fields are excluded, merged action rows carry source provenance, and tabular-plugin results remain on the existing coverage-aware tabular export path.

### Row and Schema Clarification

For an ambiguous CSV request, Chat and workflow model/agent prompts direct the assistant to ask exactly one concise question before generating a file: whether each row represents files, documents, or extracted records, and which columns to include. The assistant response is persisted in the conversation, so the next user turn can answer the clarification without a separate temporary state store.

Explicit instructions such as `one row per document` or `columns: file name, amount` bypass that clarification. When native evidence already establishes a clear structured result, the assistant proceeds directly to valid rows and the downloadable CSV.

### Response Path Finalization

The common finalizer runs after the response is complete in:

- Standard and streaming Chat, including Chat Search and selected agents
- Analyze and Compare document actions
- Personal and group workflow assistant messages
- Source-free prompts that return valid structured rows

For Analyze and Compare, the finalizer prefers `analysis_result.analysis_reply` over a concise `reply` that may only describe a separately generated artifact. That ensures a valid structured result remains exportable without changing the user-visible response.

### Evidence, Coverage, and Source Types

CSV finalization does not retrieve or infer source data itself. It consumes only valid rows already produced by the native evidence path. This keeps source authorization, revision handling, and selected-source coverage in the existing mixed-source orchestration layer.

Explicit selections remain authoritative upstream. A generated CSV cannot silently invent unprocessed source rows: if native evidence is partial, failed, unsupported, unresolved, canceled, or revision-changed, the response coverage contract remains responsible for disclosing that state. The CSV serializer only writes validated structured rows supplied to it.

### Immediate and Durable Artifacts

Small result sets upload immediately through the generic chat artifact uploader. The uploader verifies that the conversation is owned by the workflow/chat user before writing the blob-backed file message.

Large assistant-rendered tables use the existing durable tabular export queue:

1. Rows are batched with the shared row and character budget.
2. The queue stages passthrough rows, so it does not call a model again to serialize an already validated table.
3. The worker reauthorizes conversation ownership before processing.
4. The staged-chat source uses `source: chat` without pretending that staged rows are an external source blob.
5. The existing progress card exposes status, cancellation, retry/resume, and final authorized download behavior.

### Configuration

The durable threshold and batch settings are shared with tabular exports:

- `enable_tabular_generated_output_background_exports`
- `tabular_generated_output_inline_max_rows`
- `tabular_generated_output_inline_max_batches`
- `tabular_generated_output_max_batch_rows`
- `tabular_generated_output_max_batch_chars`

## File Structure

- `application/single_app/functions_assistant_table_exports.py`
- `application/single_app/functions_tabular_generated_exports.py`
- `application/single_app/route_backend_chats.py`
- `application/single_app/functions_workflow_runner.py`
- `functional_tests/test_assistant_table_csv_artifact.py`
- `functional_tests/test_tabular_row_orchestration_scale.py`

## Usage

Users can request a CSV in natural language, for example:

- `Turn these into a single CSV.`
- `Save one CSV with the extracted invoice fields.`
- `Create a combined CSV from the selected sources.`

When the response contains valid structured rows, the chat displays the downloadable CSV artifact. Large results display the existing background-export status card until the authorized artifact is published.

When the requested row unit or columns are unclear, the assistant asks one clarification in the conversation. Reply with the desired row unit and columns, then the normal CSV finalization path creates the artifact from the resulting structured response.

## Testing and Validation

- `functional_tests/test_assistant_table_csv_artifact.py` validates intent variants, non-tabular response parsing, Analyze/Compare structured-reply selection, workflow artifacts, duplicate suppression, formula safety, and immediate/background paths.
- `functional_tests/test_tabular_row_orchestration_scale.py` validates durable row contracts, worker reauthorization, staged-chat authorization, cancellation, recovery, and idempotent publication.
- `functional_tests/test_tabular_background_generated_exports.py` validates queue, status, and browser-contract wiring.

## Performance Considerations

- Small tables avoid queue overhead and upload immediately.
- Large tables use the existing bounded row/character batch budget and checkpointed durable worker.
- Passthrough batches avoid duplicate model inference and preserve the validated row order.
- Worker reauthorization uses compact identifiers and does not log source row contents.

## Known Limitations

- A CSV artifact requires parseable structured rows. Prose-only model output does not produce an empty or fabricated CSV.
- Clarification state is represented by the persisted assistant conversation message rather than a separate job or schema-state container.
- Native evidence adapters and mixed-source coverage are intentionally retained as their existing specialized contracts. This feature finalizes their valid structured response output rather than replacing retrieval, document analysis, or source orchestration.
