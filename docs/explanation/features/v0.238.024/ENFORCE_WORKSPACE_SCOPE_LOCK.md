# ENFORCE_WORKSPACE_SCOPE_LOCK.md

**Feature**: Enforce Workspace Scope Lock
**Version**: v0.238.025
**Dependencies**: Azure Cosmos DB, Flask Backend, Bootstrap 5

## Overview and Purpose

The Enforce Workspace Scope Lock feature adds an admin setting that controls whether users can unlock workspace scope in chat conversations. Workspace scope automatically locks after the first AI search to prevent accidental cross-contamination between data sources. With this setting enabled (the default), users cannot unlock scope, ensuring conversations remain restricted to the workspaces that produced search results.

## Key Features

- **Admin Toggle**: New "Enforce Workspace Scope Lock" toggle in Admin Settings > Workspace tab
- **Enabled by Default**: The setting defaults to `True`, preventing users from unlocking scope
- **Informational Modal**: When enforced, users can still click the lock icon to view which workspaces are locked, but the "Unlock Scope" button is hidden
- **Administrator Message**: The modal displays an informational alert explaining that scope lock is enforced by the administrator
- **Backend Enforcement**: Server-side validation rejects unlock API requests when the setting is enabled, providing defense-in-depth
- **Non-Breaking**: Disabling the setting restores the previous behavior where users can freely unlock and re-lock scope

## Technical Specifications

### Setting Configuration

| Property | Value |
|----------|-------|
| Setting Key | `enforce_workspace_scope_lock` |
| Default Value | `True` |
| Type | Boolean |
| Storage | Cosmos DB `app_settings` document |

### Architecture Overview

The feature touches four layers:

1. **Settings Layer** (`functions_settings.py`): Default value in the settings defaults dict
2. **Admin Layer** (`route_frontend_admin_settings.py`, `admin_settings.html`): Toggle UI and form processing
3. **Frontend Layer** (`chats.html`, `chat-documents.js`): Passed via `window.appSettings`, checked in modal show handler
4. **API Layer** (`route_backend_conversations.py`): Server-side enforcement on PATCH `/api/conversations/<id>/scope_lock`

### Frontend Behavior

When `enforce_workspace_scope_lock` is `true` and scope is locked:
- Lock icons in the chat header and scope dropdown remain visible and clickable
- The scope lock modal opens and displays locked workspace information
- The "Unlock Scope" button is hidden via Bootstrap `d-none` class
- The alert message changes to: "Workspace scope lock is enforced by your administrator. The scope cannot be unlocked."

When scope is unlocked (e.g., conversation created before setting was enabled):
- The "Lock Scope" button remains available (locking is always permitted)

### API Enforcement

The PATCH `/api/conversations/<conversation_id>/scope_lock` endpoint checks the setting server-side:
- If `scope_locked: false` is requested and `enforce_workspace_scope_lock` is `True`, returns HTTP 403
- If `scope_locked: true` is requested, the request proceeds normally regardless of the setting

### Files Modified

| File | Change |
|------|--------|
| `config.py` | Version bump to `0.238.025` |
| `functions_settings.py` | Added `enforce_workspace_scope_lock: True` default |
| `route_frontend_admin_settings.py` | Added default check, form extraction, and `new_settings` entry |
| `templates/admin_settings.html` | Added Workspace Scope Lock card in Workspace tab |
| `templates/chats.html` | Added setting to `window.appSettings` object |
| `static/js/chat/chat-documents.js` | Added enforcement check in modal show handler |
| `route_backend_conversations.py` | Added server-side enforcement in scope lock PATCH endpoint |

## Usage Instructions

### Enabling (Default)

1. Navigate to **Admin Settings** > **Workspace** tab
2. Scroll to the **Workspace Scope Lock** section (between Retention Policy and User Agreement)
3. Ensure the **Enforce Workspace Scope Lock** toggle is checked
4. Save settings

Users will see their scope lock as usual but will not be able to unlock it.

### Disabling

1. Navigate to **Admin Settings** > **Workspace** tab
2. Uncheck the **Enforce Workspace Scope Lock** toggle
3. Save settings

Users will regain the ability to unlock scope via the lock icon modal.

## Testing and Validation

1. **Admin UI**: Verify toggle appears in Workspace tab, persists across saves
2. **Enforcement ON**: Lock scope in a conversation, click lock icon, verify modal shows info but no unlock button
3. **Enforcement OFF**: Disable setting, verify unlock button reappears in modal
4. **Backend**: With enforcement ON, use dev tools to call `PATCH /api/conversations/{id}/scope_lock` with `{scope_locked: false}` — verify 403 response
5. **Locking allowed**: With enforcement ON and an unlocked conversation, verify the "Lock Scope" button still works
