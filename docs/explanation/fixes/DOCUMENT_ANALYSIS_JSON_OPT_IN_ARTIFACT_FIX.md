# Document Analysis JSON Opt-In Artifact Fix

Version: 0.241.197

Fixed/Implemented in version: **0.241.197**

Related config.py update: `VERSION = "0.241.197"`

## Header Information

- Issue description: Analyze could attach a downloadable JSON artifact whenever the model's final answer happened to be valid JSON, even when the user only asked a normal analysis question.
- Root cause analysis: Document analysis artifact selection treated parseable JSON text as an implicit request for a JSON file instead of separating structured internal output from user-requested file format.
- Version implemented: 0.241.197

## Technical Details

- Files modified: `application/single_app/functions_workflow_runner.py`, `application/single_app/config.py`, `functional_tests/test_document_analysis_lossless_artifacts.py`.
- Code changes summary: Added explicit JSON artifact intent detection, kept JSON artifacts available for prompts that request a JSON file or export, and changed implicit JSON-shaped Analyze and Comparison outputs to use Markdown artifacts when an attachment is needed.
- Testing approach: Extended the document analysis artifact functional test to verify a plain-English Analyze prompt with JSON-shaped output creates a Markdown artifact, while an explicit JSON file prompt still creates a JSON artifact.
- Impact analysis: Users no longer receive unexpected JSON downloads for regular Analyze requests, while large or structured analysis output can still be preserved in a downloadable Markdown artifact.

## Validation

- Test results: `functional_tests/test_document_analysis_lossless_artifacts.py` validates the JSON opt-in behavior and version alignment.
- Before/after comparison: Before the fix, any parseable JSON final answer could become a JSON artifact. After the fix, JSON artifacts require an explicit JSON request; otherwise artifact-backed output uses Markdown.
- User experience improvements: Analyze answers stay aligned with the user's requested format, and detailed supporting output remains downloadable without implying the user asked for JSON.