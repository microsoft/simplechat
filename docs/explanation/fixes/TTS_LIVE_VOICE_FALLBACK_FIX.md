# TTS Live Voice Fallback Fix - Version 0.241.099

Fixed/Implemented in version: **0.241.099**

## Issue Description

Text-to-speech playback could fail with a 500 response when a user's saved voice was not supported by the configured Azure Speech resource. One observed failure was Azure rejecting `en-US-Ava:DragonHDLatestNeural` with `Unsupported voice`, even though speech-to-text was configured correctly.

## Root Cause Analysis

The TTS voice picker returned a hardcoded DragonHD voice list. That list was treated as universally supported, but Azure Speech voice availability can vary by resource, region, SKU, rollout state, and voice family. A stale saved `ttsVoice` setting was then sent directly to Azure during synthesis.

## Technical Details

Files modified:

- `application/single_app/route_backend_tts.py`
- `application/single_app/config.py`
- `functional_tests/test_tts_voice_fallback.py`

Code changes summary:

- `/api/chat/tts/voices` now retrieves the live voice list from the configured Azure Speech resource and caches it briefly.
- The endpoint returns `default_voice`, `source`, and `warning` metadata so callers can tell whether live Azure voices or fallback voices were returned.
- `/api/chat/tts` validates requested/saved voices against the live list and falls back to a preferred supported voice or the first available voice.
- Unsupported-voice cancellations now trigger one refreshed voice lookup and retry with a different fallback voice before returning an error.
- Speed-adjusted SSML synthesis now escapes text and voice values before embedding them in SSML.
- `config.py` version was updated to `0.241.099` for traceability.

## Testing Approach

Functional coverage was added in `functional_tests/test_tts_voice_fallback.py` to validate:

- Supported requested voices are preserved.
- Stale DragonHD saved voices fall back to a supported live voice.
- Retry fallback skips a voice Azure already rejected.
- Azure unsupported-voice cancellation details are detected.
- Static backup voices avoid DragonHD-only names.

## Impact Analysis

Users no longer need to manually clear a stale TTS voice setting after Azure rejects it. The Profile voice picker should reflect voices available to the configured Speech resource, while chat playback can still proceed with a safe fallback if the saved voice becomes unavailable later.

## Validation

Before the fix, a saved unsupported voice caused `/api/chat/tts` to return 500 and the browser displayed a TTS error. After the fix, the backend chooses a supported fallback voice and retries unsupported-voice failures once with a refreshed live voice list.