# Generated Analysis Markdown Preview Fix

Fixed/Implemented in version: **0.241.022**

## Issue Description

Generated analysis artifacts saved as Markdown displayed their chat-card preview as raw source text. Headings, bold spans, and other Markdown syntax were visible in the preview instead of rendering like the rest of the chat response.

## Root Cause Analysis

The generated artifact card reused the plain text preview block for every non-tabular preview. That was appropriate for JSON fallback content, but Markdown artifacts are tagged with `output_format: md` and need the same explicit Markdown rendering and sanitization boundary used by assistant message content.

## Technical Details

Files modified:

- `application/single_app/static/js/chat/chat-messages.js`
- `application/single_app/static/css/chats.css`
- `ui_tests/test_chat_generated_tabular_output_card.py`
- `application/single_app/config.py`

Code changes summary:

- Detect generated artifacts with `md` or `markdown` output formats, including `.md` and `.markdown` file names.
- Render Markdown previews with `marked.parse(...)` and `DOMPurify.sanitize(...)` before assigning the sanitized HTML to the preview container.
- Keep JSON and other plain-text fallback previews in the existing preformatted text block.
- Add compact Markdown-preview styling so rendered headings, lists, tables, and code blocks fit inside the artifact card.

## Testing Approach

Added UI regression coverage in `ui_tests/test_chat_generated_tabular_output_card.py` that injects a generated Markdown artifact into the chat UI, verifies bold text and headings render as HTML, and confirms unsafe event-handler attributes do not survive sanitization.

## Impact Analysis

Markdown artifact previews now match user expectations while preserving the existing raw-text behavior for JSON and other non-Markdown preview formats. The sanitizer boundary prevents generated or uploaded Markdown from becoming executable browser content.

## Validation

Before the fix, previews showed raw syntax such as `**Document-level summary**` and `## Core framework`. After the fix, those preview lines render as styled Markdown inside the card, with raw Markdown markers removed from the visible preview.

Related config.py version update: `VERSION = "0.241.022"`.