# Generated File Export Framework

Implemented in version: **0.250.072**

Updated through version: **0.250.154**

GitHub issue: [#1071](https://github.com/microsoft/simplechat/issues/1071)

Related config.py update: `VERSION = "0.250.072"`

## Overview

Generated file output is a first-class response capability. The framework accepts the completed assistant response and the successful structured function results produced during the same turn, selects a requested renderer, and publishes one authorized downloadable chat artifact.

CSV, JSON, XML, Word (`.docx`), and PDF are separate renderer capabilities. They share source normalization, output intent detection, artifact metadata, authorization-safe publication, downloads, and workspace-promotion behavior.

## Purpose

Function results previously remained available as citations, while downloadable output depended on the model reproducing those rows in its final response. That made an action that returned structured data less reliable as an export source than a manually formatted assistant table.

The framework normalizes current-turn structured function results once and makes them available to every supported renderer. CSV remains the first durable renderer; DOCX and PDF provide immediate generated artifacts for supported response-sized outputs.

## Dependencies

- `functions_generated_file_exports.py` for output intent, structured function-result normalization, renderer dispatch, and artifact metadata
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

### Response Paths

The same finalizer is invoked after:

- standard Chat and streaming Chat
- selected agents and action/tool calls
- Chat Search
- Analyze and Compare document actions
- direct-model and agent workflows
- source-free model responses

Each path supplies the final assistant content plus its current-turn function citations. The framework does not read arbitrary historical citations or externally supplied action identifiers.

### Artifact Publication

The existing generated chat-artifact uploader remains the sole publication mechanism. It validates conversation ownership, allowed output extension, content size, and artifact metadata before creating a blob-backed file message.

Generated artifacts retain their format, capability, summary, preview metadata, and source provenance. The existing authorized download and workspace-promotion routes work without a new browser transport or external runtime asset.

Completed CSV, JSON, and XML file-export cards omit inline payloads and supporting diagnostics. They show the generated filename and row count when available, followed by format-specific Download and View actions plus Add to Workspace. View renders only bounded artifact preview metadata in a modal; the full file is read only by Download.

During streaming JSON/XML generation, the browser receives one server-authored status such as `Generating the XML file. It will appear here when ready.` The model payload is accumulated privately for validation and publication rather than rendered token by token. If artifact publication cannot complete, finalization falls back to the accumulated model response instead of leaving the temporary status in place.

Structured artifact intent is normalized once for Chat, document Analyze, and workflow output selection. Destination phrasing such as `put the PDF content into the XML`, `place these fields in an XML document`, or `write these records as JSON` selects the existing artifact generation path without requiring words such as `create`, `download`, `file`, or `populate`. Source-only mentions such as `summarize the selected XML` and explicitly negated generation requests do not select an output artifact.

## Usage

Examples:

- `Ask the billing action for invoices and save the action results as one CSV.`
- `Create a Word document from the action results.`
- `Export the agent's findings to PDF.`
- `Create a PDF report from this response.`

When an action returns structured data and the assistant summarizes it instead of reprinting a table, the requested generated file still receives the normalized rows. If a request is ambiguous only for CSV row granularity or columns, the assistant asks the existing single conversation clarification before finalization.

## Testing and Validation

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
