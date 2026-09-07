// OrchestrationPlanEditor.tsx

import { useEffect, useId, useMemo, useRef } from 'react';
import { createPortal } from 'react-dom';
import { clsx } from 'clsx';
import { Check, History, Loader2, RotateCcw, Send, Sparkles, X } from 'lucide-react';
import { GlassButton, GlassPanel } from '../ui/primitives';
import { ElicitationForm } from './ElicitationCard';
import { OrchestrationRunView } from './OrchestrationRunView';
import { useChatStore } from '../../stores/chatStore';
import {
    selectCanEditPlan,
    selectEdits,
    selectPlan,
    selectPlanEditor,
    selectPlanRunBlocked,
    useOrchestrationStore,
    type PlanEditorTarget,
} from '../../stores/orchestrationStore';
import { applyPlanEdits, isPlanRunnable } from '../../lib/orchestrationPlan';
import { MAX_PLAN_INSTRUCTION_LENGTH } from '../../lib/orchestration';
import {
    approveAndRunPlan,
    loadPlanEditorHistory,
    openOrchestrationPlanEditor,
    previewPlanEditorRevision,
    refreshOrchestrationPlanEditor,
    submitPlanRevision,
} from '../../lib/orchestrationController';

const originLabels = { original: 'Original plan', ai: 'Planner revision', restore: 'Restored plan' };

function timestampLabel(value: string): string {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? '' : date.toLocaleString();
}

/** Mounted by ChatPage, never by a message/card that streaming can replace. */
export function OrchestrationPlanEditorHost() {
    const target = useOrchestrationStore((state) => state.editorTarget);
    const visibleConversationId = useOrchestrationStore((state) => state.visibleConversationId);
    const activeConversationId = useChatStore((state) => state.activeConversationId);
    if (!target || target.conversationId !== visibleConversationId
        || target.conversationId !== activeConversationId) {
        return null;
    }
    return <OrchestrationPlanEditor key={`${target.conversationId}:${target.turnId}`} {...target} />;
}

function OrchestrationPlanEditor({ conversationId, turnId }: PlanEditorTarget) {
    const session = useOrchestrationStore((state) => selectPlanEditor(state, conversationId, turnId));
    const plan = useOrchestrationStore((state) => selectPlan(state, conversationId, turnId));
    const edits = useOrchestrationStore((state) => selectEdits(state, conversationId, turnId));
    const canEdit = useOrchestrationStore((state) => selectCanEditPlan(state, conversationId, turnId));
    const runBlocked = useOrchestrationStore((state) => selectPlanRunBlocked(state, conversationId, turnId));
    const dialogRef = useRef<HTMLDivElement>(null);
    const closeRef = useRef<HTMLButtonElement>(null);
    const id = useId();
    const target = useMemo(() => ({ conversationId, turnId }), [conversationId, turnId]);
    const currentPreview = useMemo(() => plan ? applyPlanEdits(plan, edits) : null, [plan, edits]);
    const close = () => useOrchestrationStore.getState().setEditorTarget(null);

    useEffect(() => {
        const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
        const oldOverflow = document.body.style.overflow;
        document.body.style.overflow = 'hidden';
        closeRef.current?.focus();
        const keyDown = (event: KeyboardEvent) => {
            if (event.defaultPrevented) {
                return;
            }
            if (event.key === 'Escape') {
                event.preventDefault();
                event.stopPropagation();
                useOrchestrationStore.getState().setEditorTarget(null);
            } else if (event.key === 'Tab') {
                const focusable = Array.from(dialogRef.current?.querySelectorAll<HTMLElement>(
                    'button:not([disabled]), a[href], input:not([disabled]), textarea:not([disabled]), '
                    + 'select:not([disabled]), [tabindex]:not([tabindex="-1"]), [contenteditable="true"]',
                ) ?? []).filter((element) => element.tabIndex >= 0 && element.getClientRects().length > 0);
                const first = focusable[0];
                const last = focusable[focusable.length - 1];
                const inside = dialogRef.current?.contains(document.activeElement);
                if (!inside || (event.shiftKey && document.activeElement === first)
                    || (!event.shiftKey && document.activeElement === last)) {
                    event.preventDefault();
                    (event.shiftKey ? last : first)?.focus();
                }
            }
        };
        document.addEventListener('keydown', keyDown);
        return () => {
            document.removeEventListener('keydown', keyDown);
            document.body.style.overflow = oldOverflow;
            if (previous?.isConnected && useChatStore.getState().activeConversationId === conversationId) {
                previous.focus();
            }
        };
    }, [conversationId, turnId]);

    if (!session || !plan || !currentPreview) {
        return null;
    }
    const editor = session.state;
    const pending = editor?.pending;
    const busy = session.loading || session.submitting || Boolean(editor?.busy);
    const canRequest = canEdit && Boolean(editor) && !busy && !session.blocked;
    const preview = session.previewRunId ? session.previewPlan : currentPreview;
    const canRun = canEdit && !runBlocked && isPlanRunnable(currentPreview);
    const setTab = (tab: 'ask' | 'history') =>
        useOrchestrationStore.getState().updatePlanEditor(conversationId, turnId,
            (current) => ({
                ...current, tab,
                ...(tab === 'ask' ? { previewRunId: null, previewPlan: null, previewLoading: false } : {}),
            }));
    const ask = () => {
        if (canRequest && !pending && session.instruction.trim()) {
            void submitPlanRevision(target, { action: 'ask', instruction: session.instruction });
        }
    };
    const cancelChange = () => void submitPlanRevision(target, {
        action: 'discard',
        ...(pending ? {
            elicitation_id: pending.elicitation_id,
            elicitation_revision: pending.revision ?? 0,
        } : {}),
    });
    const retryLoad = () => {
        if (editor) {
            void refreshOrchestrationPlanEditor(target);
        } else {
            void openOrchestrationPlanEditor(target);
        }
    };

    return createPortal(
        <div
            ref={dialogRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby={`${id}-title`}
            aria-describedby={`${id}-hold`}
            className="fixed inset-0 z-[70] flex items-center justify-center bg-black/60 p-0 sm:p-4"
            onClick={(event) => { if (event.target === event.currentTarget) close(); }}
        >
            <GlassPanel
                elevation="modal"
                edge
                className="relative flex h-full w-full max-w-[1600px] flex-col overflow-hidden"
            >
                <header className="flex shrink-0 items-center gap-2 border-b border-edge px-3 py-3 sm:px-5">
                    <div className="min-w-0 flex-1">
                        <h2 id={`${id}-title`} className="text-sm font-semibold text-text-1">Edit orchestration plan</h2>
                        <p className="text-xs text-text-3">Saved revision {plan.revision}</p>
                    </div>
                    <GlassButton
                        size="sm"
                        variant="primary"
                        disabled={!canRun}
                        onClick={() => void approveAndRunPlan(target)}
                        aria-label="Run saved revision"
                    >
                        <Check size={14} aria-hidden="true" />
                        Run
                    </GlassButton>
                    <button
                        ref={closeRef}
                        type="button"
                        aria-label="Close the plan editor"
                        onClick={close}
                        className="shrink-0 rounded-lg p-2 text-text-3 hover:bg-surface-2 hover:text-text-1"
                    >
                        <X size={18} aria-hidden="true" />
                    </button>
                </header>
                <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-edge px-3 py-2 sm:px-5">
                    <p id={`${id}-hold`} role="status" className="min-w-0 flex-1 text-xs text-text-3">
                        {session.loading ? 'Saving the manual-approval hold…'
                            : !editor ? 'Approval is paused in this tab. The server hold is not yet confirmed.'
                            : 'Manual approval required. Closing this editor never runs the plan.'}
                    </p>
                    {busy ? <Loader2 size={14} className="animate-spin text-accent" aria-hidden="true" /> : null}
                    {editor && (pending || editor.busy || session.submitting
                        || session.cancellationStatus !== 'idle') ? (
                        <GlassButton size="sm" variant="ghost"
                            disabled={!canEdit || session.loading || session.cancellationStatus === 'cancelling'}
                            onClick={cancelChange}
                            aria-label="Cancel change">
                            <X size={13} aria-hidden="true" />
                            {session.cancellationStatus === 'cancelling' ? 'Cancelling…'
                                : session.cancellationStatus === 'failed' ? 'Retry cancel change' : 'Cancel change'}
                        </GlassButton>
                    ) : null}
                    {!session.loading && !session.submitting ? (
                        <GlassButton size="sm" variant="ghost" onClick={retryLoad}
                            aria-label={editor ? 'Refresh saved plan' : 'Retry saving manual hold'}>
                            <RotateCcw size={13} aria-hidden="true" />
                            {editor ? 'Refresh' : 'Retry'}
                        </GlassButton>
                    ) : null}
                </div>
                {session.error ? (
                    <p role="alert" className="alert shrink-0 border-b border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger sm:px-5">
                        {session.error}
                    </p>
                ) : null}
                {!canEdit ? (
                    <p role="status" className="shrink-0 px-3 py-2 text-sm text-text-3">
                        This plan is no longer pending and cannot be edited or run here.
                    </p>
                ) : null}

                <div className="grid min-h-0 flex-1 grid-rows-[minmax(0,2fr)_minmax(0,3fr)] md:grid-cols-[minmax(0,3fr)_minmax(20rem,2fr)] md:grid-rows-1">
                    <section aria-label="Plan preview" data-testid="plan-editor-preview"
                        className="flex min-h-0 min-w-0 flex-col border-b border-edge md:border-r md:border-b-0">
                        <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-edge px-3 py-2">
                            <h3 className="min-w-0 flex-1 text-xs font-semibold text-text-2">
                                {session.previewRunId
                                    ? `History preview${preview ? ` — revision ${preview.revision}` : ''}`
                                    : 'Current saved plan'}
                            </h3>
                            {session.previewRunId ? (
                                <GlassButton size="sm" variant="subtle"
                                    onClick={() => void previewPlanEditorRevision(target, plan.run_id)}>
                                    Back to current plan
                                </GlassButton>
                            ) : null}
                        </div>
                        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
                            {session.previewLoading ? <p role="status" className="p-3 text-sm text-text-3">Loading revision…</p>
                                : preview ? (
                                    <>
                                        <OrchestrationRunView conversationId={conversationId} turnId={turnId} previewPlan={preview} />
                                        {preview.validation.repairs.length ? (
                                            <div className="m-3 rounded-xl bg-warn-soft p-3 text-xs text-warn">
                                                <p className="font-medium">Planner adjustments</p>
                                                <ul className="mt-1 list-disc pl-4">
                                                    {preview.validation.repairs.map((repair, index) => <li key={index}>{repair}</li>)}
                                                </ul>
                                            </div>
                                        ) : null}
                                    </>
                                ) : <p className="p-3 text-sm text-text-3">Preview unavailable. Your current plan is unchanged.</p>}
                        </div>
                    </section>
                    <aside aria-label="Plan editing" className="flex min-h-0 min-w-0 flex-col">
                        <div role="tablist" aria-label="Plan editor tools" className="flex shrink-0 gap-1 border-b border-edge p-2">
                            {(['ask', 'history'] as const).map((tab) => (
                                <button
                                    key={tab}
                                    id={`${id}-${tab}-tab`}
                                    type="button"
                                    role="tab"
                                    aria-controls={`${id}-${tab}-panel`}
                                    aria-selected={session.tab === tab}
                                    tabIndex={session.tab === tab ? 0 : -1}
                                    onClick={() => setTab(tab)}
                                    onKeyDown={(event) => {
                                        if (event.key === 'ArrowLeft' || event.key === 'ArrowRight'
                                            || event.key === 'Home' || event.key === 'End') {
                                            event.preventDefault();
                                            const next = event.key === 'Home' ? 'ask' : event.key === 'End'
                                                ? 'history' : tab === 'ask' ? 'history' : 'ask';
                                            setTab(next);
                                            document.getElementById(`${id}-${next}-tab`)?.focus();
                                        }
                                    }}
                                    className={clsx('flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm',
                                        session.tab === tab ? 'bg-accent-soft font-medium text-accent'
                                            : 'text-text-3 hover:bg-surface-2 hover:text-text-1')}
                                >
                                    {tab === 'ask' ? <Sparkles size={14} aria-hidden="true" /> : <History size={14} aria-hidden="true" />}
                                    {tab === 'ask' ? 'Ask planner' : 'History'}
                                </button>
                            ))}
                        </div>
                        <div role="tabpanel" id={`${id}-${session.tab}-panel`}
                            aria-labelledby={`${id}-${session.tab}-tab`}
                            className="flex min-h-0 flex-1 flex-col">
                            {session.tab === 'ask' ? (
                                <>
                                    <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-3" role="log" aria-label="Planner conversation">
                                        {!editor?.chat.length ? (
                                            <p className="text-sm text-text-3">
                                                Ask to add, remove, or rework steps. The planner checks available capabilities before saving a revision.
                                                This conversation stays in the editor.
                                            </p>
                                        ) : (
                                            <ol className="space-y-3">
                                                {editor.chat.map((entry, index) => (
                                                    <li key={`${entry.timestamp}:${index}`} className={clsx(
                                                        'rounded-xl p-3 text-sm',
                                                        entry.role === 'user' ? 'bg-accent-soft text-text-1' : 'bg-surface-2 text-text-2',
                                                    )}>
                                                        <p className="mb-1 text-xs font-medium text-text-3">{entry.role === 'user' ? 'You' : 'Planner'}</p>
                                                        <p className="whitespace-pre-wrap break-words">{entry.content}</p>
                                                    </li>
                                                ))}
                                            </ol>
                                        )}
                                        {session.submitting || editor?.busy ? (
                                            <p role="status" className="mt-3 flex items-center gap-2 text-sm text-text-3">
                                                <Loader2 size={14} className="animate-spin" aria-hidden="true" />
                                                {session.cancellationStatus === 'cancelling' ? 'Cancelling the pending change…'
                                                    : session.submitting ? 'Planner is working…'
                                                    : 'An edit is in progress. Refresh for its result or cancel the change to keep the saved plan.'}
                                            </p>
                                        ) : null}
                                        {pending && session.pendingDraft ? (
                                            <ElicitationForm
                                                conversationId={conversationId}
                                                elicitation={pending}
                                                draft={{
                                                    ...session.pendingDraft,
                                                    submitting: busy || !canEdit || session.blocked,
                                                }}
                                                ariaLabel="Planner edit questions"
                                                cancelLabel="Cancel edit request and keep current plan"
                                                onDraftChange={(update) => useOrchestrationStore.getState().updatePlanEditor(
                                                    conversationId, turnId, (current) =>
                                                        current.pendingDraft?.elicitationId === pending.elicitation_id
                                                        && current.pendingDraft.revision === (pending.revision ?? 0)
                                                            ? { ...current, pendingDraft: update(current.pendingDraft) } : current,
                                                )}
                                                onAnswer={(response, context) => void submitPlanRevision(target, {
                                                    action: 'answer',
                                                    elicitation_id: pending.elicitation_id,
                                                    elicitation_revision: pending.revision ?? 0,
                                                    elicitation_response: response,
                                                    ...(context ? { elicitation_context: context } : {}),
                                                })}
                                                onCancel={cancelChange}
                                            />
                                        ) : null}
                                    </div>
                                    {!pending ? (
                                        <form className="shrink-0 border-t border-edge p-3" onSubmit={(event) => { event.preventDefault(); ask(); }}>
                                            <label htmlFor={`${id}-instruction`} className="mb-1 block text-xs font-medium text-text-2">Ask planner</label>
                                            <textarea
                                                id={`${id}-instruction`}
                                                value={session.instruction}
                                                rows={3}
                                                maxLength={MAX_PLAN_INSTRUCTION_LENGTH}
                                                placeholder="For example: add a web search, then focus the comparison on pricing."
                                                className="w-full resize-none rounded-xl border border-edge bg-surface-2 px-3 py-2 text-sm text-text-1 focus:outline-none focus:ring-2 focus:ring-accent-ring"
                                                onChange={(event) => {
                                                    const instruction = event.target.value;
                                                    useOrchestrationStore.getState().updatePlanEditor(conversationId, turnId,
                                                        (current) => ({ ...current, instruction }));
                                                }}
                                                onKeyDown={(event) => {
                                                    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
                                                        event.preventDefault();
                                                        ask();
                                                    }
                                                }}
                                            />
                                            <div className="mt-2 flex items-center justify-between gap-2">
                                                <span className="text-xs text-text-3">{session.instruction.length}/{MAX_PLAN_INSTRUCTION_LENGTH} · Ctrl/⌘ + Enter</span>
                                                <GlassButton type="submit" size="sm" variant="primary"
                                                    disabled={!canRequest || !session.instruction.trim()}
                                                    aria-label="Send planner request">
                                                    <Send size={14} aria-hidden="true" />
                                                    Send
                                                </GlassButton>
                                            </div>
                                        </form>
                                    ) : null}
                                </>
                            ) : (
                                <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-3">
                                    <p className="mb-3 text-xs text-text-3">Previewing history never changes the active plan. Restore saves a newly validated revision.</p>
                                    <ol className="space-y-3">
                                        {(editor?.history ?? []).map((entry) => (
                                            <li key={entry.run_id} className="rounded-xl border border-edge bg-surface-2 p-3">
                                                <p className="text-sm font-medium text-text-1">
                                                    Revision {entry.revision} · {originLabels[entry.origin]}
                                                    {entry.run_id === plan.run_id ? ' · Current' : ''}
                                                </p>
                                                <p className="mt-1 whitespace-pre-wrap break-words text-xs text-text-2">{entry.note}</p>
                                                <p className="mt-1 text-xs text-text-3">{timestampLabel(entry.created_at)}</p>
                                                <div className="mt-2 flex flex-wrap gap-2">
                                                    <GlassButton size="sm" variant="subtle"
                                                        onClick={() => void previewPlanEditorRevision(target, entry.run_id)}
                                                        aria-label={`Preview revision ${entry.revision}`}>Preview</GlassButton>
                                                    {entry.run_id !== plan.run_id ? (
                                                        <GlassButton size="sm" variant="ghost" disabled={!canRequest || Boolean(pending)}
                                                            onClick={() => void submitPlanRevision(target, { action: 'restore', source_run_id: entry.run_id })}
                                                            aria-label={`Restore revision ${entry.revision}`}>
                                                            <RotateCcw size={13} aria-hidden="true" />
                                                            Restore
                                                        </GlassButton>
                                                    ) : null}
                                                </div>
                                            </li>
                                        ))}
                                    </ol>
                                    {editor && editor.next_before_revision !== null ? (
                                        <GlassButton size="sm" className="mt-3" disabled={session.historyLoading}
                                            onClick={() => void loadPlanEditorHistory(target)}>
                                            {session.historyLoading ? 'Loading history…' : 'Load earlier revisions'}
                                        </GlassButton>
                                    ) : null}
                                </div>
                            )}
                        </div>
                    </aside>
                </div>
            </GlassPanel>
        </div>,
        document.body,
    );
}
