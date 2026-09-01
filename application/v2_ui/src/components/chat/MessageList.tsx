// MessageList.tsx
// Renders the message thread, the in-flight streaming bubble and the reasoning panel.

import { useEffect, useMemo, useRef, useState } from 'react';
import { clsx } from 'clsx';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Brain, ChevronDown, Sparkles, TriangleAlert } from 'lucide-react';
import { useChatStore } from '../../stores/chatStore';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import { rehypeHighlightSubset } from '../../lib/rehypeHighlightSubset';
import { EmptyState, GlassPanel, Skeleton } from '../ui/primitives';
import type { ChatMessage, ThoughtEntry } from '../../lib/types';

/**
 * Markdown renderer for assistant output.
 *
 * Raw HTML is deliberately not enabled (no rehype-raw): model output is untrusted input,
 * and react-markdown's default of escaping HTML is what keeps this XSS-safe.
 */
function Markdown({ content }: { content: string }) {
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
                remarkPlugins={[remarkGfm]}
                rehypePlugins={[rehypeHighlightSubset]}
            >
                {content}
            </ReactMarkdown>
        </div>
    );
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
                <ol className="mt-1.5 space-y-1.5 border-l border-edge-strong pl-3">
                    {thoughts.map((thought) => (
                        <li key={thought.id} className="text-xs text-text-3">
                            <span className="font-medium text-text-2">{thought.title}</span>
                            <p className="mt-0.5 whitespace-pre-wrap">{thought.content}</p>
                        </li>
                    ))}
                </ol>
            )}
        </div>
    );
}

function MessageBubble({ message }: { message: ChatMessage }) {
    const isUser = message.role === 'user';

    if (message.role === 'image' && message.image_url) {
        return (
            <div className="flex justify-start">
                <img
                    src={message.image_url}
                    alt={message.content || 'Generated image'}
                    className="max-w-md rounded-2xl border border-edge"
                />
            </div>
        );
    }

    return (
        <div className={clsx('flex', isUser ? 'justify-end' : 'justify-start')}>
            <div
                className={clsx(
                    'max-w-[min(46rem,85%)] rounded-2xl px-4 py-3',
                    // These are repeated per message, so they use the non-blurred surface:
                    // a backdrop-filter per bubble makes long threads scroll badly.
                    isUser
                        ? 'bg-accent text-on-accent'
                        : 'glass-flat text-text-1',
                )}
            >
                {isUser ? (
                    <p className="text-[15px] leading-relaxed whitespace-pre-wrap">
                        {message.content}
                    </p>
                ) : (
                    <>
                        {message.thoughts && message.thoughts.length > 0 && (
                            <ThoughtsPanel thoughts={message.thoughts} />
                        )}
                        <Markdown content={message.content} />
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
    );
}

function StreamingBubble() {
    const { streamingContent, thoughts } = useChatStore();

    return (
        <div className="flex justify-start">
            <div className="glass-flat max-w-[min(46rem,85%)] rounded-2xl px-4 py-3">
                <ThoughtsPanel thoughts={thoughts} />
                {streamingContent ? (
                    <Markdown content={streamingContent} />
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
