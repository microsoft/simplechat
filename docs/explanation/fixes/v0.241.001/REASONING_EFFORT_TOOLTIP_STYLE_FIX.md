# Reasoning Effort Tooltip Style Fix

## Fix Title
Reasoning effort hover text now uses the same Bootstrap tooltip styling as other chat buttons and controls.

## Issue Description
The reasoning effort UI showed browser-native hover tooltips in places where the rest of the chat experience used Bootstrap tooltips. This created a visible style mismatch on the reasoning button state and on the per-level descriptions inside the reasoning modal.

## Root Cause Analysis
- `chat-reasoning.js` updated the reasoning button by assigning a raw `title` attribute after Bootstrap tooltip initialization.
- The reasoning modal created each effort level with `levelDiv.title`, which bypassed the shared tooltip component entirely.
- Native browser tooltips do not match the visual treatment, timing, or positioning behavior of the Bootstrap tooltips used elsewhere in chat.

## Version Implemented
Fixed in version: **0.239.192**

## Files Modified
| File | Change |
|------|--------|
| `application/single_app/static/js/chat/chat-reasoning.js` | Added a shared tooltip helper and routed reasoning button and modal level hover text through Bootstrap tooltip instances |
| `application/single_app/templates/chats.html` | Switched the reasoning button to `data-bs-title` Bootstrap tooltip markup |
| `functional_tests/test_reasoning_effort_tooltip_consistency.py` | Added regression coverage for Bootstrap tooltip usage and version bump |
| `application/single_app/config.py` | Version bump to 0.239.192 |

## Code Changes Summary
- Added a small helper to update tooltip text without reintroducing native `title` hovers.
- Updated the reasoning toolbar button to keep its hover text in the Bootstrap tooltip path when the selected effort changes.
- Updated the reasoning modal level cards to use Bootstrap tooltips for their descriptions.

## Testing Approach
- Added `functional_tests/test_reasoning_effort_tooltip_consistency.py`.

## Impact Analysis
- Reasoning hover text now matches the styling and behavior of the other chat button tooltips.
- Users get consistent tooltip rendering for both the toolbar control and the modal effort descriptions.
- The change is limited to tooltip wiring and does not alter reasoning effort values or backend behavior.

## Validation
- Regression test: `functional_tests/test_reasoning_effort_tooltip_consistency.py`
- Before: reasoning hover text could appear with browser-native tooltip styling.
- After: reasoning hover text is rendered through Bootstrap tooltips like the rest of the chat controls.