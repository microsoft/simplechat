# Text-to-Speech (TTS) Feature

## Overview
The Text-to-Speech feature enables users to have AI assistant messages read aloud using Azure Speech Service with high-quality DragonHD voices. This creates a more immersive conversational experience and allows for hands-free interaction with the AI.

## Version Implemented
**Version:** 0.234.189

## Dependencies
- **Azure Speech Service** (Azure Cognitive Services)
- **Azure Speech SDK for Python** (`azure-cognitiveservices-speech`)
- **Backend:** Flask routes for TTS synthesis
- **Frontend:** JavaScript module for audio playback and controls

## Features

### 1. Voice Selection
- **27 DragonHD Latest Neural Voices** across multiple languages
- Voice preview functionality in user profile
- Customizable speech speed (0.5x - 2.0x)
- Grouped by language for easy selection

### 2. Playback Controls
- **Inline "Listen" button** on each AI assistant message
- **Play/Pause/Stop** controls
- Visual feedback during playback (message highlighting)
- Audio state management (prevents multiple simultaneous playbacks)

### 3. Auto-play Mode
- Optional automatic playback of AI responses
- Configurable per-user in profile settings
- **Automatically disables streaming** when auto-play is enabled (for complete message synthesis)

### 4. Streaming Integration
- Streaming is disabled when TTS auto-play is enabled
- Users can manually play any message regardless of streaming state
- Clear UI feedback about streaming/TTS state

## Configuration

### Admin Settings (Settings Page)
Located in **Search & Extract** tab:

1. **Enable Text-to-Speech AI Responses** toggle
2. **Speech Service Settings** (shared with Speech-to-Text):
   - Endpoint: `https://<region>.cognitiveservices.azure.com/`
   - Location: Azure region (e.g., `eastus2`)
   - API Key: Azure Speech Service key

### User Settings (Profile Page)
New **Text-to-Speech Settings** section includes:

1. **Voice Selection** dropdown
   - 27 DragonHD voices organized by language
   - Gender indicators (♂ Male, ♀ Female, ◉ Multi)
   - Status badges (GA vs Preview)

2. **Speech Speed** slider
   - Range: 0.5x (slower) to 2.0x (faster)
   - Default: 1.0x (normal speed)

3. **Voice Preview** button
   - Test selected voice with sample phrase
   - Shows voice name in sample text

4. **Auto-play Toggle**
   - Enable automatic playback of AI responses
   - Warning: Disables streaming when enabled

## Available Voices

### English (US) - 14 voices
- **en-US-Andrew:DragonHDLatestNeural** (Male, GA) - *Default*
- **en-US-Andrew2:DragonHDLatestNeural** (Male, GA) - Optimized for conversational content
- **en-US-Andrew3:DragonHDLatestNeural** (Male, Preview) - Optimized for podcast content
- **en-US-Adam:DragonHDLatestNeural** (Male, GA)
- **en-US-Alloy:DragonHDLatestNeural** (Male, Preview)
- **en-US-Brian:DragonHDLatestNeural** (Male, GA)
- **en-US-Davis:DragonHDLatestNeural** (Male, GA)
- **en-US-Steffan:DragonHDLatestNeural** (Male, GA)
- **en-US-Ava:DragonHDLatestNeural** (Female, GA)
- **en-US-Ava3:DragonHDLatestNeural** (Female, Preview) - Optimized for podcast content
- **en-US-Emma:DragonHDLatestNeural** (Female, GA)
- **en-US-Emma2:DragonHDLatestNeural** (Female, GA) - Optimized for conversational content
- **en-US-Aria:DragonHDLatestNeural** (Female, Preview)
- **en-US-Jenny:DragonHDLatestNeural** (Female, Preview)
- **en-US-Nova:DragonHDLatestNeural** (Female, Preview)
- **en-US-Phoebe:DragonHDLatestNeural** (Female, Preview)
- **en-US-Serena:DragonHDLatestNeural** (Female, Preview)
- **en-US-MultiTalker-Ava-Andrew:DragonHDLatestNeural** (Multi, Preview)

### German (DE) - 2 voices
- **de-DE-Florian:DragonHDLatestNeural** (Male, GA)
- **de-DE-Seraphina:DragonHDLatestNeural** (Female, GA)

### Spanish (ES) - 2 voices
- **es-ES-Tristan:DragonHDLatestNeural** (Male, GA)
- **es-ES-Ximena:DragonHDLatestNeural** (Female, GA)

### French (FR) - 2 voices
- **fr-FR-Remy:DragonHDLatestNeural** (Male, GA)
- **fr-FR-Vivienne:DragonHDLatestNeural** (Female, GA)

### Japanese (JP) - 2 voices
- **ja-JP-Masaru:DragonHDLatestNeural** (Male, GA)
- **ja-JP-Nanami:DragonHDLatestNeural** (Female, GA)

### Chinese (CN) - 2 voices
- **zh-CN-Xiaochen:DragonHDLatestNeural** (Female, GA)
- **zh-CN-Yunfan:DragonHDLatestNeural** (Male, GA)

## API Endpoints

### POST `/api/chat/tts`
Synthesize text to speech.

**Request Body:**
```json
{
  "text": "Text to synthesize",
  "voice": "en-US-Andrew:DragonHDLatestNeural",
  "speed": 1.0
}
```

**Response:**
- **Success:** Audio stream (MP3, 48kHz, 192kbps)
- **Error:** JSON with error message

### GET `/api/chat/tts/voices`
Get list of available DragonHD voices.

**Response:**
```json
{
  "voices": [
    {
      "name": "en-US-Andrew:DragonHDLatestNeural",
      "gender": "Male",
      "language": "English (US)",
      "status": "GA",
      "note": ""
    },
    ...
  ]
}
```

## Usage Instructions

### For Administrators
1. Navigate to **Admin Settings → Search & Extract** tab
2. Enable **Text-to-Speech AI Responses** toggle
3. Configure **Speech Service Settings**:
   - Enter Azure Speech Service endpoint
   - Enter region/location
   - Enter API key
4. Save settings

### For Users
1. Navigate to **Profile** page
2. Scroll to **Text-to-Speech Settings** section
3. Select preferred voice from dropdown
4. Adjust speech speed if desired
5. Click **Play Sample** to preview voice
6. (Optional) Enable **Auto-play for AI Responses**
7. Click **Save Voice Settings**

### In Chat
1. **Manual Playback:**
   - Click the speaker icon (🔊) on any AI assistant message
   - Click again to pause
   - Message will highlight during playback

2. **Auto-play Mode:**
   - Enable in profile settings
   - AI responses will automatically play when complete
   - Streaming will be disabled automatically

## Technical Specifications

### Architecture
- **Backend:** Python Flask with Azure Speech SDK
- **Frontend:** ES6 JavaScript modules
- **Audio Format:** MP3, 48kHz, 192kbps mono
- **Synthesis:** On-demand (no caching)

### File Structure
```
Backend:
├── route_backend_tts.py          # TTS API endpoints
├── config.py                      # Version and settings
└── functions_settings.py          # TTS enable flag

Frontend:
├── static/js/chat/
│   ├── chat-tts.js               # TTS module
│   ├── chat-messages.js          # Message rendering with TTS button
│   └── chat-streaming.js         # Streaming/TTS integration
├── static/css/chats.css          # TTS button styles
└── templates/
    ├── chats.html                # TTS script import
    ├── profile.html              # TTS settings UI
    └── admin_settings.html       # Admin TTS toggle
```

### User Settings Schema
```json
{
  "settings": {
    "ttsEnabled": true,
    "ttsVoice": "en-US-Andrew:DragonHDLatestNeural",
    "ttsSpeed": 1.0,
    "ttsAutoplay": false
  }
}
```

## Testing and Validation

### Functional Test
Location: `functional_tests/test_tts_integration.py`

Tests:
- TTS API endpoint availability
- Voice list retrieval
- Audio synthesis with different voices
- Speed adjustment
- Error handling

### Manual Testing Checklist
- [ ] Admin can enable/disable TTS feature
- [ ] User can select voice in profile
- [ ] Voice preview plays sample audio
- [ ] Speech speed slider affects playback
- [ ] "Listen" button appears on AI messages
- [ ] Audio plays when clicking "Listen" button
- [ ] Message highlights during playback
- [ ] Only one message plays at a time
- [ ] Auto-play works when enabled
- [ ] Streaming disables when auto-play enabled
- [ ] Streaming button shows correct tooltip

## Performance Considerations

### No Caching Strategy
- Audio is generated on-demand for each request
- Reduces storage requirements
- Ensures fresh synthesis with latest settings
- Trade-off: Slightly higher API latency (~1-2 seconds)

### API Rate Limits
- Azure Speech Service has per-second request limits
- Consider implementing client-side rate limiting for heavy usage
- Monitor Azure Speech Service quotas

## Known Limitations

1. **Streaming Incompatibility**
   - TTS auto-play requires complete message text
   - Streaming must be disabled for auto-play
   - Manual playback works on any message

2. **Browser Support**
   - Requires modern browser with Audio API support
   - Chrome, Edge, Firefox, Safari supported

3. **Language Detection**
   - Voice selection is manual
   - No automatic language detection

4. **Message Length**
   - Azure Speech Service has character limits per request
   - Very long messages may be truncated
   - Consider implementing chunking for long messages

## Future Enhancements

### Potential Features
1. **Voice Auto-selection**
   - Detect message language
   - Auto-select appropriate voice

2. **Playback Queue**
   - Queue multiple messages
   - Continuous playback mode

3. **Word Highlighting**
   - Real-time word-by-word highlighting
   - Requires SSML with word boundaries

4. **Audio Caching**
   - Optional server-side caching
   - Reduce API calls for repeated content

5. **Custom Voices**
   - Support for custom neural voices
   - Voice training integration

6. **Emotion and Emphasis**
   - SSML-based emotion control
   - Adjust prosody based on message sentiment

## Troubleshooting

### TTS Not Working
1. Check admin settings:
   - TTS feature enabled
   - Speech Service configured correctly
2. Check user settings:
   - Voice selected
   - TTS enabled in profile
3. Check browser console for errors
4. Verify Azure Speech Service credentials

### No Audio Output
1. Check browser audio permissions
2. Verify system volume not muted
3. Test with voice preview in profile
4. Check network connectivity to Azure

### Streaming Not Disabling
1. Verify TTS auto-play is enabled
2. Check localStorage for cached settings
3. Refresh page to reload settings

## Security Considerations

### Settings Sanitization
- Admin settings sanitized before sending to frontend
- API keys never exposed in client-side code
- User settings validated server-side

### API Key Management
- Store in Azure Key Vault (if enabled)
- Use managed identity when possible
- Rotate keys regularly

### Rate Limiting
- Implement per-user rate limiting
- Monitor for abuse
- Set reasonable quotas

## Related Documentation
- [Azure Speech Service Documentation](https://docs.microsoft.com/azure/cognitive-services/speech-service/)
- [Speech-to-Text Feature](./SPEECH_TO_TEXT.md)
- [Agent Integration](./AGENT_ORCHESTRATION.md)

## Support and Feedback
For issues, feature requests, or feedback, please contact the development team or file an issue in the project repository.
