// workspaceEditorDrafts.ts
// Drafts live only in this tab's memory, and only while they contain unsaved changes.

import { useCallback, useState, type Dispatch, type SetStateAction } from 'react';
import { useBootstrapStore } from '../stores/bootstrapStore';
import {
    agentEditorReturnPath,
    GLOBAL_AGENT_RETURN_SCOPE,
    sameEditorValue,
    type ActionConfiguration,
    type AgentConfiguration,
    type AgentEditorReturnScope,
    type AuthoringResource,
} from './workspaceAuthoring';

type Configuration = AgentConfiguration | ActionConfiguration;
type EditorKind = 'agents' | 'actions';

/**
 * Which workspace a draft belongs to. Personal is the default and, to keep personal behaviour
 * byte-identical, contributes nothing to the cache key. A group scope adds its id, so a draft
 * opened in group A can never be restored into group B or into personal scope -- the isolation
 * the created-action handoff needs too. The global scope is the administrator's own partition for
 * global agents and actions edited from Admin Settings.
 */
export type EditorWorkspaceScope =
    | { kind: 'personal' }
    | { kind: 'group'; id: string }
    | { kind: 'global' };

const PERSONAL_EDITOR_SCOPE: EditorWorkspaceScope = { kind: 'personal' };

function editorScopeSegments(scope: EditorWorkspaceScope): string[] {
    if (scope.kind === 'group') return ['group', scope.id];
    return scope.kind === 'global' ? ['global'] : [];
}

/** The return-path scope `agentEditorReturnPath` checks a handed-off action against. */
function returnPathScope(scope: EditorWorkspaceScope): AgentEditorReturnScope | undefined {
    if (scope.kind === 'group') return scope.id;
    return scope.kind === 'global' ? GLOBAL_AGENT_RETURN_SCOPE : undefined;
}

interface DraftState<T extends Configuration> {
    draft: T;
    baseline: T;
    original: AuthoringResource<T> | null;
}

const drafts = new Map<string, DraftState<Configuration>>();
const createdActions = new Map<string, ActionConfiguration>();
// The drafted-action placeholder a seeded new-action editor will replace once it saves.
const actionHandoffs = new Map<string, string>();
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
        actionHandoffs.clear();
        draftOwner = owner;
        syncDraftUnloadProtection();
    }
    return owner;
}

export function clearWorkspaceEditorDrafts(): void {
    drafts.clear();
    createdActions.clear();
    actionHandoffs.clear();
    syncDraftUnloadProtection();
}

export function useWorkspaceEditorDraft<T extends Configuration>(
    kind: EditorKind,
    key: string,
    createDraft: () => T,
    workspaceScope: EditorWorkspaceScope = PERSONAL_EDITOR_SCOPE,
): {
    draft: T;
    setDraft: Dispatch<SetStateAction<T>>;
    original: AuthoringResource<T> | null;
    load: (resource: AuthoringResource<T>) => void;
    clear: () => void;
    dirty: boolean;
    restored: boolean;
} {
    const cacheKey = JSON.stringify([ownerKey(), ...editorScopeSegments(workspaceScope), kind, key]);
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

export function queueCreatedWorkspaceAction(
    returnPath: string,
    action: ActionConfiguration,
    workspaceScope: EditorWorkspaceScope = PERSONAL_EDITOR_SCOPE,
): void {
    if (!agentEditorReturnPath(returnPath, returnPathScope(workspaceScope))) throw new Error('Invalid agent editor return path.');
    createdActions.set(JSON.stringify([ownerKey(), ...editorScopeSegments(workspaceScope), returnPath]), action);
    syncDraftUnloadProtection();
}

/**
 * Opens the new-action editor that returns to ``returnPath`` with ``draft`` already filled in,
 * such as an action Ask AI drafted for an agent. ``baseline`` is the editor's empty action, so
 * the seeded draft counts as unsaved. The key matches the one the action editor builds.
 * ``handoff`` is the agent's placeholder reference the saved action replaces; it is recorded here
 * rather than in the agent draft because the agent editor unmounts as it navigates away.
 */
export function seedNewWorkspaceActionDraft(
    returnPath: string,
    draft: ActionConfiguration,
    baseline: ActionConfiguration,
    workspaceScope: EditorWorkspaceScope = PERSONAL_EDITOR_SCOPE,
    handoff = '',
): string {
    const path = agentEditorReturnPath(returnPath, returnPathScope(workspaceScope));
    if (!path) throw new Error('Invalid agent editor return path.');
    const key = JSON.stringify(['personal', 'new', path]);
    drafts.set(JSON.stringify([ownerKey(), ...editorScopeSegments(workspaceScope), 'actions', key]),
        { draft: structuredClone(draft), baseline, original: null });
    const handoffKey = JSON.stringify([ownerKey(), ...editorScopeSegments(workspaceScope), path]);
    if (handoff) actionHandoffs.set(handoffKey, handoff);
    else actionHandoffs.delete(handoffKey);
    syncDraftUnloadProtection();
    return path;
}

/** Forgets a drafted-action handoff, as when the person starts an unrelated new action. */
export function clearWorkspaceActionHandoff(
    returnPath: string,
    workspaceScope: EditorWorkspaceScope = PERSONAL_EDITOR_SCOPE,
): void {
    actionHandoffs.delete(JSON.stringify([ownerKey(), ...editorScopeSegments(workspaceScope), returnPath]));
}

export function takeCreatedWorkspaceAction(
    returnPath: string,
    workspaceScope: EditorWorkspaceScope = PERSONAL_EDITOR_SCOPE,
): ActionConfiguration | null {
    const key = JSON.stringify([ownerKey(), ...editorScopeSegments(workspaceScope), returnPath]);
    const action = createdActions.get(key);
    createdActions.delete(key);
    syncDraftUnloadProtection();
    return action ?? null;
}

/** Takes, once, the drafted-action placeholder a just-created action should replace. */
export function takeWorkspaceActionHandoff(
    returnPath: string,
    workspaceScope: EditorWorkspaceScope = PERSONAL_EDITOR_SCOPE,
): string {
    const key = JSON.stringify([ownerKey(), ...editorScopeSegments(workspaceScope), returnPath]);
    const handoff = actionHandoffs.get(key) ?? '';
    actionHandoffs.delete(key);
    return handoff;
}
