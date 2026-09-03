// sse.ts
// Server-Sent Events reader for POST /api/chat/stream.
//
// The native EventSource API cannot be used here: it only issues GET requests and cannot
// send a JSON body, while SimpleChat's streaming endpoint is a POST. So the stream is read
// manually from the fetch ReadableStream.
//
// The framing rules below intentionally match static/js/chat/chat-streaming.js so that V2
// consumes byte-for-byte the same stream the V1 client does.

import { apiUrl, API_BASE } from './apiClient';
import type { ChatStreamEvent, ChatStreamRequest } from './types';

const CREDENTIALS_MODE: RequestCredentials = API_BASE ? 'include' : 'same-origin';

/**
 * Repairs frames whose blank-line delimiter was emitted literally escaped as `\n\n`
 * instead of as real newlines. Older server paths can produce this, and V1 carries the
 * same repair, so dropping it here would silently lose events.
 */
export function normalizeLegacyEscapedSseDelimiters(chunk: string): string {
    return String(chunk || '').replace(
        /(\})\\n\\n(?=(?:data:|event:|id:|retry:|:|$))/g,
        '$1\n\n',
    );
}

/**
 * Extract the JSON payload from one SSE frame. A frame may carry several `data:` lines,
 * which per the SSE spec are joined with newlines to form a single payload.
 */
export function parseSseEventPayload(eventBlock: string): string | null {
    const dataLines = eventBlock.split('\n').filter((line) => line.startsWith('data:'));
    if (dataLines.length === 0) {
        return null;
    }
    return dataLines.map((line) => line.substring(5).trimStart()).join('\n');
}

export interface ChatStreamHandlers {
    /** A content delta arrived. Append it to the message being built. */
    onContent?: (delta: string, accumulated: string) => void;
    /** A reasoning/thought event arrived (`type: "thought"`). */
    onThought?: (event: ChatStreamEvent) => void;
    /** Conversation metadata, typically the server-assigned id and generated title. */
    onConversationMetadata?: (event: ChatStreamEvent) => void;
    /** The user's message reached durable storage (`type: "user_message_persisted"`). */
    onUserMessagePersisted?: (event: ChatStreamEvent) => void;
    /** Terminal frame carrying the final assistant message and its metadata. */
    onDone?: (event: ChatStreamEvent, accumulated: string) => void;
    /** The stream was cancelled, either by the user or server-side. */
    onCancelled?: (event: ChatStreamEvent, accumulated: string) => void;
    /** An error frame arrived, or the transport failed. */
    onError?: (message: string, event?: ChatStreamEvent) => void;
    /**
     * A reconnect is being attempted; nothing is arriving yet.
     *
     * Separate from `onReconnect` because the two mean different things to a reader: this
     * is "trying to get back", while `onReconnect` is "back, and the answer is flowing
     * again". Showing the first state for the whole reattached stream makes a working
     * response look stalled.
     */
    onReconnecting?: () => void;
    /**
     * A dropped stream is being resumed and everything received so far must be discarded.
     *
     * `/api/chat/stream/reattach` calls `iter_events()` with no start index
     * (route_backend_chats.py:24643), and that replays the session from its first event
     * rather than resuming at an offset. Keeping the earlier content would therefore
     * duplicate the whole answer.
     */
    onReconnect?: () => void;
}

export interface ChatStreamResult {
    accumulated: string;
    completed: boolean;
    cancelled: boolean;
    errored: boolean;
    /** True when the answer was finished by a reattached stream rather than the original. */
    reconnected: boolean;
}

/**
 * Status snapshot from `/api/chat/stream/status/<id>`.
 *
 * `_build_stream_status_payload` (route_backend_chats.py:2819) derives `pending` and
 * `reattachable` from `active`, so all three agree; `pending` is used here because that is
 * the field chat-streaming.js gates recovery on.
 */
export interface ChatStreamStatus {
    active?: boolean;
    pending?: boolean;
    reattachable?: boolean;
    status?: string;
    [key: string]: unknown;
}

/** Ask whether a conversation still has a live stream that could be reattached. */
export async function fetchStreamStatus(
    conversationId: string,
): Promise<ChatStreamStatus | null> {
    try {
        const response = await fetch(
            apiUrl(`/api/chat/stream/status/${encodeURIComponent(conversationId)}`),
            { credentials: CREDENTIALS_MODE, headers: { Accept: 'application/json' } },
        );
        if (!response.ok) {
            return null;
        }
        return (await response.json()) as ChatStreamStatus;
    } catch {
        return null;
    }
}

/** Reported instead of invoking `onError` directly, so recovery can suppress it. */
interface DeferredStreamError {
    message: string;
    event?: ChatStreamEvent;
}

/**
 * Read one already-open SSE response to a terminal frame.
 *
 * Shared by the initial POST and by a reattached GET so both consume byte-for-byte the
 * same framing. Errors are handed to `reportError` rather than to `handlers.onError` so
 * the caller can decide whether a reconnect makes them moot.
 */
async function consumeStreamResponse(
    response: Response,
    handlers: ChatStreamHandlers,
    result: ChatStreamResult,
    signal: AbortSignal | undefined,
    reportError: (message: string, event?: ChatStreamEvent) => void,
): Promise<void> {
    const reader = response.body!.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    /** Returns true when the frame was terminal and reading should stop. */
    const handleEvent = (event: ChatStreamEvent): boolean => {
        if (event.error) {
            result.errored = true;
            reportError(event.error, event);
            return true;
        }

        if (event.type === 'thought') {
            handlers.onThought?.(event);
            return false;
        }

        if (event.type === 'conversation_metadata') {
            handlers.onConversationMetadata?.(event);
            return false;
        }

        if (event.type === 'user_message_persisted') {
            handlers.onUserMessagePersisted?.(event);
            return false;
        }

        if (typeof event.content === 'string' && event.content.length > 0) {
            result.accumulated += event.content;
            handlers.onContent?.(event.content, result.accumulated);
        }

        if (event.done) {
            const wasCancelled =
                Boolean(event.cancelled) ||
                Boolean(event.canceled) ||
                event.type === 'cancelled' ||
                event.type === 'canceled';

            if (wasCancelled) {
                result.cancelled = true;
                handlers.onCancelled?.(event, result.accumulated);
            } else {
                result.completed = true;
                handlers.onDone?.(event, result.accumulated);
            }
            return true;
        }

        return false;
    };

    const handleFrame = (frame: string): boolean => {
        const json = parseSseEventPayload(frame);
        if (!json) {
            return false;
        }
        try {
            return handleEvent(JSON.parse(json) as ChatStreamEvent);
        } catch {
            // A malformed frame is skipped rather than killing an otherwise healthy
            // stream; the terminal frame is what decides completion.
            return false;
        }
    };

    const drainBuffer = (flush: boolean): boolean => {
        let delimiter = buffer.indexOf('\n\n');
        while (delimiter !== -1) {
            const frame = buffer.slice(0, delimiter);
            buffer = buffer.slice(delimiter + 2);
            if (handleFrame(frame)) {
                return true;
            }
            delimiter = buffer.indexOf('\n\n');
        }

        if (flush) {
            const trailing = buffer.trim();
            buffer = '';
            if (trailing) {
                return handleFrame(trailing);
            }
        }

        return false;
    };

    try {
        for (;;) {
            const { done, value } = await reader.read();

            if (done) {
                buffer += normalizeLegacyEscapedSseDelimiters(decoder.decode());
                const terminal = drainBuffer(true);
                if (!terminal && !result.completed && !result.cancelled && !result.errored) {
                    // The connection closed without a terminal frame. Surfaced as an error
                    // so the caller can offer a retry instead of leaving a half-written
                    // message on screen with no explanation.
                    result.errored = true;
                    reportError('The response ended unexpectedly.');
                }
                break;
            }

            buffer += normalizeLegacyEscapedSseDelimiters(
                decoder.decode(value, { stream: true }),
            );

            if (drainBuffer(false)) {
                break;
            }
        }
    } catch (error) {
        if (signal?.aborted) {
            result.cancelled = true;
        } else {
            result.errored = true;
            reportError(error instanceof Error ? error.message : 'Stream read error');
        }
    } finally {
        reader.cancel().catch(() => {
            /* Reader already closed. */
        });
    }
}

/**
 * Open the reattach stream for a conversation whose generation is still running.
 *
 * Returns false when there is nothing to attach to, which is the normal case: the server
 * answers 404 once the session is no longer active.
 */
async function attachToLiveStream(
    conversationId: string,
    handlers: ChatStreamHandlers,
    result: ChatStreamResult,
    signal: AbortSignal | undefined,
): Promise<boolean> {
    // Announced before the status check, because that round trip plus opening the stream is
    // exactly the window where the user is looking at a response that has stopped moving.
    handlers.onReconnecting?.();

    const status = await fetchStreamStatus(conversationId);
    if (!status?.pending) {
        return false;
    }

    let response: Response;
    try {
        response = await fetch(
            apiUrl(`/api/chat/stream/reattach/${encodeURIComponent(conversationId)}`),
            {
                method: 'GET',
                credentials: CREDENTIALS_MODE,
                headers: { Accept: 'text/event-stream' },
                signal,
            },
        );
    } catch {
        return false;
    }

    if (!response.ok || !response.body) {
        return false;
    }

    // The replay starts at the first event, so anything already rendered is a duplicate.
    result.accumulated = '';
    result.errored = false;
    result.reconnected = true;
    handlers.onReconnect?.();

    let recoveryError: DeferredStreamError | null = null;
    await consumeStreamResponse(response, handlers, result, signal, (message, event) => {
        recoveryError = { message, event };
    });

    if (recoveryError) {
        // Only one attempt, matching chat-streaming.js passing allowRecovery: false to the
        // reattached consumer. A second failure is reported rather than retried forever.
        const failure = recoveryError as DeferredStreamError;
        result.errored = true;
        handlers.onError?.(failure.message, failure.event);
    }

    return true;
}

/**
 * Resume an in-flight stream for a conversation, if one is still running.
 *
 * Used when a conversation is opened while its answer is still generating, which is what
 * chat-conversations.js:1695 does after selecting a conversation.
 */
export async function reattachChatStream(
    conversationId: string,
    handlers: ChatStreamHandlers,
    signal?: AbortSignal,
): Promise<ChatStreamResult | null> {
    const result: ChatStreamResult = {
        accumulated: '',
        completed: false,
        cancelled: false,
        errored: false,
        reconnected: false,
    };

    const attached = await attachToLiveStream(conversationId, handlers, result, signal);
    return attached ? result : null;
}

/**
 * Options that let a shared conversation reuse this transport.
 *
 * A shared conversation streams through `/api/collaboration/conversations/<id>/stream`,
 * which bridges to `/api/chat/stream` internally and re-emits its frames, so every handler
 * and the whole parser apply unchanged and only the URL differs.
 *
 * Recovery is the one thing that does not carry over. `/api/chat/stream/reattach` is keyed
 * on the conversation the generation actually runs in, which for a shared conversation is a
 * hidden source conversation the browser is never told the id of. Reattaching with the
 * shared conversation's id would address a conversation that endpoint has never heard of,
 * so recovery must be switched off rather than allowed to fail.
 */
export interface ChatStreamOptions {
    /** Endpoint to POST to. Defaults to the personal chat stream. */
    url?: string;
    /** Whether a dropped transport may be reattached to. Defaults to true. */
    allowRecovery?: boolean;
}

/**
 * Open a chat stream and dispatch frames to the supplied handlers.
 *
 * Resolves once the stream reaches a terminal state. Aborting via `signal` resolves with
 * `cancelled: true` rather than throwing, because a user pressing Stop is a normal outcome
 * rather than an error.
 *
 * If the transport drops before a terminal frame, the generation usually survives on the
 * server, so one reattach is attempted before the failure is reported.
 */
export async function streamChat(
    body: ChatStreamRequest,
    handlers: ChatStreamHandlers,
    signal?: AbortSignal,
    options: ChatStreamOptions = {},
): Promise<ChatStreamResult> {
    const result: ChatStreamResult = {
        accumulated: '',
        completed: false,
        cancelled: false,
        errored: false,
        reconnected: false,
    };

    // A new conversation has no id until the server assigns one, and recovery needs it.
    let conversationId = body.conversation_id ?? undefined;
    const trackingHandlers: ChatStreamHandlers = {
        ...handlers,
        onConversationMetadata: (event) => {
            if (typeof event.conversation_id === 'string' && event.conversation_id) {
                conversationId = event.conversation_id;
            }
            handlers.onConversationMetadata?.(event);
        },
    };

    let pendingError: DeferredStreamError | null = null;
    const captureError = (message: string, event?: ChatStreamEvent) => {
        pendingError = { message, event };
    };

    let response: Response;
    try {
        response = await fetch(options.url ?? apiUrl('/api/chat/stream'), {
            method: 'POST',
            credentials: CREDENTIALS_MODE,
            headers: {
                'Content-Type': 'application/json',
                Accept: 'text/event-stream',
            },
            body: JSON.stringify(body),
            signal,
        });
    } catch (error) {
        if (signal?.aborted) {
            result.cancelled = true;
            return result;
        }
        const message = error instanceof Error ? error.message : 'Network error';
        result.errored = true;
        captureError(message);
        response = undefined as unknown as Response;
    }

    if (!pendingError && (!response.ok || !response.body)) {
        // A failure before the stream opens comes back as a normal JSON error response.
        let message = `Stream failed with status ${response.status}`;
        try {
            const payload = (await response.json()) as { error?: string };
            if (payload?.error) {
                message = payload.error;
            }
        } catch {
            /* Non-JSON error body; keep the status-based message. */
        }
        // Reported through onError and returned rather than thrown: failure is already
        // modelled by result.errored, and throwing here would escape as an unhandled
        // rejection and skip the caller's post-stream cleanup.
        result.errored = true;
        captureError(message);
    } else if (!pendingError) {
        await consumeStreamResponse(response, trackingHandlers, result, signal, captureError);
    }

    if (pendingError && !signal?.aborted && conversationId && options.allowRecovery !== false) {
        // The answer is generated on the server and outlives the HTTP connection, so a
        // dropped transport is recoverable. attachToLiveStream reports its own failures.
        const attached = await attachToLiveStream(
            conversationId,
            trackingHandlers,
            result,
            signal,
        );
        if (attached) {
            pendingError = null;
        }
    }

    if (pendingError) {
        const failure = pendingError as DeferredStreamError;
        handlers.onError?.(failure.message, failure.event);
    }

    return result;
}

/**
 * Ask the server to stop generating. The stream itself ends with a cancelled frame.
 *
 * `url` overrides the endpoint for a shared conversation, whose cancel route resolves the
 * hidden source conversation before reaching the same stream registry.
 */
export async function cancelStream(conversationId: string, url?: string): Promise<void> {
    await fetch(
        url ?? apiUrl(`/api/chat/stream/cancel/${encodeURIComponent(conversationId)}`),
        {
            method: 'POST',
            credentials: CREDENTIALS_MODE,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ reason: 'user_requested' }),
        },
    ).catch(() => {
        /* Best effort: the stream is torn down client-side regardless. */
    });
}
