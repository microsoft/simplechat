# Chat Prompt Desktop Toolbar Position Fix

Fixed/Implemented in version: **0.241.025**

## Issue Description

The prompt selector dropdown appeared in the chat toolbar controls row on larger desktop canvases.

That placed prompts after the model or agent selector and separated them from the modifier buttons, even though the intended large-canvas order is prompt selector, model or agent selector, then modifier controls.

## Root Cause Analysis

The desktop prompt slot was anchored in `chat-toolbar-controls`, the same row that now exists primarily for the mobile tools toggle.

The mobile toolbar work correctly introduced movable desktop and mobile selector surfaces, but the desktop anchor for prompts still lived outside the main desktop tools surface. That made the desktop order depend on the controls row instead of the larger toolbar canvas.

## Technical Details

Files modified: `application/single_app/config.py`, `application/single_app/templates/chats.html`, `application/single_app/static/css/chats.css`, `functional_tests/test_chat_prompt_desktop_toolbar_position.py`, `ui_tests/test_chat_prompt_desktop_toolbar_position.py`

Code changes summary:

- Moved the desktop prompt selector slot into the main desktop tools surface before the model or agent selector.
- Kept the model or agent selector in the same desktop tools surface directly before the modifier buttons.
- Made `.chat-toolbar-controls` desktop-hidden so it remains reserved for the mobile tools toggle instead of hosting desktop selectors.
- Preserved the mobile selector slots so prompt, model, and agent selectors still move into the mobile tools drawer.
- Added functional and Playwright UI coverage for the desktop selector order.

Impact analysis:

- Desktop prompt selection now appears to the left of the model or agent selector and modifier buttons.
- The mobile drawer behavior from the previous toolbar work remains intact.
- The toolbar DOM now matches the intended desktop and mobile ownership split more clearly.

## Validation

Test coverage: `functional_tests/test_chat_prompt_desktop_toolbar_position.py`, `ui_tests/test_chat_prompt_desktop_toolbar_position.py`

Test results:

- `functional_tests/test_chat_prompt_desktop_toolbar_position.py`: passed standalone and under pytest.
- `ui_tests/test_chat_prompt_desktop_toolbar_position.py`: added to validate rendered desktop order; skipped in the current environment because authenticated UI test settings are not configured.

Before/after comparison:

- Before: The prompt selector could render in `.chat-toolbar-controls` after the model or agent selector on larger desktop canvases.
- After: The prompt selector renders in the desktop tools surface before the model or agent selector and before modifier controls, while mobile still uses the drawer slots.

Related config.py version update: `VERSION = "0.241.025"`