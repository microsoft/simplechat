// useNotificationRuntime.ts
// Everything notifications need running while the application is mounted.
//
// Called once, from the application root, rather than from the bell: the bell is drawn by
// the sidebar and is not the only thing that depends on this. The desktop notifier has to
// hear about replies on every page, a desktop notification clicked on any page has to be
// able to open a conversation through the router, and the chat store has to know whether
// the chat page is on screen when a reply lands.

import { useEffect, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { announceRouteChange, registerAppNavigator } from './appNavigation';
import { showReplyNotification } from './desktopNotifications';
import { subscribeCompletedReplies } from './replyEvents';
import { startNotificationPolling, stopNotificationPolling } from '../stores/notificationStore';

/**
 * `ready` is whether the signed-in session has loaded. Nothing starts before it, because the
 * count is meaningless for a session that turns out to have expired.
 */
export function useNotificationRuntime(ready: boolean): void {
    const navigate = useNavigate();
    const { pathname, search } = useLocation();
    const pathnameRef = useRef(pathname);
    const navigateRef = useRef(navigate);
    const announcedPathname = useRef<string | null>(null);

    // Registered once, before any route is announced, and never swapped. The router hands out
    // a new `navigate` on every change of page; registering each one would leave no navigator
    // at all for the moment in between, and that moment is exactly when the change is
    // announced -- when the chat store asks which page is showing.
    useEffect(
        () =>
            registerAppNavigator({
                navigate: (path) => navigateRef.current(path),
                pathname: () => pathnameRef.current,
            }),
        [],
    );

    // Reported on a change of page, not of query string, but with the query string the page
    // was entered with: a link to the chat page names the conversation it is opening.
    useEffect(() => {
        navigateRef.current = navigate;
        pathnameRef.current = pathname;
        if (announcedPathname.current === pathname) {
            return;
        }
        announcedPathname.current = pathname;
        announceRouteChange({ pathname, search });
    }, [navigate, pathname, search]);

    useEffect(() => {
        if (!ready) {
            return undefined;
        }
        startNotificationPolling();
        const stopListening = subscribeCompletedReplies(showReplyNotification);
        return () => {
            stopListening();
            stopNotificationPolling();
        };
    }, [ready]);
}
