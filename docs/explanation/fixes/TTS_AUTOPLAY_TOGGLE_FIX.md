# TTS Autoplay Toggle Fix - Version 0.242.048

Fixed/Implemented in version: **0.242.048**

## Issue Description

Turning on the chat toolbar AI voice response toggle did not automatically read new assistant messages aloud for users whose saved `ttsEnabled` preference was missing or false. The manual `Read this to me` button still worked because it invoked playback directly.

## Root Cause Analysis

The automatic playback path required both `ttsAutoplay` and `ttsEnabled` to be true. The chat toolbar toggle only persisted `ttsAutoplay`, while the profile settings flow was the only place that wrote `ttsEnabled`. Users who enabled voice response from chat could therefore see the toggle as enabled while auto-play remained blocked by stale playback state.

## Technical Details

Files modified:

- `application/single_app/static/js/chat/chat-tts.js`
- `application/single_app/config.py`
- `functional_tests/test_chat_tts_autoplay_toggle.py`
- `ui_tests/test_chat_tts_autoplay_toggle.py`

Code changes summary:

- Chat TTS initialization now treats `ttsAutoplay` as an enabled playback state for backward compatibility with stale user settings.
- Enabling AI voice response from the chat toolbar now persists both `ttsAutoplay: true` and `ttsEnabled: true`.
- Failed toggle saves restore both the previous autoplay state and previous TTS enabled state.
- `config.py` version was updated to `0.242.048` for traceability.

## Testing Approach

Functional coverage was added in `functional_tests/test_chat_tts_autoplay_toggle.py` to validate that the source contract keeps auto-play and playback state aligned.

UI coverage was added in `ui_tests/test_chat_tts_autoplay_toggle.py` to validate that enabling the chat toolbar AI voice response toggle posts both settings to `/api/user/settings`.

## Impact Analysis

Users can now enable AI voice response directly from chat and have new assistant messages start playback automatically. Existing users with `ttsAutoplay` already enabled but `ttsEnabled` false are normalized on the next chat load without needing to visit profile settings.

## Validation

Before the fix, the chat toggle could enable `ttsAutoplay` while auto-play still skipped playback because `ttsEnabled` stayed false. After the fix, the same toggle enables playback state and auto-play can call the same working TTS playback path used by the manual button.
