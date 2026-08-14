# User Message Metadata Streaming Fix

**Issue:** Newly submitted user-message metadata remained unavailable until the assistant response completed.

**Root cause:** The backend persisted the user message before model work but returned its real ID only in the terminal SSE event. The browser therefore retained a `temp_user_*` ID throughout streaming, and a metadata drawer opened during that interval retried the stale ID.

**Fixed/Implemented in version: `0.250.202`**

**Related config.py update:** `VERSION = "0.250.202"`

**Tracking:** `microsoft/simplechat#1244`

## Technical details

### Files modified

- `application/single_app/functions_chat_stream_events.py`
  - Defines the shared `user_message_persisted` SSE payload and serializer.
- `application/single_app/route_backend_chats.py`
  - Emits the persistence event after successful user-message storage in standard, document-action, analyze, and image-generation compatibility streams.
- `application/single_app/route_backend_collaboration.py`
  - Emits the collaboration-local user message ID and suppresses the corresponding source-conversation event.
- `application/single_app/static/js/chat/chat-streaming.js`
  - Reconciles the temporary DOM message ID, carries acknowledged IDs through recovery, refreshes expanded metadata after terminal enrichment, and distinguishes unconfirmed persistence from unconfirmed finalization after disconnect.
- `application/single_app/static/js/chat/chat-messages.js`
  - Uses the current DOM ID for metadata actions, transitions an open drawer from saving to loading, cancels stale retries, and keeps Mask/Edit/Delete/Retry disabled until terminal completion.
- `application/single_app/static/js/chat/chat-collaboration.js`
  - Re-enables ordinary non-AI shared-message actions after their REST persistence response while AI turns stay gated by stream completion.
- `functional_tests/test_message_metadata_loading_fix.py`
  - Validates the SSE contract, route ordering, collaboration translation, client handling, and terminal fallback.
- `ui_tests/test_chat_user_message_metadata_during_stream.py`
  - Verifies metadata loads under the real ID while the assistant placeholder remains active.

### Event lifecycle

1. The browser renders the submitted user message with a temporary ID.
2. The backend authorizes the conversation and persists the user message.
3. The stream sends:

   ```json
   {
     "type": "user_message_persisted",
     "conversation_id": "<authorized-conversation-id>",
     "user_message_id": "<persisted-user-message-id>",
     "message_persisted": true
   }
   ```

4. The browser updates the message element, metadata button, `aria-controls`, and metadata container ID.
5. If the metadata drawer is already open, it immediately requests the existing authorized metadata endpoint with the persisted ID.
6. Assistant generation continues. The terminal event retains `user_message_id` and refreshes an expanded drawer so later capability/model enrichment is visible.
7. If the stream fails before an acknowledgement arrives, the drawer reports that persistence could not be confirmed instead of incorrectly claiming the message was not saved.
8. If a confirmed stream disconnects before terminal enrichment, the drawer reports that metadata may still be updating and directs the user to refresh instead of freezing a pre-final snapshot.
9. Mask, Edit, Delete, and Retry remain disabled from temporary rendering through stream termination so early ID reconciliation cannot mutate an in-flight turn.

### Security and compatibility

- The event contains identifiers and persistence state only; it does not expose raw settings or message metadata.
- Metadata remains protected by the existing `/api/message/<message_id>/metadata` authorization boundary.
- Collaboration streams expose the collaboration-local message ID rather than the internal source-conversation ID.
- Assistant metadata behavior is unchanged and remains deferred until the assistant message is persisted.

## Validation

### Test coverage

- Shared SSE payload and serialization.
- Persistence-event ordering after Cosmos DB storage and before assistant work.
- Standard, document-action, analyze, image-generation, and collaboration stream wiring.
- Collaboration source-event suppression and local-ID reconciliation.
- Browser handling before terminal completion.
- Open-drawer recovery without a refresh.
- Terminal refresh after server-side metadata enrichment.
- Pre-acknowledgement stream failure handling without false storage claims.
- Post-acknowledgement disconnect handling without freezing pre-final metadata.
- Stale metadata request suppression.
- Recovery handoff with the acknowledged user message ID.
- Mask/Edit/Delete/Retry gating during generation.
- Terminal `user_message_id` fallback preservation.

### Before and after

| Scenario | Before | After |
|---|---|---|
| Open user metadata while AI is running | Temporary-ID error | Metadata loads after the persistence event |
| Refresh during AI processing | Metadata appears only after reload | Reload is unnecessary |
| Open drawer before ID acknowledgement | Retry retains stale ID | Drawer shows a saving state, then loads automatically |
| Metadata enriched later in the stream | Early snapshot remains stale | Expanded drawer refreshes on terminal completion |
| Stream fails before persistence is acknowledged | Saving state can remain indefinitely | Drawer reports an unconfirmed state and directs the user to refresh |
| Stream disconnects after persistence acknowledgement | Pre-final metadata can appear complete | Drawer reports that finalization is unconfirmed and directs the user to refresh |
| Mask/Edit/Delete/Retry during generation | Early real ID can mutate or overwrite an in-flight turn | Mutating actions remain disabled until terminal completion |
| Collaboration stream | Source/local ID timing depended on terminal event | Local collaboration ID is acknowledged immediately |
| Assistant metadata while running | Unavailable | Unchanged; available after assistant persistence |

### User experience improvement

Users can inspect the submitted message's metadata during long-running model, tabular, document-analysis, image-generation, and shared-chat operations without interrupting the stream or refreshing the page.
