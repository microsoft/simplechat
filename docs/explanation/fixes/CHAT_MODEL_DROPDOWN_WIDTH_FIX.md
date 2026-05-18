# Chat Model Dropdown Width Fix

Fixed/Implemented in version: **0.241.036**

## Issue Description

The chat model selection dropdown could expand across the full browser window when opened. This made the searchable model picker feel disconnected from the compact toolbar selector and inconsistent with the prompt and document dropdowns.

## Root Cause Analysis

The model selector uses fixed Popper positioning so it can escape toolbar clipping. The shared searchable-select CSS used `min-width: 100%`, which is safe for normal absolute dropdowns but resolves against the viewport for fixed-positioned menus. That made the model dropdown's minimum width the full window width.

## Technical Details

Files modified:
- `application/single_app/static/js/chat/chat-searchable-select.js`
- `application/single_app/static/js/chat/chat-model-selector.js`
- `application/single_app/static/js/chat/chat-agents.js`
- `application/single_app/config.py`
- `ui_tests/test_chat_model_dropdown_width.py`

Code changes summary:
- Added a reusable floating searchable-select dropdown config that sets the menu minimum width from the toggle button's measured width in pixels.
- Reused that config for model and agent selectors so both fixed-position toolbar dropdowns stay compact.
- Updated `config.py` from version `0.241.035` to `0.241.036` for traceability.

Testing approach:
- Added a Playwright UI regression test that opens the chat model dropdown and verifies the menu remains bounded to the compact selector instead of spanning the viewport.

## Validation

Expected behavior after the fix:
- The model dropdown opens near the model selector and stays within a compact width.
- The model search input stays inside the dropdown menu.
- The shared prompt dropdown behavior remains unchanged.
- The agent dropdown uses the same bounded floating behavior as the model dropdown.