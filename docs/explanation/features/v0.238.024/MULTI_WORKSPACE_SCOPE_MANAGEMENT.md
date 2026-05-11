# MULTI_WORKSPACE_SCOPE_MANAGEMENT.md

**Feature**: Multi-Workspace Scope Management
**Version**: v0.238.024
**Dependencies**: Azure Cosmos DB, Flask Backend, Bootstrap 5

## Overview and Purpose

Multi-Workspace Scope Management allows users to select from Personal, multiple Group, and multiple Public workspaces simultaneously in the chat interface. This replaces the previous single-scope dropdown with a hierarchical checkbox-based multi-select. The feature also introduces per-conversation scope locking, which prevents accidental changes to the workspace context after a search has been performed.

## Key Features

- **Multi-Workspace Selection**: Select any combination of Personal, Group, and Public workspaces simultaneously
- **Hierarchical Scope Dropdown**: Organized sections for Personal, Groups, and Public Workspaces with "Select All / Clear All" toggle
- **Scope Locking**: Per-conversation lock that freezes workspace selection after the first search
- **Lock State Machine**: Three states — `null` (auto-lockable), `true` (locked), `false` (user-unlocked)
- **Lock Indicator**: Visual lock icon with tooltip showing locked workspace names
- **Lock/Unlock Modal**: Dialog for manually toggling the scope lock per conversation
- **Workspace Search Container**: Multi-column layout (Scope, Tags, Documents) with connected card UI
- **Automatic Lock on Search**: Scope is automatically locked when AI Search is first used in a conversation
- **Lock State Persistence**: Lock state stored in conversation metadata via API

## Technical Specifications

### Architecture Overview

The scope management system is implemented primarily in `chat-documents.js` with supporting changes in `chats.html` and `route_backend_chats.py`.

**State Variables** (chat-documents.js):

| Variable | Default | Purpose |
|----------|---------|---------|
| `selectedPersonal` | `true` | Whether Personal workspace is selected |
| `selectedGroupIds` | All user group IDs | Array of selected group IDs |
| `selectedPublicWorkspaceIds` | All visible public workspace IDs | Array of selected public workspace IDs |
| `scopeLocked` | `null` | Lock state: `null` (auto-lockable), `true` (locked), `false` (user-unlocked) |
| `lockedContexts` | `[]` | Array of `{scope, id}` objects identifying locked workspaces |

**Name Maps** (built from server data):

| Variable | Source | Purpose |
|----------|--------|---------|
| `groupIdToName` | `window.userGroups` | Maps group IDs to display names |
| `publicWorkspaceIdToName` | `window.userVisiblePublicWorkspaces` | Maps public workspace IDs to display names |

### Scope Dropdown

The `buildScopeDropdown()` function renders the hierarchical checkbox dropdown:

```
Scope Dropdown Structure:
├── [x] Select All / Clear All (toggle)
├── [x] Personal
├── Groups
│   ├── [x] Group A
│   └── [x] Group B
└── Public Workspaces
    ├── [x] Public WS 1
    └── [x] Public WS 2
```

- Checkbox changes trigger `loadAllDocs()` and `loadTagsForScope()` to refresh document and tag lists
- The "Select All / Clear All" checkbox uses an indeterminate state when some items are selected
- The button label shows a summary: "All Workspaces", "Personal", "2 Workspaces", etc.

### Scope Lock State Machine

```
null (auto-lockable)
  │
  ├── First AI Search performed → true (locked)
  │                                  │
  │                                  └── User clicks unlock → false (user-unlocked)
  │                                                              │
  │                                                              └── User clicks lock → true (locked)
  │
  └── User explicitly unlocks → false (user-unlocked)
```

**Lock behaviors**:
- When locked (`true`): Non-locked workspace checkboxes are disabled/grayed out
- When auto-lockable (`null`): Lock engages automatically on first search
- When user-unlocked (`false`): Scope can be freely changed; can be re-locked manually

### Key Functions

| Function | Purpose |
|----------|---------|
| `getEffectiveScopes()` | Returns current `{personal, groupIds, publicWorkspaceIds}` object |
| `buildScopeDropdown()` | Renders the scope checkbox dropdown with current state |
| `rebuildScopeDropdownWithLock()` | Re-renders dropdown with lock indicators on locked items |
| `applyScopeLock(contexts, lockState)` | Applies lock from AI response metadata |
| `toggleScopeLock(conversationId, newState)` | API call to lock/unlock scope |
| `restoreScopeLockState(lockState, contexts)` | Restores lock state when switching conversations |
| `resetScopeLock()` | Resets lock to `null` for new conversations |
| `setScopeFromUrlParam(scopeString, options)` | Legacy URL parameter support for backward compatibility |

### API Integration

**Lock/Unlock Endpoint**:
- `PATCH /api/conversations/<id>/scope_lock`
- Request body: `{"scope_locked": true/false}`
- Updates the conversation document in Cosmos DB with `scope_locked` and `locked_contexts` fields

**Chat Request**: When a message is sent, `getEffectiveScopes()` is called to build the search request. The scopes determine which AI Search indexes are queried.

### Search Container Layout (chats.html)

The workspace search container uses a multi-column flex layout:

```
┌─────────────────────────────────────────────────┐
│ [Scope ▼]  [Tags ▼]  [Documents ▼]             │
├─────────────────────────────────────────────────┤
│ [Message input textarea]                [Send]  │
└─────────────────────────────────────────────────┘
```

- Connected card UI: search container border connects to input field (no border gap)
- Dynamic sizing: dropdown width adapts to parent container
- Viewport boundary detection: prevents dropdown overflow past screen edges

### Lock Indicator UI

When scope is locked:
- A lock icon appears near the scope dropdown
- Tooltip shows the names of locked workspaces
- Locked workspace checkboxes appear grayed out in the dropdown
- A header lock icon shows current conversation lock state

## File Structure

| File | Purpose |
|------|---------|
| `static/js/chat/chat-documents.js` (lines 1-480) | Scope state management, dropdown rendering, lock logic |
| `static/js/chat/chat-messages.js` | Reads `getEffectiveScopes()` to build search requests |
| `templates/chats.html` (lines 430+) | Search container HTML structure, scope dropdown markup |
| `route_backend_chats.py` (lines 63-143) | Scope parameters in chat API, scope lock persistence |
| `route_backend_conversations.py` | Scope lock PATCH endpoint |

## Usage Instructions

### Selecting Workspaces

1. Click the Scope dropdown button in the search container above the chat input
2. Check or uncheck workspaces to include in your search scope
3. Use "Select All / Clear All" to quickly toggle all workspaces
4. Documents and tags will automatically refresh to reflect the selected scope

### Understanding Scope Locking

1. When you start a new conversation, scope is "auto-lockable" (no lock icon shown)
2. After your first message triggers an AI Search, the scope automatically locks to the selected workspaces
3. The lock icon appears, and non-locked workspaces become grayed out
4. To change scope: click the lock icon to open the lock/unlock modal, then unlock to modify selections

### Manual Lock/Unlock

1. Click the lock icon near the scope dropdown (or in the conversation header)
2. In the modal, view the list of currently locked workspaces
3. Click "Unlock" to allow scope changes, or "Lock" to freeze the current selection
4. Lock state is saved per conversation and restored when you switch back

## Testing and Validation

- **Multi-selection**: Select various combinations of workspaces, verify documents load from all selected scopes
- **Auto-lock on search**: Send a message with search enabled, verify scope locks automatically
- **Lock indicator**: Verify lock icon appears, tooltip shows workspace names
- **Unlock/re-lock**: Unlock scope, change selections, re-lock, verify state persists
- **Conversation switching**: Switch between conversations, verify lock state is correctly restored
- **New conversation**: Start a new conversation, verify scope resets to unlocked/auto-lockable
- **API persistence**: Verify PATCH endpoint saves lock state in Cosmos DB conversation document
- **Backward compatibility**: Verify legacy single-scope URL parameters still work via `setScopeFromUrlParam()`
