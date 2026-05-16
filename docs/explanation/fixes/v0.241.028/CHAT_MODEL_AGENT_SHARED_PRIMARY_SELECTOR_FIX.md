# Chat Model Agent Shared Primary Selector Fix

Fixed/Implemented in version: **0.241.028**

## Issue Description

The chat toolbar still had one selector-placement inconsistency.

When agents were enabled, the model selector occupied the primary selector space while the agent selector appeared below prompts in the secondary selector area. That created an unnecessary layout jump and made the toolbar feel inconsistent across both desktop and mobile.

## Root Cause Analysis

`application/single_app/templates/chats.html` rendered the model selector inside the primary selector slot, but rendered the agent selector inside the secondary selector surface with prompts.

`application/single_app/static/js/chat/chat-mobile-toolbar.js` then moved the model selector and the secondary selector surface independently between desktop and mobile, which preserved that mismatch instead of normalizing it.

## Technical Details

Files modified: `application/single_app/config.py`, `application/single_app/templates/chats.html`, `application/single_app/static/js/chat/chat-mobile-toolbar.js`, `application/single_app/static/css/chats.css`, `functional_tests/test_chat_searchable_selectors.py`, `ui_tests/test_chat_mobile_toolbar_compaction.py`

Code changes summary:

- Added a shared primary selector surface in `chats.html` that now contains both the model selector and the agent selector.
- Left prompts in the secondary selector surface so they remain a separate optional filter rather than competing with model or agent selection.
- Updated `chat-mobile-toolbar.js` to move the shared primary selector surface between desktop and mobile instead of moving only the model selector.
- Added CSS for the shared primary surface so both selectors use the same slot sizing rules.
- Updated the source and UI regressions to validate the shared primary selector contract.

Impact analysis:

- Enabling agents now swaps the primary selector space from model to agent instead of adding a second selector below prompts.
- Desktop and mobile now use the same selector hierarchy: primary slot for model or agent, secondary slot for prompts.

## Validation

Test coverage: `functional_tests/test_chat_searchable_selectors.py`, `ui_tests/test_chat_mobile_toolbar_compaction.py`

Test results:

- `functional_tests/test_chat_searchable_selectors.py`: passed `9/9` checks after updating the shared primary selector contract.
- `ui_tests/test_chat_mobile_toolbar_compaction.py`: updated to version `0.241.028` and continues to validate mobile drawer ownership.
- `ui_tests/test_chat_mobile_toolbar_compaction.py`: skipped in the current environment because `SIMPLECHAT_UI_BASE_URL` and authenticated UI state are not configured.

Before/after comparison:

- Before: Model selection used the primary slot while agent selection appeared below prompts in the secondary area.
- After: Model and agent selection share the same primary slot, with prompts remaining below as a secondary selector.

Related config.py version update: `VERSION = "0.241.028"`