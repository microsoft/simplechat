# Message Audio Export

Version implemented: **0.250.102**

Fixed/Implemented in version: **0.250.102**

## Overview

SimpleChat users can export an individual user or assistant chat message as an MP3 audio file. The export reuses the chat text-to-speech service and the user's selected voice and playback speed.

Related issue: microsoft/simplechat#628

## Dependencies

- `application/single_app/config.py` version `0.250.102`
- Azure Speech Service configured in Admin Settings
- **Enable Text-to-Speech Chat Output** enabled
- A browser that supports Blob downloads

## Technical Specifications

### Architecture

1. The message action reads visible plain text from the selected message.
2. The browser sends the text, active voice, and active speed to the existing authenticated `POST /api/chat/tts` endpoint.
3. Azure Speech synthesizes `Audio48Khz192KBitRateMonoMp3` output.
4. The browser downloads the returned `audio/mpeg` Blob with a timestamped `.mp3` filename.

SimpleChat does not save generated audio to Cosmos DB or Blob Storage. The audio bytes are transient between Azure Speech, the application response, and the user's browser download.

### Files

- `application/single_app/static/js/chat/chat-tts.js` provides shared MP3 Blob synthesis with the active TTS preferences.
- `application/single_app/static/js/chat/chat-message-export.js` converts visible message text into a downloadable MP3.
- `application/single_app/static/js/chat/chat-messages.js` adds the feature-gated message actions.
- `application/single_app/route_backend_tts.py` remains the authenticated synthesis endpoint.

### Security and access

- The action is rendered only when `enable_text_to_speech` is enabled.
- The backend endpoint remains protected by the backend TTS Blueprint user policy and route-level authentication decorators.
- The browser sends message text for synthesis; it does not send caller-selected conversation, workspace, or user identifiers.
- Service failures return client-safe errors through existing Bootstrap toast notifications.

## Usage Instructions

1. Configure Azure Speech Service in **Admin Settings**.
2. Enable **Text-to-Speech Chat Output**.
3. Open a chat containing a completed user or assistant message.
4. Open the message's **More actions** menu.
5. Select **Export to Audio**.
6. Wait for synthesis to complete and save the downloaded `message_audio_YYYYMMDD_HHMMSS.mp3` file.

The downloaded audio uses the voice and speed selected in the chat text-to-speech controls when the export begins. Speech-to-text input can remain disabled because message audio export is a text-to-speech feature.

## Testing and Validation

- `functional_tests/test_message_audio_export.py` validates the MP3 endpoint contract, active preference usage, feature gating, menu wiring, and version.
- `ui_tests/test_chat_message_audio_export.py` validates browser synthesis and downloads for user and assistant messages and verifies disabled deployments cannot invoke synthesis through the export function.
- Existing text-to-speech tests continue to cover playback, autoplay, voice selection, and speed formatting.

## Known Limitations

- MP3 is the only export format in this version.
- Azure Speech configuration, throttling, quotas, supported voices, and synthesis limits apply.
- Only visible message text is spoken. Markdown syntax, HTML markup, hidden metadata, and non-text generated artifacts are not included.
- Streaming assistant messages expose the action only after the message is complete.
