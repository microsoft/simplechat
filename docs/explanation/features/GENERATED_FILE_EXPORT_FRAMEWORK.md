# Generated File Export Framework

Implemented in version: **0.250.072**

Updated through version: **0.261.126**

GitHub issue: [#1071](https://github.com/microsoft/simplechat/issues/1071)

Structured/text renderer preparation: [#1509](https://github.com/microsoft/simplechat/issues/1509)

Related config.py update: `VERSION = "0.250.072"`

Saved-record source adapter implemented in version: **0.261.119**, tracked in
`application\single_app\config.py`.

Strict structured/text renderer core implemented in version: **0.261.126**,
tracked in the same `config.py`. This is a callable serialization layer, not
activation of the orchestration rendering harness.

Headless Office registry bridge implemented in version: **0.261.126**. The
shared facade can render explicit complete sources as XLSX, DOCX, PDF and PPTX;
authorized retained-result bindings are available through
`functions_orchestration_export_sources.py`. Publication and orchestration
runtime activation remain separate.

## Overview

Generated file output is a shared representation capability. The existing response path accepts the completed assistant response and successful structured function results from the same turn, selects a requested renderer, and publishes an authorized downloadable chat artifact. Since **0.261.119**, an explicit typed source path also renders authorized saved workflow records without asking a model to recreate them.

CSV, JSON, XML, Word (`.docx`), and PDF are existing response or specialized renderer capabilities within this framework, not independent export systems. Producer-specific source adapters share renderer dispatch, artifact transport, authorized downloads, and existing workspace publication.

The explicit, headless branch additionally exposes strict CSV, JSON, XML,
YAML/YML, Markdown/MD, TXT/text, XLSX, DOCX, PDF and PPTX serializers for complete typed sources.
These callable APIs do not enable new orchestration tasks, workflow format
choices, routes or UI controls. Existing saved-workflow publication remains
restricted to `exact_records_v1` JSON.

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
- `functions_generated_export_contracts.py` for import-safe source, request, limit, error and stream contracts; no route, settings or application bootstrap dependencies
- `functions_generated_export_registry.py` for the immutable format/profile declarations and JSON-safe capability catalog
- `functions_structured_file_renderers.py` for bounded explicit-source serialization, with the existing facade as its entry point
- `functions_generated_office_adapters.py` for complete-reader adaptation and the strict prepared-deck JSON mapping
- `functions_office_file_renderers.py` for the existing headless workbook, report and explicitly positioned slide services; the bridge does not alter this helper
- `functions_workflow_artifacts.py` and the existing authorized workflow record reader for the exact saved-record source adapter and durable materialization checkpoints
- `functions_generated_artifact_sources.py` for shared source-authorization dispatch across publication, downloads, previews, history, and conversion
- `functions_assistant_table_exports.py` for CSV intent, table parsing, safe headers, and formula-injection protection
- `functions_simplechat_operations.py` for authorized generated chat-artifact upload, download, promotion, and rollback
- `functions_tabular_generated_exports.py` for durable CSV batching, checkpoints, cancellation, reauthorization, and publication
- `functions_xsd_schema.py` for closed schema-graph compilation and final-byte validation when an XSD is explicitly selected
- `python-docx` for DOCX rendering and PyMuPDF for PDF rendering
- The existing pinned `pyyaml==6.0.2` dependency for safe YAML serialization; no new dependency is needed
- The existing pinned `jsonschema==4.25.1` dependency for request options and prepared-deck validation; no manifest changes are needed
- The existing `openpyxl`, `python-pptx`, `markdown2`, Beautiful Soup and Pillow dependencies for headless Office work

## Technical Specifications

### Existing Response and Specialized Renderers

- **CSV**: Renders structured rows with safe headers, formula neutralization, quoted/multiline values, and durable background execution when the existing row or batch threshold is exceeded.
- **JSON**: Persists a valid generated JSON payload as a concise completed artifact with `Download JSON`, `View JSON`, and workspace-promotion actions.
- **XML**: Persists one hardened, well-formed XML document as a concise completed artifact with `Download XML`, `View XML`, and workspace-promotion actions. When a ready XSD is explicitly selected, generic XML publication is suppressed and the complete final bytes must validate against that schema before upload.
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

### Explicit Complete-Source Contracts

The typed branch of the existing `build_generated_file_export` entry point
accepts these shared contracts:

| Contract | Responsibility |
| --- | --- |
| `GeneratedFileExportRequest(output_format, profile="exact_records_v1", columns=None, title=None, sheet_name=None)` | An explicit format/profile. Existing constructor arguments retain their meaning. Options are accepted only by the profiles that declare them; no prompt parsing, filename inference or unsupported-format fallback. |
| `GeneratedRecordExportSource` | The unchanged `kind="records"`, exact `record_count`, `iter_records()` and authorization/integrity `recheck()` protocol. Each yielded item is a complete record object. |
| `GeneratedStructuredValueExportSource` | `kind="structured_value"`, `readiness`, `read_value()` and `recheck()`. Reads one complete, bounded JSON-domain value, including a scalar, list or object. |
| `GeneratedTextExportSource` | `kind="text"` or `"markdown"`, `readiness`, exact Unicode `character_count`, `iter_text()` yielding strings, and `recheck()`. No implicit conversion between plain text and Markdown. |
| `GeneratedFileExportReadiness` | `state="ready"`, `is_complete=True`, `is_preview=False`. Other states, partial data and previews are rejected, including when readiness changes during rendering. |
| `GeneratedFileExportStream` | An owned, rewound binary stream plus canonical `output_format`, `file_extension` (without a dot), media type, exact byte size, SHA-256, profile and source kind. `record_count` is zero for non-record sources; text also has `character_count`. Office results add safe count/layout `metadata` and the underlying `renderer_profile`. |

The contracts are re-exported from `functions_generated_file_exports.py`.
Storage/result-reader implementations may depend on the lower-level contracts
without importing renderers or application configuration. They must provide
complete authorized snapshots, not a query, prompt, bounded preview or storage
handle for the renderer to resolve.

Existing records adapters need not add a `readiness` attribute: their existing
`recheck()` remains responsible for eligibility and completeness. If they
expose `readiness`, it must satisfy the explicit complete-source contract.
New structured-value and text adapters must expose it. This does not change
the existing workflow reader's producer/consumer partial-result policy, and
does not introduce a new partial-result export profile.

The caller must supply a positive integer `max_output_bytes`. An optional
`check` callback raises on cancellation, lost lease or superseded execution.
Both execution checks and source `recheck()` run before reads, during bounded
serialization, and immediately before returning the stream. A callback's
authorization/cancellation exception propagates unchanged. Readers must not
refresh or query a different source revision during a recheck.

Rendering does not gather missing evidence, filter arbitrary fields, infer
record envelopes, drop provenance, deduplicate records or stringify arbitrary
Python objects. It performs no model calls, upload, publication, application
configuration initialization or source re-query. The existing response,
Analyze, Compare, native, message-export and workflow paths retain their own
behavior.

See [Saved workflow output publication](WORKFLOW_SAVED_OUTPUT_PUBLICATION.md)
for eligibility, source identity, recovery and destination behavior.

### Callable Format and Profile Catalog

`get_generated_file_export_catalog()` returns fresh JSON-safe declarations:
canonical format IDs, explicit aliases, extension/media type, renderer version,
profiles and compatible source kinds, supported/required options, JSON
`options_schema` and logical `input_schema`, default
limits, dependencies, streaming support and deterministic failure codes.
It is a serialization catalog, **not** permission to advertise an executable
orchestration capability. The workflow admission constant
`GENERATED_RECORD_EXPORT_FORMATS` remains unchanged.

| Canonical format / aliases | Profile | Source kinds | Representation |
| --- | --- | --- | --- |
| `json` | `exact_records_v1` (unchanged default) | `records` | Compact array, sorted object keys, ASCII escaping, finite JSON values. Byte-compatible with the existing exact-record serializer for supported input. |
| `json`, `yaml` / `yml` | `structured_records_v1` | `records` | Complete array/sequence, record and object insertion order, nested values and JSON-domain types preserved. |
| `json`, `yaml` / `yml` | `structured_value_v1` | `structured_value` | One complete JSON-domain value, preserving object insertion order. |
| `csv` | `tabular_records_v1` | `records` | Explicit ordered columns, matching scalar-only records and formula-safe headers/cells. |
| `xml` | `typed_xml_v1` | `records`, `structured_value` | A fixed typed XML vocabulary that preserves keys, nested values and scalar distinctions. |
| `md` / `markdown` | `prepared_text_v1` | `markdown` | Prepared Markdown bytes; no hidden composition or rich-document conversion. |
| `txt` / `text` | `prepared_text_v1` | `text` | Prepared plain text bytes. |
| `xlsx` | `tabular_workbook_v1` | `records` | One explicitly named sheet, ordered columns and streaming scalar records. Required options: `columns`, `sheet_name`. |
| `docx`, `pdf` | `prepared_report_v1` | `text`, `markdown` | The same complete prepared report, with literal text or supported Markdown semantics according to source kind. Optional `title`. |
| `pptx` | `prepared_slide_deck_v1` | `structured_value` | Versioned prepared-slide JSON with positioned shapes. No request options; deck title/size belong to the prepared JSON. |

Aliases return the same bytes and **canonical** extension/format metadata.
IDs are case-sensitive and do not accept leading dots or whitespace.
For example, `yml` intentionally resolves to `yaml`; `JSON` and `.json` fail.
An explicit `csv` request with the default JSON-only `exact_records_v1`
profile fails instead of changing profiles silently.

JSON and YAML accept only built-in dictionaries with string keys, lists,
strings, finite numbers, booleans and null. Tuples, sets, dates, custom objects,
cycles, non-string keys and non-finite floats fail. The newer profiles require
valid Unicode; the legacy ASCII-escaped JSON profile retains its existing
string escaping behavior. YAML uses a safe dumper, preserves string/numeric
distinctions on safe readback, disables aliases, and emits one document without
Python object tags.

CSV is an explicit presentation profile, not a lossless typed interchange.
Every row must contain exactly the requested columns; missing/extra fields
and nested cells fail instead of being silently omitted or flattened. Columns
must be nonempty and have distinct case-insensitive, formula-safe headers.
Declared spelling, whitespace and order are preserved apart from necessary
formula neutralization. Null becomes an empty cell, booleans become `true` or
`false`, and numbers retain JSON numeric spelling. Strings retain their
contents, including leading zeroes, commas, quotes, multiline content and
Unicode. The existing formula-cell policy prefixes dangerous strings with an
apostrophe while retaining signed numeric strings. CSV uses UTF-8 without an
added BOM and standard quoted cells with CRLF record separators.

XML never derives tag names from arbitrary field names. A records document
uses a `records` root containing `record` elements; a single structured value
uses a `value` root. Values are represented by `object`, `array`, `string`,
`integer`, `number`, `boolean` and `null` elements. Objects contain
`member name="original key"` elements and arrays contain `item` elements.
This distinguishes null from an empty string, false from zero, and a numeric
identifier from a string identifier without colliding sanitized key names.
XML metacharacters and attribute whitespace are escaped; carriage returns
round-trip. XML 1.0-invalid characters fail. Arbitrary XML templates, DTDs,
entities, namespaces and custom mappings are not accepted by this profile.
The existing schema-bound/native XML path is unchanged.

Prepared text is copied as UTF-8 without newline normalization, trimming,
markup interpretation or an added BOM. Counts are Unicode characters, not
UTF-8 bytes. Empty text is valid. Rendering Markdown does not make its contents
safe to insert into browser HTML; existing browser sanitization boundaries
still apply.

### Headless Office Profiles

The Office bridge uses only the explicit source methods above. It never calls
`preview()`, falls back to `read_text()`, queries a source again, or imports the
legacy conversation-export route.

For XLSX, pass `columns` as an ordered tuple/list of public field-name strings
and an explicit `sheet_name`. The adapter supplies one streaming
`PreparedSheet` to `render_prepared_xlsx`; it does not construct a list of all
rows. Every record must have exactly the declared keys. Strings, finite numeric
values, booleans and null are supported. Formula-looking strings and headers
are literal Excel text, without the CSV profile's protective apostrophe.
Date-shaped strings stay strings; native date objects and nested cells fail
instead of being guessed or flattened.

Excel limits remain binding. Integers beyond 15 decimal digits, negative zero,
and floats that cannot retain their value at 15 significant decimal digits
are rejected rather than rounded. Excel has one numeric cell type: an integral
float may read back as an integer with the same numeric value. Use exact JSON
when that distinction or a wider numeric domain matters. Empty records produce
the declared header row. There is no automatic sheet splitting or additional
sheet mapping in `tabular_workbook_v1`.

DOCX and PDF share `PreparedReport`. The source kind determines whether content
is literal plain text or supported Markdown; a request cannot silently
reinterpret plain text as Markdown. Optional `title` is a string of at most
255 characters. The adapter accumulates UTF-8 in a bounded buffer, verifies the
exact Unicode character count and input byte quota, and only then constructs
the report. A complete empty report is valid.

The headless report helper preserves its supported headings, paragraphs,
nested lists, rectangular tables, code, quotes, links/citations and images.
Unsupported markup fails rather than being stripped. Word/PDF layout,
pagination and rendering limits remain the helper's responsibility; the
bridge does not substitute a paragraph-only legacy renderer.

Optional `image_resolver` is a **server-injected callable**, separate from
`GeneratedFileExportRequest`. It receives only opaque `asset:<id>` references
and returns authorized PNG/JPEG bytes. IDs start with an ASCII letter/digit and
contain at most 128 letters, digits, dots, underscores or hyphens. URLs,
filesystem paths and client-supplied callbacks are not resolver inputs.
Absent a resolver, an unresolved reference fails; nothing is fetched.
Reports retain the helper's support for bounded inline PNG data already
present in prepared content. PPTX JSON accepts opaque asset references only,
not inline bytes, data URLs or an `images` map. Image bytes and access are checked
by the injected resolver and headless helper, not trusted from a model handle.

### Prepared Slide JSON Contract

Composition can obtain the exact schema through
`get_prepared_slide_deck_schema()` or the PPTX catalog profile's `input_schema`.
`prepare_generated_slide_deck(value, limits=None, office_limits=None, check=None)`
in `functions_generated_office_adapters.py` validates that JSON and returns a
typed `PreparedDeck` without creating a file. A Reason producer can validate
before persisting its original JSON snapshot; the renderer consumes that
complete value through `read_value()` exactly once.

The root requires `schema_version="prepared_slide_deck_v1"`, `slide_count` and
`slides`. Optional root fields are `title` and `size` (`wide`, the default, or
`standard`). The declared count must equal the nonempty slide array. All objects
reject unknown fields, including model-supplied completeness flags or image
storage maps.

Each slide requires `layout`, `title` and `shapes`, with optional literal
`notes`. Layouts are `title_and_content` (nonempty title) and `blank` (empty
title). A `box` always has numeric `left`, `top`, `width`, `height` in inches;
width and height must be positive. Boxes must fit the slide and not overlap.
Title layout reserves `(0.5, 0.25, slide_width - 1, 1)` for its title.
Wide slides are 13 1/3 by 7.5 inches; standard slides are 10 by 7.5 inches.

| Shape discriminator | Required fields | Optional fields and defaults |
| --- | --- | --- |
| `text_box` | `box`, nonempty `paragraphs` | `font_size=18`, allowed 8-40 points |
| `table` | `box`, nonempty rectangular `rows` of literal strings | `header=true`, `font_size=12`, allowed 8-32 points |
| `image` | `box`, opaque `source` | `alt=""` |

A paragraph requires literal `text`; optional fields are `list_kind`
(`none`, `bullet`, `number`), `level` (0-8; zero for `none`), `bold`, `italic`
and `url`. Styling defaults to no list, level zero, false booleans and no URL.
Links must satisfy the helper's HTTP/HTTPS/mailto policy; they are not fetched.
No chart, arbitrary HTML, animation, template, automatic outline or
Markdown-to-slide mapping is implemented. Font fitting, image validity and
final text/layout overflow are checked by the renderer after structural,
count and geometry validation.

For example, this is prepared content, not a prompt for slide composition:

```json
{
  "schema_version": "prepared_slide_deck_v1",
  "slide_count": 1,
  "title": "Prepared findings",
  "size": "wide",
  "slides": [{
    "layout": "title_and_content",
    "title": "Findings",
    "notes": "Prepared speaker notes.",
    "shapes": [{
      "type": "text_box",
      "box": {"left": 0.5, "top": 1.5, "width": 5, "height": 3},
      "paragraphs": [{"text": "An accepted finding", "list_kind": "bullet"}]
    }, {
      "type": "table",
      "box": {"left": 6, "top": 1.5, "width": 6, "height": 3},
      "rows": [["Name", "Count"], ["Alpha", "1"]]
    }]
  }]
}
```

The legacy message PPTX planner has an LLM fallback,
`_generate_powerpoint_slide_plan_with_model`; only its structured-content fast
path bypasses that call. This new Render profile uses neither path and never
imports the legacy route or composes slides implicitly.

### Bounds, Ownership and Failure Behavior

Structured/text serialization writes to a private temporary binary file in the working
directory and returns it only after complete rendering and final rechecks.
It never builds a whole-dataset list or whole-file string. Record serializers
hold one bounded record at a time; the structured-value reader supplies one
bounded value. The caller owns a successful stream and must close it, preferably
with a `with` block. Errors close the output and the consumed record/text
iterator. No failed prefix is returned as a complete file.

Owned iterator and failed-output cleanup uses the small, dependency-free
`functions_export_cleanup.py` guard. If closing also fails while a source,
authorization, cancellation, validation or rendering error is unwinding, the
original exception instance and cause remain authoritative. A safe exception
note records the secondary cleanup failure without copying private error text.
A cleanup-only failure still raises; it never turns into successful output.
Normal generator closing is distinguished from an actual failed operation so
early-close failures cannot disappear behind `GeneratorExit`.

Office output uses the headless helper's bounded, seekable in-memory streams.
The bridge transfers that stream without a second whole-file copy and closes
it if final authorization, count checks or metadata construction fail. A
successful stream has exactly one caller-owned lifetime. Workbook input stays
streaming; reports and slide JSON require bounded materialization.

`GeneratedFileExportLimits` can tighten or explicitly configure source bounds:

| Limit | Default | Meaning |
| --- | --- | --- |
| `max_records` | 1,000,000 | Maximum declared record count; not a preview/page limit. |
| `max_value_bytes` | 8 MiB | Aggregate UTF-8 string/key and numeric-text bytes per record or structured value. |
| `max_value_nodes` | 100,000 | Value/key nodes per record or structured value. |
| `max_depth` | 64 | Maximum nesting depth; callers may lower but not exceed 64. |
| `max_text_chunks` | 1,000,000 | Bounds even a text iterator that keeps yielding empty chunks. |

Office calls additionally accept server-supplied `office_limits=OfficeRenderLimits(...)`.
The catalog exposes `office_default_limits`, including the helper's 32 MiB
output, 64 MiB input, 500-page and 200-slide defaults. The effective output limit
is the smaller of `max_output_bytes` and the Office output ceiling. The row
ceiling is the smaller of shared and Office row limits, with Excel's hard limits
still enforced. Report accumulation is bounded by the smaller of
`max_value_bytes` and the Office input ceiling. These controls and
`image_resolver` are not model-authored request options and are rejected on
non-Office or legacy response calls.

These bound serializer work and auxiliary memory, not the allocator overhead
or a reader that materializes an oversized object before handing it off.
Readers remain responsible for bounded reads. `max_output_bytes` is a separate,
required caller quota on actual encoded bytes, including markup, delimiters and
escaping. SHA-256 and size are computed incrementally from those same bytes.
Declared record/character counts must remain stable and match the full stream.
Checks run at least every 100 records/text chunks and approximately every
64 KiB of output, with additional checks during large-value validation.

`GeneratedFileExportError` subclasses `ValueError`, carries a stable `code`,
and has `retryable=False`. Codes distinguish unsupported format/profile/source,
invalid options/limits/source/data, incomplete source, count mismatch, and
byte/record/value limits. Arbitrary reader, authorization and cancellation
exceptions are not turned into successful exports or automatic retry
decisions. The future execution/publication owner must classify those failures
and keep raw exception details out of browser payloads.

Native `OfficeRenderError` instances retain their original code and
`retryable` value; only `source_unavailable` and `render_io` are retryable.
The bridge separately records exceptions escaping its reader, authorization,
execution and resolver callbacks, lets the helper unwind normally, and then
restores those original exceptions. This matters because the standalone helper
otherwise wraps `InterruptedError` (an `OSError`) as a source outage. The bridge
does not skip checks or mislabel cancellation as an automatic retry condition.

### Runtime Integration Boundary

The intended future orchestration boundary remains:
**authorized source adapter -> explicit shared renderer -> existing private
artifact transport -> optional existing workspace publication**. Gather and
Reason supply retained data or prepared content; explicit Render tasks would
create files. The core does not upload or publish files, resolve source
bindings, implement retries, or enable the full M5/M6 orchestration path.

The ten-format callable catalog is not completion of M5 or M8. Authorized
retained-result integration, public capability admission, output
lifecycle/recovery and UI integration remain separate work. Existing Office
response/message callers are unchanged; these explicit profiles call the
headless helpers instead. See
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

For server-side integration, supply an already authorized complete reader and
an execution check; do not pass a prompt or a preview as the source:

```python
from functions_generated_file_exports import (
    GeneratedFileExportRequest,
    build_generated_file_export,
)

request = GeneratedFileExportRequest(
    "csv", "tabular_records_v1", columns=("identifier", "amount"),
)
with build_generated_file_export(
    source=authorized_complete_reader,
    export_request=request,
    max_output_bytes=64 * 1024 * 1024,
    check=recheck_execution,
) as exported:
    # A separate, authorized transport may consume exported.file_content here.
    rendered_size = exported.size_bytes
    rendered_digest = exported.content_sha256
```

The reader and callback in this example belong to the caller. This snippet
serializes only; it is not a new workflow or orchestration activation path.

## Testing and Validation

- `functional_tests\test_generated_file_office_bridge.py` renders every newly advertised Office source/format through `build_generated_file_export` and reopens real binaries. Coverage includes 30,017 streamed XLSX rows, ordered scalar types, precision rejection, strict prepared-deck schemas/layouts, literal text versus Markdown, authorized image callbacks, exact counts, bounds, caller-exception identity and stream ownership/cleanup.
- Its fresh normal/optimized subprocesses block network, configuration/bootstrap, model, publication, orchestration-storage and legacy-route imports. The unchanged `functional_tests\test_office_file_renderers.py` remains the separate headless-service regression anchor.
- Run the bridge alongside the existing suites with `python -m pytest .\functional_tests\test_generated_file_saved_record_exports.py .\functional_tests\test_generated_file_structured_renderers.py .\functional_tests\test_generated_file_office_bridge.py -q`.
- `functional_tests\test_generated_file_structured_renderers.py` executes the real dispatcher and serializers with local deterministic readers. Independent CSV/JSON/XML/YAML readback checks order, exact typed values, aliases, empty results, 30,017-record completeness, first/last records, byte counts and SHA-256. Negative cases cover incompatible profiles/sources, missing columns, invalid values, partial/preview/pending sources, count mismatch, size and memory limits, cancellation/revocation and stream cleanup.
- The same suite runs real cold imports and serialization in fresh normal and optimized Python processes with network calls blocked, verifies both import orders, and checks that no route/config/settings/logging owner is imported.
- Run the explicit renderer suites with `python -m pytest .\functional_tests\test_generated_file_saved_record_exports.py .\functional_tests\test_generated_file_structured_renderers.py -q`. Run legacy boolean-return regression scripts using their standalone runners, not pytest alone.
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

- Legacy response/native CSV retains the existing durable background path for large row sets. Explicit-source serialization itself never queues work or chooses a transport.
- DOCX and PDF render immediately for response-sized content; durable long-form DOCX work is tracked separately in [#1072](https://github.com/microsoft/simplechat/issues/1072).
- The framework deliberately does not route tabular-plugin rows around source coverage, authorization, or source-version checks.
- Unsupported, failed, unresolved, canceled, or partial source states remain visible through their existing evidence and export contracts; the framework does not fabricate missing rows.
- Exact saved-record serialization and its shared upload, download and publication handoff avoid whole-file buffers. Native destination ingestion still uses the existing worker and format-specific indexing; this does not assert that the downstream native indexer itself has constant memory use.
- JSON file availability, destination approval and index readiness are separate facts. An empty array can be a valid export without being searchable content.
