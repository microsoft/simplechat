# Tabular Generated Export Artifact Presentation Fix

Fixed in version: **0.241.064**

## Issue Description

Large workflow/document-analysis requests that produced a full generated JSON or CSV export could also attach secondary analysis JSON and Markdown artifacts. The result was noisy: the useful CSV preview, the analysis JSON artifact, the Markdown artifact, and the full generated export card all appeared together, making it unclear which file was the real deliverable.

## Root Cause

The document-analysis artifact builder treated exhaustive analysis outputs as standalone deliverables even when the tabular generated-output pipeline had already queued or attached the full row-level export. That caused the reduced analysis reply to be saved as additional JSON/Markdown artifacts beside the actual generated export.

## Technical Details

Files modified:

- `application/single_app/functions_workflow_runner.py`
- `functional_tests/test_document_analysis_lossless_artifacts.py`
- `docs/explanation/features/TABULAR_BACKGROUND_GENERATED_EXPORTS.md`
- `application/single_app/config.py`

Code changes summary:

- Added primary generated tabular output awareness to document-analysis artifact creation.
- Kept the supporting CSV analysis preview when available.
- Suppressed redundant analysis JSON artifacts when a full generated tabular export exists.
- Suppressed Markdown/raw-note analysis artifacts unless the user explicitly requested Markdown.
- Updated generated analysis artifact filenames to strip source extensions and avoid `*-analysis.json-analysis.md` style names.

Testing approach:

- Added a functional regression covering the primary generated JSON export plus supporting CSV preview presentation.
- Verified the assistant reply no longer inlines a duplicate preview or promotes secondary Markdown/raw-note artifacts when the full generated export exists.

## Validation

Before:

- A generated JSON export workflow could show CSV, Markdown, analysis JSON, and generated JSON cards together.
- The assistant reply included an inline preview even though artifact cards already contained previews.
- Markdown artifact filenames could inherit the source extension and appear confusing beside JSON exports.

After:

- The full generated tabular export is presented as the primary deliverable.
- The supporting CSV preview remains available for quick inspection.
- Redundant analysis JSON and default Markdown artifacts are suppressed for primary generated export flows.
- Assistant text clearly says the generated export is the exhaustive deliverable.

## Related References

- Related functional test: `functional_tests/test_document_analysis_lossless_artifacts.py`
- Related feature documentation: `docs/explanation/features/TABULAR_BACKGROUND_GENERATED_EXPORTS.md`
- Version update: `application/single_app/config.py` version **0.241.064**