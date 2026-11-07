// desktopNotifications.ts
// Operating-system notifications for replies that finish while nobody is watching the tab.
//
// This mirrors the classic interface (static/js/chat/chat-desktop-notifications.js) rule for
// rule, because the two share one preference and one administrator setting and must agree
// on what they mean:
//
// - It is on only when the administrator enabled desktop notifications and the user has not
//   turned them off. A user who never chose is opted in, as the server reads the preference
//   for classic (`bool(user_settings.get("desktopNotificationsEnabled", True))`).
// - A notification is raised only when the tab is hidden or the window does not have focus,
//   never for a reply the safety filter replaced, and never twice for one reply.
// - It names the application and the conversation, never the reply itself, so nothing from
//   the conversation is shown on a lock screen.
// - Permission is asked for once per page on send, and only while the browser has not been
//   told either way. Browsers ignore a request that is not tied to a user action.
//
// One thing is stricter than classic. V2 loads preferences after the page rather than with
// it, so until they have loaded -- or if they failed to -- the user's choice is unknown, and
// an unknown choice is treated as "off" rather than risk notifying someone who turned it off.

import { useBootstrapStore } from '../stores/bootstrapStore';
import { useUserSettingsStore } from '../stores/userSettingsStore';
import { getAppNavigator } from './appNavigation';
import { openConversationFromNotification } from './notificationNavigation';
import type { CompletedReply } from './replyEvents';

/** The preference key, shared with the classic profile page. */
export const DESKTOP_NOTIFICATIONS_SETTING = 'desktopNotificationsEnabled';

export type DesktopNotificationPermission = NotificationPermission | 'unsupported';

/** The stored preference, read the way the server reads it for classic. */
export function readDesktopNotificationPreference(value: unknown): boolean {
    return value === undefined ? true : Boolean(value);
}

export function adminAllowsDesktopNotifications(): boolean {
    return useBootstrapStore.getState().data?.features?.enable_desktop_notifications === true;
}

/** True when both the administrator and the user have desktop notifications on. */
export function desktopNotificationsEnabled(): boolean {
    if (!adminAllowsDesktopNotifications()) {
        return false;
    }
    const { settings, loading, error } = useUserSettingsStore.getState();
    if (loading || error) {
        return false;
    }
    return readDesktopNotificationPreference(settings[DESKTOP_NOTIFICATIONS_SETTING]);
}

export function desktopNotificationPermission(): DesktopNotificationPermission {
    if (typeof window === 'undefined' || !('Notification' in window)) {
        return 'unsupported';
    }
    return window.Notification.permission;
}

const permissionListeners = new Set<() => void>();

function announcePermission(): void {
    for (const listener of [...permissionListeners]) {
        listener();
    }
}

/**
 * Hear about possible permission changes, for `useSyncExternalStore`.
 *
 * A browser can change the permission from its own settings without telling the page, so
 * returning to the tab counts as a possible change too.
 */
export function subscribeDesktopNotificationPermission(listener: () => void): () => void {
    permissionListeners.add(listener);
    window.addEventListener('focus', listener);
    document.addEventListener('visibilitychange', listener);
    return () => {
        permissionListeners.delete(listener);
        window.removeEventListener('focus', listener);
        document.removeEventListener('visibilitychange', listener);
    };
}

let permissionRequested = false;

/**
 * Ask the browser for permission when it is still undecided.
 *
 * Call it directly from the user's click or key press, before anything is awaited: that is
 * the only moment a browser will show its prompt.
 *
 * On send (the default) it asks once per page and only while notifications are on, as
 * classic does. `explicit` is for a control whose whole purpose is asking -- turning the
 * preference on, or an "Allow" button -- which asks even if the page asked before, and even
 * though the preference that was just turned on may not be saved yet.
 */
export function requestDesktopNotificationPermission(
    options: { explicit?: boolean } = {},
): Promise<DesktopNotificationPermission> {
    const permission = desktopNotificationPermission();
    if (permission !== 'default' || !adminAllowsDesktopNotifications()) {
        return Promise.resolve(permission);
    }
    if (!options.explicit && (permissionRequested || !desktopNotificationsEnabled())) {
        return Promise.resolve(permission);
    }
    permissionRequested = true;
    try {
        return Promise.resolve(window.Notification.requestPermission())
            .catch((error: unknown) => {
                console.warn('Desktop notification permission request failed:', error);
            })
            .then(() => {
                announcePermission();
                return desktopNotificationPermission();
            });
    } catch (error) {
        console.warn('Desktop notification permission request failed:', error);
        return Promise.resolve(desktopNotificationPermission());
    }
}

const notifiedReplies = new Set<string>();

function replyKey(reply: CompletedReply): string {
    if (reply.messageId) {
        return `message:${reply.messageId}`;
    }
    if (reply.runId) {
        return `run:${reply.runId}`;
    }
    return `conversation:${reply.conversationId}`;
}

function appTitle(): string {
    return useBootstrapStore.getState().data?.branding?.app_title?.trim() || 'Simple Chat';
}

/** Whether the reader can already see the page, in which case the reply needs no notice. */
function pageIsWatched(): boolean {
    return document.visibilityState !== 'hidden' && document.hasFocus();
}

/**
 * Raise the notification for a finished reply, when every rule above allows it.
 *
 * Clicking it brings the window forward and opens the conversation the reply landed in.
 */
export function showReplyNotification(reply: CompletedReply): Notification | null {
    if (
        !desktopNotificationsEnabled()
        || reply.blocked
        || desktopNotificationPermission() !== 'granted'
        || pageIsWatched()
    ) {
        return null;
    }

    const key = replyKey(reply);
    if (notifiedReplies.has(key)) {
        return null;
    }

    try {
        const notification = new window.Notification(appTitle(), {
            body: reply.conversationTitle?.trim() || 'Conversation',
            // Shared with classic, so the system replaces an older notice for the same
            // conversation rather than stacking one per reply.
            tag: `simplechat-conversation-${reply.conversationId}`,
        });
        notifiedReplies.add(key);
        notification.addEventListener('click', () => {
            notification.close();
            // Opened before the window is brought forward, so the tab becomes visible already
            // knowing which conversation the reader is coming back to.
            const navigator = getAppNavigator();
            if (navigator) {
                openConversationFromNotification(reply.conversationId, {
                    navigate: navigator.navigate,
                    pathname: navigator.pathname(),
                });
            }
            window.focus();
        });
        return notification;
    } catch (error) {
        console.warn('Desktop conversation notification could not be shown:', error);
        return null;
    }
}
