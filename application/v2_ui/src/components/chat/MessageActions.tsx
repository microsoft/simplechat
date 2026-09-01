// MessageActions.tsx
// Per-message action row, differing by role.
//
// User messages can be edited; assistant messages can be rated and forked. Both can be
// copied, retried, deleted, exported and reused as a prompt. Attempt navigation appears
// only once more than one attempt exists.

import { useEffect, useRef, useState } from 'react';
import { clsx } from 'clsx';
import {
    ChevronLeft,
    ChevronRight,
    Clipboard,
    ClipboardCheck,
    Copy,
    Ellipsis,
    FileDown,
    Mail,
    Pencil,
    RefreshCw,
    Split,
    ThumbsDown,
    ThumbsUp,
    Trash2,
} from 'lucide-react';
import { useChatStore } from '../../stores/chatStore';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import { apiUrl } from '../../lib/apiClient';
import { exportMessagePath, type MessageExportFormat } from '../../lib/endpoints';
import type { ChatMessage } from '../../lib/types';

/** Thread bookkeeping the server stores on each message. */
interface ThreadInfo {
    thread_id?: string;
    thread_attempt?: number;
    active_thread?: boolean;
}

function threadInfo(message: ChatMessage): ThreadInfo {
    const metadata = message.metadata as Record<string, unknown> | undefined;
    const info = metadata?.thread_info;
    return (info && typeof info === 'object' ? info : {}) as ThreadInfo;
}

function IconButton({
    label,
    onClick,
    children,
    active = false,
    disabled = false,
}: {
    label: string;
    onClick: () => void;
    children: React.ReactNode;
    active?: boolean;
    disabled?: boolean;
}) {
    return (
        <button
            type="button"
            onClick={onClick}
            disabled={disabled}
            title={label}
            aria-label={label}
            className={clsx(
                'rounded-md p-1.5 transition-colors disabled:cursor-not-allowed disabled:opacity-40',
                active
                    ? 'bg-accent-soft text-accent'
                    : 'text-text-3 hover:bg-surface-2 hover:text-text-1',
            )}
        >
            {children}
        </button>
    );
}

/**
 * Submit a hidden form to a server export endpoint.
 *
 * A normal fetch would put the file in memory with no way to hand it to the browser's
 * download machinery; a form POST lets the response's Content-Disposition do that.
 */
function postExport(format: MessageExportFormat, message: ChatMessage) {
    const form = document.createElement('form');
    form.method = 'POST';
    form.action = apiUrl(exportMessagePath(format));
    form.target = '_blank';
    form.style.display = 'none';

    const fields: Record<string, string> = {
        message_id: message.id,
        conversation_id: message.conversation_id,
    };

    for (const [name, value] of Object.entries(fields)) {
        const input = document.createElement('input');
        input.type = 'hidden';
        input.name = name;
        input.value = value;
        form.appendChild(input);
    }

    document.body.appendChild(form);
    form.submit();
    document.body.removeChild(form);
}

function downloadMarkdown(message: ChatMessage) {
    // No server endpoint exists for markdown; the content is already markdown, so it is
    // written client-side.
    const blob = new Blob([message.content], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `message-${message.id}.md`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
}

function OverflowMenu({
    message,
    onEdit,
}: {
    message: ChatMessage;
    onEdit?: () => void;
}) {
    const [open, setOpen] = useState(false);
    // The menu opens upward by default so it does not cover the next message, but near
    // the top of the scroll area there is no room above and it would render off-screen.
    const [placement, setPlacement] = useState<'up' | 'down'>('up');
    const containerRef = useRef<HTMLDivElement>(null);
    const { removeMessage } = useChatStore();
    const isUser = message.role === 'user';

    const toggle = () => {
        if (!open && containerRef.current) {
            const { top } = containerRef.current.getBoundingClientRect();
            // Roughly the tallest the menu gets; flipping on this is cheaper and steadier
            // than measuring the menu after it renders.
            setPlacement(top < 320 ? 'down' : 'up');
        }
        setOpen((isOpen) => !isOpen);
    };

    useEffect(() => {
        if (!open) {
            return;
        }
        const onPointerDown = (event: MouseEvent) => {
            if (!containerRef.current?.contains(event.target as Node)) {
                setOpen(false);
            }
        };
        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                setOpen(false);
            }
        };
        document.addEventListener('mousedown', onPointerDown);
        document.addEventListener('keydown', onKeyDown);
        return () => {
            document.removeEventListener('mousedown', onPointerDown);
            document.removeEventListener('keydown', onKeyDown);
        };
    }, [open]);

    const item = (
        label: string,
        icon: React.ReactNode,
        action: () => void,
        danger = false,
    ) => (
        <button
            key={label}
            type="button"
            onClick={() => {
                setOpen(false);
                action();
            }}
            className={clsx(
                'flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-sm',
                danger ? 'text-danger hover:bg-danger-soft' : 'text-text-1 hover:bg-surface-2',
            )}
        >
            {icon}
            {label}
        </button>
    );

    return (
        <div className="relative" ref={containerRef}>
            <IconButton label="More actions" onClick={toggle}>
                <Ellipsis size={15} />
            </IconButton>

            {open && (
                <div
                    className={clsx(
                        'glass-modal absolute right-0 z-50 w-52 rounded-xl p-1',
                        placement === 'up' ? 'bottom-full mb-1' : 'top-full mt-1',
                    )}
                >
                    {isUser && onEdit && item('Edit', <Pencil size={14} />, onEdit)}
                    {item('Use as prompt', <Clipboard size={14} />, () => {
                        const composer = document.getElementById(
                            'composer-input',
                        ) as HTMLTextAreaElement | null;
                        if (composer) {
                            composer.value = message.content;
                            // React controlled inputs ignore direct value writes, so the
                            // change is dispatched through the native setter.
                            const setter = Object.getOwnPropertyDescriptor(
                                window.HTMLTextAreaElement.prototype,
                                'value',
                            )?.set;
                            setter?.call(composer, message.content);
                            composer.dispatchEvent(new Event('input', { bubbles: true }));
                            composer.focus();
                        }
                    })}
                    {item('Download Markdown', <FileDown size={14} />, () =>
                        downloadMarkdown(message),
                    )}
                    {item('Export to Word', <FileDown size={14} />, () =>
                        postExport('word', message),
                    )}
                    {item('Export to PowerPoint', <FileDown size={14} />, () =>
                        postExport('powerpoint', message),
                    )}
                    {item('Open as email', <Mail size={14} />, () =>
                        postExport('email-draft', message),
                    )}
                    {item(
                        'Delete',
                        <Trash2 size={14} />,
                        () => void removeMessage(message.id, isUser),
                        true,
                    )}
                </div>
            )}
        </div>
    );
}

export function MessageActions({
    message,
    onEdit,
}: {
    message: ChatMessage;
    onEdit?: () => void;
}) {
    const { retryMessage, changeAttempt, sendFeedback, forkFromMessage, streaming, messages } =
        useChatStore();
    const feedbackEnabled = useBootstrapStore((state) =>
        Boolean(state.data?.features?.enable_user_feedback),
    );

    const [copied, setCopied] = useState(false);
    const isUser = message.role === 'user';
    const info = threadInfo(message);

    // Attempt controls only make sense once a thread has more than one attempt. The
    // message list is filtered to the active attempt, so the count is derived from the
    // highest attempt number seen for this thread rather than from the visible rows.
    const attemptCount = info.thread_id
        ? messages.reduce((highest, item) => {
              const other = threadInfo(item);
              return other.thread_id === info.thread_id
                  ? Math.max(highest, (other.thread_attempt ?? 0) + 1)
                  : highest;
          }, 0)
        : 0;
    const currentAttempt = (info.thread_attempt ?? 0) + 1;
    const showAttempts = attemptCount > 1;

    const copy = async () => {
        try {
            await navigator.clipboard.writeText(message.content);
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1500);
        } catch {
            /* Clipboard access can be denied; the copy simply does not happen. */
        }
    };

    return (
        <div
            className={clsx(
                'mt-1 flex items-center gap-0.5',
                isUser ? 'justify-end' : 'justify-start',
            )}
        >
            {showAttempts && (
                <div className="mr-1 flex items-center gap-0.5">
                    <IconButton
                        label="Previous attempt"
                        onClick={() => void changeAttempt(message.id, 'prev')}
                        disabled={streaming}
                    >
                        <ChevronLeft size={15} />
                    </IconButton>
                    <span className="font-mono text-[11px] text-text-3">
                        {currentAttempt}/{attemptCount}
                    </span>
                    <IconButton
                        label="Next attempt"
                        onClick={() => void changeAttempt(message.id, 'next')}
                        disabled={streaming}
                    >
                        <ChevronRight size={15} />
                    </IconButton>
                </div>
            )}

            <IconButton label={copied ? 'Copied' : 'Copy'} onClick={() => void copy()}>
                {copied ? <ClipboardCheck size={15} className="text-ok" /> : <Copy size={15} />}
            </IconButton>

            <IconButton
                label="Retry"
                onClick={() => void retryMessage(message.id)}
                disabled={streaming}
            >
                <RefreshCw size={15} />
            </IconButton>

            {!isUser && feedbackEnabled && (
                <>
                    <IconButton
                        label="Good response"
                        active={message.feedbackType === 'positive'}
                        onClick={() => void sendFeedback(message.id, 'positive')}
                    >
                        <ThumbsUp size={15} />
                    </IconButton>
                    <IconButton
                        label="Poor response"
                        active={message.feedbackType === 'negative'}
                        onClick={() => {
                            const reason =
                                window.prompt('What was wrong with this response? (optional)') ??
                                '';
                            void sendFeedback(message.id, 'negative', reason);
                        }}
                    >
                        <ThumbsDown size={15} />
                    </IconButton>
                </>
            )}

            {!isUser && (
                <IconButton
                    label="Fork conversation from here"
                    onClick={() => void forkFromMessage(message.id)}
                    disabled={streaming}
                >
                    <Split size={15} />
                </IconButton>
            )}

            <OverflowMenu message={message} onEdit={onEdit} />
        </div>
    );
}
