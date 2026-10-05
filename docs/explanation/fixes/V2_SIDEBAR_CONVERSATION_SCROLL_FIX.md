# V2 Sidebar Conversation Scroll Fix

## Issue

On the V2 chat page, the navigation rail kept its full height for the primary navigation
(**Chats** through **Content review**) and the administrator's link groups (**External
Links**, **Custom Pages**). The conversation list scrolled in whatever height was left.
With two external links configured, a 720-pixel-tall window showed two conversations at a
time. Anyone with more than a handful of conversations spent their time scrolling a strip
two rows tall, while most of the rail held navigation they had already passed.

The classic interface has avoided this since 0.250.002
([Whole Sidebar Scroll Fix](WHOLE_SIDEBAR_SCROLL_FIX.md), #1098). Its whole sidebar body
scrolls as one panel, and the **Conversations** heading stays pinned.

Tracked in #1642.

**Fixed in version:** 0.261.235

## Root cause

`Sidebar.tsx` laid the rail out as one flex column: brand row, **New chat**, the
navigation list, `NavExtras`, then `ConversationRail` in a `min-h-0 flex-1` wrapper.
`ConversationRail` gave its list its own `overflow-y-auto`. The navigation items were flex
items that could not shrink below their content, so they kept their full height, and the
list was handed only the remainder. Nothing above the list could ever scroll out of the
way.

A second problem came from the first. The workflow alert notice
([V2 Workflow Alert Notices](../features/V2_WORKFLOW_ALERT_NOTICES.md)) hung from the
**My Workspace** item. Once the navigation can scroll away, the notice can be carried off
screen with it.

## Technical details

### Files modified

| File | Change |
|---|---|
| `application/v2_ui/src/components/layout/Sidebar.tsx` | One scroll region wraps the navigation list, `NavExtras` and `ConversationRail`. It scrolls only on the chat page with the rail expanded. The old flex wrapper and spacer are gone, and the alert slot and its `relative` are removed from **My Workspace**. |
| `application/v2_ui/src/components/chat/ConversationRail.tsx` | No scroller of its own. The search header is `sticky` and marked `data-stuck` while held. Paging watches the rail's region. The section keeps the region's height while a search is active, and keyboard focus is kept clear of the held header. |
| `application/v2_ui/src/components/layout/NotificationBell.tsx` | The bell's wrapper takes the layout classes and renders the workflow alert notice's slot right after the bell. |
| `application/v2_ui/src/components/notifications/WorkflowAlertNotice.tsx` | The slot positions the notice from the bell: dropping from it when the rail is expanded, flying out beside it when collapsed. |
| `application/v2_ui/src/components/notifications/WorkflowAlertNotice.css` | The notch comment names its new target and the offsets the slot relies on. |
| `application/single_app/config.py` | Version to 0.261.235. |
| `functional_tests/test_v2_sidebar_conversation_scroll.py` | New source-level test. |
| `ui_tests/test_v2_sidebar_conversation_scroll.py` | New browser test. |
| `ui_tests/test_v2_workflow_alert_notices.py` | Updated for the bell anchor, plus a scrolled-rail regression. |

### Code changes

**One scroll region.** Everything between **New chat** and the theme and account footer
now sits in a single `div` that is `flex-1 min-h-0 overflow-y-auto` while the conversation
list is shown. Reading down the list carries the navigation and the link groups up out of
view. Scrolling back up brings them back. The brand row, **New chat** and the footer are
outside the region and never move.

Elsewhere, meaning other pages and the collapsed strip, the region is only `flex-1`. That
fills the height the footer leaves exactly as the old spacer did, so those layouts are
unchanged.

**Search held under New chat.** The list's search header is `sticky top-0` inside the
region, so it stops right under **New chat**. When rows are selected, the bulk-selection
bar is part of the same header and is held too. The header's `pt-3` is the old wrapper's
top padding moved inside it, so the resting layout is identical. While held, the header gets
a solid `--surface-solid` backing and a 1px `--edge-strong` shadow, so rows passing beneath
don't show through the glass. At rest it stays transparent.

An IntersectionObserver, rooted on the region, watches a 1-pixel marker at the section's
top and toggles `data-stuck` on the header. The marker is written to the DOM node rather
than kept in React state, because state would re-render every row each time the header
crossed the threshold.

**Paging look-ahead.** The paging observer now uses the region as its `root`. Measured
against the viewport, the region's edge clipped the `120px` look-ahead margin, so the next
page waited until the last row was already on screen. The same clipping applied to the old
nested scroller.

**A search that doesn't jump.** While a search term is set, the conversation section keeps
at least the region's height (`min-h-full`). Without it, typing a search while the header
is held shrinks the list and the scroll range. The navigation then scrolls back into view,
pulling the search box down from under the reader's cursor.

**Keyboard focus never hidden (WCAG 2.4.11).** The browser only scrolls a focused control
into view when the control lies outside the scroll region. A row control just under the
held search lies inside it, so Shift+Tab could land on a control the header covers.

CSS couldn't fix this here:

- Chromium ignored `scroll-margin-top` on the row controls. The computed value was applied,
  but `focus()` didn't scroll.
- `scroll-padding-top` on the region was honored, but it also applied to the held search
  box itself. Focusing the search scrolled the list 516 pixels.

Instead, an `onFocus` handler on the list moves a covered control just below the header.
It acts only on `:focus-visible` focus. A mouse click lands on the part of the row the
reader can see, and moving the row out from under the pointer between press and release
would swallow the click.

**Workflow alert notice moved to the bell.** The bell never scrolls, so the notice now hangs
from it:

- Expanded rail: the notice drops 8 pixels below the bell, as the bell's own panel does.
  It's shifted so its notch points at the bell's centre, and it hangs past the rail's edge,
  so most of **New chat** stays clickable.
- Collapsed rail or phone: it flies out from the strip's edge, level with the bell.

The notice follows the bell in the tab order. Its timers, claims, tuck, card and live
region are unchanged.

### Testing approach

- Source-level assertions guard the structure, observer roots, the focus handler and the
  alert anchor. These match the convention for V2 rail changes.
- Real-component browser tests run the production `AppShell`, `Sidebar`, `ConversationRail`,
  `ChatPage` and stores with production CSS, through the orchestration harness. Only HTTP is
  stubbed.
- The workflow alert suite runs the real rail, bell, notice, card and both notification
  runtimes.

### Impact

- Chat page, expanded rail on desktop and in the phone drawer: the list gets nearly the
  whole rail once you scroll.
- Collapsed rail and other pages: no layout change.
- Workflow alert notices appear beside the bell rather than under **My Workspace**. With
  the rail expanded, the notice now overlaps the top of the page next to the rail while it
  shows. As before, moving focus onto anything it covers tucks it into the bell.

## Validation

### Test results

| Command | Result |
|---|---|
| `python functional_tests/test_v2_sidebar_conversation_scroll.py` | 7/7 passed |
| `python -m pytest ui_tests/test_v2_sidebar_conversation_scroll.py` | 9 passed |
| `python -m pytest ui_tests/test_v2_workflow_alert_notices.py` | 30 passed |
| `npm --prefix application/v2_ui run typecheck` | Passed |

The rail browser test measures the panel at 1280×720 with 75 conversations and two external
links:

- At rest, the panel is laid out exactly as before.
- After scrolling, New chat and the footer haven't moved, the navigation is out of view and
  the search is held right under New chat.
- At least ten rows are visible, against two before.
- There is one scrollbar.
- Page 2 is requested while the end of the list is still 60 pixels below the region's edge.
- Shift+Tab never lands under the held search, with or without the bulk bar.
- A mouse click on a row the header partly covers still opens that row.
- Typing a search while the header is held leaves the search box in place.
- The collapsed rail and the home page have no scroller.
- The phone drawer holds the search under New chat.
- The held backing matches `--surface-solid` in both themes.

### Before and after

| Situation (1280×720, two external links) | Before | After |
|---|---|---|
| Conversation rows visible at rest | 2 | 2, laid out exactly as before |
| Conversation rows visible after scrolling the list | 2, in an 86-pixel scroller | 12, in a 507-pixel region |
| Search box after scrolling the list | Stays mid-rail | Held right under **New chat** |
| Navigation and External Links after scrolling | Fixed in place | Scrolled out of view, back on scrolling up |
| Next page of conversations | Requested once the end is on screen | Requested 120 pixels before the end |
| Workflow alert notice with the rail scrolled | Would scroll away with **My Workspace** | Hangs from the bell, always on screen |
| Collapsed rail, other pages | Unchanged | Unchanged |

## Related

- Classic counterpart: [Whole Sidebar Scroll Fix](WHOLE_SIDEBAR_SCROLL_FIX.md)
- Feature documentation: [React V2 UI](../features/REACT_V2_UI.md),
  [V2 Workflow Alert Notices](../features/V2_WORKFLOW_ALERT_NOTICES.md)
- Tests: `functional_tests/test_v2_sidebar_conversation_scroll.py`,
  `ui_tests/test_v2_sidebar_conversation_scroll.py`,
  `ui_tests/test_v2_workflow_alert_notices.py`
