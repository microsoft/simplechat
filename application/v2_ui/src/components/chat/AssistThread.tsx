// AssistThread.tsx
// The conversation in an editor's Ask tab: stored turns, the exchanges this page sent, and the
// input. Shared by the diagram, chart, image and plan editors.
//
// Everything here renders as text. Turns can hold whatever a model or another participant wrote,
// so none of it reaches an HTML sink.

import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { clsx } from 'clsx';
import { Loader2, PenLine, RotateCcw, Send, X } from 'lucide-react';
import { ComposerEditor } from './ComposerEditor';
import type { AssistExchange, AssistThreadController } from '../../lib/assistThread';

/** One turn of an editor's stored chat, already worded for the reader. */
export interface AssistThreadTurn {
    key: string;
    role: 'user' | 'assistant';
    content: ReactNode;
    /** Set for a turn that shows source code rather than prose. */
    mono?: boolean;
}

export interface AssistThreadProps {
    thread: AssistThreadController;
    conversationId: string | null;
    inputId: string;
    label: string;
    labelClassName?: string;
    logLabel: string;
    assistantName: string;
    turns?: AssistThreadTurn[];
    /** Shown in the log when nothing has been said yet. */
    emptyState?: ReactNode;
    /** Shown at the top of the log, before any turn. */
    logHeader?: ReactNode;
    /** Shown at the end of the log, such as a question the assistant is waiting on. */
    logFooter?: ReactNode;
    /** What the assistant said in an exchange the server does not store. */
    renderReply?: (exchange: AssistExchange) => ReactNode;
    sendLabel: ReactNode;
    busyLabel?: ReactNode;
    sendAriaLabel?: string;
    /** The editor cannot take a request right now; typing still works. */
    busy?: boolean;
    /** The input cannot be used at all. */
    disabled?: boolean;
    hideComposer?: boolean;
    placeholder?: string;
    describedBy?: string;
    /** Shown between the input and the Send button, such as guidance the input refers to. */
    composerNote?: ReactNode;
    /**
     * Offer `#` documents and tags and the Add context control in the input.
     *
     * Off unless an editor opts in, and none does yet: an editor that turns it on must also send
     * the references with its request, and the server must authorise them.
     */
    allowContext?: boolean;
    counterHint?: string;
    density?: 'compact' | 'comfortable';
    className?: string;
    logClassName?: string;
    composerClassName?: string;
}

/** Seconds since a request started. Hidden from assistive technology so it is not read out every second. */
function ElapsedSeconds({ startedAt }: { startedAt: number }) {
    const [now, setNow] = useState(() => Date.now());
    useEffect(() => {
        const timer = window.setInterval(() => setNow(Date.now()), 1000);
        return () => window.clearInterval(timer);
    }, []);
    const seconds = Math.max(0, Math.floor((now - startedAt) / 1000));
    return <span aria-hidden="true" className="tabular-nums" data-testid="assist-elapsed">{seconds} s</span>;
}

export function AssistThread({
    thread,
    conversationId,
    inputId,
    label,
    labelClassName = 'sr-only',
    logLabel,
    assistantName,
    turns = [],
    emptyState,
    logHeader,
    logFooter,
    renderReply,
    sendLabel,
    busyLabel,
    sendAriaLabel,
    busy = false,
    disabled = false,
    hideComposer = false,
    placeholder,
    describedBy,
    composerNote,
    allowContext = false,
    counterHint,
    density = 'compact',
    className,
    logClassName,
    composerClassName,
}: AssistThreadProps) {
    const id = useId();
    const counterId = `${id}-counter`;
    const limitId = `${id}-limit`;
    const logRef = useRef<HTMLDivElement>(null);
    const { exchanges, pending } = thread;
    const inputDisabled = disabled || !thread.key;
    const canSubmit = !inputDisabled && !busy && !pending && !thread.overLimit
        && Boolean(thread.draft.text.trim());
    const submit = () => {
        if (canSubmit) {
            thread.send();
        }
    };
    const textClass = density === 'compact' ? 'text-xs' : 'text-sm';
    const nothingSaid = !turns.length && !exchanges.length && !logHeader;

    // New turns arrive at the bottom; keep them in view.
    useEffect(() => {
        const log = logRef.current;
        if (log) {
            log.scrollTop = log.scrollHeight;
        }
    }, [turns.length, exchanges.length, pending?.id]);

    const bubble = (role: 'user' | 'assistant', mono = false) => clsx(
        'max-w-[92%] rounded-xl px-3 py-2',
        textClass,
        role === 'user' ? 'self-end bg-accent-soft text-text-1' : 'self-start bg-surface-2 text-text-2',
        mono && 'font-mono text-[11px]',
    );
    const speaker = (role: 'user' | 'assistant') => (
        <p className="mb-0.5 text-[11px] font-medium text-text-3">{role === 'user' ? 'You' : assistantName}</p>
    );
    const actionClass = 'inline-flex items-center gap-1 rounded-lg px-2 py-1 text-[11px] font-medium '
        + 'text-text-2 transition-colors hover:bg-surface-1 hover:text-text-1 disabled:cursor-not-allowed disabled:opacity-50';

    const renderExchange = (exchange: AssistExchange) => (
        <li key={exchange.id} className="flex flex-col gap-2" data-testid="assist-exchange" data-status={exchange.status}>
            <div className={bubble('user')}>
                {speaker('user')}
                <p className="whitespace-pre-wrap break-words">{exchange.text}</p>
            </div>
            <div className={bubble('assistant')} aria-busy={exchange.status === 'pending' || undefined}>
                {speaker('assistant')}
                {exchange.status === 'pending' ? (
                    <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
                        <Loader2 size={12} className="animate-spin text-accent" aria-hidden="true" />
                        <span>{exchange.cancelling ? 'Cancelling…' : 'Working…'}</span>
                        <ElapsedSeconds startedAt={exchange.startedAt} />
                        <span aria-hidden="true">·</span>
                        <button
                            type="button"
                            className={actionClass}
                            disabled={exchange.cancelling}
                            onClick={() => thread.cancel(exchange.id)}
                            aria-label="Cancel this request"
                        >
                            <X size={11} aria-hidden="true" />
                            Cancel
                        </button>
                    </p>
                ) : exchange.status === 'done' ? (
                    <p className="whitespace-pre-wrap break-words">
                        {renderReply ? renderReply(exchange) : exchange.reply}
                    </p>
                ) : (
                    <>
                        {exchange.status === 'failed' ? (
                            <p role="alert" className="whitespace-pre-wrap break-words text-danger">{exchange.error}</p>
                        ) : (
                            <p className="whitespace-pre-wrap break-words text-text-3">{exchange.error}</p>
                        )}
                        <div className="mt-1.5 flex flex-wrap gap-1">
                            <button
                                type="button"
                                className={actionClass}
                                disabled={inputDisabled || busy || Boolean(pending)}
                                onClick={() => thread.retry(exchange.id)}
                            >
                                <RotateCcw size={11} aria-hidden="true" />
                                Retry
                            </button>
                            <button
                                type="button"
                                className={actionClass}
                                disabled={inputDisabled}
                                onClick={() => thread.editAndResend(exchange.id)}
                            >
                                <PenLine size={11} aria-hidden="true" />
                                Edit and resend
                            </button>
                        </div>
                    </>
                )}
            </div>
        </li>
    );

    return (
        <div className={clsx('flex min-h-0 flex-1 flex-col', className)}>
            <div
                ref={logRef}
                role="log"
                aria-live="polite"
                aria-label={logLabel}
                className={clsx('min-h-0 flex-1 overflow-y-auto overscroll-contain', logClassName)}
            >
                {logHeader}
                {nothingSaid && emptyState ? (
                    <div className={clsx('leading-relaxed text-text-3', textClass)}>{emptyState}</div>
                ) : null}
                {turns.length || exchanges.length ? (
                    <ol className="flex list-none flex-col gap-2">
                        {turns.map((turn) => (
                            <li key={turn.key} className={bubble(turn.role, turn.mono)}>
                                {speaker(turn.role)}
                                <div className="whitespace-pre-wrap break-words">{turn.content}</div>
                            </li>
                        ))}
                        {exchanges.map(renderExchange)}
                    </ol>
                ) : null}
                {logFooter}
            </div>

            {thread.notice ? (
                <div className="mt-2 flex shrink-0 items-start gap-2 rounded-lg bg-surface-2 px-3 py-2">
                    <p role="status" className="flex-1 text-xs text-text-2">{thread.notice}</p>
                    <button type="button" className="text-xs text-accent underline" onClick={thread.dismissNotice}>
                        Dismiss
                    </button>
                </div>
            ) : null}

            {!hideComposer ? (
                <form
                    className={clsx('shrink-0', composerClassName)}
                    onSubmit={(event) => {
                        event.preventDefault();
                        submit();
                    }}
                >
                    <div className={clsx(
                        'rounded-xl border bg-surface-sunken transition-colors focus-within:border-accent',
                        thread.overLimit ? 'border-danger' : 'border-edge-strong',
                        inputDisabled && 'opacity-60',
                    )}>
                        <ComposerEditor
                            id={inputId}
                            label={label}
                            labelClassName={labelClassName}
                            draft={thread.draft}
                            onChange={thread.setDraft}
                            conversationId={conversationId}
                            disabled={inputDisabled}
                            placeholder={placeholder}
                            rows={3}
                            onSubmit={submit}
                            textareaRef={thread.inputRef}
                            restricted
                            allowContext={allowContext}
                            describedBy={[describedBy, counterId, thread.overLimit ? limitId : null]
                                .filter(Boolean).join(' ')}
                            invalid={thread.overLimit}
                        />
                    </div>
                    {thread.overLimit ? (
                        <p id={limitId} className="mt-1.5 text-xs text-danger">
                            {`This is ${thread.length - thread.maxLength} character${
                                thread.length - thread.maxLength === 1 ? '' : 's'
                            } over the limit. Shorten it to send.`}
                        </p>
                    ) : null}
                    {composerNote}
                    <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
                        <span id={counterId} className={clsx('min-w-0 text-[11px] tabular-nums',
                            thread.overLimit ? 'text-danger' : 'text-text-3')}>
                            {`${thread.length}/${thread.maxLength}`}
                            {counterHint ? ` · ${counterHint}` : ''}
                        </span>
                        <button
                            type="submit"
                            disabled={!canSubmit}
                            aria-label={sendAriaLabel}
                            className="ml-auto inline-flex items-center justify-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-white transition-opacity disabled:cursor-not-allowed disabled:opacity-50"
                        >
                            <Send size={13} aria-hidden="true" />
                            {(busy || pending) && busyLabel ? busyLabel : sendLabel}
                        </button>
                    </div>
                </form>
            ) : null}
        </div>
    );
}
