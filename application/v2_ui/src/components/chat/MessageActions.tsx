// MessageActions.tsx
// Per-message action row, differing by role.
//
// User messages can be edited; assistant messages can be rated and forked. Both can be
// copied, retried, deleted, exported and reused as a prompt. Attempt navigation appears
// only once more than one attempt exists.

import { useEffect, useRef, useState } from 'react';
import { clsx } from 'clsx';
import {
    BookOpen,
    Brain,
    ChevronLeft,
    ChevronRight,
    Clipboard,
    ClipboardCheck,
    Copy,
    Ellipsis,
    Eye,
    EyeOff,
    FileDown,
    Info,
    Loader2,
    Mail,
    Pencil,
    RefreshCw,
    Split,
    ThumbsDown,
    ThumbsUp,
    Trash2,
    Volume2,
    VolumeX,
} from 'lucide-react';
import { useChatStore } from '../../stores/chatStore';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import { toast } from '../../stores/toastStore';
import { ApiError } from '../../lib/apiClient';
import { attemptState } from '../../lib/threads';
import { readSources } from '../../lib/messageDetails';
import { canMask, readMaskState } from '../../lib/masking';
import type { InspectorSection } from './MessageInspector';
import type { ChatMessage, Json } from '../../lib/types';
import {
    downloadMessageExport,
    emailDraftMailtoUrl,
    fetchMessageEmailDraft,
    saveEmailDraftAttachments,
    type MessageExportFormat,
} from '../../lib/endpoints';
import { synthesizeSpeech } from '../../lib/voice';

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

/** Play a message aloud via the speech endpoint. */
function SpeakButton({ message }: { message: ChatMessage }) {
    const [state, setState] = useState<'idle' | 'loading' | 'playing'>('idle');
    const audioRef = useRef<HTMLAudioElement | null>(null);
    const urlRef = useRef<string | null>(null);

    // Release the object URL and stop playback if the message unmounts mid-play.
    useEffect(
        () => () => {
            audioRef.current?.pause();
            if (urlRef.current) {
                URL.revokeObjectURL(urlRef.current);
            }
        },
        [],
    );

    const toggle = async () => {
        if (state === 'playing') {
            audioRef.current?.pause();
            setState('idle');
            return;
        }

        setState('loading');
        try {
            const url = await synthesizeSpeech(message.content);
            urlRef.current = url;
            const audio = new Audio(url);
            audioRef.current = audio;
            audio.onended = () => setState('idle');
            audio.onerror = () => setState('idle');
            await audio.play();
            setState('playing');
        } catch {
            // Speech is optional; a failure leaves the control back at rest rather than
            // interrupting the conversation.
            setState('idle');
        }
    };

    return (
        <IconButton
            label={state === 'playing' ? 'Stop reading' : 'Read aloud'}
            onClick={() => void toggle()}
            active={state === 'playing'}
            disabled={state === 'loading'}
        >
            {state === 'loading' ? (
                <Loader2 size={15} className="animate-spin" />
            ) : state === 'playing' ? (
                <VolumeX size={15} />
            ) : (
                <Volume2 size={15} />
            )}
        </IconButton>
    );
}

/**
 * Run a server-rendered export, reporting the outcome.
 *
 * Word and PowerPoint stream a file. Email is not a download at all: it returns a JSON
 * draft, whose images are saved separately because a `mailto:` URL cannot carry
 * attachments, before the mail client is opened.
 */
async function runExport(format: MessageExportFormat, message: ChatMessage) {
    const body = {
        message_id: message.id,
        conversation_id: message.conversation_id,
    };

    try {
        if (format === 'email-draft') {
            const draft = await fetchMessageEmailDraft(body);
            const saved = saveEmailDraftAttachments(draft.attachments);
            window.location.href = emailDraftMailtoUrl(draft);
            toast.success(
                saved > 0
                    ? `Email draft opened. ${saved} image${saved === 1 ? '' : 's'} downloaded to attach.`
                    : 'Email draft opened.',
            );
            return;
        }

        await downloadMessageExport(format, body);
        toast.success(format === 'word' ? 'Exported as a Word document.' : 'Exported as a PowerPoint.');
    } catch (error) {
        const label =
            format === 'word' ? 'Word' : format === 'powerpoint' ? 'PowerPoint' : 'email';
        toast.error(
            error instanceof ApiError && error.message
                ? `${label} export failed: ${error.message}`
                : `${label} export failed.`,
        );
    }
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
                        void runExport('word', message),
                    )}
                    {item('Export to PowerPoint', <FileDown size={14} />, () =>
                        void runExport('powerpoint', message),
                    )}
                    {item('Open as email', <Mail size={14} />, () =>
                        void runExport('email-draft', message),
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
    inspector,
    onInspect,
}: {
    message: ChatMessage;
    onEdit?: () => void;
    /** Section currently open below the message, or null when the panel is closed. */
    inspector?: InspectorSection | null;
    onInspect?: (section: InspectorSection | null) => void;
}) {
    const { retryMessage, changeAttempt, sendFeedback, forkFromMessage, streaming, attemptsByThread, applyMask } =
        useChatStore();
    const feedbackEnabled = useBootstrapStore((state) =>
        Boolean(state.data?.features?.enable_user_feedback),
    );
    const ttsEnabled = useBootstrapStore((state) =>
        Boolean(state.data?.features?.enable_text_to_speech),
    );
    const currentUserId = useBootstrapStore((state) => state.data?.user?.id);

    const [copied, setCopied] = useState(false);
    const isUser = message.role === 'user';
    const attempts = attemptState(message, attemptsByThread);
    const sources = readSources(message as unknown as Json);
    const masks = readMaskState(message);
    const maskingAllowed = canMask(message, currentUserId);

    const copy = async () => {
        try {
            await navigator.clipboard.writeText(message.content);
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1500);
        } catch {
            /* Clipboard access can be denied; the copy simply does not happen. */
        }
    };

    /** Toggle a section, closing the panel when the open one is clicked again. */
    const inspect = (section: InspectorSection) =>
        onInspect?.(inspector === section ? null : section);

    return (
        <div
            className={clsx(
                // Groups are separated by a wider gap than the buttons within them, so the
                // row reads as related sets rather than one long undifferentiated strip.
                'mt-1 flex items-center gap-3',
                isUser ? 'justify-end' : 'justify-start',
            )}
        >
            {attempts.show && (
                <div className="flex items-center gap-0.5">
                    <IconButton
                        label="Previous attempt"
                        onClick={() => void changeAttempt(message.id, 'prev')}
                        disabled={streaming}
                    >
                        <ChevronLeft size={15} />
                    </IconButton>
                    <span
                        className="font-mono text-[11px] text-text-3"
                        title={
                            attempts.total === null
                                ? 'Use the arrows to move between attempts'
                                : `Attempt ${attempts.current} of ${attempts.total}`
                        }
                    >
                        {attempts.total === null
                            ? attempts.current
                            : `${attempts.current}/${attempts.total}`}
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

            {/* Working with the message itself. */}
            <div className="flex items-center gap-0.5">
                <IconButton label={copied ? 'Copied' : 'Copy'} onClick={() => void copy()}>
                    {copied ? (
                        <ClipboardCheck size={15} className="text-ok" />
                    ) : (
                        <Copy size={15} />
                    )}
                </IconButton>

                <IconButton
                    label="Retry"
                    onClick={() => void retryMessage(message.id)}
                    disabled={streaming}
                >
                    <RefreshCw size={15} />
                </IconButton>

                {!isUser && ttsEnabled && <SpeakButton message={message} />}
            </div>

            {!isUser && feedbackEnabled && (
                <div className="flex items-center gap-0.5">
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
                </div>
            )}

            {/* Looking into how the message was produced. */}
            {onInspect && (
                <div className="flex items-center gap-0.5">
                    {!isUser && (
                        <IconButton
                            label={
                                sources.total > 0
                                    ? `Show sources (${sources.total})`
                                    : 'Show sources'
                            }
                            active={inspector === 'sources'}
                            onClick={() => inspect('sources')}
                        >
                            <BookOpen size={15} />
                        </IconButton>
                    )}
                    {!isUser && (
                        <IconButton
                            label="Show reasoning"
                            active={inspector === 'reasoning'}
                            onClick={() => inspect('reasoning')}
                        >
                            <Brain size={15} />
                        </IconButton>
                    )}
                    <IconButton
                        label="Message details"
                        active={inspector === 'details'}
                        onClick={() => inspect('details')}
                    >
                        <Info size={15} />
                    </IconButton>
                </div>
            )}

            {/* Masking, when the user may change it. */}
            {onInspect && maskingAllowed && (
                <div className="flex items-center gap-0.5">
                    {!masks.hasAnyMask && (
                        <IconButton
                            label="Mask this message"
                            onClick={() => void applyMask(message.id, 'mask_all')}
                        >
                            <EyeOff size={15} />
                        </IconButton>
                    )}
                    {masks.hasAnyMask && (
                        <IconButton
                            label={
                                masks.fullyMasked
                                    ? 'Remove the mask from this message'
                                    : 'Clear all masks on this message'
                            }
                            active
                            onClick={() =>
                                void applyMask(
                                    message.id,
                                    masks.fullyMasked ? 'unmask_message' : 'clear_all_masks',
                                )
                            }
                        >
                            <Eye size={15} />
                        </IconButton>
                    )}
                </div>
            )}

            {/* Branching and everything else. */}
            <div className="flex items-center gap-0.5">
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
        </div>
    );
}
