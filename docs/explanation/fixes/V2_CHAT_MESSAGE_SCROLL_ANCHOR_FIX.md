# V2 Chat Message Scroll Anchoring Fix (v0.261.318)

## Issue

A long incoming message took the reader to its end instead of its beginning.
After an AI response finished streaming, reading it required scrolling backward.
Readers looking through earlier history had no V2 new-message arrow to return
to the current discussion without losing their place automatically.

## Fixed/Implemented in version: **0.261.318**

The application version is recorded in `application/single_app/config.py`.
This fix applies to React V2 personal and collaborative conversations, including
shared group conversations. The classic interface is unchanged.

## Root cause

`MessageList.tsx` followed `scrollHeight` whenever the messages array or live
content changed. Its resize observer repeated that bottom-scroll when an image,
diagram, or card grew after rendering. A completed long reply therefore stayed
at the bottom, and changing just the message effect would not fix delayed growth.

Array changes also describe edits, optimistic ID acknowledgements, attempt
switches, and shared-message echoes. They do not necessarily mean a new message
has arrived.

## Behavior

| Situation | Reading behavior |
| --- | --- |
| A completed message arrives while the reader is caught up | Its beginning appears with a small reading margin. Short messages remain visible within the available scroll range. |
| An AI reply is streaming and the reader is following | The latest streaming line stays visible. |
| The reply finishes while the reader is still following | The pane returns once to the beginning of that completed reply. |
| The reader scrolls upward during a stream or reads earlier history | New content and completion preserve their reading position. |
| New content arrives while the reader is looking earlier | **New messages**, with a down arrow, appears above the composer. |
| The reader activates the arrow | The newest rendered message opens at its beginning. The indication clears and live output does not immediately drag the reader down again. |

Manually scrolling back to the bottom resumes live following. The indicator is
local to the message pane, not a server unread count, and does not announce every
streaming token. Loading saved history retains the existing history-opening
behavior. Changing conversations or starting a new chat clears the local state.

## Technical details

| File | Change |
| --- | --- |
| `application/v2_ui/src/lib/messageScroll.ts` | Typed arrival identity, message-start geometry, and the existing 80-pixel follow threshold. Updates, source-message echoes, removed optimistic placeholders, and replaced thread attempts are not new arrivals. |
| `application/v2_ui/src/components/chat/useMessageScroll.ts` | Separate live-following, message-reading, and manual-reading modes. Ref-based geometry and reading anchors keep delayed content growth from forcing a bottom jump. |
| `application/v2_ui/src/components/chat/MessageList.tsx` | Stable rendered-message/live-reply targets and a keyboard-operable new-content arrow using existing local icons and theme tokens. Message bubbles remain memoized. |
| `application/v2_ui/src/stores/chatStore.ts` | A client-only completed-reply reference identifies the actual saved reply for normal and orchestrated stream completion, even when its shared broadcast arrived first. |
| `application/v2_ui/src/components/chat/PendingActionSlots.tsx` | Explicit notification-card navigation pauses automatic following before moving and focusing the card. |
| `application/single_app/config.py` | Application patch version to `0.261.318`. |

Scrolling is contained within the chat pane. Automatic positioning does not move
keyboard focus or scroll the page. Jumps are immediate, including with reduced
motion enabled. No backend endpoints, SSE payload contracts, permissions, server
read receipts, capability settings, dependencies, or deployment versions change.

An interrupted, stopped, or planning-only stream is not treated as successful
answer completion. Partial saved replies remain readable without navigating to
an older reply.

## Testing and validation

`functional_tests/test_v2_chat_message_scroll.mjs` executes the production pure
helpers for identity reconciliation, thread replacement, viewport offsets, and
the exact near-bottom threshold.

`ui_tests/test_v2_chat_message_scroll.py` mounts the production message list,
composer, stores, and CSS. It checks real viewport geometry for long human and AI
messages, incremental streaming, completion, manual override, arrow navigation,
shared terminal/broadcast ordering, ID reconciliation, delayed growth, loading,
conversation resets, short messages, and non-answer terminal states. It also
exercises the production personal SSE reader with controlled frames and the
actual orchestration completion handler.

The shared Playwright connection fixture supports local Chromium or a configured
Azure Playwright workspace without provisioning resources or storing credentials.
Desktop/mobile and light/dark checks verify that the arrow remains inside the
message pane above the composer. Related streaming, collaboration, and outgoing
action-card suites protect existing behavior.

### Commands

```powershell
node .\functional_tests\test_v2_chat_message_scroll.mjs
npm --prefix .\application\v2_ui run build -- --outDir ..\..\ui_tests\artifacts\orchestration-plan-editor
python -m pytest .\ui_tests\test_v2_chat_message_scroll.py .\ui_tests\test_v2_orchestration_streaming_bubble.py .\ui_tests\test_v2_collaboration_ux.py .\ui_tests\test_v2_m365_pending_action_cards.py -q -k "not composer_mentions_become_chips_and_are_sent_as_mentions"
python -m pytest .\functional_tests\test_v2_stream_reconnect.py .\functional_tests\test_v2_stream_leave_without_cancel.py .\functional_tests\test_v2_m365_pending_actions.py -q
python .\scripts\build_docs_inventory.py
python .\functional_tests\test_docs_app_surface_coverage.py
python .\functional_tests\test_docs_site_quality.py
```

### Results

| Check | Result |
| --- | --- |
| Production scroll-policy helpers | Passed |
| TypeScript/Vite build | Passed; existing bundle-size advisory |
| Targeted V2 browser suite | 47 passed, one known baseline test deselected |
| Stream lifecycle and pending-action functional contracts | 39 passed; existing return-value warnings |
| Documentation coverage | 7/7 passed; regenerated inventory has no semantic changes |
| Documentation site quality | 6/6 passed |
| XSS boundary check for the five changed TypeScript/TSX files | Passed |
| Whitespace check | Passed |

The existing collaboration mention-chip test
`test_composer_mentions_become_chips_and_are_sent_as_mentions` can time out when
typing the next mention immediately after selection: a scheduled caret reset
can produce `Resp@` instead of `@Resp`. This was reproduced using the unchanged
`HEAD` message list, pending-action slots and chat store in a separate generated
harness. It is not caused by the scroll fix and is left out of scope.

The generated control inventory still describes classic-template controls.
The V2 arrow is documented separately in the
[chat controls reference](../../reference/chat-controls.md) and the
[collaboration guide](../../guides/collaborate-in-a-conversation.md).
