# Source Review Load More and Chat Follow-Up Actions

Implemented in version: **0.241.046**

## Overview

This feature improves source-backed web research and conversational follow-through in Chats.

Source Review can now use the optional rendered-page path to click visible Load More controls on official source archive pages. This helps pages that initially expose only a few cards, such as press-release archives that reveal additional dated releases after interaction.

Assistant responses can also surface visible next-step suggestions as prompt buttons. Selecting a suggestion stages it in the chat input and starts a cancelable send countdown, giving users a quick path to continue without treating the suggestion as an already-executed action.

## Dependencies

* Source Review Load More support depends on admins enabling JavaScript rendering and the app host having Playwright browser support installed.
* Follow-up prompt actions use the existing Chat frontend JavaScript and send-button behavior.

## Technical Specifications

### Architecture

* `application/single_app/functions_source_review.py` detects Load More controls during static extraction and uses the existing optional Playwright renderer to click matching controls.
* `application/single_app/static/js/chat/chat-messages.js` extracts visible follow-up suggestions from assistant markdown and renders prompt action buttons after the assistant message text.
* `application/single_app/static/css/chats.css` styles the action buttons and countdown progress.
* `application/single_app/templates/admin_settings.html` exposes the rendered Load More click cap near the Source Review JavaScript rendering setting.

### Load More Behavior

When JavaScript rendering is enabled, Source Review can click visible controls matching labels such as Load More, Show More, View More, or More News/Results/Articles/Releases. The renderer stops when:

* The configured click cap is reached.
* No visible matching control is found.
* A click does not add new text or links.
* The requested date range appears to be visible for requests like past three years.

The default cap is 6 clicks, and the hard maximum is 12 clicks. Existing URL policy, redirect validation, timeout, content type, page budget, and SSRF protections still apply.

### Follow-Up Actions

Follow-up prompt buttons are created only from visible assistant text near phrases such as if you want, next step, which format do you want, or would you like me to. Buttons use textContent and event listeners rather than HTML injection. Clicking a button fills the input with a normalized prompt and starts a 5-second countdown on the Send button; clicking Send during the countdown cancels auto-send and leaves the prompt staged.

## Usage Instructions

Admins can enable Source Review JavaScript rendering and set Rendered Load More Clicks in Admin Settings > Search & Extract. Users do not need a separate control for Load More; it runs only when Source Review is enabled and a reviewed source page exposes a matching control.

In Chats, users can click follow-up action buttons under assistant responses when the assistant presents concrete next-step options. The staged prompt can be edited, canceled by clicking Send during countdown, or sent automatically when the countdown completes.

## Testing and Validation

Coverage includes:

* `functional_tests/test_source_review_security.py` for Load More detection and click-cap clamping.
* `functional_tests/test_chat_follow_up_prompt_actions.py` for follow-up prompt action wiring and safe text handling.
* `ui_tests/test_admin_source_review_settings.py` for the rendered Load More admin control.
* `ui_tests/test_chat_follow_up_prompt_actions.py` for the chat follow-up action surface when a UI environment is configured.

## Known Limitations

Load More support is intentionally bounded and does not turn Source Review into a full crawler. Pages that require authentication, custom gestures, captchas, or opaque client APIs may still be incomplete. Follow-up prompt buttons are convenience actions for visible suggestions; they do not execute hidden tools or guarantee the assistant can complete the next request without additional context.
