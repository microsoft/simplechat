# AI Response Completion Audio Cues

## Overview

AI response completion audio cues notify users when a personal-chat response
finishes outside the conversation they are actively viewing. Administrators
control whether the capability is available, and each user explicitly opts in
and chooses a local sound and volume.

**Implemented in version: 0.250.103**

## Dependencies

- Existing personal-chat `chat_response_complete` notifications
- Shared notification polling in `static/js/notifications.js`
- Successful chat stream finalization in `static/js/chat/chat-streaming.js`
- User settings persistence through `/api/user/settings`
- Ten bundled WAV assets under `static/audio/completion-cues/`

## Technical Specifications

### Architecture

The backend continues to create a `chat_response_complete` notification only
after a personal AI response is successfully persisted. A focused authenticated
endpoint returns recent completion event identities for the signed-in user.
The browser establishes a silent initial baseline, then handles only newly
observed message or notification IDs.

Successful live streams also send their completion identity directly to the
same browser manager. This provides an immediate cue in the originating tab,
while notification polling recovers completions that finish after navigation,
reload, or loss of the original stream connection.

Handled identities are kept in bounded, per-user `localStorage`, with the Web
Locks API coordinating claims across tabs when available. An event is marked
handled even when audio is muted, disabled, suppressed in the foreground, or
blocked by the browser. This prevents historical unread notifications, repeated
polls, reloads, duplicate tabs, and duplicate live/polled events from replaying
a cue.

Saved enable, mute, sound, and volume preferences are also synchronized through
per-user browser storage so existing tabs apply profile changes immediately.

### Playback Rules

A newly completed response plays once when either condition is true:

- Its conversation is not the conversation currently selected in Chat.
- The SimpleChat document is hidden or the browser window is unfocused.

No cue plays when the completed conversation is selected and the page is both
visible and focused. Failed, cancelled, and interrupted streams do not reach the
successful completion hook and therefore do not play a cue.

### Configuration

The admin setting is:

- `enable_chat_completion_audio_cues` (default: `false`)

Notification count responses and live-stream completion checks refresh this
gate from the server. Open pages therefore stop playing promptly after an
administrator disables the capability. Disabling also clears the browser's completion baseline. The server records the
admin transition timestamp, so the next poll after re-enable suppresses events
from the disabled period while retaining responses completed after activation.

The per-user settings are:

- `chatCompletionAudioEnabled` (default: `false`)
- `chatCompletionAudioMuted` (default: `false`)
- `chatCompletionAudioSound` (default: `aurora`)
- `chatCompletionAudioVolume` (integer `1..10`, default: `5`)

The available sounds are Aurora, Bell, Bloom, Chime, Crystal, Glimmer, Marimba,
Pulse, Spark, and Summit. All ten WAV files were synthesized specifically for
SimpleChat, contain no third-party samples, and are served only from the local
SimpleChat static asset path.

### API

`GET /api/notifications/chat-completions?limit=50`

Returns recent personal `chat_response_complete` event identities for the
authenticated user. Read events are included because an active conversation
can be marked read while its browser document is hidden or unfocused.

`GET /api/notifications/chat-completion-audio-status`

Returns the current server-authoritative admin gate for successful live-stream
completion checks.

## Usage Instructions

### Enable the Capability

1. Open **Admin Settings**.
2. Go to the AI voice and audio section.
3. Turn on **Enable AI Response Completion Audio Cues**.
4. Save Admin Settings.

### Configure a User Preference

1. Open **Profile** and select the **Settings** tab.
2. In **AI Response Completion Audio**, turn on **Play completion cues**.
3. Choose one of the ten sounds and use **Preview** to audition it.
4. Set volume from `1` to `10`.
5. Optionally mute cues without losing the selected sound or volume.
6. Select **Save Audio Preferences**.

## Testing and Validation

- `functional_tests/test_chat_completion_audio_cues.py` validates settings,
  assets, route/runtime wiring, foreground suppression, hidden playback,
  volume mapping, concurrency, and deduplication.
- `ui_tests/test_profile_completion_audio_cues.py` validates admin gating,
  profile persistence, sound preview, and browser playback behavior.
- Route policy tests cover authentication and Blueprint policy for the new API.

## Browser Limitations

Browsers can block programmatic audio until the user has interacted with the
site, and some operating systems or browser profiles suppress background sound.
SimpleChat catches these failures without interrupting chat or notification
polling. A blocked event is not retried automatically, which avoids delayed or
duplicate sounds.

The browser records a baseline timestamp when the feature becomes active.
Events completed before that timestamp are treated as historical, while a
response that finishes between activation/page load and the first poll remains
eligible for one cue.
