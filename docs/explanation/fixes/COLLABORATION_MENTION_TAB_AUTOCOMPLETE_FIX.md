# Collaboration Mention Tab Autocomplete Fix

Fixed in version: **0.260.004**

Related issue: [#1299](https://github.com/microsoft/simplechat/issues/1299)

## Issue Description

In multi-user (collaborative) conversations, typing `@` in the chat composer opens the participant and AI target suggestion menu. Arrow keys moved the highlight and <kbd>Enter</kbd> accepted the highlighted entry, but <kbd>Tab</kbd> did nothing to the menu.

Because <kbd>Tab</kbd> fell through to the browser default, pressing it moved focus out of the message box, the menu closed on blur, and the partially typed `@par` text was left behind. Most users expect <kbd>Tab</kbd> to complete an autocomplete entry, so the mention menu felt broken even though <kbd>Enter</kbd> worked.

The behavior was also inconsistent with the agent-instruction mention menu (`static/js/agent_instruction_mentions.js`), which already treated <kbd>Tab</kbd> and <kbd>Enter</kbd> as the same "accept" action.

## Root Cause Analysis

- `handleComposerKeydown()` in `application/single_app/static/js/chat/chat-collaboration.js` only branched on `ArrowDown`, `ArrowUp`, `Enter`, and `Escape`. There was no `Tab` branch, so the function returned `false`.
- The `#user-input` keydown listener in `chat-messages.js` only short-circuits when `window.chatCollaboration.handleComposerKeydown(e)` returns `true`. A `false` return meant the browser applied its default focus-movement behavior for <kbd>Tab</kbd>.
- The selection logic (participant tag vs. AI invocation target vs. invite confirmation) was written inline inside the `Enter` branch, so there was no reusable entry point another key could call.

A related accessibility gap surfaced in the same code path: `#collaboration-mention-menu` is declared `role="listbox"` in `templates/chats.html`, but `renderMentionMenu()` created plain `<button>` elements with no `role="option"` or `aria-selected`. Assistive technology could not announce which suggestion was highlighted during keyboard navigation.

## Technical Details

### Files Modified

- `application/single_app/static/js/chat/chat-collaboration.js`
- `application/single_app/config.py`
- `functional_tests/test_collaboration_mention_tab_autocomplete.py`
- `ui_tests/test_chat_collaboration_mention_tab_selection.py`

### Code Changes Summary

- Extracted the inline `Enter` selection logic into a shared `selectActiveMentionSuggestion()` helper so every "accept" key routes through one implementation of the participant tag, `ai_tag` invocation target, and invite-confirmation branches.
- Added a `hasActiveMentionSuggestion()` guard that reports whether there is a real highlighted suggestion to accept.
- Added a `Tab` branch to `handleComposerKeydown()` that accepts the highlighted suggestion, calls `event.preventDefault()` so focus stays in the composer, and returns `true`.
- Left <kbd>Shift</kbd>+<kbd>Tab</kbd> unhandled so it keeps the browser's normal focus-backwards behavior, and left <kbd>Tab</kbd> unhandled in the empty-results state so focus movement still works when there is nothing to complete.
- Kept the `Enter` guard (`activeMentionState.activeIndex >= 0`) unchanged so unrelated <kbd>Enter</kbd> presses still send the message.
- Exposed each suggestion as a listbox option with a stable id (`collaboration-mention-option-{index}`), `role="option"`, and `aria-selected`, and pointed the composer at the highlighted option through `aria-activedescendant`.
- Paired `aria-activedescendant` with `aria-controls` and `aria-autocomplete="list"` on `#user-input`. ARIA 1.2 only resolves `aria-activedescendant` from a focused textbox when the referenced option is a descendant of the element named by `aria-controls`, and `#collaboration-mention-menu` is a sibling of the composer rather than a descendant. All three attributes are applied only while the menu is open and removed when it closes, so the composer stays a plain textbox the rest of the time.
- Kept `aria-selected` and `aria-activedescendant` in sync during arrow-key navigation, cleared the combobox attributes when the menu closes or shows the empty state, and scrolled the highlighted option into view inside the height-capped (`max-height: 240px`) menu.
- Marked the "No matching participants..." row as a disabled option so the `role="listbox"` container keeps only valid children.
- Updated `config.py` to version `0.260.004` for this fix.

### Behavior Matrix

| Key | Menu open with results | Menu open, no results | Menu closed |
| --- | --- | --- | --- |
| <kbd>Tab</kbd> | Accepts the highlighted suggestion, focus stays in the composer | Normal focus movement | Normal focus movement |
| <kbd>Shift</kbd>+<kbd>Tab</kbd> | Normal focus movement | Normal focus movement | Normal focus movement |
| <kbd>Enter</kbd> | Accepts the highlighted suggestion (unchanged) | Sends the message (unchanged) | Sends the message (unchanged) |
| <kbd>ArrowUp</kbd> / <kbd>ArrowDown</kbd> | Moves the highlight (unchanged) | No-op | No-op |
| <kbd>Escape</kbd> | Closes the menu (unchanged) | Closes the menu | Clears an active reply target |

## Validation

### Test Results

- `functional_tests/test_collaboration_mention_tab_autocomplete.py` — 5/5 tests passed. It parses the real `handleComposerKeydown()`, `selectActiveMentionSuggestion()`, `renderMentionMenu()`, `updateMentionMenuActiveItem()`, and `hideMentionMenu()` bodies out of the module and asserts the Tab branch, the `shiftKey` guard, the guard-before-`preventDefault()` ordering, the shared selection path, and the listbox ARIA wiring.
- The same test was run against the pre-fix source and failed 3/5 as expected, confirming it is a real regression test rather than a tautology.
- `ui_tests/test_chat_collaboration_mention_tab_selection.py` — new Playwright regression test that seeds deterministic agent mention targets, opens the menu on `/chats`, and asserts <kbd>Tab</kbd> inserts the highlighted mention while focus stays on `#user-input`, that <kbd>ArrowDown</kbd> plus <kbd>Tab</kbd> inserts the second suggestion, that <kbd>Enter</kbd> is unchanged, and that <kbd>Shift</kbd>+<kbd>Tab</kbd> inserts nothing and moves focus away.

### Before and After

| Observation | Before | After |
| --- | --- | --- |
| Mention menu handles <kbd>Tab</kbd> | `false` | `true` |
| <kbd>Tab</kbd> prevents default focus movement | No | Yes |
| Suggestions inserted on <kbd>Tab</kbd> | 0 | 1 |
| Suggestions inserted on <kbd>Enter</kbd> | 1 | 1 (unchanged) |
| Suggestions exposed with `role="option"` | 0 | 1 per suggestion |
| `aria-activedescendant` on the composer | absent | tracks the highlighted option |
| `aria-controls` / `aria-autocomplete` on the composer | absent | applied while the menu is open, removed when it closes |

### User Experience Improvements

- <kbd>Tab</kbd> now completes an `@` mention the way users expect from other editors and chat clients.
- Focus no longer jumps out of the message box mid-sentence, so the typed `@` fragment is not left behind.
- The chat mention menu now matches the agent-instruction mention menu, which already accepted <kbd>Tab</kbd>.
- Screen reader users hear which suggestion is highlighted while arrowing through the list, and the highlighted suggestion stays scrolled into view.
