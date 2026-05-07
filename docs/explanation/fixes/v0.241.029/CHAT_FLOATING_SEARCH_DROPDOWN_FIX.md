# Chat Floating Search Dropdown Fix

Fixed/Implemented in version: **0.241.029**

## Issue Description

Two mobile dropdown behaviors in chat were still inconsistent.

`Scope` and `Tags` in the grounded-search panel could render clipped behind surrounding UI, while `Documents` opened correctly. Separately, the model and agent selectors inside the mobile tools drawer rendered as if they were trapped inside the drawer instead of floating above it.

## Root Cause Analysis

`application/single_app/static/js/chat/chat-documents.js` initialized `Documents` with a viewport-bound Bootstrap dropdown using fixed positioning, but `Scope` and `Tags` were still using the default dropdown behavior.

`application/single_app/static/js/chat/chat-searchable-select.js` also hard-coded the default Bootstrap dropdown configuration for searchable single-select controls, so model and agent selectors had no way to opt into the same fixed, viewport-safe positioning.

## Technical Details

Files modified: `application/single_app/config.py`, `application/single_app/static/js/chat/chat-documents.js`, `application/single_app/static/js/chat/chat-searchable-select.js`, `application/single_app/static/js/chat/chat-model-selector.js`, `application/single_app/static/js/chat/chat-agents.js`, `application/single_app/static/css/chats.css`, `functional_tests/test_chat_searchable_selectors.py`, `ui_tests/test_chat_mobile_toolbar_compaction.py`

Code changes summary:

- Added a shared viewport-safe dropdown initializer in `chat-documents.js` for `Scope`, `Tags`, and `Documents`.
- Standardized grounded-search dropdowns on `boundary: 'viewport'`, `reference: 'toggle'`, and `popperConfig.strategy: 'fixed'`.
- Added sizing and cleanup helpers so search dropdowns constrain themselves to the visible viewport on mobile.
- Extended `createSearchableSingleSelect()` to accept an optional dropdown configuration.
- Updated the model and agent selectors to use a floating dropdown configuration so their menus can render above the mobile tools drawer.
- Added z-index rules for the search filters and mobile selector menus to keep them above the surrounding drawer surfaces.
- Updated source-level and UI test headers/contracts to version `0.241.029`.

Impact analysis:

- `Scope` and `Tags` now use the same mobile-safe dropdown behavior as `Documents`.
- Model and agent menus are no longer limited to the visual bounds of the tools drawer when opened on mobile.
- The dropdown behavior is now controlled through shared configuration instead of separate one-off implementations.

## Validation

Test coverage: `functional_tests/test_chat_searchable_selectors.py`, `ui_tests/test_chat_mobile_toolbar_compaction.py`

Test results:

- `functional_tests/test_chat_searchable_selectors.py`: passed `9/9` checks after the dropdown behavior updates.
- `ui_tests/test_chat_mobile_toolbar_compaction.py`: updated to version `0.241.029`.
- `ui_tests/test_chat_mobile_toolbar_compaction.py`: still skips in the current environment because `SIMPLECHAT_UI_BASE_URL` and authenticated UI state are not configured.

Before/after comparison:

- Before: `Documents` floated safely, but `Scope` and `Tags` could clip inside the mobile search UI, and model or agent menus stayed visually confined to the tools drawer.
- After: all three grounded-search filters use the same viewport-safe dropdown path, and model or agent menus can float above the drawer surface.

Related config.py version update: `VERSION = "0.241.029"`