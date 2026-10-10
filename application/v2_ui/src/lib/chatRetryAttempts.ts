// chatRetryAttempts.ts
// Attempt identity and logical placement, independent of the streaming transport.

import type { ChatMessage, Json } from './types';
import { currentAttempt, messageThreadId } from './threads';

export interface RetryPresentation {
    id: string;
    conversationId: string;
    userMessageId: string;
    sourceUserMessageId: string;
    hiddenMessageIds: string[];
    threadId?: string;
    attempt: number;
    admitted: boolean;
    kind: 'chat' | 'orchestration';
    error?: string;
    authUrl?: string | null;
}

export interface ResponseAttempt {
    kind?: string;
    state?: string;
    error?: string;
    run_id?: string;
}

function isRecord(value: unknown): value is Json {
    return value !== null && typeof value === 'object' && !Array.isArray(value);
}

export function savedResponseAttempt(message: ChatMessage | undefined): ResponseAttempt {
    const value = message?.metadata?.response_attempt;
    if (!isRecord(value)) return {};
    return {
        kind: typeof value.kind === 'string' ? value.kind : undefined,
        state: typeof value.state === 'string' ? value.state : undefined,
        error: typeof value.error === 'string' ? value.error : undefined,
        run_id: typeof value.run_id === 'string' ? value.run_id : undefined,
    };
}

export function messageOrchestrationTurn(message: ChatMessage | undefined): string | undefined {
    const orchestration = message?.metadata?.orchestration;
    const value = message?.metadata?.orchestration_turn_id ?? (isRecord(orchestration) ? orchestration.turn_id : undefined);
    return typeof value === 'string' && value ? value : undefined;
}

export function retryQuestion(messages: ChatMessage[], message: ChatMessage): ChatMessage | undefined {
    if (message.role === 'user') return message;
    const thread = messageThreadId(message);
    const turn = messageOrchestrationTurn(message);
    if (thread || turn) {
        return messages.find((candidate) => candidate.role === 'user' && (
            thread
                ? messageThreadId(candidate) === thread && currentAttempt(candidate) === currentAttempt(message)
                : messageOrchestrationTurn(candidate) === turn
        ));
    }
    const before = messages.slice(0, messages.findIndex((candidate) => candidate.id === message.id));
    return before.reverse().find((candidate) => candidate.role === 'user');
}

export function beginRetryPresentation(
    messages: ChatMessage[],
    question: ChatMessage,
    kind: RetryPresentation['kind'],
): RetryPresentation {
    const start = messages.findIndex((message) => message.id === question.id);
    const next = messages.findIndex((message, index) => index > start && message.role === 'user');
    const thread = messageThreadId(question);
    const turn = messageOrchestrationTurn(question);
    const hidden = messages.filter((message, index) => (
        message.id === question.id
        || (thread && messageThreadId(message) === thread && currentAttempt(message) === currentAttempt(question))
        || (turn && messageOrchestrationTurn(message) === turn)
        || (index > start && (next < 0 || index < next))
    ));
    return {
        id: crypto.randomUUID(),
        conversationId: question.conversation_id, userMessageId: question.id,
        sourceUserMessageId: question.id, hiddenMessageIds: hidden.map((message) => message.id),
        threadId: thread, attempt: currentAttempt(question), admitted: false, kind,
    };
}

export function adoptRetryQuestion(
    messages: ChatMessage[], presentation: RetryPresentation, question: ChatMessage,
): ChatMessage[] {
    const index = messages.findIndex((message) => message.id === presentation.userMessageId);
    const before = messages.slice(0, index < 0 ? messages.length : index);
    const after = index < 0 ? [] : messages.slice(index);
    const retained = (rows: ChatMessage[]) => rows.filter((message) =>
        !presentation.hiddenMessageIds.includes(message.id) && message.id !== question.id);
    return [...retained(before), question, ...retained(after)];
}

export function insertRetryReply(
    messages: ChatMessage[], reply: ChatMessage, presentation: RetryPresentation | null,
): ChatMessage[] {
    const withoutReply = messages.filter((message) => message.id !== reply.id);
    const question = presentation ? undefined : withoutReply.find((message) =>
        message.role === 'user' && messageThreadId(reply) && messageThreadId(message) === messageThreadId(reply)
        && currentAttempt(message) === currentAttempt(reply)
        && (savedResponseAttempt(message).kind || message.metadata?.retried || message.metadata?.edited));
    const questionId = presentation?.userMessageId ?? question?.id;
    const index = withoutReply.findIndex((message) => message.id === questionId);
    if (index < 0) return [...withoutReply, reply];
    return [...withoutReply.slice(0, index + 1), reply, ...withoutReply.slice(index + 1)];
}

export function updateRetryState(
    messages: ChatMessage[], presentation: RetryPresentation | null, state: string, error?: string,
): ChatMessage[] {
    if (!presentation?.admitted) return messages;
    return messages.map((message) => message.id === presentation.userMessageId ? {
        ...message,
        metadata: {
            ...message.metadata,
            response_attempt: {
                ...(isRecord(message.metadata?.response_attempt) ? message.metadata.response_attempt : {}),
                state, ...(error ? { error } : {}),
            },
        },
    } : message);
}

export function retryReplyMetadata(metadata: Json, presentation: RetryPresentation | null): Json {
    if (!presentation?.admitted || metadata.thread_info) return metadata;
    return {
        ...metadata,
        thread_info: {
            thread_id: presentation.threadId, thread_attempt: presentation.attempt, active_thread: true,
        },
    };
}

export function selectedAttemptError(question: ChatMessage, messages: ChatMessage[]): string | undefined {
    const attempt = savedResponseAttempt(question);
    if (!['failed', 'interrupted'].includes(attempt.state ?? '')) return undefined;
    const thread = messageThreadId(question);
    const safetyNotice = thread && messages.some((message) =>
        message.role === 'safety' && messageThreadId(message) === thread
        && currentAttempt(message) === currentAttempt(question));
    if (safetyNotice) return undefined;
    const recovered = thread && messages.some((message) =>
        message.role === 'assistant' && messageThreadId(message) === thread
        && currentAttempt(message) === currentAttempt(question)
        && isRecord(message.metadata?.orchestration) && message.metadata.orchestration.status === 'completed');
    return recovered ? undefined : attempt.error || (
        attempt.state === 'interrupted' ? 'This response was interrupted. You can retry this question.'
            : 'This attempt could not complete. You can retry this question.'
    );
}
