# Chat Tutorial Selector Coverage Fix

Fixed/Implemented in version: **0.239.180**

## Issue Description

The chat tutorial on the merged chat page had drifted behind the current toolbar, sidebar search flow, and workspace UI. It still referenced removed controls such as the streaming and classification buttons, targeted hidden compatibility selects instead of the visible searchable dropdown buttons used by the live interface, skipped important sidebar actions like advanced search, bulk selection, and export, could not walk the sidebar reliably when the user had it collapsed, eagerly opened modal dialogs during tutorial startup instead of only when their step was shown, still used the older conversation-list selector instead of the sidebar conversation list used by the live navigation, resolved conversation menu steps against generic selectors instead of the same concrete conversation item whose dropdown it had just opened, inherited the sidebar dropdown clipping bug caused by static dropdown positioning inside the scrollable sidebar, could measure newly opened popups before Popper finished placing them, still allowed popup-based steps to render underneath the tutorial overlay, was still trying to scroll fixed-position popups into view instead of scrolling their anchor controls, could open popup steps during the same click event that advanced the tutorial so Bootstrap immediately closed them again, continued to fight the live dropdown lifecycle for menu-explanation steps, failed to instantiate the tutorial-owned menu during the popup refresh path, still treated tutorial-owned menu steps like deferred popups, could let stale async popup refreshes or stale target state misalign the outline after the cloned tutorial menu appeared, still rendered the select/export outline behind the cloned menu instead of directly on the menu item itself, was still looking for the main-pane bulk action buttons during the sidebar tutorial instead of the sidebar selection controls that actually appear in nav mode, could still fail if the sidebar entered selection mode without a selected main-list checkbox to light up the bulk buttons, could still auto-revert out of selection mode a few seconds later because the app's normal inactivity timer kept running during the tutorial, still exposed the tutorial launch affordance before the conversation UI was ready while keeping the button copy too cryptic once it did appear, left the advanced-search tutorial modal stack underneath the tutorial overlay/backdrop, let the tutorial launcher tooltip sit under the button and linger after a click, and still kept the tooltip too close to the expanding launcher so the tooltip text could overlap the button itself while hovering even after the first offset adjustment.

## Root Cause Analysis

The tutorial step definitions in `chat-tutorial.js` were not updated when the chat page moved from hidden native selects to visible searchable dropdown buttons and when newer toolbar controls were added. That left several tutorial steps filtered out at runtime or pointing at stale selectors.

## Technical Details

### Files Modified

- `application/single_app/static/js/chat/chat-tutorial.js`
- `application/single_app/static/js/chat/chat-sidebar-conversations.js`
- `application/single_app/config.py`
- `functional_tests/test_chat_tutorial_selector_coverage.py`
- `functional_tests/test_sidebar_conversation_dropdown_positioning.py`

### Code Changes Summary

- Replaced stale or hidden tutorial targets with the visible chat controls now used by the merged chat UI.
- Removed dead tutorial references for streaming and classification controls that are no longer present on the chat page.
- Added tutorial coverage for conversation action menus, quick search, advanced search, selection-mode bulk actions, single-conversation export, image generation, workspace scope, tag filters, scope lock, voice input, and the send button.
- Added sidebar state handling so nav-phase tutorial steps expand the collapsed sidebar before highlighting controls and restore the original sidebar state when the walkthrough exits.
- Separated step discovery from step preparation so hidden menus, modals, and the export wizard are only opened for the active tutorial step and are closed again on the next step.
- Updated the conversation-list step to target the sidebar conversation list used by the current chat layout while keeping compatibility with the older main-template list id.
- Bound the conversation-action steps to one consistent sidebar conversation item so the opened dropdown menu, menu entries, selection-mode step, and export step all target the same live conversation row.
- Replaced the sidebar conversation dropdown's static positioning with fixed Popper positioning so the menu can render above the scrollable sidebar in both normal use and tutorial mode.
- Delayed tutorial popup targeting by two animation frames for popup-based steps so the highlight uses the popup's real on-screen position after Popper finishes placement.
- Raised tutorial-managed popups above the tutorial mask and retried popup target refresh until placement settled so popup steps no longer default to the page origin or disappear beneath the overlay.
- Stopped popup-based steps from calling `scrollIntoView` on fixed-position popups and instead scroll the anchor conversation row or skip scrolling entirely for modal steps.
- Deferred popup-step activation until after the tutorial `Next` click completes so Bootstrap no longer auto-closes tutorial-opened dropdowns on the same event turn.
- Replaced the menu-explanation tutorial steps with a tutorial-owned cloned conversation menu popup so those steps no longer depend on the live Bootstrap dropdown staying open under the overlay.
- Ensured popup-step refresh re-runs step preparation so the tutorial-owned menu is actually created before target measurement and card placement.
- Split tutorial-owned menu steps from truly deferred popup steps so the cloned menu steps stay synchronous and do not inherit stale async popup refresh behavior from modal-style steps.
- Tokenized async popup target refresh work so stale refresh callbacks from previous steps can no longer overwrite the current highlight target.
- Synced the active tutorial target immediately after the cloned conversation menu target changes and sized the outline against the viewport instead of the nav container so menu and bulk-action steps can lock onto the visible popup correctly.
- Added a popup-item highlight mode for cloned conversation menu entries so the select and export tutorial steps draw their emphasis directly on the visible dropdown item instead of behind the menu overlay.
- Retargeted the bulk-actions tutorial step to the sidebar selection buttons first, with the main chat-pane bulk buttons kept only as a fallback for alternate layouts.
- Forced the sidebar selection controls visible during the tutorial bulk-actions step so the walkthrough does not depend on the main conversation list checkbox state to expose those buttons.
- Added a tutorial keepalive for the bulk-actions step so the sidebar stays in selection mode until the user advances the tutorial instead of falling back to the normal 5-second inactivity timeout.
- Hid the tutorial launcher until sidebar conversations finish loading, delayed the auto-start path until the same readiness signal arrives, and expanded the launcher on hover to show a clearer `Chat Tutorial` label with improved tooltip copy.
- Promoted tutorial-opened modals and their Bootstrap backdrops above the tutorial layer so advanced search and export steps stay visible, and changed the launcher tooltip to hover-only with a dedicated z-index class that hides immediately when the button is clicked.
- Added a dedicated left-placement tooltip offset for the tutorial launcher so the hover text shifts farther left as the pill expands and no longer overlaps the button.
- Increased the launcher tooltip offset again so the hover copy clears the fully expanded tutorial pill on wider hover states instead of brushing the icon or label.
- Replaced the advanced-search explanation step with a tutorial-owned cloned dialog so that step no longer depends on the live Bootstrap modal/backdrop stack and can be highlighted deterministically like the conversation action walkthrough.
- Tightened the cloned advanced-search dialog to target its `.modal-content`, reuse the real `.modal-dialog` wrapper, and suppress horizontal overflow so the highlight matches the visible surface without transparent padding or a bottom scrollbar.
- Added explicit outer padding around the tutorial-owned advanced-search clone and narrowed the cloned dialog width so the walkthrough version keeps the same edge margins as the live modal.
- Added tutorial-side restoration for the sidebar header controls and conversation info button so the walkthrough can recover from selection-mode UI hiding before the `Show hidden conversations` and `Conversation details` steps resolve their targets.
- Expanded the conversation-action walkthrough to call out pinning and hiding directly from the per-conversation menu, and added a message-focused tutorial section after the send button that covers metadata, copy, masking, user-message editing, response retry/feedback/export/reuse tools, processing thoughts, and citations.
- Added tutorial-only sample user and AI messages for the walkthrough so message-action steps still work when the current conversation has no usable history yet.
- Refined the tutorial wording for drawer-based actions so the walkthrough explicitly tells users to press the `i`, thoughts, and sources buttons when those controls reveal more detail.
- Added a regression test that validates the tutorial selector set against the chat template and checks that removed selectors do not return.
- Added a regression test that rejects the old static dropdown configuration and verifies the fixed-position dropdown safeguards remain in place.

### Testing Approach

- Added functional regression tests that statically validate tutorial selectors and the sidebar dropdown positioning safeguards.
- Planned local browser validation on the merged chat page after patching.

## Validation

### Before

- Tutorial steps for prompt, model, and workspace controls could disappear because they pointed at hidden elements.
- The tutorial still referenced removed controls, missed newer merged chat-page actions, could fail when the sidebar started hidden, opened advanced search or export dialogs as soon as the tutorial launched, the sidebar conversation menu could be clipped behind the scrollable sidebar in normal use, popup-based steps could briefly highlight the top-left of the page before the popup was positioned, tutorial-managed popups could still sit under the tutorial mask, popup-based steps could destabilize their own placement by trying to scroll the popup itself, tutorial-opened dropdowns could be auto-closed by the same click used to advance to the next step, the conversation-menu explanation steps remained fragile because they depended on the live dropdown lifecycle, the new tutorial-owned menu path was not actually being created during deferred popup refresh, menu explanation steps could inherit stale async refresh behavior intended only for real modal popups, the outline could still stay locked to an older target or get clamped to the nav container after the cloned menu rendered, item-specific menu steps could still show the outline behind the popup rather than on the visible dropdown row, the bulk-actions step could fail immediately because it searched for the main conversation-pane buttons instead of the sidebar selection controls used in the nav walkthrough, selection mode could still expose no visible sidebar bulk buttons if the underlying main-list checkbox was not present for the selected conversation, the app's built-in selection timeout could still collapse the sidebar state during the tutorial after a few seconds of inactivity, the launcher could still invite users to start the tutorial before the conversation UI had actually finished loading, the advanced-search modal could still render under the tutorial layer even after it opened, the launcher tooltip could still render behind the button or remain visible until focus moved elsewhere, and the tooltip could still sit too close to the expanding launcher pill and overlap it during hover unless the offset fully cleared the widest expanded state.

### After

- The tutorial now follows the visible chat-page controls users actually interact with.
- The walkthrough covers the current toolbar more comprehensively, opens the sidebar automatically for nav steps when needed, opens popups only for the matching step, and benefits from the same fixed-position conversation menu used in normal sidebar operation.
- Regression coverage now guards both tutorial selector drift and the sidebar conversation dropdown positioning fix.
- Popup-based tutorial steps now refresh their target after the popup settles so the highlight tracks the actual menu or dialog instead of its temporary pre-placement location.
- Popup-based tutorial steps also lift the managed popup above the tutorial overlay so the menu or dialog remains visible while being highlighted.
- Popup-based tutorial steps now scroll the underlying anchor control instead of the popup itself, which avoids the collapse-to-origin behavior for fixed-position popups.
- Popup-based tutorial steps are now activated asynchronously after the tutorial navigation click finishes, which prevents Bootstrap dropdown auto-close from immediately hiding them.
- The conversation-menu explanation steps now use a tutorial-owned cloned menu popup, which makes those steps deterministic while leaving the later real bulk-action and export flows intact.
- Deferred popup refresh now explicitly runs step preparation first, so the tutorial-owned menu exists before target lookup and becomes visible for those explanation steps.
- Tutorial-owned menu steps now stay synchronous, while only true modal/export popups use deferred refresh, which keeps the next-step highlight locked to the cloned menu instead of drifting.
- Async popup refreshes are now scoped to the active step, the current target is updated as soon as the tutorial-owned menu is resolved, and the outline can use full viewport bounds, which keeps the first conversation-menu and bulk-selection tutorial highlights aligned to the visible cloned menu.
- The select and export explanation steps now apply a direct highlight class to the cloned dropdown item itself, so the emphasis is visibly on top of the menu row the tutorial is describing.
- The bulk-actions step now highlights the sidebar bulk action buttons that appear in selection mode during the nav walkthrough, so the tutorial can advance cleanly after the Select menu step.
- The tutorial now explicitly marks the sidebar conversation as selected and forces the sidebar bulk buttons visible for the bulk-actions step, so the walkthrough can continue even when the mirrored main-list checkbox is not available yet.
- The tutorial now re-applies the sidebar selection state on a short interval while the bulk-actions step is active, so the tutorial UI stays stable until the user clicks Next.
- The tutorial launcher now stays hidden until the sidebar conversation load completes, the first-run auto-start waits for the same readiness condition, and hovering the button expands it to show `Chat Tutorial` with clearer onboarding copy.
- Tutorial-opened advanced-search and export modals now lift both the modal and its backdrop above the tutorial layer, and the launcher tooltip now renders above the button and dismisses immediately on click so it does not stick around over the walkthrough.
- The launcher tooltip now uses a larger left offset, so the hover copy shifts left as the button expands and no longer covers the pill itself.
- The launcher tooltip now uses a substantially larger left offset, which pushes the hover copy clear of the fully expanded button instead of leaving it partially over the icon and label.
- The advanced-search tutorial step now uses a tutorial-owned cloned dialog, so the walkthrough highlights a stable popup surface instead of relying on the live modal stack to render above the tutorial layer.
- The cloned advanced-search dialog now highlights only the visible modal content and uses the real dialog wrapper sizing, which removes the see-through margins, fixes the card/outline placement, and eliminates the unnecessary horizontal scrollbar.
- The cloned advanced-search dialog now keeps visible breathing room around the white modal surface, which makes the tutorial version match the real advanced-search modal spacing more closely.
- The walkthrough now exits lingering sidebar selection-mode state before resolving the hidden-conversations header action and forces the conversation info button visible again when returning to the chat header, preventing the post-sidebar transition from terminating the tutorial with missing-target errors.
- The walkthrough now explains pin and hide where users actually encounter them in the conversation menu, and the post-send section teaches the message-level actions with the real control layout.
- When a chat has not started yet, the tutorial now injects temporary example user and AI messages so metadata, edit, retry, feedback, export, thought, and citation steps still have something concrete to highlight without changing saved chat data.