# Reasoning Effort Initial Sync Fix

## Fix Title
Reasoning effort button now reflects the saved level for the selected model on the first chat-page load.

## Issue Description
The reasoning effort button could show the wrong initial icon and tooltip when a user first opened the chat page. If the user opened the reasoning modal and changed the level, the button updated immediately and stayed correct for the rest of that session.

## Root Cause Analysis
- `chat-onload.js` applied the preferred model only after a broader startup `Promise.all()` that also waited on document and prompt loading.
- `chat-reasoning.js` fetched user settings independently and initialized the reasoning button as soon as its own request resolved.
- When the reasoning settings request finished before the preferred model was applied, the button synced itself against the default model instead of the user's actual selected model.
- Because the preferred model was assigned programmatically without a later reasoning-state refresh, the stale icon and tooltip remained until the user changed the reasoning level manually.

## Version Implemented
Fixed in version: **0.239.125**

## Files Modified
| File | Change |
|------|--------|
| `application/single_app/static/js/chat/chat-onload.js` | Applied user settings earlier in startup and initialized reasoning after the preferred model is set |
| `application/single_app/static/js/chat/chat-reasoning.js` | Added deterministic reasoning-state sync using already-loaded settings |
| `functional_tests/test_reasoning_effort_initial_sync.py` | Added regression coverage for the startup ordering and reasoning sync path |
| `functional_tests/test_chat_searchable_selectors.py` | Updated version metadata/assertion for the new release |
| `functional_tests/test_workspace_scope_prompts_fix.py` | Updated version metadata/assertion for the new release |
| `application/single_app/config.py` | Version bump to 0.239.125 |

## Code Changes Summary
- Added a shared reasoning-state sync path so the reasoning button can be refreshed explicitly for the current model.
- Updated reasoning initialization to accept already-loaded user settings instead of always starting a second settings fetch race.
- Changed chat startup so the preferred model is applied before the reasoning toggle is initialized.

## Testing Approach
- Added `functional_tests/test_reasoning_effort_initial_sync.py`.
- Updated existing versioned functional tests so their release assertions match the new config version.

## Impact Analysis
- The reasoning button now shows the saved effort level and tooltip immediately for the active model on initial page load.
- Startup remains responsive because user settings are still loaded in parallel with document and prompt data.
- Real-time reasoning updates after a manual change continue to work through the existing model-change and save flow.

## Validation
- Regression test: `functional_tests/test_reasoning_effort_initial_sync.py`
- Before: the first visible reasoning icon could reflect the wrong model context until the user manually changed reasoning.
- After: reasoning state is synchronized after the preferred model is applied, so the initial button state matches the saved setting.