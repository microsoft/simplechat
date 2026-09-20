// WorkflowFieldDrafts.tsx
// Session-only raw field buffers; never part of the saved workflow definition.

import { createContext, useContext, useEffect, useMemo, useState, useSyncExternalStore } from 'react';
import type { WorkflowDefinition } from '../../lib/workflowEditor';
import { isRecord } from '../../lib/workspaceAuthoring';

export type WorkflowFieldDraftOwner = readonly ['task' | 'node', string];

interface FieldDraft {
    owner: WorkflowFieldDraftOwner;
    path: readonly string[];
    value: string;
    baseline: string;
    error: string;
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
    private fields = new Map<string, FieldDraft>();
    private repeatRows = new Map<string, { owner: WorkflowFieldDraftOwner; ids: string[] }>();
    private listeners = new Set<() => void>();
    private revision = 0;
    private nextRowId = 0;

    subscribe = (listener: () => void) => {
        this.listeners.add(listener);
        return () => { this.listeners.delete(listener); };
    };

    getSnapshot = () => this.revision;

    private notify() {
        this.revision++;
        this.listeners.forEach((listener) => listener());
    }

    field(owner: WorkflowFieldDraftOwner, path: readonly string[], initialValue: string) {
        const key = fieldKey(owner, path);
        const draft = this.fields.get(key);
        return {
            value: draft?.value ?? initialValue,
            error: draft?.error ?? '',
            setValue: (value: string, error = '') => {
                const current = this.fields.get(key);
                if (current?.value === value && current.error === error) return;
                this.fields.set(key, {
                    owner, path, value, error, baseline: current?.baseline ?? initialValue,
                });
                this.notify();
            },
        };
    }

    clear(owner: WorkflowFieldDraftOwner, prefix: readonly string[] = []) {
        let changed = false;
        for (const [key, draft] of this.fields) {
            if (ownerKey(draft.owner) === ownerKey(owner) && hasPrefix(draft.path, prefix)) {
                this.fields.delete(key);
                changed = true;
            }
        }
        if (changed) this.notify();
    }

    accept(owner: WorkflowFieldDraftOwner, prefix: readonly string[]) {
        let changed = false;
        for (const [key, draft] of this.fields) {
            if (ownerKey(draft.owner) === ownerKey(owner) && hasPrefix(draft.path, prefix) &&
                !draft.error && draft.baseline !== draft.value) {
                this.fields.set(key, { ...draft, baseline: draft.value });
                changed = true;
            }
        }
        if (changed) this.notify();
    }

    acceptSavedFields() {
        let changed = false;
        for (const [key, draft] of this.fields) {
            if ((hasPrefix(draft.path, ['output', 'schema']) || hasPrefix(draft.path, ['query', 'tags'])) &&
                !draft.error && draft.baseline !== draft.value) {
                this.fields.set(key, { ...draft, baseline: draft.value });
                changed = true;
            }
        }
        if (changed) this.notify();
    }

    repeatStateRowIds(owner: WorkflowFieldDraftOwner, count: number): string[] {
        const key = ownerKey(owner);
        const rows = this.repeatRows.get(key) ?? { owner, ids: [] };
        while (rows.ids.length < count) rows.ids.push(`field-row-${++this.nextRowId}`);
        this.repeatRows.set(key, rows);
        return rows.ids.slice(0, count);
    }

    removeRepeatStateRow(owner: WorkflowFieldDraftOwner, rowId: string) {
        const rows = this.repeatRows.get(ownerKey(owner));
        if (rows) rows.ids = rows.ids.filter((id) => id !== rowId);
        this.clear(owner, ['state', rowId]);
    }

    retainOwners(owners: ReadonlySet<string>) {
        let changed = false;
        for (const [key, draft] of this.fields) {
            if (!owners.has(ownerKey(draft.owner))) {
                this.fields.delete(key);
                changed = true;
            }
        }
        for (const key of this.repeatRows.keys()) {
            if (!owners.has(key)) this.repeatRows.delete(key);
        }
        if (changed) this.notify();
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

function workflowDraftOwners(workflow: WorkflowDefinition): Set<string> {
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
