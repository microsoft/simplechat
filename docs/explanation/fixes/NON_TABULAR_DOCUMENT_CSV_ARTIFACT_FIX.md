# Non-Tabular Document CSV Artifact Fix

Fixed in version: **0.250.065**

Related issue: [#1066](https://github.com/microsoft/simplechat/issues/1066)

## Issue

When a user selected a PDF, Word document, or other non-tabular source and explicitly requested a CSV, the assistant could return valid comma-delimited rows without creating a downloadable CSV artifact.

## Root Cause

The assistant table export helper recognized Markdown pipe tables and tab-separated output, but not comma-delimited output. The chat route already invoked the helper and uploaded successful results, so valid CSV text stopped at the parser boundary.

## Technical Details

### Files Modified

- `application/single_app/functions_assistant_table_exports.py`
- `application/single_app/route_backend_chats.py`
- `application/single_app/functions_tabular_generated_exports.py`
- `application/single_app/functions_workflow_runner.py`
- `application/single_app/config.py`
- `functional_tests/test_assistant_table_csv_artifact.py`
- `functional_tests/test_document_analysis_lossless_artifacts.py`
- `functional_tests/test_tabular_row_orchestration_scale.py`
- `docs/explanation/release_notes.md`

### Changes

- Parse CSV from explicit CSV, text, and plaintext code fences.
- Parse conservative comma-delimited blocks when the model returns plain CSV text.
- Recognize broader explicit CSV phrasing through one shared intent predicate used by generic and tabular export paths.
- Use Python's CSV parser to preserve quoted commas, escaped quotes, multiline values, and column order.
- Exclude surrounding prose and document citation lines from generated CSV rows.
- Neutralize spreadsheet formula prefixes in downloaded headers and values while preserving signed numeric values across assistant-table, immediate tabular, durable background, and workflow analysis CSV writers.
- Preserve every source column when duplicate headers collide with already-suffixed header names.
- Continue requiring an explicit CSV or table request before creating an artifact.
- Send large assistant-derived CSV row sets through the existing checkpointed background exporter without a second model transformation; the chat displays the normal queued/running/completed status and download link.

## Validation

The focused functional tests cover PDF-style fenced CSV, plain CSV followed by source citations, Word-style multiline and escaped-quote values, blank lines inside quoted values, alternate text fence labels, comma-bearing prose, formula-prefixed headers and cells across every generated CSV writer, duplicate header collisions, Markdown tables, tab-separated tables, broader explicit request phrasing, non-export requests, and the bounded 30,000-row background writer.

Before the fix, a valid comma-delimited response produced no export payload. After the fix, the existing artifact uploader receives normalized rows and creates a downloadable `.csv` file; large row sets use the existing background export status and checkpoint flow.

## Impact

Users can request a CSV from structured information contained in non-tabular documents without manually copying the model's rendered CSV text into a local file. The fix does not infer rows from prose itself; the assistant response must contain valid table-shaped output.

The application version was updated in `application/single_app/config.py` from `0.250.064` to `0.250.065`.