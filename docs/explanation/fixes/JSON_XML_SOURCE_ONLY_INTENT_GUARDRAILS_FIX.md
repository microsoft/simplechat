# JSON/XML Source-Only Intent Guardrails Fix

Fixed/Implemented in version: **0.250.156**

Related work: Fixes #1198

## Issue

Source-reading prompts that mentioned JSON or XML nouns could be misclassified as generated artifact requests even when the user did not ask to create, export, save, or return a file.

## Root Cause

The structured artifact detector treated noun-only markers such as `json object`, `json file`, `xml document`, and `xml file` as sufficient evidence of an output artifact request. Those markers also appear in ordinary source-analysis prompts such as "Summarize this XML document" or "Validate this JSON object," so shared chat, document-analysis, and workflow routing could incorrectly choose generated artifact execution.

## Technical Details

### Files Modified

- `application/single_app/functions_generated_file_exports.py`
- `application/single_app/config.py`
- `functional_tests/test_generated_json_xml_exports.py`
- `docs/explanation/release_notes.md`

### Code Changes

- Removed ambiguous noun-only JSON/XML source terms from marker-only artifact detection.
- Preserved explicit action and destination detection for prompts such as "Export as JSON," "Create an XML file," and "Place these extracted fields in an XML document."
- Added intent-matrix coverage for source-only JSON/XML prompts and explicit output prompts.
- Updated the application version from `0.250.155` to `0.250.156`.

## Impact Analysis

- Source-only JSON/XML prompts continue through analysis or validation paths instead of artifact generation.
- Explicit generated JSON/XML output requests still create downloadable artifacts.
- Chat, document-analysis, and workflow wrappers continue sharing the same structured artifact intent decision.

## Validation

- `python functional_tests\test_generated_json_xml_exports.py`

## Before and After

Before, "Summarize this XML document" returned an XML artifact target and could route to generated file creation. After this fix, that prompt returns no artifact target, while explicit output requests such as "Create an XML file" still return `xml`.