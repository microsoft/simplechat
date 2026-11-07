// messageScroll.ts
import type { ChatMessage } from './types';

export const MESSAGE_READING_MARGIN = 24;
export const MESSAGE_FOLLOW_THRESHOLD = 80;

export interface CompletedReply {
    conversationId: string;
    messageId: string;
}

export function messageScrollAliases(message: ChatMessage): string[] {
    const aliases = [`id:${message.id}`];
    const source = message.metadata?.source_message_id;
    if (typeof source === 'string' && source) aliases.push(`id:${source}`);
    return aliases;
}

function threadScrollKey(message: ChatMessage): string | null {
    const thread = message.metadata?.thread_info;
    return thread && typeof thread === 'object' && 'thread_id' in thread && typeof thread.thread_id === 'string'
        ? `${message.role}:${thread.thread_id}` : null;
}

export function messageMatchesScrollId(message: ChatMessage, id: string): boolean {
    return messageScrollAliases(message).includes(`id:${id}`);
}

/** Updates, attempt switches and optimistic acknowledgements are not new tail messages. */
export function newestMessageArrival(previous: ChatMessage[], current: ChatMessage[]): ChatMessage | null {
    const known = new Set(previous.flatMap(messageScrollAliases));
    const currentAliases = new Set(current.flatMap(messageScrollAliases));
    const replaced = previous.filter((message) => !messageScrollAliases(message).some((alias) => currentAliases.has(alias)));
    const pending = replaced.filter((message) => message.id.startsWith('pending-user-'));
    const replacedThreads = new Set(replaced.map(threadScrollKey).filter((key) => key !== null));
    const recognized = current.map((message) =>
        messageScrollAliases(message).some((alias) => known.has(alias))
        || replacedThreads.has(threadScrollKey(message) ?? '')
        || pending.some((item) => item.role === message.role && item.content === message.content),
    );
    if (previous.length > 0 && !recognized.some(Boolean)) return null;
    const newest = current.at(-1);
    return newest && !recognized.at(-1) ? newest : null;
}

export function messageStartScrollTop(scrollTop: number, viewportTop: number, messageTop: number): number {
    return Math.max(0, scrollTop + messageTop - viewportTop - MESSAGE_READING_MARGIN);
}

export function isMessageNearBottom(scrollTop: number, scrollHeight: number, viewportHeight: number): boolean {
    return scrollHeight - scrollTop - viewportHeight < MESSAGE_FOLLOW_THRESHOLD;
}
