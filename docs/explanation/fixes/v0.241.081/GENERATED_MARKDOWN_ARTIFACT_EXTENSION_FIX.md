# Generated Markdown Artifact Extension Fix

Version: 0.241.081

Fixed/Implemented in version: **0.241.081**

## Issue Description

Generated Markdown artifacts, including Deep Research ledger files, could be saved as chat artifacts with Markdown content but a `.json` filename. When a user selected **Add to Workspace**, the workspace processor treated the artifact as JSON and failed with an invalid JSON structure error.

## Root Cause Analysis

Generated artifact filename normalization only preserved `.json` and `.csv` extensions. Markdown artifact uploads passed filenames such as `deep_research_ledger_20260521_194546.md`, but the helper renamed them to `.json` before storing the chat artifact. The promotion route then reused that stored filename, so Markdown bytes entered the workspace ingestion pipeline as a JSON document.

## Technical Details

### Files Modified

- `application/single_app/functions_simplechat_operations.py`
- `application/single_app/route_enhanced_citations.py`
- `application/single_app/config.py`
- `functional_tests/test_generated_markdown_artifact_extension.py`

### Code Changes Summary

- Updated generated artifact filename normalization to preserve real extensions instead of forcing non-CSV artifacts to `.json`.
- Added promotion/download filename resolution that uses generated artifact output-format metadata to repair legacy Markdown artifacts already stored with `.json` names.
- Added regression coverage for Deep Research-style Markdown artifact filenames and legacy `.json` artifact promotion.

## Testing And Validation

- Functional regression: `functional_tests/test_generated_markdown_artifact_extension.py`
- Python compile validation for the touched backend modules and regression test.

## Impact Analysis

- New Deep Research ledger artifacts are stored and promoted with `.md` filenames.
- Existing Markdown artifacts that were saved as `.json` can be added to a workspace using the metadata-corrected `.md` filename.
- JSON and CSV generated artifacts continue to keep their expected extensions.