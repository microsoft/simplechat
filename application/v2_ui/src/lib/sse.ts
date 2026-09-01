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
}

export interface ChatStreamResult {
    accumulated: string;
    completed: boolean;
    cancelled: boolean;
    errored: boolean;
}

/**
 * Open a chat stream and dispatch frames to the supplied handlers.
 *
 * Resolves once the stream reaches a terminal state. Aborting via `signal` resolves with
 * `cancelled: true` rather than throwing, because a user pressing Stop is a normal outcome
 * rather than an error.
 */
export async function streamChat(
    body: ChatStreamRequest,
    handlers: ChatStreamHandlers,
    signal?: AbortSignal,
): Promise<ChatStreamResult> {
    const result: ChatStreamResult = {
        accumulated: '',
        completed: false,
        cancelled: false,
        errored: false,
    };

    let response: Response;
    try {
        response = await fetch(apiUrl('/api/chat/stream'), {
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
        handlers.onError?.(message);
        return result;
    }

    if (!response.ok || !response.body) {
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
        handlers.onError?.(message);
        return result;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    /** Returns true when the frame was terminal and reading should stop. */
    const handleEvent = (event: ChatStreamEvent): boolean => {
        if (event.error) {
            result.errored = true;
            handlers.onError?.(event.error, event);
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
                    handlers.onError?.('The response ended unexpectedly.');
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
            handlers.onError?.(error instanceof Error ? error.message : 'Stream read error');
        }
    } finally {
        reader.cancel().catch(() => {
            /* Reader already closed. */
        });
    }

    return result;
}

/** Ask the server to stop generating. The stream itself ends with a cancelled frame. */
export async function cancelStream(conversationId: string): Promise<void> {
    await fetch(apiUrl(`/api/chat/stream/cancel/${encodeURIComponent(conversationId)}`), {
        method: 'POST',
        credentials: CREDENTIALS_MODE,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: 'user_requested' }),
    }).catch(() => {
        /* Best effort: the stream is torn down client-side regardless. */
    });
}
