# V2 Conversation Menu Layout Fix (0.261.406)

## Issue

The React V2 conversation menu put reference and handoff actions ahead of common
management actions. A bold, nonfunctional reference heading, indented child
actions, and mixed text sizes made the menu unnecessarily wordy and inconsistent.
Menus opened near the bottom of the conversation list could be clipped behind the
sidebar footer.

Fixed in version: **0.261.406**, recorded in
`application/single_app/config.py`.

## Root cause

`ConversationRail.tsx` rendered the panel with absolute positioning below each row,
inside the sidebar's scrolling region. That region clipped the panel, and the
glass sidebar also established a containing block. Raising z-index or using fixed
positioning inside that ancestor would not reliably free the menu.

The reference block was rendered before Rename and used a separate heading,
smaller child text, indentation, and an inconsistent copy icon size.

## Technical details

### Files modified

| File | Change |
| --- | --- |
| `application/v2_ui/src/components/chat/ConversationRail.tsx` | Flat action order, concise labels, uniform rows, destructive-action separation, accessible triggers, and guards against portalled focus or shortcuts changing the sidebar behind the menu. |
| `application/v2_ui/src/components/ui/ActionPopover.tsx` | Opt-in automatic placement for the conversation rail, reusing the existing body portal and dismissal/keyboard handling while preserving default header behavior. |
| `application/v2_ui/src/components/ui/dropdownPlacement.ts` | Optional measured menu dimensions, with existing composer dimensions unchanged by default. |
| `application/v2_ui/src/styles/theme.css` | Touch-sized menu controls outside the navigation DOM subtree and fixed-size icon alignment. |
| `application/single_app/config.py` | Application patch version updated to 0.261.406. |
| `functional_tests/test_v2_sidebar_conversation_scroll.py` | Portal/focus contracts and current desktop/mobile scroll-region expectations. |
| `functional_tests/test_v2_composer_picker_placement.py` | Measured-height placement cases and viewport-boundary checks alongside unchanged composer defaults. |
| `ui_tests/test_v2_sidebar_conversation_scroll.py` | Real-component menu order, geometry, hit-testing, keyboard, clipboard, and responsive regressions using production CSS. |
| `ui_tests/test_v2_conversation_references.py` | Updated flat-menu labels and private-source exclusion checks. |
| `ui_tests/test_v2_conversation_handoffs.py` | Updated menu label while retaining the existing handoff dialog and workflow. |
| `docs/guides/reference-and-send-conversations.md` | Updated reference actions, menu placement guidance, and clipboard troubleshooting. |
| `docs/reference/chat-controls.md` | Documented the flat reuse actions and conditional availability. |

### Menu and behavior

The menu order is Rename, Share, Pin, Hide, Export, then Send to conversation,
Use in this chat, and Copy reference. Delete has a divider and extra space above
it. Conditional People, Unpin, and Leave labels continue to reflect the existing
conversation state and permissions.

All action rows share normal-weight text, a consistent icon column, and the same
padding. The redundant reference heading is removed. Copying still uses the
existing portable reference format; an unavailable or denied clipboard now gives
visible error feedback rather than failing silently.

### Floating placement and focus

The panel renders through the shared popover's portal into `document.body`, beyond
the sidebar's clipping and glass containing block. The conversation menu opts
into placement based on its actual rendered height, trigger position, and visual
viewport. It opens below when there is room and above when the lower edge would
otherwise be clipped. Width and height remain bounded by the visible viewport.
An exceptionally small window may scroll the panel itself, not the conversation
list.

Resize and scroll updates keep the placement current; a trigger that leaves its
visible boundary dismisses the menu. Outside interaction and Escape also dismiss
it, and Escape restores trigger focus. Existing shared-popover keyboard navigation
is retained. Portalled focus does not invoke sidebar row scrolling, and shortcuts
inside the floating panel do not change the selection behind it.

Mobile controls retain their touch targets even though the panel no longer lives
under `#primary-navigation`. Existing header popovers retain their default
positioning and sizing. No new browser library or external runtime asset is used.

### Impact

Only the React V2 conversation-row menu changes. Source eligibility, Share/People,
Pin/Unpin, Delete/Leave permissions, confirmation dialogs, the reference format,
composer attachment, export, and handoff review remain unchanged. The classic
interface and bulk-action toolbar are not redesigned.

## Validation

The focused browser regressions use production AppShell, Sidebar,
ConversationRail, stores, and CSS with stubbed HTTP. They check actual element
bounds and hit targets rather than treating a larger z-index as proof of
visibility. Desktop and phone layouts run in both themes; enlarged text and short
windows verify that the menu remains reachable without scrolling the sidebar.

### Test results

| Command | Result |
| --- | --- |
| `npm --prefix .\application\v2_ui run typecheck` | Passed. |
| `npm --prefix .\application\v2_ui run build -- --outDir ..\..\ui_tests\artifacts\orchestration-plan-editor` | Passed, with Vite's large-chunk size advisory. |
| `python -m pytest .\functional_tests\test_v2_sidebar_conversation_scroll.py .\functional_tests\test_v2_composer_picker_placement.py .\functional_tests\test_v2_mobile_layout.py .\functional_tests\test_v2_conversation_multiselect.py .\functional_tests\test_v2_conversation_export.py -q --disable-warnings` | 47 passed. |
| `python -O .\functional_tests\test_v2_composer_picker_placement.py` | Passed; the Node checks also execute under optimized Python. |
| `python -m pytest .\ui_tests\test_v2_sidebar_conversation_scroll.py .\ui_tests\test_v2_conversation_references.py .\ui_tests\test_v2_conversation_handoffs.py -q --disable-warnings` | 24 passed. |
| `python -m pytest .\ui_tests\test_v2_mobile_headers.py -k "loading_status or (explicit_actions and (320 or 393))" -q --disable-warnings` | 9 passed; existing shared header popovers retain their behavior. |
| `python .\functional_tests\test_docs_app_surface_coverage.py` | 7 checks passed. |
| `python .\functional_tests\test_docs_site_quality.py` | 6 checks passed. |

The app-surface inventory was regenerated without a content change. The design
detector returned no findings for the four changed UI targets.

The browser suite writes desktop and phone menu screenshots in both themes under
`ui_tests/artifacts/sidebar-conversation-scroll/`. It verifies that the complete
menu fits near the bottom at ordinary desktop and phone sizes, each action is
hit-testable, and keyboard navigation leaves the sidebar's scroll position
unchanged. Short-window and enlarged-text cases confirm that Delete remains
reachable by scrolling only the bounded menu.

## Before and after

| Before | After |
| --- | --- |
| Reference heading and indented actions precede Rename. | Management actions come first; concise reuse actions follow Export. |
| Text weights, sizes, and icon alignment vary. | Every action has the same normal-weight text and alignment. |
| Delete immediately follows Export. | Delete/Leave has clear destructive-action separation. |
| Low menus can disappear behind the footer. | Portalled menus flip above the trigger and stay viewport-bounded. |
| Keyboard focus in an overlay can be mistaken for sidebar-row focus. | Sidebar scrolling and selection shortcuts ignore portalled controls. |

## Related documentation

- [Reference and send between conversations](../../guides/reference-and-send-conversations.md)
- [Chat interface controls](../../reference/chat-controls.md)
- [V2 sidebar conversation scrolling](V2_SIDEBAR_CONVERSATION_SCROLL_FIX.md)
