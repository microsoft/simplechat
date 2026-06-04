# Chat Model And Agent Dropdown Alignment Fix

Fixed/Implemented in version: **0.241.126**

## Issue Description

The chat model and agent searchable dropdown menus could open at the far left edge of the browser instead of staying aligned with the compact selector in the chat composer toolbar. This made the menu appear detached from the selected model or agent control.

## Root Cause Analysis

The model and agent selectors use fixed Popper positioning so their menus can escape toolbar clipping. The shared searchable-select CSS set `min-width: 100%`, which is safe for normal absolute dropdowns but resolves against the viewport for fixed-positioned menus before Popper calculates placement. Popper measured the menu as viewport-wide, then clamped it to the left padding to prevent overflow.

## Technical Details

Files modified:
- `application/single_app/static/css/chats.css`
- `application/single_app/config.py`
- `ui_tests/test_chat_model_dropdown_width.py`

Code changes summary:
- Added a specific CSS min-width override for the fixed-position model and agent searchable menus so Popper measures a compact menu before applying placement.
- Expanded the existing chat model dropdown UI regression test to assert horizontal anchoring, not just compact width.
- Added agent dropdown coverage that verifies the menu remains compact and overlaps its trigger button.
- Updated `config.py` to version `0.241.126` for traceability.

Testing approach:
- Updated Playwright UI coverage in `ui_tests/test_chat_model_dropdown_width.py` to validate model and agent dropdown width, viewport fit, and horizontal anchoring.

## Validation

Expected behavior after the fix:
- The model dropdown opens aligned with the model selector.
- The agent dropdown opens aligned with the agent selector.
- Both menus stay compact and do not span or align to the browser's left edge.
- The shared prompt dropdown behavior remains unchanged.