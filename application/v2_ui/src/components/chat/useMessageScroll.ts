// useMessageScroll.ts
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import {
    isMessageNearBottom,
    messageMatchesScrollId,
    messageScrollAliases,
    messageStartScrollTop,
    newestMessageArrival,
    type CompletedReply,
} from '../../lib/messageScroll';
import type { ChatMessage } from '../../lib/types';
import type { KeyboardEvent, WheelEvent } from 'react';

interface ScrollInput {
    conversationId: string | null;
    messages: ChatMessage[];
    loading: boolean;
    streaming: boolean;
    content: string;
    completedReply: CompletedReply | null;
}

interface ReadingAnchor {
    node: HTMLElement;
    offset: number;
}

export function useMessageScroll(input: ScrollInput) {
    const scrollRef = useRef<HTMLDivElement>(null);
    const previous = useRef<ScrollInput | null>(null);
    const latest = useRef(input);
    latest.current = input;
    const mode = useRef<'following' | 'reading' | 'manual'>('following');
    const pinnedRef = useRef(true);
    const caughtUp = useRef(true);
    const locked = useRef(false);
    const expectedTop = useRef<number | null>(null);
    const lastTop = useRef(0);
    const anchor = useRef<ReadingAnchor | null>(null);
    const liveAcknowledged = useRef(false);
    const unseenLive = useRef(false);
    const [hasNewMessages, setHasNewMessages] = useState(false);

    const writeTop = useCallback((top: number) => {
        const root = scrollRef.current;
        if (!root) return;
        root.scrollTop = top;
        expectedTop.current = root.scrollTop;
        lastTop.current = root.scrollTop;
        caughtUp.current = isMessageNearBottom(root.scrollTop, root.scrollHeight, root.clientHeight);
    }, []);

    const findMessage = useCallback((id: string) => {
        const message = latest.current.messages.find((item) => messageMatchesScrollId(item, id));
        return message ? Array.from(
            scrollRef.current?.querySelectorAll<HTMLElement>('[data-scroll-message-id]') ?? [],
        ).find((node) => node.dataset.scrollMessageId === message.id) ?? null : null;
    }, []);

    const liveNode = useCallback(() =>
        scrollRef.current?.querySelector<HTMLElement>('[data-scroll-live-reply]') ?? null, []);

    const captureAnchor = useCallback(() => {
        const root = scrollRef.current;
        if (!root) return;
        const box = root.getBoundingClientRect();
        const node = Array.from(root.querySelectorAll<HTMLElement>(
            '[data-scroll-message-id], [data-scroll-live-reply]',
        )).find((item) => item.getBoundingClientRect().bottom > box.top);
        anchor.current = node ? { node, offset: node.getBoundingClientRect().top - box.top } : null;
    }, []);

    const pauseFollowing = useCallback(() => {
        pinnedRef.current = false;
        mode.current = 'manual';
        locked.current = true;
        anchor.current = null;
    }, []);

    const readMessage = useCallback((node: HTMLElement, explicit = false) => {
        const root = scrollRef.current;
        if (!root) return;
        pinnedRef.current = false;
        mode.current = 'reading';
        locked.current = explicit;
        writeTop(messageStartScrollTop(root.scrollTop, root.getBoundingClientRect().top, node.getBoundingClientRect().top));
        anchor.current = { node, offset: node.getBoundingClientRect().top - root.getBoundingClientRect().top };
        setHasNewMessages(false);
        unseenLive.current = false;
    }, [writeTop]);

    const newestNode = useCallback(() => {
        const state = latest.current;
        if (state.streaming && state.content) return liveNode();
        const message = state.messages.at(-1);
        return message ? findMessage(message.id) : null;
    }, [findMessage, liveNode]);

    const jumpToNewest = useCallback(() => {
        const node = newestNode();
        if (!node) return;
        liveAcknowledged.current = true;
        readMessage(node, true);
    }, [newestNode, readMessage]);

    const onScroll = useCallback(() => {
        const root = scrollRef.current;
        if (!root) return;
        const top = root.scrollTop;
        if (expectedTop.current !== null && Math.abs(top - expectedTop.current) < 2) {
            expectedTop.current = null;
            return;
        }
        expectedTop.current = null;
        const movingUp = top < lastTop.current;
        caughtUp.current = isMessageNearBottom(top, root.scrollHeight, root.clientHeight);
        pinnedRef.current = !locked.current && !movingUp && caughtUp.current;
        mode.current = pinnedRef.current ? 'following' : 'manual';
        lastTop.current = top;
        if (pinnedRef.current) {
            anchor.current = null;
            liveAcknowledged.current = false;
            setHasNewMessages(false);
        } else {
            captureAnchor();
            const node = newestNode();
            if (node) {
                const start = node.getBoundingClientRect().top;
                const box = root.getBoundingClientRect();
                if (start >= box.top && start < box.bottom) {
                    liveAcknowledged.current = true;
                    setHasNewMessages(false);
                }
            }
        }
    }, [captureAnchor, newestNode]);

    const onWheel = useCallback((event: WheelEvent) => {
        locked.current = false;
        if (event.deltaY < 0) {
            pinnedRef.current = false;
            mode.current = 'manual';
            captureAnchor();
        }
    }, [captureAnchor]);

    const onKeyDown = useCallback((event: KeyboardEvent) => {
        if (['ArrowUp', 'PageUp', 'Home', 'ArrowDown', 'PageDown', 'End', ' '].includes(event.key)) {
            locked.current = false;
            if (['ArrowUp', 'PageUp', 'Home'].includes(event.key)) {
                pinnedRef.current = false;
                mode.current = 'manual';
                captureAnchor();
            }
        }
    }, [captureAnchor]);

    useLayoutEffect(() => {
        const root = scrollRef.current;
        const before = previous.current;
        previous.current = input;
        if (!root) return;
        const assignedFirstId = before?.conversationId === null && input.conversationId !== null
            && !input.loading && (before.streaming || before.messages.some((item) => item.id.startsWith('pending-user-')));
        const changedConversation = before && before.conversationId !== input.conversationId && !assignedFirstId;
        if (!before || changedConversation || before.loading) {
            mode.current = 'following';
            pinnedRef.current = true;
            locked.current = false;
            anchor.current = null;
            liveAcknowledged.current = false;
            unseenLive.current = false;
            setHasNewMessages(false);
            if (!input.loading) writeTop(root.scrollHeight);
            return;
        }
        if (input.loading) return;

        if (anchor.current && !anchor.current.node.isConnected && !before.streaming) {
            const oldId = anchor.current.node.dataset.scrollMessageId;
            const oldMessage = before.messages.find((message) => message.id === oldId);
            const replacement = oldMessage ? messageScrollAliases(oldMessage)
                .map((alias) => findMessage(alias.substring(3))).find((node) => node !== null) : null;
            if (replacement) anchor.current.node = replacement;
        }
        const following = pinnedRef.current || (mode.current === 'reading' && !locked.current && caughtUp.current);
        const completedReply = input.completedReply;
        const completion = completedReply && completedReply !== before.completedReply
            && completedReply.conversationId === input.conversationId;
        const arrival = input.messages !== before.messages ? newestMessageArrival(before.messages, input.messages) : null;
        if (input.streaming && !before.streaming) {
            liveAcknowledged.current = false;
            unseenLive.current = false;
            if (following) {
                pinnedRef.current = true;
                mode.current = 'following';
                anchor.current = null;
            }
        }

        if (completion && completedReply) {
            const node = findMessage(completedReply.messageId);
            if (node && following) {
                readMessage(node);
            } else if (node) {
                if (anchor.current && !anchor.current.node.isConnected) anchor.current.node = node;
                if (!liveAcknowledged.current) setHasNewMessages(true);
            }
        } else if (before.streaming && !input.streaming) {
            // Stopping or failing a stream is not successful completion. Keep the partial
            // reply at the same reading offset rather than jumping to an older answer.
            if (anchor.current && !anchor.current.node.isConnected) {
                const node = newestNode();
                anchor.current = node ? { node, offset: anchor.current.offset } : null;
            }
            pinnedRef.current = false;
            mode.current = 'reading';
            if (!arrival && unseenLive.current) setHasNewMessages(false);
        } else if (arrival && !input.streaming) {
            const node = findMessage(arrival.id);
            if (node && following) readMessage(node);
            else if (node) {
                unseenLive.current = false;
                setHasNewMessages(true);
            }
        } else if (arrival && !following) {
            unseenLive.current = false;
            setHasNewMessages(true);
        }

        if (input.streaming && pinnedRef.current) {
            writeTop(root.scrollHeight);
        } else if (input.streaming && input.content !== before.content && input.content && !liveAcknowledged.current) {
            unseenLive.current = true;
            setHasNewMessages(true);
        }
    }, [input.conversationId, input.messages, input.loading, input.streaming, input.content, input.completedReply,
        findMessage, newestNode, readMessage, writeTop]);

    useEffect(() => {
        const root = scrollRef.current;
        const content = root?.firstElementChild;
        if (!root || !content) return;
        const observer = new ResizeObserver((entries) => {
            if (pinnedRef.current && entries.some((entry) => entry.target === content)) {
                writeTop(root.scrollHeight);
            } else if (!pinnedRef.current && anchor.current?.node.isConnected) {
                const delta = anchor.current.node.getBoundingClientRect().top
                    - root.getBoundingClientRect().top - anchor.current.offset;
                if (Math.abs(delta) > 1) writeTop(root.scrollTop + delta);
            }
            caughtUp.current = isMessageNearBottom(root.scrollTop, root.scrollHeight, root.clientHeight);
        });
        observer.observe(content);
        observer.observe(root);
        return () => observer.disconnect();
    }, [writeTop]);

    return {
        scrollRef, hasNewMessages, onScroll, onWheel, onKeyDown, jumpToNewest, pauseFollowing,
        onTouchStart: () => { locked.current = false; },
        onPointerDown: () => { locked.current = false; },
    };
}
