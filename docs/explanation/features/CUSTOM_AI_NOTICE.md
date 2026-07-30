# Custom AI Notice

## Overview

Administrators can display a custom plain-text AI notice directly below the chat input. The notice can remain permanently visible or allow users to dismiss it for the current session, the current UTC day, or the current configured message version.

Implemented in version: **0.250.102**

## Technical Specifications

### Architecture

- Application settings control whether the notice is enabled, its text, and its display behavior.
- `functions_ai_notice.py` normalizes settings and computes a SHA-256 version hash from the message and frequency.
- Session-only dismissals use browser session storage.
- Daily and once-per-version dismissals use the authenticated user-settings API and are timestamped by the server.
- Changing the notice text or display behavior creates a new hash, invalidating older dismissals.

### Configuration

The **General** tab in Admin Settings provides:

- **Show a custom AI notice below the chat input**
- **Notice Text**, limited to 1,000 plain-text characters
- **Display Behavior**:
  - Always visible; users cannot dismiss it
  - Dismissible once per session
  - Dismissible once per day
  - Dismissible once per message version

### Security and Accessibility

The message is rendered as escaped plain text with line breaks preserved. The feature does not accept HTML or Markdown. Dismissible notices expose an accessible button label, and the compact Bootstrap-based layout supports desktop and mobile chat widths.

## Usage

1. Open **Admin Settings**.
2. Select the **General** tab.
3. Enable **Chat AI Notice**.
4. Enter the notice text and choose a display behavior.
5. Save the settings.

The configured notice appears beneath the chat composer for users who have not dismissed the current notice under the selected policy.

## Testing and Validation

- `functional_tests/test_ai_notice.py` covers normalization, hashing, record validation, and recurrence behavior.
- `functional_tests/test_user_settings_allowlist_keys.py` covers dismissal persistence allowlisting.
- `ui_tests/test_chat_ai_notice_ui.py` covers admin controls and desktop/mobile placement.

Known limitation: session-only dismissals are specific to the current browser tab session. Daily and once-per-version dismissals follow the signed-in user across supported clients.
