# Tabular Generated Output Exports

Implemented in version: **0.241.120**

## Overview and Purpose

Large tabular requests can now produce reusable generated exports when the user asks for a row-by-row JSON array, CSV, or similarly large structured result.

Instead of forcing the final assistant reply to inline a large dataset, SimpleChat now saves the generated output into the user's personal workspace and shows a compact preview card in the chat response.

Related config update:
- `application/single_app/config.py` now reports version `0.241.120`.

Dependencies:
- `application/single_app/route_backend_chats.py`
- `application/single_app/functions_simplechat_operations.py`
- `application/single_app/route_enhanced_citations.py`
- `application/single_app/static/js/chat/chat-messages.js`

## Technical Specifications

Architecture overview:
- Tabular chat orchestration now detects requests that are better served as generated JSON or CSV exports.
- The backend batches large structured-output generation, serializes the result, and uploads the generated file into the current user's personal workspace.
- Assistant message metadata now persists `generated_tabular_outputs` so the UI can render the export immediately after the message arrives or when chat history reloads.
- A general authenticated workspace download route reuses the existing authorized blob-serving helper to stream the saved export back to the browser.

Chat behavior:
- The assistant keeps the conversational reply concise instead of inlining a very large JSON array or CSV body.
- The assistant can still reference the generated export in its response because the backend appends a system instruction describing the saved file.
- The UI shows file name, source workbook context, row count, a small preview, and a download button.

Storage model:
- Generated exports are stored as normal personal workspace documents.
- JSON and CSV outputs are reusable in future chats because they enter the same document pipeline as other workspace uploads.

## Usage Instructions

How it works:
1. Ask a tabular question that requests a large structured result, such as one JSON object per row or a CSV export.
2. Wait for the tabular processing step to finish.
3. Read the normal assistant summary in chat.
4. Use the generated export card to preview the saved output and download the full file.
5. Reuse the saved file later from the personal workspace like any other uploaded document.

Typical requests:
- "Return one JSON array containing one object per comment row."
- "Create a CSV of every matching row."
- "Save the full structured output and give me a summary here."

## Testing and Validation

Functional coverage:
- `functional_tests/test_tabular_generated_output_exports.py`

UI coverage:
- `ui_tests/test_chat_generated_tabular_output_card.py`

Validation focus:
- generated output metadata is persisted on assistant messages
- non-streaming responses expose metadata for immediate browser rendering
- the workspace download route serves authorized generated files
- the chat UI renders preview data without unsafe HTML interpolation

## Known Limitations

- The inline preview is intentionally small and only shows a subset of the generated rows.
- Very wide JSON objects are truncated in the preview card so the chat layout stays readable.
- The saved export currently targets the personal workspace even when the source tabular file came from another allowed workspace context.