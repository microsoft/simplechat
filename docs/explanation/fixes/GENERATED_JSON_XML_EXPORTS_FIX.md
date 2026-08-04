# Generated JSON and XML Export Artifacts Fix

Fixed/implemented in version: **0.250.113**

## Issue Description

JSON and XML generation requests could be returned as large inline assistant text or as a Markdown analysis artifact instead of a downloadable generated file. XML template-population workflows were especially affected: Analyze could inspect the selected XML/PDF sources, but the final handoff did not create a completed downloadable XML file.

## Root Cause

The generated export framework was primarily wired around CSV/tabular output. JSON support existed in portions of the tabular generated-output path, but general chat and document-analysis artifact creation did not consistently treat JSON as a file artifact. XML was not a first-class generated export format, and XML ingestion contained duplicate processing implementations.

## Technical Details

### Files Modified

- `application/single_app/functions_generated_file_exports.py`
- `application/single_app/route_backend_chats.py`
- `application/single_app/functions_workflow_runner.py`
- `application/single_app/functions_document_analysis.py`
- `application/single_app/functions_documents.py`
- `application/single_app/functions_tabular_generated_exports.py`
- `application/single_app/config.py`
- `functional_tests/test_generated_json_xml_exports.py`

### Code Changes Summary

- Added shared generated-file helpers for JSON parsing, XML extraction, XML serialization, and output-format normalization.
- Extended chat export intent detection to recognize natural JSON and XML phrasing such as "convert into JSON" and "populate the XML".
- Added assistant-response JSON/XML artifact capture so valid generated JSON/XML content is saved as a downloadable chat artifact and the persisted assistant message becomes a concise file handoff.
- Extended document-analysis artifact creation to upload `.xml` artifacts when the final analysis reply is valid XML and the user requested XML output.
- Added document-analysis prompt guidance to preserve JSON/XML structure during windowed analysis and to return only valid final JSON/XML during reduction.
- Extended durable tabular generated exports to serialize XML output from checkpointed row batches.
- Consolidated XML document processing through one token-aware implementation and replaced directly touched XML processing `print()` diagnostics with `log_event`.

## Testing Approach

Added `functional_tests/test_generated_json_xml_exports.py` to verify:

- Shared JSON/XML helper parsing and serialization.
- Chat route JSON/XML artifact hooks and no-inline handoff markers.
- Document-analysis JSON/XML intent and artifact wiring.
- XML processing consolidation and token-aware return behavior.

## Impact

Users who request JSON or XML file-shaped output now get the same generated artifact/download behavior used by CSV paths where valid generated content is available. XML template population and XML-to-JSON conversion have explicit artifact support instead of relying on inline responses or Markdown fallbacks.

## Validation

Run:

```powershell
python functional_tests\test_generated_json_xml_exports.py
```

Before this fix, JSON/XML requests were not consistently recognized as generated artifact workflows and XML output had no first-class artifact path. After this fix, JSON/XML artifact intent is recognized, valid outputs are attached as downloadable files, and XML ingestion uses one consolidated processor.
