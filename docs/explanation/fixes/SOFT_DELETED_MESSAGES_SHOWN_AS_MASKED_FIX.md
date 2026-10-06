# Deleted Messages Shown as Masked Fix

Fixed in version: **0.261.257**

Related issue: [#1649](https://github.com/microsoft/simplechat/issues/1649). Gaps in regular masking found while fixing it are tracked in [#1650](https://github.com/microsoft/simplechat/issues/1650).

## Issue

With **Enable Conversation Archiving** on, a message deleted in the V2 chat disappeared and then came back as "This message is masked." It stayed that way every time the conversation was opened. With archiving off the same delete worked, which is why the problem only appeared sometimes.

## Root Cause

When archiving is enabled, `DELETE /api/message/<message_id>` is a soft delete. The message document stays in the messages container with `metadata.is_deleted` set, a copy goes to the archive container, and the message is also masked as a fail-safe. Readers were expected to drop deleted documents, but most did not:

- `/api/get_messages` returned them. The classic chat skipped them in the browser, but V2 did not, so the reload that follows a delete rendered them as masked messages.
- Attempt switching counted deleted attempts and could make one active again.
- Retry and edit copied attempt 1's metadata onto the new question. When attempt 1 had been deleted, the new question was created already deleted and masked.
- Forks and convert-to-shared copied deleted messages into the new conversation, where they also showed as masked.
- Conversation search snippets and the inbound MCP `get_conversation_messages` tool returned their full text.
- Several model paths read them: the summary of older messages (which does not check masks), reuse of earlier tool results, conversation summaries, and diagram-edit grounding.
- The mask routes could clear the fail-safe mask, which V2 offered on the masked placeholder.

Two related defects in the same flow were also fixed:

- Deleting only the latest answer of a retried turn re-activated the lowest-numbered earlier attempt. The old question and answer then showed next to the latest question, which no longer had an answer. This happened with permanent deletes too.
- The V2 attempt control showed the attempt number over the number of attempts, so it could read "3/2" once an attempt had been removed.

## Technical Details

### Files modified

- `application/single_app/functions_message_deletion.py` (new): `is_soft_deleted_message`, `exclude_soft_deleted_messages`, `strip_soft_delete_metadata`, and `NOT_SOFT_DELETED_COSMOS_FILTER` for queries that use `TOP`.
- `application/single_app/route_backend_conversations.py`: message list, search (with a new search-cache key), conversation summary, delete, switch-attempt, retry, and edit.
- `application/single_app/route_backend_chats.py`: history segments, recent assistant replies, the personal mask route, and personal diagram-edit grounding.
- `application/single_app/route_backend_collaboration.py`: the shared mask route and shared diagram-edit grounding.
- `application/single_app/functions_collaboration.py`: personal and group conversion copies, and `list_collaboration_messages`.
- `application/single_app/functions_simplechat_operations.py`: fork document collection.
- `application/single_app/functions_mcp_server_tools.py`: inbound MCP message reads.
- `application/single_app/functions_orchestration_context.py`: orchestration history projection.
- `application/v2_ui/src/lib/deletedMessages.ts` (new), `application/v2_ui/src/stores/chatStore.ts`, `application/v2_ui/src/lib/threads.ts`.
- `application/single_app/config.py`: version `0.261.257`.

### Behavior after the fix

- A soft-deleted message is left out wherever messages are shown, copied, searched, or sent to a model. Its document and archive copy are unchanged, and it keeps its mask as the fail-safe.
- Delete, retry, edit, switch-attempt, and both mask routes return 404 for a soft-deleted message, the same answer as for one that no longer exists.
- Retry and edit take the question's metadata from the earliest attempt that still exists, and never copy deletion markers.
- Attempt promotion happens only when a delete removes the active attempt's question. It never promotes a deleted attempt, and the promoted attempt becomes the only active one.
- Shared conversations created before this fix can still hold copies of deleted messages. `list_collaboration_messages` hides them at read time, so no data migration is needed. Deleting the shared conversation still removes them, because that path queries the container directly.
- V2 drops deleted messages when a conversation loads and when it is re-read, and counts attempts by position within the set the server reports.

The classic chat already skipped deleted messages in the browser. The server-side filtering also fixes its shared-conversation view, so no classic JavaScript changed.

## Validation

### Tests

- `functional_tests/test_chat_soft_deleted_message_visibility_fix.py` imports the real modules in a fresh process with network access blocked and runs them against in-memory Cosmos containers, under normal and optimized Python. It covers every path above, the promotion rules for archived and permanent deletes, and the V2 source contracts.
- `ui_tests/test_v2_chat_deleted_messages.py` runs the production message list, composer, and chat store in Chromium. Its HTTP stub returns deleted messages the way the server did before the fix. The test checks that no "This message is masked" placeholder appears on load or after a delete, and that the attempt control reads "1/2" and "2/2" rather than "3/2".
- `functional_tests/test_v2_message_actions.py`: rationale text updated for the re-read that follows a delete.
- `functional_tests/test_analyze_backend_saved_integration.py`, `functional_tests/test_content_screening_history.py`, and `functional_tests/test_group_collaboration_source_storage_fix.py` load production functions into namespaces they build themselves. They now bind `exclude_soft_deleted_messages` from the real helper module.

### Results

- The new functional test passes under normal and optimized Python. With the server changes reverted, all 21 of its path scenarios fail, each with the symptom it describes.
- The UI test passes. With the V2 changes reverted, it shows two "This message is masked" placeholders after load, and the attempt control does not read "2/2".
- The related functional suites (conversation routes, retry and edit, forks, sharing, search, MCP, history, orchestration context, masking, export) show no failure that the unmodified code does not also show.
- The V2 typecheck and production build pass.

### Before and after

| Scenario (archiving on) | Before | After |
| --- | --- | --- |
| Delete a message in V2 | Returns as "This message is masked" | Stays removed |
| Reopen the conversation | Deleted messages show as masked | Not shown |
| Delete the latest answer of a retried turn | An older attempt reappears beside the latest question | The latest question stays, without the deleted answer |
| Switch attempts after deleting one | Can land on the deleted attempt | Deleted attempts are skipped |
| Fork or share a conversation | Deleted messages are copied | Not copied |
| Search or MCP read | Deleted text is returned | Not returned |
| Summary of older messages sent to the model | Includes deleted text | Excludes it |
