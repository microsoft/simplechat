// groupWorkspaceStore.ts
// Explicit page context is separate from the account's saved active group.

import { create } from 'zustand';
import { ApiError } from '../lib/apiClient';
import { fetchGroupWorkspaceContext, requireWorkspaceId, type GroupWorkspaceContext } from '../lib/workspaceContext';
import { GROUP_WORKSPACES } from '../lib/workspaces';
import { useBootstrapStore } from './bootstrapStore';

export class WorkspaceRequestSuperseded extends Error {
    constructor() {
        super('Workspace selection or sign-in changed while loading.');
        this.name = 'WorkspaceRequestSuperseded';
    }
}

type ActivationResult =
    | { status: 'cancelled' }
    | { status: 'activated'; context: GroupWorkspaceContext };

interface GroupWorkspaceState {
    context: GroupWorkspaceContext | null;
    pendingGroupId: string | null;
    loading: boolean;
    refreshing: boolean;
    needsRevalidation: boolean;
    activating: boolean;
    needsReconciliation: boolean;
    error: string | null;
    load: (groupId: string) => Promise<GroupWorkspaceContext>;
    revalidate: (groupId: string) => Promise<GroupWorkspaceContext>;
    activate: (groupId: string, confirmLeave: () => boolean | Promise<boolean>) => Promise<ActivationResult>;
    reconcile: () => Promise<GroupWorkspaceContext | null>;
    clear: () => void;
}

const EMPTY_STATE = {
    context: null,
    pendingGroupId: null,
    loading: false,
    refreshing: false,
    needsRevalidation: false,
    activating: false,
    needsReconciliation: false,
    error: null,
};

let sequence = 0;
let readController: AbortController | null = null;
let switchInFlight = false;

function currentViewer(): string {
    const bootstrap = useBootstrapStore.getState();
    if (bootstrap.authExpired || !bootstrap.data?.user?.id) {
        throw new Error('Sign in again before selecting a workspace.');
    }
    return requireWorkspaceId(bootstrap.data.user.id);
}

function assertCurrent(token: number, viewerId: string): void {
    const bootstrap = useBootstrapStore.getState();
    if (token !== sequence || bootstrap.authExpired || bootstrap.data?.user?.id !== viewerId) {
        throw new WorkspaceRequestSuperseded();
    }
}

function beginRead(): { token: number; signal: AbortSignal } {
    readController?.abort();
    readController = new AbortController();
    return { token: ++sequence, signal: readController.signal };
}

function failureMessage(cause: unknown, fallback: string): string {
    if (cause instanceof ApiError) {
        if (cause.status === 401) return 'Your session has expired. Sign in again.';
        if (cause.status === 403) return 'You no longer have permission to access that group.';
        if (cause.status === 404) return 'That group no longer exists.';
    }
    return fallback;
}

export const useGroupWorkspaceStore = create<GroupWorkspaceState>((set, get) => ({
    ...EMPTY_STATE,

    clear: () => {
        ++sequence;
        readController?.abort();
        readController = null;
        // A reset cannot cancel a PATCH that the server may already be processing.
        set({ ...EMPTY_STATE });
    },

    load: async (groupId) => {
        if (switchInFlight || get().needsReconciliation) {
            throw new Error('Finish or reconcile the current workspace switch before loading another group.');
        }
        const viewerId = currentViewer();
        requireWorkspaceId(groupId);
        const { token, signal } = beginRead();
        set({ ...EMPTY_STATE, loading: true, pendingGroupId: groupId });
        try {
            const context = await fetchGroupWorkspaceContext(groupId, viewerId, signal);
            assertCurrent(token, viewerId);
            set({ context, loading: false, pendingGroupId: null });
            return context;
        } catch (cause) {
            assertCurrent(token, viewerId);
            const message = failureMessage(cause, 'Could not load this workspace. Please retry.');
            set({ loading: false, pendingGroupId: null, error: message });
            throw new Error(message, { cause });
        }
    },

    revalidate: async (groupId) => {
        if (switchInFlight || get().needsReconciliation) {
            throw new Error('Finish or reconcile the current workspace switch before refreshing.');
        }
        const viewerId = currentViewer();
        const previous = get().context;
        if (previous?.scope.id !== groupId || previous.viewer_id !== viewerId) {
            throw new Error('Load the selected workspace before refreshing its details.');
        }
        const { token, signal } = beginRead();
        set({ refreshing: true, error: null });
        try {
            const context = await fetchGroupWorkspaceContext(groupId, viewerId, signal);
            assertCurrent(token, viewerId);
            set({ context, refreshing: false, needsRevalidation: false });
            return context;
        } catch (cause) {
            assertCurrent(token, viewerId);
            const denied = cause instanceof ApiError && [401, 403, 404].includes(cause.status);
            const message = failureMessage(cause, 'Workspace access could not be refreshed. Your changes are kept; retry before saving.');
            set({
                context: denied ? null : previous, refreshing: false,
                needsRevalidation: !denied, error: message,
            });
            throw new Error(message, { cause });
        }
    },

    activate: async (groupId, confirmLeave) => {
        if (switchInFlight) throw new Error('A workspace switch is already in progress.');
        if (get().needsReconciliation) throw new Error('Refresh the active workspace before trying another switch.');
        const viewerId = currentViewer();
        requireWorkspaceId(groupId);
        const previous = get().context;
        const { token, signal } = beginRead();
        switchInFlight = true;
        let writeStarted = false;
        let writeAcknowledged = false;
        set({ activating: true, loading: false, refreshing: false, pendingGroupId: groupId, error: null });
        try {
            const leave = await confirmLeave();
            assertCurrent(token, viewerId);
            if (!leave) return { status: 'cancelled' };
            await fetchGroupWorkspaceContext(groupId, viewerId, signal);
            assertCurrent(token, viewerId);
            writeStarted = true;
            await GROUP_WORKSPACES.setActive(groupId);
            writeAcknowledged = true;
            assertCurrent(token, viewerId);
            const bootstrap = await useBootstrapStore.getState().refreshRequired(viewerId);
            assertCurrent(token, viewerId);
            if (bootstrap.scope?.active_group_id !== groupId) {
                throw new Error('The active group changed during selection.');
            }
            const context = await fetchGroupWorkspaceContext(groupId, viewerId, signal);
            assertCurrent(token, viewerId);
            if (useBootstrapStore.getState().data?.scope?.active_group_id !== groupId) {
                throw new Error('The active group changed while loading workspace details.');
            }
            set({ context, needsReconciliation: false, needsRevalidation: false });
            return { status: 'activated', context };
        } catch (cause) {
            assertCurrent(token, viewerId);
            const rejectedWrite = !writeAcknowledged && cause instanceof ApiError
                && [400, 401, 403, 404].includes(cause.status);
            const needsReconciliation = writeStarted && !rejectedWrite;
            const message = needsReconciliation
                ? 'The active group could not be confirmed. Refresh the workspace selection before continuing.'
                : failureMessage(cause, 'Could not switch workspaces. Your previous selection has been kept.');
            set({
                context: needsReconciliation || (cause instanceof ApiError && cause.status === 401) ? null : previous,
                needsReconciliation,
                error: message,
            });
            throw new Error(message, { cause });
        } finally {
            switchInFlight = false;
            if (token === sequence) set({ activating: false, pendingGroupId: null });
        }
    },

    reconcile: async () => {
        if (switchInFlight) throw new Error('Wait for the current workspace switch to finish.');
        const viewerId = currentViewer();
        const { token, signal } = beginRead();
        set({ context: null, loading: true, refreshing: false, needsRevalidation: false, needsReconciliation: true, error: null });
        try {
            // Recovery is read-only: never replay an ambiguously acknowledged mutation.
            const bootstrap = await useBootstrapStore.getState().refreshRequired(viewerId);
            assertCurrent(token, viewerId);
            const groupId = bootstrap.scope?.active_group_id;
            const context = groupId
                ? await fetchGroupWorkspaceContext(groupId, viewerId, signal)
                : null;
            assertCurrent(token, viewerId);
            if (useBootstrapStore.getState().data?.scope?.active_group_id !== groupId) {
                throw new Error('The active group changed while refreshing workspace details.');
            }
            set({ ...EMPTY_STATE, context });
            return context;
        } catch (cause) {
            assertCurrent(token, viewerId);
            const message = failureMessage(cause, 'Could not confirm the active workspace. Please retry.');
            set({ loading: false, pendingGroupId: null, error: message, needsReconciliation: true });
            throw new Error(message, { cause });
        }
    },
}));

useBootstrapStore.subscribe((state, previous) => {
    if (state.data?.user?.id !== previous.data?.user?.id || (state.authExpired && !previous.authExpired)) {
        useGroupWorkspaceStore.getState().clear();
    }
});
