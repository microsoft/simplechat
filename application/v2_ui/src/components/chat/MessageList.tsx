// MessageList.tsx
// Renders the message thread, the in-flight streaming bubble and the reasoning panel.

import { Children, useEffect, useMemo, useRef, useState } from 'react';
import { clsx } from 'clsx';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkBreaks from 'remark-breaks';
import { Brain, ChevronDown, EyeOff, ImageOff, Sparkles, TriangleAlert } from 'lucide-react';
import { useChatStore } from '../../stores/chatStore';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import { rehypeHighlightSubset } from '../../lib/rehypeHighlightSubset';
import { resolveImageSource } from '../../lib/images';
import {
    CITATION_PLACEHOLDER_PATTERN,
    parseCitations,
    type CitationGroup,
} from '../../lib/citations';
import { EmptyState, GlassButton, GlassPanel, Skeleton } from '../ui/primitives';
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
    type MaskedRange,
} from '../../lib/masking';
import { CitationChip } from './CitationChip';
import type { ChatMessage, ThoughtEntry } from '../../lib/types';

/**
 * Markdown renderer for assistant output.
 *
 * Raw HTML is deliberately not enabled (no rehype-raw): model output is untrusted input,
 * and react-markdown's default of escaping HTML is what keeps this XSS-safe.
 *
 * Citation markers are lifted out before rendering and swapped back in afterwards as
 * chips, so the markdown pipeline never sees them and no HTML is injected to support them.
 *
 * `remark-breaks` makes a single newline a line break. This deliberately differs from the
 * classic UI, which uses marked's defaults (`breaks: false`) so single newlines collapse
 * into the surrounding paragraph. Without it, identical text renders differently depending
 * on who sent it, because user messages are shown with `whitespace-pre-wrap` and keep every
 * newline. Models also emit single newlines expecting them to be honoured, and the classic
 * UI's own Word export uses markdown2's `break-on-newline` for exactly that reason.
 */
function Markdown({
    content,
    citations,
    masks,
}: {
    content: string;
    citations?: CitationGroup[];
    masks?: MaskedRange[];
}) {
    const groups = citations ?? [];
    const maskRanges = masks ?? [];

    /**
     * Substitute components for the placeholder tokens left in the text.
     *
     * Citations and masks both survive markdown as inert tokens and are swapped back in
     * here, so neither injects HTML into model output. A text node can contain both, so it
     * is split on each in turn rather than on one or the other.
     */
    const renderTokens = (children: React.ReactNode): React.ReactNode => {
        if (groups.length === 0 && maskRanges.length === 0) {
            return children;
        }

        return Children.map(children, (child) => {
            if (typeof child !== 'string') {
                return child;
            }

            // String.split with a capturing group interleaves text and captures, so odd
            // indices hold the captured index.
            const withMasks: React.ReactNode[] = [];
            child.split(MASK_PLACEHOLDER_PATTERN).forEach((part, index) => {
                if (index % 2 === 1) {
                    withMasks.push(
                        <MaskedSpan key={`mask-${index}`} range={maskRanges[Number(part)]} />,
                    );
                    return;
                }
                withMasks.push(part);
            });

            return withMasks.map((node, outer) => {
                if (typeof node !== 'string') {
                    return node;
                }
                const parts = node.split(CITATION_PLACEHOLDER_PATTERN);
                if (parts.length === 1) {
                    return node;
                }
                return parts.map((part, index) => {
                    if (index % 2 === 0) {
                        return part;
                    }
                    const group = groups[Number(part)];
                    return group ? (
                        <CitationChip key={`${outer}-${index}-${part}`} group={group} />
                    ) : null;
                });
            });
        });
    };

    return (
        <div
            className={clsx(
                'text-[15px] leading-relaxed break-words',
                '[&_p]:my-2 [&_p:first-child]:mt-0 [&_p:last-child]:mb-0',
                '[&_ul]:my-2 [&_ul]:list-disc [&_ul]:pl-5',
                '[&_ol]:my-2 [&_ol]:list-decimal [&_ol]:pl-5',
                '[&_li]:my-0.5',
                '[&_h1]:mt-4 [&_h1]:mb-2 [&_h1]:text-lg [&_h1]:font-semibold',
                '[&_h2]:mt-4 [&_h2]:mb-2 [&_h2]:text-base [&_h2]:font-semibold',
                '[&_h3]:mt-3 [&_h3]:mb-1.5 [&_h3]:text-sm [&_h3]:font-semibold',
                '[&_a]:text-accent [&_a]:underline',
                '[&_code]:rounded [&_code]:bg-surface-sunken [&_code]:px-1 [&_code]:py-0.5 [&_code]:font-mono [&_code]:text-[13px]',
                '[&_pre]:my-3 [&_pre]:overflow-x-auto [&_pre]:rounded-xl [&_pre]:bg-surface-sunken [&_pre]:p-3',
                '[&_pre_code]:bg-transparent [&_pre_code]:p-0',
                '[&_blockquote]:my-2 [&_blockquote]:border-l-2 [&_blockquote]:border-edge-strong [&_blockquote]:pl-3 [&_blockquote]:text-text-2',
                '[&_table]:my-3 [&_table]:w-full [&_table]:border-collapse [&_table]:text-sm',
                '[&_th]:border [&_th]:border-edge-strong [&_th]:bg-surface-sunken [&_th]:px-2 [&_th]:py-1 [&_th]:text-left',
                '[&_td]:border [&_td]:border-edge-strong [&_td]:px-2 [&_td]:py-1',
            )}
        >
            <ReactMarkdown
                remarkPlugins={[remarkGfm, remarkBreaks]}
                rehypePlugins={[rehypeHighlightSubset]}
                components={{
                    p: ({ children }) => <p>{renderTokens(children)}</p>,
                    li: ({ children }) => <li>{renderTokens(children)}</li>,
                    td: ({ children }) => <td>{renderTokens(children)}</td>,
                }}
            >
                {content}
            </ReactMarkdown>
        </div>
    );
}

/**
 * Assistant text with its citation markers turned into chips and masked spans redacted.
 *
 * Masks are applied FIRST: their offsets are canonical positions in the raw content, and
 * citation parsing rewrites the string, which would invalidate them.
 *
 * Parsing is memoised because it runs on every render of a long thread, and the streaming
 * bubble re-renders on each token.
 */
function AssistantMarkdown({
    content,
    masks,
}: {
    content: string;
    masks?: MaskedRange[];
}) {
    const { text, groups, ranges } = useMemo(() => {
        const masked = applyMasks(content, masks ?? []);
        const parsed = parseCitations(masked.text);
        return { ...parsed, ranges: masked.ranges };
    }, [content, masks]);

    return <Markdown content={text} citations={groups} masks={ranges} />;
}

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
    const source = resolveImageSource(message.content);

    // An unrecognised content shape, or an image that will not load, falls back to the
    // prompt text. A broken image element tells the user nothing.
    if (!source || failed) {
        return (
            <div id={`message-${message.id}`} className="flex justify-start">
                <div className="glass-flat max-w-[min(46rem,85%)] rounded-2xl px-4 py-3">
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
                <div className="w-full max-w-[min(46rem,85%)]">
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
                    'max-w-[min(46rem,85%)] rounded-2xl px-4 py-3',
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

function StreamingBubble() {
    const { streamingContent, thoughts } = useChatStore();

    return (
        <div className="flex justify-start">
            <div className="glass-flat max-w-[min(46rem,85%)] rounded-2xl px-4 py-3">
                <ThoughtsPanel thoughts={thoughts} />
                {streamingContent ? (
                    <AssistantMarkdown content={streamingContent} />
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
                        Thinking
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
            <div className="mx-auto w-full max-w-4xl space-y-4">
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
