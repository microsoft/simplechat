# Speech-to-Text Chat Input Feature

## Overview
The Speech-to-Text Chat Input feature enables users to record voice messages up to 90 seconds in duration directly within the chat interface. The audio is transcribed using Azure Speech Service and inserted into the text input field for review before sending.

**Version Implemented:** 0.234.086

## Dependencies
- Azure Speech Service (existing configuration)
- Browser support for MediaRecorder API and Web Audio API
- Modern browsers: Chrome 49+, Edge 79+, Firefox 25+, Safari 14.1+

## Features
- 🎤 **Voice Recording**: Click the microphone button to start recording
- 📊 **Visual Waveform**: Real-time frequency visualization during recording
- ⏱️ **Countdown Timer**: 90-second maximum duration with visual countdown
- ✅ **Review Before Send**: Transcribed text is placed in the input field for user review
- 🚫 **Cancel Anytime**: Cancel recording without transcribing
- 📱 **Responsive Design**: Works on desktop and mobile devices

## Admin Setup

### 1. Enable Speech-to-Text Chat Input

1. Navigate to **Admin Settings** → **Content Processing** tab
2. Locate **Enable Speech-to-Text Chat Input** toggle
3. Check the box to enable the feature
4. Configure Speech Service settings (if not already configured for audio file support)

### 2. Configure Azure Speech Service

The feature uses the same Speech Service configuration as audio file support:

- **Endpoint**: Your Azure Speech Service endpoint  
  Format: `https://<location>.cognitiveservices.azure.com/`
  
- **Location**: Azure region (e.g., `eastus`, `westus2`)

- **Locale**: Speech recognition language (default: `en-US`)  
  Examples: `en-GB`, `es-ES`, `fr-FR`, `de-DE`

- **Authentication Type**: Choose authentication method
  - **Key**: Use API key from Azure portal
  - **Managed Identity**: Use Azure Managed Identity (recommended for production)

- **API Key**: Required if authentication type is "Key"

### 3. Save Settings

Click **Save Settings** at the bottom of the page to apply changes.

## User Workflow

### Starting a Voice Recording

1. **Click the microphone button** on the left side of the chat input field
2. **Grant microphone permission** when prompted by the browser
3. The recording UI appears with:
   - Real-time waveform visualization
   - Countdown timer starting at 90 seconds
   - Cancel and Send buttons

### During Recording

- **Waveform displays** real-time audio frequency data
- **Timer counts down** from 90 seconds
  - Green: 90-31 seconds remaining
  - Orange: 30-11 seconds remaining
  - Red: 10-0 seconds remaining (pulsing)
- **Recording auto-stops** at 0 seconds

### Completing the Recording

#### Option 1: Send Recording
1. Click the **Send button** (green with checkmark)
2. Audio is uploaded and transcribed
3. Transcribed text appears in the input field
4. Review and edit the text if needed
5. Click the regular send button to send the message

#### Option 2: Cancel Recording
1. Click the **Cancel button** (red with X)
2. Recording is discarded
3. Returns to normal input mode

### Transcription

- Transcription typically takes 2-5 seconds
- A spinner indicates processing
- Toast notification confirms success or shows errors
- Transcribed text can be edited before sending

## Technical Implementation

### Backend Components

#### API Endpoint
- **Route**: `/api/speech/transcribe-chat`
- **Method**: POST
- **Authentication**: Required (`@login_required`)
- **Input**: Audio file via FormData ('audio' field)
- **Output**: JSON with `{ success: true, text: "..." }` or error

#### Audio Processing
1. Receives audio blob (typically WebM/Opus format)
2. Converts to WAV format (16kHz, mono) using `pydub`
3. Uses `_get_speech_config()` helper from [functions_documents.py](c:\\Users\\paullizer\\OneDrive%20-%20Microsoft\\Repos\\GitHub\\microsoft\\simplechat\\application\\single_app\\functions_documents.py#L4770-L4784)
4. Transcribes using Azure Speech SDK `SpeechRecognizer`
5. Returns transcribed text

#### File Location
- Backend: `route_backend_speech.py`
- Registered in: `app.py`

### Frontend Components

#### JavaScript Module
- **File**: `static/js/chat/chat-speech-input.js`
- **Exports**: `initializeSpeechInput()`
- **Features**:
  - Browser compatibility detection
  - MediaRecorder API integration
  - Web Audio API for waveform visualization
  - Countdown timer management
  - Audio blob creation and upload
  - UI state management

#### CSS Styling
- **File**: `static/css/chat-speech-input.css`
- **Features**:
  - Recording UI layout
  - Waveform canvas styling
  - Animated countdown timer
  - Pulsing border effects
  - Responsive design

#### HTML Template
- **File**: `templates/chats.html`
- **Components**:
  - Microphone button (conditionally rendered)
  - Recording container with canvas
  - Cancel and send buttons
  - CSS conditional loading

#### Integration
- Initialized in `chat-onload.js`
- Conditional import based on feature enablement
- Toast notifications from `chat-toast.js`

## Browser Compatibility

### Supported Browsers
- ✅ **Chrome** 49+ (Desktop & Android)
- ✅ **Microsoft Edge** 79+
- ✅ **Firefox** 25+
- ✅ **Safari** 14.1+ (Desktop & iOS)
- ✅ **Opera** 36+

### Required APIs
- **MediaRecorder API**: For audio capture
- **Web Audio API**: For waveform visualization
- **getUserMedia**: For microphone access

### Unsupported Browsers
- Internet Explorer (all versions)
- Safari < 14.1
- Older mobile browsers

**Behavior**: If browser doesn't support required APIs, the microphone button is hidden automatically.

## Microphone Permissions

### First-Time Usage
1. Browser shows permission prompt
2. User must click **Allow** to enable recording
3. Permission is remembered for the site

### Permission Denied
- Toast notification: "Microphone permission denied"
- Instructions to enable in browser settings
- Button remains visible for retry

### Browser Permission Settings

**Chrome/Edge**:
1. Click lock icon in address bar
2. Find "Microphone" permission
3. Select "Allow"

**Firefox**:
1. Click shield icon in address bar
2. Permissions → Microphone → Allow

**Safari**:
1. Safari menu → Settings for This Website
2. Microphone → Allow

## Limitations

### Recording Duration
- **Maximum**: 90 seconds
- **Auto-stop**: Recording automatically stops at 90 seconds
- **Minimum**: No minimum duration enforced

### Audio Format
- **Capture**: WebM/Opus (browser native)
- **Backend Conversion**: Automatically converted to WAV
- **Quality**: 16kHz mono (optimized for speech)

### Concurrent Usage
- Only one recording can be active at a time
- Recording UI replaces normal input during capture

### Network Requirements
- Requires internet connection for transcription
- Audio uploaded to backend then to Azure Speech Service
- Large audio files may take longer on slow connections

## Troubleshooting

### Microphone Button Not Visible
**Causes**:
- Feature not enabled in admin settings
- Browser doesn't support required APIs
- JavaScript error on page load

**Solutions**:
1. Check admin settings → Enable Speech-to-Text Chat Input
2. Update to a supported browser version
3. Check browser console for JavaScript errors

### "Microphone Permission Denied" Error
**Causes**:
- User clicked "Block" on permission prompt
- Browser settings deny microphone access
- System-level microphone permissions disabled

**Solutions**:
1. Click microphone icon in address bar → Allow
2. Check browser settings for microphone permissions
3. Check OS settings (Windows: Privacy → Microphone)

### Transcription Fails
**Causes**:
- No speech detected in audio
- Poor audio quality or background noise
- Speech Service configuration incorrect
- Network connectivity issues

**Solutions**:
1. Speak clearly and close to microphone
2. Reduce background noise
3. Verify Speech Service settings in admin panel
4. Check Speech Service quota and billing in Azure portal

### Waveform Not Displaying
**Causes**:
- Web Audio API initialization failure
- Canvas element not found
- Audio stream not properly connected

**Solutions**:
1. Refresh the page
2. Try in a different supported browser
3. Check browser console for errors

### "No Speech Could Be Recognized"
**Causes**:
- Recording too quiet or silent
- Wrong language/locale configured
- Very short recording with no clear speech

**Solutions**:
1. Speak louder and more clearly
2. Check Speech Service locale matches your language
3. Record for at least 2-3 seconds with clear speech

### Recording Cuts Off Early
**Causes**:
- 90-second limit reached
- Browser tab lost focus (some browsers)
- System audio device changed

**Solutions**:
1. Keep messages under 90 seconds
2. Keep browser tab active during recording
3. Don't change audio devices during recording

## Security Considerations

### Data Privacy
- Audio is temporarily stored for transcription only
- Audio files are deleted immediately after transcription
- No audio recordings are permanently stored

### Authentication
- Requires user login (`@login_required`)
- Uses existing session authentication
- Only authenticated users can access transcription API

### Azure Speech Service
- Uses existing Speech Service configuration
- Supports both API key and Managed Identity authentication
- Managed Identity recommended for production (more secure)

## Performance

### Audio Upload Size
- 90 seconds of WebM/Opus audio ≈ 300-500 KB
- Typical transcription time: 2-5 seconds
- Upload time depends on network speed

### Resource Usage
- **Browser**: Minimal CPU for waveform visualization
- **Backend**: Temporary file creation + Speech SDK call
- **Azure**: Speech Service API call (billed per second of audio)

## Cost Considerations

### Azure Speech Service Pricing
- **Standard**: ~$1.00 per hour of audio
- **90-second recording**: ~$0.025 per transcription
- **Free tier**: 5 hours/month (if available)

### Recommendations
- Monitor usage in Azure portal
- Set spending alerts for Speech Service
- Consider usage limits for high-traffic applications

## Accessibility

### Keyboard Navigation
- Microphone button is focusable
- Tab key navigates to button
- Enter/Space key activates recording

### Screen Readers
- Button has descriptive title attribute
- Toast notifications are announced
- Recording state changes announced

### Visual Indicators
- Color is not the only indicator (also uses text/icons)
- Countdown timer uses size changes for emphasis
- High contrast between elements

## Future Enhancements

Potential improvements for future versions:

- 📝 Support for longer recordings (chunked uploads)
- 🌍 Multi-language detection
- 💾 Optional audio file saving
- 🎚️ Microphone sensitivity controls
- 📊 Audio level meter instead of waveform
- ⏸️ Pause/resume recording
- 🔇 Background noise reduction
- 📱 Native mobile app integration

## Related Documentation

- [Audio File Support Feature](AUDIO_FILE_SUPPORT.md) (uses same Speech Service)
- [Admin Configuration Guide](../admin_configuration.md)
- [Azure Speech Service Documentation](https://learn.microsoft.com/azure/ai-services/speech-service/)

## Version History

- **0.234.086**: Initial release of Speech-to-Text Chat Input feature
  - 90-second voice recording with waveform visualization
  - Countdown timer with color-coded warnings
  - Azure Speech Service integration
  - Browser compatibility detection
  - Toast notifications for errors
  - Responsive design for mobile and desktop
