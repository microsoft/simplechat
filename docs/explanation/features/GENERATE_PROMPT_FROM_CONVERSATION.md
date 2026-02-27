# Generate Prompt from Conversation

## Overview

The **Generate Prompt from Conversation** feature uses AI to analyze a chat conversation and produce a reusable prompt that captures the intent, patterns, and techniques observed in the exchange. Users can review, edit, and save the generated prompt to their personal, group, or public workspace prompts.

**Version implemented:** 0.238.025

**Dependencies:**
- Azure OpenAI (GPT model deployment)
- Saved Prompts system (personal, group, or public workspaces)
- Cosmos DB (conversations and messages containers)

---

## Architecture Overview

### Flow

1. User clicks **"Generate Prompt"** button in the chat toolbar
2. Frontend sends `POST /api/conversations/<id>/generate-prompt`
3. Backend fetches conversation messages from Cosmos DB
4. Messages are formatted and sent to Azure OpenAI with a meta-prompt
5. AI analyzes the conversation and returns a JSON response with `name` and `content`
6. Frontend displays the result in a review/edit modal
7. User can edit name/content, select a save scope, then save
8. Save calls the existing prompt creation APIs (`/api/prompts`, `/api/group_prompts`, or `/api/public_prompts`)

### Components

| Component | File | Purpose |
|-----------|------|---------|
| Backend endpoint | `route_backend_generate_prompt.py` | AI analysis and prompt generation API |
| Frontend module | `static/js/chat/chat-generate-prompt.js` | UI logic, API calls, modal management |
| Chat template | `templates/chats.html` | Toolbar button and review/edit modal |
| Onload wiring | `static/js/chat/chat-onload.js` | Feature initialization on page load |
| App registration | `app.py` | Route registration |

---

## API Endpoint

### `POST /api/conversations/<conversation_id>/generate-prompt`

**Authentication:** Required (`@login_required`, `@user_required`)

**Request:** No body required. The conversation ID is in the URL path.

**Response (200):**
```json
{
    "success": true,
    "name": "Technical Code Review Assistant",
    "content": "You are a code review assistant. When reviewing code, please..."
}
```

**Error responses:**
| Status | Condition |
|--------|-----------|
| 401 | User not authenticated |
| 400 | Empty conversation_id or no messages in conversation |
| 404 | Conversation not found or user doesn't own it |
| 500 | AI model configuration error or unexpected server error |

**Implementation details:**
- Fetches up to 50 most recent active-thread messages
- Filters out image, file, system, and safety messages
- Uses a structured meta-prompt requesting JSON output with `name` and `content` fields
- Falls back to raw AI response text if JSON parsing fails
- Uses the same Azure OpenAI client initialization pattern as the main chat endpoint

---

## Configuration

No additional configuration is needed. The feature uses existing settings:

- **Azure OpenAI settings** — same GPT model and client used for chat
- **Workspace settings** — the toolbar button visibility depends on `enable_user_workspace` or `enable_group_workspaces` being enabled
- **Save scope options** — conditionally rendered based on `enable_user_workspace`, `enable_group_workspaces`, and `enable_public_workspaces`

---

## UI Workflow

### 1. Trigger
The **"Generate Prompt"** button (`bi-magic` icon) appears in the chat toolbar alongside existing buttons (Workspaces, File, Prompts, etc.). It is visible when user or group workspaces are enabled.

### 2. Modal
Clicking the button opens a modal with:
- A **loading spinner** while the AI analyzes the conversation
- **Prompt Name** — text input pre-filled by AI (max 100 characters)
- **Prompt Content** — textarea pre-filled by AI (markdown-compatible)
- **Save To** — dropdown to select scope (Personal, Group, or Public)

### 3. Actions
- **Regenerate** — re-runs AI analysis for a different result
- **Cancel** — closes the modal without saving
- **Save Prompt** — saves to the selected scope via existing prompt APIs

### 4. Post-save
After saving, the prompt lists are refreshed so the new prompt appears immediately in the prompt selector dropdown.

---

## File Structure

```
application/single_app/
├── route_backend_generate_prompt.py      # New backend endpoint
├── static/js/chat/
│   ├── chat-generate-prompt.js           # New frontend module
│   └── chat-onload.js                    # Modified: imports and initializes feature
├── templates/
│   └── chats.html                        # Modified: toolbar button + modal
└── app.py                                # Modified: route registration
```

---

## Testing and Validation

### Functional Tests
- **File:** `functional_tests/test_generate_prompt_from_conversation.py`
- **Coverage:**
  - Meta-prompt definition and structure validation
  - Message filtering logic (active threads, role exclusions)
  - JSON response parsing (clean, markdown-wrapped, fallback)
  - Conversation text building and truncation
  - Route file structure and required decorators
  - Frontend file existence and content validation
  - Version update verification

### Manual Testing
1. Open a conversation with several exchanges
2. Click "Generate Prompt" in the toolbar
3. Verify the loading spinner appears
4. Verify AI-generated name and content populate the form
5. Edit the name/content as desired
6. Select a save scope
7. Click "Save Prompt"
8. Verify a success toast appears
9. Verify the prompt appears in the prompts dropdown
10. Test with an empty conversation (should show an error toast)

### Known Limitations
- Very long conversations are truncated to the last 50 messages
- Image, file, system, and safety messages are excluded from analysis
- The AI response quality depends on the conversation content and GPT model capability
- Requires an active Azure OpenAI deployment with available quota
