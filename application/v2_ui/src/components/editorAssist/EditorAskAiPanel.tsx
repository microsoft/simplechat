// EditorAskAiPanel.tsx
// The Ask AI side panel for the agent and action editors: quick actions, the thread, and a card
// for each answer with what it changed, Jump to, its warnings, and Undo this change.
//
// Every string here can come from the model, the server or an admin's rate-limit text, so all of
// it renders as React text nodes. Nothing reaches an HTML sink and nothing is parsed as Markdown.

import { useEffect, useRef } from 'react';
import { clsx } from 'clsx';
import { AlertTriangle, Loader2, Sparkles, X } from 'lucide-react';
import { AssistThread } from '../chat/AssistThread';
import { GlassButton } from '../ui/primitives';
import { WorkflowAssistElapsed } from '../workflows/WorkflowAskAiTab';
import type { AssistExchange } from '../../lib/assistThread';
import type { EditorAssistKind } from '../../lib/editorAssist';
import type { EditorAssistTurnRecord } from '../../stores/editorAssistStore';
import { editorAssistTurnState, type EditorAssist } from './useEditorAssist';

interface QuickAction {
    readonly label: string;
    readonly text: string;
}

/** The quick actions for each editor. Each sends its text as a visible message of its own. */
export const EDITOR_ASSIST_QUICK_ACTIONS: Readonly<Record<EditorAssistKind, readonly QuickAction[]>> = {
    agent: [
        { label: 'Explain this agent', text: "Explain what this agent does and how it is set up. Don't change anything." },
        { label: 'Improve the instructions', text: 'Rewrite the instructions so they are clear, specific and well organized, without changing what the agent is for.' },
        { label: 'Suggest actions', text: 'Suggest the actions this agent should use for its purpose, and add the ones that fit.' },
        { label: 'Write a description', text: 'Write a short description of what this agent does, for people choosing an agent.' },
        { label: "Check what's missing", text: "Check what this agent still needs before it is ready to use. Don't change anything." },
    ],
    action: [
        { label: 'Explain this action', text: "Explain what this action does and how it is set up. Don't change anything." },
        { label: 'Fill in missing fields', text: "Fill in the fields this action still needs. Ask me for anything you can't work out." },
        { label: 'Improve the description', text: 'Rewrite the description so an agent knows when and how to use this action.' },
        { label: "Check what's missing", text: "Check what this action still needs before it can be saved and used. Don't change anything." },
    ],
};

const EMPTY_STATE: Readonly<Record<EditorAssistKind, string>> = {
    agent: 'Ask for a change, such as “make this agent answer in a friendly tone and give it the web search action”, or ask a question about this agent.',
    action: 'Ask for a change, such as “set this up to call our weather API with a key in the header”, or ask a question about this action.',
};

const NOUN: Readonly<Record<EditorAssistKind, string>> = { agent: 'agent', action: 'action' };

const actionClass = 'inline-flex items-center gap-1 rounded-lg px-2 py-1 text-[11px] font-medium text-accent '
    + 'transition-colors hover:bg-surface-1 disabled:cursor-not-allowed disabled:opacity-50';

function plural(count: number, one: string, many: string): string {
    return `${count} ${count === 1 ? one : many}`;
}

/** The footer button that opens the Ask AI panel. */
export function EditorAskAiToggle({ id, open, controls, onToggle }: {
    id: string;
    open: boolean;
    controls: string;
    onToggle: () => void;
}) {
    return (
        <GlassButton id={id} type="button" className="shrink-0" aria-label="Ask AI" aria-expanded={open}
            aria-controls={open ? controls : undefined} onClick={onToggle} data-editor-ask-ai-toggle>
            <Sparkles size={16} aria-hidden="true" />
            <span className="hidden sm:inline">Ask AI</span>
        </GlassButton>
    );
}

/** One answer's card: the reply, then what it did to the draft. */
function EditorAssistTurnCard({ turnId, record, assist }: {
    turnId: string;
    record: EditorAssistTurnRecord;
    assist: EditorAssist;
}) {
    const state = editorAssistTurnState(record);
    const undoRef = useRef<HTMLDivElement>(null);
    const seen = useRef(record.undoSequence);
    const locked = Boolean(assist.pending) || !assist.available;
    const reverted = new Set(record.undo?.reverted ?? []);
    const shortInstruction = record.instruction.length > 60 ? `${record.instruction.slice(0, 59).trimEnd()}…` : record.instruction;

    // Undo's result replaces the button, so focus moves to it.
    useEffect(() => {
        if (record.undoSequence === seen.current) return undefined;
        seen.current = record.undoSequence;
        const frame = requestAnimationFrame(() => undoRef.current?.focus());
        return () => cancelAnimationFrame(frame);
    }, [record.undoSequence]);

    let stateText = '';
    if (state === 'applied') stateText = `Changed ${plural(record.changes.length, 'thing', 'things')} in the draft. Review before saving.`;
    else if (state === 'partly_undone') stateText = 'Some of these changes were undone.';
    else if (state === 'undone') stateText = 'These changes were undone.';

    return (
        <div data-editor-assist-card={turnId} data-outcome={record.outcome} data-state={state} className="space-y-2">
            {record.reply ? <p className="whitespace-pre-wrap break-words" data-editor-assist-reply>{record.reply}</p> : null}
            {record.changes.length ? (
                <div className="rounded-lg border border-change-ai/40 bg-surface-1 p-2">
                    <p className="font-medium text-text-1" data-editor-assist-state>{stateText}</p>
                    <ul aria-label="Changes in this turn" className="mt-1 space-y-1">
                        {record.changes.map((change) => {
                            const undone = reverted.has(change.path);
                            return (
                                <li key={change.path} data-editor-assist-change={change.path}
                                    className="flex flex-wrap items-center justify-between gap-x-2">
                                    <span className={clsx('min-w-0 flex-1 break-words', undone && 'text-text-3 line-through')}>
                                        {change.label}
                                    </span>
                                    {change.section && !undone ? (
                                        <button type="button" className={actionClass} aria-label={`Jump to ${change.label}`}
                                            onClick={() => assist.jump(change.section ?? null)}>
                                            Jump to
                                        </button>
                                    ) : null}
                                </li>
                            );
                        })}
                    </ul>
                </div>
            ) : null}
            {record.warnings.length ? (
                <ul aria-label="Warnings" className="space-y-1">
                    {record.warnings.map((warning, index) => (
                        <li key={`${warning.code}:${index}`} data-editor-assist-warning={warning.code}
                            className="flex items-start gap-1.5 rounded-lg bg-warn-soft p-2 text-text-1">
                            <AlertTriangle size={12} aria-hidden="true" className="mt-0.5 shrink-0 text-warn" />
                            <span className="min-w-0 flex-1 break-words">{warning.message}</span>
                        </li>
                    ))}
                </ul>
            ) : null}
            {state === 'applied' ? (
                <button type="button" className={clsx(actionClass, 'px-0')} disabled={locked}
                    aria-label={`Undo this change: ${shortInstruction}`} onClick={() => assist.undo(turnId)}>
                    Undo this change
                </button>
            ) : null}
            {record.undo ? (
                <div ref={undoRef} tabIndex={-1} data-editor-assist-undo className="text-text-2 focus:outline-none">
                    <p>
                        {record.undo.skipped.length
                            ? `Undone: ${record.undo.reverted.length} reverted, ${record.undo.skipped.length} skipped because ${record.undo.skipped.length === 1 ? 'it' : 'they'} changed later.`
                            : `Undone: ${record.undo.reverted.length} reverted.`}
                    </p>
                    {record.undo.skipped.length ? (
                        <ul aria-label="Skipped" className="mt-1 list-disc space-y-0.5 pl-4">
                            {record.undo.skipped.map((label) => <li key={label} className="break-words">{label}</li>)}
                        </ul>
                    ) : null}
                </div>
            ) : null}
        </div>
    );
}

/** The Ask AI panel. Rendered beside the editor's form, never inside it: the thread has its own form. */
export function EditorAskAiPanel({ assist, id, inputId, onClose }: {
    assist: EditorAssist;
    id: string;
    inputId: string;
    onClose: () => void;
}) {
    const { thread, kind } = assist;
    const quickDisabled = assist.busy || Boolean(assist.pending);

    const renderReply = (exchange: AssistExchange) => {
        const record = assist.turns[exchange.id];
        if (!record || record.threadKey !== thread.key) {
            return <p className="whitespace-pre-wrap break-words">{exchange.reply}</p>;
        }
        return <EditorAssistTurnCard turnId={exchange.id} record={record} assist={assist} />;
    };

    return (
        <aside id={id} aria-label="Ask AI" data-editor-ask-ai={kind}
            className="flex min-h-0 w-full flex-1 flex-col border-edge bg-surface-0 xl:w-[400px] xl:flex-none xl:border-l">
            <div className="flex shrink-0 items-center gap-2 border-b border-edge px-3 py-2">
                <span className="inline-flex h-6 w-6 items-center justify-center rounded-md bg-change-ai-soft text-change-ai">
                    <Sparkles size={14} aria-hidden="true" />
                </span>
                <h2 className="flex-1 text-sm font-semibold text-text-1">Ask AI</h2>
                <button type="button" aria-label="Close Ask AI" onClick={onClose}
                    className="rounded-md p-1 text-text-3 hover:bg-surface-2 hover:text-text-1">
                    <X size={14} aria-hidden="true" />
                </button>
            </div>
            <div className="flex min-h-0 flex-1 flex-col gap-2 p-3">
                <p className="shrink-0 text-xs text-text-3">
                    {`Ask AI edits this draft only. Nothing is saved until you save the ${NOUN[kind]}, and you can undo each change.`}
                </p>
                <div role="group" aria-label="Quick actions" className="flex shrink-0 flex-wrap gap-1.5">
                    {EDITOR_ASSIST_QUICK_ACTIONS[kind].map((action) => (
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
                    placeholder="Ask for a change or a question."
                    emptyState={<p>{EMPTY_STATE[kind]}</p>}
                    composerClassName="mt-2"
                    composerNote={assist.waitSeconds > 0 ? (
                        <p className="mt-2 text-[11px] text-text-3" data-editor-assist-wait>
                            {`You can send again in ${assist.waitSeconds} s.`}
                        </p>
                    ) : null}
                />
            </div>
        </aside>
    );
}

/** The editor's notice while a turn runs: the editor is locked until the answer is in. */
export function EditorAssistLockBanner({ pending, onCancel }: {
    pending: AssistExchange;
    onCancel: () => void;
}) {
    return (
        <div data-editor-assist-lock
            className="sticky top-0 z-20 mb-3 flex flex-wrap items-center gap-2 rounded-xl border border-edge bg-surface-1 p-3 text-sm text-text-2 shadow-sm">
            <Loader2 size={14} aria-hidden="true" className="animate-spin text-accent" />
            <span className="min-w-0 flex-1">Ask AI is working. The editor is locked until it answers.</span>
            <WorkflowAssistElapsed startedAt={pending.startedAt} testId="editor-assist-lock-elapsed" />
            <GlassButton type="button" size="sm" className="h-7 px-2 text-xs" disabled={pending.cancelling} onClick={onCancel}>
                Cancel request
            </GlassButton>
        </div>
    );
}
