# Document Analysis Answer-First Artifact Preview Fix

Version: 0.241.124

Fixed/Implemented in version: **0.241.124**

Related config.py update: `VERSION = "0.241.124"`

## Header Information

- Issue description: Analyze workflows could successfully produce thorough CSV and Markdown artifacts while the primary assistant message led with artifact bookkeeping and a short preview instead of directly answering the user's request.
- Root cause analysis: Generated document analysis artifact replies summarized artifact creation first and rendered artifact previews expanded by default, causing supporting evidence to dominate the visible chat response.
- Version implemented: 0.241.124

## Technical Details

- Files modified: `application/single_app/functions_workflow_runner.py`, `application/single_app/static/js/chat/chat-messages.js`, `application/single_app/static/css/chats.css`, `application/single_app/config.py`, `functional_tests/test_document_analysis_answer_first_artifacts.py`.
- Code changes summary: Added answer-summary synthesis for generated Analyze replies, including page/count table summarization for search-like requests, collapsed Analyze/Comparison artifact previews behind a native disclosure control, removed inline mini-preview fragments from artifact-backed replies, and made CSV artifact previews render as tabular rows instead of JSON blobs.
- Testing approach: Added a focused functional contract test that verifies the answer-first backend reply helpers and collapsed generated analysis artifact preview UI are present.
- Impact analysis: Full CSV/Markdown artifacts remain available for download and auditability, while the visible assistant response now prioritizes the concise answer and keeps bulky previews optional.

## Validation

- Test results: `functional_tests/test_document_analysis_answer_first_artifacts.py` validates backend and UI contracts for the fix.
- Before/after comparison: Before the fix, artifact cards and previews were the dominant response surface, and CSV artifact previews could appear as JSON arrays. After the fix, the assistant message starts with an explicit answer summary, omits awkward inline table-preview fragments, keeps artifact previews collapsed by default, and renders CSV previews as rows.
- User experience improvements: Users can quickly see what the analysis found, then open or download detailed artifacts when they need the complete table or audit notes.
