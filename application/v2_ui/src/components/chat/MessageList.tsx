// MessageList.tsx
// Renders the message thread, the in-flight streaming bubble and the reasoning panel.

import { useEffect, useMemo, useRef, useState } from 'react';
import { clsx } from 'clsx';
import {
    Brain,
    ChevronDown,
    EyeOff,
    ImageOff,
    RefreshCw,
    Sparkles,
    TriangleAlert,
} from 'lucide-react';
import { useChatStore } from '../../stores/chatStore';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import { useUiStore } from '../../stores/uiStore';
import { bubbleWidthClass, chatWidthClass } from '../../lib/chatWidth';
import { resolveImageSource } from '../../lib/images';
import { EmptyState, GlassButton, GlassPanel, Skeleton } from '../ui/primitives';
import { AssistantMarkdown } from './AssistantMarkdown';
import { MessageActions } from './MessageActions';
import { MessageInspector, type InspectorSection } from './MessageInspector';
import { ThoughtsList } from './ThoughtsList';
import { MaskedSpan, MaskSelectionPopup } from './MaskedSpan';
import {
    applyMasks,
    canMask,
    describeMask,
    MASK_PLACEHOLDER_PATTERN,
    readMaskState,
} from '../../lib/masking';
import type { ChatMessage, ThoughtEntry } from '../../lib/types';

function ThoughtsPanel({ thoughts }: { thoughts: ThoughtEntry[] }) {
    const [open, setOpen] = useState(false);

    if (thoughts.length === 0) {
        return null;
    }

    return (
        <div className="mb-2">
            <button
                type="button"
                onClick={() => setOpen((isOpen) => !isOpen)}
                aria-expanded={open}
                className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs text-text-3 transition-colors hover:bg-surface-2 hover:text-text-2"
            >
                <Brain size={13} />
                <span>
                    {thoughts.length} reasoning step{thoughts.length === 1 ? '' : 's'}
                </span>
                <ChevronDown
                    size={12}
                    className={clsx('transition-transform', open && 'rotate-180')}
                />
            </button>

            {open && (
                <div className="mt-1.5">
                    <ThoughtsList thoughts={thoughts} />
                </div>
            )}
        </div>
    );
}

function ImageMessage({ message }: { message: ChatMessage }) {
    const [failed, setFailed] = useState(false);
    const chatWidth = useUiStore((state) => state.chatWidth);
    const source = resolveImageSource(message.content);

    // An unrecognised content shape, or an image that will not load, falls back to the
    // prompt text. A broken image element tells the user nothing.
    if (!source || failed) {
        return (
            <div id={`message-${message.id}`} className="flex justify-start">
                <div className={clsx('glass-flat rounded-2xl px-4 py-3', bubbleWidthClass(chatWidth))}>
                    <p className="flex items-center gap-2 text-sm text-text-2">
                        <ImageOff size={15} className="shrink-0 text-text-3" />
                        {failed ? 'This image could not be loaded.' : 'Image unavailable.'}
                    </p>
                    {message.prompt ? (
                        <p className="mt-1 text-xs text-text-3">{String(message.prompt)}</p>
                    ) : null}
                </div>
            </div>
        );
    }

    const alt = String(message.prompt || message.filename || 'Generated image');

    return (
        <div id={`message-${message.id}`} className="group/message flex flex-col">
            <div className="flex justify-start">
                <a
                    href={source.src}
                    target="_blank"
                    rel="noopener noreferrer"
                    title="Open the full-size image"
                    className="glass-flat block overflow-hidden rounded-2xl p-1.5"
                >
                    <img
                        src={source.src}
                        alt={alt}
                        onError={() => setFailed(true)}
                        className="max-h-[28rem] max-w-md rounded-xl object-contain"
                    />
                </a>
            </div>
            <div className="opacity-0 transition-opacity group-hover/message:opacity-100 focus-within:opacity-100">
                <MessageActions message={message} />
            </div>
        </div>
    );
}

function MessageBubble({ message }: { message: ChatMessage }) {
    const isUser = message.role === 'user';
    const [editing, setEditing] = useState(false);
    const [draft, setDraft] = useState(message.content);
    const [inspector, setInspector] = useState<InspectorSection | null>(null);
    const bodyRef = useRef<HTMLDivElement>(null);
    const editMessage = useChatStore((state) => state.editMessage);
    const applyMask = useChatStore((state) => state.applyMask);
    const currentUserId = useBootstrapStore((state) => state.data?.user?.id);
    const chatWidth = useUiStore((state) => state.chatWidth);

    const masks = readMaskState(message);
    const maskingAllowed = canMask(message, currentUserId);

    // A user message is plain text, so its masked spans can be cut straight out of the
    // content rather than going through the markdown placeholder path.
    const maskedUserContent = useMemo(() => {
        if (!isUser || masks.ranges.length === 0) {
            return message.content;
        }
        const applied = applyMasks(message.content, masks.ranges);
        return applied.text.split(MASK_PLACEHOLDER_PATTERN).map((part, index) =>
            index % 2 === 1 ? (
                <MaskedSpan key={index} range={applied.ranges[Number(part)]} />
            ) : (
                part
            ),
        );
    }, [isUser, message.content, masks.ranges]);

    if (message.role === 'image') {
        return <ImageMessage message={message} />;
    }

    if (editing) {
        return (
            <div id={`message-${message.id}`} className="flex justify-end">
                <div className={clsx('w-full', bubbleWidthClass(chatWidth))}>
                    <textarea
                        autoFocus
                        value={draft}
                        onChange={(event) => setDraft(event.target.value)}
                        rows={Math.min(10, draft.split('\n').length + 1)}
                        aria-label="Edit message"
                        className="w-full resize-y rounded-2xl border border-accent bg-surface-solid px-4 py-3 text-[15px] text-text-1 outline-none"
                    />
                    <div className="mt-1.5 flex justify-end gap-2">
                        <GlassButton
                            size="sm"
                            onClick={() => {
                                setDraft(message.content);
                                setEditing(false);
                            }}
                        >
                            Cancel
                        </GlassButton>
                        <GlassButton
                            size="sm"
                            variant="primary"
                            disabled={!draft.trim() || draft === message.content}
                            onClick={() => {
                                setEditing(false);
                                void editMessage(message.id, draft);
                            }}
                        >
                            Save and resend
                        </GlassButton>
                    </div>
                </div>
            </div>
        );
    }

    return (
        <div
            id={`message-${message.id}`}
            className={clsx('group/message flex flex-col transition-shadow', isUser && 'items-end')}
        >
            <div className={clsx('flex w-full', isUser ? 'justify-end' : 'justify-start')}>
            <div
                ref={bodyRef}
                className={clsx(
                    bubbleWidthClass(chatWidth),
                    'rounded-2xl px-4 py-3',
                    // These are repeated per message, so they use the non-blurred surface:
                    // a backdrop-filter per bubble makes long threads scroll badly.
                    isUser
                        ? 'bg-accent text-on-accent'
                        : 'glass-flat text-text-1',
                )}
            >
                {masks.fullyMasked ? (
                    // The whole message is masked, so none of it is rendered. The server
                    // also withholds it from the model.
                    <p
                        title={describeMask({
                            start: 0,
                            end: 0,
                            display_name: masks.maskedBy,
                            timestamp: masks.maskedAt,
                        })}
                        className={clsx(
                            'flex items-center gap-2 text-[15px] italic',
                            isUser ? 'text-on-accent/80' : 'text-text-3',
                        )}
                    >
                        <EyeOff size={14} className="shrink-0" />
                        This message is masked
                        {masks.maskedBy ? ` by ${masks.maskedBy}` : ''}.
                    </p>
                ) : isUser ? (
                    <p className="text-[15px] leading-relaxed whitespace-pre-wrap">
                        {maskedUserContent}
                    </p>
                ) : (
                    <>
                        {message.thoughts && message.thoughts.length > 0 && (
                            <ThoughtsPanel thoughts={message.thoughts} />
                        )}
                        <AssistantMarkdown content={message.content} masks={masks.ranges} />
                        {(message.model_deployment_name || message.agent_display_name) && (
                            <p className="mt-2 flex items-center gap-1.5 text-[11px] text-text-3">
                                {message.agent_display_name ? (
                                    <>
                                        <Sparkles size={11} />
                                        {message.agent_display_name}
                                    </>
                                ) : (
                                    message.model_deployment_name
                                )}
                            </p>
                        )}
                    </>
                )}
            </div>
            </div>

            {maskingAllowed && !masks.fullyMasked && (
                <MaskSelectionPopup
                    containerRef={bodyRef}
                    onMask={(selection) => applyMask(message.id, 'mask_selection', selection)}
                />
            )}

            {/* Revealed on hover or keyboard focus so a long thread stays uncluttered,
                while remaining reachable without a pointer. The inspector, once opened,
                stays visible so it does not vanish when the pointer moves into it. */}
            <div
                className={clsx(
                    'transition-opacity group-hover/message:opacity-100 focus-within:opacity-100',
                    inspector ? 'opacity-100' : 'opacity-0',
                )}
            >
                <MessageActions
                    message={message}
                    onEdit={isUser ? () => setEditing(true) : undefined}
                    inspector={inspector}
                    onInspect={setInspector}
                />
            </div>

            {inspector && (
                <MessageInspector
                    message={message}
                    section={inspector}
                    onSection={setInspector}
                    onClose={() => setInspector(null)}
                />
            )}
        </div>
    );
}

/**
 * The bubble shown while a response is being generated.
 *
 * A recovered stream is deliberately made to look ordinary once it is flowing again. The
 * interruption is worth a brief note, but leaving "Reconnecting" under an answer that is
 * actively arriving reads as a stall, which is the opposite of what is happening.
 */
function StreamingBubble() {
    const { streamingContent, thoughts, reconnectPhase } = useChatStore();
    const chatWidth = useUiStore((state) => state.chatWidth);
    const [showReconnectedNote, setShowReconnectedNote] = useState(false);

    useEffect(() => {
        if (reconnectPhase !== 'reconnected') {
            setShowReconnectedNote(false);
            return;
        }
        // Long enough to be read, short enough that it does not become part of the answer.
        setShowReconnectedNote(true);
        const timer = window.setTimeout(() => setShowReconnectedNote(false), 4000);
        return () => window.clearTimeout(timer);
    }, [reconnectPhase]);

    const connecting = reconnectPhase === 'connecting';

    return (
        <div className="flex justify-start">
            <div className={clsx('glass-flat rounded-2xl px-4 py-3', bubbleWidthClass(chatWidth))}>
                {/* Shown while connecting even when partial content is already on screen:
                    without it, a response that stopped mid-sentence just looks frozen. */}
                {connecting && (
                    <p className="mb-2 flex items-center gap-1.5 text-xs text-text-3">
                        <RefreshCw size={12} className="animate-spin" />
                        Connection lost — picking the response back up…
                    </p>
                )}
                {showReconnectedNote && (
                    <p className="mb-2 flex items-center gap-1.5 text-xs text-text-3">
                        <RefreshCw size={12} />
                        Reconnected.
                    </p>
                )}
                <ThoughtsPanel thoughts={thoughts} />
                {streamingContent ? (
                    <AssistantMarkdown content={streamingContent} streaming />
                ) : (
                    <span className="flex items-center gap-1.5 text-sm text-text-3">
                        <span className="flex gap-1">
                            {[0, 150, 300].map((delay) => (
                                <span
                                    key={delay}
                                    className="h-1.5 w-1.5 animate-bounce rounded-full bg-text-3"
                                    style={{ animationDelay: `${delay}ms` }}
                                />
                            ))}
                        </span>
                        {connecting ? 'Reconnecting' : 'Thinking'}
                    </span>
                )}
            </div>
        </div>
    );
}

export function MessageList() {
    const {
        messages,
        messagesLoading,
        messagesError,
        streaming,
        streamingContent,
        streamError,
        activeConversationId,
    } = useChatStore();
    const appTitle = useBootstrapStore((state) => state.data?.branding?.app_title);
    const chatWidth = useUiStore((state) => state.chatWidth);

    const scrollRef = useRef<HTMLDivElement>(null);
    const bottomRef = useRef<HTMLDivElement>(null);
    const [pinnedToBottom, setPinnedToBottom] = useState(true);

    // Auto-scroll only while the user is already at the bottom, so reading back through a
    // long answer is not interrupted by incoming tokens.
    useEffect(() => {
        if (pinnedToBottom) {
            bottomRef.current?.scrollIntoView({ block: 'end' });
        }
    }, [messages, streamingContent, pinnedToBottom]);

    const onScroll = () => {
        const element = scrollRef.current;
        if (!element) {
            return;
        }
        const distanceFromBottom =
            element.scrollHeight - element.scrollTop - element.clientHeight;
        setPinnedToBottom(distanceFromBottom < 80);
    };

    const isEmpty = useMemo(
        () => messages.length === 0 && !streaming && !messagesLoading,
        [messages.length, streaming, messagesLoading],
    );

    return (
        <div
            ref={scrollRef}
            onScroll={onScroll}
            className="min-h-0 flex-1 overflow-y-auto px-4 py-6"
        >
            <div className={clsx('mx-auto w-full space-y-4', chatWidthClass(chatWidth))}>
                {messagesLoading && (
                    <div className="space-y-4">
                        <Skeleton className="ml-auto h-16 w-2/3" />
                        <Skeleton className="h-28 w-4/5" />
                    </div>
                )}

                {messagesError && (
                    <GlassPanel elevation="flat" className="flex items-center gap-2 p-3 text-sm text-danger">
                        <TriangleAlert size={16} />
                        {messagesError}
                    </GlassPanel>
                )}

                {isEmpty && !messagesError && (
                    <EmptyState
                        icon={<Sparkles size={30} />}
                        title={
                            activeConversationId
                                ? 'No messages in this conversation yet'
                                : `Start a conversation with ${appTitle || 'SimpleChat'}`
                        }
                        description="Ask a question, attach a document, or pick an agent to work with."
                    />
                )}

                {/* Streaming output is announced politely so screen reader users are told
                    a response arrived without every token interrupting them. */}
                <div aria-live="polite" aria-atomic="false" className="space-y-4">
                    {messages.map((message) => (
                        <MessageBubble key={message.id} message={message} />
                    ))}
                    {streaming && <StreamingBubble />}
                </div>

                {streamError && (
                    <GlassPanel
                        elevation="flat"
                        className="flex items-start gap-2 p-3 text-sm text-danger"
                    >
                        <TriangleAlert size={16} className="mt-0.5 shrink-0" />
                        <span>{streamError}</span>
                    </GlassPanel>
                )}

                <div ref={bottomRef} />
            </div>
        </div>
    );
}
