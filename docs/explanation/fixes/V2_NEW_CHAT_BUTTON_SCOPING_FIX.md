# V2 New Chat Button Scoping Fix

## Issue

In the V2 interface the **New chat** button sat at the top of the navigation rail on every
page. Away from the chat page it did nothing at all: clicking it on **My Workspace**,
**Admin Settings** or **Settings** produced no visible response of any kind.

It was not much better on the chat page. Nothing about it read as clickable — the mouse
pointer stayed an arrow over it, as it did over every other button in the interface — and
pressing it could leave the conversation drawer stranded open and empty with no way to
dismiss it from the header.

**Fixed in version:** 0.261.041

## Root cause

Three unrelated causes, all meeting at one control.

### The button never navigated

`Sidebar.tsx` wired the button directly to the store action:

```tsx
<button type="button" onClick={startNewConversation}>
```

`startNewConversation` is a pure state reset. It stops any running stream and clears
`activeConversationId`, `messages` and `metadata`, and that is all it does — the V2 source
tree contains no `useNavigate` and no router navigation anywhere. On the chat page that
reset is the whole job, because the chat page is already on screen. On any other page it
reset state the reader could not see and left them exactly where they were.

### Tailwind v4 removed the pointer cursor from buttons

The V2 interface is built on Tailwind v4. Its Preflight base styles deliberately dropped
the v3 rule `button, [role="button"] { cursor: pointer }` so that buttons inherit the
browser default, which is `cursor: default` — the arrow used for inert text. `theme.css`
never restored it, and the interface uses the `cursor-pointer` utility in only a handful of
places, none of them an actual button.

Every button in the V2 interface was therefore affected, not just this one: the chat header
icons, conversation rows, composer controls and the admin controls all rendered as though
they were not interactive.

### The reset left the drawer behind

`startNewConversation` cleared `metadata` but left `drawerMode` set, while `ChatHeader`
draws the **Contents** and **Documents** toggles only when `activeConversationId` is
truthy. Starting a new chat with the drawer open therefore left an empty drawer on screen
whose toggles had disappeared with the conversation they belonged to. Conversation details,
held in `ChatPage` local state, survived the same way.

This is the V2 counterpart of a fault already corrected in the classic interface in
v0.260.004 (`NEW_CHAT_CONVERSATION_DOCUMENTS_DRAWER_RESET_FIX.md`, Fixes #1298).

### A fourth thing that had to change first

Removing the button from other pages would have left no way to start a new chat from them,
because navigating to the chat page does not start one. The chat store is ordinary
in-memory state with no persistence middleware, so `activeConversationId` outlives a
client-side route change. Arriving at `/chat` with nothing in the query string, the URL
sync effect writes the previously open conversation back into the address bar and reopens
it. Returning to **Chats** resumed reading rather than starting fresh.

## The fix

**New chat** is now drawn only on the chat page, where it has something to act on.

The **Chats** navigation item covers the case that leaves behind: clicking it from any
other page starts a fresh chat, which is what makes a new chat reachable from anywhere in
the application.

Two exceptions are deliberate:

- Clicking **Chats** while already on the chat page does nothing, so a stray click on the
  highlighted navigation item cannot discard the conversation being read.
- A conversation still streaming a reply is returned to rather than reset, because the
  reset stops the stream and the reply in flight would be lost.

The `streaming` flag is read from the store inside the click handler rather than subscribed
to. It changes with every token delivered, and subscribing would re-render the rail — the
whole conversation list with it — throughout every response.

Deep links are untouched. The reset lives in the navigation item's click handler, so a
fresh load of `/v2/chat?conversationId=<id>` never passes through it.

Alongside that, the pointer cursor is restored once in the base layer rather than as a
utility on each button, since the affordance is not something an individual button should
have to opt into. `:not(:disabled)` keeps the `disabled:cursor-not-allowed` utilities used
throughout the application correct. Starting a new chat now closes the drawer, and the
conversation details panel can no longer outlive the conversation it describes.

## Files modified

| File | Change |
|---|---|
| `application/v2_ui/src/components/layout/Sidebar.tsx` | **New chat** gated on the chat route; **Chats** starts a fresh chat on arrival from elsewhere, guarded on route and stream; nav list spacing follows the button |
| `application/v2_ui/src/styles/theme.css` | Pointer cursor restored for enabled buttons in the base layer |
| `application/v2_ui/src/stores/chatStore.ts` | `startNewConversation` also clears `drawerMode` |
| `application/v2_ui/src/pages/ChatPage.tsx` | Conversation details gated on an open conversation |
| `application/single_app/config.py` | Version to 0.261.041 |
| `functional_tests/test_v2_new_chat_scoping.py` | New test |

## Validation

`functional_tests/test_v2_new_chat_scoping.py` — 6/6 checks passed. It asserts that the
button is gated on the chat route and still starts a conversation, that the nav list only
carries the button's separating margin when the button is present, that arriving at the
chat page from elsewhere resets, that the reset is guarded on both the current route and
the streaming flag with the guard preceding the reset, that `streaming` is read through
`getState()` rather than subscribed, that `startNewConversation` clears `drawerMode`
alongside `metadata`, that conversation details is gated, and that the base layer carries
the pointer rule with its `:not(:disabled)` exclusion.

The same test was run against the pre-fix source and failed all six checks, so each one
covers a real regression rather than restating the implementation.

`npm run typecheck` and `npm run build` both succeed. The compiled stylesheet contains
`button:not(:disabled),[role=button]:not(:disabled){cursor:pointer}` and no competing
`cursor:default` rule, while `cursor:not-allowed` survives for disabled controls.

Eight neighbouring V2 test files were re-run and still pass, including
`test_v2_conversation_deep_link.py`, which reads `Sidebar.tsx` and `ChatPage.tsx`.

### Before and after

| Action | Before | After |
|---|---|---|
| Hover any button in the V2 interface | Arrow cursor | Pointer cursor |
| **New chat** on My Workspace, Admin or Settings | Visible, does nothing | Not shown |
| **Chats** from another page | Reopens the last conversation | Starts a new chat |
| **Chats** from another page while a reply streams | Reopens the last conversation | Returns to it, stream intact |
| **Chats** while already on the chat page | Nothing | Unchanged |
| **New chat** on the chat page with the drawer open | Drawer stays open and empty, toggles gone | Drawer closes |
| **New chat** with conversation details open | Panel describes the conversation just left | Panel closes |
| Opening `/v2/chat?conversationId=<id>` | Opens that conversation | Unchanged |

## Related

- Feature documentation: `docs/explanation/features/REACT_V2_UI.md`
- Classic interface counterpart: `docs/explanation/fixes/NEW_CHAT_CONVERSATION_DOCUMENTS_DRAWER_RESET_FIX.md`
