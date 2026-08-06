// chat-desktop-notifications.js

const notifiedCompletionKeys = new Set();
let permissionRequestAttempted = false;

function getDesktopNotificationConfig() {
    const appSettings = window.appSettings || {};
    return {
        enabled: appSettings.enable_desktop_notifications === true
            && appSettings.desktop_notifications_enabled === true,
        appTitle: String(appSettings.app_title || 'Simple Chat').trim() || 'Simple Chat'
    };
}

function getConversationTitle(finalData = {}) {
    const eventTitle = String(finalData.conversation_title || '').trim();
    if (eventTitle) {
        return eventTitle;
    }

    const currentTitle = document.getElementById('current-conversation-title')?.textContent?.trim();
    return currentTitle || 'Conversation';
}

function getCompletionKey(finalData = {}) {
    const messageId = String(finalData.message_id || '').trim();
    if (messageId) {
        return `message:${messageId}`;
    }

    const conversationId = String(finalData.conversation_id || '').trim();
    return conversationId ? `conversation:${conversationId}` : '';
}

export function requestDesktopNotificationPermissionIfNeeded() {
    const config = getDesktopNotificationConfig();
    if (!config.enabled || !('Notification' in window) || Notification.permission !== 'default') {
        return Promise.resolve(window.Notification?.permission || 'unsupported');
    }
    if (permissionRequestAttempted) {
        return Promise.resolve(Notification.permission);
    }

    permissionRequestAttempted = true;
    return Notification.requestPermission().catch(error => {
        console.warn('Desktop notification permission request failed:', error);
        return Notification.permission;
    });
}

export function showDesktopConversationNotification(finalData = {}) {
    const config = getDesktopNotificationConfig();
    if (
        !config.enabled
        || finalData.blocked === true
        || finalData.role === 'safety'
        || !('Notification' in window)
        || Notification.permission !== 'granted'
        || (document.visibilityState !== 'hidden' && document.hasFocus())
    ) {
        return null;
    }

    const completionKey = getCompletionKey(finalData);
    if (completionKey && notifiedCompletionKeys.has(completionKey)) {
        return null;
    }

    try {
        const conversationId = String(finalData.conversation_id || '').trim();
        const notification = new Notification(config.appTitle, {
            body: getConversationTitle(finalData),
            tag: conversationId ? `simplechat-conversation-${conversationId}` : undefined
        });

        if (completionKey) {
            notifiedCompletionKeys.add(completionKey);
        }

        notification.addEventListener('click', () => {
            window.focus();
            notification.close();
        });

        return notification;
    } catch (error) {
        console.warn('Desktop conversation notification could not be shown:', error);
        return null;
    }
}

export function resetDesktopNotificationCompletionKeysForTesting() {
    notifiedCompletionKeys.clear();
    permissionRequestAttempted = false;
}
