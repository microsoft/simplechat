// WorkflowAuthoringHistory.tsx

import { useEffect, useState, useSyncExternalStore, type ReactNode, type SyntheticEvent } from 'react';
import { unstable_batchedUpdates } from 'react-dom';
import {
    WorkflowAuthoringHistory, type WorkflowHistoryAction, type WorkflowHistoryDirection, type WorkflowHistoryRecordResult,
} from '../../lib/workflowAuthoringHistory';
import {
    evaluateWorkflowRestore, workflowAuthoringEligibility, workflowCandidateEligibility, type WorkflowEditImpact,
} from '../../lib/workflowAuthoring';
import { flowTaskNodeId } from '../../lib/workflowFlow';
import { sameEditorValue } from '../../lib/workspaceAuthoring';
import type { WorkflowDefinition, WorkflowEditorOptions } from '../../lib/workflowEditor';
import {
    WorkflowFieldDraftStore, sameWorkflowFieldDrafts, type WorkflowFieldDraftSnapshot,
} from './WorkflowFieldDrafts';

interface Checkpoint {
    readonly draft: WorkflowDefinition;
    readonly fields: WorkflowFieldDraftSnapshot;
}

interface ReplayProposal {
    kind: 'replay';
    direction: WorkflowHistoryDirection;
    entryId: number;
    source: number;
    options: WorkflowEditorOptions;
    label: string;
    message: string;
    impact: WorkflowEditImpact[];
}

interface OverflowProposal {
    kind: 'overflow';
    source: number;
    candidate: Checkpoint;
    action: WorkflowHistoryAction;
    label: string;
    message: string;
    impact: WorkflowEditImpact[];
}

interface SessionView {
    draft: WorkflowDefinition;
    revision: number;
    undoLabel: string;
    redoLabel: string;
    pending: ReplayProposal | OverflowProposal | null;
    notice: string;
    announcement: string;
}

interface SessionContext {
    options: WorkflowEditorOptions;
    readOnly: boolean;
    saving: boolean;
    commandPending: boolean;
    selectionId?: string | null;
    onError: (message: string) => void;
    onRestore: (before: WorkflowDefinition, after: WorkflowDefinition, targetId?: string) => void;
    onRollback?: (before: WorkflowDefinition, after: WorkflowDefinition, targetId?: string) => void;
}

interface Transaction {
    before: Checkpoint;
    draft: WorkflowDefinition;
    action: WorkflowHistoryAction;
    event?: Event;
    selectionId?: string | null;
    rejected: boolean;
}

const authoredFields = [
    'name', 'description', 'runner_type', 'selected_agent', 'model_endpoint_id', 'model_id',
    'chat_capabilities_enabled', 'trigger_type', 'schedule', 'is_enabled', 'error_handling', 'm365_run_as_user_id',
    'tasks', 'reference_inputs', 'durable_execution', 'flow', 'limits',
] as const;

function sameCheckpoint(left: Checkpoint, right: Checkpoint): boolean {
    return sameEditorValue(left.draft, right.draft) && sameWorkflowFieldDrafts(left.fields, right.fields);
}

function restoreAuthoredFields(current: WorkflowDefinition, saved: WorkflowDefinition): WorkflowDefinition {
    const result = { ...current };
    for (const key of authoredFields) {
        if (Object.hasOwn(saved, key)) Object.defineProperty(result, key, {
            value: saved[key], configurable: true, enumerable: true, writable: true,
        });
        else Reflect.deleteProperty(result, key);
    }
    return result;
}

export class WorkflowAuthoringSession {
    readonly fields = new WorkflowFieldDraftStore();
    private history: WorkflowAuthoringHistory<Checkpoint> | null;
    private view: SessionView;
    private context: SessionContext | null = null;
    private listeners = new Set<() => void>();
    private transaction: Transaction | null = null;
    private semanticRevision = 0;
    private invalidated = false;
    private composition = false;
    private mounts = 0;
    private eventTimer: ReturnType<typeof setTimeout> | null = null;

    constructor(draft: WorkflowDefinition) {
        this.fields.reconcile(draft);
        this.history = new WorkflowAuthoringHistory({ draft, fields: this.fields.capture() }, sameCheckpoint);
        this.view = { draft, revision: 0, undoLabel: '', redoLabel: '', pending: null, notice: '', announcement: '' };
        this.fields.setMutationHandler((owner, path, change) => {
            const targetId = owner[0] === 'task' ? flowTaskNodeId(this.draft, owner[1]) : owner[1];
            this.edit({ label: `Edit ${path.join(' ')}`, group: JSON.stringify([owner, path]), targetId }, () => {
                if (targetId) this.target(targetId);
                change();
            });
        });
    }

    subscribe = (listener: () => void) => {
        this.listeners.add(listener);
        return () => { this.listeners.delete(listener); };
    };

    getSnapshot = () => this.view;

    get draft() {
        return this.transaction?.draft ?? this.view.draft;
    }

    get active() {
        return !this.invalidated;
    }

    get saving() {
        return this.context?.saving === true;
    }

    setSaving(saving: boolean) {
        if (this.context) this.context = { ...this.context, saving };
    }

    configure(context: SessionContext) {
        this.context = context;
    }

    private denial(replay = false): string {
        if (this.invalidated) return 'Authoring access was lost. Close and reopen the editor.';
        if (!this.context) return 'The workflow editor is not ready.';
        if (this.context.saving || this.context.readOnly) return 'Editing is unavailable while this workflow is read-only or being saved.';
        if (this.view.pending || replay && this.context.commandPending) return 'Finish or cancel the current confirmation first.';
        if (replay && this.composition) return 'Finish composing text before using workflow history.';
        return this.draft.definition_version === 3 ? workflowAuthoringEligibility(this.draft, this.context.options) : '';
    }

    private publish(update: Partial<SessionView> = {}) {
        this.view = {
            ...this.view, ...update, revision: this.view.revision + 1,
            undoLabel: this.history?.peek('undo')?.action.label ?? '',
            redoLabel: this.history?.peek('redo')?.action.label ?? '',
        };
        this.listeners.forEach((listener) => listener());
    }

    private start(action: WorkflowHistoryAction, event?: Event) {
        this.fields.beginBatch();
        this.transaction = {
            before: { draft: this.view.draft, fields: this.fields.capture() },
            draft: this.view.draft, action, event, selectionId: this.context?.selectionId, rejected: false,
        };
    }

    edit(action: WorkflowHistoryAction, change: () => void): boolean {
        const denial = this.denial();
        if (denial) {
            this.reject();
            this.context?.onError(denial);
            return false;
        }
        if (this.transaction) {
            try {
                change();
            } catch (cause: unknown) {
                this.reject();
                throw cause;
            }
            return !this.transaction.rejected;
        }
        this.start(action);
        try {
            change();
            return this.finish();
        } catch (cause: unknown) {
            this.reject();
            this.finish();
            throw cause;
        }
    }

    changeDraft(
        update: WorkflowDefinition | ((draft: WorkflowDefinition) => WorkflowDefinition),
        action?: WorkflowHistoryAction,
    ): boolean {
        return this.edit(action ?? { label: 'Edit workflow' }, () => {
            const transaction = this.transaction;
            if (!transaction) throw new Error('A workflow edit requires an active transaction.');
            transaction.draft = typeof update === 'function' ? update(transaction.draft) : update;
            if (action) transaction.action = action;
        });
    }

    target(id: string) {
        if (this.transaction) this.transaction.action = { ...this.transaction.action, targetId: id };
    }

    reject() {
        if (this.transaction) this.transaction.rejected = true;
    }

    private rollback(transaction: Transaction) {
        this.fields.restore(transaction.before.fields);
        this.context?.onRollback?.(transaction.draft, transaction.before.draft, transaction.selectionId ?? undefined);
    }

    beginEvent(action: WorkflowHistoryAction, event: Event) {
        if (this.transaction?.event === event) return;
        this.finish();
        this.start(action, event);
        // Native capture and React bubble listeners can have a microtask checkpoint between them.
        // A stopped propagation still commits, but only after the complete native event.
        this.eventTimer = setTimeout(() => {
            if (this.transaction?.event === event) this.finish();
        }, 0);
    }

    finish(): boolean {
        if (this.eventTimer !== null) {
            clearTimeout(this.eventTimer);
            this.eventTimer = null;
        }
        const transaction = this.transaction;
        if (!transaction) return true;
        this.transaction = null;
        let applied = false;
        unstable_batchedUpdates(() => {
            try {
                if (transaction.rejected || this.invalidated) {
                    this.fields.restore(transaction.before.fields);
                    return;
                }
                let candidate: Checkpoint;
                try {
                    this.fields.reconcile(transaction.draft);
                    candidate = { draft: transaction.draft, fields: this.fields.capture() };
                } catch {
                    this.rollback(transaction);
                    this.context?.onError('The workflow edit could not be prepared. The previous draft and fields were retained.');
                    return;
                }
                if (sameCheckpoint(transaction.before, candidate)) {
                    this.fields.restore(transaction.before.fields);
                    return;
                }
                if (transaction.before.draft.definition_version === 3 && this.context) {
                    const invalid = !sameEditorValue(restoreAuthoredFields(transaction.before.draft, candidate.draft), candidate.draft)
                        ? 'Workflow edits cannot change saved identity, scope, revision, or runtime metadata.'
                        : workflowCandidateEligibility(transaction.before.draft, candidate.draft, this.context.options);
                    if (invalid) {
                        this.rollback(transaction);
                        this.context.onError(invalid);
                        return;
                    }
                }
                const enabled = transaction.before.draft.definition_version === 3 && candidate.draft.definition_version === 3;
                let result: WorkflowHistoryRecordResult;
                try {
                    result = enabled && this.history
                        ? this.history.record(transaction.before, candidate, transaction.action)
                        : { status: 'applied', evicted: 0 };
                } catch {
                    this.rollback(transaction);
                    this.context?.onError('The workflow edit could not be recorded. The previous draft, fields, and history were retained.');
                    return;
                }
                if (result.status === 'overflow') {
                    this.rollback(transaction);
                    this.publish({ pending: {
                        kind: 'overflow', source: this.semanticRevision, candidate, action: transaction.action,
                        label: transaction.action.label, impact: [],
                        message: 'This edit exceeds the workflow history budget even on its own. Apply the complete edit and clear Undo/Redo history, or keep the draft unchanged.',
                    } });
                    return;
                }
                if (result.status === 'noop') {
                    this.fields.restore(transaction.before.fields);
                    return;
                }
                if (!enabled) this.history?.clear();
                this.semanticRevision++;
                this.publish({
                    draft: candidate.draft,
                    ...(result.evicted ? { notice: 'Older workflow history steps were removed to keep history within 100 actions and 32 MiB. Your current draft is unchanged.' } : {}),
                });
                applied = true;
            } finally {
                this.fields.endBatch();
            }
        });
        return applied;
    }

    closeGroup() {
        this.finish();
        this.history?.closeGroup();
    }

    composing(active: boolean) {
        this.closeGroup();
        this.composition = active;
    }

    request(direction: WorkflowHistoryDirection) {
        this.closeGroup();
        const denial = this.denial(true);
        if (denial) {
            this.context?.onError(denial);
            return;
        }
        const entry = this.history?.peek(direction);
        if (!entry || !this.context) return;
        const checkpoint = direction === 'undo' ? entry.before : entry.after;
        const candidate = restoreAuthoredFields(this.view.draft, checkpoint.draft);
        const result = evaluateWorkflowRestore(this.view.draft, candidate, this.context.options);
        if (result.status === 'rejected') {
            this.context.onError(result.message);
            return;
        }
        this.context.onError('');
        if (result.status === 'confirmation_required') {
            this.publish({ pending: {
                kind: 'replay', direction, entryId: entry.id, source: this.semanticRevision,
                options: this.context.options, label: entry.action.label, message: result.message, impact: result.impact,
            } });
            return;
        }
        this.restore(direction, entry.id, checkpoint, candidate, entry.action);
    }

    private restore(
        direction: WorkflowHistoryDirection,
        entryId: number,
        checkpoint: Checkpoint,
        candidate: WorkflowDefinition,
        action: WorkflowHistoryAction,
    ) {
        if (!this.history?.replay(direction, entryId)) {
            this.context?.onError('The requested history step changed. Choose Undo or Redo again.');
            return;
        }
        const before = this.view.draft;
        unstable_batchedUpdates(() => {
            this.fields.beginBatch();
            try {
                this.fields.restore(checkpoint.fields);
                this.semanticRevision++;
                this.publish({
                    draft: candidate, pending: null,
                    announcement: `${direction === 'undo' ? 'Undid' : 'Redid'}: ${action.label}. The workflow has not been saved.`,
                });
                this.context?.onRestore(before, candidate, action.targetId);
            } finally {
                this.fields.endBatch();
            }
        });
    }

    confirm() {
        const pending = this.view.pending;
        if (!pending || !this.context) return;
        this.publish({ pending: null });
        const denial = this.denial(true);
        if (denial) {
            this.context.onError(denial);
            return;
        }
        if (pending.source !== this.semanticRevision) {
            this.context.onError('The draft changed while confirmation was open. Request the edit again; nothing was replayed.');
            return;
        }
        if (pending.kind === 'overflow') {
            const result = pending.candidate.draft.definition_version === 3
                ? evaluateWorkflowRestore(this.view.draft, pending.candidate.draft, this.context.options, true) : null;
            if (result?.status === 'rejected') {
                this.context.onError(result.message);
                return;
            }
            const before = this.view.draft;
            unstable_batchedUpdates(() => {
                this.fields.beginBatch();
                try {
                    this.history?.clear();
                    this.fields.restore(pending.candidate.fields);
                    this.semanticRevision++;
                    this.publish({
                        draft: pending.candidate.draft,
                        notice: 'The complete edit was applied. Workflow Undo/Redo history was cleared because this edit exceeded its memory budget.',
                    });
                    this.context?.onRestore(before, pending.candidate.draft, pending.action.targetId);
                } finally {
                    this.fields.endBatch();
                }
            });
            return;
        }
        const entry = this.history?.peek(pending.direction);
        if (!entry || entry.id !== pending.entryId) {
            this.context.onError('The requested history step changed. Choose Undo or Redo again.');
            return;
        }
        const checkpoint = pending.direction === 'undo' ? entry.before : entry.after;
        const candidate = restoreAuthoredFields(this.view.draft, checkpoint.draft);
        const changedOptions = !sameEditorValue(pending.options, this.context.options);
        const result = evaluateWorkflowRestore(this.view.draft, candidate, this.context.options, !changedOptions);
        if (result.status === 'rejected') {
            this.context.onError(result.message);
            return;
        }
        if (changedOptions) {
            this.publish({ pending: {
                ...pending, options: this.context.options, impact: result.impact,
                message: 'Editor capabilities changed. Review the current impact and confirm again; nothing was replayed.',
            } });
            return;
        }
        this.restore(pending.direction, entry.id, checkpoint, candidate, entry.action);
    }

    cancel() {
        this.publish({ pending: null });
    }

    saved(draft: WorkflowDefinition) {
        this.closeGroup();
        unstable_batchedUpdates(() => {
            this.fields.beginBatch();
            try {
                this.history?.clear();
                this.fields.acceptSavedFields();
                this.semanticRevision++;
                this.publish({ draft, pending: null, notice: '', announcement: '' });
            } finally {
                this.fields.endBatch();
            }
        });
    }

    invalidate() {
        this.invalidated = true;
        this.reject();
        this.finish();
        this.history = null;
        unstable_batchedUpdates(() => {
            this.fields.restore({ fields: new Map(), repeatRows: new Map() });
            this.publish({ pending: null, notice: '', announcement: '' });
        });
    }

    dispose() {
        this.invalidate();
        this.context = null;
        this.fields.setMutationHandler(() => { throw new Error('This workflow authoring session was disposed.'); });
        this.listeners.clear();
    }

    retain() {
        this.mounts++;
        return () => {
            this.mounts--;
            // Strict Mode immediately reattaches the same mounted session.
            queueMicrotask(() => { if (!this.mounts) this.dispose(); });
        };
    }
}

export function useWorkflowAuthoringHistory(baseline: WorkflowDefinition) {
    const [session] = useState(() => new WorkflowAuthoringSession(baseline));
    const view = useSyncExternalStore(session.subscribe, session.getSnapshot, session.getSnapshot);
    useEffect(() => session.retain(), [session]);
    return { session, ...view };
}

export function isWorkflowTextControl(target: EventTarget | null): boolean {
    if (!(target instanceof Element)) return false;
    if (target.closest('textarea, [contenteditable]:not([contenteditable="false"]), [role="textbox"]')) return true;
    const input = target.closest('input');
    return Boolean(input && !['button', 'submit', 'reset', 'checkbox', 'radio', 'file', 'range', 'color'].includes(input.type));
}

function eventAction(event: SyntheticEvent<HTMLElement>): WorkflowHistoryAction {
    const element = event.target instanceof Element ? event.target : event.currentTarget;
    const control = element.closest<HTMLElement>('input, textarea, select, button, [contenteditable], [role="textbox"]') ?? element;
    const owner = control.closest<HTMLElement>('[data-workflow-history-owner], [data-workflow-authoring-id]');
    const ownerId = owner?.dataset.workflowHistoryOwner ?? owner?.dataset.workflowAuthoringId ?? 'workflow';
    const ownerKind = owner?.dataset.workflowHistoryKind ?? (owner?.dataset.workflowAuthoringId ? 'node' : 'workflow');
    const row = control.closest<HTMLElement>('[data-workflow-history-row]')?.dataset.workflowHistoryRow ?? '';
    const label = (control.getAttribute('aria-label') || control.getAttribute('data-workflow-field') ||
        control.closest('label')?.textContent || control.textContent || 'workflow').replace(/\s+/g, ' ').trim().slice(0, 100);
    const inputType = 'inputType' in event.nativeEvent ? event.nativeEvent.inputType : '';
    const discrete = ['insertFromPaste', 'insertFromDrop', 'deleteByCut'].includes(String(inputType));
    return {
        label: `${isWorkflowTextControl(control) ? 'Edit ' : ''}${label || 'workflow'}`,
        ...(isWorkflowTextControl(control) && !discrete ? {
            group: JSON.stringify([ownerKind, ownerId, row, control.getAttribute('data-workflow-field') || label]),
        } : {}),
        ...(ownerKind === 'node' ? { targetId: ownerId } : {}),
    };
}

export function WorkflowHistoryBoundary({ session, children }: { session: WorkflowAuthoringSession; children: ReactNode }) {
    const begin = (event: SyntheticEvent<HTMLElement>) => session.beginEvent(eventAction(event), event.nativeEvent);
    return <div className="min-w-0" onChangeCapture={begin} onChange={() => session.finish()}
        onClickCapture={begin} onClick={() => session.finish()}
        onBlurCapture={begin} onBlur={() => session.closeGroup()}
        onPasteCapture={() => session.closeGroup()} onCutCapture={() => session.closeGroup()}
        onDropCapture={() => session.closeGroup()}
        onCompositionStartCapture={() => session.composing(true)}
        onCompositionEnd={() => { queueMicrotask(() => session.composing(false)); }}
        onKeyDown={(event) => {
            if (event.defaultPrevented || event.nativeEvent.isComposing || event.altKey ||
                !(event.ctrlKey || event.metaKey) ||
                isWorkflowTextControl(event.nativeEvent.composedPath()[0] ?? event.target)) return;
            const key = event.key.toLowerCase();
            const direction = key === 'z' ? event.shiftKey ? 'redo' : 'undo'
                : key === 'y' && event.ctrlKey && !event.metaKey && !event.shiftKey ? 'redo' : null;
            const view = session.getSnapshot();
            if (!direction || view.pending || !(direction === 'undo' ? view.undoLabel : view.redoLabel)) return;
            event.preventDefault();
            session.request(direction);
        }}>
        {children}
    </div>;
}
