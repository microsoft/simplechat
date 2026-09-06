// workspaceEditorDrafts.ts
// Drafts live only in this tab's memory, and only while they contain unsaved changes.

import { useCallback, useState, type Dispatch, type SetStateAction } from 'react';
import { useBootstrapStore } from '../stores/bootstrapStore';
import {
    agentEditorReturnPath,
    sameEditorValue,
    type ActionConfiguration,
    type AgentConfiguration,
    type AuthoringResource,
} from './workspaceAuthoring';

type Configuration = AgentConfiguration | ActionConfiguration;
type EditorKind = 'agents' | 'actions';

interface DraftState<T extends Configuration> {
    draft: T;
    baseline: T;
    original: AuthoringResource<T> | null;
}

const drafts = new Map<string, DraftState<Configuration>>();
const createdActions = new Map<string, ActionConfiguration>();
let draftOwner = '';

function warnBeforeDraftUnload(event: BeforeUnloadEvent): void {
    event.preventDefault();
    event.returnValue = '';
}

function syncDraftUnloadProtection(): void {
    if (typeof window === 'undefined') return;
    if (drafts.size || createdActions.size) {
        window.addEventListener('beforeunload', warnBeforeDraftUnload);
    } else {
        window.removeEventListener('beforeunload', warnBeforeDraftUnload);
    }
}

function ownerKey(): string {
    const owner = useBootstrapStore.getState().data?.user?.id ?? '';
    if (owner !== draftOwner) {
        drafts.clear();
        createdActions.clear();
        draftOwner = owner;
        syncDraftUnloadProtection();
    }
    return owner;
}

export function clearWorkspaceEditorDrafts(): void {
    drafts.clear();
    createdActions.clear();
    syncDraftUnloadProtection();
}

export function useWorkspaceEditorDraft<T extends Configuration>(
    kind: EditorKind,
    key: string,
    createDraft: () => T,
): {
    draft: T;
    setDraft: Dispatch<SetStateAction<T>>;
    original: AuthoringResource<T> | null;
    load: (resource: AuthoringResource<T>) => void;
    clear: () => void;
    dirty: boolean;
    restored: boolean;
} {
    const cacheKey = JSON.stringify([ownerKey(), kind, key]);
    const [restored] = useState(() => drafts.has(cacheKey));
    const [state, setState] = useState<DraftState<T>>(() => {
        // The kind and resource key always identify the same concrete draft type.
        const saved = drafts.get(cacheKey) as DraftState<T> | undefined;
        if (saved) return saved;
        const initial = createDraft();
        return { draft: structuredClone(initial), baseline: initial, original: null };
    });

    const setDraft: Dispatch<SetStateAction<T>> = useCallback((update) => setState((current) => {
        const draft = typeof update === 'function' ? update(current.draft) : update;
        if (sameEditorValue(current.draft, draft)) return current;
        const next = { ...current, draft };
        if (sameEditorValue(next.baseline, draft)) drafts.delete(cacheKey);
        else drafts.set(cacheKey, next);
        syncDraftUnloadProtection();
        return next;
    }), [cacheKey]);

    const load = useCallback((resource: AuthoringResource<T>) => {
        drafts.delete(cacheKey);
        syncDraftUnloadProtection();
        setState({
            draft: structuredClone(resource.record),
            baseline: structuredClone(resource.record),
            original: resource,
        });
    }, [cacheKey]);

    const clear = useCallback(() => {
        drafts.delete(cacheKey);
        syncDraftUnloadProtection();
        setState((current) => sameEditorValue(current.draft, current.baseline)
            ? current : { ...current, draft: structuredClone(current.baseline) });
    }, [cacheKey]);

    return {
        draft: state.draft,
        setDraft,
        original: state.original,
        restored,
        dirty: !sameEditorValue(state.baseline, state.draft),
        load,
        clear,
    };
}

export function queueCreatedWorkspaceAction(returnPath: string, action: ActionConfiguration): void {
    if (!agentEditorReturnPath(returnPath)) throw new Error('Invalid agent editor return path.');
    createdActions.set(JSON.stringify([ownerKey(), returnPath]), action);
    syncDraftUnloadProtection();
}

export function takeCreatedWorkspaceAction(returnPath: string): ActionConfiguration | null {
    const key = JSON.stringify([ownerKey(), returnPath]);
    const action = createdActions.get(key);
    createdActions.delete(key);
    syncDraftUnloadProtection();
    return action ?? null;
}
