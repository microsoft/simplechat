// idleSessionRuntime.ts
// Connects the idle-session controller (idleSession.ts) to the page: the real clock and
// timers, the DOM events that count as activity (in this document and in the same-origin
// frames it embeds), the heartbeat call, the local sign-out and the shared last-activity time
// other tabs write to localStorage.
//
// The heartbeat goes through apiClient like every other call, so the same-origin rules and the
// X-SimpleChat-UI marker apply to it, and an answer that says the session is over reaches the
// sign-in notice (SessionNotice) the way it does for any other call. The controller stops
// counting while that notice is up and starts again from now once sign-in is confirmed.

import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError, apiUrl } from './apiClient';
import {
    CLOSED_VIEW,
    IDLE_HEARTBEAT_ENDPOINT,
    IDLE_SIGN_OUT_PATH,
    SHARED_ACTIVITY_KEY,
    createIdleSessionController,
    type IdlePolicy,
    type IdleSessionController,
    type IdleSessionHost,
    type IdleSessionView,
} from './idleSession';
import { useAppSessionStore } from '../stores/appSessionStore';

/**
 * Input that shows someone is at the keyboard. Capture lets a scroll inside any pane count,
 * since a scroll event does not bubble and the page scrolls inside panes, not as a whole.
 */
const ACTIVITY_EVENTS = [
    'mousedown', 'mousemove', 'keydown', 'scroll', 'touchstart', 'click', 'wheel',
] as const;

/** How often the page looks for frames it has embedded since it last looked. */
const FRAME_SCAN_INTERVAL_MS = 5000;

/** Count input in `doc` as activity. Returns the function that stops. */
function listenForActivity(doc: Document, onActivity: () => void): () => void {
    for (const name of ACTIVITY_EVENTS) {
        doc.addEventListener(name, onActivity, { capture: true, passive: true });
    }
    return () => {
        for (const name of ACTIVITY_EVENTS) {
            doc.removeEventListener(name, onActivity, { capture: true });
        }
    };
}

/**
 * Count input inside the same-origin frames the page embeds, such as an embedded custom page.
 *
 * A frame is a separate document: its keys, clicks and scrolls never reach this one, so someone
 * working inside an embedded page would look idle here and be warned and signed out. Each frame
 * is listened to from the outside, as soon as it loads and on a slow scan for ones added without
 * a load event of their own. A frame from another origin cannot be read and is skipped.
 */
function watchEmbeddedFrames(onActivity: () => void): () => void {
    const watching = new Map<Document, () => void>();
    const loadWatched = new WeakSet<HTMLIFrameElement>();

    const scan = () => {
        for (const [inner, stop] of watching) {
            // The document of a frame that navigated or was removed has no window any more.
            if (!inner.defaultView) {
                stop();
                watching.delete(inner);
            }
        }
        for (const frame of document.querySelectorAll('iframe')) {
            if (!loadWatched.has(frame)) {
                loadWatched.add(frame);
                frame.addEventListener('load', scan);
            }
            let inner: Document | null = null;
            try {
                inner = frame.contentDocument;
            } catch {
                inner = null;
            }
            if (inner && !watching.has(inner)) {
                watching.set(inner, listenForActivity(inner, onActivity));
            }
        }
    };

    scan();
    const timer = window.setInterval(scan, FRAME_SCAN_INTERVAL_MS);
    return () => {
        window.clearInterval(timer);
        for (const stop of watching.values()) {
            stop();
        }
        watching.clear();
    };
}

function readSharedActivity(): string | null {
    try {
        return window.localStorage.getItem(SHARED_ACTIVITY_KEY);
    } catch {
        // Storage can be blocked; each tab then keeps its own clock, as classic does.
        return null;
    }
}

function writeSharedActivity(value: string): void {
    try {
        window.localStorage.setItem(SHARED_ACTIVITY_KEY, value);
    } catch {
        // See readSharedActivity.
    }
}

async function sendHeartbeat(): Promise<void> {
    const { revision } = useAppSessionStore.getState();
    try {
        await api.post<unknown>(IDLE_HEARTBEAT_ENDPOINT, {});
    } catch (error) {
        // apiClient reports the answers it recognises as an ended session. A 401 that does
        // not say why still means the sign-in is over.
        if (error instanceof ApiError && error.status === 401) {
            useAppSessionStore.getState().requireSignIn(revision);
        }
        throw error;
    }
}

function createBrowserHost(): IdleSessionHost {
    return {
        now: () => Date.now(),
        setTimer: (callback, delayMs) => window.setTimeout(callback, delayMs),
        clearTimer: (handle) => window.clearTimeout(handle as number),
        sendHeartbeat,
        sessionEnded: () => useAppSessionStore.getState().status !== 'ready',
        signOut: () => window.location.assign(apiUrl(IDLE_SIGN_OUT_PATH)),
        readSharedActivity,
        writeSharedActivity,
    };
}

export interface IdleSessionRuntime {
    view: IdleSessionView;
    stay: () => void;
    signOutNow: () => void;
}

/**
 * Run the idle-session warning for as long as `policy` is non-null.
 *
 * Mounted once, below the point where a session has loaded. A null policy (the timeout is off,
 * or the server did not describe one) attaches nothing.
 */
export function useIdleSessionRuntime(policy: IdlePolicy | null): IdleSessionRuntime {
    const [view, setView] = useState<IdleSessionView>(CLOSED_VIEW);
    const controller = useRef<IdleSessionController | null>(null);

    useEffect(() => {
        if (!policy) {
            return undefined;
        }
        const created = createIdleSessionController(policy, createBrowserHost(), setView);
        controller.current = created;

        const onActivity = () => created.activity();
        const onVisibility = () => {
            if (document.visibilityState === 'visible') {
                created.visible();
            }
        };
        const onStorage = (event: StorageEvent) => {
            // A null key is storage being cleared, which also forgets the shared time.
            if (event.key === SHARED_ACTIVITY_KEY || event.key === null) {
                created.sharedActivityChanged();
            }
        };
        const stopListening = listenForActivity(document, onActivity);
        const stopWatchingFrames = watchEmbeddedFrames(onActivity);
        document.addEventListener('visibilitychange', onVisibility);
        window.addEventListener('storage', onStorage);
        const unsubscribe = useAppSessionStore.subscribe((state, previous) => {
            if (state.status === previous.status) {
                return;
            }
            if (state.status === 'ready') {
                created.resume();
            } else {
                created.pause();
            }
        });

        created.start();
        if (useAppSessionStore.getState().status !== 'ready') {
            created.pause();
        }

        return () => {
            unsubscribe();
            window.removeEventListener('storage', onStorage);
            document.removeEventListener('visibilitychange', onVisibility);
            stopWatchingFrames();
            stopListening();
            created.stop();
            controller.current = null;
            setView(CLOSED_VIEW);
        };
    }, [policy]);

    const stay = useCallback(() => {
        void controller.current?.stay();
    }, []);
    const signOutNow = useCallback(() => {
        controller.current?.signOutNow();
    }, []);

    return { view, stay, signOutNow };
}
