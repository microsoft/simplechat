# TTS Speech Speed Prosody Rate Fix - Version 0.241.102

Fixed/Implemented in version: **0.241.102**

## Issue Description

Text-to-speech speeds from `1.1x` through `2.0x` sounded the same during chat playback and voice preview, making the faster-speed slider settings effectively indistinguishable.

## Root Cause Analysis

The backend converted the user speed multiplier directly into an SSML percentage. For example, `1.1x` became `rate="110%"` and `2.0x` became `rate="200%"`. Azure Speech treats percentage rates as relative changes from the default speaking rate, so these values were interpreted as oversized speed increases and clamped near the same upper limit.

## Technical Details

Files modified:

- `application/single_app/route_backend_tts.py`
- `application/single_app/config.py`
- `functional_tests/test_tts_speech_speed_prosody_rate.py`

Code changes summary:

- Added TTS speed normalization to parse, validate, and clamp incoming speed multipliers to Azure Speech's supported `0.5x` to `2.0x` range.
- Converted speed multipliers into Azure Speech relative prosody percentages, such as `1.1x` to `+10.00%` and `2.0x` to `+100.00%`.
- Kept `1.0x` on normal plain-text synthesis while non-default speeds continue to use SSML.
- Updated `config.py` version to `0.241.102` for traceability.

## Testing Approach

Functional coverage was added in `functional_tests/test_tts_speech_speed_prosody_rate.py` to validate:

- Faster speeds from `1.1x` to `2.0x` generate distinct relative increase percentages.
- Slower speeds generate negative relative percentages.
- Normal speed maps to Azure's default prosody rate.
- Out-of-range speeds are clamped to the supported range.
- Invalid speed payloads raise a `ValueError` that the route returns as a client parameter error.

## Impact Analysis

Users should now hear distinct playback speeds across the full profile slider range. Saved speed preferences require no migration because the stored user setting remains the same multiplier value.

## Validation

Before the fix, values like `1.1x`, `1.5x`, and `2.0x` generated oversized SSML rates that Azure could clamp together. After the fix, those settings generate `+10.00%`, `+50.00%`, and `+100.00%` respectively, allowing Azure Speech to synthesize progressively faster audio.