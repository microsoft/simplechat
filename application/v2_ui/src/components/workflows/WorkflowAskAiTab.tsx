// WorkflowAskAiTab.tsx
// The workflow editor's Ask AI tab: quick actions, the thread, and a card for each answer with
// what it changed, Jump to, the documents it read, its warnings, and Undo this change.
//
// Every string here can come from the model, the server or an admin's rate-limit text, so all of
// it renders as React text nodes. Nothing reaches an HTML sink and nothing is parsed as Markdown.

import { useEffect, useId, useRef, useState } from 'react';
import { clsx } from 'clsx';
import { AlertTriangle, Loader2, Sparkles, Target, X } from 'lucide-react';
import { AssistThread } from '../chat/AssistThread';
import { GlassButton } from '../ui/primitives';
import type { AssistExchange } from '../../lib/assistThread';
import {
    workflowAssistTurnState, type WorkflowAssistReplayState, type WorkflowAssistTurnRecord, type WorkflowAssistUndoResult,
} from '../../lib/workflowAssist';
import type { WorkflowAssist } from './useWorkflowAssist';

/** The five quick actions. Each sends its text as a visible message of its own. */
export const WORKFLOW_ASSIST_QUICK_ACTIONS: readonly { readonly label: string; readonly text: string }[] = [
    { label: 'Explain this workflow', text: "Explain what this workflow does, step by step. Don't change anything." },
    { label: 'Tighten task instructions', text: "Tighten each task's instructions so they are clear and specific, without changing what they ask for." },
    { label: 'Add a schedule', text: "Add a schedule that fits this workflow. Ask me if the timing isn't clear." },
    { label: 'Alert me only when urgent', text: 'Change the alerts so I am alerted only when something is urgent.' },
    { label: "Check what's needed to run", text: "Check what this workflow still needs before it can run, such as missing fields or connections. Don't change anything." },
];

// revertTurn's reason for a key the user changed again after the turn.
const CHANGED_LATER_REASON = 'Changed after this turn.';

const actionClass = 'inline-flex items-center gap-1 rounded-lg px-2 py-1 text-[11px] font-medium text-accent '
    + 'transition-colors hover:bg-surface-1 disabled:cursor-not-allowed disabled:opacity-50';

/** Seconds since a request started. Hidden from assistive technology so it is not read out every second. */
export function WorkflowAssistElapsed({ startedAt, testId }: { startedAt: number; testId?: string }) {
    const [now, setNow] = useState(() => Date.now());
    useEffect(() => {
        const timer = window.setInterval(() => setNow(Date.now()), 1000);
        return () => window.clearInterval(timer);
    }, []);
    const seconds = Math.max(0, Math.floor((now - startedAt) / 1000));
    return <span aria-hidden="true" className="tabular-nums" data-testid={testId}>{seconds} s</span>;
}

/** The footer button that opens the side panel on Ask AI. */
export function WorkflowAskAiToggle({ id, open, controls, onToggle }: {
    id: string;
    open: boolean;
    controls: string;
    onToggle: () => void;
}) {
    return (
        <GlassButton id={id} type="button" className="shrink-0" aria-label="Ask AI" aria-expanded={open}
            aria-controls={open ? controls : undefined} onClick={onToggle}>
            {/* Below sm an icon stands in for the label so Cancel and Save stay on one line. */}
            <Sparkles size={16} aria-hidden="true" className="sm:hidden" />
            <span className="hidden sm:inline">Ask AI</span>
        </GlassButton>
    );
}

function plural(count: number, one: string, many: string): string {
    return `${count} ${count === 1 ? one : many}`;
}

function stateText(state: WorkflowAssistReplayState, record: WorkflowAssistTurnRecord): string {
    const count = record.changes.length;
    switch (state) {
        case 'applied':
            return `Changed ${plural(count, 'thing', 'things')} in the draft. Review before saving.`;
        case 'partly_undone':
            return 'Some of these changes were undone.';
        case 'undone':
            return 'These changes were undone.';
        case 'pending':
            return 'Confirm to apply these changes.';
        case 'declined':
            return record.apply === 'rejected' && record.applyMessage
                ? `Nothing was applied: ${record.applyMessage}` : 'You chose not to apply these changes.';
        case 'earlier':
            return 'Made in an earlier editing session.';
        default:
            return '';
    }
}

function undoSummary(undo: Extract<WorkflowAssistUndoResult, { reverted: number }>): string {
    const reverted = `Undone: ${undo.reverted} reverted`;
    if (!undo.skipped) return `${reverted}.`;
    const later = undo.skippedKeys.every((item) => item.reason === CHANGED_LATER_REASON);
    return later
        ? `${reverted}, ${undo.skipped} skipped because ${undo.skipped === 1 ? 'it' : 'they'} changed later.`
        : `${reverted}, ${undo.skipped} skipped.`;
}

/** What the latest Undo did, worded for the card. Null when there is nothing to say. */
function UndoResult({ undo, state, confirming }: {
    undo: WorkflowAssistUndoResult;
    state: WorkflowAssistReplayState;
    confirming: boolean;
}) {
    if ('message' in undo) return <p>{undo.message}</p>;
    if (!('reverted' in undo)) {
        return <p>{undo.status === 'unavailable' ? 'This turn can no longer be undone.' : 'Nothing left to undo for this turn.'}</p>;
    }
    if (confirming) return <p>Confirm to undo these changes.</p>;
    if (state !== 'undone' && state !== 'partly_undone') return null;
    return (
        <>
            <p>{undoSummary(undo)}</p>
            {undo.revertedKeys.length ? (
                <ul aria-label="Reverted" className="mt-1 list-disc space-y-0.5 pl-4">
                    {undo.revertedKeys.map((item) => <li key={item.key} className="break-words">{item.label}</li>)}
                </ul>
            ) : null}
            {undo.skippedKeys.length ? (
                <ul aria-label="Skipped" className="mt-1 list-disc space-y-0.5 pl-4">
                    {undo.skippedKeys.map((item) => (
                        <li key={item.key} className="break-words">{item.reason ? `${item.label}: ${item.reason}` : item.label}</li>
                    ))}
                </ul>
            ) : null}
        </>
    );
}

/** One answer's card: the reply, then what it did to the draft. */
function WorkflowAssistTurnCard({ turnId, record, assist, reloading }: {
    turnId: string;
    record: WorkflowAssistTurnRecord;
    assist: WorkflowAssist;
    /** The saved workflow is reloading, so the draft this card would undo in is locked. */
    reloading: boolean;
}) {
    const state = workflowAssistTurnState(turnId, record, assist.historyView, assist.epoch);
    const undoRef = useRef<HTMLDivElement>(null);
    const seen = useRef({ sequence: record.undoSequence, state });
    const pendingAction = assist.historyView.pending?.action;
    const confirmingUndo = pendingAction?.origin === 'restore' && pendingAction.turnId === turnId;
    const locked = Boolean(assist.pending) || !assist.available || reloading;
    const jumpable = state === 'applied' || state === 'partly_undone';
    const undoable = state === 'applied' || state === 'earlier';
    const shortInstruction = record.instruction.length > 60 ? `${record.instruction.slice(0, 59).trimEnd()}…` : record.instruction;

    // Undo's result replaces the button, so focus moves to it; so does a confirmed undo, whose
    // confirmation dialog hands focus back to a button that is gone.
    useEffect(() => {
        const before = seen.current;
        seen.current = { sequence: record.undoSequence, state };
        const pressed = record.undoSequence !== before.sequence && record.undo?.status !== 'confirmation_required';
        const confirmed = record.undo?.status === 'confirmation_required' && before.state !== state
            && (state === 'undone' || state === 'partly_undone');
        if (!pressed && !confirmed) return undefined;
        const frame = requestAnimationFrame(() => {
            const active = document.activeElement;
            if (confirmed && active && active !== document.body) return;
            undoRef.current?.focus();
        });
        return () => cancelAnimationFrame(frame);
    }, [record.undoSequence, record.undo, state]);

    const text = record.outcome === 'changed' ? stateText(state, record) : '';
    return (
        <div data-workflow-assist-card={turnId} data-outcome={record.outcome} data-state={state} className="space-y-2">
            {record.outcome === 'question' ? (
                <p className="text-[11px] font-semibold uppercase tracking-wide text-text-3">Question</p>
            ) : null}
            {record.reply ? <p className="whitespace-pre-wrap break-words" data-workflow-assist-reply>{record.reply}</p> : null}
            {record.outcome === 'changed' && record.changes.length ? (
                <div className="rounded-lg border border-change-ai/40 bg-surface-1 p-2">
                    <p className="font-medium text-text-1" data-workflow-assist-state>{text}</p>
                    <ul aria-label="Changes in this turn" className="mt-1 space-y-1">
                        {record.changes.map((item) => (
                            <li key={item.key} data-workflow-assist-change={item.key}
                                className="flex flex-wrap items-center justify-between gap-x-2">
                                <span className="min-w-0 flex-1 break-words">{item.summary}</span>
                                {jumpable ? (
                                    <button type="button" className={actionClass} aria-label={`Jump to ${item.summary}`}
                                        onClick={() => assist.jump({
                                            key: item.key, focusKey: item.change.target.focusKey, nodeId: item.change.target.nodeId,
                                        })}>
                                        Jump to
                                    </button>
                                ) : null}
                            </li>
                        ))}
                    </ul>
                </div>
            ) : null}
            {record.contextDocuments.length ? (
                <p className="break-words text-text-3" data-workflow-assist-context>
                    {`Read as context: ${record.contextDocuments.join(', ')}`}
                </p>
            ) : null}
            {record.warnings.length ? (
                <ul aria-label="Warnings" className="space-y-1">
                    {record.warnings.map((warning, index) => (
                        <li key={`${warning.code}:${index}`} data-workflow-assist-warning={warning.code}
                            className="flex flex-wrap items-start gap-1.5 rounded-lg bg-warn-soft p-2 text-text-1">
                            <AlertTriangle size={12} aria-hidden="true" className="mt-0.5 shrink-0 text-warn" />
                            <span className="min-w-0 flex-1 break-words">{warning.message}</span>
                            {warning.focusKey && state !== 'earlier' ? (
                                <button type="button" className={actionClass} aria-label={`Jump to: ${warning.message}`}
                                    onClick={() => assist.jump({ key: warning.focusKey ?? '', focusKey: warning.focusKey ?? '', nodeId: warning.nodeId })}>
                                    Jump to
                                </button>
                            ) : null}
                        </li>
                    ))}
                </ul>
            ) : null}
            {undoable ? (
                <button type="button" className={clsx(actionClass, 'px-0')} disabled={locked}
                    aria-label={`Undo this change: ${shortInstruction}`} onClick={() => assist.undo(turnId)}>
                    Undo this change
                </button>
            ) : null}
            {record.undo ? (
                <div ref={undoRef} tabIndex={-1} data-workflow-assist-undo={record.undo.status} className="text-text-2 focus:outline-none">
                    <UndoResult undo={record.undo} state={state} confirming={confirmingUndo} />
                </div>
            ) : null}
        </div>
    );
}

export function WorkflowAskAiTab({ assist, inputId, onReload }: {
    assist: WorkflowAssist;
    inputId: string;
    /** Reload the saved workflow, discarding the draft. Offered after the workflow changed elsewhere. */
    onReload?: () => Promise<void>;
}) {
    const baseId = useId();
    const focusId = `${baseId}-focus`;
    const reloadButtonId = `${baseId}-reload`;
    const keepEditingId = `${baseId}-keep`;
    const [reloadStep, setReloadStep] = useState<'idle' | 'confirm' | 'loading'>('idle');
    const [reloadFailed, setReloadFailed] = useState(false);
    const { thread, focus } = assist;
    const quickDisabled = assist.busy || Boolean(assist.pending);

    const focusById = (id: string) => requestAnimationFrame(() => document.getElementById(id)?.focus());
    const reload = async () => {
        if (!onReload) return;
        setReloadStep('loading');
        setReloadFailed(false);
        try {
            await onReload();
        } catch {
            setReloadFailed(true);
            setReloadStep('idle');
            focusById(reloadButtonId);
        }
    };

    const renderReply = (exchange: AssistExchange) => {
        const record = assist.turns[exchange.id];
        if (!record || record.threadKey !== thread.key) {
            return <p className="whitespace-pre-wrap break-words">{exchange.reply}</p>;
        }
        return <WorkflowAssistTurnCard turnId={exchange.id} record={record} assist={assist} reloading={reloadStep === 'loading'} />;
    };

    return (
        <div className="flex min-h-0 flex-1 flex-col gap-2 p-3" data-workflow-ask-ai>
            <p className="shrink-0 text-xs text-text-3">
                Ask AI edits this draft only. Nothing is saved until you save the workflow, and you can undo each change.
            </p>
            {assist.reloadOffered && onReload ? (
                <div role="group" aria-label="Reload workflow" data-workflow-assist-reload
                    className="shrink-0 space-y-2 rounded-lg bg-warn-soft p-2 text-xs text-text-1">
                    <p>
                        {reloadStep === 'confirm'
                            ? 'Reloading discards your unsaved changes to this workflow.'
                            : 'The saved workflow changed after you opened it. Reload it to keep using Ask AI.'}
                    </p>
                    <div className="flex flex-wrap gap-2">
                        {reloadStep === 'confirm' ? <>
                            <GlassButton type="button" size="sm" variant="danger" className="h-7 px-2 text-xs"
                                onClick={() => void reload()}>
                                Discard and reload
                            </GlassButton>
                            <GlassButton id={keepEditingId} type="button" size="sm" className="h-7 px-2 text-xs"
                                onClick={() => {
                                    setReloadStep('idle');
                                    focusById(reloadButtonId);
                                }}>
                                Keep editing
                            </GlassButton>
                        </> : (
                            <GlassButton id={reloadButtonId} type="button" size="sm" className="h-7 px-2 text-xs"
                                disabled={reloadStep === 'loading'}
                                onClick={() => {
                                    setReloadStep('confirm');
                                    focusById(keepEditingId);
                                }}>
                                {reloadStep === 'loading' ? 'Reloading…' : 'Reload workflow'}
                            </GlassButton>
                        )}
                    </div>
                    {reloadFailed ? <p role="alert" className="text-danger">Couldn&apos;t reload the workflow. Try again.</p> : null}
                </div>
            ) : null}
            <div role="group" aria-label="Quick actions" className="flex shrink-0 flex-wrap gap-1.5">
                {WORKFLOW_ASSIST_QUICK_ACTIONS.map((action) => (
                    <button key={action.label} type="button" disabled={quickDisabled}
                        onClick={() => assist.quickAction(action.text)}
                        className="rounded-full border border-edge px-2.5 py-1 text-[11px] font-medium text-text-2 transition-colors hover:bg-surface-2 hover:text-text-1 disabled:cursor-not-allowed disabled:opacity-50">
                        {action.label}
                    </button>
                ))}
            </div>
            <AssistThread
                thread={thread}
                conversationId={null}
                inputId={inputId}
                label="Message Ask AI"
                logLabel="Ask AI conversation"
                assistantName="Ask AI"
                renderReply={renderReply}
                cancelledMessage="Cancelled. Nothing was changed."
                sendLabel="Send"
                sendAriaLabel="Send to Ask AI"
                busy={assist.busy}
                placeholder="Ask for a change or a question. Type # for a document."
                describedBy={focus ? focusId : undefined}
                allowContext
                contextDocumentsOnly
                emptyState={(
                    <p>
                        Ask for a change, such as “run this at 7 AM on weekdays and only alert me when something is urgent”,
                        or ask a question about this workflow. Type # to use one of your documents.
                    </p>
                )}
                composerClassName="mt-2"
                composerNote={<>
                    {focus ? (
                        <div className="mt-2 flex items-center gap-1" data-workflow-assist-focus={focus.taskId}>
                            <span id={focusId} className="inline-flex min-w-0 items-center gap-1 rounded-md border border-accent/40 bg-accent-soft px-2 py-0.5 text-[11px] text-text-1">
                                <Target size={11} aria-hidden="true" className="shrink-0" />
                                <span className="truncate">{`About: ${focus.label}`}</span>
                            </span>
                            <button type="button" aria-label={`Stop asking about ${focus.label}`}
                                className="rounded-md p-1 text-text-3 hover:bg-surface-2 hover:text-text-1"
                                onClick={() => {
                                    assist.setFocusTask(null);
                                    thread.focusInput();
                                }}>
                                <X size={11} aria-hidden="true" />
                            </button>
                        </div>
                    ) : null}
                    {assist.waitSeconds > 0 ? (
                        <p className="mt-2 text-[11px] text-text-3" data-workflow-assist-wait>
                            {`You can send again in ${assist.waitSeconds} s.`}
                        </p>
                    ) : null}
                </>}
            />
        </div>
    );
}

/** The editor pane's notice while a turn runs: the editor is locked until the answer is in. */
export function WorkflowAssistLockBanner({ pending, onCancel }: {
    pending: AssistExchange;
    onCancel: () => void;
}) {
    return (
        <div data-workflow-assist-lock
            className="sticky top-0 z-20 mb-3 flex flex-wrap items-center gap-2 rounded-xl border border-edge bg-surface-1 p-3 text-sm text-text-2 shadow-sm">
            <Loader2 size={14} aria-hidden="true" className="animate-spin text-accent" />
            <span className="min-w-0 flex-1">Ask AI is working. The editor is locked until it answers.</span>
            <WorkflowAssistElapsed startedAt={pending.startedAt} testId="workflow-assist-lock-elapsed" />
            <GlassButton type="button" size="sm" className="h-7 px-2 text-xs" disabled={pending.cancelling} onClick={onCancel}>
                Cancel request
            </GlassButton>
        </div>
    );
}
