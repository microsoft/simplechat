# Microphone Chat Response Audio Fix

Fixed in version: **0.250.203**

## Issue

Messages dictated with the chat microphone were transcribed and sent correctly, but the completed assistant response remained textual unless the user's global text-to-speech autoplay preference was already enabled.

## Root Cause

After transcription, the browser copied the transcript into the standard text composer and programmatically clicked Send. That discarded the microphone origin before the streaming request began, making dictated and typed turns indistinguishable to the response handler.

## Technical Details

- `chat-speech-input.js` now submits auto-sent transcripts with one-turn `voice` input and response modality options.
- `chat-messages.js` carries those modalities in the chat request and invokes the existing text-to-speech player after the final SSE message renders.
- Existing global TTS autoplay takes precedence, preventing duplicate playback.
- `chat-collaboration.js` forwards the initiating tab's completion callback without persisting modality or playing audio in other participants' browsers.
- Typed messages remain textual unless the user has independently enabled global TTS autoplay.

## Validation

- Added `functional_tests/test_chat_voice_turn_response.py` for microphone modality, request propagation, completion playback, and collaboration forwarding.
- Focused chat speech, TTS, and streaming suite: **9 passed**.
- JavaScript syntax checks and Python compilation passed.

## Impact

Users who dictate and auto-send a chat message now hear the corresponding assistant response when Azure text-to-speech is enabled. Message history and retries remain text-first, and voice modality applies only to the initiating turn and browser.
