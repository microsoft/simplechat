# Conversation Export

## Overview
The Conversation Export feature allows users to export one or multiple conversations directly from the Chats experience. A multi-step wizard modal guides users through format selection, output packaging, and downloading the final file.

**Version Implemented:** 0.237.050

## Dependencies
- Flask (backend route)
- Azure Cosmos DB (conversation and message storage)
- Bootstrap 5 (modal, step indicators, cards)
- ES modules (chat-export.js)

## Architecture Overview

### Backend
- **Route file:** `route_backend_conversation_export.py`
- **Endpoint:** `POST /api/conversations/export`
- **Registration:** Called via `register_route_backend_conversation_export(app)` in `app.py`

The endpoint accepts a JSON body with:
| Field | Type | Description |
|---|---|---|
| `conversation_ids` | list[str] | IDs of conversations to export |
| `format` | string | `"json"` or `"markdown"` |
| `packaging` | string | `"single"` or `"zip"` |

The server verifies user ownership of each conversation, fetches messages from Cosmos DB, filters for active thread messages, sanitizes internal fields, and returns either a single file or ZIP archive as a binary download.

### Frontend
- **JS module:** `static/js/chat/chat-export.js`
- **Modal HTML:** Embedded in `templates/chats.html` (`#export-wizard-modal`)
- **Global API:** `window.chatExport.openExportWizard(conversationIds, skipSelection)`

The wizard has up to 4 steps:
1. **Selection Review** — Shows selected conversations with titles (skipped for single-conversation export)
2. **Format** — Choose between JSON and Markdown via action-type cards
3. **Packaging** — Choose between single file and ZIP archive
4. **Download** — Summary and download button

## Entry Points

### Single Conversation Export
- **Sidebar ellipsis menu** → "Export" item (in `chat-sidebar-conversations.js`)
- **Left-pane ellipsis menu** → "Export" item (in `chat-conversations.js`)
- Both call `window.chatExport.openExportWizard([conversationId], true)` — skips the selection step

### Multi-Conversation Export
- Enter selection mode by clicking "Select" on any conversation
- Select multiple conversations via checkboxes
- Click the export button in:
  - **Left-pane header** — `#export-selected-btn` (btn-info, download icon)
  - **Sidebar actions bar** — `#sidebar-export-selected-btn`
- These call `window.chatExport.openExportWizard(selectedIds, false)` — shows all 4 steps

## Export Formats

### JSON
Produces a JSON array where each entry contains:
```json
{
  "conversation": {
    "id": "...",
    "title": "...",
    "last_updated": "...",
    "chat_type": "...",
    "tags": [],
    "is_pinned": false,
    "context": []
  },
  "messages": [
    {
      "role": "user",
      "content": "...",
      "timestamp": "...",
      "citations": []
    }
  ]
}
```

### Markdown
Produces a Markdown document with:
- `# Title` heading
- Metadata block (last updated, chat type, tags, message count)
- `### Role` sections per message with timestamps
- Citation lists where applicable
- `---` separators between messages and conversations

## Output Packaging

### Single File
- One file containing all selected conversations
- JSON: `.json` file
- Markdown: `.md` file with `---` separators between conversations

### ZIP Archive
- One file per conversation inside a `.zip`
- Filenames: `{sanitized_title}_{id_prefix}.{ext}`
- Titles are sanitized for filesystem safety (special chars replaced, truncated to 50 chars)

## File Structure
```
application/single_app/
├── route_backend_conversation_export.py   # Backend API endpoint
├── app.py                                  # Route registration
├── static/js/chat/
│   ├── chat-export.js                     # Export wizard module
│   ├── chat-conversations.js              # Left-pane wiring
│   └── chat-sidebar-conversations.js      # Sidebar wiring
├── templates/
│   ├── chats.html                         # Modal HTML + button + script
│   ├── _sidebar_nav.html                  # Sidebar export button
│   └── _sidebar_short_nav.html            # Short sidebar export button
functional_tests/
└── test_conversation_export.py            # Functional tests
```

## Security
- Endpoint requires `@login_required` and `@user_required` decorators
- Each conversation is verified for user ownership before export
- Internal Cosmos DB fields (`_rid`, `_self`, `_etag`, `user_id`, etc.) are stripped from output
- No sensitive data is included in the export

## Testing and Validation
- **Functional test:** `functional_tests/test_conversation_export.py`
- Tests cover:
  - Conversation sanitization (internal field stripping)
  - Message sanitization
  - Markdown generation (headings, metadata, citations)
  - JSON structure validation
  - ZIP packaging (correct entries, valid content)
  - Filename sanitization (special chars, truncation, empty input)
  - Active thread message filtering

## Known Limitations
- Export is limited to conversations the authenticated user owns
- Very large conversations (thousands of messages) may take longer to process
- The wizard fetches conversation titles client-side; if a title lookup fails, it shows the conversation ID instead
