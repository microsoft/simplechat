# Per-Message Word Export Formatting Fix

Fixed/Implemented in version: **0.240.076**

## Issue Description

Per-message "Export to Word" downloads could still contain raw markdown syntax such as pipe-delimited tables, fenced code markers, and other literal markdown text instead of Word-native formatting.

## Root Cause Analysis

The DOCX renderer in `route_backend_conversation_export.py` used a narrow line-by-line markdown parser. It handled only a small subset of markdown patterns directly and did not convert richer structures like markdown tables through a full document model.

Because the export path wrote content paragraph-by-paragraph from markdown text, parts of the response were preserved as markdown syntax rather than being translated into actual Word document elements.

## Technical Details

### Files Modified

- `application/single_app/route_backend_conversation_export.py`
- `application/single_app/config.py`
- `functional_tests/test_per_message_export.py`
- `docs/explanation/features/MESSAGE_EXPORT.md`

### Code Changes Summary

- Replaced the line-based DOCX markdown renderer with a markdown-to-HTML-to-Word conversion flow.
- Added Word rendering helpers for headings, paragraphs, inline formatting, code blocks, lists, and tables.
- Extended the existing per-message export functional test to execute the real formatter helpers from source and validate Word-native structures.
- Bumped the application version to `0.240.076`.

### Testing Approach

- Updated `functional_tests/test_per_message_export.py`.
- Added a regression that loads the formatter helpers from `route_backend_conversation_export.py`, renders markdown into a DOCX document, and verifies headings, bold text, italic text, code formatting, list styles, and table output.

## Validation

### Before

- Exported Word documents could include raw markdown markers.
- Markdown tables could remain pipe-delimited text instead of rendering as Word tables.
- Rich assistant answers were inconsistently formatted in `.docx` output.

### After

- Exported Word documents render markdown using Word-native document structures.
- Markdown tables export as actual Word tables.
- Inline styles and code blocks are represented as styled DOCX runs instead of raw markdown text.

### User Experience Improvement

Users exporting a chat message to Word now receive a document that is formatted for document review and sharing, instead of one that still looks like markdown source.