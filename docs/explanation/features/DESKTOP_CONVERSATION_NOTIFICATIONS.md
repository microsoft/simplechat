# Desktop Conversation Notifications

Implemented in version: **0.250.102**

Related issue: **#866**

## Overview and Purpose

Desktop conversation notifications let users know when an AI response is ready while SimpleChat remains open in a hidden or unfocused browser tab. Administrators control whether the capability is available, and each user can enable or disable it from Profile.

The operating system notification uses the configured SimpleChat application title and the conversation title. It does not include the AI response or other conversation content.

## Technical Specifications

### Architecture

- `enable_desktop_notifications` is the disabled-by-default application setting controlled from Admin Settings.
- `desktopNotificationsEnabled` is the per-user Cosmos setting. It defaults to enabled when no explicit preference exists.
- The Chat route combines the administrator gate and user preference before exposing an effective boolean to the browser through sanitized settings.
- `chat-desktop-notifications.js` owns browser support checks, permission requests, focus and visibility gating, duplicate prevention, notification creation, and click-to-focus behavior.
- `chat-streaming.js` requests undecided permission from the next user-initiated chat send and emits a notification only for a successful terminal stream event.

### Notification Conditions

A notification is created only when all of these conditions are true:

1. An administrator enabled desktop conversation notifications.
2. The user did not disable the preference.
3. The browser supports the Notifications API.
4. The user granted browser notification permission.
5. SimpleChat is hidden or its browser window is unfocused.
6. The AI response completed successfully.

Cancelled, failed, interrupted, and duplicate terminal stream events do not create notifications.

### Security and Privacy

- Application settings are sanitized before they reach Chat or Profile.
- Notification title and body values are passed as inert strings to the browser Notifications API.
- AI response text is never included.
- No external JavaScript, service worker, push subscription, or third-party notification service is used.

## Usage Instructions

### Administrator

1. Open **Admin Settings**.
2. Locate **Desktop Conversation Notifications**.
3. Enable **Desktop Conversation Notifications** and save settings.

### User

1. Open **Profile** and select the settings tab.
2. Locate **Desktop Conversation Notifications**.
3. Keep **Notify me when an AI response is ready** enabled or turn it off.
4. Save the preference. If browser permission is undecided, approve the native permission request.

When permission is still undecided and the preference remains enabled, SimpleChat also requests permission on the user's next chat send. If permission was denied, the user must restore it from the browser's site settings.

Clicking a desktop notification focuses the existing SimpleChat tab.

## Testing and Validation

Coverage includes:

- Application and per-user defaults
- Administrator form persistence
- User settings allowlist and boolean validation
- Conditional Profile controls
- Browser permission request behavior
- Hidden and unfocused page gating
- Application and conversation title content
- Duplicate completion suppression
- Denied permission behavior
- Notification click-to-focus behavior

Related tests:

- `functional_tests/test_desktop_notification_settings.py`
- `functional_tests/test_user_settings_allowlist_keys.py`
- `functional_tests/test_chats_user_settings_hardening_fix.py`
- `ui_tests/test_chat_desktop_conversation_notifications.py`

## Known Limitations

- SimpleChat must remain open in a browser tab. Notifications are not delivered after the tab or browser is closed.
- Notifications require a secure browser context in production and are subject to browser and operating system notification policies.
- Browser permission denial cannot be reversed by SimpleChat; users must change the site's permission in browser settings.
- This feature covers completed AI conversation responses only. It does not mirror the durable SimpleChat in-app notification inbox.
