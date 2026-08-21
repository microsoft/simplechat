# Agent Modal Icon Controls Fix

Fixed/Implemented in version: **0.250.011**

## Issue Description

The Add Agent modal showed the Bootstrap Icon/Image toggle, but the Image option did not reveal the file upload control and the Bootstrap icon search field did not populate or filter selectable icons when creating a new agent.

## Root Cause Analysis

The shared icon editor helper already supported icon search, icon selection, image mode, upload resizing, and payload generation. The new-agent modal controller saved icon payloads but did not initialize the shared helper when the stepper bound its events, so the static modal controls had no event handlers unless another path initialized them first.

## Technical Details

Files modified:
- `application/single_app/static/js/agent_modal_stepper.js`
- `application/single_app/config.py`
- `ui_tests/test_agent_modal_icon_controls.py`

Code changes summary:
- Initialize shared agent icon controls during agent modal stepper event binding.
- Reset the icon editor to the default `bi-robot` state when starting a new agent, including clearing stale image data from previous modal use.
- Added Playwright UI coverage for new-agent icon search, icon selection, Image mode visibility, and reset behavior.
- Updated `application/single_app/config.py` from `0.250.010` to `0.250.011`.

## Validation

Testing approach:
- Added `ui_tests/test_agent_modal_icon_controls.py` to guard the browser workflow.
- Verified editor diagnostics are clean for the changed JavaScript, Python config, and UI test files.
- Verified the new UI test file compiles with `python -m py_compile ui_tests/test_agent_modal_icon_controls.py`.

Local test result:
- `python -m pytest ui_tests/test_agent_modal_icon_controls.py -q -rs` skipped because Playwright is not installed in the local environment.

Expected behavior after the fix:
- Selecting `Image` in the Add Agent modal reveals the PNG/JPEG upload control.
- Typing in the Bootstrap icon search filters available local Bootstrap Icons.
- Choosing an icon updates the visible picker label, preview, and saved icon payload.