# Per-Message Export

## Overview
The Per-Message Export feature adds export and action options directly to the three-dots dropdown menu on individual chat messages. Users can export a single message to Markdown or Word, insert it into the chat prompt, or open it in their default email client — all without leaving the chat interface.

**Version Implemented:** 0.239.005–0.239.007
**Latest export formatting update:** 0.240.078

## Dependencies
- Flask (backend route for Word export)
- `python-docx` 1.1.2 (Word document generation)
- Azure Cosmos DB (message retrieval for Word export)
- Bootstrap 5 (dropdown menus, icons)
- ES modules (`chat-message-export.js`)

## Architecture Overview

### Backend
- **Route file:** `route_backend_conversation_export.py`
- **Endpoint:** `POST /api/message/export-word`
- **Registration:** Registered alongside the existing conversation export routes

The Word export endpoint accepts a JSON body with:

| Field | Type | Description |
|---|---|---|
| `message_id` | string | ID of the message to export |
| `conversation_id` | string | ID of the conversation the message belongs to |

The server verifies user ownership of the conversation, fetches the specific message from Cosmos DB, converts the stored markdown into Word-native structures, generates a Word document using `python-docx`, and returns the `.docx` as a binary download.

### Frontend
- **JS module:** `static/js/chat/chat-message-export.js`
- **Dropdown integration:** `static/js/chat/chat-messages.js` (AI and user message dropdowns)
- **Dynamic import:** Module is loaded on-demand when any export action is clicked (same pattern as `chat-edit.js`)

## Features

### Export to Markdown
- **Location:** Three-dots dropdown → "Export to Markdown"
- **Icon:** `bi-markdown`
- **Behavior:** Entirely client-side. Grabs the message content from the existing hidden textarea (AI messages) or `.message-text` element (user messages), wraps it with a role header, and triggers a `.md` file download via Blob URL.
- **Filename pattern:** `message_export_YYYYMMDD_HHMMSS.md`

### Export to Word
- **Location:** Three-dots dropdown → "Export to Word"
- **Icon:** `bi-file-earmark-word`
- **Behavior:** POSTs to `/api/message/export-word`. The backend generates a styled `.docx` document with:
  - Title heading ("Message Export")
  - Role metadata
  - Message content converted into Word formatting (headings, paragraphs, bold, italic, inline code, code blocks, bullet and numbered lists)
  - Markdown tables rendered as Word tables instead of pipe-delimited text
  - Citations section (if present on the message)
- **Filename pattern:** `message_export_YYYYMMDD_HHMMSS.docx`

### Use as Prompt
- **Location:** Three-dots dropdown → "Use as Prompt"
- **Icon:** `bi-clipboard-plus`
- **Behavior:** Entirely client-side. Inserts the raw message content directly into the chat input box (`#user-input`), focuses the input, and triggers the auto-resize/send-button update. The user can review, edit, and send it.

### Open in Email
- **Location:** Three-dots dropdown → "Open in Email"
- **Icon:** `bi-envelope`
- **Behavior:** Requests a backend-generated mailto draft, then opens the user's default email client via a `mailto:` link with:
  - **Subject:** An explicit subject from the message when present, otherwise a generated subject from the same GPT initialization path used by conversation summary generation
  - **Body:** Word-style plain text derived from the message markdown so headings, lists, tables, code blocks, and citations are no longer pasted as raw markdown
- Uses `encodeURIComponent` for safe URL encoding of the subject and body.

## Dropdown Menu Structure

Both AI and user messages now have export options below a divider:

**AI Message Dropdown:**
1. Delete
2. Retry
3. Feedback (thumbs up/down)
4. ─── divider ───
5. Export to Markdown
6. Export to Word
7. Use as Prompt
8. Open in Email

**User Message Dropdown:**
1. Edit
2. Delete
3. Retry
4. ─── divider ───
5. Export to Markdown
6. Export to Word
7. Use as Prompt
8. Open in Email

## File Structure

| File | Purpose |
|------|---------|
| `static/js/chat/chat-message-export.js` | Client-side export functions (Markdown, Word fetch, Use as Prompt, Open in Email) |
| `static/js/chat/chat-messages.js` | Dropdown menu HTML and event bindings for both AI and user messages |
| `route_backend_conversation_export.py` | Backend `/api/message/export-word` endpoint and markdown-to-Word conversion |

## Testing and Validation

### Test Scenarios
1. AI message → Export to Markdown → `.md` file downloads with content and role header
2. AI message → Export to Word → `.docx` file downloads with formatted content and citations
3. User message → Export to Markdown → `.md` file downloads
4. User message → Export to Word → `.docx` file downloads
5. AI/User message → Use as Prompt → Content appears in chat input box
6. AI/User message → Open in Email → Default email client opens with pre-filled subject and body
7. Existing actions (Delete, Retry, Edit, Feedback) still function correctly

### Known Limitations
- Word export requires a round-trip to the backend; offline use is not supported for Word format
- `mailto:` URL length is limited by the email client/OS; very long messages may be truncated
- `mailto:` does not guarantee rich HTML or RTF composition, so the email body preserves Word-like structure in plain text rather than forcing true rich-text formatting
- Markdown export for user messages uses `innerText` rather than original markdown source

## Cross-References
- Related feature: [Conversation Export](CONVERSATION_EXPORT.md) — exports entire conversations
- Backend shares infrastructure with conversation export (`route_backend_conversation_export.py`)
- Functional tests: `functional_tests/test_per_message_export.py`
