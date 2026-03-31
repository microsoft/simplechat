# Personal Workspace Tutorial Layer Order Fix

Fixed/Implemented in version: **0.239.192**

## Issue Description

The Personal Workspace tutorial card could render behind tutorial-owned action menus and example popup surfaces. That made the explanation text harder to read when a menu or modal step was active.

## Root Cause Analysis

Tutorial-owned popup surfaces were mounted directly on `document.body` with a higher stacking context than the tutorial layer. Even though the card inside the tutorial layer had a large `z-index`, it could not render above a sibling stacking context with a higher parent `z-index`.

## Technical Details

### Files Modified

- `application/single_app/static/js/workspace/workspace-tutorial.js`
- `application/single_app/config.py`
- `functional_tests/test_workspace_tutorial_layer_order_fix.py`

### Code Changes Summary

- Changed tutorial-owned popup surfaces to mount inside the tutorial layer when the layer is active.
- Inserted popup surfaces before the tutorial card so the popup stays above the dim highlight while the card stays above the popup.
- Added a regression test that verifies the layer insertion logic remains in place.

### Testing Approach

- Added a focused functional regression test for tutorial layer ordering.

## Validation

### Before

- Tutorial menus and example popups could visually sit above the tutorial card, leaving the explanatory card partially hidden behind them.

### After

- Tutorial-owned menus and example popups now render between the dim highlight and the tutorial card, so the active popup remains visible and the tutorial card stays on top.