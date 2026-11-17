// workflowActivityStream.ts
// Subscribing to one run's activity stream.
//
// `GET /api/{user|group}/workflows/activity/stream` sends the whole snapshot as one `data:` frame
// each time it changes, and a `: keep-alive` comment while it does not. It ends itself once the run
// has settled, and `EventSource` would then reconnect on its own; the page closes the stream when
// the snapshot it just read says the run is over (lib/workflowActivitySnapshot.ts,
// shouldListenForUpdates), so the reconnect never happens.
//
// Two things about the endpoint shape this module:
//
//   - A frame that is not JSON is skipped. One bad frame is not worth tearing the stream down for,
//     and the next frame carries the whole snapshot again, so nothing is lost.
//   - The server can end the stream with a named `error` event carrying a JSON body, when the run
//     fails the check that it may still be read. That is the one `error` event with data in it;
//     the connection's own failures carry none and are left to reconnect, as
//     collaborationEvents.ts leaves them.

import { API_BASE, apiUrl } from './apiClient';
import { workflowActivityApiUrl, type WorkflowActivityQuery } from './workflowActivity';

export const WORKFLOW_ACTIVITY_UNAVAILABLE = 'Workflow activity is no longer available.';

export interface WorkflowActivityStreamHandlers {
    /** One whole snapshot, as the endpoint sent it; the caller reads it into the page's shape. */
    onSnapshot: (snapshot: unknown) => void;
    /** The server closed the stream because this activity can no longer be read. */
    onUnavailable: (message: string) => void;
}

/**
 * Attach to the stream for a query.
 *
 * Returns the function that detaches. Calling it is required when the run settles or the page
 * leaves: `EventSource` reconnects by itself, so a stream nobody closed keeps a connection open
 * and keeps feeding a page that has moved on.
 */
export function subscribeToWorkflowActivity(
    query: WorkflowActivityQuery,
    handlers: WorkflowActivityStreamHandlers,
): () => void {
    if (typeof EventSource === 'undefined') {
        return () => {};
    }

    const source = new EventSource(apiUrl(workflowActivityApiUrl(query, true)), {
        // Only meaningful cross-origin, where the session cookie would otherwise be withheld.
        withCredentials: Boolean(API_BASE),
    });

    source.onmessage = (frame: MessageEvent<string>) => {
        if (!frame?.data) {
            return;
        }
        let snapshot: unknown;
        try {
            snapshot = JSON.parse(frame.data);
        } catch {
            return;
        }
        handlers.onSnapshot(snapshot);
    };

    source.addEventListener('error', (event: Event) => {
        if (!(event instanceof MessageEvent) || typeof event.data !== 'string' || !event.data) {
            return;
        }
        let message = WORKFLOW_ACTIVITY_UNAVAILABLE;
        try {
            const body: unknown = JSON.parse(event.data);
            const sentence = (body as { error?: unknown } | null)?.error;
            if (typeof sentence === 'string' && sentence.trim()) {
                message = sentence.trim();
            }
        } catch {
            /* The default sentence stands. */
        }
        source.close();
        handlers.onUnavailable(message);
    });

    return () => source.close();
}
