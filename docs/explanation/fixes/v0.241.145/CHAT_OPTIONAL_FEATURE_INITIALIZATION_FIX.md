# Chat Optional Feature Initialization Fix

Fixed in version: **0.241.145**

## Issue Description

Opening Chats could log noisy browser-console messages when optional chat features were disabled or unavailable in the rendered page. In particular, agent initialization emitted `Agent Init Error: enable-agents-btn not found.` when Semantic Kernel was enabled but per-user agents were not rendered.

## Root Cause

Chat modules are imported by other chat modules, so their initialization paths can run even when the matching optional controls are intentionally absent from `chats.html`. The agent initializer treated missing controls as an error, and the speech initializer was called by the shared chat on-load module even when speech input was disabled.

## Technical Details

Files modified:

- `application/single_app/static/js/chat/chat-agents.js`
- `application/single_app/static/js/chat/chat-speech-input.js`
- `application/single_app/config.py`
- `functional_tests/test_chat_optional_feature_initializers.py`
- `ui_tests/test_chat_optional_feature_initializers_quiet.py`

Code changes summary:

- Added an agent-controls availability guard so agent initialization and dropdown population return quietly when the agent enable button or selector controls are not present.
- Added a speech-input feature flag guard so speech initialization returns quietly when `window.appSettings.enable_speech_to_text_input` is false.
- Removed disabled-feature console error and warning paths for optional missing controls.

Config version update:

- Updated `application/single_app/config.py` from `0.241.144` to `0.241.145`.

Testing approach:

- Added a functional regression test that validates the quiet optional-initializer guards remain in place.
- Added a Playwright UI regression test that opens Chats and fails if the agent init error or speech missing-control warning appears in the browser console.

## Validation

Before:

- Chats could log `Agent Init Error: enable-agents-btn not found.` when agents were not rendered for the current configuration.
- Chats could log `Speech input button not found in DOM` when speech input was disabled but the shared chat on-load module still called the initializer.

After:

- Disabled or unavailable optional chat features no-op quietly.
- Agent and speech initializers still attach normal controls when their matching DOM is present.
