// WorkflowFieldDrafts.tsx
// Session-only raw field buffers; never part of the saved workflow definition.

import { createContext, useContext, useEffect, useMemo, useState, useSyncExternalStore } from 'react';
import type { WorkflowDefinition } from '../../lib/workflowEditor';
import { isRecord, sameEditorValue } from '../../lib/workspaceAuthoring';

export type WorkflowFieldDraftOwner = readonly ['task' | 'node', string];

export interface WorkflowFieldDraft {
    readonly owner: WorkflowFieldDraftOwner;
    readonly path: readonly string[];
    readonly value: string;
    readonly initial: string;
    readonly baseline: string;
    readonly error: string;
}

interface RepeatRows {
    readonly owner: WorkflowFieldDraftOwner;
    readonly ids: readonly string[];
}

export interface WorkflowFieldDraftSnapshot {
    readonly fields: ReadonlyMap<string, WorkflowFieldDraft>;
    readonly repeatRows: ReadonlyMap<string, RepeatRows>;
}

export function sameWorkflowFieldDrafts(left: WorkflowFieldDraftSnapshot, right: WorkflowFieldDraftSnapshot): boolean {
    return left.fields.size === right.fields.size && left.repeatRows.size === right.repeatRows.size &&
        [...left.fields].every(([key, value]) => right.fields.has(key) && sameEditorValue(value, right.fields.get(key))) &&
        [...left.repeatRows].every(([key, value]) => right.repeatRows.has(key) && sameEditorValue(value, right.repeatRows.get(key)));
}

function ownerKey(owner: WorkflowFieldDraftOwner): string {
    return JSON.stringify(owner);
}

function fieldKey(owner: WorkflowFieldDraftOwner, path: readonly string[]): string {
    return JSON.stringify([...owner, ...path]);
}

function hasPrefix(path: readonly string[], prefix: readonly string[]): boolean {
    return prefix.every((part, index) => path[index] === part);
}

export class WorkflowFieldDraftStore {
    private fields: ReadonlyMap<string, WorkflowFieldDraft> = new Map();
    private repeatRows: ReadonlyMap<string, RepeatRows> = new Map();
    private listeners = new Set<() => void>();
    private revision = 0;
    private nextRowId = 0;
    private batchDepth = 0;
    private batchChanged = false;
    private mutationHandler?: (owner: WorkflowFieldDraftOwner, path: readonly string[], change: () => void) => void;

    subscribe = (listener: () => void) => {
        this.listeners.add(listener);
        return () => { this.listeners.delete(listener); };
    };

    getSnapshot = () => this.revision;

    private notify() {
        if (this.batchDepth) {
            this.batchChanged = true;
            return;
        }
        this.revision++;
        this.listeners.forEach((listener) => listener());
    }

    capture(): WorkflowFieldDraftSnapshot {
        return { fields: this.fields, repeatRows: this.repeatRows };
    }

    restore(snapshot: WorkflowFieldDraftSnapshot) {
        if (this.fields === snapshot.fields && this.repeatRows === snapshot.repeatRows) return;
        this.fields = snapshot.fields;
        this.repeatRows = snapshot.repeatRows;
        for (const rows of snapshot.repeatRows.values()) {
            for (const id of rows.ids) {
                const number = /^field-row-(\d+)$/.exec(id);
                if (number) this.nextRowId = Math.max(this.nextRowId, Number(number[1]));
            }
        }
        this.notify();
    }

    beginBatch() {
        this.batchDepth++;
    }

    endBatch() {
        if (!this.batchDepth) throw new Error('No workflow field transaction is open.');
        this.batchDepth--;
        if (!this.batchDepth && this.batchChanged) {
            this.batchChanged = false;
            this.notify();
        }
    }

    setMutationHandler(handler: typeof this.mutationHandler) {
        this.mutationHandler = handler;
    }

    private mutate(owner: WorkflowFieldDraftOwner, path: readonly string[], change: () => void) {
        if (this.mutationHandler) this.mutationHandler(owner, path, change);
        else change();
    }

    field(owner: WorkflowFieldDraftOwner, path: readonly string[], initialValue: string) {
        const key = fieldKey(owner, path);
        const draft = this.fields.get(key);
        return {
            value: draft?.value ?? initialValue,
            error: draft?.error ?? '',
            setValue: (value: string, error = '') => {
                this.mutate(owner, path, () => {
                    const current = this.fields.get(key);
                    if (current?.value === value && current.error === error) return;
                    const initial = current?.initial ?? initialValue;
                    if (value === initial && !error && (current?.baseline ?? initial) === initial) {
                        if (current) {
                            const fields = new Map(this.fields);
                            fields.delete(key);
                            this.fields = fields;
                            this.notify();
                        }
                        return;
                    }
                    this.fields = new Map(this.fields).set(key, {
                        owner: [owner[0], owner[1]], path: [...path], value, error,
                        initial, baseline: current?.baseline ?? initialValue,
                    });
                    this.notify();
                });
            },
        };
    }

    clear(owner: WorkflowFieldDraftOwner, prefix: readonly string[] = []) {
        this.mutate(owner, prefix, () => {
            const fields = new Map(this.fields);
            for (const [key, draft] of fields) {
                if (ownerKey(draft.owner) === ownerKey(owner) && hasPrefix(draft.path, prefix)) fields.delete(key);
            }
            if (fields.size !== this.fields.size) {
                this.fields = fields;
                this.notify();
            }
        });
    }

    accept(owner: WorkflowFieldDraftOwner, prefix: readonly string[]) {
        this.mutate(owner, prefix, () => {
            const fields = new Map(this.fields);
            let changed = false;
            for (const [key, draft] of fields) {
                if (ownerKey(draft.owner) === ownerKey(owner) && hasPrefix(draft.path, prefix) &&
                    !draft.error && draft.baseline !== draft.value) {
                    fields.set(key, { ...draft, baseline: draft.value });
                    changed = true;
                }
            }
            if (changed) {
                this.fields = fields;
                this.notify();
            }
        });
    }

    acceptSavedFields() {
        const fields = new Map(this.fields);
        let changed = false;
        for (const [key, draft] of fields) {
            if ((hasPrefix(draft.path, ['output', 'schema']) || hasPrefix(draft.path, ['query', 'tags'])) &&
                !draft.error && draft.baseline !== draft.value) {
                fields.set(key, { ...draft, baseline: draft.value });
                changed = true;
            }
        }
        if (changed) {
            this.fields = fields;
            this.notify();
        }
    }

    repeatStateRowIds(owner: WorkflowFieldDraftOwner, count: number): string[] {
        const key = ownerKey(owner);
        const current = this.repeatRows.get(key);
        if (current && current.ids.length >= count) return current.ids.slice(0, count);
        const ids = [...(current?.ids ?? [])];
        while (ids.length < count) ids.push(`field-row-${++this.nextRowId}`);
        this.repeatRows = new Map(this.repeatRows).set(key, { owner: [owner[0], owner[1]], ids });
        return ids.slice();
    }

    removeRepeatStateRow(owner: WorkflowFieldDraftOwner, rowId: string) {
        this.mutate(owner, ['state', rowId], () => {
            const key = ownerKey(owner);
            const rows = this.repeatRows.get(key);
            if (rows?.ids.includes(rowId)) {
                this.repeatRows = new Map(this.repeatRows).set(key, { ...rows, ids: rows.ids.filter((id) => id !== rowId) });
                this.notify();
            }
            this.clear(owner, ['state', rowId]);
        });
    }

    retainOwners(owners: ReadonlySet<string>) {
        const fields = new Map(this.fields);
        const rows = new Map(this.repeatRows);
        for (const [key, draft] of fields) {
            if (!owners.has(ownerKey(draft.owner))) {
                fields.delete(key);
            }
        }
        for (const key of rows.keys()) {
            if (!owners.has(key)) rows.delete(key);
        }
        if (fields.size !== this.fields.size || rows.size !== this.repeatRows.size) {
            this.fields = fields;
            this.repeatRows = rows;
            this.notify();
        }
    }

    reconcile(workflow: WorkflowDefinition) {
        this.retainOwners(workflowDraftOwners(workflow));
        const visited = new Set<object>();
        const visit = (region: unknown) => {
            if (!isRecord(region) || !Array.isArray(region.nodes) || visited.has(region)) return;
            visited.add(region);
            for (const node of region.nodes) {
                if (!isRecord(node) || typeof node.id !== 'string') continue;
                if (node.kind === 'repeat_until' && Array.isArray(node.state)) {
                    this.repeatStateRowIds(['node', node.id], node.state.length);
                }
                if (node.kind === 'if') {
                    visit(node.then);
                    visit(node.else);
                } else if (node.kind === 'for_each' || node.kind === 'repeat_until') visit(node.body);
            }
        };
        visit(workflow.flow);
    }

    summary(owners: ReadonlySet<string>) {
        let pending = false;
        const taskSchemaErrors = new Map<string, string>();
        for (const draft of this.fields.values()) {
            if (!owners.has(ownerKey(draft.owner))) continue;
            pending ||= Boolean(draft.error) || draft.value !== draft.baseline;
            if (draft.owner[0] === 'task' && hasPrefix(draft.path, ['output', 'schema']) && draft.error) {
                taskSchemaErrors.set(draft.owner[1], draft.error);
            }
        }
        return { pending, taskSchemaErrors };
    }
}

const FieldDraftsContext = createContext<WorkflowFieldDraftStore | null>(null);
export const WorkflowFieldDraftsProvider = FieldDraftsContext.Provider;

export function useWorkflowFieldDrafts(): WorkflowFieldDraftStore {
    const store = useContext(FieldDraftsContext);
    if (!store) throw new Error('Workflow authoring fields require WorkflowFieldDraftsProvider.');
    useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot);
    return store;
}

export function workflowDraftOwners(workflow: WorkflowDefinition): Set<string> {
    const owners = new Set(workflow.tasks.filter((task) => task.output_contract)
        .map((task) => ownerKey(['task', task.id])));
    const visited = new Set<object>();
    const visit = (region: unknown) => {
        if (!isRecord(region) || !Array.isArray(region.nodes) || visited.has(region)) return;
        visited.add(region);
        for (const node of region.nodes) {
            if (!isRecord(node) || typeof node.id !== 'string') continue;
            if (node.kind === 'collect' || node.kind === 'repeat_until' ||
                node.kind === 'for_each' && isRecord(node.iterable) && node.iterable.kind === 'workspace_query') {
                owners.add(ownerKey(['node', node.id]));
            }
            if (node.kind === 'if') {
                visit(node.then);
                visit(node.else);
            } else if (node.kind === 'for_each' || node.kind === 'repeat_until') {
                visit(node.body);
            }
        }
    };
    visit(workflow.flow);
    return owners;
}

export function useWorkflowFieldDraftStore(workflow: WorkflowDefinition) {
    const [store] = useState(() => new WorkflowFieldDraftStore());
    const revision = useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot);
    const owners = useMemo(() => workflowDraftOwners(workflow), [workflow]);
    const summary = useMemo(() => store.summary(owners), [store, revision, owners]);
    useEffect(() => { store.retainOwners(owners); }, [store, owners]);
    return { store, ...summary };
}
