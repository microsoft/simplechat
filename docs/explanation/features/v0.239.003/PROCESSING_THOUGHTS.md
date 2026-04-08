---
layout: libdoc/page
title: Processing Thoughts
order: 100
category: Features
---

# Processing Thoughts

## Overview
The Processing Thoughts feature replaces the generic "AI is typing..." indicator with real-time processing step traces that show users what the system is doing during chat processing. Each step (document search, web search, agent invocation, content safety check, response generation) is persisted in Cosmos DB and can be reviewed later via a per-message collapsible section.

**Version Implemented:** 0.239.003

## Dependencies
- Flask (backend routes)
- Azure Cosmos DB (`thoughts` and `archive_thoughts` containers)
- Bootstrap 5 (collapsible section, badges, icons)
- ES modules (`chat-thoughts.js`)

## Architecture Overview

### Backend

#### ThoughtTracker (`functions_thoughts.py`)
Stateful per-request tracker that writes each thought step to Cosmos DB immediately so polling clients can see partial progress.

```
ThoughtTracker(conversation_id, message_id, thread_id, user_id)
  .add_thought(step_type, content, detail=None) → thought_id
  .complete_thought(thought_id, duration_ms)     → updates duration
  .enabled                                        → checks settings['enable_thoughts']
```

Design rules:
- Each `add_thought()` does an immediate `upsert_item()` to Cosmos DB.
- All writes are wrapped in try/except — thought errors never crash the chat flow.
- Auto-increments `step_index` per tracker instance.
- Logs failures via `log_event()` at WARNING level.

#### Thought Document Schema
```json
{
    "id": "uuid",
    "conversation_id": "str",
    "message_id": "str (assistant message ID)",
    "thread_id": "str",
    "user_id": "str (partition key)",
    "step_index": 0,
    "step_type": "search | tabular_analysis | web_search | agent_tool_call | generation | content_safety",
    "content": "Searching personal workspace documents for 'sales analysis'...",
    "detail": "Optional technical detail",
    "duration_ms": null,
    "timestamp": "ISO-8601"
}
```

#### API Endpoints (`route_backend_thoughts.py`)

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/api/conversations/<id>/messages/<id>/thoughts` | Fetch persisted thoughts for a specific assistant message (historical viewing) |
| GET | `/api/conversations/<id>/thoughts/pending` | Fetch latest in-progress thoughts (polling while waiting for response) |

Both endpoints return `{"thoughts": [...], "enabled": true/false}`. When `enable_thoughts` is off, they return `{"thoughts": [], "enabled": false}`.

#### Instrumentation Points (`route_backend_chats.py`)

| Step Type | Content Example | When |
|-----------|----------------|------|
| `content_safety` | "Checking content safety..." | Before content safety check |
| `search` | "Searching personal documents for 'query'..." | Before hybrid search |
| `search` | "Found 5 results from 3 documents" | After search results |
| `tabular_analysis` | "Found tabular data — evaluating analysis..." | When tabular data detected |
| `web_search` | "Searching the web for 'query'..." | Before web search |
| `web_search` | "Got 8 web results" | After web search |
| `agent_tool_call` | "Sending to agent 'Data Analyst'..." | Before agent invocation |
| `generation` | "Generating response..." | Before GPT call |

### Frontend

#### Streaming Mode
Thought events are embedded in the SSE stream as `{"type": "thought", ...}` JSON payloads. The streaming handler in `chat-streaming.js` passes these to `handleStreamingThought()` which updates the streaming placeholder badge.

#### Non-Streaming Mode
A polling mechanism in `chat-thoughts.js` fetches `/thoughts/pending` every 2 seconds while waiting for a response. The loading indicator text is updated with the latest thought step.

#### Per-Message History
Each assistant message footer includes a lightbulb toggle button (when thoughts exist). Clicking it opens a collapsible section that lazy-loads thoughts from the API. Each step shows an icon, content text, and optional duration.

#### Icon Map
| Step Type | Bootstrap Icon |
|-----------|---------------|
| `search` | `bi-search` |
| `tabular_analysis` | `bi-table` |
| `web_search` | `bi-globe` |
| `agent_tool_call` | `bi-robot` |
| `generation` | `bi-lightning` |
| `content_safety` | `bi-shield-check` |

## Configuration

### Admin Settings
- **Toggle**: `enable_thoughts` (default: `false`)
- **Location**: Admin Settings > Optional Features tab > "Processing Thoughts" section
- **Effect**: When disabled, no thoughts are recorded and no UI elements are shown

### Cosmos DB Containers
| Container | Partition Key | Purpose |
|-----------|--------------|---------|
| `thoughts` | `/user_id` | Active thought records |
| `archive_thoughts` | `/user_id` | Archived thoughts from deleted conversations |

## Archive and Cleanup

When a conversation is deleted:
- **Archiving enabled**: Thoughts are copied to `archive_thoughts` container, then deleted from `thoughts`
- **Archiving disabled**: Thoughts are permanently deleted from `thoughts`

This applies to both single conversation delete and bulk delete operations.

## File Structure

### Files Created
| File | Purpose |
|------|---------|
| `functions_thoughts.py` | ThoughtTracker class, Cosmos CRUD helpers |
| `route_backend_thoughts.py` | API endpoints for fetching thoughts |
| `static/js/chat/chat-thoughts.js` | Frontend polling, rendering, toggle |

### Files Modified
| File | Change |
|------|--------|
| `config.py` | Added `thoughts` + `archive_thoughts` Cosmos containers, bumped VERSION |
| `functions_settings.py` | Added `enable_thoughts` default setting |
| `app.py` | Imported and registered thought routes |
| `route_backend_chats.py` | Instrumented ~8 thought points per chat path |
| `route_backend_conversations.py` | Added archive/delete thoughts on conversation delete |
| `templates/admin_settings.html` | Added Processing Thoughts toggle card |
| `static/js/admin/admin_settings.js` | Added `enable_thoughts` to settings collection |
| `static/js/chat/chat-messages.js` | Integrated thoughts toggle in footer, polling start/stop |
| `static/js/chat/chat-streaming.js` | Handle `type: "thought"` in SSE data |
| `static/js/chat/chat-loading-indicator.js` | Added `updateLoadingIndicatorText()` for thought display |
| `static/css/chats.css` | Added thought indicator, toggle, container, and dark mode styles |

## Testing

1. **Enable feature**: Set `enable_thoughts: True` in admin settings
2. **Non-streaming**: Send a message with document search — verify loading indicator updates with thought steps, lightbulb icon appears after response
3. **Streaming**: Send a message — verify streaming placeholder shows thought badges, lightbulb available after finalization
4. **History**: Reload page, open old conversation — click lightbulb to verify lazy-loaded thoughts
5. **Disabled**: Set `enable_thoughts: False` — verify no thoughts generated, no lightbulb icons
6. **Archive**: Delete a conversation with archiving enabled — verify thoughts moved to `archive_thoughts`
