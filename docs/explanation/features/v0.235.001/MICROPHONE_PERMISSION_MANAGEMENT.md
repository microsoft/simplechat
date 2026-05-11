# Microphone Permission Management Feature

**Version:** 0.234.108  
**Implementation Date:** January 2, 2026

## Overview

The Microphone Permission Management feature provides users with granular control over how microphone permissions are handled for speech-to-text input. Users can choose between different permission request strategies and receive clear visual feedback about their microphone access state.

## Features

### 1. User Preference Options

Users can select from three permission management strategies:

- **Remember my choice** - Permission choice is saved permanently and the system will not re-request
- **Ask every browser session** (Recommended) - Permission is requested once per browser session
- **Ask every page load** - Permission is requested each time a page loads

### 2. Visual State Indicators

The microphone icon in the chat interface displays different colors based on permission state:

- **Green** (`text-success`) - Microphone access granted
- **Red** (`text-danger`) - Microphone access denied
- **Gray** (`text-secondary`) - Permission state not yet determined

### 3. Interactive Tooltips

Hovering over the microphone button shows contextual information:

- "Voice Input (Microphone access granted)" - When permission is granted
- "Microphone access denied - Click to manage permissions" - When permission is denied
- "Voice Input (Click to enable microphone)" - When permission not yet determined

### 4. Automatic Navigation

When the microphone icon is red (denied), clicking it automatically navigates to the profile page's microphone settings section (`/profile#speech-settings`) where users can:

- View their current permission status
- Change their permission preference
- See browser-level permission information

## Implementation Details

### Backend Changes

**File:** `route_backend_users.py`

Added two new allowed settings keys:
- `microphonePermissionPreference` - Stores user's permission strategy choice
- `microphonePermissionState` - Stores the last known permission state

```python
allowed_keys = {
    # ... existing keys ...
    'microphonePermissionPreference', 'microphonePermissionState',
    # ... other keys ...
}
```

### Frontend - Profile Page

**File:** `templates/profile.html`

Added new "Speech & Microphone Settings" section (visible only when `enable_speech_to_text_input` is enabled):

- **Permission Status Badge** - Shows current browser permission state
- **Preference Radio Buttons** - Three options for permission management
- **Save Button** - Persists user preferences to backend
- **Info Alert** - Provides context about permission management

**JavaScript Functions:**
- `saveMicrophoneSettings()` - Saves user preference to backend via `/api/user/settings`
- `loadMicrophoneSettings()` - Loads user preference from backend on page load
- `updateMicrophoneStatusBadge(status)` - Updates visual status badge

### Frontend - Chat Interface

**File:** `static/js/chat/chat-speech-input.js`

**New State Variables:**
```javascript
let microphonePermissionState = 'prompt'; // 'granted', 'denied', or 'prompt'
let userMicrophonePreference = 'ask-every-session'; // User's preference
let sessionPermissionRequested = false; // Session tracking
```

**New Functions:**
- `handleSpeechButtonClick()` - Intercepts button clicks to check permissions first
- `loadMicrophonePreference()` - Fetches user preference from `/api/user/settings`
- `shouldRequestPermission()` - Determines if permission should be requested based on preference
- `checkMicrophonePermissionState()` - Attempts to access microphone to determine permission state
- `updateMicrophoneIconState(state)` - Updates icon color and tooltip based on permission state
- `savePermissionState(state)` - Persists permission state when "remember" is selected

**Permission Request Logic:**

1. **Remember:**
   - Requests permission once
   - Saves state permanently
   - Never requests again unless permission state changes

2. **Ask every session:**
   - Requests permission once per browser session
   - Uses `sessionPermissionRequested` flag to track
   - Resets when browser is closed/reopened

3. **Ask every page load:**
   - Requests permission each time a page loads
   - Provides maximum privacy but may be intrusive

## User Workflow

### Normal Usage (Permission Granted)

1. User navigates to chat page
2. System loads user's permission preference
3. If preference requires it, system checks permission state
4. Icon appears green
5. User clicks microphone → Recording starts immediately

### First-Time Usage

1. User clicks microphone icon (gray)
2. Browser prompts for microphone permission
3. User grants permission
4. Icon turns green
5. Preference is saved based on user's settings
6. Recording begins

### Denied Permission Workflow

1. User denies microphone permission
2. Icon turns red
3. User clicks red microphone icon
4. User is redirected to `/profile#speech-settings`
5. User can:
   - See their permission preference
   - Change their preference
   - Understand they need to change browser-level permissions

### Changing Preferences

1. User navigates to Profile page
2. Scrolls to "Speech & Microphone Settings" section
3. Sees current permission status badge
4. Selects desired permission preference
5. Clicks "Save Microphone Settings"
6. Settings are persisted to backend
7. New preference takes effect on next page load or button click

## Technical Architecture

### Data Flow

```
User Action → Frontend JavaScript → Backend API → Cosmos DB
                     ↓
            Icon State Update
                     ↓
            Tooltip Update
```

### Storage

**Location:** Cosmos DB `users-<environment>` container

**Document Structure:**
```json
{
  "id": "user-id",
  "settings": {
    "microphonePermissionPreference": "ask-every-session",
    "microphonePermissionState": "granted",
    ...other settings...
  }
}
```

### Browser Compatibility

The feature uses try/catch for permission detection, making it compatible with:
- Chrome/Edge (full support)
- Firefox (full support)
- Safari/iOS (graceful degradation - relies on getUserMedia try/catch)

## Configuration

The feature is automatically enabled when:
```python
app_settings.enable_speech_to_text_input = True
```

No additional configuration is required.

## Testing

**Test File:** `functional_tests/test_microphone_permission_management.py`

Tests validate:
1. Backend accepts microphone permission settings keys
2. Profile.html contains all required UI elements and functions
3. chat-speech-input.js contains permission management code
4. Version was updated correctly

**Run Test:**
```bash
python functional_tests/test_microphone_permission_management.py
```

## Security Considerations

- Browser-level permissions are always respected
- No permissions can be granted programmatically
- User must explicitly grant via browser prompt
- Settings are stored per-user and isolated
- No cross-user permission state leakage

## Accessibility

- Tooltips provide screen reader context
- Color states supplemented with icon changes
- Clear button labels and help text
- Keyboard navigation supported

## Future Enhancements

Potential future improvements:
1. Add Permissions API support for browsers that support it (for more accurate state detection)
2. Add permission reset button on profile page
3. Show permission request history/log
4. Add analytics for permission grant/deny rates
5. Localization support for all text content

## Related Files

- `route_backend_users.py` - Backend API endpoint
- `templates/profile.html` - Settings UI
- `static/js/chat/chat-speech-input.js` - Permission management logic
- `static/js/chat/chat-user-settings.js` - Settings persistence helper
- `functional_tests/test_microphone_permission_management.py` - Automated tests

## Version History

- **0.234.108** - Initial implementation (January 2, 2026)
  - User preference selection
  - Visual state indicators
  - Automatic navigation on denied permissions
  - Persistent storage in user settings
