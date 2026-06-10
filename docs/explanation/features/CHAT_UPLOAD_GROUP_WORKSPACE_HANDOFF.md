# Chat Upload Group Workspace Handoff

Implemented in version: **0.241.176**

## Overview

Chat uploads in group-scoped conversations now use the group workspace document pipeline instead of chat-local file storage. This keeps uploaded files in the group workspace, lets the standard document processor index them, and makes the document easy to reference in follow-up questions.

## Technical Specifications

The upload route resolves a group destination from the current chat scope, validates that the selected group is part of the conversation or effective group scope, and enforces one of the write roles: `Owner`, `Admin`, or `DocumentManager`.

Regular group chats and group multi-user collaboration chats both queue files through `queue_group_workspace_upload_from_temp_file()`. Group collaboration uploads still mirror a workspace-backed file message into the visible collaborative conversation, while the hidden source conversation stores the canonical message.

Duplicate source filenames are isolated with `resolve_unique_group_workspace_file_name()`, using the same suffix pattern as workspace/file-sync duplicate handling. This prevents repeated chat uploads from becoming accidental revisions of an existing group workspace document.

Group uploaded documents are marked with `source_type: chat_upload`, conversation metadata, the selected `chat_upload_group_id`, and a clean `conversations` tag. Conversation IDs stay in metadata rather than becoming folder/tag clutter.

## User Workflow

When a chat is group-scoped and exactly one writable group workspace is available, uploads go directly to that group workspace. When multiple writable group workspaces are in scope, the browser shows a group-only picker. Personal workspace is not offered as a group upload destination.

If the user can chat in a group but lacks a write role, the upload is blocked. If group workspaces are disabled or the file type cannot be processed by the workspace pipeline, the upload fails clearly rather than falling back to chat-local storage.

## Testing and Validation

Functional coverage is provided by `functional_tests/test_chat_upload_group_workspace_handoff.py`.

The test validates:

- Group workspace queue helper and unique group filename resolution.
- Server-side group target and write-role enforcement.
- Group search cache invalidation and group metadata stamping.
- Frontend group destination picker and form payload.
- Linked group upload lookup for chat search and conversation delete lifecycle.

Related config update: `application/single_app/config.py` was bumped to **0.241.176**.
