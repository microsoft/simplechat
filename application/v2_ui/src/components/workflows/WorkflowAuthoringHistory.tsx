// WorkflowAuthoringHistory.tsx

import { useEffect, useState, useSyncExternalStore, type ReactNode, type SyntheticEvent } from 'react';
import { unstable_batchedUpdates } from 'react-dom';
import {
    WorkflowAuthoringHistory, historyActionOrigin, isWorkflowHistoryTurnId, type WorkflowHistoryAction,
    type WorkflowHistoryDirection, type WorkflowHistoryEntry, type WorkflowHistoryOrigin, type WorkflowHistoryRecordResult,
} from '../../lib/workflowAuthoringHistory';
import {
    evaluateWorkflowRestore, workflowAuthoringEligibility, workflowCandidateEligibility, type WorkflowEditImpact,
} from '../../lib/workflowAuthoring';
import { WORKFLOW_ALERT_FIELDS } from '../../lib/workflowAlerts';
import {
    EMPTY_WORKFLOW_ATTRIBUTION, buildWorkflowKeyRevert, diffWorkflowChanges, nextWorkflowAttribution, parseWorkflowChangeKey,
    planWorkflowTurnRevert, workflowChangedKeys, workflowChangeKeyLabel, workflowChangeStamp, workflowIdentityChange, workflowRestoreStamper,
    type WorkflowAttribution, type WorkflowChangeStamp,
} from '../../lib/workflowChangeTracking';
import { flowTaskNodeId } from '../../lib/workflowFlow';
import { isRecord, sameEditorValue } from '../../lib/workspaceAuthoring';
import type { WorkflowDefinition, WorkflowEditorOptions } from '../../lib/workflowEditor';
import {
    WorkflowFieldDraftStore, sameWorkflowFieldDrafts, type WorkflowFieldDraftSnapshot,
} from './WorkflowFieldDrafts';

interface Checkpoint {
    readonly draft: WorkflowDefinition;
    readonly fields: WorkflowFieldDraftSnapshot;
    /** The last author of each key that differs from the opened baseline; derived, never compared. */
    readonly attribution: WorkflowAttribution;
}

type Stamper = (key: string) => WorkflowChangeStamp;

/** One retained history entry, as the Changes tab lists it. */
export interface WorkflowSessionStep {
    readonly id: number;
    readonly label: string;
    readonly origin: WorkflowHistoryOrigin;
    readonly turnId?: string;
    /** False for undone steps that Redo can bring back. */
    readonly applied: boolean;
}

export type WorkflowChangeResult =
    | { readonly status: 'applied' | 'confirmation_required' | 'noop' }
    | { readonly status: 'rejected'; readonly message: string };

export type WorkflowTurnRevertResult =
    | { readonly status: 'unavailable' | 'noop' }
    | { readonly status: 'rejected'; readonly message: string }
    | {
        readonly status: 'applied' | 'confirmation_required';
        readonly reverted: number;
        readonly skipped: number;
        readonly revertedKeys: readonly { key: string; label: string }[];
        readonly skippedKeys: readonly { key: string; label: string; reason?: string }[];
    };

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

/** A revert, restore, or assist candidate that removes blocks or changes bindings, awaiting confirmation. */
interface ChangeProposal {
    kind: 'change';
    source: number;
    options: WorkflowEditorOptions;
    candidate: WorkflowDefinition;
    fields?: WorkflowFieldDraftSnapshot;
    stamp: Stamper;
    action: WorkflowHistoryAction;
    title: string;
    confirmLabel: string;
    announcement: string;
    label: string;
    message: string;
    impact: WorkflowEditImpact[];
}

interface SessionView {
    draft: WorkflowDefinition;
    revision: number;
    undoLabel: string;
    redoLabel: string;
    pending: ReplayProposal | OverflowProposal | ChangeProposal | null;
    notice: string;
    announcement: string;
    /** The saved definition the editor opened (or last saved), or a new workflow's initial draft. */
    baseline: WorkflowDefinition;
    attribution: WorkflowAttribution;
    steps: readonly WorkflowSessionStep[];
    /** Earlier steps were dropped by eviction, a cleared history, or a format change. */
    trimmed: boolean;
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
    /** Set by reverts and restores: the stamps and field drafts the applied version brings back. */
    stamp?: Stamper;
    fields?: WorkflowFieldDraftSnapshot;
    announcement?: string;
}

/** Top-level fields the editor authors. Everything else is identity, scope, or runtime state it keeps. */
export const WORKFLOW_AUTHORED_FIELDS: readonly string[] = Object.freeze([
    'name', 'description', 'runner_type', 'selected_agent', 'model_endpoint_id', 'model_id',
    'chat_capabilities_enabled', 'trigger_type', 'schedule', 'is_enabled', 'error_handling', 'm365_run_as_user_id',
    'tasks', 'reference_inputs', 'durable_execution', 'flow', 'limits', 'file_sync', ...WORKFLOW_ALERT_FIELDS,
]);

/** Fields an AI assist candidate may never change (roadmap §5 "Never allowed"), even where the user can. */
export const ASSIST_FORBIDDEN_FIELDS: readonly string[] = Object.freeze([
    'is_enabled', 'm365_run_as_user_id', 'definition_version', 'id', 'user_id', 'group_id', 'url_access_enabled',
]);

/** Task fields tied to an approval, which an assist candidate may not add, change, or remove. */
export const ASSIST_FORBIDDEN_TASK_FIELDS: readonly string[] = Object.freeze(['approval']);

const AUTHORED_FIELD_SET = new Set(WORKFLOW_AUTHORED_FIELDS);
const ASSIST_FORBIDDEN_FIELD_SET = new Set(ASSIST_FORBIDDEN_FIELDS);
const ABSENT = Symbol('absent');
const MAX_ACTION_LABEL = 100;

function ownField(record: unknown, field: string): unknown {
    return isRecord(record) && Object.hasOwn(record, field) ? record[field] : ABSENT;
}

// An absent or null approval is no approval.
function taskFieldValue(task: unknown, field: string): unknown {
    const value = ownField(task, field);
    return value === ABSENT || value === null || value === undefined ? null : value;
}

function tasksById(workflow: WorkflowDefinition): Map<string, unknown> {
    const result = new Map<string, unknown>();
    for (const task of Array.isArray(workflow.tasks) ? workflow.tasks : []) {
        if (isRecord(task) && typeof task.id === 'string' && !result.has(task.id)) result.set(task.id, task);
    }
    return result;
}

/**
 * Why an AI assist candidate may not be applied to `current`, or '' when it may. The candidate
 * may change only authored fields, never a forbidden field or a task approval, and every ID it
 * keeps must keep its meaning.
 */
export function workflowAssistViolation(current: WorkflowDefinition, candidate: WorkflowDefinition): string {
    if (!isRecord(candidate) || Array.isArray(candidate)) return 'The assist candidate is not a workflow.';
    for (const field of new Set([...Object.keys(current), ...Object.keys(candidate)])) {
        if (sameEditorValue(ownField(current, field), ownField(candidate, field))) continue;
        if (ASSIST_FORBIDDEN_FIELD_SET.has(field)) return `AI assist cannot change ${field}. Change it yourself if it needs to change.`;
        if (!AUTHORED_FIELD_SET.has(field)) return `AI assist cannot change ${field}, which the workflow editor does not author.`;
    }
    const before = tasksById(current);
    const after = tasksById(candidate);
    for (const id of new Set([...before.keys(), ...after.keys()])) {
        for (const field of ASSIST_FORBIDDEN_TASK_FIELDS) {
            if (!sameEditorValue(taskFieldValue(before.get(id), field), taskFieldValue(after.get(id), field))) {
                return 'AI assist cannot add, change, or remove a task approval. Change approvals yourself.';
            }
        }
    }
    return workflowIdentityChange(current, candidate);
}

function actionLabel(label: string, fallback: string): string {
    const text = label.replace(/\s+/g, ' ').trim();
    return text ? Array.from(text).slice(0, MAX_ACTION_LABEL).join('') : fallback;
}

function stampFor(action: WorkflowHistoryAction): Stamper {
    const stamp = workflowChangeStamp(historyActionOrigin(action), action.turnId);
    return () => stamp;
}

function sameCheckpoint(left: Checkpoint, right: Checkpoint): boolean {
    return sameEditorValue(left.draft, right.draft) && sameWorkflowFieldDrafts(left.fields, right.fields);
}

/** Reverted fields show their restored value, not text typed before the revert. Undefined when nothing is dropped. */
function withoutFieldDrafts(snapshot: WorkflowFieldDraftSnapshot, keys: readonly string[]): WorkflowFieldDraftSnapshot | undefined {
    const targets = keys.map(parseWorkflowChangeKey).flatMap((info) => (info.scope === 'task' || info.scope === 'node') && 'id' in info
        ? [{ scope: info.scope, id: info.id, field: info.field }] : []);
    const fields = new Map(snapshot.fields);
    for (const [id, draft] of snapshot.fields) {
        if (targets.some((target) => draft.owner[0] === target.scope && draft.owner[1] === target.id &&
            (!target.field || draft.path[0] === target.field))) fields.delete(id);
    }
    return fields.size === snapshot.fields.size ? undefined : { fields, repeatRows: snapshot.repeatRows };
}

function restoreAuthoredFields(current: WorkflowDefinition, saved: WorkflowDefinition): WorkflowDefinition {
    const result = { ...current };
    for (const key of WORKFLOW_AUTHORED_FIELDS) {
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
    private opened: Checkpoint;
    private stepSource: { entries: readonly WorkflowHistoryEntry<Checkpoint>[]; applied: number } | null = null;
    private rolledBack = false;

    constructor(draft: WorkflowDefinition) {
        this.fields.reconcile(draft);
        this.opened = { draft, fields: this.fields.capture(), attribution: EMPTY_WORKFLOW_ATTRIBUTION };
        this.history = new WorkflowAuthoringHistory(this.opened, sameCheckpoint);
        this.view = {
            draft, revision: 0, undoLabel: '', redoLabel: '', pending: null, notice: '', announcement: '',
            baseline: draft, attribution: EMPTY_WORKFLOW_ATTRIBUTION, steps: [], trimmed: false,
        };
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
        // Every format keeps history for change tracking; only structured drafts offer Undo and Redo.
        const structured = (update.draft ?? this.view.draft).definition_version === 3;
        this.view = {
            ...this.view, ...update, revision: this.view.revision + 1,
            undoLabel: structured ? this.history?.peek('undo')?.action.label ?? '' : '',
            redoLabel: structured ? this.history?.peek('redo')?.action.label ?? '' : '',
            steps: this.steps(),
        };
        this.listeners.forEach((listener) => listener());
    }

    private steps(): readonly WorkflowSessionStep[] {
        const entries = this.history?.retainedEntries ?? [];
        const applied = this.history?.appliedCount ?? 0;
        if (this.stepSource?.entries === entries && this.stepSource.applied === applied) return this.view.steps;
        this.stepSource = { entries, applied };
        return entries.map((entry, position) => Object.freeze({
            id: entry.id, label: entry.action.label, origin: historyActionOrigin(entry.action),
            ...(entry.action.turnId === undefined ? {} : { turnId: entry.action.turnId }),
            applied: position < applied,
        }));
    }

    private start(action: WorkflowHistoryAction, event?: Event) {
        this.fields.beginBatch();
        this.transaction = {
            before: { draft: this.view.draft, fields: this.fields.capture(), attribution: this.view.attribution },
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
        this.rolledBack = true;
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
                    if (transaction.fields) this.fields.restore(transaction.fields);
                    this.fields.reconcile(transaction.draft);
                    candidate = { draft: transaction.draft, fields: this.fields.capture(), attribution: transaction.before.attribution };
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
                // History is kept for every format so changes stay attributed; a format change starts it again.
                const sameVersion = transaction.before.draft.definition_version === candidate.draft.definition_version;
                const structured = candidate.draft.definition_version === 3;
                const redoDropped = sameVersion && Boolean(this.history?.peek('redo'));
                let result: WorkflowHistoryRecordResult;
                try {
                    // A coalescing edit extends its group's entry, so attribute the whole group from its start.
                    const base = sameVersion ? this.history?.coalescingBase(transaction.action) ?? transaction.before : transaction.before;
                    const stamp = transaction.stamp ?? stampFor(transaction.action);
                    candidate = {
                        ...candidate,
                        attribution: nextWorkflowAttribution(base.attribution, base.draft, candidate.draft, this.view.baseline, stamp),
                    };
                    result = sameVersion && this.history
                        ? this.history.record(transaction.before, candidate, transaction.action)
                        : { status: 'applied', evicted: 0 };
                } catch {
                    this.rollback(transaction);
                    this.context?.onError('The workflow edit could not be recorded. The previous draft, fields, and history were retained.');
                    return;
                }
                if (result.status === 'overflow' && structured) {
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
                // Classic drafts have no Undo/Redo, so an edit too large for history just clears it.
                const cleared = !sameVersion || result.status === 'overflow';
                if (cleared) this.history?.clear();
                this.semanticRevision++;
                this.publish({
                    draft: candidate.draft,
                    attribution: candidate.attribution,
                    ...(cleared || result.evicted ? { trimmed: true } : {}),
                    ...(result.evicted && structured ? { notice: 'Older workflow history steps were removed to keep history within 100 actions and 32 MiB. Your current draft is unchanged.' } : {}),
                    ...(transaction.announcement ? {
                        announcement: `${transaction.announcement}${redoDropped && structured ? ' Redo steps after this point were cleared.' : ''}`,
                    } : {}),
                });
                if (transaction.announcement) this.context?.onRestore(transaction.before.draft, candidate.draft, transaction.action.targetId);
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
        // Classic drafts keep history for change tracking only.
        if (this.view.draft.definition_version !== 3) return;
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
                    draft: candidate, attribution: checkpoint.attribution, pending: null,
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
                        attribution: pending.candidate.attribution,
                        trimmed: true,
                        notice: 'The complete edit was applied. Workflow Undo/Redo history was cleared because this edit exceeded its memory budget.',
                    });
                    this.context?.onRestore(before, pending.candidate.draft, pending.action.targetId);
                } finally {
                    this.fields.endBatch();
                }
            });
            return;
        }
        if (pending.kind === 'change') {
            const changedOptions = !sameEditorValue(pending.options, this.context.options);
            const result = this.view.draft.definition_version === 3
                ? evaluateWorkflowRestore(this.view.draft, pending.candidate, this.context.options, !changedOptions) : null;
            if (result?.status === 'rejected') {
                this.context.onError(result.message);
                return;
            }
            if (changedOptions && result?.status === 'confirmation_required') {
                this.publish({ pending: {
                    ...pending, options: this.context.options, impact: result.impact,
                    message: 'Editor capabilities changed. Review the current impact and confirm again; nothing was changed.',
                } });
                return;
            }
            this.commit(pending.candidate, pending.action, pending.stamp, pending.announcement, pending.fields);
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

    /** Checks shared by every revert, restore, and assist: the editor must be writable and idle. */
    private refusal(): string {
        this.closeGroup();
        const denial = this.denial(true);
        if (denial) this.context?.onError(denial);
        return denial;
    }

    /**
     * Apply a revert, restore, or assist candidate as one new, undoable history entry. Structured
     * drafts go through the same impact confirmation as Undo and Redo first.
     */
    private propose(
        candidate: WorkflowDefinition,
        action: WorkflowHistoryAction,
        stamp: Stamper,
        copy: { title: string; confirmLabel: string; announcement: string },
        fields?: WorkflowFieldDraftSnapshot,
    ): WorkflowChangeResult {
        const context = this.context;
        if (!context) return { status: 'rejected', message: 'The workflow editor is not ready.' };
        if (candidate === this.view.draft && !fields) return { status: 'noop' };
        if (this.view.draft.definition_version === 3) {
            const result = evaluateWorkflowRestore(this.view.draft, candidate, context.options);
            if (result.status === 'rejected') {
                context.onError(result.message);
                return { status: 'rejected', message: result.message };
            }
            context.onError('');
            if (result.status === 'confirmation_required') {
                this.publish({ pending: {
                    kind: 'change', source: this.semanticRevision, options: context.options, candidate, fields, stamp, action,
                    ...copy, label: action.label, impact: result.impact,
                    message: result.message.replace(/^This history step/, 'This change'),
                } });
                return { status: 'confirmation_required' };
            }
        }
        return this.commit(candidate, action, stamp, copy.announcement, fields);
    }

    private commit(
        candidate: WorkflowDefinition,
        action: WorkflowHistoryAction,
        stamp: Stamper,
        announcement: string,
        fields?: WorkflowFieldDraftSnapshot,
    ): WorkflowChangeResult {
        const pending = this.view.pending;
        this.rolledBack = false;
        this.start(action);
        const transaction = this.transaction;
        if (!transaction) return { status: 'rejected', message: 'The workflow editor is not ready.' };
        transaction.draft = candidate;
        transaction.stamp = stamp;
        transaction.announcement = announcement;
        if (fields) transaction.fields = fields;
        if (this.finish()) return { status: 'applied' };
        // An edit too large for history is proposed like any other edit.
        if (this.view.pending && this.view.pending !== pending) return { status: 'confirmation_required' };
        return this.rolledBack ? { status: 'rejected', message: 'The change could not be applied. The draft is unchanged.' } : { status: 'noop' };
    }

    private formatRefusal(): string {
        if (this.view.baseline.definition_version === this.view.draft.definition_version) return '';
        const message = 'The workflow format changed in this draft, so its changes can only be discarded together. Cancel to discard them.';
        this.context?.onError(message);
        return message;
    }

    /** Take change keys back to their opened values as one new history entry. Removed items return where they were. */
    revertChange(keys: readonly string[]): WorkflowChangeResult {
        const denial = this.refusal() || this.formatRefusal();
        if (denial) return { status: 'rejected', message: denial };
        const { baseline, draft } = this.view;
        const { candidate, failed } = buildWorkflowKeyRevert(draft, baseline, keys);
        if (candidate === draft) {
            const reason = failed.values().next().value;
            if (!reason) return { status: 'noop' };
            this.context?.onError(`That change could not be reverted. ${reason}`);
            return { status: 'rejected', message: reason };
        }
        const names = keys.map((key) => workflowChangeKeyLabel(key, draft, baseline));
        const changes = diffWorkflowChanges(baseline, draft);
        const restoring = keys.some((key) => !failed.has(key) && changes.byKey.get(key)?.kind === 'removed');
        const label = actionLabel(`${restoring ? 'Restore' : 'Revert'} ${names.join(', ')}`, 'Revert change');
        const partial = failed.size ? ` ${failed.size === 1 ? 'One part' : `${failed.size} parts`} could not be reverted.` : '';
        return this.propose(candidate, { label, origin: 'restore' }, workflowRestoreStamper(this.opened.attribution), {
            title: restoring ? 'Restore this item?' : 'Revert this change?',
            confirmLabel: restoring ? 'Restore' : 'Revert',
            announcement: `${label}.${partial} The workflow has not been saved.`,
        }, withoutFieldDrafts(this.fields.capture(), keys.filter((key) => !failed.has(key))));
    }

    /**
     * Apply an earlier version as one new history entry, so nothing is deleted. `step` is a
     * retained entry ID (its state after that step) or 'opened' for the opened baseline.
     */
    restoreTo(step: number | 'opened'): WorkflowChangeResult {
        const denial = this.refusal();
        if (denial) return { status: 'rejected', message: denial };
        const entries = this.history?.retainedEntries ?? [];
        const position = step === 'opened' ? -1 : entries.findIndex((item) => item.id === step);
        const entry = position < 0 ? null : entries[position];
        const unavailable = step !== 'opened' && !entry ? 'That history step is no longer retained.'
            : position >= (this.history?.appliedCount ?? 0) ? 'That step was undone. Use Redo to bring it back.' : '';
        if (unavailable) {
            this.context?.onError(unavailable);
            return { status: 'rejected', message: unavailable };
        }
        const checkpoint = entry?.after ?? this.opened;
        if (checkpoint.draft.definition_version !== this.view.draft.definition_version) {
            const message = this.formatRefusal() || 'That version uses a different workflow format.';
            return { status: 'rejected', message };
        }
        const candidate = restoreAuthoredFields(this.view.draft, checkpoint.draft);
        const name = entry ? `after “${entry.action.label}”` : this.view.baseline.id ? 'the opened version' : 'the start';
        const label = actionLabel(`Restore to ${name}`, 'Restore earlier version');
        return this.propose(sameEditorValue(candidate, this.view.draft) ? this.view.draft : candidate,
            { label, origin: 'restore' }, workflowRestoreStamper(checkpoint.attribution), {
                title: 'Restore this version?', confirmLabel: 'Restore version',
                announcement: `${label}. Your later steps stay in history. The workflow has not been saved.`,
            }, sameWorkflowFieldDrafts(checkpoint.fields, this.fields.capture()) ? undefined : checkpoint.fields);
    }

    /**
     * Revert what one assist turn changed, as one new history entry. Keys changed again after the
     * turn are skipped, so reverting never discards later work.
     */
    revertTurn(turnId: string): WorkflowTurnRevertResult {
        this.closeGroup();
        const entries = this.history?.retainedEntries ?? [];
        const applied = entries.slice(0, this.history?.appliedCount ?? 0);
        const turn = (entry: WorkflowHistoryEntry<Checkpoint>) => historyActionOrigin(entry.action) === 'ai' && entry.action.turnId === turnId;
        if (!entries.some(turn)) return { status: 'unavailable' };
        const turnEntries = applied.filter(turn);
        if (!turnEntries.length) return { status: 'noop' };
        const denial = this.refusal();
        if (denial) return { status: 'rejected', message: denial };
        const current = this.view.draft;
        const plan = planWorkflowTurnRevert(current, turnEntries.map((entry) => ({ before: entry.before.draft, after: entry.after.draft })));
        const source = (key: string) => turnEntries[plan.entryFor(key)].before;
        const { candidate, failed } = buildWorkflowKeyRevert(current, (key) => source(key).draft, plan.keys);
        const describe = (key: string) => ({ key, label: workflowChangeKeyLabel(key, current, source(key).draft) });
        const revertedKeys = plan.keys.filter((key) => !failed.has(key)).map(describe);
        const skippedKeys = [
            ...plan.skipped.map((key) => ({ ...describe(key), reason: 'Changed after this turn.' })),
            ...plan.keys.filter((key) => failed.has(key)).map((key) => ({ ...describe(key), reason: failed.get(key) })),
        ];
        const counts = { reverted: revertedKeys.length, skipped: skippedKeys.length, revertedKeys, skippedKeys };
        if (!revertedKeys.length || candidate === current) return { status: 'noop' };
        const skipped = skippedKeys.length ? ` ${skippedKeys.length} skipped because they changed later or cannot be reverted alone.` : '';
        const restoreStamp = workflowRestoreStamper(EMPTY_WORKFLOW_ATTRIBUTION);
        const result = this.propose(candidate, { label: 'Revert AI assist turn', origin: 'restore', turnId },
            (key) => source(key).attribution.get(key) ?? restoreStamp(key), {
                title: 'Revert this AI assist turn?', confirmLabel: 'Revert turn',
                announcement: `Reverted ${revertedKeys.length} AI assist ${revertedKeys.length === 1 ? 'change' : 'changes'}.${skipped} The workflow has not been saved.`,
            }, withoutFieldDrafts(this.fields.capture(), revertedKeys.map((item) => item.key)));
        if (result.status === 'rejected') return result;
        if (result.status === 'noop') return { status: 'noop' };
        return { status: result.status, ...counts };
    }

    /**
     * Apply an AI assist candidate as one history entry attributed to the turn. The candidate may
     * change only authored fields and never a forbidden one; it then takes the normal edit path:
     * eligibility, impact confirmation, and the history budget.
     */
    applyAssist(candidate: WorkflowDefinition, { turnId, label }: { turnId: string; label: string }): WorkflowChangeResult {
        if (!isWorkflowHistoryTurnId(turnId)) return { status: 'rejected', message: 'The AI assist turn ID is invalid.' };
        const denial = this.refusal();
        if (denial) return { status: 'rejected', message: denial };
        const violation = workflowAssistViolation(this.view.draft, candidate);
        if (violation) {
            this.context?.onError(violation);
            return { status: 'rejected', message: violation };
        }
        const action = { label: actionLabel(typeof label === 'string' ? label : '', 'AI assist'), origin: 'ai' as const, turnId };
        return this.propose(candidate, action, stampFor(action), {
            title: 'Apply AI assist changes?', confirmLabel: 'Apply changes',
            announcement: `Applied AI assist changes: ${action.label}. Review them before saving.`,
        }, withoutFieldDrafts(this.fields.capture(), [...workflowChangedKeys(this.view.draft, candidate)]));
    }

    saved(draft: WorkflowDefinition) {
        this.closeGroup();
        unstable_batchedUpdates(() => {
            this.fields.beginBatch();
            try {
                this.history?.clear();
                this.fields.acceptSavedFields();
                // The saved version is the new baseline: its changes are no longer unsaved.
                this.opened = { draft, fields: this.fields.capture(), attribution: EMPTY_WORKFLOW_ATTRIBUTION };
                this.semanticRevision++;
                this.publish({
                    draft, baseline: draft, attribution: EMPTY_WORKFLOW_ATTRIBUTION, trimmed: false,
                    pending: null, notice: '', announcement: '',
                });
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
