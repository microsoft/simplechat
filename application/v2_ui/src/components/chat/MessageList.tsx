// MessageList.tsx
// Renders the message thread, the in-flight streaming bubble and the reasoning panel.

import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { clsx } from 'clsx';
import {
    Brain,
    ChevronDown,
    EyeOff,
    FileText,
    ImageOff,
    PenLine,
    RefreshCw,
    Reply,
    Sparkles,
    TriangleAlert,
} from 'lucide-react';
import { useChatStore } from '../../stores/chatStore';
import { useCollaborationStore } from '../../stores/collaborationStore';
import { useBootstrapStore, useFeature } from '../../stores/bootstrapStore';
import { useUiStore } from '../../stores/uiStore';
import { bubbleWidthClass, chatWidthClass } from '../../lib/chatWidth';
import { resolveImageSource, imageEndpointBase } from '../../lib/images';
import { useImageEditCapability, useImageRevisions } from '../../lib/imageRevisions';
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
import { ImageLightbox } from './ImageLightbox';
import { ImageEditor } from './ImageEditor';
import { ImageProposalScope } from './ImageProposalContext';
import {
    extractProposalSpecs,
    findResultForSpec,
    groupProposalImages,
} from '../../lib/imageProposalSpec';
import {
    isAiRequest,
    isOwnMessage,
    messageAuthorName,
    resolveReplyContext,
} from '../../lib/sharedMessage';
import type { ChatMessage, CollaborationMessage, ThoughtEntry } from '../../lib/types';

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
    const [lightboxOpen, setLightboxOpen] = useState(false);
    const [editorOpen, setEditorOpen] = useState(false);
    const chatWidth = useUiStore((state) => state.chatWidth);
    const source = resolveImageSource(message.content);

    const imageGenerationEnabled = useFeature('enable_image_generation');
    const capability = useImageEditCapability();
    const revisions = useImageRevisions(
        message.id,
        String(message.prompt ?? ''),
        imageEndpointBase(source),
    );

    // Stable so the lightbox's download callback is not rebuilt on every render.
    const naming = useMemo(
        () => ({ filename: message.filename, prompt: message.prompt, id: message.id }),
        [message.filename, message.prompt, message.id],
    );

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

    // Offered only for an image the app generated. A user's own upload is not something the
    // image deployment can be asked to rework, and editing one is a separate decision.
    const editable =
        imageGenerationEnabled &&
        revisions.canPersist &&
        !Boolean((message.metadata as Record<string, unknown> | undefined)?.is_user_upload);

    return (
        <div id={`message-${message.id}`} className="group/message flex flex-col">
            <div className="flex justify-start">
                {/*
                  A button rather than a link: the image opens in a dialog, not a new
                  document. It also keeps the thumbnail keyboard operable, which a plain
                  clickable <img> would not be.
                */}
                <button
                    type="button"
                    onClick={() => setLightboxOpen(true)}
                    title="View the full-size image"
                    aria-label={`View the full-size image: ${alt}`}
                    aria-haspopup="dialog"
                    className="glass-flat block cursor-zoom-in overflow-hidden rounded-2xl p-1.5"
                >
                    <img
                        src={source.src}
                        alt={alt}
                        onError={() => setFailed(true)}
                        className="max-h-[28rem] max-w-md rounded-xl object-contain"
                    />
                </button>
            </div>
            <div className="flex items-center gap-1 opacity-0 transition-opacity group-hover/message:opacity-100 focus-within:opacity-100">
                <MessageActions message={message} />
                {editable && (
                    <button
                        type="button"
                        onClick={() => setEditorOpen(true)}
                        title="Change this image"
                        aria-haspopup="dialog"
                        className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1"
                    >
                        <PenLine size={13} />
                        Edit
                        {revisions.isEdited && (
                            <span
                                title="This image has been changed"
                                aria-label="Changed"
                                className="size-1.5 rounded-full bg-accent"
                            />
                        )}
                    </button>
                )}
            </div>

            {lightboxOpen && (
                <ImageLightbox
                    source={source}
                    title={alt}
                    naming={naming}
                    onClose={() => setLightboxOpen(false)}
                    onEdit={editable ? () => setEditorOpen(true) : undefined}
                />
            )}

            {editorOpen && (
                <ImageEditor
                    title={alt}
                    imageSrc={source.src}
                    revisions={revisions}
                    capability={capability}
                    onClose={() => setEditorOpen(false)}
                />
            )}
        </div>
    );
}

/**
 * A quotation of the message being replied to.
 *
 * Shared conversations are not linear the way a personal one is — several people write into
 * the same thread — so a reply that does not show what it answers is frequently
 * unintelligible by the time it is read.
 */
function ReplyQuote({ context }: { context: { display_name?: string; preview?: string } }) {
    return (
        <div className="mb-2 flex items-start gap-1.5 border-l-2 border-current/30 pl-2 text-[12px] opacity-70">
            <Reply size={12} className="mt-0.5 shrink-0" />
            <span className="min-w-0">
                {context.display_name && (
                    <span className="font-medium">{context.display_name}: </span>
                )}
                <span className="line-clamp-2">{context.preview}</span>
            </span>
        </div>
    );
}

/**
 * A file somebody attached to a shared conversation.
 *
 * `serialize_collaboration_message` gives an upload the display role `file`, which the
 * personal endpoints never emit. Rendered as a named attachment rather than as message
 * text, because `content` for one of these is extracted document text and can be the whole
 * document.
 */
function FileMessage({ message }: { message: ChatMessage }) {
    const chatWidth = useUiStore((state) => state.chatWidth);
    const currentUserId = useBootstrapStore((state) => state.data?.user?.id);
    const shared = message as CollaborationMessage;
    const author = messageAuthorName(message, currentUserId);
    const own = isOwnMessage(message, currentUserId);

    return (
        <div
            id={`message-${message.id}`}
            className={clsx('flex flex-col', own && 'items-end')}
        >
            {author && <p className="mb-1 px-1 text-[11px] text-text-3">{author}</p>}
            <div
                className={clsx(
                    bubbleWidthClass(chatWidth),
                    'glass-flat flex items-center gap-2 rounded-2xl px-4 py-3 text-[14px] text-text-1',
                )}
            >
                <FileText size={16} className="shrink-0 text-text-3" />
                <span className="truncate">{shared.filename || 'Attached file'}</span>
            </div>
        </div>
    );
}

function MessageBubbleInner({
    message,
    proposalImages,
}: {
    message: ChatMessage;
    /** Images generated from this message's own proposals, shown inside their cards. */
    proposalImages?: ChatMessage[];
}) {
    const isUser = message.role === 'user';
    const [editing, setEditing] = useState(false);
    const [draft, setDraft] = useState(message.content);
    const [inspector, setInspector] = useState<InspectorSection | null>(null);
    const bodyRef = useRef<HTMLDivElement>(null);
    const editMessage = useChatStore((state) => state.editMessage);
    const applyMask = useChatStore((state) => state.applyMask);
    const currentUserId = useBootstrapStore((state) => state.data?.user?.id);
    const chatWidth = useUiStore((state) => state.chatWidth);
    const messages = useChatStore((state) => state.messages);

    // Memoised because it walks the message's mask metadata and is read on every render of
    // the thread, which is often: the list re-renders on each streaming token.
    const masks = useMemo(() => readMaskState(message), [message]);
    const maskingAllowed = canMask(message, currentUserId);

    /**
     * Who wrote this, when that is a question worth answering.
     *
     * Empty for every personal conversation and for assistant replies, so nothing changes
     * outside a shared thread.
     */
    const author = messageAuthorName(message, currentUserId);
    const own = isOwnMessage(message, currentUserId);
    /**
     * Which side of the thread this message sits on.
     *
     * In a personal conversation that is simply "did the user write it". In a shared one it
     * is "did *this* reader write it": another participant's message is theirs, not the
     * reader's, and putting it on the reader's side would misattribute it at a glance.
     * `author` is empty outside a shared conversation, so this reduces to the old rule
     * there.
     */
    const alignRight = author ? own : isUser;
    const replyContext = useMemo(
        () => resolveReplyContext(message, messages, currentUserId),
        [message, messages, currentUserId],
    );

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

    if (message.role === 'file') {
        return <FileMessage message={message} />;
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
            className={clsx(
                'group/message flex flex-col transition-shadow',
                alignRight && 'items-end',
            )}
        >
            {/* Only ever present in a shared conversation, where a thread with several
                authors is unreadable without knowing who wrote what. */}
            {author && (
                <p className="mb-1 flex items-center gap-1.5 px-1 text-[11px] text-text-3">
                    <span className="font-medium">{author}</span>
                    {isAiRequest(message) && <span>asked the assistant</span>}
                </p>
            )}
            <div className={clsx('flex w-full', alignRight ? 'justify-end' : 'justify-start')}>
            <div
                ref={bodyRef}
                className={clsx(
                    bubbleWidthClass(chatWidth),
                    'rounded-2xl px-4 py-3',
                    // These are repeated per message, so they use the non-blurred surface:
                    // a backdrop-filter per bubble makes long threads scroll badly.
                    alignRight
                        ? 'bg-accent text-on-accent'
                        : 'glass-flat text-text-1',
                )}
            >
                {replyContext && <ReplyQuote context={replyContext} />}
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
                            alignRight ? 'text-on-accent/80' : 'text-text-3',
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
                        <ImageProposalScope
                            assistantMessageId={message.id}
                            results={proposalImages}
                        >
                            <AssistantMarkdown
                                content={message.content}
                                masks={masks.ranges}
                                messageId={message.id}
                            />
                        </ImageProposalScope>
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
                    alignRight={alignRight}
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
 * A message in the thread, re-rendered only when that message itself changes.
 *
 * Without this every message re-runs its whole markdown pipeline — remark, rehype and a fresh
 * React tree — on each streaming token and each time the scroll position crosses the pinned
 * threshold, because those both re-render the list. In a thread containing a large diagram
 * that is enough work per token to lock the interface up.
 *
 * The default shallow comparison is exactly right here: `message` is replaced by the store
 * when it changes, and `proposalImages` comes from a memoised map.
 */
const MessageBubble = memo(MessageBubbleInner);

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

/**
 * Who else is currently writing.
 *
 * Only ever populated in a shared conversation. It sits at the end of the thread rather
 * than under the composer so it reads as part of the conversation — the same place the
 * message being written will appear.
 */
function TypingIndicator() {
    const typingUsers = useCollaborationStore((state) => state.typingUsers);

    if (typingUsers.length === 0) {
        return null;
    }

    const names = typingUsers.map((entry) => entry.display_name);
    const label =
        names.length === 1
            ? `${names[0]} is typing`
            : names.length === 2
              ? `${names[0]} and ${names[1]} are typing`
              : `${names.length} people are typing`;

    return (
        <div className="flex justify-start">
            <p className="flex items-center gap-1.5 px-1 text-[12px] text-text-3">
                <span className="flex gap-1">
                    {[0, 150, 300].map((delay) => (
                        <span
                            key={delay}
                            className="h-1 w-1 animate-bounce rounded-full bg-text-3"
                            style={{ animationDelay: `${delay}ms` }}
                        />
                    ))}
                </span>
                {label}
            </p>
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

    /**
     * Whether the reader is at the bottom of the thread.
     *
     * A ref rather than state on purpose. Held in state, every scroll that crossed the
     * threshold re-rendered the list and with it every message's markdown, which is expensive
     * enough to stall a thread containing a large diagram. Nothing on screen depends on it, so
     * nothing needs to re-render when it changes.
     */
    const pinnedRef = useRef(true);

    const scrollToBottom = useCallback(() => {
        const element = scrollRef.current;
        if (element) {
            // Set directly rather than through `scrollIntoView`, which also scrolls every
            // scrollable ancestor and can drag the page itself around.
            element.scrollTop = element.scrollHeight;
        }
    }, []);

    // Auto-scroll only while the user is already at the bottom, so reading back through a
    // long answer is not interrupted by incoming tokens.
    useEffect(() => {
        if (pinnedRef.current) {
            scrollToBottom();
        }
    }, [messages, streamingContent, scrollToBottom]);

    /**
     * Follow content that grows after it was laid out.
     *
     * A diagram renders asynchronously: a 96px placeholder is replaced by a panel that can be
     * several hundred pixels tall, long after the scroll that was meant to land at the bottom.
     * Nothing re-ran, so the reader was left above the end of the thread, chasing a target that
     * moved every time another diagram finished.
     */
    useEffect(() => {
        const element = scrollRef.current;
        if (!element || typeof ResizeObserver === 'undefined') {
            return;
        }
        // The content, not the viewport: the viewport's own size changing is a window resize,
        // which should not yank the reader to the bottom.
        const content = element.firstElementChild;
        if (!content) {
            return;
        }
        const observer = new ResizeObserver(() => {
            if (pinnedRef.current) {
                scrollToBottom();
            }
        });
        observer.observe(content);
        return () => observer.disconnect();
    }, [scrollToBottom]);

    const onScroll = () => {
        const element = scrollRef.current;
        if (!element) {
            return;
        }
        const distanceFromBottom =
            element.scrollHeight - element.scrollTop - element.clientHeight;
        pinnedRef.current = distanceFromBottom < 80;
    };

    const isEmpty = useMemo(
        () => messages.length === 0 && !streaming && !messagesLoading,
        [messages.length, streaming, messagesLoading],
    );

    /**
     * Approved image proposals, filed under the assistant message that proposed them.
     *
     * The server stores an approved proposal as an ordinary `image` message carrying
     * `metadata.image_proposal.source_assistant_message_id`. Rendered as-is it would appear a
     * second time at the end of the thread, cut off from the paragraph that asked for it, so
     * it is routed to its own card instead — the same regrouping the classic client does in
     * `groupGeneratedImageProposalMessages`.
     *
     * An image is only taken out of the thread once a card in that message has been shown to
     * claim it, which is why the message's own fences are read here. Hiding an image on the
     * strength of the metadata alone would make it disappear entirely whenever a card could
     * not match it — after the prompt was edited before approval, say — and an image the user
     * paid to generate must never end up visible nowhere.
     */
    const { threadMessages, proposalImagesByMessage } = useMemo(() => {
        const grouped = groupProposalImages(messages);
        if (grouped.size === 0) {
            return { threadMessages: messages, proposalImagesByMessage: grouped };
        }

        const claimed = new Set<string>();
        for (const message of messages) {
            const candidates = message.role === 'assistant' ? grouped.get(message.id) : undefined;
            if (!candidates?.length) {
                continue;
            }
            for (const spec of extractProposalSpecs(message.content)) {
                const result = findResultForSpec(spec, candidates);
                if (result) {
                    claimed.add(result.id);
                }
            }
        }

        const visible = messages.filter(
            (message) => message.role !== 'image' || !claimed.has(message.id),
        );

        return { threadMessages: visible, proposalImagesByMessage: grouped };
    }, [messages]);

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
                    {threadMessages.map((message) => (
                        <MessageBubble
                            key={message.id}
                            message={message}
                            proposalImages={proposalImagesByMessage.get(message.id)}
                        />
                    ))}
                    {streaming && <StreamingBubble />}
                    <TypingIndicator />
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
            </div>
        </div>
    );
}
