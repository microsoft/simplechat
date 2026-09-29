// notificationNavigation.ts
// Following a resolved notification link.
//
// Shared by the notification panel and the desktop notifier, so a notice opens the same
// conversation the same way whichever of the two the user clicked.

import { OFF_SITE_LINK, sameSiteAddress, type NotificationTarget } from './notificationLinks';
import { chatHrefForConversation } from './conversationUrl';
import { GROUP_WORKSPACES } from './workspaces';
import { useChatStore } from '../stores/chatStore';
import { toast } from '../stores/toastStore';

export interface NotificationNavigationContext {
    navigate: (path: string) => void;
    /** The current route, relative to the router's `/v2` base. */
    pathname: string;
}

/**
 * Open a conversation from outside the chat page's own controls.
 *
 * The chat page reads `?conversationId=` once, on its first render, so a link that only
 * changed the query string while the page was already open would update the address bar and
 * leave the old thread on screen. On the chat page the store opens the conversation directly
 * instead -- and reports a deleted or inaccessible one itself -- while the page's own URL sync
 * writes the address bar to match. Anywhere else the link is simply followed.
 */
export function openConversationFromNotification(
    conversationId: string,
    context: NotificationNavigationContext,
): void {
    if (context.pathname === '/chat') {
        const chat = useChatStore.getState();
        if (chat.activeConversationId !== conversationId) {
            void chat.openLinkedConversation(conversationId);
        }
        return;
    }
    context.navigate(chatHrefForConversation(conversationId));
}

/**
 * Follow a target.
 *
 * A classic page is opened with a full navigation. Its address is read back once more first,
 * as the last step before the page is left: the resolver only builds addresses on this site,
 * and nothing that leaves it is followed even if that ever changed. Then the group the notice
 * is about is made the active group -- best-effort, as classic does -- because classic group
 * pages act on the active group rather than on one named in their URL. V2 routes name their
 * workspace in the path, so they never need it.
 */
export async function openNotificationTarget(
    target: NotificationTarget,
    context: NotificationNavigationContext,
): Promise<void> {
    if (target.kind === 'conversation') {
        openConversationFromNotification(target.conversationId, context);
        return;
    }
    if (target.kind === 'route') {
        context.navigate(target.path);
        return;
    }
    const address = sameSiteAddress(target.href, window.location.origin);
    if (!address) {
        toast.error(OFF_SITE_LINK);
        return;
    }
    if (target.groupId) {
        try {
            await GROUP_WORKSPACES.setActive(target.groupId);
        } catch {
            /* Advisory, as in classic: the page still opens, on whichever group was active. */
        }
    }
    window.location.assign(address);
}
